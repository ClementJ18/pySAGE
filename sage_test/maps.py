"""Which maps the engine will start, read from its own map cache.

`-file` does not start a file: it starts a **cache entry**. `TheMapCache` is populated once at
startup from `maps\\mapcache.ini` - a file that ships inside a mod's archives and, in Edain's
case, is maintained by hand - and the lookup that gates the whole auto-start is a plain
`std::map` find against it (`sage_patch/docs/game-info.md` §2). Two consequences a caller cannot
see from the folders on disk:

- **A map the cache does not name cannot be started at all.** Walking `maps/` finds map folders;
  it does not find what the engine believes exists.
- **A non-multiplayer entry is refused.** The auto-start checks `MapMetaData+0x24` and takes a
  silent failure branch when it is 0, which appends game mode 0 instead of skirmish and dies in
  `TheTerrainVisual` seconds later, somewhere that looks unrelated. Every `map edain wor …` entry
  is one of these.

So a suite that launches maps enumerates them from here, and skips what the engine would refuse
rather than reporting it as a crash.

Nothing in this module needs a running game or a parsed `.map`, and `pyBIG` is imported only on
the path that reads an archive - so it stays importable anywhere, which is what lets a test
parametrize over maps at collection time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from ntpath import basename, dirname, splitext
from pathlib import Path

__all__ = [
    "MAP_CACHE_NAME",
    "MapEntry",
    "decode_cache_key",
    "file_argument",
    "load_map_cache",
    "parse_map_cache",
    "read_archive_file",
    "read_map_cache",
]

#: Where the cache file lives, both inside an archive and under an uncompiled mod tree.
MAP_CACHE_NAME = "maps\\mapcache.ini"

#: `MapCache` keys escape every byte outside a small safe set as `_XX`: `_5C` is a backslash,
#: `_20` a space, `_2E` a dot. Names therefore round-trip through a plain hex unescape.
_ESCAPE = re.compile(r"_([0-9A-Fa-f]{2})")

_ENTRY = re.compile(r"^\s*MapCache\s+(\S+)", re.IGNORECASE)
_END = re.compile(r"^\s*END\s*$", re.IGNORECASE)
_FIELD = re.compile(r"^\s*(\w+)\s*=\s*(.*?)\s*$")


def decode_cache_key(token: str) -> str:
    """The map path a `MapCache` key stands for, `maps\\map mp harlindon\\map mp harlindon.map`."""
    return _ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), token)


def file_argument(map_path: str) -> str:
    """The `-file` argument that resolves to `map_path`, which is **not** `map_path`.

    The engine's path builder inserts the file's own stem as a directory before the basename
    (`sage_patch/docs/game-info.md` §1), so the argument names the map's *parent* folder:
    `maps\\map mp harlindon.map` is what becomes the cache key
    `maps\\map mp harlindon\\map mp harlindon.map`. Passing the path that exists on disk inserts
    the folder twice, the lookup misses, and the game dies later somewhere unrelated.

    A path whose folder is not its own stem is left alone: the builder only rewrites what it can,
    and inventing a different parent for it would be a guess.
    """
    name = basename(map_path)
    folder = dirname(map_path)
    if basename(folder).lower() != splitext(name)[0].lower():
        return map_path
    parent = dirname(folder)
    return f"{parent}\\{name}" if parent else name


@dataclass(frozen=True)
class MapEntry:
    """One cached map, as the engine believes it.

    `path` is the cache key decoded - the identity the engine keys by - and `argument` is how to
    ask for it on a command line. The two differ, which is the whole point of this class.
    """

    path: str
    is_multiplayer: bool = False
    is_official: bool = False
    num_players: int = 0

    @property
    def name(self) -> str:
        """The map's folder name, which is what a player sees it called in the map list."""
        return basename(dirname(self.path)) or splitext(basename(self.path))[0]

    @property
    def argument(self) -> str:
        """The `-file` argument that starts this map."""
        return file_argument(self.path)


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"yes", "true", "1"}


def _as_int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return 0


def parse_map_cache(text: str) -> list[MapEntry]:
    """Every entry in a `mapcache.ini`, in file order.

    Lenient by design: this file is hand-edited in some mods, and a suite that refuses to
    enumerate maps because one block has a field it does not recognise is worse than one that
    ignores the field. Only `MapCache`/`END` framing is structural.
    """
    entries: list[MapEntry] = []
    key: str | None = None
    fields: dict[str, str] = {}

    for raw in text.splitlines():
        line = raw.split(";", 1)[0]
        opener = _ENTRY.match(line)
        if opener:
            # An opener while a block is still open means that block was never closed. Drop it
            # and start this one: a missing `End` should cost the map it belongs to, not every
            # map after it in the file.
            key, fields = opener.group(1), {}
            continue
        if key is None:
            continue
        if _END.match(line):
            entries.append(
                MapEntry(
                    path=decode_cache_key(key),
                    is_multiplayer=_as_bool(fields.get("ismultiplayer", "")),
                    is_official=_as_bool(fields.get("isofficial", "")),
                    num_players=_as_int(fields.get("numplayers", "")),
                )
            )
            key = None
            continue
        field = _FIELD.match(line)
        if field:
            fields[field.group(1).lower()] = field.group(2)

    return entries


def read_map_cache(path: str | Path) -> list[MapEntry]:
    """Parse a `mapcache.ini` off disk.

    Read as latin-1, which decodes any byte sequence: every field this reads is ASCII (names are
    hex-escaped, the rest are numbers and yes/no), so only comments can carry anything else and
    they are discarded.
    """
    return parse_map_cache(Path(path).read_bytes().decode("latin-1"))


def read_archive_file(install: str | Path, name: str) -> bytes:
    """One file out of an install's `.big` archives, by its archived name.

    Searched in sorted order over every archive that opens, which is not the engine's own
    override order - good enough for reading a template map or the map cache, not a substitute
    for the game's file system.
    """
    try:
        from pyBIG import InDiskArchive  # noqa: PLC0415 - optional, only this path needs it
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        raise ImportError("reading from a .big archive needs pyBIG") from exc

    for archive in sorted(Path(install).glob("*.big")):
        try:
            big = InDiskArchive(str(archive))
        except Exception:  # noqa: BLE001 - a .big we cannot open is simply not the one
            continue
        entries = {entry.lower(): entry for entry in big.file_list()}
        if name.lower() in entries:
            return big.read_file(entries[name.lower()])
    raise FileNotFoundError(f"{name} is in no .big archive under {install}")


def load_map_cache(
    install: str | Path | None = None, mod: str | Path | None = None
) -> list[MapEntry]:
    """The map cache the game would build, given how it is being launched.

    An uncompiled `-mod` tree wins, because that is what `preferLocalFiles` makes the engine read
    and therefore what a test run with `--mod` is actually exercising; without one the cache
    comes out of the install's archives.
    """
    if mod is not None:
        local = Path(mod) / "maps" / "mapcache.ini"
        if local.is_file():
            return read_map_cache(local)
    if install is None:
        raise FileNotFoundError(
            f"no {MAP_CACHE_NAME} under the given mod tree, and no install to fall back on"
        )
    return parse_map_cache(read_archive_file(install, MAP_CACHE_NAME).decode("latin-1"))
