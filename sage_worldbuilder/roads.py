"""Roads and bridges: pairs of placed objects.

A segment is two consecutive entries of the object list: the first carries a start flag, the
second an end flag, and both name the road type (a `Road` or `Bridge` of the game data) as their
`type_name`. The game reads a road's end as the object after its start and asserts only that it
has the end flag (`pMapObj2 && pMapObj2->getFlag(FLAG_ROAD_POINT2)`, WorldBuilder `0x01DEFBA8`).
Every corpus road pair checked has matching types.

Only `FLAG_ROAD_POINT2` is named in the exe. The other meanings are read off the corpus (see
PHASE5.md): corner and join flags sit on both ends of a segment, a segment with neither corner
flag is a broad curve, and `0x10` / `0x20` start and end a bridge. `0x100` is set on 2,284 corpus
objects that are not roads at all (ambient sound emitters among them), so it is not a road flag.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from sage_map.assets.object_list import Object
from sage_map.context import AssetPropertyType, Property
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand, SetAttribute
from sage_worldbuilder.commands.edits import InsertItem
from sage_worldbuilder.ids import next_unique_number

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = [
    "BRIDGE_END",
    "BRIDGE_START",
    "CORNER_ANGLED",
    "CORNER_TIGHT",
    "DEFAULT_ROAD_WIDTH",
    "ROAD_END",
    "ROAD_JOIN",
    "ROAD_START",
    "CornerType",
    "RoadSegment",
    "RoadStyle",
    "RoadStyles",
    "add_road",
    "apply_road_style",
    "is_road_point",
    "nearest_road_end",
    "new_road",
    "road_segments",
    "segment_at",
    "selected_segments",
    "with_partners",
]

ROAD_START = 0x2
ROAD_END = 0x4
CORNER_ANGLED = 0x8
BRIDGE_START = 0x10
BRIDGE_END = 0x20
CORNER_TIGHT = 0x40
ROAD_JOIN = 0x80
_START_FLAGS = ROAD_START | BRIDGE_START
_END_FLAGS = ROAD_END | BRIDGE_END
_POINT_FLAGS = _START_FLAGS | _END_FLAGS
_SHAPE_FLAGS = CORNER_ANGLED | CORNER_TIGHT | ROAD_JOIN
# World units a road is drawn across when the game data does not give its width (a bridge, or a
# type the game does not define): the most common `RoadWidth` in RotWK's Roads.ini is 28.
DEFAULT_ROAD_WIDTH = 28.0
# The owner every corpus road object stores: the neutral player's team.
_ROAD_OWNER = "/team"
# The object record version every corpus map stores, for a map with no objects to follow.
_OBJECT_VERSION = 3

OBJECTS = Change(ChangeKind.OBJECTS)


class CornerType(StrEnum):
    """Road Options' Corner Type: how a road bends where two segments meet."""

    BROAD = "Broad Curve"
    TIGHT = "Tight Curve"
    ANGLED = "Angled"


def is_road_point(obj: Object) -> bool:
    """Whether an object is one end of a road or bridge segment."""
    return bool(obj.road_type & _POINT_FLAGS)


def corner_type(flags: int) -> CornerType:
    if flags & CORNER_ANGLED:
        return CornerType.ANGLED
    if flags & CORNER_TIGHT:
        return CornerType.TIGHT
    return CornerType.BROAD


def _shape_flags(corner: CornerType, join: bool) -> int:
    flags = {CornerType.BROAD: 0, CornerType.TIGHT: CORNER_TIGHT, CornerType.ANGLED: CORNER_ANGLED}
    return flags[corner] | (ROAD_JOIN if join else 0)


@dataclass(frozen=True, eq=False)
class RoadSegment:
    start: Object
    end: Object

    @property
    def type_name(self) -> str:
        return self.start.type_name

    @property
    def bridge(self) -> bool:
        return bool(self.start.road_type & BRIDGE_START)

    @property
    def corner(self) -> CornerType:
        return corner_type(self.start.road_type)

    @property
    def join(self) -> bool:
        return bool(self.start.road_type & ROAD_JOIN)

    @property
    def points(self) -> tuple[tuple[float, float], tuple[float, float]]:
        return (
            (self.start.position[0], self.start.position[1]),
            (self.end.position[0], self.end.position[1]),
        )


def _pairs(first: Object, second: Object) -> bool:
    return bool(
        (first.road_type & ROAD_START and second.road_type & ROAD_END)
        or (first.road_type & BRIDGE_START and second.road_type & BRIDGE_END)
    )


def road_segments(objects: Sequence[Object]) -> list[RoadSegment]:
    """The segments of an object list: each road start followed by a road end, each bridge start
    by a bridge end. A start with no end after it, or an end with no start before it, belongs to
    no segment: Ford of Bruinen, for one, stores four lone bridge starts."""
    segments: list[RoadSegment] = []
    index = 0
    while index < len(objects) - 1:
        first, second = objects[index], objects[index + 1]
        if _pairs(first, second):
            segments.append(RoadSegment(first, second))
            index += 2
        else:
            index += 1
    return segments


def _listed(map: Map) -> list[Object]:
    return map.objects_list.object_list if map.objects_list is not None else []


def with_partners(map: Map, objects: Iterable[Object]) -> list[Object]:
    """`objects` and the other end of every road segment among them, in map order, so a copy keeps
    each start straight before its end and a delete takes whole segments."""
    wanted = {id(obj) for obj in objects}
    for segment in road_segments(_listed(map)):
        if id(segment.start) in wanted or id(segment.end) in wanted:
            wanted.update((id(segment.start), id(segment.end)))
    return [obj for obj in _listed(map) if id(obj) in wanted]


def selected_segments(map: Map, items: Iterable[object]) -> list[RoadSegment]:
    """The segments with at least one end among `items`, in map order."""
    wanted = {id(item) for item in items}
    return [
        segment
        for segment in road_segments(_listed(map))
        if id(segment.start) in wanted or id(segment.end) in wanted
    ]


def _property(name: str, kind: AssetPropertyType, value: bool | int | str) -> Property:
    return {"name": name, "type": kind, "value": value}


def _road_object(
    version: int, type_name: str, point: tuple[float, float], flags: int, unique_id: str, layer: str
) -> Object:
    boolean, integer, text = (
        AssetPropertyType.Boolean,
        AssetPropertyType.Integer,
        AssetPropertyType.AsciiString,
    )
    # The properties and their order are those of the corpus's road objects.
    values: tuple[tuple[str, AssetPropertyType, bool | int | str], ...] = (
        ("objectInitialHealth", integer, 100),
        ("objectEnabled", boolean, True),
        ("objectIndestructible", boolean, False),
        ("objectUnsellable", boolean, False),
        ("objectPowered", boolean, True),
        ("objectRecruitableAI", boolean, True),
        ("objectTargetable", boolean, False),
        ("originalOwner", text, _ROAD_OWNER),
        ("uniqueID", text, unique_id),
        ("objectLayer", text, layer),
        ("objectBasePriority", integer, 40),
        ("objectBasePhase", integer, 1),
    )
    properties = {name: _property(name, kind, value) for name, kind, value in values}
    return Object(version, (point[0], point[1], 0.0), 0.0, flags, type_name, properties, 0, 0)


def new_road(
    map: Map,
    type_name: str,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    bridge: bool = False,
    corner: CornerType = CornerType.BROAD,
    join: bool = False,
    layer: str = "",
) -> RoadSegment:
    """A new segment's two objects, not yet on the map. As on the corpus maps, the start's
    `uniqueID` number is one above its end's."""
    listed = _listed(map)
    version = listed[0].version if listed else _OBJECT_VERSION
    number = next_unique_number(map)
    shape = _shape_flags(corner, join)
    first, second = (BRIDGE_START, BRIDGE_END) if bridge else (ROAD_START, ROAD_END)
    return RoadSegment(
        _road_object(version, type_name, start, first | shape, f"{type_name} {number + 1}", layer),
        _road_object(version, type_name, end, second | shape, f"{type_name} {number}", layer),
    )


def add_road(map: Map, segment: RoadSegment, label: str = "Add Road") -> Command:
    """The command appending a segment's two objects to the map, start first."""
    if map.objects_list is None:
        raise ValueError("the map has no object list to add a road to")
    listed = map.objects_list.object_list
    return CompositeCommand(
        label,
        [
            InsertItem(listed, len(listed), segment.start, OBJECTS, label),
            InsertItem(listed, len(listed) + 1, segment.end, OBJECTS, label),
        ],
    )


def apply_road_style(
    segments: Sequence[RoadSegment],
    type_name: str | None,
    bridge: bool,
    corner: CornerType,
    join: bool,
    label: str = "Apply To Selection",
) -> CompositeCommand:
    """Road Options' Apply To Selection: give every segment the road type (None keeps each
    segment's own), corner type and join flag. A type change also turns a road into a bridge or
    back, as the chosen type is one or the other. Flags that are not road flags are kept."""
    shape = _shape_flags(corner, join)
    commands: list[Command] = []
    for segment in segments:
        is_bridge = bridge if type_name is not None else segment.bridge
        name = type_name if type_name is not None else segment.type_name
        ends = (
            (segment.start, BRIDGE_START if is_bridge else ROAD_START),
            (segment.end, BRIDGE_END if is_bridge else ROAD_END),
        )
        for obj, point in ends:
            flags = obj.road_type & ~(_POINT_FLAGS | _SHAPE_FLAGS) | point | shape
            if flags != obj.road_type:
                commands.append(SetAttribute(obj, "road_type", flags, OBJECTS, label))
            if name != obj.type_name:
                commands.append(SetAttribute(obj, "type_name", name, OBJECTS, label))
    return CompositeCommand(label, commands)


def _distance_to_segment(
    x: float, y: float, a: tuple[float, float], b: tuple[float, float]
) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / length))
    return math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy))


def segment_at(
    segments: Sequence[RoadSegment],
    x: float,
    y: float,
    radius: float,
    width: dict[str, float] | None = None,
) -> RoadSegment | None:
    """The segment nearest a world point, within `radius` of its centre line or inside its road
    width when `width` gives one by type; where several qualify, the one stored last."""
    best: RoadSegment | None = None
    best_distance = math.inf
    for segment in segments:
        reach = max(radius, (width or {}).get(segment.type_name, 0.0) / 2)
        distance = _distance_to_segment(x, y, *segment.points)
        if distance <= reach and distance <= best_distance:
            best, best_distance = segment, distance
    return best


def nearest_road_end(
    segments: Sequence[RoadSegment], x: float, y: float, radius: float
) -> tuple[float, float] | None:
    """The road end closest to a world point within `radius`, for a new segment to join onto."""
    best: tuple[float, float] | None = None
    best_distance = radius
    for segment in segments:
        for point in segment.points:
            distance = math.hypot(point[0] - x, point[1] - y)
            if distance <= best_distance:
                best, best_distance = point, distance
    return best


@dataclass(frozen=True)
class RoadStyle:
    """A road type's `RoadWidth` (world units), `RoadWidthInTexture` and `Texture`: the game draws
    the road `width * width_in_texture` across, curves it by multiples of `width`, and lays that
    texture along it. A bridge has no road texture: the game draws it as a model."""

    width: float
    bridge: bool
    width_in_texture: float = 1.0
    texture: str | None = None


class RoadStyles:
    """How each road type is drawn, from the game data's `Road` blocks (`RoadWidth`, world units,
    `RoadWidthInTexture` and `Texture`) and `Bridge` blocks, read on first use and kept."""

    def __init__(self, game: Game) -> None:
        self.game = game
        self._cache: dict[str, RoadStyle] = {}

    def get(self, type_name: str) -> RoadStyle:
        if type_name not in self._cache:
            self._cache[type_name] = self._read(type_name)
        return self._cache[type_name]

    def names(self) -> tuple[list[str], list[str]]:
        """The game's road type names and bridge names, each sorted."""
        return (
            sorted(_table(self.game, "roads"), key=str.lower),
            sorted(_table(self.game, "bridges"), key=str.lower),
        )

    def _read(self, type_name: str) -> RoadStyle:
        if _find(_table(self.game, "bridges"), type_name) is not None:
            return RoadStyle(DEFAULT_ROAD_WIDTH, bridge=True)
        road = _find(_table(self.game, "roads"), type_name)
        width = _number(getattr(road, "RoadWidth", None)) if road is not None else 0.0
        in_texture = _number(getattr(road, "RoadWidthInTexture", None)) if road is not None else 0.0
        texture = getattr(road, "Texture", None) if road is not None else None
        return RoadStyle(
            width if width > 0 else DEFAULT_ROAD_WIDTH,
            bridge=False,
            width_in_texture=in_texture if in_texture > 0 else 1.0,
            texture=str(texture) if texture else None,
        )


def _table(game: Game, name: str) -> dict[str, object]:
    return getattr(game, name, None) or {}


def _find(table: dict[str, object], name: str) -> object | None:
    found = table.get(name)
    if found is not None:
        return found
    lowered = name.lower()
    return next((value for key, value in table.items() if key.lower() == lowered), None)


def _number(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
