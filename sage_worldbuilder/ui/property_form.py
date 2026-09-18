"""A form over one property dictionary: a field for each spec, and every edit issued as a
command so it can be undone."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from itertools import groupby
from typing import Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from sage_map.context import Property
from sage_utils.widgets import make_completer
from sage_worldbuilder.changes import Change
from sage_worldbuilder.commands import Command
from sage_worldbuilder.properties import Editor, PropertySpec, set_value, value_of

__all__ = ["PresetField", "PropertyForm"]

_INT_MIN, _INT_MAX = -(2**31), 2**31 - 1
_REAL_LIMIT = 1e9
_CHECK_BOX_COLUMNS = 2

Suggestions = Callable[[], Sequence[str]]
OTHER = "Other"


class PresetField(QWidget):
    """A drop-down of a spec's named values and Other, with a number box beside it that is
    enabled only for Other, as WorldBuilder's starting-health field is. `commit` is called
    with each value chosen or typed."""

    def __init__(self, spec: PropertySpec, commit: Callable[[int], None]) -> None:
        super().__init__()
        self.spec = spec
        self.presets = spec.presets or ()
        self._commit = commit
        self._updating = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.choice = QComboBox()
        self.choice.addItems([name for name, _value in self.presets] + [OTHER])
        self.number = QSpinBox()
        self.number.setRange(_INT_MIN, _INT_MAX)
        self.number.setKeyboardTracking(False)
        row.addWidget(self.choice, 1)
        row.addWidget(self.number, 1)
        self.choice.currentIndexChanged.connect(self._chosen)
        self.number.valueChanged.connect(self._typed)

    def show_value(self, value: int) -> None:
        self._updating = True
        try:
            values = [preset for _name, preset in self.presets]
            index = values.index(value) if value in values else len(values)
            self.choice.setCurrentIndex(index)
            self.number.setValue(value)
            self.number.setEnabled(index == len(values))
        finally:
            self._updating = False

    def _chosen(self, index: int) -> None:
        if self._updating:
            return
        if index == len(self.presets):
            value = self.spec.other
            self._show_other(value)
        else:
            value = self.presets[index][1]
            self.show_value(value)
        self._commit(value)

    def _show_other(self, value: int) -> None:
        self._updating = True
        try:
            self.number.setValue(value)
            self.number.setEnabled(True)
        finally:
            self._updating = False

    def _typed(self, value: int) -> None:
        if not self._updating:
            self._commit(value)


class PropertyForm(QWidget):
    """`suggestions` maps a text key to a function listing the names it may take (players,
    waypoints, scripts, objects); those fields become editable drop-downs with completion.
    `commands` maps a key to a function building the command for a new value, for a key whose
    change must also update something else. A spec whose choices are a callable has its drop-down
    refilled whenever the form reloads."""

    def __init__(
        self,
        specs: Sequence[PropertySpec],
        execute: Callable[[Command], None],
        change: Change,
        suggestions: Mapping[str, Suggestions] | None = None,
        parent: QWidget | None = None,
        commands: Mapping[str, Callable[[Any], Command]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.specs = tuple(specs)
        self.execute = execute
        self.change = change
        self.suggestions = dict(suggestions or {})
        self.commands = dict(commands or {})
        self.properties: dict[str, Property] | None = None
        self._updating = False
        self._listed: dict[str, tuple[str, ...]] = {}
        self.form = QFormLayout(self)
        self.fields: dict[str, QWidget] = {}
        for is_boolean, run in groupby(self.specs, lambda spec: spec.editor is Editor.BOOLEAN):
            specs_in_run = list(run)
            if is_boolean and len(specs_in_run) > 1:
                self.form.addRow(self._check_box_grid(specs_in_run))
                continue
            for spec in specs_in_run:
                field = self._field(spec)
                self.fields[spec.name] = field
                self.form.addRow(spec.label, field)
        self.set_properties(None)

    def _check_box_grid(self, specs: Sequence[PropertySpec]) -> QGridLayout:
        """Consecutive check boxes, labelled by their own text, filled row by row across
        columns so they take less height than a row each."""
        grid = QGridLayout()
        for column in range(_CHECK_BOX_COLUMNS):
            grid.setColumnStretch(column, 1)
        for position, spec in enumerate(specs):
            box = self._check_box(spec)
            box.setText(spec.label)
            self.fields[spec.name] = box
            grid.addWidget(box, *divmod(position, _CHECK_BOX_COLUMNS))
        return grid

    def _check_box(self, spec: PropertySpec) -> QCheckBox:
        box = QCheckBox()
        box.toggled.connect(lambda on, spec=spec: self._commit(spec, on))
        return box

    def _field(self, spec: PropertySpec) -> QWidget:
        editor = spec.editor
        if editor is Editor.BOOLEAN:
            return self._check_box(spec)
        if editor is Editor.CHOICE:
            choice = QComboBox()
            self._listed[spec.name] = spec.choice_names()
            choice.addItems(self._listed[spec.name])
            choice.currentIndexChanged.connect(
                lambda index, spec=spec: self._commit(spec, index + spec.choice_base)
            )
            return choice
        if editor is Editor.PRESET:
            return PresetField(spec, lambda value, spec=spec: self._commit(spec, value))
        if editor is Editor.INTEGER:
            spin = QSpinBox()
            spin.setRange(_INT_MIN, _INT_MAX)
            spin.valueChanged.connect(lambda value, spec=spec: self._commit(spec, value))
            return spin
        if editor is Editor.REAL:
            real = QDoubleSpinBox()
            real.setRange(-_REAL_LIMIT, _REAL_LIMIT)
            real.setDecimals(3)
            real.valueChanged.connect(lambda value, spec=spec: self._commit(spec, value))
            return real
        if spec.name in self.suggestions:
            names = QComboBox()
            names.setEditable(True)
            names.textActivated.connect(lambda text, spec=spec: self._commit(spec, text))
            line = names.lineEdit()
            if line is not None:
                line.editingFinished.connect(
                    lambda spec=spec, names=names: self._commit(spec, names.currentText())
                )
            return names
        text = QLineEdit()
        text.editingFinished.connect(lambda spec=spec, text=text: self._commit(spec, text.text()))
        return text

    def set_properties(self, properties: dict[str, Property] | None) -> None:
        self.properties = properties
        self.setEnabled(properties is not None)
        self.reload()

    def reload(self) -> None:
        """Show the dictionary's current values (or the defaults, for absent keys)."""
        self._updating = True
        try:
            for spec in self.specs:
                self._show(spec, value_of(self.properties or {}, spec))
        finally:
            self._updating = False

    def _show(self, spec: PropertySpec, value: Any) -> None:
        field = self.fields[spec.name]
        if isinstance(field, PresetField):
            field.show_value(int(value))
        elif isinstance(field, QCheckBox):
            field.setChecked(bool(value))
        elif isinstance(field, QSpinBox):
            field.setValue(int(value))
        elif isinstance(field, QDoubleSpinBox):
            field.setValue(float(value))
        elif isinstance(field, QComboBox) and not field.isEditable():
            # The list can grow after the field was built - a weather a patched engine adds
            # arrives with the `.sagepatch`, long after the panel.
            names = spec.choice_names()
            if self._listed.get(spec.name) != names:
                field.clear()
                field.addItems(names)
                self._listed[spec.name] = names
            index = int(value) - spec.choice_base
            field.setCurrentIndex(index if 0 <= index < field.count() else -1)
        elif isinstance(field, QComboBox):
            names = tuple(self.suggestions[spec.name]())
            if self._listed.get(spec.name) != names:
                field.clear()
                field.addItems(names)
                field.setCompleter(make_completer(field, names=names))
                self._listed[spec.name] = names
            field.setCurrentText(str(value))
        elif isinstance(field, QLineEdit) and field.text() != str(value):
            field.setText(str(value))

    def _commit(self, spec: PropertySpec, value: Any) -> None:
        properties = self.properties
        if self._updating or properties is None:
            return
        current = value_of(properties, spec)
        if current == value and (spec.name in properties or value == spec.default):
            return
        build = self.commands.get(spec.name)
        if build is not None:
            self.execute(build(value))
        else:
            self.execute(set_value(properties, spec, value, self.change))
