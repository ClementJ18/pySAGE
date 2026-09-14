"""Waypoints, their links, and trigger areas, without Qt: layouts, ids and names, undoable edits,
picking inside an area, and a real map saving them."""

import io
from pathlib import Path

from sage_map.assets.object_list import ObjectsList
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas
from sage_map.assets.waypoint_list import WaypointsList
from sage_map.map import Map, parse_map, write_map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.areas import (
    DeleteAreas,
    MoveAreaPoint,
    add_area,
    area_contains,
    new_area,
    new_area_name,
)
from sage_worldbuilder.objects import MoveObjects, place_objects
from sage_worldbuilder.scene import MapScene
from sage_worldbuilder.waypoints import (
    add_linked_waypoint,
    find_link,
    new_waypoint,
    toggle_link,
    waypoint_id,
)

FIXTURE = Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "spieler.map"
SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def empty_map() -> Map:
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    map.trigger_areas = TriggerAreas(version=1, trigger_areas=[], start_pos=0, end_pos=0)
    return map


def value(obj, key):
    return obj.properties[key]["value"]


def test_new_waypoint_layout_ids_and_names():
    map = empty_map()
    document = MapDocument(map)
    first = new_waypoint(map, (5.0, 6.0, 0.0))
    assert list(first.properties)[-6:] == [
        "waypointID",
        "waypointName",
        "waypointTypeOption",
        "waypointPathLabel1",
        "waypointPathLabel2",
        "waypointPathLabel3",
    ]
    assert list(first.properties)[:12][-3:] == ["originalOwner", "uniqueID", "objectLayer"]
    assert first.type_name == "*Waypoints/Waypoint"
    assert value(first, "originalOwner") == "/team"
    assert (value(first, "waypointID"), value(first, "waypointName")) == (1, "Waypoint 1")
    assert value(first, "uniqueID") == "Waypoint 1"
    document.execute(place_objects(map, [first], "Add Waypoint"))
    second = new_waypoint(map, (0.0, 0.0, 0.0))
    assert (waypoint_id(second), value(second, "waypointName")) == (2, "Waypoint 2")


def test_links_toggle_and_a_linked_waypoint_is_one_edit():
    map = empty_map()
    document = MapDocument(map)
    start = new_waypoint(map, (0.0, 0.0, 0.0))
    document.execute(place_objects(map, [start]))
    command, added = add_linked_waypoint(map, 1, (50.0, 0.0, 0.0))
    document.execute(command)
    assert map.waypoints_list.waypoint_paths == [(1, 2)]
    assert map.objects_list.object_list == [start, added]
    document.execute(toggle_link(map, 2, 1))
    assert map.waypoints_list.waypoint_paths == []
    document.stack.undo()
    assert find_link(map, 2, 1) == 0
    document.stack.undo()
    assert map.objects_list.object_list == [start]
    assert map.waypoints_list.waypoint_paths == []


def test_new_areas_take_free_names_and_the_next_id():
    map = empty_map()
    map.trigger_areas.trigger_areas.append(TriggerArea("Area 1", "", 7, list(SQUARE), 0))
    assert new_area_name(map) == "Area 2"
    area = new_area(map, [(1, 2), (3, 4), (5, 6)])
    assert (area.name, area.layer_name, area.area_id, area.unknown2) == ("Area 2", "", 8, 0)
    assert area.points == [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
    document = MapDocument(map)
    document.execute(add_area(map, area))
    assert map.trigger_areas.trigger_areas[-1] is area
    document.execute(DeleteAreas([map.trigger_areas.trigger_areas[0]]))
    assert map.trigger_areas.trigger_areas == [area]
    document.stack.undo()
    assert [a.name for a in map.trigger_areas.trigger_areas] == ["Area 1", "Area 2"]


def test_corner_moves_merge_until_closed_and_areas_move_with_objects():
    map = empty_map()
    area = TriggerArea("Zone", "", 1, list(SQUARE), 0)
    map.trigger_areas.trigger_areas.append(area)
    document = MapDocument(map)
    document.execute(MoveAreaPoint(area, 2, (12.0, 12.0)))
    first = document.stack._done[-1]
    document.execute(MoveAreaPoint(area, 2, (14.0, 13.0)))
    first.closed = True
    document.execute(MoveAreaPoint(area, 2, (20.0, 20.0)))
    document.stack.undo()
    assert area.points[2] == (14.0, 13.0)
    document.stack.undo()
    assert area.points[2] == (10.0, 10.0)

    document.execute(MoveObjects([], 5.0, -1.0, areas=[area]))
    assert area.points[0] == (5.0, -1.0)
    document.stack.undo()
    assert area.points == SQUARE


def test_picking_inside_areas():
    assert area_contains(SQUARE, 5.0, 5.0)
    assert not area_contains(SQUARE, 15.0, 5.0)
    map = empty_map()
    lower = TriggerArea("Lower", "", 1, list(SQUARE), 0)
    upper = TriggerArea("Upper", "", 2, [(5.0, 5.0), (20.0, 5.0), (20.0, 20.0)], 0)
    map.trigger_areas.trigger_areas += [lower, upper]
    scene = MapScene.from_map(map)
    assert scene.area_at(8.0, 6.0).source is upper
    assert scene.area_at(2.0, 2.0).source is lower
    assert scene.area_at(8.0, 6.0, accept=lambda outline: outline.source is lower).source is lower
    assert scene.area_at(50.0, 50.0) is None


def test_waypoints_links_and_areas_survive_saving_a_real_map():
    map = parse_map(io.BytesIO(FIXTURE.read_bytes()))
    document = MapDocument(map)
    start = new_waypoint(map, (100.0, 100.0, 0.0))
    document.execute(place_objects(map, [start]))
    command, added = add_linked_waypoint(map, waypoint_id(start), (200.0, 100.0, 0.0))
    document.execute(command)
    area = new_area(map, [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0)])
    document.execute(add_area(map, area))

    reread = parse_map(io.BytesIO(write_map(map, False)))
    objects = reread.objects_list.object_list
    assert [obj.properties for obj in objects[-2:]] == [start.properties, added.properties]
    assert reread.waypoints_list.waypoint_paths[-1] == (waypoint_id(start), waypoint_id(added))
    saved = reread.trigger_areas.trigger_areas[-1]
    assert (saved.name, saved.area_id, saved.points) == (area.name, area.area_id, area.points)
