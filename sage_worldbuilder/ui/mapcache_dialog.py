"""The MapCache Entry dialog: the `mapcache.ini` block the open map needs, ready to be pasted.

The engine writes that file for maps under the user's Maps folder, but never for one inside a
mod's archives, so a mod's cache is kept by hand - and a map missing from it cannot be listed in
the lobby or started with `-file` at all. What each field means is in `sage_worldbuilder.mapcache`.

The dialog derives everything the map itself decides and leaves the mod's own choices editable:
the two labels, the three flags, and the symbol. Writing the block into `mapcache.ini` is not
offered on purpose - those files are ordered and commented by hand, and where a new entry belongs
in one is the mapper's call.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtGui import QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.mapcache import MAX_SYMBOL, MapCacheEntry, build_entry

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_map.map import Map

__all__ = ["MapCacheDialog"]


class MapCacheDialog(QDialog):
    def __init__(
        self,
        map: Map,
        path: str | Path,
        parent: QWidget | None = None,
        *,
        game: Game | None = None,
        modified: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MapCache Entry")
        self.resize(760, 620)
        self.entry: MapCacheEntry = build_entry(map, path, game=game)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_summary(self.entry, Path(path), game is not None, modified)))

        form = QFormLayout()
        self.display_name = QLineEdit(self.entry.display_name)
        self.display_name.setToolTip(
            "The lobby's label for the map. A name beginning with $ is looked up in the game's "
            "string table, so $Map:Aldburg shows whatever Map:Aldburg is translated to."
        )
        form.addRow("Display name", self.display_name)
        self.description = QLineEdit(self.entry.description)
        form.addRow("Description", self.description)

        self.is_official = QCheckBox("Official map")
        self.is_official.setChecked(self.entry.is_official)
        self.is_official.setToolTip(
            "Off marks the map as a user map: it draws the hammer instead of the star, and sorts "
            "below the official maps."
        )
        form.addRow("", self.is_official)

        self.is_multiplayer = QCheckBox("Multiplayer")
        self.is_multiplayer.setChecked(self.entry.is_multiplayer)
        self.is_multiplayer.setToolTip(
            "A map with this off is not listed in the skirmish lobby and cannot be started from "
            "the command line, whatever its player count."
        )
        form.addRow("", self.is_multiplayer)

        self.is_scenario = QCheckBox("Multiplayer scenario")
        self.is_scenario.setChecked(self.entry.is_scenario_mp)
        form.addRow("", self.is_scenario)

        self.map_symbol = QSpinBox()
        self.map_symbol.setRange(0, MAX_SYMBOL)
        self.map_symbol.setSpecialValueText("None")
        self.map_symbol.setValue(self.entry.map_symbol)
        self.map_symbol.setToolTip(
            "The map-list-symbols engine patch: the map draws the AptMapSymbolNN images instead "
            "of the stock medal, and groups by the symbol in the list. What each number means is "
            "the mod's own convention. None leaves the field out, which is what an unpatched "
            "game.dat needs - it refuses a mapcache.ini carrying a keyword it does not know."
        )
        form.addRow("Map symbol", self.map_symbol)
        layout.addLayout(form)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.copy_button = buttons.addButton(
            "&Copy to Clipboard", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.copy_button.clicked.connect(lambda _checked=False: self.copy())
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for widget in (self.display_name, self.description):
            widget.textChanged.connect(lambda _text="": self.refresh())
        for box in (self.is_official, self.is_multiplayer, self.is_scenario):
            box.toggled.connect(lambda _checked=False: self.refresh())
        self.map_symbol.valueChanged.connect(lambda _value=0: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        """Fold the dialog's choices back into the entry and redraw the block."""
        self.entry.display_name = self.display_name.text()
        self.entry.description = self.description.text()
        self.entry.is_official = self.is_official.isChecked()
        self.entry.is_multiplayer = self.is_multiplayer.isChecked()
        self.entry.is_scenario_mp = self.is_scenario.isChecked()
        self.entry.map_symbol = self.map_symbol.value()
        self.text.setPlainText(self.entry.text())

    def copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.entry.text())


def _summary(entry: MapCacheEntry, path: Path, has_game: bool, modified: bool) -> str:
    """What the map decided for itself, and what would make the answer wrong."""
    players = f"{entry.num_players} player start" + ("" if entry.num_players == 1 else "s")
    extent = f"{entry.extent_max[0]:.0f} x {entry.extent_max[1]:.0f} playable"
    lines = [f"{path.name} - {players}, {extent}."]
    if entry.identity.file_size == 0:
        lines.append(
            "The map has no file on disk yet, so fileSize, fileCRC and the timestamps are 0. "
            "Save it and generate the entry again."
        )
    elif modified:
        lines.append(
            "The map has unsaved changes. fileSize, fileCRC and the timestamps describe the file "
            "as it is on disk, so save it and generate the entry again."
        )
    if not has_game:
        lines.append("Without game data loaded, supplyPosition markers are not read.")
    elif entry.supply_positions:
        lines.append(f"{len(entry.supply_positions)} supply markers found.")
    return "\n".join(lines)
