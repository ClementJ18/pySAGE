"""Tests for the player-ai-type-reset patch.

The cave is hand-assembled x86 that cannot run here, so the tests disassemble it back and check
the calling conventions it depends on: an unbalanced stack or a wrong `this` does not raise, it
crashes the game at the next map load.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    ASCII_STRING_CTOR,
    FILE_SYSTEM,
    FILE_SYSTEM_DOES_FILE_EXIST,
    GAME_LOGIC_LOAD_MAP_INI_ENTRY,
    GAME_LOGIC_LOAD_MAP_INI_RESUME,
    INI_CTOR,
    INI_DTOR,
    INI_LOAD,
    INI_LOAD_CREATE_OVERRIDES,
    INI_OBJECT_SIZE,
)
from sage_patch.patches.player_ai_type_reset import (
    ANCHORS,
    GLOBAL_FILE,
    HOOK_VA,
    SECTION_NAME,
    PlayerAiTypeResetPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

BASE = 0x00F00000
IMAGE_BASE = 0x400000

#: What each engine function pops on return: `doesFileExist` and the `AsciiString` constructor
#: take one argument, `INI::load` three, the `INI` constructor and destructor none.
CALLEE_POPS = {
    FILE_SYSTEM_DOES_FILE_EXIST: 4,
    ASCII_STRING_CTOR: 4,
    INI_LOAD: 12,
    INI_CTOR: 0,
    INI_DTOR: 0,
}


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the hook and every anchor, with the stock bytes planted."""
    highest = max(HOOK_VA, *ANCHORS) - IMAGE_BASE + 0x100
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

    off = HOOK_VA - IMAGE_BASE
    data[off : off + len(GAME_LOGIC_LOAD_MAP_INI_ENTRY)] = GAME_LOGIC_LOAD_MAP_INI_ENTRY
    for va, expected in ANCHORS.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(expected)] = expected
    return data


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    code = build_code(base)
    return list(md.disasm(code[len(GLOBAL_FILE) :], base + len(GLOBAL_FILE)))


def target(ins) -> int:
    return int(ins.op_str, 16)


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE)) - len(GLOBAL_FILE)

    def test_the_path_leads_the_cave_and_is_terminated(self):
        assert build_code(BASE).startswith(GLOBAL_FILE)
        assert GLOBAL_FILE.endswith(b"\x00")

    def test_every_push_of_the_path_names_the_string(self):
        pushes = [i for i in disassemble() if i.mnemonic == "push" and i.operands[0].type == 2]
        imms = {i.operands[0].imm for i in pushes}
        assert BASE in imms
        assert imms <= {BASE, 0, INI_LOAD_CREATE_OVERRIDES}

    def test_the_file_system_is_loaded_from_its_global(self):
        insns = disassemble()
        call = next(i for i in insns if i.mnemonic == "call")
        assert target(call) == FILE_SYSTEM_DOES_FILE_EXIST
        load = insns[insns.index(call) - 1]
        assert load.op_str == f"ecx, dword ptr [{FILE_SYSTEM:#x}]"

    def test_it_calls_the_engine_in_order(self):
        calls = [target(i) for i in disassemble() if i.mnemonic == "call"]
        assert calls == [
            FILE_SYSTEM_DOES_FILE_EXIST,
            INI_CTOR,
            ASCII_STRING_CTOR,
            INI_LOAD,
            INI_DTOR,
        ]

    def test_ini_load_is_asked_for_an_override_pass_with_no_xfer(self):
        insns = disassemble()
        ini = next(i for i in insns if i.mnemonic == "call" and target(i) == INI_CTOR)
        after = insns[insns.index(ini) + 1 :]
        assert [(i.mnemonic, i.op_str) for i in after[:3]] == [
            ("push", "0"),
            ("push", str(INI_LOAD_CREATE_OVERRIDES)),
            ("push", "ecx"),
        ]

    def test_the_stack_is_balanced_and_every_this_is_the_ini_object(self):
        """Walk the cave tracking `esp` relative to the `INI` object: each call on the object must
        see `ecx` pointing at it, and the cave must leave with `esp` where it found it."""
        depth = 0  # bytes below the INI object; the object itself sits at depth 0
        reserved = False
        for ins in disassemble():
            m, ops = ins.mnemonic, ins.op_str
            if m == "pushal":
                continue
            if m == "sub" and ops == f"esp, {INI_OBJECT_SIZE:#x}":
                reserved = True
                continue
            if m == "add" and ops == f"esp, {INI_OBJECT_SIZE:#x}":
                assert depth == 0
                reserved = False
                continue
            if m == "push":
                depth += 4
            elif m == "mov" and ops == "ecx, esp":
                this_depth = depth
            elif m == "lea" and ops.startswith("ecx, [esp + "):
                this_depth = depth - int(ops.split("+ ")[1].rstrip("]"), 16)
            elif m == "call":
                callee = target(ins)
                if callee in (INI_CTOR, INI_LOAD, INI_DTOR):
                    assert this_depth == 0, f"{callee:#x} called on the wrong object"
                if callee == INI_LOAD:
                    assert depth == 12
                depth -= CALLEE_POPS[callee]
        assert depth == 0 and not reserved

    def test_a_missing_file_skips_to_the_epilogue(self):
        insns = disassemble()
        je = next(i for i in insns if i.mnemonic == "je")
        landing = next(i for i in insns if i.address == target(je))
        assert (landing.mnemonic, landing.op_str) == ("add", f"esp, {INI_OBJECT_SIZE:#x}")

    def test_it_replays_the_displaced_instruction_and_resumes(self):
        insns = disassemble()
        assert [i.mnemonic for i in insns[-4:-2]] == ["add", "popal"]
        assert bytes(insns[-2].bytes) == GAME_LOGIC_LOAD_MAP_INI_ENTRY
        assert (insns[-1].mnemonic, target(insns[-1])) == ("jmp", GAME_LOGIC_LOAD_MAP_INI_RESUME)

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        PlayerAiTypeResetPatch().apply(data)
        assert PlayerAiTypeResetPatch().verify(data) == []

    def test_the_hook_jumps_past_the_path_string(self):
        data = synthetic_image()
        PlayerAiTypeResetPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        assert data[off] == 0xE9
        dest = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert dest == section_va + len(GLOBAL_FILE)

    def test_an_unpatched_image_does_not_verify(self):
        assert PlayerAiTypeResetPatch().verify(synthetic_image()) != []

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        PlayerAiTypeResetPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            PlayerAiTypeResetPatch().apply(data)

    def test_refuses_a_build_whose_reset_does_something(self):
        data = synthetic_image()
        reset = next(va for va, b in ANCHORS.items() if b == b"\xc3")
        data[reset - IMAGE_BASE] = 0x55
        with pytest.raises(ValueError, match="expected"):
            PlayerAiTypeResetPatch().apply(data)

    def test_the_section_name_fits_the_pe_field(self):
        assert len(SECTION_NAME) <= 8

    def test_it_is_registered(self):
        assert PATCHES[PlayerAiTypeResetPatch.name] is PlayerAiTypeResetPatch
