"""Apply texture to tiles (WorldBuilder's dialog 250): between these slopes, between these
heights, and randomly at an approximate saturation, each with its own Apply box."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.terrain.apply_texture import ApplyTextureOptions

__all__ = ["ApplyTextureDialog"]


class ApplyTextureDialog(QDialog):
    def __init__(self, options: ApplyTextureOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apply texture to tiles")
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Paints the chosen texture on the playable cells whose four corners match every "
            "ticked section. An unticked section allows slopes 0-89°, heights 0-255 ft and "
            "paints every matching cell."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.use_slopes, self.slope_low, self.slope_high = _range_section(
            layout, "Between these slopes", options.use_slopes, options.slopes, 90, "°"
        )
        self.use_heights, self.height_low, self.height_high = _range_section(
            layout, "Between these heights", options.use_heights, options.heights, 3000, " ft"
        )
        box = QGroupBox("Randomly, at this approximate saturation")
        row = QHBoxLayout(box)
        self.use_saturation = QCheckBox("Apply")
        self.use_saturation.setChecked(options.use_saturation)
        row.addWidget(self.use_saturation)
        self.saturation = QSpinBox()
        self.saturation.setRange(0, 100)
        self.saturation.setSuffix(" %")
        self.saturation.setValue(options.saturation)
        row.addWidget(self.saturation, 1)
        layout.addWidget(box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def options(self) -> ApplyTextureOptions:
        return ApplyTextureOptions(
            use_slopes=self.use_slopes.isChecked(),
            slopes=(self.slope_low.value(), self.slope_high.value()),
            use_heights=self.use_heights.isChecked(),
            heights=(self.height_low.value(), self.height_high.value()),
            use_saturation=self.use_saturation.isChecked(),
            saturation=self.saturation.value(),
        )


def _range_section(
    layout: QVBoxLayout,
    title: str,
    checked: bool,
    values: tuple[int, int],
    highest: int,
    suffix: str,
) -> tuple[QCheckBox, QSpinBox, QSpinBox]:
    box = QGroupBox(title)
    row = QHBoxLayout(box)
    apply = QCheckBox("Apply")
    apply.setChecked(checked)
    row.addWidget(apply)
    spins = []
    for label, value in (("from", values[0]), ("to", values[1])):
        row.addWidget(QLabel(label))
        spin = QSpinBox()
        spin.setRange(0, highest)
        spin.setSuffix(suffix)
        spin.setValue(value)
        row.addWidget(spin, 1)
        spins.append(spin)
    layout.addWidget(box)
    return apply, spins[0], spins[1]
