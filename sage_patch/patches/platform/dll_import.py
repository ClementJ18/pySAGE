"""Make `game.dat` load extra DLLs at startup by adding them to its import table.

The Windows loader maps every DLL an image imports, and runs each one's `DllMain`, before the
image's entry point. So a DLL listed in `game.dat`'s import directory starts with the process, on
the main thread, with no launcher or injector. That is how an in-memory patcher such as
bfme2-patcher's `game-patcher.dll` can be carried by the file instead of injected at every launch.

The import directory is copied into a new section, with one descriptor per added DLL after the
existing ones. Each new descriptor imports one export by name, which the DLL must provide:
`game-patcher.dll` exports `Noop` for this purpose. The existing descriptors are copied unchanged,
so every IAT slot stays at its address and nothing that calls through one moves.

Derivation: `../docs/dll-import.md`.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ...patcher import Patch, log
from ...pe import image_sections
from ...utils import align_up, allocate_section, image_base, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_DLLS",
    "DESCRIPTOR_SIZE",
    "SECTION_NAME",
    "DllImportPatch",
    "imported_dlls",
]

SECTION_NAME = ".dllimp"

#: `game-patcher.dll` and the export it provides so it can be loaded from an import table.
DEFAULT_DLLS: tuple[str, ...] = ("game-patcher.dll:Noop",)

DESCRIPTOR_SIZE = 20

# Optional-header offsets for a PE32 image.
_OPT_MAGIC_PE32 = 0x10B
_OPT_NUMBER_OF_RVA_AND_SIZES = 92
_OPT_IMPORT_DIRECTORY = 104

# Initialised data, readable and writable: the loader writes the resolved addresses into the IAT.
_CHARACTERISTICS = 0xC0000040

_ORDINAL_FLAG = 0x80000000


def _parse(spec: str) -> tuple[str, str]:
    """`"name.dll:Export"` -> `("name.dll", "Export")`. Raises for a missing part."""
    dll, sep, export = spec.partition(":")
    dll, export = dll.strip(), export.strip()
    if not sep or not dll or not export:
        raise ValueError(f"{spec!r}: expected DLL:EXPORT, e.g. game-patcher.dll:Noop")
    for part in (dll, export):
        if not part.isascii() or "\x00" in part:
            raise ValueError(f"{spec!r}: names must be plain ASCII")
    return dll, export


def _import_directory(data: bytes | bytearray) -> tuple[int, int, int]:
    """`(optional header offset, import directory RVA, size)`. Raises for a non-PE32 image."""
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    opt = e_lfanew + 24
    if struct.unpack_from("<H", data, opt)[0] != _OPT_MAGIC_PE32:
        raise ValueError("not a PE32 image")
    if struct.unpack_from("<I", data, opt + _OPT_NUMBER_OF_RVA_AND_SIZES)[0] < 2:
        raise ValueError("the image has no import directory entry")
    rva, size = struct.unpack_from("<II", data, opt + _OPT_IMPORT_DIRECTORY)
    return opt, rva, size


def _descriptors(data: bytes | bytearray) -> list[bytes]:
    """The import descriptors, raw, up to (not including) the null terminator."""
    _, rva, _ = _import_directory(data)
    if rva == 0:
        return []
    offset = va_to_offset(data, image_base(data) + rva)
    if offset is None:
        raise ValueError(f"the import directory at RVA {rva:#x} is not mapped by any section")
    found: list[bytes] = []
    while True:
        raw = bytes(data[offset : offset + DESCRIPTOR_SIZE])
        if len(raw) < DESCRIPTOR_SIZE:
            raise ValueError("the import directory runs off the end of the file")
        _, _, _, name, first_thunk = struct.unpack("<IIIII", raw)
        if name == 0 and first_thunk == 0:
            return found
        found.append(raw)
        offset += DESCRIPTOR_SIZE


def _string(data: bytes | bytearray, rva: int) -> str | None:
    offset = va_to_offset(data, image_base(data) + rva)
    if offset is None:
        return None
    end = data.find(b"\x00", offset, offset + 260)
    if end < 0:
        return None
    return bytes(data[offset:end]).decode("latin-1")


def _first_export(data: bytes | bytearray, descriptor: bytes) -> str | None:
    """The first by-name import a descriptor's thunk list names, or None."""
    original_first_thunk, _, _, _, first_thunk = struct.unpack("<IIIII", descriptor)
    thunks = original_first_thunk or first_thunk
    offset = va_to_offset(data, image_base(data) + thunks)
    if offset is None:
        return None
    while True:
        entry = struct.unpack_from("<I", data, offset)[0]
        if entry == 0:
            return None
        if not entry & _ORDINAL_FLAG:
            # A hint/name entry: a 16-bit hint, then the name.
            return _string(data, entry + 2)
        offset += 4


def imported_dlls(data: bytes | bytearray) -> list[str]:
    """Every DLL name `data` imports, in descriptor order."""
    names = []
    for descriptor in _descriptors(data):
        name = _string(data, struct.unpack_from("<I", descriptor, 12)[0])
        names.append(name if name is not None else "?")
    return names


class DllImportPatch(Patch):
    name = "dll-import"
    author = "officialNecro"
    description = (
        "Add DLLs to game.dat's import table, so Windows loads them, and runs their DllMain, "
        "before the game starts: an in-memory patcher such as bfme2-patcher's game-patcher.dll "
        "then needs no injector. --dll NAME:EXPORT, repeatable (default game-patcher.dll:Noop); "
        "each DLL must export the function named and sit beside game.dat, or the game will not "
        "start. No INI change"
    )

    def __init__(self, dlls: Sequence[str] = DEFAULT_DLLS) -> None:
        if isinstance(dlls, str):
            dlls = (dlls,)
        if not dlls:
            raise ValueError("name at least one DLL to import")
        parsed = [_parse(spec) for spec in dlls]
        lowered = [dll.lower() for dll, _ in parsed]
        if len(set(lowered)) != len(lowered):
            raise ValueError(f"a DLL is named twice in {list(dlls)}")
        self.dlls: tuple[str, ...] = tuple(f"{dll}:{export}" for dll, export in parsed)

    def apply(self, data: bytearray) -> None:
        opt, _, _ = _import_directory(data)
        existing = _descriptors(data)
        already = {name.lower() for name in imported_dlls(data)}
        added = [_parse(spec) for spec in self.dlls]
        for dll, _ in added:
            if dll.lower() in already:
                raise ValueError(f"game.dat already imports {dll}")

        table_size = (len(existing) + len(added) + 1) * DESCRIPTOR_SIZE
        base = image_base(data)

        def build(section_va: int) -> bytes:
            rva = section_va - base
            body = bytearray(table_size)
            new_descriptors = bytearray()
            for dll, export in added:
                # Lookup table and IAT: one by-name entry and a terminator each. The loader
                # overwrites the IAT copy with the resolved address.
                thunks = align_up(len(body), 4)
                hint_name = thunks + 16
                body += b"\x00" * (thunks - len(body))
                body += b"\x00" * 16
                body += b"\x00\x00" + export.encode("ascii") + b"\x00"
                body += b"\x00" * (align_up(len(body), 2) - len(body))
                dll_name = len(body)
                body += dll.encode("ascii") + b"\x00"
                struct.pack_into("<II", body, thunks, rva + hint_name, 0)
                struct.pack_into("<II", body, thunks + 8, rva + hint_name, 0)
                new_descriptors += struct.pack(
                    "<IIIII", rva + thunks, 0, 0, rva + dll_name, rva + thunks + 8
                )
            body[:table_size] = b"".join(existing) + new_descriptors + bytes(DESCRIPTOR_SIZE)
            body += b"\x00" * (align_up(len(body), 4) - len(body))
            return bytes(body)

        section_va = allocate_section(data, SECTION_NAME, build, _CHARACTERISTICS)
        struct.pack_into("<II", data, opt + _OPT_IMPORT_DIRECTORY, section_va - base, table_size)
        for dll, export in added:
            log.info("  ok  import %s!%s", dll, export)

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            descriptors = _descriptors(data)
        except (ValueError, struct.error) as error:
            return [str(error)]
        by_name: dict[str, bytes] = {}
        for descriptor in descriptors:
            name = _string(data, struct.unpack_from("<I", descriptor, 12)[0])
            if name is not None:
                by_name.setdefault(name.lower(), descriptor)
        problems = []
        for spec in self.dlls:
            dll, export = _parse(spec)
            found = by_name.get(dll.lower())
            if found is None:
                problems.append(f"game.dat does not import {dll}")
                continue
            got = _first_export(data, found)
            if got != export:
                problems.append(f"{dll} is imported for {got!r}, expected {export!r}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DllImportPatch | None:
        """The DLLs this patch added, read back from the descriptors whose names live in one of
        its sections. The copied stock descriptors still name strings in the original tables, so
        they are never mistaken for added ones."""
        try:
            sections = [s for s in image_sections(data) if s.name == SECTION_NAME]
            if not sections:
                return None
            specs = []
            for descriptor in _descriptors(data):
                name_va = image_base(data) + struct.unpack_from("<I", descriptor, 12)[0]
                if not any(s.contains(name_va) for s in sections):
                    continue
                dll = _string(data, name_va - image_base(data))
                export = _first_export(data, descriptor)
                if dll is None or export is None:
                    return None
                specs.append(f"{dll}:{export}")
            if not specs:
                return None
            patch = cls(dlls=specs)
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dll",
            action="append",
            dest="dlls",
            metavar="NAME:EXPORT",
            help=(
                "a DLL to load at startup and an export it provides; repeat for more. "
                "Default: game-patcher.dll:Noop"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DllImportPatch:
        return cls(dlls=args.dlls or DEFAULT_DLLS)
