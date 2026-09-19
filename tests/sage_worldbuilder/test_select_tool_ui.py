"""Qt-level tests for Select and Move: picking, Shift, marquee, dragging and rotating (one undo
entry a gesture), grid snap, the locks, pick allowances, and Cut / Copy / Paste / Delete.
Headless via the Qt 'offscreen' platform; marked `full`."""

import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QByteArray, QMimeData, QPointF, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.height_map import HeightMapBorder, HeightMapData  # noqa: E402
from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.assets.waypoint_list import WaypointsList  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.gizmos import HANDLE_PIXELS, front_tip  # noqa: E402
from sage_worldbuilder.objects import (  # noqa: E402
    CLIPBOARD_MIME,
    Clipboard,
    GroupEditMethod,
    clipboard_to_json,
)
from sage_worldbuilder.pick import PickCategory  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402
from sage_worldbuilder.viewport import GridSettings, ViewOptions  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def placed(type_name, x, y, **properties):
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
    return Object(3, (x, y, 0.0), 0.0, 0, type_name, stored, 0, 0)


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
    map.objects_list = ObjectsList(
        version=3,
        object_list=[
            placed("Tree", 100.0, 100.0, uniqueID="Tree 0"),
            placed("Rock", 300.0, 100.0, uniqueID="Rock 1"),
            placed("*Waypoints/Waypoint", 300.0, 300.0, waypointID=1, waypointName="Start"),
        ],
        start_pos=0,
        end_pos=0,
    )
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    return map


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    # The top-down view, which these place and pick through.
    settings = Settings(install=str(install), view=ViewOptions(view_3d=False))
    window = MainWindow(settings, load_game_data=False)
    window.map_view.resize(600, 600)
    window._set_document(MapDocument(editable_map()))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    yield window
    window.document = None
    window.close()


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


def test_click_shift_click_and_click_away(window):
    tree, rock, _waypoint = objects(window)
    selection = window.document.selection
    drag(window, [(102.0, 101.0)])
    assert selection.items == (tree,)
    drag(window, [(300.0, 100.0)], shift=True)
    assert selection.items == (tree, rock)
    drag(window, [(100.0, 100.0)], shift=True)
    assert selection.items == (rock,)
    drag(window, [(500.0, 500.0)])
    assert not selection
    assert window.document.stack.can_undo is False


def test_marquee_selects_inside_and_respects_pick_allowances(window):
    tree, rock, waypoint = objects(window)
    selection = window.document.selection
    sorted_as = lambda name: SimpleNamespace(EditorSorting=[SimpleNamespace(name=name)])  # noqa: E731
    window.context.game = SimpleNamespace(
        objects={"Tree": sorted_as("SHRUBBERY"), "Rock": sorted_as("MISC_NATURAL")}
    )
    drag(window, [(50.0, 50.0), (350.0, 350.0)])
    assert set(map(id, selection.items)) == {id(tree), id(rock), id(waypoint)}
    window._set_allowances(frozenset({PickCategory.WAYPOINTS_AREAS}))
    assert window.settings.pick_allowances == frozenset({PickCategory.WAYPOINTS_AREAS})
    drag(window, [(50.0, 50.0), (350.0, 350.0)])
    assert selection.items == (waypoint,)
    window.pick_nothing_action.trigger()
    drag(window, [(300.0, 300.0)])
    assert not selection


class TurnedTransform:
    """A view whose picture is turned 45 degrees, as the 3D view's camera usually is: world
    `(x, y)` lands at pixel `(x - y, -(x + y))`. Its scale is one pixel a world unit."""

    scale = 1.0

    def scale_at(self, x, y):
        return self.scale

    def world_to_screen(self, x, y):
        return x - y, -(x + y)

    def screen_to_world(self, sx, sy):
        return (sx - sy) / 2, (-sy - sx) / 2


def test_marquee_catches_what_the_rectangle_covers_in_a_turned_view(window):
    tree, rock, waypoint = objects(window)
    view, tool = window.map_view, window.map_view.tool
    original = view.transform
    view.transform = TurnedTransform()
    try:
        # A rectangle around all three on screen; the world rectangle through its two dragged
        # corners is x 50..450, y 100..200, which leaves the waypoint at (300, 300) out.
        corners = [QPointF(-50.0, -150.0), QPointF(250.0, -650.0), QPointF(250.0, -650.0)]
        for point, step in zip(corners, (tool.press, tool.move, tool.release), strict=True):
            step(view, Gesture(view.transform.screen_to_world(point.x(), point.y()), point))
        assert set(map(id, window.document.selection.items)) == {id(tree), id(rock), id(waypoint)}
    finally:
        view.transform = original


def test_each_drag_is_one_undo_entry(window):
    tree, rock, _waypoint = objects(window)
    drag(window, [(100.0, 100.0), (110.0, 100.0), (120.0, 105.0), (130.0, 110.0)])
    assert tree.position == (130.0, 110.0, 0.0)
    assert rock.position == (300.0, 100.0, 0.0)
    drag(window, [(130.0, 110.0), (140.0, 110.0)])
    stack = window.document.stack
    stack.undo()
    assert tree.position == (130.0, 110.0, 0.0)
    stack.undo()
    assert tree.position == (100.0, 100.0, 0.0)
    assert not stack.can_undo


def test_the_front_handle_of_a_selected_object_turns_it(window):
    tree, rock, _waypoint = objects(window)
    selection = window.document.selection
    selection.set([tree])
    # One pixel to one world unit here, so the handle ends HANDLE_PIXELS along the tree's facing.
    tip = front_tip(tree.position[0], tree.position[1], tree.angle, 1.0)
    assert tip == pytest.approx((100.0 + HANDLE_PIXELS, 100.0))
    drag(window, [tip, (120.0, 120.0), (100.0, 100.0 + HANDLE_PIXELS)])
    assert tree.angle == pytest.approx(math.pi / 2)
    assert tree.position == (100.0, 100.0, 0.0)
    assert rock.angle == 0.0
    assert selection.items == (tree,)
    stack = window.document.stack
    stack.undo()
    assert tree.angle == 0.0
    assert not stack.can_undo


def test_the_handle_belongs_to_the_selection_only(window):
    tree, _rock, _waypoint = objects(window)
    # Nothing selected: the same gesture is an ordinary marquee, and nothing turns.
    drag(window, [front_tip(100.0, 100.0, 0.0, 1.0), (100.0, 120.0)])
    assert tree.angle == 0.0
    assert not window.document.stack.can_undo
    assert window.document.selection.items == (tree,)


def test_drag_snaps_to_the_grid_and_lock_angle_keeps_to_45_degrees(window):
    tree, _rock, _waypoint = objects(window)
    window.settings.view.grid = GridSettings(spacing=50.0, snap=True)
    drag(window, [(100.0, 100.0), (137.0, 88.0)])
    assert tree.position == (150.0, 100.0, 0.0)
    window.settings.view.grid = GridSettings(spacing=50.0, snap=False)
    window.lock_angle_action.setChecked(True)
    drag(window, [(150.0, 100.0), (190.0, 138.0)])
    x, y, _ = tree.position
    assert x - 150.0 == pytest.approx(y - 100.0)


def test_alt_drag_rotates_the_selection(window):
    tree, rock, _waypoint = objects(window)
    window.document.selection.set([tree, rock])
    window._set_group_edit(GroupEditMethod.INDEPENDENT)
    # The selection's centre is (200, 100): a quarter turn about it.
    drag(window, [(250.0, 100.0), (200.0, 150.0)], alt=True)
    assert tree.angle == pytest.approx(math.pi / 2)
    assert rock.angle == pytest.approx(math.pi / 2)
    assert tree.position == (100.0, 100.0, 0.0)
    window.document.stack.undo()
    assert tree.angle == 0.0


def test_lock_selection_keeps_the_selection(window):
    tree, rock, _waypoint = objects(window)
    window.document.selection.set([tree])
    window.lock_selection_action.trigger()
    drag(window, [(300.0, 100.0)])
    drag(window, [(500.0, 500.0), (550.0, 550.0)])
    assert window.document.selection.items == (tree,)


def test_copy_paste_cut_and_delete(window):
    QApplication.clipboard().clear()
    tree, rock, _waypoint = objects(window)
    window.document.selection.set([tree])
    window._refresh()
    assert window.copy_action.isEnabled() and not window.paste_action.isEnabled()
    window.copy_action.trigger()
    assert window.paste_action.isEnabled()
    window.map_view.cursor_world = (400.0, 400.0)
    window.paste_action.trigger()
    # The copy follows the cursor, not on the map until a click puts it down.
    assert window.map_view.tool is window.paste_tool
    count = len(objects(window))
    (ghost,) = window.paste_tool.ghosts()
    assert ghost.position == (400.0, 400.0, 0.0) and ghost not in objects(window)
    window.paste_tool.hover(window.map_view, gesture(window, 450.0, 420.0))
    assert window.paste_tool.ghosts()[0].position == (450.0, 420.0, 0.0)
    drag(window, [(450.0, 420.0)])
    pasted = objects(window)[-1]
    assert len(objects(window)) == count + 1
    assert pasted.position == (450.0, 420.0, 0.0)
    assert pasted.properties["uniqueID"]["value"] == "Tree 2"
    assert window.document.selection.items == (pasted,)
    assert window.map_view.tool is window.select_tool

    window.document.selection.set([rock])
    window.cut_action.trigger()
    assert rock not in objects(window)
    window.paste_action.trigger()
    drag(window, [(300.0, 100.0)])
    assert objects(window)[-1].type_name == "Rock"

    window.document.selection.set([tree])
    window.delete_action.trigger()
    assert tree not in objects(window)
    assert not window.document.selection
    window.document.stack.undo()
    assert tree in objects(window)


def test_escape_gives_a_paste_up_and_the_tool_before_it_comes_back(window):
    tree, _rock, _waypoint = objects(window)
    window.document.selection.set([tree])
    window.copy()
    window.use_tool("waypoint")
    window.paste()
    assert window.map_view.tool is window.paste_tool
    count = len(objects(window))
    assert window.paste_tool.key(window.map_view, Qt.Key.Key_Escape)
    assert len(objects(window)) == count
    assert window.map_view.tool is window.waypoint_tool
    assert window.paste_tool.ghosts() == ()


def test_objects_copied_in_another_editor_paste_here(window):
    board = QApplication.clipboard()
    data = QMimeData()
    other = Clipboard((placed("Castle", 10.0, 20.0, uniqueID="Castle 7"),), (), (10.0, 20.0))
    data.setData(CLIPBOARD_MIME, QByteArray(clipboard_to_json(other).encode("utf-8")))
    board.setMimeData(data)
    window.map_view.cursor_world = (200.0, 250.0)
    window.paste()
    drag(window, [(200.0, 250.0)])
    castle = objects(window)[-1]
    assert castle.type_name == "Castle" and castle.position == (200.0, 250.0, 0.0)
    assert castle.properties["uniqueID"]["value"] == "Castle 2"


def test_group_edit_and_allowances_are_saved(window):
    window.group_edit_actions.actions()[0].trigger()
    assert window.settings.group_edit_method is GroupEditMethod.MATCH_LEAD
    window.pick_actions[PickCategory.ROADS].trigger()
    restored = Settings.from_dict(window.settings.to_dict())
    assert restored.group_edit_method is GroupEditMethod.MATCH_LEAD
    assert PickCategory.ROADS not in restored.pick_allowances
    assert PickCategory.UNITS in restored.pick_allowances
