"""A drag in the map view holds back the window's list refreshes until the button comes up, so
large maps drag smoothly. Headless via 'offscreen'; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def mouse(kind, point, button, buttons):
    return QMouseEvent(kind, point, point, button, buttons, Qt.KeyboardModifier.NoModifier)


def test_lists_refresh_once_when_the_drag_ends(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    try:
        tree = Object(3, (100.0, 100.0, 0.0), 0.0, 0, "Tree", {}, 0, 0)
        map = Map()
        map.objects_list = ObjectsList(version=3, object_list=[tree], start_pos=0, end_pos=0)
        window._set_document(MapDocument(map))
        view = window.map_view
        view.transform.width = view.transform.height = 600
        view.transform.fit(0, 0, 600, 600, margin=0)
        refreshes = []
        original = window.item_list_panel.refresh
        monkeypatch.setattr(
            window.item_list_panel, "refresh", lambda: (refreshes.append(1), original())
        )

        left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
        start = QPointF(*view.transform.world_to_screen(100.0, 100.0))
        view.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, start, left, left))
        assert view.gesture_active
        for step in range(1, 6):
            point = start + QPointF(10.0 * step, 0.0)
            view.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, point, none, left))
        assert tree.position[0] > 100.0
        assert refreshes == []
        end = start + QPointF(50.0, 0.0)
        view.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, end, left, none))
        assert not view.gesture_active
        assert refreshes == [1]
        assert window.document.stack.undo_label == "Move"
    finally:
        window.document = None
        window.close()
