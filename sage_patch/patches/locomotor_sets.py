"""The engine's `LocomotorSetType` name table, and how a patch appends a name to it.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address here is derived
in ``../docs/production-model-condition.md`` §11.

A locomotor set is the engine-side half of ``Locomotor = SET_X <template>``: the `ThingTemplate`
declares one vector of locomotor templates per set, and the AI switches between them by calling
`chooseLocomotorSet`. Unlike the other two tables this one is an **enum**, not a bitmask - a set
is an index, so the question is not "is there a spare bit" but "does anything index a fixed-size
array with it".

Nothing does. The storage is a **tree keyed by the set index**:

* ``ThingTemplate+0x3AC`` is a `std::map<LocomotorSetType, LocomotorTemplateVector>` (size at
  ``+0x3B0``), filled through `operator[]` (``0x005E983D``) by the INI parser at ``0x0073FB3F``
  and read by `findLocomotorTemplateVector` (``0x0073DD59``), which returns **NULL** for a key the
  template does not carry;
* ``ThingTemplate+0x3A0`` is a second map keyed the same way (the per-set attack distance);
* the token itself resolves through `INI::scanIndexList`, which walks to the terminator.

So an eighteenth set costs a table relocation and nothing else - no count, no array, no struct.

The fallback is what makes driving one safe
-------------------------------------------
`AIUpdateInterface::chooseLocomotorSet` (``0x006680B2``) is a no-op in every case a patch would
worry about. It returns early when the set is already current; it refuses outright while the
forced-locomotor flag at ``+0x3C9`` is set; and it delegates to `setLocomotorSet` (``0x00667FC9``),
which returns false - changing nothing - when the template has no locomotor for that set. An
object whose INI never mentions the new set is therefore untouched by a patch that asks for it
every frame.
"""

from __future__ import annotations

from collections.abc import Sequence

from .name_tables import (
    NameTable,
    check_fingerprint,
    layout,
    read_terminated,
    ref_edits,
    resolve_base,
)

__all__ = [
    "AI_MODULE_OFFSET",
    "CHOOSE_SET_SLOT",
    "CURRENT_SET_OFFSET",
    "NAME_TABLE_VA",
    "NORMAL_SET",
    "STOCK_SET_COUNT",
    "TABLE_FINGERPRINT",
    "TABLE_REF_VAS",
    "check_free",
    "layout",
    "read",
    "relocation_edits",
]

# --- fixed facts about the target build (VA, ImageBase 0x400000) ---------------------------

#: The stock NULL-terminated `LocomotorSetType` name table. Only used to recognise an unpatched
#: image - :func:`read` follows the references.
NAME_TABLE_VA = 0x00DA0530

#: Named sets in the stock table, and the index an appended one takes.
STOCK_SET_COUNT = 17

#: Every reference to the table: four `push imm32` in `.text`, and four `userData` slots in INI
#: field descriptors, which is how the four single-valued locomotor-set fields resolve their token.
TABLE_REF_VAS = (
    0x005E9B07,  # the per-set INI parser (`Locomotor =`)
    0x0066E9F9,  # the AIUpdate-side parser
    0x008816FC,  # the debug dumper
    0x0089A6B4,  # the script action that sets an object's locomotor set
    0x00C0F628,  # field descriptor: `ComboLocomotorSet`
    0x00C2E028,  # field descriptor: `AttackLocomotorType`
    0x00C2E038,  # field descriptor: `ReturnForAmmoLocomotorType`
    0x00C5BCC8,  # field descriptor: `ForcedLocomotorSet`
)

#: Names at these indices fingerprint the build.
TABLE_FINGERPRINT = {
    0: "SET_NORMAL",
    1: "SET_NORMAL_UPGRADED",
    4: "SET_PANIC",
    STOCK_SET_COUNT - 1: "SET_BURNINGDEATH",
}

#: The set every object falls back to, and the one a patch reverts to when it is done.
NORMAL_SET = 0

#: `Object`'s `AIUpdateInterface*`. NULL on anything without an AI - most structures - so a hook
#: must test it before dereferencing.
AI_MODULE_OFFSET = 0x260

#: `AIUpdate`'s current `LocomotorSetType`, which `chooseLocomotorSet` compares against before
#: doing any work. A patch reads it to tell "still the set I asked for" from "something else has
#: chosen since", so it can revert without stomping a set it did not install.
CURRENT_SET_OFFSET = 0x1F4

#: `chooseLocomotorSet`'s vtable slot on the AI module - `thiscall`, one stack argument
#: (``ret 4``), returns bool in al. The engine's own call at ``0x0089A6BC`` is the shape to copy:
#: ``mov ecx,[obj+0x260]; push <set>; mov edx,[ecx]; call [edx+0x238]``.
CHOOSE_SET_SLOT = 0x238


def read(data: bytes | bytearray) -> NameTable:
    """The live name table, recovered from the image rather than assumed.

    Checks that all eight references agree on a base, that the table is NULL-terminated, and that
    the four fingerprint names are at their known indices."""
    base_va = resolve_base(data, TABLE_REF_VAS, "locomotor-set name table")
    pointers = read_terminated(data, base_va, "locomotor-set name table")
    if len(pointers) < STOCK_SET_COUNT:
        raise ValueError(
            f"the locomotor-set name table at 0x{base_va:08x} has {len(pointers)} entries, "
            f"below the stock {STOCK_SET_COUNT}"
        )
    check_fingerprint(data, pointers, TABLE_FINGERPRINT, "locomotor set")
    return NameTable(base_va=base_va, pointers=pointers)


def relocation_edits(
    data: bytes | bytearray, table: NameTable, new_base_va: int
) -> list[tuple[int, bytes, bytes, str]]:
    """The edits repointing all eight references at the rebuilt table."""
    return ref_edits(data, TABLE_REF_VAS, table.base_va, new_base_va, "locomotor-set name table")


def check_free(table: NameTable, data: bytes | bytearray, new_names: Sequence[str]) -> None:
    """Raise unless every name in ``new_names`` is free to add."""
    for name in new_names:
        index = table.index_of(data, name)
        if index is not None:
            raise ValueError(f"{name!r} is already locomotor set {index} - choose another name")
