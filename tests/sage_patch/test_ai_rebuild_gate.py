"""Tests for the AI rebuild-gate patch.

Three layers, because a wrong byte in a hook does not raise - it crashes the game, or silently
rejects every structure the AI could ever repair. The cave is disassembled back and asserted to
say what it was meant to say; the apply/verify round-trip runs against a synthetic image carrying
the real stock bytes at every anchor; and the gate is then *executed* under Unicorn against the
engine's own `Object::testStatus` bytes, on both edges, with the status mask planted.
"""

from __future__ import annotations

import faulthandler
import struct

import pytest

from sage_patch.addresses import (
    AI_REBUILD_BEHAVIOR_CTOR,
    AI_REBUILD_HEALTH_TEST,
    AI_REBUILD_NEXT_CANDIDATE,
    AI_REBUILD_PICKER,
    OBJECT_BODY_MODULE,
    OBJECT_STATUS,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    OBJECT_TEST_STATUS,
    SPELLBOOK_AI_REBUILD,
    SPELLBOOK_AI_TYPE_COUNT,
)
from sage_patch.patches.ai_rebuild_gate import (
    ANCHORS,
    BEHAVIOR_CTOR_TARGET,
    HOOK_ORIGINAL,
    HOOK_VA,
    PICKER_VTABLE_SLOT_VA,
    REBUILD_NAME_SLOT,
    SECTION_NAME,
    AiRebuildGatePatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

BASE = 0x00F00000
IMAGE_BASE = 0x400000

#: The whole of `Object::testStatus` at `OBJECT_TEST_STATUS`. Planted as an anchor it is only its
#: first four bytes; the emulator needs the body, because the point of running it is that the gate
#: is proved against the engine's own bit arithmetic rather than a stand-in that agrees with the
#: reading being tested.
TEST_STATUS_BODY = bytes.fromhex(
    "8b54240433c0568bf1408bca83e11fd3e0c1ea05238496940000005ef7d81bc0f7d8c20400"
)


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


class TestTheChainFromTheKeyword:
    """The picker is identified by a chain, not by an address somebody wrote down: the keyword
    parses to an index, the index selects a factory case, the case calls a constructor, the
    constructor stamps a vtable, and slot 7 of that vtable is the function being hooked. These
    assert the links that are *computed* - the ones an anchor then checks against the image."""

    def test_the_index_is_inside_the_name_table(self):
        assert 0 <= SPELLBOOK_AI_REBUILD < SPELLBOOK_AI_TYPE_COUNT

    def test_the_name_table_slot_really_spells_the_keyword(self):
        """Why anchoring the slot proves the index: the slot holds a pointer, and the string it
        points at is anchored too, so "31 is AI_SPELLBOOK_REBUILD" is read off the image."""
        name_va = struct.unpack("<I", ANCHORS[REBUILD_NAME_SLOT])[0]
        assert ANCHORS[name_va] == b"AI_SPELLBOOK_REBUILD\x00"

    def test_the_factory_case_calls_the_anchored_constructor(self):
        """The case's `call` rel32 *is* the constructor's address, so asserting its five bytes
        asserts the target. A build that moved the constructor fails on the anchor."""
        assert BEHAVIOR_CTOR_TARGET == AI_REBUILD_BEHAVIOR_CTOR

    def test_the_constructor_stamps_the_vtable_the_slot_is_taken_from(self):
        """`mov dword [esi], imm32` is the constructor's last instruction; the imm32 must be the
        vtable `PICKER_VTABLE_SLOT_VA` is an offset into."""
        ctor = ANCHORS[AI_REBUILD_BEHAVIOR_CTOR]
        stamped = struct.unpack_from("<I", ctor, ctor.index(b"\xc7\x06") + 2)[0]
        assert PICKER_VTABLE_SLOT_VA - stamped == 0x1C

    def test_the_vtable_slot_holds_the_function_being_hooked(self):
        assert struct.unpack("<I", ANCHORS[PICKER_VTABLE_SLOT_VA])[0] == AI_REBUILD_PICKER

    def test_the_hook_site_is_inside_that_function(self):
        assert AI_REBUILD_PICKER < HOOK_VA < AI_REBUILD_HEALTH_TEST < AI_REBUILD_NEXT_CANDIDATE


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_it_tests_under_construction_on_the_candidate_object(self):
        """`ebx` is the candidate `Object` the picker resolved by id; `esi` is the list iterator
        and `edi` the vector, so testing either would read a status mask off a `std::vector`."""
        insns = disassemble()
        push = next(i for i in insns if i.mnemonic == "push")
        assert push.operands[0].imm == OBJECT_STATUS_UNDER_CONSTRUCTION
        # the argument is pushed, then `this` is loaded, then the helper is called - in that
        # order, because `testStatus` is `__thiscall` and takes the bit on the stack
        this = next(i for i in insns if i.address > push.address and i.mnemonic == "mov")
        assert this.op_str == "ecx, ebx"
        call = next(i for i in insns if i.address > this.address and i.mnemonic == "call")
        assert int(call.op_str, 16) == OBJECT_TEST_STATUS

    def test_the_status_test_precedes_the_health_test(self):
        """The whole point: reject a construction site before the ratio decides it is damaged."""
        insns = disassemble()
        call = next(i for i in insns if i.mnemonic == "call")
        resume = next(
            i for i in insns if i.mnemonic == "jmp" and int(i.op_str, 16) == AI_REBUILD_HEALTH_TEST
        )
        assert call.address < resume.address

    def test_it_re_runs_the_instruction_it_displaced(self):
        """The resume point is `mov eax, [ecx]`, so `ecx` has to be the body again - and
        `testStatus` clobbered it."""
        insns = disassemble()
        call = next(i for i in insns if i.mnemonic == "call")
        fetch = next(
            i
            for i in insns
            if i.address > call.address and i.mnemonic == "mov" and "0x25c" in i.op_str
        )
        assert fetch.op_str == "ecx, dword ptr [ebx + 0x25c]"
        assert fetch.bytes == HOOK_ORIGINAL

    def test_a_building_still_going_up_goes_to_the_next_candidate(self):
        """`testStatus` returns non-zero when the bit is set, so the *taken* edge must be the
        rejection - inverting this would skip every finished building instead."""
        insns = disassemble()
        call = next(i for i in insns if i.mnemonic == "call")
        test = next(i for i in insns if i.mnemonic == "test" and i.address > call.address)
        assert test.op_str == "al, al"
        taken = next(i for i in insns if i.mnemonic == "jne" and i.address > test.address)
        target = next(i for i in insns if i.address == int(taken.op_str, 16))
        assert (target.mnemonic, int(target.op_str, 16)) == ("jmp", AI_REBUILD_NEXT_CANDIDATE)

    def test_the_rejection_rejoins_the_loop_rather_than_returning(self):
        """One construction site must not hide a genuinely damaged building further down the
        list, which is what jumping to the picker's `ret` would do."""
        exits = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "jmp"}
        assert exits == {AI_REBUILD_HEALTH_TEST, AI_REBUILD_NEXT_CANDIDATE}

    def test_its_only_call_is_the_engines_status_helper(self):
        """The patch adds one engine call and no others; anything else would be a second
        implementation of something the binary already states."""
        calls = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "call"}
        assert calls == {OBJECT_TEST_STATUS}

    def test_it_touches_no_register_the_loop_needs(self):
        """`esi` is the iterator, `edi` the vector's end, `ebp` the behaviour, `ebx` the
        candidate. The cave's own instructions may only write `ecx`, which the displaced
        instruction sets, and `eax`, which `testStatus` returns in and the resume point
        overwrites. What the *callee* preserves is a separate claim, and `TestTheGateRuns`
        below is what settles it."""
        written = set()
        for ins in disassemble():
            regs_written = ins.regs_access()[1]
            written |= {ins.reg_name(r) for r in regs_written}
        assert not written & {"esi", "edi", "ebp", "ebx"}

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
        assert a != b, "the absolute jumps and the call must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        AiRebuildGatePatch().apply(data)
        assert AiRebuildGatePatch().verify(data) == []

    def test_the_hook_is_a_jmp_to_the_cave_then_a_nop(self):
        data = synthetic_image()
        AiRebuildGatePatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        site = bytes(data[off : off + len(HOOK_ORIGINAL)])
        assert site[0] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va
        # the displaced `mov` was 6 bytes; the 6th is padded so no half-instruction is left
        # behind for anything falling through to walk into
        assert site[5] == 0x90

    def test_the_cave_holds_the_expected_code(self):
        data = synthetic_image()
        AiRebuildGatePatch().apply(data)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + len(build_code(section_va))]) == build_code(section_va)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        data = synthetic_image()
        AiRebuildGatePatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        AiRebuildGatePatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            AiRebuildGatePatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:#010x}")
    def test_a_moved_anchor_refuses_to_apply(self, va):
        data = synthetic_image()
        off = va - IMAGE_BASE
        data[off : off + len(ANCHORS[va])] = b"\x90" * len(ANCHORS[va])
        with pytest.raises(ValueError, match="not this build's"):
            AiRebuildGatePatch().apply(data)

    def test_registered_as_settled(self):
        """It lives outside `patches/experimental/`, so it must not carry the warning."""
        assert PATCHES["ai-rebuild-gate"] is AiRebuildGatePatch
        assert not AiRebuildGatePatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_CAVE = 0x00ED3000
_HEAP = 0x20000000
_STACK = 0x30000000
_PAGE = 0x1000
_OBJECT = _HEAP + 0x1000
_BODY = _HEAP + 0x2000

#: What the loop holds in the registers the gate must not disturb.
_LIVE = {
    UC_X86_REG_ESI: 0x51515151,
    UC_X86_REG_EDI: 0xD1D1D1D1,
    UC_X86_REG_EBP: 0xB0B0B0B0,
}


def _run(*, status_bits: tuple[int, ...]) -> tuple[int, dict[int, int], int]:
    """Run the gate over one candidate whose status mask holds `status_bits`.

    Returns where it ended up, the live registers as it left them, and `ecx`. The run stops at
    whichever engine address the cave jumps to, because neither is mapped as code.
    """
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    code = build_code(_CAVE)

    pages = {_HEAP, _OBJECT, _BODY, _STACK, _STACK + _PAGE}
    pages |= {(_CAVE + off) & ~0xFFF for off in range(0, len(code) + _PAGE, _PAGE)}
    pages |= {OBJECT_TEST_STATUS & ~0xFFF}
    pages |= {AI_REBUILD_HEALTH_TEST & ~0xFFF, AI_REBUILD_NEXT_CANDIDATE & ~0xFFF}
    # `mem_map` raises and catches an SEH access violation inside Unicorn on Windows; every map
    # still succeeds, but the fault handler would print a stack for each one.
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        for page in sorted(pages):
            uc.mem_map(page, _PAGE)
    finally:
        if was_enabled:
            faulthandler.enable()

    uc.mem_write(_CAVE, code)
    uc.mem_write(OBJECT_TEST_STATUS, TEST_STATUS_BODY)
    # the engine's own status mask: four dwords at `Object+0x94`
    words = [0, 0, 0, 0]
    for bit in status_bits:
        words[bit >> 5] |= 1 << (bit & 31)
    uc.mem_write(_OBJECT + OBJECT_STATUS, struct.pack("<4I", *words))
    uc.mem_write(_OBJECT + OBJECT_BODY_MODULE, struct.pack("<I", _BODY))

    uc.reg_write(UC_X86_REG_ESP, _STACK + _PAGE)
    uc.reg_write(UC_X86_REG_EBX, _OBJECT)
    uc.reg_write(UC_X86_REG_ECX, 0xDEADBEEF)
    for reg, value in _LIVE.items():
        uc.reg_write(reg, value)

    # both exits are `jmp` into unmapped-as-code engine addresses, so the run ends when one is
    # reached; `stop` records which
    landed: list[int] = []

    def watch(u, address, size, _user):  # noqa: ANN001
        if address in (AI_REBUILD_HEALTH_TEST, AI_REBUILD_NEXT_CANDIDATE):
            landed.append(address)
            u.emu_stop()

    uc.hook_add(UC_HOOK_CODE, watch)
    uc.emu_start(_CAVE, 0, count=64)
    assert landed, "the gate reached neither exit"
    live = {reg: uc.reg_read(reg) for reg in _LIVE}
    return landed[0], live, uc.reg_read(UC_X86_REG_ECX)


class TestTheGateRuns:
    """The gate executed against the engine's own `Object::testStatus` bytes."""

    def test_a_finished_structure_reaches_the_health_test(self):
        where, _live, ecx = _run(status_bits=())
        assert where == AI_REBUILD_HEALTH_TEST

    def test_and_arrives_with_the_body_in_ecx(self):
        """The resume point is `mov eax, [ecx]` on the `BodyModule` vtable, so the displaced
        instruction has to have re-run after `testStatus` clobbered `ecx`."""
        _where, _live, ecx = _run(status_bits=())
        assert ecx == _BODY

    def test_a_structure_under_construction_is_skipped(self):
        where, _live, _ecx = _run(status_bits=(OBJECT_STATUS_UNDER_CONSTRUCTION,))
        assert where == AI_REBUILD_NEXT_CANDIDATE

    def test_an_unrelated_status_bit_does_not_skip_it(self):
        """The mask is 106 bits wide and the gate must read the one bit it named - a mask test
        written a nibble out would reject arbitrary structures."""
        for bit in (0, 1, 3, 20, 38, 105):
            where, _live, _ecx = _run(status_bits=(bit,))
            assert where == AI_REBUILD_HEALTH_TEST, f"status bit {bit} should not skip"

    @pytest.mark.parametrize("bits", [(), (OBJECT_STATUS_UNDER_CONSTRUCTION,)], ids=["up", "down"])
    def test_the_loops_registers_come_back_untouched(self, bits):
        """`esi` is the iterator, `edi` the vector's end and `ebp` the behaviour; `testStatus`
        pushes and pops `esi` itself, but that is a claim until it is run."""
        _where, live, _ecx = _run(status_bits=bits)
        assert live == _LIVE
