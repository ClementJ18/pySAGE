"""Generating a whole Edain wiki page draft from a parsed game object: infobox, quote,
recruitment tables (buildings), abilities, upgrades, an empty strategy box and navbox/category
templates. What is not derivable (ability prose nuance, manual infobox fields) is left as an
empty placeholder.

Stats come from `mapping.computed_fields`; abilities and upgrades from the object's
active `CommandSet`, keeping only the buttons the player sees (palantir/radial) that are
abilities or upgrades. Upgrades are only hinted, since the wiki transcludes them through
hand-curated labels with no algorithmic tie to the ini names.

A building also gets a recruitment section: its UNIT_BUILD buttons become a unit table, and
its REVIVE buttons a hero table — the revive buttons indexed in slot order against the
faction's buildable heroes, with the building recruiting the heroes whose button lacks the
`NEED_UPGRADE` option. Preview-only; nothing is saved.
"""

import re
from datetime import date

from sage_ini.model.behaviors import ContainBehavior
from sage_ini.model.enums import CommandTypes, Options
from sage_ini.model.state import (
    command_set_names,
    find_upgrades,
    has_kindof,
    horde_members,
    select_command_set,
)
from sage_utils.views import (
    build_cost_view,
    display_name,
    localize,
    recruited_hero_names,
    safe,
)
from sage_wiki.images import command_icon_names, portrait_filename
from sage_wiki.mapping import computed_fields

# Command types that make a button a usable ability or a purchasable upgrade. Every
# other command (move, stop, stance) is engine plumbing, not page content.
ABILITY_COMMANDS = frozenset(
    {
        CommandTypes.SPECIAL_POWER,
        CommandTypes.SPECIAL_POWER_TOGGLE,
        CommandTypes.TOGGLE_WEAPONSET,
        CommandTypes.HORDE_TOGGLE_FORMATION,
    }
)
UPGRADE_COMMANDS = frozenset(
    {
        CommandTypes.OBJECT_UPGRADE,
        CommandTypes.PURCHASE_SCIENCE,
        CommandTypes.PLAYER_UPGRADE,
    }
)

_HOTKEY = re.compile(r"\s*\(&.\)\s*$")  # the "(&X)" shortcut marker on a button name
_REQUIRES_LEVEL = re.compile(r"^Level\s+(\d+)\b", re.IGNORECASE)
_SENTENCE_END = (".", "!", "?")


def _join_segments(segments) -> str:
    """Join `\\n`-separated segments into one line, adding a period to a segment only when
    the next one starts upper-case (a lower-case continuation is a mid-sentence wrap, kept
    joined by a space)."""
    cleaned = [seg.strip() for seg in segments if seg.strip()]
    parts = []
    for index, segment in enumerate(cleaned):
        following = cleaned[index + 1] if index + 1 < len(cleaned) else ""
        if following[:1].isupper() and segment[-1] not in _SENTENCE_END:
            segment += "."
        parts.append(segment)
    return " ".join(parts)


def _split_name(text: str) -> tuple[str, str | None]:
    """A button name split into its display text and its ``(&X)`` shortcut letter."""
    match = re.search(r"\(&(.)\)", text)
    shortcut = match.group(1) if match else None
    return _HOTKEY.sub("", text).strip(), shortcut


def _clean_tooltip(text: str) -> tuple[int | None, str | None, str]:
    """A raw tooltip parsed into `(level, requirement, description)`. A leading `Requires:`
    segment becomes the level (`Requires: Level 3`) or a named requirement; the rest joins
    into the description."""
    segments = [seg.strip() for seg in text.split("\\n") if seg.strip()]
    level: int | None = None
    requirement: str | None = None
    if segments and segments[0].lower().startswith("requires:"):
        clause = segments.pop(0).split(":", 1)[1].strip()
        level_match = _REQUIRES_LEVEL.match(clause)
        if level_match:
            level = int(level_match.group(1))
        elif clause:
            requirement = clause
    return level, requirement, _join_segments(segments)


_LORE_METADATA = ("prerequisites:", "strengths:", "type:")


def _lore_prose(text: str) -> str:
    """The plain lore prose of a `RecruitText`/`Description`, dropping the leading
    `Type:`/`Prerequisites:`/`Strengths:` metadata lines and any trailing italic flavor quote."""
    kept = []
    for segment in (seg.strip() for seg in text.split("\\n")):
        if not segment or segment.lower().startswith(_LORE_METADATA):
            continue
        if segment.startswith("''") and segment.endswith("''"):
            continue  # flavor quote — the page carries flavor in its {{Quote}}
        kept.append(segment)
    return _join_segments(kept)


def _intro(game, obj, linker=None) -> str:
    """The page's opening prose, from the object's `RecruitText` (preferred) or
    `Description`, falling back to a placeholder comment when neither has any. With a `linker`,
    mentions of other units/heroes that have a wiki page are hyperlinked."""
    prose = _lore_prose(localize(game, safe(lambda: obj.RecruitText))) or _lore_prose(
        localize(game, safe(lambda: obj.Description))
    )
    if prose:
        return linker.linkify(prose) if linker is not None else prose
    return "<!-- Intro paragraph: describe the unit and its role. -->"


def _command_buttons(game, command_set):
    """`(slot, button_name, CommandButton)` for each filled slot, in slot order. The name
    is kept so a caller can join it to the button's icon filename."""
    table = game.commandbuttons
    slots = sorted(
        (int(slot), name[-1] if isinstance(name, list) else name)
        for slot, name in command_set.fields.items()
        if slot.isdigit()
    )
    return [(slot, name, table[name]) for slot, name in slots if name in table]


def _is_visible(slot: int, button) -> bool:
    """Whether the player ever sees this button: the first six slots (the palantir) when
    `InPalantir` is set, any later slot (the radial menu) when `Radial` is set."""
    visible_field = "InPalantir" if slot <= 6 else "Radial"
    return bool(safe(lambda: getattr(button, visible_field)))


def _cooldown(button) -> int | None:
    """The button's special-power recharge in whole seconds (its `SpecialPower.ReloadTime`),
    or None. A sub-second reload is an engine click-debounce, not a cooldown, so it yields None."""
    power = safe(lambda: button.SpecialPower)
    reload_ms = safe(lambda: power.ReloadTime) if power is not None else None
    if not reload_ms or int(reload_ms) < 1000:
        return None
    return round(int(reload_ms) / 1000)


def _button_entry(game, button, kind: str, image: str) -> dict | None:
    """The command entry dict for one button (`{kind, name, image, shortcut, level,
    requirement, description, cooldown}`), or None when it has no usable name. `image` is the
    icon's wiki filename."""
    name, shortcut = _split_name(localize(game, safe(lambda: button.TextLabel)))
    if not name:
        return None
    level, requirement, description = _clean_tooltip(
        localize(game, safe(lambda: button.DescriptLabel))
    )
    return {
        "kind": kind,
        "name": name,
        "image": image,
        "shortcut": shortcut,
        "level": level,
        "requirement": requirement,
        "description": description,
        "cooldown": _cooldown(button),
    }


def _button_kind(button) -> str | None:
    """Whether a button is an `"ability"`, an `"upgrade"`, or None (engine plumbing). A
    typeless button that still carries a tooltip is treated as a passive ability."""
    command = safe(lambda: button.Command)
    if command in ABILITY_COMMANDS:
        return "ability"
    if command in UPGRADE_COMMANDS:
        return "upgrade"
    if command is None and bool(safe(lambda: button.DescriptLabel)):
        return "ability"
    return None


def button_overlay_kind(button) -> str:
    """Which frame an icon for `button` takes: `"passive"` for a non-pressable button (a
    display-only aura the player can't click, flagged with the `NONPRESSABLE` option), and
    `"active"` for every other button. Every command icon is framed."""
    options = safe(lambda: button.Options) or ()
    return "passive" if Options.NONPRESSABLE in options else "active"


def command_entries(game, obj, active_upgrades=frozenset()) -> list[dict]:
    """The object's abilities and upgrades, drawn from its active command set. Each entry is
    `{kind, name, image, shortcut, level, requirement, description, cooldown}` (`image` the
    icon's wiki filename, `""` when the button names none). Generic-command, nameless and
    untyped buttons are dropped. `active_upgrades` selects the set the engine would show."""
    command_set = select_command_set(obj, set(active_upgrades))
    if command_set is None:
        return []

    icon_names = command_icon_names(game, command_set)
    entries: list[dict] = []
    for slot, button_name, button in _command_buttons(game, command_set):
        if not _is_visible(slot, button):
            continue
        kind = _button_kind(button)
        if kind is None:
            continue  # a visible non-ability button: a stance toggle, sell, …
        entry = _button_entry(game, button, kind, icon_names.get(button_name, ""))
        if entry is not None:
            entries.append(entry)
    return entries


def button_ability_block(game, button_name: str, image: str = "") -> str:
    """The `{{Ability}}` template for a single command button, looked up by name, with its
    icon `image` filename pre-filled. Empty string when the button isn't loaded or names
    nothing. Used by the image tool to scaffold one ability on demand."""
    button = game.commandbuttons.get(button_name)
    if button is None:
        return ""
    entry = _button_entry(game, button, _button_kind(button) or "ability", image)
    return ability_block(entry) if entry is not None else ""


def ability_block(entry: dict, linker=None) -> str:
    """One ability rendered as a `{{Ability}}` invocation (only set params emitted). `image`
    is pre-filled with the icon's filename, blank only when the button names none. A recharge
    is appended as `Cooldown: XX` (after closing the description's last sentence with a period),
    unless the tooltip already states it. With a `linker`, units/heroes named in the description
    are hyperlinked."""
    lines = ["{{Ability", f"|image={entry.get('image', '')}"]
    if entry["level"] is not None:
        lines.append(f"|level={entry['level']}")
    if entry["requirement"]:
        lines.append(f"|requirement={entry['requirement']}")
    lines.append(f"|name={entry['name']}")
    if entry["shortcut"]:
        lines.append(f"|shortcut={entry['shortcut']}")
    description = entry["description"]
    if linker is not None:
        description = linker.linkify(description)
    cooldown = entry.get("cooldown")
    if cooldown is not None and "cooldown" not in description.lower():
        if description and description[-1] not in _SENTENCE_END:
            description += "."
        description = f"{description} Cooldown: {cooldown}".strip()
    if description:
        lines.append(f"|description={description}")
    lines.append("}}")
    return "\n".join(lines)


def upgrade_hints(entries: list[dict]) -> str:
    """The detected upgrades as an HTML-comment hint block, listing what the unit has for
    the editor to wire up by hand (the wiki's upgrade templates have no algorithmic tie)."""
    lines = [
        "<!-- Detected upgrades — wire each up with the right {{Upgrade|…}} or per-upgrade",
        "     template from https://edain.fandom.com/wiki/Upgrades :",
    ]
    for entry in entries:
        detail = f": {entry['description']}" if entry["description"] else ""
        lines.append(f"  {entry['name']}{detail}")
    lines.append("-->")
    return "\n".join(lines)


# Curated upgrade name -> (wiki template, argument kind). The common upgrades are mapped by
# hand since the game name has no tie to the template name; the kind picks the template's
# argument (the page's faction, the Good/Evil alignment, or none).
UPGRADE_TEMPLATES: dict[str, tuple[str, str | None]] = {
    "banner carrier": ("Banner Carrier", "faction"),
    "fire arrows": ("Fire Arrows", "alignment"),
    "flaming munitions": ("Fire Arrows", "alignment"),
    "forged blades": ("Forged Blades", "faction"),
    "heavy armor": ("Heavy Armor", "faction"),
    "composite bows": ("Composite Bows", None),
    "composite bow": ("Composite Bows", None),
}


def upgrade_block(entries: list[dict], faction: str, alignment: str | None) -> str:
    """The upgrades section: each known upgrade as its curated template (filled by `faction`/
    `alignment`), the rest falling through to the HTML-comment hint so none are lost."""
    rendered: list[str] = []
    unmapped: list[dict] = []
    for entry in entries:
        key = entry["name"].lower().removeprefix("purchase ").strip()
        match = UPGRADE_TEMPLATES.get(key)
        if match is None:
            unmapped.append(entry)
            continue
        template, kind = match
        if kind is None:
            rendered.append(f"{{{{{template}}}}}<br>")
        else:
            arg = faction if kind == "faction" else (alignment or "")
            rendered.append(f"{{{{{template}|{arg}}}}}<br>")

    lines: list[str] = []
    if rendered:
        lines.append("The unit has access to the following upgrades:<br>")
        lines.extend(rendered)
    if unmapped:
        lines.append(upgrade_hints(unmapped))
    return "\n".join(lines)


def _fmt(value) -> str:
    """A numeric stat rounded to a whole number; "" for None or a non-number."""
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(round(number))


def _article_table(headers: list[str], rows: list[list[str]]) -> str:
    """A wiki `article-table` with one cell per line — the Edain building pages' convention."""
    lines = ['{| class="article-table"']
    lines += [f"! {header}" for header in headers]
    for row in rows:
        lines.append("|-")
        lines += [f"| {cell}".rstrip() for cell in row]  # an empty cell renders as a bare "|"
    lines.append("|}")
    return "\n".join(lines)


def building_units(game, obj, linker=None) -> list[list[str]]:
    """The units a building recruits: each UNIT_BUILD button across its command sets as a
    `[name, type, cost, command_points, shortcut]` row (type left blank for the editor).
    De-duplicated by display name — a sub-faction's cheaper variant shares the base unit's
    name — in first-seen slot order. With a `linker`, a name with a wiki page is hyperlinked."""
    seen: set[str] = set()
    rows: list[list[str]] = []
    for set_name in command_set_names(obj):
        command_set = game.commandsets.get(set_name)
        if command_set is None:
            continue
        for _slot, _button_name, button in _command_buttons(game, command_set):
            if getattr(safe(lambda b=button: b.Command), "name", None) != "UNIT_BUILD":
                continue
            target = safe(lambda b=button: b.Object)
            if target is None:
                continue
            name = display_name(game, target) or target.name
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            _, shortcut = _split_name(localize(game, safe(lambda b=button: b.TextLabel)))
            cost = build_cost_view(target)
            cell = linker.link(name) if linker is not None else name
            rows.append(
                [cell, "", _fmt(cost["BuildCost"]), _fmt(cost["CommandPoints"]), shortcut or ""]
            )
    return rows


def building_heroes(game, obj) -> list:
    """The hero objects a building recruits, resolved by the shared index-based REVIVE logic
    (`sage_utils.views.recruited_hero_names`): REVIVE buttons enumerated in slot order and mapped
    by position to the faction's buildable-hero order. Returns the loaded hero objects."""
    return [game.objects[name] for name in recruited_hero_names(game, obj) if name in game.objects]


def recruitment_section(game, obj, linker=None) -> str:
    """The building's recruitment section: a unit table for its UNIT_BUILD buttons and a hero
    table for its REVIVE recruits (derivable cells filled, editorial columns blank). Empty
    when the building produces neither. With a `linker`, each recruit's name is hyperlinked to
    its page when one exists."""
    units = building_units(game, obj, linker)
    heroes = building_heroes(game, obj)
    if not units and not heroes:
        return ""
    blocks: list[str] = []
    if units:
        unit_table = _article_table(["Name", "Type", "Cost", "CP Cost", "Shortcut"], units)
        blocks.append("This structure produces the following units:\n\n" + unit_table)
    if heroes:
        rows = []
        for h in heroes:
            name = display_name(game, h) or h.name
            cell = linker.link(name) if linker is not None else name
            rows.append([cell, "", "", _fmt(build_cost_view(h)["BuildCost"]), ""])
        hero_table = _article_table(["Name", "Weapon(s)", "Role", "Cost", "Importance"], rows)
        lead = (
            "It can also recruit the following heroes:"
            if units
            else "This structure recruits the following heroes:"
        )
        blocks.append(lead + "\n\n" + hero_table)
    header = "== Unit Production ==" if units else "== Heroes =="
    return header + "\n\n" + "\n\n".join(blocks)


# Each object type's logical-field -> infobox-param map for the stats `computed_fields`
# produces. A hero splits combat stats by attack type (melee shown here); a building's are
# already per-level indexed, so they pass through by name.
_HERO_PARAMS = {
    "object_name": "object",
    "cost": "cost",
    "command_points": "command_points",
    "time": "time",
    "timer": "timer",
    "health": "health",
    "armor": "armor_melee",
    "damage": "damage_melee",
    "damage_type": "damage_type_melee",
    "attack_speed": "attack_speed_melee",
    "range": "range_melee",
    "radius": "radius_melee",
    "speed": "speed_melee",
}
_UNIT_PARAMS = {
    "object_name": "object_name",
    "cost": "cost",
    "command_points": "command_points",
    "time": "time",
    "health": "health",
    "armor": "armor",
    "damage": "damage",
    "damage_type": "damage_type",
    "revenge_damage": "revenge_damage",
    "trample_damage": "trample_damage",
    "attack_speed": "attack_speed",
    "range": "range",
    "radius": "radius",
    "speed": "speed",
}
_MANUAL_FIELDS = {
    "hero": ("image", "title", "role", "location", "importance"),
    "unit": (
        "image",
        "unit_type",
        "size",
        "location",
        "requirement",
        "voice",
    ),
}
_TEMPLATE = {"hero": "Hero", "unit": "Unit", "building": "Infobox Building"}
# Manual fields the editor normally fills, but which have a sensible default to pre-fill.
_MANUAL_DEFAULTS: dict[str, str] = {}

# The Building infobox is rendered as a full skeleton: every parameter is always emitted
# (blank when the object has no value) so the editor sees the complete template. Top-level
# fields come first, then a run of per-level stat columns.
_BUILDING_TOP = ("image", "faction", "type", "object", "level_up", "cost", "time", "location")
# Each per-level stat param maps to the `computed_fields` key it draws from; a None source is
# an editor-filled field (`label`, `level_effect`) with no computed value.
_BUILDING_LEVEL_FIELDS: dict[str, str | None] = {
    "label": None,
    "armor": "armor",
    "health": "health",
    "resources": "resources",
    "interval": "interval",
    "damage": "damage",
    "attack_speed": "attack_speed",
    "range": "range",
    "level_effect": None,
}
_BUILDING_LEVELS = 3  # the template's fixed level columns; more are added if the building has them


def _building_level_count(computed: dict[str, str]) -> int:
    """At least the template's fixed columns, or more if the building has further levels."""
    highest = 0
    for source in _BUILDING_LEVEL_FIELDS.values():
        if source is None:
            continue
        level = 1
        while f"{source}{level}" in computed:
            level += 1
        highest = max(highest, level - 1)
    return max(highest, _BUILDING_LEVELS)


def _building_infobox(computed: dict[str, str], faction: str, image: str = "") -> str:
    """The Building infobox skeleton: the full field set, blank where the object has no value.
    Object-level stats fill the top block; per-level stats fill the `#levelN` columns (an
    unleveled building's single set of stats lands in level 1). `image` pre-fills the portrait
    filename."""
    top = {
        "faction": faction,
        "image": image,
        "object": computed.get("object_name", ""),
        "cost": computed.get("cost", ""),
        "time": computed.get("time", ""),
    }
    lines = [f"{{{{{_TEMPLATE['building']}"]
    lines += [f"|{param}={top.get(param, '')}" for param in _BUILDING_TOP]
    for level in range(1, _building_level_count(computed) + 1):
        for param, source in _BUILDING_LEVEL_FIELDS.items():
            value = ""
            if source is not None:
                value = computed.get(f"{source}{level}")
                if value is None and level == 1:
                    value = computed.get(source)  # unleveled building: stats live unsuffixed
                value = value or ""
            lines.append(f"|{param}{level}={value}")
    lines.append("}}")
    return "\n".join(lines)


def _object_kind(obj) -> str:
    if has_kindof(obj, "HERO"):
        return "hero"
    if has_kindof(obj, "STRUCTURE"):
        return "building"
    return "unit"


# Good/Evil faction sides, used to fill alignment-parameterized upgrade templates
# (e.g. {{Fire Arrows|Good}}).
_GOOD_SIDES = frozenset({"Men", "Dwarves", "Elves", "Rohan", "Imladris", "Arnor", "Mirkwood"})
_EVIL_SIDES = frozenset(
    {"Mordor", "Wild", "Angmar", "Isengard", "Evilmen", "EvilBeasts", "Moria", "WOR"}
)

# A unit's role guessed from its KindOf, most specific first (an archer is also INFANTRY).
_KINDOF_ROLES = (
    ("ARCHER", "Archer"),
    ("CAVALRY", "Cavalry"),
    ("SIEGE", "Siege"),
    ("MONSTER", "Monster"),
    ("INFANTRY", "Infantry"),
)


def _alignment(obj) -> str | None:
    """The object's Good/Evil side from its ``Side`` field, or None when unknown."""
    raw = obj._fields.get("Side")
    side = str(raw[-1] if isinstance(raw, list) else raw) if raw else None
    if side in _GOOD_SIDES:
        return "Good"
    if side in _EVIL_SIDES:
        return "Evil"
    return None


def _primary_role(obj) -> str:
    """A best-effort role from the object's KindOf (e.g. ``Archer``), or "" if none match."""
    for kindof, role in _KINDOF_ROLES:
        if has_kindof(obj, kindof):
            return role
    return ""


def _tier_unit(obj):
    """The object whose KindOf decides the tier: a horde's first contained member (the tier
    flags sit on the soldier, not the battalion shell), else `obj`."""
    game = getattr(obj, "_game", None)
    if game is not None:
        for name in horde_members(obj):
            member = game.objects.get(name)
            if member is not None:
                return member
    return obj


def _tier(obj) -> str:
    """The unit's wiki tier from its KindOf: Elite (`MADE_OF_METAL`), Heroic (`MADE_OF_DIRT`),
    else Standard — Edain's otherwise-cosmetic tier flags."""
    unit = _tier_unit(obj)
    if has_kindof(unit, "MADE_OF_METAL"):
        return "Elite"
    if has_kindof(unit, "MADE_OF_DIRT"):
        return "Heroic"
    return "Standard"


def _horde_size(obj) -> int | None:
    """A horde's battalion size — its ``HordeContain`` ``Slots`` — or None for a lone unit."""
    for module in getattr(obj, "_modules", ()):
        if isinstance(module, ContainBehavior):
            slots = safe(lambda m=module: m.Slots)
            if slots:
                return int(slots)
    return None


def infobox_block(
    obj, kind: str, faction: str, active_upgrades=frozenset(), image: str = ""
) -> str:
    """The object's infobox for its type, derived stats first, manual placeholders last. `image`
    pre-fills the portrait filename in the `image` field (blank leaves it for the editor)."""
    computed = computed_fields(obj, active_upgrades)
    if kind == "building":
        # The Building infobox is emitted as a full skeleton (every field, blank if need be).
        return _building_infobox(computed, faction, image)
    manual = list(_MANUAL_FIELDS[kind])
    pairs: list[tuple[str, str]] = []
    param_map = _HERO_PARAMS if kind == "hero" else _UNIT_PARAMS
    for k, v in computed.items():
        if k in param_map:
            pairs.append((param_map[k], v))
        elif kind == "hero" and k.endswith(("_melee", "_ranged", "_mounted", "_flying")):
            pairs.append((k, v))  # already split into the Hero template's stance params
        elif kind == "unit" and k.endswith("_alt"):
            pairs.append((k, v))  # already keyed to the Unit template's `_alt` params

    if kind == "unit":
        size = _horde_size(obj)
        if size is not None:  # a battalion fills `size`; a lone unit leaves it blank
            pairs.append(("size", str(size)))
            manual = [field for field in manual if field != "size"]

    defaults = {**_MANUAL_DEFAULTS, "image": image}
    lines = [f"{{{{{_TEMPLATE[kind]}", f"|faction={faction}"]
    lines += [f"|{param}={value}" for param, value in pairs]
    lines += [f"|{field}={defaults.get(field, '')}" for field in manual]
    lines.append("}}")
    return "\n".join(lines)


def available_upgrades(obj) -> list[str]:
    """The trigger upgrade names `obj` can obtain, for the UI to offer as toggles (passed
    back to `generate_page` to resolve the page after taking them)."""
    return find_upgrades(obj)


def generate_page(game, obj, faction: str = "", active_upgrades=frozenset(), linker=None) -> str:
    """A full wiki page draft for `obj`: infobox, quote, abilities, upgrades, navbox. `faction`
    fills the infobox/navbox/category template (blank leaves them for the editor);
    `active_upgrades` resolves the page as the object is after taking them. With a `linker`,
    unit/hero names in the recruitment tables, abilities and intro are hyperlinked to their
    wiki pages (best-effort, only where a page exists)."""
    kind = _object_kind(obj)
    entries = command_entries(game, obj, active_upgrades)
    abilities = [e for e in entries if e["kind"] == "ability"]
    upgrades = [e for e in entries if e["kind"] == "upgrade"]
    dated = date.today().strftime("%B %Y")

    parts = [
        infobox_block(obj, kind, faction, active_upgrades, portrait_filename(obj)),
        "{{Quote||}}",
        _intro(game, obj, linker),
    ]
    # A building's recruitment (UNIT_BUILD units and REVIVE-indexed heroes) leads its body,
    # ahead of the abilities/upgrades every object shares.
    if kind == "building":
        section = recruitment_section(game, obj, linker)
        if section:
            parts.append(section)

    parts.append("== Abilities ==")
    if abilities:
        parts.append("\n\n".join(ability_block(e, linker) for e in abilities))
    else:
        parts.append("<!-- No abilities detected. -->")

    if upgrades:
        parts += ["== Upgrades ==", upgrade_block(upgrades, faction, _alignment(obj))]

    category_maker = (
        "{{CategoryMaker"
        f"\n|type={kind.capitalize()}"
        "\n|summonable="
        f"\n|primary_role={_primary_role(obj)}"
        f"\n|tier={_tier(obj)}"
        f"\n|faction={faction}"
        "\n}}"
    )
    parts += [
        "== Strategy ==",
        f"{{{{Empty section|date={dated}}}}}",
        f"{{{{{faction} Navbox}}}}" if faction else "<!-- {{Faction Navbox}} -->",
        "__NOTOC__",
        category_maker,
    ]
    return "\n\n".join(parts)
