"""Add Skirmish Players, how players regard each other, Fix Teams, Reset Active and the named
weather values."""

from sage_ini.engine import Engine, EnumDelta
from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList
from sage_map.assets.sides_list import SidesList
from sage_map.assets.teams import Teams
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.fix_teams import clear_execute_actions, default_team, fix_teams
from sage_worldbuilder.players import (
    ALLY,
    ENEMY,
    NEUTRAL,
    SKIRMISH_PLAYER_LIMIT,
    add_player_with_team,
    add_skirmish_players,
    new_player,
    numbered_player,
    player_name,
    regard,
)
from sage_worldbuilder.properties import WORLD_INFO_SPECS
from sage_worldbuilder.scripting import active_flags, new_group, new_script, reset_active
from sage_worldbuilder.teams import new_team, team_name, team_owner


def players_map() -> Map:
    map = Map()
    map.sides_list = SidesList(
        version=6,
        unknown1=False,
        players=[new_player(""), new_player("PlyrGood", "Good", "FactionMen", True)],
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
        version=1, teams=[new_team("teamPlyrGood", "PlyrGood")], start_pos=0, end_pos=0
    )
    return map


def names(map: Map) -> list[str]:
    return [player_name(player) for player in map.sides_list.players]


def test_add_skirmish_players_adds_the_skirmish_roster_with_teams():
    map = players_map()
    document = MapDocument(map)
    command = add_skirmish_players(map, [("FactionMen", "Men"), ("FactionMordor", "Mordor")])
    assert command is not None
    document.execute(command)

    assert names(map) == [
        "",
        "PlyrGood",
        "PlyrCivilian",
        "PlyrCreeps",
        "SkirmishMen",
        "SkirmishMordor",
        "Player_1",
        "Player_2",
        "Player_3",
        "Player_4",
    ]
    men = map.sides_list.players[4].properties
    assert (
        men["playerFaction"]["value"],
        men["playerDisplayName"]["value"],
        men["playerIsHuman"]["value"],
    ) == ("FactionMen", "SkirmishMen", False)
    assert map.sides_list.players[2].properties["playerFaction"]["value"] == "FactionCivilian"
    assert len(map.player_scripts_list.script_lists) == 10
    added = [
        (team_name(team), team_owner(team), team.properties["teamIsSingleton"]["value"])
        for team in map.teams.teams[1:]
    ]
    assert added[:3] == [
        ("teamPlyrCivilian", "PlyrCivilian", True),
        ("teamPlyrCreeps", "PlyrCreeps", True),
        ("teamSkirmishMen", "SkirmishMen", True),
    ]
    assert len(added) == 8
    assert add_skirmish_players(map, [("FactionMen", "Men")]) is None

    document.stack.undo()
    assert names(map) == ["", "PlyrGood"]
    assert len(map.player_scripts_list.script_lists) == 2
    assert [team_name(team) for team in map.teams.teams] == ["teamPlyrGood"]


def test_add_skirmish_players_stops_past_the_player_limit():
    map = players_map()
    for index in range(SKIRMISH_PLAYER_LIMIT - 3):
        map.sides_list.players.append(new_player(f"Plyr{index}"))
        map.player_scripts_list.script_lists.append(
            ScriptList(version=1, items=[], start_pos=0, end_pos=0)
        )
    MapDocument(map).execute(add_skirmish_players(map, [("FactionMen", "Men")]))

    assert len(map.sides_list.players) == SKIRMISH_PLAYER_LIMIT + 1
    assert names(map)[-2:] == ["PlyrCivilian", "PlyrCreeps"]
    assert len(map.player_scripts_list.script_lists) == len(map.sides_list.players)


def test_regard_reads_allies_and_enemies():
    good = new_player("PlyrGood")
    good.properties["playerAllies"]["value"] = "PlyrElves"
    good.properties["playerEnemies"]["value"] = "PlyrEvil SkirmishMordor"

    assert regard(good, "plyrelves") == ALLY
    assert regard(good, "SkirmishMordor") == ENEMY
    assert regard(good, "PlyrCreeps") == NEUTRAL


def owned(type_name: str, owner: str, name: str | None = None) -> Object:
    properties = {"originalOwner": text("originalOwner", owner)}
    if name is not None:
        properties["objectName"] = text("objectName", name)
    return Object(
        version=3,
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        road_type=0,
        type_name=type_name,
        properties=properties,
        start_pos=0,
        end_pos=0,
    )


def text(key: str, value: str) -> dict:
    return {"name": key, "type": AssetPropertyType.AsciiString, "value": value}


def test_fix_teams_removes_bad_teams_and_moves_objects_to_default_teams():
    map = players_map()
    map.teams.teams[:] = [
        new_team("teamPlyrGood", "PlyrGood"),
        new_team("team", ""),
        new_team("Raiders", "PlyrEvil"),
        new_team("TEAMPLYRGOOD", "PlyrGood"),
    ]
    map.objects_list = ObjectsList(
        version=3,
        object_list=[
            owned("GondorFighter", "PlyrGood/teamPlyrGood"),
            owned("MordorOrc", "PlyrEvil/Raiders", "Grishnakh"),
            owned("Tree", "PlyrGood/Gone"),
        ],
        start_pos=0,
        end_pos=0,
    )
    document = MapDocument(map)

    command, messages = fix_teams(map)
    assert messages == [
        'Duplicate instance of team "TEAMPLYRGOOD" removed.',
        'Team "Raiders" was on non-existent player "PlyrEvil".  Team removed.',
        'Object "Grishnakh" (MordorOrc) on missing team "PlyrEvil/Raiders" moved to team "/team".',
        'Object "Tree" on missing team "PlyrGood/Gone" moved to team "PlyrGood/teamPlyrGood".',
    ]
    assert command is not None
    document.execute(command)

    def owners() -> list[str]:
        return [
            placed.properties["originalOwner"]["value"] for placed in map.objects_list.object_list
        ]

    assert [team_name(team) for team in map.teams.teams] == ["teamPlyrGood", "team"]
    assert owners() == ["PlyrGood/teamPlyrGood", default_team(""), default_team("PlyrGood")]
    assert fix_teams(map) == (None, [])

    document.stack.undo()
    assert [team_name(team) for team in map.teams.teams] == [
        "teamPlyrGood",
        "team",
        "Raiders",
        "TEAMPLYRGOOD",
    ]
    assert owners() == ["PlyrGood/teamPlyrGood", "PlyrEvil/Raiders", "PlyrGood/Gone"]


def test_reset_active_restores_the_flags_the_map_was_loaded_with():
    map = players_map()
    script = new_script("Intro")
    group = new_group("Act One")
    group.items.append(script)
    map.player_scripts_list.script_lists[1].items.append(group)
    assert script.is_active and group.is_active

    flags = active_flags(map)
    assert reset_active(map, flags) is None

    document = MapDocument(map)
    script.is_active = False
    group.is_active = False
    later = new_script("Later")
    later.is_active = False
    map.player_scripts_list.script_lists[1].items.append(later)
    command = reset_active(map, flags)
    assert command is not None
    document.execute(command)

    assert script.is_active and group.is_active
    assert not later.is_active
    document.stack.undo()
    assert not script.is_active and not group.is_active


def test_weather_names_its_values():
    weather = next(spec for spec in WORLD_INFO_SPECS if spec.name == "weather")
    assert weather.choice_names() == ("Normal", "Snowy")


def test_a_patched_engine_adds_its_weather():
    """A binary patch can grow the engine's weather table; the map settings follow it."""
    weather = next(spec for spec in WORLD_INFO_SPECS if spec.name == "weather")
    engine = Engine(enum_members=(EnumDelta("MapWeatherType", "DESERT", 2, "desert-weather"),))
    with engine.activate() as problems:
        assert problems == []
        assert weather.choice_names() == ("Normal", "Snowy", "Desert")
    assert weather.choice_names() == ("Normal", "Snowy")


def test_new_players_are_numbered_and_get_their_team():
    map = players_map()
    player = numbered_player(map)
    assert player_name(player) == "player0001"
    assert player.properties["playerDisplayName"]["value"] == "Player 0001's Display Name"

    document = MapDocument(map)
    document.execute(add_player_with_team(map, player))
    assert names(map)[-1] == "player0001"
    assert player_name(numbered_player(map)) == "player0002"
    team = map.teams.teams[-1]
    assert (team_name(team), team_owner(team), team.properties["teamIsSingleton"]["value"]) == (
        "teamplayer0001",
        "player0001",
        True,
    )

    document.stack.undo()
    assert names(map) == ["", "PlyrGood"]
    assert [team_name(team) for team in map.teams.teams] == ["teamPlyrGood"]


def test_clear_execute_actions_turns_the_flag_off_on_every_team():
    map = players_map()
    raiders = new_team("Raiders", "PlyrGood")
    raiders.properties["teamExecutesActionsOnCreate"] = {
        "name": "teamExecutesActionsOnCreate",
        "type": AssetPropertyType.Boolean,
        "value": True,
    }
    map.teams.teams.append(raiders)
    document = MapDocument(map)

    command, changed = clear_execute_actions(map)
    assert changed == ["Raiders"]
    assert command is not None
    document.execute(command)
    assert raiders.properties["teamExecutesActionsOnCreate"]["value"] is False
    assert clear_execute_actions(map) == (None, [])

    document.stack.undo()
    assert raiders.properties["teamExecutesActionsOnCreate"]["value"] is True
