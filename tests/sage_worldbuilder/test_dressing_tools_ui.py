"""Qt-level tests for the world dressing tools and Dressing Options: scorch marks, groves, fences,
ramps, borders and mesh molds, each gesture one undo entry. Headless via the Qt 'offscreen'
platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.height_map import HeightMapBorder, HeightMapData  # noqa: E402
from sage_map.assets.object_list import ObjectsList  # noqa: E402
from sage_map.assets.river_areas import RiverAreas  # noqa: E402
from sage_map.assets.standing_water_area import StandingWaterAreas  # noqa: E402
from sage_map.assets.standing_waves_area import StandingWaveAreas  # noqa: E402
from sage_map.assets.waypoint_list import WaypointsList  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.dressing import MoldMode  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402

SIZE = 60


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def dressing_map():
    map = Map()
    map.height_map_data = HeightMapData(
        version=5,
        width=SIZE,
        height=SIZE,
        border_width=0,
        borders=[HeightMapBorder((0, 0), (SIZE, SIZE))],
        area=SIZE * SIZE,
        min_height=0,
        max_height=0,
        # Heights rise by one 2560-unit step every 20 columns: 100, 200 and 300 ft.
        elevations=[[2560 * (1 + column // 20) for column in range(SIZE)] for _ in range(SIZE)],
        start_pos=0,
        end_pos=0,
    )
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    map.standing_water_areas = StandingWaterAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.river_areas = RiverAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.standing_wave_areas = StandingWaveAreas(version=2, areas=[], start_pos=0, end_pos=0)
    return map


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window.map_view.resize(600, 600)
    window._set_document(MapDocument(dressing_map()))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    yield window
    window.document = None
    window.close()


def use(window, name):
    window.use_tool(name)
    # Showing the panel can lay the hidden view out anew: keep the test's transform.
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)


def gesture(window, x, y, shift=False, alt=False):
    screen = QPointF(*window.map_view.transform.world_to_screen(x, y))
    return Gesture((x, y), screen, shift=shift, alt=alt)


def drag(window, points, shift=False, alt=False):
    view, tool = window.map_view, window.map_view.tool
    tool.press(view, gesture(window, *points[0], shift, alt))
    for point in points[1:]:
        tool.move(view, gesture(window, *point, shift, alt))
    tool.release(view, gesture(window, *points[-1], shift, alt))


def objects(window):
    return window.document.map.objects_list.object_list


def test_the_tools_show_their_page(window):
    use(window, "grove")
    assert "Grove" in window.dressing_panel.title.text()
    assert window.dressing_dock.isVisibleTo(window)
    use(window, "mesh mold")
    assert "Mesh Mold" in window.dressing_panel.title.text()


def test_scorch_marks_are_clicked_or_dragged_to_size(window):
    use(window, "scorch")
    window.dressing_panel.scorch_type.setCurrentIndex(2)
    drag(window, [(100.0, 100.0)])
    drag(window, [(300.0, 300.0), (330.0, 300.0)])
    first, second = objects(window)
    assert first.type_name == "Scorch" and first.properties["scorchType"]["value"] == 2
    assert first.properties["objectRadius"]["value"] == 20.0
    assert second.properties["objectRadius"]["value"] == pytest.approx(30.0)
    assert window.document.selection.items == (second,)
    window.document.stack.undo()
    assert objects(window) == [first]


def test_a_grove_is_dragged_as_a_rectangle_or_clicked_as_a_cluster(window):
    use(window, "grove")
    panel = window.dressing_panel
    drag(window, [(100.0, 100.0), (300.0, 300.0)])
    assert objects(window) == []
    panel.set_grove_trees([("Oak", 60), ("Pine", 40)])
    panel.grove_count.setValue(12)
    # The points are random and the map steps up at x = 200: let trees stand on the step.
    panel.grove_cliffs.setChecked(True)
    drag(window, [(100.0, 100.0), (300.0, 300.0)])
    trees = list(objects(window))
    assert len(trees) == 12 and {tree.type_name for tree in trees} <= {"Oak", "Pine"}
    assert all(100 <= t.position[0] <= 300 and 100 <= t.position[1] <= 300 for t in trees)
    assert len(window.document.selection) == 12
    drag(window, [(450.0, 450.0)])
    assert len(objects(window)) == 24
    stack = window.document.stack
    stack.undo()
    stack.undo()
    assert objects(window) == []


def test_a_fence_follows_the_drag_and_stretches_with_shift(window):
    window.palette_panel.template = lambda: "Fence01"
    use(window, "fence")
    assert window.dressing_panel.fence_object.text() == "Fence01"
    window.dressing_panel.fence_spacing_box.setValue(30.0)
    drag(window, [(100.0, 100.0), (200.0, 100.0)])
    assert [post.position[0] for post in objects(window)] == [100.0, 130.0, 160.0, 190.0]
    drag(window, [(100.0, 300.0), (200.0, 300.0)], shift=True)
    stretched = objects(window)[4:]
    assert len(stretched) == 4 and stretched[-1].position[0] == pytest.approx(200.0)


def test_a_ramp_slopes_the_ground_between_its_ends(window):
    use(window, "ramp")
    grid = window.document.terrain
    before = np.array(grid.heights)
    drag(window, [(100.0, 300.0), (500.0, 300.0)])
    after = window.document.terrain.heights
    row = 30
    assert after[row, 10] == before[row, 10] and after[row, 50] == before[row, 50]
    assert before[row, 10] < after[row, 30] < before[row, 50]
    assert (after[row + 5] == before[row + 5]).all()
    window.document.stack.undo()
    assert (window.document.terrain.heights == before).all()


def test_borders_are_added_resized_and_removed(window):
    use(window, "border")
    borders = window.document.map.height_map_data.borders
    drag(window, [(200.0, 150.0)])
    assert borders[-1].position == (20, 15)
    drag(window, [(200.0, 150.0), (250.0, 200.0), (300.0, 250.0)])
    assert borders[-1].position == (30, 25)
    window.document.stack.undo()
    assert borders[-1].position == (20, 15)
    drag(window, [(200.0, 150.0)], alt=True)
    assert len(borders) == 1
    drag(window, [(600.0, 600.0)], alt=True)
    assert len(borders) == 1


def test_a_mesh_mold_shapes_the_ground_where_it_is_placed(window):
    top = 400.0
    square = np.array(
        [
            [[-40.0, -40.0, top], [40.0, -40.0, top], [40.0, 40.0, top]],
            [[-40.0, -40.0, top], [40.0, 40.0, top], [-40.0, 40.0, top]],
        ]
    )
    window.mold_mesh = lambda name: square
    use(window, "mesh mold")
    window.dressing_panel.set_molds(["box.w3d"])
    window.apply_mesh_mold()
    assert not window.document.stack.can_undo
    drag(window, [(300.0, 300.0)])
    before = np.array(window.document.terrain.heights)
    window.apply_mesh_mold()
    after = window.document.terrain.heights
    assert after[30, 30] == round(top / FEET_PER_HEIGHT_UNIT)
    assert after[30, 36] == before[30, 36]
    window.document.stack.undo()
    button = window.dressing_panel._mold_mode_buttons[MoldMode.LOWER]
    button.setChecked(True)
    window.apply_mesh_mold()
    assert (window.document.terrain.heights == before).all()
