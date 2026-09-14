"""Qt-level tests for Terrain Copy and Apply To Tiles: drag and brush selection, a copy that
undoes byte-identically, the options panel, and the Apply texture dialog's result becoming one
undo entry. Headless via 'offscreen'; marked `full`."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.brush_options import CopyTerrainOptions, SelectMethod  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.apply_texture import ApplyTextureOptions  # noqa: E402
from sage_worldbuilder.terrain.cells import TileLayer  # noqa: E402
from sage_worldbuilder.terrain.textures import texture_classes  # noqa: E402
from sage_worldbuilder.ui.copy_terrain_options import CopyTerrainOptionsPanel  # noqa: E402
from sage_worldbuilder.ui.terrain_copy_tool import NOTHING_SELECTED  # noqa: E402
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
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window._set_document(MapDocument.from_bytes(FIXTURE.read_bytes()))
    view = window.map_view
    view.resize(600, 500)
    view.transform.width, view.transform.height = 600, 500
    view.fit_map()
    yield window
    window.document = None
    window.close()


def gesture(window, column, row, **modifiers):
    x, y = window.document.terrain.cell_to_world(column, row)
    return Gesture((x, y), QPointF(*window.map_view.transform.world_to_screen(x, y)), **modifiers)


def drag(tool, window, start, end):
    view = window.map_view
    tool.press(view, gesture(window, *start))
    tool.move(view, gesture(window, *end))
    tool.release(view, gesture(window, *end))


def test_drag_and_brush_select_then_copy_and_undo(window):
    document, options = window.document, window.settings.copy_terrain
    window.terrain_copy_action.trigger()
    tool = window.terrain_copy_tool
    assert window.map_view.tool is tool

    drag(tool, window, (100, 100), (104, 102))
    assert int(tool.selection.sum()) == 15
    options.method, options.brush_size, options.remove = SelectMethod.BRUSH, 1, True
    drag(tool, window, (102, 101), (102, 101))
    assert int(tool.selection.sum()) == 14
    window.map_view.grab()  # draws the selection

    before = document.to_bytes(compress=False)
    classes = texture_classes(
        document.cells(TileLayer.TILES), document.map.blend_tile_data.textures
    )
    options.copying = True
    tool.hover(window.map_view, gesture(window, 200, 150))
    window.map_view.grab()  # draws the copy preview
    drag(tool, window, (200, 150), (200, 150))
    assert document.stack.undo_label == "Copy Terrain"
    after = texture_classes(document.cells(TileLayer.TILES), document.map.blend_tile_data.textures)
    # The selection's centre (102, 101) lands on (200, 150).
    assert np.array_equal(after[149:152, 198:203], classes[100:103, 100:105])
    document.stack.undo()
    assert document.to_bytes(compress=False) == before

    tool.clear_selection()
    drag(tool, window, (200, 150), (200, 150))
    assert window.statusBar().currentMessage() == NOTHING_SELECTED
    assert not document.stack.can_undo


def test_the_options_panel_enables_the_section_for_its_mode(qapp):
    options = CopyTerrainOptions()
    panel = CopyTerrainOptionsPanel(options)
    assert panel.selection_box.isEnabled() and not panel.copy_box.isEnabled()
    panel.copy_mode.setChecked(True)
    panel.rotations[3].setChecked(True)
    panel.flip_horizontally.setChecked(True)
    assert options.copying and options.turns == 3 and options.flip_horizontally
    assert panel.copy_box.isEnabled() and not panel.selection_box.isEnabled()
    assert CopyTerrainOptions.from_dict(options.to_dict()) == options


def test_apply_to_tiles_is_one_undo_entry(window, monkeypatch):
    document = window.document
    blend = document.map.blend_tile_data
    window.terrain_material_panel.select_texture(blend.textures[2].name)

    class Accepting:
        def __init__(self, options, parent):
            pass

        def exec(self):
            return 1

        def options(self):
            return ApplyTextureOptions(use_slopes=True, slopes=(0, 3))

    monkeypatch.setattr("sage_worldbuilder.ui.window.ApplyTextureDialog", Accepting)
    before = document.to_bytes(compress=False)
    window.terrain_material_panel.apply_button.click()
    assert document.stack.undo_label == "Apply Texture to Tiles"
    document.stack.undo()
    assert document.to_bytes(compress=False) == before
