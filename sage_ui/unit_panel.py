"""The full stat view of one SAGE object — one self-contained `UnitPanel` holding its
own `UnitState`, so its toggles re-resolve only its own stats. `Browser` stacks two
side by side and wires up the `changed`, `closed` and `navigate` signals."""

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sage_ini.model.game import Game
from sage_ini.model.state import (
    UnitState,
    horde_members,
    hordes_containing,
    level_up_rank_floor,
    level_up_trigger_upgrades,
    select_command_set,
    select_weapon_set,
    set_conditions,
)
from sage_ui.layout import clear_layout
from sage_utils.textures import crop_mapped_image, render_portrait
from sage_utils.views import (
    armorset_view,
    build_cost_view,
    builders_of,
    clean_text,
    command_button_images,
    command_buttons_view,
    description,
    display_name,
    effective_health,
    effective_health_against,
    fmt_stat,
    modifier_view,
    mounted_template,
    object_button_image,
    object_detail,
    percent,
    resource_production_view,
    safe,
    select_portrait_image,
    special_power_view,
    upgrade_label,
    upgrade_toggle_labels,
    weapon_dps,
    weapon_set_view,
    weapon_top_nugget,
)
from sage_utils.widgets import (
    CopyableLabel as QLabel,  # info labels are selectable/copyable by default
)
from sage_utils.widgets import card, pil_to_pixmap


class UnitPanel(QWidget):
    """The full stat view of one object. Emits `changed` whenever a stat is recomputed
    (to refresh a side-by-side comparison) and `closed` when its remove button is pressed."""

    changed = pyqtSignal()
    closed = pyqtSignal()
    navigate = pyqtSignal(str)  # a UNIT_BUILD button asks to open the named object

    def __init__(
        self,
        game: Game,
        obj,
        *,
        removable: bool = False,
        mirrored: bool = False,
        texture_source=None,
        portrait_background=None,
    ) -> None:
        super().__init__()
        self.game = game
        self._current_obj = obj  # what was selected (a unit, or a horde)
        self._removable = removable
        self._mirrored = mirrored
        # Indexed texture sources (a TextureSource) for the inline portrait and command-button
        # icons, with the parchment background; both None until image sources are loaded.
        self._texture_source = texture_source
        self._portrait_background = portrait_background
        self._portrait_label: QLabel | None = None
        # Cropped button icons cached by MappedImage name so a palette rebuild doesn't redecode.
        self._icon_cache: dict[str, object] = {}
        self.upgrade_toggles: dict[str, QCheckBox] = {}
        # Raw template id shown as a toggle's tooltip when its label is the friendly display
        # name, so the underlying id stays discoverable (and survives a rank-grant re-sync).
        self._upgrade_tooltips: dict[str, str] = {}
        self._weapon_toggle_flags: set[str] = set()  # TOGGLE_WEAPONSET flips these on
        # SpecialPowerModule powers toggled on, by name -> their AttributeModifier list.
        self._active_special_modifiers: dict[str, object] = {}
        # Expanded command-button details, by name. Kept here (not on the widgets) so a
        # detail re-opens when the palette rebuilds (e.g. after a weapon-set flip).
        self._expanded_buttons: set[str] = set()
        self._commands_box = None
        self._loco_box = None
        self._production_box = None  # only built when the unit produces resources
        self._active_source = None
        self._rank_picker = None
        self._manual_rank = None  # the rank the user last picked (None = lowest)
        self._weapons: list[dict] = []

        self._init_sources()
        # A horde fielding this unit carries the group's experience levels, so its rank
        # modifiers feed the member's stats.
        rank_targets = [src for _label, src in self._cost_sources if src is not self._unit_obj]
        self._unit_state = UnitState(self._unit_obj, rank_targets=rank_targets)  # combat stats
        self._source_state = self._unit_state  # cost source's state (drives locomotor)

        # Two columns: inside holds the comparable stats, outside holds upgrades/ranks/
        # command buttons. Mirroring panel A faces the two units' stats inward in a comparison.
        self.setMinimumWidth(520)
        self._stats_column = QVBoxLayout()
        self._aux_column = QVBoxLayout()
        for col in (self._stats_column, self._aux_column):
            col.setSpacing(12)
            col.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._columns_row = QHBoxLayout()
        self._columns_row.setSpacing(12)
        self._columns_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._arrange_columns()

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(12)
        self._root.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._build()

    def _arrange_columns(self) -> None:
        """(Re)order the inside (stats) and outside (aux) columns. Mirrored puts stats
        last so panel A's stats meet panel B's in the middle; otherwise stats lead."""
        while self._columns_row.count():
            self._columns_row.takeAt(0)
        order = (
            (self._aux_column, self._stats_column)
            if self._mirrored
            else (self._stats_column, self._aux_column)
        )
        for col in order:
            self._columns_row.addLayout(col, 1)

    def set_mirrored(self, mirrored: bool) -> None:
        """Flip the column order (used to face two panels' stats inward)."""
        if mirrored != self._mirrored:
            self._mirrored = mirrored
            self._arrange_columns()

    def _init_sources(self) -> None:
        """Resolve the combat unit and the cost/locomotor source list. A horde's combat
        stats live on its contained unit while cost, command palette and locomotor live on
        the horde; for a plain unit it is both, and any horde fielding it is an alternate
        source (a unit only built in a horde carries its cost there)."""
        obj = self._current_obj
        members = []
        for name in horde_members(obj):
            member = self.game.objects.get(name)
            if member is not None and member not in members:
                members.append(member)

        if members:  # obj is a horde — stats from the contained unit
            self._unit_obj = members[0]
            self._cost_sources = [(f"Horde · {obj.name}", obj)]
            self._default_source = 0
        else:
            self._unit_obj = obj
            hordes = hordes_containing(self.game, obj.name)
            self._cost_sources = [("This unit", obj)] + [(f"Horde · {h.name}", h) for h in hordes]
            # Prefer the horde's cost when the unit lists none of its own.
            self._default_source = (
                1 if len(self._cost_sources) > 1 and not build_cost_view(obj)["BuildCost"] else 0
            )

    def header_name(self) -> str:
        """The localized display name of the selected object, or its raw name."""
        return display_name(self.game, self._current_obj) or self._current_obj.name

    def command_set_extract(self) -> tuple[str, list[dict]]:
        """The active command set's name and its buttons' ButtonImages, for the
        extract-image tool. The palette follows the same active source/upgrades the
        Command buttons card shows; `("", [])` when the unit displays no command set.
        """
        source = self._active_source or self._current_obj
        command_set = select_command_set(source, self._unit_state.effective_upgrades)
        if command_set is None:
            return "", []
        return command_set.name, command_button_images(self.game, command_set)

    def object_image_entries(self) -> list[dict]:
        """The unit's `SelectPortrait` and `ButtonImage` as extract entries (shaped like
        `command_button_images` entries). A horde carries no portrait of its own, so the
        portrait comes from the contained combat unit (`_unit_obj`); the button still tries
        the selected object first. Each falls back to the other object so nothing is lost."""
        entries: list[dict] = []
        resolvers = (
            ("Portrait", select_portrait_image, (self._unit_obj, self._current_obj)),
            ("Button", object_button_image, (self._current_obj, self._unit_obj)),
        )
        for label, resolve, candidates in resolvers:
            for obj in candidates:
                images = resolve(obj)
                if images:
                    entries.append({"name": f"{obj.name}_{label}", "text": label, "image": images})
                    break
        return entries

    def basic_stats(self) -> list[tuple[str, float | None, bool]]:
        """The headline (label, value, higher_is_better) stats for comparison: cost from
        the active source, combat stats carrying the active upgrades/rank."""
        cost = build_cost_view(self._active_source or self._unit_obj)
        state = self._unit_state
        profile = self._attack_profile()
        return [
            ("Max health", state.max_health, True),
            ("Build cost", cost["BuildCost"], False),
            ("Build time", cost["BuildTime"], False),
            ("Command points", cost["CommandPoints"], False),
            ("Vision range", state.vision, True),
            ("Speed", self._source_speed(), True),
            ("Top damage", self._top_damage(), True),
            ("Damage per second", profile[0] if profile else None, True),
        ]

    def _source_speed(self) -> float | None:
        """The active source's locomotor speed with the active SPEED modifiers."""
        return self._source_state.speed

    def _active_weapon_set(self):
        """The active WeaponSet, with the upgrade-driven weapon flags unioned with any
        a TOGGLE_WEAPONSET button has flipped on."""
        flags = self._unit_state.weapon_flags | self._weapon_toggle_flags
        return select_weapon_set(self._unit_obj, flags)

    def _top_damage(self) -> float | None:
        """The single hardest-hitting nugget of the active weapon set (modified)."""
        weapon_set = self._active_weapon_set()
        if weapon_set is None:
            return None
        best = None
        for weapon in weapon_set_view(weapon_set, self._unit_state.effective_upgrades):
            for nugget in weapon["nuggets"]:
                base = nugget["damage"]
                if base is None:
                    continue
                damage = self._unit_state.weapon_damage(base, nugget["damage_type"])
                if best is None or damage > best:
                    best = damage
        return best

    @staticmethod
    def _empty(layout) -> None:
        clear_layout(layout)

    def _build(self) -> None:
        # Combat stats come from the contained unit; the header still names what was selected.
        o = object_detail(self._unit_obj)

        head, layout = card()
        title_row = QHBoxLayout()
        # The unit's portrait, cropped from the loaded textures (hidden until one resolves).
        self._portrait_label = QLabel()
        self._portrait_label.setObjectName("portrait")
        self._portrait_label.setVisible(False)
        title_row.addWidget(self._portrait_label, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        # Prefer the localized DisplayName, keeping the raw name and type as a subtitle.
        shown = display_name(self.game, self._current_obj)
        name = QLabel(shown or self._current_obj.name)
        name.setObjectName("objName")
        kind_text = type(self._current_obj).__name__
        if shown:
            kind_text = f"{self._current_obj.name} · {kind_text}"
        kind = QLabel(kind_text)
        kind.setObjectName("objType")
        names.addWidget(name)
        names.addWidget(kind)
        # The description sits beside the portrait, under the name, rather than below the row.
        desc = clean_text(description(self.game, self._current_obj))
        if desc:
            desc_label = QLabel(desc)
            desc_label.setObjectName("muted")
            desc_label.setWordWrap(True)
            names.addWidget(desc_label)
        title_row.addLayout(names, 1)
        if self._removable:
            close = QPushButton("✕")
            close.setObjectName("closePanel")
            close.setFixedWidth(28)
            close.setToolTip("Remove this unit from the comparison")
            close.clicked.connect(self.closed.emit)
            title_row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)
        self._root.addWidget(head)
        self._root.addLayout(self._columns_row, 1)

        # Inside column: the comparable stats.
        self._build_cost_card()

        hp_card, hlayout = card("Max health")
        self._hp_box = QVBoxLayout()
        hlayout.addLayout(self._hp_box)
        self._stats_column.addWidget(hp_card)

        vision_card, vlayout = card("Vision range")
        self._vision_box = QVBoxLayout()
        vlayout.addLayout(self._vision_box)
        self._stats_column.addWidget(vision_card)

        armor_card, alayout = card("Armor sets")
        self._armor_box = QVBoxLayout()
        self._armor_box.setSpacing(6)
        alayout.addLayout(self._armor_box)
        self._stats_column.addWidget(armor_card)

        # Effective health — collapsed by default behind a clickable header.
        effective_card, elayout = card()
        self._effective_header = QPushButton()
        self._effective_header.setObjectName("sectionHeader")
        self._effective_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._effective_header.clicked.connect(self._toggle_effective_health)
        self._effective_body = QWidget()
        self._effective_body.setStyleSheet("QWidget { background: transparent; }")
        self._effective_box = QVBoxLayout(self._effective_body)
        self._effective_box.setContentsMargins(0, 0, 0, 0)
        self._effective_body.setVisible(False)  # collapsed by default
        self._update_effective_header()
        elayout.addWidget(self._effective_header)
        elayout.addWidget(self._effective_body)
        self._stats_column.addWidget(effective_card)

        weapon_card, wlayout = card("Weapons")
        self._weapon_box = QVBoxLayout()
        self._weapon_box.setSpacing(6)
        wlayout.addLayout(self._weapon_box)
        self._stats_column.addWidget(weapon_card)

        loco_card, llayout = card("Locomotor")
        self._loco_box = QVBoxLayout()
        self._loco_box.setSpacing(6)
        llayout.addLayout(self._loco_box)
        self._stats_column.addWidget(loco_card)

        # Outside column: upgrades, ranks, command buttons.
        self._build_rank_card()
        self._build_mounted_card()
        self._build_built_by_card()

        # Possible upgrades — the object's own upgrade gates plus the LevelUpUpgrade
        # triggers (toggling one raises the veterancy rank).
        upgrade_card, ulayout = card("Possible upgrades")
        upgrade_names = list(o["upgrades"])
        for name in self._level_up_trigger_upgrades():
            if name not in upgrade_names:
                upgrade_names.append(name)
        if not upgrade_names:
            m = QLabel("None.")
            m.setObjectName("muted")
            ulayout.addWidget(m)
        else:
            # Show the localized ability name ("Fire Arrows") rather than the raw template id,
            # disambiguating duplicate names by appending the id; keep the id as a tooltip.
            labels = upgrade_toggle_labels(self.game, upgrade_names)
            for upgrade in upgrade_names:
                toggle = QCheckBox(labels[upgrade])
                if labels[upgrade] != upgrade:
                    self._upgrade_tooltips[upgrade] = upgrade
                    toggle.setToolTip(upgrade)
                toggle.toggled.connect(
                    lambda checked, name=upgrade: self._on_upgrade_toggled(name, checked)
                )
                self.upgrade_toggles[upgrade] = toggle
                ulayout.addWidget(toggle)
        self._aux_column.addWidget(upgrade_card)

        commands_card, clayout = card("Command buttons")
        self._commands_box = QVBoxLayout()
        self._commands_box.setSpacing(6)
        clayout.addLayout(self._commands_box)
        self._aux_column.addWidget(commands_card)

        # Every stat box exists now; resolve them all, then reflect the starting rank's grants.
        self._refresh_stats()
        self._sync_rank_grants()
        self._refresh_portrait()

    def apply_textures(self, texture_source, portrait_background) -> None:
        """Adopt newly indexed texture sources and (re)render the portrait and button icons —
        called when image sources finish loading after the panel is already shown."""
        self._texture_source = texture_source
        self._portrait_background = portrait_background
        self._icon_cache.clear()
        self._refresh_portrait()
        self._refresh_commands()

    def _refresh_portrait(self) -> None:
        """(Re)show the unit's portrait from the textures, or hide the slot when there are no
        textures loaded or the object defines none."""
        if self._portrait_label is None:
            return
        pixmap = self._portrait_pixmap()
        if pixmap is None:
            self._portrait_label.clear()
            self._portrait_label.setVisible(False)
            return
        self._portrait_label.setPixmap(pixmap)
        self._portrait_label.setVisible(True)

    def _portrait_pixmap(self):
        """The unit's portrait composited on the parchment background and scaled to fit, or
        None when no textures are loaded or its texture isn't among them."""
        if self._texture_source is None:
            return None
        picture = render_portrait(
            self._texture_source, self._current_obj, self._portrait_background
        )
        if picture is None:
            return None
        pixmap = pil_to_pixmap(picture)
        target = 112
        if pixmap.width() > target or pixmap.height() > target:
            pixmap = pixmap.scaled(
                target,
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return pixmap

    def _command_icon(self, images) -> QIcon | None:
        """A QIcon for a command button's `ButtonImage` list (its first image), cropped from
        the textures and cached by name. None when no textures are loaded, the button has no
        image, or its texture isn't found."""
        if self._texture_source is None or not images:
            return None
        image = images[0]
        key = getattr(image, "name", None) or str(id(image))
        if key not in self._icon_cache:
            picture = crop_mapped_image(self._texture_source, image)
            self._icon_cache[key] = pil_to_pixmap(picture) if picture is not None else None
        pixmap = self._icon_cache[key]
        return QIcon(pixmap) if pixmap is not None else None

    def _build_cost_card(self) -> None:
        """The "Stats" card: the active source's economy stats plus resource income. A
        source picker is shown only when there is more than one; a producer's income rows
        appear below the cost, a non-producer adds none."""
        cost_card, layout = card("Stats")
        default = self._default_source
        if len(self._cost_sources) > 1:
            picker = QComboBox()
            for label, _source in self._cost_sources:
                picker.addItem(label)
            picker.setCurrentIndex(default)
            picker.currentIndexChanged.connect(self._show_cost)
            layout.addWidget(picker)

        self._cost_box = QVBoxLayout()
        layout.addLayout(self._cost_box)

        # Resource income, under the cost, only when the unit produces (else no box, so
        # `_refresh_production` is a no-op).
        view = resource_production_view(self._unit_obj)
        if view["MaxIncome"] is None and view["DepositAmount"] is None:
            self._production_box = None
        else:
            self._production_box = QVBoxLayout()
            layout.addLayout(self._production_box)

        self._stats_column.addWidget(cost_card)
        self._show_cost(default)
        self._refresh_production()

    def _show_cost(self, index: int) -> None:
        """Show the build cost / time / command points of the chosen source, which also
        drives the command palette and locomotor (a horde shows its group movement and
        buttons); health, armor and weapons stay the contained unit's."""
        self._empty(self._cost_box)
        if not 0 <= index < len(self._cost_sources):
            return
        self._active_source = self._cost_sources[index][1]
        self._source_state = (
            self._unit_state
            if self._active_source is self._unit_obj
            else UnitState(self._active_source)
        )
        if self._commands_box is not None:  # built after the cost card; refresh on change
            self._refresh_commands()
        if self._loco_box is not None:  # likewise — follows the source's locomotor
            self._refresh_locomotor()
        view = build_cost_view(self._active_source)
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        rows = [
            ("Build cost", view["BuildCost"]),
            ("Build time", view["BuildTime"]),
            ("Command points", view["CommandPoints"]),
        ]
        # Bounty (resources a killer earns) is shown only when the unit awards one.
        if view["BountyValue"]:
            rows.append(("Bounty value", view["BountyValue"]))
        for row, (name, value) in enumerate(rows):
            grid.addWidget(QLabel(name), row, 0)
            value_label = QLabel(fmt_stat(value))
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            if value is None:
                value_label.setObjectName("muted")
            grid.addWidget(value_label, row, 1)
        grid.setColumnStretch(0, 1)
        self._cost_box.addWidget(wrap)
        self.changed.emit()

    def _build_rank_card(self) -> None:
        """A dropdown over the object's experience ranks, or a muted note if none."""
        rank_card, rlayout = card("Experience rank")
        selector = self._unit_state.ranks
        if not selector.levels:
            self._rank_picker = None
            note = QLabel("No experience levels.")
            note.setObjectName("muted")
            rlayout.addWidget(note)
            self._aux_column.addWidget(rank_card)
            return

        picker = QComboBox()
        for level, rank in zip(selector.levels, selector.ranks, strict=True):
            picker.addItem(f"Rank {rank:g} — {level.name}", rank)
        picker.setCurrentIndex(selector.index)
        picker.currentIndexChanged.connect(self._on_rank_changed)
        self._rank_picker = picker
        rlayout.addWidget(picker)

        # Per-level experience: the level's own threshold (not cumulative) and its kill award.
        self._rank_xp_box = QVBoxLayout()
        rlayout.addLayout(self._rank_xp_box)
        self._refresh_rank_experience()

        self._rank_summary = QLabel("")
        self._rank_summary.setObjectName("muted")
        self._rank_summary.setWordWrap(True)
        rlayout.addWidget(self._rank_summary)
        self._aux_column.addWidget(rank_card)

    def _build_mounted_card(self) -> None:
        """A navigable link to the unit's mounted form, when a ToggleMountedSpecialAbilityUpdate
        names one. No card when there is none."""
        mounted = mounted_template(self._unit_obj)
        if mounted is None:
            return
        mount_card, mlayout = card("Mounted form")
        obj = self.game.objects.get(mounted)
        label = display_name(self.game, obj) if obj is not None else None
        button = QPushButton(f"{label or mounted}  →")
        if obj is None:
            button.setEnabled(False)
            button.setToolTip("Not loaded")
        else:
            button.clicked.connect(lambda _=False, n=mounted: self.navigate.emit(n))
        mlayout.addWidget(button)
        self._aux_column.addWidget(mount_card)

    def _build_built_by_card(self) -> None:
        """A "Where is this built?" button listing the structures that train this object
        (the inverse of a UNIT_BUILD button). No card when nothing builds it."""
        builders = builders_of(self.game, self._current_obj.name)
        if not builders:
            return
        built_by_card, layout = card("Built by")
        button = QPushButton(f"Where is this built?  ({len(builders)})")
        button.setToolTip("Show the structures that build this object")
        detail = QVBoxLayout()
        detail.setContentsMargins(16, 0, 0, 4)
        button.clicked.connect(lambda _=False, b=builders, d=detail: self._toggle_builders(b, d))
        layout.addWidget(button)
        layout.addLayout(detail)
        self._aux_column.addWidget(built_by_card)

    def _toggle_builders(self, builders: list[str], detail) -> None:
        """Show/hide the builder list — each a link that opens that structure."""
        if detail.count():
            clear_layout(detail)
            return
        for name in builders:
            obj = self.game.objects.get(name)
            label = display_name(self.game, obj) if obj is not None else None
            builder_button = QPushButton(f"{label or name}  →")
            if obj is None:
                builder_button.setEnabled(False)
                builder_button.setToolTip("Not loaded")
            else:
                builder_button.clicked.connect(lambda _=False, n=name: self.navigate.emit(n))
            detail.addWidget(builder_button)

    def _refresh_rank_experience(self) -> None:
        """(Re)show the selected level's required and kill-award experience."""
        self._empty(self._rank_xp_box)
        selector = self._unit_state.ranks
        rows = (
            ("Experience required", selector.required_experience),
            ("Experience when killed", selector.experience_award),
        )
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 2, 0, 4)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        for row, (name, value) in enumerate(rows):
            grid.addWidget(QLabel(name), row, 0)
            value_label = QLabel(fmt_stat(value))
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            if value is None:
                value_label.setObjectName("muted")
            grid.addWidget(value_label, row, 1)
        grid.setColumnStretch(0, 1)
        self._rank_xp_box.addWidget(wrap)

    def _on_rank_changed(self, index: int) -> None:
        self._manual_rank = self._rank_picker.itemData(index)
        self._apply_rank()
        self._refresh_rank_experience()
        self._sync_rank_grants()
        self._refresh_stats()

    def _level_up_objects(self) -> list:
        """The combat unit plus its cost sources — a horde holds the LevelUpUpgrade."""
        objs = [self._unit_obj]
        for _label, source in self._cost_sources:
            if source not in objs:
                objs.append(source)
        return objs

    def _level_up_trigger_upgrades(self) -> list[str]:
        """Distinct LevelUpUpgrade trigger upgrades across the unit and its hordes."""
        names: list[str] = []
        for obj in self._level_up_objects():
            for name in level_up_trigger_upgrades(obj):
                if name not in names:
                    names.append(name)
        return names

    def _rank_floor(self):
        """The rank the active LevelUpUpgrades raise the unit to (or None)."""
        base = self._unit_state.ranks.min_rank
        if base is None:
            return None
        active = self._unit_state.effective_upgrades
        floor = base
        for obj in self._level_up_objects():
            floor = max(floor, level_up_rank_floor(obj, active, base))
        return floor

    def _apply_rank(self) -> None:
        """Apply the effective rank — the manual pick raised to the LevelUp floor — to the
        unit state and sync the picker to it."""
        floor = self._rank_floor()
        manual = self._manual_rank if self._manual_rank is not None else floor
        rank = manual if floor is None else (floor if manual is None else max(manual, floor))
        if rank is None:
            return
        self._unit_state.set_rank(rank)
        if self._rank_picker is not None:
            self._rank_picker.blockSignals(True)
            self._rank_picker.setCurrentIndex(self._unit_state.ranks.index)
            self._rank_picker.blockSignals(False)

    def _sync_rank_grants(self) -> None:
        """Show the rank's granted upgrades checked and locked (they are active regardless
        of their checkbox); the rest follow the manually-toggled set. Signals are blocked so
        syncing never mutates it."""
        granted = self._unit_state.ranks.granted_upgrades
        for name, toggle in self.upgrade_toggles.items():
            toggle.blockSignals(True)
            if name in granted:
                toggle.setChecked(True)
                toggle.setEnabled(False)
                toggle.setToolTip("Granted by the current rank")
            else:
                toggle.setEnabled(True)
                toggle.setToolTip(self._upgrade_tooltips.get(name, ""))  # restore the raw id
                toggle.setChecked(name in self._unit_state.active_upgrades)
            toggle.blockSignals(False)

        picker = self._rank_picker
        if picker is not None:
            mods = [m.name for m in self._unit_state.ranks.modifier_lists]
            extra = sorted(granted - set(self.upgrade_toggles))
            parts = []
            if granted:
                parts.append(f"{len(granted)} upgrade(s) granted")
            if mods:
                parts.append(f"{len(mods)} modifier list(s)")
            if extra:
                shown = ", ".join(upgrade_label(self.game, name) for name in extra)
                parts.append("not shown above: " + shown)
            self._rank_summary.setText(" · ".join(parts))

    def _on_upgrade_toggled(self, name: str, checked: bool) -> None:
        self._unit_state.set_upgrade(name, checked)
        self._apply_rank()  # a LevelUpUpgrade trigger may raise or release the rank
        if self._rank_picker is not None:
            self._refresh_rank_experience()
        self._sync_rank_grants()
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        self._refresh_health()
        self._refresh_vision()
        self._refresh_armor()
        self._refresh_effective_health()
        self._refresh_weapons()
        self._refresh_locomotor()
        self._refresh_production()
        self._refresh_commands()
        self.changed.emit()

    def _refresh_production(self) -> None:
        """(Re)show resource income/deposit per pulse, each amount scaled by the PRODUCTION
        factor and coloured against its base, with the (unmodified) interval appended."""
        if self._production_box is None:
            return
        self._empty(self._production_box)
        view = resource_production_view(self._unit_obj)
        multiplier = self._unit_state.production_multiplier

        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        row = 0
        for amount_key, interval_key, label in (
            ("MaxIncome", "IncomeInterval", "Income"),
            ("DepositAmount", "DepositTiming", "Deposit"),
        ):
            base = view[amount_key]
            if base is None:
                continue
            modified = base * multiplier
            interval = view[interval_key]
            suffix = f"  /  {fmt_stat(interval)}s" if interval is not None else ""
            grid.addWidget(QLabel(label), row, 0)
            value = self._stat_label(f"{fmt_stat(modified)}{suffix}", modified, base)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(value, row, 1)
            row += 1
        grid.setColumnStretch(0, 1)
        self._production_box.addWidget(wrap)

    def _update_effective_header(self) -> None:
        arrow = "▾" if self._effective_body.isVisible() else "▸"
        self._effective_header.setText(f"{arrow}  EFFECTIVE HEALTH")

    def _toggle_effective_health(self) -> None:
        self._effective_body.setVisible(not self._effective_body.isVisible())
        self._update_effective_header()

    def _refresh_effective_health(self) -> None:
        """(Re)show effective HP per damage type, the toughest type marked better and the
        most vulnerable worse. Nothing to show with no armor or no health."""
        self._empty(self._effective_box)
        effective = effective_health(self._unit_state)
        if not effective:
            none = QLabel("—")
            none.setObjectName("muted")
            self._effective_box.addWidget(none)
            return

        toughest, weakest = max(effective.values()), min(effective.values())
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        for row, (damage_type, value) in enumerate(effective.items()):
            grid.addWidget(QLabel(damage_type), row, 0)
            cell = QLabel(f"{value:.0f}")
            cell.setAlignment(Qt.AlignmentFlag.AlignRight)
            # Only distinguish extremes when the types actually differ.
            if toughest != weakest and value == toughest:
                cell.setObjectName("better")
            elif toughest != weakest and value == weakest:
                cell.setObjectName("worse")
            grid.addWidget(cell, row, 1)
        grid.setColumnStretch(0, 1)
        self._effective_box.addWidget(wrap)

    def _attack_profile(self) -> tuple[float, str | None] | None:
        """The unit's best sustained attack as `(dps, damage_type)`, or None: the
        highest-DPS weapon of the active set, its hardest nugget's damage type."""
        weapon_set = self._active_weapon_set()
        if weapon_set is None:
            return None
        best = None
        for entry in safe(lambda ws=weapon_set: ws.Weapon, []) or []:
            _slot, weapon = entry
            if weapon is None:
                continue
            dps = weapon_dps(weapon, self._unit_state)
            if dps is not None and (best is None or dps > best[0]):
                best = (dps, weapon_top_nugget(weapon, self._unit_state)[1])
        return best

    def effective_health_vs(self, damage_type) -> float | None:
        """The unit's effective HP against `damage_type` (for the comparison's TTK)."""
        return effective_health_against(self._unit_state, damage_type)

    @staticmethod
    def _active_label(conditions: set[str]) -> QLabel:
        """A header naming a set's conditions (or 'default'), styled as active."""
        text = " ".join(sorted(conditions)) if conditions else "default"
        label = QLabel(f"{text}    ● active")
        label.setObjectName("conditions")
        return label

    @staticmethod
    def _stat_label(
        text: str, modified, base, inverse: bool = False, default_name: str = ""
    ) -> QLabel:
        """A value label, green when better than base and red when worse (`inverse=True`
        for armor scalars, where lower is better). When unchanged it keeps `default_name`."""
        label = QLabel(text)
        name = default_name
        if modified is not None and base is not None and modified != base:
            better = (modified < base) if inverse else (modified > base)
            name = "better" if better else "worse"
        if name:
            label.setObjectName(name)
        return label

    def _refresh_health(self) -> None:
        self._empty(self._hp_box)
        modified, base = self._unit_state.max_health, self._unit_state.base_max_health
        self._hp_box.addWidget(self._stat_label(fmt_stat(modified), modified, base))

    def _refresh_vision(self) -> None:
        self._empty(self._vision_box)
        modified, base = self._unit_state.vision, self._unit_state.base_vision
        self._vision_box.addWidget(self._stat_label(fmt_stat(modified), modified, base))

    def _refresh_weapons(self) -> None:
        """(Re)build the weapon list from the engine's active WeaponSet."""
        self._empty(self._weapon_box)
        weapon_set = self._active_weapon_set()
        upgrades = self._unit_state.effective_upgrades
        self._weapons = weapon_set_view(weapon_set, upgrades) if weapon_set is not None else []
        if not self._weapons:
            none = QLabel("None defined.")
            none.setObjectName("muted")
            self._weapon_box.addWidget(none)
            return

        self._weapon_box.addWidget(self._active_label(set_conditions(weapon_set)))
        self._weapon_picker = QComboBox()
        for weapon in self._weapons:
            self._weapon_picker.addItem(f"{weapon['slot']} — {weapon['name']}")
        self._nugget_box = QWidget()
        self._nugget_box.setLayout(QVBoxLayout())
        self._nugget_box.layout().setContentsMargins(0, 0, 0, 0)
        self._weapon_picker.currentIndexChanged.connect(self._show_nuggets)
        self._weapon_box.addWidget(self._weapon_picker)
        self._weapon_box.addWidget(self._nugget_box)
        self._show_nuggets(0)

    def _refresh_locomotor(self) -> None:
        """(Re)show the active source's locomotor speed (a horde governs group movement),
        carrying the active SPEED modifiers coloured against base."""
        self._empty(self._loco_box)
        modified = self._source_state.speed
        if modified is None:
            label = QLabel("—")
            label.setObjectName("muted")
        else:
            label = self._stat_label(
                fmt_stat(modified), modified, self._source_state.base_speed, default_name="objName"
            )
        self._loco_box.addWidget(label)

    def _refresh_commands(self) -> None:
        """(Re)build the active CommandSet's buttons, re-resolving whenever an upgrade or
        rank toggles a CommandSetUpgrade."""
        self._empty(self._commands_box)
        # The palette follows the active cost source, under the unit's active upgrades.
        source = self._active_source or self._current_obj
        command_set = select_command_set(source, self._unit_state.effective_upgrades)
        if command_set is None:
            none = QLabel("No command set.")
            none.setObjectName("muted")
            self._commands_box.addWidget(none)
            return

        self._commands_box.addWidget(QLabel(f"<b>{command_set.name}</b>"))
        buttons = command_buttons_view(self.game, command_set)
        if not buttons:
            none = QLabel("No buttons.")
            none.setObjectName("muted")
            self._commands_box.addWidget(none)
            return

        for button in buttons:
            self._add_command_button(button)

    def _add_command_button(self, button: dict) -> None:
        """One command button: a clickable detail unfurl plus its action. A UNIT_BUILD
        button is the exception — it stays a link to the object it trains. State-flipping
        buttons (a power modifier, a weapon-set toggle) flip their flag on the same click
        and rebuild the palette; the expanded set re-opens the detail afterwards."""
        button["text"] = clean_text(button["text"])
        button["tooltip"] = clean_text(button["tooltip"])
        widget = QPushButton(button["text"])
        if button["tooltip"]:
            widget.setToolTip(button["tooltip"])
        icon = self._command_icon(button["button_image"])
        if icon is not None:
            widget.setIcon(icon)
            widget.setIconSize(QSize(28, 28))
        self._commands_box.addWidget(widget)

        detail = QVBoxLayout()
        detail.setContentsMargins(16, 0, 0, 4)
        self._commands_box.addLayout(detail)

        command = button["command"]
        if command == "UNIT_BUILD" and button["object"]:
            widget.setText(f"{button['text']}  →")
            widget.clicked.connect(lambda _=False, name=button["object"]: self.navigate.emit(name))
            return

        # Special-power buttons show their recharge and mark an active modifier; the
        # resolved view is cached for the detail box and the flip.
        if button["special_power"]:  # SPECIAL_POWER* or a spellbook's SPELL_BOOK
            view = self._special_power_view(button["special_power"])
            button["power_view"] = view
            base_text = button["text"]
            if view["cooldown"] is not None:
                base_text = f"{base_text}  ·  {fmt_stat(view['cooldown'])}s"
            if (
                view["kind"] == "modifier"
                and view["modifier"] is not None
                and view["name"] in self._active_special_modifiers
            ):
                base_text = f"{base_text}  ●"  # the modifier is applied to the unit
            widget.setText(base_text)
        elif command == "TOGGLE_WEAPONSET":
            active = bool(button["toggle_flags"]) and set(button["toggle_flags"]) <= (
                self._weapon_toggle_flags
            )
            if active:
                widget.setText(f"{button['text']}  ●")

        # Re-open the detail after a rebuild if it was expanded.
        if button["name"] in self._expanded_buttons:
            self._fill_command_detail(button, detail)
        widget.clicked.connect(
            lambda _=False, b=button, d=detail: self._toggle_command_detail(b, d)
        )

    def _toggle_command_detail(self, button: dict, detail) -> None:
        """Expand or collapse a button's detail, flipping any state it carries. A modifier
        power and a weapon-set toggle flip their flag here, which rebuilds the palette (the
        rebuilt button re-fills its detail); other buttons fill or clear in place."""
        name = button["name"]
        expanding = name not in self._expanded_buttons
        if expanding:
            self._expanded_buttons.add(name)
        else:
            self._expanded_buttons.discard(name)

        view = button.get("power_view")
        if view is not None and view["kind"] == "modifier" and view["modifier"] is not None:
            self._toggle_special_power_modifier(view)  # rebuilds the palette
        elif button["command"] == "TOGGLE_WEAPONSET":
            self._toggle_weaponset(button)  # rebuilds the palette
        elif expanding:
            self._fill_command_detail(button, detail)
        else:
            clear_layout(detail)

    def _fill_command_detail(self, button: dict, detail) -> None:
        """Populate a button's expanded detail: the copyable identity box first,
        then the rows specific to its command (an upgrade's economy, a fired or
        special weapon, summoned objects, or a modifier's granted stats)."""
        self._add_button_identity(button, detail)
        command = button["command"]
        view = button.get("power_view")
        if command in ("OBJECT_UPGRADE", "PLAYER_UPGRADE"):
            self._add_upgrade_detail(button, detail)
        elif view is not None:
            if view["kind"] == "modifier" and view["modifier"] is not None:
                self._add_modifier_detail(view["modifier"], detail)
            else:
                self._add_special_power_detail(view, detail)
        elif command == "FIRE_WEAPON":
            self._add_fire_weapon_detail(button, detail)

    def _add_button_identity(self, button: dict, detail) -> None:
        """A copyable box naming the ability and its description, leading every unfurled button."""
        box, layout = card()
        name = QLabel(button["text"] or button["name"])
        name.setObjectName("objName")
        name.setWordWrap(True)
        layout.addWidget(name)
        if button["tooltip"]:
            body = QLabel(button["tooltip"])
            body.setObjectName("muted")
            body.setWordWrap(True)
            layout.addWidget(body)
        detail.addWidget(box)

    @staticmethod
    def _detail_rows(rows: list[tuple[str, str]]) -> QWidget:
        """A two-column (label, value) grid for a command button's detail panel."""
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        for row, (label, value) in enumerate(rows):
            grid.addWidget(QLabel(label), row, 0)
            value_label = QLabel(value)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(value_label, row, 1)
        grid.setColumnStretch(0, 1)
        return wrap

    def _add_upgrade_detail(self, button: dict, detail) -> None:
        """The upgrade an OBJECT_UPGRADE/PLAYER_UPGRADE grants and its cost."""
        info = button["upgrade"]
        if info is None:
            note = QLabel("No upgrade.")
            note.setObjectName("muted")
            detail.addWidget(note)
            return
        detail.addWidget(
            self._detail_rows(
                [
                    ("Upgrade", info["name"]),
                    ("Build cost", fmt_stat(info["cost"])),
                    ("Build time", fmt_stat(info["time"])),
                ]
            )
        )

    def _special_power_view(self, name: str) -> dict:
        """Resolve a SpecialPower's effect from the unit, active source or selected object
        (a horde-level power lives on the source); the first known effect wins, else the
        plain view of the unit."""
        if name:
            for obj in (self._unit_obj, self._active_source, self._current_obj):
                if obj is None:
                    continue
                view = special_power_view(self.game, obj, name)
                if view["kind"]:
                    return view
        return special_power_view(self.game, self._unit_obj, name)

    def _toggle_special_power_modifier(self, view: dict) -> None:
        """Flip a SpecialPowerModule's AttributeModifier on the unit and re-resolve: its
        ModifierList joins (or leaves) the unit state's extra modifiers, like an upgrade."""
        name = view["name"]
        if name in self._active_special_modifiers:
            del self._active_special_modifiers[name]
        else:
            self._active_special_modifiers[name] = view["modifier"]
        self._unit_state.extra_modifiers = list(self._active_special_modifiers.values())
        self._refresh_stats()  # rebuilds the palette too, re-marking the active toggle

    def _add_modifier_detail(self, modifier_list, detail) -> None:
        """List the stats a special power's AttributeModifier grants (e.g. HEALTH 500),
        shown under the button while it is applied."""
        view = modifier_view(modifier_list)
        if view["modifiers"]:
            detail.addWidget(self._detail_rows(view["modifiers"]))

    def _add_special_power_detail(self, view: dict, detail) -> None:
        """A SPECIAL_POWER button's effect: the weapon it fires, the objects it
        summons, or just the power's name when nothing more resolves."""
        if view["kind"] == "weapon":
            self._add_special_weapon_detail(view["weapon"], detail)
        elif view["kind"] == "summon":
            self._add_summon_detail(view["summoned"], detail)
        elif view["name"]:
            detail.addWidget(self._detail_rows([("Special power", view["name"])]))
        else:
            note = QLabel("No special power.")
            note.setObjectName("muted")
            detail.addWidget(note)

    def _add_special_weapon_detail(self, weapon: dict, detail) -> None:
        """The SpecialWeapon a WeaponFireSpecialAbilityUpdate fires, rendered like the
        Weapons card."""
        self._render_weapon(weapon, detail, name=weapon["name"])

    def _add_summon_detail(self, summoned: list, detail) -> None:
        """A navigable view of the objects an OCLSpecialPower summons. A real object is a
        link button (unloaded ones disabled); a summon egg is a muted "via" heading with
        what it hatches nested beneath, keeping the egg → real-object chain visible."""
        if not summoned:
            note = QLabel("No summoned objects.")
            note.setObjectName("muted")
            detail.addWidget(note)
            return
        for node in summoned:
            self._add_summon_node(node, detail)

    def _add_summon_node(self, node: dict, box) -> None:
        """Render one summon-chain node into `box` (recursing through egg payloads)."""
        name = node["name"]
        obj = self.game.objects.get(name)
        children = node.get("summoned") or []
        if children:
            heading = QLabel(f"via {display_name(self.game, obj) or name}")
            heading.setObjectName("muted")
            box.addWidget(heading)
            nested = QVBoxLayout()
            nested.setContentsMargins(16, 0, 0, 0)
            box.addLayout(nested)
            for child in children:
                self._add_summon_node(child, nested)
            return
        label = display_name(self.game, obj) if obj is not None else None
        button = QPushButton(f"{label or name}  →")
        if obj is None:
            button.setEnabled(False)
            button.setToolTip("Not loaded")
        else:
            button.clicked.connect(lambda _=False, n=name: self.navigate.emit(n))
        box.addWidget(button)

    def _add_fire_weapon_detail(self, button: dict, detail) -> None:
        """The weapon a FIRE_WEAPON button fires (the unit's matching slot)."""
        slot = button["weapon_slot"]
        weapon = next((w for w in self._weapons if w["slot"] == slot), None)
        if weapon is None:
            note = QLabel(f"No weapon in slot {slot or '—'}.")
            note.setObjectName("muted")
            detail.addWidget(note)
            return
        # Heading mirrors the Weapons card picker (slot — name).
        name = f"{slot} — {weapon['name']}" if slot else weapon["name"]
        self._render_weapon(weapon, detail, name=name)

    def _toggle_weaponset(self, button: dict) -> None:
        """Flip a TOGGLE_WEAPONSET button's condition flags and re-resolve weapons."""
        flags = set(button["toggle_flags"])
        if flags and flags <= self._weapon_toggle_flags:
            self._weapon_toggle_flags -= flags
        else:
            self._weapon_toggle_flags |= flags
        self._refresh_weapons()
        self._refresh_commands()  # reflect the toggle's active marker
        self.changed.emit()  # the comparison's top damage follows the active set

    def _refresh_armor(self) -> None:
        """(Re)show only the active ArmorSet, each per-type scalar carrying the active ARMOR
        modifiers (lower is better, coloured inversely)."""
        self._empty(self._armor_box)
        armor_set = self._unit_state.armor_set
        if armor_set is None:
            none = QLabel("None defined.")
            none.setObjectName("muted")
            self._armor_box.addWidget(none)
            return

        view = armorset_view(armor_set)
        self._armor_box.addWidget(self._active_label(set_conditions(armor_set)))
        self._armor_box.addWidget(QLabel(f"<b>{view['armor'] or '—'}</b>"))
        self._armor_box.addWidget(self._scalar_table(view.get("scalars") or {}))

    def _show_nuggets(self, index: int) -> None:
        box = self._nugget_box.layout()
        clear_layout(box)
        if 0 <= index < len(self._weapons):
            self._render_weapon(self._weapons[index], box)

    def _render_weapon(self, weapon: dict, box, *, name: str | None = None) -> None:
        """Render a weapon's range and per-nugget damage table into `box`, carrying the
        active RANGE and damage modifiers. Shared by the Weapons card and the command-button
        weapon details. `name`, if given, adds a heading (the Weapons card uses its picker)."""
        if name:
            box.addWidget(QLabel(f"<b>{name}</b>"))

        # Range carries the RANGE modifier; a melee weapon's range is hidden.
        base_range = weapon["range"]
        if base_range is not None and not weapon["melee"]:
            multiplier = self._unit_state.range_multiplier
            modified = base_range * multiplier
            row = self._stat_label(f"Range: {fmt_stat(modified)}", modified, base_range)
            box.addWidget(row)

        nuggets = weapon["nuggets"]
        if not nuggets:
            m = QLabel("No nuggets.")
            m.setObjectName("muted")
            box.addWidget(m)
            return

        # DPS: per-shot damage paced by the firing cycle. Only the active set's weapons
        # carry an `interval`, so ability/special weapons skip this.
        interval_ms = weapon.get("interval")
        per_shot = sum(
            self._unit_state.weapon_damage(n["damage"], n["damage_type"])
            for n in nuggets
            if n["damage"] is not None
        )
        if interval_ms and per_shot:
            interval_s = interval_ms / 1000
            dps = per_shot / interval_s
            box.addWidget(
                QLabel(f"<b>DPS {fmt_stat(dps)}</b>    ·    attacks every {fmt_stat(interval_s)}s")
            )

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        for col, head in enumerate(("Type", "Damage type", "Damage", "Radius")):
            label = QLabel(head)
            label.setObjectName("colhead")
            grid.addWidget(label, 0, col)
        for row, n in enumerate(nuggets, start=1):
            base_damage = n["damage"]
            damage = base_damage
            if base_damage is not None:
                damage = self._unit_state.weapon_damage(base_damage, n["damage_type"])
            cells = (
                QLabel(n["type"]),
                QLabel(n["damage_type"] or "—"),
                self._stat_label(fmt_stat(damage), damage, base_damage),
                QLabel("—" if n["radius"] is None else fmt_stat(n["radius"])),
            )
            for col, widget in enumerate(cells):
                grid.addWidget(widget, row, col)
        grid.setColumnStretch(0, 1)
        wrap = QWidget()
        wrap.setLayout(grid)
        box.addWidget(wrap)

    def _scalar_table(self, scalars: dict) -> QWidget:
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        for i, (key, base) in enumerate(scalars.items()):
            modified = self._unit_state.armor_scalar(key, base)
            name = QLabel(key)
            pct = self._stat_label(
                percent(modified), modified, base, inverse=True, default_name="scalarPct"
            )
            pct.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(name, i, 0)
            grid.addWidget(pct, i, 1)
        grid.setColumnStretch(0, 1)
        return wrap
