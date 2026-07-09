"""The CATEGORY RUN card: walk the pages shared by one or more categories through the
diff-review-apply loop, with an editable live page queue."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sage_utils.widgets import (
    card,
)


class CategoryRunMixin:
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
        """The page titles currently in the Pages list, in order - the live walk queue."""
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
        self.category_status.setText(f"Category failed - {message}")

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
        self.category_status.setText(f"Category run complete - {total} page(s) in the list.")
        self._update_skip_enabled()

    def _skip(self) -> None:
        if self._batch_running:
            self._advance_batch()

    def _update_skip_enabled(self) -> None:
        self.skip_button.setEnabled(self._batch_running)
