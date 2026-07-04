"""Unit tests for the corpus scoreboard (sage_ini.stats)."""

from pathlib import Path

from sage_ini.stats import compute_scoreboard, format_scoreboard


def make_mini_corpus(root: Path) -> None:
    (root / "weapon.ini").write_bytes(b"Weapon Sword\nEnd\n")
    (root / "shared.inc").write_bytes(b"#define DMG 10\n")
    (root / "notes.txt").write_bytes(b"not corpus material")


def test_compute_counts_files_and_metrics(tmp_path: Path):
    make_mini_corpus(tmp_path)

    board = compute_scoreboard(tmp_path)

    assert board.total == 2  # .txt excluded
    assert board.suffixes == {".ini": 1, ".inc": 1}
    assert board.encodings == {"utf-8-sig": 2}
    assert board.passed["reads with supported encoding"] == 2


def test_format_reports_rates_and_typed_metrics(tmp_path: Path):
    make_mini_corpus(tmp_path)

    text = format_scoreboard(compute_scoreboard(tmp_path))

    assert "files: 2" in text
    assert "reads with supported encoding: 2/2 (100.0%)" in text
    assert "typed-constructs (roots):" in text
    assert "validates (roots):" in text


def test_empty_directory_formats_without_division_error(tmp_path: Path):
    text = format_scoreboard(compute_scoreboard(tmp_path))

    assert "files: 0" in text
    assert "(0.0%)" in text
