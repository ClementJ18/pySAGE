"""Tests for the inflation-readout patch.

The patch is one detour and ~270 bytes of hand-encoded x86, and none of that fails loudly when it
is wrong - a mis-encoded SSE opcode assembles, applies and verifies, and then the palantir shows a
number nobody can trace back. So the tests that matter here **disassemble the result back** and
assert it says what it was meant to say, the stance `test_command_point_upkeep` takes for its own
bytes.

Two properties carry more weight than the rest:

* **Exactly `1.0f` is what blanks the slot.** `100 * 0.01f` has to round to `1.0f` or every
  faction draws a spurious `x0.999999` for its first few buildings. `multiplier` states the rule
  in single precision and the tests pin the boundary.
* **The link with `command-point-upkeep` is order-independent.** Applied either way round the
  readout has to end up calling the *same* `percent`. That is the one failure the patch framework
  cannot catch on its own - both orders succeed, and a broken one just silently omits a factor -
  so it is asserted directly, in both orders, against the address upkeep actually exported.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import CommandPointUpkeepPatch, InflationReadoutPatch
from sage_patch.addresses import (
    FLOAT_ONE,
    FLOAT_ONE_PERCENT,
    FLOAT_TWO_PERCENT,
    OBJECT_FILTER_IS_VALID,
    PALANTIR_RESOURCE_MULTIPLIER,
    PALANTIR_RESOURCE_MULTIPLIER_BYTES,
    PALANTIR_RESOURCE_MULTIPLIER_RESUME,
    PLAYER_FOR_EACH_TEAM_OBJECT,
    PLAYER_LIST_GET_LOCAL_PLAYER,
    RESOURCE_MODIFIER_COUNT_CALLBACK,
)
from sage_patch.patches import inflation_readout as ir
from sage_patch.patches.income_link import (
    READOUT_IMPORT_OFF,
    UPKEEP_EXPORT_OFF,
    read_export,
    read_import,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch import test_command_point_upkeep as cpu_test

IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """The upkeep patch's own synthetic image, which already maps everything that patch touches -
    plus this patch's one window. Sharing it is what lets the composition tests below be real."""
    data = cpu_test.synthetic_image()
    off = PALANTIR_RESOURCE_MULTIPLIER - IMAGE_BASE
    data[off : off + len(PALANTIR_RESOURCE_MULTIPLIER_BYTES)] = PALANTIR_RESOURCE_MULTIPLIER_BYTES
    return data


@pytest.fixture(scope="module")
def image() -> bytearray:
    return synthetic_image()


@pytest.fixture(scope="module")
def patched(image: bytearray) -> bytes:
    data = bytearray(image)
    InflationReadoutPatch().apply(data)
    return bytes(data)


def cave(data: bytes) -> tuple[int, int, bytes]:
    """``(section VA, code VA, code bytes)`` for the emitted routine."""
    section_va, off, vsize = find_section(data, ir.SECTION_NAME)
    return section_va, section_va + ir.CODE_OFF, bytes(data[off + ir.CODE_OFF : off + vsize])


def disasm(data: bytes):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    _section, code_va, code = cave(data)
    return list(md.disasm(code, code_va)), code, code_va


class TestWhatTheReadoutMeans:
    """`multiplier` is the rule in Python; the emitted code is asserted against it below.

    Stating it once is what makes "did I mean this?" a separate question from "did I encode it
    right?" - the two failure modes this patch has.
    """

    EDAIN_ISH = (100, 100, 100, 100, 100, 90, 80, 70, 60, 50)

    def test_a_table_entry_of_one_hundred_is_exactly_one(self):
        """The whole blank-slot behaviour rests on this. `0.01f` is 0.00999999977648..., so the
        product is *not* 1.0 in exact arithmetic - it rounds to 1.0f, and only just."""
        assert ir.multiplier(0, self.EDAIN_ISH) == 1.0
        assert struct.pack("<f", ir.multiplier(0, self.EDAIN_ISH)) == struct.pack("<f", 1.0)

    @pytest.mark.parametrize(
        ("count", "expected"),
        [(0, 1.0), (4, 1.0), (5, 0.9), (7, 0.7), (9, 0.5)],
    )
    def test_it_indexes_the_table_by_the_object_count(self, count, expected):
        assert ir.multiplier(count, self.EDAIN_ISH) == pytest.approx(expected)

    def test_past_the_end_it_keeps_falling_at_two_percent_an_object(self):
        """The stock mechanic extends its own table rather than holding the last value, and a
        readout that held it instead would over-report income for a big base."""
        assert ir.multiplier(10, self.EDAIN_ISH) == pytest.approx(0.5)
        assert ir.multiplier(11, self.EDAIN_ISH) == pytest.approx(0.48)
        assert ir.multiplier(15, self.EDAIN_ISH) == pytest.approx(0.40)

    def test_the_extension_floors_at_zero_rather_than_going_negative(self):
        assert ir.multiplier(200, self.EDAIN_ISH) == 0.0

    def test_an_empty_table_is_no_modifier(self):
        """A faction with a filter and no values. The engine reads `values[-1]` here; a per-frame
        HUD read deliberately does not."""
        assert ir.multiplier(5, ()) == 1.0

    def test_upkeep_multiplies_rather_than_adds(self):
        """-15% inflation and -10% upkeep is x0.765, not x0.75: the deposit multiplies the two
        factors into the same slot, so a readout that added them would disagree with the bank."""
        assert ir.multiplier(0, (85,), kept=90) == pytest.approx(0.765)
        assert ir.multiplier(0, (85,), kept=90) != pytest.approx(0.75)

    @pytest.mark.parametrize(
        ("values", "kept", "shown"),
        [((85,), 90, 0.765), ((85,), 100, 0.85), ((100,), 90, 0.9), ((70,), 80, 0.56)],
    )
    def test_the_worked_examples_from_the_docs(self, values, kept, shown):
        assert ir.multiplier(0, values, kept=kept) == pytest.approx(shown)

    def test_neither_penalty_still_blanks(self):
        """The combined case has to preserve the blank, or a player running both patches with a
        faction that opts into neither sees `x1` where the stock game shows nothing."""
        assert ir.multiplier(0, (100,), kept=100) == 1.0


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self, patched):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns, code, _code_va = disasm(patched)
        assert sum(i.size for i in insns) == len(code)

    def test_it_calls_the_engines_own_counter_rather_than_its_own(self, patched):
        """Counting a second way is how a readout drifts from the mechanic it reports. The
        callback also decides two things worth inheriting: it skips `testStatus(2)` objects and
        passes a null player to the filter."""
        insns, _code, _va = disasm(patched)
        pushes = [i for i in insns if i.mnemonic == "push" and i.op_str.startswith("0x")]
        assert [int(i.op_str, 16) for i in pushes] == [RESOURCE_MODIFIER_COUNT_CALLBACK]
        called = {int(i.op_str, 16) for i in insns if i.mnemonic == "call" and "0x" in i.op_str}
        assert {
            PLAYER_LIST_GET_LOCAL_PLAYER,
            OBJECT_FILTER_IS_VALID,
            PLAYER_FOR_EACH_TEAM_OBJECT,
        } <= called

    def test_it_reads_the_engines_own_float_constants(self, patched):
        """1.0f, 0.01f and 0.02f are the engine's, not copies in the cave - so a build where they
        moved fails to match rather than quietly scaling by the wrong number."""
        insns, _code, _va = disasm(patched)
        referenced = {
            int(i.op_str.split("[")[1].split("]")[0], 16)
            for i in insns
            if i.mnemonic in {"movss", "mulss"} and "[0x" in i.op_str
        }
        assert referenced == {FLOAT_ONE, FLOAT_ONE_PERCENT, FLOAT_TWO_PERCENT}

    def test_the_percentages_are_converted_as_full_dwords(self, patched):
        """`cvtsi2ss` from a 16-bit operand would assemble, apply and verify while reading half
        of a count - the same class of bug `fild` had in `command-point-upkeep`."""
        insns, _code, _va = disasm(patched)
        memory = [i for i in insns if i.mnemonic == "cvtsi2ss" and "ptr" in i.op_str]
        assert memory, "the table index has to come from memory"
        assert all(i.op_str.split(", ")[1].startswith("dword ptr") for i in memory)

    def test_the_frame_is_balanced(self, patched):
        """The cave leaves by `jmp`, not `ret`, so a leaked stack slot is not recovered by a
        caller - it corrupts the palantir refresh it returns into."""
        insns, _code, _va = disasm(patched)
        assert [i.mnemonic for i in insns[:3]] == ["push", "mov", "sub"]
        assert insns[-2].mnemonic == "leave"
        assert insns[-1].mnemonic == "jmp"

    def test_it_rejoins_where_the_stock_constant_load_did(self, patched):
        insns, _code, _va = disasm(patched)
        assert int(insns[-1].op_str, 16) == PALANTIR_RESOURCE_MULTIPLIER_RESUME

    def test_every_path_out_produces_a_multiplier(self, patched):
        """`xmm0` is the whole output. Every early exit jumps to the tail, which means the 1.0f
        loaded in the prologue is what a degenerate case yields - never an uninitialised register
        and never a fall-through into the next routine."""
        insns, _code, code_va = disasm(patched)
        end = code_va + sum(i.size for i in insns)
        targets = {
            int(i.op_str, 16)
            for i in insns
            if i.mnemonic.startswith("j") and i.op_str.startswith("0x")
        }
        assert all(code_va <= t < end for t in targets - {PALANTIR_RESOURCE_MULTIPLIER_RESUME})
        assert insns[3].mnemonic == "movss", "the 1.0f default is loaded before any branch"
        assert f"0x{FLOAT_ONE:x}" in insns[3].op_str

    def test_it_relocates_with_its_section(self, image):
        a = InflationReadoutPatch._assemble(0x00F00000).finish()  # noqa: SLF001
        b = InflationReadoutPatch._assemble(0x00F01000).finish()  # noqa: SLF001
        assert a != b
        assert len(a) == len(b)


class TestTheHook:
    def test_the_site_is_a_jump_to_the_routine_padded_with_nops(self, patched):
        off = va_to_offset(patched, PALANTIR_RESOURCE_MULTIPLIER)
        target = struct.unpack_from("<i", patched, off + 1)[0] + PALANTIR_RESOURCE_MULTIPLIER + 5
        assert patched[off] == 0xE9
        assert target == InflationReadoutPatch._assemble(  # noqa: SLF001
            find_section(patched, ir.SECTION_NAME)[0]
        ).label_va("mult")
        window = len(PALANTIR_RESOURCE_MULTIPLIER_BYTES)
        assert bytes(patched[off + 5 : off + window]) == b"\x90" * (window - 5)

    def test_the_window_ends_where_the_stock_jump_landed(self):
        """The displaced bytes are a constant load *and* the `jmp` after it, so the resume point
        is that jump's target - not the end of the window, which is how every other hook in this
        tree resumes. Getting this backwards would re-run the region-bonus branch."""
        stock_jmp = PALANTIR_RESOURCE_MULTIPLIER_BYTES[8:]
        assert stock_jmp[0] == 0xE9
        landing = struct.unpack("<i", stock_jmp[1:5])[0] + PALANTIR_RESOURCE_MULTIPLIER + 13
        assert landing == PALANTIR_RESOURCE_MULTIPLIER_RESUME

    def test_the_displaced_constant_load_is_not_re_emitted(self, patched):
        """Unlike the other hooks here, this one *replaces* its window rather than carrying it
        across: the whole point is that the multiplier is no longer the stock 1.0f."""
        _section, _code_va, code = cave(patched)
        assert PALANTIR_RESOURCE_MULTIPLIER_BYTES not in code


class TestApply:
    def test_apply_then_verify(self, patched):
        assert InflationReadoutPatch().verify(patched) == []

    def test_it_writes_nothing_outside_its_site(self, image, patched):
        off = va_to_offset(image, PALANTIR_RESOURCE_MULTIPLIER)
        edited = set(range(off, off + len(PALANTIR_RESOURCE_MULTIPLIER_BYTES)))
        differing = {i for i in range(len(image)) if image[i] != patched[i]}
        assert not differing - edited - set(range(0, 0x400))

    def test_the_section_name_survives_the_eight_byte_pe_field(self, patched):
        assert len(ir.SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        assert find_section(patched, ir.SECTION_NAME) is not None

    def test_the_cave_is_not_writable(self, patched):
        """Nothing in it is written at runtime - the import slot is filled at patch time - so
        `MEM_WRITE` would be a permission this patch does not need."""
        e = struct.unpack_from("<I", patched, 0x3C)[0]
        nsec = struct.unpack_from("<H", patched, e + 6)[0]
        sectab = e + 24 + struct.unpack_from("<H", patched, e + 20)[0]
        for i in range(nsec):
            hdr = sectab + i * 40
            if bytes(patched[hdr : hdr + 8]).rstrip(b"\x00").decode() != ir.SECTION_NAME:
                continue
            chars = struct.unpack_from("<I", patched, hdr + 36)[0]
            assert chars & 0x20000000, "the cave holds code"
            assert chars & 0x40000000, "and the import slot is read from it"
            assert not chars & 0x80000000, "but nothing writes to it at runtime"
            return
        pytest.fail(f"{ir.SECTION_NAME} is absent")

    def test_refuses_to_apply_twice(self, image):
        data = bytearray(image)
        InflationReadoutPatch().apply(data)
        with pytest.raises(ValueError, match="already carries"):
            InflationReadoutPatch().apply(data)

    def test_refuses_a_build_whose_hook_site_is_not_the_stock_one(self, image):
        data = bytearray(image)
        data[va_to_offset(data, PALANTIR_RESOURCE_MULTIPLIER)] ^= 0xFF
        with pytest.raises(ValueError, match="unexpected build"):
            InflationReadoutPatch().apply(data)

    def test_a_refused_build_is_left_without_a_cave(self, image):
        """The site is checked before the section is appended, so a wrong build is not left
        carrying a cave nothing jumps into."""
        data = bytearray(image)
        data[va_to_offset(data, PALANTIR_RESOURCE_MULTIPLIER)] ^= 0xFF
        with pytest.raises(ValueError):
            InflationReadoutPatch().apply(data)
        assert find_section(data, ir.SECTION_NAME) is None


class TestVerify:
    def test_an_unpatched_image_does_not_verify(self, image):
        problems = InflationReadoutPatch().verify(image)
        assert problems == [f"no {ir.SECTION_NAME} section: the file does not carry this patch"]

    def test_a_rewritten_hook_does_not_verify(self, patched):
        data = bytearray(patched)
        data[va_to_offset(data, PALANTIR_RESOURCE_MULTIPLIER) + 1] ^= 0xFF
        assert any("resource multiplier" in p for p in InflationReadoutPatch().verify(data))

    def test_a_bogus_import_does_not_verify(self, patched):
        """The slot is a call target. A stale value is a jump into whatever lives there now."""
        data = bytearray(patched)
        _va, off, _vsize = find_section(data, ir.SECTION_NAME)
        struct.pack_into("<I", data, off + READOUT_IMPORT_OFF, 0xDEADBEEF)
        assert any("carries no" in p for p in InflationReadoutPatch().verify(data))


class TestComposesWithCommandPointUpkeep:
    """The pair this patch exists to combine with. Both scale the same income, so the readout has
    to show the product - and it has to do so whichever order they were applied in."""

    @pytest.mark.parametrize("order", [(0, 1), (1, 0)])
    def test_any_order_applies_and_verifies(self, order):
        data = synthetic_image()
        patches = (CommandPointUpkeepPatch(), InflationReadoutPatch())
        for i in order:
            patches[i].apply(data)
        for patch in (CommandPointUpkeepPatch(), InflationReadoutPatch()):
            assert patch.verify(data) == [], f"{patch} failed in order {order}"

    @pytest.mark.parametrize("order", [(0, 1), (1, 0)])
    def test_either_order_links_the_readout_to_the_same_percent(self, order):
        """The rule-3 trap: derive-from-the-other-patch would leave one order silently unlinked,
        and both orders would still 'succeed'. So assert the link itself, not just that it
        applied."""
        data = synthetic_image()
        patches = (CommandPointUpkeepPatch(), InflationReadoutPatch())
        for i in order:
            patches[i].apply(data)

        _va, upkeep_off, _vsize = find_section(data, ".upkeep")
        exported = struct.unpack_from("<I", data, upkeep_off + UPKEEP_EXPORT_OFF)[0]
        assert exported != 0, "upkeep must publish percent regardless of order"
        assert read_import(data) == exported == read_export(data)

    def test_the_readout_alone_is_unlinked_rather_than_dangling(self):
        data = synthetic_image()
        InflationReadoutPatch().apply(data)
        assert read_import(data) == 0
        assert InflationReadoutPatch().verify(data) == []

    def test_upkeep_alone_still_exports(self):
        """The export is unconditional, so adding the readout to an already-patched binary needs
        nothing from upkeep."""
        data = synthetic_image()
        CommandPointUpkeepPatch().apply(data)
        assert read_export(data) is not None
        assert read_import(data) is None

    def test_the_cave_calls_through_the_slot_rather_than_a_baked_address(self, patched):
        """An indirect call is what makes the link fillable after the fact - a direct one would
        only work in one application order."""
        insns, _code, _va = disasm(patched)
        assert any(i.mnemonic == "call" and i.op_str == "eax" for i in insns)

    def test_they_edit_disjoint_engine_bytes(self):
        before = synthetic_image()
        mine = bytearray(before)
        InflationReadoutPatch().apply(mine)
        theirs = bytearray(before)
        CommandPointUpkeepPatch().apply(theirs)
        headers = set(range(0, 0x400))
        a = {i for i in range(len(before)) if before[i] != mine[i]} - headers
        b = {i for i in range(len(before)) if before[i] != theirs[i]} - headers
        assert not a & b

    def test_the_section_table_stays_sorted(self):
        data = synthetic_image()
        CommandPointUpkeepPatch().apply(data)
        InflationReadoutPatch().apply(data)
        e = struct.unpack_from("<I", data, 0x3C)[0]
        nsec = struct.unpack_from("<H", data, e + 6)[0]
        sectab = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
        rvas = [struct.unpack_from("<I", data, sectab + i * 40 + 12)[0] for i in range(nsec)]
        assert rvas == sorted(rvas)
