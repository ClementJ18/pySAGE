"""Layers: the name each placed object (`objectLayer`) and trigger area (`layer_name`) carries.

A map has no layer chunk: a layer exists while something is on it, and `''` is the default layer
(WorldBuilder's tree shows it as Default Object Layer and Default Trigger Layer). So every layer
edit is an ordinary edit of those names; hiding a layer and the active layer are view state,
never saved.
"""

from __future__ import annotations

from collections.abc import Iterable

from sage_map.assets.object_list import Object
from sage_map.assets.trigger_areas import TriggerArea
from sage_map.context import AssetPropertyType, Property
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand, SetAttribute
from sage_worldbuilder.commands.edits import SetProperty

__all__ = [
    "DEFAULT_LAYER",
    "delete_layer",
    "item_layer",
    "items_in_layer",
    "layer_counts",
    "merge_layer",
    "rename_layer",
    "set_layer",
]

DEFAULT_LAYER = ""
OBJECTS = Change(ChangeKind.OBJECTS)
AREAS = Change(ChangeKind.AREAS)


def item_layer(item: object) -> str | None:
    """The layer an object or trigger area is on; None for anything else."""
    if isinstance(item, Object):
        stored = item.properties.get("objectLayer")
        return str(stored["value"]) if stored is not None else DEFAULT_LAYER
    if isinstance(item, TriggerArea):
        return item.layer_name
    return None


def _items(map: Map) -> list[object]:
    items: list[object] = []
    if map.objects_list is not None:
        items += map.objects_list.object_list
    if map.trigger_areas is not None:
        items += map.trigger_areas.trigger_areas
    return items


def layer_counts(map: Map) -> dict[str, tuple[int, int]]:
    """Layer name -> (objects, trigger areas) on it: the default layer first, then by name."""
    counts: dict[str, list[int]] = {DEFAULT_LAYER: [0, 0]}
    for item in _items(map):
        name = item_layer(item)
        if name is None:
            continue
        row = counts.setdefault(name, [0, 0])
        row[0 if isinstance(item, Object) else 1] += 1
    ordered = sorted(counts, key=lambda name: (name != DEFAULT_LAYER, name.casefold()))
    return {name: (counts[name][0], counts[name][1]) for name in ordered}


def items_in_layer(map: Map, name: str) -> list[object]:
    return [item for item in _items(map) if item_layer(item) == name]


def set_layer(items: Iterable[object], name: str, label: str = "Move to Layer") -> CompositeCommand:
    """The command putting objects and trigger areas on layer `name`; items already there are
    left alone, so the command may be empty."""
    commands: list[Command] = []
    for item in items:
        if item_layer(item) == name:
            continue
        if isinstance(item, Object):
            value: Property = {
                "name": "objectLayer",
                "type": AssetPropertyType.AsciiString,
                "value": name,
            }
            commands.append(SetProperty(item.properties, "objectLayer", value, OBJECTS, label))
        elif isinstance(item, TriggerArea):
            commands.append(SetAttribute(item, "layer_name", name, AREAS, label))
    return CompositeCommand(label, commands)


def rename_layer(map: Map, old: str, new: str) -> CompositeCommand:
    return set_layer(items_in_layer(map, old), new, "Rename Layer")


def delete_layer(map: Map, name: str) -> CompositeCommand:
    """Move everything on the layer back to the default layer."""
    return set_layer(items_in_layer(map, name), DEFAULT_LAYER, "Delete Layer")


def merge_layer(map: Map, name: str, into: str) -> CompositeCommand:
    return set_layer(items_in_layer(map, name), into, "Merge Layer")
