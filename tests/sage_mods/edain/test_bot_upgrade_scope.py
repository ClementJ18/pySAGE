"""What a refused upgrade is remembered against, which has to be the button's own scope.

A faction tech is bought once and its name is the whole of it. A per-object upgrade is bought
once per battalion, so remembering a refusal by name alone means two failures anywhere retire it
everywhere.

Measured across one match: `Upgrade_GondorHeavyArmor`, `Upgrade_GondorForgedBlades` and
`Upgrade_GondorBasicTraining` were each bought three or four times, then refused twice on a single
`GondorFighterHorde`. With `UPGRADE_ATTEMPTS` at two, all three were retired for the whole army.
The run ended with 35,727 gold banked, its last research at cycle 931, and twenty-five battalions
carrying none of the three upgrades the forge had already paid to unlock.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.economy import Economy
from sage_mods.edain.bot.tuning import UPGRADE_ATTEMPTS


def _horde(object_id: int) -> SimpleNamespace:
    return SimpleNamespace(object_id=object_id, template_name="GondorFighterHorde")


def _button(name: str, player_scope: bool) -> SimpleNamespace:
    return SimpleNamespace(upgrade=name, player_scope=player_scope, cost=300)


def test_a_per_object_refusal_is_remembered_against_that_object() -> None:
    """The bug: two battalions must not share one another's refusals."""
    armour = _button("Upgrade_GondorHeavyArmor", player_scope=False)

    first = Economy._upgrade_key(_horde(101), armour)
    second = Economy._upgrade_key(_horde(202), armour)

    assert first != second
    assert first.startswith("101:")
    assert second.startswith("202:")


def test_a_faction_tech_is_remembered_by_name_alone() -> None:
    """Bought once for the whole player, so the name is exactly the right scope - and the
    building it happens to be ordered at must not split the count."""
    tech = _button("Upgrade_TechnologyGondorHeavyArmor", player_scope=True)

    forge = Economy._upgrade_key(SimpleNamespace(object_id=7, template_name="GondorForge"), tech)
    other = Economy._upgrade_key(SimpleNamespace(object_id=9, template_name="GondorForge"), tech)

    assert forge == other == "upgrade_technologygondorheavyarmor"


def test_retiring_one_battalions_upgrade_leaves_the_rest_buyable() -> None:
    """The whole point, stated as the scenario that was measured.

    A horde refuses armour `UPGRADE_ATTEMPTS` times and is given up on. Every other battalion in
    the army must still be offered it.
    """
    armour = _button("Upgrade_GondorHeavyArmor", player_scope=False)
    blocked: dict[str, int] = {}

    unlucky = _horde(101)
    for _ in range(UPGRADE_ATTEMPTS):
        key = Economy._upgrade_key(unlucky, armour)
        blocked[key] = blocked.get(key, 0) + 1

    assert blocked[Economy._upgrade_key(unlucky, armour)] >= UPGRADE_ATTEMPTS
    for other in (_horde(202), _horde(303)):
        assert blocked.get(Economy._upgrade_key(other, armour), 0) < UPGRADE_ATTEMPTS
