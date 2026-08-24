"""Follow a live match and stop the moment this client declares itself out of sync.

**The trigger is the engine's own verdict, not a guess.** `TheGameLogic + 0x1BC` is zero for the
life of a match and becomes 1 in the routine that raises the `GUI:DesyncTitle` box - written
*before* the box, latched, and never cleared until the next `GameLogic` is built. So the watcher
does not have to infer a desync from state that looks wrong; it reads the same byte the message
box reads. `sage_patch/docs/desync-detection.md` is the derivation, and section 5 the live
confirmation: observed setting at frames 102 and 103 in two real desyncs, the second agreeing to
the frame with that replay's own `abnormal_end_frame`.

**What it records, and why the log is the deliverable rather than the alarm.** By the time the
latch flips, the divergence is already tens of frames old - a client declares a mismatch when the
peer's checksum for some earlier frame arrives and disagrees. Knowing *that* it desynced is one
line; knowing *what* had already drifted needs the frames before it. So every sample is written
out as it is taken, and the trigger only marks the spot.

**Two logs from two machines are the actual instrument.** Each sample carries hashes of the same
simulation state on both peers - the whole object set, and the same thing split per owner - so
`compare` can name the first frame where the two stop agreeing and which player's objects moved.
That frame is upstream of the latch and is the one worth reading.

**Torn samples are marked, not silently trusted.** Reading a few thousand objects out of another
process is not atomic and a logic frame is only 200 ms, so a sample can straddle a frame boundary
and hash differently on two machines for a reason that is not a desync. The frame counter is read
before and after every sample; when it moved, the sample is flagged `torn` and `compare` skips it
rather than reporting a divergence it cannot stand behind.
"""

from __future__ import annotations

import hashlib
import json
import struct
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sage_live.backends.base import GameExited

if TYPE_CHECKING:
    from sage_live.api.observation import Observation
    from sage_live.backends.memory import MemoryBackend

__all__ = [
    "DEFAULT_HISTORY",
    "Divergence",
    "DesyncWatcher",
    "Sample",
    "Stop",
    "compare",
    "read_log",
]

#: How many samples to keep in memory for the summary written on the trigger. 600 at the logic
#: rate is two minutes, which is far more than the gap between a divergence and the mismatch that
#: reports it, and small enough to hold whole.
DEFAULT_HISTORY = 600

#: Why the watch ended. `desync` is the one being watched for; the rest exist so a run that
#: stopped for a boring reason cannot be misread as a clean match.
Stop = str


def _digest(chunks: Iterator[bytes]) -> str:
    """A short stable hash. blake2b rather than `hash()`, which is salted per process and would
    make two machines' logs incomparable for a reason nobody would think to check."""
    h = hashlib.blake2b(digest_size=8)
    for chunk in chunks:
        h.update(chunk)
    return h.hexdigest()


def _object_bytes(obj: Any) -> bytes:
    """One object's simulation state, packed.

    Floats go in as their **raw bits**, not rounded: two clients running the same simulation
    produce bit-identical floats, and rounding first would hide exactly the small drift that is
    worth catching early. Health is included and `max_health` is not - the latter is template
    data, identical by construction, so hashing it only costs bytes.
    """
    return struct.pack(
        "<IiiffffI",
        obj.object_id,
        -1 if obj.owner_index is None else obj.owner_index,
        len(obj.template_name),
        obj.position[0],
        obj.position[1],
        obj.position[2],
        obj.angle,
        int(obj.health * 1000),
    ) + obj.template_name.encode("utf-8", "replace")


@dataclass(frozen=True, slots=True)
class Sample:
    """One frame's worth of what both peers must agree on."""

    frame: int
    desync: bool
    objects: int
    state: str
    by_owner: dict[str, str]
    counts: dict[str, int]
    players: dict[str, dict[str, int]]
    torn: bool = False
    wall: float = 0.0

    @classmethod
    def take(cls, observation: Observation, desync: bool, torn: bool) -> Sample:
        ordered = sorted(observation.objects, key=lambda o: o.object_id)
        by_owner: dict[int, list[bytes]] = {}
        for obj in ordered:
            by_owner.setdefault(-1 if obj.owner_index is None else obj.owner_index, []).append(
                _object_bytes(obj)
            )
        return cls(
            frame=observation.frame,
            desync=desync,
            objects=len(ordered),
            state=_digest(_object_bytes(o) for o in ordered),
            by_owner={str(k): _digest(iter(v)) for k, v in sorted(by_owner.items())},
            counts={str(k): len(v) for k, v in sorted(by_owner.items())},
            players={
                str(p.index): {
                    "resources": p.resources,
                    "collected": p.resources_collected,
                    "power": p.power_points,
                    "cp_used": p.command_points[0],
                    "cp_max": p.command_points[1],
                    "sciences": len(p.sciences),
                    "upgrades": len(p.upgrades),
                }
                for p in observation.players
            },
            torn=torn,
            wall=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "desync": self.desync,
            "objects": self.objects,
            "state": self.state,
            "by_owner": self.by_owner,
            "counts": self.counts,
            "players": self.players,
            "torn": self.torn,
            "wall": round(self.wall, 3),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Sample:
        return cls(
            frame=int(raw["frame"]),
            desync=bool(raw.get("desync", False)),
            objects=int(raw.get("objects", 0)),
            state=str(raw.get("state", "")),
            by_owner=dict(raw.get("by_owner", {})),
            counts=dict(raw.get("counts", {})),
            players=dict(raw.get("players", {})),
            torn=bool(raw.get("torn", False)),
            wall=float(raw.get("wall", 0.0)),
        )


@dataclass
class DesyncWatcher:
    """Poll a live client until it says it is out of sync.

    The loop is deliberately two-speed. The latch is one byte and is read on **every** pass, so
    the edge is caught within a poll interval whatever else is happening; the full observation is
    the expensive part and is taken every `sample_every` logic frames. A run that only needs the
    moment can set `sample_every` to 0 and pay for nothing else.
    """

    backend: MemoryBackend
    log: Path | None = None
    history: int = DEFAULT_HISTORY
    sample_every: int = 1
    poll: float = 0.05
    #: Give up after this many seconds with the logic frame frozen (0 disables it). A dead
    #: `game.dat` does not always read as dead: the handle outlives the process and reads keep
    #: succeeding against the last mapped values, so the frame counter simply stops moving and a
    #: watcher with no clock here spins forever on a game that closed twenty minutes ago. That
    #: happened - a whole match went unwatched because the previous run was still "watching" a
    #: process that no longer existed. In a network match nothing else freezes the counter.
    stall_after: float = 30.0
    samples: deque[Sample] = field(init=False)
    stopped: Stop = field(default="", init=False)
    trigger_frame: int | None = field(default=None, init=False)
    _handle: Any = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.samples = deque(maxlen=max(1, self.history))

    def __enter__(self) -> DesyncWatcher:
        if self.log is not None:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.log.open("a", encoding="utf-8")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _emit(self, sample: Sample) -> None:
        self.samples.append(sample)
        if self._handle is not None:
            self._handle.write(json.dumps(sample.to_dict(), separators=(",", ":")) + "\n")
            self._handle.flush()  # a crash mid-match must not cost the tail of the log

    def await_match(self, timeout: float = 0.0) -> bool:
        """Block at the menu until a match starts. True once one has, False on timeout.

        Frame 0 means no simulation is running, which is where the game sits in the lobby - so a
        watcher started before the match would otherwise read "left-match" and exit in the first
        pass. Waiting has to happen here rather than in the caller because the whole point is to
        be attached *before* the first frame: a client that desyncs early has already done it by
        the time somebody alt-tabs out to start a watcher, and on this build alt-tabbing crashes
        the game outright.
        """
        deadline = None if not timeout else time.monotonic() + timeout
        while True:
            try:
                if self.backend.desync_declared() is None:
                    return False
                if self.backend.frame() > 0:
                    return True
            except GameExited:
                return False
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(max(self.poll, 0.25))

    def run(self, limit: int = 0, wait: bool = True) -> Stop:
        """Watch until something ends it, and say what did.

        `limit` caps the number of logic frames watched (0 = until the game or the user stops it).
        `wait` sits at the menu until a match starts rather than treating frame 0 as the end.
        Every exit sets `stopped` to a reason rather than returning a bare bool, because "the
        process vanished" and "the match ran clean" are the same `False` to a caller that only
        gets a flag - and they mean opposite things.
        """
        try:
            if wait and not self.await_match():
                return self._end("lost")
        except KeyboardInterrupt:
            return self._end("interrupted")
        last_frame = self.backend.frame()
        next_sample = last_frame
        watched = 0
        moved_at = time.monotonic()
        try:
            while True:
                try:
                    declared = self.backend.desync_declared()
                    frame = 0 if declared is None else self.backend.frame()
                except GameExited:
                    # The game crashed or was closed. That is emphatically not "the match ended
                    # clean" and must not be reported as one - three of these in fifteen minutes
                    # is the finding, not the noise.
                    return self._end("crashed")
                if declared is None:
                    return self._end("lost")
                if frame == 0:
                    return self._end("left-match")
                if frame != last_frame:
                    watched += frame - last_frame
                    last_frame = frame
                    moved_at = time.monotonic()
                elif self.stall_after and time.monotonic() - moved_at >= self.stall_after:
                    return self._end("stalled")
                if declared:
                    self.trigger_frame = frame
                    if self.sample_every:
                        self._take(declared=True)
                    return self._end("desync")
                if self.sample_every and frame >= next_sample:
                    self._take(declared=False)
                    next_sample = frame + self.sample_every
                if limit and watched >= limit:
                    return self._end("limit")
                time.sleep(self.poll)
        except KeyboardInterrupt:
            return self._end("interrupted")

    def _take(self, declared: bool) -> None:
        """One full sample, bracketed by the frame counter.

        `declared` comes from the caller's own read rather than a fresh one: the latch was just
        read to decide whether to be here at all, and reading it twice would only widen the
        window in which the two disagree.
        """
        try:
            before = self.backend.frame()
            observation = self.backend.poll()
            after = self.backend.frame()
        except GameExited:
            return
        if observation is None:
            return
        self._emit(Sample.take(observation, desync=declared, torn=before != after))

    def _end(self, reason: Stop) -> Stop:
        self.stopped = reason
        return reason

    def summary(self) -> dict[str, Any]:
        window = list(self.samples)
        return {
            "stopped": self.stopped,
            "trigger_frame": self.trigger_frame,
            "samples": len(window),
            "first_frame": window[0].frame if window else None,
            "last_frame": window[-1].frame if window else None,
            "torn": sum(1 for s in window if s.torn),
            "window": [s.to_dict() for s in window],
        }


def read_log(path: Path) -> list[Sample]:
    """Every sample in a watcher log, in file order. A malformed trailing line is dropped rather
    than raising: the common way a log ends is the process being killed mid-write."""
    samples: list[Sample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(Sample.from_dict(json.loads(line)))
        except (ValueError, KeyError):
            continue
    return samples


@dataclass(frozen=True, slots=True)
class Divergence:
    """The first frame two peers stopped agreeing, and as much of "about what" as the hashes say."""

    frame: int
    owners: tuple[str, ...]
    counts: dict[str, tuple[int, int]]
    players: tuple[str, ...]
    compared: int
    skipped: int
    last_agreed: int | None

    def describe(self) -> str:
        lines = [f"first divergence at frame {self.frame}"]
        if self.last_agreed is not None:
            lines.append(f"  last frame both agreed on: {self.last_agreed}")
        if self.owners:
            lines.append(f"  objects differ for player(s): {', '.join(self.owners)}")
            for owner, (a, b) in sorted(self.counts.items()):
                if a != b:
                    lines.append(f"    player {owner}: {a} objects here, {b} there")
        else:
            lines.append("  object state agrees; the difference is in player state")
        if self.players:
            lines.append(f"  player state differs for: {', '.join(self.players)}")
        lines.append(
            f"  compared {self.compared} frames, skipped {self.skipped} (torn or unpaired)"
        )
        return "\n".join(lines)


def compare(here: list[Sample], there: list[Sample]) -> Divergence | None:
    """The first frame at which two machines' logs of the same match disagree.

    Frames are joined on the frame number, not on position: two watchers attach at different
    moments and sample at different wall-clock times, so the *n*th sample of one is not the *n*th
    of the other. A frame either side marked `torn` is skipped, because a torn sample can differ
    for a reason that is not a desync and a false first-divergence would send the reader to the
    wrong part of the match.
    """
    mine = {s.frame: s for s in here if not s.torn}
    theirs = {s.frame: s for s in there if not s.torn}
    shared = sorted(set(mine) & set(theirs))
    skipped = len({s.frame for s in here} | {s.frame for s in there}) - len(shared)
    last_agreed: int | None = None
    for index, frame in enumerate(shared):
        a, b = mine[frame], theirs[frame]
        players = tuple(
            k
            for k in sorted(set(a.players) | set(b.players))
            if a.players.get(k) != b.players.get(k)
        )
        if a.state == b.state and not players:
            last_agreed = frame
            continue
        owners = tuple(
            k
            for k in sorted(set(a.by_owner) | set(b.by_owner))
            if a.by_owner.get(k) != b.by_owner.get(k)
        )
        return Divergence(
            frame=frame,
            owners=owners,
            counts={k: (a.counts.get(k, 0), b.counts.get(k, 0)) for k in owners},
            players=players,
            compared=index + 1,
            skipped=skipped,
            last_agreed=last_agreed,
        )
    return None
