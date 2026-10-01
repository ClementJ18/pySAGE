"""Tests for the radar-structure-discs patch.

Both hooks are small, so what could still be wrong without raising is the register contract: that
`edi` really is the object at the KindOf load, that `bl` comes out as the painter expects, and that
`esi` holds the row at each span call. So the stock KindOf test and the stock circle span loop are
emulated, before and after the patch, against the engine's own `getRadarPriority` and bounds
check, with `DrawPixel` hooked to record what gets painted.
"""

from __future__ import annotations

import argparse
import faulthandler
import struct
from pathlib import Path

import pytest

from sage_ini.model.enums import RadarPriority
from sage_patch import RadarStructureDiscsPatch
from sage_patch.addresses import (
    OBJECT_GET_RADAR_PRIORITY,
    RADAR_BLIP_COLOUR,
    RADAR_BLIP_KINDOF_LOAD,
    RADAR_BLIP_KINDOF_SEQUENCE,
    RADAR_BLIP_KINDOF_SEQUENCE_BYTES,
    RADAR_CIRCLE_MIN_RADIUS,
    RADAR_CIRCLE_MIN_RADIUS_STOCK,
    RADAR_CIRCLE_RADIUS,
    RADAR_CIRCLE_RADIUS_BYTES,
    RADAR_CIRCLE_SPAN_CALLS,
    RADAR_CIRCLE_SPAN_LOOP,
    RADAR_CIRCLE_SPAN_LOOP_BYTES,
    RADAR_PIXEL_IN_BOUNDS,
    RADAR_PIXEL_IN_BOUNDS_BYTES,
    RADAR_PLOT_SPAN_ENDS,
    RADAR_PLOT_SPAN_ENDS_BYTES,
    RADAR_PRIORITY_STRUCTURE,
    SURFACE_DRAW_PIXEL,
)
from sage_patch.patches.radar_structure_discs import MAX_MIN_RADIUS, SECTION_NAME, build_cave
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, read_cstring, va_to_offset
from tests.sage_patch.synthetic import radar_structure_discs_image

#: Where the KindOf test ends: the `call` it sets up, which the emulation stops before.
KINDOF_TEST_END = RADAR_BLIP_KINDOF_SEQUENCE + len(RADAR_BLIP_KINDOF_SEQUENCE_BYTES) - 5
#: Where the span loop falls through once every span is drawn.
SPAN_LOOP_END = RADAR_CIRCLE_SPAN_LOOP + len(RADAR_CIRCLE_SPAN_LOOP_BYTES)

COMMANDCENTER_MASK = 1 << 17
#: The engine's order, Generals': `INVALID`, `NOT_ON_RADAR`, `STRUCTURE`, `UNIT`,
#: `LOCAL_UNIT_ONLY`. `TestStockBinaries` reads it back out of the name table.
INVALID, NOT_ON_RADAR, STRUCTURE, UNIT, LOCAL_UNIT_ONLY = range(5)
RADAR_PRIORITY_NAMES = 0x00DA3B24
#: `KindOf CAPTURABLE`, which `getRadarPriority` turns an unset priority into `STRUCTURE` for.
CAPTURABLE_BYTE, CAPTURABLE_MASK = 0x10E, 0x02


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    return located[0]


@pytest.fixture
def image() -> bytearray:
    return radar_structure_discs_image()


@pytest.fixture
def patched() -> bytearray:
    data = radar_structure_discs_image()
    RadarStructureDiscsPatch().apply(data)
    return data


class TestStructure:
    def test_the_kindof_load_calls_the_cave(self, patched: bytearray) -> None:
        cave = _cave_va(patched)
        want = call_rel32(RADAR_BLIP_KINDOF_LOAD, cave) + b"\x90"
        assert _read(patched, RADAR_BLIP_KINDOF_LOAD, 6) == want

    def test_both_span_calls_reach_the_fill(self, patched: bytearray) -> None:
        _code, _kindof, fill = build_cave(_cave_va(patched))
        for site in RADAR_CIRCLE_SPAN_CALLS:
            assert _read(patched, site, 5) == call_rel32(site, fill)

    def test_the_stock_span_routine_is_left_alone(self, patched: bytearray) -> None:
        """The fill replaces the calls, not the routine, so the stock bytes stay put."""
        got = _read(patched, RADAR_PLOT_SPAN_ENDS, len(RADAR_PLOT_SPAN_ENDS_BYTES))
        assert got == RADAR_PLOT_SPAN_ENDS_BYTES

    def test_nothing_else_in_the_kindof_test_moves(self, patched: bytearray) -> None:
        got = _read(patched, RADAR_BLIP_KINDOF_SEQUENCE, len(RADAR_BLIP_KINDOF_SEQUENCE_BYTES))
        hook = RADAR_BLIP_KINDOF_LOAD - RADAR_BLIP_KINDOF_SEQUENCE
        assert got[:hook] == RADAR_BLIP_KINDOF_SEQUENCE_BYTES[:hook]
        assert got[hook + 6 :] == RADAR_BLIP_KINDOF_SEQUENCE_BYTES[hook + 6 :]


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert RadarStructureDiscsPatch().verify(patched) == []
        assert isinstance(RadarStructureDiscsPatch.detect(patched), RadarStructureDiscsPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert RadarStructureDiscsPatch().verify(image) != []
        assert RadarStructureDiscsPatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            RadarStructureDiscsPatch().apply(patched)

    def test_a_drifted_span_loop_refuses_before_writing(self, image: bytearray) -> None:
        """A changed byte away from either call still breaks the `esi` = row contract."""
        off = va_to_offset(image, RADAR_CIRCLE_SPAN_LOOP)
        assert off is not None
        image[off + 0x13] ^= 0xFF  # the displacement of `mov esi, [ebp-0x24]`
        before = bytes(image)
        with pytest.raises(ValueError, match="circle span loop"):
            RadarStructureDiscsPatch().apply(image)
        assert bytes(image) == before

    def test_registered_as_settled(self) -> None:
        assert PATCHES["radar-structure-discs"] is RadarStructureDiscsPatch
        assert not RadarStructureDiscsPatch.experimental


class TestMinRadius:
    def test_the_default_leaves_the_engines_minimum(self, patched: bytearray) -> None:
        assert _read(patched, RADAR_CIRCLE_MIN_RADIUS, 1) == bytes([RADAR_CIRCLE_MIN_RADIUS_STOCK])
        detected = RadarStructureDiscsPatch.detect(patched)
        assert isinstance(detected, RadarStructureDiscsPatch)
        assert detected.min_radius == RADAR_CIRCLE_MIN_RADIUS_STOCK

    def test_a_raised_minimum_is_written_and_recovered(self, image: bytearray) -> None:
        RadarStructureDiscsPatch(min_radius=4).apply(image)
        assert _read(image, RADAR_CIRCLE_MIN_RADIUS - 1, 2) == b"\x6a\x04"  # push 4
        assert RadarStructureDiscsPatch(min_radius=4).verify(image) == []
        assert RadarStructureDiscsPatch().verify(image) != []
        detected = RadarStructureDiscsPatch.detect(image)
        assert isinstance(detected, RadarStructureDiscsPatch)
        assert detected.min_radius == 4
        assert detected.options() == {"min_radius": 4}

    @pytest.mark.parametrize("bad", (0, -1, MAX_MIN_RADIUS + 1))
    def test_out_of_range_refuses(self, bad: int) -> None:
        with pytest.raises(ValueError, match="min_radius"):
            RadarStructureDiscsPatch(min_radius=bad)

    def test_the_cli_option(self) -> None:
        parser = argparse.ArgumentParser()
        RadarStructureDiscsPatch.add_cli_arguments(parser)
        patch = RadarStructureDiscsPatch.from_cli_args(parser.parse_args(["--min-radius", "5"]))
        assert patch.min_radius == 5
        default = RadarStructureDiscsPatch.from_cli_args(parser.parse_args([]))
        assert default.min_radius == RADAR_CIRCLE_MIN_RADIUS_STOCK

    def test_a_drifted_radius_sequence_refuses(self, image: bytearray) -> None:
        off = va_to_offset(image, RADAR_CIRCLE_RADIUS)
        assert off is not None
        image[off + 1] ^= 0xFF  # the `[edi+0xb8]` operand
        with pytest.raises(ValueError, match="circle radius"):
            RadarStructureDiscsPatch(min_radius=4).apply(image)


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_RADAR_OBJECT, _OBJECT, _TEMPLATE = _HEAP, _HEAP + _PAGE, _HEAP + 2 * _PAGE
_SPANS = _HEAP + 3 * _PAGE
_COLOUR = 0x00FF2200
_EDX_SENTINEL = 0x5EED5EED


def _machine(data: bytes | bytearray, planted: tuple[int, ...], blank: tuple[int, ...] = ()) -> Uc:
    """A Unicorn with the stack, the heap and the cave mapped, the pages holding `planted` copied
    out of `data`, and the pages holding `blank` mapped empty for the test to fill."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    cave = find_section(data, SECTION_NAME)
    pages = {_STACK, _RADAR_OBJECT, _OBJECT, _TEMPLATE, _SPANS}
    pages |= {va & ~0xFFF for va in planted + blank}
    if cave is not None:
        pages.add(cave[0] & ~0xFFF)
    # `mem_map` raises and catches an SEH access violation inside Unicorn on Windows; every map
    # still succeeds, but the fault handler would print a stack for each one.
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        for page in sorted(pages):
            uc.mem_map(page, _PAGE)
    finally:
        if was_enabled:
            faulthandler.enable()
    for va in sorted(planted):
        page = va & ~0xFFF
        uc.mem_write(page, _read(data, page, _PAGE))
    if cave is not None:
        code = build_cave(cave[0])[0]
        uc.mem_write(cave[0], _read(data, cave[0], len(code)))
    return uc


def _blip_test(
    data: bytes | bytearray, kindof: int, priority: int, capturable: bool = False
) -> tuple[bool, int]:
    """Run the painter's KindOf test for one object and return whether `bl` picks the circle,
    plus `edx` as it was left."""
    uc = _machine(data, (RADAR_BLIP_KINDOF_SEQUENCE, OBJECT_GET_RADAR_PRIORITY))
    uc.mem_write(_RADAR_OBJECT + 4, struct.pack("<I", _OBJECT))
    uc.mem_write(_OBJECT + 4, struct.pack("<I", _TEMPLATE))
    uc.mem_write(_OBJECT + 0x258, struct.pack("<I", 0))  # no contain module
    uc.mem_write(_TEMPLATE + 0x108, struct.pack("<I", kindof))
    uc.mem_write(_TEMPLATE + 0x600, bytes([priority]))
    if capturable:
        uc.mem_write(_TEMPLATE + CAPTURABLE_BYTE, bytes([CAPTURABLE_MASK]))

    esp = _STACK + 0x800
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, esp + 0x40)
    uc.reg_write(UC_X86_REG_ESI, _RADAR_OBJECT)
    uc.reg_write(UC_X86_REG_EDX, _EDX_SENTINEL)
    uc.emu_start(RADAR_BLIP_KINDOF_SEQUENCE, KINDOF_TEST_END, count=256)
    assert uc.reg_read(UC_X86_REG_ECX) == _OBJECT  # the call after it still gets the object
    assert uc.reg_read(UC_X86_REG_ESP) == esp - 4  # only its own argument pushed
    return bool(uc.reg_read(UC_X86_REG_EBX) & 0xFF), uc.reg_read(UC_X86_REG_EDX)


class TestTheKindOfTestRuns:
    def test_stock_circles_only_a_command_centre(self, image: bytearray) -> None:
        assert _blip_test(image, COMMANDCENTER_MASK, UNIT)[0]
        assert not _blip_test(image, 0, STRUCTURE)[0]

    def test_patched_circles_a_structure(self, patched: bytearray) -> None:
        assert _blip_test(patched, 0, STRUCTURE)[0]

    def test_patched_still_circles_a_command_centre(self, patched: bytearray) -> None:
        assert _blip_test(patched, COMMANDCENTER_MASK, UNIT)[0]
        assert _blip_test(patched, COMMANDCENTER_MASK, STRUCTURE)[0]

    @pytest.mark.parametrize("priority", (INVALID, NOT_ON_RADAR, UNIT, LOCAL_UNIT_ONLY))
    def test_patched_leaves_other_priorities_as_dots(
        self, patched: bytearray, priority: int
    ) -> None:
        assert not _blip_test(patched, 0, priority)[0]

    def test_an_unset_priority_on_a_capturable_counts_as_a_structure(
        self, patched: bytearray
    ) -> None:
        """`getRadarPriority`'s own fallback: Edain's farms set no `RadarPriority` and still
        report STRUCTURE, because they are CAPTURABLE."""
        assert _blip_test(patched, 0, INVALID, capturable=True)[0]
        assert not _blip_test(patched, 0, UNIT, capturable=True)[0]

    def test_other_kindof_bits_do_not_leak_in(self, patched: bytearray) -> None:
        """Bits either side of COMMANDCENTER must not reach `bl` through the `or`."""
        noise = 0xFFFFFFFF & ~COMMANDCENTER_MASK
        assert not _blip_test(patched, noise, UNIT)[0]
        assert _blip_test(patched, noise, STRUCTURE)[0]

    def test_edx_survives(self, patched: bytearray) -> None:
        assert _blip_test(patched, 0, STRUCTURE)[1] == _EDX_SENTINEL


def _draw_circle(
    data: bytes | bytearray, spans: list[tuple[int, int, int]], centre_row: int
) -> set[tuple[int, int]]:
    """Run the circle's span loop over `spans` (`(row, a, b)`) and return every `(x, row)` passed
    to `DrawPixel`, checking each carried the blip colour."""
    uc = _machine(
        data,
        (RADAR_CIRCLE_SPAN_LOOP, RADAR_PLOT_SPAN_ENDS, RADAR_PIXEL_IN_BOUNDS),
        (SURFACE_DRAW_PIXEL, RADAR_BLIP_COLOUR),
    )
    uc.mem_write(SURFACE_DRAW_PIXEL, b"\xc2\x0c\x00")  # ret 0xc; the hook does the recording
    uc.mem_write(RADAR_BLIP_COLOUR, struct.pack("<I", _COLOUR))
    uc.mem_write(_SPANS, b"".join(struct.pack("<3i", *span) for span in spans))

    esp = _STACK + 0x800
    ebp = esp + 0x80
    uc.mem_write(ebp - 0x24, struct.pack("<i", 2 * centre_row))  # the mirror
    uc.mem_write(ebp - 0x54, struct.pack("<I", _SPANS + 12 * len(spans)))  # the end
    surface = ebp - 0x14

    drawn: set[tuple[int, int]] = set()

    def record(uc: Uc, _address: int, _size: int, _user: object) -> None:
        sp = uc.reg_read(UC_X86_REG_ESP)
        x, row, colour = struct.unpack("<iiI", bytes(uc.mem_read(sp + 4, 12)))
        assert uc.reg_read(UC_X86_REG_ECX) == surface
        assert colour == _COLOUR
        drawn.add((x, row))

    uc.hook_add(UC_HOOK_CODE, record, begin=SURFACE_DRAW_PIXEL, end=SURFACE_DRAW_PIXEL)
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_EDI, _SPANS)
    uc.reg_write(UC_X86_REG_EBX, _SPANS)
    uc.reg_write(UC_X86_REG_EAX, 0)
    uc.emu_start(RADAR_CIRCLE_SPAN_LOOP, SPAN_LOOP_END, count=100_000)
    assert uc.reg_read(UC_X86_REG_ESP) == esp
    return drawn


#: The lower half of a radius-2 circle about (10, 10), as the rasteriser hands it over.
_CIRCLE = [(10, 8, 12), (11, 8, 12), (12, 9, 11)]


def _rows(spans: list[tuple[int, int, int]], centre_row: int) -> set[tuple[int, int]]:
    full = set()
    for row, a, b in spans:
        lo, hi = min(a, b), max(a, b)
        for r in (row, 2 * centre_row - row):
            full |= {(x, r) for x in range(lo, hi + 1) if 0 <= x < 128 and 0 <= r < 128}
    return full


class TestTheCircleRuns:
    def test_stock_draws_only_the_ends(self, image: bytearray) -> None:
        drawn = _draw_circle(image, _CIRCLE, 10)
        ends = {(x, r) for row, a, b in _CIRCLE for x in (a, b) for r in (row, 20 - row)}
        assert drawn == ends

    def test_patched_fills_every_row(self, patched: bytearray) -> None:
        assert _draw_circle(patched, _CIRCLE, 10) == _rows(_CIRCLE, 10)

    def test_patched_takes_the_ends_in_either_order(self, patched: bytearray) -> None:
        backwards = [(row, b, a) for row, a, b in _CIRCLE]
        assert _draw_circle(patched, backwards, 10) == _rows(_CIRCLE, 10)

    def test_patched_clips_to_the_surface(self, patched: bytearray) -> None:
        """A blip at the map's corner runs off the 128x128 surface, and those pixels are the
        bounds check's to drop."""
        corner = [(0, -2, 2), (1, -2, 2), (2, -1, 1)]
        drawn = _draw_circle(patched, corner, 0)
        assert drawn == _rows(corner, 0)
        assert all(0 <= x < 128 and 0 <= r < 128 for x, r in drawn)

    def test_a_single_pixel_row(self, patched: bytearray) -> None:
        assert _draw_circle(patched, [(5, 7, 7)], 5) == {(7, 5)}


#: Both copies a checkout can hold; neither is committed, so each check skips when absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_the_planted_bytes_are_the_engines(self, which: str) -> None:
        """The synthetic image and the emulation plant these bytes; this is what entitles them."""
        stock = self._stock(which)
        for va, expected in (
            (RADAR_BLIP_KINDOF_SEQUENCE, RADAR_BLIP_KINDOF_SEQUENCE_BYTES),
            (RADAR_CIRCLE_SPAN_LOOP, RADAR_CIRCLE_SPAN_LOOP_BYTES),
            (RADAR_CIRCLE_RADIUS, RADAR_CIRCLE_RADIUS_BYTES),
            (RADAR_PLOT_SPAN_ENDS, RADAR_PLOT_SPAN_ENDS_BYTES),
            (RADAR_PIXEL_IN_BOUNDS, RADAR_PIXEL_IN_BOUNDS_BYTES),
        ):
            assert _read(stock, va, len(expected)) == expected

    def test_the_priority_order_is_the_engines(self, which: str) -> None:
        """The value the cave compares against, and the tests' names, read out of the engine's
        own `RadarPriority` name table rather than assumed."""
        stock = self._stock(which)
        names = []
        for index in range(5):
            (name_va,) = struct.unpack("<I", _read(stock, RADAR_PRIORITY_NAMES + 4 * index, 4))
            names.append(read_cstring(stock, name_va))
        assert names == ["INVALID", "NOT_ON_RADAR", "STRUCTURE", "UNIT", "LOCAL_UNIT_ONLY"]
        assert names.index("STRUCTURE") == RADAR_PRIORITY_STRUCTURE == STRUCTURE
        assert [RadarPriority[name].value for name in names] == list(range(5))

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        RadarStructureDiscsPatch().apply(data)
        assert RadarStructureDiscsPatch().verify(data) == []
        assert isinstance(RadarStructureDiscsPatch.detect(data), RadarStructureDiscsPatch)
