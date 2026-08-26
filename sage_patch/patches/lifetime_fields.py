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
(`ARM_VA`) rolls one duration, stores an absolute death frame at ``module+0x20`` and *returns the
duration as the module's sleep*; `update` (`UPDATE_VA`) is then called once, on that frame, and
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
own `PARSE_DURATION_VA` - the same parse function `MinLifetime` and `MaxLifetime` use, which
multiplies by the live logic rate set at `0x00644F11`. So the stored value is already on the clock
`m_dieFrame` counts and the patch converts nothing.

**The in-world timer follows for free.** The bar over a summoned object is
`(die - now) / (die - start)`, recomputed every frame from the *live* module at
`UI_FRACTION_VA` - so pushing `m_dieFrame` out grows the remaining time and the total span
together, and the bar jumps up and then drains over the new total. Nothing client-side has to be
patched, and nothing reads the template's `MaxLifetime` to draw it. (This is also why *pausing*
the clock is the mechanic the stock UI cannot represent: the numerator would freeze while the
denominator kept growing, so the bar would drain to nothing over a live object. Freezing it would
mean pushing ``module+0x24`` along with the death frame.)

**The transform is the engine's own mount swap, called directly.**
`ToggleMountedSpecialAbilityUpdate`'s swap (`SWAP_VA`) reads three things off the module it is
called on - the `ModuleData` at ``+0x04``, the `Object` at ``+0x08``, and a success flag it writes
at ``+0x8c`` - makes **no virtual call on it**, and of that `ModuleData` reads only the template
name at `TEMPLATE_OFFSET` and the timer-sync vector behind it. `LifetimeUpdate`'s module has the
same first two offsets, and its `ModuleData` grows to `PATCHED_MODULEDATA_SIZE` - which is
`ToggleMountedSpecialAbilityUpdate`'s own ``sizeof`` - with the new keyword's row landing exactly
where `MountedTemplate` lands. So the cave builds a module-shaped scratch on the stack, hands it
the real `ModuleData` and `Object`, and calls the stock swap and the stock retire (`RETIRE_VA`,
which hides the drawable, drops it out of the UI and calls `GameLogic::destroyObject`). Health,
experience, team, position, facing, selection and contained passengers move exactly as they do
when a hero mounts, because it is the same code.

Six edits, one cave
-------------------
1. **The mask needs room, and `ModuleData` has none.** ``sizeof`` is ``0x18`` with two bytes of
   padding, against the ``0x90`` an `UpgradeMaskType` needs plus four for the bonus, and the
   transform needs its string at a fixed ``0xd8``, so the structure grows to
   `PATCHED_MODULEDATA_SIZE`. That is one hook, because `newModuleData`
   (`ALLOC_VA`) is **LifetimeUpdate's own thunk**: it calls the ModuleData constructor directly and
   nothing else in the image reaches either. The cave replaces the size and **zeroes everything it
   added**, which is required rather than tidy - for every `LifetimeUpdate` that does not declare
   the keywords the parsers never run, and `operator new` does not zero. Zeroing in the allocator
   rather than the constructor is what leaves the constructor's own five stores untouched.
2. **The keywords.** The field-parse table at `FIELD_TABLE_VA` is boxed in by its own keyword
   strings and its terminator, so it is rebuilt in the cave - five stock rows copied verbatim,
   since their name pointers are absolute, plus three rows and the terminator. It has **exactly
   one reference** in the image, the ``push`` immediate at `FIELD_TABLE_REF_VA`, and the reader
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
6. **The transform, ahead of the scoring arm.** `EXPIRE_VA` is `update`'s ``cmp`` of `ScoreKill`
   and the ``push esi`` after it - five bytes of two whole instructions, reached with ``ebx`` and
   ``edi`` already the `ModuleData` and the `Object` and with the `THROWN_PROJECTILE` reprieve
   already taken. Hooking *here* rather than at the kill is what keeps the score straight: the
   ``ScoreKill = No`` arm calls `ScoreKeeper::addObjectBuilt(obj, -1)` and so does the swap, so a
   hook below it would decrement twice for one transform. Returning takes the epilogue at
   `KILL_RETURN_VA`, which is the one the `THROWN_PROJECTILE` arm already returns through -
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

from ..addresses import FIELD_PARSE_STRIDE, GAME_LOGIC_FRAME, THE_GAME_LOGIC
from ..asm import JAE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ALLOC_BYTES",
    "ALLOC_RESUME_VA",
    "ALLOC_VA",
    "ANCHORS",
    "ARM_BYTES",
    "ARM_VA",
    "ASCIISTRING_IS_EMPTY_VA",
    "BONUS_OFFSET",
    "DEFAULT_BONUS_KEYWORD",
    "DEFAULT_KEYWORD",
    "DEFAULT_TEMPLATE_KEYWORD",
    "DIE_FRAME_OFFSET",
    "EXPIRE_BYTES",
    "EXPIRE_RESUME_VA",
    "EXPIRE_VA",
    "FIELD_TABLE_REF_VA",
    "FIELD_TABLE_VA",
    "GET_CONTROLLING_PLAYER_VA",
    "KILL_RETURN_VA",
    "LATCH_DEFAULT_BYTES",
    "LATCH_DEFAULT_VA",
    "LATCH_OFFSET",
    "LifetimeFieldsPatch",
    "MASK_ANY_VA",
    "MASK_DWORDS",
    "MASK_OFFSET",
    "MASK_TEST_ANY_VA",
    "OBJECT_UPGRADES_COMPLETED",
    "PARSE_ASCIISTRING_VA",
    "PARSE_DURATION_VA",
    "PARSE_UPGRADE_MASK_VA",
    "PATCHED_MODULEDATA_SIZE",
    "PLAYER_UPGRADES_COMPLETED",
    "RETIRE_VA",
    "SCRATCH_SIZE",
    "SECTION_NAME",
    "SLEEPY_UPDATE_DISPATCH_VA",
    "SLEEP_FOREVER",
    "START_FRAME_OFFSET",
    "STOCK_FIELDS",
    "STOCK_MODULEDATA_SIZE",
    "SWAP_FLAG_OFFSET",
    "SWAP_VA",
    "SYNC_SKIP_VA",
    "TEMPLATE_OFFSET",
    "UI_FRACTION_VA",
    "UI_MODULE_READ_VA",
    "UPDATE_BYTES",
    "UPDATE_RESUME_VA",
    "UPDATE_VA",
    "build_alloc",
    "build_arm",
    "build_expire",
    "build_held",
    "build_table",
    "build_update",
    "validate_keywords",
]

#: `LifetimeUpdate::newModuleData`'s ``push esi`` / ``push 0x18`` / ``call operator new``, and the
#: ``pop ecx`` that cleans the argument, which is where the cave rejoins. Eight bytes for a
#: ``jmp rel32`` and three of padding.
ALLOC_VA = 0x0064E096
ALLOC_BYTES = bytes.fromhex("566a18e84216deff")
ALLOC_RESUME_VA = 0x0064E09E
OPERATOR_NEW_VA = 0x0042F6E0

STOCK_MODULEDATA_SIZE = 0x18
#: Where the three new fields land, and what the structure grows to. `UpgradeMaskType` is 36 dwords
#: (see ``../docs/upgrade-mask-limit.md``) and `ModuleData` has two bytes of padding, so this is a
#: growth and not a hole - affordable only because the thunk that sizes it is private.
MASK_OFFSET = 0x18
MASK_DWORDS = 0x24
BONUS_OFFSET = MASK_OFFSET + MASK_DWORDS * 4
#: `MountedTemplate`'s offset in `ToggleMountedSpecialAbilityUpdate`'s `ModuleData`, which is what
#: `SWAP_VA` reads and therefore where the transform's keyword has to land - not a free choice.
#: The three dwords behind it are that module's `SynchronizeTimerOnSpecialPower` vector; zeroed,
#: they read as empty and the swap's timer pass does nothing (see `SYNC_SKIP_VA`).
TEMPLATE_OFFSET = 0xD8
#: `ToggleMountedSpecialAbilityUpdate`'s own ``sizeof``, which is what growing to `TEMPLATE_OFFSET`
#: plus that vector comes to. Nothing past the template is ever written; it is allocated and zeroed
#: so the vector the swap reads is an empty one rather than heap litter.
PATCHED_MODULEDATA_SIZE = 0xE8
#: What the allocator zeroes: everything past the stock structure.
ZERO_DWORDS = (PATCHED_MODULEDATA_SIZE - STOCK_MODULEDATA_SIZE) // 4

#: The 16-byte-stride field-parse table, and the single imm32 that loads it (inside
#: ``push 0xc31860`` at ``0x007A7E00``, so the operand starts one byte later).
FIELD_TABLE_VA = 0x00C31860
FIELD_TABLE_REF_VA = 0x007A7E01

#: The stock table in table order, as ``(name, ModuleData offset)``. Used as a fingerprint before
#: anything is written: all five names *and* offsets must match, which is a far stronger build
#: check than any single literal, and the rows are copied wholesale so a mismatch would otherwise
#: rebuild the table wrong and silently.
STOCK_FIELDS = (
    ("MinLifetime", 0x08),
    ("MaxLifetime", 0x0C),
    ("WaitForWakeUp", 0x10),
    ("ScoreKill", 0x11),
    ("DeathType", 0x14),
)

#: `INI::parseUpgradeMask`, the parse function the engine's own `TriggeredBy` row names.
PARSE_UPGRADE_MASK_VA = 0x0066F603
#: The duration parser `MinLifetime` and `MaxLifetime` use: **milliseconds in, frames out**, scaled
#: by the live logic rate (`0x00D9F610`, written from the frame rate at `0x00644F11`). Naming it
#: here is what makes the bonus authorable in the same units as the lifetime it extends, and
#: rate-independent without the patch doing any arithmetic.
PARSE_DURATION_VA = 0x0073A429
#: The `AsciiString` parse function, named by `MountedTemplate`'s own row - so the transform's
#: keyword is filled by the same code that fills the field `SWAP_VA` expects to read.
PARSE_ASCIISTRING_VA = 0x0042EE5E

#: `setLifetimeRange`'s tail: the death-frame store, the ``pop esi`` and the ``ret 8``. Seven
#: bytes, all three reproduced by the cave. ``esi`` is the module and ``eax`` the duration, which
#: is what the two call sites push as the sleep.
ARM_VA = 0x007A7DAE
ARM_BYTES = bytes.fromhex("894e205ec20800")

#: `LifetimeUpdate::update`'s prologue - ``push ebp`` / ``mov ebp,esp`` / ``push ecx`` /
#: ``push ebx``, exactly five bytes of whole instructions - and where the cave rejoins it.
UPDATE_VA = 0x007A7F8B
UPDATE_BYTES = bytes.fromhex("558bec5153")
UPDATE_RESUME_VA = 0x007A7F90

#: `update`'s `ScoreKill` test and the ``push esi`` behind it - five bytes of two whole
#: instructions, and the last point before either scoring arm runs. ``ebx`` is the `ModuleData`
#: and ``edi`` the `Object` here, and the `THROWN_PROJECTILE` reprieve above has already been
#: taken, so a projectile in flight never reaches the transform either.
EXPIRE_VA = 0x007A7FAF
EXPIRE_BYTES = bytes.fromhex("807b110056")
#: The ``je`` that picks a scoring arm, which is where the cave rejoins after re-executing the
#: displaced pair. It consumes the ``cmp``'s flags, so the cave has to set them again.
EXPIRE_RESUME_VA = 0x007A7FB4
#: `update`'s epilogue *before* its ``pop esi`` - ``pop edi`` / ``pop ebx`` / ``leave`` / ``ret``.
#: The stock `THROWN_PROJECTILE` arm returns through exactly this address from above the
#: ``push esi``, which is what makes it the right exit for a hook that displaced that push.
KILL_RETURN_VA = 0x007A8038
#: `update`'s "sleep forever" - what the stock kill returns, and what a completed transform
#: returns, since in both cases the object this module belongs to is on its way out.
SLEEP_FOREVER = 0x3FFFFFFF

#: `ToggleMountedSpecialAbilityUpdate`'s mount swap: ``__thiscall``, no arguments, and of the
#: module it is handed it reads only `MODULE_DATA_OFFSET` and `MODULE_OBJECT_OFFSET` and writes
#: only `SWAP_FLAG_OFFSET`. It makes no virtual call on that pointer, which is what lets a
#: `LifetimeUpdate` supply a plain stack frame in place of one.
SWAP_VA = 0x008B140D
#: The byte the swap sets last, after the replacement exists and everything has moved onto it. It
#: stays clear when `findTemplate` finds nothing or the build refuses, and it is the only way to
#: ask whether the transform happened.
SWAP_FLAG_OFFSET = 0x8C
#: The swap's timer pass, which walks the `SynchronizeTimerOnSpecialPower` vector at
#: ``ModuleData+0xdc``. Anchored because "a zeroed vector is safe to read" is the claim that lets
#: `LifetimeUpdate`'s grown `ModuleData` stand in: it compares ``+0xdc`` against ``+0xe0`` and
#: returns when they match.
SYNC_SKIP_VA = 0x008B12BF
#: The retire the mount toggle runs a step later: hide the drawable, drop the object out of the
#: UI, `GameLogic::destroyObject`. ``__thiscall``, and it reads `MODULE_OBJECT_OFFSET` and nothing
#: else. A retire is not a kill - no `DeathType`, no death FX, no `SlowDeathBehavior`, nothing
#: scored.
RETIRE_VA = 0x008B1E9A

#: `AsciiString::isEmpty()` - ``__thiscall(ecx = &AsciiString) -> al``, 1 when the buffer pointer
#: is NULL or its length word is zero. Clobbers ``eax`` alone, which is what lets the cave test the
#: keyword without spilling the two registers `update` handed it.
ASCIISTRING_IS_EMPTY_VA = 0x00401E64

#: The stack the cave hands the swap in place of a `ToggleMountedSpecialAbilityUpdate` instance:
#: that module's ``sizeof``, so `SWAP_FLAG_OFFSET` lands inside it. Only three slots are ever
#: touched - the two pointers and the flag - so the rest is left as whatever the stack held.
SCRATCH_SIZE = 0x90

#: The constructor's ``mov byte [esi+0x28], al`` with ``eax`` already zero, widened to a dword so
#: it clears the edge latch in the instance's tail padding as well. One byte changed, three for
#: three: the stores that follow it are untouched and `sizeof` does not move.
LATCH_DEFAULT_VA = 0x007A7F04
LATCH_DEFAULT_BYTES = bytes.fromhex("884628")

#: The module instance, as `update` and `setLifetimeRange` address it. `update` runs on the
#: `UpdateModule` subobject at ``module+0x10``, which is why it reads the others as negative
#: displacements - and why the cave's own reads are ``0x10`` lower than these.
MODULE_DATA_OFFSET = 0x04
MODULE_OBJECT_OFFSET = 0x08
UPDATE_THIS_DELTA = 0x10
DIE_FRAME_OFFSET = 0x20
START_FRAME_OFFSET = 0x24
#: The edge latch: was an upgrade in the mask held at the previous poll? Tail padding after the
#: `WaitForWakeUp` byte at ``+0x28``, inside the stock ``sizeof`` of ``0x2c``.
LATCH_OFFSET = 0x29

#: `UpgradeMaskType::any()` - ``__thiscall(ecx = mask) -> al``, no arguments - and
#: `testForAny(const UpgradeMaskType &)` - ``__thiscall``, ``ret 4``. Both are 36-dword loops that
#: touch only ``eax``/``ecx``/``edx`` and (in `testForAny`) a saved ``esi``.
MASK_ANY_VA = 0x00444DCE
MASK_TEST_ANY_VA = 0x008097D6

#: `Object::getControllingPlayer()` - ``__thiscall(ecx = Object*) -> Player*``, NULL for an
#: unowned object. It is ``mov ecx,[this+0x31c] / jmp Team::getControllingPlayer``, which is what
#: pins ``Object+0x31c`` as the team and therefore the object's mask as the one ending before it.
GET_CONTROLLING_PLAYER_VA = 0x0068B678

#: The two completed-upgrade masks the engine's own `UpgradeMux` test reads, in that order: the
#: object's own (object-scoped upgrades) and its controlling player's (player-scoped ones). An
#: upgrade is held if it is in either.
OBJECT_UPGRADES_COMPLETED = 0x28C
PLAYER_UPGRADES_COMPLETED = 0x14C

#: `GameLogic`'s sleepy-update driver, the one site that calls an `UpdateModule`'s `update`. It
#: reads ``lea ecx,[module+0x10]``, takes the return as a **sleep in frames** (clamped to a minimum
#: of 1) and stores ``now + sleep`` into the module's wake frame at ``+0x14``. Both hooks depend on
#: all three of those, and none of them is checkable from `LifetimeUpdate` alone.
SLEEPY_UPDATE_DISPATCH_VA = 0x0062EA97

#: The client's timer-widget source: it finds the `LifetimeUpdate` module by class name, skips it
#: while the `WaitForWakeUp` byte at ``+0x28`` is set, and otherwise reads the death frame and the
#: start frame straight off the instance...
UI_MODULE_READ_VA = 0x0092F7C5
#: ... and turns them into the bar's fill, ``(die - now) / (die - start)``, every frame. The patch
#: writes nothing here; it is anchored because "the in-world timer follows the extension" is a
#: claim about *this* code, and a build that computed the fill from the template's `MaxLifetime`
#: instead would leave the bar stuck while the object lived on.
UI_FRACTION_VA = 0x0092F8C8

DEFAULT_KEYWORD = "ExtendedByUpgrades"
DEFAULT_BONUS_KEYWORD = "UpgradeLifetimeBonus"
DEFAULT_TEMPLATE_KEYWORD = "ExpirationTemplate"

SECTION_NAME = ".lifeext"  # 8 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds the keyword strings and
# the rebuilt table as well as four stubs, so it is both read as data and entered as code.
SECTION_CHARACTERISTICS = 0x60000060

#: Byte windows the patch depends on and does not rewrite. The register anchors matter most: the
#: cave reads ``esi`` as the module in `setLifetimeRange` and ``[ecx-0xc]``/``[ecx-8]`` as the
#: `ModuleData`/`Object` in `update`, and nothing the patch writes would catch a build that
#: allocated them differently - the cave would simply dereference whatever the registers held.
ANCHORS: dict[int, bytes] = {
    # `setLifetimeRange`'s prologue: esi = the module, and the two duration arguments
    0x007A7D7E: bytes.fromhex("566a7668e017c300ff7424148bf1ff742414"),
    # ... and its tail up to the hook: the duration clamp, TheGameLogic's frame, m_startFrame
    0x007A7D98: bytes.fromhex("83f801730333c0408b0d2c41de008b4940894e2403c8"),
    # the ModuleData constructor, in full: the five stock fields, and no sixth
    0x007A7E0B: bytes.fromhex("8bc133c9c700307ac00089480889480c884810884811894814c3"),
    # `setLifetimeRangeAndWake`: the call, and the `push eax` handing the return to setWakeFrame
    0x007A7E4C: bytes.fromhex("e82dffffff50ff76088bcee8d68d0a005ec2"),
    # `wakeUp`, which clears the WaitForWakeUp byte at +0x28 with a *byte* store - the reason the
    # latch at +0x29 is the module's own and nothing else writes it
    0x007A7E6F: bytes.fromhex("817c2404ffffff3f740cc641180083c1f0e8dbffffff"),
    # the two stores that follow the widened one, and `eax` being zero across all three
    0x007A7F02: bytes.fromhex("33c0"),
    0x007A7F07: bytes.fromhex("894620894624"),
    # ... and the WaitForWakeUp latch, written as a byte after the zeroing
    0x007A7F27: bytes.fromhex("8a481080f901884e28"),
    # the constructor's arming path, which hands setLifetimeRange's return to setWakeFrame
    0x007A7F6A: bytes.fromhex("e80ffeffff50ff76088bcee8b88c0a00"),
    # `update` past the prologue: ebx = [ecx-0xc], edi = [ecx-8], then the THROWN_PROJECTILE gate
    # whose `return 1` is the idiom the poll reuses
    UPDATE_RESUME_VA: bytes.fromhex("8b59f4578b79f8689a0000008bcfe87569ccff84c07408"),
    # ... and the arm that gate takes: `return 1` through KILL_RETURN_VA, from above the
    # `push esi`. The transform's exit is this one, so a build that returned through the pop
    # instead would be refused rather than unbalancing the stack
    0x007A7FA7: bytes.fromhex("33c040e989000000"),
    # the `je` the displaced pair falls into, so the cave rejoins a branch that is still there
    EXPIRE_RESUME_VA: bytes.fromhex("743b8db75c020000"),
    # the sleep-forever the stock kill returns, and the epilogue behind it: `pop esi` is *last*
    # in, so KILL_RETURN_VA is the entry for a path that never pushed it
    0x007A8032: bytes.fromhex("b8ffffff3f5e5f5bc9c3"),
    # the mount swap from its entry: the frame it sets up, ModuleData at +4, the template at
    # +0xd8, findTemplate, the null exit that leaves the flag clear, and the Object at +8. Every
    # offset the scratch has to satisfy, and the entry the cave calls
    SWAP_VA: bytes.fromhex(
        "b8a82bba00e8d9ba180081ecd40000005356578bf98b47048b0d404ade0005d8000000"
        "50897de8e8ccfee1ff85c08945ec0f843d0200008b7f088bcfe8c5cbe5ff"
    ),
    # ... and its tail: the success flag at +0x8c, then the register restores that make the swap
    # safe to call with `ebx` and `edi` still holding the caller's ModuleData and Object
    0x008B167A: bytes.fromhex("c6838c000000018b4df45f5e64890d000000005b"),
    # the timer pass: `+0xdc` against `+0xe0`, and the jump taken when they match - which is what
    # makes a zeroed vector in the grown ModuleData an empty one rather than a fault
    SYNC_SKIP_VA: bytes.fromhex("558bec5151538b59048d83dc0000008b103b500456570f848200"),
    # the retire, reading the Object off +8 and nothing else off the pointer it is given
    RETIRE_VA: bytes.fromhex("568b71088bcee8eaa2ddff8bcee842a8ddff8bcee860c1e5"),
    # `AsciiString::isEmpty` in full: NULL buffer or zero length -> 1, and `eax` is all it touches
    ASCIISTRING_IS_EMPTY_VA: bytes.fromhex("8b0185c0740a6683780400740333c0c333c040c3"),
    # `MountedTemplate`'s row and the `SynchronizeTimerOnSpecialPower` row behind it, verbatim:
    # the parse function the transform's row copies and the two offsets the grown ModuleData has
    # to reproduce, read from the engine's own table rather than asserted
    0x00C05A48: bytes.fromhex("b859c0005eee420000000000d80000009859c000d6ee420000000000dc000000"),
    # `newModuleData`'s ctor call and the null test the cave's zeroing has to respect
    0x0064E09E: bytes.fromhex("598bc8894df08365fc0085c97409e85a9d1500"),
    # `UpgradeMaskType::any()` - the 36-dword scan, ecx = the mask, no arguments
    MASK_ANY_VA: bytes.fromhex("33c0833c810075094083f82472f432c0c3b001c3"),
    # `testForAny` - the same width, one stack argument, `ret 4`
    MASK_TEST_ANY_VA: bytes.fromhex(
        "8b44240433d22bc1568b34088531750f4283c10483fa2472f032c05ec20400"
    ),
    # `Object::getControllingPlayer` - the team hop that pins Object+0x31c
    GET_CONTROLLING_PLAYER_VA: bytes.fromhex("8b891c03000085c97405e9e846110033c0c3"),
    # `UpdateModule::setWakeFrame`: `frame = TheGameLogic->frame + delta`, which is what makes the
    # value the arming hook returns a sleep rather than a frame
    0x00850C32: bytes.fromhex("a12c41de008b5040035424085251ff74240c8bc8"),
    # the sleepy-update driver, the whole contract both hooks rely on: `update` is called on the
    # `module+0x10` interface, its return is a delta clamped to a minimum of 1, and the next wake
    # is recomputed as `now + delta` at the moment of the call - so a poll of 1 is every frame and
    # cannot drift
    SLEEPY_UPDATE_DISPATCH_VA: bytes.fromhex(
        "8d4b108b01ff1083f8018945ec7d07c745ec0100000083a60401000000"
        "a12c41de008b40408b4dec03c1b9ffffff3f3bc10f47c1894314"
    ),
    # `INI::parseUpgradeMask`'s entry, and the ms -> frames duration parser: the two functions the
    # appended rows name, so a build where either moved is refused rather than mis-parsed
    PARSE_UPGRADE_MASK_VA: bytes.fromhex("b86375b800e8e3d83c0083ec1453565768900000"),
    PARSE_DURATION_VA: bytes.fromhex(
        "558bec518b4d086a00e86838cfff8b4d0850e80246cfff85c08945fcdb45"
    ),
    # the client's timer widget: the module lookup, the WaitForWakeUp skip, and the two loads that
    # make the bar follow the death frame this patch moves
    UI_MODULE_READ_VA: bytes.fromhex(
        "8b7d0cff35e0a3de008bcfe8d0c5d5ff3bc6741480782800750e895de08b50248b4820e9db000000"
    ),
    # ... and the fill itself: remaining / span, both derived from the live module every frame
    UI_FRACTION_VA: bytes.fromhex(
        "3bca0f869f000000a12c41de008b40408bf12bf085f68975ecdb45ec7d06d8059886bd00"
        "8bf12bf285f68975ecdb45ec7d06d8059886bd003bc1def9d95de877"
    ),
}

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
        if any(name.lower() == stock.lower() for stock, _off in STOCK_FIELDS):
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
    alloc_va = table_va + (len(STOCK_FIELDS) + 4) * FIELD_PARSE_STRIDE  # + 3 rows + terminator
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
    mask_row = struct.pack("<IIII", keyword_va, PARSE_UPGRADE_MASK_VA, 0, MASK_OFFSET)
    bonus_row = struct.pack("<IIII", bonus_keyword_va, PARSE_DURATION_VA, 0, BONUS_OFFSET)
    template_row = struct.pack(
        "<IIII", template_keyword_va, PARSE_ASCIISTRING_VA, 0, TEMPLATE_OFFSET
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
    a.emit(0x68, _u32(PATCHED_MODULEDATA_SIZE))  # push 0xac
    a.call_absolute(OPERATOR_NEW_VA)  # call <operator new>
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "done")  # je .done              ; the caller tests for null too
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x50", STOCK_MODULEDATA_SIZE)  # lea  edx, [eax+0x18]  ; past the stock fields
    a.emit(0xB9, _u32(ZERO_DWORDS))  # mov  ecx, 37
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.label("zero")
    a.emit(b"\x89\x02")  # mov  [edx], eax
    a.emit(b"\x83\xc2\x04")  # add  edx, 4
    a.emit(0x49)  # dec  ecx
    a.jcc_short(JNE, "zero")  # jne .zero
    a.emit(0x58)  # pop  eax
    a.label("done")
    a.jmp_absolute(ALLOC_RESUME_VA)
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
    a.emit(b"\x89\x4e", DIE_FRAME_OFFSET)  # mov  [esi+0x20], ecx  ; the displaced store
    a.emit(0x50)  # push eax               ; the stock sleep
    a.emit(b"\x8b\x4e", MODULE_DATA_OFFSET)  # mov  ecx, [esi+4]     ; the ModuleData
    a.emit(b"\x83\xc1", MASK_OFFSET)  # add  ecx, 0x18        ; &the mask
    a.call_absolute(MASK_ANY_VA)  # call <any()>
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
    a.emit(b"\x8d\x8e", _u32(OBJECT_UPGRADES_COMPLETED))  # lea ecx, [esi+0x28c]
    a.call_absolute(MASK_TEST_ANY_VA)  # call <testForAny>     ; ret 4
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JNE, "yes")  # jne .yes              ; object-scoped
    a.emit(b"\x8b\xce")  # mov  ecx, esi
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)  # call <getControllingPlayer>
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "no")  # je .no                ; unowned -> not held
    a.emit(b"\x8d\x88", _u32(PLAYER_UPGRADES_COMPLETED))  # lea ecx, [eax+0x14c]
    a.emit(0x57)  # push edi
    a.call_absolute(MASK_TEST_ANY_VA)  # call <testForAny>     ; its al is ours
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
    a.emit(b"\x8b\x59", _disp8(-UPDATE_THIS_DELTA + MODULE_DATA_OFFSET))  # mov ebx, [ecx-0xc]
    a.emit(b"\x8b\x71", _disp8(-UPDATE_THIS_DELTA + MODULE_OBJECT_OFFSET))  # mov esi, [ecx-8]
    a.emit(b"\x8d\x7b", MASK_OFFSET)  # lea  edi, [ebx+0x18]  ; &the mask
    a.emit(0x51)  # push ecx
    a.emit(b"\x8b\xcf")  # mov  ecx, edi
    a.call_absolute(MASK_ANY_VA)  # call <any()>
    a.emit(0x59)  # pop  ecx
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "stock")  # je .stock             ; no keyword -> stock, bit for bit

    a.emit(0x51)  # push ecx
    a.call_absolute(held_va)  # call <held>           ; al = held now
    a.emit(0x59)  # pop  ecx
    a.emit(b"\x8a\x51", _disp8(LATCH_OFFSET - UPDATE_THIS_DELTA))  # mov dl, [ecx+0x19]
    a.emit(b"\x88\x41", _disp8(LATCH_OFFSET - UPDATE_THIS_DELTA))  # mov [ecx+0x19], al
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "due")  # je .due               ; not held -> latch cleared, nothing paid
    a.emit(b"\x84\xd2")  # test dl, dl
    a.jcc(JNE, "due")  # jne .due              ; held last frame too -> not an edge
    a.emit(b"\x8b\x93", _u32(BONUS_OFFSET))  # mov edx, [ebx+0xa8]   ; the bonus, in frames
    a.emit(b"\x01\x51", _disp8(DIE_FRAME_OFFSET - UPDATE_THIS_DELTA))  # add [ecx+0x10], edx

    a.label("due")
    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov  eax, [TheGameLogic]
    a.emit(b"\x8b\x40", GAME_LOGIC_FRAME)  # mov  eax, [eax+0x40]  ; now
    a.emit(b"\x3b\x41", _disp8(DIE_FRAME_OFFSET - UPDATE_THIS_DELTA))  # cmp eax, [ecx+0x10]
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
    a.emit(UPDATE_BYTES)  # the displaced prologue
    a.jmp_absolute(UPDATE_RESUME_VA)
    return a.finish()


def build_expire(base_va: int) -> bytes:
    """`update`'s expiry, one branch earlier: become the template, or fall through to the stock
    death.

    Entered with ``ebx`` = the `ModuleData`, ``edi`` = the `Object` and ``esi`` **not yet pushed**,
    in place of the `ScoreKill` test and the push behind it. With no template declared the two
    displaced instructions are re-executed and the function carries on, byte for byte - ``push``
    sets no flags, so the ``cmp`` can go second and land its answer directly in the ``je`` the cave
    returns to.

    The transform hands `SWAP_VA` a stack frame where a `ToggleMountedSpecialAbilityUpdate`
    instance would be. Three slots is all it reads: the `ModuleData`, whose grown tail holds the
    template name exactly where `MountedTemplate` lives, the `Object`, and the flag - cleared
    first, because it is the only way to tell a swap that happened from one the template store
    refused. The swap preserves ``ebx`` and ``edi``, so the abort arm still has what the stock path
    needs.

    `RETIRE_VA` is called immediately rather than a step later the way the mount toggle reaches it,
    because there is no pack animation to wait through: the replacement already carries everything
    and `destroyObject` is deferred to the end of the frame either way."""
    a = Asm(base_va)
    a.emit(b"\x8d\x8b", _u32(TEMPLATE_OFFSET))  # lea  ecx, [ebx+0xd8]  ; &the template
    a.call_absolute(ASCIISTRING_IS_EMPTY_VA)  # call <isEmpty>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "stock")  # jne .stock            ; no keyword -> stock, bit for bit

    a.emit(b"\x81\xec", _u32(SCRATCH_SIZE))  # sub  esp, 0x90        ; the module-shaped scratch
    a.emit(b"\x89\x5c\x24", MODULE_DATA_OFFSET)  # mov [esp+4], ebx
    a.emit(b"\x89\x7c\x24", MODULE_OBJECT_OFFSET)  # mov [esp+8], edi
    a.emit(b"\xc6\x84\x24", _u32(SWAP_FLAG_OFFSET), 0x00)  # mov byte [esp+0x8c], 0
    a.emit(b"\x8b\xcc")  # mov  ecx, esp
    a.call_absolute(SWAP_VA)  # call <the mount swap>
    a.emit(b"\x80\xbc\x24", _u32(SWAP_FLAG_OFFSET), 0x00)  # cmp byte [esp+0x8c], 0
    a.jcc(JE, "abort")  # je .abort             ; no such template -> die as stock
    a.emit(b"\x8b\xcc")  # mov  ecx, esp
    a.call_absolute(RETIRE_VA)  # call <hide, deselect, destroy>
    a.emit(b"\x81\xc4", _u32(SCRATCH_SIZE))  # add  esp, 0x90
    a.emit(0xB8, _u32(SLEEP_FOREVER))  # mov  eax, 0x3fffffff
    a.jmp_absolute(KILL_RETURN_VA)  # the epilogue above the `pop esi`

    a.label("abort")
    a.emit(b"\x81\xc4", _u32(SCRATCH_SIZE))  # add  esp, 0x90
    a.label("stock")
    a.emit(0x56)  # push esi              ; the displaced pair, flags last
    a.emit(EXPIRE_BYTES[:-1])  # cmp  byte [ebx+0x11], 0
    a.jmp_absolute(EXPIRE_RESUME_VA)
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
    widened = bytes((0x89,)) + LATCH_DEFAULT_BYTES[1:]
    assert len(widened) == len(LATCH_DEFAULT_BYTES)
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

    def _copied_rows(self, data: bytes | bytearray, pieces: _Layout) -> bytes:
        off = va_to_offset(data, pieces.table_va)
        if off is None:
            raise ValueError(f"the rebuilt table at 0x{pieces.table_va:08x} is not mapped")
        return bytes(data[off : off + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE])

    def _table_problems(self, data: bytes | bytearray, pieces: _Layout) -> list[str]:
        """What the rebuilt table has to spell: the five stock names still at their stock offsets,
        then the mask and the bonus, each parsed by the engine function that gives it its type and
        landing in the space the grown `ModuleData` bought."""
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

        appended = (
            (self.keyword, PARSE_UPGRADE_MASK_VA, MASK_OFFSET, "the upgrade mask"),
            (self.bonus_keyword, PARSE_DURATION_VA, BONUS_OFFSET, "the millisecond bonus"),
            (
                self.template_keyword,
                PARSE_ASCIISTRING_VA,
                TEMPLATE_OFFSET,
                "the expiration template",
            ),
        )
        for index, (keyword, parser, offset, what) in enumerate(appended):
            row = off + (len(STOCK_FIELDS) + index) * FIELD_PARSE_STRIDE
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
            ALLOC_VA,
            ALLOC_BYTES,
            _jmp_bytes(ALLOC_VA, pieces.alloc_va, len(ALLOC_BYTES)),
            f"newModuleData -> a 0x{PATCHED_MODULEDATA_SIZE:x}-byte ModuleData, zeroed past 0x18",
        )
        at(
            FIELD_TABLE_REF_VA,
            _u32(FIELD_TABLE_VA),
            _u32(pieces.table_va),
            f"buildFieldParse -> the {SECTION_NAME} field table",
        )
        at(
            LATCH_DEFAULT_VA,
            LATCH_DEFAULT_BYTES,
            widened_latch_default(),
            "the LifetimeUpdate ctor -> the edge latch defaults to 'not held'",
        )
        at(
            ARM_VA,
            ARM_BYTES,
            _jmp_bytes(ARM_VA, pieces.arm_va, len(ARM_BYTES)),
            f"setLifetimeRange -> poll every frame while {self.keyword} is declared",
        )
        at(
            UPDATE_VA,
            UPDATE_BYTES,
            _jmp_bytes(UPDATE_VA, pieces.update_va, len(UPDATE_BYTES)),
            f"update -> pay {self.bonus_keyword} when {self.keyword} is gained",
        )
        at(
            EXPIRE_VA,
            EXPIRE_BYTES,
            _jmp_bytes(EXPIRE_VA, pieces.expire_va, len(EXPIRE_BYTES)),
            f"update -> become {self.template_keyword} instead of dying",
        )
        return edits
