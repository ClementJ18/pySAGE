"""Qt-level tests for the shared sage_utils widgets - the `add_help_menu` help affordance every
SAGE desktop app carries. Headless via the Qt 'offscreen' platform, so no display is needed;
marked `full` (peripheral package, like the other sage_utils/sage_ui Qt suites)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [ui] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
)

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


def test_no_report_entry_where_the_app_does_not_name_itself(window):
    # `window` is built without `report_app`: an app that has not opted in gets no entry rather
    # than one that files reports against nothing in particular.
    labels = [action.text() for action in _help_menu(window).actions() if action.text()]
    assert not [label for label in labels if "Report" in label]


def _reporting_window(state=None) -> QMainWindow:
    win = QMainWindow()
    add_help_menu(
        win,
        guide_title="Getting started with the Tool",
        guide_html="<p>the basic steps</p>",
        about_title="About the Tool",
        about_html="<b>the Tool</b>",
        report_app="The Tool",
        report_state=state,
    )
    return win


def _report_dialog(win: QMainWindow) -> QDialog:
    action = next(a for a in _help_menu(win).actions() if "Report a bug" in a.text())
    action.trigger()
    return win._bug_report_dialog


def test_report_a_bug_opens_a_report_carrying_the_build_and_the_app_state(qapp):
    win = _reporting_window(lambda: {"Map": "maps/Moria/Moria.map"})

    text = _report_dialog(win).findChild(QPlainTextEdit).toPlainText()

    assert "- **App:** The Tool" in text
    assert "- **Map:** maps/Moria/Moria.map" in text


def test_state_that_cannot_be_read_still_gives_a_report(qapp):
    # Whatever went wrong, the report is the way out of it: collecting the state must never be
    # the thing that fails.
    def broken() -> dict[str, str]:
        raise RuntimeError("the panel is mid-collapse")

    win = _reporting_window(broken)

    text = _report_dialog(win).findChild(QPlainTextEdit).toPlainText()

    assert "the panel is mid-collapse" in text
    assert "- **App:** The Tool" in text


def test_copying_the_report_puts_the_edited_text_on_the_clipboard(qapp):
    win = _reporting_window()
    dialog = _report_dialog(win)
    editor = dialog.findChild(QPlainTextEdit)
    editor.setPlainText("what I was doing when it broke")

    next(b for b in dialog.findChildren(QPushButton) if "Copy" in b.text()).click()

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == "what I was doing when it broke"


def test_getting_started_dialog_is_reused_across_openings(window):
    # Cached on the window so it keeps its scroll position rather than resetting each open.
    action = next(a for a in _help_menu(window).actions() if "Getting started" in a.text())
    action.trigger()
    first = window._help_dialog
    action.trigger()

    assert window._help_dialog is first
