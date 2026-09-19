"""Double-clicking an Item List row selects that item, so the Object Properties panel shows it.
Headless via the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.items import ItemKind  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
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
    unique = {
        "uniqueID": {"name": "uniqueID", "type": AssetPropertyType.AsciiString, "value": "Tree 0"}
    }
    map = Map()
    map.objects_list = ObjectsList(
        version=3,
        object_list=[
            Object(3, (100.0, 100.0, 0.0), 0.0, 0, "Tree", unique, 0, 0),
            Object(3, (300.0, 100.0, 0.0), 0.0, 0, "Rock", {}, 0, 0),
        ],
        start_pos=0,
        end_pos=0,
    )
    map.trigger_areas = TriggerAreas(
        version=1,
        trigger_areas=[TriggerArea("Zone", "", 1, [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0)], 0)],
        start_pos=0,
        end_pos=0,
    )
    window._set_document(MapDocument(map))
    window.map_view.transform.width = window.map_view.transform.height = 600
    yield window
    window.document = None
    window.close()


def row_node(panel, kind, name=None):
    for index in range(panel.tree.topLevelItemCount()):
        node = panel.tree.topLevelItem(index)
        row = node.data(0, Qt.ItemDataRole.UserRole)
        if row.kind is kind and (name is None or row.source.type_name == name):
            return node
    raise AssertionError(f"no {kind} row")


def test_double_click_selects_the_item_for_object_properties(window):
    panel, properties = window.item_list_panel, window.object_panel
    tree, rock = window.document.map.objects_list.object_list
    zone = window.document.map.trigger_areas.trigger_areas[0]
    window.document.selection.set([rock])

    panel.tree.itemDoubleClicked.emit(row_node(panel, ItemKind.OBJECT, "Tree"), 0)
    assert window.document.selection.items == (tree,)
    assert properties.heading.text() == "Tree (Tree 0)"
    assert window.map_view.transform.center_x == pytest.approx(100.0)

    panel.tree.itemDoubleClicked.emit(row_node(panel, ItemKind.AREA), 0)
    assert window.document.selection.items == (zone,)
    assert properties.visible_tabs() == [properties.area_tab]


def test_a_locked_selection_is_kept(window):
    panel = window.item_list_panel
    tree, rock = window.document.map.objects_list.object_list
    window.document.selection.set([rock])
    window.lock_selection_action.trigger()
    panel.tree.itemDoubleClicked.emit(row_node(panel, ItemKind.OBJECT, "Tree"), 0)
    assert window.document.selection.items == (rock,)
