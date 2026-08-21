"""The SAGE Custom Hero window: open a `.cah`, edit the hero it holds - name, class, colors,
the ten purchasable powers and the twelve bling entries - and write it back with a refreshed
checksum. The file is the only thing the editor needs; loading a game's data on top is optional
and buys completion: the real class and sub-class names, the powers each class may actually buy,
and what a bling index resolves to (see `sage_cah.gamedata`).

Built on the shared sage_utils widgets (cards, the collapsible sources panel, the background
worker, the theme toggle) so it looks and behaves like the other SAGE front ends."""

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QStringListModel
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sage_cah.cah import (
    BLING_STAT_GROUPS,
    CLASS_NAMES,
    SUB_CLASS_NAMES,
    CahBling,
    CahError,
    CahPower,
    CustomHero,
    compute_checksum,
    new_guid,
    parse_cah_from_path,
    write_cah_to_path,
)
from sage_cah.gamedata import BlingOption, CahGameData, PowerOption, load_cah_game_data
from sage_utils.installs import find_installs
from sage_utils.widgets import (
    CopyableLabel as QLabel,
)
from sage_utils.widgets import (
    SourceLoader,
    ThemeToggle,
    add_help_menu,
    card,
    clear_layout,
    make_completer,
    resource_path,
)

APP_NAME = "sage_cah"
APP_TITLE = "SAGE Custom Hero"
ICON_FILE = "icon.ico"

_CAH_FILTER = "Custom heroes (*.cah *.CAH);;All files (*)"

# The Help > Getting started walkthrough. One HTML block so QTextBrowser lays it out.
_GETTING_STARTED_HTML = """
<h2>Getting started with SAGE Custom Hero</h2>
<p>A <code>.cah</code> file is one Create-a-Hero: the hero's name, class, colours, the ten
powers bought at levels 1-10, and the twelve "bling" entries (five attributes and the
appearance choices). This window edits that file directly, so you can change a hero without
spending points in the game's own Create-a-Hero screen.</p>

<h3>1. Open a hero</h3>
<p><b>File &gt; Open…</b> and pick a <code>.cah</code>. Heroes you made in game live under your
<i>My Battle for Middle-earth Files</i> folder; the ones the game ships are inside its
<code>.big</code> archives.</p>

<h3>2. Edit it</h3>
<p>The <b>HERO</b> card holds the identity: name, class and sub-class, object id, the three
palette colours and the GUID. <b>New GUID</b> gives the hero a fresh identity - do that after
copying a file, or the game treats the copy as the same hero.</p>
<p><b>POWERS</b> is one row per slot: the level the power is bought at, the
<code>CommandButton</code> it triggers, and the button index. <b>BLING</b> is one row per
customization entry; the five attribute groups show an in-game <i>value</i>, the appearance
groups a bare index into that sub-class's choices.</p>

<h3>3. Load a game for completion (optional)</h3>
<p>Everything above works with no game data at all - but the raw names are hard going. Add your
game folder or its <code>.big</code> archives to the <b>GAME DATA</b> card (or press <b>Find
installed game</b>) and load them: the class and sub-class lists then come from the data itself
(a mod reorders them), the power field completes over the buttons that class can actually buy,
and each bling row names the choice its index picks.</p>

<h3>4. Save</h3>
<p><b>Save</b> writes the file back with a freshly computed checksum - the game refuses to load
a hero whose checksum does not match its contents, so every save recomputes it.</p>
"""


@dataclass
class _PowerRow:
    """The widgets of one power slot's row (see `_rebuild_powers`)."""

    level: QSpinBox
    button: QLineEdit
    index: QSpinBox
    hint: QLabel


@dataclass
class _BlingRow:
    """The widgets of one bling entry's row, and whether it is being edited as an attribute
    value (one higher than the stored index) rather than a bare index."""

    group: QLineEdit
    value: QSpinBox
    hint: QLabel
    attribute: bool


class CahWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        self.resize(940, 820)

        self.hero: CustomHero | None = None
        self.path: Path | None = None
        self.data: CahGameData | None = None
        self._power_rows: list[_PowerRow] = []
        self._bling_rows: list[_BlingRow] = []
        self._colors = [0, 0, 0]
        self._last_dir = ""
        # Set while widgets are being filled from a freshly parsed hero, so the change signals
        # that fires don't mark the untouched file dirty or fight the values being written.
        self._loading = False
        self._dirty = False
        # Shared completion models, refilled whenever game data or the class selection changes;
        # every row's completer reads one of them, so a refresh is a single assignment.
        self._power_model = QStringListModel([], self)
        self._group_model = QStringListModel([], self)
        self._power_index: dict[str, PowerOption] = {}

        self._build_menu()

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The cards scroll; the status line and Save stay put below them, so the button the
        # window exists for is never scrolled out of reach.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        root = QVBoxLayout(body)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel(APP_TITLE)
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.DemiBold))
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(ThemeToggle())
        root.addLayout(header)

        root.addWidget(self._build_hero_card())
        root.addWidget(self._build_powers_card())
        root.addWidget(self._build_bling_card())
        root.addWidget(self._build_sources_card())
        root.addStretch(1)

        footer_widget = QWidget()
        footer = QHBoxLayout(footer_widget)
        footer.setContentsMargins(20, 10, 20, 16)
        self.status = QLabel("Open a .cah file to start.")
        self.status.setObjectName("muted")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status, 1)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip("Write the hero back to its file with a refreshed checksum.")
        self.save_button.clicked.connect(self._save)
        self.save_button.setEnabled(False)
        footer.addWidget(self.save_button)
        outer.addWidget(footer_widget)

    def _build_menu(self) -> None:
        """A File menu (open / save / save as) and the standard Help menu."""
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction("&Open…", self._open)
        self.save_action = file_menu.addAction("&Save", self._save)
        self.save_as_action = file_menu.addAction("Save &As…", self._save_as)
        self.save_action.setEnabled(False)
        self.save_as_action.setEnabled(False)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)

        add_help_menu(
            self,
            guide_title="Getting started with SAGE Custom Hero",
            guide_html=_GETTING_STARTED_HTML,
            about_title="About SAGE Custom Hero",
            about_html=(
                f"<b>{APP_TITLE}</b>"
                "<p>Edit a BFME2 / RotWK Create-a-Hero <code>.cah</code> file: identity, class, "
                "colours, powers and bling, saved with the checksum the game validates.</p>"
                "<p>Load a game's data for completion over its real classes, powers and bling "
                "choices. The <code>sage-cah</code> command line offers the same file's "
                "<code>info</code>, <code>json</code>, <code>check</code> and <code>fix</code>."
                "</p>"
                "<p>File layout, enums and checksum reversed by withmorten.</p>"
            ),
            icon=QIcon(str(resource_path(ICON_FILE, __file__))),
        )

    def _build_hero_card(self) -> QWidget:
        frame, layout = card("Hero")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("the hero's name, as shown in game")
        self.name_edit.textChanged.connect(self._touch)
        grid.addWidget(QLabel("Name"), 0, 0)
        grid.addWidget(self.name_edit, 0, 1, 1, 3)

        self.class_combo = QComboBox()
        self.class_combo.currentIndexChanged.connect(self._on_class_changed)
        self.sub_combo = QComboBox()
        self.sub_combo.currentIndexChanged.connect(self._touch)
        grid.addWidget(QLabel("Class"), 1, 0)
        grid.addWidget(self.class_combo, 1, 1)
        grid.addWidget(QLabel("Sub-class"), 1, 2)
        grid.addWidget(self.sub_combo, 1, 3)

        self.objid_spin = QSpinBox()
        self.objid_spin.setRange(-(2**31), 2**31 - 1)
        self.objid_spin.setMaximumWidth(140)
        self.objid_spin.setToolTip("The obj_id field; 19, 55 and 57 are what shipped heroes use.")
        self.objid_spin.valueChanged.connect(self._touch)
        self.system_check = QCheckBox("System hero")
        self.system_check.setToolTip("Set on every hero the game ships.")
        self.system_check.toggled.connect(self._touch)
        grid.addWidget(QLabel("Object id"), 2, 0)
        grid.addWidget(self.objid_spin, 2, 1)
        grid.addWidget(self.system_check, 2, 3)

        colors = QHBoxLayout()
        colors.setSpacing(8)
        self.color_buttons: list[QPushButton] = []
        self.color_edits: list[QLineEdit] = []
        for slot in range(3):
            swatch = QPushButton()
            swatch.setFixedWidth(34)
            swatch.setToolTip("Pick this colour (the alpha byte is kept).")
            swatch.clicked.connect(lambda _checked, i=slot: self._pick_color(i))
            edit = QLineEdit()
            edit.setMaximumWidth(110)
            edit.setPlaceholderText("AARRGGBB")
            edit.editingFinished.connect(lambda i=slot: self._color_typed(i))
            colors.addWidget(swatch)
            colors.addWidget(edit)
            self.color_buttons.append(swatch)
            self.color_edits.append(edit)
        colors.addStretch(1)
        grid.addWidget(QLabel("Colours"), 3, 0)
        grid.addLayout(colors, 3, 1, 1, 3)

        self.guid_edit = QLineEdit()
        self.guid_edit.setPlaceholderText("the hero's GUID, as the game formats it")
        self.guid_edit.textChanged.connect(self._touch)
        guid_button = QPushButton("New GUID")
        guid_button.setToolTip("Assign a fresh GUID - a copied hero needs one to be its own.")
        guid_button.clicked.connect(self._new_guid)
        grid.addWidget(QLabel("GUID"), 4, 0)
        grid.addWidget(self.guid_edit, 4, 1, 1, 2)
        grid.addWidget(guid_button, 4, 3)

        layout.addLayout(grid)
        return frame

    def _build_powers_card(self) -> QWidget:
        frame, layout = card("Powers")
        hint = QLabel(
            "One row per power slot: the level it is bought at, the CommandButton it triggers, "
            "and its button index. An empty command button is an unused slot."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.powers_grid = QGridLayout()
        self.powers_grid.setHorizontalSpacing(10)
        self.powers_grid.setVerticalSpacing(4)
        layout.addLayout(self.powers_grid)
        return frame

    def _build_bling_card(self) -> QWidget:
        frame, layout = card("Bling")
        hint = QLabel(
            "The five attribute groups show the in-game value (one higher than the index the "
            "file stores); the appearance groups show the raw index into that sub-class's "
            "choices."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.bling_grid = QGridLayout()
        self.bling_grid.setHorizontalSpacing(10)
        self.bling_grid.setVerticalSpacing(4)
        layout.addLayout(self.bling_grid)
        return frame

    def _build_sources_card(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.loader = SourceLoader(
            self,
            build=load_cah_game_data,
            app_name=APP_NAME,
            on_loaded=self._on_data_loaded,
            collapse_on_load=True,
            verb="Scanning",
            noun="source",
            empty_message="Add the game folder or its .big archives first.",
            title="GAME DATA (OPTIONAL)",
            expanded_hint="GAME DATA - for class, power and bling completion",
            show_status=True,
            list_max_height=120,
        )
        self.loader.restore_saved()
        layout.addWidget(self.loader.panel)

        row = QHBoxLayout()
        detect = QPushButton("Find installed game")
        detect.setToolTip("Add the .big archives of a BfMe II / RotWK install found on this PC.")
        detect.clicked.connect(self._detect_game)
        row.addWidget(detect)
        row.addStretch(1)
        layout.addLayout(row)
        return holder

    def _hint_label(self) -> QLabel:
        """A muted label for the name a row resolves to. It may hold long text, so it is free to
        be clipped rather than widen the column the editable fields sit in - `_set_hint` puts the
        full text in its tooltip."""
        label = QLabel("")
        label.setObjectName("muted")
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def _set_hint(self, label: QLabel, text: str) -> None:
        """Show `text` on a hint label, keeping the untruncated text reachable as its tooltip."""
        label.setText(text)
        label.setToolTip(text)

    def _touch(self, *_args) -> None:
        """Mark the open hero edited (a no-op while its widgets are being filled)."""
        if self._loading or self.hero is None:
            return
        self._dirty = True
        self._update_title()

    def _update_title(self) -> None:
        name = self.path.name if self.path is not None else "no file"
        self.setWindowTitle(f"{APP_TITLE} - {name}{' *' if self._dirty else ''}")

    def _confirm_discard(self) -> bool:
        """True when it is safe to drop the open hero's edits - nothing is unsaved, or the
        user said so."""
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "This hero has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's own spelling
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    def _open(self) -> None:
        if not self._confirm_discard():
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Open a custom hero", self._last_dir, _CAH_FILTER
        )
        if chosen:
            self.load_path(Path(chosen))

    def load_path(self, path: Path) -> None:
        """Parse `path` and show the hero it holds, reporting a parse failure in the status
        line rather than raising. Public so a test (or a later command-line argument) can open
        a file without going through the dialog."""
        try:
            hero = parse_cah_from_path(path)
        except (CahError, OSError, UnicodeDecodeError) as exc:
            self.status.setText(f"Could not open {path.name} - {exc}")
            return
        self.hero = hero
        self.path = path
        self._last_dir = str(path.parent)
        self._dirty = False
        self._populate()
        state = "valid" if hero.checksum_valid else "stale, will be rewritten on save"
        self.status.setText(f"Opened {path.name} - checksum 0x{hero.checksum:08x} ({state}).")

    def _save(self) -> None:
        if self.path is None:
            self._save_as()
            return
        self._write_to(self.path)

    def _save_as(self) -> None:
        if self.hero is None:
            return
        suggested = str(self.path) if self.path is not None else self._last_dir
        chosen, _ = QFileDialog.getSaveFileName(self, "Save the hero as", suggested, _CAH_FILTER)
        if chosen:
            self._write_to(Path(chosen))

    def _write_to(self, path: Path) -> None:
        hero = self._collect()
        if hero is None:
            return
        try:
            write_cah_to_path(hero, path, refresh_checksum=True)
        except (CahError, OSError, UnicodeEncodeError) as exc:
            self.status.setText(f"Could not save {path.name} - {exc}")
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        hero.checksum = compute_checksum(hero)
        self.path = path
        self._last_dir = str(path.parent)
        self._dirty = False
        self._update_title()
        self.status.setText(f"Saved {path} - checksum 0x{hero.checksum:08x}.")

    def _collect(self) -> CustomHero | None:
        """The open hero with every edited field written back into it. None when no hero is
        open; the fields the editor does not show (the header ints, version, the reserved
        fields) keep the values they were parsed with."""
        hero = self.hero
        if hero is None:
            return None
        hero.name = self.name_edit.text()
        hero.obj_id = self.objid_spin.value()
        class_index = self.class_combo.currentData()
        sub_index = self.sub_combo.currentData()
        hero.class_index = hero.class_index if class_index is None else int(class_index)
        hero.sub_class_index = hero.sub_class_index if sub_index is None else int(sub_index)
        hero.color1, hero.color2, hero.color3 = self._colors
        hero.guid = self.guid_edit.text().strip()
        hero.is_system_hero = 1 if self.system_check.isChecked() else 0
        hero.powers = [
            CahPower(
                command_button=row.button.text().strip(),
                exp_level=row.level.value() - 1,
                button_index=row.index.value(),
            )
            for row in self._power_rows
        ]
        hero.blings = [
            CahBling(group_name=row.group.text().strip(), bling_index=self._stored_index(row))
            for row in self._bling_rows
        ]
        return hero

    def _populate(self) -> None:
        """Fill every widget from the open hero."""
        hero = self.hero
        if hero is None:
            return
        self._loading = True
        try:
            self.name_edit.setText(hero.name)
            self.objid_spin.setValue(hero.obj_id)
            self.system_check.setChecked(bool(hero.is_system_hero))
            self.guid_edit.setText(hero.guid)
            for slot, value in enumerate((hero.color1, hero.color2, hero.color3)):
                self._set_color(slot, value)
            self._rebuild_classes()
            self._rebuild_powers()
            self._rebuild_bling()
        finally:
            self._loading = False
        self.save_button.setEnabled(True)
        self.save_action.setEnabled(True)
        self.save_as_action.setEnabled(True)
        self._update_title()

    def _class_entries(self) -> list[tuple[int, str]]:
        """The classes to offer, as `(index, name)`: the loaded game's own, in the order
        `class_index` counts them, or the built-in display names when no game is loaded."""
        if self.data is not None and self.data.classes:
            return [(i, hero_class.name) for i, hero_class in enumerate(self.data.classes)]
        return sorted(CLASS_NAMES.items())

    def _sub_class_entries(self, class_index: int) -> list[tuple[int, str]]:
        """The sub-classes of `class_index`, as `(index, name)` (see `_class_entries`)."""
        if self.data is not None and self.data.classes:
            hero_class = self.data.hero_class(class_index)
            if hero_class is not None:
                return [(i, sub.name) for i, sub in enumerate(hero_class.sub_classes)]
            return []
        return sorted(SUB_CLASS_NAMES.get(class_index, {}).items())

    def _fill_combo(self, combo: QComboBox, entries: list[tuple[int, str]], current: int) -> None:
        """Refill `combo` with `entries` and select `current`, adding a bare entry for it when
        the data knows no such index - an index the editor cannot name is still an index the
        file holds, and must survive a save untouched."""
        blocked = combo.blockSignals(True)
        combo.clear()
        known = {index for index, _name in entries}
        for index, name in entries:
            combo.addItem(f"{name}  ({index})", index)
        if current not in known:
            combo.addItem(f"index {current}", current)
        combo.setCurrentIndex(combo.findData(current))
        combo.blockSignals(blocked)

    def _rebuild_classes(self) -> None:
        """Refill the class and sub-class combos from the current data, keeping the open
        hero's indices selected."""
        hero = self.hero
        if hero is None:
            return
        self._fill_combo(self.class_combo, self._class_entries(), hero.class_index)
        self._fill_combo(
            self.sub_combo, self._sub_class_entries(hero.class_index), hero.sub_class_index
        )
        self._refresh_powers_model()

    def _on_class_changed(self) -> None:
        """Follow a class change: its sub-classes, the powers it may buy, and the bling choices
        its indices count into all differ."""
        class_index = self.class_combo.currentData()
        if class_index is None:
            return
        current = self.sub_combo.currentData()
        entries = self._sub_class_entries(int(class_index))
        keep = current if any(index == current for index, _ in entries) else 0
        self._fill_combo(self.sub_combo, entries, int(keep))
        self._refresh_powers_model()
        self._refresh_hints()
        self._touch()

    def _rebuild_powers(self) -> None:
        """Lay out one row per power slot of the open hero."""
        clear_layout(self.powers_grid)
        self._power_rows = []
        hero = self.hero
        if hero is None:
            return

        for column, caption in enumerate(("Slot", "Level", "Command button", "Power", "Btn")):
            head = QLabel(caption)
            head.setObjectName("muted")
            self.powers_grid.addWidget(head, 0, column)
        self.powers_grid.setColumnStretch(2, 3)
        self.powers_grid.setColumnStretch(3, 2)

        for slot, power in enumerate(hero.powers):
            number = QLabel(str(slot))
            number.setObjectName("muted")

            level = QSpinBox()
            level.setRange(0, 99)
            level.setMaximumWidth(70)
            level.setToolTip("The in-game level this power is bought at; 0 is an unused slot.")
            level.setValue(power.level)
            level.valueChanged.connect(self._touch)

            button = QLineEdit(power.command_button)
            button.setPlaceholderText("(empty slot)")
            # A button name is longer than its field: show it from the start, since the tail
            # (`_Level2`) is the half these names share.
            button.setCursorPosition(0)
            button.setCompleter(make_completer(button, model=self._power_model))
            button.textChanged.connect(self._touch)

            hint = self._hint_label()

            index = QSpinBox()
            index.setRange(-99, 99)
            index.setMaximumWidth(64)
            index.setToolTip("The button_index field: 1-5 for a real power, 8 for the dummy.")
            index.setValue(power.button_index)
            index.valueChanged.connect(self._touch)

            row = _PowerRow(level=level, button=button, index=index, hint=hint)
            button.textChanged.connect(lambda _text, r=row: self._refresh_power_hint(r))
            self._power_rows.append(row)

            line = slot + 1
            self.powers_grid.addWidget(number, line, 0)
            self.powers_grid.addWidget(level, line, 1)
            self.powers_grid.addWidget(button, line, 2)
            self.powers_grid.addWidget(hint, line, 3)
            self.powers_grid.addWidget(index, line, 4)
            self._refresh_power_hint(row)

    def _rebuild_bling(self) -> None:
        """Lay out one row per bling entry of the open hero."""
        clear_layout(self.bling_grid)
        self._bling_rows = []
        hero = self.hero
        if hero is None:
            return

        for column, caption in enumerate(("Group", "Value / index", "Choice")):
            head = QLabel(caption)
            head.setObjectName("muted")
            self.bling_grid.addWidget(head, 0, column)
        self.bling_grid.setColumnStretch(0, 2)
        self.bling_grid.setColumnStretch(2, 3)

        for line, bling in enumerate(hero.blings, start=1):
            group = QLineEdit(bling.group_name)
            group.setCursorPosition(0)
            group.setCompleter(make_completer(group, model=self._group_model))
            group.textChanged.connect(self._touch)

            value = QSpinBox()
            value.setMaximumWidth(120)
            value.valueChanged.connect(self._touch)

            hint = self._hint_label()

            row = _BlingRow(group=group, value=value, hint=hint, attribute=False)
            self._apply_bling_mode(row, self._is_attribute(bling.group_name), bling.bling_index)
            group.textChanged.connect(lambda _text, r=row: self._on_group_changed(r))
            value.valueChanged.connect(lambda _value, r=row: self._refresh_bling_hint(r))
            self._bling_rows.append(row)

            self.bling_grid.addWidget(group, line, 0)
            self.bling_grid.addWidget(value, line, 1)
            self.bling_grid.addWidget(hint, line, 2)
            self._refresh_bling_hint(row)

    def _is_attribute(self, group_name: str) -> bool:
        """Whether `group_name` is a stat group, whose stored index is an in-game value minus
        one. The loaded game's own binder types it when there is one; the five groups the
        format ships with are known without any game data."""
        if self.data is not None:
            group = self.data.group(group_name)
            if group is not None:
                return group.is_attribute
        return group_name in BLING_STAT_GROUPS

    def _stored_index(self, row: _BlingRow) -> int:
        """The `bling_index` a row's spin box stands for."""
        return row.value.value() - 1 if row.attribute else row.value.value()

    def _apply_bling_mode(self, row: _BlingRow, attribute: bool, stored: int) -> None:
        """Set a row's spin box to show `stored` as an attribute value or a bare index, with a
        range wide enough for both the choices the data offers and the value already stored."""
        choices = len(self._bling_choices(row.group.text().strip()))
        blocked = row.value.blockSignals(True)
        row.attribute = attribute
        row.value.setPrefix("value " if attribute else "")
        shown = stored + 1 if attribute else stored
        floor = 1 if attribute else 0
        ceiling = choices - 1 + (1 if attribute else 0) if choices else 99
        row.value.setRange(min(floor, shown), max(ceiling, shown))
        row.value.setValue(shown)
        row.value.blockSignals(blocked)

    def _on_group_changed(self, row: _BlingRow) -> None:
        """Re-read a row after its group name was edited, keeping the stored index it holds
        even when the group changed from an attribute to an appearance one (or back)."""
        stored = self._stored_index(row)
        self._apply_bling_mode(row, self._is_attribute(row.group.text().strip()), stored)
        self._refresh_bling_hint(row)

    def _bling_choices(self, group_name: str) -> tuple[BlingOption, ...]:
        """The choices the current class and sub-class give `group_name`, or empty without
        game data."""
        if self.data is None or not group_name:
            return ()
        class_index = self.class_combo.currentData()
        sub_index = self.sub_combo.currentData()
        if class_index is None or sub_index is None:
            return ()
        return self.data.bling_choices(group_name, int(class_index), int(sub_index))

    def _refresh_power_hint(self, row: _PowerRow) -> None:
        """Name the power a row's command button triggers, once game data can name it."""
        name = row.button.text().strip()
        if self.data is None or not name:
            self._set_hint(row.hint, "")
            return
        power = self._power_index.get(name.lower())
        if power is None:
            self._set_hint(row.hint, "not in the loaded data")
            return
        level = f" - from level {power.min_level}" if power.min_level is not None else ""
        self._set_hint(row.hint, f"{power.display}{level}")

    def _refresh_bling_hint(self, row: _BlingRow) -> None:
        """Name the choice a row's index picks, once game data can name it. An attribute's
        choices carry no name of their own, so those rows show the group's in-game name
        instead - which is the useful half there, a mod renames these freely."""
        group_name = row.group.text().strip()
        group = self.data.group(group_name) if self.data is not None else None
        choices = self._bling_choices(group_name)
        if group is None or not choices:
            self._set_hint(row.hint, "")
            return
        stored = self._stored_index(row)
        if not 0 <= stored < len(choices):
            self._set_hint(row.hint, f"no choice {stored} in this group")
            return
        self._set_hint(row.hint, choices[stored].label or group.display)

    def _refresh_hints(self) -> None:
        for power_row in self._power_rows:
            self._refresh_power_hint(power_row)
        for bling_row in self._bling_rows:
            self._on_group_changed(bling_row)

    def _refresh_powers_model(self) -> None:
        """Refill the power completion list with what the selected class may buy, falling back
        to every Create-a-Hero power when the data offers nothing for it."""
        if self.data is None:
            self._power_model.setStringList([])
            self._power_index = {}
            return
        class_index = self.class_combo.currentData()
        powers = self.data.powers_for(int(class_index)) if class_index is not None else ()
        if not powers:
            powers = self.data.powers
        self._power_model.setStringList([power.command_button for power in powers])
        self._power_index = {power.command_button.lower(): power for power in self.data.powers}

    def _on_data_loaded(self, data: CahGameData) -> None:
        """Take a finished scan: the class lists, completions and hints all come from it."""
        self.data = data
        self._group_model.setStringList([group.group_name for group in data.bling_groups])
        self._loading = True
        try:
            self._rebuild_classes()
            self._refresh_hints()
        finally:
            self._loading = False
        if self.loader.panel is not None and self.loader.panel.status is not None:
            self.loader.panel.status.setText(
                f"{len(data.classes)} classes, {len(data.powers)} powers, "
                f"{len(data.bling_groups)} bling groups."
            )

    def _detect_game(self) -> None:
        """Fill the source list with the archives of an installed game found on this PC."""
        installs = find_installs()
        if not installs:
            self.status.setText("No BfMe II or RotWK install found - add the folders by hand.")
            return
        install = installs[0]
        archives = [path for path in (install.path / "ini.big",) if path.is_file()]
        lang = install.path / "lang"
        if lang.is_dir():
            archives += sorted(lang.glob("*.big"))
        if not archives:
            self.loader.set_sources([("folder", str(install.path))])
        else:
            self.loader.set_sources([("big", str(path)) for path in archives])
        self.status.setText(f"Added {install.title} - press Load to scan it.")

    def _new_guid(self) -> None:
        self.guid_edit.setText(new_guid())

    def _set_color(self, slot: int, value: int) -> None:
        """Show `value` (an AARRGGBB word) in one colour slot's swatch and hex field."""
        self._colors[slot] = value & 0xFFFFFFFF
        self.color_edits[slot].setText(f"{self._colors[slot]:08X}")
        color = QColor.fromRgba(self._colors[slot])
        self.color_buttons[slot].setStyleSheet(
            f"background-color: rgb({color.red()}, {color.green()}, {color.blue()});"
        )

    def _pick_color(self, slot: int) -> None:
        """Pick a colour, keeping the stored alpha byte - the game's own heroes all carry
        0xFF there, and nothing in the editor should quietly change it."""
        current = QColor.fromRgba(self._colors[slot])
        chosen = QColorDialog.getColor(current, self, "Pick a hero colour")
        if not chosen.isValid():
            return
        alpha = self._colors[slot] & 0xFF000000
        self._set_color(slot, alpha | (chosen.rgb() & 0x00FFFFFF))
        self._touch()

    def _color_typed(self, slot: int) -> None:
        """Take a hand-typed AARRGGBB word, restoring the old one when it is not hex."""
        try:
            value = int(self.color_edits[slot].text().strip().removeprefix("0x"), 16)
        except ValueError:
            self._set_color(slot, self._colors[slot])
            return
        self._set_color(slot, value)
        self._touch()
