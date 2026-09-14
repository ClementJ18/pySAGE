"""The Build List panel: WorldBuilder's Build List and Building Properties dialogs in one dock.

Choose the player whose skirmish AI build list to edit, reorder or delete its entries, and edit
the chosen entry: name, script, starting health, rebuilds, height, angle and its flags. The Build
List Tool places and moves entries on the map. Export and Import use WorldBuilder's text format.
"""

from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.sides_list import BuildListInfo
from sage_worldbuilder.build_lists import (
    SIDES,
    build_list_entries,
    export_build_list,
    import_entries,
    move_entry,
    parse_build_list,
    remove_entry,
    side_label,
    side_names,
    stores_automatic_build,
)
from sage_worldbuilder.commands import SetAttribute
from sage_worldbuilder.ui.host import PanelHost

__all__ = ["BuildListPanel"]

_LIMIT = 1_000_000


class BuildListPanel(QWidget):
    # The chosen entry (or None) changed.
    entry_changed = pyqtSignal(object)

    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._filling = False
        layout = QVBoxLayout(self)
        self.side = QComboBox()
        self.side.currentIndexChanged.connect(lambda _index: self._fill_entries())
        layout.addWidget(self.side)
        self.entries = QListWidget()
        self.entries.currentRowChanged.connect(lambda _row: self._show_entry())
        layout.addWidget(self.entries, 1)
        buttons = QHBoxLayout()
        for text, slot in (
            ("Up", lambda: self.move_current(-1)),
            ("Down", lambda: self.move_current(1)),
            ("Delete", self.delete_current),
            ("Export…", self._ask_export),
            ("Import…", self._ask_import),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, slot=slot: slot())
            buttons.addWidget(button)
        layout.addLayout(buttons)

        form = QFormLayout()
        self.name = QLineEdit()
        self.name.editingFinished.connect(lambda: self._set("build_name", self.name.text()))
        self.script = QLineEdit()
        self.script.editingFinished.connect(lambda: self._set("script", self.script.text()))
        self.health = QSpinBox()
        self.health.setRange(0, _LIMIT)
        self.health.setSuffix("%")
        self.health.valueChanged.connect(lambda value: self._set("health", value))
        self.rebuilds = QSpinBox()
        self.rebuilds.setRange(0, _LIMIT)
        self.rebuilds.valueChanged.connect(lambda value: self._set("num_rebuilds", value))
        self.z_field = QDoubleSpinBox()
        self.z_field.setRange(-_LIMIT, _LIMIT)
        self.z_field.setKeyboardTracking(False)
        self.z_field.valueChanged.connect(self._set_z)
        self.angle = QDoubleSpinBox()
        self.angle.setRange(-360.0, 360.0)
        self.angle.setSuffix("°")
        self.angle.setKeyboardTracking(False)
        self.angle.valueChanged.connect(lambda value: self._set("angle", math.radians(value)))
        self.initially_built = QCheckBox("Structure already built")
        self.initially_built.toggled.connect(lambda on: self._set("is_initially_built", on))
        self.automatic = QCheckBox("Automatically build")
        self.automatic.toggled.connect(lambda on: self._set("unknown", on))
        self.unsellable = QCheckBox("Unsellable")
        self.unsellable.toggled.connect(lambda on: self._set("unsellable", on))
        self.repairable = QCheckBox("Repairable")
        self.repairable.toggled.connect(lambda on: self._set("repairable", on))
        self.whiner = QCheckBox("Whiner")
        self.whiner.toggled.connect(lambda on: self._set("whiner", on))
        form.addRow("Name", self.name)
        form.addRow("Script", self.script)
        form.addRow("Starting health", self.health)
        form.addRow("Rebuilds", self.rebuilds)
        form.addRow("Z", self.z_field)
        form.addRow("Angle", self.angle)
        for box in (
            self.initially_built,
            self.automatic,
            self.unsellable,
            self.repairable,
            self.whiner,
        ):
            form.addRow(box)
        layout.addLayout(form)
        self.refresh()

    def current_side(self) -> int | None:
        index = self.side.currentIndex()
        return index if index >= 0 else None

    def current_entries(self) -> list[BuildListInfo]:
        document, side = self.host.document, self.current_side()
        if document is None or side is None:
            return []
        return build_list_entries(document.map, side) or []

    def current_entry(self) -> BuildListInfo | None:
        entries, row = self.current_entries(), self.entries.currentRow()
        return entries[row] if 0 <= row < len(entries) else None

    def refresh(self) -> None:
        document = self.host.document
        side = self.current_side()
        self._filling = True
        try:
            self.side.clear()
            if document is not None:
                labels = [side_label(document.map, i) for i in range(len(side_names(document.map)))]
                self.side.addItems(labels)
                if side is not None and side < len(labels):
                    self.side.setCurrentIndex(side)
        finally:
            self._filling = False
        self._fill_entries()

    def _fill_entries(self) -> None:
        if self._filling:
            return
        row = self.entries.currentRow()
        self._filling = True
        try:
            self.entries.clear()
            self.entries.addItems(
                [f"{entry.build_name} ({entry.template_name})" for entry in self.current_entries()]
            )
            if 0 <= row < self.entries.count():
                self.entries.setCurrentRow(row)
        finally:
            self._filling = False
        self._show_entry()

    def select_entry(self, entry: BuildListInfo) -> bool:
        """Show `entry`, switching to the player whose build list holds it."""
        document = self.host.document
        if document is None:
            return False
        for side in range(len(side_names(document.map))):
            entries = build_list_entries(document.map, side) or []
            for row, candidate in enumerate(entries):
                if candidate is entry:
                    if self.current_side() != side:
                        self.side.setCurrentIndex(side)
                    self.entries.setCurrentRow(row)
                    return True
        return False

    def _show_entry(self) -> None:
        if self._filling:
            return
        entry = self.current_entry()
        document = self.host.document
        self._filling = True
        try:
            fields: list[QWidget] = [
                self.name,
                self.script,
                self.health,
                self.rebuilds,
                self.z_field,
                self.angle,
                self.initially_built,
                self.automatic,
                self.unsellable,
                self.repairable,
                self.whiner,
            ]
            for field in fields:
                field.setEnabled(entry is not None)
            if entry is not None:
                self.name.setText(entry.build_name)
                self.script.setText(entry.script)
                self.health.setValue(entry.health)
                self.rebuilds.setValue(entry.num_rebuilds)
                self.z_field.setValue(entry.location[2])
                self.angle.setValue(math.degrees(entry.angle))
                self.initially_built.setChecked(entry.is_initially_built)
                stores = document is not None and stores_automatic_build(document.map)
                self.automatic.setEnabled(stores and entry.unknown is not None)
                self.automatic.setChecked(bool(entry.unknown))
                self.unsellable.setChecked(entry.unsellable)
                self.repairable.setChecked(entry.repairable)
                self.whiner.setChecked(entry.whiner)
        finally:
            self._filling = False
        self.entry_changed.emit(entry)

    def _set(self, attribute: str, value: object) -> None:
        entry = self.current_entry()
        if self._filling or entry is None or getattr(entry, attribute) == value:
            return
        self.host.execute(SetAttribute(entry, attribute, value, SIDES, "Edit Building"))
        self._fill_entries()

    def _set_z(self, value: float) -> None:
        entry = self.current_entry()
        if entry is not None:
            x, y, _ = entry.location
            self._set("location", (x, y, value))

    def move_current(self, step: int) -> None:
        document, side, row = self.host.document, self.current_side(), self.entries.currentRow()
        if document is None or side is None or row < 0:
            return
        command = move_entry(document.map, side, row, step)
        if command is not None:
            self.host.execute(command)
            self._fill_entries()
            self.entries.setCurrentRow(row + step)

    def delete_current(self) -> None:
        document, side, row = self.host.document, self.current_side(), self.entries.currentRow()
        if document is None or side is None or row < 0:
            return
        self.host.execute(remove_entry(document.map, side, row))
        self._fill_entries()

    def export_text(self) -> str | None:
        document, side = self.host.document, self.current_side()
        if document is None or side is None:
            return None
        return export_build_list(document.map, side)

    def import_text(self, text: str) -> int:
        """Append the structures of an exported build list; returns how many were read."""
        document, side = self.host.document, self.current_side()
        if document is None or side is None:
            return 0
        structures = parse_build_list(text)
        if structures:
            self.host.execute(import_entries(document.map, side, structures))
            self._fill_entries()
        return len(structures)

    def _ask_export(self) -> None:
        text = self.export_text()
        if text is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Build List", "", "Build lists (*.ini *.txt)"
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")

    def _ask_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Build List", "", "Build lists (*.ini *.txt)"
        )
        if path:
            self.import_text(Path(path).read_text(encoding="utf-8", errors="replace"))
