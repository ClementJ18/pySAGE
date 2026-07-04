"""Unit tests for sage_lint rules and the lint orchestration."""

from pathlib import Path

from sage_ini.loader import LoadedGame, load_game
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_ini.parser.diagnostics import Diagnostics, Severity
from sage_ini.suggest import suggestions_enabled
from sage_lint.linter import lint_folder, lint_game
from sage_lint.ruleconfig import rule_options
from sage_lint.rules.assets import (
    MapFolderNameRule,
    MissingMapFileRule,
    MissingModelFileRule,
    MissingTextureFileRule,
)
from sage_lint.rules.base import Rule, run_rules
from sage_lint.rules.commandset import CommandSetButtonRule
from sage_lint.rules.definitions import (
    DuplicateDefinitionRule,
    UnusedDefinitionRule,
    UnusedObjectRule,
)
from sage_lint.rules.macros import UndefinedMacroRule
from sage_lint.rules.map_ini import MapBareModuleRule
from sage_lint.rules.module_ops import ModuleOperationRule
from sage_lint.rules.module_refs import ModuleTagReferenceRule
from sage_lint.rules.modules import UnrecognizedBlockRule
from sage_lint.rules.references import DanglingAssetReferenceRule, DanglingReferenceRule
from sage_lint.rules.respawn import RespawnLevelRule, RespawnOrderRule
from sage_lint.rules.schema import (
    OutOfRangeRule,
    RepeatedScalarFieldRule,
    SpuriousBlockLabelRule,
    UnknownAttributeRule,
)
from sage_lint.rules.strings import UnknownStringLabelRule


def _load(text: str) -> Game:
    game = Game()
    game.load_document(parse(text, file="t.ini").document)
    return game


class TestRepeatedScalarFieldRule:
    def test_flags_a_scalar_field_set_twice(self):
        game = _load("Object Foo\n    BuildCost = 100\n    BuildCost = 200\nEnd\n")
        diags = list(run_rules(game, [RepeatedScalarFieldRule]))

        assert len(diags) == 1
        assert diags[0].code == "repeated-field"
        assert diags[0].severity is Severity.WARNING
        assert "BuildCost" in diags[0].message

    def test_does_not_flag_a_single_value(self):
        game = _load("Object Foo\n    BuildCost = 100\nEnd\n")
        assert not list(run_rules(game, [RepeatedScalarFieldRule]))

    def test_does_not_flag_an_unknown_repeated_field(self):
        # NotAField is not in the schema, so intent is unknown — stay quiet.
        game = _load("Object Foo\n    NotAField = 1\n    NotAField = 2\nEnd\n")
        assert not list(run_rules(game, [RepeatedScalarFieldRule]))

    def test_does_not_flag_a_repeated_filter_scoped_field(self):
        # DamageScalar repeats by design — each occurrence scopes to its own
        # object filter and all take effect, so it is not a clobbered scalar.
        game = _load(
            "Weapon W\n  Damage = 1\n  DamageNugget\n"
            "    DamageScalar = 50% NONE +INFANTRY\n"
            "    DamageScalar = 100% NONE +CAVALRY\n"
            "  End\nEnd\n"
        )
        assert not list(run_rules(game, [RepeatedScalarFieldRule]))


class TestUnknownAttributeRule:
    def test_flags_an_attribute_absent_from_the_schema(self):
        game = _load("Object Foo\n    MadeUpThing = 1\nEnd\n")
        diags = list(run_rules(game, [UnknownAttributeRule]))

        assert any(d.code == "unknown-attribute" and "MadeUpThing" in d.message for d in diags)
        assert all(d.severity is Severity.ERROR for d in diags)

    def test_does_not_flag_a_known_attribute(self):
        game = _load("Object Foo\n    BuildCost = 100\nEnd\n")
        codes = {d.code for d in run_rules(game, [UnknownAttributeRule])}
        assert "unknown-attribute" not in codes

    def test_suggests_a_near_spelling(self):
        # A close misspelling of a real field is surfaced as a hint, not auto-fixed.
        game = _load("Object Foo\n    BuildCst = 100\nEnd\n")
        with suggestions_enabled():
            diags = list(run_rules(game, [UnknownAttributeRule]))

        assert diags[0].extra["suggestion"] == "BuildCost"
        assert "Did you mean 'BuildCost'?" in diags[0].message

    def test_does_not_flag_a_standalone_marker_group_key(self):
        # `GeometryMajorRadius` is a member of Object's `geometry` marker group; used flat
        # (before any `Geometry` line) it is still a known key, not an unknown attribute.
        game = _load("Object Foo\n    GeometryMajorRadius = 12\nEnd\n")
        keys = {d.extra["key"] for d in run_rules(game, [UnknownAttributeRule])}
        assert "GeometryMajorRadius" not in keys

    def test_does_not_flag_numbered_slots_on_a_slot_block(self):
        # CommandSet declares `numbered_slots`, so its `1 = ...` button slots are valid keys,
        # not unknown attributes — but a non-digit unknown key is still flagged.
        game = _load("CommandSet Foo\n    1 = Command_A\n    2 = Command_B\n    Bogus = 1\nEnd\n")
        diags = list(run_rules(game, [UnknownAttributeRule]))
        keys = {d.extra["key"] for d in diags}
        assert "1" not in keys and "2" not in keys
        assert "Bogus" in keys


class TestUnknownStringLabelRule:
    def test_flags_a_label_absent_from_the_string_table(self):
        game = _load("Upgrade Foo\n    DisplayName = OBJECT:Missing\nEnd\n")
        game.strings.update({"OBJECT:Present": "Present"})

        diags = list(run_rules(game, [UnknownStringLabelRule]))

        assert len(diags) == 1
        assert diags[0].code == "unknown-string-label"
        assert diags[0].severity is Severity.WARNING
        assert "OBJECT:Missing" in diags[0].message

    def test_does_not_flag_a_label_present_in_the_table(self):
        game = _load("Upgrade Foo\n    DisplayName = OBJECT:Present\nEnd\n")
        game.strings.update({"OBJECT:Present": "Present"})
        assert not list(run_rules(game, [UnknownStringLabelRule]))

    def test_resolves_case_insensitively(self):
        game = _load("Upgrade Foo\n    DisplayName = controlbar:foo\nEnd\n")
        game.strings.update({"CONTROLBAR:Foo": "Foo"})
        assert not list(run_rules(game, [UnknownStringLabelRule]))

    def test_suggests_a_near_label_within_the_namespace(self):
        game = _load("Upgrade Foo\n    DisplayName = OBJECT:Presnt\nEnd\n")
        # The close match is in OBJECT:; a close match in another namespace is ignored.
        game.strings.update({"OBJECT:Present": "Present", "CONTROLBAR:Presnter": "x"})

        with suggestions_enabled():
            diags = list(run_rules(game, [UnknownStringLabelRule]))

        assert diags[0].extra["suggestion"] == "OBJECT:Present"
        assert "Did you mean 'OBJECT:Present'?" in diags[0].message

    def test_skipped_when_no_string_table_loaded(self):
        # Without a string table, every label would falsely flag — stay silent.
        game = _load("Upgrade Foo\n    DisplayName = OBJECT:Missing\nEnd\n")
        assert not list(run_rules(game, [UnknownStringLabelRule]))

    def test_ignores_non_label_fields(self):
        # BuildCost is not a Label field, so a colon value is not a string ref.
        game = _load("Upgrade Foo\n    DisplayName = OBJECT:Present\nEnd\n")
        game.strings.update({"OBJECT:Present": "Present"})
        assert not list(run_rules(game, [UnknownStringLabelRule]))

    def test_checks_each_toggle_state_label(self):
        game = _load("CommandButton Foo\n    TextLabel = CONTROLBAR:A CONTROLBAR:B\nEnd\n")
        game.strings.update({"CONTROLBAR:A": "A"})

        diags = list(run_rules(game, [UnknownStringLabelRule]))

        # B is flagged (and may suggest the present A); A itself is never the flagged label.
        flagged = {d.extra["label"] for d in diags}
        assert flagged == {"CONTROLBAR:B"}


class TestRespawnLevelRule:
    _LEVELS = (
        "ExperienceLevel HeroL1\n    TargetNames = MyHero\n    Rank = 1\nEnd\n"
        "ExperienceLevel HeroL2\n    TargetNames = MyHero\n    Rank = 2\nEnd\n"
    )

    def _hero(self, *entries: str) -> str:
        body = "".join(f"        RespawnEntry = {e}\n" for e in entries)
        return (
            self._LEVELS
            + "Object MyHero\n    Behavior = RespawnUpdate ModuleTag_01\n"
            + body
            + "    End\nEnd\n"
        )

    def test_flags_a_level_the_object_has_no_rank_for(self):
        game = _load(self._hero("Level:2 Cost:100 Time:1000", "Level:5 Cost:100 Time:1000"))
        diags = list(run_rules(game, [RespawnLevelRule]))

        assert len(diags) == 1
        assert diags[0].code == "respawn-unknown-level"
        assert diags[0].severity is Severity.WARNING
        assert "Level:5" in diags[0].message

    def test_each_flagged_entry_lands_on_its_own_line(self):
        # Two bad entries on different lines must report distinct spans, not stack on the first.
        game = _load(self._hero("Level:5 Cost:100 Time:1000", "Level:6 Cost:100 Time:1000"))
        diags = sorted(run_rules(game, [RespawnLevelRule]), key=lambda d: d.span.line_start)

        assert len(diags) == 2
        assert [d.span.line_start for d in diags] == sorted(d.span.line_start for d in diags)
        assert diags[0].span.line_start != diags[1].span.line_start
        assert "Level:5" in diags[0].message and "Level:6" in diags[1].message

    def test_does_not_flag_levels_within_the_ladder(self):
        game = _load(self._hero("Level:1 Cost:100 Time:1000", "Level:2 Cost:100 Time:1000"))
        assert not list(run_rules(game, [RespawnLevelRule]))

    def test_flags_every_entry_when_object_has_no_experience_levels(self):
        game = _load(
            "Object Lonely\n    Behavior = RespawnUpdate ModuleTag_01\n"
            "        RespawnEntry = Level:1 Cost:100 Time:1000\n    End\nEnd\n"
        )
        diags = list(run_rules(game, [RespawnLevelRule]))

        assert len(diags) == 1
        assert "registered ranks: none" in diags[0].message

    def test_ignores_objects_without_a_respawn_update(self):
        game = _load(self._LEVELS + "Object MyHero\n    BuildCost = 100\nEnd\n")
        assert not list(run_rules(game, [RespawnLevelRule]))

    def test_ignores_a_respawn_update_with_no_entries(self):
        # Entries are optional; an empty RespawnUpdate is not flagged.
        game = _load(
            self._LEVELS
            + "Object MyHero\n    Behavior = RespawnUpdate ModuleTag_01\n    End\nEnd\n"
        )
        assert not list(run_rules(game, [RespawnLevelRule]))


class TestRespawnOrderRule:
    def _hero(self, *levels: int) -> str:
        body = "".join(f"        RespawnEntry = Level:{n} Cost:1 Time:1\n" for n in levels)
        return "Object H\n    Behavior = RespawnUpdate ModuleTag_01\n" + body + "    End\nEnd\n"

    def test_flags_a_backwards_step(self):
        diags = list(run_rules(_load(self._hero(2, 5, 3)), [RespawnOrderRule]))

        assert len(diags) == 1
        assert diags[0].code == "respawn-entry-order"
        assert diags[0].severity is Severity.WARNING
        assert "Level:3" in diags[0].message and "Level:5" in diags[0].message

    def test_flags_a_duplicate_level(self):
        diags = list(run_rules(_load(self._hero(2, 2)), [RespawnOrderRule]))
        assert len(diags) == 1
        assert "Level:2" in diags[0].message

    def test_does_not_flag_an_ascending_ladder(self):
        assert not list(run_rules(_load(self._hero(1, 2, 3, 10)), [RespawnOrderRule]))


class TestOutOfRangeRule:
    def _die(self, angle: str) -> str:
        return (
            "Object Foo\n    Behavior = DieBehavior ModuleTag_01\n"
            f"        MinKillerAngle = {angle}\n    End\nEnd\n"
        )

    def test_flags_a_value_above_the_range(self):
        diags = list(run_rules(_load(self._die("400")), [OutOfRangeRule]))

        assert len(diags) == 1
        assert diags[0].code == "out-of-range"
        assert diags[0].severity is Severity.WARNING
        assert "400" in diags[0].message and "-360..360" in diags[0].message

    def test_flags_a_value_below_the_range(self):
        diags = list(run_rules(_load(self._die("-400")), [OutOfRangeRule]))
        assert len(diags) == 1
        assert "-400" in diags[0].message

    def test_does_not_flag_a_value_in_range(self):
        assert not list(run_rules(_load(self._die("90")), [OutOfRangeRule]))

    def test_does_not_flag_a_non_numeric_value(self):
        # A value that does not convert is the conversion pass's diagnostic.
        assert not list(run_rules(_load(self._die("NotANumber")), [OutOfRangeRule]))


class TestDuplicateDefinitionRule:
    def test_flags_a_same_file_redefinition(self):
        game = _load("Object Foo\n    BuildCost = 1\nEnd\nObject Foo\n    BuildCost = 2\nEnd\n")
        diags = list(run_rules(game, [DuplicateDefinitionRule]))

        assert len(diags) == 1
        assert diags[0].code == "duplicate-definition"
        assert diags[0].severity is Severity.WARNING
        assert "Foo" in diags[0].message
        # The discarded first definition is the duplicate, so the warning lands there.
        assert diags[0].span.line_start == 1

    def test_does_not_flag_a_single_definition(self):
        game = _load("Object Foo\nEnd\n")
        assert not list(run_rules(game, [DuplicateDefinitionRule]))

    def test_does_not_flag_a_collection_type_repeat(self):
        # AIBase lists several entries under one name (unique_name = False).
        game = _load("AIBase MOWBase\n    Side = Men\nEnd\nAIBase MOWBase\n    Side = Wild\nEnd\n")
        assert not list(run_rules(game, [DuplicateDefinitionRule]))

    def test_does_not_flag_a_cross_file_redefinition(self):
        # A later file overriding an earlier one is the engine's override path.
        game = Game()
        game.load_document(parse("Object Foo\nEnd\n", file="a.ini").document)
        game.load_document(parse("Object Foo\nEnd\n", file="b.ini").document)
        assert not list(run_rules(game, [DuplicateDefinitionRule]))


class TestUnusedDefinitionRule:
    def test_flags_a_definition_nothing_references(self):
        game = _load("Upgrade Lonely\nEnd\n")
        diags = list(run_rules(game, [UnusedDefinitionRule]))

        assert len(diags) == 1
        assert diags[0].code == "unused-definition"
        assert diags[0].severity is Severity.WARNING
        assert diags[0].extra["name"] == "Lonely"
        assert diags[0].extra["table"] == "upgrades"

    def test_does_not_flag_a_referenced_definition(self):
        # The upgrade is named by a command button, so it is reached and not flagged.
        game = _load("Upgrade Used\nEnd\nCommandButton B\n    Upgrade = Used\nEnd\n")
        names = {d.extra["name"] for d in run_rules(game, [UnusedDefinitionRule])}
        assert "Used" not in names

    def test_does_not_flag_an_object(self):
        # Objects are split off to the unused-object rule, which is off by default.
        game = _load("Object Orphan\nEnd\n")
        assert not list(run_rules(game, [UnusedDefinitionRule]))

    def test_does_not_flag_an_entry_point_kind(self):
        # GameData is loaded by the engine directly and named by nothing in the data, so its
        # kind is not referenceable and is never reported as unused.
        game = _load("GameData\n    FramesPerSecondLimit = 30\nEnd\n")
        assert not list(run_rules(game, [UnusedDefinitionRule]))

    def test_does_not_flag_an_asset_definition(self):
        # FXList lives in an excluded asset table — its references resolve in ways the graph
        # cannot see, so a missing reverse edge is not treated as "unused" here.
        game = _load("FXList FX_Boom\nEnd\n")
        assert not list(run_rules(game, [UnusedDefinitionRule]))

    def test_does_not_flag_a_faction(self):
        # PlayerTemplate is an engine entry point the game loads directly; most factions are
        # named by nothing in the data, so they are excluded rather than reported.
        game = _load("PlayerTemplate FactionMen\n    Side = Men\nEnd\n")
        assert not list(run_rules(game, [UnusedDefinitionRule]))

    def test_runs_on_a_plain_default_run(self):
        game = _load("Upgrade Lonely\nEnd\n")
        assert any(d.code == "unused-definition" for d in run_rules(game))

    def test_does_not_flag_a_command_button_a_command_set_lists(self):
        # A command set names its buttons in digit-keyed slots (`1 = Command_X`), which are
        # dynamic and carry no typed field; the xref graph reads them so the button is reached.
        game = _load(
            "CommandButton Command_Build\n    Command = UNIT_BUILD\nEnd\n"
            "CommandSet RallyPointCommandSet\n    1 = Command_Build\nEnd\n"
        )
        names = {d.extra["name"] for d in run_rules(game, [UnusedDefinitionRule])}
        assert "Command_Build" not in names

    def test_does_not_flag_a_create_a_hero_button(self):
        # A `CreateAHeroUI*` field marks a button the engine injects into a custom hero's
        # command set at runtime, so no command set in the data names it.
        game = _load(
            "CommandButton Command_CreateAHero_Blade\n"
            "    Command = PURCHASE_SCIENCE\n"
            "    CreateAHeroUIMinimumLevel = 3\nEnd\n"
        )
        assert not list(run_rules(game, [UnusedDefinitionRule]))

    def test_always_referenced_config_suppresses_a_kind(self):
        game = _load("PlayerAIType Multiplayer_Human\nEnd\n")
        # By default a PlayerAIType the data never names is flagged; the config exempts the kind.
        default = run_rules(game, [UnusedDefinitionRule])
        assert any(d.extra["name"] == "Multiplayer_Human" for d in default)
        with rule_options(always_referenced=["PlayerAIType"]):
            assert not list(run_rules(game, [UnusedDefinitionRule]))


class TestUnusedObjectRule:
    def test_is_off_by_default(self):
        game = _load("Object Orphan\nEnd\n")
        assert all(d.code != "unused-object" for d in run_rules(game))

    def test_flags_an_unreferenced_object_when_selected(self):
        game = _load("Object Orphan\nEnd\n")
        diags = list(run_rules(game, [UnusedObjectRule]))

        assert len(diags) == 1
        assert diags[0].code == "unused-object"
        assert diags[0].severity is Severity.WARNING
        assert diags[0].extra["name"] == "Orphan"

    def test_does_not_flag_a_referenced_object(self):
        # The member object is named by the horde's payload, so it is reached.
        game = _load(
            "Object Member\nEnd\n"
            "Object Horde\n    Behavior = HordeContain Tag\n"
            "        InitialPayload = Member 5\n    End\nEnd\n"
        )
        names = {d.extra["name"] for d in run_rules(game, [UnusedObjectRule])}
        assert "Member" not in names


class TestUndefinedMacroRule:
    def test_flags_an_undefined_macro_in_a_field_expression(self):
        game = _load("Object Foo\n    BuildCost = #MULTIPLY( UNDEF_MACRO 2 )\nEnd\n")
        diags = list(run_rules(game, [UndefinedMacroRule]))

        assert len(diags) == 1
        assert diags[0].code == "undefined-macro"
        assert diags[0].severity is Severity.WARNING
        assert "UNDEF_MACRO" in diags[0].message

    def test_does_not_flag_a_defined_macro(self):
        game = _load(
            "#define DEFINED_MACRO 10\n"
            "Object Foo\n    BuildCost = #MULTIPLY( DEFINED_MACRO 2 )\nEnd\n"
        )
        assert not list(run_rules(game, [UndefinedMacroRule]))

    def test_suggests_a_near_macro(self):
        game = _load(
            "#define DAMAGE_BONUS 10\nObject Foo\n    BuildCost = #MULTIPLY( DAMAGE_BONS 2 )\nEnd\n"
        )
        with suggestions_enabled():
            diags = list(run_rules(game, [UndefinedMacroRule]))

        assert diags[0].extra["suggestion"] == "DAMAGE_BONUS"
        assert "Did you mean 'DAMAGE_BONUS'?" in diags[0].message

    def test_does_not_flag_a_numeric_operand(self):
        game = _load("Object Foo\n    BuildCost = #MULTIPLY( 10 2 )\nEnd\n")
        assert not list(run_rules(game, [UndefinedMacroRule]))

    def test_does_not_flag_a_bare_non_arithmetic_value(self):
        # Outside arithmetic a token may be an enum, a name, or text — not a macro.
        game = _load("Object Foo\n    KindOf = STRUCTURE SELECTABLE\nEnd\n")
        assert not list(run_rules(game, [UndefinedMacroRule]))

    def test_flags_an_undefined_macro_in_a_define_body(self):
        # A macro built on another undefined macro is caught even when unused.
        game = _load("#define A #ADD( UNDEFINED_B 1 )\n")
        diags = list(run_rules(game, [UndefinedMacroRule]))

        assert len(diags) == 1
        assert "UNDEFINED_B" in diags[0].message and "A" in diags[0].message


class TestDanglingReferenceRule:
    # A DetachableRiderUpdate whose DeathEntry names `ocl` as its RiderOCL; `defined`
    # is an OCL declared so the objectcreationlists table is populated (else the kind
    # counts as unmodelled and the reference is left alone).
    def _rider(self, ocl: str, defined: str = "OCL_Real") -> str:
        return (
            f"ObjectCreationList {defined}\nEnd\n"
            "Object Rider\n    Behavior = DetachableRiderUpdate ModuleTag_01\n"
            f"        DeathEntry = AnimState:DEATH_2 AnimTime:3000 RiderOCL:{ocl}\n"
            "    End\nEnd\n"
        )

    def test_flags_a_dangling_reference_inside_a_keyed_record(self):
        diags = list(run_rules(_load(self._rider("OCL_Missing")), [DanglingReferenceRule]))

        assert len(diags) == 1
        assert diags[0].code == "dangling-reference"
        assert diags[0].severity is Severity.WARNING
        assert "OCL_Missing" in diags[0].message
        assert diags[0].extra["table"] == "objectcreationlists"

    def test_does_not_flag_a_resolved_reference(self):
        assert not list(run_rules(_load(self._rider("OCL_Real")), [DanglingReferenceRule]))

    def test_resolves_case_insensitively(self):
        assert not list(run_rules(_load(self._rider("ocl_real")), [DanglingReferenceRule]))

    def test_skips_the_none_sentinel(self):
        assert not list(run_rules(_load(self._rider("None")), [DanglingReferenceRule]))

    def test_skips_a_configured_sentinel(self):
        # A project-configured sentinel (e.g. NoSound) is treated like None: an intentional
        # "nothing", never reported as dangling.
        game = _load(self._rider("OCL_Nothing"))
        assert list(run_rules(game, [DanglingReferenceRule]))  # flagged by default
        with rule_options(sentinels=["OCL_Nothing"]):
            assert not list(run_rules(game, [DanglingReferenceRule]))

    def test_skipped_when_the_kind_is_unmodelled(self):
        # No OCL is declared, so the objectcreationlists table is empty and every name
        # would falsely dangle — stay silent, mirroring the empty-string-table guard.
        game = _load(
            "Object Rider\n    Behavior = DetachableRiderUpdate ModuleTag_01\n"
            "        DeathEntry = RiderOCL:OCL_Missing\n    End\nEnd\n"
        )
        assert not list(run_rules(game, [DanglingReferenceRule]))

    def test_does_not_flag_asset_references(self):
        # A dangling FXList reference is an asset kind, deliberately not checked.
        game = _load("FXList FX_Real\nEnd\nWeapon W\n    FireFX = FX_Missing\nEnd\n")
        assert not list(run_rules(game, [DanglingReferenceRule]))

    def test_suggests_a_near_definition(self):
        with suggestions_enabled():
            diags = list(run_rules(_load(self._rider("OCL_Rel")), [DanglingReferenceRule]))

        assert diags[0].extra["suggestion"] == "OCL_Real"
        assert "Did you mean 'OCL_Real'?" in diags[0].message


class TestDanglingAssetReferenceRule:
    def test_flags_a_missing_fxlist_when_some_are_loaded(self):
        game = _load("FXList FX_Real\nEnd\nWeapon W\n    FireFX = FX_Missing\nEnd\n")
        diags = list(run_rules(game, [DanglingAssetReferenceRule]))

        assert [d.code for d in diags] == ["dangling-asset-reference"]
        assert diags[0].severity is Severity.INFO  # a hint, not a fatal bug
        assert "FX_Missing" in diags[0].message
        assert diags[0].extra["table"] == "fxlists"

    def test_does_not_flag_a_resolved_fxlist(self):
        game = _load("FXList FX_Real\nEnd\nWeapon W\n    FireFX = FX_Real\nEnd\n")
        assert not list(run_rules(game, [DanglingAssetReferenceRule]))

    def test_skips_when_no_asset_of_that_kind_is_loaded(self):
        # No FXList declared anywhere: the FX files were not part of this build, so a miss is
        # meaningless and must not flood the report.
        game = _load("Weapon W\n    FireFX = FX_Missing\nEnd\n")
        assert not list(run_rules(game, [DanglingAssetReferenceRule]))

    def test_resolves_a_sound_across_the_audio_table_union(self):
        # A sound name backed by a DialogEvent resolves the way the engine looks it up — across
        # every audio table — even though the field type keys to audioevents.
        game = _load(
            "DialogEvent Snd_Real\nEnd\n"
            "CommandButton B\n    SetAutoAbilityUnitSound = Snd_Real\nEnd\n"
        )
        assert not list(run_rules(game, [DanglingAssetReferenceRule]))

    def test_flags_a_missing_sound(self):
        game = _load(
            "AudioEvent Snd_Real\nEnd\n"
            "CommandButton B\n    SetAutoAbilityUnitSound = Snd_Missing\nEnd\n"
        )
        diags = list(run_rules(game, [DanglingAssetReferenceRule]))
        assert [d.code for d in diags] == ["dangling-asset-reference"]
        assert "audio" in diags[0].message


_ASSET_RULES = [MissingTextureFileRule, MissingModelFileRule, MissingMapFileRule]


class TestMissingAssetFileRule:
    # A tree object whose draw module names a model and a texture file.
    def _tree(self, model: str, texture: str) -> str:
        return (
            "Object Tree\n    Draw = W3DTreeDraw ModuleTag_01\n"
            f"        ModelName = {model}\n        TextureName = {texture}\n"
            "    End\nEnd\n"
        )

    def _game(self, model: str, texture: str, assets: set[str]) -> Game:
        game = _load(self._tree(model, texture))
        game.assets = assets
        return game

    def test_flags_a_model_and_texture_with_no_file(self):
        game = self._game("AMissingTree", "AMissingTree", {"someothertree.w3d"})
        diags = list(run_rules(game, _ASSET_RULES))

        # one code per kind — texture and model misses are reported apart
        assert {d.code for d in diags} == {"missing-texture-file", "missing-model-file"}
        assert all(d.severity is Severity.WARNING for d in diags)
        kinds = {d.extra["kind"] for d in diags}
        assert kinds == {"model", "texture"}

    def test_each_kind_has_its_own_code(self):
        # The split lets a texture, model and map miss be selected/ignored/counted separately.
        assert MissingTextureFileRule.code == "missing-texture-file"
        assert MissingModelFileRule.code == "missing-model-file"
        assert MissingMapFileRule.code == "missing-map-file"
        # Each rule only reports its own kind: the model rule alone leaves the texture miss.
        game = self._game("AMissingTree", "AMissingTree", {"someothertree.w3d"})
        model_only = list(run_rules(game, [MissingModelFileRule]))
        assert [d.extra["kind"] for d in model_only] == ["model"]

    def test_opt_in_so_skipped_by_a_default_run(self):
        # The asset rules are off by default (they flood without the base archives loaded), so a
        # plain run — `run_rules` with no explicit rule list — emits none of their codes; they
        # still fire when asked for explicitly.
        assert all(not rule.default for rule in _ASSET_RULES)
        game = self._game("AMissingTree", "AMissingTree", {"someothertree.w3d"})
        asset_codes = {"missing-texture-file", "missing-model-file", "missing-map-file"}
        assert not ({d.code for d in run_rules(game)} & asset_codes)  # default run: none
        assert {d.code for d in run_rules(game, _ASSET_RULES)} & asset_codes  # explicit: fired

    def test_resolves_a_model_by_appending_the_extension(self):
        # `ModelName = ATree` resolves to `atree.w3d` the way the engine searches by basename.
        game = self._game("ATree", "ATree.tga", {"atree.w3d", "atree.tga"})
        assert not list(run_rules(game, _ASSET_RULES))

    def test_resolves_case_insensitively(self):
        game = self._game("ATree", "ATree.TGA", {"atree.w3d", "atree.tga"})
        assert not list(run_rules(game, _ASSET_RULES))

    def test_resolves_a_texture_given_an_explicit_extension(self):
        # A value already carrying a known extension is matched as-is, not re-suffixed.
        game = self._game("ATree", "bark.dds", {"atree.w3d", "bark.dds"})
        assert not list(run_rules(game, _ASSET_RULES))

    def test_resolves_a_tga_reference_to_a_dds_file(self):
        # The engine treats .tga/.dds as interchangeable, so a .tga reference resolves to a
        # .dds of the same name (and vice versa).
        game = self._game("ATree", "bark.tga", {"atree.w3d", "bark.dds"})
        assert not list(run_rules(game, _ASSET_RULES))

    def test_strips_a_directory_prefix(self):
        game = self._game("ATree", r"trees\bark.tga", {"atree.w3d", "bark.tga"})
        assert not list(run_rules(game, _ASSET_RULES))

    def test_skips_the_none_sentinel(self):
        game = self._game("NONE", "NONE", {"atree.w3d"})
        assert not list(run_rules(game, _ASSET_RULES))

    def test_skipped_when_no_assets_crawled(self):
        # An empty index means a single file was linted in isolation (or no art shipped);
        # flagging every reference would flood the report, so stay silent.
        game = self._game("AMissingTree", "AMissingTree", set())
        assert not list(run_rules(game, _ASSET_RULES))

    def test_crawl_indexes_loose_art_files(self, tmp_path):
        art = tmp_path / "art" / "w3d"
        art.mkdir(parents=True)
        (art / "ATree.w3d").write_bytes(b"")
        (tmp_path / "trees.ini").write_text(self._tree("ATree", "ATree"), encoding="utf-8")

        loaded = load_game(tmp_path)
        assert "atree.w3d" in loaded.game.assets
        # The model resolves to the crawled file; only the missing texture is flagged.
        diags = list(run_rules(loaded.game, _ASSET_RULES))
        assert [d.extra["kind"] for d in diags] == ["texture"]

    # An AIBase whose Map names a base layout and GameMapToUseOn names a map.
    def _aibase(self, base: str, used_map: str) -> str:
        return f'AIBase B\n    Map = "{base}"\n    GameMapToUseOn = "{used_map}"\nEnd\n'

    def _map_game(self, base: str, used_map: str, files: list[str]) -> Game:
        game = _load(self._aibase(base, used_map))
        game.map_files = [Path(p) for p in files]
        return game

    def test_resolves_a_base_layout_to_a_bse_file(self):
        game = self._map_game(
            "my_base", "my_map", ["bases/my_base/my_base.bse", "maps/my_map/my_map.map"]
        )
        assert not list(run_rules(game, _ASSET_RULES))

    def test_flags_a_missing_base_layout(self):
        game = self._map_game("missing_base", "my_map", ["maps/my_map/my_map.map"])
        diags = list(run_rules(game, _ASSET_RULES))
        assert [d.extra["kind"] for d in diags] == ["map"]
        assert "missing_base" in diags[0].message

    def test_skips_the_any_sentinel(self):
        # GameMapToUseOn = "<ANY>" is an engine sentinel, not a file reference.
        game = self._map_game("my_base", "<ANY>", ["bases/my_base/my_base.bse"])
        assert not list(run_rules(game, _ASSET_RULES))

    def test_map_check_skipped_when_no_layouts_crawled(self):
        # No .map/.bse crawled (they ship in archives, or single-file lint): stay silent even
        # though art was indexed, so a map reference is not falsely flagged.
        game = self._map_game("my_base", "my_map", [])
        game.assets = {"sometexture.tga"}
        assert not list(run_rules(game, _ASSET_RULES))


class TestMapFolderNameRule:
    def _game(self, *files: str) -> Game:
        game = Game()
        game.map_files = [Path(p) for p in files]
        return game

    def test_flags_a_file_not_matching_its_folder(self):
        diags = list(run_rules(self._game("maps/my_map/other.map"), [MapFolderNameRule]))
        assert [d.code for d in diags] == ["map-folder-name"]
        assert diags[0].severity is Severity.WARNING
        assert diags[0].extra == {"file": "other.map", "folder": "my_map"}

    def test_does_not_flag_a_matching_map(self):
        assert not list(run_rules(self._game("maps/my_map/my_map.map"), [MapFolderNameRule]))

    def test_does_not_flag_a_matching_base(self):
        assert not list(run_rules(self._game("bases/my_base/my_base.bse"), [MapFolderNameRule]))

    def test_matches_folder_name_case_insensitively(self):
        assert not list(run_rules(self._game("maps/My_Map/my_map.map"), [MapFolderNameRule]))

    def test_crawl_indexes_maps_bases_and_libraries(self, tmp_path):
        for folder, name, ext in [
            ("maps", "amon_hen", ".map"),
            ("bases", "ai base - gondor", ".bse"),
            ("libraries", "ki gondor", ".map"),
        ]:
            sub = tmp_path / folder / name
            sub.mkdir(parents=True)
            (sub / f"{name}{ext}").write_bytes(b"")
        loaded = load_game(tmp_path)
        names = {p.name.lower() for p in loaded.game.map_files}
        assert names == {"amon_hen.map", "ai base - gondor.bse", "ki gondor.map"}
        assert not list(run_rules(loaded.game, [MapFolderNameRule]))


class TestCommandSetButtonRule:
    _SET = (
        "CommandButton Command_Real\nEnd\n"
        "CommandSet Set\n    1 = Command_Real\n    2 = {slot}\nEnd\n"
    )

    def _run(self, slot: str) -> list:
        return list(run_rules(_load(self._SET.format(slot=slot)), [CommandSetButtonRule]))

    def test_flags_a_slot_with_no_button(self):
        diags = self._run("Command_Missing")

        assert len(diags) == 1
        assert diags[0].code == "dangling-commandbutton"
        assert diags[0].severity is Severity.WARNING
        assert "Command_Missing" in diags[0].message
        assert diags[0].extra["key"] == "2"  # the slot number

    def test_does_not_flag_a_resolved_slot(self):
        assert not self._run("Command_Real")

    def test_resolves_case_insensitively(self):
        assert not self._run("command_real")

    def test_ignores_the_none_slot_sentinel(self):
        # `NONE` is the engine's "no button in this slot", not a dangling reference.
        assert not self._run("NONE")

    def test_suggests_a_near_button(self):
        with suggestions_enabled():
            diags = self._run("Command_Rel")

        assert diags[0].extra["suggestion"] == "Command_Real"
        assert "Did you mean 'Command_Real'?" in diags[0].message


class TestModuleTagReferenceRule:
    _OBJ = (
        "Object Hero\n"
        "    Behavior = ActivateModuleSpecialPower ModuleTag_Activate\n"
        "        TriggerSpecialPower = {tag} TARGETPOS\n"
        "    End\n"
        "    Behavior = AutoHealBehavior ModuleTag_Power\n"
        "    End\n"
        "End\n"
    )

    def test_flags_a_trigger_naming_a_missing_module_tag(self):
        game = _load(self._OBJ.format(tag="ModuleTag_Ghost"))
        diags = list(run_rules(game, [ModuleTagReferenceRule]))

        assert len(diags) == 1
        assert diags[0].code == "module-tag-reference"
        assert diags[0].severity is Severity.WARNING
        assert diags[0].extra == {"type": "Object", "object": "Hero", "tag": "ModuleTag_Ghost"}

    def test_does_not_flag_a_trigger_naming_a_present_module(self):
        game = _load(self._OBJ.format(tag="ModuleTag_Power"))
        assert not list(run_rules(game, [ModuleTagReferenceRule]))

    def test_resolves_a_trigger_without_a_position_token(self):
        game = _load(
            "Object Hero\n"
            "    Behavior = ActivateModuleSpecialPower ModuleTag_Activate\n"
            "        TriggerSpecialPower = ModuleTag_Power\n"
            "    End\n"
            "    Behavior = AutoHealBehavior ModuleTag_Power\n    End\n"
            "End\n"
        )
        assert not list(run_rules(game, [ModuleTagReferenceRule]))

    def test_does_not_flag_an_object_without_a_trigger_module(self):
        game = _load("Object Hero\n    Behavior = AutoHealBehavior ModuleTag_Power\n    End\nEnd\n")
        assert not list(run_rules(game, [ModuleTagReferenceRule]))


class TestMacroCase:
    def test_case_mismatch_surfaces_as_a_warning_not_an_error(self):
        # corpus: a `#define`d macro referenced in another casing — resolve it (the engine
        # matches loosely) but warn, instead of failing the value as a dangling literal.
        game = _load("#define MY_DAMAGE 150\nWeapon W\n    PrimaryDamage = my_damage\nEnd\n")
        diags = game.validate()
        codes = {d.code for d in diags}

        assert "macro-case" in codes
        assert "conversion-error" not in codes
        warning = next(d for d in diags if d.code == "macro-case")
        assert warning.severity is Severity.WARNING
        assert "'MY_DAMAGE'" in warning.message


class TestUnrecognizedBlockRule:
    def test_flags_a_misspelled_behavior_class(self):
        game = _load(
            "Object Foo\n"
            "    Behavior = PhysicsBeavior ModuleTag_04\n"
            "        GravityMult = 1.0\n"
            "    End\nEnd\n"
        )
        with suggestions_enabled():
            diags = list(run_rules(game, [UnrecognizedBlockRule]))

        assert len(diags) == 1
        assert diags[0].code == "unrecognized-block"
        assert diags[0].severity is Severity.ERROR
        assert "PhysicsBeavior" in diags[0].message
        assert diags[0].extra["suggestion"] == "PhysicsBehavior"
        assert "Did you mean 'PhysicsBehavior'?" in diags[0].message

    def test_does_not_flag_a_known_module(self):
        game = _load(
            "Object Foo\n    Behavior = PhysicsBehavior ModuleTag_04\n"
            "        GravityMult = 1.0\n    End\nEnd\n"
        )
        assert not list(run_rules(game, [UnrecognizedBlockRule]))

    def test_flags_an_unmodelled_block_without_a_suggestion(self):
        # Even with suggestions on, a token too far from any class yields no hint.
        game = _load("Object Foo\n    Behavior = TotallyMadeUpXyz Tag\n    End\nEnd\n")
        with suggestions_enabled():
            diags = list(run_rules(game, [UnrecognizedBlockRule]))

        assert len(diags) == 1
        assert diags[0].extra["suggestion"] is None


class TestModuleOperationRule:
    # A base object with two tagged modules, inherited by the child under test.
    _BASE = (
        "Object Base\n"
        "    Behavior = AutoHealBehavior ModuleTag_Heal\n    End\n"
        "    Draw = W3DScriptedModelDraw ModuleTag_Draw\n    End\n"
        "End\n"
    )

    def _child(self, body: str) -> Game:
        return _load(self._BASE + f"ChildObject Kid Base\n{body}End\n")

    def test_valid_edits_are_silent(self):
        game = self._child(
            "    AddModule\n        Behavior = ArmorUpgrade ModuleTag_New\n        End\n    End\n"
            "    RemoveModule ModuleTag_Draw\n"
            "    ReplaceModule ModuleTag_Heal\n"
            "        Behavior = AutoHealBehavior ModuleTag_Heal2\n        End\n    End\n"
        )
        assert not list(run_rules(game, [ModuleOperationRule]))

    def test_add_conflicting_tag(self):
        # ModuleTag_Heal already exists on the parent.
        game = self._child(
            "    AddModule\n        Behavior = ArmorUpgrade ModuleTag_Heal\n        End\n    End\n"
        )
        diags = list(run_rules(game, [ModuleOperationRule]))
        assert len(diags) == 1
        assert diags[0].code == "invalid-module-operation"
        assert diags[0].severity is Severity.ERROR
        assert "AddModule" in diags[0].message and "ModuleTag_Heal" in diags[0].message

    def test_remove_missing_module(self):
        game = self._child("    RemoveModule ModuleTag_Nope\n")
        diags = list(run_rules(game, [ModuleOperationRule]))
        assert len(diags) == 1
        assert "RemoveModule" in diags[0].message and "does not exist" in diags[0].message

    def test_replace_missing_module(self):
        game = self._child(
            "    ReplaceModule ModuleTag_Nope\n"
            "        Behavior = ArmorUpgrade ModuleTag_X\n        End\n    End\n"
        )
        diags = list(run_rules(game, [ModuleOperationRule]))
        assert len(diags) == 1
        assert "does not exist" in diags[0].message

    def test_replace_type_mismatch(self):
        game = self._child(
            "    ReplaceModule ModuleTag_Heal\n"
            "        Behavior = ArmorUpgrade ModuleTag_HealNew\n        End\n    End\n"
        )
        diags = list(run_rules(game, [ModuleOperationRule]))
        assert len(diags) == 1
        assert "AutoHealBehavior" in diags[0].message and "ArmorUpgrade" in diags[0].message

    def test_replace_with_same_tag(self):
        game = self._child(
            "    ReplaceModule ModuleTag_Heal\n"
            "        Behavior = AutoHealBehavior ModuleTag_Heal\n        End\n    End\n"
        )
        diags = list(run_rules(game, [ModuleOperationRule]))
        assert len(diags) == 1
        assert "different ModuleTag" in diags[0].message

    def test_default_template_inheritable_modules_count_as_present(self):
        # A module the default template wraps in InheritableModule is copied into every
        # object, so removing/replacing it is valid even with no explicit parent.
        game = _load(
            "Object DefaultThingTemplate\n"
            "    InheritableModule\n"
            "        Behavior = LifetimeUpdate ModuleTag_Life\n        End\n    End\n"
            "End\n"
            "Object Foo\n    RemoveModule ModuleTag_Life\nEnd\n"
        )
        assert not list(run_rules(game, [ModuleOperationRule]))

    def test_unresolved_parent_is_skipped(self):
        # The parent is not assembled, so the inherited modules are unknown; stay silent
        # rather than false-flag (mirrors the cross-file reference handling).
        game = _load("ChildObject Orphan MissingParent\n    RemoveModule ModuleTag_Whatever\nEnd\n")
        assert not list(run_rules(game, [ModuleOperationRule]))


class TestSpuriousBlockLabelRule:
    def test_flags_the_equals_form(self):
        game = _load(
            "Object Foo\n"
            "    ThreatBreakdown = ThreatBreakdown_Tag\n        AIKindOf = INFANTRY\n    End\n"
            "End\n"
        )
        diags = list(run_rules(game, [SpuriousBlockLabelRule]))

        assert len(diags) == 1
        assert diags[0].code == "spurious-block-label"
        assert diags[0].severity is Severity.WARNING
        assert "ThreatBreakdown" in diags[0].message

    def test_does_not_flag_the_bare_tag_form(self):
        # `ThreatBreakdown Tag` (no `=`) is the correct header — only the `=` form is wrong.
        game = _load(
            "Object Foo\n"
            "    ThreatBreakdown ThreatBreakdown_Tag\n        AIKindOf = INFANTRY\n    End\n"
            "End\n"
        )
        assert not list(run_rules(game, [SpuriousBlockLabelRule]))

    def test_does_not_flag_the_headerless_form(self):
        game = _load("Object Foo\n    ThreatBreakdown\n        AIKindOf = INFANTRY\n    End\nEnd\n")
        assert not list(run_rules(game, [SpuriousBlockLabelRule]))


class TestMapBareModuleRule:
    @staticmethod
    def _load_map(text: str) -> Game:
        # Parse under a map-scoped filename so the rule treats it as a map.ini.
        game = Game()
        game.load_document(parse(text, file="maps/MyMap/map.ini").document)
        return game

    def test_flags_bare_modules_in_a_map(self):
        game = self._load_map(
            "ChildObject Tweak Base\n"
            "    Behavior = AutoHealBehavior ModuleTag_Bare\n    End\n"
            "    Draw = W3DScriptedModelDraw ModuleTag_BareDraw\n    End\n"
            "End\n"
        )
        diags = list(run_rules(game, [MapBareModuleRule]))

        assert {d.extra["tag"] for d in diags} == {"ModuleTag_Bare", "ModuleTag_BareDraw"}
        assert all(d.code == "map-bare-module" and d.severity is Severity.ERROR for d in diags)

    def test_allows_keyword_module_edits_in_a_map(self):
        game = self._load_map(
            "ChildObject Tweak Base\n"
            "    AddModule\n        Behavior = ArmorUpgrade ModuleTag_Add\n        End\n    End\n"
            "    ReplaceModule ModuleTag_Old\n"
            "        Behavior = AutoHealBehavior ModuleTag_New\n        End\n    End\n"
            "    RemoveModule ModuleTag_Gone\n"
            "End\n"
        )
        assert not list(run_rules(game, [MapBareModuleRule]))

    def test_ignores_bare_modules_outside_a_map(self):
        game = _load("Object Foo\n    Behavior = AutoHealBehavior ModuleTag_X\n    End\nEnd\n")
        assert not list(run_rules(game, [MapBareModuleRule]))


class TestDanglingReferenceSuggestion:
    def test_conversion_error_suggests_a_near_definition(self):
        # A weapon reference that misspells a defined weapon dangles, and the closest
        # defined name is offered as a hint rather than the reference being dropped.
        game = _load(
            "Weapon Sword\n    PrimaryDamage = 5\nEnd\n"
            "Object Hero\n    WeaponSet\n        Weapon = PRIMARY Swrd\n    End\nEnd\n"
        )
        with suggestions_enabled():
            dangling = [d for d in game.validate() if d.code == "conversion-error"]

        assert dangling
        assert any("Did you mean 'Sword'?" in d.message for d in dangling)


class TestRunnerIsolation:
    def test_a_faulty_rule_is_isolated(self):
        class BoomRule(Rule):
            code = ""  # not auto-registered

            def check(self, game):
                raise RuntimeError("boom")
                yield  # pragma: no cover

        diags = list(run_rules(_load("Object Foo\nEnd\n"), [BoomRule]))

        assert len(diags) == 1
        assert diags[0].code == "rule-error"
        assert "boom" in diags[0].message


class TestLintGame:
    def test_merges_load_validate_and_rule_diagnostics(self):
        game = _load("Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n")
        loaded = LoadedGame(game=game, diagnostics=Diagnostics())

        codes = {d.code for d in lint_game(loaded, rules=[RepeatedScalarFieldRule])}
        assert "repeated-field" in codes


class TestLintFolder:
    def test_clean_folder_has_no_warnings(self, tmp_path):
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCost = 100\nEnd\n", encoding="utf-8")
        diags = lint_folder(tmp_path, rules=[RepeatedScalarFieldRule])
        assert not list(diags)

    def test_reports_repeated_field_across_the_folder(self, tmp_path):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        codes = {d.code for d in lint_folder(tmp_path, rules=[RepeatedScalarFieldRule])}
        assert "repeated-field" in codes

    def _with_map(self, tmp_path):
        (tmp_path / "global.ini").write_text(
            "Object Base\n    Behavior = AutoHealBehavior ModuleTag_Heal\n    End\nEnd\n",
            encoding="utf-8",
        )
        map_dir = tmp_path / "maps" / "MyMap"
        map_dir.mkdir(parents=True)
        (map_dir / "map.ini").write_text(
            "ChildObject Tweak Base\n    Behavior = ArmorUpgrade ModuleTag_Bare\n    End\nEnd\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_lints_each_map_in_its_own_context(self, tmp_path):
        # Maps are excluded from the global build, but linted on the side against it.
        root = self._with_map(tmp_path)
        diags = [
            d for d in lint_folder(root, rules=[MapBareModuleRule]) if d.code == "map-bare-module"
        ]
        assert len(diags) == 1
        assert "ModuleTag_Bare" in diags[0].message

    def test_excluded_maps_are_not_linted(self, tmp_path):
        root = self._with_map(tmp_path)
        diags = lint_folder(root, rules=[MapBareModuleRule], exclude=(root / "maps",))
        assert not [d for d in diags if d.code == "map-bare-module"]

    def _with_map_only_button(self, tmp_path):
        # A global button nothing global references, reached only by a map.ini's command set.
        (tmp_path / "global.ini").write_text(
            "CommandButton Command_MapOnly\n    Command = UNIT_BUILD\nEnd\n", encoding="utf-8"
        )
        map_dir = tmp_path / "maps" / "MyMap"
        map_dir.mkdir(parents=True)
        (map_dir / "map.ini").write_text(
            "CommandSet MapSet\n    1 = Command_MapOnly\nEnd\n", encoding="utf-8"
        )
        return tmp_path

    def test_a_definition_only_a_map_references_is_not_unused(self, tmp_path):
        # The global graph cannot see per-map contexts; the finding is retracted once the
        # map builds show they reference the definition.
        root = self._with_map_only_button(tmp_path)
        names = {
            d.extra["name"]
            for d in lint_folder(root, rules=[UnusedDefinitionRule])
            if d.code == "unused-definition"
        }
        assert "Command_MapOnly" not in names

    def test_the_map_reference_is_not_seen_when_maps_are_excluded(self, tmp_path):
        # With the maps directory excluded no map context is built, so the only reference
        # to the button is invisible and the finding stands.
        root = self._with_map_only_button(tmp_path)
        names = {
            d.extra["name"]
            for d in lint_folder(root, rules=[UnusedDefinitionRule], exclude=(root / "maps",))
            if d.code == "unused-definition"
        }
        assert "Command_MapOnly" in names


class TestExcludeFromLint:
    def _wip_folder(self, tmp_path):
        (tmp_path / "wip").mkdir()
        (tmp_path / "wip" / "draft.ini").write_text(
            "Object Draft\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        (tmp_path / "shipped.ini").write_text(
            "Object Shipped\n    BuildCost = 100\nEnd\n", encoding="utf-8"
        )
        return tmp_path

    def test_excluded_directory_diagnostics_are_dropped(self, tmp_path):
        root = self._wip_folder(tmp_path)
        diags = lint_folder(root, rules=[RepeatedScalarFieldRule], exclude=(root / "wip",))
        assert not list(diags)

    def test_only_the_excluded_directory_is_silenced(self, tmp_path):
        # A problem outside the excluded directory is still reported.
        root = self._wip_folder(tmp_path)
        (root / "shipped.ini").write_text(
            "Object Shipped\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        diags = lint_folder(root, rules=[RepeatedScalarFieldRule], exclude=(root / "wip",))
        files = {Path(d.span.file).name for d in diags}
        assert files == {"shipped.ini"}

    def test_excluded_files_still_build_the_game(self, tmp_path):
        # The excluded object must still load so cross-file references resolve.
        root = self._wip_folder(tmp_path)
        loaded = load_game(root)
        assert "Draft" in loaded.game.objects
