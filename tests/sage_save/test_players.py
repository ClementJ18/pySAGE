"""Task 5 — the structured `CHUNK_Players` decode.

The session1 single-delta series is the oracle: each save changed exactly one thing, so the
decoded fields must tell the same story ("money 4025" shows 4025, the upgrade moves from the
in-progress mask+status to the completed ones, and so on). Record boundaries come from the
indexed record heads (`0a 07` magic + the record's own player-index field), validated here by
the full-corpus walk plus the exact-inverse round-trip in test_infra.py. Money is the first
editable Players field (a u32 in place)."""

import pytest

from sage_save import (
    apply_json,
    decode_players,
    harvest_name_lists,
    harvest_object_upgrade_references,
    parse_save_from_path,
    save_to_dict,
    write_save,
)
from tests.sage_save.corpus import ALL_SAVES, FIXTURES, fixture_id

SESSION1 = FIXTURES / "session1"
HUMAN = 3  # the human player's index in the session1 lobby


def _require(path):
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return path


def _players(path):
    save = parse_save_from_path(_require(path))
    chunk = save.chunk("CHUNK_Players")
    if chunk is None:
        pytest.skip(f"{path.name} has no CHUNK_Players (between-missions stub)")
    return decode_players(chunk), save


def _session1(tag):
    return SESSION1 / f"Saved Game 1 {tag}.BfME2Skirmish"


def test_money_delta_save():
    # the save name records the HUD money at save time
    state, _ = _players(_session1("money 4025"))
    assert state.players[HUMAN].money == 4025


def test_idle_saves_show_starting_money():
    for tag in ("idle a", "idle b"):
        state, _ = _players(_session1(tag))
        assert state.players[HUMAN].money == 4000


def test_upgrade_progression_across_deltas():
    # The researched upgrade is a *fortress* upgrade, which turns out to complete on the
    # OBJECT, not the player: the player's in-progress entry (status 1) persists in both
    # saves, and completion shows up as the name arriving in the fortress object's applied
    # upgrade mask inside CHUNK_GameLogic. The one-action delta pins both halves.
    upgrade = "Upgrade_IsengardFortressMurderOfCrows"
    for tag, applied_on_object in (("upgrade in progress", False), ("upgrade done", True)):
        state, save = _players(_session1(tag))
        player = state.players[HUMAN]
        assert player.upgrades_in_progress == [upgrade]
        assert {u.name: u.status for u in player.upgrades}[upgrade] == 1
        object_upgrades = {r.name for r in harvest_object_upgrade_references(save)}
        assert (upgrade in object_upgrades) is applied_on_object
    # the faction upgrades bought in the lobby sit on the completed side with status 2
    done_player = _players(_session1("upgrade done"))[0].players[HUMAN]
    completed = {u.name: u.status for u in done_player.upgrades}
    assert all(completed[name] == 2 for name in done_player.upgrades_completed)


def test_masks_match_signature_harvest():
    # the structured decode reproduces what the signature scan finds (the old oracle)
    state, save = _players(_session1("upgrade done"))
    harvested = {
        name
        for name_list in harvest_name_lists(save.chunk("CHUNK_Players"))
        if name_list.kind == "upgrade"
        for name in name_list.names
    }
    structured = {
        name
        for player in state.players
        for name in (*player.upgrades_in_progress, *player.upgrades_completed)
    }
    assert structured <= harvested


def test_money_is_editable():
    save = parse_save_from_path(_require(_session1("money 4025")))
    edited = apply_json(save, {"players": {"players": [{"index": HUMAN, "money": 31337}]}})
    # the edit is length-preserving and reads back through a full container round-trip
    reparsed_state, _ = _players(_session1("money 4025"))
    assert reparsed_state.players[HUMAN].money == 4025  # original untouched
    edited_state = decode_players(edited.chunk("CHUNK_Players"))
    assert edited_state.players[HUMAN].money == 31337
    assert len(write_save(edited)) == len(write_save(save))


def test_export_carries_players_summary():
    save = parse_save_from_path(_require(_session1("money 4025")))
    data = save_to_dict(save, include_objects=False)
    entry = data["players"]["players"][HUMAN]
    assert entry["money"] == 4025
    assert entry["index"] == HUMAN


@pytest.mark.parametrize("path", ALL_SAVES, ids=fixture_id)
def test_players_decode_corpus_wide(path):
    state, _ = _players(path)
    assert state.version == 1
    assert state.players, "no player records decoded"
    for i, player in enumerate(state.players):
        assert player.index == i
        # money and caps are sane magnitudes (a mis-aligned walk reads garbage here)
        assert 0 <= player.money <= 10_000_000
        assert all(u.status in (1, 2) for u in player.upgrades)
        # the list and the masks carry the same names, split by status
        assert {u.name for u in player.upgrades} == set(
            player.upgrades_in_progress + player.upgrades_completed
        )
        assert all(t < 100_000 for t in player.team_ids)
