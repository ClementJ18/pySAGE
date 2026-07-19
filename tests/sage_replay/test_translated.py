"""Tests for `sage_replay.translated`: the replay-shaped document's dict/JSON round trip, the
strict `from_dict` validation contract (a wrong schema raises, an old events-shaped payload
reads as unsupported), id translation on a synthetic replay + GameData, and rehydration parity
(`compute_stats` over a fresh replay and its rehydrated translation gives equal event lists,
resolved hero names pass through, and a lobby-Random's inferred faction is stored)."""

from datetime import UTC, datetime

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
    ReplaySlot,
    ReplaySlotType,
    ReplayTimestamp,
)
from sage_replay.stats import compute_stats
from sage_replay.translated import FORMAT, FORMAT_VERSION, TranslatedReplay

_T = OrderArgumentType


class _obj:
    """Stand-in for a loaded Object: a `_fields` dict, optional ChildObject-style parent."""

    def __init__(self, fields: dict, parent=None) -> None:
        self._fields = fields
        if parent is not None:
            self.parent = parent


def _data() -> GameData:
    """A GameData with two factions (Gondor/Mordor), a small object/upgrade/science/power table,
    and hero rosters - enough to translate every id space and to infer a Random's faction from
    its build orders' Sides."""
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


def _human(name: str, *, team: int, faction: int = 0, color: int = 0, start: int = 0) -> ReplaySlot:
    return ReplaySlot(
        slot_type=ReplaySlotType.Human,
        human_name=name,
        faction=faction,
        team=team,
        color=color,
        start_position=start,
    )


def _chunk(order_type: int, args: list, *, timecode: int = 0, number: int = 3) -> ReplayChunk:
    order = Order(player_index=number - 1, order_type=order_type)
    order.arguments = [OrderArgument(t, v) for t, v in args]
    return ReplayChunk(timecode=timecode, order_type=order_type, number=number, order=order)


def _replay(slots: list[ReplaySlot], chunks: list[ReplayChunk]) -> ReplayFile:
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),  # 300 s span
        num_timecodes=300,  # 1 timecode per second
        filename="synthetic",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=ReplayMetadata(map_file="maps/synthetic", slots=slots),
        local_player_index=0,
    )
    return ReplayFile(header=header, chunks=chunks)


def _translated(tmp_path, replay: ReplayFile) -> tuple[TranslatedReplay, object]:
    """A translated document plus the replay-file path it was produced from."""
    replay_path = tmp_path / "game.BfME2Replay"
    replay_path.write_bytes(b"synthetic replay bytes")
    document = TranslatedReplay.from_replay(replay_path, replay, _data())
    return document, replay_path


def _full_replay() -> ReplayFile:
    """A replay exercising every id space: builds, a unit recruit + cancel, a hero recruit, an
    upgrade research, a spellbook science, and a power cast."""
    slots = [_human("A", team=1, faction=0), _human("B", team=0, faction=1)]
    chunks = [
        _chunk(0x419, [(_T.Integer, 1), (_T.Position, (1.0, 2.0, 3.0))], timecode=5),  # Barracks
        _chunk(0x417, [(_T.Boolean, False), (_T.Integer, 2), (_T.Integer, 0)], timecode=10),  # Orc
        _chunk(0x418, [(_T.Boolean, False), (_T.Integer, 2), (_T.Boolean, False)], timecode=11),
        _chunk(0x417, [(_T.Boolean, True), (_T.Integer, 0), (_T.Integer, 0)], timecode=20),  # Boro
        _chunk(0x415, [(_T.Integer, 4)], timecode=30),  # Upgrade_ForgedBlades
        _chunk(0x414, [(_T.Integer, 3), (_T.Integer, 2)], timecode=40),  # ScienceTwo (2nd int)
        _chunk(0x410, [(_T.Integer, 1), (_T.Integer, 0)], timecode=50),  # SpecialAbilityHeal
        # Player B recruits a Mordor fighter, so a Random-faction pass could vote its Side.
        _chunk(
            0x417, [(_T.Boolean, False), (_T.Integer, 4), (_T.Integer, 0)], number=4, timecode=60
        ),
    ]
    return _replay(slots, chunks)


def test_dict_round_trip_is_lossless(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    rebuilt = TranslatedReplay.from_dict(document.to_dict())
    assert rebuilt == document


def test_json_file_round_trip(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    path = tmp_path / "shared.json"
    document.write(path)
    assert TranslatedReplay.read(path) == document
    payload = TranslatedReplay.read(path).to_dict()
    assert payload["format"] == FORMAT
    assert payload["format_version"] == FORMAT_VERSION


def test_translation_resolves_every_id_space(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    by_order = {chunk[1]: chunk for chunk in document.chunks}

    # A build's first Integer becomes the template name; the Position stays a raw [x, y, z].
    build = by_order["0x419"]
    assert build[3][0] == ["int", "GondorBarracks"]
    assert build[3][1] == ["pos", [1.0, 2.0, 3.0]]

    # A unit recruit and its cancel both resolve to the same template name, so their id match
    # survives translation; the trailing Integer/Boolean arguments stay raw.
    recruit = next(c for c in document.chunks if c[1] == "0x417" and c[3][1] == ["int", "OrcHorde"])
    assert recruit[3][0] == ["bool", False]
    cancel = next(c for c in document.chunks if c[1] == "0x418")
    assert cancel[3][1] == ["int", "OrcHorde"]

    # The upgrade, the spellbook science (the SECOND Integer), and the power all resolve.
    research = next(c for c in document.chunks if c[1] == "0x415")
    assert research[3][0] == ["int", "Upgrade_ForgedBlades"]
    science = next(c for c in document.chunks if c[1] == "0x414")
    assert science[3][0] == ["int", 3]  # the issuer's chunk number stays raw
    assert science[3][1] == ["int", "ScienceTwo"]
    cast = next(c for c in document.chunks if c[1] == "0x410")
    assert cast[3][0] == ["int", "SpecialAbilityHeal"]


def test_hero_recruit_resolves_to_a_name(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    hero = next(c for c in document.chunks if c[1] == "0x417" and c[3][0] == ["bool", True])
    # The revive-submenu position 0 resolves to the faction's first roster hero, as a str.
    assert hero[3][1] == ["int", "Boromir"]


def test_slots_carry_faction_names(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    assert [p.faction for p in document.players] == ["FactionGondor", "FactionMordor"]
    assert document.players[0].type == "human"
    assert document.game_type == "Bfme2"
    assert document.map == "maps/synthetic"
    assert document.local_player_index == 0


def test_out_of_range_id_stays_raw(tmp_path):
    replay = _replay(
        [_human("A", team=0, faction=0)],
        [_chunk(0x419, [(_T.Integer, 99)], timecode=1)],  # no such template
    )
    document, _ = _translated(tmp_path, replay)
    assert document.chunks[0][3][0] == ["int", 99]


def test_matches_replay_by_size_and_content(tmp_path):
    document, replay_path = _translated(tmp_path, _full_replay())
    assert document.matches_replay(replay_path)

    original = replay_path.read_bytes()
    replay_path.write_bytes(bytes(reversed(original)))  # same size, different bytes
    assert not document.matches_replay(replay_path)

    replay_path.write_bytes(original)
    assert document.matches_replay(replay_path)
    assert not document.matches_replay(tmp_path / "missing.BfME2Replay")


def test_from_dict_ignores_unknown_keys(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    payload = document.to_dict()
    payload["produced_by"] = "someone else's tool"
    payload["players"][0]["notes"] = "annotated"
    assert TranslatedReplay.from_dict(payload) == document


def test_from_dict_rejects_wrong_magic_and_version(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    with pytest.raises(ValueError, match="not a"):
        TranslatedReplay.from_dict(document.to_dict() | {"format": "something/else"})
    with pytest.raises(ValueError, match="unsupported format_version"):
        TranslatedReplay.from_dict(document.to_dict() | {"format_version": FORMAT_VERSION + 1})
    with pytest.raises(ValueError, match="JSON object"):
        TranslatedReplay.from_dict(["not", "an", "object"])


def test_from_dict_rejects_missing_and_malformed(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    missing = document.to_dict()
    del missing["chunks"]
    with pytest.raises(ValueError, match="missing 'chunks'"):
        TranslatedReplay.from_dict(missing)

    bad_chunk = document.to_dict()
    bad_chunk["chunks"] = [[5, "0x419"]]  # too short
    with pytest.raises(ValueError, match="malformed chunk"):
        TranslatedReplay.from_dict(bad_chunk)

    bad_arg = document.to_dict()
    bad_arg["chunks"] = [[5, "0x419", 3, [["bogus", 1]]]]  # unknown tag
    with pytest.raises(ValueError, match="unknown chunk argument tag"):
        TranslatedReplay.from_dict(bad_arg)


def test_v2_document_carries_the_raw_header(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    payload = document.to_dict()
    assert payload["format_version"] == 2
    header = payload["header"]
    assert header["start_time"] == int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    assert header["metadata"] == ""  # the synthetic replay carries no raw metadata string
    assert header["local_player_raw"] == ""
    assert header["abnormal_end_frame"] is None
    rebuilt = TranslatedReplay.from_dict(payload)
    assert rebuilt.header == document.header


def test_v1_document_still_loads_analysis_only(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    payload = document.to_dict()
    del payload["header"]
    payload["format_version"] = 1
    loaded = TranslatedReplay.from_dict(payload)
    assert loaded.header is None
    # Analysis rehydration is untouched by the missing header ...
    assert loaded.to_replay(_data()).translated is True
    # ... and re-serializing keeps it honestly versioned as 1.
    assert loaded.to_dict()["format_version"] == 1


def test_v2_document_without_header_is_rejected(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    payload = document.to_dict()
    del payload["header"]
    with pytest.raises(ValueError, match="missing 'header'"):
        TranslatedReplay.from_dict(payload)


def test_from_dict_rejects_old_events_shaped_document():
    # The previous events-shaped document also said `format_version: 1` but keyed its per-player
    # data under `events`, with no `chunks` at all - the missing key makes it read as unsupported.
    legacy = {
        "format": FORMAT,
        "format_version": 1,
        "replay": "game.BfME2Replay",
        "size": 10,
        "sha256": "0" * 64,
        "fingerprint": "Bfme2 data=0x0",
        "assume_pov_won": True,
        "duration": 180.0,
        "players": [{"name": "A", "team": 0, "faction": "Men", "events": []}],
        "sides": {},
    }
    with pytest.raises(ValueError, match="missing 'game_type'"):
        TranslatedReplay.from_dict(legacy)


def test_read_raises_value_error_for_non_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not JSON"):
        TranslatedReplay.read(path)


def test_rehydration_gives_equal_stats(tmp_path):
    # The whole point: analysis over a rehydrated translation matches analysis over the fresh
    # parse, so all the stats semantics moved to load time unchanged.
    replay = _full_replay()
    data = _data()
    document, _ = _translated(tmp_path, replay)
    rehydrated = document.to_replay(data)
    assert rehydrated.translated is True

    fresh = {per.player: per.events for per in compute_stats(replay, data)}
    reloaded = {per.player: per.events for per in compute_stats(rehydrated, data)}
    assert reloaded == fresh
    # The resolved hero landed under `heroes` by name on both paths.
    reloaded_stats = {per.player: per for per in compute_stats(rehydrated, data)}
    assert reloaded_stats["A"].heroes == {"Boromir": 1}
    assert reloaded_stats["A"].units == {}  # the recruited Orc was cancelled


def test_rehydration_reproduces_seconds_per_frame(tmp_path):
    document, _ = _translated(tmp_path, _full_replay())
    rehydrated = document.to_replay(_data())
    assert rehydrated.seconds_per_frame == document.seconds_per_frame


def test_random_faction_is_inferred_and_stored(tmp_path):
    # A lobby-Random slot (faction -1) carries no roster; its rolled faction is read back from
    # the Sides of what it built, stored as `inferred_faction`, and used to index the paired
    # game's PlayerTemplate on rehydration.
    slots = [_human("R", team=0, faction=-1)]
    chunks = [
        _chunk(0x417, [(_T.Boolean, False), (_T.Integer, 2), (_T.Integer, 0)]),  # OrcHorde: Mordor
    ]
    document, _ = _translated(tmp_path, _replay(slots, chunks))
    assert document.players[0].faction is None
    assert document.players[0].inferred_faction == "FactionMordor"

    rehydrated = document.to_replay(_data())
    assert rehydrated.header.metadata.players[0].faction == 1  # Mordor's PlayerTemplate index


def test_observer_slot_round_trips(tmp_path):
    observer = ReplaySlot(
        slot_type=ReplaySlotType.Human,
        human_name="Caster",
        faction=ReplaySlot.OBSERVER_FACTION,
        team=-1,
    )
    document, _ = _translated(tmp_path, _replay([observer], []))
    assert document.players[0].observer is True
    assert document.players[0].faction is None
    rehydrated = document.to_replay(_data())
    assert rehydrated.header.metadata.players[0].is_observer
