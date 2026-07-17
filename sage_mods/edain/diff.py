"""Faction-level changelog between two versions of a mod - the balance-review view.

`sage_ini diff` reports raw definition/field changes; this compares two built
`FactionGraph`s instead, so the changes read in player terms: which units, heroes,
upgrades and structures a faction gained or lost, and how a surviving entity's headline
stats moved (cost, health, speed, per-weapon damage/DPS, effective armor, ability
cooldowns). Rendered as a Markdown digest an agent (or a changelog author) reads
top-to-bottom, or as JSON via `to_dict`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sage_utils.factiongraph.model import (
    FactionGraph,
    Power,
    Profile,
    ResearchableUpgrade,
    Spellbook,
    ToDictMixin,
    _named_pairs,
)

__all__ = [
    "EntityChange",
    "FactionDiff",
    "ModDiff",
    "RosterDiff",
    "StatChange",
    "diff_graphs",
    "format_mod_diff",
]


@dataclass
class StatChange(ToDictMixin):
    """One stat's move: `old`/`new` are numbers (or None when the side lacks the stat)."""

    stat: str
    old: float | str | None
    new: float | str | None


@dataclass
class EntityChange(ToDictMixin):
    """A surviving unit/hero/upgrade/structure whose stats moved."""

    name: str
    display: str
    changes: list[StatChange] = field(default_factory=list)


@dataclass
class RosterDiff(ToDictMixin):
    """One leaf kind's changes: entities only in the new version, only in the old, and the
    shared ones whose stats moved. `added`/`removed` are (name, display) pairs."""

    added: list[tuple[str, str]] = field(
        default_factory=list, metadata={"to_dict": _named_pairs, "schema": "[{name, display}]"}
    )
    removed: list[tuple[str, str]] = field(
        default_factory=list, metadata={"to_dict": _named_pairs, "schema": "[{name, display}]"}
    )
    changed: list[EntityChange] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


@dataclass
class FactionDiff(ToDictMixin):
    """Everything that changed for one faction between the two versions."""

    name: str
    display: str
    spellbook: RosterDiff = field(default_factory=RosterDiff)  # powers, by display name
    structures: RosterDiff = field(default_factory=RosterDiff)
    units: RosterDiff = field(default_factory=RosterDiff)
    heroes: RosterDiff = field(default_factory=RosterDiff)
    upgrades: RosterDiff = field(default_factory=RosterDiff)

    def is_empty(self) -> bool:
        return all(
            roster.is_empty()
            for roster in (self.spellbook, self.structures, self.units, self.heroes, self.upgrades)
        )


@dataclass
class ModDiff(ToDictMixin):
    """The whole mod's faction-level changes. `factions_changed` lists only factions with
    actual changes; unchanged ones are dropped so the changelog stays readable."""

    factions_added: list[tuple[str, str]] = field(
        default_factory=list, metadata={"to_dict": _named_pairs, "schema": "[{name, display}]"}
    )
    factions_removed: list[tuple[str, str]] = field(
        default_factory=list, metadata={"to_dict": _named_pairs, "schema": "[{name, display}]"}
    )
    factions_changed: list[FactionDiff] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.factions_added or self.factions_removed or self.factions_changed)


def _profile_stats(profile: Profile | None) -> dict[str, float | str | None]:
    """A profile's comparable headline stats, flattened to labeled scalars: the plain
    numbers, each weapon's damage/DPS/range by slot index, and effective health per damage
    type. Missing profile compares as all-None (every stat the other side has reads as a
    change)."""
    stats: dict[str, float | str | None] = {}
    if profile is None:
        return stats
    stats["health"] = profile.health
    stats["speed"] = profile.speed
    stats["build_cost"] = profile.build_cost
    stats["build_time"] = profile.build_time
    stats["command_points"] = profile.command_points
    for index, weapon in enumerate(profile.weapons, 1):
        prefix = f"weapon{index}" if len(profile.weapons) > 1 else "weapon"
        stats[f"{prefix} damage"] = weapon.damage
        stats[f"{prefix} dps"] = weapon.dps
        stats[f"{prefix} range"] = weapon.range
    for damage_type, effective in profile.defenses:
        stats[f"defense vs {damage_type}"] = round(effective) if effective is not None else None
    return stats


def _stat_changes(
    old: dict[str, float | str | None], new: dict[str, float | str | None]
) -> list[StatChange]:
    changes = []
    for stat in {*old, *new}:
        before, after = old.get(stat), new.get(stat)
        if before != after:
            changes.append(StatChange(stat, before, after))
    changes.sort(key=lambda c: c.stat)
    return changes


def _entity_stats(entity) -> dict[str, float | str | None]:
    """An entity's comparable stats: its own cost fields plus its profile's."""
    stats = _profile_stats(getattr(entity, "profile", None))
    cost = getattr(entity, "cost", None)
    if cost is not None or "build_cost" not in stats:
        stats["cost"] = cost
        stats.pop("build_cost", None)  # the leaf-level cost supersedes the profile's
    command_points = getattr(entity, "command_points", None)
    if command_points is not None:
        stats["command_points"] = command_points
    return stats


def _upgrade_stats(upgrade: ResearchableUpgrade) -> dict[str, float | str | None]:
    return {"cost": upgrade.cost}


def _diff_roster(old: dict, new: dict, stats_of) -> RosterDiff:
    """Match two `{name: entity}` tables and compare the shared entities' stats."""
    diff = RosterDiff()
    for name in new:
        if name not in old:
            diff.added.append((name, new[name].display))
    for name in old:
        if name not in new:
            diff.removed.append((name, old[name].display))
    for name in old.keys() & new.keys():
        changes = _stat_changes(stats_of(old[name]), stats_of(new[name]))
        if changes:
            diff.changed.append(EntityChange(name, new[name].display, changes))
    diff.changed.sort(key=lambda c: c.name)
    return diff


def _power_table(spellbook: Spellbook | None) -> dict[str, Power]:
    if spellbook is None:
        return {}
    return {power.name: power for power in spellbook.powers}


def _power_stats(power: Power) -> dict[str, float | str | None]:
    return {"cooldown": power.cooldown}


def diff_faction(old: FactionGraph, new: FactionGraph) -> FactionDiff:
    """What changed for one faction between two builds of its graph."""
    return FactionDiff(
        name=new.name,
        display=new.display or old.display,
        spellbook=_diff_roster(
            _power_table(old.spellbook), _power_table(new.spellbook), _power_stats
        ),
        structures=_diff_roster(old.structures, new.structures, _entity_stats),
        units=_diff_roster(old.units, new.units, _entity_stats),
        heroes=_diff_roster(old.heroes, new.heroes, _entity_stats),
        upgrades=_diff_roster(old.upgrades, new.upgrades, _upgrade_stats),
    )


def diff_graphs(old: list[FactionGraph], new: list[FactionGraph]) -> ModDiff:
    """Compare two versions' faction graphs, matched by faction template name."""
    old_by_name = {graph.name: graph for graph in old}
    new_by_name = {graph.name: graph for graph in new}
    diff = ModDiff()
    for name, graph in new_by_name.items():
        if name not in old_by_name:
            diff.factions_added.append((name, graph.display))
    for name, graph in old_by_name.items():
        if name not in new_by_name:
            diff.factions_removed.append((name, graph.display))
    for name in sorted(old_by_name.keys() & new_by_name.keys()):
        faction_diff = diff_faction(old_by_name[name], new_by_name[name])
        if not faction_diff.is_empty():
            diff.factions_changed.append(faction_diff)
    return diff


def _num(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _roster_lines(title: str, roster: RosterDiff) -> list[str]:
    if roster.is_empty():
        return []
    lines = [f"### {title}", ""]
    if roster.added:
        lines.append(
            "- Added: " + ", ".join(f"{display} (`{name}`)" for name, display in roster.added)
        )
    if roster.removed:
        lines.append(
            "- Removed: " + ", ".join(f"{display} (`{name}`)" for name, display in roster.removed)
        )
    for change in roster.changed:
        moves = "; ".join(f"{c.stat} {_num(c.old)} → {_num(c.new)}" for c in change.changes)
        lines.append(f"- **{change.display}** (`{change.name}`): {moves}")
    lines.append("")
    return lines


def format_mod_diff(diff: ModDiff, old_label: str, new_label: str) -> str:
    """The faction changelog as a Markdown digest."""
    lines = [f"# Faction changes: {old_label} → {new_label}", ""]
    if diff.is_empty():
        lines.append("No faction-level differences.")
        return "\n".join(lines) + "\n"
    if diff.factions_added:
        lines.append(
            "- New factions: "
            + ", ".join(f"{display} (`{name}`)" for name, display in diff.factions_added)
        )
    if diff.factions_removed:
        lines.append(
            "- Removed factions: "
            + ", ".join(f"{display} (`{name}`)" for name, display in diff.factions_removed)
        )
    if diff.factions_added or diff.factions_removed:
        lines.append("")
    for faction in diff.factions_changed:
        lines += [f"## {faction.display} (`{faction.name}`)", ""]
        lines += _roster_lines("Spellbook", faction.spellbook)
        lines += _roster_lines("Structures", faction.structures)
        lines += _roster_lines("Units", faction.units)
        lines += _roster_lines("Heroes", faction.heroes)
        lines += _roster_lines("Upgrades", faction.upgrades)
    return "\n".join(lines).rstrip("\n") + "\n"
