"""Qt-level tests for the shared sage_utils widgets - the `add_help_menu` help affordance every
SAGE desktop app carries. Headless via the Qt 'offscreen' platform, so no display is needed;
marked `full` (peripheral package, like the other sage_utils/sage_ui Qt suites)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [ui] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QMenu, QTextBrowser  # noqa: E402

from sage_utils.widgets import add_help_menu  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    win = QMainWindow()
    add_help_menu(
        win,
        guide_title="Getting started with the Tool",
        guide_html="<h2>Heading</h2><p>the basic steps go here</p>",
        about_title="About the Tool",
        about_html="<b>the Tool</b><p>what it does</p>",
    )
    return win


def _help_menu(win) -> QMenu:
    return next(m for m in win.menuBar().findChildren(QMenu) if m.title() == "&Help")


def test_help_menu_has_getting_started_and_about(window):
    labels = [action.text() for action in _help_menu(window).actions() if action.text()]
    assert "&Getting started…" in labels
    assert "&About the Tool" in labels


def test_getting_started_opens_a_dialog_with_the_guide_text(window):
    action = next(a for a in _help_menu(window).actions() if "Getting started" in a.text())
    action.trigger()

    dialog = window._help_dialog
    assert isinstance(dialog, QDialog)
    assert dialog.isVisible()
    assert dialog.windowTitle() == "Getting started with the Tool"
    assert "the basic steps go here" in dialog.findChild(QTextBrowser).toPlainText()


def test_getting_started_dialog_is_reused_across_openings(window):
    # Cached on the window so it keeps its scroll position rather than resetting each open.
    action = next(a for a in _help_menu(window).actions() if "Getting started" in a.text())
    action.trigger()
    first = window._help_dialog
    action.trigger()

    assert window._help_dialog is first
