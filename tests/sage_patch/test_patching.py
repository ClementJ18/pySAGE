"""Tests for the sage_patch binary-patch framework."""

import struct
from pathlib import Path

import pytest

from sage_patch import CommandSetLimitPatch, Patch, apply_patches
from sage_patch.cli import main
from sage_patch.patches import commandset as cs
from sage_patch.patches.commandset import MAX_COUNT, MIN_COUNT
from sage_patch.utils import (
    align_up,
    append_section,
    apply_byte_patch,
    hexbytes,
    image_base,
    va_to_offset,
)

_ENGINE = Path(__file__).resolve().parents[2] / "sage_patch" / "engine"


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


def _synthetic_game_dat(base: int = 0x400000) -> bytearray:
    """A PE32 image large enough to hold every `CommandSetLimitPatch` site and the original
    field-parse table at their real file offsets, with the original bytes planted so the patch
    applies cleanly. This lets the full apply + verify path run in CI without the copyrighted
    `game.dat` (whose byte-identity reproduction is covered separately, when present)."""
    probe = CommandSetLimitPatch(count=64)
    tab_foff = cs._TABLE_VA - base
    highest = tab_foff + 34 * 16
    for off, old, _new, _note in probe._phase1_edits(64):
        highest = max(highest, off + len(old))
    highest = max(highest, cs._PARSER_TABLE_REF + 5, cs._GETFIELDPARSE_REF + 5)
    data = bytearray(align_up(highest + 0x400, 0x200))

    # PE headers: one section, and room after its header for append_section to add a second.
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)  # e_lfanew
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 2, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, base)  # ImageBase
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage (append_section recomputes)
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders (room for a 2nd section header)
    sectab = opt + 0xE0
    hdr = bytearray(40)
    hdr[0:8] = b".text\x00\x00\x00"
    # A small .text so it never shadows the appended .cmdext (rva 0xAD3000) in va_to_offset.
    struct.pack_into("<IIII", hdr, 8, 0x1000, 0x1000, 0x1000, 0x1000)  # vsize, rva, rawsize, praw
    data[sectab : sectab + 40] = hdr

    # Plant the original bytes at every patch site (the `old` half of each edit is N-independent).
    for off, old, _new, _note in probe._phase1_edits(64):
        data[off : off + len(old)] = old
    data[cs._PARSER_TABLE_REF : cs._PARSER_TABLE_REF + 5] = b"\x68" + struct.pack(
        "<I", cs._TABLE_VA
    )
    data[cs._GETFIELDPARSE_REF : cs._GETFIELDPARSE_REF + 5] = b"\xb8" + struct.pack(
        "<I", cs._TABLE_VA
    )

    # Plant the original 34-entry field-parse table (33 numbered slots + InitialVisible).
    for i in range(34):
        name_ptr = 0x00D00000 + i  # distinctive; slots 1..33 are copied through into the new table
        struct.pack_into(
            "<IIII", data, tab_foff + i * 16, name_ptr, cs._PARSE_COMMAND_BUTTON, i, cs._ARRAY_OFF
        )
    return data


class TestApplyProducesVerifiablePatch:
    """End-to-end coverage of the patch logic on a synthetic PE - runnable in CI without the
    real game.dat, which the reproduction test below needs and therefore skips."""

    @pytest.mark.parametrize("count", [MIN_COUNT, 40, 64, 100, MAX_COUNT])
    def test_apply_then_verify(self, count):
        data = _synthetic_game_dat()
        CommandSetLimitPatch(count=count).apply(data)
        assert CommandSetLimitPatch(count=count).verify(data) == []

    def test_apply_writes_the_expected_immediates(self):
        data = _synthetic_game_dat()
        CommandSetLimitPatch(count=64).apply(data)
        obj_size = cs._ARRAY_OFF + 64 * 4 + 8
        assert bytes(data[0x320298 : 0x320298 + 5]) == b"\x68" + struct.pack("<I", obj_size)
        assert bytes(data[0x40C97E : 0x40C97E + 2]) == b"\x6a\x40"  # ctor stosd push = 64
        new_va = image_base(data) + cs._NEW_SECTION_RVA
        assert struct.unpack_from("<I", data, cs._PARSER_TABLE_REF + 1)[0] == new_va
        assert struct.unpack_from("<I", data, cs._GETFIELDPARSE_REF + 1)[0] == new_va

    def test_different_counts_produce_different_output(self):
        a, b = _synthetic_game_dat(), _synthetic_game_dat()
        CommandSetLimitPatch(count=40).apply(a)
        CommandSetLimitPatch(count=100).apply(b)
        assert bytes(a) != bytes(b)

    def test_verify_rejects_an_unpatched_file(self):
        # A clean build: the refs still point at the old table and there is no .cmdext section.
        assert CommandSetLimitPatch(count=64).verify(_synthetic_game_dat())

    def test_verify_rejects_the_wrong_count(self):
        data = _synthetic_game_dat()
        CommandSetLimitPatch(count=64).apply(data)
        assert CommandSetLimitPatch(count=40).verify(data)  # patched to 64, not 40


class TestCli:
    def test_list_shows_registered_patches(self, capsys):
        assert main(["list"]) == 0
        assert "commandset-limit" in capsys.readouterr().out

    def test_apply_then_verify_roundtrip(self, tmp_path):
        src = tmp_path / "game.dat.backup"
        src.write_bytes(bytes(_synthetic_game_dat()))
        out = tmp_path / "game.dat"
        rc = main(
            ["apply", "commandset-limit", "--count", "64", "--in", str(src), "--out", str(out)]
        )
        assert rc == 0
        assert src.read_bytes() == bytes(_synthetic_game_dat())  # input left untouched
        assert main(["verify", "commandset-limit", "--count", "64", str(out)]) == 0

    def test_verify_exits_nonzero_on_mismatch(self, tmp_path):
        clean = tmp_path / "clean.dat"
        clean.write_bytes(bytes(_synthetic_game_dat()))
        assert main(["verify", "commandset-limit", "--count", "64", str(clean)]) == 1


@pytest.mark.skipif(
    not (_ENGINE / "game.dat.backup").exists() or not (_ENGINE / "game.dat").exists(),
    reason="requires the local game.dat.backup + shipped game.dat (not committed to CI)",
)
class TestGameDatReproduction:
    def test_build_matches_shipped_game_dat(self, tmp_path):
        out = tmp_path / "built.dat"
        apply_patches(_ENGINE / "game.dat.backup", [CommandSetLimitPatch(count=64)], output=out)
        assert out.read_bytes() == (_ENGINE / "game.dat").read_bytes()
