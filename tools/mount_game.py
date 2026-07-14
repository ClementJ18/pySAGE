"""Mount a live SAGE install's `.big` archives into a real on-disk `data/ini` tree.

The engine reads every `.big` in the game folder into one virtual filesystem. When two
archives carry the same path, the archive mounted **first** owns it (first-registration
wins); the modding convention of prefixing a mod archive with leading underscores works
precisely because those names sort *before* the base ones (`_` is 0x5F, below `a`), so a
case-insensitive alphabetical mount makes the mod win. For RotWK+Edain that yields the
expected priority `__edain_data.big` > `_patch201ini.big` > `ini.big`.

`sage_ini`'s `thing_template_order` / `load_game` walk an on-disk ini tree, so this
extracts the winning copy of every `data/ini/**` `.ini`/`.inc` into `out_dir`, giving the
loader exactly the bytes the game parsed. The extraction is cached by a manifest so a
re-run is cheap; pass a fresh `out_dir` (or delete it) to rebuild.
"""

from __future__ import annotations

import argparse
import glob
import os
import struct
from pathlib import Path

from pyBIG import LargeArchive

__all__ = ["mount_ini_tree"]

_KEEP_SUFFIXES = (".ini", ".inc")


def _keep(entry_low: str) -> bool:
    """Whether an archive entry belongs in the extracted tree: the `data\\ini` ini/inc sources
    the object loader walks, each map's `map.ini` override (`maps\\<map>\\map.ini` - the
    per-map context `load_map` layers, e.g. a map-scoped hero roster), plus the global `.str`
    localization table (`data\\lotr.str`) so display names resolve. Map-scoped `.str` tables
    are left out."""
    if entry_low.startswith("data\\ini") and entry_low.endswith(_KEEP_SUFFIXES):
        return True
    if entry_low.startswith("maps\\") and entry_low.endswith("\\map.ini"):
        return True
    if not (entry_low.startswith("data\\") and entry_low.endswith(".str")):
        return False
    return "\\maps\\" not in entry_low  # global .str only, not per-map tables


def _archives(game_dir: Path) -> list[Path]:
    """Every `.big` in `game_dir`, in the engine's case-insensitive alphabetical mount order."""
    found = glob.glob(str(game_dir / "*.big"))
    return sorted((Path(p) for p in found), key=lambda p: p.name.lower())


def _first_wins_index(archives: list[Path]) -> dict[str, tuple[Path, str]]:
    """Map each `data/ini/**` entry (keyed by its lowercased, backslash-separated path) to the
    archive that owns it and the entry's *original-case* name - the first-mounted archive wins,
    matching the engine's first-registration rule. The original name is kept because the archive
    index is case-sensitive on read."""
    index: dict[str, tuple[Path, str]] = {}
    for archive in archives:
        try:
            listing = LargeArchive(str(archive)).file_list()
        except (OSError, ValueError, KeyError, IndexError, struct.error):
            continue  # a stray/unreadable .big should not abort the whole mount
        for entry in listing:
            low = entry.lower()
            if _keep(low):
                index.setdefault(low, (archive, entry))
    return index


def mount_ini_tree(game_dir: str | Path, out_dir: str | Path) -> Path:
    """Extract the merged `data/ini` tree of the install at `game_dir` into `out_dir`.

    Returns `out_dir` (the root to hand to `thing_template_order` / `load_game`). Cached: a
    matching `.manifest` of `entry -> archive-name, size, mtime` skips re-extraction. The size
    and mtime are part of the cache key alongside the archive name because a mod's version
    switcher can swap a `.big`'s contents in place while keeping its filename and entry list, and
    that must still be treated as a fresh install to mount.
    """
    game_dir, out_dir = Path(game_dir), Path(out_dir)
    index = _first_wins_index(_archives(game_dir))

    stat_cache: dict[Path, os.stat_result] = {}

    def _stat(archive: Path) -> os.stat_result:
        st = stat_cache.get(archive)
        if st is None:
            st = stat_cache[archive] = archive.stat()
        return st

    manifest_path = out_dir / ".manifest"
    manifest = "\n".join(
        f"{key}\t{a.name}\t{_stat(a).st_size}\t{_stat(a).st_mtime_ns}"
        for key, (a, _) in sorted(index.items())
    )
    if manifest_path.is_file() and manifest_path.read_text(encoding="utf-8") == manifest:
        return out_dir

    # Read each owner once, serving all of its winning entries from a single open handle.
    by_archive: dict[Path, list[tuple[str, str]]] = {}
    for key, (archive, name) in index.items():
        by_archive.setdefault(archive, []).append((key, name))

    for archive, entries in by_archive.items():
        source = LargeArchive(str(archive))
        for key, name in entries:
            data = source.read_file(name)
            target = out_dir / Path(key.replace("\\", os.sep))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    manifest_path.write_text(manifest, encoding="utf-8")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract a live install's merged data/ini tree.")
    parser.add_argument("game_dir", type=Path, help="install folder holding the .big archives")
    parser.add_argument("out_dir", type=Path, help="where to write the merged data/ini tree")
    args = parser.parse_args(argv)

    out = mount_ini_tree(args.game_dir, args.out_dir)
    count = sum(1 for _ in out.rglob("*") if _.is_file() and _.suffix.lower() in _KEEP_SUFFIXES)
    print(f"mounted {args.game_dir} -> {out} ({count} ini/inc files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
