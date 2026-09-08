"""Getting a compiled scenario onto disk and a game started on it.

Two things this has to get right, both of them the engine's rules rather than ours.

**Where a generated map goes.** RotWK scans `<user files>\\Maps` - `My Rise of the Witch-king
Files`, *not* the BFME2 folder next to it - and keys what it finds there by **absolute** path,
lowercased, while maps inside the `.big` archives are keyed relatively as `maps\\…`. A generated
map therefore lives at `<user files>\\Maps\\<name>\\<name>.map`, the one-folder-per-map layout
the editor uses.

**What to pass to `-file`.** The engine's path builder inserts the file's own stem as a
directory (`sage_patch/docs/game-info.md` §1), so the argument names the *parent* of the folder:
`<user files>\\Maps\\<name>.map` becomes `<user files>\\maps\\<name>\\<name>.map`, which is the
cache key. Passing the path that actually exists produces the folder twice and the lookup misses
- silently, and the game then dies several seconds later somewhere unrelated.

Nothing here starts a game by itself on import, and every path is resolved at call time, so this
module is importable on a machine with no install.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "USER_FILES",
    "GameProcess",
    "InstalledMap",
    "install_map",
    "install_map_folder",
    "launch",
    "launch_arguments",
    "user_files_dir",
]

#: The RotWK user-files folder, relative to the roaming profile. Its BFME2 sibling
#: ("My Battle for Middle-earth(tm) II Files") is a different game's and is not scanned.
USER_FILES = "My Rise of the Witch-king Files"


def user_files_dir(override: str | os.PathLike[str] | None = None) -> Path:
    """Where the game keeps maps, replays and saves."""
    if override is not None:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is unset; pass an explicit user-files directory")
    return Path(appdata) / USER_FILES


def install_map(name: str, data: bytes, user_files: Path | None = None) -> tuple[Path, str]:
    """Write a compiled map into the game's map folder.

    Returns the path written and the **`-file` argument** to launch it with, which is not that
    path: it names the parent folder, because the engine appends the stem itself.
    """
    root = (user_files or user_files_dir()) / "Maps" / name
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.map"
    path.write_bytes(data)
    # Lowercased because the map cache is keyed lowercase and the lookup is a plain std::map
    # comparison - a capital letter here is a miss, not a near-miss.
    return path, str(root.parent / f"{name}.map").lower()


@dataclass(frozen=True)
class InstalledMap:
    """A map copied into the user files, and what it takes to start it and undo it."""

    path: Path
    argument: str
    #: Everything the install created, for the caller to remove afterwards. A folder that was
    #: already there is not in here and is not ours to delete.
    created: tuple[Path, ...] = ()


def install_map_folder(
    source: str | os.PathLike[str],
    *,
    name: str | None = None,
    extras: tuple[str | os.PathLike[str], ...] = (),
    user_files: Path | None = None,
) -> InstalledMap:
    """Copy a map's whole folder into the user files, so the engine will cache it as a user map.

    **Why copy a map that already exists.** `-file` starts a *cache entry*, and the entry for a
    map inside a mod's archives comes from that mod's hand-written `maps\\mapcache.ini`, flags and
    all. An entry flagged `isMultiplayer = no` - every War of the Ring map - is refused by the
    auto-start. Maps in the user folder are cached differently: the engine parses them and derives
    the flag itself, and for those same maps it derives **yes**. So copying a map here is how you
    get the engine to start a map its own mod list refuses.

    **`extras` is not optional in practice.** A `map.ini` is loaded from the map's folder, and a
    relative `#include` in it resolves against *that* folder - so a map whose ini reads
    `..\\_inis\\general\\wotrmaps.ini` finds nothing once it has been copied somewhere with no
    `_inis` beside it, and the load stops on an error box that looks exactly like a broken
    `map.ini`. Pass the sibling folders the ini reaches for; each is copied next to the map.

    **`name` renames the installed copy**, `.map` and preview together, because the folder name
    and the map's stem have to match for the `-file` path builder. Give it a name of your own to
    keep a test out of the way of a map the player has actually installed: this **replaces** any
    folder of that name, so it should be one the harness owns rather than a bare map name.
    """
    source = Path(source)
    original = source / f"{source.name}.map"
    if not original.is_file():
        raise FileNotFoundError(f"{source} holds no {source.name}.map to install")

    root = (user_files or user_files_dir()) / "Maps"
    installed = name or source.name
    target = root / installed
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    created = [target]

    if installed != source.name:
        (target / f"{source.name}.map").rename(target / f"{installed}.map")
        preview = target / f"{source.name}.tga"
        if preview.is_file():
            preview.rename(target / f"{installed}.tga")

    for extra in extras:
        extra = Path(extra)
        destination = root / extra.name
        if not extra.is_dir() or destination.exists():
            continue
        shutil.copytree(extra, destination)
        created.append(destination)

    # Lowercased and in parent form, for the reasons `install_map` gives.
    return InstalledMap(
        path=target,
        argument=str(root / f"{installed}.map").lower(),
        created=tuple(created),
    )


@dataclass
class GameProcess:
    """A launched game, and the arguments it was launched with."""

    popen: subprocess.Popen
    arguments: list[str]

    @property
    def pid(self) -> int:
        return self.popen.pid

    @property
    def returncode(self) -> int | None:
        return self.popen.poll()

    def kill(self) -> None:
        if self.popen.poll() is None:
            self.popen.kill()
        self.popen.wait(timeout=10)

    def __enter__(self) -> GameProcess:
        return self

    def __exit__(self, *_exc) -> None:
        self.kill()


def launch(
    file_argument: str,
    game_dat: str | os.PathLike[str],
    *,
    mod: str | os.PathLike[str] | None = None,
    windowed: bool = True,
    resolution: tuple[int, int] = (1024, 768),
    script_debug: bool = False,
    extra: tuple[str, ...] = (),
) -> GameProcess:
    """Start `game_dat` on the map `file_argument` names, from its own directory.

    The binary has to be the install's `game.dat` **under that name**: a section-modified image
    run under any other name dies immediately inside `msvcr71.dll`, so a patched build cannot be
    copied aside and tried out. It also has to carry `command-line-skirmish`, or the game starts
    with a random faction and no opponent - `-file` alone does not configure a match.

    **`mod` is what makes this useful during development.** `-mod <tree>` loads a mod's files
    from a folder instead of its built `.big` archives, and sets `preferLocalFiles` with it, so a
    test runs against the ini you just edited rather than against the last release. Point it at
    the tree holding `data/ini` - Edain's is `_mod`. Resolved to an absolute path because the
    game runs with its own directory as the working directory, where a relative one would mean
    something else entirely.
    """
    game = Path(game_dat)
    arguments = launch_arguments(
        file_argument,
        game,
        mod=mod,
        windowed=windowed,
        resolution=resolution,
        script_debug=script_debug,
        extra=extra,
    )
    return GameProcess(subprocess.Popen(arguments, cwd=str(game.parent)), arguments)


def launch_arguments(
    file_argument: str,
    game_dat: str | os.PathLike[str],
    *,
    mod: str | os.PathLike[str] | None = None,
    windowed: bool = True,
    resolution: tuple[int, int] = (1024, 768),
    script_debug: bool = False,
    extra: tuple[str, ...] = (),
) -> list[str]:
    """The exact command line :func:`launch` would run.

    Split out because the command line is the part with rules in it - the mod path has to be
    absolute, the map argument has to be the form the engine's path builder expects - and none of
    that is worth a game launch to check.
    """
    arguments = [str(Path(game_dat)), "-file", file_argument]
    if mod is not None:
        arguments += ["-mod", str(Path(mod).resolve())]
    if windowed:
        arguments += ["-win", "-xres", str(resolution[0]), "-yres", str(resolution[1])]
    if script_debug:
        arguments.append("-scriptDebug2")
    arguments += list(extra)
    return arguments
