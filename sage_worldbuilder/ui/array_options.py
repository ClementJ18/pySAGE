"""The Array Options panel: what the Radial Array tool repeats, how many times, and which way
each copy is turned. WorldBuilder has no such panel; the options are `arrays.ArrayOptions`.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.arrays import MAX_COUNT, MIN_COUNT, ArrayOptions, Facing

__all__ = ["ArrayOptionsPanel"]


class ArrayOptionsPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, options: ArrayOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.options = options
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.count_box = QSpinBox()
        self.count_box.setRange(MIN_COUNT, MAX_COUNT)
        self.count_box.setToolTip("How many copies the ring holds, the first one included.")
        form.addRow("Copies", self.count_box)
        self.spacing_label = QLabel()
        form.addRow("", self.spacing_label)

        self.facing_box = QComboBox()
        self.facing_box.addItems([facing.value for facing in Facing])
        self.facing_box.setToolTip(
            "Which way each copy is turned. The rule aims the first object of the group; the "
            "rest keep their angles relative to it."
        )
        form.addRow("Facing", self.facing_box)

        self.offset_box = QDoubleSpinBox()
        self.offset_box.setRange(-180.0, 180.0)
        self.offset_box.setDecimals(1)
        self.offset_box.setSuffix(" degrees")
        self.offset_box.setToolTip("Turned further, for a model whose front is not its +X side.")
        form.addRow("Angle offset", self.offset_box)

        self.selection_box = QCheckBox("Repeat the selection")
        self.selection_box.setToolTip(
            "Repeat the selected objects, keeping the group's arrangement, instead of the Object "
            "Palette's object. Off, or with nothing selected, the palette's object is placed."
        )
        layout.addWidget(self.selection_box)
        note = QLabel(
            "Press where the ring's centre goes and drag outwards: the copies land that far from "
            "the centre, evenly spaced, and are left selected. With objects selected, a press "
            "with no drag builds the ring through them where they already stand."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self.refresh()
        self.count_box.valueChanged.connect(self._store)
        self.offset_box.valueChanged.connect(self._store)
        self.facing_box.currentIndexChanged.connect(self._store)
        self.selection_box.toggled.connect(self._store)

    def refresh(self) -> None:
        """Show the options as they stand, without reporting a change."""
        for widget in (self.count_box, self.offset_box, self.facing_box, self.selection_box):
            widget.blockSignals(True)
        self.count_box.setValue(self.options.count)
        self.offset_box.setValue(self.options.offset_degrees)
        self.facing_box.setCurrentText(self.options.facing.value)
        self.selection_box.setChecked(self.options.use_selection)
        for widget in (self.count_box, self.offset_box, self.facing_box, self.selection_box):
            widget.blockSignals(False)
        self._show_spacing()

    def _show_spacing(self) -> None:
        count = max(self.count_box.value(), 1)
        self.spacing_label.setText(f"{360 / count:.1f} degrees apart")

    def _store(self) -> None:
        self.options.count = self.count_box.value()
        self.options.offset_degrees = self.offset_box.value()
        self.options.facing = Facing(self.facing_box.currentText())
        self.options.use_selection = self.selection_box.isChecked()
        self._show_spacing()
        self.changed.emit()
