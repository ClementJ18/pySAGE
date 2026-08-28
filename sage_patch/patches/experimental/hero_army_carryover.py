"""`Persistent = Yes` on an `ArmyEntry`: that hero stays in his army when he dies in a War of the
Ring battle, at the level and with the upgrades he died with, the way BFME1's heroes do.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/living-campaign/hero-permadeath.md``.

**The one-rule difference, measured on both games.** Saves either side of a hero's death in BFME1
and in ROTWK say that *both* engines harvest a battle back into the living-world army: the roster an
army comes out with is what survived, carrying the upgrades earned. They differ in what becomes of a
hero who did not.

* BFME1 keeps him in the army. `Evil_SarumanPlayerArmy` went into evil mission 1 holding one
  `ArmyEntry` and came out holding six - five surviving Isengard hordes and `IsengardSaruman`, who
  had died, now carrying an `Upgrade_SarumanFireBall` the earlier save does not show.
* ROTWK moves him out of it. `WitchKingKampaArmy` went in with four heroes and came out with three;
  the fourth turned up on the owning `LivingWorldPlayer` and in the fortress's hero-spawn queue.

**Where a dead hero's state actually lives.** Not on his object: measured on BFME1's in-battle
saves, `IsengardSaruman` is a live object before he dies and **absent afterwards**, so by the time a
battle ends there is nothing left to harvest. What survives is his entry in the player's hero
ledger (`Player+0x758`) - the same ledger the ControlBar offers as revivable during the mission -
and the engine already copies that ledger's `KindOf HERO` entries onto the living-world player when
the battle ends (`0x0078100E`), which is why a dead hero reaches the world map with his upgrades at
all. This patch reads the same ledger and puts him back in his **army** as well, which is the half
ROTWK does not do.

**The keyword.** A new `ArmyEntry` field, so a scenario says which heroes this applies to rather
than it applying to every hero in the game::

    LivingWorldPlayerArmy
        Name = WitchKingKampaArmy
        ArmyEntry
            ThingTemplate = AngmarDurmarth
            Quantity      = 1
            Persistent    = Yes
        End
    End

Absent or `No` is the stock behaviour exactly. `Persistent = Yes` is remembered as the
*`ThingTemplate` name*, so it applies to that hero in whichever army carries him.

**What the hero comes back as.** The record is built from his ledger entry by the engine's own
`0x00780FEF` - the exact mirror of the `Object -> record` builder the harvest uses for survivors,
down to the same `record+0xD0` tail - so his name, `Quantity`, the `0x90`-byte state block and his
upgrade list are what they were **at the moment he died**, including anything earned in that
battle. That is BFME1's behaviour rather than an approximation of it.

**Three hooks and one repointed table:**

* `0x0080EF87` - the immediate naming the `ArmyEntry` sub-table, repointed at a copy in the cave
  with `Persistent` appended beside `Default`;
* `0x00811D41` - the `ArmyEntry` field-parse call, wrapped so a record that comes out with the flag
  set adds its `ThingTemplate` name to the cave's persistent set. The flag lives in a record byte
  the constructor does not initialise, the copy-constructor does not carry and nothing else reads,
  so it is zeroed on the way in and consumed before the record leaves the parser - it never has to
  survive anything;
* `0x0062565A` - the battle-start setup, wrapped to record `(army id, hero name)` for every
  persistent hero in every living-world army. It runs before any army deploys, which is the only
  moment a roster still says which army a hero belongs to;
* `0x0062667C` - the harvest, wrapped so that afterwards each living-world player's hero ledger is
  walked and every persistent hero missing from his army is put back into it.

Nothing is held by reference across a battle - the tables carry names and ids only - so an
abandoned battle leaves nothing to clean up.

**Limits.** :data:`PERSISTENT_CAPACITY` distinct hero templates may be marked and
:data:`HELD_CAPACITY` hero-in-army pairs carried across one battle; past either, the extra heroes
keep the stock behaviour. A name of :data:`NAME_CAPACITY` characters or more is dropped rather than
truncated, because a truncated name matches the wrong hero. If one hero template sits in two
armies, the first captured wins.

**Scope.** Living-world battles only: the battle-start hook's caller already gates on
`TheLivingWorldManager`, so a skirmish or a linear mission reaches neither battle hook. The parse
hook runs wherever `ArmyEntry` is parsed, which is INI load, and does nothing without the keyword.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. It shares no byte with `campaign-army-verbs`, which edits the Act
verb table and the act runner.

**He is also still offered at his faction's fortress, and that is intended.** The engine's own copy
of the hero ledger onto the `LivingWorldPlayer` (`0x0078100E`) is left alone, so a hero who died is
both back with his army and available to recruit again - confirmed in play. This patch adds BFME1's
army rule; it does not take ROTWK's own away, and `Persistent` is how a scenario chooses which
heroes get the army half at all. :meth:`~HeroArmyCarryoverPatch.verify` is deliberately silent about
`0x0078100E` for the same reason - nothing here touches it.

**Runtime-verified 2026-08-28.** A hero marked `Persistent` died in an Angmar War of the Ring
mission and came back in `WitchKingKampaArmy` afterwards carrying `Upgrade_Level_2` and three more
upgrades he did not have going in. Still `experimental`: one mission is one mission, and nothing
here has been through a whole campaign, a save/reload or a second battle.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    ARMY_ENTRY_DEFAULT_TABLE,
    ARMY_ENTRY_DEFAULT_TABLE_BYTES,
    ARMY_ENTRY_DEFAULT_TABLE_PUSH,
    ARMY_ENTRY_DEFAULT_TABLE_PUSH_BYTES,
    ARMY_ENTRY_PARSE_FIELDS,
    ARMY_ENTRY_PARSE_FIELDS_CALL,
    ARMY_ENTRY_PARSE_FIELDS_CALL_BYTES,
    ARMY_ENTRY_RECORD_CTOR,
    ARMY_ENTRY_REFCOUNT_COUNT,
    ARMY_ENTRY_REFCOUNT_OFFSET,
    ARMY_ENTRY_SCRATCH_OFFSET,
    ARMY_ENTRY_TEMPLATE_OFFSET,
    ASCII_STRING_CHARS_OFFSET,
    GAME_DATA_BOOL_PARSER,
    HERO_LEDGER_ENTRIES_BEGIN,
    HERO_LEDGER_ENTRIES_END,
    HERO_LEDGER_ENTRY_STRIDE,
    HERO_LEDGER_FIND_TEMPLATE,
    HERO_LEDGER_NAME_OFFSET,
    HERO_LEDGER_TO_RECORD,
    KINDOF_ARMY_SUMMARY_BIT,
    KINDOF_ARMY_SUMMARY_BYTE,
    KINDOF_HERO_BIT,
    KINDOF_HERO_BYTE,
    LIVING_WORLD_ARMY_ADD_RECORD,
    LIVING_WORLD_ARMY_GET_RECORD,
    LIVING_WORLD_ARMY_RECORDS_BEGIN,
    LIVING_WORLD_ARMY_RECORDS_END,
    LIVING_WORLD_ARMY_ROSTER_ID,
    LIVING_WORLD_ARMY_ROSTER_OFFSET,
    LIVING_WORLD_BATTLE_HARVEST,
    LIVING_WORLD_BATTLE_HARVEST_CALL,
    LIVING_WORLD_BATTLE_HARVEST_CALL_BYTES,
    LIVING_WORLD_BATTLE_SETUP,
    LIVING_WORLD_BATTLE_SETUP_CALL,
    LIVING_WORLD_BATTLE_SETUP_CALL_BYTES,
    LIVING_WORLD_FIND_ARMY_BY_ID,
    LIVING_WORLD_PLAYER_ARMIES_BEGIN,
    LIVING_WORLD_PLAYER_ARMIES_END,
    LIVING_WORLD_PLAYERS_BEGIN,
    LIVING_WORLD_PLAYERS_END,
    OPERATOR_NEW,
    PLAYER_HERO_LEDGER_OFFSET,
    PLAYER_LIST_COUNT_OFFSET,
    PLAYER_LIST_GET_NTH,
    PLAYER_LIVING_WORLD_ID_OFFSET,
    REF_COUNT_RELEASE,
    THE_LIVING_WORLD_LOGIC,
    THE_PLAYER_LIST,
)
from ...asm import JAE, JB, JE, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "HELD_CAPACITY",
    "KEYWORD",
    "NAME_CAPACITY",
    "PERSISTENT_CAPACITY",
    "RECORD_SIZE",
    "SECTION_NAME",
    "HeroArmyCarryoverPatch",
    "build_cave",
    "cave_layout",
]

SECTION_NAME = ".herocy"  # 7 chars: the PE name field is 8 bytes and truncates silently

# CODE | INITIALIZED_DATA | EXECUTE | READ | WRITE - the cave is code plus the two tables the parse
# and battle-start hooks fill in, so it is written as well as run.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The keyword this patch adds to `ArmyEntry`.
KEYWORD = "Persistent"

#: How many characters of a hero's `ThingTemplate` name a table entry keeps, terminator included.
NAME_CAPACITY = 64

#: How many distinct hero templates may be marked `Persistent = Yes` across the whole INI.
PERSISTENT_CAPACITY = 64

#: How many (army, hero) pairs may be carried across one battle.
HELD_CAPACITY = 64

#: The `ArmyEntry` roster record the engine allocates.
RECORD_SIZE = 0xD8

# One held pair: the id of the army the hero was in, then his template name.
_HELD_ARMY_ID = 0x00
_HELD_NAME = 0x04
_HELD_SIZE = _HELD_NAME + NAME_CAPACITY

_ROW_SIZE = 0x10


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> bytes:
    return struct.pack("<b", value)


def cave_layout() -> dict[str, int]:
    """Offsets from the cave's base. Both tables come first, at offsets that depend on nothing, so
    the code that follows can address them as `base + constant`."""
    persist_names = 0x04
    held_count = persist_names + PERSISTENT_CAPACITY * NAME_CAPACITY
    held = held_count + 0x04
    field_table = held + HELD_CAPACITY * _HELD_SIZE
    keyword = field_table + 3 * _ROW_SIZE  # `Default`, `Persistent`, terminator
    return {
        "persist_count": 0x00,
        "persist_names": persist_names,
        "held_count": held_count,
        "held": held,
        "field_table": field_table,
        "keyword": keyword,
        "code": (keyword + len(KEYWORD) + 1 + 15) & ~15,
    }


def _emit_code(base_va: int, data_va: int, layout: dict[str, int]) -> Asm:  # noqa: PLR0915
    """The cave's routines, laid out but not resolved.

    Every loop index lives in a frame slot rather than a register: the walks nest three deep and a
    register doing double duty across a call is the kind of mistake no test would describe."""
    a = Asm(base_va)
    persist_count = data_va + layout["persist_count"]
    persist_names = data_va + layout["persist_names"]
    held_count = data_va + layout["held_count"]
    held = data_va + layout["held"]

    # `str_copy`: eax = an AsciiString handle, edi = a NAME_CAPACITY-byte field. al = 1 when the
    # name fitted and is not empty.
    a.label("str_copy")
    a.emit(0x53, 0x56)  # push ebx, esi
    a.emit(b"\xc6\x07\x00")  # mov byte [edi], 0
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "sc_no")
    a.emit(b"\x8d\x70", bytes([ASCII_STRING_CHARS_OFFSET]))  # lea esi, [eax+8]
    a.emit(b"\x33\xc9")  # xor ecx, ecx
    a.label("sc_loop")
    a.emit(b"\x8a\x1c\x0e")  # mov bl, [esi+ecx]
    a.emit(b"\x88\x1c\x0f")  # mov [edi+ecx], bl
    a.emit(b"\x84\xdb")  # test bl, bl
    a.jcc(JE, "sc_end")
    a.emit(0x41)  # inc ecx
    a.emit(b"\x83\xf9", _i8(NAME_CAPACITY))  # cmp ecx, NAME_CAPACITY
    a.jcc(JB, "sc_loop")
    a.label("sc_no")  # too long, or no handle
    a.emit(b"\xc6\x07\x00")  # mov byte [edi], 0
    a.emit(b"\x32\xc0")  # xor al, al
    a.emit(0x5E, 0x5B)  # pop esi, ebx
    a.emit(0xC3)  # ret
    a.label("sc_end")
    a.emit(b"\x85\xc9")  # test ecx, ecx           ; an empty name marks nothing
    a.jcc(JE, "sc_no")
    a.emit(b"\xb0\x01")  # mov al, 1
    a.emit(0x5E, 0x5B)  # pop esi, ebx
    a.emit(0xC3)  # ret

    # `str_eq`: edi and esi are NUL-terminated; al = 1 when equal. Both sides are always the
    # engine's own template names, so a byte compare is the right comparison.
    a.label("str_eq")
    a.emit(0x56, 0x57)  # push esi, edi
    a.label("se_loop")
    a.emit(b"\x8a\x07")  # mov al, [edi]
    a.emit(b"\x8a\x16")  # mov dl, [esi]
    a.emit(b"\x3a\xc2")  # cmp al, dl
    a.jcc(JNE, "se_no")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "se_yes")
    a.emit(0x47, 0x46)  # inc edi, inc esi
    a.jmp("se_loop")
    a.label("se_yes")
    a.emit(b"\xb0\x01")  # mov al, 1
    a.emit(0x5F, 0x5E)  # pop edi, esi
    a.emit(0xC3)  # ret
    a.label("se_no")
    a.emit(b"\x32\xc0")  # xor al, al
    a.emit(0x5F, 0x5E)  # pop edi, esi
    a.emit(0xC3)  # ret

    # `is_persistent`: esi = characters, al = 1 when the INI marked that template.
    a.label("is_persistent")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x08")  # sub esp, 8
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x89\x75\xfc")  # mov [ebp-4], esi        ; the name under test
    a.emit(b"\x83\x65\xf8\x00")  # and dword [ebp-8], 0    ; the index
    a.label("ip_loop")
    a.emit(b"\x8b\x45\xf8")  # mov eax, [ebp-8]
    a.emit(b"\x3b\x05", _u32(persist_count))  # cmp eax, [persist_count]
    a.jcc(JAE, "ip_no")
    a.emit(b"\x6b\xc0", _i8(NAME_CAPACITY))  # imul eax, eax, NAME_CAPACITY
    a.emit(0x05, _u32(persist_names))  # add eax, persist_names
    a.emit(b"\x8b\xf8")  # mov edi, eax
    a.emit(b"\x8b\x75\xfc")  # mov esi, [ebp-4]
    a.call("str_eq")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "ip_yes")
    a.emit(b"\xff\x45\xf8")  # inc dword [ebp-8]
    a.jmp("ip_loop")
    a.label("ip_no")
    a.emit(b"\x32\xc0")  # xor al, al
    a.jmp("ip_done")
    a.label("ip_yes")
    a.emit(b"\xb0\x01")  # mov al, 1
    a.label("ip_done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `roster_count`: ecx = a roster container, eax = how many records it holds.
    a.label("roster_count")
    a.emit(b"\x8b\x41", _i8(LIVING_WORLD_ARMY_RECORDS_END))  # mov eax, [ecx+0x44]
    a.emit(b"\x2b\x41", _i8(LIVING_WORLD_ARMY_RECORDS_BEGIN))  # sub eax, [ecx+0x40]
    a.emit(b"\xc1\xf8\x03")  # sar eax, 3
    a.emit(0xC3)  # ret

    # `roster_has`: ecx = container, esi = characters. al = 1 when a record of that name is in it.
    a.label("roster_has")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x0c")  # sub esp, 0xc
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x89\x4d\xfc")  # mov [ebp-4], ecx        ; the container
    a.emit(b"\x89\x75\xf8")  # mov [ebp-8], esi        ; the name
    a.emit(b"\x83\x65\xf4\x00")  # and dword [ebp-0xc], 0  ; the index
    a.label("rh_loop")
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.call("roster_count")
    a.emit(b"\x3b\x45\xf4")  # cmp eax, [ebp-0xc]
    a.jcc(JLE, "rh_no")  # jle
    a.emit(b"\xff\x75\xf4")  # push dword [ebp-0xc]
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.call_absolute(LIVING_WORLD_ARMY_GET_RECORD)  # ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rh_next")
    a.emit(b"\x8b\x40", _i8(ARMY_ENTRY_TEMPLATE_OFFSET))  # mov eax, [eax+4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rh_next")
    a.emit(b"\x83\xc0", bytes([ASCII_STRING_CHARS_OFFSET]))  # add eax, 8
    a.emit(b"\x8b\xf8")  # mov edi, eax
    a.emit(b"\x8b\x75\xf8")  # mov esi, [ebp-8]
    a.call("str_eq")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "rh_yes")
    a.label("rh_next")
    a.emit(b"\xff\x45\xf4")  # inc dword [ebp-0xc]
    a.jmp("rh_loop")
    a.label("rh_no")
    a.emit(b"\x32\xc0")  # xor al, al
    a.jmp("rh_done")
    a.label("rh_yes")
    a.emit(b"\xb0\x01")  # mov al, 1
    a.label("rh_done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `entry_hook`: the `ArmyEntry` field parse. The flag byte is zeroed on the way in - the record
    # constructor does not initialise it - and consumed on the way out, before the record leaves
    # the parser, so nothing downstream ever has to carry it.
    a.label("entry_hook")  # ecx = the record, [esp+4] = the INI reader
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x8b\xf1")  # mov esi, ecx            ; the record
    a.emit(b"\xc6\x86", _u32(ARMY_ENTRY_SCRATCH_OFFSET), 0x00)  # mov byte [esi+0xd7], 0
    a.emit(b"\xff\x74\x24\x10")  # push dword [esp+0x10]   ; the INI reader
    a.emit(b"\x8b\xce")  # mov ecx, esi
    a.call_absolute(ARMY_ENTRY_PARSE_FIELDS)  # ret 4
    a.emit(b"\x80\xbe", _u32(ARMY_ENTRY_SCRATCH_OFFSET), 0x00)  # cmp byte [esi+0xd7], 0
    a.jcc(JE, "eh_done")
    a.emit(b"\xa1", _u32(persist_count))  # mov eax, [persist_count]
    a.emit(b"\x83\xf8", _i8(PERSISTENT_CAPACITY))  # cmp eax, PERSISTENT_CAPACITY
    a.jcc(JAE, "eh_done")
    a.emit(b"\x6b\xc0", _i8(NAME_CAPACITY))  # imul eax, eax, NAME_CAPACITY
    a.emit(0x05, _u32(persist_names))  # add eax, persist_names
    a.emit(b"\x8b\xf8")  # mov edi, eax            ; the slot
    a.emit(b"\x8b\x46", _i8(ARMY_ENTRY_TEMPLATE_OFFSET))  # mov eax, [esi+4]
    a.call("str_copy")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "eh_done")
    a.emit(b"\xff\x05", _u32(persist_count))  # inc dword [persist_count]
    a.label("eh_done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(b"\xc2\x04\x00")  # ret 4

    # `capture`: which army each persistent hero is in, read before any of them deploys.
    #   [ebp-0x04] TheLivingWorldLogic  [ebp-0x08] the player      [ebp-0x0c] the container
    #   [ebp-0x10] player index         [ebp-0x14] army index      [ebp-0x18] record index
    a.label("capture")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x20")  # sub esp, 0x20
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x83\x25", _u32(held_count), 0x00)  # and dword [held_count], 0
    a.emit(b"\xa1", _u32(THE_LIVING_WORLD_LOGIC))  # mov eax, [TheLivingWorldLogic]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "cap_done")
    a.emit(b"\x89\x45\xfc")  # mov [ebp-4], eax
    a.emit(b"\x83\x65\xf0\x00")  # and dword [ebp-0x10], 0

    a.label("cap_player")
    a.emit(b"\x8b\x45\xfc")  # mov eax, [ebp-4]
    a.emit(b"\x8b\x88", _u32(LIVING_WORLD_PLAYERS_END))  # mov ecx, [eax+0x90]
    a.emit(b"\x2b\x88", _u32(LIVING_WORLD_PLAYERS_BEGIN))  # sub ecx, [eax+0x8c]
    a.emit(b"\xc1\xf9\x02")  # sar ecx, 2
    a.emit(b"\x3b\x4d\xf0")  # cmp ecx, [ebp-0x10]
    a.jcc(JLE, "cap_done")  # jle
    a.emit(b"\x8b\x80", _u32(LIVING_WORLD_PLAYERS_BEGIN))  # mov eax, [eax+0x8c]
    a.emit(b"\x8b\x4d\xf0")  # mov ecx, [ebp-0x10]
    a.emit(b"\x8b\x04\x88")  # mov eax, [eax+ecx*4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "cap_player_next")
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax
    a.emit(b"\x83\x65\xec\x00")  # and dword [ebp-0x14], 0

    a.label("cap_army")
    a.emit(b"\x8b\x45\xf8")  # mov eax, [ebp-8]
    a.emit(b"\x8b\x88", _u32(LIVING_WORLD_PLAYER_ARMIES_END))  # mov ecx, [eax+0x1e8]
    a.emit(b"\x2b\x88", _u32(LIVING_WORLD_PLAYER_ARMIES_BEGIN))  # sub ecx, [eax+0x1e4]
    a.emit(b"\xc1\xf9\x02")  # sar ecx, 2
    a.emit(b"\x3b\x4d\xec")  # cmp ecx, [ebp-0x14]
    a.jcc(JLE, "cap_player_next")  # jle
    a.emit(b"\x8b\x80", _u32(LIVING_WORLD_PLAYER_ARMIES_BEGIN))  # mov eax, [eax+0x1e4]
    a.emit(b"\x8b\x4d\xec")  # mov ecx, [ebp-0x14]
    a.emit(b"\x8b\x04\x88")  # mov eax, [eax+ecx*4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "cap_army_next")
    a.emit(b"\x8b\x40", _i8(LIVING_WORLD_ARMY_ROSTER_OFFSET))  # mov eax, [eax+0x78]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "cap_army_next")
    a.emit(b"\x89\x45\xf4")  # mov [ebp-0xc], eax
    a.emit(b"\x83\x65\xe8\x00")  # and dword [ebp-0x18], 0

    a.label("cap_record")
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.call("roster_count")
    a.emit(b"\x3b\x45\xe8")  # cmp eax, [ebp-0x18]
    a.jcc(JLE, "cap_army_next")  # jle
    a.emit(b"\xff\x75\xe8")  # push dword [ebp-0x18]
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.call_absolute(LIVING_WORLD_ARMY_GET_RECORD)  # ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "cap_record_next")
    a.emit(b"\x8b\x40", _i8(ARMY_ENTRY_TEMPLATE_OFFSET))  # mov eax, [eax+4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "cap_record_next")
    a.emit(b"\x83\xc0", bytes([ASCII_STRING_CHARS_OFFSET]))  # add eax, 8
    a.emit(b"\x8b\xf0")  # mov esi, eax            ; the characters
    a.call("is_persistent")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "cap_record_next")
    a.emit(b"\xa1", _u32(held_count))  # mov eax, [held_count]
    a.emit(b"\x83\xf8", _i8(HELD_CAPACITY))  # cmp eax, HELD_CAPACITY
    a.jcc(JAE, "cap_done")
    a.emit(b"\x6b\xc0", _i8(_HELD_SIZE))  # imul eax, eax, _HELD_SIZE
    a.emit(0x05, _u32(held))  # add eax, held
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.emit(b"\x8b\x49", _i8(LIVING_WORLD_ARMY_ROSTER_ID))  # mov ecx, [ecx+0x1c]
    a.emit(b"\x89\x08")  # mov [eax], ecx          ; the army id
    a.emit(b"\x83\xc0", _i8(_HELD_NAME))  # add eax, 4
    a.emit(b"\x8b\xf8")  # mov edi, eax            ; the name slot
    # `esi` still holds the characters; copy them, terminator included, bounded by construction
    # because `is_persistent` only says yes for a name the parser already fitted.
    a.label("cap_name")
    a.emit(b"\x8a\x06")  # mov al, [esi]
    a.emit(b"\x88\x07")  # mov [edi], al
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "cap_named")
    a.emit(0x46, 0x47)  # inc esi, inc edi
    a.jmp("cap_name")
    a.label("cap_named")
    a.emit(b"\xff\x05", _u32(held_count))  # inc dword [held_count]

    a.label("cap_record_next")
    a.emit(b"\xff\x45\xe8")  # inc dword [ebp-0x18]
    a.jmp("cap_record")
    a.label("cap_army_next")
    a.emit(b"\xff\x45\xec")  # inc dword [ebp-0x14]
    a.jmp("cap_army")
    a.label("cap_player_next")
    a.emit(b"\xff\x45\xf0")  # inc dword [ebp-0x10]
    a.jmp("cap_player")
    a.label("cap_done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `rejoin`: esi = the ledger entry, [esp+4] = the army's roster container. Builds a roster
    # record from the entry and appends it. The entry carries the hero as he died, so this is what
    # keeps the level and the upgrades.
    a.label("rejoin")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x08")  # sub esp, 8
    a.emit(0x57)  # push edi
    a.emit(b"\x68", _u32(RECORD_SIZE))  # push 0xd8
    a.call_absolute(OPERATOR_NEW)
    a.emit(0x59)  # pop ecx                 ; __cdecl
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rj_done")
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call_absolute(ARMY_ENTRY_RECORD_CTOR)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rj_done")
    a.emit(b"\x8b\xf8")  # mov edi, eax            ; the record
    a.emit(b"\xff\x87", _u32(ARMY_ENTRY_REFCOUNT_COUNT))  # inc dword [edi+0xc0]
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\xce")  # mov ecx, esi            ; the ledger entry
    a.call_absolute(HERO_LEDGER_TO_RECORD)  # ret 4; fills name, state and upgrades
    a.emit(b"\x89\x7d\xfc")  # mov [ebp-4], edi
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]        ; the roster container
    a.call_absolute(LIVING_WORLD_ARMY_ADD_RECORD)  # ret 4; takes its own reference
    a.emit(b"\x8d\x8f", _u32(ARMY_ENTRY_REFCOUNT_OFFSET))  # lea ecx, [edi+0xbc]
    a.call_absolute(REF_COUNT_RELEASE)
    a.label("rj_done")
    a.emit(0x5F)  # pop edi
    a.emit(0xC9)  # leave
    a.emit(b"\xc2\x04\x00")  # ret 4

    # `restore`: every persistent hero the battle took out of his army, put back from the ledger.
    #   [ebp-0x04] player index  [ebp-0x08] the ledger   [ebp-0x0c] entry index
    #   [ebp-0x10] the entry     [ebp-0x14] characters   [ebp-0x18] the container
    a.label("restore")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x20")  # sub esp, 0x20
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x83\x65\xfc\x00")  # and dword [ebp-4], 0

    a.label("res_player")
    a.emit(b"\x8b\x0d", _u32(THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "res_done")
    a.emit(b"\x8b\x41", _i8(PLAYER_LIST_COUNT_OFFSET))  # mov eax, [ecx+0x14]
    a.emit(b"\x3b\x45\xfc")  # cmp eax, [ebp-4]
    a.jcc(JLE, "res_done")  # jle
    a.emit(b"\xff\x75\xfc")  # push dword [ebp-4]
    a.call_absolute(PLAYER_LIST_GET_NTH)  # thiscall on the list already in ecx, ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "res_player_next")
    a.emit(b"\x83\xb8", _u32(PLAYER_LIVING_WORLD_ID_OFFSET), 0xFF)  # cmp dword [eax+0x3cc], -1
    a.jcc(JE, "res_player_next")
    a.emit(0x05, _u32(PLAYER_HERO_LEDGER_OFFSET))  # add eax, 0x758
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax        ; the hero ledger
    a.emit(b"\x83\x65\xf4\x00")  # and dword [ebp-0xc], 0

    a.label("res_entry")
    a.emit(b"\x8b\x45\xf8")  # mov eax, [ebp-8]
    a.emit(b"\x8b\x48", _i8(HERO_LEDGER_ENTRIES_END))  # mov ecx, [eax+8]
    a.emit(b"\x2b\x48", _i8(HERO_LEDGER_ENTRIES_BEGIN))  # sub ecx, [eax+4]
    a.emit(b"\xb8", _u32(HERO_LEDGER_ENTRY_STRIDE))  # mov eax, 0xe8
    a.emit(b"\x87\xc1")  # xchg eax, ecx
    a.emit(b"\x99")  # cdq
    a.emit(b"\xf7\xf9")  # idiv ecx                ; eax = how many entries
    a.emit(b"\x3b\x45\xf4")  # cmp eax, [ebp-0xc]
    a.jcc(JLE, "res_player_next")  # jle
    a.emit(b"\x8b\x45\xf4")  # mov eax, [ebp-0xc]
    a.emit(b"\x69\xc0", _u32(HERO_LEDGER_ENTRY_STRIDE))  # imul eax, eax, 0xe8
    a.emit(b"\x8b\x4d\xf8")  # mov ecx, [ebp-8]
    a.emit(b"\x03\x41", _i8(HERO_LEDGER_ENTRIES_BEGIN))  # add eax, [ecx+4]
    a.emit(b"\x89\x45\xf0")  # mov [ebp-0x10], eax     ; the entry
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call_absolute(HERO_LEDGER_FIND_TEMPLATE)  # entry -> ThingTemplate
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "res_entry_next")
    a.emit(b"\xf6\x80", _u32(KINDOF_HERO_BYTE), KINDOF_HERO_BIT)  # test byte [eax+0x113], 4
    a.jcc(JE, "res_entry_next")
    a.emit(
        b"\xf6\x80", _u32(KINDOF_ARMY_SUMMARY_BYTE), KINDOF_ARMY_SUMMARY_BIT
    )  # test byte [eax+0x118], 1
    a.jcc(JE, "res_entry_next")
    a.emit(b"\x8b\x45\xf0")  # mov eax, [ebp-0x10]
    a.emit(b"\x8b\x80", _u32(HERO_LEDGER_NAME_OFFSET))  # mov eax, [eax+0xe4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "res_entry_next")
    a.emit(b"\x83\xc0", bytes([ASCII_STRING_CHARS_OFFSET]))  # add eax, 8
    a.emit(b"\x89\x45\xec")  # mov [ebp-0x14], eax     ; the characters

    # Which army was he in? The battle-start capture is the only thing that still knows.
    a.emit(b"\x33\xdb")  # xor ebx, ebx            ; held index
    a.label("res_held")
    a.emit(b"\x3b\x1d", _u32(held_count))  # cmp ebx, [held_count]
    a.jcc(JAE, "res_entry_next")
    a.emit(b"\x6b\xc3", _i8(_HELD_SIZE))  # imul eax, ebx, _HELD_SIZE
    a.emit(0x05, _u32(held))  # add eax, held
    a.emit(b"\x8b\xf8")  # mov edi, eax
    a.emit(b"\x83\xc7", _i8(_HELD_NAME))  # add edi, 4              ; the held name
    a.emit(b"\x8b\x75\xec")  # mov esi, [ebp-0x14]
    a.call("str_eq")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "res_found")
    a.emit(0x43)  # inc ebx
    a.jmp("res_held")

    a.label("res_found")
    a.emit(b"\x6b\xc3", _i8(_HELD_SIZE))  # imul eax, ebx, _HELD_SIZE
    a.emit(0x05, _u32(held))  # add eax, held
    a.emit(b"\x8b\x00")  # mov eax, [eax]          ; the army id
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "res_entry_next")
    a.emit(0x50)  # push eax
    a.call_absolute(LIVING_WORLD_FIND_ARMY_BY_ID)  # ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "res_entry_next")
    a.emit(b"\x8b\x40", _i8(LIVING_WORLD_ARMY_ROSTER_OFFSET))  # mov eax, [eax+0x78]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "res_entry_next")
    a.emit(b"\x89\x45\xe8")  # mov [ebp-0x18], eax     ; the container
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.emit(b"\x8b\x75\xec")  # mov esi, [ebp-0x14]
    a.call("roster_has")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "res_entry_next")  # he survived; the harvest already put him back
    a.emit(b"\xff\x75\xe8")  # push dword [ebp-0x18]
    a.emit(b"\x8b\x75\xf0")  # mov esi, [ebp-0x10]     ; the ledger entry
    a.call("rejoin")  # ret 4

    a.label("res_entry_next")
    a.emit(b"\xff\x45\xf4")  # inc dword [ebp-0xc]
    a.jmp("res_entry")
    a.label("res_player_next")
    a.emit(b"\xff\x45\xfc")  # inc dword [ebp-4]
    a.jmp("res_player")
    a.label("res_done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `setup_hook`: the battle-start call, then the capture. The displaced function takes no stack
    # argument, so nothing has to be re-pushed.
    a.label("setup_hook")
    a.call_absolute(LIVING_WORLD_BATTLE_SETUP)
    a.call("capture")
    a.emit(0xC3)  # ret

    # `harvest_hook`: the harvest, then the restore. The harvest is `__thiscall` with one stack
    # argument it cleans itself, so it is pushed again for it and this hook cleans the caller's
    # copy in its place.
    a.label("harvest_hook")
    a.emit(b"\xff\x74\x24\x04")  # push dword [esp+4]
    a.call_absolute(LIVING_WORLD_BATTLE_HARVEST)  # ret 4
    a.call("restore")
    a.emit(b"\xc2\x04\x00")  # ret 4

    return a


def _field_table(keyword_va: int, stock: bytes) -> bytes:
    """The stock `ArmyEntry` sub-table plus a `Persistent` row, terminator last.

    A row is `{const char *name, ParseFn parse, void *userData, UnsignedInt offset}`. `Persistent`
    is read by the engine's own `Bool` parser into the scratch byte the parse hook consumes."""
    rows = stock[:_ROW_SIZE]  # the stock `Default` row
    added = (
        _u32(keyword_va) + _u32(GAME_DATA_BOOL_PARSER) + _u32(0) + _u32(ARMY_ENTRY_SCRATCH_OFFSET)
    )
    return rows + added + bytes(_ROW_SIZE)


def build_cave(base_va: int, stock_table: bytes | None = None) -> bytes:
    """The cave's bytes, for a section based at ``base_va``."""
    stock = ARMY_ENTRY_DEFAULT_TABLE_BYTES if stock_table is None else stock_table
    layout = cave_layout()
    code = _emit_code(base_va + layout["code"], base_va, layout).finish()

    blob = bytearray(layout["code"])
    table = _field_table(base_va + layout["keyword"], stock)
    blob[layout["field_table"] : layout["field_table"] + len(table)] = table
    keyword = KEYWORD.encode("ascii") + b"\x00"
    blob[layout["keyword"] : layout["keyword"] + len(keyword)] = keyword
    return bytes(blob) + code


def _hook_targets(section_va: int) -> dict[int, int]:
    """Which cave address each patched site now reaches, read off the emitted layout."""
    layout = cave_layout()
    code = _emit_code(section_va + layout["code"], section_va, layout)
    code.finish()
    return {
        ARMY_ENTRY_PARSE_FIELDS_CALL: code.label_va("entry_hook"),
        LIVING_WORLD_BATTLE_SETUP_CALL: code.label_va("setup_hook"),
        LIVING_WORLD_BATTLE_HARVEST_CALL: code.label_va("harvest_hook"),
    }


#: Each displaced `call`, with the stock bytes and the function it must reach.
ANCHORS = {
    ARMY_ENTRY_PARSE_FIELDS_CALL: (ARMY_ENTRY_PARSE_FIELDS_CALL_BYTES, ARMY_ENTRY_PARSE_FIELDS),
    LIVING_WORLD_BATTLE_SETUP_CALL: (
        LIVING_WORLD_BATTLE_SETUP_CALL_BYTES,
        LIVING_WORLD_BATTLE_SETUP,
    ),
    LIVING_WORLD_BATTLE_HARVEST_CALL: (
        LIVING_WORLD_BATTLE_HARVEST_CALL_BYTES,
        LIVING_WORLD_BATTLE_HARVEST,
    ),
}


class HeroArmyCarryoverPatch(Patch):
    name = "hero-army-carryover"
    author = "officialNecro"
    experimental = True
    description = (
        "ArmyEntry gains Persistent: a hero marked Persistent = Yes stays in his living-world army "
        "when he dies in a War of the Ring battle instead of being moved out of it into his "
        "faction's fortress hero-spawn queue, which is what BFME1's heroes do. He rejoins from the "
        "player's hero ledger - the same one the ControlBar offers as revivable during the mission "
        "- so he comes back at the level and with the upgrades he died with, that battle's "
        "progress included. He stays available at his faction's fortress as well, which is "
        "intended: this adds BFME1's army rule without taking ROTWK's own away. Absent or No "
        "is the stock behaviour exactly"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        stock = self._stock_table(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: build_cave(base, stock), _CHARACTERISTICS
        )
        layout = cave_layout()

        off = self._offset(data, ARMY_ENTRY_DEFAULT_TABLE_PUSH)
        apply_byte_patch(
            data,
            off,
            ARMY_ENTRY_DEFAULT_TABLE_PUSH_BYTES,
            b"\x68" + _u32(section_va + layout["field_table"]),
            "the ArmyEntry sub-table -> hero-army-carryover cave",
        )
        for site, target in _hook_targets(section_va).items():
            off = self._offset(data, site)
            apply_byte_patch(
                data,
                off,
                ANCHORS[site][0],
                b"\xe8" + struct.pack("<i", target - (site + 5)),
                f"{site:#010x} -> hero-army-carryover cave",
            )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        for site, (original, callee) in ANCHORS.items():
            off = cls._offset(data, site)
            got = bytes(data[off : off + len(original)])
            if got != original:
                raise ValueError(
                    f"{site:#010x} holds {got.hex()}, expected {original.hex()} - this is not the "
                    "build whose battle boundary the patch was read from"
                )
            reached = site + 5 + struct.unpack_from("<i", original, 1)[0]
            if reached != callee:
                raise ValueError(
                    f"{site:#010x} calls {reached:#010x}, not {callee:#010x} - wrapping it would "
                    "displace the wrong function"
                )

    @classmethod
    def _stock_table(cls, data: bytes | bytearray) -> bytes:
        """The stock `ArmyEntry` sub-table, asserted before it is copied."""
        off = cls._offset(data, ARMY_ENTRY_DEFAULT_TABLE)
        got = bytes(data[off : off + len(ARMY_ENTRY_DEFAULT_TABLE_BYTES)])
        if got != ARMY_ENTRY_DEFAULT_TABLE_BYTES:
            raise ValueError(
                f"the ArmyEntry sub-table at {ARMY_ENTRY_DEFAULT_TABLE:#010x} is not this build's "
                f"({got.hex()}) - refusing to relocate it"
            )
        return got

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        layout = cave_layout()

        off = self._offset(data, ARMY_ENTRY_DEFAULT_TABLE_PUSH)
        if data[off] != 0x68:
            problems.append(f"{ARMY_ENTRY_DEFAULT_TABLE_PUSH:#010x} is not a push")
        else:
            pushed = struct.unpack_from("<I", data, off + 1)[0]
            expected = section_va + layout["field_table"]
            if pushed != expected:
                problems.append(
                    f"{ARMY_ENTRY_DEFAULT_TABLE_PUSH:#010x} pushes {pushed:#010x}, "
                    f"expected {expected:#010x}"
                )

        for site, expected in _hook_targets(section_va).items():
            off = self._offset(data, site)
            if data[off] != 0xE8:
                problems.append(f"{site:#010x} is not a call - the hook is not installed")
                continue
            target = site + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != expected:
                problems.append(f"{site:#010x} calls {target:#010x}, expected {expected:#010x}")

        cave = build_cave(section_va)
        # The two tables are written at run time; the field table, the keyword and the code are not.
        start = layout["field_table"]
        if bytes(data[section_off + start : section_off + len(cave)]) != cave[start:]:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected table and routine")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        if find_section(data, SECTION_NAME) is None:
            return None
        patch = cls()
        return patch if not patch.verify(data) else None

    def ini_surface(self) -> Engine:
        """The one keyword, on the block the engine now parses it in."""
        return Engine(fields=(FieldDelta("ArmyEntry", KEYWORD, "Bool", False, self.name),))
