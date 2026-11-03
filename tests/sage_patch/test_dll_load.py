"""`dll-load`: the entry point moves to a stub that loads each DLL and then jumps back.

The image is synthetic: the patch reads nothing of `game.dat` but the PE headers and the
`LoadLibraryA` IAT slot it calls through, so a small PE with one `.text` section exercises every
path.
"""

from __future__ import annotations

import argparse
import struct

import pytest

from sage_patch.addresses import LOAD_LIBRARY_A_IAT
from sage_patch.patches.platform.dll_load import (
    BLOCK_MAGIC,
    DEFAULT_DLLS,
    SECTION_NAME,
    DllLoadPatch,
    loaded_dlls,
)
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000
ENTRY_RVA = 0x1010


def _image() -> bytearray:
    """A PE32 image with one `.text` section and its entry point inside it."""
    data = bytearray(0x400)
    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)
    struct.pack_into("<H", data, e + 6, 1)
    struct.pack_into("<H", data, e + 20, 0xE0)
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)
    struct.pack_into("<I", data, opt + 16, ENTRY_RVA)
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)
    struct.pack_into("<I", data, opt + 36, 0x200)
    struct.pack_into("<I", data, opt + 56, 0x2000)
    struct.pack_into("<I", data, opt + 60, 0x200)
    struct.pack_into("<I", data, opt + 92, 16)
    header = bytearray(40)
    header[0:8] = b".text".ljust(8, b"\x00")
    struct.pack_into("<IIII", header, 8, 0x200, 0x1000, 0x200, 0x200)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header
    return data


def _entry(data: bytes | bytearray) -> int:
    opt = struct.unpack_from("<I", data, 0x3C)[0] + 24
    return IMAGE_BASE + struct.unpack_from("<I", data, opt + 16)[0]


def _stub(data: bytes | bytearray) -> bytes:
    off = va_to_offset(data, _entry(data))
    assert off is not None
    return bytes(data[off : off + 64])


class TestApply:
    def test_the_entry_point_moves_into_the_section(self):
        data = _image()
        DllLoadPatch().apply(data)
        section = find_section(data, SECTION_NAME)
        assert section is not None
        assert section[0] < _entry(data) < section[0] + section[2]
        assert loaded_dlls(data) == ["game-patcher.dll"]
        assert DllLoadPatch().verify(data) == []

    def test_the_stub_loads_each_dll_then_jumps_to_the_original_entry(self):
        data = _image()
        DllLoadPatch(dlls=["a.dll", "b.dll"]).apply(data)
        stub, at = _stub(data), _entry(data)
        assert stub[:2] == b"\x9c\x60"  # pushfd; pushad
        pushed = []
        for i in range(2):
            call = 2 + 11 * i
            assert stub[call] == 0x68
            pushed.append(struct.unpack_from("<I", stub, call + 1)[0])
            assert stub[call + 5 : call + 7] == b"\xff\x15"
            assert struct.unpack_from("<I", stub, call + 7)[0] == LOAD_LIBRARY_A_IAT
        names = []
        for va in pushed:
            off = va_to_offset(data, va)
            assert off is not None
            names.append(bytes(data[off : data.index(b"\x00", off)]))
        assert names == [b"a.dll", b"b.dll"]
        tail = 2 + 22
        assert stub[tail : tail + 3] == b"\x61\x9d\xe9"  # popad; popfd; jmp
        target = at + tail + 7 + struct.unpack_from("<i", stub, tail + 3)[0]
        assert target == IMAGE_BASE + ENTRY_RVA

    def test_the_block_records_the_original_entry(self):
        data = _image()
        DllLoadPatch().apply(data)
        section = find_section(data, SECTION_NAME)
        assert section is not None
        magic, original, count = struct.unpack_from("<III", data, section[1])
        assert (magic, original, count) == (BLOCK_MAGIC, IMAGE_BASE + ENTRY_RVA, 1)

    def test_a_second_application_is_refused(self):
        data = _image()
        DllLoadPatch().apply(data)
        with pytest.raises(ValueError, match="already carries"):
            DllLoadPatch(dlls=["probe.dll"]).apply(data)


class TestVerifyAndDetect:
    def test_an_unpatched_image_is_reported(self):
        assert DllLoadPatch().verify(_image()) == [f"{SECTION_NAME} section is absent"]
        assert DllLoadPatch.detect(_image()) is None
        assert loaded_dlls(_image()) == []

    def test_a_different_dll_list_is_reported(self):
        data = _image()
        DllLoadPatch(dlls=["probe.dll"]).apply(data)
        assert DllLoadPatch().verify(data) == [
            "the loader loads ['probe.dll'], expected ['game-patcher.dll']"
        ]

    def test_an_entry_point_moved_elsewhere_is_reported(self):
        data = _image()
        DllLoadPatch().apply(data)
        opt = struct.unpack_from("<I", data, 0x3C)[0] + 24
        struct.pack_into("<I", data, opt + 16, ENTRY_RVA)
        assert any("entry point" in problem for problem in DllLoadPatch().verify(data))
        assert DllLoadPatch.detect(data) is None

    def test_detect_recovers_the_dlls(self):
        data = _image()
        DllLoadPatch(dlls=["a.dll", "b.dll"]).apply(data)
        detected = DllLoadPatch.detect(data)
        assert detected is not None
        assert detected.dlls == ("a.dll", "b.dll")
        assert detected.options() == {"dlls": ("a.dll", "b.dll")}


class TestParameters:
    @pytest.mark.parametrize("name", ["", "x.dll:Noop", "x\x00.dll", "é.dll"])
    def test_rejects_a_malformed_name(self, name):
        with pytest.raises(ValueError):
            DllLoadPatch(dlls=[name])

    def test_rejects_a_dll_named_twice(self):
        with pytest.raises(ValueError, match="named twice"):
            DllLoadPatch(dlls=["a.dll", "A.DLL"])

    def test_rejects_an_empty_list(self):
        with pytest.raises(ValueError, match="at least one"):
            DllLoadPatch(dlls=[])

    def test_the_cli_defaults_to_game_patcher(self):
        parser = argparse.ArgumentParser()
        DllLoadPatch.add_cli_arguments(parser)
        assert DllLoadPatch.from_cli_args(parser.parse_args([])).dlls == DEFAULT_DLLS
        args = parser.parse_args(["--dll", "a.dll", "--dll", "b.dll"])
        assert DllLoadPatch.from_cli_args(args).dlls == ("a.dll", "b.dll")
