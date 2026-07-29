"""The shared name<->id spaces.

These are the rules `narrate` reads with and `retarget` (and a live session) writes with, so
the round trip between the two directions is the thing worth pinning.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sage_replay import narrate
from sage_replay.idspace import (
    POWER_OFFSET,
    SCIENCE_OFFSET,
    THING_OFFSET,
    UPGRADE_OFFSET,
    IdSpace,
    id_spaces,
)

THINGS = ["GondorFighter", "MordorOrcFighter", "RohanPeasant"]
UPGRADES = ["DefaultUpgrade", "Upgrade_GondorForgedBlades", "Upgrade_MordorFireArrows"]
POWERS = ["SpecialPowerEyeOfSauron", "SpecialPowerArmyOfTheDead"]
SCIENCES = ["SCIENCE_Gondor", "SCIENCE_Mordor"]


def spaces():
    return id_spaces(THINGS, UPGRADES, POWERS, SCIENCES)


def test_one_based_spaces_start_at_one():
    assert THING_OFFSET == POWER_OFFSET == SCIENCE_OFFSET == 1
    assert spaces().things.to_id("GondorFighter") == 1
    assert spaces().powers.to_id("SpecialPowerEyeOfSauron") == 1
    assert spaces().sciences.to_id("SCIENCE_Gondor") == 1


def test_upgrades_carry_the_unexplained_plus_three():
    """DefaultUpgrade is id 3, ground-truthed by an in-game survey (order_space_map OPEN 4)."""
    assert UPGRADE_OFFSET == 3
    assert spaces().upgrades.to_id("DefaultUpgrade") == 3
    assert spaces().upgrades.to_id("Upgrade_MordorFireArrows") == 5


@pytest.mark.parametrize("space_name", ["things", "upgrades", "powers", "sciences"])
def test_every_space_round_trips_name_to_id_to_name(space_name):
    space = getattr(spaces(), space_name)
    for name in space.names:
        assert space.to_name(space.to_id(name)) == name


@pytest.mark.parametrize("space_name", ["things", "upgrades", "powers", "sciences"])
def test_every_space_round_trips_id_to_name_to_id(space_name):
    space = getattr(spaces(), space_name)
    for index in range(len(space)):
        replay_id = index + space.offset
        assert space.to_id(space.to_name(replay_id)) == replay_id


def test_an_unknown_name_resolves_to_none_rather_than_raising():
    """A replay routinely names definitions a differently-modded install lacks."""
    assert spaces().things.to_id("NotATemplate") is None


@pytest.mark.parametrize("replay_id", [-5, 0, 99])
def test_an_out_of_range_id_resolves_to_none(replay_id):
    assert spaces().things.to_name(replay_id) is None


def test_an_id_below_the_upgrade_offset_is_out_of_range():
    """Ids 0..2 fall below DefaultUpgrade and name nothing."""
    for replay_id in (0, 1, 2):
        assert spaces().upgrades.to_name(replay_id) is None


def test_an_empty_space_resolves_nothing():
    empty = IdSpace([], THING_OFFSET)
    assert len(empty) == 0
    assert empty.to_id("anything") is None
    assert empty.to_name(1) is None


def test_a_duplicated_name_resolves_to_its_last_registration():
    """A registration order should not contain duplicates, but if it does the *last* one wins
    - which is what `retarget`'s dict comprehension always did, preserved deliberately rather
    than quietly changed. Both directions still agree, which is what callers rely on."""
    space = IdSpace(["A", "B", "A"], THING_OFFSET)
    assert space.to_id("A") == 3
    assert space.to_name(3) == "A"
    assert space.to_name(1) == "A", "the earlier slot still names it in the read direction"


def test_the_lookup_index_is_cached_without_breaking_frozenness():
    space = spaces().things
    assert space.to_id("RohanPeasant") == 3
    assert space.to_id("RohanPeasant") == 3, "the cached index must give the same answer"
    with pytest.raises(FrozenInstanceError):
        space.offset = 7  # type: ignore[misc]


def test_narrate_and_retarget_share_this_offset():
    """The whole point of the module: one rule, not three copies."""
    assert narrate._UPGRADE_OFFSET is UPGRADE_OFFSET
