"""The Water Options panel: WorldBuilder's Lake/Ocean Options (273), River Options (274) and Wave
Options (279), with the name / height / scroll speed / blending pane they share (271).

It lists the map's areas of one kind (the chosen water tool's, or the selected area's) with Center
Camera, shows the chosen area's fields, and for lakes the map's own water options (Max alpha depth
and Deep water alpha, kept in the map's EnvironmentData). Every field is an undoable edit. The
texture pickers offer the game's `WaterTextureList` blocks, and accept any other name.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.river_areas import RiverArea
from sage_worldbuilder.commands import SetAttribute
from sage_worldbuilder.ui.host import PanelHost
from sage_worldbuilder.water import (
    WATER,
    WaterArea,
    WaterKind,
    set_water,
    water_areas,
    water_kind,
    water_outline,
)

__all__ = ["WaterOptionsPanel"]

# (attribute, label, editor, game texture list or choices)
_Field = tuple[str, str, str, object]
_SHARED: tuple[_Field, ...] = (("name", "Name", "text", None),)
_FIELDS: dict[WaterKind, tuple[_Field, ...]] = {
    WaterKind.LAKE: (
        *_SHARED,
        ("water_height", "Water height (ft)", "int", None),
        ("uv_scroll_speed", "UV scroll speed", "float", None),
        ("use_adaptive_blending", "Use additive blending", "bool", None),
        ("bump_map_texture", "Bumpmap texture", "texture", "WaterBumpMapTextures"),
        ("sky_texture", "Sky texture", "texture", "WaterSkyTextures"),
        ("fx_shader", "FX shader", "used", None),
        ("depth_color", "Depth colors", "used", None),
    ),
    WaterKind.RIVER: (
        *_SHARED,
        ("water_height", "Water height (ft)", "int", None),
        ("uv_scroll_speed", "UV scroll speed", "float", None),
        ("use_additive_blending", "Use additive blending", "bool", None),
        ("alpha", "Alpha", "fraction", None),
        ("color", "Color", "color", None),
        ("river_texture", "River texture", "texture", "RiverTextures"),
        ("noise_texture", "Noise texture", "texture", "RiverNoiseTextures"),
        ("alpha_edge_texture", "Alpha edge texture", "texture", "RiverAlphaEdgeTextures"),
        ("sparkle_texture", "Sparkle texture", "texture", "RiverSparkleTextures"),
        ("minimum_water_lod", "Minimum water LOD", "choice", ("", "Low", "Medium", "High")),
    ),
    WaterKind.WAVE: (
        *_SHARED,
        ("uv_scroll_speed", "UV scroll speed", "float", None),
        ("use_adaptive_blending", "Use additive blending", "bool", None),
        ("final_width", "Final width", "int", None),
        ("final_height", "Final height", "int", None),
        ("initial_width_fraction", "Initial width fraction", "int", None),
        ("initial_height_fraction", "Initial height fraction", "int", None),
        ("initial_velocity", "Initial velocity", "int", None),
        ("time_to_fade", "Time to fade", "int", None),
        ("time_to_compress", "Time to compress", "int", None),
        ("time_offset_2nd_wave", "Time offset 2nd wave", "int", None),
        ("distance_from_shore", "Distance from shore", "int", None),
        ("texture", "Texture", "text", None),
        ("enable_pca_wave", "Enable PCA wave", "bool", None),
        ("wave_particle_fx_name", "Wave particle FX", "text", None),
    ),
}


class WaterOptionsPanel(QWidget):
    # A water area chosen in the list, to select.
    area_chosen = pyqtSignal(object)
    # Center Camera: the world position to centre the views on.
    center_requested = pyqtSignal(float, float)

    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self.kind = WaterKind.LAKE
        self.area: WaterArea | None = None
        self._updating = False
        self._editors: dict[str, QWidget] = {}
        layout = QVBoxLayout(self)
        self.title = QLabel()
        layout.addWidget(self.title)
        chooser = QHBoxLayout()
        self.areas = QComboBox()
        self.areas.currentIndexChanged.connect(self._area_picked)
        chooser.addWidget(self.areas, 1)
        self.center_button = QPushButton("Center Camera")
        self.center_button.clicked.connect(self._center)
        chooser.addWidget(self.center_button)
        layout.addLayout(chooser)

        self.map_box = QGroupBox("Map options")
        map_form = QFormLayout(self.map_box)
        self.alpha_depth = _float_box(0.0, 1000.0, 2)
        self.alpha_depth.valueChanged.connect(
            lambda value: self._set_environment("water_max_alpha_depth", value)
        )
        map_form.addRow("Max alpha depth (ft)", self.alpha_depth)
        self.deep_alpha = _float_box(0.0, 1.0, 3)
        self.deep_alpha.valueChanged.connect(
            lambda value: self._set_environment("deep_water_alpha", value)
        )
        map_form.addRow("Deep water alpha", self.deep_alpha)
        layout.addWidget(self.map_box)

        self.area_box = QGroupBox("Area")
        self.form = QFormLayout(self.area_box)
        layout.addWidget(self.area_box)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addStretch(1)
        self.refresh()

    def set_kind(self, kind: WaterKind) -> None:
        if kind is not self.kind:
            self.kind = kind
            self.area = None
            self.refresh()

    def show_area(self, area: WaterArea | None) -> None:
        """Show an area's fields (switching to its kind), or none."""
        kind = water_kind(area)
        if kind is not None:
            self.kind = kind
        self.area = area
        self.refresh()

    def refresh(self) -> None:
        document = self.host.document
        listed = water_areas(document.map, self.kind) if document is not None else None
        if self.area is not None and (listed is None or all(a is not self.area for a in listed)):
            self.area = None
        self._updating = True
        try:
            self.title.setText(f"{self.kind.value} areas")
            self.areas.clear()
            self.areas.addItem("(none)", None)
            for area in listed or []:
                self.areas.addItem(f"{area.name} ({area.unique_id})", area)
            index = next(
                (i for i in range(1, self.areas.count()) if self.areas.itemData(i) is self.area), 0
            )
            self.areas.setCurrentIndex(index)
            self.center_button.setEnabled(self.area is not None)
            environment = document.map.environment_data if document is not None else None
            has_options = (
                self.kind is WaterKind.LAKE
                and environment is not None
                and environment.water_max_alpha_depth is not None
            )
            self.map_box.setVisible(self.kind is WaterKind.LAKE)
            self.map_box.setEnabled(has_options)
            if has_options:
                assert environment is not None
                self.alpha_depth.setValue(float(environment.water_max_alpha_depth or 0.0))
                self.deep_alpha.setValue(float(environment.deep_water_alpha or 0.0))
            self._build_form()
            if listed is None:
                self.note.setText("This map has no chunk for this kind of water.")
            elif self.area is None:
                self.note.setText(_HINTS[self.kind])
            else:
                self.note.setText("")
        finally:
            self._updating = False

    def _build_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._editors = {}
        area = self.area
        self.area_box.setVisible(area is not None)
        if area is None:
            return
        for attribute, label, editor, extra in _FIELDS[self.kind]:
            value = getattr(area, attribute, None)
            if value is None:
                continue
            widget = self._editor(attribute, editor, extra, value)
            self._editors[attribute] = widget
            self.form.addRow(label, widget)

    def _editor(self, attribute: str, editor: str, extra: object, value: Any) -> QWidget:
        def setter(new: object) -> None:
            self._set(attribute, new)

        if editor == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            box.toggled.connect(setter)
            return box
        if editor == "int":
            spin = QSpinBox()
            spin.setRange(-(2**31), 2**31 - 1)
            spin.setValue(int(value))
            spin.editingFinished.connect(lambda: setter(spin.value()))
            return spin
        if editor in ("float", "fraction"):
            spin = _float_box(0.0, 1.0 if editor == "fraction" else 1000.0, 3)
            spin.setValue(float(value))
            spin.editingFinished.connect(lambda: setter(spin.value()))
            return spin
        if editor == "color":
            button = QPushButton()
            _paint_button(button, value)
            button.clicked.connect(lambda: self._choose_color(button))
            return button
        if editor in ("texture", "used", "choice"):
            combo = QComboBox()
            combo.setEditable(editor != "choice")
            names = self._choices(attribute, editor, extra)
            if value not in names:
                names = [value, *names]
            combo.addItems(names)
            combo.setCurrentText(str(value))
            if editor == "choice":
                combo.currentTextChanged.connect(setter)
            else:
                line = combo.lineEdit()
                if line is not None:
                    line.editingFinished.connect(lambda: setter(combo.currentText()))
                combo.activated.connect(lambda _index: setter(combo.currentText()))
            return combo
        line = QLineEdit(str(value))
        line.editingFinished.connect(lambda: setter(line.text()))
        return line

    def _choices(self, attribute: str, editor: str, extra: object) -> list[str]:
        if editor == "choice":
            return list(extra)  # type: ignore[call-overload]
        if editor == "texture":
            game = self.host.game
            table = getattr(game, "watertexturelists", None) or {}
            listed = table.get(extra) if isinstance(extra, str) else None
            return [str(texture) for texture in getattr(listed, "Texture", None) or []]
        document = self.host.document
        used = {
            str(getattr(area, attribute, ""))
            for area in (water_areas(document.map, self.kind) or [] if document else [])
        }
        return sorted(used, key=str.lower)

    def _choose_color(self, button: QPushButton) -> None:
        area = self.area
        if not isinstance(area, RiverArea):
            return
        chosen = QColorDialog.getColor(QColor(*area.color), self, "River color")
        if chosen.isValid():
            color = (chosen.red(), chosen.green(), chosen.blue())
            _paint_button(button, color)
            self._set("color", color)

    def _set(self, attribute: str, value: object) -> None:
        area = self.area
        if self._updating or area is None or getattr(area, attribute) == value:
            return
        self.host.execute(set_water(area, attribute, value))

    def _set_environment(self, attribute: str, value: float) -> None:
        document = self.host.document
        environment = document.map.environment_data if document is not None else None
        if self._updating or environment is None or getattr(environment, attribute) == value:
            return
        self.host.execute(SetAttribute(environment, attribute, value, WATER))

    def _area_picked(self, index: int) -> None:
        if self._updating:
            return
        area = self.areas.itemData(index)
        self.area = area
        self.refresh()
        if area is not None:
            self.area_chosen.emit(area)

    def _center(self) -> None:
        area = self.area
        points = water_outline(area) if area is not None else []
        if points:
            xs, ys = [x for x, _ in points], [y for _, y in points]
            self.center_requested.emit((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


_HINTS = {
    WaterKind.LAKE: "Lake/Ocean Tool: click corners on the map, then click the first one again; "
    "click inside a lake to choose it.",
    WaterKind.RIVER: "River Tool: drag across the river from bank to bank to add a bank line to "
    "the chosen river, or to start a new one.",
    WaterKind.WAVE: "Waves Tool: drag on the map from where a wave area starts to where it ends.",
}


def _float_box(low: float, high: float, decimals: int) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(10 ** -min(decimals, 2))
    return box


def _paint_button(button: QPushButton, color: tuple[int, int, int]) -> None:
    red, green, blue = color
    button.setText(f"{red}, {green}, {blue}")
    text = "black" if red * 0.3 + green * 0.59 + blue * 0.11 > 140 else "white"
    button.setStyleSheet(f"background-color: rgb({red}, {green}, {blue}); color: {text};")
