"""Tests for the command line a scenario is launched with, and where its map is written.

Data-free: both are pure path and argument arithmetic, and both have a rule that is silent when
broken - the `-file` argument names a folder that does not exist, and `-mod` has to be absolute
because the game runs with its own directory as the working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_test.runner import install_map, install_map_folder, launch_arguments


class TestLaunchArguments:
    def test_the_map_is_named_with_file(self):
        arguments = launch_arguments("maps\\x.map", "C:/RotWK/game.dat", windowed=False)
        assert arguments[0].endswith("game.dat")
        assert arguments[1:3] == ["-file", "maps\\x.map"]

    def test_no_mod_argument_unless_asked_for(self):
        assert "-mod" not in launch_arguments("m.map", "C:/RotWK/game.dat")

    def test_the_mod_tree_is_passed_absolute(self, tmp_path: Path):
        """The game runs with its own directory as the working directory, so a relative `-mod`
        would name a folder under the install rather than the one the caller meant."""
        tree = tmp_path / "_mod"
        tree.mkdir()
        arguments = launch_arguments("m.map", "C:/RotWK/game.dat", mod=tree)
        assert "-mod" in arguments
        given = Path(arguments[arguments.index("-mod") + 1])
        assert given.is_absolute()
        assert given == tree.resolve()

    def test_windowed_carries_the_resolution(self):
        arguments = launch_arguments("m.map", "g.dat", windowed=True, resolution=(800, 600))
        assert "-win" in arguments
        assert arguments[arguments.index("-xres") + 1] == "800"
        assert arguments[arguments.index("-yres") + 1] == "600"

    def test_script_debug_is_opt_in(self):
        assert "-scriptDebug2" not in launch_arguments("m.map", "g.dat")
        assert "-scriptDebug2" in launch_arguments("m.map", "g.dat", script_debug=True)

    def test_extra_arguments_come_last(self):
        arguments = launch_arguments("m.map", "g.dat", extra=("-noaudio",))
        assert arguments[-1] == "-noaudio"


class TestInstallMap:
    def test_the_map_lands_in_its_own_folder(self, tmp_path: Path):
        path, _argument = install_map("scen", b"bytes", user_files=tmp_path)
        assert path == tmp_path / "Maps" / "scen" / "scen.map"
        assert path.read_bytes() == b"bytes"

    def test_the_file_argument_names_the_parent_not_the_file(self, tmp_path: Path):
        """The engine inserts the map's own stem as a directory, so the argument that resolves to
        `…\\Maps\\scen\\scen.map` is `…\\Maps\\scen.map` - a path that does not exist on disk.
        Passing the real one produces the folder twice and the cache lookup misses in silence."""
        path, argument = install_map("scen", b"", user_files=tmp_path)
        assert argument != str(path).lower()
        assert argument == str(tmp_path / "Maps" / "scen.map").lower()

    def test_the_argument_is_lowercased(self, tmp_path: Path):
        """The map cache is keyed lowercase and the lookup is a plain comparison, so a capital
        letter is a miss rather than a near-miss."""
        _path, argument = install_map("ScenName", b"", user_files=tmp_path)
        assert argument == argument.lower()

    def test_writing_twice_replaces_rather_than_failing(self, tmp_path: Path):
        install_map("scen", b"first", user_files=tmp_path)
        path, _ = install_map("scen", b"second", user_files=tmp_path)
        assert path.read_bytes() == b"second"


class TestInstallMapFolder:
    """Copying a shipped map into the user files, which is how a map the mod's own cache flags
    `isMultiplayer = no` gets started at all: the engine caches what it finds here itself."""

    def _map_folder(self, root: Path, name: str = "wor andrast") -> Path:
        source = root / name
        source.mkdir(parents=True)
        (source / f"{name}.map").write_bytes(b"mapdata")
        (source / "map.ini").write_text('#include "..\\_inis\\general\\wotrmaps.ini"\n')
        (source / f"{name}.tga").write_bytes(b"preview")
        return source

    def test_the_whole_folder_comes_along(self, tmp_path: Path):
        """`map.ini` is the point of the exercise - a map copied without it is a map whose
        per-map data is not under test."""
        source = self._map_folder(tmp_path / "mod")
        installed = install_map_folder(source, user_files=tmp_path / "user")
        assert (installed.path / "wor andrast.map").read_bytes() == b"mapdata"
        assert (installed.path / "map.ini").is_file()

    def test_the_argument_is_the_parent_form_lowercased(self, tmp_path: Path):
        source = self._map_folder(tmp_path / "mod")
        installed = install_map_folder(source, user_files=tmp_path / "user")
        assert installed.argument == str(tmp_path / "user" / "Maps" / "wor andrast.map").lower()

    def test_extras_land_beside_the_map_not_inside_it(self, tmp_path: Path):
        r"""A relative `#include` resolves against the copied map's own folder, so
        `..\_inis\...` only finds anything if `_inis` is the map folder's sibling. Get this
        wrong and the load stops on an error box that reads exactly like a broken map.ini."""
        source = self._map_folder(tmp_path / "mod")
        shared = tmp_path / "mod" / "_inis" / "general"
        shared.mkdir(parents=True)
        (shared / "wotrmaps.ini").write_text("; shared\n")

        installed = install_map_folder(
            source, extras=(tmp_path / "mod" / "_inis",), user_files=tmp_path / "user"
        )
        assert (installed.path.parent / "_inis" / "general" / "wotrmaps.ini").is_file()

    def test_a_renamed_install_renames_the_map_with_it(self, tmp_path: Path):
        """The folder name and the map's stem have to match, because the `-file` path builder
        derives one from the other."""
        source = self._map_folder(tmp_path / "mod")
        installed = install_map_folder(source, name="sagetest x", user_files=tmp_path / "user")
        assert (installed.path / "sagetest x.map").is_file()
        assert (installed.path / "sagetest x.tga").is_file()
        assert installed.argument.endswith("sagetest x.map")

    def test_everything_created_is_reported_for_removal(self, tmp_path: Path):
        source = self._map_folder(tmp_path / "mod")
        (tmp_path / "mod" / "_inis").mkdir()
        installed = install_map_folder(
            source, extras=(tmp_path / "mod" / "_inis",), user_files=tmp_path / "user"
        )
        assert set(installed.created) == {installed.path, installed.path.parent / "_inis"}

    def test_an_extra_that_was_already_there_is_left_alone(self, tmp_path: Path):
        """It belongs to whoever put it there - a test that removes a player's files afterwards
        is worse than one that skips a copy."""
        source = self._map_folder(tmp_path / "mod")
        (tmp_path / "mod" / "_inis").mkdir()
        existing = tmp_path / "user" / "Maps" / "_inis"
        existing.mkdir(parents=True)
        (existing / "theirs.ini").write_text("mine\n")

        installed = install_map_folder(
            source, extras=(tmp_path / "mod" / "_inis",), user_files=tmp_path / "user"
        )
        assert (existing / "theirs.ini").is_file()
        assert existing not in installed.created

    def test_a_folder_with_no_map_is_refused(self, tmp_path: Path):
        empty = tmp_path / "mod" / "not a map"
        empty.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            install_map_folder(empty, user_files=tmp_path / "user")
