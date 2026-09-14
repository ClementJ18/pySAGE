"""Qt-level tests for Remap Textures: a same-size replacement renames the map's texture as one
undo entry, and one of another size is left alone. Headless via 'offscreen'; marked `full`."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.cells import TileLayer  # noqa: E402
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
    yield window
    window.document = None
    window.close()


def answering(monkeypatch, replacements, accepted=True):
    class Dialog:
        def __init__(self, names, catalogue, parent):
            self.names = names

        def exec(self):
            return 1 if accepted else 0

        def replacements(self):
            return replacements

    monkeypatch.setattr("sage_worldbuilder.ui.window.RemapTexturesDialog", Dialog)


def test_a_same_size_replacement_renames_the_texture(window, monkeypatch):
    document = window.document
    blend = document.map.blend_tile_data
    number = next(i for i, t in enumerate(blend.textures) if t.cell_size == 4)
    old = blend.textures[number].name
    tiles = document.cells(TileLayer.TILES).copy()
    before = document.to_bytes(compress=False)

    answering(monkeypatch, {number: "ReplacementTexture"})
    window.remap_textures_action.trigger()
    assert blend.textures[number].name == "ReplacementTexture"
    assert np.array_equal(document.cells(TileLayer.TILES), tiles), "every cell keeps its tile"
    assert document.stack.undo_label == "Remap Textures"
    document.stack.undo()
    assert blend.textures[number].name == old
    assert document.to_bytes(compress=False) == before


def test_a_replacement_of_another_size_is_left_alone(window, monkeypatch):
    document = window.document
    blend = document.map.blend_tile_data
    number = next((i for i, t in enumerate(blend.textures) if t.cell_size != 4), None)
    if number is None:
        pytest.skip("every texture on this map is four texture cells across")
    old = blend.textures[number].name
    answering(monkeypatch, {number: "ReplacementTexture"})
    window.remap_textures_action.trigger()
    assert blend.textures[number].name == old
    assert "ReplacementTexture" in window.statusBar().currentMessage()
    assert not document.stack.can_undo


def test_a_cancelled_dialog_changes_nothing(window, monkeypatch):
    document = window.document
    blend = document.map.blend_tile_data
    answering(monkeypatch, {0: "ReplacementTexture"}, accepted=False)
    window.remap_textures_action.trigger()
    assert blend.textures[0].name != "ReplacementTexture"
    assert not document.stack.can_undo
