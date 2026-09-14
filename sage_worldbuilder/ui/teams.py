"""The Teams panel: teams grouped under the player that owns them, and a team's identity, unit
slots, behavior scripts and generic script hooks, as WorldBuilder's Team Builder tabs show them.
Teams whose owner is not one of the map's players are grouped apart."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.teams import Team
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.edits import InsertItem, RemoveItem
from sage_worldbuilder.players import player_name
from sage_worldbuilder.properties import (
    TEAM_GENERIC_SCRIPT_SLOTS,
    TEAM_SPECS,
    TEAM_UNIT_SLOTS,
    PropertySpec,
    team_generic_script_spec,
    team_unit_specs,
)
from sage_worldbuilder.scripting import map_symbols
from sage_worldbuilder.teams import (
    copy_team,
    new_team,
    qualified_team_name,
    team_list,
    team_name,
    team_owner,
    unique_team_name,
)
from sage_worldbuilder.ui.host import PanelHost
from sage_worldbuilder.ui.property_form import PropertyForm

__all__ = ["NO_OWNER", "TeamsPanel"]

SIDES = Change(ChangeKind.SIDES)
_ROLE = Qt.ItemDataRole.UserRole
NO_OWNER = "(no owner)"
_NEUTRAL = "(neutral)"

_IDENTITY_KEYS = (
    "teamName",
    "teamOwner",
    "teamIsSingleton",
    "teamDescription",
    "teamHome",
    "teamMaxInstances",
    "teamProductionPriority",
    "teamProductionPrioritySuccessIncrease",
    "teamProductionPriorityFailureDecrease",
    "teamProductionCondition",
    "teamIsAIRecruitable",
    "teamAutoReinforce",
    "teamInitialIdleSeconds",
)
_SCRIPT_KEYS = frozenset(
    {
        "teamProductionCondition",
        "teamOnCreateScript",
        "teamEnemySightedScript",
        "teamOnDestroyedScript",
        "teamAllClearScript",
    }
)


def _scrolled(widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    return scroll


def _index_of(teams: list[Team], team: Team) -> int | None:
    # By identity: two teams with the same properties are still different teams.
    return next((index for index, candidate in enumerate(teams) if candidate is team), None)


class TeamsPanel(QWidget):
    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self.selected_team: Team | None = None
        self._symbols: dict[str, list[str]] = {}
        layout = QHBoxLayout(self)
        splitter = QSplitter()
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda current, _previous: self._select(current))
        left_layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.buttons: dict[str, QPushButton] = {}
        for text, slot in (
            ("Add", self.add),
            ("Copy", self.copy_selected),
            ("Delete", self.delete_selected),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, slot=slot: slot())
            buttons.addWidget(button)
            self.buttons[text] = button
        buttons.addStretch(1)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        by_name = {spec.name: spec for spec in TEAM_SPECS}
        identity = [by_name[key] for key in _IDENTITY_KEYS]
        behavior = [spec for spec in TEAM_SPECS if spec.name not in _IDENTITY_KEYS]
        units: list[PropertySpec] = [
            spec for slot in range(1, TEAM_UNIT_SLOTS + 1) for spec in team_unit_specs(slot)
        ]
        generic = [team_generic_script_spec(slot) for slot in range(TEAM_GENERIC_SCRIPT_SLOTS)]
        suggestions = {
            "teamOwner": self._players,
            "teamHome": lambda: self._symbols.get("waypoints", []),
        }
        for key in _SCRIPT_KEYS:
            suggestions[key] = self._scripts
        for spec in units:
            if spec.name.startswith("teamUnitType"):
                suggestions[spec.name] = self._objects
        for spec in generic:
            suggestions[spec.name] = self._scripts

        self.tabs = QTabWidget()
        self.forms: list[PropertyForm] = []
        for title, specs, scroll in (
            ("Identity", identity, False),
            ("Units", units, True),
            ("Behavior", behavior, False),
            ("Generic Scripts", generic, True),
        ):
            form = PropertyForm(specs, host.execute, SIDES, suggestions=suggestions)
            self.forms.append(form)
            self.tabs.addTab(_scrolled(form) if scroll else form, title)
        splitter.addWidget(self.tabs)
        self.refresh()

    def _teams(self) -> list[Team]:
        document = self.host.document
        if document is None:
            return []
        return team_list(document.map) or []

    def _players(self) -> list[str]:
        document = self.host.document
        if document is None or document.map.sides_list is None:
            return []
        return [player_name(player) for player in document.map.sides_list.players]

    def _scripts(self) -> list[str]:
        return self._symbols.get("scripts", [])

    def _objects(self) -> list[str]:
        game = self.host.game
        if game is None:
            return []
        return sorted(game.tables.get("objects", {}), key=str.casefold)

    def refresh(self) -> None:
        document = self.host.document
        self._symbols = map_symbols(document.map) if document is not None else {}
        teams = self._teams()
        if self.selected_team is not None and _index_of(teams, self.selected_team) is None:
            self.selected_team = None
        selected_player = self._selected_player()
        self._rebuild(teams, selected_player)
        self._show_selected()
        has_list = document is not None and team_list(document.map) is not None
        self.buttons["Add"].setEnabled(has_list)

    def _rebuild(self, teams: list[Team], selected_player: str | None) -> None:
        """One node per player, in the map's order, with its teams under it; teams whose owner
        is no player go under a last group."""
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: dict[str, list[Team]] = {name.lower(): [] for name in self._players()}
        orphans: list[Team] = []
        for team in teams:
            groups.get(team_owner(team).lower(), orphans).append(team)
        current: QTreeWidgetItem | None = None
        rows = [(name, groups[name.lower()]) for name in self._players()]
        if orphans:
            rows.append((NO_OWNER, orphans))
        for name, owned in rows:
            label = _NEUTRAL if name == "" else name
            group = QTreeWidgetItem([f"{label} ({len(owned)})"])
            group.setData(0, _ROLE, name)
            self.tree.addTopLevelItem(group)
            if selected_player is not None and name.lower() == selected_player.lower():
                current = group
            for team in owned:
                node = QTreeWidgetItem([team_name(team)])
                node.setData(0, _ROLE, team)
                group.addChild(node)
                if team is self.selected_team:
                    current = node
            group.setExpanded(bool(owned))
        if current is not None:
            self.tree.setCurrentItem(current)
        self.tree.blockSignals(False)

    def _selected_player(self) -> str | None:
        """The player the current group node stands for, when a group (not a team) is selected."""
        node = self.tree.currentItem()
        data = node.data(0, _ROLE) if node is not None else None
        return data if isinstance(data, str) and data != NO_OWNER else None

    def _select(self, node: QTreeWidgetItem | None) -> None:
        data = node.data(0, _ROLE) if node is not None else None
        self.selected_team = data if isinstance(data, Team) else None
        self._show_selected()

    def _show_selected(self) -> None:
        team = self.selected_team
        for form in self.forms:
            form.set_properties(team.properties if team is not None else None)
        self.buttons["Copy"].setEnabled(team is not None)
        self.buttons["Delete"].setEnabled(team is not None)

    def select_team(self, qualified: str) -> bool:
        """Select the team named `owner/team` (ignoring case)."""
        folded = qualified.casefold()
        for team in self._teams():
            if qualified_team_name(team).casefold() == folded:
                self.selected_team = team
                self._rebuild(self._teams(), None)
                self._show_selected()
                return True
        return False

    def select_player(self, name: str) -> bool:
        """Select the group of the player called `name` (ignoring case)."""
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            data = group.data(0, _ROLE) if group is not None else None
            if isinstance(data, str) and data != NO_OWNER and data.lower() == name.lower():
                self.tree.setCurrentItem(group)
                return True
        return False

    def add(self) -> None:
        """Add a team for the selected player (or the selected team's owner, or the first named
        player when nothing is selected)."""
        document = self.host.document
        teams = team_list(document.map) if document is not None else None
        if document is None or teams is None:
            return
        owner = self._selected_player()
        if owner is None and self.selected_team is not None:
            owner = team_owner(self.selected_team)
        if owner is None:
            named = [name for name in self._players() if name]
            owner = named[0] if named else ""
        team = new_team(unique_team_name(document.map, "Team"), owner)
        self.selected_team = team
        self.host.execute(InsertItem(teams, len(teams), team, SIDES, "Add Team"))

    def copy_selected(self) -> None:
        document = self.host.document
        teams = team_list(document.map) if document is not None else None
        if document is None or teams is None or self.selected_team is None:
            return
        index = _index_of(teams, self.selected_team)
        if index is None:
            return
        duplicate = copy_team(document.map, self.selected_team)
        self.selected_team = duplicate
        self.host.execute(InsertItem(teams, index + 1, duplicate, SIDES, "Copy Team"))

    def delete_selected(self) -> None:
        document = self.host.document
        teams = team_list(document.map) if document is not None else None
        if document is None or teams is None or self.selected_team is None:
            return
        index = _index_of(teams, self.selected_team)
        if index is None:
            return
        self.selected_team = None
        self.host.execute(RemoveItem(teams, index, SIDES, "Delete Team"))
