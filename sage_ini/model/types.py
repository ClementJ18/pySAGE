"""Value converters for typed object fields. Each exposes `convert(game, raw)`, invoked
lazily when a field is read. Scalar converters resolve macros first; container converters
(`List`, `Tuple`, `Union`, `KeyValuePair`) are built by subscription (`List["Upgrade"]`)
and delegate to their elements. Numbers may be inline arithmetic expressions
(`#MULTIPLY( X 1.1 )`), evaluated by `eval_number`.
"""

import re
from itertools import zip_longest
from typing import TYPE_CHECKING, Annotated, NamedTuple
from warnings import deprecated

import sage_ini.model.types as t  # noqa: E402  (intentional self-reference)
from sage_ini.model.enums import (
    DamageType,
    DeathType,
    Descriptors,
    DistributionType,
    KindOf,
    ModelCondition,
    ModifierType,
    Relations,
)
from sage_ini.model.objects import Multivalued, is_multivalued, resolve_annotation

if TYPE_CHECKING:
    from sage_ini.model.data_blocks import (
        AudioEvent,
        FXParticleSystem,
        MappedImage,
        MouseCursor,
        NewEvaEvent,
        PredefinedEvaEvent,
    )
    from sage_ini.model.data_blocks import FXList as _FXListBlock
    from sage_ini.model.ini_objects import Object, ObjectCreationList

OPERATIONS = {
    "MULTIPLY": lambda a, b: a * b,
    "DIVIDE": lambda a, b: a / b,
    "ADD": lambda a, b: a + b,
    "SUBTRACT": lambda a, b: a - b,
}


def to_number(value: str) -> float:
    """Parse a numeric literal: trailing ``%`` -> fraction, trailing ``f`` dropped."""
    text = value.strip()
    is_percent = text.endswith("%")
    text = text.rstrip("%").strip()
    if text[-1:] in "fF" and text[:-1].replace(".", "").replace("-", "").isdigit():
        text = text[:-1]
    number = float(text)
    return number / 100 if is_percent else number


def _split_operands(inner: str) -> list[str]:
    """Split an expression body on whitespace at paren depth zero."""
    operands: list[str] = []
    current: list[str] = []
    depth = 0
    for char in inner:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char.isspace() and depth == 0:
            if current:
                operands.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        operands.append("".join(current))
    return operands


def eval_number(game, value) -> float:
    """Evaluate a numeric value: literal, macro, or ``#OP( a b ... )`` expression."""
    if isinstance(value, (int, float)):
        return value

    text = str(value).strip()
    # A trailing `%` makes the value a percentage, and may sit apart from its
    # number (`MACRO %`, `#OP( ... ) %`); peel it, evaluate the rest, then scale.
    if text.endswith("%") and text != "%":
        return eval_number(game, text[:-1]) / 100

    if text.startswith("#") and "(" in text:
        name = text[1 : text.index("(")].strip()
        if name in OPERATIONS:
            inner = text[text.index("(") + 1 : text.rindex(")")]
            operands = [eval_number(game, operand) for operand in _split_operands(inner)]
            result = operands[0]
            for operand in operands[1:]:
                result = OPERATIONS[name](result, operand)
            return result

    resolved = game.get_macro(text)
    if isinstance(resolved, (int, float)):
        return resolved
    if isinstance(resolved, str) and resolved.strip().startswith("#"):
        return eval_number(game, resolved)
    return to_number(str(resolved))


def _first_token(value):
    """The first whitespace token of a multi-token scalar value, or None when the value is a
    single token, an arithmetic expression, or not a string. The engine reads one token for a
    scalar field and ignores any trailing tokens on the line (a redundant `0.2 0.2`, a note
    written without a `;`); the numeric converters fall back to it before giving up."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("#"):  # an arithmetic expression legitimately spans tokens
        return None
    parts = text.split()
    return parts[0] if len(parts) > 1 else None


class _Bool:
    @staticmethod
    def convert(game, value):
        resolved = game.get_macro(value)
        if isinstance(resolved, bool):
            return resolved
        low = str(resolved).strip().lower()
        if low in ("yes", "no"):
            return low == "yes"
        raise ValueError(f"expected a Bool (Yes/No) but found {resolved!r}")


Bool = Annotated[bool, _Bool]


class _Int:
    @staticmethod
    def convert(game, value):
        try:
            return int(eval_number(game, value))
        except (ValueError, KeyError) as exc:
            first = _first_token(value)
            if first is not None:
                try:
                    return int(eval_number(game, first))
                except (ValueError, KeyError):
                    pass
            raise ValueError(f"expected an Int but found {value!r}") from exc


Int = Annotated[int, _Int]


class _Float:
    @staticmethod
    def convert(game, value):
        try:
            return eval_number(game, value)
        except (ValueError, KeyError) as exc:
            first = _first_token(value)
            if first is not None:
                try:
                    return eval_number(game, first)
                except (ValueError, KeyError):
                    pass
            raise ValueError(f"expected a Float but found {value!r}") from exc


Float = Annotated[float, _Float]


class Ranged:
    """An integer that converts freely but carries `minimum`/`maximum` bounds for the
    `out-of-range` lint rule to check - whether a value sits in range is a judgment, not a
    parse fact, so `convert` never rejects it."""

    minimum: float
    maximum: float

    @classmethod
    def convert(cls, game, value):
        return _Int.convert(game, value)


class _Degrees(Ranged):
    # An angle in degrees, signed or unsigned and up to a full turn either way, so the
    # permitted range spans a whole negative-to-positive revolution: -360..360.
    minimum = -360
    maximum = 360


Degrees = Annotated[int, _Degrees]


def _range_tokens(value):
    """The tokens of a range value, splitting at paren depth zero so a `#OP( a b )` stays
    whole. A repeated scalar key arrives as a list; the last line wins, as for any scalar."""
    if isinstance(value, list):
        value = value[-1] if value else ""
    return _split_operands(value) if isinstance(value, str) else [str(value)]


class _FloatRange:
    """A `low high` pair of floats (engine `ParseFloatRange`). A lone token yields a zero-width
    range (`low == high`); tokens past the second are ignored, as the engine reads exactly two."""

    @staticmethod
    def convert(game, value):
        tokens = _range_tokens(value)
        if not tokens:
            raise ValueError("expected a float range but found nothing")
        low = _Float.convert(game, tokens[0])
        high = _Float.convert(game, tokens[1]) if len(tokens) > 1 else low
        return (low, high)


FloatRange = Annotated[tuple[float, float], _FloatRange]


class _IntRange:
    """A `low high` pair of ints (engine `ParseIntRange`); `_FloatRange` made integral."""

    @staticmethod
    def convert(game, value):
        tokens = _range_tokens(value)
        if not tokens:
            raise ValueError("expected an int range but found nothing")
        low = _Int.convert(game, tokens[0])
        high = _Int.convert(game, tokens[1]) if len(tokens) > 1 else low
        return (low, high)


IntRange = Annotated[tuple[int, int], _IntRange]


class RandomVariableValue(NamedTuple):
    """A draw between `low` and `high` with a named `distribution` (default `UNIFORM`)."""

    low: float
    high: float
    distribution: DistributionType


class _RandomVariable:
    """A `low high [distribution]` random range (engine `ParseRandomVariable`). The optional
    third token names a `DistributionType`; absent, the draw is `UNIFORM`."""

    @staticmethod
    def convert(game, value):
        tokens = _range_tokens(value)
        if not tokens:
            raise ValueError("expected a random variable but found nothing")
        low = _Float.convert(game, tokens[0])
        high = _Float.convert(game, tokens[1]) if len(tokens) > 1 else low
        distribution = DistributionType.UNIFORM
        if len(tokens) > 2:
            distribution = DistributionType.convert(game, tokens[2])
        return RandomVariableValue(low, high, distribution)


RandomVariable = Annotated[RandomVariableValue, _RandomVariable]


class _String:
    @staticmethod
    def convert(game, value):
        return value


@deprecated(
    "This field is not currently typed, if you are intending to use it please open an issue to "
    "request a dedicated type for it."
)
class Untyped(str):
    """The not-yet-typed text fallback, runtime-identical to a raw token. Deprecated *on purpose*
    so every remaining `field: Untyped` annotation surfaces as a warning in the IDE - the
    migration to dedicated types is driven by which of these are actually used. Internal
    converters default to `_String` (no warning); only an explicit field annotation is flagged.
    Once reviewed, a field becomes either a dedicated type or `String` (intentional free text)."""

    @staticmethod
    def convert(game, value):
        return value


class String(str):
    """Intentional free text: a field reviewed and *deliberately* kept as an opaque text value,
    because no dedicated type applies (an arbitrary name, a comment, a raw spec). Unlike the
    backlog `Untyped`, this is not deprecated - using it is a positive, reviewed choice, so it
    does not warn. Subclasses `str` so a value still types as text."""

    @staticmethod
    def convert(game, value):
        return value


class _Opaque:
    """A named scalar kept as its raw token (e.g. a model bone). Identical to `String` at
    runtime, but the annotation records that it denotes an external entity, not free text."""

    @staticmethod
    def convert(game, value):
        return value


Opaque = Annotated[str, _Opaque]


class _ModuleTag:
    """A `ModuleTag_*` naming another module on the *same object* (e.g. the module a
    `TriggerSpecialPower` fires). Kept as its raw token: the target is a sibling module, not a
    Game-table entry, so a converter cannot resolve it - it has no view of the parent object.
    The `module-tag-reference` lint rule checks it against the object's own modules; typing it
    here (rather than leaving it `Untyped`) records that intent."""

    @staticmethod
    def convert(game, value):
        return value


ModuleTag = Annotated[str, _ModuleTag]


class _Label:
    """A localized string-table reference (e.g. `OBJECT:MordorFighter`), kept verbatim. The
    annotation lets the linter check the label resolves in `game.strings`. A field may hold
    several whitespace-separated labels (a toggle button's per-state text)."""

    @staticmethod
    def convert(game, value):
        return value


Label = Annotated[str, _Label]


class Reference:
    """A named cross-reference to a top-level definition in `game.tables[key]`, resolving to
    the registered object when present. An unknown name passes through unchanged; strict
    dangling-reference checking is the linter's job."""

    def __init__(self, key):
        self.key = key

    def convert(self, game, value):
        name = game.get_macro(value)
        obj, canonical = game.lookup(self.key, name)
        if obj is None:
            return (
                name  # an unknown name passes through; dangling-reference checks are the linter's
            )
        if canonical != name:
            game.warn(
                "reference-case",
                f"{self.key} reference {name!r} should be {canonical!r} (case mismatch)",
                {"given": name, "canonical": canonical, "key": self.key},
            )
        return obj


class _Complex:
    """A set of `Ref:number` components in a fixed order (`X:31 Y:0 Z:47`). Scanned via
    `scan_keyed` (not split on spaces) so a spaced `X: 31` isn't torn apart; the axis letter
    is matched case-insensitively."""

    indexes: tuple[str, ...] = ()

    @classmethod
    def convert(cls, game, value):
        components = [0.0, 0.0, 0.0]
        for key, tokens in scan_keyed(value):
            if key and key.upper() in cls.indexes and tokens:
                components[cls.indexes.index(key.upper())] = float(tokens[0])
        return components


class _Coords(_Complex):
    indexes = ("X", "Y", "Z")


Coords = Annotated[list[float], _Coords]


class _CoordsList(Multivalued):
    """A repeated `X: Y: Z:` offset, one coordinate per line (e.g. an object's
    `GeometryRotationAnchorOffset`, which repeats once per geometry block). `Multivalued` so each
    occurrence stays a separate `Coords` instead of having its axis tokens flattened together."""

    @classmethod
    def convert(cls, game, value):
        return [
            _Coords.convert(game, line) for line in (value if isinstance(value, list) else [value])
        ]


CoordsList = Annotated[list[list[float]], _CoordsList]


class _RawList(Multivalued):
    """Each occurrence of a repeated key kept verbatim as one string element, with no token
    splitting - for free-form lines whose internal structure isn't modeled (e.g. a colon-keyed
    `GeometryOther` spec, which repeats once per extra geometry block)."""

    @classmethod
    def convert(cls, game, value):
        return list(value) if isinstance(value, list) else [value]


RawList = Annotated[list[str], _RawList]


class _RGB(_Complex):
    indexes = ("R", "G", "B")


RGB = Annotated[list[float], _RGB]


class _RGBA(_Complex):
    """An `R:255 G:255 B:255 A:255` colour. A missing alpha defaults to fully opaque (255),
    matching the engine's `ParseColorRgba`."""

    indexes = ("R", "G", "B", "A")

    @classmethod
    def convert(cls, game, value):
        components = [0.0, 0.0, 0.0, 255.0]
        for key, tokens in scan_keyed(value):
            if key and key.upper() in cls.indexes and tokens:
                components[cls.indexes.index(key.upper())] = float(tokens[0])
        return components


RGBA = Annotated[list[float], _RGBA]


def _names_enum_member(element, token) -> bool:
    """Whether `token` already names a member of a strict enum element. Such a token wins
    over a same-named `#define` (the `KindOf` bit `GANDALF` stays the flag). The leading
    `+`/`-` of a list override is ignored; open/non-enum elements have no members."""
    members = getattr(element, "__members__", None)
    if not members:
        return False
    key = token[1:] if token[:1] in "+-" else token
    return key in members


def _expand_macros(game, tokens, element=None, _depth=0):
    """Replace any macro token with the tokens it stands for, recursively (engine `#define`s
    are textual, so a macro naming a list of flags expands in place). A non-macro token, or
    one already naming a member of the `element` enum, is kept as-is."""
    if _depth > 50:  # a self-referential macro would otherwise loop forever
        return tokens
    out: list[str] = []
    for token in tokens:
        if _names_enum_member(element, token):
            out.append(token)
            continue
        resolved = game.get_macro(token)
        if isinstance(resolved, str) and resolved != token:
            out.extend(_expand_macros(game, resolved.split(), element, _depth + 1))
        else:
            out.append(token)
    return out


class _List(Multivalued):
    def __init__(self, element=_String, start=0):
        self.element = element
        self.start = start

    def __getitem__(self, params):
        cls = type(self)
        if isinstance(params, tuple):
            return cls(params[0], params[1])
        return cls(params)

    def convert(self, game, value):
        element = resolve_annotation(self.element)
        if is_multivalued(element):
            # A multivalued element consumes a whole line's tokens, so a line is never split:
            # one line is one element, a repeated key one element per occurrence.
            items = value if isinstance(value, list) else [value]
        elif isinstance(value, list):
            # Repeated key with a scalar element: flatten every occurrence's tokens into one list.
            items = _expand_macros(game, [tok for line in value for tok in line.split()], element)
        else:
            items = _expand_macros(game, value.split(), element)
        return [element.convert(game, item) for item in items[self.start :]]


if TYPE_CHECKING:
    # `List[X]` types as `list[X]`; at runtime it is the converter instance, whose
    # `__getitem__` builds the configured `_List`. Same split for the other generics below.
    List = list
else:
    List = _List()


class _FlagList(_List):
    """A whole-set flag list (`KindOf = IMMOBILE STRUCTURE`). Unlike a plain `List` (which a
    repeated key extends), the engine *replaces* the set each time the key reappears, so the
    last line wins; the converter keeps it and warns on the rest."""

    def convert(self, game, value):
        if isinstance(value, list):
            game.warn(
                "repeated-flag-field",
                f"set {len(value)} times; only the last set of flags takes effect",
                {"count": len(value)},
            )
            value = value[-1]
        return super().convert(game, value)


if TYPE_CHECKING:
    FlagList = list
else:
    FlagList = _FlagList()


# A token is a `"quoted name"` (kept whole, so a name with spaces stays one token) or a run of
# non-whitespace. Mirrors the header tokenizer in objects.py.
_QUOTED_TOKEN = re.compile(r'"[^"]*"|\S+')


class _QuotedList(_List):
    """A list whose elements may be `"quote-wrapped"` names containing spaces, so it splits on
    whitespace *outside* quotes rather than at every space (`GameMapToUseOn = "My Map" "<ANY>"`
    is two tokens, not five). Quotes are kept on each token, exactly as a single `MapFile`/`String`
    keeps them - the asset/reference layers strip them when resolving."""

    def convert(self, game, value):
        element = resolve_annotation(self.element)
        lines = value if isinstance(value, list) else [value]
        tokens = [token for line in lines for token in _QUOTED_TOKEN.findall(line)]
        tokens = _expand_macros(game, tokens, element)
        return [element.convert(game, token) for token in tokens[self.start :]]


if TYPE_CHECKING:
    QuotedList = list
else:
    QuotedList = _QuotedList()


class _Tuple(Multivalued):
    def __init__(self, *element_types):
        self.element_types = element_types

    def __getitem__(self, params):
        if not isinstance(params, tuple):
            params = (params,)
        return _Tuple(*params)

    def convert(self, game, value):
        converters = [resolve_annotation(t) for t in self.element_types]
        if isinstance(value, str):
            # Split at paren depth zero so a `#OP( a b )` expression stays in one slot; the
            # final slot keeps any remaining tokens, like `str.split(maxsplit=...)`.
            tokens = _split_operands(value)
            if len(tokens) > len(converters):
                head = tokens[: len(converters) - 1]
                items = head + [" ".join(tokens[len(converters) - 1 :])]
            else:
                items = tokens
        else:
            items = list(value)
        out = []
        for index, item in enumerate(items):
            # Extra tokens beyond the declared slots reuse the last converter.
            converter = converters[index] if index < len(converters) else converters[-1]
            out.append(converter.convert(game, item))
        # Fewer tokens than slots: the trailing (optional) slots resolve to None.
        out.extend(None for _ in range(len(items), len(converters)))
        return tuple(out)


if TYPE_CHECKING:
    # Variadic: `Tuple[A, B, ...]` types as `tuple[A, B, ...]` (a bare `tuple` alias would be
    # read as taking no parameters).
    type Tuple[*Ts] = tuple[*Ts]
else:
    Tuple = _Tuple()


class _Union:
    def __init__(self, *types):
        self.types = types

    def __getitem__(self, params):
        if not isinstance(params, tuple):
            params = (params,)
        return _Union(*params)

    def convert(self, game, value):
        for option in self.types:
            converter = resolve_annotation(option)
            try:
                return converter.convert(game, value)
            except (ValueError, KeyError, TypeError):
                continue
        raise ValueError(f"{value!r} matched none of {self.types}")


if TYPE_CHECKING:
    # A value that converts as whichever option matches first; statically the union of them.
    type Union[A, B] = A | B
else:
    Union = _Union()


class _KeyValuePair(Multivalued):
    def __init__(self, *values):
        self.values = values

    def __getitem__(self, params):
        if not isinstance(params, tuple):
            params = (params,)
        return _KeyValuePair(*params)

    def convert(self, game, value):
        pairs: dict[str, object] = {}
        spec = self.values or (_String,)
        if isinstance(value, list):
            tokens = [token for line in value for token in line.split()]
        else:
            tokens = value.split()
        for value_type, raw in zip_longest(spec, tokens, fillvalue=spec[-1]):
            key, _, raw_value = raw.partition(":")
            converter = resolve_annotation(value_type)
            if isinstance(converter, _List):
                element = resolve_annotation(converter.element)
                pairs.setdefault(key, []).append(element.convert(game, raw_value))
            else:
                pairs[key] = converter.convert(game, raw_value)
        return pairs


if TYPE_CHECKING:
    # A colon-keyed record always converts to `dict[str, object]`; the (variadic) subscript
    # only selects the per-key value converters at runtime, so the phantom params are discarded.
    class KeyValuePair[*Ts](dict[str, object]): ...
else:
    KeyValuePair = _KeyValuePair()


# Reference scalars: a field names a top-level definition of the matching kind, keyed to the
# game table it registers into. The converter resolves the name to the registered object, or
# passes the raw name through when it is not (yet) present - hence the `<block> | str` types.
_SoundRef = Reference("audioevents")
FXList = Annotated["_FXListBlock | str", Reference("fxlists")]
Sound = Annotated["AudioEvent | str", _SoundRef]
ParticleSystem = Annotated["FXParticleSystem | str", Reference("particlesystems")]
Image = Annotated["MappedImage | str", Reference("mappedimages")]
EvaEvent = Annotated["NewEvaEvent | PredefinedEvaEvent | str", Reference("evaevents")]
Cursor = Annotated["MouseCursor | str", Reference("cursors")]
# A soft ObjectCreationList reference (resolves when loaded, else the raw name passes through).
# Unlike the strict `ObjectCreationList` field converter, this never raises on a dangling name,
# so it suits a colon-keyed record value (`RiderOCL:OCL_...`) read in isolation.
ObjectCreationListRef = Annotated["ObjectCreationList | str", Reference("objectcreationlists")]
# `animations` is not modelled as a block, so the name always passes through as a string.
Animation = Annotated[str, Reference("animations")]

# A model bone name: opaque token, not a cross-reference.
Bone = Annotated[str, _Opaque]

# A model subobject (mesh part) name: opaque, checkable only against the model, never the ini.
SubObject = Annotated[str, _Opaque]


class _AssetFile:
    """A reference to an on-disk asset file, kept as its raw path/name (runtime-identical to
    `String`). The annotation records the extension(s) the engine expects, so the linter can
    check the file exists under the mod's asset folders and is of the right kind."""

    extensions: tuple[str, ...] = ()

    @staticmethod
    def convert(game, value):
        return value


class _TextureFile(_AssetFile):
    extensions = (".tga", ".dds")


class _ModelFile(_AssetFile):
    extensions = (".w3d",)


class _AudioFile(_AssetFile):
    extensions = (".wav", ".mp3")


class _SoundFile(_AssetFile):
    # A streamed/ambient audio file (same shape as `_AudioFile`; a separate marker keeps the
    # engine's distinction between a one-shot audio event file and a streamed source).
    extensions = (".wav", ".mp3")


class _MapFile(_AssetFile):
    # A WorldBuilder layout: a playable map (`.map`) or an AI base/library layout (`.bse`).
    # A field like `AIBase.Map` names a base layout (`.bse`), `GameMapToUseOn` a map (`.map`);
    # both are `MapFile`, so the engine may resolve either extension.
    extensions = (".map", ".bse")


TextureFile = Annotated[str, _TextureFile]
ModelFile = Annotated[str, _ModelFile]
AudioFile = Annotated[str, _AudioFile]
SoundFile = Annotated[str, _SoundFile]
MapFile = Annotated[str, _MapFile]

# Soft cross-references (resolve when loaded, else the raw name passes through) to tables that
# had no dedicated alias yet. Mirror `Animation`/`ObjectCreationListRef`: str-typed, the
# converter resolves the name; dangling-name checks are the linter's job.
Emotion = Annotated[str, Reference("emotions")]
WeaponRef = Annotated[str, Reference("weapons")]
MusicTrackRef = Annotated[str, Reference("musictracks")]
BannerTypeRef = Annotated[str, Reference("bannertypes")]
ArmyIcon = Annotated[str, Reference("livingworldarmyicons")]
PlayerTemplateRef = Annotated[str, Reference("livingworldplayertemplates")]
ObjectRef = Annotated[str, Reference("objects")]
UpgradeRef = Annotated[str, Reference("upgrades")]
ScienceRef = Annotated[str, Reference("sciences")]
ModifierRef = Annotated[str, Reference("modifiers")]
FactionRef = Annotated[str, Reference("factions")]
CrowdResponseRef = Annotated[str, Reference("crowdresponses")]
CommandButtonRef = Annotated[str, Reference("commandbuttons")]
AutoResolveBodyRef = Annotated[str, Reference("autoresolvebodys")]
AutoResolveCombatChainRef = Annotated[str, Reference("autoresolvecombatchains")]
AutoResolveLeadershipRef = Annotated[str, Reference("autoresolveleaderships")]
RegionCampaignRef = Annotated[str, Reference("livingworldregioncampaigns")]
BuildingIconRef = Annotated[str, Reference("livingworldbuildingicons")]
DamageFXRef = Annotated[str, Reference("damagefxs")]

# `AnimState:NAME AnimTime:0 TriggerTime:0` - the engine's colon-keyed pair form.
AnimAndDuration = KeyValuePair


class FilterList:
    """An include/exclude filter over object names and kindof flags."""

    members: list = []

    def __init__(self, value, game):
        self.descriptor = None
        self.relations: list = []
        self.inclusion: list = []
        self.exclusion: list = []

        for token in value.split():
            if token in Descriptors.__members__:
                self.descriptor = Descriptors[token]
            elif token in Relations.__members__:
                self.relations.append(Relations[token])
            elif token.startswith(("-", "+")):
                converted = self._resolve_member(game, token[1:])
                if token[0] == "-":
                    self.exclusion.append(converted)
                else:
                    self.inclusion.append(converted)

    def _resolve_member(self, game, name):
        for member in self.members:
            converter = resolve_annotation(member)
            try:
                return converter.convert(game, name)
            except (KeyError, ValueError):
                continue
        raise ValueError(f"expected any of {self.members} but found {name}")

    @classmethod
    def convert(cls, game, value):
        return cls(value, game)

    def __repr__(self):
        return f"<{type(self).__name__}>"


class ObjectFilter(FilterList):
    members = [KindOf, "Object"]


class DeathTypeFilter(FilterList):
    members = [DeathType]


class DamageTypeFilter(FilterList):
    members = [DamageType]


class _ScaledObjectFilter(Multivalued):
    """A multiplier optionally scoped to an object filter (`DamageScalar`): `50%` scales all
    damage, `50% NONE +COMMANDCENTER` only damage to matching objects (the filter is `None`
    when the multiplier stands alone). Repeats, so `Multivalued`, always yielding a list."""

    Scalar: float
    ObjectFilter: "t.ObjectFilter | None"

    def __init__(self, scalar, object_filter):
        self.Scalar = scalar
        self.ObjectFilter = object_filter

    @classmethod
    def convert(cls, game, value):
        lines = value if isinstance(value, list) else [value]
        return [cls._one(game, line) for line in lines]

    @classmethod
    def _one(cls, game, value):
        # The multiplier and filter may be parted by a tab (`0.0\tANY +HERO`), so split on
        # the first whitespace run, not a space.
        parts = value.split(None, 1)
        first = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        return cls(_Float.convert(game, first), ObjectFilter.convert(game, rest) if rest else None)

    def __repr__(self):
        return f"<ScaledObjectFilter {self.Scalar}>"


ScaledObjectFilter = Annotated[list[_ScaledObjectFilter], _ScaledObjectFilter]


class _Nullable:
    """Wraps a converter so a `None`/`NONE`/empty sentinel yields None - many reference
    fields accept the literal `None` to mean "no target" (`CommandButton.Object = NONE`).
    Any other value is delegated to the wrapped converter."""

    def __init__(self, inner=_String):
        self.inner = inner

    def __getitem__(self, params):
        return _Nullable(params)

    def convert(self, game, value):
        if value is None or (isinstance(value, str) and value.strip().lower() in ("", "none")):
            return None
        return resolve_annotation(self.inner).convert(game, value)


if TYPE_CHECKING:
    # `Nullable[X]` accepts a `None`/`NONE` sentinel as well as an `X`.
    type Nullable[T] = T | None
else:
    Nullable = _Nullable()


_AXES = {"X": 0, "Y": 1, "Z": 2}


def scan_keyed(value: str) -> list[tuple[str | None, list[str]]]:
    """Scan a colon-keyed line into ordered `(key, [tokens])` groups. A token `Key:inline`
    opens group `Key` (empty for a trailing-colon `Key:`); each following bare token extends
    the current group, so a value may spill across tokens (`X: -48`) or list several
    (`Excluded:A B`). Bare tokens before any key fall under `None`. Shared by the per-record
    converters so each can dispatch on the key.
    """
    groups: list[tuple[str | None, list[str]]] = []
    for token in value.split():
        head, sep, rest = token.partition(":")
        if sep:
            groups.append((head, [rest] if rest else []))
        elif groups:
            groups[-1][1].append(token)
        else:
            groups.append((None, [token]))
    return groups


class KeyedRecord:
    """A single colon-keyed line (`AnimState:DEATH_2 AnimTime:3000 RiderOCL:OCL_Foo`) typed
    declaratively. Each subclass names its keys as annotated fields whose *name is the INI key
    verbatim* (`RiderOCL: ObjectCreationListRef`), so the parsed value reads back under that
    key (`record.RiderOCL`), converted and validated by the field's converter - the same
    `Annotated[PyType, converter]` aliases that type `IniObject` fields.

    An absent key takes its class-body default (`Required: List[...] = []`), else None; a
    mutable default is copied per instance. Unknown keys are ignored. Subclass `KeyedRecordList`
    for the repeating form (one record per line).
    """

    _keyspec: dict[str, object] = {}
    _record_defaults: dict[str, object] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Move class-body defaults out of the namespace so they don't shadow the parsed
        # attributes; keep them as each key's fallback (mirrors IniObject.__init_subclass__).
        own_defaults = {}
        for field in list(cls.__dict__.get("__annotations__", {})):
            if field in cls.__dict__:
                own_defaults[field] = cls.__dict__[field]
                delattr(cls, field)
        cls._own_record_defaults = own_defaults

        keyspec: dict[str, object] = {}
        defaults: dict[str, object] = {}
        for base in reversed(cls.__mro__):
            for key, annotation in getattr(base, "__annotations__", {}).items():
                if not key.startswith("_"):  # internal bookkeeping fields are not INI keys
                    keyspec[key] = annotation
            defaults.update(base.__dict__.get("_own_record_defaults", {}))
        cls._keyspec = keyspec
        cls._record_defaults = defaults

    def __init__(self, **values):
        for name in self._keyspec:
            if name in values:
                setattr(self, name, values[name])
                continue
            default = self._record_defaults.get(name)
            if isinstance(default, (list, dict, set)):
                default = type(default)(default)
            setattr(self, name, default)

    @classmethod
    def _parse(cls, game, line):
        record = cls()
        for key, tokens in scan_keyed(line):
            if key in cls._keyspec and tokens:
                converter = resolve_annotation(cls._keyspec[key])
                setattr(record, key, converter.convert(game, " ".join(tokens)))
        return record

    @classmethod
    def convert(cls, game, value):
        return cls._parse(game, value if isinstance(value, str) else " ".join(value))

    def __repr__(self):
        shown = " ".join(f"{key}={getattr(self, key)!r}" for key in self._keyspec)
        return f"<{type(self).__name__} {shown}>"


class KeyedRecordList(KeyedRecord, Multivalued):
    """A repeating colon-keyed record: one `KeyedRecord` per line, so a field typed with it
    reads as `list[Subclass]` (via the `Annotated[list[_X], _X]` alias idiom)."""

    @classmethod
    def convert(cls, game, value):
        lines = value if isinstance(value, list) else [value]
        return [cls._parse(game, line) for line in lines]


def _apply_axis(coord: list[float], token: str) -> None:
    """Set one axis of a 3-vector in place from an ``AXIS:number`` token (`X:40`)."""
    axis, _, number = token.partition(":")
    number = number.strip()
    if number:
        coord[_AXES[axis.strip().upper()]] = float(number)


class _ScienceRequirements(Multivalued):
    """A science prerequisite expression (`None` = no requirement). `OR` separates
    alternative groups, whitespace within a group lists all-required sciences, so
    `A OR B C` parses to `[[A], [B, C]]` - any one group satisfies it."""

    @classmethod
    def convert(cls, game, value):
        lines = value if isinstance(value, list) else [value]
        groups: list[list] = []
        for line in lines:
            if line.strip().lower() in ("", "none"):
                continue
            for part in line.split(" OR "):
                names = part.split()
                if names:
                    groups.append([game.tables.get("sciences", {}).get(n, n) for n in names])
        return groups


# A list of all-required groups; each group is a list of `Science` definitions (or raw names).
ScienceRequirements = Annotated[list[list], _ScienceRequirements]


class UpgradeWithDelay:
    """A `ModifierList.Upgrade` grant (`Upgrade_A Upgrade_B Delay:1000`), the engine's
    `ModifierUpgrade`: every leading non-colon token is an upgrade applied together (resolved
    to the loaded upgrade, else its raw name), optionally after a `Delay` in ms (None when
    absent)."""

    def __init__(self, upgrades=None, delay=None):
        self.Upgrades = upgrades if upgrades is not None else []
        self.Delay = delay

    @classmethod
    def convert(cls, game, value):
        upgrade_ref = Reference("upgrades")
        upgrades: list = []
        delay = None
        for key, tokens in scan_keyed(value if isinstance(value, str) else " ".join(value)):
            if key is None:
                upgrades.extend(upgrade_ref.convert(game, token) for token in tokens)
            elif key == "Delay" and tokens:
                delay = _Int.convert(game, tokens[0])
        return cls(upgrades, delay)

    def __repr__(self):
        return f"<UpgradeWithDelay {self.Upgrades} delay={self.Delay}>"


class RespawnRules(KeyedRecord):
    """A `RespawnUpdate.RespawnRules` record (`AutoSpawn:No Cost:1500 Time:60000 Health:100%`):
    whether the hero respawns automatically, its respawn `Cost` and `Time` (ms, macros
    resolved), and the `Health` it returns with as a fraction (a `%` becomes a fraction).
    Absent keys are None."""

    AutoSpawn: Bool
    Cost: Int
    Time: Int
    Health: Float


class DeathEntry(KeyedRecord):
    """A `DetachableRiderUpdate.DeathEntry` record (`AnimState:DEATH_2 AnimTime:3000
    RiderOCL:OCL_RohirrimSpawnDeadRider`): the ModelCondition the riderless mount plays on the
    rider's death, its duration in ms, and the ObjectCreationList that spawns the dismounted
    rider (resolved to the loaded list, else its raw name). Absent keys are None."""

    AnimState: ModelCondition
    AnimTime: Int
    RiderOCL: ObjectCreationListRef


class _AttackPriorityTarget(Multivalued):
    """One `Target =` line of an `AttackPriority` (`Target = GondorFighter 10`): the object the
    AI weights and its integer priority. `Target` resolves to the loaded object, else its raw
    name; `Value` is the weight. Repeats, one entry per line."""

    Target: "Object | str | None"
    Value: int | None

    def __init__(self, target, value):
        self.Target = target
        self.Value = value

    @classmethod
    def convert(cls, game, value):
        return [cls._one(game, line) for line in (value if isinstance(value, list) else [value])]

    @classmethod
    def _one(cls, game, line):
        tokens = line.split()
        target = game.tables.get("objects", {}).get(tokens[0], tokens[0]) if tokens else None
        value = int(eval_number(game, tokens[1])) if len(tokens) > 1 else None
        return cls(target, value)

    def __repr__(self):
        return f"<AttackPriorityTarget {getattr(self.Target, 'name', self.Target)}={self.Value}>"


# A list of `Target` weightings, one per repeated `Target =` line.
AttackPriorityTarget = Annotated[list[_AttackPriorityTarget], _AttackPriorityTarget]


class _FCurveKey(KeyedRecordList):
    """One `Key =` of an `FCurve` (`Key = T:0 V:100 I:0 O:0`): the keyframe time `T` and value
    `V`, plus optional in/out tangent slopes `I`/`O`. Repeats, one entry per line."""

    T: Float
    V: Float
    I: Float  # noqa: E741  (the engine's key for the in-tangent)
    O: Float  # noqa: E741  (the engine's key for the out-tangent)


# A list of keyframes, one per repeated `Key =` line of an FCurve.
FCurveKey = Annotated[list[_FCurveKey], _FCurveKey]


class _BannerCarrierPosition(Multivalued):
    """Where a horde's banner carrier stands, per member unit type (repeatable):
    `UnitType:LAGondorFighter Pos:X:40.0 Y:0.0` pairs a member with an X/Y/Z offset
    (missing axes default to 0)."""

    UnitType: "Object | str | None"
    Pos: list[float]

    def __init__(self, unit_type, position):
        self.UnitType = unit_type
        self.Pos = position

    @classmethod
    def convert(cls, game, value):
        return [cls._one(game, line) for line in (value if isinstance(value, list) else [value])]

    @classmethod
    def _one(cls, game, value):
        unit_type = None
        position = [0.0, 0.0, 0.0]
        for key, tokens in scan_keyed(value):
            if key == "UnitType" and tokens:
                unit_type = game.tables.get("objects", {}).get(tokens[0], tokens[0])
            elif key == "Pos":
                for token in tokens:  # the inline `X:40.0` after `Pos:`
                    _apply_axis(position, token)
            elif key and key.upper() in _AXES and tokens:
                position[_AXES[key.upper()]] = float(tokens[0])
        return cls(unit_type, position)

    def __repr__(self):
        return f"<BannerCarrierPosition {self.UnitType}>"


BannerCarrierPosition = Annotated[list[_BannerCarrierPosition], _BannerCarrierPosition]


class RangeDuration:
    """A duration as a single time or a `Min:`/`Max:` range. `4000` sets both bounds; a range
    may be `Min:500 Max:1000` or two bare numbers `10 500`. Times are in ms; `average` is the
    mean."""

    def __init__(self, minimum, maximum):
        self.min = minimum
        self.max = maximum

    @property
    def average(self):
        return (self.min + self.max) / 2

    @classmethod
    def convert(cls, game, value):
        text = (value if isinstance(value, str) else " ".join(value)).strip()
        tokens = text.split()
        if tokens and tokens[0].partition(":")[0].upper() == "MIN":
            # `scan_keyed` keeps a `Min:1300` and a spaced `Min: 1300` equivalent, gathering
            # each bound's value whether it sits inline with the colon or as the next token.
            bounds: dict[str, float] = {}
            for key, group in scan_keyed(text):
                if key and group:
                    # Rejoin the group: a `#MULTIPLY( A 2 )` bound has spaces, so `scan_keyed`
                    # spreads it across the list - `group[0]` alone is a broken `#MULTIPLY(`.
                    bounds[key.upper()] = eval_number(game, " ".join(group))
            minimum = bounds.get("MIN")
            return cls(minimum, bounds.get("MAX", minimum))
        # Two bare numbers are a range; a `#OP( a b )` expression also has spaces, so split
        # only when it is not one.
        if len(tokens) >= 2 and not text.startswith("#"):
            return cls(eval_number(game, tokens[0]), eval_number(game, tokens[1]))
        single = eval_number(game, text)
        return cls(single, single)

    def __repr__(self):
        return f"<RangeDuration {self.min}..{self.max}>"


class _ContactPoint(Multivalued):
    """An attack/geometry contact point: an X/Y/Z offset (matched like `Coords`) with an
    optional trailing bone token (`X:0 Y:0 Z:112 Swoop`). Repeats, one point per line, so
    `Multivalued`."""

    Position: list[float]
    Bone: str | None

    def __init__(self, position, bone=None):
        self.Position = position
        self.Bone = bone

    @classmethod
    def convert(cls, game, value):
        return [cls._one(game, line) for line in (value if isinstance(value, list) else [value])]

    @classmethod
    def _one(cls, game, value):
        bone = None
        for token in value.split():
            if ":" in token:
                continue  # an axis token, handled by Coords below
            try:
                float(token)  # a bare axis value spilled by `Y: -48`
            except ValueError:
                bone = token
        return cls(_Coords.convert(game, value), bone)

    def __repr__(self):
        return f"<ContactPoint pos={self.Position} bone={self.Bone!r}>"


ContactPoint = Annotated[list[_ContactPoint], _ContactPoint]


class _AudioLoopCondition(KeyedRecordList):
    """One `ModelCondition` of a `ModelConditionAudioLoopClientBehavior`:
    `Required:<flags> Excluded:<flags> Sound:<event>` loops a sound while the unit holds
    every `Required` condition and none `Excluded`. Repeats, so a list per field."""

    Required: List[ModelCondition] = []
    Excluded: List[ModelCondition] = []
    Sound: t.Sound


AudioLoopCondition = Annotated[list[_AudioLoopCondition], _AudioLoopCondition]


class _VolumeSliderMultiplier(KeyedRecordList):
    """One `VolumeSliderMultiplier =` line of an `AudioEvent` (`Slider:Voice Multiplier:70`):
    scales the event's volume by `Multiplier` percent for the named mixer `Slider`. Repeats,
    one entry per slider, so a field typed with it reads as a list."""

    Slider: Opaque
    Multiplier: Int


VolumeSliderMultiplier = Annotated[list[_VolumeSliderMultiplier], _VolumeSliderMultiplier]


class _GroupedByKey(Multivalued):
    """A repeated `KEY VALUE...` field collected into `{key: [value, ...]}` (each occurrence's
    first token is the key, the rest values). Subscript with the key/value converters, e.g.
    `GroupedByKey[SlowDeathPhase, "ObjectCreationList"]` for a SlowDeath `OCL = <phase> <ocl>`."""

    def __init__(self, key=_String, value=_String):
        self.key = key
        self.value = value

    def __getitem__(self, params):
        return _GroupedByKey(*params) if isinstance(params, tuple) else _GroupedByKey(params)

    def convert(self, game, value):
        key_converter = resolve_annotation(self.key)
        value_converter = resolve_annotation(self.value)
        grouped: dict = {}
        for line in value if isinstance(value, list) else [value]:
            tokens = line.split()
            if not tokens:
                continue
            key = key_converter.convert(game, tokens[0])
            bucket = grouped.setdefault(key, [])
            bucket.extend(value_converter.convert(game, token) for token in tokens[1:])
        return grouped


if TYPE_CHECKING:
    # `GroupedByKey[K, V]` collects repeated `K V...` lines into `{k: [v, ...]}`.
    class GroupedByKey[K, V](dict[K, list[V]]): ...
else:
    GroupedByKey = _GroupedByKey()


class _TimedPosition(Multivalued):
    """A position offset paired with a time in logic frames (`X: 0.0 Y: 0.0 T: 5`): an X/Y/Z
    offset (missing axes default to 0) and `T` in frames. Repeats, one waypoint per line, so
    `Multivalued`."""

    _AXES = {"X": 0, "Y": 1, "Z": 2}

    Position: list[float]
    T: int

    def __init__(self, position, time):
        self.Position = position
        self.T = time

    @classmethod
    def convert(cls, game, value):
        lines = value if isinstance(value, list) else [value]
        return [cls._one(game, line) for line in lines]

    @classmethod
    def _one(cls, game, line):
        position = [0.0, 0.0, 0.0]
        time = 0
        for key, raw in re.findall(r"([XYZT])\s*:\s*(\S+)", line):
            if key == "T":
                time = int(eval_number(game, raw))
            else:
                position[cls._AXES[key]] = eval_number(game, raw)
        return cls(position, time)

    def __repr__(self):
        return f"<TimedPosition pos={self.Position} t={self.T}>"


TimedPosition = Annotated[list[_TimedPosition], _TimedPosition]


class _RankInfo(Multivalued):
    """One rank of a horde's formation: `RankNumber:N UnitType:Obj Position:X:.. Y:.. Position:...`
    - a rank number, the unit filling it, and one repeating `Position` per slot (each opens a
    coordinate the following axis tokens fill). Repeats, one line per rank, so `Multivalued`."""

    RankNumber: int | None
    UnitType: "Object | str | None"
    Position: list[list[float]]

    def __init__(self, rank_number=None, unit_type=None, positions=None):
        self.RankNumber = rank_number
        self.UnitType = unit_type
        self.Position = positions if positions is not None else []

    @classmethod
    def convert(cls, game, value):
        lines = value if isinstance(value, list) else [value]
        return [cls._one(game, line) for line in lines]

    @classmethod
    def _one(cls, game, line):
        rank = cls()
        coord = None  # the Position currently being filled
        for key, tokens in scan_keyed(line):
            if key == "RankNumber" and tokens:
                rank.RankNumber = _Int.convert(game, tokens[0])
            elif key == "UnitType" and tokens:
                rank.UnitType = resolve_annotation("Object").convert(game, tokens[0])
            elif key == "Position":
                coord = [0.0, 0.0, 0.0]
                rank.Position.append(coord)
                for token in tokens:  # the inline `X:..` after `Position:`
                    _apply_axis(coord, token)
            elif key and key.upper() in _AXES and coord is not None and tokens:
                coord[_AXES[key.upper()]] = float(tokens[0])
        return rank

    def __repr__(self):
        return f"<RankInfo rank={self.RankNumber} positions={len(self.Position)}>"


RankInfo = Annotated[list[_RankInfo], _RankInfo]


class _ComboHorde(KeyedRecordList):
    """A horde-combine recipe (repeating): `Target:<horde> Result:<horde> [InitiateVoice:<sound>]`
    - combining this horde with `Target` produces `Result`. Repeats, one recipe per line."""

    Target: "Object"
    Result: "Object"
    InitiateVoice: Sound


ComboHorde = Annotated[list[_ComboHorde], _ComboHorde]


class _ModifierEntry(Multivalued):
    """One `Modifier =` line of a `ModifierList`: `<ModifierType> <amount> [<DamageType>...]`
    (`SPEED 125%`, `ARMOR 25% PIERCE`). `Amount` is the resolved number (an attached `%` becomes
    a fraction, a `#OP( ... )` is evaluated), or `None` when the value is non-numeric; `Value`
    keeps the raw token for display/macro resolution. A detached `%` token (`PRODUCTION 1.25 %`)
    is dropped - the engine ignores it, taking the value as-is. `DamageTypes` scope
    `ARMOR`/`INVULNERABLE` to specific types (empty otherwise). Repeats, one entry per line,
    so `Multivalued`."""

    Type: ModifierType
    Value: str | None
    Amount: float | None
    DamageTypes: list[DamageType]

    def __init__(
        self,
        kind: ModifierType,
        value: str | None = None,
        amount: float | None = None,
        damage_types: list[DamageType] | None = None,
    ):
        self.Type = kind
        self.Value = value
        self.Amount = amount
        self.DamageTypes = damage_types if damage_types is not None else []

    @classmethod
    def convert(cls, game, value):
        lines = value if isinstance(value, list) else [value]
        return [cls._one(game, line) for line in lines]

    @classmethod
    def _one(cls, game, line):
        tokens = line.split(maxsplit=1)
        kind = ModifierType.convert(game, tokens[0])
        if len(tokens) < 2:
            return cls(kind)
        # Split paren-aware so a `#MULTIPLY( a b )` amount stays a single operand.
        operands = _split_operands(tokens[1])
        # A `%` written as its own token (`PRODUCTION 1.25 %`) is a percent marker the engine
        # ignores on a detached value - not a damage type. Drop it so the amount reads as-is
        # (the macro's plain multiplier) and the trailing operands stay genuine damage types.
        # An attached `%` (`130%`) is left for `eval_number` to scale.
        operands = [operand for operand in operands if operand != "%"]
        raw = operands[0] if operands else None
        try:
            amount = eval_number(game, raw) if raw is not None else None
        except (ValueError, KeyError):
            amount = None
        damage_types = [DamageType.convert(game, token) for token in operands[1:]]
        return cls(kind, raw, amount, damage_types)

    def __repr__(self):
        return f"<ModifierEntry {self.Type} {self.Value!r} types={self.DamageTypes}>"


ModifierEntry = Annotated[list[_ModifierEntry], _ModifierEntry]


class ContainCondition(KeyedRecord):
    """A transport's `ConditionForEntry` (`ModelConditionState: MOUNTED`): the model condition
    a unit must be in to enter. The flag may be the key's inline value or the bare token after."""

    ModelConditionState: ModelCondition


class _AttributeModelCondition:
    """The engine's `ModelConditionState:FLAG` attribute form (`TriggerModelCondition`): drop
    the `ModelConditionState:` key and resolve the flag as a `ModelCondition`."""

    @staticmethod
    def convert(game, value):
        text = value if isinstance(value, str) else " ".join(value)
        _, _, flag = text.partition(":")
        return ModelCondition.convert(game, (flag or text).strip())


AttributeModelCondition = Annotated["ModelCondition", _AttributeModelCondition]


def string_comparator(original, changed):
    """Diff two name->String maps into (changed, deleted, new) name lists."""
    deleted = [name for name in original if name not in changed]
    new = [name for name in changed if name not in original]
    modified = [name for name in original if name in changed and original[name] != changed[name]]
    return modified, deleted, new
