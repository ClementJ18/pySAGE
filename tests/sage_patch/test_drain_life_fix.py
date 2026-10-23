"""Tests for the drain-life-fix patch.

Eight edits and one cave. What could be wrong without raising is the reading behind them, so the
stock windows are disassembled: the three widened moves are the input's Bool at `+0x4C`, both hooked
damage calls go to the body-damage step, the stamp sites have the nugget in `esi`, and the `je`
turned into `jmp` is the one that skips the stock drain. `..._emulated.py` runs the cave.
"""

from __future__ import annotations

import pytest

from sage_patch.addresses import (
    DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE,
    DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE_BYTES,
    DAMAGE_INFO_INPUT_COPY_BYTE_MOVE,
    DAMAGE_INFO_INPUT_COPY_BYTE_MOVE_BYTES,
    DAMAGE_INFO_INPUT_CTOR_BYTE_STORE,
    DAMAGE_INFO_INPUT_CTOR_BYTE_STORE_BYTES,
    DAMAGE_NUGGET_ATTEMPT_CALL,
    DAMAGE_NUGGET_ATTEMPT_CALL_BYTES,
    DAMAGE_NUGGET_DRAIN,
    DAMAGE_NUGGET_DRAIN_BYTES,
    DAMAGE_NUGGET_DRAIN_SKIP,
    DOT_MANAGER_ADD,
    DOT_NUGGET_ADD_CALL,
    DOT_NUGGET_ADD_CALL_BYTES,
    OBJECT_ATTEMPT_DAMAGE,
    OBJECT_ATTEMPT_DAMAGE_NOW_CALL,
    OBJECT_ATTEMPT_DAMAGE_NOW_CALL_BYTES,
    OBJECT_ATTEMPT_HEALING,
    OBJECT_DAMAGE_NOW,
    OBJECT_DELAYED_DAMAGE_NOW_CALL,
    OBJECT_DELAYED_DAMAGE_NOW_CALL_BYTES,
)
from sage_patch.patches.drain_life_fix import (
    ANCHORS,
    SECTION_NAME,
    STOCK_WINDOWS,
    DrainLifeFixPatch,
    build_section,
    layout,
    pack_multiplier,
    unpack_multiplier,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.synthetic import drain_life_fix_image

BASE = 0x00F00000


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def ops(code: bytes, base: int) -> list[tuple[str, str]]:
    return [(i.mnemonic, i.op_str) for i in disassemble(code, base)]


def routine(name: str) -> list[tuple[str, str]]:
    at = layout(BASE)
    section = build_section(BASE)
    start = at[name]
    end = next((v for v in sorted(at.values()) if v > start), BASE + len(section))
    return ops(section[start - BASE : end - BASE], start)


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


@pytest.fixture
def patched() -> bytearray:
    data = drain_life_fix_image()
    DrainLifeFixPatch().apply(data)
    return data


class TestTheStockWindows:
    def test_the_three_moves_are_the_inputs_bool_at_0x4c(self):
        assert ops(DAMAGE_INFO_INPUT_CTOR_BYTE_STORE_BYTES, DAMAGE_INFO_INPUT_CTOR_BYTE_STORE) == [
            ("mov", "byte ptr [eax + 0x4c], cl")
        ]
        for va, stock in (
            (DAMAGE_INFO_INPUT_COPY_BYTE_MOVE, DAMAGE_INFO_INPUT_COPY_BYTE_MOVE_BYTES),
            (DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE, DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE_BYTES),
        ):
            assert ops(stock, va) == [
                ("mov", "dl, byte ptr [ecx + 0x4c]"),
                ("mov", "byte ptr [eax + 0x4c], dl"),
            ]

    @pytest.mark.parametrize(
        ("va", "stock"),
        [
            (OBJECT_ATTEMPT_DAMAGE_NOW_CALL, OBJECT_ATTEMPT_DAMAGE_NOW_CALL_BYTES),
            (OBJECT_DELAYED_DAMAGE_NOW_CALL, OBJECT_DELAYED_DAMAGE_NOW_CALL_BYTES),
        ],
    )
    def test_both_hit_sites_call_the_body_damage_step(self, va: int, stock: bytes):
        assert ops(stock, va) == [("call", hex(OBJECT_DAMAGE_NOW))]

    def test_the_stamp_sites_call_what_the_cave_tail_jumps_to(self):
        assert ops(DAMAGE_NUGGET_ATTEMPT_CALL_BYTES, DAMAGE_NUGGET_ATTEMPT_CALL) == [
            ("call", hex(OBJECT_ATTEMPT_DAMAGE))
        ]
        assert ops(DOT_NUGGET_ADD_CALL_BYTES, DOT_NUGGET_ADD_CALL) == [
            ("call", hex(DOT_MANAGER_ADD))
        ]

    def test_the_skipped_je_jumps_over_the_whole_stock_drain(self):
        drain = disassemble(DAMAGE_NUGGET_DRAIN_BYTES, DAMAGE_NUGGET_DRAIN)
        assert (drain[0].mnemonic, drain[0].op_str) == ("cmp", "byte ptr [esi + 0x1b4], 0")
        skip = next(i for i in drain if i.address == DAMAGE_NUGGET_DRAIN_SKIP)
        assert skip.mnemonic == "je"
        assert int(skip.op_str, 16) == DAMAGE_NUGGET_DRAIN + len(DAMAGE_NUGGET_DRAIN_BYTES)
        assert (drain[-1].mnemonic, int(drain[-1].op_str, 16)) == ("call", OBJECT_ATTEMPT_HEALING)
        # the amount is the multiplier times the output's damage dealt
        assert ("mulss", "xmm0, dword ptr [ebp - 0xc]") in [(i.mnemonic, i.op_str) for i in drain]


class TestTheCave:
    def test_damage_now_applies_the_hit_first_and_pops_its_argument(self):
        insns = routine("damage_now")
        assert ("and", "dword ptr [esi + 0x70], 0") in insns
        assert insns.index(("call", hex(OBJECT_DAMAGE_NOW))) < insns.index(
            ("call", hex(OBJECT_ATTEMPT_HEALING))
        )
        assert insns[-1] == ("ret", "4")

    @pytest.mark.parametrize(
        ("name", "target"),
        [("stamp_attempt", OBJECT_ATTEMPT_DAMAGE), ("stamp_dot", DOT_MANAGER_ADD)],
    )
    def test_the_stamps_tail_jump_to_what_they_replace(self, name: str, target: int):
        insns = routine(name)
        assert insns[0] == ("cmp", "byte ptr [esi + 0x1b4], 0")
        assert insns[-1] == ("jmp", hex(target))

    def test_it_disassembles_cleanly_to_its_end(self):
        section = build_section(BASE)
        assert sum(i.size for i in disassemble(section, BASE)) == len(section)

    @pytest.mark.parametrize("value", [0.5, 1.0, 0.25, 2.0, 1.5])
    def test_common_multipliers_survive_the_24_bit_round_trip(self, value: float):
        assert unpack_multiplier(pack_multiplier(value) | 0x01) == value

    def test_the_round_trip_keeps_five_digits(self):
        assert unpack_multiplier(pack_multiplier(0.3)) == pytest.approx(0.3, rel=1e-4)


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert DrainLifeFixPatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert DrainLifeFixPatch().verify(drain_life_fix_image())

    def test_the_sites_call_the_cave(self, patched: bytearray):
        at = layout(find_section(patched, SECTION_NAME)[0])
        for va in (OBJECT_ATTEMPT_DAMAGE_NOW_CALL, OBJECT_DELAYED_DAMAGE_NOW_CALL):
            assert _read(patched, va, 5) == call_rel32(va, at["damage_now"])
        assert _read(patched, DAMAGE_NUGGET_ATTEMPT_CALL, 5) == call_rel32(
            DAMAGE_NUGGET_ATTEMPT_CALL, at["stamp_attempt"]
        )
        assert _read(patched, DOT_NUGGET_ADD_CALL, 5) == call_rel32(
            DOT_NUGGET_ADD_CALL, at["stamp_dot"]
        )

    def test_the_widened_moves_are_dword_moves_of_the_same_length(self, patched: bytearray):
        assert ops(
            _read(patched, DAMAGE_INFO_INPUT_CTOR_BYTE_STORE, 3), DAMAGE_INFO_INPUT_CTOR_BYTE_STORE
        ) == [("mov", "dword ptr [eax + 0x4c], ecx")]
        for va in (DAMAGE_INFO_INPUT_COPY_BYTE_MOVE, DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE):
            assert ops(_read(patched, va, 6), va) == [
                ("mov", "edx, dword ptr [ecx + 0x4c]"),
                ("mov", "dword ptr [eax + 0x4c], edx"),
            ]

    def test_the_stock_drain_is_jumped_over(self, patched: bytearray):
        assert _read(patched, DAMAGE_NUGGET_DRAIN_SKIP, 2) == b"\xeb\x3b"

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            DrainLifeFixPatch().apply(patched)

    @pytest.mark.parametrize("va", [*sorted(ANCHORS), *sorted(STOCK_WINDOWS)])
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = drain_life_fix_image()
        data[va_to_offset(data, va)] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            DrainLifeFixPatch().apply(data)
        assert bytes(data) == before


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[DrainLifeFixPatch.name] is DrainLifeFixPatch

    def test_detect_finds_it_only_once_applied(self, patched: bytearray):
        assert DrainLifeFixPatch.detect(drain_life_fix_image()) is None
        assert isinstance(DrainLifeFixPatch.detect(patched), DrainLifeFixPatch)
