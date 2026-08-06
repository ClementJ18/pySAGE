"""The engine's `KindOf` name table, and what it takes to add a name to it.

`KindOfMaskType` is a **7-dword / 224-bit** bitfield - the `memset(mask, 0, 0x1C)` that
`KindOf = NONE` performs at `0x00655B3F` and the single-bit mask constructor at `0x00444D39`
both say so, and `ThingTemplate`'s sibling `KindOf`/`ExcludedKindOf` pair sits exactly `0x1C`
apart. The stock name table holds **222** names, so **two bits are free** and a new kindof costs
no data growth at all: not in `ThingTemplate`, not in `Object`, and not in the savegame, because
`KindOfMaskType::xfer` packs bit-by-bit into a fixed `0x1C`-byte blob that already covers 224.

That makes adding a kindof the same three moves :mod:`.name_tables` describes - read the live
table, rebuild it into a cave, repoint every reference - plus the per-table question that module
leaves to its owners: **this table does bake its count**, in six places, so the count moves with
it. The INI *parse* path is not one of them (`INI::scanIndexList` walks to the terminator), so a
name added without raising the counts would still parse; the six sites are the ones that
enumerate or bounds-check by index.

Only 222 and 223 exist. A third added kindof has nowhere to go, and widening the mask is an
`Object` and `ThingTemplate` layout change rather than a byte patch - see
``../docs/upgrade-mask-limit.md`` for what that looks like on the mask that already ran out.
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
    validate_name,
)
from .name_tables import layout as _layout_table
from .name_tables import offset as _offset
from .name_tables import ref_edits as _ref_edits
from .name_tables import resolve_base as _resolve_base

__all__ = [
    "COUNT_SITES",
    "MASK_BYTES",
    "MASK_DWORDS",
    "NAME_TABLE_VA",
    "SECTION_CHARACTERISTICS",
    "STOCK_KIND_COUNT",
    "TABLE_FINGERPRINT",
    "TABLE_REF_VAS",
    "THING_TEMPLATE_MASK_OFFSET",
    "Extension",
    "NameTable",
    "bit_test",
    "extend",
    "layout",
    "read",
    "read_cstring",
    "relocation_edits",
    "validate_name",
]

#: The stock NULL-terminated `KindOf` name table. Only used to recognise an unpatched image -
#: :func:`read` follows the references instead of trusting this.
NAME_TABLE_VA = 0x00DA0E68

#: Named kindofs in the stock table, and the answer every count site below holds.
STOCK_KIND_COUNT = 222

#: `KindOfMaskType`, in dwords and bytes. 7 * 32 == 224 is the hard ceiling on the count.
MASK_DWORDS = 7
MASK_BYTES = MASK_DWORDS * 4

#: Where a `ThingTemplate` keeps its `KindOf` mask - field-parse table entry 57 at `0x00DA4148`.
#: Engine code tests a single kindof inline as ``test byte [tmpl + 0x108 + bit/8], 1 << (bit%8)``,
#: which is the form :func:`bit_test` emits.
THING_TEMPLATE_MASK_OFFSET = 0x108

#: Every reference to the name table: 14 bare imm32/disp32 operands, all in `.text`.
#: `0x007B3CDB` is the one that looks like a false positive and is not - it sits after a byte
#: table, but `0x007B3CDA` really is a six-byte ``mov eax, <table>; ret`` accessor. Nothing calls
#: it, exactly like the dead `getCount` behind :data:`COUNT_SITES`' first entry; it is repointed
#: anyway, because "unreferenced today" is not a reason to leave a stale pointer behind.
TABLE_REF_VAS = (
    0x00655B67,  # INI mask parser, `+NAME`
    0x00655BA7,  # INI mask parser, `-NAME`
    0x00655C12,  # INI mask parser, bare `NAME`
    0x006AAD0F,  # nameFromBit -> mov eax, [eax*4 + <table>]
    0x006AAD20,  # nameToBit   -> cmp dword [<table>], edi
    0x006AAD25,  # nameToBit   -> mov esi, <table>
    0x007079FF,  # getKindOfName(index) -> mov eax, [eax*4 + <table>]
    0x007B3CDB,  # the dead table accessor
    0x007B67E3,  # the script/editor kindof picker, one function from here down
    0x007B67F3,
    0x007B6869,
    0x007B6885,
    0x007B6899,
    0x007B68DD,
)

#: Every site encoding the kindof count, as ``(instruction VA, the bytes before its imm32)``.
#: The prefix is asserted as well as the immediate, so a coincidental 222 elsewhere in a
#: different build cannot be mistaken for one of these.
#:
#: `0x006AACEA` is `getCount()` and is **dead** - no call reaches it and no vtable holds it. It
#: is raised with the others so that a future caller cannot find a stale answer.
COUNT_SITES = (
    (0x006AACEA, bytes.fromhex("b8")),  # getCount: mov eax, 222   (unreferenced)
    (0x006AC637, bytes.fromhex("81fe")),  # xfer: how many bits to pack into the blob
    (0x006ACBD5, bytes.fromhex("817d08")),  # the name-list builder
    (0x007079F5, bytes.fromhex("3d")),  # getKindOfName: reject index >= count
    (0x00762A35, bytes.fromhex("81ff")),  # editor/script list population
    (0x007B58FD, bytes.fromhex("81fe")),  # script-condition text, "Kind is '%s'"
)

#: Names at these indices fingerprint the build far more tightly than the count alone. Every
#: index is below :data:`STOCK_KIND_COUNT`, so the check keeps working once the table has grown.
TABLE_FINGERPRINT = {
    0: "OBSTACLE",
    90: "HERO",
    143: "PORTER",
    STOCK_KIND_COUNT - 1: "HORDE_MONSTER",
}


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def bit_test(bit: int, base_register: int, displacement_base: int) -> bytes:
    """``test byte [reg + base + bit/8], 1 << (bit%8)`` - how engine code asks one kindof.

    ``base_register`` is the ModRM r/m encoding (0 eax, 1 ecx, 2 edx, 3 ebx, 6 esi, 7 edi); ``esp``
    and ``ebp`` are excluded because they need a SIB byte or a different mod, and no caller here
    wants them. The disp32 form is always emitted: `ThingTemplate`'s mask starts past `0x7F`, so
    the short form could never encode it anyway."""
    if base_register in (4, 5):
        raise ValueError("esp/ebp need a different encoding - use another register")
    modrm = 0x80 | base_register  # mod=10 (disp32), reg=/0 (test r/m8, imm8)
    return bytes([0xF6, modrm]) + _u32(displacement_base + bit // 8) + bytes([1 << (bit % 8)])


@dataclass(frozen=True)
class Extension:
    """What :func:`extend` installed."""

    #: Base VA of the appended section, which is also the base of the new name table.
    section_va: int
    #: The kindof bit each added name now is, in the order they were given.
    bits: tuple[int, ...]
    #: VA of the added name strings, in the same order.
    name_vas: tuple[int, ...]
    #: VA just past the names, where ``tail`` (if any) was placed.
    tail_va: int


def read(data: bytes | bytearray) -> NameTable:
    """The live name table, recovered from the image rather than assumed.

    Checks, in order: that all 14 references agree on a base; that all 6 count sites still carry
    their expected encoding and agree; that the table is NULL-terminated after exactly that many
    entries; and that the four fingerprint names are at their known indices. Any of those failing
    means either a build these addresses were not derived against or a half-applied patch, and
    both should stop a patch rather than let it write."""
    base_va = _resolve_base(data, TABLE_REF_VAS, "kindof name table")

    counts: dict[int, int] = {}
    for va, prefix in COUNT_SITES:
        off = _offset(data, va)
        got = bytes(data[off : off + len(prefix)])
        if got != prefix:
            raise ValueError(
                f"kindof count bound @0x{va:08x} is encoded as {got.hex()}, "
                f"expected {prefix.hex()} - not the expected build"
            )
        counts[va] = struct.unpack_from("<I", data, off + len(prefix))[0]
    if len(set(counts.values())) != 1:
        disagreement = ", ".join(f"0x{va:08x}={count}" for va, count in counts.items())
        raise ValueError(f"the {len(COUNT_SITES)} kindof count sites disagree: {disagreement}")
    count = next(iter(counts.values()))
    if count < STOCK_KIND_COUNT:
        raise ValueError(f"the kindof count is {count}, below the stock {STOCK_KIND_COUNT}")

    pointers = struct.unpack_from(f"<{count + 1}I", data, _offset(data, base_va))
    if pointers[-1] != 0:
        raise ValueError(
            f"the kindof name table at 0x{base_va:08x} is not NULL-terminated after {count} "
            f"entries (found 0x{pointers[-1]:08x})"
        )
    check_fingerprint(data, pointers, TABLE_FINGERPRINT, "kindof")
    return NameTable(base_va=base_va, pointers=pointers[:count])


def layout(
    table: NameTable,
    new_names: Sequence[str],
    base_va: int,
    tail: Callable[[int, tuple[int, ...]], bytes] | None = None,
) -> tuple[bytes, tuple[int, ...], int]:
    """Lay a cave out at ``base_va``, returning ``(content, name VAs, tail VA)``.

    Order is table, then the new name strings, then whatever ``tail`` returns. Existing entries
    are copied through **by pointer**, so every kindof already named keeps both its index and its
    original string - which is what makes raising the six counts safe, since each one only
    extends a loop by the genuinely new entries."""
    bits = tuple(range(table.count, table.count + len(new_names)))
    content, name_vas, tail_va = _layout_table(table.pointers, new_names, base_va)
    if tail is not None:
        content += tail(tail_va, bits)
    return content, name_vas, tail_va


def relocation_edits(
    data: bytes | bytearray, table: NameTable, new_base_va: int, added: int
) -> list[tuple[int, bytes, bytes, str]]:
    """The ``(file offset, original bytes, patched bytes, note)`` edits that move the table to
    ``new_base_va`` and raise the count by ``added``: 14 references and 6 count immediates.

    There is deliberately no `xfer` length edit here, unlike the model-condition table's. The
    packed blob is `0x1C` bytes = 224 bits and the mask is the same 224 bits, so every count this
    table can legally reach already fits."""
    edits = _ref_edits(data, TABLE_REF_VAS, table.base_va, new_base_va, "kindof name table")
    new_count = table.count + added
    for va, prefix in COUNT_SITES:
        edits.append(
            (
                _offset(data, va),
                prefix + _u32(table.count),
                prefix + _u32(new_count),
                f"kindof count bound @0x{va:08x}",
            )
        )
    return edits


def extend(
    data: bytearray,
    section_name: str,
    new_names: Sequence[str],
    tail: Callable[[int, tuple[int, ...]], bytes] | None = None,
    characteristics: int = SECTION_CHARACTERISTICS,
) -> Extension:
    """Append ``new_names`` to the kindof name table, in a cave called ``section_name``.

    ``tail`` is called with ``(its own VA, the new bit indices)`` and its bytes are placed after
    the names in the same cave, so a patch that also needs hook code gets it laid out with an
    address it can branch from. It is called twice with the same arguments and must be
    deterministic.

    ``characteristics`` defaults to the read-execute cave every table-growing patch wants. A
    ``tail`` that keeps mutable state - a scratch variable its hook writes at runtime - has to
    ask for a writable section instead, since the whole cave is one section.

    Raises before writing anything if the image is not the expected build, if a name is not a
    token the INI parser could ever match, if a name is already a kindof, or if the additions
    would overflow the 224-bit mask."""
    table = read(data)
    for name in new_names:
        validate_name(name, "kindof name")
        index = table.index_of(data, name)
        if index is not None:
            raise ValueError(f"{name!r} is already kindof {index} - choose another name")
    if len(set(new_names)) != len(new_names):
        raise ValueError(f"duplicate names in {list(new_names)}")
    if table.count + len(new_names) > MASK_DWORDS * 32:
        raise ValueError(
            f"{table.count} + {len(new_names)} kindofs overflows the {MASK_DWORDS * 32}-bit "
            "KindOfMaskType - widening it is an Object layout change, not a byte patch"
        )

    section_va = allocate_section(
        data,
        section_name,
        lambda base_va: layout(table, new_names, base_va, tail)[0],
        characteristics,
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
