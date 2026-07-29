"""The engine's `ModelConditionFlags` name table, and how a patch appends a name to it.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The addresses here were
derived in ``../docs/production-model-condition.md``; this module is the shared owner of them,
because **more than one patch wants to add a model condition** and the table is a single global
resource. Adding one is not a local edit:

* the table itself is a NULL-terminated ``const char*[]`` reached from **16** bare imm32/disp32
  references, so growing it means relocating it and repointing all sixteen;
* the count is a **separate** immediate baked into **10** loop bounds, two of which index the
  table with no bound check - raise one without the other and the engine hands a NULL string
  pointer to `AsciiString` concatenation.

A patch that hardcoded "the stock table is at 0x00D9FAD8 with 591 entries" would therefore work
alone and break the moment a second such patch existed, in both orders: applied second it would
drop the first patch's name, and applied first it would leave the second patch asserting stock
bytes that are no longer there.

So nothing here reads the stock constants at patch time. :func:`read` recovers the **live** table
- wherever the sixteen references currently point, however many entries the ten counts currently
claim - and :func:`extend` rebuilds it into a fresh cave, repointing from what is actually in the
image. Two patches that both call :func:`extend` compose in either order and land on adjacent
bits; the stock values below are only used to recognise the build.

Bit budget
----------
`ModelConditionFlags` is 19 dwords (``0x4C`` bytes) = 608 bits, of which the stock build names
**591**, so 17 slots are already allocated and unnamed. Past 608 the mask itself must grow, and
``Object+0x10C`` is immediately followed by ``+0x158`` - an `Object` layout change, not a byte
patch. :func:`extend` refuses to cross that line.

One constant sits between 591 and 608: ``ModelConditionFlags::xfer``'s packed-blob path
(``0x004B8D87``) transmits **74 bytes = 592 bits exactly**, so bit 591 is the last one it covers.
That path is the one taken when the `Xfer`'s ``+0x10`` virtual returns true - not save/load, which
serialises **names** and so carries no bit layout at all. A single added condition therefore
changes no blob at all; the second one onwards widens the two ``push 0x4a`` length constants,
which the packer's ``sub esp, 0x4c`` buffer already has room for. See
``../docs/production-model-condition.md`` for the full derivation of both paths.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..utils import allocate_section, apply_byte_patch
from .name_tables import (
    SECTION_CHARACTERISTICS,
    NameTable,
    check_fingerprint,
    read_cstring,
    resolve_base,
    validate_name,
)
from .name_tables import layout as _layout_table
from .name_tables import offset as _offset
from .name_tables import ref_edits as _ref_edits

__all__ = [
    "COUNT_SITES",
    "MASK_DWORDS",
    "MASK_OFFSET",
    "NAME_TABLE_VA",
    "SECTION_CHARACTERISTICS",
    "STOCK_BIT_COUNT",
    "TABLE_FINGERPRINT",
    "TABLE_REF_VAS",
    "Extension",
    "NameTable",
    "extend",
    "read",
    "read_cstring",
    "validate_name",
]

# --- fixed facts about the target build (VA, ImageBase 0x400000) ---------------------------

#: The stock NULL-terminated `ModelConditionFlags` name table. `getBitNames()` at 0x00444D95
#: returns it. Only used to recognise an unpatched image - :func:`read` follows the references.
NAME_TABLE_VA = 0x00D9FAD8

#: Named bits in the stock table. Also `getBitCount()`'s answer, and every loop bound below.
STOCK_BIT_COUNT = 591

#: `Object`'s `ModelConditionFlags`, and its length in dwords. 0x10C + 19*4 == 0x158, which is
#: exactly where the second `Matrix3D` copy documented in ``../docs/live-object-model.md`` begins.
MASK_OFFSET = 0x10C
MASK_DWORDS = 19

#: Every reference to the name table. All 16 are a bare imm32/disp32 holding the base, all in
#: `.text`; unlike the CAH side table, nothing references it at an offset, so there are no
#: end-of-table loop bounds to keep in step.
TABLE_REF_VAS = (
    0x00444D96,  # getBitNames  -> mov eax, <table>
    0x00444E1A,  # nameFromBit  -> mov eax, [eax*4 + <table>]
    0x0044891C,
    0x00449578,
    0x00449590,
    0x0044959E,
    0x004B3B61,  # the INI name->bit parser: cmp dword [<table>], edi
    0x004B3B66,  # the same parser: mov esi, <table>
    0x004B5B7C,
    0x004B5E61,
    0x004B5EA1,
    0x004B5F0C,
    0x007C6429,
    0x007C64CF,
    0x008816A0,
    0x00881739,
)

#: Every site encoding the bit count, as ``(instruction VA, the bytes before its imm32)``. The
#: prefix is asserted as well as the immediate, so a coincidental count elsewhere in a different
#: build cannot be mistaken for one of these. Classified individually in the doc; all ten either
#: index the name table directly or call the single-bit-name helper at 0x00444DFB.
COUNT_SITES = (
    (0x00444DF5, bytes.fromhex("b8")),  # getBitCount: mov eax, 591
    (0x00446103, bytes.fromhex("817d08")),  # name-joining loop
    (0x00448959, bytes.fromhex("817dec")),  # debug dump, mask at +0x258
    (0x004495C7, bytes.fromhex("81fe")),  # INI writer loop
    (0x004B8DCE, bytes.fromhex("81fe")),  # xfer: how many bits to pack into the blob
    (0x004BAF80, bytes.fromhex("817d08")),  # name-joining loop
    (0x007C6452, bytes.fromhex("81fe")),  # animation-state parse loop
    (0x007C64F8, bytes.fromhex("81fe")),  # animation-state parse loop
    (0x008BA785, bytes.fromhex("81fe")),  # mask-to-string builder
    (0x008E2C1F, bytes.fromhex("81fe")),  # the validating setter: rejects bit >= count
)

#: Names at these indices fingerprint the build far more tightly than the count alone. Every index
#: is below :data:`STOCK_BIT_COUNT`, so the check keeps working once the table has grown.
TABLE_FINGERPRINT = {
    0: "TOPPLED",
    218: "JUST_BUILT",
    332: "UPGRADE_ECONOMY_BONUS",
    STOCK_BIT_COUNT - 1: "SPECIAL_WEAPON_SIX",
}

#: ``ModelConditionFlags::xfer``'s packed-blob path: the two ``push imm8`` that give its length in
#: bytes, and the stack buffer that bounds how far they can be raised.
XFER_LENGTH_VAS = (0x004B8D90, 0x004B8DDB)
XFER_STOCK_LENGTH = 0x4A  # 74 bytes = 592 bits
XFER_BUFFER_BYTES = 0x4C  # `sub esp, 0x4c` - 608 bits, the same as the mask itself


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


@dataclass(frozen=True)
class Extension:
    """What :func:`extend` installed."""

    #: Base VA of the appended section, which is also the base of the new name table.
    section_va: int
    #: The bit each added name now is, in the order they were given.
    bits: tuple[int, ...]
    #: VA of the added name strings, in the same order.
    name_vas: tuple[int, ...]
    #: VA just past the names, where ``tail`` (if any) was placed.
    tail_va: int


def read(data: bytes | bytearray) -> NameTable:
    """The live name table, recovered from the image rather than assumed.

    Checks, in order: that all 16 references agree on a base; that all 10 count sites still have
    their expected encoding and agree on a count; that the table is NULL-terminated after exactly
    that many entries; and that the four fingerprint names are at their known indices. Any of
    those failing means either a different build or a half-applied patch, and both should stop a
    patch rather than let it write."""
    base_va = resolve_base(data, TABLE_REF_VAS, "model-condition name table")

    counts: dict[int, int] = {}
    for va, prefix in COUNT_SITES:
        off = _offset(data, va)
        got = bytes(data[off : off + len(prefix)])
        if got != prefix:
            raise ValueError(
                f"model-condition count bound @0x{va:08x} is encoded as {got.hex()}, "
                f"expected {prefix.hex()} - not the expected build"
            )
        counts[va] = struct.unpack_from("<I", data, off + len(prefix))[0]
    if len(set(counts.values())) != 1:
        disagreement = ", ".join(f"0x{va:08x}={count}" for va, count in counts.items())
        raise ValueError(f"the 10 model-condition count bound sites disagree: {disagreement}")
    count = next(iter(counts.values()))
    if count < STOCK_BIT_COUNT:
        raise ValueError(f"the model-condition count is {count}, below the stock {STOCK_BIT_COUNT}")

    pointers = struct.unpack_from(f"<{count + 1}I", data, _offset(data, base_va))
    if pointers[-1] != 0:
        raise ValueError(
            f"the model-condition name table at 0x{base_va:08x} is not NULL-terminated after "
            f"{count} entries (found 0x{pointers[-1]:08x})"
        )
    check_fingerprint(data, pointers, TABLE_FINGERPRINT, "model condition")
    return NameTable(base_va=base_va, pointers=pointers[:count])


def layout(
    table: NameTable,
    new_names: Sequence[str],
    base_va: int,
    tail: Callable[[int, tuple[int, ...]], bytes] | None = None,
) -> tuple[bytes, tuple[int, ...], int]:
    """Lay a cave out at ``base_va``, returning ``(content, name VAs, tail VA)``.

    Order is table, then the new name strings, then whatever ``tail`` returns. The existing
    entries are copied through **by pointer**, so every condition already named keeps both its
    index and its original string - which is what makes raising the ten counts safe, since each
    one only extends a loop by the genuinely new entries."""
    bits = tuple(range(table.count, table.count + len(new_names)))
    content, name_vas, tail_va = _layout_table(table.pointers, new_names, base_va)
    if tail is not None:
        content += tail(tail_va, bits)
    return content, name_vas, tail_va


def relocation_edits(
    data: bytes | bytearray, table: NameTable, new_base_va: int, added: int
) -> list[tuple[int, bytes, bytes, str]]:
    """The ``(file offset, original bytes, patched bytes, note)`` edits that move the table to
    ``new_base_va`` and raise the count by ``added``: 16 references, 10 count immediates, and the
    `xfer` blob length if - and only if - the new count outgrows it."""
    edits = _ref_edits(
        data, TABLE_REF_VAS, table.base_va, new_base_va, "model-condition name table"
    )
    new_count = table.count + added
    for va, prefix in COUNT_SITES:
        edits.append(
            (
                _offset(data, va),
                prefix + _u32(table.count),
                prefix + _u32(new_count),
                f"model-condition count bound @0x{va:08x}",
            )
        )
    edits += _xfer_edits(data, new_count)
    return edits


def _xfer_edits(data: bytes | bytearray, new_count: int) -> list[tuple[int, bytes, bytes, str]]:
    """Widen ``ModelConditionFlags::xfer``'s packed blob, once the count no longer fits it.

    The stock 74 bytes cover bits 0..591 exactly, so the **first** added condition needs no edit
    at all and the blob stays byte-identical - which is why a single-condition patch changes
    nothing about that path. Beyond that the two length constants have to grow together, and they
    can only grow as far as the packer's own stack buffer."""
    if new_count <= XFER_STOCK_LENGTH * 8:
        return []
    needed = (new_count + 7) // 8
    if needed > XFER_BUFFER_BYTES:
        raise ValueError(
            f"{new_count} model conditions need a {needed}-byte xfer blob, but the packer's "
            f"buffer is {XFER_BUFFER_BYTES} bytes - past that the mask itself must grow, which "
            "is an Object layout change rather than a byte patch"
        )
    edits: list[tuple[int, bytes, bytes, str]] = []
    for va in XFER_LENGTH_VAS:
        off = _offset(data, va)
        if data[off] != 0x6A:  # push imm8
            raise ValueError(
                f"the xfer blob length @0x{va:08x} is not a `push imm8` - not the expected build"
            )
        edits.append(
            (
                off + 1,
                bytes([data[off + 1]]),
                bytes([needed]),
                f"xfer packed-blob length @0x{va:08x}",
            )
        )
    return edits


def extend(
    data: bytearray,
    section_name: str,
    new_names: Sequence[str],
    tail: Callable[[int, tuple[int, ...]], bytes] | None = None,
) -> Extension:
    """Append ``new_names`` to the model-condition name table, in a cave called ``section_name``.

    ``tail`` is called with ``(its own VA, the new bit indices)`` and its bytes are placed after
    the names in the same cave, so a patch that also needs hook code gets it laid out with an
    address it can branch from. It is called twice with the same arguments and must be
    deterministic.

    Raises before writing anything if the image is not the expected build, if a name is not a
    token the INI parser could match, or if a name is already a model condition."""
    table = read(data)
    for name in new_names:
        validate_name(name)
        index = table.index_of(data, name)
        if index is not None:
            raise ValueError(f"{name!r} is already model condition {index} - choose another name")
    if len(set(new_names)) != len(new_names):
        raise ValueError(f"duplicate names in {list(new_names)}")
    if table.count + len(new_names) > MASK_DWORDS * 32:
        raise ValueError(
            f"{table.count} + {len(new_names)} conditions overflows the "
            f"{MASK_DWORDS * 32}-bit ModelConditionFlags mask"
        )

    section_va = allocate_section(
        data,
        section_name,
        lambda base_va: layout(table, new_names, base_va, tail)[0],
        SECTION_CHARACTERISTICS,
    )
    _content, name_vas, tail_va = layout(table, new_names, section_va, tail)
    for file_off, old, new, note in relocation_edits(data, table, section_va, len(new_names)):
        apply_byte_patch(data, file_off, old, new, note)
    return Extension(
        section_va=section_va,
        bits=tuple(range(table.count, table.count + len(new_names))),
        name_vas=name_vas,
        tail_va=tail_va,
    )
