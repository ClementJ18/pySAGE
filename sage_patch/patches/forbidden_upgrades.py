"""Add `ForbiddenUpgrades` to `SpecialPower`: refuse a targeted cast near an object carrying one of
the listed upgrades.

The gate is in both targeted-cast predicates on `TheActionManager`
(`CAN_DO_SPECIAL_POWER_AT_LOCATION`, `CAN_DO_SPECIAL_POWER_AT_OBJECT`), whose callers are the
cursor, the AI and ability modules, so all three are refused alike. It reads only logic state.
Conflicts with `hero-mana` and `special-power-charges`, which grow `SpecialPowerTemplate` the same
way; each refuses the others before writing anything.

Derivation: `../docs/forbidden-upgrade-filter.md`.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    CAN_DO_SPECIAL_POWER_AT_OBJECT,
    FIELD_PARSE_STRIDE,
    GET_FINAL_OVERRIDE,
    INI_PARSE_UPGRADE_MASK,
    OBJECT_POSITION,
    OBJECT_UPGRADE_MASK,
    PARTITION_FILTER_DESTRUCTOR,
    PARTITION_FILTER_NOT_DESTROYED_VTABLE,
    PARTITION_FILTER_OBJECT_FILTER_VTABLE,
    PARTITION_FILTER_SLOT_2,
    PARTITION_GET_CLOSEST_OBJECT,
    PLAYER_COMPLETED_UPGRADE_MASK_WORDS,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    SPECIAL_POWER_FORBIDDEN_OBJECT_RANGE,
    SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL,
    SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL_BYTES,
    SPECIAL_POWER_FORBIDDEN_OBJECTS_CHECK,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
    SPECIAL_POWER_TEMPLATE_NEW_SITES,
    SPECIAL_POWER_TEMPLATE_SIZE,
    THE_PARTITION_MANAGER,
    UPGRADE_MASK_ANY,
    UPGRADE_MASK_TEST_ANY,
)
from ..asm import JBE, JE, JNE, Asm
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
    va_to_offset,
)
from .utils.field_tables import Entry, entries_before, read_field_table, resolve_table

__all__ = [
    "ANCHORS",
    "KEYWORD",
    "MASK_OFFSET",
    "MASK_SIZE",
    "NEW_TEMPLATE_SIZE",
    "OBJECT_GATE_CALL",
    "OBJECT_GATE_CALL_BYTES",
    "OBJECT_GATE_TARGET",
    "SECTION_NAME",
    "TEMPLATE_CTOR_TAIL",
    "TEMPLATE_CTOR_TAIL_BYTES",
    "TEMPLATE_CTOR_TAIL_RESUME",
    "ForbiddenUpgradesPatch",
    "build_table",
]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = ".spforbu"

#: CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE, as every cave here.
_CHARACTERISTICS = 0xE0000060

KEYWORD = "ForbiddenUpgrades"

#: The mask, appended past `UnitCostDeathType` at `+0x84`. One `UpgradeMaskType` is 36 dwords.
MASK_OFFSET = SPECIAL_POWER_TEMPLATE_SIZE
MASK_SIZE = PLAYER_COMPLETED_UPGRADE_MASK_WORDS * 4
NEW_TEMPLATE_SIZE = MASK_OFFSET + MASK_SIZE

#: The constructor's last field store, `mov dword [esi+0x84], ebx`, six bytes and not a branch
#: target. `esi` is the template and `ebx` is the constructor's zero throughout; `ecx` is
#: overwritten by the very next instruction (`mov ecx, esp`), so the cave may loop on it.
TEMPLATE_CTOR_TAIL = 0x007B200D
TEMPLATE_CTOR_TAIL_BYTES = bytes.fromhex("899e84000000")
TEMPLATE_CTOR_TAIL_RESUME = 0x007B2013

#: The object predicate's call to `0x0082C366` - `push ebx` (the caster) has already happened,
#: `ecx` is `TheActionManager`, and a true result is refused on (`jne` to the refuse arm). Every
#: earlier exit from the predicate is a refusal, so every cast that can still succeed passes here.
OBJECT_GATE_CALL = 0x0082DA69
OBJECT_GATE_CALL_BYTES = bytes.fromhex("e8f8e8ffff")
OBJECT_GATE_TARGET = 0x0082C366

#: The object predicate's frame slots the object wrapper reads: `ebp` is still the predicate's
#: frame pointer when it calls, and neither slot is written before the gate call.
_OBJECT_FRAME_TARGET = 0x0C
_OBJECT_FRAME_TEMPLATE = 0x14

JNS = 0x9

#: Everything the cave calls, copies or relies on the layout of, by address and first bytes. A
#: patch whose job is calling engine functions has no other way to notice one of them moved.
ANCHORS: dict[int, bytes] = {
    GET_FINAL_OVERRIDE: bytes.fromhex("8bc18b500485d274"),
    UPGRADE_MASK_ANY: bytes.fromhex("33c0833c81007509"),
    UPGRADE_MASK_TEST_ANY: bytes.fromhex("8b44240433d22bc1"),
    INI_PARSE_UPGRADE_MASK: bytes.fromhex("b86375b800e8e3d83c00"),
    SPECIAL_POWER_FORBIDDEN_OBJECTS_CHECK: bytes.fromhex("b816beb900e8e9fb2000"),
    OBJECT_GATE_TARGET: bytes.fromhex("558bec83ec0c833d404bde0000"),
    PARTITION_GET_CLOSEST_OBJECT: bytes.fromhex("8b4424108b54240c8b4910"),
    PARTITION_FILTER_DESTRUCTOR: bytes.fromhex("568bf1e8e9feffff"),
    PARTITION_FILTER_SLOT_2: bytes.fromhex("83c8ffc3"),
    # the not-destroyed head filter's `allow`: `!(candidate->status & DESTROYED)`
    0x00660E71: bytes.fromhex("8b4424048a8058040000f6d083e001c20400"),
    # both stock filter vtables, whose outer slots the cave's own vtable shares
    PARTITION_FILTER_NOT_DESTROYED_VTABLE: struct.pack(
        "<III", PARTITION_FILTER_DESTRUCTOR, 0x00660E71, PARTITION_FILTER_SLOT_2
    ),
    PARTITION_FILTER_OBJECT_FILTER_VTABLE: struct.pack(
        "<III", PARTITION_FILTER_DESTRUCTOR, 0x0066122D, PARTITION_FILTER_SLOT_2
    ),
    # the stock scan building its filter chain and calling getClosestObject(where, range, 1, head)
    0x0082D33B: bytes.fromhex("c745d8c84cbe00"),
    0x0082D352: bytes.fromhex("c745ec200ec100"),
    0x0082D37B: bytes.fromhex("6a01518b0d5443de00d91c24ff750ce8"),
    # the object predicate reading the two frame slots the object wrapper reads
    CAN_DO_SPECIAL_POWER_AT_OBJECT + 0x0E: bytes.fromhex("8b7d14"),
    0x0082D9AA: bytes.fromhex("8b750c"),
}

#: What the `SpecialPower` field table has to say before this patch touches it.
FINGERPRINT: dict[str, int] = {
    "ForbiddenObjectRange": SPECIAL_POWER_FORBIDDEN_OBJECT_RANGE,
    "UnitCost": 0x80,
    "UnitCostDeathType": 0x84,
}


def build_table(entries: tuple[Entry, ...], keyword_va: int) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the new row, the terminator. The
    live rows are copied rather than rewritten because every pointer in them is absolute."""
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", keyword_va, INI_PARSE_UPGRADE_MASK, 0, MASK_OFFSET)
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.


def _emit_allow(a: Asm) -> None:
    """`Bool allow(Object *candidate)` - `__thiscall` on the cave's filter, `ret 4`: does
    the candidate carry any upgrade in the mask at `[this+8]`?"""
    a.label("allow")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]              ; the candidate
    a.emit(0xFF, 0x71, 0x08)  # push dword [ecx+8]                  ; the mask
    a.emit(0x8D, 0x88, u32(OBJECT_UPGRADE_MASK))  # lea ecx, [eax+0x28c]
    a.call_absolute(UPGRADE_MASK_TEST_ANY)  # call testForAny   ; ret 4, al
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_ctor(a: Asm) -> None:
    """The constructor tail: replay the displaced store, then zero the mask from its top dword
    down, `ecx` counting the byte offset within it."""
    a.label("ctor")
    a.emit(TEMPLATE_CTOR_TAIL_BYTES)  # mov [esi+0x84], ebx         ; the displaced store
    a.emit(0xB9, u32(MASK_SIZE - 4))  # mov ecx, 0x8c
    a.label("ctor_loop")
    a.emit(0x89, 0x9C, 0x0E, u32(MASK_OFFSET))  # mov [esi+ecx+0x88], ebx   ; ebx is zero
    a.emit(0x83, 0xE9, 0x04)  # sub ecx, 4
    a.jcc_short(JNS, "ctor_loop")
    a.jmp_absolute(TEMPLATE_CTOR_TAIL_RESUME)


def _emit_copy(a: Asm) -> None:
    """The copy-constructor tail. `ebp` is the *source* template here, `ebx` the destination, and
    `edi` has already been restored - so the loop runs on `ecx` and `eax`, which the displaced
    epilogue overwrites anyway."""
    a.label("copy")
    a.emit(0xB9, u32(MASK_SIZE - 4))  # mov ecx, 0x8c
    a.label("copy_loop")
    a.emit(0x8B, 0x84, 0x0D, u32(MASK_OFFSET))  # mov eax, [ebp+ecx+0x88]
    a.emit(0x89, 0x84, 0x0B, u32(MASK_OFFSET))  # mov [ebx+ecx+0x88], eax
    a.emit(0x83, 0xE9, 0x04)  # sub ecx, 4
    a.jcc_short(JNS, "copy_loop")
    a.emit(SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES)  # mov eax, ebx / pops / ret 4


def _emit_check(a: Asm) -> None:
    """`Bool forbidden(Object *target, Coord3D *where, SpecialPowerTemplate *)` - stdcall,
    `ret 0xc`, `al = 1` when the key refuses the cast. `target` may be NULL (a location
    cast). Preserves `ebx`, `esi` and `edi`.

        t = getFinalOverride(template); mask = &t->ForbiddenUpgrades
        if !mask.any():                                   allowed
        if target and target->upgrades.testForAny(mask): forbidden
        if !(t->ForbiddenObjectRange > 0):                allowed
        head = {NotDestroyed, &f};  f = {this cave's filter, NULL, mask}
        forbidden = ThePartitionManager->getClosestObject(where, range, 1, &head) != NULL
    """
    a.label("check")
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    # [esp+0x10] = target, [esp+0x14] = where, [esp+0x18] = template
    a.emit(0x8B, 0x4C, 0x24, 0x18)  # mov ecx, [esp+0x18]
    a.call_absolute(GET_FINAL_OVERRIDE)  # eax = the template an override chain ends at
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.emit(0x8D, 0xBE, u32(MASK_OFFSET))  # lea edi, [esi+0x88]       ; the mask
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(UPGRADE_MASK_ANY)  # al = any bit set
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "check_allowed")  # an empty list is stock behaviour

    a.emit(0x8B, 0x44, 0x24, 0x10)  # mov eax, [esp+0x10]           ; target
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "check_area")
    a.emit(0x57)  # push edi                                          ; the mask
    a.emit(0x8D, 0x88, u32(OBJECT_UPGRADE_MASK))  # lea ecx, [eax+0x28c]
    a.call_absolute(UPGRADE_MASK_TEST_ANY)  # ret 4
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "check_forbidden")

    a.label("check_area")
    a.emit(0xF3, 0x0F, 0x10, 0x46, SPECIAL_POWER_FORBIDDEN_OBJECT_RANGE)  # movss xmm0, [esi+0x7c]
    a.emit(0x0F, 0x57, 0xC9)  # xorps xmm1, xmm1
    a.emit(0x0F, 0x2F, 0xC1)  # comiss xmm0, xmm1
    a.jcc(JBE, "check_allowed")  # no range (or NaN): no area to scan

    # Two filters on the stack, chained head -> ours:
    #   [esp+0x00] head.vtable = not-destroyed  [esp+0x04] head.next = &ours
    #   [esp+0x08] ours.vtable = this cave's    [esp+0x0c] ours.next = NULL
    #   [esp+0x10] ours.mask
    a.emit(0x83, 0xEC, 0x14)  # sub esp, 0x14
    a.emit(0xC7, 0x04, 0x24, u32(PARTITION_FILTER_NOT_DESTROYED_VTABLE))  # mov [esp], vtable
    a.emit(0x8D, 0x44, 0x24, 0x08)  # lea eax, [esp+8]
    a.emit(0x89, 0x44, 0x24, 0x04)  # mov [esp+4], eax
    a.emit(0xC7, 0x44, 0x24, 0x08, u32(a.label_va("vtable")))  # mov [esp+8], our vtable
    a.emit(0xC7, 0x44, 0x24, 0x0C, u32(0))  # mov [esp+0xc], 0
    a.emit(0x89, 0x7C, 0x24, 0x10)  # mov [esp+0x10], edi
    a.emit(0x8B, 0xC4)  # mov eax, esp                                ; &head
    a.emit(0x50)  # push eax                                          ; filters
    a.emit(0x6A, 0x01)  # push 1                                      ; distType, as stock
    a.emit(0xFF, 0x76, SPECIAL_POWER_FORBIDDEN_OBJECT_RANGE)  # push [esi+0x7c]   ; range
    a.emit(0xFF, 0x74, 0x24, 0x34)  # push [esp+0x34]                 ; where
    a.emit(0x8B, 0x0D, u32(THE_PARTITION_MANAGER))  # mov ecx, [ThePartitionManager]
    a.call_absolute(PARTITION_GET_CLOSEST_OBJECT)  # ret 0x10, eax = Object* or NULL
    a.emit(0x83, 0xC4, 0x14)  # add esp, 0x14
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JNE, "check_forbidden")

    a.label("check_allowed")
    a.emit(0x32, 0xC0)  # xor al, al
    a.jmp_short("check_out")
    a.label("check_forbidden")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.label("check_out")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc


def _emit_location_gate(a: Asm) -> None:
    """Stands in for the location predicate's `call` to its forbidden scan: same arguments
    `(caster, where, template)`, same `ret 0xc`, `ecx` still `TheActionManager` for the stock
    scan it calls first. `al = 1` means allowed, as the stock scan's does."""
    a.label("location_gate")
    for _ in range(3):
        a.emit(0xFF, 0x74, 0x24, 0x0C)  # push [esp+0xc]            ; template, where, caster
    a.call_absolute(SPECIAL_POWER_FORBIDDEN_OBJECTS_CHECK)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "location_gate_out")  # the stock refusal stands
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push [esp+0xc]                ; template
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push [esp+0xc]                ; where
    a.emit(0x6A, 0x00)  # push 0                                      ; no target
    a.call("check")
    a.emit(0x34, 0x01)  # xor al, 1                                   ; forbidden -> refused
    a.label("location_gate_out")
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc


def _emit_object_gate(a: Asm) -> None:
    """Stands in for the object predicate's `call 0x0082C366`: one argument, `ret 4`, and a
    true result refuses the cast - so the wrapper returns the stock true unchanged and otherwise
    answers whether this key forbids the target."""
    a.label("object_gate")
    a.emit(0xFF, 0x74, 0x24, 0x04)  # push [esp+4]                  ; the caster
    a.call_absolute(OBJECT_GATE_TARGET)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JNE, "object_gate_out")  # the stock refusal stands
    a.emit(0x8B, 0x45, _OBJECT_FRAME_TARGET)  # mov eax, [ebp+0xc]  ; the predicate's target
    a.emit(0x85, 0xC0)  # test eax, eax                               ; al is already 0
    a.jcc_short(JE, "object_gate_out")
    a.emit(0xFF, 0x75, _OBJECT_FRAME_TEMPLATE)  # push [ebp+0x14]      ; template
    a.emit(0x8D, 0x50, OBJECT_POSITION)  # lea edx, [eax+0x38]         ; where = its position
    a.emit(0x52)  # push edx
    a.emit(0x50)  # push eax                                          ; target
    a.call("check")
    a.label("object_gate_out")
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit(a: Asm, entries: tuple[Entry, ...]) -> None:
    """The whole cave. Data first, and the filter's `allow` ahead of its vtable, so everything
    that names an address by value can ask `Asm.label_va` for one already placed."""
    a.label("keyword")
    a.emit(KEYWORD.encode("ascii") + b"\x00")
    while len(a.buf) % 4:
        a.emit(0x00)
    a.label("table")
    a.emit(build_table(entries, a.label_va("keyword")))

    _emit_allow(a)
    while len(a.buf) % 4:
        a.emit(0xCC)
    a.label("vtable")
    a.emit(
        struct.pack(
            "<III", PARTITION_FILTER_DESTRUCTOR, a.label_va("allow"), PARTITION_FILTER_SLOT_2
        )
    )

    _emit_ctor(a)
    _emit_copy(a)
    _emit_check(a)
    _emit_location_gate(a)
    _emit_object_gate(a)


class ForbiddenUpgradesPatch(Patch):
    """Refuse a targeted special power near, or on, an object carrying a listed upgrade."""

    name = "forbidden-upgrades"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "SpecialPower ForbiddenUpgrades = <Upgrade> ... refuses a targeted cast when any object "
        "within ForbiddenObjectRange of the cast point carries one of the listed upgrades as an "
        "object upgrade, the caster included; an object-targeted cast is also refused when the "
        "target itself carries one. Players, the AI and ability modules are all refused the same "
        "way. A power that does not set the key is unaffected"
    )

    def apply(self, data: bytearray) -> None:
        # Before the anchors, because applying rewrites bytes several of them cover: a second run
        # would otherwise fail as "not the build", which is true of the bytes and misleading.
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(
                f"this image already carries a {SECTION_NAME} section - the patch is already "
                "applied, and applying it twice would install a second copy of the field"
            )
        self._check_anchors(data)
        entries = self._check_table(data, self._resolve(data))

        base_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base: self._assemble(base, entries).finish(),
            _CHARACTERISTICS,
        )
        for file_off, old, new, note in self._edits(data, base_va, entries):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _assemble(base_va: int, entries: tuple[Entry, ...]) -> Asm:
        a = Asm(base_va)
        _emit(a, entries)
        a.finish()  # resolve the internal branches, so `label_va` describes a real layout
        return a

    @staticmethod
    def _sites(a: Asm) -> list[tuple[int, bytes, bytes, str]]:
        """Every hook, as `(va, stock bytes, patched bytes, note)` - one list, so `apply` writes
        exactly what `verify` asserts."""
        return [
            (
                TEMPLATE_CTOR_TAIL,
                TEMPLATE_CTOR_TAIL_BYTES,
                jmp_rel32(TEMPLATE_CTOR_TAIL, a.label_va("ctor"), 6),
                "SpecialPowerTemplate ctor -> the mask starts empty",
            ),
            (
                SPECIAL_POWER_TEMPLATE_COPY_TAIL,
                SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
                jmp_rel32(SPECIAL_POWER_TEMPLATE_COPY_TAIL, a.label_va("copy"), 8),
                "SpecialPowerTemplate copy ctor -> the mask is copied",
            ),
            (
                SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL,
                SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL_BYTES,
                call_rel32(SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL, a.label_va("location_gate")),
                "canDoSpecialPowerAtLocation's forbidden scan -> the location gate",
            ),
            (
                OBJECT_GATE_CALL,
                OBJECT_GATE_CALL_BYTES,
                call_rel32(OBJECT_GATE_CALL, a.label_va("object_gate")),
                "canDoSpecialPowerAtObject's gate call -> the object gate",
            ),
        ] + [
            (
                push_va,
                b"\x68" + u32(SPECIAL_POWER_TEMPLATE_SIZE),
                b"\x68" + u32(NEW_TEMPLATE_SIZE),
                f"SpecialPowerTemplate allocation 0x{push_va:08x} -> 0x{NEW_TEMPLATE_SIZE:x}",
            )
            for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES
        ]

    def _edits(
        self, data: bytes | bytearray, base_va: int, entries: tuple[Entry, ...]
    ) -> list[tuple[int, bytes, bytes, str]]:
        a = self._assemble(base_va, entries)
        edits = [(file_offset(data, va), old, new, note) for va, old, new, note in self._sites(a)]
        table_ref = u32(a.label_va("table"))
        for ref_va, opcode in zip(
            SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = file_offset(data, ref_va)
            edits.append(
                (
                    off,
                    bytes(data[off : off + 5]),
                    bytes([opcode]) + table_ref,
                    f"SpecialPower field table reference 0x{ref_va:08x} -> {SECTION_NAME}",
                )
            )
        return edits

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """The `SpecialPower` field table's base VA as the image currently holds it, so the patch
        appends to whatever is live."""
        return resolve_table(
            data,
            SPECIAL_POWER_FIELD_TABLE_REFS,
            SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
            "SpecialPower",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, want in ANCHORS.items():
            off = va_to_offset(data, va)
            got = None if off is None else bytes(data[off : off + len(want)])
            if got != want:
                raise ValueError(
                    f"0x{va:08x} holds {'nothing mapped' if got is None else got.hex()}, expected "
                    f"{want.hex()} - this is not the build this patch was derived against"
                )

    @staticmethod
    def _check_table(data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        """The live rows, once the table has been checked for the build, for the keyword and for
        anything that has already grown the struct - a duplicate row would parse, since the reader
        takes the first match, and the field would silently do nothing."""
        entries = read_field_table(data, table_va)
        by_name = {read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, want in FINGERPRINT.items():
            got = by_name.get(field)
            if got != want:
                raise ValueError(
                    f"unexpected build: SpecialPower.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        if KEYWORD in by_name:
            raise ValueError(
                f"SpecialPower already has a {KEYWORD!r} field - this patch is already applied, "
                "or another patch has added the same field"
            )
        highest = max(offset for _n, _f, _u, offset in entries)
        if highest >= MASK_OFFSET:
            raise ValueError(
                f"the SpecialPower table already uses offset {highest:#x}, at or past the "
                f"{MASK_OFFSET:#x} this patch adds - another patch has already grown "
                "SpecialPowerTemplate (hero-mana and special-power-charges do)"
            )
        for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
            off = file_offset(data, push_va)
            allocation = bytes(data[off : off + 5])
            if allocation != b"\x68" + u32(SPECIAL_POWER_TEMPLATE_SIZE):
                raise ValueError(
                    f"the SpecialPowerTemplate allocation at 0x{push_va:08x} holds "
                    f"{allocation.hex()}, not a push of {SPECIAL_POWER_TEMPLATE_SIZE:#x} - the "
                    "struct has already been grown, or this is not the expected build"
                )
        return entries

    def ini_surface(self) -> Engine:
        """The one field this patch adds. The constructor empties the mask, so an absent key is
        an empty list, which is stock behaviour."""
        return Engine(
            fields=(FieldDelta("SpecialPower", KEYWORD, "Ref[]:upgrades", None, self.name),)
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch, reading only via `struct` and the
        section table. Every address is recovered from where the cave actually landed."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located
        try:
            live = read_field_table(data, self._resolve(data))
            preceding = entries_before(data, live, KEYWORD)
            if preceding is None:
                return [f"the live SpecialPower table does not name {KEYWORD!r}"]
            a = self._assemble(section_va, preceding)
            code = a.finish()
            if len(code) > vsize:
                return [f"{SECTION_NAME} holds {vsize} bytes, too few for the table and routines"]
            cave_off = file_offset(data, section_va)
            if bytes(data[cave_off : cave_off + len(code)]) != code:
                return [f"the {SECTION_NAME} cave is not what this patch builds"]
            problems = self._verify_live_row(data, live, a)
            for va, _old, want, note in self._sites(a):
                off = file_offset(data, va)
                got = bytes(data[off : off + len(want)])
                if got != want:
                    problems.append(f"@0x{va:08x}: not hooked - {note} (holds {got.hex()})")
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the patch (wrong build?): {exc}"]
        return problems

    @staticmethod
    def _verify_live_row(data: bytes | bytearray, live: tuple[Entry, ...], a: Asm) -> list[str]:
        """The field is still parsed out of whatever table the engine now reads. Deliberately not
        "the references name this cave's table": a later patch that rebuilds the table copies this
        row into its own and repoints the references there."""
        row = next((entry for entry in live if read_cstring(data, entry[0]) == KEYWORD), None)
        if row is None:
            return [f"the live SpecialPower table no longer parses {KEYWORD!r}"]
        want = (a.label_va("keyword"), INI_PARSE_UPGRADE_MASK, MASK_OFFSET)
        if (row[0], row[1], row[3]) != want:
            return [
                f"the live {KEYWORD!r} row is not this patch's field at SpecialPower+"
                f"0x{MASK_OFFSET:02x} (holds name 0x{row[0]:08x}, fn 0x{row[1]:08x}, "
                f"offset 0x{row[3]:02x})"
            ]
        return []
