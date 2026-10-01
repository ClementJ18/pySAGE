"""Tests for the command-point-override patch.

The edit rewrites the initialiser's merge in place, so what matters is that the stock bytes are the
merge the write-up describes (decoded here, not trusted), that the rewrite branches to the epilogue
and the factor and nowhere else, and that a build where either target moved is refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.command_point_override import MERGE, CommandPointOverridePatch
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

_SITES = (
    (ad.COMMAND_POINTS_INIT_MERGE, ad.COMMAND_POINTS_INIT_MERGE_BYTES),
    (ad.COMMAND_POINTS_INIT_FACTOR, ad.COMMAND_POINTS_INIT_FACTOR_BYTES),
    (ad.COMMAND_POINTS_INIT_RETURN, ad.COMMAND_POINTS_INIT_RETURN_BYTES),
)


def stock_image() -> bytearray:
    return _sparse_image(dict(_SITES))


def applied() -> bytearray:
    data = stock_image()
    CommandPointOverridePatch().apply(data)
    return data


def _listing(blob: bytes, va: int) -> list[tuple[int, str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(insn.address, insn.mnemonic, insn.op_str) for insn in md.disasm(blob, va)]


class TestSite:
    def test_the_merge_runs_into_the_factor(self) -> None:
        end = ad.COMMAND_POINTS_INIT_MERGE + len(ad.COMMAND_POINTS_INIT_MERGE_BYTES)
        assert end == ad.COMMAND_POINTS_INIT_FACTOR

    def test_the_stock_merge_keeps_the_larger_value_when_overridden(self) -> None:
        listing = _listing(ad.COMMAND_POINTS_INIT_MERGE_BYTES, ad.COMMAND_POINTS_INIT_MERGE)
        ops = [(m, o) for _, m, o in listing]
        assert ops[0] == ("mov", f"al, byte ptr [edi + {ad.COMMAND_POINTS_OVERRIDDEN:#x}]")
        assert ("cmp", f"esi, dword ptr [edi + {ad.COMMAND_POINTS_HARD_CAP:#x}]") in ops
        assert ("cmp", f"ebx, dword ptr [edi + {ad.COMMAND_POINTS_BASE}]") in ops
        assert ops[-1] == ("mov", f"dword ptr [edi + {ad.COMMAND_POINTS_BASE}], ebx")
        assert len(ops) == 11

    def test_the_return_is_the_epilogue(self) -> None:
        ops = [
            (m, o)
            for _, m, o in _listing(
                ad.COMMAND_POINTS_INIT_RETURN_BYTES, ad.COMMAND_POINTS_INIT_RETURN
            )
        ]
        assert ops == [
            ("pop", "ebx"),
            ("pop", "edi"),
            ("pop", "esi"),
            ("leave", ""),
            ("ret", "8"),
        ]

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        for va, expected in _SITES:
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected


class TestMerge:
    def test_same_width_as_the_stock_merge(self) -> None:
        assert len(MERGE) == len(ad.COMMAND_POINTS_INIT_MERGE_BYTES)

    def test_overridden_returns_otherwise_stores_both_and_scales(self) -> None:
        listing = _listing(MERGE, ad.COMMAND_POINTS_INIT_MERGE)
        assert [(m, o) for _, m, o in listing[:5]] == [
            ("cmp", f"byte ptr [edi + {ad.COMMAND_POINTS_OVERRIDDEN:#x}], 0"),
            ("jne", f"{ad.COMMAND_POINTS_INIT_RETURN:#x}"),
            ("mov", f"dword ptr [edi + {ad.COMMAND_POINTS_HARD_CAP:#x}], esi"),
            ("mov", f"dword ptr [edi + {ad.COMMAND_POINTS_BASE}], ebx"),
            ("jmp", f"{ad.COMMAND_POINTS_INIT_FACTOR:#x}"),
        ]
        assert all(m == "nop" for _, m, _ in listing[5:])
        assert listing[-1][0] + 1 == ad.COMMAND_POINTS_INIT_FACTOR


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert CommandPointOverridePatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = CommandPointOverridePatch().verify(stock_image())
        assert len(problems) == 1
        assert "the stock merge" in problems[0]

    def test_detect(self) -> None:
        assert CommandPointOverridePatch.detect(stock_image()) is None
        assert isinstance(CommandPointOverridePatch.detect(applied()), CommandPointOverridePatch)

    def test_only_the_merge_changes(self) -> None:
        stock, patched = stock_image(), applied()
        off = va_to_offset(stock, ad.COMMAND_POINTS_INIT_MERGE)
        assert off is not None
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        assert differing
        assert min(differing) >= off
        assert max(differing) < off + len(MERGE)
        assert patched[off : off + len(MERGE)] == MERGE

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            CommandPointOverridePatch().apply(data)

    @pytest.mark.parametrize(
        ("va", "what"),
        [
            (ad.COMMAND_POINTS_INIT_RETURN, "epilogue"),
            (ad.COMMAND_POINTS_INIT_FACTOR, "factor load"),
        ],
    )
    def test_a_moved_target_is_refused(self, va: int, what: str) -> None:
        data = stock_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match=what):
            CommandPointOverridePatch().apply(data)
        assert what in CommandPointOverridePatch().verify(data)[0]


class TestRegistration:
    def test_it_is_registered_and_settled(self) -> None:
        assert PATCHES["command-point-override"] is CommandPointOverridePatch
        assert CommandPointOverridePatch().experimental is False

    def test_the_description_names_the_action(self) -> None:
        assert "OVERRIDE_PLAYER_COMMAND_POINTS" in CommandPointOverridePatch.description
        assert not CommandPointOverridePatch.description.endswith(".")
