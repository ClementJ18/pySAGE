"""`to-xml` resolving a `.const` (or the `.apt`) out of a `.big` archive.

Mirrors the game's load order — loose file beside the `.apt` first, then the same
basename fished out of a `.big` under `--game-dir`. Needs the optional `[apt]` extra
(pyBIG); skipped cleanly when it isn't installed."""

import shutil
from pathlib import Path

import pytest

from sage_apt import apt_to_xml

pytest.importorskip("pyBIG", reason="the [apt] extra (pyBIG) is not installed")
from pyBIG import Archive  # noqa: E402 — after the importorskip guard

FIXTURES = Path(__file__).parent / "fixtures"


def _write_big(path: Path, members: dict[str, bytes]) -> None:
    archive = Archive.empty()
    for name, data in members.items():
        archive.add_file(name, data)
    archive.save(str(path))


def test_const_resolved_from_big(tmp_path):
    """A loose `.apt` whose `.const` only lives inside a `.big` still decompiles."""
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")

    game_dir = tmp_path / "game"
    game_dir.mkdir()
    _write_big(
        game_dir / "art.big",
        {r"data\apt\SpellStore.const": (FIXTURES / "SpellStore.const").read_bytes()},
    )

    xml_path = apt_to_xml(tmp_path / "SpellStore.apt", game_dir=game_dir)
    assert xml_path == tmp_path / "SpellStore.xml"
    assert xml_path.read_bytes()


def test_apt_and_const_both_from_big(tmp_path):
    """Neither loose file present: both halves come out of the `.big`."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    _write_big(
        game_dir / "menus.big",
        {
            r"data\apt\SpellStore.apt": (FIXTURES / "SpellStore.apt").read_bytes(),
            r"data\apt\SpellStore.const": (FIXTURES / "SpellStore.const").read_bytes(),
        },
    )

    xml_path = apt_to_xml(tmp_path / "SpellStore.apt", game_dir=game_dir)
    assert xml_path.read_bytes()


def test_loose_const_wins_over_big(tmp_path):
    """A loose `.const` beside the `.apt` is preferred over a packed one."""
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")
    shutil.copy(FIXTURES / "SpellStore.const", tmp_path / "SpellStore.const")

    game_dir = tmp_path / "game"
    game_dir.mkdir()
    _write_big(game_dir / "art.big", {r"data\apt\SpellStore.const": b"not a real const"})

    # If the packed junk .const were used the decompile would fail; the loose one wins.
    assert apt_to_xml(tmp_path / "SpellStore.apt", game_dir=game_dir).read_bytes()
