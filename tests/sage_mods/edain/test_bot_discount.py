"""The price the engine charges, which is not the price the ini quotes.

Edain prices most of its economy through `CostModifierUpgrade` rather than through `BuildCost`,
and a bot reading only the quote refuses spends it can afford - by up to 30% on exactly the elite
units and the `CPObject` a built-up base exists to buy. Measured live: a citadel guard quoted at
600 is charged 420 in a base with six town houses.

These cover the arithmetic and, more importantly, the direction of every uncertainty. Getting a
price too high costs a delayed order; getting one too low sends an order logic discards in
silence, which is the failure `afford` exists to prevent and which is indistinguishable from a
malformed one.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_live.utils.statics import CostLadder
from sage_mods.edain.bot.world import World

# The shipped shape, verified against `GondorWohnhaus01` and `GondorForgeDiscountPing`: six rungs,
# reached by owning one through six of the carrier.
SHIPPED = (0.0, -0.1, -0.15, -0.2, -0.25, -0.3)


class Priced(World):
    """`charged_cost` over stub holdings, with the ini replaced by a table of ladders."""

    def __init__(self, owned: dict[str, int], ladders: tuple[CostLadder, ...], quoted: int) -> None:
        self._owned = owned
        self.statics = _Statics(ladders, quoted)

    @property
    def observation(self) -> SimpleNamespace:
        return SimpleNamespace(
            mine=[
                SimpleNamespace(template_name=name)
                for name, count in self._owned.items()
                for _ in range(count)
            ]
        )


class _Statics:
    def __init__(self, ladders: tuple[CostLadder, ...], quoted: int) -> None:
        self._ladders = ladders
        self._quoted = quoted

    def same_building(self, template: str) -> frozenset[str]:
        return frozenset({template.lower()})

    def build_cost(self, template: str) -> int:
        return self._quoted

    def upgrade_cost(self, upgrade: str) -> int:
        return self._quoted

    def ladders_for_template(self, template: str) -> tuple[CostLadder, ...]:
        return tuple(lad for lad in self._ladders if lad.covers_template(template))

    def ladders_for_upgrade(self, upgrade: str) -> tuple[CostLadder, ...]:
        return tuple(lad for lad in self._ladders if lad.covers_upgrade(upgrade))


def _houses(count: int, quoted: int = 600) -> Priced:
    ladder = CostLadder("house", SHIPPED, templates=frozenset({"guard"}))
    return Priced({"house": count}, (ladder,), quoted)


def test_rate_is_indexed_by_count_and_saturates_at_both_ends() -> None:
    ladder = CostLadder("house", SHIPPED)
    assert ladder.rate(0) == 0.0  # owning none is no discount, not the first rung
    assert ladder.rate(1) == 0.0
    assert ladder.rate(6) == -0.3
    assert ladder.rate(7) == -0.3  # a seventh cannot improve on the sixth
    assert ladder.rate(99) == -0.3


def test_empty_ladder_never_discounts() -> None:
    assert CostLadder("house", ()).rate(6) == 0.0


def test_the_measured_citadel_guard_price() -> None:
    """600 quoted, 420 charged behind six houses - the number this was written from."""
    assert _houses(6).charged_cost("guard") == 420
    assert _houses(0).charged_cost("guard") == 600
    assert _houses(3).charged_cost("guard") == 510


def test_a_template_outside_the_filter_pays_the_quote() -> None:
    """The town house marks down elites, not the basic infantry that fills an army."""
    assert _houses(6).charged_cost("fighter") == 600


def test_an_unowned_carrier_contributes_nothing() -> None:
    """A ladder whose building does not stand is not a discount waiting to happen.

    It is also not a reason to abandon the ladders that *do* stand, which is the trap: an unowned
    carrier sits at rung zero, so folding it in with the others would drag every price back to the
    quote.
    """
    standing = CostLadder("house", SHIPPED, templates=frozenset({"guard"}))
    absent = CostLadder("arnor_house", SHIPPED, templates=frozenset({"guard"}))
    priced = Priced({"house": 6}, (standing, absent), 600)
    assert priced.charged_cost("guard") == 420


def test_overlapping_ladders_take_the_least_generous() -> None:
    """Two carriers standing, and no evidence about how the engine stacks them.

    Guessing that they compound would under-price the order, which is the one direction that
    fails silently - so the smaller markdown wins until something measures the real rule.
    """
    deep = CostLadder("house", SHIPPED, templates=frozenset({"guard"}))
    shallow = CostLadder("statue", (0.0, -0.05), templates=frozenset({"guard"}))
    priced = Priced({"house": 6, "statue": 2}, (deep, shallow), 600)
    assert priced.charged_cost("guard") == 570  # -5%, not -30% and not -35%


def test_upgrades_are_priced_off_their_own_ladders() -> None:
    ladder = CostLadder("forge", SHIPPED, upgrades=frozenset({"upgrade_heavyarmor"}))
    priced = Priced({"forge": 6}, (ladder,), 300)
    assert priced.charged_upgrade_cost("Upgrade_HeavyArmor") == 210
    assert priced.charged_upgrade_cost("Upgrade_Something_Else") == 300


def test_a_free_template_stays_free() -> None:
    """`build_cost` answers 0 for a template this tree does not price, and 0 discounted is 0."""
    assert _houses(6, quoted=0).charged_cost("guard") == 0
