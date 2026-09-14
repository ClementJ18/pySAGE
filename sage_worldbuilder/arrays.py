"""Radial arrays: repeating an object, or a group of them, evenly around a centre.

WorldBuilder has no tool like this, so none of it is a parity target; every rule below is a
choice, written down where it is made.

A ring is one *stamp* - the Object Palette's object, or the objects already selected - repeated
`count` times about a centre, each copy a whole turn's fraction further round. Positions swing
rigidly about the centre, so a group keeps its shape and every copy stands at the same distance
and the same spacing from its neighbours.

Angles are aimed through the stamp's *lead* (the first object selected, or the one being placed):
the facing rule says which way the lead should point, and every other member of the copy turns by
the same amount, so a group's internal arrangement survives the aiming.

A copy is a deep copy of its source with a fresh `uniqueID` and no `objectName`, since scripts
find objects by name and two objects must not answer to one. Waypoints and trigger areas are not
repeated: their ids, names and links would each need renumbering rules of their own.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sage_map.assets.object_list import Object
from sage_map.map import Map
from sage_worldbuilder.objects import renumber_unique_ids
from sage_worldbuilder.scene import WAYPOINT_PREFIX

__all__ = [
    "DEFAULT_COUNT",
    "MAX_COUNT",
    "MIN_COUNT",
    "MIN_RADIUS",
    "ArrayOptions",
    "Facing",
    "aim_delta",
    "array_copies",
    "array_placements",
    "stamp_objects",
]

DEFAULT_COUNT = 6
MIN_COUNT = 2
MAX_COUNT = 64
# A ring smaller than this leaves the copies on top of each other, so the tool asks for a longer
# drag instead of making one.
MIN_RADIUS = 1.0


class Facing(StrEnum):
    """Which way a copy is turned. Each rule aims the stamp's lead object; the rest of a group
    turns with it."""

    TOWARDS = "Towards the centre"
    AWAY = "Away from the centre"
    ALONG = "Along the ring"
    KEEP = "Keep the angles"


@dataclass
class ArrayOptions:
    """The Array Options panel."""

    count: int = DEFAULT_COUNT
    facing: Facing = Facing.TOWARDS
    # Added to every copy's angle, for a model whose front is not its +X side.
    offset_degrees: float = 0.0
    # Repeat the selection when there is one, rather than the Object Palette's object.
    use_selection: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "facing": self.facing.value,
            "offset_degrees": self.offset_degrees,
            "use_selection": self.use_selection,
        }

    @classmethod
    def from_dict(cls, data: Any) -> ArrayOptions:
        options = cls()
        if not isinstance(data, dict):
            return options
        count = data.get("count")
        if (
            isinstance(count, int)
            and not isinstance(count, bool)
            and MIN_COUNT <= count <= MAX_COUNT
        ):
            options.count = count
        if data.get("facing") in {member.value for member in Facing}:
            options.facing = Facing(data["facing"])
        offset = data.get("offset_degrees")
        if isinstance(offset, (int, float)) and not isinstance(offset, bool):
            options.offset_degrees = float(offset) % 360.0
        if isinstance(data.get("use_selection"), bool):
            options.use_selection = data["use_selection"]
        return options


def stamp_objects(items: Iterable[object]) -> list[Object]:
    """The items a stamp can repeat: placed objects, in the order given, without the waypoints and
    trigger areas a selection may also hold."""
    return [
        item
        for item in items
        if isinstance(item, Object) and not item.type_name.startswith(WAYPOINT_PREFIX)
    ]


def _centroid(stamp: Sequence[tuple[float, float, float]]) -> tuple[float, float]:
    return (
        sum(x for x, _y, _angle in stamp) / len(stamp),
        sum(y for _x, y, _angle in stamp) / len(stamp),
    )


def _turned(
    point: tuple[float, float], center: tuple[float, float], delta: float
) -> tuple[float, float]:
    cos, sin = math.cos(delta), math.sin(delta)
    dx, dy = point[0] - center[0], point[1] - center[1]
    return (center[0] + dx * cos - dy * sin, center[1] + dx * sin + dy * cos)


def aim_delta(
    stamp: Sequence[tuple[float, float, float]],
    center: tuple[float, float],
    options: ArrayOptions,
    pivot: tuple[float, float] | None = None,
) -> float:
    """How far, in radians, the whole stamp turns to satisfy the facing rule: the angle that takes
    the lead from where it points to where the rule wants it, plus the options' offset.

    `pivot` is where the stamp's centre goes, when it is not staying where it stands."""
    offset = math.radians(options.offset_degrees)
    if not stamp or options.facing is Facing.KEEP:
        return offset
    at = pivot if pivot is not None else _centroid(stamp)
    bearing = math.atan2(at[1] - center[1], at[0] - center[0])
    aim = {
        Facing.TOWARDS: bearing + math.pi,
        Facing.AWAY: bearing,
        Facing.ALONG: bearing + math.pi / 2,
    }[options.facing]
    return aim - stamp[0][2] + offset


def array_placements(
    stamp: Sequence[tuple[float, float, float]],
    center: tuple[float, float],
    options: ArrayOptions,
    *,
    pivot: tuple[float, float] | None = None,
    keep_first: bool = False,
) -> list[list[tuple[float, float, float]]]:
    """Where the ring's copies of `stamp` land: one list of `(x, y, angle)` per copy, in ring
    order from the stamp's own place.

    `pivot` moves the stamp's centre there first, so the ring runs through that spot instead.
    `keep_first` leaves the first copy out, for a ring built through objects already on the map."""
    if not stamp or options.count < 1:
        return []
    start = _centroid(stamp)
    at = pivot if pivot is not None else start
    dx, dy = at[0] - start[0], at[1] - start[1]
    delta = aim_delta(stamp, center, options, pivot)
    copies: list[list[tuple[float, float, float]]] = []
    for step in range(1 if keep_first else 0, options.count):
        turn = step * math.tau / options.count
        placed: list[tuple[float, float, float]] = []
        for x, y, angle in stamp:
            moved = _turned((x + dx, y + dy), center, turn)
            placed.append((moved[0], moved[1], math.remainder(angle + turn + delta, math.tau)))
        copies.append(placed)
    return copies


def array_copies(
    map: Map,
    sources: Sequence[Object],
    center: tuple[float, float],
    options: ArrayOptions,
    *,
    pivot: tuple[float, float] | None = None,
    keep_first: bool = False,
) -> list[Object]:
    """Fresh copies of `sources` around `center`, in ring order, ready to be placed. Each keeps
    its source's height above the ground; `keep_first` makes the sources themselves the ring's
    first copy, so one fewer is made."""
    stamp = [(x, y, source.angle) for source in sources for x, y, _z in (source.position,)]
    made: list[Object] = []
    for placed in array_placements(stamp, center, options, pivot=pivot, keep_first=keep_first):
        for source, (x, y, angle) in zip(sources, placed, strict=True):
            obj = copy.deepcopy(source)
            obj.position = (x, y, source.position[2])
            obj.angle = angle
            obj.properties.pop("objectName", None)
            made.append(obj)
    return renumber_unique_ids(map, made)
