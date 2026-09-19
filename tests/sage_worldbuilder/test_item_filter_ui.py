"""The Item List's Filter map option: the map view shows, and picks, only what the list matches.
Headless via the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def named(type_name, x, y, name):
    stored = {
        "objectName": {"name": "objectName", "type": AssetPropertyType.AsciiString, "value": name}
    }
    return Object(3, (x, y, 0.0), 0.0, 0, type_name, stored, 0, 0)


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    map = Map()
    map.objects_list = ObjectsList(
        version=3,
        object_list=[
            named("GondorFighter", 100.0, 100.0, "Guard"),
            named("Tree", 300.0, 100.0, ""),
        ],
        start_pos=0,
        end_pos=0,
    )
    map.trigger_areas = TriggerAreas(
        version=1,
        trigger_areas=[TriggerArea("Zone", "", 1, [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)], 0)],
        start_pos=0,
        end_pos=0,
    )
    window._set_document(MapDocument(map))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    yield window
    window.document = None
    window.close()


def test_filter_map_follows_the_search_and_can_be_turned_off(window):
    guard, tree = window.document.map.objects_list.object_list
    zone = window.document.map.trigger_areas.trigger_areas[0]
    panel, view = window.item_list_panel, window.map_view
    panel.search.setText("gondor")
    assert view.is_shown(guard) and view.is_shown(tree) and view.is_shown(zone)

    panel.filter_map.setChecked(True)
    assert view.is_shown(guard)
    assert not view.is_shown(tree) and not view.is_shown(zone)

    panel.search.setText("zone")
    assert view.is_shown(zone) and not view.is_shown(guard)

    panel.filter_map.setChecked(False)
    assert view.is_shown(guard) and view.is_shown(tree)


def test_hidden_objects_cannot_be_picked(window):
    guard, tree = window.document.map.objects_list.object_list
    panel, view = window.item_list_panel, window.map_view
    panel.search.setText("gondor")
    panel.filter_map.setChecked(True)

    def click(x, y):
        screen = QPointF(*view.transform.world_to_screen(x, y))
        view.tool.press(view, Gesture((x, y), screen))
        view.tool.release(view, Gesture((x, y), screen))

    click(300.0, 100.0)
    assert not window.document.selection
    click(100.0, 100.0)
    assert window.document.selection.items == (guard,)
    screen_a = QPointF(*view.transform.world_to_screen(0.0, 0.0))
    screen_b = QPointF(*view.transform.world_to_screen(400.0, 400.0))
    view.tool.press(view, Gesture((0.0, 0.0), screen_a))
    view.tool.move(view, Gesture((400.0, 400.0), screen_b))
    view.tool.release(view, Gesture((400.0, 400.0), screen_b))
    assert window.document.selection.items == (guard,)
