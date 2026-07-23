"""A shared results surface for the SAGE lint front ends: a searchable, sortable table of
diagnostics with severity colouring, double-click-to-open, and CSV export. Both SAGE Lint and
the Edain Linter's two tabs embed a `FindingsView` rather than hand-rolling the same table,
so a diagnostic reads and behaves the same wherever it is shown.

A diagnostic is the CLI's JSON dict (`severity`, `code`, `file`, `message`, `line_start`, …);
the columns to show, which one holds a path, and which stretch/are numeric are passed in."""

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_utils.widgets import CopyableLabel as QLabel
from sage_utils.widgets import saved_dark_theme, theme_notifier

# Severity text colour, per theme: the dark reds/ambers wash out on a white surface, so the
# light theme gets its own darker, more saturated set (matching the palette in styles.py).
SEVERITY_COLORS = {
    True: {  # dark
        "error": QColor("#e06c75"),
        "warning": QColor("#d8a657"),
        "info": QColor("#5fa8d3"),
    },
    False: {  # light
        "error": QColor("#c0392b"),
        "warning": QColor("#b07a1f"),
        "info": QColor("#2f6f9f"),
    },
}
SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def severity_color(severity: str, dark: bool | None = None) -> QColor | None:
    """The text colour for a severity in the current (or given) theme, or None if unknown."""
    if dark is None:
        dark = saved_dark_theme()
    return SEVERITY_COLORS[bool(dark)].get(severity)


class _SeverityItem(QTableWidgetItem):
    """A severity cell that sorts by severity rank (error < warning < info) rather than
    alphabetically, so a severity sort surfaces the errors first."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        return SEVERITY_RANK.get(self.text(), 9) < SEVERITY_RANK.get(other.text(), 9)


class FindingsView(QWidget):
    """A search + Export CSV toolbar over a sortable, severity-coloured diagnostics table.

    `columns` is an ordered `(heading, diagnostic-key)` list the table, the search and the
    export all read. `stretch_col` takes the horizontal slack (usually the message); `path_col`,
    if given, is the column whose cell holds a file/map path - double-clicking a row opens it
    (falling back to its folder when the file itself has no handler). `numeric_keys` are keys
    rendered as sortable numbers rather than text (e.g. a line number). `widths` presets a few
    column widths. Emits `status` with any message the host should show on its status line."""

    status = pyqtSignal(str)

    def __init__(
        self,
        columns: Sequence[tuple[str, str]],
        *,
        stretch_col: int,
        path_col: int | None = None,
        numeric_keys: Iterable[str] = (),
        widths: dict[int, int] | None = None,
        search_placeholder: str = "Filter the results…",
    ) -> None:
        super().__init__()
        self._columns = tuple(columns)
        self._path_col = path_col
        self._numeric_keys = frozenset(numeric_keys)
        self._diagnostics: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self._build_toolbar(search_placeholder))
        root.addWidget(self._build_table(stretch_col, widths or {}), 1)

        # The severity text colours are set in code, not by the stylesheet, so a theme flip
        # can't repaint them - recolour the visible rows ourselves when the theme changes.
        theme_notifier.changed.connect(self._recolor)

    def _build_toolbar(self, placeholder: str) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(QLabel("Search:"))
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText(placeholder)
        self.search_field.setToolTip("Show only rows containing this text (any column).")
        self.search_field.textChanged.connect(self._apply_filter)
        row.addWidget(self.search_field, 1)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.setToolTip(
            "Save the rows shown below (after search and sorting) to a CSV file."
        )
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        return wrap

    def _build_table(self, stretch_col: int, widths: dict[int, int]) -> QWidget:
        self.table = QTableWidget(0, len(self._columns))
        self.table.setHorizontalHeaderLabels([heading for heading, _ in self._columns])
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(self._open_item)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
        for col, width in widths.items():
            self.table.setColumnWidth(col, width)
        return self.table

    def set_diagnostics(self, diagnostics: list[dict]) -> None:
        """Show `diagnostics` in the table (replacing what was there) and re-apply the search."""
        self._diagnostics = diagnostics
        dark = saved_dark_theme()
        self.table.setSortingEnabled(False)  # bulk insert, then re-enable to sort
        self.table.setRowCount(len(diagnostics))
        for row, diag in enumerate(diagnostics):
            severity = diag.get("severity", "info")
            colour = severity_color(severity, dark)
            for col, (_, key) in enumerate(self._columns):
                if key == "severity":
                    item = _SeverityItem(severity)
                elif key in self._numeric_keys:
                    item = QTableWidgetItem()
                    item.setData(Qt.ItemDataRole.DisplayRole, diag.get(key) or 0)
                else:
                    item = QTableWidgetItem(str(diag.get(key, "")))
                # Remember the severity on the item so a theme flip can recolour it (row order
                # shifts under sorting, so we can't map back to `diagnostics` by index later).
                item.setData(Qt.ItemDataRole.UserRole, severity)
                if colour is not None:
                    item.setForeground(colour)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self._apply_filter(self.search_field.text())

    def _recolor(self, dark: bool) -> None:
        """Repaint every cell's severity text colour for the new theme (see the connection in
        `__init__`); the app stylesheet swap can't touch colours set in code."""
        for row in range(self.table.rowCount()):
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                colour = severity_color(item.data(Qt.ItemDataRole.UserRole), dark)
                if colour is not None:
                    item.setForeground(colour)

    def clear(self) -> None:
        self.set_diagnostics([])

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self.table.rowCount()):
            if not needle:
                self.table.setRowHidden(row, False)
                continue
            hay = " ".join(
                (self.table.item(row, col).text() if self.table.item(row, col) else "")
                for col in range(self.table.columnCount())
            ).casefold()
            self.table.setRowHidden(row, needle not in hay)

    def _open_item(self, item: QTableWidgetItem) -> None:
        """Open the double-clicked row's path (its `path_col` cell) with whatever the OS
        associates with it - an editor for an .ini, Worldbuilder for a .map - falling back to
        the containing folder when the file itself has no handler."""
        if self._path_col is None:
            return
        cell = self.table.item(item.row(), self._path_col)
        path = Path(cell.text()) if cell else Path()
        if not cell or not path.exists():
            self.status.emit(f"File not found: {path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _export(self) -> None:
        if not self._diagnostics:
            self.status.emit("Nothing to export yet - run a check first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "", "CSV file (*.csv)")
        if not path:
            return
        # Export the rows currently shown (after the search filter), in the table's sort order.
        rows = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow([heading for heading, _ in self._columns])
                for row in rows:
                    writer.writerow(
                        self.table.item(row, col).text() if self.table.item(row, col) else ""
                        for col in range(self.table.columnCount())
                    )
        except OSError as exc:
            self.status.emit(f"Could not save the file: {exc}")
            return
        self.status.emit(f"Exported {len(rows)} row(s) to {path}.")
