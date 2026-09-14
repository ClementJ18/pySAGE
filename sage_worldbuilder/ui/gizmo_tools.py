"""The Move and Rotate tools: a gizmo on the selection, and a drag on one of its handles.

New, not WorldBuilder; `gizmos.py` holds the rules. Both tools are Select and Move with a gizmo
over it - a press that misses the gizmo selects, marquees, drags and reshapes exactly as that tool
does, so nothing is lost by working in one of them.

- **Move** draws an arrow per axis out of the selection's centre, X and Y along the ground and Z
  up the screen, and a knob at the centre for a free drag. A drag on an arrow moves along that
  axis alone; X, Y and Z switch the axis in the middle of the drag, and the key of the axis in
  use lets the move go free again, as Blender's do.
- **Rotate** draws the one ring an object can turn about: the map stores a single angle, its
  heading, so there is no pitch or roll to give X and Y rings of their own. A drag on the ring
  turns the selection by the Group Edit Method, and Lock Angle holds the turned object to the
  eight 45-degree headings.

Each drag is one undo entry, and the status bar reads out how far it has gone.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF

from sage_map.assets.object_list import Object
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.gizmos import (
    GIZMO_PIXELS,
    LOCKED_STEP_DEGREES,
    MOVE_AXES,
    Axis,
    axis_tip,
    constrained,
    point_to_segment,
    reach,
    snapped_angle,
)
from sage_worldbuilder.objects import MoveObjects, RotateObjects
from sage_worldbuilder.ui.overlays import arrow_head
from sage_worldbuilder.ui.tools import (
    PICK_PIXELS,
    Gesture,
    SelectTool,
    Tool,
    ToolHost,
    ToolView,
    selected_areas,
    selected_objects,
)
from sage_worldbuilder.viewport import snap

__all__ = ["GizmoHost", "MoveTool", "RotateTool"]

_AXIS_COLORS = {
    Axis.X: QColor(235, 90, 90),
    Axis.Y: QColor(120, 215, 120),
    Axis.Z: QColor(110, 160, 255),
}
# The axis being dragged, or the one under the cursor.
_HOT = QColor(255, 220, 90)
_CENTER = QColor(235, 235, 235)
_KEYS = {Qt.Key.Key_X.value: Axis.X, Qt.Key.Key_Y.value: Axis.Y, Qt.Key.Key_Z.value: Axis.Z}


class GizmoHost(ToolHost, Protocol):
    def show_status(self, text: str) -> None: ...


def _center(document: MapDocument) -> tuple[float, float] | None:
    """Where the gizmo sits: the middle of the selected objects, or of the selected areas when
    only areas are selected. None when nothing is selected."""
    objects = selected_objects(document)
    if objects:
        return (
            sum(obj.position[0] for obj in objects) / len(objects),
            sum(obj.position[1] for obj in objects) / len(objects),
        )
    points = [point for area in selected_areas(document) for point in area.points]
    if not points:
        return None
    return (
        sum(x for x, _y in points) / len(points),
        sum(y for _x, y in points) / len(points),
    )


class _GizmoTool(Tool):
    """Select and Move with a gizmo drawn on the selection; a press that misses the gizmo goes
    through to the selecting tool underneath."""

    def __init__(self, host: GizmoHost) -> None:
        self.host = host
        self.select = SelectTool(host)
        self._press: Gesture | None = None
        # The axis being dragged, and the one the cursor is over.
        self._axis: Axis | None = None
        self._hot: Axis | None = None
        self._commands: list[MoveObjects | RotateObjects] = []

    def _grab(self, view: ToolView, center: tuple[float, float], gesture: Gesture) -> Axis | None:
        """The gizmo handle under a press, or None."""
        raise NotImplementedError

    def _drag(self, view: ToolView, document: MapDocument, gesture: Gesture) -> None:
        raise NotImplementedError

    def _draw(
        self, view: ToolView, painter: QPainter, center: tuple[float, float], scale: float
    ) -> None:
        raise NotImplementedError

    def _start(self, document: MapDocument, center: tuple[float, float], gesture: Gesture) -> None:
        """Set up whatever the drag needs to track, once a handle is grabbed."""
        return None

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        self._commands = []
        center = _center(document) if document is not None else None
        if document is not None and center is not None and not gesture.alt:
            axis = self._grab(view, center, gesture)
            if axis is not None:
                self._press = gesture
                self._axis = axis
                self._start(document, center, gesture)
                return True
        self._press = None
        self._axis = None
        return self.select.press(view, gesture)

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        if self._press is None or document is None:
            return self.select.move(view, gesture)
        self._drag(view, document, gesture)
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        for command in self._commands:
            command.closed = True
        self._commands = []
        if self._press is None:
            return self.select.release(view, gesture)
        self._press = None
        self._axis = None
        view.update()
        return True

    def hover(self, view: ToolView, gesture: Gesture) -> None:
        document = view.document
        center = _center(document) if document is not None else None
        hot = self._grab(view, center, gesture) if center is not None else None
        if hot is not self._hot:
            self._hot = hot
            view.update()

    def cancel(self) -> None:
        self._press = None
        self._axis = None
        self._hot = None
        self._commands = []
        self.select.cancel()

    def paint(self, view: ToolView, painter: QPainter) -> None:
        self.select.paint(view, painter)
        document = view.document
        center = _center(document) if document is not None else None
        if center is None:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        self._draw(view, painter, center, view.transform.scale)

    def _color(self, axis: Axis) -> QColor:
        live = self._axis if self._press is not None else self._hot
        return _HOT if axis is live else _AXIS_COLORS.get(axis, _CENTER)

    def _issue(self, command: MoveObjects | RotateObjects) -> None:
        self._commands.append(command)
        self.host.execute(command)


class MoveTool(_GizmoTool):
    """Move Tool: drag an axis arrow to move the selection along that axis alone, or the knob at
    the centre to move it freely on the ground. X, Y and Z switch the axis during the drag, and
    the axis in use switches back to a free move. Snap To Grid snaps the first selected object,
    and the Z arrow raises and lowers, as Lock Vertical does."""

    def __init__(self, host: GizmoHost) -> None:
        super().__init__(host)
        # How far the drag has moved the selection so far, so each step is the difference.
        self._moved = (0.0, 0.0, 0.0)
        # Where the gizmo stood when the drag began, which fixes the height arrow's direction.
        self._center_at = (0.0, 0.0)

    def _segment(
        self, view: ToolView, center: tuple[float, float], axis: Axis, scale: float
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """An arrow's shaft in pixels. Z has no direction on the ground, so it follows the view's
        own answer for which way height goes on screen."""
        start = view.transform.world_to_screen(*center)
        if axis is Axis.Z:
            ux, uy = view.transform.height_direction(*center)
            return start, (start[0] + ux * GIZMO_PIXELS, start[1] + uy * GIZMO_PIXELS)
        return start, view.transform.world_to_screen(*axis_tip(center, axis, scale))

    def _grab(self, view: ToolView, center: tuple[float, float], gesture: Gesture) -> Axis | None:
        point = (gesture.screen.x(), gesture.screen.y())
        scale = view.transform.scale
        start = view.transform.world_to_screen(*center)
        if math.dist(point, start) <= PICK_PIXELS:
            return Axis.GROUND
        for axis in MOVE_AXES:
            tail, tip = self._segment(view, center, axis, scale)
            if point_to_segment(point, tail, tip) <= PICK_PIXELS:
                return axis
        return None

    def _start(self, document: MapDocument, center: tuple[float, float], gesture: Gesture) -> None:
        self._moved = (0.0, 0.0, 0.0)
        self._center_at = center

    def key(self, view: ToolView, key: int) -> bool:
        axis = _KEYS.get(key)
        if self._press is None or axis is None:
            return False
        # The axis already in use frees the move again, the way Blender's second press does.
        self._axis = Axis.GROUND if axis is self._axis else axis
        view.update()
        return True

    def _drag(self, view: ToolView, document: MapDocument, gesture: Gesture) -> None:
        press = self._press
        assert press is not None
        objects, areas = selected_objects(document), selected_areas(document)
        if not objects and not areas:
            return
        dx = gesture.world[0] - press.world[0]
        dy = gesture.world[1] - press.world[1]
        # A drag along the height arrow raises, by the world units it spans at the ground's depth.
        ux, uy = view.transform.height_direction(*self._center_at)
        along = (gesture.screen.x() - press.screen.x()) * ux
        along += (gesture.screen.y() - press.screen.y()) * uy
        dz = along / view.transform.scale
        dx, dy, dz = constrained((dx, dy, dz), self._axis)
        dx, dy = self._snapped(view, objects, dx, dy)
        step = (dx - self._moved[0], dy - self._moved[1], dz - self._moved[2])
        if step == (0.0, 0.0, 0.0):
            return
        self._moved = (dx, dy, dz)
        self._issue(MoveObjects(objects, step[0], step[1], areas=areas, dz=step[2]))
        self._show(dx, dy, dz)

    def _snapped(
        self, view: ToolView, objects: Sequence[Object], dx: float, dy: float
    ) -> tuple[float, float]:
        """Snap To Grid, on the first selected object; the rest keep their offsets from it."""
        grid = view.options.grid
        if grid is None or not grid.snap or not objects:
            return dx, dy
        lead = objects[0]
        for index, delta in enumerate((dx, dy)):
            if delta:
                start = lead.position[index] - self._moved[index]
                moved = snap(start + delta, grid.spacing) - start
                dx, dy = (moved, dy) if index == 0 else (dx, moved)
        return dx, dy

    def _show(self, dx: float, dy: float, dz: float) -> None:
        axis = self._axis
        if axis is Axis.Z:
            self.host.show_status(f"Move Z: {dz:+.1f}")
        elif axis is Axis.X:
            self.host.show_status(f"Move X: {dx:+.1f}")
        elif axis is Axis.Y:
            self.host.show_status(f"Move Y: {dy:+.1f}")
        else:
            self.host.show_status(f"Move: {dx:+.1f}, {dy:+.1f}")

    def _draw(
        self, view: ToolView, painter: QPainter, center: tuple[float, float], scale: float
    ) -> None:
        for axis in MOVE_AXES:
            tail, tip = self._segment(view, center, axis, scale)
            color = self._color(axis)
            painter.setPen(QPen(color, 2.0))
            painter.setBrush(QBrush(color))
            painter.drawLine(QPointF(*tail), QPointF(*tip))
            head = arrow_head(tail, tip)
            if head is not None:
                painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in head]))
        knob = self._color(Axis.GROUND)
        painter.setPen(QPen(knob, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(*view.transform.world_to_screen(*center)), 5.0, 5.0)


class RotateTool(_GizmoTool):
    """Rotate Tool: drag the ring around the selection to turn it by the Group Edit Method. The
    ring is the one axis the map has - an object stores a heading, not a pitch or a roll - and
    Lock Angle holds the object being turned to the eight 45-degree headings."""

    def __init__(self, host: GizmoHost) -> None:
        super().__init__(host)
        self._center = (0.0, 0.0)
        # The bearing the cursor was last at, how far it has gone since the press, and how much of
        # that has been applied, so a snapped turn only issues whole steps.
        self._bearing = 0.0
        self._turned = 0.0
        self._applied = 0.0
        self._lead_angle = 0.0

    def _bearing_to(self, center: tuple[float, float], point: tuple[float, float]) -> float:
        return math.atan2(point[1] - center[1], point[0] - center[0])

    def _grab(self, view: ToolView, center: tuple[float, float], gesture: Gesture) -> Axis | None:
        start = view.transform.world_to_screen(*center)
        away = math.dist((gesture.screen.x(), gesture.screen.y()), start)
        return Axis.Z if abs(away - GIZMO_PIXELS) <= PICK_PIXELS else None

    def _start(self, document: MapDocument, center: tuple[float, float], gesture: Gesture) -> None:
        objects = selected_objects(document)
        self._center = center
        self._bearing = self._bearing_to(center, gesture.world)
        self._turned = self._applied = 0.0
        self._lead_angle = objects[0].angle if objects else 0.0

    def _drag(self, view: ToolView, document: MapDocument, gesture: Gesture) -> None:
        objects = selected_objects(document)
        if not objects:
            return
        bearing = self._bearing_to(self._center, gesture.world)
        self._turned += math.remainder(bearing - self._bearing, math.tau)
        self._bearing = bearing
        wanted = self._turned
        if self.host.angle_locked():
            wanted = (
                snapped_angle(self._lead_angle + wanted, LOCKED_STEP_DEGREES) - self._lead_angle
            )
        delta = wanted - self._applied
        if delta:
            self._applied = wanted
            self._issue(RotateObjects(objects, delta, self.host.group_edit_method()))
        self.host.show_status(f"Rotate: {math.degrees(self._applied):+.1f} degrees")

    def _draw(
        self, view: ToolView, painter: QPainter, center: tuple[float, float], scale: float
    ) -> None:
        color = self._color(Axis.Z)
        painter.setPen(QPen(color, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        view.world_circle(painter, center[0], center[1], reach(GIZMO_PIXELS, scale))
        document = view.document
        objects = selected_objects(document) if document is not None else []
        if not objects:
            return
        # The knob sits where the first selected object faces, so the ring reads as its handle.
        angle = objects[0].angle
        out = reach(GIZMO_PIXELS, scale)
        knob = view.transform.world_to_screen(
            center[0] + out * math.cos(angle), center[1] + out * math.sin(angle)
        )
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(*knob), 4.0, 4.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
