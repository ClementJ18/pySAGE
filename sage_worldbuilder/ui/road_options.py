"""The Road Options panel: WorldBuilder's Road Options dialog (148).

The road type the Road tool draws, from the game data's `Road` and `Bridge` blocks (and the types
the map uses that the game data does not list), the corner type, "Add end cap and/or join to a
different road", and Apply To Selection, which gives the selected segments those settings.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.roads import CornerType

__all__ = ["RoadOptionsPanel"]

_TYPE_ROLE = Qt.ItemDataRole.UserRole
_BRIDGE_ROLE = Qt.ItemDataRole.UserRole + 1


class RoadOptionsPanel(QWidget):
    apply_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search road types")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda *_: self._show_current())
        layout.addWidget(self.tree, 1)
        self.current_label = QLabel()
        layout.addWidget(self.current_label)

        corner_box = QGroupBox("Corner type")
        corner_layout = QVBoxLayout(corner_box)
        self.corner_buttons = QButtonGroup(self)
        self._corners: dict[CornerType, QRadioButton] = {}
        for corner in CornerType:
            button = QRadioButton(corner.value)
            self.corner_buttons.addButton(button)
            corner_layout.addWidget(button)
            self._corners[corner] = button
        self._corners[CornerType.BROAD].setChecked(True)
        layout.addWidget(corner_box)
        self.join_box = QCheckBox("Add end cap and/or join to a different road")
        layout.addWidget(self.join_box)
        self.apply_button = QPushButton("Apply To Selection")
        self.apply_button.setToolTip(
            "Give the selected road segments this road type, corner type and join setting."
        )
        self.apply_button.clicked.connect(self.apply_requested.emit)
        layout.addWidget(self.apply_button)
        self._show_current()

    def set_catalogue(self, roads: list[str], bridges: list[str], on_map: list[str]) -> None:
        """Fill the list: the game's roads and bridges, then the types only the map uses. The
        chosen type stays chosen when it is still listed."""
        chosen = self.road_type()
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = (("Roads", roads, False), ("Bridges", bridges, True), ("This map", on_map, False))
        for title, names, bridge in groups:
            if not names:
                continue
            group = QTreeWidgetItem(self.tree, [title])
            group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for name in names:
                leaf = QTreeWidgetItem(group, [name])
                leaf.setData(0, _TYPE_ROLE, name)
                leaf.setData(0, _BRIDGE_ROLE, bridge)
            group.setExpanded(True)
        self.tree.blockSignals(False)
        if chosen is not None:
            self.choose(chosen[0])
        self._filter()
        self._show_current()

    def _leaves(self) -> list[QTreeWidgetItem]:
        found: list[QTreeWidgetItem] = []
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            if group is not None:
                found += [leaf for row in range(group.childCount()) if (leaf := group.child(row))]
        return found

    def choose(self, type_name: str) -> bool:
        """Make a road type the chosen one; False when it is not listed."""
        lowered = type_name.lower()
        for leaf in self._leaves():
            if str(leaf.data(0, _TYPE_ROLE)).lower() == lowered:
                self.tree.setCurrentItem(leaf)
                return True
        return False

    def road_type(self) -> tuple[str, bool] | None:
        item = self.tree.currentItem()
        name = item.data(0, _TYPE_ROLE) if item is not None else None
        if not isinstance(name, str):
            return None
        return name, bool(item.data(0, _BRIDGE_ROLE)) if item is not None else False

    def corner(self) -> CornerType:
        return next(
            (corner for corner, button in self._corners.items() if button.isChecked()),
            CornerType.BROAD,
        )

    def join(self) -> bool:
        return self.join_box.isChecked()

    def show_style(self, type_name: str, corner: CornerType, join: bool) -> None:
        """Show a segment's settings, as when one segment is selected."""
        self.choose(type_name)
        self._corners[corner].setChecked(True)
        self.join_box.setChecked(join)

    def _filter(self) -> None:
        text = self.search.text().strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            if group is None:
                continue
            visible = 0
            for row in range(group.childCount()):
                leaf = group.child(row)
                if leaf is None:
                    continue
                hidden = bool(text) and text not in leaf.text(0).lower()
                leaf.setHidden(hidden)
                visible += not hidden
            group.setHidden(visible == 0)

    def _show_current(self) -> None:
        chosen = self.road_type()
        if chosen is None:
            self.current_label.setText("Current road type: (none chosen)")
        else:
            kind = "bridge" if chosen[1] else "road"
            self.current_label.setText(f"Current road type: {chosen[0]} ({kind})")
