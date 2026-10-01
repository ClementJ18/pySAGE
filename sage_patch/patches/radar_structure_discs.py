"""Draw every `RadarPriority = STRUCTURE` object on the minimap as a filled disc sized to it.

The stock blip painter gives an ordinary structure a fixed 2x2 dot, whatever its size. Only
`KindOf COMMANDCENTER` gets a circle scaled to the geometry's bounding radius, and that circle is
hollow, because the routine that draws each row of it plots only the row's two ends. The patch
sends every object whose radar priority is `STRUCTURE` down the COMMANDCENTER branch, and replaces
the row routine with one that fills the row, so every circle comes out solid, a command centre's
included. `WALL_SEGMENT` objects keep their footprint, since that test comes first.

The circle's radius is the bounding radius in radar pixels, rounded, and never below a minimum
the engine hardcodes as 2. On a typical map a radar pixel is about 30 world units, so an ordinary
building sits on that minimum; `min_radius` raises it.

Derivation: `../docs/radar-structure-discs.md`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import (
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
    RADAR_KINDOF_COMMANDCENTER,
    RADAR_PIXEL_IN_BOUNDS,
    RADAR_PLOT_SPAN_ENDS,
    RADAR_PRIORITY_STRUCTURE,
    SURFACE_DRAW_PIXEL,
    THING_TEMPLATE_KINDOF,
)
from ..asm import JE, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section, u32

if TYPE_CHECKING:
    import argparse

__all__ = [
    "MAX_MIN_RADIUS",
    "SECTION_NAME",
    "RadarStructureDiscsPatch",
    "build_cave",
]

#: The largest `min_radius` accepted. The value is a `push imm8`, so 127 would encode, but a
#: 64-pixel radius already covers the whole 128x128 radar.
MAX_MIN_RADIUS = 64

SECTION_NAME = ".rdrdsc"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The six bytes at `RADAR_BLIP_KINDOF_LOAD`: `mov ebx, [eax+0x108]`.
STOCK_KINDOF_LOAD = b"\x8b\x98" + u32(THING_TEMPLATE_KINDOF)


def build_cave(base_va: int) -> tuple[bytes, int, int]:
    """Return `(code, kindof VA, fill VA)` for a cave based at `base_va`.

    The kindof routine stands in for `mov ebx, [eax+0x108]`. It loads the same dword, then sets
    the COMMANDCENTER bit in it when the object's radar priority is `STRUCTURE`, so the painter's
    own `shr ebx, 0x11 / and bl, 1` picks the circle. `edi` is the `Object*` there, and `eax`,
    `ecx` and `edx` are kept because the painter's register use around the hook was not read past
    the next call.

    The fill routine replaces the span-ends routine: same `cdecl (a, b, surface)` with the row in
    `esi`, but it plots every pixel from `a` to `b` rather than just the two ends. It orders the
    ends first rather than relying on how the rasteriser lays out a span."""
    a = Asm(base_va)

    a.label("kindof")
    a.emit(STOCK_KINDOF_LOAD)  # mov ebx, [eax+0x108]
    a.emit(0x50, 0x51, 0x52)  # push eax; push ecx; push edx
    a.emit(b"\x8b\xcf")  # mov ecx, edi         ; the Object
    a.call_absolute(OBJECT_GET_RADAR_PRIORITY)
    a.emit(b"\x83\xf8", RADAR_PRIORITY_STRUCTURE)  # cmp eax, STRUCTURE
    a.jcc(JNE, "kindof_done")
    a.emit(b"\x81\xcb", u32(1 << RADAR_KINDOF_COMMANDCENTER))  # or ebx, COMMANDCENTER
    a.label("kindof_done")
    a.emit(0x5A, 0x59, 0x58)  # pop edx; pop ecx; pop eax
    a.emit(0xC3)  # ret

    a.label("fill")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x57, 0x53)  # push edi; push ebx
    a.emit(b"\x8b\x7d\x08")  # mov edi, [ebp+8]      ; a
    a.emit(b"\x8b\x5d\x0c")  # mov ebx, [ebp+0xc]    ; b
    a.emit(b"\x3b\xfb")  # cmp edi, ebx
    a.jcc(JLE, "fill_row")
    a.emit(b"\x87\xfb")  # xchg edi, ebx
    a.label("fill_row")
    a.emit(0x56, 0x57)  # push esi; push edi     ; (x, row)
    a.call_absolute(RADAR_PIXEL_IN_BOUNDS)
    a.emit(0x59, 0x59)  # pop ecx; pop ecx
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "fill_next")
    a.emit(b"\xff\x35", u32(RADAR_BLIP_COLOUR))  # push dword [colour]
    a.emit(b"\x8b\x4d\x10")  # mov ecx, [ebp+0x10]   ; the surface
    a.emit(0x56, 0x57)  # push esi; push edi
    a.call_absolute(SURFACE_DRAW_PIXEL)  # callee-cleaned
    a.label("fill_next")
    a.emit(0x47)  # inc edi
    a.emit(b"\x3b\xfb")  # cmp edi, ebx
    a.jcc(JLE, "fill_row")
    a.emit(0x5B, 0x5F, 0x5D)  # pop ebx; pop edi; pop ebp
    a.emit(0xC3)  # ret

    kindof_va = a.label_va("kindof")
    fill_va = a.label_va("fill")
    return a.finish(), kindof_va, fill_va


def _edits(cave_va: int, min_radius: int) -> list[tuple[int, bytes, bytes, str]]:
    """Every engine site the patch rewrites, as `(VA, stock, patched, note)`. The minimum-radius
    entry is listed even at the stock value, so `verify` checks it; `apply` skips it then."""
    _code, kindof_va, fill_va = build_cave(cave_va)
    edits = [
        (
            RADAR_BLIP_KINDOF_LOAD,
            STOCK_KINDOF_LOAD,
            call_rel32(RADAR_BLIP_KINDOF_LOAD, kindof_va) + b"\x90",
            "radar blip KindOf load -> STRUCTURE counts as COMMANDCENTER",
        ),
        (
            RADAR_CIRCLE_MIN_RADIUS,
            bytes([RADAR_CIRCLE_MIN_RADIUS_STOCK]),
            bytes([min_radius]),
            f"radar circle minimum radius -> {min_radius}",
        ),
    ]
    for site in RADAR_CIRCLE_SPAN_CALLS:
        edits.append(
            (
                site,
                call_rel32(site, RADAR_PLOT_SPAN_ENDS),
                call_rel32(site, fill_va),
                "radar circle row -> filled",
            )
        )
    return edits


class RadarStructureDiscsPatch(Patch):
    """Give every STRUCTURE-priority object a filled, size-scaled minimap disc."""

    name = "radar-structure-discs"
    author = "officialNecro"
    description = (
        "Draw every object whose RadarPriority is STRUCTURE on the minimap the way a "
        "COMMANDCENTER is drawn - a circle scaled to its geometry's bounding radius, at least 2 "
        "pixels in radius - instead of a fixed 2x2 dot, and fill those circles, a command "
        "centre's included, instead of drawing their outline. --min-radius raises the smallest "
        "circle, which is what an ordinary building gets. WALL_SEGMENT objects keep their "
        "footprint. Presentation only. No INI change"
    )

    def __init__(self, min_radius: int = RADAR_CIRCLE_MIN_RADIUS_STOCK):
        if not 1 <= min_radius <= MAX_MIN_RADIUS:
            raise ValueError(f"min_radius must be 1..{MAX_MIN_RADIUS}, got {min_radius}")
        self.min_radius = min_radius

    def __str__(self) -> str:
        return f"{self.name} (minimum radius {self.min_radius})"

    def apply(self, data: bytearray) -> None:
        self._check_sequences(data)
        cave_va = allocate_section(
            data, SECTION_NAME, lambda va: build_cave(va)[0], _CHARACTERISTICS
        )
        for va, old, new, note in _edits(cave_va, self.min_radius):
            if old != new:
                apply_byte_patch(data, file_offset(data, va), old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        problems: list[str] = []
        code = build_cave(cave_va)[0]
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routines in {SECTION_NAME} are not the ones this patch builds")
        for va, _old, new, note in _edits(cave_va, self.min_radius):
            off = file_offset(data, va)
            got = bytes(data[off : off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{va:08x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> RadarStructureDiscsPatch | None:
        """Recognise this patch and recover its minimum radius, which is the one byte it leaves
        at `RADAR_CIRCLE_MIN_RADIUS`."""
        if find_section(data, SECTION_NAME) is None:
            return None
        try:
            off = file_offset(data, RADAR_CIRCLE_MIN_RADIUS)
            patch = cls(min_radius=data[off])
            problems = patch.verify(data)
        except (ValueError, IndexError, struct.error):
            return None
        return None if problems else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--min-radius",
            type=int,
            default=RADAR_CIRCLE_MIN_RADIUS_STOCK,
            metavar="PIXELS",
            help=(
                "the smallest circle radius, in radar pixels on the 128x128 minimap (default: "
                f"{RADAR_CIRCLE_MIN_RADIUS_STOCK}, the engine's own). An ordinary building rounds "
                "below it on most maps, so this is what sets their size"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> RadarStructureDiscsPatch:
        return cls(min_radius=args.min_radius)

    @staticmethod
    def _check_sequences(data: bytes | bytearray) -> None:
        """Raise unless both hooked sequences are stock in full, not just the bytes being
        replaced: the caves rely on `edi` being the object at the KindOf load and on `esi`
        holding the row at each span call, which only the surrounding instructions establish."""
        for va, expected, what in (
            (RADAR_BLIP_KINDOF_SEQUENCE, RADAR_BLIP_KINDOF_SEQUENCE_BYTES, "blip KindOf test"),
            (RADAR_CIRCLE_SPAN_LOOP, RADAR_CIRCLE_SPAN_LOOP_BYTES, "circle span loop"),
            (RADAR_CIRCLE_RADIUS, RADAR_CIRCLE_RADIUS_BYTES, "circle radius"),
        ):
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"@0x{va:08x}: expected the stock radar {what} {expected.hex()}, got "
                    f"{got.hex()} - the file is not the expected build, or already carries "
                    "this patch"
                )
