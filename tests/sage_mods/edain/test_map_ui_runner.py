"""The map-check window's Qt-free runner: crawl folders/files for maps and produce the
CLI-shaped report in-process (game loaded once for the whole batch)."""

from pathlib import Path

from sage_mods.edain.map_checks.ui.runner import crawl_maps, run_check  # noqa: E402

# The shared map fixtures (see tests/sage_lint's TestLintMaps).
MAPS_DIR = Path(__file__).parents[2] / "sage_map" / "fixtures" / "maps"
LOOSE_MAP = MAPS_DIR / "map edain ford of bruinen.map"


class TestCrawlMaps:
    def test_folder_is_crawled_and_file_taken_as_is(self):
        count = len(list(MAPS_DIR.glob("*.map")))
        assert len(crawl_maps([MAPS_DIR])) == count
        assert crawl_maps([LOOSE_MAP]) == [LOOSE_MAP]

    def test_duplicates_are_kept_once(self):
        # The loose file is also under the folder; naming both keeps one copy.
        found = crawl_maps([LOOSE_MAP, MAPS_DIR])
        assert len(found) == len(list(MAPS_DIR.glob("*.map")))
        assert sum(1 for p in found if p.resolve() == LOOSE_MAP.resolve()) == 1

    def test_non_map_files_in_folder_are_ignored(self):
        # The fixtures folder also holds .bse layouts; only *.map is picked up.
        assert all(p.suffix == ".map" for p in crawl_maps([MAPS_DIR]))


class TestRunCheck:
    def test_report_has_the_cli_shape_plus_map_count(self):
        report = run_check([LOOSE_MAP])
        assert set(report) == {"diagnostics", "summary", "maps"}
        assert report["maps"] == 1
        assert set(report["summary"]) == {"errors", "warnings", "hidden"}
        for diag in report["diagnostics"]:
            assert {"code", "severity", "message", "file"} <= set(diag)

    def test_progress_reports_one_line_per_map(self):
        lines: list[str] = []
        run_check([LOOSE_MAP], progress=lines.append)
        assert lines == [f"Checking map 1/1: {LOOSE_MAP.name}"]

    def test_a_bad_binary_map_becomes_one_parse_error(self, tmp_path):
        bad = tmp_path / "broken.map"
        bad.write_bytes(b"not a real map")
        report = run_check([bad, LOOSE_MAP])
        parse_errors = [
            d
            for d in report["diagnostics"]
            if d["code"] == "map-parse-error" and d["file"] == str(bad)
        ]
        assert len(parse_errors) == 1
        assert report["maps"] == 2

    def test_game_enables_the_object_resolution_check(self, tmp_path):
        # With a game loaded, placed objects resolve against it: a root defining only one
        # object flags the fixture's other placed types as dangling (mirrors the CLI test).
        (tmp_path / "a.ini").write_text("Object Foo\n    BuildCost = 1\nEnd\n", encoding="utf-8")
        report = run_check([LOOSE_MAP], games=[tmp_path])
        assert any(d["code"] == "map-dangling-object" for d in report["diagnostics"])

    def test_level_hides_lower_severities(self):
        everything = run_check([MAPS_DIR], level="INFO")
        errors_only = run_check([MAPS_DIR], level="ERROR")
        assert errors_only["summary"]["hidden"] >= everything["summary"]["hidden"]
        assert all(d["severity"] == "error" for d in errors_only["diagnostics"])
