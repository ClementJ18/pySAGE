"""`repair-damage-cancel --min-damage`: the "damaged recently" flag, run in Unicorn over the real
probe.

The flag routine reads the body's last `DamageInfo` through a vtable call, so it is executed from
the probe's `wasDamagedWithin` call to the resume point, with that call and `getLastDamageInfo`
answered in Python, for hits below and above the threshold, a body without a record, an object
without a body and a NaN amount.
"""

from __future__ import annotations

import math
import struct

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from sage_patch.addresses import (  # noqa: E402
    BODY_GET_LAST_DAMAGE_INFO_SLOT,
    DAMAGE_INFO_DAMAGE_DEALT,
    GETTING_BUILT_RECENT_DAMAGE_RESULT,
    GETTING_BUILT_RECENT_DAMAGE_RESULT_BYTES,
    GETTING_BUILT_RECENT_DAMAGE_RESUME,
    OBJECT_BODY_MODULE,
)
from sage_patch.patches.structures.repair_damage_cancel import (  # noqa: E402
    FLAG_HOOK_WIDTH,
    RepairDamageCancelPatch,
    build_code,
)
from sage_patch.utils import find_section, read_bytes  # noqa: E402

from ..binaries import STOCK_GAME_DAT  # noqa: E402
from .save_machine import Machine  # noqa: E402

pytestmark = pytest.mark.skipif(not STOCK_GAME_DAT.is_file(), reason="no stock game.dat")

#: `push 4` - where the probe calls `wasDamagedWithin`; the run starts here.
_PROBE_CALL_SETUP = 0x00857EBA
_WAS_DAMAGED_WITHIN = 0x0068C933
#: Edain's threshold: no unupgraded archer's hit on a building reaches it.
MIN_DAMAGE = 5.0


@pytest.fixture(scope="module")
def stock() -> bytes:
    return STOCK_GAME_DAT.read_bytes()


def _patched(stock: bytes, min_damage: float = MIN_DAMAGE) -> bytearray:
    data = bytearray(stock)
    RepairDamageCancelPatch(min_damage=min_damage).apply(data)
    return data


def _flag(image: bytes, damaged: bool, dealt: float | None, body: bool = True) -> int:
    """Run the probe from its `wasDamagedWithin` call to the instruction after the flag, and
    return `[ebp-1]`. `dealt` None is a body with no damage record."""
    m = Machine(bytes(image))

    def was_damaged_within(machine: Machine) -> None:
        machine.ret(pop=8, value=1 if damaged else 0)

    m.stub(_WAS_DAMAGED_WITHIN, was_damaged_within)
    structure = m.alloc(0x400, b"\x00" * 0x400)
    if body:
        info = m.alloc(0x80, b"\x00" * 0x80)
        if dealt is not None:
            m.uc.mem_write(info + DAMAGE_INFO_DAMAGE_DEALT, struct.pack("<f", dealt))

        def get_last_damage_info(machine: Machine) -> None:
            machine.ret(value=0 if dealt is None else info)

        vtable = m.alloc(0x100, b"\x00" * 0x100)
        m.write32(vtable + BODY_GET_LAST_DAMAGE_INFO_SLOT, m.stub(None, get_last_damage_info))
        body_module = m.alloc(0x40, b"\x00" * 0x40)
        m.write32(body_module, vtable)
        m.write32(structure + OBJECT_BODY_MODULE, body_module)
    ebp = m.frame()
    m.uc.mem_write(ebp - 1, b"\xaa")  # neither answer, so a run that writes nothing shows
    m.stop_at(GETTING_BUILT_RECENT_DAMAGE_RESUME)
    esp = ebp - 0x80
    m.run(_PROBE_CALL_SETUP, esp, edi=structure, esi=structure, ebp=ebp)
    assert m.stopped_at == GETTING_BUILT_RECENT_DAMAGE_RESUME
    return m.uc.mem_read(ebp - 1, 1)[0]


@pytest.fixture(scope="module")
def image(stock) -> bytearray:
    return _patched(stock)


class TestTheFlag:
    def test_no_recent_hit_is_no_flag(self, image):
        assert _flag(image, damaged=False, dealt=500.0) == 0

    @pytest.mark.parametrize("dealt", [0.0, 0.25, 2.0, 4.99])
    def test_a_light_hit_does_not_count(self, image, dealt):
        assert _flag(image, damaged=True, dealt=dealt) == 0

    @pytest.mark.parametrize("dealt", [MIN_DAMAGE, 12.0, 400.0])
    def test_a_heavy_hit_counts(self, image, dealt):
        assert _flag(image, damaged=True, dealt=dealt) == 1

    def test_a_body_without_a_record_keeps_the_stock_answer(self, image):
        assert _flag(image, damaged=True, dealt=None) == 1

    def test_an_object_without_a_body_keeps_the_stock_answer(self, image):
        assert _flag(image, damaged=True, dealt=1.0, body=False) == 1

    def test_a_nan_amount_keeps_the_stock_answer(self, image):
        assert _flag(image, damaged=True, dealt=math.nan) == 1

    def test_stock_counts_every_hit(self, stock):
        assert _flag(stock, damaged=True, dealt=0.25) == 1
        assert _flag(stock, damaged=False, dealt=0.25) == 0

    def test_without_min_damage_every_hit_counts(self, stock):
        image = _patched(stock, min_damage=0.0)
        assert _flag(image, damaged=True, dealt=0.25) == 1
        assert _flag(image, damaged=False, dealt=0.25) == 0


def test_the_threshold_is_a_parameter(stock):
    image = _patched(stock, min_damage=1.0)
    assert _flag(image, damaged=True, dealt=2.0) == 1
    assert _flag(image, damaged=True, dealt=0.5) == 0


class TestTheBytes:
    def test_the_flag_hook_replaces_only_the_flag_store(self, stock, image):
        got = read_bytes(image, GETTING_BUILT_RECENT_DAMAGE_RESULT, FLAG_HOOK_WIDTH)
        assert got[0] == 0xE9
        assert got[5:] == b"\x90" * (FLAG_HOOK_WIDTH - 5)
        assert len(GETTING_BUILT_RECENT_DAMAGE_RESULT_BYTES) == FLAG_HOOK_WIDTH
        after = GETTING_BUILT_RECENT_DAMAGE_RESULT + FLAG_HOOK_WIDTH
        assert read_bytes(image, after, 16) == read_bytes(stock, after, 16)

    def test_without_min_damage_the_flag_store_is_stock(self, stock):
        image = _patched(stock, min_damage=0.0)
        got = read_bytes(image, GETTING_BUILT_RECENT_DAMAGE_RESULT, FLAG_HOOK_WIDTH)
        assert got == GETTING_BUILT_RECENT_DAMAGE_RESULT_BYTES

    def test_without_min_damage_the_cave_is_the_dismissal_alone(self, stock):
        image = _patched(stock, min_damage=0.0)
        located = find_section(image, ".rdcan")
        assert located is not None
        cave_va, cave_off, _ = located
        code = build_code(cave_va)
        assert bytes(image[cave_off : cave_off + len(code)]) == code
        assert len(build_code(cave_va, MIN_DAMAGE)) > len(code)


class TestDetect:
    @pytest.mark.parametrize("min_damage", [MIN_DAMAGE, 7.5, 0.0])
    def test_detect_recovers_the_threshold(self, stock, min_damage):
        found = RepairDamageCancelPatch.detect(bytes(_patched(stock, min_damage=min_damage)))
        assert found is not None
        assert found.options() == {"min_damage": min_damage}

    def test_another_threshold_does_not_verify(self, image):
        assert RepairDamageCancelPatch(min_damage=6.0).verify(image) != []
        assert RepairDamageCancelPatch().verify(image) != []

    def test_a_second_apply_refuses(self, image):
        with pytest.raises(ValueError):
            RepairDamageCancelPatch(min_damage=MIN_DAMAGE).apply(bytearray(image))

    def test_a_negative_threshold_is_refused(self):
        with pytest.raises(ValueError):
            RepairDamageCancelPatch(min_damage=-1)
