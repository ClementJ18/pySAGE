"""Tests for the command-point-modes patch.

The patch is data only: a longer `{label, value}` list in a new section and a repointed
descriptor. What matters is that the list the lobby will read is the stock seven unchanged followed
by the caller's pairs, that the descriptor's count and default index agree with it, that the
parameters round-trip through `detect`, and that inputs the lobby could not represent - a repeated
value, a label that is not a key - are refused before anything is written.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.command_point_modes import (
    MAX_MODES,
    MAX_VALUE,
    SECTION_NAME,
    STOCK_DEFAULT,
    STOCK_VALUES,
    CommandPointModesPatch,
    parse_modes,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, read_cstring, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

_SITES = {
    ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS: ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES
    + ad.GAME_RULES_COMMAND_POINT_FACTOR_BYTES,
    ad.GAME_RULES_COMBOS_MP: struct.pack("<II", 0x00C825E0, ad.GAME_RULES_COMMAND_POINT_FACTOR),
}


def stock_image() -> bytearray:
    return _sparse_image(_SITES)


def two_modes(default: int | None = None) -> CommandPointModesPatch:
    return CommandPointModesPatch((300, 150), ("VALUE:Siege", "VALUE:Ranked"), default=default)


def applied(patch: CommandPointModesPatch | None = None) -> bytearray:
    data = stock_image()
    (patch or two_modes()).apply(data)
    return data


def read_list(data: bytes | bytearray) -> list[tuple[str | None, int]]:
    """The list the lobby will build the combo from, followed through the descriptor."""
    off = va_to_offset(data, ad.GAME_RULES_COMMAND_POINT_FACTOR)
    assert off is not None
    _rule, options_va, count, _default = struct.unpack_from("<IIII", data, off)
    options_off = va_to_offset(data, options_va)
    assert options_off is not None
    pairs = []
    for i in range(count):
        label_va, value = struct.unpack_from("<II", data, options_off + 8 * i)
        pairs.append((read_cstring(data, label_va), value))
    return pairs


class TestStockSite:
    def test_the_stock_list_is_the_seven_factors(self) -> None:
        assert STOCK_VALUES == (33, 50, 100, 200, 400, 800, 10000)
        assert STOCK_DEFAULT == 100

    def test_the_descriptor_follows_the_list(self) -> None:
        end = (
            ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS
            + 8 * ad.GAME_RULES_COMMAND_POINT_FACTOR_COUNT
        )
        assert end == ad.GAME_RULES_COMMAND_POINT_FACTOR
        rule, options, count, default = struct.unpack(
            "<IIII", ad.GAME_RULES_COMMAND_POINT_FACTOR_BYTES
        )
        assert (rule, options, count, default) == (
            3,
            ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS,
            7,
            2,
        )

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_list(self) -> None:
        stock = _GAME_DAT.read_bytes()
        for va, expected in _SITES.items():
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected
        labels = [label for label, _ in read_list(stock)]
        assert labels == [
            "VALUE:ThirdX",
            "VALUE:HalfX",
            "VALUE:1X",
            "VALUE:2X",
            "VALUE:4X",
            "VALUE:8X",
            "VALUE:100X",
        ]

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_applies_to_the_real_binary(self) -> None:
        data = bytearray(_GAME_DAT.read_bytes())
        two_modes().apply(data)
        assert two_modes().verify(data) == []
        assert read_list(data)[-2:] == [("VALUE:Siege", 300), ("VALUE:Ranked", 150)]


class TestApply:
    def test_the_list_is_stock_then_the_new_pairs(self) -> None:
        pairs = read_list(applied())
        assert [value for _, value in pairs] == [*STOCK_VALUES, 300, 150]
        assert pairs[-2:] == [("VALUE:Siege", 300), ("VALUE:Ranked", 150)]

    def test_the_stock_pairs_keep_their_rdata_labels(self) -> None:
        data = applied()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        _va, section_off, _ = located
        size = len(ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES)
        assert (
            data[section_off : section_off + size]
            == ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES
        )

    def test_the_stock_default_is_kept(self) -> None:
        off = va_to_offset(applied(), ad.GAME_RULES_COMMAND_POINT_FACTOR)
        assert off is not None
        assert struct.unpack_from("<I", applied(), off + 12)[0] == STOCK_VALUES.index(100)

    def test_a_new_default_points_at_its_value(self) -> None:
        data = applied(two_modes(default=150))
        off = va_to_offset(data, ad.GAME_RULES_COMMAND_POINT_FACTOR)
        assert off is not None
        index = struct.unpack_from("<I", data, off + 12)[0]
        assert read_list(data)[index][1] == 150

    def test_the_stock_list_is_left_in_place(self) -> None:
        data = applied()
        off = va_to_offset(data, ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS)
        assert off is not None
        size = len(ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES)
        assert data[off : off + size] == ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES

    def test_verifies(self) -> None:
        assert two_modes().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        assert two_modes().verify(stock_image()) == [f"{SECTION_NAME} section is absent"]

    def test_another_list_does_not_verify(self) -> None:
        other = CommandPointModesPatch((300,), ("VALUE:Siege",))
        assert other.verify(applied()) != []

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError):
            two_modes().apply(data)

    def test_an_empty_list_is_refused_at_apply(self) -> None:
        with pytest.raises(ValueError, match="no modes"):
            CommandPointModesPatch().apply(stock_image())

    def test_a_changed_stock_list_is_refused(self) -> None:
        data = stock_image()
        off = va_to_offset(data, ad.GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS)
        assert off is not None
        data[off + 4] = 34  # ThirdX worth 34
        with pytest.raises(ValueError, match="stock command-point option list"):
            two_modes().apply(data)


class TestDetect:
    def test_recovers_the_parameters(self) -> None:
        found = CommandPointModesPatch.detect(applied(two_modes(default=300)))
        assert isinstance(found, CommandPointModesPatch)
        assert found.options() == {
            "values": (300, 150),
            "labels": ("VALUE:Siege", "VALUE:Ranked"),
            "default": 300,
        }

    def test_the_stock_default_is_not_recorded(self) -> None:
        found = CommandPointModesPatch.detect(applied())
        assert found is not None
        assert found.options() == {"values": (300, 150), "labels": ("VALUE:Siege", "VALUE:Ranked")}

    def test_a_stock_image_is_not_detected(self) -> None:
        assert CommandPointModesPatch.detect(stock_image()) is None


class TestValidation:
    @pytest.mark.parametrize(
        ("values", "labels", "match"),
        [
            ((100,), ("VALUE:Again",), "already in the list"),
            ((300, 300), ("VALUE:A", "VALUE:B"), "already in the list"),
            ((0,), ("VALUE:Zero",), "outside"),
            ((MAX_VALUE + 1,), ("VALUE:Huge",), "outside"),
            ((300,), ("",), "ASCII"),
            ((300,), ("VALUE:Two words",), "not a string-table key"),
            ((300,), ("VALUE:Siege", "VALUE:Extra"), "labels"),
            (tuple(range(1000, 1000 + MAX_MODES + 1)), ("VALUE:X",) * (MAX_MODES + 1), "at most"),
        ],
    )
    def test_refused(self, values: tuple[int, ...], labels: tuple[str, ...], match: str) -> None:
        with pytest.raises(ValueError, match=match):
            CommandPointModesPatch(values, labels)

    def test_a_default_outside_the_list_is_refused(self) -> None:
        with pytest.raises(ValueError, match="default"):
            two_modes(default=999)

    def test_a_stock_default_may_be_named(self) -> None:
        assert two_modes(default=STOCK_DEFAULT).default is None
        assert two_modes(default=800).default == 800


class TestCli:
    def test_parse_modes(self) -> None:
        assert parse_modes(" 300=VALUE:Siege , 0x96=VALUE:Ranked,") == (
            (300, 150),
            ("VALUE:Siege", "VALUE:Ranked"),
        )

    @pytest.mark.parametrize("text", ["300", "x=VALUE:Bad"])
    def test_parse_modes_refuses(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_modes(text)

    def test_from_cli_args(self) -> None:
        parser = argparse.ArgumentParser()
        CommandPointModesPatch.add_cli_arguments(parser)
        args = parser.parse_args(
            ["--modes", "300=VALUE:Siege,150=VALUE:Ranked", "--default", "150"]
        )
        patch = CommandPointModesPatch.from_cli_args(args)
        assert patch.options() == two_modes(default=150).options()


class TestRegistration:
    def test_it_is_registered_and_settled(self) -> None:
        assert PATCHES["command-point-modes"] is CommandPointModesPatch
        assert CommandPointModesPatch().experimental is False

    def test_the_description_names_the_rule(self) -> None:
        assert "RULE:CommandPointFactor" in CommandPointModesPatch.description
        assert not CommandPointModesPatch.description.endswith(".")
