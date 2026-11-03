"""Tests for the null-guards patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble
it back and assert each guard says what it was meant to say. A wrong byte here does not raise - it
either crashes the game exactly as before or, worse, leaves a function with an unbalanced stack or
the wrong answer. Both have to be caught statically.
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
    AI_MOVE_AND_ENTER_EDI_POP,
    AI_MOVE_AND_ENTER_EDI_PUSH,
    AI_MOVE_AND_ENTER_GOAL_CALL,
    AI_MOVE_AND_ENTER_GOAL_CALL_BYTES,
    AI_MOVE_AND_ENTER_ON_ENTER,
    AI_MOVE_AND_ENTER_ON_ENTER_SLOT,
    AI_MOVE_AND_ENTER_RESUME,
    AI_MOVE_AND_ENTER_STATE_VTABLE,
    AI_MOVE_AND_ENTER_TAIL,
    AI_STATE_FAILURE,
    AI_STATE_ON_ENTER_SLOT,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.ai import ai_construction_gate as construction
from sage_patch.patches.platform.null_guards import (
    ANCHORS,
    ENTER_HOOK_ORIGINAL,
    ENTER_HOOK_VA,
    NOT_WORTH_TRANSFERRING,
    SECTION_NAME,
    TRANSFER_CALL_TARGETS,
    TRANSFER_HOOK_ORIGINAL,
    TRANSFER_HOOK_VA,
    NullGuardsPatch,
    build_code,
    hooks,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import null_guards_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: `AI_COMMAND_TRANSFER_CHECK` runs from its SEH prologue to the `ret 0xc0` at 0x0066C492. The
#: interior-branch sweep stops there: a branch from outside a function into the middle of one of
#: its instructions is not something MSVC emits, and the window sits mid-function.
_CHECK_SIZE = 0x0066C495 - AI_COMMAND_TRANSFER_CHECK
#: `AI_MOVE_AND_ENTER_ON_ENTER` runs to the `ret` at 0x00751B4F.
_ON_ENTER_SIZE = 0x00751B50 - AI_MOVE_AND_ENTER_ON_ENTER


def _entry(site: int, base: int = BASE) -> int:
    """Where a site's hook jumps to in a cave built at `base`."""
    _stock, patched = hooks(base)[site]
    return site + 5 + struct.unpack_from("<i", patched, 1)[0]


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_code(base), base))


def transfer_guard(base: int = BASE):
    end = _entry(ENTER_HOOK_VA, base)
    return [i for i in disassemble(base) if _entry(TRANSFER_HOOK_VA, base) <= i.address < end]


def enter_guard(base: int = BASE):
    return [i for i in disassemble(base) if i.address >= _entry(ENTER_HOOK_VA, base)]


def _jump_target(ins) -> int:
    return int(ins.op_str, 16)


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_each_hook_lands_on_an_instruction_boundary(self):
        starts = {i.address for i in disassemble()}
        assert _entry(TRANSFER_HOOK_VA) in starts
        assert _entry(ENTER_HOOK_VA) in starts

    def test_it_calls_nothing(self):
        assert not [i for i in disassemble() if i.mnemonic == "call"]

    def test_every_conditional_branch_stays_inside_its_own_guard(self):
        """A displacement computed wrong would jump into arbitrary engine code, or into the other
        guard with the wrong registers."""
        for guard in (transfer_guard(), enter_guard()):
            lo = guard[0].address
            hi = guard[-1].address + guard[-1].size
            for ins in guard:
                if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
                    assert lo <= _jump_target(ins) < hi, f"{ins.mnemonic} at {ins.address:#x}"

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b, "the absolute jumps must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestTheTransferGuard:
    def test_it_opens_by_testing_the_target_pointer(self):
        """`eax` holds `AICommandParms::m_obj`, loaded by the instruction before the window."""
        first = transfer_guard()[0]
        assert (first.mnemonic, first.op_str) == ("test", "eax, eax")

    def test_a_live_target_runs_the_displaced_instruction_verbatim(self):
        """The stock instruction stream has to survive byte-for-byte on the common path."""
        code = build_code(BASE)
        subss = next(i for i in transfer_guard() if i.mnemonic == "subss")
        assert subss.op_str == "xmm0, dword ptr [eax + 0x38]"
        assert code[subss.address - BASE : subss.address - BASE + subss.size] == (
            TRANSFER_HOOK_ORIGINAL
        )

    def test_a_live_target_resumes_at_the_next_instruction(self):
        insns = transfer_guard()
        subss = next(i for i in insns if i.mnemonic == "subss")
        resume = next(i for i in insns if i.address == subss.address + subss.size)
        assert (resume.mnemonic, _jump_target(resume)) == ("jmp", AI_COMMAND_TRANSFER_RESUME)

    def test_a_null_target_is_the_taken_edge(self):
        """`test`/`je` - zero is NULL. Inverting this would guard every live target instead and
        never transfer anything."""
        insns = transfer_guard()
        taken = next(i for i in insns if i.mnemonic == "je")
        arm = next(i for i in insns if i.address == _jump_target(taken))
        assert (arm.mnemonic, arm.op_str) == ("mov", f"bl, {NOT_WORTH_TRANSFERRING}")

    def test_a_null_target_answers_do_not_transfer(self):
        """Both callers read the answer as `test al, al` / `jne` **past** the re-issue, so the
        null answer must be non-zero. Answering zero would hand the same NULL-carrying parms to
        the replacement object's state machine - the fault moved, not removed."""
        assert NOT_WORTH_TRANSFERRING != 0
        insns = transfer_guard()
        write = next(i for i in insns if i.mnemonic == "mov" and i.op_str.startswith("bl"))
        assert write.operands[1].imm == NOT_WORTH_TRANSFERRING
        after = next(i for i in insns if i.address == write.address + write.size)
        assert (after.mnemonic, _jump_target(after)) == ("jmp", AI_COMMAND_TRANSFER_ANSWER)

    def test_it_reuses_the_functions_own_tail_rather_than_duplicating_it(self):
        """The tail restores the SEH state and frees the parms' waypoint vector. A cave that
        returned on its own would leak that vector on every guarded call."""
        exits = {_jump_target(i) for i in transfer_guard() if i.mnemonic == "jmp"}
        assert exits == {AI_COMMAND_TRANSFER_RESUME, AI_COMMAND_TRANSFER_ANSWER}

    def test_it_writes_only_the_answer_register(self):
        """`bl` is the one thing the guard is allowed to change: `xmm0` is the displaced
        instruction's own output, and every other register is live across the resume point."""
        written = {
            i.op_str.split(",")[0]
            for i in transfer_guard()
            if i.mnemonic in {"mov", "movss", "xor", "or", "and", "add", "sub"}
        }
        assert written == {"bl"}

    def test_the_anchored_load_is_what_fixes_the_target_slot(self):
        """The guard tests whatever `AI_COMMAND_TRANSFER_TARGET_LOAD` produced, so the constant
        naming the slot and the instruction reading it must agree - `mov eax, [ebp+0x1c]`."""
        assert AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES == bytes((0x8B, 0x45, AI_COMMAND_OBJECT_EBP))

    def test_the_load_sits_immediately_before_the_hooked_window(self):
        """If anything came between them, `eax` at the window would not be the target."""
        end = AI_COMMAND_TRANSFER_TARGET_LOAD + len(AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES)
        assert end == TRANSFER_HOOK_VA
        assert AI_COMMAND_TRANSFER_OBJECT_ARM < AI_COMMAND_TRANSFER_TARGET_LOAD

    def test_both_calls_really_name_the_patched_function(self):
        """Their five bytes *are* the displacement, so asserting them asserts the target."""
        assert TRANSFER_CALL_TARGETS == (AI_COMMAND_TRANSFER_CHECK, AI_COMMAND_TRANSFER_CHECK)

    def test_the_window_is_exactly_one_jmp_with_no_padding(self):
        assert len(TRANSFER_HOOK_ORIGINAL) == 5
        _stock, patched = hooks(BASE)[TRANSFER_HOOK_VA]
        assert patched[0] == 0xE9 and len(patched) == 5


class TestTheEnterGuard:
    def test_it_tests_the_goal_object_before_reading_its_contain(self):
        """`eax` is what `getGoalObject` returned; a NULL goal faults on the contain load itself."""
        insns = enter_guard()
        assert (insns[0].mnemonic, insns[0].op_str) == ("test", "eax, eax")
        assert insns[1].mnemonic == "je"
        assert (insns[2].mnemonic, insns[2].op_str) == ("mov", "ecx, dword ptr [eax + 0x258]")

    def test_it_tests_the_contain_before_the_resume(self):
        insns = enter_guard()
        assert (insns[3].mnemonic, insns[3].op_str) == ("test", "ecx, ecx")
        assert insns[4].mnemonic == "je"
        assert _jump_target(insns[1]) == _jump_target(insns[4]), "both NULLs take one exit"

    def test_a_live_contain_runs_the_window_verbatim_and_resumes(self):
        """Both displaced instructions survive byte-for-byte, the store last so `[ebp-0xc]` is
        written only on the path that goes on to use it."""
        code = build_code(BASE)
        insns = enter_guard()
        load, store, resume = insns[2], insns[5], insns[6]
        window = code[load.address - BASE : load.address - BASE + load.size]
        window += code[store.address - BASE : store.address - BASE + store.size]
        assert window == ENTER_HOOK_ORIGINAL
        assert (store.mnemonic, store.op_str) == ("mov", "dword ptr [ebp - 0xc], eax")
        assert (resume.mnemonic, _jump_target(resume)) == ("jmp", AI_MOVE_AND_ENTER_RESUME)

    def test_the_failure_edge_balances_the_stack_and_answers_failure(self):
        """At the hook `[esp]` is the saved `edi`; the tail pops `esi` and `ebx` and `leave`s, so
        the guard pops exactly `edi` and hands the answer over in `esi`."""
        insns = enter_guard()
        fail = [i for i in insns if i.address >= _jump_target(insns[1])]
        assert [(i.mnemonic, i.op_str) for i in fail[:3]] == [
            ("pop", "edi"),
            ("push", str(AI_STATE_FAILURE)),
            ("pop", "esi"),
        ]
        assert (fail[3].mnemonic, _jump_target(fail[3])) == ("jmp", AI_MOVE_AND_ENTER_TAIL)
        assert len(fail) == 4

    def test_its_only_exits_are_the_resume_and_the_tail(self):
        exits = {_jump_target(i) for i in enter_guard() if i.mnemonic == "jmp"}
        assert exits == {AI_MOVE_AND_ENTER_RESUME, AI_MOVE_AND_ENTER_TAIL}

    def test_the_failure_value_is_the_one_ai_enter_state_uses(self):
        """`push -2` as a sign-extended imm8 - the encoding `AIEnterState::onEnter` refuses with."""
        assert AI_STATE_FAILURE == -2
        assert ANCHORS[0x0075170C] == bytes((0x6A, AI_STATE_FAILURE & 0xFF, 0x58))

    def test_the_window_is_a_jmp_and_four_nops(self):
        assert len(ENTER_HOOK_ORIGINAL) == 9
        _stock, patched = hooks(BASE)[ENTER_HOOK_VA]
        assert patched[0] == 0xE9 and patched[5:] == b"\x90" * 4

    def test_the_goal_call_sits_immediately_before_the_window(self):
        """If anything came between them, `eax` at the window would not be the goal object."""
        assert AI_MOVE_AND_ENTER_GOAL_CALL + len(AI_MOVE_AND_ENTER_GOAL_CALL_BYTES) == ENTER_HOOK_VA

    def test_the_stack_landmarks_bracket_the_window(self):
        """`push edi` before the goal call, `pop edi` after the resume, tail last."""
        assert AI_MOVE_AND_ENTER_ON_ENTER < AI_MOVE_AND_ENTER_EDI_PUSH < AI_MOVE_AND_ENTER_GOAL_CALL
        assert ENTER_HOOK_VA < AI_MOVE_AND_ENTER_RESUME < AI_MOVE_AND_ENTER_EDI_POP
        assert AI_MOVE_AND_ENTER_EDI_POP < AI_MOVE_AND_ENTER_TAIL

    def test_the_anchored_slot_is_the_states_on_enter(self):
        """The vtable slot's four bytes are the function's address, so asserting them proves the
        edited function is `AIMoveToPositionAndEnterState::onEnter`."""
        assert AI_MOVE_AND_ENTER_ON_ENTER_SLOT == (
            AI_MOVE_AND_ENTER_STATE_VTABLE + AI_STATE_ON_ENTER_SLOT
        )
        slot = ANCHORS[AI_MOVE_AND_ENTER_ON_ENTER_SLOT]
        assert struct.unpack("<I", slot)[0] == AI_MOVE_AND_ENTER_ON_ENTER


class TestApply:
    def test_apply_then_verify(self):
        data = null_guards_image()
        NullGuardsPatch().apply(data)
        assert NullGuardsPatch().verify(data) == []

    def test_every_window_jumps_to_its_own_guard(self):
        data = null_guards_image()
        NullGuardsPatch().apply(data)
        cave_va, _off, _vsize = find_section(data, SECTION_NAME)
        for site in (TRANSFER_HOOK_VA, ENTER_HOOK_VA):
            off = va_to_offset(data, site)
            assert data[off] == 0xE9
            target = site + 5 + struct.unpack_from("<i", data, off + 1)[0]
            assert target == _entry(site, cave_va)

    def test_the_cave_holds_the_expected_guards(self):
        data = null_guards_image()
        NullGuardsPatch().apply(data)
        cave_va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + len(build_code(cave_va))]) == build_code(cave_va)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"

    def test_refuses_to_apply_twice(self):
        data = null_guards_image()
        NullGuardsPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            NullGuardsPatch().apply(data)

    @pytest.mark.parametrize("anchor", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, anchor: int):
        data = null_guards_image()
        off = va_to_offset(data, anchor)
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not this build's"):
            NullGuardsPatch().apply(data)

    def test_verify_names_an_unhooked_site(self):
        data = null_guards_image()
        NullGuardsPatch().apply(data)
        off = va_to_offset(data, ENTER_HOOK_VA)
        data[off : off + len(ENTER_HOOK_ORIGINAL)] = ENTER_HOOK_ORIGINAL
        problems = NullGuardsPatch().verify(data)
        assert len(problems) == 1 and f"0x{ENTER_HOOK_VA:08x}" in problems[0]

    def test_it_does_not_touch_the_sites_the_cave_jumps_into(self):
        before = null_guards_image()
        data = null_guards_image()
        NullGuardsPatch().apply(data)
        for va in (
            AI_COMMAND_TRANSFER_RESUME,
            AI_COMMAND_TRANSFER_ANSWER,
            AI_COMMAND_TRANSFER_CHECK,
            AI_MOVE_AND_ENTER_RESUME,
            AI_MOVE_AND_ENTER_TAIL,
        ):
            o = va_to_offset(data, va)
            assert data[o : o + 4] == before[o : o + 4], f"{va:#010x} was rewritten"


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[NullGuardsPatch.name] is NullGuardsPatch

    def test_it_is_not_experimental(self):
        assert not NullGuardsPatch().experimental

    def test_it_declares_no_parameters(self):
        """`detect` takes the default, which is only correct for a patch with none."""
        assert NullGuardsPatch().options() == {}

    def test_it_composes_with_the_other_ai_patch_in_this_range(self):
        mine = set()
        for site, (stock, _patched) in hooks(BASE).items():
            mine |= set(range(site, site + len(stock)))
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

    def test_every_window_holds_its_stock_bytes(self, game_dat: bytes) -> None:
        for site, (stock, _patched) in hooks(BASE).items():
            off = va_to_offset(game_dat, site)
            assert bytes(game_dat[off : off + len(stock)]) == stock, f"0x{site:08X}"

    @pytest.mark.parametrize(
        ("site", "function", "size"),
        [
            (TRANSFER_HOOK_VA, AI_COMMAND_TRANSFER_CHECK, _CHECK_SIZE),
            (ENTER_HOOK_VA, AI_MOVE_AND_ENTER_ON_ENTER, _ON_ENTER_SIZE),
        ],
    )
    def test_nothing_branches_into_a_window(
        self, game_dat: bytes, site: int, function: int, size: int
    ) -> None:
        """A window is taken whole, so an inbound branch to any of its interior bytes would land
        mid-`jmp`. Swept over the whole containing function."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        stock, _patched = hooks(BASE)[site]
        off = va_to_offset(game_dat, function)
        interior = set(range(site + 1, site + len(stock)))
        for ins in md.disasm(game_dat[off : off + size], function):
            if not ins.mnemonic.startswith("j"):
                continue
            target = int(ins.op_str, 16) if ins.op_str.startswith("0x") else None
            assert target not in interior, f"{ins.mnemonic} at {ins.address:#010x} splits a hook"

    def test_the_enter_function_ends_in_the_anchored_tail(self, game_dat: bytes) -> None:
        """The sweep above stops at the tail's `ret`; the whole function decoding into it is what
        makes that bound honest."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        off = va_to_offset(game_dat, AI_MOVE_AND_ENTER_ON_ENTER)
        insns = list(md.disasm(game_dat[off : off + _ON_ENTER_SIZE], AI_MOVE_AND_ENTER_ON_ENTER))
        assert sum(i.size for i in insns) == _ON_ENTER_SIZE
        assert insns[-1].mnemonic == "ret"
        assert any(i.address == AI_MOVE_AND_ENTER_TAIL for i in insns)

    def test_the_answer_register_is_seeded_before_the_object_arm(self, game_dat: bytes) -> None:
        assert AI_COMMAND_TRANSFER_BOOL_INIT < AI_COMMAND_TRANSFER_OBJECT_ARM < TRANSFER_HOOK_VA
        assert TRANSFER_HOOK_VA < AI_COMMAND_TRANSFER_ANSWER < AI_COMMAND_TRANSFER_ANSWER_READ

    def test_both_call_sites_resolve_to_the_check(self, game_dat: bytes) -> None:
        for va in (AI_COMMAND_TRANSFER_MOUNT_CALL, AI_COMMAND_TRANSFER_DISMOUNT_CALL):
            off = va_to_offset(game_dat, va)
            assert game_dat[off] == 0xE8
            target = va + 5 + struct.unpack_from("<i", game_dat, off + 1)[0]
            assert target == AI_COMMAND_TRANSFER_CHECK, f"0x{va:08X}"

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        out = apply_patches(src, [NullGuardsPatch()], tmp_path / "out.dat")
        data = out.read_bytes()
        assert NullGuardsPatch().verify(data) == []
        assert NullGuardsPatch.detect(data) is not None
        assert src.read_bytes() == game_dat, "the input was modified"

    def test_it_is_not_detected_in_the_unpatched_binary(self, game_dat: bytes) -> None:
        assert NullGuardsPatch.detect(game_dat) is None
