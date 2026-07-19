"""The binary writer's acceptance gate: `serialize_replay(parse_replay(data)) == data`
byte-for-byte over every fixture replay (crash recordings and Create-A-Hero games included),
plus data-free unit tests for the writer's guard rails."""

from pathlib import Path

import pytest

from sage_replay import (
    OrderArgument,
    OrderArgumentType,
    ReplayGameType,
    parse_replay,
    serialize_replay,
    write_replay,
)

FIXTURES = Path(__file__).parent / "fixtures"
ALL_REPLAYS = sorted(FIXTURES.rglob("*.BfME2Replay"))


@pytest.mark.parametrize("path", ALL_REPLAYS, ids=lambda p: p.name)
def test_round_trip_is_byte_exact(path):
    data = path.read_bytes()
    assert serialize_replay(parse_replay(data)) == data


def test_write_replay_writes_the_same_bytes(tmp_path):
    data = ALL_REPLAYS[0].read_bytes()
    out = tmp_path / "out.BfME2Replay"
    write_replay(parse_replay(data), out)
    assert out.read_bytes() == data


def test_translated_replay_is_refused():
    replay = parse_replay(ALL_REPLAYS[0].read_bytes())
    replay.translated = True
    with pytest.raises(ValueError, match="translated"):
        serialize_replay(replay)


def test_non_bfme2_replay_is_refused():
    replay = parse_replay(ALL_REPLAYS[0].read_bytes())
    replay.header.game_type = ReplayGameType.Generals
    with pytest.raises(ValueError, match="Bfme2"):
        serialize_replay(replay)


def test_translated_name_in_integer_slot_is_refused():
    replay = parse_replay(ALL_REPLAYS[0].read_bytes())
    for chunk in replay.chunks:
        for argument in chunk.order.arguments:
            if argument.argument_type is OrderArgumentType.Integer:
                argument.value = "AngmarThrallMaster"
                with pytest.raises(ValueError, match="translated"):
                    serialize_replay(replay)
                return
    pytest.fail("no Integer argument in the fixture")


def test_long_argument_run_splits_across_pairs():
    replay = parse_replay(ALL_REPLAYS[0].read_bytes())
    chunk = replay.chunks[0]
    chunk.order.arguments = [OrderArgument(OrderArgumentType.ObjectId, n) for n in range(300)]
    reparsed = parse_replay(serialize_replay(replay))
    values = [a.value for a in reparsed.chunks[0].order.arguments]
    assert values == list(range(300))
