"""The Object Palette: WorldBuilder's Object Selection panel. Pick the object Place Object puts
down, the team it will belong to, and its height above the terrain.

Replace Selected asks for its replacement in a dialog over the same searchable tree."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.palette import Palette, filter_palette, object_palette
from sage_worldbuilder.teams import qualified_team_name, team_list
from sage_worldbuilder.ui.host import PanelHost

__all__ = ["ObjectPalettePanel", "ObjectTree", "ReplaceObjectDialog"]

_NAME_ROLE = Qt.ItemDataRole.UserRole
# The neutral player's team, which a new object belongs to unless another is chosen.
NEUTRAL_TEAM = "/team"
_HEIGHT_LIMIT = 10000.0


class ObjectTree(QWidget):
    """The palette's search box and tree: a branch per side, and under it one per editor sorting."""

    # The object name clicked in the tree.
    chosen = pyqtSignal(str)
    # The object name double-clicked, or picked with Enter.
    activated = pyqtSignal(str)
    # The object name under the cursor changed, by mouse or keyboard ("" on a heading or nothing).
    current_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._groups: Palette | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search objects")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._fill_tree())
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(lambda item, _column: self._emit(self.chosen, item))
        self.tree.itemActivated.connect(lambda item, _column: self._emit(self.activated, item))
        self.tree.currentItemChanged.connect(
            lambda _item, _previous: self.current_changed.emit(self.current() or "")
        )
        layout.addWidget(self.tree, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._fill_tree()

    def palette(self) -> Palette | None:
        return self._groups

    def set_palette(self, groups: Palette | None) -> None:
        """Show `groups`; None while the game data has not loaded."""
        self._groups = groups
        self._fill_tree()

    def current(self) -> str | None:
        """The object name under the tree's cursor; None on a heading or nothing."""
        item = self.tree.currentItem()
        name = item.data(0, _NAME_ROLE) if item is not None else None
        return name if isinstance(name, str) else None

    def select(self, name: str) -> bool:
        """Put the cursor on `name`, opening its branches; False when the tree does not show it."""
        for item in _leaves(self.tree):
            if item.data(0, _NAME_ROLE) == name:
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return True
        return False

    def _fill_tree(self) -> None:
        self.tree.clear()
        if self._groups is None:
            self.status.setText("The object list appears once the game data has loaded.")
            return
        groups = filter_palette(self._groups, self.search.text())
        searching = bool(self.search.text().strip())
        count = 0
        for side, categories in groups.items():
            total = sum(len(names) for names in categories.values())
            count += total
            branch = _heading(f"{side} ({total})")
            self.tree.addTopLevelItem(branch)
            for label, names in categories.items():
                heading = _heading(f"{label} ({len(names)})")
                branch.addChild(heading)
                for name in names:
                    leaf = QTreeWidgetItem([name])
                    leaf.setData(0, _NAME_ROLE, name)
                    heading.addChild(leaf)
                heading.setExpanded(searching)
            branch.setExpanded(searching)
        self.status.setText(f"{count} object(s)")

    @staticmethod
    def _emit(signal: pyqtSignal, item: QTreeWidgetItem) -> None:
        name = item.data(0, _NAME_ROLE)
        if isinstance(name, str):
            signal.emit(name)  # type: ignore[attr-defined]


class ObjectPalettePanel(QWidget):
    # The object name chosen in the tree.
    template_chosen = pyqtSignal(str)

    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._template: str | None = None
        self._game: object = None
        layout = QVBoxLayout(self)
        self.objects = ObjectTree()
        self.objects.chosen.connect(self._clicked)
        layout.addWidget(self.objects, 1)
        form = QFormLayout()
        self.chosen = QLabel("-")
        form.addRow("Object", self.chosen)
        self.owner = QComboBox()
        form.addRow("Default owner", self.owner)
        self.height_offset = QDoubleSpinBox()
        self.height_offset.setRange(-_HEIGHT_LIMIT, _HEIGHT_LIMIT)
        self.height_offset.setDecimals(1)
        self.height_offset.setToolTip("Height above the terrain; 0 is on the terrain.")
        form.addRow("Height", self.height_offset)
        layout.addLayout(form)
        self.refresh()

    def template(self) -> str | None:
        return self._template

    def palette(self) -> Palette | None:
        """The loaded game's objects by side and sorting; None before it has loaded."""
        return self.objects.palette()

    def default_owner(self) -> str:
        return self.owner.currentText() or NEUTRAL_TEAM

    # Not `height`: that would hide QWidget.height().
    def height_above_terrain(self) -> float:
        return self.height_offset.value()

    def choose(self, name: str | None) -> None:
        self._template = name
        self.chosen.setText(name or "-")

    def refresh(self) -> None:
        """Pick up newly loaded game data and the open map's teams."""
        game = self.host.game
        if game is not self._game:
            self._game = game
            self.objects.set_palette(object_palette(game) if game is not None else None)
        self._fill_owners()

    def _fill_owners(self) -> None:
        document = self.host.document
        teams = team_list(document.map) if document is not None else None
        names = [qualified_team_name(team) for team in teams or []]
        current = self.owner.currentText()
        self.owner.blockSignals(True)
        try:
            self.owner.clear()
            self.owner.addItems(names)
            keep = current if current in names else NEUTRAL_TEAM
            index = self.owner.findText(keep)
            self.owner.setCurrentIndex(index if index >= 0 else (0 if names else -1))
        finally:
            self.owner.blockSignals(False)

    def _clicked(self, name: str) -> None:
        self.choose(name)
        self.template_chosen.emit(name)


class ReplaceObjectDialog(QDialog):
    """Replace Selected's question: which object the selection becomes. Starts on `current`
    (the palette's own choice) when the tree shows it."""

    def __init__(
        self,
        groups: Palette | None,
        count: int,
        current: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Replace Selected")
        self.resize(360, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Replace {count} selected object(s) with:"))
        self.objects = ObjectTree()
        self.objects.set_palette(groups)
        self.objects.current_changed.connect(lambda _name: self._update_ok())
        self.objects.activated.connect(lambda _name: self.accept())
        layout.addWidget(self.objects, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Replace")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        if current is not None:
            self.objects.select(current)
        self._update_ok()
        self.objects.search.setFocus()

    def template(self) -> str | None:
        """The chosen replacement."""
        return self.objects.current()

    def accept(self) -> None:
        if self.template() is not None:
            super().accept()

    def _update_ok(self) -> None:
        self.ok.setEnabled(self.template() is not None)


def _leaves(tree: QTreeWidget) -> list[QTreeWidgetItem]:
    """The tree's object names, the items with no children."""
    found: list[QTreeWidgetItem] = []
    pending = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    while pending:
        item = pending.pop()
        if item is None:
            continue
        if item.childCount():
            pending.extend(item.child(index) for index in range(item.childCount()))
        else:
            found.append(item)
    return found


def _heading(text: str) -> QTreeWidgetItem:
    """A branch of the tree: a side or an editor sorting, which cannot itself be chosen."""
    item = QTreeWidgetItem([text])
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
    return item
