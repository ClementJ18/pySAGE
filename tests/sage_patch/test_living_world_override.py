"""Tests for the living-world-override patch.

The edit is one dword, so the interesting tests are the ones that prove it lands on the *right*
dword: the row is identified by its name and its target offset, and the parser it is pointed at is
proved by a second row rather than trusted from the module. A stand-in that got either wrong would
otherwise agree with itself.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    GAME_DATA_ASCIISTRING_PARSER,
    GAME_DATA_BOOL_PARSER,
    GAME_DATA_SHELL_MAP_NAME_ROW,
    LIVING_WORLD_OVERRIDE_OFFSET,
    LIVING_WORLD_OVERRIDE_ROW,
)
from sage_patch.patches.living_world_override import (
    FIELD_NAME,
    ROW_PARSE_OFFSET,
    LivingWorldOverridePatch,
)
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

#: Where the stand-in parks the two row-name strings.
NAMES_VA = 0x00C05000
SHELL_MAP_NAME = "ShellMapName"


def _row(name_va: int, parse: int, offset: int) -> bytes:
    """A `GameData` field-table row: {name, parse_fn, user_data, offset}."""
    return struct.pack("<IIII", name_va, parse, 0, offset)


def stock_image() -> bytearray:
    """A PE32 mapping the two rows this patch reads and the strings they name, with the real
    stock values planted - the override row carrying the Bool parser, as shipped."""
    override_name = NAMES_VA
    shell_name = NAMES_VA + 0x40
    return _sparse_image(
        {
            LIVING_WORLD_OVERRIDE_ROW: _row(
                override_name, GAME_DATA_BOOL_PARSER, LIVING_WORLD_OVERRIDE_OFFSET
            ),
            GAME_DATA_SHELL_MAP_NAME_ROW: _row(shell_name, GAME_DATA_ASCIISTRING_PARSER, 0xAEC),
            override_name: FIELD_NAME.encode() + b"\x00",
            shell_name: SHELL_MAP_NAME.encode() + b"\x00",
        }
    )


def _parser(data: bytes | bytearray) -> int:
    off = va_to_offset(data, LIVING_WORLD_OVERRIDE_ROW + ROW_PARSE_OFFSET)
    assert off is not None
    return struct.unpack_from("<I", data, off)[0]


def _applied() -> bytearray:
    data = stock_image()
    LivingWorldOverridePatch().apply(data)
    return data


class TestApply:
    def test_applies_and_verifies(self):
        assert LivingWorldOverridePatch().verify(_applied()) == []

    def test_absent_from_an_unpatched_image(self):
        problems = LivingWorldOverridePatch().verify(stock_image())
        assert len(problems) == 1
        assert "does not carry this patch" in problems[0]

    def test_detect(self):
        assert LivingWorldOverridePatch.detect(stock_image()) is None
        assert isinstance(LivingWorldOverridePatch.detect(_applied()), LivingWorldOverridePatch)

    def test_only_the_parser_pointer_changes(self):
        """Every differing byte lies inside that one dword. Not all four change - the two parsers
        share their high half (`…42 00`) - so the assertion is containment, not equality."""
        stock, patched = stock_image(), _applied()
        assert len(stock) == len(patched)
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        off = va_to_offset(stock, LIVING_WORLD_OVERRIDE_ROW + ROW_PARSE_OFFSET)
        assert off is not None
        assert differing, "the patch changed nothing"
        assert set(differing) <= set(range(off, off + 4))
        assert _parser(patched) == GAME_DATA_ASCIISTRING_PARSER

    def test_the_new_parser_is_the_one_shellmapname_uses(self):
        """Not merely 'some other address' - the same parser a real AsciiString field parses with,
        read out of the image rather than asserted from the module."""
        data = _applied()
        anchor = va_to_offset(data, GAME_DATA_SHELL_MAP_NAME_ROW + ROW_PARSE_OFFSET)
        assert anchor is not None
        assert _parser(data) == struct.unpack_from("<I", data, anchor)[0]

    def test_row_identity_is_preserved(self):
        """The name, user data and target offset are untouched: this retypes a field, it does not
        move or rename one."""
        data = _applied()
        off = va_to_offset(data, LIVING_WORLD_OVERRIDE_ROW)
        assert off is not None
        name_va, _parse, user_data, target = struct.unpack_from("<IIII", data, off)
        assert user_data == 0
        assert target == LIVING_WORLD_OVERRIDE_OFFSET
        blob = bytes(data[va_to_offset(data, name_va) :][:64])
        assert blob[: blob.find(b"\x00")].decode() == FIELD_NAME

    def test_applying_twice_raises(self):
        data = _applied()
        with pytest.raises(ValueError):
            LivingWorldOverridePatch().apply(data)


class TestBuildChecks:
    def test_a_row_naming_something_else_is_refused(self):
        data = stock_image()
        off = va_to_offset(data, NAMES_VA)
        assert off is not None
        data[off : off + len(FIELD_NAME)] = b"X" * len(FIELD_NAME)
        with pytest.raises(ValueError, match="not the GameData field table"):
            LivingWorldOverridePatch().apply(data)

    def test_a_row_targeting_another_offset_is_refused(self):
        """The triple-'r' name could plausibly survive a layout change; the offset is what proves
        the `GlobalData` layout is this build's too."""
        data = stock_image()
        off = va_to_offset(data, LIVING_WORLD_OVERRIDE_ROW + 0x0C)
        assert off is not None
        struct.pack_into("<I", data, off, 0x90)
        with pytest.raises(ValueError, match="GlobalData"):
            LivingWorldOverridePatch().apply(data)

    def test_a_moved_asciistring_parser_is_refused(self):
        """If `ShellMapName` no longer parses with the address this patch would install, the
        replacement is not this build's AsciiString parser and the field would be pointed at the
        wrong code."""
        data = stock_image()
        off = va_to_offset(data, GAME_DATA_SHELL_MAP_NAME_ROW + ROW_PARSE_OFFSET)
        assert off is not None
        struct.pack_into("<I", data, off, 0x00401000)
        with pytest.raises(ValueError, match="AsciiString parser is not where"):
            LivingWorldOverridePatch().apply(data)
        assert _parser(data) == GAME_DATA_BOOL_PARSER  # refused before writing


class TestIniSurface:
    def test_declares_the_field_as_a_string(self):
        """`String` is the spelling the grammar accepts and the one the sibling `ShellMapName`
        already carries in the model."""
        (field,) = LivingWorldOverridePatch().ini_surface().fields
        assert (field.block, field.name, field.type) == ("GameData", FIELD_NAME, "String")
        assert field.patch == LivingWorldOverridePatch.name
