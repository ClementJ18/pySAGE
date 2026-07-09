"""Rules that read the typed schema (the field annotations) of loaded objects."""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.objects import is_multivalued, resolve_annotation
from sage_ini.model.types import Ranged
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.suggest import suggestion_hint
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule


def _converter(obj, key: str):
    """The resolved converter for `key`, or None when the field is unknown."""
    fieldspec = type(obj)._fieldspec
    if key not in fieldspec:
        return None
    try:
        return resolve_annotation(fieldspec[key])
    except KeyError:
        return None


def _is_multivalued(obj, key: str) -> bool | None:
    """Whether `key`'s converter consumes a list; None when the field is unknown."""
    converter = _converter(obj, key)
    return None if converter is None else is_multivalued(converter)


class RepeatedScalarFieldRule(Rule):
    """A scalar attribute set more than once: the engine keeps only the last, so the
    earlier value silently does nothing (almost always a copy-paste leftover)."""

    code = "repeated-field"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj in walk_objects(game):
            for key, value in obj.fields.items():
                if not isinstance(value, list):
                    continue
                if _is_multivalued(obj, key) is not False:
                    continue  # unknown field or a legitimate list converter
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{type(obj).__name__}.{key} is set {len(value)} times; "
                        "only the last value takes effect"
                    ),
                    span=obj._field_spans.get(key, obj.span),
                    severity=Severity.WARNING,
                    extra={"type": type(obj).__name__, "key": key, "count": len(value)},
                )


class UnknownAttributeRule(Rule):
    """An attribute on a typed block that the block's schema does not declare: a still-untyped
    field (a coverage gap) or a misspelled attribute name.

    Raised as an ERROR - the project drives toward 100% schema coverage, so every untyped field
    is a to-do, not background noise. Exhaustive by design (an incomplete schema leaves many
    valid fields untyped), so like `unrecognized-block` it is excluded from the corpus flood
    gate; silence it with `ignore = ["unknown-attribute"]` until the backlog is triaged."""

    code = "unknown-attribute"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj in walk_objects(game):
            cls = type(obj)
            fieldspec = cls._fieldspec
            nested = cls._nested
            # Marker-group markers/members (e.g. the `Geometry*` keys) are known keys even when
            # they appear flat, before their group's first marker line.
            marker_keys = cls._marker_starts.keys() | cls._marker_members.keys()
            for key in obj.fields:
                if key in fieldspec or key in nested or key in marker_keys:
                    continue
                if cls.numbered_slots and key.isdigit():
                    continue  # a valid dynamic slot (`1 = ...`), not an unknown attribute
                hint, suggestion = suggestion_hint(key, (*fieldspec, *nested))
                yield Diagnostic(
                    code=self.code,
                    message=f"{key} is not a known attribute of {type(obj).__name__}.{hint}",
                    span=obj._field_spans.get(key, obj.span),
                    severity=Severity.ERROR,
                    extra={"type": type(obj).__name__, "key": key, "suggestion": suggestion},
                )


class OutOfRangeRule(Rule):
    """A `Ranged` numeric field whose value falls outside its type's interval. It still
    converts, so this is a likely typo (a swapped sign, an extra digit) the engine clamps
    or wraps, not a conversion failure."""

    code = "out-of-range"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj in walk_objects(game):
            for key in obj.fields:
                converter = _converter(obj, key)
                if not (isinstance(converter, type) and issubclass(converter, Ranged)):
                    continue
                try:
                    value = getattr(obj, key)
                except (ValueError, KeyError, TypeError, IndexError):
                    continue  # a non-numeric value is the conversion pass's job
                if value is None or converter.minimum <= value <= converter.maximum:
                    continue
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{type(obj).__name__}.{key} = {value} is outside the valid "
                        f"range {converter.minimum}..{converter.maximum}"
                    ),
                    span=obj._field_spans.get(key, obj.span),
                    severity=Severity.WARNING,
                    extra={
                        "type": type(obj).__name__,
                        "key": key,
                        "value": value,
                        "minimum": converter.minimum,
                        "maximum": converter.maximum,
                    },
                )


class SpuriousBlockLabelRule(Rule):
    """A block written with the `=` form of a header it takes plainly - `ThreatBreakdown =
    <tag>` instead of `ThreatBreakdown <tag>`. The engine tolerates the `=`, so it parses,
    but the `=` does nothing and usually signals a copy-paste slip."""

    code = "spurious-block-label"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj in walk_objects(game):
            if not type(obj).equals_is_spurious:
                continue
            # Only the `=` form is wrong; `Block Tag` (no `=`) is the correct header.
            if not obj._uses_equals:
                continue
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{type(obj).__name__} takes a plain header, not `=`; write "
                    f"`{type(obj).__name__} {obj.name}` instead of "
                    f"`{type(obj).__name__} = {obj.name}`. The engine ignores the `=`."
                ),
                span=obj.span,
                severity=Severity.WARNING,
                extra={"type": type(obj).__name__, "label": obj.name},
            )
