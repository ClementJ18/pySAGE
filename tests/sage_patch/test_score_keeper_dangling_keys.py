"""Tests for `score-keeper-dangling-keys`: the cave read back as text, and the patch applied.

`test_score_keeper_dangling_keys_emulated.py` executes it; this file pins what it says and where it
goes - every exit is an anchored engine address, every window is replaced whole, and the patch
applies, verifies and refuses exactly as the framework expects.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT,
    LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME,
    STD_MAP_ITERATOR_INCREMENT,
    THE_THING_FACTORY,
    XFER_OBJECT_COUNT_MAP,
    XFER_OBJECT_COUNT_MAP_COUNT_RESUME,
    XFER_OBJECT_COUNT_MAP_DONE,
    XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME,
    XFER_OBJECT_COUNT_MAP_LOAD_NEXT,
    XFER_OBJECT_COUNT_MAP_NEXT,
    XFER_OBJECT_COUNT_MAP_UNKNOWN_BRANCH,
    XFER_OBJECT_COUNT_MAP_UNKNOWN_THROW,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.score_keeper_dangling_keys import (
    ANCHORS,
    HOOKS,
    SECTION_NAME,
    ScoreKeeperDanglingKeysPatch,
    build_code,
    entry_points,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import score_keeper_dangling_keys_image

BASE = 0x00F00000
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: The functions the windows sit in, as `(start, end)`: the merge (`0x008F3308` to its `ret` at
#: `0x008F339F`) and `xferObjectCountMap` (to the `int3` after its throw at `0x009618B9`).
_FUNCTIONS = ((0x008F3308, 0x008F33A0), (XFER_OBJECT_COUNT_MAP, 0x009618BA))


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_code(base), base))


def _target(ins) -> int | None:
    return int(ins.op_str, 16) if ins.op_str.startswith("0x") else None


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self) -> None:
        assert sum(i.size for i in disassemble()) == len(build_code(BASE))

    def test_every_exit_is_an_anchored_engine_address(self) -> None:
        """Each routine leaves by a `jmp` to code the patch has checked is there."""
        lo, hi = BASE, BASE + len(build_code(BASE))
        exits = {
            _target(i)
            for i in disassemble()
            if i.mnemonic == "jmp" and not lo <= (_target(i) or lo) < hi
        }
        assert exits == {
            LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME,
            LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT,
            XFER_OBJECT_COUNT_MAP_COUNT_RESUME,
            XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME,
            XFER_OBJECT_COUNT_MAP_NEXT,
            XFER_OBJECT_COUNT_MAP_DONE,
            XFER_OBJECT_COUNT_MAP_LOAD_NEXT,
        }
        assert exits <= set(ANCHORS)

    def test_the_only_engine_call_is_the_map_iterator(self) -> None:
        lo, hi = BASE, BASE + len(build_code(BASE))
        outside = {
            _target(i)
            for i in disassemble()
            if i.mnemonic == "call" and _target(i) is not None and not lo <= _target(i) < hi
        }
        assert outside == {STD_MAP_ITERATOR_INCREMENT}

    def test_every_conditional_branch_stays_inside_the_cave(self) -> None:
        lo, hi = BASE, BASE + len(build_code(BASE))
        for ins in disassemble():
            if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
                assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x}"

    def test_is_live_reads_the_factory_and_never_the_key(self) -> None:
        """The key is compared, never dereferenced: no memory operand in `is_live` uses `eax`."""
        start = entry_points(BASE)["is_live"]
        body = [i for i in disassemble() if i.address >= start]
        assert any(f"{THE_THING_FACTORY:#x}" in i.op_str for i in body)
        for ins in body:
            assert "[eax" not in ins.op_str, f"{ins.mnemonic} {ins.op_str} reads through the key"

    def test_each_hook_reaches_its_routine(self) -> None:
        entries = entry_points(BASE)
        assert {routine for _va, _stock, routine in HOOKS} <= set(entries)

    def test_it_relocates_with_its_section(self) -> None:
        assert build_code(BASE) != build_code(BASE + 0x1000)
        assert len(build_code(BASE)) == len(build_code(BASE + 0x1000))


class TestApply:
    def test_apply_then_verify(self) -> None:
        data = score_keeper_dangling_keys_image()
        ScoreKeeperDanglingKeysPatch().apply(data)
        assert ScoreKeeperDanglingKeysPatch().verify(data) == []
        assert ScoreKeeperDanglingKeysPatch.detect(data) is not None

    def test_each_window_becomes_one_jmp_into_the_cave(self) -> None:
        data = score_keeper_dangling_keys_image()
        ScoreKeeperDanglingKeysPatch().apply(data)
        section_va, _off, _size = find_section(data, SECTION_NAME)
        entries = entry_points(section_va)
        for va, stock, routine in HOOKS:
            off = va_to_offset(data, va)
            site = bytes(data[off : off + len(stock)])
            assert site[0] == 0xE9
            assert va + 5 + struct.unpack_from("<i", site, 1)[0] == entries[routine]
            assert site[5:] == b"\x90" * (len(stock) - 5)

    def test_refuses_to_apply_twice(self) -> None:
        data = score_keeper_dangling_keys_image()
        ScoreKeeperDanglingKeysPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            ScoreKeeperDanglingKeysPatch().apply(data)

    def test_a_moved_anchor_refuses_to_apply(self) -> None:
        data = score_keeper_dangling_keys_image()
        off = va_to_offset(data, XFER_OBJECT_COUNT_MAP_DONE)
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not this build's"):
            ScoreKeeperDanglingKeysPatch().apply(data)

    def test_it_does_not_touch_the_sites_the_cave_returns_into(self) -> None:
        before = score_keeper_dangling_keys_image()
        data = score_keeper_dangling_keys_image()
        ScoreKeeperDanglingKeysPatch().apply(data)
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            assert bytes(data[off : off + len(expected)]) == expected
            assert data[off : off + len(expected)] == before[off : off + len(expected)]

    def test_the_windows_do_not_overlap_the_anchors(self) -> None:
        windows = {b for va, stock, _r in HOOKS for b in range(va, va + len(stock))}
        anchored = {b for va, stock in ANCHORS.items() for b in range(va, va + len(stock))}
        assert not windows & anchored

    def test_the_section_name_survives_the_eight_byte_pe_field(self) -> None:
        assert len(SECTION_NAME) <= 8


class TestRegistration:
    def test_it_is_offered_on_the_cli(self) -> None:
        assert PATCHES[ScoreKeeperDanglingKeysPatch.name] is ScoreKeeperDanglingKeysPatch

    def test_it_declares_no_parameters(self) -> None:
        assert ScoreKeeperDanglingKeysPatch().options() == {}

    def test_it_is_not_experimental(self) -> None:
        assert not ScoreKeeperDanglingKeysPatch().experimental


class TestTheRealBinary:
    @staticmethod
    @pytest.fixture(scope="class")
    def game_dat() -> bytes:
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        return _GAME_DAT.read_bytes()

    def test_every_window_and_anchor_holds_the_stock_bytes(self, game_dat: bytes) -> None:
        for va, expected in [*((va, stock) for va, stock, _r in HOOKS), *ANCHORS.items()]:
            off = va_to_offset(game_dat, va)
            assert bytes(game_dat[off : off + len(expected)]) == expected, f"{va:#010x}"

    def test_nothing_branches_into_a_window(self, game_dat: bytes) -> None:
        """Each window is taken whole, so an inbound branch to an interior byte would land
        mid-`jmp`. Swept, by a linear disassembly, over both functions the windows sit in."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        interiors = {b for va, stock, _r in HOOKS for b in range(va + 1, va + len(stock))}
        starts: set[int] = set()
        for start, end in _FUNCTIONS:
            off = va_to_offset(game_dat, start)
            for ins in md.disasm(game_dat[off : off + end - start], start):
                starts.add(ins.address)
                if ins.mnemonic.startswith(("j", "call")):
                    assert _target(ins) not in interiors, f"{ins.address:#010x} splits a window"
        for va, _stock, _r in HOOKS:
            assert va in starts, f"{va:#010x} is not an instruction boundary"

    def test_the_load_hook_replaces_a_block_only_the_unknown_branch_reaches(
        self, game_dat: bytes
    ) -> None:
        off = va_to_offset(game_dat, XFER_OBJECT_COUNT_MAP_UNKNOWN_BRANCH)
        branch = game_dat[off : off + 2]
        assert branch[0] == 0x74
        assert XFER_OBJECT_COUNT_MAP_UNKNOWN_BRANCH + 2 + branch[1] == (
            XFER_OBJECT_COUNT_MAP_UNKNOWN_THROW
        )

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        out = apply_patches(src, [ScoreKeeperDanglingKeysPatch()], tmp_path / "out.dat")
        data = out.read_bytes()
        assert ScoreKeeperDanglingKeysPatch().verify(data) == []
        assert ScoreKeeperDanglingKeysPatch.detect(data) is not None
        assert src.read_bytes() == game_dat, "the input was modified"

    def test_it_is_not_detected_in_the_unpatched_binary(self, game_dat: bytes) -> None:
        assert ScoreKeeperDanglingKeysPatch.detect(game_dat) is None
