"""Polygon trigger areas: adding, deleting and reshaping them.

Every corpus map keeps its trigger areas in the `TriggerAreas` chunk: a name, a layer (`''` for
the default), an id, and float x / y points in world units. WorldBuilder names a new area
`Area %d` (the format string beside `PolygonTool`'s, `0x01E05594`); ids are never reused, so a new
area takes the highest id + 1.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from sage_map.assets.trigger_areas import TriggerArea
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command
from sage_worldbuilder.commands.edits import InsertItem
from sage_worldbuilder.ids import next_trigger_area_id

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "DeleteAreas",
    "MoveAreaPoint",
    "add_area",
    "area_contains",
    "new_area",
    "new_area_name",
]

AREAS = Change(ChangeKind.AREAS)


def _areas(map: Map) -> list[TriggerArea]:
    return map.trigger_areas.trigger_areas if map.trigger_areas is not None else []


def new_area_name(map: Map) -> str:
    """`Area <N>` with the smallest N no area on the map is named."""
    taken = {area.name.lower() for area in _areas(map)}
    number = 1
    while f"area {number}" in taken:
        number += 1
    return f"Area {number}"


def new_area(map: Map, points: Iterable[tuple[float, float]], layer: str = "") -> TriggerArea:
    return TriggerArea(
        name=new_area_name(map),
        layer_name=layer,
        area_id=next_trigger_area_id(map),
        points=[(float(x), float(y)) for x, y in points],
        unknown2=0,
    )


def add_area(map: Map, area: TriggerArea) -> Command:
    if map.trigger_areas is None:
        raise ValueError("the map has no trigger area list")
    listed = map.trigger_areas.trigger_areas
    return InsertItem(listed, len(listed), area, AREAS, "Add Trigger Area")


class DeleteAreas(Command):
    def __init__(self, areas: Sequence[TriggerArea], label: str = "Delete") -> None:
        self.areas = list(areas)
        self.label = label
        self._removed: list[tuple[int, TriggerArea]] = []

    def do(self, document: MapDocument) -> None:
        listed = _areas(document.map)
        wanted = {id(area) for area in self.areas}
        self._removed = [(index, area) for index, area in enumerate(listed) if id(area) in wanted]
        for index, _area in reversed(self._removed):
            del listed[index]

    def undo(self, document: MapDocument) -> None:
        listed = _areas(document.map)
        for index, area in self._removed:
            listed.insert(index, area)

    def changes(self) -> tuple[Change, ...]:
        return (AREAS,)


class MoveAreaPoint(Command):
    """Move one corner of an area (anything with a `points` list: a trigger area, a lake, a wave
    area). A run of moves of the same corner merges until closed."""

    def __init__(
        self,
        area: Any,
        index: int,
        point: tuple[float, float],
        label: str = "Move Point",
        change: Change = AREAS,
    ) -> None:
        self.area = area
        self.index = index
        self.point = point
        self.label = label
        self.change = change
        self.closed = False
        self._before: tuple[float, float] | None = None

    def do(self, document: MapDocument) -> None:
        if self._before is None:
            self._before = self.area.points[self.index]
        self.area.points[self.index] = self.point

    def undo(self, document: MapDocument) -> None:
        assert self._before is not None
        self.area.points[self.index] = self._before

    def changes(self) -> tuple[Change, ...]:
        return (self.change,)

    def merge(self, following: Command) -> bool:
        if self.closed or not (
            isinstance(following, MoveAreaPoint)
            and following.area is self.area
            and following.index == self.index
        ):
            return False
        self.point = following.point
        return True


def area_contains(points: Sequence[tuple[float, float]], x: float, y: float) -> bool:
    """Whether a point is inside a polygon (even-odd rule)."""
    inside = False
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside
