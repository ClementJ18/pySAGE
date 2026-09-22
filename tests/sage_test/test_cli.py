"""The `sage-test` command line: installing a map where the engine will cache it, and taking it
back out. Data-free - every path is a `tmp_path`, and no game is launched."""

from pathlib import Path

import pytest

from sage_test.__main__ import main


def _map_folder(root: Path, name: str = "wor andrast") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / f"{name}.map").write_bytes(b"mapdata")
    (folder / "map.ini").write_text('#include "..\\_inis\\general\\wotrmaps.ini"\n')
    return folder


class TestInstallMap:
    def test_the_folder_lands_under_user_files_maps(self, tmp_path: Path, capsys):
        source = _map_folder(tmp_path / "mod")
        user = tmp_path / "user"

        assert main(["install-map", str(source), "--user-files", str(user)]) == 0

        installed = user / "Maps" / "wor andrast"
        assert (installed / "wor andrast.map").read_bytes() == b"mapdata"
        assert (installed / "map.ini").is_file()

    def test_it_prints_the_file_argument_and_the_map_list_name(self, tmp_path: Path, capsys):
        """Both are what the caller does next with it: one starts the map from a command line,
        the other is what to look for in the game's own list."""
        source = _map_folder(tmp_path / "mod")
        user = tmp_path / "user"

        main(["install-map", str(source), "--user-files", str(user)])

        out = capsys.readouterr().out
        assert str(user / "Maps" / "wor andrast.map").lower() in out
        assert "wor andrast" in out

    def test_extras_are_copied_beside_the_map(self, tmp_path: Path):
        source = _map_folder(tmp_path / "mod")
        shared = tmp_path / "mod" / "_inis" / "general"
        shared.mkdir(parents=True)
        (shared / "wotrmaps.ini").write_text("; shared\n")
        user = tmp_path / "user"

        main(
            [
                "install-map",
                str(source),
                "--extras",
                str(tmp_path / "mod" / "_inis"),
                "--user-files",
                str(user),
            ]
        )

        assert (user / "Maps" / "_inis" / "general" / "wotrmaps.ini").is_file()

    def test_name_renames_the_installed_copy(self, tmp_path: Path):
        source = _map_folder(tmp_path / "mod")
        user = tmp_path / "user"

        main(["install-map", str(source), "--name", "harness copy", "--user-files", str(user)])

        assert (user / "Maps" / "harness copy" / "harness copy.map").is_file()

    def test_a_folder_that_does_not_exist_is_refused(self, tmp_path: Path):
        with pytest.raises(SystemExit):
            main(["install-map", str(tmp_path / "nope"), "--user-files", str(tmp_path / "user")])


class TestUninstallMap:
    def test_it_removes_what_install_created(self, tmp_path: Path):
        source = _map_folder(tmp_path / "mod")
        user = tmp_path / "user"
        main(["install-map", str(source), "--user-files", str(user)])

        assert main(["uninstall-map", "wor andrast", "--user-files", str(user)]) == 0
        assert not (user / "Maps" / "wor andrast").exists()

    def test_removing_what_is_not_there_reports_rather_than_raises(self, tmp_path: Path, capsys):
        assert main(["uninstall-map", "absent", "--user-files", str(tmp_path / "user")]) == 1
        assert "nothing installed" in capsys.readouterr().out
