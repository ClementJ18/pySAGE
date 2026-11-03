"""`ash-weather` chained with `desert-weather`, executed.

A link cave that jumps one byte wrong applies and verifies, then flags the wrong bit on every
object - so both hook sites are run under Unicorn from the engine's own entry point, for each of
the four weathers and with the two patches applied in both orders. The setter and the propagate
helper they call are answered in Python.
"""

from __future__ import annotations

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from sage_patch.patches.render.ash_weather import AshWeatherPatch  # noqa: E402
from sage_patch.patches.render.desert_weather import DesertWeatherPatch  # noqa: E402
from sage_patch.patches.utils import map_weather, model_conditions  # noqa: E402
from sage_patch.patches.utils.map_weather import BIND_SITE, UPGRADE_SITE  # noqa: E402

from .save_machine import Machine  # noqa: E402
from .synthetic import synthetic_image  # noqa: E402


@pytest.fixture(scope="module")
def clean() -> bytearray:
    return synthetic_image()


class TestEmulated:
    """Both chained caves, executed from the hook site for each of the four weathers."""

    @pytest.fixture(params=[True, False], ids=["ash-first", "desert-first"])
    def machine(self, clean: bytearray, request: pytest.FixtureRequest):
        image = bytearray(clean)
        patches = [AshWeatherPatch(), DesertWeatherPatch()]
        for patch in patches if request.param else patches[::-1]:
            patch.apply(image)
        table = model_conditions.read(image)
        bits = {n: table.index_of(image, n) for n in ("SAND", "ASHEN")}
        return Machine(bytes(image)), bits

    @pytest.mark.parametrize("weather", [0, 1, 2, 3])
    def test_bind_sets_exactly_the_conditions_of_the_weather(self, machine, weather: int):
        m, bits = machine
        calls: dict[int, int] = {}

        def set_bit(mm) -> None:
            calls[mm.arg(0)] = mm.arg(1) & 0xFF
            mm.ret(8)

        m.stub(map_weather._SET_BIT_VA, set_bit)
        m.stop_at(BIND_SITE.return_va)
        global_data = m.alloc(0x200, b"\x00" * 0x200)
        m.write32(global_data + map_weather.WEATHER_OFFSET, weather)
        m.call(BIND_SITE.site_va, esi=global_data, ebp=m.frame())
        assert m.stopped_at == BIND_SITE.return_va
        assert calls == {
            map_weather.SNOW_BIT: int(weather == 1),
            bits["SAND"]: int(weather == 2),
            bits["ASHEN"]: int(weather == 3),
        }

    @pytest.mark.parametrize("weather", [0, 1, 2, 3])
    def test_upgrade_expiry_restores_only_the_current_weathers_condition(
        self, machine, weather: int
    ):
        m, bits = machine
        propagated: list[int] = []
        m.stub(map_weather._PROPAGATE_VA, lambda mm: (propagated.append(1), mm.ret(0)))
        m.stop_at(UPGRADE_SITE.return_va)

        global_data = m.alloc(0x200, b"\x00" * 0x200)
        m.write32(global_data + map_weather.WEATHER_OFFSET, weather)
        m.ensure(map_weather.GLOBAL_DATA_VA)
        m.write32(map_weather.GLOBAL_DATA_VA, global_data)

        obj = m.alloc(0x200, b"\x00" * 0x200)
        module = m.alloc(0x20, b"\x00" * 0x20) + 0x10
        m.write32(module - 8, obj)
        ebp = m.frame(0x200)
        every = [map_weather.SNOW_BIT, bits["SAND"], bits["ASHEN"]]
        for bit in every:  # the expiring upgrade cleared all three
            at = ebp + map_weather._UPGRADE_FLAGS_DISP + (bit // 32) * 4
            m.write32(at, m.read32(at) | 1 << (bit % 32))

        m.call(UPGRADE_SITE.site_va, esi=module, ebp=ebp)
        assert m.stopped_at == UPGRADE_SITE.return_va

        def has(bit: int) -> bool:
            word = m.read32(obj + model_conditions.MASK_OFFSET + (bit // 32) * 4)
            return bool(word >> (bit % 32) & 1)

        want = {1: map_weather.SNOW_BIT, 2: bits["SAND"], 3: bits["ASHEN"]}.get(weather)
        assert [bit for bit in every if has(bit)] == ([want] if want is not None else [])
        assert len(propagated) == (want is not None)
