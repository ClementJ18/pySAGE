"""Tests for the Worldbuilder half of the DESERT weather patch.

There is no hand-written code in this one, so the tests are about the data and about the checks
that stop it being applied to the wrong thing.

The load-bearing assertion is :meth:`TestBuildInvariants.test_the_two_patches_agree_on_the_index`.
A map stores the weather as an **integer**, not a name, so the index Worldbuilder writes and the
index `game.dat` resolves have to be the same number. Nothing at runtime would report a mismatch -
the map would simply come out as some other weather - so the two patches agreeing is checked here
rather than trusted.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.patches import desert_weather as dw
from sage_patch.patches.desert_weather import (
    _WORLDBUILDER_DIALOG_FINGERPRINT,
    DEFAULT_WEATHER,
    STOCK_WEATHER_NAMES,
    WORLDBUILDER_COMBO_BOUND_VA,
    WORLDBUILDER_SECTION_NAME,
    WORLDBUILDER_TABLE_REF_SITES,
    WORLDBUILDER_WEATHER_TABLE_VA,
    DesertWeatherWorldbuilderPatch,
)
from sage_patch.patches.utils.model_conditions import read_cstring
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import worldbuilder_image


@pytest.fixture(scope="module")
def clean() -> bytearray:
    return worldbuilder_image()


@pytest.fixture
def image(clean: bytearray) -> bytearray:
    return bytearray(clean)


def names_at(data: bytes | bytearray, table_va: int, count: int = 4) -> list[str | None]:
    out: list[str | None] = []
    off = va_to_offset(data, table_va)
    for index in range(count):
        pointer = struct.unpack_from("<I", data, off + index * 4)[0]
        out.append(None if pointer == 0 else read_cstring(data, pointer))
    return out


def live_table_va(data: bytes | bytearray) -> int:
    """Wherever the combo loop currently reads its names from."""
    va, prefix = WORLDBUILDER_TABLE_REF_SITES[0]
    return struct.unpack_from("<I", data, va_to_offset(data, va) + len(prefix))[0]


class TestBuildInvariants:
    def test_the_two_patches_agree_on_the_index(self):
        """The map stores the weather as an integer. If Worldbuilder appended DESERT at a
        different index than `game.dat` resolves it to, every map authored here would come out as
        some other weather, silently."""
        assert len(STOCK_WEATHER_NAMES) == dw.NEW_WEATHER_INDEX
        assert STOCK_WEATHER_NAMES == dw.STOCK_WEATHER_NAMES

    def test_the_combo_bound_is_the_stock_member_count(self):
        """It is the same number as the `Sound`/`ViewShake` sentinel `game.dat` moves, and for the
        same reason: the engine's authors used the member count in place of a named constant."""
        assert len(STOCK_WEATHER_NAMES) == 2


class TestApply:
    def test_apply_then_verify(self, image: bytearray):
        DesertWeatherWorldbuilderPatch().apply(image)
        assert DesertWeatherWorldbuilderPatch().verify(image) == []

    def test_verify_rejects_an_unpatched_image(self, clean: bytearray):
        assert DesertWeatherWorldbuilderPatch().verify(clean) != []

    def test_desert_is_appended_and_the_stock_members_keep_their_indices(self, image: bytearray):
        """Appending rather than inserting is what keeps every existing map meaning what it meant,
        since a map stores the index."""
        DesertWeatherWorldbuilderPatch().apply(image)
        assert names_at(image, live_table_va(image)) == ["NORMAL", "SNOWY", "DESERT", None]

    def test_every_reference_is_repointed_into_the_cave(self, image: bytearray):
        DesertWeatherWorldbuilderPatch().apply(image)
        section_va, _off, vsize = find_section(image, WORLDBUILDER_SECTION_NAME)
        for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
            got = struct.unpack_from("<I", image, va_to_offset(image, va) + len(prefix))[0]
            assert got != WORLDBUILDER_WEATHER_TABLE_VA, (
                f"{va:#010x} still points at the stock table"
            )
            assert section_va <= got < section_va + vsize

    def test_the_dropdown_bound_is_raised_to_the_new_member_count(self, image: bytearray):
        DesertWeatherWorldbuilderPatch().apply(image)
        off = va_to_offset(image, WORLDBUILDER_COMBO_BOUND_VA)
        assert bytes(image[off : off + 3]) == bytes.fromhex("837de0"), "the cmp itself must stand"
        assert image[off + 3] == len(STOCK_WEATHER_NAMES) + 1

    def test_the_cave_holds_no_code(self, image: bytearray):
        """A pointer table and a string. Marking it executable would be a claim this patch does
        not need to make."""
        DesertWeatherWorldbuilderPatch().apply(image)
        section_va, _off, vsize = find_section(image, WORLDBUILDER_SECTION_NAME)
        assert vsize == (len(STOCK_WEATHER_NAMES) + 2) * 4 + 8  # table + NULL + "DESERT\0" padded
        e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
        nsec = struct.unpack_from("<H", image, e_lfanew + 6)[0]
        sectab = e_lfanew + 24 + struct.unpack_from("<H", image, e_lfanew + 20)[0]
        for index in range(nsec):
            header = sectab + index * 40
            if (
                bytes(image[header : header + 8]).rstrip(b"\x00")
                == WORLDBUILDER_SECTION_NAME.encode()
            ):
                characteristics = struct.unpack_from("<I", image, header + 36)[0]
                assert not characteristics & 0x20000000, "MEM_EXECUTE"
                assert not characteristics & 0x00000020, "CNT_CODE"
                break
        else:
            pytest.fail(f"no {WORLDBUILDER_SECTION_NAME} section header")

    def test_the_stock_table_is_left_where_it_was(self, image: bytearray):
        """It is orphaned, not overwritten - there is nothing to gain from destroying it, and
        leaving it makes the patch's effect visible as a diff of the references alone."""
        before = bytes(image[va_to_offset(image, WORLDBUILDER_WEATHER_TABLE_VA) :][:12])
        DesertWeatherWorldbuilderPatch().apply(image)
        assert bytes(image[va_to_offset(image, WORLDBUILDER_WEATHER_TABLE_VA) :][:12]) == before

    def test_applying_twice_raises_rather_than_corrupting(self, image: bytearray):
        DesertWeatherWorldbuilderPatch().apply(image)
        with pytest.raises(ValueError, match="already patched|already weather"):
            DesertWeatherWorldbuilderPatch().apply(image)

    def test_a_wrong_build_is_refused_by_the_table_contents(self, image: bytearray):
        pointer = struct.unpack_from(
            "<I", image, va_to_offset(image, WORLDBUILDER_WEATHER_TABLE_VA) + 4
        )[0]
        image[va_to_offset(image, pointer)] = ord("X")
        with pytest.raises(ValueError, match="unexpected build"):
            DesertWeatherWorldbuilderPatch().apply(image)

    @pytest.mark.parametrize("va", sorted(_WORLDBUILDER_DIALOG_FINGERPRINT))
    def test_a_build_whose_combo_box_moved_is_refused(self, image: bytearray, va: int):
        """The immediate being raised is an ordinary `cmp` against 2. Without the two window
        messages bracketing it, the same encoding elsewhere would be indistinguishable."""
        image[va_to_offset(image, va) + 1] ^= 0xFF
        with pytest.raises(ValueError, match="weather combo box"):
            DesertWeatherWorldbuilderPatch().apply(image)

    def test_a_moved_reference_is_refused(self, image: bytearray):
        va, prefix = WORLDBUILDER_TABLE_REF_SITES[1]
        struct.pack_into("<I", image, va_to_offset(image, va) + len(prefix), 0xDEADBEEF)
        with pytest.raises(ValueError, match="not the expected build"):
            DesertWeatherWorldbuilderPatch().apply(image)

    def test_an_aslr_image_is_refused(self, image: bytearray):
        """The cave's table holds absolute string addresses with no base-relocation entries, so a
        rebased image would index strings that are no longer there."""
        e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
        struct.pack_into("<H", image, e_lfanew + 24 + 70, 0x0040)  # DYNAMIC_BASE
        with pytest.raises(ValueError, match="ASLR"):
            DesertWeatherWorldbuilderPatch().apply(image)

    @pytest.mark.parametrize("bad", ["", "lower", "1LEADING", "HAS SPACE", "Mixed"])
    def test_names_the_ini_parser_could_never_match_are_refused(self, bad: str):
        with pytest.raises(ValueError, match="condition name"):
            DesertWeatherWorldbuilderPatch(weather=bad)

    def test_a_name_already_in_the_table_is_refused(self, image: bytearray):
        with pytest.raises(ValueError, match="already weather"):
            DesertWeatherWorldbuilderPatch(weather="SNOWY").apply(image)


class TestDetect:
    """**The gate on parameter recovery.** `verify` only answers "does this file carry *this*
    name", so the default probe reports a Worldbuilder patched under any other token as
    unpatched - which is the case detection exists for."""

    def test_it_recovers_a_non_default_name(self, image: bytearray):
        DesertWeatherWorldbuilderPatch(weather="ASHLAND").apply(image)
        found = DesertWeatherWorldbuilderPatch.detect(image)
        assert found is not None, "a patch applied under another name reports as absent"
        assert found.weather == "ASHLAND"

    def test_the_recovered_patch_verifies_against_the_binary_it_came_from(self, image: bytearray):
        DesertWeatherWorldbuilderPatch(weather="ASHLAND").apply(image)
        assert DesertWeatherWorldbuilderPatch.detect(image).verify(image) == []

    def test_it_still_recovers_the_default(self, image: bytearray):
        DesertWeatherWorldbuilderPatch().apply(image)
        assert DesertWeatherWorldbuilderPatch.detect(image).weather == DEFAULT_WEATHER

    def test_an_unpatched_image_carries_nothing(self, image: bytearray):
        assert DesertWeatherWorldbuilderPatch.detect(image) is None

    def test_detection_never_raises_on_something_that_is_not_a_worldbuilder(self):
        assert DesertWeatherWorldbuilderPatch.detect(bytearray(b"MZ" + bytes(4096))) is None
