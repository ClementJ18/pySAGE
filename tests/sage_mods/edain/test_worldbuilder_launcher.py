"""Tests for the Worldbuilder launcher.

Two things here are worth more than the rest. The **argument order** - a map has to precede
`-mod`, or MFC claims the mod path as a document and the editor never starts - and **staging
cleanup**, which deletes a tree full of junctions that point into the user's real mod. Getting
the second wrong destroys mod source, so it is tested for what it must *not* do.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sage_mods.edain.worldbuilder import (
    _remove_staging,
    build_command,
    find_map,
    resolve_root,
    staging_plan,
)
from sage_patch.patches.worldbuilder_mod import MAX_MOD_PATH_CHARS


def test_map_precedes_mod_in_the_command() -> None:
    command = build_command(Path("wb.exe"), Path("a.map"), Path("D:/served"))
    assert command[1] == str(Path("a.map"))
    assert command[2] == "-mod"
    assert command.index("-mod") > 1, "a bare mod path first is what MFC opens as a document"


def test_refuses_a_served_path_the_patch_would_ignore() -> None:
    long_path = Path("D:/" + "x" * MAX_MOD_PATH_CHARS)
    with pytest.raises(SystemExit, match="characters"):
        build_command(Path("wb.exe"), Path("a.map"), long_path)


def test_staging_plan_mirrors_the_relative_path() -> None:
    plan = staging_plan(Path("D:/mod"), Path("D:/stage"), ["data/ini/object"])
    assert plan == [(Path("D:/stage/data/ini/object"), Path("D:/mod/data/ini/object"))]


@pytest.mark.parametrize("bad", ["../outside", "C:/absolute", "data/../../escape"])
def test_staging_plan_rejects_paths_that_leave_the_mod(bad: str) -> None:
    with pytest.raises(ValueError, match="inside the mod"):
        staging_plan(Path("D:/mod"), Path("D:/stage"), [bad])


def test_resolve_root_prefers_an_explicit_root(tmp_path: Path) -> None:
    assert resolve_root(tmp_path) == tmp_path.resolve()


def test_find_map_picks_one_when_not_told(tmp_path: Path) -> None:
    (tmp_path / "maps" / "aldburg").mkdir(parents=True)
    made = tmp_path / "maps" / "aldburg" / "aldburg.map"
    made.write_bytes(b"")
    assert find_map(tmp_path, None) == made.resolve()


def test_find_map_explains_itself_when_there_is_none(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Worldbuilder needs one"):
        find_map(tmp_path, None)


def test_find_map_resolves_a_bare_map_name(tmp_path: Path) -> None:
    (tmp_path / "maps" / "luhn").mkdir(parents=True)
    made = tmp_path / "maps" / "luhn" / "luhn.map"
    made.write_bytes(b"")
    assert find_map(tmp_path, "luhn") == made.resolve()


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows thing")
def test_removing_staging_never_deletes_through_a_junction(tmp_path: Path) -> None:
    """The one that matters: staging is junctions into real mod source.

    `shutil.rmtree` walks into a junction on Windows and deletes the target's contents. If
    cleanup ever regresses to that, this test loses `precious.ini` - which is exactly the mod
    file a user would lose.
    """
    real = tmp_path / "mod" / "data"
    real.mkdir(parents=True)
    precious = real / "precious.ini"
    precious.write_text("Object BARK\nEnd\n")

    staging = tmp_path / "stage"
    (staging / "data").parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir(exist_ok=True)
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(staging / "data"), str(real)],
        capture_output=True,
        check=True,
    )
    assert (staging / "data" / "precious.ini").is_file(), "junction did not take"

    _remove_staging(staging)

    assert not staging.exists()
    assert precious.is_file(), "cleanup followed the junction and ate real mod source"
    assert precious.read_text() == "Object BARK\nEnd\n"
