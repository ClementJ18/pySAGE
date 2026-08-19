"""Tests for registry-backed install discovery.

The registry itself is injected, so these run identically on a machine with no games installed
and on a CI box with no registry at all - which is the point: discovery must degrade to "found
nothing" rather than raising, or every tool that calls it breaks off Windows.
"""

from __future__ import annotations

from pathlib import Path

from sage_utils.installs import (
    GAMES,
    Install,
    RegistryKey,
    find_install,
    find_installs,
    registry_reader,
)


def _install(root: Path, name: str = "rotwk") -> Path:
    """A directory that looks like a real install: the marker file has to be there."""
    path = root / name
    path.mkdir(parents=True)
    (path / "game.dat").write_bytes(b"\x00")
    return path


def test_finds_an_install_the_registry_points_at(tmp_path: Path) -> None:
    path = _install(tmp_path)
    found = find_installs(["rotwk"], reader=lambda key: str(path), roots=())
    assert [(i.game, i.path, i.source) for i in found] == [("rotwk", path, "registry")]


def test_ignores_a_registry_path_whose_files_are_gone(tmp_path: Path) -> None:
    """Uninstalling does not reliably clear these keys, so the path alone proves nothing."""
    stale = tmp_path / "uninstalled"
    stale.mkdir()
    assert find_installs(["rotwk"], reader=lambda key: str(stale), roots=()) == ()


def test_ignores_a_directory_without_the_marker(tmp_path: Path) -> None:
    empty = tmp_path / "not-a-game"
    empty.mkdir()
    assert find_installs(["rotwk"], reader=lambda key: str(empty), roots=()) == ()


def test_strips_quotes_the_registry_sometimes_carries(tmp_path: Path) -> None:
    path = _install(tmp_path)
    found = find_installs(["rotwk"], reader=lambda key: f'"{path}"', roots=())
    assert [i.path for i in found] == [path]


def test_deduplicates_a_path_several_keys_agree_on(tmp_path: Path) -> None:
    path = _install(tmp_path)
    found = find_installs(["rotwk"], reader=lambda key: str(path), roots=())
    assert len(found) == 1, "HKLM and HKCU naming the same install is one install"


def test_missing_registry_yields_nothing(tmp_path: Path) -> None:
    assert find_installs(["rotwk"], reader=lambda key: None, roots=()) == ()


def test_find_install_returns_the_first_or_none(tmp_path: Path) -> None:
    assert find_install("rotwk", reader=lambda key: None, roots=()) is None
    path = _install(tmp_path)
    got = find_install("rotwk", reader=lambda key: str(path), roots=())
    assert isinstance(got, Install)
    assert got.path == path


def test_filters_by_game(tmp_path: Path) -> None:
    path = _install(tmp_path)
    assert find_installs(["bfme1"], reader=lambda key: str(path), roots=())[0].game == "bfme1", (
        "the marker is shared, so the filter is what decides which game a hit is reported as"
    )


def test_every_game_declares_markers_and_at_least_one_key() -> None:
    for game in GAMES:
        assert game.markers, f"{game.key} would match any directory"
        assert game.registry, f"{game.key} has no registry key to look in"


def test_registry_reader_survives_a_hive_it_does_not_know() -> None:
    """Never raises: an unreadable key is the same answer as an absent one."""
    assert registry_reader(RegistryKey("NOPE", r"SOFTWARE\nothing")) is None
    assert registry_reader(RegistryKey("HKLM", r"SOFTWARE\pySAGE\definitely-not-here")) is None
