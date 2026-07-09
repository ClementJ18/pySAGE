"""The SAGE Lint window: point it at a mod folder, set a few options, press Check, and
browse the errors and warnings in a searchable, sortable table. Built on the shared
sage_utils widgets (cards, the background Worker, the theme toggle) so it looks and behaves
like the other SAGE front ends. The lint itself runs the CLI in-process on a worker thread
(see `runner`), inheriting all of its config/baseline/sorting behaviour."""

import csv
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_lint.plugins.ui import __version__
from sage_lint.plugins.ui.runner import (
    LEVELS,
    app_dir,
    build_argv,
    build_format_argv,
    config_bases,
    effective_lint_root,
    find_baselines,
    has_project_config,
    merge_baselines,
    project_config,
    run_cli,
)
from sage_utils.widgets import (
    CopyableLabel as QLabel,
)
from sage_utils.widgets import (
    ThemeToggle,
    card,
    resource_path,
    run_worker,
)

APP_NAME = "sage_lint"
APP_TITLE = "SAGE Lint"
# Icon art by Ludovic Bourgeois-Lefèvre:
# https://ludovicbourgeoislefevre.artstation.com/projects/2xL1WJ
ICON_FILE = "icon.ico"

# The report columns: (heading, diagnostic key). The table, the search and the CSV export
# all read this one list.
_COLUMNS = (
    ("Severity", "severity"),
    ("Code", "code"),
    ("File", "file"),
    ("Line", "line_start"),
    ("Message", "message"),
)

# Severity text colour, chosen to read on both the dark and the light theme.
_SEVERITY_COLOR = {
    "error": QColor("#e06c75"),
    "warning": QColor("#d8a657"),
    "info": QColor("#5fa8d3"),
}
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


class _SeverityItem(QTableWidgetItem):
    """A severity cell that sorts by severity rank (error < warning < info) rather than
    alphabetically, so a severity sort surfaces the errors first."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        return _SEVERITY_RANK.get(self.text(), 9) < _SEVERITY_RANK.get(other.text(), 9)


class LintWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        self.resize(1180, 760)
        self._diagnostics: list[dict] = []
        self._workers = set()
        # Baselines found under the mod, merged on Check unless the user overrides the field.
        self._auto_baselines: list = []
        self._baseline_root = None
        self._baseline_is_auto = False

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

        root.addWidget(self._build_options_card())
        root.addWidget(self._build_results_toolbar())
        root.addWidget(self._build_table(), 1)

        self.status = QLabel("Pick a mod folder, then press Check.")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

        self._autoload_startup_config()

    def _autoload_startup_config(self) -> None:
        """If a `.sagelint` (or `.sagelint.local`) sits beside the app, pre-select that folder
        and load its config on launch - so a teammate who drops the exe into their mod folder
        just presses Check."""
        folder = app_dir()
        if has_project_config(folder):
            self.folder_field.setText(str(folder))
            self._load_project_config()

    def _build_options_card(self) -> QWidget:
        frame, layout = card("What to check")

        self.folder_field = self._path_row(
            layout, "Mod folder", "Folder of ini files to check", self._pick_folder
        )
        self.folder_field.editingFinished.connect(self._load_project_config)
        self.base_field = self._path_row(
            layout, "Base game (optional)", "Unmodified base-game folder", self._pick_base
        )
        self.baseline_field = self._path_row(
            layout,
            "Baseline (optional)",
            "Baseline file of accepted diagnostics",
            self._pick_baseline,
        )
        # Typing in the baseline field (textEdited fires on user input, not setText) means the
        # user is choosing their own, so stop auto-merging the found baselines.
        self.baseline_field.textEdited.connect(lambda: setattr(self, "_baseline_is_auto", False))

        options = QHBoxLayout()
        options.setSpacing(10)
        options.addWidget(QLabel("Show:"))
        self.level_box = QComboBox()
        self.level_box.addItems(LEVELS)
        self.level_box.setCurrentText("WARNING")
        options.addWidget(self.level_box)
        self.suggest_check = QCheckBox("Suggest fixes for typos")
        options.addWidget(self.suggest_check)
        self.fix_check = QCheckBox("Auto-fix safe issues (rewrites files)")
        options.addWidget(self.fix_check)
        options.addStretch(1)
        self.format_button = QPushButton("Format")
        self.format_button.setToolTip(
            "Reformat the mod's ini files to the canonical style (aligns '=' when the "
            "project's .sagelint sets align_equals). Rewrites files on disk."
        )
        self.format_button.clicked.connect(self._format)
        options.addWidget(self.format_button)
        self.check_button = QPushButton("Check")
        self.check_button.setObjectName("primary")
        self.check_button.clicked.connect(self._run)
        options.addWidget(self.check_button)
        layout.addLayout(options)
        return frame

    def _path_row(self, layout, label: str, placeholder: str, on_browse) -> QLineEdit:
        """A labelled path field with a Browse button, appended to `layout`. Returns the field."""
        row = QHBoxLayout()
        caption = QLabel(label)
        caption.setMinimumWidth(150)
        row.addWidget(caption)
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        row.addWidget(field, 1)
        button = QPushButton("Browse…")
        button.clicked.connect(on_browse)
        row.addWidget(button)
        layout.addLayout(row)
        return field

    def _build_results_toolbar(self) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(QLabel("Search:"))
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Filter the results…")
        self.search_field.textChanged.connect(self._apply_filter)
        row.addWidget(self.search_field, 1)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        return wrap

    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([heading for heading, _ in _COLUMNS])
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(self._open_item)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # Message takes the slack
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 320)
        self.table.setColumnWidth(3, 60)
        return self.table

    def _pick_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose the mod folder to check")
        if chosen:
            self.folder_field.setText(chosen)
            self._load_project_config()

    def _pick_base(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose the unmodified base-game folder")
        if chosen:
            self.base_field.setText(chosen)

    def _pick_baseline(self) -> None:
        start = self.folder_field.text().strip()
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choose a baseline file", start, "Baseline file (*.baseline);;All files (*)"
        )
        if chosen:
            self.baseline_field.setText(chosen)
            self._baseline_is_auto = False  # an explicit pick overrides the auto-merge

    def _load_project_config(self) -> None:
        """Reflect the folder's `.sagelint` (+ `.sagelint.local`) in the options, so the
        project's own settings are in force without the user setting them. The other config
        keys (ignore/select/exclude/baseline/base) are applied by the CLI itself at Check time."""
        try:
            config = project_config(self.folder_field.text().strip())
        except Exception as exc:  # noqa: BLE001 - surface, never crash, on a bad config
            self.status.setText(f"Could not read .sagelint: {type(exc).__name__}: {exc}")
            return
        if config is None:
            return
        folder = self.folder_field.text().strip()
        self.level_box.setCurrentText(config.level or "WARNING")
        self.suggest_check.setChecked(config.suggest)
        # Reflect the config's base game(s) so they are visible and used. Only overwrite when
        # the config provides one, so a value the user typed for a config-less folder is not
        # wiped on a focus-out reload.
        bases = config_bases(config, folder)
        if bases:
            self.base_field.setText("; ".join(bases))
        self._discover_baselines(config, folder)
        has_config = has_project_config(folder)
        if config.warnings:
            self.status.setText(
                f"Loaded .sagelint with {len(config.warnings)} warning(s): {config.warnings[0]}"
            )
        elif has_config:
            self.status.setText("Loaded .sagelint. Press Check.")
        else:
            self.status.setText("No .sagelint here; using defaults. Press Check.")

    def _discover_baselines(self, config, folder: str) -> None:
        """Find every baseline anywhere under the lint root and remember them to merge on Check.
        Unless the user has already typed their own, the field shows a summary of what was found;
        the actual merge (re-rooting each to the lint root) happens at Check time so it reflects
        the files as they are then. Touches nothing when none are found, so a manual value
        survives a reload."""
        root = effective_lint_root(config, folder)
        self._baseline_root = root
        self._auto_baselines = find_baselines(root)
        if not self._auto_baselines:
            return
        names = ", ".join(p.parent.name or p.name for p in self._auto_baselines)
        self.baseline_field.setText(
            f"{len(self._auto_baselines)} baseline(s) found - merged on Check ({names})"
        )
        self._baseline_is_auto = True

    def _effective_baseline(self) -> str:
        """The baseline path to pass to the CLI: the merged temp file when auto-discovery is in
        effect, else whatever the user put in the field."""
        if self._baseline_is_auto and self._auto_baselines:
            return merge_baselines(self._auto_baselines, self._baseline_root)
        return self.baseline_field.text().strip()

    def _run(self) -> None:
        folder = self.folder_field.text().strip()
        if not folder or not Path(folder).is_dir():
            self.status.setText("Pick a valid mod folder first.")
            return
        argv = build_argv(
            folder,
            level=self.level_box.currentText(),
            base=self.base_field.text(),
            baseline=self._effective_baseline(),
            suggest=self.suggest_check.isChecked(),
            fix=self.fix_check.isChecked(),
        )
        self.check_button.setEnabled(False)
        self.status.setText("Checking… this can take a moment on a large mod.")
        run_worker(self, lambda: run_cli(argv), self._on_report, self._on_failed)

    def _format(self) -> None:
        """Reformat the mod's ini files to the canonical style. Formats the config's effective
        root and passes the project's align settings explicitly (the config may sit above that
        root, where `format`'s own lookup would miss it). Rewrites files, so it confirms first."""
        folder = self.folder_field.text().strip()
        if not folder or not Path(folder).is_dir():
            self.status.setText("Pick a valid mod folder first.")
            return
        config = project_config(folder)
        root = effective_lint_root(config, folder)
        if (
            QMessageBox.question(
                self,
                "Format files",
                f"Reformat the ini files under:\n{root}\n\nThis rewrites files on disk. Continue?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        argv = build_format_argv(
            str(root),
            align_equals=bool(config and config.align_equals),
            align_exclude=tuple(config.align_exclude) if config else (),
        )
        self.format_button.setEnabled(False)
        self.status.setText("Formatting…")
        run_worker(self, lambda: run_cli(argv), self._on_formatted, self._on_format_failed)

    def _on_formatted(self, report: dict) -> None:
        self.format_button.setEnabled(True)
        summary = report.get("summary", {})
        reformatted = summary.get("reformatted", 0)
        skipped = summary.get("skipped", 0)
        smells = summary.get("with_smells", 0)
        tail = f", {smells} with tab smells" if smells else ""
        self.status.setText(f"Reformatted {reformatted} file(s), {skipped} skipped{tail}.")

    def _on_format_failed(self, message: str) -> None:
        self.format_button.setEnabled(True)
        self.status.setText(f"Format failed - {message}")

    def _on_report(self, report: dict) -> None:
        self.check_button.setEnabled(True)
        self._diagnostics = report.get("diagnostics", [])
        self._populate()
        summary = report.get("summary", {})
        errors = summary.get("errors", 0)
        warnings = summary.get("warnings", 0)
        extra = []
        if summary.get("fixed"):
            extra.append(f"{summary['fixed']} auto-fixed")
        if summary.get("baselined"):
            extra.append(f"{summary['baselined']} baselined")
        if summary.get("hidden"):
            extra.append(f"{summary['hidden']} info hidden")
        tail = f" ({', '.join(extra)})" if extra else ""
        self.status.setText(f"{errors} error(s), {warnings} warning(s){tail}.")

    def _on_failed(self, message: str) -> None:
        self.check_button.setEnabled(True)
        self.status.setText(f"Check failed - {message}")

    def _populate(self) -> None:
        self.table.setSortingEnabled(False)  # bulk insert, then re-enable to sort
        self.table.setRowCount(len(self._diagnostics))
        for row, diag in enumerate(self._diagnostics):
            severity = diag.get("severity", "info")
            colour = _SEVERITY_COLOR.get(severity)
            for col, (_, key) in enumerate(_COLUMNS):
                if key == "severity":
                    item = _SeverityItem(severity)
                elif key == "line_start":
                    item = QTableWidgetItem()
                    item.setData(Qt.ItemDataRole.DisplayRole, diag.get("line_start") or 0)
                else:
                    item = QTableWidgetItem(str(diag.get(key, "")))
                if colour is not None:
                    item.setForeground(colour)
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self._apply_filter(self.search_field.text())

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
        """Open the double-clicked row's file in the OS default editor."""
        file_item = self.table.item(item.row(), 2)  # the File column
        path = file_item.text() if file_item else ""
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self.status.setText(f"File not found: {path}")

    def _export(self) -> None:
        if not self._diagnostics:
            self.status.setText("Nothing to export yet - run a check first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "", "CSV file (*.csv)")
        if not path:
            return
        # Export the rows currently shown (after the search filter), in the table's sort order.
        rows = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow([heading for heading, _ in _COLUMNS])
                for row in rows:
                    writer.writerow(
                        self.table.item(row, col).text() if self.table.item(row, col) else ""
                        for col in range(self.table.columnCount())
                    )
        except OSError as exc:
            self.status.setText(f"Could not save the file: {exc}")
            return
        self.status.setText(f"Exported {len(rows)} row(s) to {path}.")
