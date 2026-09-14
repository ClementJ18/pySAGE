"""Waypoints and the paths between them.

A waypoint is a placed object of type `*Waypoints/Waypoint`; `WaypointsList` holds the links as
`(start waypointID, end waypointID)` pairs. A new waypoint carries the object keys every object
has, then the waypoint keys in the order most corpus waypoints store them. Its `uniqueID` is its
name, and it belongs to the neutral team, as every corpus waypoint does.
"""

from __future__ import annotations

from sage_map.assets.object_list import Object
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand
from sage_worldbuilder.commands.edits import InsertItem, RemoveItem
from sage_worldbuilder.ids import new_waypoint_name, next_waypoint_id
from sage_worldbuilder.objects import OBJECTS, new_object

__all__ = [
    "WAYPOINT_TYPE",
    "add_linked_waypoint",
    "find_link",
    "new_waypoint",
    "toggle_link",
    "waypoint_id",
]

WAYPOINT_TYPE = "*Waypoints/Waypoint"
NEUTRAL_TEAM = "/team"
WAYPOINTS = Change(ChangeKind.WAYPOINTS)


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
