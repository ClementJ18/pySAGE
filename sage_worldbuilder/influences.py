"""What a placed object reaches, for the View menu's influence views (Show Sight Ranges, Show
Weapon Ranges, Show Sound Circles).

Sight is the template's `VisionRange`. The weapon range is the longest `AttackRange` among the
weapons of the template's default weapon set: the first whose conditions are all empty, else its
first set. Sound ranges are the object's own `objectSoundAmbientMinRange` and
`objectSoundAmbientMaxRange` when it customizes its ambient sound (`objectSoundAmbientCustomized`);
the ranges of a sound it takes from its template are not read. World units throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_map.assets.object_list import Object

__all__ = ["Influences", "sound_ranges"]

_CUSTOMIZED = "objectSoundAmbientCustomized"
_MIN_RANGE = "objectSoundAmbientMinRange"
_MAX_RANGE = "objectSoundAmbientMaxRange"


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class Influences:
    """Sight and weapon ranges by object name, read from the game data on first use and kept."""

    def __init__(self, game: Game) -> None:
        self.game = game
        self._names: dict[str, str] | None = None
        self._sight: dict[str, float | None] = {}
        self._weapons: dict[str, float | None] = {}

    def _template(self, type_name: str) -> object:
        objects = self.game.objects
        template = objects.get(type_name)
        if template is None:
            if self._names is None:
                self._names = {name.lower(): name for name in objects}
            name = self._names.get(type_name.lower())
            template = objects.get(name) if name is not None else None
        return template

    def sight_range(self, type_name: str) -> float | None:
        if type_name not in self._sight:
            template = self._template(type_name)
            self._sight[type_name] = _number(getattr(template, "VisionRange", None))
        return self._sight[type_name]

    def weapon_range(self, type_name: str) -> float | None:
        if type_name not in self._weapons:
            self._weapons[type_name] = self._read_weapon_range(self._template(type_name))
        return self._weapons[type_name]

    @staticmethod
    def _read_weapon_range(template: object) -> float | None:
        sets = list(getattr(template, "WeaponSet", None) or [])
        if not sets:
            return None
        default = next(
            (entry for entry in sets if not any(getattr(entry, "Conditions", None) or [])),
            sets[0],
        )
        ranges = [
            _number(getattr(weapon, "AttackRange", None))
            for _slot, weapon in getattr(default, "Weapon", None) or []
            if weapon is not None
        ]
        known = [value for value in ranges if value is not None]
        return max(known) if known else None


def sound_ranges(obj: Object) -> tuple[float, float] | None:
    """An object's customized ambient sound's minimum and maximum range, or None."""
    properties = obj.properties
    customized = properties.get(_CUSTOMIZED)
    if customized is None or not customized["value"]:
        return None
    low, high = properties.get(_MIN_RANGE), properties.get(_MAX_RANGE)
    minimum = _number(low["value"]) if low is not None else None
    maximum = _number(high["value"]) if high is not None else None
    if maximum is None:
        return None
    return (minimum or 0.0), maximum
