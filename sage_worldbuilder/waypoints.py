"""Waypoints and the paths between them.

A waypoint is a placed object of type `*Waypoints/Waypoint`; `WaypointsList` holds the links as
`(start waypointID, end waypointID)` pairs. A new waypoint carries the object keys every object
has, then the waypoint keys in the order most corpus waypoints store them. Its `uniqueID` is its
name, and it belongs to the neutral team, as every corpus waypoint does.

A waypoint's type is one value per waypoint, except a spline: WorldBuilder gives a whole path
the type when a waypoint on it becomes a spline or stops being one
(`worldbuilder.exe` `0x00632F40`, spreading along links in both directions from `0x006331A0`).
"""

from __future__ import annotations

from sage_map.assets.object_list import Object
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand
from sage_worldbuilder.commands.edits import InsertItem, RemoveItem, SetProperty
from sage_worldbuilder.ids import new_waypoint_name, next_waypoint_id
from sage_worldbuilder.objects import OBJECTS, new_object

__all__ = [
    "WAYPOINT_TYPE",
    "add_linked_waypoint",
    "find_link",
    "linked_waypoint_ids",
    "new_waypoint",
    "set_waypoint_type",
    "toggle_link",
    "waypoint_id",
]

WAYPOINT_TYPE = "*Waypoints/Waypoint"
NEUTRAL_TEAM = "/team"
WAYPOINTS = Change(ChangeKind.WAYPOINTS)
SPLINE = 6


def waypoint_id(obj: Object) -> int | None:
    stored = obj.properties.get("waypointID")
    return int(stored["value"]) if stored is not None else None


def new_waypoint(map: Map, position: tuple[float, float, float], layer: str = "") -> Object:
    """A waypoint named `Waypoint <N>` with the next free id."""
    obj = new_object(map, WAYPOINT_TYPE, position, 0.0, NEUTRAL_TEAM, layer)
    name = new_waypoint_name(map)
    text, integer = AssetPropertyType.AsciiString, AssetPropertyType.Integer
    obj.properties["uniqueID"] = {"name": "uniqueID", "type": text, "value": name}
    for key, kind, value in (
        ("waypointID", integer, next_waypoint_id(map)),
        ("waypointName", text, name),
        ("waypointTypeOption", text, ""),
        ("waypointPathLabel1", text, ""),
        ("waypointPathLabel2", text, ""),
        ("waypointPathLabel3", text, ""),
    ):
        obj.properties[key] = {"name": key, "type": kind, "value": value}
    return obj


def _paths(map: Map) -> list[tuple[int, int]]:
    if map.waypoints_list is None:
        raise ValueError("the map has no waypoint list")
    return map.waypoints_list.waypoint_paths


def find_link(map: Map, first: int, second: int) -> int | None:
    """The index of the link between two waypoints, in either direction."""
    for index, link in enumerate(_paths(map)):
        if link in ((first, second), (second, first)):
            return index
    return None


def toggle_link(map: Map, start: int, end: int) -> Command:
    """Link two waypoints, or remove the link between them when there is one."""
    paths = _paths(map)
    index = find_link(map, start, end)
    if index is not None:
        return RemoveItem(paths, index, WAYPOINTS, "Unlink Waypoints")
    return InsertItem(paths, len(paths), (start, end), WAYPOINTS, "Link Waypoints")


def add_linked_waypoint(
    map: Map, start: int, position: tuple[float, float, float], layer: str = ""
) -> tuple[Command, Object]:
    """A new waypoint at `position` linked from waypoint `start`, as one edit."""
    if map.objects_list is None:
        raise ValueError("the map has no object list")
    paths = _paths(map)
    obj = new_waypoint(map, position, layer)
    new_id = waypoint_id(obj)
    assert new_id is not None
    listed = map.objects_list.object_list
    command = CompositeCommand(
        "Add Waypoint",
        [
            InsertItem(listed, len(listed), obj, OBJECTS, "Add Waypoint"),
            InsertItem(paths, len(paths), (start, new_id), WAYPOINTS, "Add Waypoint"),
        ],
    )
    return command, obj


def linked_waypoint_ids(map: Map, start: int) -> set[int]:
    """The ids of every waypoint reachable from `start` over links, either way along them,
    `start` included."""
    neighbours: dict[int, list[int]] = {}
    for first, second in _paths(map):
        neighbours.setdefault(first, []).append(second)
        neighbours.setdefault(second, []).append(first)
    found, pending = {start}, [start]
    while pending:
        for other in neighbours.get(pending.pop(), ()):
            if other not in found:
                found.add(other)
                pending.append(other)
    return found


def _type_of(obj: Object) -> int:
    stored = obj.properties.get("waypointType")
    return int(stored["value"]) if stored is not None else 0


def set_waypoint_type(map: Map, waypoints: list[Object], value: int) -> Command:
    """Set the type of `waypoints`; to or from a spline, the type goes to their whole paths."""
    targets = list(waypoints)
    if map.objects_list is not None and map.waypoints_list is not None:
        ids: set[int] = set()
        for obj in waypoints:
            number = waypoint_id(obj)
            if number is not None and SPLINE in (value, _type_of(obj)):
                ids |= linked_waypoint_ids(map, number)
        chosen = {id(obj) for obj in targets}
        targets += [
            obj
            for obj in map.objects_list.object_list
            if id(obj) not in chosen and waypoint_id(obj) in ids
        ]
    label = "Set Waypoint type"
    integer = AssetPropertyType.Integer
    return CompositeCommand(
        label,
        [
            SetProperty(
                obj.properties,
                "waypointType",
                {"name": "waypointType", "type": integer, "value": value},
                OBJECTS,
                label,
            )
            for obj in targets
        ],
    )
