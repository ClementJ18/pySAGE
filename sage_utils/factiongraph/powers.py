"""Resolving what a special power / ability actually does, into the links a reader cares about: the
objects it creates, the form it turns the user into, the weapon it fires, and the stat buffs it
grants.

The core three kinds (weapon / modifier / summon) come from `sage_utils.views.special_power_view`.
On top, this reads the effect-bearing fields of *any* module that names the power: `MountedTemplate`
(a transform) and `AttributeModifier` / `HeroAttributeModifier` (a buff) on the WeaponMode/HeroMode
toggles `special_power_view` doesn't cover. Powers whose modules name no weapon/modifier/object stay
unclassified (`kind == ""`) and render from their description alone, per the project decision.
"""

from __future__ import annotations

from sage_utils.factiongraph.model import Power, Weapon
from sage_utils.views import (
    display_name,
    modifier_view,
    safe,
    special_power_cooldown,
    special_power_view,
)


def _display(game, name: str) -> str:
    obj = game.objects.get(name)
    return (display_name(game, obj) if obj is not None else None) or name


def _raw_token(module, field: str) -> str | None:
    raw = module._fields.get(field)
    if raw is None:
        return None
    return str(raw[-1] if isinstance(raw, list) else raw).split()[0]


def _summon_targets(game, chain) -> list[tuple[str, str]]:
    """The real objects a summon chain (`special_power_view`'s `summoned`) places, as
    `(name, display)` pairs in first-seen order. Summon eggs - placeholders that auto-die and hatch
    a payload - are descended through, not listed: the player cares about what hatches, not the egg.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def walk(nodes) -> None:
        for node in nodes:
            children = node.get("summoned") or []
            if children:  # a summon egg - skip it, descend to the objects it hatches
                walk(children)
                continue
            name = node["name"]
            # Drop FX/banner egg placeholders that hatch nothing navigable (the `…Egg` convention).
            if name in seen or name.endswith("Egg"):
                continue
            seen.add(name)
            out.append((name, _display(game, name)))

    walk(chain)
    return out


def _weapon_summary(weapon: dict) -> Weapon:
    """A `special_power_view` weapon dict reduced to a `Weapon` summary (total nugget damage, the
    hardest nugget's type, range for a ranged weapon)."""
    nuggets = weapon.get("nuggets") or []
    damage = sum(n["damage"] for n in nuggets if n.get("damage")) or None
    best = best_type = None
    for nugget in nuggets:
        value = nugget.get("damage")
        if value and (best is None or value > best):
            best, best_type = value, nugget.get("damage_type")
    melee = bool(weapon.get("melee"))
    return Weapon(
        kind="melee" if melee else "ranged",
        damage=damage,
        damage_type=best_type,
        range=None if melee else weapon.get("range"),
    )


def _modifier_rows(modifier_list) -> list[tuple[str, str]]:
    return [(label, value) for label, value in modifier_view(modifier_list)["modifiers"]]


def _resolve_extra(game, obj, name: str, power: Power) -> None:
    """Fill `transforms_into` and `modifiers` from any module on `obj` (or a parent) that names the
    power - the WeaponMode/HeroMode/ToggleMounted toggles `special_power_view` does not classify."""
    owner = obj
    while owner is not None:
        for module in getattr(owner, "modules", ()):
            if _raw_token(module, "SpecialPowerTemplate") != name:
                continue
            form = _raw_token(module, "MountedTemplate")
            if form and form not in {n for n, _ in power.transforms_into}:
                power.transforms_into.append((form, _display(game, form)))
            for field in ("AttributeModifier", "HeroAttributeModifier"):
                mod_name = _raw_token(module, field)
                modifier_list = game.modifiers.get(mod_name) if mod_name else None
                if modifier_list is not None:
                    for row in _modifier_rows(modifier_list):
                        if row not in power.modifiers:
                            power.modifiers.append(row)
        owner = getattr(owner, "parent", None)


def _primary_kind(power: Power) -> str:
    """A coarse label from what resolved (the UI renders every populated field regardless)."""
    if power.creates:
        return "summon"
    if power.transforms_into:
        return "transform"
    if power.weapon is not None:
        return "weapon"
    if power.modifiers:
        return "modifier"
    return ""


def resolve_power(game, obj, name: str, display: str, effect: str = "") -> Power:
    """A fully-resolved `Power` for the special power `name` driven by `obj`'s modules."""
    power = Power(
        name=name,
        display=display,
        cooldown=special_power_cooldown(game, name),
        effect=effect,
    )
    view = special_power_view(game, obj, name)
    if view["kind"] == "summon":
        power.creates = _summon_targets(game, view["summoned"])
    elif view["kind"] == "weapon" and view["weapon"] is not None:
        power.weapon = _weapon_summary(view["weapon"])
    elif view["kind"] == "modifier" and view["modifier"] is not None:
        power.modifiers = safe(lambda: _modifier_rows(view["modifier"]), [])
    _resolve_extra(game, obj, name, power)
    power.kind = _primary_kind(power)
    return power
