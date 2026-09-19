"""Qt-level tests for New, Resize, heightmap Import / Export and Open from TGA in the window, and
the New Height Map dialog. Headless via 'offscreen'; marked `full`."""

import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from sage_worldbuilder.heightmap_io import Anchor, export_raw  # noqa: E402
from sage_worldbuilder.new_map import NewMapOptions  # noqa: E402
from sage_worldbuilder.resize import ResizeOptions  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.new_map_dialog import NewMapDialog  # noqa: E402
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
    yield window
    window.document = None
    window.close()


def test_new_map_opens_an_untitled_map_of_the_chosen_size(window):
    assert window.new_action.isEnabled()
    window.create_new_map(NewMapOptions(width=40, height=30, border=4, initial_height=10.0))
    document = window.document
    assert document is not None and document.path is None
    assert document.terrain.heights.shape == (30, 40)
    assert (document.terrain.heights == 256).all()
    assert window.resize_action.isEnabled()


def test_resize_is_one_undo_entry(window):
    window.create_new_map(NewMapOptions(width=40, height=30, border=4))
    window.apply_resize(ResizeOptions(width=50, height=30, border=4, anchor=Anchor.LEFT))
    document = window.document
    assert document.terrain.heights.shape == (30, 50)
    assert document.stack.undo_label == "Resize"
    document.stack.undo()
    assert document.terrain.heights.shape == (30, 40)


def test_heightmap_export_import_and_a_wrong_size(window, tmp_path):
    window.create_new_map(NewMapOptions(width=12, height=10, border=2))
    document = window.document
    path = tmp_path / "heights.raw"
    window.export_heightmap(path)
    assert path.stat().st_size == 12 * 10 * 6

    changed = np.full((10, 12), 999, dtype=np.uint16)
    changed[0, 0] = 5
    path.write_bytes(export_raw(changed))
    assert window.import_heightmap(path)
    assert document.terrain.heights[0, 0] == 5 and document.terrain.heights[9, 11] == 999
    assert document.stack.undo_label == "Import Heightmap"

    (tmp_path / "wrong.raw").write_bytes(b"\0" * 18)
    assert not window.import_heightmap(tmp_path / "wrong.raw")
    assert document.terrain.heights[0, 0] == 5


def test_open_from_an_image_makes_a_map_of_its_size(window, tmp_path):
    from PIL import Image  # noqa: PLC0415

    image = Image.new("L", (24, 18), 40)
    buffer = io.BytesIO()
    image.save(buffer, format="TGA")
    path = tmp_path / "hills.tga"
    path.write_bytes(buffer.getvalue())
    window.open_from_image(path)
    document = window.document
    assert document.terrain.heights.shape == (18, 24)
    assert (document.terrain.heights == 40 * 16).all()


def test_the_dialog_checks_its_values(qapp):
    dialog = NewMapDialog(NewMapOptions(), ["Gravel", "Rock"])
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled()
    dialog.border_box.setValue(150)
    assert not ok.isEnabled() and dialog.problem.text()
    dialog.border_box.setValue(10)
    assert dialog.new_map_options().border == 10

    resize = NewMapDialog(NewMapOptions(), [], resize=True)
    resize.anchor_buttons[Anchor.TOP_RIGHT].setChecked(True)
    assert resize.resize_options().anchor is Anchor.TOP_RIGHT
