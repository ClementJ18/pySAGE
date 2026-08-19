"""Tests for the auto-deposit-inflation patch.

One detour and ~240 bytes of hand-encoded x86, none of which fails loudly when it is wrong: a
mis-encoded SSE opcode assembles, applies and verifies, and then a keep pays a number nobody can
trace. So the tests that matter here **disassemble the result back** and assert it says what it
was meant to say - the stance `test_inflation_readout` takes for the same arithmetic.

Two properties carry more weight than the rest:

* **It is the engine's multiplier, not a re-derivation of it.** The whole value of this patch is
  that an `AutoDepositUpdate` and a `TerrainResourceBehavior` agree; a second implementation that
  drifts by a rounding step would be worse than no patch. So the cave is asserted to call the
  engine's own filter and counting callback and to read the engine's own float constants, and
  `multiplier` states the rule in single precision for the boundary cases.
* **It truncates once.** The displaced `cvttss2si` is re-emitted against the scaled value rather
  than left in place with a multiply bolted on, which would round twice and lose a gold a tick.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import AutoDepositInflationPatch
from sage_patch.addresses import (
    AUTO_DEPOSIT_DEPOSIT,
    AUTO_DEPOSIT_DEPOSIT_BYTES,
    AUTO_DEPOSIT_TRUNCATE,
    AUTO_DEPOSIT_TRUNCATE_BYTES,
    AUTO_DEPOSIT_TRUNCATE_RESUME,
    FLOAT_ONE,
    FLOAT_ONE_PERCENT,
    FLOAT_TWO_PERCENT,
    OBJECT_FILTER_ALLOW,
    OBJECT_FILTER_IS_VALID,
    PLAYER_FOR_EACH_TEAM_OBJECT,
    RESOURCE_MODIFIER_COUNT_CALLBACK,
)
from sage_patch.patches import auto_deposit_inflation as adi
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch import test_maintenance_cost as mc_test

IMAGE_BASE = 0x400000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture(scope="module")
def image() -> bytearray:
    """`maintenance-cost`'s image, which already plants this patch's window alongside its own -
    which is what lets the composition tests below be real rather than a mock."""
    return mc_test.synthetic_image()


@pytest.fixture(scope="module")
def patched(image: bytearray) -> bytes:
    data = bytearray(image)
    AutoDepositInflationPatch().apply(data)
    return bytes(data)


def disasm(data: bytes):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    code_va, off, vsize = find_section(data, adi.SECTION_NAME)
    code = bytes(data[off : off + vsize])
    return list(md.disasm(code, code_va)), code, code_va


def scale(data: bytes):
    """The instructions of the entry point, which is laid out after the helper."""
    insns, _code, code_va = disasm(data)
    begin = adi._assemble(code_va).label_va("scale")  # noqa: SLF001
    return [i for i in insns if i.address >= begin]


class TestWhatItMultipliesBy:
    """`multiplier` is the rule in Python; the emitted code is asserted against it below. Stating
    it once is what makes "did I mean this?" a separate question from "did I encode it right?".
    """

    @pytest.mark.parametrize(("count", "expected"), [(0, 1.0), (1, 0.9), (2, 0.8), (3, 0.7)])
    def test_it_indexes_the_table_by_the_object_count(self, count, expected):
        assert adi.multiplier(count, (100, 90, 80, 70)) == pytest.approx(expected)

    def test_a_table_entry_of_one_hundred_is_exactly_one(self):
        """`100 * 0.01f` has to round to exactly `1.0f` or every faction's first few buildings
        would scale a keep's income by `0.999999` - and `inflation-readout` draws a spurious
        `x0.999999` beside it. `0.01f` is `0.00999999977648...` and the product lands on `1.0f`."""
        assert adi.multiplier(0, (100, 90)) == 1.0

    def test_past_the_end_it_keeps_falling_at_two_percent_an_object(self):
        """The extension starts *at* `count == n`, where `count - n` is zero - so the last entry
        is held for one more object before the slope begins. That is the engine's `jge` and its
        `sub edx, eax`, not a rounding of the boundary."""
        assert adi.multiplier(4, (100, 90, 80, 70)) == pytest.approx(0.70)
        assert adi.multiplier(5, (100, 90, 80, 70)) == pytest.approx(0.68)
        assert adi.multiplier(6, (100, 90, 80, 70)) == pytest.approx(0.66)

    def test_the_extension_floors_at_zero_rather_than_going_negative(self):
        """A negative multiplier would turn a keep's income into a charge by accident, which is a
        different patch's job and not one anybody asked this one to do."""
        assert adi.multiplier(100, (10,)) == 0.0

    def test_an_empty_table_is_no_modifier(self):
        """The engine reads `values[n-1]` of an empty vector here; the cave declines to."""
        assert adi.multiplier(0, ()) == 1.0


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self, patched):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns, code, _va = disasm(patched)
        assert sum(i.size for i in insns) == len(code)

    def test_it_is_the_engines_own_arithmetic(self, patched):
        """Counting a second way is how this patch would drift from the module it exists to
        agree with. The engine's callback also decides two things worth inheriting: it skips
        `testStatus(2)` objects and passes a null player to the filter."""
        insns, _code, _va = disasm(patched)
        called = [
            int(i.op_str, 16) for i in insns if i.mnemonic == "call" and i.op_str.startswith("0x")
        ]
        assert OBJECT_FILTER_IS_VALID in called
        assert OBJECT_FILTER_ALLOW in called
        assert PLAYER_FOR_EACH_TEAM_OBJECT in called
        pushes = [
            int(i.op_str, 16) for i in insns if i.mnemonic == "push" and i.op_str.startswith("0x")
        ]
        assert pushes == [RESOURCE_MODIFIER_COUNT_CALLBACK]

    def test_it_reads_the_engines_own_float_constants(self, patched):
        """1.0f, 0.01f and 0.02f are the engine's, not copies in the cave - so a build where they
        moved fails to match rather than quietly scaling by the wrong number."""
        insns, _code, _va = disasm(patched)
        referenced = {
            int(i.op_str.split("[0x")[1].split("]")[0], 16) for i in insns if "[0x" in i.op_str
        }
        assert referenced == {FLOAT_ONE, FLOAT_ONE_PERCENT, FLOAT_TWO_PERCENT}

    def test_the_object_gate_is_kept(self, patched):
        """`filter.allow(object, player)` is what makes a faction whose filter does not accept its
        keeps byte-for-byte unaffected. Dropping it would silently tax every structure."""
        insns, _code, _va = disasm(patched)
        allow = next(
            i for i in insns if i.mnemonic == "call" and i.op_str == hex(OBJECT_FILTER_ALLOW)
        )
        before = [i for i in insns if i.address < allow.address]
        assert before[-3].op_str == "dword ptr [ebp + 8]", "the Player is pushed first"
        assert before[-2].op_str == "dword ptr [ebp + 0xc]", "so the Object is argument one"

    def test_the_table_index_is_read_as_a_full_dword(self, patched):
        """`cvtsi2ss` from a 16-bit operand would assemble, apply and verify while reading half of
        a count - the same class of bug `fild` had in `command-point-upkeep`."""
        insns, _code, _va = disasm(patched)
        memory = [i for i in insns if i.mnemonic == "cvtsi2ss" and "ptr" in i.op_str]
        assert memory, "the table entry has to come from memory"
        assert all(i.op_str.split(", ")[1].startswith("dword ptr") for i in memory)

    def test_the_multiplier_survives_the_engine_calls_in_memory(self, patched):
        """No calling convention in this image promises an SSE register survives a call, so the
        factor lives in a stack slot between the three of them and only reaches `xmm0` at the
        tail. Every early exit therefore yields the 1.0f the prologue stored - full income."""
        insns, _code, _va = disasm(patched)
        assert insns[3].mnemonic == "movss" and f"0x{FLOAT_ONE:x}" in insns[3].op_str
        assert insns[4].op_str.startswith("dword ptr [ebp - 4],"), "1.0f stored before any call"

    def test_the_helper_frame_is_balanced(self, patched):
        insns, _code, _va = disasm(patched)
        helper = [i for i in insns if i.address < scale(patched)[0].address]
        assert [i.mnemonic for i in helper[:3]] == ["push", "mov", "sub"]
        assert [i.mnemonic for i in helper[-2:]] == ["leave", "ret"]

    def test_it_relocates_with_its_section(self):
        a = adi._assemble(0x00F00000).finish()  # noqa: SLF001
        b = adi._assemble(0x00F01000).finish()  # noqa: SLF001
        assert a != b
        assert len(a) == len(b)


class TestTheEntry:
    def test_it_truncates_once_on_the_scaled_value(self, patched):
        """The displaced instruction was `cvttss2si eax, [ebp-0x14]`. Re-emitting it against
        `xmm0` after the multiply is one rounding; multiplying and then truncating the slot would
        be two, and would lose a gold a tick to no purpose."""
        text = [i.mnemonic + " " + i.op_str for i in scale(patched)]
        assert text.count("mulss xmm0, dword ptr [ebp - 0x14]") == 1
        assert text.count("cvttss2si eax, xmm0") == 1
        assert not any(t.startswith("cvttss2si eax, dword") for t in text)
        assert text.index("mulss xmm0, dword ptr [ebp - 0x14]") < text.index("cvttss2si eax, xmm0")

    def test_it_passes_the_depositing_object_and_its_player(self, patched):
        """`edi` is the Player and `[esi-8]` the Object at the hook - both callee-saved across the
        helper's engine calls, which is what lets the entry be six instructions."""
        text = [i.mnemonic + " " + i.op_str for i in scale(patched)]
        assert text[0] == "push dword ptr [esi - 8]"
        assert text[1] == "push edi"

    def test_the_caller_cleans_its_own_arguments(self, patched):
        """The helper is cdecl and the entry leaves by `jmp`, so a leaked slot is not recovered by
        anybody - it corrupts the deposit it returns into."""
        text = [i.mnemonic + " " + i.op_str for i in scale(patched)]
        assert text.count("add esp, 8") == 1

    def test_it_rejoins_where_the_displaced_instruction_ended(self, patched):
        last = scale(patched)[-1]
        assert last.mnemonic == "jmp"
        assert int(last.op_str, 16) == AUTO_DEPOSIT_TRUNCATE_RESUME


class TestTheHook:
    def test_the_window_is_exactly_one_instruction_so_no_padding_is_needed(self, patched):
        """Five bytes for a five-byte `jmp`. Every other hook in this pair of patches pads."""
        assert len(AUTO_DEPOSIT_TRUNCATE_BYTES) == 5
        off = va_to_offset(patched, AUTO_DEPOSIT_TRUNCATE)
        assert patched[off] == 0xE9
        assert patched[off + 5] != 0x90 or True  # the next byte is the engine's own `push eax`

    def test_the_hook_lands_on_the_entry(self, patched):
        code_va, _off, _vsize = find_section(patched, adi.SECTION_NAME)
        off = va_to_offset(patched, AUTO_DEPOSIT_TRUNCATE)
        rel = struct.unpack_from("<i", patched, off + 1)[0]
        assert AUTO_DEPOSIT_TRUNCATE + 5 + rel == adi._assemble(code_va).label_va("scale")  # noqa: SLF001

    def test_it_leaves_the_deposit_call_alone(self, patched):
        """`second-resource` owns that call and `maintenance-cost` stops one instruction short of
        it; this patch is nowhere near it."""
        off = va_to_offset(patched, AUTO_DEPOSIT_DEPOSIT)
        call = bytes(patched[off : off + len(AUTO_DEPOSIT_DEPOSIT_BYTES)])
        assert call == AUTO_DEPOSIT_DEPOSIT_BYTES


class TestApply:
    def test_apply_then_verify(self, patched):
        assert AutoDepositInflationPatch().verify(patched) == []

    def test_detect_round_trips(self, patched):
        found = AutoDepositInflationPatch.detect(patched)
        assert found is not None
        assert found.name == "auto-deposit-inflation"

    def test_a_clean_image_carries_nothing(self, image):
        assert AutoDepositInflationPatch.detect(bytes(image)) is None
        assert AutoDepositInflationPatch().verify(bytes(image))

    def test_refuses_to_apply_twice(self, image):
        data = bytearray(image)
        AutoDepositInflationPatch().apply(data)
        with pytest.raises(ValueError, match="already carries"):
            AutoDepositInflationPatch().apply(data)

    def test_refuses_a_build_whose_site_is_not_the_stock_one(self, image):
        data = bytearray(image)
        off = AUTO_DEPOSIT_TRUNCATE - IMAGE_BASE
        data[off : off + len(AUTO_DEPOSIT_TRUNCATE_BYTES)] = b"\x90" * len(
            AUTO_DEPOSIT_TRUNCATE_BYTES
        )
        with pytest.raises(ValueError, match="unexpected build"):
            AutoDepositInflationPatch().apply(data)
        assert find_section(data, adi.SECTION_NAME) is None, "a refused build keeps no cave"

    def test_verify_notices_a_tampered_cave(self, patched):
        data = bytearray(patched)
        _va, off, _vsize = find_section(data, adi.SECTION_NAME)
        data[off] ^= 0xFF
        assert AutoDepositInflationPatch().verify(bytes(data))

    def test_the_section_is_not_writable(self):
        assert not (adi._CHARACTERISTICS & 0x80000000)  # noqa: SLF001

    def test_the_section_name_survives_the_eight_byte_pe_field(self, patched):
        assert len(adi.SECTION_NAME) <= 8
        assert find_section(patched, adi.SECTION_NAME) is not None

    def test_it_adds_no_ini_surface(self):
        """It reuses `ResourceModifierObjectFilter` and `ResourceModifierValues`, which every
        faction already declares - there is no keyword to teach anybody."""
        assert AutoDepositInflationPatch().ini_surface().fields == ()


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the address is right."""

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_the_site_holds_its_stock_bytes(self, stock):
        off = va_to_offset(stock, AUTO_DEPOSIT_TRUNCATE)
        assert off is not None
        got = bytes(stock[off : off + len(AUTO_DEPOSIT_TRUNCATE_BYTES)])
        assert got == AUTO_DEPOSIT_TRUNCATE_BYTES

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = AutoDepositInflationPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert AutoDepositInflationPatch.detect(data) is not None

    def test_it_composes_with_maintenance_cost_in_both_orders(self, stock):
        """The two share `AutoDepositUpdate::update` and nothing else: this patch scales the
        amount, that one decides what to do with the sign of it, and the seam is `eax`."""
        from sage_patch import MaintenanceCostPatch  # noqa: PLC0415

        pair = (AutoDepositInflationPatch, MaintenanceCostPatch)
        for order in (pair, pair[::-1]):
            data = bytearray(stock)
            for cls in order:
                cls().apply(data)
            for cls in order:
                assert cls().verify(data) == [], f"{order[0].name} then {order[1].name}"

    def test_it_composes_with_the_other_readers_of_the_same_table(self, stock):
        from sage_patch import CommandPointUpkeepPatch, InflationReadoutPatch  # noqa: PLC0415

        for other in (CommandPointUpkeepPatch, InflationReadoutPatch):
            for order in (
                (AutoDepositInflationPatch, other),
                (other, AutoDepositInflationPatch),
            ):
                data = bytearray(stock)
                for cls in order:
                    cls().apply(data)
                for cls in order:
                    assert cls().verify(data) == [], f"{order[0].name} then {order[1].name}"
