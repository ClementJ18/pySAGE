"""Markers: shapes the user draws on the map to point an agent at.

There are three kinds. An area is a polygon (a dragged rectangle is a four-corner one), named A, B,
C, ... A point is a single place, named P1, P2, ... A path runs through points in order, named L1,
L2, ...; it holds the points' names, so moving a point reshapes every path through it. All of them
share one namespace and are looked up ignoring case.

A marker is not map data. Like the selection it is not undoable, does not mark the map as changed
and is never saved; it only lets "flatten A" or "paint a road along L1" name a place exactly. The
MCP tools read and edit them, and the Markers panel does the same in the editor.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from string import ascii_uppercase

import numpy as np

__all__ = [
    "AreaMarker",
    "Marker",
    "MarkerError",
    "MarkerKind",
    "Markers",
    "PathMarker",
    "PointMarker",
    "distance_to_polyline",
    "path_length",
    "polygon_contains",
]

Point = tuple[float, float]


class MarkerKind(Enum):
    AREA = "area"
    POINT = "point"
    PATH = "path"


class MarkerError(ValueError):
    """An edit the markers cannot take; the message is meant for whoever asked for it."""


def _round(point: Sequence[float]) -> Point:
    return round(float(point[0]), 1), round(float(point[1]), 1)


@dataclass(frozen=True)
class AreaMarker:
    """A polygon of world positions, at least three corners."""

    name: str
    points: tuple[Point, ...]

    kind = MarkerKind.AREA

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs, ys = [p[0] for p in self.points], [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def is_rectangle(self) -> bool:
        if len(self.points) != 4:
            return False
        x0, y0, x1, y1 = self.bounds
        return set(self.points) == {(x0, y0), (x1, y0), (x1, y1), (x0, y1)}

    def contains(self, x: float, y: float) -> bool:
        return bool(polygon_contains(self.points, np.array([x]), np.array([y]))[0])


@dataclass(frozen=True)
class PointMarker:
    name: str
    x: float
    y: float

    kind = MarkerKind.POINT

    @property
    def position(self) -> Point:
        return self.x, self.y


@dataclass(frozen=True)
class PathMarker:
    """A line through points, by the points' names, in order."""

    name: str
    stops: tuple[str, ...]

    kind = MarkerKind.PATH


Marker = AreaMarker | PointMarker | PathMarker

_PREFIXES = {MarkerKind.POINT: "P", MarkerKind.PATH: "L"}


def _letters(number: int) -> str:
    """A, B, ..., Z, AA, AB, ...: the spreadsheet column names."""
    label = ""
    number += 1
    while number:
        number, rest = divmod(number - 1, 26)
        label = ascii_uppercase[rest] + label
    return label


def _label(kind: MarkerKind, number: int) -> str:
    if kind is MarkerKind.AREA:
        return _letters(number)
    return f"{_PREFIXES[kind]}{number + 1}"


def polygon_contains(points: Sequence[Point], xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Which of the positions (`xs`, `ys`, same shape) lie inside a polygon, by the even-odd rule;
    a position on the outline counts as inside."""
    inside = np.zeros(np.shape(xs), dtype=bool)
    count = len(points)
    for index in range(count):
        ax, ay = points[index]
        bx, by = points[index - 1]
        crosses = (ay > ys) != (by > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            at = (bx - ax) * (ys - ay) / (by - ay) + ax
        inside ^= crosses & (xs < at)
    return inside | (distance_to_polyline([*points, points[0]], xs, ys) <= 1e-6)


def distance_to_polyline(points: Sequence[Point], xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """How far each position (`xs`, `ys`) is from the nearest part of a line through `points`."""
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    if not points:
        return np.full(xs.shape, np.inf)
    if len(points) == 1:
        return np.hypot(xs - points[0][0], ys - points[0][1])
    best = np.full(xs.shape, np.inf)
    for (ax, ay), (bx, by) in zip(points, points[1:], strict=False):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        if length == 0:
            t = np.zeros_like(xs)
        else:
            t = np.clip(((xs - ax) * dx + (ys - ay) * dy) / length, 0.0, 1.0)
        best = np.minimum(best, np.hypot(xs - (ax + t * dx), ys - (ay + t * dy)))
    return best


class Markers:
    def __init__(self) -> None:
        self._markers: dict[str, Marker] = {}
        self._listeners: list[Callable[[], None]] = []
        # The marker the Markers panel and tool are working on; not an agent's concern.
        self._selected: str | None = None

    def __iter__(self) -> Iterator[Marker]:
        return iter(tuple(self._markers.values()))

    def __len__(self) -> int:
        return len(self._markers)

    def __bool__(self) -> bool:
        return bool(self._markers)

    def get(self, name: str) -> Marker | None:
        return self._markers.get(name.strip().upper())

    def of_kind(self, kind: MarkerKind) -> list[Marker]:
        return [marker for marker in self._markers.values() if marker.kind is kind]

    def areas(self) -> list[AreaMarker]:
        return [m for m in self._markers.values() if isinstance(m, AreaMarker)]

    def points(self) -> list[PointMarker]:
        return [m for m in self._markers.values() if isinstance(m, PointMarker)]

    def paths(self) -> list[PathMarker]:
        return [m for m in self._markers.values() if isinstance(m, PathMarker)]

    def path_points(self, path: PathMarker) -> list[Point]:
        """Where a path's stops are, in order."""
        points = (self._markers.get(stop) for stop in path.stops)
        return [p.position for p in points if isinstance(p, PointMarker)]

    def paths_through(self, point: str) -> list[PathMarker]:
        key = point.strip().upper()
        return [path for path in self.paths() if key in path.stops]

    def at(self, x: float, y: float) -> AreaMarker | None:
        """The last-marked area containing a world position."""
        for area in reversed(self.areas()):
            if area.contains(x, y):
                return area
        return None

    @property
    def selected(self) -> Marker | None:
        return self._markers.get(self._selected) if self._selected is not None else None

    def select(self, name: str | None) -> None:
        key = name.strip().upper() if name else None
        if key is not None and key not in self._markers:
            key = None
        if key != self._selected:
            self._selected = key
            self._changed()

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def free_name(self, kind: MarkerKind) -> str:
        number = 0
        while _label(kind, number) in self._markers:
            number += 1
        return _label(kind, number)

    def _name_for(self, kind: MarkerKind, name: str | None) -> str:
        """`name` normalised, or the first free name of the kind. A name held by a marker of
        another kind is refused: replacing it would leave paths pointing at an area."""
        if name is None or not name.strip():
            return self.free_name(kind)
        key = name.strip().upper()
        held = self._markers.get(key)
        if held is not None and held.kind is not kind:
            raise MarkerError(f"{key} is already {_a(held.kind)}")
        return key

    def mark_area(self, points: Iterable[Sequence[float]], name: str | None = None) -> AreaMarker:
        """Mark a polygon, under `name` (replacing an area of that name) or the next free
        letter."""
        corners = _dedupe([_round(point) for point in points], closed=True)
        if len(corners) < 3 or _area(corners) == 0:
            raise MarkerError("an area needs at least three corners enclosing some ground")
        area = AreaMarker(self._name_for(MarkerKind.AREA, name), tuple(corners))
        self._markers[area.name] = area
        self._changed()
        return area

    def mark_rectangle(
        self, x0: float, y0: float, x1: float, y1: float, name: str | None = None
    ) -> AreaMarker:
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        return self.mark_area([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], name)

    def mark_point(self, x: float, y: float, name: str | None = None) -> PointMarker:
        """Mark a point, under `name` (moving a point of that name, and so its paths) or the next
        free P name."""
        rx, ry = _round((x, y))
        point = PointMarker(self._name_for(MarkerKind.POINT, name), rx, ry)
        self._markers[point.name] = point
        self._changed()
        return point

    def mark_path(self, stops: Iterable[str], name: str | None = None) -> PathMarker:
        """Mark a path through points (by name), under `name` (replacing a path of that name) or
        the next free L name."""
        path = PathMarker(self._name_for(MarkerKind.PATH, name), self._stops(stops))
        self._markers[path.name] = path
        self._changed()
        return path

    def _stops(self, stops: Iterable[str]) -> tuple[str, ...]:
        names = [stop.strip().upper() for stop in stops]
        for stop in names:
            if not isinstance(self._markers.get(stop), PointMarker):
                raise MarkerError(f"{stop} is not a marked point")
        names = _dedupe(names, closed=False)
        if len(names) < 2:
            raise MarkerError("a path needs at least two different points")
        return tuple(names)

    def rename(self, old: str, new: str) -> Marker:
        """Rename a marker; the paths through a renamed point follow it."""
        marker = self._require(old)
        key = new.strip().upper()
        if not key:
            raise MarkerError("a marker needs a name")
        if key == marker.name:
            return marker
        if key in self._markers:
            raise MarkerError(f"{key} is already taken")
        renamed = replace(marker, name=key)
        self._markers = {
            (key if name == marker.name else name): (renamed if each is marker else each)
            for name, each in self._markers.items()
        }
        if isinstance(marker, PointMarker):
            for path in self.paths():
                if marker.name in path.stops:
                    self._markers[path.name] = replace(
                        path, stops=tuple(key if s == marker.name else s for s in path.stops)
                    )
        if self._selected == marker.name:
            self._selected = key
        self._changed()
        return renamed

    def move(self, name: str, dx: float, dy: float) -> Marker:
        """Shift a marker by world units; a path takes its points with it."""
        marker = self._require(name)
        if isinstance(marker, AreaMarker):
            self._markers[marker.name] = replace(
                marker, points=tuple(_round((x + dx, y + dy)) for x, y in marker.points)
            )
        elif isinstance(marker, PointMarker):
            self._markers[marker.name] = replace(marker, **_xy(marker.x + dx, marker.y + dy))
        else:
            for stop in dict.fromkeys(marker.stops):
                point = self._markers.get(stop)
                if isinstance(point, PointMarker):
                    self._markers[stop] = replace(point, **_xy(point.x + dx, point.y + dy))
        self._changed()
        return self._markers[marker.name]

    def set_corners(self, name: str, points: Iterable[Sequence[float]]) -> AreaMarker:
        self._require(name, MarkerKind.AREA)
        return self.mark_area(points, name)

    def set_position(self, name: str, x: float, y: float) -> PointMarker:
        self._require(name, MarkerKind.POINT)
        return self.mark_point(x, y, name)

    def set_stops(self, name: str, stops: Iterable[str]) -> PathMarker:
        self._require(name, MarkerKind.PATH)
        return self.mark_path(stops, name)

    def remove(self, name: str) -> bool:
        """Remove a marker. A removed point leaves the paths through it; a path left with fewer
        than two points goes too."""
        marker = self._markers.pop(name.strip().upper(), None)
        if marker is None:
            return False
        if isinstance(marker, PointMarker):
            for path in self.paths():
                if marker.name not in path.stops:
                    continue
                stops = _dedupe([s for s in path.stops if s != marker.name], closed=False)
                if len(stops) < 2:
                    del self._markers[path.name]
                else:
                    self._markers[path.name] = replace(path, stops=tuple(stops))
        if self._selected not in self._markers:
            self._selected = None
        self._changed()
        return True

    def clear(self, kind: MarkerKind | None = None) -> int:
        """Remove every marker, or every one of a kind (clearing points clears paths too); how
        many went."""
        before = len(self._markers)
        if kind is None:
            self._markers.clear()
        else:
            gone = {kind, MarkerKind.PATH} if kind is MarkerKind.POINT else {kind}
            self._markers = {n: m for n, m in self._markers.items() if m.kind not in gone}
        if self._selected not in self._markers:
            self._selected = None
        removed = before - len(self._markers)
        if removed:
            self._changed()
        return removed

    def _require(self, name: str, kind: MarkerKind | None = None) -> Marker:
        marker = self.get(name)
        if marker is None:
            marked = ", ".join(self._markers) or "none"
            raise MarkerError(f"no marker {name.strip().upper()!r} (marked: {marked})")
        if kind is not None and marker.kind is not kind:
            raise MarkerError(f"{marker.name} is {_a(marker.kind)}, not {_a(kind)}")
        return marker

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()


def _a(kind: MarkerKind) -> str:
    return f"an {kind.value}" if kind is MarkerKind.AREA else f"a {kind.value}"


def _xy(x: float, y: float) -> dict[str, float]:
    rx, ry = _round((x, y))
    return {"x": rx, "y": ry}


def _dedupe[T](items: list[T], closed: bool) -> list[T]:
    """`items` without immediate repeats (and, `closed`, without a last item repeating the
    first)."""
    kept = [item for index, item in enumerate(items) if index == 0 or item != items[index - 1]]
    if closed and len(kept) > 1 and kept[0] == kept[-1]:
        kept.pop()
    return kept


def _area(points: Sequence[Point]) -> float:
    return (
        abs(
            sum(
                ax * by - bx * ay
                for (ax, ay), (bx, by) in zip(points, [*points[1:], points[0]], strict=True)
            )
        )
        / 2
    )


def path_length(points: Sequence[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
