"""Give upgrade-mode ``CostModifierUpgrade`` records an explicit grouping identity.

``DiscountGroup`` replaces the carrier template name in the existing Player record key when it
is non-empty. The stock percentage and target vectors remain part of that key. The Palantir then
shows the selected module's exact group record instead of querying the global empty-name sum.

The Worldbuilder companion accepts the same keyword without storing it or running game logic.

Derivation and compatibility notes: ``../../docs/cost-modifier-upgrade-groups.md``.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    ASCII_STRING_COMPARE,
    ASCII_STRING_COPY_CTOR,
    ASCII_STRING_DTOR,
    ASCII_STRING_VECTOR_EQUAL,
    COST_MODIFIER_PALANTIR_UPGRADE_QUERY,
    COST_MODIFIER_PALANTIR_UPGRADE_QUERY_BYTES,
    COST_MODIFIER_PALANTIR_UPGRADE_QUERY_RESUME,
    COST_MODIFIER_UPGRADE_FIELD_TABLE,
    COST_MODIFIER_UPGRADE_FIELD_TABLE_REF,
    COST_MODIFIER_UPGRADE_FIELD_TABLE_REF_BYTES,
    COST_MODIFIER_UPGRADE_MODULEDATA_CTOR,
    COST_MODIFIER_UPGRADE_MODULEDATA_CTOR_CALL,
    COST_MODIFIER_UPGRADE_MODULEDATA_CTOR_CALL_BYTES,
    COST_MODIFIER_UPGRADE_MODULEDATA_DTOR,
    COST_MODIFIER_UPGRADE_MODULEDATA_DTOR_BYTES,
    COST_MODIFIER_UPGRADE_MODULEDATA_SIZE,
    COST_MODIFIER_UPGRADE_MODULEDATA_SIZE_SITE,
    COST_MODIFIER_UPGRADE_MODULEDATA_SIZE_SITE_BYTES,
    COST_MODIFIER_UPGRADE_STOCK_FIELDS,
    EMPTY_ASCII_STRING,
    FLOAT_VECTOR_EQUAL,
    GAME_DATA_ASCIISTRING_PARSER,
    PLAYER_ADD_UPGRADE_DISCOUNT_RECORD,
    PLAYER_ADD_UPGRADE_DISCOUNT_RECORD_BYTES,
    PLAYER_GET_UPGRADE_DISCOUNT,
    PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD,
    PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD_BYTES,
    PLAYER_UPGRADE_DISCOUNTS,
    PLAYER_UPGRADE_DISCOUNTS_END,
    UPGRADE_DISCOUNT_RECORD_PERCENTAGES,
    UPGRADE_DISCOUNT_RECORD_SIZE,
    UPGRADE_DISCOUNT_RECORD_TARGETS,
    UPGRADE_DISCOUNT_RECORD_VALUE,
    WORLDBUILDER_COST_MODIFIER_UPGRADE_ANCHORS,
    WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL,
    WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL_BYTES,
    WORLDBUILDER_INI_GET_NEXT_TOKEN,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE,
)
from ...asm import JE, JNE, Asm
from ...patcher import Patch
from ...utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    jmp_rel32,
    read_cstring,
    u32,
)

__all__ = [
    "DISCOUNT_GROUP_OFFSET",
    "KEYWORD",
    "PATCHED_MODULEDATA_SIZE",
    "SECTION_NAME",
    "WORLDBUILDER_SECTION_NAME",
    "CostModifierUpgradeGroupsPatch",
    "CostModifierUpgradeGroupsWorldbuilderPatch",
]

KEYWORD = "DiscountGroup"
SECTION_NAME = ".cmugrp"
WORLDBUILDER_SECTION_NAME = ".wbcmug"
SECTION_CHARACTERISTICS = 0x60000060
FIELD_ENTRY_SIZE = 16
DISCOUNT_GROUP_OFFSET = COST_MODIFIER_UPGRADE_MODULEDATA_SIZE
PATCHED_MODULEDATA_SIZE = DISCOUNT_GROUP_OFFSET + 4

# The displaced first instructions. Their continuation addresses are part of each hook's ABI.
_MODULEDATA_DTOR_RESUME = COST_MODIFIER_UPGRADE_MODULEDATA_DTOR + 5
_ADD_RESUME = PLAYER_ADD_UPGRADE_DISCOUNT_RECORD + 5
_REMOVE_RESUME = PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD + 5

_ANCHORS = (
    (COST_MODIFIER_UPGRADE_MODULEDATA_CTOR, bytes.fromhex("b8b834ba00"), "ModuleData ctor"),
    (ASCII_STRING_DTOR, bytes.fromhex("6aff68f80eb700"), "AsciiString destructor"),
    (ASCII_STRING_COPY_CTOR, bytes.fromhex("56578bf9e897f6ff"), "AsciiString copy constructor"),
    (ASCII_STRING_COMPARE, bytes.fromhex("8b4424048b00"), "AsciiString comparison"),
    (PLAYER_GET_UPGRADE_DISCOUNT, bytes.fromhex("558bec510f57c0"), "upgrade-discount sum"),
)


def _cstring(text: str) -> bytes:
    blob = text.encode("ascii") + b"\x00"
    return blob + bytes(-len(blob) % 4)


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)

    a.label("ctor")
    a.call_absolute(COST_MODIFIER_UPGRADE_MODULEDATA_CTOR)
    a.emit(b"\xc7\x80", u32(DISCOUNT_GROUP_OFFSET), b"\x00\x00\x00\x00\xc3")

    # Enter before the stock exception prologue, destroy the appended AsciiString, then replay
    # its displaced first instruction and continue into the native destructor.
    a.label("dtor")
    a.emit(b"\x51\x81\xc1", u32(DISCOUNT_GROUP_OFFSET))
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(b"\x59\xb8\xf4\x34\xba\x00")
    a.jmp_absolute(_MODULEDATA_DTOR_RESUME)

    # Both Player helpers receive (ModuleData *, const AsciiString *carrierName). Repointing the
    # second argument before their prologue covers apply, removal and both capture-transfer arms.
    a.label("add")
    a.emit(b"\x8b\x44\x24\x04\x83\xb8", u32(DISCOUNT_GROUP_OFFSET), 0x00)
    a.jcc(JE, "add_native")
    a.emit(b"\x05", u32(DISCOUNT_GROUP_OFFSET), b"\x89\x44\x24\x08")
    a.label("add_native")
    a.emit(PLAYER_ADD_UPGRADE_DISCOUNT_RECORD_BYTES)
    a.jmp_absolute(_ADD_RESUME)

    a.label("remove")
    a.emit(b"\x8b\x44\x24\x04\x83\xb8", u32(DISCOUNT_GROUP_OFFSET), 0x00)
    a.jcc(JE, "remove_native")
    a.emit(b"\x05", u32(DISCOUNT_GROUP_OFFSET), b"\x89\x44\x24\x08")
    a.label("remove_native")
    a.emit(PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD_BYTES)
    a.jmp_absolute(_REMOVE_RESUME)

    # __thiscall(CostModifierUpgrade *, Player *), ret 4, value in st0. Empty groups execute the
    # stock empty-name query. Explicit groups locate the exact three-part Player record key and
    # return only that ladder's selected percentage.
    a.label("ui")
    a.emit(b"\x55\x8b\xec\x53\x56\x57\x8b\xf1\x8b\x46\x04")
    a.emit(b"\x83\xb8", u32(DISCOUNT_GROUP_OFFSET), 0x00)
    a.jcc(JNE, "ui_grouped")
    a.emit(b"\x6a\x00\x8b\xcc\x68", u32(EMPTY_ASCII_STRING))
    a.call_absolute(ASCII_STRING_COPY_CTOR)
    a.emit(b"\x8b\x4d\x08")
    a.call_absolute(PLAYER_GET_UPGRADE_DISCOUNT)
    a.jmp("ui_done")

    a.label("ui_grouped")
    a.emit(b"\x8b\x5d\x08")  # ebx = Player
    a.emit(b"\x8b\xbb", u32(PLAYER_UPGRADE_DISCOUNTS))
    a.label("ui_loop")
    a.emit(b"\x3b\xbb", u32(PLAYER_UPGRADE_DISCOUNTS_END))
    a.jcc(JE, "ui_missing")

    a.emit(b"\x8b\x46\x04\x05", u32(DISCOUNT_GROUP_OFFSET), b"\x50\x8b\xcf")
    a.call_absolute(ASCII_STRING_COMPARE)
    a.emit(b"\x85\xc0")
    a.jcc(JNE, "ui_next")

    a.emit(b"\x8b\x46\x04\x05\x3c\x01\x00\x00\x50")
    a.emit(b"\x8d\x47", UPGRADE_DISCOUNT_RECORD_PERCENTAGES, 0x50)
    a.call_absolute(FLOAT_VECTOR_EQUAL)
    a.emit(b"\x83\xc4\x08\x84\xc0")
    a.jcc(JE, "ui_next")

    a.emit(b"\x8b\x46\x04\x05\x50\x01\x00\x00\x50")
    a.emit(b"\x8d\x47", UPGRADE_DISCOUNT_RECORD_TARGETS, 0x50)
    a.call_absolute(ASCII_STRING_VECTOR_EQUAL)
    a.emit(b"\x83\xc4\x08\x84\xc0")
    a.jcc(JE, "ui_next")
    a.emit(b"\xd9\x47", UPGRADE_DISCOUNT_RECORD_VALUE)
    a.jmp("ui_done")

    a.label("ui_next")
    a.emit(b"\x83\xc7", UPGRADE_DISCOUNT_RECORD_SIZE)
    a.jmp("ui_loop")
    a.label("ui_missing")
    a.emit(b"\xd9\xee")  # fldz
    a.label("ui_done")
    a.emit(b"\x5f\x5e\x5b\xc9\xc2\x04\x00")
    return a


class CostModifierUpgradeGroupsPatch(Patch):
    """Add explicit upgrade-discount groups and a group-specific Palantir readout."""

    name = "cost-modifier-upgrade-groups"
    author = "Ostkannit"
    description = (
        "Add DiscountGroup = <name> to CostModifierUpgrade. In UpgradeDiscount mode, equal "
        "groups with equal Percentage and ApplyToTheseUpgrades share one ladder across carrier "
        "Objects and BuildVariations; the Palantir shows that group's rung. Empty is stock"
    )

    def apply(self, data: bytearray) -> None:
        self._check(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._section(data, va)[0],
            SECTION_CHARACTERISTICS,
        )
        _content, labels = self._section(data, section_va)
        for va, old, new, note in self._edits(section_va, labels):
            apply_byte_patch(data, file_offset(data, va), old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _size = located
        try:
            content, labels = self._section(data, section_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]
        problems: list[str] = []
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(f"{SECTION_NAME} is not the table and code this patch builds")
        for va, _old, new, note in self._edits(section_va, labels):
            off = file_offset(data, va)
            got = bytes(data[off : off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{va:08x}: expected {new.hex()}, got {got.hex()}")
        problems += self._anchor_problems(data)
        return problems

    def ini_surface(self) -> Engine:
        field = FieldDelta("CostModifierUpgrade", KEYWORD, "String", "", self.name)
        return Engine(fields=(field,))

    def _section(self, data: bytes | bytearray, section_va: int) -> tuple[bytes, dict[str, int]]:
        stock = self._stock_table(data)
        table_size = (len(COST_MODIFIER_UPGRADE_STOCK_FIELDS) + 2) * FIELD_ENTRY_SIZE
        keyword_va = section_va + table_size
        keyword = _cstring(KEYWORD)
        code_va = keyword_va + len(keyword)
        code = _assemble(code_va)
        row = (
            u32(keyword_va)
            + u32(GAME_DATA_ASCIISTRING_PARSER)
            + u32(0)
            + u32(DISCOUNT_GROUP_OFFSET)
        )
        table = stock + row + bytes(FIELD_ENTRY_SIZE)
        assert len(table) == table_size
        labels = {name: code.label_va(name) for name in ("ctor", "dtor", "add", "remove", "ui")}
        return table + keyword + code.finish(), labels

    def _stock_table(self, data: bytes | bytearray) -> bytes:
        off = file_offset(data, COST_MODIFIER_UPGRADE_FIELD_TABLE, "the CostModifier field table")
        size = len(COST_MODIFIER_UPGRADE_STOCK_FIELDS) * FIELD_ENTRY_SIZE
        rows = bytes(data[off : off + size])
        if len(rows) != size:
            raise ValueError("the CostModifierUpgrade field table runs past the image")
        for index, (name, offset) in enumerate(COST_MODIFIER_UPGRADE_STOCK_FIELDS):
            name_va, _parse, _user, field_off = struct.unpack_from("<4I", rows, index * 16)
            got = read_cstring(data, name_va)
            if got != name or field_off != offset:
                raise ValueError(
                    f"field table row {index}: expected {name!r} at 0x{offset:x}, found "
                    f"{got!r} at 0x{field_off:x}"
                )
        terminator = bytes(data[off + size : off + size + FIELD_ENTRY_SIZE])
        if terminator != bytes(FIELD_ENTRY_SIZE):
            raise ValueError("the CostModifierUpgrade field table is not NULL-terminated")
        return rows

    @staticmethod
    def _edits(section_va: int, labels: dict[str, int]) -> list[tuple[int, bytes, bytes, str]]:
        ui = call_rel32(COST_MODIFIER_PALANTIR_UPGRADE_QUERY + 3, labels["ui"])
        ui_hook = b"\xff\x75\x08" + ui
        ui_hook += jmp_rel32(
            COST_MODIFIER_PALANTIR_UPGRADE_QUERY + len(ui_hook),
            COST_MODIFIER_PALANTIR_UPGRADE_QUERY_RESUME,
            len(COST_MODIFIER_PALANTIR_UPGRADE_QUERY_BYTES) - len(ui_hook),
        )
        return [
            (
                COST_MODIFIER_UPGRADE_MODULEDATA_SIZE_SITE,
                COST_MODIFIER_UPGRADE_MODULEDATA_SIZE_SITE_BYTES,
                b"\x68" + u32(PATCHED_MODULEDATA_SIZE),
                "sizeof(CostModifierUpgradeModuleData)",
            ),
            (
                COST_MODIFIER_UPGRADE_MODULEDATA_CTOR_CALL,
                COST_MODIFIER_UPGRADE_MODULEDATA_CTOR_CALL_BYTES,
                call_rel32(COST_MODIFIER_UPGRADE_MODULEDATA_CTOR_CALL, labels["ctor"]),
                "ModuleData ctor -> initialize DiscountGroup",
            ),
            (
                COST_MODIFIER_UPGRADE_MODULEDATA_DTOR,
                COST_MODIFIER_UPGRADE_MODULEDATA_DTOR_BYTES,
                jmp_rel32(COST_MODIFIER_UPGRADE_MODULEDATA_DTOR, labels["dtor"]),
                "ModuleData dtor -> release DiscountGroup",
            ),
            (
                COST_MODIFIER_UPGRADE_FIELD_TABLE_REF,
                COST_MODIFIER_UPGRADE_FIELD_TABLE_REF_BYTES,
                b"\x68" + u32(section_va),
                "CostModifierUpgrade field table -> cave",
            ),
            (
                PLAYER_ADD_UPGRADE_DISCOUNT_RECORD,
                PLAYER_ADD_UPGRADE_DISCOUNT_RECORD_BYTES,
                jmp_rel32(PLAYER_ADD_UPGRADE_DISCOUNT_RECORD, labels["add"]),
                "upgrade-discount add key -> DiscountGroup",
            ),
            (
                PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD,
                PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD_BYTES,
                jmp_rel32(PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD, labels["remove"]),
                "upgrade-discount remove key -> DiscountGroup",
            ),
            (
                COST_MODIFIER_PALANTIR_UPGRADE_QUERY,
                COST_MODIFIER_PALANTIR_UPGRADE_QUERY_BYTES,
                ui_hook,
                "CostModifierUpgrade Palantir query -> exact group",
            ),
        ]

    @staticmethod
    def _anchor_problems(data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        for va, expected, what in _ANCHORS:
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                problems.append(f"{what} @0x{va:08x}: expected {expected.hex()}, got {got.hex()}")
        return problems

    def _check(self, data: bytes | bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries this patch ({SECTION_NAME} exists)")
        # Read and fingerprint the table before allocating a section.
        self._stock_table(data)
        edits = self._edits(
            COST_MODIFIER_UPGRADE_FIELD_TABLE,
            {name: 0 for name in ("ctor", "dtor", "add", "remove", "ui")},
        )
        for va, old, _new, note in edits:
            off = file_offset(data, va)
            got = bytes(data[off : off + len(old)])
            if got != old:
                raise ValueError(
                    f"not the expected build: {note} @0x{va:08x}: "
                    f"expected {old.hex()}, got {got.hex()}"
                )
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError("not the expected build: " + "; ".join(problems))


class CostModifierUpgradeGroupsWorldbuilderPatch(Patch):
    """Accept DiscountGroup in Worldbuilder without changing the native ModuleData layout."""

    name = "cost-modifier-upgrade-groups-wb"
    author = "Ostkannit"
    description = (
        "Worldbuilder.exe (not game.dat): accept CostModifierUpgrade's DiscountGroup keyword "
        "for data using cost-modifier-upgrade-groups; read and discard the value without "
        "changing ModuleData, discounts or Palantir behavior; parser-only"
    )

    @staticmethod
    def _assemble(base: int) -> Asm:
        # A keyword-only table and its terminator, then the name, then executable helpers.
        a = Asm(base + 2 * FIELD_ENTRY_SIZE + len(_cstring(KEYWORD)))
        a.label("append")
        # thiscall(MultiIniFieldParse *, table *, extraOffset), ret 8. Preserve this across
        # the native append, replaying its exact arguments before appending our own table.
        a.emit(b"\x56\x8b\xf1\xff\x74\x24\x0c\xff\x74\x24\x0c")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)
        a.emit(b"\x6a\x00\x68", u32(base), b"\x8b\xce")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)
        a.emit(b"\x5e\xc2\x08\x00")

        a.label("parse")
        # cdecl(INI *, instance *, store *, userData). No stores through either object pointer
        # and no owned string: getNextToken consumes the name, and readLine discards the rest.
        # NULL separators select the INI object's native separator set. Caller pops all 4 args.
        a.emit(b"\x8b\x4c\x24\x04\x6a\x00")
        a.call_absolute(WORLDBUILDER_INI_GET_NEXT_TOKEN)
        a.emit(b"\xc3")
        return a

    def _build(self, base: int) -> bytes:
        code = self._assemble(base)
        row = u32(base + 2 * FIELD_ENTRY_SIZE) + u32(code.label_va("parse")) + bytes(8)
        return row + bytes(FIELD_ENTRY_SIZE) + _cstring(KEYWORD) + code.finish()

    @staticmethod
    def _anchor_problems(data: bytes | bytearray, call: bytes) -> list[str]:
        problems = []
        for va, expected in {
            **WORLDBUILDER_COST_MODIFIER_UPGRADE_ANCHORS,
            WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL: call,
        }.items():
            try:
                off = file_offset(data, va)
                got = bytes(data[off : off + len(expected)])
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if got != expected:
                problems.append(f"unexpected bytes at 0x{va:08x}: {got.hex()}")
        return problems

    def apply(self, data: bytearray) -> None:
        if find_section(data, WORLDBUILDER_SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {WORLDBUILDER_SECTION_NAME} section")
        problems = self._anchor_problems(
            data, WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL_BYTES
        )
        if problems:
            raise ValueError("not the expected Worldbuilder build: " + "; ".join(problems))

        out = bytearray(data)
        base = allocate_section(
            out, WORLDBUILDER_SECTION_NAME, self._build, SECTION_CHARACTERISTICS
        )
        site = WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL
        apply_byte_patch(
            out,
            file_offset(out, site),
            WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL_BYTES,
            call_rel32(site, self._assemble(base).label_va("append")),
            "Worldbuilder CostModifierUpgrade -> append DiscountGroup parser table",
        )
        data[:] = out

    def verify(self, data: bytes | bytearray) -> list[str]:
        section = find_section(data, WORLDBUILDER_SECTION_NAME)
        if section is None:
            return [f"no {WORLDBUILDER_SECTION_NAME} section"]
        base, off, size = section
        expected = self._build(base)
        problems = []
        if size != len(expected) or bytes(data[off : off + size]) != expected:
            problems.append(f"unexpected {WORLDBUILDER_SECTION_NAME} table or helper body")
        call = call_rel32(
            WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL,
            self._assemble(base).label_va("append"),
        )
        return problems + self._anchor_problems(data, call)
