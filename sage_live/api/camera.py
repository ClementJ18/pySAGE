"""`ViewLocation` - where the camera is looking, as the engine's own bookmarks record it.

The camera is **client state**. No logic reads it, no order carries it and nothing about it
enters the message stream, so moving it cannot desync a game or change what a policy is
allowed to see. That also means it is not an action: a camera move costs no APM, needs no
selection, and there is nothing for `confirm_*` to watch except the camera itself.

This is the exact 32-byte structure `View::getLocation` fills and `View::setLocation` reads -
the same one the camera-bookmark hotkeys save and restore.

**A captured location does not round-trip, and re-aiming must not go through one.** Every
scalar is read from one field and written to another - `zoom` from `+0x124` to `+0x128`,
`angle` from `+0x100` to `+0xFC`, and so on - so they are not the same quantity, and
`setLocation` writes all four whether or not a caller wanted them touched. Measured against a
running match: handing back a location captured a moment earlier moved the live zoom from
1.281116 to 1.234136, after which the client restored it over about 0.6 seconds. Every other
value asked for was refused the same way, the reported one included. A policy re-aiming the
camera each cycle therefore zoomed in and was snapped out again, forever, and no choice of
numbers avoided it. `Session.look_at` writes the view's position field directly instead; this
structure is for reading the camera, and for putting a whole saved placement back.

**Three of the four scalars are named from evidence, and one is not.** `angle` is the field
the keyboard rotate keys step by `KeyboardCameraRotateSpeed`; `zoom` is the one a camera reset
sets to `1.0`; `pitch` is its neighbour, driven by the other axis of the same mouse drag that
drives `angle`. The fourth has no other reader or writer anywhere in the image, so it is
carried unnamed and unaltered - see `extra`.

`position` is the look-at point **on the terrain**, not the camera's eye: measured live, a
camera reporting `z=150.00` sat over 137 objects whose median `z` was `150.00`. The camera's
own altitude is derived from this point, the zoom and the pitch, and is not in this struct at
all - so "keep the camera's height" is not a thing a caller can do by preserving this Z.
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

    `valid` is the engine's own flag and it is load-bearing in one direction: `setLocation`
    returns immediately on a location whose flag is clear, so a cleared one is a camera move
    that is accepted, does nothing, and reports nothing.
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


# How often the pan writes, and how quickly it closes on its target. The rate is not a frame
# rate to match - the client samples the position field on its own schedule, and a write is
# twelve bytes with no acknowledgement to wait for, so this only has to be comfortably faster
# than the client renders. Measured live, a loop asking for 6ms achieved 162 writes a second
# with a p95 gap of 7ms, and that read as a smooth pan; a quarter-second step did not.
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
    """Eases the camera toward a target on its own clock.

    **Why this is a thread and not a call.** A policy decides what is worth watching every
    couple of seconds; a pan has to move every few milliseconds. Easing one step per decision
    is a jump every two seconds, which is what a viewer calls snapping. Splitting the two lets
    the policy say *where* at its own pace and this say *how* at the client's.

    Safe to run alongside everything else because of what it writes: the camera is client
    state, no logic reads it, and `look_at` reaches the view's position field directly without
    the bridge's command slot - so this shares no handshake with orders and cannot delay one.

    **It stops writing once it arrives**, which is what leaves the keyboard usable: a settled
    pan is silent, so a human can take the camera back until the next `aim`.
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
