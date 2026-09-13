"""Tests for the summon-carryover patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble it
back and assert it says what it was meant to say. A wrong byte does not raise: it either keeps the
stock behaviour (nothing carries) or, worse, files a summon into somebody else's army, which is a
save-visible corruption of the living world. Both have to be caught statically.

The owner comparison is the one worth being paranoid about. Dropping it would adopt the first army
id in the object list regardless of who owns the object, so every player's summons would go home
with whoever happens to be nearest the list head.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    LIVING_WORLD_BATTLE_HARVEST,
    LIVING_WORLD_HARVEST_ARMY_ID_TEST,
    LIVING_WORLD_HARVEST_ARMY_ID_TEST_BYTES,
    OBJECT_ARMY_ID,
    OBJECT_GET_CONTROLLING_PLAYER,
    THE_GAME_LOGIC,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.experimental.ranged_stand_off import RangedStandOffPatch
from sage_patch.patches.summon_carryover import (
    ANCHORS,
    GAME_LOGIC_OBJECT_LIST_HEAD,
    HOOK_BYTES,
    OBJECT_LIST_NEXT,
    SECTION,
    SummonCarryoverPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import ranged_stand_off_image, summon_carryover_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


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

    def test_it_opens_by_reading_the_objects_own_army_id(self):
        """The cave replaces that load, so it has to perform it - `edi` is the harvest's cursor."""
        first = disassemble()[0]
        assert (first.mnemonic, first.op_str) == (
            "mov",
            f"eax, dword ptr [edi + {OBJECT_ARMY_ID:#x}]",
        )
        assert build_code(BASE).startswith(HOOK_BYTES)

    def test_an_object_that_already_has_an_army_returns_it_untouched(self):
        """The common path must be the stock behaviour exactly: `test`/`jne` straight to `ret`,
        with nothing pushed. Every deployed and recruited unit takes this edge."""
        insns = disassemble()
        test = insns[1]
        assert (test.mnemonic, test.op_str) == ("test", "eax, eax")
        taken = insns[2]
        assert taken.mnemonic == "jne"
        landing = next(i for i in insns if i.address == int(taken.op_str, 16))
        assert landing.mnemonic == "ret"

    def test_it_ends_in_a_ret_rather_than_a_jump_back(self):
        """The hook is a `call`, so the cave returns; a `jmp` back would unbalance the stack."""
        assert build_code(BASE).endswith(b"\xc3")
        assert not [i for i in disassemble() if i.mnemonic == "jmp" and "0x" not in i.op_str]

    def test_the_fallback_reads_the_object_list_head_off_the_game_logic(self):
        insns = disassemble()
        load = next(
            i for i in insns if i.mnemonic == "mov" and i.op_str.endswith(f"[{THE_GAME_LOGIC:#x}]")
        )
        head = next(i for i in insns if i.address > load.address and i.mnemonic == "mov")
        assert head.op_str == f"esi, dword ptr [eax + {GAME_LOGIC_OBJECT_LIST_HEAD:#x}]"

    def test_it_walks_the_list_by_the_next_link(self):
        insns = disassemble()
        step = next(
            i
            for i in insns
            if i.mnemonic == "mov" and i.op_str == f"esi, dword ptr [esi + {OBJECT_LIST_NEXT:#x}]"
        )
        after = next(i for i in insns if i.address == step.address + step.size)
        assert after.mnemonic == "jmp", "the step must loop back, not fall through"
        assert int(after.op_str, 16) < step.address, "the loop must branch backwards"

    def test_it_compares_the_owning_player_before_adopting(self):
        """Without this the cave files a summon into whichever army is nearest the list head."""
        insns = disassemble()
        calls = [i for i in insns if i.mnemonic == "call"]
        assert len(calls) == 2, "one call for the object's owner, one per candidate"
        assert {int(c.op_str, 16) for c in calls} == {OBJECT_GET_CONTROLLING_PLAYER}
        cmp_ = next(i for i in insns if i.mnemonic == "cmp" and i.op_str == "eax, edx")
        assert cmp_.address > calls[1].address, "the compare reads the second call's result"
        taken = next(i for i in insns if i.address == cmp_.address + cmp_.size)
        assert taken.mnemonic == "je", "equal owners is the adopting edge"

    def test_the_candidates_owner_lookup_preserves_the_cursor_and_the_player(self):
        """`Object::getControllingPlayer` tail-jumps into `Team::getControllingPlayer`, and
        nothing in the engine proves `esi`/`edx` survive that, so both are pushed across it."""
        insns = disassemble()
        call = [i for i in insns if i.mnemonic == "call"][1]
        before = [i for i in insns if i.address < call.address][-3:]
        after = [i for i in insns if i.address > call.address][:2]
        assert [i.mnemonic for i in before[-2:]] == ["push", "push"]
        assert {i.op_str for i in before[-2:]} == {"edx", "esi"}
        assert [i.mnemonic for i in after] == ["pop", "pop"]
        assert [i.op_str for i in after] == ["esi", "edx"], "pops must mirror the pushes"

    def test_a_candidate_without_an_army_is_skipped_before_the_owner_call(self):
        """The cheap test has to come first: calling getControllingPlayer for every object in the
        list would be a call per object per orphan."""
        insns = disassemble()
        cheap = next(
            i
            for i in insns
            if i.mnemonic == "cmp" and i.op_str.startswith(f"dword ptr [esi + {OBJECT_ARMY_ID:#x}]")
        )
        second_call = [i for i in insns if i.mnemonic == "call"][1]
        assert cheap.address < second_call.address

    def test_every_failure_edge_answers_zero(self):
        """No team, no game logic, end of list: each must produce the stock outcome rather than
        a stale register, or the harvest files the record into a garbage army id."""
        insns = disassemble()
        zero = next(i for i in insns if i.mnemonic == "xor" and i.op_str == "eax, eax")
        targets = {int(i.op_str, 16) for i in insns if i.mnemonic == "je"}
        assert zero.address in targets
        assert (
            len([i for i in insns if i.mnemonic == "je" and int(i.op_str, 16) == zero.address]) == 3
        )

    def test_the_pushes_and_pops_balance_on_every_path(self):
        """A cave that returns with the stack unbalanced corrupts the harvest's frame."""
        insns = disassemble()
        ret = next(i for i in insns if i.mnemonic == "ret")
        slow = [i for i in insns if i.address < ret.address]
        pushes = [i for i in slow if i.mnemonic == "push"]
        pops = [i for i in slow if i.mnemonic == "pop"]
        assert len(pushes) == len(pops) == 5

    def test_it_restores_the_registers_the_harvest_still_needs(self):
        """`ecx`, `edx` and `esi` are the cave's scratch. `edi` and `ebx` are never written: the
        harvest reads both immediately after its own getControllingPlayer call, so they are
        proven callee-saved and must not be disturbed."""
        insns = disassemble()
        written = {i.op_str.split(",")[0].strip() for i in insns if i.mnemonic in {"mov", "xor"}}
        assert "edi" not in written
        assert "ebx" not in written
        assert {i.op_str for i in insns if i.mnemonic == "pop"} == {"ecx", "edx", "esi"}

    def test_every_conditional_branch_stays_inside_the_cave(self):
        """A displacement computed wrong would jump into arbitrary engine code."""
        code = build_code(BASE)
        lo, hi = BASE, BASE + len(code)
        for ins in disassemble():
            if not ins.mnemonic.startswith("j"):
                continue
            assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b, "the two absolute calls must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestTheHook:
    def test_the_window_is_six_bytes_of_call_plus_nop(self):
        """`call rel32` is five; the sixth byte must be a `nop` so no half-instruction is left."""
        assert len(HOOK_BYTES) == 6
        data = summon_carryover_image()
        SummonCarryoverPatch().apply(data)
        cave, _off, _size = find_section(data, SECTION)
        off = va_to_offset(data, LIVING_WORLD_HARVEST_ARMY_ID_TEST)
        site = bytes(data[off : off + 6])
        assert site[0] == 0xE8
        assert LIVING_WORLD_HARVEST_ARMY_ID_TEST + 5 + struct.unpack_from("<i", site, 1)[0] == cave
        assert site[5] == 0x90

    def test_the_hook_bytes_are_the_load_the_cave_reproduces(self):
        assert HOOK_BYTES == LIVING_WORLD_HARVEST_ARMY_ID_TEST_BYTES
        assert HOOK_BYTES == bytes((0x8B, 0x87)) + struct.pack("<I", OBJECT_ARMY_ID)

    def test_it_leaves_the_test_and_branch_that_consume_the_result(self):
        """The stock `test eax, eax` / `je` two and seven bytes on are what turns the cave's
        answer into the filter decision; overwriting either would change the rule."""
        before = summon_carryover_image()
        data = summon_carryover_image()
        SummonCarryoverPatch().apply(data)
        for va in (0x00811EB0, 0x00811EB5, 0x00811F04, 0x00811F0B, 0x00811F13):
            o = va_to_offset(data, va)
            assert data[o : o + 4] == before[o : o + 4], f"{va:#010x} was rewritten"

    def test_it_does_not_touch_the_army_summary_filter(self):
        """The patch keeps ARMY_SUMMARY as the whole opt-in, so filter 2 must survive verbatim."""
        before = summon_carryover_image()
        data = summon_carryover_image()
        SummonCarryoverPatch().apply(data)
        o = va_to_offset(data, 0x00811E96)
        assert data[o : o + 6] == before[o : o + 6]


class TestApply:
    def test_apply_then_verify(self):
        data = summon_carryover_image()
        SummonCarryoverPatch().apply(data)
        assert SummonCarryoverPatch().verify(data) == []

    def test_a_stock_image_verifies_as_unpatched(self):
        assert SummonCarryoverPatch().verify(summon_carryover_image()) != []

    def test_the_cave_holds_exactly_what_build_code_says(self):
        data = summon_carryover_image()
        SummonCarryoverPatch().apply(data)
        cave, off, _size = find_section(data, SECTION)
        assert bytes(data[off : off + len(build_code(cave))]) == build_code(cave)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION) <= 8, "a longer name is silently truncated in the header"
        data = summon_carryover_image()
        SummonCarryoverPatch().apply(data)
        assert find_section(data, SECTION) is not None

    def test_refuses_to_apply_twice(self):
        data = summon_carryover_image()
        SummonCarryoverPatch().apply(data)
        with pytest.raises(ValueError, match="already applied"):
            SummonCarryoverPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = summon_carryover_image()
        off = va_to_offset(data, va)
        data[off : off + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="unexpected build"):
            SummonCarryoverPatch().apply(data)

    def test_it_refuses_a_binary_that_is_not_this_build(self):
        with pytest.raises(ValueError):
            SummonCarryoverPatch().apply(ranged_stand_off_image())


class TestAgainstTheRealBinary:
    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="game.dat not present")
    def test_the_stock_bytes_are_what_the_binary_holds(self):
        data = bytearray(_GAME_DAT.read_bytes())
        sites = dict(ANCHORS)
        sites[LIVING_WORLD_HARVEST_ARMY_ID_TEST] = HOOK_BYTES
        sites[LIVING_WORLD_BATTLE_HARVEST] = bytes.fromhex("b8cd9fb900")
        for va, expected in sites.items():
            off = va_to_offset(data, va)
            assert bytes(data[off : off + len(expected)]) == expected, f"{va:#010x}"

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="game.dat not present")
    def test_apply_and_verify_round_trip(self):
        data = bytearray(_GAME_DAT.read_bytes())
        SummonCarryoverPatch().apply(data)
        assert SummonCarryoverPatch().verify(data) == []


class TestComposition:
    def test_the_cave_is_found_by_name_rather_than_a_fixed_rva(self):
        """`allocate_section` is what lets any subset of patches apply in any order; `verify`
        has to locate the cave through `find_section` rather than assuming where it landed."""
        data = summon_carryover_image()
        SummonCarryoverPatch().apply(data)
        cave, _off, _size = find_section(data, SECTION)
        off = va_to_offset(data, LIVING_WORLD_HARVEST_ARMY_ID_TEST)
        target = (
            LIVING_WORLD_HARVEST_ARMY_ID_TEST
            + 5
            + struct.unpack_from("<i", bytes(data), off + 1)[0]
        )
        assert target == cave

    def test_the_section_is_not_one_another_patch_uses(self):
        sections = {
            getattr(patch, "SECTION", None)
            for patch in PATCHES.values()
            if patch is not SummonCarryoverPatch
        }
        assert SECTION not in sections


class TestRegistration:
    def test_it_is_registered_under_its_name(self):
        assert PATCHES["summon-carryover"] is SummonCarryoverPatch

    def test_it_is_not_experimental(self):
        assert SummonCarryoverPatch.experimental is False

    def test_apply_patches_drives_it(self, tmp_path):
        src = tmp_path / "game.dat"
        src.write_bytes(bytes(summon_carryover_image()))
        apply_patches(src, [SummonCarryoverPatch()])
        assert SummonCarryoverPatch().verify(bytearray(src.read_bytes())) == []

    def test_it_does_not_collide_with_the_other_patch_under_test(self):
        assert RangedStandOffPatch.name != SummonCarryoverPatch.name
