"""Winner inference over the fixture replays - one per verdict shape.

The 1v1 fixture is ground truth: Elendil (Misty Mountains) won that game, and the
opponent's leave-game order (`0x448`) is what the heuristic keys on. The other three
exercise the honest non-answers: an elimination ending (no leave orders), AI-only
surviving opposition, and the recording player quitting first.

The last group covers the case where there is nothing to infer: a replay recorded by a
client carrying `sage_patch`'s `replay-outcome` patch states each player's final state
outright. No corpus fixture carries one yet, so those chunks are synthesized onto a fixture
and round-tripped through the real serializer, which is what makes them the same bytes the
patch writes rather than a convenient in-memory object.
"""

from pathlib import Path

import pytest

from sage_replay import (
    PlayerOutcome,
    infer_winner,
    parse_replay,
    parse_replay_from_path,
    recorded_outcomes,
    serialize_replay,
)
from sage_replay.replay import Bfme2OrderType, Order, OrderArgument, OrderArgumentType, ReplayChunk

FIXTURES = Path(__file__).parent / "fixtures"

DECIDED_FIXTURE = "1v1 Misty vs Mordor (Elendil wins).BfME2Replay"
#: Chunk player numbers are the slot index plus this - `_FIRST_SLOT_NUMBER`, the same offset
#: the engine's own orders carry, which is exactly why the patch writes `Player::m_playerIndex`
#: into the field rather than inventing a numbering of its own.
FIRST_SLOT_NUMBER = 3


def verdict_for(name: str):
    return infer_winner(parse_replay_from_path(FIXTURES / name))


def _outcome_chunk(timecode: int, slot_index: int, outcome: PlayerOutcome, defeated_at: int):
    return ReplayChunk(
        timecode=timecode,
        order_type=Bfme2OrderType.GameOutcome,
        number=slot_index + FIRST_SLOT_NUMBER,
        order=Order(
            player_index=slot_index + FIRST_SLOT_NUMBER - 1,
            order_type=Bfme2OrderType.GameOutcome,
            arguments=[
                OrderArgument(OrderArgumentType.Integer, int(outcome)),
                OrderArgument(OrderArgumentType.Integer, defeated_at),
            ],
        ),
    )


def with_recorded_outcomes(name: str, states: dict[int, tuple[PlayerOutcome, int]]):
    """`name` re-recorded as a patched client would have written it: one outcome chunk per
    player at the closing frame, ahead of the `0x1D` end-of-recording marker, then serialized
    and parsed back so the test sees the chunks off the wire."""
    replay = parse_replay_from_path(FIXTURES / name)
    end = replay.chunks[-1].timecode
    injected = [
        _outcome_chunk(end, slot, outcome, defeated_at)
        for slot, (outcome, defeated_at) in sorted(states.items())
    ]
    replay.chunks[-1:] = [*injected, replay.chunks[-1]]
    return parse_replay(serialize_replay(replay))


@pytest.fixture(scope="module")
def decided():
    return verdict_for("1v1 Misty vs Mordor (Elendil wins).BfME2Replay")


def test_concession_decides_the_game(decided):
    assert decided.outcome == "decided"
    assert decided.winner_names == ["Elendil"]
    assert decided.confidence == "high"


def test_recorder_and_sessions(decided):
    assert decided.recorder == "Elendil"
    by_name = {s.name: s for s in decided.sessions}
    assert by_name["mokaba27"].left_at == 8691
    assert by_name["Elendil"].left_at is None
    assert by_name["Elendil"].is_recorder


def test_elimination_ending_is_undetermined():
    verdict = verdict_for("4.8.2 Angmar vs Isengard (Dyastro) epic.BfME2Replay")
    assert verdict.outcome == "undetermined"
    assert "elimination" in verdict.reason
    assert verdict.recorder == "OnlyTrueWK"


def test_ai_opposition_is_opaque():
    verdict = verdict_for("2v3.BfME2Replay")
    assert verdict.outcome == "undetermined"
    assert "AI" in verdict.reason
    # Julio229 abandoned the game mid-way; his session still shows the leave order.
    by_name = {s.name: s for s in verdict.sessions}
    assert by_name["Julio229"].left_at == 4924


def test_recorder_leaving_first_is_not_a_verdict():
    verdict = verdict_for("Last Replay.BfME2Replay")
    assert verdict.outcome == "recorder_left"
    assert verdict.recorder == "TheNecro"
    assert verdict.winner is None


# --- recorded outcomes (the `replay-outcome` patch) ------------------------------------------


def test_an_unpatched_replay_records_nothing():
    """Every corpus fixture predates the patch, so the heuristic stays the only answer and
    `recorded` is empty rather than absent."""
    replay = parse_replay_from_path(FIXTURES / DECIDED_FIXTURE)
    assert recorded_outcomes(replay) == {}
    assert infer_winner(replay).recorded == {}


def test_recorded_outcomes_are_read_back_per_slot():
    replay = with_recorded_outcomes(
        DECIDED_FIXTURE,
        {0: (PlayerOutcome.Victorious, 0), 1: (PlayerOutcome.Defeated, 8691)},
    )
    recorded = recorded_outcomes(replay)
    assert {r.name: r.outcome for r in recorded.values()} == {
        "Elendil": PlayerOutcome.Victorious,
        "mokaba27": PlayerOutcome.Defeated,
    }
    # The defeat frame is the moment of the loss, not the end of the recording.
    assert recorded[1].defeated_at == 8691
    assert recorded[0].defeated_at is None
    assert {r.recorded_at for r in recorded.values()} == {replay.chunks[-1].timecode}


def test_a_recorded_verdict_outranks_the_heuristic():
    """Deliberately the opposite of what the concession heuristic reads off this fixture: the
    stream says Elendil won (mokaba27 issued the leave order), the record says otherwise. The
    record is the engine's own answer, so it must win."""
    inferred = verdict_for(DECIDED_FIXTURE)
    assert (inferred.winner_names, inferred.confidence) == (["Elendil"], "high")

    verdict = infer_winner(
        with_recorded_outcomes(
            DECIDED_FIXTURE,
            {0: (PlayerOutcome.Defeated, 8000), 1: (PlayerOutcome.Victorious, 0)},
        )
    )
    assert verdict.outcome == "decided"
    assert verdict.winner_names == ["mokaba27"]
    assert verdict.confidence == "recorded"
    assert verdict.winner == "team 0"  # mokaba27's team, keyed as the heuristic keys sides


def test_a_recorded_verdict_outranks_the_pov_assumption():
    """`--winner-pov` is an assumption about a corpus; a recorded state is a fact about the
    game. Elendil recorded this replay, and the record still says they lost."""
    replay = with_recorded_outcomes(
        DECIDED_FIXTURE,
        {0: (PlayerOutcome.Defeated, 8000), 1: (PlayerOutcome.Victorious, 0)},
    )
    verdict = infer_winner(replay, assume_pov_won=True)
    assert verdict.winner_names == ["mokaba27"]
    assert verdict.confidence == "recorded"


def test_an_elimination_ending_stops_being_undetermined():
    """The case the input stream can never answer: nobody conceded, so the heuristic gives
    up. A recorded state settles it."""
    unpatched = verdict_for("4.8.2 Angmar vs Isengard (Dyastro) epic.BfME2Replay")
    assert unpatched.outcome == "undetermined"

    verdict = infer_winner(
        with_recorded_outcomes(
            "4.8.2 Angmar vs Isengard (Dyastro) epic.BfME2Replay",
            {0: (PlayerOutcome.Victorious, 0), 1: (PlayerOutcome.Defeated, 30000)},
        )
    )
    assert verdict.outcome == "decided"
    assert verdict.confidence == "recorded"
    assert len(verdict.winner_names) == 1


def test_a_record_naming_no_winner_falls_back_to_the_heuristic():
    """What the patch writes when the recorder quits a match that was still live: their own
    defeat, and `undetermined` for everyone else. That names no winner, so the concession
    reading still has the last word - and the recorded states ride along with it."""
    verdict = infer_winner(
        with_recorded_outcomes(
            DECIDED_FIXTURE,
            {0: (PlayerOutcome.Undetermined, 0), 1: (PlayerOutcome.Defeated, 8691)},
        )
    )
    assert verdict.confidence == "high"  # the heuristic's verdict, not the record's
    assert verdict.winner_names == ["Elendil"]
    assert verdict.recorded[1].outcome is PlayerOutcome.Defeated


def test_a_chunk_with_an_unknown_outcome_value_is_skipped_not_guessed():
    replay = with_recorded_outcomes(DECIDED_FIXTURE, {1: (PlayerOutcome.Defeated, 8691)})
    bad = next(c for c in replay.chunks if c.order_type == Bfme2OrderType.GameOutcome)
    bad.order.arguments[0].value = 99
    assert recorded_outcomes(replay) == {}


def test_outcome_chunks_survive_a_serialize_round_trip():
    """`with_recorded_outcomes` already parses off serialized bytes; this pins that the
    re-emitted file is byte-identical, so a patched replay stays editable by `sage_replay`."""
    replay = with_recorded_outcomes(
        DECIDED_FIXTURE,
        {0: (PlayerOutcome.Victorious, 0), 1: (PlayerOutcome.Defeated, 8691)},
    )
    assert parse_replay(serialize_replay(replay)).chunks[-3:] == replay.chunks[-3:]
