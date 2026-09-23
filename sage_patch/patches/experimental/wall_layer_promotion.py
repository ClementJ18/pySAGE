"""Stop siege engines being lifted onto walls they are pushed against.

A wall stamps its layer into every pathfind cell its polygon touches, and the pathfinder moves an
object onto a layer when the cell under its centre names one more than 10 units above it. A wide
siege engine pushed into a wall gets its centre into a stamped cell and is lifted a storey. All
three `setLayer` calls are re-aimed at a gate in a `.wallyr` section, which refuses to lift a
`MACHINE` onto a wall-height layer more than 10 units above it. Ramps are unaffected.

Derivation: `../../docs/wall-layer-promotion.md`.
"""

from __future__ import annotations

import struct

from ...addresses import (
    FLOAT_TEN,
    KINDOF_MACHINE_BYTE,
    KINDOF_MACHINE_MASK,
    LAYER_AFTER_MOVE_SET_CALL,
    LAYER_AFTER_MOVE_SET_CALL_ENTRY,
    LAYER_SET_ARGS_ENTRY,
    OBJECT_POSITION_Z,
    OBJECT_SET_LAYER,
    OBJECT_SET_LAYER_ENTRY,
    PATHFINDER_IN_AI,
    PATHFINDER_WALL_HEIGHTS,
    PHYSICS_LAYER_SET_CALL,
    PHYSICS_LAYER_SET_CALL_ENTRY,
    TERRAIN_GET_LAYER_FOR_DESTINATION,
    THE_AI,
    WALL_LAYER_FIRST,
    WALL_LAYER_LAST,
    WALL_LAYER_PROMOTION,
    WALL_LAYER_PROMOTION_ENTRY,
    WALL_LAYER_PROMOTION_SET_ARGS,
    WALL_LAYER_PROMOTION_SET_CALL,
    WALL_LAYER_PROMOTION_SET_CALL_ENTRY,
)
from ...asm import JA, JG, JL, JZ, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_SITES",
    "SECTION_NAME",
    "WallLayerPromotionPatch",
    "build_code",
]

SECTION_NAME = ".wallyr"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: Object struct offset of the `ThingTemplate *`.
_OBJECT_TEMPLATE = 0x04

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: Every `setLayer` call that can put a moving object on a wall, as
#: `(call va, its stock five bytes, the va of the three bytes that set its arguments)`. All
#: three share the `push eax; mov ecx, esi` prologue, so one cave serves them all.
HOOK_SITES = (
    (
        WALL_LAYER_PROMOTION_SET_CALL,
        WALL_LAYER_PROMOTION_SET_CALL_ENTRY,
        WALL_LAYER_PROMOTION_SET_ARGS,
    ),
    (
        LAYER_AFTER_MOVE_SET_CALL,
        LAYER_AFTER_MOVE_SET_CALL_ENTRY,
        LAYER_AFTER_MOVE_SET_CALL - 3,
    ),
    (PHYSICS_LAYER_SET_CALL, PHYSICS_LAYER_SET_CALL_ENTRY, PHYSICS_LAYER_SET_CALL - 3),
)

#: The first instruction at each address the cave jumps to, plus the two sites whose register use
#: the cave depends on, as a `{va: bytes}` map. A build whose layout moved fails here instead of
#: on a wild jump or a gate that tests the wrong object.
ANCHORS = {
    WALL_LAYER_PROMOTION: WALL_LAYER_PROMOTION_ENTRY,  # the `h > z + 10` promotion
    TERRAIN_GET_LAYER_FOR_DESTINATION: bytes.fromhex("558bec5151"),  # the resolver feeding 2 & 3
    OBJECT_SET_LAYER: OBJECT_SET_LAYER_ENTRY,  # the call the cave stands in front of
    **{args_va: LAYER_SET_ARGS_ENTRY for _va, _stock, args_va in HOOK_SITES},
}


def build_code(base_va: int) -> bytes:
    """The gate. Entered by `call`, so it leaves the stack exactly as `setLayer` would.

    On entry `ecx` is the `Object *` and `[esp+4]` is the layer about to be set, at all three
    sites. `eax`, `edx` and `xmm0` are free: every resume point reloads what it needs, and all
    three are caller-clobbered across the call this stands in for.
    """
    a = Asm(base_va)
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]      ; the layer about to be set

    # Layer 16 is the ramp, and everything below it is ground or a slot layer. Only a wall-height
    # layer can be the teleport, so anything else goes through untouched whatever the object is -
    # this is what keeps a siege engine's climb up a ramp working.
    a.emit(0x83, 0xF8, WALL_LAYER_FIRST)  # cmp eax, 0x11
    a.jcc(JL, "allow")
    a.emit(0x83, 0xF8, WALL_LAYER_LAST)  # cmp eax, 0x40
    a.jcc(JG, "allow")

    # A wall-height layer. Is this a siege engine? `Object+0x04` is the `ThingTemplate` and the
    # `KindOf` mask lives inside it, so the test is two loads and no call.
    a.emit(0x8B, 0x51, _OBJECT_TEMPLATE)  # mov edx, [ecx+4]      ; ThingTemplate *
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JZ, "allow")  # no template: leave the engine's behaviour alone
    a.emit(0xF6, 0x82, *struct.pack("<I", KINDOF_MACHINE_BYTE), KINDOF_MACHINE_MASK)
    a.jcc(JZ, "allow")  # test byte [edx+0x109], 0x08   ; not MACHINE

    # A siege engine being put on a wall. Is it already up there, or is this the teleport? The
    # engine's own answer to "near enough to the same level" is 10 units, and it is the constant
    # used by both arms of the promotion, so the gate reuses it rather than inventing a threshold.
    # Measured: arriving off a ramp is +0.0, the glitch is +53.4.
    a.emit(0xA1, *struct.pack("<I", THE_AI))  # mov eax, [TheAI]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "allow_reload")
    a.emit(0x8B, 0x50, PATHFINDER_IN_AI)  # mov edx, [eax+0x10]   ; the Pathfinder
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JZ, "allow_reload")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]      ; the layer again
    # movss xmm0, [edx + eax*4 + 0x1BE78]   ; that layer's flat surface height
    a.emit(0xF3, 0x0F, 0x10, 0x84, 0x82, *struct.pack("<I", PATHFINDER_WALL_HEIGHTS))
    a.emit(0xF3, 0x0F, 0x5C, 0x41, OBJECT_POSITION_Z)  # subss xmm0, [ecx+0x40]   ; - obj->z
    a.emit(0x0F, 0x2F, 0x05, *struct.pack("<I", FLOAT_TEN))  # comiss xmm0, [10.0f]
    a.jcc(JA, "refuse")  # more than a step above: the teleport

    a.label("allow_reload")
    a.label("allow")
    # Tail-call the engine's own `setLayer`: its `ret 4` pops the argument and returns straight to
    # the instruction after the hooked call, so the stack is identical to the stock path.
    a.jmp_absolute(OBJECT_SET_LAYER)

    a.label("refuse")
    # Drop the argument the way `setLayer` would have, and leave the object's layer alone.
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a.finish()


class WallLayerPromotionPatch(Patch):
    name = "wall-layer-promotion"
    author = "officialNecro"
    experimental = True
    description = (
        "Stop siege engines being teleported onto walls they walked past. Ramps still work. No "
        "INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, _stock, _args in HOOK_SITES:
            if va_to_offset(data, va) is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        for va, stock, _args in HOOK_SITES:
            off = va_to_offset(data, va)
            assert off is not None  # checked above, before anything was written
            # Each hook stays a `call` - only its target moves - so the cave is entered with the
            # engine's return address already on the stack.
            call = bytes([0xE8]) + struct.pack("<i", section_va - (va + 5))
            apply_byte_patch(
                data,
                off,
                stock,
                call,
                f"setLayer at {va:#010x} -> wall-layer-promotion gate",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the wall-layer "
                    "promotion's layout is not this build's, so the gate would test the wrong "
                    "object or return to the wrong place"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        for va, _stock, _args in HOOK_SITES:
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} is not mapped by any section")
                continue
            if data[off] != 0xE8:
                problems.append(f"{va:#010x} is not a call - that hook is not installed")
                continue
            target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != section_va:
                problems.append(
                    f"hook at {va:#010x} calls {target:#010x}, expected {section_va:#010x}"
                )
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected gate")
        return problems
