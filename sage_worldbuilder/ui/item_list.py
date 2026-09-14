"""The Item List panel: search the map's objects, waypoints, trigger areas and teams.
Double-clicking a team opens it in the Teams panel; double-clicking anything else selects it on the
map (so the Object Properties panel shows it) and centres the view on it. Zoom To Selected only
centres the view. With Filter map on, the map view shows only what the list
matches. Clicking a column header sorts by it; a third click returns
to the order the map stores the items in."""

from __future__ import annotations

import re
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.items import ItemKind, ItemRow, item_position, map_items
from sage_worldbuilder.ui.host import PanelHost

__all__ = ["ItemListPanel"]

ZoomTo = Callable[[float, float], None]
# Receives the listed map items while Filter map is on, and None when the map shows everything.
FilterMap = Callable[[list[object] | None], None]
# Receives the object, waypoint or trigger area a double-click chose, to select it.
SelectItem = Callable[[object], None]

_ROLE = Qt.ItemDataRole.UserRole
_ORDER_ROLE = Qt.ItemDataRole.UserRole + 1
_ALL = "All items"
_NUMBER = re.compile(r"(-?\d+)")


def natural_key(text: str) -> list[tuple[int, int | str]]:
    """Orders text ignoring case and with its numbers by value, so `Tower2` precedes `Tower10`
    and `at (-50, 0)` precedes `at (20, 0)`."""
    return [
        (0, int(part)) if index % 2 else (1, part.casefold())
        for index, part in enumerate(_NUMBER.split(text))
        if part
    ]


class _Row(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        mine, theirs = natural_key(self.text(column)), natural_key(other.text(column))
        if mine != theirs:
            return mine < theirs
        # Equal cells keep the map's order between them.
        return int(self.data(0, _ORDER_ROLE)) < int(other.data(0, _ORDER_ROLE))


class ItemListPanel(QWidget):
    def __init__(
        self,
        host: PanelHost,
        on_team: Callable[[str], None] | None = None,
        on_zoom: ZoomTo | None = None,
        on_filter: FilterMap | None = None,
        on_select: SelectItem | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.on_team = on_team
        self.on_zoom = on_zoom
        self.on_filter = on_filter
        self.on_select = on_select
        self.rows: list[ItemRow] = []
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search names, object types and positions")
        self.search.textChanged.connect(lambda _text: self.refresh())
        filters.addWidget(self.search, 1)
        self.kind = QComboBox()
        self.kind.addItems([_ALL, *(kind.value for kind in ItemKind)])
        self.kind.currentIndexChanged.connect(lambda _index: self.refresh())
        filters.addWidget(self.kind)
        self.only_named = QCheckBox("Only named")
        self.only_named.toggled.connect(lambda _on: self.refresh())
        filters.addWidget(self.only_named)
        self.filter_map = QCheckBox("Filter map")
        self.filter_map.setToolTip(
            "Show only the objects, waypoints and trigger areas listed here on the map."
        )
        self.filter_map.toggled.connect(lambda _on: self.refresh())
        filters.addWidget(self.filter_map)
        self.zoom_button = QPushButton("Zoom To Selected")
        self.zoom_button.clicked.connect(lambda _checked=False: self.zoom_to_selected())
        filters.addWidget(self.zoom_button)
        layout.addLayout(filters)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Kind", "Name", "Detail"])
        self.tree.setRootIsDecorated(False)
        header = self.tree.header()
        if header is not None:
            # No column is sorted until one is clicked, and a third click clears the sort again.
            header.setSortIndicatorClearable(True)
            header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            header.sortIndicatorChanged.connect(self._sort_changed)
        self.tree.setSortingEnabled(True)
        self.tree.itemDoubleClicked.connect(lambda item, _column: self._open(item))
        layout.addWidget(self.tree, 1)
        self.count = QLabel()
        layout.addWidget(self.count)
        self.refresh()

    def refresh(self) -> None:
        document = self.host.document
        choice = self.kind.currentText()
        kinds = None if choice == _ALL else frozenset({ItemKind(choice)})
        self.rows = (
            map_items(document.map, self.search.text(), self.only_named.isChecked(), kinds)
            if document is not None
            else []
        )
        self.tree.clear()
        nodes: list[QTreeWidgetItem] = []
        for row in self.rows:
            node = _Row([row.kind.value, row.name, row.detail])
            node.setData(0, _ROLE, row)
            node.setData(0, _ORDER_ROLE, len(nodes))
            nodes.append(node)
        self.tree.addTopLevelItems(nodes)
        self.count.setText(f"{len(self.rows)} item(s)" if document is not None else "No map open.")
        if self.on_filter is not None:
            filtering = self.filter_map.isChecked() and document is not None
            self.on_filter([row.source for row in self.rows] if filtering else None)

    def _sort_changed(self, column: int, _order: Qt.SortOrder) -> None:
        # Sorting reorders the rows in place; with the sort cleared, rebuild them in map order.
        if column < 0:
            self.refresh()

    def _open(self, node: QTreeWidgetItem) -> None:
        row = node.data(0, _ROLE)
        if not isinstance(row, ItemRow):
            return
        if row.kind is ItemKind.TEAM:
            if self.on_team is not None:
                self.on_team(row.name)
            return
        if self.on_select is not None:
            self.on_select(row.source)
        self._zoom(row)

    def zoom_to_selected(self) -> bool:
        """Centre the map view on the selected item; False when it has no position."""
        node = self.tree.currentItem()
        row = node.data(0, _ROLE) if node is not None else None
        return isinstance(row, ItemRow) and self._zoom(row)

    def _zoom(self, row: ItemRow) -> bool:
        position = item_position(row)
        if position is None or self.on_zoom is None:
            return False
        self.on_zoom(*position)
        return True
