"""The Edain Patch Notes window: point it at the release spreadsheet's CSV export, choose
whether beta-only notes and older batches come along, and press Generate. The English and German
BBcode posts appear in the two preview tabs (ready to copy into a forum post) and are written as
`<sheet> - English.txt` / `<sheet> - German.txt` beside the sheet, or in whatever output folder is
set. The CSV can also be dropped anywhere on the window, and the last sheet, output folder and
filter choices come back on the next launch.

Nothing about *how* the notes are rendered lives here: that is the Qt-free
`sage_mods.edain.patch_notes`, which this window only drives."""

import csv
from datetime import date
from pathlib import Path

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sage_mods.edain.patch_notes import (
    Note,
    PatchNotes,
    batch_dates,
    read_notes,
    render_notes,
    write_notes,
)
from sage_mods.edain.patch_notes.ui import __version__
from sage_utils.config import read_json, write_json
from sage_utils.widgets import (
    CopyableLabel as QLabel,
)
from sage_utils.widgets import (
    ThemeToggle,
    add_help_menu,
    card,
    resource_path,
)

APP_NAME = "sage_edain_patch_notes"
APP_TITLE = "Edain Patch Notes"
ICON_FILE = "icon.ico"

# The remembered sheet, output folder and filter choices (per-user, beside the shared theme).
_SETTINGS_FILE = "patch_notes.json"

# The date list's "no cut-off" entry, which every sheet offers whatever dates it records.
_ALL_BATCHES = "All"

_GETTING_STARTED_HTML = """
<h2>Getting started with Edain Patch Notes</h2>
<p>This window turns the patch-notes spreadsheet into the two BBcode posts a release needs - one
English, one German - so they can be pasted straight into a forum post.</p>

<h3>1. Export the sheet as CSV</h3>
<p>From the spreadsheet, export the notes sheet as <code>.csv</code>. The columns it reads are
<b>Faction</b>, <b>English</b>, <b>German</b>, <b>Beta</b> and <b>Date</b>; anything else is
ignored. Only the last row of a batch needs its date - it applies to every row above it, up to
the previous date.</p>

<h3>2. Pick the file</h3>
<p>Press <b>Browse…</b> next to <b>Notes CSV</b>, or drag the file anywhere onto this window.
The batch dates in it fill the <b>Notes added after</b> list straight away. The posts are written
beside the sheet unless you set another <b>Output folder</b>.</p>

<h3>3. Choose what goes in</h3>
<p><b>Include beta-only notes</b> adds the rows whose <b>Beta</b> column says TRUE - leave it off
for a public release post. <b>Notes added after</b> lists the batch dates the sheet itself
records, written out in full and newest first: pick the batch you last posted and only the notes
added after it are kept - that batch itself is left out, since it has already been posted - or
leave it on <b>All</b> for every note in the sheet. The notes below the last dated row are the
open batch, still waiting for a date: being the newest, they are in the post whichever date you
pick.</p>

<h3>4. Generate</h3>
<p>Press <b>Generate</b>. The two tabs show the finished BBcode - <b>Copy</b> puts the visible
one on the clipboard - and both files are written for you.</p>

<h3>Writing the notes</h3>
<p>A note starting with <code>-</code> is nested under the note above it (<code>--</code> one
level deeper again). <code>*italic*</code>, <code>**bold**</code> and
<code>***both***</code> become the matching BBcode tags. A row may name several factions,
separated by commas, and appears under each. A note filled in for one language only still appears
in both posts, marked <b>TRANSLATE ME</b>, so it cannot be posted unnoticed.</p>
"""


def _full_date(day: date) -> str:
    """A batch date spelled out - "2 February 2026" - so the day and the month cannot be read
    the wrong way round, as they can in the sheet's own `02/02/2026`."""
    return f"{day.day} {day:%B %Y}"


class PatchNotesWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        # Wide enough for the options row (its two checkboxes, the date list and the buttons) to
        # lay out unsqueezed, which is what sets the window's own minimum width.
        self.resize(1100, 800)
        self.setAcceptDrops(True)  # drop the CSV anywhere on the window

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

        options, options_layout = card("What to generate")
        self.csv_field = self._path_row(
            options_layout,
            "Notes CSV",
            "The patch-notes sheet, exported as CSV",
            self._pick_csv,
            tooltip="The spreadsheet export: Faction, English, German, Beta and Date columns.",
        )
        self.csv_field.editingFinished.connect(self._refresh_dates)
        self.output_field = self._path_row(
            options_layout,
            "Output folder",
            "Where the two .txt posts go (beside the CSV by default)",
            self._pick_output,
            tooltip="Leave empty to write the posts next to the CSV.",
        )
        options_layout.addLayout(self._filter_row())
        root.addWidget(options)

        self.tabs = QTabWidget()
        self.english_view = self._preview_tab("English")
        self.german_view = self._preview_tab("German")
        root.addWidget(self.tabs, 1)

        self.status = QLabel("Pick the notes CSV, then press Generate.")
        self.status.setObjectName("muted")
        # A status line naming the output folder is longer than the window: unwrapped, a QLabel
        # cannot shrink below its text and would widen the whole window to fit the path.
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self._restore_settings()

    def _build_menu(self) -> None:
        add_help_menu(
            self,
            guide_title="Getting started with Edain Patch Notes",
            guide_html=_GETTING_STARTED_HTML,
            about_title="About Edain Patch Notes",
            about_html=(
                f"<b>{APP_TITLE}</b> v{__version__}"
                "<p>Turns the patch-notes spreadsheet into the English and German BBcode posts, "
                "grouped by faction and nested by the notes' own leading dashes.</p>"
            ),
            icon=QIcon(str(resource_path(ICON_FILE, __file__))),
        )

    def _filter_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.beta_check = QCheckBox("Include beta-only notes")
        self.beta_check.setToolTip(
            "Add the rows whose Beta column says TRUE. Leave off for a public release post."
        )
        row.addWidget(self.beta_check)
        row.addWidget(QLabel("Notes added after:"))
        # The dates the sheet itself records, newest first, under an All that takes the lot: any
        # other day would just select what the batch below it does, so the choice is the sheet's,
        # not a free calendar.
        self.after_box = QComboBox()
        self.after_box.setToolTip(
            "How far back to go: pick the batch you last posted and only what came after it is "
            "kept, that batch itself left out; All keeps every note. The undated notes at the "
            "end of the sheet - the open batch - are the newest, so they are kept whatever is "
            "chosen."
        )
        # The dates arrive long after the box is built, and the default policy sizes it once, on
        # first show - when it is still empty - which clips them. Re-size on every fill instead.
        self.after_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        row.addWidget(self.after_box)
        row.addStretch(1)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setToolTip("Copy the post shown below to the clipboard.")
        self.copy_button.clicked.connect(self._copy_shown)
        row.addWidget(self.copy_button)
        self.generate_button = QPushButton("Generate")
        self.generate_button.setObjectName("primary")
        self.generate_button.clicked.connect(self._generate)
        row.addWidget(self.generate_button)
        return row

    def _preview_tab(self, label: str) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        # A note is a whole sentence, so its BBcode line is long: wrap it to the box rather than
        # scroll sideways, and the preview never asks the window for more width than it has.
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        view.setFont(QFont("Consolas", 10))
        view.setPlaceholderText(f"The {label} post appears here once you press Generate.")
        self.tabs.addTab(view, label)
        return view

    def _generate(self) -> None:
        current = self._read_current()
        if current is None:
            return
        path, notes = current
        self._fill_dates(notes)  # the sheet may have gained a batch since it was chosen

        result = render_notes(notes, beta=self.beta_check.isChecked(), after=self._selected_after())
        self.english_view.setPlainText(result.english)
        self.german_view.setPlainText(result.german)
        self._save_settings()
        if not result.count:
            self.status.setText(
                f"None of the {len(notes)} note(s) in {path.name} matched the filters."
            )
            return

        folder = Path(self.output_field.text().strip() or path.parent)
        try:
            english_path, german_path = write_notes(result, folder, path.stem)
        except OSError as exc:
            self.status.setText(f"Could not write the posts - {type(exc).__name__}: {exc}")
            return
        self.status.setText(
            f"{self._summary(result)}. Written to {english_path.name} and "
            f"{german_path.name} in {folder}."
        )

    def _read_current(self) -> tuple[Path, list[Note]] | None:
        """The chosen sheet and its notes, or None (with the reason on the status line) when
        there is no readable CSV to read."""
        text = self.csv_field.text().strip()
        path = Path(text)
        if not text or not path.is_file():
            self.status.setText("Pick the notes CSV first.")
            return None
        try:
            return path, read_notes(path)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            self.status.setText(f"Could not read {path.name} - {type(exc).__name__}: {exc}")
            return None

    def _refresh_dates(self) -> None:
        """Offer the chosen sheet's own batch dates in the date list. A path that is not (yet) a
        readable CSV just empties the list; Generate is where an unreadable file is reported."""
        path = Path(self.csv_field.text().strip())
        try:
            notes = read_notes(path) if path.is_file() else []
        except (OSError, UnicodeDecodeError, csv.Error):
            notes = []
        self._fill_dates(notes)

    def _fill_dates(self, notes: list[Note]) -> None:
        """Rebuild the date list from `notes` - All, then each batch date, newest first - keeping
        the chosen date selected when the sheet still has it. A sheet with no dated batch offers
        All alone, since there is then nothing to cut on."""
        previous = self.after_box.currentData()
        self.after_box.clear()
        self.after_box.addItem(_ALL_BATCHES, "")
        for day in batch_dates(notes):
            self.after_box.addItem(_full_date(day), day.isoformat())
        # Hold the width the longest date needs: the row would otherwise squeeze the box back
        # down when space runs short, eliding the very date it is there to show.
        self.after_box.setMinimumWidth(self.after_box.sizeHint().width())
        self._select_date(previous)

    def _select_date(self, iso: object) -> bool:
        """Show the batch date `iso` (an ISO string, as the list stores it), if the list has it.
        Falls back to All, which the empty string selects."""
        index = self.after_box.findData(str(iso or ""))
        if index >= 0:
            self.after_box.setCurrentIndex(index)
        return index >= 0

    def _selected_after(self) -> date | None:
        """The chosen batch date, or None when All is chosen and every note is wanted."""
        chosen = self.after_box.currentData()
        return date.fromisoformat(str(chosen)) if chosen else None

    @staticmethod
    def _summary(result: PatchNotes) -> str:
        notes = "1 note" if result.count == 1 else f"{result.count} notes"
        factions = "1 faction" if len(result.factions) == 1 else f"{len(result.factions)} factions"
        return f"{notes} across {factions}"

    def _copy_shown(self) -> None:
        view = self.tabs.currentWidget()
        text = view.toPlainText() if isinstance(view, QPlainTextEdit) else ""
        if not text:
            self.status.setText("Nothing to copy yet - press Generate first.")
            return
        QApplication.clipboard().setText(text)
        self.status.setText(f"{self.tabs.tabText(self.tabs.currentIndex())} post copied.")

    def _pick_csv(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Choose the patch-notes CSV",
            self.csv_field.text().strip(),
            "CSV files (*.csv);;All files (*)",
        )
        if chosen:
            self.csv_field.setText(chosen)
            self._refresh_dates()

    def _pick_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose where the posts are written", self.output_field.text().strip()
        )
        if chosen:
            self.output_field.setText(chosen)

    def _restore_settings(self) -> None:
        """Bring back the last sheet, output folder and filter choices, so a second release post
        is one press of Generate. A missing or unreadable file simply leaves the defaults."""
        saved = read_json(APP_NAME, _SETTINGS_FILE, {})
        if not isinstance(saved, dict):
            return
        self.csv_field.setText(str(saved.get("csv", "")))
        self.output_field.setText(str(saved.get("output", "")))
        self.beta_check.setChecked(bool(saved.get("beta", False)))
        self._refresh_dates()
        # The sheet may have moved on since; a batch it no longer has falls back to All.
        self._select_date(saved.get("after", ""))

    def _save_settings(self) -> None:
        write_json(
            APP_NAME,
            _SETTINGS_FILE,
            {
                "csv": self.csv_field.text().strip(),
                "output": self.output_field.text().strip(),
                "beta": self.beta_check.isChecked(),
                "after": str(self.after_box.currentData() or ""),
            },
        )

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() == ".csv":
                self.csv_field.setText(str(path))
                self._refresh_dates()
                self.status.setText(f"Loaded {path.name}. Press Generate.")
                return
        self.status.setText("Only a .csv export can be dropped here.")

    def _path_row(
        self, layout, label: str, placeholder: str, on_browse, tooltip: str = ""
    ) -> QLineEdit:
        """A labelled path field with a Browse button, appended to `layout`. Returns the field."""
        row = QHBoxLayout()
        caption = QLabel(label)
        caption.setMinimumWidth(120)
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
