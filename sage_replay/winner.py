"""Infer the match outcome from a replay's session-end signals.

A replay records inputs, not state: eliminations are computed by the simulation and never
written to the stream, so no chunk says who won. What the stream does record is how each
human session *ended*, and those shapes carry a verdict whenever somebody conceded:

- `0x448` (Boolean) - the voluntary **leave-game** action, a player's final order when
  they exit mid-game (the recording player's own exit included). Exiting from the
  post-game victory/defeat screen emits none.
- `0x1D` - the **end-of-recording** marker: issued once, at the last timecode, attributed
  to the player whose client wrote the file - it identifies the replay's point of view.
- `0x44A` - the per-client checksum **heartbeat** (~100 frames). Only humans emit orders
  of any kind (AI players leave no trace at all), so a heartbeat going silent long before
  the recording ends marks a drop even without a leave order.

The inference is a concession heuristic, not a simulation - it assumes leaving mid-game
concedes. Its honest outcomes:

- ``decided`` - exactly one side still present at the end and every opposing human
  observably gone (left or dropped).
- ``recorder_left`` - the recording player quit first. They conceded, but everyone
  else's fate lies beyond the end of the recording (an incomplete point of view).
- ``undetermined`` - nobody left before the recording ended (an elimination ending,
  which the input stream does not record), or the surviving opposition includes AI
  players, whose fate is invisible.

Validated against a ground-truth 1v1 (the side named by `0x448` had in fact lost) and
the fixture corpus; the signal table lives in `order_space_map.md` section B.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sage_replay.replay import ReplayFile, ReplaySlot, ReplaySlotType

__all__ = ["PlayerSession", "Side", "WinnerVerdict", "infer_winner"]

LEAVE_GAME = 0x448
END_OF_RECORDING = 0x1D
HEARTBEAT = 0x44A

# A heartbeat silent for this many frames before the recording ends counts as a drop:
# the cadence is ~100 frames, so three missed beats is a dead session, not jitter.
_DROP_AFTER_FRAMES = 300


@dataclass(slots=True)
class PlayerSession:
    """How one human slot's session ended, as far as the order stream shows."""

    slot_index: int
    slot: ReplaySlot
    last_order: int | None = None  # last deliberate (non-heartbeat) order timecode
    last_heartbeat: int | None = None
    left_at: int | None = None  # their leave-game (`0x448`) timecode
    is_recorder: bool = False  # issued the `0x1D` end-of-recording marker

    @property
    def name(self) -> str:
        return self.slot.human_name or f"slot {self.slot_index}"

    def departed_at(self, end_timecode: int) -> int | None:
        """Frame this session observably ended before the recording did, or None while
        present to the end: an explicit leave order, or every signal (orders and
        heartbeats) going silent for longer than the drop threshold."""
        if self.left_at is not None:
            return self.left_at
        signals = [t for t in (self.last_order, self.last_heartbeat) if t is not None]
        if not signals:
            return None
        last_seen = max(signals)
        return last_seen if end_timecode - last_seen > _DROP_AFTER_FRAMES else None


@dataclass(slots=True)
class Side:
    """One team - or a solo player where the metadata carries no team - plus its AI
    count. AI players issue no orders and no heartbeats, so a side with any AI on it
    can never be shown to have fully departed."""

    key: str
    humans: list[PlayerSession] = field(default_factory=list)
    ai_count: int = 0


@dataclass(slots=True)
class WinnerVerdict:
    outcome: str  # "decided" | "recorder_left" | "undetermined"
    reason: str
    winner: str | None = None  # the winning Side.key, when decided
    winner_names: list[str] = field(default_factory=list)
    confidence: str | None = None  # "high" | "medium", when decided
    recorder: str | None = None  # the replay's point of view (`0x1D` issuer)
    sessions: list[PlayerSession] = field(default_factory=list)


def _build_sessions(replay: ReplayFile) -> list[PlayerSession]:
    players = replay.header.metadata.players
    sessions: dict[int, PlayerSession] = {}
    for chunk in replay.chunks:
        index = replay.slot_index(chunk)
        if index is None:
            continue
        session = sessions.setdefault(index, PlayerSession(index, players[index]))
        if chunk.order_type == HEARTBEAT:
            session.last_heartbeat = chunk.timecode
        else:
            session.last_order = chunk.timecode
        if chunk.order_type == LEAVE_GAME:
            session.left_at = chunk.timecode
        elif chunk.order_type == END_OF_RECORDING:
            session.is_recorder = True
    return [sessions[i] for i in sorted(sessions)]


def _build_sides(replay: ReplayFile, sessions: list[PlayerSession]) -> list[Side]:
    by_index = {s.slot_index: s for s in sessions}
    sides: dict[str, Side] = {}
    for index, slot in enumerate(replay.header.metadata.players):
        key = f"team {slot.team}" if slot.team >= 0 else (slot.human_name or f"slot {index}")
        side = sides.setdefault(key, Side(key))
        if slot.slot_type is ReplaySlotType.Human:
            side.humans.append(by_index.get(index) or PlayerSession(index, slot))
        else:
            side.ai_count += 1
    return list(sides.values())


def infer_winner(replay: ReplayFile) -> WinnerVerdict:
    """Apply the concession heuristic to a parsed replay."""
    sessions = _build_sessions(replay)
    recorder = next((s for s in sessions if s.is_recorder), None)
    recorder_name = recorder.name if recorder else None
    if not sessions:
        return WinnerVerdict(outcome="undetermined", reason="the replay carries no player orders")

    end = replay.chunks[-1].timecode
    sides = _build_sides(replay, sessions)

    # A side survives while any of its humans is still present - or while it has AI
    # players at all, since their departure (or death) is unobservable.
    surviving = [
        side
        for side in sides
        if side.ai_count > 0 or any(s.departed_at(end) is None for s in side.humans)
    ]

    if len(surviving) == 1 and any(s.departed_at(end) is None for s in surviving[0].humans):
        winner = surviving[0]
        gone = [s for side in sides if side is not winner for s in side.humans]
        # Explicit leave orders from every opposing human make the concession certain;
        # a drop-only departure could also be a network death, hence only "medium".
        confidence = "high" if all(s.left_at is not None for s in gone) else "medium"
        return WinnerVerdict(
            outcome="decided",
            reason="every opposing human left the game before the recording ended",
            winner=winner.key,
            winner_names=[s.name for s in winner.humans],
            confidence=confidence,
            recorder=recorder_name,
            sessions=sessions,
        )

    if recorder is not None and recorder.left_at is not None:
        return WinnerVerdict(
            outcome="recorder_left",
            reason=(
                "the recording player left mid-game - a concession in practice; "
                "everyone else's fate lies beyond the end of this recording"
            ),
            recorder=recorder_name,
            sessions=sessions,
        )

    if all(s.departed_at(end) is None for s in sessions):
        reason = (
            "nobody left before the recording ended - the game likely finished by "
            "elimination, which the input stream does not record"
        )
    elif any(side.ai_count > 0 and not side.humans for side in surviving):
        reason = (
            "the surviving opposition is AI-controlled, and AI players leave no trace "
            "in the order stream"
        )
    else:
        reason = "more than one side was still present when the recording ended"
    return WinnerVerdict(
        outcome="undetermined", reason=reason, recorder=recorder_name, sessions=sessions
    )
