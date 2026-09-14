"""Qt-level tests for the Generic AI Object tool and its options panel, and Change Time Of Day.
Headless via the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.global_lighting import TimeOfTheDay  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.generic_ai import (  # noqa: E402
    GenericAIType,
    generic_ai_objects,
    generic_ai_values,
)
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402
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
    window.map_view.resize(600, 600)
    window._set_document(MapDocument(new_map(NewMapOptions(width=60, height=60, border=2))))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    window.use_tool("generic ai")
    yield window
    window.document = None
    window.close()


def click(window, x, y):
    view, tool = window.map_view, window.map_view.tool
    screen = QPointF(*view.transform.world_to_screen(x, y))
    tool.press(view, Gesture((x, y), screen))
    tool.release(view, Gesture((x, y), screen))


def test_a_click_adds_a_generic_ai_object_with_the_panel_values(window):
    panel = window.generic_ai_panel
    panel.kind.setCurrentIndex(panel.kind.findData(GenericAIType.WALL_HUB))
    panel.wall_hub.setValue(2)

    click(window, 200.0, 300.0)

    placed = generic_ai_objects(window.document.map)
    assert len(placed) == 1
    assert placed[0].position[:2] == (200.0, 300.0)
    assert generic_ai_values(placed[0])[:3] == ("GenericAIObject 1", GenericAIType.WALL_HUB, 2)
    assert list(window.document.selection) == placed
    assert panel.name.currentText() == "GenericAIObject 1"
    assert window.generic_ai_dock.isVisibleTo(window)


def test_a_click_near_one_chooses_it_instead_of_adding(window):
    click(window, 200.0, 300.0)
    window.document.selection.clear()

    click(window, 204.0, 303.0)

    assert len(generic_ai_objects(window.document.map)) == 1
    assert len(window.document.selection) == 1


def test_the_panel_edits_the_chosen_object_undoably(window):
    click(window, 200.0, 300.0)
    obj = generic_ai_objects(window.document.map)[0]
    panel = window.generic_ai_panel

    panel.kind.setCurrentIndex(panel.kind.findData(GenericAIType.EXPANSION_LOCATOR))
    assert generic_ai_values(obj)[1] is GenericAIType.EXPANSION_LOCATOR
    assert not panel.form.isRowVisible(panel.wall_hub)

    panel.name.setEditText("_WallHub_A")
    panel._rename()
    assert generic_ai_values(obj)[0] == "_WallHub_A"

    window.undo()
    window.undo()
    assert generic_ai_values(obj)[:2] == ("GenericAIObject 1", GenericAIType.WALL_HUB)
    assert panel.form.isRowVisible(panel.wall_hub)


def test_change_time_of_day_steps_the_saved_time_and_wraps(window):
    lighting = window.document.map.global_lighting
    start = lighting.time_of_the_day
    times = list(TimeOfTheDay)

    window.time_of_day_action.trigger()
    assert lighting.time_of_the_day is times[(times.index(start) + 1) % len(times)]
    window.undo()
    assert lighting.time_of_the_day is start

    for _ in range(len(times)):
        window.time_of_day_action.trigger()
    assert lighting.time_of_the_day is start
    # Presses in a row are one undo step, as repeated edits of one value are.
    window.time_of_day_action.trigger()
    window.undo()
    assert lighting.time_of_the_day is start
