"""Unit tests for the upgrade-reference alias rules."""

from sage_ini.model.aliases import ALIASED_TABLES
from sage_ini.model.game import Game
from sage_ini.model.ini_objects import ModifierList
from sage_ini.model.xref import annotation_keys
from sage_ini.parser.blockparser import parse
from sage_ini.parser.diagnostics import Severity
from sage_lint.rules.base import default_rules, run_rules
from sage_lint.rules.references import DanglingReferenceRule
from sage_lint.rules.upgrade_alias import (
    UpgradeAliasConflictRule,
    UpgradeAliasInconsistentRule,
    UpgradeAliasInDefinitionRule,
    UpgradeAliasMalformedRule,
    _tokens,
    iter_alias_uses,
)

_ALIAS_RULES = [
    UpgradeAliasInDefinitionRule,
    UpgradeAliasMalformedRule,
    UpgradeAliasConflictRule,
    UpgradeAliasInconsistentRule,
]

_UPGRADES = """
Upgrade Upgrade_TestBuilding
  Type = OBJECT
End
Upgrade Upgrade_Other
  Type = OBJECT
End
"""


def _load(text: str) -> Game:
    game = Game()
    game.load_document(parse(_UPGRADES + text, file="t.ini").document)
    return game


def _module(triggered_by: str, tag: str = "ModuleTag_01") -> str:
    return f"  Behavior = SubObjectsUpgrade {tag}\n    TriggeredBy = {triggered_by}\n  End\n"


class TestIterAliasUses:
    def test_finds_both_annotated_and_bare_references(self):
        game = _load(
            "Object Tent\n"
            + _module("Upgrade_TestBuilding@Smithy")
            + _module("Upgrade_Other", tag="ModuleTag_02")
            + "End\n"
        )
        found = {(use.name, use.alias) for use in iter_alias_uses(game)}
        assert found == {("Upgrade_TestBuilding", "Smithy"), ("Upgrade_Other", None)}

    def test_ignores_a_colon_keyed_component(self):
        # A `Key:value` component of a colon-keyed line is never a reference name.
        assert list(_tokens("Upgrade_TestBuilding@Smithy Delay:1000")) == [
            "Upgrade_TestBuilding@Smithy"
        ]

    def test_does_not_yet_see_the_modifierlist_grant(self):
        # `ModifierList.Upgrade` is typed as `UpgradeWithDelay`, which builds its `Reference`
        # inside `convert` instead of declaring an element, so no schema walker can tell the
        # field carries upgrade references - `xref` and `sage_lint rename` miss it for the same
        # reason. Pinned rather than worked around: declaring the element is the fix, and it
        # belongs with the walkers it changes, not here.
        game = _load(
            "ModifierList TestBuff\n  Upgrade = Upgrade_TestBuilding@Smithy Delay:1000\nEnd\n"
        )
        assert not list(iter_alias_uses(game))
        assert not ALIASED_TABLES & annotation_keys(ModifierList._fieldspec["Upgrade"])

    def test_keeps_an_annotated_token_whose_base_name_is_unknown(self):
        # A typo in the base name must still be judged as an alias use; the dangling-reference
        # rule is what reports the name itself.
        game = _load("Object Tent\n" + _module("Upgrade_Typo@Smithy") + "End\n")
        assert [(use.name, use.alias) for use in iter_alias_uses(game)] == [
            ("Upgrade_Typo", "Smithy")
        ]

    def test_a_leading_separator_is_not_an_alias_use(self):
        game = _load("Object Tent\n" + _module("@Upgrade_TestBuilding") + "End\n")
        assert [use.alias for use in iter_alias_uses(game)] == []


class TestUpgradeAliasInDefinitionRule:
    def test_flags_an_alias_on_a_definition_header(self):
        game = _load("Upgrade Upgrade_TestBuilding@Smithy\n  Type = OBJECT\nEnd\n")
        diags = list(run_rules(game, [UpgradeAliasInDefinitionRule]))

        assert len(diags) == 1
        assert diags[0].code == "upgrade-alias-in-definition"
        assert diags[0].severity is Severity.ERROR
        assert diags[0].extra["base"] == "Upgrade_TestBuilding"

    def test_does_not_flag_a_plain_definition(self):
        game = _load("Object Tent\n" + _module("Upgrade_TestBuilding@Smithy") + "End\n")
        assert not list(run_rules(game, [UpgradeAliasInDefinitionRule]))


class TestUpgradeAliasMalformedRule:
    def test_flags_a_trailing_separator_with_nothing_after_it(self):
        game = _load("Object Tent\n" + _module("Upgrade_TestBuilding@") + "End\n")
        diags = list(run_rules(game, [UpgradeAliasMalformedRule]))

        assert [d.code for d in diags] == ["upgrade-alias-malformed"]
        assert diags[0].severity is Severity.ERROR
        assert "is empty" in diags[0].message

    def test_flags_a_second_separator(self):
        game = _load("Object Tent\n" + _module("Upgrade_TestBuilding@A@B") + "End\n")
        diags = list(run_rules(game, [UpgradeAliasMalformedRule]))

        assert [d.extra["alias"] for d in diags] == ["A@B"]

    def test_does_not_flag_a_well_formed_alias(self):
        game = _load("Object Tent\n" + _module("Upgrade_TestBuilding@Smithy_2") + "End\n")
        assert not list(run_rules(game, [UpgradeAliasMalformedRule]))


class TestUpgradeAliasConflictRule:
    def test_flags_two_intents_on_one_object(self):
        game = _load(
            "Object Tent\n"
            + _module("Upgrade_TestBuilding@Smithy")
            + _module("Upgrade_TestBuilding@GateOpen", tag="ModuleTag_02")
            + "End\n"
        )
        diags = list(run_rules(game, [UpgradeAliasConflictRule]))

        assert [d.code for d in diags] == ["upgrade-alias-conflict"]
        assert diags[0].severity is Severity.ERROR
        assert diags[0].extra["aliases"] == ["GateOpen", "Smithy"]

    def test_anchors_on_the_line_that_introduced_the_clash(self):
        game = _load(
            "Object Tent\n"
            + _module("Upgrade_TestBuilding@Smithy")
            + _module("Upgrade_TestBuilding@GateOpen", tag="ModuleTag_02")
            + "End\n"
        )
        diags = list(run_rules(game, [UpgradeAliasConflictRule]))
        first_use_line = min(
            use.span.line_start for use in iter_alias_uses(game) if use.alias == "Smithy"
        )
        assert diags[0].span.line_start > first_use_line

    def test_does_not_flag_one_intent_used_by_several_modules(self):
        # An upgrade legitimately drives several module effects; that is one purpose, not two.
        game = _load(
            "Object Tent\n"
            + _module("Upgrade_TestBuilding@Smithy")
            + _module("Upgrade_TestBuilding@Smithy", tag="ModuleTag_02")
            + "End\n"
        )
        assert not list(run_rules(game, [UpgradeAliasConflictRule]))

    def test_does_not_flag_the_same_upgrade_on_unrelated_objects(self):
        # Reuse across objects is the whole point of a generic upgrade: separate masks.
        game = _load(
            "Object TentA\n"
            + _module("Upgrade_TestBuilding@Smithy")
            + "End\n"
            + "Object TentB\n"
            + _module("Upgrade_TestBuilding@GateOpen")
            + "End\n"
        )
        assert not list(run_rules(game, [UpgradeAliasConflictRule]))

    def test_flags_a_clash_a_child_inherits_from_its_parent(self):
        # The bug this rule exists for: the two uses sit in different blocks, often different
        # files, and share the child's single upgrade mask.
        game = _load(
            "Object BaseTent\n"
            + _module("Upgrade_TestBuilding@Smithy")
            + "End\n"
            + "ChildObject DerivedTent BaseTent\n"
            + _module("Upgrade_TestBuilding@GateOpen", tag="ModuleTag_09")
            + "End\n"
        )
        diags = list(run_rules(game, [UpgradeAliasConflictRule]))

        assert [d.extra["object"] for d in diags] == ["DerivedTent"]

    def test_does_not_flag_a_child_that_replaces_the_parent_module_by_tag(self):
        # Re-declaring a tag overrides that module, so only the child's use runs.
        game = _load(
            "Object BaseTent\n"
            + _module("Upgrade_TestBuilding@Smithy")
            + "End\n"
            + "ChildObject DerivedTent BaseTent\n"
            + _module("Upgrade_TestBuilding@GateOpen")
            + "End\n"
        )
        assert not list(run_rules(game, [UpgradeAliasConflictRule]))


class TestUpgradeAliasInconsistentRule:
    def test_flags_a_bare_use_of_an_upgrade_annotated_elsewhere(self):
        game = _load(
            "Object TentA\n"
            + _module("Upgrade_TestBuilding@Smithy")
            + "End\n"
            + "Object TentB\n"
            + _module("Upgrade_TestBuilding")
            + "End\n"
        )
        diags = list(run_rules(game, [UpgradeAliasInconsistentRule]))

        assert [d.code for d in diags] == ["upgrade-alias-inconsistent"]
        assert diags[0].severity is Severity.WARNING
        assert diags[0].extra["known"] == ["Smithy"]

    def test_is_silent_on_data_that_uses_no_aliases(self):
        # Adoption is per upgrade, so the rule costs nothing until an upgrade is annotated once.
        game = _load(
            "Object TentA\n"
            + _module("Upgrade_TestBuilding")
            + "End\n"
            + "Object TentB\n"
            + _module("Upgrade_TestBuilding")
            + "End\n"
        )
        assert not list(run_rules(game, [UpgradeAliasInconsistentRule]))

    def test_ignores_a_malformed_alias_when_deciding_a_name_is_annotated(self):
        game = _load(
            "Object TentA\n"
            + _module("Upgrade_TestBuilding@")
            + "End\n"
            + "Object TentB\n"
            + _module("Upgrade_TestBuilding")
            + "End\n"
        )
        assert not list(run_rules(game, [UpgradeAliasInconsistentRule]))


class TestIntegration:
    def test_an_aliased_reference_is_not_reported_as_dangling(self):
        game = _load("Object Tent\n" + _module("Upgrade_TestBuilding@Smithy") + "End\n")
        assert not list(run_rules(game, [DanglingReferenceRule]))

    def test_the_rules_run_by_default(self):
        codes = {rule.code for rule in default_rules()}
        assert {rule.code for rule in _ALIAS_RULES} <= codes

    def test_unannotated_data_produces_no_alias_diagnostics(self):
        game = _load(
            "Object Tent\n"
            + _module("Upgrade_TestBuilding")
            + _module("Upgrade_Other", tag="ModuleTag_02")
            + "End\n"
        )
        assert not list(run_rules(game, _ALIAS_RULES))
