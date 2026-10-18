"""Tests for the production-death-no-refund patch.

Three edits: the `onDie` vtable slot and two refund hooks. What could be wrong without raising is
the reading behind them, so the stock bytes are disassembled and checked against it - the thunk
is the only way into slot 16 the vtable gives a death, cancel-all reaches the two cancels through
the slots whose refunds are hooked, and each hook skips exactly the deposit and nothing after it.
The caves are read back for the same contract; `..._emulated.py` runs them.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    MONEY_DEPOSIT,
    PRODUCTION_CANCEL_ALL,
    PRODUCTION_CANCEL_ALL_BYTES,
    PRODUCTION_CANCEL_UNIT_REFUND,
    PRODUCTION_CANCEL_UNIT_REFUND_BYTES,
    PRODUCTION_CANCEL_UNIT_REFUND_RESUME,
    PRODUCTION_CANCEL_UNIT_REFUND_SKIP,
    PRODUCTION_CANCEL_UPGRADE_REFUND,
    PRODUCTION_CANCEL_UPGRADE_REFUND_BYTES,
    PRODUCTION_CANCEL_UPGRADE_REFUND_RESUME,
    PRODUCTION_CANCEL_UPGRADE_REFUND_SKIP,
    PRODUCTION_ON_DIE,
    PRODUCTION_ON_DIE_BYTES,
    PRODUCTION_ON_DIE_SLOT,
    PRODUCTION_ON_LOSS,
    PRODUCTION_ON_LOSS_BYTES,
)
from sage_patch.patches.production_death_no_refund import (
    ANCHORS,
    FLAG_OFF,
    SECTION_NAME,
    UNIT_HOOK_WIDTH,
    UPGRADE_HOOK_WIDTH,
    ProductionDeathNoRefundPatch,
    build_section,
    layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, jmp_rel32, va_to_offset
from tests.sage_patch.synthetic import production_death_no_refund_image

BASE = 0x00F00000
#: Interface slots, as byte offsets into `PRODUCTION_UPDATE_INTERFACE_VTABLE`.
SLOT_CANCEL_UPGRADE = 0x10
SLOT_CANCEL_UNIT = 0x28
SLOT_CANCEL_ALL = 0x3C
SLOT_ON_LOSS = 0x40


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def ops(code: bytes, base: int) -> list[tuple[str, str]]:
    return [(i.mnemonic, i.op_str) for i in disassemble(code, base)]


def routine(name: str, base: int = BASE) -> list[tuple[str, str]]:
    """The instructions of one cave routine, up to the next routine or the end."""
    at = layout(base)
    starts = sorted(v for k, v in at.items() if k != "flag")
    start = at[name]
    end = next((s for s in starts if s > start), base + len(build_section(base)))
    section = build_section(base)
    return ops(section[start - base : end - base], start)


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


@pytest.fixture
def patched() -> bytearray:
    data = production_death_no_refund_image()
    ProductionDeathNoRefundPatch().apply(data)
    return data


class TestTheStockPath:
    def test_the_thunk_steps_to_the_interface_and_calls_slot_16(self):
        """`+0x24` minus 4 is the interface at `+0x20`, and `+0x40` is its slot 16."""
        assert ops(PRODUCTION_ON_DIE_BYTES, PRODUCTION_ON_DIE) == [
            ("add", "ecx, -4"),
            ("mov", "eax, dword ptr [ecx]"),
            ("call", f"dword ptr [eax + {SLOT_ON_LOSS:#x}]"),
            ("ret", "4"),
        ]

    def test_slot_16_calls_cancel_all_through_slot_15(self):
        insns = ops(PRODUCTION_ON_LOSS_BYTES, PRODUCTION_ON_LOSS)
        assert insns[-1] == ("call", f"dword ptr [eax + {SLOT_CANCEL_ALL:#x}]")
        assert ("mov", "esi, ecx") in insns  # this, the interface

    def test_cancel_all_raises_cancel_regardless_and_drains_the_queue(self):
        insns = ops(PRODUCTION_CANCEL_ALL_BYTES, PRODUCTION_CANCEL_ALL)
        assert insns[2] == ("mov", "byte ptr [esi + 0xfd], 1")
        assert ("cmp", "dword ptr [esi + 8], 0") in insns  # the queue head
        assert ("call", f"dword ptr [edx + {SLOT_CANCEL_UNIT:#x}]") in insns
        assert ("call", f"dword ptr [edx + {SLOT_CANCEL_UPGRADE:#x}]") in insns
        assert ("mov", "byte ptr [esi + 0xfd], 0") in insns

    def test_the_upgrade_refund_is_the_deposit_and_nothing_else(self):
        insns = disassemble(
            PRODUCTION_CANCEL_UPGRADE_REFUND_BYTES, PRODUCTION_CANCEL_UPGRADE_REFUND
        )
        last = insns[-1]
        assert (last.mnemonic, int(last.op_str, 16)) == ("call", MONEY_DEPOSIT)
        assert last.address + last.size == PRODUCTION_CANCEL_UPGRADE_REFUND_SKIP
        assert ("push", "dword ptr [esi + 0x28]") in [(i.mnemonic, i.op_str) for i in insns]

    def test_the_upgrade_hook_is_whole_instructions_before_any_push_it_skips(self):
        insns = disassemble(
            PRODUCTION_CANCEL_UPGRADE_REFUND_BYTES, PRODUCTION_CANCEL_UPGRADE_REFUND
        )
        head = [i for i in insns if i.address < PRODUCTION_CANCEL_UPGRADE_REFUND_RESUME]
        assert [(i.mnemonic, i.op_str) for i in head] == [
            ("mov", "eax, dword ptr [ebp + 8]"),
            ("push", "1"),
        ]
        assert sum(i.size for i in head) == UPGRADE_HOOK_WIDTH

    def test_the_unit_refund_is_gated_then_deposits_then_tallies(self):
        insns = disassemble(PRODUCTION_CANCEL_UNIT_REFUND_BYTES, PRODUCTION_CANCEL_UNIT_REFUND)
        assert (insns[0].mnemonic, insns[0].op_str) == ("cmp", "byte ptr [ebp - 1], 0")
        assert (insns[1].mnemonic, insns[1].op_str) == ("mov", "edi, eax")
        gate = insns[2]
        assert (gate.mnemonic, int(gate.op_str, 16)) == ("jne", PRODUCTION_CANCEL_UNIT_REFUND_SKIP)
        assert gate.address + gate.size == PRODUCTION_CANCEL_UNIT_REFUND_RESUME
        assert sum(i.size for i in insns[:3]) == UNIT_HOOK_WIDTH
        calls = [int(i.op_str, 16) for i in insns if i.mnemonic == "call"]
        assert calls[0] == MONEY_DEPOSIT and len(calls) == 2
        assert insns[-1].address + insns[-1].size == PRODUCTION_CANCEL_UNIT_REFUND_SKIP


class TestTheCave:
    def test_the_flag_starts_down(self):
        assert build_section(BASE)[FLAG_OFF] == 0

    def test_on_die_raises_the_flag_only_around_the_stock_thunk(self):
        flag = f"byte ptr [{BASE + FLAG_OFF:#x}]"
        assert routine("on_die") == [
            ("mov", f"{flag}, 1"),
            ("push", "dword ptr [esp + 4]"),
            ("call", hex(PRODUCTION_ON_DIE)),
            ("mov", f"{flag}, 0"),
            ("ret", "4"),
        ]

    def test_the_upgrade_gate_replays_the_stock_head_or_skips_the_deposit(self):
        flag = f"byte ptr [{BASE + FLAG_OFF:#x}]"
        insns = routine("upgrade_gate")
        assert insns[0] == ("cmp", f"{flag}, 0")
        assert insns[1][0] == "jne"
        assert insns[2:5] == [
            ("mov", "eax, dword ptr [ebp + 8]"),
            ("push", "1"),
            ("jmp", hex(PRODUCTION_CANCEL_UPGRADE_REFUND_RESUME)),
        ]
        assert insns[5] == ("jmp", hex(PRODUCTION_CANCEL_UPGRADE_REFUND_SKIP))

    def test_the_unit_gate_keeps_the_stock_gate_ahead_of_the_flag(self):
        flag = f"byte ptr [{BASE + FLAG_OFF:#x}]"
        insns = routine("unit_gate")
        skip = ("jmp", hex(PRODUCTION_CANCEL_UNIT_REFUND_SKIP))
        assert insns[0] == ("mov", "edi, eax")
        assert insns[1] == ("cmp", "byte ptr [ebp - 1], 0")
        assert insns[3] == ("cmp", f"{flag}, 0")
        assert insns[5] == ("jmp", hex(PRODUCTION_CANCEL_UNIT_REFUND_RESUME))
        assert insns[6] == skip

    def test_it_disassembles_cleanly_to_its_end(self):
        section = build_section(BASE)
        code = section[FLAG_OFF + 4 :]
        assert sum(i.size for i in disassemble(code, BASE + 4)) == len(code)


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert ProductionDeathNoRefundPatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert ProductionDeathNoRefundPatch().verify(production_death_no_refund_image())

    def test_the_hooks_point_into_the_section(self, patched: bytearray):
        located = find_section(patched, SECTION_NAME)
        assert located is not None
        base, off, _ = located
        at = layout(base)
        slot = struct.unpack("<I", _read(patched, PRODUCTION_ON_DIE_SLOT, 4))[0]
        assert slot == at["on_die"]
        assert _read(patched, PRODUCTION_CANCEL_UPGRADE_REFUND, UPGRADE_HOOK_WIDTH) == jmp_rel32(
            PRODUCTION_CANCEL_UPGRADE_REFUND, at["upgrade_gate"], UPGRADE_HOOK_WIDTH
        )
        assert _read(patched, PRODUCTION_CANCEL_UNIT_REFUND, UNIT_HOOK_WIDTH) == jmp_rel32(
            PRODUCTION_CANCEL_UNIT_REFUND, at["unit_gate"], UNIT_HOOK_WIDTH
        )
        section = build_section(base)
        assert bytes(patched[off : off + len(section)]) == section

    def test_the_anchors_are_untouched(self, patched: bytearray):
        for va, blob in ANCHORS.items():
            assert _read(patched, va, len(blob)) == blob

    def test_the_refund_runs_change_only_at_their_hooks(self, patched: bytearray):
        for va, blob, width in (
            (PRODUCTION_CANCEL_UPGRADE_REFUND, PRODUCTION_CANCEL_UPGRADE_REFUND_BYTES, 5),
            (PRODUCTION_CANCEL_UNIT_REFUND, PRODUCTION_CANCEL_UNIT_REFUND_BYTES, 8),
        ):
            assert _read(patched, va + width, len(blob) - width) == blob[width:]

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            ProductionDeathNoRefundPatch().apply(patched)

    @pytest.mark.parametrize(
        "va",
        [
            *sorted(ANCHORS),
            PRODUCTION_ON_DIE_SLOT,
            PRODUCTION_CANCEL_UPGRADE_REFUND,
            PRODUCTION_CANCEL_UNIT_REFUND,
        ],
    )
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = production_death_no_refund_image()
        off = va_to_offset(data, va)
        data[off] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            ProductionDeathNoRefundPatch().apply(data)
        assert bytes(data) == before


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[ProductionDeathNoRefundPatch.name] is ProductionDeathNoRefundPatch

    def test_detect_finds_it_only_once_applied(self, patched: bytearray):
        assert ProductionDeathNoRefundPatch.detect(production_death_no_refund_image()) is None
        assert isinstance(
            ProductionDeathNoRefundPatch.detect(patched), ProductionDeathNoRefundPatch
        )
