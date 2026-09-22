"""Qt-level tests for View > Set LOD: the menu's five exclusive entries, their WorldBuilder
command ids, and that choosing one is remembered and forces the 3D view's models to rebuild.
Headless via the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_ini.model.enums import LodLevel  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402
from sage_worldbuilder.viewport import ViewOptions  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    settings = Settings(install=str(install), view=ViewOptions(view_3d=False))
    window = MainWindow(settings, load_game_data=False)
    yield window
    window.close()


def test_the_five_levels_are_an_exclusive_group_with_worldbuilders_own_command_ids(window):
    assert [level for level in window.lod_actions] == [
        LodLevel.UltraHigh,
        LodLevel.High,
        LodLevel.Medium,
        LodLevel.Low,
        LodLevel.VeryLow,
    ]
    assert window.lod_group.isExclusive()
    assert {33419, 33420, 33421, 33422, 33423} <= window.available_commands
    # Ultra High is ViewOptions' default, so a first run's menu shows it checked.
    assert window.lod_actions[LodLevel.UltraHigh].isChecked()
    assert not window.lod_actions[LodLevel.Low].isChecked()


def test_choosing_a_level_is_kept_and_checks_only_that_action(window):
    window.lod_actions[LodLevel.Medium].trigger()
    assert window.settings.view.lod_level is LodLevel.Medium
    assert window.lod_actions[LodLevel.Medium].isChecked()
    assert not window.lod_actions[LodLevel.UltraHigh].isChecked()


def test_choosing_a_level_drops_the_cached_models_so_they_rebuild(window):
    window._object_models = object()
    window.lod_actions[LodLevel.VeryLow].trigger()
    assert window._object_models is None
    assert window.settings.view.lod_level is LodLevel.VeryLow
