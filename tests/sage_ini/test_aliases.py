"""Unit tests for descriptive upgrade-reference aliases (`sage_ini.model.aliases`)."""

from sage_ini.model.aliases import is_well_formed, resolve_alias, split_alias, strip_alias
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse


def _load(text: str) -> Game:
    game = Game()
    game.load_document(parse(text, file="t.ini").document)
    return game


class TestSplitAlias:
    def test_splits_an_interior_separator(self):
        assert split_alias("upgrades", "Upgrade_X@Smithy") == ("Upgrade_X", "Smithy")

    def test_leaves_an_unannotated_name_alone(self):
        assert split_alias("upgrades", "Upgrade_X") == ("Upgrade_X", None)

    def test_keeps_a_leading_separator_as_part_of_the_name(self):
        # `@Name` is the create-a-hero default-bling marker, not an alias with an empty name.
        assert split_alias("upgrades", "@Upgrade_NoHelmet") == ("@Upgrade_NoHelmet", None)
        assert split_alias("upgrades", "@") == ("@", None)

    def test_keeps_an_empty_alias_so_a_rule_can_report_it(self):
        # Distinguishing "no separator" (None) from "separator, nothing after" ("") is what
        # lets the malformed-alias rule see a stray `@`.
        assert split_alias("upgrades", "Upgrade_X@") == ("Upgrade_X", "")

    def test_splits_only_at_the_first_separator(self):
        assert split_alias("upgrades", "Upgrade_X@A@B") == ("Upgrade_X", "A@B")

    def test_ignores_tables_that_do_not_take_aliases(self):
        # The engine hook sits on the upgrade lookup alone, so `@` stays part of any other name.
        assert split_alias("objects", "Obj@Thing") == ("Obj@Thing", None)

    def test_passes_a_non_string_through(self):
        assert split_alias("upgrades", None) == (None, None)

    def test_strip_alias_yields_the_looked_up_name(self):
        assert strip_alias("upgrades", "Upgrade_X@Smithy") == "Upgrade_X"
        assert strip_alias("objects", "Obj@Thing") == "Obj@Thing"


class TestResolveAlias:
    def test_reads_an_alias_written_on_a_macro_reference(self):
        game = _load("#define MY_UPGRADE Upgrade_X\n")
        assert resolve_alias(game, "upgrades", "MY_UPGRADE@Smithy") == ("Upgrade_X", "Smithy")

    def test_reads_an_alias_coming_out_of_a_macro_body(self):
        game = _load("#define MY_UPGRADE Upgrade_X@Smithy\n")
        assert resolve_alias(game, "upgrades", "MY_UPGRADE") == ("Upgrade_X", "Smithy")

    def test_an_alias_at_the_reference_wins_over_the_macro_body(self):
        # The local statement of intent is the more specific one.
        game = _load("#define MY_UPGRADE Upgrade_X@Generic\n")
        assert resolve_alias(game, "upgrades", "MY_UPGRADE@Specific") == ("Upgrade_X", "Specific")


class TestIsWellFormed:
    def test_accepts_an_identifier(self):
        assert is_well_formed("SmithyLevel2")
        assert is_well_formed("gate_open")

    def test_rejects_an_empty_or_punctuated_alias(self):
        assert not is_well_formed("")
        assert not is_well_formed("A@B")
        assert not is_well_formed("a-b")


class TestReferenceResolution:
    TEXT = """
Upgrade Upgrade_X
  Type = OBJECT
End

Object Tent
  Behavior = SubObjectsUpgrade ModuleTag_01
    TriggeredBy = Upgrade_X@Smithy
  End
End
"""

    def test_an_aliased_reference_resolves_to_the_upgrade(self):
        game = _load(self.TEXT)
        module = game.tables["objects"]["Tent"]._modules[0]
        assert [obj.name for obj in module.TriggeredBy] == ["Upgrade_X"]

    def test_the_alias_is_not_part_of_the_upgrade_identity(self):
        game = _load(self.TEXT)
        module = game.tables["objects"]["Tent"]._modules[0]
        assert module.TriggeredBy[0] is game.tables["upgrades"]["Upgrade_X"]
