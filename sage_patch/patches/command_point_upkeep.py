"""The command-point-upkeep patch: make a large army cost a player income.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below comes
from :mod:`sage_patch.addresses` and is derived in ``../docs/command-point-upkeep.md``.

**Why this is small.** `PlayerTemplate.ResourceModifierValues` is not an analogue of what this
patch wants - it is *literally the same computation*. `AutoDepositUpdate::update` already loads
a per-faction `Int` table out of the `PlayerTemplate`, turns a **count** into a percentage, and
scales the deposit by it::

    008855a3  mov  eax, [esi+0x34]      ; the controlling Player's PlayerTemplate
    008855ae  lea  ecx, [eax+0x1c8]     ; &ResourceModifierObjectFilter
    008855ec  call 0x6ababd             ; count the player's objects the filter accepts
    008855f7  add  eax, 0x1cc           ; &ResourceModifierValues
    0088560a  mulss xmm0, [0xBE5600]    ; mult = values[count] * 0.01     -> [ebp-0x1c]
    ...
    00885685  fmul [ebp-0x1c]           ; the deposit, scaled

Upkeep swaps the count for **command points in use** and reuses everything else. It multiplies
`[ebp-0x1c]` by a second factor before that `fmul`, so the two stack cleanly and the engine's own
"never round income below 1 gold" floor still applies.

**The INI.** Two new `PlayerTemplate` fields, both **opt-in**::

    UpkeepCommandPointStep = 500              ; Int. 0 (the default) == no upkeep at all.
    UpkeepValues           = 100 90 80 70 60  ; percent of income kept, indexed by tier

`tier = commandPointsInUse / step`, clamped to the last entry, and the deposit keeps
`UpkeepValues[tier]` percent. So the example above is "-10% per 500 command points, floored at
-40%". A faction declaring neither field is byte-for-byte unaffected, which is the same rule
`hero-mana` follows with `ManaCost = 0`.

**Which income is taxed.** Only what the faction's own `ResourceModifierObjectFilter` accepts -
the cave re-runs the exact pair of calls the inflation block made three instructions earlier
(`ObjectFilter::isValid`, then `ObjectFilter::allow(object, player)`). `AutoDepositUpdate` is
*all* tick income, not only resource buildings, and without the gate upkeep would silently tax
captured neutral structures and creep lairs too. A faction with no filter set therefore gets no
upkeep, exactly as it gets no inflation.

**Where the per-faction numbers live, and why not on the template.** They cannot go on the
`PlayerTemplate`. It is `0x1DC` bytes with no hole (the apparent gap at `+0x152` is a subobject
with its own field table, added at `PlayerTemplate::parse` with extra offset `0x154`), and
growing it means correcting **24** separate `0x1DC` literals in the store's compiland alone.
Worse, a pointer key would not survive: templates live in a `std::vector<PlayerTemplate>` and a
new block is parsed into a *stack temporary* before being copied in, so the `this` a field
callback sees is transient and is reused by the next block.

So the rows live in the cave, keyed by the template's `NameKeyType` at `+0x10` - the one stable
identity a template has, and the one `PlayerTemplateStore::findPlayerTemplate` itself matches on.
The key is computed once per block, before any of the three parse paths branch, and a hook there
records it for the field callbacks to file against.

**Consequences of keying by name rather than by pointer**, all of them wanted:

* **No savegame change and no init hook.** The rows are INI-derived and rebuilt on every load;
  the command-point count is an existing `Xfer`'d field. Nothing new is per-game state.
* **An override block merges rather than replaces.** A `map.ini` re-declaring a faction shares
  its key, so it overwrites only the fields it names - where the engine's own copy semantics
  would have dropped the rest.
* **A missing row is "no upkeep", never a wrong number.** A full table, an absent key and a zero
  step all take the same untaxed path.

**Determinism.** Every input is simulation state identical on every peer: the player's command
points, its template's name key, and the INI. No pointer *value* is read, and the only writes
happen at INI load. The HUD half is a **pure read** on the local client.

**The display.** The palantir's command-point text is not a numeric data binding - `0x0080078F`
formats `L"%d/%d"` and hands the string to `TheAptPlayer::setValue`, and a mod's `.csf` entry of
the same name is only a design-time placeholder (Edain's reads ``102/200``). So a third number
has to come from the engine, and it does: with upkeep active the text reads ``500/1500 (-10%)``,
built by the same formatter with one more vararg. No `.apt` edit, no `.csf`/`.str` edit, and at
zero loss the stock two-number form is emitted unchanged.

> **Every peer must run the same patched binary.** Income decides what gets built, so the effect
> is inside the simulation: a patched and an unpatched client desync and replays do not cross.
> Same rule as `production-condition`, stricter than `replay-outcome`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    AUTO_DEPOSIT_FILTER_EBP,
    AUTO_DEPOSIT_MULTIPLIER_EBP,
    AUTO_DEPOSIT_SCALE,
    AUTO_DEPOSIT_SCALE_BYTES,
    AUTO_DEPOSIT_SCALE_RESUME,
    INI_NEXT_TOKEN_OR_NULL,
    INI_SCAN_INT,
    OBJECT_FILTER_ALLOW,
    OBJECT_FILTER_IS_VALID,
    PALANTIR_COMMAND_POINTS,
    PALANTIR_COMMAND_POINTS_BYTES,
    PALANTIR_COMMAND_POINTS_DONE,
    PALANTIR_COMMAND_POINTS_RESUME,
    PLAYER_COMMAND_POINTS_USED,
    PLAYER_LIST_GET_LOCAL_PLAYER,
    PLAYER_PLAYER_TEMPLATE,
    PLAYER_TEMPLATE_BLOCK_KEY,
    PLAYER_TEMPLATE_BLOCK_KEY_BYTES,
    PLAYER_TEMPLATE_BLOCK_KEY_RESUME,
    PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
    PLAYER_TEMPLATE_FIELD_TABLE_REFS,
    PLAYER_TEMPLATE_FIND_BY_KEY,
    PLAYER_TEMPLATE_NAME_KEY,
    PLAYER_TEMPLATE_RESOURCE_FILTER,
    PLAYER_TEMPLATE_RESOURCE_VALUES,
    THE_PLAYER_LIST,
    UNICODE_STRING_FORMAT,
)
from ..asm import JAE, JBE, JE, JG, JL, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

# `read_field_table` and `resolve_table` are generic field-table helpers that happen to live in
# the patch that needed them first. This is a code import only - the two patches rewrite
# different tables (`Object`/`SpecialPower` there, `PlayerTemplate` here) and share no byte.
from .hero_mana import Entry, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "FIELDS",
    "MAX_PERCENT",
    "ROWS",
    "ROW_STRIDE",
    "SECTION_NAME",
    "VALUES",
    "CommandPointUpkeepPatch",
    "kept_percent",
]

SECTION_NAME = ".upkeep"  # 8 chars max: the PE name field truncates silently past 8

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds code, the
# rebuilt field table and a row array written at INI load, so it needs all three access bits.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The two `PlayerTemplate` entries this patch appends, as `(name, userData)`. They share one
#: parse function and are told apart by `userData`, because neither is stored in the template at
#: all - both land in the cave's own row table. Their table `offset` is therefore 0.
FIELDS: tuple[tuple[str, int], ...] = (("UpkeepCommandPointStep", 0), ("UpkeepValues", 1))

#: Rows in the faction table. A power of two so the index fold is an `and`. Edain defines ~40
#: `PlayerTemplate` blocks; 128 leaves room for a mod that defines many more.
ROWS = 128

#: Tiers per faction. Past the last one the last value is held, so this bounds the *table*, not
#: the curve - a step of 500 with 16 entries still describes every army up to 7500 command
#: points and everything beyond it.
VALUES = 16

#: ``{ UnsignedInt key; Int step; UnsignedInt count; Int values[VALUES]; }``
ROW_STRIDE = 12 + VALUES * 4

#: Percentages are clamped into ``0..100`` before use. Above 100 would be a *bonus*, which the
#: `(-N%)` the HUD prints could not describe honestly; below 0 would invert the deposit.
MAX_PERCENT = 100

_ROWS_MASK = ROWS - 1

_KEY_OFF = 0x00  # the name key of the PlayerTemplate block currently being parsed
_ROWS_OFF = 0x10
_CONST_OFF = _ROWS_OFF + ROWS * ROW_STRIDE  # the float 0.01f the percentage is scaled by
_FMT_OFF = _CONST_OFF + 4

#: ``used/cap (-loss%)``, UTF-16 like the engine's own ``L"%d/%d"`` at `0x00C4E594`.
FORMAT = "%d/%d (-%d%%)"
_FMT_BYTES = FORMAT.encode("utf-16-le") + b"\x00\x00"
_TABLE_OFF = _FMT_OFF + len(_FMT_BYTES) + (-len(_FMT_BYTES) % 4)

#: Names the `PlayerTemplate` table must carry at these offsets, or this is not the build these
#: addresses were derived against. Checked by name rather than by count, so the check survives
#: another patch having extended the table first.
_FINGERPRINT = {
    "ResourceModifierObjectFilter": PLAYER_TEMPLATE_RESOURCE_FILTER,
    "ResourceModifierValues": PLAYER_TEMPLATE_RESOURCE_VALUES,
    "MultiSelectionPortrait": 0x1D8,
}

_NAMES = tuple(name for name, _user_data in FIELDS)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> int:
    """A signed byte displacement as the unsigned byte that encodes it."""
    return value & 0xFF


def kept_percent(command_points: int, step: int, values: tuple[int, ...]) -> int:
    """The percentage of income a player keeps - the cave's arithmetic, in Python.

    The single source of truth for what the mechanic *means*, so the tests can state the
    behaviour once and assert the emitted code against the same rule.
    """
    if step <= 0 or not values:
        return MAX_PERCENT
    tier = min(max(command_points, 0) // step, len(values) - 1)
    return min(max(values[tier], 0), MAX_PERCENT)


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.


def _emit_probe(a: Asm, tag: str, rows_va: int, *, claim: bool) -> None:
    """An open-addressed probe of the faction table, keyed by the name key in ``eax``.

    Hash the key, walk forward over occupied slots, stop at the key or at an empty one. Entries
    are never removed, so a run of occupied slots is never broken and the walk is exact. Returns
    the row in `eax`, or 0 when the key is absent (lookup), when the table is full (insert), or
    when the key is 0 - a full table degrades a faction to "no upkeep" rather than failing the
    load.

    Preserves everything but `eax`, so the read path can be called from anywhere.
    """
    a.emit(0x53, 0x51, 0x52)  # push ebx / push ecx / push edx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, f"{tag}_none")  # key 0 is the empty marker, never a row
    a.emit(0x8B, 0xD8)  # mov ebx, eax               ; the key
    a.emit(0x25, _u32(_ROWS_MASK))  # and eax, ROWS-1
    a.emit(0xB9, _u32(ROWS))  # mov ecx, ROWS              ; probe budget
    a.label(f"{tag}_probe")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(0x6B, 0xD2, ROW_STRIDE)  # imul edx, edx, ROW_STRIDE
    a.emit(0x81, 0xC2, _u32(rows_va))  # add edx, rows
    a.emit(0x83, 0x3A, 0x00)  # cmp dword ptr [edx], 0
    a.jcc(JE, f"{tag}_empty")
    a.emit(0x39, 0x1A)  # cmp dword ptr [edx], ebx
    a.jcc(JE, f"{tag}_hit")
    a.emit(0x40)  # inc eax
    a.emit(0x25, _u32(_ROWS_MASK))  # and eax, ROWS-1
    a.emit(0x49)  # dec ecx
    a.jcc(JNE, f"{tag}_probe")
    a.label(f"{tag}_none")  # budget exhausted, or key 0
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.jmp(f"{tag}_out")
    a.label(f"{tag}_empty")
    if claim:
        a.emit(0x89, 0x1A)  # mov [edx], ebx             ; claim the slot for this faction
        a.emit(0x83, 0x62, 0x04, 0x00)  # and dword ptr [edx+4], 0   ; step
        a.emit(0x83, 0x62, 0x08, 0x00)  # and dword ptr [edx+8], 0   ; count
    else:
        a.emit(0x31, 0xC0)  # xor eax, eax               ; absent
        a.jmp(f"{tag}_out")
    a.label(f"{tag}_hit")
    a.emit(0x8B, 0xC2)  # mov eax, edx
    a.label(f"{tag}_out")
    a.emit(0x5A, 0x59, 0x5B)  # pop edx / pop ecx / pop ebx
    a.emit(0xC3)  # ret


def _emit_lookup(a: Asm, rows_va: int) -> None:
    """``lookup``: `eax` = a name key, `eax` = its row or 0. Pure; the read path calls it."""
    a.label("lookup")
    _emit_probe(a, "lu", rows_va, claim=False)


def _emit_insert(a: Asm, rows_va: int) -> None:
    """``insert``: as ``lookup``, but claims an empty slot. Only ever runs at INI load."""
    a.label("insert")
    _emit_probe(a, "in", rows_va, claim=True)


def _emit_block(a: Asm, key_va: int) -> None:
    """The hook that records which faction is being parsed.

    A `PlayerTemplate` block's name key is computed once, before the three parse paths (a new
    block, an override block, a re-parse of an existing one) branch - and *after* that point a
    new block is parsed into a stack temporary whose address means nothing. So the key is
    stashed here, and the field callbacks file their values against it.

    `ecx` is the store and must survive to the displaced call.
    """
    a.label("block")
    a.emit(0x8B, 0xF8)  # mov edi, eax                 ; the displaced pair
    a.emit(0xA3, _u32(key_va))  # mov [g_key], eax
    a.emit(0x57)  # push edi
    a.call_absolute(PLAYER_TEMPLATE_FIND_BY_KEY)
    a.jmp_absolute(PLAYER_TEMPLATE_BLOCK_KEY_RESUME)


def _emit_parse(a: Asm, key_va: int) -> None:
    """The parse function behind both new fields.

    cdecl `(INI*, void *instance, void *store, const void *userData)`, the shape the field-parse
    dispatcher calls, and the shape the stock `INI::parseInt` has. `instance` and `store` are
    ignored - the table entries carry offset 0, so nothing is written into the template at all.
    `userData` says which field it is: 0 is the scalar step, 1 is the value list.

    **Tokens are always consumed even when there is no row to put them in**, so a full table or
    a missing block key cannot leave the parser mid-line.
    """
    a.label("parse")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x53, 0x57)  # push ebx / push edi
    a.emit(0x31, 0xDB)  # xor ebx, ebx                 ; the row, 0 until claimed
    a.emit(0xA1, _u32(key_va))  # mov eax, [g_key]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "q_dispatch")
    a.call("insert")
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.label("q_dispatch")
    a.emit(0x83, 0x7D, 0x14, 0x00)  # cmp dword ptr [ebp+0x14], 0  ; userData
    a.jcc(JNE, "q_values")

    # UpkeepCommandPointStep: one Int, the same shape as the stock `INI::parseInt`.
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]             ; the INI
    a.emit(0x6A, 0x00)  # push 0
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "q_out")
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]
    a.emit(0x50)  # push eax                     ; the token
    a.call_absolute(INI_SCAN_INT)  # ret 4
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "q_out")
    a.emit(0x89, 0x43, 0x04)  # mov [ebx+4], eax             ; row->step
    a.jmp("q_out")

    # UpkeepValues: Int tokens to end of line, exactly as `ResourceModifierValues` is read.
    a.label("q_values")
    a.emit(0x31, 0xFF)  # xor edi, edi                 ; how many are stored
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "q_loop")
    a.emit(0x83, 0x63, 0x08, 0x00)  # and dword ptr [ebx+8], 0     ; a re-declaration replaces
    a.label("q_loop")
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]
    a.emit(0x6A, 0x00)  # push 0
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "q_out")
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]
    a.emit(0x50)  # push eax
    a.call_absolute(INI_SCAN_INT)
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "q_loop")  # no row: parsed and dropped
    a.emit(0x83, 0xFF, VALUES)  # cmp edi, VALUES
    a.jcc(JAE, "q_loop")  # past capacity: parsed and dropped
    a.emit(0x89, 0x44, 0xBB, 0x0C)  # mov [ebx+edi*4+0xc], eax     ; row->values[i]
    a.emit(0x47)  # inc edi
    a.emit(0x89, 0x7B, 0x08)  # mov [ebx+8], edi             ; row->count
    a.jmp("q_loop")

    a.label("q_out")
    a.emit(0x5F, 0x5B)  # pop edi / pop ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret                          ; cdecl - the dispatcher cleans


def _emit_percent(a: Asm) -> None:
    """``percent``: `ecx` = a `Player*`, `eax` = the percentage of income it keeps.

    100 means "untouched", and it is what every degenerate case returns: no player, no template,
    no row, a zero or negative step, an empty value list. Preserves every register but `eax`,
    `ecx` and the flags.
    """
    a.label("percent")
    a.emit(0x53, 0x56, 0x57, 0x52)  # push ebx / push esi / push edi / push edx
    a.emit(0xB8, _u32(MAX_PERCENT))  # mov eax, 100
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "pc_out")
    a.emit(0x8B, 0x51, PLAYER_PLAYER_TEMPLATE)  # mov edx, [ecx+0x34]  ; the PlayerTemplate
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "pc_out")
    a.emit(0x8B, 0x71, PLAYER_COMMAND_POINTS_USED)  # mov esi, [ecx+0x68] ; points in use
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JG, "pc_have")
    a.emit(0x31, 0xF6)  # xor esi, esi                 ; a negative count is tier 0
    a.label("pc_have")
    a.emit(0x8B, 0x42, PLAYER_TEMPLATE_NAME_KEY)  # mov eax, [edx+0x10]  ; the faction key
    a.call("lookup")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pc_none")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                 ; the row
    a.emit(0x8B, 0x4B, 0x04)  # mov ecx, [ebx+4]             ; step
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JLE, "pc_none")  # 0 (the default) == upkeep off
    a.emit(0x8B, 0x7B, 0x08)  # mov edi, [ebx+8]             ; count
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JLE, "pc_none")
    a.emit(0x8B, 0xC6)  # mov eax, esi                 ; command points
    a.emit(0x31, 0xD2)  # xor edx, edx
    a.emit(0xF7, 0xF1)  # div ecx                      ; eax = tier
    a.emit(0x4F)  # dec edi                      ; the last usable index
    a.emit(0x3B, 0xC7)  # cmp eax, edi
    a.jcc(JBE, "pc_index")
    a.emit(0x8B, 0xC7)  # mov eax, edi                 ; past the table: hold the last value
    a.label("pc_index")
    a.emit(0x8B, 0x44, 0x83, 0x0C)  # mov eax, [ebx+eax*4+0xc]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JLE, "pc_zero")
    a.emit(0x83, 0xF8, MAX_PERCENT)  # cmp eax, 100
    a.jcc(JBE, "pc_out")
    a.label("pc_none")
    a.emit(0xB8, _u32(MAX_PERCENT))  # mov eax, 100
    a.jmp("pc_out")
    a.label("pc_zero")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("pc_out")
    a.emit(0x5A, 0x5F, 0x5E, 0x5B)  # pop edx / pop edi / pop esi / pop ebx
    a.emit(0xC3)  # ret


def _emit_deposit(a: Asm, const_va: int) -> None:
    """The charge, in `AutoDepositUpdate::update`.

    `esi` is the controlling `Player`, `edi` the depositing `Object`, and `[ebp-0x20]` still
    holds `&template->ResourceModifierObjectFilter` (a `fistp` reuses that slot 0x22 bytes
    later, which is why the hook is here and not further down). Re-running the filter is what
    limits upkeep to the income the stock inflation already scales: `AutoDepositUpdate` is on
    civilian buildings and creep lairs too.

    The x87 stack is empty here - the displaced `fild` is the next push - so one balanced
    push/pop is safe.
    """
    a.label("deposit")
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0x8B, 0x4D, _i8(AUTO_DEPOSIT_FILTER_EBP))  # mov ecx, [ebp-0x20]
    a.call_absolute(OBJECT_FILTER_IS_VALID)  # thiscall, no arguments
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "dp_done")  # no filter -> no inflation, so no upkeep
    a.emit(0x8B, 0x4D, _i8(AUTO_DEPOSIT_FILTER_EBP))  # mov ecx, [ebp-0x20]
    a.emit(0x56)  # push esi                     ; the Player
    a.emit(0x57)  # push edi                     ; the Object
    a.call_absolute(OBJECT_FILTER_ALLOW)  # ret 8
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "dp_done")
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call("percent")
    a.emit(0x83, 0xF8, MAX_PERCENT)  # cmp eax, 100
    a.jcc(JAE, "dp_done")  # nothing to take
    a.emit(0x50)  # push eax
    a.emit(0xDB, 0x04, 0x24)  # fild dword ptr [esp]   (DB /0 - DF /0 would be a 16-bit load)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0xD8, 0x0D, _u32(const_va))  # fmul dword ptr [0.01f]
    a.emit(0xD8, 0x4D, _i8(AUTO_DEPOSIT_MULTIPLIER_EBP))  # fmul dword ptr [ebp-0x1c]
    a.emit(0xD9, 0x5D, _i8(AUTO_DEPOSIT_MULTIPLIER_EBP))  # fstp dword ptr [ebp-0x1c]
    a.label("dp_done")
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.emit(AUTO_DEPOSIT_SCALE_BYTES)  # the displaced pair
    a.jmp_absolute(AUTO_DEPOSIT_SCALE_RESUME)


def _emit_local_loss(a: Asm) -> None:
    """``loss``: the local player's upkeep, as a positive percentage. 0 when there is none.

    Read-only, and read-only is required: this runs on the local client only, so a write here
    would be a desync.
    """
    a.label("loss")
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0x8B, 0x0D, _u32(THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "ls_out")
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)  # thiscall, no arguments
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "ls_out")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call("percent")
    a.emit(0x8B, 0xC8)  # mov ecx, eax                 ; what is kept
    a.emit(0xB8, _u32(MAX_PERCENT))  # mov eax, 100
    a.emit(0x29, 0xC8)  # sub eax, ecx                 ; what is lost
    a.jcc(JG, "ls_out")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("ls_out")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.emit(0xC3)  # ret


def _emit_text(a: Asm, fmt_va: int) -> None:
    """A third number in the palantir's command-point text: ``500/1500 (-10%)``.

    The engine builds that text with `UnicodeString::format(L"%d/%d", used, cap)` - cdecl, so
    the varargs are pushed last-first and the trailing `add esp` counts them. The hook therefore
    sits *before* the first vararg push, which is the only place a third one fits.

    With no upkeep the stock two-number call is emitted byte-identically, including the
    negative-`used` branch that falls back to a single `%d`.
    """
    a.label("text")
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.call("loss")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "tx_plain")
    a.emit(0x83, 0x7D, 0x0C, 0x00)  # cmp dword ptr [ebp+0xc], 0
    a.jcc(JL, "tx_plain")  # a negative count takes the stock one-number path
    a.emit(0x50)  # push eax                     ; vararg 3 - the loss
    a.emit(0xFF, 0x75, 0x08)  # push dword ptr [ebp+8]       ; vararg 2 - the cap
    a.emit(0xFF, 0x75, 0x0C)  # push dword ptr [ebp+0xc]     ; vararg 1 - points in use
    a.emit(0x68, _u32(fmt_va))  # push L"%d/%d (-%d%%)"
    a.emit(0x8D, 0x45, 0xF0)  # lea eax, [ebp-0x10]          ; the UnicodeString
    a.emit(0x50)  # push eax
    a.call_absolute(UNICODE_STRING_FORMAT)
    a.emit(0x83, 0xC4, 0x14)  # add esp, 20                  ; three varargs, not two
    a.jmp_absolute(PALANTIR_COMMAND_POINTS_DONE)
    a.label("tx_plain")
    a.emit(PALANTIR_COMMAND_POINTS_BYTES)  # the displaced compare and push
    a.jmp_absolute(PALANTIR_COMMAND_POINTS_RESUME)


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    return None if end < 0 else bytes(data[off : off + end]).decode("latin1")


def _table_bytes(table_va: int, entries: tuple[Entry, ...], parse_fn: int) -> tuple[bytes, bytes]:
    """A rebuilt `PlayerTemplate` field-parse table and its new name strings.

    The stock entries pass through unchanged - by pointer, so every field already there keeps
    its own name string - then the two new rows, then the all-zero terminator the parser scans
    for. Strings are padded so whatever follows stays dword-aligned.
    """
    table_size = (len(entries) + len(FIELDS) + 1) * 16
    strings = bytearray()
    name_vas: list[int] = []
    for name in _NAMES:
        name_vas.append(table_va + table_size + len(strings))
        strings += name.encode("ascii") + b"\x00"
    strings += b"\x00" * (-len(strings) % 4)

    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    for (_name, user_data), name_va in zip(FIELDS, name_vas, strict=True):
        # offset 0: nothing is written into the template, so `store` is never used.
        table += struct.pack("<IIII", name_va, parse_fn, user_data, 0)
    table += struct.pack("<IIII", 0, 0, 0, 0)
    assert len(table) == table_size
    return bytes(table), bytes(strings)


def _table_span(entries: tuple[Entry, ...]) -> int:
    """How many bytes the rebuilt table plus its padded name strings occupies."""
    table_size = (len(entries) + len(FIELDS) + 1) * 16
    strings = sum(len(name) + 1 for name in _NAMES)
    return table_size + strings + (-strings % 4)


class CommandPointUpkeepPatch(Patch):
    """Scale a faction's tick income down as its command-point usage crosses INI thresholds.

    ``hud`` (default on) also appends the current loss to the palantir's command-point readout,
    so ``500/1500`` becomes ``500/1500 (-10%)``. Turning it off leaves the mechanic and the text
    exactly as the stock engine draws it.
    """

    name = "command-point-upkeep"
    description = (
        "Scale resource-building income down as a player's command-point usage rises "
        "(PlayerTemplate.UpkeepCommandPointStep / UpkeepValues)"
    )

    def __init__(self, *, hud: bool = True):
        #: Show the current upkeep beside the command-point numbers. Client-local either way -
        #: the text never enters the simulation - but it is the whole point of the feature
        #: being legible, so it is on by default.
        self.hud = hud

    def __str__(self) -> str:
        return self.name if self.hud else f"{self.name} (no hud)"

    def apply(self, data: bytearray) -> None:
        table_va = self._resolve(data)
        entries = self._check_build(data, table_va)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build_section(base, entries), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va, entries, table_va):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """The `PlayerTemplate` field table's base VA, as the image currently holds it.

        Read from the reference that names it rather than from the stock constant, so the patch
        appends to whatever is live - and so applying it twice fails cleanly instead of
        installing a second copy of both fields.
        """
        return resolve_table(
            data,
            PLAYER_TEMPLATE_FIELD_TABLE_REFS,
            PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
            "PlayerTemplate",
        )

    @staticmethod
    def _check_build(data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        """Raise unless the table still names the fields these offsets came from, and does not
        already name a field this patch adds."""
        entries = read_field_table(data, table_va)
        by_name = {_read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, want in _FINGERPRINT.items():
            got = by_name.get(field)
            if got != want:
                raise ValueError(
                    f"unexpected build: PlayerTemplate.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        for field in _NAMES:
            if field in by_name:
                raise ValueError(
                    f"the PlayerTemplate table already names {field} - this patch is already "
                    "applied, or another patch has added the same field"
                )
        return entries

    @staticmethod
    def _code_offset(entries: tuple[Entry, ...]) -> int:
        return _TABLE_OFF + _table_span(entries)

    def _build_section(self, base_va: int, entries: tuple[Entry, ...]) -> bytes:
        """The block key, the row array, the constant, the format string, the rebuilt field
        table, then the code."""
        code = self._assemble(base_va, entries)
        table, strings = _table_bytes(base_va + _TABLE_OFF, entries, code.label_va("parse"))

        body = bytearray(_TABLE_OFF)
        struct.pack_into("<f", body, _CONST_OFF, 0.01)
        body[_FMT_OFF : _FMT_OFF + len(_FMT_BYTES)] = _FMT_BYTES
        body += table + strings
        assert len(body) == self._code_offset(entries)
        return bytes(body) + code.finish()

    def _assemble(self, base_va: int, entries: tuple[Entry, ...]) -> Asm:
        """The cave's code, laid out at the address it will occupy.

        :meth:`_build_section` takes the bytes and the field table, and :meth:`_edits` takes
        label addresses, from one layout - so nothing can be pointed at a routine that moved.
        """
        a = Asm(base_va + self._code_offset(entries))
        _emit_lookup(a, base_va + _ROWS_OFF)
        _emit_insert(a, base_va + _ROWS_OFF)
        _emit_block(a, base_va + _KEY_OFF)
        _emit_parse(a, base_va + _KEY_OFF)
        _emit_percent(a)
        _emit_deposit(a, base_va + _CONST_OFF)
        if self.hud:
            _emit_local_loss(a)
            _emit_text(a, base_va + _FMT_OFF)
        a.finish()  # resolve the internal branches, so `label_va` describes a real layout
        return a

    def _edits(
        self, data: bytes | bytearray, section_va: int, entries: tuple[Entry, ...], old_table: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """``(file offset, original bytes, patched bytes, note)`` for every engine byte this
        patch rewrites. One list so :meth:`apply` writes exactly what :meth:`verify` asserts."""
        labels = self._assemble(section_va, entries).label_va
        out: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int) -> int:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            return off

        # 1. repoint the PlayerTemplate field table at the rebuilt copy
        for ref_va, opcode in zip(
            PLAYER_TEMPLATE_FIELD_TABLE_REFS, PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            out.append(
                (
                    at(ref_va),
                    bytes([opcode]) + _u32(old_table),
                    bytes([opcode]) + _u32(section_va + _TABLE_OFF),
                    f"PlayerTemplate field table ref @0x{ref_va:08x}",
                )
            )

        # 2. record which faction the block being parsed is, for the field callbacks
        out.append(
            (
                at(PLAYER_TEMPLATE_BLOCK_KEY),
                PLAYER_TEMPLATE_BLOCK_KEY_BYTES,
                _jmp(PLAYER_TEMPLATE_BLOCK_KEY, labels("block"))
                + b"\x90" * (len(PLAYER_TEMPLATE_BLOCK_KEY_BYTES) - 5),
                "PlayerTemplate block key -> upkeep row key",
            )
        )

        # 3. the charge, on the finished inflation multiplier and before it is applied
        out.append(
            (
                at(AUTO_DEPOSIT_SCALE),
                AUTO_DEPOSIT_SCALE_BYTES,
                _jmp(AUTO_DEPOSIT_SCALE, labels("deposit"))
                + b"\x90" * (len(AUTO_DEPOSIT_SCALE_BYTES) - 5),
                "AutoDepositUpdate income -> upkeep multiplier",
            )
        )

        # 4. the third number in the palantir's command-point text
        if self.hud:
            out.append(
                (
                    at(PALANTIR_COMMAND_POINTS),
                    PALANTIR_COMMAND_POINTS_BYTES,
                    _jmp(PALANTIR_COMMAND_POINTS, labels("text"))
                    + b"\x90" * (len(PALANTIR_COMMAND_POINTS_BYTES) - 5),
                    "palantir command points -> upkeep suffix",
                )
            )
        return out

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--no-hud",
            action="store_true",
            help="leave the palantir's command-point text exactly as the stock engine draws it, "
            "instead of appending the current upkeep as (-N%%)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> CommandPointUpkeepPatch:
        return cls(hud=not args.no_hud)

    def ini_surface(self) -> Engine:
        """The two `PlayerTemplate` fields this patch adds. `UpkeepCommandPointStep` defaults to
        0, which is "no upkeep at all"; `UpkeepValues` is a whole-line list of percentages read
        the way the stock `ResourceModifierValues` beside it is, so it has no scalar default."""
        # Keyed by the `user_data` the cave's parse function switches on, so the INI types stated
        # here and the parse paths installed below cannot describe different fields.
        spelling = {0: ("Int", 0), 1: ("Int[]", None)}
        return Engine(
            fields=tuple(
                FieldDelta("PlayerTemplate", field, *spelling[user_data], patch=self.name)
                for field, user_data in FIELDS
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        problems: list[str] = []

        try:
            table_va = self._resolve(data)
            all_entries = read_field_table(data, table_va)
        except ValueError as exc:
            return [f"cannot read the PlayerTemplate field table: {exc}"]
        if len(all_entries) <= len(FIELDS):
            return ["the PlayerTemplate field table is too short to carry this patch"]
        entries = all_entries[: len(all_entries) - len(FIELDS)]

        by_name = {_read_cstring(data, e[0]): e for e in all_entries}
        parse_fn = self._assemble(section_va, entries).label_va("parse")
        for field, user_data in FIELDS:
            entry = by_name.get(field)
            if entry is None:
                problems.append(f"the PlayerTemplate table does not name {field}")
                continue
            if entry[1] != parse_fn:
                problems.append(f"{field} does not use the patch's own parse function")
            if entry[2] != user_data:
                problems.append(f"{field} carries userData {entry[2]}, expected {user_data}")
            if entry[3] != 0:
                problems.append(f"{field} has a non-zero template offset ({entry[3]:#x})")

        if bytes(data[section_off + _KEY_OFF : section_off + _KEY_OFF + 4]) != bytes(4):
            problems.append("the block-key slot is not zero-initialised")
        rows = section_off + _ROWS_OFF
        if bytes(data[rows : rows + ROWS * ROW_STRIDE]) != bytes(ROWS * ROW_STRIDE):
            problems.append("the faction table is not zero-initialised")
        fmt = section_off + _FMT_OFF
        if bytes(data[fmt : fmt + len(_FMT_BYTES)]) != _FMT_BYTES:
            problems.append(f"the format string is not {FORMAT!r}")

        # `_edits` only describes bytes this configuration *writes*, so with the HUD half off it
        # would not notice one that is on. Say so, rather than verifying a build this is not.
        if not self.hud:
            off = va_to_offset(data, PALANTIR_COMMAND_POINTS)
            if off is not None and bytes(data[off : off + len(PALANTIR_COMMAND_POINTS_BYTES)]) != (
                PALANTIR_COMMAND_POINTS_BYTES
            ):
                problems.append(
                    "the palantir command-point text is hooked, but this patch was built with "
                    "the HUD half off"
                )

        try:
            edits = self._edits(data, section_va, entries, table_va)
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems


def _jmp(at_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - (at_va + 5))
