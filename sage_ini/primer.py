"""A compact, token-efficient digest of the typed model, for an LLM agent assisting with
SAGE ini editing. The model in `sage_ini.model` is the single source of truth; this module
introspects it (it never hand-lists fields) so the digest can never drift from the schema.

The digest answers "what kinds exist, where each is defined, and which fields point where":
every cross-reference field carries an `R:<table>` code naming the Game table its value
resolves into, which is what lets an agent reading one file know where to chase a referenced
button, command set, weapon, upgrade, and so on.

The output is deliberately terse (a legend defines short type codes once). Tier 1 is the
always-loaded core: legend, table catalog, module catalog, a curated set of common kinds, and
an enum appendix. Detail for any other kind is pulled on demand via `expand_kind`, so the
core stays small.
"""

import enum

from sage_ini.model import types as t
from sage_ini.model.game import Game, _Table
from sage_ini.model.objects import REGISTRY, Behavior, Draw, IniObject, Module, Nugget

__all__ = ["build_index", "build_digest", "expand_kind", "dump_enum", "table_catalog"]

# The kinds whose full field schema ships in the always-loaded core. Everything else is a
# catalog line plus `expand_kind` on demand; this is the main token-budget lever.
CORE_KINDS = (
    "Object",
    "CommandButton",
    "CommandSet",
    "Weapon",
    "Upgrade",
    "Armor",
    "Locomotor",
    "SpecialPower",
    "Science",
    "ObjectCreationList",
    "PlayerTemplate",
)

# IniObject's own class-body annotations (`key`, `header_arity`, `_fieldspec`, ...) ride in
# `_fieldspec` via the MRO but are parser bookkeeping, not ini fields, so they're excluded.
_INFRA_FIELDS = frozenset(IniObject.__annotations__)

# An enum with more members than this is summarised (count + `primer enum <Name>`) instead of
# listed inline, so a few huge enums (KindOf, ModelCondition) don't dominate the digest.
_ENUM_INLINE_MAX = 24

# Blocks whose payload is digit-keyed slots (`1 = X`, `2 = ...`) that can't be Python
# annotations, mapped to the table those slot values reference. The synthesised slot line is
# the only place this fact reaches the digest.
_NUMBERED_SLOT_TARGET = {"CommandSet": "commandbuttons", "ButtonSet": "commandbuttons"}

# Short codes for the scalar/shape converters, keyed by the converter class itself so a rename
# in the model surfaces here as a missing code rather than a stale string.
_SCALAR_CODES: dict[type, str] = {
    t._Bool: "B",
    t._Int: "I",
    t._Float: "F",
    t._Degrees: "deg",
    t._IntRange: "I2",
    t._FloatRange: "F2",
    t._RandomVariable: "rand",
    t._String: "S",
    t.String: "S",
    t.Untyped: "S",
    t._Opaque: "O",
    t._ModuleTag: "tag",
    t._Label: "label",
    t._Coords: "xyz",
    t._CoordsList: "xyz+",
    t._RawList: "S+",
    t._RGB: "rgb",
    t._RGBA: "rgba",
}

LEGEND = """\
# LEGEND  one line per field: `Name: <type-code>`
#   I int  F float  B bool  S string  O opaque-token  tag module-tag  label UI-label
#   I2 int-range  F2 float-range  deg degrees  rand random-var  S+ token-list
#   xyz coords  xyz+ coords-list  rgb  rgba  file:ext on-disk asset
#   R:<table>  cross-reference -> a definition in that Game table (where to look)
#   @Name      link to a modeled block type that has no table of its own
#   E:<Enum>   enumeration (members in the ENUMS section)
#   L[x] list  Lf[x] flag-set (last set wins)  Lq[x] quoted-name list
#   (a b c) fixed tuple   a|b union   ?x accepts NONE   KV[v..] colon-keyed record
# Sub-blocks (Behavior=/Draw=/nuggets) are listed in MODULES, not as fields."""


class _Decoder:
    """Turns a field annotation into a compact type code, collecting the enums it names so the
    appendix can list exactly those that appear."""

    def __init__(self) -> None:
        self.enums: set[type[enum.Enum]] = set()

    def decode(self, ann) -> str:
        # An `Annotated[PyType, converter]` alias: the converter (first metadatum) is the truth;
        # the PyType is only there for the IDE.
        if hasattr(ann, "__metadata__"):
            return self.decode(ann.__metadata__[0])
        # A field annotated by another modeled block's name (`CommandTrigger: "CommandButton"`).
        if isinstance(ann, str):
            cls = REGISTRY.get(ann)
            return self._class_code(cls) if cls is not None else ann
        # Configured generic converters carry their parameters as attributes.
        if isinstance(ann, t.Reference):
            return f"R:{ann.key}"
        if isinstance(ann, t._Nullable):
            return "?" + self.decode(ann.inner)
        if isinstance(ann, t._List):
            prefix = {"_FlagList": "Lf", "_QuotedList": "Lq"}.get(type(ann).__name__, "L")
            return f"{prefix}[{self.decode(ann.element)}]"
        if isinstance(ann, t._Tuple):
            return "(" + " ".join(self.decode(e) for e in ann.element_types) + ")"
        if isinstance(ann, t._Union):
            return "|".join(self.decode(e) for e in ann.types)
        if isinstance(ann, t._KeyValuePair):
            inner = " ".join(self.decode(v) for v in ann.values) or "S"
            return f"KV[{inner}]"
        if isinstance(ann, type):
            return self._class_code(ann)
        # An unrecognised converter instance: its class name, sans the private underscore.
        return type(ann).__name__.lstrip("_")

    def _class_code(self, cls) -> str:
        if cls is None:
            return "?"
        if issubclass(cls, IniObject):
            return f"R:{cls.key}" if cls.key else f"@{cls.__name__}"
        if issubclass(cls, enum.Enum):
            self.enums.add(cls)
            return f"E:{cls.__name__}"
        if issubclass(cls, t._AssetFile):
            return "file:" + "/".join(e.lstrip(".") for e in cls.extensions)
        code = _SCALAR_CODES.get(cls)
        if code is not None:
            return code
        return cls.__name__.lstrip("_")


def table_catalog() -> list[tuple[str, str]]:
    """`(table-key, element-class-name)` for every Game table, the map from a kind to where its
    definitions are registered. Sorted by key."""
    out = []
    for member in vars(Game).values():
        if isinstance(member, _Table):
            out.append((member._key, member.cls.__name__))
    return sorted(out)


def _module_catalog() -> dict[str, list[str]]:
    """The sub-block module types an `Object` (or other host) can contain, grouped by their
    role. These are the `Behavior = ...` / `Draw = ...` / nugget slots, not fields."""
    groups: dict[str, list[str]] = {"Behaviors": [], "Draws": [], "Nuggets": [], "Modules": []}
    for cls in REGISTRY.values():
        if cls in (Module, Behavior, Draw, Nugget):
            continue
        if issubclass(cls, Draw):
            groups["Draws"].append(cls.__name__)
        elif issubclass(cls, Behavior):
            groups["Behaviors"].append(cls.__name__)
        elif issubclass(cls, Nugget):
            groups["Nuggets"].append(cls.__name__)
        elif issubclass(cls, Module):
            groups["Modules"].append(cls.__name__)
    return {role: sorted(names) for role, names in groups.items()}


def _schema_lines(cls: type[IniObject], decoder: _Decoder) -> list[str]:
    """The `Name: code` field lines for one kind, in declaration order, plus a synthetic line
    for digit-keyed slots when the block carries them."""
    lines = [
        f"  {name}: {decoder.decode(ann)}"
        for name, ann in cls._fieldspec.items()
        if name not in _INFRA_FIELDS and not name.startswith("_")
    ]
    if getattr(cls, "numbered_slots", False):
        target = _NUMBERED_SLOT_TARGET.get(cls.__name__)
        code = f"R:{target}" if target else "S"
        lines.append(f"  <1..N>: {code}  # numbered slots: 1 = ..., 2 = ...")
    return lines


def _enum_values(cls: type[enum.Enum]) -> str:
    """An enum's members joined for display; an open enum (no fixed members, like `Stances`)
    accepts any token, so it's labelled rather than shown blank."""
    return " ".join(member.name for member in cls) or "(open: any token)"


def _enum_members(cls: type[enum.Enum]) -> list[str]:
    return [member.name for member in cls]


def expand_kind(name: str) -> str:
    """The full field schema of one kind plus the enums it names - the on-demand detail the
    core digest omits for non-core kinds."""
    cls = REGISTRY.get(name)
    if cls is None:
        return f"no modeled kind named {name!r}"
    decoder = _Decoder()
    header = name + (f"  [table:{cls.key}]" if cls.key else "")
    lines = [header, *_schema_lines(cls, decoder)]
    for enum_cls in sorted(decoder.enums, key=lambda c: c.__name__):
        lines.append(f"E:{enum_cls.__name__} = " + _enum_values(enum_cls))
    return "\n".join(lines)


def _enum_index() -> dict[str, type[enum.Enum]]:
    """Every enum named by some field, keyed by name. Derived by decoding the whole model, so it
    is exactly the set the digest can reference (and never a hand-listed module scan)."""
    decoder = _Decoder()
    for cls in REGISTRY.values():
        for ann in cls._fieldspec.values():
            decoder.decode(ann)
    return {enum_cls.__name__: enum_cls for enum_cls in decoder.enums}


def dump_enum(name: str) -> str:
    cls = _enum_index().get(name)
    if cls is None:
        return f"no enum named {name!r}"
    return f"E:{name} = " + _enum_values(cls)


def _tables_section() -> str:
    lines = ["# TABLES  <key>: <ModeledKind>  -- a reference R:<key> resolves here"]
    lines += [f"  {key}: {cls_name}" for key, cls_name in table_catalog()]
    return "\n".join(lines)


def _modules_section() -> str:
    lines = ["# MODULES  legal sub-blocks of an Object, by role"]
    for role, names in _module_catalog().items():
        if names:
            lines.append(f"  {role} ({len(names)}): " + " ".join(names))
    return "\n".join(lines)


def _core_section(decoder: _Decoder) -> str:
    lines = ["# CORE KINDS  full field schemas (others: `primer expand <Kind>`)"]
    for name in CORE_KINDS:
        cls = REGISTRY.get(name)
        if cls is None:
            continue
        lines.append(name + (f"  [table:{cls.key}]" if cls.key else ""))
        lines.extend(_schema_lines(cls, decoder))
    return "\n".join(lines)


def _enums_section(decoder: _Decoder) -> str:
    """The enums named by the core schemas: small ones inline, big ones summarised. Only
    meaningful alongside `_core_section`, which is what populates `decoder.enums`."""
    lines = ["# ENUMS  members of the enumerations named above"]
    for enum_cls in sorted(decoder.enums, key=lambda c: c.__name__):
        members = _enum_members(enum_cls)
        if len(members) <= _ENUM_INLINE_MAX:
            lines.append(f"  E:{enum_cls.__name__} = " + _enum_values(enum_cls))
        else:
            lines.append(
                f"  E:{enum_cls.__name__} ({len(members)}, `primer enum {enum_cls.__name__}`)"
            )
    return "\n".join(lines)


def build_index() -> str:
    """The lean, always-loaded tier: legend, table catalog, and module catalog -- the "where to
    look" map with no per-kind field schemas. Detail is pulled on demand with `expand_kind`, so
    this stays small enough to keep resident."""
    footer = (
        "# USAGE  pull a kind's fields with `primer expand <Kind>`, an enum's members with\n"
        "#   `primer enum <Name>`. Every R:<table> above resolves in that Game table."
    )
    return "\n\n".join([LEGEND, _tables_section(), _modules_section(), footer]) + "\n"


def build_digest() -> str:
    """The full digest: the index plus full schemas for the core kinds and their enums. Larger
    than `build_index`; useful for inspection or a one-shot dump."""
    decoder = _Decoder()
    return (
        "\n\n".join(
            [
                LEGEND,
                _tables_section(),
                _modules_section(),
                _core_section(decoder),
                _enums_section(decoder),
            ]
        )
        + "\n"
    )
