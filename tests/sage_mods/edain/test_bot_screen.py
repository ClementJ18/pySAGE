"""Leaving somebody fighting while the rest knock the building down.

A structure does not shoot back and does not run away, so a party that sends every battalion at
one while enemies stand next to it is taking a beating for free: every order goes to the
building, and the troops around it fight unopposed for as long as the demolition takes.

`screen` is what turns one battalion round. It began as an archers-only rule - a bow pointed at a
building is the one trade the unit was bought to avoid - and the general case is the same
argument with a cheaper answer: somebody, anybody, has to be facing the enemy.

**And a creep lair is where "anybody" stops being good enough.** Its slaves are output rather than
opposition, so the party stands in them for the whole demolition; the tree's own armour blocks
make that a matchup rather than a matter of luck - every troll armour takes `SPECIALIST` at
90-170% and `SLASH` at 20-50%, and `WargpackEdainArmor` reads 170% against 100%. `counters` is
what reads it, and none of it names a warg or a troll.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import ARCHER, COUNTER_EDGE, SCREEN_REACH
from sage_mods.edain.bot.warfare import Warfare

ARCHERS, SWORDS, LAIR = "GondorArcherHorde", "GondorFighterHorde", "MordorOrcPit"
PIKES, WARG = "GondorSpearmanHorde", "NeutralWarg"

# The engine's own arithmetic for the one matchup these tests turn on, rounded off the tree:
# `GondorPikemanWeapon` deals `SPECIALIST` into `WargpackEdainArmor`'s 170%, and `GondorSword`
# deals `SLASH` into its 100%. Anything not listed is an even fight, which is what
# `Statics.effectiveness` answers for a matchup it cannot read.
TRADES = {(PIKES, WARG): 1.7, (SWORDS, WARG): 1.0, (ARCHERS, WARG): 0.75}


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
            has_kind=lambda name, *flags: target_is_structure and "STRUCTURE" in flags,
            effectiveness=lambda attacker, defender: TRADES.get((attacker, defender), 1.0),
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


def test_the_pikes_take_the_lair_and_the_swords_hold_the_wargs_off_them() -> None:
    """**The arrangement, and it is the inverse of the one this method shipped with.** A warg
    takes 170% from a spear and 100% from a sword, so the spears are the battalions that can
    walk through a warg lair's garrison - which makes them the ones to send at the lair, not the
    ones to tie up in front of it. Watched live, the old split left Gondor's swordsmen hitting
    the building while the spears stood in a fight a lair renews forever.

    `screen` returns whoever was given their own order, so here that is the swords."""
    force = [_unit(1, SWORDS, 0.0), _unit(2, PIKES, 10.0), _unit(3, PIKES, 20.0)]
    party = Party(force, [_unit(9, WARG, 30.0)])
    screened, said = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert [o.object_id for o in screened] == [1]
    assert party.engaged[0][2] == "raid:screen" and said is not None


def test_proximity_no_longer_decides_who_meets_a_lair() -> None:
    """The old rule sent whoever was nearest, which at a lair is whoever happened to walk in
    front. The swordsman is standing on the warg and it is still the matchup that decides - the
    spear goes at the lair and the sword is the one left holding the warg."""
    force = [_unit(1, SWORDS, 500.0), _unit(2, PIKES, 0.0)]
    party = Party(force, [_unit(9, WARG, 520.0)])
    screened, _ = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert [o.object_id for o in screened] == [1]


def test_a_party_with_no_counter_in_it_screens_the_way_it_always_did() -> None:
    """`counters` answers empty when nobody clears `COUNTER_EDGE`, and the measured
    one-battalion-nearest rule is the right answer there. All swords against a warg is that."""
    force = [_unit(1, SWORDS, 0.0), _unit(2, SWORDS, 500.0)]
    party = Party(force, [_unit(9, WARG, 520.0)])
    screened, _ = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert [o.object_id for o in screened] == [2]
    assert party.engaged[0][2] == "raid:screen"


def test_a_party_that_is_all_counter_is_not_split_by_the_matchup() -> None:
    """Empty from the other end. If every battalion beats the thing there is no "who is this
    for", and peeling them all would put the whole force on the slaves and nothing on the lair -
    which is the fight `screen` exists to avoid."""
    force = [_unit(1, PIKES, 0.0), _unit(2, PIKES, 10.0), _unit(3, PIKES, 20.0)]
    party = Party(force, [_unit(9, WARG, 30.0)])
    screened, _ = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert len(screened) == 1 and party.engaged[0][2] == "raid:screen"


def test_the_edge_has_to_be_a_real_one() -> None:
    """`COUNTER_EDGE` sits above an even matchup on purpose. At 1.0 any unit the numbers do not
    actively punish would qualify, and the screen would become "everybody attack the nearest
    thing"."""
    assert COUNTER_EDGE > 1.0
    force = [_unit(1, SWORDS, 0.0), _unit(2, PIKES, 10.0)]
    party = Party(force, [_unit(9, SWORDS, 30.0)])
    assert party.counters(force, _unit(9, SWORDS, 30.0)) == []


def test_archers_still_go_first_whatever_the_matchup_says() -> None:
    """A bow trades badly into a warg and it is still the thing with something better to do than
    shoot a building - so the original rule keeps its place ahead of this one."""
    force = [_unit(1, ARCHERS, 0.0), _unit(2, PIKES, 10.0), _unit(3, SWORDS, 20.0)]
    party = Party(force, [_unit(9, WARG, 30.0)])
    screened, _ = party.screen(force, _unit(50, LAIR, 0.0), "raid")
    assert [o.object_id for o in screened] == [1]
    assert party.engaged[0][2] == "raid:bows"


def test_a_party_fighting_troops_is_not_split() -> None:
    """Against a battalion the whole party already has the right idea, and splitting it there is
    two half-strength fights instead of one it wins."""
    force = [_unit(1, SWORDS, 0.0), _unit(2, SWORDS, 10.0)]
    party = Party(force, [_unit(9, SWORDS, 30.0)], target_is_structure=False)
    assert party.screen(force, _unit(50, SWORDS, 40.0), "raid") == ([], None)
