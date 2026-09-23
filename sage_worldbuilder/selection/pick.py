"""WorldBuilder's Pick Allowances: which kinds of object a click in the view may select.

`PointerTool::allowPick` (`0x00593AEA`) tests an object's template `EditorSorting`; waypoints,
areas, roads and sounds have categories of their own. An object whose template the game data does
not know is pickable whenever anything is.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sage_worldbuilder.scene import Marker, MarkerKind

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = ["ANYTHING", "NOTHING", "PickCategory", "PickRules"]


class PickCategory(StrEnum):
    BUILDINGS = "Buildings"
    UNITS = "Units"
    SHRUBBERY = "Shrubbery"
    PROPS = "Props"
    NATURAL = "Natural"
    DEBRIS = "Debris"
    WAYPOINTS_AREAS = "Waypoints & Areas"
    ROADS = "Roads"
    SOUNDS = "Sounds"


ANYTHING = frozenset(PickCategory)
NOTHING: frozenset[PickCategory] = frozenset()

_BY_SORTING = {
    "STRUCTURE": PickCategory.BUILDINGS,
    "UNIT": PickCategory.UNITS,
    "SHRUBBERY": PickCategory.SHRUBBERY,
    "MISC_MAN_MADE": PickCategory.PROPS,
    "MISC_NATURAL": PickCategory.NATURAL,
    "DEBRIS": PickCategory.DEBRIS,
    "AUDIO": PickCategory.SOUNDS,
}


class PickRules:
    def __init__(self, game: Game | None, allowed: frozenset[PickCategory] = ANYTHING) -> None:
        self.game = game
        self.allowed = allowed
        self._categories: dict[str, PickCategory | None] = {}
        self._names: dict[str, str] | None = None

    def category(self, marker: Marker) -> PickCategory | None:
        if marker.kind is MarkerKind.WAYPOINT:
            return PickCategory.WAYPOINTS_AREAS
        if marker.kind is MarkerKind.ROAD:
            return PickCategory.ROADS
        type_name = marker.source.type_name
        if type_name not in self._categories:
            self._categories[type_name] = self._template_category(type_name)
        return self._categories[type_name]

    def allows(self, marker: Marker) -> bool:
        category = self.category(marker)
        return bool(self.allowed) if category is None else category in self.allowed

    def allows_areas(self) -> bool:
        return PickCategory.WAYPOINTS_AREAS in self.allowed

    def _template_category(self, type_name: str) -> PickCategory | None:
        if self.game is None:
            return None
        objects = self.game.objects
        template = objects.get(type_name)
        if template is None:
            if self._names is None:
                self._names = {name.lower(): name for name in objects}
            name = self._names.get(type_name.lower())
            template = objects.get(name) if name is not None else None
        sortings = getattr(template, "EditorSorting", None) or []
        for sorting in sortings:
            category = _BY_SORTING.get(getattr(sorting, "name", str(sorting)).upper())
            if category is not None:
                return category
        return None
