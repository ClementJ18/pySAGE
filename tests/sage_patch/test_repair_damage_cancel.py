"""Tests for the repair-damage-cancel patch.

Two edits. The gate erase is one two-byte branch, so what could be wrong without raising is
*which* branch: the cancel sequence is read back to check the erased `jb` is the one guarding on
`SpawnTimer`. The worker dismissal is hand-assembled x86 that cannot run here, so the cave is
disassembled and read: it must keep the stock `stopRepair`, act only on a recent hit, touch only a
`WORKER_REPAIRING` worker the structure spawned, dismiss it the way the engine's own worker manager
does, keep `esi` for the epilogue, and return where the stock call would have.
"""

from __future__ import annotations

import pytest

from sage_patch.addresses import (
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GETTING_BUILT_CANCEL_RESUME,
    GETTING_BUILT_CANCEL_STOP,
    GETTING_BUILT_CANCEL_STOP_BYTES,
    GETTING_BUILT_DAMAGE_CANCEL,
    GETTING_BUILT_DAMAGE_CANCEL_BYTES,
    GETTING_BUILT_DAMAGE_CANCEL_GATE,
    GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES,
    GETTING_BUILT_DISMISS_WORKER,
    GETTING_BUILT_RECENT_DAMAGE_PROBE,
    OBJECT_KILL,
    OBJECT_MODEL_CONDITIONS_CHANGED,
    OBJECT_SET_PRODUCER,
    OBJECT_STATUS_WORKER_REPAIRING,
    OBJECT_TEST_STATUS,
)
from sage_patch.patches.repair_damage_cancel import (
    ANCHORS,
    GATE_REPLACEMENT,
    HOOK_WIDTH,
    SECTION_NAME,
    RepairDamageCancelPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, jmp_rel32, va_to_offset
from tests.sage_patch.synthetic import repair_damage_cancel_image

#: `moduleData+0x20`, the `SpawnTimer` real.
SPAWN_TIMER = 0x20
#: The update's shared exit that calls `stopRepair`.
CANCEL = 0x008580AC
#: The first instruction after the cancel: the `isRepairing` test.
PAST_CANCEL = 0x00857F4A
BASE = 0x00F00000


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def cave(base: int = BASE):
    return disassemble(build_code(base), base)


def _calls(insns) -> list[int]:
    return [int(i.op_str, 16) for i in insns if i.mnemonic == "call" and i.op_str.startswith("0x")]


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


@pytest.fixture
def patched() -> bytearray:
    data = repair_damage_cancel_image()
    RepairDamageCancelPatch().apply(data)
    return data


class TestTheCancelSequence:
    def test_the_gate_lies_inside_the_anchored_sequence(self):
        start = GETTING_BUILT_DAMAGE_CANCEL_GATE - GETTING_BUILT_DAMAGE_CANCEL
        end = start + len(GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES)
        assert (
            GETTING_BUILT_DAMAGE_CANCEL_BYTES[start:end] == GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES
        )

    def test_the_erased_branch_skips_the_cancel_when_spawn_timer_is_negative(self):
        insns = disassemble(GETTING_BUILT_DAMAGE_CANCEL_BYTES, GETTING_BUILT_DAMAGE_CANCEL)
        by_va = {i.address: i for i in insns}
        gate = by_va[GETTING_BUILT_DAMAGE_CANCEL_GATE]
        assert (gate.mnemonic, int(gate.op_str, 16)) == ("jb", PAST_CANCEL)
        assert gate.size == len(GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES)
        load, compare = insns[1], insns[2]
        assert load.mnemonic == "movss" and f"[ebx + {SPAWN_TIMER:#x}]" in load.op_str
        assert compare.mnemonic == "comiss"
        assert compare.address + compare.size == GETTING_BUILT_DAMAGE_CANCEL_GATE

    def test_the_tests_left_standing_are_recent_damage_then_still_building(self):
        insns = disassemble(GETTING_BUILT_DAMAGE_CANCEL_BYTES, GETTING_BUILT_DAMAGE_CANCEL)
        rest = [i for i in insns if i.address > GETTING_BUILT_DAMAGE_CANCEL_GATE]
        assert [(i.mnemonic, i.op_str) for i in rest] == [
            ("cmp", "byte ptr [ebp - 1], 0"),
            ("je", hex(PAST_CANCEL)),
            ("cmp", "byte ptr [esi + 0x26], 0"),
            ("je", hex(CANCEL)),
        ]

    def test_the_probe_fills_the_flag_the_cave_reads(self):
        insns = disassemble(
            ANCHORS[GETTING_BUILT_RECENT_DAMAGE_PROBE], GETTING_BUILT_RECENT_DAMAGE_PROBE
        )
        writes = [
            i.op_str
            for i in insns
            if i.mnemonic == "mov" and i.op_str.startswith("byte ptr [ebp - 1]")
        ]
        assert writes == ["byte ptr [ebp - 1], 1", "byte ptr [ebp - 1], 0"]

    def test_the_replacement_is_one_nop(self):
        insns = disassemble(GATE_REPLACEMENT, GETTING_BUILT_DAMAGE_CANCEL_GATE)
        assert len(GATE_REPLACEMENT) == len(GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES)
        assert [(i.mnemonic, i.size) for i in insns] == [("nop", 2)]


class TestTheCave:
    def test_it_opens_with_the_stock_stop_repair(self):
        assert build_code(BASE).startswith(GETTING_BUILT_CANCEL_STOP_BYTES)

    def test_the_hooked_run_is_whole_instructions(self):
        insns = disassemble(GETTING_BUILT_CANCEL_STOP_BYTES, GETTING_BUILT_CANCEL_STOP)
        assert [i.mnemonic for i in insns] == ["mov", "mov", "call"]
        assert sum(i.size for i in insns) == HOOK_WIDTH
        assert GETTING_BUILT_CANCEL_STOP + HOOK_WIDTH == GETTING_BUILT_CANCEL_RESUME

    def test_the_first_test_is_the_recent_hit(self):
        """The hook is also reached every update of an effectively-dead structure, so the hit
        test has to come before anything that could dismiss a worker."""
        insns = cave()
        assert (insns[3].mnemonic, insns[3].op_str) == ("cmp", "byte ptr [ebp - 1], 0")
        assert insns[4].mnemonic == "je"

    def test_it_only_takes_a_worker_this_module_spawned(self):
        ops = [(i.mnemonic, i.op_str) for i in cave()]
        assert ("cmp", "byte ptr [eax + 0x1c], 0") in ops
        assert ("push", "dword ptr [edi + 0x7c]") in ops
        assert ("cmp", "eax, edi") in ops
        assert ("push", hex(OBJECT_STATUS_WORKER_REPAIRING)) in ops

    def test_it_calls_what_the_engines_own_dismissal_calls(self):
        assert _calls(cave()) == [
            GAME_LOGIC_FIND_OBJECT_BY_ID,
            OBJECT_TEST_STATUS,
            OBJECT_MODEL_CONDITIONS_CHANGED,
            OBJECT_KILL,
            OBJECT_SET_PRODUCER,
        ]
        engine = disassemble(ANCHORS[GETTING_BUILT_DISMISS_WORKER], GETTING_BUILT_DISMISS_WORKER)
        assert _calls(engine) == [OBJECT_MODEL_CONDITIONS_CHANGED, OBJECT_KILL, OBJECT_SET_PRODUCER]

    def test_the_kill_is_unresistable_and_faded(self):
        insns = cave()
        kill = next(n for n, i in enumerate(insns) if i.op_str == hex(OBJECT_KILL))
        assert [(i.mnemonic, i.op_str) for i in insns[kill - 3 : kill]] == [
            ("push", "0x16"),
            ("push", "8"),
            ("mov", "ecx, esi"),
        ]

    def test_every_path_that_saved_esi_restores_it(self):
        insns = cave()
        push = next(i for i in insns if (i.mnemonic, i.op_str) == ("push", "esi"))
        pop = next(i for i in insns if (i.mnemonic, i.op_str) == ("pop", "esi"))
        for i in insns:
            if i.mnemonic in ("je", "jne"):
                target = int(i.op_str, 16)
                if i.address < push.address:
                    assert target > pop.address, f"{i.address:#x} lands between push and pop"
                elif i.address < pop.address:
                    assert push.address < target <= pop.address, f"{i.address:#x} skips pop esi"

    def test_its_only_exit_is_the_resume(self):
        insns = cave()
        assert insns[-1].mnemonic == "jmp"
        assert int(insns[-1].op_str, 16) == GETTING_BUILT_CANCEL_RESUME
        assert not any(i.mnemonic == "ret" for i in insns)
        end = BASE + len(build_code(BASE))
        for i in insns:
            if i.mnemonic in ("je", "jne"):
                assert BASE <= int(i.op_str, 16) < end

    def test_the_stack_is_balanced(self):
        """The only push the cave keeps is `esi`, and its one `pop` restores it: every callee
        cleans its own arguments (`ret 4` / `ret 8`)."""
        insns = cave()
        # findObjectById 1, testStatus 1, kill 2, setProducer 1, esi 1.
        assert sum(i.mnemonic == "push" for i in insns) == 6
        assert sum(i.mnemonic == "pop" for i in insns) == 1

    def test_a_dismissal_rewinds_the_auto_repair_countdown(self):
        """Without this the countdown, already at zero, spawns a new worker the next update and
        the cancel turns into a spawn-and-fade loop - seen in a running game."""
        ops = [(i.mnemonic, i.op_str) for i in cave()]
        rewind = [
            ("mov", "eax, dword ptr [ebp - 0x10]"),
            ("mov", "eax, dword ptr [eax + 0x20]"),
            ("mov", "ecx, dword ptr [ebp - 0x18]"),
            ("mov", "dword ptr [ecx + 8], eax"),
        ]
        at = ops.index(rewind[0])
        assert ops[at : at + 4] == rewind
        assert ops[at - 1][0] == "call"  # straight after setProducer, on the dismissal path only
        assert ops[at + 4] == ("pop", "esi")

    def test_it_disassembles_cleanly_to_its_end(self):
        code = build_code(BASE)
        assert sum(i.size for i in cave()) == len(code)


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert RepairDamageCancelPatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert RepairDamageCancelPatch().verify(repair_damage_cancel_image())

    def test_it_erases_the_gate(self, patched: bytearray):
        assert _read(patched, GETTING_BUILT_DAMAGE_CANCEL_GATE, 2) == GATE_REPLACEMENT

    def test_the_cancel_jumps_to_the_cave(self, patched: bytearray):
        located = find_section(patched, SECTION_NAME)
        assert located is not None
        cave_va, cave_off, _ = located
        want = jmp_rel32(GETTING_BUILT_CANCEL_STOP, cave_va, HOOK_WIDTH)
        assert _read(patched, GETTING_BUILT_CANCEL_STOP, HOOK_WIDTH) == want
        code = build_code(cave_va)
        assert bytes(patched[cave_off : cave_off + len(code)]) == code

    def test_the_mapped_sites_change_only_at_the_two_edits(self, patched: bytearray):
        stock = repair_damage_cancel_image()
        gate = GETTING_BUILT_DAMAGE_CANCEL_GATE
        hook = GETTING_BUILT_CANCEL_STOP
        edited = {gate, gate + 1, *range(hook, hook + HOOK_WIDTH)}
        for va, blob in ANCHORS.items():
            for n in range(len(blob)):
                if va + n not in edited:
                    assert _read(patched, va + n, 1) == _read(stock, va + n, 1)

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            RepairDamageCancelPatch().apply(patched)

    @pytest.mark.parametrize("va", [*sorted(ANCHORS), GETTING_BUILT_CANCEL_STOP])
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = repair_damage_cancel_image()
        off = va_to_offset(data, va)
        data[off] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            RepairDamageCancelPatch().apply(data)
        assert bytes(data) == before


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[RepairDamageCancelPatch.name] is RepairDamageCancelPatch

    def test_detect_finds_it_only_once_applied(self, patched: bytearray):
        assert RepairDamageCancelPatch.detect(repair_damage_cancel_image()) is None
        assert isinstance(RepairDamageCancelPatch.detect(patched), RepairDamageCancelPatch)
