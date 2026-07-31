"""The revive system: the index space, the list's mutations, and the legitimacy gate.

Data-free. The two live recruits that identified the index space are pinned here as literals
(`FactionMen[7]` is Imrahil, `FactionElves[1]` is Rumil) rather than read from a tree, so this
suite states the rule even where no game is installed; `test_statics.py` checks the rule against
real ini data when a corpus is present.
"""

from __future__ import annotations

import pytest

from sage_live import (
    GameObject,
    IllegitimateOrder,
    LoopbackBackend,
    NoReviveLookup,
    NoSelection,
    Observation,
    OrderType,
    PlayerState,
    ReviveSlot,
    Session,
    orders,
)
from sage_live import heroes as _heroes

# `FactionMen`'s roster as RotWK 2.01 + Edain defines it. Index 7 is the one a live recruit
# confirmed: an order carrying 7 at a GondorBarracks produced Imrahil.
MEN = (
    "CreateAHero",
    "RohanPippin_mod",
    "GondorBeregond",
    "GondorDenethorMod",
    "GondorBoromir_mod",
    "GondorAragornEntwicklung1",
    "GondorGandalf_mod",
    "GondorImrahil",
    "GondorFaramir_mod",
)

# The Gondor barracks' slot block, as `GondorBarracksCommandSet` declares it: fourteen REVIVE
# buttons of which two are ungated, and those two are the heroes it really offers.
DRAGON = "Upgrade_HasDragonNestFireDrake"
BARRACKS_SLOTS = (
    ReviveSlot(0, 15, "Command_FakeRingHeroReviveSlot", ("Upgrade_RingHero",)),
    ReviveSlot(1, 16, "Command_FakeCreateAHeroReviveSlot", ("Upgrade_AllowBuildCreateAHero",)),
    ReviveSlot(2, 17, "Command_FakeHeroReviveSlot1", (DRAGON,)),
    ReviveSlot(3, 18, "Command_GenericReviveSlot2"),
    ReviveSlot(4, 19, "Command_FakeHeroReviveSlot3", (DRAGON,)),
    ReviveSlot(5, 20, "Command_GenericReviveSlot4"),
    ReviveSlot(6, 21, "Command_FakeHeroReviveSlot5", (DRAGON,)),
    ReviveSlot(7, 22, "Command_FakeHeroReviveSlot6", (DRAGON,)),
    ReviveSlot(8, 23, "Command_FakeHeroReviveSlot7", (DRAGON,)),
)


class FakeRevives:
    """A `ReviveLookup` over literals - what `Statics` provides off an ini load."""

    def __init__(self, roster=MEN, slots=None) -> None:
        self._roster = tuple(roster)
        self._slots = {"gondorbarracks": tuple(BARRACKS_SLOTS)} if slots is None else slots

    def hero_roster(self, faction: str) -> tuple[str, ...]:
        return self._roster if faction.lower() == "men" else ()

    def revive_slots(self, template: str) -> tuple[ReviveSlot, ...]:
        return self._slots.get(template.lower(), ())


def obj(object_id: int, template: str, upgrades=frozenset()) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name=template,
        template_side="Men",
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        health=1.0,
        max_health=100.0,
        owner_index=3,
        upgrades=frozenset(upgrades),
    )


def player(upgrades=frozenset()) -> PlayerState:
    return PlayerState(
        index=3, name="P", faction="Men", resources=1000, upgrades=frozenset(upgrades)
    )


def frame(n: int, objects, upgrades=frozenset()) -> Observation:
    return Observation(
        frame=n,
        local_player=3,
        players=(player(upgrades),),
        objects=tuple(objects),
    )


def session(script, godsight=True, revives=None) -> Session:
    s = Session(
        LoopbackBackend(script),
        player_index=3,
        godsight=godsight,
        revives=FakeRevives() if revives is None else revives,
    )
    s.connect()
    s.poll()
    return s


# --- the order shape -------------------------------------------------------------------


def test_recruit_hero_is_the_flagged_form_of_recruit():
    """Same order type as `recruit`, distinguished only by the leading boolean. That flag is
    the whole difference between a template id and a revive index, which is why feeding one to
    the other bought heroes nobody asked for."""
    unit = orders.recruit(0, 7)
    hero = orders.recruit_hero(0, 7)
    assert hero.order_type == unit.order_type == OrderType.QUEUE_UNIT_CREATE
    assert [a.argument_type for a in hero.arguments] == [a.argument_type for a in unit.arguments]
    assert unit.arguments[0].value is False
    assert hero.arguments[0].value is True
    assert [a.value for a in hero.arguments[1:]] == [7, -1, False, False]


# --- the index space -------------------------------------------------------------------


def test_roster_position_is_the_index_before_anyone_is_fielded():
    """The two live recruits that identified the space."""
    assert _heroes.revive_index(MEN, "GondorImrahil") == 7
    elves = ("CreateAHero", "LothlorienRumil", "LothlorienHaldir")
    assert _heroes.revive_index(elves, "LothlorienRumil") == 1


def test_a_fielded_hero_leaves_the_list_and_the_rest_slide_forward():
    """The reason a roster position is not a revive index for long."""
    assert _heroes.revive_index(MEN, "GondorImrahil", fielded=["GondorBeregond"]) == 6
    assert _heroes.revive_index(MEN, "GondorImrahil", fielded=["GondorFaramir_mod"]) == 7
    assert _heroes.current_list(MEN, fielded=["CreateAHero"])[0] == "RohanPippin_mod"


def test_a_hero_on_the_map_is_not_in_the_list_at_all():
    """None rather than a stale position: ordering the place it used to hold would recruit
    whoever slid into it."""
    assert _heroes.revive_index(MEN, "GondorImrahil", fielded=["GondorImrahil"]) is None


def test_a_killed_hero_rejoins_at_the_tail_in_death_order():
    listed = _heroes.current_list(MEN, fielded=["GondorGandalf_mod"], dead=["GondorBeregond"])
    assert listed[-1] == "GondorBeregond"
    assert "GondorGandalf_mod" not in listed


def test_ring_hero_slot_serves_no_roster_entry():
    """Position 0 is the Ring hero, which is not in `BuildableHeroesMP` - the whole reason the
    binding is offset by one."""
    assert BARRACKS_SLOTS[0].is_ring_hero
    assert BARRACKS_SLOTS[0].roster_index == -1
    assert BARRACKS_SLOTS[1].roster_index == 0


def test_the_barracks_ungated_slots_are_beregond_and_boromir():
    """The corroboration that the offset is right rather than merely self-consistent: these are
    the heroes an Edain Gondor barracks actually offers."""
    offered = [s.roster_index for s in BARRACKS_SLOTS if s.enabled_for(frozenset())]
    assert [MEN[i] for i in offered] == ["GondorBeregond", "GondorBoromir_mod"]


def test_a_needed_upgrade_is_satisfied_by_any_one_of_them():
    slot = ReviveSlot(3, 18, "b", ("Upgrade_A", "Upgrade_B"))
    assert not slot.enabled_for(frozenset())
    assert slot.enabled_for(frozenset({"upgrade_b"}))


# --- tracking the list across frames ---------------------------------------------------


def test_the_session_follows_heroes_onto_and_off_the_map():
    script = [
        frame(1, []),
        frame(2, [obj(10, "GondorBeregond")]),
        frame(3, []),
    ]
    game = session(script)
    assert game.revive_index("GondorImrahil") == 7

    game.poll()  # Beregond fielded: everything behind him slides forward
    assert game.revive_index("GondorBeregond") is None
    assert game.revive_index("GondorImrahil") == 6

    game.poll()  # and killed: he rejoins at the tail, so Imrahil moves back
    assert game.revive_index("GondorImrahil") == 6
    assert game.revive_index("GondorBeregond") == len(MEN) - 1


def test_absence_under_fog_is_not_a_death():
    """The same trap `_prune_selection` guards: under fog an object's absence means it is not
    visible, and reading that as a death sends the next recruit to a position that never moved."""
    fogged = Observation(frame=2, local_player=3, players=(player(),), objects=(), fogged=True)
    game = session([frame(1, [obj(10, "GondorBeregond")]), fogged])
    assert game.revive_index("GondorImrahil") == 6
    game.poll()
    assert game.revive_index("GondorImrahil") == 6


def test_an_unknown_hero_has_no_index():
    assert session([frame(1, [])]).revive_index("MordorWitchKing") is None


# --- the godsight gate -----------------------------------------------------------------


def test_godsight_allows_any_hero_the_slot_block_can_reach():
    """The engine's real behaviour: its gate counts REVIVE buttons and never reads the one it
    matched, so a barracks will produce Imrahil. That is what a live run measured, and keeping
    it reachable is the point of godsight."""
    game = session([frame(1, [obj(10, "GondorBarracks")])], godsight=True)
    game.select([10])
    assert game.recruit_hero("GondorImrahil")
    assert game.backend.sent[-1].arguments[1].value == 7


def test_without_godsight_only_enabled_buttons_recruit():
    game = session([frame(1, [obj(10, "GondorBarracks")])], godsight=False)
    game.select([10])
    assert game.recruit_hero("GondorBeregond")

    with pytest.raises(IllegitimateOrder, match="disabled"):
        game.recruit_hero("GondorImrahil")


def test_without_godsight_an_upgrade_can_open_a_slot():
    """The gate is a live question, not a static one: the same slot is refused and then allowed
    once the upgrade its button names is held. Object scope counts as well as player scope."""
    slots = {"gondorbarracks": (*BARRACKS_SLOTS[:2], ReviveSlot(2, 17, "b", ("Upgrade_X",)))}
    script = [
        frame(1, [obj(10, "GondorBarracks")]),
        frame(2, [obj(10, "GondorBarracks", upgrades={"Upgrade_X"})]),
    ]
    game = session(script, godsight=False, revives=FakeRevives(slots=slots))
    game.select([10])
    with pytest.raises(IllegitimateOrder):
        game.recruit_hero(1)
    game.poll()
    assert game.recruit_hero(1)


def test_a_building_with_no_revive_block_is_refused_under_godsight_too():
    """Godsight widens which hero, not which building: a barracks that carries no REVIVE button
    cannot recruit one, and the engine would discard the order in silence."""
    game = session([frame(1, [obj(10, "GondorForge")])], godsight=True)
    game.select([10])
    with pytest.raises(IllegitimateOrder, match="no REVIVE buttons"):
        game.recruit_hero(2)


def test_an_index_past_the_slot_block_is_refused_in_both_modes():
    """Not a legitimacy question - the engine's gate runs out of slots to count and discards
    the order, which is indistinguishable from a malformed one."""
    for godsight in (True, False):
        game = session([frame(1, [obj(10, "GondorBarracks")])], godsight=godsight)
        game.select([10])
        with pytest.raises(IllegitimateOrder, match="cannot reach"):
            game.recruit_hero(50)


def test_hero_recruit_needs_a_selection_and_a_lookup():
    game = session([frame(1, [obj(10, "GondorBarracks")])])
    with pytest.raises(NoSelection):
        game.recruit_hero(2)

    bare = Session(LoopbackBackend([frame(1, [obj(10, "GondorBarracks")])]), player_index=3)
    bare.connect()
    bare.poll()
    bare.select([10])
    with pytest.raises(NoReviveLookup):
        bare.recruit_hero(2)


def test_recruiting_a_hero_already_on_the_map_says_so():
    game = session([frame(1, [obj(10, "GondorBarracks"), obj(11, "GondorBeregond")])])
    game.select([10])
    with pytest.raises(LookupError, match="already on the map"):
        game.recruit_hero("GondorBeregond")


def test_the_building_defaults_to_the_selection():
    """The order acts on the selected building anyway, so naming it twice is noise."""
    game = session([frame(1, [obj(10, "GondorBarracks")])], godsight=False)
    game.select([10])
    assert game.recruit_hero("GondorBeregond", building_id=10)
    assert game.recruit_hero("GondorBeregond")
