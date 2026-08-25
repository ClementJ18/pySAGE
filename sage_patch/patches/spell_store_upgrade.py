"""Select the spell-store CommandSet from a player's completed upgrades.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The hook and layouts are
derived in ``../docs/spell-store-upgrade.md``.

The stock engine picks one `PurchaseScienceCommandSet` through the shared routine at
``0x0071F933``. Retargeting that routine would change every caller, so this patch redirects only
the five-byte call at ``0x00822ACF`` inside `AptSpellStore::initializeSpellSlots`.

Mappings are declared on any `PlayerTemplate`; upgrade names are global, so the table itself does
not need the transient `PlayerTemplate *` seen by an INI field callback::

    PurchaseScienceCommandSetUpgrade = Upgrade_SubFactionA SpellStore_SubFactionA

The keyword may repeat. A later declaration of the same upgrade replaces its CommandSet in place;
otherwise declaration order is priority when several mapped upgrades are complete. Names, not
numeric upgrade ids, are retained in the cave. The selector resolves each name after all INI files
have loaded, validates `UpgradeTemplate::upgradeIndex`, and tests exactly that bit in the current
player's completed-upgrade mask.

The fixed table has :data:`MAPPINGS` rows. A full table consumes later lines but drops them, so a
large mod degrades to the mappings that fit rather than writing past the section. Unknown upgrades
and CommandSets are skipped at use time and stock selection remains the final fallback.

Composition is order-independent for section allocation and for the `PlayerTemplate` field table:
the live table is resolved through its instruction reference, copied with every field another
patch already appended, and repointed once. The spell-store call site is not edited by another
bundled patch.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    COMMAND_SET_STORE_FIND_COMMAND_SET,
    COMMAND_SET_STORE_GET_PURCHASE_SCIENCE_COMMAND_SET,
    PLAYER_COMPLETED_UPGRADE_MASK,
    PLAYER_COMPLETED_UPGRADE_MASK_WORDS,
    PLAYER_PLAYER_TEMPLATE,
    PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
    PLAYER_TEMPLATE_FIELD_TABLE_REFS,
    PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET,
    PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET_MP,
    SPELL_STORE_COMMAND_SET_CALL,
    SPELL_STORE_COMMAND_SET_CALL_BYTES,
    THE_UPGRADE_CENTER,
    UPGRADE_TEMPLATE_INDEX,
)
from ..asm import JAE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import ROW_SIZE, Entry, entries_before, read_field_table, resolve_table
from .utils.name_tables import read_cstring
from .utils.token_lists import (
    ASCII_STRING_ASSIGN,
    ASCII_STRING_DTOR,
    ASCII_STRING_IS_EMPTY,
    INI_NEXT_ASCII_STRING,
)

__all__ = [
    "FIELD_NAME",
    "MAPPING_STRIDE",
    "MAPPINGS",
    "SECTION_NAME",
    "SpellStoreUpgradePatch",
]

SECTION_NAME = ".ssupgr"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The section contains the
# selector and parser, the rebuilt read-only field table, and mapping strings assigned at INI load.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

FIELD_NAME = "PurchaseScienceCommandSetUpgrade"

# Each row is `{ AsciiString upgrade; AsciiString commandSet; }`. Both are one pointer into the
# engine's ref-counted buffer, so assignment and replacement need no patch-owned allocator.
MAPPINGS = 128
MAPPING_STRIDE = 8

_COUNT_OFF = 0x00
_MAPPINGS_OFF = 0x10
_TABLE_OFF = _MAPPINGS_OFF + MAPPINGS * MAPPING_STRIDE

_UPGRADE_MASK_BITS = PLAYER_COMPLETED_UPGRADE_MASK_WORDS * 32

# These names and offsets are read out of the live field table before a byte is written. They pin
# both stock fallback fields and the structure layout on which the hook depends.
_FINGERPRINT = {
    "PurchaseScienceCommandSet": PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET,
    "PurchaseScienceCommandSetMP": PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET_MP,
    "MultiSelectionPortrait": 0x1D8,
}

# `UpgradeCenter::findUpgrade(const AsciiString *)`, thiscall/ret 4, NULL for an unknown name.
_FIND_UPGRADE = 0x0066F5E5

# `AsciiString::compare(const AsciiString *)`, thiscall/ret 4, zero when equal.
_ASCII_STRING_COMPARE = 0x004065AA


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _call(at_va: int, target_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", target_va - (at_va + 5))


def _table_span(entries: tuple[Entry, ...]) -> int:
    table_size = (len(entries) + 2) * ROW_SIZE
    string_size = len(FIELD_NAME) + 1
    return table_size + string_size + (-string_size % 4)


def _table_bytes(table_va: int, entries: tuple[Entry, ...], parse_va: int) -> bytes:
    """The live rows, the new row, a terminator, and the new row's name."""
    table_size = (len(entries) + 2) * ROW_SIZE
    name_va = table_va + table_size
    out = bytearray()
    for entry in entries:
        out += struct.pack("<4I", *entry)
    # Offset zero is intentional: the parser owns external storage and never dereferences `store`.
    out += struct.pack("<4I", name_va, parse_va, 0, 0)
    out += bytes(ROW_SIZE)
    out += FIELD_NAME.encode("ascii") + b"\x00"
    out += b"\x00" * (-len(out) % 4)
    assert len(out) == _table_span(entries)
    return bytes(out)


def _emit_parse(a: Asm, count_va: int, mappings_va: int) -> None:
    """Parse one ``Upgrade CommandSet`` pair into the external mapping table.

    Field callbacks are cdecl ``(INI *, void *instance, void *store, const void *userData)``.
    `instance` is a transient `PlayerTemplate` during two of the three parse paths, so this routine
    deliberately ignores both template arguments. Upgrade names are global and sufficient keys.
    """
    a.label("parse")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x08")  # sub esp, 8             ; two AsciiString locals
    a.emit(0x53, 0x56, 0x57)  # push ebx / push esi / push edi
    a.emit(b"\x83\x65\xfc\x00")  # and dword [ebp-4], 0   ; upgrade name
    a.emit(b"\x83\x65\xf8\x00")  # and dword [ebp-8], 0   ; CommandSet name

    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]       ; INI
    a.call_absolute(INI_NEXT_ASCII_STRING)
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_IS_EMPTY)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "parse_done")

    a.emit(b"\x8d\x45\xf8")  # lea eax, [ebp-8]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]
    a.call_absolute(INI_NEXT_ASCII_STRING)
    a.emit(b"\x8d\x4d\xf8")  # lea ecx, [ebp-8]
    a.call_absolute(ASCII_STRING_IS_EMPTY)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "parse_done")

    # Find an existing row with the same upgrade name. Re-declaration changes the CommandSet but
    # keeps priority, which gives map.ini a deterministic last-value-wins override.
    a.emit(b"\x8b\x35", _u32(count_va))  # mov esi, [count]
    a.emit(b"\x31\xdb")  # xor ebx, ebx           ; row index
    a.label("parse_find")
    a.emit(b"\x3b\xde")  # cmp ebx, esi
    a.jcc(JAE, "parse_add")
    a.emit(b"\x8d\x3c\xdd", _u32(mappings_va))  # lea edi, [mappings+ebx*8]
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\xcf")  # mov ecx, edi
    a.call_absolute(_ASCII_STRING_COMPARE)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "parse_store")
    a.emit(0x43)  # inc ebx
    a.jmp("parse_find")

    a.label("parse_add")
    a.emit(b"\x81\xfe", _u32(MAPPINGS))  # cmp esi, MAPPINGS
    a.jcc(JAE, "parse_done")
    a.emit(b"\x8b\xde")  # mov ebx, esi
    a.emit(b"\x8d\x3c\xdd", _u32(mappings_va))  # lea edi, [mappings+ebx*8]

    a.label("parse_store")
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\xcf")  # mov ecx, edi
    a.call_absolute(ASCII_STRING_ASSIGN)
    a.emit(b"\x8d\x45\xf8")  # lea eax, [ebp-8]
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x4f\x04")  # lea ecx, [edi+4]
    a.call_absolute(ASCII_STRING_ASSIGN)
    a.emit(b"\x3b\xde")  # cmp ebx, esi
    a.jcc(JNE, "parse_done")  # an existing row does not grow the table
    a.emit(0x46)  # inc esi
    a.emit(b"\x89\x35", _u32(count_va))  # mov [count], esi

    a.label("parse_done")
    a.emit(b"\x8d\x4d\xf8")  # lea ecx, [ebp-8]
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / pop esi / pop ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret                    ; cdecl, dispatcher cleans


def _emit_selector(a: Asm, count_va: int, mappings_va: int) -> None:
    """The replacement for the one purchase-science CommandSet call.

    Entry and exit match the stock thiscall exactly: `ecx` is the store receiver, `[esp+4]` is
    `Player *`, `eax` is `CommandSet *`, and success removes the one argument with `ret 4`.
    Failure unwinds our frame and tail-calls the untouched stock function.
    """
    a.label("selector")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx / push esi / push edi
    a.emit(b"\x8b\xd9")  # mov ebx, ecx           ; preserve the store receiver
    a.emit(b"\x8b\x75\x08")  # mov esi, [ebp+8]       ; Player
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "selector_fallback")
    a.emit(b"\x8b\x46", bytes([PLAYER_PLAYER_TEMPLATE]))  # mov eax, [esi+0x34]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "selector_fallback")
    a.emit(b"\x31\xff")  # xor edi, edi           ; mapping index

    a.label("selector_next")
    a.emit(b"\x3b\x3d", _u32(count_va))  # cmp edi, [count]
    a.jcc(JAE, "selector_fallback")
    a.emit(b"\x8b\x0d", _u32(THE_UPGRADE_CENTER))  # mov ecx, [TheUpgradeCenter]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "selector_fallback")
    a.emit(b"\x8d\x04\xfd", _u32(mappings_va))  # lea eax, [mappings+edi*8]
    a.emit(0x50)  # push eax                 ; &row->upgrade
    a.call_absolute(_FIND_UPGRADE)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "selector_advance")
    a.emit(b"\x8b\x40", bytes([UPGRADE_TEMPLATE_INDEX]))  # mov eax, [eax+0x38]
    a.emit(b"\x3d", _u32(_UPGRADE_MASK_BITS))  # cmp eax, 36*32
    a.jcc(JAE, "selector_advance")
    a.emit(b"\x8b\xd0")  # mov edx, eax
    a.emit(b"\xc1\xe8\x05")  # shr eax, 5             ; mask word
    a.emit(b"\x83\xe2\x1f")  # and edx, 31            ; bit in word
    a.emit(
        b"\x0f\xa3\x94\x86", _u32(PLAYER_COMPLETED_UPGRADE_MASK)
    )  # bt dword [esi+eax*4+0x14c], edx
    a.jcc(JAE, "selector_advance")  # jnc
    a.emit(b"\x8d\x04\xfd", _u32(mappings_va + 4))  # lea eax, [row->commandSet]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\xcb")  # mov ecx, ebx
    a.call_absolute(COMMAND_SET_STORE_FIND_COMMAND_SET)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "selector_success")

    a.label("selector_advance")
    a.emit(0x47)  # inc edi
    a.jmp("selector_next")

    a.label("selector_success")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / pop esi / pop ebx
    a.emit(0xC9)  # leave
    a.emit(b"\xc2\x04\x00")  # ret 4

    a.label("selector_fallback")
    a.emit(b"\x8b\xcb")  # mov ecx, ebx           ; original receiver
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / pop esi / pop ebx
    a.emit(0xC9)  # leave
    a.jmp_absolute(COMMAND_SET_STORE_GET_PURCHASE_SCIENCE_COMMAND_SET)


class SpellStoreUpgradePatch(Patch):
    """Install the INI mapping table and the spell-store-only selector."""

    name = "spell-store-upgrade"
    author = "Ostkannit"
    experimental = False
    description = (
        "Select the SpellStore CommandSet from the current player's completed upgrades through "
        "repeatable PlayerTemplate PurchaseScienceCommandSetUpgrade = Upgrade CommandSet pairs; "
        "the first active mapping wins and stock PurchaseScienceCommandSet selection is fallback"
    )

    def apply(self, data: bytearray) -> None:
        table_va = self._resolve(data)
        entries = self._check_build(data, table_va)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build_section(base, entries), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va, entries, table_va):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        return resolve_table(
            data,
            PLAYER_TEMPLATE_FIELD_TABLE_REFS,
            PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
            "PlayerTemplate",
        )

    @staticmethod
    def _check_build(data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        entries = read_field_table(data, table_va)
        by_name = {read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, expected in _FINGERPRINT.items():
            actual = by_name.get(field)
            if actual != expected:
                got = "absent" if actual is None else f"{actual:#x}"
                raise ValueError(
                    f"unexpected build: PlayerTemplate.{field} is at {got}, expected {expected:#x}"
                )
        if FIELD_NAME in by_name:
            raise ValueError(
                f"the PlayerTemplate table already names {FIELD_NAME} - this patch is already "
                "applied, or another patch has added the same field"
            )
        return entries

    @staticmethod
    def _code_offset(entries: tuple[Entry, ...]) -> int:
        return _TABLE_OFF + _table_span(entries)

    def _assemble(self, base_va: int, entries: tuple[Entry, ...]) -> Asm:
        a = Asm(base_va + self._code_offset(entries))
        _emit_parse(a, base_va + _COUNT_OFF, base_va + _MAPPINGS_OFF)
        _emit_selector(a, base_va + _COUNT_OFF, base_va + _MAPPINGS_OFF)
        a.finish()
        return a

    def _build_section(self, base_va: int, entries: tuple[Entry, ...]) -> bytes:
        code = self._assemble(base_va, entries)
        body = bytearray(_TABLE_OFF)
        body += _table_bytes(base_va + _TABLE_OFF, entries, code.label_va("parse"))
        assert len(body) == self._code_offset(entries)
        return bytes(body) + code.finish()

    def _edits(
        self,
        data: bytes | bytearray,
        section_va: int,
        entries: tuple[Entry, ...],
        old_table: int,
        *,
        table_ref: bool = True,
    ) -> list[tuple[int, bytes, bytes, str]]:
        labels = self._assemble(section_va, entries).label_va
        out: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int) -> int:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            return off

        if table_ref:
            for ref_va, opcode in zip(
                PLAYER_TEMPLATE_FIELD_TABLE_REFS,
                PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
                strict=True,
            ):
                out.append(
                    (
                        at(ref_va),
                        bytes([opcode]) + _u32(old_table),
                        bytes([opcode]) + _u32(section_va + _TABLE_OFF),
                        f"PlayerTemplate field table ref @0x{ref_va:08x}",
                    )
                )
        out.append(
            (
                at(SPELL_STORE_COMMAND_SET_CALL),
                SPELL_STORE_COMMAND_SET_CALL_BYTES,
                _call(SPELL_STORE_COMMAND_SET_CALL, labels("selector")),
                "AptSpellStore purchase CommandSet call -> upgrade selector",
            )
        )
        return out

    def ini_surface(self) -> Engine:
        # The engine consumes exactly two names. `Opaque[]` models that token pair without
        # pretending the existing type grammar has a heterogeneous Upgrade/CommandSet tuple.
        return Engine(
            fields=(FieldDelta("PlayerTemplate", FIELD_NAME, "Opaque[]", None, patch=self.name),)
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        problems: list[str] = []

        try:
            table_va = self._resolve(data)
            all_entries = read_field_table(data, table_va)
        except ValueError as exc:
            return [f"cannot read the PlayerTemplate field table: {exc}"]
        entries = entries_before(data, all_entries, FIELD_NAME)
        if entries is None:
            return [f"the PlayerTemplate table does not name {FIELD_NAME}"]

        matching = [entry for entry in all_entries if read_cstring(data, entry[0]) == FIELD_NAME]
        if len(matching) != 1:
            problems.append(
                f"the PlayerTemplate table names {FIELD_NAME} {len(matching)} times, expected once"
            )
        else:
            parse_va = self._assemble(section_va, entries).label_va("parse")
            _name, parser, user_data, offset = matching[0]
            if parser != parse_va:
                problems.append(f"{FIELD_NAME} does not use the patch's parse function")
            if user_data != 0 or offset != 0:
                problems.append(
                    f"{FIELD_NAME} carries userData={user_data:#x}, offset={offset:#x}; "
                    "expected 0, 0"
                )

        count = struct.unpack_from("<I", data, section_off + _COUNT_OFF)[0]
        if count != 0:
            problems.append(f"the mapping count is not zero-initialised ({count})")
        rows = section_off + _MAPPINGS_OFF
        if bytes(data[rows : rows + MAPPINGS * MAPPING_STRIDE]) != bytes(MAPPINGS * MAPPING_STRIDE):
            problems.append("the mapping table is not zero-initialised")

        try:
            edits = self._edits(data, section_va, entries, table_va, table_ref=False)
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems
