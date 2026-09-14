"""The Layers List: the map's layers with what is on them. Tick a layer to show it, choose the
active layer new objects, waypoints and trigger areas go on, and rename, delete or merge layers.

A new layer lives only in this session until something is put on it, since the map stores a layer
only as the name its objects and areas carry.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.object_list import Object
from sage_worldbuilder.layers import (
    DEFAULT_LAYER,
    delete_layer,
    item_layer,
    items_in_layer,
    layer_counts,
    merge_layer,
    rename_layer,
    set_layer,
)
from sage_worldbuilder.roads import with_partners
from sage_worldbuilder.ui.host import PanelHost

__all__ = ["LayersPanel", "layer_label"]

_NAME_ROLE = Qt.ItemDataRole.UserRole


def layer_label(name: str) -> str:
    return name if name != DEFAULT_LAYER else "(default)"


class LayersPanel(QWidget):
    # The set of hidden layers changed.
    visibility_changed = pyqtSignal()

    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self.hidden: set[str] = set()
        self.active = DEFAULT_LAYER
        self.created: list[str] = []
        self._filling = False
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Layer", "Objects", "Areas"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree, 1)
        self.active_label = QLabel()
        layout.addWidget(self.active_label)
        buttons = QGridLayout()
        actions = (
            ("New Layer…", self._ask_new),
            ("Rename…", self._ask_rename),
            ("Delete", self.delete_selected),
            ("Merge Into…", self._ask_merge),
            ("Set Active", self.activate_selected),
            ("Select Its Items", self.select_items),
            ("Move Selection Here", self.move_selection_here),
        )
        for index, (text, slot) in enumerate(actions):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, slot=slot: slot())
            buttons.addWidget(button, index // 2, index % 2)
        layout.addLayout(buttons)
        self.refresh()

    def names(self) -> list[str]:
        document = self.host.document
        counts = layer_counts(document.map) if document is not None else {}
        return [*counts, *(name for name in self.created if name not in counts)]

    def refresh(self) -> None:
        document = self.host.document
        counts = layer_counts(document.map) if document is not None else {}
        current = self.selected_layer()
        self._filling = True
        try:
            self.tree.clear()
            for name in self.names() if document is not None else []:
                objects, areas = counts.get(name, (0, 0))
                label = layer_label(name) + ("  (active)" if name == self.active else "")
                row = QTreeWidgetItem([label, str(objects), str(areas)])
                row.setData(0, _NAME_ROLE, name)
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                hidden = name in self.hidden
                row.setCheckState(0, Qt.CheckState.Unchecked if hidden else Qt.CheckState.Checked)
                self.tree.addTopLevelItem(row)
                if name == current:
                    self.tree.setCurrentItem(row)
        finally:
            self._filling = False
        self.active_label.setText(f"Active layer: {layer_label(self.active)}")

    def selected_layer(self) -> str | None:
        row = self.tree.currentItem()
        name = row.data(0, _NAME_ROLE) if row is not None else None
        return name if isinstance(name, str) else None

    def select_layer(self, name: str) -> None:
        for index in range(self.tree.topLevelItemCount()):
            row = self.tree.topLevelItem(index)
            if row is not None and row.data(0, _NAME_ROLE) == name:
                self.tree.setCurrentItem(row)

    def add_layer(self, name: str) -> bool:
        name = name.strip()
        if not name or name.lower() in {existing.lower() for existing in self.names()}:
            return False
        self.created.append(name)
        self.refresh()
        self.select_layer(name)
        return True

    def rename_selected(self, new: str) -> bool:
        old, document, new = self.selected_layer(), self.host.document, new.strip()
        if old is None or old == DEFAULT_LAYER or document is None or not new:
            return False
        if new.lower() in {name.lower() for name in self.names()} - {old.lower()}:
            return False
        command = rename_layer(document.map, old, new)
        if command.commands:
            self.host.execute(command)
        self.created = [new if name == old else name for name in self.created]
        if old in self.hidden:
            self.hidden = (self.hidden - {old}) | {new}
            self.visibility_changed.emit()
        if self.active == old:
            self.active = new
        self.refresh()
        self.select_layer(new)
        return True

    def delete_selected(self) -> None:
        name, document = self.selected_layer(), self.host.document
        if name is None or name == DEFAULT_LAYER or document is None:
            return
        command = delete_layer(document.map, name)
        if command.commands:
            self.host.execute(command)
        self.created = [existing for existing in self.created if existing != name]
        if name in self.hidden:
            self.hidden.discard(name)
            self.visibility_changed.emit()
        if self.active == name:
            self.active = DEFAULT_LAYER
        self.refresh()

    def merge_selected_into(self, into: str) -> bool:
        name, document = self.selected_layer(), self.host.document
        if name is None or document is None or into == name or into not in self.names():
            return False
        command = merge_layer(document.map, name, into)
        if command.commands:
            self.host.execute(command)
        if name != DEFAULT_LAYER:
            self.created = [existing for existing in self.created if existing != name]
            if self.active == name:
                self.active = into
        self.refresh()
        return True

    def activate_selected(self) -> None:
        name = self.selected_layer()
        if name is not None:
            self.active = name
            self.refresh()

    def select_items(self) -> None:
        name, document = self.selected_layer(), self.host.document
        if name is None or document is None:
            return
        if document.selection.locked:
            return
        document.selection.set(items_in_layer(document.map, name))

    def move_selection_here(self) -> None:
        name, document = self.selected_layer(), self.host.document
        if name is None or document is None:
            return
        items = [item for item in document.selection if item_layer(item) is not None]
        # A road segment's two ends go together, so a hidden layer never shows half a road.
        objects = with_partners(document.map, [item for item in items if isinstance(item, Object)])
        items = objects + [item for item in items if not isinstance(item, Object)]
        command = set_layer(items, name)
        if command.commands:
            self.host.execute(command)

    def _item_changed(self, row: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        name = row.data(0, _NAME_ROLE)
        if not isinstance(name, str):
            return
        if row.checkState(0) == Qt.CheckState.Checked:
            self.hidden.discard(name)
        else:
            self.hidden.add(name)
        self.visibility_changed.emit()

    def _ask_new(self) -> None:
        name, accepted = QInputDialog.getText(self, "New Layer", "Layer name:", text="New Layer")
        if accepted and not self.add_layer(name):
            QMessageBox.warning(self, "New Layer", f"There is already a layer named {name!r}.")

    def _ask_rename(self) -> None:
        old = self.selected_layer()
        if old is None or old == DEFAULT_LAYER:
            return
        new, accepted = QInputDialog.getText(self, "Rename Layer", "New name:", text=old)
        if accepted and not self.rename_selected(new):
            QMessageBox.warning(self, "Rename Layer", f"Cannot rename the layer to {new!r}.")

    def _ask_merge(self) -> None:
        name = self.selected_layer()
        if name is None:
            return
        others = [layer_label(other) for other in self.names() if other != name]
        if not others:
            return
        choice, accepted = QInputDialog.getItem(
            self, "Merge Layer", f"Merge {layer_label(name)} into:", others, 0, False
        )
        if accepted:
            into = DEFAULT_LAYER if choice == layer_label(DEFAULT_LAYER) else choice
            self.merge_selected_into(into)
