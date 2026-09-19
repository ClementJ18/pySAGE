"""The Dressing Options panel: WorldBuilder's Scorch Options (214), Grove Options (195), Fence
options (196), Ramp Options (215) and Mesh Mold Options (151), one page for each tool, shown for
the tool in use. The Border Tool has no options in WorldBuilder ("This tool has no options");
its page says how its gestures work.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.dressing import (
    DEFAULT_FENCE_SPACING,
    DEFAULT_RAMP_WIDTH,
    DEFAULT_SCORCH_SIZE,
    SCORCH_TYPES,
    GroveOptions,
    MoldMode,
    MoldOptions,
)

__all__ = ["DressingOptionsPanel"]

_GROVE_ROWS = 5


def _spin(
    low: float, high: float, value: float, decimals: int = 1, suffix: str = ""
) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class DressingOptionsPanel(QWidget):
    mold_apply_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.title = QLabel()
        layout.addWidget(self.title)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        layout.addStretch(1)
        self._pages: dict[str, tuple[int, str]] = {}

        scorch = QWidget()
        form = QFormLayout(scorch)
        self.scorch_type = QComboBox()
        self.scorch_type.addItems(list(SCORCH_TYPES))
        form.addRow("Scorch", self.scorch_type)
        self.scorch_size = _spin(1.0, 256.0, DEFAULT_SCORCH_SIZE)
        form.addRow("Scorch size", self.scorch_size)
        form.addRow(_note("Click to add a scorch mark, or drag from the spot to size it."))
        self._add_page("scorch", "Scorch Options", scorch)

        grove = QWidget()
        grid = QGridLayout(grove)
        grid.addWidget(QLabel("%"), 0, 0)
        grid.addWidget(QLabel("Tree type"), 0, 1)
        self.grove_trees: list[QComboBox] = []
        self.grove_weights: list[QSpinBox] = []
        for row in range(_GROVE_ROWS):
            weight = QSpinBox()
            weight.setRange(0, 100)
            weight.valueChanged.connect(lambda _value: self._show_grove_total())
            tree = QComboBox()
            tree.setEditable(True)
            grid.addWidget(weight, row + 1, 0)
            grid.addWidget(tree, row + 1, 1)
            self.grove_weights.append(weight)
            self.grove_trees.append(tree)
        self.grove_total = QLabel()
        grid.addWidget(self.grove_total, _GROVE_ROWS + 1, 0, 1, 2)
        self.grove_count = QSpinBox()
        self.grove_count.setRange(1, 1000)
        self.grove_count.setValue(10)
        grid.addWidget(QLabel("Total tree count"), _GROVE_ROWS + 2, 0)
        grid.addWidget(self.grove_count, _GROVE_ROWS + 2, 1)
        self.grove_water = QCheckBox("Allow water placement")
        self.grove_cliffs = QCheckBox("Allow cliff placement")
        self.grove_align = QCheckBox("Align to terrain")
        for offset, box in enumerate((self.grove_water, self.grove_cliffs, self.grove_align)):
            grid.addWidget(box, _GROVE_ROWS + 3 + offset, 0, 1, 2)
        grid.addWidget(
            _note(
                "Click to place random foliage, drag to place foliage in a rectangular area. "
                "Use Terrain Objects is not supported."
            ),
            _GROVE_ROWS + 6,
            0,
            1,
            2,
        )
        self._add_page("grove", "Grove Options", grove)
        self._show_grove_total()

        fence = QWidget()
        form = QFormLayout(fence)
        self.fence_object = QLabel()
        form.addRow("Object", self.fence_object)
        self.fence_spacing_box = _spin(1.0, 1000.0, DEFAULT_FENCE_SPACING, 2)
        form.addRow("Fence spacing", self.fence_spacing_box)
        form.addRow(
            _note(
                "Choose the object in the Object Palette. Drag to place a row of it; hold Shift "
                "as you let go to stretch the row out to the end of the drag."
            )
        )
        self._add_page("fence", "Fence Options", fence)
        self.set_fence_object(None)

        ramp = QWidget()
        form = QFormLayout(ramp)
        self.ramp_width_box = _spin(1.0, 1000.0, DEFAULT_RAMP_WIDTH)
        form.addRow("Ramp width", self.ramp_width_box)
        form.addRow(
            _note(
                "Drag from one end of the ramp to the other: the ground under it becomes a slope."
            )
        )
        self._add_page("ramp", "Ramp Options", ramp)

        border = QWidget()
        column = QVBoxLayout(border)
        column.addWidget(
            _note(
                "Click to add a border reaching from the map's corner to the spot. Drag a border's "
                "corner handle to resize it; Alt-click a handle to remove that border."
            )
        )
        self._add_page("border", "Border Tool", border)

        mold = QWidget()
        form = QFormLayout(mold)
        self.mold_box = QComboBox()
        form.addRow("Mold", self.mold_box)
        self.mold_scale = _spin(1.0, 400.0, 100.0, 0, " %")
        form.addRow("Scale", self.mold_scale)
        self.mold_height = _spin(-2000.0, 2000.0, 0.0, 1, " ft")
        form.addRow("Height", self.mold_height)
        self.mold_angle = _spin(-180.0, 180.0, 0.0, 0, "°")
        form.addRow("Angle", self.mold_angle)
        self.mold_modes = QButtonGroup(self)
        self._mold_mode_buttons: dict[MoldMode, QRadioButton] = {}
        for mode in (MoldMode.RAISE, MoldMode.LOWER, MoldMode.BOTH):
            button = QRadioButton(mode.value)
            self.mold_modes.addButton(button)
            form.addRow(button)
            self._mold_mode_buttons[mode] = button
        self._mold_mode_buttons[MoldMode.BOTH].setChecked(True)
        self.mold_apply = QPushButton("Apply")
        self.mold_apply.clicked.connect(self.mold_apply_requested.emit)
        form.addRow(self.mold_apply)
        form.addRow(_note("Click the map to place the mold, then Apply."))
        self._add_page("mesh mold", "Mesh Mold Options", mold)
        self.show_page("scorch")

    def _add_page(self, name: str, title: str, page: QWidget) -> None:
        self._pages[name] = (self.stack.addWidget(page), title)

    def show_page(self, name: str) -> None:
        index, title = self._pages[name]
        self.stack.setCurrentIndex(index)
        self.title.setText(f"<b>{title}</b>")

    def scorch_settings(self) -> tuple[int, float]:
        return self.scorch_type.currentIndex(), self.scorch_size.value()

    def set_tree_choices(self, names: list[str]) -> None:
        for combo in self.grove_trees:
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.setCurrentText(current)
            combo.blockSignals(False)

    def set_grove_trees(self, trees: list[tuple[str, int]]) -> None:
        for row in range(_GROVE_ROWS):
            name, weight = trees[row] if row < len(trees) else ("", 0)
            self.grove_trees[row].setCurrentText(name)
            self.grove_weights[row].setValue(weight)

    def grove_settings(self) -> GroveOptions:
        return GroveOptions(
            trees=[
                (combo.currentText().strip(), weight.value())
                for combo, weight in zip(self.grove_trees, self.grove_weights, strict=True)
            ],
            count=self.grove_count.value(),
            allow_water=self.grove_water.isChecked(),
            allow_cliffs=self.grove_cliffs.isChecked(),
            align_to_terrain=self.grove_align.isChecked(),
        )

    def _show_grove_total(self) -> None:
        total = sum(weight.value() for weight in self.grove_weights)
        self.grove_total.setText(f"{total} % total")

    def set_fence_object(self, name: str | None) -> None:
        self.fence_object.setText(name if name else "(choose one in the Object Palette)")

    def fence_spacing(self) -> float:
        return self.fence_spacing_box.value()

    def ramp_width(self) -> float:
        return self.ramp_width_box.value()

    def set_molds(self, names: list[str]) -> None:
        current = self.mold_box.currentText()
        self.mold_box.clear()
        self.mold_box.addItems(names)
        if current in names:
            self.mold_box.setCurrentText(current)

    def mold_settings(self) -> MoldOptions:
        mode = next(
            (mode for mode, button in self._mold_mode_buttons.items() if button.isChecked()),
            MoldMode.BOTH,
        )
        return MoldOptions(
            mold=self.mold_box.currentText(),
            scale=self.mold_scale.value() / 100,
            height=self.mold_height.value(),
            angle=self.mold_angle.value(),
            mode=mode,
        )
