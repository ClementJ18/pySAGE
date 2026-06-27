"""Desktop UI to update Edain wiki infoboxes from parsed game data: load sources, name a
page, log in, generate the diff between its infobox and the object's stats, and apply it.
A category run automates that loop over the pages shared by one or more categories.
Loading and network calls run on background threads.

Run from the repo root:
    .venv/Scripts/python sage_wiki/app.py
"""

import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from PyQt6.QtCore import QStringListModel, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QWIDGETSIZE_MAX,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_utils.sources import load_saved_sources, load_sources, save_sources  # noqa: E402
from sage_utils.textures import (  # noqa: E402
    TextureSource,
    ability_overlay,
    default_background,
)
from sage_utils.widgets import (  # noqa: E402
    SourcesPanel,
    Worker,
    card,
    make_completer,
    resource_path,
    run_app,
    run_worker,
)
from sage_wiki import __version__  # noqa: E402
from sage_wiki.armorsets import armor_sections_by_page, merge_page  # noqa: E402
from sage_wiki.credentials import (  # noqa: E402
    delete_password,
    load_password,
    load_username,
    save_password,
    save_username,
)
from sage_wiki.diff import (  # noqa: E402
    FieldChange,
    apply_all,
    diff_infobox,
    resolve_object,
    resolve_objects,
)
from sage_wiki.images import (  # noqa: E402
    IMAGE_PARAM,
    command_set_icon_rows,
    filename_from_value,
    icon_filename,
    object_command_icon_rows,
    portrait_filename,
    render_icon_png,
    render_portrait_png,
)
from sage_wiki.infobox import parse_infobox, parse_infoboxes  # noqa: E402
from sage_wiki.links import build_linker  # noqa: E402
from sage_wiki.pagegen import (  # noqa: E402
    ability_overlay_kind,
    available_upgrades,
    button_ability_block,
    generate_page,
)
from sage_wiki.versions import VERSION_TEMPLATES, extract_version, replace_version  # noqa: E402
from sage_wiki.wiki import WikiClient, WikiError  # noqa: E402

APP_NAME = "sage_wiki"  # settings key (saved sources / username); not the display name
# Texture sources are remembered under their own key, separate from the data sources.
TEXTURE_SOURCES_APP = "sage_wiki_textures"
APP_TITLE = "Edain Wiki Assistant"
ICON_FILE = "icon.ico"


class WikiUpdater(QMainWindow):
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

    def _build_pagegen_card(self) -> QWidget:
        # Builds a brand-new page draft from an object (preview only, never saved).
        frame, layout = card()
        self.pagegen_frame = frame
        self.pagegen_toggle = QPushButton()
        self.pagegen_toggle.setObjectName("sectionHeader")
        self.pagegen_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pagegen_toggle.clicked.connect(self._toggle_pagegen)
        layout.addWidget(self.pagegen_toggle)

        self.pagegen_body = QWidget()
        body = QVBoxLayout(self.pagegen_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        note = QLabel(
            "Scaffold a whole new page from an object — infobox, abilities, upgrade "
            "hints, navbox and category. Review and copy the draft; nothing is saved."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        body.addWidget(note)

        row = QHBoxLayout()
        self.pagegen_object = QLineEdit()
        self.pagegen_object.setPlaceholderText("Object to generate (e.g. GondorImrahil)")
        self.pagegen_object.returnPressed.connect(self._generate_page)
        self.pagegen_object.editingFinished.connect(self._refresh_pagegen_upgrades)
        self.pagegen_faction = QLineEdit()
        self.pagegen_faction.setPlaceholderText("Faction (e.g. Gondor)")
        row.addWidget(self.pagegen_object, 2)
        row.addWidget(self.pagegen_faction, 1)
        self.pagegen_button = QPushButton("Generate page")
        self.pagegen_button.setObjectName("primary")
        self.pagegen_button.clicked.connect(self._generate_page)
        row.addWidget(self.pagegen_button)
        body.addLayout(row)

        # Optional upgrade toggles: generate the object as it is after taking them. The list
        # is its own collapsible section, hidden until the object has upgrades and collapsed
        # by default so it stays out of the way.
        self.pagegen_upgrades_toggle = QPushButton()
        self.pagegen_upgrades_toggle.setObjectName("sectionHeader")
        self.pagegen_upgrades_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pagegen_upgrades_toggle.clicked.connect(self._toggle_pagegen_upgrades)
        self.pagegen_upgrades_toggle.setVisible(False)
        body.addWidget(self.pagegen_upgrades_toggle)

        self.pagegen_upgrades_area = QScrollArea()
        self.pagegen_upgrades_area.setWidgetResizable(True)
        self.pagegen_upgrades_area.setMinimumHeight(150)
        self.pagegen_upgrades_area.setMaximumHeight(240)
        self.pagegen_upgrades_area.setVisible(False)  # collapsed by default
        container = QWidget()
        self.pagegen_upgrades_layout = QVBoxLayout(container)
        self.pagegen_upgrades_layout.setContentsMargins(4, 4, 4, 4)
        self.pagegen_upgrades_layout.setSpacing(2)
        self.pagegen_upgrades_area.setWidget(container)
        body.addWidget(self.pagegen_upgrades_area)

        self.pagegen_preview = QPlainTextEdit()
        self.pagegen_preview.setPlaceholderText("The generated wikitext appears here.")
        self.pagegen_preview.setMinimumHeight(220)
        self.pagegen_preview.setFont(QFont("Consolas", 9))
        body.addWidget(self.pagegen_preview)

        copy_row = QHBoxLayout()
        self.pagegen_status = QLabel("")
        self.pagegen_status.setObjectName("muted")
        copy_row.addWidget(self.pagegen_status, 1)
        self.pagegen_copy = QPushButton("Copy")
        self.pagegen_copy.clicked.connect(self._copy_page)
        copy_row.addWidget(self.pagegen_copy)
        body.addLayout(copy_row)

        layout.addWidget(self.pagegen_body)
        self.pagegen_body.setVisible(True)  # expanded by default
        self._update_pagegen_header()
        return frame

    def _toggle_pagegen(self) -> None:
        self._set_card_collapsed(
            self.pagegen_frame,
            self.pagegen_body,
            self.pagegen_body.isVisible(),
            self._update_pagegen_header,
        )

    def _update_pagegen_header(self) -> None:
        # `isHidden()` reflects the visibility flag even before show, so the arrow is right
        # for an expanded-by-default card at construction.
        arrow = "▾" if not self.pagegen_body.isHidden() else "▸"
        self.pagegen_toggle.setText(f"{arrow}  GENERATE PAGE")

    def _toggle_pagegen_upgrades(self) -> None:
        self.pagegen_upgrades_area.setVisible(not self.pagegen_upgrades_area.isVisible())
        self._update_pagegen_upgrades_header()

    def _update_pagegen_upgrades_header(self) -> None:
        arrow = "▾" if self.pagegen_upgrades_area.isVisible() else "▸"
        count = len(self.pagegen_upgrade_toggles)
        suffix = f" ({count})" if count else ""
        self.pagegen_upgrades_toggle.setText(f"{arrow}  ACTIVE UPGRADES (OPTIONAL){suffix}")

    def _refresh_pagegen_upgrades(self) -> None:
        """Rebuild the object's upgrade toggles, but only when the object changed (so the
        user's selections survive the focus-out events this fires on)."""
        name = self.pagegen_object.text().strip()
        if name == self._pagegen_upgrades_obj:
            return
        self._pagegen_upgrades_obj = name
        self.pagegen_upgrade_toggles.clear()
        while self.pagegen_upgrades_layout.count():
            widget = self.pagegen_upgrades_layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()

        obj = self.game.objects.get(name) if (self.game and name) else None
        upgrades = available_upgrades(obj) if obj is not None else []
        for upgrade in upgrades:
            toggle = QCheckBox(upgrade)
            self.pagegen_upgrades_layout.addWidget(toggle)
            self.pagegen_upgrade_toggles[upgrade] = toggle
        has_upgrades = bool(upgrades)
        self.pagegen_upgrades_toggle.setVisible(has_upgrades)
        self.pagegen_upgrades_area.setVisible(False)  # re-collapse for the new object
        self._update_pagegen_upgrades_header()
        self._auto_load_images(obj)  # fill its images when textures are loaded

    def _page_linker(self):
        """A wiki-link resolver for the loaded game, built once per game from the wiki's
        article titles and cached. Returns None when the titles can't be fetched (e.g. offline),
        so page generation falls back to plain unlinked text rather than failing."""
        if self.game is None:
            return None
        if self._linker is None or self._linker_game is not self.game:
            try:
                titles = self.client.all_titles()
            except WikiError:
                return None
            self._linker = build_linker(self.game, titles)
            self._linker_game = self.game
        return self._linker

    def _generate_page(self) -> None:
        if self.game is None:
            self.pagegen_status.setText("Load a data source first.")
            return
        name = self.pagegen_object.text().strip()
        obj = self.game.objects.get(name) if name else None
        if obj is None:
            self.pagegen_status.setText(f"Object “{name}” is not loaded.")
            return
        self._refresh_pagegen_upgrades()  # ensure toggles match the current object
        faction = self.pagegen_faction.text().strip()
        active = frozenset(
            upgrade
            for upgrade, toggle in self.pagegen_upgrade_toggles.items()
            if toggle.isChecked()
        )
        self.pagegen_preview.setPlainText(
            generate_page(self.game, obj, faction, active, self._page_linker())
        )
        detail = f" with {len(active)} upgrade(s)" if active else ""
        self.pagegen_status.setText(f"Generated draft for {obj.name}{detail}.")
        self._auto_load_images(obj)  # fill the portrait/icons when textures are loaded

    def _copy_page(self) -> None:
        text = self.pagegen_preview.toPlainText()
        if not text:
            self.pagegen_status.setText("Nothing to copy — generate a page first.")
            return
        QApplication.clipboard().setText(text)
        self.pagegen_status.setText("Copied to clipboard.")

    def _build_category_card(self) -> QWidget:
        frame, layout = card()
        self.category_frame = frame
        self.category_toggle = QPushButton()
        self.category_toggle.setObjectName("sectionHeader")
        self.category_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.category_toggle.clicked.connect(self._toggle_category)
        layout.addWidget(self.category_toggle)

        self.category_body = QWidget()
        body = QVBoxLayout(self.category_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        self.category_field = QLineEdit()
        self.category_field.setPlaceholderText(
            "(optional) categories to walk, comma-separated (e.g. Gondor units, Heroes)"
        )
        self.category_field.returnPressed.connect(self._run_category)
        body.addWidget(self.category_field)

        row = QHBoxLayout()
        self.category_button = QPushButton("Run category")
        self.category_button.clicked.connect(self._run_category)
        row.addWidget(self.category_button)
        row.addStretch(1)
        body.addLayout(row)

        self.category_status = QLabel("")
        self.category_status.setObjectName("muted")
        self.category_status.setWordWrap(True)
        body.addWidget(self.category_status)

        body.addWidget(self._build_category_pages_section())

        layout.addWidget(self.category_body)
        self.category_body.setVisible(True)  # expanded by default
        self._update_category_header()
        return frame

    def _toggle_category(self) -> None:
        self._set_card_collapsed(
            self.category_frame,
            self.category_body,
            self.category_body.isVisible(),
            self._update_category_header,
        )

    def _update_category_header(self) -> None:
        arrow = "▾" if not self.category_body.isHidden() else "▸"
        self.category_toggle.setText(f"{arrow}  CATEGORY RUN")

    def _build_category_pages_section(self) -> QWidget:
        # The live list of pages the run walks; the walk follows edits to it.
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.category_pages_toggle = QPushButton()
        self.category_pages_toggle.setObjectName("sectionHeader")
        self.category_pages_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.category_pages_toggle.clicked.connect(self._toggle_category_pages)
        layout.addWidget(self.category_pages_toggle)

        self.category_pages_body = QWidget()
        body = QVBoxLayout(self.category_pages_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        note = QLabel(
            "Pages the run walks. Remove ones to skip or add extra titles; the walk "
            "follows this list and keeps the page under review highlighted."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        body.addWidget(note)

        self.category_pages_list = QListWidget()
        self.category_pages_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.category_pages_list.setMinimumHeight(140)
        self.category_pages_list.setMaximumHeight(260)
        self.category_pages_list.itemDoubleClicked.connect(self._load_category_page)
        body.addWidget(self.category_pages_list)

        add_row = QHBoxLayout()
        self.category_add_field = QLineEdit()
        self.category_add_field.setPlaceholderText("Add a page title…")
        self.category_add_field.returnPressed.connect(self._add_category_page)
        add_row.addWidget(self.category_add_field, 1)
        self.category_add_button = QPushButton("Add")
        self.category_add_button.clicked.connect(self._add_category_page)
        add_row.addWidget(self.category_add_button)
        self.category_remove_button = QPushButton("Remove selected")
        self.category_remove_button.clicked.connect(self._remove_category_pages)
        add_row.addWidget(self.category_remove_button)
        body.addLayout(add_row)

        layout.addWidget(self.category_pages_body)
        self.category_pages_body.setVisible(False)  # collapsed by default
        self._update_category_pages_header()
        return wrap

    def _toggle_category_pages(self) -> None:
        self.category_pages_body.setVisible(not self.category_pages_body.isVisible())
        self._update_category_pages_header()

    def _update_category_pages_header(self) -> None:
        arrow = "▾" if self.category_pages_body.isVisible() else "▸"
        count = self.category_pages_list.count()
        suffix = f" ({count})" if count else ""
        self.category_pages_toggle.setText(f"{arrow}  PAGES{suffix}")

    @property
    def _batch_active(self) -> bool:
        return self._batch_running

    def _category_titles(self) -> list[str]:
        """The page titles currently in the Pages list, in order — the live walk queue."""
        return [
            self.category_pages_list.item(row).text()
            for row in range(self.category_pages_list.count())
        ]

    def _set_category_pages(self, titles: list[str]) -> None:
        """Replace the Pages list with `titles` (a fresh category fetch)."""
        self.category_pages_list.clear()
        self.category_pages_list.addItems(titles)
        self._update_category_pages_header()

    def _add_category_page(self) -> None:
        """Append a hand-typed page title to the walk queue, skipping duplicates."""
        title = self.category_add_field.text().strip()
        if not title:
            return
        if title in self._category_titles():
            self.category_status.setText(f"“{title}” is already in the list.")
            return
        self.category_pages_list.addItem(title)
        self.category_add_field.clear()
        self._update_category_pages_header()

    def _remove_category_pages(self) -> None:
        """Drop the selected pages from the queue. Removing the page under review jumps the
        run to the next remaining page (or finishes); removing others just shortens it."""
        items = self.category_pages_list.selectedItems()
        if not items:
            self.category_status.setText("Select one or more pages to remove.")
            return
        removing = {item.text() for item in items}
        # If the active page is being removed, find where to jump before the rows disappear.
        jump_to: str | None = None
        removing_current = self._batch_running and self._batch_current in removing
        if removing_current:
            titles = self._category_titles()
            start = titles.index(self._batch_current) + 1
            jump_to = next((t for t in titles[start:] if t not in removing), None)
        for item in items:
            self.category_pages_list.takeItem(self.category_pages_list.row(item))
        self._update_category_pages_header()
        if removing_current:
            if jump_to is not None:
                self._load_batch_title(jump_to)
            else:
                self._finish_batch()

    def _run_category(self) -> None:
        if self.game is None:
            self.status.setText("Load a data source first.")
            return
        categories = [c.strip() for c in self.category_field.text().split(",") if c.strip()]
        if not categories:
            self.category_status.setText("Enter a category to walk.")
            return
        self.category_button.setEnabled(False)
        label = categories[0] if len(categories) == 1 else f"{len(categories)} categories"
        self.category_status.setText(f"Fetching {label}…")
        self._run(
            lambda: self._intersect_categories(categories),
            self._on_category_loaded,
            self._on_category_failed,
        )

    def _intersect_categories(self, categories: list[str]) -> list[str]:
        """Page titles present in every given category, in the first one's order (a single
        category is just its own members). Runs on a worker thread, one API call per category."""
        titles = self.client.category_members(categories[0])
        for category in categories[1:]:
            shared = set(self.client.category_members(category))
            titles = [t for t in titles if t in shared]
        return titles

    def _on_category_loaded(self, titles: list[str]) -> None:
        self.category_button.setEnabled(True)
        if not titles:
            self.category_status.setText("No pages matched.")
            return
        self._set_category_pages(titles)
        self._batch_running = True
        self._load_batch_title(titles[0])

    def _on_category_failed(self, message: str) -> None:
        self.category_button.setEnabled(True)
        self.category_status.setText(f"Category failed — {message}")

    def _load_batch_title(self, title: str) -> None:
        """Make `title` the page under review: highlight it, load it and diff it."""
        self._batch_current = title
        titles = self._category_titles()
        position = titles.index(title) + 1 if title in titles else 0
        self.category_status.setText(f"Page {position} of {len(titles)}: {title}")
        matches = self.category_pages_list.findItems(title, Qt.MatchFlag.MatchExactly)
        if matches:
            self.category_pages_list.setCurrentItem(matches[0])
        self.page_field.setText(title)
        self.object_search.clear()  # no override carried between pages
        self.portrait_object_search.clear()  # nor a portrait override
        self._generate_diff()

    def _load_category_page(self, item) -> None:
        """Load the double-clicked page. During a run it becomes the page under review (so
        the walk continues from there); otherwise it just loads and diffs."""
        title = item.text()
        if self._batch_running:
            self._load_batch_title(title)
        else:
            self.page_field.setText(title)
            self.object_search.clear()
            self.portrait_object_search.clear()
            self._generate_diff()

    def _advance_batch(self) -> None:
        """Move to the next page in the live queue, or finish when none follow."""
        titles = self._category_titles()
        following = (
            titles[titles.index(self._batch_current) + 1 :]
            if (self._batch_current in titles)
            else []
        )
        if following:
            self._load_batch_title(following[0])
        else:
            self._finish_batch()

    def _finish_batch(self) -> None:
        """End the run: nothing left to walk."""
        total = self.category_pages_list.count()
        self._batch_running = False
        self._batch_current = None
        self.category_status.setText(f"Category run complete — {total} page(s) in the list.")
        self._update_skip_enabled()

    def _skip(self) -> None:
        if self._batch_running:
            self._advance_batch()

    def _update_skip_enabled(self) -> None:
        self.skip_button.setEnabled(self._batch_running)

    def _build_armorsets_card(self) -> QWidget:
        frame, layout = card()
        self.armor_toggle = QPushButton()
        self.armor_toggle.setObjectName("sectionHeader")
        self.armor_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.armor_toggle.clicked.connect(self._toggle_armorsets)
        layout.addWidget(self.armor_toggle)

        self.armor_body = QWidget()
        body = QVBoxLayout(self.armor_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        note = QLabel(
            "Write every loaded armor set onto its Armor Sets/<letter> page — "
            "refreshing each set's values in place and appending ones the page lacks."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        body.addWidget(note)

        row = QHBoxLayout()
        self.armor_button = QPushButton("Port armor sets to wiki")
        self.armor_button.clicked.connect(self._port_armorsets)
        row.addWidget(self.armor_button)
        row.addStretch(1)
        body.addLayout(row)

        self.armor_status = QLabel("")
        self.armor_status.setObjectName("muted")
        body.addWidget(self.armor_status)

        layout.addWidget(self.armor_body)
        self.armor_body.setVisible(False)  # collapsed by default
        self._update_armor_header()
        return frame

    def _toggle_armorsets(self) -> None:
        self.armor_body.setVisible(not self.armor_body.isVisible())
        self._update_armor_header()

    def _update_armor_header(self) -> None:
        arrow = "▾" if self.armor_body.isVisible() else "▸"
        self.armor_toggle.setText(f"{arrow}  ARMOR SETS")

    def _port_armorsets(self) -> None:
        if self.game is None:
            self.armor_status.setText("Load a data source first.")
            return
        if not self.client.logged_in:
            self.armor_status.setText("Log in first to save armor-set pages.")
            return
        game = self.game
        self.armor_button.setEnabled(False)
        self.armor_status.setText("Porting armor sets…")

        def task():
            pages = armor_sections_by_page(game)
            changed = 0
            errors: list[str] = []
            for title in sorted(pages):
                sections, order = pages[title]
                try:
                    existing = self.client.fetch_wikitext(title)
                    merged = merge_page(existing, sections, order)
                    if merged.strip() != existing.strip():
                        self.client.save(title, merged, "Update armor sets from game data")
                        changed += 1
                except WikiError as exc:
                    errors.append(f"{title.split('/')[-1]}: {exc}")
            return len(pages), changed, errors

        self._run(task, self._on_armor_ported, self._on_armor_failed)

    def _on_armor_ported(self, result) -> None:
        total, changed, errors = result
        self.armor_button.setEnabled(True)
        message = f"Armor sets ported — {changed} of {total} page(s) updated"
        message += " (already current)." if changed == 0 and not errors else "."
        if errors:
            message += f" {len(errors)} failed: " + "; ".join(errors[:3])
        self.armor_status.setText(message)

    def _on_armor_failed(self, message: str) -> None:
        self.armor_button.setEnabled(True)
        self.armor_status.setText(f"Porting failed — {message}")

    def _build_versions_card(self) -> QWidget:
        frame, layout = card()
        self.versions_toggle = QPushButton()
        self.versions_toggle.setObjectName("sectionHeader")
        self.versions_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.versions_toggle.clicked.connect(self._toggle_versions)
        layout.addWidget(self.versions_toggle)

        self.versions_body = QWidget()
        body = QVBoxLayout(self.versions_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        note = QLabel(
            "Edit the wiki's version templates. Fetch the current values, change "
            "any of them, and apply to write each changed template back."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        body.addWidget(note)

        # One labelled box per template, keyed by its Template page title.
        self.version_fields: dict[str, QLineEdit] = {}
        for title, label in VERSION_TEMPLATES.items():
            row = QHBoxLayout()
            caption = QLabel(label)
            caption.setMinimumWidth(120)
            caption.setToolTip(title)
            field = QLineEdit()
            field.setPlaceholderText("Fetch to load the current value…")
            row.addWidget(caption)
            row.addWidget(field, 1)
            body.addLayout(row)
            self.version_fields[title] = field

        row = QHBoxLayout()
        self.versions_fetch_button = QPushButton("Fetch current")
        self.versions_fetch_button.clicked.connect(self._fetch_versions)
        row.addWidget(self.versions_fetch_button)
        row.addStretch(1)
        self.versions_apply_button = QPushButton("Apply")
        self.versions_apply_button.setObjectName("primary")
        self.versions_apply_button.clicked.connect(self._apply_versions)
        row.addWidget(self.versions_apply_button)
        body.addLayout(row)

        self.versions_status = QLabel("")
        self.versions_status.setObjectName("muted")
        body.addWidget(self.versions_status)

        layout.addWidget(self.versions_body)
        self.versions_body.setVisible(False)  # collapsed by default
        self._update_versions_header()
        return frame

    def _toggle_versions(self) -> None:
        self.versions_body.setVisible(not self.versions_body.isVisible())
        self._update_versions_header()

    def _update_versions_header(self) -> None:
        arrow = "▾" if self.versions_body.isVisible() else "▸"
        self.versions_toggle.setText(f"{arrow}  VERSION TEMPLATES")

    def _fetch_versions(self) -> None:
        self.versions_fetch_button.setEnabled(False)
        self.versions_status.setText("Fetching version templates…")
        titles = list(VERSION_TEMPLATES)

        def task():
            return {t: extract_version(self.client.fetch_wikitext(t)) for t in titles}

        self._run(task, self._on_versions_fetched, self._on_versions_failed)

    def _on_versions_fetched(self, values: dict[str, str]) -> None:
        self.versions_fetch_button.setEnabled(True)
        for title, value in values.items():
            self.version_fields[title].setText(value)
        self._version_baseline = dict(values)
        self.versions_status.setText("Loaded current values — edit and apply.")

    def _apply_versions(self) -> None:
        if not self.client.logged_in:
            self.versions_status.setText("Log in first to save version templates.")
            return
        edited = {
            title: field.text().strip()
            for title, field in self.version_fields.items()
            if field.text().strip() != self._version_baseline.get(title, "")
        }
        if not edited:
            self.versions_status.setText("No changes to apply — fetch and edit a value first.")
            return
        self.versions_apply_button.setEnabled(False)
        self.versions_status.setText(f"Saving {len(edited)} template(s)…")

        def task():
            for title, value in edited.items():
                existing = self.client.fetch_wikitext(title)
                name = title.split(":", 1)[-1]
                summary = f"Update {name} to {value}"
                self.client.save(title, replace_version(existing, value), summary)
            return list(edited)

        self._run(task, self._on_versions_applied, self._on_versions_failed)

    def _on_versions_applied(self, saved: list[str]) -> None:
        self.versions_apply_button.setEnabled(True)
        for title in saved:
            self._version_baseline[title] = self.version_fields[title].text().strip()
        names = [title.split(":", 1)[-1] for title in saved]
        self.versions_status.setText("Saved: " + ", ".join(names))

    def _on_versions_failed(self, message: str) -> None:
        self.versions_fetch_button.setEnabled(True)
        self.versions_apply_button.setEnabled(True)
        self.versions_status.setText(f"Failed — {message}")

    def _build_login_card(self) -> QWidget:
        # Auto-collapses once logged in to step out of the way.
        frame, layout = card()
        self.login_toggle = QPushButton()
        self.login_toggle.setObjectName("sectionHeader")
        self.login_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_toggle.clicked.connect(self._toggle_login)
        layout.addWidget(self.login_toggle)

        self.login_body = QWidget()
        body = QVBoxLayout(self.login_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        row = QHBoxLayout()
        username = load_username(APP_NAME)
        self.user_field = QLineEdit(username)
        self.user_field.setPlaceholderText("Username (or User@botname)")
        remembered = load_password(username, APP_NAME) if username else ""
        self.pass_field = QLineEdit(remembered)
        self.pass_field.setPlaceholderText("Password or bot-password secret")
        self.pass_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_field.returnPressed.connect(self._login)
        self.show_pass_button = QPushButton("Show")
        self.show_pass_button.setCheckable(True)
        self.show_pass_button.toggled.connect(self._toggle_password)
        row.addWidget(self.user_field, 1)
        row.addWidget(self.pass_field, 1)
        row.addWidget(self.show_pass_button)
        self.login_button = QPushButton("Log in")
        self.login_button.clicked.connect(self._login)
        row.addWidget(self.login_button)
        body.addLayout(row)

        self.remember_pass_check = QCheckBox("Remember password")
        self.remember_pass_check.setChecked(bool(remembered))
        self.remember_pass_check.setToolTip(
            "Store the password in your operating system's secure credential store "
            "(Windows Credential Manager, macOS Keychain, or the Linux Secret Service)."
        )
        body.addWidget(self.remember_pass_check)

        self.login_status = QLabel("Not logged in.")
        self.login_status.setObjectName("muted")
        body.addWidget(self.login_status)

        layout.addWidget(self.login_body)
        self._login_summary = ""  # names the logged-in user once signed in
        self._update_login_header()
        return frame

    def _toggle_login(self) -> None:
        self.login_body.setVisible(not self.login_body.isVisible())
        self._update_login_header()

    def _update_login_header(self) -> None:
        arrow = "▾" if self.login_body.isVisible() else "▸"
        suffix = f" — {self._login_summary}" if self._login_summary else ""
        self.login_toggle.setText(f"{arrow}  WIKI LOGIN{suffix}")

    def _toggle_password(self, shown: bool) -> None:
        """Show the password as plain text while the toggle is on, mask it when off."""
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.pass_field.setEchoMode(mode)
        self.show_pass_button.setText("Hide" if shown else "Show")

    def _login(self) -> None:
        username = self.user_field.text().strip()
        password = self.pass_field.text()
        if not username or not password:
            self.login_status.setText("Enter a username and password.")
            return
        self.login_button.setEnabled(False)
        self.login_status.setText("Logging in…")

        def task():
            self.client.login(username, password)
            return username

        self._run(task, self._on_login, self._on_login_failed)

    def _on_login(self, username: str) -> None:
        save_username(username, APP_NAME)  # username goes in plaintext; the password does not
        if self.remember_pass_check.isChecked():
            # a quiet no-op on a machine with no keyring backend
            save_password(username, self.pass_field.text(), APP_NAME)
        else:
            delete_password(username, APP_NAME)  # clear any previously remembered secret
        self.pass_field.clear()
        self.login_button.setEnabled(True)
        self.login_status.setText(f"Logged in as {username}.")
        self._login_summary = f"logged in as {username}"
        self._update_login_header()
        self.login_dialog.accept()  # close the login dialog now that we're signed in
        self._update_apply_enabled()

    def _on_login_failed(self, message: str) -> None:
        self.login_button.setEnabled(True)
        self.login_status.setText(f"Login failed — {message}")

    def _build_images_card(self) -> QWidget:
        # Keyed off the page/object the diff workflow names, with its own image sources.
        frame, layout = card()
        self.images_frame = frame
        self.images_toggle = QPushButton()
        self.images_toggle.setObjectName("sectionHeader")
        self.images_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.images_toggle.clicked.connect(self._toggle_images)
        layout.addWidget(self.images_toggle)

        self.images_body = QWidget()
        body = QVBoxLayout(self.images_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        note = QLabel(
            "Crop a unit portrait from the image sources below and upload it as <object>.png "
            "— then copy the file name into the infobox image yourself. Defaults to the Page "
            "and object above; type an object below to preview any other one (e.g. another "
            "form of a complex hero)."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        body.addWidget(note)

        self.image_sources_panel = SourcesPanel(
            title="IMAGE SOURCES",
            expanded_hint="IMAGE SOURCES — texture folders / .big archives with the .dds files",
            item_label=lambda kind, path: f"[{kind}]  {Path(path).name}  —  {path}",
            list_max_height=120,
        )
        self.image_sources_panel.load_requested.connect(self._load_textures)
        body.addWidget(self.image_sources_panel)

        # Optional: a specific object whose portrait (and button icons) to show, overriding the
        # page's resolved object — handy for a complex hero's other form objects (the fell
        # beast, ring hunter, …). Enter previews it.
        self.portrait_object_search = QLineEdit()
        self.portrait_object_search.setPlaceholderText(
            "(optional) object to preview — defaults to the page's"
        )
        self.portrait_object_search.setEnabled(False)
        self.portrait_object_search.returnPressed.connect(self._preview_portrait)
        body.addWidget(self.portrait_object_search)

        # Side-by-side compare: the page's current wiki image next to the portrait cropped
        # from the sources. The current image comes from the wiki, independent of textures.
        previews = QHBoxLayout()
        previews.setSpacing(8)
        self.current_image_preview = self._build_compare_preview(
            previews, "Current (wiki)", "The page's current infobox image appears here."
        )
        self.image_preview = self._build_compare_preview(
            previews, "Generated", "Load image sources, then Preview the portrait."
        )
        body.addLayout(previews)

        row = QHBoxLayout()
        self.image_status = QLabel("")
        self.image_status.setObjectName("muted")
        # Wrap long status text (esp. wiki upload errors) instead of letting it stretch the
        # whole column wide.
        self.image_status.setWordWrap(True)
        row.addWidget(self.image_status, 1)
        self.image_preview_button = QPushButton("Preview")
        self.image_preview_button.setEnabled(False)  # enabled once image sources load
        self.image_preview_button.clicked.connect(self._preview_portrait)
        row.addWidget(self.image_preview_button)
        self.image_upload_button = QPushButton("Upload")
        self.image_upload_button.setObjectName("primary")
        self.image_upload_button.setEnabled(False)
        self.image_upload_button.clicked.connect(self._upload_portrait)
        row.addWidget(self.image_upload_button)
        body.addLayout(row)

        # The uploaded portrait's file name, surfaced (read-only, selectable) to copy into
        # the infobox rather than rewriting the page.
        self.image_name_field = QLineEdit()
        self.image_name_field.setReadOnly(True)
        self.image_name_field.setPlaceholderText("Uploaded portrait file name appears here.")
        body.addWidget(self.image_name_field)

        icons_note = QLabel(
            "Button icons list automatically for the loaded page's object. Upload any of "
            "them individually, or use Ability to copy its {{Ability}} template. Each shows "
            "its <name>.png to copy where you need it."
        )
        icons_note.setObjectName("muted")
        icons_note.setWordWrap(True)
        body.addWidget(icons_note)

        # Type a command set to list it directly instead of the object's own (Enter to apply).
        self.commandset_search = QLineEdit()
        self.commandset_search.setPlaceholderText(
            "(optional) command set to list — defaults to the object's"
        )
        self.commandset_search.setEnabled(False)
        self.commandset_search.returnPressed.connect(self._list_button_icons)
        body.addWidget(self.commandset_search)

        self.icons_area = QScrollArea()
        self.icons_area.setWidgetResizable(True)
        self.icons_area.setMinimumHeight(160)
        self.icons_area.setMaximumHeight(320)
        container = QWidget()
        self.icons_layout = QVBoxLayout(container)
        self.icons_layout.setContentsMargins(4, 4, 4, 4)
        self.icons_layout.setSpacing(4)
        self.icons_layout.addStretch(1)
        self.icons_area.setWidget(container)
        body.addWidget(self.icons_area)

        layout.addWidget(self.images_body)
        self.images_body.setVisible(False)  # collapsed by default
        frame.setMaximumHeight(frame.sizeHint().height())  # start shrunk in the splitter
        self._update_images_header()
        return frame

    def _build_compare_preview(self, row: QHBoxLayout, caption: str, placeholder: str) -> QLabel:
        """Add a captioned image preview to `row`, returning its image QLabel (used for the
        two side-by-side previews so both share one slot with a heading)."""
        column = QVBoxLayout()
        column.setSpacing(2)
        heading = QLabel(caption)
        heading.setObjectName("muted")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(heading)
        preview = QLabel(placeholder)
        preview.setObjectName("muted")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumHeight(180)
        preview.setWordWrap(True)
        column.addWidget(preview, 1)
        row.addLayout(column, 1)
        return preview

    def _toggle_images(self) -> None:
        self._set_card_collapsed(
            self.images_frame,
            self.images_body,
            self.images_body.isVisible(),
            self._update_images_header,
        )

    def _expand_images(self) -> None:
        """Reveal the images card (used by the auto-load paths) through the collapse helper so
        its frame cap is lifted and the splitter handle moves."""
        if not self.images_body.isVisible():
            self._set_card_collapsed(
                self.images_frame, self.images_body, False, self._update_images_header
            )

    def _update_images_header(self) -> None:
        arrow = "▾" if self.images_body.isVisible() else "▸"
        self.images_toggle.setText(f"{arrow}  IMAGES")

    def _load_textures(self) -> None:
        sources = self.image_sources_panel.sources()
        if not sources:
            self.image_status.setText("Add an image folder or .big file first.")
            return
        save_sources(sources, TEXTURE_SOURCES_APP)
        self.image_sources_panel.load_button.setEnabled(False)
        self.image_status.setText(f"Indexing {len(sources)} image source(s)…")
        self._run(
            lambda: TextureSource(sources),
            self._on_textures_loaded,
            self._on_textures_failed,
        )

    def _on_textures_loaded(self, source: TextureSource) -> None:
        self._texture_source = source
        self.image_sources_panel.load_button.setEnabled(True)
        self.image_sources_panel.set_collapsed(True)
        self.image_preview_button.setEnabled(True)
        self.image_upload_button.setEnabled(True)
        self.image_status.setText(f"Indexed {len(source)} texture(s). Preview or upload.")
        # Fill the card for whatever object is already in play (it may have loaded first).
        self._images_loaded_for = None
        self._auto_load_images(self._current_object())

    def _on_textures_failed(self, message: str) -> None:
        self.image_sources_panel.load_button.setEnabled(True)
        self.image_status.setText(f"Could not index the image sources — {message}")

    def _portrait_object(self, game):
        """The object whose portrait to use — the images card's own object box, else the
        Page-and-object override or the page-generation object, all without a fetch, else the
        page's infobox object id. Raises `WikiError` with a usable message."""
        for box in (self.portrait_object_search, self.object_search, self.pagegen_object):
            name = box.text().strip()
            if name:
                obj = game.objects.get(name)
                if obj is None:
                    raise WikiError(f"object “{name}” is not loaded")
                return obj
        title = self.page_field.text().strip()
        if not title:
            raise WikiError("enter a page title or an object name")
        infobox = parse_infobox(self.client.fetch_wikitext(title))
        if infobox is None:
            raise WikiError(f"no infobox found on “{title}”")
        obj = resolve_object(infobox, game)
        if obj is None:
            raise WikiError(f"could not resolve an object for “{title}”")
        return obj

    def _current_object(self):
        """The object the workflow currently names (the override box, else the page-generation
        box), or None. Used to auto-fill images once textures load."""
        if self.game is None:
            return None
        name = self.object_search.text().strip() or self.pagegen_object.text().strip()
        return self.game.objects.get(name) if name else None

    def _auto_load_images(self, obj) -> None:
        """Fill the portrait preview and button icons for `obj` when textures are loaded,
        saving the manual Preview/List clicks. A no-op when no textures are indexed, there is
        no object, or the card already shows this one."""
        if self._texture_source is None or obj is None:
            return
        if obj.name == self._images_loaded_for:
            return
        self._images_loaded_for = obj.name
        self._expand_images()  # reveal the card
        self._start_portrait_preview(obj)
        self._start_icon_list(obj)

    def _preview_portrait(self) -> None:
        self._start_portrait_preview()

    def _start_portrait_preview(self, obj=None) -> None:
        if self.game is None:
            self.image_status.setText("Load a data source first.")
            return
        if self._texture_source is None:
            self.image_status.setText("Load image sources first.")
            return
        game, source = self.game, self._texture_source
        background = self._portrait_background
        self.image_preview_button.setEnabled(False)
        self.image_status.setText("Resolving portrait…")

        def task():
            # An explicit object (an auto-load) is used as-is; otherwise resolve from the
            # override box or the page, which may fetch it.
            target = obj if obj is not None else self._portrait_object(game)
            png = render_portrait_png(source, target, background)
            if png is None:
                raise WikiError(f"no portrait found for {target.name} in the image sources")
            return target.name, png

        self._run(task, self._on_portrait_preview, self._on_portrait_failed)

    def _on_portrait_preview(self, result) -> None:
        name, png = result
        self.image_preview_button.setEnabled(True)
        pixmap = QPixmap()
        if not pixmap.loadFromData(png):
            self.image_status.setText("Could not decode the cropped portrait.")
            return
        target = min(self.image_preview.width(), self.image_preview.height())
        if target > 0 and (pixmap.width() > target or pixmap.height() > target):
            pixmap = pixmap.scaled(
                target,
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.image_preview.setText("")
        self.image_preview.setPixmap(pixmap)
        # Surface the prospective file name so it can be copied even before upload.
        self.image_name_field.setText(f"{name}.png")
        self.image_status.setText(f"Preview of {name}.png — review, then upload.")

    def _upload_portrait(self) -> None:
        if self.game is None:
            self.image_status.setText("Load a data source first.")
            return
        if self._texture_source is None:
            self.image_status.setText("Load image sources first.")
            return
        if not self.client.logged_in:
            self.image_status.setText("Log in first to upload images.")
            return
        # Resolve as Preview does and upload; the page text is left untouched, the file name
        # surfaced below for the editor to copy in.
        game, source, background = self.game, self._texture_source, self._portrait_background
        self.image_upload_button.setEnabled(False)
        self.image_status.setText("Resolving portrait…")

        def task():
            obj = self._portrait_object(game)
            png = render_portrait_png(source, obj, background)
            if png is None:
                raise WikiError(f"no portrait found for {obj.name} in the image sources")
            filename = portrait_filename(obj)
            self.client.upload(
                png,
                filename,
                description=f"{obj.name} portrait, uploaded from game data by sage_wiki.",
                comment=f"Upload {obj.name} portrait from game data",
            )
            return filename

        self._run(task, self._on_portrait_uploaded, self._on_portrait_failed)

    def _on_portrait_uploaded(self, filename: str) -> None:
        self.image_upload_button.setEnabled(True)
        self.image_name_field.setText(filename)
        self.image_status.setText(f"Uploaded {filename} — copy its name into the infobox image.")

    def _on_portrait_failed(self, message: str) -> None:
        self.image_preview_button.setEnabled(self._texture_source is not None)
        self.image_upload_button.setEnabled(self._texture_source is not None)
        self.image_status.setText(f"Portrait failed — {message}")

    def _load_current_image(self, image_value: str | None) -> None:
        """Show the page's current infobox image (from `image_value`) in the Current preview,
        fetched from the wiki for comparison — independent of the texture sources."""
        filename = filename_from_value(image_value)
        if filename is None:
            self.current_image_preview.setPixmap(QPixmap())  # drop any previous page's image
            self.current_image_preview.setText("This page's infobox names no image.")
            return
        self._expand_images()  # reveal the card
        self.current_image_preview.setPixmap(QPixmap())
        self.current_image_preview.setText(f"Loading {filename}…")
        self._run(
            lambda: (filename, self.client.fetch_image(filename)),
            self._on_current_image,
            self._on_current_image_failed,
        )

    def _on_current_image(self, result) -> None:
        filename, data = result
        if not data:
            self.current_image_preview.setPixmap(QPixmap())
            self.current_image_preview.setText(f"{filename} is not on the wiki yet.")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self.current_image_preview.setPixmap(QPixmap())
            self.current_image_preview.setText(f"Could not decode {filename}.")
            return
        target = min(self.current_image_preview.width(), self.current_image_preview.height())
        if target > 0 and (pixmap.width() > target or pixmap.height() > target):
            pixmap = pixmap.scaled(
                target,
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.current_image_preview.setText("")
        self.current_image_preview.setPixmap(pixmap)

    def _on_current_image_failed(self, message: str) -> None:
        self.current_image_preview.setPixmap(QPixmap())
        self.current_image_preview.setText(f"Current image failed — {message}")

    def _list_button_icons(self) -> None:
        self._start_icon_list()

    def _start_icon_list(self, obj=None) -> None:
        if self.game is None:
            self.image_status.setText("Load a data source first.")
            return
        if self._texture_source is None:
            self.image_status.setText("Load image sources first.")
            return
        game, source = self.game, self._texture_source
        # An auto-load lists the object's own command set; typing one in the search box and
        # pressing Enter lists that set instead.
        command_set_name = "" if obj is not None else self.commandset_search.text().strip()
        self.image_status.setText("Resolving button icons…")

        def task():
            # A named command set is listed directly; otherwise the one the object displays,
            # reporting its name so the searchbox can be filled with it.
            if command_set_name:
                command_set = game.commandsets.get(command_set_name)
                if command_set is None:
                    raise WikiError(f"command set “{command_set_name}” is not loaded")
                set_name, source_rows = command_set_name, command_set_icon_rows(game, command_set)
            else:
                target = obj if obj is not None else self._portrait_object(game)
                set_name, source_rows = object_command_icon_rows(game, target)
            # Crop every icon up front (None when unresolvable); upload reuses these bytes.
            # Ability icons are framed with their active/passive overlay so the frame is in
            # both the preview and the uploaded file.
            rows = []
            for r in source_rows:
                button = game.commandbuttons.get(r["button"])
                overlay = ability_overlay(ability_overlay_kind(button))
                rows.append(
                    {
                        "name": r["name"],
                        "text": r["text"],
                        "button": r["button"],
                        "png": render_icon_png(source, r["image"], overlay),
                    }
                )
            return set_name, rows

        self._run(task, self._on_button_icons, self._on_button_icons_failed)

    def _on_button_icons(self, result) -> None:
        set_name, rows = result
        if set_name:  # reflect the command set that was listed (esp. the auto-resolved one)
            self.commandset_search.setText(set_name)
        self._clear_icon_rows()
        croppable = 0
        for row in rows:
            self._add_icon_row(row)
            croppable += row["png"] is not None
        label = set_name or "object"
        self.image_status.setText(
            f"{label}: {croppable} of {len(rows)} button icon(s) ready to upload."
            if rows
            else f"{label}: no command-set buttons to extract."
        )

    def _on_button_icons_failed(self, message: str) -> None:
        self.image_status.setText(f"Button icons failed — {message}")

    def _clear_icon_rows(self) -> None:
        """Remove every icon row, leaving the trailing stretch in place."""
        while self.icons_layout.count() > 1:
            item = self.icons_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_icon_row(self, row: dict) -> None:
        """One button-icon row: thumbnail, label, copyable name, Upload and Ability."""
        wrap = QWidget()
        line = QHBoxLayout(wrap)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)

        png = row["png"]
        thumb = QLabel()
        thumb.setFixedSize(28, 28)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if png is not None:
            pixmap = QPixmap()
            if pixmap.loadFromData(png):
                thumb.setPixmap(
                    pixmap.scaled(
                        28,
                        28,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        line.addWidget(thumb)

        label = QLabel(row["text"])
        label.setWordWrap(True)
        line.addWidget(label, 1)

        # The destination file name, read-only but selectable.
        name_field = QLineEdit(icon_filename(row["name"]))
        name_field.setReadOnly(True)
        name_field.setMinimumWidth(150)
        line.addWidget(name_field, 1)

        upload = QPushButton("Upload")
        if png is None:
            upload.setEnabled(False)
            upload.setToolTip("This button has no icon, or its texture isn't in the sources.")
        else:
            upload.clicked.connect(
                lambda _=False, r=row, b=upload: self._upload_icon(r["name"], r["png"], b)
            )
        line.addWidget(upload)

        # Scaffold this button's {{Ability}} template (with its icon filename pre-filled)
        # and copy it to the clipboard, ready to paste into the page.
        ability = QPushButton("Ability")
        ability.setToolTip("Copy this button's {{Ability}} template to the clipboard.")
        ability.clicked.connect(lambda _=False, r=row: self._copy_ability(r))
        line.addWidget(ability)

        self.icons_layout.insertWidget(self.icons_layout.count() - 1, wrap)  # before the stretch

    def _copy_ability(self, row: dict) -> None:
        """Generate the `{{Ability}}` template for a row's command button and put it on the
        clipboard. Reports when the button isn't an ability (nothing to scaffold)."""
        if self.game is None:
            self.image_status.setText("Load a data source first.")
            return
        block = button_ability_block(self.game, row["button"], icon_filename(row["name"]))
        if not block:
            self.image_status.setText(f"{row['text']}: no ability template to generate.")
            return
        QApplication.clipboard().setText(block)
        self.image_status.setText(f"Copied {row['text']} ability template to the clipboard.")

    def _upload_icon(self, name: str, png: bytes, button: QPushButton) -> None:
        if not self.client.logged_in:
            self.image_status.setText("Log in first to upload images.")
            return
        filename = icon_filename(name)
        button.setEnabled(False)
        self.image_status.setText(f"Uploading {filename}…")

        def task():
            self.client.upload(
                png,
                filename,
                description=f"{name} icon, uploaded from game data by sage_wiki.",
                comment=f"Upload {name} icon from game data",
            )
            return filename

        self._run(
            task,
            lambda fn, b=button: self._on_icon_uploaded(fn, b),
            lambda message, b=button: self._on_icon_upload_failed(message, b),
        )

    def _on_icon_uploaded(self, filename: str, button: QPushButton) -> None:
        button.setText("Uploaded")
        button.setEnabled(False)
        self.image_status.setText(f"Uploaded {filename} — copy its name from the field.")

    def _on_icon_upload_failed(self, message: str, button: QPushButton) -> None:
        button.setEnabled(True)
        self.image_status.setText(f"Icon upload failed — {message}")

    def _build_diff_card(self) -> QWidget:
        # A read-only field-level summary; the editable page lives in the wikitext card.
        frame, layout = card("Changes")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Field", "Current", "New"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        return frame

    def _build_wikitext_card(self) -> QWidget:
        # The whole page as it will be submitted, freely editable; Apply saves exactly this text.
        frame, layout = card("Page wikitext")
        note = QLabel(
            "The full page with all changes applied. Edit freely — Apply submits exactly this text."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        # The save/skip controls sit above the editor so they stay reachable without
        # scrolling past a long page. A blank summary uses the default (the changed-field list).
        self.summary_field = QLineEdit()
        self.summary_field.setPlaceholderText("Edit summary (optional — overrides the default)")
        layout.addWidget(self.summary_field)

        button_row = QHBoxLayout()
        self.skip_button = QPushButton("Skip")
        self.skip_button.setEnabled(False)  # only active during a category run
        self.skip_button.clicked.connect(self._skip)
        button_row.addWidget(self.skip_button)
        self.goto_button = QPushButton("Go To Page")
        self.goto_button.setToolTip("Open the current page title in your web browser.")
        self.goto_button.clicked.connect(self._go_to_page)
        button_row.addWidget(self.goto_button)
        self.linkify_button = QPushButton("Linkify")
        self.linkify_button.setToolTip(
            "Add internal links to the page text: wrap unit/hero names that have a wiki page "
            "in [[links]], leaving existing links, templates and refs untouched."
        )
        self.linkify_button.clicked.connect(self._linkify_page)
        button_row.addWidget(self.linkify_button)
        button_row.addStretch(1)
        self.apply_button = QPushButton("Apply to wiki")
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        button_row.addWidget(self.apply_button)
        layout.addLayout(button_row)

        self.wikitext_editor = QPlainTextEdit()
        self.wikitext_editor.setPlaceholderText(
            "Generate a diff (or run a category) to load the page here."
        )
        self.wikitext_editor.setFont(QFont("Consolas", 9))
        layout.addWidget(self.wikitext_editor, 1)

        self.wikitext_editor.textChanged.connect(self._update_apply_enabled)
        return frame

    def _go_to_page(self) -> None:
        """Open the current page title in the user's default web browser."""
        title = self.page_field.text().strip()
        if not title:
            self.status.setText("Enter a page title to open it in the browser.")
            return
        webbrowser.open(self.client.page_url(title))

    def _linkify_page(self) -> None:
        """Add validated internal links to the editor's text: unit/hero names that have a wiki
        page are wrapped in `[[links]]`, with existing links, templates and refs left alone. The
        title fetch runs on a worker so the UI doesn't block; the edit is left for review."""
        if self.game is None:
            self.status.setText("Load a data source first.")
            return
        text = self.wikitext_editor.toPlainText()
        if not text.strip():
            self.status.setText("No page text to linkify.")
            return
        self.linkify_button.setEnabled(False)
        self.status.setText("Adding internal links…")

        def task():
            linker = self._page_linker()
            if linker is None:
                raise WikiError("could not fetch wiki page titles to validate links")
            return linker.linkify_wikitext(text)

        self._run(task, lambda linked: self._on_linkified(text, linked), self._on_linkify_failed)

    def _on_linkified(self, original: str, linked: str) -> None:
        self.linkify_button.setEnabled(True)
        if linked == original:
            self.status.setText("Linkify: no new links to add.")
            return
        self.wikitext_editor.setPlainText(linked)
        self.status.setText("Linkify: added internal links — review before applying.")

    def _on_linkify_failed(self, message: str) -> None:
        self.linkify_button.setEnabled(True)
        self.status.setText(f"Linkify failed — {message}")

    def _generate_diff(self) -> None:
        title = self.page_field.text().strip()
        if self.game is None:
            self.status.setText("Load a data source first.")
            return
        if not title:
            self.status.setText("Enter the wiki page title.")
            return
        self.diff_button.setEnabled(False)
        self.skip_button.setEnabled(False)  # re-enabled when the diff lands
        self.status.setText(f"Fetching “{title}”…")
        # Fetch/parse on the worker; resolving the object (and prompting) happens on the
        # main thread where a dialog is safe.

        def task():
            wikitext = self.client.fetch_wikitext(title)
            infoboxes = parse_infoboxes(wikitext)
            if not infoboxes:
                raise WikiError(f"no infobox found on “{title}”")
            return infoboxes

        self._run(
            task,
            lambda infoboxes: self._resolve_and_diff(title, infoboxes),
            self._on_diff_failed,
        )

    def _resolve_and_diff(self, title: str, infoboxes: list) -> None:
        """Pair every unit/hero/building infobox on the page with the object it names, then
        diff and update them all together. An infobox whose object isn't loaded is left
        untouched; one that names several forms (`A/B`) prompts for the form to use. The
        object override box, when set, forces the first infobox's object — the rest still
        resolve from their own object-id fields."""
        game = self.game
        override = self.object_search.text().strip()
        resolved: list = []  # (Infobox, obj), in document order
        for index, infobox in enumerate(infoboxes):
            if index == 0 and override:
                obj = game.objects.get(override)
                if obj is None:
                    self._on_diff_failed(f"object “{override}” is not loaded")
                    return
            else:
                candidates = resolve_objects(infobox, game)
                if not candidates:
                    continue  # this infobox names no loaded object — leave it as it is
                if len(candidates) == 1:
                    obj = candidates[0]
                else:
                    obj = self._choose_object(candidates)
                    if obj is None:  # cancelled
                        self.diff_button.setEnabled(True)
                        self.status.setText("Diff cancelled — no object chosen.")
                        self._update_skip_enabled()
                        return
            resolved.append((infobox, obj))

        if not resolved:
            named = (infoboxes[0].get("object_name") or infoboxes[0].get("object") or "").strip()
            detail = f"object “{named}” is not loaded" if named else "no object name"
            self._on_diff_failed(f"could not resolve an object for “{title}” ({detail})")
            return

        faction = self.pagegen_faction.text().strip()  # feeds the draft built alongside the diff
        primary_box, primary_obj = resolved[0]  # the draft, images and override track the first
        image_value = primary_box.get(IMAGE_PARAM)  # for the portrait comparison
        label = primary_obj.name if len(resolved) == 1 else f"{len(resolved)} infoboxes"
        self.status.setText(f"Diffing {label}…")

        def task():
            # Diff every infobox (each reads its own current values), then apply all the
            # changes to the shared page to render it exactly as it will be submitted.
            edited = []  # (Infobox, changes) for the apply pass
            groups = []  # (object name, changes) for the review table
            for infobox, obj in resolved:
                changes = diff_infobox(infobox, obj)
                edited.append((infobox, changes))
                groups.append((obj.name, changes))
            new_text = apply_all(edited)
            # Also generate a fresh draft for the primary object, so content can be copied
            # between the live page and the scaffold. A draft failure must not break the diff.
            try:
                draft = generate_page(game, primary_obj, faction, frozenset(), self._page_linker())
            except Exception as exc:  # noqa: BLE001 — keep the diff even if generation fails
                draft = f"<!-- page generation failed: {exc} -->"
            return primary_obj.name, groups, new_text, draft, image_value

        self._run(task, self._on_diff, self._on_diff_failed)

    def _choose_object(self, candidates):
        """Ask which of several slash-separated objects to load; None if cancelled."""
        names = [obj.name for obj in candidates]
        choice, ok = QInputDialog.getItem(
            self,
            "Choose object",
            "This infobox names several objects — pick the one to load:",
            names,
            0,
            False,  # not editable
        )
        if not ok:
            return None
        return next((obj for obj in candidates if obj.name == choice), candidates[0])

    def _on_diff(self, result) -> None:
        object_name, groups, new_text, draft, image_value = result
        self._changes = [change for _, changes in groups for change in changes]
        self.object_search.setText(object_name)  # reflect the primary object the page resolved to
        self._fill_table(groups)
        self.wikitext_editor.setPlainText(new_text)  # full page, every infobox's changes applied
        # Show the draft for the primary object alongside, so content can be copied between them.
        self.pagegen_object.setText(object_name)
        # setText doesn't fire editingFinished, so refresh the upgrade toggles by hand — else the
        # ACTIVE UPGRADES section stays hidden and the object's upgrades can't be selected.
        self._refresh_pagegen_upgrades()
        self.pagegen_preview.setPlainText(draft)
        self.pagegen_status.setText(f"Draft for {object_name}, generated alongside the diff.")
        if not self.pagegen_body.isVisible():
            self._set_card_collapsed(
                self.pagegen_frame, self.pagegen_body, False, self._update_pagegen_header
            )
        # Fill the portrait/icons (when textures are loaded) and the current image for comparison.
        self._auto_load_images(self.game.objects.get(object_name))
        self._load_current_image(image_value)
        self.diff_button.setEnabled(True)
        changed = sum(c.changed for c in self._changes)
        if not self._changes:
            summary = f"{object_name}: no mappable infobox fields on this page."
        elif len(groups) == 1:
            summary = f"{object_name}: {changed} field(s) differ of {len(self._changes)} mapped."
        else:
            names = ", ".join(name for name, _ in groups)
            summary = (
                f"{len(groups)} infoboxes ({names}): "
                f"{changed} field(s) differ of {len(self._changes)} mapped."
            )
        self.status.setText(summary)
        self._update_apply_enabled()
        self._update_skip_enabled()

    def _on_diff_failed(self, message: str) -> None:
        self.diff_button.setEnabled(True)
        self.wikitext_editor.clear()  # nothing safe to submit for a page that wouldn't diff
        self.status.setText(f"Diff failed — {message}")
        self._update_apply_enabled()
        self._update_skip_enabled()

    def _fill_table(self, groups: list[tuple[str, list[FieldChange]]]) -> None:
        """Show the field-level diff; changed rows are highlighted (review only). With more
        than one infobox, each object's changes sit under a bold header row naming it."""
        multi = len(groups) > 1
        self.table.clearSpans()
        self.table.setRowCount(sum(len(changes) + (1 if multi else 0) for _, changes in groups))
        row = 0
        for name, changes in groups:
            if multi:
                header = QTableWidgetItem(name)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                self.table.setItem(row, 0, header)
                self.table.setSpan(row, 0, 1, 3)
                row += 1
            for change in changes:
                cells = (change.param, change.old or "—", change.new)
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if change.changed:
                        item.setForeground(QColor("#7ee787"))
                    self.table.setItem(row, col, item)
                row += 1

    def _update_apply_enabled(self) -> None:
        # Apply submits the editor's text verbatim — enabled when there is text and we're logged in.
        has_text = bool(self.wikitext_editor.toPlainText().strip())
        self.apply_button.setEnabled(has_text and self.client.logged_in)

    def _apply(self) -> None:
        if not self.client.logged_in:
            return
        title = self.page_field.text().strip()
        new_text = self.wikitext_editor.toPlainText()
        if not title or not new_text.strip():
            return
        # A custom summary wins; else name the changed fields, falling back to a generic one.
        changed = [c.param for c in self._changes if c.changed]
        summary = self.summary_field.text().strip() or (
            "Update infobox stats from game data: " + ", ".join(changed)
            if changed
            else "Update page from game data"
        )
        self.apply_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.status.setText(f"Saving “{title}”…")
        self._run(
            lambda: self.client.save(title, new_text, summary),
            self._on_saved,
            self._on_save_failed,
        )

    def _on_saved(self, result) -> None:
        if result.no_change:
            self.status.setText("Saved — the page already matched (no new revision).")
        else:
            self.status.setText(f"Saved “{result.title}” (revision {result.new_revid}).")
        self._clear_review()
        if self._batch_active:
            self._advance_batch()  # on to the next page in the run
        else:
            self._update_apply_enabled()

    def _clear_review(self) -> None:
        """Reset the review pane after a save (the custom summary is left intact so it carries
        to the next page until the user changes it)."""
        self.wikitext_editor.clear()
        self.table.setRowCount(0)
        self._changes = []

    def _on_save_failed(self, message: str) -> None:
        self.status.setText(f"Save failed — {message}")
        self._update_apply_enabled()
        self._update_skip_enabled()  # let the run continue past a page that wouldn't save

    def _run(self, fn, on_done, on_failed) -> None:
        run_worker(self, fn, on_done, on_failed)


def main() -> None:
    run_app(WikiUpdater, icon_file=ICON_FILE, anchor=__file__, app_name=APP_TITLE)


if __name__ == "__main__":
    main()
