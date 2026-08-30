"""What the *engine binary* accepts, as data - the INI surface a patched `game.dat` has that a
stock one does not.

A binary patch (see `sage_patch`) can teach the engine INI it could not read before: a new field
on a block, a new token in a name table, a raised limit, or a field it now ignores. The typed
model in `sage_ini.model` describes the **stock** engine, so on a patched game every one of those
reads as a mistake - an unknown attribute, an unknown enum token, a slot past the array.

An `Engine` is that difference, written down. It is inert data: load one from a `.sagepatch` file
(`load_engine`), build one in code, merge several, compare or serialize them. `apply()` is what
makes the model agree with it.

It carries one thing the model never reads: `patches`, the list of binary patches the `game.dat`
was built from, each with the parameters it was built with (see `AppliedPatch`). Most patches
change no INI at all, so the surface deltas alone describe only a fraction of a build; with the
list, the same committed file is also the manifest that says what the binary *is* and that
`sage-patch rebuild` can replay onto a clean one.

## Applying is process-wide, and deliberately so

The model's schema is flattened onto the classes themselves (`IniObject._fieldspec`) and enum
members live on the enum classes; both are read straight off the class by every consumer - the
lint rules, `Xref`, `primer`, `rename`, the language server. Injecting there is what makes a
patched field simply *work* everywhere instead of needing each consumer to learn about engines.

The cost is that applying an engine mutates global state: one engine is active at a time,
`apply()` replaces whatever was active, and the deltas stay applied after a load returns (they
have to - conversion is lazy, so a field is typed when something reads it, long after the load).
`activate()` is the scoped form for tests and for a caller that wants the old state back.

For the same reason there is no `Game.engine`: an engine is process state, not per-game state, so
a rule asking what the engine allows calls `active()` - which is by construction the same engine
the model itself is typed against, and cannot drift from it.

## Failure is a warning, never an exception

Per CONVENTIONS.md rule 4, nothing here raises on bad input. A malformed file, an unknown key, a
delta naming a block that does not exist, a type spelling out of the grammar - each becomes a
message in `Engine.warnings` or in the list `apply()` returns, and the rest still loads.
"""

import enum as _enum
import textwrap
import tomllib
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import sage_ini.model.definitions  # noqa: F401  (populate the class registry)
from sage_ini.model import enums as _enums
from sage_ini.model import types as _types
from sage_ini.model.objects import REGISTRY, IniObject, rebuild_schema_tree
from sage_ini.parser.diagnostics import Diagnostics, Severity
from sage_ini.parser.location import Span

__all__ = [
    "FORMAT_VERSION",
    "SAGEPATCH_NAME",
    "STOCK",
    "STOCK_LIMITS",
    "AppliedPatch",
    "BlockDelta",
    "Engine",
    "EnumDelta",
    "FieldDelta",
    "LimitDelta",
    "NestedDelta",
    "NoopDelta",
    "Source",
    "active",
    "apply_engine",
    "dump_engine",
    "load_engine",
    "parse_engine",
    "parse_type",
    "revert",
    "type_names",
]

#: The `.sagepatch` schema version this module writes and understands. A file from a newer
#: generator still loads: unknown sections and keys warn and are skipped. Version 2 added the
#: `[[patches]]` manifest, which a version-1 reader skips as an unknown section - so a v2 file
#: still describes the same INI surface to it, minus the provenance it never knew to look for.
#: Version 3 added `[[nested]]`, the same way: an older reader loses the sub-blocks a patch let a
#: block contain, and everything else about the file still reads.
FORMAT_VERSION = 3

#: The file `sage_patch sagepatch` writes and `sage_lint` looks for beside `.sagelint`.
SAGEPATCH_NAME = ".sagepatch"

#: Engine ceilings the stock build imposes, and what a rule sees when no engine is applied. A
#: patch raises one by naming it in `[[limits]]`; a name absent here is not a limit this version
#: knows and is skipped with a warning, so an older reader survives a newer file.
STOCK_LIMITS: dict[str, int] = {
    # `CommandSet`'s `m_command[]` array: how many buttons one set may *define*. The
    # commandset-limit patch raises it.
    "commandset.max_slots": 33,
    # How many buttons the ControlBar can draw at once - a fixed-size UI array, untouched by the
    # patch that raises the slot count. Listed so a future patch that does widen it has a name.
    "commandset.max_visible_buttons": 33,
}


@dataclass(frozen=True, slots=True)
class AppliedPatch:
    """One binary patch a `game.dat` carries, with the parameters it was built with.

    Every other record here describes INI the patched engine now accepts; this one describes the
    **binary**, and it is written down whether or not the patch touches the INI at all. Most
    patches do not - a crash dumper, an observer camera, a launcher fix add no field and no token
    - so a file holding only the surface deltas silently omits most of what a build is made of.

    Recorded, the list is the build manifest: what is in this binary, at which count, under which
    keyword, by whom. `sage-patch rebuild` replays it onto a clean binary, `sage-patch sagepatch
    --check` fails when the binary stops matching it, and a reader with none of this installed can
    still open the file and see what the engine they are modding has been taught.

    `options` are the constructor keyword arguments that rebuild the patch, sorted by name so the
    file diffs cleanly; a parameter left at its default is written down too, because a manifest
    that omits it stops being a manifest the day the default changes. A list-valued option is a
    tuple here and a TOML array in the file."""

    name: str
    options: tuple[tuple[str, object], ...] = ()
    #: Whether the patch is one of the unstable, largely untested ones.
    experimental: bool = False
    #: Who worked out the patch, for the credit line a mod shipping the binary owes them.
    author: str = ""
    #: What the patch does, so the committed file reads as a reference on its own. Written into
    #: the file as the comment lines above the entry, because it is prose about a patch rather
    #: than a fact about the binary: it is not read back by `parse_engine`, and `differences`
    #: does not compare it, so rewording one never reads as drift.
    description: str = ""

    @property
    def settings(self) -> dict[str, object]:
        """`options` as the keyword-argument mapping that rebuilds the patch."""
        return dict(self.options)


@dataclass(frozen=True, slots=True)
class Source:
    """Where an engine description came from, for provenance and drift checks. Informational
    only - nothing in the model reads it - but it is what tells a mod team that the committed
    `.sagepatch` was generated from a different binary than the one they are running.

    Every field here has to be worth committing, because `.sagepatch` lives in the mod's
    repository. `sha256` identifies the binary exactly and `generated` says how stale the file is;
    a **path** identifies nothing either of them does not - two machines with the same layout
    produce the same string for different binaries - while writing a home directory into a tracked
    file and churning its diff on every rebuild elsewhere. There used to be a `game_dat` key here
    for that; a file still carrying one loads fine and simply drops it."""

    build: str = ""  # the engine build string, e.g. "2.01.2614.37001"
    sha256: str = ""  # of the game.dat it was generated from
    generator: str = ""  # what wrote it, e.g. "sage_patch 0.1.0"
    generated: str = ""  # ISO date


@dataclass(frozen=True, slots=True)
class FieldDelta:
    """What a field is in the patched engine. `type` is a spelling from the grammar `parse_type`
    accepts; `default` is what the block reads when the field is absent, matching the patch's
    own default so an unmodified mod converts the way it runs.

    Usually that means a field the patch **added**. It also covers a field the stock engine
    already had whose *type* the patch changed - a keyword that took one name and now takes a
    list - because the model only ever holds one converter per field and this is it either
    way."""

    block: str
    name: str
    type: str
    default: object = None
    patch: str = ""


@dataclass(frozen=True, slots=True)
class NoopDelta:
    """A field the patched engine still parses but no longer acts on.

    This is how a *removed* field is expressed, and the indirection is on purpose: dropping the
    field from the schema would turn every use into `unknown-attribute` ("not a known attribute
    of SpecialPower"), which misdescribes what happened and hides it among the coverage backlog.
    Kept known and marked, it converts as before and earns its own `patched-out-field` message
    saying what the patch did to it."""

    block: str
    name: str
    reason: str = ""
    patch: str = ""


@dataclass(frozen=True, slots=True)
class BlockDelta:
    """A **block type** the patched engine registers, or stops registering.

    Every other delta here changes what a known block accepts. This one changes which blocks
    exist at all, which is what a patch that touches the engine's `ModuleFactory` does: it can
    register a name the stock build never had, and - because the cheap way to add a module is to
    adopt one nothing uses - it can take a stock name away in the same move.

    `base` names the block the new one inherits from, so a new behaviour module starts with the
    fields every module slot has rather than an empty schema; it is ignored when `removed`.
    Removal is deliberately *not* spelled as a `NoopDelta`: a `NoopDelta` says a keyword is
    parsed and ignored, whereas a block the factory no longer registers is an INI parse error
    for the whole block, and the two deserve different messages."""

    name: str
    base: str = "Behavior"
    removed: bool = False
    patch: str = ""


@dataclass(frozen=True, slots=True)
class NestedDelta:
    """A **sub-block** the patched engine lets a block contain: `block` is the parent, `name` the
    keyword the child opens under, and `type` the block type it parses as (defaulting to `name`).

    Distinct from `FieldDelta` because a nested block is not a field: it has its own schema and
    its own diagnostics, and the model keeps the two in separate maps. Distinct from `BlockDelta`
    because registering a block type says the type *exists*, not where it may appear - a patch
    that adds an Act verb has to do both, and only the pair makes the sub-block legal where it is
    actually written."""

    block: str
    name: str
    type: str = ""
    patch: str = ""

    @property
    def child(self) -> str:
        """The block type this nests, which is `name` unless `type` overrides it."""
        return self.type or self.name


@dataclass(frozen=True, slots=True)
class EnumDelta:
    """A token a patch added to one of the engine's name tables (a model condition, a weapon-set
    flag, a locomotor set, a weather). `value` is the index the binary gives it, or None to let
    the member take the next free one."""

    enum: str
    name: str
    value: int | None = None
    patch: str = ""


@dataclass(frozen=True, slots=True)
class LimitDelta:
    """An engine ceiling a patch raised, named from `STOCK_LIMITS`."""

    name: str
    value: int
    patch: str = ""


@dataclass(frozen=True, slots=True)
class Engine:
    """The INI surface of one engine binary, as a difference from the stock build.

    An empty `Engine` (`STOCK`) is the stock engine: applying it is what reverts every delta.
    Instances are immutable and comparable, so a generated one can be diffed against a committed
    one to detect drift."""

    #: The patches the binary carries - the build manifest, independent of whether any of them
    #: changes the INI surface below. Nothing in the model reads it; see :class:`AppliedPatch`.
    patches: tuple[AppliedPatch, ...] = ()
    blocks: tuple[BlockDelta, ...] = ()
    nested: tuple[NestedDelta, ...] = ()
    fields: tuple[FieldDelta, ...] = ()
    noops: tuple[NoopDelta, ...] = ()
    enum_members: tuple[EnumDelta, ...] = ()
    limits: tuple[LimitDelta, ...] = ()
    source: Source = field(default_factory=Source)
    #: Problems found while loading this description (bad TOML, unknown keys, wrong types).
    #: Carried rather than raised, for the caller to report alongside its own diagnostics.
    warnings: tuple[str, ...] = ()

    @property
    def is_stock(self) -> bool:
        """Whether this adds nothing to the INI the stock engine accepts (no deltas of any kind).

        About the *surface*, not the binary: a build made entirely of patches that change no INI
        is stock by this measure and still lists its `patches`, which is the distinction the
        manifest exists to make."""
        return not (
            self.blocks
            or self.nested
            or self.fields
            or self.noops
            or self.enum_members
            or self.limits
        )

    def limit(self, name: str) -> int:
        """The value of engine limit `name` - this engine's, else the stock ceiling. Raises
        `KeyError` for a name no version of this module defines, which is a caller bug; a limit
        that merely fails to *load* from a file was already dropped with a warning."""
        for delta in self.limits:
            if delta.name == name:
                return delta.value
        return STOCK_LIMITS[name]

    def merge(self, *others: "Engine") -> "Engine":
        """This engine plus `others`, later ones winning per (block, field), (enum, token) and
        limit name. The merged `source` is the last non-empty one; warnings accumulate."""
        merged = self
        for other in others:
            merged = replace(
                merged,
                patches=_last_wins(merged.patches, other.patches, lambda d: d.name),
                blocks=_last_wins(merged.blocks, other.blocks, lambda d: d.name),
                nested=_last_wins(merged.nested, other.nested, lambda d: (d.block, d.name)),
                fields=_last_wins(merged.fields, other.fields, lambda d: (d.block, d.name)),
                noops=_last_wins(merged.noops, other.noops, lambda d: (d.block, d.name)),
                enum_members=_last_wins(
                    merged.enum_members, other.enum_members, lambda d: (d.enum, d.name)
                ),
                limits=_last_wins(merged.limits, other.limits, lambda d: d.name),
                source=other.source if other.source != Source() else merged.source,
                warnings=merged.warnings + other.warnings,
            )
        return merged

    def apply(self) -> list[str]:
        """Make the typed model describe this engine, replacing whatever engine was active.

        Returns the problems that stopped a delta from landing (an empty list == everything
        applied). Process-wide and idempotent; see the module docstring."""
        revert()
        problems: list[str] = []
        undo: list[Callable[[], None]] = []
        for block in self.blocks:
            problems.extend(_apply_block(block, undo))
        for nested in self.nested:
            problems.extend(_apply_nested(nested, undo))
        for delta in self.fields:
            problems.extend(_apply_field(delta, undo))
        for noop in self.noops:
            problems.extend(_apply_noop(noop, undo))
        for member in self.enum_members:
            problems.extend(_apply_enum_member(member, undo))
        for limit in self.limits:
            if limit.name not in STOCK_LIMITS:
                problems.append(f"unknown engine limit {limit.name!r} (ignored)")
        global _active, _undo
        _active = self
        _undo = undo
        return problems

    @contextmanager
    def activate(self) -> Iterator[list[str]]:
        """Apply this engine for the duration of the block, then restore what was active
        before. The scoped form of `apply`, for tests and for any caller that must not leave
        the model mutated."""
        previous = active()
        problems = self.apply()
        try:
            yield problems
        finally:
            previous.apply()


#: The unpatched engine. `STOCK.apply()` restores the model to its stock schema.
STOCK = Engine()

_active: Engine = STOCK
_undo: list[Callable[[], None]] = []


def active() -> Engine:
    """The engine currently applied to the model - `STOCK` when none has been."""
    return _active


def revert() -> None:
    """Undo the active engine, returning the model to the stock schema."""
    global _active, _undo
    for undo in reversed(_undo):
        undo()
    _undo = []
    _active = STOCK


def apply_engine(engine: "Engine | None", diagnostics: Diagnostics, span: Span) -> None:
    """Apply `engine` (None does nothing) and file everything it has to say - the warnings from
    loading it and whatever failed to apply - as `engine-config` diagnostics at `span`.

    The one place a tool needs: a bad `.sagepatch` then degrades to the stock engine plus a
    message in the same report as every other problem, instead of raising (CONVENTIONS.md
    rule 4)."""
    if engine is None:
        return
    for message in (*engine.warnings, *engine.apply()):
        diagnostics.add("engine-config", message, span, Severity.WARNING)


def _last_wins[T](left: tuple[T, ...], right: tuple[T, ...], key) -> tuple[T, ...]:
    """`left` then `right`, keeping each key's last entry in first-seen order."""
    merged: dict[object, T] = {}
    for item in (*left, *right):
        merged[key(item)] = item
    return tuple(merged.values())


# The scalar spellings a `.sagepatch` may name, mapped to the model's own annotations. Kept as an
# explicit table rather than a lookup into the types module: a field type arrives from a file, so
# what it can name is a whitelist, never whatever attribute happens to exist.
_SCALARS: dict[str, object] = {
    "Bool": _types.Bool,
    "Int": _types.Int,
    "Float": _types.Float,
    "String": _types.String,
    "Label": _types.Label,
    "Opaque": _types.Opaque,
    "ModuleTag": _types.ModuleTag,
    "ObjectFilter": _types.ObjectFilter,
}


# `List` and `FlagList` are two things at once (see `sage_ini.model.types`): a plain `list`
# annotation to a type checker, and a converter builder at runtime, subscripted with the element
# type. Only the runtime meaning applies here - the element is a value, not a static type - so
# they are taken as such.
_LIST: Any = _types.List
_FLAG_LIST: Any = _types.FlagList


def _enum_classes() -> dict[str, type[_enum.Enum]]:
    """The model's enum classes by name, the set `Enum:`/`Flags:` may name."""
    found: dict[str, type[_enum.Enum]] = {}
    for name, value in vars(_enums).items():
        if not isinstance(value, type) or not issubclass(value, _enums.BFMEEnum):
            continue
        if value in (_enums.BFMEEnum, _enums.CaseInsensitiveEnum):
            continue
        found[name] = value
    return found


def type_names() -> list[str]:
    """Every type spelling the grammar accepts, for a CLI listing and error messages. The
    parametrized forms are shown with a placeholder."""
    scalars = sorted(_SCALARS)
    return [
        *scalars,
        *(f"{name}[]" for name in scalars),
        "Ref:<table>",
        "Ref[]:<table>",
        "Enum:<E>",
        "Enum[]:<E>",
        "Flags:<E>",
    ]


def parse_type(spec: str) -> tuple[object | None, str]:
    """The converter a type spelling names, as `(converter, error)` - exactly one is set.

    The grammar is small and closed: a scalar (`Int`), a list of one (`Int[]`), a cross-reference
    to a Game table as one name or several (`Ref:upgrades`, `Ref[]:upgrades` - the second is what
    an upgrade mask like `TriggeredBy` is), or an enum as a scalar, a list or a whole-set flag list
    (`Enum:ModelCondition`, `Enum[]:WeaponSetConditions`, `Flags:ModelCondition`). Anything else
    is an error rather than a guess - the spelling comes from a file, so it is not trusted to
    name an arbitrary object."""
    spec = spec.strip()
    if not spec:
        return None, "empty type"
    prefix, _, argument = spec.partition(":")
    if argument:
        if prefix in ("Ref", "Ref[]"):
            reference = _types.Reference(argument)
            return (_LIST[reference] if prefix == "Ref[]" else reference), ""
        if prefix in ("Enum", "Enum[]", "Flags"):
            enum_cls = _enum_classes().get(argument)
            if enum_cls is None:
                return None, f"unknown enum {argument!r}"
            if prefix == "Enum":
                return enum_cls, ""
            return (_FLAG_LIST if prefix == "Flags" else _LIST)[enum_cls], ""
        return None, f"unknown type {spec!r}"
    if spec.endswith("[]"):
        element = _SCALARS.get(spec[:-2])
        if element is None:
            return None, f"unknown type {spec!r}"
        return _LIST[element], ""
    scalar = _SCALARS.get(spec)
    if scalar is None:
        return None, f"unknown type {spec!r}"
    return scalar, ""


def _own(cls: type, name: str) -> dict:
    """A copy of `cls`'s *own* engine dict `name` - not an inherited one, which would otherwise
    be mutated on behalf of every sibling class."""
    return dict(cls.__dict__.get(name, {}))


def _set_own(cls: type, name: str, value: dict, undo: list[Callable[[], None]]) -> None:
    """Set an engine dict on `cls` itself and record how to put it back."""
    had = name in cls.__dict__
    previous = cls.__dict__.get(name)

    def restore() -> None:
        if had:
            setattr(cls, name, previous)
        else:
            delattr(cls, name)
        rebuild_schema_tree(cls)

    setattr(cls, name, value)
    undo.append(restore)


def _block(name: str) -> tuple[type[IniObject] | None, str]:
    cls = REGISTRY.get(name)
    if cls is None:
        return None, f"unknown block type {name!r}"
    return cls, ""


def _apply_block(delta: BlockDelta, undo: list[Callable[[], None]]) -> list[str]:
    """Register or unregister a block type in `REGISTRY`, which is what every consumer reads to
    turn a block header into a class.

    A created block is a real subclass, so it inherits its base's schema and `IniObject`'s
    `__init_subclass__` builds it exactly like a declared one. Undo removes the registry entry;
    the class object itself stays reachable from its base's `__subclasses__`, which is harmless -
    nothing can name it once it is out of the registry."""
    if delta.removed:
        existing = REGISTRY.get(delta.name)
        if existing is None:
            return [
                f"{_where(delta.patch)}{delta.name!r} is not a block type, "
                "so there is nothing for the patch to have removed"
            ]

        def restore_removed() -> None:
            REGISTRY[delta.name] = existing

        del REGISTRY[delta.name]
        undo.append(restore_removed)
        return []

    if delta.name in REGISTRY:
        return [f"{_where(delta.patch)}{delta.name!r} is already a block type"]
    base, problem = _block(delta.base)
    if base is None:
        return [f"{_where(delta.patch)}{delta.name}: base {problem}"]
    created = type(delta.name, (base,), {"__module__": base.__module__})
    REGISTRY[delta.name] = created

    def restore_created() -> None:
        REGISTRY.pop(delta.name, None)

    undo.append(restore_created)
    return []


def _apply_nested(delta: NestedDelta, undo: list[Callable[[], None]]) -> list[str]:
    """Let `delta.block` contain a `delta.name` sub-block, which is what makes an added block type
    legal where the patch actually lets it be written.

    The parent's own `nested_attributes` is *copied* before the entry is added: the stock model
    shares one dict between several classes (every `Act` verb list is the same object), and
    mutating it in place would quietly give the sub-block to all of them."""
    cls, problem = _block(delta.block)
    if cls is None:
        return [f"{_where(delta.patch)}{problem}"]
    if delta.child not in REGISTRY:
        return [
            f"{_where(delta.patch)}{delta.block}.{delta.name}: unknown block type {delta.child!r}"
        ]
    nested = _own(cls, "nested_attributes")
    nested[delta.name] = [delta.child]
    _set_own(cls, "nested_attributes", nested, undo)
    rebuild_schema_tree(cls)
    return []


def _apply_field(delta: FieldDelta, undo: list[Callable[[], None]]) -> list[str]:
    cls, problem = _block(delta.block)
    if cls is None:
        return [f"{_where(delta.patch)}{problem}"]
    converter, problem = parse_type(delta.type)
    if converter is None:
        return [f"{_where(delta.patch)}{delta.block}.{delta.name}: {problem}"]
    fields = _own(cls, "_engine_fields")
    fields[delta.name] = converter
    _set_own(cls, "_engine_fields", fields, undo)
    if delta.default is not None:
        defaults = _own(cls, "_engine_defaults")
        defaults[delta.name] = delta.default
        _set_own(cls, "_engine_defaults", defaults, undo)
    rebuild_schema_tree(cls)
    return []


def _apply_noop(delta: NoopDelta, undo: list[Callable[[], None]]) -> list[str]:
    cls, problem = _block(delta.block)
    if cls is None:
        return [f"{_where(delta.patch)}{problem}"]
    if delta.name not in cls._fieldspec:
        return [
            f"{_where(delta.patch)}{delta.block}.{delta.name} is not a field of that block, "
            "so there is nothing for the patch to have retired"
        ]
    noops = _own(cls, "_engine_noops")
    reason = delta.reason or "this engine ignores it"
    noops[delta.name] = f"{reason} ({delta.patch})" if delta.patch else reason
    _set_own(cls, "_engine_noops", noops, undo)
    rebuild_schema_tree(cls)
    return []


def _apply_enum_member(delta: EnumDelta, undo: list[Callable[[], None]]) -> list[str]:
    enum_cls = _enum_classes().get(delta.enum)
    if enum_cls is None:
        return [f"{_where(delta.patch)}unknown enum {delta.enum!r}"]
    if delta.name in enum_cls.__members__:
        return []  # the model already names it; a patch re-adding it is not a problem
    value = delta.value if delta.value is not None else len(enum_cls.__members__)
    member = object.__new__(enum_cls)
    member._name_ = delta.name
    member._value_ = value
    # `enum` sets this on every member it creates; a Flag's definition-order iteration reads
    # it. Set here too, so an injected member is shaped exactly like a declared one.
    member._sort_order_ = len(enum_cls._member_names_)  # type: ignore[attr-defined]
    # Set the attribute before the member map: `EnumType.__setattr__` refuses to touch a name
    # the map already claims.
    type.__setattr__(enum_cls, delta.name, member)
    enum_cls._member_map_[delta.name] = member
    enum_cls._member_names_.append(delta.name)
    # A value the stock model already spends stays pointed at its stock member - the model's
    # enums are a union across builds, so an index the binary gives a new token can collide with
    # one already named here. Lookup by name (what INI conversion does) is unaffected either way.
    claimed = value not in enum_cls._value2member_map_
    if claimed:
        enum_cls._value2member_map_[value] = member

    def restore() -> None:
        enum_cls._member_map_.pop(delta.name, None)
        if delta.name in enum_cls._member_names_:
            enum_cls._member_names_.remove(delta.name)
        if claimed:
            enum_cls._value2member_map_.pop(value, None)
        type.__delattr__(enum_cls, delta.name)

    undo.append(restore)
    return []


def _where(patch: str) -> str:
    return f"{patch}: " if patch else ""


_SECTIONS = {"patches", "blocks", "nested", "fields", "noops", "enum_members", "limits"}
_KNOWN_KEYS = {"version", "source", *_SECTIONS}


def _table_list(data: dict, name: str, warn: list[str], where: str) -> list[dict]:
    """The array-of-tables under `name`, or [] with a warning if it is anything else."""
    value = data.get(name)
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    warn.append(f"{where}: '{name}' must be an array of tables (ignored)")
    return []


def _string(entry: dict, key: str, warn: list[str], where: str, required: bool = True) -> str:
    value = entry.get(key)
    if isinstance(value, str) and value:
        return value
    if required:
        warn.append(f"{where}: entry is missing a non-empty '{key}' (ignored)")
    return ""


def _option_value(value: object) -> object | None:
    """One patch option as it can be held and compared, or None when the file spells something
    a constructor argument never is - a nested table, an array of tables - which is dropped with
    a warning rather than carried as a value no rebuild could pass on."""
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list) and all(
        isinstance(item, bool | int | float | str) for item in value
    ):
        return tuple(value)
    return None


def parse_engine(text: str, where: str = SAGEPATCH_NAME) -> Engine:
    """Read a `.sagepatch` document. Never raises: a malformed file, an unknown section, a key
    of the wrong type or an entry missing what it needs each become a warning on the returned
    engine, and everything well-formed still loads."""
    warn: list[str] = []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return Engine(warnings=(f"{where}: {exc}",))

    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        warn.append(f"{where}: missing or non-integer 'version' (assuming {FORMAT_VERSION})")
    elif version > FORMAT_VERSION:
        warn.append(
            f"{where}: written by a newer generator (version {version} > {FORMAT_VERSION}); "
            "entries this version does not understand are skipped"
        )
    for key in sorted(set(data) - _KNOWN_KEYS):
        warn.append(f"{where}: unknown section '{key}' (ignored)")

    raw_source = data.get("source")
    source = Source()
    if isinstance(raw_source, dict):
        known = {f.name for f in Source.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        source = Source(
            **{k: v for k, v in raw_source.items() if k in known and isinstance(v, str)}
        )
    elif raw_source is not None:
        warn.append(f"{where}: 'source' must be a table (ignored)")

    patches: list[AppliedPatch] = []
    for entry in _table_list(data, "patches", warn, where):
        name = _string(entry, "name", warn, where)
        if not name:
            continue
        raw_options = entry.get("options")
        if raw_options is not None and not isinstance(raw_options, dict):
            warn.append(f"{where}: patch {name} has a non-table 'options' (ignored)")
            raw_options = None
        options: list[tuple[str, object]] = []
        for key, value in sorted((raw_options or {}).items()):
            cleaned = _option_value(value)
            if cleaned is None:
                warn.append(f"{where}: patch {name}: option {key!r} is not a value a patch takes")
                continue
            options.append((key, cleaned))
        experimental = entry.get("experimental")
        if experimental is not None and not isinstance(experimental, bool):
            warn.append(f"{where}: patch {name} has a non-boolean 'experimental' (ignored)")
            experimental = None
        patches.append(
            AppliedPatch(
                name=name,
                options=tuple(options),
                experimental=bool(experimental),
                author=_string(entry, "author", warn, where, required=False),
                description=_string(entry, "description", warn, where, required=False),
            )
        )

    blocks: list[BlockDelta] = []
    for entry in _table_list(data, "blocks", warn, where):
        name = _string(entry, "name", warn, where)
        if not name:
            continue
        removed = entry.get("removed")
        if removed is not None and not isinstance(removed, bool):
            warn.append(f"{where}: block {name} has a non-boolean 'removed' (ignored)")
            removed = None
        blocks.append(
            BlockDelta(
                name=name,
                base=_string(entry, "base", warn, where, required=False) or "Behavior",
                removed=bool(removed),
                patch=_string(entry, "patch", warn, where, required=False),
            )
        )

    nested: list[NestedDelta] = []
    for entry in _table_list(data, "nested", warn, where):
        block = _string(entry, "block", warn, where)
        name = _string(entry, "name", warn, where)
        if not (block and name):
            continue
        nested.append(
            NestedDelta(
                block=block,
                name=name,
                type=_string(entry, "type", warn, where, required=False),
                patch=_string(entry, "patch", warn, where, required=False),
            )
        )

    fields: list[FieldDelta] = []
    for entry in _table_list(data, "fields", warn, where):
        block = _string(entry, "block", warn, where)
        name = _string(entry, "name", warn, where)
        spec = _string(entry, "type", warn, where)
        if not (block and name and spec):
            continue
        default = entry.get("default")
        if default is not None and not isinstance(default, str | int | float | bool):
            warn.append(f"{where}: {block}.{name} has a non-scalar 'default' (ignored)")
            default = None
        fields.append(
            FieldDelta(
                block=block,
                name=name,
                type=spec,
                default=default,
                patch=_string(entry, "patch", warn, where, required=False),
            )
        )

    noops: list[NoopDelta] = []
    for entry in _table_list(data, "noops", warn, where):
        block = _string(entry, "block", warn, where)
        name = _string(entry, "name", warn, where)
        if not (block and name):
            continue
        noops.append(
            NoopDelta(
                block=block,
                name=name,
                reason=_string(entry, "reason", warn, where, required=False),
                patch=_string(entry, "patch", warn, where, required=False),
            )
        )

    members: list[EnumDelta] = []
    for entry in _table_list(data, "enum_members", warn, where):
        enum_name = _string(entry, "enum", warn, where)
        name = _string(entry, "name", warn, where)
        if not (enum_name and name):
            continue
        value = entry.get("value")
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            warn.append(f"{where}: {enum_name}.{name} has a non-integer 'value' (ignored)")
            value = None
        members.append(
            EnumDelta(
                enum=enum_name,
                name=name,
                value=value,
                patch=_string(entry, "patch", warn, where, required=False),
            )
        )

    limits: list[LimitDelta] = []
    for entry in _table_list(data, "limits", warn, where):
        name = _string(entry, "name", warn, where)
        value = entry.get("value")
        if not name:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            warn.append(f"{where}: limit {name!r} must have an integer 'value' (ignored)")
            continue
        if name not in STOCK_LIMITS:
            warn.append(f"{where}: unknown engine limit {name!r} (ignored)")
            continue
        limits.append(
            LimitDelta(
                name=name, value=value, patch=_string(entry, "patch", warn, where, required=False)
            )
        )

    return Engine(
        patches=tuple(patches),
        blocks=tuple(blocks),
        nested=tuple(nested),
        fields=tuple(fields),
        noops=tuple(noops),
        enum_members=tuple(members),
        limits=tuple(limits),
        source=source,
        warnings=tuple(warn),
    )


def load_engine(path: str | Path) -> Engine:
    """Load a `.sagepatch` from `path`. A missing file is the stock engine (no warning - not
    having one is the normal case); an unreadable or malformed one warns and degrades to stock."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return STOCK
    except OSError as exc:
        return Engine(warnings=(f"{path}: {exc}",))
    return parse_engine(text, str(path))


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, tuple | list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(v)}" for k, v in value.items()) + " }"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _toml_table(name: str, entries: Sequence[tuple[str, object]]) -> str:
    lines = [f"[[{name}]]"]
    lines.extend(
        f"{key} = {_toml_value(value)}" for key, value in entries if value not in ("", None)
    )
    return "\n".join(lines)


def dump_engine(engine: Engine, header: str = "") -> str:
    """Serialize `engine` as a `.sagepatch` document. `header` is prepended as comment lines,
    for the generator to say what produced the file and how to regenerate it."""
    out: list[str] = []
    if header:
        out.extend(f"# {line}" if line else "#" for line in header.splitlines())
        out.append("")
    out.append(f"version = {FORMAT_VERSION}")

    source = [
        (key, getattr(engine.source, key))
        for key in ("build", "sha256", "generator", "generated")
        if getattr(engine.source, key)
    ]
    if source:
        out.append("")
        out.append("[source]")
        out.extend(f"{key} = {_toml_value(value)}" for key, value in source)

    for patch in engine.patches:
        out.append("")
        out.extend(f"# {line}" for line in textwrap.wrap(patch.description, width=96))
        out.append(
            _toml_table(
                "patches",
                [
                    ("name", patch.name),
                    ("options", patch.settings or None),
                    ("experimental", patch.experimental or None),
                    ("author", patch.author),
                ],
            )
        )
    for block in engine.blocks:
        out.append("")
        out.append(
            _toml_table(
                "blocks",
                [
                    ("name", block.name),
                    ("base", "" if block.removed else block.base),
                    ("removed", block.removed or None),
                    ("patch", block.patch),
                ],
            )
        )
    for entry in engine.nested:
        out.append("")
        out.append(
            _toml_table(
                "nested",
                [
                    ("block", entry.block),
                    ("name", entry.name),
                    ("type", entry.type),
                    ("patch", entry.patch),
                ],
            )
        )
    for delta in engine.fields:
        out.append("")
        out.append(
            _toml_table(
                "fields",
                [
                    ("block", delta.block),
                    ("name", delta.name),
                    ("type", delta.type),
                    ("default", delta.default),
                    ("patch", delta.patch),
                ],
            )
        )
    for noop in engine.noops:
        out.append("")
        out.append(
            _toml_table(
                "noops",
                [
                    ("block", noop.block),
                    ("name", noop.name),
                    ("reason", noop.reason),
                    ("patch", noop.patch),
                ],
            )
        )
    for member in engine.enum_members:
        out.append("")
        out.append(
            _toml_table(
                "enum_members",
                [
                    ("enum", member.enum),
                    ("name", member.name),
                    ("value", member.value),
                    ("patch", member.patch),
                ],
            )
        )
    for limit in engine.limits:
        out.append("")
        out.append(
            _toml_table(
                "limits", [("name", limit.name), ("value", limit.value), ("patch", limit.patch)]
            )
        )
    return "\n".join(out) + "\n"
