"""Camera keys as objects in the world, the way WorldBuilder's Camera Animations dialog edits them.

A camera animation's keys are not only rows in a list: each one stands somewhere on the map, and
WorldBuilder draws it there as a camera, draws a look-at key as a marker, and puts drag handles on
whichever one is chosen. Dragging a handle moves or turns that key; the view it sees is shown in a
preview of its own, so the view being worked in never moves.

This module is the part of that without a screen: which objects an animation puts in the world
(`scene`), where an object's handles point (`handle_axes`), what a click lands on (`object_at`,
`handle_at`), what a drag comes to (`axis_parameter`, `turn_angle`), the wireframe a camera is
drawn as (`glyph_segments`, `frustum_segments`), and the commands an edit makes.

Handles are a constant size on screen, so their length in world units comes from the view's scale
at the object; everything here takes that length, or a `project` that turns a world point into
pixels, rather than knowing about the camera.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from sage_map.assets.camera_animation_list import CameraAnimation
from sage_map.assets.named_cameras import NamedCamera
from sage_worldbuilder.cameras import (
    CAMERAS,
    FREE,
    Pose,
    Vec3,
    camera_keys,
    evaluate,
    look_at_keys,
    pose_axes,
    turned,
)
from sage_worldbuilder.changes import Change
from sage_worldbuilder.commands import Command

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "CAMERA_KEY",
    "GLYPH_PIXELS",
    "HANDLE_PIXELS",
    "LOCAL",
    "LOOK_KEY",
    "NAMED_CAMERA",
    "PICKED",
    "PICK_PIXELS",
    "ROTATE",
    "TRANSLATE",
    "WORLD",
    "CameraObject",
    "CameraScene",
    "DRAGGING",
    "Drag",
    "Editor",
    "ViewState",
    "SetCameraValue",
    "axis_parameter",
    "frustum_segments",
    "glyph_segments",
    "handle_at",
    "handle_axes",
    "handle_tips",
    "move_command",
    "object_at",
    "turn_angle",
    "turn_command",
]

# What a handle is: a drag that slides the object along an axis, or one that turns it about one.
TRANSLATE, ROTATE = "translate", "rotate"
# What a press came to: a handle taken hold of, or another object chosen.
DRAGGING, PICKED = "dragging", "picked"
# Which axes the handles point along: the map's, or the camera's own right, up and forward.
WORLD, LOCAL = "world", "local"
# What an object in the world stands for.
CAMERA_KEY, LOOK_KEY, NAMED_CAMERA = "camera", "look-at", "named"

# Screen pixels: a handle's length, a camera glyph's height, and how close a click must land.
HANDLE_PIXELS = 64.0
GLYPH_PIXELS = 22.0
PICK_PIXELS = 8.0
# How square-on an axis must be to the view to be draggable: below this the handle is edge on and
# a drag along it would run away.
MIN_AXIS_SPREAD = 1e-3
AXIS_NAMES = ("X", "Y", "Z")
LOCAL_NAMES = ("Right", "Up", "Forward")

# A world point to pixels, or None where the view cannot show it.
Project = Callable[[float, float, float], "tuple[float, float] | None"]


@dataclass(frozen=True)
class CameraObject:
    """Something the Cameras panel puts in the world: a camera key, the point a look-at key aims
    at, or a named camera (at the point it looks at)."""

    kind: str
    # Where it sits in its track, or in the map's named cameras.
    index: int
    position: Vec3
    # Where a camera looks and which way is up for it, as unit vectors; None for a look-at point.
    forward: Vec3 | None = None
    up: Vec3 | None = None
    fov: float = 0.0
    # The frame it is keyed at (a key), else 0.
    frame: int = 0

    @property
    def key(self) -> tuple[str, int]:
        return (self.kind, self.index)

    @property
    def is_camera(self) -> bool:
        return self.forward is not None


@dataclass
class CameraScene:
    """What the 3D view draws for the Cameras panel and what a drag there may touch."""

    # The animation the objects came from, so a drag can key it; None for named cameras alone.
    animation: CameraAnimation | None = None
    objects: list[CameraObject] = field(default_factory=list)
    # The chosen object's `key`, or None.
    selected: tuple[str, int] | None = None
    system: str = WORLD
    motion: str = TRANSLATE
    # The camera's and the look-at point's paths through the animation, or None when not shown.
    camera_path: list[Vec3] | None = None
    look_at_path: list[Vec3] | None = None
    # The pose the preview looks from, and how far it sees; None with the preview off.
    preview: Pose | None = None
    far_clip: float = 1000.0

    def object(self, key: tuple[str, int] | None) -> CameraObject | None:
        return next((obj for obj in self.objects if obj.key == key), None)

    @property
    def chosen(self) -> CameraObject | None:
        return self.object(self.selected)


def _unit(vector: Sequence[float] | np.ndarray) -> Vec3:
    array = np.asarray(vector, dtype=np.float64)
    array = array / (float(np.linalg.norm(array)) or 1.0)
    return (float(array[0]), float(array[1]), float(array[2]))


def _pose_at(animation: CameraAnimation, key: Any) -> Pose | None:
    """The pose a camera key stands for: its own position and field of view, and for a look-at
    animation the direction to where the look-at track points at that frame."""
    pose = evaluate(animation, key.frame_index)
    if pose is None:
        return None
    return Pose(
        tuple(float(v) for v in key.position),  # type: ignore[arg-type]
        pose.target,
        getattr(key, "rotation", None),
        getattr(key, "roll", 0.0),
        key.fov,
    )


def objects(animation: CameraAnimation | None) -> list[CameraObject]:
    """Every key of an animation as an object in the world, cameras first."""
    if animation is None:
        return []
    listed: list[CameraObject] = []
    for index, key in enumerate(camera_keys(animation)):
        pose = _pose_at(animation, key)
        forward, up = pose_axes(pose) if pose is not None else (None, None)
        listed.append(
            CameraObject(
                CAMERA_KEY,
                index,
                tuple(float(v) for v in key.position),  # type: ignore[arg-type]
                _unit(forward) if forward is not None else (0.0, 1.0, 0.0),
                _unit(up) if up is not None else (0.0, 0.0, 1.0),
                float(key.fov),
                int(key.frame_index),
            )
        )
    for index, key in enumerate(look_at_keys(animation)):
        listed.append(
            CameraObject(
                LOOK_KEY,
                index,
                tuple(float(v) for v in key.look_at_point),  # type: ignore[arg-type]
                frame=int(key.frame_index),
            )
        )
    return listed


def named_object(camera: NamedCamera, index: int) -> CameraObject:
    """A named camera as an object at the point it looks at."""
    return CameraObject(NAMED_CAMERA, index, tuple(float(v) for v in camera.look_at_point))  # type: ignore[arg-type]


def path_points(
    animation: CameraAnimation | None, samples: int, look_at: bool = False
) -> list[Vec3]:
    """The camera's path through an animation in three dimensions, or the path of what it looks
    at; empty for an animation that has no keys (or no look-at track)."""
    if animation is None:
        return []
    count = min(max(animation.num_frames, 1), samples)
    step = max(animation.num_frames - 1, 1) / max(count - 1, 1)
    points: list[Vec3] = []
    for index in range(count):
        pose = evaluate(animation, index * step)
        if pose is None:
            return []
        point = pose.target if look_at else pose.position
        if point is None:
            return []
        points.append(tuple(float(v) for v in point))  # type: ignore[arg-type]
    return points


def handle_axes(
    obj: CameraObject, system: str = WORLD, motion: str = TRANSLATE
) -> list[tuple[str, Vec3]]:
    """The named unit axes an object's handles point along.

    In world coordinates they are the map's x, y and z. In local ones they are a camera's own
    right, up and forward; a look-at point, which has no facing of its own, keeps the map's.
    A look-at point cannot be turned, so it has no rotation handles."""
    if motion == ROTATE and not obj.is_camera:
        return []
    if system == LOCAL and obj.forward is not None and obj.up is not None:
        forward = np.asarray(obj.forward, dtype=np.float64)
        up = np.asarray(obj.up, dtype=np.float64)
        right = np.cross(forward, up)
        return list(zip(LOCAL_NAMES, (_unit(right), _unit(up), _unit(forward)), strict=True))
    return [
        (AXIS_NAMES[0], (1.0, 0.0, 0.0)),
        (AXIS_NAMES[1], (0.0, 1.0, 0.0)),
        (AXIS_NAMES[2], (0.0, 0.0, 1.0)),
    ]


def handle_tips(position: Vec3, axes: Sequence[tuple[str, Vec3]], length: float) -> list[Vec3]:
    """Where each handle's arrow ends in the world."""
    return [
        (
            position[0] + axis[0] * length,
            position[1] + axis[1] * length,
            position[2] + axis[2] * length,
        )
        for _name, axis in axes
    ]


def _distance_to_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    span = dx * dx + dy * dy
    if span <= 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / span))
    return math.hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)


def object_at(
    project: Project,
    screen: tuple[float, float],
    listed: Sequence[CameraObject],
    pixels: float = PICK_PIXELS + GLYPH_PIXELS / 2,
) -> CameraObject | None:
    """The object a click lands on: the nearest one whose marker the click is inside, or None."""
    best: tuple[float, CameraObject] | None = None
    for obj in listed:
        point = project(*obj.position)
        if point is None:
            continue
        away = math.hypot(point[0] - screen[0], point[1] - screen[1])
        if away <= pixels and (best is None or away < best[0]):
            best = (away, obj)
    return best[1] if best is not None else None


def handle_at(
    project: Project,
    screen: tuple[float, float],
    position: Vec3,
    axes: Sequence[tuple[str, Vec3]],
    length: float,
    pixels: float = PICK_PIXELS,
) -> int | None:
    """Which handle a click lands on, or None.

    A click on an arrowhead takes that handle, which settles the axes that lie over each other
    from where the view stands: two arrows can share a line on screen, but their heads are apart.
    Otherwise the arrow whose shaft passes nearest wins."""
    origin = project(*position)
    if origin is None:
        return None
    on_head: tuple[float, int] | None = None
    on_shaft: tuple[float, int] | None = None
    for index, tip in enumerate(handle_tips(position, axes, length)):
        end = project(*tip)
        if end is None:
            continue
        to_head = math.hypot(end[0] - screen[0], end[1] - screen[1])
        if to_head <= pixels * 2 and (on_head is None or to_head < on_head[0]):
            on_head = (to_head, index)
        away = _distance_to_segment(screen, origin, end)
        if away <= pixels and (on_shaft is None or away < on_shaft[0]):
            on_shaft = (away, index)
    best = on_head or on_shaft
    return best[1] if best is not None else None


def axis_parameter(
    position: Vec3,
    axis: Vec3,
    origin: Sequence[float],
    direction: Sequence[float],
) -> float | None:
    """How far along `axis` from `position` the mouse ray comes closest, in world units; None
    where the axis is too nearly along the ray to say."""
    u = np.asarray(axis, dtype=np.float64)
    v = np.asarray(direction, dtype=np.float64)
    w = np.asarray(position, dtype=np.float64) - np.asarray(origin, dtype=np.float64)
    a, b, c = float(u @ u), float(u @ v), float(v @ v)
    denominator = a * c - b * b
    if abs(denominator) < MIN_AXIS_SPREAD:
        return None
    d, e = float(u @ w), float(v @ w)
    return (b * e - c * d) / denominator


def turn_angle(
    center: tuple[float, float],
    start: tuple[float, float],
    screen: tuple[float, float],
    towards_viewer: bool,
) -> float:
    """The angle in radians a drag about a handle turns the object: the angle the cursor swept
    about the object on screen, the way round the axis points."""
    before = math.atan2(start[1] - center[1], start[0] - center[0])
    now = math.atan2(screen[1] - center[1], screen[0] - center[0])
    swept = (now - before + math.pi) % (2 * math.pi) - math.pi
    # Widget y runs down, so a sweep that reads clockwise on screen is a turn the other way.
    return -swept if towards_viewer else swept


def glyph_segments(obj: CameraObject, size: float) -> list[tuple[Vec3, Vec3]]:
    """A camera as a wireframe `size` world units tall: a body, the two reels on top of it and
    the lens it looks through."""
    if obj.forward is None or obj.up is None:
        return []
    forward = np.asarray(obj.forward, dtype=np.float64)
    up = np.asarray(obj.up, dtype=np.float64)
    right = np.cross(forward, up)
    eye = np.asarray(obj.position, dtype=np.float64)
    half = size / 2

    def at(across: float, upward: float, ahead: float) -> Vec3:
        point = eye + right * across * half + up * upward * half + forward * ahead * half
        return (float(point[0]), float(point[1]), float(point[2]))

    segments: list[tuple[Vec3, Vec3]] = []
    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    for index, (across, upward) in enumerate(corners):
        next_across, next_up = corners[(index + 1) % 4]
        for ahead in (-2.0, 0.0):
            segments.append((at(across, upward, ahead), at(next_across, next_up, ahead)))
        segments.append((at(across, upward, -2.0), at(across, upward, 0.0)))
        # The lens: from the body's face out to a smaller square in front of it.
        segments.append((at(across, upward, 0.0), at(across * 0.6, upward * 0.6, 0.9)))
    for reel in (-0.6, 0.6):
        points = [
            at(
                0.0,
                1.0 + math.sin(step / 8 * math.tau) * 0.7,
                reel + math.cos(step / 8 * math.tau) * 0.7,
            )
            for step in range(8)
        ]
        segments += [(points[step], points[(step + 1) % 8]) for step in range(8)]
    return segments


def frustum_segments(
    position: Vec3,
    forward: Sequence[float],
    up: Sequence[float],
    fov: float,
    distance: float,
    aspect: float = 4 / 3,
) -> list[tuple[Vec3, Vec3]]:
    """The pyramid a camera sees, from its eye out to `distance` world units: what the preview's
    far clip distance draws in the view."""
    eye = np.asarray(position, dtype=np.float64)
    ahead = np.asarray(forward, dtype=np.float64)
    upward = np.asarray(up, dtype=np.float64)
    right = np.cross(ahead, upward)
    half_up = math.tan(max(fov, 1e-3) / 2) * distance
    half_across = half_up * aspect
    far = eye + ahead * distance
    corners = [
        far + right * across * half_across + upward * upward_sign * half_up
        for across, upward_sign in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]
    point = (float(eye[0]), float(eye[1]), float(eye[2]))
    edges: list[tuple[Vec3, Vec3]] = []
    for index, corner in enumerate(corners):
        here = (float(corner[0]), float(corner[1]), float(corner[2]))
        after = corners[(index + 1) % 4]
        edges.append((point, here))
        edges.append((here, (float(after[0]), float(after[1]), float(after[2]))))
    return edges


class SetCameraValue(Command):
    """Set one value of a camera key or a named camera.

    A drag pushes one of these a step, and they merge while the drag is open, so the whole drag is
    one undo entry and the next drag starts another."""

    def __init__(
        self,
        target: object,
        name: str,
        value: object,
        label: str,
        change: Change = CAMERAS,
    ) -> None:
        self.target = target
        self.name = name
        self.value = value
        self.label = label
        self.change = change
        self.closed = False
        self._old: object = None
        self._done = False

    def do(self, document: MapDocument) -> None:
        if not self._done:
            self._old = getattr(self.target, self.name)
            self._done = True
        setattr(self.target, self.name, self.value)

    def undo(self, document: MapDocument) -> None:
        setattr(self.target, self.name, self._old)

    def changes(self) -> tuple[Change, ...]:
        return (self.change,)

    def merge(self, following: Command) -> bool:
        if self.closed or not (
            isinstance(following, SetCameraValue)
            and following.target is self.target
            and following.name == self.name
        ):
            return False
        self.value = following.value
        return True


def _target(
    animation: CameraAnimation | None, cameras: Sequence[NamedCamera], obj: CameraObject
) -> Any | None:
    if obj.kind == NAMED_CAMERA:
        return cameras[obj.index] if 0 <= obj.index < len(cameras) else None
    if animation is None:
        return None
    track = camera_keys(animation) if obj.kind == CAMERA_KEY else look_at_keys(animation)
    return track[obj.index] if 0 <= obj.index < len(track) else None


def move_command(
    animation: CameraAnimation | None,
    cameras: Sequence[NamedCamera],
    obj: CameraObject,
    position: Vec3,
) -> Command | None:
    """Put an object at a world position: a key's `position`, a look-at key's point, or the point
    a named camera looks at."""
    target = _target(animation, cameras, obj)
    if target is None:
        return None
    place = (float(position[0]), float(position[1]), float(position[2]))
    if obj.kind == CAMERA_KEY:
        return SetCameraValue(target, "position", place, "Move Camera Key")
    label = "Move Look-at Point" if obj.kind == LOOK_KEY else "Move Named Camera"
    return SetCameraValue(target, "look_at_point", place, label)


def turn_command(
    animation: CameraAnimation | None,
    cameras: Sequence[NamedCamera],
    obj: CameraObject,
    axis: Vec3,
    angle: float,
) -> Command | None:
    """Turn a camera `angle` radians about a world axis.

    A free animation's key stores the whole rotation, so any axis turns it. A look-at animation's
    camera key is aimed by its look-at track and stores only a roll, so a turn about the way it
    looks rolls it and the other axes do nothing. A named camera stores its own yaw, pitch and
    roll, turned the same way."""
    target = _target(animation, cameras, obj)
    if target is None or not obj.is_camera:
        return None
    if obj.kind == CAMERA_KEY and animation is not None and animation.animation_type == FREE:
        return SetCameraValue(
            target, "rotation", turned(target.rotation, axis, angle), "Turn Camera Key"
        )
    forward = np.asarray(obj.forward, dtype=np.float64)
    along = float(np.asarray(axis, dtype=np.float64) @ forward)
    if abs(along) < 0.5:
        return None
    roll = float(getattr(target, "roll", 0.0)) + angle * (1.0 if along > 0 else -1.0)
    return SetCameraValue(target, "roll", roll, "Roll Camera Key")


@dataclass(frozen=True)
class ViewState:
    """What a 3D view is showing, as the editor needs it: its camera (anything that answers `ray`,
    `eye` and `pixels_per_unit_at`), how it projects a world point, its camera objects and the
    map's named cameras. Built afresh for each event, because all of them move."""

    camera: Any
    project: Project
    scene: CameraScene
    cameras: Sequence[NamedCamera] = ()

    def handle_length(self, position: Vec3) -> float:
        """A handle's length in world units, so it stays `HANDLE_PIXELS` long on screen."""
        return HANDLE_PIXELS / max(self.camera.pixels_per_unit_at(position), 1e-6)


class Editor:
    """Picking and dragging the camera objects, without a widget: the 3D view hands it presses,
    moves and releases in pixels and it issues the commands.

    A press on a handle starts a drag, a press on another object chooses it (`picked`), and
    anything else is left to the tool. Every step of a drag pushes a command that merges into the
    one before it, so the drag is one undo entry, which `release` then closes."""

    def __init__(self, execute: Callable[[Command], None]) -> None:
        self.execute = execute
        self.drag: Drag | None = None
        # The object a press chose, for the view to tell the panel about.
        self.picked: tuple[str, int] | None = None
        # The handle the cursor is over, as `(kind, index, axis)`.
        self.hover: tuple[str, int, int] | None = None
        self._command: SetCameraValue | None = None

    def held(self, scene: CameraScene) -> CameraObject | None:
        """The object with the handles on it: the one chosen, or the one being dragged while a
        drag is on, so a drag keeps its grip even if the panel is rebuilt under it."""
        if self.drag is not None:
            return scene.object(self.drag.obj.key) or self.drag.obj
        return scene.chosen

    def handle_at(self, view: ViewState, screen: tuple[float, float]) -> tuple[int, Vec3] | None:
        """Which of the chosen object's handles a pixel is over, as `(index, axis)`."""
        obj = self.held(view.scene)
        if obj is None:
            return None
        axes = handle_axes(obj, view.scene.system, view.scene.motion)
        index = handle_at(
            view.project, screen, obj.position, axes, view.handle_length(obj.position)
        )
        return (index, axes[index][1]) if index is not None else None

    def press(self, view: ViewState, screen: tuple[float, float]) -> str | None:
        """A left press over the camera objects: DRAGGING with a handle taken hold of, PICKED with
        another object chosen (in `picked`), or None to leave the press to the tool."""
        self.picked = None
        found = self.handle_at(view, screen)
        obj = self.held(view.scene)
        if found is not None and obj is not None:
            index, axis = found
            self.drag = self._start(view, obj, axis, screen)
            self._command = None
            self.hover = (obj.kind, obj.index, index)
            return DRAGGING
        picked = object_at(view.project, screen, view.scene.objects)
        if picked is None:
            return None
        self.picked = picked.key
        return PICKED

    def _start(
        self, view: ViewState, obj: CameraObject, axis: Vec3, screen: tuple[float, float]
    ) -> Drag:
        motion = view.scene.motion
        drag = Drag(obj, axis, motion, start_position=obj.position)
        if motion == TRANSLATE:
            origin, direction = view.camera.ray(*screen)
            along = axis_parameter(obj.position, axis, origin, direction)
            drag.start_parameter = along if along is not None else 0.0
            return drag
        center = view.project(*obj.position)
        drag.center_screen = center if center is not None else screen
        drag.start_screen = screen
        away = np.asarray(obj.position, dtype=np.float64) - np.asarray(view.camera.eye)
        drag.towards_viewer = float(np.asarray(axis, dtype=np.float64) @ away) < 0
        return drag

    def move(self, view: ViewState, screen: tuple[float, float]) -> bool:
        """Carry a drag on: the object slides along its axis, or turns about it."""
        drag = self.drag
        if drag is None:
            return False
        animation, cameras = view.scene.animation, view.cameras
        if drag.motion == TRANSLATE:
            origin, direction = view.camera.ray(*screen)
            position = drag.moved_to(origin, direction)
            command = (
                move_command(animation, cameras, drag.obj, position)
                if position is not None
                else None
            )
        else:
            angle = drag.turned_by(screen)
            command = turn_command(animation, cameras, drag.obj, drag.axis, angle - drag.angle)
            drag.angle = angle
        if command is not None:
            self.execute(command)
            if self._command is None and isinstance(command, SetCameraValue):
                self._command = command
        return True

    def release(self) -> bool:
        """End a drag, closing its command so the next drag is an undo entry of its own.

        What was dragged is left in `picked`: the edits a drag makes rebuild the panel's lists,
        and the object has to come out of that still chosen, or its handles go away under the
        cursor and the next drag begins with a click that only chooses it again."""
        if self.drag is None:
            return False
        if self._command is not None:
            self._command.closed = True
        self.picked = self.drag.obj.key
        self.drag = None
        self._command = None
        return True

    def hover_at(self, view: ViewState, screen: tuple[float, float]) -> bool:
        """Follow the cursor over the handles; True when what it is over changed."""
        obj = self.held(view.scene)
        found = self.handle_at(view, screen) if obj is not None else None
        hover = (obj.kind, obj.index, found[0]) if found is not None and obj is not None else None
        if hover == self.hover:
            return False
        self.hover = hover
        return True


@dataclass
class Drag:
    """A handle being dragged: which object and axis, and where the drag started."""

    obj: CameraObject
    axis: Vec3
    motion: str
    # Where the object stood, and the parameter along the axis the press came to (a move), or
    # the pixel the press landed on and the object's pixel (a turn).
    start_position: Vec3 = (0.0, 0.0, 0.0)
    start_parameter: float = 0.0
    start_screen: tuple[float, float] = (0.0, 0.0)
    center_screen: tuple[float, float] = (0.0, 0.0)
    towards_viewer: bool = True
    angle: float = 0.0

    def moved_to(self, origin: Sequence[float], direction: Sequence[float]) -> Vec3 | None:
        """Where the object goes for a mouse ray, or None where the axis cannot be read."""
        along = axis_parameter(self.start_position, self.axis, origin, direction)
        if along is None:
            return None
        step = along - self.start_parameter
        return (
            self.start_position[0] + self.axis[0] * step,
            self.start_position[1] + self.axis[1] * step,
            self.start_position[2] + self.axis[2] * step,
        )

    def turned_by(self, screen: tuple[float, float]) -> float:
        """How far the object has turned since the press, in radians."""
        return turn_angle(self.center_screen, self.start_screen, screen, self.towards_viewer)
