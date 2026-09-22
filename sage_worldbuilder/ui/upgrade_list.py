"""WorldBuilder's Available Upgrades check list: one tickable row per upgrade the selected
objects can be given, with a search box over it (the stock list has none, and a Gondor unit can
offer several dozen rows).

The list asks for `VISIBLE_ROWS` rows of height so the Object tab's scroll area cannot squeeze it
down to a single line, and takes whatever room that tab has spare beyond that."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

__all__ = ["UpgradeList"]

_EMPTY = "No upgrades apply to this object."
_NO_GAME = "Load the game data to list the upgrades this object can be given."
# How many rows the list asks for. The Object tab scrolls, so a list that asks for nothing is
# given a single row's worth of height; this is the shortest it may be, and it grows into
# whatever room the tab has left over.
VISIBLE_ROWS = 5


class _RowsList(QListWidget):
    """A list that asks for room for `VISIBLE_ROWS` rows rather than one."""

    def _rows_height(self) -> int:
        row = self.sizeHintForRow(0)
        if row <= 0:
            row = self.fontMetrics().height() + 2
        return row * VISIBLE_ROWS + 2 * self.frameWidth()

    def _with_rows(self, size: QSize) -> QSize:
        return QSize(size.width(), max(size.height(), self._rows_height()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self._with_rows(super().minimumSizeHint())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self._with_rows(super().sizeHint())


class UpgradeList(QWidget):
    """`ticked` carries the names now ticked, whenever the mapper ticks or unticks one."""

    ticked = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating = False
        self._names: tuple[str, ...] = ()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        self.heading = QLabel("Available upgrades")
        column.addWidget(self.heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search upgrades")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        column.addWidget(self.search)
        self.list = _RowsList()
        self.list.setAlternatingRowColors(True)
        self.list.itemChanged.connect(self._item_changed)
        column.addWidget(self.list, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        column.addWidget(self.note)
        self.show_choices((), (), has_game=True)

    def show_choices(
        self, names: Sequence[str], checked: Sequence[str], has_game: bool = True
    ) -> None:
        """Show a row per name, ticking the ones in `checked` (matched ignoring case)."""
        ticked = {name.casefold() for name in checked}
        self._updating = True
        try:
            self._names = tuple(names)
            self.list.clear()
            for name in names:
                row = QListWidgetItem(name)
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                state = (
                    Qt.CheckState.Checked if name.casefold() in ticked else Qt.CheckState.Unchecked
                )
                row.setCheckState(state)
                self.list.addItem(row)
        finally:
            self._updating = False
        self._filter(self.search.text())
        self.note.setText("" if names else (_EMPTY if has_game else _NO_GAME))
        self.note.setVisible(not names)
        self.list.setVisible(bool(names))
        self.search.setVisible(bool(names))

    def checked(self) -> list[str]:
        """The names ticked now, in the list's order."""
        return [
            item.text()
            for index in range(self.list.count())
            if (item := self.list.item(index)) is not None
            and item.checkState() is Qt.CheckState.Checked
        ]

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is not None:
                item.setHidden(bool(needle) and needle not in item.text().casefold())

    def _item_changed(self, _item: QListWidgetItem) -> None:
        if not self._updating:
            self.ticked.emit(self.checked())
