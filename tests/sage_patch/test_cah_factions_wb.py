"""Tests for the Worldbuilder half of the Create-A-Hero faction patch.

There is no hand-written code in this one - the cave is a pointer table and its strings - so the
tests are about the data, about the checks that stop it being applied to the wrong thing, and
about the one thing neither binary would ever report.

That one thing is :meth:`TestBothHalves.test_the_two_halves_agree_on_every_index`. A resolved
token is stored as an **index**, so the editor and the game have to lay the table out identically.
Nothing at runtime compares them: a mod side that landed at 10 in `game.dat` and 11 in the editor
would simply mean a different faction in each, and the INI would look right in both.
"""

from __future__ import annotations

import argparse
import struct

import pytest

from sage_patch.patches import cah_factions as cf
from sage_patch.patches.cah_factions import (
    ALL_INDEX,
    ALL_NAME,
    MAX_SIDES,
    STOCK_SIDES,
    WORLDBUILDER_BOUND_SITES,
    WORLDBUILDER_DEFAULT_FACTION_USERDATA_VA,
    WORLDBUILDER_INI_TABLE_VA,
    WORLDBUILDER_SECTION_NAME,
    WORLDBUILDER_TABLE_REF_SITES,
    WORLDBUILDER_TABLE_VA,
    WORLDBUILDER_TERMINATOR_SITE,
    WORLDBUILDER_TERMINATOR_VA,
    CahFactionsPatch,
    CahFactionsWorldbuilderPatch,
)
from sage_patch.patches.utils.name_tables import read_cstring, read_terminated
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import cah_factions_worldbuilder_image

SIDES = ("Rohan", "Lothlorien")


@pytest.fixture(scope="module")
def clean() -> bytearray:
    return cah_factions_worldbuilder_image()


@pytest.fixture
def image(clean: bytearray) -> bytearray:
    return bytearray(clean)


def cave_names(data: bytes | bytearray) -> list[str | None]:
    """The rebuilt table as names, read the way the editor reads it - to the NULL terminator."""
    base_va, _off, _vsize = find_section(data, WORLDBUILDER_SECTION_NAME)
    return [read_cstring(data, p) for p in read_terminated(data, base_va, "cave")]


def dword_at(data: bytes | bytearray, va: int) -> int:
    return struct.unpack_from("<I", data, va_to_offset(data, va))[0]


class TestBuildInvariants:
    def test_the_two_stock_tables_are_the_pair_the_game_has(self, clean: bytearray):
        """Both of Worldbuilder's copies hold the same nine names in the same order as
        `game.dat`'s, which is the premise the whole twin rests on: one rebuilt table can replace
        both, and the indices it hands out are the indices the game half hands out."""
        for base_va in (WORLDBUILDER_TABLE_VA, WORLDBUILDER_INI_TABLE_VA):
            pointers = read_terminated(clean, base_va, "side table")
            assert [read_cstring(clean, p) for p in pointers] == list(STOCK_SIDES)

    def test_the_default_faction_userdata_names_the_ini_copy(self, clean: bytearray):
        """The `SubClass` field descriptor is the only thing that reads the second copy, so it is
        the only site that has to move with it."""
        userdata = dword_at(clean, WORLDBUILDER_DEFAULT_FACTION_USERDATA_VA)
        assert userdata == WORLDBUILDER_INI_TABLE_VA

    def test_the_terminator_site_holds_an_address_into_the_table(self):
        """`testNameArray` checks `table[9] == NULL` through a baked absolute address rather than
        by indexing the table it was handed, so it is the one site that does not simply take the
        new base."""
        assert WORLDBUILDER_TERMINATOR_VA == WORLDBUILDER_TABLE_VA + len(STOCK_SIDES) * 4

    def test_every_bound_fits_an_imm8_at_the_ceiling(self):
        """All ten bit-count sites encode their `9` as an `imm8`, so the patch can only rewrite
        them in place while the new count stays under 128. `MAX_SIDES` caps it at 32, which is the
        same ceiling the 32-bit mask imposes - but that is two separate reasons agreeing, so it is
        worth one assertion of its own."""
        assert CahFactionsWorldbuilderPatch(sides=[f"S{i}" for i in range(MAX_SIDES)]).entry_count
        assert ALL_INDEX + 1 + MAX_SIDES <= 0x7F

    def test_the_site_lists_hold_no_duplicates(self):
        """Every site is written once. A VA listed twice would have its stock bytes asserted
        against bytes the first edit had already replaced."""
        refs = [va for va, _prefix in WORLDBUILDER_TABLE_REF_SITES]
        bounds = [va for va, _prefix in WORLDBUILDER_BOUND_SITES]
        assert len(set(refs)) == len(refs)
        assert len(set(bounds)) == len(bounds)
        assert set(refs).isdisjoint(bounds)
        assert WORLDBUILDER_TERMINATOR_SITE[0] not in set(refs) | set(bounds)


class TestBothHalves:
    def test_the_two_halves_agree_on_every_index(self):
        """What the parse stores is the index, so the editor's table and the game's have to be the
        same list. Both halves build it from the same three constants in this module, and this is
        the assertion that says so out loud."""
        sides = ("Rohan", "Imladris", "Lothlorien")
        expected = [*STOCK_SIDES, ALL_NAME, *sides]
        game = CahFactionsPatch(sides=sides)
        editor = CahFactionsWorldbuilderPatch(sides=sides)

        assert game.entry_count == editor.entry_count == len(expected)
        assert [d.name for d in game.ini_surface().enum_members] == [ALL_NAME, *sides]
        assert [d.value for d in game.ini_surface().enum_members] == [
            expected.index(name) for name in (ALL_NAME, *sides)
        ]

    def test_the_editor_half_declares_no_ini_surface(self):
        """The surface belongs to the game half; a twin reporting one would write the tokens into
        `.sagepatch` twice. `TestNameTableTokensHaveAWorldbuilderTwin` checks this across every
        twin - here for the reason it matters to this pair."""
        assert CahFactionsWorldbuilderPatch(sides=SIDES).ini_surface().enum_members == ()

    def test_it_rejects_the_names_the_game_half_rejects(self):
        """One validator, in one place, so the two halves cannot be given lists one accepts and
        the other does not - which would be a build with a table in only one binary."""
        for name in ("Men", "All", "Goblins", "+Rohan", "Ro han", ""):
            with pytest.raises(ValueError):
                CahFactionsWorldbuilderPatch(sides=[name])
        with pytest.raises(ValueError):
            CahFactionsWorldbuilderPatch(sides=[f"S{i}" for i in range(MAX_SIDES + 1)])


class TestApply:
    def test_apply_then_verify(self, image: bytearray):
        CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)
        assert CahFactionsWorldbuilderPatch(sides=SIDES).verify(image) == []

    def test_verify_rejects_an_unpatched_image(self, clean: bytearray):
        assert CahFactionsWorldbuilderPatch(sides=SIDES).verify(clean) != []

    def test_verify_rejects_a_different_side_list(self, image: bytearray):
        CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)
        assert CahFactionsWorldbuilderPatch(sides=("Rohan",)).verify(image) != []

    def test_the_table_reads_back_as_the_stock_nine_then_all_then_the_sides(self, image: bytearray):
        """The stock entries are copied through by pointer, so they keep their original strings as
        well as their indices - the `All` bit is only meaningful because nothing above it moved."""
        CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)
        assert cave_names(image) == [*STOCK_SIDES, ALL_NAME, *SIDES]

    def test_both_stock_copies_are_repointed_at_the_one_rebuilt_table(self, image: bytearray):
        """The editor's two copies become one. `DefaultFaction` and `UsableFactions` resolve a
        token against the same list after this, which is what stops a `SubClass` naming a side in
        one field and not the other."""
        CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)
        base_va, _off, _vsize = find_section(image, WORLDBUILDER_SECTION_NAME)
        for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
            assert dword_at(image, va + len(prefix)) == base_va
        assert dword_at(image, WORLDBUILDER_DEFAULT_FACTION_USERDATA_VA) == base_va

    def test_every_bit_count_becomes_the_new_entry_count(self, image: bytearray):
        """Ten sites, one number. Leaving any of them at nine would send `All` and every mod side
        into `BitFlags<9,FactionType>`'s assert path instead of into the mask."""
        patch = CahFactionsWorldbuilderPatch(sides=SIDES)
        patch.apply(image)
        for va, prefix in WORLDBUILDER_BOUND_SITES:
            assert image[va_to_offset(image, va) + len(prefix)] == patch.entry_count

    def test_the_terminator_check_follows_the_table(self, image: bytearray):
        """`testNameArray` asserts the entry past the last name is NULL. It reads that entry by a
        baked address, so the address has to become the new table's terminator - otherwise the
        editor asserts "Someone forgot to update s_bitNameList" on a table that is correct."""
        patch = CahFactionsWorldbuilderPatch(sides=SIDES)
        patch.apply(image)
        base_va, _off, _vsize = find_section(image, WORLDBUILDER_SECTION_NAME)
        va, prefix = WORLDBUILDER_TERMINATOR_SITE
        assert dword_at(image, va + len(prefix)) == base_va + patch.entry_count * 4
        assert dword_at(image, base_va + patch.entry_count * 4) == 0

    def test_no_sides_still_installs_the_all_token(self, image: bytearray):
        """`--sides` is optional; `All` is not. Applied bare, the patch still buys a mod the
        "every side, present or future" token, and the table grows by exactly one."""
        patch = CahFactionsWorldbuilderPatch()
        patch.apply(image)
        assert patch.verify(image) == []
        assert cave_names(image) == [*STOCK_SIDES, ALL_NAME]
        assert patch.entry_count == ALL_INDEX + 1


class TestItRefusesTheWrongBinary:
    def test_a_table_that_is_not_this_builds_stops_it(self, image: bytearray):
        """The names are checked, not just the count: a build whose table held the same nine
        pointers in a different order would hand every mod side a different index."""
        base = va_to_offset(image, WORLDBUILDER_TABLE_VA)
        first, second = struct.unpack_from("<II", image, base)
        struct.pack_into("<II", image, base, second, first)
        with pytest.raises(ValueError, match="unexpected build"):
            CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)

    def test_the_second_copy_is_checked_too(self, image: bytearray):
        """One rebuilt table replaces both copies, so a build where they had drifted apart needs
        more than this patch - and it is better to hear that than to give `DefaultFaction` the
        other copy's strings."""
        base = va_to_offset(image, WORLDBUILDER_INI_TABLE_VA)
        struct.pack_into("<I", image, base, 0)
        with pytest.raises(ValueError, match="DefaultFaction userData copy"):
            CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)

    def test_an_image_that_opts_in_to_aslr_stops_it(self, image: bytearray):
        """The cave holds absolute string pointers and nothing adds relocations covering them, so
        a rebased image would index strings that are no longer there."""
        e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
        struct.pack_into("<H", image, e_lfanew + 24 + 70, 0x0040)  # DYNAMIC_BASE
        with pytest.raises(ValueError, match="DYNAMIC_BASE"):
            CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)


class TestDetect:
    def test_it_recovers_the_sides(self, image: bytearray):
        """The default probe would build the patch with no sides and answer "not patched" for an
        editor carrying any - the one case detection exists for."""
        CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)
        found = CahFactionsWorldbuilderPatch.detect(image)
        assert found is not None
        assert found.sides == SIDES

    def test_it_answers_none_for_an_unpatched_image(self, clean: bytearray):
        assert CahFactionsWorldbuilderPatch.detect(clean) is None

    def test_it_answers_none_when_a_site_was_left_behind(self, image: bytearray):
        """Detection ends in `verify`, so a half-applied editor - the cave written and a bound
        left at nine - reads as unpatched rather than as carrying the patch."""
        CahFactionsWorldbuilderPatch(sides=SIDES).apply(image)
        va, prefix = WORLDBUILDER_BOUND_SITES[0]
        image[va_to_offset(image, va) + len(prefix)] = len(STOCK_SIDES)
        assert CahFactionsWorldbuilderPatch.detect(image) is None


class TestCli:
    def test_the_sides_round_trip_through_the_command_line(self):
        parser = _parser()
        CahFactionsWorldbuilderPatch.add_cli_arguments(parser)
        args = parser.parse_args(["--sides", "Rohan, Lothlorien"])
        assert CahFactionsWorldbuilderPatch.from_cli_args(args).sides == SIDES

    def test_no_sides_is_the_default(self):
        parser = _parser()
        CahFactionsWorldbuilderPatch.add_cli_arguments(parser)
        assert CahFactionsWorldbuilderPatch.from_cli_args(parser.parse_args([])).sides == ()


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser()


def test_the_module_holds_both_halves():
    """One module for the pair, so the two are read and edited together - a rename that reached
    only one binary would be a silent index shift, not a load error."""
    assert CahFactionsPatch.__module__ == CahFactionsWorldbuilderPatch.__module__ == cf.__name__
