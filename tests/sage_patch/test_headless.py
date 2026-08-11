"""Tests for the headless patch.

Two things are worth checking statically and cannot be checked any other way. The cave is
hand-assembled x86 that nothing here can execute, so the tests that matter disassemble it back
and assert it says what it was meant to say - a wrong byte in the draw hook does not raise, it
crashes the game. And the extended command-line table is dispatched to *by index*, so a row that
names the wrong string or points outside the cave is a jump into whatever happens to be there.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    CLI_COUNT_REF,
    CLI_DISPATCH,
    CLI_TABLE,
    CLI_TABLE_BYTES,
    CLI_TABLE_ENTRIES,
    CLI_TABLE_FINGERPRINT,
    CLI_TABLE_REF,
    GAME_CLIENT_DRAW,
    GAME_CLIENT_DRAW_BYTES,
)
from sage_patch.patches.headless import (
    COUNTER_OFFSET,
    DEFAULT_RENDER_EVERY,
    OPTIONS,
    RENDER_EVERY_OFFSET,
    SECTION_NAME,
    STATE_SIZE,
    TAG,
    TAG_OFFSET,
    HeadlessPatch,
    build_code,
    table_offset_in_section,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

#: The stock table, as it stands in `game.dat` at `0x00C35DA8`: sixteen `{name, handler}` rows,
#: with the real name strings at the real addresses they are stored at (fifteen of them sit
#: immediately after the table, and `-win` alone points off into `.rdata` a long way away).
#:
#: Planted in full rather than fingerprinted, because what these tests check is that the copy the
#: cave makes is *verbatim* - a stand-in carrying placeholder rows could not tell a faithful copy
#: from a rebuilt one.
STOCK_ROWS: tuple[tuple[int, str, int], ...] = (
    (0x00C35ED4, "-noshellmap", 0x007B9EC7),
    (0x00C35ECC, "-mod", 0x007BADB9),
    (0x00C35EC0, "-noaudio", 0x007BA024),
    (0x00C35EB8, "-xres", 0x007BA104),
    (0x00C35EB0, "-yres", 0x007BA131),
    (0x00BD166C, "-win", 0x007B9FC6),
    (0x00C35EA0, "-scriptDebug2", 0x007BA1D4),
    (0x00C35E8C, "-scriptDebugLite", 0x007BA1FB),
    (0x00C35E7C, "-fullVersion", 0x007BA0B0),
    (0x00C35E68, "-preferLocalFiles", 0x007B9EBE),
    (0x00C35E5C, "-Watchdog", 0x007B9F36),
    (0x00C35E50, "-noWatchdog", 0x007B9F5A),
    (0x00C35E48, "-rif", 0x007B9F3F),
    (0x00C35E40, "-file", 0x007BACA4),
    (0x00C35E34, "-resumeGame", 0x007BACE3),
    (0x00C35E28, "-randomSeed", 0x007BA795),
)

STOCK_TABLE = b"".join(struct.pack("<II", name_va, handler) for name_va, _, handler in STOCK_ROWS)


def headless_image() -> bytearray:
    """A stand-in carrying the command-line table and its strings, the two instructions that hand
    the table to the dispatcher, the dispatcher's own entry, and the draw call.

    The sites are ~6 MB apart in an 11 MB binary, so a sparse image maps four pages rather than
    all of it.
    """
    planted: dict[int, bytes] = {
        CLI_TABLE: STOCK_TABLE,
        CLI_TABLE_REF: b"\xbb" + struct.pack("<I", CLI_TABLE),
        CLI_COUNT_REF: bytes((0x6A, CLI_TABLE_ENTRIES)),
        CLI_DISPATCH: bytes.fromhex("558bec"),  # push ebp / mov ebp, esp
        GAME_CLIENT_DRAW: GAME_CLIENT_DRAW_BYTES,
    }
    for name_va, name, _ in STOCK_ROWS:
        planted[name_va] = name.encode("ascii") + b"\x00"
    return _sparse_image(planted)


def _cave(data: bytes | bytearray) -> tuple[int, int, int]:
    """``(base_va, table_va, hook_va)`` for the applied patch."""
    section = find_section(data, SECTION_NAME)
    assert section is not None
    base_va = section[0]
    return base_va, base_va + table_offset_in_section(base_va, STOCK_TABLE), base_va + STATE_SIZE


def _read(data: bytes | bytearray, va: int, length: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"{va:#010x} is not mapped"
    return bytes(data[off : off + length])


def _applied() -> bytearray:
    data = headless_image()
    HeadlessPatch().apply(data)
    return data


class TestApply:
    def test_applies_and_verifies(self):
        assert HeadlessPatch().verify(_applied()) == []

    def test_absent_from_an_unpatched_image(self):
        problems = HeadlessPatch().verify(headless_image())
        assert problems == [f"no {SECTION_NAME} section: the file does not carry this patch"]

    def test_detect_finds_it(self):
        assert HeadlessPatch.detect(headless_image()) is None
        found = HeadlessPatch.detect(_applied())
        assert isinstance(found, HeadlessPatch)

    def test_applying_twice_raises(self):
        data = _applied()
        with pytest.raises(ValueError):
            HeadlessPatch().apply(data)

    def test_cave_lands_past_every_existing_section(self):
        data = _applied()
        base_va = _cave(data)[0]
        e = struct.unpack_from("<I", data, 0x3C)[0]
        count = struct.unpack_from("<H", data, e + 6)[0]
        sectab = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
        ends = [
            struct.unpack_from("<I", data, sectab + i * 40 + 12)[0]
            + struct.unpack_from("<I", data, sectab + i * 40 + 8)[0]
            for i in range(count - 1)  # every section but the one just appended
        ]
        assert base_va - 0x400000 >= max(ends)


class TestTable:
    def test_pointer_and_count_are_repointed_together(self):
        data = _applied()
        _, table_va, _ = _cave(data)
        assert _read(data, CLI_TABLE_REF, 5) == b"\xbb" + struct.pack("<I", table_va)
        assert _read(data, CLI_COUNT_REF, 2) == bytes((0x6A, CLI_TABLE_ENTRIES + len(OPTIONS)))

    def test_count_edit_keeps_its_length(self):
        """`push imm8` is two bytes and must stay two: the instruction after it is the `call`
        into the dispatcher, and anything longer would overwrite it."""
        data = _applied()
        assert _read(data, CLI_COUNT_REF, 1) == b"\x6a"
        assert CLI_TABLE_ENTRIES + len(OPTIONS) <= 127

    def test_stock_rows_are_copied_verbatim(self):
        data = _applied()
        _, table_va, _ = _cave(data)
        assert _read(data, table_va, CLI_TABLE_BYTES) == STOCK_TABLE
        assert _read(data, CLI_TABLE, CLI_TABLE_BYTES) == STOCK_TABLE  # and the original is intact

    def test_appended_rows_name_the_options_and_dispatch_into_the_cave(self):
        data = _applied()
        base_va, table_va, _ = _cave(data)
        for index, (option, _) in enumerate(OPTIONS):
            name_va, handler_va = struct.unpack_from(
                "<II", _read(data, table_va + CLI_TABLE_BYTES + index * 8, 8)
            )
            assert _read(data, name_va, len(option) + 1) == option.encode() + b"\x00"
            assert base_va + STATE_SIZE <= handler_va < table_va

    def test_no_new_option_can_shadow_a_stock_one(self):
        """The dispatcher matches with `_strnicmp` over *equal lengths*, so a new name is
        unreachable if a stock row of the same length spells the same letters and comes first."""
        stock = [name for _, name, _ in STOCK_ROWS]
        for option, _ in OPTIONS:
            clashes = [s for s in stock if len(s) == len(option) and s.lower() == option.lower()]
            assert clashes == [], f"{option} is shadowed by {clashes}"

    def test_options_are_distinct(self):
        names = [option.lower() for option, _ in OPTIONS]
        assert len(set(names)) == len(names)


class TestDrawHook:
    def test_call_site_becomes_a_call_padded_to_length(self):
        data = _applied()
        _, _, hook_va = _cave(data)
        patched = _read(data, GAME_CLIENT_DRAW, len(GAME_CLIENT_DRAW_BYTES))
        assert len(patched) == len(GAME_CLIENT_DRAW_BYTES)
        assert patched[:1] == b"\xe8"
        target = GAME_CLIENT_DRAW + 5 + struct.unpack_from("<i", patched, 1)[0]
        assert target == hook_va
        assert patched[5:] == b"\x90" * (len(GAME_CLIENT_DRAW_BYTES) - 5)

    def test_hook_reissues_the_displaced_instructions_verbatim(self):
        """The three instructions the redirect overwrites have to come back byte for byte -
        rewriting them by hand is how a hook ends up calling the wrong vtable slot."""
        code = build_code(0x00F00010).finish()
        assert GAME_CLIENT_DRAW_BYTES in code

    def test_state_block_starts_at_stock_behaviour(self):
        data = _applied()
        base_va = _cave(data)[0]
        tag, render_every, counter = struct.unpack_from("<III", _read(data, base_va, STATE_SIZE))
        assert (tag, render_every, counter) == (TAG, DEFAULT_RENDER_EVERY, 0)
        assert (TAG_OFFSET, RENDER_EVERY_OFFSET, COUNTER_OFFSET) == (0, 4, 8)

    def test_hook_disassembles_as_intended(self):
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        base = 0x00F00000
        asm = build_code(base + STATE_SIZE)
        instructions = list(md.disasm(asm.finish(), base + STATE_SIZE))

        text = [f"{i.mnemonic} {i.op_str}".strip() for i in instructions]
        hook = text[: text.index("ret") + 1]
        assert hook == [
            f"mov ecx, dword ptr [{base + RENDER_EVERY_OFFSET:#x}]",
            "test ecx, ecx",
            f"je {base + STATE_SIZE + 0x28:#x}",
            f"mov eax, dword ptr [{base + COUNTER_OFFSET:#x}]",
            "inc eax",
            f"mov dword ptr [{base + COUNTER_OFFSET:#x}], eax",
            "xor edx, edx",
            "div ecx",  # edx = counter % render_every
            "test edx, edx",
            f"jne {base + STATE_SIZE + 0x28:#x}",
            "mov ecx, dword ptr [0xde4418]",  # TheDisplay
            "mov eax, dword ptr [ecx]",
            "call dword ptr [eax + 0x30]",  # Display::draw
            "ret",
        ]
        # Both skip paths land on the `ret`, not past it or into the next routine.
        assert instructions[len(hook) - 1].address == base + STATE_SIZE + 0x28

    def test_every_routine_ends_in_a_return(self):
        """Each handler is `call`ed by the dispatcher and the hook by `GameClient::update`, so a
        routine that falls through into the next one corrupts the stack rather than the answer."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        asm = build_code(0x00F00010)
        code = asm.finish()
        assert code.endswith(b"\xc3")

        starts = sorted(asm.label_va(label) for _, label in OPTIONS)
        for start in starts:
            # the byte before each routine's entry is the previous routine's `ret`
            assert code[start - 0x00F00010 - 1] == 0xC3

        # every handler answers with the number of arguments it consumed, and nothing else
        ends = starts[1:] + [0x00F00010 + len(code)]
        for (option, label), end in zip(OPTIONS, ends, strict=True):
            body = code[asm.label_va(label) - 0x00F00010 : end - 0x00F00010]
            answers = {
                struct.unpack_from("<I", i.bytes, 1)[0]
                for i in md.disasm(body, asm.label_va(label))
                if i.mnemonic == "mov" and i.op_str.startswith("eax, ") and i.bytes[0] == 0xB8
            }
            assert answers, f"{option} never sets a return value"
            assert answers <= {1, 2}, f"{option} returns {answers}"


class TestBuildChecks:
    def test_a_table_that_names_something_else_is_refused(self):
        data = headless_image()
        index, expected = next(iter(CLI_TABLE_FINGERPRINT.items()))
        off = va_to_offset(data, CLI_TABLE + index * 8)
        assert off is not None
        struct.pack_into("<I", data, off, STOCK_ROWS[1][0])  # point the row at another name
        with pytest.raises(ValueError, match="is not this build's option table"):
            HeadlessPatch().apply(data)
        assert expected  # the row really did name something specific

    def test_a_dispatcher_that_is_not_a_function_entry_is_refused(self):
        data = headless_image()
        off = va_to_offset(data, CLI_DISPATCH)
        assert off is not None
        data[off : off + 3] = b"\x90\x90\x90"
        with pytest.raises(ValueError, match="command-line dispatcher"):
            HeadlessPatch().apply(data)

    def test_a_moved_draw_site_is_refused(self):
        data = headless_image()
        off = va_to_offset(data, GAME_CLIENT_DRAW)
        assert off is not None
        data[off + 2] = (data[off + 2] + 1) & 0xFF  # a different global
        with pytest.raises(ValueError, match="draw call is not this build's"):
            HeadlessPatch().apply(data)
        # refused before anything was allocated, so the image is untouched
        assert find_section(data, SECTION_NAME) is None


class TestVerifyCatchesTampering:
    def test_a_half_applied_table_edit(self):
        data = _applied()
        off = va_to_offset(data, CLI_COUNT_REF)
        assert off is not None
        data[off + 1] = CLI_TABLE_ENTRIES  # count put back, pointer left repointed
        problems = HeadlessPatch().verify(data)
        assert any("table length" in p for p in problems)

    def test_a_restored_draw_call(self):
        data = _applied()
        off = va_to_offset(data, GAME_CLIENT_DRAW)
        assert off is not None
        data[off : off + len(GAME_CLIENT_DRAW_BYTES)] = GAME_CLIENT_DRAW_BYTES
        problems = HeadlessPatch().verify(data)
        assert any("Display::draw redirect" in p for p in problems)

    def test_an_appended_row_pointing_outside_the_cave(self):
        data = _applied()
        _, table_va, _ = _cave(data)
        off = va_to_offset(data, table_va + CLI_TABLE_BYTES + 4)
        assert off is not None
        struct.pack_into("<I", data, off, 0x007B9EC7)  # a stock handler, not ours
        problems = HeadlessPatch().verify(data)
        assert any("outside the" in p for p in problems)
