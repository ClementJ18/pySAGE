"""`hero-bar-slots` - raise the in-game hero bar from its stock **16** slots to ``count``.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/hero-bar-slots.md``; the class layout it builds on was recovered in
``../docs/herobar-kindof.md`` §1.

**The gap.** The hero bar is 16 slots and nothing about that is data-driven. Adding `Hero17`+
clips to the movie therefore changes nothing at all: the constructor registers
`_OnBttnHeroSelect` on `Hero1`..`Hero16` only, so the new clips get no click callback, and the
draw loop `break`s at slot 17, so nothing ever calls `SetButtonState` on them. The failure is
silent - the extra buttons simply stay in whatever state the movie parks them in.

**Which movie.** On Edain the bar is drawn by **`FactionFrame.apt`**, not by the
`InGameHeroSelect.apt` that ships beside it and is never loaded. The engine names slots through
`%s/Hero%d/` against a path prefix held on the bar object, so no file name appears in the code
and the right one has to be identified from a running game. ``../docs/hero-bar-slots.md`` §7 has
the method and the rest of the `.apt` half.

**What it does.** Grows the bar's slot-cache array and raises the ten hardcoded counts that walk
it. The bar is one class, constructed exactly once (`AptPalantir::OnHeroSelectLoaded`), holding

===========  ===================================================================
`+0x08`      APT movie / level handle
`+0x0C`      `AsciiString` path prefix - the `%s` in `%s/Hero%d/`
`+0x10`      the shared model that owns the hero and porter lists
`+0x44`      "the bar has been shown" latch
`+0x48`      **the slot cache**: `0x18` bytes x 16, built by the vector-ctor helper
`+0x1C8`     the `0x18`-byte iteration/selection state block
`0x1E0`      `sizeof`
===========  ===================================================================

`0x48 + 16*0x18 == 0x1C8` exactly, so the array runs to the byte before that state block and the
class has no slack - which is the whole reason this is not a one-byte patch.

**Why the array grows in place rather than moving to a cave.** Every reference to the state block
past the array is already a **disp32** (`[esi+0x1c8]`, `[esi+0x1dc]`, ...), so pushing the block
up by ``(count-16)*0x18`` rewrites four bytes inside instructions that keep their exact length and
encoding. Moving the *array* instead would mean re-basing `[eax+esi+0x4c]`-style disp8 addressing,
which cannot grow to disp32 in place and would need a detour at each of the four addressing sites.
So the array stays at `+0x48`, the state block slides up, and the class gets bigger - and the
patch needs **no cave and no assembly at all**, only immediates.

That makes the whole thing 38 sites of pure immediate rewriting: ten counts, one `sizeof`, and
27 displacement re-bases. All of them are asserted against their stock bytes before anything is
written.

**The ten counts**, and why there are ten rather than the one the ceiling looks like:

=============  ===========  =============================================================
`0x0092C013`   0-based      slot search: "which slot is showing this node"
`0x0092C2DA`   count        vtable[2]: reset every slot to the list head + ungrouped
`0x0092C307`   0-based      vtable[3]: find a slot by node, then index it
`0x0092C955`   0-based      the expanded-hero scan
`0x0092D3E5`   **1-based**  the draw ceiling - the one the bar visibly stops at
`0x0092D78D`   0-based      cleanup entry guard: are there leftover slots to blank
`0x0092D8B6`   **1-based**  the cleanup loop's own back edge
`0x0092DBC8`   0-based      click dispatch: reject a slot index past the end
`0x0092DE51`   count        the vector-ctor's element count - the array itself
`0x0092E02E`   0-based      the ctor's `Hero%d` callback registration loop
=============  ===========  =============================================================

Missing any one of them is a different bug, and only the first is cosmetic: leaving `0x0092DE51`
alone would run every other loop off the end of a 16-element array and into the state block.

**The `.apt` is not optional.** The engine drives slot *i* through `%s/Hero%d/`,
`_level%d.%s_Hero%dImage` and `APT:_level%d.%s_Hero%dRank`, so the movie must define `Hero17`..
`Hero<count>` clips (and their `FlashEffect<n>` siblings) on both frames the stock sixteen appear
on - `_fadein` (frame 9) places them, `_show` (frame 19) reveals them - in **both** the `apt/` and
`apt_widescreen/` variants, whose grids differ. A movie without them leaves the extra slots inert
exactly as before: this patch removes the engine's ceiling, it does not draw anything. `sage_apt`
is the tooling for that half, and ``../docs/hero-bar-slots.md`` §7 is the procedure.

**Determinism.** The bar is client-local UI: it is built from the local player's own object
lists, nothing here enters the simulation, and the click path raises the same
`MSG_CREATE_SELECTED_GROUP` it always did. Like `replay-outcome`, it does **not** have to be on
every peer, and replays cross between patched and stock builds.

**Composition.** Order-independent; it allocates no section and reads nothing another patch
writes. It shares a function with `herobar` but not a byte: that patch's detours sit at
`0x0092D36F`/`0x0092D3EE` (the draw loop) and `0x0092DBD6` (the click), while the nearest sites
here are `0x0092D3E5` and `0x0092DBC8`, three and eight bytes clear respectively.

What a patch **cannot** do beside this one is hard-code an offset past the array. Every field from
`+0x1C8` up moves by ``(count-16)*0x18``, and on a widened bar the stock addresses land *inside*
the array instead - `bar+0x1DC` at 25 slots is byte `0x14` of slot 16. `herobar --grouped` used to
take its repeat-click window by calling `0x0092BA91` and reading `bar+0x1DC` back, which on this
combination read a slot for a deadline and left the porter's real field stomped; it now does that
arithmetic in its own cave and reads nothing here. Only the first ten sites above are counts - the
other 27 exist precisely because these offsets are not stable.

The remaining interaction is behavioural rather than structural, and only for `herobar --grouped`:
its per-pass "already drawn" set is 16 dwords in its own cave, and it *clamps* rather than overflows
(`cmp eax,16 ; jae`), so on a bar wider than 16 the 17th and later distinct `HEROBAR` templates
stop being de-duplicated - each instance takes its own slot. Its per-slot click cursor is 16
dwords too and clamps the same way, so a group in slot 17 or beyond selects its first member on
every click instead of stepping to the next. Nothing corrupts; grouping degrades past 16 kinds
and stepping past 16 slots. The default `herobar` keeps no state and is indifferent to the width.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..patcher import Patch
from ..utils import apply_byte_patch, hexbytes, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "COUNT_SITES",
    "FIELD_SITES",
    "MAX_COUNT",
    "MIN_COUNT",
    "STOCK_SLOTS",
    "HeroBarSlotsPatch",
    "class_size",
]

# --- the class, as this build has it ---------------------------------------------------------

#: The slot cache array, and one slot's stride, both as offsets into the bar object.
SLOT_ARRAY = 0x48
SLOT_STRIDE = 0x18

#: What the stock build ships, and the class size that follows from it.
STOCK_SLOTS = 16
STOCK_CLASS_SIZE = 0x1E0

#: The iteration/selection state that sits immediately after the array, and its length. Growing
#: the array slides this whole block up by the same amount; its internal layout is untouched.
STATE_BLOCK = 0x1C8
STATE_BLOCK_SIZE = 0x18

#: `push <sizeof>` in the allocating ctor wrapper at `0x0092E1D6`, as an imm32.
CLASS_SIZE_SITE = 0x0092E1E2
CLASS_SIZE_OPCODE = b"\x68"

#: 17 because this patch *raises* a ceiling: at 16 every site computes its stock bytes, and a
#: `verify` that passed on an unpatched binary would make `detect` claim every stock `game.dat`
#: carries this patch. 126 because the draw ceiling and the cleanup back edge encode ``count+1``
#: as a **signed imm8** - at 127 slots that byte is `0x80`, which decodes as -128 and turns both
#: loops into "never run".
MIN_COUNT = 17
MAX_COUNT = 126


def class_size(count: int) -> int:
    """`sizeof` the bar class with a ``count``-slot array: the array's own offset, the array, and
    the state block that follows it. Reproduces the stock ``0x1E0`` at ``count == 16``."""
    return SLOT_ARRAY + count * SLOT_STRIDE + STATE_BLOCK_SIZE


# --- the ten hardcoded slot counts -----------------------------------------------------------


@dataclass(frozen=True)
class _Count:
    """One site holding the slot count as a trailing 8-bit immediate.

    ``prefix`` is everything before that byte, so the stock bytes are
    ``prefix + (STOCK_SLOTS + bias)`` and the patched ones ``prefix + (count + bias)``. ``bias``
    is 1 where the loop counts from one and compares against the count *plus* one, which is the
    difference that makes two of these encode `0x11` rather than `0x10`."""

    va: int
    prefix: str
    bias: int
    note: str

    def encode(self, count: int) -> bytes:
        value = count + self.bias
        if not 0 <= value <= 127:
            raise ValueError(
                f"{self.va:#010x} would encode {value} as a signed imm8, which is "
                f"{value - 256}; {self.note}"
            )
        return hexbytes(self.prefix) + bytes([value])


COUNT_SITES = (
    _Count(0x0092C013, "83fe", 0, "slot search bound"),
    _Count(0x0092C2DA, "6a", 0, "reset-every-slot loop count"),
    _Count(0x0092C307, "83fa", 0, "find-slot-by-node bound"),
    _Count(0x0092C955, "837df8", 0, "expanded-hero scan bound"),
    _Count(0x0092D3E5, "83f8", 1, "the draw ceiling"),
    _Count(0x0092D78D, "83ff", 0, "cleanup entry guard"),
    _Count(0x0092D8B6, "83fb", 1, "cleanup loop back edge"),
    _Count(0x0092DBC8, "83f8", 0, "click dispatch bound"),
    _Count(0x0092DE51, "6a", 0, "slot array element count"),
    _Count(0x0092E02E, "83f8", 0, "ctor Hero%d registration bound"),
)


# --- the 27 references to the state block past the array --------------------------------------


@dataclass(frozen=True)
class _Field:
    """One instruction addressing the state block, and where its disp32 sits inside it.

    Recorded as whole stock instruction bytes rather than as "four bytes at a VA" so that the
    assertion covers the opcode and ModRM too: a build where one of these instructions is not
    what it was here is one whose class layout this patch must not assume."""

    va: int
    original: str
    disp_at: int
    field: int

    def encode(self, count: int) -> bytes:
        """The same instruction with its displacement moved up by the slots that were added."""
        raw = bytearray(hexbytes(self.original))
        moved = self.field + (count - STOCK_SLOTS) * SLOT_STRIDE
        struct.pack_into("<i", raw, self.disp_at, moved)
        return bytes(raw)


FIELD_SITES = (
    _Field(0x0092BACE, "8986dc010000", 2, 0x1DC),
    _Field(0x0092C09A, "c681da01000000", 2, 0x1DA),
    _Field(0x0092C180, "898ec8010000", 2, 0x1C8),
    _Field(0x0092C18E, "8986cc010000", 2, 0x1CC),
    _Field(0x0092C194, "c686d801000001", 2, 0x1D8),
    _Field(0x0092C1FD, "389ed8010000", 2, 0x1D8),
    _Field(0x0092C20E, "8d86c8010000", 2, 0x1C8),
    _Field(0x0092C22C, "889ed8010000", 2, 0x1D8),
    _Field(0x0092CDD9, "389ed8010000", 2, 0x1D8),
    _Field(0x0092CDF2, "8d86c8010000", 2, 0x1C8),
    _Field(0x0092CE12, "389ed9010000", 2, 0x1D9),
    _Field(0x0092CE24, "8d86d0010000", 2, 0x1D0),
    _Field(0x0092CEDF, "c687da01000001", 2, 0x1DA),
    _Field(0x0092DA3F, "80beda01000000", 2, 0x1DA),
    _Field(0x0092DA53, "3b86dc010000", 2, 0x1DC),
    _Field(0x0092DA9B, "3886da010000", 2, 0x1DA),
    _Field(0x0092DB53, "c681da01000001", 2, 0x1DA),
    _Field(0x0092DE68, "899ec8010000", 2, 0x1C8),
    _Field(0x0092DE6E, "899ed0010000", 2, 0x1D0),
    _Field(0x0092DE78, "889ed8010000", 2, 0x1D8),
    _Field(0x0092DE7E, "889ed9010000", 2, 0x1D9),
    _Field(0x0092DE84, "889eda010000", 2, 0x1DA),
    _Field(0x0092DE8A, "899edc010000", 2, 0x1DC),
    _Field(0x0092DF87, "8d86c8010000", 2, 0x1C8),
    _Field(0x0092E185, "898ed0010000", 2, 0x1D0),
    _Field(0x0092E193, "8986d4010000", 2, 0x1D4),
    _Field(0x0092E199, "c686d901000001", 2, 0x1D9),
)


class HeroBarSlotsPatch(Patch):
    """Raise the in-game hero bar from the stock 16 slots to ``count`` (17..126)."""

    name = "hero-bar-slots"
    author = "officialNecro"
    description = "Raise the in-game hero bar from 16 slots to N"

    def __init__(self, count: int = 21):
        if not MIN_COUNT <= count <= MAX_COUNT:
            hint = ""
            if count <= STOCK_SLOTS:
                hint = f" (this patch raises the ceiling; {STOCK_SLOTS} is what the engine ships)"
            elif count > MAX_COUNT:
                hint = " (count+1 is a signed imm8 at the draw ceiling and the cleanup back edge)"
            raise ValueError(f"count must be in {MIN_COUNT}..{MAX_COUNT}, got {count}{hint}")
        self.count = count

    def __str__(self) -> str:
        return f"{self.name} (N={self.count})"

    def apply(self, data: bytearray) -> None:
        for file_off, old, new, note in self._edits(data):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch at ``count`` (an empty list ==
        verified). Recomputes all 38 sites from ``count`` and compares. Reads only via the section
        table, so it needs no disassembler."""
        problems: list[str] = []
        try:
            edits = self._edits(data)
        except ValueError as exc:
            return [str(exc)]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> HeroBarSlotsPatch | None:
        """Recognise this patch **and recover its N** from ``data``.

        The default probe cannot: it would ask `verify` about the default N and call every other
        width absent. The ctor wrapper's ``push <sizeof>`` is an imm32 holding
        ``0x48 + N*0x18 + 0x18``, so N reads straight back out of it, and `verify` then checks all
        38 sites against that N. A stock binary yields ``N == 16``, which is outside this patch's
        range and so is reported - correctly - as not carrying it."""
        off = va_to_offset(data, CLASS_SIZE_SITE)
        if off is None or bytes(data[off : off + 1]) != CLASS_SIZE_OPCODE:
            return None
        try:
            size = struct.unpack_from("<I", data, off + 1)[0]
        except struct.error:
            return None
        count, remainder = divmod(size - SLOT_ARRAY - STATE_BLOCK_SIZE, SLOT_STRIDE)
        if remainder or not MIN_COUNT <= count <= MAX_COUNT:
            return None
        patch = cls(count)
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--count",
            type=int,
            default=21,
            metavar="N",
            help=(
                f"new hero-bar slot count ({MIN_COUNT}..{MAX_COUNT}); default 21. The movie must "
                "define Hero<n> clips to match"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> HeroBarSlotsPatch:
        return cls(count=args.count)

    def _edits(self, data: bytes | bytearray) -> list[tuple[int, bytes, bytes, str]]:
        """Every `(file offset, stock bytes, patched bytes, note)` this patch writes.

        One list serves `apply` and `verify`: `apply` asserts the stock bytes and writes the
        patched ones, `verify` compares the patched ones to what is on disk. Raises if a site is
        not mapped, which is how a binary that is not this build fails before anything is
        written."""
        n = self.count
        edits: list[tuple[int, bytes, bytes, str]] = []

        for site in COUNT_SITES:
            edits.append(
                (
                    self._offset(data, site.va),
                    site.encode(STOCK_SLOTS),
                    site.encode(n),
                    f"hero bar {site.note} -> {n + site.bias}",
                )
            )

        size_off = self._offset(data, CLASS_SIZE_SITE)
        edits.append(
            (
                size_off,
                CLASS_SIZE_OPCODE + struct.pack("<I", STOCK_CLASS_SIZE),
                CLASS_SIZE_OPCODE + struct.pack("<I", class_size(n)),
                f"hero bar sizeof -> {class_size(n):#x}",
            )
        )

        for field in FIELD_SITES:
            edits.append(
                (
                    self._offset(data, field.va),
                    hexbytes(field.original),
                    field.encode(n),
                    f"hero bar state {field.field:#05x} -> "
                    f"{field.field + (n - STOCK_SLOTS) * SLOT_STRIDE:#05x}",
                )
            )
        return edits

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off
