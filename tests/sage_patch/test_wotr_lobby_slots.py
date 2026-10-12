"""Tests for the wotr-lobby-slots patch.

Two one-byte edits, so what matters is that they are the right two bytes: each a `jcc rel8` whose
target is the arm that leaves the War of the Ring rule out, proved by decoding the stock bytes
rather than trusting the address module's reading of them, and refused on a build that differs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.wotr_lobby_slots import JMP_SHORT, SITES, WotrLobbySlotsPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def stock_image() -> bytearray:
    return _sparse_image({anchor: stock for anchor, stock, *_ in SITES})


def applied() -> bytearray:
    data = stock_image()
    WotrLobbySlotsPatch().apply(data)
    return data


def _disasm(blob: bytes, va: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(insn.mnemonic, insn.op_str) for insn in md.disasm(blob, va)]


class TestSites:
    def test_each_branch_is_the_last_two_bytes_of_its_anchor(self) -> None:
        for anchor, stock, branch, *_ in SITES:
            assert branch == anchor + len(stock) - 2

    def test_the_gadget_test_is_slot_six_or_more(self) -> None:
        listing = _disasm(
            ad.MP_SETUP_GADGET_WOTR_SLOT_TEST_BYTES, ad.MP_SETUP_GADGET_WOTR_SLOT_TEST
        )
        assert listing[0] == ("cmp", f"dword ptr [ebp + {ad.MP_SETUP_GADGET_SLOT_EBP:#x}], 6")
        # Below six skips straight to the epilogue: the hide is only for slots 6 and 7.
        assert listing[1] == ("jb", f"{ad.MP_SETUP_GADGET_UNKNOWN:#x}")

    def test_the_combo_gate_enters_the_walk(self) -> None:
        listing = _disasm(
            ad.MP_SETUP_SLOT_COMBO_WOTR_OPEN_GATE_BYTES, ad.MP_SETUP_SLOT_COMBO_WOTR_OPEN_GATE
        )
        assert listing[0] == ("cmp", "dword ptr [ebp - 0x24], 0")
        # Past the walk to where the historical MaxPlayers cap runs, so that cap survives.
        assert listing[1] == ("je", f"{ad.MP_SETUP_SLOT_COMBO_WALK_DONE:#x}")

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        for anchor, expected, *_ in SITES:
            off = va_to_offset(stock, anchor)
            assert off is not None
            assert stock[off : off + len(expected)] == expected

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_hide_follows_the_gadget_test(self) -> None:
        """The rule is the War of the Ring mode test and `Window::hide`, not something else
        gated on the slot number."""
        data = _GAME_DAT.read_bytes()
        va = ad.MP_SETUP_GADGET_WOTR_SLOT_TEST + len(ad.MP_SETUP_GADGET_WOTR_SLOT_TEST_BYTES)
        off = va_to_offset(data, va)
        assert off is not None
        listing = _disasm(data[off : off + 15], va)
        assert listing[0] == (
            "cmp",
            f"dword ptr [edi + {ad.MP_SETUP_MODE:#x}], {ad.MP_SETUP_MODE_WOTR}",
        )
        assert listing[1] == ("jne", f"{ad.MP_SETUP_GADGET_UNKNOWN:#x}")
        assert listing[-1][0] == "call"


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert WotrLobbySlotsPatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = WotrLobbySlotsPatch().verify(stock_image())
        assert len(problems) == 2
        assert all("the stock branch" in p for p in problems)

    def test_detect(self) -> None:
        assert WotrLobbySlotsPatch.detect(stock_image()) is None
        assert isinstance(WotrLobbySlotsPatch.detect(applied()), WotrLobbySlotsPatch)

    def test_only_the_two_opcodes_change(self) -> None:
        stock, patched = stock_image(), applied()
        offsets = [va_to_offset(stock, branch) for _, _, branch, *_ in SITES]
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        assert differing == sorted(offsets)
        assert all(patched[off] == JMP_SHORT for off in offsets if off is not None)

    def test_the_branches_keep_their_targets(self) -> None:
        patched = applied()
        for _anchor, _stock, branch, _opcode, target, _what in SITES:
            off = va_to_offset(patched, branch)
            assert off is not None
            assert _disasm(bytes(patched[off : off + 2]), branch) == [("jmp", f"{target:#x}")]

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            WotrLobbySlotsPatch().apply(data)

    def test_a_different_build_is_refused_whole(self) -> None:
        data = stock_image()
        anchor = ad.MP_SETUP_SLOT_COMBO_WOTR_OPEN_GATE
        off = va_to_offset(data, anchor)
        assert off is not None
        data[off + 2] ^= 0xFF  # a different local than [ebp-0x24]
        before = bytes(data)
        with pytest.raises(ValueError, match="game-setup screen"):
            WotrLobbySlotsPatch().apply(data)
        # The first site is checked before anything is written, so nothing changed.
        assert bytes(data) == before
        assert any("game-setup screen" in p for p in WotrLobbySlotsPatch().verify(data))


class TestRegistration:
    def test_it_is_registered_and_settled(self) -> None:
        assert PATCHES["wotr-lobby-slots"] is WotrLobbySlotsPatch
        assert WotrLobbySlotsPatch().experimental is False

    def test_the_description_names_the_companion_and_the_ini(self) -> None:
        assert "wotr-battle-observers" in WotrLobbySlotsPatch.description
        assert "MaxPlayers" in WotrLobbySlotsPatch.description
        assert not WotrLobbySlotsPatch.description.endswith(".")
