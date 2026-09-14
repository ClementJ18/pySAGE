"""The Road tool: WorldBuilder's "Click and Drag to make Roads" (R).

A drag adds one segment of the road type chosen in Road Options, from where the button went down
to where it came up, with the panel's corner type and join flag. An end let go within pick
distance of an existing road end lands exactly on it, so segments join into one road; otherwise
it snaps to the grid when Snap To Grid is on. A click without a drag selects the segment under the
cursor (both of its ends), for Apply To Selection.
"""

from __future__ import annotations

import math
from typing import Protocol

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from sage_worldbuilder.roads import (
    DEFAULT_ROAD_WIDTH,
    CornerType,
    RoadSegment,
    add_road,
    nearest_road_end,
    new_road,
    segment_at,
)
from sage_worldbuilder.ui.overlays import road_corners
from sage_worldbuilder.ui.tools import DRAG_PIXELS, PICK_PIXELS, EditHost, Gesture, Tool, ToolView
from sage_worldbuilder.viewport import snap

__all__ = ["RoadHost", "RoadTool"]

_FEEDBACK = QColor(255, 255, 255, 200)


class RoadHost(EditHost, Protocol):
    def road_type(self) -> tuple[str, bool] | None:
        """The road type chosen in Road Options and whether it is a bridge, or None."""
        ...

    def road_corner(self) -> CornerType: ...

    def road_join(self) -> bool: ...

    def road_width(self, type_name: str) -> float:
        """World units a road type is drawn across."""
        ...


class RoadTool(Tool):
    def __init__(self, host: RoadHost) -> None:
        self.host = host
        self._press: Gesture | None = None
        self._start: tuple[float, float] | None = None
        self._end: tuple[float, float] | None = None
        self._dragging = False

    def _segments(self, view: ToolView) -> list[RoadSegment]:
        scene = view.scene
        if scene is None or not view.options.show_roads:
            return []
        return [s for s in scene.roads if view.is_shown(s.start) and view.is_shown(s.end)]

    def _anchor(self, view: ToolView, point: tuple[float, float]) -> tuple[float, float]:
        radius = PICK_PIXELS / view.transform.scale
        joined = nearest_road_end(self._segments(view), *point, radius)
        if joined is not None:
            return joined
        grid = view.options.grid
        if grid is not None and grid.snap:
            return snap(point[0], grid.spacing), snap(point[1], grid.spacing)
        return point

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        if document is None or document.map.objects_list is None:
            return False
        self._press = gesture
        self._dragging = False
        self._start = self._end = self._anchor(view, gesture.world)
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        press = self._press
        if press is None:
            return False
        delta = gesture.screen - press.screen
        if math.hypot(delta.x(), delta.y()) >= DRAG_PIXELS:
            self._dragging = True
        self._end = self._anchor(view, gesture.world)
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, start, dragging, document = self._press, self._start, self._dragging, view.document
        self.cancel()
        if press is None or start is None or document is None:
            return False
        selection = document.selection
        if not dragging:
            widths = {s.type_name: self.host.road_width(s.type_name) for s in self._segments(view)}
            found = segment_at(
                self._segments(view), *press.world, PICK_PIXELS / view.transform.scale, widths
            )
            if not selection.locked:
                if found is not None:
                    selection.set([found.start, found.end])
                elif not press.shift:
                    selection.clear()
            view.update()
            return True
        end = self._anchor(view, gesture.world)
        chosen = self.host.road_type()
        if chosen is None or end == start:
            view.update()
            return True
        name, bridge = chosen
        segment = new_road(
            document.map,
            name,
            start,
            end,
            bridge=bridge,
            corner=self.host.road_corner(),
            join=self.host.road_join(),
            layer=self.host.active_layer(),
        )
        self.host.execute(add_road(document.map, segment))
        if not selection.locked:
            selection.set([segment.start, segment.end])
        view.update()
        return True

    def cancel(self) -> None:
        self._press = None
        self._start = self._end = None
        self._dragging = False

    def paint(self, view: ToolView, painter: QPainter) -> None:
        start, end = self._start, self._end
        if not self._dragging or start is None or end is None:
            return
        chosen = self.host.road_type()
        width = self.host.road_width(chosen[0]) if chosen is not None else DEFAULT_ROAD_WIDTH
        painter.setPen(QPen(_FEEDBACK, 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        corners = road_corners(start, end, width)
        if corners is not None:
            view.world_polygon(painter, corners)
        view.world_polygon(painter, [start, end], closed=False)
