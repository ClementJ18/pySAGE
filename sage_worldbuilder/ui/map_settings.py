"""The Map Settings and Multiplayer Positions panels."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.global_lighting import TimeOfTheDay
from sage_map.assets.mp_positions import MPPosition
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import SetAttribute
from sage_worldbuilder.properties import WORLD_INFO_SPECS, set_value
from sage_worldbuilder.ui.host import PanelHost
from sage_worldbuilder.ui.property_form import PropertyForm

__all__ = ["MapSettingsPanel", "MultiplayerPositionsPanel"]

SETTINGS = Change(ChangeKind.SETTINGS)
_TIMES = list(TimeOfTheDay)
# A position's forced team is stored unsigned; 0xFFFFFFFF (-1) means it has none.
_UINT32 = 2**32


def _shown_team(stored: int) -> int:
    return stored - _UINT32 if stored >= 2**31 else stored


def _stored_team(shown: int) -> int:
    return shown + _UINT32 if shown < 0 else shown


class MapSettingsPanel(QWidget):
    """The map's own settings, its time of day, and restoring the camera's defaults."""

    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._updating = False
        layout = QVBoxLayout(self)
        self.form = PropertyForm(WORLD_INFO_SPECS, host.execute, SETTINGS)
        layout.addWidget(self.form)
        lighting = QFormLayout()
        self.time_of_day = QComboBox()
        self.time_of_day.addItems([time.name for time in _TIMES])
        self.time_of_day.currentIndexChanged.connect(self._set_time)
        lighting.addRow("Time of day", self.time_of_day)
        layout.addLayout(lighting)
        self.restore_button = QPushButton("Restore Camera Defaults")
        self.restore_button.clicked.connect(lambda _checked=False: self.restore_camera_defaults())
        layout.addWidget(self.restore_button)
        layout.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        document = self.host.document
        info = document.map.world_info if document is not None else None
        self.form.set_properties(info.properties if info is not None else None)
        lighting = document.map.global_lighting if document is not None else None
        self._updating = True
        try:
            self.time_of_day.setEnabled(lighting is not None)
            if lighting is not None:
                self.time_of_day.setCurrentIndex(_TIMES.index(lighting.time_of_the_day))
        finally:
            self._updating = False
        self.restore_button.setEnabled(info is not None)

    def _set_time(self, index: int) -> None:
        document = self.host.document
        lighting = document.map.global_lighting if document is not None else None
        if self._updating or lighting is None or not 0 <= index < len(_TIMES):
            return
        if lighting.time_of_the_day is not _TIMES[index]:
            self.host.execute(
                SetAttribute(
                    lighting, "time_of_the_day", _TIMES[index], SETTINGS, "Set time of day"
                )
            )

    def restore_camera_defaults(self) -> None:
        document = self.host.document
        info = document.map.world_info if document is not None else None
        if document is None or info is None:
            return
        with document.stack.group("Restore Camera Defaults"):
            for spec in WORLD_INFO_SPECS:
                if spec.name.startswith("camera"):
                    self.host.execute(set_value(info.properties, spec, spec.default, SETTINGS))


class MultiplayerPositionsPanel(QWidget):
    """Who may take each start position, its forced team, and the factions it may not use."""

    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._updating = False
        layout = QHBoxLayout(self)
        splitter = QSplitter()
        layout.addWidget(splitter)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(lambda _row: self._show_selected())
        splitter.addWidget(self.list)

        editor = QWidget()
        form = QFormLayout(editor)
        self.human = QCheckBox("A human may take this position")
        self.human.toggled.connect(lambda on: self._set("is_human", on))
        form.addRow("", self.human)
        self.computer = QCheckBox("A computer may take this position")
        self.computer.toggled.connect(lambda on: self._set("is_computer", on))
        form.addRow("", self.computer)
        self.load_ai_script = QCheckBox("Load the default AI scripts")
        self.load_ai_script.toggled.connect(lambda on: self._set("load_ai_script", on))
        form.addRow("", self.load_ai_script)
        self.team = QSpinBox()
        self.team.setRange(-1, 1_000)
        self.team.setSpecialValueText("none")
        self.team.valueChanged.connect(lambda value: self._set("team", _stored_team(value)))
        form.addRow("Forced team", self.team)
        self.restrictions = QLineEdit()
        self.restrictions.setPlaceholderText("Factions this position may not play, space-separated")
        self.restrictions.editingFinished.connect(
            lambda: self._set("side_restrictions", self.restrictions.text().split())
        )
        form.addRow("Restricted factions", self.restrictions)
        self.note = QLabel()
        form.addRow("", self.note)
        splitter.addWidget(editor)
        self.refresh()

    def _positions(self) -> list[MPPosition]:
        document = self.host.document
        if document is None or document.map.mp_positions_list is None:
            return []
        return document.map.mp_positions_list.positions

    def refresh(self) -> None:
        positions = self._positions()
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for index in range(len(positions)):
            self.list.addItem(f"Position {index + 1}")
        self.list.setCurrentRow(min(max(row, 0), len(positions) - 1) if positions else -1)
        self.list.blockSignals(False)
        self.note.setText("" if positions else "This map has no multiplayer positions.")
        self._show_selected()

    def _selected(self) -> MPPosition | None:
        positions = self._positions()
        row = self.list.currentRow()
        return positions[row] if 0 <= row < len(positions) else None

    def _show_selected(self) -> None:
        position = self._selected()
        self._updating = True
        try:
            for widget in (
                self.human,
                self.computer,
                self.load_ai_script,
                self.team,
                self.restrictions,
            ):
                widget.setEnabled(position is not None)
            if position is not None:
                self.human.setChecked(position.is_human)
                self.computer.setChecked(position.is_computer)
                self.load_ai_script.setChecked(bool(position.load_ai_script))
                self.team.setValue(_shown_team(position.team))
                self.restrictions.setText(" ".join(position.side_restrictions))
        finally:
            self._updating = False

    def _set(self, attribute: str, value: object) -> None:
        position = self._selected()
        if self._updating or position is None or getattr(position, attribute) == value:
            return
        self.host.execute(SetAttribute(position, attribute, value, SETTINGS))
