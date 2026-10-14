"""Extend the existing PillageModule with upgrade gates and optional StealAmount.

Omitted StealAmount executes the native transfer unchanged. An explicit value,
including zero, selects an affordable all-or-nothing withdrawal and independent
PillageAmount payout. The native filter, counter, money methods, popup and Xfer
remain in place. Evidence and lifecycle audit: ../docs/pillage-module.md.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    INI_PARSE_BOOL,
    INI_PARSE_UNSIGNED_INT,
    INI_PARSE_UPGRADE_MASK,
    MONEY_AMOUNT,
    MONEY_WITHDRAW,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_UPGRADE_MASK,
    OPERATOR_NEW,
    PILLAGE_ALLOC,
    PILLAGE_ALLOC_RESUME,
    PILLAGE_ANCHORS,
    PILLAGE_COUNT_GATE,
    PILLAGE_COUNT_RESUME,
    PILLAGE_DATA_SIZE,
    PILLAGE_EVENT_EXIT,
    PILLAGE_FIELD_TABLE,
    PILLAGE_FIELD_TABLE_REF,
    PILLAGE_GUI_RESUME,
    PILLAGE_STOCK_FIELDS,
    PILLAGE_TRANSFER,
    PILLAGE_TRANSFER_RESUME,
    PILLAGE_WINDOWS,
    PLAYER_COMPLETED_UPGRADE_MASK,
    PLAYER_COMPLETED_UPGRADE_MASK_WORDS,
    PLAYER_MONEY,
    PLAYER_SCORE_KEEPER,
    UPGRADE_MASK_ANY,
    UPGRADE_MASK_TEST_ALL,
    UPGRADE_MASK_TEST_ANY,
)
from ..asm import JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32, u32
from .utils.field_tables import read_field_table, resolve_table
from .utils.name_tables import read_cstring

__all__ = ["PillageModuleExtensionPatch", "SECTION_NAME"]

SECTION_NAME = ".pillage"

# Patch-owned tail. Two fixed masks and three flags require no destructor or Xfer state.
_STEAL = PILLAGE_DATA_SIZE
_TRIGGER = _STEAL + 4
_CONFLICT = _TRIGGER + PLAYER_COMPLETED_UPGRADE_MASK_WORDS * 4
_ALL_TRIGGER = _CONFLICT + PLAYER_COMPLETED_UPGRADE_MASK_WORDS * 4
_ALL_CONFLICT = _ALL_TRIGGER + 1
_PRESENT = _ALL_CONFLICT + 1
_SIZE = (_PRESENT + 4) & ~3
_FIELDS = (
    ("StealAmount", _STEAL, "Int", None),
    ("TriggeredBy", _TRIGGER, "Ref[]:upgrades", None),
    ("ConflictsWith", _CONFLICT, "Ref[]:upgrades", None),
    ("RequiresAllTriggers", _ALL_TRIGGER, "Bool", False),
    ("RequiresAllConflictingTriggers", _ALL_CONFLICT, "Bool", False),
)


def _assemble(base: int) -> Asm:
    a = Asm(base)
    for name, _offset, _type, _default in _FIELDS:
        a.label(name)
        a.emit(name.encode("ascii") + b"\0")
    a.emit(bytes((-len(a.buf)) % 4))
    a.label("table")
    a.emit(PILLAGE_ANCHORS[PILLAGE_FIELD_TABLE][:48])
    for name, offset, _type, _default in _FIELDS:
        a.emit(u32(a.label_va(name)))
        if name == "StealAmount":
            a.label("parse_pointer")
            a.emit(bytes(4))
        else:
            a.emit(
                u32(INI_PARSE_BOOL if name.startswith("RequiresAll") else INI_PARSE_UPGRADE_MASK)
            )
        a.emit(bytes(4), u32(offset))  # parser userData = NULL
    a.emit(bytes(16))

    a.label("allocate")
    a.emit(0x68, u32(_SIZE))
    a.call_absolute(OPERATOR_NEW)
    # The original POP ECX still cleans the allocation argument at the resume point.
    a.emit(b"\x85\xc0")
    a.jcc(JE, "allocated")
    a.emit(b"\x50\x57\x8d\x78", bytes([PILLAGE_DATA_SIZE]))  # save result/EDI, tail
    a.emit(b"\x33\xd2\xb9", u32((_SIZE - PILLAGE_DATA_SIZE) // 4))
    a.label("zero")
    a.emit(b"\x89\x17\x83\xc7\x04\x49")
    a.jcc(JNE, "zero")
    a.emit(b"\x5f\x58")
    a.label("allocated")
    a.jmp_absolute(PILLAGE_ALLOC_RESUME)

    a.label("parse_steal")
    # Native cdecl parser (INI*, instance, store, userData), followed by presence.
    # Only mark a successfully parsed value; all 32-bit values remain available.
    a.emit(b"\x55\x8b\xec\xff\x75\x14\xff\x75\x10\xff\x75\x0c\xff\x75\x08")
    a.call_absolute(INI_PARSE_UNSIGNED_INT)
    # Derive presence from the field's store pointer, so it does not depend on
    # which enclosing instance the INI dispatcher supplies as its second argument.
    a.emit(
        b"\x83\xc4\x10\x8b\x45\x10\xc6\x80",
        u32(_PRESENT - _STEAL),
        b"\x01\xc9\xc3",
    )

    a.label("gate")
    # At this site ESI is owner, EBX data, EDI interface. Keep the native frame
    # and all registers; held uses EBX as owner and ESI as data, as in the LGB idiom.
    a.emit(b"\x60\x8b\xde\x8b\x77\xf4")  # PUSHAD; owner; data
    for offset, flag, fail, following in (
        (_TRIGGER, _ALL_TRIGGER, JE, "conflicts"),
        (_CONFLICT, _ALL_CONFLICT, JNE, "active"),
    ):
        a.emit(b"\x8d\x8e", u32(offset))
        a.call_absolute(UPGRADE_MASK_ANY)
        a.emit(b"\x84\xc0")
        a.jcc(JE, following)
        a.emit(b"\x8d\x86", u32(offset), b"\x0f\xb6\x96", u32(flag))
        a.call("held")
        a.emit(b"\x84\xc0")
        a.jcc(fail, "inactive")
        a.label(following)
    a.emit(b"\x61", PILLAGE_WINDOWS[PILLAGE_COUNT_GATE])
    a.jmp_absolute(PILLAGE_COUNT_RESUME)
    a.label("inactive")
    a.emit(b"\x61")
    a.jmp_absolute(PILLAGE_EVENT_EXIT)

    a.label("held")
    # EAX required mask, DL all-of, EBX owning object. Test object OR player;
    # an ALL requirement split across scopes deliberately does not satisfy it.
    a.emit(0xB9, u32(UPGRADE_MASK_TEST_ANY), b"\x84\xd2")
    a.jcc(JE, "picked")
    a.emit(0xB9, u32(UPGRADE_MASK_TEST_ALL))
    a.label("picked")
    a.emit(b"\x51\x50\x50\x8d\x8b", u32(OBJECT_UPGRADE_MASK), b"\xff\x54\x24\x08")
    a.emit(b"\x84\xc0")
    a.jcc(JNE, "held_done")
    a.emit(b"\x8b\xcb")
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "held_done")  # NULL player leaves AL = 0
    a.emit(b"\xff\x34\x24\x8d\x88", u32(PLAYER_COMPLETED_UPGRADE_MASK))
    a.emit(b"\xff\x54\x24\x08")
    a.label("held_done")
    a.emit(b"\x83\xc4\x08\xc3")

    a.label("transfer")
    a.emit(b"\x8b\x4d\xf0\x80\xb9", u32(_PRESENT), b"\x00")
    a.jcc(JNE, "extended")
    # Replay both displaced loads and resume the original min/withdraw/deposit path.
    a.emit(b"\x8b\x49\x08")
    a.jmp_absolute(PILLAGE_TRANSFER_RESUME)
    a.label("extended")
    a.emit(b"\x8b\xd8\x8b\x41", bytes([_STEAL]))  # EBX attacker, EAX cost
    a.emit(b"\x39\x87", u32(PLAYER_MONEY + MONEY_AMOUNT))  # unsigned balance >= cost
    a.jcc(JB, "unaffordable")
    a.emit(b"\x6a\x01\x8d\x8f", u32(PLAYER_SCORE_KEEPER), b"\x51\x50\x8d\x8f")
    a.emit(u32(PLAYER_MONEY))
    a.call_absolute(MONEY_WITHDRAW)
    # Zero withdrawal is valid. The native call has no synchronized callback
    # between the affordability check and its subtraction; no partial transfer.
    a.emit(b"\x8b\x4d\xf0\x8b\x79\x08\x85\xff")  # EDI payout
    a.jcc(JE, "unaffordable")  # zero payout: withdrawal stands, skip +0 popup
    a.jmp_absolute(PILLAGE_GUI_RESUME)  # native deposit and GUI, amount = EDI
    a.label("unaffordable")
    a.jmp_absolute(PILLAGE_EVENT_EXIT)
    return a


def _content(base: int) -> bytes:
    a = _assemble(base)
    blob = bytearray(a.finish())
    struct.pack_into("<I", blob, a.label_va("parse_pointer") - base, a.label_va("parse_steal"))
    return bytes(blob)


def _edits(base: int) -> dict[int, bytes]:
    a = _assemble(base)
    return {
        **{
            va: jmp_rel32(va, a.label_va(label), len(PILLAGE_WINDOWS[va]))
            for va, label in (
                (PILLAGE_ALLOC, "allocate"),
                (PILLAGE_COUNT_GATE, "gate"),
                (PILLAGE_TRANSFER, "transfer"),
            )
        },
        PILLAGE_FIELD_TABLE_REF: b"\x68" + u32(a.label_va("table")),
    }


def _anchors(base: int | None = None) -> dict[int, bytes]:
    edits = {} if base is None else _edits(base)
    sites = {**PILLAGE_ANCHORS, **PILLAGE_WINDOWS}
    for va, old in sites.items():
        blob = bytearray(old)
        for at, new in edits.items():
            if va <= at and at + len(new) <= va + len(blob):
                blob[at - va : at - va + len(new)] = new
        sites[va] = bytes(blob)
    return sites


def _problems(data: bytes | bytearray, sites: dict[int, bytes]) -> list[str]:
    problems = []
    for va, expected in sites.items():
        try:
            off = file_offset(data, va)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if bytes(data[off : off + len(expected)]) != expected:
            problems.append(f"unexpected Pillage engine bytes at {va:#010x}")
    return problems


class PillageModuleExtensionPatch(Patch):
    """Gate Pillage events and support independent, affordable deduction and payout."""

    name = "pillage-module-extension"
    author = "Ostkannit"
    description = (
        "Extend PillageModule with TriggeredBy / ConflictsWith and both RequiresAll switches; "
        "optional StealAmount enables all-or-nothing withdrawal with independent "
        "PillageAmount payout"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        problems = _problems(data, _anchors())
        if problems:
            raise ValueError("; ".join(problems))
        table = resolve_table(data, (PILLAGE_FIELD_TABLE_REF,), (0x68,), "PillageModule")
        rows = read_field_table(data, table)
        fields = tuple(
            (read_cstring(data, name), parse, userdata, offset)
            for name, parse, userdata, offset in rows
        )
        if fields != PILLAGE_STOCK_FIELDS:
            raise ValueError("unexpected Pillage field names, parsers or offsets")
        base = allocate_section(data, SECTION_NAME, _content, 0x60000060)
        for va, new in _edits(base).items():
            apply_byte_patch(data, file_offset(data, va), PILLAGE_WINDOWS[va], new, self.name)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section"]
        base, off, size = located
        content = _content(base)
        problems = _problems(data, _anchors(base))
        if size != len(content) or bytes(data[off : off + size]) != content:
            problems.append(f"unexpected {SECTION_NAME} table, strings or helper bodies")
        return problems

    def ini_surface(self) -> Engine:
        # Int is the supported integer spelling in parse_type(), even though the
        # native StealAmount parser is unsigned. None records omission, not zero.
        return Engine(
            fields=tuple(
                FieldDelta("PillageModule", name, kind, default, self.name)
                for name, _offset, kind, default in _FIELDS
            )
        )
