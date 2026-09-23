"""Qt-level tests for the Move and Rotate tools: the gizmo's hit areas, a drag held to one axis,
X/Y/Z switching the axis mid-drag, the rotate ring, Lock Angle, falling through to Select and
Move when the press misses the gizmo, and the level plane the gizmo stands on in 3D. Headless via
'offscreen'; marked `full`."""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

import numpy as np  # noqa: E402
from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.camera.projection import CameraProjection  # noqa: E402
from sage_worldbuilder.camera.view import Camera  # noqa: E402
from sage_worldbuilder.gizmos import GIZMO_PIXELS, Axis, reach  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.grid import TerrainGrid  # noqa: E402
from sage_worldbuilder.terrain.surface import ground_height  # noqa: E402
from sage_worldbuilder.ui import gizmo_tools  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402
from sage_worldbuilder.viewport import GridSettings, ViewOptions  # noqa: E402

TREE = (100.0, 100.0)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def placed(type_name, x, y):
    stored = {
        "uniqueID": {
            "name": "uniqueID",
            "type": AssetPropertyType.AsciiString,
            "value": f"{type_name} 0",
        }
    }
    return Object(3, (x, y, 0.0), 0.0, 0, type_name, stored, 0, 0)


def editable_map():
    map = Map()
    map.objects_list = ObjectsList(
        version=3,
        object_list=[placed("Tree", *TREE), placed("Rock", 300.0, 100.0)],
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
    settings = Settings(install=str(install), view=ViewOptions(view_3d=False))
    window = MainWindow(settings, load_game_data=False)
    window.map_view.resize(600, 600)
    window._set_document(MapDocument(editable_map()))
    window.map_view.transform.width = window.map_view.transform.height = 600
    # One pixel to one world unit, so a gizmo's pixels are world units too.
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    yield window
    window.document = None
    window.close()


def objects(window):
    return window.document.map.objects_list.object_list


def gesture(window, x, y, **flags):
    return Gesture((x, y), QPointF(*window.map_view.transform.world_to_screen(x, y)), **flags)


def at_screen(window, world, dx, dy):
    """A gesture at a pixel offset from a world point, for the handles drawn in screen space."""
    sx, sy = window.map_view.transform.world_to_screen(*world)
    screen = QPointF(sx + dx, sy + dy)
    return Gesture(window.map_view.transform.screen_to_world(screen.x(), screen.y()), screen)


def select(window, obj):
    window.document.selection.set([obj])


def test_the_move_gizmo_holds_a_drag_to_the_axis_that_was_grabbed(window):
    tree, rock = objects(window)
    select(window, tree)
    window.use_tool("move")
    tool, view = window.move_tool, window.map_view
    # Halfway along the X arrow, then a drag that goes up as well as along.
    assert tool.press(view, gesture(window, 140.0, 100.0))
    tool.move(view, gesture(window, 160.0, 160.0))
    tool.release(view, gesture(window, 160.0, 160.0))
    assert tree.position == (120.0, 100.0, 0.0)
    assert rock.position == (300.0, 100.0, 0.0)
    assert window.document.stack.undo_label == "Move"
    window.document.stack.undo()
    assert tree.position == (100.0, 100.0, 0.0)
    assert not window.document.stack.can_undo


def test_the_y_arrow_moves_only_along_y_and_the_centre_knob_moves_freely(window):
    tree, _rock = objects(window)
    select(window, tree)
    window.use_tool("move")
    tool, view = window.move_tool, window.map_view
    assert tool.press(view, gesture(window, 100.0, 140.0))
    tool.move(view, gesture(window, 160.0, 170.0))
    tool.release(view, gesture(window, 160.0, 170.0))
    assert tree.position == (100.0, 130.0, 0.0)

    assert tool.press(view, gesture(window, *tree.position[:2]))
    tool.move(view, gesture(window, 120.0, 150.0))
    tool.release(view, gesture(window, 120.0, 150.0))
    assert tree.position == (120.0, 150.0, 0.0)


def test_the_z_arrow_raises_and_lowers(window):
    tree, _rock = objects(window)
    select(window, tree)
    window.use_tool("move")
    tool, view = window.move_tool, window.map_view
    # Looking down, the height arrow leans up and left, clear of the Y arrow straight up.
    ux, uy = view.transform.height_direction(*TREE)
    assert (ux, uy) == pytest.approx((-math.sqrt(0.5), -math.sqrt(0.5)))
    grab = at_screen(window, TREE, ux * GIZMO_PIXELS / 2, uy * GIZMO_PIXELS / 2)
    along = at_screen(window, TREE, ux * (GIZMO_PIXELS / 2 + 30.0), uy * (GIZMO_PIXELS / 2 + 30.0))
    assert tool.press(view, grab)
    tool.move(view, along)
    tool.release(view, along)
    assert tree.position[:2] == TREE
    assert tree.position[2] == pytest.approx(30.0)


def test_x_y_and_z_switch_the_axis_during_the_drag(window):
    tree, _rock = objects(window)
    select(window, tree)
    window.use_tool("move")
    tool, view = window.move_tool, window.map_view
    tool.press(view, gesture(window, 140.0, 100.0))
    tool.move(view, gesture(window, 160.0, 160.0))
    assert tree.position == (120.0, 100.0, 0.0)
    assert tool.key(view, Qt.Key.Key_Y.value)
    tool.move(view, gesture(window, 160.0, 160.0))
    assert tree.position == (100.0, 160.0, 0.0)
    # The axis in use frees the move again, as a second press of it does in Blender.
    assert tool.key(view, Qt.Key.Key_Y.value)
    tool.move(view, gesture(window, 160.0, 160.0))
    assert tree.position == (120.0, 160.0, 0.0)
    tool.release(view, gesture(window, 160.0, 160.0))
    assert tool.key(view, Qt.Key.Key_X.value) is False


def test_a_move_along_an_axis_still_snaps_to_the_grid(window):
    tree, _rock = objects(window)
    select(window, tree)
    window.settings.view.grid = GridSettings(spacing=50.0, snap=True)
    window.use_tool("move")
    tool, view = window.move_tool, window.map_view
    tool.press(view, gesture(window, 140.0, 100.0))
    tool.move(view, gesture(window, 187.0, 130.0))
    tool.release(view, gesture(window, 187.0, 130.0))
    assert tree.position == (150.0, 100.0, 0.0)


def test_a_press_that_misses_the_gizmo_selects_as_select_and_move_does(window):
    tree, rock = objects(window)
    select(window, tree)
    window.use_tool("move")
    tool, view = window.move_tool, window.map_view
    tool.press(view, gesture(window, 300.0, 100.0))
    tool.release(view, gesture(window, 300.0, 100.0))
    assert window.document.selection.items == (rock,)
    assert tree.position == (100.0, 100.0, 0.0)


def test_the_rotate_ring_turns_the_selection_in_one_undo_entry(window):
    tree, _rock = objects(window)
    select(window, tree)
    window.use_tool("rotate")
    tool, view = window.rotate_tool, window.map_view
    # The ring sits GIZMO_PIXELS from the centre, here the same in world units.
    assert tool.press(view, gesture(window, TREE[0] + GIZMO_PIXELS, TREE[1]))
    tool.move(view, gesture(window, TREE[0] + 50.0, TREE[1] + 50.0))
    tool.move(view, gesture(window, TREE[0], TREE[1] + GIZMO_PIXELS))
    tool.release(view, gesture(window, TREE[0], TREE[1] + GIZMO_PIXELS))
    assert tree.angle == pytest.approx(math.pi / 2)
    assert tree.position == (100.0, 100.0, 0.0)
    assert window.document.stack.undo_label == "Rotate"
    window.document.stack.undo()
    assert tree.angle == 0.0
    assert not window.document.stack.can_undo


def test_lock_angle_holds_a_turn_to_the_eight_headings(window):
    tree, _rock = objects(window)
    select(window, tree)
    window.lock_angle_action.setChecked(True)
    window.use_tool("rotate")
    tool, view = window.rotate_tool, window.map_view
    tool.press(view, gesture(window, TREE[0] + GIZMO_PIXELS, TREE[1]))
    # 50 degrees round the ring snaps to the 45-degree heading.
    angle = math.radians(50.0)
    point = (TREE[0] + GIZMO_PIXELS * math.cos(angle), TREE[1] + GIZMO_PIXELS * math.sin(angle))
    tool.move(view, gesture(window, *point))
    tool.release(view, gesture(window, *point))
    assert tree.angle == pytest.approx(math.pi / 4)


def test_the_rotate_gizmo_is_missed_away_from_its_ring(window):
    tree, _rock = objects(window)
    select(window, tree)
    window.use_tool("rotate")
    tool, view = window.rotate_tool, window.map_view
    # Well inside the ring: the press falls through to selecting instead of turning.
    tool.press(view, gesture(window, TREE[0] + GIZMO_PIXELS / 2, TREE[1]))
    tool.move(view, gesture(window, TREE[0], TREE[1] + GIZMO_PIXELS))
    tool.release(view, gesture(window, TREE[0], TREE[1] + GIZMO_PIXELS))
    assert tree.angle == 0.0


def test_the_gizmo_highlights_the_axis_under_the_cursor(window):
    tree, _rock = objects(window)
    select(window, tree)
    window.use_tool("move")
    tool, view = window.move_tool, window.map_view
    tool.hover(view, gesture(window, 140.0, 100.0))
    assert tool._hot is Axis.X
    tool.hover(view, gesture(window, 400.0, 400.0))
    assert tool._hot is None


class _Sloped:
    """The least of a `ToolView` a gizmo asks about: a 3D projection over sloping ground."""

    def __init__(self, document):
        heights = np.arange(41)[None, :] * 256 + np.zeros((41, 1), dtype=np.int64)
        grid = TerrainGrid(heights.astype(np.uint16), 0)
        camera = Camera(width=800, height=600, pitch=45, distance=900)
        camera.target_x = camera.target_y = 200.0
        camera.target_z = ground_height(grid, 200.0, 200.0)
        self.transform = CameraProjection(camera, grid)
        self.document = document
        self.options = ViewOptions()

    def update(self):
        return None


def test_the_gizmo_stands_on_a_level_plane_over_sloping_ground(window, qapp):
    tree, _rock = objects(window)
    tree.position = (200.0, 200.0, 0.0)
    select(window, tree)
    view = _Sloped(window.document)
    center = (200.0, 200.0)
    plane = view.transform.ground(*center)
    scale = view.transform.scale_at(*center)
    out = reach(GIZMO_PIXELS, scale)

    # Every point of the ring as drawn is projected from the one height, not from the ground
    # under it, which rises steadily to the east.
    ring = gizmo_tools._ring(view, center, scale)
    for step, point in enumerate(ring):
        x = center[0] + out * math.cos(step * math.tau / gizmo_tools._RING_STEPS)
        y = center[1] + out * math.sin(step * math.tau / gizmo_tools._RING_STEPS)
        assert point == pytest.approx(view.transform.plane_to_screen(x, y, plane))
    assert view.transform.ground(center[0] + out, center[1]) != pytest.approx(plane)

    # And a press at the ring where it is drawn grabs it.
    east = QPointF(*view.transform.plane_to_screen(center[0] + out, center[1], plane))
    grabbed = window.rotate_tool._grab(view, center, Gesture(center, east))
    assert grabbed is Axis.Z

    # The X arrow's tip is on the same plane, not up the slope.
    tail, tip = window.move_tool._segment(view, center, Axis.X, scale)
    assert tail == pytest.approx(view.transform.plane_to_screen(*center, plane))
    assert tip == pytest.approx(view.transform.plane_to_screen(center[0] + out, center[1], plane))
