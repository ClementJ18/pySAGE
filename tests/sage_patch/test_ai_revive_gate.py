"""Tests for the AI revive-gate patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests
disassemble it back and assert it says what it was meant to say. A wrong byte in a hook does
not raise - it crashes the game, or worse, silently answers for the wrong hero - so encoding
errors have to be caught statically.
"""

from __future__ import annotations

import itertools
import struct

import pytest

from sage_patch import CahFactionsPatch, CommandSetLimitPatch
from sage_patch.addresses import (
    BUILD_ASSISTANT_VTABLE,
    CAN_MAKE_UNIT,
    CAN_MAKE_UNIT_ACCEPT,
    CAN_MAKE_UNIT_BUMP_SLOT,
    CAN_MAKE_UNIT_NEXT_SLOT,
    CAN_MAKE_UNIT_PRODUCTION_GATE,
    CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
    CAN_MAKE_UNIT_SCAN_BOUND,
    CAN_MAKE_UNIT_UPGRADE_GATE,
    CAN_MAKE_UNIT_VTABLE_SLOT,
    GUICOMMAND_REVIVE,
)
from sage_patch.patches.ai_revive_gate import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    PRODUCTION_GATE_RETURN,
    SECTION_NAME,
    AiReviveGatePatch,
    build_code,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_patching import (
    _cah_game_dat,
    _plant_commandset_sites,
    _section_rvas,
    _tiny_pe,
)

BASE = 0x00F00000
IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the hook site, every anchor and the two `BuildAssistant`
    vtable slots, with the real original bytes planted, so the whole apply + verify path runs
    without the copyrighted `game.dat`."""
    slots = (CAN_MAKE_UNIT_VTABLE_SLOT, CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT)
    highest = (
        max(
            HOOK_VA,
            CAN_MAKE_UNIT_SCAN_BOUND,
            *ANCHORS,
            *(BUILD_ASSISTANT_VTABLE + s for s in slots),
        )
        - IMAGE_BASE
        + 0x100
    )
    data = bytearray(((highest + 0x400) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for a 2nd header
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    plant_sites(data)
    return data


def plant_sites(data: bytearray) -> None:
    """The clean bytes the patch asserts before writing. Separate so a composition test can host
    this patch and `commandset-limit` in one image."""
    data[HOOK_VA - IMAGE_BASE : HOOK_VA - IMAGE_BASE + len(HOOK_ORIGINAL)] = HOOK_ORIGINAL
    for va, expected in ANCHORS.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(expected)] = expected
    for slot, target in (
        (CAN_MAKE_UNIT_VTABLE_SLOT, CAN_MAKE_UNIT),
        (CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT, CAN_MAKE_UNIT_PRODUCTION_GATE),
    ):
        struct.pack_into("<I", data, BUILD_ASSISTANT_VTABLE + slot - IMAGE_BASE, target)


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

    def test_it_tests_the_revive_command_type(self):
        first = disassemble()[0]
        assert first.mnemonic == "cmp"
        assert first.op_str == f"dword ptr [esi + 0x14], {GUICOMMAND_REVIVE:#x}"

    def test_it_compares_the_slot_count_against_the_requested_index(self):
        ops = [(i.mnemonic, i.op_str) for i in disassemble()]
        # [ebp-0xc] is the running count of REVIVE slots, [ebp+0x10] the reviveIndex argument
        assert ("mov", "eax, dword ptr [ebp - 0xc]") in ops
        assert ("cmp", "eax, dword ptr [ebp + 0x10]") in ops

    def test_it_counts_the_matched_slot_before_handing_over_to_the_gate(self):
        """The whole correctness argument: a counted slot cannot match again, so a gate failure
        ends the search for this index instead of sliding onto the next enabled slot."""
        insns = disassemble()
        inc = next(i for i in insns if i.mnemonic == "inc")
        assert inc.op_str == "dword ptr [ebp - 0xc]"
        gate_jump = next(
            i
            for i in insns
            if i.mnemonic == "jmp" and int(i.op_str, 16) == CAN_MAKE_UNIT_UPGRADE_GATE
        )
        assert inc.address < gate_jump.address
        # and nothing else runs in between
        assert inc.address + inc.size == gate_jump.address

    def test_it_tests_the_return_address_before_reaching_the_gate(self):
        """The regression guard: `canMakeUnit` is on the player's path through
        `BuildAssistant`'s `+0x64` gate, so the gate may only be applied to the AI's own direct
        queries. `[ebp+4]` is the return address, and one value means "not the AI"."""
        insns = disassemble()
        test = next(
            i for i in insns if i.mnemonic == "cmp" and i.op_str.startswith("dword ptr [ebp + 4]")
        )
        assert test.op_str == f"dword ptr [ebp + 4], {PRODUCTION_GATE_RETURN:#x}"
        gate_jump = next(
            i
            for i in insns
            if i.mnemonic == "jmp" and int(i.op_str, 16) == CAN_MAKE_UNIT_UPGRADE_GATE
        )
        assert test.address < gate_jump.address

    def test_the_production_path_takes_the_stock_edge(self):
        """Reached through `+0x64` the cave must jump to the accept path, which is exactly what
        the stock `je` at 0x007950DA did - so nothing a human sees, clicks or queues changes."""
        insns = disassemble()
        test = next(
            i for i in insns if i.mnemonic == "cmp" and i.op_str.startswith("dword ptr [ebp + 4]")
        )
        taken = next(i for i in insns if i.mnemonic == "je" and i.address > test.address)
        landing = int(taken.op_str, 16)
        stock = next(i for i in insns if i.address == landing)
        assert (stock.mnemonic, int(stock.op_str, 16)) == ("jmp", CAN_MAKE_UNIT_ACCEPT)

    def test_it_has_exactly_four_exits_all_into_canmakeunit(self):
        exits = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "jmp"}
        assert exits == {
            CAN_MAKE_UNIT_NEXT_SLOT,
            CAN_MAKE_UNIT_BUMP_SLOT,
            CAN_MAKE_UNIT_UPGRADE_GATE,
            CAN_MAKE_UNIT_ACCEPT,
        }

    def test_every_conditional_branch_stays_inside_the_cave(self):
        """A displacement computed wrong would jump into arbitrary engine code."""
        code = build_code(BASE)
        lo, hi = BASE, BASE + len(code)
        for ins in disassemble():
            if not ins.mnemonic.startswith("j") or ins.mnemonic == "jmp":
                continue
            assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_its_exits_all_precede_the_scan_bound_commandset_limit_edits(self):
        """The composition claim in the module docstring, as an assertion: the cave depends on no
        byte `commandset-limit` rewrites."""
        exits = (
            CAN_MAKE_UNIT_NEXT_SLOT,
            CAN_MAKE_UNIT_BUMP_SLOT,
            CAN_MAKE_UNIT_UPGRADE_GATE,
            CAN_MAKE_UNIT_ACCEPT,
        )
        assert all(target < CAN_MAKE_UNIT_SCAN_BOUND for target in exits)

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b, "absolute jumps must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        AiReviveGatePatch().apply(data)
        assert AiReviveGatePatch().verify(data) == []

    def test_the_hook_is_a_jmp_to_the_cave_then_a_nop(self):
        data = synthetic_image()
        AiReviveGatePatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        site = bytes(data[off : off + len(HOOK_ORIGINAL)])
        assert site[0] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va
        # the displaced `jne` was 6 bytes; the 6th is padded so no half-instruction is left
        assert site[5] == 0x90

    def test_the_cave_holds_the_expected_code(self):
        data = synthetic_image()
        AiReviveGatePatch().apply(data)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + len(build_code(section_va))]) == build_code(section_va)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        data = synthetic_image()
        AiReviveGatePatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        AiReviveGatePatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            AiReviveGatePatch().apply(data)

    @pytest.mark.parametrize(
        "slot", [CAN_MAKE_UNIT_VTABLE_SLOT, CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT]
    )
    def test_refuses_a_build_whose_vtable_names_another_function(self, slot):
        """A hook on a revive branch nothing dispatches to installs perfectly and never fires;
        a return-address test naming a gate that is no longer at `+0x64` silently gates the
        player again. Both are indistinguishable from a working patch at rest."""
        data = synthetic_image()
        struct.pack_into(
            "<I", data, BUILD_ASSISTANT_VTABLE + slot - IMAGE_BASE, CAN_MAKE_UNIT + 0x20
        )
        with pytest.raises(ValueError, match="dispatches to"):
            AiReviveGatePatch().apply(data)

    @pytest.mark.parametrize("anchor", sorted(ANCHORS))
    def test_refuses_a_build_where_a_jump_target_moved(self, anchor):
        data = synthetic_image()
        data[anchor - IMAGE_BASE] ^= 0xFF
        with pytest.raises(ValueError, match="layout is not this build"):
            AiReviveGatePatch().apply(data)

    def test_refuses_an_unmapped_build(self):
        with pytest.raises(ValueError, match="not mapped"):
            AiReviveGatePatch().apply(_tiny_pe())


def _all_three():
    return (
        CommandSetLimitPatch(count=64),
        CahFactionsPatch(sides=["Rohan"]),
        AiReviveGatePatch(),
    )


def _image_for_all_three() -> bytearray:
    data = _cah_game_dat()
    _plant_commandset_sites(data)
    plant_sites(data)
    return data


class TestComposesWithTheOtherPatches:
    """`ai-revive-gate` and `commandset-limit` are the one bundled pair that edits the same
    engine function - the hook at 0x007950CE and the scan bound at 0x007950E2, 20 bytes apart.
    These tests hold the line that they still neither share a byte nor read each other's."""

    def test_the_edited_ranges_do_not_overlap(self):
        hook = range(HOOK_VA, HOOK_VA + len(HOOK_ORIGINAL))
        bound = range(CAN_MAKE_UNIT_SCAN_BOUND, CAN_MAKE_UNIT_SCAN_BOUND + 4)
        assert not set(hook) & set(bound)

    @pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
    def test_any_order_applies_and_verifies(self, order):
        data = _image_for_all_three()
        patches = _all_three()
        for i in order:
            patches[i].apply(data)
        for patch in _all_three():
            assert patch.verify(data) == [], f"{patch} failed in order {order}"

    @pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
    def test_any_order_keeps_the_section_table_rva_sorted(self, order):
        data = _image_for_all_three()
        patches = _all_three()
        for i in order:
            patches[i].apply(data)
        rvas = _section_rvas(data)
        assert rvas == sorted(rvas)

    def test_neither_edit_in_canmakeunit_depends_on_the_other(self):
        """The rule the framework cannot enforce (`Patch`'s composition contract, rule 3): a
        patch must not derive its output from bytes another patch rewrites. Whole-file
        byte-identity across orders is *not* the test of that - whichever patch runs first takes
        the lower cave RVA, so the caves and every pointer to them differ by design. What must
        agree is each patch's edit inside the shared function: the scan bound's bytes, and a hook
        that is a `jmp` to this image's own cave followed by the pad byte."""
        seen = []
        for order in ((0, 1), (1, 0)):
            data = _image_for_all_three()
            pair = (CommandSetLimitPatch(count=64), AiReviveGatePatch())
            for i in order:
                pair[i].apply(data)
            bound = CAN_MAKE_UNIT_SCAN_BOUND - IMAGE_BASE
            hook = va_to_offset(data, HOOK_VA)
            cave, _off, _vsize = find_section(data, SECTION_NAME)
            target = HOOK_VA + 5 + struct.unpack_from("<i", data, hook + 1)[0]
            seen.append(
                {
                    "scan bound": bytes(data[bound : bound + 4]),
                    "hook opcode": data[hook],
                    "hook reaches its own cave": target == cave,
                    "hook pad": data[hook + 5],
                }
            )
        assert seen[0] == seen[1]

    def test_the_scan_bound_and_the_hook_both_survive_the_pair(self):
        data = _image_for_all_three()
        for patch in (CommandSetLimitPatch(count=64), AiReviveGatePatch()):
            patch.apply(data)
        bound = CAN_MAKE_UNIT_SCAN_BOUND - IMAGE_BASE
        assert bytes(data[bound : bound + 4]) == b"\x83\x7d\xf8\x40"  # cmp [ebp-8], 64
        assert data[HOOK_VA - IMAGE_BASE] == 0xE9


class TestVerify:
    def test_rejects_an_unpatched_file(self):
        absent = [f"{SECTION_NAME} section is absent"]
        assert AiReviveGatePatch().verify(synthetic_image()) == absent

    def test_rejects_a_cave_whose_code_was_altered(self):
        data = synthetic_image()
        AiReviveGatePatch().apply(data)
        _va, off, _vsize = find_section(data, SECTION_NAME)
        data[off] ^= 0xFF
        assert AiReviveGatePatch().verify(data)

    def test_rejects_a_hook_pointing_somewhere_else(self):
        data = synthetic_image()
        AiReviveGatePatch().apply(data)
        off = va_to_offset(data, HOOK_VA)
        struct.pack_into("<i", data, off + 1, 0x100)
        assert any("hook jumps to" in p for p in AiReviveGatePatch().verify(data))
