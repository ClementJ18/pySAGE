"""The Terrain Material panel: WorldBuilder's Terrain Painting Mode, the texture palette, and the
value each mode paints with Single Tile, Large Tile and Flood Fill.

The palette lists the game's terrain textures by type and region (from Terrain.ini `Class`),
with a search and a preview; textures a map uses that the game data does not list are under
"This map". Choosing a texture switches the mode to Texture.

Each texture row shows a small preview. Reading a texture image takes a few milliseconds and the
game has well over a thousand, so a row's preview is read only once the row can be seen (its
group opened, or a search showing it), a few at a time between events.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_worldbuilder.brush_options import PaintMode, PaintOptions, Passability

__all__ = ["FLAMMABILITY_NAMES", "TerrainMaterialPanel"]

# Flammability radio labels by stored value (WorldBuilder's buttons carry pictures, not text).
FLAMMABILITY_NAMES = ("Fire resistant", "Grass", "Highly flammable", "Undefined")
PREVIEW_PIXELS = 96
ICON_PIXELS = 32
_NAME_ROLE = Qt.ItemDataRole.UserRole
# Set on a texture row once its preview has been looked for.
_ICON_TRIED_ROLE = Qt.ItemDataRole.UserRole + 1
# How long one batch of preview loading may hold up the event loop.
_ICON_BATCH_SECONDS = 0.02

Catalogue = dict[str, dict[str, list[str]]]


class TerrainMaterialPanel(QWidget):
    changed = pyqtSignal()
    # Apply To Tiles... was clicked.
    apply_requested = pyqtSignal()

    def __init__(self, options: PaintOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.options = options
        self._catalogue: Catalogue = {}
        self._preview_source: Callable[[str], QPixmap | None] | None = None
        self._pending_icons: deque[QTreeWidgetItem] = deque()
        self._icon_timer = QTimer(self)
        self._icon_timer.setInterval(0)
        self._icon_timer.timeout.connect(self._load_some_icons)
        layout = QVBoxLayout(self)

        mode_box = QGroupBox("Terrain Painting Mode")
        mode_layout = QVBoxLayout(mode_box)
        self.mode_buttons: dict[PaintMode, QRadioButton] = {}
        self._modes = QButtonGroup(self)
        for mode in PaintMode:
            button = QRadioButton(mode.value)
            self._modes.addButton(button)
            self.mode_buttons[mode] = button
            mode_layout.addWidget(button)
        layout.addWidget(mode_box)

        self.texture_box = QGroupBox("Texture")
        texture_layout = QVBoxLayout(self.texture_box)
        current = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_PIXELS, PREVIEW_PIXELS)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setScaledContents(True)
        current.addWidget(self.preview)
        self.texture_label = QLabel()
        self.texture_label.setWordWrap(True)
        current.addWidget(self.texture_label, 1)
        texture_layout.addLayout(current)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search textures")
        self.search.setClearButtonEnabled(True)
        texture_layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(180)
        self.tree.setIconSize(QSize(ICON_PIXELS, ICON_PIXELS))
        texture_layout.addWidget(self.tree)
        self.apply_button = QPushButton("Apply To Tiles...")
        self.apply_button.setToolTip(
            "Paint the chosen texture between slopes, between heights or at random."
        )
        self.apply_button.clicked.connect(self.apply_requested.emit)
        texture_layout.addWidget(self.apply_button)
        layout.addWidget(self.texture_box)

        self.passability_buttons = self._choices(
            layout, "Passability", [state.value for state in Passability]
        )
        self.width_buttons = self._choices(layout, "Passage Width", ["Narrow", "Open"])
        self.taint_buttons = self._choices(layout, "Taintability", ["Taintable", "Not taintable"])
        self.flammability_buttons = self._choices(layout, "Flammability", list(FLAMMABILITY_NAMES))
        self.visibility_buttons = self._choices(layout, "Visibility", ["Visible", "Not visible"])
        self._groups = {
            PaintMode.PASSABILITY: self.passability_buttons,
            PaintMode.PASSAGE_WIDTH: self.width_buttons,
            PaintMode.TAINTABILITY: self.taint_buttons,
            PaintMode.FLAMMABILITY: self.flammability_buttons,
            PaintMode.VISIBILITY: self.visibility_buttons,
        }
        note = QLabel(
            "Single Tile paints one cell, Large Tile a square the brush width across, Flood Fill "
            "an area of one texture. Alt-click picks the texture under the cursor."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self.refresh()
        for button in self.mode_buttons.values():
            button.toggled.connect(self._store)
        for buttons in self._groups.values():
            for button in buttons:
                button.toggled.connect(self._store)
        self.search.textChanged.connect(self._fill_tree)
        self.tree.currentItemChanged.connect(self._texture_clicked)
        self.tree.itemExpanded.connect(self._queue_leaves_of)

    def _choices(self, layout: QVBoxLayout, title: str, labels: list[str]) -> list[QRadioButton]:
        box = QGroupBox(title)
        box_layout = QVBoxLayout(box)
        group = QButtonGroup(self)
        buttons = []
        for label in labels:
            button = QRadioButton(label)
            group.addButton(button)
            box_layout.addWidget(button)
            buttons.append(button)
        layout.addWidget(box)
        return buttons

    def set_catalogue(self, catalogue: Catalogue) -> None:
        """The textures to offer, as type -> region ('' for none) -> names."""
        self._catalogue = catalogue
        self._fill_tree()

    def set_preview_source(self, source: Callable[[str], QPixmap | None] | None) -> None:
        self._preview_source = source
        self._show_texture()
        if self._catalogue:
            self._fill_tree()

    def texture_names(self) -> list[str]:
        """Every texture the palette lists, in its order."""
        return [
            name
            for regions in self._catalogue.values()
            for names in regions.values()
            for name in names
        ]

    def select_texture(self, name: str) -> None:
        """Paint `name` from now on, switching to Texture mode."""
        self.options.texture = name
        self.options.mode = PaintMode.TEXTURE
        self.refresh()
        self.changed.emit()

    def refresh(self) -> None:
        options = self.options
        chosen = {
            PaintMode.PASSABILITY: list(Passability).index(options.passability),
            PaintMode.PASSAGE_WIDTH: 0 if options.narrow else 1,
            PaintMode.TAINTABILITY: 0 if options.taintable else 1,
            PaintMode.FLAMMABILITY: options.flammability,
            PaintMode.VISIBILITY: 0 if options.visible else 1,
        }
        widgets = [*self.mode_buttons.values()] + [b for g in self._groups.values() for b in g]
        for widget in widgets:
            widget.blockSignals(True)
        self.mode_buttons[options.mode].setChecked(True)
        for mode, buttons in self._groups.items():
            buttons[chosen[mode]].setChecked(True)
            box = buttons[0].parentWidget()
            if box is not None:
                box.setEnabled(mode is options.mode)
        for widget in widgets:
            widget.blockSignals(False)
        self._show_texture()

    def _show_texture(self) -> None:
        name = self.options.texture
        self.texture_label.setText(name or "No texture chosen")
        pixmap = self._preview_source(name) if self._preview_source and name else None
        if pixmap is None:
            self.preview.clear()
            self.preview.setText("No preview")
        else:
            self.preview.setPixmap(pixmap)

    def _fill_tree(self) -> None:
        needle = self.search.text().strip().lower()
        # The rows are about to be deleted; a queued one must not be touched after that.
        self._pending_icons.clear()
        self._icon_timer.stop()
        self.tree.blockSignals(True)
        self.tree.clear()
        for kind, regions in self._catalogue.items():
            kind_item = QTreeWidgetItem([kind])
            for region, names in regions.items():
                parent = kind_item if not region else QTreeWidgetItem([region.replace("_", " ")])
                for name in names:
                    if needle and needle not in name.lower():
                        continue
                    leaf = QTreeWidgetItem([name])
                    leaf.setData(0, _NAME_ROLE, name)
                    parent.addChild(leaf)
                    if name.lower() == self.options.texture.lower():
                        self.tree.setCurrentItem(leaf)
                if parent is not kind_item and parent.childCount():
                    kind_item.addChild(parent)
            if kind_item.childCount():
                self.tree.addTopLevelItem(kind_item)
        if needle:
            self.tree.expandAll()
        self.tree.blockSignals(False)
        for index in range(self.tree.topLevelItemCount()):
            self._queue_open_leaves(self.tree.topLevelItem(index))

    def load_pending_icons(self) -> None:
        """Read every queued preview now, rather than a few at a time."""
        while self._pending_icons:
            self._load_icon(self._pending_icons.popleft())
        self._icon_timer.stop()

    def _queue_open_leaves(self, item: QTreeWidgetItem | None) -> None:
        """Queue the previews of the texture rows showing under an open `item`."""
        if item is None or not item.isExpanded():
            return
        self._queue_leaves_of(item)
        for index in range(item.childCount()):
            self._queue_open_leaves(item.child(index))

    def _queue_leaves_of(self, item: QTreeWidgetItem) -> None:
        if self._preview_source is None:
            return
        for index in range(item.childCount()):
            child = item.child(index)
            if (
                child is not None
                and child.data(0, _NAME_ROLE)
                and not child.data(0, _ICON_TRIED_ROLE)
            ):
                self._pending_icons.append(child)
        if self._pending_icons and not self._icon_timer.isActive():
            self._icon_timer.start()

    def _load_some_icons(self) -> None:
        deadline = time.perf_counter() + _ICON_BATCH_SECONDS
        while self._pending_icons and time.perf_counter() < deadline:
            self._load_icon(self._pending_icons.popleft())
        if not self._pending_icons:
            self._icon_timer.stop()

    def _load_icon(self, leaf: QTreeWidgetItem) -> None:
        if leaf.data(0, _ICON_TRIED_ROLE):
            return
        leaf.setData(0, _ICON_TRIED_ROLE, True)
        name = leaf.data(0, _NAME_ROLE)
        source = self._preview_source
        pixmap = source(name) if source is not None and isinstance(name, str) else None
        if pixmap is not None and not pixmap.isNull():
            leaf.setIcon(0, QIcon(pixmap))

    def _texture_clicked(self, current: QTreeWidgetItem | None, _previous: object) -> None:
        name = current.data(0, _NAME_ROLE) if current is not None else None
        if isinstance(name, str) and name:
            self.select_texture(name)

    def _store(self) -> None:
        options = self.options
        for mode, button in self.mode_buttons.items():
            if button.isChecked():
                options.mode = mode
        options.passability = list(Passability)[_checked(self.passability_buttons)]
        options.narrow = _checked(self.width_buttons) == 0
        options.taintable = _checked(self.taint_buttons) == 0
        options.flammability = _checked(self.flammability_buttons)
        options.visible = _checked(self.visibility_buttons) == 0
        self.refresh()
        self.changed.emit()


def _checked(buttons: list[QRadioButton]) -> int:
    return next((index for index, button in enumerate(buttons) if button.isChecked()), 0)
