"""How fast a running game draws and simulates, measured against the wall clock.

Two counters say it all. `GameClient+0x10` advances once per drawn frame and `GameLogic+0x40` once
per simulated one, so sampling both across a window gives the client fps and the logic rate
without hooking anything (`sage_patch/docs/render-rate.md` §3). The sampler records a sample only
when the client frame changes, so the frame times it reports are the engine's cadence rather than
the sampler's, to within the poll interval.

Both counters standing still is usually the engine's modal spin, not a hang
(`examples/sage_live/spell_store_probe.py`). The sampler cannot tell the two apart, so it reports
the share of the window spent in gaps of `STALL_MS` or more: anything above 0 makes the window
suspect, whatever the cause.

Read-only, except for `pace_to_client_rate`, which writes the frame cap: see its docstring.
"""

from __future__ import annotations

import math
import struct
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from sage_patch.addresses import (
    GAME_ENGINE,
    GAME_ENGINE_MAX_FPS,
    GAME_LOGIC_FRAME,
    LOGIC_FRAMES_PER_SECOND,
    THE_GAME_LOGIC,
)

__all__ = [
    "PaceReport",
    "PaceSampler",
    "Sample",
    "pace_to_client_rate",
    "summarise",
]

Reader = Callable[[int, int], bytes | None]

#: `TheGameClient`, and its frame counter (the vtable +0x7C getter is `mov eax,[ecx+0x10]`).
THE_GAME_CLIENT = 0x00DE4388
GAME_CLIENT_FRAME = 0x10
#: The client rate the binary was built for: 30 stock, the `render-rate` patch's `--fps` otherwise.
CLIENT_FRAMES_PER_SECOND = 0x00D9F60C
#: A gap between drawn frames this long is a stall - a modal spin, a load hitch - not a slow frame.
STALL_MS = 500.0

#: How long the sampler sleeps between reads. Python 3.11+ sleeps on a high-resolution timer on
#: Windows, so this is about 1 ms in practice: well under a 60 fps frame.
DEFAULT_POLL = 0.001


@dataclass(frozen=True)
class Sample:
    """One reading, taken when the client frame changed."""

    t: float
    client_frame: int
    logic_frame: int


@dataclass(frozen=True)
class PaceReport:
    """What a window of samples says about the game's pace."""

    seconds: float
    client_frames: int
    logic_frames: int
    #: Drawn frames per wall second.
    client_fps: float
    #: Simulated frames per wall second.
    logic_hz: float
    #: The rates the binary holds: `client_rate / logic_rate` client frames make a logic frame.
    client_rate: int
    logic_rate: int
    #: Wall milliseconds between drawn frames, at the median, the 99th percentile and the worst.
    frame_ms_p50: float
    frame_ms_p99: float
    frame_ms_max: float
    #: The fps of the slowest 1% of frames, the usual "1% low".
    fps_1pct_low: float
    #: The share of the window spent in gaps of `STALL_MS` or more.
    stall_share: float

    @property
    def sim_speed(self) -> float:
        """Game seconds per wall second: 1.0 is a game running at its nominal rate."""
        return self.logic_hz / self.logic_rate if self.logic_rate else 0.0

    def as_dict(self) -> dict:
        return {**asdict(self), "sim_speed": round(self.sim_speed, 4)}


def _percentile(sorted_values: Sequence[float], share: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, math.ceil(share * len(sorted_values)) - 1))
    return sorted_values[index]


def summarise(samples: Sequence[Sample], client_rate: int, logic_rate: int) -> PaceReport:
    """Reduce a window of samples to its rates. Needs at least two samples."""
    if len(samples) < 2:
        raise ValueError("a pace needs at least two samples; the client frame never advanced")
    first, last = samples[0], samples[-1]
    seconds = last.t - first.t
    client_frames = last.client_frame - first.client_frame
    logic_frames = last.logic_frame - first.logic_frame
    # One gap per pair of consecutive samples, spread over the frames it covers: a gap of two
    # frames is a sample the poll missed, not one slow frame.
    gaps: list[float] = []
    stalled = 0.0
    for a, b in zip(samples, samples[1:], strict=False):
        frames = max(1, b.client_frame - a.client_frame)
        gaps.extend([(b.t - a.t) * 1000.0 / frames] * frames)
        if (b.t - a.t) * 1000.0 >= STALL_MS:
            stalled += b.t - a.t
    gaps.sort()
    slowest = gaps[-max(1, len(gaps) // 100) :]
    return PaceReport(
        seconds=round(seconds, 3),
        client_frames=client_frames,
        logic_frames=logic_frames,
        client_fps=round(client_frames / seconds, 2) if seconds else 0.0,
        logic_hz=round(logic_frames / seconds, 3) if seconds else 0.0,
        client_rate=client_rate,
        logic_rate=logic_rate,
        frame_ms_p50=round(_percentile(gaps, 0.50), 2),
        frame_ms_p99=round(_percentile(gaps, 0.99), 2),
        frame_ms_max=round(gaps[-1], 2) if gaps else 0.0,
        fps_1pct_low=round(1000.0 / (sum(slowest) / len(slowest)), 2) if slowest else 0.0,
        stall_share=round(stalled / seconds, 4) if seconds else 0.0,
    )


def _u32(read: Reader, address: int) -> int | None:
    raw = read(address, 4)
    return struct.unpack("<I", raw)[0] if raw and len(raw) == 4 else None


class PaceSampler:
    """Samples the frame counters on a thread for as long as the `with` block runs.

        with PaceSampler(process.read) as pace:
            ...  # the work being measured
        report = pace.report()

    `read` is a `(address, size) -> bytes | None` reader, such as `WindowsProcess.read`.
    """

    def __init__(self, read: Reader, poll: float = DEFAULT_POLL) -> None:
        self._read = read
        self._poll = poll
        self._samples: list[Sample] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        client = _u32(read, THE_GAME_CLIENT)
        logic = _u32(read, THE_GAME_LOGIC)
        if not client or not logic:
            raise RuntimeError("TheGameClient or TheGameLogic is not up; is a match running?")
        self._client_frame = client + GAME_CLIENT_FRAME
        self._logic_frame = logic + GAME_LOGIC_FRAME
        self.client_rate = _u32(read, CLIENT_FRAMES_PER_SECOND) or 0
        self.logic_rate = _u32(read, LOGIC_FRAMES_PER_SECOND) or 0

    def _run(self) -> None:
        seen: int | None = None
        while not self._stop.is_set():
            client = _u32(self._read, self._client_frame)
            if client is not None and client != seen:
                t = time.perf_counter()
                logic = _u32(self._read, self._logic_frame)
                if logic is not None:
                    self._samples.append(Sample(t, client, logic))
                    seen = client
            time.sleep(self._poll)

    def __enter__(self) -> PaceSampler:
        self._thread = threading.Thread(target=self._run, name="pace-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @property
    def samples(self) -> tuple[Sample, ...]:
        return tuple(self._samples)

    def report(self) -> PaceReport:
        return summarise(self._samples, self.client_rate, self.logic_rate)


def pace_to_client_rate(process) -> tuple[int, int]:
    """Set the frame cap to the client rate the binary was built for; return `(before, after)`.

    The main loop paces itself to the cap and the simulation runs at the loop's pace over the
    client-to-logic ratio, so a cap that disagrees with the client rate runs the whole game fast
    or slow (`render-rate.md` §9.3). A mod's `FramesPerSecondLimit` is written for the build it
    ships with; to run that mod on another build - the stock 30 fps binary as a baseline for a
    60 fps one - the cap has to follow the binary. `process` is a `WindowsProcess`.
    """
    rate = _u32(process.read, CLIENT_FRAMES_PER_SECOND)
    engine = _u32(process.read, GAME_ENGINE)
    if not rate or not engine:
        raise RuntimeError("the game engine is not up yet")
    before = _u32(process.read, engine + GAME_ENGINE_MAX_FPS) or 0
    if before != rate and not process.write(engine + GAME_ENGINE_MAX_FPS, struct.pack("<I", rate)):
        raise RuntimeError("writing the frame cap failed")
    return before, rate
