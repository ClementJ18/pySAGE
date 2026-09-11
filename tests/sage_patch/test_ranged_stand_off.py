"""Tests for the ranged-stand-off patch.

Three bytes, so the interesting tests are not about the encoding but about *which* three: the
replacement has to write `al` and only `al`, has to leave the `cmp` before it and the flag-setting
`cmp` after it alone, and must not disturb the `MeleeWeapon` clear twelve bytes on - that clear is
the only reason melee still closes to contact once the gate is open.
"""

from __future__ import annotations

import pytest

from sage_patch.addresses import (
    ATTACK_APPROACH_MAY_STOP_GATE,
    ATTACK_APPROACH_MAY_STOP_GATE_BYTES,
    ATTACK_APPROACH_MAY_STOP_OFFSET,
    WEAPON_IS_MELEE,
)
from sage_patch.patches.experimental.ranged_stand_off import (
    ANCHORS,
    MAY_STOP_SETE_VA,
    PATCHED_BYTES,
    STOCK_BYTES,
    RangedStandOffPatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset

from .synthetic import ranged_stand_off_image

MELEE_CLEAR_VA = 0x00749DBE


def disassemble(blob: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(blob, base))


class TestTheSite:
    def test_it_is_the_sete_inside_the_gate(self):
        """The gate is `cmp` then `sete`; the patch owns the second half and nothing else."""
        assert MAY_STOP_SETE_VA == ATTACK_APPROACH_MAY_STOP_GATE + 7
        assert ATTACK_APPROACH_MAY_STOP_GATE_BYTES[7:10] == STOCK_BYTES

    def test_the_stock_bytes_are_a_sete_al(self):
        insns = disassemble(STOCK_BYTES, MAY_STOP_SETE_VA)
        assert [(i.mnemonic, i.op_str) for i in insns] == [("sete", "al")]

    def test_the_replacement_writes_al_and_pads_to_the_same_length(self):
        """`sete al` writes `al` alone, so anything wider would clobber a register the caller of
        this state is entitled to keep."""
        insns = disassemble(PATCHED_BYTES, MAY_STOP_SETE_VA)
        assert [(i.mnemonic, i.op_str) for i in insns] == [("mov", "al, 1"), ("nop", "")]
        assert len(PATCHED_BYTES) == len(STOCK_BYTES)

    def test_the_replacement_touches_no_flags(self):
        """The `je` four bytes later consumes the flags of the `cmp` that follows this site. An
        encoding that wrote flags here would still be correct, but one that read them would not -
        and `mov`/`nop` do neither."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        for insn in md.disasm(PATCHED_BYTES, MAY_STOP_SETE_VA):
            regs_read, regs_written = insn.regs_access()
            assert capstone.x86.X86_REG_EFLAGS not in regs_read
            assert capstone.x86.X86_REG_EFLAGS not in regs_written

    def test_the_gate_reads_the_goal_is_object_flag(self):
        """A gate that read some other offset would leave the range exit shut for a different
        reason, so pin the byte the `cmp` names."""
        insns = disassemble(ATTACK_APPROACH_MAY_STOP_GATE_BYTES, ATTACK_APPROACH_MAY_STOP_GATE)
        assert insns[0].mnemonic == "cmp"
        assert "0x3b2" in insns[0].op_str

    def test_the_store_into_the_state_byte_is_left_alone(self):
        """`mov [esi+0x6e], al` is what carries the patched `al`; the patch must not reach it."""
        insns = disassemble(ANCHORS[0x00749D8D], 0x00749D8D)
        store = next(i for i in insns if i.mnemonic == "mov" and i.op_str.endswith(", al"))
        assert f"0x{ATTACK_APPROACH_MAY_STOP_OFFSET:x}" in store.op_str


class TestMeleeStillCloses:
    def test_the_melee_clear_runs_after_the_patched_site(self):
        assert MELEE_CLEAR_VA > MAY_STOP_SETE_VA

    def test_it_calls_the_melee_weapon_getter_and_then_clears_the_state_byte(self):
        """This is the whole reason the patch can be unconditional: the engine's own
        `MeleeWeapon` test still zeroes the byte for melee, downstream of the change."""
        insns = disassemble(ANCHORS[MELEE_CLEAR_VA], MELEE_CLEAR_VA)
        assert [int(i.op_str, 16) for i in insns if i.mnemonic == "call"] == [WEAPON_IS_MELEE]
        clear = insns[-1]
        assert clear.mnemonic == "mov"
        assert clear.op_str == f"byte ptr [esi + 0x{ATTACK_APPROACH_MAY_STOP_OFFSET:x}], 0"

    def test_the_patch_does_not_overlap_the_clear(self):
        assert MAY_STOP_SETE_VA + len(PATCHED_BYTES) <= MELEE_CLEAR_VA


class TestTheExitsItUnblocks:
    @pytest.mark.parametrize("va", [0x00749F1A, 0x0074A231])
    def test_each_arm_opens_by_testing_the_state_byte(self, va: int):
        """Both range exits are gated on the same byte, which is why one site fixes both."""
        insns = disassemble(ANCHORS[va], va)
        assert insns[0].mnemonic == "cmp"
        assert insns[0].op_str == f"byte ptr [esi + 0x{ATTACK_APPROACH_MAY_STOP_OFFSET:x}], 0"


class TestApply:
    def test_it_applies_and_verifies(self):
        data = ranged_stand_off_image()
        RangedStandOffPatch().apply(data)
        assert RangedStandOffPatch().verify(data) == []

    def test_it_writes_exactly_the_replacement(self):
        data = ranged_stand_off_image()
        RangedStandOffPatch().apply(data)
        off = va_to_offset(data, MAY_STOP_SETE_VA)
        assert off is not None
        assert bytes(data[off : off + len(PATCHED_BYTES)]) == PATCHED_BYTES

    def test_it_leaves_every_anchor_untouched(self):
        data = ranged_stand_off_image()
        RangedStandOffPatch().apply(data)
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            assert off is not None
            assert bytes(data[off : off + len(expected)]) == expected

    def test_a_stock_image_does_not_verify(self):
        assert RangedStandOffPatch().verify(ranged_stand_off_image()) != []

    def test_it_is_detected_once_applied(self):
        data = ranged_stand_off_image()
        RangedStandOffPatch().apply(data)
        assert RangedStandOffPatch.detect(data) is not None

    def test_it_is_not_detected_in_a_stock_image(self):
        assert RangedStandOffPatch.detect(ranged_stand_off_image()) is None

    def test_applying_twice_raises(self):
        data = ranged_stand_off_image()
        RangedStandOffPatch().apply(data)
        with pytest.raises(ValueError):
            RangedStandOffPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_the_build(self, va: int):
        data = ranged_stand_off_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="unexpected build"):
            RangedStandOffPatch().apply(data)

    def test_a_moved_site_refuses_the_build(self):
        data = ranged_stand_off_image()
        off = va_to_offset(data, MAY_STOP_SETE_VA)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            RangedStandOffPatch().apply(data)

    def test_an_unmapped_image_is_reported_not_crashed(self):
        assert RangedStandOffPatch().verify(bytearray(0x200)) != []

    def test_it_is_registered_as_experimental(self):
        assert PATCHES[RangedStandOffPatch.name] is RangedStandOffPatch
        assert RangedStandOffPatch.experimental
