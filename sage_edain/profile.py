"""A non-technical stat/weapon/ability snapshot of an object — the same facts sage_ui's UnitPanel
shows (health, armor-derived durability, weapons, speed, vision, cost, abilities), but as plain
serialisable data for the web UI.

Resolved at base state: no upgrades toggled, lowest experience rank. A horde's combat stats come
from its contained unit while its cost comes from the horde (mirroring `UnitPanel._init_sources`).
Every read is guarded — lazy field conversion can raise, and a missing stat just stays None.
"""

from __future__ import annotations

from sage_edain.model import Power, Profile, Weapon
from sage_edain.powers import resolve_power
from sage_ini.model.state import (
    UnitState,
    horde_member_object,
    select_command_set,
    select_weapon_set,
)
from sage_utils.views import (
    _safe,
    build_cost_view,
    command_buttons_view,
    effective_health,
    weapon_damage_per_shot,
    weapon_dps,
    weapon_top_nugget,
)


def _entry_weapon(entry):
    """The weapon object of a `(slot, weapon)` WeaponSet entry, or None."""
    return entry[1] if isinstance(entry, (tuple, list)) and len(entry) > 1 else None


def _primary_weapon(weapon_set):
    """The unit's main attack — the PRIMARY slot's weapon, else the first slot's. Other slots carry
    special-ability weapons (bombards, one-off salvos) that would read as extra attacks; those
    surface as abilities instead."""
    entries = _safe(lambda: weapon_set.Weapon, []) or []
    for entry in entries:
        slot = entry[0] if isinstance(entry, (tuple, list)) else None
        if getattr(slot, "name", "") == "PRIMARY" and _entry_weapon(entry) is not None:
            return _entry_weapon(entry)
    for entry in entries:
        if _entry_weapon(entry) is not None:
            return _entry_weapon(entry)
    return None


def _weapons(state, combat) -> list[Weapon]:
    """The unit's main attack as a single melee/ranged summary (empty when it has no damaging
    weapon). Only the primary weapon is shown — non-technical readers want "the attack", not the
    full multi-slot ability arsenal."""
    weapon_set = select_weapon_set(combat, state.weapon_flags)
    if weapon_set is None:
        return []
    weapon = _primary_weapon(weapon_set)
    if weapon is None:
        return []
    damage = weapon_damage_per_shot(weapon, state)
    if not damage:
        return []
    melee = bool(_safe(lambda: weapon.MeleeWeapon))
    _, damage_type = weapon_top_nugget(weapon, state)
    return [
        Weapon(
            kind="melee" if melee else "ranged",
            damage=damage,
            damage_type=damage_type,
            range=None if melee else _safe(lambda: float(weapon.AttackRange)),
            dps=weapon_dps(weapon, state),
        )
    ]


def _abilities(game, obj, faction_upgrades) -> list[Power]:
    """The object's special-power abilities (SPECIAL_POWER* / SPELL_BOOK buttons of its command
    set), each resolved to its created objects / transform / weapon / modifiers. De-duplicated."""
    command_set = select_command_set(obj, set(faction_upgrades))
    if command_set is None:
        return []
    abilities: list[Power] = []
    seen: set[str] = set()
    for view in command_buttons_view(game, command_set):
        command = view["command"]
        if not (command == "SPELL_BOOK" or (command and command.startswith("SPECIAL_POWER"))):
            continue
        power = view["special_power"]
        if not power or power in seen:
            continue
        seen.add(power)
        label = view["text"] or power
        tooltip = view["tooltip"] or ""
        abilities.append(resolve_power(game, obj, power, display=label, effect=tooltip))
    return abilities


def build_profile(game, obj, faction_upgrades=frozenset()) -> Profile:
    """The stat snapshot of `obj`. Combat stats are resolved from the contained unit for a horde
    (its experience levels fed in as rank targets), cost from `obj` itself."""
    member = horde_member_object(obj)
    combat = member if member is not None else obj
    state = UnitState(combat, rank_targets=(obj,) if member is not None else ())
    cost = build_cost_view(obj)
    # Effective HP per damage type, trimmed to the toughest and weakest few so the UI can say what
    # the object is strong / weak against without a wall of engine-internal types. Guarded: a
    # dangling armor reference makes `effective_health` raise, and a missing defense table just
    # leaves the object with no resilience line rather than sinking the whole walk.
    by_type = _safe(lambda: effective_health(state), {})
    ranked = sorted(by_type.items(), key=lambda item: item[1], reverse=True)
    defenses = ranked[:3] + ranked[-3:] if len(ranked) > 6 else ranked
    return Profile(
        health=_safe(lambda: state.max_health),
        speed=_safe(lambda: state.speed),
        vision=_safe(lambda: state.vision),
        build_cost=cost["BuildCost"],
        build_time=cost["BuildTime"],
        command_points=cost["CommandPoints"],
        weapons=_weapons(state, combat),
        defenses=[(damage_type, hp) for damage_type, hp in defenses],
        abilities=_abilities(game, obj, faction_upgrades),
    )
