"""The Edain Linter window: one desktop app that runs both SAGE Lint's ini checks and the
Edain map checks over a single shared game-data panel. A "Mod (ini)" tab points at the mod
folder and reports the ini findings `sage-lint` would; a "Maps" tab takes map folders / `.map`
files (browse or drag-and-drop) and reports the findings `sage-edain lint-maps` would. Both
resolve references against the shared GAME DATA sources (base game first, then the mod), and
both show their results in the same searchable, sortable FindingsView the standalone SAGE Lint
window uses. A `.sagelint` beside the app (or in the mod folder) fills the sources and options
from the project's own config on launch. The checks run in-process on a worker thread - the
ini lint via the sage_lint CLI (see sage_lint's runner), the map checks via `runner.run_check`."""

from pathlib import Path

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# The `.sagelint` discovery + argv helpers are the SAGE Lint UI's own (Qt-free), so the Mod tab
# runs exactly what `sage-lint-ui` runs - beside-the-exe autoload included.
from sage_lint.plugins.ui.runner import (
    app_dir,
    build_argv,
    build_format_argv,
    effective_lint_root,
    find_baselines,
    has_project_config,
    merge_baselines,
    project_config,
    run_cli,
)
from sage_mods.edain.map_checks.ui import __version__
from sage_mods.edain.map_checks.ui.runner import (
    LEVELS,
    config_game_sources,
    run_check,
)
from sage_utils.findings import FindingsView
from sage_utils.sources import load_saved_sources, save_sources
from sage_utils.widgets import (
    CopyableLabel as QLabel,
)
from sage_utils.widgets import (
    SourcesPanel,
    ThemeToggle,
    card,
    resource_path,
    run_worker,
)

APP_NAME = "sage_edain_linter"
APP_TITLE = "Edain Linter"
# Icon art by Ludovic Bourgeois-Lefèvre:
# https://ludovicbourgeoislefevre.artstation.com/projects/2xL1WJ
ICON_FILE = "icon.ico"

# The report columns for each tab: (heading, diagnostic key). The ini findings carry a line
# number; the map findings do not.
_LINT_COLUMNS = (
    ("Severity", "severity"),
    ("Code", "code"),
    ("File", "file"),
    ("Line", "line_start"),
    ("Message", "message"),
)
_MAP_COLUMNS = (
    ("Severity", "severity"),
    ("Code", "code"),
    ("Map", "file"),
    ("Message", "message"),
)

# The Help ▸ Getting started walkthrough. Kept as one HTML block so QTextBrowser lays it out
# with headings and lists; the steps mirror the shared GAME DATA panel and the two tabs.
_GETTING_STARTED_HTML = """
<h2>Getting started with the Edain Linter</h2>
<p>The Edain Linter checks a mod two ways from one window: the <b>Mod (ini)</b> tab reads the
mod's <code>.ini</code> game data and reports problems - repeated fields, dangling references,
out-of-range values, and more - and the <b>Maps</b> tab checks <code>.map</code> files against
that game data. Follow these steps the first time you set it up.</p>

<h3>1. Add the game data (optional)</h3>
<p>Fill the <b>GAME DATA</b> list with the game's data - folders or <code>.big</code>
archives - so references resolve against it. Sources load top to bottom (later overrides
earlier); put the original game first, then the mod, and reorder with the ↑/↓ buttons. Both
tabs resolve against this one list, and it is remembered for the next launch.</p>

<h3>2. Check the mod's ini files</h3>
<p>On the <b>Mod (ini)</b> tab, press <b>Browse…</b> next to <b>Mod folder</b> and choose the
folder that holds the mod's <code>.ini</code> files, then press <b>Check</b>. Everything under
it is checked. If a <code>.sagelint</code> config sits in that folder it is loaded
automatically - rules, severity, game data, and more come from it.</p>

<h3>3. Check the maps</h3>
<p>On the <b>Maps</b> tab, add map folders or <code>.map</code> files - or drag and drop them
anywhere on the window - and press <b>Check</b>. Folders are searched for maps, subfolders
included, and placed objects resolve against the GAME DATA list.</p>

<h3>4. Choose what to show</h3>
<p>Each tab has a <b>Show</b> box for the lowest severity to list (ERROR, WARNING, or INFO).
On the ini tab, tick <b>Suggest fixes for typos</b> for "did you mean…" hints, and
<b>Auto-fix safe issues</b> only when you want the linter to rewrite files for you.</p>

<h3>5. Browse the results</h3>
<p>Results appear in the table below - sort by any column, use <b>Search</b> to filter, and
<b>double-click a row</b> to open that file. On a large mod the first check can take a
moment.</p>

<h3>6. Adopt on an existing mod (optional)</h3>
<p>To try the linter on a mod that already has many findings, set a <b>Baseline</b> file so
only new problems are reported. Baselines found under the mod are merged automatically.</p>

<h3>Other tools</h3>
<p><b>Format</b> reprints the ini files in the canonical style. <b>Export CSV…</b> saves the
rows currently shown so you can share them.</p>
"""


class EdainLinterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        self.resize(1180, 820)
        self.setAcceptDrops(True)  # drop map files/folders anywhere -> the Maps tab
        self._workers: set = set()
        self._help_dialog: QDialog | None = None
        # Baselines found under the mod, merged on Check unless the user overrides the field.
        self._auto_baselines: list = []
        self._baseline_root = None
        self._baseline_is_auto = False

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

        # One game-data panel shared by both tabs: the ini lint layers it as `--base`, the map
        # checks resolve placed objects against it. Order matters (base game first, then the mod).
        self.sources_panel = SourcesPanel(
            title="GAME DATA (OPTIONAL)",
            expanded_hint=(
                "GAME DATA (OPTIONAL) - folders / .big archives, loaded top to bottom "
                "(reorder with ↑/↓): the original game first, then the mod. Both tabs resolve "
                "references against these."
            ),
            list_max_height=96,
            show_load=False,
        )
        root.addWidget(self.sources_panel)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_lint_tab(), "Mod (ini)")
        self.tabs.addTab(self._build_maps_tab(), "Maps")
        root.addWidget(self.tabs, 1)

        self.status = QLabel("Add the game data, then check the mod or its maps.")
        self.status.setObjectName("muted")
        root.addWidget(self.status)
        for view in (self.lint_findings, self.map_findings):
            view.status.connect(self.status.setText)

        # Last session's game sources come back first; an added mod folder's `.sagelint` (or the
        # startup autoload just below) replaces them when it names its own.
        for kind, path in load_saved_sources(APP_NAME):
            self.sources_panel.add_source(kind, path)
        self._autoload_startup_config()

    def _autoload_startup_config(self) -> None:
        """If a `.sagelint` (or `.sagelint.local`) sits beside the app - beside the `.exe` when
        frozen - pre-select that folder as the mod to lint and load its config, so a teammate who
        drops the exe into the mod folder just presses Check."""
        folder = app_dir()
        if has_project_config(folder):
            self.folder_field.setText(str(folder))
            self._load_project_config()

    # ---------------------------------------------------------------- the Help menu

    def _build_menu(self) -> None:
        """A Help menu: a getting-started walkthrough for newcomers, and an About entry."""
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("&Getting started…", self._show_getting_started)
        help_menu.addSeparator()
        help_menu.addAction("&About Edain Linter", self._show_about)

    def _show_getting_started(self) -> None:
        """A scrollable, non-modal walkthrough of the basic steps to set up the Edain Linter.
        Held on the window so it keeps its scroll position between openings."""
        if getattr(self, "_help_dialog", None) is None:
            self._help_dialog = self._make_help_dialog()
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def _make_help_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("Getting started with the Edain Linter")
        dialog.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        dialog.resize(560, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(_GETTING_STARTED_HTML)
        layout.addWidget(browser, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.close)
        buttons.accepted.connect(dialog.close)
        layout.addWidget(buttons)
        return dialog

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Edain Linter",
            f"<b>{APP_TITLE}</b> v{__version__}"
            "<p>One window for checking an Edain mod: the Mod (ini) tab runs the "
            "<code>sage_lint</code> ini checks, the Maps tab runs the Edain map checks, "
            "and both resolve against the shared GAME DATA sources.</p>"
            "<p>Icon art by Ludovic Bourgeois-Lefèvre.</p>",
        )

    # ---------------------------------------------------------------- the Mod (ini) tab

    def _build_lint_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(14)

        options, options_layout = card("What to check")
        self.folder_field = self._path_row(
            options_layout,
            "Mod folder",
            "Folder of ini files to check",
            self._pick_folder,
            tooltip="The mod's folder of .ini files - the linter checks everything under it.",
        )
        self.folder_field.editingFinished.connect(self._load_project_config)
        self.baseline_field = self._path_row(
            options_layout,
            "Baseline (optional)",
            "Baseline file of accepted diagnostics",
            self._pick_baseline,
            tooltip="A baseline of already-accepted diagnostics; only new findings are reported.",
        )
        self.baseline_field.textEdited.connect(lambda: setattr(self, "_baseline_is_auto", False))

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Show:"))
        self.lint_level_box = QComboBox()
        self.lint_level_box.addItems(LEVELS)
        self.lint_level_box.setCurrentText("WARNING")
        self.lint_level_box.setToolTip(
            "The lowest severity to report. ERROR shows only errors; INFO shows everything."
        )
        row.addWidget(self.lint_level_box)
        self.suggest_check = QCheckBox("Suggest fixes for typos")
        self.suggest_check.setToolTip(
            "Add a 'did you mean…' suggestion to unknown-name diagnostics (nearest known name)."
        )
        row.addWidget(self.suggest_check)
        self.fix_check = QCheckBox("Auto-fix safe issues (rewrites files)")
        self.fix_check.setToolTip(
            "Apply the fixes the linter deems safe and rewrite the affected files on disk."
        )
        row.addWidget(self.fix_check)
        row.addStretch(1)
        self.format_button = QPushButton("Format")
        self.format_button.setToolTip(
            "Reformat the mod's ini files to the canonical style. Rewrites files on disk."
        )
        self.format_button.clicked.connect(self._format)
        row.addWidget(self.format_button)
        self.lint_check_button = QPushButton("Check")
        self.lint_check_button.setObjectName("primary")
        self.lint_check_button.setToolTip(
            "Run the linter over the mod folder and list every error and warning below."
        )
        self.lint_check_button.clicked.connect(self._run_lint)
        row.addWidget(self.lint_check_button)
        options_layout.addLayout(row)
        layout.addWidget(options)

        self.lint_findings = FindingsView(
            _LINT_COLUMNS,
            stretch_col=4,
            path_col=2,
            numeric_keys=("line_start",),
            widths={0: 90, 1: 170, 2: 320, 3: 60},
        )
        layout.addWidget(self.lint_findings, 1)
        return tab

    def _pick_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose the mod folder to check")
        if chosen:
            self.folder_field.setText(chosen)
            self._load_project_config()

    def _pick_baseline(self) -> None:
        start = self.folder_field.text().strip()
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choose a baseline file", start, "Baseline file (*.baseline);;All files (*)"
        )
        if chosen:
            self.baseline_field.setText(chosen)
            self._baseline_is_auto = False

    def _load_project_config(self) -> None:
        """Reflect the mod folder's `.sagelint` (+ `.sagelint.local`) in the shared sources and the
        ini options, so the project's own settings are in force without the user setting them."""
        folder = self.folder_field.text().strip()
        try:
            config = project_config(folder)
        except Exception as exc:  # noqa: BLE001 - surface, never crash, on a bad config
            self.status.setText(f"Could not read .sagelint: {type(exc).__name__}: {exc}")
            return
        if config is None:
            return
        self.lint_level_box.setCurrentText(config.level or "WARNING")
        self.map_level_box.setCurrentText(config.level or "WARNING")
        self.suggest_check.setChecked(config.suggest)
        # Fill the shared game data from the config (base + the map pass's extra maps_base). Only
        # when the config names one, so sources added for a config-less folder are not wiped.
        bases = config_game_sources(config, folder)
        if bases:
            self.sources_panel.clear()
            for kind, path in bases:
                self.sources_panel.add_source(kind, path)
        self._discover_baselines(config, folder)
        if config.warnings:
            self.status.setText(
                f"Loaded .sagelint with {len(config.warnings)} warning(s): {config.warnings[0]}"
            )
        elif has_project_config(folder):
            self.status.setText("Loaded .sagelint. Press Check.")
        else:
            self.status.setText("No .sagelint here; using defaults. Press Check.")

    def _discover_baselines(self, config, folder: str) -> None:
        """Find every baseline under the lint root and remember them to merge on Check. Unless the
        user typed their own, the field shows a summary; the merge happens at Check time."""
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
        if self._baseline_is_auto and self._auto_baselines:
            return merge_baselines(self._auto_baselines, self._baseline_root)
        return self.baseline_field.text().strip()

    def _run_lint(self) -> None:
        folder = self.folder_field.text().strip()
        if not folder or not Path(folder).is_dir():
            self.status.setText("Pick a valid mod folder first.")
            return
        sources = self.sources_panel.sources()
        save_sources(sources, APP_NAME)  # remember the game data for next launch
        argv = build_argv(
            folder,
            level=self.lint_level_box.currentText(),
            bases=[path for _, path in sources],
            baseline=self._effective_baseline(),
            suggest=self.suggest_check.isChecked(),
            fix=self.fix_check.isChecked(),
        )
        self.lint_check_button.setEnabled(False)
        self.status.setText("Checking… this can take a moment on a large mod.")
        run_worker(self, lambda: run_cli(argv), self._on_lint_report, self._on_lint_failed)

    def _format(self) -> None:
        """Reformat the mod's ini files to the canonical style, passing the project's align
        settings explicitly. Rewrites files, so it confirms first."""
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

    def _on_lint_report(self, report: dict) -> None:
        self.lint_check_button.setEnabled(True)
        self.lint_findings.set_diagnostics(report.get("diagnostics", []))
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

    def _on_lint_failed(self, message: str) -> None:
        self.lint_check_button.setEnabled(True)
        self.status.setText(f"Check failed - {message}")

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

    # ---------------------------------------------------------------- the Maps tab

    def _build_maps_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(14)

        maps_card, card_layout = card("Maps to check")
        hint = QLabel(
            "Folders are searched for .map files, subfolders included. You can also drag and "
            "drop maps or folders anywhere on this window. They resolve against GAME DATA above."
        )
        hint.setObjectName("muted")
        card_layout.addWidget(hint)
        self.maps_list = QListWidget()
        self.maps_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.maps_list.setMaximumHeight(120)
        card_layout.addWidget(self.maps_list)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, slot in (
            ("Add folder…", self._pick_maps_folder),
            ("Add map files…", self._pick_map_files),
            ("Remove selected", self._remove_selected_maps),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Show:"))
        self.map_level_box = QComboBox()
        self.map_level_box.addItems(LEVELS)
        self.map_level_box.setCurrentText("WARNING")
        row.addWidget(self.map_level_box)
        row.addStretch(1)
        self.map_check_button = QPushButton("Check")
        self.map_check_button.setObjectName("primary")
        self.map_check_button.clicked.connect(self._run_maps)
        row.addWidget(self.map_check_button)
        card_layout.addLayout(buttons)
        card_layout.addLayout(row)
        layout.addWidget(maps_card)

        self.map_findings = FindingsView(
            _MAP_COLUMNS,
            stretch_col=3,
            path_col=2,
            widths={0: 90, 1: 170, 2: 340},
        )
        layout.addWidget(self.map_findings, 1)
        return tab

    def _add_map_path(self, path: str) -> None:
        """Append `path` to the maps list unless it is already there (compared as paths)."""
        resolved = str(Path(path))
        existing = {self.maps_list.item(i).text() for i in range(self.maps_list.count())}
        if resolved not in existing:
            self.maps_list.addItem(resolved)

    def _map_paths(self) -> list[str]:
        return [self.maps_list.item(i).text() for i in range(self.maps_list.count())]

    def _remove_selected_maps(self) -> None:
        for item in self.maps_list.selectedItems():
            self.maps_list.takeItem(self.maps_list.row(item))

    def _pick_maps_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder to search for maps")
        if chosen:
            self._add_map_path(chosen)

    def _pick_map_files(self) -> None:
        chosen, _ = QFileDialog.getOpenFileNames(
            self, "Choose map files", "", "SAGE maps (*.map);;All files (*)"
        )
        for path in chosen:
            self._add_map_path(path)

    def _run_maps(self) -> None:
        targets = [p for p in self._map_paths() if Path(p).exists()]
        missing = [p for p in self._map_paths() if not Path(p).exists()]
        if not targets:
            self.status.setText(
                "Add a maps folder or some .map files first."
                if not missing
                else f"None of the listed paths exist anymore (e.g. {missing[0]})."
            )
            return
        sources = self.sources_panel.sources()
        save_sources(sources, APP_NAME)
        games = [path for _, path in sources]
        self.map_check_button.setEnabled(False)
        self.status.setText("Checking…")

        # The runner reports each stage through the worker's own signal - the thread-safe way to
        # reach the status line. The worker only exists after run_worker returns, so the callable
        # reads it from a holder filled just below (a stage finishing in that gap is unreported).
        holder: list = []

        def report_progress(text: str) -> None:
            if holder:
                holder[0].progress.emit(text)

        worker = run_worker(
            self,
            lambda: run_check(
                targets,
                games=games,
                level=self.map_level_box.currentText(),
                progress=report_progress,
            ),
            self._on_map_report,
            self._on_map_failed,
        )
        holder.append(worker)
        worker.progress.connect(self.status.setText)

    def _on_map_report(self, report: dict) -> None:
        self.map_check_button.setEnabled(True)
        self.map_findings.set_diagnostics(report.get("diagnostics", []))
        summary = report.get("summary", {})
        errors = summary.get("errors", 0)
        warnings = summary.get("warnings", 0)
        maps = report.get("maps", 0)
        tail = ""
        if summary.get("hidden"):
            tail = f" ({summary['hidden']} lower-severity finding(s) hidden; set Show to INFO)"
        map_word = "1 map" if maps == 1 else f"{maps} maps"
        self.status.setText(f"{errors} error(s), {warnings} warning(s) across {map_word}{tail}.")

    def _on_map_failed(self, message: str) -> None:
        self.map_check_button.setEnabled(True)
        self.status.setText(f"Check failed - {message}")

    # ---------------------------------------------------------------- drag-and-drop (-> Maps)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        added = ignored = 0
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir() or path.suffix.lower() == ".map":
                self._add_map_path(str(path))
                added += 1
            else:
                ignored += 1
        if added:
            self.tabs.setCurrentIndex(1)  # surface the Maps tab the drop landed in
            self.status.setText(f"Added {added} item(s) to check. Press Check when ready.")
        elif ignored:
            self.status.setText("Only folders and .map files can be dropped here.")

    # ---------------------------------------------------------------- shared helpers

    def _path_row(
        self, layout, label: str, placeholder: str, on_browse, tooltip: str = ""
    ) -> QLineEdit:
        """A labelled path field with a Browse button, appended to `layout`. Returns the field."""
        row = QHBoxLayout()
        caption = QLabel(label)
        caption.setMinimumWidth(150)
        row.addWidget(caption)
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        if tooltip:
            field.setToolTip(tooltip)
        row.addWidget(field, 1)
        button = QPushButton("Browse…")
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(on_browse)
        row.addWidget(button)
        layout.addLayout(row)
        return field
