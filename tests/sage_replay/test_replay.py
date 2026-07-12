"""End-to-end parsing of the fixture replay (RotWK 2.01 / Edain 4.8.2, 1v1) plus
data-free unit tests for the metadata/slot string parsing."""

import ipaddress
import struct
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

from sage_replay import (
    OrderArgumentType,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotDifficulty,
    ReplaySlotType,
    ReplayTimestamp,
    infer_winner,
    parse_replay,
    parse_replay_from_path,
)
from sage_utils.stream import BinaryStream

FIXTURES = Path(__file__).parent / "fixtures"
REPLAY_PATH = FIXTURES / "4.8.2 Angmar vs Isengard (Dyastro) epic.BfME2Replay"
REPLAY_2V3_PATH = FIXTURES / "2v3.BfME2Replay"
REPLAY_VS_AI_PATH = FIXTURES / "Last Replay.BfME2Replay"

# The two recordings a crash cut short: no `0x1D`, num_timecodes 0, and the header's
# abnormal-end frame carries the last completed heartbeat instead of the finalized sentinel.
CRASH_REPLAYS = {
    "858843b3-4a55-488b-be46-5762a51421df.BfME2Replay": 11502,
    "cfda93ec-0b1d-4be4-b826-190b79228ae2.BfME2Replay": 7702,
}

# Games featuring a Create-A-Hero customized unit embed one length-prefixed ALAE2STR blob
# per occupied player in the header, ahead of the trailing words. name -> hero blob count
# (a 2-player and a 4-player game, covering both block-count regimes).
CUSTOM_HERO_REPLAYS = {
    "0080eaf1-a38c-4aba-8a26-893219975944.BfME2Replay": 2,
    "c18c1ef5-eed7-41b4-8269-9f89adb5ea91.BfME2Replay": 4,
}


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
    assert header.game_speed is None
    assert len(header.unknown_tail) == 6  # six trailing uint32s, no longer a uint16 lead
    assert header.unknown_tail == (0, 0, 1, 1, 0, 0)


def test_bfme2_header_decode(replay):
    header = replay.header
    assert header.crc_interval == 100  # REPLAY_CRC_INTERVAL, the heartbeat cadence
    assert header.abnormal_end_frame is None  # a recording that finalized normally
    assert replay.crashed is False
    assert header.reserved1 == b"\x00" * 9
    assert header.reserved2 == b"\x00" * 5
    assert header.local_player_index == 0  # PoV = OnlyTrueWK (slot 0)
    # data_checksum co-varies 1:1 with the metadata install id (GSID)
    assert header.data_checksum == 3242418404
    assert header.metadata.install_id == 0x7778


def test_metadata(replay):
    metadata = replay.header.metadata
    assert metadata.map_file == "maps/map edain nancurir"
    assert metadata.map_contents_mask == 0x387
    assert metadata.map_crc == 0xA72EAE30
    assert metadata.map_size == 575987
    assert metadata.seed == 92980671
    # BFME2-only keys survive verbatim, and get typed accessors
    assert metadata.values["GSID"] == "7778"
    assert metadata.install_id == 0x7778
    assert metadata.game_type_flag == 0
    assert metadata.si == -1
    assert metadata.game_rules == (0, 0, 1, 100, 1000, -1, -1, -1, -1, -1)
    assert metadata.starting_resources == 100
    assert metadata.command_points == 1000


def test_patch_fingerprint(replay, replay_2v3):
    # BFME2's fingerprint is the header's game-data checksum, as a comparable label.
    assert replay.header.patch_fingerprint == "Bfme2 data=0xC14360E4"
    # The three named root fixtures come from three different installs.
    vs_ai = parse_replay_from_path(REPLAY_VS_AI_PATH, only_header=True)
    fingerprints = {
        replay.header.patch_fingerprint,
        replay_2v3.header.patch_fingerprint,
        vs_ai.header.patch_fingerprint,
    }
    assert len(fingerprints) == 3


def test_patch_fingerprint_generals():
    # Generals has no single data checksum; its fingerprint combines the version split
    # with the separate exe/ini CRCs the header stores instead.
    header = ReplayHeader(
        game_type=ReplayGameType.Generals,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, tzinfo=UTC),
        num_timecodes=0,
        filename="",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=ReplayMetadata(),
        version_major=1,
        version_minor=8,
        exe_crc=0xDEADBEEF,
        ini_crc=0x1234,
    )
    assert header.patch_fingerprint == "Generals 1.8 exe=0xDEADBEEF ini=0x00001234"


def test_install_id_covaries_with_data_checksum():
    # The same install (GSID) always carries the same data_checksum, across every fixture.
    seen: dict[int, int] = {}
    for f in sorted(FIXTURES.glob("*.BfME2Replay")):
        header = parse_replay_from_path(f, only_header=True).header
        install = header.metadata.install_id
        assert seen.setdefault(install, header.data_checksum) == header.data_checksum


def test_slots(replay):
    slots = replay.header.metadata.slots
    assert len(slots) == 8
    assert [s.slot_type for s in slots[:2]] == [ReplaySlotType.Human, ReplaySlotType.Human]
    assert all(s.slot_type is ReplaySlotType.Empty for s in slots[2:])

    first, second = replay.header.metadata.players
    assert first.human_name == "OnlyTrueWK"
    assert (first.color, first.faction, first.team) == (1, 12, -1)
    assert first.ip == ipaddress.IPv4Address("93.209.249.175")  # 5DD1F9AF, big-endian
    assert first.port == 8094
    assert (first.accepted, first.has_map) == (True, True)
    assert first.nat_behavior == 0
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
        OrderArgumentType.Timestamp: 720,
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


@pytest.mark.parametrize(("name", "abnormal_end_frame"), CRASH_REPLAYS.items())
def test_crash_fixture_header(name, abnormal_end_frame):
    # A crash cuts the recording short: the header never finalizes (num_timecodes stays 0),
    # the abnormal-end frame carries the last completed heartbeat, and the chunk stream is
    # still fully parseable to end-of-file.
    replay = parse_replay_from_path(FIXTURES / name)
    assert replay.header.num_timecodes == 0
    assert replay.header.abnormal_end_frame == abnormal_end_frame
    assert replay.crashed is True
    assert replay.header.crc_interval == 100
    assert replay.chunks  # the order stream survives the missing header finalization


def test_crash_fixture_pov_from_header():
    # No `0x1D` marker survives a crash, so the point of view comes from the header's
    # local player index instead - and it must still name a real recording player.
    name = "858843b3-4a55-488b-be46-5762a51421df.BfME2Replay"
    replay = parse_replay_from_path(FIXTURES / name)
    assert not any(c.order_type == 0x1D for c in replay.chunks)
    pov = replay.header.local_player_index
    recorder = replay.header.metadata.players[pov]
    assert recorder.slot_type is ReplaySlotType.Human
    verdict = infer_winner(replay)
    assert verdict.recorder == recorder.human_name


@pytest.mark.parametrize(("name", "hero_count"), CUSTOM_HERO_REPLAYS.items())
def test_custom_hero_replay_parses(name, hero_count):
    # A Create-A-Hero header block once drifted the parser into the chunk stream ("unknown
    # order argument type 20"); its per-player ALAE2STR blobs must be consumed so the chunk
    # stream stays aligned to end-of-file.
    replay = parse_replay_from_path(FIXTURES / name)
    header = replay.header
    assert len(header.custom_heroes) == hero_count
    assert all(blob.startswith(b"ALAE2STR") for blob in header.custom_heroes)
    # The custom-hero list replaces the six-word unknown_tail with a shortened raw tail whose
    # closing five words are the usual (0, 1, 1, 0, 0).
    assert header.unknown_tail == ()
    assert len(header.custom_hero_tail) == 24 - len(header.metadata.players)
    assert header.custom_hero_tail.endswith(struct.pack("<5I", 0, 1, 1, 0, 0))
    # Alignment proof: the canonical match-start first chunk, and every chunk maps to a slot.
    assert replay.chunks[0].timecode == 1
    assert replay.chunks[0].order_type == 0x3EC
    assert all(replay.slot_for(chunk) is not None for chunk in replay.chunks)


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
    assert slot.ip == ipaddress.IPv4Address("93.209.249.175")
    assert slot.port == 8094
    assert (slot.accepted, slot.has_map) == (True, True)
    assert slot.nat_behavior == 0
    assert slot.reserved == (1, 0)
    assert slot.raw.startswith("HOnlyTrueWK")


def test_human_slot_flags_from_tt():
    # The TT field's two chars are the accepted and has-map flags independently.
    slot = ReplaySlot.parse("HGuest,C0A80205,8094,TF,-1,12,5,0,0,1,0")
    assert (slot.accepted, slot.has_map) == (True, False)
    assert slot.ip == ipaddress.IPv4Address("192.168.2.5")


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


def _metadata_from(raw: str, game_type: ReplayGameType) -> ReplayMetadata:
    stream = BinaryStream(BytesIO(raw.encode("ascii") + b"\x00"))
    return ReplayMetadata.parse(stream, game_type)


def test_map_mask_is_fixed_width():
    # The mask is a fixed-width hex prefix (three digits in BFME2), so a map path
    # that itself starts with hex-alphabet characters must survive intact.
    metadata = _metadata_from("M=387data castle defence;", ReplayGameType.Bfme2)
    assert metadata.map_contents_mask == 0x387
    assert metadata.map_file == "data castle defence"


def test_map_mask_generals_width():
    # Generals writes the mask as `%2.2x` - exactly two hex digits.
    metadata = _metadata_from("M=87maps/alpine assault;", ReplayGameType.Generals)
    assert metadata.map_contents_mask == 0x87
    assert metadata.map_file == "maps/alpine assault"


def test_map_mask_malformed_prefix():
    # A value with no valid hex prefix is treated as all path, mask zero.
    metadata = _metadata_from("M=maps/khand;", ReplayGameType.Bfme2)
    assert metadata.map_contents_mask == 0
    assert metadata.map_file == "maps/khand"
