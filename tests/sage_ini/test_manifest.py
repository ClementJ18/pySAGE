"""Unit tests for sage_ini.manifest: the base-symbol manifest's build/write/read/digest round
trips and the model parity a manifest-seeded `Game` must hold against a real `load_game`."""

import json

import pytest

from sage_ini.loader import load_game
from sage_ini.manifest import (
    FORMAT_VERSION,
    ManifestError,
    build_manifest,
    game_from_manifest,
    load_manifest_into,
    manifest_matches_roots,
    read_manifest,
    source_digest,
    write_manifest,
)
from sage_ini.model.game import Game
from sage_ini.model.xref import Xref
from sage_lint.rules.module_ops import default_module_tags, resolved_module_tags


def _write(folder, name, text):
    (folder / name).parent.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def _base_tree(root):
    """A small but shape-complete base game: the default template with an inheritable module, a
    parent object (typed body/draw plus an unmodeled module), a child applying all three edits, a
    weapon it references, an experience level, a revive command button, an FXList with both nugget
    kinds and the particle system one names, a string label, an asset, and a map."""
    _write(
        root,
        "objects.ini",
        "#define BASE_COST 100\n"
        "Object DefaultThingTemplate\n"
        "    InheritableModule\n"
        "        Behavior = AutoHealBehavior ModuleTag_DefaultHeal\n"
        "        End\n"
        "    End\n"
        "End\n"
        "Object BaseInfantry\n"
        "    BuildCost = 100\n"
        "    WeaponSet\n"
        "        Weapon = PRIMARY BaseSword\n"
        "    End\n"
        "    Behavior = ActiveBody ModuleTag_Body\n"
        "    End\n"
        "    Draw = W3DScriptedModelDraw ModuleTag_Draw\n"
        "    End\n"
        "    Behavior = MysteryModule ModuleTag_Mystery\n"
        "    End\n"
        "End\n"
        "ChildObject BaseArcher BaseInfantry\n"
        "    AddModule\n"
        "        Behavior = AutoHealBehavior ModuleTag_AddedHeal\n"
        "        End\n"
        "    End\n"
        "    ReplaceModule ModuleTag_Body\n"
        "        Behavior = ActiveBody ModuleTag_NewBody\n"
        "        End\n"
        "    End\n"
        "    RemoveModule = ModuleTag_Draw\n"
        "End\n",
    )
    _write(root, "weapons.ini", "Weapon BaseSword\n    PrimaryDamage = 10\nEnd\n")
    _write(
        root,
        "levels.ini",
        "ExperienceLevel BaseVeteran\n    RequiredExperience = 100\n    Rank = 1\nEnd\n",
    )
    _write(root, "buttons.ini", "CommandButton Command_Revive\n    Command = REVIVE\nEnd\n")
    _write(
        root,
        "fx.ini",
        "FXParticleSystem BaseSparkles\n    SystemLifetime = 30\nEnd\n"
        "FXList BaseHitFX\n"
        "    BuffNugget\n"
        "        BuffLifeTime = 5000\n"
        "    End\n"
        "    ParticleSystem\n"
        "        Name = BaseSparkles\n"
        "    End\n"
        "End\n",
    )
    _write(root, "strings.str", 'CONTROLBAR:BaseLabel\n"hi"\nEND\n')
    _write(root, "art/gbarcher.w3d", "")
    _write(root, "maps/testmap/testmap.map", "")


@pytest.fixture
def base(tmp_path):
    root = tmp_path / "base"
    _base_tree(root)
    return root


class TestRoundTrip:
    def test_write_read_is_identity(self, base, tmp_path):
        data = build_manifest(load_game(base), [base])
        path = write_manifest(data, tmp_path / "m.json")

        assert read_manifest(path) == data

    def test_gzip_round_trip(self, base, tmp_path):
        data = build_manifest(load_game(base), [base])
        path = write_manifest(data, tmp_path / "m.json.gz")

        # The file is gzip on disk (a plain-JSON read would choke), yet reads back identically.
        assert path.read_bytes()[:2] == b"\x1f\x8b"
        assert read_manifest(path) == data

    def test_format_field_is_current(self, base):
        assert build_manifest(load_game(base), [base])["format"] == FORMAT_VERSION

    def test_version_mismatch_raises(self, base, tmp_path):
        data = build_manifest(load_game(base), [base])
        path = tmp_path / "old.json"
        path.write_bytes(json.dumps({**data, "format": FORMAT_VERSION + 1}).encode())

        with pytest.raises(ManifestError):
            read_manifest(path)

    def test_unreadable_payload_raises(self, tmp_path):
        path = tmp_path / "junk.json"
        path.write_text("not json", encoding="utf-8")

        with pytest.raises(ManifestError):
            read_manifest(path)


class TestModelParity:
    """A manifest-seeded game must answer every question the rules ask exactly as a real load."""

    @pytest.fixture
    def games(self, base, tmp_path):
        real = load_game(base).game
        data = build_manifest(load_game(base), [base])
        path = write_manifest(data, tmp_path / "m.json")
        manifest = game_from_manifest(path, virtual_root=tmp_path / "vroot")
        return real, manifest

    def test_table_name_sets_match(self, games):
        real, manifest = games
        for table in ("objects", "weapons", "levels", "commandbuttons", "fxlists"):
            assert set(manifest.tables[table]) == set(real.tables[table])

    def test_case_insensitive_lookup(self, games):
        _, manifest = games
        obj, canonical = manifest.lookup("objects", "basearcher")
        assert obj is not None
        assert canonical == "BaseArcher"

    def test_parent_resolves_by_direct_table_read(self, games):
        _, manifest = games
        archer = manifest.objects["BaseArcher"]
        assert archer.parent is manifest.objects["BaseInfantry"]

    def test_resolved_module_tags_match(self, games):
        real, manifest = games

        def tag_classes(game, name):
            defaults = default_module_tags(game)
            resolved = resolved_module_tags(game.objects[name], defaults)
            return {
                tag: (type(m).__name__ if m is not None else None) for tag, m in resolved.items()
            }

        for name in ("BaseInfantry", "BaseArcher"):
            assert tag_classes(manifest, name) == tag_classes(real, name)

    def test_child_edits_reshape_the_module_set(self, games):
        _, manifest = games
        defaults = default_module_tags(manifest)
        tags = resolved_module_tags(manifest.objects["BaseArcher"], defaults)

        assert "ModuleTag_Draw" not in tags  # removed
        assert "ModuleTag_Body" not in tags  # replaced away
        assert type(tags["ModuleTag_NewBody"]).__name__ == "ActiveBody"  # replacement
        assert type(tags["ModuleTag_AddedHeal"]).__name__ == "AutoHealBehavior"  # added
        assert tags["ModuleTag_Mystery"] is None  # inherited unmodeled block

    def test_game_level_tables_match(self, games):
        real, manifest = games
        assert manifest.macros == real.macros
        assert set(manifest.strings) == set(real.strings)
        assert manifest.assets == real.assets

    def test_map_files_preserve_relative_layout(self, games, tmp_path):
        _, manifest = games
        vroot = tmp_path / "vroot"
        rels = [path.relative_to(vroot).as_posix() for path in manifest.map_files]
        assert rels == ["maps/testmap/testmap.map"]

    def test_forward_refs_become_reverse_edges(self, games):
        real, manifest = games
        xref = Xref.for_game(manifest)

        # The weapon a base object names is referenced (a real converted-field edge and a folded
        # `_manifest_edge` both land it), so an unused-definition check would not flag it.
        assert xref.is_referenced(manifest.weapons["BaseSword"])
        assert manifest.objects["BaseInfantry"] in xref.referenced_by(manifest.weapons["BaseSword"])
        # The particle system an FXList nugget names, likewise.
        assert xref.is_referenced(manifest.particlesystems["BaseSparkles"])


class TestShadow:
    def test_shadowed_file_definitions_are_skipped(self, base, tmp_path):
        data = build_manifest(load_game(base), [base])
        game = Game()
        load_manifest_into(game, data, tmp_path / "vroot", shadow=frozenset({"objects.ini"}))

        assert not set(game.objects)  # objects.ini was owned by the mod
        assert "BaseSword" in game.weapons  # other files still seed


class TestDigest:
    def test_digest_matches_then_goes_stale(self, base):
        data = build_manifest(load_game(base), [base])
        assert manifest_matches_roots(data, [base])

        count, digest = source_digest([base])
        assert data["source"]["file_count"] == count
        assert data["source"]["digest"] == digest

        (base / "weapons.ini").write_text(
            "Weapon BaseSword\n    PrimaryDamage = 999\nEnd\n", encoding="utf-8"
        )
        assert not manifest_matches_roots(data, [base])
