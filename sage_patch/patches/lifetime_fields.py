"""The lifetime-fields patch: three INI keywords that make `LifetimeUpdate` do more than kill.

Adds `ExtendedByUpgrades` (an upgrade mask) and `UpgradeLifetimeBonus` (a duration in
milliseconds), so gaining one of those upgrades pushes the death frame back; and
`ExpirationTemplate` (an object name), so the module **transforms the object into that template
instead of killing it** when the time runs out. Targets the ROTWK SAGE-engine `game.dat` build
``2.01.2614.37001``. The first two are derived in ``../docs/lifetime-extend-upgrade.md``, the
third in ``../docs/lifetime-transform.md``.

The three are independent: each is armed by its own keyword and a block declaring none of them
runs stock bytes. They share a module because they share `LifetimeUpdate`'s `ModuleData` and its
field-parse table, and those have one owner each.

**There is no timer to extend.** `LifetimeUpdate` does not count down. `setLifetimeRange`
(`LIFETIME_ARM`) rolls one duration, stores an absolute death frame at ``module+0x20`` and
*returns the duration as the module's sleep*; `update` (`LIFETIME_UPDATE`) is then called once,
on that frame, and
kills the object without ever reading the clock. So an extension is one add to that frame - and
the whole cost of the patch is **noticing when to do it**, because nothing tells a module that an
upgrade arrived.

**The trigger is the mask going empty -> non-empty**, checked once per frame while the keyword is
declared. That is what "the upgrade fired" can mean at this level: an upgrade already held cannot
be granted again, since granting sets a bit that is already set. So a permanent player-scoped
upgrade fires **once per object** - including on the first poll of an object created while it is
already held, which is what makes "this upgrade makes every summon last 5s longer" work - and an
object-scoped one re-arms whenever something removes it.

**The bonus is authored in milliseconds and stored in frames**, because the row names the engine's
own `INI_PARSE_DURATION` - the same parse function `MinLifetime` and `MaxLifetime` use, which
multiplies by the live logic rate set at `0x00644F11`. So the stored value is already on the clock
`m_dieFrame` counts and the patch converts nothing.

**The in-world timer follows for free.** The bar over a summoned object is
`(die - now) / (die - start)`, recomputed every frame from the *live* module at
`LIFETIME_UI_FRACTION` - so pushing `m_dieFrame` out grows the remaining time and the total span
together, and the bar jumps up and then drains over the new total. Nothing client-side has to be
patched, and nothing reads the template's `MaxLifetime` to draw it. (This is also why *pausing*
the clock is the mechanic the stock UI cannot represent: the numerator would freeze while the
denominator kept growing, so the bar would drain to nothing over a live object. Freezing it would
mean pushing ``module+0x24`` along with the death frame.)

**The transform is the engine's own mount swap, called directly.**
`ToggleMountedSpecialAbilityUpdate`'s swap (`TOGGLE_MOUNTED_SWAP`) reads three things off the
module it is
called on - the `ModuleData` at ``+0x04``, the `Object` at ``+0x08``, and a success flag it writes
at ``+0x8c`` - makes **no virtual call on it**, and of that `ModuleData` reads only the template
name at `TOGGLE_MOUNTED_TEMPLATE` and the timer-sync vector behind it. `LifetimeUpdate`'s module
has the
same first two offsets, and its `ModuleData` grows to `TOGGLE_MOUNTED_MODULE_DATA_SIZE` - which is
`ToggleMountedSpecialAbilityUpdate`'s own ``sizeof`` - with the new keyword's row landing exactly
where `MountedTemplate` lands. So the cave builds a module-shaped scratch on the stack, hands it
the real `ModuleData` and `Object`, and calls the stock swap and the stock retire
(`TOGGLE_MOUNTED_RETIRE`,
which hides the drawable, drops it out of the UI and calls `GameLogic::destroyObject`). Health,
experience, team, position, facing, selection and contained passengers move exactly as they do
when a hero mounts, because it is the same code.

Six edits, one cave
-------------------
1. **The mask needs room, and `ModuleData` has none.** ``sizeof`` is ``0x18`` with two bytes of
   padding, against the ``0x90`` an `UpgradeMaskType` needs plus four for the bonus, and the
   transform needs its string at a fixed ``0xd8``, so the structure grows to
   `TOGGLE_MOUNTED_MODULE_DATA_SIZE`. That is one hook, because `newModuleData`
   (`LIFETIME_ALLOC`) is **LifetimeUpdate's own thunk**: it calls the ModuleData constructor
   directly and
   nothing else in the image reaches either. The cave replaces the size and **zeroes everything it
   added**, which is required rather than tidy - for every `LifetimeUpdate` that does not declare
   the keywords the parsers never run, and `operator new` does not zero. Zeroing in the allocator
   rather than the constructor is what leaves the constructor's own five stores untouched.
2. **The keywords.** The field-parse table at `LIFETIME_FIELD_TABLE` is boxed in by its own keyword
   strings and its terminator, so it is rebuilt in the cave - five stock rows copied verbatim,
   since their name pointers are absolute, plus three rows and the terminator. It has **exactly
   one reference** in the image, the ``push`` immediate at `LIFETIME_FIELD_TABLE_REF`, and the
   reader
   walks to the terminator rather than to a count. All three new rows name **engine parse
   functions**, so the patch adds no parse code.
3. **The edge latch's default, for one byte.** The rising edge needs to know what last frame
   answered, and the module instance has three bytes of tail padding after the `WaitForWakeUp`
   latch at ``+0x28`` (``sizeof`` is ``0x2c``). The constructor zeroes ``+0x28`` with a *byte*
   store while `eax` is already zero, so widening that one store to a dword (`0x88` -> `0x89`)
   clears the new latch too. `sizeof` does not change, the savegame does not change, and the
   constructor is otherwise untouched.
4. **Arming, at the tail of `setLifetimeRange`.** When the mask is non-empty the returned sleep
   becomes 1, so the module wakes every frame instead of sleeping to its death frame - which is
   the only way to see an edge at all. Hooking here rather than at either call site covers both
   arming paths, the constructor and `startLifetime` (what `WaitForWakeUp` resumes through),
   because this function is the single funnel they share.
5. **The extension, at `update`'s first instruction.** Held now and not last frame -> add the
   bonus to the death frame. Then: not yet due -> sleep one frame, which is the poll the arming
   hook set up; due -> the stock update, byte for byte, including the kill. The hook is at the
   entry rather than at the kill because the module pointer is only live in ``ecx`` there:
   `update` never spills it.
6. **The transform, ahead of the scoring arm.** `LIFETIME_EXPIRE` is `update`'s ``cmp`` of
   `ScoreKill`
   and the ``push esi`` after it - five bytes of two whole instructions, reached with ``ebx`` and
   ``edi`` already the `ModuleData` and the `Object` and with the `THROWN_PROJECTILE` reprieve
   already taken. Hooking *here* rather than at the kill is what keeps the score straight: the
   ``ScoreKill = No`` arm calls `ScoreKeeper::addObjectBuilt(obj, -1)` and so does the swap, so a
   hook below it would decrement twice for one transform. Returning takes the epilogue at
   `LIFETIME_KILL_RETURN`, which is the one the `THROWN_PROJECTILE` arm already returns through -
   *before* the ``push esi`` this hook displaced.

**An object that does not declare the keyword pays one `any()`** - 36 dword compares - and one
`AsciiString::isEmpty` - two - once, on the frame it dies, and nothing else about it changes. An
object that declares the mask wakes every frame for its whole lifetime; that is the cost, and it
is the reason the field is opt-in. `ExpirationTemplate` costs nothing until the object expires.

**Determinism.** This changes *when objects die* and *which objects exist*, which is logic-side
`Object` state and is CRC'd, so **every peer must run the same patched binary** and replays do not
cross. And, as with `terrain-resource-exp` and `queue-ignore-cp`, the keywords are an INI **parse
error** on a stock build rather than a warning.

**Savegames need no version bump**, and the one thing that is not carried across a load is the
edge latch: a still-held upgrade reads as freshly gained on the first poll after loading and pays
its bonus a second time. Bounded to one extension per load, and the alternative is a module xfer
version bump that would make patched saves unreadable by anything else.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name.
No bundled patch touches `LifetimeUpdate`, its field table or its module-factory thunk, and none
reads what this one writes. The engine routines the cave calls - the two mask predicates,
`getControllingPlayer`, `AsciiString::isEmpty`, and the mount swap and retire - are read, never
rewritten, here or anywhere else in the package.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

# Every engine fact this patch reads lives in `..addresses`, which is the single home for facts
# about this build; nothing about the target binary is written down here.
from ..addresses import (
    ASCII_STRING_IS_EMPTY,
    FIELD_PARSE_STRIDE,
    GAME_DATA_ASCIISTRING_PARSER,
    GAME_LOGIC_FRAME,
    INI_PARSE_DURATION,
    INI_PARSE_UPGRADE_MASK,
    LIFETIME_ALLOC,
    LIFETIME_ALLOC_BYTES,
    LIFETIME_ALLOC_RESUME,
    LIFETIME_ANCHORS,
    LIFETIME_ARM,
    LIFETIME_ARM_BYTES,
    LIFETIME_DIE_FRAME,
    LIFETIME_EXPIRE,
    LIFETIME_EXPIRE_BYTES,
    LIFETIME_EXPIRE_RESUME,
    LIFETIME_FIELD_TABLE,
    LIFETIME_FIELD_TABLE_REF,
    LIFETIME_KILL_RETURN,
    LIFETIME_LATCH_DEFAULT,
    LIFETIME_LATCH_DEFAULT_BYTES,
    LIFETIME_MODULE_DATA_SIZE,
    LIFETIME_STOCK_FIELDS,
    LIFETIME_UPDATE,
    LIFETIME_UPDATE_BYTES,
    LIFETIME_UPDATE_RESUME,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_UPGRADE_MASK,
    OPERATOR_NEW,
    PLAYER_COMPLETED_UPGRADE_MASK,
    PLAYER_COMPLETED_UPGRADE_MASK_WORDS,
    THE_GAME_LOGIC,
    TOGGLE_MOUNTED_INSTANCE_SIZE,
    TOGGLE_MOUNTED_MODULE_DATA_SIZE,
    TOGGLE_MOUNTED_RETIRE,
    TOGGLE_MOUNTED_SWAP,
    TOGGLE_MOUNTED_SWAP_FLAG,
    TOGGLE_MOUNTED_TEMPLATE,
    UPDATE_MODULE_DATA,
    UPDATE_MODULE_OBJECT,
    UPDATE_MODULE_SLEEP_FOREVER,
    UPDATE_MODULE_THIS_DELTA,
    UPGRADE_MASK_ANY,
    UPGRADE_MASK_TEST_ANY,
)
from ..asm import JAE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "BONUS_OFFSET",
    "DEFAULT_BONUS_KEYWORD",
    "DEFAULT_KEYWORD",
    "DEFAULT_TEMPLATE_KEYWORD",
    "LATCH_OFFSET",
    "LifetimeFieldsPatch",
    "MASK_OFFSET",
    "SECTION_NAME",
    "build_alloc",
    "build_arm",
    "build_expire",
    "build_held",
    "build_table",
    "build_update",
    "validate_keywords",
]

#: Where this patch's three fields land in the grown `ModuleData`, and how much of it the
#: allocator zeroes. The mask starts at the stock structure's end, the bonus behind its 36 dwords
#: (see ``../docs/upgrade-mask-limit.md``), and the template at `TOGGLE_MOUNTED_TEMPLATE` - which
#: is the
#: one that is not a free choice, because the mount swap reads it there.
MASK_OFFSET = LIFETIME_MODULE_DATA_SIZE
BONUS_OFFSET = MASK_OFFSET + PLAYER_COMPLETED_UPGRADE_MASK_WORDS * 4
ZERO_DWORDS = (TOGGLE_MOUNTED_MODULE_DATA_SIZE - LIFETIME_MODULE_DATA_SIZE) // 4

#: The edge latch: was an upgrade in the mask held at the previous poll? Tail padding after the
#: `WaitForWakeUp` byte at ``+0x28``, inside the stock ``sizeof`` of ``0x2c``, which is what makes
#: widening one store in the constructor enough to default it.
LATCH_OFFSET = 0x29

DEFAULT_KEYWORD = "ExtendedByUpgrades"
DEFAULT_BONUS_KEYWORD = "UpgradeLifetimeBonus"
DEFAULT_TEMPLATE_KEYWORD = "ExpirationTemplate"

SECTION_NAME = ".lifeext"  # 8 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds the keyword strings and
# the rebuilt table as well as four stubs, so it is both read as data and entered as code.
SECTION_CHARACTERISTICS = 0x60000060


# An INI keyword is matched by exact compare, so anything the parser could never match is a typo
# rather than a choice. The engine's own field names are CamelCase with digits and underscores.
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def validate_keywords(keyword: str, bonus_keyword: str, template_keyword: str) -> None:
    """Raise unless all three names are tokens the engine's INI reader could match, are not already
    `LifetimeUpdate` fields, and are not each other. A duplicate would parse - the reader takes the
    first match and the engine would never complain - so the field would exist and silently do
    nothing."""
    names = (keyword, bonus_keyword, template_keyword)
    for name in names:
        if not _KEYWORD_PATTERN.match(name):
            raise ValueError(
                "an INI keyword must be letters, digits and underscores starting with a letter "
                f"(the reader matches it by exact compare), got {name!r}"
            )
        if any(name.lower() == stock.lower() for stock, _off in LIFETIME_STOCK_FIELDS):
            raise ValueError(f"{name!r} is already a LifetimeUpdate field")
    folded = [name.lower() for name in names]
    if len(set(folded)) != len(folded):
        raise ValueError(f"the three keywords must differ, got {names!r}")


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _disp8(value: int) -> int:
    return value & 0xFF


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
    """Where each piece of the cave sits, given its base address and the keywords.

    Pure arithmetic on the keywords' lengths, so :meth:`LifetimeFieldsPatch.apply` and
    :meth:`LifetimeFieldsPatch.verify` compute the same addresses from opposite directions.
    The three strings come first, in declaration order, so
    :meth:`LifetimeFieldsPatch.detect` can read them straight off the section base without
    knowing how long anything after them is."""

    keyword_va: int
    bonus_keyword_va: int
    template_keyword_va: int
    table_va: int
    alloc_va: int
    arm_va: int
    held_va: int
    update_va: int
    expire_va: int


def _layout(base_va: int, keyword: str, bonus_keyword: str, template_keyword: str) -> _Layout:
    bonus_va = base_va + len(keyword) + 1
    template_va = bonus_va + len(bonus_keyword) + 1
    strings = len(keyword) + len(bonus_keyword) + len(template_keyword) + 3
    table_va = base_va + strings + (-strings % 4)  # keep the table's dwords aligned
    # the stock rows, this patch's three and the terminator
    alloc_va = table_va + (len(LIFETIME_STOCK_FIELDS) + 4) * FIELD_PARSE_STRIDE
    arm_va = alloc_va + len(build_alloc(alloc_va))
    held_va = arm_va + len(build_arm(arm_va))
    update_va = held_va + len(build_held(held_va))
    expire_va = update_va + len(build_update(update_va, held_va))
    return _Layout(
        base_va,
        bonus_va,
        template_va,
        table_va,
        alloc_va,
        arm_va,
        held_va,
        update_va,
        expire_va,
    )


def build_table(
    keyword_va: int, bonus_keyword_va: int, template_keyword_va: int, stock_rows: bytes
) -> bytes:
    """The rebuilt field-parse table: the stock rows verbatim, the three new ones, the terminator.

    The stock rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are, in ``.rdata``, and only the new rows point into the
    cave."""
    mask_row = struct.pack("<IIII", keyword_va, INI_PARSE_UPGRADE_MASK, 0, MASK_OFFSET)
    bonus_row = struct.pack("<IIII", bonus_keyword_va, INI_PARSE_DURATION, 0, BONUS_OFFSET)
    template_row = struct.pack(
        "<IIII", template_keyword_va, GAME_DATA_ASCIISTRING_PARSER, 0, TOGGLE_MOUNTED_TEMPLATE
    )
    return stock_rows + mask_row + bonus_row + template_row + bytes(FIELD_PARSE_STRIDE)


def build_alloc(base_va: int) -> bytes:
    """Allocate the grown `ModuleData` and zero the fields it added.

    Entered in place of `newModuleData`'s ``push esi`` / ``push 0x18`` / ``call operator new``, and
    owes the caller all three effects: ``esi`` saved, the block in ``eax``, and the size argument
    still on the stack for the ``pop ecx`` the cave rejoins at.

    The zeroing is what makes the fields' defaults "no upgrade extends this, by nothing".
    `parseUpgradeMask` memsets the mask it is given, so a block declaring the keyword would be fine
    either way; a block that does not declare it never reaches either parser, and `operator new`
    hands back whatever was in the heap. ``esi`` is not touched, because the value just pushed is
    the caller's and the register is still live."""
    a = Asm(base_va)
    a.emit(0x56)  # push esi
    a.emit(0x68, _u32(TOGGLE_MOUNTED_MODULE_DATA_SIZE))  # push 0xac
    a.call_absolute(OPERATOR_NEW)  # call <operator new>
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "done")  # je .done              ; the caller tests for null too
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x50", LIFETIME_MODULE_DATA_SIZE)  # lea  edx, [eax+0x18]  ; past the stock fields
    a.emit(0xB9, _u32(ZERO_DWORDS))  # mov  ecx, 37
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.label("zero")
    a.emit(b"\x89\x02")  # mov  [edx], eax
    a.emit(b"\x83\xc2\x04")  # add  edx, 4
    a.emit(0x49)  # dec  ecx
    a.jcc_short(JNE, "zero")  # jne .zero
    a.emit(0x58)  # pop  eax
    a.label("done")
    a.jmp_absolute(LIFETIME_ALLOC_RESUME)
    return a.finish()


def build_arm(base_va: int) -> bytes:
    """The tail of `setLifetimeRange`: store the death frame, then choose the sleep.

    ``esi`` is the module, ``ecx`` the death frame and ``eax`` the duration both call sites push as
    the module's sleep. With a mask declared that becomes 1, so the module wakes every frame - the
    only way :func:`build_update` can see an upgrade arrive. The death frame is stored either way
    and stays the only thing that decides when the object dies.

    `any()` returns in ``al`` and touches nothing else the caller needs, so the duration is simply
    parked across it - and ``pop`` does not disturb the flags the ``test`` set."""
    a = Asm(base_va)
    a.emit(b"\x89\x4e", LIFETIME_DIE_FRAME)  # mov  [esi+0x20], ecx  ; the displaced store
    a.emit(0x50)  # push eax               ; the stock sleep
    a.emit(b"\x8b\x4e", UPDATE_MODULE_DATA)  # mov  ecx, [esi+4]     ; the ModuleData
    a.emit(b"\x83\xc1", MASK_OFFSET)  # add  ecx, 0x18        ; &the mask
    a.call_absolute(UPGRADE_MASK_ANY)  # call <any()>
    a.emit(b"\x84\xc0")  # test al, al
    a.emit(0x58)  # pop  eax
    a.jcc_short(JE, "out")  # je .out               ; no keyword -> the stock sleep
    a.emit(0xB8, _u32(1))  # mov  eax, 1           ; UPDATE_SLEEP(1): poll
    a.label("out")
    a.emit(0x5E)  # pop  esi
    a.emit(b"\xc2\x08\x00")  # ret  8
    return a.finish()


def build_held(base_va: int) -> bytes:
    """Is any upgrade in the mask held? ``esi`` = the `Object`, ``edi`` = the mask, answer in
    ``al``.

    The engine's own two-mask idiom, in the engine's own order: the object's completed mask first,
    then its controlling player's. Two `testForAny` calls rather than a union, which is what
    `UpgradeMux` does and costs no scratch space. An unowned object answers on its own mask alone,
    since `getControllingPlayer` returns NULL rather than faulting.

    The mask is carried in ``edi`` because it has to survive both callees, and every scratch
    register is spoken for: `testForAny` takes its argument on the stack and returns in ``al``,
    and `getControllingPlayer` answers in ``eax``."""
    a = Asm(base_va)
    a.emit(0x57)  # push edi               ; the mask, as testForAny's argument
    a.emit(b"\x8d\x8e", _u32(OBJECT_UPGRADE_MASK))  # lea ecx, [esi+0x28c]
    a.call_absolute(UPGRADE_MASK_TEST_ANY)  # call <testForAny>     ; ret 4
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JNE, "yes")  # jne .yes              ; object-scoped
    a.emit(b"\x8b\xce")  # mov  ecx, esi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)  # call <getControllingPlayer>
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "no")  # je .no                ; unowned -> not held
    a.emit(b"\x8d\x88", _u32(PLAYER_COMPLETED_UPGRADE_MASK))  # lea ecx, [eax+0x14c]
    a.emit(0x57)  # push edi
    a.call_absolute(UPGRADE_MASK_TEST_ANY)  # call <testForAny>     ; its al is ours
    a.emit(0xC3)  # ret
    a.label("yes")
    a.emit(b"\xb0\x01")  # mov  al, 1
    a.emit(0xC3)  # ret
    a.label("no")
    a.emit(b"\x32\xc0")  # xor  al, al
    a.emit(0xC3)  # ret
    return a.finish()


def build_update(base_va: int, held_va: int) -> bytes:
    """`update`'s new first instruction: pay the extension, poll, or the stock update.

    Entered with ``ecx`` = the `UpdateModule` subobject (``module+0x10``) and the stack exactly as
    the caller left it, so ``mov eax, 1 / ret`` is a legal early return - `update` takes no
    arguments and ends in a bare ``ret``.

    The latch is written on **every** polled frame, held or not, which is what makes the trigger an
    edge rather than a level: it fires when the answer changes from no to yes, and re-arms as soon
    as the upgrade goes away. ``edi`` is saved because the stock function pushes it *after* this
    hook returns and pops it on the way out, so leaving it dirty would hand the caller the wrong
    value back rather than merely clobbering it."""
    a = Asm(base_va)
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    data_disp = _disp8(-UPDATE_MODULE_THIS_DELTA + UPDATE_MODULE_DATA)
    object_disp = _disp8(-UPDATE_MODULE_THIS_DELTA + UPDATE_MODULE_OBJECT)
    a.emit(b"\x8b\x59", data_disp)  # mov  ebx, [ecx-0xc]
    a.emit(b"\x8b\x71", object_disp)  # mov  esi, [ecx-8]
    a.emit(b"\x8d\x7b", MASK_OFFSET)  # lea  edi, [ebx+0x18]  ; &the mask
    a.emit(0x51)  # push ecx
    a.emit(b"\x8b\xcf")  # mov  ecx, edi
    a.call_absolute(UPGRADE_MASK_ANY)  # call <any()>
    a.emit(0x59)  # pop  ecx
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "stock")  # je .stock             ; no keyword -> stock, bit for bit

    a.emit(0x51)  # push ecx
    a.call_absolute(held_va)  # call <held>           ; al = held now
    a.emit(0x59)  # pop  ecx
    a.emit(b"\x8a\x51", _disp8(LATCH_OFFSET - UPDATE_MODULE_THIS_DELTA))  # mov dl, [ecx+0x19]
    a.emit(b"\x88\x41", _disp8(LATCH_OFFSET - UPDATE_MODULE_THIS_DELTA))  # mov [ecx+0x19], al
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "due")  # je .due               ; not held -> latch cleared, nothing paid
    a.emit(b"\x84\xd2")  # test dl, dl
    a.jcc(JNE, "due")  # jne .due              ; held last frame too -> not an edge
    a.emit(b"\x8b\x93", _u32(BONUS_OFFSET))  # mov edx, [ebx+0xa8]   ; the bonus, in frames
    die_disp = _disp8(LIFETIME_DIE_FRAME - UPDATE_MODULE_THIS_DELTA)
    a.emit(b"\x01\x51", die_disp)  # add  [ecx+0x10], edx

    a.label("due")
    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov  eax, [TheGameLogic]
    a.emit(b"\x8b\x40", GAME_LOGIC_FRAME)  # mov  eax, [eax+0x40]  ; now
    die_disp = _disp8(LIFETIME_DIE_FRAME - UPDATE_MODULE_THIS_DELTA)
    a.emit(b"\x3b\x41", die_disp)  # cmp  eax, [ecx+0x10]
    a.jcc(JAE, "stock")  # jae .stock            ; due -> the stock kill
    a.emit(0x5F)  # pop  edi
    a.emit(0x5E)  # pop  esi
    a.emit(0x5B)  # pop  ebx
    a.emit(0xB8, _u32(1))  # mov  eax, 1           ; UPDATE_SLEEP(1)
    a.emit(0xC3)  # ret

    a.label("stock")
    a.emit(0x5F)  # pop  edi
    a.emit(0x5E)  # pop  esi
    a.emit(0x5B)  # pop  ebx
    a.emit(LIFETIME_UPDATE_BYTES)  # the displaced prologue
    a.jmp_absolute(LIFETIME_UPDATE_RESUME)
    return a.finish()


def build_expire(base_va: int) -> bytes:
    """`update`'s expiry, one branch earlier: become the template, or fall through to the stock
    death.

    Entered with ``ebx`` = the `ModuleData`, ``edi`` = the `Object` and ``esi`` **not yet pushed**,
    in place of the `ScoreKill` test and the push behind it. With no template declared the two
    displaced instructions are re-executed and the function carries on, byte for byte - ``push``
    sets no flags, so the ``cmp`` can go second and land its answer directly in the ``je`` the cave
    returns to.

    The transform hands `TOGGLE_MOUNTED_SWAP` a stack frame where a
    `ToggleMountedSpecialAbilityUpdate`
    instance would be. Three slots is all it reads: the `ModuleData`, whose grown tail holds the
    template name exactly where `MountedTemplate` lives, the `Object`, and the flag - cleared
    first, because it is the only way to tell a swap that happened from one the template store
    refused. The swap preserves ``ebx`` and ``edi``, so the abort arm still has what the stock path
    needs.

    `TOGGLE_MOUNTED_RETIRE` is called immediately rather than a step later the way the mount
    toggle reaches it,
    because there is no pack animation to wait through: the replacement already carries everything
    and `destroyObject` is deferred to the end of the frame either way."""
    a = Asm(base_va)
    a.emit(b"\x8d\x8b", _u32(TOGGLE_MOUNTED_TEMPLATE))  # lea  ecx, [ebx+0xd8]  ; &the template
    a.call_absolute(ASCII_STRING_IS_EMPTY)  # call <isEmpty>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "stock")  # jne .stock            ; no keyword -> stock, bit for bit

    a.emit(b"\x81\xec", _u32(TOGGLE_MOUNTED_INSTANCE_SIZE))  # sub esp, 0x90 ; module-shaped
    a.emit(b"\x89\x5c\x24", UPDATE_MODULE_DATA)  # mov [esp+4], ebx
    a.emit(b"\x89\x7c\x24", UPDATE_MODULE_OBJECT)  # mov [esp+8], edi
    a.emit(b"\xc6\x84\x24", _u32(TOGGLE_MOUNTED_SWAP_FLAG), 0x00)  # mov byte [esp+0x8c], 0
    a.emit(b"\x8b\xcc")  # mov  ecx, esp
    a.call_absolute(TOGGLE_MOUNTED_SWAP)  # call <the mount swap>
    a.emit(b"\x80\xbc\x24", _u32(TOGGLE_MOUNTED_SWAP_FLAG), 0x00)  # cmp byte [esp+0x8c], 0
    a.jcc(JE, "abort")  # je .abort             ; no such template -> die as stock
    a.emit(b"\x8b\xcc")  # mov  ecx, esp
    a.call_absolute(TOGGLE_MOUNTED_RETIRE)  # call <hide, deselect, destroy>
    a.emit(b"\x81\xc4", _u32(TOGGLE_MOUNTED_INSTANCE_SIZE))  # add  esp, 0x90
    a.emit(0xB8, _u32(UPDATE_MODULE_SLEEP_FOREVER))  # mov  eax, 0x3fffffff
    a.jmp_absolute(LIFETIME_KILL_RETURN)  # the epilogue above the `pop esi`

    a.label("abort")
    a.emit(b"\x81\xc4", _u32(TOGGLE_MOUNTED_INSTANCE_SIZE))  # add  esp, 0x90
    a.label("stock")
    a.emit(0x56)  # push esi              ; the displaced pair, flags last
    a.emit(LIFETIME_EXPIRE_BYTES[:-1])  # cmp  byte [ebx+0x11], 0
    a.jmp_absolute(LIFETIME_EXPIRE_RESUME)
    return a.finish()


def _jmp_bytes(from_va: int, to_va: int, width: int) -> bytes:
    """``jmp rel32`` to ``to_va``, padded with ``nop`` to the ``width`` bytes it displaces."""
    jump = b"\xe9" + struct.pack("<i", to_va - (from_va + 5))
    return jump + b"\x90" * (width - len(jump))


def widened_latch_default() -> bytes:
    """The constructor's ``mov byte [esi+0x28], al`` as a dword store.

    Three bytes for three, one of them changed: ``eax`` is already zero at that point and the
    instance is ``0x2c`` bytes, so the store clears the `WaitForWakeUp` byte exactly as before and
    the edge latch behind it as well."""
    widened = bytes((0x89,)) + LIFETIME_LATCH_DEFAULT_BYTES[1:]
    assert len(widened) == len(LIFETIME_LATCH_DEFAULT_BYTES)
    return widened


class LifetimeFieldsPatch(Patch):
    """Add an upgrade-extension pair and a transform-on-expiry template to `LifetimeUpdate`."""

    name = "lifetime-fields"
    author = "officialNecro"
    description = (
        "Add three fields to LifetimeUpdate. ExtendedByUpgrades and UpgradeLifetimeBonus push an "
        "object's death back by that many milliseconds when one of those upgrades arrives; "
        "ExpirationTemplate names an object to become when the time runs out, using the engine's "
        "own mount swap, instead of dying. Each is armed by its own keyword and a block "
        "declaring none of them leaves the module stock"
    )

    def __init__(
        self,
        keyword: str = DEFAULT_KEYWORD,
        bonus_keyword: str = DEFAULT_BONUS_KEYWORD,
        template_keyword: str = DEFAULT_TEMPLATE_KEYWORD,
    ):
        self.keyword = keyword
        self.bonus_keyword = bonus_keyword
        self.template_keyword = template_keyword
        validate_keywords(keyword, bonus_keyword, template_keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword}, {self.bonus_keyword}, {self.template_keyword})"

    @property
    def _keywords(self) -> tuple[str, str, str]:
        return (self.keyword, self.bonus_keyword, self.template_keyword)

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        stock_rows = self._read_stock_table(data)

        base_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._build(va, stock_rows),
            SECTION_CHARACTERISTICS,
        )
        pieces = _layout(base_va, *self._keywords)
        for file_off, old, new, note in self._edits(data, pieces):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch with exactly these keywords (an empty
        list == verified). Locates the cave, recomputes everything the keywords imply and compares
        it and every rewritten site to what is on disk. Reads only via ``struct`` and the section
        table, so verification needs no disassembler.

        The stock rows are read back **out of the cave's own copy** rather than from the address
        they came from, because that address still holds them: on a patched image it would only
        ever confirm the copy against itself."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located
        pieces = _layout(section_va, *self._keywords)

        # Checked first because everything after them is laid out *from* the keywords: a cave built
        # for others is a different length, and would otherwise report as a size problem.
        installed = (
            _read_cstring(data, pieces.keyword_va),
            _read_cstring(data, pieces.bonus_keyword_va),
            _read_cstring(data, pieces.template_keyword_va),
        )
        if installed != self._keywords:
            return [f"the keywords in {SECTION_NAME} are {installed!r}, not {self._keywords!r}"]

        problems: list[str] = []
        try:
            content = self._build(section_va, self._copied_rows(data, pieces))
            edits = self._edits(data, pieces)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        if len(content) > vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for this patch's cave"]
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(
                f"{SECTION_NAME} does not match keywords {self._keywords!r} "
                "(the table, strings or stubs differ)"
            )
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        problems += self._table_problems(data, pieces)
        problems += self._anchor_problems(data)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> LifetimeFieldsPatch | None:
        """Recognise this patch **and recover its keywords**.

        The default probe would only ever recognise the default names. All three strings are the
        first thing in the cave (:func:`_layout` puts them at the section base, in declaration
        order), so they read straight back out; `verify` then checks the whole cave against them."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keywords: list[str] = []
        va = located[0]
        for _ in range(3):
            name = _read_cstring(data, va)
            if name is None:
                return None
            keywords.append(name)
            va += len(name) + 1
        try:
            patch = cls(*keywords)
        except ValueError:
            return None  # not a set of keywords this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The three fields this patch adds to `LifetimeUpdate`, under whatever names it was
        installed with: the mask, typed as the engine's own mask fields are; the bonus, which is a
        duration in milliseconds like `MinLifetime` and `MaxLifetime` beside it because it is
        parsed by the same function; and the template, a cross-reference to an object like
        `MountedTemplate`, whose row it copies. All three default to empty/zero, which is stock
        behaviour and is what makes them opt-in."""
        return Engine(
            fields=(
                FieldDelta("LifetimeUpdate", self.keyword, "Ref[]:upgrades", None, self.name),
                FieldDelta("LifetimeUpdate", self.bonus_keyword, "Int", 0, self.name),
                FieldDelta("LifetimeUpdate", self.template_keyword, "Ref:objects", None, self.name),
            )
        )

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the upgrade-mask field to add to LifetimeUpdate (default "
                f"{DEFAULT_KEYWORD}); letters, digits and underscores, and must not already be one "
                "of the module's five fields"
            ),
        )
        parser.add_argument(
            "--bonus-keyword",
            default=DEFAULT_BONUS_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the duration field the mask pays out (default {DEFAULT_BONUS_KEYWORD}); "
                "authored in milliseconds, like MinLifetime and MaxLifetime beside it"
            ),
        )
        parser.add_argument(
            "--template-keyword",
            default=DEFAULT_TEMPLATE_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the object field to become on expiry (default "
                f"{DEFAULT_TEMPLATE_KEYWORD}); takes an object name the way MountedTemplate does, "
                "and declaring it turns the module's death into a transform"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> LifetimeFieldsPatch:
        return cls(
            keyword=args.keyword,
            bonus_keyword=args.bonus_keyword,
            template_keyword=args.template_keyword,
        )

    def _build(self, base_va: int, stock_rows: bytes) -> bytes:
        """The cave: the three keyword strings, the rebuilt field table, then the five stubs - in
        that order, so :meth:`detect` finds the names at the section base."""
        pieces = _layout(base_va, *self._keywords)

        blob = bytearray()
        for name in self._keywords:
            blob += name.encode("ascii") + b"\x00"
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(
            pieces.keyword_va, pieces.bonus_keyword_va, pieces.template_keyword_va, stock_rows
        )
        assert base_va + len(blob) == pieces.alloc_va, "the cave layout and its addresses disagree"

        blob += build_alloc(pieces.alloc_va)
        blob += build_arm(pieces.arm_va)
        blob += build_held(pieces.held_va)
        blob += build_update(pieces.update_va, pieces.held_va)
        blob += build_expire(pieces.expire_va)
        return bytes(blob)

    def _read_stock_table(self, data: bytes | bytearray) -> bytes:
        """The five stock entries verbatim, after checking they really are this build's
        `LifetimeUpdate` table: every name and every `ModuleData` offset must match, and the sixth
        entry must be the NULL terminator."""
        off = va_to_offset(data, LIFETIME_FIELD_TABLE)
        if off is None:
            raise ValueError(f"the field table VA 0x{LIFETIME_FIELD_TABLE:08x} is not mapped")

        size = len(LIFETIME_STOCK_FIELDS) * FIELD_PARSE_STRIDE
        entries = bytes(data[off : off + size])
        if len(entries) != size:
            raise ValueError("the field table runs past the end of the image")

        for index, (name, offset) in enumerate(LIFETIME_STOCK_FIELDS):
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
                "the field table is not NULL-terminated after "
                f"{len(LIFETIME_STOCK_FIELDS)} entries "
                f"(found {terminator.hex()})"
            )
        return entries

    def _copied_rows(self, data: bytes | bytearray, pieces: _Layout) -> bytes:
        off = va_to_offset(data, pieces.table_va)
        if off is None:
            raise ValueError(f"the rebuilt table at 0x{pieces.table_va:08x} is not mapped")
        return bytes(data[off : off + len(LIFETIME_STOCK_FIELDS) * FIELD_PARSE_STRIDE])

    def _table_problems(self, data: bytes | bytearray, pieces: _Layout) -> list[str]:
        """What the rebuilt table has to spell: the five stock names still at their stock offsets,
        then the mask and the bonus, each parsed by the engine function that gives it its type and
        landing in the space the grown `ModuleData` bought."""
        problems: list[str] = []
        off = va_to_offset(data, pieces.table_va)
        if off is None:
            return [f"the rebuilt table at 0x{pieces.table_va:08x} is not mapped"]

        for index, (name, offset) in enumerate(LIFETIME_STOCK_FIELDS):
            name_va, _parse, _ud, field_off = struct.unpack_from(
                "<4I", data, off + index * FIELD_PARSE_STRIDE
            )
            got = _read_cstring(data, name_va)
            if got != name or field_off != offset:
                problems.append(
                    f"rebuilt table entry {index}: expected {name!r} at 0x{offset:x}, "
                    f"found {got!r} at 0x{field_off:x}"
                )

        appended = (
            (self.keyword, INI_PARSE_UPGRADE_MASK, MASK_OFFSET, "the upgrade mask"),
            (self.bonus_keyword, INI_PARSE_DURATION, BONUS_OFFSET, "the millisecond bonus"),
            (
                self.template_keyword,
                GAME_DATA_ASCIISTRING_PARSER,
                TOGGLE_MOUNTED_TEMPLATE,
                "the expiration template",
            ),
        )
        for index, (keyword, parser, offset, what) in enumerate(appended):
            row = off + (len(LIFETIME_STOCK_FIELDS) + index) * FIELD_PARSE_STRIDE
            name_va, parse_fn, _ud, field_off = struct.unpack_from("<4I", data, row)
            got = _read_cstring(data, name_va)
            if got != keyword:
                problems.append(f"{what} is called {got!r}, not {keyword!r}")
            if parse_fn != parser:
                problems.append(f"{what} parses with 0x{parse_fn:08x}, not 0x{parser:08x}")
            if field_off != offset:
                problems.append(f"{what} lands at 0x{field_off:x}, not 0x{offset:x}")
        return problems

    def _anchor_problems(self, data: bytes | bytearray) -> list[str]:
        """Everything the patch depends on and does not rewrite: the register allocation both hooks
        read, the constructor that says how many fields the structure has and how the latch byte is
        defaulted, the two mask predicates and the getter the cave calls, the sleep arithmetic that
        makes the arming hook's return value mean what it means, and the client's timer widget,
        whose "follows for free" is a claim about code this patch never touches."""
        problems: list[str] = []
        for va, expected in LIFETIME_ANCHORS.items():
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
            LIFETIME_ALLOC,
            LIFETIME_ALLOC_BYTES,
            _jmp_bytes(LIFETIME_ALLOC, pieces.alloc_va, len(LIFETIME_ALLOC_BYTES)),
            f"newModuleData -> a 0x{TOGGLE_MOUNTED_MODULE_DATA_SIZE:x}-byte ModuleData, "
            "zeroed past 0x18",
        )
        at(
            LIFETIME_FIELD_TABLE_REF,
            _u32(LIFETIME_FIELD_TABLE),
            _u32(pieces.table_va),
            f"buildFieldParse -> the {SECTION_NAME} field table",
        )
        at(
            LIFETIME_LATCH_DEFAULT,
            LIFETIME_LATCH_DEFAULT_BYTES,
            widened_latch_default(),
            "the LifetimeUpdate ctor -> the edge latch defaults to 'not held'",
        )
        at(
            LIFETIME_ARM,
            LIFETIME_ARM_BYTES,
            _jmp_bytes(LIFETIME_ARM, pieces.arm_va, len(LIFETIME_ARM_BYTES)),
            f"setLifetimeRange -> poll every frame while {self.keyword} is declared",
        )
        at(
            LIFETIME_UPDATE,
            LIFETIME_UPDATE_BYTES,
            _jmp_bytes(LIFETIME_UPDATE, pieces.update_va, len(LIFETIME_UPDATE_BYTES)),
            f"update -> pay {self.bonus_keyword} when {self.keyword} is gained",
        )
        at(
            LIFETIME_EXPIRE,
            LIFETIME_EXPIRE_BYTES,
            _jmp_bytes(LIFETIME_EXPIRE, pieces.expire_va, len(LIFETIME_EXPIRE_BYTES)),
            f"update -> become {self.template_keyword} instead of dying",
        )
        return edits
