"""Add `MultiSelectGroup` to `CommandButton`: buttons with the same non-zero value share a slot in a
mixed selection instead of blanking it.

`ControlBar::populateMultiSelect` merges a mixed selection's command bar by pointer identity, so a
unit at another upgrade stage clears the slot. With the patch, grouped buttons count as the same;
the slot keeps the one the data prefers, not whichever was selected first, and a click reaches every
member with the button of its own stage. Default 0 is stock.

Derivation: `../docs/multi-select-group.md`.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    AI_GROUP_DO_OBJECT_UPGRADE,
    AI_GROUP_MEMBER_OBJECT,
    AI_GROUP_MEMBER_SENTINEL,
    AI_GROUP_UPGRADE_EBP,
    AI_GROUP_UPGRADE_MEMBER,
    AI_GROUP_UPGRADE_MEMBER_BYTES,
    AI_GROUP_UPGRADE_MEMBER_RESUME,
    AI_GROUP_UPGRADE_SELF_EBP,
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY,
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    COMMAND_BUTTON_TRIGGER_WHEN_READY,
    COMMAND_SET_STORE_FIND_COMMAND_SET,
    CONTROL_BAR_MERGE_CLEAR_SLOTS,
    CONTROL_BAR_MERGE_HIDE,
    CONTROL_BAR_MERGE_INSTALL,
    CONTROL_BAR_MERGE_INSTALL_FIRST,
    CONTROL_BAR_MERGE_INSTALL_FIRST_BYTES,
    CONTROL_BAR_MERGE_INSTALL_FIRST_RESUME,
    CONTROL_BAR_MERGE_KEEP,
    CONTROL_BAR_MERGE_OBJECT_EBP,
    CONTROL_BAR_MERGE_RESET,
    CONTROL_BAR_MERGE_RESET_BYTES,
    CONTROL_BAR_MERGE_SLOT,
    CONTROL_BAR_MERGE_SLOT_BYTES,
    CONTROL_BAR_MERGE_SLOT_EBP,
    FIELD_PARSE_STRIDE,
    INI_PARSE_UNSIGNED_SHORT,
    OBJECT_HAS_UPGRADE,
)
from ..asm import JE, JL, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    file_offset,
    find_section,
    read_cstring,
    u32,
)
from .utils.field_tables import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "AVAILABILITY",
    "COMMAND_BUTTON_UPGRADE",
    "DEFAULT_KEYWORD",
    "HOOK_CALL",
    "HOOK_JMP",
    "MULTI_SELECT_GROUP_OFFSET",
    "ROUTINES",
    "SECTION_NAME",
    "SLOTS",
    "MultiSelectGroupPatch",
    "build_code",
    "build_table",
    "entry_points",
    "rewritten_default",
    "validate_keyword",
]

SECTION_NAME = ".msgroup"  # the PE name field is 8 bytes and truncates silently

#: The INI keyword the new `CommandButton` field is parsed under.
DEFAULT_KEYWORD = "MultiSelectGroup"

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable, unlike
#: `command-point-cost`'s: the cave holds the per-slot usability record the merge maintains, which
#: is written every time a selection is repopulated.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: `MultiSelectGroup`, an `UnsignedShort` in `CommandButton`'s second alignment hole.
#: `TriggerWhenReady` is the `Bool` at +0x12C and `PresetRange` the `Real` at +0x130, so
#: +0x12D..+0x12F is a three-byte hole; +0x12E is the aligned word inside it, and +0x12D is left
#: for whatever wants a byte next, the way +0x10D was.
MULTI_SELECT_GROUP_OFFSET = 0x12E

#: `CommandButton::m_upgrade` - the `Upgrade` keyword's home, and what the merge ranks two grouped
#: buttons by. NULL on a button that buys nothing, which is the case the ranking declines.
COMMAND_BUTTON_UPGRADE = 0x24

#: `MAX_COMMANDS_PER_COMMAND_SET`, which is also the size of the per-slot usability record. The
#: stock bound; `commandset-limit` raises what a `CommandSet` may *define*, but the ControlBar still
#: draws 33 slots and this record is one byte per drawn slot.
SLOTS = 33

#: `ControlBar::getCommandAvailability` - `stdcall`, `ret 0x14`, `ecx` the `ControlBar`. Verdicts 1
#: and 2 mean usable; the cave asks for nothing else. Arguments right to left are
#: `(button, window, object, float *, recursing)`, and **a NULL window is supported** - the click
#: executor passes one at `0x009405B0`, which is why the cave does too rather than reaching for a
#: window pointer that may not exist yet.
AVAILABILITY = 0x00942733

#: The object -> command set -> button walk, the same three calls `multi-execute-gate` uses and for
#: the same reason: `getCommandSetString` returns the *effective* set, so a `CommandSetUpgrade` swap
#: is accounted for. All three preserve `ebx`/`esi`/`edi`.
GET_COMMAND_SET_STRING = 0x0069156B
GET_COMMAND_BUTTON = 0x0080C837
THE_CONTROL_BAR = 0x00DE7744

#: The cave's routines, in the order they are laid out. The first four are hook targets; the rest
#: are helpers they share.
ROUTINES = ("reset", "seed", "merge", "member", "avail", "setof", "bybtn", "bygroup", "resolve")

#: The first bytes at every address the cave jumps to or calls, plus the windows that prove the
#: hook sits inside the function this patch believes it does. A build whose layout moved fails here
#: rather than on a wild jump or a word written into somebody else's field.
ANCHORS: dict[int, bytes] = {
    CONTROL_BAR_MERGE_SLOT: CONTROL_BAR_MERGE_SLOT_BYTES,
    CONTROL_BAR_MERGE_RESET: CONTROL_BAR_MERGE_RESET_BYTES,
    CONTROL_BAR_MERGE_INSTALL_FIRST: CONTROL_BAR_MERGE_INSTALL_FIRST_BYTES,
    AI_GROUP_UPGRADE_MEMBER: AI_GROUP_UPGRADE_MEMBER_BYTES,
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY: COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES,
    # `populateMultiSelect`'s per-drawable merge: its prologue, and the store that fills the
    # `Object` slot together with the branch that proves the slot is non-NULL past it. Both caves
    # read `[ebp-0x14]` without testing it, and this is why they may.
    0x00944534: bytes.fromhex("558bec83ec148b450853"),
    0x00944554: bytes.fromhex("3bc38945ec0f84f5"),
    # The first-object loop: the counter's initialisation and its increment, which together are
    # what make `[ebp+8]` the slot index rather than the `Drawable` it started as; and the
    # `cmp ecx, esi` whose flags the seed shim has to put back.
    0x009445B7: bytes.fromhex("895d08"),
    0x009445E4: bytes.fromhex("8b0f3bce"),
    0x009446B5: bytes.fromhex("ff450883c704"),
    # The merge loop's head - the `CommandSet` slot and the `getCommandButton` call that fills
    # `edi`, which is what makes `edi` this object's button rather than anything else.
    0x009446CA: bytes.fromhex("8b75fc81c6dc000000"),
    0x009446D3: bytes.fromhex("8b4df853e85b81ecff"),
    # The `ATTACK_MOVE` exemption that sets `cl`, immediately before the merge hook.
    0x00944702: bytes.fromhex("752a"),
    0x0094472C: bytes.fromhex("32c9"),
    # The three continuations, at the shapes the cave relies on: the clear-and-hide, the loop's
    # step, and the install arm - whose `push eax` is why the cave zeroes `eax` before entering it.
    CONTROL_BAR_MERGE_HIDE: bytes.fromhex("8b0e83a68400"),
    CONTROL_BAR_MERGE_KEEP: bytes.fromhex("4383c604"),
    CONTROL_BAR_MERGE_INSTALL: bytes.fromhex("8b0e85c989be8400000074"),
    # The clear-all-slots helper the reset shim tail-calls, and its 33-slot bound.
    CONTROL_BAR_MERGE_CLEAR_SLOTS: bytes.fromhex("56576a218db1dc000000"),
    # `AIGroup::doObjectUpgrade`: its prologue, which is what says `[ebp+8]` holds the message's
    # upgrade and `[ebp-4]` the group; and the list walk the resolver copies.
    AI_GROUP_DO_OBJECT_UPGRADE: bytes.fromhex("558bec51538b5d0885db"),
    0x0076FC0A: bytes.fromhex("8b4104568b303bf0"),
    0x0076FC75: bytes.fromhex("8b368b45fc3b7004"),
    # The constructor's neighbours: the `xor ebx, ebx` the widened store's zero comes from, the
    # two `movss` that put `PresetRange` and `AutoDelay` where the hole's far edge is, and the
    # `memset(this+0x110, 0, 0x1C)` that proves the hole is not cleared already.
    0x0075D52A: bytes.fromhex("33db"),
    0x0075D6A2: bytes.fromhex("f30f118630010000"),
    0x0075D6AA: bytes.fromhex("f30f118634010000"),
    0x0075D721: bytes.fromhex("6a1c8d8610010000"),
    # `operator new(0x2E0)` in `ControlBar::newCommandButton` - untouched, and asserted so, because
    # a field in the padding is only free while the allocation is the size it is.
    0x0071C446: bytes.fromhex("68e0020000"),
    # The engine routines the cave reaches out to, and the parser the new row names. The
    # availability evaluator is anchored at its **entry**, not at `0x00942775` - that window is
    # `command-point-cost`'s, and anchoring it would make the two patches order-dependent.
    AVAILABILITY: bytes.fromhex("b81ec4ba00"),
    OBJECT_HAS_UPGRADE: bytes.fromhex("8b44240485c07504"),
    GET_COMMAND_SET_STRING: bytes.fromhex("568bf1578dbe3804"),
    GET_COMMAND_BUTTON: bytes.fromhex("558bec568bf1"),
    COMMAND_SET_STORE_FIND_COMMAND_SET: bytes.fromhex("558bec"),
    INI_PARSE_UNSIGNED_SHORT: bytes.fromhex("558bec5151"),
}

#: Fields the live table must still carry at these offsets, or this is not the build the layout
#: above was derived against. Checked by name rather than by count, so it survives another patch
#: having appended to the same table first.
FINGERPRINT = {
    "Upgrade": COMMAND_BUTTON_UPGRADE,
    # the two the padding sits between: the field's home is only free if these are where the
    # constructor's stores say they are
    "TriggerWhenReady": COMMAND_BUTTON_TRIGGER_WHEN_READY,
    "PresetRange": 0x130,
}

# An INI keyword is matched by exact compare, so anything the parser could never match is a typo
# rather than a choice. The engine's own field names are CamelCase with digits and underscores.
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def validate_keyword(keyword: str) -> None:
    """Raise unless `keyword` is a token the engine's INI reader could ever match."""
    if not _KEYWORD_PATTERN.match(keyword):
        raise ValueError(
            "an INI keyword must be letters, digits and underscores starting with a letter "
            f"(the reader matches it by exact compare), got {keyword!r}"
        )


def rewritten_default() -> bytes:
    """The constructor's `TriggerWhenReady` store, widened from a byte to a dword.

    `0x88` is `mov r/m8, r8` and `0x89` is `mov r/m32, r32` over the same ModRM, so the six stock
    bytes become six patched ones and the field's default costs no cave and no displacement."""
    return bytes([0x89]) + COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES[1:]


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address, the keyword and how many rows the
    live field table turned out to have.

    Pure arithmetic on those three, so `MultiSelectGroupPatch.apply` and
    `MultiSelectGroupPatch.verify` compute the same addresses from opposite directions."""

    keyword_va: int
    flags_va: int
    table_va: int
    code_va: int


#: The keyword string is the first thing in the cave, at a fixed offset - which is what lets
#: `MultiSelectGroupPatch.detect` read it back out of a binary it knows nothing else about.
_KEYWORD_OFFSET = 0

#: The per-slot usability record, rounded up so the reset can clear it a dword at a time.
_FLAGS_SIZE = (SLOTS + 3) & ~3


def _layout(base_va: int, keyword: str, rows: int) -> _Layout:
    keyword_va = base_va + _KEYWORD_OFFSET
    string = len(keyword) + 1
    flags_va = keyword_va + string + (-string % 4)  # keep what follows dword-aligned
    table_va = flags_va + _FLAGS_SIZE
    code_va = table_va + (rows + 2) * FIELD_PARSE_STRIDE  # + the new row + the terminator
    return _Layout(keyword_va, flags_va, table_va, code_va)


def build_table(entries: tuple[Entry, ...], keyword_va: int) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the new `UnsignedShort`, the
    terminator.

    The live rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are - and only the new row points into the cave."""
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack(
        "<IIII", keyword_va, INI_PARSE_UNSIGNED_SHORT, 0, MULTI_SELECT_GROUP_OFFSET
    )
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


def _assemble(code_va: int, flags_va: int) -> Asm:
    a = Asm(code_va)
    _emit_reset(a, flags_va)
    _emit_seed(a, flags_va)
    _emit_merge(a, flags_va)
    _emit_member(a)
    _emit_avail(a)
    _emit_setof(a)
    _emit_bybtn(a)
    _emit_bygroup(a)
    _emit_resolve(a)
    return a


def _emit_reset(a: Asm, flags_va: int) -> None:
    """Zero the per-slot usability record, then tail-call the clear-all-slots helper.

    Sited on the `call` at `0x00944853`, which has exactly one caller, so this runs once per
    repopulate. `ecx` is the `ControlBar` for the thiscall behind it and must survive; `eax` and
    the flags are dead, the helper's own prologue being `push esi` / `push edi`."""
    a.label("reset")
    for offset in range(0, _FLAGS_SIZE, 4):
        a.emit(0xC7, 0x05, u32(flags_va + offset), u32(0))  # mov dword [flags+n], 0
    a.jmp_absolute(CONTROL_BAR_MERGE_CLEAR_SLOTS)


def _emit_seed(a: Asm, flags_va: int) -> None:
    """The first object's install, plus the record of whether it can use what it installed.

    Without this the merge would never learn the first object's opinion of its own button, and a
    slot whose installed button only *that* object can use would look unusable to the rule below.

    Two things are live across the window and both are put back: `ecx`, the slot's window, which
    the `winHide` at `0x009445F4` is called on; and **ZF**, which the `je` at the resume point
    reads from the `cmp ecx, esi` two bytes before the hook. `popad` restores `ecx` and leaves
    EFLAGS alone, so the `cmp` is re-issued rather than assumed."""
    a.label("seed")
    a.emit(CONTROL_BAR_MERGE_INSTALL_FIRST_BYTES)  # mov [edi+0x84], ebx
    a.emit(0x60)  # pushad
    a.emit(0xFF, 0x75, CONTROL_BAR_MERGE_OBJECT_EBP & 0xFF)  # push [ebp-0x14]  ; the Object
    a.emit(0x53)  # push ebx                                                    ; the button
    a.call("avail")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x8B, 0x4D, CONTROL_BAR_MERGE_SLOT_EBP)  # mov ecx, [ebp+8]   ; the slot index
    a.emit(0x88, 0x81, u32(flags_va))  # mov [ecx+flags], al
    a.emit(0x61)  # popad
    a.emit(0x3B, 0xCE)  # cmp ecx, esi   ; put back the flags the resume point branches on
    a.jmp_absolute(CONTROL_BAR_MERGE_INSTALL_FIRST_RESUME)


def _emit_merge(a: Asm, flags_va: int) -> None:
    """The merge's verdict for one slot.

    `edi` is this object's button, `eax` the one already installed, `ebx` the slot index and `cl`
    the stock `ATTACK_MOVE` flag - all as the displaced instructions found them. `edx` is dead
    across the whole loop and `cl` past its own test.

    Once the pair is grouped the routine keeps a two-dword frame, because every call clobbers the
    installed button out of `eax`: `[esp+4]` holds it and `[esp]` this object's verdict on the new
    one. Every exit past that point drops the frame."""
    a.label("merge")
    a.emit(0x3B, 0xF8)  # cmp edi, eax           ; the displaced identity compare
    a.jcc(JE, "keep")
    a.emit(0x84, 0xC9)  # test cl, cl            ; the displaced ATTACK_MOVE exemption
    a.jcc(JNE, "keep")

    # A slot one side does not fill at all has nothing to group with. Both arms are reachable:
    # `edi` is NULL when this object's set is short, `eax` when nothing is installed yet.
    # A slot only one of the two sets fills is filled from the one that has it, rather than blanked.
    # This is the only rule here that is not gated on the new field: a set that says nothing about a
    # slot is not in conflict with one that does, so there is nothing to arbitrate. Stock blanks it
    # anyway, which is what puts an empty socket under `Command_PurchaseUpgradeWildForgedBlades` the
    # moment a unit without that button joins the selection.
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "keep")  # this set says nothing here; the installed button stands
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "adopt")  # nothing installed here yet; this set supplies it

    # The field, on both buttons. Zero is the default and means "not grouped", so it can never
    # match - two ungrouped buttons take the stock path they always did.
    a.emit(0x0F, 0xB7, 0x97, u32(MULTI_SELECT_GROUP_OFFSET))  # movzx edx, word [edi+0x12E]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "hide")
    a.emit(0x66, 0x3B, 0x90, u32(MULTI_SELECT_GROUP_OFFSET))  # cmp dx, word [eax+0x12E]
    a.jcc(JNE, "hide")

    # Same non-zero group, so the two are interchangeable. Take the frame and ask the ControlBar
    # about each candidate.
    a.emit(0x50)  # push eax                 ; [esp+4] once the next push lands: the installed
    a.emit(0x6A, 0x00)  # push 0             ; [esp]: this object's verdict on the new button

    a.emit(0xFF, 0x75, CONTROL_BAR_MERGE_OBJECT_EBP & 0xFF)  # push [ebp-0x14]
    a.emit(0x57)  # push edi
    a.call("avail")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x88, 0x04, 0x24)  # mov [esp], al

    # The installed button's verdict is a union over every object merged so far: the one that
    # installed it recorded its own answer in `seed`, and each later object adds to it. Once
    # something has been able to use it there is nothing left to ask.
    a.emit(0x8A, 0x83, u32(flags_va))  # mov al, [ebx+flags]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "known")
    a.emit(0xFF, 0x75, CONTROL_BAR_MERGE_OBJECT_EBP & 0xFF)  # push [ebp-0x14]
    a.emit(0xFF, 0x74, 0x24, 0x08)  # push [esp+8]           ; the installed button
    a.call("avail")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.label("known")
    a.emit(0x88, 0x83, u32(flags_va))  # mov [ebx+flags], al
    a.emit(0x8A, 0x14, 0x24)  # mov dl, [esp]                ; the new button's verdict

    # A button nothing in the selection can use never wins against one something can.
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "usable_installed")
    a.emit(0x84, 0xD2)  # test dl, dl
    a.jcc(JNE, "install")  # only the new one is usable
    a.jmp("rank")  # neither is: the stage rule decides which dead button to show
    a.label("usable_installed")
    a.emit(0x84, 0xD2)  # test dl, dl
    a.jcc(JE, "keep_framed")  # only the installed one is usable

    # Both usable: show the earlier stage. If this object already owns the installed button's
    # upgrade it is past that stage, so the installed button is the earlier of the two; otherwise
    # this object is the one behind and its own button is. That converges on the least advanced
    # usable button whatever order the selection is merged in.
    a.label("rank")
    a.emit(0x8B, 0x54, 0x24, 0x04)  # mov edx, [esp+4]       ; the installed button
    a.emit(0x8B, 0x52, COMMAND_BUTTON_UPGRADE)  # mov edx, [edx+0x24]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "keep_framed")  # buys nothing: no stage to compare
    a.emit(0x83, 0x7F, COMMAND_BUTTON_UPGRADE, 0x00)  # cmp dword [edi+0x24], 0
    a.jcc(JE, "keep_framed")

    # `pushad`/`popad` because every register in the loop is live across the call and the callee's
    # own clobbers are not this patch's to know; `popad` leaves EFLAGS alone, which is what carries
    # the answer out. `[ebp-0x14]` is the `Object`, non-NULL wherever this loop runs - the function
    # returns at `0x00944754` when it is not.
    a.emit(0x60)  # pushad
    a.emit(0x52)  # push edx                              ; the UpgradeTemplate
    a.emit(0x8B, 0x4D, CONTROL_BAR_MERGE_OBJECT_EBP & 0xFF)  # mov ecx, [ebp-0x14]
    a.call_absolute(OBJECT_HAS_UPGRADE)  # thiscall, ret 4 - it cleans the argument
    a.emit(0x84, 0xC0)  # test al, al
    a.emit(0x61)  # popad
    a.jcc(JNE, "keep_framed")

    a.label("install")
    a.emit(0x8A, 0x04, 0x24)  # mov al, [esp]     ; the new button's verdict travels with it
    a.emit(0x88, 0x83, u32(flags_va))  # mov [ebx+flags], al
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x33, 0xC0)  # xor eax, eax     ; the install arm passes eax to winHide
    a.jmp_absolute(CONTROL_BAR_MERGE_INSTALL)

    # The empty-slot half of the union: this set has a button where nothing is installed yet.
    #
    # `OK_FOR_MULTI_SELECT` is re-tested here because the first-object pass tests it before it
    # installs anything (`0x009445DA`) and this path bypasses that pass entirely. Without it the
    # union would put buttons in a group bar that are not meant to appear in one.
    #
    # `eax` is already the NULL that got here, which is exactly what the install arm wants to hand
    # to `winHide` - but `avail` clobbers it, so it is zeroed again afterwards rather than assumed.
    a.label("adopt")
    a.emit(0xF6, 0x47, 0x1D, 0x01)  # test byte [edi+0x1d], 1
    a.jcc(JE, "hide")
    a.emit(0xFF, 0x75, CONTROL_BAR_MERGE_OBJECT_EBP & 0xFF)  # push [ebp-0x14]
    a.emit(0x57)  # push edi
    a.call("avail")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x88, 0x83, u32(flags_va))  # mov [ebx+flags], al
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.jmp_absolute(CONTROL_BAR_MERGE_INSTALL)

    a.label("keep_framed")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.label("keep")
    a.jmp_absolute(CONTROL_BAR_MERGE_KEEP)
    a.label("hide")
    a.jmp_absolute(CONTROL_BAR_MERGE_HIDE)


def _emit_member(a: Asm) -> None:
    """`AIGroup::doObjectUpgrade`'s member loop, with `ebx` made per-member.

    The stock loop carries the message's one upgrade in `ebx` for every member. `[ebp+8]` keeps the
    argument untouched, so each pass re-derives it and asks what *this* member's own command set
    offers in the same group instead. Everything downstream - the legality gate, `hasUpgrade`,
    `canAcceptUpgrade`, the production queue - then runs on the right upgrade with no further
    edits, which is what makes one click start every stage in the group.

    `eax`, `ecx` and `edx` are dead at the loop's top; `esi` (the list node) and `edi` (the member)
    are not, and every helper preserves them."""
    a.label("member")
    a.emit(0x8B, 0x7E, AI_GROUP_MEMBER_OBJECT)  # mov edi, [esi+8]  ; displaced: the member
    a.emit(0xFF, 0x75, AI_GROUP_UPGRADE_SELF_EBP & 0xFF)  # push [ebp-4]  ; the AIGroup
    a.emit(0xFF, 0x75, AI_GROUP_UPGRADE_EBP)  # push [ebp+8]            ; the message's upgrade
    a.emit(0x57)  # push edi                                            ; the member
    a.call("resolve")
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.emit(0x6A, 0x00)  # push 0                                        ; displaced
    a.emit(0x57)  # push edi                                            ; displaced
    a.jmp_absolute(AI_GROUP_UPGRADE_MEMBER_RESUME)


def _emit_avail(a: Asm) -> None:
    """`int avail(CommandButton *btn, Object *obj)` - cdecl, 1 when the ControlBar would let this
    object use this button.

    The window argument is passed NULL, which the click executor at `0x009405B0` also does, so no
    window pointer has to be found or tested. The float out-param is a local the frame reclaims,
    since the callee pops only its five arguments."""
    a.label("avail")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x6A, 0x00)  # push 0                  ; [ebp-4]: the float out-param
    a.emit(0x8B, 0x0D, u32(THE_CONTROL_BAR))  # mov ecx, [TheControlBar]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "avail_no")
    a.emit(0x6A, 0x00)  # push 0                  ; arg5: not a recursive call
    a.emit(0x8D, 0x45, 0xFC)  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax                      ; arg4
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0xc]    ; arg3: the Object
    a.emit(0x6A, 0x00)  # push 0                  ; arg2: no window
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]      ; arg1: the CommandButton
    a.call_absolute(AVAILABILITY)  # stdcall, ret 0x14
    a.emit(0x48)  # dec eax                       ; verdicts 1 and 2 mean usable
    a.emit(0x83, 0xF8, 0x01)  # cmp eax, 1
    a.emit(0x0F, 0x96, 0xC0)  # setbe al
    a.emit(0x0F, 0xB6, 0xC0)  # movzx eax, al
    a.emit(0xC9)  # leave                         ; drops the float slot with the frame
    a.emit(0xC3)  # ret
    a.label("avail_no")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_setof(a: Asm) -> None:
    """`CommandSet *setof(Object *obj)` - cdecl, 0 when the object names no known set.

    `getCommandSetString` returns the object's *effective* set - the three per-object overrides
    ahead of the template's - so a `CommandSetUpgrade` swap is what this sees, which is the whole
    point. The same three calls `multi-execute-gate` uses, for the same reason."""
    a.label("setof")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]
    a.call_absolute(GET_COMMAND_SET_STRING)  # thiscall, no arguments -> AsciiString *
    a.emit(0x8B, 0x0D, u32(THE_CONTROL_BAR))  # mov ecx, [TheControlBar]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "setof_no")
    a.emit(0x50)  # push eax
    a.call_absolute(COMMAND_SET_STORE_FIND_COMMAND_SET)  # thiscall, ret 4
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret
    a.label("setof_no")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret


def _emit_search(a: Asm, name: str, accept: Callable[[Asm], None]) -> None:
    """The shape both button searches share: walk the object's own set and return the first button
    `accept` takes, or 0.

    `accept` is emitted with the candidate in `eax` and the second argument at `[ebp+0xc]`, and
    must branch to `<name>_step` to reject and to `<name>_out` to take it. All three callees
    preserve `ebx`/`esi`/`edi`, so the slot, the `CommandSet` and the candidate live in registers
    for the whole walk."""
    a.label(name)
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx / push esi / push edi
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]        ; the Object
    a.call("setof")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, f"{name}_none")
    a.emit(0x8B, 0xF0)  # mov esi, eax              ; the CommandSet
    a.emit(0x33, 0xDB)  # xor ebx, ebx              ; slot = 0
    a.label(f"{name}_next")
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(GET_COMMAND_BUTTON)  # thiscall, ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, f"{name}_step")
    accept(a)
    a.label(f"{name}_step")
    a.emit(0x43)  # inc ebx
    a.emit(0x83, 0xFB, SLOTS)  # cmp ebx, 33
    a.jcc(JL, f"{name}_next")
    a.label(f"{name}_none")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label(f"{name}_out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / pop esi / pop ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret


def _emit_bybtn(a: Asm) -> None:
    """`CommandButton *bybtn(Object *obj, UpgradeTemplate *u)` - the button in the object's own
    set that buys `u`, or 0. What says whether a member is already at the right stage."""

    def accept(asm: Asm) -> None:
        asm.emit(0x8B, 0x48, COMMAND_BUTTON_UPGRADE)  # mov ecx, [eax+0x24]
        asm.emit(0x85, 0xC9)  # test ecx, ecx
        asm.jcc(JE, "bybtn_step")
        asm.emit(0x3B, 0x4D, 0x0C)  # cmp ecx, [ebp+0xc]
        asm.jcc(JE, "bybtn_out")

    _emit_search(a, "bybtn", accept)


def _emit_bygroup(a: Asm) -> None:
    """`CommandButton *bygroup(Object *obj, unsigned group)` - the first button in the object's
    own set carrying `group`, or 0. `group` is never zero at the one call site, so a button
    that declares none can never match."""

    def accept(asm: Asm) -> None:
        asm.emit(0x0F, 0xB7, 0x88, u32(MULTI_SELECT_GROUP_OFFSET))  # movzx ecx, word [eax+0x12E]
        asm.emit(0x3B, 0x4D, 0x0C)  # cmp ecx, [ebp+0xc]
        asm.jcc(JE, "bygroup_out")

    _emit_search(a, "bygroup", accept)


def _emit_resolve(a: Asm) -> None:
    """`UpgradeTemplate *resolve(Object *member, UpgradeTemplate *u, AIGroup *group)` - the
    upgrade this member should actually be offered.

    `u` unchanged is the stock answer, and every ungrouped case returns it. Otherwise: the
    member's own set already offering `u` means it is at the right stage; if it is not, `u`'s
    group is found from whichever member of the selection *does* name it - the click came from one
    of them - and the member's own button in that group supplies the upgrade instead. A member with
    no button in that group is not part of the mechanic and takes `u`."""
    a.label("resolve")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx / push esi / push edi

    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0xc]      ; u
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]        ; the member
    a.call("bybtn")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "resolve_stock")  # already at the stage the message names

    a.emit(0x8B, 0x45, 0x10)  # mov eax, [ebp+0x10] ; the AIGroup
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "resolve_stock")
    a.emit(0x8B, 0x70, AI_GROUP_MEMBER_SENTINEL)  # mov esi, [group+4]  ; the sentinel node
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "resolve_stock")
    a.emit(0x8B, 0x1E)  # mov ebx, [esi]            ; the first node
    a.label("resolve_scan")
    a.emit(0x3B, 0xDE)  # cmp ebx, esi
    a.jcc(JE, "resolve_stock")  # round to the sentinel: nobody in the selection names u
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0xc]
    a.emit(0xFF, 0x73, AI_GROUP_MEMBER_OBJECT)  # push [node+8]
    a.call("bybtn")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "resolve_step")
    a.emit(0x0F, 0xB7, 0x80, u32(MULTI_SELECT_GROUP_OFFSET))  # movzx eax, word [eax+0x12E]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "resolve_found")
    a.label("resolve_step")
    a.emit(0x8B, 0x1B)  # mov ebx, [ebx]
    a.jmp("resolve_scan")

    a.label("resolve_found")
    a.emit(0x50)  # push eax                        ; the group
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]        ; the member
    a.call("bygroup")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "resolve_stock")
    a.emit(0x8B, 0x40, COMMAND_BUTTON_UPGRADE)  # mov eax, [eax+0x24]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "resolve_out")

    a.label("resolve_stock")
    a.emit(0x8B, 0x45, 0x0C)  # mov eax, [ebp+0xc]
    a.label("resolve_out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / pop esi / pop ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret


def build_code(code_va: int, flags_va: int) -> bytes:
    """The cave's routines, laid out at the addresses they will occupy."""
    return _assemble(code_va, flags_va).finish()


def entry_points(code_va: int, flags_va: int) -> dict[str, int]:
    """Where each routine starts, taken from the layout that was actually emitted rather than
    counted a second time by hand."""
    a = _assemble(code_va, flags_va)
    return {name: a.label_va(name) for name in ROUTINES}


#: The two shapes a hook site takes. `JMP` is the usual one - the routine reproduces the displaced
#: instructions and jumps back. `CALL` is for a site whose stock instruction **was** a `call`, and
#: it is not interchangeable: the routine there tail-calls the callee the site named, so that
#: callee's `ret` is what returns to the instruction after the site. Turn such a site into a `jmp`
#: and the `ret` pops a value that was never a return address.
HOOK_JMP, HOOK_CALL = 0xE9, 0xE8


def _hook(site_va: int, window: bytes, target_va: int, opcode: int = HOOK_JMP) -> bytes:
    """`jmp`/`call rel32` to `target_va`, padded with `nop` to the width of `window`."""
    branch = bytes([opcode]) + struct.pack("<i", target_va - (site_va + 5))
    if len(window) < len(branch):
        raise ValueError(f"the window at {site_va:#010x} is too small for a rel32 branch")
    return branch + b"\x90" * (len(window) - len(branch))


class MultiSelectGroupPatch(Patch):
    """Add a `MultiSelectGroup` `UnsignedShort` to `CommandButton`, so two buttons a mod declares
    interchangeable keep their slot when a mixed selection's command bars are merged."""

    name = "multi-select-group"
    author = "officialNecro"
    description = (
        "Add a MultiSelectGroup number to CommandButton. Two buttons carrying the same non-zero "
        "value merge as if they were one when several units are selected, instead of blanking the "
        "slot they share - which is what a CommandSet swapped by CommandSetUpgrade does today to "
        "any selection holding units at two different upgrade stages. Where both buttons buy an "
        "Upgrade the earlier stage is the one shown, whatever order the units were selected in. "
        "0, the default, is stock"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    #: The five-byte branch each routine is reached by, as
    #: `{hook va: (stock bytes, routine, opcode)}`.
    #:
    #: **The reset site is a `call`, and that is not a detail.** Its routine ends by tail-calling
    #: the clear-all-slots helper the stock instruction named, so the helper's own `ret` is what
    #: returns to the instruction after the site. Reaching it with a `jmp` leaves nothing on the
    #: stack for that `ret` to pop, and the engine returns into garbage the first time a player
    #: selects more than one unit.
    _HOOKS = {
        CONTROL_BAR_MERGE_SLOT: (CONTROL_BAR_MERGE_SLOT_BYTES, "merge", HOOK_JMP),
        CONTROL_BAR_MERGE_RESET: (CONTROL_BAR_MERGE_RESET_BYTES, "reset", HOOK_CALL),
        CONTROL_BAR_MERGE_INSTALL_FIRST: (CONTROL_BAR_MERGE_INSTALL_FIRST_BYTES, "seed", HOOK_JMP),
        AI_GROUP_UPGRADE_MEMBER: (AI_GROUP_UPGRADE_MEMBER_BYTES, "member", HOOK_JMP),
    }

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        table_va = self._resolve(data)
        entries = self._check_table(data, table_va)

        base_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build(base, entries), _CHARACTERISTICS
        )
        pieces = _layout(base_va, self.keyword, len(entries))
        routines = entry_points(pieces.code_va, pieces.flags_va)

        for hook_va, (stock, routine, opcode) in self._HOOKS.items():
            apply_byte_patch(
                data,
                file_offset(data, hook_va),
                stock,
                _hook(hook_va, stock, routines[routine], opcode),
                f"{hook_va:#010x} -> the {SECTION_NAME} {routine} routine",
            )
        apply_byte_patch(
            data,
            file_offset(data, COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY),
            COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES,
            rewritten_default(),
            f"CommandButton::CommandButton defaults +{MULTI_SELECT_GROUP_OFFSET:#05x} to 0",
        )
        table_ref = u32(pieces.table_va)
        for ref_va, opcode in zip(
            COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = file_offset(data, ref_va)
            apply_byte_patch(
                data,
                off,
                bytes(data[off : off + 5]),
                bytes([opcode]) + table_ref,
                f"CommandButton field table reference {ref_va:#010x} -> {SECTION_NAME}",
            )

    def _build(self, base_va: int, entries: tuple[Entry, ...]) -> bytes:
        """The cave: the keyword string, the rebuilt table, the code."""
        pieces = _layout(base_va, self.keyword, len(entries))
        blob = bytearray(self.keyword.encode("ascii") + b"\x00")
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(entries, pieces.keyword_va)
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        return bytes(blob) + build_code(pieces.code_va, pieces.flags_va)

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """The `CommandButton` field table's base VA, as the image currently holds it.

        Read from the three references that name it rather than from the stock constant, so the
        patch appends to whatever is live - and so applying it twice fails cleanly instead of
        installing a second copy of the field."""
        return resolve_table(
            data,
            COMMAND_BUTTON_FIELD_TABLE_REFS,
            COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
            "CommandButton",
        )

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "ControlBar and CommandButton are not the ones multi-select-group was derived "
                    "against, so the patch would write a word into somebody else's field"
                )

    def _check_table(self, data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        """The live rows, once the table has been checked for the build and for this keyword.

        A duplicate row would parse - the reader takes the first match and the engine would never
        complain - so the field would exist and silently do nothing."""
        entries = read_field_table(data, table_va)
        by_name = {read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, want in FINGERPRINT.items():
            got = by_name.get(field)
            if got != want:
                raise ValueError(
                    f"unexpected build: CommandButton.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        if self.keyword in by_name:
            raise ValueError(
                f"CommandButton already has a {self.keyword!r} field - this patch is already "
                "applied, or another patch has added the same field"
            )
        return entries

    @classmethod
    def detect(cls, data: bytes | bytearray) -> MultiSelectGroupPatch | None:
        """Recognise this patch **and recover its keyword** from `data`.

        The default probe would only ever recognise the default keyword. The keyword string is the
        first thing in the cave, so it reads straight back out; `verify` then checks the whole cave
        against it."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = read_cstring(data, located[0] + _KEYWORD_OFFSET)
        if keyword is None:
            return None
        try:
            patch = cls(keyword)
        except ValueError:
            return None  # not a keyword this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one field this patch adds to `CommandButton`, under whatever keyword it was
        installed with. The widened constructor store zeroes it, so the default is `0` - stock
        behaviour, which is what makes the field opt-in.

        Declared `Int` because that is what a mod writes: the engine's `UnsignedShort` parser
        refuses anything outside `0..65535`, and the value is an identity, not a quantity."""
        return Engine(fields=(FieldDelta("CommandButton", self.keyword, "Int", 0, self.name),))

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch for exactly this keyword. Reads only
        via `struct` and the section table, so it needs no disassembler.

        Every address is recovered from where the cave actually landed rather than from where it
        would land on a clean image, so a build carrying another patch's section too verifies the
        same."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located

        try:
            table_va = self._resolve(data)
            rebuilt = read_field_table(data, table_va)
            preceding = entries_before(data, rebuilt, self.keyword)
            if preceding is None:
                return [f"the live CommandButton table does not name {self.keyword!r}"]
            pieces = _layout(section_va, self.keyword, len(preceding))
            problems = self._verify_cave(data, pieces, preceding, section_va, vsize)
            problems += self._verify_sites(data, pieces, rebuilt)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the patch (wrong build?): {exc}"]
        return problems

    def _verify_cave(
        self,
        data: bytes | bytearray,
        pieces: _Layout,
        preceding: tuple[Entry, ...],
        section_va: int,
        vsize: int,
    ) -> list[str]:
        problems: list[str] = []
        code = build_code(pieces.code_va, pieces.flags_va)
        if pieces.code_va + len(code) > section_va + vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for the table and the code"]
        got_keyword = read_cstring(data, pieces.keyword_va)
        if got_keyword != self.keyword:
            problems.append(
                f"the keyword in {SECTION_NAME} is {got_keyword!r}, not {self.keyword!r}"
            )
        want_table = build_table(preceding, pieces.keyword_va)
        table_off = file_offset(data, pieces.table_va)
        if bytes(data[table_off : table_off + len(want_table)]) != want_table:
            problems.append(
                f"the field table at {pieces.table_va:#010x} is not the live rows plus an "
                f"UnsignedShort at CommandButton+{MULTI_SELECT_GROUP_OFFSET:#05x}"
            )
        code_off = file_offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(code)]) != code:
            problems.append(f"the code at {pieces.code_va:#010x} is not what this patch builds")
        return problems

    def _verify_sites(
        self, data: bytes | bytearray, pieces: _Layout, live: tuple[Entry, ...]
    ) -> list[str]:
        """The hook, the widened default, and the row the engine will actually parse this field
        through.

        **The row is checked in the *live* table, not in this patch's own copy of it.** A patch
        applied after this one rebuilds the same table again - copying this row across, since it
        copies every live row - and repoints the three references at *its* cave. That is the
        composition the tables are read live for, so demanding the references still name this
        cave would report a correctly composed binary as broken. What has to hold is that whatever
        table the engine reaches carries this keyword, pointing at this cave's string and at the
        parser and offset this patch installed."""
        routines = entry_points(pieces.code_va, pieces.flags_va)
        problems: list[str] = []
        for hook_va, (stock, routine, opcode) in self._HOOKS.items():
            want = _hook(hook_va, stock, routines[routine], opcode)
            off = file_offset(data, hook_va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(
                    f"@{hook_va:#010x}: this site does not reach the {SECTION_NAME} {routine} "
                    f"routine (holds {got.hex()})"
                )
        off = file_offset(data, COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY)
        want_default = rewritten_default()
        got_default = bytes(data[off : off + len(want_default)])
        if got_default != want_default:
            problems.append(
                f"@{COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY:#010x}: the constructor does not zero "
                f"CommandButton+{MULTI_SELECT_GROUP_OFFSET:#05x} (holds {got_default.hex()})"
            )

        want_row = (
            pieces.keyword_va,
            INI_PARSE_UNSIGNED_SHORT,
            0,
            MULTI_SELECT_GROUP_OFFSET,
        )
        row = next((e for e in live if read_cstring(data, e[0]) == self.keyword), None)
        if row != want_row:
            problems.append(
                f"the live CommandButton table's {self.keyword!r} row is "
                f"{'absent' if row is None else tuple(hex(v) for v in row)}, expected "
                f"{tuple(hex(v) for v in want_row)}"
            )
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the INI field to add to CommandButton (default {DEFAULT_KEYWORD}); "
                "letters, digits and underscores, and must not already be a CommandButton field"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> MultiSelectGroupPatch:
        return cls(keyword=args.keyword)
