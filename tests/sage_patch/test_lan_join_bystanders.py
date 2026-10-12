"""Tests for the lan-join-bystanders patch.

Three `jcc rel32` displacements change. What matters is that each is a not-hosting test whose stock
target is the "game gone" denial, and that the new target is the exit the handler already uses for
a request meant for another machine - both proved by decoding, not by trusting the address module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.lan_join_bystanders import (
    LanJoinBystandersPatch,
    jcc_target,
    retargeted,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def stock_image() -> bytearray:
    sites = dict(ad.LAN_REQUEST_JOIN_NOT_HOSTING)
    sites[ad.LAN_REQUEST_JOIN_TARGET_TEST] = ad.LAN_REQUEST_JOIN_TARGET_TEST_BYTES
    return _sparse_image(sites)


def applied() -> bytearray:
    data = stock_image()
    LanJoinBystandersPatch().apply(data)
    return data


def _disasm(blob: bytes, va: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(insn.mnemonic, insn.op_str) for insn in md.disasm(blob, va)]


class TestSites:
    def test_every_stock_branch_is_the_game_gone_denial(self) -> None:
        for site, stock in ad.LAN_REQUEST_JOIN_NOT_HOSTING:
            mnemonic, target = _disasm(stock, site)[-1]
            assert mnemonic in ("je", "jne")
            assert int(target, 16) == ad.LAN_REQUEST_JOIN_DENY_GONE

    def test_the_ip_test_already_uses_the_ignore_exit(self) -> None:
        listing = _disasm(ad.LAN_REQUEST_JOIN_TARGET_TEST_BYTES, ad.LAN_REQUEST_JOIN_TARGET_TEST)
        assert listing[1] == ("mov", "ecx, dword ptr [ecx + 0x1e]")
        # The comparison is one dword - the IP - and never the port beside it.
        assert listing[2] == ("cmp", "ecx, dword ptr [eax]")
        assert listing[3] == ("jne", f"{ad.LAN_REQUEST_JOIN_IGNORE:#x}")

    def test_the_tests_are_lobby_game_and_slot_zero(self) -> None:
        (s0, b0), (s1, b1), (s2, b2) = ad.LAN_REQUEST_JOIN_NOT_HOSTING
        assert _disasm(b0, s0)[0] == ("cmp", "byte ptr [esi + 0x41], 0")
        assert _disasm(b1, s1)[0] == ("mov", "eax, dword ptr [esi + 0x44]")
        assert _disasm(b2, s2)[0] == ("call", "0x64897c")

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        sites = [*ad.LAN_REQUEST_JOIN_NOT_HOSTING]
        sites.append((ad.LAN_REQUEST_JOIN_TARGET_TEST, ad.LAN_REQUEST_JOIN_TARGET_TEST_BYTES))
        for va, expected in sites:
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_ignore_exit_is_the_epilogue(self) -> None:
        """Nothing between the not-hosting tests and the exit owns a destructor, so leaving
        through it is what the IP test's own early exit does."""
        data = _GAME_DAT.read_bytes()
        off = va_to_offset(data, ad.LAN_REQUEST_JOIN_IGNORE)
        assert off is not None
        listing = _disasm(data[off : off + 20], ad.LAN_REQUEST_JOIN_IGNORE)
        assert listing[0] == ("mov", "ecx, dword ptr [ebp - 0xc]")
        assert ("ret", "8") in listing


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert LanJoinBystandersPatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = LanJoinBystandersPatch().verify(stock_image())
        assert len(problems) == 3
        assert all("the stock denial" in p for p in problems)

    def test_detect(self) -> None:
        assert LanJoinBystandersPatch.detect(stock_image()) is None
        assert isinstance(LanJoinBystandersPatch.detect(applied()), LanJoinBystandersPatch)

    def test_every_branch_lands_on_the_ignore_exit(self) -> None:
        patched = applied()
        for site, stock in ad.LAN_REQUEST_JOIN_NOT_HOSTING:
            off = va_to_offset(patched, site)
            assert off is not None
            got = bytes(patched[off : off + len(stock)])
            assert got == retargeted(site, stock)
            assert jcc_target(site, got) == ad.LAN_REQUEST_JOIN_IGNORE
            assert _disasm(got, site)[-1][0] == _disasm(stock, site)[-1][0]  # same condition

    def test_only_the_displacements_change(self) -> None:
        stock, patched = stock_image(), applied()
        expected = []
        for site, b in ad.LAN_REQUEST_JOIN_NOT_HOSTING:
            off = va_to_offset(stock, site)
            assert off is not None
            expected += [i for i in range(off + len(b) - 4, off + len(b)) if stock[i] != patched[i]]
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        assert differing == sorted(expected)

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            LanJoinBystandersPatch().apply(data)

    def test_a_different_build_is_refused_whole(self) -> None:
        data = stock_image()
        site, _ = ad.LAN_REQUEST_JOIN_NOT_HOSTING[2]
        off = va_to_offset(data, site)
        assert off is not None
        data[off + 1] ^= 0xFF  # a different call
        before = bytes(data)
        with pytest.raises(ValueError, match="LAN join handler"):
            LanJoinBystandersPatch().apply(data)
        assert bytes(data) == before


class TestRegistration:
    def test_it_is_registered_and_settled(self) -> None:
        assert PATCHES["lan-join-bystanders"] is LanJoinBystandersPatch
        assert LanJoinBystandersPatch().experimental is False

    def test_the_description_quotes_the_message(self) -> None:
        assert "Game has already started" in LanJoinBystandersPatch.description
        assert not LanJoinBystandersPatch.description.endswith(".")
