"""Tests for the rebuild-hole construction patch.

The patch is one erased branch, so the tests that matter are about *which* branch: that the six
bytes really are the `UNDER_CONSTRUCTION` gate rather than one of `onDie`'s two neighbouring
rejections, that the replacement falls through instead of doing something, and that a build whose
layout moved is refused before anything is written. Getting the wrong six bytes here would not
raise in game - it would erase an unrelated test, or leave half an instruction behind.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    DIE_MODULE_IS_APPLICABLE,
    DIE_MUX_IS_APPLICABLE,
    OBJECT_STATUS,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    REBUILD_HOLE_CONSTRUCTION_TEST,
    REBUILD_HOLE_ON_DIE,
    REBUILD_HOLE_SELF_KILL,
    REBUILD_HOLE_START_REBUILD,
)
from sage_patch.patches.rebuild_hole_construction import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_REPLACEMENT,
    HOOK_VA,
    RebuildHoleConstructionPatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset

IMAGE_BASE = 0x400000

#: Where the stock branch goes: `onDie`'s shared return, past every remaining instruction. Decoded
#: from the branch's own displacement rather than written down, so the "this is a rejection edge"
#: claim is derived from the bytes the patch asserts.
GATE_TARGET = HOOK_VA + len(HOOK_ORIGINAL) + struct.unpack("<i", HOOK_ORIGINAL[2:6])[0]


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the gate and every anchor, with the real original bytes
    planted, so the whole apply + verify path runs without the copyrighted `game.dat`."""
    highest = max(HOOK_VA, *ANCHORS) - IMAGE_BASE + 0x100
    data = bytearray(((highest + 0x400) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    data[HOOK_VA - IMAGE_BASE : HOOK_VA - IMAGE_BASE + len(HOOK_ORIGINAL)] = HOOK_ORIGINAL
    for va, expected in ANCHORS.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(expected)] = expected
    return data


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(code, base))


class TestTheSiteIsTheGate:
    def test_the_erased_bytes_are_one_conditional_branch(self):
        insns = disassemble(HOOK_ORIGINAL, HOOK_VA)
        assert len(insns) == 1, "the site must be exactly one instruction, not a partial run"
        assert insns[0].mnemonic == "jne"
        assert insns[0].size == len(HOOK_ORIGINAL)

    def test_it_branches_forward_out_of_the_function(self):
        """A rejection edge, not a loop back: erasing a branch that went *backwards* would be
        erasing something else entirely."""
        assert GATE_TARGET > HOOK_VA
        assert int(disassemble(HOOK_ORIGINAL, HOOK_VA)[0].op_str, 16) == GATE_TARGET

    def test_what_it_tests_is_under_construction_on_the_dying_object(self):
        """The three instructions immediately before it isolate one bit of one bitset. Both
        numbers have to be right, and both come from `addresses.py` rather than from here."""
        run = ANCHORS[REBUILD_HOLE_CONSTRUCTION_TEST]
        insns = disassemble(run, REBUILD_HOLE_CONSTRUCTION_TEST)
        assert [i.mnemonic for i in insns] == ["mov", "shr", "test"]
        assert insns[0].op_str == f"eax, dword ptr [esi + {OBJECT_STATUS:#x}]"
        assert insns[1].op_str == f"eax, {OBJECT_STATUS_UNDER_CONSTRUCTION}"
        assert insns[2].op_str == "al, 1"

    def test_the_test_run_ends_exactly_where_the_gate_begins(self):
        """Contiguity is what makes the pair one anchored shape instead of two addresses that
        happen to be near each other."""
        run = ANCHORS[REBUILD_HOLE_CONSTRUCTION_TEST]
        assert REBUILD_HOLE_CONSTRUCTION_TEST + len(run) == HOOK_VA

    def test_the_gate_sits_inside_on_die(self):
        assert REBUILD_HOLE_ON_DIE < HOOK_VA < GATE_TARGET

    def test_on_die_opens_with_the_shared_die_filter(self):
        """The `ExemptStatus` opt-out the patch's contract offers is only real if `onDie` runs
        the filter that reads it, so assert the call is in the prologue that is anchored."""
        insns = disassemble(ANCHORS[REBUILD_HOLE_ON_DIE], REBUILD_HOLE_ON_DIE)
        assert [i.mnemonic for i in insns[:4]] == ["push", "mov", "sub", "push"]


class TestTheReplacement:
    def test_it_is_the_same_length(self):
        assert len(HOOK_REPLACEMENT) == len(HOOK_ORIGINAL)

    def test_it_is_a_single_nop_that_falls_through(self):
        insns = disassemble(HOOK_REPLACEMENT, HOOK_VA)
        assert len(insns) == 1
        assert insns[0].mnemonic == "nop"
        assert insns[0].size == len(HOOK_REPLACEMENT)

    def test_it_contains_no_branch(self):
        assert not any(i.mnemonic.startswith("j") for i in disassemble(HOOK_REPLACEMENT, HOOK_VA))


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        RebuildHoleConstructionPatch().apply(data)
        assert RebuildHoleConstructionPatch().verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert RebuildHoleConstructionPatch().verify(synthetic_image()) == [
            f"{HOOK_VA:#010x} still holds the UNDER_CONSTRUCTION gate"
        ]

    def test_it_writes_the_nop_at_the_gate(self):
        data = synthetic_image()
        RebuildHoleConstructionPatch().apply(data)
        off = va_to_offset(data, HOOK_VA)
        assert bytes(data[off : off + len(HOOK_REPLACEMENT)]) == HOOK_REPLACEMENT

    def test_it_touches_nothing_but_those_six_bytes(self):
        before = synthetic_image()
        data = synthetic_image()
        RebuildHoleConstructionPatch().apply(data)
        off = va_to_offset(data, HOOK_VA)
        changed = {i for i in range(len(data)) if data[i] != before[i]}
        # a subset, not an equality: the branch and the nop that replaces it share their last
        # two bytes, so four of the six actually differ
        assert changed and changed <= set(range(off, off + len(HOOK_ORIGINAL)))

    def test_the_neighbouring_rejections_survive(self):
        """`onDie`'s two other early-outs - the owning-player tests - are deliberately left
        stock, and they sit within 0x30 bytes of the gate."""
        before = synthetic_image()
        data = synthetic_image()
        RebuildHoleConstructionPatch().apply(data)
        lo = va_to_offset(data, REBUILD_HOLE_ON_DIE)
        hi = va_to_offset(data, HOOK_VA)
        assert data[lo:hi] == before[lo:hi]

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        RebuildHoleConstructionPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            RebuildHoleConstructionPatch().apply(data)

    @pytest.mark.parametrize(
        "va",
        [
            REBUILD_HOLE_ON_DIE,
            REBUILD_HOLE_CONSTRUCTION_TEST,
            REBUILD_HOLE_START_REBUILD,
            REBUILD_HOLE_SELF_KILL,
            DIE_MODULE_IS_APPLICABLE,
            DIE_MUX_IS_APPLICABLE,
        ],
    )
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = synthetic_image()
        data[va - IMAGE_BASE : va - IMAGE_BASE + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            RebuildHoleConstructionPatch().apply(data)

    def test_a_moved_anchor_leaves_the_gate_alone(self):
        """The anchors are checked before the write, so a refused apply is a no-op."""
        data = synthetic_image()
        data[REBUILD_HOLE_SELF_KILL - IMAGE_BASE : REBUILD_HOLE_SELF_KILL - IMAGE_BASE + 2] = (
            b"\x90\x90"
        )
        with pytest.raises(ValueError):
            RebuildHoleConstructionPatch().apply(data)
        off = va_to_offset(data, HOOK_VA)
        assert bytes(data[off : off + len(HOOK_ORIGINAL)]) == HOOK_ORIGINAL


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[RebuildHoleConstructionPatch.name] is RebuildHoleConstructionPatch

    def test_detect_finds_it_only_once_applied(self):
        assert RebuildHoleConstructionPatch.detect(synthetic_image()) is None
        data = synthetic_image()
        RebuildHoleConstructionPatch().apply(data)
        assert isinstance(RebuildHoleConstructionPatch.detect(data), RebuildHoleConstructionPatch)

    def test_the_description_names_the_ini_opt_out(self):
        """The one thing a mod has to know to keep the stock behaviour for a given object."""
        assert "ExemptStatus" in RebuildHoleConstructionPatch.description
