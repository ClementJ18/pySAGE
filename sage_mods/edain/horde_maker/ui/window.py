"""The Edain Horde Maker window: click soldiers onto a grid, press Write block, and the
`HordeContain` formation block appears below - slot count, `InitialPayload` per unit, the banner
carrier's two lines and the numbered `RankInfo` ranks, ready to paste into the object. Paste a
block into the same pane and press Read block to see the formation it describes, unit names and
all.

The grid is the game's own frame seen from above: one cell to a world unit, the top row the front
of the horde and the marked column its centre line, so what the window draws is what marches.
Each kind of soldier carries the diameter its object's geometry has, and is drawn at that size -
the only way to see, while placing them, whether two soldiers would stand inside one another. The
ini says nothing about geometry, so the diameters ride along in the block's `SIZES_COMMENT` line.

Nothing about *how* a block is written lives here: that is the Qt-free
`sage_mods.edain.horde_maker`, which this window only drives."""

from collections.abc import Iterable, Sequence

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from sage_mods.edain.horde_maker import Slot, parse_formation, parse_sizes, render_formation
from sage_mods.edain.horde_maker.ui import __version__
from sage_utils.styles import DARK, LIGHT
from sage_utils.widgets import (
    CopyableLabel as QLabel,
)
from sage_utils.widgets import (
    ThemeToggle,
    add_help_menu,
    card,
    saved_dark_theme,
    theme_notifier,
)

APP_NAME = "sage_edain_horde_maker"
APP_TITLE = "Edain Horde Maker"

# The soldier kinds a formation can mix, each with the colour it is drawn in and the object name
# it starts out as. The banner carrier is one of them so the grid handles a single kind of thing;
# what makes it different - one per horde, placed on its own line - is `_BANNER`.
_BANNER = "Banner carrier"
_UNIT_TYPES: dict[str, tuple[str, str]] = {
    "Unit A": ("#d0564f", "UnitTypeA"),
    "Unit B": ("#5aa85a", "UnitTypeB"),
    "Unit C": ("#5a86d0", "UnitTypeC"),
    "Unit D": ("#d0913f", "UnitTypeD"),
    "Unit E": ("#a06fd0", "UnitTypeE"),
    "Unit F": ("#4fbfc4", "UnitTypeF"),
    _BANNER: ("#d8a657", "BannerCarrier"),
}

# How wide a soldier is taken to be until told otherwise, in world units: a middling infantry
# geometry, so the dots start out at a size worth comparing against.
_DEFAULT_DIAMETER = 8.0

# The grid, in world units - one cell to a unit, at a few pixels each, so a formation spaced the
# way a real horde is (soldiers a body's width apart) fits on screen at its true proportions.
# Odd column count so the centre line falls on a column rather than between two.
_COLUMNS = 181
_ROWS = 111
_CENTRE_COLUMN = _COLUMNS // 2
_CELL = 4  # pixels to a world unit
_GRID_STEP = 5  # a grid line every this many units; every cell would be a solid wash
_MARGIN = 16  # px of room around the grid, so a dot on its edge is not clipped

_GETTING_STARTED_HTML = """
<h2>Getting started with Edain Horde Maker</h2>
<p>This window lays out the formation of a horde - the block of <code>RankInfo</code> lines a
<code>HordeContain</code> carries - by drawing it rather than counting coordinates out by
hand.</p>

<h3>1. Name and size the units</h3>
<p>Each colour is one object the horde is made of. Type its object name next to the colour, and
its width in world units in the <b>Ø</b> field beside it - the diameter of the object's geometry,
so twice a <code>GeometryMajorRadius</code>. The dots are drawn at that size, which is what shows
whether two soldiers would end up standing inside one another.</p>

<h3>2. Place the soldiers</h3>
<p><b>Left click</b> on the grid places the selected kind, <b>right click</b> removes the soldier
under the cursor (hold it down to sweep several away). The <b>top row is the front</b> of the
formation and the marked column is its centre line - the horde marches towards the top of the
grid. Only one <b>banner carrier</b> exists per horde, so placing it again moves it.</p>

<h3>3. Write the block</h3>
<p><b>Write block</b> fills the pane below with the finished block: the slot count, an
<code>InitialPayload</code> per unit, the banner carrier's <code>BannerCarriersAllowed</code> /
<code>BannerCarrierPosition</code> pair, and one <code>RankInfo</code> per row, numbered front to
back. <b>Copy</b> puts it on the clipboard.</p>
<p>Ranks are tied together for you: each soldier takes the one standing at its own index in the
rank ahead as its <code>Leader</code>, which is what keeps a marching horde in shape.</p>

<h3>Reading an existing horde</h3>
<p>Paste a horde's block - or its whole <code>HordeContain</code>, the rest is ignored - into the
pane and press <b>Read block</b>. Its positions are drawn on the grid and its unit names fill the
fields, so an existing formation can be looked at and adjusted.</p>
<p>A block written here opens with a <code>; HordeMaker DotSizes</code> comment recording the
diameter each placed unit was drawn at, since the ini itself says nothing about geometry.
Reading such a block restores those sizes. It is a comment: the game never sees it, and a block
from anywhere else is read just the same.</p>

<h3>The coordinates</h3>
<p>Positions are the game's: <b>X is depth</b>, growing towards the front, and <b>Y is
lateral</b>, growing to the left of the centre line. A written block puts the back rank at
<code>X:0.0</code> and centres the formation on <code>Y:0.0</code>.</p>
"""


class FormationGrid(QWidget):
    """The formation seen from above: a grid of world-unit cells, each either empty or holding one
    soldier of a named kind, drawn at the diameter `diameter(kind)` reports. It knows nothing
    about object names or ini text - it maps cells to the game's coordinates and back, and leaves
    the rest to the window."""

    changed = pyqtSignal()

    def __init__(self, diameter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cells: dict[tuple[int, int], str] = {}
        self._diameter = diameter
        self.selected = next(iter(_UNIT_TYPES))
        self.setFixedSize(_COLUMNS * _CELL + 2 * _MARGIN, _ROWS * _CELL + 2 * _MARGIN)
        self.setCursor(Qt.CursorShape.CrossCursor)
        # The grid paints itself rather than through the stylesheet, so the theme swap cannot
        # repaint it on its own; follow the shared notifier instead.
        self._dark = saved_dark_theme()
        theme_notifier.changed.connect(self._on_theme)

    def count(self) -> int:
        return len(self._cells)

    def kinds(self) -> set[str]:
        """Which kinds of soldier are actually on the grid."""
        return set(self._cells.values())

    def clear(self) -> None:
        self._cells.clear()
        self.update()
        self.changed.emit()

    def slots(self, names: dict[str, str]) -> list[Slot]:
        """The placed soldiers as game-space slots, `names` giving each kind its object name.
        The back rank sits at X = 0 and the formation is centred on Y = 0, so where it was drawn
        on the grid does not leak into the block."""
        if not self._cells:
            return []
        back = max(row for _, row in self._cells)
        columns = [column for column, _ in self._cells]
        centre = (min(columns) + max(columns)) / 2
        return [
            Slot(
                unit=names[kind],
                x=float(back - row),
                y=centre - column,
                banner=kind == _BANNER,
            )
            # Front rank first, left to right, so the block's payload and ranks follow the eye.
            for (column, row), kind in sorted(
                self._cells.items(), key=lambda item: (item[0][1], item[0][0])
            )
        ]

    def place(self, entries: Iterable[tuple[str, float, float]]) -> int:
        """Draw `(kind, x, y)` soldiers on the grid, Y = 0 on the centre column and the front rank
        far enough down that its dots are not clipped, replacing whatever was there. Returns how
        many fell outside the grid and were dropped - a formation wider or deeper than the grid,
        which the window reports."""
        entries = list(entries)
        self._cells.clear()
        dropped = 0
        front = max((x for _, x, _ in entries), default=0.0)
        inset = round(max((self._diameter(kind) for kind, _, _ in entries), default=0.0) / 2)
        for kind, x, y in entries:
            cell = (_CENTRE_COLUMN - round(y), round(front - x) + inset)
            if 0 <= cell[0] < _COLUMNS and 0 <= cell[1] < _ROWS:
                self._cells[cell] = kind
            else:
                dropped += 1
        self.update()
        self.changed.emit()
        return dropped

    def mousePressEvent(self, event) -> None:
        self._apply(event)

    def mouseMoveEvent(self, event) -> None:
        # Only the eraser sweeps: soldiers are wider than a cell, so a left-button drag would
        # bury a whole rank's worth of dots inside one another.
        if event.buttons() & Qt.MouseButton.RightButton:
            self._apply(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = DARK if self._dark else LIGHT
        painter.fillRect(self.rect(), QColor(palette["surface"]))

        painter.setPen(QPen(QColor(palette["border"]), 1))
        for column in range(0, _COLUMNS + 1, _GRID_STEP):
            painter.drawLine(*self._at(column, 0), *self._at(column, _ROWS))
        for row in range(0, _ROWS + 1, _GRID_STEP):
            painter.drawLine(*self._at(0, row), *self._at(_COLUMNS, row))

        # The centre line (Y = 0) the block's positions are measured from.
        painter.setPen(QPen(QColor(palette["accent"]), 1, Qt.PenStyle.DashLine))
        painter.drawLine(*self._at(_CENTRE_COLUMN, 0), *self._at(_CENTRE_COLUMN, _ROWS))

        for (column, row), kind in self._cells.items():
            colour = QColor(_UNIT_TYPES[kind][0])
            radius = self._radius(kind)
            centre_x, centre_y = self._at(column, row)
            painter.setPen(QPen(colour.darker(140), 2))
            painter.setBrush(colour)
            painter.drawEllipse(
                QRectF(centre_x - radius, centre_y - radius, radius * 2, radius * 2)
            )

    def _at(self, column: int, row: int) -> tuple[int, int]:
        """Where a cell's centre sits on the widget, in pixels."""
        return (_MARGIN + column * _CELL, _MARGIN + row * _CELL)

    def _radius(self, kind: str) -> float:
        """Half a soldier's diameter in pixels, never so small the dot cannot be seen or hit."""
        return max(2.0, self._diameter(kind) * _CELL / 2)

    def _apply(self, event) -> None:
        """Place or remove a soldier under the cursor, by which button the event carries."""
        position = event.position()
        buttons = event.buttons() | event.button()
        if buttons & Qt.MouseButton.RightButton:
            under = self._under(position.x(), position.y())
            if under is None or self._cells.pop(under, None) is None:
                return
        elif buttons & Qt.MouseButton.LeftButton:
            cell = (
                round((position.x() - _MARGIN) / _CELL),
                round((position.y() - _MARGIN) / _CELL),
            )
            if not (0 <= cell[0] < _COLUMNS and 0 <= cell[1] < _ROWS):
                return
            if self._cells.get(cell) == self.selected:
                return
            if self.selected == _BANNER:
                # One banner carrier to a horde, so placing it again moves it.
                self._cells = {at: kind for at, kind in self._cells.items() if kind != _BANNER}
            self._cells[cell] = self.selected
        else:
            return
        self.update()
        self.changed.emit()

    def _under(self, x: float, y: float) -> tuple[int, int] | None:
        """The cell whose drawn soldier covers `(x, y)`, nearest centre first - a soldier is
        wider than a cell, so what is under the cursor is not the cell the cursor is in."""
        hits = []
        for cell, kind in self._cells.items():
            centre_x, centre_y = self._at(*cell)
            distance = ((x - centre_x) ** 2 + (y - centre_y) ** 2) ** 0.5
            if distance <= self._radius(kind):
                hits.append((distance, cell))
        return min(hits)[1] if hits else None

    def _on_theme(self, dark: bool) -> None:
        self._dark = dark
        self.update()


class HordeMakerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.resize(1000, 940)
        self._build_menu()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel(f"{APP_TITLE}  v{__version__}")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(ThemeToggle())
        root.addLayout(header)

        self.grid = FormationGrid(self._diameter)
        self.grid.changed.connect(self._on_grid_changed)
        root.addWidget(self._units_card())
        root.addWidget(self._grid_card())
        root.addWidget(self._block_card(), 1)

        self.status = QLabel("Place the soldiers, then press Write block.")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

    def _build_menu(self) -> None:
        add_help_menu(
            self,
            guide_title="Getting started with Edain Horde Maker",
            guide_html=_GETTING_STARTED_HTML,
            about_title="About Edain Horde Maker",
            about_html=(
                f"<b>{APP_TITLE}</b> v{__version__}"
                "<p>Draws a horde's formation - the <code>RankInfo</code> block of a "
                "<code>HordeContain</code> - on a grid, at the size the units really are, and "
                "reads an existing block back onto it.</p>"
            ),
        )

    def _units_card(self) -> QWidget:
        frame, layout = card("Units")
        self._names: dict[str, QLineEdit] = {}
        self._sizes: dict[str, QLineEdit] = {}
        group = QButtonGroup(self)  # one selected kind across the rows, whatever their parents
        rows = QGridLayout()
        rows.setHorizontalSpacing(20)
        rows.setVerticalSpacing(6)
        # Two columns of rows, so seven kinds do not push the grid off the bottom of the window.
        per_column = (len(_UNIT_TYPES) + 1) // 2
        for index, kind in enumerate(_UNIT_TYPES):
            rows.addLayout(self._unit_row(kind, group), index % per_column, index // per_column)
        rows.setColumnStretch(0, 1)
        rows.setColumnStretch(1, 1)
        layout.addLayout(rows)
        return frame

    def _unit_row(self, kind: str, group: QButtonGroup) -> QHBoxLayout:
        """One kind of soldier: its colour, the radio button that selects it, the object name it
        stands for and the diameter it is drawn at."""
        colour, default = _UNIT_TYPES[kind]
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_swatch(colour))
        button = QRadioButton(kind)
        button.setChecked(kind == self.grid.selected)
        button.toggled.connect(lambda checked, k=kind: self._select(k, checked))
        button.setMinimumWidth(110)
        group.addButton(button)
        row.addWidget(button)
        name = QLineEdit(default)
        name.setPlaceholderText("The object name this colour stands for")
        row.addWidget(name, 1)
        self._names[kind] = name
        size = QLineEdit(f"{_DEFAULT_DIAMETER:.1f}")
        size.setToolTip(
            "How wide this unit is, in world units - the diameter of its geometry, so twice a "
            "GeometryMajorRadius. The dots are drawn at this size."
        )
        size.setFixedWidth(60)
        size.textChanged.connect(self.grid.update)
        diameter = QLabel("Ø")
        diameter.setToolTip(size.toolTip())
        row.addWidget(diameter)
        row.addWidget(size)
        self._sizes[kind] = size
        return row

    def _grid_card(self) -> QWidget:
        frame, layout = card("Formation")
        hint = QLabel(
            "Left click places the selected unit, right click removes it. The top row is the "
            "front of the horde, the dashed line its centre; one cell is one world unit."
        )
        hint.setObjectName("muted")
        layout.addWidget(hint)
        centred = QHBoxLayout()
        centred.addStretch(1)
        centred.addWidget(self.grid)
        centred.addStretch(1)
        layout.addLayout(centred)
        return frame

    def _block_card(self) -> QWidget:
        frame, layout = card("Horde block")
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, tooltip, slot in (
            ("Clear", "Remove every soldier from the grid.", self.grid.clear),
            (
                "Read block",
                "Draw the formation the block below describes, unit names and sizes and all.",
                self._read,
            ),
            ("Copy", "Copy the block below to the clipboard.", self._copy),
        ):
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        write = QPushButton("Write block")
        write.setObjectName("primary")
        write.setToolTip("Write the grid out as a HordeContain formation block.")
        write.clicked.connect(self._write)
        buttons.addWidget(write)
        layout.addLayout(buttons)

        self.block = QPlainTextEdit()
        self.block.setFont(QFont("Consolas", 10))
        self.block.setPlaceholderText(
            "The formation block appears here once you press Write block - or paste one in and "
            "press Read block."
        )
        layout.addWidget(self.block, 1)
        return frame

    def _select(self, kind: str, checked: bool) -> None:
        if checked:
            self.grid.selected = kind

    def _write(self) -> None:
        slots = self.grid.slots({kind: self._unit_name(kind) for kind in _UNIT_TYPES})
        if not slots:
            self.status.setText("Nothing to write - place some soldiers on the grid first.")
            return
        # Only the units actually in the horde: a comment naming units the block does not place
        # would be noise in the object's ini.
        sizes = {self._unit_name(kind): self._diameter(kind) for kind in self.grid.kinds()}
        block = render_formation(slots, sizes)
        self.block.setPlainText(block)
        self.status.setText(f"{_soldiers(len(slots))} written as {_ranks(block)}.")

    def _read(self) -> None:
        text = self.block.toPlainText()
        slots = parse_formation(text)
        if not slots:
            self.status.setText(
                "No RankInfo or BannerCarrierPosition line in there - paste a horde's block first."
            )
            return
        kinds = self._assign_kinds(slots)
        sizes = parse_sizes(text)
        for unit, kind in kinds.items():
            if unit in sizes:
                self._sizes[kind].setText(f"{sizes[unit]:.1f}")
        dropped = self.grid.place(
            (kinds[slot.unit], slot.x, slot.y) for slot in slots if slot.unit in kinds
        )
        told = [f"Read {_soldiers(len(slots))}."]
        if dropped:
            told.append(f"{dropped} fell outside the grid and were dropped.")
        unnamed = len({slot.unit for slot in slots}) - len(kinds)
        if unnamed:
            told.append(f"{unnamed} unit(s) beyond the {len(_UNIT_TYPES)} colours were left out.")
        self.status.setText(" ".join(told))

    def _assign_kinds(self, slots: Sequence[Slot]) -> dict[str, str]:
        """One colour per object name the block places, the banner carrier taking the banner
        colour, and each name written into its field. A block naming more units than there are
        colours leaves the extras unassigned; `_read` reports them."""
        kinds: dict[str, str] = {}
        free = [kind for kind in _UNIT_TYPES if kind != _BANNER]
        for slot in slots:
            if slot.unit in kinds:
                continue
            if slot.banner:
                kinds[slot.unit] = _BANNER
            elif free:
                kinds[slot.unit] = free.pop(0)
            else:
                continue
            self._names[kinds[slot.unit]].setText(slot.unit)
        return kinds

    def _copy(self) -> None:
        text = self.block.toPlainText()
        if not text.strip():
            self.status.setText("Nothing to copy yet - press Write block first.")
            return
        QApplication.clipboard().setText(text)
        self.status.setText("Block copied.")

    def _unit_name(self, kind: str) -> str:
        """The object name typed for `kind`, falling back to its default so a block is never
        written with an empty `UnitType:`."""
        return self._names[kind].text().strip() or _UNIT_TYPES[kind][1]

    def _diameter(self, kind: str) -> float:
        """The width typed for `kind`, in world units. A field being edited passes through states
        that are not a number ("", "-", "8."), so anything unreadable keeps the default rather
        than interrupting the typing."""
        try:
            return float(self._sizes[kind].text())
        except ValueError:
            return _DEFAULT_DIAMETER

    def _on_grid_changed(self) -> None:
        self.status.setText(f"{_soldiers(self.grid.count())} on the grid.")


def _swatch(colour: str) -> QLabel:
    """The colour chip that tells a row's radio button and object name apart from the next."""
    chip = QLabel()
    chip.setFixedSize(14, 14)
    chip.setStyleSheet(f"background: {colour}; border-radius: 7px;")
    return chip


def _soldiers(count: int) -> str:
    return "1 soldier" if count == 1 else f"{count} soldiers"


def _ranks(block: str) -> str:
    count = sum(1 for line in block.splitlines() if line.startswith("RankInfo"))
    return "1 rank" if count == 1 else f"{count} ranks"
