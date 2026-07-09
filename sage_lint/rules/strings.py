"""Rules: every referenced localization label must resolve in the string table, and a map.ini
must not lean on the per-map `map.str` for its strings."""

from collections.abc import Iterator
from pathlib import Path

from sage_ini.model.game import Game
from sage_ini.model.objects import resolve_annotation
from sage_ini.model.types import Label
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.parser.io import read_text
from sage_ini.strings import STR_SUFFIX, parse_str
from sage_ini.suggest import suggestion_hint
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule

# `Label` is a typed alias (`Annotated[str, converter]`); the converter is what a field's
# resolved annotation actually is, so compare against that, not the alias.
_LABEL = resolve_annotation(Label)


def _is_label(obj, key: str) -> bool:
    """Whether `key` is a `Label` field, matching both a scalar `Label` and a
    `List[Label]` (a button's per-state `TextLabel`/`DescriptLabel`)."""
    fieldspec = type(obj)._fieldspec
    if key not in fieldspec:
        return False
    try:
        annotation = resolve_annotation(fieldspec[key])
    except KeyError:
        return False
    if annotation is _LABEL:
        return True
    element = getattr(annotation, "element", None)
    return element is not None and resolve_annotation(element) is _LABEL


def _is_map_file(path: str) -> bool:
    """Whether `path` is map-scoped - under a `maps/` directory (mirrors
    `sage_ini.stats.is_map_path`, but from the file alone)."""
    return any(part.lower() == "maps" for part in Path(path).parts[:-1])


def _label_tokens(obj) -> Iterator[tuple[str, str]]:
    """`(field_key, label_token)` for every `NAMESPACE:key` token in a `Label` field of `obj`."""
    for key, value in obj.fields.items():
        if not _is_label(obj, key):
            continue
        for entry in value if isinstance(value, list) else [value]:
            if not isinstance(entry, str):
                continue
            for token in entry.split():
                if ":" in token:
                    yield key, token


class UnknownStringLabelRule(Rule):
    """A `Label` field naming a string the loaded table does not define (it shows in-game
    as its raw name - a content bug). Lookups are case-insensitive; each `NAMESPACE:key`
    token of a multi-label value is checked, tokens without a `:` left alone. Skipped when
    no string table was loaded, else every label would falsely flag."""

    code = "unknown-string-label"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        if not game.strings:
            return
        known = {label.lower() for label in game.strings}
        for obj in walk_objects(game):
            for key, token in _label_tokens(obj):
                if token.lower() in known:
                    continue
                # Restrict candidates to the token's own namespace so a typo in the
                # key is matched against sibling labels, not every string in the game.
                namespace = token.split(":", 1)[0].lower()
                siblings = [
                    label for label in game.strings if label.split(":", 1)[0].lower() == namespace
                ]
                hint, suggestion = suggestion_hint(token, siblings)
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{type(obj).__name__}.{key} references string {token!r}, "
                        f"which the string table does not define.{hint}"
                    ),
                    span=obj._field_spans.get(key, obj.span),
                    severity=Severity.WARNING,
                    extra={
                        "label": token,
                        "type": type(obj).__name__,
                        "key": key,
                        "suggestion": suggestion,
                    },
                )


class MapLocalStringRule(Rule):
    """A `Label` in a map.ini that resolves against the map's own adjacent `map.str` rather than
    the global string table. Map-scoped `.str` tables live beside their `map.ini` and stay out of
    the global table (`load_strings` skips them), so a string defined only there is per-map: it
    does not reach the rest of the game and is the wrong place for a gameplay label. This flags a
    map.ini string reference the adjacent `map.str` defines so it can be moved to the global table.
    Case-insensitive, one finding per `NAMESPACE:key` token."""

    code = "map-local-string"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        # Adjacent `.str` labels, parsed once per map directory: dir -> {lowered label -> file}.
        by_directory: dict[Path, dict[str, str]] = {}
        for obj in walk_objects(game):
            if not _is_map_file(obj.span.file):
                continue
            labels = self._map_str_labels(Path(obj.span.file).parent, by_directory)
            if not labels:
                continue
            for key, token in _label_tokens(obj):
                source = labels.get(token.lower())
                if source is None:
                    continue
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{type(obj).__name__}.{key} references string {token!r}, which the "
                        f"adjacent {Path(source).name} defines rather than the global string "
                        f"table; a map-local string does not reach the rest of the game, so "
                        f"define it in the global string table instead."
                    ),
                    span=obj._field_spans.get(key, obj.span),
                    severity=Severity.WARNING,
                    extra={
                        "label": token,
                        "type": type(obj).__name__,
                        "key": key,
                        "str_file": source,
                    },
                )

    @staticmethod
    def _map_str_labels(directory: Path, cache: dict[Path, dict[str, str]]) -> dict[str, str]:
        """`{lowered label -> defining file}` for every `.str` table beside a map.ini, cached per
        directory. Unreadable tables are skipped (their own load-error is reported elsewhere)."""
        if directory not in cache:
            labels: dict[str, str] = {}
            for path in sorted(directory.glob(f"*{STR_SUFFIX}")):
                try:
                    text = read_text(path)
                except OSError:
                    continue
                for label in parse_str(text):
                    labels.setdefault(label.lower(), str(path))
            cache[directory] = labels
        return cache[directory]
