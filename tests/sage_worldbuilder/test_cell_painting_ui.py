"""Qt-level tests for painting cell attributes: the Terrain Material panel, Single and Large Tile,
and the overlays. Headless via 'offscreen'; marked `full`."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.brush_options import BrushOptions, PaintMode  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.cells import CellLayer  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
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
    settings = Settings(install=str(install))
    settings.brush = BrushOptions(width=4)
    window = MainWindow(settings, load_game_data=False)
    window._set_document(MapDocument.from_bytes(FIXTURE.read_bytes()))
    view = window.map_view
    view.resize(600, 500)
    view.transform.width, view.transform.height = 600, 500
    view.fit_map()
    yield window
    window.document = None
    window.close()


def world_of(window, column, row):
    return window.document.terrain.cell_to_world(column, row)


def gesture(window, x, y):
    return Gesture((x, y), QPointF(*window.map_view.transform.world_to_screen(x, y)))


def render(window):
    image = QImage(window.map_view.size(), QImage.Format.Format_ARGB32)
    window.map_view.render(image)


def test_large_tile_paints_the_chosen_passability_as_one_stroke(window):
    panel, view, document = window.terrain_material_panel, window.map_view, window.document
    panel.mode_buttons[PaintMode.PASSABILITY].setChecked(True)
    panel.passability_buttons[1].setChecked(True)  # Impassable
    window.large_tile_action.trigger()
    assert view.overlay_layers == (
        CellLayer.IMPASSABLE,
        CellLayer.IMPASSABLE_TO_PLAYERS,
        CellLayer.EXTRA_PASSABLE,
    )
    tool = window.large_tile_tool
    rows, columns = document.cells(CellLayer.IMPASSABLE).shape
    column, row = columns // 2, rows // 2
    tool.press(view, gesture(window, *world_of(window, column + 0.5, row + 0.5)))
    tool.move(view, gesture(window, *world_of(window, column + 6.5, row + 0.5)))
    tool.release(view, gesture(window, *world_of(window, column + 6.5, row + 0.5)))
    impassable = document.cells(CellLayer.IMPASSABLE)
    assert impassable[row - 1 : row + 3, column - 1 : column + 9].all()
    render(window)
    assert view._overlay is not None
    assert document.stack.undo_label == "Paint Passability"
    document.stack.undo()
    assert not document.stack.can_undo


def test_single_tile_paints_one_cell_of_the_chosen_mode(window):
    panel, view, document = window.terrain_material_panel, window.map_view, window.document
    panel.mode_buttons[PaintMode.PASSAGE_WIDTH].setChecked(True)
    assert window.settings.paint.mode is PaintMode.PASSAGE_WIDTH and window.settings.paint.narrow
    window.single_tile_action.trigger()
    assert view.overlay_layers == (CellLayer.NARROW,)
    before = int(document.cells(CellLayer.NARROW).sum())
    window.single_tile_tool.press(view, gesture(window, *world_of(window, 10.2, 12.3)))
    window.single_tile_tool.release(view, gesture(window, *world_of(window, 10.2, 12.3)))
    narrow = document.cells(CellLayer.NARROW)
    assert narrow[12, 10] and int(narrow.sum()) == before + 1

    window.select_tool_action.trigger()
    assert view.overlay_layers == ()
    window.view_actions["show_impassable"].trigger()
    render(window)
    assert view._overlay is not None
