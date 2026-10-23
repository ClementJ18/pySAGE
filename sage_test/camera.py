"""Keep the camera on something that moves, smoothly.

The test knows where its target is only when it observes, and observing a large match is slow -
long enough that a camera moved between observations freezes, then lurches. So the camera runs on
a thread of its own that does nothing but write the view's look-at point
(`sage_patch/docs/camera-control.md` §6: twelve bytes at `TheTacticalView+0x0C`, no hook, no
acknowledgement, smooth at 160 writes a second). The test thread only says where the target is
(`aim`); the camera thread extrapolates from the last two aims to where the target is *now*, and
eases towards that on the wall clock, so a late update lands where the camera should be rather
than a step behind.

The camera thread writes through its own process handle and never touches the `Session`, so the
two threads share nothing but the aim, behind a lock.

The look-at point is a point **on the terrain**, height included: aim at the target's own z, or
on high ground the view looks at a point under the surface and the target sits off-centre. And
anything else that moves the view - the player scrolling, edge-scroll with the mouse at the window
border - is overwritten on the next write, so leave the mouse alone while it runs.
"""

from __future__ import annotations

import math
import struct
import threading
import time
from collections.abc import Callable

from sage_patch.addresses.ui import THE_TACTICAL_VIEW, VIEW_POSITION_OFFSET

__all__ = ["CameraFollow", "tactical_view_mover"]

Point = tuple[float, float, float]
Mover = Callable[[Point], bool]

#: Camera writes per second: above any frame rate the game draws at.
DEFAULT_RATE = 120.0
#: How long the camera takes to close about two thirds of the gap to the predicted aim. Lower
#: follows tighter and shows every correction; higher is smoother and lags more.
DEFAULT_TIME_CONSTANT = 0.35
#: The longest a prediction is carried past the last aim. A target that stopped is noticed at the
#: next aim anyway; this only keeps a stale velocity from running away.
MAX_EXTRAPOLATION_S = 1.5


def tactical_view_mover(process) -> Mover:
    """A mover that writes the look-at point of the running game's view. `process` is a
    `WindowsProcess` of its own: the camera thread must not share the session's handle.
    `TheTacticalView` is re-read on every write, because each match builds a new one."""

    def move(point: Point) -> bool:
        raw = process.read(THE_TACTICAL_VIEW, 4)
        view = struct.unpack("<I", raw)[0] if raw and len(raw) == 4 else 0
        if not view:
            return False
        return bool(process.write(view + VIEW_POSITION_OFFSET, struct.pack("<fff", *point)))

    return move


class CameraFollow:
    """Follows the last aimed point from a thread of its own while the `with` block runs.

        with CameraFollow(tactical_view_mover(process)) as camera:
            camera.aim(where_the_army_is)
            ...
    """

    def __init__(
        self,
        move: Mover,
        rate: float = DEFAULT_RATE,
        time_constant: float = DEFAULT_TIME_CONSTANT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.move = move
        self.period = 1.0 / rate
        self.time_constant = time_constant
        self.clock = clock
        self.current: Point | None = None
        self.failed_writes = 0
        self._lock = threading.Lock()
        self._aim: Point | None = None
        self._aimed_at = 0.0
        self._velocity = (0.0, 0.0, 0.0)
        self._stepped_at: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def aim(self, point: Point) -> None:
        """Say where the target is now. Safe from any thread."""
        now = self.clock()
        with self._lock:
            if self._aim is not None and now > self._aimed_at:
                dt = now - self._aimed_at
                self._velocity = tuple((p - a) / dt for p, a in zip(point, self._aim, strict=True))
            self._aim, self._aimed_at = point, now

    def predicted(self, now: float) -> Point | None:
        with self._lock:
            if self._aim is None:
                return None
            ahead = min(max(0.0, now - self._aimed_at), MAX_EXTRAPOLATION_S)
            return tuple(a + v * ahead for a, v in zip(self._aim, self._velocity, strict=True))

    def step(self, now: float) -> None:
        """One camera update at time `now`: jump to the first aim, ease towards later ones."""
        target = self.predicted(now)
        if target is None:
            return
        if self.current is None or self._stepped_at is None:
            self.current = target
        else:
            k = 1.0 - math.exp(-max(0.0, now - self._stepped_at) / self.time_constant)
            self.current = tuple(c + (t - c) * k for c, t in zip(self.current, target, strict=True))
        self._stepped_at = now
        if not self.move(self.current):
            self.failed_writes += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            self.step(self.clock())
            time.sleep(self.period)

    def __enter__(self) -> CameraFollow:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera-follow", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def run_until(
        self,
        check: Callable[[], tuple[bool, Point | None]],
        every: float,
        timeout: float,
    ) -> bool:
        """Call `check()` every `every` seconds until it says done or `timeout` runs out; True when
        it said done. `check` returns `(done, aim)`, the aim None to keep the last one. The camera
        thread keeps the view moving between checks, however long a check takes."""
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            started = self.clock()
            done, aim = check()
            if aim is not None:
                self.aim(aim)
            if done:
                return True
            time.sleep(max(0.0, every - (self.clock() - started)))
        return False
