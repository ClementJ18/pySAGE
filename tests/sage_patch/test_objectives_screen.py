"""Tests for the objectives-screen patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble
it back and assert it says what it was meant to say. It answers a question whose two edges lead to
*different screens*, so an encoding slip does not crash - it silently opens the wrong one, which is
exactly the failure this patch exists to fix.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY,
    MISSION_OBJECTIVE_LIST_OFFSET,
    MISSION_OBJECTIVE_TRACKER,
)
from sage_patch.patches.objectives_screen import (
    ANCHORS,
    HOOKS,
    OBJECTIVE_ENTRY_SIZE,
    SECTION_NAME,
    ObjectivesScreenPatch,
    build_code,
)
from sage_patch.utils import find_section, va_to_offset

BASE = 0x00F00000
IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map every hook site and every anchor, with the real original
    bytes planted, so the whole apply + verify path runs without the copyrighted `game.dat`."""
    highest = max(*HOOKS, *ANCHORS) - IMAGE_BASE + 0x100
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
    """The clean bytes the patch asserts before writing."""
    for va, expected in {**HOOKS, **ANCHORS}.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(expected)] = expected


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

    def test_it_preserves_ecx_on_every_path(self):
        """`ecx` is the stock predicate's `this`, and the fallback edge hands it straight on. A
        push without a matching pop on some edge would also corrupt the return address."""
        insns = disassemble()
        pushes = [i for i in insns if i.mnemonic == "push" and i.op_str == "ecx"]
        pops = [i for i in insns if i.mnemonic == "pop" and i.op_str == "ecx"]
        assert len(pushes) == 1, "ecx should be saved once, on entry"
        assert len(pops) == 2, "and restored on both the objectives edge and the fallback edge"
        assert pushes[0].address < min(p.address for p in pops)

    def test_it_reads_the_objective_list_off_the_tracker(self):
        ops = [(i.mnemonic, i.op_str) for i in disassemble()]
        assert ("mov", f"eax, dword ptr [{MISSION_OBJECTIVE_TRACKER:#x}]") in ops
        assert ("mov", f"eax, dword ptr [eax + {MISSION_OBJECTIVE_LIST_OFFSET:#x}]") in ops

    def test_it_measures_the_list_the_way_the_hud_does(self):
        """`end - begin` over the vector at +0x04/+0x08, against one entry's worth of bytes."""
        ops = [(i.mnemonic, i.op_str) for i in disassemble()]
        assert ("mov", "edx, dword ptr [eax + 8]") in ops
        assert ("sub", "edx, dword ptr [eax + 4]") in ops
        # capstone renders small immediates bare, so accept either spelling
        assert any(
            m == "cmp" and o in (f"edx, {OBJECTIVE_ENTRY_SIZE}", f"edx, {OBJECTIVE_ENTRY_SIZE:#x}")
            for m, o in ops
        )

    def test_the_objectives_edge_returns_false(self):
        """`al == 0` is the edge that opens Objectives.apt. Returning anything else would open
        the player list, which is the bug."""
        insns = disassemble()
        ret = next(i for i in insns if i.mnemonic == "ret")
        before = [i for i in insns if i.address < ret.address]
        assert (before[-1].mnemonic, before[-1].op_str) == ("xor", "eax, eax")

    def test_the_fallback_tail_calls_the_stock_predicate(self):
        """A map with no objectives must be indistinguishable from stock, so the fallback jumps -
        it does not call - leaving the predicate's own `ret` to return to the game."""
        insns = disassemble()
        jmp = next(i for i in insns if i.mnemonic == "jmp")
        assert int(jmp.op_str, 16) == IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY
        assert jmp is insns[-1], "the tail call is the last instruction"
        assert not any(i.mnemonic == "call" for i in insns), "the cave calls nothing"

    def test_every_failure_edge_reaches_the_fallback(self):
        """Three guards - no tracker, no list, an empty list - and all of them must land on the
        same label. A mis-sized branch would fall into the objectives edge instead."""
        insns = disassemble()
        fallback = next(i for i in insns if i.mnemonic == "jmp").address
        # the pop ecx that precedes the tail call
        entry = max(i.address for i in insns if i.mnemonic == "pop" and i.address < fallback)
        conditional = [i for i in insns if i.mnemonic in ("je", "jb")]
        assert len(conditional) == 3
        assert all(int(i.op_str, 16) == entry for i in conditional)


class TestApply:
    def test_it_redirects_every_call_into_its_cave(self):
        """All three sites, not just the inner one: the button and the hotkey each ask the stock
        predicate *before* the handler holding the inner call is reached, so leaving either outer
        site alone leaves the click on the tribute screen."""
        data = synthetic_image()
        ObjectivesScreenPatch().apply(data)
        section = find_section(data, SECTION_NAME)
        assert section is not None
        base_va, _, size = section
        assert len(HOOKS) == 3
        for va in HOOKS:
            off = va_to_offset(data, va)
            assert off is not None
            found = bytes(data[off : off + 5])
            assert found[:1] == b"\xe8"
            target = va + 5 + struct.unpack_from("<i", found, 1)[0]
            assert base_va <= target < base_va + size

    def test_a_half_applied_file_does_not_verify(self):
        """One site restored is the shipped-then-broken state this patch was widened to fix."""
        data = synthetic_image()
        ObjectivesScreenPatch().apply(data)
        for va, original in HOOKS.items():
            half = bytearray(data)
            off = va_to_offset(half, va)
            assert off is not None
            half[off : off + len(original)] = original
            assert ObjectivesScreenPatch().verify(half) != []

    def test_it_verifies_after_applying(self):
        data = synthetic_image()
        ObjectivesScreenPatch().apply(data)
        assert ObjectivesScreenPatch().verify(data) == []

    def test_a_clean_image_does_not_verify(self):
        assert ObjectivesScreenPatch().verify(synthetic_image()) != []

    def test_it_refuses_an_image_whose_branch_moved(self):
        """The two screen pushes are the proof this is the right branch. Corrupt one and the
        patch must refuse rather than redirect an unrelated call."""
        data = synthetic_image()
        va = next(iter(ANCHORS))
        data[va - IMAGE_BASE] ^= 0xFF
        with pytest.raises(ValueError, match="screen choice is not laid out"):
            ObjectivesScreenPatch().apply(data)

    def test_it_refuses_to_apply_twice(self):
        data = synthetic_image()
        ObjectivesScreenPatch().apply(data)
        with pytest.raises(ValueError):
            ObjectivesScreenPatch().apply(data)
