"""Tests for the replacement-transfer patch.

Six in-place edits and one cave. What could be wrong without raising is the reading behind each
edit, so the stock windows are disassembled and checked against it: each hook displaces whole
instructions, the registers the cave clobbers are dead where it rejoins, the two constructor
edits only widen a store, and the rebuilt tables keep every stock row. `..._emulated.py` runs the
caves.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    FIELD_PARSE_STRIDE,
    INI_PARSE_BIT_STRING_32,
    OBJECT_GIVE_UPGRADE,
    REPLACE_SELF_FIELD_TABLE_PUSH,
    REPLACE_SELF_FIELD_TABLE_STOCK,
    REPLACE_SELF_FREE_OFFSET,
    REPLACE_SELF_MODULE_DATA_LIST_INIT,
    REPLACE_SELF_MODULE_DATA_LIST_INIT_BYTES,
    REPLACE_SELF_MODULE_DATA_LIST_INIT_RESUME,
    REPLACE_SELF_NAME_COPY,
    REPLACE_SELF_NAME_COPY_BYTES,
    REPLACE_SELF_NAME_COPY_RESUME,
    SUMMON_REPLACEMENT_DEFAULT_STORES,
    SUMMON_REPLACEMENT_DEFAULT_STORES_BYTES,
    SUMMON_REPLACEMENT_FIELD_TABLE_PUSH,
    SUMMON_REPLACEMENT_FIELD_TABLE_STOCK,
    SUMMON_REPLACEMENT_FREE_OFFSET,
    SUMMON_REPLACEMENT_HEALTH_COPY_END,
    SUMMON_REPLACEMENT_HEALTH_COPY_END_BYTES,
    SUMMON_REPLACEMENT_XP_RESTORE,
    SUMMON_REPLACEMENT_XP_RESTORE_BYTES,
    SUMMON_REPLACEMENT_XP_RESTORE_RESUME,
    TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY,
    TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE,
)
from sage_patch.patches.replacement_transfer import (
    BLOCKS,
    FLAG_EXPERIENCE,
    FLAG_HEALTH,
    FLAG_HORDE,
    FLAG_PRODUCTION,
    FLAG_RALLY,
    FLAG_SELECTION,
    FLAG_UPGRADES,
    FLAGS,
    KEYWORD,
    SECTION_NAME,
    ReplacementTransferPatch,
    build_section,
    layout,
    rewritten_summon_defaults,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, jmp_rel32, va_to_offset
from tests.sage_patch.synthetic import replacement_transfer_image

BASE = 0x00F00000


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def ops(code: bytes, base: int) -> list[tuple[str, str]]:
    return [(i.mnemonic, i.op_str) for i in disassemble(code, base)]


def routine(name: str, base: int = BASE) -> list[tuple[str, str]]:
    """One cave routine's instructions, up to the next routine or the end of the section."""
    at = layout(base)
    starts = sorted(
        v for k, v in at.items() if k not in ("keyword", "name_list", "rsu_table", "summon_table")
    )
    start = at[name]
    section = build_section(base)
    end = next((s for s in starts if s > start), base + len(section))
    return ops(section[start - base : end - base], start)


def rows(blob: bytes) -> list[tuple[int, int, int, int]]:
    out = []
    for at in range(0, len(blob), FIELD_PARSE_STRIDE):
        row = struct.unpack_from("<IIII", blob, at)
        if row == (0, 0, 0, 0):
            return out
        out.append(row)
    raise AssertionError("unterminated table")


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


@pytest.fixture
def patched() -> bytearray:
    data = replacement_transfer_image()
    ReplacementTransferPatch().apply(data)
    return data


class TestTheStockWindows:
    def test_the_rsu_ctor_window_is_the_list_lea(self):
        insns = ops(REPLACE_SELF_MODULE_DATA_LIST_INIT_BYTES, REPLACE_SELF_MODULE_DATA_LIST_INIT)
        assert insns == [("lea", "esi, [edi + 0x138]")]
        assert REPLACE_SELF_FREE_OFFSET == 0x138 - 1

    def test_the_rsu_replace_window_is_the_name_copy_pair(self):
        insns = ops(REPLACE_SELF_NAME_COPY_BYTES, REPLACE_SELF_NAME_COPY)
        assert insns == [("lea", "eax, [ebp - 0x24]"), ("lea", "ecx, [edi + 0x88]")]
        assert REPLACE_SELF_NAME_COPY + len(REPLACE_SELF_NAME_COPY_BYTES) == (
            REPLACE_SELF_NAME_COPY_RESUME
        )

    def test_the_summon_window_restores_the_feedback_flag(self):
        insns = ops(SUMMON_REPLACEMENT_XP_RESTORE_BYTES, SUMMON_REPLACEMENT_XP_RESTORE)
        assert insns == [
            ("mov", "eax, dword ptr [esi + 0x26c]"),
            ("mov", "byte ptr [eax + 0x3c], 1"),
        ]
        assert SUMMON_REPLACEMENT_XP_RESTORE + len(SUMMON_REPLACEMENT_XP_RESTORE_BYTES) == (
            SUMMON_REPLACEMENT_XP_RESTORE_RESUME
        )

    def test_the_summon_rejoin_rewrites_eax_and_ecx_first(self):
        """The cave leaves eax and ecx changed; the stock code at the rejoin is
        `mount-health-ratio`'s pinned sequence, which loads both before reading either."""
        assert SUMMON_REPLACEMENT_XP_RESTORE_RESUME == TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY
        insns = ops(TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE, TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY)
        assert insns[:2] == [
            ("mov", "eax, dword ptr [esi + 0x25c]"),
            ("mov", "ecx, dword ptr [edi + 0x25c]"),
        ]

    def test_health_skips_exactly_the_stock_absolute_copy(self):
        """With `HEALTH` the summon hook resumes after the copy: the sequence ends in the
        `setHealth` call, and what follows starts fresh (`push 0xa` / `mov ecx, esi` / call)."""
        end = TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY + len(TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE)
        assert end == SUMMON_REPLACEMENT_HEALTH_COPY_END
        tail = ops(TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE, TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY)
        assert tail[-1] == ("call", "dword ptr [ebx + 0xac]")
        after = ops(SUMMON_REPLACEMENT_HEALTH_COPY_END_BYTES, SUMMON_REPLACEMENT_HEALTH_COPY_END)
        assert [m for m, _ in after] == ["push", "mov", "call"]

    def test_the_summon_ctor_stores_are_two_bytes_from_ebx(self):
        insns = ops(SUMMON_REPLACEMENT_DEFAULT_STORES_BYTES, SUMMON_REPLACEMENT_DEFAULT_STORES)
        assert insns == [
            ("mov", "byte ptr [esi + 0xe4], bl"),
            ("mov", "byte ptr [esi + 0xe5], bl"),
        ]

    def test_the_widened_store_clears_the_new_field(self):
        insns = ops(rewritten_summon_defaults(), SUMMON_REPLACEMENT_DEFAULT_STORES)
        assert insns[0] == ("mov", "dword ptr [esi + 0xe4], ebx")
        assert [m for m, _ in insns[1:]] == ["nop"]
        assert 0xE4 <= SUMMON_REPLACEMENT_FREE_OFFSET < 0xE8

    def test_the_new_offsets_are_not_any_stock_row(self):
        for stock, offset in (
            (REPLACE_SELF_FIELD_TABLE_STOCK, REPLACE_SELF_FREE_OFFSET),
            (SUMMON_REPLACEMENT_FIELD_TABLE_STOCK, SUMMON_REPLACEMENT_FREE_OFFSET),
        ):
            assert offset not in {row[3] for row in rows(stock)}


class TestTheTables:
    @pytest.mark.parametrize(
        ("key", "stock", "offset"),
        [
            ("rsu_table", REPLACE_SELF_FIELD_TABLE_STOCK, REPLACE_SELF_FREE_OFFSET),
            ("summon_table", SUMMON_REPLACEMENT_FIELD_TABLE_STOCK, SUMMON_REPLACEMENT_FREE_OFFSET),
        ],
    )
    def test_stock_rows_then_one_new_row(self, key: str, stock: bytes, offset: int):
        section = build_section(BASE)
        at = layout(BASE)
        table = rows(section[at[key] - BASE :])
        assert table[:-1] == rows(stock)
        assert table[-1] == (at["keyword"], at["parse"], at["name_list"], offset)

    def test_the_strings(self):
        section = build_section(BASE)
        at = layout(BASE)
        keyword = section[at["keyword"] - BASE :].split(b"\x00")[0]
        assert keyword.decode() == KEYWORD
        pointers = struct.unpack_from(f"<{len(FLAGS) + 1}I", section, at["name_list"] - BASE)
        names = [section[p - BASE :].split(b"\x00")[0].decode() for p in pointers[:-1]]
        assert tuple(names) == FLAGS
        assert pointers[-1] == 0
        assert [1 << FLAGS.index(n) for n in FLAGS] == [1, 2, 4, 8, 16, 32, 64]
        assert (FLAG_UPGRADES, FLAG_EXPERIENCE, FLAG_HEALTH, FLAG_SELECTION, FLAG_RALLY) == (
            1,
            2,
            4,
            8,
            16,
        )
        assert (FLAG_PRODUCTION, FLAG_HORDE) == (32, 64)


class TestTheCave:
    def test_parse_calls_the_stock_bit_string_parser(self):
        insns = routine("parse")
        assert ("call", hex(INI_PARSE_BIT_STRING_32)) in insns
        assert insns[-1] == ("ret", "")
        assert ("mov", "byte ptr [eax], cl") in insns  # one byte written back

    def test_transfer_keeps_callee_saved_registers_and_pops_its_arguments(self):
        insns = routine("transfer")
        assert insns[:5] == [
            ("push", "ebp"),
            ("mov", "ebp, esp"),
            ("push", "ebx"),
            ("push", "esi"),
            ("push", "edi"),
        ]
        assert insns[-5:] == [
            ("pop", "edi"),
            ("pop", "esi"),
            ("pop", "ebx"),
            ("pop", "ebp"),
            ("ret", "0xc"),
        ]
        assert ("call", hex(OBJECT_GIVE_UPGRADE)) in insns

    def test_the_rsu_hooks_replay_and_rejoin(self):
        ctor = routine("rsu_ctor")
        assert ctor == [
            ("mov", f"byte ptr [edi + {REPLACE_SELF_FREE_OFFSET:#x}], 0"),
            ("lea", "esi, [edi + 0x138]"),
            ("jmp", hex(REPLACE_SELF_MODULE_DATA_LIST_INIT_RESUME)),
        ]
        replace = routine("rsu_replace")
        assert replace[-3:] == [
            ("lea", "eax, [ebp - 0x24]"),
            ("lea", "ecx, [edi + 0x88]"),
            ("jmp", hex(REPLACE_SELF_NAME_COPY_RESUME)),
        ]
        assert ("push", "dword ptr [esi - 8]") in replace

    def test_the_summon_hook_replays_first(self):
        insns = routine("summon_replace")
        assert insns[:2] == ops(SUMMON_REPLACEMENT_XP_RESTORE_BYTES, 0)
        assert insns[-1] == ("jmp", hex(SUMMON_REPLACEMENT_XP_RESTORE_RESUME))

    def test_it_disassembles_cleanly_to_its_end(self):
        section = build_section(BASE)
        at = layout(BASE)
        code = section[at["parse"] - BASE :]
        assert sum(i.size for i in disassemble(code, at["parse"])) == len(code)


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert ReplacementTransferPatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert ReplacementTransferPatch().verify(replacement_transfer_image())

    def test_the_edits_point_into_the_section(self, patched: bytearray):
        base = find_section(patched, SECTION_NAME)[0]
        at = layout(base)
        assert _read(patched, REPLACE_SELF_FIELD_TABLE_PUSH, 5) == b"\x68" + struct.pack(
            "<I", at["rsu_table"]
        )
        assert _read(patched, SUMMON_REPLACEMENT_FIELD_TABLE_PUSH, 5) == b"\x68" + struct.pack(
            "<I", at["summon_table"]
        )
        assert _read(patched, REPLACE_SELF_NAME_COPY, 9) == jmp_rel32(
            REPLACE_SELF_NAME_COPY, at["rsu_replace"], 9
        )
        assert _read(patched, SUMMON_REPLACEMENT_XP_RESTORE, 10) == jmp_rel32(
            SUMMON_REPLACEMENT_XP_RESTORE, at["summon_replace"], 10
        )
        assert _read(patched, SUMMON_REPLACEMENT_DEFAULT_STORES, 12) == rewritten_summon_defaults()

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            ReplacementTransferPatch().apply(patched)

    @pytest.mark.parametrize(
        "va",
        [
            INI_PARSE_BIT_STRING_32,
            REPLACE_SELF_FIELD_TABLE_PUSH,
            REPLACE_SELF_MODULE_DATA_LIST_INIT,
            REPLACE_SELF_NAME_COPY,
            SUMMON_REPLACEMENT_FIELD_TABLE_PUSH,
            SUMMON_REPLACEMENT_DEFAULT_STORES,
            SUMMON_REPLACEMENT_XP_RESTORE,
        ],
    )
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = replacement_transfer_image()
        data[va_to_offset(data, va)] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            ReplacementTransferPatch().apply(data)
        assert bytes(data) == before


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[ReplacementTransferPatch.name] is ReplacementTransferPatch

    def test_detect_finds_it_only_once_applied(self, patched: bytearray):
        assert ReplacementTransferPatch.detect(replacement_transfer_image()) is None
        assert isinstance(ReplacementTransferPatch.detect(patched), ReplacementTransferPatch)

    def test_the_linter_learns_the_keyword_on_both_modules(self):
        fields = ReplacementTransferPatch().ini_surface().fields
        assert {(f.block, f.name, f.type) for f in fields} == {
            (block, KEYWORD, "Opaque[]") for block in BLOCKS
        }
