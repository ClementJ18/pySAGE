"""Qt-level tests for the Road tool and Road Options: drawing and joining segments, selecting a
segment, Apply To Selection, whole-segment delete and copy, Show Roads, and drawing. Headless via
the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.height_map import HeightMapBorder, HeightMapData  # noqa: E402
from sage_map.assets.object_list import ObjectsList  # noqa: E402
from sage_map.assets.waypoint_list import WaypointsList  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.roads import (  # noqa: E402
    CORNER_ANGLED,
    ROAD_END,
    ROAD_JOIN,
    ROAD_START,
    CornerType,
    road_segments,
)
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def editable_map():
    width = height = 60
    map = Map()
    map.height_map_data = HeightMapData(
        version=5,
        width=width,
        height=height,
        border_width=0,
        borders=[HeightMapBorder((0, 0), (width, height))],
        area=width * height,
        min_height=0,
        max_height=0,
        elevations=[[0] * width for _ in range(height)],
        start_pos=0,
        end_pos=0,
    )
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    return map


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window.map_view.resize(600, 600)
    window._set_document(MapDocument(editable_map()))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    window.road_panel.set_catalogue(["DirtRoad", "Sidewalk"], ["ArcBridge"], [])
    window.use_tool("road")
    yield window
    window.document = None
    window.close()


def gesture(window, x, y, shift=False):
    screen = QPointF(*window.map_view.transform.world_to_screen(x, y))
    return Gesture((x, y), screen, shift=shift)


def drag(window, points, shift=False):
    view, tool = window.map_view, window.map_view.tool
    tool.press(view, gesture(window, *points[0], shift))
    for point in points[1:]:
        tool.move(view, gesture(window, *point, shift))
    tool.release(view, gesture(window, *points[-1], shift))


def objects(window):
    return window.document.map.objects_list.object_list


def test_a_drag_adds_a_segment_and_an_end_joins_onto_a_road(window):
    assert window.road_panel.choose("DirtRoad")
    drag(window, [(100.0, 100.0), (200.0, 100.0), (300.0, 100.0)])
    start, end = objects(window)
    assert start.road_type == ROAD_START and end.road_type == ROAD_END
    assert (start.position, end.position) == ((100.0, 100.0, 0.0), (300.0, 100.0, 0.0))
    assert window.document.selection.items == (start, end)
    # Pressing 3 world units (under the pick distance) from the end starts on it exactly.
    drag(window, [(303.0, 102.0), (300.0, 200.0), (300.0, 300.0)])
    assert objects(window)[2].position == (300.0, 100.0, 0.0)
    assert len(road_segments(objects(window))) == 2
    window.document.stack.undo()
    assert len(objects(window)) == 2


def test_nothing_is_added_without_a_road_type(window):
    drag(window, [(100.0, 100.0), (300.0, 100.0)])
    assert objects(window) == []


def test_a_bridge_type_adds_a_bridge(window):
    window.road_panel.choose("ArcBridge")
    drag(window, [(100.0, 100.0), (300.0, 100.0)])
    assert window.road_type() == ("ArcBridge", True)
    assert road_segments(objects(window))[0].bridge


def test_click_selects_a_segment_and_apply_to_selection_restyles_it(window):
    window.road_panel.choose("DirtRoad")
    drag(window, [(100.0, 100.0), (300.0, 100.0)])
    window.document.selection.clear()
    drag(window, [(200.0, 104.0)])
    start, end = objects(window)
    assert set(map(id, window.document.selection)) == {id(start), id(end)}
    window.road_panel.choose("Sidewalk")
    window.road_panel.show_style("Sidewalk", CornerType.ANGLED, True)
    window.road_panel.apply_button.click()
    assert start.type_name == end.type_name == "Sidewalk"
    assert start.road_type == ROAD_START | CORNER_ANGLED | ROAD_JOIN
    window.document.stack.undo()
    assert start.road_type == ROAD_START and start.type_name == "DirtRoad"
    drag(window, [(200.0, 400.0)])
    assert not window.document.selection


def test_selecting_one_segment_shows_its_settings(window):
    window.road_panel.choose("Sidewalk")
    window.road_panel.show_style("Sidewalk", CornerType.TIGHT, False)
    drag(window, [(100.0, 100.0), (300.0, 100.0)])
    window.road_panel.choose("DirtRoad")
    window.road_panel.show_style("DirtRoad", CornerType.BROAD, True)
    window.document.selection.set([objects(window)[1]])
    assert window.road_panel.road_type() == ("Sidewalk", False)
    assert window.road_panel.corner() is CornerType.TIGHT
    assert not window.road_panel.join()


def test_delete_cut_and_copy_take_whole_segments(window):
    window.road_panel.choose("DirtRoad")
    drag(window, [(100.0, 100.0), (300.0, 100.0)])
    start, end = objects(window)
    window.document.selection.set([end])
    window.copy()
    window.paste()
    drag(window, [(300.0, 400.0)])
    assert len(road_segments(objects(window))) == 2
    window.document.selection.set([end])
    window.delete_selection()
    assert start not in objects(window) and len(objects(window)) == 2
    window.document.selection.set([objects(window)[0]])
    window.cut()
    assert objects(window) == []


def test_show_roads_hides_roads_from_picking_and_joining(window):
    window.road_panel.choose("DirtRoad")
    drag(window, [(100.0, 100.0), (300.0, 100.0)])
    window.view_actions["show_roads"].trigger()
    assert window.settings.view.show_roads is False
    window.document.selection.clear()
    drag(window, [(200.0, 100.0)])
    assert not window.document.selection
    drag(window, [(303.0, 102.0), (300.0, 300.0)])
    assert objects(window)[2].position == (303.0, 102.0, 0.0)


def test_the_view_draws_roads(window):
    window.road_panel.choose("DirtRoad")
    drag(window, [(100.0, 300.0), (500.0, 300.0)])
    image = window.map_view.grab().toImage()
    x, y = window.map_view.transform.world_to_screen(300.0, 300.0)
    road = image.pixelColor(int(x), int(y))
    x, y = window.map_view.transform.world_to_screen(300.0, 450.0)
    ground = image.pixelColor(int(x), int(y))
    assert road != ground
