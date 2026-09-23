"""Choose which kindofs get a map's infantry light environment.

A map carries separate light sets for terrain, objects and infantry, and the render loop picks the
infantry environment for render objects flagged with a stock pair of kindofs. The patch rewrites
that kindof immediate at both draw sites; the default adds `CAVALRY`, and `every_drawable` gives
every model the infantry lights. The light sets and terrain are unchanged, and on the many maps
whose infantry and object sets are identical it is invisible.

Derivation: `../docs/infantry-lighting.md`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..patcher import Patch
from ..utils import apply_byte_patch, hexbytes, va_to_offset
from .utils import kind_of

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_KINDS",
    "FINGERPRINT",
    "LANE_BITS",
    "MASK_BYTE_OFFSET",
    "NOP_PAIR",
    "SITES",
    "STOCK_MASK",
    "InfantryLightingPatch",
    "Site",
]

#: The byte of `ThingTemplate`'s `KindOf` mask both sites test: one past its base, so bits 8..15.
MASK_BYTE_OFFSET = kind_of.THING_TEMPLATE_MASK_OFFSET + 1

#: The kindof bits that byte holds, and so the ones this patch can name.
LANE_BITS = range(8, 16)

#: The stock immediate: bit 8 (`INFANTRY`) | bit 10 (`MONSTER`).
STOCK_MASK = 0x05

#: The stock two plus `CAVALRY`, which is the case the stock test misses.
DEFAULT_KINDS = ("INFANTRY", "CAVALRY", "MONSTER")

#: What replaces the skip branch when every drawable is to take the infantry environment.
NOP_PAIR = b"\x90\x90"

#: The immediate written alongside those `nop`s. Nothing reads it once the branch is gone; it is
#: 0xFF rather than left alone so a disassembly of a patched binary reads as "any of them".
EVERY_MASK = 0xFF


@dataclass(frozen=True)
class Site:
    """One `test byte [reg + 0x109], imm8` and the `je` that skips the setter call.

    `test_prefix` is the whole instruction bar its immediate, so asserting it covers the opcode,
    the ModRM and the displacement: a two-byte `74 0a` somewhere else in a different build cannot
    be mistaken for this site. `branch` keeps its displacement in both the stock and the patched
    encoding - only the opcode pair is ever replaced, and only by `nop`s of the same length.
    """

    va: int
    test_prefix: bytes
    branch: bytes
    note: str

    @property
    def stock(self) -> bytes:
        return self.test_prefix + bytes([STOCK_MASK]) + self.branch

    def patched(self, mask: int, every_drawable: bool) -> bytes:
        immediate = EVERY_MASK if every_drawable else mask
        tail = NOP_PAIR if every_drawable else self.branch
        return self.test_prefix + bytes([immediate]) + tail


SITES = (
    Site(
        va=0x0047A7A0,
        test_prefix=hexbytes("f68709010000"),  # test byte [edi+0x109], imm8
        branch=hexbytes("740a"),  # je 0x0047A7B3, past the setter call
        note="model-draw lighting gate (0x0047A0AD)",
    ),
    Site(
        va=0x004C4E2B,
        test_prefix=hexbytes("f68309010000"),  # test byte [ebx+0x109], imm8
        branch=hexbytes("740a"),  # je 0x004C4E3E, past the setter call
        note="model-draw lighting gate (0x004C451D)",
    ),
)

#: Sites that pin `SITES` to the code that really is the lighting gate, asserted before
#: anything is written. The mask byte alone is not distinctive - what makes these unmistakable is
#: the setter call the test guards, and the render-loop branch that gives the flag its meaning.
FINGERPRINT = {
    # mov ecx, [esi+0x50] / test ecx, ecx / je - the render object, ahead of each test
    0x0047A799: hexbytes("8b4e5085c97413"),
    0x004C4E24: hexbytes("8b4e5085c97413"),
    # mov eax, [ecx] / push 1 / call [eax+0x1C4] - the flag setter each test guards
    0x0047A7A9: hexbytes("8b016a01ff90c4010000"),
    0x004C4E34: hexbytes("8b016a01ff90c4010000"),
    # call [eax+0x1C0] / test eax, eax / ... / lea eax, [esi+0x5B4] : [esi+0x164] - the render
    # loop reading the flag back and choosing the infantry or the object light environment
    0x0046FD49: hexbytes("ff90c001000085c08b7d0874088d86b4050000eb2c8d8664010000"),
}


class InfantryLightingPatch(Patch):
    """Give the map's infantry light environment to `kinds` instead of the stock
    `INFANTRY`/`MONSTER`, or to every drawable."""

    name = "infantry-lighting"
    author = "officialNecro"
    description = (
        "Light CAVALRY (or any KindOf in bits 8..15, or everything) with the map's infantry "
        "light environment instead of the darker object one. No INI change - the kindofs are "
        "chosen when the patch is applied, not per template - and it is invisible on maps whose "
        "two light sets are identical"
    )

    def __init__(self, kinds: Sequence[str] | None = None, *, every: bool = False):
        if every and kinds:
            raise ValueError("every=True lights every drawable; naming kinds as well is ambiguous")
        selection = () if every else tuple(DEFAULT_KINDS if kinds is None else kinds)
        if not every and not selection:
            raise ValueError("name at least one kindof, or pass every=True")
        if len(set(selection)) != len(selection):
            raise ValueError(f"duplicate names in {list(selection)}")
        self.kinds = selection
        self.every = every

    def __str__(self) -> str:
        if self.every:
            return f"{self.name} (every drawable)"
        return f"{self.name} ({'+'.join(self.kinds)})"

    def apply(self, data: bytearray) -> None:
        for file_off, old, new, note in self._edits(data):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries *this* configuration (an empty list == verified).
        Recomputes both sites from the kindofs this instance names and compares. Reads the kindof
        table and the section table only, so it needs no disassembler."""
        try:
            edits = self._edits(data)
        except ValueError as exc:
            return [str(exc)]
        problems: list[str] = []
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> InfantryLightingPatch | None:
        """Recognise this patch **and recover what it was applied with** from `data`.

        The default probe cannot: it would ask `verify` about the default kindofs and report every
        other selection as absent. The mask is read straight back out of the first site's immediate
        and turned into names through the image's own kindof table, and `verify` then checks both
        sites against it.

        A stock binary carries `STOCK_MASK` and an intact branch, and is reported - correctly
        - as not carrying this patch, even though "INFANTRY + MONSTER" is a selection this patch
        could have been asked for."""
        site = SITES[0]
        off = va_to_offset(data, site.va)
        if off is None:
            return None
        got = bytes(data[off : off + len(site.stock)])
        if got[: len(site.test_prefix)] != site.test_prefix:
            return None

        mask = got[len(site.test_prefix)]
        tail = got[len(site.test_prefix) + 1 :]
        if tail == NOP_PAIR:
            patch = cls(every=True)
            return None if patch.verify(data) else patch
        if tail != site.branch or mask == STOCK_MASK:
            return None  # untouched, or a branch this patch did not write

        try:
            names = cls._names_for(data, mask)
        except ValueError:
            return None
        patch = cls(names)
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--kinds",
            default=",".join(DEFAULT_KINDS),
            metavar="NAME[,NAME...]",
            help=(
                f"comma-separated KindOf names to light with the infantry light environment; "
                f"default {','.join(DEFAULT_KINDS)}. Only the eight names in mask bits 8..15 "
                f"(INFANTRY, CAVALRY, MONSTER, MACHINE, AIRCRAFT, HUGE_VEHICLE, DOZER, "
                f"SWARM_DOZER on a stock table) can be named - use --all for anything wider"
            ),
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help=(
                "light every drawable with the infantry environment, whatever its KindOf, by "
                "defusing the test instead of widening it. Overrides --kinds"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> InfantryLightingPatch:
        if args.all:
            return cls(every=True)
        return cls(tuple(part.strip() for part in args.kinds.split(",") if part.strip()))

    def mask(self, data: bytes | bytearray) -> int:
        """The immediate `kinds` encodes, resolved against the image's live kindof table.

        Raises if a name is not a kindof in this binary, or is one whose bit that byte does not
        hold - which is the whole of what the site can express, so the error names the alternative
        rather than silently dropping the kindof."""
        table = kind_of.read(data)
        value = 0
        for name in self.kinds:
            bit = table.index_of(data, name)
            if bit is None:
                raise ValueError(f"{name!r} is not a KindOf in this binary")
            if bit not in LANE_BITS:
                raise ValueError(
                    f"{name!r} is KindOf bit {bit}, which the byte this site tests does not hold "
                    f"(it holds bits {LANE_BITS.start}..{LANE_BITS.stop - 1}) - reaching it needs "
                    f"a wider test than the nine bytes here, so use --all instead"
                )
            value |= 1 << (bit - LANE_BITS.start)
        return value

    @classmethod
    def _names_for(cls, data: bytes | bytearray, mask: int) -> tuple[str, ...]:
        """The kindof names `mask` selects, in bit order, read out of the image's own table."""
        table = kind_of.read(data)
        names: list[str] = []
        for bit in LANE_BITS:
            if not mask & (1 << (bit - LANE_BITS.start)):
                continue
            if bit >= table.count:
                raise ValueError(f"the mask names bit {bit}, which this table does not")
            name = kind_of.read_cstring(data, table.pointers[bit])
            if name is None:
                raise ValueError(f"kindof bit {bit} points at an unreadable name")
            names.append(name)
        return tuple(names)

    def _edits(self, data: bytes | bytearray) -> list[tuple[int, bytes, bytes, str]]:
        """Every `(file offset, stock bytes, patched bytes, note)` this patch writes.

        One list serves `apply` and `verify`: `apply` asserts the stock bytes and writes the
        patched ones, `verify` compares the patched ones to what is on disk. Raises if the image is
        not the build these addresses were derived from, which is how a wrong binary fails before
        anything is written."""
        self._check_fingerprint(data)
        mask = 0 if self.every else self.mask(data)
        selection = "every drawable" if self.every else "+".join(self.kinds)
        return [
            (
                self._offset(data, site.va),
                site.stock,
                site.patched(mask, self.every),
                f"{site.note} -> {selection}",
            )
            for site in SITES
        ]

    def _check_fingerprint(self, data: bytes | bytearray) -> None:
        """Raise unless every pinning site holds its stock bytes, so a patch aimed at the wrong
        build fails before it writes rather than flipping an unrelated branch."""
        for va, expected in FINGERPRINT.items():
            off = va_to_offset(data, va)
            got = None if off is None else bytes(data[off : off + len(expected)])
            if got != expected:
                hexed = "unmapped" if got is None else got.hex()
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {hexed}, expected {expected.hex()} - this "
                    f"does not look like the game.dat this patch targets"
                )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off
