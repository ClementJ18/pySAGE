"""Free ids and names for new objects, waypoints and trigger areas.

The rules follow what the corpus maps store:
- `uniqueID` is `<type name> <N>`, with N counting from 0. Copied and imported objects repeat
  numbers, so a new object takes one past the highest number any `uniqueID` ends in.
- A waypoint's `uniqueID` is its `waypointName`. WorldBuilder names a new one `Waypoint <N>`.
- `waypointID` runs 1..n with no gaps in every sampled map, so a new waypoint takes n + 1.
- Trigger area ids are not renumbered when an area is deleted, so a new area takes the highest
  id + 1.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from sage_map.assets.object_list import Object
from sage_map.map import Map

__all__ = [
    "new_unique_id",
    "new_waypoint_name",
    "next_trigger_area_id",
    "next_unique_number",
    "next_waypoint_id",
]

_TRAILING_NUMBER = re.compile(r" (\d+)$")
_WAYPOINT_NAME = re.compile(r"Waypoint (\d+)", re.IGNORECASE)


def _objects(map: Map) -> Iterator[Object]:
    if map.objects_list is not None:
        yield from map.objects_list.object_list


def _value(obj: Object, key: str) -> object:
    stored = obj.properties.get(key)
    return stored["value"] if stored is not None else None


def next_unique_number(map: Map) -> int:
    """One past the highest number a `uniqueID` on the map ends in; 0 on a map with none."""
    numbers = [
        int(match.group(1))
        for obj in _objects(map)
        if isinstance(value := _value(obj, "uniqueID"), str)
        and (match := _TRAILING_NUMBER.search(value))
    ]
    return max(numbers, default=-1) + 1


def new_unique_id(map: Map, type_name: str) -> str:
    """The `uniqueID` for a new object of `type_name` (not for a waypoint: see module doc)."""
    return f"{type_name} {next_unique_number(map)}"


def next_waypoint_id(map: Map) -> int:
    ids = [value for obj in _objects(map) if isinstance(value := _value(obj, "waypointID"), int)]
    return max(ids, default=0) + 1


def new_waypoint_name(map: Map) -> str:
    """`Waypoint <N>`, one past the highest N an existing `Waypoint <N>` name or id uses."""
    numbers = [
        int(match.group(1))
        for obj in _objects(map)
        for key in ("waypointName", "uniqueID")
        if isinstance(value := _value(obj, key), str) and (match := _WAYPOINT_NAME.fullmatch(value))
    ]
    return f"Waypoint {max(numbers, default=0) + 1}"


def next_trigger_area_id(map: Map) -> int:
    areas = map.trigger_areas.trigger_areas if map.trigger_areas is not None else []
    return max((area.area_id for area in areas), default=0) + 1
