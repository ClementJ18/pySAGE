"""Computing infobox parameter values from a parsed game object.

`FIELD_MAP` ties each infobox parameter to a function over a `FieldContext`. Stats are
resolved at the object's base state (no upgrades, lowest rank) through the same typed
layer the browser uses. As the browser does, a horde's combat stats come from its
contained unit while cost/movement stay the horde's; a build shell with no Body of its
own is read from its first build variation.

A leveled building's stats are emitted per level as indexed columns (`health1`, …), each
read under that level's cumulative economy upgrades. Only fields sage_ini computes cleanly
are mapped; the infobox's manual fields are never written.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sage_ini.model.behaviors import (
    GiantBirdAIUpdate,
    LifetimeUpdate,
    ToggleMountedSpecialAbilityUpdate,
)
from sage_ini.model.state import (
    RankSelector,
    UnitState,
    build_variations,
    economy_level_upgrades,
    find_body,
    has_kindof,
    horde_member_object,
    select_armor_set,
    select_locomotor_set,
    select_weapon_set,
)
from sage_utils.views import (
    armorset_view,
    build_cost_view,
    find_behavior,
    resource_production_view,
    safe,
    weapon_attack_interval,
    weapon_radius,
    weapon_top_nugget,
)
from sage_wiki.weapons import weapon_summary_lines


@dataclass
class FieldContext:
    """What every field function needs. `obj` is the page's subject; `unit` is where its
    combat stats come from (the contained member for a horde, else `obj`). `unit_state`
    resolves combat stats on `unit`, `source_state` cost/movement on `obj`."""

    obj: object
    unit: object
    unit_state: UnitState
    source_state: UnitState


def _combat_unit(obj):
    """The object the combat/health/resource stats are read from: a horde's first contained
    member, a build shell's first build variation, else `obj` itself."""
    member = horde_member_object(obj)
    if member is not None:
        return member
    game = getattr(obj, "_game", None)
    if game is None:
        return obj
    if find_body(obj) is None:
        for name in build_variations(obj):
            variation = game.objects.get(name)
            if variation is not None and find_body(variation) is not None:
                return variation
    return obj


def _fmt_number(value) -> str | None:
    """A stat rounded to a whole number for wikitext, None when absent."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(round(number))


def _weapon_top_damage(weapon, state: UnitState):
    """The hardest-hitting nugget's modified damage (warheads descended into)."""
    return weapon_top_nugget(weapon, state)[0]


def _weapon_damage_summary(weapon, state: UnitState) -> str | None:
    """A weapon's per-archetype damage summary (see `sage_wiki.weapons`) for the infobox's
    `damage` cell - newline-joined so the modifier `*` bullets render as a wiki list. None
    when the weapon is absent or deals no nugget damage."""
    if weapon is None:
        return None
    lines = weapon_summary_lines(weapon, state)
    return "\n".join(lines) if lines else None


def _primary_of(weapon_set):
    """A weapon set's basic auto-attack weapon - its PRIMARY slot, else its first. Skips
    special-ability weapons in other slots, which would inflate the listed damage/range."""
    if weapon_set is None:
        return None
    weapons = safe(lambda: weapon_set.Weapon, []) or []
    for slot, weapon in weapons:
        if getattr(slot, "name", str(slot)) == "PRIMARY":
            return weapon
    return weapons[0][1] if weapons else None


def _primary_weapon(state: UnitState):
    """The unit's basic auto-attack weapon in its active weapon set."""
    return _primary_of(state.weapon_set)


def _named_weapon(unit, field: str):
    """Resolve an untyped weapon-name field (e.g. ``CrushWeapon``) to a Weapon."""
    raw = unit._fields.get(field)
    name = raw[-1] if isinstance(raw, list) else raw
    game = getattr(unit, "_game", None)
    if not name or game is None:
        return None
    return game.weapons.get(str(name).split()[0])


def _health(c: FieldContext) -> str | None:
    return _fmt_number(c.unit_state.max_health)


def _armor(c: FieldContext) -> str | None:
    """The active armor template's name, lower-cased to match the infobox convention."""
    armor_set = c.unit_state.armor_set
    if armor_set is None:
        return None
    name = armorset_view(armor_set)["armor"]
    return name.lower() if name is not None else None


def _damage(c: FieldContext) -> str | None:
    """The unit's basic (PRIMARY) attack as a per-archetype damage summary (the old single
    number is subsumed - the summary's first line carries it)."""
    return _weapon_damage_summary(_primary_weapon(c.unit_state), c.unit_state)


def _damage_type(c: FieldContext) -> str | None:
    """The damage type of the unit's basic attack (e.g. ``PIERCE``)."""
    weapon = _primary_weapon(c.unit_state)
    if weapon is None:
        return None
    damage_type = weapon_top_nugget(weapon, c.unit_state)[1]
    return str(damage_type) if damage_type else None


def _revenge_damage(c: FieldContext) -> str | None:
    """The damage of the unit's crush-revenge weapon (fired when overrun)."""
    weapon = _named_weapon(c.unit, "CrushRevengeWeapon")
    return _fmt_number(_weapon_top_damage(weapon, c.unit_state)) if weapon is not None else None


def _trample_damage(c: FieldContext) -> str | None:
    """The damage of the unit's crush weapon (dealt when it tramples)."""
    weapon = _named_weapon(c.unit, "CrushWeapon")
    return _fmt_number(_weapon_top_damage(weapon, c.unit_state)) if weapon is not None else None


def _attack_speed(c: FieldContext) -> str | None:
    """The basic (PRIMARY) weapon's full attack cycle in milliseconds (see
    `weapon_attack_interval`), e.g. `1500 ms`."""
    weapon = _primary_weapon(c.unit_state)
    if weapon is None:
        return None
    cycle = weapon_attack_interval(weapon)
    return f"{int(cycle)} ms" if cycle else None


def _range(c: FieldContext) -> str | None:
    """The reach of the unit's basic (PRIMARY) attack."""
    weapon = _primary_weapon(c.unit_state)
    reach = safe(lambda: float(weapon.AttackRange)) if weapon is not None else None
    return _fmt_number(reach)


def _radius(c: FieldContext) -> str | None:
    """The blast radius of the unit's basic (PRIMARY) attack, None when single-target."""
    weapon = _primary_weapon(c.unit_state)
    if weapon is None:
        return None
    return _fmt_number(weapon_radius(weapon, c.unit_state))


def _speed(c: FieldContext) -> str | None:
    """The movement speed of the page's object (a horde's own group locomotor, a lone
    unit's own)."""
    locomotor_set = c.source_state.locomotor_set
    if locomotor_set is None:
        return None
    return _fmt_number(safe(lambda: float(locomotor_set.Speed)))


def _resources(c: FieldContext) -> str | None:
    """A resource building's income per pulse with the active PRODUCTION bonuses (so
    reading it under a level's upgrades is what makes higher levels produce more). None
    for a non-producer."""
    income = resource_production_view(c.unit)["MaxIncome"]
    if income is None:
        return None
    return _fmt_number(income * c.unit_state.production_multiplier)


def _interval(c: FieldContext) -> str | None:
    """The time between a resource building's production pulses, e.g. `12 seconds`."""
    seconds = _fmt_number(resource_production_view(c.unit)["IncomeInterval"])
    return f"{seconds} seconds" if seconds is not None else None


# The engine's weapon-set toggle conditions; a two-stance unit conditions its alternate
# WeaponSet on one of these, flipped by a TOGGLE_WEAPONSET button or a stance special power.
WEAPONSET_TOGGLE_CONDITIONS = ("WEAPONSET_TOGGLE_1", "WEAPONSET_TOGGLE_2", "WEAPONSET_TOGGLE_3")


def _weapon_toggle_flag(unit, state: UnitState) -> str | None:
    """The WeaponSet condition that selects the unit's alternate attack stance, or None.
    Detected from the data - the lowest `WEAPONSET_TOGGLE_*` whose set differs from the
    default - rather than a command button, since a special power may wire the switch."""
    base = state.weapon_flags
    base_set = select_weapon_set(unit, base)
    for flag in WEAPONSET_TOGGLE_CONDITIONS:
        toggled = select_weapon_set(unit, base | {flag})
        if toggled is not None and toggled is not base_set:
            return flag
    return None


def _melee_ranged_weapons(unit, state: UnitState, toggle_flag: str):
    """The unit's (melee, ranged) primary weapons across the weapon-set toggle: each set's
    PRIMARY weapon, the longer-ranged of the two being the ranged stance. Either may be None."""
    base = state.weapon_flags
    untoggled = _primary_of(select_weapon_set(unit, base))
    toggled = _primary_of(select_weapon_set(unit, base | {toggle_flag}))
    weapons = [w for w in (untoggled, toggled) if w is not None]
    if not weapons:
        return None, None
    weapons.sort(key=lambda w: safe(lambda w=w: float(w.AttackRange)) or 0.0)
    return weapons[0], weapons[-1]


def _weapon_stats(weapon, state: UnitState) -> dict[str, str | None]:
    """One weapon's damage, damage type, range, radius and attack speed (resolved under
    `state`); an absent weapon yields all-None."""
    if weapon is None:
        return {
            "damage": None,
            "damage_type": None,
            "range": None,
            "radius": None,
            "attack_speed": None,
        }
    _, damage_type = weapon_top_nugget(weapon, state)
    cycle = weapon_attack_interval(weapon)
    return {
        "damage": _weapon_damage_summary(weapon, state),
        "damage_type": str(damage_type) if damage_type else None,
        "range": _fmt_number(safe(lambda: float(weapon.AttackRange))),
        "radius": _fmt_number(weapon_radius(weapon, state)),
        "attack_speed": f"{int(cycle)} ms" if cycle else None,
    }


# Combat stats that differ between a toggle unit's two weapon sets (read per stance's
# PRIMARY weapon); everything else is stance-independent but still emitted per stance.
WEAPON_SPLIT_FIELDS = ("damage", "damage_type", "attack_speed", "range", "radius")
# Of the stance-independent stats, the ones the Hero infobox duplicates to its `_melee`/
# `_ranged` columns (it keeps health single). The Unit infobox duplicates all to `_alt`.
HERO_SHARED_FIELDS = ("armor", "speed")

# The flag/locomotor the engine sets while mounted (a `MOUNTED` ArmorSet/WeaponSet and the
# `SET_MOUNTED` locomotor).
MOUNTED_FLAG = "MOUNTED"
MOUNTED_LOCOMOTOR = "SET_MOUNTED"
# Stats whose mounted value differs from the foot value (so the Hero infobox carries a
# `_mounted` column). Trample is mounted-only, so it is handled separately.
MOUNT_SPLIT_FIELDS = ("damage", "damage_type", "attack_speed", "range", "radius", "speed", "armor")


def _iter_mount_targets(unit):
    """Yield the object each of `unit`'s `ToggleMountedSpecialAbilityUpdate` modules mounts
    into: `unit` itself for a toggle with no `MountedTemplate` (it mounts in place), else the
    resolved template object. Unloaded templates are skipped. A hero may carry several toggles
    - a horse, a flying mount, and form transforms all share this module - so the caller
    classifies the targets rather than taking only the first."""
    game = getattr(unit, "_game", None)
    owner = unit
    while owner is not None:
        for module in getattr(owner, "modules", ()):
            if not isinstance(module, ToggleMountedSpecialAbilityUpdate):
                continue
            name = getattr(safe(lambda m=module: m.MountedTemplate), "name", None)
            if name and game is not None:
                target = game.objects.get(name)
                if target is not None:
                    yield target
            else:
                yield unit
        owner = getattr(owner, "parent", None)


def _ground_mount(unit):
    """The object the ground-mounted stance reads from, or None. The first toggle target that
    is not a flyer - `unit` for a mount-in-place toggle, else a separate mounted template (a
    horse, or a non-flying transform the engine reaches through the same module)."""
    for target in _iter_mount_targets(unit):
        if target is unit or not _giant_bird(target):
            return target
    return None


def _flying_mount(unit):
    """The flying mount a hero toggles onto (a fell beast, an eagle), or None - the first
    toggle target carrying `GiantBirdAIUpdate`. Distinct from `unit` itself flying, which is
    the pure-flyer case handled separately."""
    for target in _iter_mount_targets(unit):
        if target is not unit and _giant_bird(target):
            return target
    return None


def _giant_bird(obj) -> bool:
    """Whether `obj` flies - it carries `GiantBirdAIUpdate` (an eagle). A flyer's combat
    stats belong in the Hero infobox's `_flying` column rather than `_mounted`."""
    return find_behavior(obj, GiantBirdAIUpdate) is not None


def _summon_timer(obj) -> str | None:
    """A summoned object's lifespan in seconds (its `LifetimeUpdate.MaxLifetime`, the Hero
    infobox's summon `timer`), or None for a permanent object."""
    module = find_behavior(obj, LifetimeUpdate)
    if module is None:
        return None
    milliseconds = safe(lambda: module.MaxLifetime) or safe(lambda: module.MinLifetime)
    if not milliseconds:
        return None
    return _fmt_number(float(milliseconds) / 1000)


def _mounted_stats(unit, state: UnitState, mounted_obj) -> dict[str, str | None]:
    """The mounted-stance combat stats keyed by field name. A separate `mounted_obj` is read
    from its own base state; otherwise the unit's MOUNTED-flagged weapon/armor and SET_MOUNTED
    locomotor are selected. `trample_damage` is the crush weapon's damage."""
    if mounted_obj is unit:
        m_state = state
        weapon = _primary_of(select_weapon_set(unit, state.weapon_flags | {MOUNTED_FLAG}))
        armor_set = select_armor_set(unit, state.armor_flags | {MOUNTED_FLAG})
        locomotor_set = select_locomotor_set(unit, MOUNTED_LOCOMOTOR)
        crush = _named_weapon(unit, "CrushWeapon")
    else:
        m_state = UnitState(mounted_obj)
        weapon = _primary_of(m_state.weapon_set)
        armor_set = m_state.armor_set
        locomotor_set = m_state.locomotor_set
        crush = _named_weapon(mounted_obj, "CrushWeapon")
    stats = _weapon_stats(weapon, m_state)
    armor_name = armorset_view(armor_set)["armor"] if armor_set is not None else None
    stats["armor"] = armor_name.lower() if armor_name else None
    stats["speed"] = (
        _fmt_number(safe(lambda: float(locomotor_set.Speed))) if locomotor_set is not None else None
    )
    stats["trample_damage"] = (
        _fmt_number(_weapon_top_damage(crush, m_state)) if crush is not None else None
    )
    return stats


# infobox param -> function (FieldContext) -> value string (or None to skip)
FIELD_MAP: dict[str, Callable[[FieldContext], str | None]] = {
    "object_name": lambda c: c.obj.name,
    "cost": lambda c: _fmt_number(build_cost_view(c.obj)["BuildCost"]),
    "command_points": lambda c: _fmt_number(build_cost_view(c.obj)["CommandPoints"]),
    "time": lambda c: _fmt_number(build_cost_view(c.obj)["BuildTime"]),
    "health": _health,
    "armor": _armor,
    "damage": _damage,
    "damage_type": _damage_type,
    "revenge_damage": _revenge_damage,
    "trample_damage": _trample_damage,
    "attack_speed": _attack_speed,
    "range": _range,
    "radius": _radius,
    "speed": _speed,
    "resources": _resources,
    "interval": _interval,
}

# Read from the build object itself and identical at every level, so never indexed.
OBJECT_FIELDS = ("object_name", "cost", "command_points", "time")


def building_levels(unit) -> list[tuple[frozenset[str], float | None]]:
    """The `(active_upgrades, rank)` that resolves each level of a leveled building, in level
    order. A building levels one of two ways:

    - economy upgrades - each level adds the next `AttributeModifierUpgrade` (HEALTH/PRODUCTION),
      so level 1 takes no upgrade and each later level the cumulative set (rank stays None);
    - veterancy rank - a multi-rank `ExperienceLevel` ladder steps the building through its
      ranks, whose per-rank modifiers carry the health gain (no extra upgrade, rank selected).
      The rank may be earned by experience (`RequiredExperience`) or pushed by a `LevelUpUpgrade`;
      either way the ladder is what the page columns reflect.

    Empty unless `unit` is a structure leveled by one of these (a lone-rank or unleveled
    structure has no per-level columns)."""
    if not has_kindof(unit, "STRUCTURE"):
        return []
    upgrades = economy_level_upgrades(unit)
    if upgrades:
        return [(frozenset(upgrades[:level]), None) for level in range(len(upgrades) + 1)]
    ranks = RankSelector(unit).ranks
    if len(ranks) > 1:
        return [(frozenset(), rank) for rank in ranks]
    return []


def computed_fields(obj, active_upgrades=frozenset()) -> dict[str, str]:
    """Every infobox value derivable from `obj`, keyed by parameter name. Object-level
    fields are emitted once; combat/resource stats once for a unit, but per-level columns
    (`health1`, …) for a leveled building and per-stance (`damage_melee`, …) for a toggle
    hero. Fields the object doesn't define are omitted.

    `active_upgrades` are applied on top of the base state (unioned with a building's
    per-level upgrades).
    """
    unit = _combat_unit(obj)
    base_active = frozenset(active_upgrades)

    def context_for(active: frozenset[str], rank=None) -> FieldContext:
        unit_state = UnitState(unit, active_upgrades=active, rank=rank)
        source_state = (
            unit_state if unit is obj else UnitState(obj, active_upgrades=active, rank=rank)
        )
        return FieldContext(obj=obj, unit=unit, unit_state=unit_state, source_state=source_state)

    def emit(result: dict[str, str], param: str, derive, context: FieldContext) -> None:
        value = safe(lambda: derive(context))
        if value is not None and str(value) != "":
            result[param] = str(value)

    result: dict[str, str] = {}
    base = context_for(base_active)
    for param in OBJECT_FIELDS:
        emit(result, param, FIELD_MAP[param], base)

    stat_fields = [(p, d) for p, d in FIELD_MAP.items() if p not in OBJECT_FIELDS]
    levels = building_levels(unit)
    is_hero = has_kindof(unit, "HERO")
    ground_obj = None if levels else _ground_mount(unit)
    flying_obj = None if levels else _flying_mount(unit)
    toggle_flag = None if levels else _weapon_toggle_flag(unit, base.unit_state)
    if is_hero and (ground_obj is not None or flying_obj is not None):
        # A hero may have both a ground mount and a flying one (a Ring Hunter on foot, horse,
        # or fell beast), so foot/mounted/flying are emitted together as available.
        _emit_mount_split(result, emit, base, stat_fields, ground_obj, flying_obj)
    elif is_hero and _giant_bird(unit):
        _emit_single_stance(result, emit, base, stat_fields, "_flying")  # a flyer (Great Eagles)
    elif toggle_flag and is_hero:
        _emit_hero_split(result, emit, base, stat_fields, toggle_flag)
    elif toggle_flag:
        _emit_unit_split(result, emit, base, stat_fields, toggle_flag)
    elif levels:
        for index, (active, rank) in enumerate(levels, start=1):
            context = context_for(base_active | active, rank)
            for param, derive in stat_fields:
                emit(result, f"{param}{index}", derive, context)
    else:
        for param, derive in stat_fields:
            emit(result, param, derive, base)
    if is_hero:
        _set(result, "timer", _summon_timer(obj))
    return result


def _set(result: dict[str, str], param: str, value) -> None:
    """Record a formatted stat value under `param`, skipping None/empty."""
    if value is not None and str(value) != "":
        result[param] = str(value)


def _emit_hero_split(result, emit, base: FieldContext, stat_fields, toggle_flag: str) -> None:
    """Fill `result` with a toggle hero's per-stance combat stats (`_melee`/`_ranged`). Armor
    and speed are stance-independent but still emitted to both columns; other stats stay single."""
    melee, ranged = _melee_ranged_weapons(base.unit, base.unit_state, toggle_flag)
    columns = (
        ("_melee", _weapon_stats(melee, base.unit_state)),
        ("_ranged", _weapon_stats(ranged, base.unit_state)),
    )
    for param, derive in stat_fields:
        if param in WEAPON_SPLIT_FIELDS:
            for suffix, stats in columns:
                _set(result, f"{param}{suffix}", stats.get(param))
        elif param in HERO_SHARED_FIELDS:
            emit(result, f"{param}_melee", derive, base)
            emit(result, f"{param}_ranged", derive, base)
        else:
            emit(result, param, derive, base)


def _emit_unit_split(result, emit, base: FieldContext, stat_fields, toggle_flag: str) -> None:
    """Fill `result` with a toggle unit's primary (unsuffixed) and alternate (`_alt`) stance
    stats. Weapon stats come from each set's PRIMARY weapon; every other stat's `_alt` copy
    just repeats the base value."""
    alt_weapon = _primary_of(
        select_weapon_set(base.unit, base.unit_state.weapon_flags | {toggle_flag})
    )
    alt_stats = _weapon_stats(alt_weapon, base.unit_state)
    for param, derive in stat_fields:
        emit(result, param, derive, base)  # the default stance, unsuffixed
        if param in WEAPON_SPLIT_FIELDS:
            _set(result, f"{param}_alt", alt_stats.get(param))
        else:
            emit(result, f"{param}_alt", derive, base)


def _emit_single_stance(result, emit, base: FieldContext, stat_fields, suffix: str) -> None:
    """Fill `result` with a single-stance hero's combat stats under one `suffix` column (a
    flyer's `_flying`). Object stats (health, …) stay single fields."""
    for param, derive in stat_fields:
        if param in WEAPON_SPLIT_FIELDS or param in HERO_SHARED_FIELDS:
            emit(result, f"{param}{suffix}", derive, base)
        else:
            emit(result, param, derive, base)


def _emit_mount_split(
    result, emit, base: FieldContext, stat_fields, ground_obj, flying_obj
) -> None:
    """Fill `result` with a mountable hero's on-foot (`_melee`), ground-mounted (`_mounted`)
    and flying-mounted (`_flying`) stats. The foot column comes from the base state; each
    mount column from `_mounted_stats` on its object, emitted only when that mount exists (a
    hero may have a horse, a fell beast, or both). Trample is the ground mount's; health stays
    a single field."""
    ground = _mounted_stats(base.unit, base.unit_state, ground_obj) if ground_obj else None
    flying = _mounted_stats(base.unit, base.unit_state, flying_obj) if flying_obj else None
    for param, derive in stat_fields:
        if param == "trample_damage":
            if ground is not None:
                _set(result, "trample_damage_mounted", ground.get("trample_damage"))
        elif param in MOUNT_SPLIT_FIELDS:
            emit(result, f"{param}_melee", derive, base)  # on foot
            if ground is not None:
                _set(result, f"{param}_mounted", ground.get(param))
            if flying is not None:
                _set(result, f"{param}_flying", flying.get(param))
        else:
            emit(result, param, derive, base)  # health, … - a single field
