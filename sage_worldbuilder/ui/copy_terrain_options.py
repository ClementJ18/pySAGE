"""The Copy Terrain Options panel (WorldBuilder's dialog 262): Selection or Copy mode, how cells
are selected, and how the selection is copied."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.brush_options import CopyTerrainOptions, SelectMethod

__all__ = ["ROTATIONS", "CopyTerrainOptionsPanel"]

ROTATIONS = ("0°", "90°", "180°", "270°")


class CopyTerrainOptionsPanel(QWidget):
    changed = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self, options: CopyTerrainOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.options = options
        layout = QVBoxLayout(self)

        modes = QHBoxLayout()
        self.selection_mode = QRadioButton("Selection mode")
        self.copy_mode = QRadioButton("Copy mode")
        _group(self, [self.selection_mode, self.copy_mode])
        modes.addWidget(self.selection_mode)
        modes.addWidget(self.copy_mode)
        layout.addLayout(modes)

        self.selection_box = QGroupBox("Selection options")
        selection = QFormLayout(self.selection_box)
        self.drag_select = QRadioButton("Drag select")
        self.brush_select = QRadioButton("Brush select")
        _group(self, [self.drag_select, self.brush_select])
        selection.addRow(self.drag_select, self.brush_select)
        self.brush_size = QSpinBox()
        self.brush_size.setRange(1, 100)
        self.brush_size.setSuffix(" cells")
        selection.addRow("Brush size:", self.brush_size)
        self.add_to = QRadioButton("Add to selection")
        self.remove_from = QRadioButton("Remove from selection")
        _group(self, [self.add_to, self.remove_from])
        selection.addRow(self.add_to, self.remove_from)
        self.clear_button = QPushButton("Clear selection")
        self.clear_button.clicked.connect(self.clear_requested.emit)
        selection.addRow(self.clear_button)
        layout.addWidget(self.selection_box)

        self.copy_box = QGroupBox("Copy options")
        copying = QFormLayout(self.copy_box)
        self.flip_vertically = QCheckBox("Vertically")
        self.flip_horizontally = QCheckBox("Horizontally")
        copying.addRow("Flip:", _row(self.flip_vertically, self.flip_horizontally))
        self.copy_heights = QCheckBox("Terrain height")
        self.copy_texture = QCheckBox("Terrain texture")
        self.copy_passability = QCheckBox("Passability")
        copying.addRow("Copy:", self.copy_heights)
        copying.addRow("", self.copy_texture)
        copying.addRow("", self.copy_passability)
        self.rotations = [QRadioButton(label) for label in ROTATIONS]
        _group(self, self.rotations)
        copying.addRow("Rotate:", _row(*self.rotations))
        layout.addWidget(self.copy_box)

        note = QLabel(
            "In Selection mode, drag or brush over cells to select them. In Copy mode, click to "
            "copy the selection with its centre on the cell clicked; 90° turns it clockwise."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self.refresh()
        for button in (
            self.selection_mode,
            self.copy_mode,
            self.drag_select,
            self.brush_select,
            self.add_to,
            self.remove_from,
            *self.rotations,
        ):
            button.toggled.connect(self._store)
        for box in (
            self.flip_vertically,
            self.flip_horizontally,
            self.copy_heights,
            self.copy_texture,
            self.copy_passability,
        ):
            box.toggled.connect(self._store)
        self.brush_size.valueChanged.connect(self._store)

    def _widgets(self) -> list[QWidget]:
        return [
            self.selection_mode,
            self.copy_mode,
            self.drag_select,
            self.brush_select,
            self.brush_size,
            self.add_to,
            self.remove_from,
            self.flip_vertically,
            self.flip_horizontally,
            self.copy_heights,
            self.copy_texture,
            self.copy_passability,
            *self.rotations,
        ]

    def refresh(self) -> None:
        options = self.options
        widgets = self._widgets()
        for widget in widgets:
            widget.blockSignals(True)
        (self.copy_mode if options.copying else self.selection_mode).setChecked(True)
        brush = options.method is SelectMethod.BRUSH
        (self.brush_select if brush else self.drag_select).setChecked(True)
        self.brush_size.setValue(options.brush_size)
        (self.remove_from if options.remove else self.add_to).setChecked(True)
        self.flip_vertically.setChecked(options.flip_vertically)
        self.flip_horizontally.setChecked(options.flip_horizontally)
        self.copy_heights.setChecked(options.heights)
        self.copy_texture.setChecked(options.texture)
        self.copy_passability.setChecked(options.passability)
        self.rotations[options.turns % 4].setChecked(True)
        for widget in widgets:
            widget.blockSignals(False)
        self.selection_box.setEnabled(not options.copying)
        self.copy_box.setEnabled(options.copying)
        self.brush_size.setEnabled(brush)

    def _store(self) -> None:
        options = self.options
        options.copying = self.copy_mode.isChecked()
        options.method = SelectMethod.BRUSH if self.brush_select.isChecked() else SelectMethod.DRAG
        options.brush_size = self.brush_size.value()
        options.remove = self.remove_from.isChecked()
        options.flip_vertically = self.flip_vertically.isChecked()
        options.flip_horizontally = self.flip_horizontally.isChecked()
        options.heights = self.copy_heights.isChecked()
        options.texture = self.copy_texture.isChecked()
        options.passability = self.copy_passability.isChecked()
        options.turns = next(
            (turns for turns, button in enumerate(self.rotations) if button.isChecked()), 0
        )
        self.refresh()
        self.changed.emit()


def _group(owner: QWidget, buttons: list[QRadioButton]) -> QButtonGroup:
    group = QButtonGroup(owner)
    for button in buttons:
        group.addButton(button)
    return group


def _row(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch(1)
    return holder
