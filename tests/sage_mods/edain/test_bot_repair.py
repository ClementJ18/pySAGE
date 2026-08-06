"""Getting a rubbled keep back up, which one measured match never managed at all.

A castle keep that falls stands as rubble at zero health, and while it is down the castle can
neither cast a spell nor build anything inside itself - a state severe enough to decide a match
and one that nothing in the loop reports.

Two faults kept it down, and they compound. The gate was priced at an outpost keep's 800 when a
castle keep charges 1000, so the one attempt made was in the band where logic discards the order;
and with no reservation behind it the repair could only spend what recruiting had not already
taken. Measured live, the keep stood in rubble from cycle 283 to cycle 361 - seventy-eight cycles
with no spellcasting and no building inside the castle. The balance did reach the price in the
end, three times, and each time the repair worked; what it never did was climb on purpose.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.economy import Economy
from sage_mods.edain.bot.tuning import REPAIR, SELF_REPAIR_COST


class Repairing:
    """`stage_repair`'s decision, over stub holdings and a stub purse."""

    stage_repair = Economy.stage_repair
    reserve = Economy.reserve
    reserved = Economy.reserved
    spendable = Economy.spendable

    def __init__(
        self,
        gold: int,
        rubble: bool,
        other_reserved: int = 0,
        production: int = 1,
        army: int = 1,
    ) -> None:
        self.gold = gold
        self._reserved: dict[str, int] = {}
        if other_reserved:
            self._reserved["capture"] = other_reserved
        self._rubble = rubble
        self._production = production
        self._army = army
        self.selected: list[object] = []
        self.spent = False
        self.session = SimpleNamespace(start_self_repair=lambda: True)

    def structures(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(is_rubble=self._rubble, object_id=1, template_name="Keep")]

    def production_buildings(self) -> list[object]:
        return [object()] * self._production

    def army(self) -> list[object]:
        return [object()] * self._army

    def _cold(self, key: str) -> bool:
        return False

    def _strike(self, key: str, ok: bool) -> bool:
        return ok

    def select(self, units: list[object]) -> bool:
        self.selected = units
        return True

    def spend(self, label: str, act: object) -> bool:
        self.spent = True
        return True


def test_the_price_is_the_castle_keeps_not_the_outposts() -> None:
    """800 was the outpost figure; a castle keep charges 1000 and discards the order below it."""
    assert SELF_REPAIR_COST == 1000


def test_rubble_reserves_the_repair_price_immediately() -> None:
    """The reservation goes up when the rubble is seen, not when the balance is ready.

    That ordering is the whole fix: the balance never gets there on its own, because every other
    stage spends it first.
    """
    bot = Repairing(gold=100, rubble=True)
    assert bot.stage_repair() is None  # cannot pay yet
    assert bot._reserved[REPAIR] == SELF_REPAIR_COST
    assert bot.spendable() == 0  # and nobody else can see that gold


def test_a_standing_keep_reserves_nothing() -> None:
    """A base with its keep up must not be quietly taxed 1000 for the rest of the match."""
    bot = Repairing(gold=5000, rubble=False)
    assert bot.stage_repair() is None
    assert bot._reserved.get(REPAIR, 0) == 0
    assert bot.spendable() == 5000


def test_the_reservation_is_lifted_once_the_keep_is_back() -> None:
    bot = Repairing(gold=100, rubble=True)
    bot.stage_repair()
    assert bot._reserved[REPAIR] == SELF_REPAIR_COST
    bot._rubble = False
    bot.stage_repair()
    assert bot._reserved[REPAIR] == 0


def test_the_repair_can_spend_the_gold_it_reserved() -> None:
    """`spendable()` subtracts the repair's own promise, so pricing against it can never pay."""
    bot = Repairing(gold=SELF_REPAIR_COST, rubble=True)
    said = bot.stage_repair()
    assert bot.spent is True
    assert said is not None and "repair" in said


def test_it_still_waits_when_someone_elses_promise_blocks_it() -> None:
    """Its own reservation is excluded; a capture's is not, and that one it must respect."""
    bot = Repairing(gold=SELF_REPAIR_COST, rubble=True, other_reserved=400)
    assert bot.stage_repair() is None
    assert bot.spent is False


def test_a_base_that_cannot_fight_stops_banking() -> None:
    """The deadlock that lost a match: 875 gold, 1200 reserved, `spendable` zero, army zero.

    An unbounded promise against a balance that is not growing is a freeze, not a promise - the
    bot could not recruit a single battalion while its base was taken apart, and the gold it was
    saving guaranteed it never could. The reservation drops when there is nothing standing to
    defend the keep or to rebuild it.
    """
    bot = Repairing(gold=875, rubble=True, other_reserved=200, production=0, army=0)
    assert bot.stage_repair() is None
    assert bot._reserved.get(REPAIR, 0) == 0
    assert bot.spendable() == 675  # spendable again, rather than frozen at zero


def test_losing_only_the_army_is_enough_to_stop_banking() -> None:
    bot = Repairing(gold=875, rubble=True, production=3, army=0)
    bot.stage_repair()
    assert bot._reserved.get(REPAIR, 0) == 0


def test_a_stripped_base_still_repairs_when_it_can_genuinely_pay() -> None:
    """Banking is what gets bounded, not repairing - the keep is still wanted back."""
    bot = Repairing(gold=SELF_REPAIR_COST + 50, rubble=True, production=0, army=0)
    said = bot.stage_repair()
    assert bot.spent is True
    assert said is not None
