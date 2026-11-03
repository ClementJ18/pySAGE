"""The editor's end of the MCP bridge: Tools > Allow Agent Connections publishes a connection file,
a client's edits land on the window's own document and undo stack, and the view can be captured;
and the Markers tool and panel the user points the agent with.
Headless via 'offscreen'; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import base64
import shutil
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.mcp_server import ToolError  # noqa: E402
from sage_worldbuilder.mcp_server.bridge import BridgeClient, connection_file  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture, MarkerMode  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


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
    window.ask_save_changes = lambda document: "discard"
    copy = tmp_path / "ford.map"
    shutil.copy(FIXTURE, copy)
    window._set_document(MapDocument.open(copy))
    yield window
    window.agent_connections_action.setChecked(False)
    window.toggle_agent_connections()
    window.document = None
    window.close()


def on_worker(qapp, call):
    """Run `call` off the GUI thread, pumping Qt events so the window can answer it."""
    outcome = {}

    def run():
        try:
            outcome["value"] = call()
        except Exception as error:  # noqa: BLE001 - re-raised on the test's thread
            outcome["error"] = error

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 30
    while worker.is_alive():
        qapp.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("the bridge did not answer")
        time.sleep(0.005)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def start(window):
    window.agent_connections_action.setChecked(True)
    window.toggle_agent_connections()
    assert window.agent_listener is not None and window.agent_listener.listening
    return BridgeClient()


def test_the_bridge_is_off_until_allowed_and_cleans_up_after(window):
    assert not window.agent_connections_action.isChecked()
    assert not connection_file().exists()
    start(window)
    assert connection_file().exists()
    window.agent_connections_action.setChecked(False)
    window.toggle_agent_connections()
    assert not connection_file().exists()


def test_agent_edits_land_on_the_window_document(qapp, window):
    client = start(window)
    placed = on_worker(
        qapp, lambda: client.call("place_object", {"template": "TestTree", "x": 50.0, "y": 60.0})
    )
    document = window.document
    assert document is not None and document.dirty
    assert document.stack.undo_label == "Place TestTree"
    on_worker(qapp, lambda: client.call("select_objects", {"object_ids": [placed["id"]]}))
    assert len(document.selection) == 1
    on_worker(qapp, lambda: client.call("undo", {}))
    assert not document.dirty
    client.close()


def test_opening_over_unsaved_edits_is_refused(qapp, window, tmp_path):
    client = start(window)
    on_worker(
        qapp, lambda: client.call("place_object", {"template": "TestTree", "x": 1.0, "y": 1.0})
    )
    with pytest.raises(ToolError, match="unsaved changes"):
        on_worker(qapp, lambda: client.call("open_map", {"path": str(tmp_path / "ford.map")}))
    client.close()


def test_the_view_can_be_moved_and_captured(qapp, window):
    window.resize(800, 600)
    window.show()
    client = start(window)
    on_worker(qapp, lambda: client.call("view_at", {"x": 500.0, "y": 500.0}))
    shot = on_worker(qapp, lambda: client.call("screenshot", {"max_width": 320}))
    assert shot["format"] == "png" and shot["width"] <= 320
    assert base64.b64decode(shot["data"]).startswith(b"\x89PNG")
    client.close()


def gesture(window, point, **keys):
    view = window.map_view
    return Gesture(point, QPointF(*view.transform.world_to_screen(*point)), **keys)


def drag(window, start, end, **keys):
    """A Markers tool drag in the top-down view, from one world position to another."""
    view, tool = window.map_view, window.marker_tool
    tool.press(view, gesture(window, start, **keys))
    tool.move(view, gesture(window, end, **keys))
    tool.release(view, gesture(window, end, **keys))


def click(window, point, **keys):
    drag(window, point, point, **keys)


@pytest.fixture
def markers_window(window):
    window.resize(800, 600)
    window.show()
    window.show_3d_view(False)
    # Close enough that a test drag of 50 world units is well past the drag threshold.
    window.map_view.fit_rect(0.0, 0.0, 900.0, 900.0)
    return window


def choose(window, mode):
    window.markers_panel._modes[mode].click()
    assert window.map_view.tool is window.marker_tool
    assert window.marker_tool.mode is mode


def test_rectangles_are_lettered_and_shown_in_the_panel(markers_window):
    window = markers_window
    window.use_tool("markers")
    assert window.markers_dock.isVisible()
    choose(window, MarkerMode.RECTANGLE)
    drag(window, (100.0, 100.0), (300.0, 250.0))
    drag(window, (400.0, 400.0), (500.0, 500.0))
    markers = window.document.markers
    assert [m.name for m in markers] == ["A", "B"]
    assert markers.get("A").bounds == (100.0, 100.0, 300.0, 250.0)
    assert markers.selected.name == "B"
    assert not window.document.dirty
    window.map_view.grab()  # the overlay draws them
    areas = window.markers_panel.tree.topLevelItem(0)
    assert areas.text(0) == "Areas (2)"
    assert window.markers_panel.tree.currentItem().text(0) == "B"
    click(window, (150.0, 150.0))  # a click chooses, it no longer removes
    assert markers.selected.name == "A" and len(markers) == 2
    window.clear_markers_action.trigger()
    assert not markers


def test_a_polygon_closes_on_its_first_corner_or_enter(markers_window):
    window = markers_window
    choose(window, MarkerMode.POLYGON)
    for corner in ((100.0, 100.0), (400.0, 100.0), (250.0, 300.0)):
        click(window, corner)
    click(window, (100.0, 100.0))
    markers = window.document.markers
    assert markers.get("A").points == ((100.0, 100.0), (400.0, 100.0), (250.0, 300.0))
    for corner in ((500.0, 500.0), (700.0, 500.0), (700.0, 700.0), (600.0, 800.0)):
        click(window, corner)
    tool = window.marker_tool
    tool.key(window.map_view, Qt.Key.Key_Backspace)  # drops the last corner
    assert tool.key(window.map_view, Qt.Key.Key_Return)
    assert len(markers.get("B").points) == 3
    window.map_view.grab()


def test_points_and_a_path_through_them(markers_window):
    window = markers_window
    choose(window, MarkerMode.POINT)
    click(window, (100.0, 100.0))
    drag(window, (100.0, 100.0), (150.0, 100.0))  # drags the point instead of adding one
    markers = window.document.markers
    assert [m.name for m in markers] == ["P1"]
    assert markers.get("P1").position == (150.0, 100.0)

    choose(window, MarkerMode.PATH)
    click(window, (150.0, 100.0))  # the existing point
    click(window, (400.0, 100.0))  # new ground: a new point
    click(window, (400.0, 400.0))
    click(window, (400.0, 400.0))  # the last stop again finishes
    path = markers.get("L1")
    assert path.stops == ("P1", "P2", "P3")
    assert markers.selected is path

    # Starting on the chosen path's end extends it.
    click(window, (400.0, 400.0))
    click(window, (100.0, 400.0))
    window.marker_tool.key(window.map_view, Qt.Key.Key_Enter)
    assert markers.get("L1").stops == ("P1", "P2", "P3", "P4")
    assert len(markers.paths()) == 1
    window.map_view.grab()


def test_edit_mode_moves_reshapes_and_removes(markers_window):
    window = markers_window
    markers = window.document.markers
    markers.mark_rectangle(100.0, 100.0, 300.0, 300.0)
    choose(window, MarkerMode.EDIT)
    drag(window, (200.0, 200.0), (250.0, 200.0))  # the body
    assert markers.get("A").bounds == (150.0, 100.0, 350.0, 300.0)
    assert markers.selected.name == "A"
    drag(window, (350.0, 300.0), (400.0, 350.0))  # a corner
    assert (400.0, 350.0) in markers.get("A").points
    click(window, (250.0, 100.0), shift=True)  # the bottom edge: a corner goes in
    assert len(markers.get("A").points) == 5
    click(window, (250.0, 100.0), alt=True)  # and comes out again
    assert len(markers.get("A").points) == 4

    for x in (500.0, 700.0):
        markers.mark_point(x, 500.0)
    markers.mark_path(["P1", "P2"])
    markers.select("L1")
    click(window, (600.0, 500.0), shift=True)  # the leg: a new point in the path
    assert markers.get("L1").stops == ("P1", "P3", "P2")
    drag(window, (600.0, 500.0), (600.0, 600.0))  # a stop of the chosen path
    assert markers.get("P3").position == (600.0, 600.0)

    assert window.marker_tool.key(window.map_view, Qt.Key.Key_Delete)
    assert markers.get("L1") is None and len(markers.points()) == 3


def test_the_panel_renames_frames_and_deletes(markers_window):
    window = markers_window
    markers = window.document.markers
    markers.mark_point(100.0, 100.0)
    markers.mark_point(300.0, 100.0)
    markers.mark_path(["P1", "P2"])
    panel = window.markers_panel
    paths = panel.tree.topLevelItem(2)
    assert paths.child(0).text(1) == "P1 > P2, 200 long"
    point = panel.tree.topLevelItem(1).child(0)
    panel.tree.setCurrentItem(point)
    assert markers.selected.name == "P1"
    point.setText(0, "ford")  # an in-place rename
    assert markers.get("L1").stops == ("FORD", "P2")
    assert panel.tree.currentItem().text(0) == "FORD"
    panel.tree.currentItem().setText(0, "p2")  # taken: refused, the list puts it back
    assert markers.get("FORD") is not None
    window.map_view.zoom_to(3000.0, 3000.0, 5.0)
    panel.zoom_button.click()
    left, bottom, right, top = window.map_view.transform.visible_world()
    assert left <= 100.0 <= right and bottom <= 100.0 <= top
    panel.delete_button.click()
    assert markers.get("FORD") is None and markers.get("L1") is None
    panel.clear_button.click()
    assert not markers


def test_a_marker_screenshot_crops_to_it_and_frames_it_when_off_screen(qapp, window):
    window.resize(800, 600)
    window.show()
    window.show_3d_view(False)
    assert window.active_view() is window.map_view
    client = start(window)
    window.map_view.fit_map()
    whole = on_worker(qapp, lambda: client.call("screenshot", {"max_width": 0}))
    extent = window.document.terrain.width * 10 / 2
    x0, y0 = extent - 100.0, extent - 50.0
    corners = {"x0": x0, "y0": y0, "x1": x0 + 200.0, "y1": y0 + 100.0}
    on_worker(qapp, lambda: client.call("mark_area", corners))
    assert [m.name for m in window.document.markers] == ["A"]
    cropped = on_worker(qapp, lambda: client.call("screenshot", {"max_width": 0, "marker": "A"}))
    assert cropped["width"] < whole["width"] and cropped["height"] < whole["height"]
    # Roughly the area's 2:1 shape, margin included.
    assert 1.4 < cropped["width"] / cropped["height"] < 2.2

    window.map_view.zoom_to(3000.0, 3000.0, 5.0)  # A is off screen now
    framed = on_worker(qapp, lambda: client.call("screenshot", {"max_width": 0, "marker": "A"}))
    image = QImage.fromData(base64.b64decode(framed["data"]))
    assert not image.isNull() and framed["width"] > cropped["width"]
    left, bottom, right, top = window.map_view.transform.visible_world()
    assert left <= x0 and right >= x0 + 200.0 and bottom <= y0 and top >= y0 + 100.0

    # A point is pictured with ground round it.
    on_worker(qapp, lambda: client.call("mark_point", {"x": extent, "y": extent}))
    point = on_worker(qapp, lambda: client.call("screenshot", {"max_width": 0, "marker": "P1"}))
    assert point["width"] > 0
    client.close()


def test_a_marker_screenshot_in_the_3d_view(qapp, window):
    window.resize(800, 600)
    window.show()
    window.show_3d_view(True)
    client = start(window)
    on_worker(
        qapp,
        lambda: client.call("mark_area", {"x0": 500.0, "y0": 500.0, "x1": 900.0, "y1": 800.0}),
    )
    shot = on_worker(qapp, lambda: client.call("screenshot", {"max_width": 0, "marker": "A"}))
    assert base64.b64decode(shot["data"]).startswith(b"\x89PNG")
    client.close()


def test_an_agent_path_shows_in_the_panel(qapp, window):
    client = start(window)
    on_worker(
        qapp,
        lambda: client.call("mark_path", {"stops": [[100.0, 100.0], [300.0, 300.0]], "name": "x"}),
    )
    paths = window.markers_panel.tree.topLevelItem(2)
    assert paths.text(0) == "Paths (1)" and paths.child(0).text(0) == "X"
    client.close()


def test_texturing_through_the_editor(qapp, window):
    client = start(window)
    listed = on_worker(qapp, lambda: client.call("list_textures", {"include_game": True}))
    assert listed["game"] is None  # the window has no game data loaded here
    name = listed["on_map"][0]["name"]
    painted = on_worker(
        qapp,
        lambda: client.call(
            "paint_texture", {"texture": name, "x0": 400.0, "y0": 400.0, "x1": 500.0, "y1": 500.0}
        ),
    )
    assert painted["cells"] == 121
    on_worker(
        qapp,
        lambda: client.call("blend_region", {"x0": 300.0, "y0": 300.0, "x1": 600.0, "y1": 600.0}),
    )
    assert window.document.stack.undo_label == "Blend Region"
    client.close()
