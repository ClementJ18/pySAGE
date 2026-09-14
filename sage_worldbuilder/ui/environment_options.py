"""The Environment Options panel: WorldBuilder's Select Macrotexture (152), Select Cloudtexture
(238), Edit Skybox (239) and Post Effects Options (277, 278) dialogs in one place.

It edits the map's `EnvironmentData` macro texture (and, for chunk versions that store it, whether
the macro texture is stretched over the map) and cloud texture, and its post effect. Every corpus
map with a post effect has exactly one, a `LookupTablePostEffect` with a blend factor and a volume
texture (the lookup image); turning Post Effects on adds one with the values most such maps store,
a blend factor of 1 and `Default_vol.tga`. Every change is an undoable edit.

The skybox is the map's `SkyboxSettings` chunk: a position, scale, rotation and texture scheme (a
`SkyboxTextureSet`), as the Edit Skybox dialog shows them; Center Skybox On Camera moves it to what
the view looks at. No corpus map stores the chunk, so "Use a skybox" adds one, at version 1 with a
scale of 1 and no rotation (choices: WorldBuilder's reader was not found), and removes it again.
The view does not draw the skybox.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.post_effects_chunk import PostEffect
from sage_map.assets.skybox_settings import SkyboxSettings
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import CompositeCommand, SetAttribute
from sage_worldbuilder.commands.edits import InsertItem, RemoveItem
from sage_worldbuilder.ui.host import PanelHost

__all__ = ["LOOKUP_TABLE_EFFECT", "SKYBOX_VERSION", "EnvironmentOptionsPanel"]

SETTINGS = Change(ChangeKind.SETTINGS)
LOOKUP_TABLE_EFFECT = "LookupTablePostEffect"
_DEFAULT_BLEND = 1.0
_DEFAULT_LOOKUP = "Default_vol.tga"
SKYBOX_VERSION = 1
_COORDINATE_LIMIT = 1e6


def _number_box(low: float, high: float, decimals: int = 2) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    return box


class EnvironmentOptionsPanel(QWidget):
    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._updating = False
        # What the view looks at, for Center Skybox On Camera; set by the window.
        self.camera_target: Callable[[], tuple[float, float, float]] | None = None
        layout = QVBoxLayout(self)

        textures = QGroupBox("Textures")
        form = QFormLayout(textures)
        self.macro_edit = QLineEdit()
        self.macro_edit.editingFinished.connect(
            lambda: self._set_environment("macro_texture", self.macro_edit.text().strip())
        )
        form.addRow("Macrotexture", self.macro_edit)
        self.stretch_box = QCheckBox("Stretch the macrotexture over the map")
        self.stretch_box.toggled.connect(
            lambda on: self._set_environment("is_macro_texture_stretched", on)
        )
        form.addRow(self.stretch_box)
        self.cloud_edit = QLineEdit()
        self.cloud_edit.editingFinished.connect(
            lambda: self._set_environment("cloud_texture", self.cloud_edit.text().strip())
        )
        form.addRow("Cloud texture", self.cloud_edit)
        layout.addWidget(textures)

        self.skybox_group = QGroupBox("Skybox")
        skybox_form = QFormLayout(self.skybox_group)
        self.skybox_box = QCheckBox("Use a skybox")
        self.skybox_box.toggled.connect(self._enable_skybox)
        skybox_form.addRow(self.skybox_box)
        position = QHBoxLayout()
        self.skybox_position = [_number_box(-_COORDINATE_LIMIT, _COORDINATE_LIMIT) for _ in "xyz"]
        for box in self.skybox_position:
            box.editingFinished.connect(self._set_skybox_position)
            position.addWidget(box)
        skybox_form.addRow("Position (X, Y, Z)", position)
        self.center_skybox_button = QPushButton("Center Skybox On Camera")
        self.center_skybox_button.clicked.connect(self.center_skybox_on_camera)
        skybox_form.addRow(self.center_skybox_button)
        self.skybox_scale = _number_box(0.0, 1000.0, 3)
        self.skybox_scale.editingFinished.connect(
            lambda: self._set_skybox("scale", self.skybox_scale.value())
        )
        skybox_form.addRow("Scale", self.skybox_scale)
        self.skybox_rotation = _number_box(-1000.0, 1000.0, 3)
        self.skybox_rotation.editingFinished.connect(
            lambda: self._set_skybox("rotation", self.skybox_rotation.value())
        )
        skybox_form.addRow("Rotation", self.skybox_rotation)
        self.skybox_scheme = QComboBox()
        self.skybox_scheme.setEditable(True)
        self.skybox_scheme.activated.connect(lambda _index: self._set_scheme())
        line_edit = self.skybox_scheme.lineEdit()
        if line_edit is not None:
            line_edit.editingFinished.connect(self._set_scheme)
        skybox_form.addRow("Texture scheme", self.skybox_scheme)
        layout.addWidget(self.skybox_group)

        self.post_box = QGroupBox("Post effect")
        post_form = QFormLayout(self.post_box)
        self.enable_box = QCheckBox("Enable post effects")
        self.enable_box.toggled.connect(self._enable_post_effects)
        post_form.addRow(self.enable_box)
        self.blend_box = QDoubleSpinBox()
        self.blend_box.setRange(0.0, 1.0)
        self.blend_box.setDecimals(3)
        self.blend_box.setSingleStep(0.05)
        self.blend_box.editingFinished.connect(
            lambda: self._set_effect("blend_factor", self.blend_box.value())
        )
        post_form.addRow("Blend factor", self.blend_box)
        self.lookup_edit = QLineEdit()
        self.lookup_edit.editingFinished.connect(
            lambda: self._set_effect("lookup_image", self.lookup_edit.text().strip())
        )
        post_form.addRow("Volume texture (lookup image)", self.lookup_edit)
        layout.addWidget(self.post_box)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addStretch(1)
        self.refresh()

    def _effects(self) -> list[PostEffect] | None:
        document = self.host.document
        chunk = document.map.post_effects_chunk if document is not None else None
        return chunk.post_effects if chunk is not None and chunk.version < 2 else None

    def _skybox(self) -> SkyboxSettings | None:
        document = self.host.document
        return document.map.skybox_settings if document is not None else None

    def set_skybox_schemes(self, names: Sequence[str]) -> None:
        """Offer the game's `SkyboxTextureSet` names as texture schemes."""
        self._updating = True
        try:
            self.skybox_scheme.clear()
            self.skybox_scheme.addItems(sorted(names, key=str.lower))
        finally:
            self._updating = False
        self.refresh()

    def refresh(self) -> None:
        document = self.host.document
        environment = document.map.environment_data if document is not None else None
        chunk = document.map.post_effects_chunk if document is not None else None
        effects = self._effects()
        skybox = self._skybox()
        self._updating = True
        try:
            for widget in (self.macro_edit, self.cloud_edit):
                widget.setEnabled(environment is not None)
            self.macro_edit.setText(environment.macro_texture if environment is not None else "")
            self.cloud_edit.setText(environment.cloud_texture if environment is not None else "")
            stretched = environment.is_macro_texture_stretched if environment is not None else None
            self.stretch_box.setVisible(stretched is not None)
            self.stretch_box.setChecked(bool(stretched))

            self.skybox_group.setEnabled(document is not None)
            self.skybox_box.setChecked(skybox is not None)
            for widget in (
                *self.skybox_position,
                self.center_skybox_button,
                self.skybox_scale,
                self.skybox_rotation,
                self.skybox_scheme,
            ):
                widget.setEnabled(skybox is not None)
            if skybox is not None:
                for box, value in zip(self.skybox_position, skybox.position, strict=True):
                    box.setValue(value)
                self.skybox_scale.setValue(skybox.scale)
                self.skybox_rotation.setValue(skybox.rotation)
                self.skybox_scheme.setCurrentText(skybox.texture_scheme)

            self.post_box.setEnabled(effects is not None)
            effect = effects[0] if effects else None
            self.enable_box.setChecked(effect is not None)
            for widget in (self.blend_box, self.lookup_edit):
                widget.setEnabled(effect is not None)
            self.blend_box.setValue(effect.blend_factor or 0.0 if effect is not None else 0.0)
            self.lookup_edit.setText(effect.lookup_image or "" if effect is not None else "")
            if chunk is not None and effects is None:
                self.note.setText(
                    "This map's post effects are stored with parameters (chunk version "
                    f"{chunk.version}), which this panel does not edit."
                )
            elif effects is not None and len(effects) > 1:
                self.note.setText(f"This map has {len(effects)} post effects; the first is shown.")
            else:
                self.note.setText("")
        finally:
            self._updating = False

    def _set_environment(self, field: str, value: object) -> None:
        document = self.host.document
        environment = document.map.environment_data if document is not None else None
        if self._updating or environment is None or getattr(environment, field) == value:
            return
        self.host.execute(SetAttribute(environment, field, value, SETTINGS))

    def _enable_skybox(self, on: bool) -> None:
        document = self.host.document
        if self._updating or document is None or (self._skybox() is not None) == on:
            return
        if on:
            scheme = self.skybox_scheme.itemText(0) if self.skybox_scheme.count() else ""
            skybox: SkyboxSettings | None = SkyboxSettings(
                version=SKYBOX_VERSION,
                position=self._camera_target(),
                scale=1.0,
                rotation=0.0,
                texture_scheme=scheme,
                start_pos=0,
                end_pos=0,
            )
            label = "Add Skybox"
        else:
            skybox, label = None, "Remove Skybox"
        self.host.execute(SetAttribute(document.map, "skybox_settings", skybox, SETTINGS, label))

    def _camera_target(self) -> tuple[float, float, float]:
        if self.camera_target is None:
            return (0.0, 0.0, 0.0)
        x, y, z = self.camera_target()
        return (float(x), float(y), float(z))

    def _set_skybox(self, field: str, value: object) -> None:
        skybox = self._skybox()
        if self._updating or skybox is None or getattr(skybox, field) == value:
            return
        self.host.execute(SetAttribute(skybox, field, value, SETTINGS, "Edit Skybox"))

    def _set_skybox_position(self) -> None:
        position = tuple(box.value() for box in self.skybox_position)
        self._set_skybox("position", position)

    def _set_scheme(self) -> None:
        self._set_skybox("texture_scheme", self.skybox_scheme.currentText().strip())

    def center_skybox_on_camera(self) -> None:
        self._set_skybox("position", self._camera_target())

    def _set_effect(self, field: str, value: object) -> None:
        effects = self._effects()
        if self._updating or not effects or getattr(effects[0], field) == value:
            return
        self.host.execute(SetAttribute(effects[0], field, value, SETTINGS, "Edit Post Effects"))

    def _enable_post_effects(self, on: bool) -> None:
        effects = self._effects()
        if self._updating or effects is None or bool(effects) == on:
            return
        label = "Enable Post Effects" if on else "Disable Post Effects"
        if on:
            effect = PostEffect(LOOKUP_TABLE_EFFECT, None, _DEFAULT_BLEND, _DEFAULT_LOOKUP)
            self.host.execute(InsertItem(effects, 0, effect, SETTINGS, label))
            return
        removals = [
            RemoveItem(effects, index, SETTINGS, label) for index in reversed(range(len(effects)))
        ]
        self.host.execute(CompositeCommand(label, removals))
