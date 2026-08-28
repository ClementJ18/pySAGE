"""`LargeGroupBonusUpdate`: count loose objects, and gate the whole module on upgrades.

Two features over one module, in one patch because they are one structure. Targets the ROTWK
SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived in
``../docs/large-group-bonus.md``.

**`CountLooseObjects`.** `HordeMemberFilter` is an ordinary `ObjectFilter` - the same four-byte
interned handle `banner-filter` and `player-heal-filter` add, parsed by the same
`OBJECT_FILTER_PARSE_VA`, released by this module's own destructor at ``0x00893B75``. Nothing about
its grammar is horde-specific. It is horde-only because **it is never evaluated against the object
the partition scan returned**. It is only ever passed one level down, as an argument, to that
object's *contain* interface (vslot ``+0x180``), which counts its own contained members against it.
`Object::getContain` returns NULL for anything with no contain module, and both places that ask
treat NULL as contributing zero:

* `PARTITION_ALLOW_VA` - the `allow` of the filter wrapper `update` builds on its stack. A
  container-less object is rejected here, so the scan never even returns it.
* `COUNT_WINDOW_VA` - the accumulator loop, which repeats the same test.

So a lone hero, a unit outside a horde or a structure cannot be counted, whatever the filter says.
With the flag set, both gates additionally accept an object with no contain interface whose
`ThingTemplate` `HordeMemberFilter` itself matches, counting it as one.

**Both gates move together or neither does.** Widening only the accumulator achieves nothing,
because the partition filter has already removed loose objects from the iteration; widening only the
partition filter achieves nothing either, because the accumulator would then skip what the scan
handed it.

**`TriggeredBy` / `ConflictsWith`.** The module registers with interface mask ``1`` (`Update`) - no
`UpgradeMux` subobject, no `getUpgrade` vslot - so the upgrade keywords every `*Upgrade` module
takes were never wired to it. The gate this adds is the `UpgradeMux` *condition*, not its execute:
it is re-evaluated on every poll rather than latched, so there is no `StartsActive`, no `Permanent`
and no "already upgraded" bit. An upgrade arriving or being stripped takes effect on the next poll,
and this module never sleeps forever while its object is alive, so - unlike
`lifetime-extend-upgrade` - seeing the change costs no extra wake-ups.

An inactive module drops the bonus through the engine's own removal call and returns before the
partition scan, so switching it off is *cheaper* than leaving it on, and the falling edge is the
same one the stock count-came-up-short path takes.

**Why one patch and not two.** The two features are independent to a modder and inseparable in the
binary: they share the field-parse table (relocated once), the `ModuleData` (whose layout only one
owner can decide), and `update`'s register discipline. Split in two, each would have to tolerate
the other's edits to the same three sites; merged, the structure has one owner. This is the
`large-group-bonus-filter` patch of earlier versions with the upgrade gate folded in - a binary
carrying that older patch is not recognised by this one and has to be rebuilt from a clean image.

Five edits, one cave
--------------------
1. **The allocation.** `ModuleData` grows ``0x30`` -> ``0x158`` to hold two 36-dword upgrade masks
   and three bools. The nine bytes at `ALLOC_WINDOW_VA` - `newModuleData`'s ``push ecx`` /
   ``push esi`` / ``push 0x30`` / ``call operator new`` - become a jump into a cave stub that does
   the same with the larger size and zeroes everything past ``0x30``, then rejoins at the caller's
   ``pop ecx`` with the size argument still on the stack. `operator new` does not zero, so that
   loop **is** the defaults: no upgrade required, none conflicting, `CountLooseObjects = No`.
   Nothing else in the image reads this ``sizeof``, and the destructor's ``operator delete`` is the
   unsized form, so the growth ends here.
2. **The keywords.** The field-parse table at `FIELD_TABLE_VA` cannot grow in place - it ends at
   ``0x00C63A68`` where an unrelated ``.rdata`` path string begins. It is named by **exactly one**
   instruction, so the patch copies the eight stock rows verbatim - their name pointers are
   absolute and keep pointing into ``.rdata`` - appends five rows and the terminator, and repoints
   that imm32. Lookup is a linear name scan over a table in declaration order, so appending needs
   no re-sort, and this module inherits no second table, so there is no duplicate-keyword hazard of
   the kind `player-heal-filter` has to guard against.
3. **The upgrade gate.** The five bytes at `GATE_WINDOW_VA` (``mov eax,[TheGameLogic]``) become a
   jump into the gate stub, which tests the two masks and either resumes the stock body or drops
   the bonus and jumps to `update`'s tail. The window is one whole instruction with the owning
   `Object`, the `ModuleData` and the module all live, and it is the last one before the flags set
   at ``0x00893901`` are consumed - hence the ``pushfd``/``popfd`` around the stub.
4. **Gate 1 of the loose-object count.** The ten bytes at `SETUP_WINDOW_VA` (``lea eax,[edi+0xc]``
   plus the store of the wrapper vtable) become a ``call`` into a shim that does the same two
   things and then, only when the flag is set *and* `HordeMemberFilter` was actually written, swaps
   in a cave-built copy of the vtable whose `allow` is the widened one, parking the owning `Object`
   in the wrapper's free ``+4`` slot. Choosing the vtable rather than editing `PARTITION_ALLOW_VA`
   in place is what keeps the unwidened path byte-identical.
5. **Gate 2.** The 28 bytes at `COUNT_WINDOW_VA` - the whole "getContain, bail on null, else count"
   block plus its accumulate - become ``mov ecx,eax`` / ``call`` / ``add [ebp-0x18],eax`` and
   padding. The window is self-contained: its only inbound branch is the loop's own back edge at
   ``0x00893A01``, which lands on the first byte.

The cave holds the five keyword strings, the copied vtable, the rebuilt table and five stubs, in
that order - the renameable keyword first so :meth:`LargeGroupBonusPatch.detect` can read it
straight off the section base.

The four upgrade keywords are **not** renameable. They are the engine's own spellings, taken row
for row from the `UpgradeMuxData` base table at ``0x00C76AD8``, and a mod that writes them expects
them to mean there what they mean everywhere else.

Why the evaluator and not the wrapper
-------------------------------------
`0x007640C1` is a convenience wrapper around the real evaluator `OBJECT_FILTER_TEST_VA`, which takes
three arguments: the candidate's `ThingTemplate`, the candidate's `Player`, and the **source**
`Player` the filter is written from. The wrapper passes its own second parameter through as that
source and every stock call site passes ``0``; with a null source the evaluator rejects
unconditionally whenever the relationship mask is non-zero, so relationship tokens routed through it
do not degrade to permissive, they *always* return false. Both filter stubs here call the evaluator
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
therefore inert rather than sweeping. The upgrade gate needs no such companion test: an undeclared
mask reads as all-zero, and `MASK_ANY_VA` answering false is what makes it "no requirement".

**What this does not fix.** `AlliesOnly` is parsed by this module and read by nothing: the scan's
ownership rule is hardcoded in a second partition filter (``0x00660AFE``), a strict
``getControllingPlayer(candidate) == getControllingPlayer(owner)`` test. So a widened filter still
only ever sees the module owner's own objects, and `ENEMIES` / `NEUTRAL` / `ALLIES` can only narrow
to nothing. Honouring `AlliesOnly` means repointing the vtable store at ``0x0089396A``, whose vtable
is shared with twelve other sites - a separate patch, deliberately not this one.

**Determinism.** The bonus is applied through `AttributeModifier` on the logic-side `Object`, so
**every peer must run the same patched binary** and replays do not cross. And, as with
`terrain-resource-exp` and `queue-ignore-cp`, the new keywords are an INI **parse error** on a
stock build rather than a warning.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name,
no edited byte is shared with another bundled patch, and the structures read - the stock
`LargeGroupBonusUpdate` field-parse table, its `newModuleData` thunk and the wrapper vtable - are
ones nothing else rewrites. The nearest neighbour, `banner-filter`, lives in
``0x0089A7xx``-``0x0089AExx``.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import FIELD_PARSE_STRIDE, INI_PARSE_BOOL, OPERATOR_NEW
from ..asm import JA, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ALLOC_RESUME_VA",
    "ALLOC_WINDOW_BYTES",
    "ALLOC_WINDOW_VA",
    "ANCHORS",
    "ATTRIB_REMOVE_VA",
    "BONUS_HELD_OFFSET",
    "CONFLICTS_WITH_OFFSET",
    "COUNT_WINDOW_BYTES",
    "COUNT_WINDOW_VA",
    "DEFAULT_KEYWORD",
    "FIELD_TABLE_REF_VA",
    "FIELD_TABLE_VA",
    "FILTER_OFFSET",
    "FLAG_OFFSET",
    "GATE_RESUME_VA",
    "GATE_TAIL_VA",
    "GATE_WINDOW_BYTES",
    "GATE_WINDOW_VA",
    "MASK_ANY_VA",
    "MASK_DWORDS",
    "MASK_TEST_ALL_VA",
    "MASK_TEST_ANY_VA",
    "MODULEDATA_CTOR_CALL_VA",
    "MODULEDATA_CTOR_VA",
    "OBJECT_UPGRADES_COMPLETED",
    "PARSE_UPGRADE_MASK_VA",
    "PARTITION_ALLOW_VA",
    "PATCHED_MODULEDATA_SIZE",
    "PLAYER_UPGRADES_COMPLETED",
    "REQUIRES_ALL_CONFLICTING_OFFSET",
    "REQUIRES_ALL_TRIGGERS_OFFSET",
    "SECTION_NAME",
    "SETUP_WINDOW_BYTES",
    "SETUP_WINDOW_VA",
    "STOCK_FIELDS",
    "STOCK_MODULEDATA_SIZE",
    "TRIGGERED_BY_OFFSET",
    "UPGRADE_FIELDS",
    "WRAPPER_VTABLE_SLOTS",
    "WRAPPER_VTABLE_VA",
    "ZERO_DWORDS",
    "LargeGroupBonusPatch",
    "build_alloc",
    "build_count",
    "build_gate",
    "build_new_allow",
    "build_setup",
    "build_table",
    "validate_keyword",
]

# --- LargeGroupBonusUpdate, as this build lays it out (VA, ImageBase 0x400000) ---

#: `newModuleData`'s ``push ecx`` / ``push esi`` / ``push 0x30`` / ``call operator new``, and the
#: ``pop ecx`` that cleans the argument, which is where the cave rejoins. Nine bytes for a
#: ``jmp rel32`` and four of padding. The ``push 0x30`` is the sole `sizeof(ModuleData)` literal.
ALLOC_WINDOW_VA = 0x0064D122
ALLOC_WINDOW_BYTES = bytes.fromhex("51566a30e8b525deff")
ALLOC_RESUME_VA = 0x0064D12B

#: The ``call`` to the ModuleData constructor, inside `newModuleData`, and the ctor itself. The
#: ctor has exactly one caller, which is this site. **Not patched** - the grown tail is zeroed by
#: the allocation stub instead, which is what lets this patch hook one site fewer than the
#: `large-group-bonus-filter` it replaces. Anchored, so a binary carrying that older patch (which
#: redirected this call to a shim of its own) is refused rather than double-patched.
MODULEDATA_CTOR_CALL_VA = 0x0064D139
MODULEDATA_CTOR_VA = 0x00893871

STOCK_MODULEDATA_SIZE = 0x30
#: What the structure grows to: the stock ``0x30``, two `UpgradeMaskType`s and three bools, dword
#: aligned. `UpgradeMaskType` is 36 dwords - see ``../docs/upgrade-mask-limit.md``.
PATCHED_MODULEDATA_SIZE = 0x158
MASK_DWORDS = 0x24
#: What the allocation stub zeroes: everything past the stock structure.
ZERO_DWORDS = (PATCHED_MODULEDATA_SIZE - STOCK_MODULEDATA_SIZE) // 4

#: ``mov byte [esi+0x18], 1`` - `AlliesOnly`'s default. Anchored as a build fingerprint: it is the
#: last field the stock constructor writes before `FlagSubObjectNames`, and it says the structure
#: this patch grows is the one it thinks it is.
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

#: The upgrade gate's window: ``mov eax, [TheGameLogic]``, one whole instruction, five bytes, the
#: last before the KindOf branch at `GATE_RESUME_VA` consumes the flags set at ``0x00893901``.
GATE_WINDOW_VA = 0x0089390F
GATE_WINDOW_BYTES = bytes.fromhex("a12c41de00")
GATE_RESUME_VA = 0x00893914
THE_GAME_LOGIC = 0x00DE412C
#: `update`'s tail, past the iterator destructor and the four stack-filter vtable resets - so a
#: path that built neither may enter here. The stock ``ebx == NULL`` early-out at ``0x008938F1``
#: leaves the same frame state one step further on, which is what says this is legal.
GATE_TAIL_VA = 0x00893AF2
#: ``[ebp-0xd]``, the tail's "return `UpdateRate` or 1" selector; the stock body clears it at
#: ``0x00893932``, which the inactive path has jumped past.
SLEEP_SELECTOR_DISP8 = -0x0D
#: ``module+0x28`` / ``+0x29`` (``esi`` is biased ``+0x10``): "this object has the bonus", the pair
#: `0x008936BB` answers the `LargeGroupBonus` interface from.
BONUS_HELD_OFFSET = 0x18
BONUS_FLAG_OFFSET = 0x19

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

GET_CONTROLLING_PLAYER_VA = 0x0068B678  # __thiscall(ecx=Object*) -> Player*, NULL when unowned
#: ``Object::removeAttributeModifier`` - ``__thiscall(ecx=Object*, const AsciiString *)``,
#: ``ret 4``. The falling edge the stock body takes at ``0x00893ACB``, and the one the gate takes
#: when it switches a module off.
ATTRIB_REMOVE_VA = 0x0068F259
#: ``ModuleData+0x2c``, the `AttributeModifier` name both removal paths pass.
MODIFIER_OFFSET = 0x2C

# --- the ObjectFilter handle ABI (see docs/banner-carrier-filter.md) ---

OBJECT_FILTER_PARSE_VA = 0x0076392F  # the INI parse fn that goes in the field table
OBJECT_FILTER_IS_DEFINED_VA = 0x00762977  # __thiscall(ecx=&field) -> bool, reads the +0x88 flag
OBJECT_FILTER_TEST_VA = 0x00763543  # __thiscall(ecx=&field, template, player, source), ret 0xc

# --- the upgrade-mask ABI (see docs/upgrade-mask-limit.md, docs/lifetime-extend-upgrade.md) ---

PARSE_UPGRADE_MASK_VA = 0x0066F603  # the INI parse fn the two mask rows name
MASK_ANY_VA = 0x00444DCE  # __thiscall(ecx=&mask) -> al: is any bit set at all?
MASK_TEST_ANY_VA = 0x008097D6  # __thiscall(ecx=&held, &mask) -> al, ret 4
MASK_TEST_ALL_VA = 0x006AACB3  # ... and its all-of counterpart, same signature
#: The completed-upgrade masks an upgrade can be held in: the object's own, and its controlling
#: player's. `UpgradeMux` tests them one after the other rather than building a union, and so does
#: :func:`build_held`.
OBJECT_UPGRADES_COMPLETED = 0x28C
PLAYER_UPGRADES_COMPLETED = 0x14C

# --- layout ---

#: `HordeMemberFilter`, the `ObjectFilter` handle this patch reuses rather than adding another.
FILTER_OFFSET = 0x0C
#: The four `UpgradeMuxData` fields, and the loose-object flag behind them. All five land past the
#: stock structure, in the region :func:`build_alloc` zeroes - which is why none of them needs a
#: constructor shim to default it.
TRIGGERED_BY_OFFSET = 0x30
CONFLICTS_WITH_OFFSET = TRIGGERED_BY_OFFSET + MASK_DWORDS * 4
REQUIRES_ALL_TRIGGERS_OFFSET = CONFLICTS_WITH_OFFSET + MASK_DWORDS * 4
REQUIRES_ALL_CONFLICTING_OFFSET = REQUIRES_ALL_TRIGGERS_OFFSET + 1
FLAG_OFFSET = REQUIRES_ALL_CONFLICTING_OFFSET + 1

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

#: The four rows appended for the upgrade gate, as ``(name, parse fn, ModuleData offset)``. Copied
#: name for name and parser for parser from the `UpgradeMuxData` base table at ``0x00C76AD8``, at
#: this module's own offsets - the parse functions take the offset from the row, so the rows are
#: portable between blocks and these parse exactly as they do for `AllowBannerSpawnUpgrade`.
UPGRADE_FIELDS = (
    ("TriggeredBy", PARSE_UPGRADE_MASK_VA, TRIGGERED_BY_OFFSET),
    ("ConflictsWith", PARSE_UPGRADE_MASK_VA, CONFLICTS_WITH_OFFSET),
    ("RequiresAllTriggers", INI_PARSE_BOOL, REQUIRES_ALL_TRIGGERS_OFFSET),
    ("RequiresAllConflictingTriggers", INI_PARSE_BOOL, REQUIRES_ALL_CONFLICTING_OFFSET),
)

DEFAULT_KEYWORD = "CountLooseObjects"

SECTION_NAME = ".lgbupd"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds the copied vtable, the
# rebuilt table, the keyword strings and five stubs, so it is both read as data and entered as code.
SECTION_CHARACTERISTICS = 0x60000060

#: Byte windows the patch depends on and does not rewrite. The register anchors matter most: three
#: stubs read `edi` as the `ModuleData`, `ebx` as the owning `Object` and `esi` as the module, and
#: nothing the patch writes would catch a mismatch - the cave would simply dereference whatever the
#: registers held.
ANCHORS: dict[int, bytes] = {
    # `newModuleData` past the window: the `pop ecx` the allocation stub rejoins at, the null test
    # its zeroing has to respect, and ...
    ALLOC_RESUME_VA: bytes.fromhex("598bc8894df08365fc0085c97409"),
    # ... the ctor call this patch leaves alone. A binary carrying the older
    # `large-group-bonus-filter` has a shim here instead, and is refused by this anchor
    # rather than double-patched.
    MODULEDATA_CTOR_CALL_VA: bytes.fromhex("e833672400"),
    # the ctor's tail: `AlliesOnly`'s byte store, `RubOffRadius` four bytes later, the vector ctor
    # for `FlagSubObjectNames`, and `mov eax, esi` returning `this`
    ALLIES_ONLY_DEFAULT[0]: bytes.fromhex("c6461801f30f11461ce8f853beff83662c008b4df48bc6"),
    # `update`'s prologue: esi = the module, ebx = [esi-8] the owning Object
    0x008938E8: bytes.fromhex("8bf18b5ef8"),
    # ... edi = [esi-0xc], the ModuleData ...
    0x00893909: bytes.fromhex("8b7ef4"),
    # ... and the KindOf test whose flags the gate stub carries across itself
    0x00893901: bytes.fromhex("f6810901000001"),
    # the branch that consumes them, which is where the active path resumes
    GATE_RESUME_VA: bytes.fromhex("0f85b8000000"),
    # `and dword [ebp-0x4c], 0` - the wrapper's +4 slot, zeroed and read by nothing
    0x0089393F: bytes.fromhex("8365b400"),
    # `mov byte [ebp-0xd], 0` - the sleep selector the inactive path writes for itself
    0x00893932: bytes.fromhex("c645f300"),
    # the instruction after gate 1's window, which consumes the `lea`'s result
    0x00893950: bytes.fromhex("8945b8"),
    # the instruction after gate 2's window: the loop tail both the stock `je` and the replacement
    # fall through to
    0x008939F7: bytes.fromhex("8d4dec"),
    # the stock falling edge: `mov ecx,ebx` / `lea eax,[edi+0x2c]`, the argument shape the gate's
    # own removal reproduces ...
    0x00893A2A: bytes.fromhex("8bcb8d472c"),
    # ... and the call itself
    0x00893ACB: bytes.fromhex("50e888b7dfff"),
    # the re-entrable tail: the dead test, and the read of the sleep selector below it
    GATE_TAIL_VA: bytes.fromhex("f6835804000001"),
    0x00893B09: bytes.fromhex("807df300"),
    # the stock `allow` the cave's copy is modelled on, in full: getContain, bail on null, hand the
    # filter to +0x180, and the two-way polarity return the widened version reproduces
    PARTITION_ALLOW_VA: bytes.fromhex(
        "568bf18b4c2408e8e8bb020085c07416ff76088b108bc8ff928001000085c0"
        "76058a460ceb0833c038460c0f94c05ec20400"
    ),
    # `Object::getContain` itself: the null answer that makes a loose object invisible
    GET_CONTAIN_VA: bytes.fromhex("8b895802000085c9750333c0c38b01ff607c"),
    # `Object::getControllingPlayer` - the team hop, and the NULL both mask stubs allow for
    GET_CONTROLLING_PLAYER_VA: bytes.fromhex("8b891c03000085c97405e9e846110033c0c3"),
    # `Object::removeAttributeModifier`'s prologue: one stack argument, `ret 4`
    ATTRIB_REMOVE_VA: bytes.fromhex("558bec515356578b7d088b0785c08bf17406"),
    # `UpgradeMaskType::any()` - the 36-dword scan, ecx = the mask, no arguments
    MASK_ANY_VA: bytes.fromhex("33c0833c810075094083f82472f432c0c3b001c3"),
    # `testForAny` and `testForAll` - the same width, one stack argument, `ret 4`
    MASK_TEST_ANY_VA: bytes.fromhex(
        "8b44240433d22bc1568b34088531750f4283c10483fa2472f032c05ec20400"
    ),
    MASK_TEST_ALL_VA: bytes.fromhex(
        "8b4424045633f6572bc88b108b3c0123fa3bfa75104683c00483fe2472ecb0015f5ec2040032c0ebf7"
    ),
    # `INI::parseUpgradeMask`'s entry - the parser the two mask rows name, so a build where it
    # moved is refused rather than mis-parsed
    PARSE_UPGRADE_MASK_VA: bytes.fromhex("b86375b800e8e3d83c0083ec1453565768900000"),
}

# An INI keyword is matched by exact compare, so anything the parser could never match is a typo
# rather than a choice. The engine's own field names are CamelCase with digits and underscores.
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def validate_keyword(keyword: str) -> None:
    """Raise unless ``keyword`` is a token the engine's INI reader could ever match, and one this
    module does not already parse - the eight stock fields, or the four this patch appends beside
    it. A duplicate row would parse: the reader takes the first match and never complains, so the
    field would exist and silently write the wrong offset."""
    if not _KEYWORD_PATTERN.match(keyword):
        raise ValueError(
            "an INI keyword must be letters, digits and underscores starting with a letter "
            f"(the reader matches it by exact compare), got {keyword!r}"
        )
    taken = [name for name, _off in STOCK_FIELDS] + [name for name, _p, _o in UPGRADE_FIELDS]
    if any(keyword.lower() == name.lower() for name in taken):
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

    Pure arithmetic on the keyword's length, so :meth:`LargeGroupBonusPatch.apply` and
    :meth:`LargeGroupBonusPatch.verify` compute the same addresses from opposite directions.
    The renameable keyword is first so :meth:`LargeGroupBonusPatch.detect` can read it straight off
    the section base without knowing how long anything after it is."""

    keyword_va: int
    upgrade_vas: tuple[int, ...]
    vtable_va: int
    table_va: int
    alloc_va: int
    gate_va: int
    setup_va: int
    allow_va: int
    count_va: int


def _layout(base_va: int, keyword: str) -> _Layout:
    va = base_va + len(keyword) + 1
    upgrade_vas = []
    for name, _parse, _offset in UPGRADE_FIELDS:
        upgrade_vas.append(va)
        va += len(name) + 1

    vtable_va = va + (-va % 4)  # keep every dword after the strings aligned
    table_va = vtable_va + WRAPPER_VTABLE_SLOTS * 4
    rows = len(STOCK_FIELDS) + 1 + len(UPGRADE_FIELDS) + 1  # + the flag, + the terminator
    alloc_va = table_va + rows * FIELD_PARSE_STRIDE
    gate_va = alloc_va + len(build_alloc(alloc_va))
    setup_va = gate_va + len(build_gate(gate_va))
    allow_va = setup_va + len(build_setup(setup_va, 0, 0))
    count_va = allow_va + len(build_new_allow(allow_va))
    return _Layout(
        base_va,
        tuple(upgrade_vas),
        vtable_va,
        table_va,
        alloc_va,
        gate_va,
        setup_va,
        allow_va,
        count_va,
    )


# --- the cave's five stubs ---------------------------------------------------------------------


def build_table(keyword_va: int, upgrade_vas: tuple[int, ...], stock_rows: bytes) -> bytes:
    """The rebuilt field-parse table: the stock rows verbatim, the five new rows, the terminator.

    The stock rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are, in ``.rdata``, and only the new rows point into the
    cave."""
    rows = struct.pack("<IIII", keyword_va, INI_PARSE_BOOL, 0, FLAG_OFFSET)
    for (_name, parse, offset), name_va in zip(UPGRADE_FIELDS, upgrade_vas, strict=True):
        rows += struct.pack("<IIII", name_va, parse, 0, offset)
    return stock_rows + rows + bytes(FIELD_PARSE_STRIDE)


def build_alloc(base_va: int) -> bytes:
    """Allocate the grown `ModuleData` and zero everything the stock constructor will not write.

    Entered in place of `newModuleData`'s ``push ecx`` / ``push esi`` / ``push 0x30`` /
    ``call operator new``, and owes the caller all four effects: both displaced pushes, the block
    in ``eax``, and the size argument still on the stack for the ``pop ecx`` the cave rejoins at.

    The zeroing **is** the defaults. `parseUpgradeMask` memsets the mask it is given, so a block
    that declares a mask keyword would be fine either way; a block that declares none never reaches
    a parser at all, and `operator new` hands back whatever was in the heap. ``ecx`` and ``edx`` are
    dead across the window - the caller reloads ``ecx`` from ``[ebp+8]`` at ``0x0064D144`` - and
    ``esi`` is the value just pushed, so the loop borrows only what the stock code already
    clobbers."""
    a = Asm(base_va)
    a.emit(0x51)  # push ecx               ; the displaced slot reservation
    a.emit(0x56)  # push esi               ; the displaced save
    a.emit(0x68, _u32(PATCHED_MODULEDATA_SIZE))  # push 0x158
    a.call_absolute(OPERATOR_NEW)  # call <operator new>   ; cdecl: the arg stays
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "done")  # je .done              ; the caller tests for null too
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x50", STOCK_MODULEDATA_SIZE)  # lea  edx, [eax+0x30]  ; past the stock fields
    a.emit(0xB9, _u32(ZERO_DWORDS))  # mov  ecx, 74
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


def _emit_held(a: Asm) -> None:
    """Append the ``held`` subroutine to ``a``: is the mask at ``eax`` satisfied?

    ``dl`` picks any-of or all-of, ``ebx`` is the `Object`, the answer comes back in ``al``. It is
    emitted into the gate stub rather than built on its own so that :class:`~..asm.Asm` resolves
    the two ``call``s to it the same way it resolves every other branch - one routine, one set of
    labels, no address arithmetic done by hand.

    The engine's own idiom, in the engine's own order (`UpgradeMux`'s conflict test at
    ``0x008B901A``): the object's completed mask first, then its controlling player's, as two calls
    rather than one union. An unowned object answers on its own mask alone, since
    `getControllingPlayer` returns NULL rather than faulting.

    That two-call shape is also the limit of `RequiresAllTriggers`: a requirement split across an
    object-scoped and a player-scoped upgrade satisfies neither call, and so reads as unmet. It is
    what the stock mux does, and copying it is the point.

    The chosen test function and the mask are parked on the stack because both have to survive two
    ``__thiscall`` calls and every callee-saved register is spoken for: ``ebx``/``esi``/``edi`` are
    `update`'s and ``ebp`` is its frame."""
    a.label("held")
    a.emit(0xB9, _u32(MASK_TEST_ANY_VA))  # mov  ecx, <testForAny>
    a.emit(b"\x84\xd2")  # test dl, dl
    a.jcc_short(JE, "held_picked")
    a.emit(0xB9, _u32(MASK_TEST_ALL_VA))  # mov  ecx, <testForAll>
    a.label("held_picked")
    a.emit(0x51)  # push ecx               ; the test to run
    a.emit(0x50)  # push eax               ; the mask, kept for the second call
    a.emit(0x50)  # push eax               ; ... and as this call's argument
    a.emit(b"\x8d\x8b", _u32(OBJECT_UPGRADES_COMPLETED))  # lea ecx, [ebx+0x28c]
    a.emit(b"\xffT$")  # call dword [esp+8]    ; ret 4
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JNE, "held_yes")  # jne .yes              ; object-scoped
    a.emit(b"\x8b\xcb")  # mov  ecx, ebx
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "held_no")  # je .no                ; unowned -> its own mask alone
    a.emit(b"\xff4$")  # push dword [esp]      ; the mask again
    a.emit(b"\x8d\x88", _u32(PLAYER_UPGRADES_COMPLETED))  # lea ecx, [eax+0x14c]
    a.emit(b"\xffT$")  # call dword [esp+8]    ; ret 4
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JNE, "held_yes")
    a.label("held_no")
    a.emit(b"2\xc0")  # xor  al, al
    a.jmp_short("held_done")
    a.label("held_yes")
    a.emit(b"\xb0")  # mov  al, 1
    a.label("held_done")
    a.emit(b"\x83\xc4")  # add  esp, 8           ; the mask and the test
    a.emit(0xC3)  # ret


def build_gate(base_va: int) -> bytes:
    """The upgrade gate: resume the stock body, or drop the bonus and sleep.

    Entered in place of `update`'s ``mov eax, [TheGameLogic]``, with ``esi`` the module, ``ebx``
    the owning `Object`, ``edi`` the `ModuleData` and ``ebp`` the frame - and with the flags of the
    KindOf test at ``0x00893901`` live, which the branch at `GATE_RESUME_VA` consumes. Hence the
    ``pushfd``/``popfd``: the stub restores whatever the flags were rather than assuming which test
    set them. ``ecx`` is the `ThingTemplate` and is read again just past the resume point, so it is
    parked too.

    An undeclared mask is all-zero, so `any()` answering false is what makes each half optional: no
    `TriggeredBy` means nothing is required, no `ConflictsWith` means nothing blocks it, and a
    module that declares neither takes two calls and resumes - the only cost the stock
    configuration pays, once per frame per module.

    The inactive path is not merely "return early". It drops the bonus the way the stock falling
    edge does, through `ATTRIB_REMOVE_VA`, and only when the module actually holds it; then it
    clears the sleep selector and enters the tail, which never built the iterator or the four stack
    filters this path skipped. Gating here rather than at the count comparison is deliberate: the
    rub-off pass at ``0x00893A5D`` is not gated by the count and would hand the bonus straight back
    from a neighbour, and the partition scan would still run every `UpdateRate` frames for a module
    that is switched off.

    ``held`` is emitted behind the two exits, both of which are ``jmp``s, so nothing falls into
    it."""
    a = Asm(base_va)
    a.emit(0x9C)  # pushfd
    a.emit(0x51)  # push ecx               ; the ThingTemplate

    a.emit(b"\x8dO", TRIGGERED_BY_OFFSET)  # lea  ecx, [edi+0x30]
    a.call_absolute(MASK_ANY_VA)  # call <any()>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "conflicts")  # je .conflicts         ; nothing required
    a.emit(b"\x8dG", TRIGGERED_BY_OFFSET)  # lea  eax, [edi+0x30]
    a.emit(b"\xb6\x97", _u32(REQUIRES_ALL_TRIGGERS_OFFSET))  # movzx edx, byte [edi+0x150]
    a.call("held")  # call <held>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "inactive")  # je .inactive          ; required and not held

    a.label("conflicts")
    a.emit(b"\x8d\x8f", _u32(CONFLICTS_WITH_OFFSET))  # lea  ecx, [edi+0xc0]
    a.call_absolute(MASK_ANY_VA)  # call <any()>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "active")  # je .active            ; nothing conflicts
    a.emit(b"\x8d\x87", _u32(CONFLICTS_WITH_OFFSET))  # lea  eax, [edi+0xc0]
    a.emit(b"\xb6\x97", _u32(REQUIRES_ALL_CONFLICTING_OFFSET))  # movzx edx, [edi+0x151]
    a.call("held")  # call <held>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "inactive")  # jne .inactive         ; a conflict is held

    a.label("active")
    a.emit(0x59)  # pop  ecx
    a.emit(0x9D)  # popfd
    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov  eax, [0xde412c]  ; the displaced instruction
    a.jmp_absolute(GATE_RESUME_VA)

    a.label("inactive")
    a.emit(0x59)  # pop  ecx
    a.emit(0x9D)  # popfd
    a.emit(b"\x80~", BONUS_HELD_OFFSET, 0x00)  # cmp  byte [esi+0x18], 0
    a.jcc_short(JE, "quiet")  # je .quiet             ; never had it -> nothing to undo
    a.emit(b"\xc6F", BONUS_HELD_OFFSET, 0x00)  # mov  byte [esi+0x18], 0
    a.emit(b"\xc6F", BONUS_FLAG_OFFSET, 0x00)  # mov  byte [esi+0x19], 0
    a.emit(b"\x8dG", MODIFIER_OFFSET)  # lea  eax, [edi+0x2c]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\xcb")  # mov  ecx, ebx
    a.call_absolute(ATTRIB_REMOVE_VA)  # call <removeAttributeModifier> ; ret 4
    a.label("quiet")
    a.emit(b"\xc6E", _disp8(SLEEP_SELECTOR_DISP8), 0x00)  # mov byte [ebp-0xd], 0
    a.jmp_absolute(GATE_TAIL_VA)

    _emit_held(a)
    return a.finish()


def build_setup(base_va: int, vtable_va: int, stock_vtable_va: int) -> bytes:
    """Gate 1 of the loose-object count: build the partition-filter wrapper, choosing which `allow`
    it will dispatch to.

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
    a.emit(b"\x80\xbf", _u32(FLAG_OFFSET), 0x00)  # cmp byte [edi+0x152], 0
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
    """Gate 2 of the loose-object count: what one candidate contributes.

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
    a.emit(b"\x80\xbf", _u32(FLAG_OFFSET), 0x00)  # cmp byte [edi+0x152], 0
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


def alloc_hook_bytes(alloc_va: int) -> bytes:
    """`jmp rel32` to the allocation stub, padded to the nine bytes it displaces."""
    jump = b"\xe9" + struct.pack("<i", alloc_va - (ALLOC_WINDOW_VA + 5))
    return jump + b"\x90" * (len(ALLOC_WINDOW_BYTES) - len(jump))


def gate_hook_bytes(gate_va: int) -> bytes:
    """`jmp rel32` to the gate stub. The window is exactly five bytes, so there is no padding."""
    return b"\xe9" + struct.pack("<i", gate_va - (GATE_WINDOW_VA + 5))


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


class LargeGroupBonusPatch(Patch):
    """Give `LargeGroupBonusUpdate` a loose-object count and an upgrade gate."""

    name = "large-group-bonus"
    author = "officialNecro"
    description = (
        "Extend LargeGroupBonusUpdate: TriggeredBy / ConflictsWith / RequiresAllTriggers / "
        "RequiresAllConflictingTriggers gate the whole module on upgrades, and a "
        "CountLooseObjects boolean makes HordeMemberFilter also match objects that are not in a "
        "horde. All five default to the stock behaviour"
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
                "(the vtable, table, strings or stubs differ)"
            )
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        problems += self._table_problems(data, pieces)
        problems += self._anchor_problems(data)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> LargeGroupBonusPatch | None:
        """Recognise this patch **and recover its keyword**.

        The default probe would only ever recognise the default keyword. The renameable keyword is
        the first thing in the cave (:func:`_layout` puts it at the section base), so it reads
        straight back out; `verify` then checks the whole cave against it."""
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
        """The five fields this patch adds to `LargeGroupBonusUpdate`: the loose-object `Bool`
        under whatever keyword it was installed with, and the four `UpgradeMuxData` fields under
        the engine's own names.

        Every one of them lands in the region the allocation stub zeroes, so the defaults are "no
        requirement, no conflict, any-of, and no loose counting" - which is stock behaviour, and
        what makes all five opt-in."""
        upgrade_type = {PARSE_UPGRADE_MASK_VA: "Ref[]:upgrades", INI_PARSE_BOOL: "Bool"}
        fields = [FieldDelta("LargeGroupBonusUpdate", self.keyword, "Bool", False, self.name)]
        fields += [
            FieldDelta(
                "LargeGroupBonusUpdate",
                name,
                upgrade_type[parse],
                False if parse == INI_PARSE_BOOL else None,
                self.name,
            )
            for name, parse, _offset in UPGRADE_FIELDS
        ]
        return Engine(fields=tuple(fields))

    # --- CLI integration ---------------------------------------------------------------------

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the loose-object INI field to add to LargeGroupBonusUpdate (default "
                f"{DEFAULT_KEYWORD}); letters, digits and underscores, and must not already be one "
                "of the module's fields. The four upgrade keywords are the engine's own names and "
                "are not renameable"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> LargeGroupBonusPatch:
        return cls(keyword=args.keyword)

    # --- the cave ------------------------------------------------------------------------------

    def _build(self, base_va: int, stock_rows: bytes, stock_vtable: tuple[int, ...]) -> bytes:
        """The cave: the five keyword strings, the copied wrapper vtable, the rebuilt field table,
        and the five stubs - in that order, so :meth:`detect` finds the renameable keyword at the
        section base."""
        pieces = _layout(base_va, self.keyword)

        blob = bytearray(self.keyword.encode("ascii") + b"\x00")
        for name, _parse, _offset in UPGRADE_FIELDS:
            blob += name.encode("ascii") + b"\x00"
        blob += bytes(pieces.vtable_va - (base_va + len(blob)))

        # The copy differs from the stock vtable in exactly one slot: `allow`.
        slots = list(stock_vtable)
        slots[1] = pieces.allow_va
        blob += b"".join(_u32(slot) for slot in slots)

        blob += build_table(pieces.keyword_va, pieces.upgrade_vas, stock_rows)
        assert base_va + len(blob) == pieces.alloc_va, "the cave layout and its addresses disagree"

        blob += build_alloc(pieces.alloc_va)
        blob += build_gate(pieces.gate_va)
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
        silently. Read from the stock base rather than through the reference at `FIELD_TABLE_REF_VA`
        deliberately: this patch is the module's only extender, so a table that has already been
        relocated is a binary carrying an older version of it, and refusing is the honest answer."""
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
        then the five appended rows pointing at the cave's own strings."""
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

        appended = [(self.keyword, INI_PARSE_BOOL, FLAG_OFFSET), *UPGRADE_FIELDS]
        for index, (name, parse, offset) in enumerate(appended, start=len(STOCK_FIELDS)):
            name_va, parse_fn, _ud, field_off = struct.unpack_from(
                "<4I", data, off + index * FIELD_PARSE_STRIDE
            )
            got = _read_cstring(data, name_va)
            if got != name:
                problems.append(f"appended row {index} is {got!r}, not {name!r}")
            if parse_fn != parse:
                problems.append(
                    f"appended row {name!r} parses with 0x{parse_fn:08x}, not 0x{parse:08x}"
                )
            if field_off != offset:
                problems.append(f"appended row {name!r} lands at 0x{field_off:x}, not 0x{offset:x}")
        return problems

    def _anchor_problems(self, data: bytes | bytearray) -> list[str]:
        """Everything the patch depends on and does not rewrite.

        The register anchors are the ones that matter: the stubs read `edi` as the `ModuleData`,
        `ebx` as the owning `Object` and `esi` as the module, and a build that established them
        differently would send the cave dereferencing whatever the registers happened to hold. The
        rest say the gate's entry and exit points are where they are thought to be, that the helper
        functions the cave calls have not moved, and that the module's own allocation has not
        already been hooked by an older version of this patch."""
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
            ALLOC_WINDOW_VA,
            ALLOC_WINDOW_BYTES,
            alloc_hook_bytes(pieces.alloc_va),
            f"newModuleData -> a 0x{PATCHED_MODULEDATA_SIZE:x}-byte ModuleData, zeroed past "
            f"0x{STOCK_MODULEDATA_SIZE:x}",
        )
        at(
            FIELD_TABLE_REF_VA,
            _u32(FIELD_TABLE_VA),
            _u32(pieces.table_va),
            f"buildFieldParse -> the {SECTION_NAME} field table",
        )
        at(
            GATE_WINDOW_VA,
            GATE_WINDOW_BYTES,
            gate_hook_bytes(pieces.gate_va),
            "update's prologue -> the upgrade gate",
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
