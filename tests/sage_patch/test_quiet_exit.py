"""Tests for the quiet-exit patch.

The cave is hand-assembled x86 that cannot be executed here and runs only inside a process that has
already raised an exception, so nothing about it is observable by trying it. The tests that matter
disassemble it back and assert it says what it was meant to say, with the one failure mode singled
out that is invisible to `apply` and `verify`: a **stack imbalance**. The gate is reached by a
`call` that stood in for `call writeMiniDump`, so on the write path it must hand `writeMiniDump` the
identical frame - reached by a `jmp`, adding no push - and on the skip path it must `ret` to the
same instruction the call would have, leaving the two already-pushed arguments for the filter's own
`add esp, 8`. `TestTheGate` checks the shape of both paths; `TestStackBalance` checks neither path
pushes or pops.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    GAME_ENGINE,
    GAME_ENGINE_QUITTING,
    WRITE_MINI_DUMP,
    WRITE_MINI_DUMP_CALL_FILTER,
    WRITE_MINI_DUMP_CALL_FILTER_BYTES,
)
from sage_patch.patches.quiet_exit import (
    SECTION_NAME,
    QuietExitPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, next_section_rva, va_to_offset

from .synthetic import quiet_exit_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: The unhandled-exception filter runs from `0x0043D610` to the `int3` padding at `0x0043DAFD`; the
#: next function's prologue is `0x0043DB00`. This is the span the "nothing branches into the call"
#: check disassembles.
_FILTER = 0x0043D610
_FILTER_SIZE = 0x0043DAFD - _FILTER

#: IMAGE_BASE, the value the site's stock call points back to relative to - here, what its rewritten
#: form must *stop* pointing at.
_STOCK_CALL_TARGET = WRITE_MINI_DUMP


def instructions(base: int = BASE):
    """The gate's code, decoded at the address it was laid out for."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_code(base), base))


def text(ins) -> str:
    return f"{ins.mnemonic} {ins.op_str}".strip()


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


class TestTheGate:
    def _body(self):
        return instructions()

    def test_it_reads_the_game_engine_pointer(self):
        """Through the global, not a register: the filter hands it nothing, so the discriminator has
        to be a singleton the cave can reach on its own."""
        assert text(self._body()[0]) == f"mov eax, dword ptr [0x{GAME_ENGINE:x}]"

    def test_a_null_engine_takes_the_write_path(self):
        """If the pointer is not yet set - or already torn down - the honest answer is "I cannot
        tell", and that must be the stock behaviour of writing the dump, not swallowing it."""
        body = self._body()
        assert text(body[1]) == "test eax, eax"
        je = body[2]
        assert je.mnemonic == "je"
        # the `je` target is the write path, i.e. the tail-jump to writeMiniDump
        target = int(je.op_str, 16)
        jmp = next(ins for ins in body if ins.mnemonic == "jmp")
        assert target == jmp.address

    def test_it_tests_the_quitting_byte_through_the_pointer(self):
        want = f"cmp byte ptr [eax + 0x{GAME_ENGINE_QUITTING:x}], 0"
        assert any(text(ins) == want for ins in self._body())

    def test_quitting_takes_the_skip_path(self):
        """The `jne` past the tail-jump is the whole patch: a set flag is what drops the dump."""
        body = self._body()
        jne = next(ins for ins in body if ins.mnemonic == "jne")
        ret = next(ins for ins in body if ins.mnemonic == "ret")
        assert int(jne.op_str, 16) == ret.address

    def test_the_write_path_tail_jumps_to_write_mini_dump(self):
        """A `jmp`, not a `call`: the filter's `call` into the gate already pushed the return
        address, so `writeMiniDump` sees the frame it would have from a direct call and returns
        straight to the filter."""
        jmp = next(ins for ins in self._body() if ins.mnemonic == "jmp")
        assert int(jmp.op_str, 16) == WRITE_MINI_DUMP

    def test_the_skip_path_returns(self):
        assert self._body()[-1].mnemonic == "ret"

    def test_the_skip_return_is_a_bare_ret(self):
        """`ret`, not `ret N`: the call is `cdecl` and the filter cleans the two arguments itself,
        so the gate must not also adjust the stack."""
        ret = self._body()[-1]
        assert ret.op_str == ""

    def test_it_calls_nothing(self):
        """It runs in a process that has already faulted, so it is leaf code by construction."""
        assert not [ins for ins in self._body() if ins.mnemonic == "call"]

    def test_its_conditional_branches_are_forward(self):
        """The only backward transfer is the tail-jump to `writeMiniDump`, which is an exit, not a
        loop; every decision branch points forward, so the gate cannot spin."""
        for ins in self._body():
            if ins.mnemonic in {"je", "jne"}:
                assert int(ins.op_str, 16) > ins.address, f"{ins.address:#010x} branches backwards"


class TestStackBalance:
    """The gate stands in for `call writeMiniDump`, so it must leave the stack exactly as that call
    would at the instruction after it - on both paths."""

    def test_it_neither_pushes_nor_pops(self):
        body = instructions()
        assert not [ins for ins in body if ins.mnemonic in {"push", "pop", "leave"}]

    def test_the_only_unconditional_transfers_are_the_two_exits(self):
        """Exactly one `jmp` (the write-path tail call) and one `ret` (the skip path), and nothing
        else that leaves the routine - so the two paths are the only two ways out."""
        body = instructions()
        assert sum(1 for ins in body if ins.mnemonic == "jmp") == 1
        assert sum(1 for ins in body if ins.mnemonic == "ret") == 1


class TestApply:
    def test_it_applies_and_verifies(self):
        data = quiet_exit_image()
        patch = QuietExitPatch()
        patch.apply(data)
        assert patch.verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert QuietExitPatch().verify(quiet_exit_image())

    def test_the_call_site_becomes_a_call_into_the_cave(self):
        data = quiet_exit_image()
        QuietExitPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        off = va_to_offset(data, WRITE_MINI_DUMP_CALL_FILTER)
        assert data[off] == 0xE8
        reached = WRITE_MINI_DUMP_CALL_FILTER + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert reached == section_va

    def test_the_call_is_the_same_width_it_replaced(self):
        """Five bytes for five, so the `add esp, 8` that follows still sits where it did and the
        two pushed arguments are still what it cleans."""
        assert len(QuietExitPatch._call(BASE)) == len(WRITE_MINI_DUMP_CALL_FILTER_BYTES)

    def test_the_cave_lands_past_every_existing_section(self):
        data = quiet_exit_image()
        expected = next_section_rva(data)
        QuietExitPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        assert section_va - 0x400000 == expected

    def test_the_cave_is_not_writable(self):
        """Unlike crash-dump's cave, this one spills nothing - it only reads a global and a byte -
        so it needs no write permission."""
        data = quiet_exit_image()
        QuietExitPatch().apply(data)
        e = struct.unpack_from("<I", data, 0x3C)[0]
        count = struct.unpack_from("<H", data, e + 6)[0]
        table = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
        for index in range(count):
            header = table + index * 40
            if bytes(data[header : header + 8]) == SECTION_NAME.encode("ascii").ljust(8, b"\x00"):
                assert not struct.unpack_from("<I", data, header + 36)[0] & 0x80000000
                return
        raise AssertionError(f"{SECTION_NAME} is absent")

    def test_applying_twice_raises_rather_than_double_hooking(self):
        data = quiet_exit_image()
        QuietExitPatch().apply(data)
        with pytest.raises(ValueError):
            QuietExitPatch().apply(data)

    def test_a_moved_call_site_is_refused(self):
        data = quiet_exit_image()
        off = va_to_offset(data, WRITE_MINI_DUMP_CALL_FILTER)
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            QuietExitPatch().apply(data)

    def test_it_is_registered(self):
        assert PATCHES[QuietExitPatch.name] is QuietExitPatch

    def test_it_is_not_experimental(self):
        assert not QuietExitPatch.experimental


class TestDetect:
    def test_it_recognises_its_own_work(self):
        data = quiet_exit_image()
        QuietExitPatch().apply(data)
        assert isinstance(QuietExitPatch.detect(data), QuietExitPatch)

    def test_an_unpatched_image_carries_nothing(self):
        assert QuietExitPatch.detect(quiet_exit_image()) is None

    def test_detection_never_raises_on_something_that_is_not_a_game_dat(self):
        assert QuietExitPatch.detect(b"not a PE at all") is None


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the address is right.

    The stand-in round-trips whatever the anchor says; only the shipped `game.dat` can confirm that
    `0x0043D74E` is the filter's `call writeMiniDump` rather than the middle of some other sequence.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_the_site_holds_its_stock_bytes(self, stock):
        assert (
            at(stock, WRITE_MINI_DUMP_CALL_FILTER, len(WRITE_MINI_DUMP_CALL_FILTER_BYTES))
            == WRITE_MINI_DUMP_CALL_FILTER_BYTES
        )

    def test_the_site_really_calls_write_mini_dump(self, stock):
        """The check the synthetic image cannot make: decode the stock call and confirm it reaches
        `writeMiniDump`, so the gate is being spliced into the dump path and not somewhere else."""
        off = va_to_offset(stock, WRITE_MINI_DUMP_CALL_FILTER)
        assert stock[off] == 0xE8
        reached = WRITE_MINI_DUMP_CALL_FILTER + 5 + struct.unpack_from("<i", stock, off + 1)[0]
        assert reached == _STOCK_CALL_TARGET

    def test_nothing_branches_into_the_call(self, stock):
        """The call may be *landed on* at its first byte, but nothing may branch into its interior,
        or the replacement `call` would be entered part-way through."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        start = va_to_offset(stock, _FILTER)
        interior = range(
            WRITE_MINI_DUMP_CALL_FILTER + 1,
            WRITE_MINI_DUMP_CALL_FILTER + len(WRITE_MINI_DUMP_CALL_FILTER_BYTES),
        )
        for ins in md.disasm(stock[start : start + _FILTER_SIZE], _FILTER):
            if ins.mnemonic.startswith("j") and ins.op_str.startswith("0x"):
                assert int(ins.op_str, 16) not in interior, (
                    f"{ins.address:#010x} branches into the call at "
                    f"{WRITE_MINI_DUMP_CALL_FILTER:#010x}"
                )

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = QuietExitPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert QuietExitPatch.detect(data) is not None

    def test_the_stock_binary_carries_nothing(self, stock):
        assert QuietExitPatch.detect(stock) is None
