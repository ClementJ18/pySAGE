"""Tests for the combo-horde recruitment patch.

The patch is one six-byte hook, so most of what can go wrong is about *which* six bytes and what
the cave computes from them. Three claims carry the whole thing and each is asserted from the
anchored bytes rather than restated in prose:

* the site is a `mov`/`mov` pair reading `Object::m_producerID` and nothing else, so replacing it
  with a `call` cannot swallow half of the `test`/`jne` that reads its result;
* the cave leaves ``eax`` holding exactly what the two replaced instructions would have, on every
  path except the one this patch exists to add; and
* what the gate skips really is the multi-payload fill, and what recruitment uses instead really
  is the single-payload getter — the two halves of the defect.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import apply_patches
from sage_patch.addresses import (
    HORDE_CONTAIN_CREATE_PAYLOAD_CALL,
    HORDE_CONTAIN_FULL_STRENGTH_INIT,
    HORDE_CONTAIN_ON_OBJECT_CREATED,
    HORDE_CONTAIN_PAYLOAD_NAME,
    HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST,
    HORDE_CONTAIN_PRODUCED_GATE,
    HORDE_CONTAIN_PRODUCED_GATE_BYTES,
    HORDE_CONTAIN_PRODUCED_GATE_TEST,
    MODULE_MODULE_DATA,
    MODULE_OWNING_OBJECT,
    OBJECT_PRODUCER_ID,
    PRODUCTION_HORDE_PAYLOAD_CALL,
    TRANSPORT_CONTAIN_CREATE_PAYLOAD,
    TRANSPORT_CONTAIN_INITIAL_PAYLOAD,
)
from sage_patch.patches.combo_horde_recruitment import (
    ANCHORS,
    SECTION_NAME,
    ComboHordeRecruitmentPatch,
    build_section,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000
CAVE_BASE = 0x1000000
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the gate and every anchor, with the real original bytes
    planted, so the whole apply + verify path runs without the copyrighted `game.dat`."""
    highest = max(HORDE_CONTAIN_PRODUCED_GATE, *ANCHORS) - IMAGE_BASE + 0x100
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
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    lo = HORDE_CONTAIN_PRODUCED_GATE - IMAGE_BASE
    data[lo : lo + len(HORDE_CONTAIN_PRODUCED_GATE_BYTES)] = HORDE_CONTAIN_PRODUCED_GATE_BYTES
    for va, expected in ANCHORS.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(expected)] = expected
    return data


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(code, base))


class TestTheSiteIsTheProducerRead:
    def test_the_replaced_bytes_are_two_whole_instructions(self):
        insns = disassemble(HORDE_CONTAIN_PRODUCED_GATE_BYTES, HORDE_CONTAIN_PRODUCED_GATE)
        assert [i.mnemonic for i in insns] == ["mov", "mov"]
        assert sum(i.size for i in insns) == len(HORDE_CONTAIN_PRODUCED_GATE_BYTES)

    def test_they_load_the_owning_object_then_its_producer_id(self):
        """Both offsets come from `addresses.py`, so the cave and this test cannot drift apart
        without one of them failing."""
        insns = disassemble(HORDE_CONTAIN_PRODUCED_GATE_BYTES, HORDE_CONTAIN_PRODUCED_GATE)
        assert insns[0].op_str == f"eax, dword ptr [esi + {MODULE_OWNING_OBJECT}]"
        assert insns[1].op_str == f"eax, dword ptr [eax + {OBJECT_PRODUCER_ID:#x}]"

    def test_they_contain_no_branch(self):
        """A `call` may only replace straight-line code: an inbound branch landing mid-window, or
        an outbound one leaving it, would not survive relocation into the cave."""
        insns = disassemble(HORDE_CONTAIN_PRODUCED_GATE_BYTES, HORDE_CONTAIN_PRODUCED_GATE)
        assert not any(i.mnemonic.startswith("j") or i.mnemonic == "call" for i in insns)

    def test_the_window_ends_exactly_where_the_branch_begins(self):
        """Contiguity is the whole reason the `test`/`jne` can be left stock and merely asserted:
        the hook is the same length, so the branch keeps its address."""
        end = HORDE_CONTAIN_PRODUCED_GATE + len(HORDE_CONTAIN_PRODUCED_GATE_BYTES)
        assert end == HORDE_CONTAIN_PRODUCED_GATE_TEST

    def test_the_branch_that_reads_it_tests_eax_and_skips_forward(self):
        insns = disassemble(
            ANCHORS[HORDE_CONTAIN_PRODUCED_GATE_TEST], HORDE_CONTAIN_PRODUCED_GATE_TEST
        )
        assert [i.mnemonic for i in insns] == ["test", "jne"]
        assert insns[0].op_str == "eax, eax"
        assert int(insns[1].op_str, 16) > HORDE_CONTAIN_PRODUCED_GATE_TEST

    def test_the_gate_sits_in_on_object_created_before_the_create_payload_call(self):
        assert (
            HORDE_CONTAIN_ON_OBJECT_CREATED
            < HORDE_CONTAIN_PRODUCED_GATE
            < HORDE_CONTAIN_CREATE_PAYLOAD_CALL
        )

    def test_falling_through_reaches_the_multi_payload_fill(self):
        """The claim the patch rests on: the call the gate skips is `createPayload`."""
        call = ANCHORS[HORDE_CONTAIN_CREATE_PAYLOAD_CALL]
        insns = disassemble(call, HORDE_CONTAIN_CREATE_PAYLOAD_CALL)
        assert insns[0].mnemonic == "call"
        assert int(insns[0].op_str, 16) == TRANSPORT_CONTAIN_CREATE_PAYLOAD

    def test_the_branch_target_is_past_the_call_it_skips(self):
        insns = disassemble(
            ANCHORS[HORDE_CONTAIN_PRODUCED_GATE_TEST], HORDE_CONTAIN_PRODUCED_GATE_TEST
        )
        assert int(insns[1].op_str, 16) > HORDE_CONTAIN_CREATE_PAYLOAD_CALL


class TestTheDefectItFixes:
    def test_the_getter_refuses_any_list_that_is_not_exactly_one_long(self):
        """`cmp esi, 1` / `jne` — two instructions, and the whole reason a combo horde cannot be
        recruited."""
        run = ANCHORS[HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST]
        insns = disassemble(run, HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST)
        assert [i.mnemonic for i in insns] == ["cmp", "jne"]
        assert insns[0].op_str == "esi, 1"

    def test_that_test_lives_inside_the_getter(self):
        assert HORDE_CONTAIN_PAYLOAD_NAME < HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST

    def test_the_getter_reaches_the_payload_list_through_the_module_data(self):
        """Its prologue is an adjustor thunk: the interface sub-object sits at ``module+0x11C``,
        so ``[ecx-0x118]`` is ``module+0x04``, the `ModuleData` — the same pointer the cave reads
        directly as ``[esi+4]``."""
        insns = disassemble(ANCHORS[HORDE_CONTAIN_PAYLOAD_NAME], HORDE_CONTAIN_PAYLOAD_NAME)
        adjusted = next(i for i in insns if i.op_str.startswith("edx, dword ptr [ecx -"))
        assert int(adjusted.op_str.rsplit("- ", 1)[1].rstrip("]"), 16) == 0x11C - MODULE_MODULE_DATA
        payload = next(i for i in insns if "0xa4" in i.op_str)
        assert payload.op_str == f"ecx, dword ptr [edx + {TRANSPORT_CONTAIN_INITIAL_PAYLOAD:#x}]"

    def test_recruitment_calls_it_through_the_interface_vtable(self):
        insns = disassemble(ANCHORS[PRODUCTION_HORDE_PAYLOAD_CALL], PRODUCTION_HORDE_PAYLOAD_CALL)
        assert insns[0].mnemonic == "call"
        assert insns[0].op_str == "dword ptr [eax + 0x24]"

    def test_the_strength_trim_the_patch_newly_exposes_destroys_nobody(self):
        """Falling through the gate runs a block that trims ``(100 - [this+0x2A8])%`` of the
        members. The constructor writes 100, so it is inert — asserted here because a produced
        horde has never run it."""
        insns = disassemble(
            ANCHORS[HORDE_CONTAIN_FULL_STRENGTH_INIT], HORDE_CONTAIN_FULL_STRENGTH_INIT
        )
        assert insns[0].mnemonic == "mov"
        assert insns[0].op_str == "dword ptr [esi + 0x2a8], 0x64"


class TestTheCave:
    def test_it_is_straight_line_code_ending_in_one_ret(self):
        insns = disassemble(build_section(CAVE_BASE), CAVE_BASE)
        assert insns[-1].mnemonic == "ret"
        assert insns[-1].op_str == ""
        assert sum(i.mnemonic == "ret" for i in insns) == 1

    def test_it_opens_with_the_two_instructions_it_replaced(self):
        """Byte-for-byte, so the "no producer" answer cannot drift from the stock one."""
        assert build_section(CAVE_BASE).startswith(HORDE_CONTAIN_PRODUCED_GATE_BYTES)

    def test_every_branch_in_it_targets_the_single_ret(self):
        code = build_section(CAVE_BASE)
        insns = disassemble(code, CAVE_BASE)
        ret = insns[-1].address
        jumps = [i for i in insns if i.mnemonic.startswith("j")]
        assert jumps, "the cave must be able to hand back the stock answer"
        assert {int(i.op_str, 16) for i in jumps} == {ret}
        assert all(i.mnemonic == "je" for i in jumps)

    def test_it_clobbers_only_eax_ecx_and_edx(self):
        """`esi` is the module and must survive; `ebx` and `edi` are still the caller's, because
        they are not pushed until after the branch."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        written: set[str] = set()
        for insn in md.disasm(build_section(CAVE_BASE), CAVE_BASE):
            if insn.mnemonic == "ret":  # its `esp` write is the return, not a clobber
                continue
            _read, write = insn.regs_access()
            written |= {insn.reg_name(r) for r in write}
        assert written <= {"eax", "ecx", "edx", "eflags"}
        assert "esi" not in written

    def test_it_touches_no_memory_but_the_module_the_object_and_the_list(self):
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        operands = []
        for insn in md.disasm(build_section(CAVE_BASE), CAVE_BASE):
            for op in insn.operands:
                if op.type == capstone.x86.X86_OP_MEM:
                    operands.append((insn.reg_name(op.mem.base), op.mem.disp))
        assert ("esi", MODULE_OWNING_OBJECT) in operands
        assert ("esi", MODULE_MODULE_DATA) in operands
        assert ("ecx", TRANSPORT_CONTAIN_INITIAL_PAYLOAD) in operands
        # every read is off esi (the module), or off a pointer the cave itself just loaded
        assert {base for base, _disp in operands} <= {"esi", "ecx", "eax", "edx"}

    def test_it_reads_the_list_head_then_two_links(self):
        """ "Two or more entries" is decided by two dereferences from the `std::list` sentinel, not
        by a counting loop — which is why the cave has no backward branch."""
        insns = disassemble(build_section(CAVE_BASE), CAVE_BASE)
        after_list = insns[insns.index(next(i for i in insns if "0xa4" in i.op_str)) + 1 :]
        derefs = [
            i for i in after_list if i.op_str in ("edx, dword ptr [ecx]", "edx, dword ptr [edx]")
        ]
        assert len(derefs) == 2
        assert all(int(i.op_str, 16) > i.address for i in insns if i.mnemonic.startswith("j"))

    def test_it_is_small_enough_for_short_branches(self):
        assert len(build_section(CAVE_BASE)) < 0x80

    def test_the_layout_does_not_depend_on_where_it_is_placed(self):
        """Nothing in the cave is position-dependent, so two bases give identical bytes — which is
        what lets `verify` recompute it from the section header alone."""
        assert build_section(CAVE_BASE) == build_section(CAVE_BASE + 0x10000)


class TestTheHook:
    def test_it_is_the_same_length_as_what_it_replaces(self):
        hook = ComboHordeRecruitmentPatch._hook_bytes(CAVE_BASE)
        assert len(hook) == len(HORDE_CONTAIN_PRODUCED_GATE_BYTES)

    def test_it_is_a_call_to_the_cave_then_one_nop(self):
        hook = ComboHordeRecruitmentPatch._hook_bytes(CAVE_BASE)
        insns = disassemble(hook, HORDE_CONTAIN_PRODUCED_GATE)
        assert [i.mnemonic for i in insns] == ["call", "nop"]
        assert int(insns[0].op_str, 16) == CAVE_BASE


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        ComboHordeRecruitmentPatch().apply(data)
        assert ComboHordeRecruitmentPatch().verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert ComboHordeRecruitmentPatch().verify(synthetic_image()) == [
            f"no {SECTION_NAME} section: the file does not carry this patch"
        ]

    def test_the_call_lands_on_the_section_it_allocated(self):
        data = synthetic_image()
        ComboHordeRecruitmentPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HORDE_CONTAIN_PRODUCED_GATE)
        target = HORDE_CONTAIN_PRODUCED_GATE + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert target == section_va

    def test_the_section_holds_the_cave(self):
        data = synthetic_image()
        ComboHordeRecruitmentPatch().apply(data)
        section_va, section_off, _vsize = find_section(data, SECTION_NAME)
        content = build_section(section_va)
        assert bytes(data[section_off : section_off + len(content)]) == content

    def test_it_rewrites_nothing_in_text_but_those_six_bytes(self):
        before = synthetic_image()
        data = synthetic_image()
        ComboHordeRecruitmentPatch().apply(data)
        off = va_to_offset(data, HORDE_CONTAIN_PRODUCED_GATE)
        text_end = len(before)
        changed = {i for i in range(0x1000, text_end) if data[i] != before[i]}
        assert changed <= set(range(off, off + len(HORDE_CONTAIN_PRODUCED_GATE_BYTES)))
        assert changed, "the hook has to be written somewhere"

    def test_the_branch_it_relies_on_survives(self):
        data = synthetic_image()
        ComboHordeRecruitmentPatch().apply(data)
        off = va_to_offset(data, HORDE_CONTAIN_PRODUCED_GATE_TEST)
        expected = ANCHORS[HORDE_CONTAIN_PRODUCED_GATE_TEST]
        assert bytes(data[off : off + len(expected)]) == expected

    def test_the_single_payload_getter_survives(self):
        """The patch fixes the defect by routing around the getter, not by editing it — a mod
        without the patch must still read the same bytes there."""
        data = synthetic_image()
        ComboHordeRecruitmentPatch().apply(data)
        off = va_to_offset(data, HORDE_CONTAIN_PAYLOAD_NAME)
        expected = ANCHORS[HORDE_CONTAIN_PAYLOAD_NAME]
        assert bytes(data[off : off + len(expected)]) == expected

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        ComboHordeRecruitmentPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            ComboHordeRecruitmentPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = synthetic_image()
        data[va - IMAGE_BASE : va - IMAGE_BASE + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            ComboHordeRecruitmentPatch().apply(data)

    def test_a_moved_anchor_leaves_the_gate_alone(self):
        """The anchors are checked before anything is written, so a refused apply is a no-op."""
        before = synthetic_image()
        data = synthetic_image()
        lo = HORDE_CONTAIN_PAYLOAD_NAME - IMAGE_BASE
        data[lo : lo + 2] = b"\x90\x90"
        with pytest.raises(ValueError):
            ComboHordeRecruitmentPatch().apply(data)
        off = va_to_offset(before, HORDE_CONTAIN_PRODUCED_GATE)
        end = off + len(HORDE_CONTAIN_PRODUCED_GATE_BYTES)
        assert data[off:end] == before[off:end]
        assert find_section(data, SECTION_NAME) is None


class TestRegistration:
    def test_it_is_registered_under_its_name(self):
        assert PATCHES[ComboHordeRecruitmentPatch.name] is ComboHordeRecruitmentPatch

    def test_it_is_not_experimental(self):
        assert not ComboHordeRecruitmentPatch.experimental

    def test_it_takes_no_parameters(self):
        assert ComboHordeRecruitmentPatch.from_cli_args(None) is not None


class TestTheRealBinary:
    """The synthetic image proves the patch is self-consistent; only a real `game.dat` proves the
    addresses are right. Skipped where there is none, which is every machine but the author's."""

    @staticmethod
    @pytest.fixture(scope="class")
    def game_dat() -> bytes:
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_what_the_patch_says_it_holds(self, game_dat: bytes) -> None:
        for va, expected in sorted(ANCHORS.items()):
            off = va_to_offset(game_dat, va)
            assert off is not None, f"0x{va:08X}"
            assert bytes(game_dat[off : off + len(expected)]) == expected, f"0x{va:08X}"

    def test_the_gate_holds_the_producer_read(self, game_dat: bytes) -> None:
        off = va_to_offset(game_dat, HORDE_CONTAIN_PRODUCED_GATE)
        got = bytes(game_dat[off : off + len(HORDE_CONTAIN_PRODUCED_GATE_BYTES)])
        assert got == HORDE_CONTAIN_PRODUCED_GATE_BYTES

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        out = apply_patches(src, [ComboHordeRecruitmentPatch()], tmp_path / "out.dat")
        data = out.read_bytes()
        assert ComboHordeRecruitmentPatch().verify(data) == []
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HORDE_CONTAIN_PRODUCED_GATE)
        target = HORDE_CONTAIN_PRODUCED_GATE + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert target == section_va
        assert src.read_bytes() == game_dat, "the input was modified"
