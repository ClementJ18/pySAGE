"""The engine patches Jump To Game needs, put on the install's `game.dat` for the session and taken
off again when the editor closes.

* `command-line-skirmish`: `-file` alone does not set up a match; a stock `game.dat` starts with
  no seats and dies before frame 1 (`sage_patch/docs/game-info.md` §5).
* `mod-load-order`: `-mod` is mounted only after `GameData.ini` is read, so a loaded mod's loose
  `GameData.ini` and the macros it includes would be ignored (`sage_patch/docs/mod-load-order.md`).
* `multi-mod`: only the last `-mod` would count (`sage_patch/docs/multi-mod.md`).

A loaded `.sagepatch` adds the patches its manifest lists, rebuilt with the parameters it records,
so the game runs the binary the mod's INI was written for. An entry naming one of the three above
replaces it, parameters and all.

Jump To Game copies the binary to `game.dat.worldbuilder.bak` and applies whichever of them it
lacks, and the window moves the copy back on close. A later jump builds again from that copy, so
a patch the `.sagepatch` no longer lists does not stay behind.

A note beside the backup records the patched file's hash. It is what makes the restore safe to
retry: a session that crashed, or closed while the game still held the file, is cleaned up the
next time the editor starts, and a `game.dat` something else replaced in the meantime is not
overwritten with the old one.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import struct
from collections.abc import Sequence
from pathlib import Path

from sage_ini.engine import Engine
from sage_patch.patcher import Patch
from sage_patch.patches.experimental.command_line_skirmish import CommandLineSkirmishPatch
from sage_patch.patches.mod_load_order import ModLoadOrderPatch
from sage_patch.patches.multi_mod import MultiModPatch
from sage_patch.sagepatch import rebuild
from sage_worldbuilder.safeio import atomic_write

__all__ = [
    "LAUNCH_PATCHES",
    "LaunchPatchError",
    "backup_path",
    "missing_patches",
    "patch_for_launch",
    "restore_after_launch",
    "restore_pending",
    "sagepatch_patches",
]

#: Applied in this order when missing, with their default parameters.
LAUNCH_PATCHES: tuple[type[Patch], ...] = (
    CommandLineSkirmishPatch,
    ModLoadOrderPatch,
    MultiModPatch,
)

_PATCH_ERRORS = (ValueError, IndexError, struct.error)


class LaunchPatchError(Exception):
    """`game.dat` lacks a patch and could not be given it; the message is worded for the mapper."""


def backup_path(game_dat: Path) -> Path:
    return game_dat.with_name(f"{game_dat.name}.worldbuilder.bak")


def _note_path(game_dat: Path) -> Path:
    return game_dat.with_name(f"{game_dat.name}.worldbuilder.json")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _detected(patch: type[Patch], data: bytes) -> Patch | None:
    try:
        return patch.detect(data)
    except _PATCH_ERRORS:
        return None


def missing_patches(data: bytes) -> list[type[Patch]]:
    """The launch patches `data` does not carry, in the order they are applied."""
    return [patch for patch in LAUNCH_PATCHES if _detected(patch, data) is None]


def sagepatch_patches(engine: Engine) -> list[Patch]:
    """The patches a `.sagepatch` manifest lists, rebuilt with the parameters it records.

    Raises `LaunchPatchError` when an entry cannot be rebuilt: the INI was written for a binary
    carrying it, so a game started without it would not read that INI the way the editor does."""
    patches, problems = rebuild(engine)
    if problems:
        raise LaunchPatchError(
            "The .sagepatch lists patches this version of WorldBuilder cannot build, so the game "
            "would not accept the INI written for them:\n" + "\n".join(problems)
        )
    return patches


def _needed(base: bytes, extra: Sequence[Patch]) -> tuple[list[Patch], list[str]]:
    """The patches `base` lacks - the launch patches, then `extra` - and the `extra` patches it
    already carries built with other parameters, which cannot be put right: a patch is not taken
    off again."""
    extra_names = {patch.name for patch in extra}
    needed: list[Patch] = [
        patch_type()
        for patch_type in LAUNCH_PATCHES
        if patch_type.name not in extra_names and _detected(patch_type, base) is None
    ]
    conflicts: list[str] = []
    for patch in extra:
        carried = _detected(type(patch), base)
        if carried is None:
            needed.append(patch)
        elif carried.options() != patch.options():
            conflicts.append(
                f"{patch.name}: game.dat carries it built with {carried.options()}, the "
                f".sagepatch asks for {patch.options()}"
            )
    return needed, conflicts


def _recorded_hash(game_dat: Path) -> str | None:
    try:
        return json.loads(_note_path(game_dat).read_text(encoding="utf-8"))["patched_sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def patch_for_launch(game_dat: Path, extra: Sequence[Patch] = ()) -> bool:
    """Give `game_dat` every launch patch it lacks, and every `extra` one (a `.sagepatch`'s).

    Returns True when `game_dat` is left patched, with a backup for `restore_after_launch`, and
    False when it needed nothing. Raises `LaunchPatchError` when it can do neither.
    """
    try:
        current = game_dat.read_bytes()
    except OSError as exc:
        raise LaunchPatchError(f"Could not read {game_dat}:\n{exc}") from exc
    backup, note = backup_path(game_dat), _note_path(game_dat)
    # Patched earlier and not restored yet: the backup holds the file from before, which is what
    # this set of patches is built on.
    keep_backup = backup.is_file() and _recorded_hash(game_dat) == _sha256(current)
    try:
        base = backup.read_bytes() if keep_backup else current
    except OSError as exc:
        raise LaunchPatchError(f"Could not read {backup}:\n{exc}") from exc
    missing, conflicts = _needed(base, extra)
    if conflicts:
        raise LaunchPatchError(
            f"{game_dat} already carries patches the .sagepatch lists with other parameters, and "
            "a patch cannot be taken off again - use a game.dat without them, or a .sagepatch "
            "that matches it:\n" + "\n".join(conflicts)
        )
    if not missing:
        if keep_backup:
            # The file from before carries everything now asked for: it is what should run.
            problem = restore_after_launch(game_dat)
            if problem is not None:
                raise LaunchPatchError(problem)
        return False
    names = ", ".join(patch.name for patch in missing)
    patched = bytearray(base)
    problems: list[str] = []
    for patch in missing:
        try:
            patch.apply(patched)
            problems += [f"{patch.name}: {problem}" for problem in patch.verify(patched)]
        except _PATCH_ERRORS as exc:
            problems.append(f"{patch.name}: {exc}")
    if problems:
        raise LaunchPatchError(
            f"{game_dat} lacks patches the game needs to start a map from WorldBuilder ({names}), "
            "and they could not be applied - this is probably not a game.dat they were written "
            "for:\n" + "\n".join(problems)
        )
    if keep_backup and bytes(patched) == current:
        return True
    try:
        if not keep_backup:
            atomic_write(backup, current)
            shutil.copystat(game_dat, backup)
        note_text = json.dumps({"backup": backup.name, "patched_sha256": _sha256(bytes(patched))})
        atomic_write(note, note_text.encode("utf-8"))
        atomic_write(game_dat, bytes(patched))
    except OSError as exc:
        # `game.dat` is untouched when its own write is what failed, so the backup is not needed.
        with contextlib.suppress(OSError):
            if not keep_backup and game_dat.read_bytes() == current:
                note.unlink(missing_ok=True)
                backup.unlink(missing_ok=True)
        raise LaunchPatchError(
            f"Could not apply the patches the game needs to start a map from WorldBuilder "
            f"({names}) to {game_dat}:\n{exc}"
        ) from exc
    return True


def restore_pending(game_dat: Path) -> bool:
    """Whether a backup `patch_for_launch` made is still waiting to be put back."""
    return _note_path(game_dat).is_file()


def restore_after_launch(game_dat: Path) -> str | None:
    """Put back the `game.dat` that `patch_for_launch` replaced.

    Returns None when that is done or there is nothing to do, and otherwise why not, worded for
    the mapper. While `restore_pending` stays True the failure is worth retrying (usually the game
    is still running); once it is False the problem is only something to report.
    """
    note, backup = _note_path(game_dat), backup_path(game_dat)
    if not note.is_file():
        return None
    recorded = _recorded_hash(game_dat)
    try:
        current = game_dat.read_bytes() if game_dat.is_file() else None
        if not backup.is_file():
            note.unlink()
            return None
        if current is not None and _sha256(current) != recorded:
            note.unlink()
            if current == backup.read_bytes():
                # Stopped between writing the backup and patching: nothing was changed.
                backup.unlink()
                return None
            return (
                f"{game_dat} was replaced after WorldBuilder patched it, so it was left as it "
                f"is. The game.dat from before the patch is kept at {backup}."
            )
        os.replace(backup, game_dat)
        note.unlink()
    except OSError as exc:
        return (
            f"Could not put the original {game_dat} back, most likely because the game is still "
            f"running:\n{exc}"
        )
    return None
