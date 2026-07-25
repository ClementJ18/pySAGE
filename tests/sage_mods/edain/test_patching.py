"""Tests for the sage_mods.edain.patching binary-patch framework."""

import struct
from pathlib import Path

import pytest

from sage_mods.edain.patching import CommandSetLimitPatch, Patch, apply_patches
from sage_mods.edain.patching.patches.commandset import MAX_COUNT, MIN_COUNT
from sage_mods.edain.patching.utils import (
    align_up,
    append_section,
    apply_byte_patch,
    hexbytes,
    image_base,
    va_to_offset,
)

_ENGINE = Path(__file__).resolve().parents[3] / "sage_mods" / "edain" / "patching" / "engine"


def _tiny_pe() -> bytearray:
    """A minimal-but-valid-enough PE32 image with one `.text` section, for exercising the PE
    helpers without the real 11 MB binary."""
    data = bytearray(0x400)
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)  # e_lfanew
    data[e : e + 4] = b"PE\x00\x00"
    # COFF file header
    struct.pack_into("<H", data, e + 2, 0x14C)  # Machine (i386) - not read, just realism
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, 0x400000)  # ImageBase
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders (room for another section hdr)
    sectab = opt + 0xE0
    hdr = bytearray(40)
    hdr[0:8] = b".text\x00\x00\x00"
    struct.pack_into("<IIII", hdr, 8, 0x200, 0x1000, 0x200, 0x200)  # vsize, rva, rawsize, praw
    data[sectab : sectab + 40] = hdr
    data[0x200:0x204] = b"\xde\xad\xbe\xef"  # a byte at VA 0x401000
    return data


class TestUtils:
    def test_align_up(self):
        assert align_up(0, 0x200) == 0
        assert align_up(1, 0x200) == 0x200
        assert align_up(0x200, 0x200) == 0x200
        assert align_up(0x201, 0x200) == 0x400

    def test_hexbytes_ignores_spaces(self):
        assert hexbytes("68 d8 f3 c4 00") == b"\x68\xd8\xf3\xc4\x00"

    def test_apply_byte_patch_writes_when_old_matches(self):
        data = bytearray(b"\x68\xa0\x00\x00\x00")
        apply_byte_patch(data, 0, "68 a0 00 00 00", "68 1c 01 00 00", "grow")
        assert bytes(data) == b"\x68\x1c\x01\x00\x00"

    def test_apply_byte_patch_rejects_mismatch(self):
        data = bytearray(b"\x90\x90")
        with pytest.raises(ValueError, match="expected"):
            apply_byte_patch(data, 0, b"\x68\x00", b"\x6a\x00", "x")

    def test_apply_byte_patch_rejects_length_mismatch(self):
        with pytest.raises(ValueError, match="length mismatch"):
            apply_byte_patch(bytearray(4), 0, b"\x00", b"\x00\x00", "x")

    def test_image_base_and_va_to_offset(self):
        data = _tiny_pe()
        assert image_base(data) == 0x400000
        assert va_to_offset(data, 0x401000) == 0x200
        off = va_to_offset(data, 0x401000)
        assert data[off : off + 4] == b"\xde\xad\xbe\xef"
        assert va_to_offset(data, 0x999999) is None

    def test_append_section(self):
        data = _tiny_pe()
        e = 0x80
        content = b"hello-cmdext"
        base_va = append_section(data, ".cmdext", 0x3000, content, 0x40000040)
        assert base_va == 0x403000
        assert struct.unpack_from("<H", data, e + 6)[0] == 2  # NumberOfSections++
        # SizeOfImage grew to cover the new section
        size_of_image = struct.unpack_from("<I", data, e + 24 + 56)[0]
        assert size_of_image == align_up(0x3000 + len(content), 0x1000)
        # the appended content is reachable via its VA
        off = va_to_offset(data, base_va)
        assert data[off : off + len(content)] == content


class _NopPatch(Patch):
    name = "nop"

    def apply(self, data: bytearray) -> None:  # pragma: no cover - trivial
        pass


class _AppendByte(Patch):
    def apply(self, data: bytearray) -> None:
        data += b"\x99"


class TestApplyPatches:
    def test_writes_to_output_and_leaves_input_untouched(self, tmp_path):
        src = tmp_path / "in.bin"
        src.write_bytes(b"\x00\x01\x02")
        out = tmp_path / "out.bin"
        result = apply_patches(src, [_AppendByte()], output=out)
        assert result == out
        assert out.read_bytes() == b"\x00\x01\x02\x99"
        assert src.read_bytes() == b"\x00\x01\x02"  # input untouched

    def test_defaults_to_in_place(self, tmp_path):
        src = tmp_path / "in.bin"
        src.write_bytes(b"\x00")
        apply_patches(src, [_AppendByte()])
        assert src.read_bytes() == b"\x00\x99"

    def test_a_failing_patch_does_not_write(self, tmp_path):
        src = tmp_path / "in.bin"
        src.write_bytes(b"\x00")
        out = tmp_path / "out.bin"

        class _Boom(Patch):
            def apply(self, data):
                raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            apply_patches(src, [_Boom()], output=out)
        assert not out.exists()


class TestCommandSetLimitPatch:
    def test_rejects_counts_at_or_below_the_stock_limit(self):
        for bad in (0, 1, 33):
            with pytest.raises(ValueError, match="count must be"):
                CommandSetLimitPatch(count=bad)

    def test_rejects_counts_past_the_imm8_ceiling(self):
        # 128 is the first value that would sign-extend to -128 at the five imm8 sites; one of
        # them feeds `rep stosd`, so encoding it would be catastrophic rather than merely wrong.
        for bad in (128, 129, 256):
            with pytest.raises(ValueError, match="count must be"):
                CommandSetLimitPatch(count=bad)

    def test_accepts_the_full_supported_range(self):
        for good in (MIN_COUNT, 40, 64, 100, MAX_COUNT):
            assert CommandSetLimitPatch(count=good).count == good

    def test_defaults_to_64(self):
        assert CommandSetLimitPatch().count == 64

    def test_rejects_the_wrong_build(self):
        # A buffer whose CommandSet field table is absent: the table read runs off the end of the
        # image (struct.error) before the parse-fn guard can raise ValueError. Either way the
        # patch refuses rather than writing into an unrecognised binary.
        with pytest.raises((struct.error, ValueError)):
            CommandSetLimitPatch().apply(_tiny_pe())


@pytest.mark.skipif(
    not (_ENGINE / "game.dat.backup").exists() or not (_ENGINE / "game.dat").exists(),
    reason="requires the local game.dat.backup + shipped game.dat (not committed to CI)",
)
class TestGameDatReproduction:
    def test_build_matches_shipped_game_dat(self, tmp_path):
        out = tmp_path / "built.dat"
        apply_patches(_ENGINE / "game.dat.backup", [CommandSetLimitPatch(count=64)], output=out)
        assert out.read_bytes() == (_ENGINE / "game.dat").read_bytes()
