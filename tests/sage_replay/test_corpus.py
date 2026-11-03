"""Acceptance gates over the replay corpora.

The fixture gate always runs: it strict-audits the checked-in fixtures for format coverage,
so every still-opaque surface must match the documented known reality (the programmatic
equivalent of `coverage --strict`). The `full`-marked corpus gate extends both the
end-of-file parse check and the strict audit to the gitignored local corpus
(`tests.sage_replay.corpus`) when it is present."""

from pathlib import Path

import pytest

from sage_replay import parse_replay_from_path
from sage_replay.coverage import audit
from tests.sage_replay.corpus import CORPUS, REPLAYS_DIR, replay_id

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_fixtures_pass_strict_coverage():
    # The checked-in acceptance gate: no un-accounted-for bytes across the fixtures.
    report = audit([FIXTURES_DIR])
    assert report.files, "no fixtures found to audit"
    assert report.parsed == len(report.files)
    assert report.strict_failures() == []


@pytest.mark.full
@pytest.mark.parametrize(
    "replay_path",
    CORPUS or [pytest.param(None, marks=pytest.mark.skip(reason="no Replays corpus present"))],
    ids=[replay_id(p) for p in CORPUS] or ["no-corpus"],
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


@pytest.mark.full
@pytest.mark.skipif(not CORPUS, reason="no Replays corpus present")
def test_corpus_passes_strict_coverage():
    # The same "no raw bytes" gate over the local corpus: a deviation here is a real finding
    # (a new order id, a non-constant reserved field, an untyped metadata key).
    report = audit([REPLAYS_DIR])
    assert report.strict_failures() == []
