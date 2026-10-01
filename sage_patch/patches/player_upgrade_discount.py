"""Let `CostModifierUpgrade`'s `UpgradeDiscount` reduce the price of a `Type = PLAYER` upgrade.

Stock `UpgradeTemplate::calcCostToBuild` reads the discount only for `OBJECT` upgrades. Two edits
change that. The type branch becomes NOPs, so a PLAYER upgrade reaches the discount call (still
subject to its own `NoUpgradeDiscount`). The discount call then goes to a cave, which sends OBJECT
upgrades to the stock sum unchanged. For a PLAYER upgrade, the cave sums only the entries whose
`ApplyToTheseUpgrades` names it. An entry with no list keeps its stock meaning of every OBJECT
upgrade, so existing data prices nothing differently. A PLAYER upgrade is discounted only once a
module names it.

Every place a price is shown, checked, charged or refunded goes through `calcCostToBuild`, so
they all agree.

Derivation: `../docs/player-upgrade-discount.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    ASCII_STRING_DTOR,
    PLAYER_GET_UPGRADE_DISCOUNT,
    PLAYER_GET_UPGRADE_DISCOUNT_BODY,
    PLAYER_UPGRADE_DISCOUNTS,
    UPGRADE_DISCOUNT_CALL,
    UPGRADE_DISCOUNT_CALL_BYTES,
    UPGRADE_DISCOUNT_ENTRY_VALUE,
    UPGRADE_DISCOUNT_ENTRY_VALUE_ENTRY,
    UPGRADE_DISCOUNT_GATE,
    UPGRADE_DISCOUNT_GATE_BYTES,
    UPGRADE_DISCOUNT_TYPE_BRANCH,
    UPGRADE_DISCOUNT_TYPE_BRANCH_BYTES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "ENTRY_SIZE",
    "PlayerUpgradeDiscountPatch",
    "SECTION_NAME",
    "UPGRADE_TYPE_OBJECT",
    "build_code",
]

SECTION_NAME = ".plrdisc"  # 8 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: `UpgradeTemplate::Type`, from the name table at `0x00DA05C8`: 0 `PLAYER`, 1 `OBJECT`.
UPGRADE_TYPE_OBJECT = 1
#: The field's offset from the discount call's `esi`, which points at the name (`+0x08`).
_TYPE_FROM_NAME = 0x04 - 0x08

#: A discount entry's stride, and the `ApplyToTheseUpgrades` list's begin/end inside it.
ENTRY_SIZE = 0x24
_ENTRY_LIST_BEGIN = 0x14
_ENTRY_LIST_END = 0x18

#: The bytes each address the cave depends on must hold, as a `{va: bytes}` map. The gate block
#: is where the cave reads the `Type` field off `esi`. The whole stock sum is anchored because
#: the cave copies its loop and its layout: vector offsets, stride, and the argument's destructor.
ANCHORS = {
    UPGRADE_DISCOUNT_GATE: UPGRADE_DISCOUNT_GATE_BYTES,
    PLAYER_GET_UPGRADE_DISCOUNT: PLAYER_GET_UPGRADE_DISCOUNT_BODY,
    UPGRADE_DISCOUNT_ENTRY_VALUE: UPGRADE_DISCOUNT_ENTRY_VALUE_ENTRY,
}


def build_code(base_va: int) -> bytes:
    """`__thiscall(Player *)`, one `AsciiString` argument by value, `ret 4`, `st0` - the same
    contract as `PLAYER_GET_UPGRADE_DISCOUNT`, which it replaces at the one call site."""
    a = Asm(base_va)
    # `esi` is still the caller's: the upgrade's name, 8 bytes into its `UpgradeTemplate`.
    a.emit(0x83, 0x7E, _TYPE_FROM_NAME & 0xFF, UPGRADE_TYPE_OBJECT)  # cmp dword [esi-4], 1
    a.jcc(JNE, "player")
    a.jmp_absolute(PLAYER_GET_UPGRADE_DISCOUNT)  # OBJECT: the stock sum, stack untouched

    a.label("player")
    # The stock loop, with one extra test: an entry with an empty list does not apply here.
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x51)  # push ecx                  ; [ebp-4] = the running sum
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xF9)  # mov edi, ecx             ; the Player
    a.emit(0xC7, 0x45, 0xFC, struct.pack("<I", 0))  # mov dword [ebp-4], 0.0
    a.emit(0x8B, 0xB7, struct.pack("<I", PLAYER_UPGRADE_DISCOUNTS))  # mov esi, [edi+0x3d0]
    a.jmp_short("check")

    a.label("entry")
    a.emit(0x8B, 0x46, _ENTRY_LIST_BEGIN)  # mov eax, [esi+0x14]
    a.emit(0x3B, 0x46, _ENTRY_LIST_END)  # cmp eax, [esi+0x18]
    a.jcc_short(JE, "next")  # applies to every upgrade: OBJECT only
    a.emit(0x8D, 0x45, 0x08)  # lea eax, [ebp+8]         ; &name
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(UPGRADE_DISCOUNT_ENTRY_VALUE)
    a.emit(0xD8, 0x45, 0xFC)  # fadd dword [ebp-4]
    a.emit(0xD9, 0x5D, 0xFC)  # fstp dword [ebp-4]

    a.label("next")
    a.emit(0x83, 0xC6, ENTRY_SIZE)  # add esi, 0x24
    a.label("check")
    a.emit(0x3B, 0xB7, struct.pack("<I", PLAYER_UPGRADE_DISCOUNTS + 4))  # cmp esi, [edi+0x3d4]
    a.jcc_short(JNE, "entry")

    a.emit(0x8D, 0x4D, 0x08)  # lea ecx, [ebp+8]
    a.call_absolute(ASCII_STRING_DTOR)  # the argument is the callee's to destroy
    a.emit(0xD9, 0x45, 0xFC)  # fld dword [ebp-4]
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0xC9)  # leave
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a.finish()


def _call_to(va: int, target: int) -> bytes:
    return b"\xe8" + struct.pack("<i", target - (va + 5))


class PlayerUpgradeDiscountPatch(Patch):
    name = "player-upgrade-discount"
    author = "officialNecro"
    description = (
        "Let CostModifierUpgrade's UpgradeDiscount reduce the price of a Type = PLAYER upgrade, "
        "which the stock engine applies to OBJECT upgrades only. A PLAYER upgrade takes a "
        "discount only from a module whose ApplyToTheseUpgrades names it, so a module with no "
        "list still discounts OBJECT upgrades alone and existing data is priced as before. "
        "NoUpgradeDiscount = Yes opts a PLAYER upgrade out, as it does an OBJECT one"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            self._offset(data, UPGRADE_DISCOUNT_TYPE_BRANCH),
            UPGRADE_DISCOUNT_TYPE_BRANCH_BYTES,
            b"\x90" * len(UPGRADE_DISCOUNT_TYPE_BRANCH_BYTES),
            "calcCostToBuild OBJECT-only discount branch -> nop",
        )
        apply_byte_patch(
            data,
            self._offset(data, UPGRADE_DISCOUNT_CALL),
            UPGRADE_DISCOUNT_CALL_BYTES,
            _call_to(UPGRADE_DISCOUNT_CALL, section_va),
            "calcCostToBuild discount call -> player-upgrade-discount cave",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the upgrade "
                    "price code is not this build's, so the cave would read the wrong field or "
                    "walk the wrong list"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        problems: list[str] = []
        expected = {
            UPGRADE_DISCOUNT_TYPE_BRANCH: b"\x90" * len(UPGRADE_DISCOUNT_TYPE_BRANCH_BYTES),
            UPGRADE_DISCOUNT_CALL: _call_to(UPGRADE_DISCOUNT_CALL, section_va),
        }
        for va, want in expected.items():
            off = va_to_offset(data, va)
            if off is None:
                return [f"{va:#010x} is not mapped by any section"]
            if bytes(data[off : off + len(want)]) != want:
                problems.append(f"{va:#010x} does not hold the patched bytes")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected routine")
        return problems
