"""Byte round-trip gate over every real map on this machine.

Each map is parsed and written back, and the uncompressed bytes must match the source. The maps,
and the bases (`.bse`, the same layout), come from three places: the mod folder of each corpus
root in `tests/corpus_roots.txt` (a root that is a mod's `data/ini` contributes the mod folder two
levels up), the maps, libraries and bases inside the installed game's `.big` archives, and the
game's user-data `Maps` folder. Compressed
equality is left to `test_full_maps.py`: re-compressing costs minutes per large map in the
pure-Python codec.
"""

import io
from collections.abc import Callable
from pathlib import Path

import pytest

from sage_map.map import parse_map, write_map
from sage_utils.installs import find_install, user_data_dir
from sage_utils.refpack import RefpackError, decompress
from sage_utils.vfs import VirtualFileSystem
from tests.conftest import corpus_roots

pytestmark = pytest.mark.full

Loader = Callable[[], bytes]

_SUFFIXES = (".map", ".bse")


def _mod_folder(root: Path) -> Path:
    if root.name.lower() == "ini" and root.parent.name.lower() == "data":
        return root.parent.parent
    return root


def _loose_maps(label: str, folder: Path) -> list[tuple[str, Loader]]:
    return [
        (f"{label}:{path.relative_to(folder).as_posix()}", path.read_bytes)
        for path in sorted(folder.rglob("*"))
        if path.suffix.lower() in _SUFFIXES and path.is_file()
    ]


def _archived_maps(install: Path) -> list[tuple[str, Loader]]:
    filesystem = VirtualFileSystem([install])
    found: list[tuple[str, Loader]] = []
    for folder in ("maps", "libraries", "bases"):
        for entry in filesystem.listdir(folder):
            if entry.path.lower().endswith(_SUFFIXES):
                found.append(
                    (f"install:{entry.path}", lambda entry=entry: filesystem.read_bytes(entry))
                )
    return found


def _map_sources() -> list[tuple[str, Loader]]:
    sources: list[tuple[str, Loader]] = []
    for label, root in corpus_roots().items():
        sources += _loose_maps(label, _mod_folder(root))
    install = find_install("rotwk")
    if install is not None:
        sources += _archived_maps(install.path)
    user_data = user_data_dir("rotwk")
    if user_data is not None and (user_data / "Maps").is_dir():
        sources += _loose_maps("user", user_data / "Maps")
    return sources


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "load_map_bytes" not in metafunc.fixturenames:
        return
    # Only a --full run pays for walking the corpus; a core run deselects these anyway.
    sources = _map_sources() if metafunc.config.getoption("--full") else []
    if not sources:
        metafunc.parametrize(
            "load_map_bytes",
            [pytest.param(None, marks=pytest.mark.skip(reason="no maps found"))],
        )
        return
    metafunc.parametrize(
        "load_map_bytes", [loader for _, loader in sources], ids=[name for name, _ in sources]
    )


def _uncompressed(raw: bytes) -> bytes:
    body = raw[8:] if raw.startswith(b"EAR") else raw
    try:
        return decompress(body)
    except RefpackError:  # stored uncompressed
        return body


def test_map_round_trips_byte_exact(load_map_bytes: Loader):
    raw = load_map_bytes()
    parsed = parse_map(io.BytesIO(raw))
    assert write_map(parsed, compress=False) == _uncompressed(raw)
