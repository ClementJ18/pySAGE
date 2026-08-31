"""Tests for the AI command null-target patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble
it back and assert it says what it was meant to say. A wrong byte here does not raise - it either
crashes the game exactly as before or, worse, answers the transfer question backwards and hands a
NULL-carrying `AICommandParms` to the replacement object. Both have to be caught statically.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    AI_COMMAND_OBJECT_EBP,
    AI_COMMAND_TRANSFER_ANSWER,
    AI_COMMAND_TRANSFER_ANSWER_READ,
    AI_COMMAND_TRANSFER_BOOL_INIT,
    AI_COMMAND_TRANSFER_CHECK,
    AI_COMMAND_TRANSFER_DISMOUNT_CALL,
    AI_COMMAND_TRANSFER_MOUNT_CALL,
    AI_COMMAND_TRANSFER_OBJECT_ARM,
    AI_COMMAND_TRANSFER_RESUME,
    AI_COMMAND_TRANSFER_TARGET_LOAD,
    AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches import ai_construction_gate as construction
from sage_patch.patches.ai_command_null_target import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    NOT_WORTH_TRANSFERRING,
    SECTION_NAME,
    TRANSFER_CALL_TARGETS,
    AiCommandNullTargetPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import ai_command_null_target_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: `AI_COMMAND_TRANSFER_CHECK` runs from its SEH prologue to the `ret 0xc0` at 0x0066C492. The
#: interior-branch sweep stops there: a branch from outside a function into the middle of one of
#: its instructions is not something MSVC emits, and the window sits mid-function.
_CHECK_SIZE = 0x0066C495 - AI_COMMAND_TRANSFER_CHECK


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

    def test_it_opens_by_testing_the_target_pointer(self):
        """`eax` holds `AICommandParms::m_obj`, loaded by the instruction before the window."""
        first = disassemble()[0]
        assert (first.mnemonic, first.op_str) == ("test", "eax, eax")

    def test_a_live_target_runs_the_displaced_instruction_verbatim(self):
        """The stock instruction stream has to survive byte-for-byte on the common path: this
        guard is on a hot-ish edge and must add a test, not a reimplementation."""
        code = build_code(BASE)
        assert HOOK_ORIGINAL in code
        subss = next(i for i in disassemble() if i.mnemonic == "subss")
        assert subss.op_str == "xmm0, dword ptr [eax + 0x38]"
        assert code[subss.address - BASE : subss.address - BASE + subss.size] == HOOK_ORIGINAL

    def test_a_live_target_resumes_at_the_next_instruction(self):
        insns = disassemble()
        subss = next(i for i in insns if i.mnemonic == "subss")
        resume = next(i for i in insns if i.address == subss.address + subss.size)
        assert (resume.mnemonic, int(resume.op_str, 16)) == ("jmp", AI_COMMAND_TRANSFER_RESUME)

    def test_a_null_target_is_the_taken_edge(self):
        """`test`/`je` - zero is NULL. Inverting this would guard every live target instead and
        never transfer anything."""
        insns = disassemble()
        taken = next(i for i in insns if i.mnemonic == "je")
        target = int(taken.op_str, 16)
        arm = next(i for i in insns if i.address == target)
        assert (arm.mnemonic, arm.op_str) == ("mov", f"bl, {NOT_WORTH_TRANSFERRING}")

    def test_a_null_target_answers_do_not_transfer(self):
        """Both callers read the answer as `test al, al` / `jne` **past** the re-issue, so the
        null answer must be non-zero. Answering zero would hand the same NULL-carrying parms to
        the replacement object's state machine - the fault moved, not removed."""
        assert NOT_WORTH_TRANSFERRING != 0
        insns = disassemble()
        write = next(i for i in insns if i.mnemonic == "mov" and i.op_str.startswith("bl"))
        assert write.operands[1].imm == NOT_WORTH_TRANSFERRING
        after = next(i for i in insns if i.address == write.address + write.size)
        assert (after.mnemonic, int(after.op_str, 16)) == ("jmp", AI_COMMAND_TRANSFER_ANSWER)

    def test_it_reuses_the_functions_own_tail_rather_than_duplicating_it(self):
        """The tail restores the SEH state and frees the parms' waypoint vector. A cave that
        returned on its own would leak that vector on every guarded call."""
        exits = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "jmp"}
        assert exits == {AI_COMMAND_TRANSFER_RESUME, AI_COMMAND_TRANSFER_ANSWER}

    def test_it_calls_nothing(self):
        assert not [i for i in disassemble() if i.mnemonic == "call"]

    def test_it_writes_only_the_answer_register(self):
        """`bl` is the one thing the cave is allowed to change: `xmm0` is the displaced
        instruction's own output, and every other register is live across the resume point."""
        written = {
            i.op_str.split(",")[0]
            for i in disassemble()
            if i.mnemonic in {"mov", "movss", "xor", "or", "and", "add", "sub"}
        }
        assert written == {"bl"}

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
        assert a != b, "the two absolute jumps must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestTheFrameSlot:
    def test_the_anchored_load_is_what_fixes_the_target_slot(self):
        """The guard tests whatever `AI_COMMAND_TRANSFER_TARGET_LOAD` produced, so the constant
        naming the slot and the instruction reading it must agree - `mov eax, [ebp+0x1c]`."""
        assert AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES == bytes((0x8B, 0x45, AI_COMMAND_OBJECT_EBP))

    def test_the_load_sits_immediately_before_the_hooked_window(self):
        """If anything came between them, `eax` at the window would not be the target."""
        end = AI_COMMAND_TRANSFER_TARGET_LOAD + len(AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES)
        assert end == HOOK_VA

    def test_the_load_belongs_to_the_object_arm(self):
        assert AI_COMMAND_TRANSFER_OBJECT_ARM < AI_COMMAND_TRANSFER_TARGET_LOAD < HOOK_VA


class TestTheCallSites:
    def test_both_calls_really_name_the_patched_function(self):
        """Why anchoring the two call sites proves the function being edited is the one the mount
        swap reaches: their five bytes *are* the displacement, so asserting them asserts the
        target. A build that moved the check fails on the anchor."""
        assert TRANSFER_CALL_TARGETS == (AI_COMMAND_TRANSFER_CHECK, AI_COMMAND_TRANSFER_CHECK)

    def test_a_rewritten_call_site_refuses_to_apply(self):
        data = ai_command_null_target_image()
        off = va_to_offset(data, AI_COMMAND_TRANSFER_MOUNT_CALL)
        struct.pack_into("<i", data, off + 1, 0x1234)
        with pytest.raises(ValueError, match="not this build's"):
            AiCommandNullTargetPatch().apply(data)


class TestApply:
    def test_apply_then_verify(self):
        data = ai_command_null_target_image()
        AiCommandNullTargetPatch().apply(data)
        assert AiCommandNullTargetPatch().verify(data) == []

    def test_the_window_is_exactly_one_jmp_with_no_padding(self):
        """Five bytes is a `jmp rel32` exactly, which is why this hook leaves no half-instruction
        and needs no `nop`."""
        assert len(HOOK_ORIGINAL) == 5
        data = ai_command_null_target_image()
        AiCommandNullTargetPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        site = bytes(data[off : off + len(HOOK_ORIGINAL)])
        assert site[0] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va

    def test_the_cave_holds_the_expected_guard(self):
        data = ai_command_null_target_image()
        AiCommandNullTargetPatch().apply(data)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + len(build_code(section_va))]) == build_code(section_va)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        data = ai_command_null_target_image()
        AiCommandNullTargetPatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self):
        data = ai_command_null_target_image()
        AiCommandNullTargetPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            AiCommandNullTargetPatch().apply(data)

    def test_a_moved_anchor_refuses_to_apply(self):
        data = ai_command_null_target_image()
        off = va_to_offset(data, AI_COMMAND_TRANSFER_ANSWER)
        data[off : off + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            AiCommandNullTargetPatch().apply(data)

    def test_it_does_not_touch_the_sites_the_cave_jumps_into(self):
        """The resume point and the tail both have to survive: the cave jumps into them."""
        before = ai_command_null_target_image()
        data = ai_command_null_target_image()
        AiCommandNullTargetPatch().apply(data)
        for va in (
            AI_COMMAND_TRANSFER_RESUME,
            AI_COMMAND_TRANSFER_ANSWER,
            AI_COMMAND_TRANSFER_CHECK,
        ):
            o = va_to_offset(data, va)
            assert data[o : o + 4] == before[o : o + 4], f"{va:#010x} was rewritten"


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[AiCommandNullTargetPatch.name] is AiCommandNullTargetPatch

    def test_it_is_not_experimental(self):
        assert not AiCommandNullTargetPatch().experimental

    def test_it_declares_no_parameters(self):
        """`detect` takes the default, which is only correct for a patch with none."""
        assert AiCommandNullTargetPatch().options() == {}

    def test_it_composes_with_the_other_ai_patch_in_this_range(self):
        mine = set(range(HOOK_VA, HOOK_VA + len(HOOK_ORIGINAL)))
        theirs = set(
            range(construction.HOOK_VA, construction.HOOK_VA + len(construction.HOOK_ORIGINAL))
        )
        assert not mine & theirs
        assert not mine & set(construction.ANCHORS)
        assert not set(ANCHORS) & theirs


class TestTheRealBinary:
    """The synthetic image proves the patch is self-consistent; only a real `game.dat` proves the
    addresses are right. Skipped where there is none, which is every machine but the author's."""

    @staticmethod
    @pytest.fixture(scope="class")
    def game_dat() -> bytes:
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_what_the_patch_says_it_holds(self, game_dat: bytes) -> None:
        for va, expected in sorted(ANCHORS.items()):
            off = va_to_offset(game_dat, va)
            assert off is not None, f"0x{va:08X}"
            assert bytes(game_dat[off : off + len(expected)]) == expected, f"0x{va:08X}"

    def test_the_window_holds_the_faulting_instruction(self, game_dat: bytes) -> None:
        off = va_to_offset(game_dat, HOOK_VA)
        assert bytes(game_dat[off : off + len(HOOK_ORIGINAL)]) == HOOK_ORIGINAL

    def test_nothing_branches_into_the_window(self, game_dat: bytes) -> None:
        """The window is taken whole, so an inbound branch to any of its four interior bytes
        would land mid-`jmp`. Swept over the whole containing function."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        off = va_to_offset(game_dat, AI_COMMAND_TRANSFER_CHECK)
        body = game_dat[off : off + _CHECK_SIZE]
        interior = set(range(HOOK_VA + 1, HOOK_VA + len(HOOK_ORIGINAL)))
        for ins in md.disasm(body, AI_COMMAND_TRANSFER_CHECK):
            if not ins.mnemonic.startswith("j"):
                continue
            target = int(ins.op_str, 16) if ins.op_str.startswith("0x") else None
            assert target not in interior, f"{ins.mnemonic} at {ins.address:#010x} splits the hook"

    def test_the_answer_register_is_seeded_before_the_object_arm(self, game_dat: bytes) -> None:
        """The cave writes `bl` rather than inheriting it, but the tail still reads `bl` - so the
        seed and the read both have to be where the patch thinks they are."""
        assert AI_COMMAND_TRANSFER_BOOL_INIT < AI_COMMAND_TRANSFER_OBJECT_ARM < HOOK_VA
        assert HOOK_VA < AI_COMMAND_TRANSFER_ANSWER < AI_COMMAND_TRANSFER_ANSWER_READ

    def test_both_call_sites_resolve_to_the_check(self, game_dat: bytes) -> None:
        for va in (AI_COMMAND_TRANSFER_MOUNT_CALL, AI_COMMAND_TRANSFER_DISMOUNT_CALL):
            off = va_to_offset(game_dat, va)
            assert game_dat[off] == 0xE8
            target = va + 5 + struct.unpack_from("<i", game_dat, off + 1)[0]
            assert target == AI_COMMAND_TRANSFER_CHECK, f"0x{va:08X}"

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        out = apply_patches(src, [AiCommandNullTargetPatch()], tmp_path / "out.dat")
        data = out.read_bytes()
        assert AiCommandNullTargetPatch().verify(data) == []
        assert AiCommandNullTargetPatch.detect(data) is not None
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert target == section_va
        assert src.read_bytes() == game_dat, "the input was modified"

    def test_it_is_not_detected_in_the_unpatched_binary(self, game_dat: bytes) -> None:
        assert AiCommandNullTargetPatch.detect(game_dat) is None
