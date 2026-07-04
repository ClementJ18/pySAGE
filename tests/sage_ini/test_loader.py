"""Unit tests for sage_ini.loader (whole-game assembly from a folder)."""

from sage_ini.loader import load_game, load_map, map_files


def _write(folder, name, text):
    (folder / name).parent.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


class TestLoadGame:
    def test_assembles_objects_from_multiple_files(self, tmp_path):
        _write(tmp_path, "a.ini", "Object Alpha\n    BuildCost = 100\nEnd\n")
        _write(tmp_path, "b.ini", "Object Beta\n    BuildCost = 200\nEnd\n")

        loaded = load_game(tmp_path)

        assert set(loaded.game.objects) == {"Alpha", "Beta"}
        assert not loaded.diagnostics

    def test_cross_file_reference_resolves(self, tmp_path):
        _write(tmp_path, "weapons.ini", "Weapon Sword\n    PrimaryDamage = 5\nEnd\n")
        _write(
            tmp_path,
            "objects.ini",
            "Object Hero\n    WeaponSet\n        Weapon = PRIMARY Sword\n    End\nEnd\n",
        )

        loaded = load_game(tmp_path)

        assert "Sword" in loaded.game.weapons
        assert "Hero" in loaded.game.objects

    def test_structural_error_becomes_a_diagnostic(self, tmp_path):
        _write(tmp_path, "broken.ini", "Object Oops\n    A = 1\nEnd\nEnd\n")  # stray End

        loaded = load_game(tmp_path)

        assert any(d.code == "stray-end" for d in loaded.diagnostics)

    def test_included_files_are_not_loaded_as_roots(self, tmp_path):
        _write(tmp_path, "common.inc", "Object Shared\n    BuildCost = 1\nEnd\n")
        _write(tmp_path, "main.ini", '#include "common.inc"\nObject Main\nEnd\n')

        loaded = load_game(tmp_path)

        # common.inc is included by main.ini, so it is not parsed a second time
        # as its own root; its object still loads once via the expansion.
        assert "Shared" in loaded.game.objects
        assert "Main" in loaded.game.objects


class TestBaseSources:
    def test_base_objects_are_built_into_the_game(self, tmp_path):
        mod = tmp_path / "mod"
        base = tmp_path / "base"
        _write(mod, "units.ini", "Object ModUnit\nEnd\n")
        _write(base, "buildings.ini", "Object BaseBuilding\nEnd\n")

        loaded = load_game(mod, bases=(base,))

        # the mod's own object and a base-only object both resolve
        assert "ModUnit" in loaded.game.objects
        assert "BaseBuilding" in loaded.game.objects

    def test_mod_object_overrides_a_same_named_base_object(self, tmp_path):
        mod = tmp_path / "mod"
        base = tmp_path / "base"
        _write(mod, "units.ini", "Object Hero\n    BuildCost = 5\nEnd\n")
        _write(base, "units.ini", "Object Hero\n    BuildCost = 100\nEnd\n")

        loaded = load_game(mod, bases=(base,))

        # base loads first, the mod overrides by name
        assert loaded.game.objects["Hero"].BuildCost == 5

    def test_base_parse_problems_are_not_reported(self, tmp_path):
        mod = tmp_path / "mod"
        base = tmp_path / "base"
        _write(mod, "ok.ini", "Object Fine\nEnd\n")
        _write(base, "broken.ini", "Object Oops\n    A = 1\nEnd\nEnd\n")  # stray End

        loaded = load_game(mod, bases=(base,))

        # the base is build-only: its structural error never reaches the report
        assert not loaded.diagnostics

    def test_base_assets_and_maps_are_indexed(self, tmp_path):
        # A mod reference to a base-game texture or map must resolve, so the loose-asset and
        # map indexes include the base layer's files alongside the mod's.
        mod = tmp_path / "mod"
        base = tmp_path / "base"
        _write(mod, "data/a.ini", "Object Foo\nEnd\n")
        _write(mod, "art/modtex.tga", "x")
        _write(mod, "maps/modmap/modmap.map", "x")
        _write(base, "art/basetex.tga", "x")
        _write(base, "maps/basemap/basemap.map", "x")

        loaded = load_game(mod, bases=(base,))

        assert {"modtex.tga", "basetex.tga"} <= loaded.game.assets
        names = {path.name.lower() for path in loaded.game.map_files}
        assert {"modmap.map", "basemap.map"} <= names


class TestMapScoping:
    def test_map_definitions_are_excluded_from_the_global_game(self, tmp_path):
        _write(tmp_path, "data/objects.ini", "Object Base\n    BuildCost = 1\nEnd\n")
        _write(tmp_path, "maps/laketown/map.ini", "Object MapLocal\n    BuildCost = 9\nEnd\n")

        loaded = load_game(tmp_path)

        # the map's object is per-map and must not leak into the global game
        assert "Base" in loaded.game.objects
        assert "MapLocal" not in loaded.game.objects

    def test_map_files_enumerates_only_maps(self, tmp_path):
        _write(tmp_path, "data/objects.ini", "Object Base\nEnd\n")
        _write(tmp_path, "maps/laketown/map.ini", "Object MapLocal\nEnd\n")

        maps = map_files(tmp_path)

        assert [p.name for p in maps] == ["map.ini"]

    def test_load_map_layers_one_map_on_the_global_game(self, tmp_path):
        _write(tmp_path, "data/objects.ini", "Object Base\n    BuildCost = 1\nEnd\n")
        map_path = tmp_path / "maps" / "laketown" / "map.ini"
        _write(tmp_path, "maps/laketown/map.ini", "Object MapLocal\n    BuildCost = 9\nEnd\n")

        loaded = load_map(map_path, tmp_path)

        # in the map context, both the global object and the map-local one exist
        assert "Base" in loaded.game.objects
        assert "MapLocal" in loaded.game.objects

    def test_load_map_override_applies_only_in_its_context(self, tmp_path):
        _write(tmp_path, "data/objects.ini", "Object Hero\n    BuildCost = 100\nEnd\n")
        map_path = tmp_path / "maps" / "laketown" / "map.ini"
        _write(tmp_path, "maps/laketown/map.ini", "Object Hero\n    BuildCost = 5\nEnd\n")

        # the global game keeps the base value; the map context sees the override
        assert load_game(tmp_path).game.objects["Hero"].BuildCost == 100
        assert load_map(map_path, tmp_path).game.objects["Hero"].BuildCost == 5

    def test_map_strings_stay_out_of_the_global_table(self, tmp_path):
        _write(tmp_path, "data/lotr.str", 'OBJECT:Global\n"Global"\nEND\n')
        _write(tmp_path, "maps/laketown/map.str", 'OBJECT:MapLocal\n"Map"\nEND\n')

        strings = load_game(tmp_path).game.strings

        assert "OBJECT:Global" in strings
        assert "OBJECT:MapLocal" not in strings
