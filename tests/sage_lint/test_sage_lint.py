"""Unit tests for the sage_lint formatter and its CLI."""

import io
import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.parser.location import Span
from sage_lint.cli import main
from sage_lint.commands.common import base_paths, resolve_rule_set
from sage_lint.config import Config
from sage_lint.fixer import fix_diagnostics
from sage_lint.formatter import format_file, format_text
from sage_lint.rules.base import RULES


class TestFormatText:
    def test_reindents_to_four_spaces(self):
        result = format_text("Object Foo\n  Armor = NONE\nEnd\n", file="t.ini")

        assert result.changed
        assert not result.skipped
        assert result.formatted == "Object Foo\n    Armor = NONE\nEnd\n"

    def test_already_canonical_is_unchanged(self):
        text = "Object Foo\n    Armor = NONE\nEnd\n"
        result = format_text(text, file="t.ini")

        assert not result.changed
        assert result.formatted == text

    def test_is_idempotent(self):
        once = format_text("Object Foo\n\tArmor = NONE\n\n\n  Weapon = Sword\nEnd\n").formatted
        twice = format_text(once).formatted

        assert once == twice

    def test_blank_lines_are_preserved(self):
        text = "Object Foo\n    A = 1\n\n    B = 2\nEnd\n"
        result = format_text(text, file="t.ini")

        assert not result.changed
        assert "\n\n" in result.formatted

    def test_tab_indentation_is_a_smell_and_is_fixed(self):
        result = format_text("Object Foo\n\tArmor = NONE\nEnd\n", file="t.ini")

        assert [s.code for s in result.smells] == ["tab-indentation"]
        assert result.smells[0].span.line_start == 2
        assert "\t" not in result.formatted

    def test_mixed_indentation_is_a_smell(self):
        result = format_text("Object Foo\n \tArmor = NONE\nEnd\n", file="t.ini")

        assert [s.code for s in result.smells] == ["mixed-indentation"]

    def test_tabs_inside_a_script_body_are_not_flagged(self):
        # The printer reproduces a BeginScript/EndScript body verbatim, so its tabs can
        # never be reformatted — flagging them would be an un-fixable warning. Tabs outside
        # the body are still reported and fixed.
        text = (
            "Object Foo\n"
            "\tArmor = NONE\n"
            "    BeginScript\n"
            '\t\tCurDrawableHideSubObject("X")\n'
            "    EndScript\n"
            "End\n"
        )
        result = format_text(text, file="t.ini")

        assert [(s.code, s.span.line_start) for s in result.smells] == [("tab-indentation", 2)]
        # The script body keeps its tab verbatim; the outside tab is reindented.
        assert '\t\tCurDrawableHideSubObject("X")' in result.formatted
        assert "\tArmor" not in result.formatted

    def test_structural_error_is_skipped_not_rewritten(self):
        text = "Object Foo\n    A = 1\nEnd\nEnd\n"  # stray End
        result = format_text(text, file="t.ini")

        assert result.skipped
        assert not result.changed
        assert result.formatted == text
        assert any(d.code == "stray-end" for d in result.parse_diagnostics)


class TestFormatFile:
    def test_reads_and_reports_encoding(self, tmp_path):
        path = tmp_path / "x.ini"
        path.write_text("Object Foo\n  A = 1\nEnd\n", encoding="utf-8")
        result = format_file(path)

        assert result.changed
        assert result.encoding in {"utf-8", "utf-8-sig"}


class TestCli:
    def _make(self, tmp_path, text):
        path = tmp_path / "x.ini"
        path.write_text(text, encoding="utf-8")
        return path

    def test_check_exits_one_when_formatting_needed(self, tmp_path, capsys):
        path = self._make(tmp_path, "Object Foo\n  A = 1\nEnd\n")

        assert main(["format", "--check", str(path)]) == 1
        assert path.read_text(encoding="utf-8") == "Object Foo\n  A = 1\nEnd\n"  # untouched
        assert "would reformat" in capsys.readouterr().out

    def test_check_exits_zero_when_clean(self, tmp_path):
        path = self._make(tmp_path, "Object Foo\n    A = 1\nEnd\n")

        assert main(["format", "--check", str(path)]) == 0

    def test_write_reformats_in_place(self, tmp_path):
        path = self._make(tmp_path, "Object Foo\n  A = 1\nEnd\n")

        assert main(["format", str(path)]) == 0
        assert path.read_text(encoding="utf-8") == "Object Foo\n    A = 1\nEnd\n"

    def test_write_preserves_crlf_newlines(self, tmp_path):
        path = tmp_path / "x.ini"
        path.write_bytes(b"Object Foo\r\n  A = 1\r\nEnd\r\n")

        assert main(["format", str(path)]) == 0
        assert path.read_bytes() == b"Object Foo\r\n    A = 1\r\nEnd\r\n"

    def test_structural_error_file_is_left_alone(self, tmp_path, capsys):
        text = "Object Foo\n    A = 1\nEnd\nEnd\n"
        path = self._make(tmp_path, text)

        assert main(["format", str(path)]) == 0
        assert path.read_text(encoding="utf-8") == text
        assert "skipped" in capsys.readouterr().out

    def test_lint_clean_folder_exits_zero(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCost = 100\nEnd\n", encoding="utf-8")

        assert main(["lint", str(tmp_path)]) == 0
        assert "0 error(s)" in capsys.readouterr().out

    def test_lint_reports_repeated_field_and_exits_one(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )

        assert main(["lint", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "repeated-field" in out

    def test_lint_surfaces_unknown_attributes_by_default(self, tmp_path, capsys):
        # An untyped field is a coverage gap, reported at ERROR without needing --level INFO.
        (tmp_path / "a.ini").write_text("Object Foo\n    MadeUpThing = 1\nEnd\n", encoding="utf-8")

        assert main(["lint", str(tmp_path)]) == 1
        assert "unknown-attribute" in capsys.readouterr().out

    def test_lint_list_codes_lists_rules_and_parse_codes(self, capsys):
        # works without a root argument and exits zero
        assert main(["lint", "--list-codes"]) == 0
        out = capsys.readouterr().out

        # every registered rule code is listed (sourced live from RULES)...
        for rule in RULES:
            assert rule.code in out
        # ...alongside the non-rule parser/conversion codes --ignore also accepts
        for code in ("conversion-error", "enum-case", "stray-end", "rule-error"):
            assert code in out
        # formatter-only smells are not lint codes and must not appear
        assert "tab-indentation" not in out

    def test_lint_ignore_silences_a_diagnostic_code(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )

        # without --ignore the repeated field is reported and the run fails
        assert main(["lint", str(tmp_path)]) == 1
        assert "repeated-field" in capsys.readouterr().out

        # ignoring the code drops it entirely: nothing shown, exit zero
        assert main(["lint", str(tmp_path), "--ignore", "repeated-field"]) == 0
        out = capsys.readouterr().out
        assert "repeated-field" not in out
        assert "0 error(s), 0 warning(s)" in out

    def test_lint_ignore_accepts_repeated_and_comma_separated_codes(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n"
            "    BuildCost = 1\n"
            "    BuildCost = 2\n"  # repeated-field (warning)
            "    EditorSorting = System\n"  # enum-case (warning)
            "    MadeUpThing = 1\n"  # unknown-attribute (error)
            "End\n",
            encoding="utf-8",
        )

        # comma-separated and repeated forms both apply
        rc = main(
            [
                "lint",
                "--level",
                "INFO",
                "--ignore",
                "repeated-field,enum-case",
                "--ignore",
                "unknown-attribute",
                str(tmp_path),
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        for code in ("repeated-field", "enum-case", "unknown-attribute"):
            assert code not in out

    def test_lint_filter_scopes_to_a_block_attribute(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n"
            "    Body = ActiveBody ModuleTag_01\n"
            "        MaxHealth = notanumber\n"  # conversion-error on ActiveBody.MaxHealth
            "    End\n"
            "    MadeUpThing = 1\n"  # unknown-attribute on Object.MadeUpThing
            "End\n",
            encoding="utf-8",
        )

        # An exact TYPE.ATTR keeps only that origin's diagnostic.
        assert main(["lint", str(tmp_path), "--filter", "ActiveBody.MaxHealth"]) == 1
        out = capsys.readouterr().out
        assert "conversion-error" in out
        assert "unknown-attribute" not in out

        # A wildcard block, fixed attribute matches the same one.
        assert main(["lint", str(tmp_path), "--filter", "*.MaxHealth"]) == 1
        assert "conversion-error" in capsys.readouterr().out

        # A wildcard attribute keeps every diagnostic from that block.
        assert main(["lint", str(tmp_path), "--filter", "Object.*"]) == 1
        out = capsys.readouterr().out
        assert "unknown-attribute" in out
        assert "conversion-error" not in out

        # A bare (dotless) pattern globs the attribute alone, across blocks.
        assert main(["lint", str(tmp_path), "--filter", "MadeUp*"]) == 1
        out = capsys.readouterr().out
        assert "unknown-attribute" in out
        assert "conversion-error" not in out

        # A non-matching filter drops everything and exits clean.
        assert main(["lint", str(tmp_path), "--filter", "ArmorSet.Armor"]) == 0
        assert "0 error(s), 0 warning(s)" in capsys.readouterr().out

    def test_lint_ignore_skips_the_fix_for_that_code(self, tmp_path, capsys):
        original = "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n"
        path = tmp_path / "a.ini"
        path.write_text(original, encoding="utf-8")

        # an ignored code is not auto-fixed: the file is left untouched
        assert main(["lint", str(tmp_path), "--ignore", "repeated-field", "--fix"]) == 0
        assert "nothing to fix" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == original

    def test_lint_exclude_silences_a_directory(self, tmp_path, capsys):
        (tmp_path / "wip").mkdir()
        (tmp_path / "wip" / "draft.ini").write_text(
            "Object Draft\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )

        assert main(["lint", str(tmp_path), "--exclude", str(tmp_path / "wip")]) == 0
        assert "repeated-field" not in capsys.readouterr().out

    def _mixed_severity_file(self, tmp_path):
        # A warning (repeated BuildCost) on an early line and an error (dangling weapon)
        # on a later one, so file-order and severity-order disagree.
        path = tmp_path / "a.ini"
        path.write_text(
            "Object Foo\n"
            "    BuildCost = 1\n"
            "    BuildCost = 2\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY Sword\n"
            "    End\n"
            "End\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _diag_lines(out: str) -> list[str]:
        return [line for line in out.splitlines() if line.endswith("]")]

    def test_sort_file_orders_by_line(self, tmp_path, capsys):
        self._mixed_severity_file(tmp_path)
        main(["lint", str(tmp_path), "--sort", "file"])
        lines = self._diag_lines(capsys.readouterr().out)
        warn = next(i for i, line in enumerate(lines) if "repeated-field" in line)
        error = next(i for i, line in enumerate(lines) if "conversion-error" in line)
        assert warn < error  # the earlier line comes first regardless of severity

    def test_sort_severity_orders_errors_first(self, tmp_path, capsys):
        self._mixed_severity_file(tmp_path)
        main(["lint", str(tmp_path), "--sort", "severity"])
        lines = self._diag_lines(capsys.readouterr().out)
        warn = next(i for i, line in enumerate(lines) if "repeated-field" in line)
        error = next(i for i, line in enumerate(lines) if "conversion-error" in line)
        assert error < warn

    def test_sort_rejects_an_unknown_mode(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["lint", str(tmp_path), "--sort", "nonsense"])

    def test_lint_base_resolves_cross_reference(self, tmp_path, capsys):
        mod = tmp_path / "mod"
        base = tmp_path / "base"
        mod.mkdir()
        base.mkdir()
        (mod / "hero.ini").write_text(
            "Object Hero\n    WeaponSet\n        Weapon = PRIMARY Sword\n    End\nEnd\n",
            encoding="utf-8",
        )

        # without the base, the weapon reference dangles into a conversion error
        assert main(["lint", str(mod)]) == 1
        assert "no Weapon named 'Sword'" in capsys.readouterr().out

        # the base supplies the weapon; the reference now resolves
        (base / "weapons.ini").write_text(
            "Weapon Sword\n    PrimaryDamage = 5\nEnd\n", encoding="utf-8"
        )
        assert main(["lint", str(mod), "--base", str(base)]) == 0
        assert "0 error(s)" in capsys.readouterr().out

    def test_lint_base_problems_are_not_reported(self, tmp_path, capsys):
        mod = tmp_path / "mod"
        base = tmp_path / "base"
        mod.mkdir()
        base.mkdir()
        (mod / "ok.ini").write_text("Object Fine\n    BuildCost = 1\nEnd\n", encoding="utf-8")
        # a base file with its own lint problem (repeated scalar field)
        (base / "junk.ini").write_text(
            "Object BaseJunk\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )

        # the base is build-only: its problem never reaches the report
        assert main(["lint", str(mod), "--base", str(base)]) == 0
        assert "repeated-field" not in capsys.readouterr().out

    def test_lint_flags_enum_case_mismatch_as_warning(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    EditorSorting = System\nEnd\n", encoding="utf-8"
        )

        # an enum token that only matched ignoring case is accepted but warned
        assert main(["lint", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "enum-case" in out
        assert "warning" in out

    def test_lint_flags_reference_case_mismatch_as_warning(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(
            "MappedImage BRFoo\nEnd\nObject Foo\n    SelectPortrait = brfoo\nEnd\n",
            encoding="utf-8",
        )

        # a reference that only matched the definition ignoring case is resolved but warned
        assert main(["lint", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "reference-case" in out
        assert "warning" in out

    def test_fix_rewrites_enum_case_and_repeated_field(self, tmp_path, capsys):
        path = tmp_path / "a.ini"
        path.write_text(
            "Object Foo\n"
            "    EditorSorting = System   ; keep me\n"
            "    BuildCost = 1\n"
            "    BuildCost = 2\n"
            "    KindOf = INFANTRY Structure +Hero\n"
            "End\n",
            encoding="utf-8",
        )

        assert main(["lint", str(tmp_path), "--fix"]) == 0
        out = capsys.readouterr().out
        assert "fixed 4 issue(s)" in out
        assert path.read_text(encoding="utf-8") == (
            "Object Foo\n"
            "    EditorSorting = SYSTEM   ; keep me\n"  # canonical case, comment kept
            "    BuildCost = 2\n"  # only the last assignment survives
            "    KindOf = INFANTRY STRUCTURE +HERO\n"  # only miscased tokens touched
            "End\n"
        )

    def test_fix_deletes_space_delimited_repeated_field(self, tmp_path, capsys):
        # A repeated field written in the space form (`Geometry nh1_fills`, no `=`) is just as
        # fixable as the `=` form: the earlier occurrence is deleted, the last one survives.
        path = tmp_path / "a.ini"
        path.write_text(
            "LivingWorldRegionEffects\n"
            "    HomeRegionHighlight\n"
            "        Geometry nh1_fills ;keep nothing, line goes\n"
            "        Geometry nh1_borders\n"
            "    End\n"
            "End\n",
            encoding="utf-8",
        )

        assert main(["lint", str(tmp_path), "--fix", "--select", "repeated-field"]) == 0
        assert "fixed 1 issue(s)" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == (
            "LivingWorldRegionEffects\n"
            "    HomeRegionHighlight\n"
            "        Geometry nh1_borders\n"  # only the last occurrence survives
            "    End\n"
            "End\n"
        )

    def test_fix_rewrites_reference_case(self, tmp_path, capsys):
        path = tmp_path / "a.ini"
        path.write_text(
            "MappedImage BRFoo\nEnd\nObject Foo\n    SelectPortrait = brfoo   ; keep me\nEnd\n",
            encoding="utf-8",
        )

        assert main(["lint", str(tmp_path), "--fix"]) == 0
        out = capsys.readouterr().out
        assert "fixed 1 issue(s)" in out
        assert path.read_text(encoding="utf-8") == (
            "MappedImage BRFoo\nEnd\n"
            "Object Foo\n"
            "    SelectPortrait = BRFoo   ; keep me\n"  # definition casing, comment kept
            "End\n"
        )

    def test_fix_reference_case_follows_macro_to_its_define(self, tmp_path, capsys):
        # The miscased reference reaches the field through a macro (`TargetNames = MYSHIPS`),
        # so the token lives in the `#define`, not at the use site. The fix follows it back and
        # rewrites the macro body; the use line is untouched.
        path = tmp_path / "a.ini"
        path.write_text(
            "#define MYSHIPS brshipx\n"
            "Object BRShipX\nEnd\n"
            "ExperienceLevel L1\n"
            "    TargetNames = MYSHIPS\n"
            "    Rank = 1\n"
            "End\n",
            encoding="utf-8",
        )

        assert main(["lint", str(tmp_path), "--fix", "--select", "reference-case"]) == 0
        assert "fixed 1 issue(s)" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == (
            "#define MYSHIPS BRShipX\n"  # the macro body now carries the definition's casing
            "Object BRShipX\nEnd\n"
            "ExperienceLevel L1\n"
            "    TargetNames = MYSHIPS\n"  # the use site is left alone
            "    Rank = 1\n"
            "End\n"
        )
        # And nothing is left to report on a second pass.
        assert main(["lint", str(tmp_path), "--select", "reference-case"]) == 0

    def test_fix_summary_describes_changes_in_plain_terms(self, tmp_path, capsys):
        # A reference-case and a repeated-field fix in one run: the summary names each kind
        # and reassures that nothing else changed (the nervous-modder report).
        path = tmp_path / "a.ini"
        path.write_text(
            "MappedImage BRFoo\nEnd\n"
            "Object Foo\n    SelectPortrait = brfoo\n"
            "    BuildCost = 1\n    BuildCost = 2\nEnd\n",
            encoding="utf-8",
        )

        main(["lint", str(tmp_path), "--fix"])
        out = capsys.readouterr().out
        assert "1 reference casing" in out
        assert "1 duplicate field" in out
        assert "Nothing else was touched." in out

    def test_fix_is_idempotent_and_clears_the_warnings(self, tmp_path, capsys):
        path = tmp_path / "a.ini"
        path.write_text("Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8")

        assert main(["lint", str(tmp_path), "--fix"]) == 0  # fixed, nothing left to report
        capsys.readouterr()
        # a second pass has nothing to do and the file is unchanged
        assert main(["lint", str(tmp_path), "--fix"]) == 0
        assert "nothing to fix" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == ("Object Foo\n    BuildCost = 2\nEnd\n")

    def test_fix_preserves_crlf_and_adds_no_bom(self, tmp_path):
        path = tmp_path / "a.ini"
        path.write_bytes(b"Object Foo\r\n    BuildCost = 1\r\n    BuildCost = 2\r\nEnd\r\n")

        assert main(["lint", str(tmp_path), "--fix"]) == 0
        assert path.read_bytes() == b"Object Foo\r\n    BuildCost = 2\r\nEnd\r\n"

    def test_fix_leaves_excluded_files_untouched(self, tmp_path):
        wip = tmp_path / "wip"
        wip.mkdir()
        draft = wip / "draft.ini"
        original = "Object D\n    BuildCost = 1\n    BuildCost = 2\nEnd\n"
        draft.write_text(original, encoding="utf-8")

        assert main(["lint", str(tmp_path), "--exclude", str(wip), "--fix"]) == 0
        assert draft.read_text(encoding="utf-8") == original

    def test_fix_rewrites_macro_case(self, tmp_path, capsys):
        # A macro reference matched a #define only by ignoring case; --fix aligns the use site
        # to the #define's spelling (the same token rewrite as reference/enum case).
        path = tmp_path / "a.ini"
        path.write_text(
            "#define MY_DAMAGE 2000\nWeapon Foo\n    PrimaryDamage = my_damage   ; keep me\nEnd\n",
            encoding="utf-8",
        )

        assert main(["lint", str(tmp_path), "--fix", "--select", "macro-case"]) == 0
        assert "fixed 1 issue(s)" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == (
            "#define MY_DAMAGE 2000\nWeapon Foo\n    PrimaryDamage = MY_DAMAGE   ; keep me\nEnd\n"
        )

    def test_fix_removes_earlier_repeated_flag_field(self, tmp_path, capsys):
        # A whole-set flag field (EditorSorting) set twice keeps only the last; --fix deletes
        # the earlier set, exactly as it does a repeated scalar.
        path = tmp_path / "a.ini"
        path.write_text(
            "Object Foo\n"
            "    EditorSorting = STRUCTURE\n"
            "    EditorSorting = SYSTEM   ; the one that wins\n"
            "End\n",
            encoding="utf-8",
        )

        assert main(["lint", str(tmp_path), "--fix", "--select", "repeated-flag-field"]) == 0
        assert "fixed 1 issue(s)" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == (
            "Object Foo\n    EditorSorting = SYSTEM   ; the one that wins\nEnd\n"
        )

    def test_fix_removes_spurious_block_label_equals(self, tmp_path, capsys):
        # A ThreatBreakdown header written `= Tag` parses, but the engine ignores the `=`;
        # --fix rewrites it to the plain `Block Tag` header form.
        path = tmp_path / "a.ini"
        path.write_text(
            "Object Foo\n"
            "    ThreatBreakdown = Foo_Detail   ; keep me\n"
            "        AIThreatNumberOfTimes = 1\n"
            "    End\n"
            "End\n",
            encoding="utf-8",
        )

        assert main(["lint", str(tmp_path), "--fix", "--select", "spurious-block-label"]) == 0
        assert "fixed 1 issue(s)" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == (
            "Object Foo\n"
            "    ThreatBreakdown Foo_Detail   ; keep me\n"
            "        AIThreatNumberOfTimes = 1\n"
            "    End\n"
            "End\n"
        )

    def test_lint_dedups_identical_diagnostics_from_a_shared_include(self, tmp_path, capsys):
        (tmp_path / "snippet.inc").write_text(
            "Behavior = ObjectCreationUpgrade ModuleTag_X\n"
            "    RemoveUpgrade = Missing_Upgrade\n"
            "End\n",
            encoding="utf-8",
        )
        # the snippet is #included into two distinct objects
        (tmp_path / "a.ini").write_text(
            'Object Aaa\n    #include "snippet.inc"\nEnd\n'
            'Object Bbb\n    #include "snippet.inc"\nEnd\n',
            encoding="utf-8",
        )

        assert main(["lint", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        # the identical dangling-upgrade error is reported once, not per include
        assert out.count("no Upgrade named 'Missing_Upgrade'") == 1

    def test_lint_rejects_non_directory(self, tmp_path):
        path = tmp_path / "x.ini"
        path.write_text("Object Foo\nEnd\n", encoding="utf-8")

        with pytest.raises(SystemExit):
            main(["lint", str(path)])

    def test_folder_walk_picks_up_ini_and_inc(self, tmp_path):
        (tmp_path / "a.ini").write_text("Object A\n  X = 1\nEnd\n", encoding="utf-8")
        (tmp_path / "b.inc").write_text("Object B\n  Y = 2\nEnd\n", encoding="utf-8")
        (tmp_path / "c.txt").write_text("Object C\n  Z = 3\nEnd\n", encoding="utf-8")

        assert main(["format", str(tmp_path)]) == 0
        assert (tmp_path / "a.ini").read_text(encoding="utf-8") == "Object A\n    X = 1\nEnd\n"
        assert (tmp_path / "b.inc").read_text(encoding="utf-8") == "Object B\n    Y = 2\nEnd\n"
        # .txt is not an ini suffix and is left untouched
        assert (tmp_path / "c.txt").read_text(encoding="utf-8") == "Object C\n  Z = 3\nEnd\n"


# A file exercising a mix of severities: a repeated field (warning), a miscased
# enum (warning) and an unknown attribute (error).
_MIXED = (
    "Object Foo\n"
    "    BuildCost = 1\n"
    "    BuildCost = 2\n"
    "    EditorSorting = System\n"
    "    MadeUpThing = 1\n"
    "End\n"
)


class TestLintNewOptions:
    def test_output_format_json_emits_parsable_report(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(_MIXED, encoding="utf-8")

        assert main(["lint", str(tmp_path), "--level", "INFO", "--output-format", "json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        codes = {d["code"] for d in payload["diagnostics"]}
        assert {"repeated-field", "enum-case", "unknown-attribute"} <= codes
        assert payload["summary"] == {
            "errors": 1,
            "warnings": 2,
            "hidden": 0,
            "fixed": 0,
            "baselined": 0,
        }
        first = payload["diagnostics"][0]
        assert set(first) == {"code", "severity", "message", "file", "line_start", "line_end"}

    def test_select_reports_only_the_chosen_code(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(_MIXED, encoding="utf-8")

        assert main(["lint", str(tmp_path), "--select", "repeated-field"]) == 1
        out = capsys.readouterr().out
        assert "repeated-field" in out
        assert "enum-case" not in out
        assert "unknown-attribute" not in out

    def test_select_and_ignore_combine(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(_MIXED, encoding="utf-8")

        # select both warnings, then ignore one back out
        assert (
            main(
                [
                    "lint",
                    str(tmp_path),
                    "--select",
                    "repeated-field,enum-case",
                    "--ignore",
                    "enum-case",
                ]
            )
            == 1
        )
        out = capsys.readouterr().out
        assert "repeated-field" in out
        assert "enum-case" not in out

    def test_statistics_prints_a_count_table(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(_MIXED, encoding="utf-8")

        assert main(["lint", str(tmp_path), "--level", "INFO", "--statistics"]) == 1
        out = capsys.readouterr().out
        assert "1  warning  repeated-field" in out
        assert "1  error    unknown-attribute" in out

    def test_exit_zero_keeps_exit_code_zero(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(_MIXED, encoding="utf-8")

        assert main(["lint", str(tmp_path), "--exit-zero"]) == 0
        assert "warning(s)" in capsys.readouterr().out  # still reports, just exits 0

    def test_verbose_prints_the_offending_source_line(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(_MIXED, encoding="utf-8")

        assert main(["lint", str(tmp_path), "--verbose"]) == 1
        assert "| BuildCost = 1" in capsys.readouterr().out

    def test_quiet_suppresses_the_per_diagnostic_lines(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(_MIXED, encoding="utf-8")

        assert main(["lint", str(tmp_path), "--quiet"]) == 1
        out = capsys.readouterr().out
        assert "repeated-field" not in out
        assert "1 error(s), 2 warning(s)" in out


class TestFormatStdin:
    def test_stdin_writes_formatted_text_to_stdout(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("Object Foo\n  X = 1\nEnd\n"))

        assert main(["format", "--stdin"]) == 0
        assert capsys.readouterr().out == "Object Foo\n    X = 1\nEnd\n"

    def test_stdin_align_equals_pads_keys(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("Object Foo\n  A = 1\n  LongName = 2\nEnd\n"))

        assert main(["format", "--stdin", "--align-equals"]) == 0
        assert capsys.readouterr().out == ("Object Foo\n    A        = 1\n    LongName = 2\nEnd\n")

    def test_stdin_align_exclude_skips_a_block_type(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(
                "Object Foo\n"
                "  A = 1\n"
                "  LongName = 2\n"
                "  Draw = W3D Tag\n"
                "    ModelName = X\n"
                "    AnotherKey = Y\n"
                "  End\n"
                "End\n"
            ),
        )

        assert main(["format", "--stdin", "--align-equals", "--align-exclude", "Draw"]) == 0
        out = capsys.readouterr().out
        assert "    A        = 1\n    LongName = 2\n" in out  # Object attrs still aligned
        assert "        ModelName = X\n        AnotherKey = Y\n" in out  # Draw left unaligned

    def test_stdin_check_exits_one_when_reformat_needed(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("Object Foo\n  X = 1\nEnd\n"))

        assert main(["format", "--stdin", "--check"]) == 1
        assert capsys.readouterr().out == ""  # check writes nothing to stdout

    def test_stdin_json_reports_change(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("Object Foo\n  X = 1\nEnd\n"))

        assert main(["format", "--stdin", "--output-format", "json", "--check"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["changed"] is True
        assert payload["file"] == "<stdin>"

    def test_stdin_and_paths_are_mutually_exclusive(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("x"))

        with pytest.raises(SystemExit):
            main(["format", "--stdin", "a.ini"])

    def test_format_output_format_json_for_files(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\n  X = 1\nEnd\n", encoding="utf-8")

        assert main(["format", str(tmp_path), "--check", "--output-format", "json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["need_format"] == 1
        assert payload["results"][0]["changed"] is True


class TestFixerTokenGuard:
    """The fixer must only count a case rewrite it actually applies. A diagnostic whose span
    points at a line that doesn't hold the token (a repeated field flagged on its first
    occurrence, or a macro-supplied value) would otherwise be 'fixed' on every run forever."""

    @staticmethod
    def _enum_case(path, line: int, given: str, canonical: str) -> Diagnostic:
        return Diagnostic(
            code="enum-case",
            message=f"{given} matched {canonical} only by case",
            span=Span(str(path), line, line),
            severity=Severity.WARNING,
            extra={"given": given, "canonical": canonical},
        )

    def test_no_op_rewrite_is_not_counted_and_leaves_the_file(self, tmp_path):
        # A repeated field: the offending `Yes` is on line 3, but (as the model does) the
        # diagnostic is pinned to the first occurrence on line 2, which holds `NO`.
        text = (
            "Object Foo\n"
            "    AutoAcquireEnemiesWhenIdle = NO\n"
            "    AutoAcquireEnemiesWhenIdle = Yes ATTACK_BUILDINGS\n"
            "End\n"
        )
        path = tmp_path / "a.ini"
        path.write_text(text, encoding="utf-8")

        fixed_by_file, applied = fix_diagnostics([self._enum_case(path, 2, "Yes", "YES")])

        assert applied == []  # nothing applied — the token isn't on the reported line
        assert fixed_by_file == {}
        assert path.read_text(encoding="utf-8") == text  # file untouched, so no re-trigger

    def test_rewrite_on_the_right_line_still_applies(self, tmp_path):
        text = (
            "Object Foo\n"
            "    AutoAcquireEnemiesWhenIdle = NO\n"
            "    AutoAcquireEnemiesWhenIdle = Yes ATTACK_BUILDINGS\n"
            "End\n"
        )
        path = tmp_path / "a.ini"
        path.write_text(text, encoding="utf-8")

        fixed_by_file, applied = fix_diagnostics([self._enum_case(path, 3, "Yes", "YES")])

        assert len(applied) == 1
        assert "AutoAcquireEnemiesWhenIdle = YES ATTACK_BUILDINGS" in path.read_text(
            encoding="utf-8"
        )


# Two pre-existing problems: a repeated scalar (warning) and an unknown attribute (error).
_NOISY = "Object Foo\n    BuildCost = 1\n    BuildCost = 2\n    Weapon = NoSuchWeapon\nEnd\n"


class TestBaseline:
    """`--write-baseline` records today's diagnostics; `--baseline` then reports only what is
    new against that record, matched line-insensitively so editing files does not resurface
    accepted problems."""

    def _write(self, tmp_path, text=_NOISY):
        (tmp_path / "a.ini").write_text(text, encoding="utf-8")

    def test_write_then_clean_run(self, tmp_path, capsys):
        self._write(tmp_path)
        bl = tmp_path / "bl.json"

        assert main(["lint", str(tmp_path), "--baseline", str(bl), "--write-baseline"]) == 0
        assert "wrote 2 baseline" in capsys.readouterr().out
        assert bl.is_file()

        # With the baseline in place, both pre-existing problems are suppressed and the run is
        # clean (exit 0), the count surfaced in the summary.
        assert main(["lint", str(tmp_path), "--baseline", str(bl)]) == 0
        assert "2 baselined" in capsys.readouterr().out

    def test_new_problem_is_reported_despite_line_shift(self, tmp_path, capsys):
        self._write(tmp_path)
        bl = tmp_path / "bl.json"
        main(["lint", str(tmp_path), "--baseline", str(bl), "--write-baseline"])
        capsys.readouterr()

        # Push every line down and add a brand-new error. The baselined two stay suppressed
        # (line numbers are not part of the match); only the new one is reported.
        self._write(
            tmp_path,
            "\n; pushed down\n\n"
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\n"
            "    Weapon = NoSuchWeapon\n    Armor = AlsoNotAThing\nEnd\n",
        )
        assert main(["lint", str(tmp_path), "--baseline", str(bl)]) == 1
        out = capsys.readouterr().out
        assert "Armor is not a known attribute" in out
        assert "2 baselined" in out
        assert "BuildCost" not in out  # the accepted problems stay silent

    def test_extra_occurrence_beyond_the_recorded_count_is_new(self, tmp_path, capsys):
        # Baseline records one "BuildCost set 2 times". A second object with the same problem
        # produces a second identical message; only the surplus over the recorded count is new.
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        bl = tmp_path / "bl.json"
        main(["lint", str(tmp_path), "--baseline", str(bl), "--write-baseline"])
        capsys.readouterr()

        (tmp_path / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n"
            "Object Bar\n    BuildCost = 3\n    BuildCost = 4\nEnd\n",
            encoding="utf-8",
        )
        assert main(["lint", str(tmp_path), "--baseline", str(bl)]) == 1
        assert "1 baselined" in capsys.readouterr().out

    def test_baseline_is_auto_discovered_beside_the_config(self, tmp_path, capsys):
        # A `.sagelint.baseline` next to the linted folder is used without any flag.
        self._write(tmp_path)
        assert (
            main(
                [
                    "lint",
                    str(tmp_path),
                    "--baseline",
                    str(tmp_path / ".sagelint.baseline"),
                    "--write-baseline",
                ]
            )
            == 0
        )
        capsys.readouterr()
        assert main(["lint", str(tmp_path)]) == 0
        assert "2 baselined" in capsys.readouterr().out

    def test_corrupt_baseline_fails_loud_not_clean(self, tmp_path, capsys):
        self._write(tmp_path)
        bl = tmp_path / "bl.json"
        bl.write_text("{ not valid json", encoding="utf-8")

        # A broken baseline must not let everything through silently: it reports the error and
        # treats the baseline as empty, so the run still fails on the real problems.
        assert main(["lint", str(tmp_path), "--baseline", str(bl)]) == 1
        captured = capsys.readouterr()
        assert "not a valid baseline" in captured.err
        assert "1 error(s), 1 warning(s)" in captured.out

    def test_write_baseline_rejects_fix(self, tmp_path):
        self._write(tmp_path)
        with pytest.raises(SystemExit):
            main(["lint", str(tmp_path), "--write-baseline", "--fix"])

    def test_json_summary_reports_baselined_count(self, tmp_path, capsys):
        self._write(tmp_path)
        bl = tmp_path / "bl.json"
        main(["lint", str(tmp_path), "--baseline", str(bl), "--write-baseline"])
        capsys.readouterr()

        main(["lint", str(tmp_path), "--baseline", str(bl), "--output-format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["baselined"] == 2
        assert payload["diagnostics"] == []


class TestLintMaps:
    """The `lint-maps` subcommand wiring. The per-map logic is covered in tests/test_sage_map*;
    here we exercise the CLI path end to end on a folder with no `.map` files."""

    def test_empty_folder_exits_zero_with_zero_maps(self, tmp_path, capsys):
        pytest.importorskip("reversebox", reason="requires the optional [map] extra")
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCost = 1\nEnd\n", encoding="utf-8")

        assert main(["lint-maps", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "across 0 maps" in out

    def test_json_report_has_diagnostics_and_summary(self, tmp_path, capsys):
        pytest.importorskip("reversebox", reason="requires the optional [map] extra")
        (tmp_path / "a.ini").write_text("Object Foo\nEnd\n", encoding="utf-8")

        assert main(["lint-maps", str(tmp_path), "--output-format", "json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["diagnostics"] == []
        assert set(payload["summary"]) == {"errors", "warnings", "hidden"}


class TestLintIncludesMaps:
    """`lint` (folder mode) lints the binary .map layouts only when `--maps` is given (off by
    default). The integration is exercised here for the wiring; the map diagnostics themselves are
    covered in tests/test_sage_map*."""

    def test_maps_flag_is_accepted_and_lints_normally(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCost = 1\nEnd\n", encoding="utf-8")
        assert main(["lint", str(tmp_path), "--maps", "--no-config"]) == 0
        assert "0 error(s)" in capsys.readouterr().out

    def test_default_run_does_not_lint_maps(self, tmp_path, capsys):
        # maps are off by default, so no map pass runs (and no map diagnostics appear)
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCost = 1\nEnd\n", encoding="utf-8")
        assert main(["lint", str(tmp_path), "--no-config"]) == 0
        assert "map-dangling" not in capsys.readouterr().out


class TestBasePaths:
    """`base_paths` loads `assets_base`/`maps_base` only when the matching check is on."""

    def test_conditional_bases_added_only_when_their_check_is_on(self, tmp_path):
        args = Namespace(base=[], assets_base=[], maps_base=[])
        config = Config(base=["b"], assets_base=["ab"], maps_base=["mb"])
        assert base_paths(args, config, tmp_path, include_assets=False) == [tmp_path / "b"]
        assert base_paths(args, config, tmp_path, include_assets=True) == [
            tmp_path / "b",
            tmp_path / "ab",
        ]
        assert base_paths(args, config, tmp_path, include_assets=True, include_maps=True) == [
            tmp_path / "b",
            tmp_path / "ab",
            tmp_path / "mb",
        ]
        assert base_paths(args, config, tmp_path, include_assets=False, include_maps=True) == [
            tmp_path / "b",
            tmp_path / "mb",
        ]

    def test_cli_lists_override_config(self, tmp_path):
        args = Namespace(base=[Path("X")], assets_base=[Path("Y")], maps_base=[Path("Z")])
        config = Config(base=["b"], assets_base=["ab"], maps_base=["mb"])
        assert base_paths(args, config, tmp_path, include_assets=True, include_maps=True) == [
            Path("X"),
            Path("Y"),
            Path("Z"),
        ]


class TestAssetRulesOptIn:
    """The missing-texture/model/map-file rules are off by default (they flood without the base
    archives), enabled by `--assets` or the config `assets` key."""

    def _mod(self, tmp_path):
        # references a texture the mod does not ship, with a loose texture so the index is
        # non-empty (the empty-index guard would otherwise hide it regardless of the opt-in)
        (tmp_path / "a.ini").write_text(
            "MappedImage X\n    Texture = Missing_999.tga\nEnd\n", encoding="utf-8"
        )
        art = tmp_path / "art"
        art.mkdir()
        (art / "real.tga").write_bytes(b"x")

    def test_plain_lint_omits_asset_rules(self, tmp_path, capsys):
        self._mod(tmp_path)
        assert main(["lint", str(tmp_path), "--no-config"]) == 0
        assert "missing-texture-file" not in capsys.readouterr().out

    def test_assets_flag_enables_them(self, tmp_path, capsys):
        self._mod(tmp_path)
        assert main(["lint", str(tmp_path), "--assets", "--no-config"]) == 1
        assert "missing-texture-file" in capsys.readouterr().out

    def test_config_assets_key_enables_them(self, tmp_path, capsys):
        self._mod(tmp_path)
        (tmp_path / ".sagelint").write_text("assets = true\n", encoding="utf-8")
        assert main(["lint", str(tmp_path)]) == 1
        assert "missing-texture-file" in capsys.readouterr().out


class TestRuleSetResolution:
    """`--assets` turns on the asset-group opt-in rules, but a non-asset opt-in rule
    (unused-object) stays off unless named in `--select`."""

    def _codes(self, rules):
        return {rule.code for rule in (rules if rules is not None else [])}

    def test_assets_adds_only_the_asset_group(self):
        codes = self._codes(resolve_rule_set(set(), include_assets=True))
        assert "missing-texture-file" in codes
        assert "unused-object" not in codes  # opt-in, but not part of the asset group
        assert "unused-definition" in codes  # on by default

    def test_select_can_still_name_unused_object(self):
        codes = self._codes(resolve_rule_set({"unused-object"}, include_assets=True))
        assert codes == {"unused-object"}


class TestBaseBigIndexing:
    """A reference to an asset/map packed in a base-game `.big` must resolve once that `.big` is
    added with `--base`: textures/models are indexed by name (not extracted), maps are extracted
    and indexed. Otherwise a real base-game texture (e.g. HeroUI_001) is wrongly flagged missing."""

    def _big(self, directory, dest):
        from pyBIG import Archive  # noqa: PLC0415 — only this test needs the .big writer

        Archive.from_directory(str(directory)).save(str(dest))
        return dest

    def test_base_big_texture_name_resolves_a_reference(self, tmp_path, capsys):
        basesrc = tmp_path / "basesrc"
        (basesrc / "art").mkdir(parents=True)
        (basesrc / "art" / "HeroUI_001.dds").write_bytes(b"x")
        big = self._big(basesrc, tmp_path / "textures.big")

        mod = tmp_path / "mod"
        (mod / "data").mkdir(parents=True)
        (mod / "data" / "a.ini").write_text(
            "MappedImage X\n    Texture = HeroUI_001.tga\nEnd\n", encoding="utf-8"
        )
        (mod / "art").mkdir()  # a loose texture so the index is non-empty even without the base
        (mod / "art" / "modtex.tga").write_bytes(b"x")

        common = ["--select", "missing-texture-file", "--no-config"]
        assert main(["lint", str(mod), *common]) == 1  # flagged without the base
        assert "HeroUI_001" in capsys.readouterr().out

        rc = main(["lint", str(mod), "--base", str(big), *common])  # base .big indexes its name
        assert "HeroUI_001" not in capsys.readouterr().out
        assert rc == 0

    def test_base_big_map_is_extracted_and_resolves(self, tmp_path, capsys):
        basesrc = tmp_path / "basesrc"
        (basesrc / "maps" / "ai base - real").mkdir(parents=True)
        (basesrc / "maps" / "ai base - real" / "ai base - real.bse").write_bytes(b"x")
        big = self._big(basesrc, tmp_path / "bases.big")

        mod = tmp_path / "mod"
        (mod / "data").mkdir(parents=True)
        (mod / "data" / "ai.ini").write_text(
            'AIBase Foo\n    Map = "ai base - real"\nEnd\n'
            'AIBase Bar\n    Map = "no such layout"\nEnd\n',
            encoding="utf-8",
        )

        rc = main(
            ["lint", str(mod), "--base", str(big), "--select", "missing-map-file", "--no-config"]
        )
        out = capsys.readouterr().out
        assert "ai base - real" not in out  # the base .bse was extracted and indexed
        assert "no such layout" in out  # the genuinely missing one is still flagged
        assert rc == 1

    def test_assets_base_loads_only_with_assets(self, tmp_path, capsys):
        # A texture packed in an --assets-base .big resolves only when asset checking is on; the
        # archive is not loaded (so the rule cannot resolve against it) by a plain run.
        basesrc = tmp_path / "basesrc"
        (basesrc / "art").mkdir(parents=True)
        (basesrc / "art" / "Tex_001.dds").write_bytes(b"x")
        big = self._big(basesrc, tmp_path / "textures.big")

        mod = tmp_path / "mod"
        (mod / "data").mkdir(parents=True)
        (mod / "data" / "a.ini").write_text(
            "MappedImage X\n    Texture = Tex_001.tga\nEnd\n", encoding="utf-8"
        )
        (mod / "art").mkdir()
        (mod / "art" / "modtex.tga").write_bytes(b"x")  # keep the index non-empty

        # --assets without the assets-base: the texture is missing
        assert main(["lint", str(mod), "--assets", "--no-config"]) == 1
        assert "Tex_001" in capsys.readouterr().out

        # --assets plus the assets-base: the archived texture name is indexed, so it resolves
        rc = main(["lint", str(mod), "--assets", "--assets-base", str(big), "--no-config"])
        assert "Tex_001" not in capsys.readouterr().out
        assert rc == 0


class TestDiffCommand:
    """`sage_lint diff`: a config-aware, base-resolved changelog between two git refs."""

    def _git(self, repo, *args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    def _repo(self, tmp_path, sagelint, first, second, mod_rel="mod"):
        """A git repo with a `.sagelint`, a mod folder at `mod_rel`, and two commits whose mod
        ini is `first` then `second`. Returns the repo path."""
        repo = tmp_path / "repo"
        mod = repo / mod_rel
        mod.mkdir(parents=True)
        (repo / ".sagelint").write_text(sagelint, encoding="utf-8")
        data = mod / "data.ini"
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, text=True)
        self._git(repo, "config", "user.email", "t@t.t")
        self._git(repo, "config", "user.name", "t")
        data.write_text(first, encoding="utf-8")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "v1")
        data.write_text(second, encoding="utf-8")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "v2")
        return repo

    def test_changelog_uses_config_root(self, tmp_path, capsys):
        repo = self._repo(
            tmp_path,
            'root = "mod"\n',
            "Object Soldier\n    BuildCost = 100\nEnd\n",
            "Object Soldier\n    BuildCost = 150\nEnd\n",
        )
        assert main(["diff", "HEAD~1", "HEAD", str(repo)]) == 0
        assert "BuildCost: 100 -> 150" in capsys.readouterr().out

    def test_base_definitions_cancel_out(self, tmp_path, capsys):
        # A base-game definition present (identically) beneath both refs must not show up as a
        # change — the base merge applies to both sides and cancels.
        base = tmp_path / "base" / "data" / "ini"
        base.mkdir(parents=True)
        (base / "base.ini").write_text(
            "Object BaseUnit\n    BuildCost = 5\nEnd\n", encoding="utf-8"
        )
        repo = self._repo(
            tmp_path,
            'root = "mod"\n',
            "Object ModUnit\n    BuildCost = 100\nEnd\n",
            "Object ModUnit\n    BuildCost = 150\nEnd\n",
        )
        assert main(["diff", "HEAD~1", "HEAD", str(repo), "--base", str(base)]) == 0
        out = capsys.readouterr().out
        assert "BuildCost: 100 -> 150" in out
        assert "BaseUnit" not in out  # base content is identical on both refs, so it cancels

    def test_no_config_diffs_repo_root(self, tmp_path, capsys):
        # With --no-config the config root is ignored; diff the repo root itself.
        repo = self._repo(
            tmp_path,
            'root = "mod"\n',
            "Object A\n    BuildCost = 1\nEnd\n",
            "Object A\n    BuildCost = 2\nEnd\n",
            mod_rel=".",
        )
        assert main(["diff", "HEAD~1", "HEAD", str(repo), "--no-config"]) == 0
        assert "BuildCost: 1 -> 2" in capsys.readouterr().out
