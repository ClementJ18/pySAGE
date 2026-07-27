"""The binary-map side of a rename: which `.map` layouts name the symbol being renamed.

Maps are hand-built in memory (the same idiom as `tests/sage_map/test_sage_map_linter.py`), so
no `.map` fixture or corpus is needed. Nothing here rewrites a map - that is the point of the
module under test: a layout is reported so the rename's damage to it is visible, never edited.
"""

from sage_lint.rename_maps import map_hits, scan_maps
from sage_map import Map, MapModel, write_map_to_path
from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.player_scripts import (
    PlayerScriptsList,
    Script,
    ScriptArgument,
    ScriptDerived,
    ScriptList,
)
from sage_map.assets.player_scripts import ScriptArgumentType as AT
from sage_map.assets.sides_list import SidesList


def _prop(name, value):
    return {"name": name, "type": None, "value": value}


def _arg(arg_type, string_value=""):
    return ScriptArgument(type=arg_type, int_value=0, float_value=0.0, string_value=string_value)


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
    script.actions_if_true = list(actions)
    return script


def _object(type_name, **props):
    return Object(
        version=1,
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        road_type=0,
        type_name=type_name,
        properties={key: _prop(key, value) for key, value in props.items()},
        start_pos=0,
        end_pos=0,
    )


def _model(*, objects=None, scripts=()):
    raw = Map()
    raw.teams = None
    raw.sides_list = SidesList(
        version=6, unknown1=False, players=[], start_pos=0, end_pos=0, teams=[]
    )
    raw.objects_list = (
        None
        if objects is None
        else ObjectsList(version=1, object_list=list(objects), start_pos=0, end_pos=0)
    )
    raw.trigger_areas = None
    raw.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=list(scripts), start_pos=0, end_pos=0)],
        start_pos=0,
        end_pos=0,
    )
    return MapModel.from_map(raw)


class TestMapHits:
    def test_finds_a_placed_object_of_that_type(self):
        model = _model(objects=[_object("GondorTower")])

        assert list(map_hits(model, "objects", "GondorTower")) == ["placed object"]

    def test_counts_each_placed_instance(self):
        model = _model(objects=[_object("GondorTower"), _object("GondorTower")])

        assert list(map_hits(model, "objects", "GondorTower")) == ["placed object"] * 2

    def test_matches_case_insensitively(self):
        model = _model(objects=[_object("gondortower")])

        assert list(map_hits(model, "objects", "GondorTower")) == ["placed object"]

    def test_ignores_an_object_of_another_type(self):
        model = _model(objects=[_object("RohanBarracks")])

        assert list(map_hits(model, "objects", "GondorTower")) == []

    def test_finds_an_upgrade_in_an_object_property(self):
        model = _model(
            objects=[_object("GondorTower", objectUpgradesList="Upgrade_Fire Upgrade_Stone")]
        )

        assert list(map_hits(model, "upgrades", "Upgrade_Fire")) == [
            "object property 'objectUpgradesList'"
        ]

    def test_finds_a_game_scope_script_argument(self):
        model = _model(scripts=[_script("Spawn", _action(_arg(AT.OBJECT_TYPE, "GondorTower")))])

        assert list(map_hits(model, "objects", "GondorTower")) == [
            "script argument Spawn/if_true[0]/arg[0]"
        ]

    def test_ignores_a_script_argument_of_another_table(self):
        # An upgrade-named argument is not an object reference, whatever the spelling.
        model = _model(scripts=[_script("Grant", _action(_arg(AT.UPGRADE_NAME, "Shared")))])

        assert list(map_hits(model, "objects", "Shared")) == []
        assert list(map_hits(model, "upgrades", "Shared")) == [
            "script argument Grant/if_true[0]/arg[0]"
        ]

    def test_a_map_with_no_objects_or_scripts_yields_nothing(self):
        assert list(map_hits(_model(), "objects", "GondorTower")) == []


class TestScanMaps:
    def test_reports_a_map_on_disk_and_leaves_it_untouched(self, tmp_path):
        path = tmp_path / "MyMap" / "MyMap.map"
        path.parent.mkdir(parents=True)
        write_map_to_path(_model(objects=[_object("GondorTower")]).raw, path, compress=False)
        before = path.read_bytes()

        usages, unreadable = scan_maps([path], "objects", "GondorTower")

        assert unreadable == []
        assert [(usage.where, usage.count) for usage in usages] == [("placed object", 1)]
        assert path.read_bytes() == before  # a layout is reported, never rewritten

    def test_an_unreadable_map_is_reported_not_raised(self, tmp_path):
        path = tmp_path / "broken.map"
        path.write_bytes(b"not a map at all")

        usages, unreadable = scan_maps([path], "objects", "GondorTower")

        assert usages == []
        assert len(unreadable) == 1
        assert "broken.map" in unreadable[0]
