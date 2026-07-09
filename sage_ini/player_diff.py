"""Player-facing changelog: re-renders a `GameDiff` in the terms a player reads. Definitions
are referenced by their localized display name (a special power through the command button
that grants it), macro operands resolve to the numbers the engine sees, and each change is
attributed back through the reference graph to the display-named units that use it, grouped
under their faction - so "SpecialAbilityElvenAmbush ReloadTime 60000 -> 90000" reads as a
cooldown change on "Ambush of the Wood-elves", listed under Lothlorien with the units that
carry the ability.

Only gameplay-stat fields (cost, health, damage, armor, cooldowns, ...) are reported; the
full field-level detail stays in `format_game_diff`. Each side renders with its own macro
table, so a changed `#define` also surfaces here on every definition whose stats it moves,
even though no line of that definition changed. A change whose old side was a broken
reference (naming nothing) is a repair, not a balance move, and lands in a trailing
Bugfixes section; a spellbook power that no named unit carries is attributed to the
faction whose spellbook grants it.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from typing import NamedTuple

from sage_ini.diff import FieldChange, GameDiff, ObjectDiff
from sage_ini.model.game import Game
from sage_ini.model.objects import IniObject
from sage_ini.model.types import eval_number
from sage_ini.model.xref import Xref
from sage_ini.walk import walk_objects

__all__ = ["format_player_diff"]

# Gameplay-stat field keys reported in the player changelog, wherever they sit in a
# definition's subtree: key -> (player-facing label, unit). Unit "ms" renders as seconds,
# "s" appends the suffix, "raw" is multi-token filter text that only gets macro expansion.
_BALANCE_FIELDS = {
    "BuildCost": ("Cost", ""),
    "BuildTime": ("Build time", "s"),
    "CommandPoints": ("Command points", ""),
    "MaxHealth": ("Health", ""),
    "ReloadTime": ("Cooldown", "ms"),
    "Damage": ("Damage", ""),
    "PrimaryDamage": ("Damage", ""),
    "SecondaryDamage": ("Splash damage", ""),
    "DamageScalar": ("Damage modifier", "raw"),
    "Range": ("Range", ""),
    "AttackRange": ("Range", ""),
    "VisionRange": ("Vision range", ""),
    "Speed": ("Speed", ""),
    "DelayBetweenShots": ("Attack delay", "ms"),
    "PreAttackDelay": ("Attack delay", "ms"),
    "Armor": ("Armor", "armor"),
}

# Pseudo-faction buckets, rendered after the real factions. Bugfixes collects changes
# whose old side was a broken reference (naming nothing) - repairing one is a fix, not a
# balance move, so it reads apart from the faction lists.
_MULTIPLE = "Multiple factions"
_OTHER = "Other"
_BUGFIXES = "Bugfixes"

# What to call a definition that has no display name of its own, per table - it is then
# described by kind and owner ("Weapon of Faramir") instead of by its code name.
_KIND_LABELS = {
    "objects": "Unit",
    "weapons": "Weapon",
    "armorsets": "Armor",
    "specialpowers": "Ability",
    "upgrades": "Upgrade",
    "modifiers": "Effect",
    "locomotors": "Movement",
}

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# UI markup inside localized names: a shortcut-key marker ("Warg Lair (&X)", "&Gondor")
# and literal "\n" line breaks (only the first line names the thing).
_HOTKEY = re.compile(r"\s*\(&.\)|&")

# How many "used by" units / armor damage types to list before folding into "+n more".
_MAX_USERS = 4
_MAX_ARMOR_TYPES = 8


def _raw_scalar(obj: IniObject, key: str) -> str | None:
    """A raw field as one string token (last write wins for a repeated key)."""
    raw = obj._fields.get(key)
    if raw is None:
        return None
    text = str(raw[-1] if isinstance(raw, list) else raw).strip()
    return text.split()[0] if text else None


class _View:
    """Per-game rendering context: localized lookups, macro expansion, and the reference
    graph used to attribute changes to units."""

    def __init__(self, game: Game):
        self.game = game

    @cached_property
    def xref(self) -> Xref:
        return Xref.for_game(self.game)

    @cached_property
    def _folded_strings(self) -> dict[str, str]:
        return {label.lower(): value for label, value in self.game.strings.items()}

    def localize(self, label) -> str | None:
        """A string-table label resolved to display text, or None when it names nothing."""
        if isinstance(label, list):
            label = label[-1] if label else None
        if not label:
            return None
        first = str(label).split()[0]
        value = self.game.strings.get(first)
        if value is None:
            value = self._folded_strings.get(first.lower())
        if value is None:
            return None
        return _HOTKEY.sub("", value.split("\\n")[0]).strip() or None

    def display(self, obj: IniObject) -> str | None:
        return self.localize(obj._fields.get("DisplayName"))

    def side(self, obj: IniObject) -> str | None:
        """The object's `Side` token, walking the parent chain like the engine does."""
        node: IniObject | None = obj
        while node is not None:
            raw = _raw_scalar(node, "Side")
            if raw is not None:
                return raw
            node = getattr(node, "parent", None)
        return None

    @cached_property
    def _faction_display(self) -> dict[str, str]:
        """Side token -> localized faction name, playable templates taking precedence."""
        table: dict[str, str] = {}
        factions = list(self.game.tables.get("factions", {}).values())
        playable = [f for f in factions if str(_raw_scalar(f, "PlayableSide")).lower() == "yes"]
        for faction in playable + factions:
            side = _raw_scalar(faction, "Side")
            if side and side not in table:
                table[side] = self.localize(faction._fields.get("DisplayName")) or side
        return table

    def faction(self, obj: IniObject) -> str | None:
        side = self.side(obj)
        if side is None:
            return None
        return self._faction_display.get(side, side)

    def expand(self, text: str) -> str:
        """Every macro token in `text` replaced by its value (chains followed a few deep)."""
        macros = self.game.macros
        for _ in range(3):
            replaced = _TOKEN.sub(lambda m: str(macros.get(m.group(), m.group())), text)
            if replaced == text:
                break
            text = replaced
        return text

    def number(self, raw) -> float | None:
        if raw is None:
            return None
        # A repeated scalar key arrives joined with ", "; the engine keeps the last write,
        # so that is the value the player experiences.
        text = str(raw)
        if "," in text:
            text = text.rsplit(",", 1)[-1].strip()
            if not text:
                return None
        try:
            return eval_number(self.game, text)
        except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
            return None

    def render(self, raw, unit: str) -> str:
        if unit != "raw":
            number = self.number(raw)
            if number is not None:
                return _format_number(number, unit)
        return self.expand(str(raw))


def _format_number(number: float, unit: str) -> str:
    if unit == "ms":
        number, unit = number / 1000, "s"
    text = str(int(number)) if number == int(number) else str(round(number, 2))
    return f"{text}s" if unit == "s" else text


def _percent_delta(old: float | None, new: float | None) -> str:
    if old is None or new is None or old == 0:
        return ""
    percent = (new - old) / abs(old) * 100
    if abs(percent) < 0.5:
        return ""
    return f" ({percent:+.0f}%)"


class _Move(NamedTuple):
    """One rendered stat move; `bugfix` marks a repaired broken reference, which is
    reported in the Bugfixes section instead of the faction's balance list."""

    text: str
    bugfix: bool = False


def _flatten(diff: ObjectDiff) -> list[FieldChange]:
    """Every field change in the definition's subtree, module nesting flattened away -
    the player cares that health moved, not which module holds it."""
    changes = list(diff.fields)
    for child in diff.changed_children:
        changes.extend(_flatten(child.diff))
    return changes


def _render_move(
    label: str, unit: str, old_raw: str, new_raw: str, old_view: _View, new_view: _View
) -> str | None:
    """One stat move rendered per side with that side's macros; None when both sides
    resolve to the same value (a refactor onto a macro or a case-only token edit, not a
    player-visible change)."""
    old_text = old_view.render(old_raw, unit)
    new_text = new_view.render(new_raw, unit)
    if old_text.casefold() == new_text.casefold():
        return None
    delta = ""
    if unit != "raw":
        delta = _percent_delta(old_view.number(old_raw), new_view.number(new_raw))
    return f"{label} {old_text} → {new_text}{delta}"


def _armor_entries(text: str | None) -> dict[str, str]:
    """`"SLASH 55%, PIERCE 30%"` (an Armor list joined back into one line) -> type -> value."""
    entries: dict[str, str] = {}
    for part in (text or "").split(","):
        tokens = part.split()
        if len(tokens) >= 2:
            entries[tokens[0]] = " ".join(tokens[1:])
    return entries


def _armor_moves(
    old_entries: dict[str, str], new_entries: dict[str, str], old_view: _View, new_view: _View
) -> str | None:
    """The per-damage-type moves between two armor tables, macro-expanded and folded past
    `_MAX_ARMOR_TYPES` entries."""
    parts = []
    for damage_type in {**new_entries, **old_entries}:
        old_value = old_entries.get(damage_type)
        new_value = new_entries.get(damage_type)
        old_text = old_view.expand(old_value) if old_value is not None else "-"
        new_text = new_view.expand(new_value) if new_value is not None else "-"
        if old_text != new_text:
            parts.append(f"vs {damage_type} {old_text} → {new_text}")
    if not parts:
        return None
    shown = parts[:_MAX_ARMOR_TYPES]
    if len(parts) > _MAX_ARMOR_TYPES:
        shown.append(f"+{len(parts) - _MAX_ARMOR_TYPES} more")
    return ", ".join(shown)


def _armor_set_of(view: _View, name: str | None) -> dict[str, str] | None:
    """The per-type table of a named armor-set definition in `view`'s game, or None."""
    if not name:
        return None
    armor = view.game.tables.get("armorsets", {}).get(str(name).split()[0])
    if armor is None:
        return None
    raw = armor._fields.get("Armor")
    items = raw if isinstance(raw, list) else [raw] if raw is not None else []
    return _armor_entries(", ".join(str(item) for item in items))


def _render_armor_change(
    table_key: str, change: FieldChange, old_view: _View, new_view: _View
) -> _Move | None:
    """An `Armor` change in context: inside an armor-set definition it is the per-type
    table itself; inside an object it is a reference swap to another set, which renders
    as the effective per-type moves between the two sets - a swap onto a set with the
    same values (a rename) is not a player-visible change. An old reference that names
    no set anywhere was broken (the unit had no armor scaling), so repairing it is a
    bugfix rather than a balance move."""
    if table_key == "armorsets":
        moves = _armor_moves(
            _armor_entries(change.old), _armor_entries(change.new), old_view, new_view
        )
        return _Move(f"Armor {moves}") if moves else None
    old_set = _armor_set_of(old_view, change.old) or _armor_set_of(new_view, change.old)
    new_set = _armor_set_of(new_view, change.new) or _armor_set_of(old_view, change.new)
    if new_set is None:
        return None if old_set is None else _Move("Armor changed")
    if old_set is None:
        return _Move("broken armor reference fixed (armor now takes effect)", bugfix=True)
    moves = _armor_moves(old_set, new_set, old_view, new_view)
    return _Move(f"Armor {moves}") if moves else None


def _button_label(view: _View, obj: IniObject) -> str | None:
    """The localized text of a command button that grants `obj` - the name a player sees
    for a special power (or an upgrade without its own display name)."""
    for ref in sorted(view.xref.referenced_by(obj), key=lambda o: str(o.name)):
        if ref.key == "commandbuttons":
            label = view.localize(ref._fields.get("TextLabel"))
            if label:
                return label
    return None


def _anchor_units(
    view: _View, obj: IniObject, max_depth: int = 4
) -> tuple[dict[str, IniObject], list[IniObject]]:
    """Display-named objects that (transitively) use `obj`, as display -> object, plus
    the faction templates the walk reached. It follows reverse reference edges through
    display-less intermediates (a warhead's projectile, a command button, a command set)
    and stops at the first named object on each path - the unit or structure the player
    recognises. A spellbook power reaches no named object at all, only its faction (via
    the spellbook object and the player template), so the factions come back too."""
    seen = {obj}
    frontier = [obj]
    anchors: dict[str, IniObject] = {}
    factions: list[IniObject] = []
    for _ in range(max_depth):
        next_frontier = []
        for node in frontier:
            for ref in sorted(view.xref.referenced_by(node), key=lambda o: str(o.name)):
                if ref in seen:
                    continue
                seen.add(ref)
                if ref.key == "objects":
                    shown = view.display(ref)
                    if shown:
                        anchors.setdefault(shown, ref)
                        continue
                elif ref.key == "factions":
                    factions.append(ref)
                next_frontier.append(ref)
        frontier = next_frontier
        if not frontier:
            break
    return anchors, factions


@dataclass
class _Entry:
    faction: str
    sort: str
    line: str


def _compose(
    table_key: str, name: str, obj: IniObject, moves: list[str], view: _View
) -> _Entry | None:
    """One changelog line for a changed definition: a display-named object speaks for
    itself; anything else is titled by its granted-button label - or, without one, by
    kind and owner ("Weapon of Faramir") - and attributed to the units that use it. A
    definition no named unit uses but a faction's spellbook carries is attributed to the
    faction directly. Code names never appear; a definition nothing display-named uses
    is internal and yields no entry."""
    detail = "; ".join(moves)
    if table_key == "objects":
        shown = view.display(obj)
        if shown:
            faction = view.faction(obj) or _OTHER
            return _Entry(faction, shown, f"- **{shown}**: {detail}")
    anchors, faction_nodes = _anchor_units(view, obj)
    shown = view.display(obj) or _button_label(view, obj)
    if not anchors:
        if not faction_nodes or not shown:
            return None
        factions = sorted({view.faction(node) or _OTHER for node in faction_nodes})
        faction = factions[0] if len(factions) == 1 else _MULTIPLE
        title = f"**{shown}**" if len(factions) == 1 else f"**{shown}** ({', '.join(factions)})"
        return _Entry(faction, shown, f"- {title}: {detail}")
    factions = sorted({view.faction(anchor) or _OTHER for anchor in anchors.values()})
    if len(factions) == 1:
        faction = factions[0]
        users = sorted(anchors)
    else:
        faction = _MULTIPLE
        users = sorted(
            f"{user} ({view.faction(anchor) or _OTHER})" for user, anchor in anchors.items()
        )
    if len(users) > _MAX_USERS:
        users = users[:_MAX_USERS] + [f"+{len(users) - _MAX_USERS} more"]
    used_by = ", ".join(users)
    if shown:
        return _Entry(faction, shown, f"- **{shown}** (used by {used_by}): {detail}")
    kind = _KIND_LABELS.get(table_key, "Item")
    return _Entry(faction, users[0], f"- {kind} of {used_by}: {detail}")


def _definition(old_view: _View, new_view: _View, table_key: str, name: str) -> IniObject | None:
    obj = new_view.game.tables.get(table_key, {}).get(name)
    if obj is None:
        obj = old_view.game.tables.get(table_key, {}).get(name)
    return obj


def _change_moves(
    diff: GameDiff, old_view: _View, new_view: _View, reported: set[tuple[str, str, str]]
) -> dict[tuple[str, str], list[_Move]]:
    """Rendered stat moves per changed definition, keyed by (table, name). `reported`
    collects the (table, definition, field) triples covered here so the macro pass skips
    them."""
    moves_by_def: dict[tuple[str, str], list[_Move]] = defaultdict(list)
    for table in diff.tables:
        for name, obj_diff in table.changed:
            moves = moves_by_def[(table.key, name)]
            for change in _flatten(obj_diff):
                spec = _BALANCE_FIELDS.get(change.key)
                if spec is None or change.old is None or change.new is None:
                    continue
                label, unit = spec
                if change.key == "Armor":
                    rendered = _render_armor_change(table.key, change, old_view, new_view)
                else:
                    text = _render_move(label, unit, change.old, change.new, old_view, new_view)
                    rendered = _Move(text) if text else None
                if rendered and rendered not in moves:
                    moves.append(rendered)
                    reported.add((table.key, name, change.key))
    return moves_by_def


def _macro_moves(
    diff: GameDiff,
    old_view: _View,
    new_view: _View,
    reported: set[tuple[str, str, str]],
    moves_by_def: dict[tuple[str, str], list[_Move]],
) -> None:
    """Fold in the stats moved by a changed `#define` alone: the definition's text is the
    same on both sides, but the value it resolves to is not. Fields already reported as
    direct changes are skipped."""
    changed_macros = [name for name, _old, _new in diff.macros.changed]
    if not changed_macros:
        return
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(name) for name in changed_macros) + r")\b", re.IGNORECASE
    )
    for table_key, table in new_view.game.tables.items():
        old_table = old_view.game.tables.get(table_key, {})
        for name, obj in table.items():
            key = str(name)
            if key not in old_table:
                continue  # an added definition is reported as new content, not a stat move
            for node in walk_objects(obj):
                for field_key, raw in node._fields.items():
                    spec = _BALANCE_FIELDS.get(field_key)
                    if spec is None or (table_key, key, field_key) in reported:
                        continue
                    values = raw if isinstance(raw, list) else [raw]
                    if not any(isinstance(v, str) and pattern.search(v) for v in values):
                        continue
                    label, unit = spec
                    text = ", ".join(str(value) for value in values)
                    if field_key == "Armor" and table_key == "armorsets":
                        armor = _armor_moves(
                            _armor_entries(text), _armor_entries(text), old_view, new_view
                        )
                        rendered = _Move(f"Armor {armor}") if armor else None
                    else:
                        moved = _render_move(label, unit, text, text, old_view, new_view)
                        rendered = _Move(moved) if moved else None
                    moves = moves_by_def[(table_key, key)]
                    if rendered and rendered not in moves:
                        moves.append(rendered)
                        reported.add((table_key, key, field_key))


def _roster_changes(diff: GameDiff, old_view: _View, new_view: _View):
    """Added / removed display-named objects, grouped by faction and deduplicated by
    display name (a building and its free-build twin read as one addition)."""
    added: dict[str, set[str]] = defaultdict(set)
    removed: dict[str, set[str]] = defaultdict(set)
    for table in diff.tables:
        if table.key != "objects":
            continue
        sides = ((table.added, added, new_view), (table.removed, removed, old_view))
        for names, bucket, view in sides:
            for name in names:
                obj = view.game.tables.get("objects", {}).get(name)
                if obj is None:
                    continue
                shown = view.display(obj)
                if not shown:
                    continue
                bucket[view.faction(obj) or _OTHER].add(shown)
    return added, removed


def format_player_diff(
    diff: GameDiff, old_game: Game, new_game: Game, old_label: str, new_label: str
) -> str:
    """The player-facing changelog as a Markdown section: factions in alphabetical order
    (cross-faction and unattributed buckets last), each listing its new and removed content
    and the stat moves of its units and their weapons, powers and armor."""
    old_view, new_view = _View(old_game), _View(new_game)
    reported: set[tuple[str, str, str]] = set()
    moves_by_def = _change_moves(diff, old_view, new_view, reported)
    _macro_moves(diff, old_view, new_view, reported, moves_by_def)
    entries = []
    for (table_key, name), moves in moves_by_def.items():
        if not moves:
            continue
        obj = _definition(old_view, new_view, table_key, name)
        if obj is None:
            continue
        balance = [move.text for move in moves if not move.bugfix]
        fixes = [move.text for move in moves if move.bugfix]
        if balance:
            entry = _compose(table_key, name, obj, balance, new_view)
            if entry is not None:
                entries.append(entry)
        if fixes:
            entry = _compose(table_key, name, obj, fixes, new_view)
            if entry is not None:
                # The Bugfixes section spans all factions, so fold the faction into the
                # title (a "used by"/"of" title already names its context).
                line = entry.line
                if entry.faction != _OTHER:
                    line = line.replace("**:", f"** ({entry.faction}):", 1)
                entries.append(_Entry(_BUGFIXES, entry.sort, line))
    added, removed = _roster_changes(diff, old_view, new_view)

    by_faction: dict[str, list[_Entry]] = defaultdict(list)
    for entry in entries:
        by_faction[entry.faction].append(entry)

    factions = set(by_faction) | set(added) | set(removed)
    tail = [bucket for bucket in (_MULTIPLE, _OTHER, _BUGFIXES) if bucket in factions]
    ordered = sorted(factions - {_MULTIPLE, _OTHER, _BUGFIXES}) + tail

    lines = [f"# Player changes: {old_label} → {new_label}", ""]
    if not ordered:
        lines.append("(no player-facing differences)")
        return "\n".join(lines) + "\n"
    for faction in ordered:
        lines.append(f"## {faction}")
        if faction in added:
            lines.append("- New: " + ", ".join(sorted(added[faction])))
        if faction in removed:
            lines.append("- Removed: " + ", ".join(sorted(removed[faction])))
        # Without code names, internal variants of one unit render identically - say it once.
        seen: set[str] = set()
        for entry in sorted(by_faction.get(faction, []), key=lambda e: e.sort):
            if entry.line not in seen:
                seen.add(entry.line)
                lines.append(entry.line)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
