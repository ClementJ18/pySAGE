"""Add `HideModifierFX` to `Object`: attribute modifiers still apply to the object, but the
`FX`/`FX2`/`FX3` of their `ModifierList` are not played on it.

Meant for the invisible helper objects a mod builds mechanics out of: a leadership aura that
catches one would otherwise draw its glow on an object the player is not supposed to know exists.
The engine plays a modifier's FX in one function, `ModifierHolder::applyModifierList`, which every
modifier source goes through, so the one gate covers auras, weapon nuggets, powers and upgrades.

`ThingTemplate` has no free byte, so the field lives in a 64 KiB cave array indexed by the
template's engine-assigned 16-bit id, which INI override copies inherit. The two engine paths that
move an id between templates carry the flag with it. Logic-neutral: FX are presentation only.

Derivation: `../docs/hide-modifier-fx.md`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    FIELD_PARSE_STRIDE,
    FX_LIST_PLAY_AT_OBJECT,
    INI_PARSE_BOOL,
    MODIFIER_HOLDER_APPLY_FX_CALLS,
    OBJECT_FIELD_TABLE_REF_OPCODES,
    OBJECT_FIELD_TABLE_REFS,
    OBJECT_THING_TEMPLATE,
    THING_FACTORY_ID_SWAP,
    THING_FACTORY_ID_SWAP_BYTES,
    THING_FACTORY_ID_SWAP_RESUME,
    THING_TEMPLATE_COPY_KEEP_ID,
    THING_TEMPLATE_COPY_KEEP_ID_BYTES,
    THING_TEMPLATE_COPY_KEEP_ID_RESUME,
    THING_TEMPLATE_ID,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
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
    "ID_TABLE_SIZE",
    "SECTION_NAME",
    "HideModifierFxPatch",
    "build_code",
    "build_table",
]

SECTION_NAME = ".modfx"  # the PE name field is 8 bytes and truncates silently

#: The INI keyword the new `Object` field is parsed under.
DEFAULT_KEYWORD = "HideModifierFX"

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds
#: the id-indexed flags (**written** at INI load), the rebuilt table and the routines.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: One flag byte per possible template id: the id is a `UInt16`, so every id has a slot and no
#: bound check is needed anywhere.
ID_TABLE_SIZE = 0x10000

#: `Object` fields the live table must still carry at these offsets, or this is not the build the
#: template-id reasoning was derived against. Checked by name, so another patch having appended to
#: the same table first does not trip it.
FINGERPRINT = {"BuildCost": 0x5EA, "RefundValue": 0x5EC, "CampnessValue": 0x5E4}

# An INI keyword is matched by exact compare, so anything the parser could never match is a typo.
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
    """Where each piece of the cave sits. The id table is first and the keyword right behind it,
    both at fixed offsets, which is what lets `detect` read the keyword back out."""

    ids_va: int
    keyword_va: int
    table_va: int
    code_va: int


def _layout(base_va: int, keyword: str, rows: int) -> _Layout:
    keyword_va = base_va + ID_TABLE_SIZE
    string = len(keyword) + 1
    table_va = keyword_va + string + (-string % 4)  # keep the table's dwords aligned
    code_va = table_va + (rows + 2) * FIELD_PARSE_STRIDE  # + the new row + the terminator
    return _Layout(base_va, keyword_va, table_va, code_va)


def build_table(entries: tuple[Entry, ...], keyword_va: int, parse_va: int) -> bytes:
    """The rebuilt `Object` field table: the live rows verbatim, the new row, the terminator.

    The new row carries offset 0 and its own parse function, which ignores `store` and files the
    `Bool` against the template's id instead of inside the template."""
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", keyword_va, parse_va, 0, 0)
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


def build_code(code_va: int, ids_va: int) -> Asm:
    """The cave's four routines, laid out at the address they will occupy."""
    a = Asm(code_va)
    ids = u32(ids_va)

    # In place of both `call FX_LIST_PLAY_AT_OBJECT`: the same cdecl `(fx, object, unused)`, so
    # the caller's own `add esp, 0xC` still balances. Neither caller reads the result.
    a.label("fx_gate")
    a.emit(0x8B, 0x4C, 0x24, 0x08)  # mov ecx, [esp+8]            ; the Object
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "play")
    a.emit(0x8B, 0x49, OBJECT_THING_TEMPLATE)  # mov ecx, [ecx+4]  ; its ThingTemplate
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "play")
    a.emit(0x0F, 0xB7, 0x89, u32(THING_TEMPLATE_ID))  # movzx ecx, word [ecx+0x5E8]
    a.emit(0x80, 0xB9, ids, 0x00)  # cmp byte [ecx+ids], 0
    a.jcc_short(JNE, "hide")
    a.label("play")
    a.jmp_absolute(FX_LIST_PLAY_AT_OBJECT)
    a.label("hide")
    a.emit(0xC3)  # ret

    # The field's parse function: cdecl `(INI*, void *instance, void *store, userData)`. The
    # engine's own `Bool` parser does the token, pointed at the template's slot in the id table.
    a.label("parse")
    a.emit(0x8B, 0x44, 0x24, 0x08)  # mov eax, [esp+8]            ; the ThingTemplate
    a.emit(0x0F, 0xB7, 0x80, u32(THING_TEMPLATE_ID))  # movzx eax, word [eax+0x5E8]
    a.emit(0x05, ids)  # add eax, ids
    a.emit(0xFF, 0x74, 0x24, 0x10)  # push dword [esp+0x10]       ; userData
    a.emit(0x50)  # push eax                                        ; store
    a.emit(0xFF, 0x74, 0x24, 0x10)  # push dword [esp+0x10]       ; instance
    a.emit(0xFF, 0x74, 0x24, 0x10)  # push dword [esp+0x10]       ; ini
    a.call_absolute(INI_PARSE_BOOL)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0xC3)  # ret

    # The identity-keeping copy (ChildObject-style): the destination takes the source's flag
    # before its own id is restored, exactly as it takes every other copied field.
    a.label("keep_id")
    a.emit(0x50)  # push eax
    a.emit(0x52)  # push edx
    a.emit(0x0F, 0xB7, 0x96, u32(THING_TEMPLATE_ID))  # movzx edx, word [esi+0x5E8]  ; source id
    a.emit(0x8A, 0x82, ids)  # mov al, [edx+ids]
    a.emit(0x0F, 0xB7, 0xD3)  # movzx edx, bx                   ; own id
    a.emit(0x88, 0x82, ids)  # mov [edx+ids], al
    a.emit(0x5A)  # pop edx
    a.emit(0x58)  # pop eax
    a.emit(THING_TEMPLATE_COPY_KEEP_ID_BYTES)  # mov word [esi+0x5E8], bx
    a.jmp_absolute(THING_TEMPLATE_COPY_KEEP_ID_RESUME)

    # A redefinition replacing a registered name: the displaced template keeps its flag under its
    # fresh id, and the id the newcomer inherited starts clear for the newcomer's own fields.
    a.label("id_swap")
    a.emit(THING_FACTORY_ID_SWAP_BYTES)  # ecx = fresh id; [eax] = the old template's id
    a.emit(0x50)  # push eax
    a.emit(0x0F, 0xB7, 0xC9)  # movzx ecx, cx                   ; the old template's new id
    a.emit(0x0F, 0xB7, 0x96, u32(THING_TEMPLATE_ID))  # movzx edx, word [esi+0x5E8]  ; inherited
    a.emit(0x8A, 0x82, ids)  # mov al, [edx+ids]
    a.emit(0x88, 0x81, ids)  # mov [ecx+ids], al
    a.emit(0xC6, 0x82, ids, 0x00)  # mov byte [edx+ids], 0
    a.emit(0x58)  # pop eax
    a.jmp_absolute(THING_FACTORY_ID_SWAP_RESUME)
    return a


class HideModifierFxPatch(Patch):
    """Add a `HideModifierFX` boolean to `Object`, suppressing the FX that attribute modifiers
    play on it without touching the modifiers themselves."""

    name = "hide-modifier-fx"
    author = "officialNecro"
    description = (
        "Add a HideModifierFX boolean to Object: with Yes, attribute modifiers (leadership auras, "
        "weapon nuggets, powers, upgrades) still apply to the object, but their ModifierList "
        "FX/FX2/FX3 are not played on it - for invisible helper objects that must not glow. No, "
        "the default, is stock. Presentation only"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        self._check_sites(data)
        entries = self._check_table(data, self._resolve(data))

        base_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build(base, entries), _CHARACTERISTICS
        )
        pieces = _layout(base_va, self.keyword, len(entries))
        code = build_code(pieces.code_va, pieces.ids_va)
        for file_off, old, new, note in self._edits(data, pieces, code):
            apply_byte_patch(data, file_off, old, new, note)

    def _build(self, base_va: int, entries: tuple[Entry, ...]) -> bytes:
        """The cave: the id table (zero - nothing hidden), the keyword, the table, the code."""
        pieces = _layout(base_va, self.keyword, len(entries))
        code = build_code(pieces.code_va, pieces.ids_va)
        blob = bytearray(ID_TABLE_SIZE)
        blob += self.keyword.encode("ascii") + b"\x00"
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(entries, pieces.keyword_va, code.label_va("parse"))
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        return bytes(blob) + code.finish()

    @staticmethod
    def _hooks(code: Asm) -> list[tuple[int, bytes, bytes, str]]:
        """The four code edits as `(VA, stock bytes, replacement, note)`."""
        hooks = [
            (
                site,
                call_rel32(site, FX_LIST_PLAY_AT_OBJECT),
                call_rel32(site, code.label_va("fx_gate")),
                f"applyModifierList FX play 0x{site:08x} -> the {SECTION_NAME} gate",
            )
            for site in MODIFIER_HOLDER_APPLY_FX_CALLS
        ]
        hooks += [
            (
                THING_TEMPLATE_COPY_KEEP_ID,
                THING_TEMPLATE_COPY_KEEP_ID_BYTES,
                jmp_rel32(
                    THING_TEMPLATE_COPY_KEEP_ID,
                    code.label_va("keep_id"),
                    len(THING_TEMPLATE_COPY_KEEP_ID_BYTES),
                ),
                "identity-keeping template copy -> carry the flag",
            ),
            (
                THING_FACTORY_ID_SWAP,
                THING_FACTORY_ID_SWAP_BYTES,
                jmp_rel32(
                    THING_FACTORY_ID_SWAP,
                    code.label_va("id_swap"),
                    len(THING_FACTORY_ID_SWAP_BYTES),
                ),
                "addTemplate id swap -> carry the flag",
            ),
        ]
        return hooks

    def _edits(
        self, data: bytes | bytearray, pieces: _Layout, code: Asm
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte this patch writes outside its own cave, as
        `(file offset, expected, replacement, note)`."""
        edits = [
            (file_offset(data, va), old, new, note) for va, old, new, note in self._hooks(code)
        ]
        table_ref = u32(pieces.table_va)
        for ref_va, opcode in zip(
            OBJECT_FIELD_TABLE_REFS, OBJECT_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = file_offset(data, ref_va)
            edits.append(
                (
                    off,
                    bytes(data[off : off + 5]),
                    bytes([opcode]) + table_ref,
                    f"Object field table reference 0x{ref_va:08x} -> {SECTION_NAME}",
                )
            )
        return edits

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """The `Object` field table's base VA, as the image currently holds it - so the patch
        appends to whatever is live, and applying it twice fails cleanly."""
        return resolve_table(
            data, OBJECT_FIELD_TABLE_REFS, OBJECT_FIELD_TABLE_REF_OPCODES, "Object"
        )

    @staticmethod
    def _check_sites(data: bytes | bytearray) -> None:
        """Raise unless all four hooked windows hold the stock bytes."""
        for va, old, _new, _note in HideModifierFxPatch._hooks(build_code(0, 0)):
            off = file_offset(data, va)
            got = bytes(data[off : off + len(old)])
            if got != old:
                raise ValueError(
                    f"@0x{va:08x}: expected {old.hex()}, got {got.hex()} - the file is not the "
                    "expected build, or already carries this patch"
                )

    def _check_table(self, data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        """The live rows, once the table has been checked for the build and for this keyword."""
        entries = read_field_table(data, table_va)
        by_name = {read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, want in FINGERPRINT.items():
            got = by_name.get(field)
            if got != want:
                raise ValueError(
                    f"unexpected build: Object.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        if self.keyword in by_name:
            raise ValueError(
                f"Object already has a {self.keyword!r} field - this patch is already applied, "
                "or another patch has added the same field"
            )
        return entries

    @classmethod
    def detect(cls, data: bytes | bytearray) -> HideModifierFxPatch | None:
        """Recognise this patch and recover its keyword, which sits right behind the id table."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = read_cstring(data, located[0] + ID_TABLE_SIZE)
        if keyword is None:
            return None
        try:
            patch = cls(keyword)
        except ValueError:
            return None
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one `Bool` this patch adds to `Object`. The id table starts zeroed, so the default
        is `No` - stock behaviour."""
        return Engine(fields=(FieldDelta("Object", self.keyword, "Bool", False, self.name),))

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch for exactly this keyword, with every
        address recovered from where the cave actually landed."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located

        try:
            rebuilt = read_field_table(data, self._resolve(data))
            preceding = entries_before(data, rebuilt, self.keyword)
            if preceding is None:
                return [f"the live Object table does not name {self.keyword!r}"]
            pieces = _layout(section_va, self.keyword, len(preceding))
            code = build_code(pieces.code_va, pieces.ids_va)
            problems = self._verify_cave(data, pieces, code, preceding, section_va, vsize)
            problems += self._verify_sites(data, pieces, code, rebuilt)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the patch (wrong build?): {exc}"]
        return problems

    def _verify_cave(
        self,
        data: bytes | bytearray,
        pieces: _Layout,
        code: Asm,
        preceding: tuple[Entry, ...],
        section_va: int,
        vsize: int,
    ) -> list[str]:
        body = code.finish()
        if pieces.code_va + len(body) > section_va + vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for the table and the code"]
        problems: list[str] = []
        got_keyword = read_cstring(data, pieces.keyword_va)
        if got_keyword != self.keyword:
            problems.append(
                f"the keyword in {SECTION_NAME} is {got_keyword!r}, not {self.keyword!r}"
            )
        want_table = build_table(preceding, pieces.keyword_va, code.label_va("parse"))
        table_off = file_offset(data, pieces.table_va)
        if bytes(data[table_off : table_off + len(want_table)]) != want_table:
            problems.append(
                f"the field table at 0x{pieces.table_va:08x} is not the live rows plus "
                f"{self.keyword}"
            )
        code_off = file_offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(body)]) != body:
            problems.append(f"the code at 0x{pieces.code_va:08x} is not what this patch builds")
        return problems

    def _verify_sites(
        self, data: bytes | bytearray, pieces: _Layout, code: Asm, live: tuple[Entry, ...]
    ) -> list[str]:
        """The four hooks, and the row in whatever table the engine now reaches - a later patch
        extending `Object` again copies this row into its own cave, which is correct composition."""
        problems: list[str] = []
        for va, _old, want, note in self._hooks(code):
            off = file_offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{va:08x}: {note} is not installed (holds {got.hex()})")
        want_row = (pieces.keyword_va, code.label_va("parse"), 0, 0)
        row = next((e for e in live if read_cstring(data, e[0]) == self.keyword), None)
        if row != want_row:
            problems.append(
                f"the live Object table's {self.keyword!r} row is "
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
                f"name of the INI field to add to Object (default {DEFAULT_KEYWORD}); letters, "
                "digits and underscores, and must not already be an Object field"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> HideModifierFxPatch:
        return cls(keyword=args.keyword)
