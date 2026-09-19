"""The Validation panel: check the open map against the loaded game and list what is wrong, the
way WorldBuilder's Generate Report does, and repair its teams with Fix Teams or turn their "Execute
associated actions" off. A mod overlay can add its own map rule set as `extra_checks`, with the
signature `sage-lint`'s map lint takes. Double-clicking a script finding selects that script."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_ini.parser.diagnostics import Diagnostic
from sage_map.linter import lint_map
from sage_map.map import Map
from sage_map.model import MapModel
from sage_worldbuilder.commands import Command
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.fix_teams import NO_PROBLEMS, clear_execute_actions, fix_teams

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = ["MapChecks", "ValidationHost", "ValidationPanel"]

_ROLE = Qt.ItemDataRole.UserRole
# A rule set's findings for one map, given the map and the path it is reported under.
MapChecks = Callable[[Map, Path], Iterable[Diagnostic]]


class ValidationHost(Protocol):
    @property
    def document(self) -> MapDocument | None: ...

    @property
    def game(self) -> Game | None: ...

    def execute(self, command: Command) -> None: ...


class ValidationPanel(QWidget):
    def __init__(
        self,
        host: ValidationHost,
        on_script: Callable[[str], None],
        parent: QWidget | None = None,
        *,
        extra_checks: MapChecks | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.on_script = on_script
        self.extra_checks = extra_checks
        self.findings: list[Diagnostic] = []

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.run_button = QPushButton("Generate Report")
        self.run_button.clicked.connect(lambda _checked=False: self.run())
        row.addWidget(self.run_button)
        self.fix_teams_button = QPushButton("Fix Teams")
        self.fix_teams_button.setToolTip(
            "Remove duplicate teams and teams on missing players, and move objects off teams that "
            "do not exist."
        )
        self.fix_teams_button.clicked.connect(lambda _checked=False: self.run_fix_teams())
        row.addWidget(self.fix_teams_button)
        self.clear_execute_button = QPushButton("Clear Execute Actions")
        self.clear_execute_button.setToolTip(
            'Adjust all teams so that their "Execute associated actions" is off.'
        )
        self.clear_execute_button.clicked.connect(
            lambda _checked=False: self.run_clear_execute_actions()
        )
        row.addWidget(self.clear_execute_button)
        self.summary = QLabel("Not run yet.")
        row.addWidget(self.summary, 1)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Severity", "Finding"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(lambda item, _column: self._open(item))
        layout.addWidget(self.tree, 1)

    def run(self) -> None:
        document, game = self.host.document, self.host.game
        self.tree.clear()
        self.findings = []
        if document is None:
            self.summary.setText("No map open.")
            return
        if game is None:
            self.summary.setText("Game data is not loaded yet, so references cannot be checked.")
            return
        path = str(document.path) if document.path is not None else document.title
        self.findings = list(lint_map(MapModel.from_map(document.map), game, path).items)
        if self.extra_checks is not None:
            self.findings.extend(self.extra_checks(document.map, Path(path)))
        for finding in self.findings:
            node = QTreeWidgetItem([finding.severity.value, finding.message])
            node.setData(0, _ROLE, finding)
            node.setToolTip(1, finding.message)
            self.tree.addTopLevelItem(node)
        self.tree.resizeColumnToContents(0)
        count = len(self.findings)
        self.summary.setText("No problems found." if count == 0 else f"{count} finding(s).")

    def run_fix_teams(self) -> None:
        """Make Fix Teams' repairs as one undoable edit and list what each one did."""
        document = self.host.document
        self.tree.clear()
        self.findings = []
        if document is None:
            self.summary.setText("No map open.")
            return
        command, messages = fix_teams(document.map)
        if command is not None:
            self.host.execute(command)
        for message in messages or [NO_PROBLEMS]:
            node = QTreeWidgetItem(["fixed" if messages else "info", message])
            node.setToolTip(1, message)
            self.tree.addTopLevelItem(node)
        self.tree.resizeColumnToContents(0)
        self.summary.setText(
            f"Fix Teams made {len(messages)} repair(s)." if messages else NO_PROBLEMS
        )

    def run_clear_execute_actions(self) -> None:
        """Turn "Execute associated actions" off on every team, as one undoable edit, and list the
        teams changed."""
        document = self.host.document
        self.tree.clear()
        self.findings = []
        if document is None:
            self.summary.setText("No map open.")
            return
        command, changed = clear_execute_actions(document.map)
        if command is not None:
            self.host.execute(command)
        for name in changed:
            message = f'Team "{name}" no longer executes its associated actions.'
            self.tree.addTopLevelItem(QTreeWidgetItem(["fixed", message]))
        self.tree.resizeColumnToContents(0)
        self.summary.setText(
            f"{len(changed)} team(s) changed." if changed else "No team executes its actions."
        )

    def clear(self) -> None:
        self.tree.clear()
        self.findings = []
        self.summary.setText("Not run yet.")

    def _open(self, node: QTreeWidgetItem) -> None:
        finding = node.data(0, _ROLE)
        script = finding.extra.get("script") if finding is not None else None
        if isinstance(script, str):
            self.on_script(script)
