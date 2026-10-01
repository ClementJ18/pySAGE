"""Make units re-plan a path that runs through a gate when the gate closes.

A path planned while a gate stood open keeps leading through it after the gate shuts: closing a gate
updates the pathfind map, but nothing re-checks the paths units already hold, so they walk through
the closed doors. An order given after the close routes around the gate, because it is planned
against the updated map.

The hook is the last thing close-for-pathing does, the call that puts the gate back into the
pathfind map. The cave makes that call, then walks every object, and for each unit whose current
path passes within reach of the gate - a segment within the gate's bounding-circle radius plus the
unit's own - calls the engine's `destroyPath`. The unit's move state sees no path on its next update
and plans a fresh one against the map the close just updated, exactly as a new order would.

Units the cave leaves alone: a unit still waiting for the pathfinder (its request is planned against
the new map anyway), and one whose main state is `AI_STATE_NO_PATH_UNSAFE`, the one state in which
the move state reads the path without checking it.

Derivation: `../docs/gate-close-pathfinding.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_CURRENT_STATE_ID,
    AI_CURRENT_STATE_ID_BYTES,
    AI_DESTROY_PATH,
    AI_DESTROY_PATH_BYTES,
    AI_MOVE_UPDATE_NO_PATH_RECOMPUTE,
    AI_MOVE_UPDATE_NO_PATH_RECOMPUTE_BYTES,
    AI_MOVE_UPDATE_STATE_TEST,
    AI_MOVE_UPDATE_STATE_TEST_BYTES,
    AI_MOVE_UPDATE_UNGUARDED_PATH_READ,
    AI_MOVE_UPDATE_UNGUARDED_PATH_READ_BYTES,
    AI_PATH_OFFSET,
    AI_STATE_NO_PATH_UNSAFE,
    AI_WAITING_FOR_PATH_OFFSET,
    GAME_LOGIC_OBJECT_BUCKETS_BEGIN,
    GAME_LOGIC_OBJECT_BUCKETS_END,
    GAME_LOGIC_OBJECT_HASH_WALK,
    GAME_LOGIC_OBJECT_HASH_WALK_BYTES,
    GATE_CLOSE_EPILOGUE,
    GATE_CLOSE_EPILOGUE_BYTES,
    GATE_CLOSE_FOR_PATHING,
    GATE_CLOSE_FOR_PATHING_ENTRY,
    GATE_CLOSE_READD_CALL,
    GATE_CLOSE_READD_CALL_BYTES,
    GATE_CLOSE_READD_SETUP,
    GATE_CLOSE_READD_SETUP_BYTES,
    OBJECT_AI_UPDATE,
    OBJECT_BOUNDING_CIRCLE_RADIUS,
    OBJECT_BOUNDING_CIRCLE_RADIUS_READ,
    OBJECT_BOUNDING_CIRCLE_RADIUS_READ_BYTES,
    OBJECT_HASH_ENTRY_NEXT,
    OBJECT_HASH_ENTRY_OBJECT,
    OBJECT_POSITION,
    PATH_APPEND_NODE_LINK,
    PATH_APPEND_NODE_LINK_BYTES,
    PATH_DESTRUCTOR,
    PATH_DESTRUCTOR_BYTES,
    PATH_HEAD_OFFSET,
    PATH_NODE_NEXT_OFFSET,
    PATH_NODE_POS_OFFSET,
    PATHFINDER_ADD_OBJECT,
    PATHFINDER_ADD_OBJECT_BYTES,
    THE_GAME_LOGIC,
)
from ..asm import JAE, JBE, JE, JNE, JZ, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "GateCloseRepathPatch",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".gaterp"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = GATE_CLOSE_READD_CALL
HOOK_ORIGINAL = GATE_CLOSE_READD_CALL_BYTES

#: Every site the cave depends on, as `{va: bytes}`. The hooked call is asserted by
#: `apply_byte_patch`; these are the function it sits in and the code around it, the four engine
#: functions the cave calls, the layouts it walks (object hash, `Path`, bounding radius), and the
#: move-state code that makes a destroyed path turn into a new plan and that the state exclusion
#: protects.
ANCHORS = {
    GATE_CLOSE_FOR_PATHING: GATE_CLOSE_FOR_PATHING_ENTRY,
    GATE_CLOSE_READD_SETUP: GATE_CLOSE_READD_SETUP_BYTES,
    GATE_CLOSE_EPILOGUE: GATE_CLOSE_EPILOGUE_BYTES,
    PATHFINDER_ADD_OBJECT: PATHFINDER_ADD_OBJECT_BYTES,
    AI_DESTROY_PATH: AI_DESTROY_PATH_BYTES,
    AI_CURRENT_STATE_ID: AI_CURRENT_STATE_ID_BYTES,
    AI_MOVE_UPDATE_NO_PATH_RECOMPUTE: AI_MOVE_UPDATE_NO_PATH_RECOMPUTE_BYTES,
    AI_MOVE_UPDATE_STATE_TEST: AI_MOVE_UPDATE_STATE_TEST_BYTES,
    AI_MOVE_UPDATE_UNGUARDED_PATH_READ: AI_MOVE_UPDATE_UNGUARDED_PATH_READ_BYTES,
    GAME_LOGIC_OBJECT_HASH_WALK: GAME_LOGIC_OBJECT_HASH_WALK_BYTES,
    PATH_APPEND_NODE_LINK: PATH_APPEND_NODE_LINK_BYTES,
    PATH_DESTRUCTOR: PATH_DESTRUCTOR_BYTES,
    OBJECT_BOUNDING_CIRCLE_RADIUS_READ: OBJECT_BOUNDING_CIRCLE_RADIUS_READ_BYTES,
}


def _d32(value: int) -> bytes:
    return struct.pack("<i", value)


def _movss_load(xmm: int, base: int, disp: int) -> bytes:
    """`movss xmmN, dword [reg+disp]`, disp8 when it fits."""
    return _sse_mem(0x10, xmm, base, disp)


def _sse_mem(opcode: int, xmm: int, base: int, disp: int) -> bytes:
    """A scalar-single `F3 0F <opcode> /r` with a `[reg+disp]` operand. `base` is never esp."""
    if -128 <= disp <= 127:
        return bytes([0xF3, 0x0F, opcode, 0x40 | xmm << 3 | base, disp & 0xFF])
    return bytes([0xF3, 0x0F, opcode, 0x80 | xmm << 3 | base]) + _d32(disp)


def _sse_reg(opcode: int, dst: int, src: int) -> bytes:
    """A scalar-single `F3 0F <opcode> /r` between two registers."""
    return bytes([0xF3, 0x0F, opcode, 0xC0 | dst << 3 | src])


_MOVSS, _ADDSS, _MULSS, _SUBSS, _DIVSS = 0x10, 0x58, 0x59, 0x5C, 0x5E
_EAX, _ECX, _EDX, _EBX, _EBP = 0, 1, 2, 3, 5
_POS_X = PATH_NODE_POS_OFFSET
_POS_Y = PATH_NODE_POS_OFFSET + 4
_GATE_X = OBJECT_POSITION
_GATE_Y = OBJECT_POSITION + 4


def build_code(base_va: int) -> bytes:
    """The cave: re-add the gate, then drop every path that runs through it.

    Entered by `call` from `HOOK_VA`, so `[esp+4]` is the gate `Object *` and `ecx` the pathfinder,
    and it leaves by `ret 4` as the replaced callee did.

    Registers through the walk: `ebp` the gate, `esi`/`edi` the bucket cursor and end, `ebx` the
    hash entry, `edx` the path node. `xmm7` holds the squared reach, `xmm0`/`xmm1` the segment's
    start; the rest are scratch.
    """
    a = Asm(base_va)
    a.emit(0xFF, 0x74, 0x24, 0x04)  # push dword [esp+4]  ; the gate, again
    a.call_absolute(PATHFINDER_ADD_OBJECT)  # the displaced call (ret 4 pops the copy)
    a.emit(0x53, 0x56, 0x57, 0x55)  # push ebx / esi / edi / ebp
    a.emit(0x8B, 0x6C, 0x24, 0x14)  # mov ebp, [esp+0x14]  ; the gate, past the four saves
    a.emit(0xA1, struct.pack("<I", THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x8B, 0xB0, _d32(GAME_LOGIC_OBJECT_BUCKETS_BEGIN))  # mov esi, [eax+begin]
    a.emit(0x8B, 0xB8, _d32(GAME_LOGIC_OBJECT_BUCKETS_END))  # mov edi, [eax+end]

    a.label("next_bucket")
    a.emit(0x3B, 0xF7)  # cmp esi, edi
    a.jcc(JAE, "done")
    a.emit(0x8B, 0x1E)  # mov ebx, [esi]  ; the bucket's first entry
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4

    a.label("chain")
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JZ, "next_bucket")

    # --- is this a unit holding a finished path? ---
    a.emit(0x8B, 0x43, OBJECT_HASH_ENTRY_OBJECT)  # mov eax, [ebx+8]  ; Object *
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "next_entry")
    a.emit(0x3B, 0xC5)  # cmp eax, ebp  ; not the gate itself
    a.jcc(JE, "next_entry")
    a.emit(0x8B, 0x88, _d32(OBJECT_AI_UPDATE))  # mov ecx, [eax+0x260]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JZ, "next_entry")
    a.emit(0x80, 0xB9, _d32(AI_WAITING_FOR_PATH_OFFSET), 0x00)  # cmp byte [ecx+0x3b1], 0
    a.jcc(JNE, "next_entry")
    a.emit(0x8B, 0x91, _d32(AI_PATH_OFFSET))  # mov edx, [ecx+0x140]  ; Path *
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JZ, "next_entry")
    a.emit(0x8B, 0x52, PATH_HEAD_OFFSET)  # mov edx, [edx+4]  ; first node
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JZ, "next_entry")

    # --- reach^2 = (gate radius + unit radius)^2 ---
    a.emit(_sse_mem(_MOVSS, 7, _EBP, OBJECT_BOUNDING_CIRCLE_RADIUS))  # movss xmm7, [ebp+0xb8]
    a.emit(_sse_mem(_ADDSS, 7, _EAX, OBJECT_BOUNDING_CIRCLE_RADIUS))  # addss xmm7, [eax+0xb8]
    a.emit(_sse_reg(_MULSS, 7, 7))  # mulss xmm7, xmm7
    a.emit(_movss_load(0, _EDX, _POS_X))  # movss xmm0, [edx+0xc]  ; P0
    a.emit(_movss_load(1, _EDX, _POS_Y))  # movss xmm1, [edx+0x10]

    # --- for each segment P0 -> P1 (the last node is tested as a point, P1 = P0) ---
    a.label("segment")
    a.emit(0x8B, 0x42, PATH_NODE_NEXT_OFFSET)  # mov eax, [edx]  ; next node
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JNE, "have_next")
    a.emit(0x8B, 0xC2)  # mov eax, edx
    a.label("have_next")
    a.emit(_movss_load(2, _EAX, _POS_X))  # movss xmm2, [eax+0xc]  ; P1
    a.emit(_movss_load(3, _EAX, _POS_Y))  # movss xmm3, [eax+0x10]
    a.emit(_sse_mem(_MOVSS, 4, _EBP, _GATE_X))  # movss xmm4, [ebp+0x38]  ; w = G - P0
    a.emit(_sse_reg(_SUBSS, 4, 0))  # subss xmm4, xmm0
    a.emit(_sse_mem(_MOVSS, 5, _EBP, _GATE_Y))  # movss xmm5, [ebp+0x3c]
    a.emit(_sse_reg(_SUBSS, 5, 1))  # subss xmm5, xmm1
    a.emit(_sse_reg(_SUBSS, 2, 0))  # subss xmm2, xmm0  ; d = P1 - P0
    a.emit(_sse_reg(_SUBSS, 3, 1))  # subss xmm3, xmm1
    a.emit(0x0F, 0x28, 0xF4)  # movaps xmm6, xmm4  ; wd = w.d
    a.emit(_sse_reg(_MULSS, 6, 2))  # mulss xmm6, xmm2
    a.emit(0x0F, 0x28, 0xC5)  # movaps xmm0, xmm5
    a.emit(_sse_reg(_MULSS, 0, 3))  # mulss xmm0, xmm3
    a.emit(_sse_reg(_ADDSS, 6, 0))  # addss xmm6, xmm0
    a.emit(_sse_reg(_MULSS, 4, 4))  # mulss xmm4, xmm4  ; ww = w.w
    a.emit(_sse_reg(_MULSS, 5, 5))  # mulss xmm5, xmm5
    a.emit(_sse_reg(_ADDSS, 4, 5))  # addss xmm4, xmm5
    a.emit(0x0F, 0x57, 0xC9)  # xorps xmm1, xmm1
    a.emit(0x0F, 0x2F, 0xF1)  # comiss xmm6, xmm1
    a.jcc_short(JBE, "compare")  # wd <= 0: P0 is closest, dist^2 = ww
    a.emit(_sse_reg(_MULSS, 2, 2))  # mulss xmm2, xmm2  ; dd = d.d
    a.emit(_sse_reg(_MULSS, 3, 3))  # mulss xmm3, xmm3
    a.emit(_sse_reg(_ADDSS, 2, 3))  # addss xmm2, xmm3
    a.emit(0x0F, 0x2F, 0xF2)  # comiss xmm6, xmm2
    a.jcc_short(JAE, "past_end")  # wd >= dd: P1 is closest
    a.emit(_sse_reg(_MULSS, 6, 6))  # mulss xmm6, xmm6  ; dist^2 = ww - wd^2/dd
    a.emit(_sse_reg(_DIVSS, 6, 2))  # divss xmm6, xmm2
    a.emit(_sse_reg(_SUBSS, 4, 6))  # subss xmm4, xmm6
    a.jmp_short("compare")
    a.label("past_end")
    a.emit(_sse_mem(_MOVSS, 4, _EBP, _GATE_X))  # movss xmm4, [ebp+0x38]  ; |G - P1|^2
    a.emit(_sse_mem(_SUBSS, 4, _EAX, _POS_X))  # subss xmm4, [eax+0xc]
    a.emit(_sse_reg(_MULSS, 4, 4))  # mulss xmm4, xmm4
    a.emit(_sse_mem(_MOVSS, 5, _EBP, _GATE_Y))  # movss xmm5, [ebp+0x3c]
    a.emit(_sse_mem(_SUBSS, 5, _EAX, _POS_Y))  # subss xmm5, [eax+0x10]
    a.emit(_sse_reg(_MULSS, 5, 5))  # mulss xmm5, xmm5
    a.emit(_sse_reg(_ADDSS, 4, 5))  # addss xmm4, xmm5
    a.label("compare")
    a.emit(0x0F, 0x2F, 0xE7)  # comiss xmm4, xmm7
    a.jcc_short(JBE, "crosses")  # within reach (a NaN also lands here: re-planning is safe)
    a.emit(0x3B, 0xC2)  # cmp eax, edx  ; that was the last node
    a.jcc(JE, "next_entry")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(_movss_load(0, _EDX, _POS_X))  # movss xmm0, [edx+0xc]  ; P0 = P1
    a.emit(_movss_load(1, _EDX, _POS_Y))  # movss xmm1, [edx+0x10]
    a.jmp("segment")

    # --- the path runs through the gate: drop it, unless the move state cannot take that ---
    a.label("crosses")
    a.emit(0x8B, 0x43, OBJECT_HASH_ENTRY_OBJECT)  # mov eax, [ebx+8]
    a.emit(0x8B, 0x88, _d32(OBJECT_AI_UPDATE))  # mov ecx, [eax+0x260]
    a.call_absolute(AI_CURRENT_STATE_ID)  # eax = main state id; ecx untouched
    a.emit(0x83, 0xF8, AI_STATE_NO_PATH_UNSAFE)  # cmp eax, 0x47
    a.jcc(JE, "next_entry")
    a.call_absolute(AI_DESTROY_PATH)  # ecx is still the AIUpdate

    a.label("next_entry")
    a.emit(0x8B, 0x5B, OBJECT_HASH_ENTRY_NEXT)  # mov ebx, [ebx]
    a.jmp("chain")

    a.label("done")
    a.emit(0x5D, 0x5F, 0x5E, 0x5B)  # pop ebp / edi / esi / ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a.finish()


class GateCloseRepathPatch(Patch):
    """Units whose path runs through a gate plan again when it closes."""

    name = "gate-close-repath"
    author = "officialNecro"
    description = (
        "Stop units walking through a gate that closed after they were ordered through it: when a "
        "gate closes, every unit whose current path passes the gate drops that path and plans a "
        "new one against the closed gate, the way an order given after the close already does. "
        "Any gate, any owner. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        call = b"\xe8" + struct.pack("<i", section_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            call,
            "gate close-for-pathing re-add -> gate-close-repath cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the gate close or "
                    "the AI path code is not this build's, so the cave would call or read the "
                    "wrong thing"
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
        if data[off] != 0xE8:
            return [f"{HOOK_VA:#010x} is not a call - the hook is not installed"]
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va:
            problems.append(f"hook calls {target:#010x}, expected {section_va:#010x}")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected code")
        return problems
