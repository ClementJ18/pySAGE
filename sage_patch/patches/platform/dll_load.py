"""Make `game.dat` load extra DLLs at startup when they are there, and start without them when not.

`game.dat`'s entry point is moved to a cave that `LoadLibraryA`s each DLL by name and then jumps to
the original entry point. The loader has resolved every import and run every imported DLL's
`DllMain` by then, and no game code has run, so a DLL loaded here gets the moment an import would
give it - on the main thread, before the game's first instruction - which is what bfme2-patcher's
`game-patcher.dll` needs. Unlike an import (`dll-import`), a DLL that is missing, or whose own
dependencies are, makes `LoadLibraryA` return 0 and the game starts without it, as `accel-module`
does for the accelerator.

Derivation: `../docs/dll-load.md`.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ...addresses import LOAD_LIBRARY_A_IAT
from ...asm import Asm
from ...patcher import Patch, log
from ...utils import align_up, allocate_section, find_section, image_base, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "BLOCK_MAGIC",
    "DEFAULT_DLLS",
    "SECTION_NAME",
    "DllLoadPatch",
    "build_section",
    "loaded_dlls",
]

SECTION_NAME = ".dllload"

#: bfme2-patcher's in-memory patcher. Its EasyHook32.dll has to sit beside it as well.
DEFAULT_DLLS: tuple[str, ...] = ("game-patcher.dll",)

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ: the stub and the names it passes.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000

#: `'DLLD'`, so the block is recognisable without being told where it landed.
BLOCK_MAGIC = 0x444C4C44

# The block: magic, the original entry point's VA, the number of names, then the names
# (NUL-terminated, back to back), then the stub, 16-aligned.
_OFF_MAGIC = 0x00
_OFF_ORIGINAL_ENTRY = 0x04
_OFF_COUNT = 0x08
_OFF_NAMES = 0x10

# Optional-header offset of AddressOfEntryPoint in a PE32 image.
_OPT_ENTRY_POINT = 16


def _check(name: str) -> str:
    name = name.strip()
    if not name or not name.isascii() or "\x00" in name or ":" in name:
        raise ValueError(f"{name!r}: expected a plain ASCII DLL file name, e.g. game-patcher.dll")
    return name


def _optional_header(data: bytes | bytearray) -> int:
    return struct.unpack_from("<I", data, 0x3C)[0] + 24


def _entry_va(data: bytes | bytearray) -> int:
    return (
        image_base(data)
        + struct.unpack_from("<I", data, _optional_header(data) + _OPT_ENTRY_POINT)[0]
    )


def _layout(dlls: Sequence[str]) -> tuple[list[int], int]:
    """Each name's offset in the block, and where the stub starts."""
    offsets, at = [], _OFF_NAMES
    for dll in dlls:
        offsets.append(at)
        at += len(dll) + 1
    return offsets, align_up(at, 16)


def build_section(base_va: int, dlls: Sequence[str], original_entry: int) -> bytes:
    """The whole section as it is written to the file: the block, then the stub."""
    offsets, code_offset = _layout(dlls)
    block = bytearray(code_offset)
    struct.pack_into("<III", block, _OFF_MAGIC, BLOCK_MAGIC, original_entry, len(dlls))
    for dll, offset in zip(dlls, offsets, strict=True):
        block[offset : offset + len(dll)] = dll.encode("ascii")

    a = Asm(base_va + code_offset)
    # The loader's registers and flags go to the original entry point exactly as they came.
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad
    for offset in offsets:
        a.emit(0x68, struct.pack("<I", base_va + offset))  # push "name.dll"
        a.emit(0xFF, 0x15, struct.pack("<I", LOAD_LIBRARY_A_IAT))  # call [LoadLibraryA]
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    a.jmp_absolute(original_entry)
    return bytes(block) + a.finish()


def _stub_va(base_va: int, dlls: Sequence[str]) -> int:
    return base_va + _layout(dlls)[1]


def _read_block(data: bytes | bytearray) -> tuple[int, list[str], int] | None:
    """`(section VA, names, original entry VA)` from the patch's section, or None."""
    located = find_section(data, SECTION_NAME)
    if located is None:
        return None
    section_va, section_off, _ = located
    magic, original_entry, count = struct.unpack_from("<III", data, section_off + _OFF_MAGIC)
    if magic != BLOCK_MAGIC:
        return None
    names, at = [], section_off + _OFF_NAMES
    for _ in range(count):
        end = data.find(b"\x00", at, at + 260)
        if end < 0:
            return None
        names.append(bytes(data[at:end]).decode("ascii"))
        at = end + 1
    return section_va, names, original_entry


def loaded_dlls(data: bytes | bytearray) -> list[str]:
    """The DLLs `data`'s entry point loads through this patch, or none."""
    block = _read_block(data)
    return [] if block is None else block[1]


class DllLoadPatch(Patch):
    name = "dll-load"
    author = "officialNecro"
    description = (
        "Have game.dat LoadLibraryA DLLs from its own folder at its entry point, before any game "
        "code runs, so an in-memory patcher such as bfme2-patcher's game-patcher.dll needs no "
        "injector. A DLL that is not there is skipped and the game starts without it. --dll NAME, "
        "repeatable (default game-patcher.dll). No INI change"
    )
    # Edain's game.dat, 2026-11-02: game-patcher.dll loads and logs with the dll present, and the
    # game reaches the menu as stock with it absent (docs/dll-load.md)
    runtime_verified = "yes"

    def __init__(self, dlls: Sequence[str] = DEFAULT_DLLS) -> None:
        if isinstance(dlls, str):
            dlls = (dlls,)
        if not dlls:
            raise ValueError("name at least one DLL to load")
        checked = [_check(dll) for dll in dlls]
        lowered = [dll.lower() for dll in checked]
        if len(set(lowered)) != len(lowered):
            raise ValueError(f"a DLL is named twice in {list(dlls)}")
        self.dlls: tuple[str, ...] = tuple(checked)

    def apply(self, data: bytearray) -> None:
        if _read_block(data) is not None:
            raise ValueError(f"game.dat already carries a {SECTION_NAME} loader")
        original_entry = _entry_va(data)
        if va_to_offset(data, original_entry) is None:
            raise ValueError(f"the entry point {original_entry:#010x} is not mapped")

        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base_va: build_section(base_va, self.dlls, original_entry),
            _CHARACTERISTICS,
        )
        stub = _stub_va(section_va, self.dlls)
        struct.pack_into(
            "<I", data, _optional_header(data) + _OPT_ENTRY_POINT, stub - image_base(data)
        )
        for dll in self.dlls:
            log.info("  ok  load %s at the entry point", dll)

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            block = _read_block(data)
        except (ValueError, struct.error) as error:
            return [str(error)]
        if block is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, names, original_entry = block
        problems = []
        if [name.lower() for name in names] != [dll.lower() for dll in self.dlls]:
            problems.append(f"the loader loads {names}, expected {list(self.dlls)}")
            return problems
        stub = _stub_va(section_va, names)
        if _entry_va(data) != stub:
            problems.append(f"the entry point is {_entry_va(data):#010x}, expected {stub:#010x}")
        located = find_section(data, SECTION_NAME)
        assert located is not None
        expected = build_section(section_va, names, original_entry)
        if bytes(data[located[1] : located[1] + len(expected)]) != expected:
            problems.append(f"the {SECTION_NAME} section does not hold the expected loader")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DllLoadPatch | None:
        try:
            block = _read_block(data)
            if block is None or not block[1]:
                return None
            patch = cls(dlls=block[1])
        except (ValueError, KeyError, IndexError, TypeError, struct.error, UnicodeDecodeError):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dll",
            action="append",
            dest="dlls",
            metavar="NAME",
            help=(
                "a DLL to load at startup if it is there; repeat for more. "
                "Default: game-patcher.dll"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DllLoadPatch:
        return cls(dlls=args.dlls or DEFAULT_DLLS)
