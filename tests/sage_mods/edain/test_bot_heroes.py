"""The hero mission: where a hero stands, when it runs, and what it fires.

Three things separate a hero from every other unit this bot commands, and each of them is a way
the ordinary stages get it wrong:

- it is worth six battalions and does not come back, so it must leave a fight it is losing;
- most of what it is worth is behind buttons, gated by a level that is readable only as an
  upgrade on the object itself;
- two stages must never both command it, which is why it is out of the parties, out of the
  defence groups and out of the push force.

The stand-ins here are the shapes the live game produces, and the tests are named after the
failure each one prevents rather than after the method it calls.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_live.api.orders import CAST_LOCATION, CAST_OBJECT, CAST_SELF
from sage_live.utils.statics import (
    EFFECT_BUFF,
    EFFECT_SELF_BUFF,
    EFFECT_STRIKE,
    EFFECT_SUMMON,
    CastablePower,
)
from sage_mods.edain.bot.heroes import Heroes
from sage_mods.edain.bot.tuning import HERO_RETREAT, HERO_RETURN
from sage_mods.edain.bot.warfare import Warfare


def _obj(
    object_id: int,
    x: float = 0.0,
    template: str = "GondorFighterHorde",
    health: float = 1.0,
    upgrades: frozenset[str] = frozenset(),
) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        health=health,
        max_health=1000.0,
        has_body=True,
        is_damaged=health < 1.0,
        under_construction=False,
        upgrades=upgrades,
        distance_to=lambda point, _x=x: abs(point[0] - _x),
    )


def _hero(object_id: int = 1, x: float = 0.0, health: float = 1.0, level: int = 1):  # noqa: ANN202
    return _obj(
        object_id,
        x,
        template="GondorBeregond",
        health=health,
        upgrades=frozenset({f"Upgrade_Level_{n}" for n in range(1, level + 1)}),
    )


def _power(
    power: str,
    effect: str = EFFECT_STRIKE,
    form: str = CAST_OBJECT,
    unlocked_by: str = "",
    reach: float = 0.0,
    radius: float = 0.0,
    reload_seconds: float = 60.0,
) -> CastablePower:
    return CastablePower(
        command_slot=1,
        button=f"Command_{power}",
        power=power,
        form=form,
        effect=effect,
        radius=radius,
        reload_seconds=reload_seconds,
        unlocked_by=unlocked_by,
        ability_range=reach,
    )


class Field(Heroes):
    """The hero stages over a stub board, with every order recorded rather than sent."""

    def __init__(
        self,
        heroes: list,
        army: list | None = None,
        enemies: list | None = None,
        structures: list | None = None,
        powers: tuple[CastablePower, ...] = (),
        parties: dict[int, tuple[int, ...]] | None = None,
        groups: dict[int, tuple[int, ...]] | None = None,
        cooldowns: dict[str, int] | None = None,
        contact: bool = False,
    ) -> None:
        self._my_heroes = heroes
        self._army = [*heroes, *(army or [])]
        self._enemies = enemies or []
        self._structures = structures or []
        self._powers = powers
        self._parties = parties or {}
        self._groups = groups or {}
        self._pushing = False
        self._contact = contact
        self._cooldowns_read = cooldowns if cooldowns is not None else {}
        # The bot state these stages actually touch.
        self._hero_aim: dict = {}
        self._hero_ordered: dict = {}
        self._hero_escort: dict = {}
        self._hero_powers: dict = {}
        self._retreating: set[int] = set()
        self._cast_at: dict = {}
        self._cast_wait: dict = {}
        self._cast_frame: dict = {}
        self._ready_since: dict = {}
        self._strikes: dict = {}
        self._cooldowns: dict = {}
        # `summon_spot` searches for room to unpack, and the search remembers ground the engine
        # refused - shared with the spellbook's own casting, which is where the field lives.
        self._refused_ground: dict = {}
        # What the stage did.
        self.moves: list[tuple] = []
        self.casts: list[tuple] = []
        self.reported: list[bool | None] = []
        self.ledger = SimpleNamespace(record=lambda label, ok: self.reported.append(ok))
        self.session = SimpleNamespace(
            move=lambda point: self.moves.append(("move", point)) or True,
            attack_move=lambda point: self.moves.append(("attack_move", point)) or True,
            cast=self._cast,
            power_cooldowns=lambda object_id: self._cooldowns_read,
            confirm=lambda changed, timeout=0.0: True,
        )
        self.statics = SimpleNamespace(hero_powers=lambda template: self._powers)

    @property
    def observation(self) -> SimpleNamespace:
        return SimpleNamespace(
            mine=self._army + self._structures,
            objects=self._army + self._structures + self._enemies,
            me=SimpleNamespace(upgrades=frozenset(), command_points_free=999),
            frame=1000,
        )

    def _cast(self, power, form, position, target_id=0, source_id=0):  # noqa: ANN001, ANN202
        self.casts.append((power, form, position, target_id, source_id))
        return True

    def army(self) -> list:
        return self._army

    def heroes(self) -> list:
        return self._my_heroes

    def structures(self) -> list:
        return self._structures

    def enemies(self) -> list:
        return self._enemies

    def visible_targets(self, objects: list) -> list:
        return objects

    def can_cast_at(self, position) -> bool:  # noqa: ANN001
        return True

    def in_contact(self, force: list) -> bool:
        return self._contact

    def base_centre(self):  # noqa: ANN202
        return (0.0, 0.0, 0.0)

    def held_by(self, obj) -> set[str]:  # noqa: ANN001
        return {u.lower() for u in obj.upgrades}

    def select(self, objects) -> bool:  # noqa: ANN001
        return True

    def manoeuvre(self, label, act, units) -> bool:  # noqa: ANN001
        return bool(act())

    def _issue(self, label, act):  # noqa: ANN001, ANN202
        return act()

    def _report(self, label, ok, good, bad) -> bool:  # noqa: ANN001
        self.reported.append(ok)
        return ok


#
# Where the hero stands.


def test_a_healthy_hero_walks_to_the_force_that_is_fighting() -> None:
    """The whole mission in one line. A hero given its own target is one expensive object arriving
    alone; standing with a party it is a party that fights better and a hero that survives."""
    hero = _hero(1, x=0.0)
    party = [_obj(i, x=500.0) for i in (2, 3, 4)]
    field = Field([hero], army=party, parties={0: (2, 3, 4)}, groups={7: (5,)}, contact=True)
    said = field.stage_hero()

    assert said is not None and "3 of ours" in said
    assert field.moves == [("attack_move", (500.0, 0.0, 0.0))]


def test_an_escort_is_an_attack_move_and_a_retreat_is_a_move() -> None:
    """Two different orders and the difference is the point: a withdrawal that stops to fight
    everything on the way home is not a withdrawal."""
    hurt = _hero(1, x=900.0, health=HERO_RETREAT - 0.05)
    field = Field([hurt], structures=[_obj(9, x=100.0, template="GondorBarracks")])
    field.stage_hero()

    assert field.moves == [("move", (100.0, 0.0, 0.0))]


def test_a_hurt_hero_falls_back_to_something_rather_than_away_from_something() -> None:
    """Retreating along the vector away from the attacker buys one cycle and arrives in open
    ground, where the thing chasing is usually faster. A building is where the rest of the army
    already is - the same correction `stage_archers` makes toward the melee line."""
    hurt = _hero(1, x=900.0, health=0.2)
    near, far = _obj(9, x=700.0, template="GondorBarracks"), _obj(10, x=0.0, template="GondorForge")
    field = Field([hurt], structures=[far, near])
    field.stage_hero()

    assert field.moves == [("move", (700.0, 0.0, 0.0))]


def test_the_retreat_latches_so_a_hero_does_not_turn_round_at_the_threshold() -> None:
    """**The reason there are two numbers.** One threshold means the hero crosses it, regenerates
    a percent on the walk, turns back into the same fight and crosses it again - spending the
    match walking and fighting none of it."""
    field = Field([_hero(1, health=HERO_RETREAT - 0.01)])
    assert field.hero_retreating(field.heroes()[0])

    # Recovered a little, but nowhere near fit. Still going.
    field._my_heroes = [_hero(1, health=HERO_RETREAT + 0.05)]
    assert field.hero_retreating(field.heroes()[0])

    field._my_heroes = [_hero(1, health=HERO_RETURN)]
    assert not field.hero_retreating(field.heroes()[0])


def test_a_healthy_hero_is_not_retreating() -> None:
    """The ordinary case, and the one a mistake here would break silently."""
    assert not Field([_hero(1, health=1.0)]).hero_retreating(_hero(1, health=1.0))


def test_a_hero_with_no_readable_body_is_not_dying() -> None:
    """`has_body` is false where the observation could not read hit points, and zero there means
    "not applicable" rather than "about to die"."""
    hero = _hero(1, health=0.0)
    hero.has_body = False
    assert not Field([hero]).hero_retreating(hero)


def test_the_escort_is_sticky_between_cycles() -> None:
    """Two forces at roughly equal distance would otherwise swap the hero back and forth every
    cycle, and it would never arrive at either - the flicker `Shot.label` exists to prevent one
    layer up, applied to a unit instead of a camera."""
    hero = _hero(1, x=0.0)
    field = Field(
        [hero],
        army=[_obj(2, x=500.0), _obj(3, x=501.0)],
        parties={0: (2,), 1: (3,)},
    )
    first = field.hero_escort(hero)
    assert field._hero_escort[1] == "party:0"

    # The other party edges closer. The commitment holds.
    field._army[2].position = (1.0, 0.0, 0.0)
    assert field.hero_escort(hero) == first


def test_a_force_that_has_died_releases_the_commitment() -> None:
    """Sticky is not permanent. A party that no longer exists is not somewhere to walk to."""
    hero = _hero(1, x=0.0)
    field = Field([hero], army=[_obj(2, x=500.0), _obj(3, x=900.0)], parties={0: (2,), 1: (3,)})
    field.hero_escort(hero)
    field._parties = {1: (3,)}

    assert [o.object_id for o in field.hero_escort(hero)] == [3]


def test_with_no_party_yet_the_hero_stands_with_the_army() -> None:
    """The opening, and any cycle where the bookkeeping is momentarily empty. A hero standing with
    a crowd that has no job beats a hero standing on its own."""
    hero = _hero(1, x=0.0)
    field = Field([hero], army=[_obj(2, x=400.0), _obj(3, x=400.0)])

    assert [o.object_id for o in field.hero_escort(hero)] == [2, 3]


def test_a_force_is_never_made_of_heroes() -> None:
    """Otherwise two heroes escort each other, walk to their own midpoint, and are exactly as
    alone as they were."""
    one, two = _hero(1, x=0.0), _hero(2, x=800.0)
    field = Field([one, two])

    assert field.hero_escort(one) is None


#
# What the hero fires.


def test_an_ability_below_its_level_is_not_offered() -> None:
    """The gate is an upgrade on the hero itself. Firing a paused ability is the silent discard
    every unaffordable order in this bot gets - taken by the stream, dropped by logic."""
    hero = _hero(1, level=3)
    powers = (
        _power("Early", unlocked_by="Upgrade_Level_1"),
        _power("Late", unlocked_by="Upgrade_Level_8"),
    )
    field = Field([hero], enemies=[_obj(5, x=50.0)], powers=powers)

    assert [p.power for p in field.hero_ready_powers(hero)] == ["Early"]


def test_an_ability_with_no_gate_is_offered() -> None:
    """Not every ability is gated - Gandalf's shield bubble carries no unpause module - and a
    missing gate must read as open rather than as permanently shut."""
    hero = _hero(1, level=1)
    field = Field([hero], enemies=[_obj(5, x=50.0)], powers=(_power("Open"),))

    assert [p.power for p in field.hero_ready_powers(hero)] == ["Open"]


def test_two_heroes_do_not_share_one_clock() -> None:
    """`SpecialAbilityAragornBladeMaster` is Boromir's and Aragorn's, and every hero in the game
    carries `SpecialAbilityCaptureBuilding`. Keyed by name alone, one hero's cast silences the
    other's ability for a whole recharge."""
    one, two = _hero(1), _hero(2, x=50.0)
    power = _power("Shared")
    field = Field([one, two])

    assert field.hero_key(one, power) != field.hero_key(two, power)


def test_a_self_buff_waits_until_the_hero_is_in_a_fight() -> None:
    """There is no target to count and no position to choose, so "something is hitting me" is the
    only honest test available at a two-second cycle - and firing Blade Master while walking
    across an empty map is two minutes of recharge spent on nothing."""
    hero = _hero(1)
    power = _power("Blades", effect=EFFECT_SELF_BUFF, form=CAST_SELF)

    assert Field([hero], powers=(power,), contact=False).hero_aim(hero, power) is None
    assert Field([hero], powers=(power,), contact=True).hero_aim(hero, power) is not None


def test_a_self_cast_ally_buff_asks_the_same_question() -> None:
    """Boromir's Horn declares an `AttributeModifierRange` of 9999999 - the whole map - so counting
    who is inside it proves nothing. Whether the army is *fighting* is what decides whether a speed
    buff is worth two minutes."""
    hero = _hero(1)
    horn = _power("Horn", effect=EFFECT_BUFF, form=CAST_SELF, radius=9999999.0)

    assert Field([hero], powers=(horn,), contact=False).hero_aim(hero, horn) is None
    assert Field([hero], powers=(horn,), contact=True).hero_aim(hero, horn) is not None


def test_a_target_outside_the_approach_range_is_not_chosen() -> None:
    """**`StartAbilityRange` is a walk, not a filter.** The engine closes the distance itself, so
    an ability aimed past it does not fail - it sends the hero there alone, which is the expensive
    way to lose one. Gandalf's Wizard Blast declares 80."""
    hero = _hero(1, x=0.0)
    blast = _power("Blast", effect=EFFECT_STRIKE, form=CAST_OBJECT, reach=80.0)
    far = Field([hero], enemies=[_obj(5, x=4000.0)], powers=(blast,))
    near = Field([hero], enemies=[_obj(5, x=60.0)], powers=(blast,))

    assert far.hero_aim(hero, blast) is None
    assert near.hero_aim(hero, blast) is not None


def test_an_object_cast_names_the_nearest_rather_than_the_densest() -> None:
    """Density describes a circle and an object cast names one thing, so there is no circle."""
    hero = _hero(1, x=0.0)
    blast = _power("Blast", effect=EFFECT_STRIKE, form=CAST_OBJECT, reach=1000.0)
    field = Field([hero], enemies=[_obj(5, x=800.0), _obj(6, x=100.0)], powers=(blast,))
    position, target_id, _ = field.hero_aim(hero, blast)

    assert target_id == 6
    assert position == (100.0, 0.0, 0.0)


def test_a_ground_strike_wants_a_crowd() -> None:
    """A recharge measured in minutes spent on one warg is the same waste `CAST_MIN_TARGETS`
    exists to prevent for the spellbook, at a lower bar because hero recharges are shorter."""
    hero = _hero(1, x=0.0)
    volley = _power("Volley", effect=EFFECT_STRIKE, form=CAST_LOCATION, reach=500.0, radius=200.0)
    alone = Field([hero], enemies=[_obj(5, x=100.0)], powers=(volley,))
    crowd = Field([hero], enemies=[_obj(5, x=100.0), _obj(6, x=110.0)], powers=(volley,))

    assert alone.hero_aim(hero, volley) is None
    assert crowd.hero_aim(hero, volley) is not None


def test_a_summon_lands_beside_the_fighting() -> None:
    """The arrivals need room to unpack - the same reason a spellbook summon goes through
    `summon_spot` rather than into the middle of the crowd it was aimed at."""
    hero = _hero(1, x=0.0)
    call = _power("Call", effect=EFFECT_SUMMON, form=CAST_LOCATION, reach=500.0, radius=200.0)
    field = Field([hero], enemies=[_obj(5, x=100.0), _obj(6, x=110.0)], powers=(call,))

    assert field.hero_aim(hero, call) is not None


def test_the_source_slot_is_zero_for_an_object_cast_and_the_hero_otherwise() -> None:
    """**Measured, and measured on a hero ability.** Faramir's Wound Arrow did nothing with him
    named as the source and fired the moment the slot was zeroed - while a self or ground cast is
    cast *by* an object and does nothing without one. Getting it the wrong way round is silent."""
    hero = _hero(1, x=0.0)
    blast = _power("Blast", effect=EFFECT_STRIKE, form=CAST_OBJECT, reach=500.0)
    field = Field([hero], enemies=[_obj(5, x=100.0)], powers=(blast,))
    field.stage_hero_cast()
    assert field.casts[0][4] == 0

    horn = _power("Horn", effect=EFFECT_SELF_BUFF, form=CAST_SELF)
    selfcast = Field([hero], powers=(horn,), contact=True)
    selfcast.stage_hero_cast()
    assert selfcast.casts[0][4] == 1


def test_a_retreating_hero_fires_only_what_needs_no_approach() -> None:
    """An ability with a target makes the engine close `StartAbilityRange` first, so ordering one
    during a withdrawal turns the hero round and walks it back into what it is running from - the
    retreat undone by the stage meant to help it survive."""
    hero = _hero(1, x=900.0, health=0.2)
    blast = _power("Blast", effect=EFFECT_STRIKE, form=CAST_OBJECT, reach=1000.0)
    field = Field(
        [hero],
        enemies=[_obj(5, x=950.0)],
        structures=[_obj(9, x=0.0, template="GondorBarracks")],
        powers=(blast,),
        contact=True,
    )
    field.stage_hero()
    assert field.stage_hero_cast() is None
    assert field.casts == []


def test_a_retreating_hero_still_fires_a_self_cast() -> None:
    """Last Stand, Blade Master and the Horn are exactly the abilities worth having while hurt,
    and none of them makes the hero walk anywhere."""
    hero = _hero(1, x=900.0, health=0.2)
    stand = _power("Stand", effect=EFFECT_SELF_BUFF, form=CAST_SELF)
    field = Field(
        [hero],
        structures=[_obj(9, x=0.0, template="GondorBarracks")],
        powers=(stand,),
        contact=True,
    )
    field.stage_hero()
    field.stage_hero_cast()

    assert [c[0] for c in field.casts] == ["Stand"]


def test_the_recharge_is_the_receipt() -> None:
    """**A hero has an oracle the spellbook does not.** A self buff changes no field an observation
    carries, drops no view marker and hurts nothing - but accepting a cast is what starts a
    recharge, so the ready-frame on the hero's own module moves when, and only when, the order
    landed. The signal fire paid for this lesson at 520 summons and zero charges spent."""
    hero = _hero(1)
    stand = _power("Stand", effect=EFFECT_SELF_BUFF, form=CAST_SELF)
    field = Field([hero], powers=(stand,), cooldowns={"Stand": 900}, contact=True)
    field.stage_hero_cast()

    assert field.reported == [True], "confirmed against the frame, not against the send"


def test_a_cast_with_no_readable_frame_is_recorded_as_unverified() -> None:
    """A backend that cannot read modules answers empty, and empty means "unknown". Recorded as
    exactly that rather than as a success - the case that reported 14/14 for a power the engine
    was refusing every time."""
    hero = _hero(1)
    stand = _power("Stand", effect=EFFECT_SELF_BUFF, form=CAST_SELF)
    field = Field([hero], powers=(stand,), cooldowns={}, contact=True)
    field.stage_hero_cast()

    assert field.reported == [None]


def test_an_ability_still_recharging_is_not_offered() -> None:
    """The engine's own number, not an estimate of it: `SpecialPower.ReloadTime` is undiscounted
    and Edain rescales it per player, so a bot pricing readiness from the ini sits out several
    times too long."""
    hero = _hero(1)
    stand = _power("Stand", effect=EFFECT_SELF_BUFF, form=CAST_SELF)
    field = Field([hero], powers=(stand,), cooldowns={"Stand": 5000}, contact=True)

    assert field.hero_ready_powers(hero) == []


def test_one_ability_per_cycle() -> None:
    """Like every other order in this bot. Two abilities fired in one frame is two confirmation
    windows and an APM spike, and the second was decided against a board the first has changed."""
    hero = _hero(1, x=0.0)
    powers = (
        _power("One", effect=EFFECT_STRIKE, form=CAST_OBJECT, reach=500.0, reload_seconds=90.0),
        _power("Two", effect=EFFECT_STRIKE, form=CAST_OBJECT, reach=500.0, reload_seconds=30.0),
    )
    field = Field([hero], enemies=[_obj(5, x=100.0)], powers=powers, cooldowns={})
    field.stage_hero_cast()

    assert len(field.casts) == 1


def test_the_longest_recharge_goes_first() -> None:
    """The opposite of the buying stage and for the opposite reason: a cast opens nothing, so the
    ability worth firing is the one that has been waiting longest to be worth something."""
    hero = _hero(1, x=0.0)
    powers = (
        _power("Short", effect=EFFECT_STRIKE, form=CAST_OBJECT, reach=500.0, reload_seconds=30.0),
        _power("Long", effect=EFFECT_STRIKE, form=CAST_OBJECT, reach=500.0, reload_seconds=300.0),
    )
    field = Field([hero], enemies=[_obj(5, x=100.0)], powers=powers, cooldowns={})
    field.stage_hero_cast()

    assert field.casts[0][0] == "Long"


def test_a_seat_with_no_heroes_does_nothing() -> None:
    """Which is every seat for most of a match, and every seat of a faction whose plan names no
    hero. The stages are in the generic loop, so this must cost a comparison and nothing else."""
    field = Field([], army=[_obj(2, x=100.0)])

    assert field.stage_hero() is None
    assert field.stage_hero_cast() is None
    assert field.moves == [] and field.casts == []


#
# Buying one. Nothing else in the bot does: `producers` reads `UNIT_BUILD` buttons and every hero
# in the game is behind a `REVIVE` one, in an index space of its own.

HERO_TEMPLATE = "GondorBeregond"
HERO_PRICE = 1300


class Slot:
    """One `Command = REVIVE` button, as `Statics.revive_slots` reports it."""

    def __init__(self, roster_index: int, needs: str = "") -> None:
        self.roster_index = roster_index
        self.needed_upgrades = (needs,) if needs else ()

    def enabled_for(self, upgrades) -> bool:  # noqa: ANN001
        return not self.needed_upgrades or any(u.lower() in upgrades for u in self.needed_upgrades)


class Hiring(Heroes):
    """`stage_hero_recruit` over a stub base, recording what it ordered and what it reserved."""

    def __init__(
        self,
        gold: int = 5000,
        slots: dict[str, tuple[Slot, ...]] | None = None,
        standing: list | None = None,
        free_points: int = 999,
        index: int | None = 2,
        queued: int = 0,
    ) -> None:
        self.plan = SimpleNamespace(hero=HERO_TEMPLATE)
        self._gold = gold
        self._standing = standing or []
        self._slots = slots if slots is not None else {"GondorBarracks": (Slot(2),)}
        self._free = free_points
        self._queued = queued
        self._reserved: dict[str, int] = {}
        self._strikes: dict = {}
        self._cooldowns: dict = {}
        self.ordered: list[tuple[str, int]] = []
        self.reported: list[bool] = []
        self.session = SimpleNamespace(
            revive_index=lambda hero: index,
            recruit_hero=lambda hero, building_id: self.ordered.append((hero, building_id)) or True,
            confirm_queued=lambda act, object_id: bool(act()),
        )
        self.statics = SimpleNamespace(
            revive_slots=lambda template: self._slots.get(template, ()),
            command_point_cost=lambda template: 30,
        )

    @property
    def gold(self) -> int:
        return self._gold

    @property
    def observation(self) -> SimpleNamespace:
        return SimpleNamespace(
            mine=self._standing,
            me=SimpleNamespace(upgrades=frozenset(), command_points_free=self._free),
        )

    def structures(self) -> list:
        return [_obj(10, template="GondorBarracks"), _obj(11, template="GondorForge")]

    def queued_units(self, building) -> int:  # noqa: ANN001
        return self._queued

    def held_by(self, obj) -> set[str]:  # noqa: ANN001
        return set()

    def charged_cost(self, template: str) -> int:
        return HERO_PRICE

    def select(self, objects) -> bool:  # noqa: ANN001
        return True

    def _issue(self, label, act):  # noqa: ANN001, ANN202
        return act()

    def _report(self, label, ok, good, bad) -> bool:  # noqa: ANN001
        self.reported.append(ok)
        return ok


def test_the_hero_is_bought_at_a_building_that_actually_offers_it() -> None:
    """The engine's own revive gate counts `REVIVE` buttons and never reads the button it matched,
    so it will build a hero at a building that does not offer one - a `GondorBarracks` was made to
    produce Imrahil this way, and nothing in the game reports it."""
    hiring = Hiring()
    hiring.stage_hero_recruit()

    assert hiring.ordered == [(HERO_TEMPLATE, 10)]


def test_no_building_serves_the_slot_and_nothing_is_ordered() -> None:
    """The honest version of the gate above: a cycle where nobody can serve is a stage returning
    None, not an `IllegitimateOrder` climbing out of `decide`."""
    hiring = Hiring(slots={})
    assert hiring.stage_hero_recruit() is None
    assert hiring.ordered == []


def test_a_slot_the_control_bar_would_hide_is_not_used() -> None:
    """A revive button gated behind an upgrade nobody has bought is a hero that is not on offer,
    whatever the engine would accept."""
    hiring = Hiring(slots={"GondorBarracks": (Slot(2, needs="Upgrade_Never"),)})
    assert hiring.stage_hero_recruit() is None


def test_a_hero_already_on_the_map_is_not_bought_again() -> None:
    """`revive_index` answers None for one that has left the list, and ordering the position it
    used to hold would recruit whoever slid into that place."""
    hiring = Hiring(standing=[_obj(3, template=HERO_TEMPLATE)], index=None)
    assert hiring.stage_hero_recruit() is None
    assert hiring.ordered == []


def test_nothing_is_reserved_before_the_economy_can_carry_it() -> None:
    """**A hero bought early is six battalions not bought, and a hero standing alone.** Holding
    gold back before production can absorb the balance starves the recruiting that has to happen
    first for the hero to have an army to stand with."""
    hiring = Hiring(gold=400)
    assert hiring.stage_hero_recruit() is None
    assert hiring.reserved() == 0


def test_the_price_is_set_aside_while_the_order_is_reached() -> None:
    """`stage_recruit` runs first in every list and spends whatever it can see, so a hero priced
    against the plain balance is a hero whose price is gone by the next cycle - the same failure
    `take_flag` reserves against."""
    hiring = Hiring(gold=1600)
    hiring.stage_hero_recruit()

    assert hiring.reserved() == 0, "released once the order went out"
    assert hiring.ordered

    saving = Hiring(gold=1500)
    saving._reserved["something else"] = 900
    said = saving.stage_hero_recruit()
    assert said is not None and "saving" in said
    assert saving.ordered == []


def test_every_way_out_gives_the_gold_back() -> None:
    """**The half of a reservation that is easy to forget.** The price is invisible to every other
    stage while it is held, so a promise left standing for a hero nobody is going to buy is 1300
    gold the bot cannot see - for two minutes after three refusals bench it, and for the rest of
    the match if the barracks that sold it has been razed."""
    for giving_up in (
        Hiring(slots={}),  # nothing offers the slot any more
        Hiring(gold=100),  # the balance fell back under the floor
        Hiring(standing=[_obj(3, template=HERO_TEMPLATE)], index=None),  # already fielded
    ):
        giving_up._reserved["hero"] = HERO_PRICE
        giving_up.stage_hero_recruit()
        assert giving_up.reserved() == 0


def test_a_hero_the_ceiling_has_no_room_for_waits() -> None:
    """The same silent discard an over-cap recruit gets: the engine takes the order, queues
    nothing and reports nothing."""
    hiring = Hiring(free_points=10)
    said = hiring.stage_hero_recruit()

    assert said is not None and "command points" in said
    assert hiring.ordered == []


def test_a_faction_whose_plan_names_no_hero_buys_none() -> None:
    """Mordor today. The stage is in the generic loop and must cost one comparison there."""
    hiring = Hiring()
    hiring.plan = SimpleNamespace(hero="")

    assert hiring.stage_hero_recruit() is None


#
# One stage owns each unit. These three are the places that used to command a hero as though it
# were a battalion, and the reason each of them must not.


class Splitting(Warfare):
    """`expansion_parties` and `group_for` over a stub army, to check who is claimed."""

    def __init__(self, army: list, heroes: list) -> None:
        self._army = army
        self._my_heroes = heroes
        self._groups: dict[int, tuple[int, ...]] = {}
        self._parties: dict[int, tuple[int, ...]] = {}
        self._party_flag: dict[int, int] = {}
        self._forming: tuple[int, ...] = ()
        self._next_party = 0
        self._cav: tuple[int, ...] = ()
        self._pushing = False

    def army(self) -> list:
        return self._army

    def heroes(self) -> list:
        return self._my_heroes

    def role(self, obj, *flags) -> bool:  # noqa: ANN001
        return any(o.object_id == obj.object_id for o in self._my_heroes)

    def detachment(self, available, current, size):  # noqa: ANN001, ANN202
        return available[:size]


def test_a_hero_is_never_a_battalion_in_a_party() -> None:
    """**The state before any of this existed.** `army()` deliberately keeps heroes, so a fielded
    one was simply the oldest object in a party and got marched at lairs like a swordsman - the
    most expensive unit in the game fighting the one way it is worst at, with no ability fired and
    nobody watching its health."""
    hero = _hero(1)
    army = [hero, *(_obj(i, x=100.0) for i in (2, 3, 4))]
    parties = Splitting(army, [hero]).expansion_parties()

    assert [o.object_id for party in parties.values() for o in party] == [2, 3, 4]


def test_a_hero_is_not_drafted_into_a_defence_group() -> None:
    """Not because a hero at a threatened farm is unwanted - `stage_hero` sends it, because a
    group in contact is exactly the force it escorts. What must not happen is both stages
    commanding it: ordered to stand on the holding by one and home to heal by the other, on
    alternate cycles, it would do neither."""
    hero = _hero(1)
    army = [hero, *(_obj(i, x=100.0) for i in (2, 3))]
    field = Splitting(army, [hero])
    group = field.group_for(0, (0.0, 0.0, 0.0), [_obj(9, x=50.0)], set())

    assert 1 not in [o.object_id for o in group]
