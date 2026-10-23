"""Add two `AISpecialPowerUpdate` types that cast at the AI player's own objects.

No stock `SpecialPowerAIType` aims at an allied object, so a `NEED_TARGET_ALLY_OBJECT` power
has no AI hook. The stock building types (`AI_SPELLBOOK_BUFFECONOMYBUILDING`) cast at a building's
*position* and check it with the point test, which an object-target power always fails. This
patch adds:

- `AI_SPECIAL_POWER_ALLY_OBJECT` (index 53), for a power on an allied unit (Edain's Might of the
  Witch-king, a banner promotion, a hero-on-hero buff). Its picker walks the AI player's own unit
  list, the list `AI_SPELLBOOK_ASSIST_BATTLE_*` walks, so it reaches the whole map at the cost of
  one pass over the player's units. It takes a unit that is fighting (its AI has a current
  victim) and that the button accepts as a target (`CommandButton::isValidToUseOn`: the
  relationship, the power's `ObjectFilter`, `MaxCastRange`). Among those it prefers a `HERO`,
  then the lowest health ratio.
- `AI_SPECIAL_POWER_ALLY_STRUCTURE` (index 54), for a power on an own building (Edain's
  Establish Vineyard). Its picker walks the player's two building lists in
  `TheSkirmishAIManager`'s record, the structures (`+8`, the list `AI_SPELLBOOK_REBUILD` walks)
  and then the economy buildings (`+0xC`, the list `AI_SPELLBOOK_BUFFECONOMYBUILDING` walks), and
  takes the first one the button accepts. It doesn't wait for a fight, so it works on a caster
  with no weapon.

Both casts are the enemy-killer type's at-object cast. `SpecialPowerRange` and
`SpecialPowerRadius` are not read. Each behaviour is an enemy-killer behaviour with its picker slot
replaced, so its wake-up timing and cast are stock.

Three edits, none on bytes another patch rewrites:

- the parser's name-table read is pointed at a copy of the table with the new names appended, and
  its loop bound raised by two;
- the factory's out-of-range branch, the 4 bytes past what `ai-rebuild-gate` anchors, goes to a
  case that builds the new behaviours, and on to the stock exit for anything else.

An unpatched `game.dat` reading either name leaves the hook without a behaviour: it never casts
and nothing crashes. `AiAllyTargetsWorldbuilderPatch` teaches the editor the names, which it would
otherwise stop on with an assert box.

Derivation: `../docs/ai-ally-targets.md`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from sage_ini.engine import Engine, EnumDelta

from ..addresses import (
    AI_CURRENT_VICTIM,
    AI_CURRENT_VICTIM_BYTES,
    AI_KILLER_BEHAVIOR_CTOR,
    AI_KILLER_BEHAVIOR_CTOR_BYTES,
    AI_KILLER_BEHAVIOR_SIZE,
    AI_KILLER_BEHAVIOR_VTABLE,
    AI_KILLER_BEHAVIOR_VTABLE_SLOTS,
    AI_KILLER_PICKER,
    AI_REBUILD_PICKER_VTABLE_SLOT,
    BODY_GET_HEALTH_RATIO_SLOT,
    COMMAND_BUTTON_IS_VALID_TO_USE_ON,
    COMMAND_BUTTON_IS_VALID_TO_USE_ON_ENTRY,
    COMMAND_BUTTON_IS_VALID_TO_USE_ON_EXIT,
    COMMAND_BUTTON_IS_VALID_TO_USE_ON_EXIT_BYTES,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    KINDOF_HERO_BIT,
    KINDOF_HERO_BYTE,
    OBJECT_AI_UPDATE,
    OBJECT_BODY_MODULE,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_GET_CONTROLLING_PLAYER_ENTRY,
    OBJECT_THING_TEMPLATE,
    OPERATOR_NEW,
    SKIRMISH_AI_ID_LIST_BEGIN,
    SKIRMISH_AI_PLAYER_RECORD,
    SKIRMISH_AI_PLAYER_RECORD_ENTRY,
    SKIRMISH_AI_RECORD_ECONOMY,
    SKIRMISH_AI_RECORD_STRUCTURES,
    SKIRMISH_AI_RECORD_UNITS,
    SPELLBOOK_AI_TYPE_COUNT,
    SPELLBOOK_AI_TYPE_FACTORY,
    SPELLBOOK_AI_TYPE_FACTORY_ENTRY,
    SPELLBOOK_AI_TYPE_FACTORY_EXIT,
    SPELLBOOK_AI_TYPE_FACTORY_EXIT_BYTES,
    SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK,
    SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK_BYTES,
    SPELLBOOK_AI_TYPE_FACTORY_RETURN,
    SPELLBOOK_AI_TYPE_NAMES,
    SPELLBOOK_AI_TYPE_PARSE_BOUND,
    SPELLBOOK_AI_TYPE_PARSE_BOUND_BYTES,
    SPELLBOOK_AI_TYPE_PARSE_TABLE_READ,
    SPELLBOOK_AI_TYPE_PARSE_TABLE_READ_BYTES,
    SPELLBOOK_SET_TARGET_OBJECT,
    SPELLBOOK_SET_TARGET_OBJECT_BYTES,
    THE_GAME_LOGIC,
    THE_SKIRMISH_AI_MANAGER,
)
from ..asm import JA, JAE, JB, JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, u32
from .utils import name_tables

__all__ = [
    "ALLY_OBJECT_INDEX",
    "ALLY_OBJECT_NAME",
    "ALLY_STRUCTURE_INDEX",
    "ALLY_STRUCTURE_NAME",
    "ANCHORS",
    "GAME",
    "NAMES",
    "SECTION_NAME",
    "STRUCTURE_LISTS",
    "WORLDBUILDER",
    "WORLDBUILDER_SECTION_NAME",
    "AiAllyTargetsPatch",
    "AiAllyTargetsWorldbuilderPatch",
    "Layout",
    "build_section",
    "layout",
]

ALLY_OBJECT_NAME = "AI_SPECIAL_POWER_ALLY_OBJECT"
ALLY_STRUCTURE_NAME = "AI_SPECIAL_POWER_ALLY_STRUCTURE"
#: In table order: the first parses to one past the stock names, so every stock index is
#: unchanged, and the second to the one after.
NAMES = (ALLY_OBJECT_NAME, ALLY_STRUCTURE_NAME)
ALLY_OBJECT_INDEX = SPELLBOOK_AI_TYPE_COUNT
ALLY_STRUCTURE_INDEX = SPELLBOOK_AI_TYPE_COUNT + 1

#: The record's building lists `AI_SPECIAL_POWER_ALLY_STRUCTURE` walks, in order.
STRUCTURE_LISTS = (SKIRMISH_AI_RECORD_STRUCTURES, SKIRMISH_AI_RECORD_ECONOMY)

SECTION_NAME = ".aially"
WORLDBUILDER_SECTION_NAME = ".wbaialy"

#: The first and last stock names. Checking both ends of the table proves its length as well as
#: its identity.
_FIRST_NAME = "AI_SPECIAL_POWER_BASIC_SELF_BUFF"
_GAME_LAST_NAME = "AI_SPECIAL_POWER_GOBLIN_POISON"


@dataclass(frozen=True)
class _Target:
    """Where one binary keeps the `SpecialPowerAIType` names, and the parser that reads them."""

    binary: str
    table_va: int
    count: int
    last_name: str
    #: The instruction holding the table's address as a disp32, and where in it the disp32 sits.
    read_va: int
    read_bytes: bytes
    read_disp_at: int
    #: The loop bound: the instruction comparing the index against `count`, and its imm8.
    bound_va: int
    bound_bytes: bytes
    bound_imm_at: int


GAME = _Target(
    "game.dat",
    SPELLBOOK_AI_TYPE_NAMES,
    SPELLBOOK_AI_TYPE_COUNT,
    _GAME_LAST_NAME,
    SPELLBOOK_AI_TYPE_PARSE_TABLE_READ,
    SPELLBOOK_AI_TYPE_PARSE_TABLE_READ_BYTES,
    3,
    SPELLBOOK_AI_TYPE_PARSE_BOUND,
    SPELLBOOK_AI_TYPE_PARSE_BOUND_BYTES,
    2,
)

#: Worldbuilder's copy holds 51 names, two fewer than the game's, and is read by a name-to-index
#: helper (0x014A6090) that raises a `DEBUG_CRASH` box on a name it does not find. The editor runs
#: no AI, so only the parse matters there and the indices the names get are irrelevant.
WORLDBUILDER = _Target(
    "Worldbuilder.exe",
    0x02247A20,
    51,
    "AI_SPECIAL_POWER_RANGED_AOE_ATTACK_UNITS",
    0x014A60DB,
    bytes.fromhex("8b148d207a2402"),  # mov edx, [ecx*4 + 0x2247A20]
    3,
    0x014A60CE,
    bytes.fromhex("837dec33"),  # cmp dword [ebp-0x14], 0x33
    3,
)

#: The factory's own registers at the range check: `eax` is the index, `esi` was pushed and is
#: popped by the shared epilogue, `ebp` frames `[ebp-0xC]`, the saved SEH link the epilogue reads.
#: Everything the case jumps back to is anchored; the range check's own bytes are asserted by
#: `apply_byte_patch`.
ANCHORS = {
    SPELLBOOK_AI_TYPE_FACTORY: SPELLBOOK_AI_TYPE_FACTORY_ENTRY,
    SPELLBOOK_AI_TYPE_FACTORY_EXIT: SPELLBOOK_AI_TYPE_FACTORY_EXIT_BYTES,
    AI_KILLER_BEHAVIOR_CTOR: AI_KILLER_BEHAVIOR_CTOR_BYTES,
    SPELLBOOK_SET_TARGET_OBJECT: SPELLBOOK_SET_TARGET_OBJECT_BYTES,
    SKIRMISH_AI_PLAYER_RECORD: SKIRMISH_AI_PLAYER_RECORD_ENTRY,
    COMMAND_BUTTON_IS_VALID_TO_USE_ON: COMMAND_BUTTON_IS_VALID_TO_USE_ON_ENTRY,
    COMMAND_BUTTON_IS_VALID_TO_USE_ON_EXIT: COMMAND_BUTTON_IS_VALID_TO_USE_ON_EXIT_BYTES,
    AI_CURRENT_VICTIM: AI_CURRENT_VICTIM_BYTES,
    GAME_LOGIC_FIND_OBJECT_BY_ID: GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER: OBJECT_GET_CONTROLLING_PLAYER_ENTRY,
    OPERATOR_NEW: bytes.fromhex("8b4424046a00"),
}

# The unit picker's locals, `esp`-relative once its prologue has run: four saved registers (16
# bytes) and 0x14 bytes of locals sit above the return address, so the caster argument is at +0x28.
_BEST_RATIO = 0x00
_BEST_RANK = 0x04
_CANDIDATE = 0x08
_CANDIDATE_RANK = 0x0C
_CANDIDATE_RATIO = 0x10
_LOCALS = 0x14
_CASTER = _LOCALS + 16 + 4

#: Ranks: 0 is "nothing picked yet", so any candidate beats it; a hero beats any other unit.
_RANK_UNIT = 1

# The structure picker's locals, laid out the same way: the end of the list being walked, the
# record offset of that list, and the candidate across the validity call.
_S_END = 0x00
_S_LIST = 0x04
_S_CANDIDATE = 0x08
_S_LOCALS = 0x0C
_S_CASTER = _S_LOCALS + 16 + 4


@dataclass(frozen=True)
class Layout:
    """Where each piece of the cave sits."""

    table: int
    object_vtable: int
    structure_vtable: int
    names: tuple[int, ...]
    factory_case: int
    object_picker: int
    structure_picker: int


def _vtable(killer_slots: tuple[int, ...], picker_va: int) -> bytes:
    slots = list(killer_slots)
    slots[AI_REBUILD_PICKER_VTABLE_SLOT // 4] = picker_va
    return b"".join(u32(slot) for slot in slots)


def _factory_case(base_va: int, object_vtable: int, structure_vtable: int) -> bytes:
    """Reached from the factory's out-of-range branch with the parsed index in `eax`."""
    a = Asm(base_va)
    a.emit(0xBA, u32(object_vtable))  # mov edx, object vtable
    a.emit(0x83, 0xF8, ALLY_OBJECT_INDEX)  # cmp eax, 53
    a.jcc(JE, "build")
    a.emit(0xBA, u32(structure_vtable))  # mov edx, structure vtable
    a.emit(0x83, 0xF8, ALLY_STRUCTURE_INDEX)  # cmp eax, 54
    a.jcc(JNE, "none")
    a.label("build")
    a.emit(0x52)  # push edx                     ; the vtable, across the two calls
    a.emit(0x6A, AI_KILLER_BEHAVIOR_SIZE)  # push 0x40
    a.call_absolute(OPERATOR_NEW)  # cdecl
    a.emit(0x59)  # pop ecx
    a.emit(0x5A)  # pop edx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "none")
    a.emit(0x52)  # push edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(AI_KILLER_BEHAVIOR_CTOR)  # returns this
    a.emit(0x5A)  # pop edx
    a.emit(0x89, 0x10)  # mov [eax], edx
    a.jmp_absolute(SPELLBOOK_AI_TYPE_FACTORY_RETURN)
    a.label("none")
    a.jmp_absolute(SPELLBOOK_AI_TYPE_FACTORY_EXIT)  # the stock "no behaviour" exit
    return a.finish()


def _object_picker(base_va: int) -> bytes:
    """Vtable slot 7: `__thiscall(Object *caster)` on the behaviour, `ret 4`, `al` = cast now.

    Registers across the loop: `esi` the behaviour, `edi` the id iterator, `ebp` the list's end,
    `ebx` the best candidate so far. The engine calls preserve all four. The x87 stack is empty at
    every call: a candidate's health ratio is stored to a local before `isValidToUseOn` runs.
    """
    a = Asm(base_va)
    a.emit(0x55, 0x53, 0x56, 0x57)  # push ebp, ebx, esi, edi
    a.emit(0x83, 0xEC, _LOCALS)  # sub esp, 0x14
    a.emit(0x8B, 0xF1)  # mov esi, ecx
    a.emit(0x33, 0xDB)  # xor ebx, ebx
    a.emit(0x89, 0x5C, 0x24, _BEST_RANK)  # mov [esp+best_rank], ebx
    a.emit(0x53)  # push ebx                     ; NULL: clear any earlier target
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(SPELLBOOK_SET_TARGET_OBJECT)

    a.emit(0x8B, 0x4C, 0x24, _CASTER)  # mov ecx, [esp+caster]
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0x0D, u32(THE_SKIRMISH_AI_MANAGER))  # mov ecx, [TheSkirmishAIManager]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "done")
    a.emit(0x50)  # push eax                     ; the player
    a.call_absolute(SKIRMISH_AI_PLAYER_RECORD)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0x40, SKIRMISH_AI_RECORD_UNITS)  # mov eax, [eax]  ; the unit list
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0x78, SKIRMISH_AI_ID_LIST_BEGIN)  # mov edi, [eax+4]
    a.emit(0x8B, 0x68, SKIRMISH_AI_ID_LIST_BEGIN + 4)  # mov ebp, [eax+8]

    a.label("next")
    a.emit(0x3B, 0xFD)  # cmp edi, ebp
    a.jcc(JAE, "done")
    a.emit(0xFF, 0x37)  # push dword [edi]           ; the id
    a.emit(0x83, 0xC7, 0x04)  # add edi, 4
    a.emit(0x8B, 0x0D, u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(GAME_LOGIC_FIND_OBJECT_BY_ID)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")
    a.emit(0x3B, 0x44, 0x24, _CASTER)  # cmp eax, [esp+caster]
    a.jcc(JE, "next")

    # Fighting: an AI with a current victim. The candidate rides the stack across the call, and
    # `pop` leaves the flags of the `test` alone.
    a.emit(0x8B, 0x88, u32(OBJECT_AI_UPDATE))  # mov ecx, [eax+0x260]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "next")
    a.emit(0x50)  # push eax
    a.call_absolute(AI_CURRENT_VICTIM)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.emit(0x58)  # pop eax
    a.jcc(JE, "next")

    # Rank: 2 for a hero, 1 otherwise. A worse rank than the best is out before anything costs.
    a.emit(0x8B, 0x48, OBJECT_THING_TEMPLATE)  # mov ecx, [eax+4]
    a.emit(0x33, 0xD2)  # xor edx, edx
    a.emit(0xF6, 0x81, u32(KINDOF_HERO_BYTE), KINDOF_HERO_BIT)  # test byte [ecx+0x113], 4
    a.emit(0x0F, 0x95, 0xC2)  # setnz dl
    a.emit(0x83, 0xC2, _RANK_UNIT)  # add edx, 1
    a.emit(0x3B, 0x54, 0x24, _BEST_RANK)  # cmp edx, [esp+best_rank]
    a.jcc(JB, "next")
    a.emit(0x89, 0x44, 0x24, _CANDIDATE)  # mov [esp+candidate], eax
    a.emit(0x89, 0x54, 0x24, _CANDIDATE_RANK)  # mov [esp+candidate_rank], edx

    a.emit(0x8B, 0x88, u32(OBJECT_BODY_MODULE))  # mov ecx, [eax+0x25c]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "next")
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, BODY_GET_HEALTH_RATIO_SLOT)  # call [eax+0x14]  ; st0 = health ratio
    a.emit(0x8B, 0x54, 0x24, _CANDIDATE_RANK)  # mov edx, [esp+candidate_rank]
    a.emit(0x3B, 0x54, 0x24, _BEST_RANK)  # cmp edx, [esp+best_rank]
    a.jcc(JA, "better")
    # Same rank: only a lower health ratio wins.
    a.emit(0xD9, 0x04, 0x24)  # fld dword [esp+best_ratio]  ; st0 best, st1 candidate
    a.emit(0xDF, 0xF1)  # fcomip st0, st1          ; pops the best
    a.jcc(JBE, "reject")  # best <= candidate

    a.label("better")
    a.emit(0xD9, 0x5C, 0x24, _CANDIDATE_RATIO)  # fstp dword [esp+candidate_ratio]
    a.emit(0x6A, 0x00)  # push 0                       ; CommandSource
    a.emit(0x6A, 0x00)  # push 0                       ; no position
    a.emit(0xFF, 0x74, 0x24, _CANDIDATE + 8)  # push dword [esp+candidate]
    a.emit(0xFF, 0x74, 0x24, _CASTER + 12)  # push dword [esp+caster]
    a.emit(0x8B, 0x4E, 0x0C)  # mov ecx, [esi+0xc]          ; the bound button
    a.call_absolute(COMMAND_BUTTON_IS_VALID_TO_USE_ON)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "next")
    a.emit(0x8B, 0x44, 0x24, _CANDIDATE_RATIO)  # mov eax, [esp+candidate_ratio]
    a.emit(0x89, 0x04, 0x24)  # mov [esp+best_ratio], eax
    a.emit(0x8B, 0x44, 0x24, _CANDIDATE_RANK)  # mov eax, [esp+candidate_rank]
    a.emit(0x89, 0x44, 0x24, _BEST_RANK)  # mov [esp+best_rank], eax
    a.emit(0x8B, 0x5C, 0x24, _CANDIDATE)  # mov ebx, [esp+candidate]
    a.jmp("next")

    a.label("reject")
    a.emit(0xDD, 0xD8)  # fstp st0
    a.jmp("next")

    a.label("done")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "out")
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(SPELLBOOK_SET_TARGET_OBJECT)
    a.emit(0xB0, 0x01)  # mov al, 1
    a.label("out")
    a.emit(0x83, 0xC4, _LOCALS)  # add esp, 0x14
    a.emit(0x5F, 0x5E, 0x5B, 0x5D)  # pop edi, esi, ebx, ebp
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a.finish()


def _structure_picker(base_va: int) -> bytes:
    """Vtable slot 7 of `AI_SPECIAL_POWER_ALLY_STRUCTURE`, same contract as the unit picker.

    Walks the record's structure list, then its economy list, and takes the first object other
    than the caster that `isValidToUseOn` accepts. Registers across the loop: `esi` the behaviour,
    `edi` the id iterator, `ebx` the record; the list being walked is in the locals.
    """
    a = Asm(base_va)
    a.emit(0x55, 0x53, 0x56, 0x57)  # push ebp, ebx, esi, edi
    a.emit(0x83, 0xEC, _S_LOCALS)  # sub esp, 0xc
    a.emit(0x8B, 0xF1)  # mov esi, ecx
    a.emit(0x6A, 0x00)  # push 0                       ; NULL: clear any earlier target
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(SPELLBOOK_SET_TARGET_OBJECT)

    a.emit(0x8B, 0x4C, 0x24, _S_CASTER)  # mov ecx, [esp+caster]
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "none")
    a.emit(0x8B, 0x0D, u32(THE_SKIRMISH_AI_MANAGER))  # mov ecx, [TheSkirmishAIManager]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "none")
    a.emit(0x50)  # push eax                     ; the player
    a.call_absolute(SKIRMISH_AI_PLAYER_RECORD)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "none")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                 ; the record
    a.emit(0xC7, 0x44, 0x24, _S_LIST, u32(STRUCTURE_LISTS[0]))  # mov [esp+list], 8

    a.label("list")
    a.emit(0x8B, 0x44, 0x24, _S_LIST)  # mov eax, [esp+list]
    a.emit(0x8B, 0x04, 0x03)  # mov eax, [ebx+eax]          ; the list object
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next_list")
    a.emit(0x8B, 0x78, SKIRMISH_AI_ID_LIST_BEGIN)  # mov edi, [eax+4]
    a.emit(0x8B, 0x40, SKIRMISH_AI_ID_LIST_BEGIN + 4)  # mov eax, [eax+8]
    a.emit(0x89, 0x04, 0x24)  # mov [esp+end], eax

    a.label("next")
    a.emit(0x3B, 0x3C, 0x24)  # cmp edi, [esp+end]
    a.jcc(JAE, "next_list")
    a.emit(0xFF, 0x37)  # push dword [edi]           ; the id
    a.emit(0x83, 0xC7, 0x04)  # add edi, 4
    a.emit(0x8B, 0x0D, u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(GAME_LOGIC_FIND_OBJECT_BY_ID)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")
    a.emit(0x3B, 0x44, 0x24, _S_CASTER)  # cmp eax, [esp+caster]
    a.jcc(JE, "next")
    a.emit(0x89, 0x44, 0x24, _S_CANDIDATE)  # mov [esp+candidate], eax
    a.emit(0x6A, 0x00)  # push 0                       ; CommandSource
    a.emit(0x6A, 0x00)  # push 0                       ; no position
    a.emit(0x50)  # push eax                     ; the candidate
    a.emit(0xFF, 0x74, 0x24, _S_CASTER + 12)  # push dword [esp+caster]
    a.emit(0x8B, 0x4E, 0x0C)  # mov ecx, [esi+0xc]          ; the bound button
    a.call_absolute(COMMAND_BUTTON_IS_VALID_TO_USE_ON)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "next")
    a.emit(0xFF, 0x74, 0x24, _S_CANDIDATE)  # push dword [esp+candidate]
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(SPELLBOOK_SET_TARGET_OBJECT)
    a.emit(0xB0, 0x01)  # mov al, 1
    a.jmp("out")

    a.label("next_list")
    a.emit(0x8B, 0x44, 0x24, _S_LIST)  # mov eax, [esp+list]
    a.emit(0x83, 0xC0, 0x04)  # add eax, 4
    a.emit(0x89, 0x44, 0x24, _S_LIST)  # mov [esp+list], eax
    a.emit(0x83, 0xF8, STRUCTURE_LISTS[-1])  # cmp eax, 0xc
    a.jcc(JBE, "list")

    a.label("none")
    a.emit(0x32, 0xC0)  # xor al, al
    a.label("out")
    a.emit(0x83, 0xC4, _S_LOCALS)  # add esp, 0xc
    a.emit(0x5F, 0x5E, 0x5B, 0x5D)  # pop edi, esi, ebx, ebp
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a.finish()


def _align(n: int) -> int:
    return (n + 15) & ~15


def layout(base_va: int, table_count: int = SPELLBOOK_AI_TYPE_COUNT) -> Layout:
    """The cave: the name table (stock pointers, the new ones, NULL), the two vtables, the name
    strings, the factory case and the two pickers, each 16-aligned."""
    table = base_va
    object_vtable = _align(table + 4 * (table_count + len(NAMES) + 1))
    structure_vtable = object_vtable + 4 * AI_KILLER_BEHAVIOR_VTABLE_SLOTS
    names = []
    at = structure_vtable + 4 * AI_KILLER_BEHAVIOR_VTABLE_SLOTS
    for name in NAMES:
        names.append(at)
        at += len(name) + 1
    factory_case = _align(at)
    object_picker = _align(
        factory_case + len(_factory_case(factory_case, object_vtable, structure_vtable))
    )
    structure_picker = _align(object_picker + len(_object_picker(object_picker)))
    return Layout(
        table,
        object_vtable,
        structure_vtable,
        tuple(names),
        factory_case,
        object_picker,
        structure_picker,
    )


def build_section(
    base_va: int, stock_names: tuple[int, ...], killer_slots: tuple[int, ...]
) -> bytes:
    at = layout(base_va, len(stock_names))
    blob = bytearray()

    def put(va: int, chunk: bytes) -> None:
        blob.extend(b"\x00" * (va - base_va - len(blob)))
        blob.extend(chunk)

    put(at.table, b"".join(u32(p) for p in (*stock_names, *at.names, 0)))
    put(at.object_vtable, _vtable(killer_slots, at.object_picker))
    put(at.structure_vtable, _vtable(killer_slots, at.structure_picker))
    for va, name in zip(at.names, NAMES, strict=True):
        put(va, name.encode("ascii") + b"\x00")
    put(at.factory_case, _factory_case(at.factory_case, at.object_vtable, at.structure_vtable))
    put(at.object_picker, _object_picker(at.object_picker))
    put(at.structure_picker, _structure_picker(at.structure_picker))
    return bytes(blob)


def _name_table(data: bytes | bytearray, target: _Target) -> tuple[int, ...]:
    """The stock name pointers, after checking the table is the one this build should hold."""
    pointers = name_tables.read_terminated(data, target.table_va, "SpecialPowerAIType table")
    names = [name_tables.read_cstring(data, p) for p in pointers]
    if len(pointers) != target.count or names[0] != _FIRST_NAME or names[-1] != target.last_name:
        raise ValueError(
            f"the SpecialPowerAIType table at 0x{target.table_va:08x} holds {len(pointers)} "
            f"names from {names[:1]} to {names[-1:]}, expected {target.count} from {_FIRST_NAME} "
            f"to {target.last_name} - not the expected {target.binary}"
        )
    return pointers


def _check(data: bytes | bytearray, anchors: dict[int, bytes], binary: str) -> None:
    for va, expected in anchors.items():
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"0x{va:08x} holds {got.hex()}, expected {expected.hex()} - not the expected "
                f"{binary}, or a patch already rewrote it"
            )


def _killer_slots(data: bytes | bytearray) -> tuple[int, ...]:
    off = file_offset(data, AI_KILLER_BEHAVIOR_VTABLE)
    slots = struct.unpack_from(f"<{AI_KILLER_BEHAVIOR_VTABLE_SLOTS}I", data, off)
    # The constructor stamps this vtable, and its picker slot is the enemy picker the new ones
    # replace; a build where either moved is not this one.
    if slots[AI_REBUILD_PICKER_VTABLE_SLOT // 4] != AI_KILLER_PICKER:
        raise ValueError(
            f"the enemy-killer vtable's picker slot is not 0x{AI_KILLER_PICKER:08x} - not the "
            "expected game.dat"
        )
    return slots


def _repoint(data: bytearray, target: _Target, table_va: int, section: str) -> None:
    read_off = file_offset(data, target.read_va)
    new_read = bytearray(target.read_bytes)
    new_read[target.read_disp_at : target.read_disp_at + 4] = u32(table_va)
    apply_byte_patch(
        data, read_off, target.read_bytes, bytes(new_read), f"SpecialPowerAIType table -> {section}"
    )
    bound_off = file_offset(data, target.bound_va)
    new_bound = bytearray(target.bound_bytes)
    new_bound[target.bound_imm_at] = target.count + len(NAMES)
    apply_byte_patch(
        data,
        bound_off,
        target.bound_bytes,
        bytes(new_bound),
        f"SpecialPowerAIType parse bound {target.count} -> {target.count + len(NAMES)}",
    )


def _verify_table(data: bytes | bytearray, target: _Target, section: str) -> list[str]:
    located = find_section(data, section)
    if located is None:
        return [f"no {section} section: the file does not carry this patch"]
    section_va = located[0]
    problems: list[str] = []
    read = file_offset(data, target.read_va) + target.read_disp_at
    if struct.unpack_from("<I", data, read)[0] != section_va:
        problems.append(f"the parser at 0x{target.read_va:08x} does not read the {section} table")
    bound = data[file_offset(data, target.bound_va) + target.bound_imm_at]
    if bound != target.count + len(NAMES):
        problems.append(f"the parser's loop bound is {bound}, expected {target.count + len(NAMES)}")
    try:
        pointers = name_tables.read_terminated(data, section_va, "SpecialPowerAIType table")
    except (ValueError, struct.error) as exc:
        return [*problems, f"cannot read back the {section} table: {exc}"]
    added = tuple(name_tables.read_cstring(data, p) for p in pointers[target.count :])
    if len(pointers) != target.count + len(NAMES) or added != NAMES:
        problems.append(
            f"the {section} table does not end in {', '.join(NAMES)} from index {target.count}"
        )
    return problems


class AiAllyTargetsPatch(Patch):
    name = "ai-ally-targets"
    author = "officialNecro"
    runtime_verified = "partly"
    description = (
        f"Add two SpecialPowerAITypes that cast a NEED_TARGET_ALLY_OBJECT power at the AI "
        f"player's own objects anywhere on the map, filtered by the power's ObjectFilter and "
        f"MaxCastRange. {ALLY_OBJECT_NAME}: a unit that is fighting, a HERO first, then the "
        f"lowest health. {ALLY_STRUCTURE_NAME}: the first own building the power accepts, "
        "structures then economy buildings, without waiting for a fight. SpecialPowerRange and "
        "SpecialPowerRadius are not read"
    )

    def apply(self, data: bytearray) -> None:
        name_tables.check_not_rebased(data)
        stock = _name_table(data, GAME)
        _check(data, ANCHORS, GAME.binary)
        slots = _killer_slots(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base: build_section(base, stock, slots),
            name_tables.SECTION_CHARACTERISTICS,
        )
        at = layout(section_va, len(stock))
        _repoint(data, GAME, at.table, SECTION_NAME)
        jump_off = file_offset(data, SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK)
        rel = at.factory_case - (SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK + 6)
        apply_byte_patch(
            data,
            jump_off,
            SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK_BYTES,
            b"\x0f\x87" + struct.pack("<i", rel),
            f"SpecialPowerAIType factory out-of-range branch -> {SECTION_NAME}",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems = _verify_table(data, GAME, SECTION_NAME)
        located = find_section(data, SECTION_NAME)
        if located is None:
            return problems
        section_va, section_off, _ = located
        try:
            stock = _name_table(data, GAME)
            slots = _killer_slots(data)
        except ValueError as exc:
            return [*problems, str(exc)]
        code = build_section(section_va, stock, slots)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected code")
        off = file_offset(data, SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK)
        target = (
            SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK + 6 + struct.unpack_from("<i", data, off + 2)[0]
        )
        if bytes(data[off : off + 2]) != b"\x0f\x87" or target != layout(section_va).factory_case:
            problems.append("the factory's out-of-range branch does not reach the new case")
        return problems

    def ini_surface(self) -> Engine:
        return Engine(
            enum_members=(
                EnumDelta("SpecialPowerAIType", ALLY_OBJECT_NAME, ALLY_OBJECT_INDEX, self.name),
                EnumDelta(
                    "SpecialPowerAIType", ALLY_STRUCTURE_NAME, ALLY_STRUCTURE_INDEX, self.name
                ),
            )
        )


class AiAllyTargetsWorldbuilderPatch(Patch):
    """Teach Worldbuilder's parser the same names.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** The editor loads every object and
    asserts on a `SpecialPowerAIType` its own table does not hold.
    """

    name = "ai-ally-targets-wb"
    author = "officialNecro"
    description = (
        f"Worldbuilder.exe (not game.dat): add {ALLY_OBJECT_NAME} and {ALLY_STRUCTURE_NAME} to "
        "the editor's SpecialPowerAIType names, so it loads objects whose AISpecialPowerUpdate "
        "uses them instead of stopping on an assert"
    )

    def apply(self, data: bytearray) -> None:
        name_tables.check_not_rebased(data)
        stock = _name_table(data, WORLDBUILDER)
        section_va = allocate_section(
            data,
            WORLDBUILDER_SECTION_NAME,
            lambda base: name_tables.layout(stock, NAMES, base)[0],
            name_tables.SECTION_CHARACTERISTICS,
        )
        _repoint(data, WORLDBUILDER, section_va, WORLDBUILDER_SECTION_NAME)

    def verify(self, data: bytes | bytearray) -> list[str]:
        return _verify_table(data, WORLDBUILDER, WORLDBUILDER_SECTION_NAME)
