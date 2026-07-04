"""Acceptance gate over the local replay corpus: every replay in `<repo>/Replays`
(gitignored, machine-specific) must parse to end-of-file with a consistent player
mapping. Skipped when the folder is absent."""

from pathlib import Path

import pytest

from sage_replay import parse_replay_from_path

pytestmark = pytest.mark.full

REPLAYS_DIR = Path(__file__).resolve().parents[2] / "Replays"

_corpus = sorted(REPLAYS_DIR.glob("*.BfME2Replay")) if REPLAYS_DIR.is_dir() else []


@pytest.mark.parametrize(
    "replay_path",
    _corpus or [pytest.param(None, marks=pytest.mark.skip(reason="no Replays corpus present"))],
    ids=[p.name for p in _corpus] or ["no-corpus"],
)
def test_corpus_replay_parses(replay_path):
    replay = parse_replay_from_path(replay_path)
    assert replay.chunks

    # Every order must map back to an occupied slot (number = slot index + 3).
    players = replay.header.metadata.players
    for chunk in replay.chunks:
        assert replay.slot_for(chunk) is not None, (
            f"chunk number {chunk.number} outside the {len(players)} occupied slots"
        )
