"""Tests for `damage-subtypes` and its Worldbuilder twin.

Both are pure data: a relocated name table and three repointed `userData` slots per binary. So the
tests are about the table's shape - above all that index 4 stays the module's unnameable "no
trigger" default - and about the checks that stop it landing on the wrong thing.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import pytest

from sage_patch.patches import damage_subtypes as ds
from sage_patch.patches.damage_subtypes import (
    DEFAULT_NAMES,
    FIRST_NEW_INDEX,
    GAME,
    RESERVED_NAME,
    SECTION_NAME,
    STOCK_NAMES,
    WORLDBUILDER,
    WORLDBUILDER_SECTION_NAME,
    DamageSubtypesPatch,
    DamageSubtypesWorldbuilderPatch,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: Where each stand-in parks the stock name strings: a page nothing else in it uses.
_STRINGS_VA = {GAME: 0x00BEF000, WORLDBUILDER: 0x01E6A000}

_PAIRS = [
    pytest.param(DamageSubtypesPatch, GAME, SECTION_NAME, id="game"),
    pytest.param(DamageSubtypesWorldbuilderPatch, WORLDBUILDER, WORLDBUILDER_SECTION_NAME, id="wb"),
]


def stand_in(target: ds._Target) -> bytearray:
    """The pages a target's patch touches: the stock strings, each distinct stock table (with the
    next table's first entry right behind its NULL, which is why none can grow in place), and the
    three field descriptors' `userData` slots."""
    planted: dict[int, bytes] = {}
    strings_va = _STRINGS_VA[target]
    blob = bytearray()
    pointers = []
    for name in STOCK_NAMES:
        pointers.append(strings_va + len(blob))
        blob += name.encode("ascii") + b"\x00"
    planted[strings_va] = bytes(blob)
    for slot_va, table_va in target.refs:
        planted[table_va] = struct.pack("<6I", *pointers, 0, strings_va)
        planted[slot_va] = struct.pack("<I", table_va)
    return _sparse_image(planted)


def slot(data: bytes | bytearray, va: int) -> int:
    return struct.unpack_from("<I", data, va_to_offset(data, va))[0]


@pytest.mark.parametrize(("cls", "target", "section"), _PAIRS)
class TestApply:
    def test_apply_then_verify_and_detect(self, cls, target, section):
        data = stand_in(target)
        cls().apply(data)
        assert cls().verify(data) == []
        assert cls.detect(data).names == DEFAULT_NAMES

    def test_every_slot_reads_the_one_new_table(self, cls, target, section):
        data = stand_in(target)
        cls().apply(data)
        section_va = find_section(data, section)[0]
        assert {slot(data, va) for va, _ in target.refs} == {section_va}

    def test_stock_names_keep_their_pointers_and_index_4_is_unnameable(self, cls, target, section):
        """The stock entries are copied by pointer, so nothing already parsed moves. Slot 4 is the
        module's default trigger value: it must hold *something* (a NULL would end the table) that
        no INI token can equal, which a string with a space in it guarantees."""
        data = stand_in(target)
        stock = struct.unpack_from("<4I", data, va_to_offset(data, target.refs[0][1]))
        cls(("WEBBED",)).apply(data)
        names = ds._read_names(data, find_section(data, section)[0])
        assert names == [*STOCK_NAMES, RESERVED_NAME, "WEBBED"]
        table_va = find_section(data, section)[0]
        assert struct.unpack_from("<4I", data, va_to_offset(data, table_va)) == stock
        assert " " in RESERVED_NAME
        assert names.index("WEBBED") == FIRST_NEW_INDEX == 5

    def test_detect_recovers_custom_names(self, cls, target, section):
        data = stand_in(target)
        cls(("WEBBED", "COCOON")).apply(data)
        assert cls.detect(data).names == ("WEBBED", "COCOON")

    def test_an_unpatched_image_is_not_detected(self, cls, target, section):
        data = stand_in(target)
        assert cls.detect(data) is None
        assert cls().verify(data) != []

    def test_a_second_apply_is_refused(self, cls, target, section):
        data = stand_in(target)
        cls().apply(data)
        with pytest.raises(ValueError, match="already patched"):
            cls().apply(data)

    def test_a_table_naming_something_else_is_refused(self, cls, target, section):
        data = stand_in(target)
        strings_off = va_to_offset(data, _STRINGS_VA[target])
        data[strings_off : strings_off + 6] = b"FOOBAR"
        with pytest.raises(ValueError, match="unexpected build"):
            cls().apply(data)


class TestOptions:
    @pytest.mark.parametrize(
        "names",
        [(), ("SELF",), ("WEBBED", "WEBBED"), ("webbed",), ("HAS SPACE",)],
        ids=["empty", "stock", "repeated", "lowercase", "space"],
    )
    def test_rejects_bad_names(self, names):
        with pytest.raises(ValueError):
            DamageSubtypesPatch(names)

    def test_ini_surface_states_each_index(self):
        members = DamageSubtypesPatch(("WEBBED", "COCOON")).ini_surface().enum_members
        assert [(m.enum, m.name, m.value) for m in members] == [
            ("DamageSubType", "WEBBED", 5),
            ("DamageSubType", "COCOON", 6),
        ]

    def test_cli_round_trip(self):
        parser = argparse.ArgumentParser()
        DamageSubtypesPatch.add_cli_arguments(parser)
        patch = DamageSubtypesPatch.from_cli_args(parser.parse_args(["--names", "WEBBED, COCOON"]))
        assert patch.names == ("WEBBED", "COCOON")
        assert DamageSubtypesPatch.from_cli_args(parser.parse_args([])).names == DEFAULT_NAMES


class TestRealBinary:
    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_round_trip_on_game_dat(self):
        data = bytearray(_GAME_DAT.read_bytes())
        DamageSubtypesPatch().apply(data)
        assert DamageSubtypesPatch().verify(data) == []
        assert DamageSubtypesPatch.detect(data).names == DEFAULT_NAMES
