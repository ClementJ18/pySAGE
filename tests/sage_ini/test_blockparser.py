"""Unit tests for sage_ini.parser.blockparser.

Every block shape is pinned by a real construct from the game-data corpus.
Malformed input must never raise: it produces diagnostics and the parser
recovers (CONVENTIONS.md rule 4).
"""

import textwrap

from sage_ini.parser.ast import Attribute, Block, Comment, Include, MacroDef, ScriptBlock
from sage_ini.parser.blockparser import parse


def parse_clean(text: str):
    """Parse expecting zero diagnostics; return the document."""
    result = parse(textwrap.dedent(text), file="t.ini")
    assert not result.diagnostics, [str(d) for d in result.diagnostics]
    return result.document


class TestBlockShapes:
    def test_plain_header_block(self):
        doc = parse_clean(
            """\
            WeaponSet
                Conditions = None
            End
            """
        )

        (block,) = doc.children
        assert isinstance(block, Block)
        assert block.name == "WeaponSet"
        assert block.label is None
        assert block.uses_equals is False
        assert block.children == [Attribute(key="Conditions", value="None", span=block.span)]

    def test_labeled_block(self):
        doc = parse_clean("Object MordorFighter\nEnd\n")

        (block,) = doc.children
        assert block.name == "Object"
        assert block.label == "MordorFighter"

    def test_two_token_label(self):
        doc = parse_clean("ChildObject ElvenWarriorLorien ElvenWarrior\nEnd\n")

        (block,) = doc.children
        assert block.name == "ChildObject"
        assert block.label == "ElvenWarriorLorien ElvenWarrior"

    def test_module_header_with_equals(self):
        doc = parse_clean(
            """\
            Behavior = AutoHealBehavior ModuleTag_05
                HealingAmount = 5
            End
            """
        )

        (block,) = doc.children
        assert block.name == "Behavior"
        assert block.label == "AutoHealBehavior ModuleTag_05"
        assert block.uses_equals is True
        assert block.children[0].key == "HealingAmount"

    def test_block_opening_attribute(self):
        # corpus: mordorfighter.ini `LodOptions = LOW ... End`
        doc = parse_clean(
            """\
            LodOptions = LOW
                AllowMultipleModels = ALLOW_MULTIPLE_MODELS_LOW
            End
            """
        )

        (block,) = doc.children
        assert block.name == "LodOptions"
        assert block.label == "LOW"
        assert block.uses_equals is True

    def test_headerless_body(self):
        doc = parse_clean(
            """\
            DefaultModelConditionState
                Model = MUOrcWar_SKN
            End
            """
        )

        (block,) = doc.children
        assert block.name == "DefaultModelConditionState"
        assert block.label is None

    def test_nested_blocks(self):
        doc = parse_clean(
            """\
            Object MordorFighter
                Draw = W3DHordeModelDraw ModuleTag_01
                    LodOptions = LOW
                        MaxRandomTextures = 2
                    End
                End
                CommandPoints = 60
            End
            """
        )

        (obj,) = doc.children
        draw, points = obj.children
        assert draw.name == "Draw"
        assert draw.label == "W3DHordeModelDraw ModuleTag_01"
        (lod,) = draw.children
        assert lod.name == "LodOptions"
        assert points == Attribute(key="CommandPoints", value="60", span=obj.span)

    def test_unknown_nested_block_does_not_desync_parent(self):
        # the current_issues.txt case: an unparsed module's End must not
        # terminate the enclosing Object
        doc = parse_clean(
            """\
            Object SomeBuilding
                ProductionQueueHordeContain
                    ObjectStatusOfContained = UNSELECTABLE
                End
                BuildCost = 500
            End
            """
        )

        (obj,) = doc.children
        contain, cost = obj.children
        assert isinstance(contain, Block)
        assert contain.name == "ProductionQueueHordeContain"
        assert cost.key == "BuildCost"

    def test_misplaced_equals_in_block_header(self):
        # corpus: mumakil.ini `Behavior SubObjectsUpgrade = FadeInTheHodwah` —
        # the engine treats '=' as a skippable token wherever it appears
        doc = parse_clean(
            """\
            Behavior SubObjectsUpgrade = FadeInTheHodwah
                TriggeredBy = Upgrade_MumakilLevel1
            End
            """
        )

        (block,) = doc.children
        assert block.name == "Behavior"
        assert block.label == "SubObjectsUpgrade FadeInTheHodwah"
        assert block.uses_equals is True
        assert block.children[0].key == "TriggeredBy"

    def test_end_is_case_insensitive(self):
        doc = parse_clean("Object A\nEND\nObject B\nend\n")

        assert [block.label for block in doc.children] == ["A", "B"]

    def test_stray_punctuation_after_end_is_not_a_block(self):
        # corpus: unitchronicles.ini `End        "` — junk token preserved as
        # a value line, never an opener
        doc = parse_clean('Object A\n    TransitionState = T\n    End "\nEnd\n')

        (obj,) = doc.children
        state, junk = obj.children
        assert state.name == "TransitionState"
        assert junk == Attribute(key='"', value="", uses_equals=False, span=obj.span)

    def test_end_followed_by_statement_on_same_line(self):
        # corpus: cinematicobjects.ini `End   StateName = Sword` — the engine
        # is token-based; End closes the block and the rest is the next field
        doc = parse_clean(
            """\
            AnimationState = X
                Animation = AttackWithSwordF
                    AnimationMode = ONCE
                End StateName = Sword
            End
            """
        )

        (state,) = doc.children
        animation, name = state.children
        assert isinstance(animation, Block)
        assert animation.name == "Animation"
        assert name == Attribute(key="StateName", value="Sword", span=state.span)


class TestAttributes:
    def test_value_keeps_internal_spacing(self):
        doc = parse_clean("EconomyUpgradeProbability = 1 : 1050\n")

        (attr,) = doc.children
        assert attr.value == "1 : 1050"

    def test_value_collapses_internal_whitespace_runs(self):
        # Tabs and runs of spaces between tokens are alignment, not meaning, so
        # the value canonicalizes to single spaces (the formatter then emits it).
        doc = parse_clean("DamageScalar = 0.0\tANY  +HERO\n")

        (attr,) = doc.children
        assert attr.value == "0.0 ANY +HERO"

    def test_empty_value(self):
        doc = parse_clean("Upgrades =\n")

        (attr,) = doc.children
        assert attr.key == "Upgrades"
        assert attr.value == ""

    def test_splits_on_first_equals(self):
        doc = parse_clean("Condition = EMOTION_ALERT = nope\n")

        (attr,) = doc.children
        assert attr.key == "Condition"
        assert attr.value == "EMOTION_ALERT = nope"

    def test_digit_key(self):
        # corpus: commandset.ini slots
        doc = parse_clean("CommandSet GondorFighterCommandSet\n    1 = Command_ToggleStance\nEnd\n")

        (block,) = doc.children
        assert block.children == [Attribute(key="1", value="Command_ToggleStance", span=block.span)]


class TestBareValueLines:
    def test_bare_value_key_is_an_attribute(self):
        # corpus: crate.ini `ParticleSysBone NONE GoldChestGlimmer`
        doc = parse_clean(
            """\
            DefaultModelConditionState
                Model = PchestTreasure
                ParticleSysBone NONE GoldChestGlimmer
            End
            """
        )

        (block,) = doc.children
        model, bone = block.children
        assert bone == Attribute(
            key="ParticleSysBone",
            value="NONE GoldChestGlimmer",
            uses_equals=False,
            span=block.span,
        )

    def test_bare_value_key_without_value(self):
        # corpus: credits.ini `Blank`
        doc = parse_clean("Blank\n")

        (attr,) = doc.children
        assert attr == Attribute(key="Blank", value="", uses_equals=False, span=doc.span)

    def test_side_is_a_value_inside_controlbarscheme(self):
        # corpus: controlbarscheme.ini
        doc = parse_clean(
            """\
            ControlBarScheme Mordor8x6
                ScreenCreationRes X:1024 Y:768
                Side Mordor
            End
            """
        )

        (scheme,) = doc.children
        assert [child.key for child in scheme.children] == ["ScreenCreationRes", "Side"]


class TestScriptBlocks:
    def test_script_body_is_opaque(self):
        # corpus: createaheroanims.inc — Lua bodies contain `end`, which must
        # not close ini blocks
        doc = parse_clean(
            """\
            AnimationState = MOVING
                BeginScript
                    if CurDrawableModelcondition("DYING") then return "DIE" end
                    return "IDLA"
                EndScript
                Flags = RANDOMSTART
            End
            """
        )

        (state,) = doc.children
        script, flags = state.children
        assert isinstance(script, ScriptBlock)
        assert script.lines == [
            '        if CurDrawableModelcondition("DYING") then return "DIE" end',
            '        return "IDLA"',
        ]
        assert flags.key == "Flags"

    def test_script_lines_keep_comment_markers_verbatim(self):
        # Lua code may contain ini comment markers; bodies are raw text
        doc = parse_clean("BeginScript\n    x = a - -b ; lua, not an ini comment\nEndScript\n")

        (script,) = doc.children
        assert script.lines == ["    x = a - -b ; lua, not an ini comment"]

    def test_glued_comment_on_beginscript(self):
        # corpus: createaheroanims.inc `BeginScript//script to set transition`
        doc = parse_clean("BeginScript//script to set transition\nEndScript\n")

        (script,) = doc.children
        assert script.comment == "//script to set transition"
        assert script.lines == []

    def test_unterminated_script_yields_diagnostic(self):
        result = parse("BeginScript\n    return 1\n", file="t.ini")

        assert [d.code for d in result.diagnostics] == ["unclosed-script"]


class TestDirectives:
    def test_define(self):
        doc = parse_clean("#define STRONG_DAMAGE 120\n")

        assert doc.children == [MacroDef(name="STRONG_DAMAGE", value="120", span=doc.span)]

    def test_define_with_multi_token_value(self):
        doc = parse_clean("#define EMOTION_PANIC_TIME 5000 3000\n")

        (macro,) = doc.children
        assert macro.value == "5000 3000"

    def test_include(self):
        doc = parse_clean('#include "..\\Common\\LivingWorldDefaultRTSSettings.inc"\n')

        assert doc.children == [
            Include(path="..\\Common\\LivingWorldDefaultRTSSettings.inc", span=doc.span)
        ]


class TestComments:
    def test_standalone_comment_becomes_node(self):
        doc = parse_clean("; Moved from MordorInfantry.INI\nObject A\nEnd\n")

        comment, block = doc.children
        assert comment == Comment(text="; Moved from MordorInfantry.INI", span=doc.span)

    def test_comment_inside_block_is_a_child(self):
        doc = parse_clean("Object A\n    // art params\n    BuildCost = 1\nEnd\n")

        (block,) = doc.children
        assert block.children[0] == Comment(text="// art params", span=doc.span)

    def test_trailing_comment_on_attribute(self):
        doc = parse_clean("OkToChangeModelColor = Yes // colorable\n")

        (attr,) = doc.children
        assert attr.value == "Yes"
        assert attr.comment == "// colorable"

    def test_trailing_comment_on_block_header_and_end(self):
        doc = parse_clean("Object A ; header note\nEnd ; closing note\n")

        (block,) = doc.children
        assert block.comment == "; header note"
        assert block.end_comment == "; closing note"


class TestSpans:
    def test_attribute_span_is_its_line(self):
        doc = parse_clean("Object A\n    BuildCost = 1\nEnd\n")

        (block,) = doc.children
        (attr,) = block.children
        assert (attr.span.line_start, attr.span.line_end) == (2, 2)

    def test_block_span_covers_header_to_end(self):
        doc = parse_clean("; intro\nObject A\n    BuildCost = 1\nEnd\n")

        block = doc.children[1]
        assert (block.span.line_start, block.span.line_end) == (2, 4)
        assert block.span.file == "t.ini"


class TestRecovery:
    def test_stray_end_yields_diagnostic_and_parsing_continues(self):
        result = parse("End\nObject A\nEnd\n", file="t.ini")

        assert [d.code for d in result.diagnostics] == ["stray-end"]
        assert result.diagnostics[0].span.line_start == 1
        (block,) = result.document.children
        assert block.label == "A"

    def test_unclosed_block_yields_diagnostic_and_stays_in_tree(self):
        result = parse("Object A\n    BuildCost = 1\n", file="t.ini")

        assert [d.code for d in result.diagnostics] == ["unclosed-block"]
        (block,) = result.document.children
        assert block.label == "A"
        assert len(block.children) == 1

    def test_unknown_directive_yields_diagnostic(self):
        result = parse("#frobnicate all the things\n", file="t.ini")

        assert [d.code for d in result.diagnostics] == ["unknown-directive"]

    def test_nothing_raises_on_garbage(self):
        result = parse("End\nEnd\n#define\n#include nope\nEnd\n", file="t.ini")

        assert result.diagnostics
        assert result.document.children == []
