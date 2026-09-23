"""`ViewLocation` - where the camera is looking, as the engine's own bookmarks record it.

The camera is client state: no logic reads it and it never enters the message stream, so moving it
cannot desync a game, costs no APM and needs no selection. `ViewLocation` is the 32-byte structure
`View::getLocation` fills and `View::setLocation` reads.

A captured location does not round-trip: each scalar is read from one field and written to another,
and `setLocation` writes all four, visibly disturbing the zoom. So re-aim with `Session.look_at`
(which writes the view's position directly), and use this for reading the camera or restoring a
whole saved placement. `position` is the look-at point on the terrain, not the camera's eye.
Details: `sage_patch/docs/camera-control.md`.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, replace
from typing import Protocol

from sage_live.api.observation import Vec3

__all__ = ["CameraPan", "ViewLocation"]


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
