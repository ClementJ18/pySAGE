"""File discovery and reading for SAGE ini data. The data mixes encodings, so the reader
tries ENCODINGS in order and reports which succeeded; latin-1 is the terminal fallback and
decodes any byte sequence, so reading never fails on encoding.
"""

import codecs
from collections.abc import Iterator
from pathlib import Path

__all__ = [
    "INI_SUFFIXES",
    "ASSET_SUFFIXES",
    "MAP_SUFFIXES",
    "ENCODINGS",
    "read_text",
    "read_text_with_encoding",
    "writeback_encoding",
    "iter_ini_files",
    "iter_asset_files",
    "iter_map_files",
]

ENCODINGS: tuple[str, ...] = ("utf-8-sig", "windows-1252", "latin-1")
INI_SUFFIXES: frozenset[str] = frozenset({".ini", ".inc", ".bhav"})

# Loose asset kinds indexed for the linter's missing-texture/model checks. Only textures and
# models, which reliably ship as loose files under `art\`; audio usually lives in archives, so
# it is not indexed. Mirrors the `_AssetFile` extensions in sage_ini.model.types.
ASSET_SUFFIXES: frozenset[str] = frozenset({".tga", ".dds", ".w3d"})

# WorldBuilder layout files: maps (`.map`) and AI base/library layouts (`.bse`). Mirrors
# `_MapFile.extensions` in sage_ini.model.types.
MAP_SUFFIXES: frozenset[str] = frozenset({".map", ".bse"})


def read_text_with_encoding(path: str | Path) -> tuple[str, str]:
    """Read a file, trying ENCODINGS in order; return (text, encoding used)."""
    data = Path(path).read_bytes()

    for encoding in ENCODINGS[:-1]:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    terminal = ENCODINGS[-1]
    return data.decode(terminal), terminal


def read_text(path: str | Path) -> str:
    """Read a file with encoding fallback, returning the text only."""
    text, _ = read_text_with_encoding(path)
    return text


def writeback_encoding(path: str | Path, encoding: str) -> str:
    """The encoding to write a file back in, given the one `read_text_with_encoding` reported.
    `utf-8-sig` decodes BOM-less files too but reports `utf-8-sig`; writing that back would
    prepend a BOM the file never had, so fall back to plain `utf-8` unless one is present."""
    if encoding == "utf-8-sig" and not Path(path).read_bytes().startswith(codecs.BOM_UTF8):
        return "utf-8"
    return encoding


def iter_ini_files(root: str | Path) -> Iterator[Path]:
    """Yield every ini-family file (INI_SUFFIXES) under `root`, sorted, recursively."""
    root = Path(root)
    yield from sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in INI_SUFFIXES
    )


def iter_asset_files(root: str | Path) -> Iterator[Path]:
    """Yield every asset file (ASSET_SUFFIXES) under `root`, sorted, recursively - the same
    crawl as `iter_ini_files`, for the texture/model files the linter checks references against."""
    root = Path(root)
    yield from sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in ASSET_SUFFIXES
    )


def iter_map_files(root: str | Path) -> Iterator[Path]:
    """Yield every WorldBuilder layout file (MAP_SUFFIXES - `.map`/`.bse`) under `root`, sorted,
    recursively. Each ships as `<name>/<name>.ext` under `maps\\`, `bases\\` or `libraries\\`;
    the engine loads it by folder name, so the linter both indexes these for `MapFile`
    reference checks and flags a file whose stem does not match its folder."""
    root = Path(root)
    yield from sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in MAP_SUFFIXES
    )
