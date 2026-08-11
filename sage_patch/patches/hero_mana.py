"""The hero-mana patch: give special powers a spendable, regenerating per-object cost.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below comes
from :mod:`sage_patch.addresses` and is derived in ``../docs/hero-mana.md``.

**Why the engine cannot already do this.** `SpecialPower` has a `UnitCost` field, and on a hero
it is not a weak mechanic - it is a **no-op**. All three sites that read it (the ControlBar's
availability test, the shared can-do gate, and the routine that kills the members) share one
shape: read the cost, and if it is non-zero ask ``Object+0x258`` for the horde interface. When
that interface is absent - which is every lone hero - they branch to *the same label as
"cost is zero"*. So ``UnitCost = 5`` on a hero costs nothing at all::

    00943440  cmp  dword ptr [eax+0x80], 0     ; unitCost == 0 ?
    00943447  je   0x943486                    ;   yes -> skip the check
    00943449  mov  ecx, dword ptr [ebx+0x258]  ; obj->m_contain
    00943460  je   0x943486                    ; no horde -> SKIP, same label

**What this does.** Three new `Int` fields, on the two blocks the quantities actually belong to:

=========================  ==================================================================
`SpecialPower.ManaCost`    what **one activation** costs, in whole points. **0 (the default)
                           leaves the power exactly as it is today**, so an unmodified mod is
                           unaffected.
`Object.ManaPool`          the **caster's** maximum, in whole points. 0 = the patch default.
`Object.ManaRegen`         the caster's refill, in **hundredths of a point per logic frame** -
                           30 is one point per second at 30fps. 0 = the patch default.
=========================  ==================================================================

A hero has one pool and many abilities, so the pool and the regen are per *object* and only the
cost is per *power*. Putting all three on `SpecialPower` instead would make the cap depend on
which ability happened to be evaluated, and let two of a hero's powers disagree about it.

They are enforced in three places: the affordability predicate every caller *including the AI*
goes through, the three activation entry points, and the ControlBar so the button greys out.

**Where the caster's numbers live.** `ThingTemplate` is `0x650` bytes with no safe hole - the one
apparent gap, ``+0x5E8``, is written as a word by the constructor at ``0x73FF8D``, so it is a live
non-INI member - and it is allocated 11,143 times. Rather than grow it, `ManaPool`/`ManaRegen`
parse into a **side table in the cave keyed by the `ThingTemplate*`**, through a parse function
that borrows the engine's own `Int` tokenizer for the value. An INI **override block** is a
*copy* of the template, so the table would lose the entry - and that is why the patch also rides
``ThingTemplate::copyFrom``, propagating the row from source to copy. Missing the table entirely
is a fallback to the patch defaults, never a wrong number.

**Where the pool itself lives, and why it needs no init, destroy or savegame hook.** A second
cave table of ``{id, stamp, value}`` rows indexed by ``Object+0x74 & (POOL_ROWS-1)``, and the pool
is **not ticked** - it is *computed* on read from the frame counter::

    value = min(cap, stored + (now - stamp) * regen)

Only a spend writes a row, and three consequences follow:

* **No per-frame hook.** Nothing has to walk the table every frame, and in particular nothing
  has to hook ``GameLogic::update`` - which matters, because :mod:`.live_bridge` already owns
  those five bytes and the two would collide.
* **No init hook.** A row whose ``id`` does not match reads as *full*, so a hero that has never
  cast is full by construction, at frame 0 or frame 40,000.
* **No destroy hook, and no savegame format change.** An id reused by a new object finds a row
  that still names the old one and reads full. A save reloads with the table zeroed, so every
  hero comes back full - a defined, benign state rather than "everyone drained".

**Determinism.** Every input is simulation state that is identical on every peer: the object id,
the logic frame, and the template fields. Nothing here reads a pointer *value*, a wall clock or
anything client-local - the template side table is keyed by a pointer, but only ever probed with
a pointer both peers derived the same way, and a probe is a read. The only writes at play time
happen on the logic-side activation path, which runs on all peers. The ControlBar path is a
**pure read** - it must be, since it runs only on the local client.

**Collisions.** Pool rows are indexed by ``id & (POOL_ROWS-1)``, because the id space is *not*
bounded by the object table: four engine-reserved objects carry ids near 100,000,000. Two live
objects whose ids differ by a multiple of ``POOL_ROWS`` share a row; the one that does not own it
reads *full*, so the failure mode is "a power was occasionally free", never a crash, never a
refusal, and never a desync (every peer folds the same ids the same way).

**What is not covered.** `MSG_DO_SPELLBOOK_SPECIAL_POWER` (player-scoped spellbook powers) does
not run through ``Object::doSpecialPower*`` and is deliberately out of scope. The shared can-do
gate at ``0x0082D925`` is not hooked either: everything it guards reaches
``Object::doSpecialPower*`` afterwards, so an unaffordable power is refused there instead - one
step later and with no "cannot do that" feedback, but refused.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. It shares no edited byte with any other bundled patch, and both
field-parse tables are read **live** rather than assumed, so a patch that extended either one
first still composes.

> **Every peer must run the same patched binary.** Affordability decides whether a power fires,
> so the effect is inside the simulation: a patched and an unpatched client desync the first
> time a mana-costing power is cast, and replays do not cross. Same rule as
> `production-condition`, stricter than `replay-outcome`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    ABILITY_MODULEDATA_SPECIAL_POWER,
    ABILITY_TRIGGER,
    ABILITY_TRIGGER_MODULEDATA_EBP,
    ABILITY_TRIGGER_OBJECT_EBP,
    ABILITY_TRIGGER_PAY,
    ABILITY_TRIGGER_PAY_BYTES,
    ABILITY_TRIGGER_PAY_RESUME,
    ABILITY_TRIGGER_VTABLE,
    CAN_USE_SPECIAL_POWER,
    CAN_USE_SPECIAL_POWER_ENTRY,
    COMMAND_BUTTON_SPECIAL_POWER,
    CONTROL_BAR_UNAVAILABLE,
    CONTROL_BAR_UNIT_COST_CALL,
    CONTROL_BAR_UNIT_COST_CALL_BYTES,
    DESCRIPTION_BUFFER_EBP_OFFSET,
    DESCRIPTION_DONE,
    DESCRIPTION_LINE_EBP_OFFSET,
    DESCRIPTION_OBJECT_EBP_OFFSET,
    DESCRIPTION_RANK_APPEND,
    DESCRIPTION_RANK_APPEND_BYTES,
    DESCRIPTION_RANK_RESUME,
    DESCRIPTION_SPECIAL_POWER_CASE,
    DESCRIPTION_SPECIAL_POWER_CASE_BYTES,
    DESCRIPTION_TEXT_EBP_OFFSET,
    DESCRIPTION_UNIT_COST_BODY,
    DO_SPECIAL_POWER_SITES,
    GAME_LOGIC_FRAME,
    GAME_TEXT_FORMAT_SLOT,
    GET_FINAL_OVERRIDE,
    GUI_COMMAND_SPECIAL_POWER,
    INI_PARSE_INT,
    OBJECT_FIELD_TABLE_REF_OPCODES,
    OBJECT_FIELD_TABLE_REFS,
    OBJECT_ID,
    OBJECT_THING_TEMPLATE,
    OPERATOR_NEW,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
    SPECIAL_POWER_TEMPLATE_NEW_SITES,
    SPECIAL_POWER_TEMPLATE_SIZE,
    SPECIAL_POWER_UNIT_COST,
    THE_GAME_LOGIC,
    THE_GAME_TEXT,
    THING_TEMPLATE_COPY_CALL,
    THING_TEMPLATE_COPY_CALL_BYTES,
    THING_TEMPLATE_COPY_FROM,
    UNICODE_STRING_APPEND,
    UNICODE_STRING_CONCAT,
)
from ..asm import JB, JBE, JE, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "HUNDREDTHS",
    "MANA_COST_OFF",
    "NEW_TEMPLATE_SIZE",
    "OBJECT_FIELDS",
    "POOL_ROWS",
    "POWER_FIELDS",
    "ROW_STRIDE",
    "SECTION_NAME",
    "TOOLTIP_LABELS",
    "TEMPLATE_ROWS",
    "TRACE_RING",
    "TRACE_STRIDE",
    "HeroManaPatch",
    "entries_before",
    "read_field_table",
    "resolve_table",
]

#: One `{const char *name, ParseFn, void *userData, UnsignedInt offset}` row of an INI
#: field-parse table, as `struct` unpacks it.
Entry = tuple[int, int, int, int]

SECTION_NAME = ".heromna"  # 8 chars exactly: the PE name field truncates silently past 8

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds code, two
# rebuilt field tables and two mutable row arrays, so it needs all three access bits.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: `SpecialPowerTemplate` grows by one `Int`. The stock struct is `0x88` with
#: `UnitCostDeathType` at `+0x84` as its last field, so this is pure growth - there is no padding
#: to reuse.
MANA_COST_OFF = 0x88
NEW_TEMPLATE_SIZE = 0x8C

#: `SpecialPower` entries appended to that table, as `(name, template offset)`.
POWER_FIELDS: tuple[tuple[str, int], ...] = (("ManaCost", MANA_COST_OFF),)

#: `Object` entries appended to the `ThingTemplate` table, as `(name, userData)`. They share one
#: parse function and are told apart by `userData`, because neither writes into the template at
#: all - both land in the cave's own side table. Their table `offset` is therefore 0.
OBJECT_FIELDS: tuple[tuple[str, int], ...] = (("ManaPool", 0), ("ManaRegen", 1))

#: Internal fixed point. Pools and costs are declared in whole points and stored in hundredths,
#: so `ManaRegen` can be a plain per-frame integer and the whole computation stays in exact
#: integer arithmetic - no division anywhere, and therefore no rounding to disagree about.
HUNDREDTHS = 100

#: A ceiling every INI-supplied number is clamped to before it is multiplied, which is what makes
#: the arithmetic provably overflow-free: elapsed, regen and pool are each <= 0xFFFF, so
#: `elapsed * regen` < 2^32 and `pool * 100` < 2^23.
_CLAMP = 0xFFFF

#: Rows in each table. Powers of two so both index folds are an `and`.
POOL_ROWS = 8192  # { UnsignedInt id;       UnsignedInt stamp; UnsignedInt value_hundredths; }
TEMPLATE_ROWS = 1024  # { ThingTemplate *tmpl; UnsignedInt pool;  UnsignedInt regen; }
ROW_STRIDE = 12
_POOL_MASK = POOL_ROWS - 1
_TEMPLATE_MASK = TEMPLATE_ROWS - 1

_CFG_POOL_OFF = 0x00
_CFG_REGEN_OFF = 0x04
_SCRATCH_OFF = 0x08  # where the borrowed Int parser is told to put the value
_POOL_OFF = 0x10
_TEMPLATE_OFF = _POOL_OFF + POOL_ROWS * ROW_STRIDE

#: A diagnostic ring buffer, always allocated so the section layout does not depend on whether
#: tracing is on - only the emitted *calls* differ. `tools/hero_mana_trace.py` reads it out of a
#: running game. Entries are `{frame, tag, a, b, c}`; `TRACE_INDEX` is a free-running write
#: counter, so the reader can tell a wrapped ring from a partly-filled one.
TRACE_RING = 512
TRACE_STRIDE = 20
_TRACE_OFF = _TEMPLATE_OFF + TEMPLATE_ROWS * ROW_STRIDE
_TRACE_INDEX_OFF = _TRACE_OFF
_TRACE_ENTRIES_OFF = _TRACE_OFF + 4
_TABLES_OFF = _TRACE_ENTRIES_OFF + TRACE_RING * TRACE_STRIDE

#: What each traced record means. The dispatch tags are the ones that answer "did this power even
#: reach the charge, and how many times per cast".
TRACE_DISPATCH = 0x10  # +variant: an Object::doSpecialPower* dispatch was reached
TRACE_SPEND_ENTER = 0x20  # a = final template, b = its ManaCost, c = the Object
TRACE_SPEND_CHARGED = 0x21  # a = cost (hundredths), b = value before, c = value after
TRACE_SPEND_REFUSED = 0x22  # a = cost (hundredths), b = value
TRACE_ABILITY_FIRE = 0x30  # an ability update actually fired: a = template, b = the Object

#: Names each table must carry at these offsets, or this is not the build these addresses were
#: derived against. Checked by name rather than by count, so the check survives another patch
#: having extended a table first.
_POWER_FINGERPRINT = {"UnitCost": SPECIAL_POWER_UNIT_COST, "UnitCostDeathType": 0x84}
_OBJECT_FINGERPRINT = {"BuildCost": 0x5EA, "RefundValue": 0x5EC, "CampnessValue": 0x5E4}

#: The localization keys the two description lines are built from - the same shape as the
#: engine's own `TOOLTIP:UnitCost`. `ManaCost` goes on an ability button, `ManaPool` under a
#: hero's level on its revive/recruit button. A mod has to add both keys to its `.str`/`.csf`
#: string table for the lines to read as anything; that is exactly how `UnitCost` behaves too,
#: and an absent key costs nothing but an unhelpful line.
TOOLTIP_LABELS: tuple[str, ...] = ("TOOLTIP:ManaCost", "TOOLTIP:ManaPool")

_DEFAULT_POOL = 100  # points
_DEFAULT_REGEN = 30  # hundredths per frame == one point per second at 30fps


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`). The forms that take a 32-bit displacement are the error-prone ones - `0x88` does not
# fit the signed imm8 a disassembler would print - so they get helpers rather than being spelled
# out at each use.

_ESI, _EBX, _EBP = 6, 3, 5


def _mov_eax_field(base_reg: int, disp: int) -> bytes:
    """``mov eax, [<base>+disp32]`` - base 6 = esi, 3 = ebx, 5 = ebp."""
    return bytes([0x8B, 0x80 | base_reg]) + _u32(disp)


def _mov_field_eax(base_reg: int, disp: int) -> bytes:
    """``mov [<base>+disp32], eax``."""
    return bytes([0x89, 0x80 | base_reg]) + _u32(disp)


def _mov_edx_field(base_reg: int, disp: int) -> bytes:
    """``mov edx, [<base>+disp32]`` - base 0 = eax."""
    return bytes([0x8B, 0x90 | base_reg]) + _u32(disp)


def _push_field(base_reg: int, disp: int) -> bytes:
    """``push dword ptr [<base>+disp32]``."""
    return bytes([0xFF, 0xB0 | base_reg]) + _u32(disp)


def _zero_field(disp: int) -> bytes:
    """``and dword ptr [eax+disp32], 0`` - shorter than a `mov` of an immediate zero."""
    return bytes([0x83, 0xA0]) + _u32(disp) + b"\x00"


def _emit_probe(a: Asm, tag: str, rows_va: int, *, claim: bool) -> None:
    """An open-addressed probe of the template side table, keyed by ``ecx``.

    Hash the pointer, walk forward over occupied slots, stop at the key or at an empty one.
    Entries are never removed, so a run of occupied slots is never broken and the walk is exact.
    Returns the row in `eax`, or 0 when the key is absent (lookup) or the table is full (insert)
    - a full table degrades a hero to the patch defaults rather than failing the load.

    Clobbers `eax`, `edx` and `edi` (saved); leaves `ecx` alone so the caller keeps its key.
    """
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.emit(0xC1, 0xE8, 0x04)  # shr eax, 4     ; templates are 0x650 apart; drop the dead bits
    a.emit(0x25, _u32(_TEMPLATE_MASK))  # and eax, mask
    a.emit(0xBF, _u32(TEMPLATE_ROWS))  # mov edi, TEMPLATE_ROWS   ; probe budget
    a.label(f"{tag}_probe")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(0x6B, 0xD2, ROW_STRIDE)  # imul edx, edx, 12
    a.emit(0x81, 0xC2, _u32(rows_va))  # add edx, rows
    a.emit(0x83, 0x3A, 0x00)  # cmp dword ptr [edx], 0
    a.jcc(JE, f"{tag}_empty")
    a.emit(0x39, 0x0A)  # cmp dword ptr [edx], ecx
    a.jcc(JE, f"{tag}_hit")
    a.emit(0x40)  # inc eax
    a.emit(0x25, _u32(_TEMPLATE_MASK))  # and eax, mask
    a.emit(0x4F)  # dec edi
    a.jcc(JNE, f"{tag}_probe")
    a.emit(0x31, 0xC0)  # xor eax, eax   ; budget exhausted - the table is full
    a.jmp(f"{tag}_out")
    a.label(f"{tag}_empty")
    if claim:
        a.emit(0x89, 0x0A)  # mov [edx], ecx     ; claim the slot for this template
    else:
        a.emit(0x31, 0xC0)  # xor eax, eax       ; absent
        a.jmp(f"{tag}_out")
    a.label(f"{tag}_hit")
    a.emit(0x8B, 0xC2)  # mov eax, edx
    a.label(f"{tag}_out")
    a.emit(0x5F)  # pop edi
    a.emit(0xC3)  # ret


def _emit_trace(a: Asm, index_va: int, entries_va: int) -> None:
    """``trace(tag, a, b, c)`` - append one record to the diagnostic ring. cdecl.

    Saves and restores everything, flags included, so a call can be dropped anywhere without
    thinking about what is live. Always emitted; only the *calls* are conditional, which keeps the
    traced and untraced builds identical apart from those call sites.
    """
    a.label("trace")
    a.emit(0x60)  # pushad
    a.emit(0x9C)  # pushfd
    a.emit(0xA1, _u32(index_va))  # mov eax, [index]
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(0x81, 0xE2, _u32(TRACE_RING - 1))  # and edx, RING-1
    a.emit(0x6B, 0xD2, TRACE_STRIDE)  # imul edx, edx, 20
    a.emit(0x81, 0xC2, _u32(entries_va))  # add edx, entries
    a.emit(0x40)  # inc eax
    a.emit(0xA3, _u32(index_va))  # mov [index], eax
    # the logic frame, so a record can be placed in time against the others
    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "t_noframe")
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.jcc(JNE, "t_frame")  # (ZF is clear here - eax was non-null)
    a.label("t_noframe")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("t_frame")
    a.emit(0x89, 0x02)  # mov [edx], eax
    for slot, arg in enumerate((0x28, 0x2C, 0x30, 0x34)):
        a.emit(0x8B, 0x44, 0x24, arg)  # mov eax, [esp+<arg>]   ; pushad(32) + pushfd(4) + ret(4)
        a.emit(0x89, 0x42, 4 + slot * 4)  # mov [edx+n], eax
    a.emit(0x9D)  # popfd
    a.emit(0x61)  # popad
    a.emit(0xC3)  # ret


def _emit_trace_call(a: Asm, tag: int, push_c: bytes, push_b: bytes, push_a: bytes) -> None:
    """``trace(tag, a, b, c)`` at a call site - arguments pushed last-first, then cleaned."""
    a.emit(push_c)
    a.emit(push_b)
    a.emit(push_a)
    a.emit(0x68, _u32(tag))
    a.call("trace")
    a.emit(0x83, 0xC4, 0x10)  # add esp, 16


def _emit_lookup(a: Asm, rows_va: int) -> None:
    """``tlookup``: `ecx` = a `ThingTemplate*`, `eax` = its row or 0. Pure - the read path calls
    it from the ControlBar, on the local client only."""
    a.label("tlookup")
    _emit_probe(a, "tl", rows_va, claim=False)


def _emit_insert(a: Asm, rows_va: int) -> None:
    """``tinsert``: as ``tlookup``, but claims an empty slot. Only ever runs at INI load."""
    a.label("tinsert")
    _emit_probe(a, "ti", rows_va, claim=True)


def _emit_parse(a: Asm, scratch_va: int) -> None:
    """The parse function behind `Object.ManaPool` and `Object.ManaRegen`.

    cdecl `(INI*, void *instance, void *store, const void *userData)`, the shape the field-parse
    dispatcher calls. It **borrows the engine's own `Int` parser** for the token - pointing it at
    a scratch dword instead of at the template - and then files the value in the side table
    against the `ThingTemplate` being parsed. `userData` says which of the two fields it is.

    `store` is ignored, and the table entries carry offset 0 so it is only ever `instance`. That
    keeps the pair out of the template entirely, which is the whole point.
    """
    a.label("tparse")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0xFF, 0x75, 0x14)  # push dword ptr [ebp+0x14]   ; userData
    a.emit(0x68, _u32(scratch_va))  # push scratch                ; store
    a.emit(0xFF, 0x75, 0x0C)  # push dword ptr [ebp+0xc]    ; instance
    a.emit(0xFF, 0x75, 0x08)  # push dword ptr [ebp+8]      ; ini
    a.call_absolute(INI_PARSE_INT)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 16                 ; cdecl - we clean
    a.emit(0x8B, 0x4D, 0x0C)  # mov ecx, [ebp+0xc]          ; the ThingTemplate
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "p_out")
    a.call("tinsert")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "p_out")  # table full -> this hero keeps the defaults
    a.emit(0x8B, 0x15, _u32(scratch_va))  # mov edx, [scratch]
    a.emit(0x83, 0x7D, 0x14, 0x00)  # cmp dword ptr [ebp+0x14], 0
    a.jcc(JNE, "p_regen")
    a.emit(0x89, 0x50, 0x04)  # mov [eax+4], edx            ; ManaPool
    a.jmp("p_out")
    a.label("p_regen")
    a.emit(0x89, 0x50, 0x08)  # mov [eax+8], edx            ; ManaRegen
    a.label("p_out")
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret


def _emit_propagate(a: Asm) -> None:
    """``ThingTemplate::copyFrom``, plus the side-table row.

    An INI override block is a *copy* of the template it overrides, made here and nowhere else.
    Without this a `map.ini` that re-declares a hero would silently drop its pool. `__thiscall`
    with one stack argument and `ret 4`, exactly like the routine it wraps.
    """
    a.label("tprop")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]      ; the source template
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xD9)  # mov ebx, ecx          ; the destination
    a.emit(0x8B, 0xF0)  # mov esi, eax          ; the source
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(THING_TEMPLATE_COPY_FROM)  # cleans its own argument
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call("tlookup")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pr_out")  # the source declared nothing to carry over
    a.emit(0x8B, 0xF0)  # mov esi, eax          ; the source row
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call("tinsert")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pr_out")
    a.emit(0x8B, 0x4E, 0x04)  # mov ecx, [esi+4]
    a.emit(0x89, 0x48, 0x04)  # mov [eax+4], ecx
    a.emit(0x8B, 0x4E, 0x08)  # mov ecx, [esi+8]
    a.emit(0x89, 0x48, 0x08)  # mov [eax+8], ecx
    a.label("pr_out")
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_value(a: Asm, cfg_pool: int, cfg_regen: int, pool_rows: int) -> None:
    """``value``: the current pool of `ebx` (an `Object*`), in hundredths, in `eax`.

    The cap and the regen come from the object's **own** `ThingTemplate`, so every ability a hero
    has draws on one pool. **Pure** - it never writes a row, because the ControlBar calls it on
    the local client only and a write there would desync. Clobbers `eax`, `ecx`, `edx`; preserves
    `ebx` and `esi` for its callers.
    """
    a.label("value")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x83, 0xEC, 0x0C)  # sub esp, 12   ; [-4] cap_h, [-8] row, [-12] regen

    # The caster's pool and regen, from its template's side-table row.
    a.emit(0x8B, 0x4B, OBJECT_THING_TEMPLATE)  # mov ecx, [ebx+4]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "v_defaults")
    a.call("tlookup")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "v_defaults")
    a.emit(0x8B, 0x48, 0x04)  # mov ecx, [eax+4]     ; ManaPool
    a.emit(0x8B, 0x50, 0x08)  # mov edx, [eax+8]     ; ManaRegen
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JNE, "v_have_pool")
    a.emit(0x8B, 0x0D, _u32(cfg_pool))  # mov ecx, [cfg_pool]
    a.label("v_have_pool")
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JNE, "v_clamp")
    a.emit(0x8B, 0x15, _u32(cfg_regen))  # mov edx, [cfg_regen]
    a.jmp("v_clamp")

    a.label("v_defaults")
    a.emit(0x8B, 0x0D, _u32(cfg_pool))  # mov ecx, [cfg_pool]
    a.emit(0x8B, 0x15, _u32(cfg_regen))  # mov edx, [cfg_regen]

    a.label("v_clamp")
    a.emit(0x81, 0xF9, _u32(_CLAMP))  # cmp ecx, 0xFFFF
    a.jcc(JBE, "v_pool_ok")
    a.emit(0xB9, _u32(_CLAMP))  # mov ecx, 0xFFFF
    a.label("v_pool_ok")
    a.emit(0x81, 0xFA, _u32(_CLAMP))  # cmp edx, 0xFFFF
    a.jcc(JBE, "v_regen_ok")
    a.emit(0xBA, _u32(_CLAMP))  # mov edx, 0xFFFF
    a.label("v_regen_ok")
    a.emit(0x89, 0x55, 0xF4)  # mov [ebp-12], edx
    a.emit(0x6B, 0xC9, HUNDREDTHS)  # imul ecx, ecx, 100
    a.emit(0x89, 0x4D, 0xFC)  # mov [ebp-4], ecx      ; cap_h

    # The row. One that does not name this object reads as full, which is what makes a hero that
    # has never cast - and a reloaded save - start full with no init hook anywhere.
    a.emit(0x8B, 0x53, OBJECT_ID)  # mov edx, [ebx+0x74]   ; the object id
    a.emit(0x8B, 0xCA)  # mov ecx, edx
    a.emit(0x81, 0xE1, _u32(_POOL_MASK))  # and ecx, POOL_MASK
    a.emit(0x6B, 0xC9, ROW_STRIDE)  # imul ecx, ecx, 12
    a.emit(0x81, 0xC1, _u32(pool_rows))  # add ecx, pool_rows
    a.emit(0x89, 0x4D, 0xF8)  # mov [ebp-8], ecx
    a.emit(0x39, 0x11)  # cmp [ecx], edx
    a.jcc(JNE, "v_full")

    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "v_full")
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.emit(0x2B, 0x41, 0x04)  # sub eax, [ecx+4]      ; elapsed
    a.jcc(JLE, "v_stored")
    a.emit(0x3D, _u32(_CLAMP))  # cmp eax, 0xFFFF
    a.jcc(JBE, "v_elapsed")
    a.emit(0xB8, _u32(_CLAMP))  # mov eax, 0xFFFF
    a.label("v_elapsed")

    # gain = elapsed * regen, clamped to the cap *before* the add so the sum cannot wrap
    a.emit(0x0F, 0xAF, 0x45, 0xF4)  # imul eax, dword ptr [ebp-12]
    a.emit(0x3B, 0x45, 0xFC)  # cmp eax, [ebp-4]
    a.jcc(JB, "v_gain_ok")
    a.emit(0x8B, 0x45, 0xFC)  # mov eax, [ebp-4]
    a.label("v_gain_ok")
    a.emit(0x8B, 0x4D, 0xF8)  # mov ecx, [ebp-8]
    a.emit(0x03, 0x41, 0x08)  # add eax, [ecx+8]
    a.jmp("v_clamp_out")

    a.label("v_stored")  # no time has passed: the stored value, still clamped
    a.emit(0x8B, 0x4D, 0xF8)  # mov ecx, [ebp-8]
    a.emit(0x8B, 0x41, 0x08)  # mov eax, [ecx+8]

    a.label("v_clamp_out")
    a.emit(0x3B, 0x45, 0xFC)  # cmp eax, [ebp-4]
    a.jcc(JBE, "v_out")
    a.label("v_full")  # falls through: eax = cap_h
    a.emit(0x8B, 0x45, 0xFC)  # mov eax, [ebp-4]
    a.label("v_out")
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_cost_prologue(a: Asm, prefix: str) -> None:
    """Shared tail of `check`/`spend`: `esi` is a final-override power template, and this leaves
    `eax` = the cost in hundredths and `ebx` = the object, or jumps to ``<prefix>_allow`` when
    the power is not mana-gated at all."""
    a.emit(_mov_eax_field(_ESI, MANA_COST_OFF))
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, f"{prefix}_allow")  # ManaCost 0 -> stock behaviour, untouched
    a.emit(0x3D, _u32(_CLAMP))  # cmp eax, 0xFFFF
    a.jcc(JBE, f"{prefix}_cost")
    a.emit(0xB8, _u32(_CLAMP))  # mov eax, 0xFFFF
    a.label(f"{prefix}_cost")
    a.emit(0x6B, 0xC0, HUNDREDTHS)  # imul eax, eax, 100
    a.emit(0x8B, 0x5D, 0x08)  # mov ebx, [ebp+8]        ; the Object
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, f"{prefix}_allow")


def _emit_check(a: Asm) -> None:
    """``check(Object*, SpecialPowerTemplate* final)`` -> `eax` 0 allow / 1 refuse. cdecl.

    Read-only. This is what the affordability predicate and the ControlBar both call.
    """
    a.label("check")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x75, 0x0C)  # mov esi, [ebp+0xc]      ; template (already final)
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "c_allow")
    _emit_cost_prologue(a, "c")
    a.emit(0x50)  # push eax                ; cost_h
    a.call("value")
    a.emit(0x59)  # pop ecx                 ; cost_h
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JB, "c_refuse")
    a.label("c_allow")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.jmp("c_out")
    a.label("c_refuse")
    a.emit(0xB8, _u32(1))  # mov eax, 1
    a.label("c_out")
    a.emit(0x5E, 0x5B, 0x5D)  # pop esi / pop ebx / pop ebp
    a.emit(0xC3)  # ret


def _emit_spend(a: Asm, pool_rows: int, *, trace: bool) -> None:
    """``spend(Object*, SpecialPowerTemplate* raw)`` -> `eax` 0 allowed (and charged) / 1 refuse.

    cdecl. Logic-side only: this is the one routine that writes a pool row at play time. It
    resolves the override itself, because its callers hand it the template straight out of their
    own frame.
    """
    a.label("spend")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x4D, 0x0C)  # mov ecx, [ebp+0xc]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "s_allow")
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "s_allow")
    if trace:
        # Before any cost test, so a power that reaches here with ManaCost 0 is still recorded -
        # which is the difference between "never dispatched" and "dispatched but free".
        _emit_trace_call(
            a,
            TRACE_SPEND_ENTER,
            bytes([0xFF, 0x75, 0x08]),  # c = the Object
            _push_field(_ESI, MANA_COST_OFF),  # b = its ManaCost
            bytes([0x56]),  # a = the final template
        )
    _emit_cost_prologue(a, "s")
    a.emit(0x50)  # push eax                ; cost_h
    a.call("value")
    a.emit(0x59)  # pop ecx                 ; cost_h
    if trace:
        _emit_trace_call(
            a,
            TRACE_SPEND_CHARGED,
            bytes([0x6A, 0x00]),  # c = 0
            bytes([0x50]),  # b = what the caster has
            bytes([0x51]),  # a = what it costs
        )
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JB, "s_refuse")
    a.emit(0x2B, 0xC1)  # sub eax, ecx            ; the new value

    # Take the row for this object and stamp it with the current frame.
    a.emit(0x8B, 0x53, OBJECT_ID)  # mov edx, [ebx+0x74]
    a.emit(0x8B, 0xCA)  # mov ecx, edx
    a.emit(0x81, 0xE1, _u32(_POOL_MASK))  # and ecx, POOL_MASK
    a.emit(0x6B, 0xC9, ROW_STRIDE)  # imul ecx, ecx, 12
    a.emit(0x81, 0xC1, _u32(pool_rows))  # add ecx, pool_rows
    a.emit(0x89, 0x11)  # mov [ecx], edx          ; id
    a.emit(0x89, 0x41, 0x08)  # mov [ecx+8], eax        ; value
    a.emit(0x8B, 0x15, _u32(THE_GAME_LOGIC))  # mov edx, [TheGameLogic]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "s_allow")
    a.emit(0x8B, 0x52, GAME_LOGIC_FRAME)  # mov edx, [edx+0x40]
    a.emit(0x89, 0x51, 0x04)  # mov [ecx+4], edx        ; stamp

    a.label("s_allow")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.jmp("s_out")
    a.label("s_refuse")
    a.emit(0xB8, _u32(1))  # mov eax, 1
    a.label("s_out")
    a.emit(0x5E, 0x5B, 0x5D)  # pop esi / pop ebx / pop ebp
    a.emit(0xC3)  # ret


def _emit_new(a: Asm) -> None:
    """``new(size)``: `operator new`, then zero the new field.

    The engine's `SpecialPowerTemplate` constructor has no room for another store and no
    five-byte site that is safe to take, so the grown tail is zeroed where the memory is handed
    out instead. Only the three template allocations are retargeted here, so the extra store can
    never land on another class.
    """
    a.label("new")
    a.emit(0xFF, 0x74, 0x24, 0x04)  # push dword ptr [esp+4]
    a.call_absolute(OPERATOR_NEW)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "n_out")
    a.emit(_zero_field(MANA_COST_OFF))
    a.label("n_out")
    a.emit(0xC3)  # ret


def _emit_copy_tail(a: Asm) -> None:
    """The `SpecialPowerTemplate` copy constructor's epilogue, with the new field copied first.

    Same reasoning as ``tprop`` one level down: an INI override block is a copy, and this
    constructor moves fields one at a time. `ebp` is the source pointer here, not a frame
    pointer.
    """
    a.label("copy")
    a.emit(_mov_eax_field(_EBP, MANA_COST_OFF))  # mov eax, [ebp+0x88]   (source)
    a.emit(_mov_field_eax(_EBX, MANA_COST_OFF))  # mov [ebx+0x88], eax   (destination)
    a.emit(SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES)  # the displaced epilogue


def _emit_can_use(a: Asm) -> None:
    """The gate, hooked onto `SpecialPowerStore::canUseSpecialPower`'s five-byte entry.

    Refusing here reaches the player's UI, the AI's two callers and every activation path at
    once, which is the whole reason this patch is small. `ecx` is `this` and has to survive.
    """
    a.label("canuse")
    a.emit(0x51)  # push ecx                     ; this
    a.emit(0x8B, 0x4C, 0x24, 0x0C)  # mov ecx, [esp+0xc]           ; the template argument
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "u_pass")
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "u_pass")
    a.emit(0x50)  # push eax                     ; arg1 = template
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword ptr [esp+0xc]     ; arg0 = the Object
    a.call("check")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "u_refuse")
    a.label("u_pass")
    a.emit(0x59)  # pop ecx
    a.emit(CAN_USE_SPECIAL_POWER_ENTRY)  # the displaced instruction
    a.jmp_absolute(CAN_USE_SPECIAL_POWER + len(CAN_USE_SPECIAL_POWER_ENTRY))
    a.label("u_refuse")
    a.emit(0x59)  # pop ecx
    a.emit(0x31, 0xC0)  # xor eax, eax                 ; the bool is returned in al
    a.emit(0xC2, 0x08, 0x00)  # ret 8


def _emit_control_bar(a: Asm) -> None:
    """The ControlBar's button-availability test.

    Installed over the `getFinalOverride` call that already precedes the engine's own `UnitCost`
    comparison, so it must return what that call returns. On a refusal it drops its own return
    address and jumps to the tail the `unitCost > members` branch already uses - the same
    function, the same stack depth. `ebx` is the `Object` throughout.
    """
    a.label("cbar")
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "b_out")
    a.emit(0x50)  # push eax        ; keep the override to return
    a.emit(0x50)  # push eax        ; arg1 = template
    a.emit(0x53)  # push ebx        ; arg0 = the Object
    a.call("check")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.emit(0x58)  # pop eax         ; (does not disturb the flags)
    a.jcc(JNE, "b_deny")
    a.label("b_out")
    a.emit(0xC3)  # ret
    a.label("b_deny")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4      ; discard our own return address
    a.jmp_absolute(CONTROL_BAR_UNAVAILABLE)


def _emit_ability_trigger(a: Asm, *, trace: bool) -> None:
    """The charge, at the instant a `...SpecialAbilityUpdate` ability actually fires.

    **This is where a hero ability's cost really belongs**, and the click is not. A BFME ability is
    a `SpecialPowerModule` "starter" plus an update that takes the timing; with
    ``UpdateModuleStartsAttack = Yes`` the starter never performs the power, so
    `Object::doSpecialPower*` is not even reached. Measured live: casting Gandalf's Word of Power
    produced **zero** records at those three sites, which is why it was never charged - and why a
    ranged cast charged at the click, before the hero had walked anywhere.

    The hook sits where the engine pays `UnitCost`, one instruction after an unpack countdown hits
    zero. `ebp` is the update's interface `this` (the tick does ``mov ebp, ecx``), so the module
    data is at ``ebp-0x0c`` and the owning `Object` at ``ebp-0x08``.

    A refusal here cannot stop the ability - the engine is already mid-trigger - so it simply does
    not charge. The click-time gate in `canUseSpecialPower` is what prevents an unaffordable cast
    from starting; the only way to reach here short is to drain the pool during the approach, which
    only the same hero can do.
    """
    a.label("atrig")
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0x8B, 0x45, ABILITY_TRIGGER_MODULEDATA_EBP & 0xFF)  # mov eax, [ebp-0xc]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "atrig_done")
    a.emit(0x8B, 0x40, ABILITY_MODULEDATA_SPECIAL_POWER)  # mov eax, [eax+0x38]  ; the power
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "atrig_done")
    if trace:
        _emit_trace_call(
            a,
            TRACE_ABILITY_FIRE,
            bytes([0x6A, 0x00]),  # c = 0
            bytes([0xFF, 0x75, ABILITY_TRIGGER_OBJECT_EBP & 0xFF]),  # b = the Object
            bytes([0x50]),  # a = the template
        )
    a.emit(0x50)  # push eax                                  ; arg1 = the template
    a.emit(0xFF, 0x75, ABILITY_TRIGGER_OBJECT_EBP & 0xFF)  # push [ebp-8]  ; arg0 = the Object
    a.call("spend")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.label("atrig_done")
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.emit(ABILITY_TRIGGER_PAY_BYTES)  # the displaced pair
    a.jmp_absolute(ABILITY_TRIGGER_PAY_RESUME)


def _emit_description(a: Asm, label_va: int) -> None:
    """A `ManaCost` line in a command button's description, exactly where `UnitCost` puts one -
    carrying **the price and what the caster currently has**.

    Installed over the five-byte `cmp ecx, 0x18` / `jne <done>` that guards the builder's
    special-power case, so this runs first and the stock `UnitCost` line still follows. The
    appending is the engine's own twelve-site idiom, reconstructed rather than jumped into - the
    stock block ends by branching to the case's exit, and a second line has to come back here.

    **The two-number form is what the idiom already supports**, not an invention. The engine's
    `fetch(label, exists)` is `__thiscall` and cleans both, so the varargs the formatter reads are
    whatever was pushed *below* the `exists` argument, lowest address first; the trailing
    `add esp` then drops those varargs plus the two arguments to the concat. Two sites pin the
    rule: the one-vararg `TOOLTIP:UnitCost` cleans `0xc`, and the two-dword-vararg
    `CONTROLBAR:UnderConstructionDesc` at `0x677e6b` cleans `0x10`. So pushing `current` then
    `cost` makes the cost `%d` #1 and the current `%d` #2, and the cleanup grows by one dword.

    `edi` is zero throughout this case - the `exists` out-parameter, which must stay null; it is
    **not** a spare value slot.

    The caster is the builder's own `ebp-0x1c`, the `Object` it resolved in its prologue. A null
    one (no unit being described) prints zero rather than skipping the line, so the cost is still
    shown.
    """
    a.label("desc")
    a.emit(0x83, 0xF9, GUI_COMMAND_SPECIAL_POWER)  # cmp ecx, 0x18   (the displaced test)
    a.jcc(JNE, "e_done")
    a.emit(0x8B, 0x50, COMMAND_BUTTON_SPECIAL_POWER)  # mov edx, [eax+0x44]  ; the power
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "e_stock")
    a.emit(0x50)  # push eax        ; the button - the stock case still needs it
    a.emit(0x8B, 0xCA)  # mov ecx, edx
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(_mov_edx_field(0, MANA_COST_OFF))  # mov edx, [eax+0x88]  ; ManaCost
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "e_pop")  # no cost -> no line

    # What the caster has right now, in whole points. `value` wants the Object in ebx and hands
    # back hundredths; ebx is a saved register the builder still needs, so it is put back.
    a.emit(0x53)  # push ebx
    a.emit(0x52)  # push edx                    ; keep the cost across the call
    a.emit(0x8B, 0x5D, DESCRIPTION_OBJECT_EBP_OFFSET & 0xFF)  # mov ebx, [ebp-0x1c]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "e_nocaster")
    a.call("value")
    a.emit(0x31, 0xD2)  # xor edx, edx
    a.emit(0xB9, _u32(HUNDREDTHS))  # mov ecx, 100
    a.emit(0xF7, 0xF1)  # div ecx                     ; hundredths -> whole points
    a.jmp("e_havecaster")
    a.label("e_nocaster")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("e_havecaster")
    a.emit(0x5A)  # pop edx                     ; the cost
    a.emit(0x5B)  # pop ebx

    a.emit(0x50)  # push eax                    ; vararg 2 - what the caster has
    a.emit(0x52)  # push edx                    ; vararg 1 - what it costs
    a.emit(0x57)  # push edi                    ; exists = NULL
    a.emit(0x68, _u32(label_va))  # push "TOOLTIP:ManaCost"
    a.emit(0x8B, 0x0D, _u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, GAME_TEXT_FORMAT_SLOT)  # call [eax+0x44]   ; fetch(label, exists)
    a.emit(0x50)  # push eax
    a.emit(0x8D, 0x45, DESCRIPTION_BUFFER_EBP_OFFSET & 0xFF)  # lea eax, [ebp-0x28]
    a.emit(0x50)  # push eax
    a.call_absolute(UNICODE_STRING_CONCAT)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 16      ; two varargs + the concat's two arguments

    a.label("e_pop")
    a.emit(0x58)  # pop eax
    a.label("e_stock")
    a.jmp_absolute(DESCRIPTION_UNIT_COST_BODY)  # on into the stock UnitCost line
    a.label("e_done")
    a.jmp_absolute(DESCRIPTION_DONE)


def _emit_revive_line(a: Asm, label_va: int) -> None:
    """A `ManaPool` line on a hero's revive / recruit description, right under its level.

    The engine's own rank line is built into the buffer at ``ebp-0x2c`` and then folded into the
    description at ``ebp-0x18``; this hooks that fold, adds a second line to the same buffer
    first, and then performs the fold. So the pool reads as one more descriptive property of the
    hero, in the place the level already occupies.

    `esi` is the hero's `ThingTemplate` in this branch (the case resolves it through
    `TheThingFactory::findTemplate`), which is exactly the key the side table wants. **No line is
    emitted unless the template actually declares a `ManaPool`** - an unmodified mod sees no
    change, the same rule `ManaCost = 0` follows.

    There is deliberately no "current" half here: a revive button describes a hero that does not
    exist yet, so it has no pool to be current in.
    """
    a.label("rline")
    a.emit(0x8B, 0xCE)  # mov ecx, esi          ; the hero's ThingTemplate
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "r_stock")
    a.call("tlookup")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "r_stock")  # nothing declared -> no line
    a.emit(0x8B, 0x50, 0x04)  # mov edx, [eax+4]      ; ManaPool
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "r_stock")

    a.emit(0x52)  # push edx                    ; the value
    a.emit(0x57)  # push edi                    ; zero
    a.emit(0x68, _u32(label_va))  # push "TOOLTIP:ManaPool"
    a.emit(0x8B, 0x0D, _u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, GAME_TEXT_FORMAT_SLOT)  # call [eax+0x44]
    a.emit(0x50)  # push eax
    a.emit(0x8D, 0x45, DESCRIPTION_LINE_EBP_OFFSET & 0xFF)  # lea eax, [ebp-0x2c]
    a.emit(0x50)  # push eax
    a.call_absolute(UNICODE_STRING_CONCAT)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 12

    a.label("r_stock")
    # The displaced fold: hand the accumulated line(s) to the description.
    a.emit(0x8D, 0x4D, DESCRIPTION_TEXT_EBP_OFFSET & 0xFF)  # lea ecx, [ebp-0x18]
    a.call_absolute(UNICODE_STRING_APPEND)
    a.jmp_absolute(DESCRIPTION_RANK_RESUME)


def _emit_dispatch_hook(a: Asm, index: int, window: bytes, resume_va: int, *, trace: bool) -> None:
    """An observation point on one `Object::doSpecialPower*` variant's dispatch. **Not a charge.**

    Charging here is wrong twice over. A cast that a `...SpecialAbilityUpdate` handles runs
    *both* this and the trigger that :func:`_emit_ability_trigger` hooks, so the price is taken
    twice. Measured live on `SpecialAbilityLightningSword`:

    .. code-block:: none

        frame 1696  DISPATCH v1   cost=50 available=145    -> CHARGED   (the click)
        frame 1713  ABILITY-FIRE  cost=50 available=96.02  -> CHARGED   (the fire)

    And it would charge at the click, before the hero has walked or finished its wind-up, so a
    cancelled order would still cost the player.

    The charge therefore lives at the trigger alone. The cost of that choice is that a power which
    dispatches without ever reaching an ability update - an instant one with no update module -
    is not charged at all. That is deliberate: under-charging is visible and safe, double-charging
    is silent and wrong, and a `--trace` build shows exactly which powers fall in that class (a
    `DISPATCH` with no matching `ABILITY-FIRE`).
    """
    tag = f"d{index}"
    a.label(tag)
    if trace:
        _emit_trace_call(
            a,
            TRACE_DISPATCH + index,
            bytes([0x6A, 0x00]),  # c = 0
            bytes([0x57]),  # b = the Object
            bytes([0xFF, 0x75, 0x08]),  # a = the raw template
        )
    a.emit(window)  # the displaced dispatch
    a.jmp_absolute(resume_va)


def read_field_table(data: bytes | bytearray, base_va: int) -> tuple[Entry, ...]:
    """The live field-parse table at ``base_va``, terminator excluded.

    Read from the image rather than assumed, so that a patch which extended the table first still
    composes - the rule :mod:`.name_tables` states for the name tables.
    """
    off = va_to_offset(data, base_va)
    if off is None:
        raise ValueError(f"the field table at 0x{base_va:08x} is not mapped")
    entries: list[Entry] = []
    for index in range(1024):
        entry: Entry = struct.unpack_from("<IIII", data, off + index * 16)
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
        name_va = entry[0]
        off = va_to_offset(data, name_va)
        if off is None:
            continue
        end = bytes(data[off : off + 64]).find(b"\x00")
        if end >= 0 and bytes(data[off : off + end]).decode("latin1") == name:
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


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    return None if end < 0 else bytes(data[off : off + end]).decode("latin1")


def _table_bytes(
    table_va: int, entries: tuple[Entry, ...], new_rows: tuple[tuple[str, int, int, int], ...]
) -> tuple[bytes, bytes]:
    """A rebuilt field-parse table and its new name strings, as a pair.

    The stock entries pass through unchanged - by pointer, so every field already there keeps its
    own name string - then ``new_rows`` as ``(name, parse fn, userData, offset)``, then the
    all-zero terminator the parser scans for. Strings are padded so whatever follows stays
    dword-aligned.
    """
    table_size = (len(entries) + len(new_rows) + 1) * 16
    strings = bytearray()
    name_vas: list[int] = []
    for row in new_rows:
        name_vas.append(table_va + table_size + len(strings))
        strings += row[0].encode("ascii") + b"\x00"
    strings += b"\x00" * (-len(strings) % 4)

    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    for (_name, parse_fn, user_data, offset), name_va in zip(new_rows, name_vas, strict=True):
        table += struct.pack("<IIII", name_va, parse_fn, user_data, offset)
    table += struct.pack("<IIII", 0, 0, 0, 0)
    assert len(table) == table_size
    return bytes(table), bytes(strings)


def _table_span(entries: tuple[Entry, ...], names: tuple[str, ...]) -> int:
    """How many bytes a rebuilt table plus its padded name strings occupies."""
    table_size = (len(entries) + len(names) + 1) * 16
    strings = sum(len(name) + 1 for name in names)
    return table_size + strings + (-strings % 4)


_POWER_NAMES = tuple(name for name, _offset in POWER_FIELDS)
_OBJECT_NAMES = tuple(name for name, _user_data in OBJECT_FIELDS)


class HeroManaPatch(Patch):
    """Add `SpecialPower.ManaCost` plus `Object.ManaPool` / `Object.ManaRegen`, and enforce them.

    ``pool`` and ``regen`` are the fallbacks an object that declares neither gets: the maximum in
    whole points, and the refill in hundredths of a point per logic frame (30 == one point per
    second at 30fps).
    """

    name = "hero-mana"
    author = "officialNecro"
    description = "Give special powers a regenerating per-object mana cost (SpecialPower.ManaCost)"

    def __init__(
        self, pool: int = _DEFAULT_POOL, regen: int = _DEFAULT_REGEN, *, trace: bool = False
    ):
        for label, value in (("pool", pool), ("regen", regen)):
            if not 0 < value <= _CLAMP:
                raise ValueError(f"{label} must be in 1..{_CLAMP}, got {value}")
        self.pool = pool
        self.regen = regen
        #: Emit calls into the diagnostic ring. Off by default - it costs a `pushad`/`popad` per
        #: activation and the ring is only useful with a reader attached.
        self.trace = trace

    def __str__(self) -> str:
        suffix = ", trace" if self.trace else ""
        return f"{self.name} (pool={self.pool}, regen={self.regen}{suffix})"

    def apply(self, data: bytearray) -> None:
        self._check_dispatch(data)
        power_va, object_va = self._resolve(data)
        power, objects = self._check_build(data, power_va, object_va)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base_va: self._build_section(base_va, power, objects),
            _CHARACTERISTICS,
        )
        edits = self._edits(data, section_va, power, objects, power_va, object_va)
        for file_off, old, new, note in edits:
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless the ability-update tick is still the function its vtable names.

        The charge is installed *inside* that function. A hook in a routine nothing dispatches to
        applies perfectly, never fires, and looks exactly like a working patch - which is the
        failure this whole session started with.
        """
        off = va_to_offset(data, ABILITY_TRIGGER_VTABLE)
        if off is None:
            raise ValueError("the ability-update vtable is not mapped - not the expected build")
        target = struct.unpack_from("<I", data, off)[0]
        if target != ABILITY_TRIGGER:
            raise ValueError(
                f"vtable {ABILITY_TRIGGER_VTABLE:#010x} dispatches to {target:#010x}, not "
                f"{ABILITY_TRIGGER:#010x} - the ability trigger being hooked is not the live one"
            )

    @staticmethod
    def _resolve(data: bytes | bytearray) -> tuple[int, int]:
        """``(SpecialPower table VA, Object table VA)`` as the image currently holds them."""
        return (
            resolve_table(
                data,
                SPECIAL_POWER_FIELD_TABLE_REFS,
                SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
                "SpecialPower",
            ),
            resolve_table(data, OBJECT_FIELD_TABLE_REFS, OBJECT_FIELD_TABLE_REF_OPCODES, "Object"),
        )

    @staticmethod
    def _check_build(
        data: bytes | bytearray, power_va: int, object_va: int
    ) -> tuple[tuple[Entry, ...], tuple[Entry, ...]]:
        """Raise unless both tables still name the fields these offsets came from, neither
        already names a field this patch adds, and `SpecialPower`'s new field would land past
        every offset that table already uses.

        Together those make the patch safe against being applied twice, and against a build or a
        prior patch where `+0x88` is already somebody's."""
        tables: list[tuple[Entry, ...]] = []
        for base_va, fingerprint, added, what in (
            (power_va, _POWER_FINGERPRINT, _POWER_NAMES, "SpecialPower"),
            (object_va, _OBJECT_FINGERPRINT, _OBJECT_NAMES, "Object"),
        ):
            entries = read_field_table(data, base_va)
            by_name = {_read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
            for field, want in fingerprint.items():
                got = by_name.get(field)
                if got != want:
                    raise ValueError(
                        f"unexpected build: {what}.{field} is at "
                        f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                    )
            for field in added:
                if field in by_name:
                    raise ValueError(
                        f"the {what} table already names {field} - this patch is already "
                        "applied, or another patch has added the same field"
                    )
            tables.append(entries)

        highest = max(offset for _n, _f, _u, offset in tables[0])
        if highest >= MANA_COST_OFF:
            raise ValueError(
                f"the SpecialPower table already uses offset {highest:#x}, at or past the "
                f"{MANA_COST_OFF:#x} this patch adds - it is already applied, or another patch "
                "has grown SpecialPowerTemplate"
            )
        return tables[0], tables[1]

    @classmethod
    def _object_table_off(cls, power: tuple[Entry, ...]) -> int:
        return _TABLES_OFF + _table_span(power, _POWER_NAMES)

    @classmethod
    def _label_offs(cls, power: tuple[Entry, ...], objects: tuple[Entry, ...]) -> list[int]:
        """Where each description line's localization key sits, past both tables."""
        base = cls._object_table_off(power) + _table_span(objects, _OBJECT_NAMES)
        offs, cursor = [], 0
        for label in TOOLTIP_LABELS:
            offs.append(base + cursor)
            cursor += len(label) + 1
        return offs

    @classmethod
    def _code_offset(cls, power: tuple[Entry, ...], objects: tuple[Entry, ...]) -> int:
        span = sum(len(label) + 1 for label in TOOLTIP_LABELS)
        return cls._label_offs(power, objects)[0] + span + (-span % 4)

    def _build_section(
        self, base_va: int, power: tuple[Entry, ...], objects: tuple[Entry, ...]
    ) -> bytes:
        """Config dwords, the two row arrays, the two rebuilt field tables, then the code."""
        code = self._assemble(base_va, power, objects, trace=self.trace)
        parse_fn = code.label_va("tparse")

        power_table, power_strings = _table_bytes(
            base_va + _TABLES_OFF,
            power,
            tuple((name, INI_PARSE_INT, 0, offset) for name, offset in POWER_FIELDS),
        )
        object_table, object_strings = _table_bytes(
            base_va + self._object_table_off(power),
            objects,
            # offset 0: neither field is stored in the template at all, so `store` is unused.
            tuple((name, parse_fn, user_data, 0) for name, user_data in OBJECT_FIELDS),
        )

        head = bytearray(_TABLES_OFF)
        struct.pack_into("<I", head, _CFG_POOL_OFF, self.pool)
        struct.pack_into("<I", head, _CFG_REGEN_OFF, self.regen)
        body = bytes(head) + power_table + power_strings + object_table + object_strings
        assert len(body) == self._label_offs(power, objects)[0]
        labels = b"".join(label.encode("ascii") + b"\x00" for label in TOOLTIP_LABELS)
        body += labels + b"\x00" * (-len(labels) % 4)
        assert len(body) == self._code_offset(power, objects)
        return body + code.finish()

    @classmethod
    def _assemble(
        cls,
        base_va: int,
        power: tuple[Entry, ...],
        objects: tuple[Entry, ...],
        *,
        trace: bool = False,
    ) -> Asm:
        """The cave's code, laid out at the address it will occupy.

        :meth:`_build_section` takes the bytes and both field tables, and :meth:`_edits` takes
        label addresses, from one layout - so nothing can be pointed at a routine that moved.
        """
        a = Asm(base_va + cls._code_offset(power, objects))
        template_rows = base_va + _TEMPLATE_OFF
        _emit_trace(a, base_va + _TRACE_INDEX_OFF, base_va + _TRACE_ENTRIES_OFF)
        _emit_lookup(a, template_rows)
        _emit_insert(a, template_rows)
        _emit_parse(a, base_va + _SCRATCH_OFF)
        _emit_propagate(a)
        _emit_value(a, base_va + _CFG_POOL_OFF, base_va + _CFG_REGEN_OFF, base_va + _POOL_OFF)
        _emit_check(a)
        _emit_spend(a, base_va + _POOL_OFF, trace=trace)
        _emit_new(a)
        _emit_copy_tail(a)
        _emit_can_use(a)
        _emit_control_bar(a)
        label_vas = [base_va + off for off in cls._label_offs(power, objects)]
        _emit_ability_trigger(a, trace=trace)
        _emit_description(a, label_vas[0])
        _emit_revive_line(a, label_vas[1])
        if trace:
            # Observation only, and only in a trace build - see `_emit_dispatch_hook`.
            for index, (_va, window, resume_va) in enumerate(DO_SPECIAL_POWER_SITES):
                _emit_dispatch_hook(a, index, window, resume_va, trace=trace)
        a.finish()  # resolve the internal branches, so `label_va` describes a real layout
        return a

    def _edits(
        self,
        data: bytes | bytearray,
        section_va: int,
        power: tuple[Entry, ...],
        objects: tuple[Entry, ...],
        old_power_va: int,
        old_object_va: int,
        *,
        table_refs: bool = True,
    ) -> list[tuple[int, bytes, bytes, str]]:
        """``(file offset, original bytes, patched bytes, note)`` for every engine byte this
        patch rewrites. One list so :meth:`apply` writes exactly what :meth:`verify` asserts.

        ``table_refs=False`` drops the field-table repoints. :meth:`verify` asks for that, because
        a repoint is the one edit here a *later* patch is entitled to overwrite: a second patch
        extending the same table rebuilds it including these rows - by pointer, so they stay the
        same rows with the same parse function - and points the reference at its own copy. What
        has to hold afterwards is that the live table still names these fields correctly, which
        `verify` checks directly, not that the reference still names this patch's copy."""
        labels = self._assemble(section_va, power, objects, trace=self.trace).label_va
        out: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int) -> int:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            return off

        # 1. repoint both field tables
        for refs, opcodes, old_va, new_va, what in (
            ()
            if not table_refs
            else (
                (
                    SPECIAL_POWER_FIELD_TABLE_REFS,
                    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
                    old_power_va,
                    section_va + _TABLES_OFF,
                    "SpecialPower",
                ),
                (
                    OBJECT_FIELD_TABLE_REFS,
                    OBJECT_FIELD_TABLE_REF_OPCODES,
                    old_object_va,
                    section_va + self._object_table_off(power),
                    "Object",
                ),
            )
        ):
            for ref_va, opcode in zip(refs, opcodes, strict=True):
                out.append(
                    (
                        at(ref_va),
                        bytes([opcode]) + _u32(old_va),
                        bytes([opcode]) + _u32(new_va),
                        f"{what} field table ref @0x{ref_va:08x}",
                    )
                )

        # 2. grow SpecialPowerTemplate at all three allocations, and zero the new field
        for push_va, call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
            out.append(
                (
                    at(push_va),
                    b"\x68" + _u32(SPECIAL_POWER_TEMPLATE_SIZE),
                    b"\x68" + _u32(NEW_TEMPLATE_SIZE),
                    f"SpecialPowerTemplate size @0x{push_va:08x}",
                )
            )
            out.append(
                (
                    at(call_va),
                    _call(call_va, OPERATOR_NEW),
                    _call(call_va, labels("new")),
                    f"operator new -> zeroing wrapper @0x{call_va:08x}",
                )
            )

        # 3. carry the new field through the SpecialPowerTemplate copy constructor
        out.append(
            (
                at(SPECIAL_POWER_TEMPLATE_COPY_TAIL),
                SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
                _jmp(SPECIAL_POWER_TEMPLATE_COPY_TAIL, labels("copy"))
                + b"\x90" * (len(SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES) - 5),
                "SpecialPowerTemplate copy ctor tail",
            )
        )

        # 4. carry the side-table row through ThingTemplate::copyFrom, so an INI override of an
        #    Object block keeps the pool the base declared
        out.append(
            (
                at(THING_TEMPLATE_COPY_CALL),
                THING_TEMPLATE_COPY_CALL_BYTES,
                _call(THING_TEMPLATE_COPY_CALL, labels("tprop")),
                "ThingTemplate::copyFrom -> side-table propagation",
            )
        )

        # 5. the charge, where an ability update actually fires - the click is too early, and
        #    for an `UpdateModuleStartsAttack` power the click is not even on this path
        out.append(
            (
                at(ABILITY_TRIGGER_PAY),
                ABILITY_TRIGGER_PAY_BYTES,
                _jmp(ABILITY_TRIGGER_PAY, labels("atrig"))
                + b"\x90" * (len(ABILITY_TRIGGER_PAY_BYTES) - 5),
                "ability trigger -> mana charge",
            )
        )

        # 6. the gate
        out.append(
            (
                at(CAN_USE_SPECIAL_POWER),
                CAN_USE_SPECIAL_POWER_ENTRY,
                _jmp(CAN_USE_SPECIAL_POWER, labels("canuse")),
                "canUseSpecialPower -> mana gate",
            )
        )

        # 7. observation points on the activation variants - trace builds only. They take no
        #    cost; the charge is at the trigger in step 5.
        if self.trace:
            for index, (va, window, _resume) in enumerate(DO_SPECIAL_POWER_SITES):
                out.append(
                    (
                        at(va),
                        window,
                        _jmp(va, labels(f"d{index}")) + b"\x90" * (len(window) - 5),
                        f"doSpecialPower variant {index} -> trace",
                    )
                )

        # 8. a ManaCost line in the button description, ahead of the stock UnitCost one
        out.append(
            (
                at(DESCRIPTION_SPECIAL_POWER_CASE),
                DESCRIPTION_SPECIAL_POWER_CASE_BYTES,
                _jmp(DESCRIPTION_SPECIAL_POWER_CASE, labels("desc")),
                "button description -> ManaCost line",
            )
        )

        # 9. a ManaPool line under the hero's level on its revive/recruit button
        out.append(
            (
                at(DESCRIPTION_RANK_APPEND),
                DESCRIPTION_RANK_APPEND_BYTES,
                _jmp(DESCRIPTION_RANK_APPEND, labels("rline"))
                + b"\x90" * (len(DESCRIPTION_RANK_APPEND_BYTES) - 5),
                "hero revive description -> ManaPool line",
            )
        )

        # 10. the ControlBar's button state
        out.append(
            (
                at(CONTROL_BAR_UNIT_COST_CALL),
                CONTROL_BAR_UNIT_COST_CALL_BYTES,
                _call(CONTROL_BAR_UNIT_COST_CALL, labels("cbar")),
                "ControlBar availability -> mana test",
            )
        )
        return out

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--pool",
            type=int,
            default=_DEFAULT_POOL,
            metavar="N",
            help="default maximum, in whole points, for an Object that declares no ManaPool "
            f"(default {_DEFAULT_POOL})",
        )
        parser.add_argument(
            "--regen",
            type=int,
            default=_DEFAULT_REGEN,
            metavar="N",
            help="default refill, in hundredths of a point per logic frame, for an Object that "
            f"declares no ManaRegen (default {_DEFAULT_REGEN} == 1 point/second at 30fps)",
        )
        parser.add_argument(
            "--trace",
            action="store_true",
            help="record every activation into a diagnostic ring in the cave, for "
            "tools/hero_mana_trace.py to read out of a running game (debug builds only)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> HeroManaPatch:
        return cls(pool=args.pool, regen=args.regen, trace=args.trace)

    def ini_surface(self) -> Engine:
        """The three `Int` fields this patch teaches the parser, from the same tables the caves
        are built from. All default to 0, which is "no mana cost" / "use the patch's own pool and
        regen" - so a mod that names none of them is unaffected, exactly as the code path is."""
        return Engine(
            fields=tuple(
                FieldDelta(block=block, name=field, type="Int", default=0, patch=self.name)
                for block, fields in (("SpecialPower", POWER_FIELDS), ("Object", OBJECT_FIELDS))
                for field, _user_data in fields
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        problems: list[str] = []

        try:
            power_va, object_va = self._resolve(data)
            power_all = read_field_table(data, power_va)
            object_all = read_field_table(data, object_va)
        except ValueError as exc:
            return [f"cannot read the field tables: {exc}"]
        # By name, not by position: another patch may have extended either table afterwards, and
        # these counts size the rebuilt tables - which place every routine in the cave.
        power = entries_before(data, power_all, POWER_FIELDS[0][0])
        objects = entries_before(data, object_all, OBJECT_FIELDS[0][0])
        if power is None or objects is None:
            missing = POWER_FIELDS[0][0] if power is None else OBJECT_FIELDS[0][0]
            return [f"no {missing} row: the file does not carry this patch"]

        by_name = {}
        for table in (power_all, object_all):
            for entry in table:
                by_name[_read_cstring(data, entry[0])] = entry

        for field, offset in POWER_FIELDS:
            row = by_name.get(field)
            if row is None:
                problems.append(f"the SpecialPower table does not name {field}")
                continue
            if row[1] != INI_PARSE_INT:
                problems.append(f"{field} parses with 0x{row[1]:08x}, not the stock Int parser")
            if row[3] != offset:
                problems.append(f"{field} writes 0x{row[3]:x}, expected 0x{offset:x}")

        parse_fn = self._assemble(section_va, power, objects, trace=self.trace).label_va("tparse")
        for field, user_data in OBJECT_FIELDS:
            row = by_name.get(field)
            if row is None:
                problems.append(f"the Object table does not name {field}")
                continue
            if row[1] != parse_fn:
                problems.append(f"{field} does not use the patch's own parse function")
            if row[2] != user_data:
                problems.append(f"{field} carries userData {row[2]}, expected {user_data}")
            if row[3] != 0:
                problems.append(f"{field} has a non-zero template offset ({row[3]:#x})")

        if struct.unpack_from("<I", data, section_off + _CFG_POOL_OFF)[0] != self.pool:
            problems.append(f"the default pool is not {self.pool}")
        if struct.unpack_from("<I", data, section_off + _CFG_REGEN_OFF)[0] != self.regen:
            problems.append(f"the default regen is not {self.regen}")

        try:
            edits = self._edits(
                data, section_va, power, objects, power_va, object_va, table_refs=False
            )
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got_bytes = bytes(data[file_off : file_off + len(new)])
            if got_bytes != new:
                problems.append(
                    f"{note} @0x{file_off:x}: expected {new.hex()}, got {got_bytes.hex()}"
                )
        return problems


def _call(at_va: int, target_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", target_va - (at_va + 5))


def _jmp(at_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - (at_va + 5))
