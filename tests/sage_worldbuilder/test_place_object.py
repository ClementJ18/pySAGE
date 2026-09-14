"""Placing objects without Qt: the palette, the new object's properties, footprints, and a placed
object surviving a save of a real map."""

import io
from pathlib import Path
from types import SimpleNamespace

from sage_map.assets.object_list import Object, ObjectsList
from sage_map.context import AssetPropertyType
from sage_map.map import Map, parse_map, write_map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.footprints import Footprint, Footprints, FootprintShape
from sage_worldbuilder.objects import new_object, place_objects
from sage_worldbuilder.palette import (
    CIVILIAN,
    NO_SORTING,
    filter_palette,
    names_under,
    object_palette,
)

FIXTURE = Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "spieler.map"


def sorting(*names):
    return [SimpleNamespace(name=name) for name in names]


def test_palette_groups_by_side_then_by_editor_sorting_in_order():
    game = SimpleNamespace(
        objects={
            "tree02": SimpleNamespace(EditorSorting=sorting("SHRUBBERY")),
            "GondorBarracks": SimpleNamespace(EditorSorting=sorting("STRUCTURE"), Side="Gondor"),
            "Tree01": SimpleNamespace(EditorSorting=sorting("SHRUBBERY")),
            "GondorFighter": SimpleNamespace(EditorSorting=sorting("UNIT"), Side="Gondor"),
            # No Side and no EditorSorting: the engine's defaults, Civilian and NONE.
            "Mystery": SimpleNamespace(),
        }
    )
    groups = object_palette(game)
    assert list(groups) == [CIVILIAN, "Gondor"]
    assert list(groups[CIVILIAN]) == ["Shrubbery", NO_SORTING]
    assert groups[CIVILIAN]["Shrubbery"] == ["Tree01", "tree02"]
    assert groups[CIVILIAN][NO_SORTING] == ["Mystery"]
    assert list(groups["Gondor"]) == ["Structures", "Units"]
    assert filter_palette(groups, "TREE") == {CIVILIAN: {"Shrubbery": ["Tree01", "tree02"]}}
    assert filter_palette(groups, "GONDOR") == {
        "Gondor": {"Structures": ["GondorBarracks"], "Units": ["GondorFighter"]}
    }
    assert filter_palette(groups, "  ") is groups
    assert names_under(groups, "Shrubbery", "Units") == ["GondorFighter", "Tree01", "tree02"]


def test_an_empty_side_field_files_the_object_under_civilian():
    game = SimpleNamespace(objects={"Rock": SimpleNamespace(Side="  ")})
    assert object_palette(game) == {CIVILIAN: {NO_SORTING: ["Rock"]}}


def test_new_object_properties_follow_the_corpus_layout():
    map = Map()
    existing = Object(3, (0.0, 0.0, 0.0), 0.0, 0, "Tree", {}, 0, 0)
    existing.properties["uniqueID"] = {
        "name": "uniqueID",
        "type": AssetPropertyType.AsciiString,
        "value": "Tree 6",
    }
    map.objects_list = ObjectsList(version=3, object_list=[existing], start_pos=0, end_pos=0)
    obj = new_object(map, "GondorFighter", (10.0, 20.0, 5.0), 1.5, "PlyrCivilian/teamPlyrCivilian")
    assert list(obj.properties) == [
        "objectInitialHealth",
        "objectEnabled",
        "objectIndestructible",
        "objectUnsellable",
        "objectPowered",
        "objectRecruitableAI",
        "objectTargetable",
        "objectBasePriority",
        "objectBasePhase",
        "originalOwner",
        "uniqueID",
        "objectLayer",
    ]
    assert obj.properties["uniqueID"]["value"] == "GondorFighter 7"
    assert obj.properties["objectEnabled"]["type"] is AssetPropertyType.Boolean
    assert obj.properties["originalOwner"]["value"] == "PlyrCivilian/teamPlyrCivilian"
    assert (obj.version, obj.position, obj.angle, obj.road_type) == (3, (10.0, 20.0, 5.0), 1.5, 0)

    document = MapDocument(map)
    document.execute(place_objects(map, [obj]))
    assert map.objects_list.object_list == [existing, obj]
    document.stack.undo()
    assert map.objects_list.object_list == [existing]


def test_a_placed_object_survives_saving_a_real_map():
    map = parse_map(io.BytesIO(FIXTURE.read_bytes()))
    before = len(map.objects_list.object_list)
    obj = new_object(map, "GondorFighter", (123.5, 456.25, 0.0), 0.75, "/team")
    MapDocument(map).execute(place_objects(map, [obj]))
    reread = parse_map(io.BytesIO(write_map(map, False)))
    objects = reread.objects_list.object_list
    assert len(objects) == before + 1
    placed = objects[-1]
    assert placed.type_name == "GondorFighter"
    assert placed.position == (123.5, 456.25, 0.0)
    assert placed.angle == 0.75
    assert placed.properties == obj.properties


def geometry(kind, major, minor=0.0):
    return SimpleNamespace(
        type=SimpleNamespace(name=kind), GeometryMajorRadius=major, GeometryMinorRadius=minor
    )


def test_footprints_from_the_first_geometry_shape():
    game = SimpleNamespace(
        objects={
            "Barracks": SimpleNamespace(geometry=[geometry("BOX", 40.0, 25.0)]),
            "Tower": SimpleNamespace(geometry=[geometry("CYLINDER", 15.0)]),
            "Flag": SimpleNamespace(geometry=[geometry("BOX", 0.0)]),
            "Marker": SimpleNamespace(geometry=[]),
        }
    )
    footprints = Footprints(game)
    assert footprints.get("barracks") == Footprint(FootprintShape.BOX, 40.0, 25.0)
    assert footprints.get("Tower") == Footprint(FootprintShape.CIRCLE, 15.0, 15.0)
    assert footprints.get("Flag") is None
    assert footprints.get("Marker") is None
    assert footprints.get("Unknown") is None
