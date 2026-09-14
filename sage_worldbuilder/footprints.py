"""The ground an object covers, from its template's geometry, for drawing footprints from above.

An object's first geometry shape decides: a BOX covers `GeometryMajorRadius` either side along
the object's facing and `GeometryMinorRadius` either side across it; a CYLINDER or SPHERE covers
a circle of `GeometryMajorRadius`. World units, like positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = ["Footprint", "FootprintShape", "Footprints"]


class FootprintShape(StrEnum):
    BOX = "box"
    CIRCLE = "circle"


@dataclass(frozen=True)
class Footprint:
    shape: FootprintShape
    major: float
    minor: float


class Footprints:
    """Footprints by object name, read from the game data on first use and kept."""

    def __init__(self, game: Game) -> None:
        self.game = game
        self._cache: dict[str, Footprint | None] = {}
        self._names: dict[str, str] | None = None

    def get(self, type_name: str) -> Footprint | None:
        if type_name not in self._cache:
            self._cache[type_name] = self._read(type_name)
        return self._cache[type_name]

    def _read(self, type_name: str) -> Footprint | None:
        objects = self.game.objects
        template = objects.get(type_name)
        if template is None:
            if self._names is None:
                self._names = {name.lower(): name for name in objects}
            name = self._names.get(type_name.lower())
            template = objects.get(name) if name is not None else None
        shapes = getattr(template, "geometry", None) or []
        if not shapes:
            return None
        shape = shapes[0]
        major = _number(getattr(shape, "GeometryMajorRadius", None))
        if major <= 0:
            return None
        kind = getattr(shape, "type", None)
        if getattr(kind, "name", str(kind)).upper() == "BOX":
            minor = _number(getattr(shape, "GeometryMinorRadius", None))
            return Footprint(FootprintShape.BOX, major, minor if minor > 0 else major)
        return Footprint(FootprintShape.CIRCLE, major, major)


def _number(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
