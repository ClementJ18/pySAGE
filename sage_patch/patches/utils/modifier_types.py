"""The engine's `ModifierType` name table, and how a patch appends a name to it.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The addresses here are derived
in ``../docs/production-split.md`` §1.2 and ``../docs/healing-received-modifier.md`` §4.

A modifier type is the first token of a `ModifierList`'s ``Modifier = <TYPE> <value>`` line. The
parser resolves it through the name→index walk at ``0x00804CAD``, over a NULL-terminated
``const char *[]``:

    00804cb1  cmp  [0xda6d28], edi          ; edi = 0: an empty table means "not found"
    00804cb9  mov  esi, 0xda6d28            ; else walk it with stricmp

Index 0 is the `ATTRIBUTE_NONE` sentinel and doubles as "not found", so an unrecognised token
raises ``"Attribute '%s' not found"`` (``0x00C4EA38``) and ends the INI load.

**Nothing is sized by the number of types.** `ModifierList::getValue` (``0x00805268``) is a linear
scan comparing a stored dword, the holder walk above it is type-agnostic, and there is no array
indexed by type anywhere in the image. So an appended type costs a table relocation and nothing
else - no count, no bitmask, no switch arm.

The table has **no slack**: it ends at its terminator and the next enum's list begins four bytes
later, so it cannot grow in place. Both references are bare imm32 operands inside the one walk,
which is what :func:`relocation_edits` rewrites.

`.data` holds some 135 identical copies of the array for the linker's own reasons; only
``0x00DA6D28`` is reachable from code, which is why :func:`read` follows the references rather
than trusting the stock address.

Composing two appenders
-----------------------
`production-split` and `healing-received` both append here, and compose in either order because
each one **reads the live table** - wherever the references currently point and however many
entries it currently has - and copies it through by pointer, so every name already present keeps
its index and its original string. What neither may do is assert that the live references still
name *its own* rebuilt table: the patch applied second owns them. The invariant that survives
both orders is the one their `verify` checks instead - the walk reaches a table that gives this
patch's keyword the index this patch's code was built to push.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from .name_tables import (
    NameTable,
    check_fingerprint,
    offset,
    read_cstring,
    read_terminated,
    ref_edits,
    resolve_base,
)

__all__ = [
    "ANCHORS",
    "NAME_TABLE_VA",
    "PRODUCTION_TYPE",
    "STOCK_TYPE_COUNT",
    "TABLE_FINGERPRINT",
    "TABLE_REF_VAS",
    "VOLATILE_SPANS",
    "WORLDBUILDER_NAME_TABLE_VA",
    "WORLDBUILDER_TABLE_FINGERPRINT",
    "WORLDBUILDER_TABLE_REF_SITES",
    "appended_names",
    "check_free",
    "index_of",
    "names",
    "push_type",
    "read",
    "read_worldbuilder",
    "relocation_edits",
    "worldbuilder_ref_vas",
    "worldbuilder_relocation_edits",
]


#: The stock NULL-terminated `ModifierType` name table. Only used to recognise an unpatched
#: image - :func:`read` follows the references.
NAME_TABLE_VA = 0x00DA6D28

#: Named types in the stock table, `ATTRIBUTE_NONE` included.
STOCK_TYPE_COUNT = 28

#: Both references, the imm32 operands of the two instructions that open the name walk: the
#: empty-table guard (``cmp [table], edi``) and the walk itself (``mov esi, table``).
TABLE_REF_VAS = (0x00804CB3, 0x00804CBA)

#: Names at these indices fingerprint the build far more tightly than the count alone: the
#: sentinel, the first real type, the one `production-split` splits, and the last stock one.
TABLE_FINGERPRINT = {
    0: "ATTRIBUTE_NONE",
    1: "ARMOR",
    13: "PRODUCTION",
    STOCK_TYPE_COUNT - 1: "INVULNERABLE",
}

#: `PRODUCTION`, the one stock type a patch here currently reads by index.
PRODUCTION_TYPE = 13

#: The largest index a ``push imm8`` can carry. Every emitted query pushes its type as a byte, so
#: a table that ever grew past this would need `push imm32` instead - :func:`push_type` says so
#: rather than silently emitting a sign-extended negative.
_MAX_PUSH_IMM8 = 0x7F

#: Byte windows that say the modifier system still works the way an appended type depends on, for
#: any patch that appends one to assert. Facts about the system rather than about one patch, which
#: is why they live here and not beside a hook table.
#:
#: * the **name walk**: a NULL-terminated scan, and the "index 0 == not found" contract a new name
#:   relies on;
#: * **`ModifierList::getValue`**: a linear scan over ``0x14``-byte entries comparing the type
#:   dword, which is what makes a new index cost no array, bitmask or switch arm;
#: * **`Object::hasModifier` / `Object::getModifierMultiplier`**: the two thunks a query goes
#:   through, with the ``ret 0xC`` / ``ret 0x10`` an emitted call has to match.
ANCHORS: dict[int, bytes] = {
    0x00804CAD: bytes.fromhex(
        "565733ff393d286dda007423be286dda008bc6ff74240cff30e87582230085c05959"
        "741283c60447833e008bc675e433c05f5ec204008bc7eb"
    ),
    0x00805268: bytes.fromhex(
        "558bec568b318b490457eb0a8b063b4508740f83c6143bf175f232c05f5e5dc20c00837d10007428"
    ),
    0x0068C818: bytes.fromhex(
        "e889fcffff85c0750532c0c20c008bc8e90c871700e874fcffff85c0750532c0c210008bc8e9bd871700"
    ),
}

#: The ``(VA, width)`` spans inside :data:`ANCHORS` that **any** type-appending patch may have
#: rewritten - the two table operands. A patch checking these windows blanks them unconditionally,
#: in both directions: whichever appender ran last owns them, so their value says nothing about
#: any particular patch, and :func:`read` checks what they point at far more tightly than a byte
#: compare would.
VOLATILE_SPANS: tuple[tuple[int, int], ...] = tuple((va, 4) for va in TABLE_REF_VAS)


def read(data: bytes | bytearray) -> NameTable:
    """The live name table, recovered from the image rather than assumed.

    Checks that both references agree on a base, that the table is NULL-terminated, and that the
    four fingerprint names are at their known indices - all of which keep working once another
    patch has relocated and extended it."""
    base_va = resolve_base(data, TABLE_REF_VAS, "modifier-type name table")
    pointers = read_terminated(data, base_va, "modifier-type name table")
    if len(pointers) < STOCK_TYPE_COUNT:
        raise ValueError(
            f"the modifier-type name table at 0x{base_va:08x} has {len(pointers)} entries, "
            f"below the stock {STOCK_TYPE_COUNT}"
        )
    check_fingerprint(data, pointers, TABLE_FINGERPRINT, "modifier type")
    return NameTable(base_va=base_va, pointers=pointers)


def relocation_edits(
    data: bytes | bytearray, table: NameTable, new_base_va: int
) -> list[tuple[int, bytes, bytes, str]]:
    """The edits repointing both references at the rebuilt table."""
    return ref_edits(data, TABLE_REF_VAS, table.base_va, new_base_va, "modifier-type name table")


def check_free(table: NameTable, data: bytes | bytearray, new_names: Sequence[str]) -> None:
    """Raise unless every name in ``new_names`` is free to add, and they are distinct."""
    if len(set(new_names)) != len(new_names):
        raise ValueError(f"duplicate names in {list(new_names)}")
    for name in new_names:
        index = table.index_of(data, name)
        if index is not None:
            raise ValueError(f"{name!r} is already modifier type {index} - choose another name")


def index_of(data: bytes | bytearray, name: str) -> int | None:
    """The index the **live** table gives ``name``, or None if it does not name it."""
    return read(data).index_of(data, name)


def push_type(index: int) -> bytes:
    """``push <index>`` as the engine's own query sites encode it: a sign-extended imm8."""
    if not 0 <= index <= _MAX_PUSH_IMM8:
        raise ValueError(
            f"modifier type {index} does not fit the `push imm8` every query site uses "
            f"(0..{_MAX_PUSH_IMM8})"
        )
    return bytes([0x6A, index])


# The Worldbuilder half.
#
# The editor parses `attributemodifier.ini` too, and resolves the same first token through its own
# copy of the table. A name that copy does not hold is an unknown token in a lookup, which throws,
# and a throw during INI load ends the editor. Its table is **terminator-driven** exactly like
# `game.dat`'s:
#
#     00e983a4  cmp dword [eax*4 + 0x022343E0], 0   ; walk to the NULL
#     00e983ac  je  0x00E983D3
#     00e983b5  mov eax, [edx*4 + 0x022343E0]       ; else compare this name
#     00e983bd  call 0x016C37DE                     ; stricmp
#
# so there is no count to raise - the only two references in the image are the two above, both
# inside that one loop, and relocating the table and repointing them is the whole patch.

#: Worldbuilder's own copy of the table.
WORLDBUILDER_NAME_TABLE_VA = 0x022343E0

#: Both references, as ``(operand VA, the bytes immediately before it)``. Both sit in the single
#: lookup loop - the terminator test and the name fetch - so asserting the encoding pins them to
#: that loop rather than to any dword that happens to hold the same address.
WORLDBUILDER_TABLE_REF_SITES = (
    (0x00E983A7, bytes.fromhex("833c85")),  # cmp dword [eax*4 + <table>], 0
    (0x00E983B8, bytes.fromhex("8b0495")),  # mov eax, [edx*4 + <table>]
)

#: The editor's copy holds no `PRODUCTION` fingerprint worth naming separately - the same three
#: names identify it.
WORLDBUILDER_TABLE_FINGERPRINT = {
    0: "ATTRIBUTE_NONE",
    1: "ARMOR",
    STOCK_TYPE_COUNT - 1: "INVULNERABLE",
}


def worldbuilder_ref_vas() -> tuple[int, ...]:
    """Just the operand VAs of :data:`WORLDBUILDER_TABLE_REF_SITES`."""
    return tuple(va for va, _prefix in WORLDBUILDER_TABLE_REF_SITES)


def read_worldbuilder(data: bytes | bytearray) -> NameTable:
    """The live table in a `Worldbuilder.exe`, taken from the references rather than the constant.

    Asserts each reference's encoding as well as its value, which is what says these two dwords
    are the lookup loop's operands and not some unrelated pointer."""
    bases: set[int] = set()
    for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
        off = offset(data, va)
        got = bytes(data[off - len(prefix) : off])
        if got != prefix:
            raise ValueError(
                f"modifier-type table ref @0x{va:08x} is encoded as {got.hex()}, expected "
                f"{prefix.hex()} - not the expected build"
            )
        bases.add(struct.unpack_from("<I", data, off)[0])
    if len(bases) != 1:
        raise ValueError(f"the modifier-type table refs disagree: {[hex(b) for b in bases]}")
    base_va = bases.pop()
    pointers = read_terminated(data, base_va, "Worldbuilder modifier-type table", limit=256)
    if len(pointers) < STOCK_TYPE_COUNT:
        raise ValueError(
            f"the modifier-type table holds {len(pointers)} names, below the stock "
            f"{STOCK_TYPE_COUNT}"
        )
    check_fingerprint(data, pointers, WORLDBUILDER_TABLE_FINGERPRINT, "Worldbuilder modifier type")
    return NameTable(base_va=base_va, pointers=pointers)


def worldbuilder_relocation_edits(
    data: bytes | bytearray, table: NameTable, new_base_va: int
) -> list[tuple[int, bytes, bytes, str]]:
    """The two reference edits. There is no count edit: the lookup walks to the terminator."""
    return ref_edits(
        data,
        worldbuilder_ref_vas(),
        table.base_va,
        new_base_va,
        "Worldbuilder modifier-type table",
    )


def appended_names(
    data: bytes | bytearray, section_va: int, vsize: int, limit: int = 256
) -> list[str]:
    """The names a cave based at ``section_va`` appended to the table it copied.

    A cave lays its rebuilt table out at its own base and copies the entries it was handed
    **through by pointer**, so the names it added are exactly the trailing entries whose string
    lives inside that section. Deciding it that way rather than by counting up from the stock size
    stays right however many types another patch had already appended before this one ran.
    """
    pointers = read_terminated(data, section_va, "the rebuilt modifier-type table", limit=limit)
    added: list[str] = []
    for pointer in reversed(pointers):
        if not section_va <= pointer < section_va + vsize:
            break
        name = read_cstring(data, pointer)
        if name is None:
            raise ValueError(f"the entry at 0x{pointer:08x} points at unmapped memory")
        added.append(name)
    added.reverse()
    return added


def names(data: bytes | bytearray, table: NameTable) -> list[str]:
    """Every name in ``table``, in index order. Raises if an entry points at unmapped memory."""
    read_back = [read_cstring(data, pointer) for pointer in table.pointers]
    if any(entry is None for entry in read_back):
        raise ValueError("a modifier-type entry points at unmapped memory")
    return [entry for entry in read_back if entry is not None]
