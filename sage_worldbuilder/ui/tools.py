"""The map view's tools: what a left-button gesture in the view does.

A tool receives world positions, so it works the same whatever draws the map. It issues edits
through its host as commands, and changes the document's selection directly (selecting is not an
edit). One gesture is one undo entry: the tool closes its commands when the button comes up, so
the next drag does not merge into them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from sage_map.assets.object_list import Object
from sage_map.assets.sides_list import BuildListInfo
from sage_map.assets.trigger_areas import TriggerArea
from sage_worldbuilder.areas import MoveAreaPoint, add_area, new_area
from sage_worldbuilder.build_lists import (
    MoveBuilding,
    add_entry,
    build_list_entries,
    new_entry,
    side_names,
)
from sage_worldbuilder.commands import Command
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.generic_ai import PICK_DISTANCES, GenericAIType, new_generic_ai_object
from sage_worldbuilder.gizmos import HANDLE_PIXELS, front_tip
from sage_worldbuilder.objects import (
    GroupEditMethod,
    MoveObjects,
    RotateObjects,
    new_object,
    place_objects,
)
from sage_worldbuilder.pick import PickRules
from sage_worldbuilder.scene import MapScene, Marker, MarkerKind
from sage_worldbuilder.terrain.grid import WORLD_UNITS_PER_CELL
from sage_worldbuilder.ui.overlays import draw_label
from sage_worldbuilder.viewport import ViewOptions, ViewTransform, snap
from sage_worldbuilder.waypoints import (
    add_linked_waypoint,
    new_waypoint,
    toggle_link,
    waypoint_id,
)

if TYPE_CHECKING:
    from sage_worldbuilder.footprints import Footprints

__all__ = [
    "BuildListHost",
    "BuildListTool",
    "EditHost",
    "GenericAIHost",
    "GenericAIObjectTool",
    "Gesture",
    "PlaceHost",
    "PlaceTool",
    "PolygonTool",
    "RulerHost",
    "RulerTool",
    "SelectTool",
    "Tool",
    "ToolHost",
    "WaypointTool",
    "selected_areas",
    "selected_objects",
]

# How close, in pixels, a click must land to pick a marker or a corner.
PICK_PIXELS = 8.0
# How far, in pixels, the mouse must travel before a press becomes a drag.
DRAG_PIXELS = 3.0
_MARQUEE = QColor(255, 255, 255, 200)
_EIGHTH = math.pi / 4
_WAYPOINTS = frozenset({MarkerKind.WAYPOINT})
_GENERIC_AI = frozenset({MarkerKind.GENERIC_AI})


class EditHost(Protocol):
    def execute(self, command: Command) -> None: ...

    def active_layer(self) -> str:
        """The layer new objects, waypoints and trigger areas go on."""
        ...


class RulerHost(Protocol):
    def ruler_circular(self) -> bool:
        """Circular Measurements: show the measured distance as a circle's radius."""
        ...

    def show_measurement(self, text: str) -> None: ...


class ToolHost(EditHost, Protocol):
    def pick_rules(self) -> PickRules: ...

    def group_edit_method(self) -> GroupEditMethod: ...

    def angle_locked(self) -> bool:
        """Lock Angle: moves go only along the eight 45-degree directions."""
        ...

    def vertical_locked(self) -> bool:
        """Lock Vertical: a drag moves the selected objects only up and down."""
        ...


class PlaceHost(EditHost, Protocol):
    def place_template(self) -> str | None:
        """The object chosen in the palette, or None."""
        ...

    def place_owner(self) -> str:
        """The team a placed object belongs to (`<player>/<team>`)."""
        ...

    def place_height(self) -> float:
        """The placed object's height above the terrain."""
        ...


@dataclass(frozen=True)
class Gesture:
    """One mouse event, as a tool sees it."""

    world: tuple[float, float]
    screen: QPointF
    shift: bool = False
    alt: bool = False
    # The right button, for a tool that takes right-button drags.
    right: bool = False


class ToolView(Protocol):
    @property
    def document(self) -> MapDocument | None: ...

    @property
    def scene(self) -> MapScene | None: ...

    @property
    def transform(self) -> ViewTransform: ...

    @property
    def options(self) -> ViewOptions: ...

    @property
    def footprints(self) -> Footprints | None:
        """The ground objects cover, from the game data; None until a game has loaded."""
        ...

    def update(self) -> None: ...

    def is_shown(self, source: object) -> bool:
        """Whether a map item is drawn; a hidden one cannot be picked."""
        ...

    def world_circle(self, painter: QPainter, x: float, y: float, radius: float) -> None:
        """A circle of `radius` world units on the ground about a world position."""
        ...

    def world_polygon(
        self, painter: QPainter, points: Sequence[tuple[float, float]], closed: bool = True
    ) -> None:
        """A world outline on the ground: a polygon, or a line through the points."""
        ...


class Tool:
    """Does nothing; the base of every tool."""

    # Whether the map view hands the tool right-button presses and drags as well.
    right_button = False

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        return False

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        return False

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        return False

    def hover(self, view: ToolView, gesture: Gesture) -> None:
        """The mouse moved with no button down."""
        return None

    def key(self, view: ToolView, key: int) -> bool:
        """A key pressed over the map view, before the window's own shortcuts see it; True when
        the tool took it (the gizmo tools take X, Y and Z during a drag)."""
        return False

    def cancel(self) -> None:
        """Drop anything half-made, as when another tool is chosen."""
        return None

    def paint(self, view: ToolView, painter: QPainter) -> None:
        return None


def _travelled(press: Gesture, gesture: Gesture) -> float:
    delta = gesture.screen - press.screen
    return math.hypot(delta.x(), delta.y())


def _marker_shown(view: ToolView, marker: Marker) -> bool:
    """Whether a marker is drawn: its kind is on in the View menu and the item itself is shown."""
    return view.options.shows(marker.kind) and view.is_shown(marker.source)


def _snapped(view: ToolView, point: tuple[float, float]) -> tuple[float, float]:
    grid = view.options.grid
    if grid is not None and grid.snap:
        return snap(point[0], grid.spacing), snap(point[1], grid.spacing)
    return point


class _Mode(Enum):
    IDLE = "idle"
    PRESSED = "pressed"
    MOVE = "move"
    MARQUEE = "marquee"
    ROTATE = "rotate"
    CORNER = "corner"


class SelectTool(Tool):
    """Select and Move: click to select an object, or a trigger area by clicking inside it;
    Shift-click adds or removes; drag an empty spot for a marquee; drag an object or area to move
    the selection (snapping the dragged object to the grid when Snap To Grid is on); drag a corner
    of a selected area to reshape it; drag the handle out of a selected object's ring to turn it,
    or Alt-drag to rotate the selected objects about their centre."""

    def __init__(self, host: ToolHost) -> None:
        self.host = host
        self._mode = _Mode.IDLE
        self._press: Gesture | None = None
        self._current: Gesture | None = None
        self._picked: object | None = None
        self._corner: tuple[TriggerArea, int] | None = None
        self._commands: list[MoveObjects | RotateObjects | MoveAreaPoint] = []
        self._moved = (0.0, 0.0)
        # How far the drag has raised the selection, with Lock Vertical on.
        self._lifted = 0.0
        self._angle = 0.0
        self._center = (0.0, 0.0)

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document, scene = view.document, view.scene
        if document is None or scene is None:
            return False
        self._press = self._current = gesture
        self._moved = (0.0, 0.0)
        self._lifted = 0.0
        self._commands = []
        selected = selected_objects(document)
        if gesture.alt and selected:
            self._mode = _Mode.ROTATE
            self._center = (
                sum(obj.position[0] for obj in selected) / len(selected),
                sum(obj.position[1] for obj in selected) / len(selected),
            )
            self._angle = _bearing(self._center, gesture.world)
            return True
        grabbed = self._handle_at(view, document, gesture)
        if grabbed is not None:
            self._mode = _Mode.ROTATE
            self._center = (grabbed.x, grabbed.y)
            self._angle = _bearing(self._center, gesture.world)
            return True
        self._corner = self._corner_at(view, document, gesture)
        if self._corner is not None:
            self._mode = _Mode.CORNER
            return True
        self._picked = self._pick(view, scene, gesture.world)
        self._mode = _Mode.PRESSED
        return True

    def _pick(self, view: ToolView, scene: MapScene, point: tuple[float, float]) -> object | None:
        rules = self.host.pick_rules()
        marker = scene.nearest(
            *point,
            PICK_PIXELS / view.transform.scale,
            accept=lambda marker: rules.allows(marker) and _marker_shown(view, marker),
        )
        if marker is not None:
            return marker.source
        if not rules.allows_areas() or not view.options.show_areas:
            return None
        area = scene.area_at(*point, accept=lambda outline: view.is_shown(outline.source))
        return area.source if area is not None else None

    def _handle_at(self, view: ToolView, document: MapDocument, gesture: Gesture) -> Marker | None:
        """The selected object whose front handle the press landed on, so the drag turns it."""
        scene, selection = view.scene, document.selection
        if scene is None or not selection:
            return None
        scale = view.transform.scale
        margin = (HANDLE_PIXELS + PICK_PIXELS) / scale
        x, y = gesture.world
        for marker in scene.in_rect(x - margin, y - margin, x + margin, y + margin):
            if marker.kind is not MarkerKind.OBJECT or marker.source not in selection:
                continue
            if not _marker_shown(view, marker):
                continue
            out = front_tip(marker.x, marker.y, marker.angle, scale)
            tip = view.transform.world_to_screen(*out)
            if math.hypot(tip[0] - gesture.screen.x(), tip[1] - gesture.screen.y()) <= PICK_PIXELS:
                return marker
        return None

    def _corner_at(
        self, view: ToolView, document: MapDocument, gesture: Gesture
    ) -> tuple[TriggerArea, int] | None:
        if not view.options.show_areas:
            return None
        for area in selected_areas(document):
            if not view.is_shown(area):
                continue
            for index, (x, y) in enumerate(area.points):
                sx, sy = view.transform.world_to_screen(x, y)
                if math.hypot(sx - gesture.screen.x(), sy - gesture.screen.y()) <= PICK_PIXELS:
                    return area, index
        return None

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        document, press = view.document, self._press
        if document is None or press is None or self._mode is _Mode.IDLE:
            return False
        self._current = gesture
        if self._mode is _Mode.PRESSED:
            if _travelled(press, gesture) < DRAG_PIXELS:
                return True
            self._start_drag(document, press)
        if self._mode is _Mode.MOVE:
            self._drag_move(view, document, press, gesture)
        elif self._mode is _Mode.CORNER and self._corner is not None:
            area, index = self._corner
            self._issue(MoveAreaPoint(area, index, _snapped(view, gesture.world)))
        elif self._mode is _Mode.ROTATE:
            angle = _bearing(self._center, gesture.world)
            delta = math.remainder(angle - self._angle, math.tau)
            self._angle = angle
            if delta:
                self._issue(
                    RotateObjects(selected_objects(document), delta, self.host.group_edit_method())
                )
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        document, press = view.document, self._press
        mode = self._mode
        self._mode = _Mode.IDLE
        self._press = None
        self._corner = None
        for command in self._commands:
            command.closed = True
        self._commands = []
        if document is None or press is None or mode is _Mode.IDLE:
            return False
        selection = document.selection
        if mode is _Mode.PRESSED and not selection.locked:
            picked = self._picked
            if picked is None:
                if not press.shift:
                    selection.clear()
            elif press.shift:
                selection.toggle(picked)
            else:
                selection.set([picked])
        elif mode is _Mode.MARQUEE and not selection.locked:
            inside = self._inside(view, press.screen, gesture.screen)
            if press.shift:
                selection.add(inside)
            else:
                selection.set(inside)
        view.update()
        return True

    def _inside(self, view: ToolView, corner: QPointF, other: QPointF) -> list[object]:
        """What the marquee catches: everything drawn inside the rectangle the user dragged, in
        pixels.

        The test is on screen rather than in world units because in the 3D view the rectangle
        covers a turned trapezoid of ground, and the world rectangle through two of its corners
        is a much smaller box that leaves out most of what the user drew around.
        """
        scene = view.scene
        if scene is None:
            return []
        rect = QRectF(corner, other).normalized()
        to_screen = view.transform.world_to_screen

        def holds(x: float, y: float) -> bool:
            return rect.contains(QPointF(*to_screen(x, y)))

        rules = self.host.pick_rules()
        found: list[object] = [
            marker.source
            for marker in scene.markers
            if rules.allows(marker) and _marker_shown(view, marker) and holds(marker.x, marker.y)
        ]
        if rules.allows_areas() and view.options.show_areas:
            found += [
                outline.source
                for outline in scene.areas
                if outline.points
                and view.is_shown(outline.source)
                and all(holds(x, y) for x, y in outline.points)
            ]
        return found

    def paint(self, view: ToolView, painter: QPainter) -> None:
        if self._mode is not _Mode.MARQUEE or self._press is None or self._current is None:
            return
        painter.setPen(QPen(_MARQUEE, 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(self._press.screen, self._current.screen).normalized())

    def _start_drag(self, document: MapDocument, press: Gesture) -> None:
        picked = self._picked
        selection = document.selection
        if picked is None:
            self._mode = _Mode.MARQUEE
            return
        if picked not in selection:
            if selection.locked:
                self._mode = _Mode.MARQUEE
                return
            if press.shift:
                selection.add([picked])
            else:
                selection.set([picked])
        self._mode = _Mode.MOVE

    def _drag_move(
        self, view: ToolView, document: MapDocument, press: Gesture, gesture: Gesture
    ) -> None:
        objects, areas = selected_objects(document), selected_areas(document)
        if not objects and not areas:
            return
        if self.host.vertical_locked():
            # Up the screen raises, by the world units the drag spans at the ground's depth.
            lift = (press.screen.y() - gesture.screen.y()) / view.transform.scale
            rise = lift - self._lifted
            if objects and rise:
                self._lifted = lift
                self._issue(MoveObjects(objects, 0.0, 0.0, dz=rise))
            return
        dx = gesture.world[0] - press.world[0]
        dy = gesture.world[1] - press.world[1]
        if self.host.angle_locked():
            length = math.hypot(dx, dy)
            direction = round(math.atan2(dy, dx) / _EIGHTH) * _EIGHTH
            dx, dy = length * math.cos(direction), length * math.sin(direction)
        grid = view.options.grid
        lead = self._picked
        if grid is not None and grid.snap and isinstance(lead, Object):
            # Snap the object under the cursor; the rest of the selection keeps its offsets.
            start_x = lead.position[0] - self._moved[0]
            start_y = lead.position[1] - self._moved[1]
            dx = snap(start_x + dx, grid.spacing) - start_x
            dy = snap(start_y + dy, grid.spacing) - start_y
        step = (dx - self._moved[0], dy - self._moved[1])
        if step == (0.0, 0.0):
            return
        self._moved = (dx, dy)
        self._issue(MoveObjects(objects, *step, areas=areas))

    def _issue(self, command: MoveObjects | RotateObjects | MoveAreaPoint) -> None:
        self._commands.append(command)
        self.host.execute(command)


class PlaceTool(Tool):
    """Place Object: click to place the palette's object, or drag from where it goes to turn it
    towards the cursor. The new object is selected."""

    def __init__(self, host: PlaceHost) -> None:
        self.host = host
        self._press: Gesture | None = None
        self._current: Gesture | None = None
        self._dragging = False

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        if document is None or document.map.objects_list is None:
            return False
        if self.host.place_template() is None:
            return False
        self._press = self._current = gesture
        self._dragging = False
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        if self._press is None:
            return False
        self._current = gesture
        if _travelled(self._press, gesture) >= DRAG_PIXELS:
            self._dragging = True
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, document, template = self._press, view.document, self.host.place_template()
        dragging = self._dragging
        self._press = self._current = None
        self._dragging = False
        if press is None or document is None or template is None:
            return False
        x, y = _snapped(view, press.world)
        angle = _bearing((x, y), gesture.world) if dragging else 0.0
        obj = new_object(
            document.map,
            template,
            (x, y, self.host.place_height()),
            angle,
            self.host.place_owner(),
            self.host.active_layer(),
        )
        self.host.execute(place_objects(document.map, [obj]))
        document.selection.set([obj])
        view.update()
        return True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        if not self._dragging or self._press is None or self._current is None:
            return
        painter.setPen(QPen(_MARQUEE, 1.5))
        painter.drawLine(self._press.screen, self._current.screen)
        painter.drawEllipse(self._press.screen, 4.0, 4.0)


class WaypointTool(Tool):
    """Waypoint Tool: click an empty spot to add a waypoint; click a waypoint to select it; drag
    from a waypoint to another to link them (or, if they are linked, to remove the link), or to
    an empty spot to add a waypoint linked from it. The waypoint added or reached is selected."""

    def __init__(self, host: EditHost) -> None:
        self.host = host
        self._press: Gesture | None = None
        self._current: Gesture | None = None
        self._start: Marker | None = None
        self._dragging = False

    def _waypoint_at(self, view: ToolView, gesture: Gesture) -> Marker | None:
        scene = view.scene
        if scene is None:
            return None
        return scene.nearest(
            *gesture.world,
            PICK_PIXELS / view.transform.scale,
            kinds=_WAYPOINTS,
            accept=lambda marker: _marker_shown(view, marker),
        )

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        if document is None or document.map.objects_list is None:
            return False
        self._press = self._current = gesture
        self._start = self._waypoint_at(view, gesture)
        self._dragging = False
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        if self._press is None:
            return False
        self._current = gesture
        if _travelled(self._press, gesture) >= DRAG_PIXELS:
            self._dragging = True
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, start, dragging, document = self._press, self._start, self._dragging, view.document
        self._press = self._current = self._start = None
        self._dragging = False
        if press is None or document is None:
            return False
        map, selection = document.map, document.selection
        try:
            if start is not None and not dragging:
                selection.set([start.source])
            elif start is not None:
                start_id = waypoint_id(start.source)
                target = self._waypoint_at(view, gesture)
                if start_id is None:
                    return True
                if target is not None and target.source is not start.source:
                    target_id = waypoint_id(target.source)
                    if target_id is not None:
                        self.host.execute(toggle_link(map, start_id, target_id))
                        selection.set([target.source])
                elif target is None:
                    x, y = _snapped(view, gesture.world)
                    command, obj = add_linked_waypoint(
                        map, start_id, (x, y, 0.0), self.host.active_layer()
                    )
                    self.host.execute(command)
                    selection.set([obj])
            else:
                x, y = _snapped(view, press.world)
                obj = new_waypoint(map, (x, y, 0.0), self.host.active_layer())
                self.host.execute(place_objects(map, [obj], "Add Waypoint"))
                selection.set([obj])
        except ValueError:
            return True
        finally:
            view.update()
        return True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        if not self._dragging or self._start is None or self._current is None:
            return
        start = QPointF(*view.transform.world_to_screen(self._start.x, self._start.y))
        painter.setPen(QPen(_MARQUEE, 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(start, self._current.screen)


class GenericAIHost(EditHost, Protocol):
    def generic_ai_type(self) -> GenericAIType:
        """The type Generic AI Object Options gives a new object."""
        ...

    def generic_ai_wall_hub(self) -> int:
        """The wall hub number Generic AI Object Options gives a new object."""
        ...


class GenericAIObjectTool(Tool):
    """Generic AI Object tool: a click on a generic AI object selects it; a click elsewhere adds
    one with the options' type and wall hub number, and selects it."""

    def __init__(self, host: GenericAIHost) -> None:
        self.host = host
        self._press: Gesture | None = None

    def _object_at(self, view: ToolView, gesture: Gesture) -> Marker | None:
        scene = view.scene
        if scene is None:
            return None
        for distance in PICK_DISTANCES:
            found = scene.nearest(
                *gesture.world,
                max(distance, PICK_PIXELS / view.transform.scale),
                kinds=_GENERIC_AI,
                accept=lambda marker: _marker_shown(view, marker),
            )
            if found is not None:
                return found
        return None

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        if document is None or document.map.objects_list is None:
            return False
        self._press = gesture
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, document = self._press, view.document
        self._press = None
        if press is None or document is None:
            return False
        found = self._object_at(view, press)
        if found is not None:
            document.selection.set([found.source])
        else:
            x, y = _snapped(view, press.world)
            obj = new_generic_ai_object(
                document.map,
                (x, y, 0.0),
                self.host.generic_ai_type(),
                self.host.generic_ai_wall_hub(),
                self.host.active_layer(),
            )
            try:
                self.host.execute(place_objects(document.map, [obj], "Add Generic AI Object"))
            except ValueError:
                return True
            document.selection.set([obj])
        view.update()
        return True

    def cancel(self) -> None:
        self._press = None


class PolygonTool(Tool):
    """Polygon Tool: click to add corners; click the first corner again (with at least three) to
    close the new trigger area, which is then selected."""

    def __init__(self, host: EditHost) -> None:
        self.host = host
        self.points: list[tuple[float, float]] = []
        self._hover: Gesture | None = None

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        return document is not None and document.map.trigger_areas is not None

    def hover(self, view: ToolView, gesture: Gesture) -> None:
        self._hover = gesture
        if self.points:
            view.update()

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        self.hover(view, gesture)
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        if document is None or document.map.trigger_areas is None:
            return False
        if len(self.points) >= 3 and self._near_first(view, gesture):
            area = new_area(document.map, self.points, self.host.active_layer())
            self.points = []
            self.host.execute(add_area(document.map, area))
            document.selection.set([area])
        else:
            self.points.append(_snapped(view, gesture.world))
        view.update()
        return True

    def _near_first(self, view: ToolView, gesture: Gesture) -> bool:
        sx, sy = view.transform.world_to_screen(*self.points[0])
        return math.hypot(sx - gesture.screen.x(), sy - gesture.screen.y()) <= PICK_PIXELS

    def cancel(self) -> None:
        self.points = []

    def paint(self, view: ToolView, painter: QPainter) -> None:
        if not self.points:
            return
        screen = [QPointF(*view.transform.world_to_screen(x, y)) for x, y in self.points]
        painter.setPen(QPen(_MARQUEE, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for first, second in zip(screen, screen[1:], strict=False):
            painter.drawLine(first, second)
        if self._hover is not None:
            painter.setPen(QPen(_MARQUEE, 1, Qt.PenStyle.DashLine))
            painter.drawLine(screen[-1], self._hover.screen)
        painter.setPen(QPen(_MARQUEE, 1.5))
        for index, point in enumerate(screen):
            size = 6.0 if index == 0 else 4.0
            painter.drawRect(QRectF(point.x() - size / 2, point.y() - size / 2, size, size))


class BuildListHost(EditHost, Protocol):
    def place_template(self) -> str | None:
        """The object chosen in the palette, or None."""
        ...

    def build_side(self) -> int | None:
        """The player whose build list the Build List panel shows."""
        ...

    def select_build_entry(self, entry: BuildListInfo) -> None: ...


class BuildListTool(Tool):
    """Build List Tool: click to add the palette's object to the chosen player's build list, drag
    from the spot to turn it, click an entry of any build list to choose it, and drag an entry to
    move it."""

    def __init__(self, host: BuildListHost) -> None:
        self.host = host
        self._press: Gesture | None = None
        self._entry: BuildListInfo | None = None
        self._dragging = False
        self._commands: list[MoveBuilding] = []

    def entry_at(self, view: ToolView, gesture: Gesture) -> BuildListInfo | None:
        document = view.document
        if document is None:
            return None
        best, best_distance = None, PICK_PIXELS
        for side in range(len(side_names(document.map))):
            for entry in build_list_entries(document.map, side) or []:
                sx, sy = view.transform.world_to_screen(entry.location[0], entry.location[1])
                distance = math.hypot(sx - gesture.screen.x(), sy - gesture.screen.y())
                if distance <= best_distance:
                    best, best_distance = entry, distance
        return best

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        if view.document is None:
            return False
        self._press = gesture
        self._entry = self.entry_at(view, gesture)
        self._dragging = False
        self._commands = []
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        press, entry = self._press, self._entry
        if press is None:
            return False
        if _travelled(press, gesture) >= DRAG_PIXELS:
            self._dragging = True
        if self._dragging and entry is not None:
            x, y = _snapped(view, gesture.world)
            command = MoveBuilding(entry, (x, y, entry.location[2]))
            self._commands.append(command)
            self.host.execute(command)
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        press, entry, dragging, document = self._press, self._entry, self._dragging, view.document
        self._press = self._entry = None
        self._dragging = False
        for command in self._commands:
            command.closed = True
        self._commands = []
        if press is None or document is None:
            return False
        if entry is not None:
            self.host.select_build_entry(entry)
            return True
        side, template = self.host.build_side(), self.host.place_template()
        if side is None or template is None or build_list_entries(document.map, side) is None:
            return True
        x, y = _snapped(view, press.world)
        angle = _bearing((x, y), gesture.world) if dragging else 0.0
        added = new_entry(document.map, template, (x, y, 0.0), angle)
        self.host.execute(add_entry(document.map, side, added))
        self.host.select_build_entry(added)
        view.update()
        return True


class RulerTool(Tool):
    """Ruler Tool: drag to measure the distance between two points, in feet (world units) and
    heightmap cells. With Circular Measurements on, the distance is shown as a circle's radius
    about the first point. The measurement stays until the next one."""

    def __init__(self, host: RulerHost) -> None:
        self.host = host
        self.start: tuple[float, float] | None = None
        self.end: tuple[float, float] | None = None

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        if view.document is None:
            return False
        self.start = self.end = gesture.world
        view.update()
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        if self.start is None:
            return False
        self.end = gesture.world
        self.host.show_measurement(self.measurement())
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        if self.start is None:
            return False
        self.end = gesture.world
        self.host.show_measurement(self.measurement())
        view.update()
        return True

    def distance(self) -> float:
        if self.start is None or self.end is None:
            return 0.0
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    def measurement(self) -> str:
        distance = self.distance()
        kind = "Radius" if self.host.ruler_circular() else "Distance"
        return f"{kind}: {distance:.1f} ft ({distance / WORLD_UNITS_PER_CELL:.1f} cells)"

    def cancel(self) -> None:
        self.start = self.end = None

    def paint(self, view: ToolView, painter: QPainter) -> None:
        if self.start is None or self.end is None:
            return
        painter.setPen(QPen(_MARQUEE, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        view.world_polygon(painter, [self.start, self.end], closed=False)
        if self.host.ruler_circular():
            view.world_circle(painter, *self.start, self.distance())
        end = QPointF(*view.transform.world_to_screen(*self.end))
        draw_label(painter, end + QPointF(8, -8), self.measurement())


def selected_objects(document: MapDocument) -> list[Object]:
    return [item for item in document.selection if isinstance(item, Object)]


def selected_areas(document: MapDocument) -> list[TriggerArea]:
    return [item for item in document.selection if isinstance(item, TriggerArea)]


def _bearing(center: tuple[float, float], point: tuple[float, float]) -> float:
    return math.atan2(point[1] - center[1], point[0] - center[0])
