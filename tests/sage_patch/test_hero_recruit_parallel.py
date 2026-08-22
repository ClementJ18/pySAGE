"""Tests for the hero-recruit-parallel patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say - and, just as importantly, that it says it
about the *fallback* rule rather than about the rule one step earlier that lets a ready hero jump
the queue. Skipping the wrong entries here does not raise: it would either leave the report's bug
in place or stop heroes appearing at all.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    PRODUCTION_ENTRY_KIND,
    PRODUCTION_ENTRY_KIND_REVIVE,
    PRODUCTION_ENTRY_NEXT,
    PRODUCTION_QUEUE_HEAD,
    PRODUCTION_UPDATE_GET_NEXT,
    PRODUCTION_UPDATE_PICK_CALL,
    PRODUCTION_UPDATE_PICK_ENTRY,
    PRODUCTION_UPDATE_PICK_RETURN,
    PRODUCTION_UPDATE_PICK_REVIVE_SCAN,
    REVIVE_MGR_PROGRESS,
)
from sage_patch.patches.hero_recruit_parallel import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    REVIVE_READY_TARGET,
    SECTION_NAME,
    HeroRecruitParallelPatch,
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


class TestTheDisplacedBytes:
    def test_it_displaces_a_whole_number_of_instructions(self):
        """`test ebx,ebx` / `jne` / `mov eax,[esi+0x28]` - seven bytes, three instructions. Taking
        five would leave two bytes of the head load behind for the cave's `jmp` to fall into."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        insns = list(md.disasm(HOOK_ORIGINAL, HOOK_VA))
        assert [i.mnemonic for i in insns] == ["test", "jne", "mov"]
        assert sum(i.size for i in insns) == len(HOOK_ORIGINAL)

    def test_the_last_one_is_the_stock_fallback(self):
        """The rule being replaced: return the head, whatever kind it is."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        load = list(md.disasm(HOOK_ORIGINAL, HOOK_VA))[-1]
        assert load.op_str == f"eax, dword ptr [esi + {PRODUCTION_QUEUE_HEAD:#x}]"

    def test_the_displaced_branch_goes_back_into_the_revive_scan(self):
        """Decoded from the bytes rather than written down: the `jne` the cave reproduces is the
        revive rule's own loop, so reproducing it keeps that rule intact."""
        target = HOOK_VA + 4 + struct.unpack("<b", HOOK_ORIGINAL[3:4])[0]
        assert target == PRODUCTION_UPDATE_PICK_REVIVE_SCAN

    def test_the_hook_ends_where_the_epilogue_begins(self):
        assert HOOK_VA + len(HOOK_ORIGINAL) == PRODUCTION_UPDATE_PICK_RETURN


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_it_reproduces_the_loop_condition_it_displaced(self):
        insns = disassemble()
        assert (insns[0].mnemonic, insns[0].op_str) == ("test", "ebx, ebx")

    def test_the_revive_rule_is_reached_unchanged(self):
        """The rule that lets a ready hero jump the queue - the half of the behaviour the report
        wants kept - must still be looped over exactly as stock."""
        insns = disassemble()
        back = next(i for i in insns if i.mnemonic == "jmp")
        assert int(back.op_str, 16) == PRODUCTION_UPDATE_PICK_REVIVE_SCAN

    def test_the_fallback_starts_at_the_head(self):
        insns = disassemble()
        first = next(i for i in insns if i.mnemonic == "mov")
        assert first.op_str == f"eax, dword ptr [esi + {PRODUCTION_QUEUE_HEAD:#x}]"

    def test_it_skips_exactly_the_revive_kind(self):
        """Kind 3 and nothing else. Skipping kind 2 as well would freeze upgrades behind units."""
        insns = disassemble()
        cmp_ = next(i for i in insns if i.mnemonic == "cmp")
        assert cmp_.op_str == (
            f"dword ptr [eax + {PRODUCTION_ENTRY_KIND}], {PRODUCTION_ENTRY_KIND_REVIVE}"
        )

    def test_it_walks_the_list_by_the_next_pointer(self):
        """The same field `getNextProduction` reads, which is what makes the raw walk equivalent
        to the vtable call the rest of the picker makes."""
        insns = disassemble()
        want = f"eax, dword ptr [eax + {PRODUCTION_ENTRY_NEXT:#x}]"
        assert any(i.mnemonic == "mov" and i.op_str == want for i in insns)

    def test_an_all_revive_queue_still_gets_the_head(self):
        """The walk running off the end must land on the stock answer, not on NULL: a queue of
        nothing but heroes has to behave exactly as it does today."""
        insns = disassemble()
        head = f"eax, dword ptr [esi + {PRODUCTION_QUEUE_HEAD:#x}]"
        loads = [i for i in insns if i.op_str == head]
        assert len(loads) == 2, "the head is loaded once to start the walk and once to end it"
        exhausted = next(i for i in insns if i.mnemonic == "jne" and i.address > loads[0].address)
        assert exhausted.address < loads[1].address

    def test_every_path_ends_at_the_epilogue(self):
        insns = disassemble()
        assert int(insns[-1].op_str, 16) == PRODUCTION_UPDATE_PICK_RETURN

    def test_it_writes_only_eax(self):
        """`esi` is the module base and is still needed; `ebx`/`edi`/`esi` are restored by the
        pops the cave jumps to, so eax is the only register it may touch."""
        capstone = pytest.importorskip("capstone")
        for insn in disassemble():
            for op in insn.operands:
                if op.type == capstone.x86.X86_OP_REG and op.access & capstone.CS_AC_WRITE:
                    assert insn.reg_name(op.reg) == "eax", f"{insn.mnemonic} writes a live register"

    def test_it_calls_nothing(self):
        """The picker is called with a bare `push esi` frame; the cave adds no engine calls."""
        assert not [i for i in disassemble() if i.mnemonic == "call"]


class TestTheAnchors:
    def test_the_readiness_call_reaches_the_revive_clock(self):
        """Derived from the call's own displacement: the rule that runs before the rewritten
        fallback asks the player-side revive progress, which is why skipping a waiting hero in
        the fallback cannot make a ready one late."""
        assert REVIVE_READY_TARGET == REVIVE_MGR_PROGRESS

    def test_the_picker_is_what_update_calls(self):
        target = (
            PRODUCTION_UPDATE_PICK_CALL
            + 5
            + struct.unpack("<i", ANCHORS[PRODUCTION_UPDATE_PICK_CALL][1:5])[0]
        )
        assert target == PRODUCTION_UPDATE_PICK_ENTRY

    def test_the_hook_sits_inside_the_picker(self):
        assert PRODUCTION_UPDATE_PICK_ENTRY < HOOK_VA < PRODUCTION_UPDATE_PICK_RETURN

    def test_get_next_reads_the_field_the_cave_walks(self):
        """`entry ? entry->+0x48 : NULL` - four instructions, and the disp8 the cave uses."""
        assert PRODUCTION_ENTRY_NEXT == 0x48
        assert PRODUCTION_UPDATE_GET_NEXT != PRODUCTION_UPDATE_PICK_ENTRY

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = synthetic_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            HeroRecruitParallelPatch().apply(data)

    def test_a_moved_anchor_leaves_the_hook_alone(self):
        data = synthetic_image()
        off = va_to_offset(data, PRODUCTION_UPDATE_PICK_RETURN)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            HeroRecruitParallelPatch().apply(data)
        hook = va_to_offset(data, HOOK_VA)
        assert bytes(data[hook : hook + len(HOOK_ORIGINAL)]) == HOOK_ORIGINAL


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        HeroRecruitParallelPatch().apply(data)
        assert HeroRecruitParallelPatch().verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert HeroRecruitParallelPatch().verify(synthetic_image())

    def test_the_hook_jumps_to_the_cave(self):
        data = synthetic_image()
        HeroRecruitParallelPatch().apply(data)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        off = va_to_offset(data, HOOK_VA)
        assert data[off] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0] == located[0]

    def test_the_two_spare_bytes_are_padded(self):
        """A five-byte jump in a seven-byte hole leaves two bytes that are still reachable by
        falling through, so they have to be `nop`s and not the tail of the old head load."""
        data = synthetic_image()
        HeroRecruitParallelPatch().apply(data)
        off = va_to_offset(data, HOOK_VA)
        assert bytes(data[off + 5 : off + len(HOOK_ORIGINAL)]) == b"\x90\x90"

    def test_it_touches_nothing_but_the_hook(self):
        before = synthetic_image()
        data = synthetic_image()
        HeroRecruitParallelPatch().apply(data)
        hook = va_to_offset(before, HOOK_VA)
        changed = [
            i
            for i in range(len(before))
            if before[i] != data[i] and not hook <= i < hook + len(HOOK_ORIGINAL)
        ]
        # only the PE header (a new section) and the appended cave itself
        located = find_section(data, SECTION_NAME)
        assert located is not None
        assert all(i < 0x400 or i >= located[1] for i in changed)

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        HeroRecruitParallelPatch().apply(data)
        with pytest.raises(ValueError):
            HeroRecruitParallelPatch().apply(data)


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[HeroRecruitParallelPatch.name] is HeroRecruitParallelPatch

    def test_detect_finds_it_only_once_applied(self):
        data = synthetic_image()
        assert HeroRecruitParallelPatch.detect(data) is None
        HeroRecruitParallelPatch().apply(data)
        assert HeroRecruitParallelPatch.detect(data) is not None

    def test_the_description_promises_the_revive_time_is_unchanged(self):
        assert "revive time is unchanged" in HeroRecruitParallelPatch.description
