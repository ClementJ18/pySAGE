"""The Scripts panel: every player's groups and scripts as a tree, and an editor for the one
selected - its properties, its IF/OR conditions and its two action lists. Every change is a
command on the document, so it is undoable."""

from __future__ import annotations

import copy
import struct
from collections.abc import Callable, MutableSequence
from typing import TYPE_CHECKING, Any, Protocol

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QDropEvent, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.player_scripts import Script, ScriptArgument, ScriptDerived, ScriptGroup
from sage_map.linter import lint_map
from sage_map.map import Map
from sage_map.model import MapModel
from sage_map.scb import ScriptLibrary, parse_scb_from_path, write_scb_to_path
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command, SetAttribute
from sage_worldbuilder.commands.edits import InsertItem, MoveItem, RemoveItem, ReplaceItem
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.exchange import (
    ExportOptions,
    ImportChoices,
    ImportReport,
    build_export,
    import_library,
    plan_import,
)
from sage_worldbuilder.libraries import (
    ImportedItem,
    ImportedScripts,
    MapLoader,
    imported_scripts,
    library_name,
    override,
)
from sage_worldbuilder.script_targets import ScriptTarget, argument_target
from sage_worldbuilder.scripting import (
    ActiveFlags,
    active_flags,
    item_text,
    iter_script_items,
    map_symbols,
    new_group,
    new_or_condition,
    new_script,
    player_script_lists,
    reset_active,
    script_matches,
    unique_script_name,
)
from sage_worldbuilder.templates import TemplateKind
from sage_worldbuilder.ui.exchange_dialogs import (
    ExportOptionsDialog,
    ReanchorDialog,
    ask_duplicate,
    ask_team_player,
)
from sage_worldbuilder.ui.script_items import ScriptItemDialog
from sage_worldbuilder.ui.sentences import HTML_ROLE, SentenceDelegate, sentence_html

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = ["GoTo", "ScriptsHost", "ScriptsPanel"]

SCRIPTS = Change(ChangeKind.SCRIPTS)
_ROLE = Qt.ItemDataRole.UserRole
_LINT_DELAY_MS = 400
_COMMENT_DELAY_MS = 400
_SCB_FILTER = "Map export data files (*.scb);;All files (*)"
_INDENT = "&nbsp;" * 6
# A condition or action list row: its plain text, what it points at, and its markup.
_Row = tuple[str, Any, str]
# What reading a malformed `.scb` raises: the container and chunk parsers are not defensive.
_READ_ERRORS = (OSError, ValueError, KeyError, IndexError, struct.error)

#: Shows what a script argument names: an object on the map, a script in this panel, a team.
GoTo = Callable[[ScriptTarget], None]


class ScriptsHost(Protocol):
    """What the panel needs from the window around it."""

    @property
    def document(self) -> MapDocument | None: ...

    @property
    def game(self) -> Game | None: ...

    def execute(self, command: Command) -> None: ...


def script_warnings(map: Map, game: Game) -> dict[str, list[str]]:
    """The problems the map linter finds in each script, keyed by the script's name in lower
    case."""
    warnings: dict[str, list[str]] = {}
    for finding in lint_map(MapModel.from_map(map), game).items:
        script = finding.extra.get("script")
        if isinstance(script, str):
            warnings.setdefault(script.lower(), []).append(finding.message)
    return warnings


def _player_choices(map: Map) -> list[tuple[str, str]]:
    """Each player's name and display name, for Export Options' player list."""
    players = map.sides_list.players if map.sides_list is not None else []
    choices = []
    for player in players:
        name = player.properties.get("playerName")
        display = player.properties.get("playerDisplayName")
        choices.append(
            (
                str(name["value"]) if name is not None else "",
                str(display["value"]) if display is not None else "",
            )
        )
    return choices


def _show_import_report(parent: QWidget, report: ImportReport) -> None:
    """Say what an import left out, when it left anything out."""
    lines = [
        f"Could not find player {name}, discarding scripts for this player."
        for name in report.discarded_players
    ]
    if report.dropped_scripts:
        lines.append(
            "Scripts the player already has were not imported: "
            + ", ".join(sorted(set(report.dropped_scripts)))
        )
    if report.skipped_teams:
        lines.append("Teams with no player were not imported: " + ", ".join(report.skipped_teams))
    if report.not_imported:
        lines.append("Not imported: " + ", ".join(report.not_imported))
    if lines:
        QMessageBox.information(parent, "Import Scripts", "\n\n".join(lines))


def _import_tip(imported: ImportedItem) -> str:
    """What an imported row says about where it comes from, and what took its name."""
    tip = f"Imported from the library map {imported.library}."
    if imported.overridden_by is not None:
        held = f"the library map {imported.overridden_by}" if imported.overridden_by else "the map"
        tip += f"\nOverridden: {held} defines this name first and keeps it."
    return tip


def _holds(group: ScriptGroup, items: MutableSequence[Script | ScriptGroup]) -> bool:
    """Whether `items` is `group`'s own list or the list of a group somewhere inside it."""
    if group.items is items:
        return True
    return any(isinstance(child, ScriptGroup) and _holds(child, items) for child in group.items)


class _ScriptTree(QTreeWidget):
    """A tree whose drag and drop is reported as a move instead of being carried out, so the move
    goes through the undo stack and the tree is rebuilt from the map."""

    def __init__(
        self, on_drop: Callable[[object, object, QAbstractItemView.DropIndicatorPosition], None]
    ) -> None:
        super().__init__()
        self._on_drop = on_drop
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def dropEvent(self, event: QDropEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        dragged = self.currentItem()
        position = event.position().toPoint()
        target = self.itemAt(position)
        indicator = self.dropIndicatorPosition()
        event.ignore()
        if dragged is None or target is None:
            return
        self._on_drop(dragged.data(0, _ROLE), target.data(0, _ROLE), indicator)


class _ItemList(QWidget):
    """One list of conditions or actions with its buttons."""

    def __init__(self, title: str, buttons: list[tuple[str, Callable[[], None]]]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        self.list = QListWidget()
        # Rows draw their arguments as links; a click on one is reported, not a row click.
        self.delegate = SentenceDelegate(self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.setMouseTracking(True)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.buttons: dict[str, QPushButton] = {}
        for text, slot in buttons:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, slot=slot: slot())
            row.addWidget(button)
            self.buttons[text] = button
        row.addStretch(1)
        layout.addLayout(row)


class ScriptsPanel(QWidget):
    def __init__(
        self,
        host: ScriptsHost,
        load_library: MapLoader | None = None,
        go_to: GoTo | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        # Reads a player's library maps; without one the tree shows the map's own scripts alone.
        self.load_library = load_library
        # Shows what an argument names; without one no Go To button or menu entry is offered.
        self.go_to = go_to
        self.item_dialog: Callable[..., Any] = ScriptItemDialog
        self.selected: Script | ScriptGroup | None = None
        self._updating = False
        self._expanded: set[int] = set()
        # Every imported item in the tree, by identity: what makes a row read-only.
        self._imported: dict[int, ImportedItem] = {}
        # The Active flags of the open map as it was loaded, for Reset Active.
        self._loaded_document: MapDocument | None = None
        self._loaded_active: ActiveFlags = []

        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        tree_side = QWidget()
        tree_layout = QVBoxLayout(tree_side)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search scripts, conditions and actions")
        self.search.textChanged.connect(lambda _text: self.refresh())
        search_row.addWidget(self.search, 1)
        self.whole_value = QCheckBox("Match entire parameter")
        self.whole_value.toggled.connect(lambda _on: self.refresh())
        search_row.addWidget(self.whole_value)
        tree_layout.addLayout(search_row)
        self.tree = _ScriptTree(self._dropped)
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda current, _previous: self._select(current))
        self.tree.itemExpanded.connect(lambda item: self._remember_expanded(item, True))
        self.tree.itemCollapsed.connect(lambda item: self._remember_expanded(item, False))
        tree_layout.addWidget(self.tree, 1)
        tree_buttons = QHBoxLayout()
        self.tree_buttons: dict[str, QPushButton] = {}
        for text, slot in (
            ("New Script", self.new_script),
            ("New Group", self.new_group),
            ("Copy", self.copy_selected),
            ("Override", self.override_selected),
            ("Delete", self.delete_selected),
            ("Up", lambda: self.move_selected(-1)),
            ("Down", lambda: self.move_selected(1)),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, slot=slot: slot())
            tree_buttons.addWidget(button)
            self.tree_buttons[text] = button
        self.tree_buttons["Override"].setToolTip(
            "Give the map its own copy of the selected imported item, at the same path, so it can"
            " be edited. The copy keeps its name, which is what takes that name off the library;"
            " a group of the path the map does not have is recreated to hold it, and that group's"
            " name comes off the library too."
        )
        tree_layout.addLayout(tree_buttons)
        library_buttons = QHBoxLayout()
        library_actions: tuple[tuple[str, Callable[[], object]], ...] = (
            ("Import Scripts…", lambda: self.import_scripts()),
            ("Export Scripts…", lambda: self.export_scripts()),
            ("Reset Active", lambda: self.reset_active_flags()),
        )
        for label, handler in library_actions:
            library_button = QPushButton(label)
            library_button.clicked.connect(lambda _checked=False, handler=handler: handler())
            library_buttons.addWidget(library_button)
            self.tree_buttons[label] = library_button
        self.tree_buttons["Reset Active"].setToolTip(
            "Reset the Active flags to their original load state."
        )
        library_buttons.addStretch(1)
        tree_layout.addLayout(library_buttons)
        splitter.addWidget(tree_side)

        self.pages = QStackedWidget()
        self.pages.addWidget(QLabel("Select a script or a group."))
        self.pages.addWidget(self._build_group_page())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._build_script_page())
        self.pages.addWidget(scroll)
        splitter.addWidget(self.pages)
        splitter.setSizes([320, 680])

        self._comment_timer = QTimer(self)
        self._comment_timer.setSingleShot(True)
        self._comment_timer.setInterval(_COMMENT_DELAY_MS)
        self._comment_timer.timeout.connect(self._commit_comment)
        # Live warnings: the scripts are rechecked a moment after the last edit.
        self.lint: Callable[[Map, Game], dict[str, list[str]]] = script_warnings
        self.warnings: dict[str, list[str]] = {}
        self._lint_timer = QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.setInterval(_LINT_DELAY_MS)
        self._lint_timer.timeout.connect(self.update_warnings)
        self.refresh()

    def _build_group_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.group_name = QLineEdit()
        self.group_name.editingFinished.connect(
            lambda: self._set_selected("name", self.group_name.text(), "Rename Group")
        )
        form.addRow("Name", self.group_name)
        self.group_active = QCheckBox("Active")
        self.group_active.toggled.connect(lambda on: self._set_selected("is_active", on))
        form.addRow("", self.group_active)
        self.group_subroutine = QCheckBox("Subroutine")
        self.group_subroutine.toggled.connect(lambda on: self._set_selected("is_subroutine", on))
        form.addRow("", self.group_subroutine)
        return page

    def _build_script_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.script_name = QLineEdit()
        self.script_name.editingFinished.connect(
            lambda: self._set_selected("name", self.script_name.text(), "Rename Script")
        )
        form.addRow("Name", self.script_name)
        self.script_comment = QPlainTextEdit()
        self.script_comment.setFixedHeight(60)
        self.script_comment.textChanged.connect(
            lambda: None if self._updating else self._comment_timer.start()
        )
        form.addRow("Comment", self.script_comment)
        flags = QHBoxLayout()
        self.script_flags: dict[str, QCheckBox] = {}
        for attribute, text in (
            ("is_active", "Active"),
            ("is_subroutine", "Subroutine"),
            ("deactivate_upon_success", "Deactivate upon success"),
            ("active_in_easy", "Easy"),
            ("active_in_medium", "Medium"),
            ("active_in_hard", "Hard"),
        ):
            box = QCheckBox(text)
            box.toggled.connect(lambda on, attribute=attribute: self._set_selected(attribute, on))
            flags.addWidget(box)
            self.script_flags[attribute] = box
        flags.addStretch(1)
        form.addRow("", self._wrap(flags))
        self.script_interval = QSpinBox()
        self.script_interval.setRange(0, 1_000_000)
        self.script_interval.setSuffix(" s")
        self.script_interval.setSpecialValueText("every frame")
        self.script_interval.valueChanged.connect(
            lambda value: self._set_selected("evaluation_interval", value, "Set evaluation")
        )
        form.addRow("Evaluate", self.script_interval)
        sequential = QHBoxLayout()
        self.sequential_box = QCheckBox("Fire actions sequentially")
        self.sequential_box.toggled.connect(
            lambda on: self._set_selected("actions_fire_sequentially", on)
        )
        sequential.addWidget(self.sequential_box)
        self.loop_box = QCheckBox("Loop, count")
        self.loop_box.toggled.connect(lambda on: self._set_selected("loop_actions", on))
        sequential.addWidget(self.loop_box)
        self.loop_count = QSpinBox()
        self.loop_count.setRange(0, 1_000_000)
        self.loop_count.valueChanged.connect(
            lambda value: self._set_selected("loop_count", value, "Set loop count")
        )
        sequential.addWidget(self.loop_count)
        sequential.addStretch(1)
        form.addRow("Sequential", self._wrap(sequential))
        self.sequential_target = QLineEdit()
        self.sequential_target.setPlaceholderText("Team or unit the actions run on")
        self.sequential_target.editingFinished.connect(
            lambda: self._set_selected(
                "sequential_target_name", self.sequential_target.text(), "Set sequential target"
            )
        )
        form.addRow("Run on", self.sequential_target)
        layout.addLayout(form)

        self.conditions = _ItemList(
            "Conditions (IF ... OR ...)",
            [
                ("New Condition", self.new_condition),
                ("New OR", self.new_or_clause),
                ("Edit", lambda: self.edit_item(self.conditions)),
                ("Delete", lambda: self.delete_item(self.conditions)),
                ("Up", lambda: self.move_item(self.conditions, -1)),
                ("Down", lambda: self.move_item(self.conditions, 1)),
                ("Enable/Disable", lambda: self.toggle_item(self.conditions)),
            ],
        )
        self.actions_true = self._action_list("Actions if true", "actions_if_true")
        self.actions_false = self._action_list("Actions if false", "actions_if_false")
        for items in (self.conditions, self.actions_true, self.actions_false):
            items.list.itemDoubleClicked.connect(lambda _item, items=items: self.edit_item(items))
            items.list.currentRowChanged.connect(lambda _row: self._sync_buttons())
            items.delegate.argument_clicked.connect(
                lambda row, argument, items=items: self.edit_argument(items, row, argument)
            )
            items.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            items.list.customContextMenuRequested.connect(
                lambda point, items=items: self.show_item_menu(items, point)
            )
            layout.addWidget(items, 1)
        return page

    def _action_list(self, title: str, attribute: str) -> _ItemList:
        holder: list[_ItemList] = []

        def target() -> _ItemList:
            return holder[0]

        items = _ItemList(
            title,
            [
                ("New Action", lambda: self.new_action(attribute)),
                ("Edit", lambda: self.edit_item(target())),
                ("Delete", lambda: self.delete_item(target())),
                ("Up", lambda: self.move_item(target(), -1)),
                ("Down", lambda: self.move_item(target(), 1)),
                ("Enable/Disable", lambda: self.toggle_item(target())),
            ],
        )
        holder.append(items)
        return items

    @staticmethod
    def _wrap(layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        widget.setLayout(layout)
        return widget

    def refresh(self) -> None:
        """Rebuild from the document, keeping the selection and the expanded folders."""
        self._updating = True
        document = self.host.document
        if document is not self._loaded_document:
            self._loaded_document = document
            self._loaded_active = active_flags(document.map) if document is not None else []
        try:
            self._rebuild_tree()
            self._show_selected()
        finally:
            self._updating = False
        self._sync_buttons()
        self._lint_timer.start()

    def _rebuild_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self._imported.clear()
        document = self.host.document
        current: QTreeWidgetItem | None = None
        if document is not None:
            for index, (name, script_list) in enumerate(player_script_lists(document.map)):
                top = QTreeWidgetItem([name or f"Player {index + 1}"])
                top.setData(0, _ROLE, script_list)
                top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
                self.tree.addTopLevelItem(top)
                found = self._add_children(top, script_list.items)
                inherited = self._inherited(document.map, index)
                found = self._add_imported(top, inherited) or found
                current = current or found
                expanded = id(script_list) in self._expanded or bool(found) or self._searching()
                top.setExpanded(expanded)
        if current is None:
            self.selected = None
        else:
            self.tree.setCurrentItem(current)
        self.tree.blockSignals(False)

    def _inherited(self, map: Map, index: int) -> ImportedScripts:
        """What player `index` inherits from its library maps, empty when no loader was given."""
        if self.load_library is None:
            return ImportedScripts()
        return imported_scripts(map, index, self.load_library)

    def _add_imported(
        self, parent: QTreeWidgetItem, inherited: ImportedScripts
    ) -> QTreeWidgetItem | None:
        """The player's library maps under its own scripts: their items, read-only, and a row for
        each library the game does not have."""
        current = None
        for imported in inherited.items:
            found = self._add_children(parent, [imported.item], inherited)
            current = current or found
        for path in inherited.missing:
            node = QTreeWidgetItem([f"{library_name(path)}  (library map not found)"])
            node.setFlags(Qt.ItemFlag.ItemIsEnabled)
            node.setIcon(0, self._standard_icon(QStyle.StandardPixmap.SP_MessageBoxWarning))
            node.setToolTip(0, f"{path} is not in the loaded game.")
            node.setForeground(0, Qt.GlobalColor.gray)
            node.setHidden(self._searching())
            parent.addChild(node)
        return current

    def _add_children(
        self,
        parent: QTreeWidgetItem,
        items: list[Script | ScriptGroup],
        inherited: ImportedScripts | None = None,
    ) -> QTreeWidgetItem | None:
        current = None
        for child in items:
            imported = inherited.of(child) if inherited is not None else None
            node = QTreeWidgetItem([self._label(child, imported)])
            node.setData(0, _ROLE, child)
            self._decorate(node, child, imported)
            if imported is not None:
                self._imported[id(child)] = imported
                node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            if not child.is_active:
                node.setForeground(0, Qt.GlobalColor.gray)
            parent.addChild(node)
            node.setHidden(not self._matches(child))
            if child is self.selected:
                current = node
            if isinstance(child, ScriptGroup):
                found = self._add_children(node, child.items, inherited)
                current = current or found
                node.setExpanded(id(child) in self._expanded or bool(found) or self._searching())
        return current

    def _icon(self, item: Script | ScriptGroup, imported: bool = False) -> QIcon:
        """A folder for a group, a file for a script, as Windows Explorer draws them; an item a
        library map lends the player is drawn as a shortcut to one."""
        if isinstance(item, ScriptGroup):
            pixmap = (
                QStyle.StandardPixmap.SP_DirLinkIcon
                if imported
                else QStyle.StandardPixmap.SP_DirIcon
            )
        else:
            pixmap = (
                QStyle.StandardPixmap.SP_FileLinkIcon
                if imported
                else QStyle.StandardPixmap.SP_FileIcon
            )
        return self._standard_icon(pixmap)

    def _standard_icon(self, pixmap: QStyle.StandardPixmap) -> QIcon:
        style = self.style()
        return style.standardIcon(pixmap) if style is not None else QIcon()

    def _decorate(
        self,
        node: QTreeWidgetItem,
        item: Script | ScriptGroup,
        imported: ImportedItem | None = None,
    ) -> None:
        """The item's icon, or a warning sign with the problems as its tooltip. An imported item
        says which library map it comes from instead."""
        problems = self.warnings.get(item.name.lower()) if isinstance(item, Script) else None
        if problems and imported is None:
            node.setIcon(0, self._standard_icon(QStyle.StandardPixmap.SP_MessageBoxWarning))
            node.setToolTip(0, "\n".join(problems))
        else:
            node.setIcon(0, self._icon(item, imported is not None))
            node.setToolTip(0, _import_tip(imported) if imported is not None else "")

    def update_warnings(self) -> None:
        """Recheck the scripts against the game and mark the ones with problems."""
        document, game = self.host.document, self.host.game
        found = self.lint(document.map, game) if document is not None and game is not None else {}
        if found == self.warnings:
            return
        self.warnings = found
        iterator = QTreeWidgetItemIterator(self.tree)
        while (node := iterator.value()) is not None:
            item = node.data(0, _ROLE)
            if isinstance(item, (Script, ScriptGroup)):
                self._decorate(node, item, self._imported.get(id(item)))
            iterator += 1

    def _searching(self) -> bool:
        return bool(self.search.text().strip())

    def _matches(self, item: Script | ScriptGroup) -> bool:
        """Whether the search keeps `item` in the tree: it matches, or something inside it does."""
        needle = self.search.text().strip()
        if not needle or script_matches(item, needle, self.whole_value.isChecked()):
            return True
        return isinstance(item, ScriptGroup) and any(self._matches(child) for child in item.items)

    @staticmethod
    def _label(item: Script | ScriptGroup, imported: ImportedItem | None = None) -> str:
        notes = []
        if not item.is_active:
            notes.append("inactive")
        if item.is_subroutine:
            notes.append("subroutine")
        if imported is not None:
            notes.append("overridden" if imported.overridden else "imported")
        suffix = f"  ({', '.join(notes)})" if notes else ""
        return f"{item.name}{suffix}"

    def _remember_expanded(self, node: QTreeWidgetItem, expanded: bool) -> None:
        data = node.data(0, _ROLE)
        if data is None:
            return
        if expanded:
            self._expanded.add(id(data))
        else:
            self._expanded.discard(id(data))

    def _select(self, node: QTreeWidgetItem | None) -> None:
        data = node.data(0, _ROLE) if node is not None else None
        self.selected = data if isinstance(data, Script | ScriptGroup) else None
        self._updating = True
        try:
            self._show_selected()
        finally:
            self._updating = False
        self._sync_buttons()

    def _show_selected(self) -> None:
        selected = self.selected
        if isinstance(selected, ScriptGroup):
            self.pages.setCurrentIndex(1)
            self.group_name.setText(selected.name)
            self.group_active.setChecked(selected.is_active)
            self.group_subroutine.setChecked(selected.is_subroutine)
        elif isinstance(selected, Script):
            self.pages.setCurrentIndex(2)
            if self.script_name.text() != selected.name:
                self.script_name.setText(selected.name)
            if self.script_comment.toPlainText() != selected.comment:
                self.script_comment.setPlainText(selected.comment)
            for attribute, box in self.script_flags.items():
                box.setChecked(bool(getattr(selected, attribute)))
            self.script_interval.setValue(selected.evaluation_interval or 0)
            self.sequential_box.setChecked(bool(selected.actions_fire_sequentially))
            self.loop_box.setChecked(bool(selected.loop_actions))
            self.loop_count.setValue(selected.loop_count or 0)
            target = selected.sequential_target_name or ""
            if self.sequential_target.text() != target:
                self.sequential_target.setText(target)
            self._fill_lists(selected)
        else:
            self.pages.setCurrentIndex(0)
        self._apply_lock()

    def _apply_lock(self) -> None:
        """An imported item is shown, not edited: its fields are read-only, the way WorldBuilder
        refuses to take a script inherited from a library map."""
        editable = not self.locked()
        for widget in (
            self.group_name,
            self.group_active,
            self.group_subroutine,
            self.script_name,
            self.script_comment,
            self.script_interval,
            self.sequential_box,
            self.loop_box,
            self.loop_count,
            self.sequential_target,
            *self.script_flags.values(),
        ):
            widget.setEnabled(editable)

    def _fill_lists(self, script: Script) -> None:
        rows: list[_Row] = []
        for clause_index, clause in enumerate(script.or_conditions):
            header = "IF" if clause_index == 0 else "OR"
            rows.append((header, (clause_index, None), f"<b>{header}</b>"))
            for condition_index, condition in enumerate(clause.conditions):
                text, markup = self._row(condition, TemplateKind.CONDITION)
                rows.append((f"    {text}", (clause_index, condition_index), f"{_INDENT}{markup}"))
        self._fill(self.conditions.list, rows)
        for items, actions in (
            (self.actions_true, script.actions_if_true),
            (self.actions_false, script.actions_if_false),
        ):
            action_rows: list[_Row] = []
            for index, action in enumerate(actions):
                text, markup = self._row(action, TemplateKind.ACTION)
                action_rows.append((text, index, markup))
            self._fill(items.list, action_rows)

    @staticmethod
    def _row(item: ScriptDerived, kind: TemplateKind) -> tuple[str, str]:
        """The row's plain text and its markup with the arguments as links."""
        text, markup = item_text(item, kind), sentence_html(item, kind)
        if item.is_enabled:
            return text, markup
        return f"{text}  [disabled]", f"{markup}&nbsp;&nbsp;<i>[disabled]</i>"

    @staticmethod
    def _fill(widget: QListWidget, rows: list[_Row]) -> None:
        row = widget.currentRow()
        widget.blockSignals(True)
        widget.clear()
        for text, data, markup in rows:
            entry = QListWidgetItem(text)
            entry.setData(_ROLE, data)
            entry.setData(HTML_ROLE, markup)
            widget.addItem(entry)
        widget.setCurrentRow(min(row, widget.count() - 1))
        widget.blockSignals(False)

    def locked(self) -> bool:
        """Whether the selected item belongs to a library map: it is read here, edited there."""
        return self.selected is not None and id(self.selected) in self._imported

    def _sync_buttons(self) -> None:
        has_document = self.host.document is not None
        locked = self.locked()
        has_selection = self.selected is not None and not locked
        self.tree_buttons["New Script"].setEnabled(has_document)
        self.tree_buttons["New Group"].setEnabled(has_document)
        for text in ("Copy", "Delete", "Up", "Down"):
            self.tree_buttons[text].setEnabled(has_selection)
        self.tree_buttons["Override"].setEnabled(locked)
        for items in (self.conditions, self.actions_true, self.actions_false):
            for button in items.buttons.values():
                button.setEnabled(not locked)
        document = self.host.document
        self.tree_buttons["Reset Active"].setEnabled(
            document is not None and reset_active(document.map, self._loaded_active) is not None
        )

    def reset_active_flags(self) -> None:
        """Put every script's and group's Active flag back to its value when the map was
        loaded."""
        document = self.host.document
        command = reset_active(document.map, self._loaded_active) if document is not None else None
        if command is not None:
            self._execute(command)

    def _execute(self, command: Command) -> None:
        self.host.execute(command)

    def _set_selected(self, attribute: str, value: Any, label: str | None = None) -> None:
        selected = self.selected
        if self._updating or selected is None or self.locked():
            return
        if getattr(selected, attribute) == value:
            return
        self._execute(SetAttribute(selected, attribute, value, SCRIPTS, label))

    def _commit_comment(self) -> None:
        if isinstance(self.selected, Script):
            self._set_selected("comment", self.script_comment.toPlainText(), "Edit comment")

    def _script_lists(self) -> list[MutableSequence[Script | ScriptGroup]]:
        document = self.host.document
        if document is None:
            return []
        return [script_list.items for _, script_list in player_script_lists(document.map)]

    def _parent_of(
        self, target: Script | ScriptGroup
    ) -> tuple[MutableSequence[Script | ScriptGroup], int] | None:
        def search(items: MutableSequence[Script | ScriptGroup]) -> tuple[Any, int] | None:
            for index, child in enumerate(items):
                if child is target:
                    return items, index
                if isinstance(child, ScriptGroup) and (found := search(child.items)):
                    return found
            return None

        for items in self._script_lists():
            if found := search(items):
                return found
        return None

    def _insertion_point(self) -> tuple[MutableSequence[Script | ScriptGroup], int] | None:
        """Where a new script or group goes: after the selected script, at the end of the
        selected group or player, or at the end of the first player's list."""
        node = self.tree.currentItem()
        data = node.data(0, _ROLE) if node is not None else None
        if isinstance(data, Script | ScriptGroup) and id(data) in self._imported:
            # Nothing is added to a library map from here: the new item goes to the player whose
            # tree the imported one is shown in.
            return self._player_items(node)
        if isinstance(data, Script):
            found = self._parent_of(data)
            return (found[0], found[1] + 1) if found is not None else None
        if data is not None and hasattr(data, "items"):
            return data.items, len(data.items)
        lists = self._script_lists()
        return (lists[0], len(lists[0])) if lists else None

    def _player_items(
        self, node: QTreeWidgetItem | None
    ) -> tuple[MutableSequence[Script | ScriptGroup], int] | None:
        """The end of the script list of the player `node` sits under."""
        while node is not None and node.parent() is not None:
            node = node.parent()
        data = node.data(0, _ROLE) if node is not None else None
        items = getattr(data, "items", None)
        return (items, len(items)) if items is not None else None

    def _insert(self, item: Script | ScriptGroup, label: str) -> None:
        point = self._insertion_point()
        if point is None:
            return
        items, index = point
        self.selected = item
        self._execute(InsertItem(items, index, item, SCRIPTS, label))

    def select_script(self, name: str) -> bool:
        """Select the script or group called `name` (ignoring case), clearing any search."""
        document = self.host.document
        if document is None:
            return False
        folded = name.casefold()
        for _, script_list in player_script_lists(document.map):
            for location in iter_script_items(script_list.items):
                if location.item.name.casefold() == folded:
                    self.selected = location.item
                    self.search.blockSignals(True)
                    self.search.clear()
                    self.search.blockSignals(False)
                    self.refresh()
                    return True
        return False

    def move_to(
        self, item: Script | ScriptGroup, target: MutableSequence[Script | ScriptGroup], index: int
    ) -> None:
        """Move a script or group into `target` (a player's or a group's list) so it lands before
        what is at `index` there now. A group never moves into itself."""
        point = self._parent_of(item)
        if point is None or (isinstance(item, ScriptGroup) and _holds(item, target)):
            return
        source, source_index = point
        if source is target:
            if index > source_index:
                index -= 1
            if index == source_index:
                return
        self.selected = item
        self._execute(MoveItem(source, source_index, target, index, SCRIPTS, "Move"))

    def _dropped(
        self, item: object, target: object, position: QAbstractItemView.DropIndicatorPosition
    ) -> None:
        if not isinstance(item, Script | ScriptGroup) or target is None:
            return
        if id(item) in self._imported or id(target) in self._imported:
            return
        on_item = position is QAbstractItemView.DropIndicatorPosition.OnItem
        if isinstance(target, Script | ScriptGroup) and not (
            on_item and isinstance(target, ScriptGroup)
        ):
            point = self._parent_of(target)
            if point is not None:
                above = position is QAbstractItemView.DropIndicatorPosition.AboveItem
                self.move_to(item, point[0], point[1] if above else point[1] + 1)
            return
        items = getattr(target, "items", None)
        if items is not None:
            self.move_to(item, items, len(items))

    def export_scripts(self, path: str | None = None, options: ExportOptions | None = None) -> None:
        """Write a `.scb` of the parts of the map `options` choose, as WorldBuilder's Export
        Script(s) does. Without a path it asks for the options, then the file; with one it uses
        `options` or the defaults (every script and what the scripts name)."""
        document = self.host.document
        if document is None:
            return
        interactive = path is None
        if options is None and interactive:
            dialog = ExportOptionsDialog(
                _player_choices(document.map),
                ExportOptions(),
                has_selected_scripts=self.selected is not None,
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            options = dialog.options()
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Script(s)", f"{document.title}.scb", _SCB_FILTER
            )
            if not path:
                return
        library = build_export(
            document.map,
            options if options is not None else ExportOptions(),
            selection=document.selection.items,
            selected_scripts=[self.selected] if self.selected is not None else [],
        )
        try:
            write_scb_to_path(library, path)
        except OSError as exc:
            if interactive:
                QMessageBox.warning(self, "Export Script(s)", f"Could not write {path}:\n{exc}")
            raise

    def _selection_player(self) -> str | None:
        """The player selected scripts in a library go to: the one whose list holds the selected
        tree item, or the first player."""
        document = self.host.document
        lists = player_script_lists(document.map) if document is not None else []
        if self.selected is not None:
            for name, script_list in lists:
                if any(loc.item is self.selected for loc in iter_script_items(script_list.items)):
                    return name
        return lists[0][0] if lists else None

    def import_scripts(
        self, path: str | None = None, choices: ImportChoices | None = None
    ) -> list[str]:
        """Merge a `.scb` into the map as one undoable edit, as WorldBuilder's Import Scripts does.
        Without a path it asks for the file and every choice the import needs; with one it uses
        `choices` or the defaults (centred, existing items kept). Returns the library's players
        whose scripts found no player."""
        document = self.host.document
        if document is None:
            return []
        interactive = path is None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Import Scripts", "", _SCB_FILTER)
            if not path:
                return []
        try:
            library = parse_scb_from_path(path)
        except _READ_ERRORS as exc:
            if not interactive:
                raise
            QMessageBox.warning(self, "Import Scripts", f"Could not read {path}:\n{exc}")
            return []
        if choices is None:
            choices = ImportChoices(selection_player=self._selection_player())
            if interactive and not self._ask_import_choices(document, library, choices):
                return []
        command, report = import_library(document.map, library, choices)
        if command is not None:
            self._execute(command)
        if interactive:
            _show_import_report(self, report)
        return report.discarded_players

    def _ask_import_choices(
        self, document: MapDocument, library: ScriptLibrary, choices: ImportChoices
    ) -> bool:
        """Ask the anchor, each duplicate and each ownerless team's player; False on Cancel."""
        plan = plan_import(document.map, library)
        if plan.needs_anchor:
            dialog = ReanchorDialog(plan.import_size, plan.map_size, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
            choices.anchor = dialog.anchor()
        for kind, names in plan.duplicates.items():
            for name in names:
                if kind in choices.duplicate_defaults:
                    break
                answer = ask_duplicate(self, kind, name)
                if answer is None:
                    return False
                policy, to_all = answer
                if to_all:
                    choices.duplicate_defaults[kind] = policy
                else:
                    choices.duplicates[(kind, name)] = policy
        players = [name for name, _ in player_script_lists(document.map)]
        for team, owner in plan.teams_without_player:
            choices.team_players[team] = ask_team_player(self, team, owner, players)
        return True

    def new_script(self) -> None:
        document = self.host.document
        if document is not None:
            self._insert(new_script(unique_script_name(document.map, "New Script")), "New Script")

    def new_group(self) -> None:
        document = self.host.document
        if document is not None:
            self._insert(new_group(unique_script_name(document.map, "New Group")), "New Group")

    def copy_selected(self) -> None:
        document, selected = self.host.document, self.selected
        if document is None or selected is None or (point := self._parent_of(selected)) is None:
            return
        duplicate = copy.deepcopy(selected)
        duplicate.name = unique_script_name(document.map, selected.name)
        items, index = point
        self.selected = duplicate
        self._execute(InsertItem(items, index + 1, duplicate, SCRIPTS, "Copy"))

    def override_selected(self) -> None:
        """Copy the selected imported item into the player's own scripts, at the same path, and
        select the copy - which is the map's, so it can be edited."""
        document, selected = self.host.document, self.selected
        imported = self._imported.get(id(selected)) if selected is not None else None
        index = self._player_of(self.tree.currentItem())
        if document is None or imported is None or index is None:
            return
        result = override(document.map, index, imported)
        if result.command is None or result.copy is None:
            QMessageBox.information(
                self,
                "Override",
                f"{imported.item.name} cannot be overridden: {result.blocked}."
                "\n\nA name the map itself defines already wins over the library's.",
            )
            return
        self.selected = result.copy
        self._execute(result.command)

    def _player_of(self, node: QTreeWidgetItem | None) -> int | None:
        """Which player's tree `node` sits in."""
        while node is not None and node.parent() is not None:
            node = node.parent()
        if node is None:
            return None
        found = self.tree.indexOfTopLevelItem(node)
        return found if found >= 0 else None

    def delete_selected(self) -> None:
        selected = self.selected
        if selected is None or (point := self._parent_of(selected)) is None:
            return
        items, index = point
        remaining = [child for child in items if child is not selected]
        self.selected = remaining[min(index, len(remaining) - 1)] if remaining else None
        self._execute(RemoveItem(items, index, SCRIPTS, "Delete"))

    def move_selected(self, step: int) -> None:
        selected = self.selected
        if selected is None or (point := self._parent_of(selected)) is None:
            return
        items, index = point
        if 0 <= index + step < len(items):
            self._execute(MoveItem(items, index, items, index + step, SCRIPTS, "Move"))

    def _open_item_dialog(
        self, kind: TemplateKind, item: ScriptDerived | None, focus_argument: int | None = None
    ) -> Any:
        document = self.host.document
        if document is None:
            return None
        dialog = self.item_dialog(
            kind,
            item,
            map_symbols(document.map),
            self.host.game,
            self,
            focus_argument=focus_argument,
            find_target=self.find_target,
            go_to=self.go_to,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.item is None:
            return None
        return dialog.item

    def _current(self, items: _ItemList) -> Any:
        entry = items.list.currentItem()
        return entry.data(_ROLE) if entry is not None else None

    def _condition_target(self, position: Any) -> tuple[MutableSequence[ScriptDerived], int] | None:
        script = self.selected
        if not isinstance(script, Script) or position is None:
            return None
        clause_index, condition_index = position
        if condition_index is None:
            return None
        return script.or_conditions[clause_index].conditions, condition_index

    def _action_target(self, items: _ItemList) -> tuple[MutableSequence[ScriptDerived], int] | None:
        script = self.selected
        index = self._current(items)
        if not isinstance(script, Script) or index is None:
            return None
        actions = script.actions_if_true if items is self.actions_true else script.actions_if_false
        return actions, index

    def _target(self, items: _ItemList) -> tuple[MutableSequence[ScriptDerived], int] | None:
        if self.locked():
            return None
        if items is self.conditions:
            return self._condition_target(self._current(items))
        return self._action_target(items)

    def new_condition(self) -> None:
        script = self.selected
        if not isinstance(script, Script) or self.locked():
            return
        item = self._open_item_dialog(TemplateKind.CONDITION, None)
        if item is None:
            return
        document = self.host.document
        assert document is not None
        # After the selected condition, at the end of the selected clause, or at the end of the
        # last clause.
        position = self._current(self.conditions)
        with document.stack.group("New Condition"):
            if not script.or_conditions:
                self._execute(InsertItem(script.or_conditions, 0, new_or_condition(), SCRIPTS))
            if position is None:
                clause_index, index = len(script.or_conditions) - 1, None
            else:
                clause_index, condition_index = position
                index = None if condition_index is None else condition_index + 1
            conditions = script.or_conditions[clause_index].conditions
            self._execute(
                InsertItem(conditions, len(conditions) if index is None else index, item, SCRIPTS)
            )

    def new_or_clause(self) -> None:
        script = self.selected
        if not isinstance(script, Script) or self.locked():
            return
        position = self._current(self.conditions)
        index = position[0] + 1 if position is not None else len(script.or_conditions)
        self._execute(
            InsertItem(script.or_conditions, index, new_or_condition(), SCRIPTS, "New OR")
        )

    def new_action(self, attribute: str) -> None:
        script = self.selected
        if not isinstance(script, Script) or self.locked():
            return
        item = self._open_item_dialog(TemplateKind.ACTION, None)
        if item is None:
            return
        actions = getattr(script, attribute)
        widget = self.actions_true if attribute == "actions_if_true" else self.actions_false
        current = self._current(widget)
        index = current + 1 if current is not None else len(actions)
        self._execute(InsertItem(actions, index, item, SCRIPTS, "New Action"))

    def edit_argument(self, items: _ItemList, row: int, argument: int) -> None:
        """Edit the condition or action on `row`, starting at the argument that was clicked."""
        items.list.setCurrentRow(row)
        self.edit_item(items, focus_argument=argument)

    def find_target(self, argument: ScriptArgument) -> ScriptTarget | None:
        """What `argument` names in the open map, or `None` when it names nothing there."""
        document = self.host.document
        return argument_target(argument, document.map) if document is not None else None

    def item_at(self, items: _ItemList, row: int) -> ScriptDerived | None:
        """The condition or action a list row stands for; `None` for an IF/OR header."""
        script = self.selected
        entry = items.list.item(row) if 0 <= row < items.list.count() else None
        data = entry.data(_ROLE) if entry is not None else None
        if not isinstance(script, Script) or data is None:
            return None
        if items is self.conditions:
            if not isinstance(data, tuple) or data[1] is None:
                return None
            clause, index = data
            if not 0 <= clause < len(script.or_conditions):
                return None
            conditions = script.or_conditions[clause].conditions
            return conditions[index] if 0 <= index < len(conditions) else None
        actions = script.actions_if_true if items is self.actions_true else script.actions_if_false
        return actions[data] if isinstance(data, int) and 0 <= data < len(actions) else None

    def item_targets(self, item: ScriptDerived) -> list[ScriptTarget]:
        """Everything the item's arguments name in the map, in argument order, each listed once:
        an action naming the same team twice offers one entry for it."""
        found: list[ScriptTarget] = []
        seen: set[tuple[str, str]] = set()
        for argument in item.arguments:
            target = self.find_target(argument)
            if target is None or (target.kind, target.name) in seen:
                continue
            seen.add((target.kind, target.name))
            found.append(target)
        return found

    def show_item_menu(self, items: _ItemList, point: QPoint) -> None:
        """The right-click handler of a condition or action list: open the menu of the row under
        the cursor, at the cursor."""
        entry = items.list.itemAt(point)
        if entry is None:
            return
        viewport = items.list.viewport()
        at = viewport.mapToGlobal(point) if viewport is not None else point
        self.open_item_menu(items, items.list.row(entry), at)

    def open_item_menu(self, items: _ItemList, row: int, at: QPoint) -> None:
        """The menu of a condition or action row: edit it, or go to anything its arguments name.
        An imported item is read-only, so only its Go To entries do anything."""
        items.list.setCurrentRow(row)
        item = self.item_at(items, row)
        menu = QMenu(self)
        edit = menu.addAction("Edit…")
        if edit is not None:
            edit.setEnabled(item is not None and not self.locked())
        targets = self.item_targets(item) if item is not None and self.go_to is not None else []
        if targets:
            menu.addSeparator()
        entries = {menu.addAction(target.label): target for target in targets}
        chosen = menu.exec(at)
        if chosen is None:
            return
        if chosen is edit:
            self.edit_item(items)
        elif chosen in entries and self.go_to is not None:
            self.go_to(entries[chosen])

    def edit_item(self, items: _ItemList, focus_argument: int | None = None) -> None:
        target = self._target(items)
        if target is None:
            return
        container, index = target
        kind = TemplateKind.CONDITION if items is self.conditions else TemplateKind.ACTION
        edited = self._open_item_dialog(kind, container[index], focus_argument)
        if edited is not None:
            self._execute(ReplaceItem(container, index, edited, SCRIPTS, f"Edit {kind.value}"))

    def delete_item(self, items: _ItemList) -> None:
        script = self.selected
        if items is self.conditions and isinstance(script, Script):
            position = self._current(items)
            if position is not None and position[1] is None:
                self._execute(RemoveItem(script.or_conditions, position[0], SCRIPTS, "Delete OR"))
                return
        target = self._target(items)
        if target is not None:
            self._execute(RemoveItem(target[0], target[1], SCRIPTS, "Delete"))

    def move_item(self, items: _ItemList, step: int) -> None:
        target = self._target(items)
        if target is None:
            return
        container, index = target
        if 0 <= index + step < len(container):
            items.list.setCurrentRow(items.list.currentRow() + step)
            self._execute(MoveItem(container, index, container, index + step, SCRIPTS, "Move"))

    def toggle_item(self, items: _ItemList) -> None:
        target = self._target(items)
        if target is None:
            return
        item = target[0][target[1]]
        label = "Disable" if item.is_enabled else "Enable"
        self._execute(SetAttribute(item, "is_enabled", not item.is_enabled, SCRIPTS, label))
