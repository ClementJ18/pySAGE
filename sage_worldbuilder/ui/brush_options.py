"""The Brush Options panel: WorldBuilder's Height Brush, Terrain Brush and Feather Brush option
panels in one place, since the height tools share the brush width and feather."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDoubleSpinBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from sage_worldbuilder.brush_options import BrushOptions
from sage_worldbuilder.terrain import WORLD_UNITS_PER_CELL

__all__ = ["BrushOptionsPanel"]


class BrushOptionsPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, options: BrushOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.options = options
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.width_box = _spin(1, 100, " cells")
        self.width_box.setToolTip("Brush Width: the samples at full strength, across.")
        form.addRow("Brush width", self.width_box)
        self.feather_box = _spin(0, 50, " cells")
        self.feather_box.setToolTip(
            "Brush Feather Width: the ring beyond the brush where its effect fades out."
        )
        form.addRow("Feather width", self.feather_box)
        self.size_label = QLabel()
        form.addRow("", self.size_label)

        self.height_box = _feet(0.0, 2559.0)
        self.height_box.setToolTip("Height Brush: the height it paints.")
        form.addRow("Brush height", self.height_box)
        self.amount_box = _feet(0.0, 500.0)
        self.amount_box.setToolTip("Mound and Dig: how far each application raises or lowers.")
        form.addRow("Raise / lower by", self.amount_box)

        self.radius_box = _spin(1, 10, " cells")
        self.radius_box.setToolTip(
            "Smooth Height's Filter Radius. A large value tends to flatten the map. A small value "
            "retains steep sides to smoothed hills."
        )
        form.addRow("Filter radius", self.radius_box)
        self.rate_box = _spin(1, 10, "")
        self.rate_box.setToolTip(
            "Smooth Height's Feather Rate. A high value flattens terrain quickly. A low value "
            'requires you to "scrub" with the cursor to achieve the same effect.'
        )
        form.addRow("Feather rate", self.rate_box)
        layout.addStretch(1)

        self.refresh()
        for box in (self.width_box, self.feather_box, self.radius_box, self.rate_box):
            box.valueChanged.connect(self._store)
        for box in (self.height_box, self.amount_box):
            box.valueChanged.connect(self._store)

    def refresh(self) -> None:
        boxes = (
            (self.width_box, self.options.width),
            (self.feather_box, self.options.feather),
            (self.height_box, self.options.height),
            (self.amount_box, self.options.amount),
            (self.radius_box, self.options.radius),
            (self.rate_box, self.options.rate),
        )
        for box, value in boxes:
            box.blockSignals(True)
            box.setValue(value)  # type: ignore[arg-type]
            box.blockSignals(False)
        self._show_size()

    def _store(self) -> None:
        self.options.width = self.width_box.value()
        self.options.feather = self.feather_box.value()
        self.options.height = self.height_box.value()
        self.options.amount = self.amount_box.value()
        self.options.radius = self.radius_box.value()
        self.options.rate = self.rate_box.value()
        self._show_size()
        self.changed.emit()

    def _show_size(self) -> None:
        width = self.options.width * WORLD_UNITS_PER_CELL
        across = (self.options.width + 2 * self.options.feather) * WORLD_UNITS_PER_CELL
        self.size_label.setText(f"{width:.0f} ft, {across:.0f} ft with the feather")


def _spin(low: int, high: int, suffix: str) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setSuffix(suffix)
    return box


def _feet(low: float, high: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(1)
    box.setSuffix(" ft")
    return box
