"""Winner inference over the fixture replays - one per verdict shape.

The 1v1 fixture is ground truth: Elendil (Misty Mountains) won that game, and the
opponent's leave-game order (`0x448`) is what the heuristic keys on. The other three
exercise the honest non-answers: an elimination ending (no leave orders), AI-only
surviving opposition, and the recording player quitting first.
"""

from pathlib import Path

import pytest

from sage_replay import infer_winner, parse_replay_from_path

FIXTURES = Path(__file__).parent / "fixtures"


def verdict_for(name: str):
    return infer_winner(parse_replay_from_path(FIXTURES / name))


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
