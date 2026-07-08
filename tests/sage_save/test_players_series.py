"""The saves 4–9 time-series: one 4-faction FFA on `map wor enedwaith`, saved six times as it
progresses (baseline → one science researched → minutes on → two enemies defeated in turn).

These were authored to reverse `CHUNK_Players` (`Player::xfer`). A full byte-exact per-player
walk is not safely reachable from this corpus — even player 0 varies from byte 35, and the
records are a heterogeneous field sequence — so `sage_save.players` still harvests the fatal
name lists by signature. What these tests lock in is what the series *did* establish: the
signature harvest scales to a four-faction FFA, and a controlled single-science experiment
(save 4 → 5) confirms the science-vec layout structurally (the count incremented and the new
name appeared). They double as the regression anchor for a future full decode."""

import struct
from pathlib import Path

import pytest

from sage_save import (
    decode_game_logic,
    decode_game_state,
    decode_game_state_map,
    harvest_player_references,
    parse_save_from_path,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SERIES = {n: FIXTURES / f"Saved Game {n}.BfME2Skirmish" for n in range(4, 10)}


def _save(n: int):
    path = SERIES[n]
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return parse_save_from_path(path)


def _upgrades_sciences(save):
    refs = harvest_player_references(save)
    return (
        {r.name for r in refs if r.kind == "upgrade"},
        {r.name for r in refs if r.kind == "science"},
    )


@pytest.mark.parametrize("n", list(SERIES))
def test_series_is_one_match(n):
    save = _save(n)
    assert "enedwaith" in decode_game_state(save.chunk("CHUNK_GameState")).map_name
    assert decode_game_state_map(save.chunk("CHUNK_GameStateMap")).game_mode == 2  # skirmish
    # a four-faction FFA: eight player slots (four playing + system/neutral), like the arnor save
    assert struct.unpack_from("<I", save.chunk("CHUNK_Players").payload, 1)[0] == 8


def test_object_count_grows_then_drops_as_enemies_die():
    # units accumulate through saves 4→8, then fall in save 9 as the second enemy is defeated
    counts = {n: len(decode_game_logic(_save(n).chunk("CHUNK_GameLogic")).objects) for n in SERIES}
    assert counts[4] < counts[6] < counts[8]
    assert counts[9] < counts[8]


def test_ffa_harvest_finds_every_faction():
    # the signature harvest recognises all four factions' upgrades and sciences in one save
    upgrades, sciences = _upgrades_sciences(_save(4))
    assert {
        "Upgrade_ElfFaction",
        "Upgrade_MenFaction",
        "Upgrade_IsengardFaction",
        "Upgrade_MordorFaction",
    } <= upgrades
    assert {"SCIENCE_ELVES", "SCIENCE_MEN", "SCIENCE_ISENGARD", "SCIENCE_MORDOR"} <= sciences


def test_controlled_science_experiment():
    # Save 5 was taken right after researching exactly one science; it is the only difference the
    # harvest should show over the baseline save 4 for the human (Elves) player.
    _, sciences4 = _upgrades_sciences(_save(4))
    _, sciences5 = _upgrades_sciences(_save(5))
    assert "SCIENCE_Heal" not in sciences4
    assert "SCIENCE_Heal" in sciences5
