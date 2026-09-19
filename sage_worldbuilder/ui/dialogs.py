"""The shell's dialogs: open and save a map by WorldBuilder's categories, the game settings, and
the keyboard shortcut reference."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_utils.installs import find_install
from sage_worldbuilder.autosave import MIN_INTERVAL_SECONDS
from sage_worldbuilder.categories import MapCategory, MapEntry
from sage_worldbuilder.gamedata import GameContext
from sage_worldbuilder.keymap import Accelerator
from sage_worldbuilder.settings import Settings, same_folder

__all__ = ["GameSettingsDialog", "OpenMapDialog", "SaveMapDialog", "ShortcutsDialog"]

MAP_FILTER = "Maps (*.map *.bse);;All files (*)"
SAGEPATCH_FILTER = "Engine patches (*.sagepatch);;All files (*)"
_INVALID_NAME_CHARACTERS = frozenset('<>:"/\\|?*')
_MAX_INTERVAL_SECONDS = 3600


class _CategoryPicker(QWidget):
    """The six category radio buttons both map dialogs share."""

    def __init__(self, initial: MapCategory, on_change, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        self._group = QButtonGroup(self)
        self.buttons: dict[MapCategory, QRadioButton] = {}
        for index, category in enumerate(MapCategory):
            button = QRadioButton(category.label)
            self._group.addButton(button)
            grid.addWidget(button, index // 3, index % 3)
            self.buttons[category] = button
        self.category = initial
        self._on_change = on_change
        self.buttons[initial].setChecked(True)
        for category, button in self.buttons.items():
            button.toggled.connect(
                lambda checked, category=category: self._select(category, checked)
            )

    def _select(self, category: MapCategory, checked: bool) -> None:
        if checked:
            self.category = category
            self._on_change()


class OpenMapDialog(QDialog):
    """Pick a map from a category, or browse to any file."""

    def __init__(
        self,
        context: GameContext | None,
        parent: QWidget | None = None,
        category: MapCategory = MapCategory.USER,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open Map")
        self.resize(540, 580)
        self.context = context
        self.selected: MapEntry | None = None
        self.browsed: Path | None = None

        layout = QVBoxLayout(self)
        self.picker = _CategoryPicker(category, self._populate)
        layout.addWidget(self.picker)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by name")
        self.filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        self.list.currentItemChanged.connect(lambda *_: self._sync_buttons())
        layout.addWidget(self.list, 1)
        self.status = QLabel()
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel
        )
        self.open_button = buttons.button(QDialogButtonBox.StandardButton.Open)
        browse = buttons.addButton("Browse…", QDialogButtonBox.ButtonRole.ActionRole)
        if browse is not None:
            browse.clicked.connect(self._browse)
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    def _populate(self) -> None:
        self.list.clear()
        category = self.picker.category
        if self.context is None:
            self.status.setText("No game install is set, so only Browse… can open a map.")
            entries: list[MapEntry] = []
        else:
            entries = self.context.maps(category)
            self.status.setText(f"{len(entries)} map(s) in {category.label}")
        for entry in entries:
            suffix = "   (in an archive: opens read-only)" if entry.read_only else ""
            item = QListWidgetItem(entry.name + suffix)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
        self._apply_filter(self.filter.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold()
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is not None:
                item.setHidden(needle not in item.text().casefold())
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        item = self.list.currentItem()
        if self.open_button is not None:
            self.open_button.setEnabled(item is not None and not item.isHidden())

    def _accept_selection(self) -> None:
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return
        self.selected = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Map", "", MAP_FILTER)
        if path:
            self.browsed = Path(path)
            self.accept()


class SaveMapDialog(QDialog):
    """Name the map and pick its category, or browse to any file."""

    def __init__(
        self,
        context: GameContext | None,
        name: str,
        *,
        compressed: bool,
        parent: QWidget | None = None,
        category: MapCategory = MapCategory.USER,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Map As")
        self.resize(540, 260)
        self.context = context
        self.target: Path | None = None
        self.compress = compressed

        layout = QVBoxLayout(self)
        self.picker = _CategoryPicker(category, self._update)
        layout.addWidget(self.picker)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.textChanged.connect(lambda _text: self._update())
        form.addRow("Map name", self.name)
        self.compress_box = QCheckBox("Compress (RefPack), as the game's own maps are")
        self.compress_box.setChecked(compressed)
        form.addRow("", self.compress_box)
        layout.addLayout(form)
        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        browse = buttons.addButton("Browse…", QDialogButtonBox.ButtonRole.ActionRole)
        if browse is not None:
            browse.clicked.connect(self._browse)
        buttons.accepted.connect(self._accept_target)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update()

    def _category_target(self) -> tuple[Path | None, str]:
        category = self.picker.category
        name = self.name.text().strip()
        if self.context is None:
            return None, "No game install is set, so only Browse… can pick where to save."
        if self.context.save_root(category) is None:
            if category is MapCategory.USER:
                return None, "The game's user-data folder was not found; use Browse…."
            return None, f"{category.label} are saved into a mod folder: set one in Game Settings."
        if not name or any(character in _INVALID_NAME_CHARACTERS for character in name):
            return None, 'Enter a map name (it becomes a folder name, so no \\ / : * ? " < > |).'
        path = self.context.save_path(category, name)
        return path, f"Saves to {path}"

    def _update(self) -> None:
        target, message = self._category_target()
        self.path_label.setText(message)
        if self.save_button is not None:
            self.save_button.setEnabled(target is not None)

    def _accept_target(self) -> None:
        target, _ = self._category_target()
        if target is None:
            return
        self.target = target
        self.compress = self.compress_box.isChecked()
        self.accept()

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Map As", f"{self.name.text().strip() or 'map'}.map", MAP_FILTER
        )
        if path:
            self.target = Path(path)
            self.compress = self.compress_box.isChecked()
            self.accept()


class GameSettingsDialog(QDialog):
    """The install and mod folders to read, and the autosave options."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Game Settings")
        self.resize(620, 400)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.install_edit = QLineEdit(settings.install or "")
        self.install_edit.setPlaceholderText("Detected automatically when empty")
        detect = QPushButton("Detect")
        detect.clicked.connect(self._detect)
        form.addRow("Game install", self._folder_row(self.install_edit, detect))

        self.mods_list = QListWidget()
        self.mods_list.addItems(settings.mods)
        self.mods_list.setToolTip("None: the install alone")
        form.addRow("Mod folders", self._mods_row())
        hint = QLabel("Loaded top to bottom: a mod lower in the list wins over the ones above it.")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self.sagepatch_edit = QLineEdit(settings.sagepatch or "")
        self.sagepatch_edit.setPlaceholderText("None: the stock game.dat")
        browse_patch = QPushButton("Browse…")
        browse_patch.clicked.connect(self._browse_sagepatch)
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.sagepatch_edit, 1)
        box.addWidget(browse_patch)
        form.addRow("Engine patches", row)

        self.autosave_box = QCheckBox("Autosave unsaved changes")
        self.autosave_box.setChecked(settings.autosave_enabled)
        form.addRow("", self.autosave_box)
        self.interval = QSpinBox()
        self.interval.setRange(MIN_INTERVAL_SECONDS, _MAX_INTERVAL_SECONDS)
        self.interval.setSuffix(" s")
        self.interval.setValue(settings.autosave_interval_seconds)
        form.addRow("Autosave every", self.interval)

        layout.addLayout(form)

        self.message = QLabel()
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _folder_row(self, edit: QLineEdit, *extra: QPushButton) -> QWidget:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_into(edit))
        box.addWidget(browse)
        for button in extra:
            box.addWidget(button)
        return row

    def _mods_row(self) -> QWidget:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.mods_list, 1)
        column = QVBoxLayout()
        for text, handler in (
            ("Add…", self.add_mod),
            ("Remove", self.remove_mod),
            ("Move Up", lambda: self.move_mod(-1)),
            ("Move Down", lambda: self.move_mod(1)),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, handler=handler: handler())
            column.addWidget(button)
        column.addStretch(1)
        box.addLayout(column)
        return row

    def add_mod(self, folder: str | None = None) -> None:
        """Add `folder` (chosen in a folder dialog when `None`) at the bottom of the load order,
        where it wins over the others; one already listed moves there."""
        if folder is None:
            start = self.mods[-1] if self.mods else ""
            folder = QFileDialog.getExistingDirectory(self, "Add Mod Folder", start)
            if not folder:
                return
        for row in reversed(range(self.mods_list.count())):
            item = self.mods_list.item(row)
            if item is not None and same_folder(item.text(), folder):
                self.mods_list.takeItem(row)
        self.mods_list.addItem(folder)
        self.mods_list.setCurrentRow(self.mods_list.count() - 1)

    def remove_mod(self) -> None:
        row = self.mods_list.currentRow()
        if row >= 0:
            self.mods_list.takeItem(row)

    def move_mod(self, step: int) -> None:
        row = self.mods_list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.mods_list.count():
            return
        item = self.mods_list.takeItem(row)
        self.mods_list.insertItem(target, item)
        self.mods_list.setCurrentRow(target)

    def _browse_sagepatch(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose .sagepatch", self.sagepatch_edit.text(), SAGEPATCH_FILTER
        )
        if path:
            self.sagepatch_edit.setText(path)

    def _browse_into(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Folder", edit.text())
        if folder:
            edit.setText(folder)

    def _detect(self) -> None:
        install = find_install("rotwk")
        if install is None:
            self.message.setText("No installed game was found; browse to it instead.")
            return
        self.install_edit.setText(str(install.path))
        self.message.setText(f"Found {install.title}.")

    @property
    def install(self) -> str | None:
        return self.install_edit.text().strip() or None

    @property
    def mods(self) -> list[str]:
        """The listed mod folders, in load order."""
        items = (self.mods_list.item(row) for row in range(self.mods_list.count()))
        return [item.text() for item in items if item is not None]

    @property
    def sagepatch(self) -> str | None:
        return self.sagepatch_edit.text().strip() or None

    @property
    def autosave_enabled(self) -> bool:
        return self.autosave_box.isChecked()

    @property
    def autosave_interval(self) -> int:
        return self.interval.value()


class ShortcutsDialog(QDialog):
    """Every WorldBuilder shortcut, and whether the command behind it exists here yet."""

    def __init__(
        self,
        rows: Iterable[Accelerator],
        available: set[int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(640, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "The shortcuts are WorldBuilder's own. A command not built yet keeps its key "
                "reserved for when it arrives."
            )
        )
        ordered = sorted(rows, key=lambda row: ((row.menu or row.label or "~").lower(), row.keys))
        self.table = QTableWidget(len(ordered), 3)
        self.table.setHorizontalHeaderLabels(["Keys", "Command", "Available"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for index, row in enumerate(ordered):
            command = row.menu or row.label or f"(unlabelled command {row.command})"
            status = "yes" if row.command in available else "not yet"
            for column, text in enumerate((row.keys, command, status)):
                item = QTableWidgetItem(text)
                if row.description:
                    item.setToolTip(row.description)
                self.table.setItem(index, column, item)
        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
