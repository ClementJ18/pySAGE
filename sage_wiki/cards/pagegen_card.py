"""The GENERATE PAGE card: scaffold a brand-new page draft from an object — infobox,
abilities, upgrade toggles, navbox and category — for review and copy; nothing is saved."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sage_utils.widgets import (
    card,
)
from sage_wiki.links import build_linker
from sage_wiki.pagegen import (
    available_upgrades,
    generate_page,
)
from sage_wiki.wiki import WikiError


class PagegenCardMixin:
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
