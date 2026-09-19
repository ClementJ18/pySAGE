"""The dialogs of WorldBuilder's map data export and import: Export Options (194), Reanchor Import
(257), Duplicate Object / Waypoint / Area Trigger Detected (253-255) and Select a valid Player
(226)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.exchange import DuplicateKind, DuplicatePolicy, ExportOptions, ScriptsMode
from sage_worldbuilder.heightmap_io import Anchor

__all__ = ["ExportOptionsDialog", "ReanchorDialog", "ask_duplicate", "ask_team_player"]

_INCLUDES = (
    ("terrain_texture", "Include terrain texture"),
    ("terrain_height", "Include terrain height"),
    ("selected_objects", "Include all selected objects"),
    ("all_waypoints", "Include all waypoints and waypoint paths"),
    ("all_areas", "Include all trigger areas"),
    ("water", "Include all water areas"),
    ("lighting", "Include lighting"),
    ("all_players", "Include all players"),
    ("passability", "Include passability"),
)
_SCRIPTS = (
    (ScriptsMode.NONE, "Export no scripts"),
    (ScriptsMode.ALL, "Export all scripts"),
    (ScriptsMode.SELECTED, "Export selected scripts"),
)
_REFERENCED = (
    ("referenced_waypoints", "Include waypoints and waypoint paths"),
    ("referenced_areas", "Include trigger areas"),
    ("referenced_objects", "Include units and buildings"),
)
_NOUNS = {
    DuplicateKind.OBJECT: ("Object", "object"),
    DuplicateKind.WAYPOINT: ("Waypoint", "waypoint"),
    DuplicateKind.AREA: ("Area Trigger", "area"),
}


def _shown_player(name: str, display: str) -> str:
    """A player as the dialog lists it: `name="display name"`, or `(neutral)`."""
    return "(neutral)" if not name else f'{name}="{display}"'


class ExportOptionsDialog(QDialog):
    def __init__(
        self,
        players: Sequence[tuple[str, str]],
        options: ExportOptions,
        *,
        has_selected_scripts: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Options")
        layout = QVBoxLayout(self)
        self.includes: dict[str, QCheckBox] = {}
        for name, text in _INCLUDES:
            box = QCheckBox(text)
            box.setChecked(bool(getattr(options, name)))
            layout.addWidget(box)
            self.includes[name] = box

        layout.addWidget(QLabel("Include all units belonging to the following players:"))
        self.players = QListWidget()
        for name, display in players:
            item = QListWidgetItem(_shown_player(name, display))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in options.players else Qt.CheckState.Unchecked
            )
            self.players.addItem(item)
        layout.addWidget(self.players)

        scripts = QGroupBox("Scripts")
        scripts_layout = QVBoxLayout(scripts)
        self.scripts = QButtonGroup(self)
        for mode, text in _SCRIPTS:
            button = QRadioButton(text)
            button.setChecked(mode is options.scripts)
            if mode is ScriptsMode.SELECTED:
                button.setEnabled(has_selected_scripts)
            self.scripts.addButton(button, int(mode))
            scripts_layout.addWidget(button)
        layout.addWidget(scripts)

        referenced = QGroupBox("Include items referenced in exported scripts")
        referenced_layout = QVBoxLayout(referenced)
        self.referenced: dict[str, QCheckBox] = {}
        for name, text in _REFERENCED:
            box = QCheckBox(text)
            box.setChecked(bool(getattr(options, name)))
            referenced_layout.addWidget(box)
            self.referenced[name] = box
        layout.addWidget(referenced)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def options(self) -> ExportOptions:
        values: dict[str, object] = {
            name: box.isChecked() for name, box in {**self.includes, **self.referenced}.items()
        }
        values["players"] = frozenset(
            self.players.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.players.count())
            if self.players.item(row).checkState() == Qt.CheckState.Checked
        )
        checked = self.scripts.checkedId()
        values["scripts"] = ScriptsMode(checked) if checked >= 0 else ScriptsMode.ALL
        known = {field.name for field in fields(ExportOptions)}
        return ExportOptions(**{name: value for name, value in values.items() if name in known})  # type: ignore[arg-type]


class ReanchorDialog(QDialog):
    def __init__(
        self,
        imported: tuple[int, int],
        current: tuple[int, int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reanchor Import")
        layout = QVBoxLayout(self)
        message = QLabel(
            "The size of the imported data does not match the size of the current map."
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        sizes = QFormLayout()
        sizes.addRow("Imported data:", QLabel(f"Width: {imported[0]}   Height: {imported[1]}"))
        sizes.addRow("Current map:", QLabel(f"Width: {current[0]}   Height: {current[1]}"))
        layout.addLayout(sizes)
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        group = QButtonGroup(self)
        self.anchor_buttons: dict[Anchor, QRadioButton] = {}
        for anchor in Anchor:
            column, row_from_bottom = anchor.value
            button = QRadioButton()
            button.setToolTip(anchor.name.replace("_", " ").title())
            group.addButton(button)
            grid.addWidget(button, 2 - row_from_bottom, column)
            self.anchor_buttons[anchor] = button
        self.anchor_buttons[Anchor.CENTER].setChecked(True)
        anchor_row = QFormLayout()
        anchor_row.addRow("Anchor:", grid_widget)
        layout.addLayout(anchor_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def anchor(self) -> Anchor:
        return next(
            (anchor for anchor, button in self.anchor_buttons.items() if button.isChecked()),
            Anchor.CENTER,
        )


def ask_duplicate(
    parent: QWidget | None, kind: DuplicateKind, name: str
) -> tuple[DuplicatePolicy, bool] | None:
    """Which of two same-named items to keep, and whether for every duplicate of the kind; `None`
    cancels the import."""
    title, noun = _NOUNS[kind]
    box = QMessageBox(parent)
    box.setWindowTitle(f"Duplicate {title} Detected")
    box.setText(f'The map already has a {noun} named "{name}".')
    existing = box.addButton(f"Keep existing {noun}", QMessageBox.ButtonRole.AcceptRole)
    imported = box.addButton(f"Keep imported {noun}", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    apply_to_all = QCheckBox("Apply to all")
    box.setCheckBox(apply_to_all)
    box.exec()
    clicked = box.clickedButton()
    if clicked is existing:
        return DuplicatePolicy.KEEP_EXISTING, apply_to_all.isChecked()
    if clicked is imported:
        return DuplicatePolicy.KEEP_IMPORTED, apply_to_all.isChecked()
    return None


def ask_team_player(
    parent: QWidget | None, team: str, owner: str, players: Sequence[str]
) -> str | None:
    """The player a team goes to when the map lacks its own; `None` leaves the team out."""
    labels = ["(neutral)" if not name else name for name in players]
    label, accepted = QInputDialog.getItem(
        parent,
        "Select a valid Player",
        f"Importing team {team} of player {owner}. Player {owner} doesn't exist, select player.",
        labels,
        0,
        False,
    )
    if not accepted or label not in labels:
        return None
    return players[labels.index(label)]
