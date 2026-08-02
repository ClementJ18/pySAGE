"""Tests for linting against a patched engine: how a run finds its `.sagepatch`, and what
changes in the report once it has one.

The point of the feature is that a mod built for a patched `game.dat` stops being told its own
data is wrong, so these check the two directions that matter - the patched field is accepted with
the engine and still reported without it - and that the ceilings the rules enforce move with the
engine rather than being baked in.
"""

import json

import pytest

from sage_lint.cli import main
from sage_lint.commands.common import project_engine
from sage_lint.config import load_config

# A `SpecialPower` using the field the hero-mana patch adds: unknown on a stock engine.
_POWER = "SpecialPower Test\n    ManaCost = 5\nEnd\n"

_SAGEPATCH = (
    "version = 1\n"
    "[[fields]]\n"
    'block = "SpecialPower"\n'
    'name = "ManaCost"\n'
    'type = "Int"\n'
    "default = 0\n"
    'patch = "hero-mana"\n'
)


def _codes(capsys, tmp_path, *extra: str) -> list[str]:
    """Lint `tmp_path` as JSON and return the codes reported. `unused-definition` is silenced
    throughout: these fixtures are one definition nothing else names, which is the point of the
    fixture and nothing to do with the engine."""
    argv = ["lint", str(tmp_path), "--output-format", "json", "--ignore", "unused-definition"]
    assert main([*argv, *extra]) in (0, 1)
    return [item["code"] for item in json.loads(capsys.readouterr().out)["diagnostics"]]


@pytest.fixture
def project(tmp_path):
    (tmp_path / "power.ini").write_text(_POWER, encoding="utf-8")
    return tmp_path


class TestDiscovery:
    def test_a_sagepatch_beside_the_config_is_found_with_no_configuration(self, tmp_path):
        (tmp_path / ".sagepatch").write_text(_SAGEPATCH, encoding="utf-8")
        args = type("Args", (), {"engine": None, "no_engine": False})()
        engine = project_engine(args, load_config(tmp_path), tmp_path)

        assert engine is not None
        assert engine.fields[0].name == "ManaCost"

    def test_the_config_key_points_elsewhere(self, tmp_path):
        (tmp_path / "engine").mkdir()
        (tmp_path / "engine" / "rotwk.sagepatch").write_text(_SAGEPATCH, encoding="utf-8")
        (tmp_path / ".sagelint").write_text('sagepatch = "engine/rotwk.sagepatch"\n', "utf-8")
        args = type("Args", (), {"engine": None, "no_engine": False})()
        engine = project_engine(args, load_config(tmp_path), tmp_path)

        assert engine is not None and engine.fields[0].name == "ManaCost"

    def test_no_sagepatch_anywhere_is_the_stock_engine(self, tmp_path):
        args = type("Args", (), {"engine": None, "no_engine": False})()

        assert project_engine(args, load_config(tmp_path), tmp_path) is None

    def test_a_bad_path_in_the_config_is_a_warning_not_a_crash(self, tmp_path):
        (tmp_path / ".sagelint").write_text("sagepatch = 12\n", encoding="utf-8")
        config = load_config(tmp_path)

        assert config.sagepatch is None
        assert any("sagepatch" in warning for warning in config.warnings)


class TestReport:
    def test_a_patched_field_is_unknown_without_the_engine(self, project, capsys):
        assert "unknown-attribute" in _codes(capsys, project)

    def test_the_engine_makes_it_a_known_field(self, project, capsys):
        (project / ".sagepatch").write_text(_SAGEPATCH, encoding="utf-8")

        assert _codes(capsys, project) == []

    def test_no_engine_lints_against_the_stock_engine_anyway(self, project, capsys):
        (project / ".sagepatch").write_text(_SAGEPATCH, encoding="utf-8")

        assert "unknown-attribute" in _codes(capsys, project, "--no-engine")

    def test_a_retired_field_is_reported_as_doing_nothing(self, tmp_path, capsys):
        (tmp_path / "power.ini").write_text("SpecialPower Test\n    UnitCost = 5\nEnd\n", "utf-8")
        (tmp_path / ".sagepatch").write_text(
            "version = 1\n[[noops]]\n"
            'block = "SpecialPower"\nname = "UnitCost"\n'
            'reason = "replaced by ManaCost"\npatch = "hero-mana"\n',
            encoding="utf-8",
        )

        assert _codes(capsys, tmp_path) == ["patched-out-field"]

    def test_a_malformed_sagepatch_is_reported_and_the_lint_still_runs(self, project, capsys):
        (project / ".sagepatch").write_text("= = =\n", encoding="utf-8")
        codes = _codes(capsys, project)

        assert "engine-config" in codes
        assert "unknown-attribute" in codes  # the stock schema still linted the file


class TestEngineLimits:
    """The CommandSet ceilings are engine facts, so a raised limit has to move them - and the
    display ceiling, which no patch raises, has to stay put."""

    _SET = (
        "CommandSet TestSet\n"
        + "".join(f"    {slot} = Command_X\n" for slot in range(1, 41))
        + "End\n"
        "CommandButton Command_X\n    Command = PUSH_VISIBLE_COMMAND_RANGE\n"
        "    CommandRangeStart = 0\n    CommandRangeCount = 50\nEnd\n"
    )

    def test_a_window_past_the_stock_array_is_an_error(self, tmp_path, capsys):
        (tmp_path / "set.ini").write_text(self._SET, encoding="utf-8")
        assert main(["lint", str(tmp_path), "--output-format", "json"]) == 1
        reported = json.loads(capsys.readouterr().out)["diagnostics"]
        overflow = [d for d in reported if d["code"] == "command-range-overflow"]

        assert overflow and overflow[0]["severity"] == "error"
        assert "33-slot" in overflow[0]["message"]

    def test_the_raised_limit_makes_the_same_window_a_warning(self, tmp_path, capsys):
        (tmp_path / "set.ini").write_text(self._SET, encoding="utf-8")
        (tmp_path / ".sagepatch").write_text(
            'version = 1\n[[limits]]\nname = "commandset.max_slots"\nvalue = 64\n'
            'patch = "commandset-limit"\n',
            encoding="utf-8",
        )
        main(["lint", str(tmp_path), "--output-format", "json"])
        reported = json.loads(capsys.readouterr().out)["diagnostics"]
        overflow = [d for d in reported if d["code"] == "command-range-overflow"]

        assert overflow and overflow[0]["severity"] == "warning"

    def test_a_sagepatch_that_was_asked_for_and_is_missing_warns(self, tmp_path, capsys):
        args = type("Args", (), {"engine": tmp_path / "gone.sagepatch", "no_engine": False})()

        assert project_engine(args, load_config(tmp_path), tmp_path) is None
        assert "no .sagepatch" in capsys.readouterr().err
