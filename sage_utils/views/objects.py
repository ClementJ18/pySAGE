"""Whole-object views: economy stats, resource production, and the identity/upgrade
summary a detail panel starts from."""

from sage_ini.model.behaviors import AutoDepositUpdate, TerrainResourceBehavior
from sage_ini.model.state import find_upgrades, has_kindof
from sage_utils.views.base import find_behavior, safe
from sage_utils.views.weapons import weapon_upgrade_triggers


def build_cost_view(obj) -> dict:
    """An object's economy stats — build cost, build time, command points, bounty
    (resources awarded to the killer). A `BUILD_FOR_FREE` object's build cost is always 0."""
    cost = 0 if has_kindof(obj, "BUILD_FOR_FREE") else safe(lambda: obj.BuildCost)
    return {
        "BuildCost": cost,
        "BuildTime": safe(lambda: obj.BuildTime),
        "CommandPoints": safe(lambda: obj.CommandPoints),
        "BountyValue": safe(lambda: obj.BountyValue),
    }


def resource_production_view(obj) -> dict:
    """A resource building's production from either money-over-time module:
    `TerrainResourceBehavior` (`MaxIncome` per `IncomeInterval`) or `AutoDepositUpdate`
    (`DepositAmount` per `DepositTiming`). Intervals are returned in whole seconds; each
    pair is None when the object carries no such module. Amounts are base values, scaled
    by the caller's active PRODUCTION modifier.
    """
    terrain = find_behavior(obj, TerrainResourceBehavior)
    deposit = find_behavior(obj, AutoDepositUpdate)
    income_ms = safe(lambda: terrain.IncomeInterval) if terrain is not None else None
    timing_ms = safe(lambda: deposit.DepositTiming) if deposit is not None else None
    return {
        "MaxIncome": safe(lambda: terrain.MaxIncome) if terrain is not None else None,
        "IncomeInterval": None if income_ms is None else income_ms / 1000,
        "DepositAmount": safe(lambda: deposit.DepositAmount) if deposit is not None else None,
        "DepositTiming": None if timing_ms is None else timing_ms / 1000,
    }


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
