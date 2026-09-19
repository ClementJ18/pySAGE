"""Qt-level tests for the Build List panel and tool. Headless via 'offscreen'; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import ObjectsList  # noqa: E402
from sage_map.assets.sides_list import BuildList, BuildLists, SidesList  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.build_lists import build_list_entries  # noqa: E402
from sage_worldbuilder.players import new_player  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
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
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.sides_list = SidesList(
        version=6,
        unknown1=False,
        players=[new_player(""), new_player("PlyrGood", "Good", "FactionMen")],
        start_pos=0,
        end_pos=0,
    )
    map.build_lists = BuildLists(
        version=6,
        build_lists=[
            BuildList(faction_name="UNKNOWN", faction_name_property=None, build_list=[]),
            BuildList(faction_name="Men", faction_name_property=None, build_list=[]),
        ],
        start_pos=0,
        end_pos=0,
    )
    window._set_document(MapDocument(map))
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


def test_tool_places_and_moves_entries_and_the_panel_edits_them(window):
    panel, map = window.build_list_panel, window.document.map
    assert [panel.side.itemText(i) for i in range(panel.side.count())] == [
        "(neutral) (UNKNOWN)",
        "PlyrGood (Men)",
    ]
    panel.side.setCurrentIndex(1)
    window.palette_panel.choose("GondorFarm")
    window.build_list_tool_action.trigger()
    assert window.map_view.tool is window.build_list_tool

    drag(window, [(100.0, 100.0)])
    (farm,) = build_list_entries(map, 1)
    assert farm.location == (100.0, 100.0, 0.0)
    assert panel.current_entry() is farm
    assert window.map_view.build_entry is farm

    drag(window, [(100.0, 100.0), (150.0, 120.0), (200.0, 200.0)])
    assert farm.location == (200.0, 200.0, 0.0)
    assert len(build_list_entries(map, 1)) == 1
    window.document.stack.undo()
    assert farm.location == (100.0, 100.0, 0.0)

    panel.rebuilds.setValue(3)
    panel.initially_built.setChecked(True)
    panel.name.setText("Home Farm")
    panel.name.editingFinished.emit()
    assert (farm.num_rebuilds, farm.is_initially_built, farm.build_name) == (3, True, "Home Farm")
    assert panel.entries.item(0).text() == "Home Farm (GondorFarm)"

    text = panel.export_text()
    assert "Structure GondorFarm" in text and "Name = Home Farm" in text
    panel.side.setCurrentIndex(0)
    assert panel.import_text(text) == 1
    assert build_list_entries(map, 0)[0].build_name == "Home Farm"

    panel.side.setCurrentIndex(1)
    panel.entries.setCurrentRow(0)
    panel.delete_current()
    assert build_list_entries(map, 1) == []


def test_clicking_an_entry_of_another_player_switches_the_panel(window):
    panel, map = window.build_list_panel, window.document.map
    panel.side.setCurrentIndex(0)
    window.palette_panel.choose("Tower")
    window.use_tool("build list")
    drag(window, [(300.0, 300.0)])
    panel.side.setCurrentIndex(1)
    drag(window, [(301.0, 299.0)])
    assert panel.current_side() == 0
    assert panel.current_entry() is build_list_entries(map, 0)[0]
