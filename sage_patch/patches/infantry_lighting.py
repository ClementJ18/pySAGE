"""The infantry-lighting patch: choose which kindofs get the map's *infantry* light environment.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/infantry-lighting.md``.

**The gap.** A `.map`'s `GlobalLighting` chunk carries **three** light sets per time of day - one
for terrain, one for objects, one for infantry, three lights each - and the map reader stores them
at three bases in `TheGlobalData` (``+0x1AC``, ``+0x434``, ``+0x6BC``). The scene builds the last
two into two ready-made light environments, and the render loop at ``0x0046FD42`` picks between
them per render object: a flag bit set means the infantry environment at ``scene+0x5B4``, clear
means the object environment at ``scene+0x164``.

That flag is set in the model-draw path, and the only thing that sets it is this test::

    test byte ptr [tmpl + 0x109], 5     ; KindOf bits 8 and 10 - INFANTRY, MONSTER

So a unit whose `KindOf` says `CAVALRY` and nothing else is lit as an *object*, alongside walls,
rocks and siege engines. On the shipped maps the two sets differ in one term - the sun's ambient -
and the object set is the darker one (stock `map mp amon sul fortress`: ``0.090, 0.071, 0.043``
against the infantry set's ``0.290, 0.306, 0.290``, with diffuse colour and direction identical),
which is why the symptom reads as "cavalry is too dark" rather than "cavalry is lit from
elsewhere". Giving a mounted unit `KINDOF_INFANTRY` fixes the look because it buys a pass on this
test - and drags in crush rules, `PATH_THROUGH_INFANTRY`, KindOf filters on weapons, armor and
powers, and AI target selection along with it.

**What this does.** Rewrites that immediate at both draw sites, so the infantry environment is
chosen for whichever kindofs are named instead of the stock two. The default adds `CAVALRY`, which
is the whole bug; ``every_drawable`` instead defuses the branch, so every drawable that reaches the
model-draw path takes the infantry environment.

**Only the bits that byte holds.** The immediate is a byte-lane mask over `KindOfMaskType` bits
8..15 - `INFANTRY`, `CAVALRY`, `MONSTER`, `MACHINE`, `AIRCRAFT`, `HUGE_VEHICLE`, `DOZER`,
`SWARM_DOZER` in the stock table - because that is the byte the stock instruction reads and there
is no room at the site to read another one. Names are resolved against the image's **live** kindof
table rather than a hardcoded list, so a binary carrying an added kindof reports its real bit and
is refused by index, not by name; anything outside the lane raises and points at ``every_drawable``.

Two sites, nine bytes each
--------------------------
The test and the `je` that skips the setter call sit adjacent, and both are rewritten together:

* ``0x0047A7A0`` - ``test byte [edi+0x109], 5`` / ``je +0x0A``, in the draw virtual at
  ``0x0047A0AD``.
* ``0x004C4E2B`` - ``test byte [ebx+0x109], 5`` / ``je +0x0A``, in the draw virtual at
  ``0x004C451D``, which six more draw-module vtables hold at the same slot.

Both then run ``mov eax,[ecx] / push 1 / call [eax+0x1C4]``, the `RenderObjClass` flag setter whose
getter at ``+0x1C0`` is what the render loop reads. Naming a wider mask therefore costs nothing at
runtime: the same instruction tests more bits.

``every_drawable`` writes ``0xFF`` into the immediate and replaces the two-byte ``je`` with two
``nop``s, so the call is unconditional. The two null checks ahead of it - the template pointer and
the render object - are left standing, so a drawable with neither still takes neither branch.

**What it does not do.** Nothing here changes the light sets themselves. On a map whose infantry
set equals its object set the patch is invisible, correctly: 80 of the 103 stock maps and 205 of
Edain's 510 ship them identical. Nor does it touch terrain, which is lit from the third set and
never consults this flag.

**Determinism.** Client-side render state only. The flag lives on a `RenderObjClass`, is read once
per draw, and reaches nothing the logic frame or the CRC can see - so a peer running a stock binary
disagrees about pixels and about nothing else, and replays cross freely in both directions.

**Composition.** No cave, no table growth, and no byte here is touched by anything else in this
package, so it is order-independent with everything bundled. It *reads* the kindof name table
through `patches.utils.kind_of`, which `desert-weather` and any other kindof-adding patch rebuild
in a cave - reading it live rather than at its stock address is what keeps that pair order-free in
both directions. See the composition contract on :class:`~..patcher.Patch`.
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
    """One ``test byte [reg + 0x109], imm8`` and the ``je`` that skips the setter call.

    ``test_prefix`` is the whole instruction bar its immediate, so asserting it covers the opcode,
    the ModRM and the displacement: a two-byte ``74 0a`` somewhere else in a different build cannot
    be mistaken for this site. ``branch`` keeps its displacement in both the stock and the patched
    encoding - only the opcode pair is ever replaced, and only by ``nop``s of the same length.
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

#: Sites that pin :data:`SITES` to the code that really is the lighting gate, asserted before
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
    """Give the map's infantry light environment to ``kinds`` instead of the stock
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
        """Structural check that ``data`` carries *this* configuration (an empty list == verified).
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
        """Recognise this patch **and recover what it was applied with** from ``data``.

        The default probe cannot: it would ask `verify` about the default kindofs and report every
        other selection as absent. The mask is read straight back out of the first site's immediate
        and turned into names through the image's own kindof table, and `verify` then checks both
        sites against it.

        A stock binary carries :data:`STOCK_MASK` and an intact branch, and is reported - correctly
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
        """The immediate :attr:`kinds` encodes, resolved against the image's live kindof table.

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
        """The kindof names ``mask`` selects, in bit order, read out of the image's own table."""
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
