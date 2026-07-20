"""End-to-end parsing of the fixture BFME2 skirmish saves plus data-free unit tests for the
container framing. Two saves on the same map with different faction match-ups (save 1: Dwarves
vs Wild; save 2: Mordor vs Men) cross-validate the decoders that were reversed from a single
sample. The saves live in `tests/sage_save/fixtures/`; tests skip cleanly when a save is
absent."""

import json
import struct
from datetime import datetime
from pathlib import Path

import pytest

from sage_save import (
    Chunk,
    Reference,
    SaveFile,
    SaveHeader,
    XferReader,
    apply_json,
    check_references,
    check_save,
    decode_campaign,
    decode_game_logic,
    decode_game_state,
    decode_game_state_map,
    extract_map,
    harvest_player_references,
    harvest_references,
    iter_objects,
    parse_save,
    parse_save_from_path,
    save_to_dict,
    save_to_json,
    write_save,
)
from sage_save.players import NameList, _scan
from sage_save.save import BLOCK_MARKER, EOF_TOKEN, MAGIC_EALA, MAGIC_RTS
from tests.sage_save.corpus import CAH_SKIRMISH

# End-to-end parsing of the real .BfME2Skirmish binary fixtures, so this module is part of the
# full suite rather than the data-free core (CONVENTIONS.md rule 7). The synthetic payload
# round-trips that stay in the core live in the other sage_save test modules.
pytestmark = pytest.mark.full

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAVE_PATH = FIXTURES / "Saved Game 1.BfME2Skirmish"
SAVE2_PATH = FIXTURES / "Saved Game 2.BfME2Skirmish"
SAVE3_PATH = FIXTURES / "Saved Game 3.BfME2Skirmish"
ALL_SAVES = [SAVE_PATH, SAVE2_PATH, SAVE3_PATH]


@pytest.fixture(params=ALL_SAVES, ids=lambda p: p.stem.replace(" ", "_"))
def any_save_path(request):
    """Each authored save path in turn - for invariants that must hold across faction match-ups."""
    if not request.param.is_file():
        pytest.skip(f"fixture save not present: {request.param.name}")
    return request.param


class FakeGame:
    """The `Game.lookup` slice `sage_save.xref` needs: `defined` names resolve (exact, then
    case-insensitive → the canonical spelling); everything else is missing."""

    def __init__(self, tables: dict[str, set[str]]):
        self.tables = tables

    def lookup(self, key: str, name: str):
        table = self.tables.get(key, set())
        if name in table:
            return object(), name
        for canonical in table:
            if canonical.lower() == name.lower():
                return object(), canonical
        return None, name


@pytest.fixture(scope="module")
def raw() -> bytes:
    if not SAVE_PATH.is_file():
        pytest.skip("fixture save not present")
    return SAVE_PATH.read_bytes()


@pytest.fixture(scope="module")
def save():
    if not SAVE_PATH.is_file():
        pytest.skip("fixture save not present")
    return parse_save_from_path(SAVE_PATH)


def test_header(save):
    assert save.header.magic_eala == MAGIC_EALA
    assert save.header.magic_rts == MAGIC_RTS
    assert save.header.container_id == "EALA RTS2"
    assert (save.header.value1, save.header.value2) == (1, 0)


def test_chunk_inventory(save):
    # The first and last chunks bracket the whole stream; both are BFME2-specific additions
    # absent from the Generals registry.
    assert save.chunks[0].name == "CHUNK_LivingWorldLogic"
    assert save.chunks[-1].name == "CHUNK_FireLogicSystem"
    assert save.chunk("CHUNK_GameLogic") is not None
    # case-insensitive, as the engine matches
    assert save.chunk("chunk_gamelogic") is save.chunk("CHUNK_GameLogic")
    assert save.chunk("CHUNK_DoesNotExist") is None


def test_round_trip_bytes(save, raw):
    assert write_save(save) == raw


def test_game_state(save):
    header = decode_game_state(save.chunk("CHUNK_GameState"))
    assert header.version == 1
    assert header.description == "Saved Game 1"
    assert header.user_name == "Clem"
    # an ordinary save brought in no hero: the hero-name string is empty
    assert header.hero_name == ""
    assert header.map_name == r"maps\map mp harlindon\map mp harlindon.map"
    assert header.saved_at == datetime(2026, 7, 4, 21, 9, 6, 253000)


def test_create_a_hero_save():
    """A create-a-hero skirmish save populates the GameState `hero_name` string with the hero's
    display name, and carries the recruited hero as a live `CreateAHero` object - the two places
    the created hero is visible in the save."""
    if not CAH_SKIRMISH.is_file():
        pytest.skip(f"fixture save not present: {CAH_SKIRMISH.name}")
    save = parse_save_from_path(CAH_SKIRMISH)
    header = decode_game_state(save.chunk("CHUNK_GameState"))
    assert header.hero_name == "Berethor"
    assert header.user_name == "Clem"  # the profile name is a separate, later string
    templates = {o.template_name for o in decode_game_logic(save.chunk("CHUNK_GameLogic")).objects}
    assert "CreateAHero" in templates


def test_game_state_map(save):
    gsm = decode_game_state_map(save.chunk("CHUNK_GameStateMap"))
    assert gsm.version == 2
    assert gsm.game_mode == 2  # skirmish
    assert gsm.save_map_name == r"save\map mp harlindon.map"
    assert gsm.map_data[:4] == b"EAR\x00"  # a plain on-disk (RefPack) .map
    assert extract_map(save) == gsm.map_data


def test_extracted_map_parses_with_sage_map(save, tmp_path):
    parse = pytest.importorskip("sage_map.map").parse_map_from_path
    out = tmp_path / "embedded.map"
    out.write_bytes(extract_map(save))
    parse(out)  # raises if the extracted bytes are not a valid map


def test_campaign(save):
    campaign = decode_campaign(save.chunk("CHUNK_Campaign"))
    assert campaign.version == 1
    assert campaign.current_campaign == ""  # skirmish: no campaign


def test_game_logic(save):
    state = decode_game_logic(save.chunk("CHUNK_GameLogic"))
    assert state.version == 8
    assert state.frame == 2
    assert len(state.templates) == 76
    assert state.templates[1] == "RockGrey06"
    # Every object resolves to a known template (the walk stayed aligned end to end).
    assert len(state.objects) == 358
    assert all(o.template_id in state.templates for o in state.objects)
    assert all(o.template_name in state.templates.values() for o in state.objects)
    # Object ids are the runtime ids, unique per live object.
    assert len({o.object_id for o in state.objects}) == len(state.objects)


def test_iter_objects(save):
    objects = iter_objects(save)
    names = {o.template_name for o in objects}
    assert "DwarvenGuardian" in names
    assert len(objects) == 358


def test_harvest_references(save):
    refs = harvest_references(save)
    by_name = {r.name: r for r in refs}
    # 76 GameLogic TOC templates + the ScriptEngine object-type/attack-priority template
    # names (all non-fatal), merged per name ...
    objects = [r for r in refs if r.kind == "object_template"]
    assert len(objects) == 375
    assert all(not r.fatal for r in objects)
    assert by_name["DwarvenGuardian"].count == 37  # live-object count rides along
    # ... plus the fatal upgrade/science names harvested from CHUNK_Players.
    assert by_name["Upgrade_DwarfFaction"].fatal
    assert by_name["Upgrade_DwarfFaction"].kind == "upgrade"
    assert by_name["SCIENCE_DWARVES"].kind == "science"
    assert {r.name for r in harvest_player_references(save)} == {
        "Upgrade_DwarfFaction",
        "Upgrade_WildFaction",
        "Upgrade_EvilDualEconomyChoice",
        "Upgrade_GoblinDualEconomyChoice",
        "SCIENCE_DWARVES",
        "SCIENCE_Rebuild",
        "SCIENCE_WILD",
        "SCIENCE_CaveBats",
    }


def test_check_save_all_defined(save):
    # A game defining every name the save carries (each in its own table) yields no findings.
    tables: dict[str, set[str]] = {"objects": set(), "upgrades": set(), "sciences": set()}
    table_for = {"object_template": "objects", "upgrade": "upgrades", "science": "sciences"}
    for ref in harvest_references(save):
        tables[table_for[ref.kind]].add(ref.name)
    assert check_save(save, FakeGame(tables)) == []


def test_check_save_flags_fatal_upgrade(save):
    # A game that dropped one upgrade (as Edain did with Upgrade_GoblinDualEconomyChoice) yields
    # a fatal finding sorted ahead of any non-fatal object-template danglers.
    refs = harvest_references(save)
    tables: dict[str, set[str]] = {"objects": set(), "upgrades": set(), "sciences": set()}
    table_for = {"object_template": "objects", "upgrade": "upgrades", "science": "sciences"}
    for ref in refs:
        if ref.name != "Upgrade_GoblinDualEconomyChoice":
            tables[table_for[ref.kind]].add(ref.name)
    findings = check_save(save, FakeGame(tables))
    assert len(findings) == 1
    assert findings[0].reference.name == "Upgrade_GoblinDualEconomyChoice"
    assert findings[0].reference.fatal


def test_scan_name_list_shape():
    # version 1 + u16 count(2) + two Upgrade_ names (each 11 chars) is recognised.
    payload = b"\x01\x02\x00\x0bUpgrade_Foo\x0bUpgrade_Bar"
    [found] = _scan(payload, "upgrade", 2, "Upgrade_")
    assert isinstance(found, NameList)
    assert found.names == ["Upgrade_Foo", "Upgrade_Bar"]
    assert _scan(b"\x02" + payload[1:], "upgrade", 2, "Upgrade_") == []  # version != 1
    # a run with no conventionally-prefixed name is rejected (precision guard)
    assert _scan(b"\x01\x01\x00\x03abc", "upgrade", 2, "Upgrade_") == []


def test_check_references_missing_and_case():
    refs = [
        Reference("object_template", "DwarvenGuardian", 37, fatal=False),
        Reference("object_template", "RemovedUnit", 3, fatal=False),
        Reference("object_template", "rockgrey06", 1, fatal=False),  # wrong case
    ]
    game = FakeGame({"objects": {"DwarvenGuardian", "RockGrey06"}})
    findings = check_references(refs, game)
    assert [(f.reference.name, f.status, f.canonical) for f in findings] == [
        ("RemovedUnit", "missing", None),
        ("rockgrey06", "case-mismatch", "RockGrey06"),
    ]


# --- invariants that must hold for every authored save, whatever the factions ---


def test_any_save_round_trips(any_save_path):
    raw = any_save_path.read_bytes()
    assert write_save(parse_save(raw)) == raw


def test_any_save_chunk_bookends(any_save_path):
    save = parse_save_from_path(any_save_path)
    assert save.chunks[0].name == "CHUNK_LivingWorldLogic"
    assert save.chunks[-1].name == "CHUNK_FireLogicSystem"
    assert len(save.chunks) == 32


def test_any_save_game_state(any_save_path):
    header = decode_game_state(parse_save_from_path(any_save_path).chunk("CHUNK_GameState"))
    assert header.version == 1
    assert header.description.startswith("Saved Game")
    assert header.user_name == "Clem"
    # a portable map path, backslash-separated, whatever the map
    assert header.map_name.startswith("maps\\") and header.map_name.endswith(".map")
    assert isinstance(header.saved_at, datetime)
    # An ordinary skirmish save brought in no hero: the hero-name string is empty.
    assert header.hero_name == ""
    # The undecoded regions are the same constant in every skirmish save (three maps): the
    # leading save-type field, the u32 after the map name (0 in skirmish), and no post-profile
    # trailing (the WotR living-world state that region would carry is absent here).
    assert header.leading == bytes.fromhex("030200000000")
    assert header.post_map == bytes.fromhex("00000000")
    assert header.trailing == b""


def test_any_save_embedded_map(any_save_path, tmp_path):
    parse = pytest.importorskip("sage_map.map").parse_map_from_path
    save = parse_save_from_path(any_save_path)
    gsm = decode_game_state_map(save.chunk("CHUNK_GameStateMap"))
    assert gsm.game_mode == 2
    assert gsm.map_data[:4] == b"EAR\x00"  # a plain on-disk (RefPack) .map
    out = tmp_path / "embedded.map"
    out.write_bytes(extract_map(save))
    parse(out)  # raises if the extracted bytes are not a valid map


def test_any_save_object_walk_aligned(any_save_path):
    state = decode_game_logic(parse_save_from_path(any_save_path).chunk("CHUNK_GameLogic"))
    assert state.frame == 2
    # Every object resolves against the template table → the walk never lost alignment.
    assert all(o.template_id in state.templates for o in state.objects)
    assert len({o.object_id for o in state.objects}) == len(state.objects)


def test_any_save_player_refs_are_fatal_names(any_save_path):
    refs = harvest_player_references(parse_save_from_path(any_save_path))
    assert refs, "expected upgrade/science names in a skirmish save"
    assert all(r.fatal for r in refs)
    assert all(r.kind in ("upgrade", "science") for r in refs)
    for ref in refs:
        prefix = "Upgrade_" if ref.kind == "upgrade" else "SCIENCE_"
        assert ref.name.startswith(prefix)


# The exact-inverse encoder round-trip now runs over the decoder registry (CHUNK_CODECS) for
# every fixture in test_infra.py::test_registered_codec_round_trips.


# --- save-2-specific values (Mordor vs Men) ---


@pytest.fixture(scope="module")
def save2():
    if not SAVE2_PATH.is_file():
        pytest.skip("fixture save 2 not present")
    return parse_save_from_path(SAVE2_PATH)


def test_save2_game_state(save2):
    header = decode_game_state(save2.chunk("CHUNK_GameState"))
    assert header.description == "Saved Game 2"
    assert header.saved_at == datetime(2026, 7, 5, 11, 17, 12, 280000)


def test_save2_game_logic(save2):
    state = decode_game_logic(save2.chunk("CHUNK_GameLogic"))
    assert len(state.templates) == 78
    assert len(state.objects) == 350


def test_save2_faction_names(save2):
    names = {r.name for r in harvest_player_references(save2)}
    # faction upgrades + building-level upgrades from a longer game, and faction sciences
    assert {"Upgrade_MordorFaction", "Upgrade_MenFaction"} <= names
    assert {"SCIENCE_MORDOR", "SCIENCE_MEN"} <= names
    assert "Upgrade_GondorBarracksLevel3" in names


# --- save-3-specific values (Elves + a 3-enemy team of Mordor/Men/Isengard, a different map) ---


@pytest.fixture(scope="module")
def save3():
    if not SAVE3_PATH.is_file():
        pytest.skip("fixture save 3 not present")
    return parse_save_from_path(SAVE3_PATH)


def test_save3_different_map(save3):
    header = decode_game_state(save3.chunk("CHUNK_GameState"))
    assert header.description == "Saved Game 3"
    assert "arnor" in header.map_name  # a different map from saves 1 & 2 (harlindon)
    gsm = decode_game_state_map(save3.chunk("CHUNK_GameStateMap"))
    assert gsm.game_mode == 2


def test_save3_game_logic(save3):
    state = decode_game_logic(save3.chunk("CHUNK_GameLogic"))
    assert len(state.templates) == 103
    assert len(state.objects) == 485


def test_save3_four_factions(save3):
    # eight player slots (four factions + neutral/civilian), not the six of a 1v1
    assert struct.unpack_from("<I", save3.chunk("CHUNK_Players").payload, 1)[0] == 8
    names = {r.name for r in harvest_player_references(save3)}
    # one faction upgrade + science per playing faction: Elves, Men, Isengard, Mordor
    assert {
        "Upgrade_ElfFaction",
        "Upgrade_MenFaction",
        "Upgrade_IsengardFaction",
        "Upgrade_MordorFaction",
    } <= names
    assert {"SCIENCE_ELVES", "SCIENCE_MEN", "SCIENCE_ISENGARD", "SCIENCE_MORDOR"} <= names


def test_save_to_json(save):
    document = json.loads(save_to_json(save))  # valid JSON, and load-round-trips
    assert document["container"]["id"] == "EALA RTS2"
    assert document["game_state"]["description"] == "Saved Game 1"
    assert document["game_state"]["saved_at"] == "2026-07-04T21:09:06.253000"
    assert document["game_state_map"]["game_mode"] == 2
    assert document["game_logic"]["object_count"] == 358
    assert document["game_logic"]["templates"]["1"] == "RockGrey06"
    first_object = document["game_logic"]["objects"][0]
    assert first_object["object_id"] == 1
    assert first_object["template_id"] == 1
    assert first_object["template"] == "RockGrey06"
    assert len(first_object["position"]) == 3  # from the Object::xfer prefix transform
    assert len(document["chunks"]) == 32
    fatal = [r for r in document["references"] if r["fatal"]]
    assert {r["name"] for r in fatal} >= {"Upgrade_DwarfFaction", "SCIENCE_DWARVES"}


def test_save_to_dict_without_objects(save):
    compact = save_to_dict(save, include_objects=False)
    # the per-object list is dropped but the counts and reference summary remain
    assert "objects" not in compact["game_logic"]
    assert compact["game_logic"]["object_count"] == 358
    assert compact["references"]


def test_apply_json_length_preserving_edit(save):
    # a same-length rename + a new timestamp + a game-mode change all preserve chunk length
    edited = apply_json(
        save,
        {
            "game_state": {"description": "Renamed Save", "saved_at": "2030-12-25T09:00:00"},
            "game_state_map": {"game_mode": 5},
        },
    )
    reparsed = parse_save(write_save(edited))  # write + reparse: proves the file stays valid
    header = decode_game_state(reparsed.chunk("CHUNK_GameState"))
    assert header.description == "Renamed Save"
    assert header.saved_at == datetime(2030, 12, 25, 9, 0, 0)
    assert decode_game_state_map(reparsed.chunk("CHUNK_GameStateMap")).game_mode == 5
    # nothing shifted, so the offset-bearing chunks still decode
    logic = decode_game_logic(reparsed.chunk("CHUNK_GameLogic"))
    assert all(o.template_id in logic.templates for o in logic.objects)
    # only the two edited chunks differ from the original
    changed = [
        a.name for a, b in zip(save.chunks, reparsed.chunks, strict=True) if a.payload != b.payload
    ]
    assert changed == ["CHUNK_GameState", "CHUNK_GameStateMap"]


def test_apply_json_refuses_length_change(save):
    with pytest.raises(ValueError, match="changed its size"):
        apply_json(save, {"game_state": {"description": "A Considerably Longer Save Name"}})


def test_apply_json_map_data_preserved(save):
    # editing the map path (same length) keeps the embedded map bytes byte-for-byte
    original = decode_game_state_map(save.chunk("CHUNK_GameStateMap"))
    swapped = original.save_map_name.replace("harlindon", "harlindoN")  # same length
    edited = apply_json(save, {"game_state_map": {"save_map_name": swapped}})
    result = decode_game_state_map(edited.chunk("CHUNK_GameStateMap"))
    assert result.save_map_name == swapped
    assert result.map_data == original.map_data


def test_parse_rejects_non_save():
    with pytest.raises(ValueError, match="not a BFME save"):
        parse_save(b"NOPE" + b"\x00" * 32)


def test_xfer_reader_primitives():
    payload = (
        bytes([2])  # version
        + struct.pack("<IhH", 0xDEADBEEF, -3, 7)  # uint32, int16, uint16
        + struct.pack("<f", 1.5)  # real
        + bytes([5])
        + b"hello"  # ascii_string
        + bytes([2])
        + "hé".encode("utf-16-le")  # unicode_string (2 chars)
    )
    reader = XferReader(payload)
    assert reader.version(2) == 2
    assert reader.uint32() == 0xDEADBEEF
    assert reader.int16() == -3
    assert reader.uint16() == 7
    assert reader.real() == 1.5
    assert reader.ascii_string() == "hello"
    assert reader.unicode_string() == "hé"
    assert reader.eof()


def test_xfer_reader_version_guard():
    with pytest.raises(ValueError, match="exceeds supported version"):
        XferReader(bytes([9])).version(8)


def test_xfer_reader_nested_block_resolves_absolute_offset():
    # A KOLB block whose absolute end-offset is resolved against base_offset.
    base = 0x1000
    data = BLOCK_MARKER + struct.pack("<I", base + 6) + b"ab"
    reader = XferReader(data, base_offset=base)
    end = reader.nested_block()
    assert end == 6  # payload-relative
    assert reader.bytes(end - reader.tell()) == b"ab"


def test_container_framing_round_trips_synthetic():
    # A hand-built two-chunk save exercises the writer's end-offset backpatching without the
    # fixture. Payloads are opaque, each starting with a version byte.
    header = SaveHeader(MAGIC_EALA, MAGIC_RTS, 1, 0)
    chunks = [Chunk("CHUNK_A", b"\x01hello", 0), Chunk("CHUNK_B", b"\x02world!!", 0)]
    data = write_save(SaveFile(header, chunks))

    assert data[:4] == MAGIC_EALA
    assert BLOCK_MARKER in data
    assert data.endswith(bytes([len(EOF_TOKEN)]) + EOF_TOKEN.encode())

    reparsed = parse_save(data)
    assert [(c.name, c.payload) for c in reparsed.chunks] == [
        ("CHUNK_A", b"\x01hello"),
        ("CHUNK_B", b"\x02world!!"),
    ]
    assert reparsed.chunks[0].version == 1
