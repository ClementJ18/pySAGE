"""End-to-end parsing of the fixture replay (RotWK 2.01 / Edain 4.8.2, 1v1) plus
data-free unit tests for the metadata/slot string parsing."""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sage_replay import (
    OrderArgumentType,
    ReplayGameType,
    ReplaySlot,
    ReplaySlotDifficulty,
    ReplaySlotType,
    parse_replay,
    parse_replay_from_path,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPLAY_PATH = FIXTURES / "4.8.2 Angmar vs Isengard (Dyastro) epic.BfME2Replay"
REPLAY_2V3_PATH = FIXTURES / "2v3.BfME2Replay"
REPLAY_VS_AI_PATH = FIXTURES / "Last Replay.BfME2Replay"


@pytest.fixture(scope="module")
def replay():
    return parse_replay_from_path(REPLAY_PATH)


@pytest.fixture(scope="module")
def replay_2v3():
    return parse_replay_from_path(REPLAY_2V3_PATH)


def test_game_type(replay):
    assert replay.game_type is ReplayGameType.Bfme2


def test_header_times(replay):
    header = replay.header
    assert header.start_time == datetime.fromtimestamp(1758055192, tz=UTC)
    assert header.end_time == datetime.fromtimestamp(1758058844, tz=UTC)
    assert header.end_time > header.start_time


def test_header_strings(replay):
    header = replay.header
    assert header.filename == "Last Replay"
    assert header.version.startswith("2.01.2614 Build 37001")
    assert header.build_date == "2007-03-30 19:47:21"


def test_header_timestamp(replay):
    ts = replay.header.timestamp
    assert (ts.year, ts.month, ts.day) == (2025, 9, 16)
    assert (ts.hour, ts.minute, ts.second) == (22, 39, 52)
    assert ts.day_of_week == 2  # Tuesday


def test_bfme2_header_has_no_version_split(replay):
    header = replay.header
    assert header.version_minor is None
    assert header.version_major is None
    assert len(header.unknown2) == 9
    assert header.game_speed is None
    assert len(header.unknown_tail) == 7  # uint16 + 6 uint32


def test_metadata(replay):
    metadata = replay.header.metadata
    assert metadata.map_file == "maps/map edain nancurir"
    assert metadata.map_file_prefix == "387"
    assert metadata.map_crc == 0xA72EAE30
    assert metadata.map_size == 575987
    assert metadata.seed == 92980671
    # BFME2-only keys survive verbatim even without typed accessors
    assert metadata.values["GSID"] == "7778"
    assert metadata.values["GT"] == "0"


def test_slots(replay):
    slots = replay.header.metadata.slots
    assert len(slots) == 8
    assert [s.slot_type for s in slots[:2]] == [ReplaySlotType.Human, ReplaySlotType.Human]
    assert all(s.slot_type is ReplaySlotType.Empty for s in slots[2:])

    first, second = replay.header.metadata.players
    assert first.human_name == "OnlyTrueWK"
    assert (first.color, first.faction, first.team) == (1, 12, -1)
    assert second.human_name == "Dyastro"
    assert (second.color, second.faction, second.team) == (9, 9, -1)


def test_chunk_stream_parses_to_eof(replay):
    # parse_replay reads chunks until end-of-file and validates the header's
    # timecode count against the last chunk, so reaching here proves alignment.
    assert len(replay.chunks) == 9709
    assert replay.chunks[-1].timecode == replay.header.num_timecodes == 18107


def test_chunk_arguments_are_typed(replay):
    counts = Counter(
        argument.argument_type for chunk in replay.chunks for argument in chunk.order.arguments
    )
    assert counts == {
        OrderArgumentType.Integer: 1582,
        OrderArgumentType.Float: 39,
        OrderArgumentType.Boolean: 5376,
        OrderArgumentType.ObjectId: 6563,
        OrderArgumentType.Position: 3118,
        OrderArgumentType.ScreenRectangle: 1299,
        OrderArgumentType.Unknown9: 720,
    }

    first = replay.chunks[0]
    assert first.timecode == 1
    assert first.order_type == 0x3EC
    assert first.order.arguments[0].value is True

    position = next(
        a.value
        for chunk in replay.chunks
        for a in chunk.order.arguments
        if a.argument_type is OrderArgumentType.Position
    )
    assert isinstance(position, tuple) and len(position) == 3


def test_slot_mapping_1v1(replay):
    # Chunk numbers are slot index + 3 for BFME2 (validated across the corpus)
    issuers = {replay.slot_for(chunk).human_name for chunk in replay.chunks}
    assert issuers == {"OnlyTrueWK", "Dyastro"}
    assert {replay.slot_index(c) for c in replay.chunks} == {0, 1}


def test_2v3_slots(replay_2v3):
    metadata = replay_2v3.header.metadata
    assert metadata.map_file == "maps/khand"
    humans = [s for s in metadata.players if s.slot_type is ReplaySlotType.Human]
    computers = [s for s in metadata.players if s.slot_type is ReplaySlotType.Computer]
    assert [s.human_name for s in humans] == ["TheNecro", "Julio229", "GameRanger"]
    assert [s.computer_difficulty for s in computers] == [ReplaySlotDifficulty.Brutal] * 3


def test_2v3_slot_mapping(replay_2v3):
    # Only humans issue recorded orders (AI input replays from the seed); their
    # numbers cover exactly the first three slots.
    assert len(replay_2v3.chunks) == 6865
    assert {c.number for c in replay_2v3.chunks} == {3, 4, 5}
    issuers = {replay_2v3.slot_for(chunk).human_name for chunk in replay_2v3.chunks}
    assert issuers == {"TheNecro", "Julio229", "GameRanger"}


def test_vs_brutal_ai_replay():
    replay = parse_replay_from_path(REPLAY_VS_AI_PATH)
    metadata = replay.header.metadata
    assert metadata.map_file == "maps/map edain mount doom ii"
    assert len(replay.chunks) == 74
    assert [s.slot_type for s in metadata.players].count(ReplaySlotType.Computer) == 5
    assert all(replay.slot_for(c).human_name == "TheNecro" for c in replay.chunks)


def test_crash_replay_header_timecodes_zero():
    # A crashed game leaves the header's timecode count 0; parsing must not
    # reject the (otherwise valid) chunk stream then.
    data = bytearray(REPLAY_PATH.read_bytes())
    data[16:20] = b"\x00\x00\x00\x00"  # num_timecodes sits right after the timestamps
    replay = parse_replay(bytes(data))
    assert replay.header.num_timecodes == 0
    assert len(replay.chunks) == 9709


def test_only_header():
    replay = parse_replay_from_path(REPLAY_PATH, only_header=True)
    assert replay.chunks == []
    assert replay.header.metadata.map_file == "maps/map edain nancurir"


def test_not_a_replay_raises():
    with pytest.raises(ValueError, match="not a SAGE replay"):
        parse_replay(b"NOTAREPL" + b"\x00" * 64)


def test_human_slot_parse():
    slot = ReplaySlot.parse("HOnlyTrueWK,5DD1F9AF,8094,TT,1,12,-1,-1,0,1,0")
    assert slot.slot_type is ReplaySlotType.Human
    assert slot.human_name == "OnlyTrueWK"
    assert (slot.color, slot.faction, slot.start_position, slot.team) == (1, 12, -1, -1)
    assert slot.raw.startswith("HOnlyTrueWK")


def test_computer_slot_parse():
    slot = ReplaySlot.parse("CM,3,5,2,1")
    assert slot.slot_type is ReplaySlotType.Computer
    assert slot.computer_difficulty is ReplaySlotDifficulty.Medium
    assert (slot.color, slot.faction, slot.start_position, slot.team) == (3, 5, 2, 1)


def test_brutal_computer_slot_parse():
    # BFME2 has a fourth difficulty the Generals format doesn't: B(rutal)
    slot = ReplaySlot.parse("CB,-1,-1,3,1,0,0")
    assert slot.computer_difficulty is ReplaySlotDifficulty.Brutal
    assert (slot.color, slot.faction, slot.start_position, slot.team) == (-1, -1, 3, 1)


def test_empty_slot_parse():
    for raw in ("X", "O"):
        assert ReplaySlot.parse(raw).slot_type is ReplaySlotType.Empty


def test_bad_slot_raises():
    with pytest.raises(ValueError, match="slot type"):
        ReplaySlot.parse("Zwhat")
