"""Condense a multi-nugget weapon into the compact damage lines an infobox shows.

A weapon spreads its damage across several `DamageNugget`s, each scoped to object filters
(`DamageScalar`), plus a `MetaImpactNugget` for knockback. `weapon_summary_lines` turns that
into a damage header per nugget, each followed by its modifiers as wiki bullet items, e.g.::

    '''vs General''': 150 WATER (50R)
    * +150% vs Single
    * Knockback (50R) vs Non-hero
    '''vs Structure''': 240 SIEGE (30R)

Each header names the nugget's primary target archetype (see `sage_wiki.archetypes`, bolded
for the wiki), its modified damage, damage type and blast radius; per-archetype bonuses,
knockback (MetaImpactNugget) and damage-over-time (DOTNugget, e.g. `POISON DoT 20/s for 30s`)
hang below it as `*` bullets. A `0%` scalar drops an archetype: on an inclusion
(`0% +STRUCTURE`) it just removes that archetype from the general target (another nugget covers
it); on an exclusion (`0% ALL -STRUCTURE`) only the spared set is hit, so the header's target
becomes that complement. Weapon-wide effects (knockback, DoT) attach to the broadest header.
"""

from sage_utils.views import weapon_damage_breakdown
from sage_wiki.archetypes import archetype_key, label_for, label_for_key


def _fmt_num(value) -> str:
    """A stat rounded to a whole number (`50.0` -> `50`, `12.6` -> `13`)."""
    return str(round(float(value)))


def _nugget_render(nugget: dict) -> tuple[str, str, list[str]]:
    """One damage nugget rendered to `(primary_archetype, header, modifiers)`. The primary is
    "General" unless a `0%` exclusion narrows the target to its complement; `modifiers` are the
    per-archetype bonus/penalty strings shown as bullets below the header."""
    primary = "General"
    modifiers: list[str] = []
    for multiplier, object_filter in nugget["scalars"]:
        if multiplier == 1:
            continue  # a 100% scalar is a no-op
        included, excluded = archetype_key(object_filter)
        if multiplier == 0:
            # An exclusion (`0% ALL -STRUCTURE`) spares only the excluded set, so that set is
            # the real target; an inclusion (`0% +STRUCTURE`) just drops it from "All".
            if not included and excluded:
                primary = label_for_key((excluded, frozenset()))
            continue
        percent = (multiplier - 1) * 100
        modifiers.append(f"{round(percent):+}% vs {label_for(object_filter)}")

    header = f"'''vs {primary}''': {_fmt_num(nugget['damage'])}"
    if nugget["damage_type"]:
        header += f" {nugget['damage_type']}"
    if nugget["radius"]:
        header += f" ({_fmt_num(nugget['radius'])}R)"
    return primary, header, modifiers


def _knockback_fragment(knockback: dict) -> str:
    """The `Knockback (50R) vs Non-hero` fragment. HeroResist >= 1 spares heroes (Non-hero),
    less throws everyone (All)."""
    target = "Non-hero" if (knockback["hero_resist"] or 0) >= 1 else "All"
    return f"Knockback ({_fmt_num(knockback['radius'])}R) vs {target}"


def _dot_fragment(dot: dict) -> str:
    """A damage-over-time effect as `POISON DoT 20/s for 30s`. The per-second rate is the tick
    damage scaled by the interval (`DamageInterval` ms); the duration is `DamageDuration` ms in
    seconds. The SpecialObjectFilter is ignored - a DoT is taken to apply to All."""
    interval = dot["interval"] or 0
    per_second = dot["damage"] * 1000 / interval if interval else dot["damage"]
    prefix = f"{dot['damage_type']} DoT" if dot["damage_type"] else "DoT"
    text = f"{prefix} {_fmt_num(per_second)}/s"
    if dot["duration"]:
        text += f" for {_fmt_num(dot['duration'] / 1000)}s"
    return text


def weapon_summary_lines(weapon, state) -> list[str]:
    """The compact damage lines for `weapon` resolved under `state`: a header per active damage
    nugget, each followed by its modifiers as `*` bullet lines, with the knockback bullet folded
    onto the broadest ("All") header. Empty when the weapon deals no nugget damage and has no
    knockback."""
    breakdown = weapon_damage_breakdown(weapon, state)
    # Each entry is [primary, header, [modifiers]]; modifiers become bullets at render time.
    entries: list[list] = [list(_nugget_render(nugget)) for nugget in breakdown["damage_nuggets"]]

    # Weapon-wide effects (knockback, DoTs) apply to All; they hang under the broadest header.
    effects: list[str] = []
    if breakdown["knockback"]:
        effects.append(_knockback_fragment(breakdown["knockback"]))
    effects.extend(_dot_fragment(dot) for dot in breakdown["dots"])

    if effects:
        if entries:
            primaries = [primary for primary, _, _ in entries]
            index = primaries.index("All") if "All" in primaries else 0
            entries[index][2].extend(effects)
        else:
            # A weapon with only effects (no damage nugget): lone, unbulleted lines.
            return effects

    lines: list[str] = []
    for _primary, header, modifiers in entries:
        lines.append(header)
        lines.extend(f"* {modifier}" for modifier in modifiers)
    return lines
