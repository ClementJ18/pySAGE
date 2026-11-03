"""`dll-import`: the import table grows by one descriptor per DLL and nothing already there moves.

The image is synthetic: `game.dat`'s import table is a plain PE structure, so a small PE with one
`kernel32.dll` import exercises every path. Its descriptors are IAT-only (`OriginalFirstThunk` is
0), the form `game.dat` uses, and a second fixture carries a lookup table too.
"""

from __future__ import annotations

import argparse
import struct

import pytest

from sage_patch.patches.platform.dll_import import (
    DEFAULT_DLLS,
    DESCRIPTOR_SIZE,
    SECTION_NAME,
    DllImportPatch,
    imported_dlls,
)
from sage_patch.utils import find_section, image_base, va_to_offset

IMAGE_BASE = 0x400000
IDATA_RVA = 0x2000
IDATA_RAW = 0x400
IAT_RVA = 0x2028
ILT_RVA = 0x2030
HINT_NAME_RVA = 0x2040
DLL_NAME_RVA = 0x2060


def _image(*, lookup_table: bool = False) -> bytearray:
    """A PE32 image with `.text` and an `.idata` importing `kernel32.dll!GetTickCount`."""
    data = bytearray(0x600)
    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)
    struct.pack_into("<H", data, e + 6, 2)
    struct.pack_into("<H", data, e + 20, 0xE0)
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)
    struct.pack_into("<I", data, opt + 36, 0x200)
    struct.pack_into("<I", data, opt + 56, 0x3000)
    struct.pack_into("<I", data, opt + 60, 0x400)
    struct.pack_into("<I", data, opt + 92, 16)
    struct.pack_into("<II", data, opt + 104, IDATA_RVA, 2 * DESCRIPTOR_SIZE)
    sectab = opt + 0xE0
    for i, (name, rva, raw) in enumerate(
        ((b".text", 0x1000, 0x200), (b".idata", IDATA_RVA, IDATA_RAW))
    ):
        header = bytearray(40)
        header[0:8] = name.ljust(8, b"\x00")
        struct.pack_into("<IIII", header, 8, 0x200, rva, 0x200, raw)
        data[sectab + 40 * i : sectab + 40 * (i + 1)] = header

    def at(rva: int) -> int:
        return IDATA_RAW + rva - IDATA_RVA

    original_first_thunk = ILT_RVA if lookup_table else 0
    struct.pack_into(
        "<IIIII", data, at(IDATA_RVA), original_first_thunk, 0, 0, DLL_NAME_RVA, IAT_RVA
    )
    struct.pack_into("<II", data, at(IAT_RVA), HINT_NAME_RVA, 0)
    if lookup_table:
        struct.pack_into("<II", data, at(ILT_RVA), HINT_NAME_RVA, 0)
    data[at(HINT_NAME_RVA) : at(HINT_NAME_RVA) + 15] = b"\x00\x00GetTickCount\x00"
    data[at(DLL_NAME_RVA) : at(DLL_NAME_RVA) + 13] = b"kernel32.dll\x00"
    return data


def _import_directory(data: bytes | bytearray) -> tuple[int, int]:
    opt = struct.unpack_from("<I", data, 0x3C)[0] + 24
    return struct.unpack_from("<II", data, opt + 104)


class TestApply:
    @pytest.mark.parametrize("lookup_table", [False, True], ids=["iat-only", "lookup-table"])
    def test_adds_the_dll_after_the_existing_imports(self, lookup_table):
        data = _image(lookup_table=lookup_table)
        DllImportPatch().apply(data)
        assert imported_dlls(data) == ["kernel32.dll", "game-patcher.dll"]
        assert DllImportPatch().verify(data) == []

    def test_moves_the_directory_into_its_own_section(self):
        data = _image()
        DllImportPatch().apply(data)
        section = find_section(data, SECTION_NAME)
        assert section is not None
        rva, size = _import_directory(data)
        assert image_base(data) + rva == section[0]
        assert size == 3 * DESCRIPTOR_SIZE  # kernel32, game-patcher, terminator

    def test_existing_descriptors_and_iat_stay_where_they_were(self):
        """Code calls through IAT slots at fixed addresses, so the copy must not repoint them."""
        data = _image()
        stock = bytes(data[IDATA_RAW : IDATA_RAW + DESCRIPTOR_SIZE])
        iat = bytes(data[IDATA_RAW + 0x28 : IDATA_RAW + 0x30])
        DllImportPatch().apply(data)
        rva, _ = _import_directory(data)
        moved = va_to_offset(data, IMAGE_BASE + rva)
        assert bytes(data[moved : moved + DESCRIPTOR_SIZE]) == stock
        assert bytes(data[IDATA_RAW + 0x28 : IDATA_RAW + 0x30]) == iat

    def test_the_new_descriptor_imports_the_export_by_name(self):
        data = _image()
        DllImportPatch(dlls=["probe.dll:Init"]).apply(data)
        rva, _ = _import_directory(data)
        offset = va_to_offset(data, IMAGE_BASE + rva + DESCRIPTOR_SIZE)
        lookup, stamp, chain, name, iat = struct.unpack_from("<IIIII", data, offset)
        assert (stamp, chain) == (0, 0)
        assert lookup != iat  # the loader overwrites the IAT, so it keeps a separate lookup table
        for thunks in (lookup, iat):
            entry = struct.unpack_from("<I", data, va_to_offset(data, IMAGE_BASE + thunks))[0]
            hint_name = va_to_offset(data, IMAGE_BASE + entry)
            assert bytes(data[hint_name : hint_name + 7]) == b"\x00\x00Init\x00"
        dll = va_to_offset(data, IMAGE_BASE + name)
        assert bytes(data[dll : dll + 10]) == b"probe.dll\x00"

    def test_several_dlls_in_one_go(self):
        data = _image()
        DllImportPatch(dlls=["a.dll:One", "b.dll:Two"]).apply(data)
        assert imported_dlls(data) == ["kernel32.dll", "a.dll", "b.dll"]

    def test_refuses_a_dll_the_image_already_imports(self):
        data = _image()
        DllImportPatch().apply(data)
        with pytest.raises(ValueError, match="already imports game-patcher.dll"):
            DllImportPatch().apply(data)
        with pytest.raises(ValueError, match="already imports KERNEL32.dll"):
            DllImportPatch(dlls=["KERNEL32.dll:Sleep"]).apply(_image())

    def test_a_second_application_keeps_the_first(self):
        data = _image()
        DllImportPatch().apply(data)
        DllImportPatch(dlls=["probe.dll:Init"]).apply(data)
        assert imported_dlls(data) == ["kernel32.dll", "game-patcher.dll", "probe.dll"]
        assert DllImportPatch().verify(data) == []


class TestVerifyAndDetect:
    def test_an_unpatched_image_is_reported(self):
        assert DllImportPatch().verify(_image()) == ["game.dat does not import game-patcher.dll"]
        assert DllImportPatch.detect(_image()) is None

    def test_a_different_export_is_reported(self):
        data = _image()
        DllImportPatch(dlls=["game-patcher.dll:Other"]).apply(data)
        assert DllImportPatch().verify(data) == [
            "game-patcher.dll is imported for 'Other', expected 'Noop'"
        ]

    def test_detect_recovers_every_added_dll(self):
        data = _image()
        DllImportPatch(dlls=["a.dll:One", "b.dll:Two"]).apply(data)
        detected = DllImportPatch.detect(data)
        assert detected is not None
        assert detected.dlls == ("a.dll:One", "b.dll:Two")
        assert detected.options() == {"dlls": ("a.dll:One", "b.dll:Two")}

    def test_detect_spans_two_applications_and_skips_stock_imports(self):
        data = _image()
        DllImportPatch().apply(data)
        DllImportPatch(dlls=["probe.dll:Init"]).apply(data)
        detected = DllImportPatch.detect(data)
        assert detected is not None
        assert detected.dlls == ("game-patcher.dll:Noop", "probe.dll:Init")


class TestParameters:
    @pytest.mark.parametrize("spec", ["game-patcher.dll", ":Noop", "x.dll:", "x.dll:N\x00"])
    def test_rejects_a_malformed_spec(self, spec):
        with pytest.raises(ValueError):
            DllImportPatch(dlls=[spec])

    def test_rejects_a_dll_named_twice(self):
        with pytest.raises(ValueError, match="named twice"):
            DllImportPatch(dlls=["a.dll:One", "A.DLL:Two"])

    def test_rejects_an_empty_list(self):
        with pytest.raises(ValueError, match="at least one"):
            DllImportPatch(dlls=[])

    def test_the_cli_defaults_to_game_patcher(self):
        parser = argparse.ArgumentParser()
        DllImportPatch.add_cli_arguments(parser)
        assert DllImportPatch.from_cli_args(parser.parse_args([])).dlls == DEFAULT_DLLS
        args = parser.parse_args(["--dll", "a.dll:One", "--dll", "b.dll:Two"])
        assert DllImportPatch.from_cli_args(args).dlls == ("a.dll:One", "b.dll:Two")
