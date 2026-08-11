"""Readiness and reporting for spellbook powers, both measured wrong in a live run.

The two faults these cover were found the same way, by watching a match: a power the engine's
cooldown table does not mention was treated as ready and fired on the ini's clock, and a buff
with nothing to confirm against was counted as having worked.
"""

from __future__ import annotations

import math
import time

from sage_live.api.observation import GameObject, distance
from sage_live.utils.statics import CastablePower, PowerButton
from sage_mods.edain.bot.ledger import Ledger
from sage_mods.edain.bot.powers import Powers
from sage_mods.edain.bot.tuning import (
    CAST_BACKOFF_CAP,
    CAST_BUILD_CLEARANCE,
    CAST_BUILD_RINGS,
    CAST_SUMMON_CLEARANCE,
    CAST_SUMMON_RINGS,
)


class Readiness:
    """The parts of `Powers` that decide whether a power may fire, over stub state.

    A real `Powers` needs a session, an ini tree and a match; `ready` needs the cooldown table,
    the frame, and its own two dictionaries.
    """

    ready = Powers.ready
    wait_for = Powers.wait_for
    back_off = Powers.back_off

    def __init__(self, cooldowns: dict[str, int], frame: int) -> None:
        self._cooldowns = cooldowns
        self._cast_at: dict[str, float] = {}
        self._cast_wait: dict[str, float] = {}
        self._cast_frame: dict[str, int] = {}
        self.session = _Session(cooldowns)
        self.observation = _Observation(frame)

    def spellbook_id(self) -> int:
        return 1


class _Session:
    def __init__(self, cooldowns: dict[str, int]) -> None:
        self._cooldowns = cooldowns

    def power_cooldowns(self, object_id: int) -> dict[str, int]:
        return dict(self._cooldowns)


class _Observation:
    def __init__(self, frame: int) -> None:
        self.frame = frame


def power(name: str, reload_seconds: float = 180.0) -> CastablePower:
    return CastablePower(
        command_slot=0, button=f"Command_{name}", power=name, reload_seconds=reload_seconds
    )


def test_a_power_the_table_names_is_answered_by_the_engine() -> None:
    spell = power("SpellBookRallyingCall_Gondor")
    recharging = Readiness({spell.power: 900}, frame=800)
    assert not recharging.ready(spell)
    assert Readiness({spell.power: 900}, frame=900).ready(spell)


def test_a_power_the_table_omits_falls_back_to_the_clock() -> None:
    """The measured case: 44 entries answered, none of them the power being cast.

    A `.get` miss used to be indistinguishable from a ready-frame in the past, so three of the
    four powers a live Gondor run cast were fired on the ini's declared recharge.
    """
    spell = power("SpellBookRebuild")
    others = {"SpellBookHealRohan": 1, "SpellBookArrowVolleyArnor": 1}
    book = Readiness(others, frame=10_000)

    # Never cast, so the clock permits it - but on the clock's terms, not the table's.
    assert book.ready(spell)

    book._cast_at[spell.power] = time.monotonic()
    assert not book.ready(spell), (
        "an unmentioned power must not read as ready straight after firing"
    )


def test_a_ready_frame_that_has_not_moved_since_the_last_cast_is_not_permission() -> None:
    """Rallying Call, frozen at 10852 across five casts while the match ran to frame 11360."""
    spell = power("SpellBookRallyingCall_Gondor")
    book = Readiness({spell.power: 10_852}, frame=11_360)
    assert book.ready(spell)

    # The bot casts, and the engine declines it: the frame stays exactly where it was.
    book._cast_frame[spell.power] = 10_852
    book._cast_at[spell.power] = time.monotonic()
    assert not book.ready(spell), "a stalled frame would fire this power every cycle"

    # A cast the engine did accept moves the frame, and the reading is trusted again.
    book.session._cooldowns[spell.power] = 11_400
    assert not book.ready(spell), "the new frame is in the future, so it is still recharging"
    book.observation.frame = 11_400
    assert book.ready(spell)


def test_a_refusal_makes_the_fallback_clock_wait_longer() -> None:
    spell = power("SpellBookRebuild", reload_seconds=180.0)
    book = Readiness({}, frame=0)
    assert book.wait_for(spell) == 180.0

    book.back_off(spell)
    assert book.wait_for(spell) > 180.0, "the declared recharge is what the refusals measured short"

    for _ in range(50):
        book.back_off(spell)
    assert book.wait_for(spell) == 180.0 * CAST_BACKOFF_CAP, "growth has to stop somewhere"


def test_the_ledger_keeps_unverifiable_orders_out_of_the_success_count() -> None:
    ledger = Ledger()
    for _ in range(14):
        ledger.record("cast buff", None)
    assert "14 sent, none of them checkable" in ledger.report()
    assert "14/14 took effect" not in ledger.report()


def test_the_ledger_still_counts_what_it_can_check() -> None:
    ledger = Ledger()
    ledger.record("cast heal", True)
    ledger.record("cast heal", False)
    ledger.record("cast heal", None)
    report = ledger.report()
    assert "1/3 took effect" in report
    assert "(1 unverifiable)" in report


class Ground:
    """`open_ground` over a stub observation - it needs only the objects and their positions."""

    open_ground = Powers.open_ground
    clear_spot = Powers.clear_spot
    summon_spot = Powers.summon_spot
    refused_ground = Powers.refused_ground

    def __init__(self, standing: list[tuple[float, float, float]]) -> None:
        self.observation = _Objects([_Object(p) for p in standing])
        self._refused_ground: dict[tuple[float, float, float], float] = {}


class _Objects:
    def __init__(self, objects: list[_Object]) -> None:
        self.objects = objects


class _Object:
    def __init__(self, position: tuple[float, float, float]) -> None:
        self.position = position
        self.has_body = True


def test_a_build_power_is_aimed_at_ground_nothing_is_standing_on() -> None:
    """The measured refusals: Lone Tower fired at the centre of a base with no room in it."""
    centre = (0.0, 0.0, 150.0)
    empty = Ground([])
    assert empty.open_ground(centre) == centre, "an empty base takes the building at its centre"

    blocked = Ground([centre])
    spot = blocked.open_ground(centre)
    assert spot is not None
    assert distance(spot, centre) >= CAST_BUILD_CLEARANCE, "the centre is occupied, so look out"
    assert spot[2] == centre[2], "the search moves over the ground, not through it"


def test_a_base_with_no_room_anywhere_keeps_the_charge() -> None:
    """None rather than a guess: the cast would be refused and the recharge spent for nothing."""
    centre = (0.0, 0.0, 150.0)
    packed = [
        (ring * math.cos(step * math.pi / 4), ring * math.sin(step * math.pi / 4), 150.0)
        for ring in CAST_BUILD_RINGS
        for step in range(8)
    ]
    assert Ground(packed).open_ground(centre) is None


def structure(conditions: frozenset[str], health: float) -> GameObject:
    return GameObject(
        object_id=1,
        template_name="GondorCampKeep",
        template_side="Men",
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        health=health,
        max_health=5000.0,
        conditions=conditions,
    )


def test_wreckage_is_told_apart_from_a_building_worth_healing() -> None:
    """A destroyed keep stays in the table at zero health, wearing `RUBBLE`.

    It is not under construction and it is the most damaged thing owned, so before the engine's
    own condition was read it won every heal it was offered - `GondorCampKeep at 0%`, twice.
    """
    wreck = structure(frozenset({"RUBBLE"}), health=0.0)
    assert wreck.is_rubble
    assert wreck.is_damaged, "it does still read as damaged, which is the whole trap"
    assert not wreck.under_construction

    hurt = structure(frozenset({"DAMAGED"}), health=0.11)
    assert not hurt.is_rubble
    assert structure(frozenset(), health=1.0).is_rubble is False


def test_ground_the_engine_refused_is_not_offered_again() -> None:
    """Measured: the same spot picked and refused in two consecutive matches, to the decimal.

    The scan is deterministic and so is the base it measures from, so without a memory of
    refusals it answers water or cliff every cycle for the whole match.
    """
    centre = (0.0, 0.0, 150.0)
    ground = Ground([])
    first = ground.open_ground(centre)
    assert first == centre

    ground._refused_ground[first] = time.monotonic() + 120.0
    second = ground.open_ground(centre)
    assert second is not None
    assert second != first, "a refused spot has to be struck off, not offered again"
    assert distance(second, first) >= CAST_BUILD_CLEARANCE


def test_refused_ground_is_matched_by_proximity_not_equality() -> None:
    """`base_centre` drifts as buildings change, so every spot measured off it drifts too."""
    ground = Ground([])
    ground._refused_ground[(0.0, 0.0, 150.0)] = time.monotonic() + 120.0
    assert ground.refused_ground((3.0, 4.0, 150.0)), "a few units of drift is the same ground"
    assert not ground.refused_ground((1000.0, 0.0, 150.0))


class Sight:
    """`can_cast_at` over a stub shroud grid."""

    can_cast_at = Powers.can_cast_at
    visible_targets = Powers.visible_targets

    def __init__(self, grid: object) -> None:
        self.observation = _Shrouded(grid)
        self.session = _Seat(3)


class _Shrouded:
    def __init__(self, shroud: object) -> None:
        self.shroud = shroud


class _Seat:
    def __init__(self, player_index: int) -> None:
        self.player_index = player_index


class _Grid:
    def __init__(self, fog_enabled: bool, clear: set[tuple[float, float, float]]) -> None:
        self.fog_enabled = fog_enabled
        self._clear = clear

    def visible(self, position: tuple[float, float, float], player: int) -> bool:
        return position in self._clear


def test_a_cast_is_not_aimed_at_ground_the_seat_cannot_see() -> None:
    """Measured: Arrow Volley discarded at (1041, 2618), which the seat's shroud did not cover.

    Reading the object table from memory tells this bot where everything is; it does not give
    the seat the sight the engine checks when the order lands.
    """
    seen = (3263.0, 1516.0, 150.0)
    hidden = (1041.0, 2618.0, 150.0)
    eyes = Sight(_Grid(fog_enabled=True, clear={seen}))
    assert eyes.can_cast_at(seen)
    assert not eyes.can_cast_at(hidden)


def test_no_shroud_grid_filters_nothing() -> None:
    """Unknown means yes, as everywhere else here - a backend that cannot say must not veto."""
    assert Sight(None).can_cast_at((0.0, 0.0, 0.0))
    assert Sight(_Grid(fog_enabled=False, clear=set())).can_cast_at((0.0, 0.0, 0.0))


def test_refused_ground_is_offered_again_once_the_mark_expires() -> None:
    """A refusal may have been a battalion in the way, and a battalion moves.

    Terrain and traffic are indistinguishable from an observation, so the spot is avoided for a
    while rather than condemned for the match.
    """
    ground = Ground([])
    spot = (0.0, 0.0, 150.0)
    ground._refused_ground[spot] = time.monotonic() - 1.0
    assert not ground.refused_ground(spot), "an expired mark must not keep good ground blocked"

    ground._refused_ground[spot] = time.monotonic() + 120.0
    assert ground.refused_ground(spot)


def test_a_summon_is_aimed_beside_the_fight_not_into_it() -> None:
    """Measured by hand: a summon unpacks over a hundred units and needs room to do it.

    `SpellBookArmyoftheDead` and `SpellBookDieGraueSchaar` were both discarded on a cluster of
    twelve and both landed in open ground.
    """
    fight = (0.0, 0.0, 150.0)
    crowd = Ground([fight, (30.0, 10.0, 150.0), (-20.0, 25.0, 150.0)])
    spot = crowd.summon_spot(fight)
    assert spot != fight, "the middle of a crowd has no room for a summon"
    assert distance(spot, fight) >= CAST_SUMMON_CLEARANCE - 1e-6


def test_a_summon_falls_back_to_the_cluster_when_there_is_no_room_anywhere() -> None:
    """A flying summon needs no ground - Adler landed on the crowd the other two were refused on.

    So a packed map keeps the old aim rather than losing the cast.
    """
    fight = (0.0, 0.0, 150.0)
    packed = [
        (ring * math.cos(step * math.pi / 4), ring * math.sin(step * math.pi / 4), 150.0)
        for ring in CAST_SUMMON_RINGS
        for step in range(8)
    ]
    assert Ground(packed).summon_spot(fight) == fight


class Named:
    """`filter_targets` over a stub - it needs the build's template names and what is owned."""

    filter_targets = Powers.filter_targets

    def __init__(self, mine: list[GameObject], templates: set[str]) -> None:
        self.observation = _Mine(mine)
        self.statics = _Known(templates)


class _Mine:
    def __init__(self, mine: list[GameObject]) -> None:
        self.mine = mine


class _Known:
    def __init__(self, templates: set[str]) -> None:
        self._templates = {t.lower() for t in templates}

    def known(self, template: str) -> bool:
        return template.lower() in self._templates


def signal_fire(object_id: int, upgrades: frozenset[str] = frozenset()) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name="GondorLeuchtfeuer",
        template_side="Men",
        position=(0.0, 0.0, 150.0),
        angle=0.0,
        health=1.0,
        max_health=1000.0,
        upgrades=upgrades,
    )


def aid(grants: tuple[str, ...] = ("Upgrade_SwitchToRockThrowing",)) -> CastablePower:
    """Assistance in Time of Need, as `spell_book` reads it off the tree."""
    return CastablePower(
        command_slot=0,
        button="Command_SpellBookBeistandinderNotNormal",
        power="SpellBookBeistandinderNotNormal",
        affects=("SAME_PLAYER", "+GondorLeuchtfeuer"),
        grants=grants,
    )


BLESSED = frozenset({"Upgrade_SwitchToRockThrowing"})


def test_a_signal_fire_that_already_has_the_blessing_is_not_offered_it_again() -> None:
    """The cast is accepted, spends the charge and re-grants an upgrade already held.

    With two fires standing and one blessed, the whole point is that the other one gets it.
    """
    field = Named([signal_fire(1, BLESSED), signal_fire(2)], {"GondorLeuchtfeuer"})
    assert [o.object_id for o in field.filter_targets(aid()) or []] == [2]


def test_every_signal_fire_blessed_keeps_the_charge() -> None:
    """The empty list, not None - the caller already reads that as "do not fire"."""
    field = Named([signal_fire(1, BLESSED), signal_fire(2, BLESSED)], {"GondorLeuchtfeuer"})
    assert field.filter_targets(aid()) == []


def test_the_upgrade_is_matched_without_regard_to_case() -> None:
    """`GameObject.upgrades` carries the engine's spelling, which is not the ini's everywhere."""
    field = Named(
        [signal_fire(1, frozenset({"upgrade_switchtorockthrowing"}))], {"GondorLeuchtfeuer"}
    )
    assert field.filter_targets(aid()) == []


def test_a_power_that_grants_nothing_permanent_still_names_every_target() -> None:
    """A timed buff wears off, so recasting it on the same building is the whole point."""
    field = Named([signal_fire(1, BLESSED), signal_fire(2)], {"GondorLeuchtfeuer"})
    assert [o.object_id for o in field.filter_targets(aid(())) or []] == [1, 2]


def test_a_power_naming_no_template_is_still_not_template_specific() -> None:
    """None and the empty list mean different things, and the grant test must not confuse them."""
    field = Named([signal_fire(1, BLESSED)], set())
    assert field.filter_targets(aid()) is None


#
# What is worth buying. Almost every power is worth its points the moment it is affordable; the
# ones that buy an upgrade are not, because an upgrade has to land on something.


class Store:
    """`power_wanted` over a stub - it needs the plan's table and what is standing."""

    power_wanted = Powers.power_wanted

    def __init__(self, mine: list[GameObject], needs: tuple) -> None:
        self.observation = _Mine(mine)
        self.plan = _Plan(needs)


class _Plan:
    def __init__(self, power_needs: tuple) -> None:
        self.power_needs = power_needs


def standing(template: str) -> GameObject:
    return GameObject(
        object_id=1,
        template_name=template,
        template_side="Men",
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        health=1.0,
        max_health=1000.0,
    )


def white(cost: int = 5):  # noqa: ANN202
    """Gandalf the White, as `spell_store` reads it off `MenPurchaseScienceCommandSetMP`."""
    return PowerButton(
        command_slot=6,
        button="Command_PurchaseSpellGandalftheWhite",
        science="SCIENCE_GandalftheWhite",
        cost=cost,
    )


GANDALF = (("SCIENCE_GandalftheWhite", ("GondorGandalf",)),)


def test_an_upgrade_power_waits_for_the_hero_that_wears_it() -> None:
    """`SpellBookGandalftheWhite` grants `Upgrade_GandalfWhite`, which only Gandalf reads. Five of
    the book's points spent with him off the map buy nothing at all, and points are not refunded."""
    field = Store([standing("GondorBeregond")], GANDALF)
    assert not field.power_wanted(white())


def test_the_hero_on_the_map_opens_the_purchase() -> None:
    """The cycle after he appears, out of the ring quest or the White Council - this plan does not
    recruit him itself."""
    field = Store([standing("GondorBeregond"), standing("GondorGandalf")], GANDALF)
    assert field.power_wanted(white())


def test_a_variant_of_the_same_hero_counts() -> None:
    """Matched by prefix the way `precious` is: `GondorGandalf_WhiteCouncil` and the two ring-quest
    forms are all the hero the upgrade is for, and a plan should not have to list them."""
    field = Store([standing("GondorGandalf_WhiteCouncil")], GANDALF)
    assert field.power_wanted(white())


def test_every_other_power_is_wanted_on_sight() -> None:
    """The rule this stage is built on - a summon lands wherever it is aimed, so "is there anything
    to use it on" is the casting stage's question and never the store's."""
    eagles = PowerButton(
        command_slot=7, button="Command_PurchaseSpellAdler", science="SCIENCE_Adler", cost=7
    )
    assert Store([], GANDALF).power_wanted(eagles)


def test_a_faction_whose_plan_names_no_such_power_gates_nothing() -> None:
    """Mordor today. The table is empty and the filter must cost a lookup and nothing else."""
    assert Store([], ()).power_wanted(white())
