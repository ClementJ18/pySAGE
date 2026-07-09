"""Tests for the per-project .sagelint config and its precedence in the lint CLI."""

import json

import pytest

from sage_lint.cli import main
from sage_lint.config import init_project, load_config

# A file with a repeated field (warning), a miscased enum (warning) and an unknown
# attribute (info) - one of every reportable severity, reused across the CLI tests.
_MIXED = (
    "Object Foo\n"
    "    BuildCost = 1\n"
    "    BuildCost = 2\n"
    "    EditorSorting = System\n"
    "    MadeUpThing = 1\n"
    "End\n"
)


class TestLoadConfig:
    def test_missing_files_give_an_empty_config(self, tmp_path):
        config = load_config(tmp_path)

        assert config.level is None
        assert config.ignore == []
        assert config.warnings == []

    def test_reads_shared_keys(self, tmp_path):
        (tmp_path / ".sagelint").write_text(
            'level = "INFO"\nignore = ["enum-case", "repeated-field"]\n', encoding="utf-8"
        )
        config = load_config(tmp_path)

        assert config.level == "INFO"
        assert config.ignore == ["enum-case", "repeated-field"]

    def test_a_bare_string_is_accepted_as_a_one_item_list(self, tmp_path):
        (tmp_path / ".sagelint").write_text('ignore = "enum-case"\n', encoding="utf-8")

        assert load_config(tmp_path).ignore == ["enum-case"]

    def test_reads_the_assets_bool_key(self, tmp_path):
        assert load_config(tmp_path).assets is False  # default off
        (tmp_path / ".sagelint").write_text("assets = true\n", encoding="utf-8")
        assert load_config(tmp_path).assets is True

    def test_invalid_assets_warns_and_is_ignored(self, tmp_path):
        (tmp_path / ".sagelint").write_text('assets = "yes"\n', encoding="utf-8")
        config = load_config(tmp_path)
        assert config.assets is False
        assert any("assets" in w for w in config.warnings)

    def test_reads_the_assets_base_list_key(self, tmp_path):
        assert load_config(tmp_path).assets_base == []  # default empty
        (tmp_path / ".sagelint").write_text(
            'assets_base = ["textures2.big", "textures3.big"]\n', encoding="utf-8"
        )
        assert load_config(tmp_path).assets_base == ["textures2.big", "textures3.big"]

    def test_maps_defaults_off_and_can_be_enabled(self, tmp_path):
        assert load_config(tmp_path).maps is False  # default: maps not linted
        (tmp_path / ".sagelint").write_text("maps = true\n", encoding="utf-8")
        assert load_config(tmp_path).maps is True

    def test_reads_the_maps_base_list_key(self, tmp_path):
        assert load_config(tmp_path).maps_base == []
        (tmp_path / ".sagelint").write_text('maps_base = ["bfme2/ini"]\n', encoding="utf-8")
        assert load_config(tmp_path).maps_base == ["bfme2/ini"]

    def test_reads_the_sentinels_list_key(self, tmp_path):
        assert load_config(tmp_path).sentinels == []  # default empty
        (tmp_path / ".sagelint").write_text(
            'sentinels = ["NoSound", "NoWeapon"]\n', encoding="utf-8"
        )
        assert load_config(tmp_path).sentinels == ["NoSound", "NoWeapon"]

    def test_reads_the_always_referenced_list_key(self, tmp_path):
        assert load_config(tmp_path).always_referenced == []
        (tmp_path / ".sagelint").write_text(
            'always_referenced = ["PlayerAIType"]\n', encoding="utf-8"
        )
        assert load_config(tmp_path).always_referenced == ["PlayerAIType"]

    def test_local_overrides_shared_per_key(self, tmp_path):
        (tmp_path / ".sagelint").write_text(
            'level = "WARNING"\nignore = ["enum-case"]\n', encoding="utf-8"
        )
        (tmp_path / ".sagelint.local").write_text('level = "INFO"\n', encoding="utf-8")
        config = load_config(tmp_path)

        assert config.level == "INFO"  # local wins
        assert config.ignore == ["enum-case"]  # untouched by local

    def test_unknown_key_warns_but_does_not_fail(self, tmp_path):
        (tmp_path / ".sagelint").write_text('levle = "INFO"\n', encoding="utf-8")
        config = load_config(tmp_path)

        assert config.level is None
        assert any("unknown key 'levle'" in w for w in config.warnings)

    def test_invalid_level_warns_and_is_ignored(self, tmp_path):
        (tmp_path / ".sagelint").write_text('level = "LOUD"\n', encoding="utf-8")
        config = load_config(tmp_path)

        assert config.level is None
        assert any("invalid level" in w for w in config.warnings)

    def test_malformed_toml_warns(self, tmp_path):
        (tmp_path / ".sagelint").write_text("level = \n", encoding="utf-8")
        config = load_config(tmp_path)

        assert any(".sagelint" in w for w in config.warnings)

    def test_reads_the_root_key(self, tmp_path):
        (tmp_path / ".sagelint").write_text('root = "gamedata"\n', encoding="utf-8")

        assert load_config(tmp_path).root == "gamedata"

    def test_invalid_root_warns_and_is_ignored(self, tmp_path):
        # `root` is a single path, not a list - a non-string value is rejected.
        (tmp_path / ".sagelint").write_text("root = 5\n", encoding="utf-8")
        config = load_config(tmp_path)

        assert config.root is None
        assert any("'root'" in w for w in config.warnings)

    def test_reads_the_baseline_key(self, tmp_path):
        (tmp_path / ".sagelint").write_text('baseline = "errors.baseline"\n', encoding="utf-8")

        assert load_config(tmp_path).baseline == "errors.baseline"

    def test_invalid_baseline_warns_and_is_ignored(self, tmp_path):
        (tmp_path / ".sagelint").write_text("baseline = 5\n", encoding="utf-8")
        config = load_config(tmp_path)

        assert config.baseline is None
        assert any("'baseline'" in w for w in config.warnings)

    def test_suggest_defaults_off(self, tmp_path):
        assert load_config(tmp_path).suggest is False

    def test_reads_the_suggest_key(self, tmp_path):
        (tmp_path / ".sagelint").write_text("suggest = true\n", encoding="utf-8")

        assert load_config(tmp_path).suggest is True

    def test_invalid_suggest_warns_and_is_ignored(self, tmp_path):
        # `suggest` is a bool; a string is rejected so a typo cannot silently enable it.
        (tmp_path / ".sagelint").write_text('suggest = "yes"\n', encoding="utf-8")
        config = load_config(tmp_path)

        assert config.suggest is False
        assert any("'suggest'" in w for w in config.warnings)

    def test_format_keys_default_off(self, tmp_path):
        config = load_config(tmp_path)
        assert config.align_equals is False
        assert config.align_exclude == []

    def test_reads_the_format_keys(self, tmp_path):
        (tmp_path / ".sagelint").write_text(
            'align_equals = true\nalign_exclude = ["Object", "ArmorSet"]\n', encoding="utf-8"
        )
        config = load_config(tmp_path)

        assert config.align_equals is True
        assert config.align_exclude == ["Object", "ArmorSet"]

    def test_invalid_align_equals_warns_and_is_ignored(self, tmp_path):
        (tmp_path / ".sagelint").write_text('align_equals = "yes"\n', encoding="utf-8")
        config = load_config(tmp_path)

        assert config.align_equals is False
        assert any("'align_equals'" in w for w in config.warnings)


class TestInitProject:
    def test_scaffolds_both_config_files(self, tmp_path):
        (tmp_path / "a.ini").write_text("Object Foo\nEnd\n", encoding="utf-8")
        result = init_project(tmp_path)

        assert {p.name for p in result.written} == {".sagelint", ".sagelint.local"}
        assert result.ini_count == 1
        # the written config is valid TOML and names this folder as the lint root
        assert load_config(tmp_path).root == "."
        assert load_config(tmp_path).warnings == []

    def test_detects_a_string_table(self, tmp_path):
        (tmp_path / "strings.str").write_text('NS:Key\n"V"\nEND\n', encoding="utf-8")
        assert init_project(tmp_path).string_files

    def test_reports_no_string_table_when_absent(self, tmp_path):
        (tmp_path / "a.ini").write_text("Object Foo\nEnd\n", encoding="utf-8")
        assert init_project(tmp_path).string_files == []

    def test_does_not_overwrite_without_force(self, tmp_path):
        (tmp_path / ".sagelint").write_text('root = "sub"\n', encoding="utf-8")
        result = init_project(tmp_path)

        assert (tmp_path / ".sagelint") in result.skipped
        assert load_config(tmp_path).root == "sub"  # left untouched

    def test_force_overwrites_an_existing_config(self, tmp_path):
        (tmp_path / ".sagelint").write_text('root = "sub"\n', encoding="utf-8")
        init_project(tmp_path, force=True)

        assert load_config(tmp_path).root == "."


class TestInitCli:
    def test_init_writes_config_and_reports(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\nEnd\n", encoding="utf-8")

        assert main(["init", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "wrote" in out
        assert "1 ini file(s) found" in out
        assert (tmp_path / ".sagelint").exists()

    def test_init_flags_a_missing_string_table(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\nEnd\n", encoding="utf-8")

        main(["init", str(tmp_path)])
        assert "no string table" in capsys.readouterr().out

    def test_init_keeps_an_existing_config_without_force(self, tmp_path, capsys):
        (tmp_path / ".sagelint").write_text('root = "sub"\n', encoding="utf-8")

        assert main(["init", str(tmp_path)]) == 0
        assert "kept existing" in capsys.readouterr().out
        assert load_config(tmp_path).root == "sub"

    def test_init_rejects_a_missing_directory(self, tmp_path, capsys):
        assert main(["init", str(tmp_path / "nope")]) == 2
        assert "not a directory" in capsys.readouterr().err


class TestConfigInLintCli:
    def test_config_ignore_silences_a_code(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        (tmp_path / ".sagelint").write_text('ignore = ["repeated-field"]\n', encoding="utf-8")

        assert main(["lint", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "repeated-field" not in out
        assert "0 error(s), 0 warning(s)" in out

    def test_cli_flag_overrides_config_ignore(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(_MIXED, encoding="utf-8")
        (tmp_path / ".sagelint").write_text('ignore = ["repeated-field"]\n', encoding="utf-8")

        # the flag replaces the config's ignore list, so repeated-field is reported again
        # while the flag's own code (enum-case) is the one silenced
        assert main(["lint", str(tmp_path), "--ignore", "enum-case"]) == 1
        out = capsys.readouterr().out
        assert "repeated-field" in out
        assert "enum-case" not in out

    def test_suggest_is_off_by_default(self, tmp_path, capsys):
        # A near-miss attribute is flagged, but no "Did you mean" hint without opting in.
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCst = 1\nEnd\n", encoding="utf-8")

        main(["lint", str(tmp_path)])
        out = capsys.readouterr().out
        assert "unknown-attribute" in out
        assert "Did you mean" not in out

    def test_suggest_flag_adds_a_hint(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCst = 1\nEnd\n", encoding="utf-8")

        main(["lint", str(tmp_path), "--suggest"])
        assert "Did you mean 'BuildCost'?" in capsys.readouterr().out

    def test_config_suggest_key_adds_a_hint(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCst = 1\nEnd\n", encoding="utf-8")
        (tmp_path / ".sagelint").write_text("suggest = true\n", encoding="utf-8")

        main(["lint", str(tmp_path)])
        assert "Did you mean 'BuildCost'?" in capsys.readouterr().out

    def test_config_level_shows_info(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\n    MadeUpThing = 1\nEnd\n", encoding="utf-8")
        (tmp_path / ".sagelint").write_text('level = "INFO"\n', encoding="utf-8")

        assert main(["lint", str(tmp_path)]) == 1
        assert "unknown-attribute" in capsys.readouterr().out

    def test_no_config_bypasses_the_file(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        (tmp_path / ".sagelint").write_text('ignore = ["repeated-field"]\n', encoding="utf-8")

        # --no-config makes the linter forget the ignore, so the warning returns
        assert main(["lint", str(tmp_path), "--no-config"]) == 1
        assert "repeated-field" in capsys.readouterr().out

    def test_local_base_resolves_a_cross_reference(self, tmp_path, capsys):
        mod = tmp_path / "mod"
        base = tmp_path / "base"
        mod.mkdir()
        base.mkdir()
        (mod / "hero.ini").write_text(
            "Object Hero\n    WeaponSet\n        Weapon = PRIMARY Sword\n    End\nEnd\n",
            encoding="utf-8",
        )
        (base / "weapons.ini").write_text(
            "Weapon Sword\n    PrimaryDamage = 5\nEnd\n", encoding="utf-8"
        )
        # a TOML literal string ('...') avoids escaping the backslashes in a Windows path
        (mod / ".sagelint.local").write_text(f"base = ['{base}']\n", encoding="utf-8")

        assert main(["lint", str(mod)]) == 0
        assert "0 error(s)" in capsys.readouterr().out

    def test_config_root_picks_the_folder_to_lint(self, tmp_path, capsys, monkeypatch):
        # No positional root: the `.sagelint` in the working directory names the folder,
        # resolved relative to that config's own location.
        data = tmp_path / "gamedata"
        data.mkdir()
        (data / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        (tmp_path / ".sagelint").write_text('root = "gamedata"\n', encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        assert main(["lint"]) == 1
        assert "repeated-field" in capsys.readouterr().out

    def test_config_root_refines_a_positional_project_root(self, tmp_path, capsys):
        # The positional arg locates the project (where `.sagelint` is read); the config's
        # `root` then redirects the build to a subfolder, resolved against that location.
        data = tmp_path / "gamedata"
        data.mkdir()
        (data / "a.ini").write_text(
            "Object Foo\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        # A sibling file outside the subfolder must NOT be linted once `root` scopes in.
        (tmp_path / "stray.ini").write_text(
            "Object Bar\n    ArmorSet\n        Armor = MissingArmor\n    End\nEnd\n",
            encoding="utf-8",
        )
        (tmp_path / ".sagelint").write_text('root = "gamedata"\n', encoding="utf-8")

        assert main(["lint", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "repeated-field" in out  # from gamedata/a.ini
        assert "MissingArmor" not in out  # stray.ini is outside the scoped root

    def test_config_exclude_resolves_against_the_lint_root(self, tmp_path, capsys):
        # `exclude = ["wip"]` in the config must resolve to <lint-root>/wip, not the process
        # working directory, so the excluded folder's diagnostics are dropped.
        (tmp_path / "shipped.ini").write_text("Object Foo\nEnd\n", encoding="utf-8")
        wip = tmp_path / "wip"
        wip.mkdir()
        (wip / "draft.ini").write_text(
            "Object Draft\n    BuildCost = 1\n    BuildCost = 2\nEnd\n", encoding="utf-8"
        )
        (tmp_path / ".sagelint").write_text('exclude = ["wip"]\n', encoding="utf-8")

        assert main(["lint", str(tmp_path)]) == 0
        assert "repeated-field" not in capsys.readouterr().out

    def test_no_config_ignores_config_root(self, tmp_path, monkeypatch):
        # Without a root from the CLI or config, the folder lint has nothing to build.
        (tmp_path / ".sagelint").write_text('root = "gamedata"\n', encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit):
            main(["lint", "--no-config"])

    def test_config_warning_goes_to_stderr_not_json(self, tmp_path, capsys):
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCost = 1\nEnd\n", encoding="utf-8")
        (tmp_path / ".sagelint").write_text('bogus = "x"\n', encoding="utf-8")

        main(["lint", str(tmp_path), "--output-format", "json"])
        captured = capsys.readouterr()
        json.loads(captured.out)  # stdout stays valid JSON
        assert "unknown key 'bogus'" in captured.err
