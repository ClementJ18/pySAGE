"""The large-group-bonus filter: let `LargeGroupBonusUpdate` count objects that are not in a horde.

Adds one INI keyword - `CountLooseObjects` by default - to `LargeGroupBonusUpdate`. Targets the
ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived in
``../docs/large-group-bonus-filter.md``.

**Why the stock filter is horde-only, and it is not the filter's fault.** `HordeMemberFilter` is an
ordinary `ObjectFilter` - the same four-byte interned handle `banner-filter` and
`player-heal-filter` add, parsed by the same `OBJECT_FILTER_PARSE_VA`, released by this module's own
destructor at ``0x00893B75``. Nothing about its grammar is horde-specific. It is horde-only because
**it is never evaluated against the object the partition scan returned**. It is only ever passed one
level down, as an argument, to that object's *contain* interface (vslot ``+0x180``), which counts
its own contained members against it. `Object::getContain` returns NULL for anything with no contain
module, and both places that ask treat NULL as contributing zero:

* `PARTITION_ALLOW_VA` - the `allow` of the filter wrapper `update` builds on its stack. A
  container-less object is rejected here, so the scan never even returns it.
* `COUNT_WINDOW_VA` - the accumulator loop, which repeats the same test.

So a lone hero, a unit outside a horde or a structure cannot be counted, whatever the filter says.

**What this adds.** A `Bool` at ``ModuleData+0x19``. When it is `Yes`, both gates additionally
accept an object with no contain interface whose `ThingTemplate` `HordeMemberFilter` itself matches,
counting it as one. When it is `No` - the default, and every mod shipping today - the stock vtable
is installed and the accumulator's cave returns zero for such an object, so the module behaves bit
for bit as it does now.

**Both gates move together or neither does.** Widening only the accumulator achieves nothing,
because the partition filter has already removed loose objects from the iteration; widening only the
partition filter achieves nothing either, because the accumulator would then skip what the scan
handed it. That is why they are one patch and not two.

**The flag costs no allocation.** The constructor writes `AlliesOnly` with a *byte* store at
`ALLIES_ONLY_DEFAULT`, so ``+0x19``..``+0x1b`` is alignment padding it never touches - the next
field, `RubOffRadius`, starts at ``+0x1c``. ``sizeof(ModuleData)`` stays ``0x30`` and the
``push 0x30`` at `MODULEDATA_SIZE_VA` is left alone. `operator new` does not zero, so the default
still has to be written, and the byte store cannot be widened in place (a word or dword form is two
to three bytes longer and the very next instruction writes ``+0x1c``) - hence the constructor shim,
which is the same shape both existing filter patches use.

Four edits, one cave
--------------------
1. **The default.** `MODULEDATA_CTOR_CALL_VA` is redirected through a shim that runs the stock
   constructor and zeroes the new byte. The stock ctor is ``__thiscall``, takes no arguments and
   returns ``this`` in ``eax``, so the shim needs no frame of its own and stays transparent to the
   unwinder inside `newModuleData`'s protected region.
2. **The keyword.** The field-parse table at `FIELD_TABLE_VA` cannot grow in place: it ends at
   ``0x00C63A68`` where an unrelated ``.rdata`` path string begins. It is named by **exactly one**
   instruction, so the patch copies the eight stock rows verbatim - their name pointers are
   absolute and keep pointing into ``.rdata`` - appends one row and the terminator, and repoints
   that imm32. Lookup is a linear name scan over a table in declaration order, so appending needs
   no re-sort, and this module inherits no second table, so there is no duplicate-keyword hazard of
   the kind `player-heal-filter` has to guard against.
3. **Gate 1.** The ten bytes at `SETUP_WINDOW_VA` (``lea eax,[edi+0xc]`` plus the store of the
   wrapper vtable) become a ``call`` into a shim that does the same two things and then, only when
   the flag is set *and* `HordeMemberFilter` was actually written, swaps in a cave-built copy of the
   vtable whose `allow` is the widened one, parking the owning `Object` in the wrapper's free ``+4``
   slot. Choosing the vtable rather than editing `PARTITION_ALLOW_VA` in place is what keeps the
   unwidened path byte-identical.
4. **Gate 2.** The 28 bytes at `COUNT_WINDOW_VA` - the whole "getContain, bail on null, else count"
   block plus its accumulate - become ``mov ecx,eax`` / ``call`` / ``add [ebp-0x18],eax`` and
   padding. The window is self-contained: its only inbound branch is the loop's own back edge at
   ``0x00893A01``, which lands on the first byte.
The cave holds the keyword string, the copied vtable, the rebuilt table and four stubs, in that
order - the keyword first so :meth:`LargeGroupBonusFilterPatch.detect` can read it straight off the
section base.

Why the evaluator and not the wrapper
-------------------------------------
`0x007640C1` is a convenience wrapper around the real evaluator `OBJECT_FILTER_TEST_VA`, which takes
three arguments: the candidate's `ThingTemplate`, the candidate's `Player`, and the **source**
`Player` the filter is written from. The wrapper passes its own second parameter through as that
source and every stock call site passes ``0``; with a null source the evaluator rejects
unconditionally whenever the relationship mask is non-zero, so relationship tokens routed through it
do not degrade to permissive, they *always* return false. Both stubs here call the evaluator
directly with the module owner's own player, exactly as `banner-filter` and `player-heal-filter` do.

The source player is not read out of a frame slot. Gate 2 has the owning `Object` in ``ebx``, live
since ``0x008938EA`` and unclobbered for the whole function; gate 1's `allow` runs inside the
partition scan with no such register, so the shim stashes the same pointer in the wrapper's ``+4``
slot - a dword the update zeroes at ``0x0089393F`` and **nothing reads**, since the stock
`allow` looks only at ``+8`` (the filter) and ``+0xc`` (its accept/reject polarity).

`isDefined` gates the widened path as well as the flag
------------------------------------------------------
A `LargeGroupBonusUpdate` that never wrote `HordeMemberFilter` still hands the default handle to the
contain interface today, and what that means for a *container* is the contain module's business. On
the loose-object side there is no such precedent, and "count every nearby object" is not a default
worth inferring from silence - so both stubs ask `OBJECT_FILTER_IS_DEFINED_VA` first and contribute
nothing when the keyword was never written. `CountLooseObjects` without `HordeMemberFilter` is
therefore inert rather than sweeping.

**What this does not fix.** `AlliesOnly` is parsed by this module and read by nothing: the scan's
ownership rule is hardcoded in a second partition filter (``0x00660AFE``), a strict
``getControllingPlayer(candidate) == getControllingPlayer(owner)`` test. So a widened filter still
only ever sees the module owner's own objects, and `ENEMIES` / `NEUTRAL` / `ALLIES` can only narrow
to nothing. Honouring `AlliesOnly` means repointing the vtable store at ``0x0089396A``, whose vtable
is shared with twelve other sites - a separate patch, deliberately not this one.

**Determinism.** The bonus is applied through `AttributeModifier` on the logic-side `Object`, so
**every peer must run the same patched binary** and replays do not cross. And, as with
`terrain-resource-exp` and `queue-ignore-cp`, the new keyword is an INI **parse error** on a stock
build rather than a warning.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name,
no edited byte is shared with another bundled patch, and the only structure read - the stock
`LargeGroupBonusUpdate` field-parse table and wrapper vtable - is one nothing else rewrites. The
nearest neighbour, `banner-filter`, lives in ``0x0089A7xx``-``0x0089AExx``.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import FIELD_PARSE_STRIDE, INI_PARSE_BOOL
from ..asm import JA, JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "COUNT_WINDOW_BYTES",
    "COUNT_WINDOW_VA",
    "DEFAULT_KEYWORD",
    "FIELD_TABLE_REF_VA",
    "FIELD_TABLE_VA",
    "FILTER_OFFSET",
    "FLAG_OFFSET",
    "MODULEDATA_CTOR_CALL_VA",
    "MODULEDATA_CTOR_VA",
    "MODULEDATA_SIZE",
    "PARTITION_ALLOW_VA",
    "SECTION_NAME",
    "SETUP_WINDOW_BYTES",
    "SETUP_WINDOW_VA",
    "STOCK_FIELDS",
    "WRAPPER_VTABLE_SLOTS",
    "WRAPPER_VTABLE_VA",
    "LargeGroupBonusFilterPatch",
    "build_count",
    "build_ctor",
    "build_new_allow",
    "build_setup",
    "build_table",
    "validate_keyword",
]

# --- LargeGroupBonusUpdate, as this build lays it out (VA, ImageBase 0x400000) ---

#: `newModuleData`'s ``push 0x30`` - the sole `sizeof(ModuleData)` literal. **Not patched**: the
#: new field lands in padding. Asserted so a build whose structure is a different size is refused.
MODULEDATA_SIZE_VA = 0x0064D124
MODULEDATA_SIZE = 0x30

#: The ``call`` to the ModuleData constructor, inside `newModuleData`, and the ctor itself. The
#: ctor has exactly one caller, which is this site.
MODULEDATA_CTOR_CALL_VA = 0x0064D139
MODULEDATA_CTOR_VA = 0x00893871

#: ``mov byte [esi+0x18], 1`` - `AlliesOnly`'s default. A *byte* store, which is what leaves
#: ``+0x19``..``+0x1b`` as padding; the next field is written by the ``movss`` to ``+0x1c`` four
#: bytes later.
ALLIES_ONLY_DEFAULT = (0x008938B8, bytes.fromhex("c6461801"))

#: The 16-byte-stride field-parse table, and the single imm32 that loads it (inside
#: ``push 0xc639d8`` at ``0x0089375A``, so the operand starts one byte later).
FIELD_TABLE_VA = 0x00C639D8
FIELD_TABLE_REF_VA = 0x0089375B

#: The stack-built partition filter that carries `HordeMemberFilter`: its vtable, the three slots
#: the patch copies, and the `allow` in slot 1 that both this patch and the stock engine use as the
#: horde gate. The class appears nowhere else - `allow` is referenced only from this vtable, and
#: the vtable only from `SETUP_WINDOW_VA` and an out-of-line constructor with zero callers.
WRAPPER_VTABLE_VA = 0x00C63870
WRAPPER_VTABLE_SLOTS = 3
PARTITION_ALLOW_VA = 0x00660C72
#: The wrapper's own layout: ``+4`` free, ``+8`` the `ObjectFilter *`, ``+0xc`` the polarity byte.
WRAPPER_OWNER_SLOT = 0x04
WRAPPER_FILTER_SLOT = 0x08
WRAPPER_POLARITY_SLOT = 0x0C
#: ``[ebp-0x50]`` and ``[ebp-0x4c]`` - where `update` builds the wrapper in its own frame.
WRAPPER_VTABLE_DISP8 = -0x50
WRAPPER_OWNER_DISP8 = -0x4C

#: Gate 1: ``lea eax,[edi+0xc]`` + ``mov dword [ebp-0x50], 0xc63870``. Ten bytes, replaced by a
#: ``call`` and padding. The ``lea``'s result is consumed by the ``mov [ebp-0x48], eax`` that
#: follows the window, so the shim has to reproduce it.
SETUP_WINDOW_VA = 0x00893946
SETUP_WINDOW_BYTES = bytes.fromhex("8d470cc745b07038c600")

#: Gate 2: the accumulator's whole ``getContain`` / bail / count / accumulate block. Its only
#: inbound branch is the loop back edge at ``0x00893A01``, which lands on the first byte.
COUNT_WINDOW_VA = 0x008939DB
COUNT_WINDOW_BYTES = bytes.fromhex("8bc8e8848edfff85c074118b108d4f0c518bc8ff92800100000145e8")
#: ``[ebp-0x18]`` - the accumulator the window adds into, reproduced by the replacement.
COUNT_ACCUMULATOR_DISP8 = -0x18

#: `Object::getContain` - ``__thiscall(ecx=Object*) -> ContainModuleInterface*``, NULL when the
#: object has no contain module. This one test is the whole of why the stock filter is horde-only.
GET_CONTAIN_VA = 0x0068C866
#: The contain interface's member-count slot:
#: ``__thiscall(ecx=iface, const ObjectFilter *) -> Int``, ``ret 4``. A NULL filter counts
#: everything; this module always passes one.
CONTAIN_COUNT_SLOT = 0x180

GET_CONTROLLING_PLAYER_VA = 0x0068B678  # __thiscall(ecx=Object*) -> Player*

# --- the ObjectFilter handle ABI (see docs/banner-carrier-filter.md) ---

OBJECT_FILTER_PARSE_VA = 0x0076392F  # the INI parse fn that goes in the field table
OBJECT_FILTER_IS_DEFINED_VA = 0x00762977  # __thiscall(ecx=&field) -> bool, reads the +0x88 flag
OBJECT_FILTER_TEST_VA = 0x00763543  # __thiscall(ecx=&field, template, player, source), ret 0xc

# --- layout ---

#: `HordeMemberFilter`, the `ObjectFilter` handle this patch reuses rather than adding another.
FILTER_OFFSET = 0x0C
#: Where the new `Bool` lands: alignment padding after `AlliesOnly`, so nothing grows.
FLAG_OFFSET = 0x19

#: The stock table, in table order, as ``(name, ModuleData offset)``. Used as a fingerprint: all
#: eight names *and* offsets must match before anything is written, which is a far stronger build
#: check than any single literal.
STOCK_FIELDS = (
    ("UpdateRate", 0x08),
    ("HordeMemberFilter", 0x0C),
    ("Count", 0x10),
    ("Radius", 0x14),
    ("RubOffRadius", 0x1C),
    ("AlliesOnly", 0x18),
    ("FlagSubObjectNames", 0x20),
    ("AttributeModifier", 0x2C),
)

DEFAULT_KEYWORD = "CountLooseObjects"

SECTION_NAME = ".lgbflt"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds the copied vtable, the
# rebuilt table, the keyword string and four stubs, so it is both read as data and entered as code.
SECTION_CHARACTERISTICS = 0x60000060

#: Byte windows the patch depends on and does not rewrite. The register anchors matter most: both
#: stubs read `edi` as the `ModuleData` and `ebx` as the owning `Object`, and nothing the patch
#: writes would catch a mismatch - the cave would simply dereference whatever the registers held.
ANCHORS: dict[int, bytes] = {
    # `newModuleData`: the size literal this patch deliberately does not touch
    MODULEDATA_SIZE_VA: bytes.fromhex("6a30"),
    # the ctor's tail: `AlliesOnly`'s byte store (so +0x19 is padding), `RubOffRadius` four bytes
    # later, the vector ctor for `FlagSubObjectNames`, and `mov eax, esi` returning `this`
    0x008938B8: bytes.fromhex("c6461801f30f11461ce8f853beff83662c008b4df48bc6"),
    # `update`'s prologue: esi = the module, ebx = [esi-8] the owning Object
    0x008938E8: bytes.fromhex("8bf18b5ef8"),
    # ... and edi = [esi-0xc], the ModuleData
    0x00893909: bytes.fromhex("8b7ef4"),
    # `and dword [ebp-0x4c], 0` - the wrapper's +4 slot, zeroed and read by nothing
    0x0089393F: bytes.fromhex("8365b400"),
    # the instruction after gate 1's window, which consumes the `lea`'s result
    0x00893950: bytes.fromhex("8945b8"),
    # the instruction after gate 2's window: the loop tail both the stock `je` and the replacement
    # fall through to
    0x008939F7: bytes.fromhex("8d4dec"),
    # the stock `allow` the cave's copy is modelled on, in full: getContain, bail on null, hand the
    # filter to +0x180, and the two-way polarity return the widened version reproduces
    PARTITION_ALLOW_VA: bytes.fromhex(
        "568bf18b4c2408e8e8bb020085c07416ff76088b108bc8ff928001000085c0"
        "76058a460ceb0833c038460c0f94c05ec20400"
    ),
    # `Object::getContain` itself: the null answer that makes a loose object invisible
    GET_CONTAIN_VA: bytes.fromhex("8b895802000085c9750333c0c38b01ff607c"),
}

# An INI keyword is matched by exact compare, so anything the parser could never match is a typo
# rather than a choice. The engine's own field names are CamelCase with digits and underscores.
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def validate_keyword(keyword: str) -> None:
    """Raise unless ``keyword`` is a token the engine's INI reader could ever match, and one this
    module does not already parse."""
    if not _KEYWORD_PATTERN.match(keyword):
        raise ValueError(
            "an INI keyword must be letters, digits and underscores starting with a letter "
            f"(the reader matches it by exact compare), got {keyword!r}"
        )
    if any(keyword.lower() == name.lower() for name, _off in STOCK_FIELDS):
        raise ValueError(f"{keyword!r} is already a LargeGroupBonusUpdate field")


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _disp8(value: int) -> int:
    return value & 0xFF


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    if end < 0:
        return None
    try:
        return bytes(data[off : off + end]).decode("ascii")
    except UnicodeDecodeError:
        return None


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address and the keyword.

    Pure arithmetic on the keyword's length, so :meth:`LargeGroupBonusFilterPatch.apply` and
    :meth:`LargeGroupBonusFilterPatch.verify` compute the same addresses from opposite directions.
    The keyword is first so :meth:`LargeGroupBonusFilterPatch.detect` can read it straight off the
    section base without knowing how long anything after it is."""

    keyword_va: int
    vtable_va: int
    table_va: int
    ctor_va: int
    setup_va: int
    allow_va: int
    count_va: int


def _layout(base_va: int, keyword: str) -> _Layout:
    string = len(keyword) + 1
    vtable_va = base_va + string + (-string % 4)  # keep every dword after it aligned
    table_va = vtable_va + WRAPPER_VTABLE_SLOTS * 4
    ctor_va = table_va + (len(STOCK_FIELDS) + 2) * FIELD_PARSE_STRIDE  # + the row + the terminator
    setup_va = ctor_va + len(build_ctor(ctor_va))
    allow_va = setup_va + len(build_setup(setup_va, 0, 0))
    count_va = allow_va + len(build_new_allow(allow_va))
    return _Layout(base_va, vtable_va, table_va, ctor_va, setup_va, allow_va, count_va)


# --- the cave's four stubs ---------------------------------------------------------------------


def build_table(keyword_va: int, stock_rows: bytes) -> bytes:
    """The rebuilt field-parse table: the stock rows verbatim, the new `Bool`, the terminator.

    The stock rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are, in ``.rdata``, and only the new row points into the
    cave."""
    new_row = struct.pack("<IIII", keyword_va, INI_PARSE_BOOL, 0, FLAG_OFFSET)
    return stock_rows + new_row + bytes(FIELD_PARSE_STRIDE)


def build_ctor(base_va: int) -> bytes:
    """Run the stock ModuleData constructor, then default the new flag to `No`.

    The stock ctor is ``__thiscall`` with no arguments and returns ``this`` in ``eax``, so the shim
    needs no frame of its own - which also keeps it transparent to the unwinder, since the call site
    it replaces sits inside `newModuleData`'s protected region. `operator new` does not zero, so
    without this the flag would hold whatever the allocator left there and the field would default
    to whatever that byte happened to be."""
    a = Asm(base_va)
    a.call_absolute(MODULEDATA_CTOR_VA)  # call <stock ctor>       ; eax = this
    a.emit(b"\xc6\x40", FLAG_OFFSET, 0x00)  # mov byte [eax+0x19], 0
    a.emit(0xC3)  # ret
    return a.finish()


def build_setup(base_va: int, vtable_va: int, stock_vtable_va: int) -> bytes:
    """Gate 1: build the partition-filter wrapper, choosing which `allow` it will dispatch to.

    Entered in place of the two instructions at `SETUP_WINDOW_VA`, so it owes the caller both of
    their effects: the wrapper's vtable slot written, and ``eax`` left holding
    ``&ModuleData.HordeMemberFilter`` for the ``mov [ebp-0x48], eax`` that follows the window.

    ``ebp`` is `update`'s own frame, ``edi`` the `ModuleData` and ``ebx`` the owning `Object`, all
    established before the window and asserted by :data:`ANCHORS`. ``eax``, ``ecx`` and ``edx`` are
    dead here on every path into the window, and `isDefined` is ``__thiscall`` and preserves
    everything else, so nothing has to be saved.

    The widened vtable is installed only when the flag is set **and** the filter was written; see
    the module docstring on why an unwritten filter is not taken to mean "count everything"."""
    a = Asm(base_va)
    a.emit(b"\xc7\x45", _disp8(WRAPPER_VTABLE_DISP8), _u32(stock_vtable_va))
    #                       mov dword [ebp-0x50], <stock vtable>
    a.emit(b"\x80\x7f", FLAG_OFFSET, 0x00)  # cmp byte [edi+0x19], 0
    a.jcc(JE, "done")  # je .done                ; flag clear -> stock
    a.emit(b"\x8d\x4f", FILTER_OFFSET)  # lea ecx, [edi+0xc]
    a.call_absolute(OBJECT_FILTER_IS_DEFINED_VA)  # call <isDefined>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "done")  # je .done                ; no filter written -> stock
    a.emit(b"\xc7\x45", _disp8(WRAPPER_VTABLE_DISP8), _u32(vtable_va))
    #                       mov dword [ebp-0x50], <cave vtable>
    a.emit(b"\x89\x5d", _disp8(WRAPPER_OWNER_DISP8))  # mov [ebp-0x4c], ebx  ; the owning Object
    a.label("done")
    a.emit(b"\x8d\x47", FILTER_OFFSET)  # lea eax, [edi+0xc]      ; what the window left in eax
    a.emit(0xC3)  # ret
    return a.finish()


def build_new_allow(base_va: int) -> bytes:
    """The widened `allow`, dispatched through the cave's copy of the wrapper vtable.

    ``__thiscall(ecx = wrapper, Object *candidate) -> bool``, ``ret 4`` - the stock signature. The
    contain-carrying path is the stock one instruction for instruction; a candidate with no contain
    interface, which the stock version rejects outright, is instead put to the `ObjectFilter`
    directly.

    The source player comes from the wrapper's ``+4`` slot, which :func:`build_setup` filled - the
    partition scan runs with no register holding the module's own object, and the stock `allow`
    reads only ``+8`` and ``+0xc``, so that dword is free.

    Both exits reproduce the stock polarity contract exactly: a match returns the wrapper's ``+0xc``
    byte, a non-match returns whether that byte is zero."""
    a = Asm(base_va)
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(b"\x8b\xf1")  # mov  esi, ecx           ; the wrapper
    a.emit(b"\x8b\x5c\x24\x0c")  # mov  ebx, [esp+0xc]     ; the candidate
    a.emit(b"\x8b\xcb")  # mov  ecx, ebx
    a.call_absolute(GET_CONTAIN_VA)  # call <getContain>
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "loose")  # je .loose               ; no contain -> the new path

    a.emit(b"\xff\x76", WRAPPER_FILTER_SLOT)  # push dword [esi+8]   ; &HordeMemberFilter
    a.emit(b"\x8b\x10")  # mov  edx, [eax]
    a.emit(b"\x8b\xc8")  # mov  ecx, eax
    a.emit(b"\xff\x92", _u32(CONTAIN_COUNT_SLOT))  # call dword [edx+0x180]  ; ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JA, "match")  # ja .match
    a.jmp("nomatch")

    a.label("loose")
    a.emit(b"\x8b\x4e", WRAPPER_FILTER_SLOT)  # mov ecx, [esi+8]
    a.call_absolute(OBJECT_FILTER_IS_DEFINED_VA)  # call <isDefined>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "nomatch")  # je .nomatch            ; unwritten -> contributes nothing
    a.emit(b"\x8b\x4e", WRAPPER_OWNER_SLOT)  # mov ecx, [esi+4]    ; the owning Object
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)
    a.emit(0x50)  # push eax                ; arg3 = the source player
    a.emit(b"\x8b\xcb")  # mov  ecx, ebx
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)
    a.emit(0x50)  # push eax                ; arg2 = the candidate's player
    a.emit(b"\xff\x73\x04")  # push dword [ebx+4]      ; arg1 = its ThingTemplate*
    a.emit(b"\x8b\x4e", WRAPPER_FILTER_SLOT)  # mov ecx, [esi+8]
    a.call_absolute(OBJECT_FILTER_TEST_VA)  # call <evaluator>        ; ret 0xc
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "nomatch")

    a.label("match")
    a.emit(b"\x8a\x46", WRAPPER_POLARITY_SLOT)  # mov al, [esi+0xc]
    a.emit(0x5E)  # pop  esi
    a.emit(0x5B)  # pop  ebx
    a.emit(b"\xc2\x04\x00")  # ret  4

    a.label("nomatch")
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.emit(b"\x38\x46", WRAPPER_POLARITY_SLOT)  # cmp [esi+0xc], al
    a.emit(b"\x0f\x94\xc0")  # sete al
    a.emit(0x5E)  # pop  esi
    a.emit(0x5B)  # pop  ebx
    a.emit(b"\xc2\x04\x00")  # ret  4
    return a.finish()


def build_count(base_va: int) -> bytes:
    """Gate 2: what one candidate contributes to the count.

    ``__thiscall``-shaped: ``ecx`` is the candidate, the answer comes back in ``eax``, and the
    caller adds it into ``[ebp-0x18]`` exactly as the stock window did. ``edi`` is the `ModuleData`
    and ``ebx`` the owning `Object`, both live across the whole loop; the stub clobbers only
    ``eax``/``ecx``/``edx``, which the stock window clobbers too.

    A container contributes its matching member count, a loose object contributes one, and anything
    else contributes zero. The candidate lives on the stack rather than in a register because every
    callee here is ``__thiscall`` and only the callee-saved set survives, and those are all spoken
    for."""
    a = Asm(base_va)
    a.emit(0x51)  # push ecx                ; save the candidate
    a.call_absolute(GET_CONTAIN_VA)  # call <getContain>       ; ecx is still the candidate
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "loose")

    a.emit(b"\x8d\x4f", FILTER_OFFSET)  # lea  ecx, [edi+0xc]
    a.emit(0x51)  # push ecx                ; &HordeMemberFilter
    a.emit(b"\x8b\x10")  # mov  edx, [eax]
    a.emit(b"\x8b\xc8")  # mov  ecx, eax
    a.emit(b"\xff\x92", _u32(CONTAIN_COUNT_SLOT))  # call dword [edx+0x180]  ; ret 4
    a.emit(0x59)  # pop  ecx                ; drop the candidate
    a.emit(0xC3)  # ret

    a.label("loose")
    a.emit(b"\x80\x7f", FLAG_OFFSET, 0x00)  # cmp byte [edi+0x19], 0
    a.jcc(JE, "zero")
    a.emit(b"\x8d\x4f", FILTER_OFFSET)  # lea  ecx, [edi+0xc]
    a.call_absolute(OBJECT_FILTER_IS_DEFINED_VA)  # call <isDefined>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "zero")
    a.emit(b"\x8b\xcb")  # mov  ecx, ebx           ; the owning Object
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)
    a.emit(0x50)  # push eax                ; arg3 = the source player
    a.emit(b"\x8b\x4c\x24\x04")  # mov  ecx, [esp+4]       ; the candidate
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)
    a.emit(0x50)  # push eax                ; arg2 = the candidate's player
    a.emit(b"\x8b\x4c\x24\x08")  # mov  ecx, [esp+8]       ; the candidate
    a.emit(b"\xff\x71\x04")  # push dword [ecx+4]      ; arg1 = its ThingTemplate*
    a.emit(b"\x8d\x4f", FILTER_OFFSET)  # lea  ecx, [edi+0xc]
    a.call_absolute(OBJECT_FILTER_TEST_VA)  # call <evaluator>        ; ret 0xc
    a.emit(b"\x0f\xb6\xc0")  # movzx eax, al           ; a match contributes exactly 1
    a.emit(0x59)  # pop  ecx
    a.emit(0xC3)  # ret

    a.label("zero")
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.emit(0x59)  # pop  ecx
    a.emit(0xC3)  # ret
    return a.finish()


def setup_hook_bytes(setup_va: int) -> bytes:
    """`call rel32` to the gate-1 shim, padded to the ten bytes it displaces."""
    call = _call_bytes(SETUP_WINDOW_VA, setup_va)
    return call + b"\x90" * (len(SETUP_WINDOW_BYTES) - len(call))


def count_hook_bytes(count_va: int) -> bytes:
    """The gate-2 replacement, padded to the 28 bytes it displaces.

    ``mov ecx, eax`` is the stock window's own first instruction, and the ``add`` its last; only
    the middle - getContain, the null bail and the contain-interface call - is replaced."""
    body = (
        b"\x8b\xc8"  # mov ecx, eax
        + _call_bytes(COUNT_WINDOW_VA + 2, count_va)  # call <cave_count>
        + b"\x01\x45"
        + bytes((_disp8(COUNT_ACCUMULATOR_DISP8),))  # add [ebp-0x18], eax
    )
    return body + b"\x90" * (len(COUNT_WINDOW_BYTES) - len(body))


class LargeGroupBonusFilterPatch(Patch):
    """Let `LargeGroupBonusUpdate` count objects that are not inside a horde."""

    name = "large-group-bonus-filter"
    author = "officialNecro"
    description = (
        "Add a CountLooseObjects boolean to LargeGroupBonusUpdate, so HordeMemberFilter also "
        "matches objects that are not in a horde. Write CountLooseObjects = Yes beside the "
        "existing HordeMemberFilter; No, the default, is bit-for-bit stock"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    # --- apply / verify ----------------------------------------------------------------------

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        stock_rows = self._read_stock_table(data)
        stock_vtable = self._read_stock_vtable(data)

        base_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._build(va, stock_rows, stock_vtable),
            SECTION_CHARACTERISTICS,
        )
        for file_off, old, new, note in self._edits(data, _layout(base_va, self.keyword)):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch with exactly this keyword (an empty
        list == verified). Locates the cave, recomputes everything the keyword implies, and compares
        it and every rewritten site to what is on disk. Reads only via ``struct`` and the section
        table, so verification needs no disassembler.

        The stock rows and the stock vtable slots are read back **out of the cave's own copies**
        rather than from the addresses they came from, because those addresses still hold them: on a
        patched image they would only ever confirm the copy against itself."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located
        pieces = _layout(section_va, self.keyword)

        problems: list[str] = []
        try:
            stock_rows = self._copied_rows(data, pieces)
            stock_vtable = self._copied_vtable(data, pieces)
            content = self._build(section_va, stock_rows, stock_vtable)
            edits = self._edits(data, pieces)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        if len(content) > vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for this patch's cave"]
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(
                f"{SECTION_NAME} does not match keyword {self.keyword!r} "
                "(the vtable, table, string or stubs differ)"
            )
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        problems += self._table_problems(data, pieces)
        problems += self._anchor_problems(data)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> LargeGroupBonusFilterPatch | None:
        """Recognise this patch **and recover its keyword**.

        The default probe would only ever recognise the default keyword. The keyword string is the
        first thing in the cave (:func:`_layout` puts it at the section base), so it reads straight
        back out; `verify` then checks the whole cave against it."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = _read_cstring(data, located[0])
        if keyword is None:
            return None
        try:
            patch = cls(keyword)
        except ValueError:
            return None  # not a keyword this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one `Bool` this patch adds to `LargeGroupBonusUpdate`, under whatever keyword it was
        installed with. The constructor shim zeroes it, so the default is `No` - stock behaviour,
        which is what makes the field opt-in."""
        return Engine(
            fields=(FieldDelta("LargeGroupBonusUpdate", self.keyword, "Bool", False, self.name),)
        )

    # --- CLI integration ---------------------------------------------------------------------

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the INI field to add to LargeGroupBonusUpdate (default "
                f"{DEFAULT_KEYWORD}); letters, digits and underscores, and must not already be one "
                "of the module's eight fields"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> LargeGroupBonusFilterPatch:
        return cls(keyword=args.keyword)

    # --- the cave ------------------------------------------------------------------------------

    def _build(self, base_va: int, stock_rows: bytes, stock_vtable: tuple[int, ...]) -> bytes:
        """The cave: the keyword string, the copied wrapper vtable, the rebuilt field table, and
        the four stubs - in that order, so :meth:`detect` finds the keyword at the section base."""
        pieces = _layout(base_va, self.keyword)

        blob = bytearray(self.keyword.encode("ascii") + b"\x00")
        blob += bytes(pieces.vtable_va - (base_va + len(blob)))

        # The copy differs from the stock vtable in exactly one slot: `allow`.
        slots = list(stock_vtable)
        slots[1] = pieces.allow_va
        blob += b"".join(_u32(slot) for slot in slots)

        blob += build_table(pieces.keyword_va, stock_rows)
        assert base_va + len(blob) == pieces.ctor_va, "the cave layout and its addresses disagree"

        blob += build_ctor(pieces.ctor_va)
        blob += build_setup(pieces.setup_va, pieces.vtable_va, WRAPPER_VTABLE_VA)
        blob += build_new_allow(pieces.allow_va)
        blob += build_count(pieces.count_va)
        return bytes(blob)

    def _read_stock_table(self, data: bytes | bytearray) -> bytes:
        """The eight stock entries verbatim, after checking they really are this build's
        `LargeGroupBonusUpdate` table: every name and every `ModuleData` offset must match, and the
        ninth entry must be the NULL terminator.

        Checked before anything is written, because the table is copied into the cave wholesale
        rather than read row by row - a build whose table differs here would be rebuilt wrong and
        silently."""
        off = va_to_offset(data, FIELD_TABLE_VA)
        if off is None:
            raise ValueError(f"the field table VA 0x{FIELD_TABLE_VA:08x} is not mapped")

        size = len(STOCK_FIELDS) * FIELD_PARSE_STRIDE
        entries = bytes(data[off : off + size])
        if len(entries) != size:
            raise ValueError("the field table runs past the end of the image")

        for index, (name, offset) in enumerate(STOCK_FIELDS):
            name_va, _parse, _userdata, field_off = struct.unpack_from(
                "<4I", entries, index * FIELD_PARSE_STRIDE
            )
            got = _read_cstring(data, name_va)
            if got != name:
                raise ValueError(f"field table entry {index}: expected {name!r}, found {got!r}")
            if field_off != offset:
                raise ValueError(
                    f"field table entry {name!r}: expected offset 0x{offset:x}, "
                    f"found 0x{field_off:x}"
                )

        terminator = bytes(data[off + size : off + size + FIELD_PARSE_STRIDE])
        if terminator != bytes(FIELD_PARSE_STRIDE):
            raise ValueError(
                f"the field table is not NULL-terminated after {len(STOCK_FIELDS)} entries "
                f"(found {terminator.hex()})"
            )
        return entries

    def _read_stock_vtable(self, data: bytes | bytearray) -> tuple[int, ...]:
        """The wrapper vtable's three slots, after checking slot 1 is the `allow` this patch
        replaces. Getting that wrong would install a copy that dispatches the widened test from the
        wrong slot, which nothing downstream would catch."""
        off = va_to_offset(data, WRAPPER_VTABLE_VA)
        if off is None:
            raise ValueError(f"the wrapper vtable VA 0x{WRAPPER_VTABLE_VA:08x} is not mapped")
        slots = struct.unpack_from(f"<{WRAPPER_VTABLE_SLOTS}I", data, off)
        if slots[1] != PARTITION_ALLOW_VA:
            raise ValueError(
                f"the partition filter's vtable slot 1 is 0x{slots[1]:08x}, not the horde gate "
                f"0x{PARTITION_ALLOW_VA:08x} - this is not the expected build"
            )
        return slots

    def _copied_rows(self, data: bytes | bytearray, pieces: _Layout) -> bytes:
        off = va_to_offset(data, pieces.table_va)
        if off is None:
            raise ValueError(f"the rebuilt table at 0x{pieces.table_va:08x} is not mapped")
        return bytes(data[off : off + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE])

    def _copied_vtable(self, data: bytes | bytearray, pieces: _Layout) -> tuple[int, ...]:
        off = va_to_offset(data, pieces.vtable_va)
        if off is None:
            raise ValueError(f"the copied vtable at 0x{pieces.vtable_va:08x} is not mapped")
        slots = list(struct.unpack_from(f"<{WRAPPER_VTABLE_SLOTS}I", data, off))
        slots[1] = PARTITION_ALLOW_VA  # `_build` puts the cave's own allow here
        return tuple(slots)

    def _table_problems(self, data: bytes | bytearray, pieces: _Layout) -> list[str]:
        """What the rebuilt table has to spell: the eight stock names still at their stock offsets,
        and the new keyword after them pointing at the cave's own string."""
        problems: list[str] = []
        off = va_to_offset(data, pieces.table_va)
        if off is None:
            return [f"the rebuilt table at 0x{pieces.table_va:08x} is not mapped"]

        for index, (name, offset) in enumerate(STOCK_FIELDS):
            name_va, _parse, _ud, field_off = struct.unpack_from(
                "<4I", data, off + index * FIELD_PARSE_STRIDE
            )
            got = _read_cstring(data, name_va)
            if got != name or field_off != offset:
                problems.append(
                    f"rebuilt table entry {index}: expected {name!r} at 0x{offset:x}, "
                    f"found {got!r} at 0x{field_off:x}"
                )

        name_va, parse_fn, _ud, field_off = struct.unpack_from(
            "<4I", data, off + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE
        )
        got = _read_cstring(data, name_va)
        if got != self.keyword:
            problems.append(f"the appended keyword is {got!r}, not {self.keyword!r}")
        if parse_fn != INI_PARSE_BOOL:
            problems.append(f"the appended row parses with 0x{parse_fn:08x}, not the Bool parser")
        if field_off != FLAG_OFFSET:
            problems.append(f"the appended row lands at 0x{field_off:x}, not 0x{FLAG_OFFSET:x}")
        return problems

    def _anchor_problems(self, data: bytes | bytearray) -> list[str]:
        """Everything the patch depends on and does not rewrite.

        The register anchors are the ones that matter: both stubs read `edi` as the `ModuleData`
        and `ebx` as the owning `Object`, and a build that established them differently would send
        the cave dereferencing whatever the registers happened to hold. The rest say the structure
        is still the size the flag's padding depends on, and that the gate being replaced is still
        the horde gate."""
        problems: list[str] = []
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"anchor 0x{va:08x} is not mapped - not the expected build")
                continue
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                problems.append(f"anchor 0x{va:08x}: expected {expected.hex()}, got {got.hex()}")
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError(f"{self.name}: this is not the expected build: {'; '.join(problems)}")

    # --- the edits -----------------------------------------------------------------------------

    def _edits(
        self, data: bytes | bytearray, pieces: _Layout
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``."""
        edits: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int, old: bytes, new: bytes, note: str) -> None:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{va:08x} is not mapped")
            edits.append((off, old, new, note))

        at(
            MODULEDATA_CTOR_CALL_VA,
            _call_bytes(MODULEDATA_CTOR_CALL_VA, MODULEDATA_CTOR_VA),
            _call_bytes(MODULEDATA_CTOR_CALL_VA, pieces.ctor_va),
            f"ModuleData ctor -> the shim defaulting {self.keyword} to No",
        )
        at(
            FIELD_TABLE_REF_VA,
            _u32(FIELD_TABLE_VA),
            _u32(pieces.table_va),
            f"buildFieldParse -> the {SECTION_NAME} field table",
        )
        at(
            SETUP_WINDOW_VA,
            SETUP_WINDOW_BYTES,
            setup_hook_bytes(pieces.setup_va),
            "update's partition-filter wrapper -> the cave's vtable chooser",
        )
        at(
            COUNT_WINDOW_VA,
            COUNT_WINDOW_BYTES,
            count_hook_bytes(pieces.count_va),
            "update's count loop -> the cave's per-candidate contribution",
        )
        return edits
