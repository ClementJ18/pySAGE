"""Make `PickupStuffUpdate` enter a slaughter contain instead of walking up to it.

`PickupStuffUpdate` scans `ScanRange` every `ScanIntervalSeconds` for the nearest object matching
`StuffToPickUp`, and orders its owner to move to it. That is how the skirmish AI walks a hero to
the One Ring: the hero's own contain collects the Ring on contact. Pointed at a building, the same
move leaves the unit standing at the wall.

The patch replaces the order's one `call aiMoveToObject` with a call into a cave taking the same
arguments. When any contain module on the target answers "I slaughter what enters me" -
`SlaughterHordeContain`, `CitadelSlaughterHordeContain` - the cave orders `aiEnter` instead, so the
unit goes in and is paid out. Every other target gets the stock move, so the Ring, crates and
anything without a contain behave as before.

Every contain module is asked, not only the one at `OBJECT_CONTAIN`, so with `multi-contain` a
slaughter contain declared ahead of a `TunnelContain` is found too. Without it, the enter goes to
the stored contain, which refuses the rider, and the unit is left where a move would have left it.

Logic-side: every peer needs the same binary. Derivation: `../docs/pickup-stuff-enter.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_ENTER,
    AI_ENTER_ENTRY,
    AI_ENTER_TYPE_PUSH,
    AI_ENTER_TYPE_PUSH_BYTES,
    AI_MOVE_TO_OBJECT,
    AI_MOVE_TO_OBJECT_ENTRY,
    AI_MOVE_TO_OBJECT_TYPE_PUSH,
    AI_MOVE_TO_OBJECT_TYPE_PUSH_BYTES,
    BEHAVIOR_GET_CONTAIN_SLOT,
    BEHAVIOR_MODULE_INTERFACE,
    CONTAIN_IS_SLAUGHTER_SLOT,
    OBJECT_MODULE_LIST,
    PICKUP_STUFF_MOVE_CALL,
    PICKUP_STUFF_MOVE_CALL_BYTES,
    PICKUP_STUFF_MOVE_ORDER,
    PICKUP_STUFF_MOVE_ORDER_BYTES,
    PICKUP_STUFF_MOVE_TO,
    PICKUP_STUFF_MOVE_TO_BYTES,
    PICKUP_STUFF_SCAN_ISSUE,
    PICKUP_STUFF_SCAN_ISSUE_BYTES,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "PickupStuffEnterPatch",
    "build_code",
]

SECTION_NAME = ".pkpent"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = PICKUP_STUFF_MOVE_CALL
HOOK_ORIGINAL = PICKUP_STUFF_MOVE_CALL_BYTES

#: The first bytes at each address the cave depends on. Both orders' entries and the command type
#: each builds are what make the two tail jumps a move and an enter; the order's argument pushes
#: and the scan's call into `PICKUP_STUFF_MOVE_TO` pin the hooked call to `PickupStuffUpdate`.
ANCHORS = {
    AI_MOVE_TO_OBJECT: AI_MOVE_TO_OBJECT_ENTRY,
    AI_MOVE_TO_OBJECT_TYPE_PUSH: AI_MOVE_TO_OBJECT_TYPE_PUSH_BYTES,
    AI_ENTER: AI_ENTER_ENTRY,
    AI_ENTER_TYPE_PUSH: AI_ENTER_TYPE_PUSH_BYTES,
    PICKUP_STUFF_MOVE_TO: PICKUP_STUFF_MOVE_TO_BYTES,
    PICKUP_STUFF_MOVE_ORDER: PICKUP_STUFF_MOVE_ORDER_BYTES,
    PICKUP_STUFF_SCAN_ISSUE: PICKUP_STUFF_SCAN_ISSUE_BYTES,
}


def build_code(base_va: int) -> bytes:
    """`aiMoveToObject`'s drop-in: `__thiscall` on `AIUpdate+0x20`, `(target, cmdSource)`, and it
    leaves by tail-jumping to one of the two orders with the stack and `ecx` as it found them."""
    a = Asm(base_va)
    a.emit(0x56, 0x57, 0x51)  # push esi / edi / ecx      ecx is the order's `this`
    a.emit(0x8B, 0x74, 0x24, 0x10)  # mov esi, [esp+0x10]    target
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "move")
    a.emit(0x8B, 0xBE, struct.pack("<I", OBJECT_MODULE_LIST))  # mov edi, [esi+0x24c]
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "move")

    a.label("next")
    a.emit(0x8B, 0x07)  # mov eax, [edi]             the module, NULL at the end
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "move")
    a.emit(0x83, 0xC7, 0x04)  # add edi, 4
    a.emit(0x8D, 0x48, BEHAVIOR_MODULE_INTERFACE)  # lea ecx, [eax+0xc]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, BEHAVIOR_GET_CONTAIN_SLOT)  # call [eax+8]       getContain
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "next")  # not a contain
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0xFF, 0x52, CONTAIN_IS_SLAUGHTER_SLOT)  # call [edx+0x30]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "next")  # keeps its passengers: walk up to it as stock does

    a.emit(0x59, 0x5F, 0x5E)  # pop ecx / edi / esi
    a.jmp_absolute(AI_ENTER)

    a.label("move")
    a.emit(0x59, 0x5F, 0x5E)  # pop ecx / edi / esi
    a.jmp_absolute(AI_MOVE_TO_OBJECT)
    return a.finish()


class PickupStuffEnterPatch(Patch):
    name = "pickup-stuff-enter"
    author = "officialNecro"
    description = (
        "Make PickupStuffUpdate enter its target when the target carries a slaughter contain "
        "(SlaughterHordeContain, CitadelSlaughterHordeContain) instead of only walking up to it. "
        "With SkirmishAIOnly = No and StuffToPickUp naming the building, units go into it on "
        "their own: tribute carts into a collection point, ambient workers into their building. "
        "Every other target - the One Ring, crates - still gets the stock move. Logic-side: every "
        "peer needs the same binary. No INI change on its own"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            call_rel32(HOOK_VA, section_va),
            "PickupStuffUpdate aiMoveToObject -> pickup-stuff-enter cave",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - PickupStuffUpdate "
                    "or the AI orders it gives are not laid out as in this build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        if bytes(data[off : off + 5]) != call_rel32(HOOK_VA, section_va):
            problems.append(f"{HOOK_VA:#010x} does not call the {SECTION_NAME} cave")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected code")
        return problems
