"""The second-resource patch: a second per-player currency, granted, shown and spent.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below comes
from :mod:`sage_patch.addresses` and is derived in ``../docs/second-resource.md``.

**What this is.** A second spendable currency alongside gold needs four pieces: a counter per
player, a HUD element, an INI block that grants it, and an INI field that makes something *cost*
it. This patch is the first three - the **grant-and-show** half::

    AutoDepositUpdate
      DepositAmount  = 10                 ; stock: gold per tick
      DepositAmount2 = 2                  ; new:   resource 2 per tick

    PlayerTemplate FactionMen
      StartMoney   = 1000                 ; stock
      StartMoney2  = 50                   ; new

and the palantir reads ``1000 (50)``.

Nothing spends resource 2 and nothing gates on it, which is exactly what makes this phase cheap
and safe: no affordability path changes, so the AI cannot stall on a pool it cannot see and no
production decision moves. A mod can already use it as a scored or prestige currency, a
captured-point tally or a faction meter, read back out through `sage_live`.

**Where the counter lives.** ``UInt32 pool[MAX_PLAYER_COUNT]`` in the cave, indexed by
`Player::m_playerIndex`, rather than a grown `Player`. `MAX_PLAYER_COUNT` is 20 and
[cannot practically be raised](max-player-count.md), so the array is exact, and a side table
costs no struct growth, no constructor edit and no allocation-size hunt. Same shape as
`unique-production-id`'s `.prodid` counter.

> **A load resets the pool.** A cave-resident counter is not `Xfer`'d, so a savegame does not
> carry it. That is a narrow trade for a production id; for a resource *pool* it is a visible
> limitation, and it is stated here rather than hidden: **savegames are not supported by this
> patch**. Extending `Player::xfer` is a savegame format change, and is the largest single
> thing this patch does not do.

**Seeding, and why `Player::init` is the only right place.** The pool has to be zeroed on a new
game *and* seeded per faction, and `Player::init` does exactly that for gold - one call per slot,
from `PlayerList`'s own reset. The hook is at the function's **entry**, not at the money block:
the reset calls `init` on all twenty slots with a **NULL** template, and the money block sits
inside the `template != NULL` branch, so a hook there would leave an unused slot carrying the
previous game's number. At the entry, a NULL template means "seed 0", which is the clear.

**Where `DepositAmount2` lives, for no bytes.** `AutoDepositUpdate`'s `ModuleData` is 0x24 bytes
whose last two fields are `Bool`s at +0x20/+0x21, so **+0x22..+0x23 is alignment padding** and a
`UInt16` fits with no growth at all - the same argument `terrain-resource-exp` makes for its
`Bool` in +0x16. `operator new` does not zero the block, so the field still needs initialising,
and the constructor's two byte stores (`mov [esi+0x20], bl` / `mov [esi+0x21], bl`, six bytes)
rewrite as the single `mov [esi+0x20], ebx` with `ebx` already zero - three bytes for six, and
that one dword store clears the padding on the way past. The default therefore costs nothing.

**Where `StartMoney2` lives, and why not on the template.** `PlayerTemplate` is 0x1DC bytes with
no hole. The apparent gap at +0x34 is not one: it is the `Money` subobject's own
`m_playerIndex`, read by `Player::init` at `0x006B0545` into `Player+0x98`. So the per-faction
value goes in the cave, keyed by the template's `NameKeyType` at +0x10 - the one stable identity
a template has, and the key `PlayerTemplateStore::findPlayerTemplate` itself matches on. The key
is not readable from the instance a field callback sees: **all three parse paths write +0x10
after `initFromINI` returns**, and a new block is parsed into a stack temporary besides. So a
hook records it before the paths branch, and the field callback files against it.

That is `command-point-upkeep`'s mechanism, for `command-point-upkeep`'s reasons, and it carries
the same three consequences: no savegame change and no init hook for the *rows* (they are
INI-derived and rebuilt on every load), an override block merges rather than replaces, and a
missing row is "start at 0" rather than a wrong number.

**Composing with `command-point-upkeep`.** The two patches both need a `PlayerTemplate` block key
and both rebuild the `PlayerTemplate` field table, so the pair is worth stating explicitly:

* **The block-key hooks are different instructions.** `command-point-upkeep` takes the pair at
  `0x005FE886`; this takes the `mov ecx, [store]` at `0x005FE880` immediately before it. Both do
  nothing but copy `eax`, which already holds the key at both addresses, so neither reads what
  the other writes.
* **The field table is read live, from its own reference**, so whichever patch is applied second
  rebuilds the first one's table with its own row appended, in either order.

**The display costs no `.apt` at all.** `APT:PalantirResources` looks like a data binding - the
HUD constructor really does register `Palantir/ResourceBar/Resources/` against a pointer into its
own members - but the *text* is separately formatted and pushed by the engine every refresh
(`0x006D56E1` builds `"%d"` and calls `TheAptPlayer::setValue`). So a mod's `.csf` entry of that
name is a design-time placeholder the engine overwrites, and a second number is one more vararg
on a call the engine already makes: no movie edit, no `.csf` edit, and no second binding. That is
`command-point-upkeep`'s trick on the other readout, and it is why this half shipped with the
mechanic rather than waiting on `sage_apt`.

Two things follow from the text being *cached*:

* **The refresh filter has to widen.** The palantir only rebuilds the string when the number it
  last pushed changed, so a second number needs its own comparison or the bracket shows whatever
  it said the last time gold moved.
* **The bracket appears only when the mod uses the resource**, decided at INI load by a flag both
  parse functions raise. Deciding it from the pool instead would make the readout change shape
  mid-game, which reads as a bug. `--no-hud` drops the display entirely and leaves the mechanic.

**What this phase does not cover.** `TerrainResourceBehavior` - the *other* income module, and
the one Edain uses more for resource spots - gets no `DepositAmount2`. Its `ModuleData` has a
single spare padding byte, already claimed by `terrain-resource-exp`, so covering it means
growing the struct rather than reusing a hole, which is a job of its own.

> **Every peer must run the same patched binary** as soon as anything reacts to the pool. Today
> nothing in the *simulation* does - the counter is written, and read only by the local client's
> HUD - so a patched and an unpatched client stay in sync on *this* patch alone. Do not rely on
> that: the moment a mod uses the number for anything, it is simulation state.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    ASCII_STRING_FORMAT,
    AUTO_DEPOSIT_DEPOSIT,
    AUTO_DEPOSIT_DEPOSIT_BYTES,
    AUTO_DEPOSIT_DEPOSIT_RESUME,
    AUTO_DEPOSIT_FIELD_TABLE_REF_OPCODES,
    AUTO_DEPOSIT_FIELD_TABLE_REFS,
    AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS,
    AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS_BYTES,
    AUTO_DEPOSIT_MODULE_DATA_ESI,
    BUILD_GATE_AFFORD,
    BUILD_GATE_AFFORD_BYTES,
    BUILD_GATE_AFFORD_OK,
    BUILD_GATE_AFFORD_REFUSE,
    BUILD_GATE_NOT_ENOUGH_MONEY,
    BUILD_GATE_TEMPLATE_EBP,
    INI_NEXT_TOKEN_OR_NULL,
    INI_PARSE_UNSIGNED_SHORT,
    INI_SCAN_INT,
    MAX_PLAYER_COUNT,
    MONEY_DEPOSIT,
    MONEY_WITHDRAW,
    OBJECT_FIELD_TABLE_REF_OPCODES,
    OBJECT_FIELD_TABLE_REFS,
    PALANTIR_RESOURCES,
    PALANTIR_RESOURCES_BYTES,
    PALANTIR_RESOURCES_CACHE,
    PALANTIR_RESOURCES_CACHE_BYTES,
    PALANTIR_RESOURCES_CACHE_PUSH,
    PALANTIR_RESOURCES_CACHE_SKIP,
    PALANTIR_RESOURCES_DONE,
    PALANTIR_RESOURCES_RESUME,
    PLAYER_INDEX,
    PLAYER_INIT_ENTRY,
    PLAYER_INIT_ENTRY_BYTES,
    PLAYER_INIT_ENTRY_RESUME,
    PLAYER_LIST_GET_LOCAL_PLAYER,
    PLAYER_TEMPLATE_BLOCK_KEY_EARLY,
    PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES,
    PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME,
    PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
    PLAYER_TEMPLATE_FIELD_TABLE_REFS,
    PLAYER_TEMPLATE_NAME_KEY,
    PLAYER_TEMPLATE_RESOURCE_VALUES,
    PRODUCTION_WITHDRAW,
    PRODUCTION_WITHDRAW_BYTES,
    PRODUCTION_WITHDRAW_PLAYER_EBP,
    PRODUCTION_WITHDRAW_RESUME,
    PRODUCTION_WITHDRAW_TEMPLATE_EBP,
    THE_PLAYER_LIST,
    THING_TEMPLATE_BUILD_COST,
    THING_TEMPLATE_COPY_ID,
    THING_TEMPLATE_COPY_ID_BYTES,
    THING_TEMPLATE_COPY_ID_RESUME,
    TOOLTIP_COST_BUILD,
    TOOLTIP_COST_BUILD_RESUME,
    TOOLTIP_COST_BYTES,
    TOOLTIP_COST_REVIVE,
    TOOLTIP_COST_REVIVE_RESUME,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_DTOR,
    UNICODE_STRING_FORMAT,
)
from ..asm import JA, JAE, JBE, JE, JGE, JL, JNC, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

# `read_field_table` and `resolve_table` are generic field-table helpers that happen to live in
# the patch that needed them first. This is a code import only.
from .hero_mana import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "COST_FIELD",
    "SUFFIX",
    "COST_ROWS",
    "COST_STRIDE",
    "DEPOSIT_FIELD",
    "FORMAT",
    "DEPOSIT_OFFSET",
    "ROWS",
    "ROW_STRIDE",
    "SECTION_NAME",
    "START_FIELD",
    "SecondResourcePatch",
]

SECTION_NAME = ".res2"  # 8 chars max: the PE name field truncates silently past 8

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds code, two
# rebuilt field tables, the per-player pool and a row array written at INI load.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The `AutoDepositUpdate` field this patch adds, and the `ModuleData` padding it lands in.
DEPOSIT_FIELD = "DepositAmount2"
DEPOSIT_OFFSET = 0x22

#: The `PlayerTemplate` field this patch adds. It is stored in the cave, not on the template, so
#: its table entry carries offset 0 and its parse function is the cave's own.
START_FIELD = "StartMoney2"

#: The `Object` field this patch adds: what a thing costs in resource 2 to build or recruit.
#: Stored in the cave keyed by `ThingTemplate *`, because the template has no hole - the 2-byte
#: 2-byte gap at +0x5E8 that looks like one is the template's engine-assigned id.
COST_FIELD = "BuildCost2"

#: Rows in the faction table. A power of two so the index fold is an `and`. Edain defines ~40
#: `PlayerTemplate` blocks; 128 leaves room for a mod that defines many more.
ROWS = 128

#: ``{ UnsignedInt key; UnsignedInt start; }``
ROW_STRIDE = 8

#: Rows in the cost table, keyed by `ThingTemplate *`. Only objects that actually name
#: `BuildCost2` claim one, but the ceiling is sized well past any plausible mod because
#: **overflowing it makes a unit silently free** rather than merely unpriced - Edain alone loads
#: 11,143 templates, and 4096 is 32KB of cave for a failure mode nobody would diagnose.
COST_ROWS = 4096

#: ``{ ThingTemplate *tmpl; UnsignedInt cost; }``
COST_STRIDE = 8

_ROWS_MASK = ROWS - 1
_COST_MASK = COST_ROWS - 1

#: ``1000 (50)`` - the palantir's own number, then the second pool. **8-bit**, because the
#: resource text is built as an `AsciiString` and only widened on the way into the movie.
FORMAT = "%d (%d)"
_FMT_BYTES = FORMAT.encode("ascii") + b"\x00"

#: `` (25)`` - what a priced button's cost line gains. **UTF-16**, unlike the palantir's:
#: a description is built out of `UnicodeString`s all the way down.
SUFFIX = " (%d)"
_SUFFIX_BYTES = SUFFIX.encode("utf-16-le") + b"\x00\x00"

_KEY_OFF = 0x00  # the name key of the PlayerTemplate block currently being parsed
_INUSE_OFF = 0x04  # set at INI load when any block gives the resource a non-zero value
_SHOWN_OFF = 0x08  # the last pool value pushed to the palantir, for the refresh filter
_POOL_OFF = 0x10  # UInt32 pool[MAX_PLAYER_COUNT]
_ROWS_OFF = _POOL_OFF + MAX_PLAYER_COUNT * 4
_COST_OFF = _ROWS_OFF + ROWS * ROW_STRIDE
_FMT_OFF = _COST_OFF + COST_ROWS * COST_STRIDE
_SUFFIX_OFF = _FMT_OFF + len(_FMT_BYTES) + (-len(_FMT_BYTES) % 4)
_DEPOSIT_TABLE_OFF = _SUFFIX_OFF + len(_SUFFIX_BYTES) + (-len(_SUFFIX_BYTES) % 4)

#: Names each table must carry at these offsets, or this is not the build these addresses were
#: derived against. Checked by name rather than by count, so the check survives another patch
#: having extended the same table first.
_DEPOSIT_FINGERPRINT = {"DepositAmount": 0x0C, "GiveNoXP": 0x20, "OnlyWhenGarrisoned": 0x21}
_OBJECT_FINGERPRINT = {"BuildCost": THING_TEMPLATE_BUILD_COST, "RefundValue": 0x5EC}
_TEMPLATE_FINGERPRINT = {
    "ResourceModifierValues": PLAYER_TEMPLATE_RESOURCE_VALUES,
    "MultiSelectionPortrait": 0x1D8,
}


@dataclass(frozen=True)
class _Table:
    """One INI block this patch appends a field to.

    Three tables end up in the cave laid end to end, and every one of them is located from its
    own live reference rather than from a stock constant - so the patch appends to whatever is
    there, whichever other patch rebuilt it first.
    """

    block: str
    refs: tuple[int, ...]
    opcodes: tuple[int, ...]
    fingerprint: dict[str, int]
    field: str
    parse_label: str
    #: The offset the new row carries. 0 means the value is not stored on the instance at all -
    #: it goes in one of the cave's row tables, because neither `PlayerTemplate` nor
    #: `ThingTemplate` has a hole to put it in.
    offset: int


_TABLES: tuple[_Table, ...] = (
    _Table(
        "AutoDepositUpdate",
        AUTO_DEPOSIT_FIELD_TABLE_REFS,
        AUTO_DEPOSIT_FIELD_TABLE_REF_OPCODES,
        _DEPOSIT_FINGERPRINT,
        DEPOSIT_FIELD,
        "dep_parse",
        DEPOSIT_OFFSET,
    ),
    _Table(
        "PlayerTemplate",
        PLAYER_TEMPLATE_FIELD_TABLE_REFS,
        PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
        _TEMPLATE_FINGERPRINT,
        START_FIELD,
        "parse",
        0,
    ),
    _Table(
        "Object",
        OBJECT_FIELD_TABLE_REFS,
        OBJECT_FIELD_TABLE_REF_OPCODES,
        _OBJECT_FINGERPRINT,
        COST_FIELD,
        "cost_parse",
        0,
    ),
)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> int:
    """A signed byte displacement as the unsigned byte that encodes it."""
    return value & 0xFF


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.


def _emit_probe(a: Asm, tag: str, rows_va: int, *, claim: bool) -> None:
    """An open-addressed probe of the faction table, keyed by the name key in ``eax``.

    Hash the key, walk forward over occupied slots, stop at the key or at an empty one. Entries
    are never removed, so a run of occupied slots is never broken and the walk is exact. Returns
    the row in `eax`, or 0 when the key is absent (lookup), when the table is full (insert), or
    when the key is 0 - a full table degrades a faction to "start at 0" rather than failing the
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
        a.emit(0x83, 0x62, 0x04, 0x00)  # and dword ptr [edx+4], 0   ; start
    else:
        a.emit(0x31, 0xC0)  # xor eax, eax               ; absent
        a.jmp(f"{tag}_out")
    a.label(f"{tag}_hit")
    a.emit(0x8B, 0xC2)  # mov eax, edx
    a.label(f"{tag}_out")
    a.emit(0x5A, 0x59, 0x5B)  # pop edx / pop ecx / pop ebx
    a.emit(0xC3)  # ret


def _emit_lookup(a: Asm, rows_va: int) -> None:
    """``lookup``: `eax` = a name key, `eax` = its row or 0. Pure; the seed path calls it."""
    a.label("lookup")
    _emit_probe(a, "lu", rows_va, claim=False)


def _emit_insert(a: Asm, rows_va: int) -> None:
    """``insert``: as ``lookup``, but claims an empty slot. Only ever runs at INI load."""
    a.label("insert")
    _emit_probe(a, "in", rows_va, claim=True)


def _emit_block(a: Asm, key_va: int) -> None:
    """The hook that records which faction is being parsed.

    `eax` already holds the block's name key here - the displaced instruction is the load of the
    template store, one instruction before `command-point-upkeep`'s own hook - so recording it
    is one store and clobbers nothing.
    """
    a.label("block")
    a.emit(0xA3, _u32(key_va))  # mov [g_key], eax
    a.emit(PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES)  # the displaced mov ecx, [store]
    a.jmp_absolute(PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME)


def _emit_parse(a: Asm, key_va: int, inuse_va: int) -> None:
    """`StartMoney2`'s parse function.

    cdecl `(INI*, void *instance, void *store, const void *userData)`, the shape the field-parse
    dispatcher calls and the shape the stock `INI::parseInt` has. `instance` and `store` are
    ignored - the table entry carries offset 0, so nothing is written into the template at all.

    **The token is always consumed even when there is no row to put it in**, so a full table or
    a missing block key cannot leave the parser mid-line. A non-zero value raises the in-use flag
    whether or not there was a row to store it in, because the flag describes *the mod*, not the
    faction.
    """
    a.label("parse")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x53)  # push ebx
    a.emit(0x31, 0xDB)  # xor ebx, ebx                 ; the row, 0 until claimed
    a.emit(0xA1, _u32(key_va))  # mov eax, [g_key]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "sm_read")
    a.call("insert")
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.label("sm_read")
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]             ; the INI
    a.emit(0x6A, 0x00)  # push 0
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "sm_out")
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]
    a.emit(0x50)  # push eax                     ; the token
    a.call_absolute(INI_SCAN_INT)  # ret 4
    a.emit(0x83, 0xF8, 0x00)  # cmp eax, 0
    a.jcc(JGE, "sm_positive")
    a.emit(0x31, 0xC0)  # xor eax, eax                 ; a negative start is 0
    a.jmp("sm_row")
    a.label("sm_positive")
    a.jcc(JE, "sm_row")
    a.emit(0xC7, 0x05, _u32(inuse_va), _u32(1))  # mov dword [g_inuse], 1
    a.label("sm_row")
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "sm_out")  # no row: parsed and dropped
    a.emit(0x89, 0x43, 0x04)  # mov [ebx+4], eax             ; row->start
    a.label("sm_out")
    a.emit(0x5B)  # pop ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret                          ; cdecl - the dispatcher cleans


def _emit_init(a: Asm, pool_va: int) -> None:
    """The seed, at the entry of `Player::init`.

    `ecx` is the `Player` and `[ebp+8]` its `PlayerTemplate`, which is **NULL** on the reset that
    walks all twenty slots - and a NULL template seeds 0, which is the per-game clear. Assigns
    rather than adds, so re-initialising a slot cannot accumulate.
    """
    a.label("init")
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0x31, 0xD2)  # xor edx, edx                 ; the seed
    a.emit(0x8B, 0x45, 0x08)  # mov eax, [ebp+8]             ; the PlayerTemplate
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pi_seed")  # no faction -> 0
    a.emit(0x8B, 0x40, PLAYER_TEMPLATE_NAME_KEY)  # mov eax, [eax+0x10]  ; its name key
    a.call("lookup")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pi_seed")  # no row -> 0
    a.emit(0x8B, 0x50, 0x04)  # mov edx, [eax+4]             ; row->start
    a.label("pi_seed")
    a.emit(0x8B, 0x41, PLAYER_INDEX)  # mov eax, [ecx+0x54]  ; m_playerIndex
    a.emit(0x83, 0xF8, MAX_PLAYER_COUNT)  # cmp eax, 20
    a.jcc(JAE, "pi_done")  # unsigned: -1 is out of range too
    a.emit(0x89, 0x14, 0x85, _u32(pool_va))  # mov [pool + eax*4], edx
    a.label("pi_done")
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.emit(PLAYER_INIT_ENTRY_BYTES)  # the displaced frame setup and template load
    a.jmp_absolute(PLAYER_INIT_ENTRY_RESUME)


def _emit_grant(a: Asm, pool_va: int) -> None:
    """The grant, on `AutoDepositUpdate`'s own income tick.

    The hook replaces the whole five-byte `call Money::deposit`, so the cave makes that call
    itself and then credits resource 2 from the same module. `esi` is the module (`ModuleData` at
    `[esi-0x0C]`) and `edi` the controlling `Player`; both survive the deposit, and `edi` stops
    being the player at the resume address.

    **The grant is flat.** Neither the `UpgradeBonusPercent` bonus nor the difficulty handicap
    that scale the gold deposit apply to it, so `DepositAmount2 = N` means N per tick and nothing
    else. That is the honest primitive for a pool nothing prices against yet.
    """
    a.label("grant")
    a.call_absolute(MONEY_DEPOSIT)  # the displaced call
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0x8B, 0x46, _i8(AUTO_DEPOSIT_MODULE_DATA_ESI))  # mov eax, [esi-0xc]
    a.emit(0x0F, 0xB7, 0x40, DEPOSIT_OFFSET)  # movzx eax, word ptr [eax+0x22]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "gr_done")  # 0 (the default) == no second income
    a.emit(0x8B, 0x4F, PLAYER_INDEX)  # mov ecx, [edi+0x54]  ; m_playerIndex
    a.emit(0x83, 0xF9, MAX_PLAYER_COUNT)  # cmp ecx, 20
    a.jcc(JAE, "gr_done")
    a.emit(0x01, 0x04, 0x8D, _u32(pool_va))  # add [pool + ecx*4], eax
    a.jcc(JNC, "gr_done")
    a.emit(0xC7, 0x04, 0x8D, _u32(pool_va), _u32(0xFFFFFFFF))  # saturate rather than wrap
    a.label("gr_done")
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.jmp_absolute(AUTO_DEPOSIT_DEPOSIT_RESUME)


def _emit_cost_probe(a: Asm, tag: str, rows_va: int, *, claim: bool) -> None:
    """An open-addressed probe of the cost table, keyed by the `ThingTemplate *` in ``ecx``.

    The same walk as the faction probe, with one difference that matters: **the key is a pointer**,
    so its low bits are dead (templates are allocated 0x6B8 apart and 4-byte aligned). Folding the
    raw pointer would pile every template into a handful of slots; `shr 4` first is what makes the
    table behave like a hash table rather than a linked list. That is `hero-mana`'s fold, for
    `hero-mana`'s reason - it keys the same objects.

    Returns the row in `eax`, or 0 when the key is absent, when the table is full, or when the
    pointer is null. Preserves everything but `eax`.
    """
    a.emit(0x52, 0x57)  # push edx / push edi
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, f"{tag}_none")  # a null template has no cost
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.emit(0xC1, 0xE8, 0x04)  # shr eax, 4                 ; drop the dead alignment bits
    a.emit(0x25, _u32(_COST_MASK))  # and eax, COST_ROWS-1
    a.emit(0xBF, _u32(COST_ROWS))  # mov edi, COST_ROWS         ; probe budget
    a.label(f"{tag}_probe")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(0x6B, 0xD2, COST_STRIDE)  # imul edx, edx, COST_STRIDE
    a.emit(0x81, 0xC2, _u32(rows_va))  # add edx, rows
    a.emit(0x83, 0x3A, 0x00)  # cmp dword ptr [edx], 0
    a.jcc(JE, f"{tag}_empty")
    a.emit(0x39, 0x0A)  # cmp dword ptr [edx], ecx
    a.jcc(JE, f"{tag}_hit")
    a.emit(0x40)  # inc eax
    a.emit(0x25, _u32(_COST_MASK))  # and eax, COST_ROWS-1
    a.emit(0x4F)  # dec edi
    a.jcc(JNE, f"{tag}_probe")
    a.label(f"{tag}_none")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.jmp(f"{tag}_out")
    a.label(f"{tag}_empty")
    if claim:
        a.emit(0x89, 0x0A)  # mov [edx], ecx             ; claim the slot for this template
        a.emit(0x83, 0x62, 0x04, 0x00)  # and dword ptr [edx+4], 0
    else:
        a.emit(0x31, 0xC0)  # xor eax, eax               ; absent
        a.jmp(f"{tag}_out")
    a.label(f"{tag}_hit")
    a.emit(0x8B, 0xC2)  # mov eax, edx
    a.label(f"{tag}_out")
    a.emit(0x5F, 0x5A)  # pop edi / pop edx
    a.emit(0xC3)  # ret


def _emit_cost_row(a: Asm, rows_va: int) -> None:
    """``cost_row``: `ecx` = a `ThingTemplate *`, `eax` = its row or 0. Pure."""
    a.label("cost_row")
    _emit_cost_probe(a, "cr", rows_va, claim=False)


def _emit_cost_claim(a: Asm, rows_va: int) -> None:
    """``cost_claim``: as ``cost_row``, but claims an empty slot. INI load and the copy only."""
    a.label("cost_claim")
    _emit_cost_probe(a, "cq", rows_va, claim=True)


def _emit_cost_lookup(a: Asm, rows_va: int) -> None:
    """``cost_of``: `ecx` = a `ThingTemplate *`, `eax` = its `BuildCost2`, 0 when it has none.

    The one reader every enforcement site shares, so "no row" and "a row of 0" are the same
    answer and an object that never names the field is priced exactly as it is today.
    """
    a.label("cost_of")
    a.emit(0x51)  # push ecx
    a.call("cost_row")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "co_zero")
    a.emit(0x8B, 0x40, 0x04)  # mov eax, [eax+4]
    a.jmp("co_out")
    a.label("co_zero")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("co_out")
    a.emit(0x59)  # pop ecx
    a.emit(0xC3)  # ret


def _emit_cost_parse(a: Asm, rows_va: int, inuse_va: int) -> None:
    """`Object.BuildCost2`'s parse function.

    cdecl `(INI*, void *instance, void *store, const void *userData)`. **`instance` is read, not
    `store`**: the table entry carries offset 0 so the two coincide today, but `store` is
    `instance + offset + whatever extra offset the block's field parse was registered with`, and
    only `instance` is guaranteed to be the `ThingTemplate` itself.

    The token is always consumed, so a full table cannot leave the parser mid-line, and a negative
    cost is clamped to 0 rather than wrapping into a fortune.
    """
    a.label("cost_parse")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x53)  # push ebx
    a.emit(0x31, 0xDB)  # xor ebx, ebx                 ; the row, 0 until claimed
    a.emit(0x8B, 0x4D, 0x0C)  # mov ecx, [ebp+0xc]           ; the ThingTemplate
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "bc_read")
    a.call("cost_claim")
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.label("bc_read")
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]             ; the INI
    a.emit(0x6A, 0x00)  # push 0
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "bc_out")
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]
    a.emit(0x50)  # push eax                     ; the token
    a.call_absolute(INI_SCAN_INT)  # ret 4
    a.emit(0x83, 0xF8, 0x00)  # cmp eax, 0
    a.jcc(JGE, "bc_positive")
    a.emit(0x31, 0xC0)  # xor eax, eax                 ; a negative cost is free, not a fortune
    a.jmp("bc_row")
    a.label("bc_positive")
    a.jcc(JE, "bc_row")
    a.emit(0xC7, 0x05, _u32(inuse_va), _u32(1))  # mov dword [g_inuse], 1
    a.label("bc_row")
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "bc_out")  # no row: parsed and dropped
    a.emit(0x89, 0x43, 0x04)  # mov [ebx+4], eax             ; row->cost
    a.label("bc_out")
    a.emit(0x5B)  # pop ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret                          ; cdecl - the dispatcher cleans


def _emit_cost_copy(a: Asm) -> None:
    """Carry a template's cost across `ThingTemplate::copyFrom`.

    An INI override block (`map.ini` re-declaring an object, or a mod file loaded later) is parsed
    into a **fresh** template that is copied from the old one - and the copy is field by field, so
    anything keyed on the pointer is lost unless it rides the same call. This is the engine's own
    id copy, in the middle of that function, with `eax` the source and `ebx` the destination.

    `hero-mana` rides the same copy by retargeting its *call site*; hooking the body instead
    shares no byte with that, and also covers any caller that is not that one call.
    """
    a.label("cost_copy")
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax                 ; the source template
    a.call("cost_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "cc_done")  # nothing to carry
    a.emit(0x89, 0xC2)  # mov edx, eax                 ; the cost
    a.emit(0x8B, 0xCB)  # mov ecx, ebx                 ; the destination template
    a.emit(0x52)  # push edx
    a.call("cost_claim")
    a.emit(0x5A)  # pop edx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "cc_done")  # the table is full: the copy silently costs nothing
    a.emit(0x89, 0x50, 0x04)  # mov [eax+4], edx
    a.label("cc_done")
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.emit(THING_TEMPLATE_COPY_ID_BYTES)  # the displaced id copy
    a.jmp_absolute(THING_TEMPLATE_COPY_ID_RESUME)


def _emit_gate(a: Asm, pool_va: int) -> None:
    """The affordability gate, in `BuildAssistant`'s `+0x64` predicate.

    This is the one comparison the ControlBar, `queueCreateUnit` and every script path share, so
    one hook refuses everything a player cannot pay for. `eax` is the gold cost, `ebx` gold plus
    the frame's allowance, `esi` the `Player` and `[ebp+0xC]` the `ThingTemplate`.

    **Refusal reuses the engine's own code 2, "not enough money"** - so the button tint, the
    refusal sound and the message are the ones the player already knows, with no new UI at all.

    The AI reaches this predicate too, and that is fine by construction: AI-only unit variants
    leave `BuildCost2` at 0, and a cost of 0 sails through without ever reading the pool.
    """
    a.label("gate")
    a.emit(0x3B, 0xC3)  # cmp eax, ebx                 ; the displaced gold test
    a.jcc(JA, "gt_refuse")  # short of gold: the stock answer
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x8B, 0x4D, BUILD_GATE_TEMPLATE_EBP)  # mov ecx, [ebp+0xc]  ; the ThingTemplate
    a.call("cost_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "gt_ok")  # costs no resource 2: nothing to check
    a.emit(0x8B, 0x4E, PLAYER_INDEX)  # mov ecx, [esi+0x54]  ; m_playerIndex
    a.emit(0x83, 0xF9, MAX_PLAYER_COUNT)  # cmp ecx, 20
    a.jcc(JAE, "gt_short")  # no addressable pool: treat as broke, never as free
    a.emit(0x3B, 0x04, 0x8D, _u32(pool_va))  # cmp eax, [pool + ecx*4]
    a.jcc(JBE, "gt_ok")
    a.label("gt_short")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.label("gt_refuse")
    a.emit(0x6A, BUILD_GATE_NOT_ENOUGH_MONEY)  # push 2
    a.jmp_absolute(BUILD_GATE_AFFORD_REFUSE)
    a.label("gt_ok")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.jmp_absolute(BUILD_GATE_AFFORD_OK)


def _emit_spend(a: Asm, pool_va: int) -> None:
    """The charge, on `queueCreateUnit`'s own withdrawal.

    The hook replaces the whole five-byte `call Money::withdraw`, so the cave makes that call
    itself and then debits resource 2 from the same player. `[ebp-0x0C]` is the `Player` and
    `[ebp+8]` the `ThingTemplate`; `ecx` has already become `&player->m_money` by this point,
    which is why the player is read from the frame and not from a register.

    **Clamps at zero rather than going negative.** `Money::withdraw` does the same for gold - it
    takes what is there and never refuses - so affordability is decided upstream, at the gate, and
    a debit that arrives anyway must not wrap a `UInt32` into four billion.
    """
    a.label("spend")
    a.call_absolute(MONEY_WITHDRAW)  # the displaced call
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0x8B, 0x4D, _i8(PRODUCTION_WITHDRAW_TEMPLATE_EBP))  # mov ecx, [ebp+8]
    a.call("cost_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "sp_done")  # costs no resource 2
    a.emit(0x8B, 0x4D, _i8(PRODUCTION_WITHDRAW_PLAYER_EBP))  # mov ecx, [ebp-0xc]  ; the Player
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "sp_done")
    a.emit(0x8B, 0x49, PLAYER_INDEX)  # mov ecx, [ecx+0x54]  ; m_playerIndex
    a.emit(0x83, 0xF9, MAX_PLAYER_COUNT)  # cmp ecx, 20
    a.jcc(JAE, "sp_done")
    a.emit(0x3B, 0x04, 0x8D, _u32(pool_va))  # cmp eax, [pool + ecx*4]
    a.jcc(JBE, "sp_take")
    a.emit(0x8B, 0x04, 0x8D, _u32(pool_va))  # mov eax, [pool + ecx*4]  ; take what is there
    a.label("sp_take")
    a.emit(0x29, 0x04, 0x8D, _u32(pool_va))  # sub [pool + ecx*4], eax
    a.label("sp_done")
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.jmp_absolute(PRODUCTION_WITHDRAW_RESUME)


def _emit_tip(a: Asm, suffix_va: int) -> None:
    """``tip``: append ``" (N)"`` to the cost line in `eax`, for the template in `ecx`.

    The engine has just built the localized ``Cost: 100`` into a `UnicodeString` and is about to
    concatenate it onto the description. Appending here rather than rebuilding the line is what
    keeps the label localized: the `.csf` string is the mod's, and this only adds to what it
    produced. **No `.csf` edit and no new tooltip key.**

    Builds the suffix into a `UnicodeString` temporary in its own frame, concatenates it, and
    destroys it - `UNICODE_STRING_FORMAT` allocates, so the destructor is not optional. A cost of
    0 leaves the line exactly as the engine made it and never constructs anything.

    Preserves `eax`, which the displaced pushes still need.
    """
    a.label("tip")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x83, 0xEC, 0x04)  # sub esp, 4                   ; [ebp-4] = the suffix
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0x83, 0x65, 0xFC, 0x00)  # and dword [ebp-4], 0        ; an empty UnicodeString
    a.call("cost_of")  # ecx is still the template
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "tp_done")  # costs no resource 2: the stock line
    a.emit(0x50)  # push eax                     ; vararg - the cost
    a.emit(0x68, _u32(suffix_va))  # push L" (%d)"
    a.emit(0x8D, 0x45, 0xFC)  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.call_absolute(UNICODE_STRING_FORMAT)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 12                  ; cdecl - we clean
    a.emit(0x8D, 0x45, 0xFC)  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax                     ; src - the suffix
    a.emit(0xFF, 0x75, 0xF8)  # push dword [ebp-8]           ; dest - the saved cost line
    a.call_absolute(UNICODE_STRING_CONCAT)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x8D, 0x4D, 0xFC)  # lea ecx, [ebp-4]
    a.call_absolute(UNICODE_STRING_DTOR)  # thiscall, no arguments
    a.label("tp_done")
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax  ; the line, back where it was
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_tip_site(a: Asm, label: str, template_reg: int, resume_va: int) -> None:
    """One of the two cost lines that price a `ThingTemplate`.

    The two differ only in which register holds the template - `ebx` where a unit or structure is
    being priced, `esi` where a hero is - so each is a three-instruction stub in front of the
    shared body. ``template_reg`` is the ModRM byte of ``mov ecx, <reg>``.
    """
    a.label(label)
    a.emit(0x51)  # push ecx
    a.emit(0x8B, template_reg)  # mov ecx, <the ThingTemplate>
    a.call("tip")
    a.emit(0x59)  # pop ecx
    a.emit(TOOLTIP_COST_BYTES)  # the displaced pushes
    a.jmp_absolute(resume_va)


def _emit_deposit_parse(a: Asm, inuse_va: int) -> None:
    """`DepositAmount2`'s parse function: the stock `UInt16` one, plus the in-use flag.

    The parsing itself is entirely the engine's - the field lives in two bytes of `ModuleData`
    padding and `INI::parseUnsignedShort` is exactly the range check and word store that needs.
    The wrapper exists only to notice that *some* block gave the resource a non-zero value, which
    is what decides whether the palantir grows a second number **at load time**. Deciding it from
    the pool instead would make the readout change shape mid-game, which reads as a bug.

    cdecl throughout, so the four arguments are forwarded verbatim and cleaned by this frame.
    """
    a.label("dep_parse")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    for argument in (0x14, 0x10, 0x0C, 0x08):  # userData, store, instance, INI - last first
        a.emit(0xFF, 0x75, argument)  # push dword [ebp+n]
    a.call_absolute(INI_PARSE_UNSIGNED_SHORT)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 16                  ; cdecl - we clean
    a.emit(0x8B, 0x45, 0x10)  # mov eax, [ebp+0x10]          ; store == ModuleData + 0x22
    a.emit(0x66, 0x83, 0x38, 0x00)  # cmp word ptr [eax], 0
    a.jcc(JE, "dp_out")
    a.emit(0xC7, 0x05, _u32(inuse_va), _u32(1))  # mov dword [g_inuse], 1
    a.label("dp_out")
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret


def _emit_local_pool(a: Asm, pool_va: int) -> None:
    """``local_pool``: `eax` = the local player's second resource, 0 when there is no local
    player or its index is out of range.

    Read-only, and read-only is required: this runs on the local client only, so a write here
    would be a desync. Preserves every register but `eax` and the flags.
    """
    a.label("local_pool")
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0x8B, 0x0D, _u32(THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "lp_out")
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)  # thiscall, no arguments
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "lp_out")
    a.emit(0x8B, 0x48, PLAYER_INDEX)  # mov ecx, [eax+0x54]  ; m_playerIndex
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0x83, 0xF9, MAX_PLAYER_COUNT)  # cmp ecx, 20
    a.jcc(JAE, "lp_out")  # unsigned: -1 is out of range too
    a.emit(0x8B, 0x04, 0x8D, _u32(pool_va))  # mov eax, [pool + ecx*4]
    a.label("lp_out")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.emit(0xC3)  # ret


def _emit_text(a: Asm, fmt_va: int, inuse_va: int) -> None:
    """A second number in the palantir's resource text: ``1000 (50)``.

    The engine builds that text with `AsciiString::format(L"%d", amount)` - cdecl, so the varargs
    are pushed last-first and the trailing `add esp` counts them. The hook therefore sits *before*
    the first vararg push, which is the only place a second one fits.

    Two displaced instructions, reordered but each executed exactly once on every path: the SEH
    state store first (it sets no flags and is needed on both), and the compare last on the stock
    path (so the `jl` at the resume address reads flags this hook produced).

    With the resource unused, or on the negative-amount branch the engine answers with a `" "`
    placeholder, the stock one-number call is emitted byte-identically.
    """
    a.label("text")
    a.emit(0xC7, 0x45, 0xFC, _u32(1))  # mov dword [ebp-4], 1   ; the displaced SEH state
    a.emit(0x83, 0x3D, _u32(inuse_va), 0x00)  # cmp dword [g_inuse], 0
    a.jcc(JE, "tx_plain")
    a.emit(0x83, 0x7D, 0x08, 0x00)  # cmp dword [ebp+8], 0
    a.jcc(JL, "tx_plain")  # a negative amount takes the stock placeholder
    a.call("local_pool")
    a.emit(0x50)  # push eax                     ; vararg 2 - the second resource
    a.emit(0xFF, 0x75, 0x08)  # push dword [ebp+8]           ; vararg 1 - the engine's own number
    a.emit(0x68, _u32(fmt_va))  # push "%d (%d)"
    a.emit(0x8D, 0x45, 0xF0)  # lea eax, [ebp-0x10]          ; the AsciiString
    a.emit(0x50)  # push eax
    a.call_absolute(ASCII_STRING_FORMAT)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 16                  ; two varargs, not one
    a.jmp_absolute(PALANTIR_RESOURCES_DONE)
    a.label("tx_plain")
    a.emit(0x83, 0x7D, 0x08, 0x00)  # the displaced compare, for the jl at the resume
    a.jmp_absolute(PALANTIR_RESOURCES_RESUME)


def _emit_refresh(a: Asm, shown_va: int, inuse_va: int) -> None:
    """Widen the refresh's change filter to notice the second resource too.

    The palantir only rebuilds its resource text when the number it last pushed has changed -
    `edi` against `[esi+0xC]`. A second number in the same string has to widen that test, or it
    shows whatever it happened to say the last time *gold* moved.

    `eax` is dead here on both edges (the next read of it, at the skip address, is a fresh load),
    so the comparison needs no register saved.
    """
    a.label("refresh")
    a.emit(0x83, 0x3D, _u32(inuse_va), 0x00)  # cmp dword [g_inuse], 0
    a.jcc(JE, "rf_stock")  # unused: the stock filter, exactly
    a.call("local_pool")
    a.emit(0x3B, 0x05, _u32(shown_va))  # cmp eax, [g_shown]
    a.jcc(JE, "rf_stock")
    a.emit(0xA3, _u32(shown_va))  # mov [g_shown], eax
    a.jmp_absolute(PALANTIR_RESOURCES_CACHE_PUSH)  # force the text, whatever gold did
    a.label("rf_stock")
    a.emit(0x3B, 0x7E, 0x0C)  # cmp edi, [esi+0xc]           ; the displaced compare
    a.jcc(JNE, "rf_push")  # its `je`, inverted, so both edges are absolute jumps
    a.jmp_absolute(PALANTIR_RESOURCES_CACHE_SKIP)
    a.label("rf_push")
    a.jmp_absolute(PALANTIR_RESOURCES_CACHE_PUSH)


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    return None if end < 0 else bytes(data[off : off + end]).decode("latin1")


def _table_bytes(
    table_va: int, entries: tuple[Entry, ...], name: str, parse_fn: int, offset: int
) -> tuple[bytes, bytes]:
    """A rebuilt field-parse table and its new name string.

    The stock entries pass through unchanged - by pointer, so every field already there keeps its
    own name string - then the new row, then the all-zero terminator the parser scans for. The
    string is padded so whatever follows stays dword-aligned.
    """
    table_size = (len(entries) + 2) * 16
    name_va = table_va + table_size
    strings = name.encode("ascii") + b"\x00"
    strings += b"\x00" * (-len(strings) % 4)

    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", name_va, parse_fn, 0, offset)
    table += struct.pack("<IIII", 0, 0, 0, 0)
    assert len(table) == table_size
    return bytes(table), bytes(strings)


def _table_span(entries: tuple[Entry, ...], name: str) -> int:
    """How many bytes a rebuilt table plus its padded name string occupies."""
    strings = len(name) + 1
    return (len(entries) + 2) * 16 + strings + (-strings % 4)


class SecondResourcePatch(Patch):
    """Give every player a second resource pool, granted per tick and seeded per faction.

    Adds `AutoDepositUpdate.DepositAmount2` and `PlayerTemplate.StartMoney2`, and shows the pool
    in brackets after the palantir's own number. Nothing *costs* the new resource - this is the
    grant-and-show half of the feature.

    ``hud`` (default on) is the bracket. Turning it off leaves the palantir's resource text
    exactly as the stock engine draws it, and leaves the mechanic untouched.
    """

    name = "second-resource"
    author = "officialNecro"
    description = (
        "A second per-player resource pool, granted by AutoDepositUpdate.DepositAmount2, seeded "
        "by PlayerTemplate.StartMoney2 and shown in brackets on the palantir (nothing costs it)"
    )

    def __init__(self, *, hud: bool = True):
        #: Append the pool to the palantir's resource readout, as ``1000 (50)``. Client-local
        #: either way - the text never enters the simulation - but a resource nobody can see is
        #: not much of a resource, so it is on by default.
        self.hud = hud

    def __str__(self) -> str:
        return self.name if self.hud else f"{self.name} (no hud)"

    def apply(self, data: bytearray) -> None:
        bases = self._resolve(data)
        tables = self._check_build(data, bases)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build_section(base, tables), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va, tables, bases):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _resolve(data: bytes | bytearray) -> tuple[int, ...]:
        """Every field table's base VA, as the image currently holds it, in `_TABLES` order.

        Read from the references that name them rather than from the stock constants, so the
        patch appends to whatever is live - which is what lets it compose with any other patch
        that has already rebuilt any of them - and so applying it twice fails cleanly instead of
        installing a second copy of every field.
        """
        return tuple(resolve_table(data, spec.refs, spec.opcodes, spec.block) for spec in _TABLES)

    @staticmethod
    def _check_build(
        data: bytes | bytearray, bases: tuple[int, ...]
    ) -> tuple[tuple[Entry, ...], ...]:
        """Raise unless every table still names the fields these offsets came from, and none
        already names a field this patch adds."""
        out: list[tuple[Entry, ...]] = []
        for spec, table_va in zip(_TABLES, bases, strict=True):
            entries = read_field_table(data, table_va)
            by_name = {_read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
            for field, want in spec.fingerprint.items():
                got = by_name.get(field)
                if got != want:
                    raise ValueError(
                        f"unexpected build: {spec.block}.{field} is at "
                        f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                    )
            if spec.field in by_name:
                raise ValueError(
                    f"the {spec.block} table already names {spec.field} - this patch is already "
                    "applied, or another patch has added the same field"
                )
            out.append(entries)
        return tuple(out)

    @staticmethod
    def _table_offsets(tables: tuple[tuple[Entry, ...], ...]) -> tuple[int, ...]:
        """Where each rebuilt table starts in the cave, laid end to end after the data."""
        offsets, cursor = [], _DEPOSIT_TABLE_OFF
        for spec, entries in zip(_TABLES, tables, strict=True):
            offsets.append(cursor)
            cursor += _table_span(entries, spec.field)
        return tuple(offsets)

    @classmethod
    def _code_offset(cls, tables: tuple[tuple[Entry, ...], ...]) -> int:
        offsets = cls._table_offsets(tables)
        return offsets[-1] + _table_span(tables[-1], _TABLES[-1].field)

    def _build_section(self, base_va: int, tables: tuple[tuple[Entry, ...], ...]) -> bytes:
        """The block key and flags, the pool, both row arrays, the format string, every rebuilt
        field table, then the code."""
        code = self._assemble(base_va, tables)
        body = bytearray(_DEPOSIT_TABLE_OFF)
        body[_FMT_OFF : _FMT_OFF + len(_FMT_BYTES)] = _FMT_BYTES
        body[_SUFFIX_OFF : _SUFFIX_OFF + len(_SUFFIX_BYTES)] = _SUFFIX_BYTES
        for spec, entries, offset in zip(_TABLES, tables, self._table_offsets(tables), strict=True):
            table, strings = _table_bytes(
                base_va + offset,
                entries,
                spec.field,
                code.label_va(spec.parse_label),
                spec.offset,
            )
            body += table + strings
        assert len(body) == self._code_offset(tables)
        return bytes(body) + code.finish()

    def _assemble(self, base_va: int, tables: tuple[tuple[Entry, ...], ...]) -> Asm:
        """The cave's code, laid out at the address it will occupy.

        :meth:`_build_section` takes the bytes and the field tables, and :meth:`_edits` takes
        label addresses, from one layout - so nothing can be pointed at a routine that moved.
        """
        a = Asm(base_va + self._code_offset(tables))
        _emit_lookup(a, base_va + _ROWS_OFF)
        _emit_insert(a, base_va + _ROWS_OFF)
        _emit_block(a, base_va + _KEY_OFF)
        _emit_parse(a, base_va + _KEY_OFF, base_va + _INUSE_OFF)
        _emit_deposit_parse(a, base_va + _INUSE_OFF)
        _emit_init(a, base_va + _POOL_OFF)
        _emit_grant(a, base_va + _POOL_OFF)
        _emit_cost_row(a, base_va + _COST_OFF)
        _emit_cost_claim(a, base_va + _COST_OFF)
        _emit_cost_lookup(a, base_va + _COST_OFF)
        _emit_cost_parse(a, base_va + _COST_OFF, base_va + _INUSE_OFF)
        _emit_cost_copy(a)
        _emit_gate(a, base_va + _POOL_OFF)
        _emit_spend(a, base_va + _POOL_OFF)
        # The local-pool read is the HUD's, so it is emitted with it - and only with it, so
        # `--no-hud` leaves no code that reads the local player at all.
        if self.hud:
            _emit_local_pool(a, base_va + _POOL_OFF)
            _emit_text(a, base_va + _FMT_OFF, base_va + _INUSE_OFF)
            _emit_refresh(a, base_va + _SHOWN_OFF, base_va + _INUSE_OFF)
            _emit_tip(a, base_va + _SUFFIX_OFF)
            _emit_tip_site(a, "tip_build", 0xCB, TOOLTIP_COST_BUILD_RESUME)  # mov ecx, ebx
            _emit_tip_site(a, "tip_revive", 0xCE, TOOLTIP_COST_REVIVE_RESUME)  # mov ecx, esi
        a.finish()  # resolve the internal branches, so `label_va` describes a real layout
        return a

    def _edits(
        self,
        data: bytes | bytearray,
        section_va: int,
        tables: tuple[tuple[Entry, ...], ...],
        bases: tuple[int, ...],
        *,
        table_refs: bool = True,
    ) -> list[tuple[int, bytes, bytes, str]]:
        """``(file offset, original bytes, patched bytes, note)`` for every engine byte this
        patch rewrites. One list so :meth:`apply` writes exactly what :meth:`verify` asserts.

        ``table_refs=False`` drops the field-table repoints. :meth:`verify` asks for that,
        because a repoint is the one edit here a *later* patch is entitled to overwrite: a second
        patch extending the same table rebuilds it including these rows - by pointer, so they stay
        the same rows with the same parse function - and points the reference at its own copy.
        What has to hold afterwards is that the live table still names these fields correctly,
        which `verify` checks directly, not that the reference still names this patch's copy.
        """
        labels = self._assemble(section_va, tables).label_va
        out: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int) -> int:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            return off

        def hook(va: int, old: bytes, target: str, note: str) -> None:
            out.append((at(va), old, _jmp(va, labels(target)) + b"\x90" * (len(old) - 5), note))

        # 1. repoint every field table at its rebuilt copy
        if table_refs:
            offsets = self._table_offsets(tables)
            for spec, old, offset in zip(_TABLES, bases, offsets, strict=True):
                for ref_va, opcode in zip(spec.refs, spec.opcodes, strict=True):
                    out.append(
                        (
                            at(ref_va),
                            bytes([opcode]) + _u32(old),
                            bytes([opcode]) + _u32(section_va + offset),
                            f"{spec.block} field table ref @0x{ref_va:08x}",
                        )
                    )

        # 2. clear the new ModuleData field in the constructor, for three bytes of the six the
        #    two Bool stores took
        out.append(
            (
                at(AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS),
                AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS_BYTES,
                bytes.fromhex("895e20") + b"\x90" * 3,  # mov [esi+0x20], ebx
                "AutoDepositUpdate ModuleData Bool defaults -> one dword clear",
            )
        )

        # 3. record which faction the block being parsed is, for StartMoney2's callback
        hook(
            PLAYER_TEMPLATE_BLOCK_KEY_EARLY,
            PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES,
            "block",
            "PlayerTemplate block key -> second-resource row key",
        )

        # 4. seed (and clear) the pool where gold is seeded
        hook(
            PLAYER_INIT_ENTRY,
            PLAYER_INIT_ENTRY_BYTES,
            "init",
            "Player::init -> seed the second resource pool",
        )

        # 5. the grant, on the income the module already pays
        hook(
            AUTO_DEPOSIT_DEPOSIT,
            AUTO_DEPOSIT_DEPOSIT_BYTES,
            "grant",
            "AutoDepositUpdate deposit -> also credit resource 2",
        )

        # 6. carry a template's cost across an INI override block
        hook(
            THING_TEMPLATE_COPY_ID,
            THING_TEMPLATE_COPY_ID_BYTES,
            "cost_copy",
            "ThingTemplate::copyFrom -> carry BuildCost2",
        )

        # 7. refuse what the player cannot pay for, through the one gate every human path shares
        hook(
            BUILD_GATE_AFFORD,
            BUILD_GATE_AFFORD_BYTES,
            "gate",
            "BuildAssistant affordability -> also check resource 2",
        )

        # 8. and charge it where the gold is taken
        hook(
            PRODUCTION_WITHDRAW,
            PRODUCTION_WITHDRAW_BYTES,
            "spend",
            "queueCreateUnit withdrawal -> also debit resource 2",
        )

        # 9. the second number in the palantir's resource text, and the change filter that has to
        #    widen with it or the bracket goes stale whenever gold happens to sit still
        if self.hud:
            hook(
                PALANTIR_RESOURCES,
                PALANTIR_RESOURCES_BYTES,
                "text",
                "palantir resources -> second-resource bracket",
            )
            hook(
                PALANTIR_RESOURCES_CACHE,
                PALANTIR_RESOURCES_CACHE_BYTES,
                "refresh",
                "palantir resource refresh -> also on a second-resource change",
            )
            # 10. the bracket on a priced button's cost line, at both sites that price a
            #     template - a unit or structure to build, and a hero to revive
            for site, label in (
                (TOOLTIP_COST_BUILD, "tip_build"),
                (TOOLTIP_COST_REVIVE, "tip_revive"),
            ):
                hook(site, TOOLTIP_COST_BYTES, label, f"{label} cost line -> BuildCost2 bracket")
        return out

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--no-hud",
            action="store_true",
            help="leave the palantir's resource text exactly as the stock engine draws it, "
            "instead of appending the second resource as (N)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> SecondResourcePatch:
        return cls(hud=not args.no_hud)

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        """Recover which half was built. `verify` only answers "is this *this* configuration",
        so a default-built probe would report a `--no-hud` binary as not carrying the patch."""
        for candidate in (cls(), cls(hud=False)):
            try:
                if not candidate.verify(data):
                    return candidate
            except (ValueError, KeyError, IndexError, TypeError, struct.error):
                continue
        return None

    def ini_surface(self) -> Engine:
        """The two fields this patch adds, both defaulting to 0 - which is "no second income" and
        "start with none", so an unmodified mod converts the way it runs."""
        return Engine(
            fields=tuple(
                FieldDelta(spec.block, spec.field, "Int", 0, patch=self.name) for spec in _TABLES
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        try:
            bases = self._resolve(data)
            live = tuple(read_field_table(data, base) for base in bases)
        except ValueError as exc:
            return [f"cannot read the field tables: {exc}"]

        problems: list[str] = []
        prior = tuple(
            entries_before(data, rows, spec.field) for spec, rows in zip(_TABLES, live, strict=True)
        )
        for spec, before in zip(_TABLES, prior, strict=True):
            if before is None:
                return [f"no {spec.field} row: the file does not carry this patch"]
        tables = tuple(before for before in prior if before is not None)

        labels = self._assemble(section_va, tables).label_va
        for spec, all_entries in zip(_TABLES, live, strict=True):
            want_fn = labels(spec.parse_label)
            entry = next(e for e in all_entries if _read_cstring(data, e[0]) == spec.field)
            if entry[1] != want_fn:
                problems.append(
                    f"{spec.block}.{spec.field} parses with {entry[1]:#x}, expected {want_fn:#x}"
                )
            if entry[2] != 0:
                problems.append(
                    f"{spec.block}.{spec.field} carries userData {entry[2]}, expected 0"
                )
            if entry[3] != spec.offset:
                problems.append(
                    f"{spec.block}.{spec.field} is at {entry[3]:#x}, expected {spec.offset:#x}"
                )

        for label, off, size in (
            ("block-key slot", _KEY_OFF, 4),
            ("in-use flag", _INUSE_OFF, 4),
            ("shown-value cache", _SHOWN_OFF, 4),
            ("player pool", _POOL_OFF, MAX_PLAYER_COUNT * 4),
            ("faction table", _ROWS_OFF, ROWS * ROW_STRIDE),
            ("cost table", _COST_OFF, COST_ROWS * COST_STRIDE),
        ):
            if bytes(data[section_off + off : section_off + off + size]) != bytes(size):
                problems.append(f"the {label} is not zero-initialised")

        fmt = section_off + _FMT_OFF
        if bytes(data[fmt : fmt + len(_FMT_BYTES)]) != _FMT_BYTES:
            problems.append(f"the format string is not {FORMAT!r}")
        suffix = section_off + _SUFFIX_OFF
        if bytes(data[suffix : suffix + len(_SUFFIX_BYTES)]) != _SUFFIX_BYTES:
            problems.append(f"the cost suffix is not {SUFFIX!r}")

        # `_edits` only describes bytes this configuration *writes*, so with the HUD half off it
        # would not notice one that is on. Say so, rather than verifying a build this is not.
        if not self.hud:
            for site, window in (
                (PALANTIR_RESOURCES, PALANTIR_RESOURCES_BYTES),
                (PALANTIR_RESOURCES_CACHE, PALANTIR_RESOURCES_CACHE_BYTES),
                (TOOLTIP_COST_BUILD, TOOLTIP_COST_BYTES),
                (TOOLTIP_COST_REVIVE, TOOLTIP_COST_BYTES),
            ):
                site_off = va_to_offset(data, site)
                if site_off is None:
                    continue
                if bytes(data[site_off : site_off + len(window)]) != window:
                    problems.append(
                        f"the palantir site at 0x{site:08x} is hooked, but this patch was built "
                        "with the HUD half off"
                    )

        try:
            edits = self._edits(data, section_va, tables, bases, table_refs=False)
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems


def _jmp(at_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - (at_va + 5))
