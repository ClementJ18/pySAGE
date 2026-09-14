"""The Object Properties panel: what is selected, with a tab for each kind of thing in the
selection and only those.

- **Object** (ordinary placed objects): the first one's properties; an edit is set on every
  selected object.
- **Waypoint** (waypoints): the first one's name, path labels, bi-directional flag and type; an
  edit is set on every selected waypoint.
- **Area** (trigger areas): the first one's name, and the layer of every selected area.
- **Other keys** (objects or waypoints): the keys the first one stores that its tab does not
  cover, read-only, so nothing stored is hidden.

Position and angle show while objects or waypoints are selected: X and Y move all of them by the
change to the first, Z is set on each, and the angle on each ordinary object. Every edit is one
undo entry.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.object_list import Object
from sage_map.assets.trigger_areas import TriggerArea
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command, CompositeCommand, SetAttribute
from sage_worldbuilder.commands.edits import SetProperty
from sage_worldbuilder.objects import MoveObjects
from sage_worldbuilder.properties import OBJECT_SPECS, WAYPOINT_SPECS
from sage_worldbuilder.scene import WAYPOINT_PREFIX
from sage_worldbuilder.teams import qualified_team_name, team_list
from sage_worldbuilder.ui.host import PanelHost
from sage_worldbuilder.ui.property_form import PropertyForm

__all__ = ["ObjectPropertiesPanel"]

OBJECTS = Change(ChangeKind.OBJECTS)
AREAS = Change(ChangeKind.AREAS)
_COORDINATE_LIMIT = 1e6
_OBJECT_KEYS = {spec.name for spec in OBJECT_SPECS} | {"uniqueID"}
_WAYPOINT_KEYS = {spec.name for spec in WAYPOINT_SPECS} | {"uniqueID", "waypointID"}


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


class ObjectPropertiesPanel(QWidget):
    def __init__(self, host: PanelHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        # The selection by kind, each in selection order.
        self.objects: list[Object] = []
        self.waypoints: list[Object] = []
        self.areas: list[TriggerArea] = []
        self._updating = False
        layout = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        # Selectable so the object's name can be copied.
        self.heading.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        layout.addWidget(self.heading)

        self.placement = QWidget()
        placement = QFormLayout(self.placement)
        placement.setContentsMargins(0, 0, 0, 0)
        # Not `x` / `y`: those would hide QWidget.x() and QWidget.y().
        self.x_field = self._coordinate()
        self.y_field = self._coordinate()
        self.z_field = self._coordinate()
        self.angle = QDoubleSpinBox()
        self.angle.setRange(-360.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("°")
        self.angle.setKeyboardTracking(False)
        placement.addRow("X", self.x_field)
        placement.addRow("Y", self.y_field)
        placement.addRow("Z", self.z_field)
        placement.addRow("Angle", self.angle)
        layout.addWidget(self.placement)
        self.x_field.valueChanged.connect(lambda _value: self._move())
        self.y_field.valueChanged.connect(lambda _value: self._move())
        self.z_field.valueChanged.connect(self._set_z)
        self.angle.valueChanged.connect(self._set_angle)

        self.tabs = QTabWidget()
        suggestions = {"originalOwner": self._team_names, "objectLayer": self._layer_names}
        self.object_form = PropertyForm(
            OBJECT_SPECS, self._executor(lambda: self.objects), OBJECTS, suggestions
        )
        self.waypoint_form = PropertyForm(
            WAYPOINT_SPECS, self._executor(lambda: self.waypoints), OBJECTS
        )
        # The Listen button plays the first object's ambient sound (`MapObjectProps::OnListen`);
        # the window sets what it calls.
        self.listen: Callable[[Object], None] | None = None
        object_page = QWidget()
        object_column = QVBoxLayout(object_page)
        object_column.setContentsMargins(0, 0, 0, 0)
        object_column.addWidget(self.object_form)
        self.listen_button = QPushButton("&Listen")
        self.listen_button.setToolTip("Play the ambient sound of the first selected object")
        self.listen_button.clicked.connect(self._listen)
        object_column.addWidget(self.listen_button)
        self.object_tab = _scrolling(object_page)
        self.tabs.addTab(self.object_tab, "Object")
        self.waypoint_tab = _scrolling(self.waypoint_form)
        self.tabs.addTab(self.waypoint_tab, "Waypoint")
        self.area_tab = QWidget()
        area_form = QFormLayout(self.area_tab)
        self.area_name = QLineEdit()
        self.area_name.editingFinished.connect(self._rename_area)
        self.area_layer = QLineEdit()
        self.area_layer.editingFinished.connect(self._set_area_layer)
        self.area_details = QLabel()
        area_form.addRow("Name", self.area_name)
        area_form.addRow("Layer", self.area_layer)
        area_form.addRow(self.area_details)
        self.tabs.addTab(self.area_tab, "Area")
        self.other_keys = QTreeWidget()
        self.other_keys.setHeaderLabels(["Key", "Type", "Value"])
        self.other_keys.setRootIsDecorated(False)
        self.tabs.addTab(self.other_keys, "Other keys")
        layout.addWidget(self.tabs, 1)
        self.refresh()

    @staticmethod
    def _coordinate() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-_COORDINATE_LIMIT, _COORDINATE_LIMIT)
        spin.setDecimals(2)
        spin.setKeyboardTracking(False)
        return spin

    @property
    def placed(self) -> list[Object]:
        """The selected objects and waypoints, in selection order."""
        document = self.host.document
        if document is None:
            return []
        return [item for item in document.selection if isinstance(item, Object)]

    def visible_tabs(self) -> list[QWidget]:
        return [
            widget
            for index in range(self.tabs.count())
            if self.tabs.isTabVisible(index) and (widget := self.tabs.widget(index)) is not None
        ]

    def refresh(self) -> None:
        document = self.host.document
        selected = list(document.selection) if document is not None else []
        placed = [item for item in selected if isinstance(item, Object)]
        self.waypoints = [obj for obj in placed if obj.type_name.startswith(WAYPOINT_PREFIX)]
        self.objects = [obj for obj in placed if not obj.type_name.startswith(WAYPOINT_PREFIX)]
        self.areas = [item for item in selected if isinstance(item, TriggerArea)]
        current = self.tabs.currentWidget()
        self._updating = True
        try:
            self.heading.setText(self._describe(document is not None, placed))
            self._show_placement(placed)
            self.object_form.set_properties(self.objects[0].properties if self.objects else None)
            self.waypoint_form.set_properties(
                self.waypoints[0].properties if self.waypoints else None
            )
            self._show_area()
            self._fill_other_keys(placed[0] if placed else None)
            shown = {
                self.object_tab: bool(self.objects),
                self.waypoint_tab: bool(self.waypoints),
                self.area_tab: bool(self.areas),
                self.other_keys: bool(placed),
            }
            for widget, visible in shown.items():
                self.tabs.setTabVisible(self.tabs.indexOf(widget), visible)
            self.tabs.setVisible(any(shown.values()))
            visible_tabs = self.visible_tabs()
            if visible_tabs and current not in visible_tabs:
                self.tabs.setCurrentWidget(visible_tabs[0])
        finally:
            self._updating = False

    def _describe(self, has_document: bool, placed: Sequence[Object]) -> str:
        if not has_document:
            return "No map open."
        counts = [
            _count(len(items), noun)
            for items, noun in (
                (self.objects, "object"),
                (self.waypoints, "waypoint"),
                (self.areas, "trigger area"),
            )
            if items
        ]
        if not counts:
            return "Nothing selected."
        if placed:
            first = placed[0]
            if first.type_name.startswith(WAYPOINT_PREFIX):
                name = first.properties.get("waypointName")
                lead = f"Waypoint {name['value']}" if name else "Waypoint"
            else:
                unique = first.properties.get("uniqueID")
                lead = first.type_name + (f" ({unique['value']})" if unique else "")
        else:
            lead = f"Trigger area {self.areas[0].name}"
        if len(placed) + len(self.areas) == 1:
            return lead
        return f"{lead}; {', '.join(counts)} selected"

    def _show_placement(self, placed: Sequence[Object]) -> None:
        self.placement.setVisible(bool(placed))
        if not placed:
            return
        x, y, z = placed[0].position
        self.x_field.setValue(x)
        self.y_field.setValue(y)
        self.z_field.setValue(z)
        self.angle.setEnabled(bool(self.objects))
        self.angle.setValue(math.degrees(self.objects[0].angle) if self.objects else 0.0)

    def _show_area(self) -> None:
        area = self.areas[0] if self.areas else None
        self.area_name.setText(area.name if area is not None else "")
        self.area_layer.setText(area.layer_name if area is not None else "")
        self.area_details.setText(
            f"Id {area.area_id}, {len(area.points)} corners" if area is not None else ""
        )

    def _fill_other_keys(self, lead: Object | None) -> None:
        self.other_keys.clear()
        if lead is None:
            return
        covered = _WAYPOINT_KEYS if lead.type_name.startswith(WAYPOINT_PREFIX) else _OBJECT_KEYS
        rows = [
            QTreeWidgetItem([name, stored["type"].name, str(stored["value"])])
            for name, stored in lead.properties.items()
            if name not in covered
        ]
        self.other_keys.addTopLevelItems(rows)

    def _executor(self, targets: Callable[[], list[Object]]) -> Callable[[Command], None]:
        """Run a form's edit, made on the first of `targets`, on every one of them."""

        def execute(command: Command) -> None:
            items = targets()
            if isinstance(command, SetProperty) and len(items) > 1:
                command = CompositeCommand(
                    command.label,
                    [
                        SetProperty(
                            item.properties,
                            command.name,
                            command.value,
                            command.change,
                            command.label,
                        )
                        for item in items
                    ],
                )
            self.host.execute(command)

        return execute

    def _listen(self) -> None:
        if self.listen is not None and self.objects:
            self.listen(self.objects[0])

    def _move(self) -> None:
        placed = self.placed
        if self._updating or not placed:
            return
        lead_x, lead_y, _ = placed[0].position
        dx, dy = self.x_field.value() - lead_x, self.y_field.value() - lead_y
        if dx or dy:
            self.host.execute(MoveObjects(placed, dx, dy, "Set position"))

    def _set_z(self, value: float) -> None:
        placed = self.placed
        if self._updating or not placed:
            return
        commands: list[Command] = [
            SetAttribute(
                obj, "position", (obj.position[0], obj.position[1], value), OBJECTS, "Set Z"
            )
            for obj in placed
        ]
        self.host.execute(CompositeCommand("Set Z", commands))

    def _set_angle(self, value: float) -> None:
        if self._updating or not self.objects:
            return
        commands: list[Command] = [
            SetAttribute(obj, "angle", math.radians(value), OBJECTS, "Set angle")
            for obj in self.objects
        ]
        self.host.execute(CompositeCommand("Set angle", commands))

    def _rename_area(self) -> None:
        if self._updating or not self.areas:
            return
        area, name = self.areas[0], self.area_name.text().strip()
        if name and name != area.name:
            self.host.execute(SetAttribute(area, "name", name, AREAS, "Rename Trigger Area"))

    def _set_area_layer(self) -> None:
        if self._updating or not self.areas:
            return
        layer = self.area_layer.text().strip()
        changed = [area for area in self.areas if area.layer_name != layer]
        if changed:
            self.host.execute(
                CompositeCommand(
                    "Set Layer",
                    [
                        SetAttribute(area, "layer_name", layer, AREAS, "Set Layer")
                        for area in changed
                    ],
                )
            )

    def _team_names(self) -> list[str]:
        document = self.host.document
        teams = team_list(document.map) if document is not None else None
        return [qualified_team_name(team) for team in teams or []]

    def _layer_names(self) -> list[str]:
        document = self.host.document
        if document is None or document.map.objects_list is None:
            return []
        names = {
            str(obj.properties["objectLayer"]["value"])
            for obj in document.map.objects_list.object_list
            if "objectLayer" in obj.properties
        }
        return sorted(names - {""})


def _scrolling(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    return area
