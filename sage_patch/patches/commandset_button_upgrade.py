"""Buying **single command buttons** with an upgrade, not a whole `CommandSet` per combination.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/commandset-button-upgrade.md``.

**What the engine does today.** An object's command bar comes from one named `CommandSet`, and
the only stock way to change it at runtime is `CommandSetUpgrade`, which swaps the whole set for
another one named in INI. So "this unit can buy any of four abilities" costs 16 hand-written
`CommandSet` blocks and 16 modules, one per combination, and a fifth ability doubles that.

**What this does.** Adds one keyword to `CommandSetUpgrade`:

.. code-block:: none

    Behavior = CommandSetUpgrade ModuleTag_Spear
      TriggeredBy    = Upgrade_BuySpear
      CommandButtons = Command_ThrowSpear:5 Command_BraceSpear
    End

Each token is a `CommandButton` name, optionally followed by ``:`` and a **slot number**; a bare
name takes the lowest free slot. The module then no longer replaces the set - it **overlays those
buttons onto whatever set the object would otherwise show**, and several such modules on one
object accumulate.

How the set is built
--------------------
The engine already does exactly this, for Create-A-Hero: `0x00809FFB` formats a name, creates a
**mutable** `CommandSet` under it, copies a base set's buttons in, overlays its own
``(button, slot)`` table and points the object at the result. This patch reuses that shape.

On each change the cave **rebuilds the union from scratch** rather than adding to what is there:
it walks `Object+0x24C`, takes every `CommandSetUpgrade` module that is currently applied, and
from them derives a base set (the last applied module naming a plain `CommandSet`, else the
object's `ThingTemplate`) and the list of overlays. The synthetic set's name is that base plus
each overlay's tokens, so it is a pure function of the applied set - which makes the operation
idempotent, order-independent, and the same on every peer. The name is then looked up before it
is created, so each distinct combination is built once and cached in `TheCommandSetStore`.

Rebuilding rather than accumulating is also what makes **removal** work. Mux slot ``+0x18``
(`0x008B7CAB`) runs on every module on every `Object::updateUpgradeModules` pass and calls
`unUpgradeImplementation` and then `attemptUpgrade`, so the whole set of modules is reset and
re-evaluated; hooking both halves means a `ConflictsWith` that revokes an upgrade takes its
button away again.

An object with no `CommandButtons` module runs stock bytes
----------------------------------------------------------
Both hooks open by scanning the object's modules for a `CommandSetUpgrade` whose `CommandButtons`
is non-empty. If there is none, they jump back into the stock function with the displaced
instructions re-executed, so a mod that does not use the keyword is byte-for-byte unaffected -
including the parts of the stock behaviour this patch deliberately does not reproduce, such as
`unUpgradeImplementation` only clearing the object's override when it is the one this module set.

The slot bound is read at runtime
---------------------------------
How many slots a `CommandSet` has is `commandset-limit`'s business, and the cave must agree with
whatever that patch installed - including when it is applied *after* this one. So the copy loop
and the free-slot search take their bound at **run time**, from the ``imm8`` of the
``cmp edx, N`` guard inside `CommandSet::setCommandButton` (`0x0080C8FE`) - the one byte that
always holds the live limit. Neither patch writes bytes the other reads at apply time, so the two
compose in either order.

Composition
-----------
Order-independent. The cave is allocated with :func:`~..utils.allocate_section` past every
existing section and :meth:`verify` finds it by name; the six byte ranges it rewrites are touched
by no other bundled patch; and the field table is located through the reference that names it
(:func:`~.utils.field_tables.resolve_table`) rather than by its stock address, so a patch that
relocated it first would be followed rather than bypassed.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..asm import JA, JE, JGE, JL, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import ROW_SIZE, Entry, entries_before, read_field_table, resolve_table
from .utils.name_tables import read_cstring
from .utils.token_lists import (
    ASCII_STRING_CHARS,
    ASCII_STRING_CONCAT_CHAR,
    ASCII_STRING_CONCAT_CSTR,
    ASCII_STRING_DTOR,
    ASCII_STRING_SET,
    SEPARATOR,
    build_list_parser,
)

__all__ = [
    "ANCHORS",
    "COMMAND_BUTTONS_OFFSET",
    "COMMAND_SET_OFFSET",
    "CommandSetButtonUpgradePatch",
    "FIELD_TABLE_REF_VA",
    "FIELD_TABLE_VA",
    "KEYWORD",
    "MAX_NAME",
    "MODULE_DATA_SIZE",
    "MODULE_DATA_SIZE_VA",
    "MODULE_VTABLE",
    "SECTION_NAME",
    "SET_BUTTON_BOUND_IMM8_VA",
    "SLOT_SEPARATOR",
    "UNUPGRADE_IMPL_VA",
    "UPGRADE_IMPL_VA",
    "build_code",
]

#: The keyword this patch adds to `CommandSetUpgrade`, and the character that separates a button
#: name from its slot number inside one token. `INI::getNextAsciiString` splits on whitespace
#: only, so a colon stays inside the token - the same shape `DeathAnimAndDuration`'s
#: ``AnimState:X`` uses.
KEYWORD = "CommandButtons"
SLOT_SEPARATOR = 0x3A  # ':'

#: `CommandSetUpgrade`'s own one-row field-parse table, and the ``push imm32`` inside its
#: `buildFieldParse` that is the table's **only** reference in the image. The base is taken from
#: the reference rather than from the constant, so a patch that relocated the table first is
#: followed instead of bypassed; `FIELD_TABLE_VA` is what that reference holds on a stock build.
#:
#: The table has one row and **no slack**: `0x00C6DF90`, sixteen bytes past its base, is live
#: vtable data. Adding a keyword therefore means rebuilding it in the cave.
FIELD_TABLE_VA = 0x00C6DF70
FIELD_TABLE_REF_VA = 0x008B7C10

#: `CommandSetUpgradeModuleData`: the stock `CommandSet` `AsciiString`, the first free byte past
#: it (where this patch's field goes), and `sizeof` with the ``push`` that allocates it.
#:
#: The layout up to here is `UpgradeMuxData` inlined at ``+0x08`` - `TriggeredBy` ``+0x08``,
#: `ConflictsWith` ``+0x98``, `CustomAnimAndDuration` ``+0x128``, the three flags ``+0x134``..
#: ``+0x136`` - then `CommandSet`, then the end of the object.
COMMAND_SET_OFFSET = 0x138
COMMAND_BUTTONS_OFFSET = 0x13C
MODULE_DATA_SIZE = 0x13C
MODULE_DATA_SIZE_VA = 0x00655452

#: The two calls inside the `ModuleData` constructor and destructor that this patch widens to the
#: new field. Both are reached with ``ecx`` = ``&ModuleData->CommandSet``, so both shims reach the
#: new field as ``ecx+4`` and neither depends on a register the surrounding code happens to hold.
CTOR_ASSIGN_CALL_VA = 0x00655432
DTOR_DTOR_CALL_VA = 0x00656004

#: `CommandSetUpgrade`'s primary vtable, written by its constructor at `0x008B7C2B`. Comparing a
#: module's first dword against it is what identifies one of these modules while walking an
#: object's module array - an exact type test that costs one load, where asking the engine would
#: mean two virtual calls.
MODULE_VTABLE = 0x00C6DF40

#: `CommandSetUpgrade::upgradeImplementation` and `::unUpgradeImplementation` - vtable slots
#: ``+0x28`` and ``+0x20`` of the `UpgradeMux` interface, both ``__thiscall`` on the interface
#: subobject (``module+0x10``) with no arguments.
#:
#: The upgrade hook displaces seven bytes (four instructions) and resumes at
#: `UPGRADE_IMPL_RESUME`; the un-upgrade hook displaces the five-byte ``mov eax, imm32`` that
#: feeds `__EH_prolog` and resumes at the ``call`` itself, which is why it has to put ``eax``
#: back before jumping.
UPGRADE_IMPL_VA = 0x008B7C68
UPGRADE_IMPL_BYTES = bytes.fromhex("568bf1578d4ef0")
UPGRADE_IMPL_RESUME = 0x008B7C6F
UNUPGRADE_IMPL_VA = 0x008B7CFA
UNUPGRADE_IMPL_BYTES = bytes.fromhex("b83432ba00")
UNUPGRADE_IMPL_RESUME = 0x008B7CFF
UNUPGRADE_EH_EAX = 0x00BA3234

#: Where the module interface finds its neighbours. ``this`` is the `UpgradeMux` subobject at
#: ``module+0x10``, which is why the stock code reads its `ModuleData` as ``[this-0x0C]`` and its
#: `Object` as ``[this-0x08]``; `MODULE_LATCH_OFFSET` is `UpgradeMux`'s "already upgraded" byte,
#: at ``this+4`` and therefore ``module+0x14``.
MUX_OFFSET = 0x10
MODULE_DATA_PTR_OFFSET = 0x04
MODULE_OBJECT_PTR_OFFSET = 0x08
MODULE_LATCH_OFFSET = 0x14

#: `Object`: the NULL-terminated `BehaviorModule*` array, the `ThingTemplate` back-pointer, and
#: the template's `CommandSet` `AsciiString` - the last link of the four-way priority chain in
#: `Object::getCommandSetString`.
OBJECT_MODULES_OFFSET = 0x24C
OBJECT_TEMPLATE_OFFSET = 0x04
TEMPLATE_COMMAND_SET_OFFSET = 0x70

#: `TheCommandSetStore` and its "the sets changed" byte, which both the stock upgrade step and
#: the Create-A-Hero builder set after touching a set.
THE_COMMAND_SET_STORE = 0x00DE7744
COMMAND_SET_STORE_DIRTY_OFFSET = 0x28

#: `CommandSetStore::findCommandSet(const AsciiString *)` (``ret 4``, NULL when unknown),
#: `::newCommandSet(const AsciiString *, Bool mutable)` (``ret 8``) and
#: `::findCommandButton(const AsciiString *)` (``ret 4``), all ``__thiscall`` on the store.
#:
#: `newCommandSet` **always allocates** - it is `operator new` plus ``map[name] = set`` - so the
#: cave looks the name up first and only creates on a miss. Its second argument is the flag at
#: `CommandSet+0x9C` that `setCommandButton` and `clearCommandButtons` both guard on: sets parsed
#: from INI are created with ``0`` and are silently immutable, so a synthetic set has to be
#: created with ``1``.
FIND_COMMAND_SET = 0x0071EFA2
NEW_COMMAND_SET = 0x0072028B
FIND_COMMAND_BUTTON = 0x0071D6EA

#: `CommandSet::clearCommandButtons()` (no arguments, plain ``ret``),
#: `::getCommandButton(Int)` (``ret 4``) and `::setCommandButton(CommandButton *, Int)`
#: (``ret 8`` - the index is the **second** argument, at ``[esp+8]``).
#:
#: `getCommandButton` is not a bare array read: it first offers the slot to a per-map override
#: (`0x0062FF03`) and returns that when it answers. It has no bound check either way, which is
#: why the copy loop needs `SET_BUTTON_BOUND_IMM8_VA`.
CLEAR_COMMAND_BUTTONS = 0x0080C8D2
GET_COMMAND_BUTTON = 0x0080C837
SET_COMMAND_BUTTON = 0x0080C8EF

#: The ``imm8`` of ``cmp edx, 0x21`` inside `CommandSet::setCommandButton`, i.e. the highest legal
#: slot plus one. `commandset-limit` rewrites exactly this byte, so reading it **at run time** is
#: what lets the cave agree with that patch whichever order the two are applied in.
#: `SET_BUTTON_BOUND_VA` is the instruction; the opcode pair is asserted, the immediate is not.
SET_BUTTON_BOUND_VA = 0x0080C8FC
SET_BUTTON_BOUND_IMM8_VA = 0x0080C8FE

#: `Object::setCommandSetStringOverride(const AsciiString *)` - ``__thiscall``, ``ret 4``. Writes
#: `Object+0x43C`, the third and lowest-priority of the four sources
#: `Object::getCommandSetString` consults, and then notifies the control bar itself. An **empty**
#: string is how the override is cleared, which is how the stock un-upgrade step resets it.
SET_COMMAND_SET_STRING_OVERRIDE = 0x00693B94

#: `UpgradeMux::setCustomAnimAndDuration(false)` - ``__thiscall`` on the **module base**, no
#: arguments, plain ``ret``. The first thing the stock un-upgrade step does, and the only part of
#: it this patch's replacement keeps verbatim.
CLEAR_CUSTOM_ANIM = 0x008D28F9

#: The global the module's own upgrade step reads at `0x008B7C87` to deselect and reselect the
#: object, which is what makes the command bar rebuild rather than redraw. Named for what it is
#: used for: it is **not** `THE_IN_GAME_UI` (`0x00DE4830`), which the garrison command-set swap
#: uses a few hundred bytes away.
SELECTION_UI = 0x00DE4938
UI_DESELECT = 0x006A99CB
UI_RESELECT = 0x006A9D9C

#: `AsciiString::operator=(const AsciiString &)` - ``__thiscall``, ``ret 4``, and the call the
#: `ModuleData` constructor makes to default its `CommandSet`. :mod:`.utils.token_lists` knows it
#: as `ASCII_STRING_ASSIGN`; it is spelled out here because this patch also *replaces* that call.
ASCII_STRING_ASSIGN = 0x00436030

#: The longest button name the cave will look up. A token is copied into a frame buffer to be
#: NUL-terminated and to have its ``:slot`` suffix cut off, and this bounds that copy; a longer
#: token is truncated, which simply fails the lookup. No real button name comes close.
MAX_NAME = 0xFF

#: What :meth:`CommandSetButtonUpgradePatch._compute_section` hands back: the addresses the
#: image has to be pointed at, as ``(table, parser, upgrade hook, un-upgrade hook, ctor shim,
#: dtor shim)``. Named so `apply` and `verify` unpack the same shape.
_Stubs = tuple[int, int, int, int, int, int]

SECTION_NAME = ".cmdbtn"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave is a field table, one string
# and code; the token buffer lives in the rebuild routine's own frame, so it needs no MEM_WRITE.
SECTION_CHARACTERISTICS = 0x60000060

#: Sites this patch depends on and does not itself rewrite. Between them they pin every offset the
#: cave hardcodes - the module's identity, where it keeps its `ModuleData` and `Object`, the
#: "already upgraded" latch, the module array, the override field - plus the two resume points the
#: hooks jump back to and the guard whose immediate the bound is read from. Nothing else would
#: catch a mismatch: the cave would walk the wrong array, or test the wrong byte, so each is
#: asserted before anything is written and again by
#: :meth:`~CommandSetButtonUpgradePatch.verify`.
ANCHORS = (
    (
        0x008B7C2B,
        bytes.fromhex("c706") + struct.pack("<I", MODULE_VTABLE),
        "mov [esi], 0xc6df40 - the CommandSetUpgrade constructor writing the vtable the cave "
        "type-tests against",
    ),
    (
        0x008B7C74,
        bytes.fromhex("8b46f48b7ef8"),
        "mov eax, [esi-0xc] / mov edi, [esi-8] - the ModuleData and Object behind the interface",
    ),
    (
        0x008B7C7A,
        bytes.fromhex("0538010000"),
        "add eax, 0x138 - the stock CommandSet field the new keyword sits beside",
    ),
    (
        UPGRADE_IMPL_RESUME,
        bytes.fromhex("e87dac0100"),
        "call 0x8d28f1 - where the upgrade hook resumes the stock function",
    ),
    (
        UNUPGRADE_IMPL_RESUME,
        bytes.fromhex("e8ec511800"),
        "call __EH_prolog - where the un-upgrade hook resumes the stock function",
    ),
    (
        0x008B7CB9,
        bytes.fromhex("ff5020"),
        "call [eax+0x20] - attemptUnUpgrade calling unUpgradeImplementation every pass, which is "
        "what makes removal reach this patch",
    ),
    (
        0x008B7C87,
        bytes.fromhex("8b0d") + struct.pack("<I", SELECTION_UI),
        "mov ecx, [0xde4938] - the selection global the stock upgrade step deselects through",
    ),
    (
        0x0065541A,
        bytes.fromhex("8d8e38010000"),
        "lea ecx, [esi+0x138] - the ModuleData constructor's CommandSet, so the shim's ecx+4 is "
        "the new field",
    ),
    (
        0x00655FFE,
        bytes.fromhex("8d8e38010000"),
        "lea ecx, [esi+0x138] - the same in the destructor",
    ),
    (
        0x005B462D,
        bytes.fromhex("8a442404884104"),
        "mov al, [esp+4] / mov [ecx+4], al - setUpgradeExecuted, which is where the latch offset "
        "comes from",
    ),
    (
        0x00693740,
        bytes.fromhex("8bb74c020000"),
        "mov esi, [edi+0x24c] - Object::updateUpgradeModules walking the module array the cave "
        "walks",
    ),
    (
        0x0069156F,
        bytes.fromhex("8dbe38040000"),
        "lea edi, [esi+0x438] - the head of Object::getCommandSetString's priority chain",
    ),
    (
        0x00693B9D,
        bytes.fromhex("8dbe3c040000"),
        "lea edi, [esi+0x43c] - setCommandSetStringOverride writing the field this patch drives",
    ),
    (
        SET_BUTTON_BOUND_VA - 4,
        bytes.fromhex("8b54240883fa"),
        "mov edx, [esp+8] / cmp edx - setCommandButton's slot guard, whose immediate is the "
        "run-time bound (the immediate itself is commandset-limit's and is not asserted)",
    ),
)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _jmp_bytes(from_va: int, to_va: int, width: int) -> bytes:
    """``jmp rel32`` sited at ``from_va``, padded with `nop` to ``width``."""
    jump = b"\xe9" + struct.pack("<i", to_va - (from_va + 5))
    if width < len(jump):
        raise ValueError(f"the window at 0x{from_va:08x} is too small for a jmp rel32")
    return jump + b"\x90" * (width - len(jump))


# Frame slots of the rebuild routine, as `ebp`-relative displacements. The token buffer sits
# below all of them, which is why they are negative and small and it is not.
_NAME = -0x04  # AsciiString: the synthetic set's name, and the override that is written
_BASE_PTR = -0x08  # AsciiString *: the set the overlay is applied on top of
_ANY_OVERLAY = -0x0C  # Int: whether any applied module carries CommandButtons
_SET = -0x10  # CommandSet *: the synthetic set being built
_BASE_SET = -0x14  # CommandSet *: the set its buttons are copied from
_BOUND = -0x18  # Int: slots per CommandSet, read from the engine at run time
_PLAIN_BASE = -0x1C  # Int: whether _BASE_PTR came from an applied plain CommandSetUpgrade
_SLOT = -0x20  # Int: the slot the token asked for, or -1 for "the lowest free one"
_TMP = -0x24  # AsciiString: the token, as findCommandButton wants it
_BUF = -0x128  # char[MAX_NAME+1]
_FRAME = 0x128


def _disp8(value: int) -> bytes:
    return struct.pack("<b", value)


def _disp32(value: int) -> bytes:
    return struct.pack("<i", value)


def _lea_ecx(slot: int) -> bytes:
    """``lea ecx, [ebp+slot]``, in whichever displacement width the slot needs."""
    return b"\x8d\x4d" + _disp8(slot) if -128 <= slot <= 127 else b"\x8d\x8d" + _disp32(slot)


def _lea_eax(slot: int) -> bytes:
    """``lea eax, [ebp+slot]``."""
    return b"\x8d\x45" + _disp8(slot) if -128 <= slot <= 127 else b"\x8d\x85" + _disp32(slot)


def build_code(base_va: int) -> Asm:
    """The cave's five routines, laid out at the address they will occupy.

    Returned as the :class:`~sage_patch.asm.Asm` rather than as bytes so the caller can take each
    routine's address from the same layout that produced them - the two hooks and the two
    `ModuleData` shims are all pointed at from the image.
    """
    a = Asm(base_va)

    _emit_hook_upgrade(a)
    _emit_hook_unupgrade(a)
    _emit_has_overlay(a)
    _emit_rebuild(a)
    _emit_shims(a)
    return a


def _emit_hook_upgrade(a: Asm) -> None:
    """`CommandSetUpgrade::upgradeImplementation`, in front of the stock one.

    Entered with ``ecx`` = the `UpgradeMux` interface, at the function's first byte, so nothing is
    live but ``ecx`` and the stack. An object carrying no `CommandButtons` module takes the
    passthrough, which re-executes the four displaced instructions and jumps back - the stock
    function then runs exactly as it does today, having lost nothing but the time of the scan.

    The rebuild arm passes **1** for ``selfApplied``: `UpgradeMux::giveSelfUpgrade` calls this
    before `setUpgradeExecuted(true)`, so this module's own latch is still clear while its
    implementation runs and the walk would otherwise leave it out of the union it is being run
    for.
    """
    a.label("hook_upgrade")
    a.emit(0x51)  # push ecx
    a.emit(b"\x8b\x49", _disp8(-MODULE_OBJECT_PTR_OFFSET))  # mov ecx, [ecx-8]   ; the Object
    a.call("has_overlay")
    a.emit(0x59)  # pop ecx
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "hook_upgrade_rebuild")

    a.emit(UPGRADE_IMPL_BYTES)  # the displaced push esi / mov esi,ecx / push edi / lea ecx
    a.jmp_absolute(UPGRADE_IMPL_RESUME)

    a.label("hook_upgrade_rebuild")
    a.emit(b"\x6a\x01")  # push 1                 ; selfApplied
    a.emit(b"\x8d\x41", _disp8(-MUX_OFFSET))  # lea eax, [ecx-0x10]    ; the module
    a.emit(0x50)  # push eax
    a.emit(b"\xff\x71", _disp8(-MODULE_OBJECT_PTR_OFFSET))  # push [ecx-8]  ; the Object
    a.call("rebuild")
    a.emit(b"\x83\xc4\x0c")  # add esp, 0xc
    a.emit(0xC3)  # ret


def _emit_hook_unupgrade(a: Asm) -> None:
    """`CommandSetUpgrade::unUpgradeImplementation`, in front of the stock one.

    The passthrough has to put ``eax`` back before jumping, because the five bytes it displaced
    are the ``mov eax, imm32`` that hands `__EH_prolog` its handler table; the ``call`` it lands
    on then pushes the right return address, and ``esp`` is untouched because the scan balances
    its own ``push``.

    The rebuild arm reimplements the stock function rather than calling it: the latch guard, the
    custom-animation reset (verbatim, through the same `0x008D28F9`), the union rebuild **without
    this module**, and the latch clear. What it drops is the stock comparison of the object's
    override against this module's own `CommandSet` - which cannot be asked of a synthetic name -
    and it is safe to drop precisely because objects that would notice never get here.
    """
    a.label("hook_unupgrade")
    a.emit(0x51)  # push ecx
    a.emit(b"\x8b\x49", _disp8(-MODULE_OBJECT_PTR_OFFSET))  # mov ecx, [ecx-8]
    a.call("has_overlay")
    a.emit(0x59)  # pop ecx
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "hook_unupgrade_go")

    a.emit(0xB8, _u32(UNUPGRADE_EH_EAX))  # mov eax, 0xba3234   ; the displaced instruction
    a.jmp_absolute(UNUPGRADE_IMPL_RESUME)

    a.label("hook_unupgrade_go")
    a.emit(b"\x80\x79\x04\x00")  # cmp byte [ecx+4], 0    ; isAlreadyUpgraded
    a.jcc(JNE, "hook_unupgrade_do")
    a.emit(0xC3)  # ret

    a.label("hook_unupgrade_do")
    a.emit(0x56)  # push esi
    a.emit(b"\x8b\xf1")  # mov esi, ecx
    a.emit(b"\x8d\x4e", _disp8(-MUX_OFFSET))  # lea ecx, [esi-0x10]  ; the module
    a.call_absolute(CLEAR_CUSTOM_ANIM)
    a.emit(b"\x6a\x00")  # push 0                 ; selfApplied
    a.emit(b"\x8d\x46", _disp8(-MUX_OFFSET))  # lea eax, [esi-0x10]
    a.emit(0x50)  # push eax
    a.emit(b"\xff\x76", _disp8(-MODULE_OBJECT_PTR_OFFSET))  # push [esi-8]
    a.call("rebuild")
    a.emit(b"\x83\xc4\x0c")  # add esp, 0xc
    a.emit(b"\xc6\x46\x04\x00")  # mov byte [esi+4], 0    ; setUpgradeExecuted(false)
    a.emit(0x5E)  # pop esi
    a.emit(0xC3)  # ret


def _emit_has_overlay(a: Asm) -> None:
    """Does this object carry a `CommandSetUpgrade` with a non-empty `CommandButtons`?

    ``ecx`` the `Object`, answer in ``al``, clobbers ``eax``/``ecx``/``edx`` and nothing else -
    which is what lets both hooks call it before they have a frame.

    The emptiness test is the field's handle against NULL rather than `AsciiString::isEmpty`. For
    *this* field the two agree: it is only ever written by the list parser, which assigns an
    accumulator that is either NULL-handled or holds at least one character.
    """
    a.label("has_overlay")
    a.emit(b"\x8b\x91", _u32(OBJECT_MODULES_OFFSET))  # mov edx, [ecx+0x24c]

    a.label("has_overlay_loop")
    a.emit(b"\x8b\x02")  # mov eax, [edx]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "has_overlay_no")
    a.emit(b"\x81\x38", _u32(MODULE_VTABLE))  # cmp dword [eax], 0xc6df40
    a.jcc(JNE, "has_overlay_next")
    a.emit(b"\x8b\x40", _disp8(MODULE_DATA_PTR_OFFSET))  # mov eax, [eax+4]
    a.emit(b"\x83\xb8", _u32(COMMAND_BUTTONS_OFFSET), 0x00)  # cmp dword [eax+0x13c], 0
    a.jcc(JNE, "has_overlay_yes")

    a.label("has_overlay_next")
    a.emit(b"\x83\xc2\x04")  # add edx, 4
    a.jmp("has_overlay_loop")

    a.label("has_overlay_no")
    a.emit(b"\x32\xc0")  # xor al, al
    a.emit(0xC3)  # ret

    a.label("has_overlay_yes")
    a.emit(b"\xb0\x01")  # mov al, 1
    a.emit(0xC3)  # ret


def _emit_rebuild(a: Asm) -> None:
    """Rebuild the object's command set from every `CommandSetUpgrade` currently applied to it.

    ``cdecl(Object *obj, void *self, Int selfApplied)``. ``self`` is the module whose
    implementation is running and ``selfApplied`` what to count it as, because its latch is not in
    the state the caller means: it is still clear during `upgradeImplementation` and still set
    during `unUpgradeImplementation`.

    Three walks of the module array, deliberately, rather than one walk into a list: the array is
    short, the walk is six instructions, and a list would need a bound and somewhere to put it.
    The first finds the base set and whether anything overlays it, the second builds the name, the
    third fills a set that turned out not to exist yet.

    Writing an **empty** name is a valid outcome and the one that restores stock behaviour: it
    clears `Object+0x43C` and lets `getCommandSetString` fall through to the template.
    """
    a.label("rebuild")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x81\xec", _u32(_FRAME))  # sub esp, 0x128
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x83\x65", _disp8(_NAME), 0x00)  # and dword [ebp-4], 0    ; empty AsciiString
    a.emit(b"\x83\x65", _disp8(_TMP), 0x00)  # and dword [ebp-0x24], 0
    a.emit(b"\x83\x65", _disp8(_ANY_OVERLAY), 0x00)  # and dword [ebp-0xc], 0
    a.emit(b"\x83\x65", _disp8(_PLAIN_BASE), 0x00)  # and dword [ebp-0x1c], 0
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]        ; the Object
    a.emit(b"\x8b\x40", _disp8(OBJECT_TEMPLATE_OFFSET))  # mov eax, [eax+4]  ; ThingTemplate
    a.emit(b"\x83\xc0", _disp8(TEMPLATE_COMMAND_SET_OFFSET))  # add eax, 0x70
    a.emit(b"\x89\x45", _disp8(_BASE_PTR))  # mov [ebp-8], eax
    a.emit(b"\x0f\xbe\x05", _u32(SET_BUTTON_BOUND_IMM8_VA))  # movsx eax, byte [0x80c8fe]
    a.emit(b"\x89\x45", _disp8(_BOUND))  # mov [ebp-0x18], eax

    _emit_walk_head(a, "p1")
    a.emit(b"\x8b\x7b", _disp8(MODULE_DATA_PTR_OFFSET))  # mov edi, [ebx+4]   ; ModuleData
    a.emit(b"\x83\xbf", _u32(COMMAND_BUTTONS_OFFSET), 0x00)  # cmp dword [edi+0x13c], 0
    a.jcc(JE, "p1_plain")
    a.emit(b"\xc7\x45", _disp8(_ANY_OVERLAY), _u32(1))  # mov dword [ebp-0xc], 1
    a.jmp("p1_next")

    a.label("p1_plain")  # a plain CommandSetUpgrade supplies the base; the last one wins,
    a.emit(b"\x83\xbf", _u32(COMMAND_SET_OFFSET), 0x00)  # which is the stock last-writer rule
    a.jcc(JE, "p1_next")
    a.emit(b"\x8d\x87", _u32(COMMAND_SET_OFFSET))  # lea eax, [edi+0x138]
    a.emit(b"\x89\x45", _disp8(_BASE_PTR))  # mov [ebp-8], eax
    a.emit(b"\xc7\x45", _disp8(_PLAIN_BASE), _u32(1))  # mov dword [ebp-0x1c], 1
    _emit_walk_tail(a, "p1")

    a.emit(b"\x83\x7d", _disp8(_ANY_OVERLAY), 0x00)  # cmp dword [ebp-0xc], 0
    a.jcc(JNE, "overlay")
    # Nothing overlays the object any more. The name stays empty unless a plain module is still
    # applied, in which case its set is the whole answer.
    a.emit(b"\x83\x7d", _disp8(_PLAIN_BASE), 0x00)  # cmp dword [ebp-0x1c], 0
    a.jcc(JE, "commit")
    _emit_assign_base(a)
    a.jmp("commit")

    a.label("overlay")
    _emit_assign_base(a)
    _emit_walk_head(a, "p2")
    _emit_overlay_field(a, "p2")
    a.emit(0x6A, 0x2B)  # push '+'
    a.emit(_lea_ecx(_NAME))
    a.call_absolute(ASCII_STRING_CONCAT_CHAR)
    a.emit(b"\x83\xc7", _disp8(ASCII_STRING_CHARS))  # add edi, 8    ; the token list's characters
    a.emit(0x57)  # push edi
    a.emit(_lea_ecx(_NAME))
    a.call_absolute(ASCII_STRING_CONCAT_CSTR)
    _emit_walk_tail(a, "p2")

    a.emit(_lea_eax(_NAME))
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x0d", _u32(THE_COMMAND_SET_STORE))  # mov ecx, [TheCommandSetStore]
    a.call_absolute(FIND_COMMAND_SET)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "commit")  # this combination has been built before

    a.emit(b"\x6a\x01")  # push 1                 ; mutable, or the writes below are no-ops
    a.emit(_lea_eax(_NAME))
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x0d", _u32(THE_COMMAND_SET_STORE))  # mov ecx, [TheCommandSetStore]
    a.call_absolute(NEW_COMMAND_SET)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "commit")  # out of memory: leave the object showing its base set
    a.emit(b"\x89\x45", _disp8(_SET))  # mov [ebp-0x10], eax
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call_absolute(CLEAR_COMMAND_BUTTONS)

    a.emit(b"\x8b\x45", _disp8(_BASE_PTR))  # mov eax, [ebp-8]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x0d", _u32(THE_COMMAND_SET_STORE))  # mov ecx, [TheCommandSetStore]
    a.call_absolute(FIND_COMMAND_SET)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "overlays")  # an unknown base is an empty one, not a failure
    a.emit(b"\x89\x45", _disp8(_BASE_SET))  # mov [ebp-0x14], eax
    a.emit(b"\x33\xff")  # xor edi, edi

    a.label("copy")
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\x4d", _disp8(_BASE_SET))  # mov ecx, [ebp-0x14]
    a.call_absolute(GET_COMMAND_BUTTON)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "copy_next")
    a.emit(0x57)  # push edi                ; the slot
    a.emit(0x50)  # push eax                ; the button
    a.emit(b"\x8b\x4d", _disp8(_SET))  # mov ecx, [ebp-0x10]
    a.call_absolute(SET_COMMAND_BUTTON)

    a.label("copy_next")
    a.emit(0x47)  # inc edi
    a.emit(b"\x3b\x7d", _disp8(_BOUND))  # cmp edi, [ebp-0x18]
    a.jcc(JL, "copy")

    a.label("overlays")
    _emit_walk_head(a, "p3")
    _emit_overlay_field(a, "p3")
    a.emit(b"\x83\xc7", _disp8(ASCII_STRING_CHARS))  # add edi, 8
    a.call("tokens")
    _emit_walk_tail(a, "p3", done="commit")

    a.label("commit")
    a.emit(_lea_eax(_NAME))
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]
    a.call_absolute(SET_COMMAND_SET_STRING_OVERRIDE)
    a.emit(0xA1, _u32(THE_COMMAND_SET_STORE))  # mov eax, [TheCommandSetStore]
    a.emit(b"\xc6\x40", _disp8(COMMAND_SET_STORE_DIRTY_OFFSET), 0x01)  # mov byte [eax+0x28], 1
    a.emit(b"\xff\x75\x08")  # push [ebp+8]
    a.emit(b"\x8b\x0d", _u32(SELECTION_UI))  # mov ecx, [0xde4938]
    a.call_absolute(UI_DESELECT)
    a.emit(b"\xff\x75\x08")  # push [ebp+8]
    a.emit(b"\x8b\x0d", _u32(SELECTION_UI))  # mov ecx, [0xde4938]
    a.call_absolute(UI_RESELECT)
    a.emit(_lea_ecx(_TMP))
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(_lea_ecx(_NAME))
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    _emit_applied(a)
    _emit_tokens(a)


def _emit_walk_head(a: Asm, tag: str) -> None:
    """Start a walk of the object's module array, stopping on each applied `CommandSetUpgrade`.

    Leaves ``esi`` on the array cursor and ``ebx`` on the module, which is what
    :func:`_emit_walk_tail` expects and what `applied` reads.
    """
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]
    a.emit(b"\x8b\xb0", _u32(OBJECT_MODULES_OFFSET))  # mov esi, [eax+0x24c]
    a.label(f"{tag}_loop")
    a.emit(b"\x8b\x1e")  # mov ebx, [esi]
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc(JE, f"{tag}_done")
    a.emit(b"\x81\x3b", _u32(MODULE_VTABLE))  # cmp dword [ebx], 0xc6df40
    a.jcc(JNE, f"{tag}_next")
    a.call("applied")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, f"{tag}_next")


def _emit_walk_tail(a: Asm, tag: str, done: str | None = None) -> None:
    """Close a walk opened by :func:`_emit_walk_head`. ``done`` redirects the exit, for the last
    walk, which has nothing left to do but commit."""
    a.label(f"{tag}_next")
    a.emit(b"\x83\xc6\x04")  # add esi, 4
    a.jmp(f"{tag}_loop")
    if done is None:
        a.label(f"{tag}_done")
    else:
        a.label(f"{tag}_done")
        a.jmp(done)


def _emit_overlay_field(a: Asm, tag: str) -> None:
    """Load this module's `CommandButtons` handle into ``edi``, skipping the module if it is
    empty - i.e. if it is a plain `CommandSetUpgrade`."""
    a.emit(b"\x8b\x7b", _disp8(MODULE_DATA_PTR_OFFSET))  # mov edi, [ebx+4]
    a.emit(b"\x8b\xbf", _u32(COMMAND_BUTTONS_OFFSET))  # mov edi, [edi+0x13c]
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, f"{tag}_next")


def _emit_assign_base(a: Asm) -> None:
    """``name = *basePtr``, through the same `AsciiString::operator=` the engine uses."""
    a.emit(b"\x8b\x45", _disp8(_BASE_PTR))  # mov eax, [ebp-8]
    a.emit(0x50)  # push eax
    a.emit(_lea_ecx(_NAME))
    a.call_absolute(ASCII_STRING_ASSIGN)


def _emit_applied(a: Asm) -> None:
    """Is the module in ``ebx`` currently applied? Answer in ``al``, nothing else touched.

    The latch at ``module+0x14`` is the whole test, except for the module the caller is running
    for: `UpgradeMux` sets that latch *around* the implementation rather than before it, so the
    caller says what it should count as.
    """
    a.label("applied")
    a.emit(b"\x3b\x5d\x0c")  # cmp ebx, [ebp+0xc]     ; self?
    a.jcc(JNE, "applied_latch")
    a.emit(b"\x8a\x45\x10")  # mov al, [ebp+0x10]
    a.emit(0xC3)  # ret

    a.label("applied_latch")
    a.emit(b"\x8a\x43", _disp8(MODULE_LATCH_OFFSET))  # mov al, [ebx+0x14]
    a.emit(0xC3)  # ret


def _emit_tokens(a: Asm) -> None:
    """Write one module's `CommandButtons` into the set being built.

    ``edi`` the characters, the set in ``[ebp-0x10]``; preserves ``esi`` and ``ebx`` so the walk
    around it keeps its cursor and its module.

    A token is ``Name`` or ``Name:Slot``. The name is copied into the frame buffer to be
    NUL-terminated - `findCommandButton` wants an `AsciiString`, and the list's own separator is
    not a terminator - and a trailing ``:`` with no digits is read as no slot rather than as slot
    zero. A name that resolves to nothing, and a bare name when every slot is taken, are both
    skipped: a `CommandSet` that is short one button is a better failure than one that is
    silently missing the button that was there before.
    """
    a.label("tokens")
    a.emit(0x56)  # push esi
    a.emit(0x53)  # push ebx

    a.label("tok_skip")
    a.emit(b"\x8a\x07")  # mov al, [edi]
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JNE, "tok_start")
    a.emit(0x47)  # inc edi
    a.jmp("tok_skip")

    a.label("tok_start")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "tok_done")
    a.emit(b"\x8d\xb5", _disp32(_BUF))  # lea esi, [ebp-0x128]
    a.emit(0xB9, _u32(MAX_NAME))  # mov ecx, 0xff

    a.label("tok_copy")
    a.emit(b"\x8a\x07")  # mov al, [edi]
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "tok_name_end")
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JE, "tok_name_end")
    a.emit(b"\x3c", bytes([SLOT_SEPARATOR]))  # cmp al, ':'
    a.jcc(JE, "tok_name_end")
    a.emit(b"\x88\x06")  # mov [esi], al
    a.emit(0x47)  # inc edi
    a.emit(0x46)  # inc esi
    a.emit(0x49)  # dec ecx
    a.jcc(JNE, "tok_copy")  # full: take what we have, and let the lookup fail

    a.label("tok_name_end")
    a.emit(b"\xc6\x06\x00")  # mov byte [esi], 0
    a.emit(b"\x83\x4d", _disp8(_SLOT), 0xFF)  # or dword [ebp-0x20], -1   ; no slot asked for
    a.emit(b"\x80\x3f", bytes([SLOT_SEPARATOR]))  # cmp byte [edi], ':'
    a.jcc(JNE, "tok_lookup")
    a.emit(0x47)  # inc edi
    a.emit(b"\x33\xdb")  # xor ebx, ebx           ; the number
    a.emit(b"\x33\xc9")  # xor ecx, ecx           ; how many digits

    a.label("tok_digits")
    a.emit(b"\x0f\xb6\x07")  # movzx eax, byte [edi]
    a.emit(b"\x83\xe8\x30")  # sub eax, '0'
    a.emit(b"\x83\xf8\x09")  # cmp eax, 9
    a.jcc(JA, "tok_digits_end")
    a.emit(b"\x6b\xdb\x0a")  # imul ebx, ebx, 10
    a.emit(b"\x03\xd8")  # add ebx, eax
    a.emit(0x47)  # inc edi
    a.emit(0x41)  # inc ecx
    a.jmp("tok_digits")

    a.label("tok_digits_end")
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "tok_lookup")  # a bare ':' is not a slot
    a.emit(b"\x89\x5d", _disp8(_SLOT))  # mov [ebp-0x20], ebx

    a.label("tok_lookup")
    a.emit(b"\x8d\x85", _disp32(_BUF))  # lea eax, [ebp-0x128]
    a.emit(0x50)  # push eax
    a.emit(_lea_ecx(_TMP))
    a.call_absolute(ASCII_STRING_SET)
    a.emit(_lea_eax(_TMP))
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x0d", _u32(THE_COMMAND_SET_STORE))  # mov ecx, [TheCommandSetStore]
    a.call_absolute(FIND_COMMAND_BUTTON)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "tok_next")  # no such button
    a.emit(b"\x83\x7d", _disp8(_SLOT), 0x00)  # cmp dword [ebp-0x20], 0
    a.jcc(JGE, "tok_place")

    a.emit(b"\x8b\xd8")  # mov ebx, eax           ; the button, while eax is the scan's
    a.emit(b"\x33\xc9")  # xor ecx, ecx

    a.label("tok_free")
    a.emit(0x51)  # push ecx                ; saved across the call
    a.emit(0x51)  # push ecx                ; the slot to look at
    a.emit(b"\x8b\x4d", _disp8(_SET))  # mov ecx, [ebp-0x10]
    a.call_absolute(GET_COMMAND_BUTTON)  # ret 4: takes the second push
    a.emit(0x59)  # pop ecx
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "tok_free_found")
    a.emit(0x41)  # inc ecx
    a.emit(b"\x3b\x4d", _disp8(_BOUND))  # cmp ecx, [ebp-0x18]
    a.jcc(JL, "tok_free")
    a.jmp("tok_next")  # every slot is taken

    a.label("tok_free_found")
    a.emit(b"\x89\x4d", _disp8(_SLOT))  # mov [ebp-0x20], ecx
    a.emit(b"\x8b\xc3")  # mov eax, ebx

    a.label("tok_place")
    a.emit(b"\xff\x75", _disp8(_SLOT))  # push [ebp-0x20]        ; the slot
    a.emit(0x50)  # push eax                ; the button
    a.emit(b"\x8b\x4d", _disp8(_SET))  # mov ecx, [ebp-0x10]
    a.call_absolute(SET_COMMAND_BUTTON)

    a.label("tok_next")  # run to the end of this token, then take the next
    a.emit(b"\x8a\x07")  # mov al, [edi]
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "tok_done")
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JE, "tok_skip")
    a.emit(0x47)  # inc edi
    a.jmp("tok_next")

    a.label("tok_done")
    a.emit(_lea_ecx(_TMP))
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(0x5B)  # pop ebx
    a.emit(0x5E)  # pop esi
    a.emit(0xC3)  # ret


def _emit_shims(a: Asm) -> None:
    """The two `ModuleData` shims: default the new field, and release it.

    Both are entered with ``ecx`` = ``&ModuleData->CommandSet`` - the ``lea`` two instructions
    earlier in each function - so the new field is ``ecx+4`` and neither shim has to know which
    register holds the `ModuleData`. Each ends by tail-calling the routine it displaced, which is
    what keeps the caller's ``ret 4`` (constructor) and plain ``ret`` (destructor) contracts.
    """
    a.label("ctor_shim")
    a.emit(b"\x83\x61\x04\x00")  # and dword [ecx+4], 0   ; a validly constructed empty string
    a.jmp_absolute(ASCII_STRING_ASSIGN)

    a.label("dtor_shim")
    a.emit(0x51)  # push ecx
    a.emit(b"\x83\xc1\x04")  # add ecx, 4
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(0x59)  # pop ecx
    a.jmp_absolute(ASCII_STRING_DTOR)


class CommandSetButtonUpgradePatch(Patch):
    """Let `CommandSetUpgrade` add individual command buttons instead of swapping the whole set."""

    name = "commandset-button-upgrade"
    author = "officialNecro"
    description = (
        "CommandSetUpgrade gains CommandButtons, a list of CommandButton names that are overlaid "
        "onto the object's existing command set instead of replacing it - write "
        "CommandButtons = Command_Foo:5 Command_Bar to pin one button to slot 5 and put the "
        "other in the first free slot. Several modules on one object accumulate, and the "
        "combined set is built and cached at run time, so buying N abilities needs N modules "
        "rather than a CommandSet per combination. The stock CommandSet keyword is unchanged"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        preceding = self._preceding_rows(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._compute_section(va, preceding)[0],
            SECTION_CHARACTERISTICS,
        )
        # The layout is a pure function of the base VA and the rows that precede the new one, so
        # re-deriving it costs nothing and keeps the callable above a plain bytes-returning one.
        _content, stubs = self._compute_section(section_va, preceding)
        for file_off, old, new, note in self._edits(data, stubs):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified). Locates
        the cave, recomputes the table and the code its base VA implies, and compares them and all
        six rewritten sites to what is on disk. Reads only via ``struct`` and the section table,
        so verification needs no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            preceding = self._preceding_rows(data, patched=True)
            content, stubs = self._compute_section(section_va, preceding)
            edits = self._edits(data, stubs)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(f"{SECTION_NAME} does not hold the expected table, parser and code")

        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        try:
            self._check_anchors(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems

    def ini_surface(self) -> Engine:
        """The one keyword, as a list of raw tokens rather than of button references: a token is
        ``Name`` *or* ``Name:Slot``, so it is not a name `commandbuttons` could be looked up by.
        No default is stated - an absent keyword leaves the field empty, and an empty field is
        what makes the module behave exactly as it does today."""
        return Engine(
            fields=(FieldDelta("CommandSetUpgrade", KEYWORD, "Opaque[]", None, self.name),)
        )

    def _compute_section(
        self, section_va: int, preceding: tuple[Entry, ...]
    ) -> tuple[bytes, _Stubs]:
        """Return ``(section content, (table VA, parse VA, upgrade hook, un-upgrade hook, ctor
        shim, dtor shim))`` for a cave based at ``section_va``.

        Layout: the rebuilt field table (first, so it inherits the section's own alignment), the
        keyword string, the list parser, then the code. The order is arbitrary but fixed, because
        `verify` recomputes all of it from the section's base address and the preceding rows
        alone.
        """
        keyword_va = section_va + (len(preceding) + 2) * ROW_SIZE  # + the new row + terminator
        string = KEYWORD.encode("latin1") + b"\x00"
        parser_va = keyword_va + len(string) + (-len(string) % 4)
        parser = build_list_parser(parser_va)
        code = build_code(parser_va + len(parser))

        table = bytearray()
        for entry in preceding:
            table += struct.pack("<IIII", *entry)
        table += struct.pack("<IIII", keyword_va, parser_va, 0, COMMAND_BUTTONS_OFFSET)
        table += bytes(ROW_SIZE)  # the terminator

        content = bytes(table) + string + bytes(-len(string) % 4) + parser + code.finish()
        stubs = (
            section_va,
            parser_va,
            code.label_va("hook_upgrade"),
            code.label_va("hook_unupgrade"),
            code.label_va("ctor_shim"),
            code.label_va("dtor_shim"),
        )
        return content, stubs

    @staticmethod
    def _table_base(data: bytes | bytearray) -> int:
        """Where `CommandSetUpgrade`'s field table currently is, from the one reference that names
        it - never from :data:`FIELD_TABLE_VA`, which is only what a stock build holds there."""
        return resolve_table(data, (FIELD_TABLE_REF_VA,), (0x68,), "CommandSetUpgrade")

    def _preceding_rows(self, data: bytes | bytearray, patched: bool = False) -> tuple[Entry, ...]:
        """The `CommandSetUpgrade` field-table rows that come before this patch's own.

        Read from the live table both ways round, which is what makes applying this patch twice
        fail cleanly and what lets it be applied after something else has extended the same
        table. Before the write there must be no `CommandButtons` row; after it there must be
        one, and it is located **by name** rather than by counting back from the end, so a third
        patch appending past it would not shift the answer.
        """
        entries = read_field_table(data, self._table_base(data))
        before = entries_before(data, entries, KEYWORD)
        if patched:
            if before is None:
                raise ValueError(
                    f"the CommandSetUpgrade field table has no {KEYWORD!r} row - the file does "
                    f"not carry this patch"
                )
            return before
        if before is not None:
            raise ValueError(
                f"the CommandSetUpgrade field table already has a {KEYWORD!r} row - the file is "
                f"already patched"
            )
        names = [read_cstring(data, entry[0]) for entry in entries]
        if "CommandSet" not in names:
            raise ValueError(
                "the CommandSetUpgrade field table has no 'CommandSet' row - this is not the "
                "expected build"
            )
        return entries

    def _check_anchors(self, data: bytes | bytearray) -> None:
        for va, expected, what in ANCHORS:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{what}: VA 0x{va:08x} is not mapped")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{what} @0x{va:08x}: expected {expected.hex()}, got {got.hex()} - this is "
                    f"not the expected build"
                )

    def _edits(
        self,
        data: bytes | bytearray,
        stubs: _Stubs,
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``.

        The field-table reference's "old" value is **whatever it currently holds**, not the stock
        constant: that is the stock table on a plain build, this patch's own on a patched one, and
        somebody else's on a build where another patch relocated the table first. Reading it here
        is what makes the third case compose rather than raise, and it costs nothing - the opcode
        is already asserted by :func:`~.utils.field_tables.resolve_table`, and a doubly-applied
        file is refused by :meth:`_preceding_rows` before this runs.
        """
        table_va, _parser_va, upgrade_va, unupgrade_va, ctor_va, dtor_va = stubs
        planned = [
            (
                FIELD_TABLE_REF_VA + 1,
                _u32(self._table_base(data)),
                _u32(table_va),
                "CommandSetUpgrade field table -> cave",
            ),
            (
                MODULE_DATA_SIZE_VA + 1,
                _u32(MODULE_DATA_SIZE),
                _u32(MODULE_DATA_SIZE + 4),
                "sizeof(CommandSetUpgradeModuleData) 0x13c -> 0x140",
            ),
            (
                CTOR_ASSIGN_CALL_VA,
                _call_bytes(CTOR_ASSIGN_CALL_VA, ASCII_STRING_ASSIGN),
                _call_bytes(CTOR_ASSIGN_CALL_VA, ctor_va),
                "the ModuleData constructor's string default -> cave",
            ),
            (
                DTOR_DTOR_CALL_VA,
                _call_bytes(DTOR_DTOR_CALL_VA, ASCII_STRING_DTOR),
                _call_bytes(DTOR_DTOR_CALL_VA, dtor_va),
                "the ModuleData destructor's string release -> cave",
            ),
            (
                UPGRADE_IMPL_VA,
                UPGRADE_IMPL_BYTES,
                _jmp_bytes(UPGRADE_IMPL_VA, upgrade_va, len(UPGRADE_IMPL_BYTES)),
                "upgradeImplementation -> cave",
            ),
            (
                UNUPGRADE_IMPL_VA,
                UNUPGRADE_IMPL_BYTES,
                _jmp_bytes(UNUPGRADE_IMPL_VA, unupgrade_va, len(UNUPGRADE_IMPL_BYTES)),
                "unUpgradeImplementation -> cave",
            ),
        ]

        edits: list[tuple[int, bytes, bytes, str]] = []
        for va, old, new, note in planned:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{va:08x} is not mapped")
            edits.append((off, old, new, note))
        return edits
