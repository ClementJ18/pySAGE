"""Edit > Special > Adjust Terrain to GROUND Objects in the window. Headless, marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.full

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")
pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402
from sage_worldbuilder.objects import new_object  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.grid import FEET_PER_HEIGHT_UNIT  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402

PAD = np.array(
    [
        [(-20.0, -20.0, 8.0), (20.0, -20.0, 8.0), (20.0, 20.0, 8.0)],
        [(-20.0, -20.0, 8.0), (20.0, 20.0, 8.0), (-20.0, 20.0, 8.0)],
    ]
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
    # Ground at zero, so the pad below raises it instead of flattening it down.
    map = new_map(NewMapOptions(width=32, height=32, border=2, initial_height=0.0))
    map.objects_list.object_list.append(new_object(map, "Keep", (100.0, 100.0, 0.0), 0.0, "/team"))
    window._set_document(MapDocument(map))
    # The window needs game data for this command; the models themselves are stubbed below.
    window.context = SimpleNamespace(game=object(), art_filesystem=lambda: object())
    monkeypatch.setattr("sage_worldbuilder.ui.window.ObjectModels", lambda game, world: object())
    monkeypatch.setattr("sage_worldbuilder.ui.window.ArtIndex", lambda filesystem: object())
    # Run the worker's work here, so the test sees the result without waiting on a thread.
    window._run_busy = lambda message, work, done: done(work())
    yield window
    window.document = None
    window.close()


def test_adjust_terrain_raises_the_ground_under_a_ground_object(window, monkeypatch):
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.load_ground_triangles",
        lambda names, models, art: {"Keep": PAD},
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    before = window.document.terrain.heights.copy()

    window.adjust_terrain_to_ground()

    heights = window.document.terrain.heights
    assert heights.max() == int(np.floor(8.0 / FEET_PER_HEIGHT_UNIT + 0.5))
    assert window.document.stack.undo_label == "Adjust Terrain to GROUND Objects"
    window.undo()
    assert np.array_equal(window.document.terrain.heights, before)


def test_the_question_can_be_declined_and_models_without_ground_change_nothing(window, monkeypatch):
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.load_ground_triangles",
        lambda names, models, art: {"Keep": PAD},
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    before = window.document.terrain.heights.copy()

    window.adjust_terrain_to_ground()
    assert np.array_equal(window.document.terrain.heights, before)

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.load_ground_triangles", lambda names, models, art: {}
    )

    window.adjust_terrain_to_ground()

    assert np.array_equal(window.document.terrain.heights, before)
    assert not window.document.stack.can_undo
