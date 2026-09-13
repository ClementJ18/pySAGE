"""Tests for the ai-disabled-regions patch.

The edit is six bytes, so what matters is that they are the right six: the branch taken when the
builder's enabled test fails, proved by decoding the stock bytes rather than trusting the module's
reading of them, and refused on a build whose test is not where the patch expects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.experimental.ai_disabled_regions import NOPS, AiDisabledRegionsPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def stock_image() -> bytearray:
    """The builder's enabled test and the skip after it, adjacent as the binary has them."""
    return _sparse_image(
        {
            ad.AI_REGION_GRAPH_ENABLED_TEST: ad.AI_REGION_GRAPH_ENABLED_TEST_BYTES,
            ad.AI_REGION_GRAPH_SKIP_DISABLED: ad.AI_REGION_GRAPH_SKIP_DISABLED_BYTES,
        }
    )


def applied() -> bytearray:
    data = stock_image()
    AiDisabledRegionsPatch().apply(data)
    return data


class TestSite:
    def test_the_test_and_the_skip_are_adjacent(self) -> None:
        end = ad.AI_REGION_GRAPH_ENABLED_TEST + len(ad.AI_REGION_GRAPH_ENABLED_TEST_BYTES)
        assert end == ad.AI_REGION_GRAPH_SKIP_DISABLED

    def test_the_stock_bytes_are_the_enabled_test_and_its_skip(self) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        blob = ad.AI_REGION_GRAPH_ENABLED_TEST_BYTES + ad.AI_REGION_GRAPH_SKIP_DISABLED_BYTES
        listing = [
            (insn.mnemonic, insn.op_str)
            for insn in md.disasm(blob, ad.AI_REGION_GRAPH_ENABLED_TEST)
        ]
        assert listing[0] == ("cmp", f"byte ptr [ecx + {ad.REGION_ENABLED:#x}], 0")
        assert listing[1] == ("mov", "dword ptr [ebp - 0x18], ecx")
        mnemonic, target = listing[2]
        assert mnemonic == "je"
        # Past the region's whole body, to the loop's increment - so it skips the region entirely.
        assert int(target, 16) == 0x009081A0

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        for va, expected in (
            (ad.AI_REGION_GRAPH_ENABLED_TEST, ad.AI_REGION_GRAPH_ENABLED_TEST_BYTES),
            (ad.AI_REGION_GRAPH_SKIP_DISABLED, ad.AI_REGION_GRAPH_SKIP_DISABLED_BYTES),
        ):
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert AiDisabledRegionsPatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = AiDisabledRegionsPatch().verify(stock_image())
        assert len(problems) == 1
        assert "the stock skip" in problems[0]

    def test_detect(self) -> None:
        assert AiDisabledRegionsPatch.detect(stock_image()) is None
        assert isinstance(AiDisabledRegionsPatch.detect(applied()), AiDisabledRegionsPatch)

    def test_only_the_skip_changes(self) -> None:
        stock, patched = stock_image(), applied()
        off = va_to_offset(stock, ad.AI_REGION_GRAPH_SKIP_DISABLED)
        assert off is not None
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        assert differing == list(range(off, off + len(NOPS)))
        assert patched[off : off + len(NOPS)] == NOPS

    def test_the_enabled_test_is_left_alone(self) -> None:
        patched = applied()
        off = va_to_offset(patched, ad.AI_REGION_GRAPH_ENABLED_TEST)
        assert off is not None
        size = len(ad.AI_REGION_GRAPH_ENABLED_TEST_BYTES)
        assert patched[off : off + size] == ad.AI_REGION_GRAPH_ENABLED_TEST_BYTES

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            AiDisabledRegionsPatch().apply(data)

    def test_a_moved_builder_is_refused(self) -> None:
        data = stock_image()
        off = va_to_offset(data, ad.AI_REGION_GRAPH_ENABLED_TEST)
        assert off is not None
        data[off + 2] ^= 0xFF  # a different field than +0x1C2
        with pytest.raises(ValueError, match="enabled test"):
            AiDisabledRegionsPatch().apply(data)
        assert "enabled test" in AiDisabledRegionsPatch().verify(data)[0]


class TestRegistration:
    def test_it_is_registered_and_experimental(self) -> None:
        assert PATCHES["ai-disabled-regions"] is AiDisabledRegionsPatch
        assert AiDisabledRegionsPatch().experimental is True

    def test_the_description_names_the_trigger(self) -> None:
        assert "DisableRegions" in AiDisabledRegionsPatch.description
        assert not AiDisabledRegionsPatch.description.endswith(".")
