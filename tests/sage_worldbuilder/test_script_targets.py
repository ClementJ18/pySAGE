"""What a script argument points at: the lookup behind the editor's Go To buttons."""

from sage_map.assets.object_list import ObjectsList
from sage_map.assets.player_scripts import (
    PlayerScriptsList,
    ScriptArgument,
    ScriptArgumentType,
    ScriptList,
)
from sage_map.assets.sides_list import SidesList
from sage_map.assets.teams import Teams
from sage_map.assets.trigger_areas import TriggerAreas
from sage_map.assets.waypoint_list import WaypointsList
from sage_map.map import Map
from sage_worldbuilder.areas import new_area
from sage_worldbuilder.objects import new_object
from sage_worldbuilder.players import new_player
from sage_worldbuilder.script_targets import (
    TargetKind,
    argument_target,
    navigable,
    target_kind,
)
from sage_worldbuilder.scripting import new_group, new_script
from sage_worldbuilder.teams import new_team
from sage_worldbuilder.waypoints import new_waypoint

T = ScriptArgumentType


def populated_map() -> Map:
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    map.trigger_areas = TriggerAreas(version=1, trigger_areas=[], start_pos=0, end_pos=0)
    ambush = new_area(map, [(0.0, 0.0), (10.0, 20.0)])
    ambush.name = "Ambush"
    map.trigger_areas.trigger_areas.append(ambush)
    gandalf = new_object(map, "GondorGandalf", (30.0, 40.0, 0.0), 0.0, "/team")
    gandalf.properties["objectName"] = {
        "name": "objectName",
        "type": gandalf.properties["originalOwner"]["type"],
        "value": "Gandalf",
    }
    map.objects_list.object_list.append(gandalf)
    for index, position in enumerate(((100.0, 0.0, 0.0), (200.0, 40.0, 0.0))):
        waypoint = new_waypoint(map, position)
        map.objects_list.object_list.append(waypoint)
        if index:
            waypoint.properties["waypointPathLabel1"]["value"] = "March"
        else:
            waypoint.properties["waypointPathLabel2"]["value"] = "March"
    map.teams = Teams(version=1, teams=[new_team("Archers", "Player_1")], start_pos=0, end_pos=0)
    map.sides_list = SidesList(
        version=1,
        unknown1=False,
        players=[new_player("Player_1")],
        teams=[],
        start_pos=0,
        end_pos=0,
    )
    group = new_group("Act One")
    group.items.append(new_script("Intro"))
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=[group], start_pos=0, end_pos=0)],
        start_pos=0,
        end_pos=0,
    )
    return map


def named(kind: ScriptArgumentType, value: str) -> ScriptArgument:
    return ScriptArgument(kind, int_value=0, float_value=0.0, string_value=value)


def test_only_map_scope_types_are_navigable():
    """An argument naming something the map declares can be gone to; one naming an ini
    definition, a scalar or a counter cannot."""
    for kind in (T.OBJECT_NAME, T.UNIT_NAME, T.WAYPOINT_NAME, T.TEAM_REFERENCE, T.SCRIPT_NAME):
        assert navigable(kind)
    for kind in (T.OBJECT_TYPE, T.UPGRADE_NAME, T.INTEGER, T.COUNTER_NAME, T.FLAG_NAME):
        assert not navigable(kind)
    assert target_kind(T.SUBROUTINE_NAME) is TargetKind.SCRIPT
    assert target_kind(9999) is None


def test_named_object_resolves_to_its_position():
    map = populated_map()
    target = argument_target(named(T.OBJECT_NAME, "gandalf"), map)
    assert target is not None
    # The name reads as the map stores it, not as the argument happens to spell it.
    assert target.kind is TargetKind.OBJECT and target.position == (30.0, 40.0)
    assert target.sources == (map.objects_list.object_list[0],)
    assert target.label == "Go to object 'Gandalf'"


def test_waypoint_and_its_path():
    map = populated_map()
    waypoint = argument_target(named(T.WAYPOINT_NAME, "Waypoint 1"), map)
    assert waypoint is not None and waypoint.kind is TargetKind.WAYPOINT
    assert waypoint.position == (100.0, 0.0)
    # A path is a label its waypoints share, so it selects them all and centres between them.
    path = argument_target(named(T.WAYPOINT_PATH_NAME, "March"), map)
    assert path is not None and path.kind is TargetKind.WAYPOINT_PATH
    assert len(path.sources) == 2 and path.position == (150.0, 20.0)


def test_area_team_player_and_script():
    map = populated_map()
    area = argument_target(named(T.TRIGGER_AREA_NAME, "Ambush"), map)
    assert area is not None and area.position == (5.0, 10.0)
    # Scripts qualify a team with its owner; a bare team name finds it just the same.
    for written in ("Player_1/Archers", "Archers"):
        team = argument_target(named(T.TEAM_NAME, written), map)
        assert team is not None and team.name == "Player_1/Archers"
    player = argument_target(named(T.PLAYER_NAME, "Player_1"), map)
    assert player is not None and player.kind is TargetKind.PLAYER and player.position is None
    script = argument_target(named(T.SCRIPT_NAME, "intro"), map)
    assert script is not None and script.name == "Intro"
    assert argument_target(named(T.SUBROUTINE_NAME, "Act One"), map) is not None


def test_nothing_to_go_to():
    map = populated_map()
    assert argument_target(named(T.OBJECT_NAME, "Saruman"), map) is None
    assert argument_target(named(T.OBJECT_NAME, "  "), map) is None
    assert argument_target(named(T.COUNTER_NAME, "Kills"), map) is None
    assert argument_target(ScriptArgument(T.INTEGER, int_value=3), map) is None
    assert argument_target(named(T.OBJECT_NAME, "Gandalf"), Map()) is None
