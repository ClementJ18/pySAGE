"""Rule: a cross-reference field naming a definition the game never declares.

A `Reference` converter resolves a name to its registered object when present and otherwise
passes the raw name through unchanged (`types.Reference` defers the strict check here on
purpose). So after conversion a *resolved* reference is an `IniObject` and a *dangling* one
is the leftover `str` — the signal this rule keys on. References are found wherever they are
typed: a scalar field, a `List[...]` of them, or a key inside a `KeyedRecord` line (e.g.
`DetachableRiderUpdate.DeathEntry`'s `RiderOCL`).

A kind that the corpus does not model as a block (animations, predefined eva events) leaves
its table empty, so every such name is a bare string by design; the empty-table guard skips
those wholesale rather than flagging all of them.
"""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.objects import resolve_annotation
from sage_ini.model.types import KeyedRecord, Reference
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.suggest import suggestion_hint
from sage_ini.walk import walk_objects
from sage_lint.ruleconfig import sentinels
from sage_lint.rules.base import Rule

# Asset-reference tables this rule does not check. Their names resolve in ways a single-table
# lookup cannot judge: an audio reference resolves across several tables at once
# (`audioevents`/`dialogevents`/`musictracks`/`multisounds`), and art/UI names (images,
# cursors, particle systems, FX) are routinely defined in files outside the gameplay data set
# (or, for some FX fields, carried inside a colon-keyed `Loc:.. FXList:..` record). Checking
# them here floods the mostly-valid base game with false positives; only gameplay/logic
# references (objects, OCLs, weapons, upgrades, ...) are authoritative within the data.
_ASSET_TABLES = frozenset(
    {
        "audioevents",
        "dialogevents",
        "musictracks",
        "multisounds",
        "fxlists",
        "mappedimages",
        "cursors",
        "particlesystems",
        "evaevents",
        "videos",
        "ambientstreams",
        "livingworldsounds",
    }
)

# A sound reference resolves against any of these tables — the engine tries each, so a name
# present in just one is valid. The asset rule must check the union, not a single table, or a
# `DialogEvent`-backed sound would falsely flag as missing from `audioevents`.
_AUDIO_TABLES = frozenset({"audioevents", "dialogevents", "musictracks", "multisounds"})

# The non-audio asset tables the (INFO) asset-reference rule does check, with a friendly noun
# for each; audio is folded in via `_AUDIO_TABLES` below.
_ASSET_NOUN: dict[str, str] = {
    "fxlists": "FXList",
    "particlesystems": "particle system",
}
_CHECKED_ASSET_TABLES = frozenset(_ASSET_NOUN) | _AUDIO_TABLES


def _iter_refs(value, converter, game: Game) -> Iterator[tuple[str, str]]:
    """`(table_key, name)` for every *unresolved* reference reachable through `value` given
    its resolved `converter`. A reference resolves to an `IniObject`, so only a leftover
    `str` is a candidate; converter shapes handled are a bare `Reference`, a `List[...]` of
    one (via its `element`), and a `KeyedRecord` whose keys are themselves typed."""
    if isinstance(converter, Reference):
        if isinstance(value, str):
            yield converter.key, value
    elif (element := getattr(converter, "element", None)) is not None:
        for item in value if isinstance(value, list) else [value]:
            yield from _iter_refs(item, resolve_annotation(element), game)
    elif (element_types := getattr(converter, "element_types", None)) is not None:
        # A `Tuple[...]` slot: each converted value is a tuple aligned to its element types, so
        # a reference in any slot (e.g. the object of a `Tuple[Object, Int]`) is reachable here.
        if isinstance(value, (list, tuple)):
            for slot, annotation in zip(value, element_types, strict=False):
                yield from _iter_refs(slot, resolve_annotation(annotation), game)
    elif isinstance(converter, type) and issubclass(converter, KeyedRecord):
        for record in value if isinstance(value, list) else [value]:
            if record is None:
                continue
            for key, annotation in converter._keyspec.items():
                yield from _iter_refs(
                    getattr(record, key, None), resolve_annotation(annotation), game
                )


def _is_sentinel(name: str) -> bool:
    """Whether `name` is an "intentionally nothing" token the engine treats as no target, so a
    miss is by design, not dangling. `None`/`NONE`/empty are always sentinels; a project adds
    more (e.g. `NoSound`) via the `sentinels` config (`sage_lint.ruleconfig`)."""
    lowered = name.lower()
    return lowered in ("", "none") or lowered in sentinels()


def _iter_candidates(game: Game) -> Iterator[tuple[object, str, str, str]]:
    """`(obj, field, table_key, name)` for every unresolved reference in the game's typed
    fields — the shared front half of the dangling-reference checks. A name with a space or a
    colon is dropped here: a reference is one bareword, never a colon-keyed record value."""
    for obj in walk_objects(game):
        fieldspec = type(obj)._fieldspec
        for key in obj.fields:
            if key not in fieldspec:
                continue
            try:
                converter = resolve_annotation(fieldspec[key])
                value = getattr(obj, key)
            except (ValueError, KeyError, TypeError, IndexError):
                continue  # a bad value is the conversion pass's own diagnostic
            for table_key, name in _iter_refs(value, converter, game):
                if _is_sentinel(name) or " " in name or ":" in name:
                    continue
                yield obj, key, table_key, name


class DanglingReferenceRule(Rule):
    """A typed gameplay cross-reference (an OCL, object, weapon, upgrade, ...) naming a
    definition the loaded game does not declare: in-game the engine finds nothing under that
    name, so whatever the field drives silently does not happen — a content bug. Asset/audio
    kinds are excluded (see `_ASSET_TABLES`, handled by the INFO asset rule below); a kind the
    corpus does not model leaves its table empty and is skipped; and `None` is the engine's
    "nothing" sentinel, left alone."""

    code = "dangling-reference"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj, key, table_key, name in _iter_candidates(game):
            if table_key in _ASSET_TABLES:
                continue
            table = game.tables.get(table_key)
            if not table or game.lookup(table_key, name)[0] is not None:
                continue  # kind not modelled, or it resolves case-insensitively
            hint, suggestion = suggestion_hint(name, table)
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{type(obj).__name__}.{key} references {name!r}, which no "
                    f"{table_key} definition declares.{hint}"
                ),
                span=obj._field_spans.get(key, obj.span),
                severity=Severity.WARNING,
                extra={
                    "name": name,
                    "table": table_key,
                    "type": type(obj).__name__,
                    "key": key,
                    "suggestion": suggestion,
                },
            )


class DanglingAssetReferenceRule(Rule):
    """An FX, particle-system or sound reference naming an asset the loaded game does not
    declare. Reported at INFO, not WARNING: these asset tables are routinely defined in files
    outside the gameplay data set, so a miss is a *hint* (often a typo) rather than a certain
    bug — and the report stays out of the default error/warning view. A table with nothing
    loaded is skipped wholesale (the asset files simply were not part of this build); a sound
    is resolved against the whole audio table union, the way the engine looks it up."""

    code = "dangling-asset-reference"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        audio_names = [
            name
            for table_key in _AUDIO_TABLES
            for name in game.tables.get(table_key, {})
            if isinstance(name, str)
        ]
        audio_known = {name.lower() for name in audio_names}
        for obj, key, table_key, name in _iter_candidates(game):
            if table_key not in _CHECKED_ASSET_TABLES:
                continue
            if table_key in _AUDIO_TABLES:
                if not audio_known or name.lower() in audio_known:
                    continue  # no audio loaded at all, or the sound resolves somewhere
                noun, candidates = "audio", audio_names
            else:
                table = game.tables.get(table_key)
                if not table or game.lookup(table_key, name)[0] is not None:
                    continue
                noun, candidates = _ASSET_NOUN[table_key], table
            hint, suggestion = suggestion_hint(name, candidates)
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{type(obj).__name__}.{key} references {name!r}, which no loaded "
                    f"{noun} definition declares.{hint}"
                ),
                span=obj._field_spans.get(key, obj.span),
                severity=Severity.INFO,
                extra={
                    "name": name,
                    "table": table_key,
                    "type": type(obj).__name__,
                    "key": key,
                    "suggestion": suggestion,
                },
            )
