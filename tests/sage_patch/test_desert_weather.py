"""Tests for the DESERT weather / SAND model condition patch.

Three kinds of thing are checked here.

The two caves are hand-encoded x86 that cannot be executed in a test, so the tests that matter
disassemble them back and assert they say what they were meant to say - a wrong byte does not
raise, it crashes the game or flags the wrong bit on the wrong object.

Then the data side: that the weather enum really gained a third member without disturbing the
first two, and that the "matches any weather" sentinel moved with the member count. That sentinel
is the one thing about this patch that fails *silently* if forgotten - `Weather = DESERT` on a
sound would simply mean "always", and nothing would report it.

Last, composition with `production-condition`, which wants a model condition of its own out of the
same table. Both orders must apply, and both patches must verify afterwards.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.patches.desert_weather import (
    _ANY_WEATHER_DEFAULT_VA,
    _ANY_WEATHER_TEST_VA,
    _BIND_ORIGINAL,
    _BIND_RETURN_VA,
    _BIND_SITE_VA,
    _SECTION_NAME,
    _UPGRADE_ORIGINAL,
    _UPGRADE_RETURN_VA,
    _UPGRADE_SITE_VA,
    NEW_WEATHER_INDEX,
    SNOW_BIT,
    STOCK_WEATHER_NAMES,
    WEATHER_OFFSET,
    WEATHER_TABLE_REF_VAS,
    WEATHER_TABLE_VA,
    DesertWeatherPatch,
    build_bind_code,
    build_upgrade_code,
)
from sage_patch.patches.production_condition import ProductionConditionPatch
from sage_patch.patches.utils import model_conditions
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import synthetic_image

BASE = 0x00F00000

#: The bit `SAND` lands on when this patch is the only one adding a condition.
SAND_BIT = model_conditions.STOCK_BIT_COUNT


@pytest.fixture(scope="module")
def clean() -> bytearray:
    """Built once - the image is ~10 MB and every test only reads or copies it."""
    return synthetic_image()


@pytest.fixture
def image(clean: bytearray) -> bytearray:
    return bytearray(clean)


def disassemble(code: bytes, base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(code, base))


def name_at(data: bytes | bytearray, table_va: int, index: int) -> str | None:
    pointer = struct.unpack_from("<I", data, va_to_offset(data, table_va) + index * 4)[0]
    return None if pointer == 0 else model_conditions.read_cstring(data, pointer)


class TestBuildInvariants:
    def test_desert_takes_the_slot_the_stock_count_occupied(self):
        """Which is exactly why the `any weather` sentinel has to move: it *is* the count."""
        assert NEW_WEATHER_INDEX == len(STOCK_WEATHER_NAMES) == 2

    def test_snow_is_the_bit_the_engine_hardcodes(self):
        assert SNOW_BIT == 8

    def test_both_replaced_blocks_are_wide_enough_for_a_jmp_rel32(self):
        assert len(_BIND_ORIGINAL) >= 5
        assert len(_UPGRADE_ORIGINAL) >= 5

    def test_the_replaced_blocks_end_where_the_caves_return(self):
        """A `jmp` back to anything but the first byte past the block would either skip engine
        code or land mid-instruction."""
        assert _BIND_SITE_VA + len(_BIND_ORIGINAL) == _BIND_RETURN_VA
        assert _UPGRADE_SITE_VA + len(_UPGRADE_ORIGINAL) == _UPGRADE_RETURN_VA


class TestTheBindCave:
    """The primary site: `Drawable::bindToObject` deciding a new drawable's conditions."""

    def code(self, bit: int = SAND_BIT) -> bytes:
        return build_bind_code(BASE, bit)

    def test_it_disassembles_cleanly_to_its_end(self):
        insns = disassemble(self.code())
        assert sum(i.size for i in insns) == len(self.code())

    def test_it_sets_both_conditions_through_the_engines_own_setter(self):
        """Two calls, both to `ModelConditionFlags::set`, so a false result *clears* the bit -
        an `or` would leave SNOW on after the weather changed."""
        calls = [i for i in disassemble(self.code()) if i.mnemonic == "call"]
        assert len({i.op_str for i in calls}) == 1, "both conditions go through one setter"
        assert len(calls) == 2

    def test_each_call_is_passed_its_own_bit_and_the_matching_weather(self):
        ops = [(i.mnemonic, i.op_str) for i in disassemble(self.code())]
        pushes = [op for mnemonic, op in ops if mnemonic == "push"]
        # `push <value>` then `push <bit>`, twice
        assert pushes == ["eax", f"{SNOW_BIT}", "eax", f"{SAND_BIT:#x}"]
        compares = [op for mnemonic, op in ops if mnemonic == "cmp"]
        assert compares == [
            f"dword ptr [esi + {WEATHER_OFFSET:#x}], 1",  # SNOWY
            f"dword ptr [esi + {WEATHER_OFFSET:#x}], {NEW_WEATHER_INDEX}",  # DESERT
        ]

    def test_nothing_between_a_compare_and_its_sete_touches_the_flags(self):
        """`lea` is in there precisely because it does not - swapping it for an `add` would make
        every model wear the condition."""
        insns = disassemble(self.code())
        for index, ins in enumerate(insns):
            if ins.mnemonic != "sete":
                continue
            between = insns[index - 1]
            assert between.mnemonic in ("cmp", "lea")

    def test_it_touches_no_callee_saved_register(self):
        """esi holds TheWritableGlobalData and edi the Drawable, and both are live at the join."""
        for ins in disassemble(self.code()):
            written = ins.op_str.split(",")[0].strip()
            assert written not in ("esi", "edi", "ebx", "ebp", "esp")

    def test_it_returns_to_the_instruction_after_the_block_it_replaced(self):
        insns = disassemble(self.code())
        assert insns[-1].mnemonic == "jmp"
        assert int(insns[-1].op_str, 16) == _BIND_RETURN_VA

    def test_its_size_does_not_depend_on_the_bit(self):
        """The tail layout computes the second cave's address from the first one's length, so a
        bit that changed the encoding size would silently misplace it."""
        assert len(build_bind_code(BASE, 0)) == len(build_bind_code(BASE, 600))

    def test_it_relocates_with_its_section(self):
        assert build_bind_code(BASE, SAND_BIT) != build_bind_code(BASE + 0x1000, SAND_BIT)


class TestTheUpgradeCave:
    """The secondary site: re-asserting a weather condition an expiring upgrade just cleared."""

    def code(self, bit: int = SAND_BIT) -> bytes:
        return build_upgrade_code(BASE, bit)

    def test_it_disassembles_cleanly_to_its_end(self):
        insns = disassemble(self.code())
        assert sum(i.size for i in insns) == len(self.code())

    def test_it_guards_every_write_with_a_read(self):
        """The engine's own shape. Without it, every expiring upgrade would push the mask to the
        `Drawable` whether or not anything actually changed."""
        insns = disassemble(self.code())
        writes = [i for i in insns if i.mnemonic == "or"]
        assert len(writes) == 2
        for write in writes:
            guards = [
                i
                for i in insns
                if i.mnemonic == "test" and i.address < write.address and "ecx" in i.op_str
            ]
            assert guards, f"the write at {write.address:#x} is unguarded"

    def test_it_touches_only_the_dword_holding_each_bit(self):
        for bit in (SNOW_BIT, SAND_BIT):
            word = model_conditions.MASK_OFFSET + (bit // 32) * 4
            mask = 1 << (bit % 32)
            matching = [
                i
                for i in disassemble(self.code())
                if i.mnemonic in ("test", "or") and f"[ecx + {word:#x}]" in i.op_str
            ]
            assert matching, f"bit {bit} is never written"
            for ins in matching:
                assert ins.op_str.endswith(f"{mask:#x}")

    def test_it_reads_the_cleared_mask_from_the_frame_and_the_object_from_this(self):
        ops = {(i.mnemonic, i.op_str) for i in disassemble(self.code())}
        assert ("mov", "ecx, dword ptr [esi - 8]") in ops  # Object*, at module+0x08
        assert any(mnemonic == "test" and "ebp -" in op for mnemonic, op in ops), (
            "the just-cleared mask lives in the frame"
        )

    def test_every_branch_stays_inside_the_cave_except_the_return(self):
        code = self.code()
        lo, hi = BASE, BASE + len(code)
        exits = set()
        for ins in disassemble(code):
            if not ins.mnemonic.startswith("j"):
                continue
            target = int(ins.op_str, 16)
            if not lo <= target < hi:
                exits.add((ins.mnemonic, target))
        assert exits == {("jmp", _UPGRADE_RETURN_VA)}

    def test_its_only_calls_are_the_propagate_helper(self):
        calls = {i.op_str for i in disassemble(self.code()) if i.mnemonic == "call"}
        assert len(calls) == 1, "both arms notify through the same helper"


class TestApply:
    def test_apply_then_verify(self, image: bytearray):
        DesertWeatherPatch().apply(image)
        assert DesertWeatherPatch().verify(image) == []

    def test_verify_rejects_an_unpatched_image(self, clean: bytearray):
        assert DesertWeatherPatch().verify(clean) != []

    def test_the_weather_enum_gains_a_third_member_and_keeps_the_first_two(self, image: bytearray):
        DesertWeatherPatch().apply(image)
        table_va = struct.unpack_from("<I", image, va_to_offset(image, WEATHER_TABLE_REF_VAS[0]))[0]
        assert [name_at(image, table_va, i) for i in range(4)] == [
            "NORMAL",
            "SNOWY",
            "DESERT",
            None,
        ]

    def test_every_weather_reference_is_repointed(self, image: bytearray):
        DesertWeatherPatch().apply(image)
        section_va, _off, vsize = find_section(image, _SECTION_NAME)
        for va in WEATHER_TABLE_REF_VAS:
            got = struct.unpack_from("<I", image, va_to_offset(image, va))[0]
            assert got != WEATHER_TABLE_VA, f"{va:#010x} still points at the stock table"
            assert section_va <= got < section_va + vsize

    def test_the_model_condition_is_named(self, image: bytearray):
        DesertWeatherPatch().apply(image)
        table = model_conditions.read(image)
        assert table.index_of(image, "SAND") == SAND_BIT
        assert table.count == model_conditions.STOCK_BIT_COUNT + 1

    def test_the_any_weather_sentinel_moves_with_the_member_count(self, image: bytearray):
        """The silent one. Left at 2, `Weather = DESERT` on a sound would mean `any weather`."""
        DesertWeatherPatch().apply(image)
        default_off = va_to_offset(image, _ANY_WEATHER_DEFAULT_VA) + 6
        assert struct.unpack_from("<I", image, default_off)[0] == NEW_WEATHER_INDEX + 1
        assert image[va_to_offset(image, _ANY_WEATHER_TEST_VA) + 2] == NEW_WEATHER_INDEX + 1

    @pytest.mark.parametrize("site", [_BIND_SITE_VA, _UPGRADE_SITE_VA])
    def test_each_block_becomes_a_jmp_into_the_cave(self, image: bytearray, site: int):
        DesertWeatherPatch().apply(image)
        section_va, _off, vsize = find_section(image, _SECTION_NAME)
        off = va_to_offset(image, site)
        assert image[off] == 0xE9
        target = site + 5 + struct.unpack_from("<i", image, off + 1)[0]
        assert section_va <= target < section_va + vsize

    @pytest.mark.parametrize(
        ("site", "original"),
        [(_BIND_SITE_VA, _BIND_ORIGINAL), (_UPGRADE_SITE_VA, _UPGRADE_ORIGINAL)],
    )
    def test_the_replaced_block_is_padded_out_with_nops(
        self, image: bytearray, site: int, original: bytes
    ):
        """Both blocks are jumped over as a whole; a short write would leave the tail of the
        original decoding as garbage."""
        DesertWeatherPatch().apply(image)
        off = va_to_offset(image, site)
        assert bytes(image[off + 5 : off + len(original)]) == b"\x90" * (len(original) - 5)

    def test_applying_twice_raises_rather_than_corrupting(self, image: bytearray):
        DesertWeatherPatch().apply(image)
        with pytest.raises(ValueError):
            DesertWeatherPatch().apply(image)

    def test_a_wrong_build_is_refused_by_the_weather_table(self, image: bytearray):
        pointer = struct.unpack_from("<I", image, va_to_offset(image, WEATHER_TABLE_VA) + 4)[0]
        image[va_to_offset(image, pointer)] = ord("X")
        with pytest.raises(ValueError, match="unexpected build"):
            DesertWeatherPatch().apply(image)

    def test_a_changed_block_is_refused_rather_than_overwritten(self, image: bytearray):
        """The blocks are *replaced*, not edited, so applying to a build whose code differs would
        destroy whatever was there."""
        image[va_to_offset(image, _BIND_SITE_VA) + 2] ^= 0xFF
        with pytest.raises(ValueError, match="not the expected build"):
            DesertWeatherPatch().apply(image)

    def test_a_name_that_is_already_a_model_condition_is_refused(self, image: bytearray):
        with pytest.raises(ValueError, match="already model condition"):
            DesertWeatherPatch(condition="JUST_BUILT").apply(image)

    @pytest.mark.parametrize("bad", ["", "lower", "1LEADING", "HAS SPACE", "Mixed"])
    def test_names_the_ini_parser_could_never_match_are_refused(self, bad: str):
        with pytest.raises(ValueError, match="condition name"):
            DesertWeatherPatch(weather=bad)


class TestComposition:
    """Both condition-adding patches share the name table and its ten count bounds."""

    @pytest.mark.parametrize("desert_first", [True, False])
    def test_both_patches_apply_and_verify_in_either_order(
        self, image: bytearray, desert_first: bool
    ):
        patches = [DesertWeatherPatch(), ProductionConditionPatch()]
        if not desert_first:
            patches.reverse()
        for patch in patches:
            patch.apply(image)
        assert DesertWeatherPatch().verify(image) == []
        assert ProductionConditionPatch().verify(image) == []

    @pytest.mark.parametrize("desert_first", [True, False])
    def test_the_two_conditions_land_on_adjacent_bits(self, image: bytearray, desert_first: bool):
        patches = [DesertWeatherPatch(), ProductionConditionPatch()]
        if not desert_first:
            patches.reverse()
        for patch in patches:
            patch.apply(image)
        table = model_conditions.read(image)
        bits = sorted([table.index_of(image, "SAND"), table.index_of(image, "PRODUCING")])
        assert bits == [model_conditions.STOCK_BIT_COUNT, model_conditions.STOCK_BIT_COUNT + 1]
        assert table.count == model_conditions.STOCK_BIT_COUNT + 2

    def test_the_second_condition_widens_the_xfer_blob(self, image: bytearray):
        """74 bytes cover bits 0..591 exactly, so the first added condition needs no change and
        the second one does. Both length constants have to move together."""
        DesertWeatherPatch().apply(image)
        for va in model_conditions.XFER_LENGTH_VAS:
            assert image[va_to_offset(image, va) + 1] == model_conditions.XFER_STOCK_LENGTH
        ProductionConditionPatch().apply(image)
        for va in model_conditions.XFER_LENGTH_VAS:
            assert image[va_to_offset(image, va) + 1] == model_conditions.XFER_STOCK_LENGTH + 1

    @pytest.mark.parametrize("desert_first", [True, False])
    def test_the_optional_halves_compose_too(self, image: bytearray, desert_first: bool):
        """`production-condition`'s weapon-set and locomotor tables are its own, but the model
        condition it adds alongside them is still the shared one - so the pair has to survive
        being applied either way round with the extras switched on."""
        production = ProductionConditionPatch(
            weapon_set_flag="PRODUCING_WEAPONS", locomotor_set="SET_PRODUCING"
        )
        patches = [DesertWeatherPatch(), production]
        if not desert_first:
            patches.reverse()
        for patch in patches:
            patch.apply(image)
        assert DesertWeatherPatch().verify(image) == []
        assert production.verify(image) == []

    def test_the_cave_carries_the_bit_it_was_built_for(self, image: bytearray):
        """`production-condition` applied afterwards shifts nothing about this cave, so verify
        must read the bit out of the cave rather than off the live table's tail."""
        DesertWeatherPatch().apply(image)
        ProductionConditionPatch().apply(image)
        section_va, _off, _vsize = find_section(image, _SECTION_NAME)
        assert name_at(image, section_va, SAND_BIT) == "SAND"
        assert DesertWeatherPatch().verify(image) == []


class TestDetect:
    """**The gate on parameter recovery.** `verify` only answers "does this file carry *these*
    names", so the default probe - which asks about `DESERT` -> `SAND` - reports a binary patched
    under any other pair as unpatched, which is the case detection exists for."""

    def test_it_recovers_both_non_default_names(self, image: bytearray):
        DesertWeatherPatch(weather="ASHLAND", condition="ASH").apply(image)
        found = DesertWeatherPatch.detect(image)
        assert found is not None, "a patch applied under other names reports as absent"
        assert (found.weather, found.condition) == ("ASHLAND", "ASH")

    def test_the_recovered_patch_verifies_against_the_binary_it_came_from(self, image: bytearray):
        DesertWeatherPatch(weather="ASHLAND", condition="ASH").apply(image)
        assert DesertWeatherPatch.detect(image).verify(image) == []

    def test_it_still_recovers_the_defaults(self, image: bytearray):
        DesertWeatherPatch().apply(image)
        found = DesertWeatherPatch.detect(image)
        assert (found.weather, found.condition) == ("DESERT", "SAND")

    def test_a_second_condition_patch_on_top_does_not_confuse_it(self, image: bytearray):
        """The condition is read out of this patch's own cave, not off the live table's tail, so
        another condition-adding patch applied afterwards cannot be mistaken for it."""
        DesertWeatherPatch(weather="ASHLAND", condition="ASH").apply(image)
        ProductionConditionPatch().apply(image)
        found = DesertWeatherPatch.detect(image)
        assert found is not None
        assert (found.weather, found.condition) == ("ASHLAND", "ASH")

    def test_an_unpatched_image_carries_nothing(self, image: bytearray):
        assert DesertWeatherPatch.detect(image) is None

    def test_detection_never_raises_on_something_that_is_not_a_game_dat(self):
        assert DesertWeatherPatch.detect(bytearray(b"MZ" + bytes(4096))) is None
