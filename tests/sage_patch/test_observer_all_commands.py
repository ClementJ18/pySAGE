"""Tests for the observer-all-commands patch.

Five bytes, so the interesting assertions are not about size. Three things are silent otherwise:
five bytes that decode to something other than what was meant, a zero narrow enough to leave
garbage in the dword the executor is handed, and the patch quietly co-existing with
`observer-command-range` on the call both of them own.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    CONTROL_BAR_CLICK_ARGUMENT_BUILD,
    CONTROL_BAR_CLICK_GATE_CALL,
    CONTROL_BAR_CLICK_GATE_CALL_BYTES,
    CONTROL_BAR_CLICK_GATE_SUFFIX,
    PLAYER_LIST_LOCAL_IS_NOT_ACTIVE,
)
from sage_patch.patches.experimental.observer_all_commands import (
    ALWAYS_ACTIVE,
    ANCHORS,
    ObserverAllCommandsPatch,
)
from sage_patch.patches.observer_command_range import ObserverCommandRangePatch
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import observer_all_commands_image
from tests.sage_patch.test_patching import _tiny_pe

#: The installed binary. Its click path is byte-identical to the clean 2.01.2614 backup at every
#: site this patch touches, so either answers the "are these addresses real" question.
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def _size_of_headers(data: bytes | bytearray) -> int:
    """`SizeOfHeaders`, past which nothing this patch writes belongs."""
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    return struct.unpack_from("<I", data, e_lfanew + 24 + 60)[0]


def _corrupt(data: bytearray, va: int) -> None:
    """Flip a byte at ``va``, which a sparse stand-in does not map at ``va - IMAGE_BASE``."""
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    data[off] ^= 0xFF


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(code, base))


class TestTheFiveBytes:
    def test_they_are_the_length_of_the_call_they_replace(self):
        """Anything shorter would need the rest padding anyway, anything longer would run into
        the ``test al, al`` the answer is for."""
        assert len(ALWAYS_ACTIVE) == len(CONTROL_BAR_CLICK_GATE_CALL_BYTES) == 5

    def test_they_decode_to_a_zeroed_eax_and_nothing_else(self):
        insns = disassemble(ALWAYS_ACTIVE, CONTROL_BAR_CLICK_GATE_CALL)
        assert [(i.mnemonic, i.op_str) for i in insns] == [
            ("xor", "eax, eax"),
            ("nop", ""),
            ("nop", ""),
            ("nop", ""),
        ]

    def test_the_zero_is_thirty_two_bits_wide(self):
        """**The assertion the patch exists to keep.** Four instructions below the gate the
        caller does ``sete al`` / ``push eax`` twice, building the executor's two `Bool`
        arguments as dwords. The stock predicate leaves ``eax`` at a clean 0 or 1, so a
        replacement writing only ``al`` would push the window virtual's leftover top three
        bytes into `ControlBar::doCommand`."""
        insns = disassemble(ALWAYS_ACTIVE, CONTROL_BAR_CLICK_GATE_CALL)
        written = {insns[0].reg_name(r) for r in insns[0].regs_access()[1]}
        assert "eax" in written and "al" not in written

    def test_it_clobbers_nothing_the_click_path_still_needs(self):
        """``esi`` is the button the executor is about to be handed, ``edi`` the window stored
        into it, and ``ebx`` is `TheControlBar`. ``eax`` and the flags are all the stock
        predicate was entitled to move, and all this moves."""
        for ins in disassemble(ALWAYS_ACTIVE, CONTROL_BAR_CLICK_GATE_CALL):
            written = {ins.reg_name(r) for r in ins.regs_access()[1]}
            assert not written & {"ecx", "esi", "edi", "ebx", "ebp", "esp"}, ins.mnemonic

    def test_the_last_byte_ends_where_the_call_did(self):
        """The ``jne`` at `CONTROL_BAR_CLICK_GATE_SUFFIX` + 2 is a backward ``rel8`` this patch
        does not rewrite, so the instruction boundary after the five bytes has to be the stock
        one or everything below decodes shifted."""
        insns = disassemble(ALWAYS_ACTIVE, CONTROL_BAR_CLICK_GATE_CALL)
        assert insns[-1].address + insns[-1].size == CONTROL_BAR_CLICK_GATE_SUFFIX

    def test_it_asks_the_predicate_nothing(self):
        """The whole difference from `observer-command-range`: there is no call left, so the
        answer cannot depend on who is watching."""
        assert not any(
            i.mnemonic in {"call", "jmp"}
            for i in disassemble(ALWAYS_ACTIVE, CONTROL_BAR_CLICK_GATE_CALL)
        )


class TestApply:
    def test_apply_then_verify(self):
        data = observer_all_commands_image()
        ObserverAllCommandsPatch().apply(data)
        assert ObserverAllCommandsPatch().verify(data) == []

    def test_the_gate_holds_the_constant(self):
        data = observer_all_commands_image()
        ObserverAllCommandsPatch().apply(data)
        off = va_to_offset(data, CONTROL_BAR_CLICK_GATE_CALL)
        assert bytes(data[off : off + len(ALWAYS_ACTIVE)]) == ALWAYS_ACTIVE

    def test_it_edits_five_bytes_and_no_others(self):
        """No cave, so unlike every patch that allocates one this can claim the whole image:
        past the PE headers, exactly the gate moves."""
        before = observer_all_commands_image()
        after = bytearray(before)
        ObserverAllCommandsPatch().apply(after)
        gate = va_to_offset(before, CONTROL_BAR_CLICK_GATE_CALL)
        headers = _size_of_headers(before)
        differing = {i for i in range(headers, len(before)) if before[i] != after[i]}
        assert differing == set(range(gate, gate + len(ALWAYS_ACTIVE)))

    def test_it_allocates_no_section(self):
        before = observer_all_commands_image()
        after = bytearray(before)
        ObserverAllCommandsPatch().apply(after)
        assert len(after) == len(before)
        assert after[: _size_of_headers(before)] == before[: _size_of_headers(before)]

    def test_refuses_to_apply_twice(self):
        data = observer_all_commands_image()
        ObserverAllCommandsPatch().apply(data)
        with pytest.raises(ValueError, match="is applied to this binary"):
            ObserverAllCommandsPatch().apply(data)

    @pytest.mark.parametrize("anchor", sorted(ANCHORS))
    def test_refuses_a_build_where_the_click_path_moved(self, anchor):
        data = observer_all_commands_image()
        _corrupt(data, anchor)
        with pytest.raises(ValueError, match="click path is not this build"):
            ObserverAllCommandsPatch().apply(data)

    def test_refuses_an_unmapped_build(self):
        with pytest.raises(ValueError, match="not mapped"):
            ObserverAllCommandsPatch().apply(_tiny_pe())

    def test_the_argument_build_is_an_anchor(self):
        """It is the only one a reader would think is decorative, and it is the one that says
        why the zero is thirty-two bits wide."""
        assert CONTROL_BAR_CLICK_ARGUMENT_BUILD in ANCHORS


class TestVerify:
    def test_rejects_an_unpatched_file(self):
        problems = ObserverAllCommandsPatch().verify(observer_all_commands_image())
        assert any("the gate is not open" in p for p in problems)

    def test_rejects_a_gate_holding_some_other_answer(self):
        data = observer_all_commands_image()
        ObserverAllCommandsPatch().apply(data)
        off = va_to_offset(data, CONTROL_BAR_CLICK_GATE_CALL)
        data[off] ^= 0xFF
        assert ObserverAllCommandsPatch().verify(data)

    def test_detect_recovers_it(self):
        data = observer_all_commands_image()
        assert ObserverAllCommandsPatch.detect(data) is None
        ObserverAllCommandsPatch().apply(data)
        found = ObserverAllCommandsPatch.detect(data)
        assert found is not None and found.name == ObserverAllCommandsPatch.name


class TestItIsDeclaredForWhatItIs:
    def test_it_is_registered(self):
        assert PATCHES[ObserverAllCommandsPatch.name] is ObserverAllCommandsPatch

    def test_it_is_experimental(self):
        """It dispatches order-posting commands from a seat the engine says is not playing, so
        the CLI has to say so before it writes a byte."""
        assert ObserverAllCommandsPatch.experimental is True

    def test_it_has_an_author(self):
        assert ObserverAllCommandsPatch.author


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The stand-in is planted from this patch's own table, so it round-trips whatever that says.
    Only the shipped `game.dat` can confirm that `0x00941BD2` is the ControlBar's click gate and
    that the five bytes there really call the observer predicate.
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

    def test_the_gate_really_calls_the_observer_predicate(self, stock):
        """Read out of the shipped displacement rather than trusted from the write-up: if this
        call went anywhere else, overwriting it would be deleting some other question."""
        off = va_to_offset(stock, CONTROL_BAR_CLICK_GATE_CALL)
        rel = struct.unpack_from("<i", stock, off + 1)[0]
        assert stock[off] == 0xE8
        assert CONTROL_BAR_CLICK_GATE_CALL + 5 + rel == PLAYER_LIST_LOCAL_IS_NOT_ACTIVE

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = ObserverAllCommandsPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert ObserverAllCommandsPatch.detect(data) is not None

    @pytest.mark.parametrize("first", [ObserverAllCommandsPatch, ObserverCommandRangePatch])
    def test_it_cannot_be_combined_with_observer_command_range(self, stock, first):
        """Both own the same five bytes. Whichever goes second has to refuse, in either order -
        a binary carrying half of each would have the cave's whitelist unreachable behind an
        open gate, or the open gate overwritten by a call into a cave."""
        second = (
            ObserverCommandRangePatch
            if first is ObserverAllCommandsPatch
            else ObserverAllCommandsPatch
        )
        data = bytearray(stock)
        first().apply(data)
        with pytest.raises(ValueError):
            second().apply(data)

    def test_the_conflict_names_the_other_patch(self, stock):
        """`apply_byte_patch` would refuse with a hex pair either way; this is the one direction
        where the reason is knowable, so it is said out loud."""
        data = bytearray(stock)
        ObserverCommandRangePatch().apply(data)
        with pytest.raises(ValueError, match="observer-command-range"):
            ObserverAllCommandsPatch().apply(data)
