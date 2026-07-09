"""The diff-review workflow: generate the infobox-vs-game diff for a page, review the
changes table and editable wikitext (linking selected text to a page), and apply the result
to the wiki."""

import webbrowser

from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_utils.widgets import (
    card,
)
from sage_wiki.diff import (
    FieldChange,
    apply_all,
    diff_infobox,
    resolve_objects,
)
from sage_wiki.images import (
    IMAGE_PARAM,
)
from sage_wiki.infobox import parse_infoboxes
from sage_wiki.pagegen import (
    generate_page,
)
from sage_wiki.wiki import WikiError

# Cap the number of titles shown at once so a bare search doesn't try to list the whole wiki.
_MAX_LINK_RESULTS = 200


class PageSearchDialog(QDialog):
    """Pick a wiki page to link some selected text to. Filters the wiki's article titles live
    as the user types (case-insensitive substring); `chosen_title` is the picked title, or None
    when cancelled."""

    def __init__(self, parent: QWidget, titles: set[str], initial: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Link to page")
        self._titles = sorted(titles)
        self._chosen: str | None = None

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for a page…")
        self.search.setText(initial)
        self.search.textChanged.connect(self._refilter)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        layout.addWidget(self.results, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refilter(initial)
        self.search.setFocus()
        self.search.selectAll()  # so a typed page name replaces the prefilled selection

    def _refilter(self, text: str) -> None:
        needle = text.strip().casefold()
        matches = (
            [title for title in self._titles if needle in title.casefold()]
            if needle
            else self._titles
        )
        self.results.clear()
        self.results.addItems(matches[:_MAX_LINK_RESULTS])
        if self.results.count():
            self.results.setCurrentRow(0)  # so Enter/OK links to the top match

    def _accept_selection(self) -> None:
        item = self.results.currentItem()
        if item is not None:
            self._chosen = item.text()
            self.accept()

    def chosen_title(self) -> str | None:
        return self._chosen


class DiffReviewMixin:
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
            "The full page with all changes applied. Edit freely - Apply submits exactly this text."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        # The save/skip controls sit above the editor so they stay reachable without
        # scrolling past a long page. A blank summary uses the default (the changed-field list).
        self.summary_field = QLineEdit()
        self.summary_field.setPlaceholderText("Edit summary (optional - overrides the default)")
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
        self.link_button = QPushButton("Link")
        self.link_button.setToolTip(
            "Wrap the selected text in an internal link: search for the wiki page to point at, "
            "then insert [[Page]] (or [[Page|selection]] when the text differs from the title)."
        )
        self.link_button.clicked.connect(self._link_selection)
        button_row.addWidget(self.link_button)
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

    def _link_selection(self) -> None:
        """Wrap the text selected in the editor in a link to a page the user picks from a search
        dialog. The wiki's article titles are fetched on a worker (so the UI doesn't block), then
        the dialog opens on the main thread where a modal is safe."""
        cursor = self.wikitext_editor.textCursor()
        selected = cursor.selectedText().strip()
        if not selected:
            self.status.setText("Select the text to link first.")
            return
        self.link_button.setEnabled(False)
        self.status.setText("Fetching page titles…")
        self._run(
            self.client.all_titles,
            lambda titles: self._on_link_titles(cursor, selected, titles),
            self._on_link_failed,
        )

    def _on_link_titles(self, cursor, selected: str, titles: set[str]) -> None:
        """Open the page-search dialog and, on a pick, replace the selection with the link:
        `[[Title]]` when the selection already is the title, else `[[Title|selection]]`."""
        self.link_button.setEnabled(True)
        dialog = PageSearchDialog(self, titles, selected)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.status.setText("Link cancelled.")
            return
        title = dialog.chosen_title()
        if not title:
            return
        cursor.insertText(f"[[{title}]]" if selected == title else f"[[{title}|{selected}]]")
        self.status.setText(f"Linked selection to “{title}”.")

    def _on_link_failed(self, message: str) -> None:
        self.link_button.setEnabled(True)
        self.status.setText(f"Link failed - {message}")

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
        object override box, when set, forces the first infobox's object - the rest still
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
                    continue  # this infobox names no loaded object - leave it as it is
                if len(candidates) == 1:
                    obj = candidates[0]
                else:
                    obj = self._choose_object(candidates)
                    if obj is None:  # cancelled
                        self.diff_button.setEnabled(True)
                        self.status.setText("Diff cancelled - no object chosen.")
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
            except Exception as exc:  # noqa: BLE001 - keep the diff even if generation fails
                draft = f"<!-- page generation failed: {exc} -->"
            return primary_obj.name, groups, new_text, draft, image_value

        self._run(task, self._on_diff, self._on_diff_failed)

    def _choose_object(self, candidates):
        """Ask which of several slash-separated objects to load; None if cancelled."""
        names = [obj.name for obj in candidates]
        choice, ok = QInputDialog.getItem(
            self,
            "Choose object",
            "This infobox names several objects - pick the one to load:",
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
        # setText doesn't fire editingFinished, so refresh the upgrade toggles by hand - else the
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
        self.status.setText(f"Diff failed - {message}")
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
                cells = (change.param, change.old or "-", change.new)
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if change.changed:
                        item.setForeground(QColor("#7ee787"))
                    self.table.setItem(row, col, item)
                row += 1

    def _update_apply_enabled(self) -> None:
        # Apply submits the editor's text verbatim - enabled when there is text and we're logged in.
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
            self.status.setText("Saved - the page already matched (no new revision).")
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
        self.status.setText(f"Save failed - {message}")
        self._update_apply_enabled()
        self._update_skip_enabled()  # let the run continue past a page that wouldn't save
