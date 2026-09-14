"""Map data export and import: what Export Options puts in a library, and merging one into a map."""

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from sage_map.assets import ScriptApplyHeight, ScriptImportSize, ScriptPassability
from sage_map.assets.player_scripts import ScriptArgument, ScriptArgumentType
from sage_map.assets.script_passability import LAYERS
from sage_map.assets.trigger_areas import TriggerArea
from sage_map.map import parse_map_from_path
from sage_map.scb import ScriptLibrary, parse_scb, write_scb
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.objects import new_object
from sage_worldbuilder.scripting import new_script
from sage_worldbuilder.waypoints import new_waypoint

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.exchange import (  # noqa: E402
    SELECTION_PLAYER,
    DuplicateKind,
    DuplicatePolicy,
    ExportOptions,
    ImportChoices,
    ScriptsMode,
    build_export,
    import_library,
    plan_import,
)
from sage_worldbuilder.heightmap_io import Anchor  # noqa: E402
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402
from sage_worldbuilder.terrain.cells import CellLayer  # noqa: E402

FIXTURE = Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map kampa good 08.map"
T = ScriptArgumentType


def _map(size=32):
    return new_map(NewMapOptions(width=size, height=size, border=1 if size < 16 else 2))


def _text(obj, key):
    return obj.properties[key]["value"]


def _set(obj, key, value):
    kind = type(next(iter(obj.properties.values()))["type"]).AsciiString
    obj.properties[key] = {"name": key, "type": kind, "value": value}


def _unit(map, name, position, owner="/team"):
    obj = new_object(map, "Hero", position, 0.0, owner)
    if name:
        _set(obj, "objectName", name)
    map.objects_list.object_list.append(obj)
    return obj


def _waypoint(map, name, position):
    obj = new_waypoint(map, position)
    _set(obj, "waypointName", name)
    map.objects_list.object_list.append(obj)
    return obj


def _area(map, name, points=((0.0, 0.0), (50.0, 0.0), (50.0, 50.0))):
    area = TriggerArea(name, "", len(map.trigger_areas.trigger_areas) + 1, list(points), 0)
    map.trigger_areas.trigger_areas.append(area)
    return area


def _script(map, name, *arguments):
    script = new_script(name)
    script.actions_if_true.append(
        SimpleNamespace(
            arguments=[ScriptArgument(kind, string_value=value) for kind, value in arguments]
        )
    )
    map.player_scripts_list.script_lists[0].items.append(script)
    return script


def _waypoint_id(obj):
    return obj.properties["waypointID"]["value"]


def test_an_export_of_all_scripts_takes_what_the_scripts_name():
    map = _map()
    hero = _unit(map, "Hero", (100.0, 100.0, 0.0))
    _unit(map, "", (120.0, 100.0, 0.0), owner="/other")
    a = _waypoint(map, "A", (10.0, 10.0, 0.0))
    b = _waypoint(map, "B", (20.0, 10.0, 0.0))
    _waypoint(map, "C", (30.0, 10.0, 0.0))
    map.waypoints_list.waypoint_paths.append((_waypoint_id(a), _waypoint_id(b)))
    zone = _area(map, "Zone")
    _area(map, "Other")
    _script(map, "Go", (T.UNIT_NAME, "Hero"), (T.WAYPOINT_NAME, "A"), (T.TRIGGER_AREA_NAME, "Zone"))

    library = build_export(map, ExportOptions())

    assert (library.script_import_size.width, library.script_import_size.height) == (32, 32)
    assert [obj.type_name for obj in library.objects_list.object_list] == [
        hero.type_name,
        a.type_name,
        b.type_name,
    ]
    assert [area.name for area in library.trigger_areas.trigger_areas] == [zone.name]
    assert library.waypoints_list.waypoint_paths == [(_waypoint_id(a), _waypoint_id(b))]
    assert [s.name for s in library.player_scripts_list.script_lists[0].items] == ["Go"]
    assert [player.name for player in library.scripts_players.players] == [""]
    assert [t.properties["teamName"]["value"] for t in library.script_teams.teams] == ["team"]
    assert library.height_map_data is None and library.script_passability is None


def test_options_choose_selected_objects_passability_and_no_scripts():
    map = _map(16)
    _unit(map, "Hero", (100.0, 100.0, 0.0))
    extra = _unit(map, "", (120.0, 100.0, 0.0))
    _script(map, "Go", (T.UNIT_NAME, "Hero"))
    options = ExportOptions(
        scripts=ScriptsMode.NONE,
        selected_objects=True,
        passability=True,
        terrain_height=True,
        lighting=True,
    )

    library = build_export(map, options, selection=[extra])

    assert [_text(obj, "uniqueID") for obj in library.objects_list.object_list] == [
        _text(extra, "uniqueID")
    ]
    assert library.player_scripts_list.script_lists == []
    assert [player.name for player in library.scripts_players.players] == [SELECTION_PLAYER]
    cells = library.script_passability.cells
    assert sorted(cells) == sorted(name for name, _ in LAYERS)
    assert len(cells["impassability"]) == 16 and len(cells["impassability"][0]) == 16
    assert library.script_apply_height.apply_height is True and library.blend_tile_data is None
    assert library.global_lighting is not map.global_lighting


def test_an_import_of_another_size_lands_at_its_anchor_and_undoes():
    source = _map(32)
    hero = _unit(source, "Hero", (100.0, 100.0, 0.0))
    a = _waypoint(source, "A", (10.0, 10.0, 0.0))
    b = _waypoint(source, "B", (20.0, 10.0, 0.0))
    source.waypoints_list.waypoint_paths.append((_waypoint_id(a), _waypoint_id(b)))
    _area(source, "Zone")
    library = build_export(
        source,
        ExportOptions(
            scripts=ScriptsMode.NONE, all_waypoints=True, all_areas=True, selected_objects=True
        ),
        selection=[hero],
    )

    target = _map(64)
    existing = _waypoint(target, "Start", (5.0, 5.0, 0.0))
    document = MapDocument(target)
    plan = plan_import(target, library)
    assert plan.needs_anchor and plan.offset(Anchor.CENTER) == (16, 16)
    assert plan.offset(Anchor.BOTTOM_LEFT) == (0, 0) and plan.offset(Anchor.TOP_RIGHT) == (32, 32)

    command, report = import_library(target, library, ImportChoices(anchor=Anchor.CENTER))
    document.execute(command)

    objects = target.objects_list.object_list
    assert (report.objects, report.waypoints, report.areas) == (1, 2, 1)
    assert objects[1].position[:2] == (260.0, 260.0)
    ids = [_waypoint_id(obj) for obj in objects[2:]]
    assert ids == [_waypoint_id(existing) + 1, _waypoint_id(existing) + 2]
    assert target.waypoints_list.waypoint_paths == [tuple(ids)]
    assert target.trigger_areas.trigger_areas[-1].points[0] == (160.0, 160.0)
    assert _text(objects[1], "uniqueID") != _text(hero, "uniqueID") or len(objects) == 4

    document.stack.undo()
    assert target.objects_list.object_list == [existing]
    assert target.waypoints_list.waypoint_paths == []
    assert target.trigger_areas.trigger_areas == []


def test_duplicates_keep_the_existing_or_the_imported_item():
    source = _map()
    a = _waypoint(source, "A", (10.0, 10.0, 0.0))
    b = _waypoint(source, "B", (20.0, 10.0, 0.0))
    source.waypoints_list.waypoint_paths.append((_waypoint_id(a), _waypoint_id(b)))
    _unit(source, "Hero", (100.0, 100.0, 0.0))
    _area(source, "Zone", ((1.0, 1.0), (2.0, 1.0), (2.0, 2.0)))
    options = ExportOptions(scripts=ScriptsMode.NONE, all_waypoints=True, all_areas=True)
    library = build_export(source, options, selection=list(source.objects_list.object_list))
    library.objects_list.object_list.append(source.objects_list.object_list[-1])

    target = _map()
    kept_a = _waypoint(target, "A", (99.0, 99.0, 0.0))
    old_hero = _unit(target, "Hero", (5.0, 5.0, 0.0))
    old_zone = _area(target, "Zone")
    plan = plan_import(target, library)
    assert plan.duplicates == {
        DuplicateKind.OBJECT: ["Hero"],
        DuplicateKind.WAYPOINT: ["A"],
        DuplicateKind.AREA: ["Zone"],
    }

    document = MapDocument(target)
    choices = ImportChoices(
        duplicate_defaults={
            DuplicateKind.WAYPOINT: DuplicatePolicy.KEEP_EXISTING,
            DuplicateKind.OBJECT: DuplicatePolicy.KEEP_IMPORTED,
        },
        duplicates={(DuplicateKind.AREA, "Zone"): DuplicatePolicy.KEEP_IMPORTED},
    )
    command, _ = import_library(target, library, choices)
    document.execute(command)

    objects = target.objects_list.object_list
    assert kept_a in objects and old_hero not in objects
    assert [
        _text(obj, "waypointName") for obj in objects if obj.type_name.startswith("*Waypoints")
    ] == [
        "A",
        "B",
    ]
    new_b = next(
        obj for obj in objects if obj.properties.get("waypointName", {}).get("value") == "B"
    )
    assert target.waypoints_list.waypoint_paths == [(_waypoint_id(kept_a), _waypoint_id(new_b))]
    assert old_zone not in target.trigger_areas.trigger_areas
    assert target.trigger_areas.trigger_areas[0].points[0] == (1.0, 1.0)

    document.stack.undo()
    assert (
        old_hero in target.objects_list.object_list
        and old_zone in target.trigger_areas.trigger_areas
    )


def test_scripts_go_to_the_player_of_their_name_or_the_chosen_one():
    source = _map()
    go = _script(source, "Go")
    _script(source, "Taken")
    selected = build_export(
        source, ExportOptions(scripts=ScriptsMode.SELECTED), selected_scripts=[go]
    )
    everything = build_export(source, ExportOptions())
    everything.scripts_players.players[0].name = "Nobody"

    target = _map()
    _script(target, "Go")
    items = target.player_scripts_list.script_lists[0].items

    assert plan_import(target, selected).uses_selection
    command, report = import_library(target, selected, ImportChoices(selection_player=""))
    assert command is None and report.dropped_scripts == ["Go"]

    command, report = import_library(target, everything, ImportChoices())
    assert command is None and report.discarded_players == ["Nobody"]
    assert plan_import(target, everything).missing_script_players == ["Nobody"]

    everything.scripts_players.players[0].name = ""
    document = MapDocument(target)
    command, report = import_library(target, everything, ImportChoices())
    document.execute(command)
    assert [item.name for item in items] == ["Go", "Taken"]
    assert report.dropped_scripts == ["Go"] and report.scripts == 1


def test_a_team_whose_player_is_missing_needs_a_player():
    source = _map()
    team = source.teams.teams[0]
    team.properties["teamName"] = {**team.properties["teamName"], "value": "raiders"}
    team.properties["teamOwner"] = {**team.properties["teamOwner"], "value": "Orcs"}
    library = build_export(source, ExportOptions())

    target = _map()
    assert plan_import(target, library).teams_without_player == [("raiders", "Orcs")]
    _, report = import_library(target, library, ImportChoices())
    assert report.skipped_teams == ["raiders"]

    document = MapDocument(target)
    command, report = import_library(target, library, ImportChoices(team_players={"raiders": ""}))
    document.execute(command)
    added = target.teams.teams[-1].properties
    assert (added["teamName"]["value"], added["teamOwner"]["value"]) == ("raiders", "")


def test_heights_and_passability_land_at_the_anchor_clipped_to_the_map():
    small = _map(8)
    for row in small.height_map_data.elevations:
        row[:] = [5] * len(row)
    library = ScriptLibrary()
    library.script_import_size = ScriptImportSize(1, 8, 8, 0, 0)
    library.height_map_data = small.height_map_data
    library.script_apply_height = ScriptApplyHeight(1, True, 0, 0)
    cells = {name: [[0] * 8 for _ in range(8)] for name, _ in LAYERS}
    cells["impassability"] = [[1] * 8 for _ in range(8)]
    cells["visibility"] = [[1] * 8 for _ in range(8)]
    library.script_passability = ScriptPassability(3, cells, 0, 0)

    target = _map(32)
    document = MapDocument(target)
    before = document.terrain.heights.copy()
    command, _ = import_library(target, library, ImportChoices(anchor=Anchor.TOP_RIGHT))
    document.execute(command)

    heights = document.terrain.heights
    assert (heights[24:32, 24:32] == 5).all()
    assert np.array_equal(heights[:24, :], before[:24, :])
    impassable = document.cells(CellLayer.IMPASSABLE)
    assert impassable[24:32, 24:32].all() and not impassable[:24, :].any()

    document.stack.undo()
    assert np.array_equal(document.terrain.heights, before)


def test_an_export_of_a_real_map_survives_a_scb_file_and_imports_into_it():
    map = parse_map_from_path(FIXTURE)
    options = ExportOptions(
        all_waypoints=True, all_areas=True, water=True, lighting=True, terrain_height=True
    )
    written = write_scb(build_export(map, options))
    library = parse_scb(io.BytesIO(written))
    assert write_scb(library) == written

    document = MapDocument(parse_map_from_path(FIXTURE))
    command, report = import_library(document.map, library, ImportChoices())
    if command is not None:
        document.execute(command)
        document.stack.undo()
    assert report.discarded_players == []
