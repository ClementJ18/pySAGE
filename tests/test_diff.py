"""Tests for the structure-aware game diff (`sage_ini.diff`) and its `diff` CLI."""

import subprocess

from sage_ini.__main__ import main
from sage_ini.diff import diff_games, format_game_diff
from sage_ini.loader import load_game


def _game(tmp_path, name, text):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "data.ini").write_text(text, encoding="utf-8")
    return load_game(folder).game


class TestDiffGames:
    def test_added_and_removed_definitions(self, tmp_path):
        old = _game(tmp_path, "old", "Object Keep\nEnd\nObject Gone\nEnd\n")
        new = _game(tmp_path, "new", "Object Keep\nEnd\nObject Fresh\nEnd\n")
        diff = diff_games(old, new)
        objects = next(t for t in diff.tables if t.key == "objects")
        assert objects.added == ["Fresh"]
        assert objects.removed == ["Gone"]

    def test_scalar_field_change(self, tmp_path):
        old = _game(tmp_path, "old", "Object Soldier\n    BuildCost = 100\nEnd\n")
        new = _game(tmp_path, "new", "Object Soldier\n    BuildCost = 150\nEnd\n")
        diff = diff_games(old, new)
        _, obj_diff = next(c for t in diff.tables for c in t.changed)
        change = next(f for f in obj_diff.fields if f.key == "BuildCost")
        assert (change.old, change.new) == ("100", "150")

    def test_added_and_removed_fields(self, tmp_path):
        old = _game(tmp_path, "old", "Object A\n    Armor = Light\nEnd\n")
        new = _game(tmp_path, "new", "Object A\n    DisplayName = Hi\nEnd\n")
        _, obj_diff = next(c for t in diff_games(old, new).tables for c in t.changed)
        keys = {(f.key, f.old, f.new) for f in obj_diff.fields}
        assert ("Armor", "Light", None) in keys
        assert ("DisplayName", None, "Hi") in keys

    def test_identical_games_have_no_changes(self, tmp_path):
        text = "Object A\n    BuildCost = 1\nEnd\nWeapon W\n    PrimaryDamage = 5\nEnd\n"
        old = _game(tmp_path, "old", text)
        new = _game(tmp_path, "new", text)
        assert diff_games(old, new).tables == []

    def test_nested_module_field_change(self, tmp_path):
        block = (
            "Object Knight\n"
            "    Body = ActiveBody ModuleTag_01\n"
            "        MaxHealth = {cost}\n"
            "    End\n"
            "End\n"
        )
        old = _game(tmp_path, "old", block.format(cost="300"))
        new = _game(tmp_path, "new", block.format(cost="350"))
        _, obj_diff = next(c for t in diff_games(old, new).tables for c in t.changed)
        assert not obj_diff.fields  # the change is inside the module, not the top level
        child = obj_diff.changed_children[0]
        assert child.label == "ActiveBody ModuleTag_01"
        assert (child.diff.fields[0].old, child.diff.fields[0].new) == ("300", "350")

    def test_repeated_key_change(self, tmp_path):
        old = _game(tmp_path, "old", "Weapon W\n    Nuggets = A\n    Nuggets = B\nEnd\n")
        new = _game(tmp_path, "new", "Weapon W\n    Nuggets = A\n    Nuggets = C\nEnd\n")
        _, obj_diff = next(c for t in diff_games(old, new).tables for c in t.changed)
        change = obj_diff.fields[0]
        assert change.old == "A, B" and change.new == "A, C"

    def test_macro_change(self, tmp_path):
        old = _game(tmp_path, "old", "#define COST 100\nObject A\nEnd\n")
        new = _game(tmp_path, "new", "#define COST 150\nObject A\nEnd\n")
        diff = diff_games(old, new)
        assert ("COST", "100", "150") in diff.macros.changed

    def test_strings_off_by_default(self, tmp_path):
        old = _game(tmp_path, "old", "Object A\nEnd\n")
        new = _game(tmp_path, "new", "Object A\nEnd\n")
        old.strings["LABEL"] = "before"
        new.strings["LABEL"] = "after"
        assert diff_games(old, new).strings is None
        assert ("LABEL", "before", "after") in diff_games(old, new, strings=True).strings.changed


class TestFormat:
    def test_changelog_mentions_changes(self, tmp_path):
        old = _game(tmp_path, "old", "Object Soldier\n    BuildCost = 100\nEnd\nObject Gone\nEnd\n")
        new = _game(tmp_path, "new", "Object Soldier\n    BuildCost = 150\nEnd\nObject New\nEnd\n")
        text = format_game_diff(diff_games(old, new), "v1", "v2")
        assert "# ini diff: v1 -> v2" in text
        assert "BuildCost: 100 -> 150" in text
        assert "+ New" in text
        assert "- Gone" in text

    def test_no_differences_message(self, tmp_path):
        old = _game(tmp_path, "old", "Object A\nEnd\n")
        new = _game(tmp_path, "new", "Object A\nEnd\n")
        assert "(no differences)" in format_game_diff(diff_games(old, new), "a", "b")


class TestDiffCommand:
    def _folder(self, tmp_path, name, text):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "data.ini").write_text(text, encoding="utf-8")
        return str(folder)

    def test_folder_diff_prints_changelog(self, tmp_path, capsys):
        old = self._folder(tmp_path, "old", "Object A\n    BuildCost = 1\nEnd\n")
        new = self._folder(tmp_path, "new", "Object A\n    BuildCost = 2\nEnd\n")
        assert main(["diff", old, new]) == 0
        assert "BuildCost: 1 -> 2" in capsys.readouterr().out

    def test_missing_folder_errors_cleanly(self, tmp_path, capsys):
        old = self._folder(tmp_path, "old", "Object A\nEnd\n")
        assert main(["diff", old, str(tmp_path / "nope")]) == 2
        assert "not a directory" in capsys.readouterr().out

    def test_diff_two_git_refs(self, tmp_path, capsys):
        repo = tmp_path / "repo"
        ini = repo / "ini"
        ini.mkdir(parents=True)

        def git(*args):
            subprocess.run(
                ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
            )

        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, text=True)
        git("config", "user.email", "t@t.t")
        git("config", "user.name", "t")
        data = ini / "data.ini"
        data.write_text("Object Soldier\n    BuildCost = 100\nEnd\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "v1")
        data.write_text("Object Soldier\n    BuildCost = 150\nEnd\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "v2")
        assert main(["diff", "HEAD~1", "HEAD", "--repo", str(repo), "--path", "ini"]) == 0
        assert "BuildCost: 100 -> 150" in capsys.readouterr().out
