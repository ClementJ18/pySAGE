"""The engine's `WeaponSetFlags` name table, and how a patch appends a name to it.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address here is derived
in ``../docs/production-model-condition.md`` §10.

A `WeaponSetFlag` is what an object's `WeaponSet` blocks select on: `WeaponSet::updateWeaponSet`
(``0x006C99E2``) scores every `WeaponTemplateSet` the `ThingTemplate` declares against the flags
the object is currently carrying, and installs the winner. Adding a name to this table therefore
buys a mod a new ``Conditions =`` token - a whole extra weapon loadout switchable from the engine
side.

Why this is cheaper than a model condition
------------------------------------------
The table is read through its **terminator**, never through a count:

* the INI token resolves through `INI::scanIndexList` (``0x0042B914``), which walks to the NULL;
* `getBitFromName` (``0x0068CE19``) walks to the NULL;
* selection is pure mask arithmetic - the two scoring helpers (``0x0073C77B`` matched-bit
  popcount, ``0x0073C7D2`` mismatched-bit popcount) loop over **4 dwords** flat, as do the
  whole-mask set (``0x0068CC53``) and clear (``0x0068CC38``) helpers.

So there is no count to raise anywhere on the path that makes a new flag *work*, and none of the
ten-count-sites problem `ModelConditionFlags` has. Relocating the table and repointing its eight
references is the entire data-side patch.

Why :data:`BIT_COUNT_VA` is asserted and never written
------------------------------------------------------
`getBitCount` (``0x0068CC34``: ``push 0x68; pop eax; ret``) answers **104**, and exactly two
things consume it, neither of which a new flag wants to be part of:

* ``0x00690F40`` and ``0x0069120E`` walk bits ``0..103`` against the weaponset-to-model-condition
  map at ``0x00C16958``, which has **104 entries**. Raising the count without extending that map
  would read past it; leaving it alone keeps bit 104 out of a mapping it has no entry in anyway,
  which is what a patch that already installs its own model condition wants.
* `xfer` bounds the saved bit list by it, so bit 104 is not written to a savegame. That is a
  feature for a flag whose whole value is recomputed from live state every frame - and it is why
  the driver of such a flag must be **level-triggered**, testing the bit each frame rather than
  acting on a transition, so a loaded game re-asserts it.

:func:`read` therefore asserts those four bytes verbatim: the count staying at 104 is an
invariant this patch relies on, not an incidental fact.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from .name_tables import (
    NameTable,
    check_fingerprint,
    layout,
    offset,
    read_terminated,
    ref_edits,
    resolve_base,
)

__all__ = [
    "CLEAR_FLAGS_VA",
    "MASK_DWORDS",
    "MASK_OFFSET",
    "NAME_TABLE_VA",
    "SET_FLAGS_VA",
    "STOCK_FLAG_COUNT",
    "TABLE_FINGERPRINT",
    "TABLE_REF_VAS",
    "layout",
    "mask_bytes",
    "read",
    "relocation_edits",
]


#: The stock NULL-terminated `WeaponSetFlags` name table. Only used to recognise an unpatched
#: image - :func:`read` follows the references.
NAME_TABLE_VA = 0x00DA1328

#: Named flags in the stock table, and `getBitCount`'s answer.
STOCK_FLAG_COUNT = 104

#: Every reference to the table. All eight are a bare imm32 holding the base, all in `.text`:
#: the two name<->bit helpers, the three `Conditions =` parse arms (``+FLAG``, ``-FLAG``, bare),
#: `getBitNames`, and the debug mask dumper.
TABLE_REF_VAS = (
    0x0068CD7A,  # nameFromBit  -> mov eax, [eax*4 + <table>]
    0x0068CE1F,  # getBitFromName: cmp dword [<table>], edi
    0x0068CE24,  # the same walk: mov esi, <table>
    0x006C906F,  # WeaponSet `Conditions =` parser, the `+` arm
    0x006C90AF,  # the `-` arm
    0x006C911A,  # the bare-token arm
    0x00881635,  # getBitNames -> mov eax, <table>
    0x008816B5,  # the debug mask dumper
)

#: Names at these indices fingerprint the build. Every index is below :data:`STOCK_FLAG_COUNT`,
#: so the check keeps working once the table has grown.
TABLE_FINGERPRINT = {
    0: "VETERAN",
    3: "PLAYER_UPGRADE",
    20: "CONTAINED",
    STOCK_FLAG_COUNT - 1: "WEAPONSET_CREATE_A_HERO_WS_64",
}

#: `Object`'s `WeaponSetFlags`, and its length in dwords. `Object::getWeaponSetFlags`
#: (``0x0068BE7D``) is literally ``lea eax, [ecx+0x38c]; ret``, and every whole-mask helper loops
#: 4 dwords - so 104 named flags leave bits 104..127 allocated and unnamed.
MASK_OFFSET = 0x38C
MASK_DWORDS = 4

#: `getBitCount` - ``push 0x68; pop eax; ret``. Asserted, never written; see the module docstring.
BIT_COUNT_VA = 0x0068CC34
BIT_COUNT_BYTES = bytes.fromhex("6a6858c3")

#: `Object::setWeaponSetFlags(const WeaponSetFlags&)` / `clearWeaponSetFlags`. Both are `thiscall`
#: with one stack argument (``ret 4``) taking a **whole mask**, not a bit index: they OR / AND-NOT
#: it into ``Object+0x38C`` and then call `WeaponSet::updateWeaponSet`, which is what actually
#: re-selects the weapon. Pass :func:`mask_bytes` for the argument.
SET_FLAGS_VA = 0x0068DECA
CLEAR_FLAGS_VA = 0x006911B7


def mask_bytes(bit: int) -> bytes:
    """The 4-dword `WeaponSetFlags` constant with only ``bit`` set - the argument the two helpers
    above take. A patch parks one of these in its own cave and pushes its address."""
    if not 0 <= bit < MASK_DWORDS * 32:
        raise ValueError(f"weapon set flag {bit} is outside the {MASK_DWORDS * 32}-bit mask")
    words = [0] * MASK_DWORDS
    words[bit // 32] = 1 << (bit % 32)
    return struct.pack(f"<{MASK_DWORDS}I", *words)


def read(data: bytes | bytearray) -> NameTable:
    """The live name table, recovered from the image rather than assumed.

    Checks that all eight references agree on a base, that `getBitCount` still reads 104, that
    the table is NULL-terminated, and that the four fingerprint names are at their known indices.
    Any of those failing means either a different build or a half-applied patch."""
    got = bytes(data[offset(data, BIT_COUNT_VA) : offset(data, BIT_COUNT_VA) + 4])
    if got != BIT_COUNT_BYTES:
        raise ValueError(
            f"the weapon-set-flag count @0x{BIT_COUNT_VA:08x} is encoded as {got.hex()}, expected "
            f"{BIT_COUNT_BYTES.hex()} (`push {STOCK_FLAG_COUNT}; pop eax; ret`) - either not the "
            "expected build, or something has raised it, which this patch relies on nothing doing"
        )
    base_va = resolve_base(data, TABLE_REF_VAS, "weapon-set-flag name table")
    pointers = read_terminated(data, base_va, "weapon-set-flag name table")
    if len(pointers) < STOCK_FLAG_COUNT:
        raise ValueError(
            f"the weapon-set-flag name table at 0x{base_va:08x} has {len(pointers)} entries, "
            f"below the stock {STOCK_FLAG_COUNT}"
        )
    check_fingerprint(data, pointers, TABLE_FINGERPRINT, "weapon set flag")
    return NameTable(base_va=base_va, pointers=pointers)


def relocation_edits(
    data: bytes | bytearray, table: NameTable, new_base_va: int
) -> list[tuple[int, bytes, bytes, str]]:
    """The edits repointing all eight references at the rebuilt table. There is deliberately no
    count to raise alongside them - see the module docstring."""
    return ref_edits(data, TABLE_REF_VAS, table.base_va, new_base_va, "weapon-set-flag name table")


def check_free(table: NameTable, data: bytes | bytearray, new_names: Sequence[str]) -> None:
    """Raise unless every name in ``new_names`` can be added: not already present, and still
    inside the 128-bit mask once appended."""
    for name in new_names:
        index = table.index_of(data, name)
        if index is not None:
            raise ValueError(f"{name!r} is already weapon set flag {index} - choose another name")
    if table.count + len(new_names) > MASK_DWORDS * 32:
        raise ValueError(
            f"{table.count} + {len(new_names)} flags overflows the {MASK_DWORDS * 32}-bit "
            "WeaponSetFlags mask, which is an Object layout change rather than a byte patch"
        )
