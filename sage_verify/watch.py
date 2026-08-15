"""The live loop: follow a replay playing back in a real client and judge its orders as they pass.

**Why a live client rather than a simulation.** A replay is a list of inputs. Whether a player
could see something is a function of the *state* those inputs produced, and the only thing that
can reproduce that state faithfully is the engine. So the engine does it: start the replay in the
game, attach read-only, and read the shroud grid it rebuilds frame by frame. Nothing here
simulates anything.

**Ordering is the whole design.** Attacking a unit reveals it, so a verdict computed from a
sample taken *after* an order is worthless - it clears every real maphack. The loop therefore
keeps the previous sample and judges each order against the newest sample **at or before** the
order's frame, refusing when that sample is more than `max_lag` frames stale. Memory is absorbed
in the same order, so a target is never excused by visibility that arrived after the click.

**Seat mapping is by name, and failures are loud.** Replay slot numbering and the live
`PlayerList` index are different spaces - `sage_patch/docs/message-stream.md` section 4c records
a game whose recorder was index 3 in memory and player 2 in the file - so an offset assumption
would silently judge one player's orders against another's vision. Names are matched instead, and
an unmatched seat's orders are reported unjudged rather than guessed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from sage_live.api.observation import Observation
from sage_replay.replay import ReplayChunk, ReplayFile
from sage_verify.orders import OBJECT_TARGETED, POSITION_TARGETED, order_name, target_of
from sage_verify.report import Finding, Report
from sage_verify.rules import Memory, Snapshot, Verdict, judge

__all__ = ["DEFAULT_MAX_LAG", "SeatMap", "Watcher"]


#: How stale a visibility sample may be and still be trusted to judge an order. 30 logic frames
#: is about a second of game time - long enough to absorb a poll that took a moment, short enough
#: that an army cannot have crossed a shroud boundary and back inside it.
DEFAULT_MAX_LAG = 30


@dataclass(frozen=True)
class SeatMap:
    """Which live `PlayerList` index each replay slot corresponds to.

    Built by name because the two numbering spaces do not agree; `notes` records every slot that
    could not be matched, so the report can say which players it never actually checked.
    """

    by_slot: dict[int, int] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, replay: ReplayFile, observation: Observation) -> SeatMap:
        live = {
            player.name.strip().casefold(): player.index
            for player in observation.players
            if player.name and player.playing
        }
        by_slot: dict[int, int] = {}
        names: dict[int, str] = {}
        notes: list[str] = []
        for index, slot in enumerate(replay.header.metadata.players):
            # Only human slots carry a name to match on. An AI slot issues no orders at all (see
            # `sage_replay.winner`), so leaving it unmapped costs nothing; an observer plays no
            # side and must not be mapped onto one.
            name = (slot.human_name or "").strip()
            if not name or slot.is_observer:
                continue
            matched = live.get(name.casefold())
            if matched is None:
                notes.append(f"replay slot {index} ({name!r}) matched no live seat - not judged")
                continue
            by_slot[index] = matched
            names[matched] = name
        if not by_slot:
            notes.append("no replay slot matched any live seat by name")
        return cls(by_slot=by_slot, names=names, notes=notes)

    def live_index(self, slot_index: int | None) -> int | None:
        return None if slot_index is None else self.by_slot.get(slot_index)


def _snapshot(observation: Observation) -> Snapshot:
    """One frame of the live game, reduced to what `rules` needs.

    Objects whose owner could not be resolved are dropped rather than given a placeholder seat.
    `owner_index` is None for script-team objects, and an order against one of those is not
    evidence about anybody's vision - inventing an owner for it would make it look like one.
    """
    return Snapshot(
        frame=observation.frame,
        objects={
            obj.object_id: (obj.position, obj.owner_index)
            for obj in observation.objects
            if obj.owner_index is not None
        },
        shroud=observation.shroud,
    )


@dataclass
class Watcher:
    """Follows one replay through one live playback.

    `poll` is injected so the whole loop can be driven from a list of constructed observations in
    a test; in normal use it is a `Session.poll`.
    """

    replay: ReplayFile
    poll: Callable[[], Observation | None]
    max_lag: int = DEFAULT_MAX_LAG
    interval: float = 0.05
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    report: Report = field(default_factory=Report)
    memory: Memory = field(default_factory=Memory)
    _seats: SeatMap | None = None
    _previous: Snapshot | None = None
    _pending: list[ReplayChunk] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Chunks in timecode order, which is the order the loop consumes them in. Real recordings
        # are already ordered; sorting is a cheap guard against one that is not, since a single
        # out-of-order chunk would otherwise be judged against a snapshot from its future.
        self._pending = sorted(
            (c for c in self.replay.chunks if c.order_type not in _IGNORED),
            key=lambda c: c.timecode,
        )
        self.report.orders_seen = len(self._pending)
        self.report.targeted_orders = sum(1 for c in self._pending if _is_targeted(c))

    def run(self, until_frame: int | None = None, timeout: float | None = None) -> Report:
        """Follow the playback to its end (or `until_frame`) and return the report."""
        deadline = None if timeout is None else self.clock() + timeout
        last_frame = -1
        stalled = 0
        for observation in self._observations(deadline):
            if not observation.in_match:
                continue
            if observation.frame == last_frame:
                stalled += 1
                # A playback that has stopped advancing is finished, paused or at the score
                # screen. Waiting forever there would report a run that never ended.
                if stalled > _STALL_LIMIT:
                    break
                continue
            stalled = 0
            last_frame = observation.frame
            self._absorb(observation)
            if until_frame is not None and observation.frame >= until_frame:
                break
            if not self._pending:
                break
        self._drain()
        if self._seats is not None:
            self.report.seat_notes = list(self._seats.notes)
        return self.report

    def _observations(self, deadline: float | None) -> Iterator[Observation]:
        while deadline is None or self.clock() < deadline:
            observation = self.poll()
            if observation is not None:
                yield observation
            self.sleep(self.interval)

    def _absorb(self, observation: Observation) -> None:
        """Take one sample: judge everything it has moved past, then fold it into memory."""
        if self._seats is None:
            self._seats = SeatMap.build(self.replay, observation)
        snapshot = _snapshot(observation)

        self.report.samples += 1
        if self.report.first_frame is None:
            self.report.first_frame = snapshot.frame
        self.report.last_frame = snapshot.frame

        # Everything strictly before this frame can now be judged, using the previous sample -
        # which is at or before each of those orders, and therefore free of the visibility the
        # orders themselves created.
        while self._pending and self._pending[0].timecode < snapshot.frame:
            self._evaluate(self._pending.pop(0), self._previous)

        self.memory.absorb(snapshot, self._seats.by_slot.values())
        self._previous = snapshot

    def _drain(self) -> None:
        """Judge whatever is left when the playback ends, using the last sample taken."""
        while self._pending:
            self._evaluate(self._pending.pop(0), self._previous)

    def _evaluate(self, chunk: ReplayChunk, snapshot: Snapshot | None) -> None:
        target = target_of(chunk)
        if target is None:
            return
        seats = self._seats
        slot_index = self.replay.slot_index(chunk)
        player = None if seats is None else seats.live_index(slot_index)
        if player is None:
            self.report.record(
                Verdict("unjudged", f"replay slot {slot_index} has no matched live seat"), None
            )
            return

        verdict = judge(
            target,
            player=player,
            frame=chunk.timecode,
            snapshot=snapshot,
            memory=self.memory,
            max_lag=self.max_lag,
        )
        finding = None
        if verdict.is_finding:
            finding = Finding(
                frame=chunk.timecode,
                player=player,
                player_name=(seats.names.get(player) if seats else None) or f"player {player}",
                order_type=chunk.order_type,
                order_name=order_name(chunk.order_type),
                confidence=verdict.confidence or "low",
                reason=verdict.reason,
                target_object=target.object_id,
                target_position=target.position,
            )
        self.report.record(verdict, finding)


# Housekeeping traffic that carries no target and would only dilute the counts.
_IGNORED = frozenset({0x1D, 0x44A, 0x7D0})

# Consecutive polls on the same frame before the playback counts as over.
_STALL_LIMIT = 60


def _is_targeted(chunk: ReplayChunk) -> bool:
    return chunk.order_type in OBJECT_TARGETED or chunk.order_type in POSITION_TARGETED
