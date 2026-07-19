"""Tests for `sage_replay.retarget`: translate a synthetic replay under game A, retarget the
document to game B (every table shuffled, factions swapped, the hero roster reordered) and
check each id space lands on B's indices; the identity conversion (A back to A) reproduces the
original bytes exactly; a donor replay re-identifies the header; and every unresolvable name
collects into one `RetargetError`."""

from datetime import UTC, datetime
from io import BytesIO

import pytest

from sage_replay.narrate import GameData
from sage_replay.replay import (
    Order,
    OrderArgument,
    OrderArgumentType,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplayTimestamp,
    integer_arguments,
    parse_replay,
)
from sage_replay.retarget import RetargetError, retarget
from sage_replay.serialize import serialize_replay
from sage_replay.translated import TranslatedReplay
from sage_utils.stream import BinaryStream

_T = OrderArgumentType

# The metadata string of the synthetic recording, as game A wrote it: two humans on factions
# 0 (Gondor) and 1 (Mordor), an empty slot, a GSID, and an unknown key that must survive.
_METADATA_A = (
    "M=387maps/synthetic;MC=4A0B;SD=42;GSID=deadbeef;ZZ=kept;"
    "S=HA,7F000001,8088,TT,0,0,2,1,1,0:HB,7F000002,8088,TT,3,1,0,0,1,0:X:;"
)


class _obj:
    def __init__(self, fields: dict, parent=None) -> None:
        self._fields = fields
        if parent is not None:
            self.parent = parent


def _data_a() -> GameData:
    """The recording game: the id spaces the synthetic replay's raw integers index."""
    return GameData(
        object_order=["GondorBarracks", "OrcHorde", "Boromir", "MordorFighter"],
        objects={
            "GondorBarracks": _obj({"KindOf": "STRUCTURE SELECTABLE", "Side": "Men"}),
            "OrcHorde": _obj({"KindOf": "HORDE SELECTABLE", "Side": "Mordor"}),
            "Boromir": _obj({"KindOf": "HERO SELECTABLE", "Side": "Men"}),
            "MordorFighter": _obj({"KindOf": "SELECTABLE", "Side": "Mordor"}),
        },
        specialpowers=["SpecialAbilityHeal"],
        sciences=["ScienceOne", "ScienceTwo"],
        upgrades=["DefaultUpgrade", "Upgrade_ForgedBlades"],
        displaynames={},
        faction_labels=["FactionGondor", "FactionMordor"],
        faction_sides=["Men", "Mordor"],
        faction_names=["FactionGondor", "FactionMordor"],
        hero_rosters=[["Boromir"], []],
        hero_build_times={"Boromir": 30.0},
    )


def _data_b() -> GameData:
    """The target game: same code names, every registration order shuffled - new templates
    inserted, the science and faction orders swapped, and the Gondor revive roster gaining a
    CreateAHero placeholder ahead of Boromir."""
    return GameData(
        object_order=["NewThing", "MordorFighter", "GondorBarracks", "Boromir", "OrcHorde"],
        objects={},
        specialpowers=["SomethingElse", "SpecialAbilityHeal"],
        sciences=["ScienceTwo", "ScienceOne"],
        upgrades=["DefaultUpgrade", "Upgrade_Other", "Upgrade_ForgedBlades"],
        displaynames={},
        faction_labels=["FactionMordor", "FactionGondor"],
        faction_sides=["Mordor", "Men"],
        faction_names=["FactionMordor", "FactionGondor"],
        hero_rosters=[[], ["CreateAHero", "Boromir"]],
        hero_build_times={"Boromir": 30.0},
    )


def _metadata(raw: str) -> ReplayMetadata:
    return ReplayMetadata.parse(
        BinaryStream(BytesIO(raw.encode("ascii") + b"\x00")), ReplayGameType.Bfme2
    )


def _chunk(order_type: int, args: list, *, timecode: int, number: int = 3) -> ReplayChunk:
    order = Order(player_index=number - 1, order_type=order_type)
    order.arguments = [OrderArgument(t, v) for t, v in args]
    return ReplayChunk(timecode=timecode, order_type=order_type, number=number, order=order)


def _source_replay() -> ReplayFile:
    """A fully serializable synthetic recording under game A, exercising every id space:
    a build, a unit recruit + cancel, a fortress-hero recruit, an upgrade, a spellbook
    science, and a power cast."""
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime.fromtimestamp(1_700_000_000, tz=UTC),
        end_time=datetime.fromtimestamp(1_700_000_300, tz=UTC),
        num_timecodes=60,
        filename="Last Replay",
        timestamp=ReplayTimestamp(2026, 1, 4, 1, 12, 30, 5, 120),
        version="2.01.0001 source",
        build_date="2026-01-01",
        metadata=_metadata(_METADATA_A),
        local_player_index=0,
        local_player_raw="0",
        crc_interval=100,
        abnormal_end_frame=None,
        reserved1=b"\x00" * 9,
        data_checksum=0x11111111,
        reserved2=b"\x00" * 5,
        unknown_tail=(0, 0, 1, 1, 0, 0),
    )
    chunks = [
        _chunk(0x419, [(_T.Integer, 1), (_T.Position, (1.0, 2.0, 3.0))], timecode=5),
        _chunk(0x417, [(_T.Boolean, False), (_T.Integer, 2), (_T.Integer, 0)], timecode=10),
        _chunk(0x418, [(_T.Boolean, False), (_T.Integer, 2), (_T.Boolean, False)], timecode=11),
        _chunk(0x417, [(_T.Boolean, True), (_T.Integer, 0), (_T.Integer, 0)], timecode=20),
        _chunk(0x415, [(_T.Integer, 4)], timecode=30),
        _chunk(0x414, [(_T.Integer, 3), (_T.Integer, 2)], timecode=40),
        _chunk(0x410, [(_T.Integer, 1), (_T.Integer, 0)], timecode=50),
        _chunk(
            0x417, [(_T.Boolean, False), (_T.Integer, 4), (_T.Integer, 0)], number=4, timecode=60
        ),
    ]
    return ReplayFile(header=header, chunks=chunks)


def _document(tmp_path) -> tuple[TranslatedReplay, bytes]:
    """The synthetic recording translated under game A, plus its exact binary bytes."""
    data = serialize_replay(_source_replay())
    replay_path = tmp_path / "source.BfME2Replay"
    replay_path.write_bytes(data)
    document = TranslatedReplay.from_replay(replay_path, parse_replay(data), _data_a())
    return document, data


def _ints(replay: ReplayFile, timecode: int) -> list:
    chunk = next(c for c in replay.chunks if c.timecode == timecode)
    return integer_arguments(chunk)


def test_identity_retarget_is_byte_exact(tmp_path):
    # Source game == target game and no donor: the conversion must reproduce the recording
    # exactly - the definition of "nothing was lost on the way through the document".
    document, data = _document(tmp_path)
    assert serialize_replay(retarget(document, _data_a())) == data


def test_retarget_remaps_every_id_space(tmp_path):
    document, _ = _document(tmp_path)
    converted = retarget(document, _data_b())

    assert _ints(converted, 5)[0] == 3  # GondorBarracks: B object_order index 2 + 1
    assert _ints(converted, 10)[0] == 5  # OrcHorde recruit: index 4 + 1
    assert _ints(converted, 11)[0] == 5  # ... and its cancel follows it
    assert _ints(converted, 20)[0] == 1  # Boromir: slot 1 behind B's CreateAHero placeholder
    assert _ints(converted, 30)[0] == 5  # Upgrade_ForgedBlades: 0-based index 2 + 3
    assert _ints(converted, 40) == [3, 1]  # chunk number stays raw; ScienceTwo is B's id 1
    assert _ints(converted, 50)[0] == 2  # SpecialAbilityHeal: index 1 + 1
    assert _ints(converted, 60)[0] == 2  # MordorFighter: index 1 + 1

    # The slot faction fields now index B's PlayerTemplate order (Gondor 0 -> 1, Mordor 1 -> 0)
    # while every other metadata byte - unknown keys included - survived verbatim.
    metadata = converted.header.metadata
    assert [slot.faction for slot in metadata.players] == [1, 0]
    assert metadata.values["ZZ"] == "kept"
    assert metadata.values["GSID"] == "deadbeef"  # no donor: the source identity stays
    assert metadata.map_file == "maps/synthetic"

    # The emitted file is a real replay: it serializes and parses back.
    assert parse_replay(serialize_replay(converted)).header.metadata.players[0].faction == 1


def test_donor_reidentifies_the_header(tmp_path):
    document, _ = _document(tmp_path)
    donor_header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime.fromtimestamp(1_800_000_000, tz=UTC),
        end_time=datetime.fromtimestamp(1_800_000_100, tz=UTC),
        num_timecodes=1,
        filename="donor",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="2.02.9999 target",
        build_date="2026-06-01",
        metadata=_metadata("GSID=feedf00d;"),
        data_checksum=0x22222222,
    )
    converted = retarget(document, _data_b(), donor=ReplayFile(header=donor_header))
    assert converted.header.version == "2.02.9999 target"
    assert converted.header.build_date == "2026-06-01"
    assert converted.header.data_checksum == 0x22222222
    assert converted.header.metadata.values["GSID"] == "feedf00d"
    # Everything that is not patch identity still comes from the recording, not the donor.
    assert converted.header.filename == "Last Replay"
    assert converted.header.num_timecodes == 60


def test_unresolvable_names_collect_into_one_error(tmp_path):
    document, _ = _document(tmp_path)
    target = _data_b()
    target.object_order.remove("OrcHorde")  # breaks the recruit and its cancel
    target.sciences.remove("ScienceTwo")
    with pytest.raises(RetargetError) as info:
        retarget(document, target)
    failures = info.value.failures
    assert len(failures) == 3
    assert sum("'OrcHorde'" in f for f in failures) == 2
    assert any("'ScienceTwo'" in f for f in failures)


def test_missing_target_faction_is_an_error(tmp_path):
    document, _ = _document(tmp_path)
    target = _data_b()
    target.faction_names[1] = "FactionRenamed"  # FactionGondor is gone
    with pytest.raises(RetargetError, match="FactionGondor"):
        retarget(document, target)


def test_raw_int_in_an_id_slot_is_an_error(tmp_path):
    # An id the source translation could not resolve indexes the SOURCE game; emitting it
    # into the target file would be silently wrong, so it must fail loudly instead.
    document, _ = _document(tmp_path)
    build = next(chunk for chunk in document.chunks if chunk[1] == "0x419")
    build[3][0][1] = 99
    with pytest.raises(RetargetError, match="never resolved"):
        retarget(document, _data_a())


def test_v1_document_is_refused(tmp_path):
    document, _ = _document(tmp_path)
    payload = document.to_dict()
    del payload["header"]
    payload["format_version"] = 1
    with pytest.raises(ValueError, match="v1"):
        retarget(TranslatedReplay.from_dict(payload), _data_a())
