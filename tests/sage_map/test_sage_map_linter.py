"""Phase 3: dangling-reference linting of a `.map` against an assembled game.

Hand-built sagemap maps + a tiny `Game` populated directly, so no corpus or `.map` file is
needed. A `pytest.importorskip` keeps these quiet without the optional `[map]` extra.
"""

import pytest

pytest.importorskip("reversebox", reason="requires the optional [map] extra (reversebox)")

from sage_ini.model.game import Game  # noqa: E402
from sage_ini.parser.diagnostics import Severity  # noqa: E402
from sage_map import (  # noqa: E402
    Map,  # noqa: E402
    MapModel,
    lint_map,
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
from sage_map.assets.sides_list import SidesList  # noqa: E402
from sage_map.assets.teams import Team, Teams  # noqa: E402


def _prop(name, value):
    return {"name": name, "type": None, "value": value}


def _arg(arg_type, string_value="", int_value=0):
    return ScriptArgument(
        type=arg_type, int_value=int_value, float_value=0.0, string_value=string_value
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


def _script(name, *actions):
    s = Script(
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
    s.actions_if_true = list(actions)
    return s


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


def _map(*, teams=(), scripts=(), objects=None):
    m = Map()
    m.teams = Teams(version=5, teams=list(teams), start_pos=0, end_pos=0) if teams else None
    m.sides_list = SidesList(
        version=6, unknown1=False, players=[], start_pos=0, end_pos=0, teams=[]
    )
    m.objects_list = (
        None
        if objects is None
        else ObjectsList(version=1, object_list=list(objects), start_pos=0, end_pos=0)
    )
    m.trigger_areas = None
    m.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=list(scripts), start_pos=0, end_pos=0)],
        start_pos=0,
        end_pos=0,
    )
    return m


def _team(name):
    return Team(properties={"teamName": _prop("teamName", name)})


def _populate(game, key, names):
    for name in names:
        game.tables[key][name] = object()  # type: ignore[assignment]
        game._folded_names[key][name.lower()] = name


def _game_with_object(*names):
    """A game whose `objects` table has these definitions, so object resolution is live."""
    game = Game()
    _populate(game, "objects", names)
    return game


def _game(*, objects=(), upgrades=()):
    """A game with the given `objects` and `upgrades` tables populated."""
    game = Game()
    _populate(game, "objects", objects)
    _populate(game, "upgrades", upgrades)
    return game


def test_game_reference_dangles_when_object_absent():
    game = _game_with_object("GondorFighter")
    m = _map(scripts=[_script("S", _action(_arg(AT.OBJECT_TYPE, "RohanArcher")))])
    diags = lint_map(MapModel.from_map(m), game)
    assert len(diags.items) == 1
    d = diags.items[0]
    assert d.code == "map-dangling-reference"
    assert d.severity is Severity.WARNING
    assert d.extra == {
        "name": "RohanArcher",
        "noun": "object",
        "scope": "game",
        "target": "objects",
        "script": "S",
        "address": "S/if_true[0]/arg[0]",
    }


def test_game_reference_resolves_case_insensitively():
    game = _game_with_object("GondorFighter")
    m = _map(scripts=[_script("S", _action(_arg(AT.OBJECT_TYPE, "gondorfighter")))])
    assert lint_map(MapModel.from_map(m), game).items == []


def test_empty_game_table_is_skipped_not_flagged():
    """A map linted without building its mod must not flag every object reference."""
    m = _map(scripts=[_script("S", _action(_arg(AT.OBJECT_TYPE, "Anything")))])
    assert lint_map(MapModel.from_map(m), Game()).items == []


def test_map_reference_dangles_for_unknown_team():
    m = _map(
        teams=[_team("Alpha")],
        scripts=[_script("S", _action(_arg(AT.TEAM_NAME, "Bravo")))],
    )
    diags = lint_map(MapModel.from_map(m), Game())
    assert [d.extra["noun"] for d in diags.items] == ["team"]
    assert diags.items[0].extra["scope"] == "map"


def test_map_reference_resolves_for_known_team():
    m = _map(teams=[_team("Alpha")], scripts=[_script("S", _action(_arg(AT.TEAM_NAME, "Alpha")))])
    assert lint_map(MapModel.from_map(m), Game()).items == []


def test_engine_sentinels_are_not_flagged():
    m = _map(scripts=[_script("S", _action(_arg(AT.PLAYER_NAME, "<All Players>")))])
    assert lint_map(MapModel.from_map(m), Game()).items == []


def test_untracked_map_target_is_skipped():
    """COUNTER_NAME is MAP-scope but counters are never declared, so a miss is not dangling."""
    m = _map(scripts=[_script("S", _action(_arg(AT.COUNTER_NAME, "time")))])
    assert lint_map(MapModel.from_map(m), Game()).items == []


def test_script_references_are_not_flagged():
    """SCRIPT_NAME / SUBROUTINE_NAME references can target a subroutine imported from a library
    merged only at runtime, so they are intentionally not linted — an unknown name never flags."""
    m = _map(scripts=[_script("S", _action(_arg(AT.SCRIPT_NAME, "SomeLibrarySubroutine")))])
    assert lint_map(MapModel.from_map(m), Game()).items == []


def test_placed_object_with_unknown_type_is_flagged_once_with_count():
    game = _game_with_object("GondorFighter")
    m = _map(objects=[_object("RohanArcher"), _object("RohanArcher"), _object("GondorFighter")])
    diags = lint_map(MapModel.from_map(m), game).items
    # one diagnostic per distinct missing type, carrying the placed-instance count
    assert len(diags) == 1
    d = diags[0]
    assert d.code == "map-dangling-object"  # distinct code, separately --ignore-able
    assert d.severity is Severity.WARNING
    assert d.extra == {
        "name": "RohanArcher",
        "noun": "object",
        "scope": "game",
        "target": "objects",
        "count": 2,
    }
    assert "2 objects" in d.message


def test_known_object_type_resolves_case_insensitively():
    game = _game_with_object("GondorFighter")
    m = _map(objects=[_object("gondorfighter")])
    assert lint_map(MapModel.from_map(m), game).items == []


def test_object_check_skipped_when_objects_table_empty():
    """A map linted without building its mod must not flag every placed object."""
    m = _map(objects=[_object("Anything")])
    assert lint_map(MapModel.from_map(m), Game()).items == []


def test_worldbuilder_internal_object_types_are_skipped():
    # `*Waypoints/Waypoint` and friends are editor categories, not Object templates.
    game = _game_with_object("GondorFighter")
    m = _map(objects=[_object("*Waypoints/Waypoint"), _object("*Lights/AmbientLight")])
    assert lint_map(MapModel.from_map(m), game).items == []


def test_object_owner_resolves_to_a_defined_team():
    game = _game_with_object("Foo")
    # `_team("team")` is harvested as both "team" and the qualified neutral form "/team".
    m = _map(teams=[_team("team")], objects=[_object("Foo", originalOwner="/team")])
    assert lint_map(MapModel.from_map(m), game).items == []


def test_object_owner_dangles_for_unknown_team():
    game = _game_with_object("Foo")
    m = _map(
        teams=[_team("team")],
        objects=[
            _object("Foo", originalOwner="Ghost/teamGhost"),
            _object("Foo", originalOwner="Ghost/teamGhost"),
        ],
    )
    diags = lint_map(MapModel.from_map(m), game).items
    assert len(diags) == 1  # deduped, with the placed-instance count
    assert diags[0].code == "map-dangling-property"
    assert diags[0].extra == {
        "name": "Ghost/teamGhost",
        "noun": "team",
        "scope": "map",
        "target": "teams",
        "key": "originalOwner",
        "count": 2,
    }
    assert "originalOwner" in diags[0].message


def test_object_owner_skipped_when_map_has_no_teams():
    # A map declaring no teams cannot meaningfully check ownership, so the check stays silent.
    game = _game_with_object("Foo")
    m = _map(objects=[_object("Foo", originalOwner="/team")])
    assert lint_map(MapModel.from_map(m), game).items == []


def test_object_upgrades_list_splits_and_resolves_each_name():
    game = _game(objects=["Foo"], upgrades=["Upgrade_Known"])
    m = _map(
        objects=[
            _object("Foo", objectUpgradesList="Upgrade_Known Upgrade_Missing "),
            _object("Foo", objectUpgradesList="Upgrade_Missing "),
        ]
    )
    diags = lint_map(MapModel.from_map(m), game).items
    # the known upgrade resolves; only the missing one flags, once, with the count across objects
    assert len(diags) == 1
    assert diags[0].code == "map-dangling-property"
    assert diags[0].extra == {
        "name": "Upgrade_Missing",
        "noun": "upgrade",
        "scope": "game",
        "target": "upgrades",
        "key": "objectUpgradesList",
        "count": 2,
    }


def test_object_upgrades_skipped_when_upgrades_table_empty():
    game = _game(objects=["Foo"])  # no upgrades built: the GAME empty-table guard applies
    m = _map(objects=[_object("Foo", objectUpgradesList="Upgrade_X ")])
    assert lint_map(MapModel.from_map(m), game).items == []
