"""WorldBuilder's Contour Options dialog: show the contour lines, how many, their offset and
their width."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QWidget,
)

from sage_worldbuilder.viewport import ContourOptions, ViewOptions

__all__ = ["ContourOptionsDialog"]


class ContourOptionsDialog(QDialog):
    def __init__(self, options: ViewOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Contour Options")
        contours = options.contours if options.contours is not None else ContourOptions()
        layout = QFormLayout(self)
        self.show_contours = QCheckBox("Show Contours")
        self.show_contours.setChecked(options.show_contours)
        layout.addRow(self.show_contours)
        self.count = QSpinBox()
        self.count.setRange(1, 100)
        self.count.setValue(contours.count)
        layout.addRow("Number of lines", self.count)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-2560.0, 2560.0)
        self.offset.setDecimals(1)
        self.offset.setSuffix(" ft")
        self.offset.setValue(contours.offset)
        layout.addRow("Offset", self.offset)
        self.width = QSpinBox()
        self.width.setRange(1, 10)
        self.width.setSuffix(" cells")
        self.width.setValue(contours.width)
        layout.addRow("Width", self.width)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def apply(self, options: ViewOptions) -> None:
        options.show_contours = self.show_contours.isChecked()
        options.contours = ContourOptions(
            count=self.count.value(), offset=self.offset.value(), width=self.width.value()
        )
