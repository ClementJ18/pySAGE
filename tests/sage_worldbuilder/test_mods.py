"""Loading an unpacked mod: where `-mod` points, what counts as a mod folder, the command line and
the recent-mods list."""

from pathlib import Path

import pytest

from sage_worldbuilder.gamedata import is_mod_folder, resolve_mod_folder
from sage_worldbuilder.settings import MAX_RECENT, Settings
from sage_worldbuilder.ui.app import parse_arguments


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


def test_absolute_mod_path_is_taken_as_given(tmp_path):
    mod = tmp_path / "Edain"
    mod.mkdir()
    assert resolve_mod_folder(mod, tmp_path / "user") == mod


def test_relative_mod_path_is_looked_up_in_the_user_mods_folder(tmp_path, monkeypatch):
    user = tmp_path / "user"
    (user / "Mods" / "Edain").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert resolve_mod_folder("Edain", user) == user / "Mods" / "Edain"


def test_relative_mod_path_falls_back_to_the_working_directory(tmp_path, monkeypatch):
    (tmp_path / "_mod").mkdir()
    monkeypatch.chdir(tmp_path)
    assert resolve_mod_folder("_mod", tmp_path / "user") == (tmp_path / "_mod").resolve()
    assert resolve_mod_folder("_mod", None) == (tmp_path / "_mod").resolve()


def test_mod_folder_needs_data_or_archives(tmp_path):
    empty, loose, packed = tmp_path / "empty", tmp_path / "loose", tmp_path / "packed"
    empty.mkdir()
    (loose / "Data" / "ini").mkdir(parents=True)
    packed.mkdir()
    (packed / "_mod.big").write_bytes(b"")

    assert not is_mod_folder(empty)
    assert is_mod_folder(loose)
    assert is_mod_folder(packed)
    assert not is_mod_folder(tmp_path / "missing")


def test_command_line_takes_the_games_spelling():
    args = parse_arguments(["fords.map", "-mod", "C:/Mods/Edain"])
    assert args.map == Path("fords.map")
    assert args.mods == ["C:/Mods/Edain"]

    args = parse_arguments(["--mod", "Edain"])
    assert args.map is None and args.mods == ["Edain"]

    assert parse_arguments([]).mods == []
    assert parse_arguments([]).sagepatch is None
    assert parse_arguments(["-sagepatch", "C:/Mods/Edain/.sagepatch"]).sagepatch == Path(
        "C:/Mods/Edain/.sagepatch"
    )


def test_repeated_mod_switches_keep_their_order():
    args = parse_arguments(["-mod", "Edain", "fords.map", "--mod", "Submod"])
    assert args.map == Path("fords.map")
    assert args.mods == ["Edain", "Submod"]


def test_recent_mods_are_newest_first_deduplicated_capped_and_saved():
    settings = Settings()
    for index in range(MAX_RECENT + 2):
        settings.add_recent_mod(f"C:/Mods/{index}")
    settings.add_recent_mod("c:\\MODS\\4\\")

    assert len(settings.recent_mods) == MAX_RECENT
    assert settings.recent_mods[0] == "c:\\MODS\\4\\"
    assert sum(folder.lower().startswith("c:\\mods\\4") for folder in settings.recent_mods) == 1
    assert "C:/Mods/4" not in settings.recent_mods

    settings.save()
    assert Settings.load().recent_mods == settings.recent_mods
    assert Settings.from_dict({"recent_mods": ["ok", 3, ""]}).recent_mods == ["ok"]
