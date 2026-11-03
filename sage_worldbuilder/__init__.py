"""A map editor for SAGE `.map` files, built to replace WorldBuilder.

The model layer here is Qt-free: `MapDocument` holds the map and its undo stack, every edit is a
`Command`, and `categories` lists the maps the Open dialog offers.

The names below load on first use, so importing a subpackage (the entry points under `ui` and
`mcp_server`) does not pull in numpy before those entry points can report a missing extra.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sage_worldbuilder.autosave import Autosaver, AutosaveSettings
    from sage_worldbuilder.categories import MapCategory, MapEntry, list_maps
    from sage_worldbuilder.changes import Change, ChangeKind, Region
    from sage_worldbuilder.commands import Command, CompositeCommand, SetAttribute, UndoStack
    from sage_worldbuilder.document import MapDocument, ReadOnlyMapError
    from sage_worldbuilder.safeio import atomic_write

_EXPORTS = {
    "AutosaveSettings": "sage_worldbuilder.autosave",
    "Autosaver": "sage_worldbuilder.autosave",
    "Change": "sage_worldbuilder.changes",
    "ChangeKind": "sage_worldbuilder.changes",
    "Command": "sage_worldbuilder.commands",
    "CompositeCommand": "sage_worldbuilder.commands",
    "MapCategory": "sage_worldbuilder.categories",
    "MapDocument": "sage_worldbuilder.document",
    "MapEntry": "sage_worldbuilder.categories",
    "ReadOnlyMapError": "sage_worldbuilder.document",
    "Region": "sage_worldbuilder.changes",
    "SetAttribute": "sage_worldbuilder.commands",
    "UndoStack": "sage_worldbuilder.commands",
    "atomic_write": "sage_worldbuilder.safeio",
    "list_maps": "sage_worldbuilder.categories",
}

__all__ = [
    "AutosaveSettings",
    "Autosaver",
    "Change",
    "ChangeKind",
    "Command",
    "CompositeCommand",
    "MapCategory",
    "MapDocument",
    "MapEntry",
    "ReadOnlyMapError",
    "Region",
    "SetAttribute",
    "UndoStack",
    "atomic_write",
    "list_maps",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value
