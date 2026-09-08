"""The map-transition patch: a script action that loads another map without leaving the session.

Derived in ``../../docs/map-transition.md``. Two hooks and one cave:

* the jump-table entry for a **stubbed** script action, repointed at the cave. The action records
  the destination map name and raises a pending flag; it cannot do the swap itself, because it
  runs inside the script engine's update and the swap resets the script engine.
* `GameLogic::update`'s entry, where the flag is serviced with no script frame on the stack. The
  transition mirrors a player quitting to the menu and picking the next map: end the match with
  `GameLogic::clearGameData`, then **two** posted `MSG_NEW_GAME` messages with a trip through the
  shell map between them. One leaves the current match; then, once the shell is actually up, one
  starts the destination in the mode the session had. The engine has no game-to-game path: it has
  a game-to-shell path and a shell-to-game path, and this chains them. Skipping the teardown, or
  calling `startNewGame` and `loadMap` directly the way `LivingWorldLogic::startCampaign` does,
  builds a world while the previous session is still standing and faults inside construction.

A destination that does not exist is refused before the swap begins, because `loadMap` destroys
the session and *then* looks for the map.

**The local player's army carries across; nothing else does yet.** What counts as the army is
War of the Ring's rule, `KindOf = ARMY_SUMMARY`, taken from the engine's own post-battle harvest:
units and hordes carry, structures do not, and a horde carries once rather than as a horde plus
every one of its members. Each is snapshotted into an `ArmyEntry` record before the teardown and
rebuilt on the destination, which brings template, health, purchased upgrades and veterancy - the
engine marshals all of that itself.

**Script counters, timers and flags carry too**, by name and scope. A timer holds ticks remaining
rather than an expiry frame, so it resumes on the destination with the time it had. The engine's
own `___MusicScript_` state is deliberately left behind.

**So does the player's purse, command-point ceiling and spellbook currency**, along with the
purchased sciences and the completed-upgrade set. The points-in-use counter is not carried, because
restoring the army re-accrues it; and the upgrades are replayed through the engine's own grant path
rather than written back as a bitset, so whatever an upgrade does on completion happens.

**Special-power cooldowns are out of scope**, so powers arrive ready. The hero revival ledger is
the one layer still outstanding.

**It edits `GameLogic::update`'s first five bytes, which `live-bridge` also takes.** The two do not
compose; `apply_byte_patch` raises for whichever is applied second rather than corrupting the site.
"""

from __future__ import annotations

import struct

from ...addresses import (
    APPEND_MESSAGE_VTABLE_SLOT,
    ARMY_ENTRY_RECORD_CTOR,
    ARMY_RECORD_CREATE_OBJECT,
    ASCII_STRING_COPY,
    ASCII_STRING_CTOR,
    ASCII_STRING_FORMAT,
    CLEAR_GAME_DATA,
    FILE_SYSTEM_DOES_FILE_EXIST,
    GAME_LOGIC_UPDATE,
    GAME_LOGIC_UPDATE_ENTRY,
    GAME_LOGIC_UPDATE_VTABLE_SLOT,
    GAME_MESSAGE_APPEND_INTEGER,
    GLOBAL_DATA,
    GLOBAL_DATA_SHELL_MAP,
    GLOBAL_DATA_STAGED_MAP,
    KINDOF_ARMY_SUMMARY_BIT,
    KINDOF_ARMY_SUMMARY_BYTE,
    MAP_PATH_FORMAT,
    MSG_NEW_GAME,
    OBJECT_ANGLE,
    OBJECT_ARMY_EXCLUDED,
    OBJECT_ARMY_EXCLUDED_BIT,
    OBJECT_POSITION,
    OBJECT_SET_ORIENTATION,
    OBJECT_SET_POSITION,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    OBJECT_TEST_STATUS,
    OBJECT_THING_TEMPLATE,
    OBJECT_TO_ARMY_RECORD,
    PLAYER_COMMAND_POINTS_BONUS,
    PLAYER_COMMAND_POINTS_CAP,
    PLAYER_COMMAND_POINTS_HARD_CAP,
    PLAYER_COMPLETED_UPGRADE_MASK,
    PLAYER_COMPLETED_UPGRADE_MASK_WORDS,
    PLAYER_FOR_EACH_TEAM_OBJECT,
    PLAYER_GRANT_UPGRADE,
    PLAYER_LIST_GET_LOCAL_PLAYER,
    PLAYER_POWER_POINTS,
    PLAYER_POWER_POINTS_TOTAL,
    PLAYER_RESOURCES,
    PLAYER_SCIENCES,
    PLAYER_SET_SCIENCES,
    SCRIPT_ACTION_EPILOGUE,
    SCRIPT_ACTION_JUMP_TABLE,
    SCRIPT_ACTION_PARAM_ARRAY,
    SCRIPT_ACTION_PARAM_COUNT,
    SCRIPT_COUNTER_IS_SECONDS,
    SCRIPT_COUNTER_IS_TIMER,
    SCRIPT_COUNTER_VALUE,
    SCRIPT_ENGINE_COUNTER_MAP,
    SCRIPT_ENGINE_FIND_OR_CREATE_COUNTER,
    SCRIPT_ENGINE_FIND_OR_CREATE_FLAG,
    SCRIPT_ENGINE_FLAG_MAP,
    SCRIPT_PARAMETER_STRING,
    STD_MAP_ITERATOR_INCREMENT,
    STD_MAP_NODE_VALUE,
    THE_GAME_INFO,
    THE_GAME_LOGIC,
    THE_MESSAGE_STREAM,
    THE_PLAYER_LIST,
    THE_SCRIPT_ENGINE,
    THE_SKIRMISH_GAME_INFO,
    THE_UPGRADE_CENTER,
    UPGRADE_FIRST_SET,
    UPGRADE_TEMPLATE_INDEX,
)
from ...asm import JE, JGE, JL, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ACTION_ID",
    "ANCHORS",
    "CODE_OFF",
    "NAME_MAX",
    "NAME_OFF",
    "COUNT_OFF",
    "MAX_OBJECTS",
    "MAX_SCIENCES",
    "MAX_SCRIPT_RECORDS",
    "PENDING_OFF",
    "PLAYER_STATE_OFF",
    "PLAYER_STATE_SIZE",
    "PLAYER_STATE_UPGRADE_MASK",
    "PLAYER_STATE_UPGRADE_SCRATCH",
    "PLAYER_STATE_VALID",
    "RECORDS_OFF",
    "SLOT_SIZE",
    "SAVED_MODE_OFF",
    "SCRIPT_COUNT_OFF",
    "SCRIPT_NAME_MAX",
    "SCRIPT_RECORDS_OFF",
    "SCRIPT_SLOT_IS_SECONDS",
    "SCRIPT_SLOT_IS_TIMER",
    "SCRIPT_SLOT_KIND",
    "SCRIPT_SLOT_SIZE",
    "SCRIPT_SLOT_VALUE",
    "SECTION_NAME",
    "TABLE_SLOT_VA",
    "MapTransitionPatch",
    "build_section",
    "entry_points",
]

SECTION_NAME = ".maptran"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ | MEM_WRITE - the cave writes its own pending flag
# and name buffer, so the section cannot be read-only.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

#: `PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME`, one of five consecutive stubs (539-543) that dispatch to
#: the shared epilogue and do nothing. Chosen over the other dead ids because the whole assimilate
#: and reinforcement family appears **zero** times across the 480-map Edain corpus, so no existing
#: map can trigger a transition by accident - which `LIVING_WORLD_DESPAWN_ARMY` (365) and
#: `MAP_REVEAL_IN_TRIGGER` (553) cannot promise, each having one live occurrence.
#:
#: Its stock parameters are a player and a string, so a mapper places it in WorldBuilder under that
#: name and types the destination in the string slot. This build reads only the string; the player
#: slot is what a later layer uses to say whose army carries.
ACTION_ID = 540

PENDING_OFF = 0x00
#: The mode the session had when the transition was asked for, held across the trip through the
#: shell so the destination starts in the same kind of game.
SAVED_MODE_OFF = 0x04
#: How many objects the snapshot captured.
COUNT_OFF = 0x08
NAME_OFF = 0x10
#: Enough for any `maps\<name>\<name>.map` stem. The copy is bounded by this and always
#: terminates, so an over-long script string is truncated rather than running off the buffer.
NAME_MAX = 128

#: One carried object: the `ARMY_RECORD_SIZE` record the engine fills, then the position and
#: facing it does **not** carry. `ArmyRecord::createObject` rebuilds template, team, health and
#: the upgrade mask - which includes veterancy - but places nothing, so the two are stored side by
#: side and replayed together.
RECORD_POSITION_OFF = 0xD8
RECORD_ANGLE_OFF = 0xE4
SLOT_SIZE = 0xE8

#: The ceiling on carried objects. 256 slots is 58 KB of section, comfortably more than a
#: scenario army, and the callback stops recording past it rather than growing the arena.
MAX_OBJECTS = 256

RECORDS_OFF = NAME_OFF + NAME_MAX

#: One carried script symbol: a counter, a timer or a flag. The name is stored **scope-qualified**
#: as `<scope>/<name>`, always with the separator even when the scope is empty, because
#: `SCRIPT_KEY_COMPOSE` splits on the first `/` and only falls back to the engine's current scope
#: when there is none. Writing the separator unconditionally means restore never depends on what
#: `SCRIPT_ENGINE_SCOPE` happens to hold, which outside script evaluation is not a defined thing.
SCRIPT_SLOT_VALUE = 0x48
SCRIPT_SLOT_IS_TIMER = 0x4C
SCRIPT_SLOT_IS_SECONDS = 0x4D
#: 0 for a counter or timer, 1 for a flag - which map the record goes back into.
SCRIPT_SLOT_KIND = 0x4E
SCRIPT_SLOT_SIZE = 0x50
#: The name buffer is everything before the value, and the copy is bounded by it.
SCRIPT_NAME_MAX = SCRIPT_SLOT_VALUE

#: The ceiling on carried script symbols. A live Edain skirmish holds 11 counters and 17 flags,
#: most of them the engine's own `___MusicScript_` state, which is filtered out.
MAX_SCRIPT_RECORDS = 128

SCRIPT_COUNT_OFF = RECORDS_OFF + MAX_OBJECTS * SLOT_SIZE
SCRIPT_RECORDS_OFF = SCRIPT_COUNT_OFF + 0x10

#: The player's own state, as flat fields. `PLAYER_STATE_VALID` says the snapshot ran, so an
#: aborted transition restores nothing rather than zeroing the player's purse.
#:
#: **The points-in-use counter is deliberately absent.** `Player+0x68` is maintained by the engine
#: as objects are created and destroyed (`0x006A7FDA` / `0x006A7FEB`), so restoring the army
#: re-accrues it; carrying the number as well would count every carried unit twice.
PLAYER_STATE_VALID = 0x00
PLAYER_STATE_MONEY = 0x04
PLAYER_STATE_CP_CAP = 0x08
PLAYER_STATE_CP_BONUS = 0x0C
PLAYER_STATE_CP_HARD_CAP = 0x10
PLAYER_STATE_POWER_POINTS = 0x14
PLAYER_STATE_POWER_POINTS_TOTAL = 0x18
PLAYER_STATE_SCIENCE_COUNT = 0x1C
#: The completed-upgrade bitset, and a second copy of it. Restore consumes the copy - the engine's
#: own replay clears each bit as it grants it - so the snapshot survives a transition that aborts
#: part way and the arena needs no stack scratch.
PLAYER_STATE_UPGRADE_MASK = 0x20
PLAYER_STATE_UPGRADE_SCRATCH = PLAYER_STATE_UPGRADE_MASK + PLAYER_COMPLETED_UPGRADE_MASK_WORDS * 4
PLAYER_STATE_SCIENCES = PLAYER_STATE_UPGRADE_SCRATCH + PLAYER_COMPLETED_UPGRADE_MASK_WORDS * 4
#: A skirmish seat holds four or five. The copy stops here rather than growing the arena.
MAX_SCIENCES = 64
PLAYER_STATE_SIZE = PLAYER_STATE_SCIENCES + MAX_SCIENCES * 4

PLAYER_STATE_OFF = SCRIPT_RECORDS_OFF + MAX_SCRIPT_RECORDS * SCRIPT_SLOT_SIZE
CODE_OFF = PLAYER_STATE_OFF + PLAYER_STATE_SIZE

HOOK_VA = GAME_LOGIC_UPDATE
HOOK_ORIGINAL = GAME_LOGIC_UPDATE_ENTRY
HOOK_RETURN_VA = HOOK_VA + len(HOOK_ORIGINAL)

#: The jump-table slot this patch takes over, and the dword it must hold first.
TABLE_SLOT_VA = SCRIPT_ACTION_JUMP_TABLE + ACTION_ID * 4
TABLE_SLOT_STOCK = struct.pack("<I", SCRIPT_ACTION_EPILOGUE)

#: The first instruction at each address the cave jumps to or returns into. A build whose layout
#: moved fails here rather than on a wild jump. The epilogue's `mov ecx, [ebp-0xc]` is the SEH
#: unwind it performs for every case body, which is why the action must reach it with the stack
#: as it found it.
ANCHORS = {
    SCRIPT_ACTION_EPILOGUE: bytes.fromhex("8b4df4"),
    HOOK_RETURN_VA: bytes.fromhex("e8fee94000"),
}

#: `GameLogic::m_gameMode`, read back so a transition keeps the mode the session already has.
_GAME_MODE_OFFSET = 0x110

#: The two modes that mean "no match is running". `4` is the shell map. `9` is what the engine
#: actually rests at after an end-of-match flow drops the player in the skirmish lobby - read out
#: of a live process sitting in exactly that state, which is why step two waited forever for `4`
#: alone. The engine's own shell return special-cases `9` at `0x0075DEAA` for the same reason.
_MODE_SHELL_MAP = 4
_MODE_NO_SESSION = 9


#: `(Player offset, slot offset)`, snapshotted and restored in this order. Kept as one table so
#: the two routines cannot disagree about which field went where.
_PLAYER_STATE_FIELDS = (
    (PLAYER_RESOURCES, PLAYER_STATE_MONEY),
    (PLAYER_COMMAND_POINTS_CAP, PLAYER_STATE_CP_CAP),
    (PLAYER_COMMAND_POINTS_BONUS, PLAYER_STATE_CP_BONUS),
    (PLAYER_COMMAND_POINTS_HARD_CAP, PLAYER_STATE_CP_HARD_CAP),
    (PLAYER_POWER_POINTS, PLAYER_STATE_POWER_POINTS),
    (PLAYER_POWER_POINTS_TOTAL, PLAYER_STATE_POWER_POINTS_TOTAL),
)


def _emit(base_va: int) -> Asm:
    """Lay out both routines, returning the emitter so callers can read the labels back."""
    pending_va = base_va + PENDING_OFF
    saved_mode_va = base_va + SAVED_MODE_OFF
    name_va = base_va + NAME_OFF
    count_va = base_va + COUNT_OFF
    records_va = base_va + RECORDS_OFF
    script_count_va = base_va + SCRIPT_COUNT_OFF
    script_records_va = base_va + SCRIPT_RECORDS_OFF
    player_state_va = base_va + PLAYER_STATE_OFF
    science_count_va = player_state_va + PLAYER_STATE_SCIENCE_COUNT
    sciences_va = player_state_va + PLAYER_STATE_SCIENCES
    mask_va = player_state_va + PLAYER_STATE_UPGRADE_MASK
    scratch_va = player_state_va + PLAYER_STATE_UPGRADE_SCRATCH

    a = Asm(base_va + CODE_OFF)

    # The script action. Entered from the jump table with `esi` = the ScriptAction and `edi` =
    # the ScriptActions object, and it must leave through the shared epilogue like any case body.
    # The per-object callback the engine's object walk drives: `cdecl (Object *, void *ctx)`,
    # caller-cleaned, returning non-zero to keep going. It writes one slot per object.
    a.label("record_one")
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0x74, 0x24, 0x0C)  # mov esi, [esp+0xc]   ; the Object

    # Carry what the engine itself considers part of an army. `LIVING_WORLD_BATTLE_HARVEST`
    # (`0x00811E1F`) is War of the Ring's own answer to "which of these objects go home with the
    # player", and two of its four filters are not living-world-specific:
    #
    #   00811e93  mov  eax, [edi + 4]           ; the ThingTemplate
    #   00811e96  test byte [eax + 0x118], bl   ; KindOf = ARMY_SUMMARY
    #   00811e9c  je   skip
    #   00811ea2  test byte [edi + 0x458], bl
    #   00811ea8  jne  skip
    #
    # `ARMY_SUMMARY` is the whole selection rule, and it is better than "not a structure" in a way
    # that matters here: hordes carry it and their **members do not**, so a horde is carried once,
    # as a horde, and `createObject` rebuilds its members. Walking every team object took the
    # horde *and* each of its members and put both back.
    a.emit(0x8B, 0x46, OBJECT_THING_TEMPLATE)  # mov eax, [esi+4]
    a.emit(0xF6, 0x80, struct.pack("<I", KINDOF_ARMY_SUMMARY_BYTE), KINDOF_ARMY_SUMMARY_BIT)
    a.jcc(JE, "record_done")
    a.emit(0xF6, 0x86, struct.pack("<I", OBJECT_ARMY_EXCLUDED), OBJECT_ARMY_EXCLUDED_BIT)
    a.jcc(JNE, "record_done")

    # Skip anything still under construction, exactly as the engine's own per-object callback
    # does at `0x00885234` before it counts. A half-built object is not something to carry, and
    # matching the one precedent in the image for this walk costs four instructions.
    a.emit(0x6A, OBJECT_STATUS_UNDER_CONSTRUCTION)  # push 2
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_TEST_STATUS)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "record_done")

    a.emit(0x8B, 0x3D, struct.pack("<I", count_va))  # mov edi, [count]
    a.emit(0x81, 0xFF, struct.pack("<I", MAX_OBJECTS))  # cmp edi, MAX_OBJECTS
    a.jcc(JGE, "record_done")
    a.emit(0x69, 0xFF, struct.pack("<I", SLOT_SIZE))  # imul edi, edi, SLOT_SIZE
    a.emit(0x81, 0xC7, struct.pack("<I", records_va))  # add edi, records
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(ARMY_ENTRY_RECORD_CTOR)  # construct the record in place
    a.emit(0x57)  # push edi              ; the record
    a.emit(0x8B, 0xCE)  # mov ecx, esi          ; the Object
    a.call_absolute(OBJECT_TO_ARMY_RECORD)  # name, quantity, state block, upgrades

    # The record carries no position, so the two fields it omits are stored beside it.
    for step in range(3):
        a.emit(0x8B, 0x46, OBJECT_POSITION + step * 4)  # mov eax, [esi+0x38+n]
        # disp32, not disp8: 0xD8 does not fit a signed byte and would store at edi-0x28.
        a.emit(0x89, 0x87, struct.pack("<I", RECORD_POSITION_OFF + step * 4))
    a.emit(0x8B, 0x46, OBJECT_ANGLE)  # mov eax, [esi+0x44]
    a.emit(0x89, 0x87, struct.pack("<I", RECORD_ANGLE_OFF))  # mov [edi+0xe4], eax
    a.emit(0xFF, 0x05, struct.pack("<I", count_va))  # inc dword [count]

    a.label("record_done")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x40)  # inc eax               ; keep walking
    a.emit(0xC3)  # ret                   ; cdecl: the caller cleans

    # Snapshot the local player's objects. Called from step one **before** the teardown, which is
    # the only moment they still exist.
    a.label("snapshot")
    a.emit(0xC7, 0x05, struct.pack("<I", count_va), struct.pack("<I", 0))  # count = 0
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "snapshot_done")
    a.emit(0x6A, 0x00)  # push 0               ; ctx
    a.emit(0x68, struct.pack("<I", a.label_va("record_one")))  # push the callback
    a.emit(0x8B, 0xC8)  # mov ecx, eax          ; the Player
    a.call_absolute(PLAYER_FOR_EACH_TEAM_OBJECT)  # ret 8
    a.label("snapshot_done")
    a.emit(0xC3)  # ret

    # Put them back on the destination map. `ArmyRecord::createObject` rebuilds each object onto
    # the receiving player's default team with its health and upgrade mask - veterancy included -
    # and this replays the position and facing the record does not carry.
    a.label("restore")
    a.emit(0x83, 0x3D, struct.pack("<I", count_va), 0x00)  # cmp dword [count], 0
    a.jcc(JE, "restore_done")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "restore_clear")
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xD8)  # mov ebx, eax          ; the Player
    a.emit(0x33, 0xF6)  # xor esi, esi          ; index

    a.label("restore_loop")
    a.emit(0x8B, 0xFE)  # mov edi, esi
    a.emit(0x69, 0xFF, struct.pack("<I", SLOT_SIZE))  # imul edi, edi, SLOT_SIZE
    a.emit(0x81, 0xC7, struct.pack("<I", records_va))  # add edi, records
    a.emit(0x53)  # push ebx              ; the receiving Player
    a.emit(0x8B, 0xCF)  # mov ecx, edi          ; the record
    a.call_absolute(ARMY_RECORD_CREATE_OBJECT)  # ret 4 -> the new Object
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "restore_next")
    a.emit(0x50)  # push eax              ; keep the object across setPosition
    a.emit(0x8D, 0x97, struct.pack("<I", RECORD_POSITION_OFF))  # lea edx, [edi+0xd8]
    a.emit(0x52)  # push edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(OBJECT_SET_POSITION)  # ret 4
    a.emit(0x58)  # pop eax
    a.emit(0xFF, 0xB7, struct.pack("<I", RECORD_ANGLE_OFF))  # push dword [edi+0xe4]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(OBJECT_SET_ORIENTATION)  # ret 4

    a.label("restore_next")
    a.emit(0x46)  # inc esi
    a.emit(0x3B, 0x35, struct.pack("<I", count_va))  # cmp esi, [count]
    a.jcc(JL, "restore_loop")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx

    a.label("restore_clear")
    a.emit(0xC7, 0x05, struct.pack("<I", count_va), struct.pack("<I", 0))  # count = 0
    a.label("restore_done")
    a.emit(0xC3)  # ret

    # The player's own state: the purse, the command-point ceiling and the spellbook currency.
    #
    # Every field is addressed with a **disp32** even where a disp8 would encode. `Player+0x94` and
    # `Player+0x14C` do not fit a signed byte, and mixing the two forms in one block is how the
    # object record grew a `[edi-0x28]` store that assembled cleanly and corrupted the arena.
    #
    # The command-point *ceiling* carries even though it is normally earned from buildings, which
    # do not carry: an army that arrives without the headroom to hold it is over its cap on the
    # first frame. The engine combines the three as
    # `min(base + bonus + <filtered extras>, hard)`, so all three flat fields go and the extras -
    # a vector of `ObjectFilter`-carrying entries - are left to the destination.
    a.label("player_snapshot")
    a.emit(
        0xC7, 0x05, struct.pack("<I", player_state_va + PLAYER_STATE_VALID), struct.pack("<I", 0)
    )
    a.emit(0xC7, 0x05, struct.pack("<I", science_count_va), struct.pack("<I", 0))
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "player_snapshot_done")
    for player_off, slot_off in _PLAYER_STATE_FIELDS:
        a.emit(0x8B, 0x88, struct.pack("<I", player_off))  # mov ecx, [eax+<field>]
        a.emit(0x89, 0x0D, struct.pack("<I", player_state_va + slot_off))  # mov [slot], ecx

    # The completed-upgrade bitset, verbatim. Restore replays it through the engine rather than
    # writing it back, so what is stored is only the set of bits.
    a.emit(0x33, 0xC9)  # xor ecx, ecx
    a.label("player_mask_loop")
    a.emit(
        0x8B, 0x94, 0x88, struct.pack("<I", PLAYER_COMPLETED_UPGRADE_MASK)
    )  # mov edx,[eax+ecx*4+m]
    a.emit(0x89, 0x14, 0x8D, struct.pack("<I", mask_va))  # mov [mask + ecx*4], edx
    a.emit(0x41)  # inc ecx
    a.emit(0x83, 0xF9, PLAYER_COMPLETED_UPGRADE_MASK_WORDS)  # cmp ecx, 36
    a.jcc(JL, "player_mask_loop")

    # The purchased sciences: a `std::vector<ScienceType>`, so begin and end and a bounded copy.
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x88, struct.pack("<I", PLAYER_SCIENCES))  # mov ecx, [eax+0x310]  ; begin
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "player_sciences_done")
    a.emit(0x8B, 0x90, struct.pack("<I", PLAYER_SCIENCES + 4))  # mov edx, [eax+0x314]  ; end
    a.emit(0x2B, 0xD1)  # sub edx, ecx
    a.emit(0xC1, 0xFA, 0x02)  # sar edx, 2            ; the count
    a.jcc(JLE, "player_sciences_done")
    a.emit(0x81, 0xFA, struct.pack("<I", MAX_SCIENCES))  # cmp edx, MAX_SCIENCES
    a.jcc(JLE, "player_sciences_bounded")
    a.emit(0xBA, struct.pack("<I", MAX_SCIENCES))  # mov edx, MAX_SCIENCES
    a.label("player_sciences_bounded")
    a.emit(0x89, 0x15, struct.pack("<I", science_count_va))  # mov [science_count], edx
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("player_sciences_loop")
    a.emit(0x8B, 0x34, 0x81)  # mov esi, [ecx+eax*4]
    a.emit(0x89, 0x34, 0x85, struct.pack("<I", sciences_va))  # mov [sciences + eax*4], esi
    a.emit(0x40)  # inc eax
    a.emit(0x3B, 0xC2)  # cmp eax, edx
    a.jcc(JL, "player_sciences_loop")
    a.label("player_sciences_done")
    a.emit(0x5E)  # pop esi

    a.emit(
        0xC7, 0x05, struct.pack("<I", player_state_va + PLAYER_STATE_VALID), struct.pack("<I", 1)
    )
    a.label("player_snapshot_done")
    a.emit(0xC3)  # ret

    # Put it back before the army does, so the ceiling is in place by the time carried units
    # start adding themselves to the points in use underneath it.
    a.label("player_restore")
    a.emit(0x83, 0x3D, struct.pack("<I", player_state_va + PLAYER_STATE_VALID), 0x00)
    a.jcc(JE, "player_restore_done")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "player_restore_clear")
    for player_off, slot_off in _PLAYER_STATE_FIELDS:
        a.emit(0x8B, 0x0D, struct.pack("<I", player_state_va + slot_off))  # mov ecx, [slot]
        a.emit(0x89, 0x88, struct.pack("<I", player_off))  # mov [eax+<field>], ecx

    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xF0)  # mov esi, eax          ; the Player, across both calls below

    # The sciences, as one assignment. `setSciences` reads only begin and end, so the argument is
    # a three-word header built on the stack over the arena's own buffer - and it returns without
    # doing anything when the two are equal, which is the empty case handled for free.
    a.emit(0x8B, 0x15, struct.pack("<I", science_count_va))  # mov edx, [science_count]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "player_sciences_restored")
    a.emit(0xB8, struct.pack("<I", sciences_va))  # mov eax, sciences
    a.emit(0x8D, 0x14, 0x90)  # lea edx, [eax+edx*4]  ; one past the last
    a.emit(0x52)  # push edx              ; capacity end
    a.emit(0x52)  # push edx              ; end
    a.emit(0x50)  # push eax              ; begin
    a.emit(0x8B, 0xD4)  # mov edx, esp
    a.emit(0x52)  # push edx
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(PLAYER_SET_SCIENCES)  # ret 4
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc          ; drop the header
    a.label("player_sciences_restored")

    # The upgrades, replayed the way `LIVING_WORLD_BATTLE_SETUP` replays them: turn the mask into
    # a template, grant it through the engine so whatever it does on completion happens, clear the
    # bit, go round. Writing the bitset back directly would set every bit and run nothing.
    a.emit(0x33, 0xC9)  # xor ecx, ecx
    a.label("player_scratch_loop")
    a.emit(0x8B, 0x14, 0x8D, struct.pack("<I", mask_va))  # mov edx, [mask + ecx*4]
    a.emit(0x89, 0x14, 0x8D, struct.pack("<I", scratch_va))  # mov [scratch + ecx*4], edx
    a.emit(0x41)  # inc ecx
    a.emit(0x83, 0xF9, PLAYER_COMPLETED_UPGRADE_MASK_WORDS)  # cmp ecx, 36
    a.jcc(JL, "player_scratch_loop")

    a.label("player_upgrade_loop")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_UPGRADE_CENTER))  # mov ecx, [TheUpgradeCenter]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "player_upgrades_done")
    a.emit(0x68, struct.pack("<I", scratch_va))  # push scratch
    a.call_absolute(UPGRADE_FIRST_SET)  # ret 4 -> UpgradeTemplate * or 0
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "player_upgrades_done")
    a.emit(0x8B, 0xF8)  # mov edi, eax
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x6A, 0x02)  # push 2
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(PLAYER_GRANT_UPGRADE)  # ret 0xc
    # Clear the bit whatever the grant did, so the loop always makes progress.
    a.emit(0x8B, 0x4F, UPGRADE_TEMPLATE_INDEX)  # mov ecx, [edi+0x38]
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.emit(0xC1, 0xE8, 0x05)  # shr eax, 5            ; the word
    a.emit(0x83, 0xE1, 0x1F)  # and ecx, 0x1f         ; the bit
    a.emit(0xBA, struct.pack("<I", 1))  # mov edx, 1
    a.emit(0xD3, 0xE2)  # shl edx, cl
    a.emit(0xF7, 0xD2)  # not edx
    a.emit(0x21, 0x14, 0x85, struct.pack("<I", scratch_va))  # and [scratch + eax*4], edx
    a.jmp("player_upgrade_loop")

    a.label("player_upgrades_done")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.label("player_restore_clear")
    a.emit(
        0xC7, 0x05, struct.pack("<I", player_state_va + PLAYER_STATE_VALID), struct.pack("<I", 0)
    )
    a.label("player_restore_done")
    a.emit(0xC3)  # ret

    # The script state: counters, timers and flags, carried by name.
    #
    # Counters and timers are one `std::map` at `SCRIPT_ENGINE_COUNTER_MAP` and flags another at
    # `SCRIPT_ENGINE_FLAG_MAP`; a timer is a counter record with `SCRIPT_COUNTER_IS_TIMER` set.
    # The node layout is read off a live engine rather than assumed: `+0x10` the scope
    # `AsciiString`, `+0x14` the name, `STD_MAP_NODE_VALUE` the record. The tree is ordered by
    # scope first and then name, which is the second confirmation of which field is which.
    #
    # A timer holds ticks **remaining** and never references the frame counter, so carrying the
    # record verbatim resumes it with the time it had. Nothing needs rebasing.
    a.label("script_append")
    # `edi` the slot, `ecx` the write index, `edx` the source: copy until NUL, bounded.
    a.emit(0x8A, 0x02)  # mov al, [edx]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "script_append_done")
    a.emit(0x83, 0xF9, SCRIPT_NAME_MAX - 2)  # cmp ecx, 0x46
    a.jcc(JGE, "script_append_done")
    a.emit(0x88, 0x04, 0x0F)  # mov [edi+ecx], al
    a.emit(0x41)  # inc ecx
    a.emit(0x42)  # inc edx
    a.jmp("script_append")
    a.label("script_append_done")
    a.emit(0xC3)  # ret

    # One node into one slot. `esi` the node, `bl` the kind. `edi` is saved because the caller is
    # holding the map header in it, and this needs it for the slot.
    a.label("script_record")
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0x46, 0x14)  # mov eax, [esi+0x14]   ; the name AsciiString
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "script_record_done")

    # Skip the engine's own `___MusicScript_` state. Three leading underscores is its convention
    # for script symbols the map did not author, and carrying them would hand the destination's
    # music scripts the source map's idea of what has already been initialised.
    a.emit(0x80, 0x78, 0x08, 0x5F)  # cmp byte [eax+8], 0x5f
    a.jcc(JNE, "script_record_keep")
    a.emit(0x80, 0x78, 0x09, 0x5F)  # cmp byte [eax+9], 0x5f
    a.jcc(JNE, "script_record_keep")
    a.emit(0x80, 0x78, 0x0A, 0x5F)  # cmp byte [eax+10], 0x5f
    a.jcc(JE, "script_record_done")

    a.label("script_record_keep")
    a.emit(0x8B, 0x3D, struct.pack("<I", script_count_va))  # mov edi, [script_count]
    a.emit(0x81, 0xFF, struct.pack("<I", MAX_SCRIPT_RECORDS))  # cmp edi, MAX_SCRIPT_RECORDS
    a.jcc(JGE, "script_record_done")
    a.emit(0x69, 0xFF, struct.pack("<I", SCRIPT_SLOT_SIZE))  # imul edi, edi, SCRIPT_SLOT_SIZE
    a.emit(0x81, 0xC7, struct.pack("<I", script_records_va))  # add edi, script_records
    a.emit(0x33, 0xC9)  # xor ecx, ecx          ; the write index

    # The scope, then the separator - unconditionally, so a global reads back as /name.
    a.emit(0x8B, 0x56, 0x10)  # mov edx, [esi+0x10]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "script_record_slash")
    a.emit(0x83, 0xC2, 0x08)  # add edx, 8
    a.call("script_append")
    a.label("script_record_slash")
    a.emit(0xC6, 0x04, 0x0F, 0x2F)  # mov byte [edi+ecx], 0x2f
    a.emit(0x41)  # inc ecx

    a.emit(0x8B, 0x56, 0x14)  # mov edx, [esi+0x14]
    a.emit(0x83, 0xC2, 0x08)  # add edx, 8
    a.call("script_append")
    a.emit(0xC6, 0x04, 0x0F, 0x00)  # mov byte [edi+ecx], 0

    a.emit(0x88, 0x5F, SCRIPT_SLOT_KIND)  # mov [edi+0x4e], bl
    a.emit(0x84, 0xDB)  # test bl, bl
    a.jcc(JNE, "script_record_flag")
    a.emit(0x8B, 0x46, STD_MAP_NODE_VALUE)  # mov eax, [esi+0x18]
    a.emit(0x89, 0x47, SCRIPT_SLOT_VALUE)  # mov [edi+0x48], eax
    a.emit(0x8A, 0x46, STD_MAP_NODE_VALUE + SCRIPT_COUNTER_IS_TIMER)  # mov al, [esi+0x1c]
    a.emit(0x88, 0x47, SCRIPT_SLOT_IS_TIMER)  # mov [edi+0x4c], al
    a.emit(0x8A, 0x46, STD_MAP_NODE_VALUE + SCRIPT_COUNTER_IS_SECONDS)  # mov al, [esi+0x1d]
    a.emit(0x88, 0x47, SCRIPT_SLOT_IS_SECONDS)  # mov [edi+0x4d], al
    a.jmp("script_record_stored")

    # A flag's value is a **byte**; the three bytes above it in the node are someone else's.
    a.label("script_record_flag")
    a.emit(0x0F, 0xB6, 0x46, STD_MAP_NODE_VALUE)  # movzx eax, byte [esi+0x18]
    a.emit(0x89, 0x47, SCRIPT_SLOT_VALUE)  # mov [edi+0x48], eax
    a.emit(0xC6, 0x47, SCRIPT_SLOT_IS_TIMER, 0x00)  # mov byte [edi+0x4c], 0
    a.emit(0xC6, 0x47, SCRIPT_SLOT_IS_SECONDS, 0x00)  # mov byte [edi+0x4d], 0

    a.label("script_record_stored")
    a.emit(0xFF, 0x05, struct.pack("<I", script_count_va))  # inc dword [script_count]
    a.label("script_record_done")
    a.emit(0x5F)  # pop edi
    a.emit(0xC3)  # ret

    # One map, front to back. `edi` the header, `bl` the kind. Iteration walks `[header+8]` to the
    # leftmost node and steps with the engine's own iterator increment until it comes back round.
    a.label("script_walk")
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "script_walk_done")
    a.emit(0x8B, 0x77, 0x08)  # mov esi, [edi+8]
    a.label("script_walk_loop")
    a.emit(0x3B, 0xF7)  # cmp esi, edi
    a.jcc(JE, "script_walk_done")
    a.call("script_record")
    a.emit(0x56)  # push esi
    a.call_absolute(STD_MAP_ITERATOR_INCREMENT)
    a.emit(0x59)  # pop ecx                ; cdecl
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.jmp("script_walk_loop")
    a.label("script_walk_done")
    a.emit(0xC3)  # ret

    a.label("script_snapshot")
    a.emit(0xC7, 0x05, struct.pack("<I", script_count_va), struct.pack("<I", 0))  # count = 0
    a.emit(0xA1, struct.pack("<I", THE_SCRIPT_ENGINE))  # mov eax, [TheScriptEngine]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "script_snapshot_done")
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x33, 0xDB)  # xor ebx, ebx          ; counters and timers
    a.emit(0x8B, 0xB8, struct.pack("<I", SCRIPT_ENGINE_COUNTER_MAP))  # mov edi, [eax+0x191a0]
    a.call("script_walk")
    a.emit(0xA1, struct.pack("<I", THE_SCRIPT_ENGINE))  # mov eax, [TheScriptEngine]
    a.emit(0xBB, struct.pack("<I", 1))  # mov ebx, 1            ; flags
    a.emit(0x8B, 0xB8, struct.pack("<I", SCRIPT_ENGINE_FLAG_MAP))  # mov edi, [eax+0x191ac]
    a.call("script_walk")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.label("script_snapshot_done")
    a.emit(0xC3)  # ret

    # Put them back. Both lookups are `__thiscall` on `TheScriptEngine`, take an `AsciiString`
    # **by value** and destroy it themselves, and return the record - so the string is built into
    # the stack slot that is already the argument and the callee's `ret 4` disposes of both.
    a.label("script_restore")
    a.emit(0x83, 0x3D, struct.pack("<I", script_count_va), 0x00)  # cmp dword [script_count], 0
    a.jcc(JE, "script_restore_done")
    a.emit(0x83, 0x3D, struct.pack("<I", THE_SCRIPT_ENGINE), 0x00)  # cmp [TheScriptEngine], 0
    a.jcc(JE, "script_restore_clear")
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x33, 0xF6)  # xor esi, esi          ; index

    a.label("script_restore_loop")
    a.emit(0x8B, 0xFE)  # mov edi, esi
    a.emit(0x69, 0xFF, struct.pack("<I", SCRIPT_SLOT_SIZE))  # imul edi, edi, SCRIPT_SLOT_SIZE
    a.emit(0x81, 0xC7, struct.pack("<I", script_records_va))  # add edi, script_records
    a.emit(0x83, 0xEC, 0x04)  # sub esp, 4            ; the AsciiString, by value
    a.emit(0x8B, 0xCC)  # mov ecx, esp
    a.emit(0x57)  # push edi              ; the name buffer
    a.call_absolute(ASCII_STRING_CTOR)  # ret 4
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_SCRIPT_ENGINE))  # mov ecx, [TheScriptEngine]
    a.emit(0x80, 0x7F, SCRIPT_SLOT_KIND, 0x00)  # cmp byte [edi+0x4e], 0
    a.jcc(JNE, "script_restore_flag")
    a.call_absolute(SCRIPT_ENGINE_FIND_OR_CREATE_COUNTER)  # ret 4 -> the record
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "script_restore_next")
    a.emit(0x8B, 0x57, SCRIPT_SLOT_VALUE)  # mov edx, [edi+0x48]
    a.emit(0x89, 0x50, SCRIPT_COUNTER_VALUE)  # mov [eax], edx
    a.emit(0x8A, 0x57, SCRIPT_SLOT_IS_TIMER)  # mov dl, [edi+0x4c]
    a.emit(0x88, 0x50, SCRIPT_COUNTER_IS_TIMER)  # mov [eax+4], dl
    a.emit(0x8A, 0x57, SCRIPT_SLOT_IS_SECONDS)  # mov dl, [edi+0x4d]
    a.emit(0x88, 0x50, SCRIPT_COUNTER_IS_SECONDS)  # mov [eax+5], dl
    a.jmp("script_restore_next")

    a.label("script_restore_flag")
    a.call_absolute(SCRIPT_ENGINE_FIND_OR_CREATE_FLAG)  # ret 4 -> the record
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "script_restore_next")
    a.emit(0x8A, 0x57, SCRIPT_SLOT_VALUE)  # mov dl, [edi+0x48]
    a.emit(0x88, 0x10)  # mov [eax], dl

    a.label("script_restore_next")
    a.emit(0x46)  # inc esi
    a.emit(0x3B, 0x35, struct.pack("<I", script_count_va))  # cmp esi, [script_count]
    a.jcc(JL, "script_restore_loop")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi

    a.label("script_restore_clear")
    a.emit(0xC7, 0x05, struct.pack("<I", script_count_va), struct.pack("<I", 0))  # count = 0
    a.label("script_restore_done")
    a.emit(0xC3)  # ret

    a.label("action")
    a.emit(0x83, 0x7E, SCRIPT_ACTION_PARAM_COUNT, 0x02)  # cmp dword [esi+8], 2
    a.jcc_short(JL, "action_done")
    a.emit(0x8B, 0x46, SCRIPT_ACTION_PARAM_ARRAY + 4)  # mov eax, [esi+0x10]  ; Parameter *1
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "action_done")
    a.emit(0x8B, 0x40, SCRIPT_PARAMETER_STRING)  # mov eax, [eax+0x10]  ; the AsciiString block
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "action_done")

    # Copy the name rather than remembering a pointer into the map's own script data. The pointer
    # would in fact still be live when the hook runs - the swap happens on the next tick, before
    # anything frees the scripts - but a copy costs nine instructions and removes the question.
    a.emit(0x56)  # push esi
    a.emit(0x8D, 0x70, 0x08)  # lea esi, [eax+8]     ; AsciiString characters
    a.emit(0xBA, struct.pack("<I", name_va))  # mov edx, name
    a.emit(0x33, 0xC9)  # xor ecx, ecx
    a.label("copy")
    a.emit(0x8A, 0x04, 0x0E)  # mov al, [esi+ecx]
    a.emit(0x88, 0x04, 0x0A)  # mov [edx+ecx], al
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "copied")
    a.emit(0x41)  # inc ecx
    a.emit(0x83, 0xF9, NAME_MAX - 1)  # cmp ecx, NAME_MAX-1
    a.jcc_short(JL, "copy")
    a.emit(0xC6, 0x04, 0x0A, 0x00)  # mov byte [edx+ecx], 0   ; truncated
    a.label("copied")
    a.emit(0x5E)  # pop esi

    # An empty name would format to `maps\\.map` and fail the load with the session already torn
    # down, so refuse it here where refusing costs nothing.
    a.emit(0x80, 0x3D, struct.pack("<I", name_va), 0x00)  # cmp byte [name], 0
    a.jcc_short(JE, "action_done")
    a.emit(0xC7, 0x05, struct.pack("<I", pending_va), struct.pack("<I", 1))  # pending = 1
    a.label("action_done")
    a.jmp_absolute(SCRIPT_ACTION_EPILOGUE)

    # The logic-update hook, which runs the transition as **two** posted messages with a trip
    # through the shell map between them.
    #
    # One message is not enough, and this is the second thing the first two builds got wrong. The
    # engine has no game-to-game transition: `MSG_NEW_GAME` mid-match, carrying a playing mode,
    # builds the destination's world while the previous session is still standing, and world
    # construction faults in `Object::setTeam` on an object whose team pointer is into freed
    # memory. What the engine *does* support is leaving a match for the shell map, and starting a
    # match from the shell. Chaining those two is the only sequence it is known to survive, and it
    # is what a player does by hand: quit to the menu, then pick the next map.
    #
    # `ecx` carries `this` at a thiscall entry and the prologue has not run yet, so the whole
    # block is bracketed by pushad/popad rather than reasoning about which registers survive.
    a.label("hook")
    a.emit(0x83, 0x3D, struct.pack("<I", pending_va), 0x00)  # cmp dword [pending], 0
    a.jcc(JE, "passthrough")
    a.emit(0x60)  # pushad
    a.emit(0x83, 0x3D, struct.pack("<I", pending_va), 0x03)  # cmp dword [pending], 3
    a.jcc(JE, "arriving")
    a.emit(0x83, 0x3D, struct.pack("<I", pending_va), 0x02)  # cmp dword [pending], 2
    a.jcc(JE, "leaving")

    # Step one: remember the kind of game this is and ask for the shell map. Nothing about the
    # destination is touched yet - in particular the active map name is left alone, because the
    # shell load reads it.
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x8B, 0x91, struct.pack("<I", _GAME_MODE_OFFSET))  # mov edx, [ecx+0x110]
    a.emit(0x89, 0x15, struct.pack("<I", saved_mode_va))  # mov [saved_mode], edx
    a.emit(0xC7, 0x05, struct.pack("<I", pending_va), struct.pack("<I", 2))  # pending = 2

    # End the match, and then **stop**. `GameLogic::clearGameData(Bool)` is what the pause menu's
    # Quit calls (`0x00921A67`, with 1); it is `__thiscall`, `ret 4`, and its argument only gates a
    # network branch a single-player session skips anyway.
    #
    # It hands off to the engine's own end-of-match flow, which shows the score screen and then
    # takes the player to the shell map on its own schedule. An earlier build also posted
    # `MSG_NEW_GAME(4)` here and named the shell map by hand: that put a second, competing shell
    # request into the middle of a flow already heading there, and the score screen was seen
    # flashing before the crash. The engine sequences this perfectly well unaided; step two just
    # has to wait for it to arrive.
    # Snapshot the army **before** the teardown destroys it. This is the only moment the objects
    # still exist and the only reason step one has to be split from step two at all.
    a.call("snapshot")
    a.call("script_snapshot")
    a.call("player_snapshot")
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(CLEAR_GAME_DATA)
    a.jmp("abort")

    # Step two: wait for the shell to actually be up. The message posted above is handled later in
    # the frame, and the mode only reads 4 once it has been. Until then this is a no-op that costs
    # one compare per frame.
    a.label("leaving")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x8B, 0x81, struct.pack("<I", _GAME_MODE_OFFSET))  # mov eax, [ecx+0x110]
    a.emit(0x83, 0xF8, _MODE_SHELL_MAP)  # cmp eax, 4
    a.jcc(JE, "at_shell")
    a.emit(0x83, 0xF8, _MODE_NO_SESSION)  # cmp eax, 9
    a.jcc(JNE, "abort")

    # Mode 9 is the skirmish lobby, where the end-of-match flow leaves the player. A
    # `MSG_NEW_GAME` posted from here is not acted on - measured: the message went out, the mode
    # stayed 9, the staged map was never promoted and the active map never changed. So ask for the
    # shell map first and come back. Mode 4 is the state the engine's own shell-to-game start
    # works from, and it is the only one this has ever been observed to work from.
    a.emit(0xA1, struct.pack("<I", GLOBAL_DATA))  # mov eax, [TheWritableGlobalData]
    a.emit(0x8D, 0x90, struct.pack("<I", GLOBAL_DATA_SHELL_MAP))  # lea edx, [eax+0xaec]
    a.emit(0x52)  # push edx
    a.emit(0x05, struct.pack("<I", GLOBAL_DATA_STAGED_MAP))  # add eax, 0xac0
    a.emit(0x8B, 0xC8)  # mov ecx, eax          ; the staged name
    a.call_absolute(ASCII_STRING_COPY)
    a.emit(0x6A, _MODE_SHELL_MAP)  # push 4
    a.jmp("post")

    # At the shell map: name the destination and start it in the mode the session had. The
    # staged slot is what the engine's own shell return writes, and `startNewGame` promotes it
    # over the active name and clears it.
    a.label("at_shell")
    a.emit(0xC7, 0x05, struct.pack("<I", pending_va), struct.pack("<I", 3))  # pending = 3
    a.emit(0x68, struct.pack("<I", name_va))  # push name
    a.emit(0x68, struct.pack("<I", name_va))  # push name
    a.emit(0x68, struct.pack("<I", MAP_PATH_FORMAT))  # push "maps\%s\%s.map"
    a.emit(0xA1, struct.pack("<I", GLOBAL_DATA))  # mov eax, [TheWritableGlobalData]
    a.emit(0x05, struct.pack("<I", GLOBAL_DATA_STAGED_MAP))  # add eax, 0xac0
    a.emit(0x50)  # push eax
    a.call_absolute(ASCII_STRING_FORMAT)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10   ; cdecl

    # A destination that is not there leaves the player at the menu rather than loading nothing.
    a.emit(0xA1, struct.pack("<I", GLOBAL_DATA))  # mov eax, [TheWritableGlobalData]
    a.emit(0x8B, 0x80, struct.pack("<I", GLOBAL_DATA_STAGED_MAP))  # mov eax, [eax+0xac0]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "abort")
    a.emit(0x83, 0xC0, 0x08)  # add eax, 8
    a.emit(0x50)  # push eax
    a.call_absolute(FILE_SYSTEM_DOES_FILE_EXIST)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "abort")

    # Give the session its `GameInfo` back. `loadMap` nulls `TheGameInfo` for game mode 4 alone
    # (`0x0063152D`: `cmp [esi+0x110], 4` / `mov [TheGameInfo], 0`), so the shell hop above is
    # what took it away. The destination then loads with no `GameInfo`, and `LoadScreen::init`
    # (`0x0081CB08`) returns on the spot when handed a null one, leaving its progress window
    # (`+0x88`) at zero for the very next progress tick to dereference.
    #
    # The skirmish info itself survives: only the shell menu destroys it (`0x0082BE30`, which
    # nulls both globals together), so a non-null `THE_SKIRMISH_GAME_INFO` is a live one. This
    # is the same assignment the shell's own skirmish start makes at `0x0082BE98`.
    a.emit(0xA1, struct.pack("<I", THE_SKIRMISH_GAME_INFO))  # mov eax, [TheSkirmishGameInfo]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "no_game_info")
    a.emit(0xA3, struct.pack("<I", THE_GAME_INFO))  # mov [TheGameInfo], eax
    a.label("no_game_info")

    # Tear the shell map down before asking for the destination. Without this the destination
    # loads correctly on the logic side - measured: `TheTerrainLogic` and the world heightmap both
    # hold the destination's 520x370, and the object list matches its map file template for
    # template - while the **render** scene keeps the shell map. The player sees the shell map's
    # scenery still standing, and the destination's own terrain nowhere: units and buildings sit
    # correctly placed on black.
    #
    # The one hop in this whole sequence that rendered correctly is the one that had a teardown in
    # front of it: step one ends the match, and the shell map that follows comes up whole. Nothing
    # tears down between the shell map and the destination, so this does, with the same call and
    # the argument the engine's own non-match teardown uses. Both messages land in one stream in
    # order - `MSG_CLEAR_GAME_DATA` from the call, then `MSG_NEW_GAME` from the post below.
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(CLEAR_GAME_DATA)

    a.emit(0xFF, 0x35, struct.pack("<I", saved_mode_va))  # push dword [saved_mode]
    a.jmp("post")

    # Step three: the destination is running once the mode matches the one the session had. Put
    # the army back, then disarm.
    a.label("arriving")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x8B, 0x81, struct.pack("<I", _GAME_MODE_OFFSET))  # mov eax, [ecx+0x110]
    a.emit(0x3B, 0x05, struct.pack("<I", saved_mode_va))  # cmp eax, [saved_mode]
    a.jcc(JNE, "abort")
    a.emit(0xC7, 0x05, struct.pack("<I", pending_va), struct.pack("<I", 0))  # pending = 0
    a.call("player_restore")
    a.call("restore")
    a.call("script_restore")
    a.jmp("abort")

    # Shared tail: post MSG_NEW_GAME carrying the mode already on the stack, exactly as the shell
    # return does at 0x0075DEE2. The mode survives the vtable call on the stack rather than in a
    # register the callee may use.
    a.label("post")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_MESSAGE_STREAM))  # mov ecx, [TheMessageStream]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x6A, MSG_NEW_GAME)  # push 0x1e
    a.emit(0xFF, 0x50, APPEND_MESSAGE_VTABLE_SLOT)  # call [eax+0x48] -> GameMessage *
    a.emit(0x5A)  # pop edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x52)  # push edx
    a.call_absolute(GAME_MESSAGE_APPEND_INTEGER)

    a.label("abort")
    a.emit(0x61)  # popad
    a.label("passthrough")
    a.emit(HOOK_ORIGINAL)  # the stolen prologue
    a.jmp_absolute(HOOK_RETURN_VA)
    return a


def build_section(base_va: int) -> bytes:
    """The whole section: the pending flag and name buffer, then both entry points."""
    return b"\x00" * CODE_OFF + _emit(base_va).finish()


def entry_points(base_va: int) -> tuple[int, int]:
    """`(action, hook)` virtual addresses, read off the layout that was actually emitted."""
    a = _emit(base_va)
    a.finish()
    return a.label_va("action"), a.label_va("hook")


class MapTransitionPatch(Patch):
    name = "map-transition"
    author = "officialNecro"
    experimental = True
    description = (
        "A script action that loads another map without leaving the session, so a scenario can "
        "span several map files. No INI change: in WorldBuilder's action browser take "
        "Player_ -> 'Assimilates player with an army by name.', which does nothing in the "
        "unpatched engine, and type the destination map's folder name into the army-name slot - "
        "the line reads 'Set <player> to be assimilated by army <name>.' and only the name is "
        "read. Single player only. The local player's army carries across with veterancy, "
        "upgrades and health - what counts as the army is KindOf ARMY_SUMMARY, so units and "
        "hordes carry and structures do not - and so do script counters, timers and flags by "
        "name and scope, and the player's resources, command-point ceiling, spellbook points, "
        "purchased sciences and completed upgrades. Special-power cooldowns are out of scope, so "
        "powers arrive ready; the hero revival ledger does not carry yet"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        slot_off = va_to_offset(data, TABLE_SLOT_VA)
        if slot_off is None:
            raise ValueError(f"{TABLE_SLOT_VA:#010x} is not mapped - not the expected build")
        # Prove the engine dispatches to the function being hooked, that the action id is still a
        # stub, and that the addresses the cave returns into hold what it was written against.
        self._check_dispatch(data)
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        action_va, hook_va = entry_points(section_va)

        apply_byte_patch(
            data,
            slot_off,
            TABLE_SLOT_STOCK,
            struct.pack("<I", action_va),
            f"script action {ACTION_ID} stub -> map-transition cave",
        )
        jump = b"\xe9" + struct.pack("<i", hook_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "GameLogic::update entry -> map-transition hook",
        )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless the GameLogic vtable still names the function being hooked.

        A hook on a function nothing dispatches to installs perfectly and never runs, which looks
        exactly like a working patch until a transition is asked for and nothing happens.
        """
        slot_off = va_to_offset(data, GAME_LOGIC_UPDATE_VTABLE_SLOT)
        if slot_off is None:
            raise ValueError("the GameLogic vtable is not mapped - not the expected build")
        target = struct.unpack_from("<I", data, slot_off)[0]
        if target != HOOK_VA:
            raise ValueError(
                f"vtable slot {GAME_LOGIC_UPDATE_VTABLE_SLOT:#010x} dispatches to "
                f"{target:#010x}, not {HOOK_VA:#010x} - hooking it would never fire"
            )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            if bytes(data[off : off + len(expected)]) != expected:
                raise ValueError(
                    f"{va:#010x} does not hold {expected.hex()} - not the expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, _, _ = located
        action_va, hook_va = entry_points(section_va)

        slot_off = va_to_offset(data, TABLE_SLOT_VA)
        if slot_off is None:
            return [f"{TABLE_SLOT_VA:#010x} is not mapped by any section"]
        slot = struct.unpack_from("<I", data, slot_off)[0]
        if slot != action_va:
            problems.append(
                f"script action {ACTION_ID} dispatches to {slot:#010x}, expected {action_va:#010x}"
            )

        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            problems.append(f"{HOOK_VA:#010x} is not a jmp - the hook is not installed")
        else:
            target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != hook_va:
                problems.append(f"hook jumps to {target:#010x}, expected {hook_va:#010x}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> MapTransitionPatch | None:
        if find_section(data, SECTION_NAME) is None:
            return None
        patch = cls()
        return patch if not patch.verify(data) else None
