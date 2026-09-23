"""Add `QueueIgnoreCP` to `CommandButton`: an engine press of the button may queue its unit even at
the command-point cap.

`DoCommandUpgrade` presses a recruitment button on an object's behalf through the same production
gate as a click, and the cap is that gate's last refusal. With the field set, that refusal is
skipped; gold, producer, queue slot and prerequisites are still required. The control bar's own
availability test is unchanged, so a visible button still refuses a player's click at the cap.

Derivation: `../docs/queue-ignore-cp.md`.
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
from ..utils import (
    allocate_section,
    apply_byte_patch,
    file_offset,
    find_section,
    jmp_rel32,
    read_cstring,
    u32,
)
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
    """Raise unless `keyword` is a token the engine's INI reader could ever match."""
    if not _KEYWORD_PATTERN.match(keyword):
        raise ValueError(
            "an INI keyword must be letters, digits and underscores starting with a letter "
            f"(the reader matches it by exact compare), got {keyword!r}"
        )


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address, the keyword and how many rows
    the live field table turned out to have.

    Pure arithmetic on those three, so `QueueIgnoreCpPatch.apply` and
    `QueueIgnoreCpPatch.verify` compute the same addresses from opposite directions."""

    flag_va: int
    keyword_va: int
    table_va: int
    code_va: int


#: The flag is the first dword of the cave and the keyword string follows it, both at fixed
#: offsets - which is what lets `QueueIgnoreCpPatch.detect` read the keyword back out of a
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

    `mov byte [esi+0x10C], bl` becomes `mov dword [esi+0x10C], ebx`: one byte changed, six
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
    a.emit(0x0F, 0xB6, 0x80, u32(COMMAND_BUTTON_FREE_OFFSET))  # movzx eax, byte [eax+0x10D]
    a.emit(0xA3, u32(flag_va))  # mov [flag], eax


def _emit_disarm(a: Asm, flag_va: int) -> None:
    """Clear the flag. Touches no register; the flags it sets are dead at both resume addresses,
    which are unconditional jumps to the function's common exit."""
    a.emit(0x83, 0x25, u32(flag_va), 0x00)  # and dword [flag], 0


def build_code(code_va: int, flag_va: int) -> Asm:
    """The cave's three routines, laid out at the address they will occupy.

    Two wrappers around `queueCreateUnit`, which raise the flag for exactly the length of the
    call, and the gate's replacement verdict, which is the only thing that reads it. Returned as
    the `Asm` rather than as bytes so the caller can take each routine's
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
    a.emit(0x83, 0x3D, u32(flag_va), 0x00)  # cmp dword [flag], 0
    a.jcc_short(JE, "refuse")
    a.label("allow")
    a.jmp_absolute(BUILD_GATE_COMMAND_POINTS_OK)
    a.label("refuse")
    a.emit(0x6A, BUILD_GATE_NOT_ENOUGH_COMMAND_POINTS)  # push 7
    a.jmp_absolute(BUILD_GATE_COMMAND_POINTS_REFUSE)
    return a


class QueueIgnoreCpPatch(Patch):
    """Add a `QueueIgnoreCP` boolean to `CommandButton`, letting a press of that button queue
    production the command-point cap would otherwise refuse."""

    name = "queue-ignore-cp"
    author = "officialNecro"
    runtime_verified = "yes"
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
        `(file offset, expected, replacement, note)`."""
        edits: list[tuple[int, bytes, bytes, str]] = [
            (
                file_offset(data, COMMAND_BUTTON_CTOR_AUTO_ABILITY),
                COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES,
                rewritten_default(),
                f"CommandButton ctor -> {self.keyword} defaults to No",
            ),
            (
                file_offset(data, DO_COMMAND_BUTTON_UNIT_QUEUE),
                DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES,
                jmp_rel32(
                    DO_COMMAND_BUTTON_UNIT_QUEUE,
                    code.label_va("unit_build"),
                    len(DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES),
                ),
                f"doCommandButton UNIT_BUILD -> the {SECTION_NAME} queue wrapper",
            ),
            (
                file_offset(data, DO_COMMAND_BUTTON_REVIVE_QUEUE),
                DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES,
                jmp_rel32(
                    DO_COMMAND_BUTTON_REVIVE_QUEUE,
                    code.label_va("revive"),
                    len(DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES),
                ),
                f"doCommandButton REVIVE -> the {SECTION_NAME} queue wrapper",
            ),
            (
                file_offset(data, BUILD_GATE_COMMAND_POINTS),
                BUILD_GATE_COMMAND_POINTS_BYTES,
                jmp_rel32(
                    BUILD_GATE_COMMAND_POINTS,
                    code.label_va("gate"),
                    len(BUILD_GATE_COMMAND_POINTS_BYTES),
                ),
                f"the command-point verdict -> the {SECTION_NAME} gate",
            ),
        ]
        table_ref = u32(pieces.table_va)
        for ref_va, opcode in zip(
            COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = file_offset(data, ref_va)
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
        target = struct.unpack_from("<I", data, file_offset(data, slot_va))[0]
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
    def detect(cls, data: bytes | bytearray) -> QueueIgnoreCpPatch | None:
        """Recognise this patch **and recover its keyword** from `data`.

        The default probe would only ever recognise the default keyword. The keyword string sits
        at a fixed offset in the cave, right behind the flag, so it reads straight back out;
        `verify` then checks the whole cave against it."""
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
        """The one `Bool` this patch adds to `CommandButton`, under whatever keyword it was
        installed with. The constructor zeroes it, so the default is `No` - stock behaviour,
        which is what makes the field opt-in."""
        return Engine(fields=(FieldDelta("CommandButton", self.keyword, "Bool", False, self.name),))

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
        code = build_code(pieces.code_va, pieces.flag_va).finish()
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
                f"the field table at 0x{pieces.table_va:08x} is not the live rows plus a Bool at "
                f"CommandButton+0x{COMMAND_BUTTON_FREE_OFFSET:02x}"
            )
        code_off = file_offset(data, pieces.code_va)
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
                jmp_rel32(
                    DO_COMMAND_BUTTON_UNIT_QUEUE,
                    code.label_va("unit_build"),
                    len(DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES),
                ),
                f"the UNIT_BUILD queue call is not wrapped by the {SECTION_NAME} cave",
            ),
            (
                DO_COMMAND_BUTTON_REVIVE_QUEUE,
                jmp_rel32(
                    DO_COMMAND_BUTTON_REVIVE_QUEUE,
                    code.label_va("revive"),
                    len(DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES),
                ),
                f"the REVIVE queue call is not wrapped by the {SECTION_NAME} cave",
            ),
            (
                BUILD_GATE_COMMAND_POINTS,
                jmp_rel32(
                    BUILD_GATE_COMMAND_POINTS,
                    code.label_va("gate"),
                    len(BUILD_GATE_COMMAND_POINTS_BYTES),
                ),
                f"the command-point verdict is not hooked to the {SECTION_NAME} gate",
            ),
        ]
        problems: list[str] = []
        for va, want, complaint in checks:
            off = file_offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{va:08x}: {complaint} (holds {got.hex()})")

        want_row = (pieces.keyword_va, INI_PARSE_BOOL, 0, COMMAND_BUTTON_FREE_OFFSET)
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
    def from_cli_args(cls, args: argparse.Namespace) -> QueueIgnoreCpPatch:
        return cls(keyword=args.keyword)
