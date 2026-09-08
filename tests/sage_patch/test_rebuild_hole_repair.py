"""Tests for the rebuild-hole repair patch.

The patch has two edits and each fails silently in its own way. The gate is one erased branch, so
the tests that matter are about *which* branch: getting the wrong six bytes would not raise, it
would erase an unrelated test or leave half an instruction behind. The placement hook is
hand-assembled x86 that cannot be executed here, so the cave is disassembled back and read; and
its stolen run is eleven bytes ending in a `call`, so taking one byte too few would leave a half
`call` behind for the return jump to walk into.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    DIE_MODULE_IS_APPLICABLE,
    DIE_MUX_IS_APPLICABLE,
    OBJECT_GET_HEIGHT_ABOVE_TERRAIN,
    OBJECT_SET_POSITION,
    OBJECT_STATUS,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    REBUILD_HOLE_CONSTRUCTION_TEST,
    REBUILD_HOLE_ON_DIE,
    REBUILD_HOLE_SELF_KILL,
    REBUILD_HOLE_SET_POSITION_RESUME,
    REBUILD_HOLE_START_REBUILD,
    TERRAIN_LOGIC_GET_GROUND_HEIGHT_SLOT,
    THE_TERRAIN_LOGIC,
)
from sage_patch.patches.experimental.rebuild_hole_repair import (
    ANCHORS,
    COORD3D_SIZE,
    GATE_ORIGINAL,
    GATE_REPLACEMENT,
    GATE_VA,
    PLACEMENT_ORIGINAL,
    PLACEMENT_VA,
    SECTION_NAME,
    RebuildHoleRepairPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

BASE = 0x00F00000
IMAGE_BASE = 0x400000

#: Where the stock gate goes: `onDie`'s shared return, past every remaining instruction. Decoded
#: from the branch's own displacement rather than written down, so the "this is a rejection edge"
#: claim is derived from the bytes the patch asserts.
GATE_TARGET = GATE_VA + len(GATE_ORIGINAL) + struct.unpack("<i", GATE_ORIGINAL[2:6])[0]


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map both edits and every anchor, with the real original bytes
    planted, so the whole apply + verify path runs without the copyrighted `game.dat`."""
    highest = max(GATE_VA, PLACEMENT_VA, *ANCHORS) - IMAGE_BASE + 0x100
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

    for va, planted in (
        (GATE_VA, GATE_ORIGINAL),
        (PLACEMENT_VA, PLACEMENT_ORIGINAL),
        *ANCHORS.items(),
    ):
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(planted)] = planted
    return data


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(code, base))


def cave(base: int = BASE):
    return disassemble(build_code(base), base)


class TestTheGateSite:
    def test_the_erased_bytes_are_one_conditional_branch(self):
        insns = disassemble(GATE_ORIGINAL, GATE_VA)
        assert len(insns) == 1, "the site must be exactly one instruction, not a partial run"
        assert insns[0].mnemonic == "jne"
        assert insns[0].size == len(GATE_ORIGINAL)

    def test_it_branches_forward_out_of_the_function(self):
        """A rejection edge, not a loop back: erasing a branch that went *backwards* would be
        erasing something else entirely."""
        assert GATE_TARGET > GATE_VA
        assert int(disassemble(GATE_ORIGINAL, GATE_VA)[0].op_str, 16) == GATE_TARGET

    def test_what_it_tests_is_under_construction_on_the_dying_object(self):
        """The three instructions immediately before it isolate one bit of one bitset. Both
        numbers have to be right, and both come from `addresses.py` rather than from here."""
        run = ANCHORS[REBUILD_HOLE_CONSTRUCTION_TEST]
        insns = disassemble(run, REBUILD_HOLE_CONSTRUCTION_TEST)
        assert [i.mnemonic for i in insns] == ["mov", "shr", "test"]
        assert insns[0].op_str == f"eax, dword ptr [esi + {OBJECT_STATUS:#x}]"
        assert insns[1].op_str == f"eax, {OBJECT_STATUS_UNDER_CONSTRUCTION}"
        assert insns[2].op_str == "al, 1"

    def test_the_test_run_ends_exactly_where_the_gate_begins(self):
        """Contiguity is what makes the pair one anchored shape instead of two addresses that
        happen to be near each other."""
        run = ANCHORS[REBUILD_HOLE_CONSTRUCTION_TEST]
        assert REBUILD_HOLE_CONSTRUCTION_TEST + len(run) == GATE_VA

    def test_on_die_opens_with_the_shared_die_filter(self):
        """The `ExemptStatus` opt-out the patch's contract offers is only real if `onDie` runs
        the filter that reads it, so assert the call is in the prologue that is anchored."""
        insns = disassemble(ANCHORS[REBUILD_HOLE_ON_DIE], REBUILD_HOLE_ON_DIE)
        assert [i.mnemonic for i in insns[:4]] == ["push", "mov", "sub", "push"]

    def test_the_replacement_is_a_single_nop_that_falls_through(self):
        insns = disassemble(GATE_REPLACEMENT, GATE_VA)
        assert len(GATE_REPLACEMENT) == len(GATE_ORIGINAL)
        assert len(insns) == 1
        assert insns[0].mnemonic == "nop"
        assert insns[0].size == len(GATE_REPLACEMENT)
        assert not any(i.mnemonic.startswith("j") for i in insns)


class TestThePlacementSite:
    def test_the_stolen_run_is_whole_instructions(self):
        """Eleven bytes, four instructions, nothing left over - the failure this guards against
        is stealing ten and leaving the last byte of a `call` behind."""
        insns = disassemble(PLACEMENT_ORIGINAL, PLACEMENT_VA)
        assert [i.mnemonic for i in insns] == ["lea", "push", "mov", "call"]
        assert sum(i.size for i in insns) == len(PLACEMENT_ORIGINAL)

    def test_it_takes_the_dying_objects_position_and_gives_it_to_the_hole(self):
        insns = disassemble(PLACEMENT_ORIGINAL, PLACEMENT_VA)
        assert insns[0].op_str == "eax, [esi + 0x38]"  # the dying object's Coord3D
        assert insns[2].op_str == "ecx, edi"  # the hole, as `this`
        assert int(insns[3].op_str, 16) == OBJECT_SET_POSITION

    def test_the_run_ends_exactly_where_the_cave_returns(self):
        assert PLACEMENT_VA + len(PLACEMENT_ORIGINAL) == REBUILD_HOLE_SET_POSITION_RESUME

    def test_the_resume_point_is_on_dies_angle_copy(self):
        insns = disassemble(
            ANCHORS[REBUILD_HOLE_SET_POSITION_RESUME], REBUILD_HOLE_SET_POSITION_RESUME
        )
        assert insns[0].mnemonic == "fld"
        assert insns[0].op_str == "dword ptr [esi + 0x44]"

    def test_both_edits_sit_inside_on_die(self):
        assert REBUILD_HOLE_ON_DIE < GATE_VA < PLACEMENT_VA < REBUILD_HOLE_START_REBUILD

    def test_the_two_edits_do_not_overlap(self):
        gate = set(range(GATE_VA, GATE_VA + len(GATE_ORIGINAL)))
        placement = set(range(PLACEMENT_VA, PLACEMENT_VA + len(PLACEMENT_ORIGINAL)))
        assert not gate & placement


class TestTheTerrainAnchor:
    """`OBJECT_GET_HEIGHT_ABOVE_TERRAIN` is the whole reason the cave can assert what it calls:
    a `.data` global holds nothing until the game runs, so the global's *address* and the vtable
    slot are pinned through a function that uses both."""

    def anchor(self):
        return disassemble(
            ANCHORS[OBJECT_GET_HEIGHT_ABOVE_TERRAIN], OBJECT_GET_HEIGHT_ABOVE_TERRAIN
        )

    def test_it_loads_the_terrain_logic_the_cave_loads(self):
        assert self.anchor()[0].op_str == f"ecx, dword ptr [{THE_TERRAIN_LOGIC:#x}]"

    def test_it_calls_the_slot_the_cave_calls(self):
        calls = [i for i in self.anchor() if i.mnemonic == "call"]
        assert len(calls) == 1
        assert calls[0].op_str == f"dword ptr [eax + {TERRAIN_LOGIC_GET_GROUND_HEIGHT_SLOT:#x}]"

    def test_it_pushes_three_arguments_and_never_pops_them(self):
        """The calling convention the cave depends on: x, y and a NULL normal go on the stack and
        the callee cleans them, so the cave's `Coord3D` is back under `esp` when it stores z."""
        insns = self.anchor()
        assert sum(1 for i in insns if i.mnemonic == "push") == 3
        assert not any(i.mnemonic == "add" and i.op_str.startswith("esp") for i in insns)


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        insns = cave()
        assert insns, "capstone decoded nothing"
        assert insns[-1].address + insns[-1].size == BASE + len(build_code(BASE))

    def test_it_seeds_the_coord3d_with_the_stock_answer_before_asking_the_terrain(self):
        """The terrain lookup is skipped when there is no `TerrainLogic`, so all three floats have
        to be written first - otherwise that path places the hole at whatever the stack held."""
        insns = cave()
        writes = [i.op_str for i in insns if i.mnemonic == "mov" and i.op_str.startswith("dword")]
        assert writes[:3] == [
            "dword ptr [esp], eax",
            "dword ptr [esp + 4], eax",
            "dword ptr [esp + 8], eax",
        ]
        reads = [i.op_str for i in insns if i.mnemonic == "mov" and i.op_str.startswith("eax, ")]
        assert reads[:3] == [
            "eax, dword ptr [esi + 0x38]",
            "eax, dword ptr [esi + 0x3c]",
            "eax, dword ptr [esi + 0x40]",
        ]

    def test_it_asks_the_terrain_for_the_height_under_the_dying_objects_x_and_y(self):
        insns = cave()
        pushes = [i.op_str for i in insns if i.mnemonic == "push"]
        assert pushes[:3] == ["0", "dword ptr [esi + 0x3c]", "dword ptr [esi + 0x38]"]
        indirect = [i for i in insns if i.mnemonic == "call" and i.op_str.startswith("dword")]
        assert len(indirect) == 1
        assert indirect[0].op_str == f"dword ptr [eax + {TERRAIN_LOGIC_GET_GROUND_HEIGHT_SLOT:#x}]"

    def test_the_terrain_answer_lands_in_z_and_nowhere_else(self):
        """`fstp dword [esp+8]` - the third float of the `Coord3D`. Writing `[esp]` or `[esp+4]`
        instead would move the hole sideways, which no test of the height would catch."""
        stores = [i for i in cave() if i.mnemonic == "fstp"]
        assert len(stores) == 1
        assert stores[0].op_str == "dword ptr [esp + 8]"

    def test_a_missing_terrain_logic_keeps_the_stock_position(self):
        """The null check exists so the cave degrades to the engine's own behaviour rather than
        dereferencing an unloaded subsystem, so the branch must land on the placement, not past
        it and not on the lookup it is meant to skip."""
        insns = cave()
        branch = next(i for i in insns if i.mnemonic.startswith("j"))
        assert branch.mnemonic == "je"
        placement = next(i for i in insns if i.mnemonic == "mov" and i.op_str == "eax, esp")
        assert int(branch.op_str, 16) == placement.address

    def test_the_stack_is_balanced(self):
        """The `Coord3D` is the cave's own frame. Both calls clean their own arguments, so the
        one `sub` is undone by the one `add` and the return jump leaves `esp` where it found it."""
        insns = cave()
        subs = [i for i in insns if i.mnemonic == "sub" and i.op_str.startswith("esp")]
        adds = [i for i in insns if i.mnemonic == "add" and i.op_str.startswith("esp")]
        assert len(subs) == len(adds) == 1
        assert subs[0].op_str == adds[0].op_str == f"esp, {COORD3D_SIZE:#x}"

    def test_the_x87_stack_is_balanced(self):
        """One value is pushed by `getGroundHeight` and popped by the store. Leaving it on the
        x87 stack would corrupt the `fld` waiting at the resume point."""
        insns = cave()
        assert sum(1 for i in insns if i.mnemonic in {"fld", "fild"}) == 0
        assert sum(1 for i in insns if i.mnemonic in {"fstp", "fistp"}) == 1

    def test_it_places_the_hole_once_through_the_engines_own_setter(self):
        insns = cave()
        direct = [i for i in insns if i.mnemonic == "call" and not i.op_str.startswith("dword")]
        assert [int(i.op_str, 16) for i in direct] == [OBJECT_SET_POSITION]
        this = [i for i in insns if i.mnemonic == "mov" and i.op_str == "ecx, edi"]
        assert len(this) == 1, "the hole, not the dying object, is what gets positioned"

    def test_its_only_exit_is_back_into_on_die(self):
        jumps = [i for i in cave() if i.mnemonic == "jmp"]
        assert [int(i.op_str, 16) for i in jumps] == [REBUILD_HOLE_SET_POSITION_RESUME]

    def test_every_conditional_branch_stays_inside_the_cave(self):
        code = build_code(BASE)
        for insn in cave():
            if insn.mnemonic.startswith("j") and insn.mnemonic != "jmp":
                assert BASE <= int(insn.op_str, 16) < BASE + len(code)

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b, "the absolute call and the return jump must be recomputed"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        assert RebuildHoleRepairPatch().verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert RebuildHoleRepairPatch().verify(synthetic_image()) == [
            f"{SECTION_NAME} section is absent"
        ]

    def test_it_writes_the_nop_at_the_gate(self):
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        off = va_to_offset(data, GATE_VA)
        assert bytes(data[off : off + len(GATE_REPLACEMENT)]) == GATE_REPLACEMENT

    def test_the_placement_hook_is_a_jmp_to_the_cave_then_padding(self):
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, PLACEMENT_VA)
        site = bytes(data[off : off + len(PLACEMENT_ORIGINAL)])
        assert site[0] == 0xE9
        assert PLACEMENT_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va
        pad = disassemble(site[5:], PLACEMENT_VA + 5)
        assert [i.mnemonic for i in pad] == ["nop", "nop"]
        assert sum(i.size for i in pad) == len(PLACEMENT_ORIGINAL) - 5

    def test_the_cave_holds_the_expected_code(self):
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + len(build_code(section_va))]) == build_code(section_va)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None

    def test_it_touches_nothing_but_the_two_sites_and_the_new_section(self):
        before = synthetic_image()
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        gate = va_to_offset(data, GATE_VA)
        placement = va_to_offset(data, PLACEMENT_VA)
        header_end = 0x400  # the PE header, where a section entry is added
        changed = {i for i in range(header_end, len(before)) if data[i] != before[i]}
        allowed = set(range(gate, gate + len(GATE_ORIGINAL))) | set(
            range(placement, placement + len(PLACEMENT_ORIGINAL))
        )
        # a subset, not an equality: the gate branch and the nop that replaces it share their
        # last two bytes, so four of those six actually differ
        assert changed and changed <= allowed

    def test_the_neighbouring_rejections_survive(self):
        """`onDie`'s two other early-outs - the owning-player tests - are deliberately left
        stock, and they sit within 0x30 bytes of the gate."""
        before = synthetic_image()
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        lo = va_to_offset(data, REBUILD_HOLE_ON_DIE)
        hi = va_to_offset(data, GATE_VA)
        assert data[lo:hi] == before[lo:hi]

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        with pytest.raises(ValueError, match="not stock"):
            RebuildHoleRepairPatch().apply(data)

    @pytest.mark.parametrize(
        "va",
        [
            REBUILD_HOLE_ON_DIE,
            REBUILD_HOLE_CONSTRUCTION_TEST,
            REBUILD_HOLE_START_REBUILD,
            REBUILD_HOLE_SELF_KILL,
            DIE_MODULE_IS_APPLICABLE,
            DIE_MUX_IS_APPLICABLE,
            REBUILD_HOLE_SET_POSITION_RESUME,
            OBJECT_SET_POSITION,
            OBJECT_GET_HEIGHT_ABOVE_TERRAIN,
        ],
    )
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = synthetic_image()
        data[va - IMAGE_BASE : va - IMAGE_BASE + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            RebuildHoleRepairPatch().apply(data)

    def test_a_refused_apply_writes_nothing_at_all(self):
        """Both edits and the section allocation come after every check, so a build that fails
        one leaves no half-patched binary and no orphan section."""
        data = synthetic_image()
        before = bytes(data)
        off = REBUILD_HOLE_SELF_KILL - IMAGE_BASE
        data[off : off + 2] = b"\x90\x90"
        with pytest.raises(ValueError):
            RebuildHoleRepairPatch().apply(data)
        data[off : off + 2] = before[off : off + 2]
        assert bytes(data) == before
        assert find_section(data, SECTION_NAME) is None

    def test_a_second_apply_leaves_the_first_intact(self):
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        applied = bytes(data)
        with pytest.raises(ValueError):
            RebuildHoleRepairPatch().apply(data)
        assert bytes(data) == applied
        assert RebuildHoleRepairPatch().verify(data) == []


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[RebuildHoleRepairPatch.name] is RebuildHoleRepairPatch

    def test_detect_finds_it_only_once_applied(self):
        assert RebuildHoleRepairPatch.detect(synthetic_image()) is None
        data = synthetic_image()
        RebuildHoleRepairPatch().apply(data)
        assert isinstance(RebuildHoleRepairPatch.detect(data), RebuildHoleRepairPatch)

    def test_the_description_names_the_ini_opt_out(self):
        """The one thing a mod has to know to keep the stock behaviour for a given object."""
        assert "ExemptStatus" in RebuildHoleRepairPatch.description
