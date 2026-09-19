"""The water tools: WorldBuilder's Lake/Ocean Tool (32986), River Tool (33441) and Waves Tool
(33489).

Each tool edits only its own kind of area, as WorldBuilder's do, and the area it selects is the
one Water Options shows.

- Every tool: click inside an area (on a wave area's line) to select it, drag it to move it, and
  drag one of the selected area's points to move that point.
- Lake/Ocean: click on open ground to start an outline, click to add corners, and click the first
  corner again (with three or more) to close the new lake.
- River: drag across the river, from its left bank to its right, to add a bank line to the
  selected river, or to start a new river when none is selected. A click on open ground ends the
  river being drawn.
- Waves: drag on open ground from where a wave area starts to where it ends.

A new area stands at the height of the lowest ground under its points (the host's
`water_height`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import Enum
from typing import Protocol

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from sage_map.assets.river_areas import RiverArea
from sage_worldbuilder.areas import MoveAreaPoint
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.scene import AreaOutline
from sage_worldbuilder.ui.tools import DRAG_PIXELS, PICK_PIXELS, EditHost, Gesture, Tool, ToolView
from sage_worldbuilder.viewport import snap
from sage_worldbuilder.water import (
    MoveRiverPoint,
    MoveWater,
    WaterArea,
    WaterKind,
    add_river_line,
    add_water,
    move_handle,
    new_lake,
    new_river,
    new_wave,
    water_areas,
    water_handles,
    water_kind,
)

__all__ = ["WaterHost", "WaterTool"]

_FEEDBACK = QColor(255, 255, 255, 200)
Handle = tuple[int, int | None]


class WaterHost(EditHost, Protocol):
    def water_height(self, points: Sequence[tuple[float, float]]) -> int:
        """The height a new area over these points stands at, in feet."""
        ...


class _Mode(Enum):
    IDLE = "idle"
    AREA = "area"
    HANDLE = "handle"
    EMPTY = "empty"


class WaterTool(Tool):
    def __init__(self, host: WaterHost, kind: WaterKind) -> None:
        self.host = host
        self.kind = kind
        # The lake outline being clicked out.
        self.points: list[tuple[float, float]] = []
        self._mode = _Mode.IDLE
        self._press: Gesture | None = None
        self._current: Gesture | None = None
        self._dragging = False
        self._area: WaterArea | None = None
        self._handle: Handle | None = None
        self._commands: list[MoveWater | MoveAreaPoint | MoveRiverPoint] = []
        self._moved = (0.0, 0.0)

    def _selected(self, document: MapDocument) -> WaterArea | None:
        found = [item for item in document.selection if water_kind(item) is self.kind]
        return found[0] if len(found) == 1 else None  # type: ignore[return-value]

    def _accept(self, view: ToolView) -> object:
        def accept(outline: AreaOutline) -> bool:
            return water_kind(outline.source) is self.kind and view.is_shown(outline.source)

        return accept

    def _handle_at(self, view: ToolView, area: WaterArea, gesture: Gesture) -> Handle | None:
        for handle, (x, y) in water_handles(area):
            sx, sy = view.transform.world_to_screen(x, y)
            if math.hypot(sx - gesture.screen.x(), sy - gesture.screen.y()) <= PICK_PIXELS:
                return handle
        return None

    def _snapped(self, view: ToolView, point: tuple[float, float]) -> tuple[float, float]:
        grid = view.options.grid
        if grid is not None and grid.snap:
            return snap(point[0], grid.spacing), snap(point[1], grid.spacing)
        return point

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document, scene = view.document, view.scene
        if document is None or scene is None or water_areas(document.map, self.kind) is None:
            return False
        self._press = self._current = gesture
        self._dragging = False
        self._commands = []
        self._moved = (0.0, 0.0)
        self._area, self._handle = None, None
        if not view.options.show_water:
            self._mode = _Mode.EMPTY
            return True
        selected = self._selected(document)
        if selected is not None and not self.points:
            handle = self._handle_at(view, selected, gesture)
            if handle is not None:
                self._mode, self._area, self._handle = _Mode.HANDLE, selected, handle
                return True
        outline = None
        if not self.points:
            outline = scene.water_at(
                *gesture.world, PICK_PIXELS / view.transform.scale, self._accept(view)
            )
        if outline is not None:
            self._mode, self._area = _Mode.AREA, outline.source  # type: ignore[assignment]
        else:
            self._mode = _Mode.EMPTY
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        press, document = self._press, view.document
        if press is None or document is None:
            if self.points:
                self.hover(view, gesture)
            return False
        self._current = gesture
        delta = gesture.screen - press.screen
        if math.hypot(delta.x(), delta.y()) >= DRAG_PIXELS:
            self._dragging = True
        if self._dragging and self._mode is _Mode.HANDLE and self._area is not None:
            assert self._handle is not None
            self._issue(move_handle(self._area, self._handle, self._snapped(view, gesture.world)))
        elif self._dragging and self._mode is _Mode.AREA and self._area is not None:
            if self._area not in document.selection and not document.selection.locked:
                document.selection.set([self._area])
            dx = gesture.world[0] - press.world[0]
            dy = gesture.world[1] - press.world[1]
            step = (dx - self._moved[0], dy - self._moved[1])
            if step != (0.0, 0.0):
                self._moved = (dx, dy)
                self._issue(MoveWater([self._area], *step))
        view.update()
        return True

    def hover(self, view: ToolView, gesture: Gesture) -> None:
        self._current = gesture
        if self.points:
            view.update()

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, document, mode, dragging = self._press, view.document, self._mode, self._dragging
        area = self._area
        for command in self._commands:
            command.closed = True
        self._commands = []
        self._press = None
        self._mode = _Mode.IDLE
        self._dragging = False
        if press is None or document is None:
            return False
        selection = document.selection
        if mode is _Mode.AREA and not dragging and not selection.locked:
            selection.set([area])
        elif mode is _Mode.EMPTY:
            if self.kind is WaterKind.LAKE:
                self._lake_click(view, document, gesture)
            elif self.kind is WaterKind.RIVER:
                self._river_gesture(view, document, press, gesture, dragging)
            elif dragging:
                self._add_wave(view, document, press, gesture)
            elif not selection.locked:
                selection.clear()
        view.update()
        return True

    def _lake_click(self, view: ToolView, document: MapDocument, gesture: Gesture) -> None:
        if len(self.points) >= 3:
            sx, sy = view.transform.world_to_screen(*self.points[0])
            if math.hypot(sx - gesture.screen.x(), sy - gesture.screen.y()) <= PICK_PIXELS:
                points, self.points = self.points, []
                lake = new_lake(
                    document.map, points, self.host.water_height(points), self.host.active_layer()
                )
                self.host.execute(add_water(document.map, lake))
                if not document.selection.locked:
                    document.selection.set([lake])
                return
        if not self.points and not document.selection.locked:
            document.selection.clear()
        self.points.append(self._snapped(view, gesture.world))

    def _river_gesture(
        self,
        view: ToolView,
        document: MapDocument,
        press: Gesture,
        gesture: Gesture,
        dragging: bool,
    ) -> None:
        selection = document.selection
        if not dragging:
            if not selection.locked:
                selection.clear()
            return
        line = (self._snapped(view, press.world), self._snapped(view, gesture.world))
        river = self._selected(document)
        if isinstance(river, RiverArea):
            self.host.execute(add_river_line(river, line))
            return
        created = new_river(
            document.map, [line], self.host.water_height(line), self.host.active_layer()
        )
        self.host.execute(add_water(document.map, created))
        if not selection.locked:
            selection.set([created])

    def _add_wave(
        self, view: ToolView, document: MapDocument, press: Gesture, gesture: Gesture
    ) -> None:
        points = [self._snapped(view, press.world), self._snapped(view, gesture.world)]
        wave = new_wave(document.map, points, self.host.active_layer())
        self.host.execute(add_water(document.map, wave))
        if not document.selection.locked:
            document.selection.set([wave])

    def _issue(self, command: MoveWater | MoveAreaPoint | MoveRiverPoint) -> None:
        self._commands.append(command)
        self.host.execute(command)

    def cancel(self) -> None:
        self.points = []
        self._press = None
        self._mode = _Mode.IDLE
        self._dragging = False

    def paint(self, view: ToolView, painter: QPainter) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.points:
            painter.setPen(QPen(_FEEDBACK, 1.5))
            view.world_polygon(painter, self.points, closed=False)
            screen = [QPointF(*view.transform.world_to_screen(x, y)) for x, y in self.points]
            if self._current is not None:
                painter.setPen(QPen(_FEEDBACK, 1, Qt.PenStyle.DashLine))
                painter.drawLine(screen[-1], self._current.screen)
            painter.setPen(QPen(_FEEDBACK, 1.5))
            for index, point in enumerate(screen):
                size = 6.0 if index == 0 else 4.0
                painter.drawRect(QRectF(point.x() - size / 2, point.y() - size / 2, size, size))
            return
        press, current = self._press, self._current
        if (
            self._mode is _Mode.EMPTY
            and self._dragging
            and press is not None
            and current is not None
        ):
            painter.setPen(QPen(_FEEDBACK, 1.5, Qt.PenStyle.DashLine))
            view.world_polygon(painter, [press.world, current.world], closed=False)
