"""Unit tests for the rename engine, its CLI command, and the binary-map warning.

Every test builds a small game on disk: a rename is a set of edits to real files, so a plan
computed against an in-memory game would not exercise the part most likely to be wrong.
"""

import argparse
import json
from pathlib import Path

from sage_ini.loader import load_game
from sage_ini.parser.io import iter_ini_files
from sage_lint.cli import main
from sage_lint.commands.rename import build_plan
from sage_lint.config import Config
from sage_lint.rename import (
    Anchor,
    RenamePlan,
    apply_plan,
    check_conflicts,
    collect_sites,
    dedupe_sites,
    keywords_for_table,
    scan_text,
    valid_name,
)
from sage_map import Map, write_map_to_path
from sage_map.assets.object_list import Object as MapObject
from sage_map.assets.object_list import ObjectsList


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _rename(root: Path, table: str, old: str, new: str) -> tuple[RenamePlan, dict[str, int]]:
    """Plan and apply a rename over the game under `root`, as `(plan, changed)`."""
    game = load_game(root).game
    plan = RenamePlan(table, old, new, collect_sites(game, table, old))
    return plan, apply_plan(plan)


class TestCollectSites:
    def test_finds_declaration_reference_and_macro_body(self, tmp_path):
        _write(
            tmp_path,
            "data/ini/w.ini",
            "#define MY_WEAPON OldSword\n"
            "\n"
            "Weapon OldSword\n"
            "    AttackRange = 10.0\n"
            "End\n"
            "\n"
            "Object Hero\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY OldSword\n"
            "    End\n"
            "End\n",
        )
        game = load_game(tmp_path).game

        sites = collect_sites(game, "weapons", "OldSword")

        anchors = {(site.line, site.anchor) for site in sites}
        assert (3, Anchor.HEADER_NAME) in anchors  # the declaration
        assert (9, Anchor.VALUE) in anchors  # the reference
        assert (1, Anchor.MACRO_BODY) in anchors  # the `#define` a field reaches it through

    def test_reference_through_a_macro_is_planned_at_the_define_only(self, tmp_path):
        # The use site holds the macro name, not the symbol, so rewriting it would be wrong.
        _write(
            tmp_path,
            "data/ini/w.ini",
            "#define MY_WEAPON OldSword\n"
            "Weapon OldSword\n"
            "    AttackRange = 1.0\n"
            "End\n"
            "Object Hero\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY MY_WEAPON\n"
            "    End\n"
            "End\n",
        )
        game = load_game(tmp_path).game

        lines = {site.line for site in collect_sites(game, "weapons", "OldSword")}

        assert lines == {1, 2}

    def test_matches_case_insensitively(self, tmp_path):
        # The engine resolves names case-insensitively, so any spelling is the same symbol.
        _write(
            tmp_path,
            "data/ini/w.ini",
            "Weapon OldSword\n    AttackRange = 1.0\nEnd\n"
            "Object Hero\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY oldsword\n"
            "    End\n"
            "End\n",
        )
        game = load_game(tmp_path).game

        assert any(site.line == 6 for site in collect_sites(game, "weapons", "OldSword"))

    def test_finds_a_commandset_numbered_slot(self, tmp_path):
        # A command set's buttons are digit-keyed, so no typed field carries them.
        _write(
            tmp_path,
            "data/ini/c.ini",
            "CommandButton Command_Attack\n    Command = ATTACK\nEnd\n"
            "CommandSet HeroSet\n"
            "    1 = Command_Attack\n"
            "End\n",
        )
        game = load_game(tmp_path).game

        sites = collect_sites(game, "commandbuttons", "Command_Attack")

        assert (5, Anchor.VALUE) in {(site.line, site.anchor) for site in sites}

    def test_finds_a_childobject_parent(self, tmp_path):
        _write(
            tmp_path,
            "data/ini/o.ini",
            "Object Hero\n    BuildCost = 1\nEnd\n"
            "ChildObject HeroChild Hero\n    BuildCost = 2\nEnd\n",
        )
        game = load_game(tmp_path).game

        sites = collect_sites(game, "objects", "Hero")

        assert (4, Anchor.HEADER_PARENT) in {(site.line, site.anchor) for site in sites}

    def test_a_dangling_reference_is_still_a_site(self, tmp_path):
        # A name that resolves to nothing today is still the name the modder meant, so a
        # pass-through `Reference` field is planned whether or not it resolves.
        _write(tmp_path, "data/ini/w.ini", "Weapon W\n    FireFX = FX_Missing\nEnd\n")
        game = load_game(tmp_path).game

        assert [site.line for site in collect_sites(game, "fxlists", "FX_Missing")] == [2]

    def test_a_dangling_strict_reference_falls_through_to_the_text_scan(self, tmp_path):
        # Some converters are typed as the definition class itself and raise on an unknown
        # name rather than passing it through, so the typed pass cannot see the name at all.
        # The safety-net scan is what keeps that from becoming a silent half-rename.
        path = _write(
            tmp_path,
            "data/ini/o.ini",
            "Object Hero\n    WeaponSet\n        Weapon = PRIMARY Ghost\n    End\nEnd\n",
        )
        game = load_game(tmp_path).game
        sites = collect_sites(game, "weapons", "Ghost")

        _promoted, unaccounted = scan_text(iter_ini_files(tmp_path), "weapons", "Ghost", sites)

        assert sites == []
        assert [(hit.file, hit.line) for hit in unaccounted] == [(str(path), 3)]


class TestApplyPlan:
    def test_rewrites_declaration_reference_and_macro(self, tmp_path):
        path = _write(
            tmp_path,
            "data/ini/w.ini",
            "#define MY_WEAPON OldSword\n"
            "Weapon OldSword\n"
            "    AttackRange = 10.0\n"
            "End\n"
            "Object Hero\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY OldSword\n"
            "    End\n"
            "End\n",
        )

        _plan, changed = _rename(tmp_path, "weapons", "OldSword", "NewSword")

        assert changed == {str(path): 3}
        text = path.read_text(encoding="utf-8")
        assert "#define MY_WEAPON NewSword" in text
        assert "Weapon NewSword" in text
        assert "Weapon = PRIMARY NewSword" in text
        assert "OldSword" not in text

    def test_leaves_a_longer_name_that_merely_contains_the_old_one(self, tmp_path):
        path = _write(
            tmp_path,
            "data/ini/o.ini",
            "Object Hero\n    BuildCost = 1\nEnd\n"
            "ChildObject HeroChild Hero\n    BuildCost = 2\nEnd\n",
        )

        _rename(tmp_path, "objects", "Hero", "Champion")

        text = path.read_text(encoding="utf-8")
        assert "Object Champion" in text
        assert "ChildObject HeroChild Champion" in text  # the child's own name is untouched

    def test_does_not_rewrite_a_comment(self, tmp_path):
        path = _write(
            tmp_path,
            "data/ini/w.ini",
            "Weapon OldSword\n    AttackRange = 1.0   ; OldSword is the starting weapon\nEnd\n",
        )

        _rename(tmp_path, "weapons", "OldSword", "NewSword")

        assert "; OldSword is the starting weapon" in path.read_text(encoding="utf-8")

    def test_preserves_crlf_newlines(self, tmp_path):
        path = tmp_path / "data" / "ini" / "w.ini"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"Weapon OldSword\r\n    AttackRange = 1.0\r\nEnd\r\n")

        _rename(tmp_path, "weapons", "OldSword", "NewSword")

        assert path.read_bytes() == b"Weapon NewSword\r\n    AttackRange = 1.0\r\nEnd\r\n"

    def test_a_line_holding_no_token_is_not_counted(self, tmp_path):
        # A field's span can cover lines that do not hold the name; those must not count as
        # changes, or the report would claim edits it never made.
        path = _write(
            tmp_path,
            "data/ini/w.ini",
            "Weapon OldSword\n    AttackRange = 1.0\nEnd\n",
        )

        _plan, changed = _rename(tmp_path, "weapons", "OldSword", "NewSword")

        assert changed == {str(path): 1}


class TestCheckConflicts:
    def test_blocks_renaming_onto_an_existing_name(self, tmp_path):
        _write(
            tmp_path,
            "data/ini/w.ini",
            "Weapon OldSword\n    AttackRange = 1.0\nEnd\n"
            "Weapon Taken\n    AttackRange = 2.0\nEnd\n",
        )
        game = load_game(tmp_path).game

        problems = check_conflicts(game, "weapons", "OldSword", "Taken", tmp_path)

        assert any("already exists" in problem for problem in problems)

    def test_blocks_an_unusable_new_name(self, tmp_path):
        _write(tmp_path, "data/ini/w.ini", "Weapon OldSword\n    AttackRange = 1.0\nEnd\n")
        game = load_game(tmp_path).game

        assert check_conflicts(game, "weapons", "OldSword", "New Sword", tmp_path)
        assert check_conflicts(game, "weapons", "OldSword", "New=Sword", tmp_path)

    def test_blocks_an_unknown_definition(self, tmp_path):
        _write(tmp_path, "data/ini/w.ini", "Weapon OldSword\n    AttackRange = 1.0\nEnd\n")
        game = load_game(tmp_path).game

        problems = check_conflicts(game, "weapons", "Absent", "Other", tmp_path)

        assert any("no weapons definition" in problem for problem in problems)

    def test_blocks_a_definition_declared_outside_the_root(self, tmp_path):
        # A base-game definition is not this run's to rewrite, and renaming only the mod's
        # references to it would break every one of them.
        base = tmp_path / "base"
        mod = tmp_path / "mod"
        _write(base, "data/ini/w.ini", "Weapon BaseSword\n    AttackRange = 1.0\nEnd\n")
        _write(mod, "data/ini/o.ini", "Object Hero\n    BuildCost = 1\nEnd\n")
        game = load_game(mod, bases=(str(base),)).game

        problems = check_conflicts(game, "weapons", "BaseSword", "NewSword", mod)

        assert any("declared outside the rename root" in problem for problem in problems)

    def test_accepts_a_case_only_rename_as_a_conflict(self, tmp_path):
        _write(tmp_path, "data/ini/w.ini", "Weapon OldSword\n    AttackRange = 1.0\nEnd\n")
        game = load_game(tmp_path).game

        problems = check_conflicts(game, "weapons", "OldSword", "oldsword", tmp_path)

        assert any("same name to the engine" in problem for problem in problems)


class TestScanText:
    def test_reports_an_unmodelled_field_as_unaccounted(self, tmp_path):
        path = _write(
            tmp_path,
            "data/ini/o.ini",
            "Weapon OldSword\n    AttackRange = 1.0\nEnd\n"
            "Object Hero\n    SomeUnmodelledField = OldSword\nEnd\n",
        )
        game = load_game(tmp_path).game
        sites = collect_sites(game, "weapons", "OldSword")

        _promoted, unaccounted = scan_text(iter_ini_files(tmp_path), "weapons", "OldSword", sites)

        assert [(hit.file, hit.line) for hit in unaccounted] == [(str(path), 5)]

    def test_promotes_a_shadowed_declaration(self, tmp_path):
        # Only the winning declaration of a name is registered in the game, so the loser is
        # invisible to the typed pass; between them the two passes must cover both files.
        first = _write(tmp_path, "data/ini/a.ini", "Weapon OldSword\n    AttackRange = 1.0\nEnd\n")
        second = _write(tmp_path, "data/ini/b.ini", "Weapon OldSword\n    AttackRange = 2.0\nEnd\n")
        game = load_game(tmp_path).game
        sites = collect_sites(game, "weapons", "OldSword")

        promoted, _unaccounted = scan_text(iter_ini_files(tmp_path), "weapons", "OldSword", sites)

        assert promoted  # the typed pass alone cannot have found both
        headers = {
            (site.file, site.line)
            for site in dedupe_sites([sites, promoted])
            if site.anchor is Anchor.HEADER_NAME
        }
        assert headers == {(str(first), 1), (str(second), 1)}

    def test_a_promoted_declaration_is_rewritten(self, tmp_path):
        first = _write(tmp_path, "data/ini/a.ini", "Weapon OldSword\n    AttackRange = 1.0\nEnd\n")
        second = _write(tmp_path, "data/ini/b.ini", "Weapon OldSword\n    AttackRange = 2.0\nEnd\n")
        game = load_game(tmp_path).game
        sites = collect_sites(game, "weapons", "OldSword")
        promoted, _ = scan_text(iter_ini_files(tmp_path), "weapons", "OldSword", sites)

        apply_plan(RenamePlan("weapons", "OldSword", "NewSword", dedupe_sites([sites, promoted])))

        assert "Weapon NewSword" in first.read_text(encoding="utf-8")
        assert "Weapon NewSword" in second.read_text(encoding="utf-8")

    def test_a_comment_only_mention_is_unaccounted_not_rewritten(self, tmp_path):
        _write(
            tmp_path,
            "data/ini/o.ini",
            "Weapon OldSword\n    AttackRange = 1.0\nEnd\n; OldSword is deprecated\n",
        )
        game = load_game(tmp_path).game
        sites = collect_sites(game, "weapons", "OldSword")

        _promoted, unaccounted = scan_text(iter_ini_files(tmp_path), "weapons", "OldSword", sites)

        assert unaccounted == []  # the scan ignores comment text entirely


class TestHelpers:
    def test_keywords_for_table_covers_every_object_keyword(self):
        keywords = keywords_for_table("objects")

        assert {"Object", "ChildObject", "ObjectReskin"} <= keywords

    def test_valid_name_rejects_what_the_engine_cannot_read(self):
        assert valid_name("Command_Attack")
        assert valid_name("Gondor-Tower:Upgrade")
        assert not valid_name("two words")
        assert not valid_name("has=equals")
        assert not valid_name("has;comment")
        assert not valid_name("")


class TestRenameCommand:
    def test_dry_run_writes_nothing(self, tmp_path, capsys):
        path = _write(
            tmp_path,
            "data/ini/w.ini",
            "Weapon OldSword\n    AttackRange = 1.0\nEnd\n",
        )
        before = path.read_text(encoding="utf-8")

        assert (
            main(["rename", str(tmp_path), "OldSword", "NewSword", "--no-maps", "--no-config"]) == 0
        )

        assert path.read_text(encoding="utf-8") == before
        assert "nothing written" in capsys.readouterr().out

    def test_apply_rewrites_the_files(self, tmp_path):
        path = _write(
            tmp_path,
            "data/ini/w.ini",
            "Weapon OldSword\n    AttackRange = 1.0\nEnd\n",
        )

        code = main(
            ["rename", str(tmp_path), "OldSword", "NewSword", "--apply", "--no-maps", "--no-config"]
        )

        assert code == 0
        assert "Weapon NewSword" in path.read_text(encoding="utf-8")

    def test_a_blocked_rename_exits_one_and_changes_nothing(self, tmp_path, capsys):
        path = _write(
            tmp_path,
            "data/ini/w.ini",
            "Weapon OldSword\n    AttackRange = 1.0\nEnd\n"
            "Weapon Taken\n    AttackRange = 2.0\nEnd\n",
        )
        before = path.read_text(encoding="utf-8")

        code = main(
            ["rename", str(tmp_path), "OldSword", "Taken", "--apply", "--no-maps", "--no-config"]
        )

        assert code == 1
        assert path.read_text(encoding="utf-8") == before
        assert "blocked" in capsys.readouterr().out

    def test_an_ambiguous_name_asks_for_a_table(self, tmp_path, capsys):
        # One bareword naming two kinds of definition is the caller's to resolve, not ours.
        _write(
            tmp_path,
            "data/ini/x.ini",
            "Weapon Shared\n    AttackRange = 1.0\nEnd\nUpgrade Shared\n    DisplayName = X\nEnd\n",
        )

        code = main(["rename", str(tmp_path), "Shared", "Other", "--no-maps", "--no-config"])

        assert code == 1
        assert "pass --table" in capsys.readouterr().out

    def test_table_disambiguates_an_ambiguous_name(self, tmp_path):
        path = _write(
            tmp_path,
            "data/ini/x.ini",
            "Weapon Shared\n    AttackRange = 1.0\nEnd\nUpgrade Shared\n    DisplayName = X\nEnd\n",
        )

        code = main(
            [
                "rename",
                str(tmp_path),
                "Shared",
                "Other",
                "--table",
                "weapons",
                "--apply",
                "--no-maps",
                "--no-config",
            ]
        )

        assert code == 0
        text = path.read_text(encoding="utf-8")
        assert "Weapon Other" in text
        assert "Upgrade Shared" in text  # the same bareword in another table is left alone

    def test_a_map_ini_reference_is_rewritten(self, tmp_path):
        # A map.ini is a per-map overlay the global build excludes, so it needs its own pass.
        _write(tmp_path, "data/ini/o.ini", "Object Hero\n    BuildCost = 1\nEnd\n")
        map_ini = _write(
            tmp_path,
            "data/maps/MyMap/map.ini",
            "Object Hero\n    AddModule\n        Behavior = AutoHealBehavior ModuleTag_H\n"
            "            HealingAmount = 5\n        End\n    End\nEnd\n",
        )

        code = main(
            ["rename", str(tmp_path), "Hero", "Champion", "--apply", "--no-maps", "--no-config"]
        )

        assert code == 0
        assert map_ini.read_text(encoding="utf-8").startswith("Object Champion")

    def test_a_map_layout_is_warned_about_but_never_rewritten(self, tmp_path):
        # The whole point of the map half of the feature: the .map is reported so the rename's
        # damage is visible, and left byte-for-byte alone so WorldBuilder still owns it.
        _write(tmp_path, "data/ini/o.ini", "Object Hero\n    BuildCost = 1\nEnd\n")
        raw = Map()
        raw.objects_list = ObjectsList(
            version=1,
            object_list=[
                MapObject(
                    version=1,
                    position=(0.0, 0.0, 0.0),
                    angle=0.0,
                    road_type=0,
                    type_name="Hero",
                    properties={},
                    start_pos=0,
                    end_pos=0,
                )
            ],
            start_pos=0,
            end_pos=0,
        )
        map_path = tmp_path / "data" / "maps" / "MyMap" / "MyMap.map"
        map_path.parent.mkdir(parents=True)
        write_map_to_path(raw, map_path, compress=False)
        before = map_path.read_bytes()

        args = argparse.Namespace(
            root=tmp_path,
            old="Hero",
            new="Champion",
            table=None,
            apply=True,
            no_maps=False,
            base=[],
            json=False,
            no_config=True,
            file=None,
        )
        plan = build_plan(args, Config(), tmp_path)

        assert any("placed object" in warning for warning in plan.map_warnings)
        apply_plan(plan)
        assert map_path.read_bytes() == before

    def test_json_plan_carries_sites_and_summary(self, tmp_path, capsys):
        _write(tmp_path, "data/ini/w.ini", "Weapon OldSword\n    AttackRange = 1.0\nEnd\n")

        main(
            ["rename", str(tmp_path), "OldSword", "NewSword", "--no-maps", "--no-config", "--json"]
        )

        plan = json.loads(capsys.readouterr().out)
        assert plan["table"] == "weapons"
        assert plan["summary"]["sites"] == 1
        assert plan["applied"] == {}

    def test_list_tables_lists_object_keywords(self, capsys):
        assert main(["rename", "--list-tables"]) == 0
        assert "objects" in capsys.readouterr().out

    def test_a_base_tree_is_never_rewritten(self, tmp_path):
        base = tmp_path / "base"
        mod = tmp_path / "mod"
        base_file = _write(
            base,
            "data/ini/w.ini",
            "Weapon BaseSword\n    AttackRange = 1.0\nEnd\n"
            "Object BaseHero\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY BaseSword\n"
            "    End\n"
            "End\n",
        )
        mod_file = _write(
            mod,
            "data/ini/o.ini",
            "Weapon BaseSword\n    AttackRange = 9.0\nEnd\n"
            "Object ModHero\n"
            "    WeaponSet\n"
            "        Weapon = PRIMARY BaseSword\n"
            "    End\n"
            "End\n",
        )
        before = base_file.read_text(encoding="utf-8")

        code = main(
            [
                "rename",
                str(mod),
                "BaseSword",
                "ModSword",
                "--base",
                str(base),
                "--apply",
                "--no-maps",
                "--no-config",
            ]
        )

        assert code == 0
        assert base_file.read_text(encoding="utf-8") == before
        assert "Weapon ModSword" in mod_file.read_text(encoding="utf-8")
