"""What the *engine binary* accepts, as data - the INI surface a patched `game.dat` has that a
stock one does not.

A binary patch (see `sage_patch`) can teach the engine INI it could not read before: a new field
on a block, a new token in a name table, a raised limit, or a field it now ignores. The typed
model in `sage_ini.model` describes the **stock** engine, so on a patched game every one of those
reads as a mistake - an unknown attribute, an unknown enum token, a slot past the array.

An `Engine` is that difference, written down. It is inert data: load one from a `.sagepatch` file
(`load_engine`), build one in code, merge several, compare or serialize them. `apply()` is what
makes the model agree with it.

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
    "Engine",
    "EnumDelta",
    "FieldDelta",
    "LimitDelta",
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
#: generator still loads: unknown sections and keys warn and are skipped.
FORMAT_VERSION = 1

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
class Source:
    """Where an engine description came from, for provenance and drift checks. Informational
    only - nothing in the model reads it - but it is what tells a mod team that the committed
    `.sagepatch` was generated from a different binary than the one they are running."""

    build: str = ""  # the engine build string, e.g. "2.01.2614.37001"
    sha256: str = ""  # of the game.dat it was generated from
    game_dat: str = ""  # the path it was generated from, as typed (machine-specific)
    generator: str = ""  # what wrote it, e.g. "sage_patch 0.1.0"
    generated: str = ""  # ISO date


@dataclass(frozen=True, slots=True)
class FieldDelta:
    """A field a patch added to a block. `type` is a spelling from the grammar `parse_type`
    accepts; `default` is what the block reads when the field is absent, matching the patch's
    own default so an unmodified mod converts the way it runs."""

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
        """Whether this describes an unpatched engine (no deltas of any kind)."""
        return not (self.fields or self.noops or self.enum_members or self.limits)

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
        "Enum:<E>",
        "Enum[]:<E>",
        "Flags:<E>",
    ]


def parse_type(spec: str) -> tuple[object | None, str]:
    """The converter a type spelling names, as `(converter, error)` - exactly one is set.

    The grammar is small and closed: a scalar (`Int`), a list of one (`Int[]`), a cross-reference
    to a Game table (`Ref:upgrades`), or an enum as a scalar, a list or a whole-set flag list
    (`Enum:ModelCondition`, `Enum[]:WeaponSetConditions`, `Flags:ModelCondition`). Anything else
    is an error rather than a guess - the spelling comes from a file, so it is not trusted to
    name an arbitrary object."""
    spec = spec.strip()
    if not spec:
        return None, "empty type"
    prefix, _, argument = spec.partition(":")
    if argument:
        if prefix == "Ref":
            return _types.Reference(argument), ""
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


_SECTIONS = {"fields", "noops", "enum_members", "limits"}
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
        for key in ("build", "sha256", "game_dat", "generator", "generated")
        if getattr(engine.source, key)
    ]
    if source:
        out.append("")
        out.append("[source]")
        out.extend(f"{key} = {_toml_value(value)}" for key, value in source)

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
