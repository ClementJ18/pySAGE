"""`KindOf` resolution: inheritance, deltas, and the two questions it exists to answer.

`Statics` takes a `Game` rather than a path, so a build is faked with a handful of stand-in
objects and the whole module stays in the data-free suite - no install, no `.big` archives,
no minute-long load.

The cases here are the ones that were wrong in practice, not hypotheticals. A build plot was
first looked for as "an object with no body", which finds nothing because a plot carries an
`ImmortalBody`; then as a name ending in `Foundation`, which misses
`MordorFortressExpansionPadCorner`. `KindOf` is the only thing that answers it, and a
`ChildObject` does not restate its parent's - so inheritance is not an optional refinement.
"""

from __future__ import annotations

import pytest

from sage_live.statics import BASE_SITE_KINDS, MP_COUNT_FOR_VICTORY, Statics


class FakeModule:
    """The one member `Statics` reads off a behaviour module."""

    def __init__(self, fields: dict[str, str]) -> None:
        self.fields = fields


class FakeObject:
    """The three members `Statics` reads off a loaded definition."""

    def __init__(
        self,
        fields: dict[str, str],
        parent_name: str | None = None,
        modules: list[FakeModule] | None = None,
    ) -> None:
        self.fields = fields
        self.parent_name = parent_name
        self.modules = modules or []


class FakeGame:
    def __init__(self, objects: dict[str, FakeObject], **tables: dict[str, FakeObject]) -> None:
        self.tables = {"objects": objects, **tables}


def build() -> Statics:
    return Statics(
        FakeGame(
            {
                "GondorBuildingFoundation": FakeObject(
                    {"KindOf": "STRUCTURE SELECTABLE BASE_FOUNDATION MP_COUNT_FOR_VICTORY"}
                ),
                # A ChildObject that restates nothing - the case that made a name-based filter
                # look like it worked while quietly missing plots.
                "GondorBuildingFoundation_Independant": FakeObject(
                    {}, parent_name="GondorBuildingFoundation"
                ),
                # The delta form: adds to the inherited set rather than replacing it.
                "SummonedFoundation": FakeObject(
                    {"KindOf": "+SUMMONED"}, parent_name="GondorBuildingFoundation"
                ),
                # A delta that removes an inherited flag.
                "DecorativeFoundation": FakeObject(
                    {"KindOf": "-BASE_FOUNDATION"}, parent_name="GondorBuildingFoundation"
                ),
                # A plain KindOf on a child replaces the parent's outright.
                "PlainChild": FakeObject(
                    {"KindOf": "INFANTRY SELECTABLE"}, parent_name="GondorBuildingFoundation"
                ),
                # The real shape of an Edain economy building: what you order is never what
                # appears, and each variation restates the same KindOf as its own Object.
                "GondorWohnhaus": FakeObject(
                    {
                        "KindOf": "STRUCTURE IMMOBILE ECONOMY_STRUCTURE IGNORE_FOR_VICTORY",
                        "BuildVariations": "GondorWohnhaus01 GondorWohnhaus02",
                    }
                ),
                "GondorWohnhaus01": FakeObject(
                    {"KindOf": "STRUCTURE IMMOBILE ECONOMY_STRUCTURE IGNORE_FOR_VICTORY"}
                ),
                "GondorWohnhaus02": FakeObject(
                    {"KindOf": "STRUCTURE IMMOBILE ECONOMY_STRUCTURE IGNORE_FOR_VICTORY"}
                ),
                "GondorFighter": FakeObject({"KindOf": "INFANTRY SELECTABLE SCORE"}),
                # The container an order is addressed to. Its payload names the member
                # template and the count, and only the first token is the template.
                "GondorFighterHorde": FakeObject(
                    {"KindOf": "INFANTRY SELECTABLE HORDE SCORE"},
                    modules=[
                        FakeModule({"Body": "ActiveBody"}),  # a module carrying no payload
                        FakeModule({"InitialPayload": "GondorFighter GOOD_MEN_GIANT_HORDE_SIZE"}),
                    ],
                ),
                # A container whose payload is itself a container. Both roles at once, which
                # is the case `is_horde_member` has to resolve in favour of the container.
                "GondorCombinedHorde": FakeObject(
                    {"KindOf": "INFANTRY SELECTABLE HORDE"},
                    modules=[FakeModule({"InitialPayload": "GondorFighterHorde 1"})],
                ),
                "NoKindOfAtAll": FakeObject({"Side": "Men"}),
            }
        )
    )


@pytest.fixture
def statics() -> Statics:
    return build()


def test_a_plain_kindof_reads_directly(statics):
    assert "BASE_FOUNDATION" in statics.kind_of("GondorBuildingFoundation")
    assert statics.is_build_site("GondorBuildingFoundation")


def test_a_child_inherits_its_parents_kindof(statics):
    """The case a name-based or body-based filter silently misses."""
    assert statics.is_build_site("GondorBuildingFoundation_Independant")
    assert statics.counts_for_victory("GondorBuildingFoundation_Independant")


def test_a_plus_delta_adds_to_the_inherited_set(statics):
    kinds = statics.kind_of("SummonedFoundation")
    assert "SUMMONED" in kinds
    assert "BASE_FOUNDATION" in kinds  # inherited, not replaced


def test_a_minus_delta_removes_an_inherited_flag(statics):
    kinds = statics.kind_of("DecorativeFoundation")
    assert "BASE_FOUNDATION" not in kinds
    assert "STRUCTURE" in kinds
    assert not statics.is_build_site("DecorativeFoundation")


def test_a_plain_kindof_on_a_child_replaces_rather_than_extends(statics):
    kinds = statics.kind_of("PlainChild")
    assert kinds == frozenset({"INFANTRY", "SELECTABLE"})
    assert not statics.is_build_site("PlainChild")


def test_lookup_is_case_insensitive(statics):
    """A live observation spells a template however the engine registered it."""
    assert statics.is_build_site("gondorbuildingfoundation")
    assert statics.kind_of("GONDORFIGHTER") == statics.kind_of("GondorFighter")


def test_an_unknown_template_is_empty_rather_than_an_error(statics):
    """A live game carries templates a differently-modded tree never defined. That is a
    reason to skip the object, not to end the session."""
    assert statics.kind_of("SomethingThisBuildNeverHeardOf") == frozenset()
    assert not statics.is_build_site("SomethingThisBuildNeverHeardOf")
    assert not statics.known("SomethingThisBuildNeverHeardOf")


def test_an_economy_building_does_not_count_for_victory(statics):
    """`IGNORE_FOR_VICTORY` is why "owns no buildings" is the wrong defeat test."""
    assert statics.known("GondorWohnhaus")
    assert not statics.counts_for_victory("GondorWohnhaus")


def test_a_definition_with_no_kindof_answers_empty(statics):
    assert statics.kind_of("NoKindOfAtAll") == frozenset()


def test_has_kind_is_an_any_of_test(statics):
    assert statics.has_kind("GondorFighter", "CAVALRY", "INFANTRY")
    assert not statics.has_kind("GondorFighter", "CAVALRY", "STRUCTURE")


def test_field_follows_the_parent_chain(statics):
    assert statics.field("GondorBuildingFoundation_Independant", "KindOf") is not None
    assert statics.field("GondorFighter", "Side") is None


def test_templates_with_finds_every_carrier(statics):
    found = statics.templates_with(*BASE_SITE_KINDS)
    assert "gondorbuildingfoundation" in found
    assert "gondorbuildingfoundation_independant" in found
    assert "decorativefoundation" not in found  # the minus delta removed it


def test_the_victory_flag_constant_matches_what_the_engine_spells(statics):
    assert MP_COUNT_FOR_VICTORY in statics.kind_of("GondorBuildingFoundation")


def test_build_variations_are_reported(statics):
    """What you order is not what appears. A bot counting the ordered name sees zero forever
    and rebuilds every cycle, which is exactly what happened live."""
    assert statics.build_variations("GondorWohnhaus") == (
        "GondorWohnhaus01",
        "GondorWohnhaus02",
    )
    assert statics.build_variations("GondorBarracks") == ()


def test_a_variation_maps_back_to_the_template_that_was_ordered(statics):
    assert statics.canonical("GondorWohnhaus01") == "gondorwohnhaus"
    assert statics.canonical("GondorWohnhaus02") == "gondorwohnhaus"


def test_a_template_with_no_variations_is_its_own_canonical(statics):
    assert statics.canonical("GondorFighter") == "GondorFighter"


def test_same_building_covers_the_ordered_name_and_every_variation(statics):
    assert statics.same_building("GondorWohnhaus") == frozenset(
        {"gondorwohnhaus", "gondorwohnhaus01", "gondorwohnhaus02"}
    )


def test_a_variation_carries_the_kindof_that_counting_relies_on(statics):
    """The fix for the rebuild loop: count by flag, and every variation answers to it."""
    for name in ("GondorWohnhaus", "GondorWohnhaus01", "GondorWohnhaus02"):
        assert statics.has_kind(name, "ECONOMY_STRUCTURE")
        assert not statics.counts_for_victory(name)


def test_a_horde_names_the_member_it_is_filled_with(statics):
    """`InitialPayload` is `<template> <count>`, and only the first token is a template."""
    assert statics.horde_payload("GondorFighterHorde") == "GondorFighter"


def test_a_module_without_a_payload_is_skipped(statics):
    """The payload module is one of many, and it is not the first."""
    assert statics.horde_payload("GondorWohnhaus") is None
    assert statics.horde_payload("SomethingThisBuildNeverHeardOf") is None


def test_the_thing_an_order_is_addressed_to_is_the_container(statics):
    assert statics.is_horde("GondorFighterHorde")
    assert not statics.is_horde("GondorFighter")


def test_a_member_is_not_something_to_select(statics):
    """Selecting 30 `GondorFighter` and issuing a move produced an order the engine recorded
    and then ignored: `HordeAIUpdate` on the container is what moves them."""
    assert statics.is_horde_member("GondorFighter")
    assert not statics.is_horde_member("GondorFighterHorde")


def test_a_container_that_is_also_a_payload_stays_orderable(statics):
    """`GondorCombinedHorde` is filled with `GondorFighterHorde`, so the inner one appears in
    both roles. It is still a container, and still the correct thing to name."""
    assert "gondorfighterhorde" in statics.horde_members()
    assert not statics.is_horde_member("GondorFighterHorde")


def test_every_payload_template_is_collected(statics):
    assert statics.horde_members() == frozenset({"gondorfighter", "gondorfighterhorde"})


def test_horde_lookups_are_case_insensitive(statics):
    assert statics.is_horde_member("gondorfighter")
    assert statics.is_horde("GONDORFIGHTERHORDE")
    assert statics.horde_payload("gondorfighterhorde") == "GondorFighter"


# --- the revive system ------------------------------------------------------------------
#
# `GondorBarracksCommandSet` reproduced faithfully, because its shape is the whole point: a
# building that recruits *any* hero carries the whole slot block, and the slots it must not
# offer are killed with an upgrade it can never hold. Two of fourteen are live here, and they
# are the two heroes an Edain Gondor barracks really offers.

DRAGON = "Upgrade_HasDragonNestFireDrake"
BARRACKS = {
    # The command range a player reaches the revive submenu through, which is not a REVIVE
    # button itself and must not be counted as one.
    14: ("Command_SelectRevivablesGondorKaserne", "PUSH_VISIBLE_COMMAND_RANGE", ""),
    15: ("Command_FakeRingHeroReviveSlot", "REVIVE", "Upgrade_RingHero"),
    16: ("Command_FakeCreateAHeroReviveSlot", "REVIVE", "Upgrade_AllowBuildCreateAHero"),
    17: ("Command_FakeHeroReviveSlot1", "REVIVE", DRAGON),
    18: ("Command_GenericReviveSlot2", "REVIVE", ""),
    19: ("Command_FakeHeroReviveSlot3", "REVIVE", DRAGON),
    20: ("Command_GenericReviveSlot4", "REVIVE", ""),
    21: ("Command_FakeHeroReviveSlot5", "REVIVE", DRAGON),
}

MEN_ROSTER = (
    "CreateAHero RohanPippin_mod GondorBeregond GondorDenethorMod GondorBoromir_mod "
    "GondorAragornEntwicklung1 GondorGandalf_mod GondorImrahil GondorFaramir_mod"
)


@pytest.fixture
def revives() -> Statics:
    buttons = {
        name: FakeObject({"Command": command, "NeededUpgrade": needed, "Options": "NEED_UPGRADE"})
        for name, command, needed in BARRACKS.values()
    }
    return Statics(
        FakeGame(
            {
                "GondorBarracks": FakeObject({"CommandSet": "GondorBarracksCommandSet"}),
                "GondorBarracksLevel2": FakeObject({}, parent_name="GondorBarracks"),
                "GondorForge": FakeObject({"CommandSet": "GondorForgeCommandSet"}),
            },
            commandsets={
                "GondorBarracksCommandSet": FakeObject(
                    {str(slot): button for slot, (button, _, _) in BARRACKS.items()}
                ),
                "GondorForgeCommandSet": FakeObject({"1": "Command_Sell"}),
            },
            commandbuttons={**buttons, "Command_Sell": FakeObject({"Command": "SELL"})},
            factions={
                "FactionMen": FakeObject(
                    {"Side": "Men", "PlayableSide": "Yes", "BuildableHeroesMP": MEN_ROSTER}
                ),
                # Same Side, different roster: matching on Side alone would pick between them
                # by luck.
                "FactionTutorial": FakeObject(
                    {"Side": "Men", "PlayableSide": "No", "BuildableHeroesMP": "CreateAHero"}
                ),
            },
        )
    )


def test_only_revive_buttons_are_counted(revives):
    """The submenu button that *reaches* the slots sits in the same range and is not one of
    them. Counting it would shift every hero by one."""
    slots = revives.revive_slots("GondorBarracks")
    assert [s.command_slot for s in slots] == [15, 16, 17, 18, 19, 20, 21]
    assert [s.position for s in slots] == [0, 1, 2, 3, 4, 5, 6]


def test_the_ungated_slots_name_the_heroes_the_barracks_offers(revives):
    """The check that the one-position offset is right rather than merely self-consistent."""
    roster = revives.hero_roster("Men")
    offered = [
        roster[s.roster_index]
        for s in revives.revive_slots("GondorBarracks")
        if s.enabled_for(frozenset())
    ]
    assert offered == ["GondorBeregond", "GondorBoromir_mod"]


def test_a_slot_block_that_does_not_line_up_is_reported(revives):
    """An enabled slot serving an index the roster does not have means the positional rule has
    landed nowhere, so the heroes that producer appears to offer are fiction. Reported rather
    than resolved: 9 of the tree's 187 playable-faction producers trip this, `RohanCitadel`
    among them."""
    assert revives.check_revive_slots("GondorBarracks", revives.hero_roster("Men")) == ()

    adrift = Statics(
        FakeGame(
            {"Keep": FakeObject({"CommandSet": "KeepCommandSet"})},
            commandsets={"KeepCommandSet": FakeObject({str(n): f"B{n}" for n in range(1, 6)})},
            commandbuttons={f"B{n}": FakeObject({"Command": "REVIVE"}) for n in range(1, 6)},
        )
    )
    assert adrift.check_revive_slots("Keep", ("CreateAHero", "SomeHero")) != ()
    assert "outside a roster of 2" in adrift.check_revive_slots("Keep", ("A", "B"))[0]


def test_a_permanently_gated_filler_is_not_checked(revives):
    """The `Fake...` slots hold positions so the real buttons land in the right places. They
    are never shown, so whether they line up is not a fact about anything."""
    short = revives.hero_roster("Men")[:3]
    assert all(
        "Fake" not in problem for problem in revives.check_revive_slots("GondorBarracks", short)
    )


def test_a_producer_inherits_its_command_set(revives):
    """A levelled building restates nothing, and reading the field directly would report no
    revive slots at all."""
    assert revives.revive_slots("GondorBarracksLevel2") == revives.revive_slots("GondorBarracks")


def test_anything_without_revive_buttons_has_no_slots(revives):
    assert revives.revive_slots("GondorForge") == ()
    assert revives.revive_slots("SomethingThisBuildNeverHeardOf") == ()


def test_the_roster_is_found_by_side_or_by_block_name(revives):
    """A live observation reports the Side token (`Men`), not the block name (`FactionMen`),
    and where several templates share a Side the playable one wins."""
    assert revives.hero_roster("Men")[7] == "GondorImrahil"
    assert revives.hero_roster("FactionMen") == revives.hero_roster("men")
    assert revives.hero_roster("Mordor") == ()


def test_revive_slot_for_finds_the_button_serving_an_index(revives):
    assert revives.revive_slot_for("GondorBarracks", 2).button == "Command_GenericReviveSlot2"
    assert revives.revive_slot_for("GondorBarracks", 99) is None
