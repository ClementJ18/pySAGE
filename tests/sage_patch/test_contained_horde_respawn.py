"""Tests for the contained-horde-respawn patch.

The cave is a transcription, so what needs proving is that it is a *faithful* one. Every claim
below is checked against instructions decoded out of the stock bytes rather than against numbers
written down here: the gates it applies to a passenger, the three horde-interface slots it calls,
the two engine routines, the module-data field it reads the effect list from, and the frame the
delay gate compares against all come from disassembling the radius arm's own respawn block and the
`AffectsContained` arm's own `iterateContained` call.

The other thing a reader cannot check by eye is the callback's stack. A conditional that leaves
with an argument still pushed corrupts the iterator's frame and the bytes look fine, so
:class:`TestTheCallbackBalancesItsStack` walks every exit and asserts the depth.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    AUTO_HEAL_ANCHORS,
    AUTO_HEAL_CONTAINED_EXIT,
    AUTO_HEAL_CONTAINED_EXIT_BYTES,
    AUTO_HEAL_CONTAINED_ITERATE,
    AUTO_HEAL_LAST_RESPAWN_FRAME,
    AUTO_HEAL_MODULE_BASE_SLOT,
    AUTO_HEAL_RESPAWN_BLOCK,
    AUTO_HEAL_RESPAWN_FX_LIST,
    AUTO_HEAL_RESPAWN_MEMBER_FIXUP,
    AUTO_HEAL_RESPAWN_MINIMUM_DELAY,
    AUTO_HEAL_RESPAWN_NEARBY_HORDE_MEMBERS,
    AUTO_HEAL_UPDATE,
    AUTO_HEAL_UPDATE_TAIL,
    AUTO_HEAL_UPDATE_VTABLE,
    CONTAIN_ITERATE_SLOT,
    FX_LIST_PLAY_AT_OBJECT,
    HORDE_IFACE_MAX_MEMBERS_SLOT,
    HORDE_IFACE_MEMBER_COUNT_SLOT,
    HORDE_IFACE_RESPAWN_MEMBER_SLOT,
    OBJECT_GET_HORDE_IFACE,
    OBJECT_TEST_STATUS,
)
from sage_patch.patches.contained_horde_respawn import (
    SECTION_NAME,
    ContainedHordeRespawnPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import allocate_section, find_section, va_to_offset

from .synthetic import contained_horde_respawn_image

#: Where the cave lands in the tests that disassemble it. `apply` allocates the real one past the
#: last section, and `verify` finds it by name.
CAVE_BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def cave() -> list:
    """The whole cave, decoded at :data:`CAVE_BASE`."""
    return disassemble(build_code(CAVE_BASE), CAVE_BASE)


def callback() -> list:
    """Just the callback: everything between the leading `jmp` and the address it jumps to."""
    code = cave()
    entry = int(code[0].op_str, 16)
    return [i for i in code[1:] if i.address < entry]


def entry() -> list:
    """Just the hook body."""
    code = cave()
    start = int(code[0].op_str, 16)
    return [i for i in code if i.address >= start]


def stock_respawn() -> list:
    """The radius arm's respawn block, decoded out of its anchor."""
    return disassemble(AUTO_HEAL_ANCHORS[AUTO_HEAL_RESPAWN_BLOCK], AUTO_HEAL_RESPAWN_BLOCK)


def operands(instructions, mnemonic: str) -> list[str]:
    return [i.op_str for i in instructions if i.mnemonic == mnemonic]


def applied() -> bytearray:
    data = contained_horde_respawn_image()
    ContainedHordeRespawnPatch().apply(data)
    return data


class TestTheSiteItRewrites:
    def test_the_stock_bytes_are_the_arms_exit(self):
        """Decoded rather than asserted as hex: the five bytes really are the jump to the shared
        tail, so replacing them adds a step to this arm and to no other."""
        insn = disassemble(AUTO_HEAL_CONTAINED_EXIT_BYTES, AUTO_HEAL_CONTAINED_EXIT)[0]
        assert (insn.mnemonic, int(insn.op_str, 16)) == ("jmp", AUTO_HEAL_UPDATE_TAIL)

    def test_the_list_destructor_abuts_it(self):
        """The site is the end of the `AffectsContained` arm and not some other five bytes: the
        arm's own list destructor ends exactly where the rewritten instruction begins."""
        va = 0x00855AB9
        code = AUTO_HEAL_ANCHORS[va]
        assert va + len(code) == AUTO_HEAL_CONTAINED_EXIT
        lea, call = disassemble(code, va)
        assert (lea.mnemonic, lea.op_str) == ("lea", "ecx, [ebp - 0x18]")
        assert call.mnemonic == "call"

    def test_the_arm_is_gated_on_affects_contained(self):
        """`cmp byte [ebx+0x14d], 0` and a `je` past the whole arm - the only read of
        `AffectsContained` in the image, and what makes the new code unreachable for a module that
        does not set it."""
        gate, branch = disassemble(AUTO_HEAL_ANCHORS[0x00855A25], 0x00855A25)
        assert (gate.mnemonic, gate.op_str) == ("cmp", "byte ptr [ebx + 0x14d], 0")
        assert branch.mnemonic == "je"
        assert int(branch.op_str, 16) > AUTO_HEAL_CONTAINED_EXIT

    def test_the_vtable_slot_and_the_name_say_which_module(self):
        slot = AUTO_HEAL_ANCHORS[AUTO_HEAL_UPDATE_VTABLE]
        assert struct.unpack("<I", slot)[0] == AUTO_HEAL_UPDATE
        assert AUTO_HEAL_ANCHORS[0x00C0BED4] == b"AutoHealBehavior\x00"


class TestTheEntryReproducesTheRadiusArmsGate:
    def test_it_reads_the_respawn_flag(self):
        """The same `ModuleData` byte the radius arm tests, so the two arms are switched by one
        keyword rather than by two that could drift apart."""
        stock = next(i for i in stock_respawn() if i.mnemonic == "cmp" and "0x175" in i.op_str)
        mine = next(i for i in entry() if i.mnemonic == "cmp" and "0x175" in i.op_str)
        assert mine.op_str == stock.op_str
        assert f"0x{AUTO_HEAL_RESPAWN_NEARBY_HORDE_MEMBERS:x}" in mine.op_str

    def test_it_compares_the_same_two_numbers_the_radius_arm_does(self):
        """`RespawnMinimumDelay` plus the module's own timestamp, against `TheGameLogic`'s frame.

        The radius arm reaches the timestamp as `+0x24` off the `UpdateModule` sub-object; the
        cave reaches the same dword as `+0x34` off the module base, because the frame slot holding
        the sub-object has been reused as a list head by the time it runs.
        """
        stock = disassemble(AUTO_HEAL_ANCHORS[0x00855B04], 0x00855B04)
        assert operands(stock, "add") == ["ecx, dword ptr [edx + 0x24]"]
        assert f"[ebx + 0x{AUTO_HEAL_RESPAWN_MINIMUM_DELAY:x}]" in operands(stock, "mov")[0]

        mine = entry()
        assert f"ecx, dword ptr [edx + 0x{AUTO_HEAL_LAST_RESPAWN_FRAME:x}]" in operands(mine, "add")
        base = f"edx, dword ptr [ebp - 0x{AUTO_HEAL_MODULE_BASE_SLOT:x}]"
        assert base in operands(mine, "mov")
        assert f"ecx, dword ptr [ebx + 0x{AUTO_HEAL_RESPAWN_MINIMUM_DELAY:x}]" in operands(
            mine, "mov"
        )

    def test_the_frame_it_reads_is_the_one_the_radius_arm_reads(self):
        """`TheGameLogic` and the frame offset, both taken from the stock gate rather than
        restated."""
        stock = disassemble(AUTO_HEAL_ANCHORS[0x00855B04], 0x00855B04)
        globals_read = [i.op_str for i in stock if i.mnemonic == "mov" and "0xde412c" in i.op_str]
        assert globals_read, "the stock gate should load TheGameLogic"
        mine = [i.op_str for i in entry() if i.mnemonic == "mov" and "0xde412c" in i.op_str]
        assert mine == globals_read
        assert "eax, dword ptr [eax + 0x40]" in operands(entry(), "mov")

    def test_it_stamps_the_field_the_radius_arm_stamps(self):
        write_back = disassemble(AUTO_HEAL_ANCHORS[0x00855DAD], 0x00855DAD)
        assert "dword ptr [ecx + 0x24], eax" in operands(write_back, "mov")
        assert f"dword ptr [edx + 0x{AUTO_HEAL_LAST_RESPAWN_FRAME:x}], eax" in operands(
            entry(), "mov"
        )

    def test_it_clears_the_scope_index_the_arm_left_set(self):
        """The arm sets the index when it builds its list and never resets it, so the cave does -
        otherwise an unwind out of the calls below would destroy that list a second time."""
        assert "dword ptr [ebp - 4], 0xffffffff" in operands(entry(), "or")
        arm = disassemble(
            AUTO_HEAL_ANCHORS[AUTO_HEAL_CONTAINED_ITERATE], AUTO_HEAL_CONTAINED_ITERATE
        )
        assert "dword ptr [ebp - 4], eax" in operands(arm, "mov")

    def test_every_path_leaves_through_the_shared_tail(self):
        jumps = [i for i in entry() if i.mnemonic == "jmp"]
        assert [int(i.op_str, 16) for i in jumps] == [AUTO_HEAL_UPDATE_TAIL]


class TestItIteratesTheWayTheArmAlreadyDoes:
    def test_it_calls_the_slot_the_arm_calls(self):
        """Not "a" contained-items walk: the same vtable slot, on the same interface, that the arm
        used three instructions earlier - which is what makes it right for whatever concrete
        contain the object happens to carry."""
        arm = disassemble(
            AUTO_HEAL_ANCHORS[AUTO_HEAL_CONTAINED_ITERATE], AUTO_HEAL_CONTAINED_ITERATE
        )
        stock_call = next(i for i in arm if i.mnemonic == "call")
        assert stock_call.op_str == f"dword ptr [edx + 0x{CONTAIN_ITERATE_SLOT:x}]"
        mine = next(i for i in entry() if i.mnemonic == "call")
        assert mine.op_str == f"dword ptr [eax + 0x{CONTAIN_ITERATE_SLOT:x}]"

    def test_it_pushes_the_same_three_arguments_in_the_same_order(self):
        """`func`, `userData`, `1` - read off the arm's own call site rather than assumed."""
        arm = disassemble(
            AUTO_HEAL_ANCHORS[AUTO_HEAL_CONTAINED_ITERATE], AUTO_HEAL_CONTAINED_ITERATE
        )
        assert operands(arm, "push")[-3:] == ["eax", "eax", "0x85584b"]

        pushes = operands(entry(), "push")[-3:]
        assert pushes[0] == "1"
        assert pushes[1] == "ebx", "the ModuleData travels as userData, not in a live register"
        assert int(pushes[2], 16) == callback()[0].address

    def test_the_callback_ends_in_a_plain_ret(self):
        """The iterator cleans the two arguments, exactly as the engine's own callback at
        `0x0085584B` assumes."""
        assert callback()[-1].mnemonic == "ret"
        assert callback()[-1].op_str == ""

    def test_the_callback_reads_its_arguments_past_its_own_pushes(self):
        saved = [i for i in callback()[:3] if i.mnemonic == "push"]
        assert [i.op_str for i in saved] == ["ebx", "esi", "edi"]
        loads = operands(callback(), "mov")[:2]
        assert loads[0] == "esi, dword ptr [esp + 0x10]"
        assert loads[1] == "ebx, dword ptr [esp + 0x14]"


class TestTheCallbackIsTheStockRespawn:
    def test_it_applies_the_same_kindof_test(self):
        stock = next(i for i in stock_respawn() if i.mnemonic == "test" and "0x115" in i.op_str)
        mine = next(i for i in callback() if i.mnemonic == "test" and "0x115" in i.op_str)
        assert mine.op_str == stock.op_str

    def test_it_applies_the_same_status_test(self):
        stock_pushes = operands(stock_respawn(), "push")
        assert "2" in stock_pushes, "the stock block pushes the status index"
        calls = [i for i in callback() if i.mnemonic == "call" and i.op_str.startswith("0x")]
        assert int(calls[0].op_str, 16) == OBJECT_TEST_STATUS
        body = callback()
        before = [i for i in body if i.address < calls[0].address]
        assert operands(before, "push")[-1] == "2"

    def test_it_fetches_the_horde_interface_the_same_way(self):
        stock_calls = [
            int(i.op_str, 16)
            for i in stock_respawn()
            if i.mnemonic == "call" and i.op_str.startswith("0x")
        ]
        mine_calls = [
            int(i.op_str, 16)
            for i in callback()
            if i.mnemonic == "call" and i.op_str.startswith("0x")
        ]
        assert stock_calls == mine_calls
        assert mine_calls == [
            OBJECT_TEST_STATUS,
            OBJECT_GET_HORDE_IFACE,
            AUTO_HEAL_RESPAWN_MEMBER_FIXUP,
            FX_LIST_PLAY_AT_OBJECT,
        ]

    def test_it_calls_the_same_three_interface_slots_in_the_same_order(self):
        def slots(instructions):
            return [
                int(i.op_str.split("+")[1].strip(" ]"), 16)
                for i in instructions
                if i.mnemonic == "call" and "dword ptr [" in i.op_str
            ]

        expected = [
            HORDE_IFACE_MAX_MEMBERS_SLOT,
            HORDE_IFACE_MEMBER_COUNT_SLOT,
            HORDE_IFACE_RESPAWN_MEMBER_SLOT,
        ]
        assert slots(stock_respawn()) == expected
        assert slots(callback()) == expected

    def test_it_skips_a_horde_at_its_ceiling(self):
        """The live count in `eax` against `Slots`, and `jae` out - the stock comparison, in the
        stock direction. Reversing it would replenish a full battalion forever."""
        assert any(i.mnemonic == "jae" for i in stock_respawn())
        assert any(i.mnemonic == "jae" for i in callback())
        mine = callback()
        jae = next(i for i in mine if i.mnemonic == "jae")
        before = mine[: mine.index(jae)]
        assert before[-1].mnemonic == "cmp" and before[-1].op_str == "eax, ecx"

    def test_it_passes_the_transform_not_the_position(self):
        """`add esi, 8` - `Object`'s `Matrix3D`, which is what the spawn slot takes. The `Coord3D`
        at `+0x38` would assemble just as well and put the member somewhere else."""
        assert "esi, 8" in operands(stock_respawn(), "add")
        assert "esi, 8" in operands(callback(), "add")

    def test_it_plays_the_effect_list_from_the_same_field(self):
        stock = next(i for i in stock_respawn() if i.mnemonic == "mov" and "0x178" in i.op_str)
        mine = next(i for i in callback() if i.mnemonic == "mov" and "0x178" in i.op_str)
        assert mine.op_str == stock.op_str
        assert f"0x{AUTO_HEAL_RESPAWN_FX_LIST:x}" in mine.op_str

    def test_the_effect_list_is_optional(self):
        """A NULL `RespawnFXList` is tested before the call, as the stock block tests it, so a mod
        that leaves the line out does not hand the wrapper a null it would have tolerated anyway."""
        mine = callback()
        fx_load = next(i for i in mine if i.mnemonic == "mov" and "0x178" in i.op_str)
        after = mine[mine.index(fx_load) + 1 :]
        assert after[0].mnemonic == "test" and after[0].op_str == "eax, eax"
        assert after[1].mnemonic == "je"


class TestTheCallbackBalancesItsStack:
    """Every exit leaves the stack where the three pops expect it.

    The failure this rules out is silent: a conditional taken with an argument still pushed
    corrupts the iterator's frame, and nothing about the bytes looks wrong.
    """

    #: How many dwords each call takes off the stack itself. The two `ret 4` routines are the
    #: engine's `Object::testStatus` and the horde interface's respawn slot; the rest take no
    #: arguments, and the `FXList` wrapper is `__cdecl` and is balanced by an explicit `add esp`.
    CALLEE_CLEANS = {
        OBJECT_TEST_STATUS: 1,
        OBJECT_GET_HORDE_IFACE: 0,
        AUTO_HEAL_RESPAWN_MEMBER_FIXUP: 0,
        FX_LIST_PLAY_AT_OBJECT: 0,
        HORDE_IFACE_MAX_MEMBERS_SLOT: 0,
        HORDE_IFACE_MEMBER_COUNT_SLOT: 0,
        HORDE_IFACE_RESPAWN_MEMBER_SLOT: 1,
    }

    def test_every_branch_out_leaves_at_the_same_depth(self):
        body = callback()
        done = body[-4].address  # the three pops and the ret
        prologue = body[:3]
        assert [i.mnemonic for i in prologue] == ["push"] * 3
        depth = 0  # counted past the three saved registers, which the epilogue pops
        seen_exits = 0
        for insn in body[3:]:
            if insn.address == done:
                assert depth == 0, f"fell into the epilogue {depth} dwords deep"
                break
            if insn.mnemonic.startswith("j") and int(insn.op_str, 16) == done:
                assert depth == 0, f"branch at 0x{insn.address:08x} leaves {depth} dwords pushed"
                seen_exits += 1
            elif insn.mnemonic == "push":
                depth += 1
            elif insn.mnemonic == "pop":
                depth -= 1
            elif insn.mnemonic == "add" and insn.op_str.startswith("esp,"):
                depth -= int(insn.op_str.split(",")[1], 16) // 4
            elif insn.mnemonic == "call":
                if insn.op_str.startswith("0x"):
                    key = int(insn.op_str, 16)
                else:
                    key = int(insn.op_str.split("+")[1].strip(" ]"), 16)
                depth -= self.CALLEE_CLEANS[key]
        assert seen_exits == 6, "one guard per gate, plus the two NULL checks"


class TestApplyingIt:
    def test_the_hook_points_at_the_cave(self):
        data = applied()
        section_va, _, _ = find_section(data, SECTION_NAME)
        off = va_to_offset(data, AUTO_HEAL_CONTAINED_EXIT)
        insn = disassemble(bytes(data[off : off + 5]), AUTO_HEAL_CONTAINED_EXIT)[0]
        assert (insn.mnemonic, int(insn.op_str, 16)) == ("jmp", section_va)

    def test_the_cave_holds_what_build_code_says(self):
        data = applied()
        section_va, section_off, size = find_section(data, SECTION_NAME)
        assert bytes(data[section_off : section_off + size]) == build_code(section_va)

    def test_verify_passes_on_the_patched_image(self):
        assert ContainedHordeRespawnPatch().verify(applied()) == []

    def test_verify_says_unpatched_rather_than_wrong(self):
        problems = ContainedHordeRespawnPatch().verify(contained_horde_respawn_image())
        assert problems and "absent" in problems[0]

    def test_detect_recognises_it(self):
        assert ContainedHordeRespawnPatch.detect(applied()) is not None
        assert ContainedHordeRespawnPatch.detect(contained_horde_respawn_image()) is None

    def test_it_refuses_a_build_whose_anchors_disagree(self):
        data = contained_horde_respawn_image()
        off = va_to_offset(data, AUTO_HEAL_RESPAWN_BLOCK)
        data[off] = (data[off] + 1) & 0xFF
        with pytest.raises(ValueError, match="unexpected build"):
            ContainedHordeRespawnPatch().apply(data)

    def test_it_refuses_a_site_that_is_not_the_arms_exit(self):
        data = contained_horde_respawn_image()
        off = va_to_offset(data, AUTO_HEAL_CONTAINED_EXIT)
        data[off] = 0x90
        with pytest.raises(ValueError, match="expected e907030000"):
            ContainedHordeRespawnPatch().apply(data)

    def test_applying_it_twice_fails_loudly(self):
        data = applied()
        with pytest.raises(ValueError):
            ContainedHordeRespawnPatch().apply(data)


class TestItComposes:
    """Order-independence against another cave-adding patch, stood in for by a bare section.

    Using a real second patch would tie this file to that patch's own anchors, which say nothing
    about this one. What matters is only that the cave is allocated past whatever is already there
    and that `verify` finds it by name rather than by the RVA it happened to get.
    """

    @staticmethod
    def _other_cave(data: bytearray) -> int:
        return allocate_section(data, ".other", lambda _base: bytes([0xC3]) * 0x40, 0x60000020)

    def test_a_cave_added_first_does_not_disturb_it(self):
        data = contained_horde_respawn_image()
        other = self._other_cave(data)
        ContainedHordeRespawnPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        assert section_va > other
        assert ContainedHordeRespawnPatch().verify(data) == []

    def test_a_cave_added_after_does_not_disturb_it(self):
        data = contained_horde_respawn_image()
        ContainedHordeRespawnPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        assert self._other_cave(data) > section_va
        assert ContainedHordeRespawnPatch().verify(data) == []

    def test_the_hook_follows_the_cave_wherever_it_lands(self):
        """The two orders put the cave at different addresses, and the hook has to name the one it
        actually got - which is what a hardcoded RVA would get wrong."""
        addresses = set()
        for add_other_first in (True, False):
            data = contained_horde_respawn_image()
            if add_other_first:
                self._other_cave(data)
            ContainedHordeRespawnPatch().apply(data)
            section_va, _, _ = find_section(data, SECTION_NAME)
            off = va_to_offset(data, AUTO_HEAL_CONTAINED_EXIT)
            insn = disassemble(bytes(data[off : off + 5]), AUTO_HEAL_CONTAINED_EXIT)[0]
            assert int(insn.op_str, 16) == section_va
            addresses.add(section_va)
        assert len(addresses) == 2, "the stand-in should move the cave"


class TestItIsRegistered:
    def test_the_cli_can_reach_it(self):
        assert PATCHES["contained-horde-respawn"] is ContainedHordeRespawnPatch

    def test_it_is_not_experimental(self):
        assert ContainedHordeRespawnPatch.experimental is False

    def test_it_changes_no_ini_surface(self):
        """`RespawnNearbyHordeMembers` and `AffectsContained` are stock keywords on a stock block -
        the patch only changes what writing both of them does."""
        assert ContainedHordeRespawnPatch().ini_surface() is STOCK

    def test_it_takes_no_parameters(self):
        assert ContainedHordeRespawnPatch().options() == {}


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestAgainstTheRealBinary:
    @pytest.fixture(scope="class")
    def game(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_anchor_is_where_it_says(self, game: bytes):
        for va, expected in AUTO_HEAL_ANCHORS.items():
            off = va_to_offset(game, va)
            assert off is not None, f"0x{va:08x} is not mapped"
            assert bytes(game[off : off + len(expected)]) == expected, f"0x{va:08x}"

    def test_the_site_is_stock(self, game: bytes):
        off = va_to_offset(game, AUTO_HEAL_CONTAINED_EXIT)
        assert bytes(game[off : off + 5]) == AUTO_HEAL_CONTAINED_EXIT_BYTES

    def test_it_applies_and_verifies(self, game: bytes):
        data = bytearray(game)
        patch = ContainedHordeRespawnPatch()
        patch.apply(data)
        assert patch.verify(data) == []
