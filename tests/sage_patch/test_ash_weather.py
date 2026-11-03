"""Tests for the ASH_RAIN weather / ASHEN model condition patch, and its composition with
`desert-weather` through the shared `map_weather` helper.

The point of the pair is that a map's weather is an **integer**, so `ASH_RAIN` must be 3 and
`DESERT` 2 on every stack, in every order - and that the two hook sites both patches take over
end up running both conditions. The chained caves are executed in `test_ash_weather_emulated.py`.
"""

from __future__ import annotations

import itertools
import struct
from pathlib import Path

import pytest

from sage_patch.patches.economy.production_condition import ProductionConditionPatch
from sage_patch.patches.render.ash_weather import (
    _SECTION_NAME,
    WEATHER_INDEX,
    WORLDBUILDER_SECTION_NAME,
    AshWeatherPatch,
    AshWeatherWorldbuilderPatch,
)
from sage_patch.patches.render.desert_weather import _SECTION_NAME as DESERT_SECTION
from sage_patch.patches.render.desert_weather import (
    DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch,
)
from sage_patch.patches.utils import map_weather, model_conditions
from sage_patch.patches.utils.map_weather import (
    _ANY_WEATHER_DEFAULT_VA,
    _ANY_WEATHER_TEST_VA,
    BIND_SITE,
    UPGRADE_SITE,
    WEATHER_TABLE_REF_VAS,
    WORLDBUILDER_COMBO_BOUND_VA,
    WORLDBUILDER_TABLE_REF_SITES,
)
from sage_patch.sagepatch import name_table_members
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import synthetic_image, worldbuilder_image

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture(scope="module")
def clean() -> bytearray:
    return synthetic_image()


@pytest.fixture
def image(clean: bytearray) -> bytearray:
    return bytearray(clean)


@pytest.fixture(scope="module")
def clean_wb() -> bytearray:
    return worldbuilder_image()


@pytest.fixture
def wb(clean_wb: bytearray) -> bytearray:
    return bytearray(clean_wb)


def live_names(data: bytes | bytearray) -> list[str]:
    return map_weather.live_weather_names(data)[2]


def wb_names(data: bytes | bytearray) -> list[str]:
    return map_weather.worldbuilder_live_names(data)[2]


def sentinel(data: bytes | bytearray) -> tuple[int, int]:
    default = struct.unpack_from("<I", data, va_to_offset(data, _ANY_WEATHER_DEFAULT_VA) + 6)[0]
    return default, data[va_to_offset(data, _ANY_WEATHER_TEST_VA) + 2]


def apply_all(data: bytearray, patches: list) -> None:
    for patch in patches:
        patch.apply(data)


class TestAlone:
    def test_apply_then_verify(self, image: bytearray):
        AshWeatherPatch().apply(image)
        assert AshWeatherPatch().verify(image) == []

    def test_verify_rejects_an_unpatched_image(self, clean: bytearray):
        assert AshWeatherPatch().verify(clean) != []

    def test_ash_rain_takes_slot_3_and_slot_2_is_held(self, image: bytearray):
        """Slot 2 is `desert-weather`'s, so alone it holds a placeholder rather than letting
        `ASH_RAIN` slide down to 2 - which would change what every map authored with it means."""
        AshWeatherPatch().apply(image)
        assert live_names(image) == ["NORMAL", "SNOWY", "RESERVED_WEATHER_2", "ASH_RAIN"]

    def test_the_any_weather_value_is_the_whole_table(self, image: bytearray):
        AshWeatherPatch().apply(image)
        assert sentinel(image) == (4, 4)

    def test_the_condition_is_named(self, image: bytearray):
        AshWeatherPatch().apply(image)
        table = model_conditions.read(image)
        assert table.index_of(image, "ASHEN") == model_conditions.STOCK_BIT_COUNT

    def test_the_ini_surface_states_slot_3(self):
        members = {(d.enum, d.name): d.value for d in AshWeatherPatch().ini_surface().enum_members}
        assert members[("MapWeatherType", "ASH_RAIN")] == WEATHER_INDEX == 3

    def test_the_generated_tokens_leave_the_placeholder_out(self, image: bytearray):
        AshWeatherPatch().apply(image)
        members, _notes = name_table_members(image)
        weathers = {d.name: d.value for d in members if d.enum == "MapWeatherType"}
        assert weathers == {"ASH_RAIN": 3}

    def test_applying_twice_raises(self, image: bytearray):
        AshWeatherPatch().apply(image)
        with pytest.raises(ValueError, match="already weather 3"):
            AshWeatherPatch().apply(image)

    def test_a_name_already_taken_is_refused(self, image: bytearray):
        with pytest.raises(ValueError, match="already weather"):
            AshWeatherPatch(weather="SNOWY").apply(image)

    def test_detect_recovers_custom_names(self, image: bytearray):
        AshWeatherPatch(weather="ASHFALL", condition="CINDER").apply(image)
        found = AshWeatherPatch.detect(image)
        assert found is not None
        assert (found.weather, found.condition) == ("ASHFALL", "CINDER")

    def test_an_unpatched_image_carries_nothing(self, image: bytearray):
        assert AshWeatherPatch.detect(image) is None


ORDERS = [
    pytest.param(order, id="+".join(type(p).__name__.removesuffix("Patch") for p in order))
    for order in itertools.permutations(
        [DesertWeatherPatch(), AshWeatherPatch(), ProductionConditionPatch()]
    )
]


class TestWithDesert:
    @pytest.mark.parametrize("ash_first", [True, False])
    def test_both_apply_and_verify_in_either_order(self, image: bytearray, ash_first: bool):
        patches = [AshWeatherPatch(), DesertWeatherPatch()]
        apply_all(image, patches if ash_first else patches[::-1])
        assert AshWeatherPatch().verify(image) == []
        assert DesertWeatherPatch().verify(image) == []

    @pytest.mark.parametrize("ash_first", [True, False])
    def test_the_indices_do_not_depend_on_the_order(self, image: bytearray, ash_first: bool):
        patches = [AshWeatherPatch(), DesertWeatherPatch()]
        apply_all(image, patches if ash_first else patches[::-1])
        assert live_names(image) == ["NORMAL", "SNOWY", "DESERT", "ASH_RAIN"]
        assert sentinel(image) == (4, 4)

    @pytest.mark.parametrize("ash_first", [True, False])
    def test_both_are_detected_with_their_names(self, image: bytearray, ash_first: bool):
        patches = [AshWeatherPatch(weather="ASHFALL"), DesertWeatherPatch(condition="DUNE")]
        apply_all(image, patches if ash_first else patches[::-1])
        ash, desert = AshWeatherPatch.detect(image), DesertWeatherPatch.detect(image)
        assert ash is not None and (ash.weather, ash.condition) == ("ASHFALL", "ASHEN")
        assert desert is not None and (desert.weather, desert.condition) == ("DESERT", "DUNE")

    @pytest.mark.parametrize("order", ORDERS)
    def test_all_three_condition_patches_compose_in_every_order(
        self, image: bytearray, order: tuple
    ):
        apply_all(image, list(order))
        for patch in order:
            assert patch.verify(image) == [], patch
        table = model_conditions.read(image)
        bits = {table.index_of(image, n) for n in ("SAND", "ASHEN", "PRODUCING")}
        assert bits == {model_conditions.STOCK_BIT_COUNT + i for i in range(3)}

    def test_the_second_patch_chains_in_front_of_the_first(self, image: bytearray):
        """The site jumps to the newest cave, which jumps on to the head that replaced the
        engine's block."""
        DesertWeatherPatch().apply(image)
        AshWeatherPatch().apply(image)
        ash_va, _off, ash_size = find_section(image, _SECTION_NAME)
        desert_va, _off, desert_size = find_section(image, DESERT_SECTION)
        for site in (BIND_SITE, UPGRADE_SITE):
            chain = map_weather.walk(image, site)
            assert len(chain) == 2
            assert ash_va <= chain[0].va < ash_va + ash_size
            assert desert_va <= chain[1].va < desert_va + desert_size
            assert chain[0].next_va == chain[1].va
            assert chain[1].next_va is None

    def test_a_chained_site_keeps_the_nop_padding(self, image: bytearray):
        DesertWeatherPatch().apply(image)
        AshWeatherPatch().apply(image)
        off = va_to_offset(image, BIND_SITE.site_va)
        assert bytes(image[off + 5 : off + len(BIND_SITE.original)]) == b"\x90" * (
            len(BIND_SITE.original) - 5
        )

    def test_desert_fills_the_placeholder_ash_left(self, image: bytearray):
        AshWeatherPatch().apply(image)
        DesertWeatherPatch().apply(image)
        assert "RESERVED_WEATHER_2" not in live_names(image)

    def test_every_reference_points_at_the_newest_table(self, image: bytearray):
        DesertWeatherPatch().apply(image)
        AshWeatherPatch().apply(image)
        bases = {
            struct.unpack_from("<I", image, va_to_offset(image, va))[0]
            for va in WEATHER_TABLE_REF_VAS
        }
        ash_va, _off, ash_size = find_section(image, _SECTION_NAME)
        assert len(bases) == 1
        assert ash_va <= next(iter(bases)) < ash_va + ash_size


class TestCaves:
    def disassemble(self, code: bytes, base: int):
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        return list(md.disasm(code, base))

    @pytest.mark.parametrize("site", [BIND_SITE, UPGRADE_SITE], ids=["bind", "upgrade"])
    def test_a_link_ends_in_a_jump_to_the_next_cave(self, site: map_weather.HookSite):
        base, next_va = 0x00F00000, 0x00F12340
        code = site.link(base, 600, 3, next_va)
        insns = self.disassemble(code, base)
        assert sum(i.size for i in insns) == len(code)
        assert insns[-1].mnemonic == "jmp" and int(insns[-1].op_str, 16) == next_va

    @pytest.mark.parametrize("site", [BIND_SITE, UPGRADE_SITE], ids=["bind", "upgrade"])
    def test_a_link_touches_no_callee_saved_register(self, site: map_weather.HookSite):
        for ins in self.disassemble(site.link(0x00F00000, 600, 3, 0x00F12340), 0x00F00000):
            written = ins.op_str.split(",")[0].strip()
            assert written not in ("esi", "edi", "ebx", "ebp", "esp")

    @pytest.mark.parametrize("site", [BIND_SITE, UPGRADE_SITE], ids=["bind", "upgrade"])
    def test_head_and_link_are_told_apart_by_their_first_weather(self, site: map_weather.HookSite):
        head = site.head(0, 600, 2)
        link = site.link(0, 600, 3, 0)
        assert head[site.weather_byte] == map_weather.WEATHER_SNOWY
        assert link[site.weather_byte] == 3

    @pytest.mark.parametrize("site", [BIND_SITE, UPGRADE_SITE], ids=["bind", "upgrade"])
    def test_sizes_do_not_depend_on_bit_or_weather(self, site: map_weather.HookSite):
        assert len(site.link(0, 0, 0, 0)) == len(site.link(0, 607, 9, 0xFFFF0000))
        assert len(site.head(0, 0, 0)) == len(site.head(0, 607, 9))


class TestWorldbuilder:
    def test_alone_it_holds_slot_2_and_lists_the_whole_table(self, wb: bytearray):
        AshWeatherWorldbuilderPatch().apply(wb)
        assert AshWeatherWorldbuilderPatch().verify(wb) == []
        assert wb_names(wb) == ["NORMAL", "SNOWY", "RESERVED_WEATHER_2", "ASH_RAIN"]
        assert wb[va_to_offset(wb, WORLDBUILDER_COMBO_BOUND_VA) + 3] == 4

    @pytest.mark.parametrize("ash_first", [True, False])
    def test_both_compose_in_either_order(self, wb: bytearray, ash_first: bool):
        patches = [AshWeatherWorldbuilderPatch(), DesertWeatherWorldbuilderPatch()]
        apply_all(wb, patches if ash_first else patches[::-1])
        assert AshWeatherWorldbuilderPatch().verify(wb) == []
        assert DesertWeatherWorldbuilderPatch().verify(wb) == []
        assert wb_names(wb) == ["NORMAL", "SNOWY", "DESERT", "ASH_RAIN"]
        assert wb[va_to_offset(wb, WORLDBUILDER_COMBO_BOUND_VA) + 3] == 4
        assert AshWeatherWorldbuilderPatch.detect(wb) is not None
        assert DesertWeatherWorldbuilderPatch.detect(wb) is not None

    def test_every_reference_moves_to_the_newest_table(self, wb: bytearray):
        DesertWeatherWorldbuilderPatch().apply(wb)
        AshWeatherWorldbuilderPatch().apply(wb)
        section_va, _off, _size = find_section(wb, WORLDBUILDER_SECTION_NAME)
        for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
            got = struct.unpack_from("<I", wb, va_to_offset(wb, va) + len(prefix))[0]
            assert got == section_va

    def test_the_editor_and_the_game_agree_on_the_index(self):
        assert AshWeatherWorldbuilderPatch().weather == AshWeatherPatch().weather


@pytest.mark.full
@pytest.mark.skipif(not REAL_GAME_DAT.exists(), reason="needs the real game.dat")
@pytest.mark.parametrize("ash_first", [True, False])
def test_the_real_game_dat_takes_both_in_either_order(ash_first: bool):
    image = bytearray(REAL_GAME_DAT.read_bytes())
    patches = [AshWeatherPatch(), DesertWeatherPatch()]
    apply_all(image, patches if ash_first else patches[::-1])
    assert AshWeatherPatch().verify(image) == []
    assert DesertWeatherPatch().verify(image) == []
    assert live_names(image) == ["NORMAL", "SNOWY", "DESERT", "ASH_RAIN"]
