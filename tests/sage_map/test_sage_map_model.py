"""Phase 2: the game-aware map adapter (symbol harvest + located argument walk).

Built from hand-made sagemap dataclasses so the tests need no `.map` file or corpus. A
`pytest.importorskip` keeps them quiet without the optional `[map]` extra.
"""

import pytest

pytest.importorskip("reversebox", reason="requires the optional [map] extra (reversebox)")

from sage_map import (  # noqa: E402
    Map,  # noqa: E402
    MapModel,
    Scope,
    build_symbols,
)
from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.assets.player_scripts import (  # noqa: E402
    PlayerScriptsList,
    Script,
    ScriptArgument,
    ScriptDerived,
    ScriptList,
)
from sage_map.assets.player_scripts import ScriptArgumentType as AT  # noqa: E402
from sage_map.assets.sides_list import Player, SidesList  # noqa: E402
from sage_map.assets.teams import Team, Teams  # noqa: E402
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas  # noqa: E402


def _prop(name, value):
    return {"name": name, "type": None, "value": value}


def _team(name, owner=""):
    return Team(
        properties={
            "teamName": _prop("teamName", name),
            "teamOwner": _prop("teamOwner", owner),
        }
    )


def _player(name):
    return Player(properties={"playerName": _prop("playerName", name)}, build_list_items={})


def _object(type_name, **props):
    return Object(
        version=1,
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        road_type=0,
        type_name=type_name,
        properties={k: _prop(k, v) for k, v in props.items()},
        start_pos=0,
        end_pos=0,
    )


def _action(*args):
    return ScriptDerived(
        version=2,
        content_type=0,
        internal_name=None,
        arguments=list(args),
        is_enabled=True,
        is_inverted=None,
        has_internal_name_version=2,
        has_is_enabled_version=3,
        has_is_inverted=False,
    )


def _script(name, *, actions_if_true=()):
    script = Script(
        name=name,
        comment="",
        conditions_comment="",
        actions_comment="",
        is_active=True,
        deactivate_upon_success=False,
        active_in_easy=True,
        active_in_medium=True,
        active_in_hard=True,
        is_subroutine=False,
        version=2,
        start_pos=0,
        end_pos=0,
    )
    script.actions_if_true = list(actions_if_true)
    return script


def _map(*, teams=(), players=(), objects=(), trigger_areas=(), scripts=()):
    m = Map()
    m.teams = Teams(version=5, teams=list(teams), start_pos=0, end_pos=0) if teams else None
    m.sides_list = SidesList(
        version=6, unknown1=False, players=list(players), start_pos=0, end_pos=0, teams=[]
    )
    m.objects_list = ObjectsList(version=1, object_list=list(objects), start_pos=0, end_pos=0)
    m.trigger_areas = (
        TriggerAreas(version=1, trigger_areas=list(trigger_areas), start_pos=0, end_pos=0)
        if trigger_areas
        else None
    )
    m.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=list(scripts), start_pos=0, end_pos=0)],
        start_pos=0,
        end_pos=0,
    )
    return m


def test_symbol_harvest_collects_each_kind():
    m = _map(
        teams=[_team("Farmers", owner="PlyrCivilian")],
        players=[_player("PlyrCreeps"), _player("")],  # the empty neutral player is dropped
        objects=[
            _object("GenericWaypoint", waypointName="Marker1", waypointPathLabel1="PathA"),
            _object("GondorFighter", objectName="Hero1"),
        ],
        trigger_areas=[TriggerArea("Zone1", "", 1, [], 0)],
        scripts=[_script("Intro")],
    )
    s = build_symbols(m)
    # Teams are harvested both bare and as the qualified `owner/name` scripts reference.
    assert s.teams == {"farmers", "plyrcivilian/farmers"}
    assert s.players == {"plyrcreeps"}
    assert s.waypoints == {"marker1"}
    assert s.waypoint_paths == {"patha"}
    assert s.units == {"hero1"}  # harvested for the API, but not resolvable (see below)
    assert s.trigger_areas == {"zone1"}
    assert s.scripts == {"intro"}


def test_resolve_is_case_insensitive_and_tristate():
    s = build_symbols(_map(teams=[_team("Farmers", owner="PlyrCivilian")]))
    assert s.resolve("teams", "PlyrCivilian/Farmers") is True  # qualified, case-insensitive
    assert s.resolve("teams", "FARMERS") is True  # bare form also resolves
    assert s.resolve("teams", "Missing") is False
    assert s.resolve("counters", "anything") is None  # untracked: never declared
    # Named units are harvested but not resolved: scripts can create units at runtime, so a name
    # absent from the placed set is not necessarily dangling.
    assert s.resolve("units", "Hero1") is None
    # Scripts are likewise untracked: a SCRIPT_NAME reference may target a subroutine (script or
    # script group) imported from a library merged only at runtime.
    assert s.resolve("scripts", "anything") is None


def test_located_argument_walk():
    arg = ScriptArgument(type=AT.TEAM_NAME, int_value=0, float_value=0.0, string_value="Alpha")
    m = _map(scripts=[_script("Intro", actions_if_true=[_action(arg)])])
    refs = list(MapModel.from_map(m).script_arguments())
    assert len(refs) == 1
    ref = refs[0]
    assert ref.script_name == "Intro"
    assert ref.address == "Intro/if_true[0]/arg[0]"
    assert ref.resolved.spec.scope is Scope.MAP
    assert ref.resolved.value == "Alpha"


def test_references_filters_to_resolvable_named_args():
    team = ScriptArgument(type=AT.TEAM_NAME, int_value=0, float_value=0.0, string_value="Alpha")
    number = ScriptArgument(type=AT.INTEGER, int_value=5, float_value=0.0, string_value="")
    blank = ScriptArgument(type=AT.TEAM_NAME, int_value=0, float_value=0.0, string_value="")
    m = _map(scripts=[_script("S", actions_if_true=[_action(team, number, blank)])])
    refs = list(MapModel.from_map(m).references())
    assert [r.resolved.value for r in refs] == ["Alpha"]  # number (LITERAL) and blank dropped
