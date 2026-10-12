"""Script-selected CastleBehavior prefabs; stock unpack rules and retail actions stay intact.

The two unused template slots are registered in the engine. CommandButton selection travels
through the stock message stream, with an optional typed payload.
Derivation and phase-one limitations: ../../docs/castle-prefab.md.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    APPEND_MESSAGE_VTABLE_SLOT,
    ASCII_STRING_SET,
    ASCII_STRING_SET_BYTES,
    CASTLE_BEHAVIOR_DESTRUCTOR,
    CASTLE_BEHAVIOR_FACTION_PREFAB,
    CASTLE_BEHAVIOR_PREFAB_RESOLVER,
    CASTLE_BEHAVIOR_START_UNPACK,
    CASTLE_BEHAVIOR_UNPACK,
    CASTLE_BEHAVIOR_UNPACK_EPILOGUE,
    CASTLE_COMMAND_ANCHORS,
    CASTLE_COMMAND_RECEIVER,
    CASTLE_COMMAND_RECEIVER_FAIL,
    CASTLE_COMMAND_RECEIVER_RESUME,
    CASTLE_COMMAND_RECEIVER_STOCK,
    CASTLE_COMMAND_SENDER,
    CASTLE_COMMAND_SENDER_EXIT,
    CASTLE_COMMAND_SENDER_STOCK_RESUME,
    CASTLE_PREFAB_RESOLVER_USES,
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_CTOR,
    COMMAND_BUTTON_CTOR_BYTES,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    COMMAND_BUTTON_OBJECT,
    COMMAND_BUTTON_SIDECAR_CTOR,
    COMMAND_BUTTON_SIDECAR_CTOR_BYTES,
    GAME_MESSAGE_APPEND_INTEGER,
    GAME_MESSAGE_ARGUMENT_COUNT,
    GAME_MESSAGE_GET_ARGUMENT_DATA,
    GAME_MESSAGE_GET_ARGUMENT_TYPE,
    INI_NEXT_TOKEN_OR_NULL,
    MSG_CASTLE_UNPACK,
    NAME_KEY_FROM_CSTR,
    NAME_KEY_FROM_STRING,
    OBJECT_ID,
    SCRIPT_ACTION_DISPATCH_BOUND,
    SCRIPT_ACTION_EPILOGUE,
    SCRIPT_ACTION_JUMP_TABLE,
    SCRIPT_ACTION_PARAM_ARRAY,
    SCRIPT_ACTION_PARAM_COUNT,
    SCRIPT_ACTION_TEMPLATE_INIT,
    SCRIPT_ACTION_TEMPLATE_LAST_SET,
    SCRIPT_NAMED_BASE_START_UNPACK_CALL,
    SCRIPT_NAMED_BASE_UNPACK,
    SCRIPT_PARAMETER_STRING,
    SCRIPT_PARAMETER_TYPE,
    SCRIPT_RESOLVE_UNIT_PARAMETER,
    SCRIPT_TEMPLATE_STRING_SET,
    THE_MESSAGE_STREAM,
    THE_NAME_KEY_GENERATOR,
    THE_SCRIPT_ENGINE,
    WORLDBUILDER_ASCIISTRING_SET,
    WORLDBUILDER_SCRIPT_ACTION_TEMPLATE_LAST_SET,
    WORLDBUILDER_SCRIPT_ACTION_TEMPLATES_INIT,
)
from ...asm import JA, JAE, JB, JE, JNE, Asm
from ...patcher import Patch
from ...utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    jmp_rel32,
    u32,
)
from ..utils.field_tables import Entry, entries_before, read_field_table, resolve_table
from ..utils.name_tables import read_cstring

__all__ = ["CastlePrefabPatch", "CastlePrefabCommandButtonPatch", "CastlePrefabWorldbuilderPatch"]

SECTION_NAME = ".cstpre"
WB_SECTION_NAME = ".cstprwb"
ACTION_IDS = (227, 343)
ACTION_NAMES = ("NAMED_BASE_UNPACK_PREFAB", "NAMED_BASE_UNPACK_PREFAB_FREE")
PARAMETER_TYPES = (14, 54, 10)  # UNIT_NAME, NAMED_REFERENCE, TEXT_STRING
MAX_OVERRIDES = 256
PENDING_OFF = 0
TABLE_OFF = 0x20
SLOT_SIZE = 16  # behavior, key, object, ObjectID
CODE_OFF = TABLE_OFF + MAX_OVERRIDES * SLOT_SIZE
_CHARACTERISTICS = 0xE0000020  # code and writable simulation state

HOOKS = {
    SCRIPT_NAMED_BASE_START_UNPACK_CALL: (
        call_rel32(SCRIPT_NAMED_BASE_START_UNPACK_CALL, CASTLE_BEHAVIOR_START_UNPACK),
        "start",
        True,
    ),
    CASTLE_BEHAVIOR_PREFAB_RESOLVER: (bytes.fromhex("8bc18b4808"), "resolve", False),
    CASTLE_BEHAVIOR_UNPACK: (bytes.fromhex("b8ae55b900"), "unpack", False),
    CASTLE_BEHAVIOR_UNPACK_EPILOGUE: (bytes.fromhex("8b4df45e5b"), "complete", False),
    CASTLE_BEHAVIOR_DESTRUCTOR: (bytes.fromhex("b86854b900"), "destroy", False),
    SCRIPT_ACTION_TEMPLATE_LAST_SET: (
        call_rel32(SCRIPT_ACTION_TEMPLATE_LAST_SET, SCRIPT_TEMPLATE_STRING_SET),
        "register",
        True,
    ),
}
ANCHORS = {
    SCRIPT_NAMED_BASE_UNPACK: bytes.fromhex("558bec8b0dac3bde00"),
    SCRIPT_NAMED_BASE_START_UNPACK_CALL - 7: bytes.fromhex("6a00ff75108bce"),
    CASTLE_BEHAVIOR_PREFAB_RESOLVER + 5: bytes.fromhex("568b7004e84926efff508bcee839ffffff5ec3"),
    CASTLE_BEHAVIOR_FACTION_PREFAB: bytes.fromhex("b83453b900e8763f2a00"),
    CASTLE_BEHAVIOR_UNPACK + 5: bytes.fromhex("e87c102a005153568bf18b5e08"),
    CASTLE_BEHAVIOR_UNPACK_EPILOGUE + 5: bytes.fromhex("64890d00000000c9c20400"),
    CASTLE_BEHAVIOR_DESTRUCTOR + 5: bytes.fromhex("e83f242a0051568bf18975f0"),
    SCRIPT_ACTION_TEMPLATE_INIT: bytes.fromhex("535556578bf1"),
    SCRIPT_ACTION_TEMPLATE_LAST_SET + 5: bytes.fromhex("5f5e5d5bc3"),
    SCRIPT_ACTION_EPILOGUE: bytes.fromhex("8b4df45f5e"),
    SCRIPT_RESOLVE_UNIT_PARAMETER: bytes.fromhex("558bec568b75088b4624"),
    NAME_KEY_FROM_STRING: bytes.fromhex("8b4424048b0085c0"),
    ASCII_STRING_SET: ASCII_STRING_SET_BYTES,
    SCRIPT_TEMPLATE_STRING_SET: bytes.fromhex("56ff7424088bf1e84eefffff8bc65ec20400"),
    # The fixed dispatcher bound and the original unpack actions must survive installation.
    SCRIPT_ACTION_DISPATCH_BOUND: bytes.fromhex("3d570200000f8771480000ff248557f87c00"),
    SCRIPT_ACTION_JUMP_TABLE + 381 * 4: u32(0x007CE925),
    SCRIPT_ACTION_JUMP_TABLE + 493 * 4: u32(0x007CE928),
    **{va: call_rel32(va, CASTLE_BEHAVIOR_PREFAB_RESOLVER) for va in CASTLE_PREFAB_RESOLVER_USES},
}
WB_HOOK = WORLDBUILDER_SCRIPT_ACTION_TEMPLATE_LAST_SET
WB_STOCK = call_rel32(WB_HOOK, WORLDBUILDER_ASCIISTRING_SET)
WB_ANCHORS = {
    WORLDBUILDER_SCRIPT_ACTION_TEMPLATES_INIT: bytes.fromhex("558bec83ec08894df8"),
    WB_HOOK + 5: bytes.fromhex("8be55dc3"),
}


def _check(data: bytes | bytearray, sites: dict[int, bytes]) -> None:
    for va, expected in sites.items():
        off = file_offset(data, va)
        if bytes(data[off : off + len(expected)]) != expected:
            raise ValueError(f"{va:#010x}: expected {expected.hex()} - build or patch conflict")


def _slot_va(action_id: int) -> int:
    return SCRIPT_ACTION_JUMP_TABLE + action_id * 4


def _strings() -> tuple[bytes, list[dict[int, int]]]:
    blob = bytearray()
    records: list[dict[int, int]] = []
    for name, free in zip(ACTION_NAMES, (False, True), strict=True):
        fields = {
            0x0C: name,
            0x04: "Base/Unpack a base using a specific castle prefab"
            + (" for free" if free else ""),
            0x18: "Unpack castle ",
            0x1C: " as reference ",
            0x20: " using registered prefab ",
            0x24: " immediately for free" if free else " with normal faction rules",
        }
        record: dict[int, int] = {}
        for off, text in fields.items():
            record[off] = len(blob)
            blob.extend(text.encode("ascii") + b"\0")
        records.append(record)
    return bytes(blob), records


def _emit(base_va: int, *, worldbuilder: bool = False) -> Asm:
    a = Asm(base_va)
    if not worldbuilder:
        a.emit(bytes(CODE_OFF))
    a.label("register")
    setter = WORLDBUILDER_ASCIISTRING_SET if worldbuilder else SCRIPT_TEMPLATE_STRING_SET
    a.emit(b"\xff\x74\x24\x04")  # forward the caller's literal below our return address
    a.call_absolute(setter)  # replay the initializer's final string assignment
    a.emit(0x9C, 0x60)  # preserve initializer registers and flags
    if worldbuilder:
        a.emit(b"\x8b\x75\xf8")  # its debug frame retains the template owner
    # Strings follow code, so one fixed-width placeholder is patched after their label exists.
    string_fixups: list[tuple[int, int]] = []
    _, records = _strings()
    for action_id, fields in zip(ACTION_IDS, records, strict=True):
        record_off = 0x20 + action_id * 0x80
        values = {0: 3, 0x14: 4, 0x48: 3}
        values.update({0x4C + i * 4: kind for i, kind in enumerate(PARAMETER_TYPES)})
        for off, value in values.items():
            a.emit(b"\xc7\x86", u32(record_off + off), u32(value))
        for off, relative in fields.items():
            a.emit(0x68)
            string_fixups.append((len(a.buf), relative))
            a.emit(u32(0), b"\x8d\x8e", u32(record_off + off))
            a.call_absolute(setter)
    a.emit(0x61, 0x9D, b"\xc2\x04\x00")  # consume the original setter argument
    if not worldbuilder:
        _runtime(a, base_va)
    a.label("strings")
    a.emit(_strings()[0])
    for at, off in string_fixups:
        struct.pack_into("<I", a.buf, at, a.label_va("strings") + off)
    return a


def _runtime(a: Asm, base: int) -> None:
    pending = base + PENDING_OFF
    table = base + TABLE_OFF
    for name, free in [("normal", 0), ("free", 1)]:
        a.label(name)
        a.emit(0x6A, free)
        a.jmp("action")
    a.label("action")
    a.emit(0x9C, 0x60)  # a dispatcher case must leave its frame and registers intact
    a.emit(b"\x83\x7e", SCRIPT_ACTION_PARAM_COUNT, 3)
    a.jcc(JNE, "action_done")
    for i, kind in enumerate(PARAMETER_TYPES):
        a.emit(b"\x8b\x46", SCRIPT_ACTION_PARAM_ARRAY + i * 4)
        a.emit(b"\x85\xc0")
        a.jcc(JE, "action_done")
        a.emit(b"\x83\x78", SCRIPT_PARAMETER_TYPE, kind)
        if i == 2:
            # External map editors may encode generic string arguments as SCRIPT_NAME (2).
            # Both tags carry the same AsciiString; numeric and coordinate tags remain invalid.
            a.jcc(JE, "prefab_type_valid")
            a.emit(b"\x83\x78", SCRIPT_PARAMETER_TYPE, 2)
            a.jcc(JNE, "action_done")
            a.label("prefab_type_valid")
        else:
            a.jcc(JNE, "action_done")
    a.emit(b"\x8b\x46\x14\x8b\x40", SCRIPT_PARAMETER_STRING)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "action_done")
    a.emit(b"\x80\x78\x08\x00")  # an empty template must not accidentally select key zero
    a.jcc(JE, "action_done")
    a.emit(b"\xff\x76\x0c\x8b\x0d", u32(THE_SCRIPT_ENGINE))
    a.call_absolute(SCRIPT_RESOLVE_UNIT_PARAMETER)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "action_done")
    a.emit(b"\x8b\xd8")  # resolved target Object*, before stock validation
    a.emit(b"\x8b\x46\x14\x83\xc0", SCRIPT_PARAMETER_STRING, 0x50)
    a.emit(b"\x8b\x0d", u32(THE_NAME_KEY_GENERATOR))
    a.call_absolute(NAME_KEY_FROM_STRING)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "action_done")
    for off in (0, 4, 8):
        a.emit(b"\xff\x35", u32(pending + off))  # save an outer action's pending context
    a.emit(b"\x89\x1d", u32(pending), b"\xa3", u32(pending + 4))
    a.emit(b"\x8b\x46\x0c\xa3", u32(pending + 8))
    a.emit(b"\xff\x74\x24\x30")  # the free flag below pushfd, pushad, and three saved words
    a.emit(b"\x8b\x46\x10\x83\xc0", SCRIPT_PARAMETER_STRING, 0x50)
    a.emit(b"\xff\x76\x0c\x8b\xcf")
    a.call_absolute(SCRIPT_NAMED_BASE_UNPACK)
    for off in (8, 4, 0):
        a.emit(b"\x8f\x05", u32(pending + off))
    a.label("action_done")
    a.emit(0x61, 0x9D, b"\x83\xc4\x04")
    a.jmp_absolute(SCRIPT_ACTION_EPILOGUE)

    a.label("find")  # ecx=Behavior*, edx=slot or zero; eax is scratch
    a.emit(0xBA, u32(table), 0xB8, u32(MAX_OVERRIDES))
    a.label("find_loop")
    a.emit(b"\x39\x0a")
    a.jcc(JE, "found")
    a.emit(b"\x83\xc2", SLOT_SIZE, 0x48)
    a.jcc(JNE, "find_loop")
    a.emit(b"\x33\xd2")
    a.label("found")
    a.emit(0xC3)

    a.label("clear")
    a.call("find")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "clear_done")
    a.emit(b"\xc7\x02", u32(0))
    a.label("clear_done")
    a.emit(0xC3)

    # Shared entry for validated script and CommandButton requests. ECX=behavior,
    # EDI=owner, EAX=NameKey; return EAX=success. No pending/UI state is required.
    a.label("promote")
    a.emit(0x53, 0x50)
    a.call("find")
    a.emit(0x5B, b"\x85\xd2")
    a.jcc(JNE, "latch")
    a.emit(0xBA, u32(table), 0xB8, u32(MAX_OVERRIDES))
    a.label("empty_loop")
    a.emit(b"\x83\x3a\x00")
    a.jcc(JE, "latch")
    a.emit(b"\x83\xc2", SLOT_SIZE, 0x48)
    a.jcc(JNE, "empty_loop")
    a.emit(b"\x33\xc0", 0x5B, 0xC3)
    a.label("latch")
    a.emit(b"\x89\x0a\x89\x5a\x04\x89\x7a\x08")
    a.emit(b"\x8b\x47", OBJECT_ID, b"\x89\x42\x0c")
    a.emit(0xB8, u32(1), 0x5B, 0xC3)

    a.label("start")
    a.emit(0x9C, 0x60)
    a.emit(b"\x39\x3d", u32(pending))  # helper's resolved Object* must be our target
    a.jcc(JNE, "start_stock")
    a.emit(b"\x8b\x45\x08\x3b\x05", u32(pending + 8))
    a.jcc(JNE, "start_stock")  # reentrant helpers must also carry the same Parameter*
    a.emit(b"\x39\x79\x08")
    a.jcc(JNE, "start_stock")
    a.emit(b"\xa1", u32(pending + 4))
    a.call("promote")
    a.emit(b"\x85\xc0")
    a.jcc(JNE, "start_stock")
    a.emit(0x61, 0x9D, b"\xc2\x08\x00")  # full: decline rather than choose another prefab
    a.label("start_stock")
    a.emit(0x61, 0x9D)
    a.jmp_absolute(CASTLE_BEHAVIOR_START_UNPACK)  # tail call retains both arguments and ret 8

    a.label("resolve")
    a.emit(0x51)
    a.call("find")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "resolve_stock")
    a.emit(b"\x8b\x41\x08\x3b\x42\x08")
    a.jcc(JNE, "resolve_stock")
    a.emit(b"\x85\xc0")
    a.jcc(JE, "resolve_stock")
    a.emit(b"\x8b\x40", OBJECT_ID, b"\x3b\x42\x0c")
    a.jcc(JNE, "resolve_stock")
    a.emit(b"\x8b\x42\x04", 0x59, 0xC3)
    a.label("resolve_stock")
    a.emit(0x59, HOOKS[CASTLE_BEHAVIOR_PREFAB_RESOLVER][0])
    a.jmp_absolute(CASTLE_BEHAVIOR_PREFAB_RESOLVER + 5)

    a.label("unpack")
    # Hidden second argument captures this per invocation. ESI becomes Object* late in stock
    # unpack; its local at ebp-0x10 is reused too. Neither is a valid cleanup identity.
    a.emit(0x51, b"\xff\x74\x24\x08")
    a.call("unpack_stock")
    a.emit(0x59, b"\xc2\x04\x00")
    a.label("unpack_stock")
    a.emit(HOOKS[CASTLE_BEHAVIOR_UNPACK][0])
    a.jmp_absolute(CASTLE_BEHAVIOR_UNPACK + 5)

    a.label("complete")
    a.emit(0x9C, 0x60, b"\x8b\x4d\x0c")
    a.call("clear")
    a.emit(0x61, 0x9D, HOOKS[CASTLE_BEHAVIOR_UNPACK_EPILOGUE][0])
    a.jmp_absolute(CASTLE_BEHAVIOR_UNPACK_EPILOGUE + 5)

    a.label("destroy")
    a.emit(0x9C, 0x60)
    a.call("clear")  # destruction and map teardown cannot leave reusable pointers
    a.emit(0x61, 0x9D, HOOKS[CASTLE_BEHAVIOR_DESTRUCTOR][0])
    a.jmp_absolute(CASTLE_BEHAVIOR_DESTRUCTOR + 5)


def build_section(base_va: int) -> bytes:
    return _emit(base_va).finish()


def _replacements(base: int) -> dict[int, bytes]:
    a = _emit(base)
    sites = {
        va: (call_rel32 if call else jmp_rel32)(va, a.label_va(label))
        for va, (_, label, call) in HOOKS.items()
    }
    for action_id, label in zip(ACTION_IDS, ("normal", "free"), strict=True):
        sites[_slot_va(action_id)] = u32(a.label_va(label))
    return sites


class CastlePrefabPatch(Patch):
    name = "castle-prefab"
    author = "Ostkannit"
    experimental = True
    description = "Add NAMED_BASE_UNPACK_PREFAB[_FREE](castle, reference, prefab) script actions"

    def apply(self, data: bytearray) -> None:
        stock = {va: entry[0] for va, entry in HOOKS.items()}
        stock.update({_slot_va(i): u32(SCRIPT_ACTION_EPILOGUE) for i in ACTION_IDS})
        _check(data, {**ANCHORS, **stock})
        base = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        for va, replacement in _replacements(base).items():
            apply_byte_patch(data, file_offset(data, va), stock[va], replacement, self.name)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        base, off, _ = located
        try:
            _check(data, {**ANCHORS, **_replacements(base)})
        except ValueError as exc:
            return [str(exc)]
        expected = build_section(base)
        if bytes(data[off : off + len(expected)]) != expected:
            return [f"{SECTION_NAME} code or initial state differs"]
        return []


class CastlePrefabWorldbuilderPatch(Patch):
    name = "castle-prefab-wb"
    author = "Ostkannit"
    experimental = True
    description = (
        "Worldbuilder.exe (not game.dat): Offer both castle-prefab script actions "
        "with three string fields"
    )

    def apply(self, data: bytearray) -> None:
        _check(data, {**WB_ANCHORS, WB_HOOK: WB_STOCK})
        base = allocate_section(
            data, WB_SECTION_NAME, lambda va: _emit(va, worldbuilder=True).finish(), 0x60000020
        )
        apply_byte_patch(
            data, file_offset(data, WB_HOOK), WB_STOCK, call_rel32(WB_HOOK, base), self.name
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, WB_SECTION_NAME)
        if located is None:
            return [f"{WB_SECTION_NAME} section is absent"]
        base, off, _ = located
        try:
            _check(data, {**WB_ANCHORS, WB_HOOK: call_rel32(WB_HOOK, base)})
        except ValueError as exc:
            return [str(exc)]
        expected = _emit(base, worldbuilder=True).finish()
        if bytes(data[off : off + len(expected)]) != expected:
            return [f"{WB_SECTION_NAME} code differs"]
        return []


# Fixed-size load-time config; the simulation override itself remains in .cstpre.
COMMAND_SECTION = ".cstcmd"
COMMAND_MAGIC = 0x50534350  # wire integer: pySAGE Castle Prefab, version 1
COMMAND_FIELD = "CastlePrefab"
COMMAND_BUTTON_ROWS = 2048
COMMAND_PREFAB_ROWS = 1024
COMMAND_NAME_SIZE = 256
COMMAND_PREFAB_STRIDE = 8 + COMMAND_NAME_SIZE  # id, NameKey (zero quarantines), exact name
COMMAND_BUTTON_OFF = 16  # invalid, collision and capacity counters, reserved
COMMAND_PREFAB_OFF = COMMAND_BUTTON_OFF + COMMAND_BUTTON_ROWS * 8
COMMAND_FIELD_OFF = COMMAND_PREFAB_OFF + COMMAND_PREFAB_ROWS * COMMAND_PREFAB_STRIDE
COMMAND_TABLE_OFF = COMMAND_FIELD_OFF + 16
COMMAND_HOOKS = {
    CASTLE_COMMAND_SENDER: (b"\x68" + u32(MSG_CASTLE_UNPACK), "send"),
    CASTLE_COMMAND_RECEIVER: (CASTLE_COMMAND_RECEIVER_STOCK, "receive"),
    COMMAND_BUTTON_SIDECAR_CTOR: (COMMAND_BUTTON_SIDECAR_CTOR_BYTES, "button_ctor"),
}


def _prefab_id(name: str) -> int:
    """FNV-1a/32 of an ASCII, case-sensitive engine name, stripped of outer whitespace.

    Keep case: the engine's NameKey namespace is case-sensitive. Zero is reserved.
    Runtime parsing implements this same algorithm, with collision quarantine.
    """
    token = name.strip(" \t\r\n")
    raw = token.encode("ascii")
    if not raw or len(raw) >= COMMAND_NAME_SIZE or any(c < 33 or c > 126 for c in raw):
        raise ValueError("CastlePrefab requires one printable ASCII name of 1..255 bytes")
    value = 0x811C9DC5
    for c in raw:
        value = ((value ^ c) * 0x01000193) & 0xFFFFFFFF
    if not value:
        raise ValueError("CastlePrefab identifier zero is reserved")
    return value


def _command_table(data: bytes | bytearray) -> tuple[Entry, ...]:
    table = resolve_table(
        data,
        COMMAND_BUTTON_FIELD_TABLE_REFS,
        COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
        "CommandButton",
    )
    return read_field_table(data, table)


def _command_emit(base: int, entries: tuple[Entry, ...], core: int) -> Asm:
    a = Asm(base)
    a.emit(bytes(COMMAND_FIELD_OFF), COMMAND_FIELD.encode("ascii") + b"\0")
    a.emit(bytes(COMMAND_TABLE_OFF - len(a.buf)))
    for entry in entries:
        a.emit(struct.pack("<IIII", *entry))
    row_at = len(a.buf)
    a.emit(bytes(32))  # extension row and terminator; parse address follows code generation
    buttons = base + COMMAND_BUTTON_OFF
    prefabs = base + COMMAND_PREFAB_OFF
    # Buttons are recycled by the ctor. Search beyond holes, retaining the first free
    # row, so a recycled early identity cannot hide a later live button.
    a.label("find_button")
    a.emit(0x53, b"\x31\xdb", 0xBA, u32(buttons), 0xB8, u32(COMMAND_BUTTON_ROWS))
    a.label("button_loop")
    a.emit(b"\x39\x0a")
    a.jcc(JE, "button_found")
    a.emit(b"\x83\x3a\x00")
    a.jcc(JNE, "button_next")
    a.emit(b"\x85\xdb")
    a.jcc(JNE, "button_next")
    a.emit(b"\x8b\xda")
    a.label("button_next")
    a.emit(b"\x83\xc2\x08", 0x48)
    a.jcc(JNE, "button_loop")
    a.emit(b"\x8b\xd3")
    a.label("button_found")
    a.emit(0x5B, 0xC3)
    a.label("find_prefab")
    a.emit(0xBA, u32(prefabs), 0xB8, u32(COMMAND_PREFAB_ROWS))
    a.label("prefab_loop")
    a.emit(b"\x39\x0a")
    a.jcc(JE, "prefab_found")
    a.emit(b"\x83\x3a\x00")
    a.jcc(JE, "prefab_found")
    a.emit(b"\x81\xc2", u32(COMMAND_PREFAB_STRIDE), 0x48)
    a.jcc(JNE, "prefab_loop")
    a.emit(b"\x31\xd2")
    a.label("prefab_found")
    a.emit(0xC3)

    a.label("parse")  # cdecl (INI*, instance, store, userData); writes only sidecar
    a.emit(b"\x55\x8b\xec\x53\x56\x57\xfc\x81\xec", u32(256))
    # Repeated fields/invalid replacement cannot retain an earlier value.
    a.emit(b"\x8b\x4d\x0c")
    a.call("find_button")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "parse_capacity")
    a.emit(b"\x89\x0a\xc7\x42\x04", u32(0))
    a.emit(b"\x8b\x75\x08\x8b\xce\x6a\x00")
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "parse_invalid")
    a.emit(b"\x89\xe7\x31\xc9\xbb", u32(0x811C9DC5))
    a.label("parse_copy")
    a.emit(b"\x0f\xb6\x14\x08\x85\xd2")
    a.jcc(JE, "parse_copied")
    a.emit(b"\x83\xfa\x21")
    a.jcc(JB, "parse_invalid")
    a.emit(b"\x83\xfa\x7e")
    a.jcc(JA, "parse_invalid")
    a.emit(b"\x81\xf9", u32(COMMAND_NAME_SIZE - 1))
    a.jcc(JAE, "parse_invalid")
    a.emit(b"\x88\x14\x0f\x31\xd3\x69\xdb", u32(0x01000193), 0x41)
    a.jmp("parse_copy")
    a.label("parse_copied")
    a.emit(b"\x85\xc9")
    a.jcc(JE, "parse_invalid")
    a.emit(b"\xc6\x04\x0f\x00\x85\xdb")
    a.jcc(JE, "parse_invalid")
    # Reject extra tokens before registering names or modifying the engine name registry.
    a.emit(b"\x8b\xce\x6a\x00")
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)
    a.emit(b"\x85\xc0")
    a.jcc(JNE, "parse_invalid")
    a.emit(b"\x8b\xcb")
    a.call("find_prefab")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "parse_capacity")
    a.emit(b"\x83\x3a\x00")
    a.jcc(JE, "parse_new")
    a.emit(b"\x83\x7a\x04\x00")
    a.jcc(JE, "parse_invalid")  # already quarantined, never rehabilitate a colliding ID
    a.emit(b"\x89\xe6\x8d\x7a\x08")
    a.label("parse_compare")
    a.emit(b"\x8a\x06\x3a\x07")
    a.jcc(JNE, "parse_collision")
    a.emit(b"\x84\xc0")
    a.jcc(JE, "parse_commit")
    a.emit(0x46, 0x47)
    a.jmp("parse_compare")
    a.label("parse_new")
    a.emit(b"\x89\x1a\x89\xe6\x8d\x7a\x08")
    a.label("parse_store")
    a.emit(b"\xac\xaa\x84\xc0")
    a.jcc(JNE, "parse_store")
    a.emit(0x52, b"\x8d\x42\x08", 0x50, b"\x8b\x0d", u32(THE_NAME_KEY_GENERATOR))
    a.call_absolute(NAME_KEY_FROM_CSTR)  # load-time only; no UI-side interning
    a.emit(0x5A, b"\x89\x42\x04\x85\xc0")
    a.jcc(JE, "parse_invalid")
    a.label("parse_commit")
    a.emit(b"\x8b\x4d\x0c")
    a.call("find_button")
    a.emit(b"\x89\x5a\x04")
    a.jmp("parse_done")
    a.label("parse_collision")
    a.emit(b"\xc7\x42\x04", u32(0), b"\xff\x05", u32(base + 4))
    a.jmp("parse_done")
    a.label("parse_capacity")
    a.emit(b"\xff\x05", u32(base + 8))
    a.jmp("parse_done")
    a.label("parse_invalid")
    a.emit(b"\xff\x05", u32(base))
    a.label("parse_done")
    a.emit(b"\x8d\x65\xf4\x5f\x5e\x5b\x5d\xc3")

    a.label("button_ctor")
    a.emit(COMMAND_BUTTON_SIDECAR_CTOR_BYTES, 0x9C, 0x60)
    a.call("find_button")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "ctor_done")
    a.emit(b"\xc7\x02", u32(0), b"\xc7\x42\x04", u32(0))
    a.label("ctor_done")
    a.emit(0x61, 0x9D)
    a.jmp_absolute(COMMAND_BUTTON_SIDECAR_CTOR + len(COMMAND_BUTTON_SIDECAR_CTOR_BYTES))

    a.label("send")
    a.emit(0x9C, 0x60, b"\x8b\xce")
    a.call("find_button")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "send_stock")
    a.emit(b"\x39\x32")
    a.jcc(JNE, "send_stock")
    a.emit(b"\x8b\x4a\x04\x85\xc9")
    a.jcc(JE, "send_stock")
    a.emit(b"\x8b\xf9")  # retain stable id in EDI across calls
    a.call("find_prefab")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "send_stock")
    a.emit(b"\x39\x3a")
    a.jcc(JNE, "send_stock")
    a.emit(b"\x83\x7a\x04\x00")
    a.jcc(JE, "send_stock")
    a.emit(b"\x8b\x0d", u32(THE_MESSAGE_STREAM), b"\x8b\x01\x68", u32(MSG_CASTLE_UNPACK))
    a.emit(b"\xff\x50", APPEND_MESSAGE_VTABLE_SLOT, b"\x8b\xf0")
    a.emit(0x68, u32(COMMAND_MAGIC), b"\x8b\xce")
    a.call_absolute(GAME_MESSAGE_APPEND_INTEGER)
    a.emit(0x57, b"\x8b\xce")
    a.call_absolute(GAME_MESSAGE_APPEND_INTEGER)
    a.emit(0x61, 0x9D)
    a.jmp_absolute(CASTLE_COMMAND_SENDER_EXIT)
    a.label("send_stock")
    a.emit(0x61, 0x9D, COMMAND_HOOKS[CASTLE_COMMAND_SENDER][0])
    a.jmp_absolute(CASTLE_COMMAND_SENDER_STOCK_RESUME)

    a.label("receive")
    a.jcc(JE, "receive_fail")  # first instruction consumes retail TEST AL,AL unchanged
    a.emit(0x9C, 0x60, b"\x8b\x5d\x08\x85\xdb")
    a.jcc(JE, "receive_done")
    a.emit(b"\x80\x7b", GAME_MESSAGE_ARGUMENT_COUNT, 2)
    a.jcc(JB, "receive_done")
    for index in (0, 1):
        a.emit(0x6A, index, b"\x8b\xcb")
        a.call_absolute(GAME_MESSAGE_GET_ARGUMENT_TYPE)
        a.emit(b"\x85\xc0")
        a.jcc(JNE, "receive_done")
    a.emit(b"\x6a\x00\x8b\xcb")
    a.call_absolute(GAME_MESSAGE_GET_ARGUMENT_DATA)
    a.emit(b"\x81\x38", u32(COMMAND_MAGIC))
    a.jcc(JNE, "receive_done")
    a.emit(b"\x6a\x01\x8b\xcb")
    a.call_absolute(GAME_MESSAGE_GET_ARGUMENT_DATA)
    a.emit(b"\x8b\x18\x85\xdb")
    a.jcc(JE, "receive_done")
    a.emit(b"\x8b\xcb")
    a.call("find_prefab")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "receive_done")
    a.emit(b"\x39\x1a")
    a.jcc(JNE, "receive_done")
    a.emit(b"\x8b\x42\x04\x85\xc0")
    a.jcc(JE, "receive_done")
    a.emit(b"\x8b\xce")
    a.call_absolute(_emit(core).label_va("promote"))
    a.label("receive_done")
    a.emit(0x61, 0x9D)
    a.jmp_absolute(CASTLE_COMMAND_RECEIVER_RESUME)  # preserve shared 0x43F StartUnpack tail
    a.label("receive_fail")
    a.jmp_absolute(CASTLE_COMMAND_RECEIVER_FAIL)
    struct.pack_into("<IIII", a.buf, row_at, base + COMMAND_FIELD_OFF, a.label_va("parse"), 0, 0)
    return a


class CastlePrefabCommandButtonPatch(Patch):
    """Ordered extension: apply CastlePrefabPatch first; its verified core owns all overrides.

    Field tables compose using the active rows. The ctor, CASTLE_UNPACK sender and receiver
    windows are exclusive hooks; a second owner fails signature verification before any write.
    """

    name = "castle-prefab-commandbutton"
    author = "Ostkannit"
    experimental = True
    description = (
        "Add CastlePrefab = <BSE name> to CASTLE_UNPACK CommandButtons; requires castle-prefab"
    )

    @staticmethod
    def _core(data: bytes | bytearray) -> int:
        problems = CastlePrefabPatch().verify(data)
        located = find_section(data, SECTION_NAME)
        if problems or located is None:
            raise ValueError(
                "apply castle-prefab first (matching core required): " + "; ".join(problems)
            )
        return located[0]

    def apply(self, data: bytearray) -> None:
        core = self._core(data)
        _check(
            data,
            {
                **CASTLE_COMMAND_ANCHORS,
                COMMAND_BUTTON_CTOR: COMMAND_BUTTON_CTOR_BYTES,
                **{v: e[0] for v, e in COMMAND_HOOKS.items()},
            },
        )
        entries = _command_table(data)
        fields = {read_cstring(data, e[0]): e[3] for e in entries}
        if (
            fields.get("Command") != COMMAND_BUTTON_COMMAND
            or fields.get("Object") != COMMAND_BUTTON_OBJECT
        ):
            raise ValueError("unexpected CommandButton field layout")
        if COMMAND_FIELD in fields:
            raise ValueError("CommandButton CastlePrefab already exists: parser conflict")
        base = allocate_section(
            data,
            COMMAND_SECTION,
            lambda va: _command_emit(va, entries, core).finish(),
            _CHARACTERISTICS,
        )
        a = _command_emit(base, entries, core)
        for va, (stock, label) in COMMAND_HOOKS.items():
            apply_byte_patch(
                data,
                file_offset(data, va),
                stock,
                jmp_rel32(va, a.label_va(label), len(stock)),
                self.name,
            )
        for va, opcode in zip(
            COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = file_offset(data, va)
            apply_byte_patch(
                data,
                off,
                bytes(data[off : off + 5]),
                bytes([opcode]) + u32(base + COMMAND_TABLE_OFF),
                self.name,
            )

    def ini_surface(self) -> Engine:
        return Engine(fields=(FieldDelta("CommandButton", COMMAND_FIELD, "String", "", self.name),))

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, COMMAND_SECTION)
        if located is None:
            return [f"{COMMAND_SECTION} section is absent"]
        base, off, size = located
        try:
            core = self._core(data)
            live = _command_table(data)
            entries = entries_before(data, live, COMMAND_FIELD)
            if entries is None:
                return ["live CommandButton table lacks CastlePrefab"]
            a = _command_emit(base, entries, core)
            _check(
                data,
                {
                    **CASTLE_COMMAND_ANCHORS,
                    COMMAND_BUTTON_CTOR: COMMAND_BUTTON_CTOR_BYTES,
                    **{
                        va: jmp_rel32(va, a.label_va(label), len(stock))
                        for va, (stock, label) in COMMAND_HOOKS.items()
                    },
                },
            )
            expected_row = (base + COMMAND_FIELD_OFF, a.label_va("parse"), 0, 0)
            if live[len(entries)] != expected_row:
                return ["live CastlePrefab parser row differs"]
            expected = a.finish()
            if size < len(expected) or bytes(data[off : off + len(expected)]) != expected:
                return [f"{COMMAND_SECTION} code, table or initial state differs"]
        except (ValueError, struct.error) as exc:
            return [str(exc)]
        return []
