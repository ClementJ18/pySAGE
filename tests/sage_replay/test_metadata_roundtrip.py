"""Serializing the game-info string back must reproduce the engine's own bytes.

`ReplayMetadata` was a read-only model until the lobby file turned out to hold the same string
(`tools/skirmish_config.py`). Writing it back is only safe if a parse/serialize round trip is
*byte-identical* on strings the engine wrote — otherwise editing one field silently rewrites
others, and the failure surfaces as a game that will not start rather than as a bad diff.

The whole fixture corpus is the gate: every replay header, every slot, every key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_replay import parse_replay_from_path
from sage_replay.replay import ReplayMetadata, ReplaySlot, ReplaySlotType

FIXTURES = sorted((Path(__file__).parent / "fixtures").rglob("*.BfME2Replay"))
REPLAYS_DIR = Path(__file__).resolve().parents[2] / "Replays"
CORPUS = sorted(REPLAYS_DIR.glob("*.BfME2Replay")) if REPLAYS_DIR.is_dir() else []


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem[:40] for p in FIXTURES])
def test_metadata_round_trips_byte_for_byte(path: Path):
    metadata = parse_replay_from_path(path).header.metadata
    assert metadata.to_string() == metadata.raw


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem[:40] for p in FIXTURES])
def test_every_slot_round_trips(path: Path):
    """Slot-level, so a failure names the slot rather than the whole header."""
    for slot in parse_replay_from_path(path).header.metadata.slots:
        assert slot.serialize() == slot.raw


@pytest.mark.full
@pytest.mark.parametrize(
    "path",
    CORPUS or [pytest.param(None, marks=pytest.mark.skip(reason="no Replays corpus present"))],
    ids=[p.name for p in CORPUS] or ["no-corpus"],
)
def test_corpus_metadata_round_trips(path: Path):
    """The same gate over the gitignored corpus, where the odd formatting turns up: an
    unpadded `MC=C1ABD7B` and a lower-cased IP both slipped past the fixtures at first."""
    metadata = parse_replay_from_path(path).header.metadata
    assert metadata.to_string() == metadata.raw


def test_editing_a_faction_changes_only_that_field():
    """The point of the exercise: change one thing, leave everything else alone."""
    metadata = parse_replay_from_path(FIXTURES[0]).header.metadata
    slot = next(s for s in metadata.slots if s.slot_type is not ReplaySlotType.Empty)
    original = slot.faction
    slot.faction = original + 1
    rebuilt = ReplayMetadata.from_string(metadata.to_string(), metadata.game_type)
    assert [s.faction for s in rebuilt.slots] == [
        (original + 1 if s is slot else s.faction) for s in metadata.slots
    ]
    assert rebuilt.map_file == metadata.map_file
    assert rebuilt.seed == metadata.seed
    assert rebuilt.values.keys() == metadata.values.keys()


def test_an_unknown_key_survives_an_edit():
    """`GR`, `GSID`, `GT`, `SI` are unexplained; an edit must not drop them."""
    metadata = parse_replay_from_path(FIXTURES[0]).header.metadata
    metadata.seed = 12345
    rebuilt = ReplayMetadata.from_string(metadata.to_string(), metadata.game_type)
    assert rebuilt.seed == 12345
    for key, value in metadata.values.items():
        if key not in {"SD"}:
            assert rebuilt.values[key] == value


def test_an_empty_slot_serializes_to_its_marker():
    assert ReplaySlot(slot_type=ReplaySlotType.Empty, raw="X").serialize() == "X"
    assert ReplaySlot(slot_type=ReplaySlotType.Empty, raw="O").serialize() == "O"
    # No raw at all still has to emit something the engine reads as "closed".
    assert ReplaySlot(slot_type=ReplaySlotType.Empty).serialize() == "X"
