"""Render a faction's ownership graph as a Markdown digest - the agent-facing view.

`explore --json` emits the whole `FactionGraph` for a program to consume; `serve` opens a browser
for a human. This renders the same graph as one self-contained Markdown document an agent can read
top-to-bottom and reason over: the faction's identity and roster tally, its spellbook, where it
builds, every structure grouped by role with what it produces, and stat tables for its units,
heroes and upgrades. It is deterministic data extraction - the agent layers judgment (critique,
comparison, a written profile) on top of it.

Nothing here resolves anything; it only formats the dataclasses from `sage_edain.model`.
"""

from __future__ import annotations

import re

from sage_edain.model import (
    FactionGraph,
    Power,
    Profile,
    Structure,
    StructureRole,
    Weapon,
)

# The order roles are presented in: the base unpacks the citadel, foundations are built on its
# plots, prebuilt structures ship with the base, standalone buildings come from expansion plots.
_ROLE_ORDER = (
    StructureRole.CITADEL,
    StructureRole.FOUNDATION,
    StructureRole.FOUNDATION_BUILDING,
    StructureRole.PREBUILT,
    StructureRole.STANDALONE,
)


_WHITESPACE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """A localized string onto one Markdown line. In-game text uses literal `\\n` markers and real
    newlines as line breaks; collapse both (and any whitespace run) to single spaces so a
    description or effect doesn't break out of its bullet / blockquote."""
    return _WHITESPACE.sub(" ", text.replace("\\n", " ")).strip()


def _dedupe(names: list[str]) -> list[str]:
    """Display names in first-seen order, dropping repeats — a structure that produces several rank
    variants of one unit would otherwise list the same name many times."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _num(value: float | None) -> str:
    """A compact number for a table cell: integers lose their `.0`, None becomes a dash."""
    if value is None:
        return "-"
    return f"{value:g}"


def _weapon_phrase(weapon: Weapon | None) -> str:
    """A one-line attack summary, e.g. `ranged 120 PIERCE @ 250 (40 dps)`."""
    if weapon is None:
        return "-"
    parts = [weapon.kind]
    if weapon.damage is not None:
        parts.append(f"{weapon.damage:g}")
    if weapon.damage_type:
        parts.append(weapon.damage_type)
    head = " ".join(parts)
    if weapon.range:
        head += f" @ {weapon.range:g}"
    if weapon.dps:
        head += f" ({weapon.dps:g} dps)"
    return head


def _resilience(profile: Profile) -> str:
    """What the unit is toughest / weakest against, from its effective-HP defenses. `defenses` is
    already ranked strongest-first by `build_profile`."""
    if not profile.defenses:
        return "-"
    tough_type, tough_hp = profile.defenses[0]
    weak_type, weak_hp = profile.defenses[-1]
    if tough_type == weak_type:
        return f"{tough_type} {tough_hp:g}"
    return f"tough vs {tough_type} ({tough_hp:g}), weak vs {weak_type} ({weak_hp:g})"


def _power_lines(power: Power) -> list[str]:
    """A spellbook power / ability as a heading-free Markdown bullet block."""
    tag = f" `{power.kind}`" if power.kind else ""
    cd = f" - {power.cooldown:g}s cooldown" if power.cooldown else ""
    lines = [f"- **{power.display}**{tag}{cd}"]
    if power.effect:
        lines.append(f"  - {_clean(power.effect)}")
    if power.creates:
        lines.append("  - summons: " + ", ".join(_dedupe([d or n for n, d in power.creates])))
    if power.transforms_into:
        forms = _dedupe([d or n for n, d in power.transforms_into])
        lines.append("  - transforms into: " + ", ".join(forms))
    if power.weapon is not None:
        lines.append(f"  - weapon: {_weapon_phrase(power.weapon)}")
    if power.modifiers:
        lines.append("  - effects: " + ", ".join(f"{stat} {amt}" for stat, amt in power.modifiers))
    return lines


def _spellbook_section(graph: FactionGraph) -> list[str]:
    if graph.spellbook is None or not graph.spellbook.powers:
        return []
    lines = [f"## Spellbook - {graph.spellbook.name}", ""]
    for power in graph.spellbook.powers:
        lines += _power_lines(power)
    lines.append("")
    return lines


def _start_points_section(graph: FactionGraph) -> list[str]:
    if not graph.start_points:
        return []
    lines = ["## Start points", ""]
    for point in graph.start_points:
        target = (
            f"base `{point.base}`"
            if point.base
            else (f"structure `{point.structure}`" if point.structure else "-")
        )
        cost = f" ({_num(point.cost)})" if point.cost else ""
        lines.append(f"- **{point.flag}** - {point.kind.value} -> {target}{cost}")
        if point.citadel:
            lines.append(f"  - citadel: {point.citadel}")
        if point.foundations:
            lines.append(f"  - foundations: {', '.join(point.foundations)}")
        if point.prebuilt:
            lines.append(f"  - prebuilt: {', '.join(point.prebuilt)}")
    lines.append("")
    return lines


def _structure_block(graph: FactionGraph, structure: Structure) -> list[str]:
    lines = [f"### {structure.display}  `{structure.name}`"]
    if structure.description:
        lines.append(f"> {_clean(structure.description)}")
    produces: list[str] = []
    if structure.trains_units:
        names = _dedupe(
            [graph.units[u].display for u in structure.trains_units if u in graph.units]
        )
        produces.append(f"- trains: {', '.join(names)}")
    if structure.recruits_heroes:
        names = _dedupe(
            [graph.heroes[h].display for h in structure.recruits_heroes if h in graph.heroes]
        )
        produces.append(f"- recruits: {', '.join(names)}")
    if structure.researches_upgrades:
        researched = structure.researches_upgrades
        names = _dedupe([graph.upgrades[u].display for u in researched if u in graph.upgrades])
        produces.append(f"- researches: {', '.join(names)}")
    lines += produces
    for ability in structure.abilities:
        lines += _power_lines(ability)
    lines.append("")
    return lines


def _structures_section(graph: FactionGraph) -> list[str]:
    if not graph.structures:
        return []
    lines = [f"## Structures ({len(graph.structures)})", ""]
    by_role: dict[StructureRole, list[Structure]] = {}
    for structure in graph.structures.values():
        by_role.setdefault(structure.role, []).append(structure)
    for role in _ROLE_ORDER:
        group = by_role.get(role)
        if not group:
            continue
        lines.append(f"### {role.value.replace('_', ' ')}")
        lines.append("")
        for structure in group:
            lines += _structure_block(graph, structure)
    return lines


def _unit_rows(graph: FactionGraph) -> list[str]:
    rows = [
        "| Unit | Cost | CP | Health | Attack | Resilience | Built at |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for unit in graph.units.values():
        profile = unit.profile
        attack = _weapon_phrase(profile.weapons[0]) if profile and profile.weapons else "-"
        resilience = _resilience(profile) if profile else "-"
        health = _num(profile.health) if profile else "-"
        built_at = ", ".join(sorted({p.structure for p in unit.producers})) or "-"
        rows.append(
            f"| {unit.display} | {_num(unit.cost)} | {_num(unit.command_points)} | "
            f"{health} | {attack} | {resilience} | {built_at} |"
        )
    return rows


def _units_section(graph: FactionGraph) -> list[str]:
    if not graph.units:
        return []
    lines = [f"## Units ({len(graph.units)})", "", *_unit_rows(graph), ""]
    # Unit abilities don't fit a table row; list them beneath for the ones that have any.
    detail = []
    for unit in graph.units.values():
        abilities = unit.profile.abilities if unit.profile else []
        if not abilities:
            continue
        detail.append(f"- **{unit.display}** abilities:")
        for ability in abilities:
            detail += [f"  {line}" for line in _power_lines(ability)]
    if detail:
        lines += ["**Unit abilities**", "", *detail, ""]
    return lines


def _heroes_section(graph: FactionGraph) -> list[str]:
    if not graph.heroes:
        return []
    lines = [
        f"## Heroes ({len(graph.heroes)})",
        "",
        "| Hero | Health | Attack | Resilience | Recruited at |",
        "| --- | --- | --- | --- | --- |",
    ]
    for hero in graph.heroes.values():
        profile = hero.profile
        attack = _weapon_phrase(profile.weapons[0]) if profile and profile.weapons else "-"
        resilience = _resilience(profile) if profile else "-"
        health = _num(profile.health) if profile else "-"
        recruited_at = ", ".join(sorted({p.structure for p in hero.producers})) or "-"
        lines.append(f"| {hero.display} | {health} | {attack} | {resilience} | {recruited_at} |")
    lines.append("")
    detail = []
    for hero in graph.heroes.values():
        abilities = hero.profile.abilities if hero.profile else []
        if not abilities:
            continue
        detail.append(f"- **{hero.display}** abilities:")
        for ability in abilities:
            detail += [f"  {line}" for line in _power_lines(ability)]
    if detail:
        lines += ["**Hero abilities**", "", *detail, ""]
    return lines


def _upgrades_section(graph: FactionGraph) -> list[str]:
    if not graph.upgrades:
        return []
    lines = [
        f"## Upgrades ({len(graph.upgrades)})",
        "",
        "| Upgrade | Cost | Researched at |",
        "| --- | --- | --- |",
    ]
    for upgrade in graph.upgrades.values():
        researched_at = ", ".join(sorted({p.structure for p in upgrade.producers})) or "-"
        lines.append(f"| {upgrade.display} | {_num(upgrade.cost)} | {researched_at} |")
    lines.append("")
    return lines


def render_report(graph: FactionGraph) -> str:
    """One faction's ownership graph as a Markdown digest."""
    side = f", side `{graph.side}`" if graph.side else ""
    tally = (
        f"**Roster:** {len(graph.structures)} structures - {len(graph.units)} units - "
        f"{len(graph.heroes)} heroes - {len(graph.upgrades)} upgrades"
    )
    if graph.spellbook:
        tally += f" - {len(graph.spellbook.powers)} spellbook powers"
    lines = [
        f"# {graph.display or graph.name} - faction report",
        "",
        f"*template `{graph.name}`{side}*",
        "",
        tally,
        "",
        *_spellbook_section(graph),
        *_start_points_section(graph),
        *_structures_section(graph),
        *_units_section(graph),
        *_heroes_section(graph),
        *_upgrades_section(graph),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_roster_table(graphs: list[FactionGraph]) -> str:
    """A one-row-per-faction comparison table, for picking which faction to dig into."""
    lines = [
        "# Faction roster",
        "",
        "| Faction | Side | Structures | Units | Heroes | Upgrades | Powers |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for graph in graphs:
        powers = len(graph.spellbook.powers) if graph.spellbook else 0
        lines.append(
            f"| {graph.display or graph.name} | {graph.side or '-'} | {len(graph.structures)} | "
            f"{len(graph.units)} | {len(graph.heroes)} | {len(graph.upgrades)} | {powers} |"
        )
    lines.append("")
    return "\n".join(lines)
