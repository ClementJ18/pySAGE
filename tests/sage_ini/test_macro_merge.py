"""Tests for set-aware `#define` list conflict resolution (`sage_ini.macro_merge`)."""

import json

from sage_ini.__main__ import main
from sage_ini.macro_merge import (
    format_macro_report,
    merge_macro_tokens,
    resolve_macro_conflicts,
)


def marked(ours: str, base: str | None, theirs: str) -> str:
    """A one-hunk conflict-marked file (diff3 when `base` is given)."""
    lines = ["<<<<<<< ours", ours]
    if base is not None:
        lines += ["||||||| base", base]
    lines += ["=======", theirs, ">>>>>>> theirs"]
    return "\n".join(lines) + "\n"


class TestMergeMacroTokens:
    def test_add_add_union_keeps_both(self):
        merged, ro, rt = merge_macro_tokens(["a", "b"], ["a", "b", "x"], ["a", "b", "y"])
        assert merged == ["a", "b", "x", "y"]
        assert ro == set() and rt == set()

    def test_one_sided_removal_is_honoured(self):
        # ours drops "c"; theirs keeps it -> the deletion wins, "c" is gone.
        merged, ro, rt = merge_macro_tokens(["a", "b", "c"], ["a", "b"], ["a", "b", "c"])
        assert "c" not in merged
        assert ro == {"c"} and rt == set()

    def test_removed_by_both(self):
        merged, ro, rt = merge_macro_tokens(["a", "b", "c"], ["a", "b"], ["a", "c"])
        assert merged == ["a"]
        assert ro == {"c"} and rt == {"b"}

    def test_no_base_is_order_preserving_union(self):
        merged, ro, rt = merge_macro_tokens(None, ["a", "b"], ["b", "c"])
        assert merged == ["a", "b", "c"]
        assert ro == set() and rt == set()

    def test_ours_order_is_the_spine(self):
        merged, _, _ = merge_macro_tokens(["a"], ["z", "a"], ["a", "q"])
        assert merged == ["z", "a", "q"]


class TestResolveMacroConflicts:
    def test_list_hunk_is_set_merged(self):
        text = marked(
            "#define SQUAD Alpha Bravo Delta Echo",
            "#define SQUAD Alpha Bravo Charlie Delta",
            "#define SQUAD Alpha Bravo Charlie Delta Foxtrot",
        )
        result = resolve_macro_conflicts(text)
        assert result.resolved == 1 and result.remaining == 0
        assert "<<<<<<<" not in result.text
        assert "#define SQUAD Alpha Bravo Delta Echo Foxtrot" in result.text
        (merge,) = result.merges
        assert merge.added_ours == ["Echo"]
        assert merge.added_theirs == ["Foxtrot"]
        assert merge.removed_one_side == [("Charlie", "ours")]

    def test_surrounding_content_preserved_verbatim(self):
        text = (
            "Object Before\nEnd\n"
            + marked("#define L a b x", "#define L a b", "#define L a b y")
            + "Object After\nEnd\n"
        )
        result = resolve_macro_conflicts(text)
        assert result.text.startswith("Object Before\nEnd\n")
        assert result.text.rstrip().endswith("Object After\nEnd")

    def test_scalar_hunk_left_as_conflict(self):
        text = marked("#define MONEY 1200", "#define MONEY 1000", "#define MONEY 1500")
        result = resolve_macro_conflicts(text)
        assert result.resolved == 0 and result.remaining == 1
        assert "<<<<<<<" in result.text  # untouched

    def test_non_macro_hunk_left_untouched(self):
        text = marked("BuildCost = 2", "BuildCost = 1", "BuildCost = 3")
        result = resolve_macro_conflicts(text)
        assert result.resolved == 0 and result.remaining == 1
        assert result.text == text

    def test_crlf_line_endings_preserved_not_doubled(self):
        text = (
            "X\r\n"
            + marked("#define L a b x", "#define L a b", "#define L a b y").replace("\n", "\r\n")
            + "Y\r\n"
        )
        out = resolve_macro_conflicts(text).text
        assert "\r\r\n" not in out  # the CR must not be doubled
        assert out == "X\r\n#define L a b x y\r\nY\r\n"

    def test_no_conflict_file_is_byte_identical(self):
        for text in ("Object A\r\n  BuildCost = 5\r\nEnd\r\n", "Object A\n  BuildCost = 5\nEnd"):
            assert resolve_macro_conflicts(text).text == text

    def test_two_way_hunk_unions_and_flags_no_base(self):
        text = marked("#define L a b x", None, "#define L a b y")
        result = resolve_macro_conflicts(text)
        assert result.resolved == 1
        (merge,) = result.merges
        assert merge.has_base is False
        assert merge.merged == ["a", "b", "x", "y"]

    def test_duplicates_are_reported(self):
        text = marked("#define L a b b x", "#define L a b", "#define L a b y")
        (merge,) = resolve_macro_conflicts(text).merges
        assert merge.duplicates == {"ours": ["b"]}

    def test_mismatched_macro_names_left_untouched(self):
        text = marked("#define FOO a b x", "#define FOO a b", "#define BAR a b y")
        result = resolve_macro_conflicts(text)
        assert result.resolved == 0 and result.remaining == 1

    def test_report_lists_deletions_to_verify(self):
        text = marked("#define L a b", "#define L a b c", "#define L a b c")
        report = format_macro_report(resolve_macro_conflicts(text))
        assert "VERIFY" in report
        assert "c (removed by ours)" in report


class TestMacroMergeCommand:
    def _write(self, tmp_path, text):
        path = tmp_path / "conflict.ini"
        path.write_text(text, encoding="utf-8")
        return path

    def test_dry_run_reports_without_writing(self, tmp_path, capsys):
        text = marked("#define L a b x", "#define L a b", "#define L a b y")
        path = self._write(tmp_path, text)
        assert main(["macro-merge", str(path)]) == 0
        assert "dry run" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == text  # unchanged

    def test_write_applies_merge(self, tmp_path):
        text = marked("#define L a b x", "#define L a b", "#define L a b y")
        path = self._write(tmp_path, text)
        assert main(["macro-merge", str(path), "--write"]) == 0
        written = path.read_text(encoding="utf-8")
        assert "<<<<<<<" not in written
        assert "#define L a b x y" in written

    def test_remaining_conflicts_exit_one(self, tmp_path):
        text = marked("#define M 2", "#define M 1", "#define M 3")  # scalar -> stays
        path = self._write(tmp_path, text)
        assert main(["macro-merge", str(path), "--write"]) == 1

    def test_json_output(self, tmp_path, capsys):
        text = marked("#define L a b x", "#define L a b", "#define L a b y")
        path = self._write(tmp_path, text)
        main(["macro-merge", str(path), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["resolved"] == 1
        assert payload["macros"][0]["added_ours"] == ["x"]
