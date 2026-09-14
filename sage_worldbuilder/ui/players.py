"""The Player List panel: add and remove players (or all a skirmish map needs at once), edit each
one's name, faction, AI type, faction icon, relations and color, see how it and the others regard
each other, and pick the library maps it draws scripts and teams from. Teams whose owner is not a
player are listed, as WorldBuilder reports them."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from sage_utils.views.base import safe
from sage_utils.widgets import make_completer
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command
from sage_worldbuilder.commands.edits import InsertItem, RemoveItem, SetProperty
from sage_worldbuilder.players import (
    add_player_with_team,
    add_skirmish_players,
    library_map_path,
    library_paths,
    numbered_player,
    player_name,
    regard,
    remove_player,
    set_player_faction,
    teams_without_owner,
)
from sage_worldbuilder.properties import PLAYER_SPECS, make_property
from sage_worldbuilder.teams import qualified_team_name
from sage_worldbuilder.ui.host import PanelHost
from sage_worldbuilder.ui.property_form import PropertyForm

__all__ = ["PlayersPanel"]

SIDES = Change(ChangeKind.SIDES)
# The faction icon choice that stores nothing, and the one icon no faction template provides.
DEFAULT_ICON = "(default)"
_FELLOWSHIP_ICON = "Fellowship"
_OPTIONAL_KEYS = ("playerAIType", "playerFactionIcon")


class PlayersPanel(QWidget):
    """`library_names` lists the library maps the game offers, by name."""

    def __init__(
        self,
        host: PanelHost,
        library_names: Callable[[], list[str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.library_names = library_names or (lambda: [])
        layout = QHBoxLayout(self)
        splitter = QSplitter()
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(lambda _row: self._show_selected())
        left_layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add Player")
        self.add_button.clicked.connect(lambda _checked=False: self.add())
        buttons.addWidget(self.add_button)
        self.skirmish_button = QPushButton("Add Skirmish Players")
        self.skirmish_button.setToolTip(
            "Add PlyrCivilian, PlyrCreeps, a computer player per playable faction and Player_1 to "
            "Player_4, each with its team."
        )
        self.skirmish_button.clicked.connect(lambda _checked=False: self.add_skirmish())
        buttons.addWidget(self.skirmish_button)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(lambda _checked=False: self.remove_selected())
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.form = PropertyForm(
            PLAYER_SPECS,
            host.execute,
            SIDES,
            suggestions={
                "playerFaction": self._factions,
                "playerAIType": self._ai_types,
                "playerFactionIcon": self._faction_icons,
            },
            commands={
                "playerFaction": self._faction_command,
                **{key: self._optional_command(key) for key in _OPTIONAL_KEYS},
            },
        )
        right_layout.addWidget(self.form)
        regard_row = QHBoxLayout()
        self.regards_others = QLabel()
        self.regarded_by = QLabel()
        for label in (self.regards_others, self.regarded_by):
            label.setWordWrap(True)
            regard_row.addWidget(label, 1)
        right_layout.addLayout(regard_row)
        right_layout.addWidget(
            QLabel("<b>Library maps</b> (scripts and teams used from other maps)")
        )
        self.libraries = QListWidget()
        right_layout.addWidget(self.libraries)
        library_row = QHBoxLayout()
        self.library_choice = QComboBox()
        self.library_choice.setEditable(True)
        library_row.addWidget(self.library_choice, 1)
        self.add_library_button = QPushButton("Add Library")
        self.add_library_button.clicked.connect(
            lambda _checked=False: self.add_library(self.library_choice.currentText())
        )
        library_row.addWidget(self.add_library_button)
        self.remove_library_button = QPushButton("Remove Library")
        self.remove_library_button.clicked.connect(lambda _checked=False: self.remove_library())
        library_row.addWidget(self.remove_library_button)
        right_layout.addLayout(library_row)
        self.orphans = QLabel()
        self.orphans.setWordWrap(True)
        right_layout.addWidget(self.orphans)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        self._listed_libraries: tuple[str, ...] = ()
        self.refresh()

    def _players(self) -> list:
        document = self.host.document
        if document is None or document.map.sides_list is None:
            return []
        return document.map.sides_list.players

    def _factions(self) -> list[str]:
        game = self.host.game
        if game is None:
            return []
        return sorted(game.tables.get("factions", {}), key=str.casefold)

    def _playable(self) -> list[tuple[str, str]]:
        """Each playable faction template's name and side, in the game's order."""
        game = self.host.game
        if game is None:
            return []
        playable = []
        for name, template in game.tables.get("factions", {}).items():
            side = safe(lambda template=template: template._fields.get("Side"))
            if side and safe(lambda template=template: template.PlayableSide):
                playable.append((name, str(side)))
        return playable

    def _ai_types(self) -> list[str]:
        game = self.host.game
        if game is None:
            return []
        return sorted(game.tables.get("playeraitypes", {}), key=str.casefold)

    def _faction_icons(self) -> list[str]:
        return [DEFAULT_ICON, *(side for _, side in self._playable()), _FELLOWSHIP_ICON]

    def _optional_command(self, key: str) -> Callable[[Any], Command]:
        spec = next(spec for spec in PLAYER_SPECS if spec.name == key)

        def build(value: Any) -> Command:
            properties = self.form.properties
            assert properties is not None
            text = str(value).strip()
            # An empty choice, or the default icon, removes the key rather than storing it.
            stored = None if text in ("", DEFAULT_ICON) else make_property(spec, text)
            return SetProperty(properties, key, stored, SIDES, f"Set {spec.label}")

        return build

    def _faction_command(self, value: object):
        document = self.host.document
        assert document is not None
        return set_player_faction(document.map, self.list.currentRow(), str(value))

    def refresh(self) -> None:
        players = self._players()
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for index, player in enumerate(players):
            name = player_name(player) or "(neutral)"
            self.list.addItem(f"{index + 1}. {name}")
        self.list.setCurrentRow(min(max(row, 0), len(players) - 1) if players else -1)
        self.list.blockSignals(False)
        names = tuple(self.library_names())
        if names != self._listed_libraries:
            self.library_choice.clear()
            self.library_choice.addItems(names)
            self.library_choice.setCompleter(make_completer(self.library_choice, names=names))
            self._listed_libraries = names
        self._show_selected()
        document = self.host.document
        orphans = teams_without_owner(document.map) if document is not None else []
        self.orphans.setText(
            "Teams owned by no player: " + ", ".join(qualified_team_name(t) for t in orphans)
            if orphans
            else ""
        )
        has_players = document is not None and document.map.sides_list is not None
        self.add_button.setEnabled(has_players)
        self.skirmish_button.setEnabled(has_players)

    def _show_selected(self) -> None:
        players = self._players()
        row = self.list.currentRow()
        player = players[row] if 0 <= row < len(players) else None
        self.form.set_properties(player.properties if player is not None else None)
        # The first player is the neutral one every map keeps.
        self.remove_button.setEnabled(player is not None and row > 0)
        self._show_regard(row)
        paths = self._library_paths()
        selected = self.libraries.currentRow()
        self.libraries.clear()
        self.libraries.addItems(paths or [])
        if paths:
            self.libraries.setCurrentRow(min(max(selected, 0), len(paths) - 1))
        for widget in (self.libraries, self.library_choice, self.add_library_button):
            widget.setEnabled(paths is not None)
        self.remove_library_button.setEnabled(bool(paths))

    def _show_regard(self, row: int) -> None:
        """How the selected player regards each other player, and how each regards it."""
        players = self._players()
        if not 0 <= row < len(players):
            self.regards_others.setText("")
            self.regarded_by.setText("")
            return
        player = players[row]
        name = player_name(player)
        outgoing, incoming = [], []
        for index, other in enumerate(players):
            if index == row:
                continue
            label = player_name(other) or "(neutral)"
            outgoing.append(f"{label}: {regard(player, player_name(other))}")
            incoming.append(f"{label}: {regard(other, name)}")
        self.regards_others.setText(
            "<b>How this player regards others</b><br>" + "<br>".join(outgoing)
        )
        self.regarded_by.setText("<b>How others regard this player</b><br>" + "<br>".join(incoming))

    def _library_paths(self) -> list[str] | None:
        document = self.host.document
        row = self.list.currentRow()
        if document is None or row < 0:
            return None
        return library_paths(document.map, row)

    def add(self) -> None:
        document = self.host.document
        if document is None or document.map.sides_list is None:
            return
        player = numbered_player(document.map)
        self.host.execute(add_player_with_team(document.map, player))
        self.list.setCurrentRow(len(self._players()) - 1)

    def add_skirmish(self) -> None:
        document = self.host.document
        if document is None or document.map.sides_list is None:
            return
        command = add_skirmish_players(document.map, self._playable())
        if command is not None:
            self.host.execute(command)

    def remove_selected(self) -> None:
        document = self.host.document
        row = self.list.currentRow()
        if document is None or row <= 0 or row >= len(self._players()):
            return
        self.host.execute(remove_player(document.map, row))

    def add_library(self, name: str) -> None:
        """Add a library map, by name or by its stored `Libraries\\...` path."""
        paths = self._library_paths()
        name = name.strip()
        if paths is None or not name:
            return
        path = name if "\\" in name else library_map_path(name)
        if path.lower() in (existing.lower() for existing in paths):
            return
        self.host.execute(InsertItem(paths, len(paths), path, SIDES, "Add library map"))

    def remove_library(self) -> None:
        paths = self._library_paths()
        row = self.libraries.currentRow()
        if paths is None or not 0 <= row < len(paths):
            return
        self.host.execute(RemoveItem(paths, row, SIDES, "Remove library map"))
