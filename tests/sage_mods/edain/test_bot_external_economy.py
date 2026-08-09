"""Which building a claimed settlement gets, when its palette offers more than one.

`unpack_plot` took the first button on the plot, and for Men slot 1 is the farm and the slots do
not move - so every settlement on the map was a farm and the other half of the palette was dead
data. The two are interchangeable as income (identical `TerrainResourceBehavior`, identical
200g unpack cost) and differ in exactly the ways that make spreading them worth something: only
the farm takes the marketplace's `GrandHarvest`, only the tents spawn defenders.

These cover the balance and, more carefully, the cases where the plan must *not* get involved -
an outpost's argument-less claim and a faction with no settlement list, both of which still take
the first button.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.economy import Economy
from sage_mods.edain.bot.factions import Plan

FARM = "GondorFarm_Extern"
TENTS = "GondorRangerTents"
# What the plot offers once `Upgrade_EdainSiedlerWerkzeuge` is held - a different template for
# the same two families, which is why the count follows the `ChildObject` chain.
FARM3 = "GondorFarm_Extern3"
TENTS3 = "GondorRangerTents3"

PARENTS = {
    FARM: "GondorFarm",
    "GondorFarm_Extern2": FARM,
    FARM3: FARM,
    "GondorRangerTents2": TENTS,
    TENTS3: TENTS,
    # Owned, a structure, and named like the tents without being one.
    "GondorRangerTentsDiscountPing": None,
}


class _Statics:
    """`descends_from` over a parent table, which is all the balance reads."""

    def descends_from(self, template: str, ancestor: str) -> bool:
        current: str | None = template
        while current is not None:
            if current.lower() == ancestor.lower():
                return True
            current = PARENTS.get(current)
        return False


class Expanding(Economy):
    """`wanted_external` over a fixed set of owned objects."""

    def __init__(
        self,
        owned: list[str],
        external: tuple[str, ...] = (FARM, TENTS),
        benched: tuple[str, ...] = (),
    ) -> None:
        self._owned = owned
        self._benched = {f"unpack:{root}" for root in benched}
        self.plan = Plan(
            resource="GondorWohnhaus", production=("GondorBarracks",), unit="x", external=external
        )
        self.statics = _Statics()

    def _cold(self, key: str) -> bool:
        return key in self._benched

    @property
    def observation(self) -> SimpleNamespace:
        return SimpleNamespace(mine=[SimpleNamespace(template_name=n) for n in self._owned])


def test_the_first_settlement_gets_the_plans_first_building() -> None:
    """Nothing standing is a tie, and a tie goes to the plan's order - so an opening that used
    to take the farm still takes the farm, and this change is not a rewrite of the opening."""
    assert Expanding([]).wanted_external((FARM, "GondorLeuchtfeuer", TENTS)) == FARM


def test_the_second_settlement_gets_the_other_one() -> None:
    """The whole point: one farm standing makes the tents the family furthest behind."""
    assert Expanding([FARM]).wanted_external((FARM, TENTS)) == TENTS


def test_they_alternate_rather_than_converge() -> None:
    """One of each is a tie again, so the third flag restarts the cycle instead of settling on
    whichever was built last."""
    assert Expanding([FARM, TENTS]).wanted_external((FARM, TENTS)) == FARM
    assert Expanding([FARM, TENTS, FARM]).wanted_external((FARM, TENTS)) == TENTS


def test_an_upgraded_tier_counts_toward_its_family() -> None:
    """A settlement raised after the economy upgrades is a `_Extern3`, and a count that missed
    that would read a map of upgraded farms as having none and build farms for ever."""
    assert Expanding([FARM3, FARM3]).wanted_external((FARM3, TENTS3)) == TENTS3


def test_the_cost_ladders_ping_object_is_not_a_settlement() -> None:
    """It is owned and it is named like the tents. Counting it would make the bot believe it had
    a tent it never built, and the first real one would go to the farm instead."""
    plan = Expanding(["GondorRangerTentsDiscountPing"])
    assert plan.external_standing() == {FARM: 0, TENTS: 0}
    assert plan.wanted_external((FARM, TENTS)) == FARM


def test_the_beacon_is_never_chosen() -> None:
    """Slot 2 of the same palette. It earns nothing, costs twice as much, and is not in the
    plan - so an offer that contains it is an offer of two things, not three."""
    assert Expanding([FARM, FARM]).wanted_external(("GondorLeuchtfeuer",)) is None


def test_a_faction_with_no_settlement_list_defers() -> None:
    """None is how `unpack_plot` is told to keep its first-button answer, which is every plan
    that has not named an `external` set."""
    assert Expanding([], external=()).wanted_external((FARM, TENTS)) is None


def test_a_benched_family_is_not_chosen() -> None:
    """The lock-in this exists to break. Nothing standing is a tie the tents would win on plan
    order once the farm is up, but a benched template must be skipped however far behind it is."""
    assert Expanding([FARM], benched=(TENTS,)).wanted_external((FARM, TENTS)) == FARM


def test_being_furthest_behind_does_not_override_a_bench() -> None:
    """The exact shape of the measured failure: the family that never builds is permanently at
    zero, so the ranking alone would pick it at every flag for the rest of the match."""
    assert Expanding([FARM, FARM, FARM], benched=(TENTS,)).wanted_external((FARM, TENTS)) == FARM


def test_every_family_benched_falls_back_to_the_palette() -> None:
    """None hands the caller back to the plot's own slot 1 - the behaviour from before there was
    a plan, which is the right floor when the plan's own answers are all failing."""
    assert Expanding([], benched=(FARM, TENTS)).wanted_external((FARM, TENTS)) is None


def test_an_outpost_offers_nothing_this_recognises() -> None:
    """An outpost's slot 1 is the argument-less castle claim, which names no template at all and
    so reaches this as an empty offer. Choosing there is not this function's job."""
    assert Expanding([]).wanted_external(("MenFortressCitadel",)) is None
