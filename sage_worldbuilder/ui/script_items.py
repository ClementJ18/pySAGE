"""The dialog that creates or edits one condition or action: pick its template from
WorldBuilder's tree, then fill in each parameter."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.player_scripts import ScriptArgument, ScriptDerived
from sage_map.scripts import arg_spec
from sage_utils.widgets import make_completer
from sage_worldbuilder.scripting import (
    argument_choices,
    item_template,
    new_item,
    retarget,
)
from sage_worldbuilder.templates import (
    ScriptTemplate,
    TemplateKind,
    parameter_values,
    script_templates,
)
from sage_worldbuilder.ui.sentences import argument_at, link_color, sentence_html

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = ["ScriptItemDialog"]

_INT_MIN, _INT_MAX = -(2**31), 2**31 - 1
_REAL_LIMIT = 1e9


class ScriptItemDialog(QDialog):
    """`item` is left untouched; the edited copy is `self.item` once the dialog is accepted."""

    def __init__(
        self,
        kind: TemplateKind,
        item: ScriptDerived | None,
        symbols: Mapping[str, Sequence[str]],
        game: Game | None,
        parent: QWidget | None = None,
        focus_argument: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        # The parameter whose field last took the focus from a link or on opening.
        self.focused_argument: int | None = None
        self.symbols = symbols
        self.game = game
        self.item: ScriptDerived | None = copy.deepcopy(item) if item is not None else None
        noun = "Condition" if kind is TemplateKind.CONDITION else "Action"
        self.setWindowTitle(f"Edit {noun}" if item is not None else f"New {noun}")
        self.resize(1000, 640)

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {noun.lower()}s by name or path")
        self.search.textChanged.connect(self._filter)
        left_layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda current, _previous: self._chosen(current))
        left_layout.addWidget(self.tree, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.preview.setStyleSheet("font-size: 13pt;")
        preview_palette = self.preview.palette()
        preview_palette.setColor(
            QPalette.ColorRole.Link,
            link_color(preview_palette, preview_palette.color(QPalette.ColorRole.Window)),
        )
        self.preview.setPalette(preview_palette)
        self.preview.linkActivated.connect(self._link_activated)
        right_layout.addWidget(self.preview)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_layout.addWidget(self.details)
        self.form = QFormLayout()
        right_layout.addLayout(self.form)
        self.enabled_box = QCheckBox("Enabled")
        self.enabled_box.toggled.connect(lambda _checked: self._update_preview())
        right_layout.addWidget(self.enabled_box)
        self.inverted_box = QCheckBox("NOT: true when the condition is false")
        self.inverted_box.toggled.connect(lambda _checked: self._update_preview())
        self.inverted_box.setVisible(kind is TemplateKind.CONDITION)
        right_layout.addWidget(self.inverted_box)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([420, 580])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._leaves: dict[tuple[TemplateKind, int], QTreeWidgetItem] = {}
        self._build_tree()
        if self.item is not None:
            self.enabled_box.setChecked(bool(self.item.is_enabled))
            self.inverted_box.setChecked(bool(self.item.is_inverted))
            entry = item_template(self.item, kind)
            if entry is not None:
                leaf = self._leaves[(entry.kind, entry.id)]
                self.tree.blockSignals(True)
                self.tree.setCurrentItem(leaf)
                self.tree.blockSignals(False)
                self.tree.scrollToItem(leaf)
        else:
            self.enabled_box.setChecked(True)
        self._show_item()
        if focus_argument is not None:
            # After the dialog is shown: a widget cannot take the focus before that.
            QTimer.singleShot(0, lambda: self.focus_argument(focus_argument))

    def argument_editor(self, index: int) -> QWidget | None:
        """The field editing argument `index`."""
        if not 0 <= index < self.form.rowCount():
            return None
        entry = self.form.itemAt(index, QFormLayout.ItemRole.FieldRole)
        return entry.widget() if entry is not None else None

    def focus_argument(self, index: int) -> None:
        editor = self.argument_editor(index)
        if editor is None:
            return
        self.focused_argument = index
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        line = editor.lineEdit() if isinstance(editor, QComboBox) else None
        if line is not None:
            line.selectAll()

    def _link_activated(self, anchor: str) -> None:
        index = argument_at(anchor)
        if index is not None:
            self.focus_argument(index)

    def _build_tree(self) -> None:
        folders: dict[tuple[str, ...], QTreeWidgetItem] = {}
        entries = [entry for entry in script_templates() if entry.kind is self.kind]
        for entry in sorted(entries, key=lambda e: tuple(part.casefold() for part in e.path)):
            parent: QTreeWidgetItem | None = None
            path = entry.path
            for depth in range(len(path) - 1):
                key = path[: depth + 1]
                folder = folders.get(key)
                if folder is None:
                    folder = QTreeWidgetItem([path[depth]])
                    if parent is None:
                        self.tree.addTopLevelItem(folder)
                    else:
                        parent.addChild(folder)
                    folders[key] = folder
                parent = folder
            leaf = QTreeWidgetItem([path[-1]])
            leaf.setData(0, Qt.ItemDataRole.UserRole, entry)
            leaf.setToolTip(0, entry.internal_name)
            if parent is None:
                self.tree.addTopLevelItem(leaf)
            else:
                parent.addChild(leaf)
            self._leaves[(entry.kind, entry.id)] = leaf

    def select_template(self, entry: ScriptTemplate) -> None:
        self.tree.setCurrentItem(self._leaves[(entry.kind, entry.id)])

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()

        def visit(node: QTreeWidgetItem) -> bool:
            entry = node.data(0, Qt.ItemDataRole.UserRole)
            if entry is not None:
                haystack = f"{entry.ui_name} {entry.internal_name}".casefold()
                visible = needle in haystack
            else:
                children = (node.child(i) for i in range(node.childCount()))
                visible = any([visit(child) for child in children if child is not None])
            node.setHidden(not visible)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            if top is not None:
                visit(top)
        if needle:
            self.tree.expandAll()
        else:
            self.tree.collapseAll()

    def _chosen(self, current: QTreeWidgetItem | None) -> None:
        entry = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        if entry is None:
            return
        self.item = retarget(self.item, entry) if self.item is not None else new_item(entry)
        self._show_item()

    def _show_item(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        item = self.item
        has_item = item is not None
        for widget in (self.enabled_box, self.inverted_box):
            widget.setEnabled(has_item)
        if self.ok_button is not None:
            self.ok_button.setEnabled(has_item)
        if item is None:
            self.preview.setText("Choose a template on the left.")
            self.details.setText("")
            return
        entry = item_template(item, self.kind)
        if entry is not None:
            self.details.setText(f"{entry.internal_name}\n{entry.ui_name}")
        for index, argument in enumerate(item.arguments):
            label = ""
            if entry is not None and index < len(entry.ui_strings):
                label = (entry.ui_strings[index] or "").strip()
            self.form.addRow(label or f"Parameter {index + 1}", self._editor(argument))
        self._update_preview()

    def _update_preview(self) -> None:
        if self.item is None:
            return
        self.item.is_enabled = self.enabled_box.isChecked()
        if self.kind is TemplateKind.CONDITION:
            self.item.is_inverted = self.inverted_box.isChecked()
        self.preview.setText(sentence_html(self.item, self.kind))

    def _setter(self, argument: ScriptArgument, field: str) -> Callable[[Any], None]:
        def apply(value: Any) -> None:
            setattr(argument, field, value)
            self._update_preview()

        return apply

    def _editor(self, argument: ScriptArgument) -> QWidget:
        kind = argument.type
        names = parameter_values(kind)
        if names is not None:
            return self._value_box(argument, names)
        field = arg_spec(kind).field
        if field == "position_value":
            return self._position_editor(argument)
        if field == "int_value":
            spin = QSpinBox()
            spin.setRange(_INT_MIN, _INT_MAX)
            spin.setValue(argument.int_value or 0)
            spin.valueChanged.connect(self._setter(argument, "int_value"))
            return spin
        if field == "float_value":
            real = QDoubleSpinBox()
            real.setRange(-_REAL_LIMIT, _REAL_LIMIT)
            real.setDecimals(4)
            real.setValue(argument.float_value or 0.0)
            real.valueChanged.connect(self._setter(argument, "float_value"))
            return real
        box = QComboBox()
        box.setEditable(True)
        choices = argument_choices(kind, self.symbols, self.game)
        box.addItems(choices)
        box.setCurrentText(argument.string_value or "")
        if choices:
            box.setCompleter(make_completer(box, names=choices))
        box.currentTextChanged.connect(self._setter(argument, "string_value"))
        return box

    def _value_box(self, argument: ScriptArgument, names: Sequence[str]) -> QComboBox:
        box = QComboBox()
        box.addItems(names)
        value = argument.int_value or 0
        if not 0 <= value < len(names):
            box.addItem(str(value))  # a value outside the table, kept as stored
        box.setCurrentIndex(value if 0 <= value < len(names) else len(names))
        apply = self._setter(argument, "int_value")
        box.currentIndexChanged.connect(lambda index: apply(index if index < len(names) else value))
        return box

    def _position_editor(self, argument: ScriptArgument) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        spins = []
        for component in argument.position_value or (0.0, 0.0, 0.0):
            spin = QDoubleSpinBox()
            spin.setRange(-_REAL_LIMIT, _REAL_LIMIT)
            spin.setDecimals(2)
            spin.setValue(component)
            layout.addWidget(spin)
            spins.append(spin)
        apply = self._setter(argument, "position_value")
        for spin in spins:
            spin.valueChanged.connect(lambda _value: apply(tuple(s.value() for s in spins)))
        return row

    def accept(self) -> None:
        if self.item is None:
            return
        self._update_preview()
        super().accept()
