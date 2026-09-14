"""Qt-level tests for the whole-map texture commands: Optimize, Remove All Texture Blends and
Remove Cliff Texture Mapping from their menus, Show Stretched Tiles, and Flood Fill's Shift-fill
with a same-size texture the map lacks. Headless via 'offscreen'; marked `full`."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.brush_options import PaintMode  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.cells import TileLayer  # noqa: E402
from sage_worldbuilder.terrain.textures import texture_classes  # noqa: E402
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
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *args: QMessageBox.StandardButton.Yes)
    )
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window._set_document(MapDocument.from_bytes(FIXTURE.read_bytes()))
    view = window.map_view
    view.resize(600, 500)
    view.transform.width, view.transform.height = 600, 500
    view.fit_map()
    yield window
    window.document = None
    window.close()


def test_the_whole_map_commands_are_each_one_undo_entry(window):
    document = window.document
    before = document.to_bytes(compress=False)
    for action, label in (
        (window.remove_blends_action, "Remove All Texture Blends"),
        (window.optimize_tiles_action, "Optimize Tiles and Blend Tiles"),
    ):
        action.trigger()
        assert document.stack.undo_label == label
        document.stack.undo()
        assert document.to_bytes(compress=False) == before
    window.remove_cliff_mapping_action.trigger()
    if document.map.blend_tile_data.cliff_texture_mappings or document.stack.can_undo:
        document.stack.undo()
    assert document.to_bytes(compress=False) == before


def test_show_stretched_and_unblended_tiles_draw_their_tints(window):
    window.view_actions["show_stretched"].trigger()
    window.view_actions["show_unblended"].trigger()
    assert window.settings.view.show_stretched and window.settings.view.show_unblended
    assert window.map_view._stretched_image() is not None
    assert window.map_view._unblended_image() is not None
    window.map_view.grab()


def test_a_shift_fill_with_a_same_size_texture_renames_the_entry(window):
    document = window.document
    blend = document.map.blend_tile_data
    tiles = document.cells(TileLayer.TILES)
    classes = texture_classes(tiles, blend.textures)
    number = int(classes[100, 100])
    assert blend.textures[number].cell_size == 4
    old = blend.textures[number].name
    window.settings.paint.mode = PaintMode.TEXTURE
    window.settings.paint.texture = "BrandNewTexture"
    window.flood_fill_action.trigger()
    x, y = document.terrain.cell_to_world(100, 100)
    point = QPointF(*window.map_view.transform.world_to_screen(x, y))
    monkeypatched = window.confirm_replace_all
    window.confirm_replace_all = lambda name: True
    try:
        window.flood_fill_tool.press(window.map_view, Gesture((x, y), point, shift=True))
    finally:
        window.confirm_replace_all = monkeypatched
    assert blend.textures[number].name == "BrandNewTexture"
    assert np.array_equal(document.cells(TileLayer.TILES), tiles), "every cell keeps its tile"
    document.stack.undo()
    assert blend.textures[number].name == old
