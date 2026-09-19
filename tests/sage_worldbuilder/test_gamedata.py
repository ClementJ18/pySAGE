"""GameLayers / GameContext over small loose game trees, and the VFS extraction behind the load."""

from pathlib import Path

import pytest

from sage_ini.engine import STOCK, active, revert
from sage_ini.model.objects import REGISTRY
from sage_map.map import Map
from sage_utils.installs import find_install
from sage_utils.vfs import VirtualFileSystem
from sage_worldbuilder import MapCategory, MapDocument
from sage_worldbuilder.gamedata import GameContext, GameLayers, keep_game_data


def touch(root: Path, relative: str, text: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_install(root: Path) -> Path:
    touch(root, "data/ini/object/units.ini", "Object TestUnit\nEnd\n")
    touch(root, "data/ini/readme.txt", "not game data")
    map_path = root / "Maps" / "Fords" / "Fords.map"
    map_path.parent.mkdir(parents=True)
    MapDocument(Map()).save(map_path, compress=False)
    return root


@pytest.mark.parametrize(
    ("key", "kept"),
    [
        ("data\\ini\\object\\units.ini", True),
        ("data\\ini\\default\\gamedata.inc", True),
        ("data\\lotr.str", True),
        ("data\\ini\\readme.txt", False),
        ("data\\maps\\map mp arnor\\map.str", False),
        ("maps\\fords\\map.ini", False),
        ("art\\textures\\foo.dds", False),
    ],
)
def test_keep_game_data(key, kept):
    assert keep_game_data(key) is kept


def test_extract_copies_winners_and_skips_unchanged_sets(tmp_path, monkeypatch):
    mod, install, out = tmp_path / "mod", tmp_path / "install", tmp_path / "out"
    touch(mod, "data/ini/a.ini", "mod")
    touch(install, "data/ini/a.ini", "install")
    touch(install, "data/ini/b.ini", "install")
    filesystem = VirtualFileSystem([mod, install], archives=False)

    filesystem.extract(out, ("data",), keep_game_data)
    assert (out / "data" / "ini" / "a.ini").read_text(encoding="utf-8") == "mod"
    assert (out / "data" / "ini" / "b.ini").is_file()

    reads: list[object] = []
    original = filesystem.read_bytes

    def counting(entry):
        reads.append(entry)
        return original(entry)

    monkeypatch.setattr(filesystem, "read_bytes", counting)
    filesystem.extract(out, ("data",), keep_game_data)
    assert reads == []


def test_extract_deletes_files_no_longer_in_the_set(tmp_path):
    install, out = tmp_path / "install", tmp_path / "out"
    gone = touch(install, "data/ini/gone.ini")
    touch(install, "data/ini/kept.ini")
    VirtualFileSystem([install], archives=False).extract(out, ("data",), keep_game_data)
    touch(out, "notes.txt")  # not game data, so never touched
    gone.unlink()

    VirtualFileSystem([install], archives=False).extract(out, ("data",), keep_game_data)

    assert not (out / "data" / "ini" / "gone.ini").exists()
    assert (out / "data" / "ini" / "kept.ini").is_file()
    assert (out / "notes.txt").is_file()


def test_context_lists_opens_and_loads(tmp_path):
    install = make_install(tmp_path / "install")
    user = tmp_path / "user"
    context = GameContext.open(GameLayers(install), user)

    maps = context.maps(MapCategory.SYSTEM)
    assert [entry.name for entry in maps] == ["Fords"]
    document = context.open_map(maps[0])
    assert document.title == "Fords"
    assert not document.read_only
    assert context.find_map("maps/fords/fords.map").name == "Fords"
    assert context.find_map("maps/missing/missing.map") is None

    game = context.load(cache=tmp_path / "cache")
    assert "TestUnit" in game.objects
    assert context.game is None  # the caller decides when to swap it in


def test_save_paths_follow_the_writable_layers(tmp_path):
    install = make_install(tmp_path / "install")
    user, mod = tmp_path / "user", tmp_path / "mod"
    plain = GameContext.open(GameLayers(install), user)
    modded = GameContext.open(GameLayers(install, (tmp_path / "lower", mod)), user)

    assert plain.save_path(MapCategory.USER, "New") == user / "Maps" / "New" / "New.map"
    assert plain.save_path(MapCategory.SYSTEM, "New") is None
    # Into the last mod loaded, whose files win.
    assert modded.save_path(MapCategory.LIBRARIES, "Lib") == mod / "Libraries" / "Lib" / "Lib.map"


def test_a_later_mod_wins_over_an_earlier_one(tmp_path):
    install = make_install(tmp_path / "install")
    first, second = tmp_path / "first", tmp_path / "second"
    touch(first, "data/ini/shared.ini", "first")
    touch(first, "data/ini/first.ini", "first")
    touch(second, "data/ini/shared.ini", "second")
    filesystem = GameLayers(install, [first, second]).filesystem()

    assert filesystem.read_bytes("data/ini/shared.ini") == b"second"
    assert filesystem.read_bytes("data/ini/first.ini") == b"first"
    assert (
        GameLayers(install, [second, first]).filesystem().read_bytes("data/ini/shared.ini")
        == b"first"
    )


SAGEPATCH = """version = 3

[[patches]]
name = "hero-mana"

[[fields]]
block = "Object"
name = "PatchedPool"
type = "Int"
default = 0
patch = "hero-mana"
"""


@pytest.fixture
def stock_engine():
    yield
    revert()


def test_a_sagepatch_teaches_the_model_before_the_data_loads(tmp_path, stock_engine):
    install = make_install(tmp_path / "install")
    touch(install, "data/ini/object/units.ini", "Object TestUnit\n  PatchedPool = 3\nEnd\n")
    sagepatch = touch(tmp_path, "mod.sagepatch", SAGEPATCH)
    context = GameContext.open(GameLayers(install, sagepatch=sagepatch), tmp_path / "user")

    assert [patch.name for patch in context.engine.patches] == ["hero-mana"]
    assert "PatchedPool" not in REGISTRY["Object"]._fieldspec  # opening applies nothing
    assert context.apply_engine() == []
    assert "PatchedPool" in REGISTRY["Object"]._fieldspec
    game = context.load(cache=tmp_path / "cache")
    assert game.objects["TestUnit"].PatchedPool == 3

    # Mounting without it goes back to the stock engine.
    assert GameContext.open(GameLayers(install), tmp_path / "user").apply_engine() == []
    assert active() is STOCK
    assert "PatchedPool" not in REGISTRY["Object"]._fieldspec


def test_a_missing_or_malformed_sagepatch_is_reported_not_raised(tmp_path, stock_engine):
    install = make_install(tmp_path / "install")
    gone = GameContext.open(GameLayers(install, sagepatch=tmp_path / "gone.sagepatch"), None)
    assert gone.engine.is_stock
    assert any("no .sagepatch" in problem for problem in gone.apply_engine())

    broken = touch(tmp_path, "broken.sagepatch", "version = [")
    problems = GameContext.open(GameLayers(install, sagepatch=broken), None).apply_engine()
    assert problems and "broken.sagepatch" in problems[0]


def test_open_needs_an_existing_install(tmp_path):
    with pytest.raises(FileNotFoundError):
        GameContext.open(GameLayers(tmp_path / "missing"), detect_user_data=False)


def test_cache_dir_is_per_layer_combination(tmp_path):
    install = tmp_path / "install"
    a, b = tmp_path / "a", tmp_path / "b"
    assert GameLayers(install).cache_dir() != GameLayers(install, (a,)).cache_dir()
    assert GameLayers(install).cache_dir() == GameLayers(install).cache_dir()
    assert GameLayers(install, (a, b)).cache_dir() != GameLayers(install, (b, a)).cache_dir()


@pytest.mark.full
def test_installed_game_archive_map_opens_read_only():
    install = find_install("rotwk")
    if install is None:
        pytest.skip("no installed game")
    context = GameContext.open(GameLayers(install.path))
    archived = next((m for m in context.maps(MapCategory.SYSTEM) if m.read_only), None)
    if archived is None:
        pytest.skip("the install ships no archived maps")

    document = context.open_map(archived)

    assert document.read_only
    assert document.path is None
    assert document.title == archived.name
