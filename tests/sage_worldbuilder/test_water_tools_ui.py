"""Qt-level tests for the water tools and Water Options: drawing lakes, rivers and wave areas,
choosing, moving and reshaping them, the panel's edits, Delete, Show Water, and drawing. Headless
via the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication, QCheckBox, QLineEdit  # noqa: E402

from sage_map.assets.environment_data import EnvironmentData  # noqa: E402
from sage_map.assets.height_map import HeightMapBorder, HeightMapData  # noqa: E402
from sage_map.assets.object_list import ObjectsList  # noqa: E402
from sage_map.assets.river_areas import RiverAreas  # noqa: E402
from sage_map.assets.standing_water_area import StandingWaterAreas  # noqa: E402
from sage_map.assets.standing_waves_area import StandingWaveAreas  # noqa: E402
from sage_map.assets.waypoint_list import WaypointsList  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402
from sage_worldbuilder.water import NEW_NAMES, WaterKind  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def water_map():
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
        # 2,560 stored units is 100 ft.
        elevations=[[2560] * width for _ in range(height)],
        start_pos=0,
        end_pos=0,
    )
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    map.standing_water_areas = StandingWaterAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.river_areas = RiverAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.standing_wave_areas = StandingWaveAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.environment_data = EnvironmentData(
        version=3,
        water_max_alpha_depth=3.0,
        deep_water_alpha=1.0,
        is_macro_texture_stretched=False,
        macro_texture="",
        cloud_texture="",
        unknown_texture=None,
        unknown_texture2=None,
        start_pos=0,
        end_pos=0,
    )
    return map


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window.map_view.resize(600, 600)
    window._set_document(MapDocument(water_map()))
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


def lakes(window):
    return window.document.map.standing_water_areas.areas


def draw_lake(window, corners=((100.0, 100.0), (300.0, 100.0), (300.0, 300.0))):
    window.use_tool("lake")
    for corner in (*corners, corners[0]):
        drag(window, [corner])


def test_the_lake_tool_closes_an_outline_into_a_lake(window):
    draw_lake(window)
    (lake,) = lakes(window)
    assert lake.name == NEW_NAMES[WaterKind.LAKE]
    assert lake.points == [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0)]
    assert lake.water_height == 100
    assert window.document.selection.items == (lake,)
    assert window.water_panel.area is lake and window.water_dock.isVisibleTo(window)
    window.document.stack.undo()
    assert lakes(window) == []


def test_choose_move_and_reshape_a_lake_one_undo_entry_each(window):
    draw_lake(window)
    (lake,) = lakes(window)
    window.document.selection.clear()
    drag(window, [(250.0, 150.0)])
    assert window.document.selection.items == (lake,)
    drag(window, [(250.0, 150.0), (260.0, 150.0), (270.0, 160.0)])
    assert lake.points[0] == (120.0, 110.0)
    drag(window, [(120.0, 110.0), (90.0, 90.0)])
    assert lake.points[0] == (90.0, 90.0)
    stack = window.document.stack
    stack.undo()
    assert lake.points[0] == (120.0, 110.0)
    stack.undo()
    assert lake.points[0] == (100.0, 100.0)


def test_the_river_tool_adds_bank_lines_and_starts_new_rivers(window):
    window.use_tool("river")
    drag(window, [(100.0, 100.0), (100.0, 160.0)])
    drag(window, [(200.0, 100.0), (200.0, 160.0)])
    rivers = window.document.map.river_areas.areas
    (river,) = rivers
    assert river.lines == [((100.0, 100.0), (100.0, 160.0)), ((200.0, 100.0), (200.0, 160.0))]
    assert window.water_panel.kind is WaterKind.RIVER
    drag(window, [(500.0, 500.0)])
    assert not window.document.selection
    drag(window, [(400.0, 400.0), (400.0, 460.0)])
    assert len(rivers) == 2
    window.document.stack.undo()
    assert len(rivers) == 1
    window.document.stack.undo()
    assert len(river.lines) == 1


def test_the_waves_tool_adds_a_line_that_a_click_chooses(window):
    window.use_tool("waves")
    drag(window, [(100.0, 400.0), (300.0, 400.0)])
    (wave,) = window.document.map.standing_wave_areas.areas
    assert wave.points == [(100.0, 400.0), (300.0, 400.0)]
    window.document.selection.clear()
    drag(window, [(200.0, 403.0)])
    assert window.document.selection.items == (wave,)


def test_the_panel_edits_the_chosen_area_and_the_map_options(window):
    draw_lake(window)
    (lake,) = lakes(window)
    panel = window.water_panel
    name = panel._editors["name"]
    assert isinstance(name, QLineEdit)
    name.setText("Moat")
    name.editingFinished.emit()
    assert lake.name == "Moat"
    blending = panel._editors["use_adaptive_blending"]
    assert isinstance(blending, QCheckBox)
    blending.setChecked(True)
    assert lake.use_adaptive_blending is True
    panel.alpha_depth.setValue(8.0)
    assert window.document.map.environment_data.water_max_alpha_depth == 8.0
    stack = window.document.stack
    stack.undo()
    assert window.document.map.environment_data.water_max_alpha_depth == 3.0
    stack.undo()
    stack.undo()
    assert lake.name == NEW_NAMES[WaterKind.LAKE] and lake.use_adaptive_blending is False


def test_delete_removes_the_chosen_area(window):
    draw_lake(window)
    window.delete_selection()
    assert lakes(window) == []
    assert window.water_panel.area is None


def test_hidden_water_is_not_chosen(window):
    draw_lake(window)
    window.view_actions["show_water"].trigger()
    window.document.selection.clear()
    window.use_tool("lake")
    drag(window, [(250.0, 150.0)])
    assert not window.document.selection


def test_the_view_draws_a_lake(window):
    draw_lake(window)
    window.document.selection.clear()
    # Choosing the tool shows its panel, so the view's grab is laid out anew and no longer the
    # size the test set: compare whole pictures rather than one pixel.
    shown = window.map_view.grab().toImage()
    window.view_actions["show_water"].trigger()
    hidden = window.map_view.grab().toImage()
    assert shown.size() == hidden.size()
    assert shown != hidden
