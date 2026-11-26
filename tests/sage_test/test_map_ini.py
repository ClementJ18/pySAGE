"""Tests for a scenario's `map.ini`: how it is declared, written beside the map, and checked.

Data-free: nothing here launches a game. What is worth pinning is what the engine would punish
silently or slowly - an override that lands in the wrong place loads nothing, one without a final
line ending loses its last line, and a bare module on an existing Object stops the load on an
error box that a test only sees as a two-minute timeout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_test import Scenario, Seat
from sage_test.run import MapIniError, check_map_ini, write_map_ini

GOOD = """
    Object EntEntling
        AddModule ModuleTag_WallMelee
            Behavior = WeaponSetUpgrade ModuleTag_WallMelee
                TriggeredBy = Upgrade_Test
            End
        End
    End
"""

BARE = """
    Object EntEntling
        Behavior = WeaponSetUpgrade ModuleTag_WallMelee
            TriggeredBy = Upgrade_Test
        End
    End
"""


def _scenario() -> Scenario:
    return Scenario("t", seats=(Seat.human(faction=3),))


def _map_folder(tmp_path: Path) -> Path:
    # Under a `maps` folder, as the generated map is: that is what makes an ini map-scoped.
    folder = tmp_path / "Maps" / "t"
    folder.mkdir(parents=True)
    return folder


class TestOverride:
    def test_a_scenario_has_no_map_ini_by_default(self):
        assert _scenario().map_ini == ""

    def test_the_text_is_dedented(self):
        scenario = _scenario()
        scenario.override(GOOD)
        assert scenario.map_ini.startswith("Object EntEntling\n    AddModule")
        assert scenario.map_ini.endswith("End\n")

    def test_overrides_accumulate(self):
        scenario = _scenario()
        scenario.override("Object A\nEnd")
        scenario.override("Object B\nEnd", "extra.ini")
        assert scenario.map_ini == "Object A\nEnd\n\nObject B\nEnd\n"
        assert scenario.map_ini_includes == ("extra.ini",)

    def test_a_renamed_copy_keeps_the_override(self):
        scenario = _scenario()
        scenario.override(GOOD)
        assert scenario.with_name("t_gw1").map_ini == scenario.map_ini


class TestWrite:
    def test_nothing_is_written_without_an_override(self, tmp_path: Path):
        assert write_map_ini(_scenario(), _map_folder(tmp_path)) is None

    def test_a_stale_override_is_removed(self, tmp_path: Path):
        """A folder kept by `--keep-maps` must not hand its old map.ini to the next run."""
        folder = _map_folder(tmp_path)
        (folder / "map.ini").write_text("Object Old\nEnd\n")
        write_map_ini(_scenario(), folder)
        assert not (folder / "map.ini").exists()

    def test_it_lands_beside_the_map_with_crlf_and_a_final_newline(self, tmp_path: Path):
        scenario = _scenario()
        scenario.override("Object A\nEnd")
        path = write_map_ini(scenario, _map_folder(tmp_path))
        assert path == tmp_path / "Maps" / "t" / "map.ini"
        assert path.read_bytes() == b"Object A\r\nEnd\r\n"

    def test_includes_are_copied_beside_it(self, tmp_path: Path):
        shared = tmp_path / "src" / "_inis"
        shared.mkdir(parents=True)
        (shared / "common.ini").write_text("Object A\nEnd\n")
        single = tmp_path / "src" / "one.ini"
        single.write_text("Object B\nEnd\n")
        scenario = _scenario()
        scenario.override('#include "_inis/common.ini"', shared, single)
        folder = _map_folder(tmp_path)
        write_map_ini(scenario, folder)
        assert (folder / "_inis" / "common.ini").is_file()
        assert (folder / "one.ini").is_file()

    def test_a_missing_include_is_refused(self, tmp_path: Path):
        scenario = _scenario()
        scenario.override("Object A\nEnd", tmp_path / "nowhere.ini")
        with pytest.raises(MapIniError, match="nowhere.ini"):
            write_map_ini(scenario, _map_folder(tmp_path))


class TestCheck:
    def _written(self, tmp_path: Path, text: str) -> Path:
        scenario = _scenario()
        scenario.override(text)
        path = write_map_ini(scenario, _map_folder(tmp_path))
        assert path is not None
        return path

    def test_an_add_module_override_passes(self, tmp_path: Path):
        assert check_map_ini(self._written(tmp_path, GOOD)) == []

    def test_a_bare_module_is_reported(self, tmp_path: Path):
        problems = check_map_ini(self._written(tmp_path, BARE))
        assert len(problems) == 1
        assert "[map-bare-module]" in problems[0]

    def test_a_missing_end_is_reported(self, tmp_path: Path):
        problems = check_map_ini(self._written(tmp_path, "Object EntEntling\n    BuildCost = 5"))
        assert problems
