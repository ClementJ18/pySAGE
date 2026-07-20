"""Unit tests for the `sage_lint manifest` command and the `.sagelint`/`lint` consumption side
of `sage_ini.manifest`: the CLI happy path, and - the important guarantee - that linting a mod
against a real base tree and against that base's generated manifest report *exactly* the same
diagnostics.
"""

from pathlib import Path

import pytest

from sage_ini.loader import load_game
from sage_ini.manifest import build_manifest, read_manifest, write_manifest
from sage_lint.cli import main
from sage_lint.linter import lint_folder


def _write(folder: Path, name: str, text: str) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _base_tree(root: Path) -> None:
    """A small base game exercising one audit item each: a parent `Object` two rules read
    (module tags, weapon refs), a weapon on its own file (later shadowed by the mod), an
    `ExperienceLevel` targeting the mod's hero by name, a REVIVE `CommandButton`, and a string
    label."""
    _write(
        root,
        "objects.ini",
        "Object BaseInfantry\n"
        "    BuildCost = 100\n"
        "    WeaponSet\n"
        "        Weapon = PRIMARY BaseSword\n"
        "        Weapon = SECONDARY SharedWeapon\n"
        "    End\n"
        "    Behavior = ActiveBody ModuleTag_Body\n"
        "    End\n"
        "End\n",
    )
    _write(root, "weapons_primary.ini", "Weapon BaseSword\n    PrimaryDamage = 10\nEnd\n")
    # Shadowed by the mod's own weapons.ini (same relative path) - BaseInfantry's reference to
    # SharedWeapon can then only be satisfied by the mod's shadowing definition.
    _write(root, "weapons.ini", "Weapon SharedWeapon\n    PrimaryDamage = 1\nEnd\n")
    _write(
        root,
        "levels.ini",
        "ExperienceLevel BaseVeteran\n"
        "    TargetNames = ModHero\n"
        "    RequiredExperience = 100\n"
        "    Rank = 1\n"
        "End\n",
    )
    _write(root, "buttons.ini", "CommandButton Command_Revive\n    Command = REVIVE\nEnd\n")
    # Populates the objectcreationlists table so DanglingReferenceRule treats the kind as
    # modelled (an empty table is skipped wholesale) - see the mod's RiderOCL below.
    _write(root, "ocl.ini", "ObjectCreationList BaseOCL\nEnd\n")
    _write(root, "strings.str", 'CONTROLBAR:BaseLabel\n"hi"\nEND\n')


def _mod_tree(root: Path) -> None:
    """A mod exercising the matching rule against each base fixture: a weapon reference that
    resolves into base alongside one that does not (a conversion-error), a dangling reference
    into base's (populated but not matching) OCL table, an invalid RemoveModule against the base
    parent's tags, a RespawnEntry level the base ExperienceLevel does not grant, the base REVIVE
    button wired into two slots, a button using the base string label, and a weapons.ini
    shadowing base's."""
    _write(
        root,
        "hero.ini",
        "ChildObject ModHero BaseInfantry\n"
        "    RemoveModule = ModuleTag_Ghost\n"
        "    WeaponSet\n"
        "        Weapon = PRIMARY BaseSword\n"
        "        Weapon = SECONDARY NoSuchWeapon\n"
        "    End\n"
        "    Behavior = RespawnUpdate ModuleTag_Respawn\n"
        "        RespawnEntry = Level:5 Cost:100 Time:10\n"
        "    End\n"
        "    Behavior = DetachableRiderUpdate ModuleTag_Rider\n"
        "        DeathEntry = AnimState:DEATH_2 AnimTime:3000 RiderOCL:NoSuchOCL\n"
        "    End\n"
        "End\n"
        "CommandSet ModCommandSet\n"
        "    1 = Command_Revive\n"
        "    2 = Command_Revive\n"
        "    3 = ModHeroButton\n"
        "End\n"
        "CommandButton ModHeroButton\n"
        "    Command = UNIT_BUILD\n"
        "    TextLabel = CONTROLBAR:BaseLabel\n"
        "End\n",
    )
    _write(root, "weapons.ini", "Weapon SharedWeapon\n    PrimaryDamage = 99\nEnd\n")


class TestManifestCommandCli:
    def test_happy_path_writes_a_valid_manifest(self, tmp_path):
        base = tmp_path / "base"
        _base_tree(base)
        out = tmp_path / "out.json"

        assert main(["manifest", "--game", str(base), "-o", str(out)]) == 0

        data = read_manifest(out)  # raises ManifestError if the file is not a valid manifest
        assert data["format"] == 1
        assert "objects.ini" in data["files"]

    def test_quiet_prints_only_the_output_path(self, tmp_path, capsys):
        base = tmp_path / "base"
        _base_tree(base)
        out = tmp_path / "out.json"

        assert main(["manifest", "--game", str(base), "-o", str(out), "-q"]) == 0
        assert capsys.readouterr().out.strip() == str(out)

    def test_missing_game_is_an_argparse_error(self):
        with pytest.raises(SystemExit):
            main(["manifest"])


class TestRuleParity:
    """A mod linted against a real base tree, and against that tree's generated manifest, must
    report identical diagnostics - the whole point of a manifest being a lint-only stand-in."""

    @pytest.fixture
    def trees(self, tmp_path):
        base = tmp_path / "base"
        mod = tmp_path / "mod"
        _base_tree(base)
        _mod_tree(mod)
        manifest_path = tmp_path / "base-manifest.json"
        write_manifest(build_manifest(load_game(base), [base]), manifest_path)
        return base, mod, manifest_path

    @staticmethod
    def _keys(diagnostics, mod: Path):
        mod = mod.resolve()
        return sorted(
            (d.code, Path(d.span.file).resolve().relative_to(mod).as_posix(), d.span.line_start)
            for d in diagnostics.items
        )

    def test_diagnostics_are_identical_via_base_or_manifest(self, trees):
        base, mod, manifest_path = trees

        from_base = lint_folder(mod, bases=(("folder", str(base)),))
        from_manifest = lint_folder(mod, manifest=manifest_path)

        assert self._keys(from_base, mod) == self._keys(from_manifest, mod)

        # Sanity check the fixture actually exercises the rules being compared - an empty
        # intersection would make the equality above vacuous.
        codes = {d.code for d in from_base.items}
        assert codes >= {
            "dangling-reference",
            "conversion-error",
            "duplicate-revive-button",
            "invalid-module-operation",
            "respawn-unknown-level",
        }
        # The shadowed weapon is saved from unused-definition purely by the base object's
        # precomputed forward edge resolving, post-shadow, to the mod's own definition.
        assert not any(
            d.code == "unused-definition" and d.extra.get("name") == "SharedWeapon"
            for d in from_base.items
        )
        assert not any(
            d.code == "unused-definition" and d.extra.get("name") == "SharedWeapon"
            for d in from_manifest.items
        )
        # The base string label resolves for the mod's own button (no unknown-string-label).
        assert not any(d.code == "unknown-string-label" for d in from_base.items)
        assert not any(d.code == "unknown-string-label" for d in from_manifest.items)


class TestDataIniLayoutShadowing:
    """Manifest entries are keyed `ini_root`-relative, so a mod keeping the full `data/ini`
    layout must shadow them by the same identity - a root-relative shadow key
    (`data/ini/weapons.ini` vs the manifest's `weapons.ini`) would never collide, and a
    definition the mod's shadowing file *removes* would silently stay resolvable."""

    def test_shadowing_file_removes_base_definitions_across_layouts(self, tmp_path):
        base = tmp_path / "base"  # bare ini root
        _write(
            base,
            "weapons.ini",
            "Weapon SharedWeapon\n    PrimaryDamage = 1\nEnd\n"
            "Weapon GhostWeapon\n    PrimaryDamage = 1\nEnd\n",
        )
        mod = tmp_path / "mod"  # full game layout: ini under data/ini
        _write(mod, "data/ini/weapons.ini", "Weapon SharedWeapon\n    PrimaryDamage = 9\nEnd\n")
        _write(
            mod,
            "data/ini/hero.ini",
            "Object ModHero\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY SharedWeapon\n"
            "        Weapon = SECONDARY GhostWeapon\n"
            "    End\n"
            "End\n",
        )
        manifest_path = tmp_path / "base-manifest.json"
        write_manifest(build_manifest(load_game(base), [base]), manifest_path)

        from_base = lint_folder(mod, bases=(("folder", str(base)),))
        from_manifest = lint_folder(mod, manifest=manifest_path)

        assert TestRuleParity._keys(from_base, mod) == TestRuleParity._keys(from_manifest, mod)
        # GhostWeapon died with the shadowed base file, so referencing it must fail in both runs
        # - if the manifest's stand-in survived, the manifest run would resolve it silently.
        assert any(d.code == "conversion-error" for d in from_manifest.items)


class TestSagelintBaseManifest:
    def test_base_manifest_config_resolves_base_references(self, tmp_path, capsys):
        base = tmp_path / "base"
        mod = tmp_path / "mod"
        _base_tree(base)
        _mod_tree(mod)
        manifest_path = tmp_path / "base-manifest.json"
        write_manifest(build_manifest(load_game(base), [base]), manifest_path)

        (mod / ".sagelint").write_text(
            f'root = "."\nbase_manifest = "{manifest_path.as_posix()}"\n', encoding="utf-8"
        )

        assert main(["lint", str(mod), "--select", "dangling-reference"]) == 1
        out = capsys.readouterr().out
        # NoSuchOCL still dangles (base's OCL table is populated but doesn't name it); BaseSword
        # (a real base weapon reference) resolves cleanly and never appears in the report.
        assert "NoSuchOCL" in out
        assert "BaseSword" not in out

    def test_real_base_wins_over_base_manifest_with_no_crash(self, tmp_path, capsys):
        base = tmp_path / "base"
        mod = tmp_path / "mod"
        _base_tree(base)
        _mod_tree(mod)
        manifest_path = tmp_path / "base-manifest.json"
        write_manifest(build_manifest(load_game(base), [base]), manifest_path)

        (mod / ".sagelint").write_text(
            f'root = "."\n'
            f'base = "{base.as_posix()}"\n'
            f'base_manifest = "{manifest_path.as_posix()}"\n',
            encoding="utf-8",
        )

        # Both a real base and a manifest configured: the real base wins, and nothing double-
        # loads or crashes.
        assert main(["lint", str(mod), "--select", "dangling-reference"]) == 1
        assert "NoSuchOCL" in capsys.readouterr().out

    def test_bad_base_manifest_is_a_clean_cli_error(self, tmp_path, capsys):
        mod = tmp_path / "mod"
        mod.mkdir()
        (mod / "a.ini").write_text("Object Fine\n    BuildCost = 1\nEnd\n", encoding="utf-8")

        rc = main(["lint", str(mod), "--base-manifest", str(tmp_path / "missing.json")])

        assert rc == 2
        assert "sage_lint:" in capsys.readouterr().err
