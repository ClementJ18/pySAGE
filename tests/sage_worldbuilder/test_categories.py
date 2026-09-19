"""Open Map categories over loose folders, and the loose side of the virtual file system."""

from pathlib import Path

from sage_utils.installs import RegistryKey, user_data_dir
from sage_utils.vfs import VirtualFileSystem, vfs_key
from sage_worldbuilder import MapCategory, list_maps


def touch(root: Path, relative: str, data: bytes = b"") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_vfs_key_normalizes_separators_and_case():
    assert vfs_key("/Maps/Foo/Foo.map") == "maps\\foo\\foo.map"


def test_higher_layer_wins_and_each_path_lists_once(tmp_path):
    mod, install = tmp_path / "mod", tmp_path / "install"
    touch(mod, "Maps/a/a.map", b"mod")
    touch(install, "Maps/a/a.map", b"install")
    touch(install, "Maps/b/b.map", b"install")
    filesystem = VirtualFileSystem([mod, install], archives=False)

    listed = sorted(entry.path for entry in filesystem.listdir("maps"))
    assert listed == ["Maps\\a\\a.map", "Maps\\b\\b.map"]
    assert filesystem.read_bytes("maps/a/a.map") == b"mod"
    assert filesystem.find("maps/missing.map") is None


def test_list_maps_keeps_only_name_matching_layouts(tmp_path):
    touch(tmp_path, "Maps/Fords/Fords.map")
    touch(tmp_path, "Maps/Fords/map.ini")
    touch(tmp_path, "Maps/Odd/Other.map")
    touch(tmp_path, "Maps/loose.map")
    touch(tmp_path, "Bases/Camp/Camp.bse")
    filesystem = VirtualFileSystem([tmp_path], archives=False)

    maps = list_maps(MapCategory.SYSTEM, filesystem)
    assert [entry.name for entry in maps] == ["Fords"]
    assert not maps[0].read_only
    assert [entry.name for entry in list_maps(MapCategory.BASES, filesystem)] == ["Camp"]


def test_user_maps_come_from_the_user_data_folder(tmp_path):
    game, user = tmp_path / "game", tmp_path / "user"
    touch(game, "Maps/System/System.map")
    touch(user, "Maps/Mine/Mine.map")
    filesystem = VirtualFileSystem([game], archives=False)

    assert [m.name for m in list_maps(MapCategory.USER, filesystem, user)] == ["Mine"]
    assert list_maps(MapCategory.USER, filesystem, None) == []


def test_user_data_dir_joins_the_registry_leaf_onto_appdata(tmp_path):
    def reader(key: RegistryKey) -> str | None:
        return "My Game Files" if key.value == "UserDataLeafName" else None

    assert user_data_dir("rotwk", reader, appdata=tmp_path) == tmp_path / "My Game Files"
    assert user_data_dir("rotwk", lambda key: None, appdata=tmp_path) is None
    assert user_data_dir("unknown", reader, appdata=tmp_path) is None
