"""WorldBuilder's Grid Settings dialog: show the grid, its spacing, snapping, and whether the lines
start at the world origin."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QWidget,
)

from sage_worldbuilder.viewport import GridSettings, ViewOptions

__all__ = ["GridSettingsDialog"]


class GridSettingsDialog(QDialog):
    def __init__(self, options: ViewOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Grid Settings")
        grid = options.grid if options.grid is not None else GridSettings()
        layout = QFormLayout(self)
        self.show_grid = QCheckBox("Show Grid")
        self.show_grid.setChecked(options.show_grid)
        layout.addRow(self.show_grid)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(1.0, 10000.0)
        self.spacing.setDecimals(1)
        self.spacing.setSuffix(" world units")
        self.spacing.setValue(grid.spacing)
        layout.addRow("Spacing", self.spacing)
        self.justify = QCheckBox("Justify to (0, 0)")
        self.justify.setChecked(grid.justify_to_origin)
        layout.addRow(self.justify)
        self.snap = QCheckBox("Snap To Grid")
        self.snap.setChecked(grid.snap)
        layout.addRow(self.snap)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if restore is not None:
            restore.clicked.connect(self._restore_defaults)
        layout.addRow(buttons)

    def _restore_defaults(self) -> None:
        defaults = GridSettings()
        self.spacing.setValue(defaults.spacing)
        self.justify.setChecked(defaults.justify_to_origin)
        self.snap.setChecked(defaults.snap)

    def apply(self, options: ViewOptions) -> None:
        options.show_grid = self.show_grid.isChecked()
        options.grid = GridSettings(
            spacing=self.spacing.value(),
            snap=self.snap.isChecked(),
            justify_to_origin=self.justify.isChecked(),
        )
