"""Qt-level tests for Place Object: the palette, placing by click and by drag, grid snap, the
default owner and height, and switching tools. Headless via 'offscreen'; marked `full`."""

import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import ObjectsList  # noqa: E402
from sage_map.assets.sides_list import SidesList  # noqa: E402
from sage_map.assets.teams import Teams  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.players import new_player  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.teams import new_team  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402
from sage_worldbuilder.viewport import GridSettings  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def placeable_map():
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.sides_list = SidesList(
        version=6,
        unknown1=False,
        players=[new_player(""), new_player("PlyrCivilian", "Civilian")],
        start_pos=0,
        end_pos=0,
    )
    map.teams = Teams(
        version=1,
        teams=[new_team("team", ""), new_team("teamPlyrCivilian", "PlyrCivilian")],
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
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window.context.game = SimpleNamespace(
        objects={
            "GondorFighter": SimpleNamespace(
                EditorSorting=[SimpleNamespace(name="UNIT")], Side="Gondor"
            ),
            # No Side: the palette files it under Civilian, as the engine reads it.
            "Tree": SimpleNamespace(EditorSorting=[SimpleNamespace(name="SHRUBBERY")]),
        },
        # The Player List panel reads the factions table when a map opens.
        tables={"factions": {}},
    )
    window._set_document(MapDocument(placeable_map()))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    yield window
    window.document = None
    window.close()


def gesture(window, x, y):
    return Gesture((x, y), QPointF(*window.map_view.transform.world_to_screen(x, y)))


def placed(window):
    return window.document.map.objects_list.object_list


def test_palette_lists_the_game_objects_by_side_and_the_map_teams(window):
    palette = window.palette_panel
    sides = [palette.tree.topLevelItem(i).text(0) for i in range(palette.tree.topLevelItemCount())]
    assert sides == ["Civilian (1)", "Gondor (1)"]
    branch = palette.tree.topLevelItem(1)
    assert [branch.child(i).text(0) for i in range(branch.childCount())] == ["Units (1)"]
    assert branch.child(0).child(0).text(0) == "GondorFighter"
    palette.search.setText("tree")
    assert palette.tree.topLevelItemCount() == 1
    assert palette.tree.topLevelItem(0).text(0) == "Civilian (1)"
    assert palette.status.text() == "1 object(s)"
    palette.search.setText("")
    owners = [palette.owner.itemText(i) for i in range(palette.owner.count())]
    assert owners == ["/team", "PlyrCivilian/teamPlyrCivilian"]
    assert palette.default_owner() == "/team"


def test_choosing_an_object_switches_to_place_and_a_click_places_it(window):
    palette = window.palette_panel
    tree = palette.tree.topLevelItem(0).child(0).child(0)
    palette._clicked(tree)
    assert window.map_view.tool is window.place_tool
    assert window.place_tool_action.isChecked()

    palette.owner.setCurrentIndex(1)
    palette.height_offset.setValue(12.0)
    tool, view = window.place_tool, window.map_view
    tool.press(view, gesture(window, 100.0, 200.0))
    tool.release(view, gesture(window, 100.0, 200.0))
    (obj,) = placed(window)
    assert obj.type_name == "Tree"
    assert obj.position == (100.0, 200.0, 12.0)
    assert obj.angle == 0.0
    assert obj.properties["originalOwner"]["value"] == "PlyrCivilian/teamPlyrCivilian"
    assert obj.properties["uniqueID"]["value"] == "Tree 0"
    assert window.document.selection.items == (obj,)
    window.document.stack.undo()
    assert placed(window) == []


def test_drag_orients_and_snap_applies(window):
    window.palette_panel.choose("GondorFighter")
    window.use_tool("place")
    window.settings.view.grid = GridSettings(spacing=50.0, snap=True)
    tool, view = window.place_tool, window.map_view
    tool.press(view, gesture(window, 104.0, 196.0))
    tool.move(view, gesture(window, 104.0, 250.0))
    tool.release(view, gesture(window, 100.0, 250.0))
    (obj,) = placed(window)
    assert obj.position[:2] == (100.0, 200.0)
    assert obj.angle == pytest.approx(math.pi / 2)
    assert window.document.stack.undo_label == "Place Object"


def test_the_chosen_object_follows_the_cursor_until_a_click_places_it(window):
    window.palette_panel.choose("GondorFighter")
    window.use_tool("place")
    window.palette_panel.height_offset.setValue(5.0)
    tool, view = window.place_tool, window.map_view
    assert tool.ghosts() == ()
    tool.hover(view, gesture(window, 120.0, 80.0))
    (ghost,) = tool.ghosts()
    assert ghost.type_name == "GondorFighter" and ghost.position == (120.0, 80.0, 5.0)
    assert placed(window) == []
    # Turning it by a drag turns the one shown too.
    tool.press(view, gesture(window, 120.0, 80.0))
    tool.move(view, gesture(window, 120.0, 180.0))
    assert tool.ghosts()[0].angle == pytest.approx(math.pi / 2)
    tool.release(view, gesture(window, 120.0, 180.0))
    assert len(placed(window)) == 1
    tool.leave(view)
    assert tool.ghosts() == ()


def test_place_without_a_chosen_object_does_nothing_and_select_comes_back(window):
    window.use_tool("place")
    assert not window.place_tool.press(window.map_view, gesture(window, 10.0, 10.0))
    assert placed(window) == []
    window.select_tool_action.trigger()
    assert window.map_view.tool is window.select_tool
