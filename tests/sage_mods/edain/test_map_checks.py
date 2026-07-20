"""The Edain map rules over synthetic maps: findings as sage_ini diagnostics."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sage_ini.parser.diagnostics import Severity  # noqa: E402
from sage_map import Map  # noqa: E402
from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.checks import LintConfig as BaseLintConfig  # noqa: E402
from sage_map.checks import lint_map as run_rules  # noqa: E402
from sage_mods.edain.__main__ import main  # noqa: E402
from sage_mods.edain.map_checks import (  # noqa: E402
    CAMERA_MAX_HEIGHT_TOO_LOW,
    CONTAINS_EXPANSION_FLAG,
    EXCESSIVE_OBJECT_COUNT,
    LOW_EXPANSION_PLOT_FLAG_COUNT,
    MISSING_FARM_TEMPLATE,
    MISSING_GOLLUM_SPAWN_POINT,
    MISSING_GOLLUM_SPAWN_SCRIPT,
    MISSING_PLAYER_TYPES,
    ROTATED_PLOT_FLAG,
    LintConfig,
    lint_map,
)


def _object(type_name, angle=0.0, **props):
    props.setdefault("uniqueID", 1)
    return Object(
        version=1,
        position=(0.0, 0.0, 0.0),
        angle=angle,
        road_type=0,
        type_name=type_name,
        properties={k: {"name": k, "type": None, "value": v} for k, v in props.items()},
        start_pos=0,
        end_pos=0,
    )


def _map(*objects, camera_max_height=None):
    m = Map()
    m.objects_list = ObjectsList(version=1, object_list=list(objects), start_pos=0, end_pos=0)
    world_props = {}
    if camera_max_height is not None:
        world_props["cameraMaxHeight"] = {"name": "cameraMaxHeight", "value": camera_max_height}
    m.world_info = SimpleNamespace(properties=world_props)
    m.sides_list = SimpleNamespace(players=[])
    m.player_scripts_list = SimpleNamespace(script_lists=[])
    m.library_map_lists = SimpleNamespace(lists=[])
    return m


VALIDATION_ONLY = dict(run_flatness=False, run_resources=False, run_performance=False)


def test_validation_findings_and_span():
    m = _map(
        _object("FestungPlotFlag", angle=45.0),
        _object("ExpansionFlag"),
        camera_max_height=300,
    )
    findings = lint_map(m, LintConfig(**VALIDATION_ONLY), path="skirmish.map")

    codes = {d.code for d in findings}
    assert codes == {
        ROTATED_PLOT_FLAG,
        CONTAINS_EXPANSION_FLAG,
        LOW_EXPANSION_PLOT_FLAG_COUNT,
        CAMERA_MAX_HEIGHT_TOO_LOW,
        MISSING_FARM_TEMPLATE,
        MISSING_GOLLUM_SPAWN_POINT,
        MISSING_GOLLUM_SPAWN_SCRIPT,
        MISSING_PLAYER_TYPES,
    }
    assert all(d.span.file == "skirmish.map" for d in findings)

    by_code = {d.code: d for d in findings}
    assert by_code[LOW_EXPANSION_PLOT_FLAG_COUNT].severity is Severity.INFO
    assert by_code[ROTATED_PLOT_FLAG].severity is Severity.ERROR
    assert "FestungPlotFlag" in by_code[ROTATED_PLOT_FLAG].message
    assert by_code[MISSING_PLAYER_TYPES].extra["missing_players"][0] == "SkirmishMen"


def test_exclude_codes_filter():
    m = _map(_object("FestungPlotFlag"))
    config = LintConfig(
        exclude_codes=[LOW_EXPANSION_PLOT_FLAG_COUNT, MISSING_PLAYER_TYPES], **VALIDATION_ONLY
    )
    codes = {d.code for d in lint_map(m, config)}
    assert LOW_EXPANSION_PLOT_FLAG_COUNT not in codes
    assert MISSING_PLAYER_TYPES not in codes
    assert MISSING_FARM_TEMPLATE in codes


def test_performance_rule():
    m = _map(_object("SomeTree"), _object("SomeTree"))
    config = LintConfig(
        run_validation=False, run_flatness=False, run_resources=False, max_recommended_objects=1
    )
    findings = lint_map(m, config)
    assert [d.code for d in findings] == [EXCESSIVE_OBJECT_COUNT]
    assert findings[0].severity is Severity.WARNING
    assert findings[0].extra == {"object_count": 2, "limit": 1}


def test_crashing_rule_becomes_finding():
    def bad_rule(map_obj, config):
        raise ValueError("boom")

    findings = run_rules(_map(), [bad_rule], BaseLintConfig(), path="broken.map")
    assert len(findings) == 1
    assert findings[0].code == "rule-error"
    assert "bad_rule failed: boom" in findings[0].message
    assert findings[0].span.file == "broken.map"


class TestMapChecksCli:
    """`python -m sage_mods.edain lint-maps` is the `sage-lint lint-maps` interface plus the Edain
    MAP-xxx rules: same target/--game/filter surface, driven through the shared runner."""

    _MAPS_DIR = Path(__file__).parents[2] / "sage_map" / "fixtures" / "maps"
    _EDAIN_MAP = _MAPS_DIR / "map edain ford of bruinen.map"

    def test_reports_edain_map_codes_without_a_game(self, capsys):
        # No --game: the game-resolved dangling checks self-skip, but the Edain rules still run and
        # emit their MAP-xxx codes (this Edain skirmish map trips several).
        code = main(
            ["lint-maps", str(self._EDAIN_MAP), "--level", "INFO", "--output-format", "json"]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        codes = {d["code"] for d in payload["diagnostics"]}
        assert any(code.startswith("MAP-") for code in codes)

    def test_select_narrows_to_one_edain_code(self, capsys):
        code = main(
            ["lint-maps", str(self._EDAIN_MAP), "--select", "MAP-013", "--output-format", "json"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert {d["code"] for d in payload["diagnostics"]} == {"MAP-013"}
        assert code == 1

    def test_crawls_a_folder(self, capsys):
        count = len(list(self._MAPS_DIR.glob("*.map")))
        main(["lint-maps", str(self._MAPS_DIR)])
        assert f"across {count} maps" in capsys.readouterr().out

    def test_requires_a_target(self):
        with pytest.raises(SystemExit):
            main(["lint-maps"])

    def test_rejects_a_nonexistent_target(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["lint-maps", str(tmp_path / "nope.map")])
