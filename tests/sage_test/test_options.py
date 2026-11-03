"""Overriding `Options.ini` for a launch, against a temporary folder."""

from __future__ import annotations

from sage_test.options import OPTIONS_INI, apply_options, options_override

PLAYER = "AllHealthBars = yes\r\nStaticGameLOD = High\r\nTimesInGame = 7119\r\n"


def test_an_existing_key_is_rewritten_in_place():
    out = apply_options(PLAYER, {"StaticGameLOD": "Low"})
    assert out == "AllHealthBars = yes\r\nStaticGameLOD = Low\r\nTimesInGame = 7119\r\n"


def test_keys_match_case_insensitively_and_missing_ones_are_added():
    out = apply_options("staticgamelod = High\n", {"StaticGameLOD": "Medium", "HeatEffects": "no"})
    assert out == "StaticGameLOD = Medium\nHeatEffects = no\n"


def test_the_players_file_comes_back_byte_for_byte(tmp_path):
    path = tmp_path / OPTIONS_INI
    path.write_bytes(PLAYER.encode("latin-1"))
    with options_override({"StaticGameLOD": "Low"}, folder=tmp_path):
        assert "StaticGameLOD = Low" in path.read_text("latin-1")
        path.write_text("the game rewrote it on exit")
    assert path.read_bytes() == PLAYER.encode("latin-1")


def test_a_file_that_was_not_there_is_removed(tmp_path):
    with options_override({"StaticGameLOD": "Low"}, folder=tmp_path) as path:
        assert path.read_text("latin-1") == "StaticGameLOD = Low\n"
    assert not path.exists()
