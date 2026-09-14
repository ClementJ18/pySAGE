"""Qt-level tests for the Waypoint and Polygon tools, and for selecting, moving, reshaping,
renaming and deleting trigger areas. Headless via 'offscreen'; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import ObjectsList  # noqa: E402
from sage_map.assets.trigger_areas import TriggerAreas  # noqa: E402
from sage_map.assets.waypoint_list import WaypointsList  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    map.trigger_areas = TriggerAreas(version=1, trigger_areas=[], start_pos=0, end_pos=0)
    window._set_document(MapDocument(map))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    yield window
    window.document = None
    window.close()


def gesture(window, x, y):
    return Gesture((x, y), QPointF(*window.map_view.transform.world_to_screen(x, y)))


def drag(window, points):
    view, tool = window.map_view, window.map_view.tool
    tool.press(view, gesture(window, *points[0]))
    for point in points[1:]:
        tool.move(view, gesture(window, *point))
    tool.release(view, gesture(window, *points[-1]))


def test_waypoint_tool_adds_links_and_unlinks(window):
    map = window.document.map
    window.waypoint_tool_action.trigger()
    assert window.map_view.tool is window.waypoint_tool
    drag(window, [(100.0, 100.0)])
    (first,) = map.objects_list.object_list
    assert first.properties["waypointName"]["value"] == "Waypoint 1"
    assert window.document.selection.items == (first,)

    drag(window, [(100.0, 100.0), (200.0, 150.0), (300.0, 100.0)])
    second = map.objects_list.object_list[-1]
    assert second.position == (300.0, 100.0, 0.0)
    assert map.waypoints_list.waypoint_paths == [(1, 2)]
    assert window.document.stack.undo_label == "Add Waypoint"

    drag(window, [(300.0, 100.0), (200.0, 100.0), (100.0, 100.0)])
    assert map.waypoints_list.waypoint_paths == []
    drag(window, [(100.0, 100.0), (200.0, 100.0), (300.0, 100.0)])
    assert map.waypoints_list.waypoint_paths == [(1, 2)]

    drag(window, [(101.0, 99.0)])
    assert window.document.selection.items == (first,)
    assert len(map.objects_list.object_list) == 2


def test_polygon_tool_closes_on_the_first_corner_and_cancels_on_switch(window):
    map = window.document.map
    window.polygon_tool_action.trigger()
    for point in [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0)]:
        drag(window, [point])
    assert window.polygon_tool.points == [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0)]
    drag(window, [(101.0, 101.0)])
    (area,) = map.trigger_areas.trigger_areas
    assert area.name == "Area 1" and area.area_id == 1
    assert area.points == [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0)]
    assert window.document.selection.items == (area,)
    assert window.polygon_tool.points == []

    drag(window, [(400.0, 400.0)])
    assert window.polygon_tool.points == [(400.0, 400.0)]
    window.select_tool_action.trigger()
    assert window.polygon_tool.points == []


def test_select_moves_reshapes_renames_and_deletes_areas(window):
    map = window.document.map
    window.polygon_tool_action.trigger()
    for point in [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 100.0)]:
        drag(window, [point])
    (area,) = map.trigger_areas.trigger_areas
    window.select_tool_action.trigger()
    selection = window.document.selection

    drag(window, [(500.0, 500.0)])
    assert not selection
    drag(window, [(250.0, 150.0)])
    assert selection.items == (area,)

    drag(window, [(250.0, 150.0), (260.0, 150.0), (270.0, 160.0)])
    assert area.points == [(120.0, 110.0), (320.0, 110.0), (320.0, 310.0)]

    drag(window, [(320.0, 310.0), (330.0, 330.0), (350.0, 350.0)])
    assert area.points[2] == (350.0, 350.0)
    window.document.stack.undo()
    assert area.points[2] == (320.0, 310.0)

    panel = window.object_panel
    assert panel.tabs.currentWidget() is panel.area_tab
    panel.area_name.setText("Village")
    panel.area_name.editingFinished.emit()
    assert area.name == "Village"

    drag(window, [(50.0, 50.0), (400.0, 400.0)])
    assert selection.items == (area,)
    window.delete_action.trigger()
    assert map.trigger_areas.trigger_areas == []
    window.document.stack.undo()
    assert map.trigger_areas.trigger_areas == [area]


def test_areas_and_waypoints_the_view_hides_cannot_be_picked(window):
    map = window.document.map
    window.polygon_tool_action.trigger()
    for point in [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 100.0)]:
        drag(window, [point])
    (area,) = map.trigger_areas.trigger_areas
    window.waypoint_tool_action.trigger()
    drag(window, [(250.0, 150.0)])
    (waypoint,) = map.objects_list.object_list
    window.select_tool_action.trigger()
    selection = window.document.selection
    options = window.map_view.options

    options.show_waypoints = False
    drag(window, [(250.0, 150.0)])
    assert selection.items == (area,)

    options.show_areas = False
    selection.clear()
    drag(window, [(260.0, 150.0)])
    assert not selection
    drag(window, [(300.0, 300.0), (350.0, 350.0)])
    assert area.points[2] == (300.0, 300.0)
    drag(window, [(50.0, 50.0), (400.0, 400.0)])
    assert not selection

    options.show_waypoints = True
    drag(window, [(250.0, 150.0)])
    assert selection.items == (waypoint,)

    options.show_waypoints = False
    window.waypoint_tool_action.trigger()
    drag(window, [(250.0, 150.0)])
    assert len(map.objects_list.object_list) == 2
