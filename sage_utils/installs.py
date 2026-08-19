"""Find installed SAGE games, from the Windows registry first and known paths second.

Every tool that has to reach a *live* install - `sage_patch` deploying a patched binary,
`sage_live` attaching to a running game, the Worldbuilder launcher - otherwise hardcodes
``C:\\Program Files (x86)\\Games\\bfme\\rotwk`` and breaks on anyone else's machine. This is the
one place that guesses, so a wrong guess is fixed once.

:func:`find_installs` is deliberately separate from :mod:`sage_utils.gameroot`, which resolves a
path the *user already gave*. This module answers the earlier question - what is on this machine -
and its results are meant to become the default that `gameroot` then resolves.

**Discovery is advisory.** The registry records where an installer put a game, not whether the
files are still there, so every candidate is checked for a marker file before being returned and
the caller always gets a `--game`-shaped override. On a non-Windows machine the registry half is
simply absent and the known-path half finds nothing, which is why `find_installs` returns an empty
tuple rather than raising: a test suite that runs on Linux must not depend on any of this.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

try:  # not present off Windows; the registry half is skipped there
    import winreg
except ImportError:  # pragma: no cover - exercised only on non-Windows
    winreg = None  # type: ignore[assignment]

__all__ = [
    "GAMES",
    "Install",
    "RegistryKey",
    "find_install",
    "find_installs",
    "registry_reader",
]


@dataclass(frozen=True)
class RegistryKey:
    """One place an installer records an install path.

    ``wow64_32`` asks for the 32-bit view explicitly rather than spelling `Wow6432Node` into the
    subkey: these are 32-bit games, so on a 64-bit Windows their keys live under the redirected
    hive, and naming the view lets the same subkey string work on both."""

    hive: str
    subkey: str
    value: str = "InstallPath"
    wow64_32: bool = True


@dataclass(frozen=True)
class Game:
    """A game this module knows how to look for."""

    key: str
    title: str
    #: Files that must all exist for a candidate directory to count as this game.
    markers: tuple[str, ...]
    registry: tuple[RegistryKey, ...]
    #: Paths to try when the registry says nothing, relative to each Program Files root.
    known_paths: tuple[str, ...]


@dataclass(frozen=True)
class Install:
    """A directory that really does hold ``game``'s files."""

    game: str
    title: str
    path: Path
    #: ``"registry"`` or ``"known-path"`` - which half of the search produced it.
    source: str


_EA = r"SOFTWARE\Electronic Arts\Electronic Arts"

#: The games, in the order :func:`find_installs` reports them.
GAMES: tuple[Game, ...] = (
    Game(
        key="rotwk",
        title="The Lord of the Rings, The Rise of the Witch-king",
        markers=("game.dat",),
        registry=(
            RegistryKey("HKLM", rf"{_EA}\The Lord of the Rings, The Rise of the Witch-king"),
            RegistryKey("HKCU", rf"{_EA}\The Lord of the Rings, The Rise of the Witch-king"),
        ),
        known_paths=(
            r"Games\bfme\rotwk",
            r"Electronic Arts\The Lord of the Rings, The Rise of the Witch-king",
        ),
    ),
    Game(
        key="bfme2",
        title="The Battle for Middle-earth II",
        markers=("game.dat",),
        registry=(
            RegistryKey("HKLM", rf"{_EA}\The Battle for Middle-earth II"),
            RegistryKey("HKCU", rf"{_EA}\The Battle for Middle-earth II"),
        ),
        known_paths=(
            r"Games\bfme\bfme2",
            r"Electronic Arts\The Battle for Middle-earth II",
        ),
    ),
    Game(
        key="bfme1",
        title="The Battle for Middle-earth",
        markers=("game.dat",),
        registry=(
            RegistryKey("HKLM", r"SOFTWARE\EA GAMES\The Battle for Middle-earth"),
            RegistryKey("HKLM", r"SOFTWARE\EA Games\The Battle for Middle-earth"),
        ),
        known_paths=(r"Games\bfme\bfme1", r"EA GAMES\The Battle for Middle-earth"),
    ),
)

#: A registry reader: takes a :class:`RegistryKey`, returns the string it holds or `None`.
Reader = Callable[[RegistryKey], str | None]


def registry_reader(key: RegistryKey) -> str | None:
    """Read one value, returning `None` for anything that is simply not there.

    Off Windows there is no registry and every lookup is `None`. `OSError` covers the whole
    `winreg` failure surface - missing key, missing value, no permission - all of which mean the
    same thing here: this is not where the game is."""
    if winreg is None:
        return None
    hives = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    hive = hives.get(key.hive)
    if hive is None:
        return None
    access = winreg.KEY_READ | (winreg.KEY_WOW64_32KEY if key.wow64_32 else 0)
    try:
        with winreg.OpenKey(hive, key.subkey, 0, access) as handle:
            value, _kind = winreg.QueryValueEx(handle, key.value)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def _program_files_roots() -> Iterator[Path]:
    """The Program Files directories to hang :attr:`Game.known_paths` off, plus bare drives.

    A lot of BFME installs are not under Program Files at all - the games predate the convention
    and people move them - so the drive roots are tried too."""
    seen: set[Path] = set()
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
        raw = os.environ.get(variable)
        if raw:
            root = Path(raw)
            if root not in seen:
                seen.add(root)
                yield root
    for letter in "CDEF":
        root = Path(f"{letter}:\\")
        if root not in seen and root.is_dir():
            seen.add(root)
            yield root


def _is_install(path: Path, game: Game) -> bool:
    return path.is_dir() and all((path / marker).is_file() for marker in game.markers)


def find_installs(
    games: Iterable[str] | None = None,
    reader: Reader = registry_reader,
    roots: Iterable[Path] | None = None,
) -> tuple[Install, ...]:
    """Every install found on this machine, registry hits first, de-duplicated by path.

    ``games`` filters by :attr:`Game.key` (default: all of :data:`GAMES`). ``reader`` and
    ``roots`` are both injectable so the two halves of the search can be exercised in isolation -
    passing ``roots=()`` turns off the known-path guessing and leaves only the registry, which is
    what makes a test independent of what happens to be installed on the machine running it.
    """
    wanted = set(games) if games is not None else None
    search_roots = tuple(_program_files_roots() if roots is None else roots)
    found: list[Install] = []
    seen: set[Path] = set()

    def offer(path: Path, game: Game, source: str) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen or not _is_install(resolved, game):
            return
        seen.add(resolved)
        found.append(Install(game.key, game.title, resolved, source))

    for game in GAMES:
        if wanted is not None and game.key not in wanted:
            continue
        for key in game.registry:
            raw = reader(key)
            if raw:
                offer(Path(raw.strip('"')), game, "registry")
        for root in search_roots:
            for relative in game.known_paths:
                offer(root / relative, game, "known-path")
    return tuple(found)


def find_install(
    game: str = "rotwk",
    reader: Reader = registry_reader,
    roots: Iterable[Path] | None = None,
) -> Install | None:
    """The first install of ``game``, or `None`. The common case behind :func:`find_installs`."""
    installs = find_installs([game], reader, roots)
    return installs[0] if installs else None


def describe(installs: Iterable[Install]) -> str:
    """A short human listing, for a CLI that wants to say what it found."""
    rows = [f"  {i.game:6} {i.source:10} {i.path}" for i in installs]
    return "\n".join(rows) if rows else "  (nothing found)"


if __name__ == "__main__":  # pragma: no cover - a convenience probe, not a supported entry point
    print(f"platform: {sys.platform}")
    print(describe(find_installs()))
