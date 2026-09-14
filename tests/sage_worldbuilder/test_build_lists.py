"""Build lists without Qt: entries per player, new entries, undoable edits, WorldBuilder's export
format and importing it, and a real map saving an added entry."""

import io
import math
from pathlib import Path

from sage_map.assets.sides_list import BuildList, BuildLists, SidesList
from sage_map.map import Map, parse_map, write_map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.build_lists import (
    MoveBuilding,
    add_entry,
    build_list_entries,
    export_build_list,
    import_entries,
    move_entry,
    new_entry,
    parse_build_list,
    remove_entry,
    side_label,
    side_names,
    stores_automatic_build,
)
from sage_worldbuilder.players import new_player

FIXTURE = Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "spieler.map"


def two_player_map() -> Map:
    map = Map()
    map.sides_list = SidesList(
        version=6,
        unknown1=False,
        players=[new_player(""), new_player("PlyrGood", "Good", "FactionMen")],
        start_pos=0,
        end_pos=0,
    )
    map.build_lists = BuildLists(
        version=6,
        build_lists=[
            BuildList(faction_name="UNKNOWN", faction_name_property=None, build_list=[]),
            BuildList(faction_name="Men", faction_name_property=None, build_list=[]),
        ],
        start_pos=0,
        end_pos=0,
    )
    return map


def test_sides_and_new_entries():
    map = two_player_map()
    assert side_names(map) == ["", "PlyrGood"]
    assert side_label(map, 1) == "PlyrGood (Men)"
    assert side_label(map, 0) == "(neutral) (UNKNOWN)"
    assert not stores_automatic_build(map)
    entry = new_entry(map, "GondorFarm", (10.0, 20.0, 0.0), 0.5)
    assert (entry.build_name, entry.template_name, entry.unknown) == (
        "GondorFarm",
        "GondorFarm",
        None,
    )
    assert (entry.health, entry.num_rebuilds, entry.is_initially_built) == (100, 0, False)
    assert build_list_entries(map, 5) is None


def test_add_reorder_move_and_remove_are_undoable():
    map = two_player_map()
    document = MapDocument(map)
    farm = new_entry(map, "GondorFarm", (0.0, 0.0, 0.0))
    barracks = new_entry(map, "GondorBarracks", (50.0, 0.0, 0.0))
    document.execute(add_entry(map, 1, farm))
    document.execute(add_entry(map, 1, barracks))
    entries = build_list_entries(map, 1)
    assert entries == [farm, barracks]
    assert move_entry(map, 1, 0, -1) is None
    document.execute(move_entry(map, 1, 1, -1))
    assert entries == [barracks, farm]

    document.execute(MoveBuilding(farm, (5.0, 5.0, 0.0)))
    first = document.stack._done[-1]
    document.execute(MoveBuilding(farm, (9.0, 9.0, 0.0)))
    first.closed = True
    document.execute(MoveBuilding(farm, (20.0, 20.0, 0.0)))
    document.stack.undo()
    assert farm.location == (9.0, 9.0, 0.0)

    document.execute(remove_entry(map, 1, 0))
    assert entries == [farm]
    # Undo the delete, the merged first move and the reorder.
    for _ in range(3):
        document.stack.undo()
    assert entries == [farm, barracks]
    assert farm.location == (0.0, 0.0, 0.0)


def test_export_uses_worldbuilder_format_and_imports_back():
    map = two_player_map()
    document = MapDocument(map)
    farm = new_entry(map, "GondorFarm", (10.0, 20.5, 0.0), math.radians(90))
    farm.build_name = "Farm One"
    farm.num_rebuilds = 2
    document.execute(add_entry(map, 1, farm))
    text = export_build_list(map, 1)
    assert text == (
        ";Skirmish AI Build List\n"
        "SkirmishBuildList Men\n"
        "  Structure GondorFarm\n"
        "    Name = Farm One\n"
        "    Location = X:10.00 Y:20.50\n"
        "    Rebuilds = 2\n"
        "    Angle = 90.00\n"
        "    InitiallyBuilt = No\n"
        "    AutomaticallyBuild = Yes\n"
        "  END ;Structure GondorFarm\n"
        "END ;SkirmishBuildList Men\n"
    )
    (structure,) = parse_build_list(text)
    assert (structure.template, structure.name, structure.x, structure.y) == (
        "GondorFarm",
        "Farm One",
        10.0,
        20.5,
    )
    assert (structure.rebuilds, structure.angle_degrees, structure.initially_built) == (
        2,
        90.0,
        False,
    )

    document.execute(import_entries(map, 0, [structure]))
    (imported,) = build_list_entries(map, 0)
    assert imported.build_name == "Farm One" and imported.num_rebuilds == 2
    assert imported.angle == math.radians(90.0)
    document.stack.undo()
    assert build_list_entries(map, 0) == []


def test_an_added_entry_survives_saving_a_real_map():
    map = parse_map(io.BytesIO(FIXTURE.read_bytes()))
    side = next(
        index for index in range(len(side_names(map))) if build_list_entries(map, index) is not None
    )
    entry = new_entry(map, "GondorFarm", (120.0, 340.0, 0.0), 1.25)
    MapDocument(map).execute(add_entry(map, side, entry))
    reread = parse_map(io.BytesIO(write_map(map, False)))
    saved = build_list_entries(reread, side)[-1]
    assert saved == entry
