"""The SAGE Lint window: point it at a mod folder, set a few options, press Check, and
browse the errors and warnings in a searchable, sortable table. Built on the shared
sage_utils widgets (cards, the background Worker, the theme toggle) so it looks and behaves
like the other SAGE front ends. The lint itself runs the CLI in-process on a worker thread
(see `runner`), inheriting all of its config/baseline/sorting behaviour."""

from pathlib import Path

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextBrowser,
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

APP_NAME = "sage_lint"
APP_TITLE = "SAGE Lint"
# Icon art by Ludovic Bourgeois-Lefèvre:
# https://ludovicbourgeoislefevre.artstation.com/projects/2xL1WJ
ICON_FILE = "icon.ico"

# The report columns: (heading, diagnostic key), handed to the shared FindingsView.
_COLUMNS = (
    ("Severity", "severity"),
    ("Code", "code"),
    ("File", "file"),
    ("Line", "line_start"),
    ("Message", "message"),
)

# The Help ▸ Getting started walkthrough. Kept as one HTML block so QTextBrowser lays it out
# with headings and lists; the steps mirror the fields on the options card.
_GETTING_STARTED_HTML = """
<h2>Getting started with SAGE Lint</h2>
<p>SAGE Lint reads a mod's <code>.ini</code> game data, assembles the game, and reports
problems - repeated fields, dangling references, out-of-range values, and more. Follow these
steps the first time you set it up.</p>

<h3>1. Pick your mod folder</h3>
<p>Next to <b>Mod folder</b>, press <b>Browse…</b> and choose the folder that holds your
mod's <code>.ini</code> files. Everything under it is checked.</p>

<h3>2. Point at the base game (optional)</h3>
<p>If your mod overrides base-game files, add the unmodified game data to the
<b>BASE GAME</b> list - folders or <code>.big</code> archives - so references resolve against
the original data. Sources load top to bottom (later overrides earlier); put the original
game first and reorder with the ↑/↓ buttons. The list is remembered for the next launch.
You can skip this for a standalone mod.</p>

<h3>3. Add a project config (optional)</h3>
<p>Drop a <code>.sagelint</code> file in your mod folder to set which rules run, the default
severity, formatting style, and more. When one is present the UI loads it automatically and
uses it on every Check. See <code>.sagelint.template</code> in the repo for the documented
options.</p>

<h3>4. Choose what to show</h3>
<p>Use <b>Show</b> to set the lowest severity you want listed (ERROR, WARNING, or INFO).
Tick <b>Suggest fixes for typos</b> to get "did you mean…" hints, and
<b>Auto-fix safe issues</b> only when you want the linter to rewrite files for you.</p>

<h3>5. Run the check</h3>
<p>Press <b>Check</b>. Results appear in the table below - sort by any column, use
<b>Search</b> to filter, and <b>double-click a row</b> to open that file. On a large mod the
first check can take a moment.</p>

<h3>6. Adopt on an existing mod (optional)</h3>
<p>To try the linter on a mod that already has many findings, set a <b>Baseline</b> file so
only new problems are reported. Baselines found under the mod are merged automatically.</p>

<h3>Other tools</h3>
<p><b>Format</b> reprints the ini files in the canonical style. <b>Export CSV…</b> saves the
rows currently shown so you can share them.</p>
"""


class LintWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        self.resize(1180, 760)
        self._workers = set()
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

        root.addWidget(self._build_options_card())
        root.addWidget(self._build_base_panel())
        # The searchable, sortable results table is the shared FindingsView (the Edain Linter
        # uses the same one). Its double-click / export messages come back on `status`.
        self.findings = FindingsView(
            _COLUMNS,
            stretch_col=4,  # Message takes the slack
            path_col=2,  # the File column, opened on double-click
            numeric_keys=("line_start",),
            widths={0: 90, 1: 170, 2: 320, 3: 60},
        )
        self.findings.status.connect(lambda text: self.status.setText(text))
        root.addWidget(self.findings, 1)

        self.status = QLabel("Pick a mod folder, then press Check.")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

        # Last session's base sources come back first; a picked folder's `.sagelint` (or the
        # startup autoload just below) replaces them when it names its own.
        for kind, path in load_saved_sources(APP_NAME):
            self.base_panel.add_source(kind, path)
        self._autoload_startup_config()

    def _autoload_startup_config(self) -> None:
        """If a `.sagelint` (or `.sagelint.local`) sits beside the app, pre-select that folder
        and load its config on launch - so a teammate who drops the exe into their mod folder
        just presses Check."""
        folder = app_dir()
        if has_project_config(folder):
            self.folder_field.setText(str(folder))
            self._load_project_config()

    def _build_menu(self) -> None:
        """A Help menu: a getting-started walkthrough for newcomers, and an About entry."""
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("&Getting started…", self._show_getting_started)
        help_menu.addSeparator()
        help_menu.addAction("&About SAGE Lint", self._show_about)

    def _show_getting_started(self) -> None:
        """A scrollable, non-modal walkthrough of the basic steps to set up SAGE Lint. Held on
        the window so it keeps its scroll position between openings."""
        if getattr(self, "_help_dialog", None) is None:
            self._help_dialog = self._make_help_dialog()
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def _make_help_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("Getting started with SAGE Lint")
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
            "About SAGE Lint",
            f"<b>{APP_TITLE}</b> v{__version__}"
            "<p>A formatter and linter for SAGE ini game data. This window runs the "
            "<code>sage_lint</code> command line in-process - point it at a mod folder, "
            "press Check, and browse the results.</p>"
            "<p>Icon art by Ludovic Bourgeois-Lefèvre.</p>",
        )

    def _build_options_card(self) -> QWidget:
        frame, layout = card("What to check")

        self.folder_field = self._path_row(
            layout,
            "Mod folder",
            "Folder of ini files to check",
            self._pick_folder,
            tooltip="The mod's folder of .ini files - the linter checks everything under it.",
        )
        self.folder_field.editingFinished.connect(self._load_project_config)
        self.baseline_field = self._path_row(
            layout,
            "Baseline (optional)",
            "Baseline file of accepted diagnostics",
            self._pick_baseline,
            tooltip="A baseline of already-accepted diagnostics; only new findings are reported.",
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
        self.level_box.setToolTip(
            "The lowest severity to report. ERROR shows only errors; INFO shows everything."
        )
        options.addWidget(self.level_box)
        self.suggest_check = QCheckBox("Suggest fixes for typos")
        self.suggest_check.setToolTip(
            "Add a 'did you mean…' suggestion to unknown-name diagnostics (nearest known name)."
        )
        options.addWidget(self.suggest_check)
        self.fix_check = QCheckBox("Auto-fix safe issues (rewrites files)")
        self.fix_check.setToolTip(
            "Apply the fixes the linter deems safe and rewrite the affected files on disk."
        )
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
        self.check_button.setToolTip(
            "Run the linter over the mod folder and list every error and warning below."
        )
        self.check_button.clicked.connect(self._run)
        options.addWidget(self.check_button)
        layout.addLayout(options)
        return frame

    def _build_base_panel(self) -> QWidget:
        """The base-game sources: an ordered list of folders and .big archives (the shared
        SourcesPanel sage_ui / sage_wiki use, without its Load button - Check consumes it).
        Order matters: the CLI layers them top to bottom, so put the original game first and
        use the ↑/↓ buttons to reorder."""
        self.base_panel = SourcesPanel(
            title="BASE GAME (OPTIONAL)",
            expanded_hint=(
                "BASE GAME (OPTIONAL) - folders / .big archives, loaded top to bottom "
                "(reorder with ↑/↓): the original game first. References into these resolve "
                "instead of showing up as dangling."
            ),
            list_max_height=96,
            show_load=False,
        )
        return self.base_panel

    def _set_bases(self, paths) -> None:
        """Show `paths` as the base-game sources, replacing the list (kind read off the
        suffix, mirroring how the CLI classifies a `--base`)."""
        self.base_panel.clear()
        for path in paths:
            kind = "big" if str(path).lower().endswith(".big") else "folder"
            self.base_panel.add_source(kind, str(path))

    def _path_row(
        self, layout, label: str, placeholder: str, on_browse, tooltip: str = ""
    ) -> QLineEdit:
        """A labelled path field with a Browse button, appended to `layout`. Returns the field.
        `tooltip`, if given, is shown on hover over both the field and its Browse button."""
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
        # the config provides one, so sources the user added for a config-less folder are not
        # wiped on a focus-out reload.
        bases = config_bases(config, folder)
        if bases:
            self._set_bases(bases)
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
        sources = self.base_panel.sources()
        save_sources(sources, APP_NAME)  # remember the base list for next launch
        argv = build_argv(
            folder,
            level=self.level_box.currentText(),
            bases=[path for _, path in sources],
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
        self.findings.set_diagnostics(report.get("diagnostics", []))
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
