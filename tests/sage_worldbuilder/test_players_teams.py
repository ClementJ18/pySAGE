"""Property specs, players and teams: typed values, aligned player lists, and free names."""

import io

import pytest

from sage_map.assets.library_map_lists import LibraryMapLists, LibraryMaps
from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList
from sage_map.assets.sides_list import BuildList, BuildLists, SidesList
from sage_map.assets.teams import Teams
from sage_map.context import AssetPropertyType
from sage_map.map import Map, parse_map, write_map
from sage_worldbuilder import Change, ChangeKind, MapDocument
from sage_worldbuilder.players import (
    add_player,
    build_list_owner,
    join_relations,
    library_map_path,
    library_paths,
    new_player,
    player_name,
    relation_names,
    remove_player,
    set_player_faction,
    teams_without_owner,
    unique_player_name,
)
from sage_worldbuilder.properties import (
    PLAYER_SPECS,
    WORLD_INFO_SPECS,
    Editor,
    set_value,
    team_generic_script_spec,
    team_unit_specs,
    value_of,
)
from sage_worldbuilder.teams import (
    copy_team,
    new_team,
    qualified_team_name,
    team_list,
    team_name,
    unique_team_name,
)

SIDES = Change(ChangeKind.SIDES)


def spec(specs, name):
    return next(entry for entry in specs if entry.name == name)


def map_with_players() -> Map:
    map = Map()
    map.sides_list = SidesList(
        version=6,
        unknown1=False,
        players=[new_player(""), new_player("PlyrGood", "Good", "FactionMen", True)],
        start_pos=0,
        end_pos=0,
    )
    map.build_lists = BuildLists(
        version=1,
        build_lists=[
            BuildList(None, (AssetPropertyType.AsciiString, 0, owner), [])
            for owner in ("UNKNOWN", "Men")
        ],
        start_pos=0,
        end_pos=0,
    )
    map.library_map_lists = LibraryMapLists(
        version=1,
        lists=[LibraryMaps(version=1, values=[], start_pos=0, end_pos=0) for _ in range(2)],
        start_pos=0,
        end_pos=0,
    )
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=[], start_pos=0, end_pos=0) for _ in range(2)],
        start_pos=0,
        end_pos=0,
    )
    map.teams = Teams(
        version=1,
        teams=[new_team("teamPlyrGood", "PlyrGood"), new_team("Raiders", "PlyrEvil")],
        start_pos=0,
        end_pos=0,
    )
    return map


def test_specs_pick_editors_and_coerce_values():
    assert spec(WORLD_INFO_SPECS, "cameraPitchAngle").editor is Editor.REAL
    assert spec(PLAYER_SPECS, "playerIsHuman").editor is Editor.BOOLEAN
    assert spec(PLAYER_SPECS, "playerDisplayName").type is AssetPropertyType.UnicodeString

    document = MapDocument(Map())
    properties: dict = {}
    pitch = spec(WORLD_INFO_SPECS, "cameraPitchAngle")
    assert value_of(properties, pitch) == 37.5
    document.execute(set_value(properties, pitch, 40, SIDES))
    assert properties["cameraPitchAngle"] == {
        "name": "cameraPitchAngle",
        "type": AssetPropertyType.RealNumber,
        "value": 40.0,
    }
    document.stack.undo()
    assert properties == {}


def test_team_slot_specs():
    assert [entry.name for entry in team_unit_specs(3)][:3] == [
        "teamUnitType3",
        "teamUnitMinCount3",
        "teamUnitMaxCount3",
    ]
    assert team_generic_script_spec(31).name == "teamGenericScriptHook31"
    with pytest.raises(ValueError):
        team_unit_specs(8)


def test_new_player_matches_the_stored_layout_and_round_trips():
    map = map_with_players()
    written = write_map(map, compress=False)
    reread = parse_map(io.BytesIO(written))

    good = reread.sides_list.players[1]
    assert list(good.properties) == [
        "playerName",
        "playerIsHuman",
        "playerDisplayName",
        "playerFaction",
        "playerAllies",
        "playerEnemies",
    ]
    assert player_name(good) == "PlyrGood"
    assert team_name(reread.teams.teams[0]) == "teamPlyrGood"
    assert write_map(reread, compress=False) == written


def test_add_and_remove_keep_script_lists_aligned():
    map = map_with_players()
    document = MapDocument(map)
    evil = new_player(unique_player_name(map, "PlyrGood"))
    assert player_name(evil) == "PlyrGood2"

    def counts():
        return (
            len(map.sides_list.players),
            len(map.player_scripts_list.script_lists),
            len(map.build_lists.build_lists),
            len(map.library_map_lists.lists),
        )

    document.execute(add_player(map, evil))
    assert counts() == (3, 3, 3, 3)
    assert map.build_lists.build_lists[2].faction_name_property[2] == "UNKNOWN"
    document.execute(remove_player(map, 1))
    assert [player_name(p) for p in map.sides_list.players] == ["", "PlyrGood2"]
    assert counts() == (2, 2, 2, 2)

    document.stack.undo()
    document.stack.undo()
    assert [player_name(p) for p in map.sides_list.players] == ["", "PlyrGood"]
    assert counts() == (2, 2, 2, 2)


def test_faction_change_refiles_the_build_list():
    map = map_with_players()
    document = MapDocument(map)

    document.execute(set_player_faction(map, 1, "FactionElves"))
    assert map.sides_list.players[1].properties["playerFaction"]["value"] == "FactionElves"
    assert map.build_lists.build_lists[1].faction_name_property[2] == "Elves"
    document.stack.undo()
    assert map.build_lists.build_lists[1].faction_name_property[2] == "Men"

    assert build_list_owner("FactionMordor") == "Mordor"
    assert build_list_owner("") == "UNKNOWN"
    assert library_map_path("KI Kern") == "Libraries\\KI Kern\\KI Kern.map"
    assert library_paths(map, 1) == [] and library_paths(map, 5) is None


def test_relations_and_orphaned_teams():
    assert relation_names("PlyrGood  PlyrEvil ") == ["PlyrGood", "PlyrEvil"]
    assert join_relations(["PlyrGood", "PlyrEvil"]) == "PlyrGood PlyrEvil"

    map = map_with_players()
    assert [team_name(team) for team in teams_without_owner(map)] == ["Raiders"]


def test_team_names_and_copies():
    map = map_with_players()
    teams = team_list(map)
    assert teams is map.teams.teams
    assert qualified_team_name(teams[0]) == "PlyrGood/teamPlyrGood"
    assert unique_team_name(map, "Raiders") == "Raiders2"

    duplicate = copy_team(map, teams[1])
    assert team_name(duplicate) == "Raiders2"
    assert team_name(teams[1]) == "Raiders"
    assert team_list(Map()) is None
