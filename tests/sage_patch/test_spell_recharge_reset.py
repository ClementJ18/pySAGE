"""Tests for the spell-recharge-reset patch.

The sites are checked by decoding the stock bytes. The behaviour is checked by running the real
`onDelete` and `onCapture` bodies of `SpellRechargeModifierUpgrade` under unicorn, from the
decrement to the point the cave resumes at. That run uses the stock binary and the patched one,
so the stock bug is pinned beside the fix: at level 0 stock writes `Percentage[0]`, and the patch
writes `0.0`.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.patches.special_powers.spell_recharge_reset import (
    PLAYER_RECHARGE_DISCOUNT,
    PLAYER_RECHARGE_LEVEL,
    SITES,
    SpellRechargeResetPatch,
    _anchor,
    _stock_call,
)
from sage_patch.patches.special_powers.spell_recharge_targets import SpellRechargeTargetsPatch
from sage_patch.pe import image_sections
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

try:
    import unicorn
    from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP
except ImportError:  # the site and apply tests still run
    unicorn = None

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
needs_game_dat = pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")

_RESUME_BYTES = {0x008BA05A: bytes.fromhex("5e5fc9c3"), 0x008BA0C9: bytes.fromhex("8b7d0c")}


def stock_image_sites() -> dict[int, bytes]:
    """Each decrement and level read, and each resume point, as the binary has them."""
    sites: dict[int, bytes] = dict(_RESUME_BYTES)
    for _which, site, _resume in SITES:
        sites[site - 9] = _anchor(site) + _stock_call(site)
    return sites


def stock_image() -> bytearray:
    return _sparse_image(stock_image_sites())


def applied() -> bytearray:
    data = stock_image()
    SpellRechargeResetPatch().apply(data)
    return data


class TestSite:
    def test_each_site_reads_the_level_right_after_decrementing_it(self) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        for _which, site, _resume in SITES:
            blob = _anchor(site) + _stock_call(site)
            listing = [(i.mnemonic, i.op_str) for i in md.disasm(blob, site - 9)]
            assert listing == [
                ("mov", "ecx, edi"),
                ("call", "0x6aaae7"),
                ("mov", "ecx, edi"),
                ("call", "0x6aaad9"),
            ]

    @needs_game_dat
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        for va, expected in stock_image_sites().items():
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected, hex(va)


class TestApply:
    def test_verify_passes_after_apply(self) -> None:
        assert SpellRechargeResetPatch().verify(applied()) == []

    def test_verify_fails_on_the_stock_image(self) -> None:
        assert SpellRechargeResetPatch().verify(stock_image())

    def test_detect(self) -> None:
        assert SpellRechargeResetPatch.detect(applied()) is not None
        assert SpellRechargeResetPatch.detect(stock_image()) is None

    def test_refuses_a_second_application(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            SpellRechargeResetPatch().apply(data)

    def test_refuses_a_build_without_the_decrement(self) -> None:
        site = SITES[0][1]
        data = _sparse_image({**stock_image_sites(), site - 9: b"\x90" * 14})
        with pytest.raises(ValueError):
            SpellRechargeResetPatch().apply(data)

    def test_registered(self) -> None:
        assert PATCHES["spell-recharge-reset"] is SpellRechargeResetPatch

    @needs_game_dat
    def test_composes_with_spell_recharge_targets(self) -> None:
        for order in (
            (SpellRechargeTargetsPatch(), SpellRechargeResetPatch()),
            (SpellRechargeResetPatch(), SpellRechargeTargetsPatch()),
        ):
            data = bytearray(_GAME_DAT.read_bytes())
            for patch in order:
                patch.apply(data)
            for patch in order:
                assert patch.verify(data) == [], patch


# ---------------------------------------------------------------------------------------------
# Running the stock bodies.

_PLAYER = 0x10000000
_OTHER_PLAYER = 0x10001000
_MODULE_DATA = 0x10002000
_PERCENTAGES = 0x10003000
_STACK = 0x10100000
_STACK_SIZE = 0x10000


class _Machine:
    def __init__(self, image: bytes) -> None:
        if unicorn is None:
            pytest.skip("the emulator needs unicorn")
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        for section in image_sections(image):
            start = section.virtual_address & ~0xFFF
            size = (
                section.virtual_address
                + max(section.virtual_size, section.raw_size)
                - start
                + 0xFFF
            ) & ~0xFFF
            self.uc.mem_map(start, size)
            raw = image[section.raw_offset : section.raw_offset + section.raw_size]
            self.uc.mem_write(section.virtual_address, bytes(raw))
        self.uc.mem_map(_PLAYER, 0x4000)
        self.uc.mem_map(_STACK - _STACK_SIZE, _STACK_SIZE * 2)

    def player(self, at: int, level: int, discount: float) -> None:
        self.uc.mem_write(at + PLAYER_RECHARGE_LEVEL, struct.pack("<i", level))
        self.uc.mem_write(at + PLAYER_RECHARGE_DISCOUNT, struct.pack("<f", discount))

    def read(self, at: int) -> tuple[int, float]:
        level = struct.unpack("<i", self.uc.mem_read(at + PLAYER_RECHARGE_LEVEL, 4))[0]
        discount = struct.unpack("<f", self.uc.mem_read(at + PLAYER_RECHARGE_DISCOUNT, 4))[0]
        return level, discount

    def module(self, percentages: tuple[float, ...]) -> None:
        self.uc.mem_write(_PERCENTAGES, struct.pack(f"<{len(percentages)}f", *percentages))
        begin, end = _PERCENTAGES, _PERCENTAGES + 4 * len(percentages)
        self.uc.mem_write(_MODULE_DATA + 0x138, struct.pack("<II", begin, end))

    def run(self, start: int, until: int, edi: int) -> None:
        ebp = _STACK
        self.uc.mem_write(ebp + 0xC, struct.pack("<I", 0))  # onCapture's new owner: none
        self.uc.reg_write(UC_X86_REG_EBP, ebp)
        self.uc.reg_write(UC_X86_REG_ESP, ebp - 0x20)
        self.uc.reg_write(UC_X86_REG_EDI, edi)
        self.uc.reg_write(UC_X86_REG_ESI, _MODULE_DATA)
        self.uc.emu_start(start, until, count=200)
        assert self.uc.reg_read(UC_X86_REG_ESP) == ebp - 0x20, (
            "the stack is unbalanced at the resume"
        )


#: Where each body's decrement starts (`mov ecx, edi`), and where both versions end up.
_DELETE = (0x008BA002, 0x008BA05A)
_CAPTURE = (0x008BA071, 0x008BA0C9)

_TOWER = (-0.2, -0.4)


def _image(patched: bool) -> bytes:
    data = bytearray(_GAME_DAT.read_bytes())
    if patched:
        SpellRechargeResetPatch().apply(data)
    return bytes(data)


@needs_game_dat
@pytest.mark.parametrize("body", [_DELETE, _CAPTURE], ids=["onDelete", "onCapture"])
class TestEmulated:
    def _lose_one(self, patched: bool, body: tuple[int, int], level: int, discount: float):
        machine = _Machine(_image(patched))
        machine.player(_PLAYER, level, discount)
        machine.module(_TOWER)
        machine.run(*body, edi=_PLAYER)
        return machine.read(_PLAYER)

    def test_stock_keeps_the_first_level_after_the_last_module(self, body) -> None:
        level, discount = self._lose_one(False, body, 1, -0.2)
        assert level == 0
        assert discount == pytest.approx(-0.2)

    def test_patched_clears_the_discount_after_the_last_module(self, body) -> None:
        level, discount = self._lose_one(True, body, 1, -0.2)
        assert level == 0
        assert discount == 0.0

    def test_patched_steps_down_a_level_as_stock_does(self, body) -> None:
        assert self._lose_one(True, body, 2, -0.4) == self._lose_one(False, body, 2, -0.4)
        level, discount = self._lose_one(True, body, 2, -0.4)
        assert (level, discount) == (1, pytest.approx(-0.2))
