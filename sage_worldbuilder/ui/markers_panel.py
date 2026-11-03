"""The Markers panel (beyond WorldBuilder): draw and manage the areas, points and paths an AI agent
is pointed at.

The mode buttons pick what the Markers tool draws on the map. The list shows every marker by kind;
choosing one makes it the marker the tool edits (its corners or stops get handles), a name can be
edited in place, and double-clicking a marker frames it in the view. Markers are never saved with
the map.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.markers import (
    AreaMarker,
    Marker,
    MarkerError,
    MarkerKind,
    Markers,
    PathMarker,
    PointMarker,
    path_length,
)
from sage_worldbuilder.ui.tools import MarkerMode

__all__ = ["MarkersPanel"]

_NAME_ROLE = Qt.ItemDataRole.UserRole
_GROUPS = ((MarkerKind.AREA, "Areas"), (MarkerKind.POINT, "Points"), (MarkerKind.PATH, "Paths"))
_HINTS = {
    MarkerMode.EDIT: "Drag a marker to move it, or a corner or point to reshape it. Shift-click "
    "the chosen area's edge or path's leg to add a corner or point; Alt-click one to remove it. "
    "Delete removes the chosen marker.",
    MarkerMode.RECTANGLE: "Drag a rectangle to mark an area. Click a marker to choose it.",
    MarkerMode.POLYGON: "Click to add corners; click the first corner again, or press Enter, to "
    "close the area. Backspace removes the last corner, Escape gives up.",
    MarkerMode.POINT: "Click to drop a point; drag a point to move it.",
    MarkerMode.PATH: "Click points, or ground for new points, in order; click the last stop again "
    "or press Enter to finish. Start on an end of the chosen path to extend it.",
}


class MarkersPanel(QWidget):
    mode_chosen = pyqtSignal(object)
    # A world rectangle (x0, y0, x1, y1) to show in the view.
    frame_requested = pyqtSignal(float, float, float, float)
    status = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._markers: Markers | None = None
        # What the list shows, (name, details) per marker, to tell when it needs rebuilding.
        self._listed: list[tuple[str, str]] | None = None
        self._refreshing = False
        layout = QVBoxLayout(self)

        modes = QGridLayout()
        self.mode_buttons = QButtonGroup(self)
        self.mode_buttons.setExclusive(True)
        self._modes: dict[MarkerMode, QToolButton] = {}
        for index, mode in enumerate(MarkerMode):
            button = QToolButton()
            button.setText(mode.value)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked, m=mode: self._mode_clicked(m))
            self.mode_buttons.addButton(button)
            modes.addWidget(button, index // 3, index % 3)
            self._modes[mode] = button
        layout.addLayout(modes)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Name", "Details"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.tree.currentItemChanged.connect(lambda *_: self._current_changed())
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(lambda item, _column: self._frame(item))
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.zoom_button = QPushButton("Zoom To")
        self.zoom_button.setToolTip("Show the chosen marker in the view")
        self.zoom_button.clicked.connect(lambda: self._frame(self.tree.currentItem()))
        self.rename_button = QPushButton("Rename")
        self.rename_button.setToolTip("Give the chosen marker a name to tell the agent")
        self.rename_button.clicked.connect(self._rename)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setToolTip(
            "Remove the chosen marker; a removed point leaves the paths through it"
        )
        self.delete_button.clicked.connect(self._delete)
        self.clear_button = QPushButton("Clear All")
        self.clear_button.setToolTip("Remove every marker")
        self.clear_button.clicked.connect(self._clear)
        for button in (self.zoom_button, self.rename_button, self.delete_button, self.clear_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        note = QLabel("Markers are for pointing an AI agent at places; they are not saved.")
        note.setWordWrap(True)
        note.setEnabled(False)
        layout.addWidget(note)
        self.set_mode(MarkerMode.RECTANGLE)
        self.refresh()

    def set_mode(self, mode: MarkerMode) -> None:
        """Show `mode` as chosen, without telling anyone."""
        self._modes[mode].setChecked(True)
        self.hint.setText(_HINTS[mode])

    def mode(self) -> MarkerMode:
        return next(mode for mode, button in self._modes.items() if button.isChecked())

    def _mode_clicked(self, mode: MarkerMode) -> None:
        self.set_mode(mode)
        self.mode_chosen.emit(mode)

    def set_markers(self, markers: Markers | None) -> None:
        self._markers = markers
        self._listed = None
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the list from the markers, keeping the chosen one chosen. When only the
        choice changed the list stays, so an item being renamed is not pulled away."""
        markers = self._markers
        listed = (
            [(m.name, self._details(markers, m)) for m in markers] if markers is not None else None
        )
        if listed is not None and listed == self._listed:
            self._show_choice()
            return
        self._listed = listed
        self._refreshing = True
        try:
            self.tree.clear()
            current = None
            if markers is not None:
                selected = markers.selected
                for kind, title in _GROUPS:
                    group = QTreeWidgetItem([title])
                    group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.tree.addTopLevelItem(group)
                    for marker in markers.of_kind(kind):
                        item = QTreeWidgetItem([marker.name, self._details(markers, marker)])
                        item.setData(0, _NAME_ROLE, marker.name)
                        item.setFlags(
                            Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsEditable
                        )
                        group.addChild(item)
                        if marker is selected:
                            current = item
                    group.setText(0, f"{title} ({group.childCount()})")
                    group.setExpanded(True)
            self.tree.setCurrentItem(current)
            self.tree.resizeColumnToContents(0)
        finally:
            self._refreshing = False
        self._enable()

    def _show_choice(self) -> None:
        """Make the chosen marker the list's current item."""
        markers = self._markers
        selected = markers.selected if markers is not None else None
        current = None
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            for row in range(group.childCount() if group is not None else 0):
                item = group.child(row) if group is not None else None
                if selected is not None and self._name(item) == selected.name:
                    current = item
        if current is not self.tree.currentItem():
            self._refreshing = True
            try:
                self.tree.setCurrentItem(current)
            finally:
                self._refreshing = False
        self._enable()

    def _enable(self) -> None:
        markers = self._markers
        chosen = self._name(self.tree.currentItem()) is not None
        for button in (self.zoom_button, self.rename_button, self.delete_button):
            button.setEnabled(chosen)
        self.clear_button.setEnabled(bool(markers))
        self.setEnabled(markers is not None)

    @staticmethod
    def _details(markers: Markers, marker: Marker) -> str:
        if isinstance(marker, AreaMarker):
            x0, y0, x1, y1 = marker.bounds
            shape = "rectangle" if marker.is_rectangle else f"{len(marker.points)} corners"
            return f"{shape}, {x1 - x0:.0f} x {y1 - y0:.0f}"
        if isinstance(marker, PointMarker):
            return f"({marker.x:.0f}, {marker.y:.0f})"
        assert isinstance(marker, PathMarker)
        length = path_length(markers.path_points(marker))
        return f"{' > '.join(marker.stops)}, {length:.0f} long"

    def _name(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, _NAME_ROLE) if item is not None else None

    def _current_changed(self) -> None:
        if self._refreshing or self._markers is None:
            return
        self._markers.select(self._name(self.tree.currentItem()))

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        name = self._name(item)
        if self._refreshing or self._markers is None or name is None or column != 0:
            return
        try:
            self._markers.rename(name, item.text(0))
        except MarkerError as error:
            self.status.emit(str(error))
            self.refresh()

    def _rename(self) -> None:
        item = self.tree.currentItem()
        if self._name(item) is not None:
            self.tree.editItem(item, 0)

    def _delete(self) -> None:
        name = self._name(self.tree.currentItem())
        if self._markers is not None and name is not None:
            self._markers.remove(name)

    def _clear(self) -> None:
        if self._markers is not None:
            self._markers.clear()

    def _frame(self, item: QTreeWidgetItem | None) -> None:
        name = self._name(item)
        markers = self._markers
        marker = markers.get(name) if markers is not None and name is not None else None
        if marker is None or markers is None:
            return
        if isinstance(marker, AreaMarker):
            points = list(marker.points)
        elif isinstance(marker, PointMarker):
            points = [marker.position]
        else:
            points = markers.path_points(marker)
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        # Some ground round a point or a straight path, so it is not framed edge to edge.
        span = max(max(xs) - min(xs), max(ys) - min(ys), 200.0) * 0.6
        middle = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        self.frame_requested.emit(
            middle[0] - span, middle[1] - span, middle[0] + span, middle[1] + span
        )
