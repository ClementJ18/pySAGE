"""Make `DrainLife` heal for every hit a `DamageNugget` deals: delayed hits and every DOT tick.

Stock `DamageNugget::doDamage` calls `target->attemptDamage(info)` and then heals the source by
`DrainLifeMultiplier` times the damage that call dealt. Two kinds of hit never get there:

- **`DelayTime`.** `attemptDamage` queues a damage with a delay on the target and returns at once,
  having dealt nothing, so the drain heals for zero. The queued hit lands later, from the target's
  delayed-damage list, with no drain.
- **`DOTNugget`.** Its first hit goes through `doDamage` and drains. Every later tick comes from
  the DOT manager, which calls `attemptDamage` on its stored `DamageInfo` directly, with no drain.

The patch moves the drain to where damage is actually dealt. The multiplier travels in the
`DamageInfo` itself, in three padding bytes after the input's Bool at input `+0x4C`. Three
same-length edits make those bytes a real field: the input constructor zeroes them, and the copy
constructor and the assignment copy them, so the delayed list's queued copy and the DOT manager's
stored entry (which it assigns, never copy-constructs) carry them. `doDamage`
and `DOTNugget::doDamage` stamp the multiplier there when `DrainLife` is set. The two calls that
apply a hit to a body (immediate, and a delay running out) go through `damage_now`, which applies
the hit and then heals the source exactly as the stock drain did. The stock drain after
`attemptDamage` is skipped, so an immediate hit heals once.

The multiplier is stored as the top 24 bits of its float, so the drain reads it back with the low
mantissa byte cleared (about five significant digits). Logic-side: every peer needs the same
binary. No INI change.

Derivation: `../docs/drain-life-fix.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE,
    DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE_BYTES,
    DAMAGE_INFO_DAMAGE_DEALT,
    DAMAGE_INFO_DAMAGE_TYPE,
    DAMAGE_INFO_INPUT_COPY_BYTE_MOVE,
    DAMAGE_INFO_INPUT_COPY_BYTE_MOVE_BYTES,
    DAMAGE_INFO_INPUT_CTOR_BYTE_STORE,
    DAMAGE_INFO_INPUT_CTOR_BYTE_STORE_BYTES,
    DAMAGE_INFO_PAD_DWORD,
    DAMAGE_INFO_SOURCE_ID,
    DAMAGE_NUGGET_ATTEMPT_CALL,
    DAMAGE_NUGGET_ATTEMPT_CALL_BYTES,
    DAMAGE_NUGGET_DRAIN,
    DAMAGE_NUGGET_DRAIN_BYTES,
    DAMAGE_NUGGET_DRAIN_LIFE,
    DAMAGE_NUGGET_DRAIN_LIFE_MULTIPLIER,
    DAMAGE_NUGGET_DRAIN_SKIP,
    DAMAGE_NUGGET_DRAIN_SKIP_BYTES,
    DAMAGE_TYPE_HEALING,
    DOT_MANAGER_ADD,
    DOT_NUGGET_ADD_CALL,
    DOT_NUGGET_ADD_CALL_BYTES,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    KINDOF_PROJECTILE_BYTE,
    KINDOF_PROJECTILE_MASK,
    OBJECT_ATTEMPT_DAMAGE,
    OBJECT_ATTEMPT_DAMAGE_NOW_CALL,
    OBJECT_ATTEMPT_DAMAGE_NOW_CALL_BYTES,
    OBJECT_ATTEMPT_HEALING,
    OBJECT_ATTEMPT_HEALING_ENTRY,
    OBJECT_DAMAGE_NOW,
    OBJECT_DAMAGE_NOW_ENTRY,
    OBJECT_DELAYED_DAMAGE_NOW_CALL,
    OBJECT_DELAYED_DAMAGE_NOW_CALL_BYTES,
    OBJECT_THING_TEMPLATE,
    THE_GAME_LOGIC,
)
from ..asm import JE, JNE, JP, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section, u32

__all__ = [
    "ANCHORS",
    "SECTION_NAME",
    "STOCK_WINDOWS",
    "DrainLifeFixPatch",
    "build_section",
    "layout",
    "pack_multiplier",
    "unpack_multiplier",
]

SECTION_NAME = ".drain"

#: Read, never rewritten: the routines the cave calls, and the stock drain it makes unreachable
#: (pinned whole, so the reading of what it does is checked on every apply).
ANCHORS: dict[int, bytes] = {
    OBJECT_DAMAGE_NOW: OBJECT_DAMAGE_NOW_ENTRY,
    GAME_LOGIC_FIND_OBJECT_BY_ID: GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    OBJECT_ATTEMPT_HEALING: OBJECT_ATTEMPT_HEALING_ENTRY,
    DAMAGE_NUGGET_DRAIN: DAMAGE_NUGGET_DRAIN_BYTES,
}

# CNT_CODE | MEM_EXECUTE | MEM_READ
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def pack_multiplier(value: float) -> int:
    """The dword the stamp leaves at `DamageInfo+0x50`, low byte (the input's Bool) aside."""
    return struct.unpack("<I", struct.pack("<f", value))[0] & 0xFFFFFF00


def unpack_multiplier(dword: int) -> float:
    """What `damage_now` reads back from that dword."""
    return struct.unpack("<f", struct.pack("<I", dword & 0xFFFFFF00))[0]


def _stamp(a: Asm, info: int) -> None:
    """With `esi` the nugget and the `DamageInfo *` at `[esp+info]`: when `DrainLife` is set, write
    the multiplier's top 24 bits over the padding, keeping the Bool in the low byte."""
    a.emit(0x80, 0xBE, u32(DAMAGE_NUGGET_DRAIN_LIFE), 0x00)  # cmp byte [esi+0x1b4], 0
    a.jcc(JE, f"stamp_done_{info}")
    a.emit(0x8B, 0x54, 0x24, info)  # mov edx, [esp+info]
    a.emit(0x8B, 0x86, u32(DAMAGE_NUGGET_DRAIN_LIFE_MULTIPLIER))  # mov eax, [esi+0x1b8]
    a.emit(0x8A, 0x42, DAMAGE_INFO_PAD_DWORD)  # mov al, [edx+0x50]   ; keep the Bool
    a.emit(0x89, 0x42, DAMAGE_INFO_PAD_DWORD)  # mov [edx+0x50], eax
    a.label(f"stamp_done_{info}")


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)

    # stamp_attempt: stands in for `doDamage`'s `target->attemptDamage(info)`, `ecx` the target,
    # `esi` the nugget. Stamps, then tail-jumps, so the stock routine returns to the caller.
    a.label("stamp_attempt")
    _stamp(a, 4)
    a.jmp_absolute(OBJECT_ATTEMPT_DAMAGE)

    # stamp_dot: stands in for `DOTNugget::doDamage`'s `manager->add(targetID, entry)`, the entry
    # starting with its `DamageInfo`; `esi` the nugget.
    a.label("stamp_dot")
    _stamp(a, 8)
    a.jmp_absolute(DOT_MANAGER_ADD)

    # damage_now(info): `__thiscall` on the target, `ret 4`, standing in for the body-damage step.
    # Clears the output's damage dealt (a DOT reuses one DamageInfo for every tick), applies the
    # hit, then drains as the stock code did: not for healing damage, not for a zero amount, not
    # to a missing or PROJECTILE source, through `source->attemptHealing(amount, NULL)`.
    a.label("damage_now")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x74, 0x24, 0x08)  # mov esi, [esp+8]      ; info
    a.emit(0x83, 0x66, DAMAGE_INFO_DAMAGE_DEALT, 0x00)  # and dword [esi+0x70], 0
    a.emit(0x56)  # push esi
    a.call_absolute(OBJECT_DAMAGE_NOW)  # ecx is still the target
    a.emit(0x8B, 0x46, DAMAGE_INFO_PAD_DWORD)  # mov eax, [esi+0x50]
    a.emit(0x32, 0xC0)  # xor al, al                   ; the Bool is not part of the multiplier
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x83, 0x7E, DAMAGE_INFO_DAMAGE_TYPE, DAMAGE_TYPE_HEALING)  # cmp dword [esi+0x10], 7
    a.jcc(JE, "done")
    a.emit(0x66, 0x0F, 0x6E, 0xC0)  # movd xmm0, eax
    a.emit(0xF3, 0x0F, 0x59, 0x46, DAMAGE_INFO_DAMAGE_DEALT)  # mulss xmm0, [esi+0x70]
    a.emit(0x0F, 0x57, 0xC9)  # xorps xmm1, xmm1
    a.emit(0x0F, 0x2E, 0xC1)  # ucomiss xmm0, xmm1
    a.jcc(JP, "done")  # NaN
    a.jcc(JE, "done")  # nothing to give
    a.emit(0x83, 0xEC, 0x04)  # sub esp, 4
    a.emit(0xF3, 0x0F, 0x11, 0x04, 0x24)  # movss [esp], xmm0  ; parked across the lookup
    a.emit(0xFF, 0x76, DAMAGE_INFO_SOURCE_ID)  # push [esi+8]
    a.emit(0x8B, 0x0D, u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(GAME_LOGIC_FIND_OBJECT_BY_ID)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "drop")
    a.emit(0x8B, 0x48, OBJECT_THING_TEMPLATE)  # mov ecx, [eax+4]
    a.emit(0xF6, 0x81, u32(KINDOF_PROJECTILE_BYTE), KINDOF_PROJECTILE_MASK)  # test [ecx+0x10b], 2
    a.jcc(JNE, "drop")
    a.emit(0xF3, 0x0F, 0x10, 0x04, 0x24)  # movss xmm0, [esp]
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x83, 0xEC, 0x04)  # sub esp, 4
    a.emit(0xF3, 0x0F, 0x11, 0x04, 0x24)  # movss [esp], xmm0
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(OBJECT_ATTEMPT_HEALING)
    a.label("drop")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.label("done")
    a.emit(0x5E)  # pop esi
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a


_ROUTINES = ("stamp_attempt", "stamp_dot", "damage_now")


def build_section(base_va: int) -> bytes:
    return _assemble(base_va).finish()


def layout(base_va: int) -> dict[str, int]:
    a = _assemble(base_va)
    return {name: a.label_va(name) for name in _ROUTINES}


def _edits(base_va: int) -> list[tuple[int, bytes, bytes, str]]:
    """Every in-place edit as `(va, stock, replacement, note)`."""
    at = layout(base_va)
    return [
        (
            DAMAGE_INFO_INPUT_CTOR_BYTE_STORE,
            DAMAGE_INFO_INPUT_CTOR_BYTE_STORE_BYTES,
            bytes.fromhex("89484c"),  # mov [eax+0x4c], ecx  (ecx zero)
            "DamageInfoInput ctor -> zero the padding after +0x4C too",
        ),
        (
            DAMAGE_INFO_INPUT_COPY_BYTE_MOVE,
            DAMAGE_INFO_INPUT_COPY_BYTE_MOVE_BYTES,
            bytes.fromhex("8b514c89504c"),  # mov edx, [ecx+0x4c] / mov [eax+0x4c], edx
            "DamageInfoInput copy -> copy the padding after +0x4C too",
        ),
        (
            DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE,
            DAMAGE_INFO_INPUT_ASSIGN_BYTE_MOVE_BYTES,
            bytes.fromhex("8b514c89504c"),  # mov edx, [ecx+0x4c] / mov [eax+0x4c], edx
            "DamageInfoInput assignment -> copy the padding after +0x4C too (the DOT store)",
        ),
        (
            DAMAGE_NUGGET_ATTEMPT_CALL,
            DAMAGE_NUGGET_ATTEMPT_CALL_BYTES,
            call_rel32(DAMAGE_NUGGET_ATTEMPT_CALL, at["stamp_attempt"]),
            "DamageNugget::doDamage -> stamp the drain into the DamageInfo",
        ),
        (
            DAMAGE_NUGGET_DRAIN_SKIP,
            DAMAGE_NUGGET_DRAIN_SKIP_BYTES,
            b"\xeb" + DAMAGE_NUGGET_DRAIN_SKIP_BYTES[1:],  # je -> jmp
            "DamageNugget::doDamage -> skip the stock drain (damage_now does it)",
        ),
        (
            DOT_NUGGET_ADD_CALL,
            DOT_NUGGET_ADD_CALL_BYTES,
            call_rel32(DOT_NUGGET_ADD_CALL, at["stamp_dot"]),
            "DOTNugget::doDamage -> stamp the drain into the stored DamageInfo",
        ),
        (
            OBJECT_ATTEMPT_DAMAGE_NOW_CALL,
            OBJECT_ATTEMPT_DAMAGE_NOW_CALL_BYTES,
            call_rel32(OBJECT_ATTEMPT_DAMAGE_NOW_CALL, at["damage_now"]),
            "Object::attemptDamage immediate hit -> drain after it",
        ),
        (
            OBJECT_DELAYED_DAMAGE_NOW_CALL,
            OBJECT_DELAYED_DAMAGE_NOW_CALL_BYTES,
            call_rel32(OBJECT_DELAYED_DAMAGE_NOW_CALL, at["damage_now"]),
            "Object delayed damage landing -> drain after it",
        ),
    ]


#: Every rewritten window, stock bytes: what an image must hold for the patch to apply.
STOCK_WINDOWS: dict[int, bytes] = {va: stock for va, stock, _new, _note in _edits(0)}


class DrainLifeFixPatch(Patch):
    name = "drain-life-fix"
    author = "officialNecro"
    description = (
        "Make DamageNugget DrainLife heal for every hit: with DelayTime the stock drain heals for "
        "nothing (the hit is only queued), and a DOTNugget drains on its first tick only. The "
        "drain now happens when each hit lands, with the same rules as stock. Logic-side: every "
        "peer needs the same binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in ANCHORS.items():
            self._check_stock(data, va, expected)
        for va, stock, _new, _note in _edits(0):  # the stock half does not depend on the base
            self._check_stock(data, va, stock)
        base_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        for va, stock, new, note in _edits(base_va):
            apply_byte_patch(data, file_offset(data, va), stock, new, note)

    @staticmethod
    def _check_stock(data: bytes | bytearray, va: int, expected: bytes) -> None:
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the file is not "
                "the expected build, or already carries this patch"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, section_off, vsize = located
        problems: list[str] = []
        expected = build_section(base_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if vsize < len(expected) or got != expected:
            problems.append(f"the {SECTION_NAME} cave is not the one this patch builds")
        for va, _stock, new, note in _edits(base_va):
            off = file_offset(data, va)
            here = bytes(data[off : off + len(new)])
            if here != new:
                problems.append(f"@{va:#010x}: {note} is not installed (holds {here.hex()})")
        return problems
