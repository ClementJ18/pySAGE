"""The menu-bar tool dialogs: wiki login (with remembered credentials), the armor-set
porter, and the version-template updater."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sage_utils.widgets import (
    card,
)
from sage_wiki.armorsets import armor_sections_by_page, merge_page
from sage_wiki.credentials import (
    delete_password,
    load_password,
    load_username,
    save_password,
    save_username,
)
from sage_wiki.meta import APP_NAME
from sage_wiki.versions import VERSION_TEMPLATES, extract_version, replace_version
from sage_wiki.wiki import WikiError


class ToolDialogsMixin:
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
            "Write every loaded armor set onto its Armor Sets/<letter> page - "
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
        message = f"Armor sets ported - {changed} of {total} page(s) updated"
        message += " (already current)." if changed == 0 and not errors else "."
        if errors:
            message += f" {len(errors)} failed: " + "; ".join(errors[:3])
        self.armor_status.setText(message)

    def _on_armor_failed(self, message: str) -> None:
        self.armor_button.setEnabled(True)
        self.armor_status.setText(f"Porting failed - {message}")

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
        self.versions_status.setText("Loaded current values - edit and apply.")

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
            self.versions_status.setText("No changes to apply - fetch and edit a value first.")
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
        self.versions_status.setText(f"Failed - {message}")

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
        suffix = f" - {self._login_summary}" if self._login_summary else ""
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
        self.login_status.setText(f"Login failed - {message}")
