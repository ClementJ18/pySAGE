"""Qt-level tests for the export and import dialogs. Headless via the Qt 'offscreen' platform."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder.exchange import ExportOptions, ScriptsMode  # noqa: E402
from sage_worldbuilder.heightmap_io import Anchor  # noqa: E402
from sage_worldbuilder.ui.exchange_dialogs import ExportOptionsDialog, ReanchorDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_export_options_read_back_what_was_chosen(qapp):
    players = [("", "Neutral"), ("PlyrGood", "Men of the West")]
    dialog = ExportOptionsDialog(
        players, ExportOptions(players=frozenset({"PlyrGood"})), has_selected_scripts=False
    )

    assert dialog.players.item(0).text() == "(neutral)"
    assert dialog.players.item(1).text() == 'PlyrGood="Men of the West"'
    assert dialog.players.item(1).checkState() == Qt.CheckState.Checked
    # Export selected scripts needs something selected in the tree.
    assert not dialog.scripts.button(int(ScriptsMode.SELECTED)).isEnabled()

    dialog.includes["water"].setChecked(True)
    dialog.includes["terrain_height"].setChecked(True)
    dialog.referenced["referenced_objects"].setChecked(False)
    dialog.scripts.button(int(ScriptsMode.NONE)).setChecked(True)
    dialog.players.item(0).setCheckState(Qt.CheckState.Checked)

    options = dialog.options()

    assert options.water and options.terrain_height and not options.terrain_texture
    assert not options.referenced_objects and options.referenced_areas
    assert options.scripts is ScriptsMode.NONE
    assert options.players == frozenset({"", "PlyrGood"})


def test_reanchor_shows_both_sizes_and_returns_the_anchor(qapp):
    dialog = ReanchorDialog((32, 32), (64, 48))

    assert dialog.anchor() is Anchor.CENTER
    dialog.anchor_buttons[Anchor.TOP_RIGHT].setChecked(True)
    assert dialog.anchor() is Anchor.TOP_RIGHT
