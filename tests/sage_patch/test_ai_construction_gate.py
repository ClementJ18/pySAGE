"""Tests for the AI construction-gate patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble
it back and assert it says what it was meant to say. A wrong byte in a hook does not raise - it
crashes the game, or worse, silently rejects every producer the AI has - so encoding errors have
to be caught statically.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    AI_PRODUCER_ACCEPT,
    AI_PRODUCER_NEXT_CANDIDATE,
    AI_PRODUCER_PICKER,
    AI_PRODUCER_PICKER_CALL,
    AI_PRODUCER_USABLE_TESTS,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    OBJECT_TEST_STATUS,
)
from sage_patch.patches import ai_revive_gate as revive
from sage_patch.patches.ai_construction_gate import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    PICKER_CALL_TARGET,
    SECTION_NAME,
    AiConstructionGatePatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

BASE = 0x00F00000
IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the hook site and every anchor, with the real original
    bytes planted, so the whole apply + verify path runs without the copyrighted `game.dat`."""
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
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for a 2nd header
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    data[HOOK_VA - IMAGE_BASE : HOOK_VA - IMAGE_BASE + len(HOOK_ORIGINAL)] = HOOK_ORIGINAL
    for va, expected in ANCHORS.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(expected)] = expected
    return data


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_code(base), base))


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_it_reproduces_the_arm_select_it_displaced(self):
        first = disassemble()[0]
        assert (first.mnemonic, first.op_str) == ("cmp", "byte ptr [ebp + 0x10], 0")

    def test_the_hypothetical_arm_takes_the_stock_edge(self):
        """Three of the picker's six callers pass a non-zero flag to ask "could anything ever
        make this", and one of them *cancels* an order when the answer is null. Those must reach
        accept exactly as stock, or the AI starts cancelling plans over unfinished buildings."""
        insns = disassemble()
        taken = next(i for i in insns if i.mnemonic == "je")
        # the `je` guards the "pick one to use" arm; everything before its target is the
        # hypothetical arm, and it must be a single jump to the accept path
        stock = next(i for i in insns if i.address == taken.address + taken.size)
        assert (stock.mnemonic, int(stock.op_str, 16)) == ("jmp", AI_PRODUCER_ACCEPT)

    def test_it_tests_under_construction_on_the_candidate_object(self):
        """`edi` is the candidate `Object` the picker resolved by id; testing anything else -
        `esi`, which holds its `ProductionUpdate` - would read a status mask off a module."""
        insns = disassemble()
        push = next(i for i in insns if i.mnemonic == "push")
        assert push.operands[0].imm == OBJECT_STATUS_UNDER_CONSTRUCTION
        # the argument is pushed, then `this` is loaded, then the helper is called - in that
        # order, because `testStatus` is `__thiscall` and takes the bit on the stack
        this = next(i for i in insns if i.address > push.address and i.mnemonic == "mov")
        assert this.op_str == "ecx, edi"
        call = next(i for i in insns if i.address > this.address and i.mnemonic == "call")
        assert int(call.op_str, 16) == OBJECT_TEST_STATUS

    def test_the_status_test_precedes_the_engines_own_tests(self):
        """The whole point: reject a construction site before the disabled/idle tests accept it."""
        insns = disassemble()
        call = next(i for i in insns if i.mnemonic == "call")
        resume = next(
            i
            for i in insns
            if i.mnemonic == "jmp" and int(i.op_str, 16) == AI_PRODUCER_USABLE_TESTS
        )
        assert call.address < resume.address

    def test_a_building_still_going_up_goes_to_the_next_candidate(self):
        """`testStatus` returns non-zero when the bit is set, so the *taken* edge must be the
        rejection - inverting this would reject every finished building instead."""
        insns = disassemble()
        call = next(i for i in insns if i.mnemonic == "call")
        test = next(i for i in insns if i.mnemonic == "test" and i.address > call.address)
        assert test.op_str == "al, al"
        # zero (not under construction) falls through to the resume; non-zero reaches the reject
        taken = next(i for i in insns if i.mnemonic == "je" and i.address > test.address)
        reject = next(i for i in insns if i.address == taken.address + taken.size)
        assert (reject.mnemonic, int(reject.op_str, 16)) == ("jmp", AI_PRODUCER_NEXT_CANDIDATE)

    def test_it_has_exactly_three_exits_all_into_the_picker(self):
        exits = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "jmp"}
        assert exits == {
            AI_PRODUCER_ACCEPT,
            AI_PRODUCER_NEXT_CANDIDATE,
            AI_PRODUCER_USABLE_TESTS,
        }

    def test_its_only_call_is_the_engines_status_helper(self):
        """The patch adds one engine call and no others; anything else would be a second
        implementation of something the binary already states."""
        calls = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "call"}
        assert calls == {OBJECT_TEST_STATUS}

    def test_every_conditional_branch_stays_inside_the_cave(self):
        """A displacement computed wrong would jump into arbitrary engine code."""
        code = build_code(BASE)
        lo, hi = BASE, BASE + len(code)
        for ins in disassemble():
            if not ins.mnemonic.startswith("j") or ins.mnemonic == "jmp":
                continue
            assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b, "absolute jumps and the call must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        AiConstructionGatePatch().apply(data)
        assert AiConstructionGatePatch().verify(data) == []

    def test_the_hook_is_a_jmp_to_the_cave_then_a_nop(self):
        data = synthetic_image()
        AiConstructionGatePatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        site = bytes(data[off : off + len(HOOK_ORIGINAL)])
        assert site[0] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va
        # the displaced `cmp` + `jne` were 6 bytes; the 6th is padded so no half-instruction
        # is left behind for the fallthrough to walk into
        assert site[5] == 0x90

    def test_the_cave_holds_the_expected_code(self):
        data = synthetic_image()
        AiConstructionGatePatch().apply(data)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + len(build_code(section_va))]) == build_code(section_va)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        data = synthetic_image()
        AiConstructionGatePatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        AiConstructionGatePatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            AiConstructionGatePatch().apply(data)

    def test_a_moved_anchor_refuses_to_apply(self):
        data = synthetic_image()
        va = AI_PRODUCER_USABLE_TESTS
        data[va - IMAGE_BASE : va - IMAGE_BASE + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            AiConstructionGatePatch().apply(data)

    def test_the_anchored_call_site_really_names_the_picker(self):
        """Why anchoring `AI_PRODUCER_PICKER_CALL` proves the function being edited is the one
        the AI's order pump reaches: its five bytes *are* the displacement, so asserting them
        asserts the target. A build that moved the picker fails on the anchor."""
        assert PICKER_CALL_TARGET == AI_PRODUCER_PICKER

    def test_a_rewritten_call_site_refuses_to_apply(self):
        data = synthetic_image()
        off = AI_PRODUCER_PICKER_CALL - IMAGE_BASE
        struct.pack_into("<i", data, off + 1, 0x1234)
        with pytest.raises(ValueError, match="not this build's"):
            AiConstructionGatePatch().apply(data)

    def test_it_does_not_touch_the_picker_beyond_the_six_hooked_bytes(self):
        """`AI_PRODUCER_PICKER`'s prologue, the accept path and the next-candidate edge all have
        to survive: the cave jumps into two of them."""
        before = synthetic_image()
        data = synthetic_image()
        AiConstructionGatePatch().apply(data)
        for va in (AI_PRODUCER_PICKER, AI_PRODUCER_ACCEPT, AI_PRODUCER_NEXT_CANDIDATE):
            o = va - IMAGE_BASE
            assert data[o : o + 8] == before[o : o + 8], f"{va:#010x} was rewritten"


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[AiConstructionGatePatch.name] is AiConstructionGatePatch

    def test_it_composes_with_ai_revive_gate(self):
        """The other AI production patch. The composition claim in the module docstring, as an
        assertion: neither edits a byte the other edits, and neither jumps into the other's
        function."""
        mine = set(range(HOOK_VA, HOOK_VA + len(HOOK_ORIGINAL)))
        theirs = set(range(revive.HOOK_VA, revive.HOOK_VA + len(revive.HOOK_ORIGINAL)))
        assert not mine & theirs
        assert not {va for va in ANCHORS} & theirs
        assert not mine & set(revive.ANCHORS)
