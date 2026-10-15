"""Tests for `save-temp-file`: the cave read back as text, and the patch applied.

`test_save_temp_file_emulated.py` runs the cave; this file pins where it goes - the open hook stays
a `call`, the three close hooks become `jmp`s back to the instruction after the close, and the
Win32 calls go through the import slots the real image binds to those names.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    DELETE_FILE_W_IAT,
    GAME_STATE_SAVE_CATCH_CLOSE_RESUME,
    GAME_STATE_SAVE_CLOSE_BYTES,
    GAME_STATE_SAVE_DONE_CLOSE_RESUME,
    GAME_STATE_SAVE_GAME,
    GAME_STATE_SAVE_OPEN_CALL,
    GAME_STATE_SAVE_OPEN_CATCH_RESUME,
    GET_MODULE_HANDLE_A_IAT,
    GET_PROC_ADDRESS_IAT,
    LOCAL_FILE_SYSTEM_OPEN_WIDE,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.save_temp_file import (
    ANCHORS,
    CODE_OFFSET,
    HOOKS,
    SECTION_NAME,
    SaveTempFilePatch,
    build_section,
    entry_points,
)
from sage_patch.patches.score_keeper_dangling_keys import ScoreKeeperDanglingKeysPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import save_temp_file_image

BASE = 0x00F00000
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
#: `GameState::saveGame` runs from its `EH_PROLOG` to the end of its last catch funclet's tail.
_SAVE_GAME_END = 0x006DE8F1


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    code = build_section(base)[CODE_OFFSET:]
    return list(md.disasm(code, base + CODE_OFFSET))


def _target(ins) -> int | None:
    return int(ins.op_str, 16) if ins.op_str.startswith("0x") else None


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self) -> None:
        assert sum(i.size for i in disassemble()) == len(build_section(BASE)) - CODE_OFFSET

    def test_it_leaves_only_for_the_open_and_the_three_resume_points(self) -> None:
        lo, hi = BASE, BASE + len(build_section(BASE))
        exits = {
            _target(i)
            for i in disassemble()
            if i.mnemonic in ("jmp", "call") and _target(i) and not lo <= _target(i) < hi
        }
        assert exits == {
            LOCAL_FILE_SYSTEM_OPEN_WIDE,
            GAME_STATE_SAVE_DONE_CLOSE_RESUME,
            GAME_STATE_SAVE_CATCH_CLOSE_RESUME,
            GAME_STATE_SAVE_OPEN_CATCH_RESUME,
        }

    def test_the_win32_calls_go_through_the_three_import_slots(self) -> None:
        slots = {
            int(i.op_str.split("[")[1].rstrip("]"), 16)
            for i in disassemble()
            if i.mnemonic == "call" and i.op_str.startswith("dword ptr [0x")
        }
        assert slots == {GET_MODULE_HANDLE_A_IAT, GET_PROC_ADDRESS_IAT, DELETE_FILE_W_IAT}

    def test_each_close_hook_replays_the_close_it_displaced(self) -> None:
        code = build_section(BASE)
        for routine in ("done", "abort", "open_abort"):
            at = entry_points(BASE)[routine] - BASE
            assert code[at : at + len(GAME_STATE_SAVE_CLOSE_BYTES)] == GAME_STATE_SAVE_CLOSE_BYTES

    def test_every_conditional_branch_stays_inside_the_cave(self) -> None:
        lo, hi = BASE, BASE + len(build_section(BASE))
        for ins in disassemble():
            if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
                assert lo <= int(ins.op_str, 16) < hi

    def test_it_relocates_with_its_section(self) -> None:
        assert build_section(BASE) != build_section(BASE + 0x1000)


class TestApply:
    def test_apply_then_verify(self) -> None:
        data = save_temp_file_image()
        SaveTempFilePatch().apply(data)
        assert SaveTempFilePatch().verify(data) == []
        assert SaveTempFilePatch.detect(data) is not None

    def test_the_open_stays_a_call_and_the_closes_become_jumps(self) -> None:
        data = save_temp_file_image()
        SaveTempFilePatch().apply(data)
        section_va, _off, _size = find_section(data, SECTION_NAME)
        entries = entry_points(section_va)
        for va, stock, routine, how in HOOKS:
            off = va_to_offset(data, va)
            site = bytes(data[off : off + len(stock)])
            assert site[0] == (0xE8 if how == "call" else 0xE9)
            assert va + 5 + struct.unpack_from("<i", site, 1)[0] == entries[routine]
            assert site[5:] == b"\x90" * (len(stock) - 5)
        assert next(h for h in HOOKS if h[0] == GAME_STATE_SAVE_OPEN_CALL)[3] == "call"

    def test_refuses_to_apply_twice(self) -> None:
        data = save_temp_file_image()
        SaveTempFilePatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            SaveTempFilePatch().apply(data)

    def test_a_moved_anchor_refuses_to_apply(self) -> None:
        data = save_temp_file_image()
        off = va_to_offset(data, LOCAL_FILE_SYSTEM_OPEN_WIDE)
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not this build's"):
            SaveTempFilePatch().apply(data)

    def test_the_section_name_survives_the_eight_byte_pe_field(self) -> None:
        assert len(SECTION_NAME) <= 8


class TestRegistration:
    def test_it_is_offered_on_the_cli(self) -> None:
        assert PATCHES[SaveTempFilePatch.name] is SaveTempFilePatch

    def test_it_declares_no_parameters(self) -> None:
        assert SaveTempFilePatch().options() == {}


class TestTheRealBinary:
    @staticmethod
    @pytest.fixture(scope="class")
    def game_dat() -> bytes:
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        return _GAME_DAT.read_bytes()

    def test_every_window_and_anchor_holds_the_stock_bytes(self, game_dat: bytes) -> None:
        for va, expected in [*((va, stock) for va, stock, _r, _h in HOOKS), *ANCHORS.items()]:
            off = va_to_offset(game_dat, va)
            assert bytes(game_dat[off : off + len(expected)]) == expected, f"{va:#010x}"

    def test_the_open_call_reaches_the_wide_open(self, game_dat: bytes) -> None:
        off = va_to_offset(game_dat, GAME_STATE_SAVE_OPEN_CALL)
        target = GAME_STATE_SAVE_OPEN_CALL + 5 + struct.unpack_from("<i", game_dat, off + 1)[0]
        assert target == LOCAL_FILE_SYSTEM_OPEN_WIDE

    def test_the_import_slots_are_the_functions_the_cave_calls(self, game_dat: bytes) -> None:
        pefile = pytest.importorskip("pefile")
        pe = pefile.PE(data=game_dat)
        names = {
            imp.address: imp.name.decode()
            for entry in pe.DIRECTORY_ENTRY_IMPORT
            for imp in entry.imports
            if imp.name
        }
        assert names[GET_MODULE_HANDLE_A_IAT] == "GetModuleHandleA"
        assert names[GET_PROC_ADDRESS_IAT] == "GetProcAddress"
        assert names[DELETE_FILE_W_IAT] == "DeleteFileW"
        assert "MoveFileExW" not in names.values(), "resolved at run time because it is absent"

    def test_nothing_branches_into_a_window(self, game_dat: bytes) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        interiors = {b for va, stock, _r, _h in HOOKS for b in range(va + 1, va + len(stock))}
        off = va_to_offset(game_dat, GAME_STATE_SAVE_GAME)
        body = game_dat[off : off + _SAVE_GAME_END - GAME_STATE_SAVE_GAME]
        starts = set()
        for ins in md.disasm(body, GAME_STATE_SAVE_GAME):
            starts.add(ins.address)
            if ins.mnemonic.startswith(("j", "call")):
                assert _target(ins) not in interiors, f"{ins.address:#010x} splits a window"
        for va, _stock, _r, _h in HOOKS:
            assert va in starts, f"{va:#010x} is not an instruction boundary"

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        out = apply_patches(src, [SaveTempFilePatch()], tmp_path / "out.dat")
        data = out.read_bytes()
        assert SaveTempFilePatch().verify(data) == []
        assert SaveTempFilePatch.detect(data) is not None
        assert SaveTempFilePatch.detect(game_dat) is None

    def test_it_composes_with_the_score_keeper_patch(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        for order in (
            [SaveTempFilePatch(), ScoreKeeperDanglingKeysPatch()],
            [ScoreKeeperDanglingKeysPatch(), SaveTempFilePatch()],
        ):
            data = apply_patches(src, order, tmp_path / "both.dat").read_bytes()
            assert SaveTempFilePatch().verify(data) == []
            assert ScoreKeeperDanglingKeysPatch().verify(data) == []
