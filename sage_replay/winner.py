"""Infer the match outcome from a replay's session-end signals - or read it, when recorded.

A replay records inputs, not state: eliminations are computed by the simulation and never
written to the stream, so no stock chunk says who won.

**Unless the recording client carried the `replay-outcome` patch.** That patch
(`sage_patch.patches.replay_outcome`) writes one `0x7D0` chunk per player at the frame the
recording ends - whether the game finished or somebody left - carrying that player's final
state as the engine's own `VictoryConditions` had it. `recorded_outcomes` reads them back and
`infer_winner` prefers them outright: they are ground truth, not a heuristic, and they cover
AI players and elimination endings that leave no trace in the input stream. Replays from
unpatched clients carry none, and everything below is what happens then.

What the stream does record is how each human session *ended*, and those shapes carry a
verdict whenever somebody conceded:

- `0x448` (Boolean) - the voluntary **leave-game** action, a player's final order when
  they exit mid-game (the recording player's own exit included). Exiting from the
  post-game victory/defeat screen emits none.
- `0x1D` - the **end-of-recording** marker: issued once, at the last timecode, attributed
  to the player whose client wrote the file. The recording player (the point of view) is
  taken from the header's `local_player_index`, which agrees with this marker wherever one
  exists and remains available for crashed recordings that finalized no `0x1D`.
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

`assume_pov_won` (the CLI's `--winner-pov`) layers an external assumption over the
heuristic: the recording player's team won - for corpora where the replay's owner is known
to be the winner (a ladder upload, a personal win archive). It only fills in verdicts the
stream leaves ``undetermined``; explicit evidence still wins (a `decided` verdict stands
even against the point of view, and `recorder_left` - the recorder's own concession -
directly contradicts the assumption and is kept).

Validated against a ground-truth 1v1 (the side named by `0x448` had in fact lost) and
the fixture corpus; the signal table lives in `order_space_map.md` section B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from sage_replay.replay import (
    Bfme2OrderType,
    ReplayFile,
    ReplaySlot,
    ReplaySlotType,
    integer_arguments,
)

__all__ = [
    "PlayerOutcome",
    "PlayerSession",
    "RecordedOutcome",
    "Side",
    "WinnerVerdict",
    "infer_winner",
    "recorded_outcomes",
]

LEAVE_GAME = Bfme2OrderType.LeaveGame
END_OF_RECORDING = Bfme2OrderType.EndOfRecording
HEARTBEAT = Bfme2OrderType.ChecksumHeartbeat
GAME_OUTCOME = Bfme2OrderType.GameOutcome

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


class PlayerOutcome(IntEnum):
    """The values a `0x7D0` chunk's first Integer argument takes, as the `replay-outcome`
    patch writes them. `Undetermined` is the honest answer for a player who had neither lost
    nor won when the recording ended - typically everyone else's state when the recorder quit
    a match that was still live."""

    Undetermined = 0
    Victorious = 1
    Defeated = 2


@dataclass(slots=True)
class RecordedOutcome:
    """One player's final state as the engine itself had it, read from a `0x7D0` chunk."""

    slot_index: int
    slot: ReplaySlot
    outcome: PlayerOutcome
    #: The frame this player was defeated on, or None if they never were. The engine stamps it
    #: on the transition, so it is the moment of the loss, not the moment of the recording's end.
    defeated_at: int | None
    #: The frame the record itself was written - the end of the recording, the same for all.
    recorded_at: int

    @property
    def name(self) -> str:
        return self.slot.human_name or f"slot {self.slot_index}"


@dataclass(slots=True)
class WinnerVerdict:
    outcome: str  # "decided" | "recorder_left" | "undetermined"
    reason: str
    winner: str | None = None  # the winning Side.key, when decided
    winner_names: list[str] = field(default_factory=list)
    # "recorded" (read from the replay, ground truth) | "high" | "medium" | "assumed"
    confidence: str | None = None
    recorder: str | None = None  # the replay's point of view (`0x1D` issuer)
    sessions: list[PlayerSession] = field(default_factory=list)
    #: The per-player states the `replay-outcome` patch wrote, by slot index. Empty for a
    #: replay recorded by an unpatched client, which is what makes everything else a heuristic.
    recorded: dict[int, RecordedOutcome] = field(default_factory=dict)


def recorded_outcomes(replay: ReplayFile) -> dict[int, RecordedOutcome]:
    """The final per-player states written into `replay` by the `replay-outcome` patch, keyed
    by metadata slot index. Empty when the recording client did not carry the patch.

    A chunk names its player exactly as a real order does - the engine's own `m_playerIndex` in
    the chunk's number field - so `ReplayFile.slot_index` maps it with no extra rule. Chunks
    whose number falls outside the occupied slots, or whose payload is not the expected pair of
    Integers, are skipped rather than guessed at. A later batch wins over an earlier one, so a
    teardown that somehow ran twice reports its last word.
    """
    found: dict[int, RecordedOutcome] = {}
    for chunk in replay.chunks:
        if chunk.order_type != GAME_OUTCOME:
            continue
        index = replay.slot_index(chunk)
        if index is None:
            continue
        values = integer_arguments(chunk)
        if len(values) != 2:
            continue
        raw, defeated_at = values
        # A replay rehydrated from a translated document carries code names in its Integer
        # slots; these two are engine numbers with no id space behind them, so a name here
        # means the document was edited rather than translated, and is not readable.
        if not isinstance(raw, int) or not isinstance(defeated_at, int):
            continue
        try:
            outcome = PlayerOutcome(raw)
        except ValueError:
            continue
        found[index] = RecordedOutcome(
            slot_index=index,
            slot=replay.header.metadata.players[index],
            outcome=outcome,
            defeated_at=defeated_at or None,
            recorded_at=chunk.timecode,
        )
    return found


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

    # The header's local player index is the authoritative point of view: it indexes into
    # `metadata.players` exactly as a session's slot index does, agrees with the `0x1D`
    # end-of-recording issuer wherever one exists (10/10 in the corpus), and - unlike
    # `0x1D` - is present even in crashed recordings that never finalized. Prefer it.
    pov = replay.header.local_player_index
    if pov in sessions:
        for session in sessions.values():
            session.is_recorder = session.slot_index == pov

    return [sessions[i] for i in sorted(sessions)]


def _side_key(slot: ReplaySlot, index: int) -> str:
    """The `Side.key` a slot belongs to: its team, or the slot itself where the metadata
    carries none. Shared so a recorded verdict names the same side the heuristic would."""
    return f"team {slot.team}" if slot.team >= 0 else (slot.human_name or f"slot {index}")


def _build_sides(replay: ReplayFile, sessions: list[PlayerSession]) -> list[Side]:
    by_index = {s.slot_index: s for s in sessions}
    sides: dict[str, Side] = {}
    for index, slot in enumerate(replay.header.metadata.players):
        key = _side_key(slot, index)
        side = sides.setdefault(key, Side(key))
        if slot.slot_type is ReplaySlotType.Human:
            side.humans.append(by_index.get(index) or PlayerSession(index, slot))
        else:
            side.ai_count += 1
    return list(sides.values())


def _verdict_from_record(
    recorded: dict[int, RecordedOutcome],
    recorder_name: str | None,
    sessions: list[PlayerSession],
) -> WinnerVerdict | None:
    """The verdict the recorded states settle outright, or None when they name no winner.

    They name none when the engine had decided nothing yet - the recorder quitting a live
    match is the usual case - and then the concession heuristic still has something to add,
    so this defers to it rather than reporting an undetermined verdict of its own.
    """
    winners = [r for r in recorded.values() if r.outcome is PlayerOutcome.Victorious]
    if not winners:
        return None
    keys = {_side_key(r.slot, r.slot_index) for r in winners}
    defeated = sum(1 for r in recorded.values() if r.outcome is PlayerOutcome.Defeated)
    return WinnerVerdict(
        outcome="decided",
        reason=(
            f"recorded by the game itself at the end of the recording: "
            f"{len(winners)} victorious, {defeated} defeated"
        ),
        # One team normally wins; a record that somehow named two keeps both rather than
        # picking, so the disagreement is visible instead of resolved by ordering.
        winner=sorted(keys)[0] if len(keys) == 1 else ", ".join(sorted(keys)),
        winner_names=[r.name for r in winners],
        confidence="recorded",
        recorder=recorder_name,
        sessions=sessions,
        recorded=recorded,
    )


def infer_winner(replay: ReplayFile, *, assume_pov_won: bool = False) -> WinnerVerdict:
    """Read the match outcome the `replay-outcome` patch recorded, or fall back to the
    concession heuristic. With `assume_pov_won`, verdicts the stream leaves undetermined are
    decided in favour of the recording player's team - an assumption the recorded states, when
    present, always outrank."""
    sessions = _build_sessions(replay)
    recorder = next((s for s in sessions if s.is_recorder), None)
    recorder_name = recorder.name if recorder else None

    recorded = recorded_outcomes(replay)
    if recorded:
        verdict = _verdict_from_record(recorded, recorder_name, sessions)
        if verdict is not None:
            return verdict

    if not sessions:
        return WinnerVerdict(
            outcome="undetermined",
            reason="the replay carries no player orders",
            recorded=recorded,
        )

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
            recorded=recorded,
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
            recorded=recorded,
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

    if assume_pov_won and recorder is not None:
        pov_side = next(s for s in sides if any(h is recorder for h in s.humans))
        return WinnerVerdict(
            outcome="decided",
            reason=f"assumed - the recording player's team wins (--winner-pov); {reason}",
            winner=pov_side.key,
            winner_names=[s.name for s in pov_side.humans],
            confidence="assumed",
            recorder=recorder_name,
            sessions=sessions,
            recorded=recorded,
        )
    return WinnerVerdict(
        outcome="undetermined",
        reason=reason,
        recorder=recorder_name,
        sessions=sessions,
        recorded=recorded,
    )
