"""CLI behaviour, driven against the synthetic engine image rather than a real game."""

from __future__ import annotations

import json

import pytest

from sage_live import __main__ as cli
from sage_live.memory import LAYOUT_ROTWK_201, MemoryBackend
from tests.sage_live.test_memory import build_game


@pytest.fixture
def attached(monkeypatch):
    """Replace process attachment with the fake image, leaving every command intact."""

    def fake_attach(args):
        backend = MemoryBackend(build_game(), layout=cli._layout(args.layout_json))
        backend.connect()
        return backend

    monkeypatch.setattr(cli, "_attach", fake_attach)


def test_info_reports_frame_players_and_census(attached, capsys):
    assert cli.main(["info"]) == 0
    out = capsys.readouterr().out
    assert "frame           8688" in out
    assert "Player_1" in out and "Men" in out
    assert "PlyrCreeps" in out
    assert "<- local" in out


def test_info_json_is_machine_readable(attached, capsys):
    assert cli.main(["info", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["frame"] == 8688
    assert doc["local_player"] == 2
    assert doc["object_count"] == 4
    assert doc["objects_by_side"]["Men"] == 3
    assert doc["fogged"] is False


def test_players_json_lists_every_named_side(attached, capsys):
    assert cli.main(["players", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [p["name"] for p in doc] == ["PlyrCreeps", "Player_1"]
    assert doc[1]["spent"] == 2150


def test_objects_groups_by_template(attached, capsys):
    assert cli.main(["objects"]) == 0
    out = capsys.readouterr().out
    assert "GondorFighter" in out
    assert "4 objects, 3 templates" in out


def test_objects_side_filter(attached, capsys):
    assert cli.main(["objects", "--side", "Neutral", "--list"]) == 0
    out = capsys.readouterr().out
    assert "MoriarGoblinLair" in out
    assert "GondorFighter" not in out


def test_side_filter_is_case_insensitive(attached, capsys):
    assert cli.main(["objects", "--side", "men"]) == 0
    assert "GondorFighter" in capsys.readouterr().out


def test_objects_damaged_filter(attached, capsys):
    assert cli.main(["objects", "--damaged", "--list"]) == 0
    out = capsys.readouterr().out
    assert "1 objects" in out, "only the 237/255 fighter is damaged"
    assert "93." in out or "92." in out


def test_objects_list_shows_a_dash_for_bodyless_objects(attached, capsys, monkeypatch):
    def fake_attach(args):
        img = build_game()
        marker_t = img.template("WallHubTemplate", "Neutral")
        marker = img.game_object(marker_t, (1.0, 2.0, 3.0), body=img.body(0.0, 1.8191141e-38))
        img.game_logic(5, [img.entry(1, marker)])
        backend = MemoryBackend(img)
        backend.connect()
        return backend

    monkeypatch.setattr(cli, "_attach", fake_attach)
    assert cli.main(["objects", "--list"]) == 0
    out = capsys.readouterr().out
    assert "WallHubTemplate" in out
    assert "%" not in out, "an object with no body must not display a health percentage"


def test_watch_stops_after_the_requested_frames(attached, capsys, monkeypatch):
    frames = iter([10, 11, 12])

    def fake_step(self, timeout=None):
        try:
            return self.observe().__class__(
                frame=next(frames),
                local_player=2,
                players=self.read_players(),
                objects=self.read_objects(),
            )
        except StopIteration:
            return None

    monkeypatch.setattr(MemoryBackend, "step", fake_step)
    assert cli.main(["watch", "--frames", "3"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 4, "a header plus three frames"


def test_unknown_layout_field_is_rejected(tmp_path):
    bad = tmp_path / "layout.json"
    bad.write_text(json.dumps({"not_a_field": 1}), encoding="utf-8")
    with pytest.raises(SystemExit, match="unknown EngineLayout fields"):
        cli._layout(str(bad))


def test_layout_override_is_applied(tmp_path):
    override = tmp_path / "layout.json"
    override.write_text(json.dumps({"gl_frame": 0x44}), encoding="utf-8")
    layout = cli._layout(str(override))
    assert layout.gl_frame == 0x44
    assert layout.the_game_logic == LAYOUT_ROTWK_201.the_game_logic, "other fields keep defaults"


def test_no_layout_file_means_the_default_build():
    assert cli._layout(None) is LAYOUT_ROTWK_201
