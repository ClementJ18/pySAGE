"""The Generic AI Object Options panel: WorldBuilder's dialog 294 with its Wall Hub page (295).

It shows the chosen generic AI object's name, type and wall hub number and edits them; with none
chosen, the type and number are what the Generic AI Object tool gives the next one it adds.
Picking a name from the list chooses that object.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from sage_map.assets.object_list import Object
from sage_worldbuilder.generic_ai import (
    GenericAIType,
    generic_ai_objects,
    generic_ai_values,
    is_generic_ai,
    set_generic_ai,
)
from sage_worldbuilder.ui.host import PanelHost

__all__ = ["GenericAIOptionsPanel"]

_MAX_WALL_HUB = 99


class GenericAIOptionsPanel(QWidget):
    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._updating = False
        self._listed: list[Object] = []
        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        layout.addLayout(self.form)

        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.name.activated.connect(self._choose)
        line = self.name.lineEdit()
        if line is not None:
            line.editingFinished.connect(self._rename)
        self.form.addRow("Generic AI Object Name", self.name)

        self.kind = QComboBox()
        for kind in GenericAIType:
            self.kind.addItem(kind.label, kind)
        self.kind.currentIndexChanged.connect(self._set_kind)
        self.form.addRow("Generic AI Object Type", self.kind)

        self.wall_hub = QSpinBox()
        self.wall_hub.setRange(0, _MAX_WALL_HUB)
        self.wall_hub.valueChanged.connect(self._set_wall_hub)
        self.form.addRow("WallHub Number", self.wall_hub)

        note = QLabel(
            "Click the map to add a generic AI object with this type and number; click one to "
            "choose it."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.refresh()

    def selected(self) -> list[Object]:
        document = self.host.document
        if document is None:
            return []
        return [
            item
            for item in document.selection.items
            if isinstance(item, Object) and is_generic_ai(item)
        ]

    def new_type(self) -> GenericAIType:
        kind = self.kind.currentData()
        return kind if isinstance(kind, GenericAIType) else GenericAIType.WALL_HUB

    def new_wall_hub(self) -> int:
        return self.wall_hub.value()

    def refresh(self) -> None:
        document = self.host.document
        self._listed = generic_ai_objects(document.map) if document is not None else []
        chosen = self.selected()
        self._updating = True
        try:
            self.name.clear()
            for obj in self._listed:
                self.name.addItem(generic_ai_values(obj)[0])
            self.name.setEnabled(len(chosen) == 1)
            if chosen:
                name, kind, hub, _ = generic_ai_values(chosen[0])
                self.name.setCurrentIndex(
                    self._listed.index(chosen[0]) if chosen[0] in self._listed else -1
                )
                self.name.setEditText(name if len(chosen) == 1 else "")
                self.kind.setCurrentIndex(
                    self.kind.findData(kind) if isinstance(kind, GenericAIType) else -1
                )
                self.wall_hub.setValue(hub)
            else:
                self.name.setCurrentIndex(-1)
                self.name.setEditText("")
                if self.kind.currentIndex() < 0:
                    self.kind.setCurrentIndex(0)
        finally:
            self._updating = False
        self._show_wall_hub()

    def _show_wall_hub(self) -> None:
        self.form.setRowVisible(self.wall_hub, self.kind.currentData() is GenericAIType.WALL_HUB)

    def _execute(self, **values: object) -> None:
        command = set_generic_ai(self.selected(), **values)  # type: ignore[arg-type]
        if command is not None:
            self.host.execute(command)

    def _choose(self, index: int) -> None:
        document = self.host.document
        if document is None or not 0 <= index < len(self._listed):
            return
        document.selection.set([self._listed[index]])
        self.refresh()

    def _rename(self) -> None:
        chosen = self.selected()
        if self._updating or len(chosen) != 1:
            return
        text = self.name.currentText().strip()
        if text and text != generic_ai_values(chosen[0])[0]:
            self._execute(name=text)

    def _set_kind(self, _index: int) -> None:
        self._show_wall_hub()
        if not self._updating:
            kind = self.kind.currentData()
            if isinstance(kind, GenericAIType):
                self._execute(kind=kind)

    def _set_wall_hub(self, value: int) -> None:
        if not self._updating:
            self._execute(wall_hub=value)
