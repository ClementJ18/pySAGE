"""The multi-select-group patch: two buttons a mod declares interchangeable share a slot.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/multi-select-group.md``.

**The gap.** `ControlBar::populateMultiSelect` builds a mixed selection's command bar as a strict
intersection. The first selected unit's `CommandSet` fills the 33 slots, and every later unit is
merged in by the loop at ``0x009446CA``, which compares its button for each slot against the one
already installed **by pointer identity**. A difference clears the slot and hides the window, so a
mod that gives a unit a second-stage button by swapping its `CommandSet` - the only stock way to
change one at runtime - loses that slot the moment a player selects units at two different stages.
The palantir draws six buttons for a unit, so the slot cannot simply be moved: what the player sees
is an empty black socket where the upgrade icon was.

**What this does.** Adds one field, `MultiSelectGroup`, to `CommandButton`. Default `0`, which is
stock behaviour; two buttons carrying the *same* non-zero value are treated as the same button when
the slots are merged, so the slot survives. Nothing else changes - a slot whose buttons disagree
and are not grouped is still cleared and hidden.

**Which of the two the slot keeps is decided by the data, not by selection order.** When both
buttons name an `Upgrade`, the merge keeps the one for the **earlier stage**, found by asking
whether the unit being merged already owns the installed button's upgrade
(`Object::hasUpgrade`, ``0x00691421``): if it does, that unit is ahead of the installed button and
the installed button is the earlier one; if it does not, this unit is behind and its own button
replaces it. Either way the answer converges on the least advanced button in the selection, in any
merge order, which is the safe one - `AIGroup::doObjectUpgrade` (``0x0076FBFB``) skips a member
that already holds the upgrade, so a click advances the units that are behind and no-ops for the
rest.

**That choice is a safety property, not a preference.** A click on an upgrade button sends
`MSG(0x415)` with an object id of zero, and zero means the whole selection; the logic side gates
each member on `Object::hasUpgrade` and `Object::canAcceptUpgrade` and on nothing else. It never
asks whether the button was in *that* unit's own `CommandSet`. So showing a mixed selection the
**later** stage would let a unit still at stage one take stage two directly - skipping the first
purchase and its price. Keeping the earlier button is what makes the field safe to hand a mod.

**Buttons with no `Upgrade` keep the installed one.** Two grouped `SPECIAL_POWER` buttons - the
stealth-set swap `multi-execute-gate` is written about, for one - have no stage to compare, so the
first selected unit's button wins, which is what the rest of the bar already does. There is no
purchase to skip on that path, and `multi-execute-gate` is what gates the members.

Two edits, one cave
-------------------
1. **The field, in the struct's own padding.** `CommandButton+0x12E` is inside the alignment gap
   between `TriggerWhenReady` (a `Bool` at +0x12C) and `PresetRange` (a `Real` at +0x130): no row
   in the field table names it, and the ``memset(this+0x110, 0, 0x1C)`` in the constructor stops at
   +0x12B. Two aligned bytes, parsed by the engine's own `INI::parseUnsignedShort`
   (``0x0042EC11``). ``sizeof`` stays 0x2E0 and `ControlBar::newCommandButton`'s
   ``operator new(0x2E0)`` is untouched.

2. **The default, without a hook.** `operator new` does not zero the block, so the field needs
   initialising or every button inherits a random group - and buttons that collided would then
   merge. The constructor's ``mov byte [esi+0x12C], bl`` becomes ``mov dword [esi+0x12C], ebx``:
   one byte changed, six for six, and `ebx` is the zero the whole constructor stores from, so
   `TriggerWhenReady` stays `No` and the padding is cleared on the way past. No displaced
   instruction and no constructor routine in the cave.

3. **The field table moves, and three references are repointed.** The stock table at ``0x00C2BAC8``
   is boxed in by its own terminator, so it is rebuilt in the cave: every live row copied verbatim,
   since their name pointers are absolute, plus one appended `UnsignedShort` row and the
   terminator. The three references are the static accessor at ``0x005DA706`` and the two `push`
   immediates in the block parser.

4. **The merge's verdict.** ``0x0094472E`` is eight bytes and four whole instructions - the
   identity compare, the `ATTACK_MOVE` exemption, and the fall-through into the clear-and-hide. The
   cave reproduces both stock tests, asks the new field when they fail, and dispatches to one of
   the three continuations the loop already has: `KEEP` (``0x0094474A``), the loop's own step;
   `HIDE` (``0x00944736``), the stock refusal; or `INSTALL` (``0x00944704``), the arm the
   empty-slot case takes, entered with `eax` zeroed because that arm passes `eax` to `winHide`.

**Determinism.** Nothing here is logic-side state. The merge runs on the client, over the local
player's own command bar, and decides which buttons are drawn; the orders a click produces are
unchanged, and the logic side gates each member exactly as it did before. What *is* fatal on a
stock build is the keyword - SAGE treats an unknown field in a known block as a parse error - so a
mod using it ships the patched `game.dat` or does not run at all.

**Composition.** Order-independent: the cave is allocated past every existing section, `verify`
finds it by name, and the field table is located from its live references rather than from the
stock constant, so it appends to whatever is there. `command-point-cost` and `queue-ignore-cp`
rebuild the same table the same way and take the *other* padding hole, +0x10D and +0x10E; this one
takes +0x12E and rewrites a constructor store fourteen bytes past the one they share the window of,
so no two of the three touch a byte in common. Nothing else hooks
`ControlBar::populateMultiSelect`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY,
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    COMMAND_BUTTON_TRIGGER_WHEN_READY,
    CONTROL_BAR_MERGE_HIDE,
    CONTROL_BAR_MERGE_INSTALL,
    CONTROL_BAR_MERGE_KEEP,
    CONTROL_BAR_MERGE_OBJECT_EBP,
    CONTROL_BAR_MERGE_SLOT,
    CONTROL_BAR_MERGE_SLOT_BYTES,
    FIELD_PARSE_STRIDE,
    INI_PARSE_UNSIGNED_SHORT,
    OBJECT_HAS_UPGRADE,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "COMMAND_BUTTON_UPGRADE",
    "DEFAULT_KEYWORD",
    "MULTI_SELECT_GROUP_OFFSET",
    "ROUTINES",
    "SECTION_NAME",
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

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave holds the keyword
#: string and the rebuilt table (read) and one routine (executed); nothing in it is ever written,
#: which is what lets the section stay read-only.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000

#: `MultiSelectGroup`, an `UnsignedShort` in `CommandButton`'s second alignment hole.
#: `TriggerWhenReady` is the `Bool` at +0x12C and `PresetRange` the `Real` at +0x130, so
#: +0x12D..+0x12F is a three-byte hole; +0x12E is the aligned word inside it, and +0x12D is left
#: for whatever wants a byte next, the way +0x10D was.
MULTI_SELECT_GROUP_OFFSET = 0x12E

#: `CommandButton::m_upgrade` - the `Upgrade` keyword's home, and what the merge ranks two grouped
#: buttons by. NULL on a button that buys nothing, which is the case the ranking declines.
COMMAND_BUTTON_UPGRADE = 0x24

#: The cave's routines, in the order they are laid out. One, reached by the only hook.
ROUTINES = ("merge",)

#: The first bytes at every address the cave jumps to or calls, plus the windows that prove the
#: hook sits inside the function this patch believes it does. A build whose layout moved fails here
#: rather than on a wild jump or a word written into somebody else's field.
ANCHORS: dict[int, bytes] = {
    CONTROL_BAR_MERGE_SLOT: CONTROL_BAR_MERGE_SLOT_BYTES,
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY: COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES,
    # `populateMultiSelect`'s per-drawable merge: its prologue, and the store that fills the
    # `Object` slot together with the branch that proves the slot is non-NULL past it. The cave
    # reads `[ebp-0x14]` without testing it, and this is why it may.
    0x00944534: bytes.fromhex("558bec83ec148b450853"),
    0x00944554: bytes.fromhex("3bc38945ec0f84f5"),
    # The merge loop's head - the `CommandSet` slot and the `getCommandButton` call that fills
    # `edi`, which is what makes `edi` this object's button rather than anything else.
    0x009446CA: bytes.fromhex("8b75fc81c6dc000000"),
    0x009446D3: bytes.fromhex("8b4df853e85b81ecff"),
    # The `ATTACK_MOVE` exemption that sets `cl`, immediately before the hook.
    0x00944702: bytes.fromhex("752a"),
    0x0094472C: bytes.fromhex("32c9"),
    # The three continuations, at the shapes the cave relies on: the clear-and-hide, the loop's
    # step, and the install arm - whose `push eax` is why the cave zeroes `eax` before entering it.
    CONTROL_BAR_MERGE_HIDE: bytes.fromhex("8b0e83a68400"),
    CONTROL_BAR_MERGE_KEEP: bytes.fromhex("4383c604"),
    CONTROL_BAR_MERGE_INSTALL: bytes.fromhex("8b0e85c989be8400000074"),
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
    # The two engine routines the cave reaches out to, and the parser the new row names.
    OBJECT_HAS_UPGRADE: bytes.fromhex("8b44240485c07504"),
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
    """Raise unless ``keyword`` is a token the engine's INI reader could ever match."""
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


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address, the keyword and how many rows the
    live field table turned out to have.

    Pure arithmetic on those three, so :meth:`MultiSelectGroupPatch.apply` and
    :meth:`MultiSelectGroupPatch.verify` compute the same addresses from opposite directions."""

    keyword_va: int
    table_va: int
    code_va: int


#: The keyword string is the first thing in the cave, at a fixed offset - which is what lets
#: :meth:`MultiSelectGroupPatch.detect` read it back out of a binary it knows nothing else about.
_KEYWORD_OFFSET = 0


def _layout(base_va: int, keyword: str, rows: int) -> _Layout:
    keyword_va = base_va + _KEYWORD_OFFSET
    string = len(keyword) + 1
    table_va = keyword_va + string + (-string % 4)  # keep the table's dwords aligned
    code_va = table_va + (rows + 2) * FIELD_PARSE_STRIDE  # + the new row + the terminator
    return _Layout(keyword_va, table_va, code_va)


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


def _assemble(code_va: int) -> Asm:
    a = Asm(code_va)

    # The merge's verdict for one slot. `edi` is this object's button, `eax` the one already
    # installed, `cl` the stock `ATTACK_MOVE` flag - all three exactly as the displaced
    # instructions found them. `edx` is dead across the whole loop, which is what it is used for.
    a.label("merge")
    a.emit(0x3B, 0xF8)  # cmp edi, eax           ; the displaced identity compare
    a.jcc(JE, "keep")
    a.emit(0x84, 0xC9)  # test cl, cl            ; the displaced ATTACK_MOVE exemption
    a.jcc(JNE, "keep")

    # A slot one side does not fill at all has nothing to group with. Both arms are reachable:
    # `edi` is NULL when this object's set is short, `eax` when nothing is installed yet.
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "hide")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "hide")

    # The field, on both buttons. Zero is the default and means "not grouped", so it can never
    # match - two ungrouped buttons take the stock path they always did.
    a.emit(0x0F, 0xB7, 0x97, _u32(MULTI_SELECT_GROUP_OFFSET))  # movzx edx, word [edi+0x12E]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "hide")
    a.emit(0x66, 0x3B, 0x90, _u32(MULTI_SELECT_GROUP_OFFSET))  # cmp dx, word [eax+0x12E]
    a.jcc(JNE, "hide")

    # Same non-zero group. Rank the two by stage when both buy something; when either does not,
    # there is no stage to compare and the installed button stands.
    a.emit(0x8B, 0x50, COMMAND_BUTTON_UPGRADE)  # mov edx, [eax+0x24]   ; the installed Upgrade
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "keep")
    a.emit(0x83, 0x7F, COMMAND_BUTTON_UPGRADE, 0x00)  # cmp dword [edi+0x24], 0
    a.jcc(JE, "keep")

    # `Object::hasUpgrade(installed->Upgrade)` on the unit being merged. `pushad`/`popad` because
    # every register in the loop is live across it and the callee's own clobbers are not this
    # patch's to know; `popad` leaves EFLAGS alone, which is what carries the answer out.
    # `[ebp-0x14]` is the `Object`, non-NULL wherever this loop runs - the function returns at
    # `0x00944754` when it is not.
    a.emit(0x60)  # pushad
    a.emit(0x52)  # push edx                              ; the UpgradeTemplate
    a.emit(0x8B, 0x4D, CONTROL_BAR_MERGE_OBJECT_EBP & 0xFF)  # mov ecx, [ebp-0x14]
    a.call_absolute(OBJECT_HAS_UPGRADE)  # thiscall, ret 4 - it cleans the argument
    a.emit(0x84, 0xC0)  # test al, al
    a.emit(0x61)  # popad
    # It has the installed button's upgrade, so it is past that stage and the installed button is
    # the earlier of the two. Otherwise this unit is the one behind, and its button is.
    a.jcc(JNE, "keep")
    a.emit(0x33, 0xC0)  # xor eax, eax     ; the install arm passes eax to winHide
    a.jmp_absolute(CONTROL_BAR_MERGE_INSTALL)

    a.label("keep")
    a.jmp_absolute(CONTROL_BAR_MERGE_KEEP)
    a.label("hide")
    a.jmp_absolute(CONTROL_BAR_MERGE_HIDE)
    return a


def build_code(code_va: int) -> bytes:
    """The cave's routine, laid out at the address it will occupy."""
    return _assemble(code_va).finish()


def entry_points(code_va: int) -> dict[str, int]:
    """Where each routine starts, taken from the layout that was actually emitted rather than
    counted a second time by hand."""
    a = _assemble(code_va)
    return {name: a.label_va(name) for name in ROUTINES}


def _hook(site_va: int, window: bytes, target_va: int) -> bytes:
    """`jmp rel32` to ``target_va``, padded with `nop` to the width of ``window``."""
    jump = b"\xe9" + struct.pack("<i", target_va - (site_va + 5))
    if len(window) < len(jump):
        raise ValueError(f"the window at {site_va:#010x} is too small for a jmp rel32")
    return jump + b"\x90" * (len(window) - len(jump))


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA {va:#010x} is not mapped - not the expected build")
    return off


def _cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    """The NUL-terminated ASCII string at ``va``, or None if it is unmapped or not one."""
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data).find(b"\x00", off, off + limit)
    if end < 0:
        return None
    try:
        return data[off:end].decode("ascii")
    except UnicodeDecodeError:
        return None


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

    #: The five-byte jump the routine is reached by, as ``{hook va: (stock bytes, routine)}``. The
    #: window is eight bytes, so it takes three trailing `nop`.
    _HOOKS = {CONTROL_BAR_MERGE_SLOT: (CONTROL_BAR_MERGE_SLOT_BYTES, "merge")}

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        table_va = self._resolve(data)
        entries = self._check_table(data, table_va)

        base_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build(base, entries), _CHARACTERISTICS
        )
        pieces = _layout(base_va, self.keyword, len(entries))
        routines = entry_points(pieces.code_va)

        for hook_va, (stock, routine) in self._HOOKS.items():
            apply_byte_patch(
                data,
                _offset(data, hook_va),
                stock,
                _hook(hook_va, stock, routines[routine]),
                f"{hook_va:#010x} -> the {SECTION_NAME} {routine} routine",
            )
        apply_byte_patch(
            data,
            _offset(data, COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY),
            COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES,
            rewritten_default(),
            f"CommandButton::CommandButton defaults +{MULTI_SELECT_GROUP_OFFSET:#05x} to 0",
        )
        table_ref = _u32(pieces.table_va)
        for ref_va, opcode in zip(
            COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = _offset(data, ref_va)
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
        return bytes(blob) + build_code(pieces.code_va)

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
            off = _offset(data, va)
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
        by_name = {_cstring(data, name): offset for name, _fn, _ud, offset in entries}
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
        """Recognise this patch **and recover its keyword** from ``data``.

        The default probe would only ever recognise the default keyword. The keyword string is the
        first thing in the cave, so it reads straight back out; `verify` then checks the whole cave
        against it."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = _cstring(data, located[0] + _KEYWORD_OFFSET)
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
        refuses anything outside ``0..65535``, and the value is an identity, not a quantity."""
        return Engine(fields=(FieldDelta("CommandButton", self.keyword, "Int", 0, self.name),))

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch for exactly this keyword. Reads only
        via ``struct`` and the section table, so it needs no disassembler.

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
        code = build_code(pieces.code_va)
        if pieces.code_va + len(code) > section_va + vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for the table and the code"]
        got_keyword = _cstring(data, pieces.keyword_va)
        if got_keyword != self.keyword:
            problems.append(
                f"the keyword in {SECTION_NAME} is {got_keyword!r}, not {self.keyword!r}"
            )
        want_table = build_table(preceding, pieces.keyword_va)
        table_off = _offset(data, pieces.table_va)
        if bytes(data[table_off : table_off + len(want_table)]) != want_table:
            problems.append(
                f"the field table at {pieces.table_va:#010x} is not the live rows plus an "
                f"UnsignedShort at CommandButton+{MULTI_SELECT_GROUP_OFFSET:#05x}"
            )
        code_off = _offset(data, pieces.code_va)
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
        routines = entry_points(pieces.code_va)
        problems: list[str] = []
        for hook_va, (stock, routine) in self._HOOKS.items():
            want = _hook(hook_va, stock, routines[routine])
            off = _offset(data, hook_va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(
                    f"@{hook_va:#010x}: this site does not reach the {SECTION_NAME} {routine} "
                    f"routine (holds {got.hex()})"
                )
        off = _offset(data, COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY)
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
        row = next((e for e in live if _cstring(data, e[0]) == self.keyword), None)
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
