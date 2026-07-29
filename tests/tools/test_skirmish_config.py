"""`Skirmish.ini` round trips, and an edit changes only what was asked for.

The engine owns this file: it rewrites it when a match starts. So the bar is not "our writer
produces something parseable", it is "our writer produces the same bytes back unless a field was
deliberately changed". Anything less silently rewrites lobby state that took a human clicking to
set up, and the symptom is a match that starts wrong rather than a visible error.

The sample is the real file's shape, taken verbatim from a RotWK install (names shortened).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import skirmish_config  # noqa: E402
from skirmish_config import SkirmishConfig  # noqa: E402

SAMPLE = (
    ":0:B_00e_00n_00:GameInfo = M=387maps/map wor forlindon;MC=440170C3;MS=561107;"
    "SD=18624468;GSID=161B;GT=-1;SI=-1;GR=1 0 0 100 1000 -1 -1 -1 -1 -1 ;"
    "S=HBen,0,0,TT,0,3,0,0,0,1,19:X:X:X:X:X:X:X:;\n"
    ":0:B_00e_00n_00:HeroIndexes = :3:-1:-1:-1:-1:-1:-1:-1:\n"
    ":0:B_00e_00n_00:Map = maps\\map wor forlindon\\map wor forlindon.map\n"
    ":1:B_00e_00n_00:GameInfo = M=387maps/map mp harlindon;MC=7E7E82C3;MS=487138;"
    "SD=7508265;GSID=6331;GT=-1;SI=4;GR=1 -1 1 -1 -1 0 0 0 0 0 ;"
    "S=HBen,0,0,TT,0,3,51,0,0,1,19:CB,1,10,27,1,0,0:X:X:X:X:X:X:;\n"
    ":1:B_00e_00n_00:HeroIndexes = :3:-1:-1:-1:-1:-1:-1:-1:\n"
    ":1:B_00e_00n_00:Map = maps\\map mp harlindon\\map mp harlindon.map\n"
    "CurrentUserName = B_00e_00n_00\n"
    "UserNames = B_00e_00n_00_2C_00\n"
)


def test_the_file_round_trips_unchanged():
    """The gate everything else rests on."""
    assert SkirmishConfig.parse(SAMPLE).render() == SAMPLE


def test_entries_and_slots_are_typed():
    config = SkirmishConfig.parse(SAMPLE)
    assert [e.index for e in config.entries] == [0, 1]
    solo, versus = config.entries
    assert solo.metadata is not None and versus.metadata is not None
    assert solo.metadata.map_file == "maps/map wor forlindon"
    assert solo.metadata.seed == 18624468
    assert solo.metadata.map_crc == 0x440170C3
    assert len(solo.occupied) == 1
    assert len(versus.occupied) == 2
    assert solo.map_path == "maps\\map wor forlindon\\map wor forlindon.map"


def test_faction_is_the_playertemplate_index():
    """Cross-checked live: slot faction 3 is `FactionMen`, and the running game whose lobby
    entry this is reported the local player's Side as `Men`."""
    config = SkirmishConfig.parse(SAMPLE)
    assert config.entry(0).occupied[0].faction == 3
    assert config.entry(1).occupied[1].faction == 10  # the Brutal AI


def test_setting_the_seed_changes_one_key_and_nothing_else():
    config = SkirmishConfig.parse(SAMPLE)
    config.entry(0).metadata.seed = 999
    rendered = config.render()
    assert "SD=999;" in rendered
    assert "SD=18624468" not in rendered
    # every other line survives byte for byte
    for before, after in zip(SAMPLE.splitlines(), rendered.splitlines(), strict=True):
        assert before == after or "SD=999" in after


def test_setting_a_faction_leaves_the_other_entry_alone():
    config = SkirmishConfig.parse(SAMPLE)
    config.entry(0).occupied[0].faction = 7
    rendered = config.render()
    assert "S=HBen,0,0,TT,0,7,0,0,0,1,19:" in rendered
    assert "S=HBen,0,0,TT,0,3,51,0,0,1,19:" in rendered, "entry 1 must be untouched"


def test_unmodelled_keys_survive():
    """`GSID`, `GT`, `SI` and `GR` are unexplained, and `HeroIndexes` is not modelled at all."""
    config = SkirmishConfig.parse(SAMPLE)
    config.entry(0).metadata.seed = 1
    rendered = config.render()
    for fragment in ("GSID=161B;", "GT=-1;", "SI=-1;", "GR=1 0 0 100 1000 -1 -1 -1 -1 -1 ;"):
        assert fragment in rendered
    assert ":0:B_00e_00n_00:HeroIndexes = :3:-1:-1:-1:-1:-1:-1:-1:" in rendered


def test_entry_defaults_to_zero_rather_than_guessing_at_most_recent():
    """A solo skirmish was observed running entry 0, not the highest-numbered one, so this
    must not silently pick the last entry."""
    config = SkirmishConfig.parse(SAMPLE)
    assert config.entry().index == 0
    assert config.entry(1).index == 1
    assert config.entry(99) is None


def test_an_empty_file_parses_to_nothing_rather_than_raising():
    config = SkirmishConfig.parse("")
    assert config.entries == []
    assert config.entry() is None
    assert config.render() == "\n"


def test_save_refuses_while_the_game_is_running(monkeypatch, tmp_path):
    """The engine rewrites this file when a match starts, so writing under a live game loses
    the edit without saying so."""
    monkeypatch.setattr(skirmish_config, "find_game_processes", lambda: [1234])
    target = tmp_path / "Skirmish.ini"
    with pytest.raises(RuntimeError, match="game.dat is running"):
        SkirmishConfig.parse(SAMPLE).save(target)
    assert not target.exists()


def test_save_writes_when_no_game_is_running(monkeypatch, tmp_path):
    monkeypatch.setattr(skirmish_config, "find_game_processes", lambda: [])
    target = tmp_path / "Skirmish.ini"
    SkirmishConfig.parse(SAMPLE).save(target)
    assert target.read_text(encoding="latin-1") == SAMPLE
