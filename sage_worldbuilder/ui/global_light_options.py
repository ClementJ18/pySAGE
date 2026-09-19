"""The Global Light Options panel: WorldBuilder's Global Light Options (154) and Shadow Options
(172) dialogs in one place.

It edits the map's lights for its own time of day (Map Settings changes the time): for the chosen
target, the sun's ambient colour and each light's colour, heading and elevation, with Restore To
Default; and for the whole map, 2X overbright lighting, bloom with its infantry, terrain and objects
colours, the no-cloud factor, and the shadow colour with its intensity (the colour's alpha).
Every change is an undoable edit.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.global_lighting import GlobalLighting, MapColorArgb
from sage_worldbuilder.lighting import (
    LightSlot,
    LightTarget,
    angles_to_direction,
    current_configuration,
    direction_to_angles,
    light,
    restore_default_lights,
    set_light,
    set_lighting,
)
from sage_worldbuilder.ui.host import PanelHost

__all__ = ["ColorButton", "GlobalLightOptionsPanel"]

Vector = tuple[float, float, float]


class ColorButton(QPushButton):
    """A button showing a colour of 0-1 floats; clicking it picks another."""

    chosen = pyqtSignal(object)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.color: Vector = (0.0, 0.0, 0.0)
        self.clicked.connect(self._pick)

    def set_color(self, color: Sequence[float]) -> None:
        self.color = (float(color[0]), float(color[1]), float(color[2]))
        red, green, blue = (_byte(value) for value in self.color)
        self.setText(f"{red}, {green}, {blue}")
        text = "black" if red * 0.3 + green * 0.59 + blue * 0.11 > 140 else "white"
        self.setStyleSheet(f"background-color: rgb({red}, {green}, {blue}); color: {text};")

    def choose(self, color: Sequence[float]) -> None:
        """Take a colour as if picked, and report it."""
        self.set_color(color)
        self.chosen.emit(self.color)

    def _pick(self) -> None:
        red, green, blue = (_byte(value) for value in self.color)
        picked = QColorDialog.getColor(QColor(red, green, blue), self, self.title)
        if picked.isValid():
            self.choose((picked.red() / 255, picked.green() / 255, picked.blue() / 255))


def _byte(value: float) -> int:
    return max(0, min(255, round(value * 255)))


def _angle_box(high: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0.0, high)
    box.setDecimals(1)
    box.setSuffix("°")
    return box


class GlobalLightOptionsPanel(QWidget):
    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._updating = False
        layout = QVBoxLayout(self)
        self.time_label = QLabel()
        layout.addWidget(self.time_label)
        form = QFormLayout()
        self.target_box = QComboBox()
        self.target_box.addItems([target.value for target in LightTarget])
        self.target_box.currentIndexChanged.connect(lambda _index: self.refresh())
        form.addRow("Lighting applies to", self.target_box)
        layout.addLayout(form)

        lights = QGroupBox("Lights")
        grid = QGridLayout(lights)
        for column, title in enumerate(("", "Color", "Heading", "Elevation")):
            grid.addWidget(QLabel(title), 0, column)
        self.ambient_button = ColorButton("Ambient")
        self.ambient_button.chosen.connect(
            lambda color: self._set_light(LightSlot.SUN, "ambient", color)
        )
        grid.addWidget(QLabel("Ambient"), 1, 0)
        grid.addWidget(self.ambient_button, 1, 1)
        self.color_buttons: dict[LightSlot, ColorButton] = {}
        self.heading_boxes: dict[LightSlot, QDoubleSpinBox] = {}
        self.elevation_boxes: dict[LightSlot, QDoubleSpinBox] = {}
        for row, slot in enumerate(LightSlot, start=2):
            button = ColorButton(slot.value)
            button.chosen.connect(lambda color, slot=slot: self._set_light(slot, "color", color))
            heading, elevation = _angle_box(359.9), _angle_box(90.0)
            for box in (heading, elevation):
                box.editingFinished.connect(lambda slot=slot: self._set_direction(slot))
            grid.addWidget(QLabel(slot.value), row, 0)
            grid.addWidget(button, row, 1)
            grid.addWidget(heading, row, 2)
            grid.addWidget(elevation, row, 3)
            self.color_buttons[slot] = button
            self.heading_boxes[slot] = heading
            self.elevation_boxes[slot] = elevation
        self.restore_button = QPushButton("Restore To Default")
        self.restore_button.clicked.connect(self.restore_defaults)
        grid.addWidget(self.restore_button, len(LightSlot) + 2, 0, 1, 4)
        layout.addWidget(lights)

        effects = QGroupBox("Lighting effects")
        effects_form = QFormLayout(effects)
        self.overbright_box = QCheckBox("Enable 2X overbright lighting")
        self.overbright_box.toggled.connect(lambda on: self._set("overbright", 2.0 if on else 1.0))
        effects_form.addRow(self.overbright_box)
        self.bloom_box = QCheckBox("Enable bloom lighting effect")
        self.bloom_box.toggled.connect(lambda on: self._set("bloom_enabled", int(on)))
        effects_form.addRow(self.bloom_box)
        self.bloom_buttons: dict[str, ColorButton] = {}
        for field, label in (
            ("bloom_infantry", "Bloom: infantry"),
            ("bloom_terrain", "Bloom: terrain"),
            ("bloom_objects", "Bloom: objects"),
        ):
            button = ColorButton(label)
            button.chosen.connect(lambda color, field=field: self._set(field, color))
            effects_form.addRow(label, button)
            self.bloom_buttons[field] = button
        self.cloud_button = ColorButton("No cloud factor")
        self.cloud_button.chosen.connect(lambda color: self._set("no_cloud_factor", color))
        effects_form.addRow("No cloud factor", self.cloud_button)
        layout.addWidget(effects)

        shadows = QGroupBox("Shadows")
        shadow_form = QFormLayout(shadows)
        self.shadow_button = ColorButton("Shadow color")
        self.shadow_button.chosen.connect(lambda _color: self._set_shadow())
        shadow_form.addRow("Shadow color", self.shadow_button)
        self.intensity_box = QSpinBox()
        self.intensity_box.setRange(0, 255)
        self.intensity_box.editingFinished.connect(self._set_shadow)
        shadow_form.addRow("Shadow intensity", self.intensity_box)
        layout.addWidget(shadows)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addStretch(1)
        self._effects, self._shadows = effects, shadows
        self.refresh()

    @property
    def target(self) -> LightTarget:
        return list(LightTarget)[max(self.target_box.currentIndex(), 0)]

    def _lighting(self) -> GlobalLighting | None:
        document = self.host.document
        return document.map.global_lighting if document is not None else None

    def refresh(self) -> None:
        lighting = self._lighting()
        self._updating = True
        try:
            self.setEnabled(lighting is not None)
            if lighting is None:
                self.time_label.setText("This map has no lighting.")
                return
            self.time_label.setText(f"Time of day: {lighting.time_of_the_day.name}")
            configuration = current_configuration(lighting)
            sun = light(configuration, self.target, LightSlot.SUN)
            self.ambient_button.setEnabled(sun is not None)
            if sun is not None:
                self.ambient_button.set_color(sun.ambient)
            for slot in LightSlot:
                found = light(configuration, self.target, slot)
                for widget in (
                    self.color_buttons[slot],
                    self.heading_boxes[slot],
                    self.elevation_boxes[slot],
                ):
                    widget.setEnabled(found is not None)
                if found is None:
                    continue
                self.color_buttons[slot].set_color(found.color)
                heading, elevation = direction_to_angles(found.direction)
                self.heading_boxes[slot].setValue(round(heading, 1) % 360.0)
                self.elevation_boxes[slot].setValue(round(elevation, 1))
            self._effects.setEnabled(lighting.overbright is not None)
            if lighting.overbright is not None:
                self.overbright_box.setChecked(lighting.overbright > 1.0)
            self.bloom_box.setEnabled(lighting.bloom_enabled is not None)
            self.bloom_box.setChecked(bool(lighting.bloom_enabled))
            for field, button in self.bloom_buttons.items():
                value = getattr(lighting, field)
                button.setEnabled(value is not None)
                if value is not None:
                    button.set_color(value)
            self.cloud_button.setEnabled(lighting.no_cloud_factor is not None)
            if lighting.no_cloud_factor is not None:
                self.cloud_button.set_color(lighting.no_cloud_factor)
            shadow = lighting.shadow_color
            self._shadows.setEnabled(shadow is not None)
            if shadow is not None:
                self.shadow_button.set_color((shadow.r / 255, shadow.g / 255, shadow.b / 255))
                self.intensity_box.setValue(shadow.a)
            self.note.setText(
                "Everything changes the terrain's, objects' and infantry's lights together, and "
                "shows the objects' lights."
                if self.target is LightTarget.EVERYTHING
                else ""
            )
        finally:
            self._updating = False

    def _set_light(self, slot: LightSlot, field: str, value: Vector) -> None:
        lighting = self._lighting()
        if self._updating or lighting is None:
            return
        command = set_light(current_configuration(lighting), self.target, slot, field, value)
        if command.commands:
            self.host.execute(command)

    def _set_direction(self, slot: LightSlot) -> None:
        heading = self.heading_boxes[slot].value()
        elevation = self.elevation_boxes[slot].value()
        lighting = self._lighting()
        found = light(current_configuration(lighting), self.target, slot) if lighting else None
        if found is None:
            return
        # Boxes left as shown (to 0.1 degree) keep the stored direction exactly.
        shown_heading, shown_elevation = direction_to_angles(found.direction)
        if (round(shown_heading, 1) % 360.0, round(shown_elevation, 1)) == (heading, elevation):
            return
        self._set_light(slot, "direction", angles_to_direction(heading, elevation))

    def _set(self, field: str, value: object) -> None:
        lighting = self._lighting()
        if self._updating or lighting is None or getattr(lighting, field) == value:
            return
        self.host.execute(set_lighting(lighting, field, value))

    def _set_shadow(self) -> None:
        lighting = self._lighting()
        if self._updating or lighting is None or lighting.shadow_color is None:
            return
        red, green, blue = (_byte(value) for value in self.shadow_button.color)
        color = MapColorArgb(self.intensity_box.value(), red, green, blue)
        if color != lighting.shadow_color:
            self.host.execute(set_lighting(lighting, "shadow_color", color, "Edit Shadows"))

    def restore_defaults(self) -> None:
        lighting = self._lighting()
        if lighting is None:
            return
        command = restore_default_lights(lighting, self.target)
        if command.commands:
            self.host.execute(command)
