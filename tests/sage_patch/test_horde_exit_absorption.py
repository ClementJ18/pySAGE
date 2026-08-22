"""Tests for the horde-exit-absorption patch.

The patch is one repointed `call` plus a cave that duplicates an engine rule, so the tests are
about the two things that could be silently wrong: that the five bytes really are the pending-horde
lookup and not one of `exitObjectViaDoor`'s other `findObjectByID`-shaped sites, and that the
duplicate really is the original - same helpers, same order, same fields. A wrong gate here does not
crash; it quietly stops battalions forming, or quietly keeps absorbing heroes.
"""

from __future__ import annotations

import re
import struct

import pytest

from sage_patch.addresses import (
    CONTAIN_GET_HORDE_IFACE,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    HORDE_IFACE_ASSIGN_SLOT,
    HORDE_IFACE_ASSIGN_SLOT_BYTES,
    HORDE_IFACE_SLOT_STRIDE,
    HORDE_PAYLOAD_LOOKUP,
    QUEUE_EXIT_BIND_BLOCK,
    QUEUE_EXIT_BIND_BLOCK_BYTES,
    QUEUE_EXIT_LONE_UNIT_FLAG,
    QUEUE_EXIT_LONE_UNIT_FLAG_BYTES,
    QUEUE_EXIT_OBJECT_VIA_DOOR,
    QUEUE_EXIT_PENDING_HORDE,
    QUEUE_EXIT_REMEMBER_HORDE,
    QUEUE_EXIT_REMEMBER_HORDE_BYTES,
    THING_FACTORY_FIND_TEMPLATE,
    THING_TEMPLATE_IS_EQUIVALENT,
)
from sage_patch.patches.horde_exit_absorption import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    HordeExitAbsorptionPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000


def _direct_calls(code: bytes, base: int) -> list[int]:
    """The `call rel32` targets in ``code``, in order.

    Decoding the engine's rule rather than retyping its helper list here is what makes "the cave
    mirrors that rule" a comparison of two things instead of a list agreeing with itself."""
    return [
        int(i.op_str, 16)
        for i in disassemble(code, base)
        if i.mnemonic == "call" and i.op_str.startswith("0x")
    ]


def _register_operands(code: bytes, base: int) -> set[str]:
    """Every ``[esi ...]`` / ``[edi ...]`` / ``[ebx ...]`` operand, as text."""
    found: set[str] = set()
    for insn in disassemble(code, base):
        found.update(re.findall(r"\[e(?:si|di|bx)[^]]*\]", insn.op_str))
    return found


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the hook and every anchor, with the real original bytes
    planted, so the whole apply + verify path runs without the copyrighted `game.dat`."""
    highest = max(HOOK_VA, *(va + len(b) for va, b in ANCHORS.items())) - IMAGE_BASE + 0x100
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


class TestTheSiteIsTheLookup:
    def test_the_hooked_bytes_are_one_call_to_find_object_by_id(self):
        insns = disassemble(HOOK_ORIGINAL, HOOK_VA)
        assert len(insns) == 1, "the site must be exactly one instruction"
        assert insns[0].mnemonic == "call"
        assert insns[0].size == len(HOOK_ORIGINAL)
        assert int(insns[0].op_str, 16) == GAME_LOGIC_FIND_OBJECT_BY_ID

    def test_it_sits_inside_exit_object_via_door(self):
        assert QUEUE_EXIT_OBJECT_VIA_DOOR < HOOK_VA < QUEUE_EXIT_REMEMBER_HORDE

    def test_the_pending_horde_is_written_only_behind_the_kind_of_horde_test(self):
        """The store the whole defect hangs on, and the branch that makes it horde-only. Both
        are in one anchored run, so they cannot drift apart."""
        insns = disassemble(QUEUE_EXIT_REMEMBER_HORDE_BYTES, QUEUE_EXIT_REMEMBER_HORDE)
        assert insns[0].op_str == "eax, dword ptr [ebx + 4]"
        assert insns[1].mnemonic == "test"  # the KINDOF HORDE bit
        assert insns[2].mnemonic == "je"
        stores = [
            i for i in insns if i.op_str == f"dword ptr [edi + {QUEUE_EXIT_PENDING_HORDE:#x}], eax"
        ]
        assert len(stores) == 1, "exactly one write of the pending-horde field in this run"
        assert int(insns[2].op_str, 16) > stores[0].address, "the test skips the store"

    def test_the_bind_block_is_the_three_unconditional_bindings(self):
        """What the hook prevents: producer, slot assignment, team - with no branch between
        them, which is the point."""
        insns = disassemble(QUEUE_EXIT_BIND_BLOCK_BYTES, QUEUE_EXIT_BIND_BLOCK)
        assert not any(i.mnemonic.startswith("j") for i in insns)
        assert [i.mnemonic for i in insns[:5]] == ["push", "mov", "call", "mov", "push"]
        assert insns[-1].op_str == "dword ptr [eax + 0x2c]", "the horde interface's slot assign"

    def test_the_lone_unit_flag_reads_the_same_resolved_pointer(self):
        """The second consumer of the lookup's answer: a byte in the caller's frame that decides
        whether this object gets the structure's rally point on its own exit path."""
        insns = disassemble(QUEUE_EXIT_LONE_UNIT_FLAG_BYTES, QUEUE_EXIT_LONE_UNIT_FLAG)
        writes = [i for i in insns if i.mnemonic == "mov" and i.op_str.startswith("byte ptr [ebp")]
        assert {i.op_str.split(", ")[1] for i in writes} == {"1", "0"}
        assert any("dword ptr [ebp - 0x1c], 0" in i.op_str for i in insns), (
            "the flag is decided by the resolved horde, which lives at [ebp-0x1c]"
        )


class TestTheGateMirrorsTheEnginesRule:
    def test_it_calls_the_same_helpers_in_the_same_order(self):
        engine = _direct_calls(HORDE_IFACE_ASSIGN_SLOT_BYTES, HORDE_IFACE_ASSIGN_SLOT)
        assert engine == [
            HORDE_PAYLOAD_LOOKUP,
            THING_FACTORY_FIND_TEMPLATE,
            THING_TEMPLATE_IS_EQUIVALENT,
        ]
        cave = _direct_calls(build_code(0xAD3000), 0xAD3000)
        assert cave[0] == GAME_LOGIC_FIND_OBJECT_BY_ID, "the call it replaces comes first"
        assert cave[1:] == engine

    def test_it_reads_the_same_fields(self):
        """Every interface, node and object field the cave touches is one the anchored rule
        touches too - so a build where those offsets moved fails the anchor, not the game."""
        engine = _register_operands(HORDE_IFACE_ASSIGN_SLOT_BYTES, HORDE_IFACE_ASSIGN_SLOT)
        cave = _register_operands(build_code(0xAD3000), 0xAD3000)
        # `[edi]` is the list step, which sits one instruction past the anchored run
        assert cave - engine <= {"[edi]"}

    def test_it_indexes_the_slot_array_with_the_engines_stride(self):
        cave = disassemble(build_code(0xAD3000), 0xAD3000)
        assert any(
            i.mnemonic == "imul" and i.op_str == f"eax, eax, {HORDE_IFACE_SLOT_STRIDE:#x}"
            for i in cave
        )

    def test_it_reaches_the_horde_interface_the_way_the_engine_does(self):
        """`getHordeIface` is a vtable call, so the cave's claim to be looking at a horde rests
        on calling the same slot on the same interface pointer."""
        cave = disassemble(build_code(0xAD3000), 0xAD3000)
        indirect = [i.op_str for i in cave if i.mnemonic == "call" and i.op_str.startswith("dword")]
        assert indirect == ["dword ptr [eax + 0x7c]", "dword ptr [eax + 0x84]"]
        assert CONTAIN_GET_HORDE_IFACE in ANCHORS, "and on that slot's target being pinned"


class TestTheGateIsAPredicate:
    def test_it_returns_with_the_callee_cleanup_the_call_it_replaces_did(self):
        cave = disassemble(build_code(0xAD3000), 0xAD3000)
        rets = [i for i in cave if i.mnemonic == "ret"]
        assert len(rets) == 1
        assert rets[0].op_str == "4"

    def test_it_writes_no_memory_of_its_own(self):
        """A gate that answers a question and changes nothing. The one call that does have an
        effect - building the lazy slot list - is the engine's own, made a few instructions
        earlier than the stock code would."""
        cave = disassemble(build_code(0xAD3000), 0xAD3000)
        for insn in cave:
            if insn.mnemonic in {"call", "push", "cmp", "test", "lea"}:
                continue
            destination = insn.op_str.split(", ")[0]
            assert "[" not in destination, f"{insn.mnemonic} {insn.op_str} writes memory"

    def test_the_early_out_skips_the_saves(self):
        """A NULL from `findObjectByID` must reach the `ret` without having pushed anything,
        or the stack unwinds four registers short."""
        cave = disassemble(build_code(0xAD3000), 0xAD3000)
        ret = next(i for i in cave if i.mnemonic == "ret")
        early = next(i for i in cave if i.mnemonic == "je")
        assert int(early.op_str, 16) == ret.address
        saves = next(n for n, i in enumerate(cave) if i.mnemonic == "push" and i.op_str == "esi")
        assert cave.index(early) < saves

    def test_both_answers_restore_the_same_registers(self):
        cave = disassemble(build_code(0xAD3000), 0xAD3000)
        pops = [i.op_str for i in cave if i.mnemonic == "pop"]
        assert pops == ["eax", "eax", "edi", "esi"], (
            "one pop of the saved horde per answer, then the shared epilogue"
        )
        assert [i.op_str for i in cave if i.mnemonic == "push"] == [
            "dword ptr [esp + 4]",
            "esi",
            "edi",
            "eax",
            "1",
            "dword ptr [eax]",
            "eax",
            "eax",
        ]

    def test_the_rejection_answers_null(self):
        cave = disassemble(build_code(0xAD3000), 0xAD3000)
        assert any(i.mnemonic == "xor" and i.op_str == "eax, eax" for i in cave)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        HordeExitAbsorptionPatch().apply(data)
        assert HordeExitAbsorptionPatch().verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert HordeExitAbsorptionPatch().verify(synthetic_image()) == [
            f"no {SECTION_NAME} section: the file does not carry this patch"
        ]

    def test_the_hook_calls_the_cave(self):
        data = synthetic_image()
        HordeExitAbsorptionPatch().apply(data)
        section_va, section_off, _ = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        assert data[off] == 0xE8
        assert HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0] == section_va
        code = build_code(section_va)
        assert bytes(data[section_off : section_off + len(code)]) == code

    def test_it_touches_nothing_but_those_five_bytes(self):
        """Everything else the apply does is append-only: the new section header lives in the
        header block and its content past the end of the original file."""
        before = synthetic_image()
        data = synthetic_image()
        HordeExitAbsorptionPatch().apply(data)
        off = va_to_offset(data, HOOK_VA)
        changed = {i for i in range(0x400, len(before)) if data[i] != before[i]}
        assert changed == set(range(off + 1, off + len(HOOK_ORIGINAL))), (
            "only the four displacement bytes differ - both are a call"
        )

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        HordeExitAbsorptionPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            HordeExitAbsorptionPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = synthetic_image()
        data[va - IMAGE_BASE : va - IMAGE_BASE + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            HordeExitAbsorptionPatch().apply(data)

    def test_a_moved_anchor_leaves_the_lookup_alone(self):
        """The anchors are checked before the section is allocated, so a refused apply is a
        no-op rather than a file carrying an orphaned cave."""
        data = synthetic_image()
        data[HORDE_IFACE_ASSIGN_SLOT - IMAGE_BASE : HORDE_IFACE_ASSIGN_SLOT - IMAGE_BASE + 2] = (
            b"\x90\x90"
        )
        with pytest.raises(ValueError):
            HordeExitAbsorptionPatch().apply(data)
        off = va_to_offset(data, HOOK_VA)
        assert bytes(data[off : off + len(HOOK_ORIGINAL)]) == HOOK_ORIGINAL
        assert find_section(data, SECTION_NAME) is None


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[HordeExitAbsorptionPatch.name] is HordeExitAbsorptionPatch

    def test_detect_finds_it_only_once_applied(self):
        assert HordeExitAbsorptionPatch.detect(synthetic_image()) is None
        data = synthetic_image()
        HordeExitAbsorptionPatch().apply(data)
        assert isinstance(HordeExitAbsorptionPatch.detect(data), HordeExitAbsorptionPatch)

    def test_the_description_says_there_is_nothing_to_declare(self):
        """The patch is global and opt-out-free, so the one thing a modder needs from the
        description is that no INI change turns it on."""
        assert "No INI change" in HordeExitAbsorptionPatch.description
