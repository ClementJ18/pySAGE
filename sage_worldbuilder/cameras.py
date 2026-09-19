"""Named cameras and camera animations (PLAN.md 5.5 and 5.8).

**Named cameras** (`NamedCameras`) are a look-at point (height 0 on all 795 corpus cameras), a name,
pitch, roll and yaw in radians (pitch 1.0 on 528), a zoom, a field of view in radians (50 degrees
on 719) and a float not decoded. How the game frames a view from them is not read, so going to one
in the 3D view is a choice: it looks at the point from the camera's pitch and yaw, from the zoom
times the map's maximum camera height above it.

**Camera animations** (`CameraAnimationList`) are free animations, whose keys each hold the
camera's position, rotation (a unit quaternion) and field of view, and look-at animations, whose
camera keys hold a position, roll and field of view and whose look-at keys hold the point looked at.
Every animation has a length in frames (at least 1, `CameraAnimation::setDuration`) and a start
offset; on all 373 corpus animations the first key is at frame 0, the keys are in order and none is
past the last frame. WorldBuilder names new ones `Free Animation` and `Look-at Animation`, then with
a number.

Between keys a track is interpolated as `CameraAnimationFrameData::doInterpolate` (`0x00EE42C0`,
`0x00EE5DC0`, `0x00EE5C10`) does: the segment is the last key at or before the frame and the next
one, `t` the frame's fraction of the way between them, and the method the segment's first key's.
Linear (`line`) mixes the two keys. Spline (`catm`) is a Catmull-Rom curve (`0x012FE0A0`) through
the keys before and after the segment, each first scaled so its gap matches the segment's frame
count: `before' = key0 + (before - key0) * (frame1 - frame0) / (frame0 - frameBefore)`, and the same
on the far side. Rotations are always spherically interpolated the short way round (`0x0071CAB0`).
A frame past the last key holds it.
"""

from __future__ import annotations

import copy
import math
from collections.abc import MutableSequence, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from sage_map.assets.camera_animation_list import (
    CameraAnimation,
    FreeCameraAnimationCameraFrame,
    FreeCameraAnimationFrameData,
    LookAtCameraAnimationCameraFrame,
    LookAtCameraAnimationFrameData,
    LookAtCameraAnimationLookAtFrame,
)
from sage_map.assets.named_cameras import NamedCamera
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, SetAttribute
from sage_worldbuilder.commands.edits import InsertItem, RemoveItem

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "CAMERAS",
    "CAMERA_FORWARD",
    "CAMERA_UP",
    "FREE",
    "LINEAR",
    "LOOK",
    "SPLINE",
    "CameraView",
    "Pose",
    "SetKey",
    "add_animation",
    "add_named_camera",
    "animation_length_error",
    "copy_animation",
    "delete_key",
    "evaluate",
    "focal_length",
    "fov_from_focal",
    "look_rotation",
    "named_camera_from_view",
    "named_camera_view",
    "new_animation",
    "new_animation_name",
    "new_camera_name",
    "pose_axes",
    "pose_view",
    "remove_animation",
    "remove_named_camera",
    "rotation_angles",
    "rotation_for",
    "set_camera_key",
    "set_look_at_key",
    "turned",
]

CAMERAS = Change(ChangeKind.CAMERAS)
FREE, LOOK = "free", "look"
SPLINE, LINEAR = "catm", "line"
ANIMATION_NAMES = {FREE: "Free Animation", LOOK: "Look-at Animation"}
# The field of view and undecoded float most corpus named cameras store.
NAMED_FOV = math.radians(50.0)
NAMED_UNKNOWN = 100.0
# The height a named camera's zoom multiplies when the map stores no maximum camera height.
DEFAULT_CAMERA_HEIGHT = 800.0
# The frame height in millimetres the Camera Animations dialog's focal lengths are read on: 24, a
# 35mm frame, on which its default 25.734mm is a 50-degree field of view exactly.
FRAME_HEIGHT = 24.0
# A free key's rotation turns these camera axes into world axes: on the corpus's 385 free keys
# camera +Y points up on 364, -Z down on 276 (cameras look down) and X stays level on 306.
CAMERA_FORWARD = (0.0, 0.0, -1.0)
CAMERA_UP = (0.0, 1.0, 0.0)

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]


@dataclass(frozen=True)
class CameraView:
    """A 3D view camera: target, yaw and pitch in degrees (as `camera.Camera`), distance from the
    target, and vertical field of view in degrees."""

    target: Vec3
    yaw: float
    pitch: float
    distance: float
    fov: float

    @property
    def forward(self) -> np.ndarray:
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        return np.array(
            (math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), -math.sin(pitch))
        )

    @property
    def eye(self) -> Vec3:
        eye = np.asarray(self.target) - self.distance * self.forward
        return (float(eye[0]), float(eye[1]), float(eye[2]))


@dataclass(frozen=True)
class Pose:
    """Where an animation puts the camera at a frame: its position, what it looks at (a look-at
    animation) or its rotation (a free one), its roll and its field of view, in radians."""

    position: Vec3
    target: Vec3 | None
    rotation: Quat | None
    roll: float
    fov: float


def _camera_height(map: Map) -> float:
    info = map.world_info
    stored = (getattr(info, "properties", None) or {}).get("cameraMaxHeight")
    try:
        height = float(stored["value"]) if stored is not None else 0.0
    except (TypeError, ValueError):
        height = 0.0
    return height if height > 0 else DEFAULT_CAMERA_HEIGHT


def _cameras(map: Map) -> list[NamedCamera]:
    return map.named_cameras.cameras if map.named_cameras is not None else []


def new_camera_name(map: Map) -> str:
    taken = {camera.name.lower() for camera in _cameras(map)}
    number = 1
    while f"camera {number}" in taken:
        number += 1
    return f"Camera {number}"


def named_camera_from_view(map: Map, name: str, view: CameraView) -> NamedCamera:
    """A named camera looking as a 3D view does; the look-at point stands on height 0, as on every
    corpus camera."""
    pitch = math.radians(view.pitch)
    height = view.distance * max(math.sin(pitch), 1e-3)
    return NamedCamera(
        look_at_point=(float(view.target[0]), float(view.target[1]), 0.0),
        name=name,
        pitch=pitch,
        roll=0.0,
        yaw=math.radians(view.yaw),
        zoom=height / _camera_height(map),
        fov=math.radians(view.fov),
        unknown=NAMED_UNKNOWN,
    )


def named_camera_view(map: Map, camera: NamedCamera) -> CameraView:
    pitch = min(90.0, max(1.0, math.degrees(camera.pitch)))
    height = max(camera.zoom, 1e-3) * _camera_height(map)
    return CameraView(
        target=tuple(float(v) for v in camera.look_at_point),  # type: ignore[arg-type]
        yaw=math.degrees(camera.yaw) % 360.0,
        pitch=pitch,
        distance=height / math.sin(math.radians(pitch)),
        fov=math.degrees(camera.fov) if camera.fov > 0 else 50.0,
    )


def add_named_camera(map: Map, camera: NamedCamera) -> Command:
    if map.named_cameras is None:
        raise ValueError("the map has no named cameras chunk")
    listed = map.named_cameras.cameras
    return InsertItem(listed, len(listed), camera, CAMERAS, "New Named Camera")


def remove_named_camera(map: Map, camera: NamedCamera) -> Command:
    listed = _cameras(map)
    index = next((i for i, each in enumerate(listed) if each is camera), None)
    if index is None:
        raise ValueError("the camera is not on the map")
    return RemoveItem(listed, index, CAMERAS, "Delete Named Camera")


def _animations(map: Map) -> list[CameraAnimation]:
    listed = map.camera_animation_list
    return listed.animations if listed is not None else []


def new_animation_name(map: Map, kind: str, base: str | None = None) -> str:
    """`Free Animation` / `Look-at Animation` (or `base`), then `<name> 1`, `<name> 2`, ... for
    the first not taken."""
    base = base or ANIMATION_NAMES[kind]
    taken = {animation.name.lower() for animation in _animations(map)}
    if base.lower() not in taken:
        return base
    number = 1
    while f"{base} {number}".lower() in taken:
        number += 1
    return f"{base} {number}"


def new_animation(map: Map, kind: str, pose: Pose) -> CameraAnimation:
    """A one-frame animation keyed at frame 0 with the pose."""
    if kind == FREE:
        rotation = pose.rotation if pose.rotation is not None else (0.0, 0.0, 0.0, 1.0)
        frame_data: Any = FreeCameraAnimationFrameData(
            [FreeCameraAnimationCameraFrame(0, SPLINE, pose.position, rotation, pose.fov)]
        )
    else:
        target = pose.target if pose.target is not None else pose.position
        frame_data = LookAtCameraAnimationFrameData(
            [LookAtCameraAnimationCameraFrame(0, SPLINE, pose.position, pose.roll, pose.fov)],
            [LookAtCameraAnimationLookAtFrame(0, SPLINE, target)],
        )
    return CameraAnimation(kind, new_animation_name(map, kind), 1, 0, frame_data)


def add_animation(
    map: Map, animation: CameraAnimation, label: str = "Add Camera Animation"
) -> Command:
    if map.camera_animation_list is None:
        raise ValueError("the map has no camera animation list")
    listed = map.camera_animation_list.animations
    return InsertItem(listed, len(listed), animation, CAMERAS, label)


def copy_animation(map: Map, animation: CameraAnimation) -> CameraAnimation:
    copied = copy.deepcopy(animation)
    copied.name = new_animation_name(map, animation.animation_type, animation.name)
    return copied


def remove_animation(map: Map, animation: CameraAnimation) -> Command:
    listed = _animations(map)
    index = next((i for i, each in enumerate(listed) if each is animation), None)
    if index is None:
        raise ValueError("the animation is not on the map")
    return RemoveItem(listed, index, CAMERAS, "Remove Camera Animation")


def camera_keys(animation: CameraAnimation) -> list[Any]:
    data = animation.frame_data
    return data.frames if isinstance(data, FreeCameraAnimationFrameData) else data.camera_frames


def look_at_keys(animation: CameraAnimation) -> list[LookAtCameraAnimationLookAtFrame]:
    data = animation.frame_data
    return data.look_at_frames if isinstance(data, LookAtCameraAnimationFrameData) else []


def animation_length_error(animation: CameraAnimation, frames: int) -> str | None:
    """Why an animation cannot be `frames` long, or None when it can."""
    if frames < 1:
        return "An animation is at least one frame long."
    last = max(
        (key.frame_index for key in [*camera_keys(animation), *look_at_keys(animation)]), default=0
    )
    if frames <= last:
        return f"The animation has a key at frame {last}."
    return None


class SetKey(Command):
    """Put a key into a track at its frame: replacing the key there, or inserted in frame order."""

    def __init__(self, track: MutableSequence[Any], key: Any, label: str = "Set Key") -> None:
        self.track = track
        self.key = key
        self.label = label
        self._index = 0
        self._replaced: Any = None

    def do(self, document: MapDocument) -> None:
        frame = self.key.frame_index
        self._replaced = None
        for index, existing in enumerate(self.track):
            if existing.frame_index == frame:
                self._index, self._replaced = index, existing
                self.track[index] = self.key
                return
            if existing.frame_index > frame:
                self._index = index
                self.track.insert(index, self.key)
                return
        self._index = len(self.track)
        self.track.append(self.key)

    def undo(self, document: MapDocument) -> None:
        if self._replaced is not None:
            self.track[self._index] = self._replaced
        else:
            del self.track[self._index]

    def changes(self) -> tuple[Change, ...]:
        return (CAMERAS,)


def _interpolation_at(track: Sequence[Any], frame: int) -> str:
    before = [key for key in track if key.frame_index <= frame]
    return before[-1].interpolation_type if before else SPLINE


def set_camera_key(animation: CameraAnimation, frame: int, pose: Pose) -> Command:
    """Key the animation's camera at a frame from a pose, keeping the interpolation of the key
    it replaces or of the segment it falls in."""
    track = camera_keys(animation)
    method = _interpolation_at(track, frame)
    if animation.animation_type == FREE:
        rotation = pose.rotation if pose.rotation is not None else (0.0, 0.0, 0.0, 1.0)
        key: Any = FreeCameraAnimationCameraFrame(frame, method, pose.position, rotation, pose.fov)
    else:
        key = LookAtCameraAnimationCameraFrame(frame, method, pose.position, pose.roll, pose.fov)
    return SetKey(track, key, "Set Camera Key")


def set_look_at_key(animation: CameraAnimation, frame: int, point: Vec3) -> Command:
    track = look_at_keys(animation)
    key = LookAtCameraAnimationLookAtFrame(frame, _interpolation_at(track, frame), point)
    return SetKey(track, key, "Set Look-at Key")


def delete_key(track: MutableSequence[Any], frame: int) -> Command:
    """Remove the key at a frame. The key at frame 0 stays: every corpus track starts with one."""
    if frame == 0:
        raise ValueError("the key at frame 0 cannot be removed")
    index = next((i for i, key in enumerate(track) if key.frame_index == frame), None)
    if index is None:
        raise ValueError(f"no key at frame {frame}")
    return RemoveItem(track, index, CAMERAS, "Delete Key")


def set_interpolation(key: Any, method: str) -> Command:
    return SetAttribute(key, "interpolation_type", method, CAMERAS, "Set Interpolation")


def _catmull_rom(
    p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, t: float
) -> np.ndarray:
    return 0.5 * (
        (3 * p1 - p0 - 3 * p2 + p3) * t**3
        + (4 * p2 + 2 * p0 - 5 * p1 - p3) * t**2
        + (p2 - p0) * t
        + 2 * p1
    )


def _slerp(q0: np.ndarray, q1: np.ndarray, t: float) -> np.ndarray:
    dot = float(q0 @ q1)
    flip = dot < 0
    if flip:
        dot = -dot
    if 1 - dot >= 1e-4:
        angle = math.acos(min(dot, 1.0))
        scale = 1 / math.sin(angle)
        w0, w1 = math.sin(angle - angle * t) * scale, math.sin(angle * t) * scale
    else:
        w0, w1 = 1 - t, t
    if flip:
        w1 = -w1
    return w0 * q0 + w1 * q1


def _track_value(
    track: Sequence[Any], frame: float, value: Any, rotation: bool = False
) -> np.ndarray:
    """A track's value at a frame, as `doInterpolate` gives it."""
    values = [np.asarray(value(key), dtype=np.float64) for key in track]
    frames = [key.frame_index for key in track]
    at = sum(1 for f in frames if f <= frame) - 1
    if at < 0:
        return values[0]
    if at >= len(track) - 1:
        return values[-1]
    before, after = max(at - 1, 0), min(at + 2, len(track) - 1)
    f0, f1 = frames[at], frames[at + 1]
    t = (frame - f0) / (f1 - f0)
    p0, p1 = values[at], values[at + 1]
    if rotation:
        return _slerp(p0, p1, t)
    if track[at].interpolation_type == LINEAR:
        return (1 - t) * p0 + t * p1
    span = f1 - f0
    gap = f0 - frames[before]
    lead = p0 + (values[before] - p0) * span / gap if gap > 0 else values[before]
    gap = frames[after] - f1
    tail = p1 + (values[after] - p1) * span / gap if gap > 0 else values[after]
    return _catmull_rom(lead, p0, p1, tail, t)


def _vec(array: np.ndarray) -> Vec3:
    return (float(array[0]), float(array[1]), float(array[2]))


def evaluate(animation: CameraAnimation, frame: float) -> Pose | None:
    """The camera's pose at a frame, or None for an animation without keys."""
    track = camera_keys(animation)
    if not track:
        return None
    position = _vec(_track_value(track, frame, lambda key: key.position))
    fov = float(_track_value(track, frame, lambda key: key.fov))
    if animation.animation_type == FREE:
        q = _track_value(track, frame, lambda key: key.rotation, rotation=True)
        q = q / (np.linalg.norm(q) or 1.0)
        return Pose(position, None, (float(q[0]), float(q[1]), float(q[2]), float(q[3])), 0.0, fov)
    roll = float(_track_value(track, frame, lambda key: key.roll))
    looks = look_at_keys(animation)
    target = _vec(_track_value(looks, frame, lambda key: key.look_at_point)) if looks else None
    return Pose(position, target, None, roll, fov)


def _rotate(q: Sequence[float], vector: Sequence[float] | np.ndarray) -> np.ndarray:
    x, y, z, w = q
    axis = np.array((x, y, z))
    v = np.asarray(vector, dtype=np.float64)
    return v + 2 * np.cross(axis, np.cross(axis, v) + w * v)


def look_rotation(
    forward: Sequence[float] | np.ndarray, up: Sequence[float] | np.ndarray = (0.0, 0.0, 1.0)
) -> Quat:
    """The unit quaternion turning `CAMERA_FORWARD` to `forward` and `CAMERA_UP` towards `up`."""
    f = np.asarray(forward, dtype=np.float64)
    f /= np.linalg.norm(f)
    right = np.cross(f, np.asarray(up, dtype=np.float64))
    if np.linalg.norm(right) < 1e-9:
        right = np.cross(f, (0.0, 1.0, 0.0))
    right /= np.linalg.norm(right)
    true_up = np.cross(right, f)
    camera = np.column_stack(
        (np.cross(CAMERA_UP, np.negative(CAMERA_FORWARD)), CAMERA_UP, np.negative(CAMERA_FORWARD))
    )
    world = np.column_stack((right, true_up, -f))
    matrix = world @ camera.T
    trace = np.trace(matrix)
    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (matrix[2, 1] - matrix[1, 2]) * s
        y = (matrix[0, 2] - matrix[2, 0]) * s
        z = (matrix[1, 0] - matrix[0, 1]) * s
    else:
        i = int(np.argmax(np.diag(matrix)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(max(matrix[i, i] - matrix[j, j] - matrix[k, k] + 1.0, 1e-12))
        quat = [0.0, 0.0, 0.0]
        quat[i] = 0.5 * s
        s = 0.5 / s
        w = (matrix[k, j] - matrix[j, k]) * s
        quat[j] = (matrix[j, i] + matrix[i, j]) * s
        quat[k] = (matrix[k, i] + matrix[i, k]) * s
        x, y, z = quat
    q = np.array((x, y, z, w))
    q /= np.linalg.norm(q)
    return (float(q[0]), float(q[1]), float(q[2]), float(q[3]))


def pose_view(pose: Pose, ground: float = 0.0) -> CameraView:
    """A 3D view camera showing a pose: from its position towards its look-at point, or along its
    rotation's forward axis to where that meets the height `ground` (at most 5,000 units on)."""
    eye = np.asarray(pose.position, dtype=np.float64)
    if pose.target is not None:
        offset = np.asarray(pose.target, dtype=np.float64) - eye
        distance = float(np.linalg.norm(offset)) or 1.0
        forward = offset / distance
    else:
        rotation = pose.rotation if pose.rotation is not None else (0.0, 0.0, 0.0, 1.0)
        forward = _rotate(rotation, CAMERA_FORWARD)
        forward /= np.linalg.norm(forward)
        down = -forward[2]
        distance = (eye[2] - ground) / down if down > 1e-3 else 5000.0
        distance = min(max(distance, 20.0), 5000.0)
    target = eye + forward * distance
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -forward[2]))))
    yaw = math.degrees(math.atan2(forward[0], forward[1])) % 360.0
    return CameraView(_vec(target), yaw, pitch, distance, math.degrees(pose.fov))


def view_pose(view: CameraView) -> Pose:
    """The pose of a 3D view camera, with both what it looks at and its rotation."""
    return Pose(
        view.eye,
        view.target,
        look_rotation(view.forward),
        0.0,
        math.radians(view.fov),
    )


def focal_length(fov: float) -> float:
    """A vertical field of view in radians as the lens focal length in millimetres the Camera
    Animations dialog shows."""
    return FRAME_HEIGHT / 2 / math.tan(max(fov, 1e-4) / 2)


def fov_from_focal(millimetres: float) -> float:
    """The vertical field of view in radians a focal length gives."""
    return 2 * math.atan(FRAME_HEIGHT / 2 / max(millimetres, 1e-4))


def pose_axes(pose: Pose) -> tuple[np.ndarray, np.ndarray]:
    """Where a pose looks and which way is up for it, as unit vectors: along its rotation for a
    free pose, towards its look-at point for a look-at one, rolled by its roll."""
    if pose.rotation is not None:
        forward = _rotate(pose.rotation, CAMERA_FORWARD)
        up = _rotate(pose.rotation, CAMERA_UP)
    else:
        target = pose.target if pose.target is not None else (0.0, 0.0, 0.0)
        forward = np.asarray(target, dtype=np.float64) - np.asarray(pose.position)
        if np.linalg.norm(forward) < 1e-9:
            forward = np.array((0.0, 1.0, 0.0))
        up = _rotate(look_rotation(forward), CAMERA_UP)
    forward = forward / (np.linalg.norm(forward) or 1.0)
    up = up / (np.linalg.norm(up) or 1.0)
    if pose.roll:
        up = _rotate(turned((0.0, 0.0, 0.0, 1.0), forward, pose.roll), up)
    # Square up: the roll and the stored rotation both leave a little drift.
    up = up - forward * float(up @ forward)
    return forward, up / (np.linalg.norm(up) or 1.0)


def turned(rotation: Quat, axis: Sequence[float] | np.ndarray, angle: float) -> Quat:
    """`rotation` turned a further `angle` radians about a world axis."""
    unit = np.asarray(axis, dtype=np.float64)
    unit = unit / (np.linalg.norm(unit) or 1.0)
    half = angle / 2
    x, y, z = unit * math.sin(half)
    turn = np.array((x, y, z, math.cos(half)))
    q = np.asarray(rotation, dtype=np.float64)
    # Hamilton product `turn * q`: the turn is about a world axis, so it goes on the left.
    product = np.array(
        (
            turn[3] * q[0] + turn[0] * q[3] + turn[1] * q[2] - turn[2] * q[1],
            turn[3] * q[1] - turn[0] * q[2] + turn[1] * q[3] + turn[2] * q[0],
            turn[3] * q[2] + turn[0] * q[1] - turn[1] * q[0] + turn[2] * q[3],
            turn[3] * q[3] - turn[0] * q[0] - turn[1] * q[1] - turn[2] * q[2],
        )
    )
    product /= np.linalg.norm(product) or 1.0
    return (float(product[0]), float(product[1]), float(product[2]), float(product[3]))


def rotation_angles(rotation: Quat) -> tuple[float, float, float]:
    """A free key's rotation as the yaw, pitch and roll in radians the Camera Animations dialog
    shows: where it looks (yaw 0 north, pitch positive downwards) and how far it is rolled from
    level about that."""
    forward = _rotate(rotation, CAMERA_FORWARD)
    forward = forward / (np.linalg.norm(forward) or 1.0)
    up = _rotate(rotation, CAMERA_UP)
    yaw = math.atan2(forward[0], forward[1])
    pitch = math.asin(max(-1.0, min(1.0, -forward[2])))
    level = _rotate(look_rotation(forward), CAMERA_UP)
    roll = math.atan2(float(np.cross(level, up) @ forward), float(level @ up))
    return yaw, pitch, roll


def rotation_for(yaw: float, pitch: float, roll: float) -> Quat:
    """The rotation a free key stores for a yaw, pitch and roll in radians."""
    forward = (
        math.sin(yaw) * math.cos(pitch),
        math.cos(yaw) * math.cos(pitch),
        -math.sin(pitch),
    )
    return turned(look_rotation(forward), forward, roll)
