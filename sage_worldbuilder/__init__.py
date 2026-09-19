"""A map editor for SAGE `.map` files, built to replace WorldBuilder.

The model layer here is Qt-free: `MapDocument` holds the map and its undo stack, every edit is a
`Command`, and `categories` lists the maps the Open dialog offers. See PLAN.md for the roadmap.
"""

from sage_worldbuilder.autosave import Autosaver, AutosaveSettings
from sage_worldbuilder.categories import MapCategory, MapEntry, list_maps
from sage_worldbuilder.changes import Change, ChangeKind, Region
from sage_worldbuilder.commands import Command, CompositeCommand, SetAttribute, UndoStack
from sage_worldbuilder.document import MapDocument, ReadOnlyMapError
from sage_worldbuilder.safeio import atomic_write

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
