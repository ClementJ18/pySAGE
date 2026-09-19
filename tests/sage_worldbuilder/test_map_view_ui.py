"""Qt-level tests for the map view and its place in the window: drawing a map, the cursor readout,
zoom and pan, the View toggles, Grid Settings and the Item List's Zoom To Selected. Headless via
the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QImage, QMouseEvent, QWheelEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.height_map import HeightMapBorder, HeightMapData  # noqa: E402
from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import Change, ChangeKind, MapDocument  # noqa: E402
from sage_worldbuilder.items import ItemKind  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.map_view import MapView  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402
from sage_worldbuilder.viewport import ViewOptions  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def small_map() -> Map:
    width, height, border = 20, 16, 2
    map = Map()
    map.height_map_data = HeightMapData(
        version=5,
        width=width,
        height=height,
        border_width=border,
        borders=[HeightMapBorder((0, 0), (width - 2 * border, height - 2 * border))],
        area=width * height,
        min_height=0,
        max_height=0,
        elevations=[[row * 10 + column for column in range(width)] for row in range(height)],
        start_pos=0,
        end_pos=0,
    )
    name = {"name": "objectName", "type": AssetPropertyType.AsciiString, "value": "Guard"}
    map.objects_list = ObjectsList(
        version=3,
        object_list=[Object(3, (50.0, 40.0, 0.0), 0.0, 0, "Tree", {"objectName": name}, 0, 0)],
        start_pos=0,
        end_pos=0,
    )
    map.trigger_areas = TriggerAreas(
        version=1,
        trigger_areas=[TriggerArea("Zone", "", 1, [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0)], 0)],
        start_pos=0,
        end_pos=0,
    )
    return map


def render(view: MapView) -> QImage:
    image = QImage(view.size(), QImage.Format.Format_ARGB32)
    view.render(image)
    return image


def test_view_draws_and_reports_the_cell_under_the_cursor(qapp):
    view = MapView(ViewOptions(show_grid=True, show_labels=True))
    view.resize(400, 300)
    document = MapDocument(small_map())
    view.set_document(document)
    view.fit_map()
    render(view)
    reports = []
    view.cursor_moved.connect(lambda cell, height: reports.append((cell, height)))
    sx, sy = view.transform.world_to_screen(0.0, 0.0)
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(sx, sy),
        QPointF(sx, sy),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.mouseMoveEvent(move)
    # World (0, 0) is sample (2, 2); its stored row is 16 - 1 - 2 = 13, so 13 * 10 + 2.
    assert reports[-1] == ((2, 2), 132.0)


def test_wheel_zooms_and_middle_drag_pans(qapp):
    view = MapView()
    view.resize(400, 300)
    view.set_document(MapDocument(small_map()))
    scale = view.transform.scale
    wheel = QWheelEvent(
        QPointF(200, 150),
        QPointF(200, 150),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    view.wheelEvent(wheel)
    assert view.transform.scale == pytest.approx(scale * 1.2)
    view.options.reverse_scroll = True
    view.wheelEvent(wheel)
    assert view.transform.scale == pytest.approx(scale)

    center = (view.transform.center_x, view.transform.center_y)

    def mouse(kind, x, buttons):
        return QMouseEvent(
            kind,
            QPointF(x, 150),
            QPointF(x, 150),
            Qt.MouseButton.MiddleButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    view.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, 200, Qt.MouseButton.MiddleButton))
    view.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, 240, Qt.MouseButton.MiddleButton))
    view.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, 240, Qt.MouseButton.NoButton))
    assert view.transform.center_x == pytest.approx(center[0] - 40 / view.transform.scale)
    assert view.transform.center_y == pytest.approx(center[1])


def test_scene_is_rebuilt_only_for_changes_it_shows(qapp):
    view = MapView()
    document = MapDocument(small_map())
    view.set_document(document)
    scene = view.scene
    view.on_change(Change(ChangeKind.SCRIPTS))
    assert view.scene is scene
    view.on_change(Change(ChangeKind.OBJECTS))
    assert view.scene is not scene


def test_window_hosts_the_view_and_its_toggles(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    try:
        assert window.centralWidget() is window.view_stack
        # The editor opens in 3D; the rest of this drives the top-down view.
        opened = window.map_view_3d if window.map_view_3d is not None else window.map_view
        assert window.active_view() is opened
        window.show_3d_view(False)
        assert window.active_view() is window.map_view
        window._set_document(MapDocument(small_map()))
        assert window.map_view.document is window.document

        window.view_actions["show_grid"].trigger()
        assert window.settings.view.show_grid is True
        assert Settings.from_dict(window.settings.to_dict()).view.show_grid is True

        window.show_cursor((3, 4), 12.0)
        assert window.cell_label.text() == "Cell: 3, 4"

        panel = window.item_list_panel
        panel.refresh()
        nodes = [panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())]
        area = next(
            node for node in nodes if node.data(0, Qt.ItemDataRole.UserRole).kind is ItemKind.AREA
        )
        panel.tree.setCurrentItem(area)
        assert panel.zoom_to_selected()
        # The area's points average to (80/3, 40/3).
        assert window.map_view.transform.center_x == pytest.approx(80 / 3)
        assert window.map_view.transform.center_y == pytest.approx(40 / 3)
        assert window.map_view.transform.scale >= 0.5
    finally:
        window.document = None
        window.close()


def test_the_editor_opens_in_the_view_it_was_left_in(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    assert ViewOptions().view_3d is True
    settings = Settings(install=str(install), view=ViewOptions(view_3d=False))
    window = MainWindow(settings, load_game_data=False)
    try:
        # Left in the top-down view, so the 3D view is not made at all.
        assert window.active_view() is window.map_view
        assert window.map_view_3d is None
        assert not window.view_3d_action.isChecked()
        assert Settings.from_dict(settings.to_dict()).view.view_3d is False
    finally:
        window.close()
