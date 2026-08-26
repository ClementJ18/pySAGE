"""Tests for the AI flag-capture gate.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter
disassemble it back and assert it says what it was meant to say. Two of its properties are
invisible to `apply` and `verify` and would be wrong in a way nobody would notice for a whole
match, so each gets its own check:

* the **order of the two tests**. `BASE_SITE` has to be asked first and on its own, because a
  plain `CaptureFlag` is recaptured by standing on it and that is the entire purpose of the
  tactic being gated. A cave that asked `UNSELECTABLE` first, or that and-ed the two the other
  way round, would silently stop the AI recapturing flags it is supposed to recapture - and
  would still apply, verify and pass a round trip;
* which **displacement each test reads**. `KindOf` and `ObjectStatus` are both bitfields asked
  with the same `test byte [reg + disp], imm8` encoding, so swapping their bases produces
  working code that tests two unrelated bits.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    AI_FLAG_CAPTURE_KEEP,
    AI_FLAG_CAPTURE_PICKER,
    AI_FLAG_CAPTURE_SKIP,
    AI_FLAG_CAPTURE_SQUAD_UPDATE,
    AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT,
    AI_FLAG_CAPTURE_SQUAD_VTABLE,
    KINDOF_BASE_SITE,
    OBJECT_STATUS,
    OBJECT_STATUS_COUNT,
    OBJECT_STATUS_NAMES,
    OBJECT_STATUS_UNSELECTABLE,
    PLAYER_RELATIONSHIP_ALLIES,
)
from sage_patch.patches.ai_flag_capture_gate import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    AiFlagCaptureGatePatch,
    build_code,
)
from sage_patch.patches.utils.kind_of import NAME_TABLE_VA, THING_TEMPLATE_MASK_OFFSET
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import ai_flag_capture_gate_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: `AIFlagCaptureSquad::pickFlag` runs from its prologue to its `ret`. The branch-target sweep
#: stops there: a jump from outside the function could not reach into the middle of its loop.
_PICKER_SIZE = 0x00F0

#: The displacement each of the cave's two bit tests must read - the `KindOf` mask on the
#: `ThingTemplate` and the status mask on the `Object`. Swapping them assembles fine.
_KINDOF_DISP = THING_TEMPLATE_MASK_OFFSET + KINDOF_BASE_SITE // 8
_STATUS_DISP = OBJECT_STATUS + OBJECT_STATUS_UNSELECTABLE // 8


def instructions(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return {ins.address: ins for ins in md.disasm(build_code(base), base)}


def text(ins) -> str:
    return f"{ins.mnemonic} {ins.op_str}".strip()


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def cstring(data: bytes | bytearray, va: int) -> str:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    end = data.index(b"\x00", off)
    return bytes(data[off:end]).decode("ascii")


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        decoded = instructions()
        assert decoded, "nothing decoded"
        last = max(decoded)
        assert last + decoded[last].size == BASE + len(build_code(BASE))

    def test_it_opens_with_the_stock_allies_test(self):
        """The five bytes replaced were `cmp eax, ALLIES` / `je <skip>`, and the relationship the
        engine just computed is only live for that one instruction."""
        decoded = instructions()
        assert text(decoded[BASE]) == f"cmp eax, {PLAYER_RELATIONSHIP_ALLIES}"

    def test_it_loads_the_template_off_the_candidate(self):
        decoded = instructions()
        assert any(text(ins) == "mov ecx, dword ptr [esi + 4]" for ins in decoded.values()), (
            "the KindOf has to come off the candidate's own ThingTemplate"
        )

    def test_it_tests_base_site_on_the_template(self):
        decoded = instructions()
        expected = f"test byte ptr [ecx + 0x{_KINDOF_DISP:x}], {1 << (KINDOF_BASE_SITE % 8)}"
        assert any(text(ins) == expected for ins in decoded.values()), expected

    def test_it_tests_unselectable_on_the_object(self):
        decoded = instructions()
        expected = (
            f"test byte ptr [esi + 0x{_STATUS_DISP:x}], {1 << (OBJECT_STATUS_UNSELECTABLE % 8)}"
        )
        assert any(text(ins) == expected for ins in decoded.values()), expected

    def test_the_two_bit_tests_read_different_masks(self):
        """`KindOf` and `ObjectStatus` are asked with the same encoding, so a swapped base is
        working code testing the wrong bit of the wrong structure."""
        decoded = instructions()
        tests = [ins for ins in decoded.values() if ins.mnemonic == "test"]
        assert len(tests) == 2
        assert _KINDOF_DISP != _STATUS_DISP
        assert {ins.op_str.split("]")[0] for ins in tests} == {
            f"byte ptr [ecx + 0x{_KINDOF_DISP:x}",
            f"byte ptr [esi + 0x{_STATUS_DISP:x}",
        }

    def test_base_site_is_tested_before_unselectable(self):
        """The order is the patch. A plain `CaptureFlag` must reach the accept edge whoever holds
        it, and it does so by failing the `BASE_SITE` test before the claim test is ever asked."""
        decoded = instructions()
        kindof = next(a for a, i in decoded.items() if f"[ecx + 0x{_KINDOF_DISP:x}]" in i.op_str)
        status = next(a for a, i in decoded.items() if f"[esi + 0x{_STATUS_DISP:x}]" in i.op_str)
        assert kindof < status

    def test_a_flag_without_base_site_reaches_the_keep_edge(self):
        """The `je` after the `BASE_SITE` test is what protects the tactic's real purpose: it has
        to land on the exit that accepts the candidate, not on the one that drops it."""
        decoded = instructions()
        kindof = next(a for a, i in decoded.items() if f"[ecx + 0x{_KINDOF_DISP:x}]" in i.op_str)
        branch = min(a for a in decoded if a > kindof and decoded[a].mnemonic.startswith("j"))
        assert decoded[branch].mnemonic == "je"
        landing = int(decoded[branch].op_str, 16)
        assert text(decoded[landing]) == f"jmp 0x{AI_FLAG_CAPTURE_KEEP:x}"

    def test_a_claimed_plot_reaches_the_skip_edge(self):
        decoded = instructions()
        status = next(a for a, i in decoded.items() if f"[esi + 0x{_STATUS_DISP:x}]" in i.op_str)
        branch = min(a for a in decoded if a > status and decoded[a].mnemonic.startswith("j"))
        assert decoded[branch].mnemonic == "jne"
        landing = int(decoded[branch].op_str, 16)
        assert text(decoded[landing]) == f"jmp 0x{AI_FLAG_CAPTURE_SKIP:x}"

    def test_it_has_exactly_two_exits_and_both_are_the_pickers_own_edges(self):
        decoded = instructions()
        end = BASE + len(build_code(BASE))
        outward = {
            int(ins.op_str, 16)
            for ins in decoded.values()
            if ins.mnemonic == "jmp" and not BASE <= int(ins.op_str, 16) < end
        }
        assert outward == {AI_FLAG_CAPTURE_KEEP, AI_FLAG_CAPTURE_SKIP}

    def test_every_conditional_branch_stays_inside_the_cave(self):
        decoded = instructions()
        size = len(build_code(BASE))
        for ins in decoded.values():
            if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
                target = int(ins.op_str, 16)
                assert BASE <= target < BASE + size, f"{text(ins)} leaves the cave"

    def test_it_writes_nothing(self):
        """The gate is a filter. Anything that stored would be changing state the picker and its
        caller still own."""
        capstone = pytest.importorskip("capstone")
        decoded = instructions()
        stores = [
            text(ins)
            for ins in decoded.values()
            for op in ins.operands
            if op.type == capstone.x86.X86_OP_MEM and op.access & capstone.CS_AC_WRITE
        ]
        assert stores == [], "the gate only reads - `cmp` and `test` do not write"

    def test_it_relocates_with_its_section(self):
        assert build_code(BASE) != build_code(BASE + 0x1000)


class TestApply:
    @pytest.fixture
    def image(self) -> bytearray:
        return ai_flag_capture_gate_image()

    def test_apply_then_verify(self, image):
        patch = AiFlagCaptureGatePatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_the_hook_is_a_bare_jmp_with_no_padding(self, image):
        """The stock test is five bytes and `jmp rel32` is five bytes, so unlike most hooks here
        this one needs no `nop` - and a stray one would be a byte of the next instruction."""
        AiFlagCaptureGatePatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        hook = at(image, HOOK_VA, len(HOOK_ORIGINAL))
        assert hook[0] == 0xE9
        assert HOOK_VA + 5 + struct.unpack("<i", hook[1:5])[0] == section_va
        assert len(hook) == 5

    def test_the_cave_holds_the_expected_code(self, image):
        AiFlagCaptureGatePatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        section_va, section_off, _ = located
        code = build_code(section_va)
        assert bytes(image[section_off : section_off + len(code)]) == code

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8

    def test_refuses_to_apply_twice(self, image):
        AiFlagCaptureGatePatch().apply(image)
        with pytest.raises(ValueError):
            AiFlagCaptureGatePatch().apply(image)

    def test_refuses_a_build_whose_vtable_names_another_update(self, image):
        slot = AI_FLAG_CAPTURE_SQUAD_VTABLE + AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT
        off = va_to_offset(image, slot)
        struct.pack_into("<I", image, off, AI_FLAG_CAPTURE_SQUAD_UPDATE + 0x10)
        with pytest.raises(ValueError, match="dispatches to"):
            AiFlagCaptureGatePatch().apply(image)

    @pytest.mark.parametrize("anchor", sorted(ANCHORS))
    def test_refuses_a_build_where_an_anchor_moved(self, image, anchor):
        off = va_to_offset(image, anchor)
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="layout is not this build's"):
            AiFlagCaptureGatePatch().apply(image)

    def test_refuses_an_unmapped_build(self):
        with pytest.raises(ValueError, match="not mapped"):
            AiFlagCaptureGatePatch().apply(bytearray(b"MZ" + b"\x00" * 0x400))


class TestVerify:
    def test_rejects_an_unpatched_file(self):
        problems = AiFlagCaptureGatePatch().verify(ai_flag_capture_gate_image())
        assert problems == [f"{SECTION_NAME} section is absent"]

    def test_rejects_a_cave_whose_code_was_altered(self):
        image = ai_flag_capture_gate_image()
        patch = AiFlagCaptureGatePatch()
        patch.apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        _, section_off, _ = located
        image[section_off] ^= 0xFF
        assert patch.verify(image) == [f"the {SECTION_NAME} cave does not hold the expected test"]

    def test_rejects_a_hook_pointing_somewhere_else(self):
        image = ai_flag_capture_gate_image()
        patch = AiFlagCaptureGatePatch()
        patch.apply(image)
        off = va_to_offset(image, HOOK_VA)
        struct.pack_into("<i", image, off + 1, 0x20)
        assert any("hook jumps to" in problem for problem in patch.verify(image))


class TestRegistration:
    def test_it_is_registered_under_its_name(self):
        assert PATCHES[AiFlagCaptureGatePatch.name] is AiFlagCaptureGatePatch

    def test_it_is_not_experimental(self):
        assert not AiFlagCaptureGatePatch.experimental


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The stand-in is built from this patch's own anchor table, so it round-trips whatever that
    table says. Only the shipped `game.dat` can confirm that `0x009BC28B` is the flag picker's
    ownership test rather than the middle of some other comparison, and that the two bit indices
    name the kindof and the status they claim to.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        for va, expected in ((HOOK_VA, HOOK_ORIGINAL), *ANCHORS.items()):
            assert at(stock, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_vtable_dispatches_to_the_update_that_calls_the_picker(self, stock):
        slot = AI_FLAG_CAPTURE_SQUAD_VTABLE + AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT
        assert struct.unpack("<I", at(stock, slot, 4))[0] == AI_FLAG_CAPTURE_SQUAD_UPDATE

    def test_the_constructor_names_the_tactic(self, stock):
        """The one anchor that cannot be a coincidence of layout: the `push` recorded in ANCHORS
        carries the address of the string `FlagCaptureSquad`."""
        push = ANCHORS[next(va for va in ANCHORS if ANCHORS[va].startswith(b"\x68"))]
        assert cstring(stock, struct.unpack("<I", push[1:5])[0]) == "FlagCaptureSquad"

    def test_the_kindof_bit_is_base_site(self, stock):
        entry = struct.unpack("<I", at(stock, NAME_TABLE_VA + 4 * KINDOF_BASE_SITE, 4))[0]
        assert cstring(stock, entry) == "BASE_SITE"

    def test_the_status_bit_is_unselectable(self, stock):
        assert OBJECT_STATUS_UNSELECTABLE < OBJECT_STATUS_COUNT
        entry = struct.unpack(
            "<I", at(stock, OBJECT_STATUS_NAMES + 4 * OBJECT_STATUS_UNSELECTABLE, 4)
        )[0]
        assert cstring(stock, entry) == "UNSELECTABLE"

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = AiFlagCaptureGatePatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert AiFlagCaptureGatePatch.detect(data) is not None

    def test_the_stock_binary_carries_no_gate(self, stock):
        assert AiFlagCaptureGatePatch.detect(stock) is None

    def test_nothing_branches_into_the_hook_window(self, stock):
        """The window may be *landed on* - it is the fall-through of the call above it - but
        nothing may jump into its interior, or the replacement `jmp` would be entered part-way
        through."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        start = va_to_offset(stock, AI_FLAG_CAPTURE_PICKER)
        body = stock[start : start + _PICKER_SIZE]
        interior = range(HOOK_VA + 1, HOOK_VA + len(HOOK_ORIGINAL))
        for ins in md.disasm(body, AI_FLAG_CAPTURE_PICKER):
            if ins.mnemonic.startswith("j") and ins.op_str.startswith("0x"):
                assert int(ins.op_str, 16) not in interior, f"{text(ins)} at 0x{ins.address:08x}"
