"""Tests for the sage_patch binary-patch framework."""

import logging
import struct
from pathlib import Path

import pytest

from sage_patch import CahFactionsPatch, CommandSetLimitPatch, Patch, apply_patches
from sage_patch.cli import main
from sage_patch.patcher import EXPERIMENTAL_WARNING
from sage_patch.patches import cah_factions as cf
from sage_patch.patches import commandset as cs
from sage_patch.patches.commandset import MAX_COUNT, MIN_COUNT
from sage_patch.registry import PATCHES
from sage_patch.utils import (
    align_up,
    allocate_section,
    append_section,
    apply_byte_patch,
    find_section,
    hexbytes,
    image_base,
    next_section_rva,
    va_to_offset,
)

_ENGINE = Path(__file__).resolve().parents[2] / "sage_patch" / "engine"


def _tiny_pe() -> bytearray:
    """A minimal-but-valid-enough PE32 image with one `.text` section, for exercising the PE
    helpers without the real 11 MB binary."""
    data = bytearray(0x400)
    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)  # e_lfanew
    data[e : e + 4] = b"PE\x00\x00"
    # COFF file header
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386) - not read, just realism
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

    def test_find_section(self):
        data = _tiny_pe()
        assert find_section(data, ".nope") is None
        base_va = append_section(data, ".cave", 0x3000, b"xyz", 0x40000040)
        located = find_section(data, ".cave")
        assert located is not None
        found_va, off, vsize = located
        assert (found_va, vsize) == (base_va, 3)
        assert data[off : off + 3] == b"xyz"

    def test_allocate_section_builds_self_referential_content(self):
        data = _tiny_pe()
        # `build` is handed the base VA, so content can point at itself
        base_va = allocate_section(
            data, ".cave", lambda va: struct.pack("<I", va + 4) + b"tail", 0x40000040
        )
        off = va_to_offset(data, base_va)
        assert struct.unpack_from("<I", data, off)[0] == base_va + 4
        assert data[off + 4 : off + 8] == b"tail"

    def test_allocate_section_always_lands_past_every_existing_section(self):
        data = _tiny_pe()
        first = allocate_section(data, ".one", lambda va: b"a", 0x40000040)
        second = allocate_section(data, ".two", lambda va: b"b", 0x40000040)
        assert second > first  # appending twice keeps the section table RVA-sorted
        rvas = _section_rvas(data)
        assert rvas == sorted(rvas)


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

    def test_applying_names_the_author(self, tmp_path, caplog):
        """A patch is somebody's reverse engineering before it is anybody's code, and none of that
        work is visible in the diff once the assembly is written down. The applying line is where
        a run says whose it was."""
        src = tmp_path / "in.bin"
        src.write_bytes(b"\x00")

        class _Credited(_AppendByte):
            name = "credited"
            author = "officialNecro"

        with caplog.at_level(logging.INFO, logger="sage_patch"):
            apply_patches(src, [_Credited()])
        assert "credited (by officialNecro)" in caplog.text

    def test_an_unattributed_patch_says_so_rather_than_going_quiet(self, tmp_path, caplog):
        """Silence would read as "this one is nobody's", which is never true - it means the
        attribute was not filled in. Every patch in the registry has one; see
        `TestEveryPatchIsAttributed`."""
        src = tmp_path / "in.bin"
        src.write_bytes(b"\x00")

        with caplog.at_level(logging.INFO, logger="sage_patch"):
            apply_patches(src, [_NopPatch()])
        assert "nop (author unrecorded)" in caplog.text


class TestEveryPatchIsAttributed:
    """**The gate that keeps the credit honest as patches are added.**

    An `author` nobody fills in is worse than no author field at all: it puts a "(author
    unrecorded)" line in front of work somebody did, and it does it silently, one new patch at a
    time. The default is deliberately empty rather than a name so that the omission is visible -
    and this is what makes it fail rather than merely be visible."""

    @pytest.mark.parametrize("name", sorted(PATCHES), ids=sorted(PATCHES))
    def test_a_registered_patch_names_its_author(self, name):
        author = PATCHES[name].author
        assert author, (
            f'{name} has no author. Set `author = "..."` on the patch class beside its `name` - '
            "whoever worked out the addresses and the call convention is not recoverable from the "
            "assembly afterwards, and `apply` prints this as the credit line."
        )
        assert author.strip() == author, f"{name}'s author has stray whitespace: {author!r}"

    def test_the_credit_line_carries_it(self):
        """`apply` prints `credit`, not `author`, so the attribute being set is only half of it."""
        for name, cls in PATCHES.items():
            assert cls.author in cls().credit, name

    def test_list_names_every_author(self, capsys):
        """**The command somebody runs when they are writing their mod's credits.** An `apply` log
        names only the patches that build used, which is the wrong question here - "who do I need
        to thank" is asked of the whole registry, before any binary exists."""
        assert main(["list"]) == 0
        printed = capsys.readouterr().out
        for name, cls in PATCHES.items():
            line = next(row for row in printed.splitlines() if row.startswith(name))
            # Against `-` rather than against `cls.author`, which an unattributed patch would
            # satisfy vacuously: the empty string is a substring of every line, so the assertion
            # that reads as the obvious one is the one that cannot fail.
            assert "-" not in line.removeprefix(name).split()[0], f"{name} is unattributed"
            assert cls.author in line, name


class TestExperimentalPatchesAreDeclared:
    """**The gate that keeps the experimental warning attached to the right patches.**

    "Experimental" is recorded twice - as the directory a module sits in, and as
    `Patch.experimental` - because the two are read by different people. A contributor learns it
    from the import path; somebody running `sage-patch apply` learns it from the warning, and never
    opens the source at all. Neither is redundant, and either drifting on its own is worse than not
    having marked it: a module moved up out of `experimental/` with the attribute left behind warns
    about a patch that has been played, and one moved *in* without it stays silent about a patch
    that has not.

    So the move is the whole procedure, and this is what makes it so."""

    @staticmethod
    def _in_experimental_package(cls: type[Patch]) -> bool:
        return cls.__module__.startswith("sage_patch.patches.experimental.")

    @pytest.mark.parametrize("name", sorted(PATCHES), ids=sorted(PATCHES))
    def test_the_flag_agrees_with_where_the_patch_lives(self, name):
        cls = PATCHES[name]
        if self._in_experimental_package(cls):
            assert cls.experimental, (
                f"{name} lives in sage_patch/patches/experimental/ but does not set "
                "`experimental = True`, so `sage-patch list` and `sage-patch apply` present it as "
                "a settled patch. Set it, or move the module up if it has been run in a game."
            )
        else:
            assert not cls.experimental, (
                f"{name} sets `experimental = True` but does not live in "
                "sage_patch/patches/experimental/. Move the module there, or drop the attribute."
            )

    def test_list_marks_them_and_spells_the_warning_out(self, capsys):
        """The marker and the sentence it stands for, in the output somebody reads *before*
        choosing a patch - `apply` also warns, but by then the choice is made."""
        assert main(["list"]) == 0
        printed = capsys.readouterr().out
        experimental = [name for name, cls in PATCHES.items() if cls.experimental]
        assert experimental, "nothing to check - drop this test with the last experimental patch"
        assert EXPERIMENTAL_WARNING in printed
        for name, cls in PATCHES.items():
            line = next(row for row in printed.splitlines() if row.startswith(name))
            marked = "exp" in line.removeprefix(name).split()[:1]
            assert marked == cls.experimental, f"{name}'s row disagrees with its flag: {line!r}"

    def test_apply_warns_before_it_writes(self, tmp_path, caplog):
        """A `WARNING` rather than a print, so it reaches a caller who never configured logging -
        Python's last-resort handler puts warnings on stderr with no setup at all, which `log.info`
        does not get."""

        class _Experimental(Patch):
            name = "experimental-nop"
            author = "nobody"
            experimental = True

            def apply(self, data: bytearray) -> None:
                data += b"\xff"

        src = tmp_path / "in.bin"
        src.write_bytes(b"\x00")
        with caplog.at_level(logging.WARNING, logger="sage_patch"):
            apply_patches(src, [_Experimental()], output=tmp_path / "out.bin")
        assert EXPERIMENTAL_WARNING in caplog.text
        assert "experimental-nop" in caplog.text

    def test_a_settled_patch_stays_quiet(self, tmp_path, caplog):
        """The other half, and the reason the default is False: a warning printed for everything
        is a warning read for nothing."""
        src = tmp_path / "in.bin"
        src.write_bytes(b"\x00")
        with caplog.at_level(logging.WARNING, logger="sage_patch"):
            apply_patches(src, [_NopPatch()], output=tmp_path / "out.bin")
        assert EXPERIMENTAL_WARNING not in caplog.text


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
    data[0:2] = b"MZ"

    # PE headers: one section, and room after its header for append_section to add a second.
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)  # e_lfanew
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
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
    # A small .text so it never shadows the cave appended past it in va_to_offset.
    struct.pack_into("<IIII", hdr, 8, 0x1000, 0x1000, 0x1000, 0x1000)  # vsize, rva, rawsize, praw
    data[sectab : sectab + 40] = hdr

    _plant_commandset_sites(data, base)
    return data


def _plant_commandset_sites(data: bytearray, base: int = 0x400000) -> None:
    """Write the clean bytes `CommandSetLimitPatch` expects at every site it touches, so it can be
    applied to ``data``. Kept separate so a test can host both patches in one image."""
    probe = CommandSetLimitPatch(count=64)
    # The `old` half of each edit is N-independent, so any probe count will do.
    for off, old, _new, _note in probe._phase1_edits(64):
        data[off : off + len(old)] = old
    data[cs._PARSER_TABLE_REF : cs._PARSER_TABLE_REF + 5] = b"\x68" + struct.pack(
        "<I", cs._TABLE_VA
    )
    data[cs._GETFIELDPARSE_REF : cs._GETFIELDPARSE_REF + 5] = b"\xb8" + struct.pack(
        "<I", cs._TABLE_VA
    )

    # Plant the original 34-entry field-parse table (33 numbered slots + InitialVisible).
    tab_foff = cs._TABLE_VA - base
    for i in range(34):
        name_ptr = 0x00D00000 + i  # distinctive; slots 1..33 are copied through into the new table
        struct.pack_into(
            "<IIII", data, tab_foff + i * 16, name_ptr, cs._PARSE_COMMAND_BUTTON, i, cs._ARRAY_OFF
        )


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
        new_va, _off, _vsize = find_section(data, cs._SECTION_NAME)
        assert struct.unpack_from("<I", data, cs._PARSER_TABLE_REF + 1)[0] == new_va
        assert struct.unpack_from("<I", data, cs._GETFIELDPARSE_REF + 1)[0] == new_va

    @pytest.mark.parametrize("count", [MIN_COUNT, 64, MAX_COUNT])
    def test_the_ai_scan_bound_tracks_the_limit(self, count):
        """`BuildAssistant::canMakeUnit` walks the set for the AI. Left at 33 it would not see the
        buttons this patch newly allows, so a paged hero roster would be player-only."""
        data = _synthetic_game_dat()
        CommandSetLimitPatch(count=count).apply(data)
        site = cs._AI_SCAN_BOUND
        assert bytes(data[site : site + 4]) == b"\x83\x7d\xf8" + bytes([count])

    def test_the_ai_scan_bound_stops_one_short_of_the_count_field(self):
        """The bound is unchecked (`getCommandButton` is a bare `[this + i*4 + 0x14]`), so `N`
        must visit indices 0..N-1 and never index N, where Phase 1 puts the count field."""
        count = 64
        data = _synthetic_game_dat()
        CommandSetLimitPatch(count=count).apply(data)
        highest_index_visited = count - 1
        count_field_index = (cs._ARRAY_OFF + count * 4 - cs._ARRAY_OFF) // 4
        assert highest_index_visited < count_field_index

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


def _cah_game_dat(base: int = 0x400000) -> bytearray:
    """A PE32 image carrying the clean bytes `CahFactionsPatch` expects at every site it touches,
    at their real file offsets, so the full apply + verify path runs in CI without the
    copyrighted `game.dat`. Raw offset equals RVA throughout, as it does in the real binary."""
    sites = [
        *cf._TABLE_REF_VAS,
        *cf._TABLE_END_REF_VAS,
        cf._DEFAULT_FACTION_USERDATA_VA,
        cf._USABLE_FACTIONS_PARSER_VA,
    ]
    highest = max(
        (cf._SIDE_TABLE_VA - base) + (len(cf.STOCK_SIDES) + 1) * 4,
        cf._SCAN_BOUND_VA - base + 8,
        max(va - base + 4 for va in sites),
    )
    data = bytearray(align_up(highest + 0x1000, 0x200))
    data[0:2] = b"MZ"

    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)  # e_lfanew
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, base)  # ImageBase
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage (append_section recomputes)
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders (room for more section headers)
    sectab = opt + 0xE0
    hdr = bytearray(40)
    hdr[0:8] = b".text\x00\x00\x00"
    span = len(data) - 0x1000
    struct.pack_into("<IIII", hdr, 8, span, 0x1000, span, 0x1000)  # vsize, rva, rawsize, praw
    data[sectab : sectab + 40] = hdr

    # The nine stock name strings, and the NULL-terminated table of pointers to them.
    cursor = 0x900000
    ptrs = []
    for name in cf.STOCK_SIDES:
        ptrs.append(base + cursor)
        raw = name.encode("ascii") + b"\x00"
        data[cursor : cursor + len(raw)] = raw
        cursor += len(raw)
    struct.pack_into(f"<{len(ptrs) + 1}I", data, cf._SIDE_TABLE_VA - base, *ptrs, 0)

    for va in cf._TABLE_REF_VAS:
        struct.pack_into("<I", data, va - base, cf._SIDE_TABLE_VA)
    for va in cf._TABLE_END_REF_VAS:
        struct.pack_into("<I", data, va - base, cf._SIDE_TABLE_VA + cf._TABLE_END_DELTA)
    struct.pack_into("<I", data, cf._DEFAULT_FACTION_USERDATA_VA - base, cf._INI_TABLE_VA)
    struct.pack_into("<I", data, cf._USABLE_FACTIONS_PARSER_VA - base, cf._STOCK_PARSER_VA)
    # `cmp esi, 9 / jl / push 9 / pop eax` - the scan bound, then the not-found answer that the
    # patch deliberately leaves alone.
    scan = cf._SCAN_BOUND_VA - base
    data[scan : scan + 8] = b"\x83\xfe\x09\x7c\xe6\x6a\x09\x58"
    return data


def _cave(data, patch):
    """The `.cahfac` section's ``(base_va, file_offset)``, plus the parsed table entry names."""
    base_va, off, _vsize = find_section(data, cf._SECTION_NAME)
    count = patch.entry_count
    ptrs = struct.unpack_from(f"<{count + 1}I", data, off)
    names = [cf._read_cstring(data, p) for p in ptrs[:-1]]
    return base_va, off, names, ptrs[-1]


class TestCahFactionsValidation:
    def test_ceiling_is_the_32_bit_mask(self):
        # indices 0..8 are the stock sides and 9 is `All`, so 31 is the highest usable bit.
        assert cf.ALL_INDEX == 9
        assert cf.MAX_SIDES == 22
        assert CahFactionsPatch(sides=[f"S{i}" for i in range(cf.MAX_SIDES)])

    def test_rejects_more_sides_than_bits(self):
        with pytest.raises(ValueError, match="at most 22 sides"):
            CahFactionsPatch(sides=[f"S{i}" for i in range(cf.MAX_SIDES + 1)])

    @pytest.mark.parametrize("name", ["Men", "men", "Neutral", "All", "all", "None", "Goblins"])
    def test_rejects_reserved_names(self, name):
        with pytest.raises(ValueError, match="reserved"):
            CahFactionsPatch(sides=[name])

    def test_rejects_duplicates_case_insensitively(self):
        with pytest.raises(ValueError, match="duplicate"):
            CahFactionsPatch(sides=["Rohan", "rohan"])

    @pytest.mark.parametrize("name", ["", " ", "Ro han", "Rohan ", "Rohán", "Ro\tan"])
    def test_rejects_unusable_names(self, name):
        with pytest.raises(ValueError):
            CahFactionsPatch(sides=[name])

    @pytest.mark.parametrize("name", ["+Rohan", "-Rohan"])
    def test_rejects_usablefactions_prefixes(self, name):
        # `+Name` / `-Name` are the parser's set/clear tokens, so a name starting with one could
        # never be written literally in an INI.
        with pytest.raises(ValueError, match=r"\+"):
            CahFactionsPatch(sides=[name])

    def test_no_sides_is_valid_and_still_adds_all(self):
        assert CahFactionsPatch().entry_count == len(cf.STOCK_SIDES) + 1


class TestCahFactionsApply:
    @pytest.mark.parametrize(
        "sides",
        [(), ("Rohan",), ("Rohan", "Lothlorien", "Harad"), tuple(f"S{i}" for i in range(22))],
    )
    def test_apply_then_verify(self, sides):
        data = _cah_game_dat()
        CahFactionsPatch(sides=sides).apply(data)
        assert CahFactionsPatch(sides=sides).verify(data) == []

    def test_table_is_the_stock_nine_then_all_then_the_sides(self):
        data = _cah_game_dat()
        patch = CahFactionsPatch(sides=["Rohan", "Lothlorien"])
        patch.apply(data)
        _base_va, _off, names, terminator = _cave(data, patch)
        assert names == [*cf.STOCK_SIDES, "All", "Rohan", "Lothlorien"]
        assert terminator == 0  # the scan still stops on a NULL
        assert names.index("Wild") == 5  # `Goblins` is hard-coded to alias index 5

    def test_every_reference_moves_to_the_new_table(self):
        data = _cah_game_dat()
        patch = CahFactionsPatch(sides=["Rohan"])
        patch.apply(data)
        base_va, _off, _names, _term = _cave(data, patch)
        for va in cf._TABLE_REF_VAS:
            assert struct.unpack_from("<I", data, va - 0x400000)[0] == base_va
        for va in cf._TABLE_END_REF_VAS:
            # the stock-eight loops keep pointing at entry 8, so they still iterate eight sides
            assert struct.unpack_from("<I", data, va - 0x400000)[0] == base_va + cf._TABLE_END_DELTA
        assert (
            struct.unpack_from("<I", data, cf._DEFAULT_FACTION_USERDATA_VA - 0x400000)[0] == base_va
        )

    def test_scan_bound_grows_but_the_not_found_answer_stays_at_the_all_index(self):
        data = _cah_game_dat()
        patch = CahFactionsPatch(sides=["Rohan", "Lothlorien"])
        patch.apply(data)
        scan = cf._SCAN_BOUND_VA - 0x400000
        assert data[scan : scan + 3] == b"\x83\xfe" + bytes([patch.entry_count])  # cmp esi, 12
        # `push 9 / pop eax`: an unrecognised side resolves to the `All` entry, by design.
        assert data[scan + 5 : scan + 8] == b"\x6a\x09\x58"
        assert patch.entry_count == 12

    def test_wrapper_calls_the_stock_parser_and_expands_the_all_bit(self):
        data = _cah_game_dat()
        CahFactionsPatch(sides=["Rohan"]).apply(data)
        wrapper_va = struct.unpack_from("<I", data, cf._USABLE_FACTIONS_PARSER_VA - 0x400000)[0]
        off = va_to_offset(data, wrapper_va)
        code = bytes(data[off : off + 43])
        # the call at +16 lands exactly on the stock parser it wraps
        assert code[16] == 0xE8
        rel = struct.unpack_from("<i", code, 17)[0]
        assert wrapper_va + 16 + 5 + rel == cf._STOCK_PARSER_VA
        # ... and the bit it tests is the `All` entry's
        assert struct.unpack_from("<I", code, 30)[0] == 1 << cf.ALL_INDEX
        assert code.endswith(b"\xc7\x00\xff\xff\xff\xff\xc3")  # mask := all ones

    def test_rejects_the_wrong_build(self):
        data = _cah_game_dat()
        # a table whose first entry is not "Men" is not this build's side table
        struct.pack_into("<I", data, cf._SIDE_TABLE_VA - 0x400000, 0x00BF0000)
        with pytest.raises(ValueError, match="unexpected build"):
            CahFactionsPatch(sides=["Rohan"]).apply(data)

    def test_refuses_to_apply_twice(self):
        data = _cah_game_dat()
        CahFactionsPatch(sides=["Rohan"]).apply(data)
        with pytest.raises(ValueError, match="expected"):
            CahFactionsPatch(sides=["Rohan"]).apply(data)


class TestCahFactionsVerify:
    def test_rejects_an_unpatched_file(self):
        assert CahFactionsPatch(sides=["Rohan"]).verify(_cah_game_dat())

    def test_rejects_a_different_side_list(self):
        data = _cah_game_dat()
        CahFactionsPatch(sides=["Rohan"]).apply(data)
        assert CahFactionsPatch(sides=["Lothlorien"]).verify(data)
        assert CahFactionsPatch(sides=["Rohan", "Lothlorien"]).verify(data)
        assert CahFactionsPatch(sides=["Rohan"]).verify(data) == []


def _both_patches():
    return CommandSetLimitPatch(count=64), CahFactionsPatch(sides=["Rohan"])


def _section_rvas(data) -> list[int]:
    e = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, e + 6)[0]
    sectab = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
    return [struct.unpack_from("<I", data, sectab + i * 40 + 12)[0] for i in range(nsec)]


class TestPatchesCompose:
    """Both bundled patches allocate their cave past every existing section and locate it by
    name, so any subset applies in any order. See `Patch`'s composition contract."""

    @pytest.mark.parametrize("reverse", [False, True], ids=["commandset-first", "cah-first"])
    def test_either_order_applies_and_verifies(self, reverse):
        data = _cah_game_dat()
        _plant_commandset_sites(data)
        order = list(reversed(_both_patches())) if reverse else list(_both_patches())
        for patch in order:
            patch.apply(data)
        for patch in _both_patches():
            assert patch.verify(data) == [], f"{patch} failed after {[str(p) for p in order]}"

    @pytest.mark.parametrize("reverse", [False, True], ids=["commandset-first", "cah-first"])
    def test_either_order_keeps_the_section_table_rva_sorted(self, reverse):
        data = _cah_game_dat()
        _plant_commandset_sites(data)
        for patch in reversed(_both_patches()) if reverse else _both_patches():
            patch.apply(data)
        rvas = _section_rvas(data)
        assert rvas == sorted(rvas)
        # both caves exist, at distinct addresses, whichever went first
        cmdext, _o, _v = find_section(data, cs._SECTION_NAME)
        cahfac, _o, _v = find_section(data, cf._SECTION_NAME)
        assert cmdext != cahfac

    def test_a_lone_patch_lands_where_the_old_fixed_rva_put_it(self):
        # The RVA is computed now rather than hardcoded, but on an unpatched image it computes to
        # the same address the constant used to name - which is what keeps the byte-identity
        # reproduction of the shipped game.dat intact.
        data = _synthetic_game_dat()
        expected = image_base(data) + next_section_rva(data)
        CommandSetLimitPatch(count=64).apply(data)
        assert find_section(data, cs._SECTION_NAME)[0] == expected


class TestCahFactionsCli:
    def test_apply_then_verify_roundtrip(self, tmp_path):
        src = tmp_path / "game.dat.backup"
        src.write_bytes(bytes(_cah_game_dat()))
        out = tmp_path / "game.dat"
        rc = main(
            [
                "apply",
                "cah-factions",
                "--sides",
                "Rohan, Lothlorien",
                "--in",
                str(src),
                "--out",
                str(out),
            ]
        )
        assert rc == 0
        assert src.read_bytes() == bytes(_cah_game_dat())  # input left untouched
        assert main(["verify", "cah-factions", "--sides", "Rohan,Lothlorien", str(out)]) == 0

    def test_verify_exits_nonzero_on_mismatch(self, tmp_path):
        clean = tmp_path / "clean.dat"
        clean.write_bytes(bytes(_cah_game_dat()))
        assert main(["verify", "cah-factions", "--sides", "Rohan", str(clean)]) == 1

    def test_list_shows_the_patch(self, capsys):
        assert main(["list"]) == 0
        assert "cah-factions" in capsys.readouterr().out


@pytest.mark.skipif(
    not (_ENGINE / "game.dat.backup").exists() or not (_ENGINE / "game.dat").exists(),
    reason="requires the local game.dat.backup + shipped game.dat (not committed to CI)",
)
class TestGameDatReproduction:
    def test_build_matches_shipped_game_dat(self, tmp_path):
        out = tmp_path / "built.dat"
        apply_patches(_ENGINE / "game.dat.backup", [CommandSetLimitPatch(count=64)], output=out)
        assert out.read_bytes() == (_ENGINE / "game.dat").read_bytes()
