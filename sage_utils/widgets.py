"""PyQt6 UI building blocks shared by the SAGE front ends, so the desktop apps don't
duplicate them: a card frame, a background worker thread, bundled-resource lookup, a
name completer, and the collapsible data-sources panel."""

import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, QStringListModel, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QApplication,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from sage_utils.config import read_json, write_json
from sage_utils.sources import load_saved_sources, save_sources
from sage_utils.styles import DARK_STYLE, LIGHT_STYLE

# The theme preference is shared across every SAGE front end, so it lives under one key
# rather than per app - toggle dark/light in one and the others open the same way.
_THEME_APP = "sage_utils"
_THEME_FILE = "theme.json"


class _ThemeNotifier(QObject):
    """Broadcasts theme flips to widgets whose colours are set in code rather than by the
    stylesheet (e.g. a table's severity-coloured text), which the app stylesheet swap can't
    repaint on its own. `changed` carries True for dark, False for light."""

    changed = pyqtSignal(bool)


# One process-wide notifier; widgets connect to `theme_notifier.changed` to recolour on toggle.
theme_notifier = _ThemeNotifier()


def saved_dark_theme(default: bool = True) -> bool:
    """The remembered theme choice (True = dark), defaulting to dark when none is saved."""
    data = read_json(_THEME_APP, _THEME_FILE, {})
    value = data.get("dark") if isinstance(data, dict) else None
    return value if isinstance(value, bool) else default


def apply_theme(dark: bool, *, persist: bool = True) -> None:
    """Repaint the running application in the shared dark or light theme, and (by default)
    remember the choice for next launch. A no-op before a QApplication exists."""
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(DARK_STYLE if dark else LIGHT_STYLE)
    if persist:
        write_json(_THEME_APP, _THEME_FILE, {"dark": bool(dark)})
    theme_notifier.changed.emit(bool(dark))


class ThemeToggle(QPushButton):
    """A checkable toolbar button that flips the app between the shared dark and light themes
    and remembers the choice. Drop it into any SAGE front end; it reflects the saved state on
    construction (the theme itself is applied by `run_app` at boot)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(saved_dark_theme())
        self.toggled.connect(self._on_toggled)
        self._sync_label()

    def _on_toggled(self, dark: bool) -> None:
        apply_theme(dark)
        self._sync_label()

    def _sync_label(self) -> None:
        self.setText("☾ Dark" if self.isChecked() else "☀ Light")


class CopyableLabel(QLabel):
    """A QLabel whose text the user can select with the mouse and copy. Mouse-only
    selection keeps labels out of the tab-focus order."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)


def card(title: str | None = None, *, spacing: int = 8) -> tuple[QFrame, QVBoxLayout]:
    """A styled `#card` frame and its vertical layout. `title`, if given, adds an
    uppercase `#h2` heading."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(spacing)
    if title is not None:
        head = CopyableLabel(title.upper())
        head.setObjectName("h2")
        layout.addWidget(head)
    return frame, layout


def getting_started_dialog(
    parent: QWidget, title: str, html: str, *, icon: QIcon | None = None
) -> QDialog:
    """A non-modal, scrollable dialog showing `html` (rich text with working external links).
    Built once and reused by `add_help_menu`, which caches it on the window so it keeps its
    scroll position between openings."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    if icon is not None:
        dialog.setWindowIcon(icon)
    dialog.resize(560, 520)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setHtml(html)
    layout.addWidget(browser, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.close)
    buttons.accepted.connect(dialog.close)
    layout.addWidget(buttons)
    return dialog


def add_help_menu(
    window: QMainWindow,
    *,
    guide_title: str,
    guide_html: str,
    about_title: str,
    about_html: str,
    icon: QIcon | None = None,
) -> None:
    """Add a `&Help` menu to `window`: a "Getting started…" walkthrough of the basics and an
    About entry - the standard help affordance every SAGE desktop app carries, so a newcomer
    can always find out what the window does and how to drive it. The walkthrough dialog is
    created on first use and cached on the window, so it keeps its scroll position across
    openings."""
    menu = window.menuBar().addMenu("&Help")

    def show_guide() -> None:
        dialog = getattr(window, "_help_dialog", None)
        if dialog is None:
            dialog = getting_started_dialog(window, guide_title, guide_html, icon=icon)
            window._help_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_about() -> None:
        QMessageBox.about(window, about_title, about_html)

    menu.addAction("&Getting started…", show_guide)
    menu.addSeparator()
    menu.addAction(f"&{about_title}", show_about)


def pil_to_pixmap(picture) -> QPixmap:
    """A QPixmap copy of a Pillow image (kept RGBA so transparency survives)."""
    picture = picture.convert("RGBA")
    data = picture.tobytes("raw", "RGBA")
    image = QImage(data, picture.width, picture.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(image.copy())  # copy() detaches from the temp buffer


def resource_path(name: str, anchor: str) -> Path:
    """Path to a bundled resource, working in both a dev run and a PyInstaller one-file
    exe (which unpacks under `sys._MEIPASS`). `anchor` is the app module's `__file__`."""
    base = Path(getattr(sys, "_MEIPASS", Path(anchor).resolve().parent))
    return base / name


def run_app(window_factory, *, icon_file: str, anchor: str, app_name: str | None = None) -> None:
    """Boot a QApplication with the shared dark theme and bundled window icon, show the
    window `window_factory()` builds, and run the event loop until exit. `anchor` is the app
    module's `__file__` (for `resource_path`); `app_name`, if given, sets the application name."""
    app = QApplication(sys.argv)
    if app_name is not None:
        app.setApplicationName(app_name)
    app.setWindowIcon(QIcon(str(resource_path(icon_file, anchor))))
    apply_theme(saved_dark_theme(), persist=False)  # last chosen theme, dark by default
    window = window_factory()
    window.show()
    sys.exit(app.exec())


def make_completer(parent, *, model=None, names=None, on_pick=None) -> QCompleter:
    """A case-insensitive, substring-matching completer over object names. Pass a shared
    `model` or a `names` list; `on_pick`, if given, fires when a suggestion is activated."""
    completer = QCompleter(parent)
    if model is not None:
        completer.setModel(model)
    elif names is not None:
        completer.setModel(QStringListModel(list(names), parent))
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    if on_pick is not None:
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.activated.connect(on_pick)
    return completer


class Worker(QThread):
    """Runs one callable off the UI thread, emitting its result or an error string. Pass
    `self.progress.emit` into the callable as a thread-safe way to report status."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(result)


def run_worker(owner, fn, on_done, on_failed=None) -> Worker:
    """Run `fn` on a background `Worker`, wiring `on_done`/`on_failed` to its result/error
    signals. A strong reference is kept on `owner._workers` (created on first use) so the
    QThread isn't garbage-collected mid-run, and dropped when the work finishes. Returns the
    started worker for callers that need to wire extra signals (e.g. `progress`)."""
    workers = getattr(owner, "_workers", None)
    if workers is None:
        workers = set()
        owner._workers = workers
    worker = Worker(fn)

    def cleanup() -> None:
        workers.discard(worker)

    worker.done.connect(on_done)
    worker.done.connect(cleanup)
    if on_failed is not None:
        worker.failed.connect(on_failed)
    worker.failed.connect(cleanup)
    workers.add(worker)
    worker.start()
    return worker


class SourcesPanel(QFrame):
    """Collapsible data-sources card: an ordered list of `(kind, path)` sources with
    add/remove/reorder controls and a Load button. Sources load top to bottom (later
    overrides earlier). Emits `load_requested` on Load; the host reads `sources()`.
    Emits `collapsed_changed(bool)` whenever it collapses or expands, so a host can move a
    parent splitter's handle to match the new size. Pass `show_load=False` for a host whose
    own action button (e.g. a Check) consumes the sources - the panel is then just the
    ordered list editor and `load_button` is None."""

    load_requested = pyqtSignal()
    collapsed_changed = pyqtSignal(bool)

    def __init__(
        self,
        *,
        title: str = "SOURCES",
        expanded_hint: str | None = None,
        item_label=None,
        list_min_height: int | None = None,
        list_max_height: int | None = None,
        show_status: bool = False,
        show_load: bool = True,
    ) -> None:
        super().__init__()
        self.setObjectName("card")
        self._title = title
        self._expanded_hint = expanded_hint
        self._item_label = item_label or (lambda kind, path: f"[{kind}]  {path}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(8)

        self.header = QPushButton()
        self.header.setObjectName("sectionHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.clicked.connect(self._toggle)  # header doubles as a collapse toggle
        outer.addWidget(self.header)

        self.body = QWidget()
        # Transparent (scoped by object name so it doesn't cascade onto child buttons)
        # so the card surface shows behind the controls, not the dark window background.
        self.body.setObjectName("sourcesBody")
        self.body.setStyleSheet("QWidget#sourcesBody { background: transparent; }")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        self.source_list = QListWidget()
        self.source_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        # Clear the viewport's inherited dark window background so the card shows through.
        self.source_list.viewport().setStyleSheet("background: transparent;")
        if list_min_height is not None:
            self.source_list.setMinimumHeight(list_min_height)
        if list_max_height is not None:
            self.source_list.setMaximumHeight(list_max_height)
        body.addWidget(self.source_list)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, slot in (
            ("Add folder…", self._add_folder),
            ("Add .big…", self._add_big),
            ("Remove", self._remove_source),
            ("↑", lambda: self._move(-1)),
            ("↓", lambda: self._move(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.load_button: QPushButton | None = None
        if show_load:
            self.load_button = QPushButton("Load")
            self.load_button.setObjectName("primary")
            self.load_button.clicked.connect(self.load_requested.emit)
            buttons.addWidget(self.load_button)
        body.addLayout(buttons)

        outer.addWidget(self.body)

        self.status: QLabel | None = None
        if show_status:
            self.status = QLabel("")
            self.status.setObjectName("muted")
            outer.addWidget(self.status)

        self._update_header()

    def add_source(self, kind: str, path: str) -> None:
        item = QListWidgetItem(self._item_label(kind, path))
        item.setData(Qt.ItemDataRole.UserRole, (kind, path))
        self.source_list.addItem(item)
        self._update_header()

    def clear(self) -> None:
        """Drop every source, leaving the list empty."""
        self.source_list.clear()
        self._update_header()

    def sources(self) -> list[tuple[str, str]]:
        return [
            self.source_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.source_list.count())
        ]

    def count(self) -> int:
        return self.source_list.count()

    def prompt_add_folder(self) -> None:
        """Open the folder picker and add the chosen folder. Public so an onboarding host can
        offer the same action its own buttons do."""
        path = QFileDialog.getExistingDirectory(self, "Add a data folder")
        if path:
            self.add_source("folder", path)

    def prompt_add_big(self) -> None:
        """Open the .big picker and add the chosen archive (see `prompt_add_folder`)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Add a .big archive", "", "BIG archives (*.big)"
        )
        if path:
            self.add_source("big", path)

    # The toolbar buttons keep their private-method wiring; both now delegate to the public
    # prompts so the onboarding state and the panel share one add path.
    def _add_folder(self) -> None:
        self.prompt_add_folder()

    def _add_big(self) -> None:
        self.prompt_add_big()

    def _remove_source(self) -> None:
        for item in self.source_list.selectedItems():
            self.source_list.takeItem(self.source_list.row(item))
        self._update_header()

    def _move(self, delta: int) -> None:
        """Move the selected source up (delta -1) or down (delta +1) one place."""
        row = self.source_list.currentRow()
        target = row + delta
        if 0 <= row and 0 <= target < self.source_list.count():
            item = self.source_list.takeItem(row)
            self.source_list.insertItem(target, item)
            self.source_list.setCurrentRow(target)

    def set_collapsed(self, collapsed: bool) -> None:
        self.body.setVisible(not collapsed)
        # Cap the height to the header when collapsed so a parent QSplitter shrinks the pane
        # to just the title rather than leaving the old (now empty) space; lift the cap when
        # expanded so it can grow back. A no-op for a panel laid out in a plain box.
        self.setMaximumHeight(self.sizeHint().height() if collapsed else QWIDGETSIZE_MAX)
        self._update_header()
        self.collapsed_changed.emit(collapsed)

    def _toggle(self) -> None:
        self.set_collapsed(self.body.isVisible())

    def _update_header(self) -> None:
        # `isHidden()` reflects the visibility flag even before show, so the arrow
        # is correct at construction.
        expanded = not self.body.isHidden()
        arrow = "▾" if expanded else "▸"
        if expanded and self._expanded_hint:
            self.header.setText(f"{arrow}  {self._expanded_hint}")
        else:
            self.header.setText(f"{arrow}  {self._title} ({self.count()})")


class SourceLoader:
    """Runs an ordered `(kind, path)` source list through a `build` callable on a background
    worker, with the boilerplate every SAGE front end shares: persist the list, disable the
    Load button, put an "…ing N source(s)" line on a status widget, hand the result (or the
    error) back to the host, and (optionally) collapse the panel once loaded.

    It backs two flows that are the same skeleton:
      * loading data into a Game - `build=load_sources`, result `(game, names)`;
      * indexing image archives into a TextureSource - `build=lambda s, _p: TextureSource(s)`.

    Pass panel kwargs (title, hints, …) to have it build and own a `SourcesPanel` whose Load
    button drives it, or `panel=None` for a headless loader triggered by `load(sources)` (e.g.
    an app auto-indexing remembered image sources with no visible panel). The host keeps its
    own post-load fan-out in `on_loaded`; `on_start`, if given, runs just before the worker
    (the game browser uses it to blank its results area while data loads)."""

    def __init__(
        self,
        owner,
        *,
        build,
        app_name: str,
        on_loaded,
        on_failed=None,
        status=None,
        on_start=None,
        collapse_on_load: bool = False,
        verb: str = "Loading",
        noun: str = "source",
        empty_message: str = "Add at least one folder or .big file first.",
        panel: "SourcesPanel | None" = None,
        **panel_kwargs,
    ) -> None:
        self.owner = owner
        self._build = build
        self.app_name = app_name
        self._on_loaded = on_loaded
        self._on_failed = on_failed
        self._status = status
        self._on_start = on_start
        self._collapse_on_load = collapse_on_load
        self._verb = verb
        self._noun = noun
        self._empty_message = empty_message
        self._worker: Worker | None = None
        if panel is None and panel_kwargs:
            panel = SourcesPanel(**panel_kwargs)
        self.panel = panel
        if self.panel is not None:
            self.panel.load_requested.connect(self.load)
            # A panel built with show_status carries its own status label; report to it unless
            # the host wired a different one.
            if self._status is None:
                self._status = getattr(self.panel, "status", None)

    # -- panel helpers ------------------------------------------------------------------
    def restore_saved(self) -> None:
        """Re-add the source list remembered for this app under `app_name` (a no-op headless)."""
        if self.panel is None:
            return
        for kind, path in load_saved_sources(self.app_name):
            self.panel.add_source(kind, path)

    def set_sources(self, sources) -> None:
        """Replace the panel's list with `sources` (used by the one-click Edain/vanilla loads)."""
        if self.panel is None:
            return
        self.panel.clear()
        for kind, path in sources:
            self.panel.add_source(kind, path)

    def sources(self) -> list[tuple[str, str]]:
        return self.panel.sources() if self.panel is not None else []

    # -- loading ------------------------------------------------------------------------
    def load(self, sources=None, *, save: bool = True) -> None:
        """Build `sources` (or the panel's current list) on a worker. Persists the list under
        `app_name` (unless `save=False`), then hands the result to `on_loaded`."""
        srcs = list(sources) if sources is not None else self.sources()
        if not srcs:
            self._say(self._empty_message)
            return
        if save:
            save_sources(srcs, self.app_name)
        self._enable_load(False)
        self._say(f"{self._verb} {len(srcs)} {self._noun}(s)…")
        if self._on_start is not None:
            self._on_start(srcs)
        self._worker = run_worker(
            self.owner,
            lambda: self._build(srcs, self._emit_progress),
            self._on_done,
            self._on_worker_failed,
        )
        self._worker.progress.connect(self._say)

    def _on_done(self, result) -> None:
        self._enable_load(True)
        if self._collapse_on_load and self.panel is not None:
            self.panel.set_collapsed(True)
        self._on_loaded(result)

    def _on_worker_failed(self, message: str) -> None:
        self._enable_load(True)
        if self._on_failed is not None:
            self._on_failed(message)
        else:
            self._say(f"Load failed - {message}")

    def _emit_progress(self, text: str) -> None:
        # The build callable reports progress through the worker's own signal (thread-safe);
        # a report landing before `load` finishes wiring the worker is simply dropped.
        worker = self._worker
        if worker is not None:
            worker.progress.emit(text)

    def _enable_load(self, enabled: bool) -> None:
        if self.panel is not None and self.panel.load_button is not None:
            self.panel.load_button.setEnabled(enabled)

    def _say(self, text: str) -> None:
        if self._status is None:
            return
        setter = getattr(self._status, "setText", self._status)
        setter(text)
