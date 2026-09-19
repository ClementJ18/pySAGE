"""The Object Palette: WorldBuilder's Object Selection panel. Pick the object Place Object puts
down, the team it will belong to, and its height above the terrain."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
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

__all__ = ["ObjectPalettePanel"]

_NAME_ROLE = Qt.ItemDataRole.UserRole
# The neutral player's team, which a new object belongs to unless another is chosen.
NEUTRAL_TEAM = "/team"
_HEIGHT_LIMIT = 10000.0


class ObjectPalettePanel(QWidget):
    # The object name chosen in the tree.
    template_chosen = pyqtSignal(str)

    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._template: str | None = None
        self._groups: Palette = {}
        self._game: object = None
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search objects")
        self.search.textChanged.connect(lambda _text: self._fill_tree())
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(lambda item, _column: self._clicked(item))
        layout.addWidget(self.tree, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
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
            self._groups = object_palette(game) if game is not None else {}
            self._fill_tree()
        self._fill_owners()

    def _fill_tree(self) -> None:
        """Fill the tree: a branch per side, and under it one per editor sorting."""
        self.tree.clear()
        if self.host.game is None:
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

    def _clicked(self, item: QTreeWidgetItem) -> None:
        name = item.data(0, _NAME_ROLE)
        if isinstance(name, str):
            self.choose(name)
            self.template_chosen.emit(name)


def _heading(text: str) -> QTreeWidgetItem:
    """A branch of the tree: a side or an editor sorting, which cannot itself be chosen."""
    item = QTreeWidgetItem([text])
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
    return item
