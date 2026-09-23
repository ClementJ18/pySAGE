"""Add `FireAtAttacker` to `FireWeaponWhenDamagedBehavior`: the reaction weapon fires at whatever
dealt the damage.

The stock reaction weapon fires at the damaged unit's own position. With the flag set, the weapon
fires through the engine's object-targeted `createAndFireTempWeapon` overload (`0x006CF3AE`) at the
damage source, falling back to stock when there is none. Kill credit and XP are unchanged. The
`Continuous*` weapons fire from `update`, where no attacker is in scope, so their call
(`0x00885E1A`) is left stock. Not runtime-verified.

Derivation: `../docs/fire-at-attacker.md`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION,
    CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION_ENTRY,
    CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM,
    CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM_ENTRY,
    DAMAGE_INFO_SOURCE_ID,
    FIELD_PARSE_STRIDE,
    FIRE_WEAPON_WHEN_DAMAGED_ON_DAMAGE,
    FWWD_FIELD_TABLE_REF_OPCODES,
    FWWD_FIELD_TABLE_REFS,
    FWWD_IFACE_MODULE_DATA_DISP,
    FWWD_MODULEDATA_CTOR,
    FWWD_MODULEDATA_CTOR_CALL,
    FWWD_MODULEDATA_CTOR_CALL_BYTES,
    FWWD_MODULEDATA_SIZE,
    FWWD_MODULEDATA_SIZE_BYTES,
    FWWD_MODULEDATA_SIZE_VA,
    FWWD_REACTION_AIM,
    FWWD_REACTION_AIM_BYTES,
    FWWD_REACTION_FIRE_CALL,
    FWWD_REACTION_FIRE_RESUME,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    INI_PARSE_BOOL,
    THE_GAME_LOGIC,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    i8,
    jmp_rel32,
    read_cstring,
    u32,
)
from .utils.field_tables import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "DEFAULT_KEYWORD",
    "FINGERPRINT",
    "FLAG_OFFSET",
    "GROWN_MODULEDATA_SIZE",
    "SECTION_NAME",
    "FireAtAttackerPatch",
    "build_code",
    "build_table",
    "grown_size_bytes",
    "validate_keyword",
]

SECTION_NAME = ".faa"  # the PE name field is 8 bytes and truncates silently

#: The INI keyword the new `FireWeaponWhenDamagedBehavior` field is parsed under.
DEFAULT_KEYWORD = "FireAtAttacker"

#: Where the new field lives in the `ModuleData` - **exactly** the stock `sizeof`, because the
#: block is grown by four bytes to make room and the stock fields end flush against it. Spelling
#: it as the stock size rather than as a literal is what ties the two together: if one moves and
#: the other does not, `_check_table` fails rather than the field landing on a live field.
FLAG_OFFSET = FWWD_MODULEDATA_SIZE

#: What `newModuleData` allocates once the field is added. Four bytes, not one, so the block stays
#: dword-aligned and the shim can zero the field with a single store.
GROWN_MODULEDATA_SIZE = FWWD_MODULEDATA_SIZE + 4

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave holds the keyword
#: string and the rebuilt table (read) and the two routines (executed); nothing in it is written.
SECTION_CHARACTERISTICS = 0x60000060

#: Fields the live table must still carry at these offsets, or this is not the build the layout
#: above was derived against. Checked by name rather than by count, so it survives another patch
#: having appended to the same table first.
FINGERPRINT = {
    "StartsActive": 0x138,
    "DamageTypes": 0x13C,
    "DamageAmount": 0x140,
    "ReactionWeaponPristine": 0x144,
    "ContinuousWeaponRubble": 0x160,
}

#: Byte windows the patch depends on and does **not** rewrite. The register anchors matter most:
#: the cave reads `esi` as `onDamage`'s damage-interface sub-object and `edi` as the owning
#: `Object`, and nothing the patch writes would catch a mismatch - the cave would simply
#: dereference whatever the registers held.
ANCHORS: dict[int, bytes] = {
    # `onDamage`'s prologue: `mov esi, ecx` establishes the interface sub-object the cave later
    # reaches the `ModuleData` through.
    FIRE_WEAPON_WHEN_DAMAGED_ON_DAMAGE: bytes.fromhex("568bf18d4ef88b01ff10"),
    # the stock `mov eax, [esi-0x24]` the cave's own first instruction reproduces - this is what
    # pins `FWWD_IFACE_MODULE_DATA_DISP` to the register the cave will read it from
    0x00885CEE: bytes.fromhex("8b46dc"),
    # the positional call the `No` path still returns to, and the epilogue the `Yes` path lands
    # on having made the call itself
    FWWD_REACTION_FIRE_CALL: bytes.fromhex("e84796e4ff"),
    FWWD_REACTION_FIRE_RESUME: bytes.fromhex("5f5ec20400"),
    # the two overloads, so a build that laid them out differently fails before applying
    CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM: CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM_ENTRY,
    CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION: CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION_ENTRY,
    GAME_LOGIC_FIND_OBJECT_BY_ID: GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    # the `ModuleData` constructor the shim calls: `__thiscall`, `mov esi, ecx`, base ctor, and
    # the vtable store that makes it this class's
    FWWD_MODULEDATA_CTOR: bytes.fromhex("568bf18d4e08c706307ac000"),
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

    Pure arithmetic on those three, so `FireAtAttackerPatch.apply` and
    `FireAtAttackerPatch.verify` compute the same addresses from opposite directions."""

    keyword_va: int
    table_va: int
    code_va: int


def _layout(base_va: int, keyword: str, rows: int) -> _Layout:
    """The cave's three pieces. The keyword string is **first**, at the section base, which is
    what lets `FireAtAttackerPatch.detect` read it back out of a binary it knows nothing
    else about."""
    string = len(keyword) + 1
    table_va = base_va + string + (-string % 4)  # keep the table's dwords aligned
    code_va = table_va + (rows + 2) * FIELD_PARSE_STRIDE  # + the new row + the terminator
    return _Layout(base_va, table_va, code_va)


def grown_size_bytes() -> bytes:
    """`newModuleData`'s allocation, widened by the four bytes the new field needs.

    `push 0x164` becomes `push 0x168`: a bare `imm32`, so five bytes for five and no hook."""
    new = FWWD_MODULEDATA_SIZE_BYTES[:1] + u32(GROWN_MODULEDATA_SIZE)
    assert len(new) == len(FWWD_MODULEDATA_SIZE_BYTES)
    return new


def build_table(entries: tuple[Entry, ...], keyword_va: int) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the new `Bool`, the terminator.

    The live rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are - and only the new row points into the cave."""
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", keyword_va, INI_PARSE_BOOL, 0, FLAG_OFFSET)
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


def build_code(code_va: int) -> Asm:
    """The cave's two routines, laid out at the address they will occupy.

    Returned as the `Asm` rather than as bytes so the caller can take each
    routine's address from the same layout that produced them."""
    a = Asm(code_va)

    # The `ModuleData` constructor shim. The stock constructor is `__thiscall` with no arguments
    # and returns `this` in `eax`, so the shim needs no frame of its own and stays transparent to
    # `newModuleData`, which goes on to test `eax` for NULL exactly as it did before.
    a.label("ctor")
    a.call_absolute(FWWD_MODULEDATA_CTOR)
    a.emit(0xC7, 0x80, u32(FLAG_OFFSET), u32(0))  # mov dword [eax+0x164], 0
    a.emit(0xC3)  # ret

    # The aim. Entered by `jmp` from the one block every body-state arm converges on, so the stack
    # is `onDamage`'s: [esp] = saved edi, +4 = saved esi, +8 = return address, +0xc = the
    # `DamageInfo`. `ecx` holds the chosen `WeaponTemplate` and must survive; `edi` is the owning
    # `Object`; `esi` is the damage-interface sub-object.
    a.label("aim")
    a.emit(0x8B, 0x46, i8(FWWD_IFACE_MODULE_DATA_DISP))  # mov eax, [esi-0x24]  ; ModuleData
    a.emit(0x80, 0xB8, u32(FLAG_OFFSET), 0x00)  # cmp byte [eax+0x164], 0
    a.jcc_short(JE, "at_self")  # FireAtAttacker = No: stock behaviour
    a.emit(0x51)  # push ecx                      ; the WeaponTemplate, over the lookup
    a.emit(0x8B, 0x44, 0x24, 0x10)  # mov eax, [esp+0x10]   ; the DamageInfo
    a.emit(0xFF, 0x70, DAMAGE_INFO_SOURCE_ID)  # push dword [eax+8]  ; whatever dealt the damage
    a.emit(0x8B, 0x0D, u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(GAME_LOGIC_FIND_OBJECT_BY_ID)  # ret 4 -> eax = the attacker, or NULL
    a.emit(0x59)  # pop ecx                       ; the WeaponTemplate again (pop sets no flags)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "at_self")  # no source object, or it is already gone
    a.emit(0x50)  # push eax                      ; victim = the attacker
    a.emit(0x57)  # push edi                      ; source = the reflecting object, as before
    a.call_absolute(CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM)  # ret 8
    a.jmp_absolute(FWWD_REACTION_FIRE_RESUME)  # past the stock call, into the epilogue

    a.label("at_self")
    a.emit(FWWD_REACTION_AIM_BYTES)  # lea eax,[edi+0x38] / push eax / push edi
    a.jmp_absolute(FWWD_REACTION_FIRE_CALL)
    return a


class FireAtAttackerPatch(Patch):
    """Add a `FireAtAttacker` boolean to `FireWeaponWhenDamagedBehavior`, so its reaction weapon
    hits whatever dealt the damage instead of going off at the damaged object's own feet."""

    name = "fire-at-attacker"
    author = "officialNecro"
    description = (
        "Add a FireAtAttacker boolean to FireWeaponWhenDamagedBehavior, so its ReactionWeapon* "
        "fires at whatever dealt the damage rather than at the damaged object's own position - "
        "which is what lets a level-gated reflect hit one attacker instead of splashing a Radius "
        "over everything nearby. Write FireAtAttacker = Yes on the behavior; No, the default, is "
        "stock, and damage with no resolvable source still fires at self"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        table_va = self._resolve(data)
        entries = self._check_table(data, table_va)

        base_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build(base, entries), SECTION_CHARACTERISTICS
        )
        pieces = _layout(base_va, self.keyword, len(entries))
        code = build_code(pieces.code_va)

        for file_off, old, new, note in self._edits(data, pieces, code):
            apply_byte_patch(data, file_off, old, new, note)

    def _build(self, base_va: int, entries: tuple[Entry, ...]) -> bytes:
        """The cave: the keyword string, the rebuilt table, the code."""
        pieces = _layout(base_va, self.keyword, len(entries))
        blob = bytearray(self.keyword.encode("ascii") + b"\x00")
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(entries, pieces.keyword_va)
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        return bytes(blob) + build_code(pieces.code_va).finish()

    def _edits(
        self, data: bytes | bytearray, pieces: _Layout, code: Asm
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte this patch writes outside its own cave, as
        `(file offset, expected, replacement, note)`."""
        edits: list[tuple[int, bytes, bytes, str]] = [
            (
                file_offset(data, FWWD_MODULEDATA_SIZE_VA),
                FWWD_MODULEDATA_SIZE_BYTES,
                grown_size_bytes(),
                f"FireWeaponWhenDamagedBehavior ModuleData -> 0x{GROWN_MODULEDATA_SIZE:x} bytes",
            ),
            (
                file_offset(data, FWWD_MODULEDATA_CTOR_CALL),
                FWWD_MODULEDATA_CTOR_CALL_BYTES,
                call_rel32(FWWD_MODULEDATA_CTOR_CALL, code.label_va("ctor")),
                f"ModuleData ctor -> the shim defaulting {self.keyword} to No",
            ),
            (
                file_offset(data, FWWD_REACTION_AIM),
                FWWD_REACTION_AIM_BYTES,
                jmp_rel32(FWWD_REACTION_AIM, code.label_va("aim"), len(FWWD_REACTION_AIM_BYTES)),
                f"the reaction weapon's aim -> the {SECTION_NAME} cave",
            ),
        ]
        table_ref = u32(pieces.table_va)
        for ref_va, opcode in zip(FWWD_FIELD_TABLE_REFS, FWWD_FIELD_TABLE_REF_OPCODES, strict=True):
            off = file_offset(data, ref_va)
            edits.append(
                (
                    off,
                    bytes(data[off : off + 5]),
                    bytes([opcode]) + table_ref,
                    f"FireWeaponWhenDamagedBehavior field table reference "
                    f"0x{ref_va:08x} -> {SECTION_NAME}",
                )
            )
        return edits

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """The `FireWeaponWhenDamagedBehavior` field table's base VA, as the image currently holds
        it.

        Read from the reference that names it rather than from the stock constant, so the patch
        appends to whatever is live - and so applying it twice fails cleanly instead of installing
        a second copy of the field."""
        return resolve_table(
            data,
            FWWD_FIELD_TABLE_REFS,
            FWWD_FIELD_TABLE_REF_OPCODES,
            "FireWeaponWhenDamagedBehavior",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Raise unless every window this patch reads but does not write still says what the
        derivation says it does."""
        for va, want in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} holds {got.hex()}, expected {want.hex()}"
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
                    f"unexpected build: FireWeaponWhenDamagedBehavior.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        if self.keyword in by_name:
            raise ValueError(
                f"FireWeaponWhenDamagedBehavior already has a {self.keyword!r} field - this patch "
                "is already applied, or another patch has added the same field"
            )
        # The grown block is only free if the stock fields really do end flush against the stock
        # size. A dword field at 0x160 ending at 0x164 is the whole reason 0x164 is safe to take.
        end = max(offset for _name, _fn, _ud, offset in entries) + 4
        if end != FLAG_OFFSET:
            raise ValueError(
                f"unexpected build: FireWeaponWhenDamagedBehavior's fields end at {end:#x}, not at "
                f"the {FLAG_OFFSET:#x} the new field is placed at"
            )
        return entries

    @classmethod
    def detect(cls, data: bytes | bytearray) -> FireAtAttackerPatch | None:
        """Recognise this patch **and recover its keyword** from `data`.

        The default probe would only ever recognise the default keyword. The keyword string sits
        at the base of the cave, so it reads straight back out; `verify` then checks the whole
        cave against it."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = read_cstring(data, located[0])
        if keyword is None:
            return None
        try:
            patch = cls(keyword)
        except ValueError:
            return None  # not a keyword this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one `Bool` this patch adds to `FireWeaponWhenDamagedBehavior`, under whatever
        keyword it was installed with. The constructor shim zeroes it, so the default is `No` -
        stock behaviour, which is what makes the field opt-in."""
        return Engine(
            fields=(
                FieldDelta("FireWeaponWhenDamagedBehavior", self.keyword, "Bool", False, self.name),
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Return the structural problems that mean `data` does not carry this patch for exactly
        this keyword. Reads only via `struct` and the section table, so it needs no disassembler.

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
                return [
                    f"the live FireWeaponWhenDamagedBehavior table does not name {self.keyword!r}"
                ]
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
        code = build_code(pieces.code_va).finish()
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
                f"FireWeaponWhenDamagedBehavior ModuleData+0x{FLAG_OFFSET:x}"
            )
        code_off = file_offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(code)]) != code:
            problems.append(f"the code at 0x{pieces.code_va:08x} is not what this patch builds")
        return problems

    def _verify_sites(
        self, data: bytes | bytearray, pieces: _Layout, live: tuple[Entry, ...]
    ) -> list[str]:
        """The three edits, and the row the engine will actually parse this field through.

        **The row is checked in the *live* table, not in this patch's own copy of it.** A patch
        applied afterwards that extends the same module would rebuild the table again, copying
        this row across with every other live row, and repoint the reference at *its* cave. That
        is exactly the composition the tables are read live for, so demanding the reference still
        name this cave would report a correctly composed binary as broken. What has to hold is
        that whatever table the engine reaches carries this keyword, pointing at this cave's
        string and at the parser and offset this patch installed."""
        code = build_code(pieces.code_va)
        checks: list[tuple[int, bytes, str]] = [
            (
                FWWD_MODULEDATA_SIZE_VA,
                grown_size_bytes(),
                f"the ModuleData allocation is not grown to 0x{GROWN_MODULEDATA_SIZE:x}",
            ),
            (
                FWWD_MODULEDATA_CTOR_CALL,
                call_rel32(FWWD_MODULEDATA_CTOR_CALL, code.label_va("ctor")),
                f"the ctor does not default {self.keyword} to No",
            ),
            (
                FWWD_REACTION_AIM,
                jmp_rel32(FWWD_REACTION_AIM, code.label_va("aim"), len(FWWD_REACTION_AIM_BYTES)),
                f"the reaction weapon's aim is not hooked to the {SECTION_NAME} cave",
            ),
        ]
        problems: list[str] = []
        for va, want, complaint in checks:
            off = file_offset(data, va)
            if bytes(data[off : off + len(want)]) != want:
                problems.append(complaint)

        row = next(
            (entry for entry in live if read_cstring(data, entry[0]) == self.keyword),
            None,
        )
        if row is None:
            problems.append(f"the live table does not carry a {self.keyword!r} row")
        elif (row[0], row[1], row[3]) != (pieces.keyword_va, INI_PARSE_BOOL, FLAG_OFFSET):
            problems.append(
                f"the live {self.keyword!r} row is not this patch's Bool at "
                f"ModuleData+0x{FLAG_OFFSET:x}"
            )
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            help=(
                "the INI keyword the new FireWeaponWhenDamagedBehavior boolean is parsed under "
                f"(default: {DEFAULT_KEYWORD})"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> FireAtAttackerPatch:
        return cls(args.keyword)
