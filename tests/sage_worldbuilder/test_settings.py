"""Settings persistence, the recent-maps list and forgiving reads."""

from pathlib import Path

import pytest

from sage_utils.config import user_file
from sage_worldbuilder.jump import JumpMatch, JumpSeat
from sage_worldbuilder.settings import APP, MAX_RECENT, SETTINGS_FILE, RecentMap, Settings


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def test_round_trip():
    settings = Settings(
        install="C:/Game",
        mods=["C:/Mod", "C:/Sub"],
        sagepatch="C:/Mod/.sagepatch",
        autosave_interval_seconds=300,
    )
    settings.add_recent(RecentMap("file", "C:/maps/a.map"))
    settings.add_recent(RecentMap("game", "maps\\fords\\fords.map"))
    assert settings.save()

    assert Settings.load().to_dict() == settings.to_dict()


def test_recent_is_newest_first_deduplicated_and_capped():
    settings = Settings()
    for index in range(MAX_RECENT + 3):
        settings.add_recent(RecentMap("file", f"C:/maps/{index}.map"))
    settings.add_recent(RecentMap("file", "c:/MAPS/5.map"))

    assert len(settings.recent) == MAX_RECENT
    assert settings.recent[0].path == "c:/MAPS/5.map"
    assert sum(recent.path.lower() == "c:/maps/5.map" for recent in settings.recent) == 1

    settings.remove_recent(RecentMap("file", "C:/maps/5.map"))
    assert all(recent.path.lower() != "c:/maps/5.map" for recent in settings.recent)


def test_corrupt_file_gives_defaults():
    path = user_file(APP, SETTINGS_FILE)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert Settings.load().to_dict() == Settings().to_dict()


def test_wrong_values_are_ignored_one_by_one():
    settings = Settings.from_dict(
        {
            "install": 3,
            "mod": "C:/Mod",
            "autosave_enabled": "yes",
            "autosave_interval_seconds": True,
            "recent": [{"kind": "bad", "path": "x"}, {"kind": "file", "path": "ok.map"}, "junk"],
        }
    )

    assert settings.install is None
    assert settings.mods == ["C:/Mod"]  # one `mod`, as written before several could load
    assert settings.autosave_enabled is True
    assert settings.autosave_interval_seconds == Settings().autosave_interval_seconds
    assert settings.recent == [RecentMap("file", "ok.map")]


def test_layers_and_autosave_come_from_the_values():
    settings = Settings(
        install="C:/Game",
        mods=["C:/Mod", "C:/Sub"],
        sagepatch="C:/Mod/.sagepatch",
        autosave_interval_seconds=5,
    )
    layers = settings.layers()

    assert layers is not None
    assert layers.install == Path("C:/Game")
    assert layers.mods == (Path("C:/Mod"), Path("C:/Sub"))
    assert layers.sagepatch == Path("C:/Mod/.sagepatch")
    assert Settings(install="C:/Game").layers().sagepatch is None
    assert settings.autosave_settings().interval_seconds == 60


def test_mods_keep_load_order_and_a_reloaded_one_moves_last():
    settings = Settings.from_dict({"mods": ["C:/A", "C:/B", 3, "", "c:\\a\\"], "mod": "C:/Old"})
    assert settings.mods == ["C:/B", "c:\\a\\"]

    settings.load_mod("C:/C")
    settings.load_mod("C:/B")
    assert settings.mods == ["c:\\a\\", "C:/C", "C:/B"]
    assert settings.has_mod("C:\\c")

    settings.unload_mod("c:/a")
    assert settings.mods == ["C:/C", "C:/B"]
    assert Settings.from_dict(settings.to_dict()).mods == ["C:/C", "C:/B"]


def test_jump_options_round_trip():
    settings = Settings(jump_windowed=False, jump_script_debug=True, jump_extra_arguments="-quick")
    settings.save()

    options = Settings.load().jump_options()
    assert (options.windowed, options.script_debug, options.extra_arguments) == (
        False,
        True,
        "-quick",
    )


def test_the_jump_match_round_trips_and_reaches_the_options():
    match = JumpMatch(
        enabled=True, seats=(JumpSeat("hard", "FactionMen", 2, "ColorRed", 1),), seed=5
    )
    Settings(jump_match=match).save()

    loaded = Settings.load()
    assert loaded.jump_match == match
    assert loaded.jump_options("S=X:;").game_info == "S=X:;"
    assert loaded.jump_options().game_info is None


def test_recent_labels():
    assert RecentMap("game", "maps\\fords\\fords.map").label() == "fords (game)"
    assert RecentMap("file", "C:/maps/a.map").label() == "C:/maps/a.map"
