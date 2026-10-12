"""Put the skirmish AI's farm raids in the INI: whether a faction raids, how big and how often its
squads are, and which of its units may join one.

`AIFarmKillSquad` is a targetless tactic: every ten to sixty seconds it pulls one to three idle
units - anything that is not a `HERO`, an `ARCHER`, a `MACHINE` or a `DOZER` - off the army and
walks them at an enemy economy building. Nothing in the INI reaches it. This patch adds three
fields to `ArmyDefinition` and four to `ArmyMemberDefinition`:

* `FarmKillSquad = <Bool>` - `Yes` and that faction raids, `No` and it never does;
* `FarmKillSquadSize = <min> <max>` - the squad's size, in place of one-or-two to three;
* `FarmKillSquadInterval = <min> <max>` - seconds until the next squad, in place of 10 to 60;
* `FarmKillerTeam = <Bool>` on a member, or `FarmKillerTeamPhase1`..`3` for one phase each. Once
  any member of an army sets one, only members flagged for the current phase may join a squad,
  and `ARCHER` units are no longer barred.

**A faction raids only if it asks to**: `FarmKillSquad = Yes`, or `FarmKillSquad` left unwritten
and at least one member flagged. An `ArmyDefinition` that writes neither never forms a squad, so
installing the patch switches the tactic off for every army that has not opted in.

It wraps three of the tactic's vtable slots (run gate, reset, squad build) and the team
recruiter's per-object test. The squad build marks its team prototype by forbidding `SKYBOX` - a
`KindOf` no unit carries - and that mark is how the recruiter's wrapper knows a farm squad from
any other team.

The per-faction values are recorded against the block's `Side` and looked up with the `Side` of
the `ArmyDefinition` the AI player runs on, the way `ai-hero-build-delay` keys its delays. `Side`
has to be parsed before them for that - it is the block's first line in stock RotWK and in Edain.

Derivation: `../docs/ai-farm-kill-gate.md`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    AI_DATA_ARMY_DEFINITION,
    AI_DATA_SET_VALUE,
    AI_DATA_SET_VALUE_ENTRY,
    AI_FARM_KILL_SQUAD_BUILD,
    AI_FARM_KILL_SQUAD_BUILD_ENTRY,
    AI_FARM_KILL_SQUAD_BUILD_SLOT,
    AI_FARM_KILL_SQUAD_NAME_PUSH,
    AI_FARM_KILL_SQUAD_NAME_PUSH_BYTES,
    AI_FARM_KILL_SQUAD_NEXT_RUN_KEY,
    AI_FARM_KILL_SQUAD_RESET,
    AI_FARM_KILL_SQUAD_RESET_ENTRY,
    AI_FARM_KILL_SQUAD_RESET_SLOT,
    AI_FARM_KILL_SQUAD_RUN_GATE,
    AI_FARM_KILL_SQUAD_RUN_GATE_ENTRY,
    AI_FARM_KILL_SQUAD_RUN_GATE_SLOT,
    AI_FARM_KILL_SQUAD_SOURCE_FILE,
    AI_FARM_KILL_SQUAD_VTABLE,
    AI_TACTIC_PLAYER,
    AI_TEAM_BUILDER_PLAYER,
    AI_TEAM_PROTOTYPE_FORBIDDEN_KIND_OF,
    AI_TEAM_PROTOTYPE_MAX_SIZE,
    AI_TEAM_PROTOTYPE_MIN_SIZE,
    AI_TEAM_RECRUIT_ACCEPT,
    AI_TEAM_RECRUIT_ACCEPT_CALLS,
    AI_TEAM_RECRUIT_ACCEPT_ENTRY,
    AI_TEAM_RECRUIT_FORBIDDEN_KIND_OF,
    ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES,
    ARMY_DEFINITION_FIELD_TABLE_REFS,
    ARMY_DEFINITION_MEMBERS,
    ARMY_DEFINITION_PHASE_DURATION_MID_GAME,
    ARMY_DEFINITION_PHASE_DURATION_RUSH,
    ARMY_DEFINITION_SIDE,
    ARMY_MEMBER_DEFINITION_ALLOC,
    ARMY_MEMBER_DEFINITION_ALLOC_BYTES,
    ARMY_MEMBER_DEFINITION_FIELD_TABLE_REF_OPCODES,
    ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS,
    ARMY_MEMBER_DEFINITION_SIZE,
    GAME_LOGIC_FRAME,
    GAME_LOGIC_RANDOM_VALUE,
    INI_PARSE_BOOL,
    INI_PARSE_INT,
    LOGIC_FRAMES_PER_SECOND,
    NAME_KEY_FROM_STRING,
    OBJECT_THING_TEMPLATE,
    OPERATOR_NEW,
    SKIRMISH_AI_MANAGER_PLAYER_DATA,
    THE_GAME_LOGIC,
    THE_NAME_KEY_GENERATOR,
    THE_SKIRMISH_AI_MANAGER,
    THE_THING_FACTORY,
    THING_FACTORY_FIND_TEMPLATE,
    THING_FACTORY_FIND_TEMPLATE_ENTRY,
    THING_TEMPLATE_IS_EQUIVALENT,
    THING_TEMPLATE_IS_EQUIVALENT_ENTRY,
)
from ..asm import JB, JE, JGE, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    find_section,
    u32,
    va_to_offset,
)
from .utils.field_tables import ROW_SIZE, Entry, entries_before, read_field_table, resolve_table
from .utils.name_tables import read_cstring

__all__ = [
    "ANCHORS",
    "ARMY_KEYWORDS",
    "FLAGS_OFFSET",
    "MARKER_BIT",
    "MARKER_BYTE",
    "MEMBER_KEYWORDS",
    "PATCHED_MEMBER_SIZE",
    "SECTION_NAME",
    "SLOTS",
    "SLOT_SIZE",
    "TABLE_BYTES",
    "AiFarmKillGatePatch",
    "Layout",
    "build_code",
    "build_section",
    "layout",
    "live_rows",
]

SECTION_NAME = ".farmkil"  # 8 chars exactly: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable, because
# the per-faction table at the section's base is filled while the INI is read.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The `ArmyDefinition` keywords, in the order their rows are appended.
ARMY_KEYWORDS = ("FarmKillSquad", "FarmKillSquadSize", "FarmKillSquadInterval")
#: The `ArmyMemberDefinition` keywords: every phase at once, then one per phase.
MEMBER_KEYWORDS = (
    "FarmKillerTeam",
    "FarmKillerTeamPhase1",
    "FarmKillerTeamPhase2",
    "FarmKillerTeamPhase3",
)

#: How many factions may carry settings. Stock RotWK declares six `ArmyDefinition` blocks and
#: Edain eleven.
SLOTS = 64
#: One faction: the `NameKey` of its `Side`, what its `FarmKillSquad` line said, then the size
#: pair and the interval pair as written. A pair whose second number is not positive is unset.
SLOT_SIZE = 24
_SLOT_SIDE = 0x00
_SLOT_ANSWER = 0x04
#: `FarmKillSquad` as recorded: zero while the block has not written it.
_ANSWER_NO = 1
_ANSWER_YES = 2
_SLOT_SIZE_PAIR = 0x08
_SLOT_INTERVAL_PAIR = 0x10
TABLE_BYTES = SLOTS * SLOT_SIZE

#: The three per-phase flags sit in the four bytes this patch adds to `ArmyMemberDefinition`.
FLAGS_OFFSET = ARMY_MEMBER_DEFINITION_SIZE
PATCHED_MEMBER_SIZE = ARMY_MEMBER_DEFINITION_SIZE + 4
_ANY_PHASE = 0x00FFFFFF

#: `KindOf SKYBOX` (202) in a `KindOf` mask: the bit the squad build sets in its prototype's
#: forbidden mask to mark it. Forbidding it changes who is recruited by nothing.
MARKER_BYTE = 0x19
MARKER_BIT = 0x04
#: `KindOf ARCHER` (133), which the stock squad build forbids.
_ARCHER_BYTE = 0x10
_ARCHER_BIT = 0x20

#: The line number passed with `AI_FARM_KILL_SQUAD_SOURCE_FILE` to the random-number calls this
#: patch adds. The engine only logs it.
_RANDOM_LINE = 0x267

#: What ties the vtable to the farm raid and the cave's callees to the routines it expects. The
#: bytes each edit replaces are asserted by `apply_byte_patch`.
ANCHORS = {
    AI_FARM_KILL_SQUAD_RUN_GATE: AI_FARM_KILL_SQUAD_RUN_GATE_ENTRY,
    AI_FARM_KILL_SQUAD_RESET: AI_FARM_KILL_SQUAD_RESET_ENTRY,
    AI_FARM_KILL_SQUAD_BUILD: AI_FARM_KILL_SQUAD_BUILD_ENTRY,
    AI_FARM_KILL_SQUAD_NAME_PUSH: AI_FARM_KILL_SQUAD_NAME_PUSH_BYTES,
    AI_TEAM_RECRUIT_ACCEPT: AI_TEAM_RECRUIT_ACCEPT_ENTRY,
    AI_DATA_SET_VALUE: AI_DATA_SET_VALUE_ENTRY,
    THING_FACTORY_FIND_TEMPLATE: THING_FACTORY_FIND_TEMPLATE_ENTRY,
    THING_TEMPLATE_IS_EQUIVALENT: THING_TEMPLATE_IS_EQUIVALENT_ENTRY,
}

_KEYWORD_SHAPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_ROUTINES = (
    "parse_bool",
    "parse_pair",
    "parse_member",
    "alloc",
    "gate",
    "reset",
    "build",
    "accept",
)


@dataclass(frozen=True, slots=True)
class Layout:
    """Where each piece of the cave sits, for a section at a given base."""

    parse_bool: int
    parse_pair: int
    parse_member: int
    alloc: int
    gate: int
    reset: int
    build: int
    accept: int
    keywords: dict[str, int]
    army_table: int


def live_rows(data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
    """The rows of a field table the INI reader can match, in table order.

    Neither stock table has a terminator of its own: the last row is followed directly by other
    data, and `read_field_table` walks through that until it meets zeroes. Those trailing rows
    name nothing a keyword could equal, so the walk stops at the first one whose name is not a
    keyword. A table some other patch has rebuilt is terminated properly and comes back whole.
    """
    rows: list[Entry] = []
    for entry in read_field_table(data, table_va):
        name = read_cstring(data, entry[0])
        if name is None or _KEYWORD_SHAPE.fullmatch(name) is None:
            break
        rows.append(entry)
    return tuple(rows)


def _emit_side_key(a: Asm, miss: str) -> None:
    """`eax` = an `ArmyDefinition` in, the `NameKey` of its `Side` out; jumps to `miss` for a
    block with no `Side`. Interned the same way at parse time and at run time."""
    a.emit(0x8D, 0x40, ARMY_DEFINITION_SIDE)  # lea eax, [eax+Side]
    a.emit(0x83, 0x38, 0x00)  # cmp dword [eax], 0     ; an empty AsciiString has no data
    a.jcc(JE, miss)
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0x0D, u32(THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
    a.call_absolute(NAME_KEY_FROM_STRING)  # eax = NameKey, ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, miss)  # key 0 is the empty slot's own key


def _emit_slot_lookups(a: Asm, table: int, table_end: int) -> None:
    """Two leaf routines, both `eax` = `ArmyDefinition` in and `eax` = its slot or null out.
    `slot_of_army` only finds; `claim_slot` takes the first free slot for a faction not yet
    listed. A full table leaves the faction stock rather than displacing another."""
    a.label("slot_of_army")
    _emit_side_key(a, "slot_none")
    a.emit(0xB9, u32(table))  # mov ecx, table
    a.label("slot_scan")
    a.emit(0x39, 0x01)  # cmp [ecx], eax
    a.jcc(JE, "slot_found")
    a.emit(0x83, 0xC1, SLOT_SIZE)  # add ecx, 24
    a.emit(0x81, 0xF9, u32(table_end))  # cmp ecx, table_end
    a.jcc(JB, "slot_scan")
    a.label("slot_none")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0xC3)  # ret
    a.label("slot_found")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.emit(0xC3)  # ret

    a.label("claim_slot")
    _emit_side_key(a, "claim_none")
    a.emit(0x33, 0xD2)  # xor edx, edx           ; the first free slot seen
    a.emit(0xB9, u32(table))  # mov ecx, table
    a.label("claim_scan")
    a.emit(0x39, 0x01)  # cmp [ecx], eax
    a.jcc(JE, "claim_found")
    a.emit(0x83, 0x39, 0x00)  # cmp dword [ecx], 0
    a.jcc(JNE, "claim_next")
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JNE, "claim_next")
    a.emit(0x8B, 0xD1)  # mov edx, ecx
    a.label("claim_next")
    a.emit(0x83, 0xC1, SLOT_SIZE)  # add ecx, 24
    a.emit(0x81, 0xF9, u32(table_end))  # cmp ecx, table_end
    a.jcc(JB, "claim_scan")
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "claim_none")
    a.emit(0x89, 0x02)  # mov [edx], eax
    a.emit(0x8B, 0xC2)  # mov eax, edx
    a.emit(0xC3)  # ret
    a.label("claim_found")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.emit(0xC3)  # ret
    a.label("claim_none")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0xC3)  # ret


def _emit_any_flagged(a: Asm) -> None:
    """Leaf: `eax` = `ArmyDefinition` in, `al` = whether any member sets a `FarmKillerTeam`
    flag for any phase."""
    a.label("any_flagged")
    a.emit(0x8B, 0x48, ARMY_DEFINITION_MEMBERS)  # mov ecx, [eax+4]       ; begin
    a.emit(0x8B, 0x50, ARMY_DEFINITION_MEMBERS + 4)  # mov edx, [eax+8]       ; end
    a.label("flag_scan")
    a.emit(0x3B, 0xCA)  # cmp ecx, edx
    a.jcc(JE, "flag_none")
    a.emit(0x8B, 0x01)  # mov eax, [ecx]         ; the member
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "flag_next")
    a.emit(0xF7, 0x40, FLAGS_OFFSET, u32(_ANY_PHASE))  # test dword [eax+0x10], 0xffffff
    a.jcc(JNE, "flag_some")
    a.label("flag_next")
    a.emit(0x83, 0xC1, 0x04)  # add ecx, 4
    a.jmp("flag_scan")
    a.label("flag_none")
    a.emit(0x32, 0xC0)  # xor al, al
    a.emit(0xC3)  # ret
    a.label("flag_some")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.emit(0xC3)  # ret


def _emit_parsers(a: Asm) -> None:
    """The three field-table rows that need code. All `__cdecl parse(ini, instance, store,
    userData)`, caller-cleaned like every row."""
    # `FarmKillSquad`: the stock `Bool` parser into a local, then the faction's slot.
    a.label("parse_bool")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x51)  # push ecx               ; the local
    a.emit(0x8D, 0x45, 0xFC)  # lea eax, [ebp-4]
    a.emit(0x6A, 0x00)  # push 0                 ; userData
    a.emit(0x50)  # push eax               ; store
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0x0c]        ; instance
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+0x08]        ; ini
    a.call_absolute(INI_PARSE_BOOL)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x8B, 0x45, 0x0C)  # mov eax, [ebp+0xc]     ; instance
    a.call("claim_slot")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "bool_done")  # no Side yet, or no room: the line is dropped
    a.emit(0x33, 0xC9)  # xor ecx, ecx
    a.emit(0x80, 0x7D, 0xFC, 0x00)  # cmp byte [ebp-4], 0
    a.emit(0x0F, 0x95, 0xC1)  # setne cl
    a.emit(0x41)  # inc ecx                ; No is 1, Yes is 2
    a.emit(0x89, 0x48, _SLOT_ANSWER)  # mov [eax+4], ecx
    a.label("bool_done")
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `FarmKillSquadSize` and `FarmKillSquadInterval`: two integers, stored at the slot offset
    # the row carries as `userData`. Both tokens are read before the slot is looked for, so a
    # dropped line still consumes them.
    a.label("parse_pair")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x83, 0xEC, 0x08)  # sub esp, 8
    for local in (0xF8, 0xFC):
        a.emit(0x8D, 0x45, local)  # lea eax, [ebp-8] / [ebp-4]
        a.emit(0x6A, 0x00)  # push 0
        a.emit(0x50)  # push eax
        a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0x0c]
        a.emit(0xFF, 0x75, 0x08)  # push [ebp+0x08]
        a.call_absolute(INI_PARSE_INT)
        a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x8B, 0x45, 0x0C)  # mov eax, [ebp+0xc]     ; instance
    a.call("claim_slot")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pair_done")
    a.emit(0x03, 0x45, 0x14)  # add eax, [ebp+0x14]    ; userData: the pair's offset
    a.emit(0x8B, 0x4D, 0xF8)  # mov ecx, [ebp-8]
    a.emit(0x89, 0x08)  # mov [eax], ecx
    a.emit(0x8B, 0x4D, 0xFC)  # mov ecx, [ebp-4]
    a.emit(0x89, 0x48, 0x04)  # mov [eax+4], ecx
    a.label("pair_done")
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `FarmKillerTeam`: the stock `Bool` parser with this call's own arguments, then the same
    # answer for the other two phases. `store` is the member's first flag byte.
    a.label("parse_member")
    for _ in range(4):
        a.emit(0xFF, 0x74, 0x24, 0x10)  # push [esp+0x10]        ; userData, store, instance, ini
    a.call_absolute(INI_PARSE_BOOL)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x8B, 0x44, 0x24, 0x0C)  # mov eax, [esp+0xc]     ; store
    a.emit(0x8A, 0x08)  # mov cl, [eax]
    a.emit(0x88, 0x48, 0x01)  # mov [eax+1], cl
    a.emit(0x88, 0x48, 0x02)  # mov [eax+2], cl
    a.emit(0xC3)  # ret

    # `operator new` for an `ArmyMemberDefinition`, with the bytes the stock constructor does
    # not know about cleared. Leaves the size on the stack, as the call it replaces does.
    a.label("alloc")
    a.emit(0xFF, 0x74, 0x24, 0x04)  # push [esp+4]           ; the size
    a.call_absolute(OPERATOR_NEW)
    a.emit(0x59)  # pop ecx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "alloc_done")
    a.emit(0x83, 0x60, FLAGS_OFFSET, 0x00)  # and dword [eax+0x10], 0
    a.label("alloc_done")
    a.emit(0xC3)  # ret


def _emit_army_of_tactic(a: Asm, tactic_push: tuple[int, ...], miss: str) -> None:
    """`eax` = the AI record of the tactic's player, or a jump to `miss`. `tactic_push` is the
    `push dword [reg+0x24]` for whichever register holds the tactic."""
    a.emit(*tactic_push)  # push dword [tactic+0x24]   ; its player
    a.emit(0x8B, 0x0D, u32(THE_SKIRMISH_AI_MANAGER))  # mov ecx, [TheSkirmishAIManager]
    a.call_absolute(SKIRMISH_AI_MANAGER_PLAYER_DATA)  # eax = the AI record, or null; ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, miss)


def _emit_gate(a: Asm) -> None:
    """Vtable slot 1, `__thiscall bool canRun(arg)`. The stock routine is reached, with `ecx`
    and the stack as the caller left them, only for a faction that asked to raid: one whose
    `FarmKillSquad` says `Yes`, or one that did not write it and flags a member. Every other
    faction is answered `false` with the stock `ret 4`.

    A player the AI manager has no record for, or a record with no `ArmyDefinition`, has no INI to
    have asked through and is left to the stock routine."""
    a.label("gate")
    a.emit(0x51)  # push ecx                 ; the tactic, across the lookup
    _emit_army_of_tactic(a, (0xFF, 0x71, AI_TACTIC_PLAYER), "gate_stock")
    a.emit(0x8B, 0x80, u32(AI_DATA_ARMY_DEFINITION))  # mov eax, [eax+0x160]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "gate_stock")
    a.emit(0x50)  # push eax                 ; the army, across the slot lookup
    a.call("slot_of_army")
    a.emit(0x5A)  # pop edx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "gate_unwritten")  # no slot: none of the three fields was written
    a.emit(0x8B, 0x40, _SLOT_ANSWER)  # mov eax, [eax+4]
    a.emit(0x83, 0xF8, _ANSWER_YES)  # cmp eax, 2
    a.jcc(JE, "gate_stock")
    a.emit(0x83, 0xF8, _ANSWER_NO)  # cmp eax, 1
    a.jcc(JE, "gate_declined")
    a.label("gate_unwritten")
    a.emit(0x8B, 0xC2)  # mov eax, edx
    a.call("any_flagged")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "gate_declined")
    a.label("gate_stock")
    a.emit(0x59)  # pop ecx
    a.jmp_absolute(AI_FARM_KILL_SQUAD_RUN_GATE)
    a.label("gate_declined")
    a.emit(0x59)  # pop ecx
    a.emit(0x32, 0xC0)  # xor al, al
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_random(a: Asm) -> None:
    """`eax = GameLogicRandomValue(edx, ecx)`, with the tactic's own source path."""
    a.emit(0x68, u32(_RANDOM_LINE))  # push line
    a.emit(0x68, u32(AI_FARM_KILL_SQUAD_SOURCE_FILE))  # push file
    a.emit(0x51)  # push ecx                 ; hi
    a.emit(0x52)  # push edx                 ; lo
    a.call_absolute(GAME_LOGIC_RANDOM_VALUE)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10


def _emit_reset(a: Asm) -> None:
    """Vtable slot 2, `__thiscall void reset()`. Runs the stock routine, then - for a faction
    with an interval - stores the next-run frame again from the faction's own range."""
    a.label("reset")
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(0x8B, 0xF1)  # mov esi, ecx             ; the tactic
    a.call_absolute(AI_FARM_KILL_SQUAD_RESET)
    _emit_army_of_tactic(a, (0xFF, 0x76, AI_TACTIC_PLAYER), "reset_done")
    a.emit(0x8B, 0xF8)  # mov edi, eax             ; the AI record
    a.emit(0x8B, 0x80, u32(AI_DATA_ARMY_DEFINITION))  # mov eax, [eax+0x160]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "reset_done")
    a.call("slot_of_army")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "reset_done")
    a.emit(0x8B, 0x48, _SLOT_INTERVAL_PAIR + 4)  # mov ecx, [eax+0x14]      ; max seconds
    a.emit(0x83, 0xF9, 0x00)  # cmp ecx, 0
    a.jcc(JLE, "reset_done")  # unset
    a.emit(0x8B, 0x50, _SLOT_INTERVAL_PAIR)  # mov edx, [eax+0x10]      ; min seconds
    a.emit(0x83, 0xFA, 0x00)  # cmp edx, 0
    a.jcc(JGE, "reset_min_ok")
    a.emit(0x33, 0xD2)  # xor edx, edx
    a.label("reset_min_ok")
    a.emit(0x3B, 0xCA)  # cmp ecx, edx
    a.jcc(JGE, "reset_max_ok")
    a.emit(0x8B, 0xCA)  # mov ecx, edx
    a.label("reset_max_ok")
    a.emit(0x0F, 0xAF, 0x0D, u32(LOGIC_FRAMES_PER_SECOND))  # imul ecx, [logic rate]
    a.emit(0x0F, 0xAF, 0x15, u32(LOGIC_FRAMES_PER_SECOND))  # imul edx, [logic rate]
    _emit_random(a)
    a.emit(0x8B, 0x0D, u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x03, 0x41, GAME_LOGIC_FRAME)  # add eax, [ecx+0x40]
    a.emit(0x50)  # push eax                 ; the frame
    a.emit(0x68, u32(AI_FARM_KILL_SQUAD_NEXT_RUN_KEY))  # push <next-run key>
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(AI_DATA_SET_VALUE)  # ret 8
    a.label("reset_done")
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0xC3)  # ret


def _emit_build(a: Asm) -> None:
    """Vtable slot 3, `__thiscall bool build(prototype, index)`, `ret 8`. Runs the stock
    routine, marks the prototype, lifts the `ARCHER` bar for an army that names its own raiders,
    and rewrites the two sizes for a faction that set them."""
    forbidden = AI_TEAM_PROTOTYPE_FORBIDDEN_KIND_OF
    a.label("build")
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(0x8B, 0x74, 0x24, 0x0C)  # mov esi, [esp+0xc]       ; the prototype
    a.emit(0x8B, 0xF9)  # mov edi, ecx             ; the tactic
    a.emit(0xFF, 0x74, 0x24, 0x10)  # push [esp+0x10]          ; index
    a.emit(0x56)  # push esi
    a.call_absolute(AI_FARM_KILL_SQUAD_BUILD)  # ecx is still the tactic; ret 8
    a.emit(0x80, 0x8E, u32(forbidden + MARKER_BYTE), MARKER_BIT)  # or byte [esi+0x315], 4
    _emit_army_of_tactic(a, (0xFF, 0x77, AI_TACTIC_PLAYER), "build_done")
    a.emit(0x8B, 0xB8, u32(AI_DATA_ARMY_DEFINITION))  # mov edi, [eax+0x160]     ; the army
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "build_done")
    a.emit(0x8B, 0xC7)  # mov eax, edi
    a.call("any_flagged")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "build_size")
    a.emit(0x80, 0xA6, u32(forbidden + _ARCHER_BYTE), 0xFF ^ _ARCHER_BIT)  # and byte [..], ~0x20
    a.label("build_size")
    a.emit(0x8B, 0xC7)  # mov eax, edi
    a.call("slot_of_army")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "build_done")
    a.emit(0x8B, 0x48, _SLOT_SIZE_PAIR + 4)  # mov ecx, [eax+0xc]       ; max
    a.emit(0x83, 0xF9, 0x00)  # cmp ecx, 0
    a.jcc(JLE, "build_done")  # unset
    a.emit(0x8B, 0x50, _SLOT_SIZE_PAIR)  # mov edx, [eax+8]         ; min
    a.emit(0x83, 0xFA, 0x01)  # cmp edx, 1
    a.jcc(JGE, "build_min_ok")
    a.emit(0xBA, u32(1))  # mov edx, 1
    a.label("build_min_ok")
    a.emit(0x3B, 0xCA)  # cmp ecx, edx
    a.jcc(JGE, "build_max_ok")
    a.emit(0x8B, 0xCA)  # mov ecx, edx
    a.label("build_max_ok")
    a.emit(0x89, 0x96, u32(AI_TEAM_PROTOTYPE_MIN_SIZE))  # mov [esi+0x2d4], edx
    _emit_random(a)
    a.emit(0x89, 0x86, u32(AI_TEAM_PROTOTYPE_MAX_SIZE))  # mov [esi+0x2d0], eax
    a.label("build_done")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0xC2, 0x08, 0x00)  # ret 8


def _emit_accept(a: Asm) -> None:
    """What the recruiter's two calls to its per-object test reach instead:
    `__thiscall bool(object, prototypePart, where)`, `ret 0xC`. A team that is not a farm squad
    goes straight to the stock test. A farm squad's candidate is first put to `eligible`, and
    one it refuses is answered `false` here."""
    a.label("accept")
    a.emit(0x8B, 0x44, 0x24, 0x08)  # mov eax, [esp+8]         ; the prototype part
    a.emit(0xF6, 0x80, u32(AI_TEAM_RECRUIT_FORBIDDEN_KIND_OF + MARKER_BYTE), MARKER_BIT)
    a.jcc(JE, "accept_stock")  # test byte [eax+0x1e9], 4 : not a farm squad
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]         ; the object
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "accept_stock")
    a.emit(0x51)  # push ecx                 ; the team builder
    a.emit(0x50)  # push eax                 ; object
    a.emit(0xFF, 0x71, AI_TEAM_BUILDER_PLAYER)  # push dword [ecx+0x14]    ; player
    a.call("eligible")  # ret 8
    a.emit(0x59)  # pop ecx
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "accept_stock")
    a.emit(0x32, 0xC0)  # xor al, al
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc
    a.label("accept_stock")
    a.jmp_absolute(AI_TEAM_RECRUIT_ACCEPT)

    # `__stdcall bool eligible(player, object)`. True when the player's army flags no member at
    # all - the stock rule stands - or when a member flagged for the current phase names a
    # template the object's is equivalent to.
    a.label("eligible")
    a.emit(0x53, 0x56, 0x57, 0x55)  # push ebx / esi / edi / ebp
    a.emit(0xFF, 0x74, 0x24, 0x14)  # push [esp+0x14]          ; player
    a.emit(0x8B, 0x0D, u32(THE_SKIRMISH_AI_MANAGER))  # mov ecx, [TheSkirmishAIManager]
    a.call_absolute(SKIRMISH_AI_MANAGER_PLAYER_DATA)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "eligible_yes")
    a.emit(0x8B, 0xA8, u32(AI_DATA_ARMY_DEFINITION))  # mov ebp, [eax+0x160]     ; the army
    a.emit(0x85, 0xED)  # test ebp, ebp
    a.jcc(JE, "eligible_yes")

    # The phase, 0 to 2, into edi: whole seconds played against the two phase lengths.
    a.emit(0xA1, u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.emit(0x33, 0xD2)  # xor edx, edx
    a.emit(0xF7, 0x35, u32(LOGIC_FRAMES_PER_SECOND))  # div dword [logic rate]
    a.emit(0xF3, 0x0F, 0x2C, 0x8D, u32(ARMY_DEFINITION_PHASE_DURATION_RUSH))  # cvttss2si ecx, ..
    a.emit(0x33, 0xFF)  # xor edi, edi
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JB, "phased")
    a.emit(0x47)  # inc edi
    a.emit(0xF3, 0x0F, 0x2C, 0x95, u32(ARMY_DEFINITION_PHASE_DURATION_MID_GAME))  # cvttss2si edx
    a.emit(0x03, 0xCA)  # add ecx, edx
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JB, "phased")
    a.emit(0x47)  # inc edi
    a.label("phased")

    a.emit(0x8B, 0x75, ARMY_DEFINITION_MEMBERS)  # mov esi, [ebp+4]         ; begin
    a.emit(0x33, 0xDB)  # xor ebx, ebx             ; bl: some member is flagged
    a.label("member")
    a.emit(0x3B, 0x75, ARMY_DEFINITION_MEMBERS + 4)  # cmp esi, [ebp+8]         ; end
    a.jcc(JE, "members_done")
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "member_next")
    a.emit(0xF7, 0x40, FLAGS_OFFSET, u32(_ANY_PHASE))  # test dword [eax+0x10], 0xffffff
    a.jcc(JE, "member_next")
    a.emit(0xB3, 0x01)  # mov bl, 1
    a.emit(0x80, 0x7C, 0x38, FLAGS_OFFSET, 0x00)  # cmp byte [eax+edi+0x10], 0
    a.jcc(JE, "member_next")  # flagged, but not for this phase
    a.emit(0x50)  # push eax                 ; &Unit, the member's first field
    a.emit(0x8B, 0x0D, u32(THE_THING_FACTORY))  # mov ecx, [TheThingFactory]
    a.call_absolute(THING_FACTORY_FIND_TEMPLATE)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "member_next")
    a.emit(0x8B, 0x4C, 0x24, 0x18)  # mov ecx, [esp+0x18]      ; object
    a.emit(0x8B, 0x49, OBJECT_THING_TEMPLATE)  # mov ecx, [ecx+4]
    a.emit(0x50)  # push eax
    a.call_absolute(THING_TEMPLATE_IS_EQUIVALENT)  # ret 4
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "eligible_yes")
    a.label("member_next")
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4
    a.jmp("member")

    a.label("members_done")
    a.emit(0x84, 0xDB)  # test bl, bl
    a.jcc(JE, "eligible_yes")  # nobody is flagged: the stock rule stands
    a.emit(0x32, 0xC0)  # xor al, al
    a.jmp("eligible_out")
    a.label("eligible_yes")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.label("eligible_out")
    a.emit(0x5D, 0x5F, 0x5E, 0x5B)  # pop ebp / edi / esi / ebx
    a.emit(0xC2, 0x08, 0x00)  # ret 8


def _assemble(section_va: int) -> Asm:
    """The cave's code, assembled for a section based at `section_va`.

    The faction table occupies the first `TABLE_BYTES` of the section and the code follows it,
    so both sit at offsets that do not depend on how many rows either field table has.
    """
    table = section_va
    a = Asm(section_va + TABLE_BYTES)
    _emit_slot_lookups(a, table, table + TABLE_BYTES)
    _emit_any_flagged(a)
    _emit_parsers(a)
    _emit_gate(a)
    _emit_reset(a)
    _emit_build(a)
    _emit_accept(a)
    return a


def build_code(section_va: int) -> bytes:
    """The cave's code, for a section based at `section_va`. The faction table precedes it."""
    return _assemble(section_va).finish()


def _keyword_blob() -> bytes:
    """Every keyword with its terminator, padded so the tables after it are row-aligned."""
    blob = b"".join(name.encode("ascii") + b"\x00" for name in ARMY_KEYWORDS + MEMBER_KEYWORDS)
    return blob + bytes(-len(blob) % ROW_SIZE)


def layout(section_va: int) -> Layout:
    """Where everything but the member table sits. After the code, padded to a row boundary,
    come the keyword strings and then the rebuilt `ArmyDefinition` table; the member table
    follows that one, at a distance that depends on how many rows the image's own has."""
    a = _assemble(section_va)
    code = a.finish()
    cursor = section_va + TABLE_BYTES + len(code) + (-len(code) % ROW_SIZE)
    keywords: dict[str, int] = {}
    for name in ARMY_KEYWORDS + MEMBER_KEYWORDS:
        keywords[name] = cursor
        cursor += len(name) + 1
    routines = {name: a.label_va(name) for name in _ROUTINES}
    return Layout(**routines, keywords=keywords, army_table=cursor + (-cursor % ROW_SIZE))


def _army_rows(pieces: Layout) -> tuple[Entry, ...]:
    declined, size, interval = (pieces.keywords[name] for name in ARMY_KEYWORDS)
    return (
        (declined, pieces.parse_bool, 0, 0),
        (size, pieces.parse_pair, _SLOT_SIZE_PAIR, 0),
        (interval, pieces.parse_pair, _SLOT_INTERVAL_PAIR, 0),
    )


def _member_rows(pieces: Layout) -> tuple[Entry, ...]:
    every, *phases = (pieces.keywords[name] for name in MEMBER_KEYWORDS)
    rows: list[Entry] = [(every, pieces.parse_member, 0, FLAGS_OFFSET)]
    rows += [(name, INI_PARSE_BOOL, 0, FLAGS_OFFSET + phase) for phase, name in enumerate(phases)]
    return tuple(rows)


def _table(rows: tuple[Entry, ...]) -> bytes:
    return b"".join(struct.pack("<IIII", *row) for row in rows) + bytes(ROW_SIZE)


def _member_table_va(pieces: Layout, army_rows: int) -> int:
    """Where the member table lands, given how many rows the image's `ArmyDefinition` table
    had before this patch's three."""
    return pieces.army_table + (army_rows + len(ARMY_KEYWORDS) + 1) * ROW_SIZE


def build_section(
    section_va: int, army_rows: tuple[Entry, ...], member_rows: tuple[Entry, ...]
) -> bytes:
    """The whole section: the zeroed faction table, the code, the keywords, then each field
    table as its live rows, this patch's rows and a terminator."""
    pieces = layout(section_va)
    code = build_code(section_va)
    blob = bytes(TABLE_BYTES) + code + bytes(-len(code) % ROW_SIZE) + _keyword_blob()
    assert section_va + len(blob) == pieces.army_table, "the cave and its layout disagree"
    blob += _table(army_rows + _army_rows(pieces))
    assert section_va + len(blob) == _member_table_va(pieces, len(army_rows))
    return blob + _table(member_rows + _member_rows(pieces))


class AiFarmKillGatePatch(Patch):
    name = "ai-farm-kill-gate"
    author = "officialNecro"
    description = (
        "Put the skirmish AI's farm raids in the INI, and make them opt-in: a Side raids only if "
        "its ArmyDefinition says FarmKillSquad = Yes, or leaves that unwritten and flags a "
        "member. An ArmyDefinition that writes neither stops raiding. Also on ArmyDefinition: "
        "FarmKillSquadSize = <min> <max> (units in a squad, in place of 1-3) and "
        "FarmKillSquadInterval = <min> <max> (seconds between squads, in place of 10-60). On "
        "ArmyMemberDefinition: FarmKillerTeam = <Bool>, or FarmKillerTeamPhase1/2/3 for one "
        "phase each; once an army flags any member, only members flagged for the current phase "
        "join a squad"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        army_va = self._resolve_army(data)
        member_va = self._resolve_member(data)
        army_rows = live_rows(data, army_va)
        member_rows = live_rows(data, member_va)
        for rows, names, block in (
            (army_rows, ARMY_KEYWORDS, "ArmyDefinition"),
            (member_rows, MEMBER_KEYWORDS, "ArmyMemberDefinition"),
        ):
            for name in names:
                if entries_before(data, rows, name) is not None:
                    raise ValueError(f"the live {block} table already names {name!r}")

        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base: build_section(base, army_rows, member_rows),
            _CHARACTERISTICS,
        )
        pieces = layout(section_va)
        new_member_va = _member_table_va(pieces, len(army_rows))
        for file_off, old, new, note in self._edits(
            data, pieces, army_va, member_va, new_member_va
        ):
            apply_byte_patch(data, file_off, old, new, note)

    def _edits(
        self,
        data: bytes | bytearray,
        pieces: Layout,
        army_va: int,
        member_va: int,
        new_member_va: int,
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte this patch writes outside its own cave, as
        `(file offset, expected, replacement, note)`."""
        edits: list[tuple[int, bytes, bytes, str]] = []
        for slot, stock, routine, what in (
            (
                AI_FARM_KILL_SQUAD_RUN_GATE_SLOT,
                AI_FARM_KILL_SQUAD_RUN_GATE,
                pieces.gate,
                "run gate",
            ),
            (AI_FARM_KILL_SQUAD_RESET_SLOT, AI_FARM_KILL_SQUAD_RESET, pieces.reset, "reset"),
            (AI_FARM_KILL_SQUAD_BUILD_SLOT, AI_FARM_KILL_SQUAD_BUILD, pieces.build, "squad build"),
        ):
            edits.append(
                (
                    self._offset(data, AI_FARM_KILL_SQUAD_VTABLE + slot),
                    u32(stock),
                    u32(routine),
                    f"AIFarmKillSquad {what} -> {SECTION_NAME}",
                )
            )
        edits += [
            (
                self._offset(data, call_va),
                call_rel32(call_va, AI_TEAM_RECRUIT_ACCEPT),
                call_rel32(call_va, pieces.accept),
                f"team recruiter's object test at 0x{call_va:08x} -> {SECTION_NAME}",
            )
            for call_va in AI_TEAM_RECRUIT_ACCEPT_CALLS
        ]
        alloc_call = ARMY_MEMBER_DEFINITION_ALLOC + 2
        edits.append(
            (
                self._offset(data, ARMY_MEMBER_DEFINITION_ALLOC),
                ARMY_MEMBER_DEFINITION_ALLOC_BYTES,
                bytes([0x6A, PATCHED_MEMBER_SIZE]) + call_rel32(alloc_call, pieces.alloc),
                "ArmyMemberDefinition allocation: four more bytes, cleared",
            )
        )
        for refs, opcodes, old_va, new_va, block in (
            (
                ARMY_DEFINITION_FIELD_TABLE_REFS,
                ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES,
                army_va,
                pieces.army_table,
                "ArmyDefinition",
            ),
            (
                ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS,
                ARMY_MEMBER_DEFINITION_FIELD_TABLE_REF_OPCODES,
                member_va,
                new_member_va,
                "ArmyMemberDefinition",
            ),
        ):
            edits += [
                (
                    self._offset(data, ref_va),
                    bytes([opcode]) + u32(old_va),
                    bytes([opcode]) + u32(new_va),
                    f"{block} field table reference 0x{ref_va:08x} -> {SECTION_NAME}",
                )
                for ref_va, opcode in zip(refs, opcodes, strict=True)
            ]
        return edits

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @staticmethod
    def _resolve_army(data: bytes | bytearray) -> int:
        """The `ArmyDefinition` field table's base VA, as the image currently holds it."""
        return resolve_table(
            data,
            ARMY_DEFINITION_FIELD_TABLE_REFS,
            ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES,
            "ArmyDefinition",
        )

    @staticmethod
    def _resolve_member(data: bytes | bytearray) -> int:
        """The `ArmyMemberDefinition` field table's base VA, as the image currently holds it."""
        return resolve_table(
            data,
            ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS,
            ARMY_MEMBER_DEFINITION_FIELD_TABLE_REF_OPCODES,
            "ArmyMemberDefinition",
        )

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the farm raid "
                    "tactic is not this build's, so the cave would call the wrong routines"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        pieces = layout(section_va)
        problems: list[str] = []

        # Only the code is compared. The faction table sits ahead of it and is written while the
        # engine reads its INI, and the rows copied into the field tables are whatever was live.
        code = build_code(section_va)
        start = section_off + TABLE_BYTES
        if bytes(data[start : start + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected code")

        try:
            army = read_field_table(data, self._resolve_army(data))
            member = read_field_table(data, self._resolve_member(data))
            edits = self._edits(data, pieces, 0, 0, 0)
        except (ValueError, struct.error) as exc:
            return [*problems, f"cannot read back the patch (wrong build?): {exc}"]

        for file_off, _old, new, note in edits:
            if "field table reference" in note:
                continue  # another patch may have rebuilt the table again; the rows are checked
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note}: expected {new.hex()}, found {got.hex()}")
        for rows, wanted, block in (
            (army, _army_rows(pieces), "ArmyDefinition"),
            (member, _member_rows(pieces), "ArmyMemberDefinition"),
        ):
            for row in wanted:
                keyword = read_cstring(data, row[0])
                if row not in rows:
                    problems.append(f"the live {block} table has no {keyword} row of this patch's")
        return problems

    def ini_surface(self) -> Engine:
        """The seven fields. `FarmKillSquad` has no default to state: unwritten is its own third
        answer, "raid if a member is flagged". A pair that is not written leaves the engine's
        own numbers, and a member with no flag is not chosen."""
        declined, size, interval = ARMY_KEYWORDS
        fields = [
            FieldDelta("ArmyDefinition", declined, "Bool", None, self.name),
            FieldDelta("ArmyDefinition", size, "Int[]", None, self.name),
            FieldDelta("ArmyDefinition", interval, "Int[]", None, self.name),
        ]
        fields += [
            FieldDelta("ArmyMemberDefinition", name, "Bool", False, self.name)
            for name in MEMBER_KEYWORDS
        ]
        return Engine(fields=tuple(fields))
