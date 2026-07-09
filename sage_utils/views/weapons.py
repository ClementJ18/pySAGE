"""Weapon, armor and damage views: per-nugget breakdowns (warheads descended into),
attack cadence, per-shot damage / DPS, and effective health against each damage type."""

from typing import NamedTuple

from sage_ini.model.nuggets import DamageNugget, DOTNugget, MetaImpactNugget, ProjectileNugget
from sage_utils.views.base import safe, upgrade_names


def _nugget_active(nug, active_upgrades) -> bool:
    """Whether a nugget fires under the active upgrades: all its `RequiredUpgradeNames`
    active and none of its `ForbiddenUpgradeNames`."""
    required = upgrade_names(nug._fields.get("RequiredUpgradeNames"))
    if any(name not in active_upgrades for name in required):
        return False
    forbidden = upgrade_names(nug._fields.get("ForbiddenUpgradeNames"))
    return not any(name in active_upgrades for name in forbidden)


def _resolve_warhead(nug):
    """The warhead `Weapon` a ProjectileNugget launches (where its damage lives)."""
    raw = nug._fields.get("WarheadTemplateName")
    name = raw[-1] if isinstance(raw, list) else raw
    game = getattr(nug, "_game", None)
    if not name or game is None:
        return None
    return game.weapons.get(str(name).split()[0])


def weapon_nuggets(weapon, active_upgrades=frozenset(), _seen=None) -> list[dict]:
    """Per-nugget damage view, filtered to active nuggets. A ProjectileNugget
    contributes its warhead weapon's nuggets (the real damage) instead of itself,
    recursing with a guard against cycles."""
    seen = set() if _seen is None else _seen
    nuggets = []
    for nug in safe(lambda w=weapon: w.Nuggets, []) or []:
        if not _nugget_active(nug, active_upgrades):
            continue
        if isinstance(nug, ProjectileNugget):
            warhead = _resolve_warhead(nug)
            if warhead is not None and warhead.name not in seen:
                seen.add(warhead.name)
                nuggets.extend(weapon_nuggets(warhead, active_upgrades, seen))
            continue
        damage_type = safe(lambda n=nug: n.DamageType)
        nuggets.append(
            {
                "type": type(nug).__name__,
                "damage_type": getattr(damage_type, "name", None),
                "damage": safe(lambda n=nug: n.Damage),
                "radius": safe(lambda n=nug: n.Radius),
            }
        )
    return nuggets


def weapon_damage_breakdown(weapon, state, _seen=None) -> dict:
    """Per-nugget detail for a weapon summary (sage_wiki.weapons). Returns
    `{"damage_nuggets": [...], "dots": [...], "knockback": {...} | None}`: each active
    DamageNugget's modified `damage` (under `state`), `radius`, `damage_type` and its `scalars`
    as `(multiplier, object_filter)` pairs; each DOTNugget's modified `damage`, `interval` and
    `duration` (ms) and `damage_type`; `knockback` is the first MetaImpactNugget's `radius` +
    `hero_resist`. ProjectileNugget warheads are descended into, like `weapon_nuggets`, with a
    cycle guard."""
    seen = set() if _seen is None else _seen
    damage_nuggets: list[dict] = []
    dots: list[dict] = []
    knockback: dict | None = None
    for nug in safe(lambda w=weapon: w.Nuggets, []) or []:
        if not _nugget_active(nug, state.effective_upgrades):
            continue
        if isinstance(nug, ProjectileNugget):
            warhead = _resolve_warhead(nug)
            if warhead is not None and warhead.name not in seen:
                seen.add(warhead.name)
                sub = weapon_damage_breakdown(warhead, state, seen)
                damage_nuggets.extend(sub["damage_nuggets"])
                dots.extend(sub["dots"])
                knockback = knockback or sub["knockback"]
        elif isinstance(nug, DOTNugget):
            # DOTNugget subclasses DamageNugget, so it must be matched first.
            base = safe(lambda n=nug: n.Damage)
            if base is None:
                continue
            damage_type = getattr(safe(lambda n=nug: n.DamageType), "name", None)
            dots.append(
                {
                    "damage": state.weapon_damage(base, damage_type),
                    "interval": safe(lambda n=nug: n.DamageInterval),
                    "duration": safe(lambda n=nug: n.DamageDuration),
                    "damage_type": damage_type,
                }
            )
        elif isinstance(nug, DamageNugget):
            base = safe(lambda n=nug: n.Damage)
            if base is None:
                continue
            damage_type = getattr(safe(lambda n=nug: n.DamageType), "name", None)
            scalars = [
                (scaled.Scalar, scaled.ObjectFilter)
                for scaled in safe(lambda n=nug: n.DamageScalar, []) or []
            ]
            damage_nuggets.append(
                {
                    "damage": state.weapon_damage(base, damage_type),
                    "radius": safe(lambda n=nug: n.Radius),
                    "damage_type": damage_type,
                    "scalars": scalars,
                }
            )
        elif isinstance(nug, MetaImpactNugget) and knockback is None:
            radius = safe(lambda n=nug: n.ShockWaveRadius)
            if radius:
                knockback = {"radius": radius, "hero_resist": safe(lambda n=nug: n.HeroResist)}
    return {"damage_nuggets": damage_nuggets, "dots": dots, "knockback": knockback}


class FilterSignature(NamedTuple):
    """A hashable, canonical reduction of an `ObjectFilter` - the join key between a parsed
    filter and a hand-labeled archetype registry (see `sage_wiki.archetypes`). `inclusion`
    and `exclusion` are the `+`/`-` object/kindof names; `descriptor` is ANY/ALL/NONE;
    `relations` are ENEMIES/ALLIES/… . Names, not objects, so two filters that mention the
    same flags compare equal regardless of how each token resolved."""

    descriptor: str | None
    relations: frozenset[str]
    inclusion: frozenset[str]
    exclusion: frozenset[str]


def _filter_member_name(member) -> str:
    """One filter member's name - a KindOf flag's name, an Object's name, or the raw token
    when it never resolved to either."""
    return getattr(member, "name", None) or str(member)


def filter_signature(object_filter) -> FilterSignature | None:
    """`object_filter` reduced to a `FilterSignature`, or None when there is no filter (a
    bare `DamageScalar` multiplier with no scope), which means "everything"."""
    if object_filter is None:
        return None
    return FilterSignature(
        descriptor=getattr(object_filter.descriptor, "name", None),
        relations=frozenset(_filter_member_name(r) for r in object_filter.relations),
        inclusion=frozenset(_filter_member_name(m) for m in object_filter.inclusion),
        exclusion=frozenset(_filter_member_name(m) for m in object_filter.exclusion),
    )


def _unit_weapon_sets(obj) -> list:
    """Every WeaponSet on the object and its parent chain (own first)."""
    sets: list = []
    owner = obj
    while owner is not None:
        sets.extend(getattr(owner, "WeaponSet", None) or [])
        owner = getattr(owner, "parent", None)
    return sets


def weapon_upgrade_triggers(obj) -> list[str]:
    """Upgrade names that gate this unit's weapon nuggets (warheads included), so they
    become toggles in the panel. De-duplicated in first-seen order."""
    names: list[str] = []
    seen_weapons: set[str] = set()

    def visit(weapon) -> None:
        if weapon is None or weapon.name in seen_weapons:
            return
        seen_weapons.add(weapon.name)
        for nug in safe(lambda w=weapon: w.Nuggets, []) or []:
            for field in ("RequiredUpgradeNames", "ForbiddenUpgradeNames"):
                names.extend(upgrade_names(nug._fields.get(field)))
            if isinstance(nug, ProjectileNugget):
                visit(_resolve_warhead(nug))

    for weapon_set in _unit_weapon_sets(obj):
        for entry in safe(lambda ws=weapon_set: ws.Weapon, []) or []:
            visit(entry[1])

    ordered, seen = [], set()
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def armorset_view(armor_set) -> dict:
    """Display data for one ArmorSet: its conditions, armor name and scalars."""
    armor = safe(lambda: armor_set.Armor)
    return {
        "conditions": armor_set._fields.get("Conditions", "DEFAULT"),
        "armor": getattr(armor, "name", None),
        "scalars": safe(lambda: armor.damage_scalars(), {}) if armor else {},
    }


def weapon_set_view(weapon_set, active_upgrades=frozenset()) -> list[dict]:
    """The (slot, weapon, melee, range, interval, nuggets) of each weapon in a WeaponSet.
    `interval` is the firing cycle in ms (see `weapon_attack_interval`)."""
    weapons = []
    for entry in safe(lambda: weapon_set.Weapon, []) or []:
        slot, weapon = entry
        weapons.append(
            {
                "slot": getattr(slot, "name", str(slot)),
                "name": weapon.name,
                "melee": bool(safe(lambda w=weapon: w.MeleeWeapon)),
                "range": safe(lambda w=weapon: float(w.AttackRange)),
                "interval": weapon_attack_interval(weapon),
                "nuggets": weapon_nuggets(weapon, active_upgrades),
            }
        )
    return weapons


def clip_reload_time(weapon) -> float | None:
    """A clip-reloading weapon's reload time in ms (the Max of a `Min:/Max:` form).

    Archers fire a one-shot clip then reload, so their cadence is `ClipReloadTime`,
    not `DelayBetweenShots` + `FiringDuration` (0 for them). The untyped field may be
    a bare number, a macro name, or a `Min:1500 Max:2000` pair.
    """
    raw = weapon._fields.get("ClipReloadTime")
    if raw is None:
        return None
    game = getattr(weapon, "_game", None)
    tokens = raw if isinstance(raw, list) else str(raw).split()
    values = []
    for token in tokens:
        text = str(token).split(":", 1)[1] if ":" in str(token) else str(token)
        resolved = game.get_macro(text) if game is not None else text
        number = safe(lambda r=resolved: float(r))
        if number is not None:
            values.append(number)
    return max(values) if values else None


def weapon_attack_interval(weapon) -> float | None:
    """A weapon's full firing cycle in ms: `Weapon.AttackSpeed` (firing duration plus
    mean delay between shots), falling back to `ClipReloadTime` for a clip-reload
    weapon whose cycle is zero. None when neither resolves."""
    cycle = safe(lambda: float(weapon.AttackSpeed))
    if not cycle:  # 0 or None - a clip-reload weapon times by its reload, not the cycle
        cycle = clip_reload_time(weapon)
    return cycle or None


def weapon_top_nugget(weapon, state):
    """The `(damage, damage_type)` of `weapon`'s hardest-hitting nugget (warheads
    descended into, damage modified by `state`), or `(None, None)`."""
    best, best_type = None, None
    for nugget in weapon_nuggets(weapon, state.effective_upgrades):
        base = nugget["damage"]
        if base is None:
            continue
        damage = state.weapon_damage(base, nugget["damage_type"])
        if best is None or damage > best:
            best, best_type = damage, nugget["damage_type"]
    return best, best_type


def weapon_radius(weapon, state):
    """The blast radius of `weapon`'s hardest-hitting nugget (the one `weapon_top_nugget`
    reports), or None for a single-target weapon or one with no damage nugget."""
    best, best_radius = None, None
    for nugget in weapon_nuggets(weapon, state.effective_upgrades):
        base = nugget["damage"]
        if base is None:
            continue
        damage = state.weapon_damage(base, nugget["damage_type"])
        if best is None or damage > best:
            best, best_radius = damage, nugget["radius"]
    return best_radius or None


def weapon_damage_per_shot(weapon, state) -> float | None:
    """Total modified damage of one shot - the sum of `weapon`'s active damage
    nuggets (warheads descended into), or None when it deals no nugget damage."""
    total, found = 0.0, False
    for nugget in weapon_nuggets(weapon, state.effective_upgrades):
        base = nugget["damage"]
        if base is None:
            continue
        total += state.weapon_damage(base, nugget["damage_type"])
        found = True
    return total if found else None


def weapon_dps(weapon, state) -> float | None:
    """Sustained DPS: per-shot damage divided by the firing cycle in seconds. None when
    the weapon deals no damage or has no resolvable cadence."""
    per_shot = weapon_damage_per_shot(weapon, state)
    interval_ms = weapon_attack_interval(weapon)
    if per_shot is None or not interval_ms:
        return None
    return per_shot / (interval_ms / 1000)


def effective_health(state) -> dict[str, float]:
    """Effective hit points against each of the active armor's damage types.

    An armor coefficient is the fraction of a hit that gets through, so the unit
    survives `max_health / coefficient` damage of that type. Keyed by the armor's
    damage types; empty when the unit has no health/armor. A 0% (immune) coefficient
    is skipped, since its effective health is unbounded.
    """
    health = state.max_health
    armor = state.armor
    if health is None or armor is None:
        return {}
    scalars = safe(lambda: armor.damage_scalars(), {}) or {}
    effective = {}
    for damage_type, base in scalars.items():
        coefficient = state.armor_scalar(damage_type, base)
        if coefficient > 0:
            effective[damage_type] = health / coefficient
    return effective


def effective_health_against(state, damage_type) -> float | None:
    """The unit's effective hit points against one `damage_type` (the armor's DEFAULT
    when the type isn't listed; `max_health` when it has no armor). None when the unit
    has no health or is immune (a 0% coefficient)."""
    health = state.max_health
    if health is None:
        return None
    armor = state.armor
    if armor is None:
        return health
    scalars = safe(lambda: armor.damage_scalars(), {}) or {}
    base = scalars.get(damage_type, scalars.get("DEFAULT", 1.0))
    coefficient = state.armor_scalar(damage_type, base)
    return health / coefficient if coefficient > 0 else None
