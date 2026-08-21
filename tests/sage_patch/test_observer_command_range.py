"""Tests for the observer-command-range patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter
disassemble it back and assert it says what it was meant to say. Two failure modes are silent
otherwise: a cave that answers "active" for the wrong command lets an observer issue real orders,
and one that clobbers a register the caller still needs corrupts a click path that works in every
other game the same binary plays.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    COMMAND_BUTTON_COMMAND,
    CONTROL_BAR_CLICK_GATE_CALL,
    CONTROL_BAR_CLICK_GATE_CALL_BYTES,
    CONTROL_BAR_COMMAND_INDEX_TABLE,
    CONTROL_BAR_COMMAND_JUMP_TABLE,
    CONTROL_BAR_POP_RANGE_HANDLER,
    CONTROL_BAR_PUSH_RANGE_HANDLER,
    GUICOMMAND_POP_VISIBLE_COMMAND_RANGE,
    GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE,
    GUICOMMAND_REVIVE,
    PLAYER_LIST_LOCAL_IS_NOT_ACTIVE,
)
from sage_patch.patches.observer_command_range import (
    ANCHORS,
    PAGING_COMMANDS,
    SECTION_NAME,
    ObserverCommandRangePatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import PAGING_SWITCH_SLOTS, observer_command_range_image
from tests.sage_patch.test_patching import _tiny_pe

BASE = 0x00F00000

#: The installed binary. Its click path is byte-identical to the clean 2.01.2614 backup at every
#: site this patch touches, so either answers the "are these addresses real" question.
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def _size_of_headers(data: bytes | bytearray) -> int:
    """`SizeOfHeaders`, past which nothing a cave allocation writes belongs."""
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    return struct.unpack_from("<I", data, e_lfanew + 24 + 60)[0]


def _corrupt(data: bytearray, va: int) -> None:
    """Flip a byte at ``va``, which a sparse stand-in does not map at ``va - IMAGE_BASE``."""
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    data[off] ^= 0xFF


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

    @pytest.mark.parametrize(
        "command",
        [GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE, GUICOMMAND_POP_VISIBLE_COMMAND_RANGE],
    )
    def test_it_tests_the_command_type_of_the_clicked_button(self, command):
        """``esi`` is the `CommandButton` at the call site, ``+0x14`` its `GUICOMMAND`."""
        compares = [i.op_str for i in disassemble() if i.mnemonic == "cmp" and "esi" in i.op_str]
        assert f"dword ptr [esi + {COMMAND_BUTTON_COMMAND:#x}], {command:#x}" in compares

    def test_it_tests_exactly_the_two_paging_commands(self):
        """The whole safety argument. Any third command waved through here would be issued by a
        player the engine has already decided is not playing."""
        compares = [i for i in disassemble() if i.mnemonic == "cmp"]
        assert len(compares) == len(PAGING_COMMANDS)

    def test_the_refusing_path_tail_jumps_to_the_stock_predicate(self):
        """A `jmp`, not a `call`: the stock predicate's own `ret` has to land on the click path's
        return address, and ``ecx`` has to reach it still holding `ThePlayerList`."""
        jumps = [i for i in disassemble() if i.mnemonic == "jmp"]
        assert [int(i.op_str, 16) for i in jumps] == [PLAYER_LIST_LOCAL_IS_NOT_ACTIVE]

    def test_the_allowing_path_answers_zero_and_returns(self):
        """The caller's ``test al, al / jne <discard>`` dispatches on zero, so "let it through"
        is `al = 0` - the same answer an active player gets."""
        insns = disassemble()
        tail = insns[-2:]
        assert [(i.mnemonic, i.op_str) for i in tail] == [("xor", "al, al"), ("ret", "")]
        taken = {int(i.op_str, 16) for i in insns if i.mnemonic == "je"}
        assert taken == {tail[0].address}

    def test_it_clobbers_nothing_the_click_path_still_needs(self):
        """``esi`` is the button the executor is about to be handed, ``ecx`` the argument the
        tail jump depends on, and ``edi``/``ebx``/``ebp`` are live across the gate in the caller.
        Only ``eax`` and the flags may move - which is what the stock predicate does anyway."""
        for ins in disassemble():
            written = {ins.reg_name(r) for r in ins.regs_access()[1]}
            assert not written & {"ecx", "esi", "edi", "ebx", "ebp"}, ins.op_str

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
        assert a != b, "the tail jump must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = observer_command_range_image()
        ObserverCommandRangePatch().apply(data)
        assert ObserverCommandRangePatch().verify(data) == []

    def test_the_gate_becomes_a_call_to_the_cave(self):
        data = observer_command_range_image()
        ObserverCommandRangePatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, CONTROL_BAR_CLICK_GATE_CALL)
        site = bytes(data[off : off + len(CONTROL_BAR_CLICK_GATE_CALL_BYTES)])
        assert site[0] == 0xE8, "still a call, so the caller's frame is unchanged"
        assert CONTROL_BAR_CLICK_GATE_CALL + 5 + struct.unpack_from("<i", site, 1)[0] == section_va

    def test_it_edits_five_bytes_and_no_others(self):
        """The claim in the docstring, as an assertion: past the PE headers - which allocating a
        cave necessarily rewrites - the only changed bytes in the original image are the
        retargeted displacement."""
        before = observer_command_range_image()
        after = bytearray(before)
        ObserverCommandRangePatch().apply(after)
        gate = va_to_offset(before, CONTROL_BAR_CLICK_GATE_CALL)
        headers = _size_of_headers(before)
        differing = {i for i in range(headers, len(before)) if before[i] != after[i]}
        # The opcode byte stays `e8`, so only the four displacement bytes actually move.
        assert differing and differing <= set(range(gate, gate + 5))

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        data = observer_command_range_image()
        ObserverCommandRangePatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self):
        data = observer_command_range_image()
        ObserverCommandRangePatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            ObserverCommandRangePatch().apply(data)

    @pytest.mark.parametrize("anchor", sorted(ANCHORS))
    def test_refuses_a_build_where_the_click_path_moved(self, anchor):
        data = observer_command_range_image()
        _corrupt(data, anchor)
        with pytest.raises(ValueError, match="click path is not this build"):
            ObserverCommandRangePatch().apply(data)

    def test_refuses_an_unmapped_build(self):
        with pytest.raises(ValueError, match="not mapped"):
            ObserverCommandRangePatch().apply(_tiny_pe())

    @pytest.mark.parametrize(
        "command",
        [GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE, GUICOMMAND_POP_VISIBLE_COMMAND_RANGE],
    )
    def test_refuses_a_build_that_numbers_the_paging_commands_differently(self, command):
        """**The check the cave cannot make for itself.** The two numbers come from a name
        table, and a build that reordered it would have the cave waving through whatever command
        happens to sit at 55 - which could be one that posts a `GameMessage`."""
        data = observer_command_range_image()
        off = va_to_offset(data, CONTROL_BAR_COMMAND_INDEX_TABLE + command - 1)
        data[off] = 0  # slot 0, which the stand-in leaves holding a null handler
        with pytest.raises(ValueError, match=f"GUICOMMAND {command} dispatches to"):
            ObserverCommandRangePatch().apply(data)

    def test_refuses_a_build_whose_paging_handler_is_not_the_paging_code(self):
        """A jump table can name the right address in a build where that address holds something
        else, which is the one thing the dispatch walk alone would not catch."""
        data = observer_command_range_image()
        _corrupt(data, CONTROL_BAR_PUSH_RANGE_HANDLER)
        with pytest.raises(ValueError, match="is not the paging code"):
            ObserverCommandRangePatch().apply(data)


class TestVerify:
    def test_rejects_an_unpatched_file(self):
        absent = [f"{SECTION_NAME} section is absent"]
        assert ObserverCommandRangePatch().verify(observer_command_range_image()) == absent

    def test_rejects_a_cave_whose_code_was_altered(self):
        data = observer_command_range_image()
        ObserverCommandRangePatch().apply(data)
        _va, off, _vsize = find_section(data, SECTION_NAME)
        data[off] ^= 0xFF
        assert ObserverCommandRangePatch().verify(data)

    def test_rejects_a_gate_pointing_somewhere_else(self):
        data = observer_command_range_image()
        ObserverCommandRangePatch().apply(data)
        off = va_to_offset(data, CONTROL_BAR_CLICK_GATE_CALL)
        struct.pack_into("<i", data, off + 1, 0x100)
        problems = ObserverCommandRangePatch().verify(data)
        assert any("the hook is not installed" in p for p in problems)

    def test_detect_recovers_it(self):
        data = observer_command_range_image()
        assert ObserverCommandRangePatch.detect(data) is None
        ObserverCommandRangePatch().apply(data)
        found = ObserverCommandRangePatch.detect(data)
        assert found is not None and found.name == ObserverCommandRangePatch.name


class TestTheNumbersItTrusts:
    """The two `GUICOMMAND` values are the patch's whole risk surface, so they are pinned here as
    well as walked in the image: a change to either constant has to be a deliberate edit in two
    files, not a typo that still passes."""

    def test_the_paging_commands_are_55_and_56(self):
        assert GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE == 55
        assert GUICOMMAND_POP_VISIBLE_COMMAND_RANGE == 56

    def test_they_are_not_the_command_the_other_gate_patch_names(self):
        """`ai-revive-gate` reads the same field a few megabytes away; a collision between the
        two constants would mean one of them was read out of the wrong table."""
        assert GUICOMMAND_REVIVE not in {c for c, _h, _b in PAGING_COMMANDS}

    def test_the_stand_in_maps_them_to_the_two_paging_handlers(self):
        data = observer_command_range_image()
        for command, handler in (
            (GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE, CONTROL_BAR_PUSH_RANGE_HANDLER),
            (GUICOMMAND_POP_VISIBLE_COMMAND_RANGE, CONTROL_BAR_POP_RANGE_HANDLER),
        ):
            slot = PAGING_SWITCH_SLOTS[command]
            off = va_to_offset(data, CONTROL_BAR_COMMAND_JUMP_TABLE + slot * 4)
            assert struct.unpack_from("<I", data, off)[0] == handler


def test_it_is_registered():
    assert PATCHES[ObserverCommandRangePatch.name] is ObserverCommandRangePatch


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The stand-in is planted from this patch's own tables, so it round-trips whatever they say.
    Only the shipped `game.dat` can confirm that `0x00941BD2` is the ControlBar's click gate
    rather than the middle of some other call, and that the two switch tables really send
    commands 55 and 56 to the paging handlers.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        for va, expected in (
            (CONTROL_BAR_CLICK_GATE_CALL, CONTROL_BAR_CLICK_GATE_CALL_BYTES),
            *ANCHORS.items(),
        ):
            off = va_to_offset(stock, va)
            assert off is not None, f"0x{va:08x} is not mapped"
            assert bytes(stock[off : off + len(expected)]) == expected, f"0x{va:08x}"

    def test_the_real_switch_sends_the_paging_commands_to_the_paging_handlers(self, stock):
        """The claim the whitelist rests on, read out of the shipped dispatch rather than out of
        the name table it was originally derived from."""
        index = va_to_offset(stock, CONTROL_BAR_COMMAND_INDEX_TABLE)
        jump = va_to_offset(stock, CONTROL_BAR_COMMAND_JUMP_TABLE)
        for command, handler, head in PAGING_COMMANDS:
            slot = stock[index + command - 1]
            assert struct.unpack_from("<I", stock, jump + slot * 4)[0] == handler
            off = va_to_offset(stock, handler)
            assert bytes(stock[off : off + len(head)]) == head

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = ObserverCommandRangePatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert ObserverCommandRangePatch.detect(data) is not None
