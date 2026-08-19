"""The queue-ignore-cp patch: let a button queue production the command-point cap would refuse.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/queue-ignore-cp.md``.

**The gap.** A `CommandButton` can be pressed by the engine as well as by a player:
`DoCommandUpgrade` looks its `GetUpgradeCommandButtonName` up in `TheControlBar` and calls
`Object::doCommandButton` with it, which is how a power or a research "clicks" a recruitment
button on the object's behalf. That press goes through the same gate a human click does -
`BuildAssistant`'s vtable `+0x64` (`0x00793ECB`) - and that gate's **last** refusal is the
command-point cap: `hasEnoughCommandPoints` says no, the gate answers 7, and
`ProductionUpdate::queueCreateUnit` returns FALSE before anything is queued or charged.

For a player that is a click that does nothing and can be repeated. For an upgrade-driven press
it is the whole feature lost: the upgrade has already been granted, the power has already been
spent, and nothing will press the button again.

**What this does.** Adds one boolean field, `QueueIgnoreCP`, to `CommandButton`. Default `No`,
which is stock behaviour; `Yes` means a press of *this* button may queue its unit even when the
player is at the command-point cap. Nothing else about the gate moves - the button still needs
the gold, the producer, the queue slot and every prerequisite, and a unit queued this way is
still charged the moment it is queued.

**The other half is already in the engine.** The queue does not run away with the cap once the
unit is in it, because the stock `ProductionUpdate::update` refuses to advance a head entry the
player cannot afford in command points (`0x008A1E27`): it asks the *same* predicate about the
entry's own template and, when the answer is no, plays EVA message 0x0B for the local player and
returns before the block that adds this frame's progress. Revives get the same treatment from a
different direction - `0x008A0669`, called from the top of `update`, pushes the revive's start
frame out by one frame per tick while the cap holds. So a unit queued through this field sits at
the head of the queue, charged and waiting, and starts building the moment command points free
up. That is the behaviour this field is for, and it needed no patching.

Four edits, one cave
--------------------
1. **The field, in the struct's own padding.** `CommandButton+0x10D` is the alignment gap between
   `AutoAbility` (a `Bool` at +0x10C) and the `KindOfFlags` at +0x110: no row in the field table
   names it, the constructor never writes it, and the `memset(this+0x110, 0, 0x1C)` that follows
   starts past it. ``sizeof`` stays 0x2E0 and `ControlBar::newCommandButton`'s
   ``operator new(0x2E0)`` is untouched.

2. **The default, for one byte.** `operator new` does not zero the block, so the field still needs
   initialising. The constructor's ``mov byte [esi+0x10C], bl`` becomes
   ``mov dword [esi+0x10C], ebx`` - **0x88 to 0x89, six bytes for six** - which leaves
   `AutoAbility` at `No` and clears +0x10D..+0x10F on the way past. `ebx` is the zero the whole
   constructor stores from, six bytes earlier included.

3. **The field table moves, and three references are repointed.** The stock table at
   ``0x00C2BAC8`` is boxed in by its own terminator, so it is rebuilt in the cave - every live
   row copied verbatim, since their name pointers are absolute, plus one appended `Bool` row and
   the terminator. The three references are the static accessor at ``0x005DA706`` and the two
   `push` immediates in the block parser, one for a fresh button and one for an override. The
   table is walked to its terminator rather than to a count, so no bound is raised anywhere.

4. **Three hooks, and a flag that lives for one call.** The gate takes
   ``(producer, what, reviveIndex)`` and never sees the button, so the button's answer has to
   reach it some other way. The two calls to `ProductionUpdate::queueCreateUnit` in
   `Object::doCommandButton` - the `UNIT_BUILD` case and the `REVIVE` case, five and six bytes,
   whole instructions both - are wrapped: read `[ebp+8]->QueueIgnoreCP` into a dword in the cave,
   run the displaced call, clear it. The gate's command-point verdict (eight bytes at
   ``0x0079402B``) then reads that dword and, when it is set, takes the accept edge instead of
   pushing 7.

   The flag is therefore only ever non-zero *inside* one `queueCreateUnit` call on the logic
   thread, which is what makes it safe: no other caller of the gate can observe it, and it cannot
   survive a frame. It is set and cleared in the same wrapper, so it is re-entrancy-proof by
   construction rather than by argument.

**What it does not do.** The ControlBar's own availability query is left stock. A *visible*
button carrying this field is still drawn unavailable while the player is at the cap and still
answers "not enough command points" when clicked, because that verdict is reached from
`ControlBar` frames this patch does not hook. The field is for buttons the engine presses -
`DoCommandUpgrade`, and anything else that reaches `Object::doCommandButton` without going
through the control bar's own refusal first.

Nor does it touch what the cap *means*: a unit queued past it still costs its command points once
it exists, `Player+0x68` still counts it, and every other consumer of the cap - the AI's own
production choices, the palantir readout, `IgnoreCommandPointLimit` on a template - is unchanged.

**Determinism.** The flag is written and read on the logic thread inside one order's execution
and is zero at every frame boundary, so it is not state a peer can disagree about and nothing the
engine CRCs changes. What *does* need every peer on the same binary is the consequence: a client
without the patch refuses the production a patched client accepts, and the two diverge on the
next frame. And the keyword is fatal on a stock build - SAGE treats an unknown field in a known
block as a parse error - so a mod using it ships the patched `game.dat` or does not run at all.

**Composition.** Order-independent: the cave is allocated past every existing section, `verify`
finds it by name, and the field table is located from its live references rather than from the
stock constant, so it appends to whatever is there. The nearest neighbour is `second-resource`,
which takes the gate's *money* verdict at ``0x00794013`` - 24 bytes below the command-point one,
no overlap - and rebuilds three other field tables, not this one. `unique-production-id` rewrites
`requestUniqueUnitID`, which the two hooked cases call one instruction before the window this
patch takes.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    BUILD_ASSISTANT_VTABLE,
    BUILD_GATE_COMMAND_POINTS,
    BUILD_GATE_COMMAND_POINTS_BYTES,
    BUILD_GATE_COMMAND_POINTS_OK,
    BUILD_GATE_COMMAND_POINTS_REFUSE,
    BUILD_GATE_NOT_ENOUGH_COMMAND_POINTS,
    CAN_MAKE_UNIT_PRODUCTION_GATE,
    CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
    COMMAND_BUTTON_AUTO_ABILITY,
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_CTOR_AUTO_ABILITY,
    COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    COMMAND_BUTTON_FREE_OFFSET,
    DO_COMMAND_BUTTON_BUTTON_EBP,
    DO_COMMAND_BUTTON_REVIVE_QUEUE,
    DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES,
    DO_COMMAND_BUTTON_REVIVE_QUEUE_RESUME,
    DO_COMMAND_BUTTON_UNIT_QUEUE,
    DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES,
    DO_COMMAND_BUTTON_UNIT_QUEUE_RESUME,
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_KEYWORD",
    "SECTION_NAME",
    "QueueIgnoreCpPatch",
    "build_code",
    "build_table",
    "rewritten_default",
    "validate_keyword",
]

SECTION_NAME = ".qcp"  # the PE name field is 8 bytes and truncates silently

#: The INI keyword the new `CommandButton` field is parsed under.
DEFAULT_KEYWORD = "QueueIgnoreCP"

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds
#: the rebuilt table (read), the three routines (executed) and the flag (**written**).
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: Fields the live table must still carry at these offsets, or this is not the build the layout
#: above was derived against. Checked by name rather than by count, so it survives another patch
#: having appended to the same table first.
FINGERPRINT = {
    "Command": COMMAND_BUTTON_COMMAND,
    "RequireLevel": 0x108,
    # the two the padding sits between: the field's home is only free if these are where the
    # constructor's store and the `KindOfFlags` memset say they are
    "AutoAbility": COMMAND_BUTTON_AUTO_ABILITY,
    "AffectsKindOf": 0x110,
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


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address, the keyword and how many rows
    the live field table turned out to have.

    Pure arithmetic on those three, so :meth:`QueueIgnoreCpPatch.apply` and
    :meth:`QueueIgnoreCpPatch.verify` compute the same addresses from opposite directions."""

    flag_va: int
    keyword_va: int
    table_va: int
    code_va: int


#: The flag is the first dword of the cave and the keyword string follows it, both at fixed
#: offsets - which is what lets :meth:`QueueIgnoreCpPatch.detect` read the keyword back out of a
#: binary it knows nothing else about.
_FLAG_OFFSET = 0
_KEYWORD_OFFSET = 4


def _layout(base_va: int, keyword: str, rows: int) -> _Layout:
    keyword_va = base_va + _KEYWORD_OFFSET
    string = len(keyword) + 1
    table_va = keyword_va + string + (-string % 4)  # keep the table's dwords aligned
    code_va = table_va + (rows + 2) * FIELD_PARSE_STRIDE  # + the new row + the terminator
    return _Layout(base_va + _FLAG_OFFSET, keyword_va, table_va, code_va)


def rewritten_default() -> bytes:
    """The constructor's `AutoAbility` store, widened to zero the new field as well.

    ``mov byte [esi+0x10C], bl`` becomes ``mov dword [esi+0x10C], ebx``: one byte changed, six
    for six, so there is no hook and no displaced instruction. `ebx` is zero throughout the
    constructor - it is what `RequireLevel` is defaulted with six bytes earlier - so `AutoAbility`
    keeps its `No` default and +0x10D..+0x10F are cleared on the way past."""
    new = bytes([0x89]) + COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES[1:]
    assert len(new) == len(COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES)
    return new


def build_table(entries: tuple[Entry, ...], keyword_va: int) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the new `Bool`, the terminator.

    The live rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are - and only the new row points into the cave."""
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", keyword_va, INI_PARSE_BOOL, 0, COMMAND_BUTTON_FREE_OFFSET)
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


def _emit_arm(a: Asm, flag_va: int) -> None:
    """Read the pressed button's `QueueIgnoreCP` into the cave's flag.

    `[ebp+8]` is `Object::doCommandButton`'s first argument and is never written, so it still
    holds the button at both call sites. `eax` is the only register touched, and at both sites it
    is dead - it holds the production id, which has already been pushed."""
    a.emit(0x8B, 0x45, DO_COMMAND_BUTTON_BUTTON_EBP)  # mov eax, [ebp+8]      ; the CommandButton
    a.emit(0x0F, 0xB6, 0x80, _u32(COMMAND_BUTTON_FREE_OFFSET))  # movzx eax, byte [eax+0x10D]
    a.emit(0xA3, _u32(flag_va))  # mov [flag], eax


def _emit_disarm(a: Asm, flag_va: int) -> None:
    """Clear the flag. Touches no register; the flags it sets are dead at both resume addresses,
    which are unconditional jumps to the function's common exit."""
    a.emit(0x83, 0x25, _u32(flag_va), 0x00)  # and dword [flag], 0


def build_code(code_va: int, flag_va: int) -> Asm:
    """The cave's three routines, laid out at the address they will occupy.

    Two wrappers around `queueCreateUnit`, which raise the flag for exactly the length of the
    call, and the gate's replacement verdict, which is the only thing that reads it. Returned as
    the :class:`~sage_patch.asm.Asm` rather than as bytes so the caller can take each routine's
    address from the same layout that produced them."""
    a = Asm(code_va)

    a.label("unit_build")  # in place of 0x00697800
    _emit_arm(a, flag_va)
    a.emit(DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES)  # mov ecx, edi / call [esi+0x20]
    _emit_disarm(a, flag_va)
    a.jmp_absolute(DO_COMMAND_BUTTON_UNIT_QUEUE_RESUME)

    a.label("revive")  # in place of 0x00697403
    _emit_arm(a, flag_va)
    a.emit(DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES)  # mov ecx, esi / push ebx / call [edi+0x20]
    _emit_disarm(a, flag_va)
    a.jmp_absolute(DO_COMMAND_BUTTON_REVIVE_QUEUE_RESUME)

    a.label("gate")  # in place of 0x0079402B
    a.emit(0x84, 0xC0)  # test al, al                  ; the stock verdict
    a.jcc_short(JNE, "allow")
    a.emit(0x83, 0x3D, _u32(flag_va), 0x00)  # cmp dword [flag], 0
    a.jcc_short(JE, "refuse")
    a.label("allow")
    a.jmp_absolute(BUILD_GATE_COMMAND_POINTS_OK)
    a.label("refuse")
    a.emit(0x6A, BUILD_GATE_NOT_ENOUGH_COMMAND_POINTS)  # push 7
    a.jmp_absolute(BUILD_GATE_COMMAND_POINTS_REFUSE)
    return a


def _hook(site_va: int, window: bytes, target_va: int) -> bytes:
    """`jmp rel32` to ``target_va``, padded with `nop` to the width of ``window``."""
    jump = b"\xe9" + struct.pack("<i", target_va - (site_va + 5))
    if len(window) < len(jump):
        raise ValueError(f"the window at 0x{site_va:08x} is too small for a jmp rel32")
    return jump + b"\x90" * (len(window) - len(jump))


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
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


class QueueIgnoreCpPatch(Patch):
    """Add a `QueueIgnoreCP` boolean to `CommandButton`, letting a press of that button queue
    production the command-point cap would otherwise refuse."""

    name = "queue-ignore-cp"
    author = "officialNecro"
    description = (
        "Add a QueueIgnoreCP boolean to CommandButton, so a button the engine presses (a "
        "DoCommandUpgrade, say) can queue its unit at the command-point cap - the stock queue "
        "then holds it until the points free up. Write QueueIgnoreCP = Yes on that button; No, "
        "the default, is stock, and the gold, producer and prerequisites are still required"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        self._check_dispatch(data)
        table_va = self._resolve(data)
        entries = self._check_table(data, table_va)

        base_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build(base, entries), _CHARACTERISTICS
        )
        pieces = _layout(base_va, self.keyword, len(entries))
        code = build_code(pieces.code_va, pieces.flag_va)

        for file_off, old, new, note in self._edits(data, pieces, code):
            apply_byte_patch(data, file_off, old, new, note)

    def _build(self, base_va: int, entries: tuple[Entry, ...]) -> bytes:
        """The cave: the flag, the keyword string, the rebuilt table, the code."""
        pieces = _layout(base_va, self.keyword, len(entries))
        blob = bytearray(_KEYWORD_OFFSET)  # the flag, zero at load
        blob += self.keyword.encode("ascii") + b"\x00"
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(entries, pieces.keyword_va)
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        return bytes(blob) + build_code(pieces.code_va, pieces.flag_va).finish()

    def _edits(
        self, data: bytes | bytearray, pieces: _Layout, code: Asm
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte this patch writes outside its own cave, as
        ``(file offset, expected, replacement, note)``."""
        edits: list[tuple[int, bytes, bytes, str]] = [
            (
                _offset(data, COMMAND_BUTTON_CTOR_AUTO_ABILITY),
                COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES,
                rewritten_default(),
                f"CommandButton ctor -> {self.keyword} defaults to No",
            ),
            (
                _offset(data, DO_COMMAND_BUTTON_UNIT_QUEUE),
                DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES,
                _hook(
                    DO_COMMAND_BUTTON_UNIT_QUEUE,
                    DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES,
                    code.label_va("unit_build"),
                ),
                f"doCommandButton UNIT_BUILD -> the {SECTION_NAME} queue wrapper",
            ),
            (
                _offset(data, DO_COMMAND_BUTTON_REVIVE_QUEUE),
                DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES,
                _hook(
                    DO_COMMAND_BUTTON_REVIVE_QUEUE,
                    DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES,
                    code.label_va("revive"),
                ),
                f"doCommandButton REVIVE -> the {SECTION_NAME} queue wrapper",
            ),
            (
                _offset(data, BUILD_GATE_COMMAND_POINTS),
                BUILD_GATE_COMMAND_POINTS_BYTES,
                _hook(
                    BUILD_GATE_COMMAND_POINTS,
                    BUILD_GATE_COMMAND_POINTS_BYTES,
                    code.label_va("gate"),
                ),
                f"the command-point verdict -> the {SECTION_NAME} gate",
            ),
        ]
        table_ref = _u32(pieces.table_va)
        for ref_va, opcode in zip(
            COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = _offset(data, ref_va)
            edits.append(
                (
                    off,
                    bytes(data[off : off + 5]),
                    bytes([opcode]) + table_ref,
                    f"CommandButton field table reference 0x{ref_va:08x} -> {SECTION_NAME}",
                )
            )
        return edits

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

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless `TheBuildAssistant`'s vtable still names the function being hooked.

        A hook installed inside some other function assembles perfectly and never runs."""
        slot_va = BUILD_ASSISTANT_VTABLE + CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT
        target = struct.unpack_from("<I", data, _offset(data, slot_va))[0]
        if target != CAN_MAKE_UNIT_PRODUCTION_GATE:
            raise ValueError(
                f"vtable slot 0x{slot_va:08x} dispatches to 0x{target:08x}, not "
                f"0x{CAN_MAKE_UNIT_PRODUCTION_GATE:08x} - the gate being hooked is not the live one"
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
    def detect(cls, data: bytes | bytearray) -> QueueIgnoreCpPatch | None:
        """Recognise this patch **and recover its keyword** from ``data``.

        The default probe would only ever recognise the default keyword. The keyword string sits
        at a fixed offset in the cave, right behind the flag, so it reads straight back out;
        `verify` then checks the whole cave against it."""
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
        """The one `Bool` this patch adds to `CommandButton`, under whatever keyword it was
        installed with. The constructor zeroes it, so the default is `No` - stock behaviour,
        which is what makes the field opt-in."""
        return Engine(fields=(FieldDelta("CommandButton", self.keyword, "Bool", False, self.name),))

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
        code = build_code(pieces.code_va, pieces.flag_va).finish()
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
                f"the field table at 0x{pieces.table_va:08x} is not the live rows plus a Bool at "
                f"CommandButton+0x{COMMAND_BUTTON_FREE_OFFSET:02x}"
            )
        code_off = _offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(code)]) != code:
            problems.append(f"the code at 0x{pieces.code_va:08x} is not what this patch builds")
        return problems

    def _verify_sites(
        self, data: bytes | bytearray, pieces: _Layout, live: tuple[Entry, ...]
    ) -> list[str]:
        """The four edits, and the row the engine will actually parse this field through.

        **The row is checked in the *live* table, not in this patch's own copy of it.** A patch
        applied afterwards that extends the same block - `command-point-cost` is the one that does
        - rebuilds the table again, copying this row across with every other live row, and
        repoints the three references at *its* cave. That is exactly the composition the tables are
        read live for, so demanding the references still name this cave would report a correctly
        composed binary as broken. What has to hold is that whatever table the engine reaches
        carries this keyword, pointing at this cave's string and at the parser and offset this
        patch installed."""
        code = build_code(pieces.code_va, pieces.flag_va)
        checks: list[tuple[int, bytes, str]] = [
            (
                COMMAND_BUTTON_CTOR_AUTO_ABILITY,
                rewritten_default(),
                f"the ctor does not default {self.keyword} to No",
            ),
            (
                DO_COMMAND_BUTTON_UNIT_QUEUE,
                _hook(
                    DO_COMMAND_BUTTON_UNIT_QUEUE,
                    DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES,
                    code.label_va("unit_build"),
                ),
                f"the UNIT_BUILD queue call is not wrapped by the {SECTION_NAME} cave",
            ),
            (
                DO_COMMAND_BUTTON_REVIVE_QUEUE,
                _hook(
                    DO_COMMAND_BUTTON_REVIVE_QUEUE,
                    DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES,
                    code.label_va("revive"),
                ),
                f"the REVIVE queue call is not wrapped by the {SECTION_NAME} cave",
            ),
            (
                BUILD_GATE_COMMAND_POINTS,
                _hook(
                    BUILD_GATE_COMMAND_POINTS,
                    BUILD_GATE_COMMAND_POINTS_BYTES,
                    code.label_va("gate"),
                ),
                f"the command-point verdict is not hooked to the {SECTION_NAME} gate",
            ),
        ]
        problems: list[str] = []
        for va, want, complaint in checks:
            off = _offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{va:08x}: {complaint} (holds {got.hex()})")

        want_row = (pieces.keyword_va, INI_PARSE_BOOL, 0, COMMAND_BUTTON_FREE_OFFSET)
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
    def from_cli_args(cls, args: argparse.Namespace) -> QueueIgnoreCpPatch:
        return cls(keyword=args.keyword)
