"""WorldBuilder's New Height Map dialog (133), used by New and by Resize: the size and border in
cells of 10 feet, the initial height in feet, and for a new map the Living World flag and the
texture to cover it with; for a resize, the anchor the old terrain stays pinned to."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QWidget,
)

from sage_worldbuilder.heightmap_io import Anchor
from sage_worldbuilder.new_map import NewMapOptions
from sage_worldbuilder.resize import ResizeOptions
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, MAX_HEIGHT

__all__ = ["NewMapDialog"]

_MAX_CELLS = 2048


class NewMapDialog(QDialog):
    def __init__(
        self,
        options: NewMapOptions,
        textures: list[str],
        parent: QWidget | None = None,
        *,
        resize: bool = False,
    ) -> None:
        super().__init__(parent)
        self.resizing = resize
        self.setWindowTitle("Resize Map" if resize else "New Height Map")
        layout = QFormLayout(self)
        self.width_box = _cells(options.width)
        layout.addRow("Horz (x) size", self.width_box)
        self.height_box = _cells(options.height)
        layout.addRow("Vert (y) size", self.height_box)
        self.border_box = _cells(options.border, low=0)
        layout.addRow("Border size", self.border_box)
        self.initial_height = QDoubleSpinBox()
        self.initial_height.setRange(0.0, MAX_HEIGHT * FEET_PER_HEIGHT_UNIT)
        self.initial_height.setDecimals(1)
        self.initial_height.setSuffix(" ft")
        self.initial_height.setValue(options.initial_height)
        layout.addRow(
            "Initial height" if not resize else "Height of new cells", self.initial_height
        )

        self.texture = QComboBox()
        self.texture.setEditable(True)
        self.texture.addItems(textures)
        self.texture.setCurrentText(options.texture)
        self.living_world = QCheckBox(
            "Map is a script holder for the Living World (a.k.a. Strategy Map)"
        )
        self.living_world.setChecked(options.living_world_script_holder)
        self.cell_size = options.cell_size
        self.anchor_buttons: dict[Anchor, QRadioButton] = {}
        if resize:
            grid_widget = QWidget()
            grid = QGridLayout(grid_widget)
            group = QButtonGroup(self)
            for anchor in Anchor:
                column, row_from_bottom = anchor.value
                button = QRadioButton()
                button.setToolTip(anchor.name.replace("_", " ").title())
                group.addButton(button)
                grid.addWidget(button, 2 - row_from_bottom, column)
                self.anchor_buttons[anchor] = button
            self.anchor_buttons[Anchor.CENTER].setChecked(True)
            layout.addRow("Anchor", grid_widget)
        else:
            layout.addRow("Texture", self.texture)
            layout.addRow(self.living_world)

        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addRow(self.problem)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)
        for box in (self.width_box, self.height_box, self.border_box):
            box.valueChanged.connect(self._check)
        self.texture.currentTextChanged.connect(self._check)
        self._check()

    def anchor(self) -> Anchor:
        return next(
            (anchor for anchor, button in self.anchor_buttons.items() if button.isChecked()),
            Anchor.CENTER,
        )

    def new_map_options(self) -> NewMapOptions:
        return NewMapOptions(
            width=self.width_box.value(),
            height=self.height_box.value(),
            border=self.border_box.value(),
            initial_height=self.initial_height.value(),
            living_world_script_holder=self.living_world.isChecked(),
            texture=self.texture.currentText().strip(),
            cell_size=self.cell_size,
        )

    def resize_options(self) -> ResizeOptions:
        fill = round(self.initial_height.value() / FEET_PER_HEIGHT_UNIT)
        return ResizeOptions(
            width=self.width_box.value(),
            height=self.height_box.value(),
            border=self.border_box.value(),
            anchor=self.anchor(),
            fill_height=int(min(max(fill, 0), MAX_HEIGHT)),
        )

    def _check(self) -> None:
        try:
            if self.resizing:
                self.resize_options().validate()
            else:
                self.new_map_options().validate()
        except ValueError as exc:
            self.problem.setText(str(exc).capitalize() + ".")
            ok = False
        else:
            self.problem.setText("")
            ok = True
        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if button is not None:
            button.setEnabled(ok)


def _cells(value: int, low: int = 1) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, _MAX_CELLS)
    box.setSuffix(" x 10 ft")
    box.setValue(value)
    return box
