"""Tests for the ai-equivalent-build-gate patch.

The edit is eight bytes inside `canMakeUnit`'s accept path. What matters is that the argument it
pushes is the function's own `what`, that the stack is left exactly as the stock three
instructions left it, and that it is refused on a build whose gate is not where it expects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.ai_equivalent_build_gate import (
    ANCHORS,
    PUSH_WANTED,
    AiEquivalentBuildGatePatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

_SITES: dict[int, bytes] = {
    **ANCHORS,
    ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE: ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES,
}


def stock_image() -> bytearray:
    """The equivalence test, the button-template fetch and the buildability call, as the binary
    has them."""
    return _sparse_image(_SITES)


def applied() -> bytearray:
    data = stock_image()
    AiEquivalentBuildGatePatch().apply(data)
    return data


def _listing(blob: bytes, va: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(insn.mnemonic, insn.op_str) for insn in md.disasm(blob, va)]


class TestSite:
    def test_the_fetch_and_the_call_are_adjacent(self) -> None:
        end = ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE + len(ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES)
        assert end == ad.CAN_MAKE_UNIT_CAN_BUILD_CALL

    def test_the_site_is_inside_the_accept_path(self) -> None:
        assert ad.CAN_MAKE_UNIT_ACCEPT < ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE
        assert ad.CAN_MAKE_UNIT_CAN_BUILD_CALL < ad.CAN_MAKE_UNIT_REVIVE_BRANCH

    def test_the_stock_bytes_fetch_the_buttons_template(self) -> None:
        blob = ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES + ad.CAN_MAKE_UNIT_CAN_BUILD_CALL_BYTES
        assert _listing(blob, ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE) == [
            ("mov", "ecx, esi"),
            ("call", "0x75d1dc"),
            ("push", "eax"),
            ("mov", "ecx, ebx"),
            ("call", "0x6ac927"),
        ]

    def test_the_equivalence_test_is_is_equivalent_to(self) -> None:
        listing = _listing(ad.CAN_MAKE_UNIT_EQUIVALENT_CALL_BYTES, ad.CAN_MAKE_UNIT_EQUIVALENT_CALL)
        assert listing == [("call", f"{ad.THING_TEMPLATE_IS_EQUIVALENT:#x}")]

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        for va, expected in _SITES.items():
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert AiEquivalentBuildGatePatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = AiEquivalentBuildGatePatch().verify(stock_image())
        assert len(problems) == 1
        assert "the stock button-template fetch" in problems[0]

    def test_detect(self) -> None:
        assert AiEquivalentBuildGatePatch.detect(stock_image()) is None
        assert isinstance(AiEquivalentBuildGatePatch.detect(applied()), AiEquivalentBuildGatePatch)

    def test_only_the_fetch_changes(self) -> None:
        stock, patched = stock_image(), applied()
        off = va_to_offset(stock, ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE)
        assert off is not None
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        assert set(differing) <= set(range(off, off + len(PUSH_WANTED)))
        assert patched[off : off + len(PUSH_WANTED)] == PUSH_WANTED

    def test_the_patched_bytes_push_the_wanted_template_once(self) -> None:
        """One push, as stock, so the call's `ret 4` still balances the stack."""
        blob = PUSH_WANTED + ad.CAN_MAKE_UNIT_CAN_BUILD_CALL_BYTES
        listing = _listing(blob, ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE)
        assert listing[0] == ("push", "dword ptr [ebp + 0xc]")
        assert [mnemonic for mnemonic, _ in listing[1:-2]] == ["nop"] * 5
        assert listing[-2:] == [("mov", "ecx, ebx"), ("call", "0x6ac927")]

    def test_the_replacement_is_the_same_length(self) -> None:
        assert len(PUSH_WANTED) == len(ad.CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES)

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            AiEquivalentBuildGatePatch().apply(data)

    def test_a_moved_gate_is_refused(self) -> None:
        data = stock_image()
        off = va_to_offset(data, ad.CAN_MAKE_UNIT_EQUIVALENT_CALL)
        assert off is not None
        data[off + 1] ^= 0xFF  # a call to somewhere else
        with pytest.raises(ValueError, match="equivalence test"):
            AiEquivalentBuildGatePatch().apply(data)
        assert "equivalence test" in AiEquivalentBuildGatePatch().verify(data)[0]


class TestRegistration:
    def test_it_is_registered_and_settled(self) -> None:
        """It lives outside `patches/experimental/`, so it must not carry the warning."""
        assert PATCHES["ai-equivalent-build-gate"] is AiEquivalentBuildGatePatch
        assert AiEquivalentBuildGatePatch().experimental is False

    def test_the_description_says_who_it_applies_to(self) -> None:
        assert "All factions" in AiEquivalentBuildGatePatch.description
        assert not AiEquivalentBuildGatePatch.description.endswith(".")
