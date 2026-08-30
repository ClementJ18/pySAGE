"""Tests for the deploy-before-attack patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble it
back and assert it says what it was meant to say. A wrong byte in a hook does not raise - it
crashes the game, or, worse here, silently deploys units that were never meant to stand up - so
encoding errors have to be caught statically.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    AI_CURRENT_VICTIM,
    DEPLOY_STYLE_MUST_DEPLOY_OFFSET,
    DEPLOY_STYLE_RECORDED_COMMAND_OFFSETS,
    DEPLOY_STYLE_SET_MY_STATE,
    DEPLOY_STYLE_STATE_DEPLOY,
    DEPLOY_STYLE_STATE_OFFSET,
    DEPLOY_STYLE_STATE_READY_TO_MOVE,
    DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS,
    DEPLOY_STYLE_UPDATE_ESI_BIAS,
    DEPLOY_STYLE_UPDATE_OBJECT_PATH,
    DEPLOY_STYLE_UPDATE_POSITION_PATH,
    DEPLOY_STYLE_UPDATE_RESOLVED,
    WEAPON_TARGET_IN_RANGE,
)
from sage_patch.patches.deploy_before_attack import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    DeployBeforeAttackPatch,
    build_cave,
    update_field,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import deploy_before_attack_image

BASE = 0x00F00000


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_cave(base), base))


def biased(offset: int) -> int:
    """A module field as `update` names it off its biased `esi`."""
    return offset - DEPLOY_STYLE_UPDATE_ESI_BIAS


def calls(insns) -> list[int]:
    return [int(i.op_str, 16) for i in insns if i.mnemonic == "call"]


def jump_targets(insns) -> list[int]:
    return [int(i.op_str, 16) for i in insns if i.mnemonic == "jmp"]


class TestTheFieldBias:
    def test_it_subtracts_the_bias_update_applies_to_esi(self):
        assert update_field(0x594) == struct.pack("<i", 0x584)

    def test_the_module_itself_is_reachable_from_the_biased_register(self):
        """The cave hands `module + 0x10 - 0x10` to three `__thiscall` helpers; a wrong bias would
        call all of them on the middle of the module."""
        assert struct.unpack("<i", update_field(0))[0] == -DEPLOY_STYLE_UPDATE_ESI_BIAS


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_cave(BASE))

    def test_it_ends_in_the_two_arms_the_displaced_branch_chose_between(self):
        """The last thing the cave does, on every declining path, is the test it displaced."""
        insns = disassemble()
        assert jump_targets(insns)[-2:] == [
            DEPLOY_STYLE_UPDATE_OBJECT_PATH,
            DEPLOY_STYLE_UPDATE_POSITION_PATH,
        ]

    def test_the_displaced_test_is_reproduced_verbatim(self):
        """A recorded attack position falls through to its own arm; anything else goes on to try
        the recorded attack object. Getting the sense of that branch backwards would read a
        position out of a module that recorded a target."""
        insns = disassemble()
        position_flag = biased(DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS[1])
        repeats = [
            i
            for i in insns
            if i.mnemonic == "cmp" and i.op_str == f"byte ptr [esi + {position_flag:#x}], 0"
        ]
        assert len(repeats) == 2, "the flag is read once as a guard and once as the displaced test"
        after = [i for i in insns if i.address > repeats[-1].address]
        assert after[0].mnemonic == "jne"
        assert (after[1].mnemonic, int(after[1].op_str, 16)) == (
            "jmp",
            DEPLOY_STYLE_UPDATE_OBJECT_PATH,
        )
        taken = next(i for i in after if i.address == int(after[0].op_str, 16))
        assert (taken.mnemonic, int(taken.op_str, 16)) == ("jmp", DEPLOY_STYLE_UPDATE_POSITION_PATH)

    def test_every_added_test_falls_out_to_the_stock_tail(self):
        """Each new condition may only *decline* to deploy, and they all decline to the same
        place: the reproduced stock test. A condition that jumped anywhere else would skip part
        of the work `update` still has to do."""
        insns = disassemble()
        position_flag = biased(DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS[1])
        stock = [
            i
            for i in insns
            if i.mnemonic == "cmp" and i.op_str == f"byte ptr [esi + {position_flag:#x}], 0"
        ][-1].address
        conditional = [i for i in insns if i.mnemonic.startswith("j") and i.mnemonic != "jmp"]
        assert len(conditional) > 5
        assert [int(i.op_str, 16) for i in conditional[:-1]] == [stock] * (len(conditional) - 1)
        assert all(i.address < stock for i in conditional[:-1])

    def test_it_checks_the_targeted_command_flags(self):
        """A targeted order names something the stock arm resolves and deploys for by itself, so
        the cave keeps out of its way."""
        insns = disassemble()
        guards = [i for i in insns if i.mnemonic == "cmp" and i.op_str.startswith("byte ptr [esi")]
        offsets = [int(i.op_str.split("+ ")[1].split("]")[0], 16) for i in guards]
        assert offsets[: len(DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS)] == [
            biased(o) for o in DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS
        ]

    def test_it_does_not_check_the_untargeted_command_flag(self):
        """`+0x594` - guard, attack-move, hunt - names nothing, and its arm resolves a target only
        through the mood picker and the tracked id, both of which come back empty for a unit
        attacking out of its guard machine. Refusing to act on it is the bug this flag was."""
        untargeted = next(
            o
            for o in DEPLOY_STYLE_RECORDED_COMMAND_OFFSETS
            if o not in DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS
        )
        insns = disassemble()
        assert not [i for i in insns if i.op_str == f"byte ptr [esi + {biased(untargeted):#x}], 0"]

    def test_it_only_deploys_a_packed_module(self):
        """`READY_TO_MOVE` is the only state where standing up means anything; running on a module
        that is already deploying would restart its timer every frame."""
        insns = disassemble()
        state = next(
            i for i in insns if i.mnemonic == "cmp" and i.op_str.startswith("dword ptr [esi")
        )
        packed = DEPLOY_STYLE_STATE_READY_TO_MOVE
        assert state.op_str == f"dword ptr [esi + {biased(DEPLOY_STYLE_STATE_OFFSET):#x}], {packed}"

    def test_it_reads_must_deploy_to_attack_off_the_module_data(self):
        """The `ModuleData` is at `module+4`, which is `esi-0xc` here; reading the byte off `esi`
        itself would test a field of the module instead of the keyword."""
        insns = disassemble()
        load = next(i for i in insns if i.mnemonic == "mov" and i.op_str.startswith("eax,"))
        assert load.op_str == "eax, dword ptr [esi - 0xc]"
        test = next(i for i in insns if i.address > load.address and i.mnemonic == "cmp")
        assert test.op_str == f"byte ptr [eax + {DEPLOY_STYLE_MUST_DEPLOY_OFFSET:#x}], 0"

    def test_it_asks_the_engine_what_the_unit_is_attacking(self):
        """The whole point: the module cannot see an acquire that never became an `AICommandParms`,
        and it cannot see one that never allocated an attack machine either. `getCurrentVictim` is
        the field every attack path writes."""
        insns = disassemble()
        assert calls(insns)[0] == AI_CURRENT_VICTIM

    def test_it_refuses_a_unit_with_no_victim(self):
        """`getCurrentVictim` answers NULL when the AI is not attacking - an idle guard, or a unit
        moving with nothing acquired."""
        insns = disassemble()
        call = next(
            i for i in insns if i.mnemonic == "call" and int(i.op_str, 16) == AI_CURRENT_VICTIM
        )
        after = [i for i in insns if i.address > call.address]
        assert (after[0].mnemonic, after[0].op_str) == ("test", "eax, eax")
        assert after[1].mnemonic == "je"

    def test_it_deploys_only_for_a_target_in_range(self):
        """Without this the unit stands up for anything it acquires across the map and then walks
        to it deployed."""
        insns = disassemble()
        assert calls(insns)[1] == WEAPON_TARGET_IN_RANGE
        weapon = next(i for i in insns if i.op_str == "ecx, ebx")
        assert weapon.address < next(
            i.address
            for i in insns
            if i.mnemonic == "call" and int(i.op_str, 16) == WEAPON_TARGET_IN_RANGE
        )

    def test_the_range_call_is_balanced(self):
        """`Weapon::isTargetObjectInRange` is `ret 0x10`: four dwords in, all cleaned by the
        callee. One push too few and the cave returns on a corrupted stack."""
        insns = disassemble()
        call = next(
            i for i in insns if i.mnemonic == "call" and int(i.op_str, 16) == WEAPON_TARGET_IN_RANGE
        )
        pushed = [i for i in insns if i.mnemonic == "push" and i.address < call.address]
        assert len(pushed) == 4
        assert any(i.mnemonic == "fstp" and i.op_str == "dword ptr [esp]" for i in insns)

    def test_it_deploys_by_calling_set_my_state(self):
        insns = disassemble()
        assert calls(insns)[-1] == DEPLOY_STYLE_SET_MY_STATE
        push = [
            i for i in insns if i.mnemonic == "push" and i.op_str == str(DEPLOY_STYLE_STATE_DEPLOY)
        ]
        assert push, "the DEPLOY state is never pushed"

    def test_it_rejoins_update_with_nothing_resolved(self):
        """The deploying path must not fall into the resolution it skipped: `[esp+0x11]` and
        `[esp+0x12]` are still zero, which is exactly what the rejoin point expects."""
        insns = disassemble()
        assert jump_targets(insns)[0] == DEPLOY_STYLE_UPDATE_RESOLVED

    def test_it_writes_nothing_to_the_module(self):
        """The cave is stateless on purpose - a flag it set would outlive the target that made it
        true, and nothing would ever clear it."""
        insns = disassemble()
        stores = [
            i for i in insns if i.mnemonic == "mov" and i.op_str.startswith(("byte", "dword"))
        ]
        assert stores == []


class TestApply:
    def test_it_applies_and_verifies(self):
        data = deploy_before_attack_image()
        DeployBeforeAttackPatch().apply(data)
        assert DeployBeforeAttackPatch().verify(data) == []

    def test_the_hook_is_a_jump_to_the_cave_and_the_rest_is_nops(self):
        data = deploy_before_attack_image()
        DeployBeforeAttackPatch().apply(data)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, section_off, _ = located
        off = va_to_offset(data, HOOK_VA)
        assert off is not None
        assert data[off] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0] == section_va
        assert bytes(data[off + 5 : off + len(HOOK_ORIGINAL)]) == b"\x90" * (len(HOOK_ORIGINAL) - 5)
        assert bytes(data[section_off : section_off + len(build_cave(section_va))]) == build_cave(
            section_va
        )

    def test_a_stock_image_does_not_verify(self):
        assert DeployBeforeAttackPatch().verify(deploy_before_attack_image()) != []

    def test_it_is_detected_once_applied(self):
        data = deploy_before_attack_image()
        DeployBeforeAttackPatch().apply(data)
        assert DeployBeforeAttackPatch.detect(data) is not None

    def test_it_is_not_detected_in_a_stock_image(self):
        assert DeployBeforeAttackPatch.detect(deploy_before_attack_image()) is None

    def test_applying_twice_raises(self):
        data = deploy_before_attack_image()
        DeployBeforeAttackPatch().apply(data)
        with pytest.raises(ValueError):
            DeployBeforeAttackPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_the_build(self, va: int):
        data = deploy_before_attack_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not this build's|not the expected build"):
            DeployBeforeAttackPatch().apply(data)

    def test_a_moved_hook_refuses_the_build(self):
        data = deploy_before_attack_image()
        off = va_to_offset(data, HOOK_VA)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            DeployBeforeAttackPatch().apply(data)

    def test_it_is_registered(self):
        assert PATCHES[DeployBeforeAttackPatch.name] is DeployBeforeAttackPatch
        assert not DeployBeforeAttackPatch.experimental
