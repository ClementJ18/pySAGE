"""Unit tests for sage_ini.parser.printer.

The printer re-emits a document with canonical indentation and all comments;
the contract is parse -> print -> reparse yields an identical tree (node
equality ignores spans).
"""

import textwrap

from sage_ini.parser.ast import BlankLine
from sage_ini.parser.blockparser import parse
from sage_ini.parser.printer import print_document


def roundtrip(text: str):
    first = parse(textwrap.dedent(text), file="t.ini")
    assert not first.diagnostics
    printed = print_document(first.document)
    second = parse(printed, file="reprint.ini")
    assert not second.diagnostics
    return first.document, printed, second.document


class TestCanonicalOutput:
    def test_known_document_prints_exactly(self):
        doc, printed, _ = roundtrip(
            """\
            ; banner
            #define STRONG_DAMAGE 120
            #include "common.inc"

            Object MordorFighter ; header note
              Draw = W3DHordeModelDraw ModuleTag_01
                  OkToChangeModelColor = Yes // colorable
              End
              BuildCost =
            End ; closing note
            """
        )

        assert printed == textwrap.dedent(
            """\
            ; banner
            #define STRONG_DAMAGE 120
            #include "common.inc"

            Object MordorFighter ; header note
                Draw = W3DHordeModelDraw ModuleTag_01
                    OkToChangeModelColor = Yes // colorable
                End
                BuildCost =
            End ; closing note
            """
        )

    def test_headerless_block_and_bare_label(self):
        _, printed, _ = roundtrip("DefaultModelConditionState\n  Model = X\nEnd\n")

        assert printed == "DefaultModelConditionState\n    Model = X\nEnd\n"


class TestAlignEquals:
    def _doc(self, text: str):
        result = parse(textwrap.dedent(text), file="t.ini")
        assert not result.diagnostics
        return result.document

    def test_block_attributes_align_per_block(self):
        doc = self._doc(
            """\
            Object Foo
                ShortKey = 1
                AVeryLongKeyName = 2
                Mid = 3
                Behavior = ActiveBody ModuleTag_01
                    MaxHealth = 100
                    InitialHealth = 50
                End
            End
            """
        )

        assert print_document(doc, align_equals=True) == textwrap.dedent(
            """\
            Object Foo
                ShortKey         = 1
                AVeryLongKeyName = 2
                Mid              = 3
                Behavior = ActiveBody ModuleTag_01
                    MaxHealth     = 100
                    InitialHealth = 50
                End
            End
            """
        )

    def test_empty_value_and_bare_value_lines(self):
        # An empty-value assignment still aligns its `=`; a bare-value line (no `=`) is
        # left alone and never widens the column.
        doc = self._doc(
            "DefaultModelConditionState\n"
            "    ParticleSysBone NONE Glimmer\n"
            "    LongAttr = 1\n"
            "    Short =\n"
            "End\n"
        )

        assert print_document(doc, align_equals=True) == (
            "DefaultModelConditionState\n"
            "    ParticleSysBone NONE Glimmer\n"
            "    LongAttr = 1\n"
            "    Short    =\n"
            "End\n"
        )

    def test_off_by_default_and_idempotent(self):
        text = "Object Foo\n    A = 1\n    LongName = 2\nEnd\n"
        doc = self._doc(text)
        # Default is the canonical single-space form.
        assert print_document(doc) == text
        # Aligning is a fixed point: reparse + reprint yields the same text.
        aligned = print_document(doc, align_equals=True)
        assert print_document(parse(aligned).document, align_equals=True) == aligned
        # The padding is cosmetic — the aligned tree equals the canonical one.
        assert parse(aligned).document.children == doc.children

    def test_blank_lines_reset_the_alignment_group(self):
        doc = self._doc(
            """\
            Object Foo
                A = 1
                LongName = 2

                X = 3
                ExtremelyLongKeyHere = 4
            End
            """
        )

        assert print_document(doc, align_equals=True) == textwrap.dedent(
            """\
            Object Foo
                A        = 1
                LongName = 2

                X                    = 3
                ExtremelyLongKeyHere = 4
            End
            """
        )

    def test_align_exclude_by_header_keyword_and_module_subtype(self):
        doc = self._doc(
            """\
            Object Foo
                A = 1
                LongName = 2
                Behavior = ActiveBody ModuleTag_01
                    MaxHealth = 100
                    InitialHealth = 50
                End
                Draw = W3D ModuleTag_02
                    ModelName = X
                    AnotherKey = Y
                End
            End
            """
        )

        # ActiveBody (module subtype) is excluded, so its attributes stay unaligned; the Draw
        # block is still aligned, as is the Object's own attribute group.
        printed = print_document(doc, align_equals=True, align_exclude=["ActiveBody"])
        assert printed == textwrap.dedent(
            """\
            Object Foo
                A        = 1
                LongName = 2
                Behavior = ActiveBody ModuleTag_01
                    MaxHealth = 100
                    InitialHealth = 50
                End
                Draw = W3D ModuleTag_02
                    ModelName  = X
                    AnotherKey = Y
                End
            End
            """
        )

        # Excluding by the header keyword (Object) leaves the top-level attributes unaligned
        # while the nested blocks still align.
        printed = print_document(doc, align_equals=True, align_exclude=["object"])
        assert "    A = 1\n    LongName = 2\n" in printed  # case-insensitive match
        assert "        ModelName  = X" in printed


class TestRoundTrip:
    def test_trees_are_equal(self):
        first, _, second = roundtrip(
            """\
            ; preamble
            #define X 1
            Object A
                ProductionQueueHordeContain
                    ObjectStatusOfContained = UNSELECTABLE ; note
                End
                LodOptions = LOW
                    MaxRandomTextures = 2
                End
                BuildCost = 500
            End
            """
        )

        assert first.children == second.children

    def test_print_is_a_fixed_point(self):
        _, printed, second = roundtrip("Object A ; n\n  K = V // c\nEnd\n")

        assert print_document(second) == printed

    def test_equals_style_of_header_survives(self):
        first, _, second = roundtrip("Behavior = AutoHealBehavior Tag\nEnd\nWeaponSet\nEnd\n")

        assert [b.uses_equals for b in first.children] == [True, False]
        assert first.children == second.children

    def test_bare_value_lines_print_without_equals(self):
        _, printed, second = roundtrip(
            "DefaultModelConditionState\n  ParticleSysBone NONE Glimmer\nEnd\nBlank\n"
        )

        assert printed == (
            "DefaultModelConditionState\n    ParticleSysBone NONE Glimmer\nEnd\nBlank\n"
        )
        assert print_document(second) == printed

    def test_script_body_round_trips_verbatim(self):
        first, printed, second = roundtrip(
            "AnimationState = MOVING\n"
            "  BeginScript\n"
            '    if x then return "DIE" end\n'
            "\n"
            "    return 1 ; lua\n"
            "  EndScript\n"
            "End\n"
        )

        assert first.children == second.children
        assert '    if x then return "DIE" end' in printed.splitlines()


class TestBlankLines:
    def test_run_of_blanks_collapses_to_one(self):
        _, printed, _ = roundtrip("K = 1\n\n\n\nL = 2\n")

        assert printed == "K = 1\n\nL = 2\n"

    def test_blanks_at_block_edges_are_dropped(self):
        _, printed, _ = roundtrip("Object A\n\n\n    K = 1\n\n\nEnd\n")

        assert printed == "Object A\n    K = 1\nEnd\n"

    def test_blank_between_nested_siblings_is_kept(self):
        _, printed, second = roundtrip("Object A\n    K = 1\n\n    L = 2\nEnd\n")

        assert printed == "Object A\n    K = 1\n\n    L = 2\nEnd\n"
        assert print_document(second) == printed

    def test_leading_and_trailing_document_blanks_are_dropped(self):
        _, printed, _ = roundtrip("\n\nK = 1\n\n\n")

        assert printed == "K = 1\n"

    def test_blank_before_end_does_not_separate_next_sibling(self):
        first, printed, _ = roundtrip("Object A\n    K = 1\n\nEnd\nObject B\nEnd\n")

        assert printed == "Object A\n    K = 1\nEnd\nObject B\nEnd\n"
        assert not any(isinstance(child, BlankLine) for child in first.children)

    def test_blank_lines_are_nodes_with_spans(self):
        doc = parse("K = 1\n\nL = 2\n", file="t.ini").document
        blanks = [child for child in doc.children if isinstance(child, BlankLine)]

        assert len(blanks) == 1
        assert blanks[0].span.file == "t.ini"
        assert blanks[0].span.line_start == 2
