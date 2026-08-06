"""Leaving somebody fighting while the rest knock the building down.

A structure does not shoot back and does not run away, so a party that sends every battalion at
one while enemies stand next to it is taking a beating for free: every order goes to the
building, and the troops around it fight unopposed for as long as the demolition takes.

`screen` is what turns one battalion round. It began as an archers-only rule - a bow pointed at a
building is the one trade the unit was bought to avoid - and the general case is the same
argument with a cheaper answer: somebody, anybody, has to be facing the enemy.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import ARCHER, SCREEN_REACH
from sage_mods.edain.bot.warfare import Warfare

ARCHERS, SWORDS, LAIR = "GondorArcherHorde", "GondorFighterHorde", "MordorOrcPit"


def _unit(object_id: int, template: str, x: float) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


class Party(Warfare):
    """`screen` over a fixed party, a fixed target and a fixed set of hostiles."""

    def __init__(self, force: list, enemies: list, target_is_structure: bool = True) -> None:
        self._force = force
        self._enemies = enemies
        self.engaged: list[tuple] = []
        self.statics = SimpleNamespace(
            has_kind=lambda name, *flags: target_is_structure and "STRUCTURE" in flags
        )

    @property
    def observation(self) -> SimpleNamespace:
        return SimpleNamespace(objects=[*self._force, *self._enemies])

    def role(self, obj, *flags) -> bool:
        return ARCHER in flags and obj.template_name == ARCHERS

    def hostile(self, obj) -> bool:
        return obj in self._enemies

    def engage(self, force, target, what, key):
        self.engaged.append((tuple(o.object_id for o in force), target.object_id, key))
        return what


def test_one_battalion_turns_to_meet_what_is_on_the_party() -> None:
    """The rule. Three swordsmen at a lair with an orc beside them: two keep swinging at the
    building and one fights."""
    force = [_unit(1, SWORDS, 0.0), _unit(2, SWORDS, 10.0), _unit(3, SWORDS, 20.0)]
    party = Party(force, [_unit(9, SWORDS, 30.0)])
    screened, said = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert len(screened) == 1 and said is not None
    assert party.engaged[0][2] == "raid:screen"


def test_the_battalion_nearest_the_threat_is_the_one_that_turns() -> None:
    """The others are already swinging at the building; the one that has to walk least is the
    one whose fight starts soonest."""
    force = [_unit(1, SWORDS, 0.0), _unit(2, SWORDS, 500.0)]
    party = Party(force, [_unit(9, SWORDS, 520.0)])
    screened, _ = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert [o.object_id for o in screened] == [2]


def test_archers_are_still_preferred_and_all_of_them_go() -> None:
    """For a bow the screen is not a sacrifice, it is the better target - so the original rule
    survives intact and takes every archer rather than one battalion."""
    force = [_unit(1, ARCHERS, 0.0), _unit(2, ARCHERS, 10.0), _unit(3, SWORDS, 20.0)]
    party = Party(force, [_unit(9, SWORDS, 30.0)])
    screened, _ = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert [o.object_id for o in screened] == [1, 2]
    assert party.engaged[0][2] == "raid:bows"


def test_nothing_nearby_means_nobody_turns_round() -> None:
    """The building is the objective. A screen against an empty field is a battalion not
    demolishing anything."""
    force = [_unit(1, SWORDS, 0.0), _unit(2, SWORDS, 10.0)]
    party = Party(force, [_unit(9, SWORDS, SCREEN_REACH * 3)])
    assert party.screen(force, _unit(50, LAIR, 0.0), "raid") == ([], None)


def test_a_lone_battalion_does_not_screen_itself() -> None:
    """One battalion cannot both hold the enemy off and knock the building down, and the target
    is the reason it walked there."""
    force = [_unit(1, SWORDS, 0.0)]
    party = Party(force, [_unit(9, SWORDS, 30.0)])
    assert party.screen(force, _unit(50, LAIR, 0.0), "raid") == ([], None)


def test_the_whole_force_is_never_peeled() -> None:
    """A party of pure archers at a building has nobody to leave on it, so it stays as it was -
    splitting here would be a party that has stopped doing the thing it came for."""
    force = [_unit(1, ARCHERS, 0.0), _unit(2, ARCHERS, 10.0)]
    party = Party(force, [_unit(9, SWORDS, 30.0)])
    screened, _ = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert len(screened) < len(force)


def test_a_party_fighting_troops_is_not_split() -> None:
    """Against a battalion the whole party already has the right idea, and splitting it there is
    two half-strength fights instead of one it wins."""
    force = [_unit(1, SWORDS, 0.0), _unit(2, SWORDS, 10.0)]
    party = Party(force, [_unit(9, SWORDS, 30.0)], target_is_structure=False)
    assert party.screen(force, _unit(50, SWORDS, 40.0), "raid") == ([], None)
