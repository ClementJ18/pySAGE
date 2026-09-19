"""The Jump To Game command line, for each place a map can live, and the match it starts."""

import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from sage_replay.replay import ReplayGameType, ReplayMetadata, ReplaySlotDifficulty
from sage_worldbuilder.gamedata import GameLayers
from sage_worldbuilder.jump import (
    DEFAULT_STARTING_RESOURCES,
    JumpMatch,
    JumpMatchError,
    JumpOptions,
    JumpSeat,
    colour_names,
    default_seats,
    plan_jump,
    playable_factions,
    start_position_count,
)


def test_user_map_launches_in_place(tmp_path):
    install, user = tmp_path / "Game", tmp_path / "User"
    path = user / "Maps" / "Fords" / "Fords.map"
    plan = plan_jump(path, "Fords", GameLayers(install), user, JumpOptions())

    assert plan.install_to is None
    assert plan.arguments[:3] == [
        str(install / "game.dat"),
        "-file",
        str(user / "Maps" / "Fords.map").lower(),
    ]
    assert plan.arguments[3:] == ["-win", "-xres", "1024", "-yres", "768"]
    assert plan.working_directory == install


def test_the_window_takes_the_chosen_size(tmp_path):
    install, user = tmp_path / "Game", tmp_path / "User"
    path = user / "Maps" / "Fords" / "Fords.map"
    options = JumpOptions(resolution=(1920, 1080))
    plan = plan_jump(path, "Fords", GameLayers(install), user, options)

    assert plan.arguments[3:] == ["-win", "-xres", "1920", "-yres", "1080"]


def test_mod_map_uses_the_game_path(tmp_path):
    install, user, mod = tmp_path / "Game", tmp_path / "User", tmp_path / "Mod"
    path = mod / "maps" / "map mp fords" / "map mp fords.map"
    options = JumpOptions(
        windowed=False, script_debug=True, extra_arguments='-noshellmap -foo "a b"'
    )
    plan = plan_jump(path, "map mp fords", GameLayers(install, (mod,)), user, options)

    assert plan.install_to is None
    assert plan.arguments[2] == "maps\\map mp fords.map"
    assert plan.arguments[3:5] == ["-mod", str(mod.resolve())]
    assert plan.arguments[5:] == ["-scriptDebug2", "-noshellmap", "-foo", '"a b"']


def test_every_loaded_mod_travels_in_load_order(tmp_path):
    install, user = tmp_path / "Game", tmp_path / "User"
    base, submod = tmp_path / "Edain", tmp_path / "Submod"
    path = base / "maps" / "fords" / "fords.map"
    layers = GameLayers(install, (base, submod))
    plan = plan_jump(path, "fords", layers, user, JumpOptions(windowed=False))

    assert plan.install_to is None
    assert plan.arguments[2] == "maps\\fords.map"
    assert plan.arguments[3:] == ["-mod", str(base.resolve()), "-mod", str(submod.resolve())]


def test_map_elsewhere_or_in_an_archive_is_copied_first(tmp_path):
    install, user = tmp_path / "Game", tmp_path / "User"
    elsewhere = plan_jump(
        tmp_path / "desk" / "draft.map", "draft", GameLayers(install), user, JumpOptions()
    )
    archived = plan_jump(None, 'Fords: "Final"', GameLayers(install), user, JumpOptions())

    assert elsewhere.install_to == user / "Maps" / "draft" / "draft.map"
    assert elsewhere.arguments[2] == str(user / "Maps" / "draft.map").lower()
    assert archived.install_to == Path(user / "Maps" / "Fords_ _Final_" / "Fords_ _Final_.map")


def test_the_match_follows_the_map_argument(tmp_path):
    install, user = tmp_path / "Game", tmp_path / "User"
    path = user / "Maps" / "Fords" / "Fords.map"
    plan = plan_jump(path, "Fords", GameLayers(install), user, JumpOptions(game_info="S=X:;"))

    assert plan.arguments[3:5] == ["-gameInfo", "S=X:;"]


def fake_game():
    """Three factions, the first not playable, and three colours - in the order the engine
    registers them, which is what the lobby string indexes."""

    def template(playable):
        return SimpleNamespace(PlayableSide=playable, _fields={})

    return SimpleNamespace(
        tables={
            "factions": {
                "FactionCivilian": template(False),
                "FactionMen": template(True),
                "FactionMordor": template(True),
            },
            "multiplayercolors": {
                "ColorBlue": object(),
                "ColorRed": object(),
                "ColorWhite": object(),
            },
        }
    )


def _metadata(text: str) -> ReplayMetadata:
    return ReplayMetadata.from_string(text, ReplayGameType.Bfme2)


class TestTheMatch:
    def test_names_become_the_games_indices(self):
        match = JumpMatch(
            enabled=True,
            seats=(
                JumpSeat("human", "FactionMordor", 2, "ColorWhite", 0),
                JumpSeat("hard", "factionmen", 0, "ColorBlue", 1),
            ),
            starting_resources=8000,
            seed=77,
        )

        metadata = _metadata(match.game_info(fake_game()))

        human, ai = metadata.players
        assert (human.faction, human.start_position, human.color, human.team) == (2, 2, 2, 0)
        assert (ai.faction, ai.start_position, ai.color, ai.team) == (1, 0, 0, 1)
        assert ai.computer_difficulty is ReplaySlotDifficulty.Hard
        assert metadata.seed == 77
        assert metadata.values["GR"].split()[4] == "8000"

    def test_no_seed_draws_one_per_launch(self):
        match = JumpMatch(enabled=True, seats=default_seats(fake_game()))
        first = _metadata(match.game_info(fake_game(), random.Random(1))).seed
        second = _metadata(match.game_info(fake_game(), random.Random(2))).seed
        assert first != second and first > 0

    def test_without_game_data_it_says_so(self):
        with pytest.raises(JumpMatchError, match="not loaded"):
            JumpMatch(enabled=True, seats=(JumpSeat("human", "FactionMen"),)).game_info(None)

    def test_a_faction_the_game_does_not_have_is_named(self):
        match = JumpMatch(enabled=True, seats=(JumpSeat("human", "FactionElves", 0, "ColorRed"),))
        with pytest.raises(JumpMatchError, match="Seat 1's faction, FactionElves"):
            match.game_info(fake_game())

    def test_an_unchosen_colour_is_named(self):
        match = JumpMatch(enabled=True, seats=(JumpSeat("human", "FactionMen", 0, ""),))
        with pytest.raises(JumpMatchError, match="Seat 1's colour is not chosen"):
            match.game_info(fake_game())

    def test_the_lobby_rules_are_enforced(self):
        seats = (
            JumpSeat("human", "FactionMen", 1, "ColorRed"),
            JumpSeat("easy", "FactionMordor", 1, "ColorBlue"),
        )
        # Counted from 1, as the settings dialog shows seats and positions.
        with pytest.raises(JumpMatchError, match="Seats 1 and 2 both start at Position 2"):
            JumpMatch(enabled=True, seats=seats).game_info(fake_game())

    def test_a_second_human_is_refused(self):
        seats = (
            JumpSeat("human", "FactionMen", 0, "ColorRed"),
            JumpSeat("human", "FactionMordor", 1, "ColorBlue"),
        )
        with pytest.raises(JumpMatchError, match="Exactly one seat must be the human, not 2"):
            JumpMatch(enabled=True, seats=seats).game_info(fake_game())

    def test_the_defaults_are_a_human_against_an_easy_ai(self):
        human, ai = default_seats(fake_game())
        assert (human.kind, human.faction, human.start_position, human.colour) == (
            "human",
            "FactionMen",
            0,
            "ColorBlue",
        )
        assert (ai.kind, ai.faction, ai.start_position, ai.colour) == (
            "easy",
            "FactionMordor",
            1,
            "ColorRed",
        )
        assert human.team == ai.team == -1

    def test_the_offered_factions_are_the_playable_ones(self):
        assert playable_factions(fake_game()) == ["FactionMen", "FactionMordor"]
        assert colour_names(fake_game()) == ["ColorBlue", "ColorRed", "ColorWhite"]
        assert playable_factions(None) == [] and colour_names(None) == []


class TestStoring:
    def test_round_trip(self):
        match = JumpMatch(
            enabled=True,
            seats=(JumpSeat("brutal", "FactionMen", 5, "ColorRed", 3),),
            starting_resources=1234,
            seed=9,
        )
        assert JumpMatch.from_dict(match.to_dict()) == match

    def test_wrong_values_fall_back_one_by_one(self):
        match = JumpMatch.from_dict(
            {
                "enabled": "yes",
                "seats": [
                    {"kind": "insane", "faction": "FactionMen"},
                    {"kind": "hard", "faction": 3, "start_position": 12, "team": 9},
                    "junk",
                ],
                "starting_resources": -5,
                "seed": True,
            }
        )
        assert match.enabled is False
        assert match.seats == (JumpSeat("hard", "", 0, "", -1),)
        assert match.starting_resources == DEFAULT_STARTING_RESOURCES
        assert match.seed is None

    def test_anything_else_is_the_default(self):
        assert JumpMatch.from_dict("junk") == JumpMatch()


def test_start_positions_come_from_the_map():
    map = SimpleNamespace(mp_positions_list=SimpleNamespace(positions=[object()] * 3))
    assert start_position_count(map) == 3
    assert start_position_count(SimpleNamespace(mp_positions_list=None)) == 0
