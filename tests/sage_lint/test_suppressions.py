"""Inline `sagelint: ignore` suppression comments (sage_lint.suppressions)."""

from sage_lint.linter import lint_file, lint_folder
from sage_lint.suppressions import line_suppressions


class TestLineSuppressions:
    def test_parses_bracketed_codes(self):
        assert line_suppressions("X = 1 ; sagelint: ignore[unknown-attribute]") == {
            1: frozenset({"unknown-attribute"})
        }

    def test_parses_several_codes_comma_or_space_separated(self):
        text = "X = 1 ; sagelint: ignore[unused-definition, dangling-reference out-of-range]"
        assert line_suppressions(text) == {
            1: frozenset({"unused-definition", "dangling-reference", "out-of-range"})
        }

    def test_bare_ignore_suppresses_everything(self):
        assert line_suppressions("X = 1 ; sagelint: ignore") == {1: None}
        assert line_suppressions("X = 1 ; sagelint: ignore[]") == {1: None}

    def test_directive_and_codes_match_case_insensitively(self):
        assert line_suppressions("X = 1 ; SageLint: IGNORE[Unknown-Attribute]") == {
            1: frozenset({"unknown-attribute"})
        }

    def test_every_comment_marker_carries_a_directive(self):
        for marker in (";", "//", "--"):
            assert line_suppressions(f"X = 1 {marker} sagelint: ignore[a-code]") == {
                1: frozenset({"a-code"})
            }, marker

    def test_a_plain_comment_is_not_a_directive(self):
        assert line_suppressions("X = 1 ; just a note about ignoring nothing") == {}

    def test_maps_the_directive_to_its_own_line(self):
        text = "Object Foo\n    X = 1 ; sagelint: ignore[a-code]\nEnd\n"
        assert line_suppressions(text) == {2: frozenset({"a-code"})}


class TestSuppressionFiltering:
    def test_suppresses_the_named_code_on_its_line(self, tmp_path):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    MadeUpThing = 1 ; sagelint: ignore[unknown-attribute]\nEnd\n",
            encoding="utf-8",
        )
        assert all(d.code != "unknown-attribute" for d in lint_folder(tmp_path))

    def test_does_not_suppress_a_different_code(self, tmp_path):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    MadeUpThing = 1 ; sagelint: ignore[out-of-range]\nEnd\n",
            encoding="utf-8",
        )
        assert any(d.code == "unknown-attribute" for d in lint_folder(tmp_path))

    def test_only_covers_the_line_the_comment_is_on(self, tmp_path):
        (tmp_path / "a.ini").write_text(
            "Object Foo ; sagelint: ignore[unknown-attribute]\n    MadeUpThing = 1\nEnd\n",
            encoding="utf-8",
        )
        assert any(d.code == "unknown-attribute" for d in lint_folder(tmp_path))

    def test_suppresses_a_block_diagnostic_on_its_header_line(self, tmp_path):
        # unused-definition spans the whole block; its span starts on the header.
        (tmp_path / "a.ini").write_text(
            "Upgrade Lonely ; sagelint: ignore[unused-definition]\nEnd\n", encoding="utf-8"
        )
        assert all(d.code != "unused-definition" for d in lint_folder(tmp_path))

    def test_bare_ignore_suppresses_every_code_on_the_line(self, tmp_path):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    MadeUpThing = 1 ; sagelint: ignore\nEnd\n", encoding="utf-8"
        )
        assert all(d.code != "unknown-attribute" for d in lint_folder(tmp_path))

    def test_applies_on_the_single_file_path_too(self, tmp_path):
        path = tmp_path / "a.ini"
        path.write_text(
            "Object Foo\n    MadeUpThing = 1 ; sagelint: ignore[unknown-attribute]\nEnd\n",
            encoding="utf-8",
        )
        assert all(d.code != "unknown-attribute" for d in lint_file(path))
