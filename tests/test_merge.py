"""Tests for the structure-aware 3-way merge (`sage_ini.merge`) and its `merge` CLI."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sage_ini.__main__ import main
from sage_ini.merge import merge_documents, resolve_markers
from sage_ini.parser.blockparser import parse

_REPO_ROOT = Path(__file__).resolve().parent.parent


def doc(text: str):
    return parse(text).document


def merge(base: str | None, ours: str, theirs: str, **kw):
    return merge_documents(doc(base) if base is not None else None, doc(ours), doc(theirs), **kw)


class TestStructuralMerge:
    def test_independent_objects_both_kept(self):
        base = "Object Shared\n    BuildCost = 1\nEnd\n"
        ours = base + "Object Ours\n    BuildCost = 2\nEnd\n"
        theirs = base + "Object Theirs\n    BuildCost = 3\nEnd\n"
        result = merge(base, ours, theirs)
        assert result.conflicts == 0
        names = {b.label for b in doc(result.text).children}
        assert names == {"Shared", "Ours", "Theirs"}

    def test_output_reparses_cleanly(self):
        base = "Object A\n    BuildCost = 1\nEnd\n"
        ours = "Object A\n    BuildCost = 2\nEnd\nObject B\nEnd\n"
        theirs = "Object A\n    BuildCost = 1\n    Armor = X\nEnd\n"
        result = merge(base, ours, theirs)
        # the merged text round-trips through the parser/printer
        assert parse(result.text).diagnostics.items == []

    def test_disjoint_fields_same_object_merge_silently(self):
        base = "Object Gondor\n    BuildCost = 100\n    Armor = Light\nEnd\n"
        ours = "Object Gondor\n    BuildCost = 150\n    Armor = Light\nEnd\n"
        theirs = "Object Gondor\n    BuildCost = 100\n    Armor = Heavy\nEnd\n"
        result = merge(base, ours, theirs)
        assert result.conflicts == 0
        gondor = doc(result.text).children[0]
        fields = {c.key: c.value for c in gondor.children}
        assert fields == {"BuildCost": "150", "Armor": "Heavy"}

    def test_same_field_both_sides_conflicts_narrowly(self):
        base = "Object A\n    BuildCost = 100\n    Armor = X\nEnd\n"
        ours = "Object A\n    BuildCost = 150\n    Armor = X\nEnd\n"
        theirs = "Object A\n    BuildCost = 200\n    Armor = X\nEnd\n"
        result = merge(base, ours, theirs)
        assert result.conflicts == 1
        # the conflict wraps only the BuildCost line; Armor stays clean outside markers
        assert "<<<<<<< ours" in result.text
        assert "    BuildCost = 150" in result.text
        assert "    BuildCost = 200" in result.text
        # Armor is unchanged, so it stays outside the markers (after the conflict block).
        assert "    Armor = X" in result.text.split(">>>>>>> theirs")[1]

    def test_delete_versus_modify_conflicts(self):
        base = "Object A\n    BuildCost = 1\nEnd\nObject B\nEnd\n"
        ours = "Object B\nEnd\n"  # A deleted, untouched before that
        theirs = "Object A\n    BuildCost = 99\nEnd\nObject B\nEnd\n"  # A modified
        result = merge(base, ours, theirs)
        assert result.conflicts == 1

    def test_delete_unchanged_drops_silently(self):
        base = "Object A\n    BuildCost = 1\nEnd\nObject B\nEnd\n"
        ours = "Object B\nEnd\n"  # A deleted
        theirs = base  # A untouched
        result = merge(base, ours, theirs)
        assert result.conflicts == 0
        assert "Object A" not in result.text

    def test_add_add_identical_keeps_one_copy(self):
        base = "Object Base\nEnd\n"
        added = "Object New\n    BuildCost = 5\nEnd\n"
        result = merge(base, base + added, base + added)
        assert result.conflicts == 0
        assert result.text.count("Object New") == 1

    def test_repeated_keys_fall_back_to_textual(self):
        # WeaponSpeed (ours) and a repeated Nuggets line (theirs) change disjointly.
        base = "Weapon W\n    WeaponSpeed = 1\n    Nuggets = A\n    Nuggets = B\nEnd\n"
        ours = "Weapon W\n    WeaponSpeed = 2\n    Nuggets = A\n    Nuggets = B\nEnd\n"
        theirs = "Weapon W\n    WeaponSpeed = 1\n    Nuggets = A\n    Nuggets = C\nEnd\n"
        result = merge(base, ours, theirs)
        assert result.conflicts == 0
        assert "WeaponSpeed = 2" in result.text
        assert "Nuggets = C" in result.text

    def test_repeated_keys_overlap_conflicts(self):
        base = "Weapon W\n    Nuggets = A\n    Nuggets = B\nEnd\n"
        ours = "Weapon W\n    Nuggets = X\n    Nuggets = B\nEnd\n"
        theirs = "Weapon W\n    Nuggets = Y\n    Nuggets = B\nEnd\n"
        result = merge(base, ours, theirs)
        assert result.conflicts == 1

    def test_marker_size_honoured(self):
        base = "Object A\n    BuildCost = 1\nEnd\n"
        ours = "Object A\n    BuildCost = 2\nEnd\n"
        theirs = "Object A\n    BuildCost = 3\nEnd\n"
        result = merge(base, ours, theirs, marker_size=8)
        assert "<<<<<<<< ours" in result.text
        assert "======== " not in result.text  # no trailing space on the divider
        assert "\n========\n" in result.text


class TestResolveMarkers:
    def test_independent_conflicts_collapse(self):
        # git flagged the whole region, but the two hunks touch different objects.
        marked = (
            "Object A\n"
            "<<<<<<< ours\n    BuildCost = 2\n||||||| base\n    BuildCost = 1\n"
            "=======\n    BuildCost = 1\n>>>>>>> theirs\nEnd\n"
            "Object B\n"
            "<<<<<<< ours\n    Armor = X\n||||||| base\n    Armor = X\n"
            "=======\n    Armor = Y\n>>>>>>> theirs\nEnd\n"
        )
        result = resolve_markers(marked)
        assert result.conflicts == 0
        assert "BuildCost = 2" in result.text and "Armor = Y" in result.text

    def test_overlapping_field_stays_conflicted(self):
        marked = (
            "Object A\n"
            "<<<<<<< ours\n    BuildCost = 2\n||||||| base\n    BuildCost = 1\n"
            "=======\n    BuildCost = 3\n>>>>>>> theirs\nEnd\n"
        )
        result = resolve_markers(marked)
        assert result.conflicts == 1

    def test_resolving_is_idempotent(self):
        marked = (
            "Object A\n"
            "<<<<<<< ours\n    BuildCost = 2\n||||||| base\n    BuildCost = 1\n"
            "=======\n    BuildCost = 3\n>>>>>>> theirs\nEnd\n"
        )
        once = resolve_markers(marked)
        twice = resolve_markers(once.text)
        assert twice.text == once.text


class TestMergeCommand:
    def _files(self, tmp_path, base, ours, theirs):
        (tmp_path / "base.ini").write_text(base, encoding="utf-8")
        (tmp_path / "ours.ini").write_text(ours, encoding="utf-8")
        (tmp_path / "theirs.ini").write_text(theirs, encoding="utf-8")
        return [str(tmp_path / f) for f in ("base.ini", "ours.ini", "theirs.ini")]

    def test_clean_merge_exit_zero_writes_ours(self, tmp_path):
        b, o, t = self._files(
            tmp_path,
            "Object A\n    BuildCost = 1\nEnd\n",
            "Object A\n    BuildCost = 2\nEnd\n",
            "Object A\n    BuildCost = 1\n    Armor = X\nEnd\n",
        )
        assert main(["merge", b, o, t]) == 0
        written = (tmp_path / "ours.ini").read_text(encoding="utf-8")
        assert "BuildCost = 2" in written and "Armor = X" in written

    def test_conflict_exits_one(self, tmp_path, capsys):
        b, o, t = self._files(
            tmp_path,
            "Object A\n    BuildCost = 1\nEnd\n",
            "Object A\n    BuildCost = 2\nEnd\n",
            "Object A\n    BuildCost = 3\nEnd\n",
        )
        out = tmp_path / "out.ini"
        assert main(["merge", b, o, t, "-o", str(out)]) == 1
        assert "<<<<<<<" in out.read_text(encoding="utf-8")
        assert "conflict(s) remain" in capsys.readouterr().out

    def test_merges_windows_1252_file_without_crashing(self, tmp_path):
        # SAGE data mixes encodings; 0xdb is 'Û' in windows-1252 but invalid utf-8. The driver
        # must read it via the fallback and not crash, and write the result back as 1252.
        base = "Object A\n    DisplayName = base\nEnd\n".encode("windows-1252")
        ours = "Object A\n    DisplayName = Ûnit\nEnd\n".encode("windows-1252")
        theirs = "Object A\n    DisplayName = base\n    Armor = X\nEnd\n".encode("windows-1252")
        (tmp_path / "base.ini").write_bytes(base)
        (tmp_path / "ours.ini").write_bytes(ours)
        (tmp_path / "theirs.ini").write_bytes(theirs)
        args = [str(tmp_path / f) for f in ("base.ini", "ours.ini", "theirs.ini")]
        assert main(["merge", *args]) == 0
        written = (tmp_path / "ours.ini").read_bytes().decode("windows-1252")
        assert "Ûnit" in written and "Armor = X" in written

    def test_missing_input_file_does_not_crash(self, tmp_path):
        # git's ort strategy creates/deletes the %O/%A/%B temps around each call; a vanished
        # input must be treated as empty, never crash the whole merge.
        (tmp_path / "ours.ini").write_text("Object A\n    BuildCost = 2\nEnd\n", encoding="utf-8")
        (tmp_path / "theirs.ini").write_text("Object A\n    BuildCost = 2\nEnd\n", encoding="utf-8")
        gone = str(tmp_path / "vanished_base.ini")  # never created
        args = [gone, str(tmp_path / "ours.ini"), str(tmp_path / "theirs.ini")]
        assert main(["merge", *args]) == 0
        assert "BuildCost = 2" in (tmp_path / "ours.ini").read_text(encoding="utf-8")

    def test_resolve_command(self, tmp_path):
        conflicted = tmp_path / "c.ini"
        conflicted.write_text(
            "Object A\n<<<<<<< ours\n    BuildCost = 2\n||||||| base\n    BuildCost = 1\n"
            "=======\n    BuildCost = 1\n>>>>>>> theirs\nEnd\n",
            encoding="utf-8",
        )
        assert main(["merge", "--resolve", str(conflicted)]) == 0
        assert "<<<<<<<" not in conflicted.read_text(encoding="utf-8")

    def test_missing_args_errors(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            main(["merge", str(tmp_path / "only.ini")])

    def test_install_registers_driver(self, tmp_path):
        # Run as a subprocess with cwd inside a throwaway repo so the local `git config`
        # write lands there, never in the real project repo.
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
        result = subprocess.run(
            [sys.executable, "-m", "sage_ini", "merge", "--install"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert "*.ini merge=sage-ini" in result.stdout
        driver = subprocess.run(
            ["git", "config", "merge.sage-ini.driver"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert "sage-ini merge" in driver.stdout
