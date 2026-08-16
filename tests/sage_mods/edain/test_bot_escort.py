"""Why a party is not filled in the order the queues happened to finish.

`expansion_parties` handed spare battalions round by object id, which is recruit order, which is
whatever the barracks and the archery range finished first. Nothing in that says a party needs
somebody who can stand in a fight - so two archer battalions completing in a row went out as a
party of two bows.

That is not a weak party, it is a free kill. An archer beats everything at range and loses to
everything that reaches it, so a group with no melee in it is one whatever finds it simply walks
into. `stage_archers` is the other half of the same problem and is switched off, because pulling
bows *out* of a melee needs a damage reading it does not have; keeping them company on the way
out needs nothing at all.

The rule is an ordering and never a refusal, which is what makes it safe: an army that is nothing
but archers still goes out, on the same cycle, with the same battalions.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import ARCHER
from sage_mods.edain.bot.warfare import Warfare

BOW = "GondorArcherHorde"
SWORD = "GondorFighterHorde"


def _unit(object_id: int, template: str) -> SimpleNamespace:
    return SimpleNamespace(object_id=object_id, template_name=template)


class Field:
    """`escort_first` over an army whose roles are read off the template."""

    escort_first = Warfare.escort_first

    def role(self, obj: SimpleNamespace, which: str) -> bool:
        return which == ARCHER and obj.template_name == BOW


def _alive(*units: SimpleNamespace) -> dict[int, SimpleNamespace]:
    return {u.object_id: u for u in units}


def test_a_party_with_no_melee_is_given_melee_first() -> None:
    """The bug. The party is two bows and the spare pool leads with a third."""
    alive = _alive(_unit(1, BOW), _unit(2, BOW), _unit(3, BOW), _unit(4, SWORD))
    field = Field()
    assert field.escort_first([3, 4], alive, (1, 2)) == [4, 3]


def test_a_party_that_already_has_melee_is_left_alone() -> None:
    """**The second swordsman matters much less than the first.** Preferring melee past that
    point would starve the parties that have no bows at all."""
    alive = _alive(_unit(1, SWORD), _unit(3, BOW), _unit(4, SWORD))
    field = Field()
    assert field.escort_first([3, 4], alive, (1,)) == [3, 4]


def test_an_all_archer_army_still_goes_out() -> None:
    """The case a refusal would have to answer for and this never has to ask. There is no melee
    anywhere, and the party leaves anyway with exactly what there is."""
    alive = _alive(_unit(1, BOW), _unit(3, BOW), _unit(4, BOW))
    field = Field()
    assert field.escort_first([3, 4], alive, (1,)) == [3, 4]


def test_nothing_is_added_or_dropped() -> None:
    """It is a permutation. A battalion that fell out here would be one that never expanded and
    never idled in `_forming` either - lost bookkeeping rather than a tactical choice."""
    alive = _alive(*(_unit(i, BOW if i % 2 else SWORD) for i in range(1, 9)))
    field = Field()
    spare = [2, 3, 4, 5, 6, 7, 8]
    assert sorted(field.escort_first(spare, alive, (1,))) == sorted(spare)


def test_a_dead_battalion_in_the_party_does_not_count_as_an_escort() -> None:
    """`alive` is the filter everything else in `expansion_parties` is keyed on, and a party
    whose only swordsman has just died is a party with no melee in it."""
    alive = _alive(_unit(2, BOW), _unit(4, SWORD))
    field = Field()
    # 1 was the party's swordsman and is no longer alive.
    assert field.escort_first([4, 2], alive, (1, 2)) == [4, 2]
