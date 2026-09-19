"""Jump To Game Settings: how the game is launched, and the match Jump To Game starts - the seats,
and the lobby's other options.

One row per seat: who plays it (the human, or an AI and its difficulty), the faction, the start
position, the colour and the team. Below them the starting resources and the seed. The choices are
the loaded game's own playable factions and multiplayer colours, and the start positions are the
open map's; the row is kept as it was saved when the game has not loaded, so opening the dialog
early never loses a setup.

The launch settings - a window and its size, script debugging, extra arguments - apply whether or
not a match is chosen.

The note under the table is the same check a launch makes, so a match the engine would refuse is
explained here rather than when the game fails to start the one the mapper asked for.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from sage_test.game_info import SLOT_COUNT
from sage_worldbuilder.jump import (
    MAX_RESOLUTION,
    MIN_RESOLUTION,
    SEAT_KINDS,
    TEAM_COUNT,
    JumpMatch,
    JumpMatchError,
    JumpOptions,
    JumpSeat,
    colour_names,
    default_seats,
    playable_factions,
)

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = ["JumpSettingsDialog"]

_KIND_LABELS = {
    "human": "Human (you)",
    "easy": "Easy AI",
    "medium": "Medium AI",
    "hard": "Hard AI",
    "brutal": "Brutal AI",
}
_COLUMNS = ("Player", "Faction", "Start position", "Colour", "Team")
_MAX_RESOURCES = 1_000_000
_MAX_SEED = 2**31 - 1


def _combo(
    items: list[tuple[str, object]], current: object, *, editable: bool = False
) -> QComboBox:
    """A combo of `(label, data)` items with `current` selected, added when it is not offered."""
    combo = QComboBox()
    combo.setEditable(editable)
    for label, data in items:
        combo.addItem(label, data)
    index = combo.findData(current)
    if index < 0 and current not in (None, ""):
        combo.addItem(f"{current} (not in the game data)", current)
        index = combo.count() - 1
    combo.setCurrentIndex(max(index, 0))
    return combo


class JumpSettingsDialog(QDialog):
    """Edit a `JumpMatch` and the launch `options`. `positions` is the open map's start position
    count, 0 when unknown.

    After `exec`, `match` is the edited match, `options` the launch settings (without a
    `game_info`, which comes from the match at launch) and `jump_requested` says whether Save and
    Jump was the button pressed."""

    def __init__(
        self,
        match: JumpMatch,
        game: Game | None,
        positions: int,
        parent: QWidget | None = None,
        *,
        options: JumpOptions | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Jump To Game Settings")
        self.resize(760, 600)
        self.game = game
        self.factions = playable_factions(game)
        self.colours = colour_names(game)
        self.positions = positions if 0 < positions <= SLOT_COUNT else SLOT_COUNT
        self.jump_requested = False
        layout = QVBoxLayout(self)
        layout.addWidget(self._launch_group(options or JumpOptions()))

        self.enabled_box = QCheckBox("Choose the match Jump To Game starts")
        self.enabled_box.setChecked(match.enabled)
        self.enabled_box.toggled.connect(lambda _on: self._changed())
        layout.addWidget(self.enabled_box)
        explanation = QLabel(
            "Off, the game starts the command-line-skirmish patch's own match: a human against "
            "an easy AI. On, the seats below are the match, passed to the game as -gameInfo."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        if game is None:
            missing = QLabel(
                "The game data is not loaded, so factions and colours cannot be listed; the "
                "saved names are kept, and can be typed."
            )
            missing.setWordWrap(True)
            layout.addWidget(missing)
        elif positions == 0:
            layout.addWidget(QLabel("The open map has no multiplayer positions; offering 8."))

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        row_buttons = QHBoxLayout()
        self.add_button = QPushButton("Add Seat")
        self.add_button.clicked.connect(self.add_seat)
        row_buttons.addWidget(self.add_button)
        self.remove_button = QPushButton("Remove Seat")
        self.remove_button.clicked.connect(self.remove_selected)
        row_buttons.addWidget(self.remove_button)
        self.reset_button = QPushButton("Reset Seats")
        self.reset_button.clicked.connect(self.reset_seats)
        row_buttons.addWidget(self.reset_button)
        row_buttons.addStretch(1)
        layout.addLayout(row_buttons)

        form = QFormLayout()
        self.resources = QSpinBox()
        self.resources.setRange(0, _MAX_RESOURCES)
        self.resources.setSingleStep(500)
        self.resources.setValue(match.starting_resources)
        self.resources.valueChanged.connect(lambda _value: self._changed())
        form.addRow("Starting resources", self.resources)
        seed_row = QWidget()
        seed_box = QHBoxLayout(seed_row)
        seed_box.setContentsMargins(0, 0, 0, 0)
        self.random_seed_box = QCheckBox("New random seed each launch")
        self.random_seed_box.setChecked(match.seed is None)
        self.random_seed_box.toggled.connect(lambda _on: self._changed())
        seed_box.addWidget(self.random_seed_box)
        self.seed = QSpinBox()
        self.seed.setRange(0, _MAX_SEED)
        self.seed.setValue(match.seed if match.seed is not None else 0)
        self.seed.valueChanged.connect(lambda _value: self._changed())
        seed_box.addWidget(self.seed, 1)
        form.addRow("Seed", seed_row)
        layout.addLayout(form)

        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.jump_button = buttons.addButton(
            "Save and Jump", QDialogButtonBox.ButtonRole.AcceptRole
        )
        if self.jump_button is not None:
            self.jump_button.clicked.connect(self._request_jump)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for seat in match.seats or default_seats(game):
            self._append_row(seat)
        self._changed()

    def _launch_group(self, options: JumpOptions) -> QGroupBox:
        group = QGroupBox("Launch")
        form = QFormLayout(group)
        self.windowed_box = QCheckBox("Run the game in a window (-win)")
        self.windowed_box.setChecked(options.windowed)
        form.addRow("", self.windowed_box)
        self.width_spin, self.height_spin = QSpinBox(), QSpinBox()
        for spin, value, low, high in zip(
            (self.width_spin, self.height_spin),
            options.resolution,
            MIN_RESOLUTION,
            MAX_RESOLUTION,
            strict=True,
        ):
            spin.setRange(low, high)
            spin.setValue(value)
        size = QWidget()
        box = QHBoxLayout(size)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.width_spin)
        box.addWidget(QLabel("×"))
        box.addWidget(self.height_spin)
        box.addStretch(1)
        size.setEnabled(options.windowed)
        self.windowed_box.toggled.connect(size.setEnabled)
        form.addRow("Window size (-xres × -yres)", size)
        self.script_debug_box = QCheckBox("Script debugging (-scriptDebug2)")
        self.script_debug_box.setChecked(options.script_debug)
        form.addRow("", self.script_debug_box)
        self.extra_edit = QLineEdit(options.extra_arguments)
        self.extra_edit.setPlaceholderText("Extra game arguments, e.g. -noshellmap")
        form.addRow("Extra arguments", self.extra_edit)
        return group

    @property
    def options(self) -> JumpOptions:
        return JumpOptions(
            windowed=self.windowed_box.isChecked(),
            script_debug=self.script_debug_box.isChecked(),
            extra_arguments=self.extra_edit.text().strip(),
            resolution=(self.width_spin.value(), self.height_spin.value()),
        )

    def _append_row(self, seat: JumpSeat) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        editable = self.game is None
        widgets = (
            _combo([(_KIND_LABELS[kind], kind) for kind in SEAT_KINDS], seat.kind),
            _combo([(name, name) for name in self.factions], seat.faction, editable=editable),
            _combo(
                [(f"Position {index + 1}", index) for index in range(self.positions)],
                seat.start_position,
            ),
            _combo([(name, name) for name in self.colours], seat.colour, editable=editable),
            _combo(
                [("None", -1), *((f"Team {team + 1}", team) for team in range(TEAM_COUNT))],
                seat.team,
            ),
        )
        for column, combo in enumerate(widgets):
            combo.currentIndexChanged.connect(lambda _index: self._changed())
            combo.editTextChanged.connect(lambda _text: self._changed())
            self.table.setCellWidget(row, column, combo)

    def _cell(self, row: int, column: int) -> QComboBox:
        widget = self.table.cellWidget(row, column)
        assert isinstance(widget, QComboBox)
        return widget

    def _value(self, row: int, column: int) -> object:
        combo = self._cell(row, column)
        if combo.isEditable() and combo.currentText() != combo.itemText(combo.currentIndex()):
            return combo.currentText().strip()
        return combo.currentData()

    @property
    def seats(self) -> tuple[JumpSeat, ...]:
        seats = []
        for row in range(self.table.rowCount()):
            kind, faction, start, colour, team = (
                self._value(row, column) for column in range(len(_COLUMNS))
            )
            seats.append(
                JumpSeat(
                    kind=str(kind),
                    faction=str(faction or ""),
                    start_position=int(start),  # type: ignore[arg-type]
                    colour=str(colour or ""),
                    team=int(team),  # type: ignore[arg-type]
                )
            )
        return tuple(seats)

    @property
    def match(self) -> JumpMatch:
        return JumpMatch(
            enabled=self.enabled_box.isChecked(),
            seats=self.seats,
            starting_resources=self.resources.value(),
            seed=None if self.random_seed_box.isChecked() else self.seed.value(),
        )

    def add_seat(self) -> None:
        """Add an easy AI at the first free start position, with the next faction and colour."""
        seats = self.seats
        if len(seats) >= SLOT_COUNT:
            return
        taken_positions = {seat.start_position for seat in seats}
        position = next(
            (index for index in range(self.positions) if index not in taken_positions), 0
        )
        taken_colours = {seat.colour for seat in seats}
        colour = next((name for name in self.colours if name not in taken_colours), "")
        faction = self.factions[len(seats) % len(self.factions)] if self.factions else ""
        self._append_row(JumpSeat("easy", faction, position, colour, -1))
        self._changed()

    def remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        if row >= 0:
            self.table.removeRow(row)
            self._changed()

    def reset_seats(self) -> None:
        self.table.setRowCount(0)
        for seat in default_seats(self.game):
            self._append_row(seat)
        self._changed()

    def _changed(self) -> None:
        enabled = self.enabled_box.isChecked()
        for widget in (
            self.table,
            self.add_button,
            self.remove_button,
            self.reset_button,
            self.resources,
            self.random_seed_box,
        ):
            widget.setEnabled(enabled)
        self.seed.setEnabled(enabled and not self.random_seed_box.isChecked())
        self.add_button.setEnabled(enabled and self.table.rowCount() < SLOT_COUNT)
        self.note.setText(self.problem() or "")

    def problem(self) -> str | None:
        """Why Jump To Game would refuse this match, or `None` when it would start it."""
        match = self.match
        if not match.enabled:
            return None
        try:
            match.game_info(self.game, random.Random(0))
        except JumpMatchError as exc:
            return str(exc)
        return None

    def _request_jump(self) -> None:
        self.jump_requested = True
