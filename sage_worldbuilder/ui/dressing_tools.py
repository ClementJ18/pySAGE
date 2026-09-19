"""The world dressing tools: Add Scorchmarks (33007), Grove (32924), Fence (32979), Ramp (33467),
Border Tool (33330) and Mesh Mold Tool (32955).

What each writes follows `dressing.py`. How each answers the mouse is a choice made from the
tools' tooltips and option panels, since WorldBuilder's handlers for them were not read:

- Scorch: click to add a scorch mark of the Dressing Options type and size, or drag from the spot
  to size it to the drag.
- Grove: "Click to place random foliage, drag to place foliage in a rectangular area."
- Fence: "Places a row of objects. Drag then use shift to stretch": a drag places the Object
  Palette's object along it; with Shift held when the button comes up, the row is stretched to
  end where the drag does. A click places one.
- Ramp: drag from one end of the ramp to the other; the ground under the drag, Ramp Width across,
  becomes a straight slope when the button comes up.
- Border: click to add a border reaching the clicked spot from the map's corner; drag a border's
  corner handle to resize it; Alt-click a handle to remove that border (the last one stays).
- Mesh Mold: click or drag to place the mold (its reach and facing are drawn); Dressing Options'
  Apply shapes the ground under it.

Each gesture is one undo entry, and what a tool adds is selected.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from sage_map.assets.height_map import HeightMapBorder
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.dressing import (
    GroveOptions,
    MoldOptions,
    ResizeBorder,
    add_border,
    cluster_points,
    fence_objects,
    fence_points,
    grove_objects,
    mold_patch,
    new_scorch,
    pick_tree,
    ramp_patch,
    rectangle_points,
    remove_border,
)
from sage_worldbuilder.objects import place_objects
from sage_worldbuilder.terrain.edits import PatchHeights
from sage_worldbuilder.terrain.grid import WORLD_UNITS_PER_CELL
from sage_worldbuilder.ui.overlays import road_corners
from sage_worldbuilder.ui.tools import DRAG_PIXELS, PICK_PIXELS, EditHost, Gesture, Tool, ToolView
from sage_worldbuilder.viewport import snap

__all__ = [
    "BorderTool",
    "DressingHost",
    "FenceTool",
    "GroveTool",
    "MeshMoldTool",
    "RampTool",
    "ScorchTool",
]

_FEEDBACK = QColor(255, 255, 255, 200)


class DressingHost(EditHost, Protocol):
    def place_template(self) -> str | None: ...

    def place_owner(self) -> str: ...

    def scorch_settings(self) -> tuple[int, float]:
        """Dressing Options' scorch type (0-3) and size."""
        ...

    def grove_settings(self) -> GroveOptions: ...

    def fence_spacing(self) -> float: ...

    def ramp_width(self) -> float: ...

    def mold_settings(self) -> MoldOptions: ...

    def mold_mesh(self, name: str) -> np.ndarray | None:
        """A mold's triangles in model space, `(T, 3, 3)`, or None when it cannot be read."""
        ...

    def show_status(self, text: str) -> None: ...


class _DragTool(Tool):
    """A press, the drag from it, and the spot under the cursor when no button is down."""

    def __init__(self, host: DressingHost) -> None:
        self.host = host
        self._press: Gesture | None = None
        self._current: Gesture | None = None
        self._hover: tuple[float, float] | None = None
        self._dragging = False

    def _snapped(self, view: ToolView, point: tuple[float, float]) -> tuple[float, float]:
        grid = view.options.grid
        if grid is not None and grid.snap:
            return snap(point[0], grid.spacing), snap(point[1], grid.spacing)
        return point

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        if document is None or not self._accepts(document):
            return False
        self._press = self._current = gesture
        self._dragging = False
        return True

    def _accepts(self, document: MapDocument) -> bool:
        return document.map.objects_list is not None

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        press = self._press
        if press is None:
            return False
        self._current = gesture
        delta = gesture.screen - press.screen
        if math.hypot(delta.x(), delta.y()) >= DRAG_PIXELS:
            self._dragging = True
        view.update()
        return True

    def hover(self, view: ToolView, gesture: Gesture) -> None:
        self._hover = gesture.world
        view.update()

    def _finish(self) -> tuple[Gesture | None, bool]:
        press, dragging = self._press, self._dragging
        self._press = self._current = None
        self._dragging = False
        return press, dragging

    def cancel(self) -> None:
        self._finish()

    def _select(self, document: MapDocument, items: Sequence[object]) -> None:
        if items and not document.selection.locked:
            document.selection.set(items)


class ScorchTool(_DragTool):
    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, dragging = self._finish()
        document = view.document
        if press is None or document is None:
            return False
        kind, size = self.host.scorch_settings()
        center = self._snapped(view, press.world)
        if dragging:
            size = max(1.0, math.hypot(gesture.world[0] - center[0], gesture.world[1] - center[1]))
        scorch = new_scorch(document.map, center, kind, size, self.host.active_layer())
        self.host.execute(place_objects(document.map, [scorch], "Add Scorchmark"))
        self._select(document, [scorch])
        view.update()
        return True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_FEEDBACK, 1.5, Qt.PenStyle.DashLine))
        press, current = self._press, self._current
        if self._dragging and press is not None and current is not None:
            radius = math.hypot(
                current.world[0] - press.world[0], current.world[1] - press.world[1]
            )
            view.world_circle(painter, *press.world, radius)
        elif self._hover is not None:
            view.world_circle(painter, *self._hover, self.host.scorch_settings()[1])


class GroveTool(_DragTool):
    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, dragging = self._finish()
        document = view.document
        if press is None or document is None:
            return False
        options = self.host.grove_settings()
        rng = np.random.default_rng()
        if pick_tree(options, rng) is None:
            self.host.show_status("Choose tree types and their weights in Dressing Options.")
            return True
        if dragging:
            points = rectangle_points(rng, options.count, press.world, gesture.world)
        else:
            points = cluster_points(rng, options.count, press.world)
        trees = grove_objects(
            document.map, points, options, rng, document.terrain, self.host.active_layer()
        )
        if trees:
            self.host.execute(place_objects(document.map, trees, "Grove"))
            self._select(document, trees)
        view.update()
        return True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        press, current = self._press, self._current
        if not self._dragging or press is None or current is None:
            return
        (x0, y0), (x1, y1) = press.world, current.world
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_FEEDBACK, 1.5, Qt.PenStyle.DashLine))
        view.world_polygon(painter, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


class FenceTool(_DragTool):
    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, dragging = self._finish()
        document = view.document
        if press is None or document is None:
            return False
        template = self.host.place_template()
        if template is None:
            self.host.show_status("Choose the fence object in the Object Palette.")
            return True
        start = self._snapped(view, press.world)
        end = self._snapped(view, gesture.world) if dragging else start
        posts = fence_objects(
            document.map,
            template,
            start,
            end,
            self.host.fence_spacing(),
            self.host.place_owner(),
            stretch=gesture.shift,
            layer=self.host.active_layer(),
        )
        self.host.execute(place_objects(document.map, posts, "Fence"))
        self._select(document, posts)
        view.update()
        return True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        press, current = self._press, self._current
        if not self._dragging or press is None or current is None:
            return
        points, _angle = fence_points(
            press.world, current.world, self.host.fence_spacing(), stretch=current.shift
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_FEEDBACK, 1.5, Qt.PenStyle.DashLine))
        view.world_polygon(painter, [press.world, current.world], closed=False)
        painter.setPen(QPen(_FEEDBACK, 1.5))
        for x, y in points:
            view.world_circle(painter, x, y, 4.0)


class RampTool(_DragTool):
    def _accepts(self, document: MapDocument) -> bool:
        return document.terrain is not None

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, dragging = self._finish()
        document = view.document
        grid = document.terrain if document is not None else None
        if press is None or document is None or grid is None or not dragging:
            return press is not None
        patch = ramp_patch(grid, press.world, gesture.world, self.host.ramp_width())
        if patch is not None:
            command = PatchHeights(patch.x0, patch.y0, patch.values, "Ramp")
            self.host.execute(command)
            command.closed = True
        view.update()
        return True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        press, current = self._press, self._current
        if not self._dragging or press is None or current is None:
            return
        corners = road_corners(press.world, current.world, self.host.ramp_width())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_FEEDBACK, 1.5, Qt.PenStyle.DashLine))
        if corners is not None:
            view.world_polygon(painter, corners)


class BorderTool(_DragTool):
    def __init__(self, host: DressingHost) -> None:
        super().__init__(host)
        self._border: HeightMapBorder | None = None
        self._commands: list[ResizeBorder] = []

    def _accepts(self, document: MapDocument) -> bool:
        return document.map.height_map_data is not None

    def _borders(self, document: MapDocument) -> list[HeightMapBorder]:
        height_map = document.map.height_map_data
        return height_map.borders if height_map is not None else []

    def _size_at(self, document: MapDocument, point: tuple[float, float]) -> tuple[int, int]:
        height_map = document.map.height_map_data
        assert height_map is not None
        width = min(max(1, round(point[0] / WORLD_UNITS_PER_CELL)), height_map.width)
        height = min(max(1, round(point[1] / WORLD_UNITS_PER_CELL)), height_map.height)
        return width, height

    def _handle_at(self, view: ToolView, gesture: Gesture) -> HeightMapBorder | None:
        document = view.document
        if document is None:
            return None
        for border in reversed(self._borders(document)):
            x, y = (value * WORLD_UNITS_PER_CELL for value in border.position)
            sx, sy = view.transform.world_to_screen(x, y)
            if math.hypot(sx - gesture.screen.x(), sy - gesture.screen.y()) <= PICK_PIXELS:
                return border
        return None

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        if not super().press(view, gesture):
            return False
        self._border = self._handle_at(view, gesture)
        self._commands = []
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        if not super().move(view, gesture):
            return False
        document, border = view.document, self._border
        if self._dragging and document is not None and border is not None:
            size = self._size_at(document, gesture.world)
            if size != border.position:
                command = ResizeBorder(border, size)
                self._commands.append(command)
                self.host.execute(command)
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        border = self._border
        press, dragging = self._finish()
        self._border = None
        for command in self._commands:
            command.closed = True
        self._commands = []
        document = view.document
        if press is None or document is None:
            return False
        if border is not None and not dragging and press.alt:
            if len(self._borders(document)) > 1:
                self.host.execute(remove_border(document.map, border))
            else:
                self.host.show_status("The map's last border cannot be removed.")
        elif border is None and not dragging:
            self.host.execute(add_border(document.map, self._size_at(document, press.world)))
        view.update()
        return True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        document = view.document
        if document is None:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_FEEDBACK)
        for border in self._borders(document):
            x, y = (value * WORLD_UNITS_PER_CELL for value in border.position)
            sx, sy = view.transform.world_to_screen(x, y)
            painter.drawRect(QRectF(sx - 4, sy - 4, 8, 8))


class MeshMoldTool(_DragTool):
    def __init__(self, host: DressingHost) -> None:
        super().__init__(host)
        # Where the mold stands, in world units; None until placed.
        self.position: tuple[float, float] | None = None

    def _accepts(self, document: MapDocument) -> bool:
        return document.terrain is not None

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        if not super().press(view, gesture):
            return False
        self.position = self._snapped(view, gesture.world)
        view.update()
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        if not super().move(view, gesture):
            return False
        self.position = self._snapped(view, gesture.world)
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, _dragging = self._finish()
        return press is not None

    def apply(self, document: MapDocument | None) -> bool:
        """Shape the ground under the placed mold; False when there is nothing to apply."""
        grid = document.terrain if document is not None else None
        options = self.host.mold_settings()
        if grid is None or self.position is None:
            self.host.show_status("Click the map to place the mold first.")
            return False
        triangles = self.host.mold_mesh(options.mold) if options.mold else None
        if triangles is None:
            self.host.show_status("Choose a mold in Dressing Options.")
            return False
        patch = mold_patch(grid, triangles, self.position, options)
        if patch is None:
            self.host.show_status("The mold does not change the ground there.")
            return False
        command = PatchHeights(patch.x0, patch.y0, patch.values, "Mesh Mold")
        self.host.execute(command)
        command.closed = True
        return True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        position = self.position
        if position is None:
            return
        options = self.host.mold_settings()
        triangles = self.host.mold_mesh(options.mold) if options.mold else None
        reach = 50.0 * options.scale
        if triangles is not None and len(triangles):
            reach = float(np.hypot(triangles[..., 0], triangles[..., 1]).max()) * options.scale
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_FEEDBACK, 1.5, Qt.PenStyle.DashLine))
        view.world_circle(painter, *position, reach)
        facing = math.radians(options.angle)
        tip = (position[0] + reach * math.cos(facing), position[1] + reach * math.sin(facing))
        painter.setPen(QPen(_FEEDBACK, 1.5))
        view.world_polygon(painter, [position, tip], closed=False)
