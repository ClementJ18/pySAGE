"""Tests for the player-upgrade-discount patch.

The cave replaces `Player::getUpgradeDiscount` at its one call site in the upgrade price function,
so it has to keep that routine's whole contract: `__thiscall`, the name by value, `ret 4`, the
argument destroyed, the sum in `st0`. None of that raises when wrong - a bad stack balance or an
undestroyed string only shows up in game - so the tests disassemble the cave and check it.
"""

from __future__ import annotations

import pytest

from sage_patch.addresses import (
    ASCII_STRING_DTOR,
    PLAYER_GET_UPGRADE_DISCOUNT,
    PLAYER_GET_UPGRADE_DISCOUNT_BODY,
    UPGRADE_DISCOUNT_CALL,
    UPGRADE_DISCOUNT_CALL_BYTES,
    UPGRADE_DISCOUNT_ENTRY_VALUE,
    UPGRADE_DISCOUNT_GATE,
    UPGRADE_DISCOUNT_GATE_BYTES,
    UPGRADE_DISCOUNT_TYPE_BRANCH,
    UPGRADE_DISCOUNT_TYPE_BRANCH_BYTES,
)
from sage_patch.patches.player_upgrade_discount import (
    ENTRY_SIZE,
    SECTION_NAME,
    UPGRADE_TYPE_OBJECT,
    PlayerUpgradeDiscountPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import player_upgrade_discount_image

BASE = 0x00F00000


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def cave():
    return disassemble(build_code(BASE), BASE)


def target(insn) -> int:
    return int(insn.op_str, 16)


def stock_sum():
    return disassemble(PLAYER_GET_UPGRADE_DISCOUNT_BODY, PLAYER_GET_UPGRADE_DISCOUNT)


class TestTheStockSites:
    def test_the_gate_block_ends_on_the_discount_call(self):
        """The two sites the patch edits lie inside the block it anchors, where it says they are."""
        at = {i.address: i for i in disassemble(UPGRADE_DISCOUNT_GATE_BYTES, UPGRADE_DISCOUNT_GATE)}
        branch = at[UPGRADE_DISCOUNT_TYPE_BRANCH]
        assert branch.mnemonic == "jne" and branch.bytes == UPGRADE_DISCOUNT_TYPE_BRANCH_BYTES
        call = at[UPGRADE_DISCOUNT_CALL]
        assert call.bytes == UPGRADE_DISCOUNT_CALL_BYTES
        assert target(call) == PLAYER_GET_UPGRADE_DISCOUNT

    def test_the_branch_tests_type_against_object(self):
        """The `jne` is the OBJECT-only gate because it follows `cmp [esi+4], 1` on the template."""
        first = disassemble(UPGRADE_DISCOUNT_GATE_BYTES, UPGRADE_DISCOUNT_GATE)[0]
        assert first.op_str == f"dword ptr [esi + 4], {UPGRADE_TYPE_OBJECT}"

    def test_esi_points_at_the_name_when_the_call_is_made(self):
        """The cave reads `Type` at `[esi-4]`, which holds only once `add esi, 8` has run."""
        insns = disassemble(UPGRADE_DISCOUNT_GATE_BYTES, UPGRADE_DISCOUNT_GATE)
        adds = [i for i in insns if i.mnemonic == "add" and i.op_str.startswith("esi")]
        assert [i.op_str for i in adds] == ["esi, 8"]
        assert adds[0].address < UPGRADE_DISCOUNT_CALL


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        assert sum(i.size for i in cave()) == len(build_code(BASE))

    def test_an_object_upgrade_goes_to_the_stock_sum_untouched(self):
        """No push, no frame, before the tail jump: the stock routine must see the same stack."""
        insns = cave()
        assert (insns[0].mnemonic, insns[0].op_str) == ("cmp", "dword ptr [esi - 4], 1")
        assert insns[1].mnemonic == "jne"
        assert (insns[2].mnemonic, target(insns[2])) == ("jmp", PLAYER_GET_UPGRADE_DISCOUNT)

    def test_the_player_loop_skips_an_entry_with_no_list(self):
        insns = cave()
        cmp = next(i for i in insns if i.op_str == "eax, dword ptr [esi + 0x18]")
        prev = insns[insns.index(cmp) - 1]
        assert prev.op_str == "eax, dword ptr [esi + 0x14]"
        skip = insns[insns.index(cmp) + 1]
        assert skip.mnemonic == "je"
        landing = next(i for i in insns if i.address == target(skip))
        assert (landing.mnemonic, landing.op_str) == ("add", f"esi, {ENTRY_SIZE:#x}")

    def test_it_walks_the_same_vector_as_the_stock_sum(self):
        """Its vector offsets, stride and per-entry helper, taken from the stock routine itself."""

        def shape(insns):
            return (
                [i.op_str for i in insns if "0x3d" in i.op_str],
                [i.op_str for i in insns if i.mnemonic == "add" and i.op_str.startswith("esi")],
                {target(i) for i in insns if i.mnemonic == "call"},
            )

        mine, stock = shape(cave()), shape(stock_sum())
        assert mine == stock
        assert mine[2] == {UPGRADE_DISCOUNT_ENTRY_VALUE, ASCII_STRING_DTOR}

    def test_it_keeps_the_stock_calling_contract(self):
        """Callee-saved registers restored, the argument popped, the sum left in `st0`."""
        tail = [(i.mnemonic, i.op_str) for i in cave()[-5:]]
        assert tail == [
            ("fld", "dword ptr [ebp - 4]"),
            ("pop", "edi"),
            ("pop", "esi"),
            ("leave", ""),
            ("ret", "4"),
        ]
        stock_tail = [(i.mnemonic, i.op_str) for i in stock_sum()[-5:]]
        assert tail == stock_tail

    def test_the_argument_is_destroyed_before_returning(self):
        insns = cave()
        dtor = next(i for i in insns if i.mnemonic == "call" and target(i) == ASCII_STRING_DTOR)
        assert insns[insns.index(dtor) - 1].op_str == "ecx, [ebp + 8]"

    def test_every_conditional_branch_stays_inside_the_cave(self):
        lo, hi = BASE, BASE + len(build_code(BASE))
        for ins in cave():
            if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
                assert lo <= target(ins) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b and len(a) == len(b)


class TestApply:
    def test_apply_then_verify_and_detect(self):
        data = player_upgrade_discount_image()
        PlayerUpgradeDiscountPatch().apply(data)
        assert PlayerUpgradeDiscountPatch().verify(data) == []
        assert PlayerUpgradeDiscountPatch.detect(data) is not None

    def test_an_unpatched_image_is_not_detected(self):
        assert PlayerUpgradeDiscountPatch.detect(player_upgrade_discount_image()) is None

    def test_it_edits_only_the_branch_and_the_call(self):
        before = player_upgrade_discount_image()
        data = player_upgrade_discount_image()
        PlayerUpgradeDiscountPatch().apply(data)
        start = va_to_offset(data, UPGRADE_DISCOUNT_GATE)
        changed = {
            UPGRADE_DISCOUNT_GATE + k
            for k in range(len(UPGRADE_DISCOUNT_GATE_BYTES))
            if data[start + k] != before[start + k]
        }
        branch = set(range(UPGRADE_DISCOUNT_TYPE_BRANCH, UPGRADE_DISCOUNT_TYPE_BRANCH + 2))
        call = set(range(UPGRADE_DISCOUNT_CALL, UPGRADE_DISCOUNT_CALL + 5))
        assert changed <= branch | call
        assert branch <= changed  # both branch bytes become nops
        stock = va_to_offset(data, PLAYER_GET_UPGRADE_DISCOUNT)
        body = bytes(data[stock : stock + len(PLAYER_GET_UPGRADE_DISCOUNT_BODY)])
        assert body == PLAYER_GET_UPGRADE_DISCOUNT_BODY

    def test_the_call_reaches_the_cave(self):
        data = player_upgrade_discount_image()
        PlayerUpgradeDiscountPatch().apply(data)
        section_va, _off, _size = find_section(data, SECTION_NAME)
        off = va_to_offset(data, UPGRADE_DISCOUNT_CALL)
        call = disassemble(bytes(data[off : off + 5]), UPGRADE_DISCOUNT_CALL)[0]
        assert (call.mnemonic, target(call)) == ("call", section_va)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8

    def test_refuses_to_apply_twice(self):
        data = player_upgrade_discount_image()
        PlayerUpgradeDiscountPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            PlayerUpgradeDiscountPatch().apply(data)

    def test_a_moved_stock_sum_refuses_to_apply(self):
        data = player_upgrade_discount_image()
        off = va_to_offset(data, PLAYER_GET_UPGRADE_DISCOUNT) + 0x0D  # the vector's offset
        data[off] ^= 0x04
        with pytest.raises(ValueError, match="not this build's"):
            PlayerUpgradeDiscountPatch().apply(data)


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[PlayerUpgradeDiscountPatch.name] is PlayerUpgradeDiscountPatch
