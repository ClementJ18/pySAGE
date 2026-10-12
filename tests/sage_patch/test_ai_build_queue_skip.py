"""Tests for the ai-build-queue-skip patch.

The edit is two bytes, so what matters is that they are the right two: the branch taken when an
order answers "no builder" and the builder pool is not empty, proved by decoding the stock bytes
rather than trusting the module's reading of them, and refused on a build whose test is not where
the patch expects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.ai_build_queue_skip import ANCHORS, NOPS, AiBuildQueueSkipPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: Where the removed branch went: past the loop, to the pump's "stop at this order" exit.
_STOP_TARGET = 0x008F1073


def stock_image() -> bytearray:
    """The pump's can-start call, the no-builder test and the stop after it, as the binary has
    them."""
    return _sparse_image(
        {
            **ANCHORS,
            ad.AI_ORDER_PUMP_NO_BUILDER_STOP: ad.AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES,
        }
    )


def applied() -> bytearray:
    data = stock_image()
    AiBuildQueueSkipPatch().apply(data)
    return data


class TestSite:
    def test_the_test_and_the_stop_are_adjacent(self) -> None:
        end = ad.AI_ORDER_PUMP_NO_BUILDER_TEST + len(ad.AI_ORDER_PUMP_NO_BUILDER_TEST_BYTES)
        assert end == ad.AI_ORDER_PUMP_NO_BUILDER_STOP

    def test_the_stock_bytes_are_the_no_builder_test_and_its_stop(self) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        blob = ad.AI_ORDER_PUMP_NO_BUILDER_TEST_BYTES + ad.AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES
        listing = [
            (insn.mnemonic, insn.op_str)
            for insn in md.disasm(blob, ad.AI_ORDER_PUMP_NO_BUILDER_TEST)
        ]
        assert listing[0] == ("cmp", "eax, 8")
        # Any other answer jumps over the pool test and the stop, to where the patch falls to.
        after = ad.AI_ORDER_PUMP_NO_BUILDER_STOP + len(ad.AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES)
        assert listing[1] == ("jne", f"{after:#x}")
        assert listing[2] == ("cmp", "dword ptr [ebp - 8], 0")
        assert listing[3] == ("ja", f"{_STOP_TARGET:#x}")

    def test_the_call_is_the_can_start_helper(self) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        insn = next(
            md.disasm(ad.AI_ORDER_PUMP_CAN_START_CALL_BYTES, ad.AI_ORDER_PUMP_CAN_START_CALL)
        )
        assert (insn.mnemonic, insn.op_str) == ("call", "0x961975")

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        sites = {
            **ANCHORS,
            ad.AI_ORDER_PUMP_NO_BUILDER_STOP: ad.AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES,
        }
        for va, expected in sites.items():
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert AiBuildQueueSkipPatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = AiBuildQueueSkipPatch().verify(stock_image())
        assert len(problems) == 1
        assert "the stock stop" in problems[0]

    def test_detect(self) -> None:
        assert AiBuildQueueSkipPatch.detect(stock_image()) is None
        assert isinstance(AiBuildQueueSkipPatch.detect(applied()), AiBuildQueueSkipPatch)

    def test_only_the_stop_changes(self) -> None:
        stock, patched = stock_image(), applied()
        off = va_to_offset(stock, ad.AI_ORDER_PUMP_NO_BUILDER_STOP)
        assert off is not None
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        assert differing == list(range(off, off + len(NOPS)))
        assert patched[off : off + len(NOPS)] == NOPS

    def test_the_patched_bytes_fall_through_to_the_next_order_path(self) -> None:
        """With the stop gone, answer 8 reaches the `cmp eax, 2` every other answer reaches."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        blob = ad.AI_ORDER_PUMP_NO_BUILDER_TEST_BYTES + NOPS
        mnemonics = [i.mnemonic for i in md.disasm(blob, ad.AI_ORDER_PUMP_NO_BUILDER_TEST)]
        assert mnemonics == ["cmp", "jne", "cmp", "nop", "nop"]

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            AiBuildQueueSkipPatch().apply(data)

    def test_a_moved_pump_is_refused(self) -> None:
        data = stock_image()
        off = va_to_offset(data, ad.AI_ORDER_PUMP_NO_BUILDER_TEST)
        assert off is not None
        data[off + 2] ^= 0xFF  # a different answer than 8
        with pytest.raises(ValueError, match="no-builder test"):
            AiBuildQueueSkipPatch().apply(data)
        assert "no-builder test" in AiBuildQueueSkipPatch().verify(data)[0]


class TestRegistration:
    def test_it_is_registered_and_settled(self) -> None:
        """It lives outside `patches/experimental/`, so it must not carry the warning."""
        assert PATCHES["ai-build-queue-skip"] is AiBuildQueueSkipPatch
        assert AiBuildQueueSkipPatch().experimental is False

    def test_the_description_says_who_it_applies_to(self) -> None:
        assert "All factions" in AiBuildQueueSkipPatch.description
        assert not AiBuildQueueSkipPatch.description.endswith(".")
