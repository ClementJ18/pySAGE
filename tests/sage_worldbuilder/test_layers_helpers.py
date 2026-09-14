"""Layers and the selection helpers, without Qt."""

import math
from types import SimpleNamespace

from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.teams import Teams
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.anchors import RotationAnchors
from sage_worldbuilder.layers import (
    delete_layer,
    item_layer,
    items_in_layer,
    layer_counts,
    merge_layer,
    rename_layer,
    set_layer,
)
from sage_worldbuilder.selection_helpers import (
    TemplateIndex,
    base_parents,
    base_siblings,
    deprecated_objects,
    duplicate_objects,
    missing_objects,
    objects_with_bad_teams,
    replace_objects,
    similar_objects,
)
from sage_worldbuilder.teams import new_team


def placed(type_name, x=0.0, y=0.0, **text):
    properties = {
        key: {"name": key, "type": AssetPropertyType.AsciiString, "value": value}
        for key, value in text.items()
    }
    return Object(3, (x, y, 0.0), 0.0, 0, type_name, properties, 0, 0)


def layered_map():
    map = Map()
    map.objects_list = ObjectsList(
        version=3,
        object_list=[
            placed("Tree", objectLayer="Trees"),
            placed("Tree", objectLayer="Trees"),
            placed("Rock", objectLayer=""),
            placed("Wall"),
        ],
        start_pos=0,
        end_pos=0,
    )
    map.trigger_areas = TriggerAreas(
        version=1,
        trigger_areas=[TriggerArea("Zone", "Areas", 1, [(0.0, 0.0)], 0)],
        start_pos=0,
        end_pos=0,
    )
    return map


def test_layer_counts_and_membership():
    map = layered_map()
    assert layer_counts(map) == {"": (2, 0), "Areas": (0, 1), "Trees": (2, 0)}
    assert item_layer(map.objects_list.object_list[3]) == ""
    assert item_layer("not an item") is None
    assert len(items_in_layer(map, "Trees")) == 2


def test_rename_delete_merge_and_move_are_undoable():
    map = layered_map()
    document = MapDocument(map)
    trees = items_in_layer(map, "Trees")
    zone = map.trigger_areas.trigger_areas[0]

    document.execute(rename_layer(map, "Trees", "Forest"))
    assert layer_counts(map)["Forest"] == (2, 0) and "Trees" not in layer_counts(map)
    document.execute(merge_layer(map, "Areas", "Forest"))
    assert zone.layer_name == "Forest"
    document.execute(delete_layer(map, "Forest"))
    assert layer_counts(map) == {"": (4, 1)}
    document.stack.undo()
    document.stack.undo()
    document.stack.undo()
    assert layer_counts(map) == {"": (2, 0), "Areas": (0, 1), "Trees": (2, 0)}

    wall = map.objects_list.object_list[3]
    command = set_layer([wall, *trees], "Trees")
    assert len(command.commands) == 1
    document.execute(command)
    assert wall.properties["objectLayer"]["value"] == "Trees"
    assert list(wall.properties) == ["objectLayer"]


def test_duplicates_are_objects_standing_together():
    # A castle's walls share one stored pivot and stand apart, turned about it.
    walls = [placed("CastleWall", 0.0, 0.0) for _ in range(3)]
    for wall, degrees in zip(walls, (0, 120, 240), strict=True):
        wall.angle = math.radians(degrees)
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=walls, start_pos=0, end_pos=0)
    game = SimpleNamespace(
        objects={"CastleWall": SimpleNamespace(GeometryRotationAnchorOffset=[[375.0, 0.0, 0.0]])}
    )
    assert duplicate_objects(map) == walls[1:]
    assert duplicate_objects(map, anchors=RotationAnchors(game)) == []


def test_base_objects_are_found_by_the_base_they_belong_to():
    # A real map stores `objectIsABase` as a boolean; both it and a non-empty string count.
    centre = placed(
        "ElvenCentre", objectBaseName="Fortress", objectName="Fortress", objectIsABase="1"
    )
    wall = placed("ElvenWall", 10.0, objectBaseName="Fortress")
    tower = placed("ElvenTower", 0.0, 10.0, objectBaseName="fortress")
    tree = placed("Tree", 50.0, 50.0)
    map = Map()
    map.objects_list = ObjectsList(
        version=3, object_list=[centre, wall, tower, tree], start_pos=0, end_pos=0
    )

    assert base_siblings(map, [wall]) == [centre, wall, tower]
    assert base_parents(map, [wall, tower]) == [centre]
    assert base_siblings(map, [tree]) == [] and base_parents(map, [tree]) == []
    assert base_parents(map, [centre]) == [centre]


def test_selection_helpers():
    map = Map()
    tree_a = placed("Tree", 10.0, 10.0, originalOwner="/team")
    tree_b = placed("tree", 10.4, 9.8, originalOwner="PlyrGone/teamPlyrGone")
    rock = placed("Rock", 50.0, 50.0, originalOwner="/team")
    old = placed("OldHut", 90.0, 90.0)
    waypoint = placed("*Waypoints/Waypoint", 5.0, 5.0)
    map.objects_list = ObjectsList(
        version=3, object_list=[tree_a, tree_b, rock, old, waypoint], start_pos=0, end_pos=0
    )
    map.teams = Teams(version=1, teams=[new_team("team", "")], start_pos=0, end_pos=0)

    assert similar_objects(map, [tree_a]) == [tree_a, tree_b]
    assert duplicate_objects(map) == [tree_b]
    assert duplicate_objects(map, tolerance=0.1) == []
    assert objects_with_bad_teams(map) == [tree_b]

    obsolete = SimpleNamespace(EditorSorting=[SimpleNamespace(name="OBSOLETE")])
    game = SimpleNamespace(
        objects={"Tree": SimpleNamespace(EditorSorting=[]), "Rock": object(), "OldHut": obsolete}
    )
    templates = TemplateIndex(game)
    assert deprecated_objects(map, templates) == [old]
    assert missing_objects(map, TemplateIndex(SimpleNamespace(objects={"Tree": object()}))) == [
        rock,
        old,
    ]

    document = MapDocument(map)
    document.execute(replace_objects([tree_a, rock], "Rock"))
    assert (tree_a.type_name, rock.type_name) == ("Rock", "Rock")
    assert tree_a.properties["originalOwner"]["value"] == "/team"
    document.stack.undo()
    assert tree_a.type_name == "Tree"
