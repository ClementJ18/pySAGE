"""Let the skirmish AI send units through its own tunnel network when that is the shorter way.

The pathfinder has no notion of a tunnel, so an AI army ordered across the map walks the whole way
past the tunnel it owns beside it. This patch decides at order time instead of in the pathfinder.
When a computer player's unit outside the network is given a move or an attack-move by the AI, the
cave compares the straight walk with walking to the player's tunnel nearest the unit, a fixed
`transit_cost`, and walking on from the tunnel nearest the goal. If the tunnel wins, and the near
tunnel's contain accepts the unit, the order is recorded in a table and the unit is sent in with
the engine's own `aiEnter`.

Once a recorded unit is inside, it is brought out at the tunnel nearest its goal with the same
order a tunnel's Evacuate gives each passenger - `aiExit` against that tunnel, or the horde's own
exit for a battalion - and as soon as it is out, the recorded order is given again with the
routing switched off. A move the AI gives a unit that is already in its network is recorded the
same way, so the unit comes out where that order is going rather than sitting inside.

The AI repeats its orders, so neither half restarts on a repeat: the same order again to a unit
walking to the door is absorbed, and any order to a unit inside only changes where it is going.

Fallbacks, so that no unit is left inside or stranded at the door:

- an enter that fails or stalls (the unit goes idle outside, or `ENTER_SECONDS` pass) gives the
  recorded order back as a plain walk;
- an exit that has not happened after `EXIT_RETRY_SECONDS` is ordered again, and from the third
  attempt on it is ordered at the tunnel the unit is in, whatever the goal;
- a unit that dies, leaves the network some other way or is given a different order loses its
  entry; and `GameLogic::reset` empties the table between matches and before a save loads.

Three hooks: the six bytes in front of `aiDoCommand`'s command switch, `TunnelContain::update`'s
vtable slot (the per-frame pass, run once per logic frame whichever tunnel gets there first), and
`GameLogic::reset`'s two vtable slots.

Derivation: `../docs/ai-tunnel-routing.md`.
"""

from __future__ import annotations

import argparse
import struct

from ..addresses import (
    AI_ATTACK_MOVE_TO_POSITION,
    AI_ATTACK_MOVE_TO_POSITION_ENTRY,
    AI_CMD_ATTACK_MOVE_TO_POSITION,
    AI_CMD_IDLE,
    AI_CMD_MOVE_TO_POSITION,
    AI_COMMAND_INT_VALUE_OFFSET,
    AI_COMMAND_POSITION_OFFSET,
    AI_COMMAND_SOURCE_FROM_AI,
    AI_COMMAND_SOURCE_FROM_PLAYER,
    AI_CURRENT_STATE_ID,
    AI_CURRENT_STATE_ID_BYTES,
    AI_DO_COMMAND,
    AI_DO_COMMAND_DISPATCH,
    AI_DO_COMMAND_DISPATCH_BYTES,
    AI_DO_COMMAND_ENTRY,
    AI_DO_COMMAND_MODULE,
    AI_DO_COMMAND_MODULE_BYTES,
    AI_DO_COMMAND_OWNER_EBP,
    AI_DO_COMMAND_OWNER_STORE,
    AI_DO_COMMAND_OWNER_STORE_BYTES,
    AI_DO_COMMAND_SETUP,
    AI_DO_COMMAND_SETUP_BYTES,
    AI_DO_COMMAND_SWITCH,
    AI_DO_COMMAND_SWITCH_BYTES,
    AI_DO_COMMAND_TAIL,
    AI_DO_COMMAND_TAIL_BYTES,
    AI_DO_COMMAND_THIS_EBP,
    AI_ENTER,
    AI_ENTER_ENTRY,
    AI_ENTER_TYPE_PUSH,
    AI_ENTER_TYPE_PUSH_BYTES,
    AI_EXIT,
    AI_EXIT_ENTRY,
    AI_MOVE_TO_POSITION,
    AI_MOVE_TO_POSITION_ENTRY,
    AI_STATE_IDLE,
    CONTAIN_GET_HORDE_IFACE,
    CONTAIN_GET_HORDE_IFACE_ENTRY,
    CONTAIN_GET_HORDE_IFACE_SLOT,
    CONTAIN_IS_VALID_CONTAINER_FOR_SLOT,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    GAME_LOGIC_FRAME,
    GAME_LOGIC_RESET,
    GAME_LOGIC_RESET_ENTRY,
    GAME_LOGIC_RESET_VTABLE_SLOTS,
    HORDE_IFACE_EXIT,
    HORDE_IFACE_EXIT_BYTES,
    HORDE_IFACE_EXIT_SLOT,
    HORDE_IFACE_EXIT_VTABLE_SLOT,
    LOGIC_FRAMES_PER_SECOND,
    OBJECT_AI_UPDATE,
    OBJECT_CONTAIN,
    OBJECT_CONTAINED_BY,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_GET_CONTROLLING_PLAYER_ENTRY,
    OBJECT_ID,
    OBJECT_POSITION,
    PLAYER_NEAREST_TUNNEL,
    PLAYER_NEAREST_TUNNEL_ENTRY,
    PLAYER_TUNNEL_TRACKER,
    PLAYER_TYPE,
    PLAYER_TYPE_COMPUTER,
    THE_GAME_LOGIC,
    TN_GUARD_NEAREST_TUNNEL_CALL,
    TN_GUARD_NEAREST_TUNNEL_CALL_BYTES,
    TUNNEL_CONTAIN_INTERFACE_VTABLE,
    TUNNEL_CONTAIN_UPDATE,
    TUNNEL_CONTAIN_UPDATE_ENTRY,
    TUNNEL_CONTAIN_UPDATE_VTABLE_SLOT,
)
from ..asm import JAE, JB, JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "DEFAULT_TRANSIT_COST",
    "ENTER_SECONDS",
    "ENTRY_SIZE",
    "EXIT_RETRY_SECONDS",
    "FALLBACK_ATTEMPT",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "PHASE_ENTERING",
    "PHASE_EXITING",
    "PHASE_INSIDE",
    "SECTION_NAME",
    "SLOTS",
    "VTABLE_SLOTS",
    "AiTunnelRoutingPatch",
    "Layout",
    "build_section",
]

SECTION_NAME = ".tunrte"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE: the routing table
# at the section's base is written every frame.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

HOOK_VA = AI_DO_COMMAND_DISPATCH
HOOK_ORIGINAL = AI_DO_COMMAND_DISPATCH_BYTES

#: Extra world units a trip through the network is charged, on top of the two walks. Covers the
#: walk into the door and the wait to come out; a cell is ten units.
DEFAULT_TRANSIT_COST = 200
#: How long an enter may take before the order is given back as a walk.
ENTER_SECONDS = 60
#: How long an exit may take before it is ordered again.
EXIT_RETRY_SECONDS = 10
#: The exit attempt (counting from 0) from which a unit is ordered out of the tunnel it is in rather
#: than the one nearest its goal - so a goal tunnel that has gone, or never lets it out, costs two
#: retries and no more.
FALLBACK_ATTEMPT = 2

#: Units routed at once. A full table only means the next order is not rerouted.
SLOTS = 64
ENTRY_SIZE = 0x20
_ID = 0x00
_CMD = 0x04
_GOAL = 0x08  # Coord3D, 12 bytes
_SHOTS = 0x14
_PHASE = 0x18  # byte
_ATTEMPTS = 0x19  # byte
_DEADLINE = 0x1C

PHASE_ENTERING = 1
PHASE_INSIDE = 2
PHASE_EXITING = 3

_TRANSIT = 0x00
_BUSY = 0x04
_LAST_TICK = 0x08
_TABLE = 0x10
_CODE = _TABLE + SLOTS * ENTRY_SIZE

#: Every site the cave depends on, as `{va: bytes}`. The hook's own six bytes are asserted by
#: `apply_byte_patch`, the three vtable slots by `apply`. These are `aiDoCommand`'s frame layout at
#: the hook (its parms, source, `this`, module and owner) and the switch and tail the cave leaves
#: by; the engine functions it calls; and the tunnel-guard call that pins the nearest-tunnel
#: helper's register convention.
ANCHORS = {
    AI_DO_COMMAND: AI_DO_COMMAND_ENTRY,
    AI_DO_COMMAND_SETUP: AI_DO_COMMAND_SETUP_BYTES,
    AI_DO_COMMAND_MODULE: AI_DO_COMMAND_MODULE_BYTES,
    AI_DO_COMMAND_OWNER_STORE: AI_DO_COMMAND_OWNER_STORE_BYTES,
    AI_DO_COMMAND_SWITCH: AI_DO_COMMAND_SWITCH_BYTES,
    AI_DO_COMMAND_TAIL: AI_DO_COMMAND_TAIL_BYTES,
    AI_ENTER: AI_ENTER_ENTRY,
    AI_ENTER_TYPE_PUSH: AI_ENTER_TYPE_PUSH_BYTES,
    AI_EXIT: AI_EXIT_ENTRY,
    AI_MOVE_TO_POSITION: AI_MOVE_TO_POSITION_ENTRY,
    AI_ATTACK_MOVE_TO_POSITION: AI_ATTACK_MOVE_TO_POSITION_ENTRY,
    AI_CURRENT_STATE_ID: AI_CURRENT_STATE_ID_BYTES,
    CONTAIN_GET_HORDE_IFACE: CONTAIN_GET_HORDE_IFACE_ENTRY,
    HORDE_IFACE_EXIT: HORDE_IFACE_EXIT_BYTES,
    HORDE_IFACE_EXIT_VTABLE_SLOT: struct.pack("<I", HORDE_IFACE_EXIT),
    GAME_LOGIC_FIND_OBJECT_BY_ID: GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER: OBJECT_GET_CONTROLLING_PLAYER_ENTRY,
    PLAYER_NEAREST_TUNNEL: PLAYER_NEAREST_TUNNEL_ENTRY,
    TN_GUARD_NEAREST_TUNNEL_CALL: TN_GUARD_NEAREST_TUNNEL_CALL_BYTES,
    TUNNEL_CONTAIN_UPDATE: TUNNEL_CONTAIN_UPDATE_ENTRY,
    GAME_LOGIC_RESET: GAME_LOGIC_RESET_ENTRY,
}

#: The vtable slots the patch repoints, and the dword each must hold first.
VTABLE_SLOTS = {
    TUNNEL_CONTAIN_UPDATE_VTABLE_SLOT: TUNNEL_CONTAIN_UPDATE,
    **dict.fromkeys(GAME_LOGIC_RESET_VTABLE_SLOTS, GAME_LOGIC_RESET),
}


def _u32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def _i8(value: int) -> int:
    return value & 0xFF


class Layout:
    """Where everything sits in a section based at `base`: the data words, the table, and the
    three routines the hooks point at."""

    def __init__(self, base: int) -> None:
        self.base = base
        self.transit = base + _TRANSIT
        self.busy = base + _BUSY
        self.last_tick = base + _LAST_TICK
        self.table = base + _TABLE
        self.table_end = self.table + SLOTS * ENTRY_SIZE
        self.code, self.dispatch, self.tick, self.reset = _assemble(self)


def _set_busy(a: Asm, layout: Layout, value: int) -> None:
    a.emit(0xC7, 0x05, _u32(layout.busy), _u32(value))  # mov dword [busy], value


def _frame_into_edx(a: Asm) -> None:
    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x8B, 0x50, GAME_LOGIC_FRAME)  # mov edx, [eax+0x40]


def _assemble(layout: Layout) -> tuple[bytes, int, int, int]:
    a = Asm(layout.base + _CODE)

    dispatch = a.va
    _emit_dispatch(a, layout)
    tick = a.va
    _emit_tick(a, layout)
    reset = a.va
    _emit_reset(a, layout)
    _emit_helpers(a, layout)
    return a.finish(), dispatch, tick, reset


def _emit_dispatch(a: Asm, layout: Layout) -> None:
    """Jumped to from `aiDoCommand` in front of its switch.

    On entry `esi` is the `AICommandParms`, `ebx` its command source, `edi` the `AIUpdate`, and the
    frame holds `this` and the owning `Object`. Leaves either to the switch, with the replaced
    instructions done and every register as it found them, or - when it has taken the order over -
    to the function's common tail, which ends the call as a handled command does.
    """
    a.emit(0x8B, 0x06)  # mov eax, [esi]  ; displaced: the command type
    a.emit(0x83, 0x4D, 0x08, 0xFF)  # or dword [ebp+8], -1  ; displaced
    a.emit(0x83, 0x3D, _u32(layout.busy), 0x00)  # cmp dword [busy], 0
    a.jcc(JNE, "to_switch")  # an order this cave is giving itself
    a.emit(0x60)  # pushad
    a.emit(0x8B, 0x7D, _i8(AI_DO_COMMAND_OWNER_EBP))  # mov edi, [ebp-0x14]  ; the Object
    # The engine's AI and the player: the skirmish AI gives its army orders as its player, so both
    # count. A human player's never reach the tunnel test - `network_player` wants a computer.
    a.emit(0x83, 0xFB, AI_COMMAND_SOURCE_FROM_AI)  # cmp ebx, 2
    a.jcc_short(JE, "routable_source")
    a.emit(0x83, 0xFB, AI_COMMAND_SOURCE_FROM_PLAYER)  # cmp ebx, 0
    a.jcc_short(JNE, "other_order")
    a.label("routable_source")
    a.emit(0x83, 0xF8, AI_CMD_MOVE_TO_POSITION)  # cmp eax, 0
    a.jcc_short(JE, "move")
    a.emit(0x83, 0xF8, AI_CMD_ATTACK_MOVE_TO_POSITION)  # cmp eax, 0xf
    a.jcc_short(JE, "move")

    # Anything else replaces a route the unit was walking to the door for. An idle order is the
    # engine settling a unit down, not a new order, and one inside the network keeps its route.
    a.label("other_order")
    a.emit(0x83, 0xF8, AI_CMD_IDLE)  # cmp eax, 5
    a.jcc(JE, "pass")
    a.emit(0x83, 0xBF, _u32(OBJECT_CONTAINED_BY), 0x00)  # cmp dword [edi+0x27c], 0
    a.jcc(JNE, "pass")
    a.call("drop_entry")
    a.jmp("pass")

    a.label("move")
    a.emit(0x8B, 0x8F, _u32(OBJECT_CONTAINED_BY))  # mov ecx, [edi+0x27c]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JNE, "inside")

    # The AI repeats its orders. The same order again, to a unit already walking to the door for
    # it, is taken as given: restarting the enter every time would leave it stuttering.
    a.call("find_entry")
    a.emit(0x85, 0xC0)
    a.jcc_short(JE, "fresh_order")
    a.emit(0x80, 0x78, _PHASE, PHASE_ENTERING)  # cmp byte [eax+0x18], 1
    a.jcc_short(JNE, "drop_route")
    same = [(0, _CMD)] + [(AI_COMMAND_POSITION_OFFSET + 4 * n, _GOAL + 4 * n) for n in range(3)]
    for own, recorded in same:
        a.emit(0x8B, 0x4E, own)  # mov ecx, [esi+own]
        a.emit(0x3B, 0x48, recorded)  # cmp ecx, [eax+recorded]
        a.jcc_short(JNE, "drop_route")
    a.emit(0x61)  # popad
    a.jmp_absolute(AI_DO_COMMAND_TAIL)
    a.label("drop_route")
    a.emit(0xC7, 0x00, _u32(0))  # mov dword [eax], 0  ; a new order replaces the route
    a.label("fresh_order")
    a.call("network_player")  # eax = a computer player with a tunnel network, or 0
    a.emit(0x85, 0xC0)
    a.jcc(JE, "pass")
    a.emit(0x50)  # push eax  ; [esp] = player
    a.emit(0x8D, 0x5F, OBJECT_POSITION)  # lea ebx, [edi+0x38]
    a.call_absolute(PLAYER_NEAREST_TUNNEL)  # eax = A, the tunnel nearest the unit
    a.emit(0x85, 0xC0)
    a.jcc(JE, "pass_player")
    a.emit(0x50)  # push eax  ; [esp] = A, [esp+4] = player
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]
    a.emit(0x8D, 0x5E, AI_COMMAND_POSITION_OFFSET)  # lea ebx, [esi+8]  ; the goal
    a.call_absolute(PLAYER_NEAREST_TUNNEL)  # eax = B, the tunnel nearest the goal
    a.emit(0x85, 0xC0)
    a.jcc(JE, "pass_tunnel")
    a.emit(0x3B, 0x04, 0x24)  # cmp eax, [esp]
    a.jcc(JE, "pass_tunnel")

    # direct = |goal - unit|, via = |A - unit| + |goal - B| + transit, all in the ground plane
    pos, goal = OBJECT_POSITION, AI_COMMAND_POSITION_OFFSET
    a.emit(0xF3, 0x0F, 0x10, 0x46, goal)  # movss xmm0, [esi+8]
    a.emit(0xF3, 0x0F, 0x5C, 0x47, pos)  # subss xmm0, [edi+0x38]
    a.emit(0xF3, 0x0F, 0x59, 0xC0)  # mulss xmm0, xmm0
    a.emit(0xF3, 0x0F, 0x10, 0x4E, goal + 4)  # movss xmm1, [esi+0xc]
    a.emit(0xF3, 0x0F, 0x5C, 0x4F, pos + 4)  # subss xmm1, [edi+0x3c]
    a.emit(0xF3, 0x0F, 0x59, 0xC9)  # mulss xmm1, xmm1
    a.emit(0xF3, 0x0F, 0x58, 0xC1)  # addss xmm0, xmm1
    a.emit(0xF3, 0x0F, 0x51, 0xC0)  # sqrtss xmm0, xmm0
    a.emit(0x8B, 0x0C, 0x24)  # mov ecx, [esp]  ; A
    a.emit(0xF3, 0x0F, 0x10, 0x51, pos)  # movss xmm2, [ecx+0x38]
    a.emit(0xF3, 0x0F, 0x5C, 0x57, pos)  # subss xmm2, [edi+0x38]
    a.emit(0xF3, 0x0F, 0x59, 0xD2)  # mulss xmm2, xmm2
    a.emit(0xF3, 0x0F, 0x10, 0x49, pos + 4)  # movss xmm1, [ecx+0x3c]
    a.emit(0xF3, 0x0F, 0x5C, 0x4F, pos + 4)  # subss xmm1, [edi+0x3c]
    a.emit(0xF3, 0x0F, 0x59, 0xC9)  # mulss xmm1, xmm1
    a.emit(0xF3, 0x0F, 0x58, 0xD1)  # addss xmm2, xmm1
    a.emit(0xF3, 0x0F, 0x51, 0xD2)  # sqrtss xmm2, xmm2
    a.emit(0xF3, 0x0F, 0x10, 0x5E, goal)  # movss xmm3, [esi+8]
    a.emit(0xF3, 0x0F, 0x5C, 0x58, pos)  # subss xmm3, [eax+0x38]  ; B
    a.emit(0xF3, 0x0F, 0x59, 0xDB)  # mulss xmm3, xmm3
    a.emit(0xF3, 0x0F, 0x10, 0x4E, goal + 4)  # movss xmm1, [esi+0xc]
    a.emit(0xF3, 0x0F, 0x5C, 0x48, pos + 4)  # subss xmm1, [eax+0x3c]
    a.emit(0xF3, 0x0F, 0x59, 0xC9)  # mulss xmm1, xmm1
    a.emit(0xF3, 0x0F, 0x58, 0xD9)  # addss xmm3, xmm1
    a.emit(0xF3, 0x0F, 0x51, 0xDB)  # sqrtss xmm3, xmm3
    a.emit(0xF3, 0x0F, 0x58, 0xD3)  # addss xmm2, xmm3
    a.emit(0xF3, 0x0F, 0x58, 0x15, _u32(layout.transit))  # addss xmm2, [transit]
    a.emit(0x0F, 0x2F, 0xC2)  # comiss xmm0, xmm2
    a.jcc(JBE, "pass_tunnel")  # walking is no longer than the tunnel (or a NaN): leave it

    # Only a unit A's contain would take: the filter, relationship and status tests, not capacity.
    a.emit(0x8B, 0x0C, 0x24)  # mov ecx, [esp]  ; A
    a.emit(0x8B, 0x89, _u32(OBJECT_CONTAIN))  # mov ecx, [ecx+0x258]
    a.emit(0x85, 0xC9)
    a.jcc(JE, "pass_tunnel")
    a.emit(0x6A, 0x00, 0x6A, 0x00, 0x57)  # push 0 / push 0 / push edi
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x90, _u32(CONTAIN_IS_VALID_CONTAINER_FOR_SLOT))  # call [eax+0x98]
    a.emit(0x84, 0xC0)
    a.jcc(JE, "pass_tunnel")
    a.call("alloc_entry")
    a.emit(0x85, 0xC0)
    a.jcc(JE, "pass_tunnel")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.call("fill_entry")
    a.emit(0xC6, 0x42, _PHASE, PHASE_ENTERING)  # mov byte [edx+0x18], 1
    a.emit(0xC6, 0x42, _ATTEMPTS, 0x00)  # mov byte [edx+0x19], 0
    a.emit(0xA1, _u32(LOGIC_FRAMES_PER_SECOND))  # mov eax, [fps]
    a.emit(0x6B, 0xC0, ENTER_SECONDS)  # imul eax, eax, 60
    a.emit(0x8B, 0x0D, _u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x03, 0x41, GAME_LOGIC_FRAME)  # add eax, [ecx+0x40]
    a.emit(0x89, 0x42, _DEADLINE)  # mov [edx+0x1c], eax
    _set_busy(a, layout, 1)
    a.emit(0x6A, AI_COMMAND_SOURCE_FROM_AI)  # push 2
    a.emit(0xFF, 0x74, 0x24, 0x04)  # push dword [esp+4]  ; A
    a.emit(0x8B, 0x4D, _i8(AI_DO_COMMAND_THIS_EBP))  # mov ecx, [ebp-0x10]
    a.call_absolute(AI_ENTER)
    _set_busy(a, layout, 0)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x61)  # popad
    a.jmp_absolute(AI_DO_COMMAND_TAIL)

    # Already in a tunnel: record where this order is going; the per-frame pass brings it out. A
    # unit with a route keeps its phase and its count of exits, so an order the AI repeats while it
    # is on its way out changes where it is going, never restarts the exit.
    a.label("inside")
    a.emit(0x8B, 0x81, _u32(OBJECT_CONTAIN))  # mov eax, [ecx+0x258]
    a.emit(0x85, 0xC0)
    a.jcc(JE, "pass")
    a.emit(0x81, 0x38, _u32(TUNNEL_CONTAIN_INTERFACE_VTABLE))  # cmp dword [eax], TunnelContain
    a.jcc(JNE, "pass")  # a horde member, a garrison, a transport: not ours
    a.call("network_player")
    a.emit(0x85, 0xC0)
    a.jcc(JE, "pass")
    a.call("find_entry")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc_short(JNE, "have_entry")
    a.call("alloc_entry")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(0x85, 0xD2)
    a.jcc(JE, "pass")
    a.emit(0xC6, 0x42, _PHASE, PHASE_INSIDE)  # mov byte [edx+0x18], 2
    a.emit(0xC6, 0x42, _ATTEMPTS, 0x00)  # mov byte [edx+0x19], 0
    a.label("have_entry")
    a.call("fill_entry")
    a.emit(0x61)  # popad
    a.jmp_absolute(AI_DO_COMMAND_TAIL)

    a.label("pass_tunnel")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4  ; A
    a.label("pass_player")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4  ; the player
    a.label("pass")
    a.emit(0x61)  # popad
    a.label("to_switch")
    a.jmp_absolute(AI_DO_COMMAND_SWITCH)


def _emit_tick(a: Asm, layout: Layout) -> None:
    """`TunnelContain::update`'s replacement: the stock update, then the routing pass once per logic
    frame. The stock sleep value goes back in `eax` untouched."""
    a.call_absolute(TUNNEL_CONTAIN_UPDATE)  # ecx is still the module
    a.emit(0x60)  # pushad
    a.call("run_tick")
    a.emit(0x61)  # popad
    a.emit(0xC3)  # ret

    a.label("run_tick")
    _frame_into_edx(a)
    a.emit(0x3B, 0x15, _u32(layout.last_tick))  # cmp edx, [last_tick]
    a.jcc(JE, "tick_done")
    a.emit(0x89, 0x15, _u32(layout.last_tick))  # mov [last_tick], edx
    a.emit(0xBE, _u32(layout.table))  # mov esi, table

    a.label("tick_entry")
    a.emit(0x83, 0x3E, 0x00)  # cmp dword [esi], 0
    a.jcc(JE, "tick_next")
    a.emit(0xFF, 0x36)  # push dword [esi]
    a.emit(0x8B, 0x0D, _u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(GAME_LOGIC_FIND_OBJECT_BY_ID)
    a.emit(0x8B, 0xF8)  # mov edi, eax
    a.emit(0x85, 0xFF)
    a.jcc(JE, "tick_free")  # gone
    a.emit(0x83, 0xBF, _u32(OBJECT_AI_UPDATE), 0x00)  # cmp dword [edi+0x260], 0
    a.jcc(JE, "tick_free")
    a.emit(0x8B, 0x8F, _u32(OBJECT_CONTAINED_BY))  # mov ecx, [edi+0x27c]
    a.emit(0x85, 0xC9)
    a.jcc(JE, "tick_outside")
    a.emit(0x8B, 0x81, _u32(OBJECT_CONTAIN))  # mov eax, [ecx+0x258]
    a.emit(0x85, 0xC0)
    a.jcc(JE, "tick_free")
    a.emit(0x81, 0x38, _u32(TUNNEL_CONTAIN_INTERFACE_VTABLE))  # cmp dword [eax], TunnelContain
    a.jcc(JNE, "tick_free")

    # In the network. Order the exit now, or again once the last one has had its time.
    _frame_into_edx(a)
    a.emit(0x80, 0x7E, _PHASE, PHASE_EXITING)  # cmp byte [esi+0x18], 3
    a.jcc_short(JNE, "exit_now")
    a.emit(0x3B, 0x56, _DEADLINE)  # cmp edx, [esi+0x1c]
    a.jcc(JB, "tick_next")
    a.emit(0xFE, 0x46, _ATTEMPTS)  # inc byte [esi+0x19]
    a.label("exit_now")
    a.emit(0xC6, 0x46, _PHASE, PHASE_EXITING)  # mov byte [esi+0x18], 3
    a.emit(0xA1, _u32(LOGIC_FRAMES_PER_SECOND))  # mov eax, [fps]
    a.emit(0x6B, 0xC0, EXIT_RETRY_SECONDS)  # imul eax, eax, 10
    a.emit(0x03, 0xC2)  # add eax, edx
    a.emit(0x89, 0x46, _DEADLINE)  # mov [esi+0x1c], eax
    a.emit(0x51)  # push ecx  ; the tunnel it is in, unless the goal's tunnel is found below
    a.emit(0x80, 0x7E, _ATTEMPTS, FALLBACK_ATTEMPT)  # cmp byte [esi+0x19], 2
    a.jcc_short(JAE, "exit_chosen")
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x85, 0xC0)
    a.jcc_short(JE, "exit_chosen")
    a.emit(0x83, 0xB8, _u32(PLAYER_TUNNEL_TRACKER), 0x00)  # cmp dword [eax+0x308], 0
    a.jcc_short(JE, "exit_chosen")
    a.emit(0x8D, 0x5E, _GOAL)  # lea ebx, [esi+8]
    a.call_absolute(PLAYER_NEAREST_TUNNEL)
    a.emit(0x85, 0xC0)
    a.jcc_short(JE, "exit_chosen")
    a.emit(0x89, 0x04, 0x24)  # mov [esp], eax
    a.label("exit_chosen")
    a.emit(0x5B)  # pop ebx  ; the tunnel to come out of
    a.call("issue_exit")
    a.jmp("tick_next")

    # Outside. Still walking to the door, or out and ready for its order.
    a.label("tick_outside")
    a.emit(0x80, 0x7E, _PHASE, PHASE_ENTERING)  # cmp byte [esi+0x18], 1
    a.jcc_short(JNE, "tick_reissue")
    _frame_into_edx(a)
    a.emit(0x3B, 0x56, _DEADLINE)  # cmp edx, [esi+0x1c]
    a.jcc_short(JAE, "tick_reissue")  # the enter has taken too long
    a.emit(0x8B, 0x8F, _u32(OBJECT_AI_UPDATE))  # mov ecx, [edi+0x260]
    a.call_absolute(AI_CURRENT_STATE_ID)
    a.emit(0x83, 0xF8, AI_STATE_IDLE)  # cmp eax, 0
    a.jcc(JNE, "tick_next")  # on its way in
    a.label("tick_reissue")
    a.call("reissue")
    a.label("tick_free")
    a.emit(0xC7, 0x06, _u32(0))  # mov dword [esi], 0
    a.label("tick_next")
    a.emit(0x83, 0xC6, ENTRY_SIZE)  # add esi, 0x20
    a.emit(0x81, 0xFE, _u32(layout.table_end))  # cmp esi, table_end
    a.jcc(JB, "tick_entry")
    a.label("tick_done")
    a.emit(0xC3)  # ret


def _emit_reset(a: Asm, layout: Layout) -> None:
    """`GameLogic::reset`'s replacement: forget every route, then the stock reset. The table holds
    `ObjectID`s, which a new match hands out again from the start."""
    a.emit(0x57, 0x51)  # push edi / push ecx
    a.emit(0xBF, _u32(layout.table))  # mov edi, table
    a.emit(0xB9, _u32(SLOTS * ENTRY_SIZE // 4))  # mov ecx, dwords
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0xF3, 0xAB)  # rep stosd
    a.emit(0xC7, 0x05, _u32(layout.last_tick), _u32(0xFFFFFFFF))  # mov dword [last_tick], -1
    _set_busy(a, layout, 0)
    a.emit(0x59, 0x5F)  # pop ecx / pop edi
    a.jmp_absolute(GAME_LOGIC_RESET)


def _emit_helpers(a: Asm, layout: Layout) -> None:
    """The routines both hooks share. Each preserves `ebx`, `esi`, `edi` and `ebp`."""

    # find_entry(edi = Object) -> eax = its entry, or 0. Clobbers ecx.
    a.label("find_entry")
    a.emit(0x8B, 0x4F, OBJECT_ID)  # mov ecx, [edi+0x74]
    a.emit(0xB8, _u32(layout.table))  # mov eax, table
    a.label("find_loop")
    a.emit(0x39, 0x08)  # cmp [eax], ecx
    a.jcc_short(JE, "find_done")
    a.emit(0x83, 0xC0, ENTRY_SIZE)  # add eax, 0x20
    a.emit(0x3D, _u32(layout.table_end))  # cmp eax, table_end
    a.jcc_short(JB, "find_loop")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("find_done")
    a.emit(0xC3)

    # alloc_entry() -> eax = a free entry, or 0.
    a.label("alloc_entry")
    a.emit(0xB8, _u32(layout.table))  # mov eax, table
    a.label("alloc_loop")
    a.emit(0x83, 0x38, 0x00)  # cmp dword [eax], 0
    a.jcc_short(JE, "alloc_done")
    a.emit(0x83, 0xC0, ENTRY_SIZE)  # add eax, 0x20
    a.emit(0x3D, _u32(layout.table_end))  # cmp eax, table_end
    a.jcc_short(JB, "alloc_loop")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("alloc_done")
    a.emit(0xC3)

    # drop_entry(edi = Object): forget its route, if it has one.
    a.label("drop_entry")
    a.call("find_entry")
    a.emit(0x85, 0xC0)
    a.jcc_short(JE, "drop_done")
    a.emit(0xC7, 0x00, _u32(0))  # mov dword [eax], 0
    a.label("drop_done")
    a.emit(0xC3)

    # network_player(edi = Object) -> eax = its controlling player if that is a computer player
    # with a tunnel network, else 0. Clobbers ecx and edx.
    a.label("network_player")
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x85, 0xC0)
    a.jcc_short(JE, "network_done")
    a.emit(0x83, 0x78, PLAYER_TYPE, PLAYER_TYPE_COMPUTER)  # cmp dword [eax+0x5c], 1
    a.jcc_short(JNE, "network_none")
    a.emit(0x83, 0xB8, _u32(PLAYER_TUNNEL_TRACKER), 0x00)  # cmp dword [eax+0x308], 0
    a.jcc_short(JNE, "network_done")
    a.label("network_none")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("network_done")
    a.emit(0xC3)

    # fill_entry(edx = entry, edi = Object, esi = AICommandParms): who, and the order. The phase
    # and the exit count are the caller's.
    a.label("fill_entry")
    a.emit(0x8B, 0x47, OBJECT_ID)  # mov eax, [edi+0x74]
    a.emit(0x89, 0x42, _ID)  # mov [edx], eax
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.emit(0x89, 0x42, _CMD)  # mov [edx+4], eax
    for word in range(3):
        a.emit(0x8B, 0x46, AI_COMMAND_POSITION_OFFSET + 4 * word)  # mov eax, [esi+8+4n]
        a.emit(0x89, 0x42, _GOAL + 4 * word)  # mov [edx+8+4n], eax
    a.emit(0x8B, 0x46, AI_COMMAND_INT_VALUE_OFFSET)  # mov eax, [esi+0x34]
    a.emit(0x89, 0x42, _SHOTS)  # mov [edx+0x14], eax
    a.emit(0xC3)

    # issue_exit(edi = Object, ebx = tunnel): the order Evacuate gives that passenger.
    a.label("issue_exit")
    _set_busy(a, layout, 1)
    a.emit(0x6A, AI_COMMAND_SOURCE_FROM_AI, 0x53)  # push 2 / push ebx
    a.emit(0x8B, 0x8F, _u32(OBJECT_CONTAIN))  # mov ecx, [edi+0x258]
    a.emit(0x85, 0xC9)
    a.jcc_short(JE, "exit_single")
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, CONTAIN_GET_HORDE_IFACE_SLOT)  # call [eax+0x7c]
    a.emit(0x85, 0xC0)
    a.jcc_short(JE, "exit_single")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0xFF, 0x92, _u32(HORDE_IFACE_EXIT_SLOT))  # call [edx+0x84]  ; the whole battalion
    a.jmp_short("exit_done")
    a.label("exit_single")
    a.emit(0x8B, 0x8F, _u32(OBJECT_AI_UPDATE))  # mov ecx, [edi+0x260]
    a.emit(0x83, 0xC1, 0x20)  # add ecx, 0x20
    a.call_absolute(AI_EXIT)
    a.label("exit_done")
    _set_busy(a, layout, 0)
    a.emit(0xC3)

    # reissue(edi = Object, esi = entry): the recorded order, given again past the routing.
    a.label("reissue")
    _set_busy(a, layout, 1)
    a.emit(0x8B, 0x8F, _u32(OBJECT_AI_UPDATE))  # mov ecx, [edi+0x260]
    a.emit(0x83, 0xC1, 0x20)  # add ecx, 0x20
    a.emit(0x8D, 0x46, _GOAL)  # lea eax, [esi+8]
    a.emit(0x6A, AI_COMMAND_SOURCE_FROM_AI)  # push 2
    a.emit(0x83, 0x7E, _CMD, AI_CMD_ATTACK_MOVE_TO_POSITION)  # cmp dword [esi+4], 0xf
    a.jcc_short(JE, "reissue_attack")
    a.emit(0x50)  # push eax
    a.call_absolute(AI_MOVE_TO_POSITION)
    a.jmp_short("reissue_done")
    a.label("reissue_attack")
    a.emit(0xFF, 0x76, _SHOTS)  # push dword [esi+0x14]
    a.emit(0x50)  # push eax
    a.call_absolute(AI_ATTACK_MOVE_TO_POSITION)
    a.label("reissue_done")
    _set_busy(a, layout, 0)
    a.emit(0xC3)


def build_section(base_va: int, transit_cost: float = DEFAULT_TRANSIT_COST) -> bytes:
    """The whole cave: the data words, an empty table, then the code."""
    layout = Layout(base_va)
    head = struct.pack("<fII", float(transit_cost), 0, 0xFFFFFFFF).ljust(_TABLE, b"\0")
    return head + bytes(SLOTS * ENTRY_SIZE) + layout.code


class AiTunnelRoutingPatch(Patch):
    """The skirmish AI routes moves through its tunnel network when that is shorter."""

    name = "ai-tunnel-routing"
    author = "officialNecro"
    description = (
        "Let the skirmish AI route a unit through its own tunnel network: a move or attack-move "
        "the AI gives is replaced by entering the tunnel nearest the unit when the walk from the "
        "tunnel nearest the goal, plus --transit-cost, is shorter, and the unit comes out there "
        "and carries on. Units are never left inside: a failed enter falls back to walking, and "
        "an exit that does not happen is retried, then made at the tunnel the unit is in. No INI "
        "change"
    )

    def __init__(self, transit_cost: int = DEFAULT_TRANSIT_COST) -> None:
        if not 0 <= transit_cost <= 100_000:
            raise ValueError(f"transit cost {transit_cost} is outside 0..100000 world units")
        self.transit_cost = transit_cost

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--transit-cost",
            type=int,
            default=DEFAULT_TRANSIT_COST,
            help=(
                f"world units charged per trip through the network (default {DEFAULT_TRANSIT_COST})"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        return cls(transit_cost=args.transit_cost)

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        _check_anchors(data)
        slot_offs = {}
        for slot, stock in VTABLE_SLOTS.items():
            off = va_to_offset(data, slot)
            if off is None:
                raise ValueError(f"vtable slot {slot:#010x} is not mapped - not the expected build")
            held = struct.unpack_from("<I", data, off)[0]
            if held != stock:
                raise ValueError(
                    f"vtable slot {slot:#010x} holds {held:#010x}, expected {stock:#010x} - "
                    "another patch has taken it, or this is not the expected build"
                )
            slot_offs[slot] = off

        base = allocate_section(
            data, SECTION_NAME, lambda va: build_section(va, self.transit_cost), _CHARACTERISTICS
        )
        layout = Layout(base)
        jump = b"\xe9" + struct.pack("<i", layout.dispatch - (HOOK_VA + 5)) + b"\x90"
        apply_byte_patch(
            data, hook_off, HOOK_ORIGINAL, jump, "aiDoCommand switch -> tunnel routing"
        )
        struct.pack_into("<I", data, slot_offs[TUNNEL_CONTAIN_UPDATE_VTABLE_SLOT], layout.tick)
        for slot in GAME_LOGIC_RESET_VTABLE_SLOTS:
            struct.pack_into("<I", data, slot_offs[slot], layout.reset)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        base, section_off, _ = located
        layout = Layout(base)
        problems: list[str] = []
        transit = struct.unpack_from("<f", data, section_off + _TRANSIT)[0]
        if transit != float(self.transit_cost):
            problems.append(f"transit cost is {transit}, expected {self.transit_cost}")
        code_off = section_off + _CODE
        if bytes(data[code_off : code_off + len(layout.code)]) != layout.code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected code")
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [*problems, f"{HOOK_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            problems.append(f"{HOOK_VA:#010x} is not a jmp - the dispatch hook is not installed")
        elif HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0] != layout.dispatch:
            problems.append(f"the dispatch hook does not jump to {layout.dispatch:#010x}")
        wanted = {
            TUNNEL_CONTAIN_UPDATE_VTABLE_SLOT: layout.tick,
            **dict.fromkeys(GAME_LOGIC_RESET_VTABLE_SLOTS, layout.reset),
        }
        for slot, target in wanted.items():
            slot_off = va_to_offset(data, slot)
            if slot_off is None or struct.unpack_from("<I", data, slot_off)[0] != target:
                problems.append(f"vtable slot {slot:#010x} does not point at {target:#010x}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        try:
            located = find_section(data, SECTION_NAME)
            if located is None:
                return None
            transit = struct.unpack_from("<f", data, located[1] + _TRANSIT)[0]
            if transit != int(transit):
                return None
            patch = cls(transit_cost=int(transit))
            return None if patch.verify(data) else patch
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None


def _check_anchors(data: bytes | bytearray) -> None:
    for va, expected in ANCHORS.items():
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the AI command or "
                "tunnel code is not this build's, so the cave would call or read the wrong thing"
            )
