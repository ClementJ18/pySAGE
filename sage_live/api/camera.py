"""`ViewLocation` - where the camera is looking, as the engine's own bookmarks record it.

The camera is client state: no logic reads it and it never enters the message stream, so moving it
cannot desync a game, costs no APM and needs no selection. `ViewLocation` is the 32-byte structure
`View::getLocation` fills and `View::setLocation` reads.

A captured location does not round-trip: each scalar is read from one field and written to another,
and `setLocation` writes all four, visibly disturbing the zoom. So re-aim with `Session.look_at`
(which writes the view's position directly), and use this for reading the camera or restoring a
whole saved placement. `position` is the look-at point on the terrain, not the camera's eye.
Details: `sage_patch/docs/camera-control.md`.

`CameraView` - what the camera sees. A `ViewLocation` says where the camera aims but not how much
of the world fits on screen; that is the 3D camera the view draws through, its transform and view
plane, read as they are. It answers whether a world point is on the local client's screen and
where, and which ground the screen covers.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, replace
from typing import Protocol

from sage_live.api.observation import Vec3

__all__ = ["CameraPan", "CameraView", "ViewLocation"]

# A rectangle as the camera stores one: min x, min y, max x, max y.
Rect = tuple[float, float, float, float]
# A rigid transform as three rows of (x, y, z, translation).
Rows = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


@dataclass(frozen=True)
class ViewLocation:
    """A camera placement: where it is, which way it faces, and how far out it is zoomed.

    `setLocation` ignores a location whose `valid` flag is clear, silently.
    """

    position: Vec3 = (0.0, 0.0, 0.0)
    # Yaw, in radians. The keyboard rotate keys add `TheWritableGlobalData`'s
    # `KeyboardCameraRotateSpeed` to this field each frame they are held.
    angle: float = 0.0
    # Tilt, in radians. Driven by the vertical axis of the same drag whose horizontal axis
    # drives `angle`, at one hundredth of a radian per pixel.
    pitch: float = 0.0
    # A multiplier, not a distance: the engine's own camera reset writes `1.0` here, and a
    # scripted pull-back writes `2.2`. The map's own camera limits still clamp it - and the
    # field written is not the field read, so a value captured here cannot be written back. See
    # the module docstring; this is why re-aiming does not use this structure.
    zoom: float = 1.0
    # The fourth scalar `getLocation` records. Its accessor pair is called from nowhere else
    # in the image, so what it means is unestablished - it is carried so that a captured
    # location can be handed straight back unchanged.
    extra: float = 0.0
    valid: bool = True

    def looking_at(self, position: Vec3) -> ViewLocation:
        """This same camera, re-aimed at `position`. Everything else is kept."""
        return replace(self, position=position)


@dataclass(frozen=True)
class CameraView:
    """The 3D camera the world is drawn through, enough to say what is on screen.

    Screen positions are fractions of the client area, (0, 0) top-left to (1, 1) bottom-right, so
    they hold at any resolution. The transform is rigid, which is what lets a world point be taken
    into camera space with its transpose rather than a general inverse.
    """

    # Camera space to world. The camera looks down its own -Z, with +X right and +Y up.
    transform: Rows
    # The view plane at distance one: `±tan(fov / 2)` for a perspective camera, world units for
    # an orthographic one.
    view_plane: Rect
    near: float
    far: float
    # The part of the screen drawn into, as fractions; the whole of it in a match.
    viewport: Rect = (0.0, 0.0, 1.0, 1.0)
    orthographic: bool = False

    @property
    def eye(self) -> Vec3:
        """Where the camera is, in world units."""
        return (self.transform[0][3], self.transform[1][3], self.transform[2][3])

    @property
    def forward(self) -> Vec3:
        """The unit direction the camera looks in, in world space."""
        return (-self.transform[0][2], -self.transform[1][2], -self.transform[2][2])

    def to_camera(self, point: Vec3) -> Vec3:
        """`point` in camera space: +X right, +Y up, and -Z its distance in front."""
        eye = self.eye
        d = (point[0] - eye[0], point[1] - eye[1], point[2] - eye[2])
        rows = self.transform
        return (
            rows[0][0] * d[0] + rows[1][0] * d[1] + rows[2][0] * d[2],
            rows[0][1] * d[0] + rows[1][1] * d[1] + rows[2][1] * d[2],
            rows[0][2] * d[0] + rows[1][2] * d[1] + rows[2][2] * d[2],
        )

    def project(self, point: Vec3) -> tuple[float, float] | None:
        """Where `point` falls on screen, or None when it is behind the camera or outside the clip
        distances. Off to the side still answers, with a fraction outside 0..1, so a caller can
        tell "just off screen" from "far away"."""
        x, y, z = self.to_camera(point)
        depth = -z
        if not self.near <= depth <= self.far:
            return None
        if not self.orthographic:
            x, y = x / depth, y / depth
        min_x, min_y, max_x, max_y = self.view_plane
        across = (x - min_x) / (max_x - min_x)
        down = (max_y - y) / (max_y - min_y)
        left, top, right, bottom = self.viewport
        return (left + across * (right - left), top + down * (bottom - top))

    def sees(self, point: Vec3, margin: float = 0.0) -> bool:
        """Whether `point` is on screen. `margin`, as a fraction of the screen, widens the test
        on every side when positive and narrows it when negative."""
        at = self.project(point)
        if at is None:
            return False
        return -margin <= at[0] <= 1.0 + margin and -margin <= at[1] <= 1.0 + margin

    def ground_footprint(self, height: float = 0.0) -> tuple[tuple[float, float], ...]:
        """The ground the screen covers: its four corners cast onto the plane at `height`, in the
        order top-left, top-right, bottom-right, bottom-left.

        A corner looking above the horizon, or reaching the plane only beyond the far clip, stops
        at the far clip instead, so a tilted view gives a finite shape rather than none. The plane
        is flat; on hilly ground use `sees` with each point's own height.
        """
        min_x, min_y, max_x, max_y = self.view_plane
        corners = []
        for plane_x, plane_y in ((min_x, max_y), (max_x, max_y), (max_x, min_y), (min_x, min_y)):
            if self.orthographic:
                origin = self._to_world((plane_x, plane_y, 0.0))
                ray = self._rotate((0.0, 0.0, -1.0))
            else:
                origin = self.eye
                ray = self._rotate((plane_x, plane_y, -1.0))
            # Either ray advances one unit of depth per unit of `t`, so `t` compares with `far`.
            t = self.far
            if ray[2] < 0.0:
                t = max(0.0, min(t, (height - origin[2]) / ray[2]))
            corners.append((origin[0] + ray[0] * t, origin[1] + ray[1] * t))
        return tuple(corners)

    def _rotate(self, v: Vec3) -> Vec3:
        rows = self.transform
        return (
            rows[0][0] * v[0] + rows[0][1] * v[1] + rows[0][2] * v[2],
            rows[1][0] * v[0] + rows[1][1] * v[1] + rows[1][2] * v[2],
            rows[2][0] * v[0] + rows[2][1] * v[1] + rows[2][2] * v[2],
        )

    def _to_world(self, v: Vec3) -> Vec3:
        r = self._rotate(v)
        eye = self.eye
        return (r[0] + eye[0], r[1] + eye[1], r[2] + eye[2])


# How often the pan writes, and how quickly it closes on its target. Only needs to be comfortably
# faster than the client renders; about 6 ms read as smooth, a quarter second did not.
PAN_INTERVAL = 0.006
# Time constant, in seconds: the camera closes 63% of its remaining distance in this long. An
# exponential approach rather than a fixed fraction per tick, so the pan looks the same however
# the tick rate wanders - which on Windows it does.
PAN_TAU = 0.45
# Beyond this the pan is a cut. Easing across half a map drifts through empty ground for
# seconds and reads as a fault rather than a camera move.
PAN_CUT = 900.0
# Closer than this to the target, stop writing. Without it the loop rewrites a camera that has
# arrived, forever, which pins the view against anyone at the keyboard and wastes the writes.
PAN_SETTLED = 1.0


class _Aimable(Protocol):
    """The one thing a pan needs from a session, kept structural to avoid importing it."""

    def look_at(self, position: Vec3) -> bool: ...


class CameraPan:
    """Eases the camera toward a target on its own thread.

    A policy decides where to look every couple of seconds, but a smooth pan moves every few
    milliseconds, so the two run separately. It writes only the view's position field (no bridge
    command), so it cannot delay an order. It stops writing once it arrives, leaving the keyboard to
    the player until the next `aim`.
    """

    def __init__(
        self,
        session: _Aimable,
        interval: float = PAN_INTERVAL,
        tau: float = PAN_TAU,
        cut: float = PAN_CUT,
    ) -> None:
        self._session = session
        self._interval = interval
        self._tau = tau
        self._cut = cut
        self._lock = threading.Lock()
        self._target: Vec3 | None = None
        self._at: Vec3 | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def aim(self, position: Vec3) -> None:
        """Ask for the camera to end up at `position`. Cheap, and safe from any thread."""
        with self._lock:
            self._target = position

    @property
    def at(self) -> Vec3 | None:
        """Where the pan believes the camera is, or None before it has moved it."""
        with self._lock:
            return self._at

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera-pan", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)

    def __enter__(self) -> CameraPan:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def _run(self) -> None:
        last = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            step, last = now - last, now
            self._advance(step)
            # `Event.wait` rather than `sleep`, so `stop` is immediate rather than up to one
            # interval late - which matters at shutdown far more than the interval suggests,
            # because a daemon thread writing into a closing process is worth not having.
            self._stop.wait(self._interval)

    def _advance(self, step: float) -> None:
        with self._lock:
            target, at = self._target, self._at
        if target is None:
            return
        if at is None or _distance(at, target) > self._cut:
            moved = target  # a cut: nothing to ease from, or too far to ease across
        elif _distance(at, target) <= PAN_SETTLED:
            return
        else:
            # Frame-rate independent: the fraction closed depends on elapsed time, not on how
            # many ticks happened to fit in it.
            moved = _toward(at, target, 1.0 - math.exp(-step / self._tau))
        if self._session.look_at(moved):
            with self._lock:
                self._at = moved


def _distance(here: Vec3, there: Vec3) -> float:
    return math.dist(here[:2], there[:2])


def _toward(here: Vec3, there: Vec3, fraction: float) -> Vec3:
    return (
        here[0] + (there[0] - here[0]) * fraction,
        here[1] + (there[1] - here[1]) * fraction,
        here[2] + (there[2] - here[2]) * fraction,
    )
