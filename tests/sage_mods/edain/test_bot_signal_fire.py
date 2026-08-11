"""Gondor's signal fire: reading a charge count off a template name, and spending it.

The mechanic has no counter and no queue. A rider's charges are its template - `ErrandRider6` is
six charges - and the units are special powers costing 2, 3 or 8 of them. Both halves of that are
easy to get wrong in ways nothing reports: a template misread is a rider the bot thinks is broke,
and a summon sent through the wrong cast constructor is accepted and silently discarded.

`test_bot_external_economy` covers the other faction-specific reading of a live template. This
one is stricter about the boundaries, because the name is doing arithmetic.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sage_live.api.orders import CAST_SELF
from sage_mods.edain.bot.factions.men.signal_fire import (
    MAX_CHARGES,
    SAVE_FOR,
    SAVE_FROM,
    SECOND_FIRE_EXTERNAL,
    SUMMONS,
    SignalFire,
    affordable,
    best_summon,
    charges_of,
    role_wait,
)

# The four fiefdoms bucketed the way `World.role_of` buckets them, read off the tree: Ring Vale's
# swordsmen and Lossarnach's axes are both plain `INFANTRY`, Pelargir's spearmen carry `PIKE` on
# top of it and Morthond's bowmen carry `ARCHER`. **That the two-charge summons are both infantry
# is the entire shape of this mechanic's problem** - a rider that spends the moment it can afford
# something can only ever buy infantry.
ROLES = {
    "RingValeSwordsmanHorde": "INFANTRY",
    "LehenLossarnachAxteHorde": "INFANTRY",
    "MorthondBowmenHorde": "ARCHER",
    "PelegirSpearmenHorde": "PIKE",
    "RingValeSwordsmanHorde_Veteranen": "INFANTRY",
    "LehenLossarnachAxteHorde_Veteranen": "INFANTRY",
    "MorthondBowmenHorde_Veteranen": "ARCHER",
    "PelegirSpearmenHorde_Veteranen": "PIKE",
    "GondorFighterHorde": "INFANTRY",
    "GondorSpearmanHorde": "PIKE",
    "GondorArcherHorde": "ARCHER",
    "GondorKnightHorde": "CAVALRY",
}


def _rider(object_id: int, charges: int, x: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=f"ErrandRider{charges}",
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


def _fire(object_id: int, x: float) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id, template_name="GondorLeuchtfeuer", position=(x, 0.0, 0.0)
    )


# The shipped charges, verified against the tree: a fiefdom battalion is 60 points and Morthond's
# bowmen 90. Every summon recruits **two** of its battalion, so the order costs twice these;
# Lehen recruits one of each fiefdom instead, for 270.
CP = {
    "RingValeSwordsmanHorde": 60,
    "LehenLossarnachAxteHorde": 60,
    "MorthondBowmenHorde": 90,
    "PelegirSpearmenHorde": 60,
    "RingValeSwordsmanHorde_Veteranen": 60,
    "LehenLossarnachAxteHorde_Veteranen": 60,
    "PelegirSpearmenHorde_Veteranen": 60,
    "MorthondBowmenHorde_Veteranen": 90,
}
LEHEN_CP = 270


class Fires(SignalFire):
    """`stage_signal_fire` over stub holdings, recording what it tried to cast."""

    def __init__(
        self,
        owned: list,
        side: str = "Men",
        selectable: bool = True,
        free_points: int | None = 9999,
        spends: bool = True,
        fielded: tuple[str, ...] = (),
        mix: dict[str, float] | None = None,
    ) -> None:
        self._owned = owned
        self.side = side
        self._selectable = selectable
        self._free = free_points
        # The army as templates, and the mix the plan wants - the two halves `role_needs` joins.
        # Both empty by default, which is the state that has no opinion and leaves every summon
        # ranked by the table exactly as it was before there was a balance at all.
        self._fielded = fielded
        self._mix = mix or {}
        self.cast: list[tuple] = []
        self.reported: list[bool] = []
        # Whether the engine actually spends the charges. False reproduces the wrong-constructor
        # failure: the order is accepted, the rider keeps its charges, and nothing happens.
        self.spends = spends
        self.session = SimpleNamespace(cast=self._cast, confirm=self._confirm)
        self.statics = SimpleNamespace(command_point_cost=lambda name: CP.get(name, 0))

    @property
    def observation(self) -> SimpleNamespace:
        me = None if self._free is None else SimpleNamespace(command_points_free=self._free)
        return SimpleNamespace(mine=self._owned, me=me)

    def _cast(self, power, form, position, source_id=0):
        self.cast.append((power, form, position, source_id))
        return True

    def _confirm(self, changed, timeout=0.0) -> bool:
        return bool(changed(self._after()))

    def _after(self) -> SimpleNamespace:
        """The board once the engine has - or has not - spent the charges.

        **The rider is replaced, not edited**, so the stand-in gives the new one a new id too:
        that is what the live game does, and a confirmation that survives it is the whole point.
        """
        after = []
        for owned in self._owned:
            charges = charges_of(owned.template_name)
            if charges is None or not self.spends:
                after.append(owned)
                continue
            after.append(
                SimpleNamespace(
                    object_id=owned.object_id + 1000,
                    template_name=f"ErrandRider{max(0, charges - 2)}",
                    position=owned.position,
                    distance_to=owned.distance_to,
                )
            )
        return SimpleNamespace(mine=after)

    def select(self, objects) -> bool:
        return self._selectable

    def _issue(self, label, act):
        return act()

    def _report(self, label, ok, good, bad) -> bool:
        self.reported.append(ok)
        return ok

    def role_of(self, template: str) -> str:
        return ROLES.get(template, "INFANTRY")

    def army(self) -> list:
        return [
            SimpleNamespace(object_id=9000 + i, template_name=t)
            for i, t in enumerate(self._fielded)
        ]

    def heroes(self) -> list:
        return []

    def wanted_mix(self) -> dict[str, float]:
        return self._mix


def test_the_template_name_is_the_charge_count() -> None:
    """There is no counter anywhere. `ErrandRider0` is a rider with nothing to spend and
    `ErrandRider14` is one at the cap, and the only difference is the digits."""
    assert charges_of("ErrandRider0") == 0
    assert charges_of("ErrandRider7") == 7
    assert charges_of(f"ErrandRider{MAX_CHARGES}") == MAX_CHARGES


def test_the_reading_is_case_insensitive() -> None:
    """A live observation spells a template however the engine registered it, which is not
    always how the ini declares it."""
    assert charges_of("errandrider3") == 3
    assert charges_of("ERRANDRIDER3") == 3


def test_something_that_is_not_a_rider_is_not_a_charge_count() -> None:
    """The prefix test is a name test, and name tests are the trap this whole mechanic is made
    of - see the ranger tents' `...DiscountPing` for the same shape one folder over."""
    assert charges_of("GondorFighterHorde") is None
    assert charges_of("ErrandRiderInterface") is None
    assert charges_of("ErrandRider") is None
    assert charges_of("ErrandRider2Extra") is None


def test_what_two_charges_buys() -> None:
    """`GondorErrandRiderCommandset1` opens at two charges with exactly these two."""
    assert [s.charges for s in affordable(2)] == [2, 2]


def test_nothing_is_affordable_below_the_cheapest() -> None:
    """Charges 0 and 1 are a rider that can do nothing but keep accruing."""
    assert affordable(0) == ()
    assert affordable(1) == ()


def test_the_costs_match_the_command_sets_that_gate_them() -> None:
    """The ini states each cost twice - as a `ChainedButton` deduction and as the charge level
    whose command set enables the button. This pins the table to the pair that agreed."""
    assert sorted({s.charges for s in SUMMONS}) == [2, 3, 8]


def test_only_lehen_summons_veterans() -> None:
    """Which is the entire argument for ever saving instead of spending."""
    assert [s.veteran for s in SUMMONS] == [False, False, False, False, True]
    assert len(SAVE_FOR.spawns) == 4


def test_a_poor_rider_spends_what_it_has() -> None:
    """Early on, Lehen is ten minutes away and a battalion now is worth more than a better
    battalion later."""
    assert best_summon(2).charges == 2
    assert best_summon(3).charges == 3
    assert best_summon(5).charges == 3


def test_a_rider_close_to_lehen_holds() -> None:
    """The case where the stage deliberately buys nothing. Spending here would reset a wait
    that is nearly over, and it is the only reason `best_summon` can answer None with charges
    in hand."""
    assert best_summon(SAVE_FROM) is None
    assert best_summon(SAVE_FOR.charges - 1) is None


def test_lehen_is_taken_the_moment_it_is_affordable() -> None:
    """Saving past eight buys nothing at all - the command set at 14 offers what the one at 8
    offers - so the wait ends exactly when it is paid for."""
    assert best_summon(SAVE_FOR.charges) is SAVE_FOR
    assert best_summon(MAX_CHARGES) is SAVE_FOR


def test_the_richest_rider_is_answered_first() -> None:
    """Two signal fires is two riders accruing independently. The fuller one is both nearer to
    Lehen and nearer to the cap, where further charges are simply lost."""
    poor, rich = _rider(1, 2), _rider(2, 9)
    assert Fires([poor, rich]).signal_fire_riders()[0][0] is rich


def test_a_summon_names_the_rider_as_its_source() -> None:
    """The cast is fired *by* the rider, and an order that leaves the source at 0 is taken by
    the stream and discarded by logic in silence - the lesson `Session.cast` records about
    spellbook powers, which applies to every object-sourced cast."""
    rider, fire = _rider(77, 3, x=0.0), _fire(78, x=300.0)
    fires = Fires([rider, fire])
    fires.stage_signal_fire()
    (power, form, position, source_id) = fires.cast[0]
    assert source_id == 77
    # The rider casts; the building is what the cast is pointed at. Two different objects, and
    # sending either one in the other's slot is discarded without a word.
    assert position == fire.position


def test_the_cast_is_aimed_at_the_signal_fire() -> None:
    """The building is what recruits, so aiming is about reaching it - `StartAbilityRange` is
    400 - and not about placing troops, which arrive at the building's exit regardless."""
    rider, fire = _rider(1, 3, x=5000.0), _fire(2, x=100.0)
    assert Fires([rider, fire]).signal_fire_target(rider) == fire.position


def test_the_nearest_signal_fire_is_the_one_aimed_at() -> None:
    """Two signal fires is two riders, and a rider that walks to the far one crosses the map to
    reach a building identical to the one beside it."""
    rider = _rider(1, 3, x=0.0)
    near, far = _fire(2, x=200.0), _fire(3, x=9000.0)
    assert Fires([rider, far, near]).signal_fire_target(rider) == near.position


def test_a_rider_that_outlived_its_building_falls_back_to_itself() -> None:
    """A guess, and documented as one. The building razed while the rider lives is a state the
    mechanic has nothing useful to do with, so it must not crash on the way to finding out."""
    rider = _rider(1, 3, x=5000.0)
    assert Fires([rider]).signal_fire_target(rider) == rider.position


def test_a_failed_selection_sends_nothing() -> None:
    """Every order here acts on the selection. Casting into whatever was selected last is worse
    than not casting."""
    fires = Fires([_rider(1, 3)], selectable=False)
    fires.stage_signal_fire()
    assert fires.cast == []


def test_the_stage_is_inert_off_faction() -> None:
    """The mechanic lives in the generic loop, so a Mordor run must pay one comparison and
    nothing else - including on a map that somehow contains a rider."""
    fires = Fires([_rider(1, 9)], side="Mordor")
    assert fires.stage_signal_fire() is None
    assert fires.cast == []


def test_a_seat_with_no_rider_does_nothing() -> None:
    """The signal fire is optional. Most Men runs never build one."""
    fires = Fires([SimpleNamespace(object_id=1, template_name="GondorFighterHorde")])
    assert fires.stage_signal_fire() is None


def test_holding_reports_rather_than_going_quiet(capsys) -> None:
    """A stage that returns None reads as "nothing to do" in the log. Saving is a decision and
    says so, with how much longer it intends to wait."""
    line = Fires([_rider(1, SAVE_FROM)]).stage_signal_fire()
    assert line is not None and "saving" in line


@pytest.mark.parametrize("charges", range(MAX_CHARGES + 1))
def test_no_charge_count_ever_overspends(charges: int) -> None:
    """The one invariant that must hold at every rung: a summon the rider cannot pay for is a
    cast the engine accepts, charges nothing for, and silently drops."""
    summon = best_summon(charges)
    assert summon is None or summon.charges <= charges


# A plan that wants a third of each of the three roles a fiefdom can fill. Real mixes are messier
# - `MenOfTheWestArmy` phase 1 is roughly 37% infantry, 31% archers, 26% pikes, 5% horse - but the
# arithmetic under test is "which role is furthest below its share", and an even target makes the
# answer a statement about the *army* rather than about the plan.
EVEN = {"GondorFighterHorde": 1 / 3, "GondorArcherHorde": 1 / 3, "GondorSpearmanHorde": 1 / 3}


def test_the_summon_answers_the_role_the_army_is_short_of() -> None:
    """The whole point of the change. An army of nothing but swordsmen wants bows and spears, and
    which of the two it wants more is a question about the army rather than about the table."""
    swords = ("GondorFighterHorde",) * 6
    fires = Fires([_rider(1, 3), _fire(2, 300.0)], fielded=swords, mix=EVEN)
    fires.stage_signal_fire()
    assert fires.cast and fires.cast[0][0].endswith(("Morthond", "Pelagir"))


def test_a_wall_of_archers_is_answered_with_spears_not_more_archers() -> None:
    """The same rule pointed the other way, which is what makes it a balance and not a preference
    for the three-charge summons."""
    bows = ("GondorArcherHorde",) * 6
    fires = Fires([_rider(1, 3), _fire(2, 300.0)], fielded=bows, mix=EVEN)
    fires.stage_signal_fire()
    assert fires.cast and fires.cast[0][0].endswith("Pelagir")


def test_infantry_is_taken_when_infantry_is_what_is_missing() -> None:
    """A party wiped out down to its bows and spears is the case the two-charge summons are for,
    and the rider must not sit on its charges waiting for a role it already has."""
    ranged = ("GondorArcherHorde",) * 3 + ("GondorSpearmanHorde",) * 3
    fires = Fires([_rider(1, 2), _fire(2, 300.0)], fielded=ranged, mix=EVEN)
    fires.stage_signal_fire()
    assert fires.cast and fires.cast[0][0].endswith(("RingVale", "Lossarnach"))


def test_a_rider_holds_one_charge_for_a_role_two_charges_cannot_buy() -> None:
    """**The failure this whole change exists for.** Both two-charge summons are infantry, so a
    rider that spends the moment it can afford anything resets to zero at two every time and never
    reaches the bows and the spears at all. A measured match ended `summon LehenLossarn 3/3` -
    three summons, all of them the same axes. One charge of patience is what unlocks the rest."""
    swords = ("GondorFighterHorde",) * 6
    fires = Fires([_rider(1, 2), _fire(2, 300.0)], fielded=swords, mix=EVEN)
    line = fires.stage_signal_fire()
    assert fires.cast == []
    assert line is not None and "holding one more" in line


def test_the_wait_is_one_charge_and_not_a_second_save_for_lehen() -> None:
    """Patience bounded at `charges + 1`. Past three there is nothing between the fiefdoms and
    Lehen's eight, so a rider at three spends rather than starting a five-charge wait it was never
    asked for."""
    swords = ("GondorFighterHorde",) * 6
    needs = Fires([], fielded=swords, mix=EVEN).role_needs()
    fires = Fires([], fielded=swords, mix=EVEN)
    assert role_wait(2, fires.summon_fits, lambda s: fires.summon_balance(s, needs)) is not None
    assert role_wait(3, fires.summon_fits, lambda s: fires.summon_balance(s, needs)) is None


def test_no_wait_when_the_roles_are_already_even() -> None:
    """`ROLE_PATIENCE` is what keeps this from being a hold on every cycle. An army already at its
    intended shape has no role that is worth 75 seconds, so the rider spends."""
    even = ("GondorFighterHorde", "GondorArcherHorde", "GondorSpearmanHorde")
    fires = Fires([_rider(1, 2), _fire(2, 300.0)], fielded=even, mix=EVEN)
    fires.stage_signal_fire()
    assert fires.cast


def test_an_army_with_nothing_in_it_falls_back_to_the_table() -> None:
    """No producers and no battalions is no opinion, and a preference invented out of an empty
    census would be worse than the arbitrary one it replaced."""
    assert Fires([]).role_needs() == {}
    assert Fires([]).summon_balance(SUMMONS[0], {}) == 0.0


def test_heroes_are_not_counted_into_the_balance() -> None:
    """They are in `army()` deliberately, and no `ArmyDefinition` lists one - so counting them
    puts a body in a role that asked for none and tilts every summon away from it."""
    fires = Fires([], fielded=("GondorFighterHorde",), mix=EVEN)
    with_hero = Fires([], fielded=("GondorFighterHorde", "GondorKnightHorde"), mix=EVEN)
    with_hero.heroes = lambda: [SimpleNamespace(object_id=9001)]
    assert fires.role_needs() == with_hero.role_needs()


def test_every_summon_recruits_a_pair() -> None:
    """The count is not visible in the OCL - it lists the type once - so it is stated here, and
    it is what makes the price a sum. Lehen is the exception: four, one of each fiefdom."""
    assert [len(s.spawns) for s in SUMMONS] == [2, 2, 2, 2, 4]
    assert len(set(SAVE_FOR.spawns)) == 4


def test_a_summon_is_priced_for_every_battalion_it_recruits() -> None:
    """Halving this is the failure mode: a guard reading only the first entry lets a 120-point
    order through on 60 points of headroom, and the engine queues nothing."""
    assert Fires([]).summon_command_points(SUMMONS[0]) == 120
    assert Fires([]).summon_command_points(SAVE_FOR) == LEHEN_CP


def test_a_summon_the_ceiling_has_no_room_for_is_not_sent() -> None:
    """The bug this guard exists for. The engine takes the cast, spends the charges, queues no
    troops and reports nothing - so the charges are gone and there is nothing to show for it."""
    fires = Fires([_rider(1, 3)], free_points=10)
    fires.stage_signal_fire()
    assert fires.cast == []


def test_a_cheaper_summon_is_taken_when_the_expensive_one_will_not_fit() -> None:
    """Morthond's pair is 180 and Pelargir's 120, both at three charges. With 120 free the
    stage should buy the pair that fits rather than stall on the pair that does not."""
    fires = Fires([_rider(1, 3)], free_points=120)
    fires.stage_signal_fire()
    assert fires.cast and fires.cast[0][0].endswith("Pelagir")


def test_lehen_waits_for_the_ceiling_rather_than_being_nibbled_away() -> None:
    """Blocked on points rather than charges, spending them on a fiefdom would reset a ten-minute
    wait to buy a pair. `stage_command_points` raises the ceiling; this waits for it."""
    fires = Fires([_rider(1, SAVE_FOR.charges)], free_points=120)
    fires.stage_signal_fire()
    assert fires.cast == []


def test_at_the_charge_cap_it_stops_waiting() -> None:
    """At 14 the wait has become pure loss - a charge every 75 seconds falling on the floor - so
    the best thing that does fit gets bought."""
    fires = Fires([_rider(1, MAX_CHARGES)], free_points=120)
    fires.stage_signal_fire()
    assert fires.cast and fires.cast[0][0].endswith("Pelagir")


def test_lehen_goes_out_the_moment_the_ceiling_allows_it() -> None:
    """The guard must not become a second reason never to cast the good one."""
    fires = Fires([_rider(1, SAVE_FOR.charges)], free_points=LEHEN_CP)
    fires.stage_signal_fire()
    assert fires.cast and fires.cast[0][0].endswith("Lehen")


def test_being_short_of_points_reads_differently_from_being_short_of_charges() -> None:
    """Two different holds. One resolves itself with time; the other means the ceiling is not
    keeping up, and a log that spells them the same way hides the second behind the first."""
    charge_bound = Fires([_rider(1, SAVE_FROM)], free_points=9999).stage_signal_fire()
    point_bound = Fires([_rider(1, SAVE_FOR.charges)], free_points=10).stage_signal_fire()
    assert "saving" in charge_bound
    assert "command points" in point_bound and "10 are free" in point_bound


def test_an_unreadable_ceiling_does_not_disable_the_stage() -> None:
    """The reading is the guard, not the mechanic. No player state is no opinion, which is what
    `stage_recruit` does with the same missing value."""
    fires = Fires([_rider(1, 3)], free_points=None)
    fires.stage_signal_fire()
    assert fires.cast


FIRE = "GondorLeuchtfeuer"
# `GondorEconomyPlotCommandSet` in slot order: the farm, the beacon, the ranger tents.
PALETTE = ("GondorFarm_Extern", FIRE, "GondorRangerTents")
WITHOUT_FIRE = ("GondorFarm_Extern", "GondorRangerTents")


def _plot(object_id: int, x: float) -> SimpleNamespace:
    return SimpleNamespace(object_id=object_id, position=(x, 0.0, 0.0), template_name="plot")


class Siting(SignalFire):
    """`signal_fire_site` over stub holdings, an enemy seat and a set of hostiles."""

    def __init__(
        self,
        standing: int = 0,
        hostiles: list | None = None,
        enemy_at: tuple | None = None,
        home: tuple = (0.0, 0.0, 0.0),
        externals: dict[str, int] | None = None,
    ) -> None:
        self._standing = standing
        self._hostiles = hostiles or []
        self._enemy_at = enemy_at
        self._home = home
        # What `external_standing` reports: the farms and the ranger tents, counted per family.
        # An empty opening is the default, which is one fire and only one.
        self._externals = (
            {"GondorFarm_Extern": 0, "GondorRangerTents": 0} if externals is None else externals
        )

    def external_standing(self) -> dict[str, int]:
        return self._externals

    @property
    def observation(self) -> SimpleNamespace:
        return SimpleNamespace(objects=self._hostiles, mine=[])

    def owned_building(self, template: str) -> list:
        return [object()] * self._standing

    def hostile(self, other) -> bool:
        return True

    def enemy(self):
        return None if self._enemy_at is None else (2, self._enemy_at)

    def base_centre(self):
        return self._home


def _hostile(x: float) -> SimpleNamespace:
    return SimpleNamespace(distance_to=lambda point, _x=x: abs(point[0] - _x))


def test_a_quiet_settlement_near_home_gets_the_signal_fire() -> None:
    """The mission: one fire, somewhere it will still be standing when the rider has charges."""
    assert Siting().signal_fire_site(_plot(1, 500.0), PALETTE) == FIRE


def test_one_while_the_map_is_still_being_taken() -> None:
    """400g buys a rider, and against an empty map a second rider is a second trickle for the
    price of two battalions or two farms. One, until the settlements have nothing better to
    carry."""
    assert Siting(standing=1).signal_fire_site(_plot(1, 500.0), PALETTE) is None
    assert Siting(standing=2).signal_fire_site(_plot(1, 500.0), PALETTE) is None


BUILT_OUT = {"GondorFarm_Extern": SECOND_FIRE_EXTERNAL, "GondorRangerTents": SECOND_FIRE_EXTERNAL}


def test_a_second_fire_once_the_settlements_are_built_out() -> None:
    """The opening's argument against a second one expires. A base with four farms and four
    ranger tents is putting its next settlement on a fifth farm whose discount ladder stopped
    improving two buildings ago; a second rider pays a battalion every 75 seconds instead."""
    built = Siting(standing=1, externals=BUILT_OUT)
    assert built.signal_fires_wanted() == 2
    assert built.signal_fire_site(_plot(1, 500.0), PALETTE) == FIRE


def test_a_third_is_still_refused() -> None:
    """Two is a decision about a built-out base, not the removal of the cap."""
    full = Siting(standing=2, externals=BUILT_OUT)
    assert full.signal_fire_site(_plot(1, 500.0), PALETTE) is None


def test_one_family_built_out_is_not_a_built_out_base() -> None:
    """`min` rather than a sum, and this is why: eight farms and one tent is a base that still
    has an obvious better thing to put on a settlement, which is the second tent."""
    lopsided = {"GondorFarm_Extern": 8, "GondorRangerTents": 1}
    assert Siting(standing=1, externals=lopsided).signal_fires_wanted() == 1
    assert Siting(standing=1, externals=lopsided).signal_fire_site(_plot(1, 500.0), PALETTE) is None


def test_a_razed_fire_is_replaced() -> None:
    """The target is one *standing*, not one bought. Losing the only fire ends the mechanic for
    the rest of the match otherwise, and the rider is the entire point of the building - so the
    next settlement that qualifies gets one. Seen live: built on plot 215, razed, reclaimed and
    rebuilt."""
    assert Siting(standing=0).signal_fire_site(_plot(1, 500.0), PALETTE) == FIRE


def test_a_settlement_with_an_enemy_on_it_is_not_safe() -> None:
    """A farm razed has already paid for part of itself; a fire razed before its rider reaches
    two charges has bought nothing at all."""
    contested = Siting(hostiles=[_hostile(600.0)])
    assert contested.signal_fire_site(_plot(1, 500.0), PALETTE) is None


def test_a_settlement_on_the_enemys_side_is_not_safe() -> None:
    """Nearer to them than to us is the definition of the ground that changes hands."""
    forward = Siting(enemy_at=(1000.0, 0.0, 0.0))
    assert forward.signal_fire_site(_plot(1, 900.0), PALETTE) is None
    assert forward.signal_fire_site(_plot(2, 100.0), PALETTE) == FIRE


def test_an_unknown_enemy_does_not_block_the_build() -> None:
    """Under fog the enemy is usually unknown for the whole opening. A plot with nothing visibly
    on it is the best answer available, and refusing until one is scouted means never."""
    assert Siting(enemy_at=None).signal_fire_site(_plot(1, 5000.0), PALETTE) == FIRE


def test_a_palette_without_the_fire_declines() -> None:
    """Outposts, other factions, and any plot whose buttons do not offer one."""
    assert Siting().signal_fire_site(_plot(1, 500.0), WITHOUT_FIRE) is None


def test_the_cast_is_self_targeted() -> None:
    """`CAST_LOCATION` was wrong here for two matches. The button declares no `Options`, so
    `Statics._cast_form` classifies these self-cast, and a cast through the wrong constructor is
    accepted, charged nothing and reported as sent."""
    fires = Fires([_rider(1, 3), _fire(2, 300.0)])
    fires.stage_signal_fire()
    assert fires.cast[0][1] == CAST_SELF


def test_a_summon_that_spends_no_charges_is_not_a_success() -> None:
    """The failure the ledger could not see. 520 summons went out in one match, every one logged
    as sent, and the rider's charge count never moved - so the receipt has to be the charges."""
    fires = Fires([_rider(1, 3), _fire(2, 300.0)], spends=False)
    assert fires.stage_signal_fire() is not None
    assert fires.cast, "the order still goes out - it is the *reporting* that must not lie"
    assert fires.reported == [False]


def test_a_summon_that_spends_charges_is_a_success() -> None:
    """The rider is its own oracle: spending dismounts it down the ladder, so the template name
    is the receipt."""
    fires = Fires([_rider(1, 3), _fire(2, 300.0)], spends=True)
    fires.stage_signal_fire()
    assert fires.reported == [True]


def test_the_confirmation_survives_the_rider_being_replaced() -> None:
    """The bug the first confirmation had. Spending does not edit the rider - the engine destroys
    it and creates the lower rung with a **new object id** (`rider 1276` became `rider 1373`
    live), so looking the old id up finds nothing and reads a summon that worked as one that
    failed. Summing charges across whatever riders exist is immune to that."""
    fires = Fires([_rider(1, 3), _fire(2, 300.0)], spends=True)
    fires.stage_signal_fire()
    after = fires._after()
    assert all(o.object_id != 1 for o in after.mine if charges_of(o.template_name) is not None)
    assert fires.reported == [True]


def test_charges_are_counted_across_every_rider() -> None:
    """Two signal fires is two riders, and nothing says which one the engine rebuilt - so the
    total is the only reading that can tell a spend from a swap."""
    fires = Fires([_rider(1, 3), _rider(2, 5)])
    assert fires.charges_held() == 8
