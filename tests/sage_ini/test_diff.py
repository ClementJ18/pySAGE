"""Tests for the structure-aware game diff (`sage_ini.diff`), the player-facing rendering
(`sage_ini.player_diff`), and the `diff` CLI."""

import subprocess

from sage_ini.__main__ import main
from sage_ini.diff import diff_games, format_game_diff
from sage_ini.loader import load_game
from sage_ini.player_diff import format_player_diff


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


_PLAYER_STRINGS = {
    "FACTION:Lothlorien": "Lothlórien",
    "OBJECT:LothlorienArcher": "Lórien Archer",
    "APT:Ambush": "Ambush of the Wood-elves",
}

_FACTION = (
    "PlayerTemplate FactionLothlorien\n"
    "    PlayableSide = Yes\n"
    "    Side = Lothlorien\n"
    "    DisplayName = FACTION:Lothlorien\n"
    "End\n"
)


class TestPlayerDiff:
    def _render(self, tmp_path, old_text, new_text):
        old = _game(tmp_path, "old", old_text)
        new = _game(tmp_path, "new", new_text)
        old.strings.update(_PLAYER_STRINGS)
        new.strings.update(_PLAYER_STRINGS)
        return format_player_diff(diff_games(old, new), old, new, "v1", "v2")

    def _archer(self, cost, extra=""):
        return _FACTION + (
            "Object LothlorienArcher\n"
            "    Side = Lothlorien\n"
            "    DisplayName = OBJECT:LothlorienArcher\n"
            f"    BuildCost = {cost}\n"
            f"{extra}"
            "End\n"
        )

    def test_unit_change_uses_display_name_under_faction(self, tmp_path):
        text = self._render(tmp_path, self._archer(300), self._archer(350))
        assert "## Lothlórien" in text
        assert "- **Lórien Archer**: Cost 300 → 350 (+17%)" in text
        assert "LothlorienArcher" not in text  # code names stay out of the player section

    def test_power_referenced_by_string_name_and_linked_to_units(self, tmp_path):
        chain = (
            "CommandSet ArcherCS\n"
            "    1 = Command_Ambush\n"
            "End\n"
            "CommandButton Command_Ambush\n"
            "    Command = SPECIAL_POWER\n"
            "    SpecialPower = SpecialAbilityElvenAmbush\n"
            "    TextLabel = APT:Ambush\n"
            "End\n"
            "SpecialPower SpecialAbilityElvenAmbush\n"
            "    ReloadTime = {reload}\n"
            "End\n"
        )
        old_text = self._archer(300, "    CommandSet = ArcherCS\n") + chain.format(reload=60000)
        new_text = self._archer(300, "    CommandSet = ArcherCS\n") + chain.format(reload=90000)
        text = self._render(tmp_path, old_text, new_text)
        assert "## Lothlórien" in text
        assert (
            "- **Ambush of the Wood-elves** (used by Lórien Archer): "
            "Cooldown 60s → 90s (+50%)" in text
        )
        assert "SpecialAbilityElvenAmbush" not in text

    def test_weapon_change_linked_to_units(self, tmp_path):
        body = "Weapon ElfBow\n    PrimaryDamage = {damage}\nEnd\n"
        extra = "    WeaponSet\n        Weapon = PRIMARY ElfBow\n    End\n"
        text = self._render(
            tmp_path,
            self._archer(300, extra) + body.format(damage=30),
            self._archer(300, extra) + body.format(damage=40),
        )
        assert "- Weapon of Lórien Archer: Damage 30 → 40 (+33%)" in text
        assert "ElfBow" not in text

    def test_macro_change_surfaces_on_units_that_use_it(self, tmp_path):
        text = self._render(
            tmp_path,
            "#define ELF_COST 300\n" + self._archer("ELF_COST"),
            "#define ELF_COST 350\n" + self._archer("ELF_COST"),
        )
        assert "- **Lórien Archer**: Cost 300 → 350 (+17%)" in text

    def test_refactor_onto_equal_macro_is_not_a_player_change(self, tmp_path):
        text = self._render(
            tmp_path,
            self._archer(300),
            "#define ELF_COST 300\n" + self._archer("ELF_COST"),
        )
        assert "(no player-facing differences)" in text

    def test_armor_set_swap_shows_effective_moves(self, tmp_path):
        armors = (
            "Armor LightArmor\n    Armor = SLASH 50%\nEnd\n"
            "Armor HeavyArmor\n    Armor = SLASH 25%\nEnd\n"
        )
        old_extra = "    ArmorSet\n        Armor = LightArmor\n    End\n"
        new_extra = "    ArmorSet\n        Armor = HeavyArmor\n    End\n"
        text = self._render(
            tmp_path,
            self._archer(300, old_extra) + armors,
            self._archer(300, new_extra) + armors,
        )
        assert "- **Lórien Archer**: Armor vs SLASH 50% → 25%" in text
        assert "HeavyArmor" not in text  # armor-set names are internal

    def test_spellbook_power_attributed_to_faction(self, tmp_path):
        chain = (
            "Object LothlorienSpellBook\n"
            "    CommandSet = SpellBookCS\n"
            "End\n"
            "CommandSet SpellBookCS\n"
            "    1 = Command_Drums\n"
            "End\n"
            "CommandButton Command_Drums\n"
            "    Command = SPELL_BOOK\n"
            "    SpecialPower = SpellBookDrums\n"
            "    TextLabel = APT:Drums\n"
            "End\n"
            "SpecialPower SpellBookDrums\n"
            "    ReloadTime = {reload}\n"
            "End\n"
        )
        faction = _FACTION.replace("End\n", "    SpellBookMp = LothlorienSpellBook\nEnd\n")
        old = _game(tmp_path, "old", faction + chain.format(reload=240000))
        new = _game(tmp_path, "new", faction + chain.format(reload=300000))
        strings = {**_PLAYER_STRINGS, "APT:Drums": "Drums in the Deep"}
        old.strings.update(strings)
        new.strings.update(strings)
        text = format_player_diff(diff_games(old, new), old, new, "v1", "v2")
        assert "## Lothlórien" in text
        assert "- **Drums in the Deep**: Cooldown 240s → 300s (+25%)" in text

    def test_dangling_armor_reference_fix_lands_in_bugfixes(self, tmp_path):
        # MissingArmor is defined nowhere: the old reference was broken, so pointing it
        # at a real set is a repair, reported apart from the balance lists.
        real = "Armor RealArmor\n    Armor = SLASH 50%\nEnd\n"
        old_extra = "    ArmorSet\n        Armor = MissingArmor\n    End\n"
        new_extra = "    ArmorSet\n        Armor = RealArmor\n    End\n"
        text = self._render(
            tmp_path,
            self._archer(300, old_extra) + real,
            self._archer(300, new_extra) + real,
        )
        assert "## Bugfixes" in text
        assert (
            "- **Lórien Archer** (Lothlórien): "
            "broken armor reference fixed (armor now takes effect)" in text
        )
        assert "## Lothlórien" not in text  # the fix is the unit's only change

    def test_armor_set_rename_with_equal_values_is_silent(self, tmp_path):
        old_armor = "Armor OldName\n    Armor = SLASH 50%\nEnd\n"
        new_armor = "Armor NewName\n    Armor = SLASH 50%\nEnd\n"
        old_extra = "    ArmorSet\n        Armor = OldName\n    End\n"
        new_extra = "    ArmorSet\n        Armor = NewName\n    End\n"
        text = self._render(
            tmp_path,
            self._archer(300, old_extra) + old_armor,
            self._archer(300, new_extra) + new_armor,
        )
        assert "(no player-facing differences)" in text

    def test_added_unit_listed_as_new_content(self, tmp_path):
        text = self._render(tmp_path, _FACTION, self._archer(300))
        assert "## Lothlórien" in text
        assert "- New: Lórien Archer" in text

    def test_repeated_scalar_compares_by_last_value(self, tmp_path):
        # The engine keeps the last write of a repeated scalar, so dropping a shadowed
        # earlier value is not a player-visible change.
        old = self._archer(300).replace("BuildCost = 300", "BuildCost = 500\n    BuildCost = 300")
        text = self._render(tmp_path, old, self._archer(300))
        assert "(no player-facing differences)" in text

    def test_case_only_token_change_is_silent(self, tmp_path):
        body = (
            "Weapon ElfBow\n"
            "    DamageNugget\n"
            "        Damage = 10\n"
            "        DamageScalar = 150% NONE +{token}\n"
            "    End\n"
            "End\n"
        )
        extra = "    WeaponSet\n        Weapon = PRIMARY ElfBow\n    End\n"
        text = self._render(
            tmp_path,
            self._archer(300, extra) + body.format(token="Structure"),
            self._archer(300, extra) + body.format(token="STRUCTURE"),
        )
        assert "(no player-facing differences)" in text

    def test_display_names_drop_hotkey_markers_and_line_breaks(self, tmp_path):
        strings = {"OBJECT:WargLair": "Warg &Lair (&X)\\nA lair of wargs"}
        old = _game(tmp_path, "old", self._lair(400))
        new = _game(tmp_path, "new", self._lair(500))
        old.strings.update(strings)
        new.strings.update(strings)
        text = format_player_diff(diff_games(old, new), old, new, "v1", "v2")
        assert "- **Warg Lair**: Cost 400 → 500 (+25%)" in text

    def _lair(self, cost):
        return f"Object WargLair\n    DisplayName = OBJECT:WargLair\n    BuildCost = {cost}\nEnd\n"


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
