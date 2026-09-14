"""What a map view draws and picks: a marker per placed object, the trigger area outlines and the
waypoint links, with a spatial index so the view finds what is under the cursor quickly.

Built from the map and thrown away when objects, waypoints or areas change; building it for a
map with thousands of objects takes milliseconds.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from sage_map.assets.object_list import Object
from sage_map.map import Map
from sage_worldbuilder.anchors import RotationAnchors, shown_position
from sage_worldbuilder.areas import area_contains
from sage_worldbuilder.roads import RoadSegment, is_road_point, road_segments
from sage_worldbuilder.water import all_water, water_outline

__all__ = ["AreaOutline", "MapScene", "Marker", "MarkerKind"]

WAYPOINT_PREFIX = "*Waypoints/"
GENERIC_AI_PREFIX = "*GenericAIObjects/"
# World units per index bucket: a few heightmap cells, so a bucket holds a handful of markers.
_BUCKET = 50.0


class MarkerKind(StrEnum):
    OBJECT = "object"
    WAYPOINT = "waypoint"
    ROAD = "road"
    GENERIC_AI = "generic AI"


def marker_kind(obj: Object) -> MarkerKind:
    if obj.type_name.startswith(WAYPOINT_PREFIX):
        return MarkerKind.WAYPOINT
    if obj.type_name.startswith(GENERIC_AI_PREFIX):
        return MarkerKind.GENERIC_AI
    # Only the road point flags: other `road_type` bits (0x100) sit on objects that are not roads.
    if is_road_point(obj):
        return MarkerKind.ROAD
    return MarkerKind.OBJECT


def _text(obj: Object, key: str) -> str:
    stored = obj.properties.get(key)
    return str(stored["value"]) if stored is not None and stored["value"] else ""


@dataclass(frozen=True, eq=False)
class Marker:
    kind: MarkerKind
    x: float
    y: float
    angle: float
    label: str
    source: Object


@dataclass(frozen=True, eq=False)
class AreaOutline:
    name: str
    points: tuple[tuple[float, float], ...]
    source: object


@dataclass
class MapScene:
    markers: list[Marker] = field(default_factory=list)
    areas: list[AreaOutline] = field(default_factory=list)
    links: list[tuple[Marker, Marker]] = field(default_factory=list)
    roads: list[RoadSegment] = field(default_factory=list)
    # Lakes, rivers and wave areas, each as the outline it covers (a wave area's points may be
    # fewer than three: a line, or a single point).
    water: list[AreaOutline] = field(default_factory=list)
    _buckets: dict[tuple[int, int], list[Marker]] = field(default_factory=dict, repr=False)

    @classmethod
    def from_map(cls, map: Map, anchors: RotationAnchors | None = None) -> MapScene:
        """The map's scene; each marker stands where its object does (`shown_position`), out
        from its stored pivot along its template's rotation anchor when `anchors` are given."""
        scene = cls()
        waypoints: dict[int, Marker] = {}
        buckets: defaultdict[tuple[int, int], list[Marker]] = defaultdict(list)
        objects = map.objects_list.object_list if map.objects_list is not None else []
        for obj in objects:
            kind = marker_kind(obj)
            label = _text(obj, "waypointName") if kind is MarkerKind.WAYPOINT else ""
            label = label or _text(obj, "objectName")
            x, y, _ = shown_position(obj, anchors)
            marker = Marker(kind, x, y, obj.angle, label, obj)
            scene.markers.append(marker)
            buckets[_bucket(x, y)].append(marker)
            waypoint_id = obj.properties.get("waypointID")
            if kind is MarkerKind.WAYPOINT and waypoint_id is not None:
                waypoints[int(waypoint_id["value"])] = marker
        scene._buckets = dict(buckets)
        scene.roads = road_segments(objects)
        scene.water = [
            AreaOutline(area.name, tuple(water_outline(area)), area) for area in all_water(map)
        ]
        if map.waypoints_list is not None:
            for start, end in map.waypoints_list.waypoint_paths:
                if start in waypoints and end in waypoints:
                    scene.links.append((waypoints[start], waypoints[end]))
        if map.trigger_areas is not None:
            scene.areas += [
                AreaOutline(area.name, tuple((float(x), float(y)) for x, y in area.points), area)
                for area in map.trigger_areas.trigger_areas
            ]
        return scene

    def in_rect(self, x0: float, y0: float, x1: float, y1: float) -> Iterator[Marker]:
        """The markers inside a world rectangle (corners in any order), in map order within each
        bucket."""
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        bx0, by0 = _bucket(x0, y0)
        bx1, by1 = _bucket(x1, y1)
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                for marker in self._buckets.get((bx, by), ()):
                    if x0 <= marker.x <= x1 and y0 <= marker.y <= y1:
                        yield marker

    def nearest(
        self,
        x: float,
        y: float,
        radius: float,
        kinds: frozenset[MarkerKind] | None = None,
        accept: Callable[[Marker], bool] | None = None,
    ) -> Marker | None:
        """The closest marker within `radius` world units, of one of `kinds` and passing
        `accept` when given. A tie goes to the one the map stores last, which is also the one
        drawn on top."""
        best: Marker | None = None
        best_distance = radius
        for marker in self.in_rect(x - radius, y - radius, x + radius, y + radius):
            if kinds is not None and marker.kind not in kinds:
                continue
            if accept is not None and not accept(marker):
                continue
            distance = math.hypot(marker.x - x, marker.y - y)
            if distance <= best_distance:
                best, best_distance = marker, distance
        return best

    def marker_for(self, source: object) -> Marker | None:
        return next((marker for marker in self.markers if marker.source is source), None)

    def area_at(
        self, x: float, y: float, accept: Callable[[AreaOutline], bool] | None = None
    ) -> AreaOutline | None:
        """The area containing a world point, passing `accept` when given; where areas overlap,
        the one the map stores last, which is drawn on top."""
        for area in reversed(self.areas):
            if accept is not None and not accept(area):
                continue
            if len(area.points) >= 3 and area_contains(area.points, x, y):
                return area
        return None

    def water_at(
        self,
        x: float,
        y: float,
        radius: float,
        accept: Callable[[AreaOutline], bool] | None = None,
    ) -> AreaOutline | None:
        """The water area under a world point: inside its outline, or within `radius` of a wave
        area's line or point; where areas overlap, the one drawn last."""
        for outline in reversed(self.water):
            if accept is not None and not accept(outline):
                continue
            points = outline.points
            if len(points) >= 3 and area_contains(points, x, y):
                return outline
            if 0 < len(points) < 3 and _near_path(points, x, y, radius):
                return outline
        return None


def _near_path(points: tuple[tuple[float, float], ...], x: float, y: float, radius: float) -> bool:
    if len(points) == 1:
        return math.hypot(points[0][0] - x, points[0][1] - y) <= radius
    (ax, ay), (bx, by) = points[0], points[1]
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= radius


def _bucket(x: float, y: float) -> tuple[int, int]:
    return math.floor(x / _BUCKET), math.floor(y / _BUCKET)
