"""Name -> id resolution and the name-taking order constructors.

`GameData` is a plain dataclass of name lists, so a build can be faked and the whole module
stays in the data-free suite.
"""

from __future__ import annotations

import pytest

import sage_live
from sage_live.orders import OrderType
from sage_live.resolve import Resolver, UnknownDefinition
from sage_replay.idspace import UPGRADE_OFFSET
from sage_replay.narrate import GameData
from sage_replay.replay import OrderArgumentType


def fake_game() -> GameData:
    return GameData(
        object_order=["GondorFighter", "MordorFighterHorde", "GondorBarracks"],
        objects={},
        specialpowers=["SpecialAbilityEyeOfSauron", "SpecialPowerArmyOfTheDead"],
        sciences=["SCIENCE_Gondor", "SCIENCE_Mordor"],
        upgrades=["DefaultUpgrade", "Upgrade_MordorFireArrows"],
        displaynames={},
    )


@pytest.fixture
def resolver() -> Resolver:
    return Resolver(fake_game(), player_index=3)


def test_thing_ids_are_one_based(resolver):
    assert resolver.thing("GondorFighter") == 1
    assert resolver.thing("GondorBarracks") == 3


def test_upgrade_ids_carry_the_shared_offset(resolver):
    assert resolver.upgrade("DefaultUpgrade") == UPGRADE_OFFSET
    assert resolver.upgrade("Upgrade_MordorFireArrows") == UPGRADE_OFFSET + 1


def test_power_and_science_ids_are_one_based(resolver):
    assert resolver.power("SpecialAbilityEyeOfSauron") == 1
    assert resolver.science("SCIENCE_Mordor") == 2


def test_an_unknown_name_raises_rather_than_resolving_to_something_wrong(resolver):
    """A wrong id builds the wrong thing and looks like a policy bug; fail at the mistake."""
    with pytest.raises(UnknownDefinition) as excinfo:
        resolver.thing("NotAThing")
    assert "NotAThing" in str(excinfo.value)


def test_a_near_miss_is_suggested(resolver):
    with pytest.raises(UnknownDefinition, match="MordorFighterHorde"):
        resolver.thing("MordorFighter")


def test_knows_answers_without_raising(resolver):
    assert resolver.knows("things", "GondorFighter")
    assert not resolver.knows("things", "Nope")
    assert not resolver.knows("nosuchspace", "GondorFighter")


def test_recruit_builds_a_queue_unit_create_order(resolver):
    order = resolver.recruit("MordorFighterHorde")
    assert order.order_type == OrderType.QUEUE_UNIT_CREATE
    assert order.player_index == 3
    assert order.arguments[0].argument_type == OrderArgumentType.Boolean
    assert order.arguments[1].value == 2


def test_build_carries_template_position_and_angle(resolver):
    order = resolver.build("GondorBarracks", (1200.0, 880.0, 61.0), angle=1.5)
    assert order.order_type == OrderType.FOUNDATION_CONSTRUCT
    assert [a.argument_type for a in order.arguments] == [
        OrderArgumentType.Integer,
        OrderArgumentType.Position,
        OrderArgumentType.Float,
    ]
    assert order.arguments[0].value == 3
    assert order.arguments[1].value == (1200.0, 880.0, 61.0)


def test_research_and_purchase_power_resolve_their_own_spaces(resolver):
    assert resolver.research("Upgrade_MordorFireArrows", 545).order_type == OrderType.QUEUE_UPGRADE
    assert resolver.purchase_power("SCIENCE_Gondor").order_type == OrderType.PURCHASE_SCIENCE


def test_the_three_cast_shapes_pick_the_right_order_type(resolver):
    power = "SpecialAbilityEyeOfSauron"
    assert resolver.cast(power).order_type == OrderType.DO_SPECIAL_POWER
    assert resolver.cast_at(power, (1.0, 2.0, 3.0)).order_type == (
        OrderType.DO_SPECIAL_POWER_AT_LOCATION
    )
    assert resolver.cast_on(power, 42, (1.0, 2.0, 3.0)).order_type == (
        OrderType.DO_SPECIAL_POWER_AT_OBJECT
    )


def test_an_unknown_power_fails_before_an_order_is_built(resolver):
    with pytest.raises(UnknownDefinition):
        resolver.cast_at("NoSuchPower", (0.0, 0.0, 0.0))


def test_resolve_is_not_exported_from_the_package_root():
    """It imports sage_ini, so the root must stay install-free."""
    assert "Resolver" not in sage_live.__all__
    assert not hasattr(sage_live, "Resolver")
