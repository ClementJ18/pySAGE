"""Qt-level tests for the editor shell: opening, editing, undo, saving, prompts, autosave, dialogs
and the background game-data load. Headless via the Qt 'offscreen' platform; marked `full`
(peripheral package, like the other desktop apps' suites)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import time
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtGui import QKeySequence  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from sage_ini.engine import STOCK, active, revert  # noqa: E402
from sage_ini.model.objects import REGISTRY  # noqa: E402
from sage_map.map import Map, parse_map_from_path  # noqa: E402
from sage_worldbuilder import (  # noqa: E402
    Change,
    ChangeKind,
    MapCategory,
    MapDocument,
    SetAttribute,
)
from sage_worldbuilder.keymap import accelerators  # noqa: E402
from sage_worldbuilder.settings import RecentMap, Settings  # noqa: E402
from sage_worldbuilder.ui.dialogs import OpenMapDialog, SaveMapDialog  # noqa: E402
from sage_worldbuilder.ui.window import APP_TITLE, MainWindow  # noqa: E402


@dataclass
class Target:
    value: int = 0


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


def make_window(folders, *, load: bool = False) -> MainWindow:
    install, _ = folders
    window = MainWindow(Settings(install=str(install)), load_game_data=load)
    window.ask_save_changes = lambda document: "discard"  # type: ignore[method-assign]
    return window


@pytest.fixture
def window(qapp, folders):
    window = make_window(folders)
    yield window
    window.close()


def wait_until(qapp, condition, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the window")
        qapp.processEvents()
        time.sleep(0.01)


def saved_map(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    MapDocument(Map()).save(path, compress=False)
    return path


def edit(window: MainWindow, value: int = 1) -> None:
    assert window.document is not None
    window.document.execute(SetAttribute(Target(), "value", value, Change(ChangeKind.SETTINGS)))


def test_starts_empty(window, folders):
    _, user = folders
    assert window.windowTitle() == APP_TITLE
    assert not window.save_action.isEnabled()
    assert not window.undo_action.isEnabled()
    assert window.context is not None
    assert window.autosaver is not None and window.autosaver.folder == user


def make_mod(folders, name: str = "mod") -> Path:
    install, _ = folders
    mod = install.parent / name
    (mod / "data" / "ini" / "object").mkdir(parents=True)
    (mod / "data" / "ini" / "object" / f"{name}_units.ini").write_text("Object ModUnit\nEnd\n")
    return mod


def test_load_and_unload_a_mod_before_any_map(window, folders):
    mod = make_mod(folders)
    assert window.document is None
    assert window.load_mod_action.isEnabled()
    assert not window.unload_mod_action.isEnabled()

    window.load_mod(mod)
    assert window.context is not None and window.context.layers.mods == (mod,)
    assert window.settings.mods == [str(mod)]
    assert window.settings.recent_mods == [str(mod)]
    assert window.unload_mod_action.isEnabled()
    checked = [action for action in window.recent_mods_menu.actions() if action.isChecked()]
    assert len(checked) == 1 and str(mod) in checked[0].text()

    window.unload_mod_action.trigger()
    assert window.context is not None and window.context.layers.mods == ()
    assert window.settings.mods == []
    assert window.settings.recent_mods == [str(mod)]  # still offered
    assert not window.unload_mod_action.isEnabled()


def test_several_mods_load_in_order_and_unload_one_at_a_time(window, folders):
    first, second = make_mod(folders, "first"), make_mod(folders, "second")
    window.load_mod(first)
    window.load_mod(second)
    assert window.context is not None and window.context.layers.mods == (first, second)
    labels = [action.text() for action in window.recent_mods_menu.actions() if action.isChecked()]
    assert any(str(first) in label and "loaded 1 of 2" in label for label in labels)
    assert any(str(second) in label and "loaded 2 of 2" in label for label in labels)

    window.load_mod(first)  # loading one again moves it on top
    assert window.context.layers.mods == (second, first)

    window.toggle_mod(second)
    assert window.context is not None and window.context.layers.mods == (first,)
    window.toggle_mod(second)
    assert window.context is not None and window.context.layers.mods == (first, second)

    window.unload_all_mods()
    assert window.settings.mods == []


def test_game_settings_reorder_the_mods(window, folders, monkeypatch):
    first, second = make_mod(folders, "first"), make_mod(folders, "second")
    window.load_mod(first)
    window.load_mod(second)

    def reorder(dialog):
        dialog.mods_list.setCurrentRow(1)
        dialog.move_mod(-1)
        dialog.add_mod(str(first).upper())  # already listed: moves to the bottom, not doubled
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr("sage_worldbuilder.ui.window.GameSettingsDialog.exec", reorder)
    window.edit_game_settings()
    assert window.settings.mods == [str(second), str(first).upper()]
    assert window.context is not None and len(window.context.layers.mods) == 2


def test_load_and_unload_a_sagepatch(window, folders, qapp):
    install, _ = folders
    (install / "data" / "ini" / "object" / "units.ini").write_text(
        "Object TestUnit\n  PatchedPool = 3\nEnd\n"
    )
    sagepatch = install.parent / ".sagepatch"
    sagepatch.write_text(
        'version = 3\n\n[[patches]]\nname = "multi-mod"\n\n'
        '[[fields]]\nblock = "Object"\nname = "PatchedPool"\ntype = "Int"\n',
        encoding="utf-8",
    )
    assert not window.unload_sagepatch_action.isEnabled()
    try:
        window.load_sagepatch(sagepatch)
        assert window.settings.sagepatch == str(sagepatch)
        assert window.context is not None
        assert [patch.name for patch in window.context.engine.patches] == ["multi-mod"]
        assert "PatchedPool" in REGISTRY["Object"]._fieldspec
        wait_until(qapp, lambda: window.context is not None and window.context.game is not None)
        assert window.context.game.objects["TestUnit"].PatchedPool == 3
        assert "1 engine patch)" in window.game_label.text()
        assert window.unload_sagepatch_action.isEnabled()

        window.unload_sagepatch_action.trigger()
        assert window.settings.sagepatch is None
        assert active() is STOCK
        assert not window.unload_sagepatch_action.isEnabled()
    finally:
        revert()


def test_jump_to_game_applies_the_sagepatch_patches(window, folders, monkeypatch, tmp_path):
    install, _ = folders
    sagepatch = tmp_path / ".sagepatch"
    sagepatch.write_text('version = 3\n\n[[patches]]\nname = "multi-mod"\n', encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.patch_for_launch",
        lambda game_dat, extra=(): calls.append((game_dat, extra)) or False,
    )
    monkeypatch.setattr(MainWindow, "launch_game", lambda self, arguments, directory: None)
    try:
        window.load_sagepatch(sagepatch)
        path = saved_map(tmp_path / "user_maps" / "Fords" / "Fords.map")
        window._set_document(MapDocument.open(path))
        window.jump_to_game()
    finally:
        revert()
    assert len(calls) == 1 and calls[0][0] == install / "game.dat"
    assert [patch.name for patch in calls[0][1]] == ["multi-mod"]


def test_missing_recent_mod_is_forgotten(window, folders, monkeypatch):
    install, _ = folders
    gone = str(install.parent / "gone")
    window.settings.add_recent_mod(gone)
    monkeypatch.setattr("sage_worldbuilder.ui.window.QMessageBox.warning", lambda *args: None)

    window.load_mod(Path(gone))
    assert window.settings.recent_mods == []
    assert window.settings.mods == []


def test_command_line_mod_loads_with_the_game(qapp, folders):
    install, _ = folders
    mod = make_mod(folders)
    window = MainWindow(Settings(install=str(install)), load_game_data=True, mods=[mod])
    try:
        assert window.context is not None and window.context.layers.mods == (mod,)
        wait_until(qapp, lambda: window.context is not None and window.context.game is not None)
        assert "ModUnit" in window.context.game.objects
        assert "TestUnit" in window.context.game.objects
        assert "mod mod" in window.game_label.text()
    finally:
        window.close()


class RecordingView:
    """Stands in for the 3D view (which needs OpenGL), recording what the window asks of it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: self.calls.append(name)


def test_new_game_data_drops_the_3d_views_art(qapp, folders):
    window = make_window(folders)
    try:
        view = RecordingView()
        window.map_view_3d = view  # type: ignore[assignment]
        window.load_mod(make_mod(folders))
        wait_until(qapp, lambda: window.context is not None and window.context.game is not None)
        assert "reload_art" in view.calls
    finally:
        window.map_view_3d = None
        window.close()


def test_open_edit_undo_redo_save(window, folders, qapp):
    _, user = folders
    path = saved_map(user / "Maps" / "Mine" / "Mine.map")
    window.open_path(path)
    wait_until(qapp, lambda: not window.busy and window.document is not None)

    assert "Mine" in window.windowTitle()
    edit(window)
    assert window.isWindowModified()
    assert window.undo_action.isEnabled()
    assert window.undo_action.text() == "&Undo Set value"

    window.undo_action.trigger()
    assert not window.isWindowModified()
    window.redo_action.trigger()
    assert window.isWindowModified()

    window.save_action.trigger()
    wait_until(qapp, lambda: not window.busy)
    assert not window.isWindowModified()
    assert parse_map_from_path(path) is not None
    assert window.settings.recent[0] == RecentMap("file", str(path))
    assert window.recent_menu.actions()


def test_shortcuts_are_worldbuilders(window):
    assert "Ctrl+Z" in [sequence.toString() for sequence in window.undo_action.shortcuts()]
    for row in accelerators():
        assert not QKeySequence(row.keys).isEmpty(), row.keys


def _menu_named(menu, title: str):
    for action in menu.actions():
        if action.text() == title:
            assert action.menu() is not None, title
            return action.menu()
    raise AssertionError(f"no {title} submenu")


def view_menu(window):
    bar = window.menuBar()
    menu = next(action.menu() for action in bar.actions() if action.text() == "&View")
    assert menu is not None
    return menu


def test_the_view_menu_is_grouped_into_submenus(window):
    menu = view_menu(window)
    entries = [action for action in menu.actions() if not action.isSeparator()]
    assert len(entries) <= 12, [action.text() for action in entries]
    # Every show/hide toggle sits in one of the submenus, and none is lost on the way.
    placed = [
        action
        for entry in entries
        for action in (entry.menu().actions() if entry.menu() is not None else [entry])
    ]
    for name, action in window.view_actions.items():
        assert placed.count(action) == 1, name
    panels = _menu_named(menu, "&Panels")
    assert window.status_bar_action in panels.actions()
    for dock in window._docks():
        assert dock.toggleViewAction() in panels.actions(), dock.windowTitle()


def test_saving_a_map_without_a_file_goes_to_save_as(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "save_as", lambda then=None: calls.append(then))
    window._set_document(MapDocument(Map(), read_only=True, name="Packed"))

    window.save_action.trigger()

    assert calls == [None]
    assert "Packed (read-only)" in window.windowTitle()


def test_close_respects_the_unsaved_changes_answer(window):
    window._set_document(MapDocument(Map()))
    edit(window)

    window.ask_save_changes = lambda document: "cancel"
    assert not window.close()
    window.ask_save_changes = lambda document: "discard"
    assert window.close()


def test_autosave_writes_into_user_data(window, folders):
    _, user = folders
    window._set_document(MapDocument(Map()))
    edit(window)

    window.autosave()

    assert (user / "WorldBuilderAutoSave1.map").is_file()


def test_map_dialogs_follow_categories(window, folders, qapp):
    _, user = folders
    saved_map(user / "Maps" / "Mine" / "Mine.map")

    dialog = OpenMapDialog(window.context, window)
    assert dialog.list.count() == 1
    dialog.picker.buttons[MapCategory.SYSTEM].setChecked(True)
    assert dialog.list.count() == 0

    save = SaveMapDialog(window.context, "New", compressed=True, parent=window)
    assert save.save_button is not None and save.save_button.isEnabled()
    save.picker.buttons[MapCategory.LIBRARIES].setChecked(True)
    assert not save.save_button.isEnabled()  # no mod folder to write into


def test_reset_layout_and_cursor_readout(window):
    window.map_dock.hide()
    window.reset_layout()
    assert not window.map_dock.isHidden()

    window.show_cursor((3, 4), 12.5)
    assert window.cell_label.text() == "Cell: 3, 4"
    assert window.height_label.text() == "Height: 12 (0.5 ft)"


def test_game_data_loads_in_the_background(qapp, folders):
    window = make_window(folders, load=True)
    try:
        wait_until(qapp, lambda: window.context is not None and window.context.game is not None)
        assert "TestUnit" in window.context.game.objects
        assert "Loaded" in window.game_label.text()
    finally:
        window.close()
