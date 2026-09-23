"""Where a game's ini lives: the include root, layered roots, map-scoped files and the root
files that are the parse units."""

from collections.abc import Iterator, Sequence
from pathlib import Path

from sage_ini.parser.blockparser import include_target, resolve_include
from sage_ini.parser.io import INI_SUFFIXES, iter_ini_files
from sage_ini.parser.lexer import tokenize_path

__all__ = [
    "LOAD_SUFFIXES",
    "STR_SUFFIX",
    "as_root_list",
    "included_files",
    "ini_root",
    "is_map_path",
    "loadable_files",
    "norm_key",
    "root_files",
]

# What the engine loads by default: its ini and its string tables.
STR_SUFFIX = ".str"
LOAD_SUFFIXES = INI_SUFFIXES | {STR_SUFFIX}


def ini_root(root: str | Path) -> Path:
    """The directory root-relative includes resolve against: the scan root, or its nested
    `data/ini` when the corpus dump keeps the full game layout."""
    root = Path(root)
    nested = root / "data" / "ini"
    return nested if nested.is_dir() else root


def as_root_list(root: str | Path | Sequence[str | Path]) -> list[Path]:
    """Normalize a game-root argument - a single root, or an ascending-priority sequence of them
    (a later root shadows an earlier one) - to a list of `Path`s. The shared spelling the loader
    and the ThingTemplate walk use so multiple `--game` roots layer the same way in both."""
    if isinstance(root, (str, Path)):
        return [Path(root)]
    return [Path(part) for part in root]


def is_map_path(path: str | Path, root: str | Path) -> bool:
    """Whether `path` is map-scoped - beneath a `maps/` directory under `root`. A map.ini
    is per-map (its definitions never leak to the global game), so whole-game assembly
    excludes these files."""
    root = Path(root)
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        parts = Path(path).parts
    return any(part.lower() == "maps" for part in parts[:-1])


def included_files(root: str | Path) -> set[str]:
    """Lowercased resolved paths of every file `#include`d by another."""
    layers = (ini_root(root),)
    included: set[str] = set()
    for path in iter_ini_files(root):
        source = path.resolve()
        for line in tokenize_path(source):
            target = include_target(line.content)
            if target is not None:
                resolved = resolve_include(target, source, layers)
                if resolved is not None:
                    included.add(str(resolved).lower())
    return included


def root_files(root: str | Path) -> list[Path]:
    """Files that are not included by any other file - the parse units."""
    included = included_files(root)
    return [path for path in iter_ini_files(root) if str(path.resolve()).lower() not in included]


def norm_key(path: str | Path) -> str:
    """A source-relative path normalized to a lowercase forward-slash key."""
    return str(path).replace("\\", "/").lstrip("/").lower()


def loadable_files(
    folder: str | Path, suffixes: frozenset[str] = LOAD_SUFFIXES
) -> Iterator[tuple[str, Path]]:
    """Yield (relative-path key, absolute path) for each file in a folder whose suffix is in
    `suffixes` (the ini/str the engine loads by default; callers that also want `.map`/`.bse`
    layouts merged pass a wider set)."""
    base = Path(folder)
    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            yield norm_key(path.relative_to(base)), path
