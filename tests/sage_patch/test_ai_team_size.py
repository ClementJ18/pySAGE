"""Tests for the AI team-size patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble
it back and assert it says what it was meant to say. A wrong branch sense here does not crash -
it makes every AI team count as empty, or count as it always did - so the encoding has to be
caught statically.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    AI_TEAM_BUILDER_DONE_SIZE_CALL,
    AI_TEAM_BUILDER_RECRUIT_SIZE_CALL,
    AI_TEAM_SIZE,
    AI_TEAM_SIZE_BACK_EDGE,
    AI_TEAM_SIZE_BACK_EDGE_BYTES,
    AI_TEAM_SIZE_KINDOF_TESTS,
    AI_TEAM_SIZE_NEXT,
    OBJECT_STATUS,
    OBJECT_STATUS_HORDE_MEMBER,
)
from sage_patch.patches import ai_construction_gate as construction
from sage_patch.patches import ai_revive_gate as revive
from sage_patch.patches.ai_team_size import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    AiTeamSizePatch,
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

    def test_it_reloads_the_member_the_hook_displaced(self):
        first = disassemble()[0]
        assert (first.mnemonic, first.op_str) == ("mov", "eax, dword ptr [ebp - 0x18]")

    def test_it_tests_horde_member_on_the_object(self):
        """Bit 38 of the status mask at `Object+0x94` is `0x40` of the byte at `+0x98`; testing the
        wrong byte would skip some other status and count members as before."""
        test = disassemble()[1]
        assert test.mnemonic == "test"
        assert OBJECT_STATUS + (OBJECT_STATUS_HORDE_MEMBER // 32) * 4 == 0x98
        assert test.op_str == "byte ptr [eax + 0x98], 0x40"

    def test_a_member_is_skipped_and_anything_else_reaches_the_kindof_tests(self):
        """Set bit (a member) takes the `jne` to the iterator's advance; clear bit falls through to
        the displaced template read and the stock tests. Inverted, only members would count."""
        insns = disassemble()
        jne = next(i for i in insns if i.mnemonic == "jne")
        fall = [i for i in insns if jne.address < i.address < int(jne.op_str, 16)]
        assert [(i.mnemonic, i.op_str) for i in fall][0] == ("mov", "eax, dword ptr [eax + 4]")
        assert (fall[-1].mnemonic, int(fall[-1].op_str, 16)) == ("jmp", AI_TEAM_SIZE_KINDOF_TESTS)
        taken = next(i for i in insns if i.address == int(jne.op_str, 16))
        assert (taken.mnemonic, int(taken.op_str, 16)) == ("jmp", AI_TEAM_SIZE_NEXT)

    def test_it_writes_only_eax(self):
        """`edi` is the running count and `esi` the mask the stock tests reuse."""
        for ins in disassemble():
            if ins.mnemonic == "mov":
                assert ins.op_str.startswith("eax,"), ins.op_str

    def test_it_has_exactly_two_exits_both_into_the_count(self):
        exits = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "jmp"}
        assert exits == {AI_TEAM_SIZE_KINDOF_TESTS, AI_TEAM_SIZE_NEXT}

    def test_it_makes_no_calls(self):
        assert not [i for i in disassemble() if i.mnemonic == "call"]

    def test_every_conditional_branch_stays_inside_the_cave(self):
        code = build_code(BASE)
        lo, hi = BASE, BASE + len(code)
        for ins in disassemble():
            if not ins.mnemonic.startswith("j") or ins.mnemonic == "jmp":
                continue
            assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b, "the absolute jumps must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        AiTeamSizePatch().apply(data)
        assert AiTeamSizePatch().verify(data) == []

    def test_the_hook_is_a_jmp_to_the_cave_then_a_nop(self):
        data = synthetic_image()
        AiTeamSizePatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        site = bytes(data[off : off + len(HOOK_ORIGINAL)])
        assert site[0] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va
        assert site[5] == 0x90

    def test_the_back_edge_still_lands_on_the_hook(self):
        """The loop's `jne` is the only branch into the head; it must reach the new `jmp`, not the
        middle of the displaced bytes."""
        rel = struct.unpack("<b", AI_TEAM_SIZE_BACK_EDGE_BYTES[1:2])[0]
        assert AI_TEAM_SIZE_BACK_EDGE + 2 + rel == HOOK_VA

    def test_the_anchored_calls_really_name_the_count(self):
        """Their five bytes are the displacement, so asserting them asserts the team builder
        calls the function being edited."""
        for site in (AI_TEAM_BUILDER_RECRUIT_SIZE_CALL, AI_TEAM_BUILDER_DONE_SIZE_CALL):
            call = ANCHORS[site]
            assert site + 5 + struct.unpack("<i", call[1:5])[0] == AI_TEAM_SIZE

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        AiTeamSizePatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            AiTeamSizePatch().apply(data)

    def test_a_moved_resume_point_refuses_to_apply(self):
        data = synthetic_image()
        va = AI_TEAM_SIZE_KINDOF_TESTS
        data[va - IMAGE_BASE : va - IMAGE_BASE + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            AiTeamSizePatch().apply(data)

    def test_a_rewritten_team_builder_call_refuses_to_apply(self):
        data = synthetic_image()
        struct.pack_into("<i", data, AI_TEAM_BUILDER_DONE_SIZE_CALL - IMAGE_BASE + 1, 0x1234)
        with pytest.raises(ValueError, match="not this build's"):
            AiTeamSizePatch().apply(data)

    def test_it_does_not_touch_the_count_beyond_the_six_hooked_bytes(self):
        before = synthetic_image()
        data = synthetic_image()
        AiTeamSizePatch().apply(data)
        for va in (AI_TEAM_SIZE, AI_TEAM_SIZE_KINDOF_TESTS, AI_TEAM_SIZE_NEXT):
            o = va - IMAGE_BASE
            assert data[o : o + 7] == before[o : o + 7], f"{va:#010x} was rewritten"


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[AiTeamSizePatch.name] is AiTeamSizePatch

    @pytest.mark.parametrize("other", [construction, revive])
    def test_it_composes_with_the_other_ai_patches(self, other):
        mine = set(range(HOOK_VA, HOOK_VA + len(HOOK_ORIGINAL)))
        theirs = set(range(other.HOOK_VA, other.HOOK_VA + len(other.HOOK_ORIGINAL)))
        assert not mine & theirs
        assert not set(ANCHORS) & theirs
        assert not mine & set(other.ANCHORS)
