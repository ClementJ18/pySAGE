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


class FakeObject:
    """The two members `Statics` reads off a loaded definition."""

    def __init__(self, fields: dict[str, str], parent_name: str | None = None) -> None:
        self.fields = fields
        self.parent_name = parent_name


class FakeGame:
    def __init__(self, objects: dict[str, FakeObject]) -> None:
        self.tables = {"objects": objects}


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
