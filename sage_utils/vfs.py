"""A read-only view of a SAGE game's virtual file system: loose files over `.big` archives.

The engine resolves a game path (`maps\\foo\\foo.map`) against loose files first, then against
every `.big` in the game folder in case-insensitive alphabetical mount order, where the first
archive to register a path owns it. That order is why leading-underscore mod archives win over
the base ones (`__edain_data.big` > `_patch201ini.big` > `ini.big`). A mod folder sits above the
install the same way, so layers are given highest priority first.

Archive indexes are read once, at construction. Loose files are looked up on demand, so a large
install folder is never walked in full.
"""

from __future__ import annotations

import os
import struct
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyBIG import LargeArchive

__all__ = ["VfsEntry", "VirtualFileSystem", "mount_order", "vfs_key"]

# Everything pyBIG raises for a truncated or foreign `.big`; one bad archive must not sink a mount.
_ARCHIVE_ERRORS = (OSError, ValueError, KeyError, IndexError, struct.error)
_MANIFEST = ".vfs-manifest"


def vfs_key(path: str) -> str:
    """The lookup key of a game path: lowercase, backslash-separated, no leading separator."""
    return path.replace("/", "\\").strip("\\").lower()


def mount_order(folder: Path) -> list[Path]:
    """Every `.big` the engine mounts from `folder` (its `lang\\` subfolder included), in mount
    order: the first archive holding a path is the one the game reads it from."""
    found = [*folder.glob("*.big"), *(folder / "lang").glob("*.big")]
    return sorted(found, key=lambda path: path.name.lower())


def _loose_path(layer: Path, key: str) -> Path | None:
    """The on-disk path under `layer` for a game-path `key`, matching each segment without regard
    to case (as the engine does on any file system), in the case it is stored with."""
    current = layer
    for segment in filter(None, key.split("\\")):
        if not current.is_dir():
            return None
        match = next((child for child in current.iterdir() if child.name.lower() == segment), None)
        if match is None:
            return None
        current = match
    return current


def _game_path(file: Path, layer: Path) -> str:
    return str(file.relative_to(layer)).replace("/", "\\")


@dataclass(frozen=True)
class VfsEntry:
    """One resolved file: its game path as stored, and the layer folder or archive holding it."""

    path: str
    source: Path
    in_archive: bool

    @property
    def file(self) -> Path | None:
        """The loose file on disk, or `None` for an archive member."""
        if self.in_archive:
            return None
        return self.source / self.path.replace("\\", "/")


class VirtualFileSystem:
    """Resolve and list game paths across `layers`, highest priority first.

    Within a layer, loose files beat that layer's archives; any entry in a higher layer beats
    every entry in a lower one. `archives=False` gives a loose-only view (a user-data folder)."""

    def __init__(self, layers: Sequence[str | Path], *, archives: bool = True) -> None:
        self.layers = tuple(Path(layer) for layer in layers)
        # Archive handles are shared, and a UI reads through them from worker threads.
        self._lock = threading.RLock()
        self._open: dict[Path, LargeArchive] = {}
        self._indexes: list[dict[str, VfsEntry]] = [
            self._index(layer) if archives else {} for layer in self.layers
        ]

    def _index(self, layer: Path) -> dict[str, VfsEntry]:
        index: dict[str, VfsEntry] = {}
        for path in mount_order(layer):
            try:
                archive = self._archive(path)
                listing = archive.file_list()
            except _ARCHIVE_ERRORS:
                continue
            for name in listing:
                index.setdefault(vfs_key(name), VfsEntry(name, path, in_archive=True))
        return index

    def _archive(self, path: Path) -> LargeArchive:
        with self._lock:
            archive = self._open.get(path)
            if archive is None:
                # pyBIG is an optional dependency; only a view that mounts archives needs it.
                from pyBIG import LargeArchive  # noqa: PLC0415

                archive = self._open[path] = LargeArchive(str(path))
            return archive

    def find(self, path: str) -> VfsEntry | None:
        """The entry the game would read for `path`, or `None` when no layer has it."""
        key = vfs_key(path)
        for layer, index in zip(self.layers, self._indexes, strict=True):
            loose = _loose_path(layer, key)
            if loose is not None and loose.is_file():
                return VfsEntry(_game_path(loose, layer), layer, in_archive=False)
            if key in index:
                return index[key]
        return None

    def listdir(self, folder: str) -> Iterator[VfsEntry]:
        """Every winning entry under `folder`, recursively, each path reported once."""
        prefix = vfs_key(folder) + "\\"
        seen: set[str] = set()
        for layer, index in zip(self.layers, self._indexes, strict=True):
            base = _loose_path(layer, prefix)
            loose = sorted(base.rglob("*")) if base is not None and base.is_dir() else []
            for file in loose:
                if not file.is_file():
                    continue
                name = _game_path(file, layer)
                key = vfs_key(name)
                if key not in seen:
                    seen.add(key)
                    yield VfsEntry(name, layer, in_archive=False)
            for key, entry in index.items():
                if key.startswith(prefix) and key not in seen:
                    seen.add(key)
                    yield entry

    def read_bytes(self, entry: VfsEntry | str) -> bytes:
        """The contents of `entry` (or of the winning entry for a game path)."""
        if isinstance(entry, str):
            found = self.find(entry)
            if found is None:
                raise FileNotFoundError(entry)
            entry = found
        if entry.file is not None:
            return entry.file.read_bytes()
        with self._lock:
            return bytes(self._archive(entry.source).read_file(entry.path))

    def extract(
        self, out_dir: str | Path, folders: Sequence[str], keep: Callable[[str], bool]
    ) -> Path:
        """Copy every winning file under `folders` whose key `keep` accepts into `out_dir`, at its
        lowercase game path, and return `out_dir`.

        Cached by a manifest of each file's origin, size and modification time, so an unchanged
        set is not copied again. A file `keep` accepts that is no longer in the set is deleted:
        the loaders walk the whole tree, and a leftover from another game or mod would merge two
        games into one."""
        out_dir = Path(out_dir)
        selected: dict[str, VfsEntry] = {}
        for folder in folders:
            for entry in self.listdir(folder):
                key = vfs_key(entry.path)
                if keep(key):
                    selected[key] = entry

        stats: dict[Path, os.stat_result] = {}
        lines = []
        for key in sorted(selected):
            entry = selected[key]
            origin = entry.file if entry.file is not None else entry.source
            if origin not in stats:
                stats[origin] = origin.stat()
            lines.append(f"{key}\t{origin}\t{stats[origin].st_size}\t{stats[origin].st_mtime_ns}")
        manifest = "\n".join(lines)
        manifest_path = out_dir / _MANIFEST
        if manifest_path.is_file() and manifest_path.read_text(encoding="utf-8") == manifest:
            return out_dir

        # Removed first, so an extraction that stops halfway is never mistaken for a finished one.
        manifest_path.unlink(missing_ok=True)
        if out_dir.is_dir():
            for existing in out_dir.rglob("*"):
                key = vfs_key(str(existing.relative_to(out_dir)))
                if existing.is_file() and keep(key) and key not in selected:
                    existing.unlink()
        for key, entry in selected.items():
            target = out_dir.joinpath(*key.split("\\"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.read_bytes(entry))
        manifest_path.write_text(manifest, encoding="utf-8")
        return out_dir
