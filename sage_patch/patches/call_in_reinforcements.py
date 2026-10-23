"""A script action that calls a War of the Ring reinforcement army into the battle by its overworld
`ScriptingName`, without the player clicking its banner.

It gives the stock `CALL_IN_REINFORCEMENTS_WITHOUT_MOVIE` action (543), which does nothing
unpatched, a body. The action finds the army by name, checks that it is one of the armies in this
battle, and if it is still waiting, summoning or ready, calls it in at once: the same
`roster.callIn()` the banner's second click reaches through `MSG_CALL_IN_REINFORCEMENTS`, minus
the countdown and the movie. It runs in game logic, as the AI's own call-in does, so every machine
in a multiplayer battle runs it alike.

Derivation: `../docs/living-campaign/reinforcements.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    LIVING_WORLD_ARMY_ROSTER_ID,
    LIVING_WORLD_ARMY_ROSTER_OFFSET,
    LIVING_WORLD_BATTLE_ARMY_IDS_BEGIN,
    LIVING_WORLD_BATTLE_ARMY_IDS_END,
    LIVING_WORLD_BATTLE_BRIDGE_OFFSET,
    LIVING_WORLD_FIND_ARMY_BY_NAME,
    LIVING_WORLD_FIND_ARMY_BY_NAME_BYTES,
    LIVING_WORLD_ROSTER_CALL_IN,
    LIVING_WORLD_ROSTER_CALL_IN_BYTES,
    LIVING_WORLD_ROSTER_STATE,
    ROSTER_STATE_CALLED_IN,
    ROSTER_STATE_IN_BATTLE,
    ROSTER_STATE_READY,
    SCRIPT_ACTION_EPILOGUE,
    SCRIPT_ACTION_JUMP_TABLE,
    SCRIPT_ACTION_PARAM_ARRAY,
    SCRIPT_ACTION_PARAM_COUNT,
    SCRIPT_PARAMETER_STRING,
    THE_GAME_LOGIC,
    THE_LIVING_WORLD_LOGIC,
)
from ..asm import JAE, JE, JL, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section

__all__ = [
    "ACTION_ID",
    "ANCHORS",
    "SECTION_NAME",
    "TABLE_SLOT_STOCK",
    "TABLE_SLOT_VA",
    "CallInReinforcementsPatch",
    "build_code",
]

SECTION_NAME = ".callin"

#: `CALL_IN_REINFORCEMENTS_WITHOUT_MOVIE`, WorldBuilder's "ReinforcementArmies/Call in army
#: clean.", whose one parameter is a free string: "Call in reinforcement army named <name>.". It
#: appears **zero** times across the 480-map Edain corpus, so no existing map changes behaviour.
ACTION_ID = 543

#: The jump-table slot this patch takes over, and the dword it must hold first: the shared
#: epilogue, which is what a stub dispatches to.
TABLE_SLOT_VA = SCRIPT_ACTION_JUMP_TABLE + ACTION_ID * 4
TABLE_SLOT_STOCK = struct.pack("<I", SCRIPT_ACTION_EPILOGUE)

#: Every engine routine the cave calls or returns into, by its first instructions. The epilogue's
#: `mov ecx, [ebp-0xc]` is the SEH unwind every case body leaves through.
ANCHORS = {
    SCRIPT_ACTION_EPILOGUE: bytes.fromhex("8b4df4"),
    LIVING_WORLD_FIND_ARMY_BY_NAME: LIVING_WORLD_FIND_ARMY_BY_NAME_BYTES,
    LIVING_WORLD_ROSTER_CALL_IN: LIVING_WORLD_ROSTER_CALL_IN_BYTES,
}

_IDS_BEGIN = LIVING_WORLD_BATTLE_BRIDGE_OFFSET + LIVING_WORLD_BATTLE_ARMY_IDS_BEGIN
_IDS_END = LIVING_WORLD_BATTLE_BRIDGE_OFFSET + LIVING_WORLD_BATTLE_ARMY_IDS_END


def build_code(base_va: int) -> bytes:
    """The action body. Entered from the jump table with `esi` = the ScriptAction and `edi` = the
    ScriptActions object; it leaves through the shared epilogue with the stack as it found it."""
    a = Asm(base_va)
    a.emit(0x83, 0x7E, SCRIPT_ACTION_PARAM_COUNT, 0x01)  # cmp dword [esi+8], 1
    a.jcc(JL, "done")
    a.emit(0x8B, 0x46, SCRIPT_ACTION_PARAM_ARRAY)  # mov eax, [esi+0xc]   ; Parameter *0
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")

    # An empty name compares equal to every army without a ScriptingName, so refuse it rather
    # than call in whichever unnamed army the walk meets first.
    a.emit(0x8B, 0x48, SCRIPT_PARAMETER_STRING)  # mov ecx, [eax+0x10]  ; AsciiString buffer
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "done")
    a.emit(0x80, 0x79, 0x08, 0x00)  # cmp byte [ecx+8], 0
    a.jcc(JE, "done")

    a.emit(0x8B, 0x0D, struct.pack("<I", THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "done")
    a.emit(0x83, 0xC0, SCRIPT_PARAMETER_STRING)  # add eax, 0x10        ; &param->string
    a.emit(0x50)  # push eax
    a.call_absolute(LIVING_WORLD_FIND_ARMY_BY_NAME)  # thiscall, ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0x50, LIVING_WORLD_ARMY_ROSTER_OFFSET)  # mov edx, [eax+0x78]  ; the roster
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "done")

    # Only an army in **this** battle. Every other army on the board is `WAITING` too - it is the
    # roster's resting state - and calling one in would spawn it on a map it is not fighting on.
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "done")
    a.emit(0x8B, 0x42, LIVING_WORLD_ARMY_ROSTER_ID)  # mov eax, [edx+0x1c]  ; the army id
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xB1, struct.pack("<I", _IDS_BEGIN))  # mov esi, [ecx+0x198]
    a.emit(0x8B, 0x89, struct.pack("<I", _IDS_END))  # mov ecx, [ecx+0x19c]
    a.label("scan")
    a.emit(0x3B, 0xF1)  # cmp esi, ecx
    a.jcc(JAE, "absent")
    a.emit(0x39, 0x06)  # cmp [esi], eax
    a.jcc(JE, "present")
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4
    a.jmp("scan")
    a.label("absent")
    a.emit(0x5E)  # pop esi
    a.jmp("done")
    a.label("present")
    a.emit(0x5E)  # pop esi

    # `WAITING`, `SUMMONING` and `READY` are the states a banner still offers; `IN_BATTLE` fought
    # from the start and `CALLED_IN` has already arrived. Promoting to `READY` is what lets the
    # engine's own `callIn` take it from there, countdown or none.
    a.emit(0x8B, 0x42, LIVING_WORLD_ROSTER_STATE)  # mov eax, [edx+0x2c]
    a.emit(0x83, 0xF8, ROSTER_STATE_IN_BATTLE)  # cmp eax, 1
    a.jcc(JE, "done")
    a.emit(0x83, 0xF8, ROSTER_STATE_CALLED_IN)  # cmp eax, 4
    a.jcc(JAE, "done")
    # mov dword [edx+0x2c], READY
    a.emit(0xC7, 0x42, LIVING_WORLD_ROSTER_STATE, struct.pack("<I", ROSTER_STATE_READY))
    a.emit(0x8B, 0xCA)  # mov ecx, edx
    a.call_absolute(LIVING_WORLD_ROSTER_CALL_IN)  # thiscall, no args
    a.label("done")
    a.jmp_absolute(SCRIPT_ACTION_EPILOGUE)
    return a.finish()


class CallInReinforcementsPatch(Patch):
    name = "call-in-reinforcements"
    author = "officialNecro"
    description = (
        "A script action that calls a War of the Ring reinforcement army into the battle by its "
        "overworld ScriptingName, without the player clicking its banner. No INI change: in "
        "WorldBuilder's action browser take ReinforcementArmies -> 'Call in army clean.', "
        "which does nothing in the unpatched engine, and type the army's ScriptingName - the "
        "line reads "
        "'Call in reinforcement army named <name>.'. The army arrives at once, skipping its "
        "countdown and its movie, and its banner clears. An army that is not in this battle, "
        "fought from the start or has already arrived is left alone"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        self._check_stock(data)
        base = allocate_section(data, SECTION_NAME, build_code, 0x60000020)
        apply_byte_patch(
            data,
            file_offset(data, TABLE_SLOT_VA),
            TABLE_SLOT_STOCK,
            struct.pack("<I", base),
            f"script action {ACTION_ID} stub -> call-in-reinforcements cave",
        )

    @staticmethod
    def _check_stock(data: bytes | bytearray) -> None:
        """Raise unless the action is still a stub and every routine the cave reaches holds what
        it was written against."""
        sites = {**ANCHORS, TABLE_SLOT_VA: TABLE_SLOT_STOCK}
        for va, expected in sites.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build at {va:#010x}: expected {expected.hex()} got {got.hex()}"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section"]
        base, off, size = located
        code = build_code(base)
        problems = []
        if size < len(code) or bytes(data[off : off + len(code)]) != code:
            problems.append(f"unexpected {SECTION_NAME} body")
        slot = struct.unpack_from("<I", data, file_offset(data, TABLE_SLOT_VA))[0]
        if slot != base:
            problems.append(f"action {ACTION_ID} dispatches to {slot:#010x}, not {base:#010x}")
        for va, expected in ANCHORS.items():
            at = file_offset(data, va)
            if bytes(data[at : at + len(expected)]) != expected:
                problems.append(f"unexpected bytes at {va:#010x}")
        return problems
