"""Qt-level tests for the MapCache Entry dialog. Headless via the Qt 'offscreen' platform;
marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder.mapcache import escape_text  # noqa: E402
from sage_worldbuilder.ui.mapcache_dialog import MapCacheDialog  # noqa: E402
from tests.sage_worldbuilder.test_mapcache import make_map  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def dialog_for():
    return MapCacheDialog(
        make_map(
            starts=(("Player_1_Start", (10.0, 20.0, 0.0)), ("Player_2_Start", (30.0, 40.0, 0.0))),
        ),
        "x/Green Fields/Green Fields.map",
    )


def rows(dialog) -> dict[str, str]:
    """The block the dialog is showing, as `field -> value`, whatever it aligned it to."""
    lines = dialog.text.toPlainText().splitlines()[1:-1]
    return {
        name.strip(): value.strip() for name, _, value in (line.partition("=") for line in lines)
    }


def test_dialog_shows_the_derived_block(qapp):
    dialog = dialog_for()
    text = dialog.text.toPlainText()
    assert text.splitlines()[0] == "MapCache maps_5Cgreen_20fields_5Cgreen_20fields_2Emap"
    assert text.splitlines()[-1] == "End"
    fields = rows(dialog)
    assert fields["numPlayers"] == "2"
    assert fields["extentMax"] == "X:500.00 Y:500.00 Z:0.00"
    assert dialog.display_name.text() == "$Map:GreenFields"
    # Two starts make it multiplayer, and the file is not there, so its identity reads as zero.
    assert dialog.is_multiplayer.isChecked()
    assert fields["fileSize"] == "0"
    dialog.deleteLater()


def test_edits_reach_the_block(qapp):
    dialog = dialog_for()
    dialog.display_name.setText("Horde: Green Fields")
    dialog.is_official.setChecked(False)
    dialog.is_multiplayer.setChecked(False)
    dialog.map_symbol.setValue(6)

    fields = rows(dialog)
    assert fields["displayName"] == escape_text("Horde: Green Fields")
    assert fields["isOfficial"] == "no"
    assert fields["isMultiplayer"] == "no"
    assert fields["mapSymbol"] == "6"
    dialog.deleteLater()


def test_symbol_zero_leaves_the_field_out(qapp):
    dialog = dialog_for()
    dialog.map_symbol.setValue(3)
    assert "mapSymbol" in rows(dialog)
    dialog.map_symbol.setValue(0)
    assert "mapSymbol" not in rows(dialog)
    dialog.deleteLater()


def test_copy_puts_the_block_on_the_clipboard(qapp):
    dialog = dialog_for()
    dialog.copy()
    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == dialog.entry.text()
    dialog.deleteLater()
