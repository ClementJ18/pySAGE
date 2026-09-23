"""Undoable edits to placed objects: move, rotate, delete, and copy and paste.

Objects are the map's own `Object` records, held by identity. Moves and rotations keep the state
from before the first of a run of merged edits, so undo and redo land exactly where they should
however many drag steps were merged.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from sage_map.assets.object_list import Object
from sage_map.assets.trigger_areas import TriggerArea
from sage_map.context import AssetPropertyType, Property
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand
from sage_worldbuilder.commands.edits import InsertItem
from sage_worldbuilder.ids import new_unique_id, next_unique_number, next_waypoint_id
from sage_worldbuilder.scene import WAYPOINT_PREFIX

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "CLIPBOARD_MIME",
    "Clipboard",
    "DeleteObjects",
    "GroupEditMethod",
    "MoveObjects",
    "RotateObjects",
    "clipboard_from_json",
    "clipboard_to_json",
    "copy_objects",
    "new_object",
    "place_objects",
    "paste_objects",
    "renumber_unique_ids",
]

OBJECTS = Change(ChangeKind.OBJECTS)
WAYPOINTS = Change(ChangeKind.WAYPOINTS)
AREAS = Change(ChangeKind.AREAS)


class GroupEditMethod(StrEnum):
    """Edit > Group Edit Method: how a rotation applies to several objects."""

    MATCH_LEAD = "Match Lead"
    AS_GROUP = "As Group"
    INDEPENDENT = "Independent"


def _same_objects(a: Sequence[object], b: Sequence[object]) -> bool:
    return len(a) == len(b) and all(x is y for x, y in zip(a, b, strict=True))


class MoveObjects(Command):
    """Move objects, and trigger areas with them, by `dx`, `dy` world units; `dz` raises the
    objects (areas have no height)."""

    def __init__(
        self,
        objects: Sequence[Object],
        dx: float,
        dy: float,
        label: str = "Move",
        areas: Sequence[TriggerArea] = (),
        dz: float = 0.0,
    ) -> None:
        self.objects = list(objects)
        self.areas = list(areas)
        self.dx, self.dy, self.dz = dx, dy, dz
        self.label = label
        # Set when the drag that issued it ends, so the next drag is an undo entry of its own.
        self.closed = False
        self._before: list[tuple[float, float, float]] | None = None
        self._area_before: list[list[tuple[float, float]]] = []

    def do(self, document: MapDocument) -> None:
        if self._before is None:
            self._before = [obj.position for obj in self.objects]
            self._area_before = [list(area.points) for area in self.areas]
        for obj, (x, y, z) in zip(self.objects, self._before, strict=True):
            obj.position = (x + self.dx, y + self.dy, z + self.dz)
        for area, points in zip(self.areas, self._area_before, strict=True):
            area.points = [(x + self.dx, y + self.dy) for x, y in points]

    def undo(self, document: MapDocument) -> None:
        assert self._before is not None
        for obj, position in zip(self.objects, self._before, strict=True):
            obj.position = position
        for area, points in zip(self.areas, self._area_before, strict=True):
            area.points = list(points)

    def changes(self) -> tuple[Change, ...]:
        return (OBJECTS, AREAS) if self.areas else (OBJECTS,)

    def merge(self, following: Command) -> bool:
        if self.closed or not (
            isinstance(following, MoveObjects)
            and _same_objects(self.objects, following.objects)
            and _same_objects(self.areas, following.areas)
        ):
            return False
        self.dx += following.dx
        self.dy += following.dy
        self.dz += following.dz
        return True


class RotateObjects(Command):
    """Turn objects by `delta` radians. As Group also swings their positions about the group's
    centre; Match Lead gives every object the lead's new angle."""

    def __init__(
        self,
        objects: Sequence[Object],
        delta: float,
        method: GroupEditMethod = GroupEditMethod.INDEPENDENT,
        label: str = "Rotate",
    ) -> None:
        self.objects = list(objects)
        self.delta = delta
        self.method = method
        self.label = label
        self.closed = False
        self._before: list[tuple[tuple[float, float, float], float]] | None = None

    def do(self, document: MapDocument) -> None:
        if self._before is None:
            self._before = [(obj.position, obj.angle) for obj in self.objects]
        if not self.objects:
            return
        if self.method is GroupEditMethod.MATCH_LEAD:
            angle = self._before[0][1] + self.delta
            for obj in self.objects:
                obj.angle = angle
            return
        for obj, (_position, angle) in zip(self.objects, self._before, strict=True):
            obj.angle = angle + self.delta
        if self.method is GroupEditMethod.AS_GROUP:
            positions = [position for position, _angle in self._before]
            cx = sum(x for x, _y, _z in positions) / len(positions)
            cy = sum(y for _x, y, _z in positions) / len(positions)
            cos, sin = math.cos(self.delta), math.sin(self.delta)
            for obj, (x, y, z) in zip(self.objects, positions, strict=True):
                ox, oy = x - cx, y - cy
                obj.position = (cx + ox * cos - oy * sin, cy + ox * sin + oy * cos, z)

    def undo(self, document: MapDocument) -> None:
        assert self._before is not None
        for obj, (position, angle) in zip(self.objects, self._before, strict=True):
            obj.position, obj.angle = position, angle

    def changes(self) -> tuple[Change, ...]:
        return (OBJECTS,)

    def merge(self, following: Command) -> bool:
        if self.closed or not (
            isinstance(following, RotateObjects)
            and following.method is self.method
            and _same_objects(self.objects, following.objects)
        ):
            return False
        self.delta += following.delta
        return True


def _waypoint_id(obj: Object) -> int | None:
    stored = obj.properties.get("waypointID")
    return int(stored["value"]) if stored is not None else None


class DeleteObjects(Command):
    """Remove objects from the map, and the waypoint links that touch a removed waypoint."""

    def __init__(self, objects: Sequence[Object], label: str = "Delete") -> None:
        self.objects = list(objects)
        self.label = label
        self._removed: list[tuple[int, Object]] = []
        self._links: list[tuple[int, tuple[int, int]]] = []

    def do(self, document: MapDocument) -> None:
        map = document.map
        listed = map.objects_list.object_list if map.objects_list is not None else []
        wanted = {id(obj) for obj in self.objects}
        self._removed = [(index, obj) for index, obj in enumerate(listed) if id(obj) in wanted]
        for index, _obj in reversed(self._removed):
            del listed[index]
        ids = {_waypoint_id(obj) for _index, obj in self._removed} - {None}
        self._links = []
        if map.waypoints_list is not None and ids:
            paths = map.waypoints_list.waypoint_paths
            self._links = [
                (index, link)
                for index, link in enumerate(paths)
                if link[0] in ids or link[1] in ids
            ]
            for index, _link in reversed(self._links):
                del paths[index]

    def undo(self, document: MapDocument) -> None:
        map = document.map
        if map.objects_list is not None:
            for index, obj in self._removed:
                map.objects_list.object_list.insert(index, obj)
        if map.waypoints_list is not None:
            for index, link in self._links:
                map.waypoints_list.waypoint_paths.insert(index, link)

    def changes(self) -> tuple[Change, ...]:
        return (OBJECTS, WAYPOINTS)


@dataclass(frozen=True)
class Clipboard:
    """Copies of objects, the waypoint links among them, and the centre they were copied about."""

    objects: tuple[Object, ...]
    links: tuple[tuple[int, int], ...]
    center: tuple[float, float]


def copy_objects(map: Map, objects: Sequence[Object]) -> Clipboard:
    copies = tuple(copy.deepcopy(obj) for obj in objects)
    ids = {_waypoint_id(obj) for obj in objects} - {None}
    links: tuple[tuple[int, int], ...] = ()
    if map.waypoints_list is not None:
        links = tuple(
            link for link in map.waypoints_list.waypoint_paths if link[0] in ids and link[1] in ids
        )
    if copies:
        cx = sum(obj.position[0] for obj in copies) / len(copies)
        cy = sum(obj.position[1] for obj in copies) / len(copies)
    else:
        cx = cy = 0.0
    return Clipboard(copies, links, (cx, cy))


# The clipboard format copied objects travel in between editors.
CLIPBOARD_MIME = "application/x-sage-worldbuilder-objects"
_CLIPBOARD_FORMAT = 1


def clipboard_to_json(clipboard: Clipboard) -> str:
    """The clipboard as text another editor can paste from: the objects' records in full."""
    return json.dumps(
        {
            "format": _CLIPBOARD_FORMAT,
            "center": list(clipboard.center),
            "links": [list(link) for link in clipboard.links],
            "objects": [
                {
                    "version": obj.version,
                    "position": list(obj.position),
                    "angle": obj.angle,
                    "road_type": obj.road_type,
                    "type_name": obj.type_name,
                    "properties": [
                        [stored["name"], int(stored["type"]), stored["value"]]
                        for stored in obj.properties.values()
                    ],
                }
                for obj in clipboard.objects
            ],
        }
    )


def clipboard_from_json(text: str) -> Clipboard | None:
    """The clipboard `clipboard_to_json` wrote, or None for text that is not one."""
    try:
        data = json.loads(text)
        if data.get("format") != _CLIPBOARD_FORMAT:
            return None
        objects = tuple(
            Object(
                int(item["version"]),
                _vector(item["position"]),
                float(item["angle"]),
                int(item["road_type"]),
                str(item["type_name"]),
                {
                    str(name): {"name": str(name), "type": AssetPropertyType(kind), "value": value}
                    for name, kind, value in item["properties"]
                },
                0,
                0,
            )
            for item in data["objects"]
        )
        links = tuple((int(start), int(end)) for start, end in data["links"])
        cx, cy = data["center"]
        return Clipboard(objects, links, (float(cx), float(cy)))
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _vector(values: Sequence[float]) -> tuple[float, float, float]:
    x, y, z = values
    return float(x), float(y), float(z)


def _set_text(obj: Object, key: str, value: str) -> None:
    stored = obj.properties.get(key)
    if stored is not None:
        obj.properties[key] = {**stored, "value": value}


def paste_objects(
    map: Map, clipboard: Clipboard, at: tuple[float, float]
) -> tuple[Command, list[Object]]:
    """The command adding fresh copies of the clipboard centred on `at`, and those copies.

    Each copy gets a new `uniqueID`; a waypoint also gets a new `waypointID` and, when its name is
    taken, a new `Waypoint <N>` name. An object keeps its `objectName` only while no other object
    has it, since scripts find objects by name."""
    if map.objects_list is None:
        raise ValueError("the map has no object list to paste into")
    listed = map.objects_list.object_list
    dx, dy = at[0] - clipboard.center[0], at[1] - clipboard.center[1]
    names = {
        str(obj.properties[key]["value"]).lower()
        for obj in listed
        for key in ("objectName", "waypointName")
        if key in obj.properties and obj.properties[key]["value"]
    }
    number = next_unique_number(map)
    waypoint_id = next_waypoint_id(map)
    waypoint_number = _max_waypoint_number(listed)
    remap: dict[int, int] = {}
    pasted: list[Object] = []
    for original in clipboard.objects:
        obj = copy.deepcopy(original)
        x, y, z = obj.position
        obj.position = (x + dx, y + dy, z)
        if obj.type_name.startswith(WAYPOINT_PREFIX):
            old_id = _waypoint_id(obj)
            if old_id is not None:
                remap[old_id] = waypoint_id
                obj.properties["waypointID"] = {
                    **obj.properties["waypointID"],
                    "value": waypoint_id,
                }
                waypoint_id += 1
            stored_name = obj.properties.get("waypointName")
            name = str(stored_name["value"]) if stored_name is not None else ""
            if not name or name.lower() in names:
                waypoint_number += 1
                name = f"Waypoint {waypoint_number}"
                _set_text(obj, "waypointName", name)
            names.add(name.lower())
            _set_text(obj, "uniqueID", name)
        else:
            _set_text(obj, "uniqueID", f"{obj.type_name} {number}")
            number += 1
            stored = obj.properties.get("objectName")
            if stored is not None and stored["value"]:
                if str(stored["value"]).lower() in names:
                    del obj.properties["objectName"]
                else:
                    names.add(str(stored["value"]).lower())
        pasted.append(obj)
    commands: list[Command] = [
        InsertItem(listed, len(listed) + index, obj, OBJECTS, "Paste")
        for index, obj in enumerate(pasted)
    ]
    if map.waypoints_list is not None:
        paths = map.waypoints_list.waypoint_paths
        commands += [
            InsertItem(paths, len(paths) + index, (remap[start], remap[end]), WAYPOINTS, "Paste")
            for index, (start, end) in enumerate(clipboard.links)
            if start in remap and end in remap
        ]
    return CompositeCommand("Paste", commands), pasted


def _max_waypoint_number(objects: Sequence[Object]) -> int:
    best = 0
    for obj in objects:
        for key in ("waypointName", "uniqueID"):
            stored = obj.properties.get(key)
            text = str(stored["value"]) if stored is not None else ""
            if text.lower().startswith("waypoint ") and text[9:].isdigit():
                best = max(best, int(text[9:]))
    return best


# The object record version every corpus map stores.
OBJECT_VERSION = 3
_BOOLEAN, _INTEGER = AssetPropertyType.Boolean, AssetPropertyType.Integer
_TEXT = AssetPropertyType.AsciiString


def new_object(
    map: Map,
    type_name: str,
    position: tuple[float, float, float],
    angle: float,
    owner: str,
    layer: str = "",
) -> Object:
    """A placed object with the properties a new object carries, in the order most corpus objects
    store them, and a fresh `uniqueID`. Its record version follows the map's other objects."""
    listed = map.objects_list.object_list if map.objects_list is not None else []
    version = listed[0].version if listed else OBJECT_VERSION
    values: tuple[tuple[str, AssetPropertyType, bool | int | str], ...] = (
        ("objectInitialHealth", _INTEGER, 100),
        ("objectEnabled", _BOOLEAN, True),
        ("objectIndestructible", _BOOLEAN, False),
        ("objectUnsellable", _BOOLEAN, False),
        ("objectPowered", _BOOLEAN, True),
        ("objectRecruitableAI", _BOOLEAN, True),
        ("objectTargetable", _BOOLEAN, False),
        ("objectBasePriority", _INTEGER, 40),
        ("objectBasePhase", _INTEGER, 1),
        ("originalOwner", _TEXT, owner),
        ("uniqueID", _TEXT, new_unique_id(map, type_name)),
        ("objectLayer", _TEXT, layer),
    )
    properties: dict[str, Property] = {
        name: {"name": name, "type": kind, "value": value} for name, kind, value in values
    }
    return Object(version, position, angle, 0, type_name, properties, 0, 0)


def renumber_unique_ids(map: Map, objects: Sequence[Object]) -> list[Object]:
    """Give new objects consecutive `uniqueID` numbers after the map's, since each was made before
    the others were on the map."""
    number = next_unique_number(map)
    for obj in objects:
        stored = obj.properties.get("uniqueID")
        if stored is not None:
            obj.properties["uniqueID"] = {**stored, "value": f"{obj.type_name} {number}"}
            number += 1
    return list(objects)


def place_objects(map: Map, objects: Sequence[Object], label: str = "Place Object") -> Command:
    """The command appending `objects` to the map's object list."""
    if map.objects_list is None:
        raise ValueError("the map has no object list to place objects in")
    listed = map.objects_list.object_list
    return CompositeCommand(
        label,
        [
            InsertItem(listed, len(listed) + index, obj, OBJECTS, label)
            for index, obj in enumerate(objects)
        ],
    )
