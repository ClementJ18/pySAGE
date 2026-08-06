"""Riding through a battalion instead of walking up to it.

Two decisions, and the second is the one that is easy to get wrong. **Which targets** take a
charge is `World.can_trample`, and it is the engine's own crush arithmetic plus one refusal -
`PIKE`. The arithmetic does not cover it: the charge lands, and what punishes it is the crushed
unit's `CrushRevengeWeapon` bill afterwards. See the constant for why that bill is not readable
as a threshold and the flag stays.

**When the order is sent** is `Orders.charging`, and there the failure to avoid is issuing the
attack on the cycle after the move: that cancels the charge and the horse arrives at a walk,
which is exactly the behaviour the trample exists to replace.
"""

from __future__ import annotations

import time

from sage_live.api.observation import GameObject, Vec3
from sage_mods.edain.bot.orders import Orders, _beyond, _centre
from sage_mods.edain.bot.tuning import TRAMPLE_OVERSHOOT, TRAMPLE_RUNUP, TRAMPLE_SECONDS
from sage_mods.edain.bot.world import World


class FakeStatics:
    """The three questions a charge asks of the ini, answered from two small tables."""

    def __init__(
        self,
        crusher: dict[str, int],
        crushable: dict[str, int],
        pikes: set[str],
        revenge: dict[str, float] | None = None,
    ) -> None:
        self._crusher = crusher
        self._crushable = crushable
        self._pikes = {p.lower() for p in pikes}
        self._revenge = revenge or {}

    def crusher_level(self, template: str) -> int:
        return self._crusher.get(template, 0)

    def crushable_level(self, template: str) -> int:
        return self._crushable.get(template, 0)

    def crush_resisted(self, template: str) -> int:
        return 0

    def crushes(self, attacker: str, defender: str) -> bool:
        level = self.crusher_level(attacker)
        return level > 0 and level > self.crushable_level(defender)

    def has_kind(self, template: str, *flags: str) -> bool:
        return "PIKE" in flags and template.lower() in self._pikes

    def crush_revenge_multiple(self, template: str) -> float:
        return self._revenge.get(template, 0.0)

    def fighting_template(self, template: str) -> str:
        return template


class FakeSession:
    """Records what was ordered, which is the whole of what these tests check."""

    def __init__(self) -> None:
        self.selected: list[list[int]] = []
        self.moves: list[Vec3] = []

    def select(self, ids: list[int]) -> bool:
        self.selected.append(list(ids))
        return True

    def move(self, position: Vec3) -> bool:
        self.moves.append(position)
        return True


class Charging:
    """`charging` and `can_trample` over stub state - no session, no ini tree, no match."""

    charging = Orders.charging
    can_trample = World.can_trample
    role = World.role

    def __init__(self, statics: FakeStatics) -> None:
        self.statics = statics
        self.session = FakeSession()
        self._charge_target: dict[str, int] = {}
        self._charged: dict[str, float] = {}

    def select(self, force: list[GameObject]) -> bool:
        return self.session.select([o.object_id for o in force])

    def manoeuvre(self, label: str, act, units: list[GameObject]) -> bool:
        act()
        return True


def unit(object_id: int, template: str, position: Vec3) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name=template,
        template_side="Men",
        position=position,
        angle=0.0,
        health=1.0,
        max_health=100.0,
        owner_index=1,
    )


KNIGHTS = "GondorKnightHorde"
SWORDS = "GondorFighterHorde"
PIKES = "MordorPikemanHorde"
CATAPULT = "MordorCatapult"


def board() -> Charging:
    return Charging(
        FakeStatics(
            crusher={KNIGHTS: 1},
            crushable={KNIGHTS: 3, CATAPULT: 2, SWORDS: 0, PIKES: 0},
            pikes={PIKES},
        )
    )


def horse(count: int = 2, at: float = 0.0) -> list[GameObject]:
    return [unit(i, KNIGHTS, (at, 0.0, 0.0)) for i in range(1, count + 1)]


def enemy(template: str, distance: float) -> GameObject:
    return unit(99, template, (distance, 0.0, 0.0))


def test_horses_charge_foot_soldiers() -> None:
    bot = board()
    said = bot.charging(horse(), enemy(SWORDS, 600.0), "cav")
    assert said is not None
    assert bot.session.moves, "a charge is a move order, and nothing else makes it one"


def test_the_charge_is_aimed_past_the_target_not_at_it() -> None:
    """Aimed at the target's own position the horse arrives and halts, which is the stationary
    fight again with extra steps."""
    bot = board()
    target = enemy(SWORDS, 600.0)
    bot.charging(horse(), target, "cav")
    (aimed,) = bot.session.moves
    assert aimed[0] > target.position[0], "the ride-through must end on the far side"
    assert aimed[0] - target.position[0] == TRAMPLE_OVERSHOOT


def test_cavalry_is_not_charged() -> None:
    """`CrushableLevel` rules out every mounted battalion in the tree without naming one."""
    bot = board()
    assert bot.charging(horse(), enemy(KNIGHTS, 600.0), "cav") is None
    assert not bot.session.moves


def test_siege_is_not_charged() -> None:
    bot = board()
    assert bot.charging(horse(), enemy(CATAPULT, 600.0), "cav") is None


def test_pikes_are_not_charged_even_though_the_arithmetic_allows_it() -> None:
    """`CrushableLevel = 0` says the crush lands, and it does - that is the point. What makes it a
    bad trade is the `CrushRevengeWeapon` bill afterwards, which the crush arithmetic knows
    nothing about - so the arithmetic alone would ride the horse into the one matchup it loses."""
    bot = board()
    pikes = enemy(PIKES, 600.0)
    assert bot.statics.crushes(KNIGHTS, PIKES), "the fake must reproduce the trap, not dodge it"
    assert bot.charging(horse(), pikes, "cav") is None


def test_a_mixed_force_does_not_charge() -> None:
    """The order goes to the whole selection, so one battalion that cannot crush is one
    battalion walking past the enemy and starting its own fight late."""
    bot = board()
    force = [*horse(), unit(3, SWORDS, (0.0, 0.0, 0.0))]
    assert bot.charging(force, enemy(SWORDS, 600.0), "cav") is None


def test_there_is_no_charge_from_a_standing_start() -> None:
    """A crush is a momentum check - every crusher carries a `MinCrushVelocityPercent` - so a
    charge begun on top of the enemy flattens nothing and is a move order away from a fight."""
    bot = board()
    assert bot.charging(horse(), enemy(SWORDS, TRAMPLE_RUNUP - 1.0), "cav") is None
    assert not bot.session.moves


def test_a_running_charge_is_not_re_ordered() -> None:
    """The failure this exists to prevent: an attack on the next cycle cancels the move and the
    horse finishes its approach at a walk."""
    bot = board()
    target = enemy(SWORDS, 600.0)
    assert bot.charging(horse(), target, "cav") is not None
    said = bot.charging(horse(), target, "cav")
    assert said is not None, "still charging - the caller must not fall through and attack"
    assert len(bot.session.moves) == 1


def test_the_charge_ends_and_hands_the_fight_back() -> None:
    """One trample per commitment. Once the ride-through has had its seconds the caller is told
    nothing, which is how the party turns and fights where the charge left it."""
    bot = board()
    target = enemy(SWORDS, 600.0)
    bot.charging(horse(), target, "cav")
    bot._charged["cav"] = time.monotonic() - TRAMPLE_SECONDS - 1.0
    assert bot.charging(horse(), target, "cav") is None
    assert len(bot.session.moves) == 1, "and it does not charge the same target again"


def test_a_new_target_gets_its_own_charge() -> None:
    bot = board()
    bot.charging(horse(), enemy(SWORDS, 600.0), "cav")
    bot._charged["cav"] = time.monotonic() - TRAMPLE_SECONDS - 1.0
    fresh = unit(100, SWORDS, (700.0, 0.0, 0.0))
    assert bot.charging(horse(), fresh, "cav") is not None
    assert len(bot.session.moves) == 2


def test_the_run_is_extended_along_the_line_the_force_is_already_on() -> None:
    start: Vec3 = (0.0, 0.0, 0.0)
    through: Vec3 = (0.0, 100.0, 50.0)
    assert _beyond(start, through, 200.0) == (0.0, 300.0, 50.0)


def test_a_run_with_nowhere_to_go_answers_the_target() -> None:
    """Guarded rather than relied on - `TRAMPLE_RUNUP` has already refused this case - but a
    divide by zero in the middle of a match is not an acceptable way to find that out."""
    same: Vec3 = (10.0, 10.0, 0.0)
    assert _beyond(same, same, 200.0) == same


def test_the_run_starts_from_where_the_party_actually_is() -> None:
    force = [unit(1, KNIGHTS, (0.0, 0.0, 0.0)), unit(2, KNIGHTS, (100.0, 200.0, 0.0))]
    assert _centre(force) == (50.0, 100.0, 0.0)


def test_a_high_revenge_multiple_refuses_the_charge_without_the_flag() -> None:
    """The second clause, for the unit nobody tagged. `MordorFighterHorde` is not a pike and the
    fake does not list it as one - a 4.0 multiplier is the only thing saying do not ride it."""
    bot = Charging(
        FakeStatics(
            crusher={KNIGHTS: 1},
            crushable={KNIGHTS: 3, CATAPULT: 2, SWORDS: 0, PIKES: 0},
            pikes=set(),
            revenge={PIKES: 4.0},
        )
    )
    assert bot.charging(horse(), enemy(PIKES, 600.0), "cav") is None


def test_an_ordinary_multiple_still_charges() -> None:
    """Every non-pike in the tree reads exactly 2.0, so 2.0 must not refuse anything - or the
    clause would ban charging the swordsmen cavalry exists to ride down."""
    bot = Charging(
        FakeStatics(
            crusher={KNIGHTS: 1},
            crushable={KNIGHTS: 3, CATAPULT: 2, SWORDS: 0, PIKES: 0},
            pikes=set(),
            revenge={SWORDS: 2.0},
        )
    )
    assert bot.charging(horse(), enemy(SWORDS, 600.0), "cav") is not None
