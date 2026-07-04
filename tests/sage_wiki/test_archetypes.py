"""Unit tests for the object-filter archetype registry (sage_wiki.archetypes)."""

import pytest

import sage_ini.model.definitions  # noqa: F401  (register classes)
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_wiki.archetypes import (
    archetype_key,
    collect_archetypes,
    describe_filter,
    discovery_report,
    label_for,
)

# Peripheral package (sage_wiki, deferred project): full suite only.
pytestmark = pytest.mark.full

FIXTURE = """
Weapon TrollPunch
  DamageNugget
    Damage = 150
    Radius = 50
    DamageScalar = 250% ANY +HERO +MACHINE +MONSTER
    DamageScalar = 0% ANY +STRUCTURE
  End
  DamageNugget
    Damage = 240
    Radius = 30
    DamageScalar = 0% ALL -STRUCTURE ENEMIES
  End
  MetaImpactNugget
    ShockWaveRadius = 50
    HeroResist = 1.0
  End
End
Weapon FlatSword
  DamageNugget
    Damage = 40
    DamageScalar = 250% ANY +HERO +MACHINE +MONSTER
  End
End
"""


def _game() -> Game:
    game = Game()
    result = parse(FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def _scalars(game):
    """The DamageScalar entries of TrollPunch's two damage nuggets, flattened in order."""
    nuggets = [n for n in game.weapons["TrollPunch"].Nuggets if type(n).__name__ == "DamageNugget"]
    return [scaled for nugget in nuggets for scaled in nugget.DamageScalar]


def test_archetype_key_keeps_include_and_exclude_separate():
    bonus, structure_incl, structure_excl = _scalars(_game())
    assert archetype_key(bonus.ObjectFilter) == (
        frozenset({"HERO", "MACHINE", "MONSTER"}),
        frozenset(),
    )
    # An inclusion and an exclusion of the same kindof are distinct keys.
    assert archetype_key(structure_incl.ObjectFilter) == (frozenset({"STRUCTURE"}), frozenset())
    assert archetype_key(structure_excl.ObjectFilter) == (frozenset(), frozenset({"STRUCTURE"}))


def test_label_for_uses_the_registry_then_falls_back():
    bonus, structure_incl, structure_excl = _scalars(_game())
    assert label_for(bonus.ObjectFilter) == "Single"
    assert label_for(structure_incl.ObjectFilter) == "Structure"
    # The exclusion form is a different shape: the renderer reads it as a complement later,
    # so on its own it auto-labels rather than mapping to "Structure".
    assert label_for(structure_excl.ObjectFilter) == "All-STRUCTURE"


def test_label_for_unscoped_filter_is_all():
    game = Game()
    result = parse(
        "Weapon W\n  DamageNugget\n    Damage = 1\n    DamageScalar = 50%\n  End\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    scaled = game.weapons["W"].Nuggets[0].DamageScalar[0]
    assert label_for(scaled.ObjectFilter) == "All"


def test_describe_filter_reconstructs_the_token_string():
    _bonus, _incl, structure_excl = _scalars(_game())
    assert describe_filter(structure_excl.ObjectFilter) == "ALL ENEMIES -STRUCTURE"
    assert describe_filter(None) == "(none)"


def test_collect_archetypes_tallies_shapes_with_examples():
    counts, examples = collect_archetypes(_game())
    single = (frozenset({"HERO", "MACHINE", "MONSTER"}), frozenset())
    # The Single shape appears in both weapons' nuggets.
    assert counts[single] == 2
    # The two STRUCTURE forms are now separate keys, one each.
    assert counts[(frozenset({"STRUCTURE"}), frozenset())] == 1
    assert counts[(frozenset(), frozenset({"STRUCTURE"}))] == 1
    # Examples list the weapons that use a shape (de-duplicated, capped).
    assert examples[single][1] == ["TrollPunch", "FlatSword"]


def test_discovery_report_marks_unlabeled_shapes():
    # A weapon whose filter is not in ARCHETYPES surfaces as UNLABELED with an auto label.
    game = Game()
    result = parse(
        "Weapon W\n  DamageNugget\n    Damage = 1\n"
        "    DamageScalar = 0% ANY +HARVESTER\n  End\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    report = discovery_report(game)
    assert "UNLABELED" in report
    assert "HARVESTER" in report
