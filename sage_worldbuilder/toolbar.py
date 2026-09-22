"""The main toolbar's catalogue: every action a user may put on it, and the layout they get before
they ever open the customisation dialog.

Letting a user choose what the toolbar shows means there has to be something to choose *from*,
independent of Qt and of `MainWindow` itself: a plain catalogue of stable ids the settings file can
store, a dialog can list, and the toolbar builder (`MainWindow._build_toolbar`) can turn back into
actions. `ITEMS_BY_ID` is that catalogue's index; `DEFAULT_ITEMS` is what a user who never opens the
dialog sees.

A stored layout is just the ids the user picked, in the order they picked them; `normalise` is
what keeps a stored layout honest as the catalogue itself changes underneath it - an id this build
of the catalogue does not carry is quietly dropped rather than crashing the toolbar, and a
duplicate (from hand-edited settings) collapses to its first occurrence. Separators are not part
of this model: they are a rendering detail of the toolbar itself, inserted wherever the group
changes, so the stored layout only ever needs to say which items and in what order.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolbarItem:
    """One action the toolbar can show.

    `id` is the stable key a layout is stored by; it must not change once shipped, or existing
    users' saved layouts silently lose the item. `label` is the plain-text name a customisation
    dialog shows (the action's menu text with Qt's `&` accelerator stripped). `group` sections the
    catalogue for that dialog, following how `window.py` already groups its actions.
    """

    id: str
    label: str
    group: str


# File
_FILE = "File"
# Edit
_EDIT = "Edit"
# The general object/selection tools: what a user reaches for most often.
_TOOLS = "Tools"
# The lake/river/wave tools.
_WATER = "Water"
# World dressing: scorchmarks, groves, fences, ramps, borders, mesh mold.
_DRESSING = "Dressing"
# Height and texture painting.
_TERRAIN = "Terrain"
_LOCKS = "Locks"
_GAME = "Game"

CATALOGUE: tuple[ToolbarItem, ...] = (
    ToolbarItem("new", "New…", _FILE),
    ToolbarItem("open", "Open…", _FILE),
    ToolbarItem("save", "Save", _FILE),
    ToolbarItem("save-as", "Save As…", _FILE),
    ToolbarItem("undo", "Undo", _EDIT),
    ToolbarItem("redo", "Redo", _EDIT),
    ToolbarItem("cut", "Cut", _EDIT),
    ToolbarItem("copy", "Copy", _EDIT),
    ToolbarItem("paste", "Paste", _EDIT),
    ToolbarItem("delete", "Delete", _EDIT),
    ToolbarItem("select-tool", "Select and Move", _TOOLS),
    ToolbarItem("move-tool", "Move Tool", _TOOLS),
    ToolbarItem("rotate-tool", "Rotate Tool", _TOOLS),
    ToolbarItem("place-tool", "Place Object", _TOOLS),
    ToolbarItem("array-tool", "Radial Array", _TOOLS),
    ToolbarItem("waypoint-tool", "Waypoint Tool", _TOOLS),
    ToolbarItem("polygon-tool", "Polygon Tool", _TOOLS),
    ToolbarItem("build-list-tool", "Build List Tool", _TOOLS),
    ToolbarItem("road-tool", "Road", _TOOLS),
    ToolbarItem("generic-ai-tool", "Generic AI Object Tool", _TOOLS),
    ToolbarItem("ruler-tool", "Ruler Tool", _TOOLS),
    ToolbarItem("lake-tool", "Lake/Ocean Tool", _WATER),
    ToolbarItem("river-tool", "River Tool", _WATER),
    ToolbarItem("waves-tool", "Waves Tool", _WATER),
    ToolbarItem("scorch-tool", "Add Scorchmarks", _DRESSING),
    ToolbarItem("grove-tool", "Grove", _DRESSING),
    ToolbarItem("fence-tool", "Fence", _DRESSING),
    ToolbarItem("ramp-tool", "Ramp", _DRESSING),
    ToolbarItem("border-tool", "Border Tool", _DRESSING),
    ToolbarItem("mesh-mold-tool", "Mesh Mold Tool", _DRESSING),
    ToolbarItem("height-brush-tool", "Height Brush", _TERRAIN),
    ToolbarItem("mound-tool", "Mound", _TERRAIN),
    ToolbarItem("dig-tool", "Dig", _TERRAIN),
    ToolbarItem("smooth-height-tool", "Smooth Height", _TERRAIN),
    ToolbarItem("single-tile-tool", "Single Tile", _TERRAIN),
    ToolbarItem("large-tile-tool", "Large Tile", _TERRAIN),
    ToolbarItem("flood-fill-tool", "Flood Fill", _TERRAIN),
    ToolbarItem("eyedropper-tool", "Eyedropper", _TERRAIN),
    ToolbarItem("blend-single-edge-tool", "Blend Single Edge", _TERRAIN),
    ToolbarItem("auto-edge-out-tool", "Auto Edge Out", _TERRAIN),
    ToolbarItem("auto-edge-in-tool", "Auto Edge In", _TERRAIN),
    ToolbarItem("terrain-copy-tool", "Terrain Copy", _TERRAIN),
    ToolbarItem("lock-selection", "Lock Selection", _LOCKS),
    ToolbarItem("lock-angle", "Lock Angle", _LOCKS),
    ToolbarItem("lock-vertical", "Lock Vertical", _LOCKS),
    ToolbarItem("jump", "Jump To Game", _GAME),
)

ITEMS_BY_ID: dict[str, ToolbarItem] = {item.id: item for item in CATALOGUE}

# The layout the toolbar shows until a user customises it: open, save | undo, redo | every tool
# action, in the order `_build_actions` adds them to `self.tool_actions` | the three lock toggles
# | jump.
DEFAULT_ITEMS: tuple[str, ...] = (
    "open",
    "save",
    "undo",
    "redo",
    "select-tool",
    "move-tool",
    "rotate-tool",
    "place-tool",
    "array-tool",
    "waypoint-tool",
    "polygon-tool",
    "build-list-tool",
    "road-tool",
    "generic-ai-tool",
    "lake-tool",
    "river-tool",
    "waves-tool",
    "scorch-tool",
    "grove-tool",
    "fence-tool",
    "ramp-tool",
    "border-tool",
    "mesh-mold-tool",
    "ruler-tool",
    "height-brush-tool",
    "mound-tool",
    "dig-tool",
    "smooth-height-tool",
    "single-tile-tool",
    "large-tile-tool",
    "flood-fill-tool",
    "eyedropper-tool",
    "blend-single-edge-tool",
    "auto-edge-out-tool",
    "auto-edge-in-tool",
    "terrain-copy-tool",
    "lock-selection",
    "lock-angle",
    "lock-vertical",
    "jump",
)


def normalise(items: Iterable[str]) -> tuple[str, ...]:
    """`items` with anything not in `CATALOGUE` dropped and a repeated id kept only at its first
    occurrence, so a stored layout stays valid across catalogue changes and hand-edited settings."""
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        if item in ITEMS_BY_ID and item not in seen:
            seen.add(item)
            kept.append(item)
    return tuple(kept)
