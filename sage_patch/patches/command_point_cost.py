"""The command-point-cost patch: a button can cost command points, and greys out without them.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/command-point-cost.md``.

**The gap.** Command points gate *recruitment*, and only recruitment. `BuildAssistant`'s production
gate asks `hasEnoughCommandPoints` about the `ThingTemplate` being queued (``0x0079402B``), and
that is the whole of the rule: the cost is a property of the unit, and it is read when a unit
enters a production queue. A special power that drops a battalion on the map, or an upgrade whose
`DoCommandUpgrade` summons one, reaches none of that. Its button is lit at 1500 of 1500 command
points, it fires, and the army it makes arrives outside the cap every recruited battalion pays.

**What this does.** Adds one field, `CommandPointCost`, to `CommandButton`. Default `0`, which is
stock behaviour; any positive value means *this button is unavailable unless the player has that
many command points free*. Free is the engine's own arithmetic, not a new one:
``getCommandPointCap() - pointsInUse``, the same two numbers `hasEnoughCommandPoints` subtracts, so
the field agrees with the palantir readout and with the cap a `CPObject` raises.

The refusal is the engine's own too. The ControlBar's availability evaluator already has a verdict
for this - **7**, which it produces at ``0x00942F47`` when the production gate answers "not enough
command points". It greys the button, and a click on it plays `GUI:ErrorNoMoreCommandPoints` over
the object rather than issuing an order. So a summon button carrying `CommandPointCost` behaves
like a recruit button at the cap, because it is answered with the same number.

**It gates the button, not the power.** The evaluator is client-side UI, and this patch stops
there: it charges nothing, reserves nothing, and does not touch the logic side. A power fired by a
script, by the AI's own special-power evaluation, or by any path that does not go through a command
button is unaffected - and so is the cost of what the power summons, which is still paid the moment
the summoned objects exist, by the stock accounting. The field is a *requirement*, in the way
`RequireLevel` is: it says what the player must have to press the button.

Four edits, one cave
--------------------
1. **The field, in the struct's own padding.** `CommandButton+0x10E` is inside the alignment gap
   between `AutoAbility` (a `Bool` at +0x10C) and the `KindOfFlags` at +0x110: no row in the field
   table names it, the constructor never writes it, and the ``memset(this+0x110, 0, 0x1C)`` that
   follows starts past it. Two aligned bytes, parsed by the engine's own `INI::parseUnsignedShort`
   (``0x0042EC11``), which range-checks ``0..65535`` and stores a word - two orders of magnitude
   past the 1500 hard cap, so the range is not a limit anyone can reach. ``sizeof`` stays 0x2E0 and
   `ControlBar::newCommandButton`'s ``operator new(0x2E0)`` is untouched.

2. **The default.** `operator new` does not zero the block, so the field needs initialising or
   every button in the game inherits a random cost. The constructor's ``mov [esi+0x108], ebx`` -
   `RequireLevel`'s default, six bytes, one whole instruction - is displaced into the cave, which
   reproduces it and then writes an explicit zero word at +0x10E.

3. **The field table moves, and three references are repointed.** The stock table at ``0x00C2BAC8``
   is boxed in by its own terminator, so it is rebuilt in the cave: every live row copied verbatim,
   since their name pointers are absolute, plus one appended `UnsignedShort` row and the
   terminator. The three references are the static accessor at ``0x005DA706`` and the two `push`
   immediates in the block parser, one for a fresh button and one for an override. The table is
   walked to its terminator rather than to a count, so no bound is raised anywhere.

4. **The check, at the top of the one evaluator.** `ControlBar::getCommandAvailability`
   (``0x00942733``) is the single routine every caller asks whether a button is usable - the two
   that draw it, the two that execute a click, the radial menu's and the palantir's. Its first act
   once the local player is resolved is ``mov edi, [ebp+8]`` / ``mov eax, [edi+0x14]``: the button,
   and the GUI command it dispatches on. Those six bytes are displaced, and the cave asks the new
   field before it hands them back.

   **The check has to be here rather than at the function's exit**, and that is not a preference.
   `edi` is reloaded eleven times inside the function and the argument slot `[ebp+8]` is reused as
   scratch by four of the command cases, so by the time a verdict exists the button is no longer
   recoverable from either. At the top both are still what the caller passed. Nothing is lost by
   answering early: every one of the evaluator's own thirty-odd refusals answers 3, and it answers
   3 whether it is reached or not, so short-circuiting can only turn an *otherwise usable* button
   unavailable - which is the whole feature.

**Determinism.** Nothing this patch writes is logic-side state, and nothing it reads is state a
peer can disagree about: the evaluator runs on the client, over the local player's own command bar,
and its answer decides whether an order is created rather than what an order does. An unpatched
peer in the same game would simply let its own player press a button this one greys. What *is*
fatal on a stock build is the keyword - SAGE treats an unknown field in a known block as a parse
error - so a mod using it ships the patched `game.dat` or does not run at all.

**Composition.** Order-independent: the cave is allocated past every existing section, `verify`
finds it by name, and the field table is located from its live references rather than from the
stock constant, so it appends to whatever is there. The nearest neighbour is `queue-ignore-cp`,
which takes the *byte* at +0x10D and widens the constructor's `AutoAbility` store at ``0x0075D688``
to clear it - a different byte and a different instruction from the ones here, and the two rebuild
the same table by reading it live, so either order gives a binary both verify.
`multi-execute-gate` hooks ``0x00942490``, the model-condition predicate this evaluator calls, and
shares no bytes with it.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    COMMAND_BUTTON_AUTO_ABILITY,
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    FIELD_PARSE_STRIDE,
    INI_PARSE_UNSIGNED_SHORT,
)
from ..asm import JE, JG, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "COMMAND_POINT_COST_OFFSET",
    "DEFAULT_KEYWORD",
    "ROUTINES",
    "SECTION_NAME",
    "CommandPointCostPatch",
    "build_code",
    "build_table",
    "entry_points",
    "validate_keyword",
]

SECTION_NAME = ".cpcost"  # the PE name field is 8 bytes and truncates silently

#: The INI keyword the new `CommandButton` field is parsed under.
DEFAULT_KEYWORD = "CommandPointCost"

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave holds the keyword
#: string and the rebuilt table (read) and the two routines (executed); nothing in it is ever
#: written, which is what lets the section stay read-only.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000

# --- the field's home ---------------------------------------------------------------------------

#: `CommandPointCost`, an `UnsignedShort` in `CommandButton`'s alignment padding. `AutoAbility` is
#: the `Bool` at +0x10C and `AffectsKindOf` the `KindOfFlags` at +0x110, so +0x10D..+0x10F is a
#: three-byte hole; +0x10E is the aligned word inside it, and +0x10D - the byte `queue-ignore-cp`
#: takes - is the one this patch leaves alone.
COMMAND_POINT_COST_OFFSET = 0x10E

# --- the engine ---------------------------------------------------------------------------------

#: `Player::getCommandPointCap` - ``__thiscall`` on the command-point subobject at `Player+0x60`,
#: no arguments, answers in `eax`. It is the cap in full: the base at +0x64 plus the `CPObject`
#: bonus at +0x6C plus a filtered vector's term, clamped by ``cmovg`` against the hard cap at
#: +0x70. Asking it is the only way to get the number the engine itself gates on, which is why the
#: cave calls it rather than reading a field.
#:
#: It does **not** preserve `ecx`: the ``push ecx`` in its prologue is a local slot, which
#: ``mov [esp+0xc], eax`` overwrites before the matching ``pop ecx``. The cave therefore carries
#: its own value across the call on the stack rather than in a register.
GET_COMMAND_POINT_CAP = 0x006A7B9F

#: `Player::m_commandPoints`, the subobject every caller reaches as ``lea ecx, [player+0x60]``, and
#: the points-in-use dword inside it that `hasEnoughCommandPoints` reads as ``[ecx+8]``.
PLAYER_COMMAND_POINTS = 0x60
COMMAND_POINTS_IN_USE = 0x08

#: `ControlBar::getCommandAvailability` - ``stdcall``, ``ret 0x14``, one epilogue. The single
#: routine that answers "is this button usable", asked by the two draw paths, the two click
#: executors, the radial menu and the palantir - seven callers, plus one recursive call it makes
#: about a toggle button's partner.
AVAILABILITY = 0x00942733

#: Its `CommandButton *` argument, and the frame slot holding the player whose command bar is being
#: evaluated (`ThePlayerList->getLocalPlayer()`, or the observed player). The slot is filled at
#: ``0x00942766`` and the function returns 3 immediately when it is NULL, so at the hook it is both
#: set and non-NULL; the cave tests it anyway, because a null deref here is a crash and the test is
#: four bytes.
AVAILABILITY_BUTTON_EBP = 0x08
AVAILABILITY_PLAYER_EBP = -0x10

#: The verdict for "not enough command points". The evaluator already produces it, at
#: ``0x00942F47``, when the production gate answers 7 about a `UNIT_BUILD` button - which is what
#: makes it the right answer here rather than a new one: ``0x0071CCB0`` greys the button for it and
#: ``0x009405B3`` answers a click on it with `GUI:ErrorNoMoreCommandPoints` instead of an order.
NOT_ENOUGH_COMMAND_POINTS = 7

#: The evaluator's shared refusal tail - the ``pop eax`` that takes the pushed code, and the
#: epilogue behind it. The engine's own verdict sites reach it as ``push <code>`` / ``jmp``, and
#: the cave reproduces that shape exactly.
AVAILABILITY_REFUSE_TAIL = 0x00942C5F

# --- the hooks ----------------------------------------------------------------------------------

#: The evaluator's first two instructions past the local-player resolution: the button, and the GUI
#: command it dispatches on. Six bytes, two whole instructions, and `ebx`/`edi` have just been
#: pushed - so the cave may clobber both and the refusal tail's pops still balance.
AVAILABILITY_HOOK_VA = 0x00942775
AVAILABILITY_HOOK_STOCK = bytes.fromhex("8b7d088b4714")  # mov edi,[ebp+8]; mov eax,[edi+0x14]
AVAILABILITY_RESUME_VA = 0x0094277B

#: `CommandButton`'s constructor defaulting `RequireLevel`. Six bytes, one whole instruction, and
#: the instruction that follows it is the `AutoAbility` store `queue-ignore-cp` rewrites - which is
#: why this patch takes the one before rather than sharing.
CTOR_HOOK_VA = 0x0075D682
CTOR_HOOK_STOCK = bytes.fromhex("899e08010000")  # mov dword [esi+0x108], ebx
CTOR_RESUME_VA = 0x0075D688

#: The first bytes at every address the cave jumps to or calls, plus the windows that prove the two
#: hooks sit inside the functions this patch believes they do. A build whose layout moved fails
#: here rather than on a wild jump or a word written into somebody else's field.
#:
#: ``0x0075D688`` is deliberately **not** anchored: it is the instruction `queue-ignore-cp`
#: rewrites, and anchoring it would make the two patches order-dependent for no gain.
ANCHORS: dict[int, bytes] = {
    AVAILABILITY_HOOK_VA: AVAILABILITY_HOOK_STOCK,
    CTOR_HOOK_VA: CTOR_HOOK_STOCK,
    # The evaluator's entry, its `getLocalPlayer` call and the store that fills the player slot -
    # together, the proof that `[ebp-0x10]` holds a `Player *` at the hook.
    AVAILABILITY: bytes.fromhex("b81ec4ba00"),
    0x0094275D: bytes.fromhex("e8d760d6ff"),  # call ThePlayerList::getLocalPlayer
    0x00942766: bytes.fromhex("894df0"),  # mov [ebp-0x10], ecx
    # `push ebx` / `push edi`, immediately before the hook: what makes both free to clobber.
    0x00942773: bytes.fromhex("5357"),
    # ⚠ **`ecx` is live across the hook window.** ``mov ecx, eax`` puts the local player in it, and
    # the two `__thiscall`s the displaced `Command` load dispatches to - `0x20` and `0x26` - are
    # reached with it untouched, six and thirteen bytes past the resume point. Their prologues
    # (``mov esi, ecx`` / ``mov [ebp-8], ecx``) are anchored too, because "this argument is passed
    # in `ecx`" is the fact that makes the liveness matter. A cave that clobbers `ecx` faults at
    # ``0x006AD100`` on a null `this`; this one saves every register instead.
    0x00942762: bytes.fromhex("8bc8"),  # mov ecx, eax
    0x00942785: bytes.fromhex("e86ea9d6ff"),  # call 0x6ad0f8   (Command == 0x26)
    0x0094278C: bytes.fromhex("e848a9d6ff"),  # call 0x6ad0d9   (Command == 0x20)
    0x006AD0F8: bytes.fromhex("558bec5151568bf183be"),  # push ebp..mov esi,ecx; cmp [esi+0x710]
    0x006AD0D9: bytes.fromhex("558bec515183"),
    # The refusal tail, and the engine's own verdict-7 site the cave copies its shape from.
    AVAILABILITY_REFUSE_TAIL: bytes.fromhex("585f5b"),  # pop eax; pop edi; pop ebx
    0x00942F42: bytes.fromhex("83f80775076a07"),  # cmp eax,7; jne; push 7
    AVAILABILITY_RESUME_VA: bytes.fromhex("83f820"),  # cmp eax, 0x20 - the displaced load's reader
    # The constructor: its entry, the `xor ebx, ebx` the displaced store's zero comes from, and the
    # `memset(this+0x110, 0, 0x1C)` that proves the padding ends where the new field does.
    0x0075D516: bytes.fromhex("b80c20b900"),
    0x0075D52A: bytes.fromhex("33db"),
    0x0075D721: bytes.fromhex("6a1c8d8610010000"),  # push 0x1c; lea eax, [esi+0x110]
    # `operator new(0x2E0)` in `ControlBar::newCommandButton` - untouched, and asserted so, because
    # a field in the padding is only free while the allocation is the size it is.
    0x0071C446: bytes.fromhex("68e0020000"),
    # The two engine routines the cave reaches out to.
    GET_COMMAND_POINT_CAP: bytes.fromhex("5153568bf1"),
    INI_PARSE_UNSIGNED_SHORT: bytes.fromhex("558bec5151"),
}

#: Fields the live table must still carry at these offsets, or this is not the build the layout
#: above was derived against. Checked by name rather than by count, so it survives another patch
#: having appended to the same table first.
FINGERPRINT = {
    "Command": COMMAND_BUTTON_COMMAND,
    "RequireLevel": 0x108,
    # the two the padding sits between: the field's home is only free if these are where the
    # constructor's stores and the `KindOfFlags` memset say they are
    "AutoAbility": COMMAND_BUTTON_AUTO_ABILITY,
    "AffectsKindOf": 0x110,
}

#: The cave's routines, in the order they are laid out. Each is the target of one hook.
ROUTINES = ("ctor", "gate")

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


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address, the keyword and how many rows the
    live field table turned out to have.

    Pure arithmetic on those three, so :meth:`CommandPointCostPatch.apply` and
    :meth:`CommandPointCostPatch.verify` compute the same addresses from opposite directions."""

    keyword_va: int
    table_va: int
    code_va: int


#: The keyword string is the first thing in the cave, at a fixed offset - which is what lets
#: :meth:`CommandPointCostPatch.detect` read it back out of a binary it knows nothing else about.
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
        "<IIII", keyword_va, INI_PARSE_UNSIGNED_SHORT, 0, COMMAND_POINT_COST_OFFSET
    )
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


def _assemble(code_va: int) -> Asm:
    a = Asm(code_va)

    # --- the constructor's `RequireLevel` default, with the new field zeroed behind it ---
    a.label("ctor")
    a.emit(CTOR_HOOK_STOCK)  # mov dword [esi+0x108], ebx
    # `ebx` is zero here and `mov word [esi+0x10E], bx` would be shorter, but the field's default
    # is the one thing in this patch that nothing downstream can catch, so it is a literal.
    a.emit(0x66, 0xC7, 0x86, _u32(COMMAND_POINT_COST_OFFSET), 0x00, 0x00)  # mov word [..], 0
    a.jmp_absolute(CTOR_RESUME_VA)

    # --- the availability evaluator, asked before it starts deciding ---
    #
    # ⚠ `ecx` is **live** across this window: it is the `Player *` from ``0x00942762``, and the two
    # `__thiscall`s at ``0x00942785`` / ``0x0094278C`` are reached with it still in place, because
    # the two instructions displaced here happen not to touch it. Clobbering it crashes at
    # ``0x006AD100`` (`cmp [esi+0x710], 0` on a null `this`) for any button whose `Command` is
    # `0x20` or `0x26`. So the routine saves **every** register rather than the ones it noticed:
    # `pushad`/`popad` cost one byte each, neither touches EFLAGS - which is what lets the verdict
    # be carried out of the guarded region in the flags - and being wrong about a live register is
    # the one mistake here that assembles, applies, verifies and then crashes in play.
    a.label("gate")
    a.emit(0x8B, 0x7D, AVAILABILITY_BUTTON_EBP)  # mov edi, [ebp+8]        ; the CommandButton
    a.emit(0x60)  # pushad
    a.emit(0x0F, 0xB7, 0x87, _u32(COMMAND_POINT_COST_OFFSET))  # movzx eax, word [edi+0x10E]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "stock")  # no cost declared: nothing to say
    a.emit(0x8B, 0x55, AVAILABILITY_PLAYER_EBP & 0xFF)  # mov edx, [ebp-0x10]    ; the Player
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc_short(JE, "stock")
    a.emit(0x83, 0xC2, PLAYER_COMMAND_POINTS)  # add edx, 0x60
    a.emit(0x03, 0x42, COMMAND_POINTS_IN_USE)  # add eax, [edx+8]        ; cost + points in use
    # `getCommandPointCap` answers in `eax` and clobbers `ecx`, so the total crosses on the stack.
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCA)  # mov ecx, edx
    a.call_absolute(GET_COMMAND_POINT_CAP)
    a.emit(0x5A)  # pop edx
    a.emit(0x3B, 0xD0)  # cmp edx, eax        ; the comparison hasEnoughCommandPoints makes
    a.jcc_short(JG, "refuse")  # over the cap: the player has not got them free
    a.label("stock")
    a.emit(0x61)  # popad                   ; flags survive it, and so does the live ecx
    a.emit(0x8B, 0x47, COMMAND_BUTTON_COMMAND)  # mov eax, [edi+0x14]     ; the displaced second
    a.jmp_absolute(AVAILABILITY_RESUME_VA)
    a.label("refuse")
    a.emit(0x61)  # popad
    a.emit(0x6A, NOT_ENOUGH_COMMAND_POINTS)  # push 7
    a.jmp_absolute(AVAILABILITY_REFUSE_TAIL)
    return a


def build_code(code_va: int) -> bytes:
    """The cave's two routines, laid out at the address they will occupy."""
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


class CommandPointCostPatch(Patch):
    """Add a `CommandPointCost` `UnsignedShort` to `CommandButton`, so a button that summons units
    can be made unavailable while the player has fewer than that many command points free."""

    name = "command-point-cost"
    author = "officialNecro"
    description = (
        "Add a CommandPointCost integer to CommandButton, so a summoning special power or upgrade "
        "greys out unless the player has that many command points free - the engine's own "
        "GUI:ErrorNoMoreCommandPoints answers a click on it. Write CommandPointCost = <n> on that "
        "button; 0, the default, is stock. It gates the button only: nothing is charged or "
        "reserved, and the units it summons still cost their own CommandPoints as they always did"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    #: The five-byte jump each routine is reached by, as ``{hook va: (stock bytes, routine)}``.
    #: Both windows are six bytes, so both take a trailing `nop`.
    _HOOKS = {
        CTOR_HOOK_VA: (CTOR_HOOK_STOCK, "ctor"),
        AVAILABILITY_HOOK_VA: (AVAILABILITY_HOOK_STOCK, "gate"),
    }

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
                    "ControlBar and CommandButton are not the ones command-point-cost was derived "
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
    def detect(cls, data: bytes | bytearray) -> CommandPointCostPatch | None:
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
        installed with. The constructor zeroes it, so the default is `0` - stock behaviour, which
        is what makes the field opt-in.

        Declared `Int` because that is what a mod writes: the engine's `UnsignedShort` parser
        refuses anything outside ``0..65535``, and the hard command-point cap is 1500."""
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
                f"UnsignedShort at CommandButton+{COMMAND_POINT_COST_OFFSET:#05x}"
            )
        code_off = _offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(code)]) != code:
            problems.append(f"the code at {pieces.code_va:#010x} is not what this patch builds")
        return problems

    def _verify_sites(
        self, data: bytes | bytearray, pieces: _Layout, live: tuple[Entry, ...]
    ) -> list[str]:
        """The two hooks, and the row the engine will actually parse this field through.

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

        want_row = (
            pieces.keyword_va,
            INI_PARSE_UNSIGNED_SHORT,
            0,
            COMMAND_POINT_COST_OFFSET,
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
    def from_cli_args(cls, args: argparse.Namespace) -> CommandPointCostPatch:
        return cls(keyword=args.keyword)
