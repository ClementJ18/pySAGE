r"""Launch Worldbuilder against a mod's loose files, without building a `.big`.

Sits next to the mod folder - the built exe is meant to live in `Edain-Mod\`, one level above the
`_mod` directory it serves - and does the three things a bare `-mod` invocation gets wrong:

**It finds the game.** Via :mod:`sage_utils.installs`, which reads the install path out of the
registry rather than hardcoding anyone's drive layout. ``--game`` overrides it.

**It puts a map before `-mod`.** Worldbuilder is an MFC application whose `CCommandLineInfo`
claims the first non-flag argument as a document to open. A bare mod path lands there and the
editor dies with `Access to … was denied` before it starts. A real map in front of it takes that
slot, and the mod path is then discarded by MFC while the engine still reads it. See
``sage_patch/docs/worldbuilder-mod.md`` §3.

**It serves a subtree, not the whole mod.** `-mod` pointed at a full Edain tree kills the editor
partway through startup; pointed at the subtree being edited it is stable. So the launcher stages
a directory holding only the requested subtrees, as junctions back into the real mod, and points
`-mod` at that. Editing still happens in the real files - the staging directory is a view, not a
copy.

Serve a **self-contained** subtree. The mod directory shadows an archive file by whole path and
its files are parsed before the archive's, so a served file that drops a definition its stale
neighbours still reference - or that redefines a name an unshadowed archive file also defines -
kills the editor. Narrow is safer than wide, but coherent matters more than small: see
``sage_patch/docs/worldbuilder-mod.md`` §8 for the three mechanisms and how they were measured.

**It patches the editor if nobody has.** `-mod` only reaches Worldbuilder's engine through
`sage_patch`'s `worldbuilder-mod`; an unpatched editor ignores the switch entirely and shows the
shipped data with no sign anything was wrong, which looks exactly like a mod that failed to load.
So the launcher checks the installed binary and installs the patch if it is missing, keeping the
stock one beside it first.

    python -m sage_mods.edain.worldbuilder --subtree data/ini/object/civilian
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path, PureWindowsPath

from sage_patch.patches.worldbuilder_mod import MAX_MOD_PATH_CHARS, WorldbuilderModPatch
from sage_utils.installs import find_install

__all__ = [
    "BACKUP_NAME",
    "DEFAULT_STAGING",
    "MOD_DIR_NAME",
    "build_command",
    "ensure_patched",
    "main",
    "resolve_root",
    "stage",
    "staging_plan",
]

#: The stock editor is kept under this name before the patch is written over the original, so
#: reverting is a rename and never needs this repo.
BACKUP_NAME = "Worldbuilder_stock.exe"

#: The mod directory, relative to the root this launcher sits in.
MOD_DIR_NAME = "_mod"

#: Where the served view is staged. Kept short and beside the mod rather than under the temp
#: directory because the whole path is handed to `-mod`, which the patch caps at
#: `MAX_MOD_PATH_CHARS` - a temp path alone can eat that budget.
DEFAULT_STAGING = "_wbmod"

WORLDBUILDER_EXE = "Worldbuilder.exe"


def resolve_root(explicit: str | Path | None = None) -> Path:
    """The folder holding `_mod`.

    Frozen, that is the folder the exe sits in, which is the whole point of shipping it beside
    the mod. Run from source it falls back to the current directory, so ``--root`` is the way to
    be explicit either way."""
    if explicit is not None:
        return Path(explicit).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def _is_junction(path: Path) -> bool:
    """Whether ``path`` is a junction or symlink rather than a real directory.

    This is the guard that makes cleanup safe: the staging tree is mostly links *into the user's
    mod*, and removing one by recursing through it would delete their actual data."""
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction(path)) if isjunction is not None else False


def _remove_staging(path: Path) -> None:
    """Delete a staging tree without ever following a link out of it.

    Deliberately not `shutil.rmtree`: on Windows that walks *into* a junction and deletes the
    target's contents, and every junction here points at real mod source."""
    if not path.exists():
        return
    if _is_junction(path):
        path.rmdir()  # removes the link, never what it points at
        return
    for child in path.iterdir():
        if child.is_dir():
            _remove_staging(child)
        else:
            child.unlink()
    path.rmdir()


def staging_plan(mod: Path, staging: Path, subtrees: Iterable[str]) -> list[tuple[Path, Path]]:
    """The ``(link, target)`` pairs that mirror ``subtrees`` from ``mod`` into ``staging``.

    Each subtree keeps its path relative to the mod root, because that relative path is exactly
    what the engine asks the file system for."""
    plan: list[tuple[Path, Path]] = []
    for subtree in subtrees:
        # Judged as a Windows path whatever the host runs: these are mod paths, and only
        # PureWindowsPath reads the drive letter in "C:/x" as absolute.
        windows = PureWindowsPath(subtree)
        if windows.drive or windows.root or ".." in windows.parts:
            raise ValueError(f"{subtree!r} must be a path inside the mod, relative to it")
        relative = Path(subtree.replace("\\", "/"))
        plan.append((staging / relative, mod / relative))
    return plan


def stage(mod: Path, staging: Path, subtrees: Sequence[str]) -> Path:
    """Rebuild ``staging`` so it exposes only ``subtrees`` of ``mod``, and return it."""
    plan = staging_plan(mod, staging, subtrees)
    for _link, target in plan:
        if not target.exists():
            raise SystemExit(f"{target} does not exist - nothing to serve for that subtree")

    _remove_staging(staging)
    staging.mkdir(parents=True)
    for link, target in plan:
        link.parent.mkdir(parents=True, exist_ok=True)
        # A junction, not a copy, so edits land in the real mod; and not a symlink, because those
        # need developer mode or elevation on Windows while junctions do not.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"could not link {link} -> {target}: {result.stdout}{result.stderr}")
    return staging


def find_map(mod: Path, explicit: str | None) -> Path:
    """The map to open. Any map will do - it exists to occupy MFC's document slot."""
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            for guess in (mod / candidate, mod / "maps" / candidate / f"{candidate}.map"):
                if guess.is_file():
                    return guess.resolve()
        if candidate.is_file():
            return candidate.resolve()
        raise SystemExit(f"map not found: {explicit}")
    found = next(iter(sorted((mod / "maps").glob("*/*.map"))), None)
    if found is None:
        raise SystemExit(
            f"no map found under {mod / 'maps'}; pass --map, since Worldbuilder needs one "
            "ahead of -mod or MFC claims the mod path as a document to open"
        )
    return found.resolve()


def ensure_patched(worldbuilder: Path, backup_name: str = BACKUP_NAME) -> str:
    """Install `worldbuilder-mod` into ``worldbuilder`` unless it is already there.

    The stock binary is copied aside *before* anything is written, and the patched image is
    verified in memory before it replaces the original - so a build this patch does not recognise
    leaves the install untouched rather than half-written."""
    data = worldbuilder.read_bytes()
    if WorldbuilderModPatch.detect(data) is not None:
        return "already patched"

    backup = worldbuilder.with_name(backup_name)
    if not backup.exists():
        backup.write_bytes(data)

    patched = bytearray(data)
    WorldbuilderModPatch().apply(patched)
    problems = WorldbuilderModPatch().verify(patched)
    if problems:
        raise SystemExit(
            "refusing to install, the patched image does not verify:\n  " + "\n  ".join(problems)
        )
    try:
        worldbuilder.write_bytes(patched)
    except PermissionError as exc:
        raise SystemExit(
            f"cannot write {worldbuilder}: {exc}. Close Worldbuilder if it is running, and note "
            "that an install under Program Files needs this to run as administrator"
        ) from exc
    return f"patched (stock kept as {backup.name})"


def build_command(worldbuilder: Path, map_path: Path, served: Path) -> list[str]:
    """The argument vector. **The map must precede `-mod`** - see the module docstring."""
    if len(str(served)) >= MAX_MOD_PATH_CHARS:
        raise SystemExit(
            f"the served path is {len(str(served))} characters; the patch ignores anything at or "
            f"over {MAX_MOD_PATH_CHARS}. Use --staging to put it somewhere shorter"
        )
    return [str(worldbuilder), str(map_path), "-mod", str(served)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="edain-worldbuilder",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", help=f"folder holding {MOD_DIR_NAME} (default: this exe's own)")
    parser.add_argument("--game", help="RotWK install (default: found in the registry)")
    parser.add_argument("--map", help="map to open; any will do (default: the first one found)")
    parser.add_argument(
        "--subtree",
        action="append",
        default=[],
        metavar="REL",
        help=(
            "mod-relative subtree to serve, repeatable, e.g. data/ini/object/civilian. "
            "Serve the narrowest thing you are editing"
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "serve the whole mod. Known to kill the editor partway through startup, and not "
            "yet explained - the tree itself is consistent, the installed archives under it "
            "are not"
        ),
    )
    parser.add_argument("--staging", default=DEFAULT_STAGING, help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-patch",
        action="store_true",
        help="do not install worldbuilder-mod if the editor is missing it",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the command, do not run it")
    args = parser.parse_args(argv)

    root = resolve_root(args.root)
    mod = root / MOD_DIR_NAME
    if not mod.is_dir():
        raise SystemExit(f"no {MOD_DIR_NAME} directory in {root} - is this the mod folder?")

    if args.game:
        game = Path(args.game)
    else:
        install = find_install("rotwk")
        if install is None:
            raise SystemExit("no RotWK install found in the registry - pass --game")
        game = install.path
    worldbuilder = game / WORLDBUILDER_EXE
    if not worldbuilder.is_file():
        raise SystemExit(f"{worldbuilder} not found")

    if args.full:
        served = mod
        print("serving the whole mod; the editor is known to die partway through startup")
    elif args.subtree:
        served = stage(mod, root / args.staging, args.subtree)
    else:
        parser.error(
            "nothing to serve: pass --subtree (repeatable), e.g.\n"
            "  --subtree data/ini/object/civilian\n"
            "or --full to serve the whole mod, which is known to kill the editor"
        )

    patch_state = "skipped (--no-patch)" if args.no_patch else ensure_patched(worldbuilder)

    command = build_command(worldbuilder, find_map(mod, args.map), served)
    print("  game :", game)
    print("  patch:", patch_state)
    print("  map  :", command[1])
    print("  -mod :", served)
    if args.dry_run:
        print("\n" + subprocess.list2cmdline(command))
        return 0
    subprocess.Popen(command, cwd=str(game), close_fds=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
