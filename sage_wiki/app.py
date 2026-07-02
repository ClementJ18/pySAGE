"""Desktop UI to update Edain wiki infoboxes from parsed game data: load sources, name a
page, log in, generate the diff between its infobox and the object's stats, and apply it.
A category run automates that loop over the pages shared by one or more categories.
Loading and network calls run on background threads.

Run with `sage-wiki` (installed with the `wiki` extra) or `python -m sage_wiki.app`.
"""

from PyQt6.QtCore import QStringListModel, Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QCheckBox,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from sage_utils.sources import load_saved_sources, load_sources, save_sources
from sage_utils.textures import (
    TextureSource,
    default_background,
)
from sage_utils.widgets import (
    SourcesPanel,
    Worker,
    card,
    make_completer,
    resource_path,
    run_app,
    run_worker,
)
from sage_wiki import __version__
from sage_wiki.cards.category_card import CategoryRunMixin
from sage_wiki.cards.diff_card import DiffReviewMixin
from sage_wiki.cards.images_card import ImagesCardMixin
from sage_wiki.cards.pagegen_card import PagegenCardMixin
from sage_wiki.cards.tools_card import ToolDialogsMixin
from sage_wiki.diff import (
    FieldChange,
)
from sage_wiki.meta import APP_NAME, APP_TITLE, ICON_FILE, TEXTURE_SOURCES_APP
from sage_wiki.wiki import WikiClient


class WikiUpdater(
    PagegenCardMixin,
    CategoryRunMixin,
    ToolDialogsMixin,
    ImagesCardMixin,
    DiffReviewMixin,
    QMainWindow,
):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        self.resize(1700, 1040)
        self.game = None
        self.client = WikiClient()
        self._linker = None  # validated wiki-link resolver, built lazily per loaded game
        self._linker_game = None
        self._texture_source: TextureSource | None = None  # indexed image sources
        self._portrait_background = default_background()  # parchment behind portraits
        # The object the images card currently shows, so auto-load skips redundant reloads.
        self._images_loaded_for: str | None = None
        self._changes: list[FieldChange] = []
        self._workers: set[Worker] = set()
        # Page-generation upgrade toggles, and the object they were built for (so the list
        # rebuilds only when the object changes).
        self.pagegen_upgrade_toggles: dict[str, QCheckBox] = {}
        self._pagegen_upgrades_obj: str | None = None
        # The version-template values last fetched, so Apply writes only changed ones.
        self._version_baseline: dict[str, str] = {}
        # Category run state. The Pages list is the live queue; `_batch_current` is the
        # title under review (tracked by title, not index, so edits to the queue stay correct).
        self._batch_running = False
        self._batch_current: str | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel(f"{APP_TITLE}  v{__version__}")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        root.addWidget(title)

        # Three columns (update workflow / editable wikitext / image+page tools), each a
        # vertical splitter of cards, all under one horizontal splitter — so every column
        # boundary and every card boundary can be dragged to taste. The whole thing sits in
        # a scroll area so it still scrolls when squeezed below the cards' minimum sizes.
        columns = QSplitter(Qt.Orientation.Horizontal)
        columns.setChildrenCollapsible(False)
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body_scroll.setWidget(columns)
        root.addWidget(body_scroll, 1)

        left = self._build_column(
            self._build_sources_card(),
            self._build_object_card(),
            self._build_category_card(),
            self._build_diff_card(),
            grow=3,  # the changes table takes the slack
        )
        middle = self._build_column(self._build_wikitext_card(), grow=0)
        right = self._build_column(
            self._build_images_card(),
            self._build_pagegen_card(),
            grow=1,  # the generated draft takes the slack
        )
        for column in (left, middle, right):
            columns.addWidget(column)
        columns.setSizes([560, 560, 560])

        # Armor sets, version templates and wiki login are infrequent; they live in their
        # own dialogs opened from the menu bar rather than crowding a column.
        self.login_dialog = self._tool_dialog("Wiki Login", self._build_login_card())
        self.armor_dialog = self._tool_dialog("Armor Sets", self._build_armorsets_card())
        self.versions_dialog = self._tool_dialog("Version Templates", self._build_versions_card())
        self.armor_body.setVisible(True)  # always expanded inside their own dialogs
        self.versions_body.setVisible(True)
        self._update_armor_header()
        self._update_versions_header()
        self._build_menu()

        self.status = QLabel("Add data sources and Load to begin.")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

        for kind, path in load_saved_sources(APP_NAME):
            self.sources_panel.add_source(kind, path)
        for kind, path in load_saved_sources(TEXTURE_SOURCES_APP):
            self.image_sources_panel.add_source(kind, path)

    def _build_column(self, *cards: QWidget, grow: int) -> QSplitter:
        """A vertical splitter stacking `cards`; the card at index `grow` is given the slack
        so it expands when the window grows (matching the old stretch-factor layout)."""
        column = QSplitter(Qt.Orientation.Vertical)
        column.setChildrenCollapsible(False)
        for card_widget in cards:
            column.addWidget(card_widget)
        column.setStretchFactor(grow, 1)
        return column

    def _tool_dialog(self, title: str, widget: QWidget) -> QDialog:
        """A non-modal dialog wrapping a tool `widget`, opened from the menu bar. Held on
        the window so it keeps its state (and entered values) between openings."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(widget)
        return dialog

    def _build_menu(self) -> None:
        # Each tool is its own top-level menu-bar entry rather than nested under a Tools menu.
        menu_bar = self.menuBar()
        for label, dialog in (
            ("Wiki &Login", self.login_dialog),
            ("&Armor Sets", self.armor_dialog),
            ("&Version Templates", self.versions_dialog),
        ):
            menu_bar.addAction(label, lambda _=False, d=dialog: self._open_dialog(d))

    def _open_dialog(self, dialog: QDialog) -> None:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _build_sources_card(self) -> QWidget:
        self.sources_panel = SourcesPanel(title="DATA SOURCES", list_min_height=170)
        self.sources_panel.load_requested.connect(self._load)
        # Collapsing/expanding the panel moves its splitter handle so the freed (or needed)
        # space goes to the column's growing card rather than leaving a gap.
        self.sources_panel.collapsed_changed.connect(
            lambda _: self._adjust_splitter_for_panel(self.sources_panel)
        )
        return self.sources_panel

    def _set_card_collapsed(self, frame, body, collapsed: bool, update_header) -> None:
        """Collapse/expand a card: hide its body, cap the frame to its header when collapsed
        (so a parent splitter shrinks it instead of leaving a gap), refresh the header, and
        move the splitter handle to hand the freed/needed space to a neighbour."""
        body.setVisible(not collapsed)
        frame.setMaximumHeight(frame.sizeHint().height() if collapsed else QWIDGETSIZE_MAX)
        update_header()
        self._adjust_splitter_for_panel(frame)

    def _adjust_splitter_for_panel(self, panel: QWidget) -> None:
        """Move the splitter handle above/below `panel` after it collapses or expands, handing
        the size change to a neighbouring card. Prefers an expandable (uncapped) neighbour over
        another collapsed one — donating to a collapsed card would just leave the gap. A no-op
        when the panel isn't a direct child of a splitter (e.g. one nested in a plain layout)."""
        splitter = panel.parentWidget()
        if not isinstance(splitter, QSplitter):
            return
        sizes = splitter.sizes()
        index = splitter.indexOf(panel)
        delta = sizes[index] - panel.sizeHint().height()
        others = [i for i in range(len(sizes)) if i != index]
        if delta == 0 or not others:
            return
        expandable = [i for i in others if splitter.widget(i).maximumHeight() >= QWIDGETSIZE_MAX]
        grow = max(expandable or others, key=lambda i: sizes[i])
        sizes[index] -= delta
        sizes[grow] = max(1, sizes[grow] + delta)
        splitter.setSizes(sizes)

    def _load(self) -> None:
        sources = self.sources_panel.sources()
        if not sources:
            self.status.setText("Add at least one folder or .big file first.")
            return
        save_sources(sources, APP_NAME)
        self.sources_panel.load_button.setEnabled(False)
        self.status.setText(f"Loading {len(sources)} source(s)…")
        self._run(lambda: load_sources(sources), self._on_loaded, self._on_load_failed)

    def _on_loaded(self, result) -> None:
        self.game, names = result
        self.object_search.setEnabled(True)
        self.object_search.setPlaceholderText(f"(optional) override object — {len(names)} loaded")
        names_model = QStringListModel(names, self)
        for field in (self.object_search, self.pagegen_object, self.portrait_object_search):
            field.setCompleter(make_completer(self, model=names_model))
        self.portrait_object_search.setEnabled(True)
        # The command-set searchbox completes over the loaded command-set names.
        self.commandset_search.setCompleter(
            make_completer(self, names=sorted(self.game.commandsets))
        )
        self.commandset_search.setEnabled(True)
        self.sources_panel.load_button.setEnabled(True)
        self.sources_panel.set_collapsed(True)  # free up room now that sources are loaded
        self.status.setText(f"Loaded {len(names)} objects.")

    def _on_load_failed(self, message: str) -> None:
        self.sources_panel.load_button.setEnabled(True)
        self.status.setText(f"Load failed — {message}")

    def _build_object_card(self) -> QWidget:
        frame, layout = card("Page and object")
        # The page is the primary input — its infobox names the object to use.
        self.page_field = QLineEdit()
        self.page_field.setPlaceholderText("Wiki page title (e.g. Gondor Soldiers)")
        self.page_field.returnPressed.connect(self._generate_diff)
        layout.addWidget(self.page_field)

        # Optional: type an object to override the one the page would pick. Also
        # shows which object a generated diff resolved to.
        self.object_search = QLineEdit()
        self.object_search.setPlaceholderText("Load a source first…")
        self.object_search.setEnabled(False)
        layout.addWidget(self.object_search)

        self.diff_button = QPushButton("Generate diff")
        self.diff_button.setObjectName("primary")
        self.diff_button.clicked.connect(self._generate_diff)
        layout.addWidget(self.diff_button)
        return frame

    def _run(self, fn, on_done, on_failed) -> None:
        run_worker(self, fn, on_done, on_failed)


def main() -> None:
    run_app(WikiUpdater, icon_file=ICON_FILE, anchor=__file__, app_name=APP_TITLE)


if __name__ == "__main__":
    main()
