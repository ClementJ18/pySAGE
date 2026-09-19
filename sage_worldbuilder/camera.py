"""The 3D view's camera: where it looks from, and the conversions between world positions and
widget pixels it gives.

World axes are the map's: x east, y north (up in the top-down view), z up, all in world units. The
camera orbits a target point: `yaw` turns it about the vertical (0 looks north, 90 east), `pitch`
is how far below the horizon it looks (90 straight down), and `distance` is how far back from the
target it stands. Pure numpy and floats, so tools and tests use it without a GL context.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

__all__ = [
    "FIELD_OF_VIEW",
    "MAX_DISTANCE",
    "MAX_PITCH",
    "MIN_DISTANCE",
    "MIN_PITCH",
    "Camera",
    "Projector",
    "pose_matrix",
]

# Vertical field of view in degrees: a choice until the game camera's focal length is read.
FIELD_OF_VIEW = 45.0
MIN_PITCH = 5.0
MAX_PITCH = 90.0
MIN_DISTANCE = 20.0
MAX_DISTANCE = 40000.0
# Degrees the camera turns per pixel dragged.
ORBIT_DEGREES_PER_PIXEL = 0.4

# A world point `(x, y, z)` to widget pixels, or None when it is not in front of the camera.
Projector = Callable[[float, float, float], "tuple[float, float] | None"]


@dataclass
class Camera:
    target_x: float = 0.0
    target_y: float = 0.0
    target_z: float = 0.0
    yaw: float = 0.0
    pitch: float = 50.0
    distance: float = 1500.0
    width: int = 1
    height: int = 1
    fov: float = FIELD_OF_VIEW

    @property
    def target(self) -> np.ndarray:
        return np.array((self.target_x, self.target_y, self.target_z))

    def basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The camera's right, up and forward unit vectors, in world axes."""
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        forward = np.array(
            (
                math.sin(yaw) * math.cos(pitch),
                math.cos(yaw) * math.cos(pitch),
                -math.sin(pitch),
            )
        )
        right = np.array((math.cos(yaw), -math.sin(yaw), 0.0))
        return right, np.cross(right, forward), forward

    @property
    def eye(self) -> np.ndarray:
        return self.target - self.distance * self.basis()[2]

    def clip_planes(self) -> tuple[float, float]:
        near = max(self.distance * 0.02, 1.0)
        return near, self.distance * 4.0 + 20000.0

    def focal_pixels(self) -> float:
        """Pixels a world unit spans one world unit in front of the camera."""
        return self.height / (2 * math.tan(math.radians(self.fov) / 2))

    def view_matrix(self) -> np.ndarray:
        right, up, forward = self.basis()
        eye = self.eye
        view = np.eye(4)
        view[0, :3], view[0, 3] = right, -right @ eye
        view[1, :3], view[1, 3] = up, -up @ eye
        view[2, :3], view[2, 3] = -forward, forward @ eye
        return view

    def projection_matrix(self) -> np.ndarray:
        near, far = self.clip_planes()
        focal = 1.0 / math.tan(math.radians(self.fov) / 2)
        projection = np.zeros((4, 4))
        projection[0, 0] = focal * self.height / max(self.width, 1)
        projection[1, 1] = focal
        projection[2, 2] = (far + near) / (near - far)
        projection[2, 3] = 2 * far * near / (near - far)
        projection[3, 2] = -1.0
        return projection

    def matrix(self) -> np.ndarray:
        """World to clip space, row-major."""
        return self.projection_matrix() @ self.view_matrix()

    def project(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Widget pixels `(N, 2)` for world points `(N, 3)`, and which of them are in front of
        the near plane (the others' pixels mean nothing)."""
        right, up, forward = self.basis()
        relative = np.asarray(points, dtype=np.float64).reshape(-1, 3) - self.eye
        depth = relative @ forward
        near, _ = self.clip_planes()
        in_front = depth > near
        k = self.focal_pixels() / np.where(in_front, depth, 1.0)
        pixels = np.stack(
            (self.width / 2 + (relative @ right) * k, self.height / 2 - (relative @ up) * k),
            axis=1,
        )
        return pixels, in_front

    def projector(self) -> Projector:
        """`world_to_screen` as plain float arithmetic, for projecting many points one at a time;
        it keeps the camera as it is now."""
        right, up, forward = (tuple(float(v) for v in axis) for axis in self.basis())
        ex, ey, ez = (float(v) for v in self.eye)
        near, _ = self.clip_planes()
        focal = self.focal_pixels()
        cx, cy = self.width / 2, self.height / 2
        rx, ry, rz = right
        ux, uy, uz = up
        fx, fy, fz = forward

        def project(x: float, y: float, z: float) -> tuple[float, float] | None:
            dx, dy, dz = x - ex, y - ey, z - ez
            depth = dx * fx + dy * fy + dz * fz
            if depth <= near:
                return None
            k = focal / depth
            return cx + (dx * rx + dy * ry + dz * rz) * k, cy - (dx * ux + dy * uy + dz * uz) * k

        return project

    def world_to_screen(self, x: float, y: float, z: float) -> tuple[float, float] | None:
        return self.projector()(x, y, z)

    def ray(self, sx: float, sy: float) -> tuple[np.ndarray, np.ndarray]:
        """The eye and the unit direction through widget pixel `(sx, sy)`."""
        right, up, forward = self.basis()
        half = math.tan(math.radians(self.fov) / 2)
        across = (2 * sx / max(self.width, 1) - 1) * half * self.width / max(self.height, 1)
        upward = (1 - 2 * sy / max(self.height, 1)) * half
        direction = forward + right * across + up * upward
        return self.eye, direction / np.linalg.norm(direction)

    def pixels_per_unit_at(self, point: Sequence[float] | np.ndarray) -> float:
        """Pixels a world unit spans at the depth of `point` (at the near plane when closer)."""
        depth = float((np.asarray(point, dtype=np.float64) - self.eye) @ self.basis()[2])
        return self.focal_pixels() / max(depth, self.clip_planes()[0])

    def orbit(self, dx: float, dy: float) -> None:
        """Turn about the target by a drag of `dx`, `dy` pixels: across turns, down looks down."""
        self.yaw = (self.yaw + dx * ORBIT_DEGREES_PER_PIXEL) % 360.0
        self.pitch = min(MAX_PITCH, max(MIN_PITCH, self.pitch + dy * ORBIT_DEGREES_PER_PIXEL))

    def pan(self, dx: float, dy: float) -> None:
        """Slide the target over the ground by a drag of `dx`, `dy` pixels, so the ground follows
        the cursor about the target."""
        units = self.distance / self.focal_pixels()
        yaw = math.radians(self.yaw)
        # A drag down the screen covers more ground the flatter the camera looks.
        along = dy * units / max(math.sin(math.radians(self.pitch)), 0.25)
        self.target_x += -dx * units * math.cos(yaw) + along * math.sin(yaw)
        self.target_y += dx * units * math.sin(yaw) + along * math.cos(yaw)

    def zoom(self, factor: float, anchor: Sequence[float] | None = None) -> None:
        """Move in by `factor` (out below 1), keeping `anchor` under the same pixel."""
        distance = min(MAX_DISTANCE, max(MIN_DISTANCE, self.distance / factor))
        if anchor is not None:
            keep = 1 - distance / self.distance
            self.target_x += (anchor[0] - self.target_x) * keep
            self.target_y += (anchor[1] - self.target_y) * keep
            self.target_z += (anchor[2] - self.target_z) * keep
        self.distance = distance

    def look_at(self, x: float, y: float, z: float) -> None:
        self.target_x, self.target_y, self.target_z = x, y, z

    def fit(self, x0: float, y0: float, x1: float, y1: float, z: float = 0.0) -> None:
        """Aim at the middle of a world rectangle from far enough back to show it whole."""
        self.look_at((x0 + x1) / 2, (y0 + y1) / 2, z)
        half = math.tan(math.radians(self.fov) / 2)
        aspect = max(self.width, 1) / max(self.height, 1)
        needed = max(abs(y1 - y0) / 2, abs(x1 - x0) / 2 / aspect) / half * 1.1
        self.distance = min(MAX_DISTANCE, max(MIN_DISTANCE, needed))


def pose_matrix(
    position: Sequence[float],
    forward: Sequence[float],
    up: Sequence[float],
    fov: float,
    width: int,
    height: int,
    near: float = 1.0,
    far: float = 20000.0,
) -> np.ndarray:
    """World to clip space for a camera standing anywhere and looking any way: the camera preview's
    matrix, where `Camera`'s orbit (no roll, pitch at most straight down) does not reach."""
    eye = np.asarray(position, dtype=np.float64)
    ahead = np.asarray(forward, dtype=np.float64)
    ahead = ahead / (np.linalg.norm(ahead) or 1.0)
    right = np.cross(ahead, np.asarray(up, dtype=np.float64))
    if np.linalg.norm(right) < 1e-9:
        right = np.cross(ahead, (0.0, 0.0, 1.0))
    right = right / (np.linalg.norm(right) or 1.0)
    upward = np.cross(right, ahead)
    view = np.eye(4)
    view[0, :3], view[0, 3] = right, -right @ eye
    view[1, :3], view[1, 3] = upward, -upward @ eye
    view[2, :3], view[2, 3] = -ahead, ahead @ eye
    focal = 1.0 / math.tan(math.radians(fov) / 2)
    far = max(far, near * 2)
    projection = np.zeros((4, 4))
    projection[0, 0] = focal * height / max(width, 1)
    projection[1, 1] = focal
    projection[2, 2] = (far + near) / (near - far)
    projection[2, 3] = 2 * far * near / (near - far)
    projection[3, 2] = -1.0
    return projection @ view
