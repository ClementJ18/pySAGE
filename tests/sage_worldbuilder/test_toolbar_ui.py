"""Qt-level tests for the customisable, wrapping main toolbar. Headless via the Qt 'offscreen'
platform; marked `full` like the other desktop suites."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.toolbar import CATALOGUE, DEFAULT_ITEMS, ITEMS_BY_ID  # noqa: E402
from sage_worldbuilder.ui.flow_layout import FlowWidget  # noqa: E402
from sage_worldbuilder.ui.toolbar_dialog import CustomizeToolbarDialog  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def folders(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr("sage_worldbuilder.gamedata.tempfile.gettempdir", lambda: str(tmp_path))
    install = tmp_path / "install"
    (install / "data" / "ini" / "object").mkdir(parents=True)
    (install / "data" / "ini" / "object" / "units.ini").write_text("Object TestUnit\nEnd\n")
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: user)
    return install, user


def make_window(folders, settings=None) -> MainWindow:
    install, _ = folders
    window = MainWindow(settings or Settings(install=str(install)), load_game_data=False)
    window.ask_save_changes = lambda document: "discard"  # type: ignore[method-assign]
    return window


@pytest.fixture
def window(qapp, folders):
    window = make_window(folders)
    yield window
    window.close()


def flush_deletes(qapp: QApplication) -> None:
    """Run the pending `deleteLater`s. `processEvents` alone leaves deferred deletions posted, so
    a test that counts what a rebuild left behind has to ask for them by hand."""
    qapp.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qapp.processEvents()


def strip_widgets(window: MainWindow) -> list[QFrame | QToolButton]:
    """Every widget the toolbar's flow strip currently holds, in layout order."""
    flow = window._toolbar_strip.flow
    widgets = []
    for index in range(flow.count()):
        item = flow.itemAt(index)
        assert item is not None
        widget = item.widget()
        assert widget is not None
        widgets.append(widget)
    return widgets


def test_default_toolbar_matches_default_items(window):
    """The strip's buttons carry the ids of `DEFAULT_ITEMS`, in order, with a separator between
    each pair of consecutive items whose catalogue group differs and nowhere else."""
    widgets = strip_widgets(window)
    ids = tuple(w.property("toolbarItemId") for w in widgets if isinstance(w, QToolButton))
    assert ids == DEFAULT_ITEMS

    # Fold the actual widget sequence down to (item_id, separator_before) pairs, then compare
    # against what the catalogue's groups say the separators should be.
    actual: list[tuple[str, bool]] = []
    pending_separator = False
    for widget in widgets:
        if isinstance(widget, QFrame):
            pending_separator = True
            continue
        assert isinstance(widget, QToolButton)
        actual.append((widget.property("toolbarItemId"), pending_separator))
        pending_separator = False

    expected: list[tuple[str, bool]] = []
    previous_group = None
    for item_id in DEFAULT_ITEMS:
        group = ITEMS_BY_ID[item_id].group
        expected.append((item_id, previous_group is not None and group != previous_group))
        previous_group = group

    assert actual == expected


def test_default_toolbar_actions_match_window_actions(window):
    actions = window._toolbar_actions()
    for widget in strip_widgets(window):
        if isinstance(widget, QToolButton):
            item_id = widget.property("toolbarItemId")
            assert widget.defaultAction() is actions[item_id]


def test_custom_layout_produces_exactly_those_buttons(folders):
    custom = ("save", "jump", "select-tool", "move-tool")
    window = make_window(folders, Settings(install=str(folders[0]), toolbar_items=list(custom)))
    try:
        ids = tuple(
            w.property("toolbarItemId") for w in strip_widgets(window) if isinstance(w, QToolButton)
        )
        assert ids == custom
    finally:
        window.close()


def test_rebuild_replaces_rather_than_duplicates(qapp, window):
    """`_build_toolbar` is what the customisation dialog calls again after the user changes
    `settings.toolbar_items`; it must swap the toolbar's contents in place, not grow a second
    strip alongside the first, and must leave nothing of the old one behind."""
    first_strip = window._toolbar_strip
    window.settings.toolbar_items = ["save", "jump"]
    window._build_toolbar()
    assert window._toolbar_strip is not first_strip
    ids = tuple(
        w.property("toolbarItemId") for w in strip_widgets(window) if isinstance(w, QToolButton)
    )
    assert ids == ("save", "jump")
    # Only the new strip's two buttons are attached to the toolbar's layout: Qt's own (normally
    # hidden) overflow-extension button is the toolbar's only other QToolButton child.
    other_buttons = [
        b
        for b in window.toolbar.findChildren(QToolButton)
        if b.objectName() != "qt_toolbar_ext_button"
    ]
    assert len(other_buttons) == 2

    # Nothing of the old strip survives either: `addWidget` wraps the strip in a QWidgetAction
    # that stays a child of the toolbar until it is deleted by hand, so a rebuild that drops only
    # the widget would pile the actions up one per customisation.
    flush_deletes(qapp)
    assert len(window.toolbar.findChildren(QWidgetAction)) == 1
    assert len(window.toolbar.findChildren(FlowWidget)) == 1


def test_toolbar_context_menu_offers_customize_and_is_not_kept_alive(qapp, window, monkeypatch):
    """Right-clicking the strip, or any button on it, raises Qt's own panels menu with Customize
    Toolbar added on the end. `createPopupMenu` parents that menu to the window, so each one has
    to be dropped again rather than accumulating for the window's whole life."""
    raised: list[QMenu] = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *args: raised.append(self))
    before = len(window.findChildren(QMenu))

    button = next(w for w in strip_widgets(window) if isinstance(w, QToolButton))
    for widget in (window._toolbar_strip, button):
        assert widget.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
        widget.customContextMenuRequested.emit(QPoint(1, 1))

    assert len(raised) == 2
    for menu in raised:
        assert window.customize_toolbar_action in menu.actions()
        assert window.toolbar.toggleViewAction() in menu.actions()

    raised.clear()
    flush_deletes(qapp)
    assert len(window.findChildren(QMenu)) == before


def test_toolbar_wraps_onto_more_rows_when_narrow(qapp, window):
    """Resizing the window - not calling any private layout helper - changes how wide the
    toolbar's flow strip is allowed to be; a narrower window must wrap it onto more rows, taller,
    with every button still present and clickable (no `»` overflow button anywhere)."""
    window.show()
    strip = window._toolbar_strip
    for _ in range(3):
        qapp.processEvents()

    def rows() -> int:
        tops = {w.y() for w in strip_widgets(window) if isinstance(w, QToolButton)}
        return len(tops)

    window.resize(6000, 900)
    for _ in range(3):
        qapp.processEvents()
    wide_width, wide_height, wide_rows = strip.width(), strip.height(), rows()

    window.resize(window.minimumWidth() or 200, 900)
    for _ in range(3):
        qapp.processEvents()
    narrow_width, narrow_height, narrow_rows = strip.width(), strip.height(), rows()

    print(f"wide: strip width={wide_width} height={wide_height} rows={wide_rows}")
    print(f"narrow: strip width={narrow_width} height={narrow_height} rows={narrow_rows}")

    assert narrow_width < wide_width
    # The strip is taller because the buttons sit on more rows, not merely because something
    # stretched: each row of buttons has its own top edge.
    assert narrow_rows > wide_rows >= 1
    assert narrow_height > wide_height

    # No `»` overflow button: the toolbar's own action list holds only the one widget action
    # wrapping the flow strip, never the QToolBarExtension Qt adds when it hides overflow.
    extension = window.toolbar.findChild(QWidget, "qt_toolbar_ext_button")
    assert extension is None or not extension.isVisible()

    visible_ids = {
        w.property("toolbarItemId") for w in strip_widgets(window) if isinstance(w, QToolButton)
    }
    assert visible_ids == set(DEFAULT_ITEMS)
    for widget in strip_widgets(window):
        if isinstance(widget, QToolButton):
            # Not hidden and actually given real screen space, i.e. clickable - regardless of
            # whether the action itself happens to be enabled right now (many start disabled
            # until there is a document, which is a document-state question, not a layout one).
            assert not widget.isHidden()
            assert widget.width() > 0
            assert widget.height() > 0


def test_every_catalogue_id_is_wired_to_a_window_action(window):
    """The catalogue and `_toolbar_actions` must name exactly the same ids: an id in only one of
    them is an item the dialog offers and the toolbar then silently skips, or an action no user
    can ever choose."""
    actions = window._toolbar_actions()
    assert set(actions) == {item.id for item in CATALOGUE}


def _all_ids_in_order(dialog: CustomizeToolbarDialog) -> list[str]:
    ids = []
    for row in range(dialog.list.count()):
        item = dialog.list.item(row)
        assert item is not None
        ids.append(item.data(Qt.ItemDataRole.UserRole))
    return ids


def _checked_ids(dialog: CustomizeToolbarDialog) -> list[str]:
    ids = []
    for row in range(dialog.list.count()):
        item = dialog.list.item(row)
        assert item is not None
        if item.checkState() == Qt.CheckState.Checked:
            ids.append(item.data(Qt.ItemDataRole.UserRole))
    return ids


def _find_button(dialog: CustomizeToolbarDialog, text: str) -> QPushButton:
    for button in dialog.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"no button labelled {text!r}")


def test_dialog_opens_prefilled_from_current_layout(window):
    """Items on the toolbar today come first, checked, in toolbar order; every other catalogue
    item follows, unchecked, in catalogue order."""
    custom = ("save", "jump", "select-tool")
    window.settings.toolbar_items = list(custom)
    dialog = CustomizeToolbarDialog(window.settings.toolbar_layout(), window)
    try:
        assert dialog.list.count() == len(CATALOGUE)
        ids = _all_ids_in_order(dialog)
        assert tuple(ids[: len(custom)]) == custom
        assert set(ids[len(custom) :]) == {item.id for item in CATALOGUE} - set(custom)
        assert _checked_ids(dialog) == list(custom)
        assert dialog.chosen_ids() == list(custom)
    finally:
        dialog.deleteLater()


def test_unchecking_an_item_removes_it_and_persists(window, monkeypatch):
    def uncheck_save_and_accept(dialog):
        for row in range(dialog.list.count()):
            item = dialog.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == "save":
                item.setCheckState(Qt.CheckState.Unchecked)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.CustomizeToolbarDialog.exec", uncheck_save_and_accept
    )
    window.edit_toolbar_layout()

    ids = tuple(
        w.property("toolbarItemId") for w in strip_widgets(window) if isinstance(w, QToolButton)
    )
    assert "save" not in ids
    assert ids == tuple(item_id for item_id in DEFAULT_ITEMS if item_id != "save")
    assert window.settings.toolbar_items == list(ids)

    reloaded = Settings.from_dict(window.settings.to_dict())
    assert reloaded.toolbar_items == window.settings.toolbar_items
    assert reloaded.toolbar_layout() == tuple(ids)


def test_move_up_button_reorders_the_layout_and_the_toolbar_follows(window, monkeypatch):
    def move_second_item_up(dialog):
        dialog.list.setCurrentRow(1)
        _find_button(dialog, "Move Up").click()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.CustomizeToolbarDialog.exec", move_second_item_up
    )
    window.edit_toolbar_layout()

    expected = list(DEFAULT_ITEMS)
    expected[0], expected[1] = expected[1], expected[0]
    ids = tuple(
        w.property("toolbarItemId") for w in strip_widgets(window) if isinstance(w, QToolButton)
    )
    assert ids == tuple(expected)
    assert window.settings.toolbar_items == expected


def test_restore_defaults_button_returns_default_items_and_stores_none(window, monkeypatch):
    window.settings.toolbar_items = ["save", "jump"]

    def restore_and_accept(dialog):
        assert dialog.chosen_ids() == ["save", "jump"]
        box = dialog.findChild(QDialogButtonBox)
        assert box is not None
        restore = box.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        assert restore is not None
        restore.click()
        assert dialog.chosen_ids() == list(DEFAULT_ITEMS)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.CustomizeToolbarDialog.exec", restore_and_accept
    )
    window.edit_toolbar_layout()

    assert window.settings.toolbar_items is None
    ids = tuple(
        w.property("toolbarItemId") for w in strip_widgets(window) if isinstance(w, QToolButton)
    )
    assert ids == DEFAULT_ITEMS


def test_empty_selection_yields_an_empty_toolbar_without_crashing(window, monkeypatch):
    def uncheck_everything_and_accept(dialog):
        for row in range(dialog.list.count()):
            item = dialog.list.item(row)
            item.setCheckState(Qt.CheckState.Unchecked)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.CustomizeToolbarDialog.exec", uncheck_everything_and_accept
    )
    window.edit_toolbar_layout()

    assert window.settings.toolbar_items == []
    assert strip_widgets(window) == []

    reloaded = Settings.from_dict(window.settings.to_dict())
    assert reloaded.toolbar_items == []
    assert reloaded.toolbar_layout() == ()
