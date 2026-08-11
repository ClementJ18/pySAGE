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

from sage_ini.model.behaviors import CommandSetUpgrade
from sage_live.utils.statics import (
    BASE_SITE_KINDS,
    CASTLE_UNPACK,
    MP_COUNT_FOR_VICTORY,
    Statics,
)


class FakeModule:
    """The one member `Statics` reads off a behaviour module.

    `_fields` is the same dict under the name `sage_ini.model.state` reads it by - the real
    model exposes both, and `live_command_set` hands these straight to `state`.
    """

    def __init__(self, fields: dict[str, str], name: str = "") -> None:
        self.fields = fields
        self._fields = fields
        # `Behavior = SlavedUpdate ModuleTag_Slave` - the declared type, then the tag. Which
        # module a block *is* lives here and nowhere in its fields.
        self.name = f"{name} ModuleTag_01" if name else ""


class FakeObject:
    """The three members `Statics` reads off a loaded definition.

    `_fields` and `parent` mirror `fields`/`parent_name` for `sage_ini.model.state`, which
    walks the chain by object rather than by name. `parent` is filled in by `_link`.
    """

    def __init__(
        self,
        fields: dict[str, str],
        parent_name: str | None = None,
        modules: list[FakeModule] | None = None,
    ) -> None:
        self.fields = fields
        self._fields = fields
        self.parent_name = parent_name
        self.parent: FakeObject | None = None
        self.modules = modules or []


def _link(objects: dict[str, FakeObject]) -> dict[str, FakeObject]:
    """Resolve each `parent_name` to the object itself, keyed as the real loader keys them."""
    by_name = {name.lower(): obj for name, obj in objects.items()}
    for obj in objects.values():
        if obj.parent_name is not None:
            obj.parent = by_name.get(obj.parent_name.lower())
    return objects


class FakeGame:
    """The tables and the `#define` table, which is the other half of reading a `KindOf`.

    A macro there is not decoration: `Rabbit` writes `KindOf = NATUREUNITS_KINDOF` and nothing
    else, so a reader that does not expand gets one token that matches no flag at all.
    """

    def __init__(
        self,
        objects: dict[str, FakeObject],
        macros: dict[str, str] | None = None,
        **tables: dict[str, FakeObject],
    ) -> None:
        self.tables = {"objects": objects, **tables}
        self.macros = macros or {}

    def has_macro(self, name: object) -> bool:
        return isinstance(name, str) and name in self.macros

    def get_macro(self, value: object) -> object:
        return self.macros.get(value, value) if isinstance(value, str) else value


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
                # One block stating the field twice, which the loader hands over as a list.
                # `RohanTheoden_mod_Summoned` spells its flags out and then adds `+SUMMONED` on
                # a line of its own, twenty lines further down.
                "RestatedChild": FakeObject(
                    {"KindOf": ["HERO SELECTABLE INFANTRY", "+SUMMONED"]},
                    parent_name="GondorBuildingFoundation",
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
                # Every animal in the tree writes its whole KindOf as one macro, so a reader
                # that does not expand answers "carries nothing" - and a live match then reads
                # a rabbit as a raider and a fish as a flag's defender.
                "Rabbit": FakeObject({"KindOf": "NATUREUNITS_KINDOF"}),
                # A delta whose token is a macro: the sign belongs to every flag it brings.
                "TameRabbit": FakeObject({"KindOf": "-NATUREUNITS_KINDOF"}, parent_name="Rabbit"),
                # A macro naming another, which is why expansion is a loop rather than a step.
                "AmbientNoise": FakeObject({"KindOf": "AMBIENT_KINDOF"}),
                # A creep lair: the flags of any ordinary structure, and a SpawnBehavior that
                # replaces every defender killed near it. Only the module tells them apart.
                "DunlandGoblinLair": FakeObject(
                    {"KindOf": "STRUCTURE IMMOBILE SELECTABLE IGNORE_FOR_VICTORY"},
                    modules=[
                        FakeModule({"Body": "ActiveBody"}),
                        FakeModule({"SpawnTemplateName": "Wildman_Slaved WildmanAxe_Slaved"}),
                    ],
                ),
                "DunlandGoblinLairSnow": FakeObject({}, parent_name="DunlandGoblinLair"),
                # A lair's defender: as selectable and as mobile as a battalion, and driven by
                # its master rather than by whoever owns it. So is the civilian an economy
                # building spawns, which is why this is what tells an army from a list.
                "Wildman_Slaved": FakeObject(
                    {"KindOf": "INFANTRY SELECTABLE"},
                    modules=[FakeModule({"Body": "ActiveBody"}), FakeModule({}, "SlavedUpdate")],
                ),
                "Wildman_SlavedSnow": FakeObject({}, parent_name="Wildman_Slaved"),
                # What the lair leaves behind, written the way the tree writes it: as a macro.
                "DunlandLairHole": FakeObject({"KindOf": "WILD_HOLE_KINDOF"}),
            },
            macros={
                "NATUREUNITS_KINDOF": "PRELOAD INFANTRY NOT_AUTOACQUIRABLE NO_BASE_CAPTURE INERT",
                "WILD_HOLE_KINDOF": "PRELOAD STRUCTURE IMMOBILE REBUILD_HOLE NOT_AUTOACQUIRABLE",
                "AMBIENT_KINDOF": "IMMOBILE NATUREUNITS_KINDOF",
            },
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


def test_a_block_restating_kindof_edits_rather_than_replaces(statics):
    """**Measured on `RohanTheoden_mod_Summoned`**, which spells its flags out and then adds
    `KindOf = +SUMMONED` on a line of its own. The field arrives as a list of both declarations,
    and stringifying that list produced tokens like `['HERO` and `SUMMONED',` - so Theoden
    answered no to `HERO`, `World.heroes` never saw him, and Glorious Charge was never fired."""
    kinds = statics.kind_of("RestatedChild")
    assert kinds == frozenset({"HERO", "SELECTABLE", "INFANTRY", "SUMMONED"})
    assert statics.has_kind("RestatedChild", "HERO")


def test_a_kindof_written_as_a_macro_expands(statics):
    """The whole declaration may be one `#define`, and then nothing at all reads directly.

    136 objects in RotWK+Edain are written this way. The flag that matters most is `INERT`,
    which is how a live match tells the map's wildlife from something that came to fight.
    """
    kinds = statics.kind_of("Rabbit")
    assert "INERT" in kinds
    assert "NO_BASE_CAPTURE" in kinds
    assert "NATUREUNITS_KINDOF" not in kinds
    assert statics.has_kind("Rabbit", "INERT")


def test_a_macro_naming_a_macro_expands_all_the_way(statics):
    kinds = statics.kind_of("AmbientNoise")
    assert "IMMOBILE" in kinds
    assert "INERT" in kinds
    assert not any(name.endswith("_KINDOF") for name in kinds)


def test_a_delta_on_a_macro_carries_its_sign_to_every_flag(statics):
    """`-SOME_MACRO` subtracts everything the macro brings, not a flag of that name."""
    kinds = statics.kind_of("TameRabbit")
    assert "INERT" not in kinds
    assert "NO_BASE_CAPTURE" not in kinds


def test_a_rebuild_hole_is_found_through_its_macro(statics):
    """The stump a razed lair leaves, which rebuilds it if nothing finishes the job.

    Written as `WILD_HOLE_KINDOF`, so this is the same expansion question - and getting it
    wrong means the hole is invisible, which reads in a match as lairs that come back.
    """
    assert statics.is_rebuild_hole("DunlandLairHole")
    assert not statics.is_rebuild_hole("DunlandGoblinLair")


def test_a_lair_is_told_by_its_spawn_module_not_its_flags(statics):
    """A lair carries exactly the `KindOf` an ordinary structure does. What is different is
    that it garrisons itself, which only the `SpawnBehavior` says."""
    assert statics.spawns("DunlandGoblinLair") == ("Wildman_Slaved", "WildmanAxe_Slaved")
    assert statics.kind_of("DunlandGoblinLair") == statics.kind_of("DunlandGoblinLairSnow")


def test_a_child_lair_inherits_the_module_it_does_not_restate(statics):
    assert statics.spawns("DunlandGoblinLairSnow") == ("Wildman_Slaved", "WildmanAxe_Slaved")


def test_a_slave_is_not_something_to_order(statics):
    """A lair's defender and a farm's civilian look exactly like a battalion in an observation.

    Selectable, mobile, a real body, owned by a player - and driven by their master, so an order
    addressed to one goes nowhere. A live match sent seven farm civilians to take a settlement.
    """
    assert statics.is_slaved("Wildman_Slaved")
    assert not statics.is_slaved("GondorFighterHorde")
    assert not statics.is_slaved("DunlandGoblinLair")


def test_a_child_inherits_the_slave_module_it_does_not_restate(statics):
    assert statics.is_slaved("Wildman_SlavedSnow")


def test_an_unknown_template_is_not_slaved(statics):
    assert not statics.is_slaved("SomethingThisBuildNeverHeardOf")


def test_a_building_that_spawns_nothing_answers_empty(statics):
    """Most templates. Empty rather than an error, so the caller can ask about anything."""
    assert statics.spawns("GondorWohnhaus") == ()
    assert statics.spawns("SomethingThisBuildNeverHeardOf") == ()


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


class FakeUpgrade:
    """The two members `Statics` reads off a loaded `Upgrade`.

    Attributes rather than raw fields, because the ini spells both as macros
    (`GONDOR_PERSONAL_HEAVY_ARMOR_BUILDCOST`, not `300`) and only the typed model expands
    them - so reading `.fields` here would test a path production does not take.
    """

    def __init__(self, cost: int, scope: str) -> None:
        self.BuildCost = cost
        self.Type = scope
        self.fields: dict[str, str] = {}


@pytest.fixture
def upgrades() -> Statics:
    """Gondor's real armour chain, which is two tiers and not one.

    The forge sells a `PLAYER` tech that touches no unit; the tech satisfies the
    `NeededUpgrade` of an `OBJECT` button on the battalion, which is where the armour lands.
    Both are modelled because buying only the first is the failure this exists to prevent.
    """
    return Statics(
        FakeGame(
            {
                "GondorForge": FakeObject({"CommandSet": "GondorForgeCommandSet"}),
                "GondorFighterHorde": FakeObject({"CommandSet": "GondorFighterHordeCommandSet"}),
                "GondorBarracks": FakeObject({"CommandSet": "GondorBarracksCommandSet"}),
                "GondorWohnhaus": FakeObject({"CommandSet": "GondorWohnhausCommandSet"}),
            },
            commandsets={
                "GondorForgeCommandSet": FakeObject({"3": "Command_PurchaseTechnologyHeavyArmor"}),
                "GondorFighterHordeCommandSet": FakeObject(
                    {"4": "Command_PurchaseUpgradeHeavyArmor"}
                ),
                "GondorBarracksCommandSet": FakeObject({"7": "Command_PurchaseLevel2"}),
                "GondorWohnhausCommandSet": FakeObject({"1": "Command_Sell"}),
            },
            commandbuttons={
                "Command_PurchaseTechnologyHeavyArmor": FakeObject(
                    {
                        "Command": "PLAYER_UPGRADE",
                        "Upgrade": "Upgrade_TechnologyGondorHeavyArmor",
                        "NeededUpgrade": "Upgrade_MarketplaceUpgradeIronOre",
                    }
                ),
                "Command_PurchaseUpgradeHeavyArmor": FakeObject(
                    {
                        "Command": "OBJECT_UPGRADE",
                        "Upgrade": "Upgrade_GondorHeavyArmor",
                        "NeededUpgrade": "Upgrade_TechnologyGondorHeavyArmor",
                    }
                ),
                "Command_PurchaseLevel2": FakeObject(
                    {"Command": "OBJECT_UPGRADE", "Upgrade": "Upgrade_GondorStructureLevel2"}
                ),
                "Command_Sell": FakeObject({"Command": "SELL"}),
            },
            upgrades={
                "Upgrade_TechnologyGondorHeavyArmor": FakeUpgrade(1000, "PLAYER"),
                "Upgrade_GondorHeavyArmor": FakeUpgrade(300, "OBJECT"),
                "Upgrade_GondorStructureLevel2": FakeUpgrade(400, "OBJECT"),
            },
        )
    )


def test_a_building_reports_the_upgrades_its_command_set_sells(upgrades):
    (armour,) = upgrades.upgrade_buttons("GondorForge")
    assert armour.upgrade == "Upgrade_TechnologyGondorHeavyArmor"
    assert armour.command_slot == 3
    assert armour.cost == 1000
    assert armour.needed_upgrades == ("Upgrade_MarketplaceUpgradeIronOre",)


def test_scope_comes_from_the_upgrade_block_not_the_button(upgrades):
    """The two tiers differ only by `Type`, and which one it is decides which live field
    answers "do I already have this" - the player's upgrades or the object's."""
    (tech,) = upgrades.upgrade_buttons("GondorForge")
    (personal,) = upgrades.upgrade_buttons("GondorFighterHorde")
    assert tech.player_scope
    assert not personal.player_scope
    assert personal.upgrade == "Upgrade_GondorHeavyArmor"


def test_the_battalion_upgrade_is_gated_on_the_faction_tech(upgrades):
    """Buying the forge tech and stopping is the failure this models: the tech touches no
    unit, and until the player holds it the battalion's own button is not offered."""
    (personal,) = upgrades.upgrade_buttons("GondorFighterHorde")
    assert not personal.enabled_for(frozenset())
    assert personal.enabled_for({"upgrade_technologygondorheavyarmor"})


def test_an_ungated_upgrade_is_always_offered(upgrades):
    (level2,) = upgrades.upgrade_buttons("GondorBarracks")
    assert level2.needed_upgrades == ()
    assert level2.enabled_for(frozenset())


def test_a_building_that_sells_nothing_reports_nothing(upgrades):
    """A non-upgrade button is not an upgrade with an empty name - `SELL` must not appear."""
    assert upgrades.upgrade_buttons("GondorWohnhaus") == ()
    assert upgrades.upgrade_buttons("SomethingThisBuildNeverHeardOf") == ()


def test_an_upgrade_this_build_does_not_define_costs_nothing(upgrades):
    assert upgrades.upgrade_cost("Upgrade_SomethingElse") == 0
    assert not upgrades.upgrade_is_player_scope("Upgrade_SomethingElse")


@pytest.fixture
def costs() -> Statics:
    """Objects priced the way the ini really prices them - through the typed model.

    The raw field carries a macro name (`GONDOR_SOLDIER_BUILDCOST`), which is why the fakes
    here set the expanded attribute instead: comparing the unexpanded string against a gold
    balance is nonsense rather than an error, so the accessor has to read the typed value.
    """
    priced = _link(
        {
            "GondorFighterHorde": FakeObject({"BuildCost": "GONDOR_SOLDIER_BUILDCOST"}),
            # The inheriting case: `CPObject` declares no cost and takes its parent's.
            "CPObject_Unlimited": FakeObject({}),
            "CPObject": FakeObject({}, parent_name="CPObject_Unlimited"),
            "FreeThing": FakeObject({}),
            "GondorRangerHorde": FakeObject(
                {"CommandPoints": "COMMAND_POINTS_HERO_ARCHER_5_HORDE"}
            ),
        }
    )
    priced["GondorFighterHorde"].BuildCost = 200
    priced["CPObject_Unlimited"].BuildCost = 500
    priced["GondorRangerHorde"].CommandPoints = 60
    priced["CPObject_Unlimited"].CommandPoints = 40
    return Statics(FakeGame(priced))


def test_a_build_cost_is_the_expanded_number_not_the_macro(costs):
    assert costs.build_cost("GondorFighterHorde") == 200
    assert costs.build_cost("gondorfighterhorde") == 200


def test_a_build_cost_is_inherited_from_the_parent(costs):
    """`CPObject` declares no cost of its own and is 500 because `CPObject_Unlimited` is."""
    assert costs.build_cost("CPObject") == 500


def test_an_object_this_build_does_not_price_costs_nothing(costs):
    """Zero rather than an error, so an unpriced template is never refused as unaffordable."""
    assert costs.build_cost("FreeThing") == 0
    assert costs.build_cost("SomethingThisBuildNeverHeardOf") == 0


def test_a_command_point_cost_is_the_expanded_number_not_the_macro(costs):
    """The other currency a recruit spends, and the one nothing used to price.

    The engine discards a recruit that would breach the command-point ceiling exactly as
    silently as an unaffordable one: 71 of 219 orders thrown away across one match, at a mean of
    46 free points against 409 for those that queued.
    """
    assert costs.command_point_cost("GondorRangerHorde") == 60
    assert costs.command_point_cost("gondorrangerhorde") == 60


def test_a_command_point_cost_is_inherited_from_the_parent(costs):
    assert costs.command_point_cost("CPObject") == 40


def test_an_object_that_charges_no_command_points_is_free(costs):
    """Zero means "charges nothing", so an unpriced template is never refused for headroom."""
    assert costs.command_point_cost("FreeThing") == 0
    assert costs.command_point_cost("SomethingThisBuildNeverHeardOf") == 0


@pytest.fixture
def producers() -> Statics:
    """A keep that sells `CPObject` and a barracks that does not.

    Every faction sells the command-point object through a differently-named button on a
    differently-named command set, so the only portable way to find a producer is to ask each
    building what it can build.
    """
    return Statics(
        FakeGame(
            {
                "GondorCastleBaseKeep": FakeObject({"CommandSet": "KeepCommandSet"}),
                "GondorBarracks": FakeObject({"CommandSet": "BarracksCommandSet"}),
                "GondorWohnhaus": FakeObject({"CommandSet": "WohnhausCommandSet"}),
            },
            commandsets={
                "KeepCommandSet": FakeObject({"1": "Command_CommandPoints", "2": "Command_Sell"}),
                "BarracksCommandSet": FakeObject({"1": "Command_Fighters"}),
                "WohnhausCommandSet": FakeObject({"1": "Command_Sell"}),
            },
            commandbuttons={
                "Command_CommandPoints": FakeObject(
                    {"Command": "UNIT_BUILD", "Object": "CPObject"}
                ),
                "Command_Fighters": FakeObject(
                    {"Command": "UNIT_BUILD", "Object": "GondorFighterHorde"}
                ),
                "Command_Sell": FakeObject({"Command": "SELL"}),
            },
        )
    )


def test_a_building_reports_what_it_can_build(producers):
    assert producers.recruits("GondorCastleBaseKeep") == frozenset({"cpobject"})
    assert producers.recruits("GondorBarracks") == frozenset({"gondorfighterhorde"})


def test_a_building_that_builds_nothing_reports_nothing(producers):
    """A `SELL` button is not a producer, and neither is an unknown template."""
    assert producers.recruits("GondorWohnhaus") == frozenset()
    assert producers.recruits("SomethingThisBuildNeverHeardOf") == frozenset()


#
# Unpack: which of the engine's two plot orders a target actually takes.
#
# This is modelled on `WirtschaftPlotFlag_Real` - Edain's **settlement**, not an "economy plot"
# whatever the name suggests - because it is the case that misled the library for a week. Its
# declared `CommandSet` offers one argument-less `CASTLE_UNPACK`, and no player ever sees that
# palette: owning the plot means holding a faction upgrade, and a `CommandSetUpgrade` swaps in
# explicit per-building buttons. Reading the static field said "send castle_unpack()"; the game
# sends `unpack(template)`.
#
# Settled twice on 2026-08-04. A hand-played Gondor match recorded four explicit orders naming
# `GondorFarm_Extern`, `GondorLeuchtfeuer` and `GondorRangerTents` - the three buttons
# reproduced below, in this slot order. Then the live game was watched doing the swap: the
# palette printed `EconomyFlagCommandSet` while the flag was neutral and
# `GondorEconomyPlotCommandSet` the moment `owner_index` flipped.

MEN = "Upgrade_MenFaction"
TOOLS = "Upgrade_EdainSiedlerWerkzeuge"


def command_set_upgrade(fields: dict[str, str]) -> CommandSetUpgrade:
    """A real `CommandSetUpgrade`, because `state` dispatches on the module's class."""
    module = object.__new__(CommandSetUpgrade)
    module._fields = fields
    return module


@pytest.fixture
def plots() -> Statics:
    return Statics(
        FakeGame(
            _link(
                {
                    "WirtschaftPlotFlag_Real": FakeObject(
                        {"CommandSet": "EconomyFlagCommandSet"},
                        modules=[
                            command_set_upgrade(
                                {"TriggeredBy": MEN, "CommandSet": "GondorEconomyPlotCommandSet"}
                            ),
                            command_set_upgrade(
                                {
                                    "TriggeredBy": f"{MEN} {TOOLS}",
                                    "RequiresAllTriggers": "Yes",
                                    "CommandSet": "GondorEconomyPlotCommandSet3",
                                }
                            ),
                        ],
                    ),
                    "GondorBarracks": FakeObject({"CommandSet": "BarracksCommandSet"}),
                }
            ),
            commandsets={
                "EconomyFlagCommandSet": FakeObject({"1": "Command_UnpackEconomyPlot"}),
                "GondorEconomyPlotCommandSet": FakeObject(
                    {"1": "Command_UnpackExplicitGondorFarm", "2": "Command_Sell"}
                ),
                "GondorEconomyPlotCommandSet3": FakeObject(
                    {"1": "Command_UnpackExplicitGondorFarm3"}
                ),
                "BarracksCommandSet": FakeObject({"1": "Command_Sell"}),
            },
            commandbuttons={
                "Command_UnpackEconomyPlot": FakeObject({"Command": "CASTLE_UNPACK"}),
                "Command_UnpackExplicitGondorFarm": FakeObject(
                    {
                        "Command": "CASTLE_UNPACK_EXPLICIT_OBJECT",
                        "Object": "GondorFarm_Extern",
                    }
                ),
                "Command_UnpackExplicitGondorFarm3": FakeObject(
                    {
                        "Command": "CASTLE_UNPACK_EXPLICIT_OBJECT",
                        "Object": "GondorFarm_Extern3",
                    }
                ),
                "Command_Sell": FakeObject({"Command": "SELL"}),
            },
        )
    )


def test_an_unclaimed_plot_offers_the_argument_less_claim(plots):
    (button,) = plots.unpack_buttons("WirtschaftPlotFlag_Real")
    assert button.command == CASTLE_UNPACK
    assert button.template is None
    assert not button.explicit


def test_owning_the_plot_replaces_that_claim_with_explicit_buttons(plots):
    """The whole bug in one assertion: the same plot, a real owner, the other order."""
    (button,) = plots.unpack_buttons("WirtschaftPlotFlag_Real", [MEN])
    assert button.explicit
    assert button.template == "GondorFarm_Extern"


def test_the_last_triggered_swap_wins(plots):
    """Edain layers economy techs on top of the faction palette, so a plot can be upgraded
    twice; the engine takes the last active module and so must this."""
    (button,) = plots.unpack_buttons("WirtschaftPlotFlag_Real", [MEN, TOOLS])
    assert button.template == "GondorFarm_Extern3"


def test_a_swap_needing_all_its_triggers_stays_off_without_them(plots):
    assert plots.live_command_set("WirtschaftPlotFlag_Real", [TOOLS]) == "EconomyFlagCommandSet"


def test_held_upgrades_are_matched_case_insensitively(plots):
    """A live observation's spelling is not the ini's, and everything else here folds case."""
    (button,) = plots.unpack_buttons("WirtschaftPlotFlag_Real", ["upgrade_menfaction"])
    assert button.template == "GondorFarm_Extern"


def test_a_non_unpack_button_is_not_reported(plots):
    """`Command_Sell` shares the claimed palette and is not a way to build on the plot."""
    buttons = plots.unpack_buttons("WirtschaftPlotFlag_Real", [MEN])
    assert [b.button for b in buttons] == ["Command_UnpackExplicitGondorFarm"]


def test_something_that_is_not_a_plot_offers_no_unpack(plots):
    assert plots.unpack_buttons("GondorBarracks", [MEN]) == ()
    assert plots.unpack_buttons("SomethingThisBuildNeverHeardOf", [MEN]) == ()


class FakeArmy(FakeObject):
    """An `ArmyDefinition` block, whose members are a nested attribute rather than a field.

    The real model exposes those through `__getattr__` off `_nested_data`; the two members
    `army_plan` reads are the name and that list, so a stand-in carries exactly those.
    """

    def __init__(self, name: str, fields: dict[str, str], members: list[FakeObject]) -> None:
        super().__init__(fields)
        self.name = name
        self.ArmyMemberDefinition = members


def _member(unit: str, one: str, two: str, three: str) -> FakeObject:
    return FakeObject(
        {
            "Unit": unit,
            "PercentageOfArmyPhase1": one,
            "PercentageOfArmyPhase2": two,
            "PercentageOfArmyPhase3": three,
        }
    )


@pytest.fixture
def armies() -> Statics:
    """Two definitions, shaped like the real file - suffixed durations, a repeated unit, and
    an entry no building sells."""
    return Statics(
        FakeGame(
            {},
            armydefinitions={
                "MenOfTheWestArmy": FakeArmy(
                    "MenOfTheWestArmy",
                    {
                        "Side": "Men",
                        "PhaseDuration_Rush": "300.0 ;//seconds from the start",
                        "PhaseDuration_MidGame": "400.0",
                    },
                    [
                        _member("GondorFighterHorde", "35.0", "25.0", "20.0"),
                        _member("GondorArcherHorde", "25.0", "20.0", "15.0"),
                        # A sub-faction unit no Gondor building offers. Kept by the reader and
                        # dropped later by the command-set filter, which is the only thing that
                        # can tell - the name gives nothing away.
                        _member("AmrothFighterHorde", "35.0", "25.0", "20.0"),
                    ],
                ),
                "MordorArmy": FakeArmy(
                    "MordorArmy",
                    {"Side": "Mordor", "PhaseDuration_MidGame": "540.0f"},
                    [
                        # Shares that sum to far more than 100, as the real file's do.
                        _member("MordorFighterHorde", "150.0", "140.0", "100.0"),
                        _member("MordorCirithOrkHorde", "10.0", "20.0", "30.0"),
                        # The same unit again in a second role, which `MordorArmy` really does.
                        _member("MordorCirithOrkHorde", "5.0", "5.0", "5.0"),
                        _member("", "1.0", "1.0", "1.0"),  # a member naming no unit
                    ],
                ),
            },
        )
    )


def test_an_army_is_found_by_side_not_by_block_name(armies):
    """A live observation reports `Men`; the block is called `MenOfTheWestArmy`."""
    army = armies.army_plan("Men")
    assert army is not None
    assert army.name == "MenOfTheWestArmy"
    assert [m.unit for m in army.members] == [
        "GondorFighterHorde",
        "GondorArcherHorde",
        "AmrothFighterHorde",
    ]


def test_the_side_match_folds_case(armies):
    assert armies.army_plan("men").name == "MenOfTheWestArmy"


def test_a_side_with_no_definition_is_none_not_an_error(armies):
    """Real: the mounted install defines nine armies and the mod tree eleven."""
    assert armies.army_plan("Arnor") is None


def test_phase_durations_survive_the_suffixes_the_file_writes(armies):
    """`300.0 ;//comment` and `540.0f` are both what the shipped file actually contains."""
    assert armies.army_plan("Men").rush_seconds == 300.0
    assert armies.army_plan("Mordor").midgame_seconds == 540.0


def test_a_missing_duration_falls_back_rather_than_raising(armies):
    """`MordorArmy` here declares no rush duration; the phase test still has to answer."""
    assert armies.army_plan("Mordor").rush_seconds == 300.0


def test_phases_run_rush_then_midgame_then_endgame(armies):
    army = armies.army_plan("Men")
    assert army.phase(0.0) == 0
    assert army.phase(299.0) == 0
    assert army.phase(300.0) == 1
    assert army.phase(699.0) == 1
    assert army.phase(700.0) == 2
    assert army.phase(10_000.0) == 2


def test_a_share_is_read_per_phase_and_clamped_to_the_three_that_exist(armies):
    fighter = armies.army_plan("Men").members[0]
    assert fighter.share(0) == 35.0
    assert fighter.share(2) == 20.0
    assert fighter.share(9) == 20.0
    assert fighter.share(-1) == 35.0


def test_a_member_naming_no_unit_is_dropped(armies):
    assert all(m.unit for m in armies.army_plan("Mordor").members)


def test_frames_per_second_defaults_to_the_engine_constant(armies):
    """RotWK + Edain declares no `FramesPerSecondLimit`, so the fallback is the live path."""
    assert armies.frames_per_second() == 30.0


def test_a_declared_frame_rate_limit_wins_over_the_constant():
    game = FakeGame({}, gamedatas={"GameData": FakeObject({"FramesPerSecondLimit": "24"})})
    assert Statics(game).frames_per_second() == 24.0


#
# A building's levels: the palette a structure shows is not the one its template declares.
#
# Edain builds a structure's levels as a chain of `CommandSetUpgrade` modules, and the chain is
# the case that made a bot buy one level and report the building fully upgraded: only the
# level-2 palette offers the level-3 button. The units are gated the other way round, by
# `NeededUpgrade` on the recruit button itself - so an unlevelled barracks was offering a
# battalion the engine then discarded in silence. Modelled on `GondorBarracks`, which does both.

LEVEL2 = "Upgrade_GondorStructureLevel2"
LEVEL3 = "Upgrade_GondorStructureLevel3_Barracks"
RANK2 = "Upgrade_StructureLevel2"


@pytest.fixture
def levels() -> Statics:
    return Statics(
        FakeGame(
            _link(
                {
                    "GondorBarracks": FakeObject(
                        {"CommandSet": "BarracksCommandSet"},
                        modules=[
                            command_set_upgrade(
                                {"TriggeredBy": LEVEL2, "CommandSet": "BarracksCommandSetLevel2"}
                            ),
                            command_set_upgrade(
                                {"TriggeredBy": LEVEL3, "CommandSet": "BarracksCommandSetLevel3"}
                            ),
                        ],
                    ),
                }
            ),
            commandsets={
                "BarracksCommandSet": FakeObject(
                    {"1": "Command_Fighters", "2": "Command_Guards", "7": "Command_Level2"}
                ),
                "BarracksCommandSetLevel2": FakeObject(
                    {"1": "Command_Fighters", "2": "Command_Guards", "7": "Command_Level3"}
                ),
                "BarracksCommandSetLevel3": FakeObject(
                    {"1": "Command_Fighters", "2": "Command_Guards"}
                ),
            },
            commandbuttons={
                "Command_Fighters": FakeObject(
                    {"Command": "UNIT_BUILD", "Object": "GondorFighterHorde"}
                ),
                "Command_Guards": FakeObject(
                    {
                        "Command": "UNIT_BUILD",
                        "Object": "GondorWachterderVesteHorde",
                        "NeededUpgrade": RANK2,
                    }
                ),
                "Command_Level2": FakeObject({"Command": "OBJECT_UPGRADE", "Upgrade": LEVEL2}),
                "Command_Level3": FakeObject({"Command": "OBJECT_UPGRADE", "Upgrade": LEVEL3}),
            },
            upgrades={LEVEL2: FakeUpgrade(400, "OBJECT"), LEVEL3: FakeUpgrade(800, "OBJECT")},
        )
    )


def test_a_gated_unit_is_not_offered_before_its_level(levels):
    """The button exists on the palette and the control bar would show it greyed out. Ordering
    it anyway is an order the engine consumes and discards without a word."""
    assert levels.recruits("GondorBarracks") == frozenset({"gondorfighterhorde"})


def test_the_level_unlocks_the_unit_it_gates(levels):
    assert levels.recruits("GondorBarracks", [RANK2]) == frozenset(
        {"gondorfighterhorde", "gondorwachterdervestehorde"}
    )


def test_only_the_level_two_palette_offers_level_three(levels):
    """The failure this models: a bot buys level 2, reads the declared command set again, finds
    the one button it already holds, and reports the building as fully upgraded for ever."""
    (first,) = levels.upgrade_buttons("GondorBarracks")
    assert first.upgrade == LEVEL2
    (second,) = levels.upgrade_buttons("GondorBarracks", [LEVEL2])
    assert second.upgrade == LEVEL3
    assert second.cost == 800
    assert levels.upgrade_buttons("GondorBarracks", [LEVEL2, LEVEL3]) == ()


def test_reachable_recruits_answers_for_the_whole_ladder(levels):
    """What a pre-match report wants: not what this building sells now, but what the plan can
    get to over a match. `recruits` deliberately answers the other question."""
    assert levels.reachable_recruits("GondorBarracks") == frozenset(
        {"gondorfighterhorde", "gondorwachterdervestehorde"}
    )


#
# Counters: what beats what, read off the engine's own damage types and armour tables.
#
# Nothing here names a matchup. A weapon declares a `DamageType` and an armour block prices
# every type against itself, so "pikes beat cavalry" is `SPECIALIST` against
# `EdainCavalryArmor`'s 170% - a fact about this mod's balance that a hand-written counter table
# would have to be kept in step with by hand. The percentages below are the shipped ones.


class FakeNugget:
    def __init__(self, fields: dict[str, str]) -> None:
        self.fields = fields


class FakeWeapon:
    def __init__(self, *nuggets: FakeNugget) -> None:
        self.fields: dict[str, str] = {}
        self.Nuggets = list(nuggets)


class FakeSet:
    """A `WeaponSet` or `ArmorSet` sub-block, which is neither a field nor a module."""

    def __init__(self, **fields: object) -> None:
        self.fields = fields


class FakeFighter(FakeObject):
    def __init__(
        self,
        weapon_sets: list[FakeSet] | None = None,
        armor_sets: list[FakeSet] | None = None,
    ) -> None:
        super().__init__({})
        self.WeaponSet = weapon_sets or []
        self.ArmorSet = armor_sets or []


def horde(payload: str) -> FakeObject:
    """A battalion carries no weapon of its own - the fifteen soldiers inside it do."""
    return FakeObject(
        {"KindOf": "HORDE"},
        modules=[FakeModule({"InitialPayload": f"{payload} 15"}, name="HordeContain")],
    )


@pytest.fixture
def counters() -> Statics:
    return Statics(
        FakeGame(
            _link(
                {
                    "GondorSpearmanHorde": horde("GondorSpearman"),
                    "GondorFighterHorde": horde("GondorFighter"),
                    "GondorArcherHorde": horde("GondorArcher"),
                    "MordorMorgulriderHorde": horde("MordorMorgulrider"),
                    "MordorFighterHorde": horde("MordorFighter"),
                    "GondorSpearman": FakeFighter(
                        [FakeSet(Conditions="None", Weapon="PRIMARY GondorPikemanWeapon")],
                        [FakeSet(Conditions="None", Armor="EdainPikemanArmor")],
                    ),
                    "GondorFighter": FakeFighter(
                        [
                            FakeSet(Conditions="None", Weapon="PRIMARY GondorSword"),
                            # The upgraded set, which must not blur the base answer.
                            FakeSet(Conditions="PLAYER_UPGRADE", Weapon="PRIMARY GondorSiegeSword"),
                        ],
                        [FakeSet(Conditions="None", Armor="EdainInfantryArmor")],
                    ),
                    # Ranged: the bow carries no damage at all, its warhead does.
                    "GondorArcher": FakeFighter(
                        [FakeSet(Conditions="None", Weapon="PRIMARY GondorArcherBow")],
                        [FakeSet(Conditions="None", Armor="EdainInfantryArmor")],
                    ),
                    "MordorMorgulrider": FakeFighter(
                        [FakeSet(Conditions="None", Weapon="PRIMARY MordorCavalryLance")],
                        [FakeSet(Conditions="None", Armor="EdainCavalryArmor")],
                    ),
                    "MordorFighter": FakeFighter(
                        [FakeSet(Conditions="None", Weapon="PRIMARY MordorWarriorAxe")],
                        [FakeSet(Conditions="None", Armor="EdainInfantryArmor")],
                    ),
                    "NobodyHasHeardOfThis": FakeObject({}),
                }
            ),
            weapons={
                "GondorPikemanWeapon": FakeWeapon(FakeNugget({"DamageType": "SPECIALIST"})),
                "GondorSword": FakeWeapon(FakeNugget({"DamageType": "SLASH"})),
                "GondorSiegeSword": FakeWeapon(FakeNugget({"DamageType": "SIEGE"})),
                "MordorCavalryLance": FakeWeapon(FakeNugget({"DamageType": "CAVALRY"})),
                "MordorWarriorAxe": FakeWeapon(FakeNugget({"DamageType": "SLASH"})),
                "GondorArcherBow": FakeWeapon(
                    FakeNugget({"WarheadTemplateName": "GondorArcherBowWarhead"})
                ),
                "GondorArcherBowWarhead": FakeWeapon(FakeNugget({"DamageType": "PIERCE"})),
            },
            armorsets={
                "EdainPikemanArmor": FakeObject(
                    {"Armor": ["DEFAULT 100%", "SLASH 150%", "CAVALRY 40%", "SPECIALIST 100%"]}
                ),
                "EdainInfantryArmor": FakeObject(
                    {"Armor": ["DEFAULT 100%", "SLASH 100%", "CAVALRY 135%", "SPECIALIST 65%"]}
                ),
                "EdainCavalryArmor": FakeObject(
                    {"Armor": ["DEFAULT 100%", "SLASH 30%", "CAVALRY 100%", "SPECIALIST 170%"]}
                ),
            },
        )
    )


def test_a_battalions_weapon_is_read_off_the_soldiers_inside_it(counters):
    """`GondorSpearmanHorde` has a `HordeContain` and no weapon of its own; asking the container
    answers "this thing cannot fight" for every battalion in the game."""
    assert counters.fighting_template("GondorSpearmanHorde") == "GondorSpearman"
    assert counters.damage_types("GondorSpearmanHorde") == frozenset({"SPECIALIST"})


def test_only_the_unconditional_weapon_set_is_read(counters):
    """The upgraded and alternate-formation sets describe a unit nobody has bought anything for
    yet, and unioning them blurs the baseline two units are compared on."""
    assert counters.damage_types("GondorFighterHorde") == frozenset({"SLASH"})


def test_a_projectile_is_followed_to_the_warhead_that_carries_the_damage(counters):
    """`GondorArcherBow` is a `ProjectileNugget` and declares no `DamageType` at all."""
    assert counters.damage_types("GondorArcherHorde") == frozenset({"PIERCE"})


def test_armour_prices_every_damage_type_against_the_unit(counters):
    armour = counters.armour("MordorMorgulriderHorde")
    assert armour["SPECIALIST"] == pytest.approx(1.7)
    assert armour["SLASH"] == pytest.approx(0.3)


def test_pikes_beat_cavalry_and_lose_to_infantry(counters):
    """The whole point: this is the shipped balance, not a rule this repo wrote down."""
    assert counters.effectiveness("GondorSpearmanHorde", "MordorMorgulriderHorde") == pytest.approx(
        1.7
    )
    assert counters.effectiveness("GondorSpearmanHorde", "MordorFighterHorde") == pytest.approx(
        0.65
    )


def test_swords_beat_pikes_and_cavalry_beats_swords(counters):
    assert counters.effectiveness("GondorFighterHorde", "GondorSpearmanHorde") == pytest.approx(1.5)
    assert counters.effectiveness("MordorMorgulriderHorde", "MordorFighterHorde") == pytest.approx(
        1.35
    )


def test_an_unreadable_matchup_is_even_rather_than_bad(counters):
    """An unknown template is not evidence of a good matchup or a bad one, and weighting a build
    order by zero would retire a unit on the strength of a missing definition."""
    assert counters.effectiveness("GondorSpearmanHorde", "NobodyHasHeardOfThis") == 1.0
    assert counters.effectiveness("NobodyHasHeardOfThis", "MordorMorgulriderHorde") == 1.0


def test_a_type_the_armour_block_omits_falls_back_to_default(counters):
    """`DEFAULT` is the engine's own fallback, which is why `armour` keeps it in the mapping
    rather than applying it while reading."""
    assert counters.effectiveness("GondorArcherHorde", "MordorMorgulriderHorde") == pytest.approx(
        1.0
    )


class FakeScience:
    """The four members `Statics` reads off a loaded `Science`.

    Attributes rather than raw fields, for the reason `FakeUpgrade` records: the cost is spelled
    as a macro (`GOOD_RANK_1_COST`) and only the typed model expands it. `PrerequisiteSciences`
    arrives already parsed into alternative all-required groups, which is what `sage_ini`'s
    `ScienceRequirements` produces - `A OR B C` is `[[A], [B, C]]`, not a flat list.
    """

    def __init__(
        self,
        cost: int,
        groups: tuple[tuple[str, ...], ...] = (),
        grantable: bool = True,
    ) -> None:
        self.SciencePurchasePointCostMP = cost
        self.PrerequisiteSciences = [list(group) for group in groups]
        self.IsGrantable = grantable
        self.fields: dict[str, str] = {}


# Gondor's opening rows, as the tree writes them: two powers unlocked by the faction's own
# intrinsic science, one gated behind the first of those, and the padding every book carries.
# `SCIENCE_GOOD` is the single-player intrinsic and is never held in a skirmish, which is why
# the alternative groups matter - reading the expression as a flat list opens the whole book.
SPELLBOOK = {
    1: ("Command_PurchaseSpellBaumeisterGondors", "SCIENCE_RebuildMen"),
    2: ("Command_PurchaseSpellHornGondors", "SCIENCE_HornMen"),
    3: ("Command_PurchaseSpellLoneTowerMen_Edain", "SCIENCE_EinsamerTurmMen"),
    4: ("Command_PurchaseSpellEmpty", "SCIENCE_Empty"),
}


@pytest.fixture
def spellbook() -> Statics:
    return Statics(
        FakeGame(
            {},
            commandsets={
                "GondorSpellStoreCommandSet": FakeObject(
                    {str(slot): button for slot, (button, _) in SPELLBOOK.items()}
                )
            },
            commandbuttons={
                button: FakeObject({"Command": "PURCHASE_SCIENCE", "Science": science})
                for button, science in SPELLBOOK.values()
            },
            sciences={
                "SCIENCE_RebuildMen": FakeScience(
                    1, (("SCIENCE_GOOD",), ("SCIENCE_MEN",), ("SCIENCE_ARNOR",))
                ),
                "SCIENCE_HornMen": FakeScience(
                    1, (("SCIENCE_GOOD",), ("SCIENCE_MEN",), ("SCIENCE_ARNOR",))
                ),
                "SCIENCE_EinsamerTurmMen": FakeScience(
                    2, (("SCIENCE_GOOD",), ("SCIENCE_MEN", "SCIENCE_RebuildMen"))
                ),
                # The padding: not grantable, and its one group asks for both alignments at once.
                "SCIENCE_Empty": FakeScience(
                    111, (("SCIENCE_EVIL", "SCIENCE_GOOD"),), grantable=False
                ),
            },
            factions={
                "FactionMen": FakeObject(
                    {
                        "Side": "Men",
                        "PlayableSide": "Yes",
                        "IntrinsicSciences": "SCIENCE_GOOD",
                        "IntrinsicSciencesMP": "SCIENCE_MEN",
                        "PurchaseScienceCommandSetMP": "GondorSpellStoreCommandSet",
                    }
                )
            },
        )
    )


def test_the_spell_store_is_read_off_the_faction_by_side(spellbook):
    """A live observation reports `Men`, not `FactionMen` - the same lookup `hero_roster` needs."""
    assert [p.science for p in spellbook.spell_store("Men")] == [
        "SCIENCE_RebuildMen",
        "SCIENCE_HornMen",
        "SCIENCE_EinsamerTurmMen",
        "SCIENCE_Empty",
    ]
    assert spellbook.spell_store("FactionMen") == spellbook.spell_store("Men")
    assert spellbook.spell_store("Mordor") == ()


def test_the_multiplayer_intrinsic_science_is_the_one_a_skirmish_starts_with(spellbook):
    """`SCIENCE_GOOD` is the campaign's and is never held in a skirmish. Reading it would report
    every tier-1 power as already unlocked by something the player does not have."""
    assert spellbook.intrinsic_sciences("Men") == ("SCIENCE_MEN",)


def test_the_padding_slots_are_excluded_by_what_the_data_says(spellbook):
    """Every book is padded to twenty with `Command_PurchaseSpellEmpty`. Nothing here matches on
    the name: `SCIENCE_Empty` is not grantable, and its prerequisite group asks for both
    alignments at once, so no player ever satisfies it."""
    store = {p.science: p for p in spellbook.spell_store("Men")}
    assert not store["SCIENCE_Empty"].purchasable
    assert not store["SCIENCE_Empty"].enabled_for(frozenset({"science_good", "science_men"}))
    assert store["SCIENCE_RebuildMen"].purchasable


def test_a_power_opens_when_any_one_prerequisite_group_is_fully_held(spellbook):
    """`OR` separates alternatives and whitespace is *and*. Read as a flat list, the whole book
    is open from frame one; read as one big group, none of it ever opens."""
    store = {p.science: p for p in spellbook.spell_store("Men")}
    start = frozenset({"science_men"})
    assert store["SCIENCE_RebuildMen"].enabled_for(start)
    assert not store["SCIENCE_EinsamerTurmMen"].enabled_for(start)
    assert store["SCIENCE_EinsamerTurmMen"].enabled_for(start | {"science_rebuildmen"})
    # The campaign route is a group of its own, and holding it alone is enough.
    assert store["SCIENCE_EinsamerTurmMen"].enabled_for(frozenset({"science_good"}))


def test_the_multiplayer_price_is_the_one_read(spellbook):
    """The two costs differ for nearly every power in the tree, and a skirmish is multiplayer."""
    assert [p.cost for p in spellbook.spell_store("Men")] == [1, 1, 2, 111]


class FakePower:
    """The members `Statics` reads off a loaded `SpecialPower`.

    Split across typed attributes and raw fields exactly as the real model splits them:
    `ReloadTime` is spelled as a macro in the tree (`SPELL_RECHARGE_TIME_TIER_1_NORMAL`) so only
    the typed accessor expands it, while `RadiusCursorRadius` is read raw. `RequiredSciences`
    arrives already parsed into alternative groups - and it is a *different key* from a
    `Science`'s `PrerequisiteSciences`, which is the whole reason `_science_groups` takes one.
    """

    def __init__(self, reload_ms: int = 0, radius: float = 0.0, sciences: tuple = ()) -> None:
        self.ReloadTime = reload_ms
        self.RequiredSciences = [[s] for s in sciences]
        self.fields: dict[str, str] = {}
        if radius:
            self.fields["RadiusCursorRadius"] = str(radius)


class FakeOCL:
    """An `ObjectCreationList`: one `CreateObject` entry naming templates."""

    def __init__(self, *templates: str) -> None:
        self.CreateObject = [FakeObject({"ObjectNames": " ".join(templates)})]
        self.fields: dict[str, str] = {}


# A book with one of every shape, because the classification is the point and each shape is read
# by a different field. Slot 9 is not a SPELL_BOOK button at all - the walk must skip it.
BOOK = {
    1: ("Command_Rebuild", "SpellBookRebuild", "NEED_TARGET_POS"),
    2: ("Command_Horn", "SpellBookRallyingCall", "NEED_TARGET_POS"),
    3: ("Command_Eagles", "SpellBookAdler", "NEED_TARGET_POS"),
    4: ("Command_Tower", "SpellBookLoneTower", "NEED_TARGET_POS"),
    5: ("Command_Volley", "SpellBookArrowVolley", "NEED_TARGET_POS"),
    6: ("Command_Aid", "SpellBookBeistand", "NEED_TARGET_POS"),
    7: ("Command_Grond", "SpellBookGrond", "NEED_TARGET_POS"),
    8: ("Command_Gandalf", "SpellBookGandalf", "NONPRESSABLE"),
    9: ("Command_Sell", "", ""),
}


@pytest.fixture
def book() -> Statics:
    spellbook = FakeObject(
        {"CommandSet": "GondorSpellBookCommandSet"},
        modules=[
            FakeModule({"SpecialPowerTemplate": "SpellBookRebuild", "HealAffects": "STRUCTURE"}),
            FakeModule(
                {
                    "SpecialPowerTemplate": "SpellBookRallyingCall",
                    "AttributeModifier": "RallyModifier",
                    "AttributeModifierAffects": "HORN_BUFF_FILTER",
                    "AttributeModifierRange": "100",
                }
            ),
            FakeModule({"SpecialPowerTemplate": "SpellBookAdler", "OCL": "OCL_SpawnAdler"}),
            FakeModule({"SpecialPowerTemplate": "SpellBookLoneTower", "OCL": "OCL_Tower"}),
            FakeModule(
                {
                    "SpecialPowerTemplate": "SpellBookArrowVolley",
                    "OCL": "OCL_BombardEgg",
                    "NearestSecondaryObjectFilter": "NONE +STRUCTURE ENEMIES",
                }
            ),
            FakeModule({"SpecialPowerTemplate": "SpellBookBeistand", "OCL": "OCL_AidEgg"}),
            FakeModule({"SpecialPowerTemplate": "SpellBookGrond", "OCL": "OCL_GrondPing"}),
            # A granted upgrade names no OCL, no modifier and no heal: it changes the player.
            FakeModule({"SpecialPowerTemplate": "SpellBookGandalf", "UpgradeName": "Upgrade_X"}),
        ],
    )
    return Statics(
        FakeGame(
            {
                "GondorSpellBook": spellbook,
                # A summon ends at something with an army KindOf...
                "Gwaihir_Summoned": FakeObject({"KindOf": "MONSTER SELECTABLE"}),
                # ...a build at a structure...
                "SentryTower": FakeObject({"KindOf": "STRUCTURE IMMOBILE"}),
                # ...and a strike at scenery that carries the weapon. The bombard goes through
                # an egg, which is how every one of these is really written.
                "BombardEgg": FakeObject(
                    {"KindOf": "UNATTACKABLE"},
                    modules=[FakeModule({"OCL": "FINAL OCL_BombardSeed"}, "SlowDeathBehavior")],
                ),
                "BombardSeed": FakeObject({"KindOf": "UNATTACKABLE"}),
                # A friendly effect delivered the same way a hostile one is - the only thing
                # telling them apart is the relationship token on the created object's filter.
                "AidEgg": FakeObject(
                    {"KindOf": "UNATTACKABLE"},
                    modules=[
                        FakeModule(
                            {"ObjectFilter": "ANY +GondorLeuchtfeuer SAME_PLAYER"}, "AttachUpdate"
                        )
                    ],
                ),
                # And one that names no side anywhere.
                "GrondPing": FakeObject({"KindOf": "UNATTACKABLE"}),
            },
            macros={"HORN_BUFF_FILTER": "ANY +HORDE +INFANTRY -HERO"},
            commandsets={
                "GondorSpellBookCommandSet": FakeObject(
                    {str(slot): button for slot, (button, _, _) in BOOK.items()}
                )
            },
            commandbuttons={
                button: FakeObject(
                    {"Command": "SPELL_BOOK" if power else "SELL"}
                    | ({"SpecialPower": power} if power else {})
                    | ({"Options": options} if options else {})
                )
                for button, power, options in BOOK.values()
            },
            specialpowers={
                "SpellBookRebuild": FakePower(180000, 150.0, ("SCIENCE_RebuildMen",)),
                "SpellBookRallyingCall": FakePower(180000, 75.0, ("SCIENCE_HornMen",)),
                "SpellBookAdler": FakePower(630000, 100.0, ("SCIENCE_Adler",)),
                "SpellBookLoneTower": FakePower(360000, 60.0, ("SCIENCE_Turm",)),
                "SpellBookArrowVolley": FakePower(360000, 95.0, ("SCIENCE_Volley",)),
                "SpellBookBeistand": FakePower(370000, 40.0, ("SCIENCE_Beistand",)),
                "SpellBookGrond": FakePower(940000, 40.0, ("SCIENCE_Grond",)),
                "SpellBookGandalf": FakePower(0, 0.0, ("SCIENCE_Gandalf",)),
            },
            objectcreationlists={
                "OCL_SpawnAdler": FakeOCL("Gwaihir_Summoned"),
                "OCL_Tower": FakeOCL("SentryTower"),
                "OCL_BombardEgg": FakeOCL("BombardEgg"),
                "OCL_BombardSeed": FakeOCL("BombardSeed"),
                "OCL_AidEgg": FakeOCL("AidEgg"),
                "OCL_GrondPing": FakeOCL("GrondPing"),
            },
            factions={
                "FactionMen": FakeObject(
                    {"Side": "Men", "PlayableSide": "Yes", "SpellBookMp": "GondorSpellBook"}
                )
            },
        )
    )


def test_the_book_is_the_spellbook_objects_command_set_not_the_stores(book):
    """Two different command sets on two different things: the store sells, the book casts."""
    assert [p.power for p in book.spell_book("Men")] == [
        "SpellBookRebuild",
        "SpellBookRallyingCall",
        "SpellBookAdler",
        "SpellBookLoneTower",
        "SpellBookArrowVolley",
        "SpellBookBeistand",
        "SpellBookGrond",
        "SpellBookGandalf",
    ]


def test_a_button_that_is_not_a_cast_is_skipped(book):
    """Slot 9 sells. A book is not made only of powers."""
    assert all(p.button != "Command_Sell" for p in book.spell_book("Men"))


def test_the_cast_form_comes_from_the_buttons_options(book):
    """A power sent through the wrong constructor is accepted, does nothing, and reports
    nothing - so the form is read rather than guessed from what the spell sounds like."""
    forms = {p.power: p.form for p in book.spell_book("Men")}
    assert forms["SpellBookRebuild"] == "location"
    assert forms["SpellBookGandalf"] == "passive"


def test_a_power_with_no_target_and_no_recharge_is_passive(book):
    """Both halves are needed. It was bought, it fired once, and it is never an order again."""
    gandalf = next(p for p in book.spell_book("Men") if p.power == "SpellBookGandalf")
    assert not gandalf.castable
    assert gandalf.effect == "grant"


def test_the_science_is_read_from_the_powers_own_key(book):
    """A `SpecialPower` gates itself with `RequiredSciences` and a `Science` with
    `PrerequisiteSciences`. Reading the wrong one returns nothing - which has the shape of a
    power that needs no science at all, the most permissive possible wrong answer."""
    rebuild = next(p for p in book.spell_book("Men") if p.power == "SpellBookRebuild")
    assert rebuild.sciences == ("SCIENCE_RebuildMen",)
    assert rebuild.enabled_for(frozenset({"science_rebuildmen"}))
    assert not rebuild.enabled_for(frozenset({"science_hornmen"}))


def test_recharge_is_read_in_seconds_from_the_engines_milliseconds(book):
    """The tier macros are milliseconds - 180000 is three minutes, not three."""
    rebuild = next(p for p in book.spell_book("Men") if p.power == "SpellBookRebuild")
    assert rebuild.reload_seconds == pytest.approx(180.0)


def test_a_heal_and_a_buff_are_told_apart_by_their_own_field(book):
    """Not by the module's class name: a mod may implement either through a class this has
    never heard of, and `HealAffects` / `AttributeModifier` still say which it is."""
    powers = {p.power: p for p in book.spell_book("Men")}
    assert powers["SpellBookRebuild"].effect == "heal"
    assert powers["SpellBookRebuild"].affects == ("STRUCTURE",)
    assert powers["SpellBookRallyingCall"].effect == "buff"
    # The filter is a macro, and expanding it is what keeps the flags readable.
    assert "+HORDE" in powers["SpellBookRallyingCall"].affects


def test_a_summon_is_known_by_what_it_finally_puts_on_the_map(book):
    """Not by the module - a summon and a bombardment are the same `OCLSpecialPower`. What
    separates them is that one chain ends at units and the other at scenery."""
    powers = {p.power: p for p in book.spell_book("Men")}
    assert powers["SpellBookAdler"].effect == "summon"
    assert powers["SpellBookAdler"].spawns == ("Gwaihir_Summoned",)
    assert not powers["SpellBookAdler"].hostile, "a summon has no side; it goes where it is aimed"
    assert powers["SpellBookLoneTower"].effect == "build"


def test_a_bombardment_is_followed_through_its_egg(book):
    """One hop answers "this power creates an egg", which is true and useless."""
    volley = next(p for p in book.spell_book("Men") if p.power == "SpellBookArrowVolley")
    assert volley.effect == "strike"
    assert volley.hostile
    assert "BombardSeed" in volley.spawns, "the chain must be followed past the egg"


def test_a_friendly_effect_delivered_like_a_hostile_one_is_not_a_strike(book):
    """The case that made this read the chain's filters at all: an aid spell creates an
    `UNATTACKABLE` egg and fires a weapon from it, exactly as a bombardment does. Only the
    `SAME_PLAYER` on the egg's own filter says it is pointed at your side."""
    aid = next(p for p in book.spell_book("Men") if p.power == "SpellBookBeistand")
    assert aid.effect == "buff"
    assert not aid.hostile


def test_a_power_no_field_can_place_is_unknown_rather_than_guessed(book):
    """A wrong guess spends a recharge measured in minutes on helping the wrong army, so a
    chain that names no side anywhere is reported as unreadable and a policy can decline it."""
    grond = next(p for p in book.spell_book("Men") if p.power == "SpellBookGrond")
    assert grond.effect == "unknown"
    assert grond.spawns == ("GrondPing",)


def test_an_ocl_cycle_terminates(book):
    """`OCL_SpawnEagles` recreates its own members in the real tree, so the walk is guarded
    rather than trusting the data to be a tree."""
    looping = Statics(
        FakeGame(
            {"Egg": FakeObject({}, modules=[FakeModule({"OCL": "FINAL OCL_Loop"})])},
            objectcreationlists={"OCL_Loop": FakeOCL("Egg")},
        )
    )
    assert looping.creates("OCL_Loop") == ("Egg",)


def test_a_faction_with_no_spellbook_object_has_no_book(book):
    assert book.spell_book("Mordor") == ()


@pytest.fixture
def crushing() -> Statics:
    """A knight battalion, a pike battalion, and the ways the tree writes them down.

    Every awkwardness here is one the real tree has. The crush levels sit on the horde container
    *and* on its payload and the two disagree; the resist is a module on the payload only,
    because the container's body is an `ImmortalBody` that carries nothing; and a pike battalion
    routinely declares no resist at all, which is why `PIKE` is a separate question.
    """
    return Statics(
        FakeGame(
            {
                # The container is what an order is addressed to and what carries the physics.
                "GondorKnightHorde": FakeObject(
                    {
                        "KindOf": "SELECTABLE CAVALRY HORDE",
                        "CrusherLevel": "1",
                        "CrushableLevel": "2",
                    },
                    modules=[FakeModule({"InitialPayload": "GondorCavalry 4"})],
                ),
                # The payload disagrees about how hard it is to crush - 3 against the horde's 2.
                "GondorCavalry": FakeObject(
                    {"KindOf": "CAVALRY INFANTRY SELECTABLE", "CrushableLevel": "3"}
                ),
                "GondorFighterHorde": FakeObject(
                    {"KindOf": "SELECTABLE INFANTRY HORDE", "CrusherLevel": "0"},
                    modules=[FakeModule({"InitialPayload": "GondorFighter 15"})],
                ),
                "GondorFighter": FakeObject({"KindOf": "INFANTRY SELECTABLE"}),
                # A braced spear line: the resist is on the payload's body, and the trailing
                # semicolon is how the tree actually writes the value.
                "MordorPikemanHorde": FakeObject(
                    {"KindOf": "SELECTABLE INFANTRY HORDE PIKE", "CrushableLevel": "0"},
                    modules=[FakeModule({"InitialPayload": "MordorPikeman 15"})],
                ),
                "MordorPikeman": FakeObject(
                    {"KindOf": "INFANTRY SELECTABLE PIKE"},
                    modules=[
                        FakeModule({"CrusherLevelResisted": "1;"}, "PorcupineFormationBodyModule")
                    ],
                ),
                # A siege engine is neither a horde nor crushable by a horse.
                "MordorCatapult": FakeObject(
                    {"KindOf": "SELECTABLE SIEGEENGINE VEHICLE", "CrushableLevel": "2"}
                ),
                # A child that restates none of it, which is most of the tree.
                "GondorKnightHorde_Summoned": FakeObject({}, parent_name="GondorKnightHorde"),
                # A mounted hero: the crush level is on the unit itself, not on a container.
                "RohanTheoden": FakeObject(
                    {"KindOf": "HERO CAVALRY SELECTABLE", "CrusherLevel": "1"}
                ),
                "NoCrushFieldsAtAll": FakeObject({"KindOf": "INFANTRY SELECTABLE"}),
            }
        )
    )


def test_a_horde_crushes_by_its_containers_level(crushing):
    """The container is the object that moves, so it is the one asked."""
    assert crushing.crusher_level("GondorKnightHorde") == 1
    assert crushing.crusher_level("GondorFighterHorde") == 0


def test_a_unit_that_is_not_a_horde_answers_for_itself(crushing):
    assert crushing.crusher_level("RohanTheoden") == 1


def test_a_child_inherits_the_crush_levels_it_does_not_restate(crushing):
    """Most of the tree is `ChildObject`s that restate nothing, and a summoned or veteran
    variant of a knight battalion still crushes. The payload hop is deliberately not asserted
    here: `sage_ini` folds a parent's modules onto the child at load, so on the real tree
    `AmrothKnightHorde_Summoned` resolves `AmrothCavalry` and reads 3, and a hand-built stand-in
    that reproduced that would only be testing itself."""
    assert crushing.crusher_level("GondorKnightHorde_Summoned") == 1
    assert crushing.crushable_level("GondorKnightHorde_Summoned") == 2


def test_the_higher_of_the_hordes_and_its_members_crushable_level_wins(crushing):
    """They disagree in the real tree - 2 on `GondorKnightHorde` and 3 on `GondorCavalry` - and
    the larger is the safe direction: a charge declined costs one order, a charge into something
    that does not go down costs the battalion."""
    assert crushing.crushable_level("GondorKnightHorde") == 3


def test_a_template_declaring_nothing_reads_as_crushing_nothing(crushing):
    assert crushing.crusher_level("NoCrushFieldsAtAll") == 0
    assert crushing.crushable_level("NoCrushFieldsAtAll") == 0
    assert crushing.crush_resisted("NoCrushFieldsAtAll") == 0


def test_the_resist_is_read_off_the_payloads_body(crushing):
    """The container's body carries nothing, so asking it alone answers zero for every pike in
    the game - and the value is written with a trailing semicolon the reader has to survive."""
    assert crushing.crush_resisted("MordorPikemanHorde") == 1
    assert crushing.crush_resisted("GondorFighterHorde") == 0


def test_horses_crush_foot_soldiers_and_not_each_other(crushing):
    """The whole of "cavalry trample infantry", written once in the data both sides are
    balanced from rather than in a list of unit names."""
    assert crushing.crushes("GondorKnightHorde", "GondorFighterHorde")
    assert not crushing.crushes("GondorKnightHorde", "GondorKnightHorde")
    assert not crushing.crushes("GondorKnightHorde", "MordorCatapult")


def test_infantry_crushes_nothing_at_all(crushing):
    """`CrusherLevel = 0` is strictly-not-greater than the `CrushableLevel = 0` every foot
    soldier carries, which is what stops a swordsman battalion being ordered to charge."""
    assert not crushing.crushes("GondorFighterHorde", "GondorFighterHorde")


def test_a_body_that_resists_is_not_crushed_by_the_level_it_resists(crushing):
    """`CrushableLevel = 0` says the arithmetic goes through; the resist says it does not."""
    assert crushing.crushable_level("MordorPikemanHorde") == 0
    assert not crushing.crushes("GondorKnightHorde", "MordorPikemanHorde")


@pytest.fixture
def settlement_family() -> Statics:
    """The Men settlement palette's real shape: two tiered families and a lookalike helper.

    Every name here is shipped. The tiers are what the plot swaps in as the owner's economy
    upgrades land, and `GondorRangerTentsDiscountPing` is the invisible object that carries the
    tents' cost ladder - it is owned, it is a `STRUCTURE`, and its name starts with the family's.
    """
    return Statics(
        FakeGame(
            _link(
                {
                    "GondorFarm": FakeObject({}),
                    "GondorFarm_Extern": FakeObject({}, parent_name="GondorFarm"),
                    "GondorFarm_Extern2": FakeObject({}, parent_name="GondorFarm_Extern"),
                    "GondorFarm_Extern3": FakeObject({}, parent_name="GondorFarm_Extern"),
                    "GondorRangerTents": FakeObject({}),
                    "GondorRangerTents2": FakeObject({}, parent_name="GondorRangerTents"),
                    "GondorRangerTents3": FakeObject({}, parent_name="GondorRangerTents"),
                    "GondorRangerTentsDiscountPing": FakeObject({}),
                }
            )
        )
    )


def test_a_template_descends_from_itself(settlement_family):
    """The level 1 building is a member of its own family, which is what makes the plan's own
    name a usable answer rather than a special case at every call site."""
    assert settlement_family.descends_from("GondorFarm_Extern", "GondorFarm_Extern")


def test_every_tier_belongs_to_the_family_it_is_a_child_of(settlement_family):
    """What the plot actually offers changes with the economy upgrades held, so a farm counted
    only as `GondorFarm_Extern` reads a fully upgraded map as having no farms at all."""
    assert settlement_family.descends_from("GondorFarm_Extern2", "GondorFarm_Extern")
    assert settlement_family.descends_from("GondorFarm_Extern3", "GondorFarm_Extern")
    assert settlement_family.descends_from("GondorRangerTents3", "GondorRangerTents")


def test_the_parent_is_not_a_member_of_its_childs_family(settlement_family):
    """The direction matters: `GondorFarm` is the internal farm these descend from, and counting
    it as an external one would price a base building as an expansion."""
    assert not settlement_family.descends_from("GondorFarm", "GondorFarm_Extern")


def test_a_lookalike_name_is_not_a_family_member(settlement_family):
    """The whole reason this follows the chain instead of the name. `...DiscountPing` shares the
    prefix, is owned, and would inflate the tents' count by one per player."""
    assert not settlement_family.descends_from("GondorRangerTentsDiscountPing", "GondorRangerTents")


def test_an_unknown_template_belongs_to_nothing(settlement_family):
    """A live game carries templates a differently-modded tree never heard of, and that is a
    reason to answer no rather than to raise mid-match."""
    assert not settlement_family.descends_from("RohanFarmPlayer_Extern", "GondorFarm_Extern")
