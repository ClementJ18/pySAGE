"""Primitives shared by every patch that adds a **field to an INI block**.

A block type - `Object`, `SpecialPower`, `PlayerTemplate`, `CommandButton` - is a NULL-terminated
array of ``{const char *name, ParseFn parse, void *userData, UnsignedInt offset}`` rows, and the
INI reader walks it with `stricmp` to turn a keyword into a parse call and a struct offset. Adding
a keyword is therefore not a code change at all: it is one more row. But the array has no slack and
its base is a bare imm32 in every instruction that names it, so "one more row" means rebuilding the
whole table in a cave and repointing every reference at it.

That is three moves, and this module owns the reading half of all three:

1. :func:`resolve_table` - where the table *currently* is, taken from the references rather than
   from a stock constant;
2. :func:`read_field_table` - what is *currently* in it, read out of the live image;
3. :func:`entries_before` - which of those rows were there before a given patch's own rows, so a
   patch can re-derive its own layout in a table something else has since extended again.

**Every one of them reads the live image, and that is the point.** It is the same rule
:mod:`.name_tables` states for the engine's global name tables, for the same reason: a patch that
appends to whatever is live composes with anything that relocated the table first, where one that
reads the stock base would silently drop the earlier patch's rows and install a second copy of its
own. Four patches extend field tables today - `hero-mana`, `second-resource`, `command-point-upkeep`
and `queue-ignore-cp` - and they extend four different blocks, so what they actually share is not a
table but this discipline about reading one.

What is deliberately **not** here is the writing half. Laying a rebuilt table out in a cave means
knowing where the new rows sit relative to the code and the strings the same cave holds, and that
layout is the patch's own business; each of the four has its own `_table_bytes` / `_table_span`.
The split is where the answer stops being generic.

Not to be confused with :func:`.name_tables.resolve_base`, which does the same job for the global
name tables against a different convention: its reference VAs point at the **operand**, these point
at the **instruction**, which is why this one takes and checks an opcode as well.
"""

from __future__ import annotations

import struct

from ...utils import va_to_offset
from .name_tables import read_cstring

__all__ = [
    "Entry",
    "entries_before",
    "read_field_table",
    "resolve_table",
]

#: One `{const char *name, ParseFn, void *userData, UnsignedInt offset}` row of an INI
#: field-parse table, as `struct` unpacks it.
Entry = tuple[int, int, int, int]

#: A row is four dwords. Named rather than spelled `16` at each site, because the same number is
#: also a table's alignment and its terminator's size, and those are the same fact.
ROW_SIZE = 16

#: How far :func:`read_field_table` walks before deciding a table is not terminated. The largest
#: stock table is an order of magnitude under this, so it is a runaway guard rather than a limit.
_MAX_ROWS = 1024


def read_field_table(data: bytes | bytearray, base_va: int) -> tuple[Entry, ...]:
    """The live field-parse table at ``base_va``, terminator excluded.

    Read from the image rather than assumed, so that a patch which extended the table first still
    composes - the rule :mod:`.name_tables` states for the name tables.
    """
    off = va_to_offset(data, base_va)
    if off is None:
        raise ValueError(f"the field table at 0x{base_va:08x} is not mapped")
    entries: list[Entry] = []
    for index in range(_MAX_ROWS):
        entry: Entry = struct.unpack_from("<IIII", data, off + index * ROW_SIZE)
        if entry[0] == 0 and entry[1] == 0:
            return tuple(entries)
        entries.append(entry)
    raise ValueError(f"the field table at 0x{base_va:08x} is not terminated")


def entries_before(
    data: bytes | bytearray, entries: tuple[Entry, ...], name: str
) -> tuple[Entry, ...] | None:
    """The rows that preceded ``name`` when the patch owning it rebuilt the table, or None if the
    table does not name it.

    Located **by name, never by counting back from the end**. A rebuilt table is
    ``[what was live] + [the new rows] + terminator``, so a patch that extends the same table
    afterwards appends past these - and counting back would then report the wrong number of
    preceding rows. That number is not cosmetic: it sizes the rebuilt table, which places
    everything the cave lays out after it, so getting it wrong moves every routine the patch
    points the engine at.
    """
    for index, entry in enumerate(entries):
        if read_cstring(data, entry[0]) == name:
            return entries[:index]
    return None


def resolve_table(
    data: bytes | bytearray, ref_vas: tuple[int, ...], opcodes: tuple[int, ...], what: str
) -> int:
    """A field table's base VA, taken from the references that name it.

    Read from the references rather than from the stock constant for two reasons. It is what
    makes the patch compose with anything that relocated a table first - it appends to whatever
    is live instead of dropping that patch's entries. And it is what makes **applying this patch
    twice** fail cleanly: the second run reads its own rebuilt table and sees the fields already
    there, where reading the stock base would find the untouched original and cheerfully install
    a second copy.
    """
    bases = {}
    for ref_va, opcode in zip(ref_vas, opcodes, strict=True):
        off = va_to_offset(data, ref_va)
        if off is None:
            raise ValueError(f"0x{ref_va:08x} is not mapped - not the expected build")
        if data[off] != opcode:
            raise ValueError(
                f"the {what} table reference at 0x{ref_va:08x} is opcode 0x{data[off]:02x}, "
                f"expected 0x{opcode:02x} - not the expected build"
            )
        bases[ref_va] = struct.unpack_from("<I", data, off + 1)[0]
    if len(set(bases.values())) != 1:
        disagreement = ", ".join(f"0x{va:08x}->0x{base:08x}" for va, base in bases.items())
        raise ValueError(f"the {len(ref_vas)} {what} table refs disagree: {disagreement}")
    return next(iter(bases.values()))
