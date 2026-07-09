"""Special-power and modifier views: which module drives a power, what it does (fired
weapon, summon chain - eggs hatched - or attribute modifier), its cooldown, and the
mounted-form toggle."""

from sage_ini.model.behaviors import (
    CreateObjectDieBehavior,
    LifetimeUpdate,
    OCLSpecialPower,
    SlowDeathBehavior,
    SpecialPowerModule,
    ToggleMountedSpecialAbilityUpdate,
    WeaponFireSpecialAbilityUpdate,
)
from sage_ini.model.game import Game
from sage_ini.model.state import modifier_entries
from sage_utils.views.base import all_modules, find_behavior, safe
from sage_utils.views.weapons import weapon_nuggets


def _special_power_modules(obj, name) -> list:
    """Every behavior module on `obj` driven by the SpecialPower `name` (matched on its
    raw `SpecialPowerTemplate` token), in object order. A power is usually wired by
    several modules sharing the template - an enabler, a paused starter and the module
    carrying the effect - so the caller picks the one it renders."""
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
        "melee": bool(safe(lambda: weapon.MeleeWeapon)) if weapon is not None else False,
        "range": safe(lambda: float(weapon.AttackRange)) if weapon is not None else None,
        "nuggets": weapon_nuggets(weapon) if weapon is not None else [],
    }


def _ocl_created_names(ocl) -> list[str]:
    """The object names an ObjectCreationList places (across its CreateObject blocks),
    in first-seen order."""
    if ocl is None:
        return []
    names: list[str] = []
    for create in safe(lambda: ocl.CreateObject, []) or []:
        for entry in safe(lambda c=create: c.ObjectNames, []) or []:
            obj_name = getattr(entry, "name", None) or str(entry)
            if obj_name and obj_name not in names:
                names.append(obj_name)
    return names


def _hatch_ocls(obj) -> list:
    """The ObjectCreationLists `obj` spawns when it dies - a summon egg's hatch - from a
    CreateObjectDie's `CreationList` or a SlowDeathBehavior's `OCL` (grouped by death
    phase)."""
    ocls = []
    for module in all_modules(obj):
        if isinstance(module, CreateObjectDieBehavior):
            ocl = safe(lambda m=module: m.CreationList)
            if ocl is not None:
                ocls.append(ocl)
        elif isinstance(module, SlowDeathBehavior):
            grouped = safe(lambda m=module: m.OCL, {}) or {}
            for bucket in grouped.values():
                ocls.extend(ocl for ocl in bucket if ocl is not None)
    return ocls


def _is_summon_egg(obj) -> bool:
    """Whether `obj` is a summon egg: a placeholder that auto-dies (a LifetimeUpdate)
    *and* hatches a payload from a death behavior. Both halves are required, to tell it
    apart from a real unit that merely drops debris on death."""
    has_lifetime = any(isinstance(m, LifetimeUpdate) for m in all_modules(obj))
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
    reload_ms = safe(lambda: power.ReloadTime)
    return None if reload_ms is None else reload_ms / 1000


def special_power_view(game: Game, obj, name: str) -> dict:
    """How a SPECIAL_POWER button's effect should render, resolved from the module on
    `obj` the named SpecialPower drives. `kind` selects the UI handling and the matching
    payload field is filled, the rest left empty:

    - "weapon" - a WeaponFireSpecialAbilityUpdate fires `weapon`.
    - "modifier" - a SpecialPowerModule applies `modifier` (an AttributeModifier).
    - "summon" - an OCLSpecialPower spawns the `summoned` chain.
    - "" - nothing resolvable; only `name` is known.

    `cooldown` is the recharge time in seconds, or None.
    """
    view: dict = {
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
            ocl = safe(lambda m=module: m.OCL)
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


def mounted_template(obj) -> str | None:
    """The raw name of the object a unit's ToggleMountedSpecialAbilityUpdate mounts it
    into (its `MountedTemplate`), or None when there is no such module."""
    behavior = find_behavior(obj, ToggleMountedSpecialAbilityUpdate)
    if behavior is None:
        return None
    return getattr(safe(lambda: behavior.MountedTemplate), "name", None)
