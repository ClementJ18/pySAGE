"""Tests for the multi-execute-cooldown patch.

Four `call rel32` redirects and one cave. What could be wrong without raising is the reading
behind them, so the stock windows are disassembled: each site is a call to the routine the cave
stands in for, both `isReady` calls sit inside the anchored `doCommand` gate, and a refusal there
drops the click. The cave is read back for the contract; `..._emulated.py` runs it.
"""

from __future__ import annotations

import pytest

from sage_patch.addresses import (
    COMMAND_BUTTON_IS_READY,
    COMMAND_BUTTON_OPTION_MULTI_EXECUTE,
    CONTROL_BAR_DO_COMMAND_MULTI_READY_CALL,
    CONTROL_BAR_DO_COMMAND_READY_CALL,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE_BYTES,
    CONTROL_BAR_GET_COMMAND_AVAILABILITY,
    CONTROL_BAR_MULTI_USABLE_CLEAR_CALL,
    CONTROL_BAR_MULTI_USABLE_PASS,
    CONTROL_BAR_MULTI_USABLE_PASS_BYTES,
    THE_IN_GAME_UI,
    WINDOW_CLEAR_STATUS,
)
from sage_patch.patches.multi_execute_cooldown import (
    ANCHORS,
    AVAILABILITY_SITES,
    READY_SITES,
    SECTION_NAME,
    USABLE_SITES,
    MultiExecuteCooldownPatch,
    build_section,
    layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.synthetic import multi_execute_cooldown_image

BASE = 0x00F00000
GATE = CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE
GATE_BYTES = CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE_BYTES
#: Where `doCommand` lands when it drops a click, and where it posts the command.
DROP = 0x00940642
DO_IT = 0x00940656


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def ops(code: bytes, base: int) -> list[tuple[str, str]]:
    return [(i.mnemonic, i.op_str) for i in disassemble(code, base)]


def routine(name: str) -> list[tuple[str, str]]:
    at = layout(BASE)
    section = build_section(BASE)
    start = at[name]
    end = next((v for v in sorted(at.values()) if v > start), BASE + len(section))
    return ops(section[start - BASE : end - BASE], start)


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


@pytest.fixture
def patched() -> bytearray:
    data = multi_execute_cooldown_image()
    MultiExecuteCooldownPatch().apply(data)
    return data


class TestTheStockSites:
    @pytest.mark.parametrize("va", sorted(AVAILABILITY_SITES))
    def test_the_paint_sites_call_the_availability_evaluator(self, va: int):
        assert ops(AVAILABILITY_SITES[va], va) == [
            ("call", hex(CONTROL_BAR_GET_COMMAND_AVAILABILITY))
        ]

    @pytest.mark.parametrize("va", sorted(READY_SITES))
    def test_the_click_sites_call_is_ready(self, va: int):
        assert ops(READY_SITES[va], va) == [("call", hex(COMMAND_BUTTON_IS_READY))]

    def test_both_ready_calls_sit_in_the_gate_and_a_refusal_drops_the_click(self):
        gate = disassemble(
            CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE_BYTES,
            CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE,
        )
        by_va = {i.address: n for n, i in enumerate(gate)}
        for va in (CONTROL_BAR_DO_COMMAND_READY_CALL, CONTROL_BAR_DO_COMMAND_MULTI_READY_CALL):
            n = by_va[va]
            assert (gate[n].mnemonic, int(gate[n].op_str, 16)) == ("call", COMMAND_BUTTON_IS_READY)
            assert (gate[n + 1].mnemonic, gate[n + 1].op_str) == ("test", "al, al")
        single = by_va[CONTROL_BAR_DO_COMMAND_READY_CALL]
        assert (gate[single + 2].mnemonic, int(gate[single + 2].op_str, 16)) == ("jne", DO_IT)
        assert (gate[single + 3].mnemonic, int(gate[single + 3].op_str, 16)) == ("jmp", DROP)
        multi = by_va[CONTROL_BAR_DO_COMMAND_MULTI_READY_CALL]
        assert (gate[multi + 2].mnemonic, int(gate[multi + 2].op_str, 16)) == ("je", DROP)

    def test_the_mixed_context_gate_asks_every_selected_member(self):
        gate = ops(
            CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE_BYTES,
            CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE,
        )
        assert ("cmp", "dword ptr [edi + 0x70], 7") in gate
        assert ("call", "dword ptr [eax + 0x124]") in gate
        assert ("push", "dword ptr [eax + 0xfc]") in gate


class TestTheUsablePass:
    def test_the_hooked_clear_runs_only_for_a_usable_slot(self):
        insns = disassemble(CONTROL_BAR_MULTI_USABLE_PASS_BYTES, CONTROL_BAR_MULTI_USABLE_PASS)
        assert (insns[0].mnemonic, insns[0].op_str) == (
            "cmp",
            "dword ptr [esp + ebp*4 + 0x2c], ebx",
        )
        assert insns[2].mnemonic == "jle"  # a count of zero -> the disable branch
        by_va = {i.address: n for n, i in enumerate(insns)}
        n = by_va[CONTROL_BAR_MULTI_USABLE_CLEAR_CALL]
        assert (insns[n].mnemonic, int(insns[n].op_str, 16)) == ("call", WINDOW_CLEAR_STATUS)
        assert [(i.mnemonic, i.op_str) for i in insns[n - 2 : n]] == [
            ("push", "0x1000000"),
            ("mov", "ecx, esi"),
        ]
        assert int(insns[2].op_str, 16) > CONTROL_BAR_MULTI_USABLE_CLEAR_CALL

    def test_usable_paint_keeps_the_stock_clear_first_and_pops_its_mask(self):
        insns = routine("usable_paint")
        assert insns[2:4] == [("push", "dword ptr [esp + 8]"), ("call", hex(WINDOW_CLEAR_STATUS))]
        assert insns[-1] == ("ret", "4")
        assert ("cmp", "byte ptr [eax], 2") in insns
        assert ("push", "0x400000") in insns


class TestTheCave:
    def test_availability_any_asks_stock_first_with_the_callers_arguments(self):
        insns = routine("availability_any")
        assert insns[7:13] == [
            ("push", "dword ptr [ebp + 0x18]"),
            ("push", "dword ptr [ebp + 0x14]"),
            ("push", "dword ptr [ebp + 0x10]"),
            ("push", "dword ptr [ebp + 0xc]"),
            ("push", "dword ptr [ebp + 8]"),
            ("call", hex(CONTROL_BAR_GET_COMMAND_AVAILABILITY)),
        ]
        assert insns[13] == ("cmp", "eax, 5")

    @pytest.mark.parametrize("name", ["availability_any", "ready_any"])
    def test_only_multi_execute_special_powers_walk_the_selection(self, name: str):
        insns = routine(name)
        assert ("cmp", "dword ptr [edx + 0x14], 0x18") in insns or (
            "cmp",
            "dword ptr [ebx + 0x14], 0x18",
        ) in insns
        mask = hex(COMMAND_BUTTON_OPTION_MULTI_EXECUTE)
        assert any(m == "test" and op.endswith(f"+ 0x1c], {mask}") for m, op in insns)
        assert ("mov", f"ecx, dword ptr [{hex(THE_IN_GAME_UI)}]") in insns

    def test_the_calling_conventions_match_what_they_replace(self):
        assert routine("availability_any")[-1] == ("ret", "0x14")
        assert routine("ready_any")[-1] == ("ret", "4")
        for name in ("availability_any", "ready_any"):
            insns = routine(name)
            assert insns[:5] == [
                ("push", "ebp"),
                ("mov", "ebp, esp"),
                ("push", "ebx"),
                ("push", "esi"),
                ("push", "edi"),
            ]

    def test_it_disassembles_cleanly_to_its_end(self):
        section = build_section(BASE)
        assert sum(i.size for i in disassemble(section, BASE)) == len(section)


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert MultiExecuteCooldownPatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert MultiExecuteCooldownPatch().verify(multi_execute_cooldown_image())

    def test_the_sites_call_the_cave(self, patched: bytearray):
        at = layout(find_section(patched, SECTION_NAME)[0])
        for va in AVAILABILITY_SITES:
            assert _read(patched, va, 5) == call_rel32(va, at["availability_any"])
        for va in READY_SITES:
            assert _read(patched, va, 5) == call_rel32(va, at["ready_any"])
        for va in USABLE_SITES:
            assert _read(patched, va, 5) == call_rel32(va, at["usable_paint"])

    def test_the_gate_changes_only_at_its_two_calls(self, patched: bytearray):
        stock = GATE_BYTES
        here = _read(patched, GATE, len(stock))
        changed = {i for i in range(len(stock)) if stock[i] != here[i]}
        allowed = {
            va - CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE + k
            for va in READY_SITES
            for k in range(5)
        }
        assert changed and changed <= allowed

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            MultiExecuteCooldownPatch().apply(patched)

    @pytest.mark.parametrize("va", [*sorted(ANCHORS), *sorted(AVAILABILITY_SITES)])
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = multi_execute_cooldown_image()
        data[va_to_offset(data, va)] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            MultiExecuteCooldownPatch().apply(data)
        assert bytes(data) == before


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[MultiExecuteCooldownPatch.name] is MultiExecuteCooldownPatch

    def test_detect_finds_it_only_once_applied(self, patched: bytearray):
        assert MultiExecuteCooldownPatch.detect(multi_execute_cooldown_image()) is None
        assert isinstance(MultiExecuteCooldownPatch.detect(patched), MultiExecuteCooldownPatch)
