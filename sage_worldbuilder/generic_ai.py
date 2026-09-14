"""Generic AI objects: the markers the AI reads wall hubs and expansion spots from.

WorldBuilder's Generic AI Object tool (`GenericAIObjectTool.cpp`, command 33500) places a
`*GenericAIObjects/GenericAIObject` object owned by `/team`, named `GenericAIObject %d` with the
first free number (`0x00500180`), and Generic AI Object Options (dialog 294) sets its type, `Wall
Hub` or `Expansion Locator`, and a wall hub's number (dialog 295). The four values are object
properties, stored after the properties every new object carries, in the order all 222 corpus
generic AI objects store them.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum

from sage_map.assets.object_list import Object
from sage_map.context import AssetPropertyType, Property
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand
from sage_worldbuilder.commands.edits import SetProperty
from sage_worldbuilder.objects import new_object
from sage_worldbuilder.scene import GENERIC_AI_PREFIX

__all__ = [
    "GENERIC_AI_OBJECT",
    "PICK_DISTANCES",
    "GenericAIType",
    "generic_ai_objects",
    "generic_ai_values",
    "is_generic_ai",
    "new_generic_ai_object",
    "set_generic_ai",
]

GENERIC_AI_OBJECT = f"{GENERIC_AI_PREFIX}GenericAIObject"
OWNER = "/team"
NAME_FORMAT = "GenericAIObject {}"
# A click picks the generic AI object within the first of these world distances that has one
# (`GenericAIObjectTool::pickGenericAIObject`, `0x00501180`).
PICK_DISTANCES = (5.0, 15.0)

TYPE_KEY = "GenericAIObjectType"
ID_KEY = "GenericAIObjectID"
NAME_KEY = "GenericAIObjectName"
WALL_HUB_KEY = "GenericAIObjectWallHubNumber"

_OBJECTS = Change(ChangeKind.OBJECTS)
_INTEGER, _TEXT = AssetPropertyType.Integer, AssetPropertyType.AsciiString


class GenericAIType(IntEnum):
    """The type combo's entries, in the order `GenericAIObjectOptions::OnInitDialog` adds them."""

    WALL_HUB = 0
    EXPANSION_LOCATOR = 1

    @property
    def label(self) -> str:
        return "Wall Hub" if self is GenericAIType.WALL_HUB else "Expansion Locator"


def is_generic_ai(obj: Object) -> bool:
    return obj.type_name.startswith(GENERIC_AI_PREFIX)


def generic_ai_objects(map: Map) -> list[Object]:
    objects = map.objects_list.object_list if map.objects_list is not None else []
    return [obj for obj in objects if is_generic_ai(obj)]


def _value(obj: Object, key: str, default: int | str) -> int | str:
    stored = obj.properties.get(key)
    value = stored["value"] if stored is not None else default
    return value if type(value) is type(default) else default


def generic_ai_values(obj: Object) -> tuple[str, GenericAIType | int, int, int]:
    """The object's name, type (a plain number when it is not one the dialog lists), wall hub
    number and id."""
    kind = _value(obj, TYPE_KEY, 0)
    assert isinstance(kind, int)
    try:
        shown: GenericAIType | int = GenericAIType(kind)
    except ValueError:
        shown = kind
    name, hub, identity = (
        _value(obj, NAME_KEY, ""),
        _value(obj, WALL_HUB_KEY, 0),
        _value(obj, ID_KEY, 0),
    )
    assert isinstance(name, str) and isinstance(hub, int) and isinstance(identity, int)
    return name, shown, hub, identity


def _free_name(map: Map) -> str:
    taken = {str(_value(obj, NAME_KEY, "")) for obj in generic_ai_objects(map)}
    number = 1
    while NAME_FORMAT.format(number) in taken:
        number += 1
    return NAME_FORMAT.format(number)


def _next_id(map: Map) -> int:
    """One above the map's highest generic AI object id. WorldBuilder counts on its document,
    which is not saved; the corpus maps number their objects densely, as this does."""
    ids = [int(_value(obj, ID_KEY, 0)) for obj in generic_ai_objects(map)]
    return max(ids, default=0) + 1


def _property(name: str, kind: AssetPropertyType, value: int | str) -> Property:
    return {"name": name, "type": kind, "value": value}


def new_generic_ai_object(
    map: Map,
    position: tuple[float, float, float],
    kind: GenericAIType = GenericAIType.WALL_HUB,
    wall_hub: int = 0,
    layer: str = "",
) -> Object:
    """A generic AI object at `position` with the next free name and id."""
    obj = new_object(map, GENERIC_AI_OBJECT, position, 0.0, OWNER, layer)
    for name, stored, value in (
        (TYPE_KEY, _INTEGER, int(kind)),
        (ID_KEY, _INTEGER, _next_id(map)),
        (NAME_KEY, _TEXT, _free_name(map)),
        (WALL_HUB_KEY, _INTEGER, wall_hub),
    ):
        obj.properties[name] = _property(name, stored, value)
    return obj


def set_generic_ai(
    objects: Sequence[Object],
    *,
    name: str | None = None,
    kind: GenericAIType | None = None,
    wall_hub: int | None = None,
) -> Command | None:
    """The edit giving `objects` the values passed, or `None` when none of them changes."""
    commands: list[Command] = []
    for obj in objects:
        for key, stored, value in (
            (NAME_KEY, _TEXT, name),
            (TYPE_KEY, _INTEGER, None if kind is None else int(kind)),
            (WALL_HUB_KEY, _INTEGER, wall_hub),
        ):
            if value is None:
                continue
            current = obj.properties.get(key)
            if current is not None and current["value"] == value:
                continue
            commands.append(
                SetProperty(obj.properties, key, _property(key, stored, value), _OBJECTS)
            )
    if not commands:
        return None
    return CompositeCommand("Generic AI Object Options", commands)
