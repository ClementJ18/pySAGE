"""The data-free halves of a performance run: laying out an army, logging it, and the accelerator
ini a run sets and puts back."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sage_test.accelerator import ACCEL_INI, BACKUP_SUFFIX, accelerator_settings, read_settings
from sage_test.perf import append_row, formation, median_centre

SHIPPED = "; bfme2 accelerator\r\nLogicHz = 6 ; the mod's rate\r\nFpsLimit=60\r\nResetDiag = 0\r\n"


class TestFormation:
    def test_a_small_army_is_the_block_nearest_the_centre(self):
        spots = formation((1000.0, 1000.0, 0.0), 4, columns=10, rows=8, spacing=100.0)
        assert len(spots) == 4
        assert all(abs(x - 1000.0) <= 100.0 and abs(y - 1000.0) <= 100.0 for x, y, _ in spots)

    def test_more_objects_than_spots_is_refused(self):
        with pytest.raises(ValueError, match="81 objects for 80 spots"):
            formation((0.0, 0.0, 0.0), 81, columns=10, rows=8, spacing=100.0)


def test_the_median_centre_ignores_stragglers_and_keeps_height():
    bulk = [(100.0, 100.0, 50.0), (110.0, 100.0, 50.0), (105.0, 105.0, 52.0)]
    straggler = (3000.0, 3000.0, 0.0)
    assert median_centre([*bulk, straggler]) == (107.5, 102.5, 50.0)


def test_rows_append_as_json_lines(tmp_path: Path):
    log = tmp_path / "perf" / "run.jsonl"
    append_row(log, {"hordes": 70})
    append_row(log, {"hordes": 140})
    assert [json.loads(line)["hordes"] for line in log.read_text().splitlines()] == [70, 140]


def test_read_settings_drops_inline_comments_and_matches_any_case(tmp_path: Path):
    ini = tmp_path / ACCEL_INI
    ini.write_bytes(SHIPPED.encode())
    assert read_settings(ini, ("logichz", "FpsLimit", "Missing")) == {
        "logichz": "6",
        "FpsLimit": "60",
    }
    assert read_settings(tmp_path / "absent.ini", ("LogicHz",)) == {}


class TestAcceleratorSettings:
    def test_the_settings_hold_for_the_block_and_the_file_comes_back(self, tmp_path: Path):
        ini = tmp_path / ACCEL_INI
        ini.write_bytes(SHIPPED.encode())
        with accelerator_settings(tmp_path, {"ResetDiag": "1", "TextureCache": "0"}) as path:
            assert path == ini
            assert read_settings(ini, ("ResetDiag", "TextureCache", "LogicHz")) == {
                "ResetDiag": "1",
                "TextureCache": "0",
                "LogicHz": "6",
            }
        assert ini.read_bytes() == SHIPPED.encode()
        assert not (tmp_path / f"{ACCEL_INI}{BACKUP_SUFFIX}").exists()

    def test_a_killed_run_is_repaired_by_the_next(self, tmp_path: Path):
        """A run killed inside the block leaves its copy behind; the next one puts it back
        before taking its own, so it never mistakes a modified file for the original."""
        ini = tmp_path / ACCEL_INI
        ini.write_bytes(SHIPPED.encode())
        backup = tmp_path / f"{ACCEL_INI}{BACKUP_SUFFIX}"
        shutil.copy2(ini, backup)
        ini.write_text("ResetDiag = 1\n")
        with accelerator_settings(tmp_path, {"FpsLimit": "30"}):
            assert read_settings(ini, ("ResetDiag", "FpsLimit")) == {
                "ResetDiag": "0",
                "FpsLimit": "30",
            }
        assert ini.read_bytes() == SHIPPED.encode()

    def test_without_the_accelerator_nothing_is_written(self, tmp_path: Path):
        with accelerator_settings(tmp_path, {"LogicHz": "5"}) as path:
            assert path is None
        assert list(tmp_path.iterdir()) == []
