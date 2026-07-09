"""Rule: an attribute modifier whose visual FX does not last as long as the modifier itself.

A `ModifierList` applies its bonus for `Duration` milliseconds and plays `FX` while it holds.
The effects inside that FX carry their own lifetimes - a `BuffNugget`'s `BuffLifeTime`
(milliseconds) or a particle system's `SystemLifetime` (counted in 30-per-second logic
frames). When a timed effect's lifetime runs more than a second past or short of the modifier's
`Duration`, the visual ends before the bonus wears off or lingers after it has gone - a common
slip when a generic FX is reused for a longer- or shorter-lived modifier. A gap of up to a
second is imperceptible (and often a deliberate round-second reuse), so it is tolerated.

The check runs only when everything resolves and is self-timed: `FX` names a loaded `FXList`,
a particle nugget names a loaded `FXParticleSystem`, and each compared lifetime is set and
positive. A `SystemLifetime`/`BuffLifeTime` of 0 (or unset) means the effect imposes no limit
of its own and is killed when the modifier is removed, so it can never mismatch and is skipped.
A `Duration` or lifetime longer than an hour is an effectively-permanent placeholder rather
than a timed effect, so it is left alone too.
"""

from collections.abc import Iterator

from sage_ini.model.data_blocks import FXList, FXParticleSystem
from sage_ini.model.game import Game
from sage_ini.model.ini_objects import ModifierList
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule

# SAGE logic runs at a fixed 30 frames per second; a particle `SystemLifetime` is a count of
# those frames, so its duration in milliseconds is `frames * 1000 / 30`.
_FRAME_MS = 1000 / 30

# An effect that outlasts or falls short of its modifier by up to a second is close enough:
# the mismatch is imperceptible and often a deliberate round-second reuse of a generic FX. Only
# a gap wider than this window is reported. (This also absorbs the frame quantisation above.)
_TOLERANCE_MS = 1000

# A modifier or effect lasting longer than an hour is an effectively-permanent placeholder, not
# a timed effect meant to line up visually — a `Duration` or lifetime past this is left alone.
_MAX_MS = 60 * 60 * 1000


def _get(obj: object, name: str) -> object:
    """`obj.name`, or None when reading it raises - a bad value there is the conversion pass's
    own diagnostic, not this rule's."""
    try:
        return getattr(obj, name)
    except (ValueError, KeyError, TypeError, IndexError):
        return None


def _lifetime(value: object) -> int | None:
    """`value` as a positive count, else None. Zero or unset means "no self-imposed limit",
    which is never a mismatch."""
    return value if isinstance(value, int) and value > 0 else None


def _effect_lifetimes(fx: FXList) -> Iterator[tuple[str, float]]:
    """`(label, lifetime_ms)` for each timed effect in `fx` whose lifetime can be read: a
    `BuffNugget`'s `BuffLifeTime` (already milliseconds) and a particle system's
    `SystemLifetime` (logic frames converted to milliseconds). Unresolved or unbounded effects
    are omitted."""
    for buff in fx.BuffNugget:
        lifetime = _lifetime(_get(buff, "BuffLifeTime"))
        if lifetime is not None:
            yield "BuffNugget BuffLifeTime", float(lifetime)
    for nugget in fx.ParticleSystem:
        system = _get(nugget, "Name")
        if not isinstance(system, FXParticleSystem):
            continue
        frames = _lifetime(_get(system, "SystemLifetime"))
        if frames is not None:
            yield f"particle system {system.name!r} SystemLifetime", frames * _FRAME_MS


class ModifierFxDurationRule(Rule):
    """A `ModifierList` whose `FX` plays a timed effect (a `BuffNugget` or a self-timed particle
    system) whose lifetime differs from the modifier's `Duration`, so the effect visibly ends
    before the bonus expires or outlasts it. Only self-timed effects with a resolved FX are
    judged; an unbounded effect (killed with the modifier) never mismatches.

    Off by default: the base game ships intentional generic-FX reuse where the visual and the
    modifier disagree by design, so this is opt-in via `--select modifier-fx-duration` rather
    than part of a plain run."""

    code = "modifier-fx-duration"
    default = False

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for modifier in walk_objects(game, ModifierList):
            duration = _lifetime(_get(modifier, "Duration"))
            fx = _get(modifier, "FX")
            if duration is None or duration > _MAX_MS or not isinstance(fx, FXList):
                continue
            span = modifier._field_spans.get("FX", modifier.span)
            for label, lifetime_ms in _effect_lifetimes(fx):
                if lifetime_ms > _MAX_MS or abs(lifetime_ms - duration) <= _TOLERANCE_MS:
                    continue
                relation = "outlasts" if lifetime_ms > duration else "ends before"
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"ModifierList {modifier.name!r} lasts {duration} ms but its FX "
                        f"{fx.name!r} {label} is {round(lifetime_ms)} ms - the effect "
                        f"{relation} the modifier."
                    ),
                    span=span,
                    severity=Severity.WARNING,
                    extra={
                        "modifier": modifier.name,
                        "fx": fx.name,
                        "duration": duration,
                        "fx_duration": round(lifetime_ms),
                    },
                )
