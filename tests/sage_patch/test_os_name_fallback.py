"""Tests for the os-name-fallback patch.

The edit is the displacement of one `jne`, so what matters is that it is the right branch: the one
taken when the NT major version is not 5, proved by decoding the stock bytes rather than trusting
the module's reading of them, that its stock target is the bare return that leaves the name unset,
and that the new target writes a name and returns through the same epilogue.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.os_name_fallback import ANCHORS, FALLBACK_BRANCH, OsNameFallbackPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: The stock target of the branch: `pop edi / pop esi / pop ebx / pop ecx / ret`, nothing written.
_BARE_RETURN = 0x00A257B1
_BARE_RETURN_BYTES = bytes.fromhex("5f5e5b59c3")
#: "WINXX", the name the fallback case writes.
_WINXX = 0x00C945E8


def stock_image() -> bytearray:
    """The major-5 test, the branch after it and the "WINXX" case, as the binary has them."""
    return _sparse_image(
        {**ANCHORS, ad.OS_NAME_NT_UNKNOWN_BRANCH: ad.OS_NAME_NT_UNKNOWN_BRANCH_BYTES}
    )


def applied() -> bytearray:
    data = stock_image()
    OsNameFallbackPatch().apply(data)
    return data


def _disasm(blob: bytes, va: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(insn.mnemonic, insn.op_str) for insn in md.disasm(blob, va)]


class TestSite:
    def test_the_test_and_the_branch_are_adjacent(self) -> None:
        end = ad.OS_NAME_NT_MAJOR_FIVE_TEST + len(ad.OS_NAME_NT_MAJOR_FIVE_TEST_BYTES)
        assert end == ad.OS_NAME_NT_UNKNOWN_BRANCH

    def test_the_stock_branch_leaves_on_a_major_other_than_five(self) -> None:
        blob = ad.OS_NAME_NT_MAJOR_FIVE_TEST_BYTES + ad.OS_NAME_NT_UNKNOWN_BRANCH_BYTES
        assert _disasm(blob, ad.OS_NAME_NT_MAJOR_FIVE_TEST) == [
            ("cmp", "edi, 5"),
            ("jne", f"{_BARE_RETURN:#x}"),
        ]

    def test_the_bare_return_writes_nothing(self) -> None:
        assert _disasm(_BARE_RETURN_BYTES, _BARE_RETURN) == [
            ("pop", "edi"),
            ("pop", "esi"),
            ("pop", "ebx"),
            ("pop", "ecx"),
            ("ret", ""),
        ]

    def test_the_fallback_writes_winxx_and_returns_the_same_way(self) -> None:
        assert _disasm(ad.OS_NAME_NT_FALLBACK_BYTES, ad.OS_NAME_NT_FALLBACK) == [
            ("pop", "edi"),
            ("pop", "esi"),
            ("mov", f"dword ptr [ecx], {_WINXX:#x}"),
            ("pop", "ebx"),
            ("pop", "ecx"),
            ("ret", ""),
        ]

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        sites = {
            **ANCHORS,
            ad.OS_NAME_NT_UNKNOWN_BRANCH: ad.OS_NAME_NT_UNKNOWN_BRANCH_BYTES,
            _BARE_RETURN: _BARE_RETURN_BYTES,
            _WINXX: b"WINXX\x00",
        }
        for va, expected in sites.items():
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert OsNameFallbackPatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = OsNameFallbackPatch().verify(stock_image())
        assert len(problems) == 1
        assert "the stock branch" in problems[0]

    def test_detect(self) -> None:
        assert OsNameFallbackPatch.detect(stock_image()) is None
        assert isinstance(OsNameFallbackPatch.detect(applied()), OsNameFallbackPatch)

    def test_only_the_displacement_changes(self) -> None:
        stock, patched = stock_image(), applied()
        off = va_to_offset(stock, ad.OS_NAME_NT_UNKNOWN_BRANCH)
        assert off is not None
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        assert differing and all(off + 2 <= i < off + 6 for i in differing)
        assert patched[off : off + len(FALLBACK_BRANCH)] == FALLBACK_BRANCH

    def test_the_patched_branch_reaches_the_fallback(self) -> None:
        assert _disasm(FALLBACK_BRANCH, ad.OS_NAME_NT_UNKNOWN_BRANCH) == [
            ("jne", f"{ad.OS_NAME_NT_FALLBACK:#x}")
        ]

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            OsNameFallbackPatch().apply(data)

    def test_a_moved_builder_is_refused(self) -> None:
        data = stock_image()
        off = va_to_offset(data, ad.OS_NAME_NT_MAJOR_FIVE_TEST)
        assert off is not None
        data[off + 2] = 6  # compares against another major
        with pytest.raises(ValueError, match="Windows-name builder"):
            OsNameFallbackPatch().apply(data)
        assert "Windows-name builder" in OsNameFallbackPatch().verify(data)[0]


class TestRegistration:
    def test_it_is_registered_and_settled(self) -> None:
        """It lives outside `patches/experimental/`, so it must not carry the warning."""
        assert PATCHES["os-name-fallback"] is OsNameFallbackPatch
        assert OsNameFallbackPatch().experimental is False

    def test_the_description_has_no_trailing_full_stop(self) -> None:
        assert not OsNameFallbackPatch.description.endswith(".")
