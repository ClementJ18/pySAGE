"""Task 4 — the `CHUNK_ScriptEngine` decode.

The layout was cracked with the session3 `zztest.map` save, whose script symbols are all
distinctive `ZZ*` grep-anchors: the counter/flag records turned out to carry an always-present
player-scope string (empty for globals) — the discriminator the earlier byte-reversing pass
could not recover — and the rest of the chunk follows the ZH v5 section order with BFME2's
systematic changes (u32 list counts, name-hash pairs). These tests pin the zztest anchors, the
named-object join against the GameLogic object index (the save<->map symbol-consistency input),
the per-player science vectors (the third fatal xref source), and the corpus-wide invariants
the decoder's tripwires rely on. The exact-inverse round-trip is covered by the registry test
in test_infra.py."""

import pytest

from sage_save import (
    SCRIPT_ENGINE_PLAYER_SLOTS,
    decode_game_logic,
    decode_script_engine,
    harvest_script_engine_references,
    parse_save_from_path,
    save_to_dict,
)
from tests.sage_save.corpus import ALL_SAVES, FIXTURES, fixture_id

ZZTEST = FIXTURES / "session3" / "Saved Game 3.BfME2Skirmish"
SKIRMISH_9 = FIXTURES / "Saved Game 9.BfME2Skirmish"


def _require(path):
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return path


def _script_engine(path):
    save = parse_save_from_path(_require(path))
    chunk = save.chunk("CHUNK_ScriptEngine")
    if chunk is None:
        pytest.skip(f"{path.name} has no CHUNK_ScriptEngine (between-missions stub)")
    return decode_script_engine(chunk), save


def test_zztest_counters_and_scopes():
    state, _ = _script_engine(ZZTEST)
    by_name = {(c.scope, c.name): c for c in state.counters}
    # the map-authored global counters, with the values its script set
    assert by_name[("", "ZZCOUNTER_ONE")].value == 4
    assert by_name[("", "ZZCOUNTER_TWO")].value == 9
    assert by_name[("", "ZZTIMER_ONE")].value == 60
    # the player-scoped twins: same values, non-empty scope
    assert by_name[("Player_1", "ZZCOUNTER_ONEP")].value == 4
    assert by_name[("Player_1", "ZZCOUNTER_TWOP")].value == 9
    assert by_name[("Player_1", "ZZTIMER_ONEP")].value == 60
    # engine music-script counters are global, and countdown timers are flagged
    assert by_name[("", "___MusicScript_NeedNewMusic")].is_countdown_timer


def test_zztest_flags():
    state, _ = _script_engine(ZZTEST)
    by_name = {(f.scope, f.name): f.value for f in state.flags}
    assert by_name[("", "ZZFLAG_A")] is False
    assert by_name[("", "ZZFLAG_B")] is True
    assert by_name[("Player_1", "ZZFLAG_AP")] is False
    assert by_name[("Player_1", "ZZFLAG_BP")] is True


def test_zztest_named_object_joins_game_logic():
    state, save = _script_engine(ZZTEST)
    named = dict(state.named_objects)
    object_index = {
        o.object_id: o.template_name
        for o in decode_game_logic(save.chunk("CHUNK_GameLogic")).objects
    }
    # the map's named unit resolves to the placed hero
    assert object_index[named["ZZUNIT_NAMED"]] == "ElvenHaldir"


def test_zztest_sciences_match_purchase_flag():
    state, _ = _script_engine(ZZTEST)
    # the AI bought Cave Bats: the science vector and the script flag agree
    all_sciences = [s for sciences in state.player_sciences for s in sciences]
    assert all_sciences == ["SCIENCE_CaveBats"]
    flags = {(f.scope, f.name): f.value for f in state.flags}
    assert flags[("Player_2", "Cave Bats Spell Purchased")] is True


def test_enedwaith_science_history():
    # save 9 is the end of the controlled series: the human's sciences include the
    # experimentally-proven SCIENCE_Heal purchase from save 5
    state, _ = _script_engine(SKIRMISH_9)
    human = max(state.player_sciences, key=len)
    assert "SCIENCE_Heal" in human
    assert "SCIENCE_ElvenWood" in human


def test_script_engine_reference_harvest():
    state, save = _script_engine(SKIRMISH_9)
    references = harvest_script_engine_references(save)
    sciences = {r.name for r in references if r.kind == "science"}
    assert "SCIENCE_Heal" in sciences
    assert all(r.fatal for r in references if r.kind == "science")
    # the object-type lists contribute non-fatal template names
    templates = {r.name for r in references if r.kind == "object_template"}
    assert "MordorFellBeast" in templates
    assert all(not r.fatal for r in references if r.kind == "object_template")


def test_export_carries_script_engine_summary():
    save = parse_save_from_path(_require(ZZTEST))
    data = save_to_dict(save, include_objects=False)
    section = data["script_engine"]
    assert any(c["name"] == "ZZCOUNTER_ONE" for c in section["counters"])
    assert any(n["name"] == "ZZUNIT_NAMED" for n in section["named_objects"])
    assert ["SCIENCE_CaveBats"] in section["player_sciences"].values()


def test_topple_directions_decode_in_campaign():
    # The Ettenmoors Good-campaign saves are the only fixtures with a non-empty
    # m_toppleDirections list: two toppling props, each a {u32 key-hash, Coord3D}. The empty
    # skirmish case is covered by the corpus-wide test below (and the round-trip in test_infra).
    ettenmoors = FIXTURES / "campaign" / "Saved Game 13.BfME2Campaign"
    state, _ = _script_engine(ettenmoors)
    assert len(state.topple_directions) == 2
    positions = {t.position for t in state.topple_directions}
    assert (3028.0, 1671.0, 0.0) in positions
    assert (1036.0, 2973.0, 0.0) in positions
    # a skirmish save has none
    skirmish, _ = _script_engine(SKIRMISH_9)
    assert skirmish.topple_directions == []


@pytest.mark.parametrize("path", ALL_SAVES, ids=fixture_id)
def test_script_engine_decodes_corpus_wide(path):
    state, save = _script_engine(path)
    # every per-player section is exactly the 20 BFME2 player slots
    assert len(state.player_sciences) == SCRIPT_ENGINE_PLAYER_SLOTS
    assert all(len(s) == SCRIPT_ENGINE_PLAYER_SLOTS for s in state.special_power_maps)
    # the ZH breeze block: unit direction vector, sane period
    dx, dy = state.breeze[1], state.breeze[2]
    assert abs(dx * dx + dy * dy - 1.0) < 1e-3
    assert state.breeze_period > 0
    # every named object id is either 0 (dead/invalid) or a live GameLogic object
    object_ids = {o.object_id for o in decode_game_logic(save.chunk("CHUNK_GameLogic")).objects}
    for _name, object_id in state.named_objects:
        assert object_id == 0 or object_id in object_ids
    # counter/flag scopes are either global or a script player *name* ("Player_1",
    # "PlyrCreeps", ...) — never garbage bytes
    for record in [*state.counters, *state.flags]:
        assert all(32 <= ord(ch) < 127 for ch in record.scope)
        assert len(record.scope) < 32
