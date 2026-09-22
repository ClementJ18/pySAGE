"""The Customize Toolbar dialog: which of `sage_worldbuilder.toolbar`'s catalogue items the main
toolbar shows, and in what order.

One checkable, reorderable list carries the whole catalogue - an item on the toolbar today starts
checked, at its current position; everything else starts unchecked, in catalogue order, ready to
be ticked on. Checking, unchecking, dragging a row and Move Up/Move Down all edit the same list, so
there is exactly one thing the dialog needs to read back on accept: the checked ids, top to bottom.
Separators are not part of this model - `MainWindow._build_toolbar` derives them from where the
catalogue's own group changes, so the list never carries one.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.toolbar import CATALOGUE, DEFAULT_ITEMS, ITEMS_BY_ID

__all__ = ["CustomizeToolbarDialog"]

# The group name is shown as a left-aligned, fixed-width column ahead of the item's own label, so
# a Terrain tool reads differently from a Locks toggle without needing a hover for the tooltip
# that carries the same text. Padding to the longest group name is what keeps the labels lined up.
_GROUP_WIDTH = max(len(item.group) for item in CATALOGUE) + 2


class CustomizeToolbarDialog(QDialog):
    def __init__(self, layout_ids: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Toolbar")
        self.resize(420, 520)

        outer = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._populate(layout_ids)
        outer.addWidget(self.list, 1)

        move_row = QHBoxLayout()
        up = QPushButton("Move Up")
        up.clicked.connect(lambda: self._move(-1))
        move_row.addWidget(up)
        down = QPushButton("Move Down")
        down.clicked.connect(lambda: self._move(1))
        move_row.addWidget(down)
        move_row.addStretch(1)
        outer.addLayout(move_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if restore is not None:
            restore.clicked.connect(self._restore_defaults)
        outer.addWidget(buttons)

    def _populate(self, layout_ids: Sequence[str]) -> None:
        """Fill the list from `layout_ids`: those ids first, checked, in that order, then every
        other catalogue item, unchecked, in catalogue order. An id `layout_ids` carries that the
        catalogue does not have is silently dropped, same as `toolbar.normalise`."""
        self.list.clear()
        chosen = [item_id for item_id in layout_ids if item_id in ITEMS_BY_ID]
        chosen_set = set(chosen)
        rest = [item.id for item in CATALOGUE if item.id not in chosen_set]
        for item_id in (*chosen, *rest):
            self.list.addItem(self._row(item_id, checked=item_id in chosen_set))

    def _row(self, item_id: str, *, checked: bool) -> QListWidgetItem:
        catalogue_item = ITEMS_BY_ID[item_id]
        row = QListWidgetItem(f"{catalogue_item.group.ljust(_GROUP_WIDTH)}{catalogue_item.label}")
        row.setData(Qt.ItemDataRole.UserRole, item_id)
        row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        row.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        row.setToolTip(catalogue_item.group)
        return row

    def _move(self, step: int) -> None:
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)

    def _restore_defaults(self) -> None:
        self._populate(DEFAULT_ITEMS)

    def chosen_ids(self) -> list[str]:
        """The checked ids, top to bottom: the layout to store. Empty when nothing is checked,
        which is a legal, empty toolbar. Not named `layout`, which is `QWidget`'s own and returns
        the dialog's `QVBoxLayout`."""
        chosen: list[str] = []
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                chosen.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return chosen
