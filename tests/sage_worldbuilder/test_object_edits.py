"""Selection, pick allowances, and the undoable object edits: move, rotate, delete, copy, paste."""

import math
from types import SimpleNamespace

import pytest

from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.waypoint_list import WaypointsList
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.objects import (
    DeleteObjects,
    GroupEditMethod,
    MoveObjects,
    RotateObjects,
    clipboard_from_json,
    clipboard_to_json,
    copy_objects,
    paste_objects,
)
from sage_worldbuilder.pick import ANYTHING, NOTHING, PickCategory, PickRules
from sage_worldbuilder.scene import MapScene
from sage_worldbuilder.selection import Selection


def placed(type_name, x=0.0, y=0.0, **properties):
    stored = {
        key: {
            "name": key,
            "type": AssetPropertyType.Integer
            if isinstance(v, int)
            else AssetPropertyType.AsciiString,
            "value": v,
        }
        for key, v in properties.items()
    }
    return Object(3, (x, y, 5.0), 0.0, 0, type_name, stored, 0, 0)


def document_with(*objects, links=()) -> MapDocument:
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=list(objects), start_pos=0, end_pos=0)
    map.waypoints_list = WaypointsList(
        version=1, waypoint_paths=list(links), start_pos=0, end_pos=0
    )
    return MapDocument(map)


def value(obj, key):
    return obj.properties[key]["value"]


def test_selection_keeps_order_notifies_and_forgets_removed_objects():
    a, b, c = placed("A"), placed("B"), placed("C")
    selection = Selection()
    calls = []
    selection.subscribe(lambda: calls.append(len(selection)))
    selection.set([b, a])
    selection.set([b, a])
    selection.toggle(c)
    selection.toggle(b)
    assert selection.items == (a, c)
    assert b not in selection and a in selection
    selection.keep_only([c])
    assert selection.items == (c,)
    assert calls == [2, 3, 2, 1]


def test_document_drops_deleted_objects_from_the_selection():
    tree, rock = placed("Tree"), placed("Rock")
    document = document_with(tree, rock)
    document.selection.set([tree, rock])
    document.execute(DeleteObjects([tree]))
    assert document.selection.items == (rock,)
    document.stack.undo()
    assert document.selection.items == (rock,)


def test_pick_rules_follow_editor_sorting_and_marker_kinds():
    sorting = lambda name: SimpleNamespace(name=name)  # noqa: E731
    game = SimpleNamespace(
        objects={
            "GondorBarracks": SimpleNamespace(EditorSorting=[sorting("STRUCTURE")]),
            "Tree": SimpleNamespace(EditorSorting=[sorting("SHRUBBERY")]),
        }
    )
    document = document_with(
        placed("GondorBarracks"),
        placed("tree"),
        placed("*Waypoints/Waypoint", waypointID=1),
        placed("Mystery"),
    )
    scene = MapScene.from_map(document.map)
    barracks, tree, waypoint, mystery = scene.markers
    rules = PickRules(game, frozenset({PickCategory.BUILDINGS}))
    assert rules.category(tree) is PickCategory.SHRUBBERY
    assert rules.allows(barracks) and not rules.allows(tree) and not rules.allows(waypoint)
    assert rules.allows(mystery)
    assert not PickRules(game, NOTHING).allows(mystery)
    assert PickRules(None, ANYTHING).allows(barracks)
    assert PickRules(game, frozenset({PickCategory.WAYPOINTS_AREAS})).allows(waypoint)


def test_moves_merge_and_undo_exactly():
    a, b = placed("A", 10.0, 20.0), placed("B", 30.0, 40.0)
    document = document_with(a, b)
    for _ in range(3):
        document.execute(MoveObjects([a, b], 0.1, -0.2))
    assert document.stack.undo_label == "Move"
    assert a.position == pytest.approx((10.3, 19.4, 5.0))
    document.stack.undo()
    assert a.position == (10.0, 20.0, 5.0) and b.position == (30.0, 40.0, 5.0)
    assert not document.stack.can_undo
    document.stack.redo()
    assert b.position == pytest.approx((30.3, 39.4, 5.0))


def test_rotation_group_edit_methods():
    def pair():
        return placed("A", 0.0, 0.0), placed("B", 10.0, 0.0)

    a, b = pair()
    b.angle = 1.0
    document = document_with(a, b)
    document.execute(RotateObjects([a, b], 0.5, GroupEditMethod.INDEPENDENT))
    assert (a.angle, b.angle) == (0.5, 1.5)
    assert a.position == (0.0, 0.0, 5.0)

    a, b = pair()
    b.angle = 1.0
    document = document_with(a, b)
    document.execute(RotateObjects([a, b], 0.5, GroupEditMethod.MATCH_LEAD))
    assert (a.angle, b.angle) == (0.5, 0.5)

    a, b = pair()
    document = document_with(a, b)
    document.execute(RotateObjects([a, b], math.pi / 4, GroupEditMethod.AS_GROUP))
    document.execute(RotateObjects([a, b], math.pi / 4, GroupEditMethod.AS_GROUP))
    assert a.position == pytest.approx((5.0, -5.0, 5.0))
    assert b.position == pytest.approx((5.0, 5.0, 5.0))
    assert a.angle == pytest.approx(math.pi / 2)
    document.stack.undo()
    assert a.position == (0.0, 0.0, 5.0) and a.angle == 0.0


def test_delete_removes_waypoint_links_and_undo_restores_order():
    tree = placed("Tree")
    start = placed("*Waypoints/Waypoint", waypointID=1, waypointName="Start")
    end = placed("*Waypoints/Waypoint", waypointID=2, waypointName="End")
    other = placed("*Waypoints/Waypoint", waypointID=3, waypointName="Other")
    document = document_with(tree, start, end, other, links=[(1, 2), (3, 1), (2, 3)])
    document.execute(DeleteObjects([start, tree]))
    assert document.map.objects_list.object_list == [end, other]
    assert document.map.waypoints_list.waypoint_paths == [(2, 3)]
    document.stack.undo()
    assert document.map.objects_list.object_list == [tree, start, end, other]
    assert document.map.waypoints_list.waypoint_paths == [(1, 2), (3, 1), (2, 3)]


def test_paste_gives_copies_fresh_ids_names_and_links():
    guard = placed("GondorFighter", 0.0, 0.0, uniqueID="GondorFighter 0", objectName="Guard")
    start = placed(
        "*Waypoints/Waypoint", 10.0, 0.0, waypointID=1, waypointName="Start", uniqueID="Start"
    )
    end = placed(
        "*Waypoints/Waypoint",
        20.0,
        0.0,
        waypointID=2,
        waypointName="Waypoint 4",
        uniqueID="Waypoint 4",
    )
    document = document_with(guard, start, end, links=[(1, 2)])
    clipboard = copy_objects(document.map, [guard, start, end])
    assert clipboard.center == (10.0, 0.0)
    assert clipboard.links == ((1, 2),)

    command, pasted = paste_objects(document.map, clipboard, (110.0, 50.0))
    document.execute(command)
    new_guard, new_start, new_end = pasted
    assert new_guard.position == (100.0, 50.0, 5.0)
    assert value(new_guard, "uniqueID") == "GondorFighter 5"
    assert "objectName" not in new_guard.properties
    assert value(new_start, "waypointID") == 3 and value(new_end, "waypointID") == 4
    assert value(new_start, "waypointName") == "Waypoint 5"
    assert value(new_end, "waypointName") == "Waypoint 6"
    assert value(new_end, "uniqueID") == "Waypoint 6"
    assert document.map.waypoints_list.waypoint_paths == [(1, 2), (3, 4)]
    assert value(guard, "uniqueID") == "GondorFighter 0"
    document.stack.undo()
    assert len(document.map.objects_list.object_list) == 3
    assert document.map.waypoints_list.waypoint_paths == [(1, 2)]


def test_a_clipboard_goes_through_text_whole_for_another_editor():
    guard = placed("GondorFighter", 4.0, 6.0, uniqueID="GondorFighter 0", objectName="Guard")
    guard.properties["objectEnabled"] = {
        "name": "objectEnabled",
        "type": AssetPropertyType.Boolean,
        "value": True,
    }
    guard.angle, guard.road_type = 1.25, 2
    start = placed("*Waypoints/Waypoint", 10.0, 0.0, waypointID=1, waypointName="Start")
    end = placed("*Waypoints/Waypoint", 20.0, 0.0, waypointID=2, waypointName="End")
    document = document_with(guard, start, end, links=[(1, 2)])
    clipboard = copy_objects(document.map, [guard, start, end])

    back = clipboard_from_json(clipboard_to_json(clipboard))
    assert back is not None
    assert back.center == clipboard.center and back.links == clipboard.links
    assert back.objects == clipboard.objects
    assert back.objects[0].properties["objectEnabled"]["type"] is AssetPropertyType.Boolean
    assert list(back.objects[0].properties) == list(guard.properties)


def test_text_that_is_not_a_clipboard_reads_as_none():
    for text in ("", "hello", "[]", '{"format": 99}', '{"format": 1, "objects": [{}]}'):
        assert clipboard_from_json(text) is None
