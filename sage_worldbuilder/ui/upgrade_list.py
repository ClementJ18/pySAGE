"""WorldBuilder's Available Upgrades check list: one tickable row per upgrade the selected
objects can be given, with a search box over it (the stock list has none, and a Gondor unit can
offer several dozen rows).

A search that matches none of the object's own upgrades falls back to every upgrade the mod
defines, under a heading row, so the mapper can grant one the template does not offer. A name
ticked there joins the object's rows as soon as the search changes, so it stays listed and ticked.

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
_EMPTY_SEARCHABLE = "No upgrades apply to this object. Search to grant any upgrade in the mod."
_FALLBACK = "No match among this object's upgrades. All upgrades in the mod:"
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
        self._all_names: tuple[str, ...] = ()
        self._has_game = True
        # Rows past `len(self._names)`: the heading and the mod-wide matches of a fruitless search.
        self._fallback = False
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
        self,
        names: Sequence[str],
        checked: Sequence[str],
        has_game: bool = True,
        all_names: Sequence[str] = (),
    ) -> None:
        """Show a row per name, ticking the ones in `checked` (matched ignoring case).
        `all_names` are the mod's upgrades a search falls back to when no row matches."""
        self._all_names = tuple(all_names)
        self._has_game = has_game
        self._fill(names, {name.casefold() for name in checked})
        self._filter(self.search.text())

    def checked(self) -> list[str]:
        """The names ticked now, in the list's order."""
        return [
            item.text()
            for index in range(self.list.count())
            if (item := self.list.item(index)) is not None
            and item.checkState() is Qt.CheckState.Checked
        ]

    def _row(self, name: str, ticked: set[str]) -> QListWidgetItem:
        row = QListWidgetItem(name)
        row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        state = Qt.CheckState.Checked if name.casefold() in ticked else Qt.CheckState.Unchecked
        row.setCheckState(state)
        return row

    def _fill(self, names: Sequence[str], ticked: set[str]) -> None:
        self._updating = True
        try:
            self._names = tuple(names)
            self._fallback = False
            self.list.clear()
            for name in names:
                self.list.addItem(self._row(name, ticked))
        finally:
            self._updating = False

    def _fallback_items(self) -> list[QListWidgetItem]:
        if not self._fallback:
            return []
        rows = (self.list.item(index) for index in range(len(self._names) + 1, self.list.count()))
        return [row for row in rows if row is not None]

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        # Whatever was granted from the last fallback joins the object's own rows.
        granted = [
            item.text()
            for item in self._fallback_items()
            if item.checkState() is Qt.CheckState.Checked
        ]
        if self._fallback:
            ticked = {name.casefold() for name in self.checked()}
            self._fill(sorted([*self._names, *granted], key=str.casefold), ticked)
        matched = False
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is not None:
                hidden = bool(needle) and needle not in item.text().casefold()
                item.setHidden(hidden)
                matched = matched or not hidden
        if needle and not matched:
            self._show_fallback(needle)
        names_or_fallback = bool(self._names) or self._fallback
        if self._names:
            note = ""
        elif self._all_names:
            note = _EMPTY_SEARCHABLE
        else:
            note = _EMPTY if self._has_game else _NO_GAME
        self.note.setText(note)
        self.note.setVisible(bool(note) and not self._fallback)
        self.list.setVisible(names_or_fallback)
        self.search.setVisible(bool(self._names) or bool(self._all_names))

    def _show_fallback(self, needle: str) -> None:
        offered = {name.casefold() for name in self._names}
        matches = [
            name
            for name in self._all_names
            if needle in name.casefold() and name.casefold() not in offered
        ]
        if not matches:
            return
        self._updating = True
        try:
            heading = QListWidgetItem(_FALLBACK)
            heading.setFlags(Qt.ItemFlag.NoItemFlags)
            font = heading.font()
            font.setItalic(True)
            heading.setFont(font)
            self.list.addItem(heading)
            for name in matches:
                self.list.addItem(self._row(name, set()))
            self._fallback = True
        finally:
            self._updating = False

    def _item_changed(self, _item: QListWidgetItem) -> None:
        if not self._updating:
            self.ticked.emit(self.checked())
