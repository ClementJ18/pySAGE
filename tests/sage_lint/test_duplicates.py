"""Unit tests for `sage_lint.duplicates` (the detection engine: normalization, whole-block
and sibling-run clustering, maximality and containment suppression) and the `duplicates`
CLI command (output shapes, config wiring, exclusions)."""

import json
from pathlib import Path

import pytest

from sage_ini.parser.blockparser import parse
from sage_lint.cli import main
from sage_lint.duplicates import canonical_text, find_duplicates

# A 4-normalized-line block (header + 2 attributes + End) reused across cases.
_WEAPON = "Weapon SharedSword\n    PrimaryDamage = 10\n    Radius = 5.0\nEnd\n"


def _doc(text: str, file: str = "a.ini"):
    result = parse(text, file=file)
    assert not result.diagnostics.items, [str(d) for d in result.diagnostics]
    return result.document


def _write(folder: Path, name: str, text: str) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestNormalization:
    def test_comments_blanks_and_indentation_do_not_matter(self):
        plain = _doc(_WEAPON)
        noisy = _doc(
            "; a file comment\n"
            "Weapon SharedSword ; trailing\n"
            "\n"
            "  PrimaryDamage   =    10\n"
            "    ; interior comment\n"
            "    Radius = 5.0\n"
            "End ; done\n"
        )
        assert canonical_text(plain.children) == canonical_text(noisy.children)

    def test_different_values_do_not_match(self):
        other = _WEAPON.replace("10", "11")
        assert canonical_text(_doc(_WEAPON).children) != canonical_text(_doc(other).children)


class TestWholeBlocks:
    def test_cross_file_duplicate_block(self):
        docs = [_doc(_WEAPON, "a.ini"), _doc("; intro\n" + _WEAPON, "b.ini")]

        clusters = find_duplicates(docs, min_lines=4)

        assert len(clusters) == 1
        cluster = clusters[0]
        assert cluster.kind == "block"
        assert cluster.title == "Weapon SharedSword"
        assert cluster.lines == 4
        assert [span.file for span in cluster.occurrences] == ["a.ini", "b.ini"]
        assert cluster.saved_lines == 4 * 1 - 2

    def test_min_lines_threshold(self):
        docs = [_doc(_WEAPON, "a.ini"), _doc(_WEAPON, "b.ini")]
        assert find_duplicates(docs, min_lines=5) == []
        assert len(find_duplicates(docs, min_lines=4)) == 1

    def test_min_occurrences_threshold(self):
        docs = [_doc(_WEAPON, "a.ini"), _doc(_WEAPON, "b.ini")]
        assert find_duplicates(docs, min_lines=4, min_occurrences=3) == []

    def test_nested_block_duplicated_inside_different_parents(self):
        behavior = (
            "    Behavior = ActiveBody ModuleTag_Body\n"
            "        MaxHealth = 100\n"
            "        MaxHealthDamaged = 50\n"
            "    End\n"
        )
        docs = [
            _doc(f"Object FirstUnit\n    BuildCost = 1\n{behavior}End\n", "a.ini"),
            _doc(f"Object SecondUnit\n    BuildCost = 2\n{behavior}End\n", "b.ini"),
        ]

        clusters = find_duplicates(docs, min_lines=4)

        assert [c.title for c in clusters] == ["Behavior ActiveBody ModuleTag_Body"]
        assert clusters[0].kind == "block"

    def test_script_block_duplicates_are_found(self):
        text = "Object Scripted\n    BeginScript\n        return 1\n    EndScript\nEnd\n"
        docs = [_doc(text, "a.ini"), _doc(text, "b.ini")]

        clusters = find_duplicates(docs, min_lines=3)

        # The Object cluster wins (bigger); the script inside it is suppressed as contained.
        assert [c.title for c in clusters] == ["Object Scripted"]
        # On its own (parents differ), the script block is its own cluster.
        docs = [
            _doc("Object One\n    BeginScript\n        return 1\n    EndScript\nEnd\n", "a.ini"),
            _doc("Object Two\n    BeginScript\n        return 1\n    EndScript\nEnd\n", "b.ini"),
        ]
        clusters = find_duplicates(docs, min_lines=3)
        assert [c.title for c in clusters] == ["script block"]


class TestContainment:
    def test_inner_duplicate_suppressed_when_parents_duplicate(self):
        text = (
            "Object Soldier\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY Sword\n"
            "        Weapon = SECONDARY Bow\n"
            "    End\n"
            "End\n"
        )
        docs = [_doc(text, "a.ini"), _doc(text, "b.ini")]

        clusters = find_duplicates(docs, min_lines=4)

        assert [c.title for c in clusters] == ["Object Soldier"]

    def test_inner_duplicate_kept_when_it_also_occurs_standalone(self):
        weaponset = (
            "    WeaponSet\n"
            "        Weapon = PRIMARY Sword\n"
            "        Weapon = SECONDARY Bow\n"
            "    End\n"
        )
        obj = f"Object Soldier\n{weaponset}End\n"
        standalone = weaponset.replace("    ", "", 1).replace("\n        ", "\n    ")
        docs = [_doc(obj, "a.ini"), _doc(obj, "b.ini"), _doc(standalone, "c.ini")]

        clusters = find_duplicates(docs, min_lines=4)

        # The WeaponSet cluster saves more (3 sites x 4 lines) than the Object cluster
        # (2 sites x 6 lines), so it sorts first; both survive selection.
        assert [c.title for c in clusters] == ["WeaponSet", "Object Soldier"]
        assert len(clusters[0].occurrences) == 3


class TestRuns:
    _SHARED = (
        "    EmotionType = TAUNTING\n"
        "    Duration = 2000\n"
        "    Frequency = 3000\n"
        "    Radius = 140.0\n"
    )

    def _object(self, name: str, extra: str) -> str:
        return f"Object {name}\n    BuildCost = {extra}\n{self._SHARED}End\n"

    def test_shared_attribute_run_across_bodies(self):
        docs = [
            _doc(self._object("UnitA", "1"), "a.ini"),
            _doc(self._object("UnitB", "2"), "b.ini"),
            _doc(self._object("UnitC", "3"), "c.ini"),
        ]

        clusters = find_duplicates(docs, min_lines=4)

        assert len(clusters) == 1
        cluster = clusters[0]
        assert cluster.kind == "run"
        assert cluster.lines == 4
        assert len(cluster.occurrences) == 3
        # The run is the 4 shared attribute lines, not the differing BuildCost above them.
        span = cluster.occurrences[0]
        assert span.line_end - span.line_start == 3

    def test_longer_and_shorter_overlapping_runs_both_survive(self):
        longer = self._SHARED + "    ShareCount = 2\n    SharePriority = 5\n"
        docs = [
            _doc(f"Object UnitA\n    BuildCost = 1\n{longer}End\n", "a.ini"),
            _doc(f"Object UnitB\n    BuildCost = 2\n{longer}End\n", "b.ini"),
            _doc(f"Object UnitC\n    BuildCost = 3\n{self._SHARED}End\n", "c.ini"),
        ]

        clusters = find_duplicates(docs, min_lines=4)

        by_size = {len(c.occurrences): c for c in clusters}
        assert set(by_size) == {2, 3}
        assert by_size[2].lines == 6
        assert by_size[3].lines == 4

    def test_repeat_within_one_parent_counts_and_never_overlaps(self):
        body = "    Key = 1\n    Other = 2\n" * 3
        docs = [_doc(f"Object Repeated\n{body}End\n", "a.ini")]

        clusters = find_duplicates(docs, min_lines=2)

        assert len(clusters) == 1
        cluster = clusters[0]
        assert cluster.kind == "run"
        assert cluster.lines == 2
        assert len(cluster.occurrences) == 3
        starts = [span.line_start for span in cluster.occurrences]
        ends = [span.line_end for span in cluster.occurrences]
        assert all(later > earlier for earlier, later in zip(ends, starts[1:], strict=False))

    def test_comments_inside_a_run_do_not_break_it(self):
        commented = self._SHARED.replace("    Duration", "    ; why taunt\n    Duration", 1)
        docs = [
            _doc(f"Object UnitA\n    BuildCost = 1\n{self._SHARED}End\n", "a.ini"),
            _doc(f"Object UnitB\n    BuildCost = 2\n{commented}End\n", "b.ini"),
        ]

        clusters = find_duplicates(docs, min_lines=4)

        assert len(clusters) == 1
        assert clusters[0].kind == "run"

    def test_an_include_breaks_a_run(self):
        split = self._SHARED.replace("    Frequency", '    #include "shared.inc"\n    Frequency', 1)
        docs = [
            _doc(f"Object UnitA\n    BuildCost = 1\n{self._SHARED}End\n", "a.ini"),
            _doc(f"Object UnitB\n    BuildCost = 2\n{split}End\n", "b.ini"),
        ]

        assert find_duplicates(docs, min_lines=4) == []

    def test_macro_defs_participate_in_runs(self):
        macros = "#define SHARED_HEALTH 100\n#define SHARED_ARMOR ArmorLight\n"
        docs = [
            _doc(macros + "Weapon OnlyInA\n    PrimaryDamage = 1\nEnd\n", "a.ini"),
            _doc(macros + "Weapon OnlyInB\n    PrimaryDamage = 2\nEnd\n", "b.ini"),
        ]

        clusters = find_duplicates(docs, min_lines=2)

        assert len(clusters) == 1
        assert clusters[0].kind == "run"
        assert clusters[0].lines == 2


class TestDuplicatesCommandCli:
    def _tree(self, root: Path) -> None:
        _write(root, "a.ini", _WEAPON)
        _write(root, "sub/b.ini", "; a copy\n" + _WEAPON)

    def test_reports_and_exits_zero(self, tmp_path, capsys):
        self._tree(tmp_path)

        assert main(["duplicates", str(tmp_path), "--min-lines", "4"]) == 0
        out = capsys.readouterr().out
        assert "duplicate block 'Weapon SharedSword'" in out
        assert "a.ini:1-4" in out
        assert "1 duplicate cluster(s)" in out

    def test_clean_tree_exits_zero(self, tmp_path, capsys):
        _write(tmp_path, "a.ini", _WEAPON)

        assert main(["duplicates", str(tmp_path)]) == 0
        assert "no duplicates found" in capsys.readouterr().out

    def test_quiet_prints_only_the_summary(self, tmp_path, capsys):
        self._tree(tmp_path)

        assert main(["duplicates", str(tmp_path), "--min-lines", "4", "-q"]) == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1
        assert "1 duplicate cluster(s)" in out[0]

    def test_verbose_prints_the_snippet(self, tmp_path, capsys):
        self._tree(tmp_path)

        assert main(["duplicates", str(tmp_path), "--min-lines", "4", "-v"]) == 0
        assert "| Weapon SharedSword" in capsys.readouterr().out

    def test_json_output_shape(self, tmp_path, capsys):
        self._tree(tmp_path)

        rc = main(["duplicates", str(tmp_path), "--min-lines", "4", "--output-format", "json"])

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["summary"] == {
            "clusters": 1,
            "saved_lines": 2,
            "files_scanned": 2,
            "parse_error_files": 0,
        }
        (cluster,) = report["clusters"]
        assert cluster["kind"] == "block"
        assert cluster["title"] == "Weapon SharedSword"
        assert cluster["occurrences"][0]["line_start"] == 1

    def test_config_threshold_respected_and_cli_overrides(self, tmp_path, capsys):
        self._tree(tmp_path)
        _write(tmp_path, ".sagelint", "duplicate_min_lines = 30\n")

        assert main(["duplicates", str(tmp_path)]) == 0
        assert "no duplicates found" in capsys.readouterr().out

        assert main(["duplicates", str(tmp_path), "--min-lines", "4"]) == 0
        assert "1 duplicate cluster(s)" in capsys.readouterr().out

        assert main(["duplicates", str(tmp_path), "--no-config", "--min-lines", "4"]) == 0
        assert "1 duplicate cluster(s)" in capsys.readouterr().out

    def test_bad_config_value_warns_and_uses_defaults(self, tmp_path, capsys):
        self._tree(tmp_path)
        _write(tmp_path, ".sagelint", 'duplicate_min_lines = "many"\n')

        assert main(["duplicates", str(tmp_path), "--min-lines", "4"]) == 0
        captured = capsys.readouterr()
        assert "duplicate_min_lines" in captured.err
        assert "1 duplicate cluster(s)" in captured.out

    def test_exclude_skips_a_folder(self, tmp_path, capsys):
        self._tree(tmp_path)

        rc = main(
            [
                "duplicates",
                str(tmp_path),
                "--min-lines",
                "4",
                "--exclude",
                str(tmp_path / "sub"),
            ]
        )

        assert rc == 0
        assert "no duplicates found" in capsys.readouterr().out

    def test_min_occurrences_below_two_is_an_argparse_error(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["duplicates", str(tmp_path), "--min-occurrences", "1"])
