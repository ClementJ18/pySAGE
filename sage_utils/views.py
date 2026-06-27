"""Pure (non-Qt) read helpers turning typed game objects into the dicts/values a UI
renders. Lazy conversion can raise, so every getter degrades to a default (`_safe`)
rather than abort the view.
"""

from collections import Counter
from typing import NamedTuple

from sage_ini.model.behaviors import (
    AutoDepositUpdate,
    CreateObjectDieBehavior,
    LifetimeUpdate,
    OCLSpecialPower,
    SlowDeathBehavior,
    SpecialPowerModule,
    TerrainResourceBehavior,
    ToggleMountedSpecialAbilityUpdate,
    WeaponFireSpecialAbilityUpdate,
)
from sage_ini.model.data_blocks import MappedImage
from sage_ini.model.game import Game
from sage_ini.model.nuggets import DamageNugget, DOTNugget, MetaImpactNugget, ProjectileNugget
from sage_ini.model.state import (
    command_set_names,
    find_upgrades,
    has_kindof,
    horde_member_object,
    modifier_entries,
)


def _safe(getter, default=None):
    try:
        return getter()
    except Exception:  # noqa: BLE001  (lazy conversion may raise; UI degrades gracefully)
        return default


def _upgrade_names(raw) -> list[str]:
    """Split a raw upgrade field (a name or whitespace-separated names) into names."""
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    names: list[str] = []
    for value in values:
        names.extend(str(value).split())
    return names


def _nugget_active(nug, active_upgrades) -> bool:
    """Whether a nugget fires under the active upgrades: all its `RequiredUpgradeNames`
    active and none of its `ForbiddenUpgradeNames`."""
    required = _upgrade_names(nug._fields.get("RequiredUpgradeNames"))
    if any(name not in active_upgrades for name in required):
        return False
    forbidden = _upgrade_names(nug._fields.get("ForbiddenUpgradeNames"))
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
    for nug in _safe(lambda w=weapon: w.Nuggets, []) or []:
        if not _nugget_active(nug, active_upgrades):
            continue
        if isinstance(nug, ProjectileNugget):
            warhead = _resolve_warhead(nug)
            if warhead is not None and warhead.name not in seen:
                seen.add(warhead.name)
                nuggets.extend(weapon_nuggets(warhead, active_upgrades, seen))
            continue
        damage_type = _safe(lambda n=nug: n.DamageType)
        nuggets.append(
            {
                "type": type(nug).__name__,
                "damage_type": getattr(damage_type, "name", None),
                "damage": _safe(lambda n=nug: n.Damage),
                "radius": _safe(lambda n=nug: n.Radius),
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
    for nug in _safe(lambda w=weapon: w.Nuggets, []) or []:
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
            base = _safe(lambda n=nug: n.Damage)
            if base is None:
                continue
            damage_type = getattr(_safe(lambda n=nug: n.DamageType), "name", None)
            dots.append(
                {
                    "damage": state.weapon_damage(base, damage_type),
                    "interval": _safe(lambda n=nug: n.DamageInterval),
                    "duration": _safe(lambda n=nug: n.DamageDuration),
                    "damage_type": damage_type,
                }
            )
        elif isinstance(nug, DamageNugget):
            base = _safe(lambda n=nug: n.Damage)
            if base is None:
                continue
            damage_type = getattr(_safe(lambda n=nug: n.DamageType), "name", None)
            scalars = [
                (scaled.Scalar, scaled.ObjectFilter)
                for scaled in _safe(lambda n=nug: n.DamageScalar, []) or []
            ]
            damage_nuggets.append(
                {
                    "damage": state.weapon_damage(base, damage_type),
                    "radius": _safe(lambda n=nug: n.Radius),
                    "damage_type": damage_type,
                    "scalars": scalars,
                }
            )
        elif isinstance(nug, MetaImpactNugget) and knockback is None:
            radius = _safe(lambda n=nug: n.ShockWaveRadius)
            if radius:
                knockback = {"radius": radius, "hero_resist": _safe(lambda n=nug: n.HeroResist)}
    return {"damage_nuggets": damage_nuggets, "dots": dots, "knockback": knockback}


class FilterSignature(NamedTuple):
    """A hashable, canonical reduction of an `ObjectFilter` — the join key between a parsed
    filter and a hand-labeled archetype registry (see `sage_wiki.archetypes`). `inclusion`
    and `exclusion` are the `+`/`-` object/kindof names; `descriptor` is ANY/ALL/NONE;
    `relations` are ENEMIES/ALLIES/… . Names, not objects, so two filters that mention the
    same flags compare equal regardless of how each token resolved."""

    descriptor: str | None
    relations: frozenset[str]
    inclusion: frozenset[str]
    exclusion: frozenset[str]


def _filter_member_name(member) -> str:
    """One filter member's name — a KindOf flag's name, an Object's name, or the raw token
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
    sets = []
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
        for nug in _safe(lambda w=weapon: w.Nuggets, []) or []:
            for field in ("RequiredUpgradeNames", "ForbiddenUpgradeNames"):
                names.extend(_upgrade_names(nug._fields.get(field)))
            if isinstance(nug, ProjectileNugget):
                visit(_resolve_warhead(nug))

    for weapon_set in _unit_weapon_sets(obj):
        for entry in _safe(lambda ws=weapon_set: ws.Weapon, []) or []:
            visit(entry[1])

    ordered, seen = [], set()
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def armorset_view(armor_set) -> dict:
    """Display data for one ArmorSet: its conditions, armor name and scalars."""
    armor = _safe(lambda: armor_set.Armor)
    return {
        "conditions": armor_set._fields.get("Conditions", "DEFAULT"),
        "armor": getattr(armor, "name", None),
        "scalars": _safe(lambda: armor.damage_scalars(), {}) if armor else {},
    }


def weapon_set_view(weapon_set, active_upgrades=frozenset()) -> list[dict]:
    """The (slot, weapon, melee, range, interval, nuggets) of each weapon in a WeaponSet.
    `interval` is the firing cycle in ms (see `weapon_attack_interval`)."""
    weapons = []
    for entry in _safe(lambda: weapon_set.Weapon, []) or []:
        slot, weapon = entry
        weapons.append(
            {
                "slot": getattr(slot, "name", str(slot)),
                "name": weapon.name,
                "melee": bool(_safe(lambda w=weapon: w.MeleeWeapon)),
                "range": _safe(lambda w=weapon: float(w.AttackRange)),
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
        number = _safe(lambda r=resolved: float(r))
        if number is not None:
            values.append(number)
    return max(values) if values else None


def weapon_attack_interval(weapon) -> float | None:
    """A weapon's full firing cycle in ms: `Weapon.AttackSpeed` (firing duration plus
    mean delay between shots), falling back to `ClipReloadTime` for a clip-reload
    weapon whose cycle is zero. None when neither resolves."""
    cycle = _safe(lambda: float(weapon.AttackSpeed))
    if not cycle:  # 0 or None — a clip-reload weapon times by its reload, not the cycle
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
    """Total modified damage of one shot — the sum of `weapon`'s active damage
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
    scalars = _safe(lambda: armor.damage_scalars(), {}) or {}
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
    scalars = _safe(lambda: armor.damage_scalars(), {}) or {}
    base = scalars.get(damage_type, scalars.get("DEFAULT", 1.0))
    coefficient = state.armor_scalar(damage_type, base)
    return health / coefficient if coefficient > 0 else None


def build_cost_view(obj) -> dict:
    """An object's economy stats — build cost, build time, command points, bounty
    (resources awarded to the killer). A `BUILD_FOR_FREE` object's build cost is always 0."""
    cost = 0 if has_kindof(obj, "BUILD_FOR_FREE") else _safe(lambda: obj.BuildCost)
    return {
        "BuildCost": cost,
        "BuildTime": _safe(lambda: obj.BuildTime),
        "CommandPoints": _safe(lambda: obj.CommandPoints),
        "BountyValue": _safe(lambda: obj.BountyValue),
    }


def _find_behavior(obj, behavior_type):
    """The first module of `behavior_type` on `obj` or a template it inherits from."""
    owner = obj
    while owner is not None:
        for module in getattr(owner, "modules", ()):
            if isinstance(module, behavior_type):
                return module
        owner = getattr(owner, "parent", None)
    return None


def resource_production_view(obj) -> dict:
    """A resource building's production from either money-over-time module:
    `TerrainResourceBehavior` (`MaxIncome` per `IncomeInterval`) or `AutoDepositUpdate`
    (`DepositAmount` per `DepositTiming`). Intervals are returned in whole seconds; each
    pair is None when the object carries no such module. Amounts are base values, scaled
    by the caller's active PRODUCTION modifier.
    """
    terrain = _find_behavior(obj, TerrainResourceBehavior)
    deposit = _find_behavior(obj, AutoDepositUpdate)
    income_ms = _safe(lambda: terrain.IncomeInterval) if terrain is not None else None
    timing_ms = _safe(lambda: deposit.DepositTiming) if deposit is not None else None
    return {
        "MaxIncome": _safe(lambda: terrain.MaxIncome) if terrain is not None else None,
        "IncomeInterval": None if income_ms is None else income_ms / 1000,
        "DepositAmount": _safe(lambda: deposit.DepositAmount) if deposit is not None else None,
        "DepositTiming": None if timing_ms is None else timing_ms / 1000,
    }


def _special_power_modules(obj, name) -> list:
    """Every behavior module on `obj` driven by the SpecialPower `name` (matched on its
    raw `SpecialPowerTemplate` token), in object order. A power is usually wired by
    several modules sharing the template — an enabler, a paused starter and the module
    carrying the effect — so the caller picks the one it renders."""
    modules = []
    owner = obj
    while owner is not None:
        for module in getattr(owner, "modules", ()):
            raw = module._fields.get("SpecialPowerTemplate")
            if raw is None:
                continue
            token = raw[-1] if isinstance(raw, list) else raw
            if str(token).split()[0] == name:
                modules.append(module)
        owner = getattr(owner, "parent", None)
    return modules


def _special_weapon_view(game, module) -> dict | None:
    """A WeaponFireSpecialAbilityUpdate's SpecialWeapon as a weapon-list entry, or None
    when it names none. Range/melee/nuggets are filled only when the `Weapon` block is
    loaded (it may live in another source)."""
    raw = module._fields.get("SpecialWeapon")
    name = raw[-1] if isinstance(raw, list) else raw
    if not name:
        return None
    name = str(name).split()[0]
    weapon = game.weapons.get(name)
    return {
        "name": name,
        "melee": bool(_safe(lambda: weapon.MeleeWeapon)) if weapon is not None else False,
        "range": _safe(lambda: float(weapon.AttackRange)) if weapon is not None else None,
        "nuggets": weapon_nuggets(weapon) if weapon is not None else [],
    }


def _ocl_created_names(ocl) -> list[str]:
    """The object names an ObjectCreationList places (across its CreateObject blocks),
    in first-seen order."""
    if ocl is None:
        return []
    names: list[str] = []
    for create in _safe(lambda: ocl.CreateObject, []) or []:
        for entry in _safe(lambda c=create: c.ObjectNames, []) or []:
            obj_name = getattr(entry, "name", None) or str(entry)
            if obj_name and obj_name not in names:
                names.append(obj_name)
    return names


def _all_modules(obj):
    """Every behavior module on `obj` and the templates it inherits from."""
    owner = obj
    while owner is not None:
        yield from getattr(owner, "modules", ())
        owner = getattr(owner, "parent", None)


def _hatch_ocls(obj) -> list:
    """The ObjectCreationLists `obj` spawns when it dies — a summon egg's hatch — from a
    CreateObjectDie's `CreationList` or a SlowDeathBehavior's `OCL` (grouped by death
    phase)."""
    ocls = []
    for module in _all_modules(obj):
        if isinstance(module, CreateObjectDieBehavior):
            ocl = _safe(lambda m=module: m.CreationList)
            if ocl is not None:
                ocls.append(ocl)
        elif isinstance(module, SlowDeathBehavior):
            grouped = _safe(lambda m=module: m.OCL, {}) or {}
            for bucket in grouped.values():
                ocls.extend(ocl for ocl in bucket if ocl is not None)
    return ocls


def _is_summon_egg(obj) -> bool:
    """Whether `obj` is a summon egg: a placeholder that auto-dies (a LifetimeUpdate)
    *and* hatches a payload from a death behavior. Both halves are required, to tell it
    apart from a real unit that merely drops debris on death."""
    has_lifetime = any(isinstance(m, LifetimeUpdate) for m in _all_modules(obj))
    return has_lifetime and bool(_hatch_ocls(obj))


# Eggs can chain (an egg hatches an egg), and CreateObjectDie cascades are common,
# so the walk is depth-capped and remembers the eggs it has already opened.
_MAX_SUMMON_DEPTH = 8


def _resolve_summons(game, names, *, _seen=None, _depth=0) -> list[dict]:
    """Expand summoned object names into a navigable chain, hatching any eggs. Each entry
    is `{"name", "summoned"}`: a summon egg's `summoned` holds the objects it hatches
    (resolved recursively); a real object's is empty."""
    seen = set() if _seen is None else _seen
    chain: list[dict] = []
    for name in names:
        node = {"name": name, "summoned": []}
        obj = game.objects.get(name)
        unopened_egg = (
            obj is not None
            and name not in seen
            and _depth < _MAX_SUMMON_DEPTH
            and _is_summon_egg(obj)
        )
        if unopened_egg:
            seen.add(name)
            hatched: list[str] = []
            for ocl in _hatch_ocls(obj):
                for hatched_name in _ocl_created_names(ocl):
                    if hatched_name not in hatched:
                        hatched.append(hatched_name)
            node["summoned"] = _resolve_summons(game, hatched, _seen=seen, _depth=_depth + 1)
        chain.append(node)
    return chain


def special_power_cooldown(game: Game, name: str) -> float | None:
    """A SpecialPower's recharge time in whole seconds (its `ReloadTime`, stored in
    milliseconds), or None when the power isn't loaded or declares no reload."""
    power = game.specialpowers.get(name)
    if power is None:
        return None
    reload_ms = _safe(lambda: power.ReloadTime)
    return None if reload_ms is None else reload_ms / 1000


def special_power_view(game: Game, obj, name: str) -> dict:
    """How a SPECIAL_POWER button's effect should render, resolved from the module on
    `obj` the named SpecialPower drives. `kind` selects the UI handling and the matching
    payload field is filled, the rest left empty:

    - "weapon" — a WeaponFireSpecialAbilityUpdate fires `weapon`.
    - "modifier" — a SpecialPowerModule applies `modifier` (an AttributeModifier).
    - "summon" — an OCLSpecialPower spawns the `summoned` chain.
    - "" — nothing resolvable; only `name` is known.

    `cooldown` is the recharge time in seconds, or None.
    """
    view = {
        "name": name,
        "kind": "",
        "weapon": None,
        "modifier": None,
        "summoned": [],
        "cooldown": special_power_cooldown(game, name),
    }
    modules = _special_power_modules(obj, name)
    # Prefer a concrete effect (a fired weapon or a summon) over a plain
    # attribute-modifier buff when several modules share the template.
    for module in modules:
        if isinstance(module, WeaponFireSpecialAbilityUpdate):
            weapon = _special_weapon_view(game, module)
            if weapon is not None:
                view["kind"] = "weapon"
                view["weapon"] = weapon
                return view
    for module in modules:
        if isinstance(module, OCLSpecialPower):
            view["kind"] = "summon"
            ocl = _safe(lambda m=module: m.OCL)
            view["summoned"] = _resolve_summons(game, _ocl_created_names(ocl))
            return view
    for module in modules:
        # Matched on the raw field so it classifies even when the ModifierList block
        # lives in another (unloaded) source; the resolved list may then be None.
        if isinstance(module, SpecialPowerModule):
            raw = module._fields.get("AttributeModifier")
            if raw is None:
                continue
            mod_name = str(raw[-1] if isinstance(raw, list) else raw).split()[0]
            view["kind"] = "modifier"
            view["modifier"] = game.modifiers.get(mod_name)
            return view
    return view


def modifier_view(modifier_list) -> dict:
    """A ModifierList's name and its per-stat (label, value) rows. Each `Modifier =` line
    becomes one row: the stat key (trailing qualifier tokens folded into the label)
    paired with the value, with `#define` macros resolved to their number."""
    if modifier_list is None:
        return {"name": None, "modifiers": []}
    game = getattr(modifier_list, "_game", None)
    rows: list[tuple[str, str]] = []
    for key, value, extra in modifier_entries(modifier_list):
        resolved = str(game.get_macro(value)) if game is not None else value
        label = f"{key} ({', '.join(extra)})" if extra else key
        rows.append((label, resolved))
    return {"name": getattr(modifier_list, "name", None), "modifiers": rows}


def _strings_ci(game) -> dict[str, str]:
    """A case-insensitive view of the string table, cached per game and rebuilt when its
    size changes. `.str` labels and the ini references that name them disagree on case,
    so a direct lookup misses; this keys every string by its lower-cased label."""
    cache = getattr(game, "_strings_ci_cache", None)
    if cache is None or cache[0] != len(game.strings):
        index = {key.lower(): value for key, value in game.strings.items()}
        cache = (len(game.strings), index)
        game._strings_ci_cache = cache
    return cache[1]


def clean_text(text: str | None) -> str | None:
    """Flatten a localized string's literal `\\n` line breaks into flowing prose: each
    becomes a space, with a period inserted when the preceding text ends in a letter or
    digit so stacked lines read as sentences. Text without `\\n` (and None) passes through."""
    if not text or "\\n" not in text:
        return text
    segments = [seg.strip() for seg in text.split("\\n")]
    segments = [seg for seg in segments if seg]
    for i, seg in enumerate(segments[:-1]):
        if seg[-1].isalnum():
            segments[i] = seg + "."
    return " ".join(segments)


def localize(game, label) -> str:
    """A string-table label resolved to its display text (the raw label if absent). Only
    the first of a toggle button's several labels is used; resolution falls back to a
    case-insensitive lookup. Returns raw text — a display caller flattens it via `clean_text`."""
    if isinstance(label, list):
        label = label[0] if label else None
    if not label:
        return ""
    first = str(label).split()[0]
    value = game.strings.get(first)
    if value is None:
        value = _strings_ci(game).get(first.lower())
    return first if value is None else value


def _resolve_label(game, label) -> str | None:
    """Like `localize`, but a label naming no loaded string yields None (not the raw
    label), so callers can fall back to a template name of their own."""
    if isinstance(label, list):
        label = label[0] if label else None
    if not label:
        return None
    first = str(label).split()[0]
    return game.strings.get(first) or _strings_ci(game).get(first.lower())


def display_name(game, obj) -> str | None:
    """An object's localized `DisplayName`, or None when it declares none or the label
    isn't in the string table."""
    return _resolve_label(game, _safe(lambda: obj.DisplayName))


def description(game, obj) -> str | None:
    """An object's localized `Description` (the flavour/help text shown in-game), falling
    back to its `RecruitText` when it declares no description. None when neither resolves to
    a loaded string."""
    return _resolve_label(game, _safe(lambda: obj.Description)) or _resolve_label(
        game, _safe(lambda: obj.RecruitText)
    )


def display_name_index(game, names) -> tuple[list[str], dict[str, str]]:
    """Returns `(display_names, index)`: a sorted list of the distinct display names and
    a case-insensitive dict from display name back to raw object name. Objects without a
    display name are skipped; when several share one, the first in `names` order wins."""
    index: dict[str, str] = {}
    labels: dict[str, str] = {}
    for name in names:
        obj = game.objects.get(name)
        shown = display_name(game, obj) if obj is not None else None
        if shown:
            key = shown.casefold()
            if key not in index:
                index[key] = name
                labels[key] = shown
    return sorted(labels.values()), index


def upgrade_label(game, name: str) -> str:
    """An upgrade's localized DisplayName, or its raw template name when it declares none or
    isn't loaded — the friendly label for an upgrade/ability toggle ("Fire Arrows", not
    `Upgrade_FireArrows`)."""
    upgrade = game.upgrades.get(name)
    if upgrade is None:
        return name
    return display_name(game, upgrade) or name


def upgrade_toggle_labels(game, names) -> dict[str, str]:
    """Map each upgrade name to its display label for a toggle list, keyed by the raw name the
    UI still drives the upgrade with. A label shared by more than one upgrade in `names` keeps
    the raw template name in parentheses ("Fire Arrows (Upgrade_FireArrows)") so the duplicates
    stay distinguishable; a name with no localized label is left as-is."""
    labels = {name: upgrade_label(game, name) for name in names}
    counts = Counter(labels.values())
    return {
        name: (f"{label} ({name})" if counts[label] > 1 and label != name else label)
        for name, label in labels.items()
    }


def mounted_template(obj) -> str | None:
    """The raw name of the object a unit's ToggleMountedSpecialAbilityUpdate mounts it
    into (its `MountedTemplate`), or None when there is no such module."""
    behavior = _find_behavior(obj, ToggleMountedSpecialAbilityUpdate)
    if behavior is None:
        return None
    return getattr(_safe(lambda: behavior.MountedTemplate), "name", None)


def _unit_build_targets(game, command_set) -> list[str]:
    """The object names the UNIT_BUILD buttons of `command_set` build, in slot order,
    de-duplicated. A lean read for the builder index; unloaded buttons are skipped."""
    buttons = game.commandbuttons
    targets: list[str] = []
    for slot, raw in command_set.fields.items():
        if not slot.isdigit():
            continue
        button_name = raw[-1] if isinstance(raw, list) else raw
        button = buttons.get(button_name)
        if button is None:
            continue
        if getattr(_safe(lambda b=button: b.Command), "name", None) != "UNIT_BUILD":
            continue
        obj_name = getattr(_safe(lambda b=button: b.Object), "name", None)
        if obj_name and obj_name not in targets:
            targets.append(obj_name)
    return targets


def builder_index(game) -> dict[str, list[str]]:
    """Map each buildable object's name to the objects that build it (the inverse of
    UNIT_BUILD navigation), in object-table order. An object builds another when one of
    its command sets has a UNIT_BUILD button naming it. Cached on the game by `builders_of`."""
    index: dict[str, list[str]] = {}
    commandsets = game.commandsets
    # Command sets are shared across many objects, so resolve each one's targets once.
    targets_cache: dict[str, list[str]] = {}

    def targets(set_name: str) -> list[str]:
        if set_name not in targets_cache:
            command_set = commandsets.get(set_name)
            targets_cache[set_name] = (
                _unit_build_targets(game, command_set) if command_set is not None else []
            )
        return targets_cache[set_name]

    for builder in game.objects.values():
        for set_name in command_set_names(builder):
            for built_name in targets(set_name):
                builders = index.setdefault(built_name, [])
                if builder.name not in builders:
                    builders.append(builder.name)
    return index


def builders_of(game, name: str) -> list[str]:
    """The objects that build `name`, from the `builder_index` cached on the game (a
    fresh Game per load, so it never goes stale)."""
    index = getattr(game, "_builder_index", None)
    if index is None:
        index = builder_index(game)
        game._builder_index = index
    return index.get(name, [])


# Non-hero entries that appear in the buildable-hero lists: the Create-A-Hero
# customizer and the ring-hero slot placeholder, neither a real fielded hero.
_HERO_PLACEHOLDERS = frozenset({"CreateAHero", "RingHeroDummy"})


def playable_factions(game) -> list[dict]:
    """Playable factions (a `PlayerTemplate` with `PlayableSide = Yes`) in faction-table
    order, for the Faction Info panel. Each entry carries:

    - `name` / `display` — the raw template name and its localized DisplayName.
    - `heroes` — buildable heroes (`BuildableHeroesMP` then `BuildableRingHeroesMP`),
      de-duplicated, with the `CreateAHero`/`RingHeroDummy` placeholders dropped.
    - `spellbook` — the faction-specific `SpellBookMp`, else the shared `SpellBook`, or None.
    """
    factions = []
    for faction in game.factions.values():
        if not _safe(lambda f=faction: f.PlayableSide):
            continue
        heroes: list[str] = []
        for field in ("BuildableHeroesMP", "BuildableRingHeroesMP"):
            for hero in _upgrade_names(faction._fields.get(field)):
                if hero not in _HERO_PLACEHOLDERS and hero not in heroes:
                    heroes.append(hero)
        raw = faction._fields.get("SpellBookMp") or faction._fields.get("SpellBook")
        spellbook = None
        if raw is not None:
            spellbook = str(raw[-1] if isinstance(raw, list) else raw).split()[0]
        factions.append(
            {
                "name": faction.name,
                "display": display_name(game, faction) or faction.name,
                "heroes": heroes,
                "spellbook": spellbook,
            }
        )
    return factions


def _button_upgrade_view(game, button) -> dict | None:
    """The Upgrade an OBJECT_UPGRADE/PLAYER_UPGRADE button grants — its localized name,
    cost and time — or None when the button names no resolvable upgrade."""
    upgrade = _safe(lambda: button.Upgrade)
    if upgrade is None:
        return None
    return {
        "name": display_name(game, upgrade) or upgrade.name,
        "cost": _safe(lambda: upgrade.BuildCost),
        "time": _safe(lambda: upgrade.BuildTime),
    }


def command_button_view(game, name, button) -> dict:
    """One CommandButton as a render-ready dict. Always carries the slot `name`, localized
    `text`/`tooltip` and the `command` action name (None when unloaded). The rest are
    filled only for the action the UI acts on, else None:

    - `upgrade` — {name, cost, time} for OBJECT_UPGRADE / PLAYER_UPGRADE.
    - `object` — the object a UNIT_BUILD button builds.
    - `special_power` — the SpecialPower of a SPECIAL_POWER* or SPELL_BOOK button.
    - `weapon_slot` — the SlotTypes name a FIRE_WEAPON button fires.
    - `toggle_flags` — the WeaponSet flags a TOGGLE_WEAPONSET button flips.
    - `button_image` — the button's `ButtonImage` as a croppable `MappedImage` list.
    """
    text = localize(game, _safe(lambda: button.TextLabel)) if button else ""
    tooltip = localize(game, _safe(lambda: button.DescriptLabel)) if button else ""
    command = getattr(_safe(lambda: button.Command), "name", None) if button else None
    view = {
        "name": name,
        "text": text or name,
        "tooltip": tooltip,
        "command": command,
        "upgrade": None,
        "object": None,
        "special_power": None,
        "weapon_slot": None,
        "toggle_flags": [],
        "button_image": _mapped_images(_safe(lambda: button.ButtonImage)) if button else [],
    }
    if button is None:
        return view
    if command in ("OBJECT_UPGRADE", "PLAYER_UPGRADE"):
        view["upgrade"] = _button_upgrade_view(game, button)
    elif command == "UNIT_BUILD":
        view["object"] = getattr(_safe(lambda: button.Object), "name", None)
    elif command and (command.startswith("SPECIAL_POWER") or command == "SPELL_BOOK"):
        view["special_power"] = getattr(_safe(lambda: button.SpecialPower), "name", None)
    elif command == "FIRE_WEAPON":
        view["weapon_slot"] = getattr(_safe(lambda: button.WeaponSlot), "name", None)
    elif command == "TOGGLE_WEAPONSET":
        raw = button._fields.get("FlagsUsedForToggle")
        view["toggle_flags"] = [token.upper() for token in _upgrade_names(raw)]
    return view


def _command_set_slots(command_set) -> list[tuple[int, str]]:
    """A CommandSet's `(slot index, button name)` pairs, in slot order. Only numbered
    fields are slots; one listing several values keeps the last (the engine's override)."""
    slots = []
    for slot, name in command_set.fields.items():
        if slot.isdigit():
            slots.append((int(slot), name[-1] if isinstance(name, list) else name))
    return sorted(slots)


def command_buttons_view(game, command_set) -> list[dict]:
    """Each filled slot of a CommandSet as a `command_button_view` dict, in slot order. A
    slot whose button isn't loaded falls back to the raw name so nothing is dropped."""
    table = game.commandbuttons
    return [
        command_button_view(game, name, table.get(name))
        for _slot, name in _command_set_slots(command_set)
    ]


def _mapped_images(value) -> list:
    """The croppable `MappedImage` definitions in a resolved `Image` field value, always
    as a list. Unresolved names (raw strings) and a missing field yield nothing."""
    values = value if isinstance(value, list) else [value]
    return [item for item in values if isinstance(item, MappedImage)]


def _image_names(value) -> list[str]:
    """The image names in a resolved `Image` field value, resolved or not: a loaded
    `MappedImage`'s `name`, else the raw token. Keeps the icon's real `ButtonImage` name
    even when its definition wasn't loaded. Always a list, mirroring `_mapped_images`."""
    values = value if isinstance(value, list) else [value]
    names = []
    for item in values:
        if isinstance(item, MappedImage):
            names.append(item.name)
        elif item:
            names.append(str(item).split()[0])
    return names


def select_portrait_image(obj) -> list:
    """The object's `SelectPortrait` as a list of croppable `MappedImage`s (empty when
    unset/unresolved), resolved like a button's `ButtonImage`."""
    return _mapped_images(_safe(lambda: obj.SelectPortrait))


def object_button_image(obj) -> list:
    """The object's own `ButtonImage` (the icon shown for it, e.g. in a build menu) as a
    list of croppable `MappedImage`s; empty when unset/unresolved."""
    return _mapped_images(_safe(lambda: obj.ButtonImage))


def portrait_mapped_images(obj) -> list:
    """The object's portrait `MappedImage`s, tried in order: its own `SelectPortrait`, a horde
    member's `SelectPortrait`, then either's `ButtonImage` (the next-best icon for
    structures/summons). A horde may carry the portrait on its shell or only on the contained
    unit — some define it on one, some on the other — so both are consulted. Empty when none
    resolves."""
    member = horde_member_object(obj)
    sources = [obj] if member is None else [obj, member]
    for resolve in (select_portrait_image, object_button_image):
        for source in sources:
            images = resolve(source)
            if images:
                return images
    return []


def command_button_images(game, command_set) -> list[dict]:
    """Each button of a CommandSet paired with its `ButtonImage`(s), in slot order, for
    the extract-image tool. Every slot yields `{name, text, image, image_names}`: `image`
    is the resolved `MappedImage` list (empty when unloaded/unresolved) and `image_names`
    the button's image name(s) resolved or not."""
    table = game.commandbuttons
    entries = []
    for _slot, name in _command_set_slots(command_set):
        button = table.get(name)
        image = _safe(lambda b=button: b.ButtonImage) if button is not None else None
        text = localize(game, _safe(lambda b=button: b.TextLabel)) if button is not None else ""
        entries.append(
            {
                "name": name,
                "text": text or name,
                "image": _mapped_images(image),
                "image_names": _image_names(image),
            }
        )
    return entries


def flatten_button_images(entries) -> list[dict]:
    """One selectable row per croppable image across button-image `entries`. A button's
    several layered images each become a row, the index suffixed onto `name`/`text` only
    when there is more than one. A button with no resolved image becomes a single row with
    `image` None, named after its `ButtonImage` if it has one, else the button itself. Each
    row keeps its originating `button` (the command button's name) so callers can look the
    button back up (e.g. to scaffold its ability template)."""
    rows: list[dict] = []
    for entry in entries:
        button = entry["name"]
        images = entry["image"]
        if not images:
            image_names = entry.get("image_names") or []
            name = image_names[0] if image_names else entry["name"]
            rows.append({"name": name, "text": entry["text"], "image": None, "button": button})
            continue
        multiple = len(images) > 1
        for index, image in enumerate(images, 1):
            rows.append(
                {
                    "name": f"{entry['name']}_{index}" if multiple else entry["name"],
                    "text": f"{entry['text']} ({index})" if multiple else entry["text"],
                    "image": image,
                    "button": button,
                }
            )
    return rows


def object_detail(obj) -> dict:
    # Only identity and the upgrade list are precomputed; stats are resolved live from
    # the UnitState since they depend on active upgrades. The upgrade list also includes
    # the upgrades that gate weapon nuggets, merged after the object's own triggers.
    upgrades = find_upgrades(obj)
    seen = set(upgrades)
    for name in weapon_upgrade_triggers(obj):
        if name not in seen:
            seen.add(name)
            upgrades.append(name)
    return {
        "name": obj.name,
        "type": type(obj).__name__,
        "upgrades": upgrades,
    }


def percent(value) -> str:
    """A damage scalar as a rounded percentage: 1.0 -> '100%', 1.254 -> '125%'."""
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt(value) -> str:
    """A numeric stat rounded to a whole number for display, or an em dash when absent."""
    return "—" if value is None else str(round(float(value)))
