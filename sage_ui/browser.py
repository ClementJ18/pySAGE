"""The main browser window: source loading, search, and the unit comparison. `Browser`
owns the source panel, the two search boxes (raw-name and display-name modes), the
UNIT_BUILD back trail, the pinned Faction Info card, and the unit comparison."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sage_ini.model.game import Game
from sage_ini.suggest import closest_names
from sage_ui import __version__
from sage_ui.extract import TEXTURE_SOURCES_APP, ExtractImageDialog
from sage_ui.layout import clear_layout
from sage_ui.object_browser import ObjectBrowser
from sage_ui.registry import (
    detect_installed_games,
    registry_read_paths_bfme2,
    registry_read_paths_rotwk,
    vanilla_archives,
)
from sage_ui.unit_panel import UnitPanel
from sage_utils.factiongraph import build_faction_graphs
from sage_utils.sources import (
    load_saved_sources,
    load_sources,
    save_sources,
)
from sage_utils.textures import TextureSource, default_background
from sage_utils.views import (
    display_name,
    display_name_index,
    fmt_stat,
    playable_factions,
)
from sage_utils.widgets import (
    CopyableLabel as QLabel,  # info labels are selectable/copyable by default
)
from sage_utils.widgets import (
    SourcesPanel,
    ThemeToggle,
    Worker,
    card,
    make_completer,
    resource_path,
    run_worker,
)

ICON_FILE = "icon.ico"


class Browser(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"BfMe Searcher v{__version__}")
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        self.resize(900, 820)
        self.game: Game | None = None
        self.panel_a: UnitPanel | None = None  # primary unit
        self.panel_b: UnitPanel | None = None  # comparison unit (optional)
        self.object_browser: ObjectBrowser | None = None  # floating tree above this window
        # The faction ownership graphs, built once per load on a worker the first time the
        # Faction Info card or the browser's By-faction tab wants them; callbacks queue
        # while a build is in flight.
        self._faction_graphs: list | None = None
        self._faction_graphs_loading = False
        self._faction_graph_callbacks: list[tuple] = []
        self._faction_tallies: dict[str, QLabel] = {}
        # Indexed image sources for the inline portraits / button icons (None until loaded),
        # with the parchment portrait background.
        self._texture_source: TextureSource | None = None
        self._portrait_background = default_background()

        # A bare menu-bar action that opens the floating Object Browser window.
        browser_action = self.menuBar().addAction("Browser")
        browser_action.triggered.connect(self._open_object_browser)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel(f"BfMe Searcher  v{__version__}")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        header.addWidget(title)
        header.addStretch(1)
        self.edain_button = QPushButton("Load Edain")
        self.edain_button.setToolTip(
            "Load the Edain mod: BfMe II's ini.big, then RotWK's ini.big, "
            "__edain_data.big and the English patch"
        )
        self.edain_button.clicked.connect(self._load_edain)
        header.addWidget(self.edain_button, 0, Qt.AlignmentFlag.AlignTop)
        self.extract_button = QPushButton("Extract Images")
        self.extract_button.setToolTip(
            "Crop the current unit's command-button icons out of the texture archives"
        )
        self.extract_button.clicked.connect(self._open_extract)
        header.addWidget(self.extract_button, 0, Qt.AlignmentFlag.AlignTop)
        self.theme_button = ThemeToggle()
        self.theme_button.setToolTip("Switch between dark and light mode")
        header.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        self.sources_panel = SourcesPanel(
            title="SOURCES",
            expanded_hint="SOURCES - loaded top to bottom; lower entries override upper",
            item_label=lambda kind, path: f"[{kind}]  {Path(path).name}  -  {path}",
            list_max_height=140,
            show_status=True,
        )
        self.sources_panel.load_requested.connect(self._load)
        self.status = self.sources_panel.status
        root.addWidget(self.sources_panel)

        # Search by raw template name, or by localized display name when toggled on.
        self._object_names: list[str] = []
        self._display_names: list[str] = []
        self._display_index: dict[str, str] = {}
        self.string_search_toggle = QCheckBox("Search by display name")
        self.string_search_toggle.setToolTip(
            "Match objects by their in-game display name instead of their template name"
        )
        self.string_search_toggle.setEnabled(False)
        self.string_search_toggle.toggled.connect(self._on_search_mode_changed)
        root.addWidget(self.string_search_toggle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Load game data to start searching…")
        self.search.setEnabled(False)
        self.search.returnPressed.connect(self._on_enter)
        root.addWidget(self.search)

        # Second search, hidden until a primary unit is selected, to pick a unit to compare.
        self.compare_search = QLineEdit()
        self.compare_search.setPlaceholderText("Compare with another unit…")
        self.compare_search.setVisible(False)
        self.compare_search.returnPressed.connect(self._on_compare_enter)
        root.addWidget(self.compare_search)

        # Back through the UNIT_BUILD trail (a build button opens its target as primary).
        self._nav_stack: list[str] = []
        self.back_button = QPushButton("←  Back")
        self.back_button.setVisible(False)
        self.back_button.clicked.connect(self._navigate_back)
        root.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)

        # Faction Info: a collapsed card pinned above the unit data. Kept in the root
        # layout (not the scroll area) so it pins like SOURCES rather than scrolling away.
        self._root_layout = root
        self.faction_info: QWidget | None = None
        self._faction_body: QWidget | None = None
        self._faction_header: QPushButton | None = None
        self._faction_count = 0

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self.results = QWidget()
        self._results_column = QVBoxLayout(self.results)
        self._results_column.setContentsMargins(0, 0, 0, 0)
        self._results_column.setSpacing(12)
        self._results_column.setAlignment(Qt.AlignmentFlag.AlignTop)

        # The basic-stat comparison sits above the one or two side-by-side unit panels. Its
        # collapsed state is kept here so it survives the card being rebuilt on every change.
        self._comparison_collapsed = False
        self._comparison_body: QWidget | None = None
        self._comparison_header: QPushButton | None = None
        self._compare_box = QVBoxLayout()
        self._compare_box.setSpacing(12)
        self._panels_row = QHBoxLayout()
        self._panels_row.setSpacing(12)
        self._panels_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._results_column.addLayout(self._compare_box)
        self._results_column.addLayout(self._panels_row, 1)

        self._scroll.setWidget(self.results)
        root.addWidget(self._scroll, 1)

        # Restore the saved source list (list only; nothing loads until Load is pressed),
        # falling back to the local dev corpus when there is none.
        saved = load_saved_sources()
        if saved:
            for kind, path in saved:
                self.sources_panel.add_source(kind, path)
        elif Path("data").is_dir():
            self.sources_panel.add_source("folder", str(Path("data").resolve()))
        self._show_initial_state()

    def _open_object_browser(self) -> None:
        """Open (or re-focus) the floating object browser, rebuilt from the current game
        so it reflects the latest load."""
        if self.object_browser is None:
            self.object_browser = ObjectBrowser(self)
        else:
            self.object_browser.rebuild()
        self.object_browser.show()
        self.object_browser.raise_()
        self.object_browser.activateWindow()

    def _open_extract(self) -> None:
        """Open the image extractor for the unit shown in panel A, seeded with its active
        command set buttons."""
        if self.panel_a is None:
            QMessageBox.information(self, "Extract Images", "Show a unit first, then extract.")
            return
        command_set_name, buttons = self.panel_a.command_set_extract()
        # The object's own images (portrait, button icon) lead, then the command set's.
        entries = self.panel_a.object_image_entries() + buttons
        if not entries:
            QMessageBox.information(
                self, "Extract Images", "This unit has no portrait or command-set icons to extract."
            )
            return
        ExtractImageDialog(self.panel_a.header_name(), command_set_name, entries, self).exec()

    def _load_edain(self) -> None:
        """Resolve the installed games and load the Edain mod's .big archives in override
        order (BfMe II base, then RotWK + Edain data + English patch). Its texture
        archives are remembered as the extract-image tool's sources."""
        bfme2 = registry_read_paths_bfme2()
        rotwk = registry_read_paths_rotwk()
        if not bfme2 or not rotwk:
            self.status.setText("Edain load cancelled - a game folder was not selected.")
            return

        archives = [
            Path(bfme2) / "ini.big",
            Path(rotwk) / "ini.big",
            Path(rotwk) / "__edain_data.big",
            Path(rotwk) / "lang" / "englishpatch201.big",
        ]
        # The mod's texture archives feed the inline portraits / button icons and the
        # extract-image tool, so they are remembered under TEXTURE_SOURCES_APP and indexed
        # here rather than added to the data sources.
        textures = [
            Path(rotwk) / "__edain_textures1.big",
            Path(rotwk) / "__edain_textures2.big",
        ]
        missing = [str(p) for p in archives + textures if not p.is_file()]
        if missing:
            QMessageBox.warning(
                self,
                "Missing archives",
                "These Edain archives were not found:\n\n" + "\n".join(missing),
            )
            return

        texture_sources = [("big", str(p)) for p in textures]
        save_sources(texture_sources, TEXTURE_SOURCES_APP)
        self._load_textures(texture_sources)

        self.sources_panel.clear()
        for archive in archives:
            self.sources_panel.add_source("big", str(archive))
        self._load()

    def _load_vanilla(self, label: str) -> None:
        """One-click load of a detected vanilla install: its ini.big plus its language
        archives (for display names), with BfMe II layered beneath RotWK the way the
        engine loads the expansion. Texture archives are remembered as the image sources,
        like the Edain load."""
        installed = detect_installed_games()
        roots: list[Path] = []
        if label == "RotWK" and "BfMe II" in installed:
            roots.append(Path(installed["BfMe II"]))
        if label in installed:
            roots.append(Path(installed[label]))
        data: list[Path] = []
        textures: list[Path] = []
        for root in roots:
            found_data, found_textures = vanilla_archives(root)
            data += found_data
            textures += found_textures
        if not data:
            QMessageBox.warning(
                self,
                "No archives found",
                "No ini.big was found under:\n\n" + "\n".join(str(r) for r in roots),
            )
            return
        if textures:
            texture_sources = [("big", str(p)) for p in textures]
            save_sources(texture_sources, TEXTURE_SOURCES_APP)
            self._load_textures(texture_sources)
        self.sources_panel.clear()
        for archive in data:
            self.sources_panel.add_source("big", str(archive))
        self._load()

    def _load(self) -> None:
        sources = self.sources_panel.sources()
        if not sources:
            self.status.setText("Add at least one folder or .big file first.")
            return
        save_sources(sources)  # remember this list for next launch (no auto-load)
        self.sources_panel.load_button.setEnabled(False)
        self.search.setEnabled(False)
        self.status.setText(f"Loading {len(sources)} source(s)…")
        self._set_message("Loading game data…")
        # Pass the worker's progress signal as the load callback so each source's name
        # appears on the status line as it is read.
        self.loader = Worker(lambda: load_sources(sources, progress=self.loader.progress.emit))
        self.loader.progress.connect(self.status.setText)
        self.loader.done.connect(self._on_loaded)
        self.loader.failed.connect(self._on_failed)
        self.loader.start()

    def ensure_faction_graphs(self, on_ready, on_failed=None) -> None:
        """Hand `on_ready` the faction ownership graphs - immediately when cached, else
        once the background build finishes. Callers queue while a build is in flight, so
        the Faction Info card and the object browser share one build per load."""
        if self.game is None:
            return
        if self._faction_graphs is not None:
            on_ready(self._faction_graphs)
            return
        self._faction_graph_callbacks.append((on_ready, on_failed))
        if self._faction_graphs_loading:
            return
        self._faction_graphs_loading = True
        game = self.game
        run_worker(
            self,
            lambda: (game, build_faction_graphs(game)),
            self._on_faction_graphs,
            self._on_faction_graphs_failed,
        )

    def _on_faction_graphs(self, result) -> None:
        game, graphs = result
        if game is not self.game:
            # A reload superseded this build; leave the queue to the current build.
            return
        self._faction_graphs_loading = False
        self._faction_graphs = graphs
        callbacks, self._faction_graph_callbacks = self._faction_graph_callbacks, []
        for on_ready, _on_failed in callbacks:
            on_ready(graphs)

    def _on_faction_graphs_failed(self, message: str) -> None:
        self._faction_graphs_loading = False
        callbacks, self._faction_graph_callbacks = self._faction_graph_callbacks, []
        self.status.setText(f"Faction roster failed - {message}")
        for _on_ready, on_failed in callbacks:
            if on_failed is not None:
                on_failed(message)

    def _on_loaded(self, result) -> None:
        self.game, names = result
        self._object_names = names
        # A new game invalidates the faction graphs; they rebuild on next demand.
        self._faction_graphs = None
        self._faction_graphs_loading = False
        self._faction_graph_callbacks = []
        self._display_names, self._display_index = display_name_index(self.game, names)
        self.string_search_toggle.setEnabled(True)
        self._rebuild_completers()
        self.search.setEnabled(True)
        self._update_search_placeholder()
        self.search.setFocus()
        self.sources_panel.load_button.setEnabled(True)
        self.status.setText(
            f"Loaded {len(names)} objects from {self.sources_panel.count()} source(s)."
        )
        self.sources_panel.set_collapsed(True)  # collapse once loaded; header re-expands it
        self._build_faction_info()
        if self.object_browser is not None:  # keep the floating tree in step with the load
            self.object_browser.rebuild()
        self._set_message("Start typing to find an object.")
        # Index any remembered image sources so portraits / button icons show without the
        # Edain button (its own load indexes them directly).
        if self._texture_source is None:
            saved_textures = load_saved_sources(TEXTURE_SOURCES_APP)
            if saved_textures:
                self._load_textures(saved_textures)

    def _on_failed(self, message: str) -> None:
        self.sources_panel.load_button.setEnabled(True)
        self.status.setText(f"Load failed - {message}")
        self._set_message("Load failed. Check the sources and try again.")

    def _load_textures(self, sources: list[tuple[str, str]]) -> None:
        """Index the image sources on a worker so the panels can crop portraits and button
        icons out of them; the indexed source is handed to the panels when it is ready."""
        if not sources:
            return
        run_worker(
            self,
            lambda: TextureSource(sources),
            self._on_textures_loaded,
            self._on_textures_failed,
        )

    def _on_textures_loaded(self, source: TextureSource) -> None:
        self._texture_source = source
        for panel in (self.panel_a, self.panel_b):
            if panel is not None:
                panel.apply_textures(self._texture_source, self._portrait_background)

    def _on_textures_failed(self, message: str) -> None:
        # A texture-index failure is non-fatal: the data still loads, just without images.
        self.status.setText(f"Image sources could not be indexed - {message}")

    def _rebuild_completers(self) -> None:
        """Point both search boxes' completers at the active name list (display names or
        template names, per the search mode)."""
        names = self._display_names if self.string_search_toggle.isChecked() else self._object_names
        self.search.setCompleter(make_completer(self, names=names, on_pick=self._pick_primary))
        self.compare_search.setCompleter(
            make_completer(self, names=names, on_pick=self._pick_compare)
        )

    def _resolve(self, text: str) -> str:
        """Map a search term to a raw object name (a no-op in raw-name mode). An unknown
        display name passes through so the "no object" message still names what was searched."""
        if self.string_search_toggle.isChecked():
            return self._display_index.get(text.casefold(), text)
        return text

    def _update_search_placeholder(self) -> None:
        """Set the primary search hint to match the active search mode."""
        count = len(self.game.objects) if self.game else 0
        if self.string_search_toggle.isChecked():
            hint = f"Search {count} objects by display name (e.g. Orc Warrior)…"
        else:
            hint = f"Search {count} objects (e.g. MordorFighter)…"
        self.search.setPlaceholderText(hint)

    def _on_search_mode_changed(self) -> None:
        """Switch the completers between raw-name and display-name search."""
        self._rebuild_completers()
        self.search.clear()
        self.compare_search.clear()
        self._update_search_placeholder()

    def _pick_primary(self, text: str) -> None:
        self.show_object(self._resolve(text))

    def _pick_compare(self, text: str) -> None:
        self.compare_object(self._resolve(text))

    def _active_names(self) -> list[str]:
        """The name list the active search mode matches against (display or template names)."""
        return self._display_names if self.string_search_toggle.isChecked() else self._object_names

    def _object_exists(self, text: str) -> bool:
        """Whether `text` resolves to a loaded object in the active search mode."""
        return bool(self.game) and self.game.objects.get(self._resolve(text)) is not None

    def _on_enter(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        # An exact (or display-name) hit opens straight away; a miss falls back to a typo-
        # tolerant "did you mean" so a sloppy spelling still finds the unit.
        if self._object_exists(text):
            self.show_object(self._resolve(text))
        else:
            matches = closest_names(text, self._active_names())
            self._show_suggestions(text, matches, self._pick_primary)

    def _show_suggestions(self, typed: str, matches: list[str], on_pick) -> None:
        """Replace the results area with a "no match - did you mean" card: one clickable
        button per fuzzy match (each opens via `on_pick`), or a gentle nudge when nothing is
        close enough."""
        self._reset_results()
        self.compare_search.setVisible(False)
        self.back_button.setVisible(False)

        frame, layout = card()
        title = QLabel(f"No unit matched “{typed}”.")
        title.setObjectName("objName")
        title.setWordWrap(True)
        layout.addWidget(title)
        if matches:
            hint = QLabel("Did you mean:")
            hint.setObjectName("muted")
            layout.addWidget(hint)
            for name in matches:
                button = QPushButton(f"{name}  →")
                button.clicked.connect(lambda _=False, n=name: on_pick(n))
                layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            hint = QLabel("Try a different spelling, or pick a hero from Faction Info above.")
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        self._panels_row.addWidget(frame, 0, Qt.AlignmentFlag.AlignTop)

    @staticmethod
    def _empty(layout) -> None:
        clear_layout(layout)

    def _reset_results(self) -> None:
        """Tear down both unit panels and the comparison card."""
        self.panel_a = None
        self.panel_b = None
        self._empty(self._compare_box)
        self._empty(self._panels_row)

    def _set_message(self, text: str) -> None:
        self._reset_results()
        self.compare_search.setVisible(False)
        self.back_button.setVisible(False)
        label = QLabel(text)
        label.setObjectName("muted")
        self._panels_row.addWidget(label)

    def _show_initial_state(self) -> None:
        """The pre-load state: a one-line prompt once sources are queued, otherwise the
        onboarding card (a fresh user with nothing added yet)."""
        if self.sources_panel.count():
            self._set_message("Sources ready - press Load in SOURCES above to read them.")
        else:
            self._set_onboarding()

    def _set_onboarding(self) -> None:
        """A friendly welcome shown when no data is loaded and no sources are queued, instead
        of a bare disabled search box. Detects an installed game to offer one-click Edain
        loading, and otherwise guides the user to add their own folders / .big files."""
        self._reset_results()
        self.compare_search.setVisible(False)
        self.back_button.setVisible(False)

        frame, layout = card()
        title = QLabel("Welcome to BfMe Searcher")
        title.setObjectName("objName")
        layout.addWidget(title)
        intro = QLabel(
            "Look up any unit's stats, compare two side by side, and trace what builds what. "
            "To begin, load some game data:"
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        installed = detect_installed_games()
        if installed:
            found = "; ".join(f"{label} - {path}" for label, path in installed.items())
            note = QLabel(f"Found your install: {found}")
            note.setObjectName("muted")
            note.setWordWrap(True)
            layout.addWidget(note)
            buttons = QHBoxLayout()
            # One click per detected game (RotWK layers BfMe II beneath it automatically);
            # Edain lives in the RotWK folder, so its button appears only when RotWK does.
            for label in installed:
                load_game_button = QPushButton(f"Load {label}")
                load_game_button.clicked.connect(lambda _=False, g=label: self._load_vanilla(g))
                buttons.addWidget(load_game_button)
            if "RotWK" in installed:
                edain = QPushButton("Load Edain")
                edain.setObjectName("primary")
                edain.clicked.connect(self._load_edain)
                buttons.addWidget(edain)
            buttons.addStretch(1)
            layout.addLayout(buttons)
            footer = QLabel("…or add your own folders / .big files in SOURCES above, then Load.")
        else:
            note = QLabel(
                "No Battle for Middle-earth II / RotWK install was detected automatically - "
                "point the tool at your game files instead:"
            )
            note.setObjectName("muted")
            note.setWordWrap(True)
            layout.addWidget(note)
            buttons = QHBoxLayout()
            add_folder = QPushButton("Add data folder…")
            add_folder.clicked.connect(self._onboard_add_folder)
            add_big = QPushButton("Add .big file…")
            add_big.clicked.connect(self._onboard_add_big)
            buttons.addWidget(add_folder)
            buttons.addWidget(add_big)
            buttons.addStretch(1)
            layout.addLayout(buttons)
            footer = QLabel("Add your game's ini.big (or a data folder), then press Load above.")
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self._panels_row.addWidget(frame, 0, Qt.AlignmentFlag.AlignTop)

    def _onboard_add_folder(self) -> None:
        """Add a folder from the onboarding card, then refresh the card to the "ready" state."""
        self.sources_panel.prompt_add_folder()
        self._show_initial_state()

    def _onboard_add_big(self) -> None:
        self.sources_panel.prompt_add_big()
        self._show_initial_state()

    def _build_faction_info(self) -> None:
        """(Re)build the collapsed "Faction Info" card pinned above the unit data, one
        block per playable faction (name, hero links, spellbook link). Rebuilt on each load."""
        if self.faction_info is not None:
            self.faction_info.deleteLater()
            self.faction_info = None
            self._faction_body = None
            self._faction_header = None
        self._faction_tallies = {}
        factions = playable_factions(self.game)
        if not factions:
            return

        frame, layout = card()
        self._faction_header = QPushButton()
        self._faction_header.setObjectName("sectionHeader")
        self._faction_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._faction_header.clicked.connect(self._toggle_faction_info)

        inner = QWidget()
        inner.setStyleSheet("QWidget { background: transparent; }")
        body_layout = QVBoxLayout(inner)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)
        for faction in factions:
            body_layout.addWidget(self._faction_block(faction))

        # The body scrolls within a capped height so expanding never pushes units off-screen.
        self._faction_body = QScrollArea()
        self._faction_body.setWidgetResizable(True)
        self._faction_body.setFrameShape(QFrame.Shape.NoFrame)
        self._faction_body.setMaximumHeight(320)
        self._faction_body.viewport().setStyleSheet("background: transparent;")
        self._faction_body.setStyleSheet("QWidget { background: transparent; }")
        self._faction_body.setWidget(inner)
        self._faction_body.setVisible(False)  # collapsed by default

        self._faction_count = len(factions)
        self._update_faction_header()
        layout.addWidget(self._faction_header)
        layout.addWidget(self._faction_body)

        self.faction_info = frame
        self._root_layout.insertWidget(self._root_layout.indexOf(self._scroll), frame)

    def _update_faction_header(self) -> None:
        arrow = "▾" if self._faction_body.isVisible() else "▸"
        self._faction_header.setText(f"{arrow}  FACTION INFO ({self._faction_count})")

    def _toggle_faction_info(self) -> None:
        self._faction_body.setVisible(not self._faction_body.isVisible())
        self._update_faction_header()
        # First expand kicks the background roster build; the tally lines fill in when done.
        # (`isHidden` reads the visibility flag itself, correct even before the window shows.)
        if not self._faction_body.isHidden() and self._faction_graphs is None:
            for tally in self._faction_tallies.values():
                tally.setText("computing roster…")
            self.ensure_faction_graphs(self._apply_faction_tallies, self._tallies_failed)

    def _apply_faction_tallies(self, graphs) -> None:
        """Fill each faction block's roster line from its built graph."""
        for graph in graphs:
            tally = self._faction_tallies.get(graph.name)
            if tally is None:
                continue
            parts = [
                f"{len(graph.structures)} structures",
                f"{len(graph.units)} units",
                f"{len(graph.heroes)} heroes",
                f"{len(graph.upgrades)} upgrades",
            ]
            if graph.spellbook is not None and graph.spellbook.powers:
                parts.append(f"{len(graph.spellbook.powers)} powers")
            tally.setText("  ·  ".join(parts))

    def _tallies_failed(self, _message: str) -> None:
        for tally in self._faction_tallies.values():
            tally.setText("")

    def _collapse_faction_info(self) -> None:
        """Collapse the section (used after one of its links is followed)."""
        if self._faction_body is not None and self._faction_body.isVisible():
            self._faction_body.setVisible(False)
            self._update_faction_header()

    def _faction_block(self, faction: dict) -> QWidget:
        """One faction's block: name + roster tally (filled from the ownership graph once
        it is built), the spellbook link, its heroes collapsed under one toggle, and a
        link into the object browser's By-faction drill-down."""
        block = QWidget()
        block.setStyleSheet("QWidget { background: transparent; }")
        column = QVBoxLayout(block)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        header = QHBoxLayout()
        name = QLabel(faction["display"])
        name.setObjectName("objName")
        header.addWidget(name)
        header.addStretch(1)
        browse = QPushButton("Browse roster  →")
        browse.setToolTip("Open this faction in the Object Browser's By-faction view")
        browse.clicked.connect(lambda _=False, d=faction["display"]: self._browse_faction(d))
        header.addWidget(browse)
        column.addLayout(header)

        tally = QLabel("")
        tally.setObjectName("muted")
        tally.setWordWrap(True)
        self._faction_tallies[faction["name"]] = tally
        column.addWidget(tally)
        if self._faction_graphs is not None:  # card rebuilt with the graphs already cached
            self._apply_faction_tallies(self._faction_graphs)

        if faction["spellbook"]:
            column.addWidget(self._faction_nav_button(faction["spellbook"], prefix="Spellbook: "))

        if faction["heroes"]:
            # All heroes under one collapsible section, collapsed by default - an Edain
            # faction lists a dozen, which otherwise dominates the card.
            toggle = QPushButton()
            toggle.setObjectName("sectionHeader")
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            grid_wrap = QWidget()
            grid = QGridLayout(grid_wrap)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(6)
            for i, hero in enumerate(faction["heroes"]):
                grid.addWidget(self._faction_nav_button(hero), i // 3, i % 3)
            grid_wrap.setVisible(False)
            hero_count = len(faction["heroes"])

            # `isHidden` reads the visibility flag itself, so the arrow and the flip are
            # right even while the window is not yet shown.
            def update_toggle(wrap=grid_wrap, button=toggle, count=hero_count):
                arrow = "▾" if not wrap.isHidden() else "▸"
                button.setText(f"{arrow}  Heroes ({count})")

            def flip(_=False, wrap=grid_wrap, refresh=update_toggle):
                wrap.setVisible(wrap.isHidden())
                refresh()

            toggle.clicked.connect(flip)
            update_toggle()
            column.addWidget(toggle)
            column.addWidget(grid_wrap)
        return block

    def _browse_faction(self, display: str) -> None:
        """Jump from a Faction Info block into the object browser's By-faction view."""
        self._collapse_faction_info()
        self._open_object_browser()
        self.object_browser.focus_faction(display)

    def _faction_nav_button(self, name: str, *, prefix: str = "") -> QPushButton:
        """A link that opens `name` as the primary unit (disabled when not loaded)."""
        obj = self.game.objects.get(name)
        label = display_name(self.game, obj) if obj is not None else None
        button = QPushButton(f"{prefix}{label or name}  →")
        if obj is None:
            button.setEnabled(False)
            button.setToolTip(f"{name} is not loaded")
        else:
            button.clicked.connect(lambda _=False, n=name: self._open_from_faction(n))
        return button

    def _open_from_faction(self, name: str) -> None:
        """Follow a Faction Info link: collapse the section, then open the object."""
        self._collapse_faction_info()
        self.show_object(name)

    def _make_panel(self, obj, *, removable: bool) -> "UnitPanel":
        panel = UnitPanel(
            self.game,
            obj,
            removable=removable,
            texture_source=self._texture_source,
            portrait_background=self._portrait_background,
        )
        panel.changed.connect(self._refresh_comparison)
        panel.navigate.connect(self._navigate_to)
        return panel

    def _fill_search(self, line_edit: QLineEdit, name: str) -> None:
        """Reflect a programmatic selection in a search box, using the text the active
        search mode expects (the display name when searching by display name, else the
        raw name). A no-op for an unknown object so the box is not cleared spuriously."""
        if not self.game or not name or self.game.objects.get(name) is None:
            return
        text = name
        if self.string_search_toggle.isChecked():
            obj = self.game.objects.get(name)
            text = display_name(self.game, obj) or name
        line_edit.setText(text)

    def show_object(self, name: str) -> None:
        """Select the primary unit (panel A); a fresh search drops the build trail."""
        self._nav_stack = []
        self._fill_search(self.search, name)
        self._open_object(name)

    def _open_object(self, name: str) -> None:
        """Show `name` as the primary unit (panel A); resets any comparison unit."""
        if not self.game or not name:
            return
        obj = self.game.objects.get(name)
        if obj is None:
            self._set_message(f"No object named “{name}”.")
            return
        self._reset_results()
        self.panel_a = self._make_panel(obj, removable=False)
        self._panels_row.addWidget(self.panel_a, 1)

        # Offer a second unit for comparison now that a primary one is shown.
        self.compare_search.setVisible(True)
        self.compare_search.clear()
        self.compare_search.setEnabled(True)
        self.compare_search.setPlaceholderText("Compare with another unit…")
        self.back_button.setVisible(bool(self._nav_stack))
        self._refresh_comparison()

    def _navigate_to(self, name: str) -> None:
        """Open a UNIT_BUILD target, remembering the current unit for Back."""
        if not self.game or not name or self.game.objects.get(name) is None:
            return
        if self.panel_a is not None:
            self._nav_stack.append(self.panel_a._current_obj.name)
        self._open_object(name)

    def _navigate_back(self) -> None:
        """Return to the unit the current one was built from."""
        if not self._nav_stack:
            return
        self._open_object(self._nav_stack.pop())

    def compare_object(self, name: str) -> None:
        """Select the comparison unit (panel B), shown beside panel A."""
        if not self.game or not name or self.panel_a is None:
            return
        obj = self.game.objects.get(name)
        if obj is None:
            return
        self._fill_search(self.compare_search, name)
        if self.panel_b is not None:
            self._panels_row.removeWidget(self.panel_b)
            self.panel_b.deleteLater()
        # Mirror panel A so the two units' stat columns meet in the middle (A: aux | stats,
        # B: stats | aux).
        self.panel_a.set_mirrored(True)
        self.panel_b = self._make_panel(obj, removable=True)
        self.panel_b.closed.connect(self._remove_comparison)
        self._panels_row.addWidget(self.panel_b, 1)
        self._grow_for_comparison()
        self._refresh_comparison()

    def _remove_comparison(self) -> None:
        """Drop panel B and its comparison, leaving the primary unit shown."""
        if self.panel_b is not None:
            self._panels_row.removeWidget(self.panel_b)
            self.panel_b.deleteLater()
            self.panel_b = None
        if self.panel_a is not None:
            self.panel_a.set_mirrored(False)  # back to the stats-then-aux layout
        self.compare_search.clear()
        self._refresh_comparison()

    def _grow_for_comparison(self) -> None:
        """Widen the window so four columns fit, the first time a comparison opens."""
        if self.width() < 1320:
            self.resize(1320, self.height())

    def _on_compare_enter(self) -> None:
        text = self.compare_search.text().strip()
        if self.panel_a is None or not text:
            return
        if self._object_exists(text):
            self.compare_object(self._resolve(text))
            return
        # The comparison slot can't host the suggestion card (panel A is showing), so the
        # closest matches go to the status line as a typo nudge.
        matches = closest_names(text, self._active_names())
        if matches:
            self.status.setText(f"No unit matched “{text}”. Closest: {', '.join(matches[:3])}")
        else:
            self.status.setText(f"No unit matched “{text}”.")

    def _refresh_comparison(self) -> None:
        """(Re)build the basic-stat comparison whenever either panel changes. Each row pairs
        the two units' value for one headline stat, the more favourable side coloured green
        (favourable following each stat's own sense). A final "time to defeat" row pits each
        unit's DPS against the other's effective health."""
        self._empty(self._compare_box)
        self._comparison_body = None
        self._comparison_header = None
        if self.panel_a is None or self.panel_b is None:
            return

        a_stats = self.panel_a.basic_stats()
        b_stats = self.panel_b.basic_stats()
        # A clickable header collapses the card; its state is remembered across rebuilds.
        compare_card, layout = card()
        self._comparison_header = QPushButton()
        self._comparison_header.setObjectName("sectionHeader")
        self._comparison_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._comparison_header.clicked.connect(self._toggle_comparison)
        layout.addWidget(self._comparison_header)

        self._comparison_body = QWidget()
        self._comparison_body.setStyleSheet("QWidget { background: transparent; }")
        body_layout = QVBoxLayout(self._comparison_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        layout = body_layout

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(4)
        for col, text in enumerate(
            ("Stat", self.panel_a.header_name(), self.panel_b.header_name())
        ):
            head = QLabel(text)
            head.setObjectName("colhead")
            if col:
                head.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(head, 0, col)

        for row, ((label, a_val, higher), (_label, b_val, _higher)) in enumerate(
            zip(a_stats, b_stats, strict=True), start=1
        ):
            grid.addWidget(QLabel(label), row, 0)
            a_name, b_name = self._compare_names(a_val, b_val, higher)
            for col, (value, name) in enumerate(((a_val, a_name), (b_val, b_name)), start=1):
                cell = QLabel(fmt_stat(value))
                cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                if name:
                    cell.setObjectName(name)
                grid.addWidget(cell, row, col)

        # Time to defeat: each unit's DPS against the *other's* effective health for that
        # damage type, lower is better.
        ttk_row = len(a_stats) + 1
        a_ttk = self._time_to_defeat(self.panel_a, self.panel_b)
        b_ttk = self._time_to_defeat(self.panel_b, self.panel_a)
        grid.addWidget(QLabel("Time to defeat (s)"), ttk_row, 0)
        a_name, b_name = self._compare_names(a_ttk, b_ttk, higher_is_better=False)
        for col, (value, name) in enumerate(((a_ttk, a_name), (b_ttk, b_name)), start=1):
            cell = QLabel(fmt_stat(value))
            cell.setAlignment(Qt.AlignmentFlag.AlignRight)
            if name:
                cell.setObjectName(name)
            grid.addWidget(cell, ttk_row, col)

        grid.setColumnStretch(0, 1)
        wrap = QWidget()
        wrap.setLayout(grid)
        layout.addWidget(wrap)

        compare_card.layout().addWidget(self._comparison_body)
        self._comparison_body.setVisible(not self._comparison_collapsed)
        self._update_comparison_header()
        self._compare_box.addWidget(compare_card)

    def _toggle_comparison(self) -> None:
        """Collapse/expand the comparison card, remembering the state for later rebuilds."""
        self._comparison_collapsed = not self._comparison_collapsed
        if self._comparison_body is not None:
            self._comparison_body.setVisible(not self._comparison_collapsed)
        self._update_comparison_header()

    def _update_comparison_header(self) -> None:
        if self._comparison_header is None:
            return
        arrow = "▸" if self._comparison_collapsed else "▾"
        self._comparison_header.setText(f"{arrow}  COMPARISON")

    @staticmethod
    def _time_to_defeat(attacker: "UnitPanel", target: "UnitPanel") -> float | None:
        """Seconds for `attacker` to kill `target`: the target's effective health
        against the attacker's damage type, divided by the attacker's DPS. None
        when the attacker deals no damage or the target is immune to that type."""
        profile = attacker._attack_profile()
        if profile is None or not profile[0]:
            return None
        ehp = target.effective_health_vs(profile[1])
        return None if ehp is None else ehp / profile[0]

    @staticmethod
    def _compare_names(a_val, b_val, higher_is_better: bool) -> tuple[str, str]:
        """The (panel-A, panel-B) style names colouring the favourable side green. Equal or
        unknown values are left neutral."""
        if a_val is None or b_val is None or a_val == b_val:
            return "", ""
        a_better = (a_val > b_val) if higher_is_better else (a_val < b_val)
        return ("better", "worse") if a_better else ("worse", "better")
