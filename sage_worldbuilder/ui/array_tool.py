"""The Radial Array tool: repeat an object, or a whole group of them, evenly around a centre.

New, so nothing here follows WorldBuilder; `arrays.py` holds the rules and this is how the mouse
reaches them. A press puts the ring's centre down and the drag out of it says how far the copies
stand from it and which way the first one lies; the ring is drawn under the cursor as it goes, as
the footprint of every copy with a tick for its facing, and the whole ring is selected once the
button comes up, ready for a group edit.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from sage_map.assets.object_list import Object
from sage_worldbuilder.arrays import (
    MIN_RADIUS,
    ArrayOptions,
    aim_delta,
    array_copies,
    array_placements,
    stamp_objects,
)
from sage_worldbuilder.commands.base import Command, CompositeCommand
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.footprints import FootprintShape
from sage_worldbuilder.objects import GroupEditMethod, RotateObjects, new_object, place_objects
from sage_worldbuilder.ui.tools import DRAG_PIXELS, Gesture, PlaceHost, Tool, ToolView
from sage_worldbuilder.viewport import snap

__all__ = ["ArrayHost", "RadialArrayTool"]

_FEEDBACK = QColor(255, 255, 255, 200)
_GHOST = QColor(140, 220, 255, 220)
_EIGHTH = math.pi / 4
# What a ghost is drawn as where the game data gives the object no footprint, and how far its
# facing tick reaches past the footprint it does have.
_GHOST_RADIUS = 6.0
_TICK = 1.6
LABEL = "Radial Array"


class ArrayHost(PlaceHost, Protocol):
    def array_options(self) -> ArrayOptions: ...

    def angle_locked(self) -> bool:
        """Lock Angle: the drag lies only along the eight 45-degree directions."""
        ...

    def show_status(self, text: str) -> None: ...


class RadialArrayTool(Tool):
    """Radial Array: press where the ring's centre goes and drag outwards. Array Options' count
    says how many copies the ring holds and the facing which way each is turned; the copies are
    the Object Palette's object, or, when something is selected and Array Options says to use it,
    the selection - a group keeps its arrangement, so a building and its walls repeat as one.

    A press with a selection and no drag builds the ring through the selection where it already
    stands: those objects keep their place, the rest of the ring joins them at the same distance
    and spacing, and aiming turns them with the copies (Keep the angles leaves every angle alone).
    Lock Angle holds the drag to the eight 45-degree directions; the grid snaps the centre.
    """

    def __init__(self, host: ArrayHost) -> None:
        self.host = host
        self._press: Gesture | None = None
        self._current: Gesture | None = None
        self._dragging = False
        # The selection as it stood at the press, so a change during the drag cannot surprise it.
        self._stamp: list[Object] = []

    def _selection_stamp(self, document: MapDocument) -> list[Object]:
        if not self.host.array_options().use_selection:
            return []
        return stamp_objects(document.selection.items)

    def _snapped(self, view: ToolView, point: tuple[float, float]) -> tuple[float, float]:
        grid = view.options.grid
        if grid is not None and grid.snap:
            return snap(point[0], grid.spacing), snap(point[1], grid.spacing)
        return point

    def _aim(
        self, center: tuple[float, float], gesture: Gesture
    ) -> tuple[tuple[float, float], float]:
        """Where the drag puts the stamp's centre, and how far that is from the ring's centre."""
        dx, dy = gesture.world[0] - center[0], gesture.world[1] - center[1]
        radius = math.hypot(dx, dy)
        if self.host.angle_locked() and radius:
            bearing = round(math.atan2(dy, dx) / _EIGHTH) * _EIGHTH
            dx, dy = radius * math.cos(bearing), radius * math.sin(bearing)
        return (center[0] + dx, center[1] + dy), radius

    def _ring(
        self, view: ToolView, gesture: Gesture
    ) -> tuple[
        tuple[float, float],
        list[tuple[float, float, float]],
        list[str],
        tuple[float, float] | None,
    ]:
        """What the gesture describes: the ring's centre, the stamp as `(x, y, angle)` with a type
        name for each member, and where the stamp moves to, or None when it stays where it is."""
        press = self._press
        assert press is not None
        center = self._snapped(view, press.world)
        if self._stamp:
            stamp = [(x, y, obj.angle) for obj in self._stamp for x, y, _z in (obj.position,)]
            names = [obj.type_name for obj in self._stamp]
            pivot = self._aim(center, gesture)[0] if self._dragging else None
            return center, stamp, names, pivot
        template = self.host.place_template()
        pivot = self._aim(center, gesture)[0]
        return center, [(pivot[0], pivot[1], 0.0)], [template or ""], pivot

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        if document is None or document.map.objects_list is None:
            return False
        stamp = self._selection_stamp(document)
        if not stamp and self.host.place_template() is None:
            self.host.show_status(
                "Choose an object in the Object Palette, or select the objects to repeat."
            )
            return False
        self._press = self._current = gesture
        self._stamp = stamp
        self._dragging = False
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        press = self._press
        if press is None:
            return False
        self._current = gesture
        delta = gesture.screen - press.screen
        if math.hypot(delta.x(), delta.y()) >= DRAG_PIXELS:
            self._dragging = True
        if self._dragging:
            count = self.host.array_options().count
            radius = self._aim(self._snapped(view, press.world), gesture)[1]
            self.host.show_status(
                f"{count} copies of {self._what()}, radius {radius:.0f}, "
                f"{360 / count:.1f} degrees apart"
            )
        view.update()
        return True

    def _what(self) -> str:
        """What the ring repeats, for the status bar."""
        if not self._stamp:
            return self.host.place_template() or "the palette's object"
        if len(self._stamp) == 1:
            return self._stamp[0].type_name
        return f"the selection ({len(self._stamp)} objects)"

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, dragging, stamp = self._press, self._dragging, self._stamp
        document = view.document
        if press is None or document is None:
            self.cancel()
            return False
        center, _points, _names, pivot = self._ring(view, gesture)
        self.cancel()
        options = self.host.array_options()
        if not stamp and not dragging:
            self.host.show_status("Drag outwards from the centre to set the ring's radius.")
            return True
        if pivot is not None and math.dist(pivot, center) < MIN_RADIUS:
            self.host.show_status("Drag further from the centre: the copies would land on it.")
            return True
        if stamp:
            command, placed = self._from_selection(document, stamp, center, options, pivot)
        else:
            assert pivot is not None
            command, placed = self._from_palette(document, center, options, pivot)
        if command is None:
            return True
        self.host.execute(command)
        if not document.selection.locked:
            document.selection.set(placed)
        view.update()
        return True

    def _from_palette(
        self,
        document: MapDocument,
        center: tuple[float, float],
        options: ArrayOptions,
        pivot: tuple[float, float],
    ) -> tuple[Command | None, list[Object]]:
        """A ring of the Object Palette's object, its first copy where the drag ended."""
        template = self.host.place_template()
        if template is None:
            return None, []
        source = new_object(
            document.map,
            template,
            (pivot[0], pivot[1], self.host.place_height()),
            0.0,
            self.host.place_owner(),
            self.host.active_layer(),
        )
        copies = array_copies(document.map, [source], center, options)
        return place_objects(document.map, copies, LABEL), copies

    def _from_selection(
        self,
        document: MapDocument,
        stamp: Sequence[Object],
        center: tuple[float, float],
        options: ArrayOptions,
        pivot: tuple[float, float] | None,
    ) -> tuple[Command | None, list[Object]]:
        """A ring of the selection: copied to where the drag ended, or, with no drag, built
        through the selection where it stands, which the aiming turns with the copies."""
        map = document.map
        if pivot is not None:
            copies = array_copies(map, stamp, center, options, pivot=pivot)
            return place_objects(map, copies, LABEL), copies
        points = [(x, y, obj.angle) for obj in stamp for x, y, _z in (obj.position,)]
        at = (
            sum(x for x, _y, _angle in points) / len(points),
            sum(y for _x, y, _angle in points) / len(points),
        )
        if math.dist(at, center) < MIN_RADIUS:
            self.host.show_status("Press further from the selection: the copies would land on it.")
            return None, []
        copies = array_copies(map, stamp, center, options, keep_first=True)
        delta = aim_delta(points, center, options)
        commands: list[Command] = []
        if delta:
            commands.append(RotateObjects(stamp, delta, GroupEditMethod.INDEPENDENT, LABEL))
        commands.append(place_objects(map, copies, LABEL))
        return CompositeCommand(LABEL, commands), [*stamp, *copies]

    def cancel(self) -> None:
        self._press = self._current = None
        self._dragging = False
        self._stamp = []

    def paint(self, view: ToolView, painter: QPainter) -> None:
        press, current = self._press, self._current
        if press is None or current is None or (not self._stamp and not self._dragging):
            return
        center, points, names, pivot = self._ring(view, current)
        keep_first = bool(self._stamp) and pivot is None
        at = (
            pivot
            if pivot is not None
            else (
                sum(x for x, _y, _angle in points) / len(points),
                sum(y for _x, y, _angle in points) / len(points),
            )
        )
        options = self.host.array_options()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_FEEDBACK, 1.5, Qt.PenStyle.DashLine))
        view.world_circle(painter, center[0], center[1], math.dist(at, center))
        view.world_polygon(painter, [center, at], closed=False)
        painter.setPen(QPen(_GHOST, 1.5))
        for placed in array_placements(points, center, options, pivot=pivot, keep_first=keep_first):
            for name, (x, y, angle) in zip(names, placed, strict=True):
                self._ghost(view, painter, name, x, y, angle)

    def _ghost(
        self, view: ToolView, painter: QPainter, name: str, x: float, y: float, angle: float
    ) -> None:
        """One copy where it would land: what it covers, and a tick for the way it faces."""
        footprint = view.footprints.get(name) if view.footprints is not None else None
        reach = footprint.major if footprint is not None else _GHOST_RADIUS
        if footprint is None or footprint.shape is FootprintShape.CIRCLE:
            view.world_circle(painter, x, y, reach)
        else:
            cos, sin = math.cos(angle), math.sin(angle)
            view.world_polygon(
                painter,
                [
                    (
                        x + along * footprint.major * cos - across * footprint.minor * sin,
                        y + along * footprint.major * sin + across * footprint.minor * cos,
                    )
                    for along, across in ((1, 1), (1, -1), (-1, -1), (-1, 1))
                ],
            )
        tip = (x + reach * _TICK * math.cos(angle), y + reach * _TICK * math.sin(angle))
        view.world_polygon(painter, [(x, y), tip], closed=False)
