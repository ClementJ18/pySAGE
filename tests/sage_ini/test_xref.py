"""Tests for the cross-reference graph (`sage_ini.model.xref`)."""

from pathlib import Path

import pytest

from sage_ini.loader import load_game
from sage_ini.model.game import Game
from sage_ini.model.xref import Xref, referenceable_keys
from sage_ini.parser.blockparser import parse

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _load(text: str) -> Game:
    game = Game()
    game.load_document(parse(text, file="t.ini").document)
    return game


class TestXref:
    # A CommandButton's `Upgrade` field is a typed cross-reference to an Upgrade.
    _BUTTON = (
        "Upgrade Upgrade_Foo\nEnd\nCommandButton Command_Bar\n    Upgrade = Upgrade_Foo\nEnd\n"
    )

    def test_records_a_forward_edge(self):
        game = _load(self._BUTTON)
        xref = Xref(game)
        button = game.commandbuttons["Command_Bar"]
        upgrade = game.upgrades["Upgrade_Foo"]
        assert upgrade in xref.references(button)

    def test_records_the_reverse_edge(self):
        game = _load(self._BUTTON)
        xref = Xref(game)
        button = game.commandbuttons["Command_Bar"]
        upgrade = game.upgrades["Upgrade_Foo"]
        assert button in xref.referenced_by(upgrade)
        assert xref.is_referenced(upgrade)

    def test_an_unreferenced_definition_has_no_reverse_edge(self):
        game = _load("Upgrade Lonely\nEnd\n")
        xref = Xref(game)
        assert not xref.is_referenced(game.upgrades["Lonely"])

    def test_a_dangling_reference_is_not_an_edge(self):
        # The target does not resolve to a registered object, so it is no edge -
        # a dangling reference is the validate/lint pass's concern, not the graph's.
        game = _load("CommandButton Command_Bar\n    Upgrade = Missing\nEnd\n")
        xref = Xref(game)
        button = game.commandbuttons["Command_Bar"]
        assert not xref.references(button)

    def test_a_reference_inside_a_module_is_the_owning_objects_edge(self):
        # An upgrade referenced from a behavior is attributed to the Object, not
        # the anonymous module that holds the field.
        game = _load(
            "Upgrade Upgrade_Foo\nEnd\n"
            "Object Hero\n    Behavior = UpgradeBehavior ModuleTag_01\n"
            "        TriggeredBy = Upgrade_Foo\n    End\nEnd\n"
        )
        xref = Xref(game)
        hero = game.objects["Hero"]
        upgrade = game.upgrades["Upgrade_Foo"]
        assert upgrade in xref.references(hero)
        assert hero in xref.referenced_by(upgrade)

    def test_self_reference_is_excluded(self):
        # A button naming itself as its toggle target is not its own reference.
        game = _load("CommandButton Command_Bar\n    ToggleButtonName = Command_Bar\nEnd\n")
        xref = Xref(game)
        button = game.commandbuttons["Command_Bar"]
        assert button not in xref.references(button)

    def test_for_game_caches_one_graph(self):
        game = _load(self._BUTTON)
        first = Xref.for_game(game)
        assert Xref.for_game(game) is first  # reused, not rebuilt


class TestReferenceableKeys:
    def test_includes_a_referenced_kind(self):
        # CommandButton.Upgrade is a typed reference to the upgrades table.
        assert "upgrades" in referenceable_keys()

    def test_excludes_an_entry_point_kind(self):
        # Nothing in the data references the game-data singleton by name.
        assert "gamedatas" not in referenceable_keys()

    def test_is_schema_derived_and_game_independent(self):
        # The answer does not depend on what a particular game happens to load.
        assert referenceable_keys() == referenceable_keys()


@pytest.mark.full
def test_corpus_reverse_reference_is_discoverable():
    if not DATA_DIR.is_dir():
        pytest.skip("base game corpus (data/) not present")
    game = load_game(DATA_DIR).game
    xref = Xref(game)

    fighter = game.objects["GondorFighter"]
    referrers = {obj.name for obj in xref.referenced_by(fighter)}
    # The fighter's horde fields it as a member - a known corpus fact.
    assert "GondorFighterHorde" in referrers
