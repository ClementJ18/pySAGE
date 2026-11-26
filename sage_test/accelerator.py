"""Run a game with some `bfme2_accel.ini` settings, then put the installed file back.

The BFME2 accelerator (`d3d9.dll` beside `game.dat`) reads its ini once, at startup, so a setting -
its logic rate, its frame cap, a diagnostic switch - is fixed for the life of the process, the
way an `Options.ini` preference is (`sage_test.options`). A test that compares a run with the
accelerator's pacing against one without, or turns a diagnostic on, sets them here around the
launch.

**The installed file is restored from a copy on disk**, not from memory, because a run that is
killed - a timed-out test, a closed terminal - never reaches its `finally`. The copy sits beside
the ini, and the next override finds it and puts it back before doing anything else, so one killed
run cannot leave the next one starting from a modified file it then treats as the original.
"""

from __future__ import annotations

import shutil
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from sage_test.options import apply_options

__all__ = ["ACCEL_INI", "BACKUP_SUFFIX", "accelerator_settings", "read_settings"]

ACCEL_INI = "bfme2_accel.ini"
#: What the installed ini is kept as while a test runs with its own settings.
BACKUP_SUFFIX = ".sage-test-keep"


def read_settings(path: Path, keys: Collection[str]) -> dict[str, str]:
    """`keys` as `path` sets them, inline `;` comments dropped; empty when the file is not there.
    Keys match case-insensitively, as `apply_options` does, and are returned as asked for."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    wanted = {key.lower(): key for key in keys}
    found: dict[str, str] = {}
    for line in lines:
        if "=" not in line or line.lstrip().startswith(";"):
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key.lower() in wanted:
            found[wanted[key.lower()]] = value.split(";", 1)[0].strip()
    return found


def _restore(ini: Path, backup: Path) -> None:
    if backup.exists():
        shutil.move(backup, ini)


@contextmanager
def accelerator_settings(install: Path, settings: Mapping[str, str]) -> Iterator[Path | None]:
    """Set `settings` in the install's accelerator ini for the block; yields the ini's path, or
    None - changing nothing - when the accelerator is not installed.

    Put the launch inside the `with`: the accelerator reads its ini when the game starts.
    """
    ini = install / ACCEL_INI
    backup = install / f"{ACCEL_INI}{BACKUP_SUFFIX}"
    _restore(ini, backup)
    if not ini.exists():
        yield None
        return
    shutil.copy2(ini, backup)
    try:
        text = ini.read_bytes().decode("utf-8", errors="replace")
        ini.write_bytes(apply_options(text, settings).encode("utf-8"))
        yield ini
    finally:
        _restore(ini, backup)
