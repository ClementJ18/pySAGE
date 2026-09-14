"""Qt-level tests for the Layers List, the selection helpers in the Edit menu, Replace Selected and
the Ruler Tool. Headless via 'offscreen'; marked `full`."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.assets.trigger_areas import TriggerAreas  # noqa: E402
from sage_map.assets.waypoint_list import WaypointsList  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def placed(type_name, x, y, layer=""):
    properties = {
        "objectLayer": {
            "name": "objectLayer",
            "type": AssetPropertyType.AsciiString,
            "value": layer,
        }
    }
    return Object(3, (x, y, 0.0), 0.0, 0, type_name, properties, 0, 0)


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
            placed("Tree", 100.0, 100.0, "Trees"),
            placed("Tree", 200.0, 100.0, "Trees"),
            placed("Rock", 300.0, 100.0),
        ],
        start_pos=0,
        end_pos=0,
    )
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    map.trigger_areas = TriggerAreas(version=1, trigger_areas=[], start_pos=0, end_pos=0)
    window._set_document(MapDocument(map))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    yield window
    window.document = None
    window.close()


def gesture(window, x, y):
    return Gesture((x, y), QPointF(*window.map_view.transform.world_to_screen(x, y)))


def rows(panel):
    return [
        [panel.tree.topLevelItem(i).text(column) for column in range(3)]
        for i in range(panel.tree.topLevelItemCount())
    ]


def test_layers_list_rows_hiding_and_the_active_layer(window):
    panel, view = window.layers_panel, window.map_view
    tree_a, tree_b, rock = window.document.map.objects_list.object_list
    assert rows(panel) == [["(default)  (active)", "1", "0"], ["Trees", "2", "0"]]

    panel.tree.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)
    assert panel.hidden == {"Trees"}
    assert not view.is_shown(tree_a) and view.is_shown(rock)

    assert panel.add_layer("Paths")
    assert not panel.add_layer("paths")
    panel.activate_selected()
    assert window.active_layer() == "Paths"
    window.waypoint_tool_action.trigger()
    window.waypoint_tool.press(view, gesture(window, 400.0, 400.0))
    window.waypoint_tool.release(view, gesture(window, 400.0, 400.0))
    waypoint = window.document.map.objects_list.object_list[-1]
    assert waypoint.properties["objectLayer"]["value"] == "Paths"
    assert ["Paths  (active)", "1", "0"] in rows(panel)


def test_rename_merge_delete_select_and_move_selection(window):
    panel = window.layers_panel
    tree_a, tree_b, rock = window.document.map.objects_list.object_list
    panel.select_layer("Trees")
    assert panel.rename_selected("Forest")
    assert tree_a.properties["objectLayer"]["value"] == "Forest"
    panel.select_items()
    assert window.document.selection.items == (tree_a, tree_b)

    window.document.selection.set([rock])
    panel.select_layer("Forest")
    panel.move_selection_here()
    assert rock.properties["objectLayer"]["value"] == "Forest"

    panel.select_layer("")
    assert not panel.rename_selected("Nope")
    panel.select_layer("Forest")
    panel.delete_selected()
    assert [row[0] for row in rows(panel)] == ["(default)  (active)"]
    assert rock.properties["objectLayer"]["value"] == ""
    window.document.stack.undo()
    panel.refresh()
    assert ["Forest", "3", "0"] in rows(panel)


def test_select_helpers_and_replace_selected(window):
    tree_a, tree_b, rock = window.document.map.objects_list.object_list
    window.document.selection.set([tree_a])
    window._refresh()
    window.select_similar_action.trigger()
    assert window.document.selection.items == (tree_a, tree_b)

    window.select_missing_action.trigger()
    assert window.document.selection.items == (tree_a, tree_b)
    window.context.game = SimpleNamespace(objects={"tree": object()}, tables={"factions": {}})
    window.select_missing_action.trigger()
    assert window.document.selection.items == (rock,)

    window.palette_panel.choose("Tree")
    window.replace_selected_action.trigger()
    assert rock.type_name == "Tree"
    window.document.stack.undo()
    assert rock.type_name == "Rock"


def test_ruler_measures_in_feet_and_cells(window):
    view = window.map_view
    window.ruler_tool_action.trigger()
    tool = window.ruler_tool
    tool.press(view, gesture(window, 0.0, 0.0))
    tool.move(view, gesture(window, 30.0, 40.0))
    tool.release(view, gesture(window, 30.0, 40.0))
    assert tool.measurement() == "Distance: 50.0 ft (5.0 cells)"
    assert window.statusBar().currentMessage() == "Distance: 50.0 ft (5.0 cells)"
    window.circular_ruler_action.trigger()
    assert tool.measurement().startswith("Radius: 50.0 ft")
    assert window.document.stack.can_undo is False
    window.select_tool_action.trigger()
    assert tool.start is None
