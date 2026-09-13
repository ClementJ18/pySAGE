"""`MergePlayerArmy`, `DespawnArmy` and `ForceBattle`: the BFME1 campaign Act verbs ROTWK dropped or
compiled out, re-implemented, and `SpawnArmy`'s `ExactPosition`.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The army verbs are derived in
``../docs/living-campaign/merge-player-army.md``; `ForceBattle` and `ExactPosition` in
``../docs/living-campaign/force-battle.md``.

**What BFME1 had.** A campaign `Act` could split a named group of units out of one army into
another (`MergePlayerArmy` with `SplitArmy = Yes` - the Fellowship breaking apart), pour one army
wholesale into another (`SplitArmy = No`), remove an army from the world map
(`DespawnArmy = <name>`), and start a battle (`ForceBattle`). ROTWK's Act verb table has neither
army verb, which is why Edain's `wotrscenarioangmar.inc` carries both of them written out correctly
and commented out with ``; Doesn't work ;( - Necro``. It still parses `ForceBattle`, but the battle
half calls a bare `ret 0xC`.

**What this adds**::

    Act SomeAct
        MergePlayerArmy
            SourceArmy        = Zaphragor_Army        ; a SpawnArmy ScriptingName
            DestArmy          = WitchKing_Army        ; a SpawnArmy ScriptingName
            SplitArmyTemplate = ZaphragorSplitArmy    ; a LivingWorldPlayerArmy, the manifest
            SplitArmy         = Yes                   ; omit to merge the whole army instead
            DespawnSource     = Yes                   ; optional; see below
        End
        DespawnArmy = Zaphragor_Army
        ForceBattle
            Region  = Isengard                        ; or Position = X:203 Y:603
            UseArmy = Saruman_Army                    ; optional, a SpawnArmy ScriptingName
        End
        SpawnArmy
            ScriptingName = Lurtz_Army
            Position      = X:355 Y:266
            ExactPosition = Yes                       ; stand exactly there
        End
    End

`SplitArmyTemplate` names a `LivingWorldPlayerArmy` used purely as a **list of names**: every
roster entry of the source army whose `ThingTemplate` appears in that manifest is moved to the
destination. With `SplitArmy = No` the manifest is ignored and the whole roster moves.

**Armies are named by `ScriptingName`, not by `PlayerArmy` - a deliberate divergence from BFME1.**
BFME1 named `LivingWorldPlayerArmy` *templates* in all three fields, because in BFME1 a template is
the only strategic state there is: every battle re-instantiates an army from its roster and nothing
writes back. ROTWK inverted that - an army's roster is its own object at ``army+0x78``, seeded from
the template once and then rewritten after every battle by the harvest at
:data:`~sage_patch.addresses.LIVING_WORLD_BATTLE_HARVEST` - so mutating a template here would change
only armies spawned *later* and do nothing to the army standing on the map. A mod porting BFME1
campaign INI verbatim therefore has to change these two fields; `SplitArmyTemplate` stays a
template, because it is a manifest rather than a target.

**`DespawnSource` is not a BFME1 field.** BFME1's `absorbInto` left the source army populated and
relied on the next line's `DespawnArmy` to clear it up. Here the unsplit merge **empties** the
source, because leaving a duplicate roster behind in ROTWK means those units exist twice and both
copies deploy. `DespawnSource = Yes` additionally removes the now-empty source army from the map,
so a single block does what BFME1 needed two lines for; it fires only when the source roster ends
up empty, so it is safe to leave on a split that does not exhaust the army.

**`ForceBattle` builds the battle the engine's own conflict pass would.** The two calls into the
stub are repointed at the cave, which queues the request; the queue runs after the stock passes, so
an army spawned or moved by the same act is already there. A queued battle resolves its region -
by name, or as the region containing `Position` - and its point on the map, moves `UseArmy` there
if it stands elsewhere, then takes every army in the region (by the engine's own membership rule),
seats one side per owner, adds the region's owner as defender when
:data:`~sage_patch.addresses.REGION_DEFENDS_AGAINST` says the engine would, and hands the lot to
:data:`~sage_patch.addresses.REGION_STORE_CREATE_BATTLE`. The battle waits in the store like any
other and is offered when the turn reaches its battle phase. Nothing happens when fewer than two
players would fight, when the region already has a battle, or when a named `UseArmy` does not
exist. `ArmyAttackDirection` parses and is ignored: a `LivingWorldBattle` has nowhere to keep it.

**`ExactPosition = Yes` keeps a `SpawnArmy` where its `Position` says.** Stock, an army with a
`HeroTemplateName` whose `Position` lies inside a region is snapped to one of that region's
hero-army slots, and one without a hero is merged into the army its player already has there. Only
the first can be kept in place: a merged record's army no longer exists, so the cave moves the army
it gets back only when that army carries the record's `ScriptingName`. The Act's
`SpawnArmy` parser is handed a copy of its field table with the extra row, and its
`INI::parseFields` call is wrapped so a block that set the flag files its `ScriptingName` in the
cave. When pass three spawns an army at a position, the cave looks the name up and, on a match,
moves the army to the record's `Position` after the engine has placed it. Opt-in because every one
of Edain's 25 `SpawnArmy` positions relies on the snapping today. Honoured only in an Act's
`SpawnArmy`; the army still reserves the slot it was first placed in.

**Where the records live.** The `Act` struct is `0xB8` bytes with three spare
(:data:`~sage_patch.addresses.ACT_SIZE`), so a new verb cannot add a per-act list without rewriting
the constructor, the copy-constructor, the destructor and the campaign's act-vector stride. The
parsed records live in this patch's own cave instead, keyed by the act's **name** - which is
already the engine's key for an act, since `CallActSubroutine` resolves acts that way. Names are
copied out as characters at parse time, so the cave owns no `AsciiString` and no destructor;
:data:`RECORD_CAPACITY` records fit, and a name longer than 63 characters drops its record rather
than being truncated into something that would match the wrong act.

**When they run.** As an eleventh pass of the act runner, after the ten the engine makes. That
ordering is required rather than incidental: BFME1's own usage spawns the destination army in the
same act and then splits into it, and within an act the engine orders by pass, not by INI line.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. None of the seven engine sites it edits is touched by another
bundled patch, and neither stock table it copies is rewritten by one.

**Untested in game.** Every address is read out of the disassembly and the tests are written from
the same reading, so nothing here is confirmed by a scenario having actually been played with it.
"""

from __future__ import annotations

import struct

from sage_ini.engine import BlockDelta, Engine, FieldDelta, NestedDelta

from ..addresses import (
    ACT_FORCE_BATTLE_POSITION_CALL,
    ACT_FORCE_BATTLE_POSITION_CALL_BYTES,
    ACT_FORCE_BATTLE_REGION_CALL,
    ACT_FORCE_BATTLE_REGION_CALL_BYTES,
    ACT_NAME_OFFSET,
    ACT_RUN_PASS9_CALL,
    ACT_RUN_PASS9_CALL_BYTES,
    ACT_SET_PLAYER_CONTROL_EXEC,
    ACT_SPAWN_ARMY_AT_POSITION_CALL,
    ACT_SPAWN_ARMY_AT_POSITION_CALL_BYTES,
    ACT_SPAWN_ARMY_PARSE_FIELDS_CALL,
    ACT_SPAWN_ARMY_PARSE_FIELDS_CALL_BYTES,
    ACT_SPAWN_ARMY_TABLE_PUSH_SITE,
    ACT_SPAWN_ARMY_TABLE_PUSH_SITE_BYTES,
    ACT_VERB_ROW_COUNT,
    ACT_VERB_ROW_SIZE,
    ACT_VERB_TABLE,
    ACT_VERB_TABLE_BYTES,
    ACT_VERB_TABLE_PUSH_SITE,
    ACT_VERB_TABLE_PUSH_SITE_BYTES,
    ARMY_ENTRY_REFCOUNT_OFFSET,
    ARMY_ENTRY_TEMPLATE_OFFSET,
    ARMY_IS_EMPTY_PLACEHOLDER,
    ARMY_SCRIPTING_NAME_OFFSET,
    ARMY_SET_POSITION,
    ARMY_UPDATE_REGION,
    ASCII_STRING_COMPARE,
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    EMPTY_STRING,
    GAME_DATA_ASCIISTRING_PARSER,
    GAME_DATA_BOOL_PARSER,
    INI_PARSE_FIELDS,
    LIVING_WORLD_ARMY_ADD_RECORD,
    LIVING_WORLD_ARMY_DESTROY,
    LIVING_WORLD_ARMY_ERASE_RECORD,
    LIVING_WORLD_ARMY_GET_RECORD,
    LIVING_WORLD_ARMY_OWNER_ID,
    LIVING_WORLD_ARMY_RECORDS_BEGIN,
    LIVING_WORLD_ARMY_RECORDS_END,
    LIVING_WORLD_ARMY_ROSTER_OFFSET,
    LIVING_WORLD_FIND_ARMY_BY_NAME,
    LIVING_WORLD_FIND_PLAYER_ARMY_BY_NAME,
    LIVING_WORLD_FIND_PLAYER_BY_ID,
    LIVING_WORLD_LOGIC_BATTLE_STORE,
    LIVING_WORLD_PLAYER_ARMIES_BEGIN,
    LIVING_WORLD_PLAYER_ARMIES_END,
    LIVING_WORLD_PLAYERS_BEGIN,
    LIVING_WORLD_PLAYERS_END,
    LIVING_WORLD_REGION_OWNER,
    LIVING_WORLD_ROSTER_IN_BATTLE,
    LIVING_WORLD_SPAWN_ARMY,
    REF_COUNT_RELEASE,
    REGION_DEFENDS_AGAINST,
    REGION_IS_DEFENDED,
    REGION_STORE_BATTLE_POINT,
    REGION_STORE_CREATE_BATTLE,
    REGION_STORE_FIND_BATTLE,
    REGION_STORE_FIND_REGION_BY_NAME,
    REGION_STORE_REGION_AT,
    SPAWN_ARMY_FIELD_ROW_COUNT,
    SPAWN_ARMY_FIELD_TABLE,
    SPAWN_ARMY_FIELD_TABLE_BYTES,
    SPAWN_ARMY_POSITION_OFFSET,
    SPAWN_ARMY_SCRIPTING_NAME_OFFSET,
    THE_LIVING_WORLD_CAMPAIGN_MANAGER,
    THE_LIVING_WORLD_LOGIC,
)
from ..asm import JAE, JB, JE, JGE, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

# Where an `AsciiString`'s characters start, kept where the other string-reading patches keep it.
from .utils.token_lists import ASCII_STRING_CHARS

__all__ = [
    "ARMY_SLOTS",
    "BATTLE_CAPACITY",
    "BATTLE_SIZE",
    "EXACT_CAPACITY",
    "FIELD_ROWS",
    "NAME_CAPACITY",
    "PLAYER_SLOTS",
    "RECORD_CAPACITY",
    "RECORD_SIZE",
    "SECTION_NAME",
    "SITES",
    "CampaignArmyVerbsPatch",
    "build_cave",
    "cave_layout",
]

SECTION_NAME = ".actarm"  # 7 chars: the PE name field is 8 bytes and truncates silently

# CODE | INITIALIZED_DATA | EXECUTE | READ | WRITE - the cave is code plus the record table the
# parse functions fill in, so it is written as well as run.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: How many characters of a name a record keeps, terminator included. A longer `SourceArmy`,
#: `DestArmy`, `SplitArmyTemplate` or act name drops the whole record: silently truncating one
#: would leave it matching a *different* army, which is worse than not running.
NAME_CAPACITY = 64

#: How many `MergePlayerArmy`/`DespawnArmy` entries the cave holds across the whole campaign INI.
#: BFME1's Gondor campaign - the heaviest user there has ever been - writes 14 merges and 9
#: despawns between them.
RECORD_CAPACITY = 64

#: How many `SpawnArmy` blocks across the campaign may say `ExactPosition = Yes`.
EXACT_CAPACITY = 64

#: How many `ForceBattle` requests one act may queue. BFME1's campaigns never put two in one act.
BATTLE_CAPACITY = 16

#: The most armies and players one forced battle gathers; a region holding more fights with the
#: first ones found.
ARMY_SLOTS = 32
PLAYER_SLOTS = 8

# One parsed verb. Four fixed-size names, then the three bytes that say what to do with them.
_REC_ACT = 0x00
_REC_SOURCE = 0x40
_REC_DEST = 0x80
_REC_TEMPLATE = 0xC0
_REC_KIND = 0x100
_REC_SPLIT = 0x101
_REC_DESPAWN = 0x102
RECORD_SIZE = 0x104

_KIND_MERGE = 0
_KIND_DESPAWN = 1

# One queued `ForceBattle`: which form it is, the region name or the point, and the army to use.
_BTL_KIND = 0x00
_BTL_REGION = 0x04
_BTL_ARMY = 0x44
_BTL_X = 0x84
_BTL_Y = 0x88
BATTLE_SIZE = 0x8C

_BATTLE_BY_REGION = 0
_BATTLE_BY_POSITION = 1

# The scratch `MergePlayerArmy` record the field table parses into, on the parser's own stack.
_SCRATCH_SIZE = 0x10
_FLD_SOURCE = 0x00
_FLD_DEST = 0x04
_FLD_TEMPLATE = 0x08
_FLD_SPLIT = 0x0C
_FLD_DESPAWN = 0x0D

#: The `MergePlayerArmy` block's fields, as `(keyword, parser, offset in the scratch record)`.
#: Every one of them is parsed by an engine parser, so the cave writes no scalar parser of its own.
FIELD_ROWS: tuple[tuple[str, int, int], ...] = (
    ("SourceArmy", GAME_DATA_ASCIISTRING_PARSER, _FLD_SOURCE),
    ("DestArmy", GAME_DATA_ASCIISTRING_PARSER, _FLD_DEST),
    ("SplitArmyTemplate", GAME_DATA_ASCIISTRING_PARSER, _FLD_TEMPLATE),
    ("SplitArmy", GAME_DATA_BOOL_PARSER, _FLD_SPLIT),
    ("DespawnSource", GAME_DATA_BOOL_PARSER, _FLD_DESPAWN),
)

_MERGE_VERB = "MergePlayerArmy"
_DESPAWN_VERB = "DespawnArmy"
_EXACT_FIELD = "ExactPosition"

# The strings the cave needs, in the order they are laid out.
_STRINGS: tuple[str, ...] = (
    _MERGE_VERB,
    _DESPAWN_VERB,
    *(name for name, _, _ in FIELD_ROWS),
    _EXACT_FIELD,
)

#: Every engine site the patch rewrites: `(va, stock bytes, the cave label it now reaches, what it
#: is)`. A `push` site gets the label's address as its immediate, a `call` site a rel32 to it.
SITES: tuple[tuple[int, bytes, str, str], ...] = (
    (
        ACT_VERB_TABLE_PUSH_SITE,
        ACT_VERB_TABLE_PUSH_SITE_BYTES,
        "verb_table",
        "the Act verb table",
    ),
    (ACT_RUN_PASS9_CALL, ACT_RUN_PASS9_CALL_BYTES, "pass_hook", "act runner pass 9"),
    (
        ACT_SPAWN_ARMY_TABLE_PUSH_SITE,
        ACT_SPAWN_ARMY_TABLE_PUSH_SITE_BYTES,
        "spawn_field_table",
        "the Act SpawnArmy field table",
    ),
    (
        ACT_SPAWN_ARMY_PARSE_FIELDS_CALL,
        ACT_SPAWN_ARMY_PARSE_FIELDS_CALL_BYTES,
        "spawn_parse_fields",
        "the Act SpawnArmy parseFields call",
    ),
    (
        ACT_SPAWN_ARMY_AT_POSITION_CALL,
        ACT_SPAWN_ARMY_AT_POSITION_CALL_BYTES,
        "spawn_at_position",
        "pass 3's spawn at a position",
    ),
    (
        ACT_FORCE_BATTLE_REGION_CALL,
        ACT_FORCE_BATTLE_REGION_CALL_BYTES,
        "battle_by_region",
        "ForceBattle's Region call",
    ),
    (
        ACT_FORCE_BATTLE_POSITION_CALL,
        ACT_FORCE_BATTLE_POSITION_CALL_BYTES,
        "battle_by_position",
        "ForceBattle's Position call",
    ),
)

# The labels a site may name that are data rather than code.
_DATA_LABELS = ("verb_table", "spawn_field_table")


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> bytes:
    return struct.pack("<b", value)


def cave_layout() -> dict[str, int]:
    """Offsets from the cave's base for everything in it.

    The data comes **first**, at offsets that depend on nothing, so the code that follows can
    address it as `base + constant`; the code's own addresses are only known once it is laid out,
    which is the direction the verb table needs and the data does not. Everything the running game
    writes sits before `verb_table`, which is where `verify` starts comparing."""
    count = 0x00
    records = 0x04
    exact_pending = records + RECORD_CAPACITY * RECORD_SIZE
    exact_count = exact_pending + 4
    exact_names = exact_count + 4
    battle_count = exact_names + EXACT_CAPACITY * NAME_CAPACITY
    battles = battle_count + 4
    armies = battles + BATTLE_CAPACITY * BATTLE_SIZE
    armies_vector = armies + ARMY_SLOTS * 4
    players = armies_vector + 12
    players_vector = players + PLAYER_SLOTS * 4
    battle_point = players_vector + 12
    verb_table = (battle_point + 8 + 3) & ~3
    # The stock rows, this patch's two, and the terminator.
    field_table = verb_table + (ACT_VERB_ROW_COUNT + 3) * ACT_VERB_ROW_SIZE
    spawn_field_table = field_table + (len(FIELD_ROWS) + 1) * ACT_VERB_ROW_SIZE
    # The stock rows, `ExactPosition`, and the terminator.
    strings = spawn_field_table + (SPAWN_ARMY_FIELD_ROW_COUNT + 2) * ACT_VERB_ROW_SIZE
    layout = {
        "count": count,
        "records": records,
        "exact_pending": exact_pending,
        "exact_count": exact_count,
        "exact_names": exact_names,
        "battle_count": battle_count,
        "battles": battles,
        "armies": armies,
        "armies_vector": armies_vector,
        "players": players,
        "players_vector": players_vector,
        "battle_point": battle_point,
        "verb_table": verb_table,
        "field_table": field_table,
        "spawn_field_table": spawn_field_table,
    }
    offset = strings
    for text in _STRINGS:
        layout[f"str:{text}"] = offset
        offset += len(text) + 1
    layout["code"] = (offset + 15) & ~15
    return layout


def _emit_code(base_va: int, data_va: int, layout: dict[str, int]) -> Asm:
    """The cave's routines, laid out but not resolved. `data_va` is the cave's base, which is what
    the absolute addresses of the record table and the field table are computed from."""
    a = Asm(base_va)
    count_va = data_va + layout["count"]
    records_va = data_va + layout["records"]
    field_table_va = data_va + layout["field_table"]
    exact_pending_va = data_va + layout["exact_pending"]
    exact_count_va = data_va + layout["exact_count"]
    exact_names_va = data_va + layout["exact_names"]
    battle_count_va = data_va + layout["battle_count"]
    battles_va = data_va + layout["battles"]
    armies_va = data_va + layout["armies"]
    armies_vector_va = data_va + layout["armies_vector"]
    players_va = data_va + layout["players"]
    players_vector_va = data_va + layout["players_vector"]
    battle_point_va = data_va + layout["battle_point"]

    def _record_base() -> None:
        """`eax = records + eax * RECORD_SIZE` - where the next free record starts."""
        a.emit(b"\x69\xc0", _u32(RECORD_SIZE))  # imul eax, eax, RECORD_SIZE
        a.emit(0x05, _u32(records_va))  # add eax, records

    # `str_copy`: eax = an AsciiString handle, edi = a NAME_CAPACITY-byte field. al = 1 when the
    # name fitted. A null handle copies as the empty string, which no army is named.
    a.label("str_copy")
    a.emit(0x53)  # push ebx
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JNE, "sc_have")
    a.emit(b"\xc6\x07\x00")  # mov byte [edi], 0
    a.emit(0x5B)  # pop ebx
    a.emit(b"\xb0\x01")  # mov al, 1
    a.emit(0xC3)  # ret

    a.label("sc_have")
    a.emit(b"\x8d\x70", bytes([ASCII_STRING_CHARS]))  # lea esi, [eax+8]
    a.emit(b"\x33\xc9")  # xor ecx, ecx
    a.label("sc_loop")
    a.emit(b"\x8a\x1c\x0e")  # mov bl, [esi+ecx]
    a.emit(b"\x88\x1c\x0f")  # mov [edi+ecx], bl
    a.emit(b"\x84\xdb")  # test bl, bl
    a.jcc_short(JE, "sc_ok")
    a.emit(0x41)  # inc ecx
    a.emit(b"\x83\xf9", _i8(NAME_CAPACITY))  # cmp ecx, NAME_CAPACITY
    a.jcc_short(JB, "sc_loop")
    a.emit(b"\xc6\x07\x00")  # mov byte [edi], 0   ; too long: refuse the record
    a.emit(0x5B)  # pop ebx
    a.emit(b"\x32\xc0")  # xor al, al
    a.emit(0xC3)  # ret

    a.label("sc_ok")
    a.emit(0x5B)  # pop ebx
    a.emit(b"\xb0\x01")  # mov al, 1
    a.emit(0xC3)  # ret

    # `str_eq`: edi and esi are NUL-terminated; al = 1 when they are equal. Both sides of the act
    # comparison are copies of the same INI token, so this is a plain byte compare on purpose.
    a.label("str_eq")
    a.emit(b"\x8a\x07")  # mov al, [edi]
    a.emit(b"\x8a\x16")  # mov dl, [esi]
    a.emit(b"\x3a\xc2")  # cmp al, dl
    a.jcc_short(JNE, "se_no")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JE, "se_yes")
    a.emit(0x47)  # inc edi
    a.emit(0x46)  # inc esi
    a.jmp_short("str_eq")
    a.label("se_yes")
    a.emit(b"\xb0\x01")  # mov al, 1
    a.emit(0xC3)  # ret
    a.label("se_no")
    a.emit(b"\x32\xc0")  # xor al, al
    a.emit(0xC3)  # ret

    # `find_army`: eax = characters, returns the living-world army of that ScriptingName or 0.
    # The lookup goes through the engine's own matcher, so the patch inherits whatever the engine
    # considers an equal name rather than re-deciding it.
    a.label("find_army")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x08")  # sub esp, 8
    a.emit(0x56)  # push esi
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax
    a.emit(b"\xff\x75\xf8")  # push dword [ebp-8]
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_CTOR)  # ret 4; zeroes the slot itself
    a.emit(b"\x33\xf6")  # xor esi, esi
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc_short(JE, "fa_dtor")
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.call_absolute(LIVING_WORLD_FIND_ARMY_BY_NAME)  # ret 4
    a.emit(b"\x8b\xf0")  # mov esi, eax
    a.label("fa_dtor")
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(b"\x8b\xc6")  # mov eax, esi
    a.emit(0x5E)  # pop esi
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `find_manifest`: eax = characters, returns the LivingWorldPlayerArmy of that Name or 0.
    a.label("find_manifest")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x08")  # sub esp, 8
    a.emit(0x56)  # push esi
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax
    a.emit(b"\xff\x75\xf8")  # push dword [ebp-8]
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_CTOR)
    a.emit(b"\x33\xf6")  # xor esi, esi
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_CAMPAIGN_MANAGER))  # mov ecx, [manager]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc_short(JE, "fm_dtor")
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.call_absolute(LIVING_WORLD_FIND_PLAYER_ARMY_BY_NAME)  # ret 4
    a.emit(b"\x8b\xf0")  # mov esi, eax
    a.label("fm_dtor")
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(b"\x8b\xc6")  # mov eax, esi
    a.emit(0x5E)  # pop esi
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `merge_parse`: __cdecl(ini, act, store, userData), the row's parse function. Modelled on
    # `SetPlayerControlOfArmy`'s own parser - build a scratch record, hand it and the field table
    # to `INI::parseFields`, then take what the block said.
    a.label("merge_parse")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec", _i8(_SCRATCH_SIZE))  # sub esp, 0x10
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x33\xc0")  # xor eax, eax
    for slot in (-0x10, -0x0C, -0x08, -0x04):
        a.emit(b"\x89\x45", _i8(slot))  # mov [ebp+slot], eax
    a.emit(0x68, _u32(field_table_va))  # push field_table
    a.emit(b"\x8d\x45\xf0")  # lea eax, [ebp-0x10]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]        ; the INI reader
    a.call_absolute(INI_PARSE_FIELDS)  # ret 8

    a.emit(b"\xa1", _u32(count_va))  # mov eax, [count]
    a.emit(b"\x83\xf8", _i8(RECORD_CAPACITY))  # cmp eax, RECORD_CAPACITY
    a.jcc(JAE, "mp_done")
    _record_base()
    a.emit(b"\x8b\xd8")  # mov ebx, eax             ; the record being filled
    a.emit(b"\x8b\x45\x0c")  # mov eax, [ebp+0xc]      ; the act
    a.emit(b"\x8b\x40", _i8(ACT_NAME_OFFSET))  # mov eax, [eax+4]
    a.emit(b"\x8b\xfb")  # mov edi, ebx
    a.call("str_copy")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "mp_done")
    for slot, field in ((-0x10, _REC_SOURCE), (-0x0C, _REC_DEST), (-0x08, _REC_TEMPLATE)):
        a.emit(b"\x8b\x45", _i8(slot))  # mov eax, [ebp+slot]
        if field < 0x80:
            a.emit(b"\x8d\x7b", _i8(field))  # lea edi, [ebx+field]
        else:
            a.emit(b"\x8d\xbb", _u32(field))  # lea edi, [ebx+field]
        a.call("str_copy")
        a.emit(b"\x84\xc0")  # test al, al
        a.jcc(JE, "mp_done")
    a.emit(b"\x8a\x45", _i8(-0x04))  # mov al, [ebp-4]         ; SplitArmy
    a.emit(b"\x88\x83", _u32(_REC_SPLIT))  # mov [ebx+0x101], al
    a.emit(b"\x8a\x45", _i8(-0x03))  # mov al, [ebp-3]         ; DespawnSource
    a.emit(b"\x88\x83", _u32(_REC_DESPAWN))  # mov [ebx+0x102], al
    a.emit(b"\xc6\x83", _u32(_REC_KIND), _KIND_MERGE)  # mov byte [ebx+0x100], 0

    # A block that names neither army does nothing; a split with no manifest would silently move
    # nothing. Both are INI mistakes worth dropping rather than storing.
    a.emit(b"\x80\x7b", _i8(_REC_SOURCE), 0x00)  # cmp byte [ebx+0x40], 0
    a.jcc(JE, "mp_done")
    a.emit(b"\x80\xbb", _u32(_REC_DEST), 0x00)  # cmp byte [ebx+0x80], 0
    a.jcc(JE, "mp_done")
    a.emit(b"\x80\xbb", _u32(_REC_SPLIT), 0x00)  # cmp byte [ebx+0x101], 0
    a.jcc(JE, "mp_commit")
    a.emit(b"\x80\xbb", _u32(_REC_TEMPLATE), 0x00)  # cmp byte [ebx+0xc0], 0
    a.jcc(JE, "mp_done")
    a.label("mp_commit")
    a.emit(b"\xff\x05", _u32(count_va))  # inc dword [count]

    a.label("mp_done")
    for slot in (-0x10, -0x0C, -0x08):
        a.emit(b"\x8d\x4d", _i8(slot))  # lea ecx, [ebp+slot]
        a.call_absolute(ASCII_STRING_DTOR)
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `despawn_parse`: __cdecl(ini, act, store, userData). `DespawnArmy = <name>` is a plain field
    # rather than a block, so the engine's own AsciiString parser reads the value into a scratch
    # slot and the record is built from that.
    a.label("despawn_parse")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x04")  # sub esp, 4
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x83\x65\xfc\x00")  # and dword [ebp-4], 0
    a.emit(b"\x6a\x00")  # push 0                  ; userData
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax                ; store
    a.emit(b"\xff\x75\x0c")  # push dword [ebp+0xc]    ; instance
    a.emit(b"\xff\x75\x08")  # push dword [ebp+8]      ; ini
    a.call_absolute(GAME_DATA_ASCIISTRING_PARSER)  # __cdecl
    a.emit(b"\x83\xc4\x10")  # add esp, 0x10

    a.emit(b"\xa1", _u32(count_va))  # mov eax, [count]
    a.emit(b"\x83\xf8", _i8(RECORD_CAPACITY))  # cmp eax, RECORD_CAPACITY
    a.jcc(JAE, "dp_done")
    _record_base()
    a.emit(b"\x8b\xd8")  # mov ebx, eax
    a.emit(b"\x8b\x45\x0c")  # mov eax, [ebp+0xc]
    a.emit(b"\x8b\x40", _i8(ACT_NAME_OFFSET))  # mov eax, [eax+4]
    a.emit(b"\x8b\xfb")  # mov edi, ebx
    a.call("str_copy")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "dp_done")
    a.emit(b"\x8b\x45\xfc")  # mov eax, [ebp-4]
    a.emit(b"\x8d\x7b", _i8(_REC_SOURCE))  # lea edi, [ebx+0x40]
    a.call("str_copy")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "dp_done")
    a.emit(b"\x80\x7b", _i8(_REC_SOURCE), 0x00)  # cmp byte [ebx+0x40], 0
    a.jcc(JE, "dp_done")
    a.emit(b"\xc6\x83", _u32(_REC_KIND), _KIND_DESPAWN)  # mov byte [ebx+0x100], 1
    a.emit(b"\xc6\x83", _u32(_REC_SPLIT), 0x00)  # mov byte [ebx+0x101], 0
    a.emit(b"\xc6\x83", _u32(_REC_DESPAWN), 0x00)  # mov byte [ebx+0x102], 0
    a.emit(b"\xff\x05", _u32(count_va))  # inc dword [count]

    a.label("dp_done")
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `pass_hook`: what pass nine's `call` now reaches. It makes the call it displaced, then runs
    # the act's merges and despawns, then the battles its pass two queued - so the stock ten still
    # happen in the stock order and a battle sees every army the act spawned or moved.
    a.label("pass_hook")
    a.emit(0x51)  # push ecx
    a.call_absolute(ACT_SET_PLAYER_CONTROL_EXEC)
    a.emit(0x59)  # pop ecx
    a.call("run_pass")
    a.jmp("run_battles")

    # `run_pass`: ecx = the act. Runs every record written for this act's name.
    a.label("run_pass")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x08")  # sub esp, 8
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x8b\x41", _i8(ACT_NAME_OFFSET))  # mov eax, [ecx+4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "rp_empty")
    a.emit(b"\x83\xc0", bytes([ASCII_STRING_CHARS]))  # add eax, 8
    a.jmp_short("rp_have")
    a.label("rp_empty")
    a.emit(0xB8, _u32(EMPTY_STRING))  # mov eax, EMPTY_STRING
    a.label("rp_have")
    a.emit(b"\x89\x45\xfc")  # mov [ebp-4], eax        ; the act's characters
    a.emit(b"\x33\xdb")  # xor ebx, ebx            ; the record index

    a.label("rp_loop")
    a.emit(b"\x3b\x1d", _u32(count_va))  # cmp ebx, [count]
    a.jcc(JAE, "rp_done")
    a.emit(b"\x69\xc3", _u32(RECORD_SIZE))  # imul eax, ebx, RECORD_SIZE
    a.emit(0x05, _u32(records_va))  # add eax, records
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax
    a.emit(b"\x8b\xf8")  # mov edi, eax            ; rec->act
    a.emit(b"\x8b\x75\xfc")  # mov esi, [ebp-4]
    a.call("str_eq")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "rp_next")
    a.emit(b"\x8b\x75\xf8")  # mov esi, [ebp-8]        ; the record
    a.emit(b"\x80\xbe", _u32(_REC_KIND), _KIND_MERGE)  # cmp byte [esi+0x100], 0
    a.jcc(JNE, "rp_despawn")
    a.call("run_merge")
    a.jmp("rp_next")
    a.label("rp_despawn")
    a.call("run_despawn")
    a.label("rp_next")
    a.emit(0x43)  # inc ebx
    a.jmp("rp_loop")
    a.label("rp_done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `run_despawn`: esi = the record. Takes the named army off the map.
    a.label("run_despawn")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x56)  # push esi
    a.emit(b"\x8d\x46", _i8(_REC_SOURCE))  # lea eax, [esi+0x40]
    a.call("find_army")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "rd_done")
    a.emit(b"\x8b\xf0")  # mov esi, eax
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc_short(JE, "rd_done")
    a.emit(0x56)  # push esi
    a.call_absolute(LIVING_WORLD_ARMY_DESTROY)  # ret 4
    a.label("rd_done")
    a.emit(0x5E)  # pop esi
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `run_merge`: esi = the record.
    #   [ebp-0x04] the record   [ebp-0x08] the source army
    #   [ebp-0x0c] its roster   [ebp-0x10] the destination's roster
    #   [ebp-0x14] the record being moved   [ebp-0x18] the manifest
    a.label("run_merge")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x18")  # sub esp, 0x18
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x89\x75\xfc")  # mov [ebp-4], esi
    a.emit(b"\x8d\x46", _i8(_REC_SOURCE))  # lea eax, [esi+0x40]
    a.call("find_army")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rm_done")
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax        ; the source army
    a.emit(b"\x8b\x40", _i8(LIVING_WORLD_ARMY_ROSTER_OFFSET))  # mov eax, [eax+0x78]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rm_done")
    a.emit(b"\x89\x45\xf4")  # mov [ebp-0xc], eax      ; the source roster
    a.emit(b"\x8b\x75\xfc")  # mov esi, [ebp-4]
    a.emit(b"\x8d\x86", _u32(_REC_DEST))  # lea eax, [esi+0x80]
    a.call("find_army")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rm_done")
    a.emit(b"\x8b\x40", _i8(LIVING_WORLD_ARMY_ROSTER_OFFSET))  # mov eax, [eax+0x78]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rm_done")
    a.emit(b"\x89\x45\xf0")  # mov [ebp-0x10], eax     ; the destination roster
    a.emit(b"\x8b\x75\xfc")  # mov esi, [ebp-4]
    a.emit(b"\x80\xbe", _u32(_REC_SPLIT), 0x00)  # cmp byte [esi+0x101], 0
    a.jcc(JNE, "rm_split")

    # `SplitArmy = No`: the whole roster moves, bounded by the count taken before the first move.
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.call("roster_count")
    a.emit(b"\x8b\xd8")  # mov ebx, eax
    a.label("rm_all")
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc(JLE, "rm_finish")
    a.emit(b"\x33\xc0")  # xor eax, eax
    a.call("move_record")
    a.emit(0x4B)  # dec ebx
    a.jmp("rm_all")

    # `SplitArmy = Yes`: one pass over the manifest, moving at most one roster entry per name.
    a.label("rm_split")
    a.emit(b"\x8d\x86", _u32(_REC_TEMPLATE))  # lea eax, [esi+0xc0]
    a.call("find_manifest")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rm_done")
    a.emit(b"\x89\x45\xe8")  # mov [ebp-0x18], eax
    a.emit(b"\x33\xdb")  # xor ebx, ebx            ; the manifest index

    a.label("rm_entry")
    a.emit(b"\x8b\x4d\xe8")  # mov ecx, [ebp-0x18]
    a.call("roster_count")
    a.emit(b"\x3b\xd8")  # cmp ebx, eax
    a.jcc(JGE, "rm_finish")
    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\x4d\xe8")  # mov ecx, [ebp-0x18]
    a.call_absolute(LIVING_WORLD_ARMY_GET_RECORD)  # ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rm_entry_next")
    a.emit(b"\x83\xc0", _i8(ARMY_ENTRY_TEMPLATE_OFFSET))  # add eax, 4
    a.emit(b"\x8b\xf8")  # mov edi, eax            ; &manifest entry's name
    a.emit(b"\x33\xf6")  # xor esi, esi            ; the roster index

    a.label("rm_find")
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.call("roster_count")
    a.emit(b"\x3b\xf0")  # cmp esi, eax
    a.jcc(JGE, "rm_entry_next")
    a.emit(0x56)  # push esi
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.call_absolute(LIVING_WORLD_ARMY_GET_RECORD)  # ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rm_find_next")
    a.emit(0x57)  # push edi
    a.emit(b"\x8d\x48", _i8(ARMY_ENTRY_TEMPLATE_OFFSET))  # lea ecx, [eax+4]
    a.call_absolute(ASCII_STRING_COMPARE)  # ret 4; zero when equal
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "rm_find_next")
    a.emit(b"\x8b\xc6")  # mov eax, esi
    a.call("move_record")
    a.jmp("rm_entry_next")
    a.label("rm_find_next")
    a.emit(0x46)  # inc esi
    a.jmp("rm_find")
    a.label("rm_entry_next")
    a.emit(0x43)  # inc ebx
    a.jmp("rm_entry")

    # `DespawnSource`, and only once the source has actually been emptied.
    a.label("rm_finish")
    a.emit(b"\x8b\x75\xfc")  # mov esi, [ebp-4]
    a.emit(b"\x80\xbe", _u32(_REC_DESPAWN), 0x00)  # cmp byte [esi+0x102], 0
    a.jcc(JE, "rm_done")
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.call("roster_count")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "rm_done")
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "rm_done")
    a.emit(b"\xff\x75\xf8")  # push dword [ebp-8]
    a.call_absolute(LIVING_WORLD_ARMY_DESTROY)  # ret 4

    a.label("rm_done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `move_record`: eax = the index in the source roster. Runs on `run_merge`'s frame, so it
    # reads the two rosters out of that frame's locals rather than taking them in registers.
    # The erase hands back a reference; the append takes its own, so ours is dropped after.
    a.label("move_record")
    a.emit(b"\x83\x65\xec\x00")  # and dword [ebp-0x14], 0
    a.emit(0x50)  # push eax                ; the index
    a.emit(b"\x8d\x45\xec")  # lea eax, [ebp-0x14]
    a.emit(0x50)  # push eax                ; &out
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]      ; the source roster
    a.call_absolute(LIVING_WORLD_ARMY_ERASE_RECORD)  # ret 8
    a.emit(b"\x8b\x45\xec")  # mov eax, [ebp-0x14]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "mv_done")
    a.emit(b"\x8d\x45\xec")  # lea eax, [ebp-0x14]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\xf0")  # mov ecx, [ebp-0x10]     ; the destination roster
    a.call_absolute(LIVING_WORLD_ARMY_ADD_RECORD)  # ret 4
    a.emit(b"\x8b\x4d\xec")  # mov ecx, [ebp-0x14]
    a.emit(b"\x81\xc1", _u32(ARMY_ENTRY_REFCOUNT_OFFSET))  # add ecx, 0xbc
    a.call_absolute(REF_COUNT_RELEASE)
    a.label("mv_done")
    a.emit(0xC3)  # ret

    # `roster_count`: ecx = a roster container, eax = how many records it holds.
    a.label("roster_count")
    a.emit(b"\x8b\x41", _i8(LIVING_WORLD_ARMY_RECORDS_END))  # mov eax, [ecx+0x44]
    a.emit(b"\x2b\x41", _i8(LIVING_WORLD_ARMY_RECORDS_BEGIN))  # sub eax, [ecx+0x40]
    a.emit(b"\xc1\xf8\x03")  # sar eax, 3
    a.emit(0xC3)  # ret

    # `exact_parse`: __cdecl(ini, instance, store, userData), the `ExactPosition` row. The record
    # has no spare field to hold the flag, so the engine's Bool parser writes it into the cave.
    a.label("exact_parse")
    a.emit(b"\x6a\x00")  # push 0                  ; userData
    a.emit(0x68, _u32(exact_pending_va))  # push exact_pending      ; store
    a.emit(b"\xff\x74\x24\x10")  # push dword [esp+0x10]   ; instance
    a.emit(b"\xff\x74\x24\x10")  # push dword [esp+0x10]   ; ini
    a.call_absolute(GAME_DATA_BOOL_PARSER)  # __cdecl
    a.emit(b"\x83\xc4\x10")  # add esp, 0x10
    a.emit(0xC3)  # ret

    # `spawn_parse_fields`: what the Act's `SpawnArmy` parser calls instead of `INI::parseFields`,
    # thiscall(ini; record, table), `ret 8`. The flag is cleared before the block is read, so only
    # a block that says `ExactPosition = Yes` files its name - and a parse that throws half-way
    # leaves nothing for the next block to inherit.
    a.label("spawn_parse_fields")
    a.emit(b"\xc6\x05", _u32(exact_pending_va), 0x00)  # mov byte [exact_pending], 0
    a.emit(b"\xff\x74\x24\x08")  # push dword [esp+8]      ; the table
    a.emit(b"\xff\x74\x24\x08")  # push dword [esp+8]      ; the record
    a.call_absolute(INI_PARSE_FIELDS)  # ret 8; ecx is still the reader
    a.emit(b"\x80\x3d", _u32(exact_pending_va), 0x00)  # cmp byte [exact_pending], 0
    a.jcc(JE, "spf_done")
    a.emit(b"\x8b\x44\x24\x04")  # mov eax, [esp+4]        ; the record
    a.emit(b"\x8b\x40", _i8(SPAWN_ARMY_SCRIPTING_NAME_OFFSET))  # mov eax, [eax+0x18]
    a.emit(b"\x85\xc0")  # test eax, eax            ; no name, nothing to key on
    a.jcc(JE, "spf_done")
    a.emit(0x56, 0x57)  # push esi, edi
    a.emit(b"\x8b\x15", _u32(exact_count_va))  # mov edx, [exact_count]
    a.emit(b"\x83\xfa", _i8(EXACT_CAPACITY))  # cmp edx, EXACT_CAPACITY
    a.jcc(JAE, "spf_restore")
    a.emit(b"\x69\xfa", _u32(NAME_CAPACITY))  # imul edi, edx, NAME_CAPACITY
    a.emit(b"\x81\xc7", _u32(exact_names_va))  # add edi, exact_names
    a.call("str_copy")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "spf_restore")
    a.emit(b"\x80\x3f\x00")  # cmp byte [edi], 0
    a.jcc(JE, "spf_restore")
    a.emit(b"\xff\x05", _u32(exact_count_va))  # inc dword [exact_count]
    a.label("spf_restore")
    a.emit(0x5F, 0x5E)  # pop edi, esi
    a.label("spf_done")
    a.emit(b"\xc6\x05", _u32(exact_pending_va), 0x00)  # mov byte [exact_pending], 0
    a.emit(b"\xc2\x08\x00")  # ret 8

    # `spawn_at_position`: what pass three calls for a record with a non-zero `Position`,
    # thiscall(TheLivingWorldLogic; record, player, controllable), `ret 0xC`. The engine spawns and
    # places the army first; a name `ExactPosition` filed is then moved to the record's point.
    #   [ebp-0x04] the record's name characters   [ebp-0x08] the index into the filed names
    a.label("spawn_at_position")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x08")  # sub esp, 8
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\xff\x75\x10")  # push dword [ebp+0x10]
    a.emit(b"\xff\x75\x0c")  # push dword [ebp+0xc]
    a.emit(b"\xff\x75\x08")  # push dword [ebp+8]
    a.call_absolute(LIVING_WORLD_SPAWN_ARMY)  # ret 0xC; ecx untouched since entry
    a.emit(b"\x8b\xd8")  # mov ebx, eax            ; the army
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc(JE, "sa_done")
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]
    a.emit(b"\x8b\x40", _i8(SPAWN_ARMY_SCRIPTING_NAME_OFFSET))  # mov eax, [eax+0x18]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "sa_done")
    a.emit(b"\x83\xc0", bytes([ASCII_STRING_CHARS]))  # add eax, 8
    a.emit(b"\x89\x45\xfc")  # mov [ebp-4], eax
    # A record with no hero is merged into the army its player already has in the region, and the
    # engine hands back that army - which is not the one the record describes and must not move.
    a.emit(b"\x8b\x43", _i8(ARMY_SCRIPTING_NAME_OFFSET))  # mov eax, [ebx+0x1c]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "sa_done")
    a.emit(b"\x8d\x78", bytes([ASCII_STRING_CHARS]))  # lea edi, [eax+8]
    a.emit(b"\x8b\x75\xfc")  # mov esi, [ebp-4]
    a.call("str_eq")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "sa_done")
    a.emit(b"\x83\x65\xf8\x00")  # and dword [ebp-8], 0
    a.label("sa_loop")
    a.emit(b"\x8b\x45\xf8")  # mov eax, [ebp-8]
    a.emit(b"\x3b\x05", _u32(exact_count_va))  # cmp eax, [exact_count]
    a.jcc(JAE, "sa_done")
    a.emit(b"\x69\xf8", _u32(NAME_CAPACITY))  # imul edi, eax, NAME_CAPACITY
    a.emit(b"\x81\xc7", _u32(exact_names_va))  # add edi, exact_names
    a.emit(b"\x8b\x75\xfc")  # mov esi, [ebp-4]
    a.call("str_eq")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "sa_exact")
    a.emit(b"\xff\x45\xf8")  # inc dword [ebp-8]
    a.jmp("sa_loop")
    a.label("sa_exact")
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]
    a.emit(b"\x83\xc0", _i8(SPAWN_ARMY_POSITION_OFFSET))  # add eax, 0x20   ; &Position
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\xcb")  # mov ecx, ebx
    a.call_absolute(ARMY_SET_POSITION)  # ret 4
    a.emit(b"\x8b\xcb")  # mov ecx, ebx
    a.call_absolute(ARMY_UPDATE_REGION)
    a.label("sa_done")
    a.emit(b"\x8b\xc3")  # mov eax, ebx
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(b"\xc2\x0c\x00")  # ret 0xC

    # `battle_by_region` / `battle_by_position`: the two calls pass two made into the stub,
    # thiscall(TheLivingWorldLogic; Region name or &Position, UseArmy, &ArmyAttackDirection),
    # `ret 0xC`. The strings are the pass's own temporaries, so the request is copied, not kept.
    a.label("battle_by_region")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\xa1", _u32(battle_count_va))  # mov eax, [battle_count]
    a.emit(b"\x83\xf8", _i8(BATTLE_CAPACITY))  # cmp eax, BATTLE_CAPACITY
    a.jcc(JAE, "bq_out")
    a.emit(b"\x69\xd8", _u32(BATTLE_SIZE))  # imul ebx, eax, BATTLE_SIZE
    a.emit(b"\x81\xc3", _u32(battles_va))  # add ebx, battles
    a.emit(b"\xc6\x03", _BATTLE_BY_REGION)  # mov byte [ebx], 0
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]
    a.emit(b"\x8b\x00")  # mov eax, [eax]          ; the Region string's handle
    a.emit(b"\x8d\x7b", _i8(_BTL_REGION))  # lea edi, [ebx+4]
    a.call("str_copy")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "bq_out")
    a.emit(b"\x80\x7b", _i8(_BTL_REGION), 0x00)  # cmp byte [ebx+4], 0
    a.jcc(JE, "bq_out")
    a.jmp("bq_army")

    a.label("battle_by_position")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\xa1", _u32(battle_count_va))  # mov eax, [battle_count]
    a.emit(b"\x83\xf8", _i8(BATTLE_CAPACITY))  # cmp eax, BATTLE_CAPACITY
    a.jcc(JAE, "bq_out")
    a.emit(b"\x69\xd8", _u32(BATTLE_SIZE))  # imul ebx, eax, BATTLE_SIZE
    a.emit(b"\x81\xc3", _u32(battles_va))  # add ebx, battles
    a.emit(b"\xc6\x03", _BATTLE_BY_POSITION)  # mov byte [ebx], 1
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]        ; &Position
    a.emit(b"\x8b\x10")  # mov edx, [eax]
    a.emit(b"\x89\x93", _u32(_BTL_X))  # mov [ebx+0x84], edx
    a.emit(b"\x8b\x50\x04")  # mov edx, [eax+4]
    a.emit(b"\x89\x93", _u32(_BTL_Y))  # mov [ebx+0x88], edx

    a.label("bq_army")
    a.emit(b"\x8b\x45\x0c")  # mov eax, [ebp+0xc]
    a.emit(b"\x8b\x00")  # mov eax, [eax]          ; UseArmy's handle, possibly null
    a.emit(b"\x8d\x7b", _i8(_BTL_ARMY))  # lea edi, [ebx+0x44]
    a.call("str_copy")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "bq_out")
    a.emit(b"\xff\x05", _u32(battle_count_va))  # inc dword [battle_count]
    a.label("bq_out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(b"\xc2\x0c\x00")  # ret 0xC

    # `run_battles`: builds every queued battle, then empties the queue.
    a.label("run_battles")
    a.emit(0x53, 0x56)  # push ebx, esi
    a.emit(b"\x33\xdb")  # xor ebx, ebx
    a.label("rb_loop")
    a.emit(b"\x3b\x1d", _u32(battle_count_va))  # cmp ebx, [battle_count]
    a.jcc(JAE, "rb_done")
    a.emit(b"\x69\xf3", _u32(BATTLE_SIZE))  # imul esi, ebx, BATTLE_SIZE
    a.emit(b"\x81\xc6", _u32(battles_va))  # add esi, battles
    a.call("force_battle")
    a.emit(0x43)  # inc ebx
    a.jmp("rb_loop")
    a.label("rb_done")
    a.emit(b"\x83\x25", _u32(battle_count_va), 0x00)  # and dword [battle_count], 0
    a.emit(0x5E, 0x5B)  # pop esi, ebx
    a.emit(0xC3)  # ret

    # `force_battle`: esi = a queued request. Does what `RegionStore::detectConflicts` does for one
    # region, without its "is there a conflict" gate.
    #   [ebp-0x04] the region store   [ebp-0x08] the region    [ebp-0x0c] UseArmy, or 0
    #   [ebp-0x10] the attacker       [ebp-0x14] armies taken  [ebp-0x18] players taken
    #   [ebp-0x1c] player index       [ebp-0x20] army index    [ebp-0x24] the request
    #   [ebp-0x28] the owner          [ebp-0x2c] a scratch AsciiString
    a.label("force_battle")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x30")  # sub esp, 0x30
    a.emit(0x53, 0x56, 0x57)  # push ebx, esi, edi
    a.emit(b"\x89\x75\xdc")  # mov [ebp-0x24], esi
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "fb_ret")
    a.emit(b"\x8b\x81", _u32(LIVING_WORLD_LOGIC_BATTLE_STORE))  # mov eax, [ecx+0xb0]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_ret")
    a.emit(b"\x89\x45\xfc")  # mov [ebp-4], eax

    # A named UseArmy that does not exist is an INI mistake: no battle rather than a different one.
    a.emit(b"\x33\xc0")  # xor eax, eax
    a.emit(b"\x89\x45\xf4")  # mov [ebp-0xc], eax
    a.emit(b"\x80\x7e", _i8(_BTL_ARMY), 0x00)  # cmp byte [esi+0x44], 0
    a.jcc(JE, "fb_region")
    a.emit(b"\x8d\x46", _i8(_BTL_ARMY))  # lea eax, [esi+0x44]
    a.call("find_army")
    a.emit(b"\x89\x45\xf4")  # mov [ebp-0xc], eax
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_ret")

    a.label("fb_region")
    a.emit(b"\x8b\x75\xdc")  # mov esi, [ebp-0x24]
    a.emit(b"\x80\x3e", _BATTLE_BY_REGION)  # cmp byte [esi], 0
    a.jcc(JNE, "fb_by_position")
    a.emit(b"\x8d\x46", _i8(_BTL_REGION))  # lea eax, [esi+4]
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x4d\xd4")  # lea ecx, [ebp-0x2c]
    a.call_absolute(ASCII_STRING_CTOR)  # ret 4
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.emit(b"\x8d\x45\xd4")  # lea eax, [ebp-0x2c]
    a.emit(0x50)  # push eax
    a.call_absolute(REGION_STORE_FIND_REGION_BY_NAME)  # ret 4
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax
    a.emit(b"\x8d\x4d\xd4")  # lea ecx, [ebp-0x2c]
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(b"\x8b\x45\xf8")  # mov eax, [ebp-8]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_ret")
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.emit(0x68, _u32(battle_point_va))  # push battle_point
    a.emit(0x50)  # push eax
    a.call_absolute(REGION_STORE_BATTLE_POINT)  # ret 8
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "fb_ret")
    a.jmp("fb_have_region")

    a.label("fb_by_position")
    a.emit(b"\x8b\x86", _u32(_BTL_X))  # mov eax, [esi+0x84]
    a.emit(b"\xa3", _u32(battle_point_va))  # mov [battle_point], eax
    a.emit(b"\x8b\x86", _u32(_BTL_Y))  # mov eax, [esi+0x88]
    a.emit(b"\xa3", _u32(battle_point_va + 4))  # mov [battle_point+4], eax
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.emit(b"\x6a\x00")  # push 0                  ; no hint
    a.emit(0x68, _u32(battle_point_va))  # push battle_point
    a.call_absolute(REGION_STORE_REGION_AT)  # ret 8
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_ret")

    # One battle per region, as the engine keeps it.
    a.label("fb_have_region")
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.emit(b"\xff\x75\xf8")  # push dword [ebp-8]
    a.call_absolute(REGION_STORE_FIND_BATTLE)  # ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "fb_ret")

    # UseArmy fights where the battle is: move it there if it stands anywhere else.
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "fb_collect")
    a.call_absolute(ARMY_UPDATE_REGION)
    a.emit(b"\x3b\x45\xf8")  # cmp eax, [ebp-8]
    a.jcc(JE, "fb_collect")
    a.emit(0x68, _u32(battle_point_va))  # push battle_point
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.call_absolute(ARMY_SET_POSITION)  # ret 4
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.call_absolute(ARMY_UPDATE_REGION)

    # Every army in the region, by the membership rule the engine's conflict pass applies.
    a.label("fb_collect")
    a.emit(b"\x33\xc0")  # xor eax, eax
    a.emit(b"\x89\x45\xec")  # mov [ebp-0x14], eax
    a.emit(b"\x89\x45\xe8")  # mov [ebp-0x18], eax
    a.emit(b"\x89\x45\xe4")  # mov [ebp-0x1c], eax
    a.label("fb_player_loop")
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x8b\x81", _u32(LIVING_WORLD_PLAYERS_END))  # mov eax, [ecx+0x90]
    a.emit(b"\x2b\x81", _u32(LIVING_WORLD_PLAYERS_BEGIN))  # sub eax, [ecx+0x8c]
    a.emit(b"\xc1\xf8\x02")  # sar eax, 2
    a.emit(b"\x39\x45\xe4")  # cmp [ebp-0x1c], eax
    a.jcc(JAE, "fb_players_done")
    a.emit(b"\x8b\x81", _u32(LIVING_WORLD_PLAYERS_BEGIN))  # mov eax, [ecx+0x8c]
    a.emit(b"\x8b\x55\xe4")  # mov edx, [ebp-0x1c]
    a.emit(b"\x8b\x3c\x90")  # mov edi, [eax+edx*4]    ; the player
    a.emit(b"\x83\x65\xe0\x00")  # and dword [ebp-0x20], 0
    a.label("fb_army_loop")
    a.emit(b"\x8b\x87", _u32(LIVING_WORLD_PLAYER_ARMIES_END))  # mov eax, [edi+0x1e8]
    a.emit(b"\x2b\x87", _u32(LIVING_WORLD_PLAYER_ARMIES_BEGIN))  # sub eax, [edi+0x1e4]
    a.emit(b"\xc1\xf8\x02")  # sar eax, 2
    a.emit(b"\x39\x45\xe0")  # cmp [ebp-0x20], eax
    a.jcc(JAE, "fb_next_player")
    a.emit(b"\x8b\x87", _u32(LIVING_WORLD_PLAYER_ARMIES_BEGIN))  # mov eax, [edi+0x1e4]
    a.emit(b"\x8b\x55\xe0")  # mov edx, [ebp-0x20]
    a.emit(b"\x8b\x1c\x90")  # mov ebx, [eax+edx*4]    ; the army
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc(JE, "fb_next_army")
    a.emit(b"\x8b\xcb")  # mov ecx, ebx
    a.call_absolute(ARMY_UPDATE_REGION)
    a.emit(b"\x3b\x45\xf8")  # cmp eax, [ebp-8]
    a.jcc(JNE, "fb_next_army")
    a.emit(b"\x8b\xcb")  # mov ecx, ebx
    a.call_absolute(ARMY_IS_EMPTY_PLACEHOLDER)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "fb_take_army")
    a.emit(b"\x8b\x45\xf8")  # mov eax, [ebp-8]
    a.emit(b"\x8b\x80", _u32(LIVING_WORLD_REGION_OWNER))  # mov eax, [eax+0x15c]
    a.emit(b"\x3b\x43", _i8(LIVING_WORLD_ARMY_OWNER_ID))  # cmp eax, [ebx+0x54]
    a.jcc(JNE, "fb_next_army")
    a.emit(b"\x8b\x4d\xf8")  # mov ecx, [ebp-8]
    a.call_absolute(REGION_IS_DEFENDED)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "fb_next_army")
    a.label("fb_take_army")
    a.emit(b"\x8b\xc3")  # mov eax, ebx
    a.call("take_army")
    a.label("fb_next_army")
    a.emit(b"\xff\x45\xe0")  # inc dword [ebp-0x20]
    a.jmp("fb_army_loop")
    a.label("fb_next_player")
    a.emit(b"\xff\x45\xe4")  # inc dword [ebp-0x1c]
    a.jmp("fb_player_loop")

    # UseArmy fights whatever the membership rule made of it.
    a.label("fb_players_done")
    a.emit(b"\x8b\x45\xf4")  # mov eax, [ebp-0xc]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_sides")
    a.call("take_army")

    # One side per owner of a fighting army, each army flagged the way the conflict pass flags it.
    a.label("fb_sides")
    a.emit(b"\x83\x65\xe0\x00")  # and dword [ebp-0x20], 0
    a.label("fb_side_loop")
    a.emit(b"\x8b\x45\xe0")  # mov eax, [ebp-0x20]
    a.emit(b"\x3b\x45\xec")  # cmp eax, [ebp-0x14]
    a.jcc(JAE, "fb_sides_done")
    a.emit(b"\x8b\x1c\x85", _u32(armies_va))  # mov ebx, [armies+eax*4]
    a.emit(b"\x8b\x43", _i8(LIVING_WORLD_ARMY_ROSTER_OFFSET))  # mov eax, [ebx+0x78]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_owner")
    a.emit(b"\xc7\x40", _i8(LIVING_WORLD_ROSTER_IN_BATTLE), _u32(1))  # mov dword [eax+0x2c], 1
    a.label("fb_owner")
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x6a\x00")  # push 0
    a.emit(b"\xff\x73", _i8(LIVING_WORLD_ARMY_OWNER_ID))  # push dword [ebx+0x54]
    a.call_absolute(LIVING_WORLD_FIND_PLAYER_BY_ID)  # ret 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_side_next")
    a.call("take_player")
    a.label("fb_side_next")
    a.emit(b"\xff\x45\xe0")  # inc dword [ebp-0x20]
    a.jmp("fb_side_loop")

    # The attacker is UseArmy's owner, or whoever was found first.
    a.label("fb_sides_done")
    a.emit(b"\x8b\x45\xf4")  # mov eax, [ebp-0xc]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_first")
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x6a\x00")  # push 0
    a.emit(b"\xff\x70", _i8(LIVING_WORLD_ARMY_OWNER_ID))  # push dword [eax+0x54]
    a.call_absolute(LIVING_WORLD_FIND_PLAYER_BY_ID)  # ret 8
    a.jmp("fb_attacker")
    a.label("fb_first")
    a.emit(b"\x33\xc0")  # xor eax, eax
    a.emit(b"\x39\x45\xe8")  # cmp [ebp-0x18], eax
    a.jcc(JE, "fb_attacker")
    a.emit(b"\xa1", _u32(players_va))  # mov eax, [players]
    a.label("fb_attacker")
    a.emit(b"\x89\x45\xf0")  # mov [ebp-0x10], eax

    # The region's owner defends when the engine's own test says it would.
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_count")
    a.emit(b"\x8b\x45\xf8")  # mov eax, [ebp-8]
    a.emit(b"\x8b\x80", _u32(LIVING_WORLD_REGION_OWNER))  # mov eax, [eax+0x15c]
    a.emit(b"\x83\xf8\xff")  # cmp eax, -1
    a.jcc(JE, "fb_count")
    a.emit(b"\x8b\x0d", _u32(THE_LIVING_WORLD_LOGIC))  # mov ecx, [TheLivingWorldLogic]
    a.emit(b"\x6a\x00")  # push 0
    a.emit(0x50)  # push eax
    a.call_absolute(LIVING_WORLD_FIND_PLAYER_BY_ID)  # ret 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_count")
    a.emit(b"\x89\x45\xd8")  # mov [ebp-0x28], eax
    a.emit(b"\xff\x75\xf0")  # push dword [ebp-0x10]
    a.emit(b"\x8b\x4d\xf8")  # mov ecx, [ebp-8]
    a.call_absolute(REGION_DEFENDS_AGAINST)  # ret 4
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "fb_count")
    a.emit(b"\x8b\x45\xd8")  # mov eax, [ebp-0x28]
    a.call("take_player")

    # A battle needs two sides. The vectors are handed over as `begin, end`, which is all
    # `createBattle` and the battle's constructor read of them.
    a.label("fb_count")
    a.emit(b"\x83\x7d\xe8\x02")  # cmp dword [ebp-0x18], 2
    a.jcc(JB, "fb_ret")
    a.emit(b"\x8b\x45\xec")  # mov eax, [ebp-0x14]
    a.emit(b"\x8d\x04\x85", _u32(armies_va))  # lea eax, [armies+eax*4]
    a.emit(b"\xa3", _u32(armies_vector_va + 4))  # mov [armies_vector+4], eax
    a.emit(b"\x8b\x45\xe8")  # mov eax, [ebp-0x18]
    a.emit(b"\x8d\x04\x85", _u32(players_va))  # lea eax, [players+eax*4]
    a.emit(b"\xa3", _u32(players_vector_va + 4))  # mov [players_vector+4], eax
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.emit(0x68, _u32(battle_point_va))  # push battle_point
    a.emit(0x68, _u32(players_vector_va))  # push players_vector
    a.emit(0x68, _u32(armies_vector_va))  # push armies_vector
    a.emit(b"\xff\x75\xf8")  # push dword [ebp-8]
    a.call_absolute(REGION_STORE_CREATE_BATTLE)  # ret 0x10

    a.label("fb_ret")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi, esi, ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # `take_army` / `take_player`: eax = one to add, once. Run on `force_battle`'s frame, whose
    # locals hold the counts.
    for label, count_slot, buffer_va, slots in (
        ("take_army", -0x14, armies_va, ARMY_SLOTS),
        ("take_player", -0x18, players_va, PLAYER_SLOTS),
    ):
        a.label(label)
        a.emit(b"\x8b\x55", _i8(count_slot))  # mov edx, [ebp+count]
        a.emit(b"\x33\xc9")  # xor ecx, ecx
        a.label(f"{label}_loop")
        a.emit(b"\x3b\xca")  # cmp ecx, edx
        a.jcc_short(JAE, f"{label}_append")
        a.emit(b"\x39\x04\x8d", _u32(buffer_va))  # cmp [buffer+ecx*4], eax
        a.jcc_short(JE, f"{label}_done")
        a.emit(0x41)  # inc ecx
        a.jmp_short(f"{label}_loop")
        a.label(f"{label}_append")
        a.emit(b"\x83\xfa", _i8(slots))  # cmp edx, slots
        a.jcc_short(JAE, f"{label}_done")
        a.emit(b"\x89\x04\x95", _u32(buffer_va))  # mov [buffer+edx*4], eax
        a.emit(b"\xff\x45", _i8(count_slot))  # inc dword [ebp+count]
        a.label(f"{label}_done")
        a.emit(0xC3)  # ret

    return a


def _verb_table(stock: bytes, merge_parse: int, despawn_parse: int, strings_va: dict) -> bytes:
    """The stock rows, this patch's two, and the terminator.

    A row is `{const char *name, ParseFn parse, void *userData, UnsignedInt offset}`. Both new
    rows carry offset 0, like every other block-shaped verb: the record they build does not live
    on the Act, so there is no field for the driver to compute an address into."""
    rows = stock[: ACT_VERB_ROW_COUNT * ACT_VERB_ROW_SIZE]
    added = b"".join(
        _u32(strings_va[name]) + _u32(parse) + _u32(0) + _u32(0)
        for name, parse in ((_MERGE_VERB, merge_parse), (_DESPAWN_VERB, despawn_parse))
    )
    return rows + added + bytes(ACT_VERB_ROW_SIZE)


def _field_table(strings_va: dict) -> bytes:
    """The `MergePlayerArmy` block's field table, in the engine's own row format."""
    rows = b"".join(
        _u32(strings_va[name]) + _u32(parse) + _u32(0) + _u32(offset)
        for name, parse, offset in FIELD_ROWS
    )
    return rows + bytes(ACT_VERB_ROW_SIZE)


def _spawn_field_table(stock: bytes, exact_parse: int, strings_va: dict) -> bytes:
    """The Act `SpawnArmy` field table: the stock rows, `ExactPosition`, and the terminator. The
    new row's offset is 0 because its parser ignores the store it is handed."""
    rows = stock[: SPAWN_ARMY_FIELD_ROW_COUNT * ACT_VERB_ROW_SIZE]
    added = _u32(strings_va[_EXACT_FIELD]) + _u32(exact_parse) + _u32(0) + _u32(0)
    return rows + added + bytes(ACT_VERB_ROW_SIZE)


def build_cave(
    base_va: int,
    stock_table: bytes = ACT_VERB_TABLE_BYTES,
    stock_spawn_table: bytes = SPAWN_ARMY_FIELD_TABLE_BYTES,
) -> bytes:
    """The cave's bytes, for a section based at ``base_va``."""
    layout = cave_layout()
    code = _emit_code(base_va + layout["code"], base_va, layout)
    strings_va = {text: base_va + layout[f"str:{text}"] for text in _STRINGS}

    blob = bytearray(layout["code"])
    blob[layout["count"] : layout["count"] + 4] = _u32(0)
    # Both battle vectors start empty: `begin == end`, with the capacity their buffers really have.
    for vector, buffer, slots in (
        ("armies_vector", "armies", ARMY_SLOTS),
        ("players_vector", "players", PLAYER_SLOTS),
    ):
        start = base_va + layout[buffer]
        blob[layout[vector] : layout[vector] + 12] = (
            _u32(start) + _u32(start) + _u32(start + slots * 4)
        )
    table = _verb_table(
        stock_table, code.label_va("merge_parse"), code.label_va("despawn_parse"), strings_va
    )
    blob[layout["verb_table"] : layout["verb_table"] + len(table)] = table
    fields = _field_table(strings_va)
    blob[layout["field_table"] : layout["field_table"] + len(fields)] = fields
    spawn = _spawn_field_table(stock_spawn_table, code.label_va("exact_parse"), strings_va)
    blob[layout["spawn_field_table"] : layout["spawn_field_table"] + len(spawn)] = spawn
    for text in _STRINGS:
        start = layout[f"str:{text}"]
        blob[start : start + len(text) + 1] = text.encode("ascii") + b"\x00"
    return bytes(blob) + code.finish()


def _hook_targets(section_va: int) -> dict[str, int]:
    """Where each site's label lands, read off the layout that was actually emitted rather than
    counted a second time by hand."""
    layout = cave_layout()
    code = _emit_code(section_va + layout["code"], section_va, layout)
    return {
        label: section_va + layout[label] if label in _DATA_LABELS else code.label_va(label)
        for _, _, label, _ in SITES
    }


def _site_bytes(va: int, stock: bytes, target: int) -> bytes:
    """The five bytes a site becomes: the same instruction, aimed at the cave."""
    if stock[0] == 0x68:
        return b"\x68" + _u32(target)
    return b"\xe8" + struct.pack("<i", target - (va + 5))


class CampaignArmyVerbsPatch(Patch):
    name = "campaign-army-verbs"
    author = "officialNecro"
    description = (
        "Restore BFME1's campaign Act verbs. MergePlayerArmy { SourceArmy, DestArmy, "
        "SplitArmyTemplate, SplitArmy, DespawnSource } moves roster entries from one living-world "
        "army to another - all of them, or just the ones a SplitArmyTemplate "
        "LivingWorldPlayerArmy names - and DespawnArmy = <name> removes an army from the world "
        "map. ForceBattle { Region or Position, UseArmy } builds a battle in that region from the "
        "armies there plus UseArmy, which ROTWK parses but never starts. SpawnArmy gains "
        "ExactPosition = Yes, keeping an army at its Position instead of the region's army slot. "
        "Army names are SpawnArmy ScriptingNames, not PlayerArmy names as they were in BFME1, "
        "because in ROTWK the live army's roster is the state and the template is only its seed. "
        f"Up to {RECORD_CAPACITY} merge/despawn entries across the campaign, names up to "
        f"{NAME_CAPACITY - 1} characters"
    )

    def apply(self, data: bytearray) -> None:
        stock = self._stock_table(data, ACT_VERB_TABLE, ACT_VERB_TABLE_BYTES)
        stock_spawn = self._stock_table(data, SPAWN_ARMY_FIELD_TABLE, SPAWN_ARMY_FIELD_TABLE_BYTES)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: build_cave(base, stock, stock_spawn), _CHARACTERISTICS
        )
        targets = _hook_targets(section_va)
        for va, original, label, what in SITES:
            apply_byte_patch(
                data,
                self._offset(data, va),
                original,
                _site_bytes(va, original, targets[label]),
                f"{what} -> campaign-army-verbs cave",
            )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _stock_table(cls, data: bytes | bytearray, va: int, expected: bytes) -> bytes:
        """A stock field table, asserted before it is copied.

        The copy is only as good as what it copies: a build whose table has moved, grown or holds
        different parsers has to fail here rather than have wrong rows relocated into a cave and
        pushed at the parser."""
        off = cls._offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"the table at {va:#010x} is not this build's "
                f"({got[:16].hex()}...) - refusing to relocate it"
            )
        return got

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        targets = _hook_targets(section_va)

        for va, original, label, what in SITES:
            off = self._offset(data, va)
            expected = targets[label]
            if original[0] == 0x68:
                if data[off] != 0x68:
                    problems.append(f"{va:#010x} is not a push - {what} is stock")
                    continue
                pushed = struct.unpack_from("<I", data, off + 1)[0]
                if pushed != expected:
                    problems.append(f"{va:#010x} pushes {pushed:#010x}, expected {expected:#010x}")
            else:
                if data[off] != 0xE8:
                    problems.append(f"{va:#010x} is not a call - {what} is not hooked")
                    continue
                target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
                if target != expected:
                    problems.append(f"{va:#010x} calls {target:#010x}, expected {expected:#010x}")

        cave = build_cave(section_va)
        # Everything before the verb table is written at run time, so only the parts that never
        # change are compared: everything from the verb table on.
        start = cave_layout()["verb_table"]
        if bytes(data[section_off + start : section_off + len(cave)]) != cave[start:]:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected tables and code")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        if find_section(data, SECTION_NAME) is None:
            return None
        patch = cls()
        return patch if not patch.verify(data) else None

    def ini_surface(self) -> Engine:
        """The verb block, where it may be written, the field `DespawnArmy` becomes on an Act, and
        `SpawnArmy`'s new flag.

        `MergePlayerArmy` needs both a block type and a place to appear: registering the type says
        it exists, and nesting it under `Act` is what stops every use being reported as an unknown
        attribute of the act it is written in. `ForceBattle` is stock surface already."""
        return Engine(
            blocks=(BlockDelta(_MERGE_VERB, base="NestedAttribute", patch=self.name),),
            nested=(NestedDelta("Act", _MERGE_VERB, patch=self.name),),
            fields=(
                # One record per line, so repeating the field despawns every army it names.
                FieldDelta("Act", _DESPAWN_VERB, "Opaque[]", None, self.name),
                FieldDelta(_MERGE_VERB, "SourceArmy", "Opaque", None, self.name),
                FieldDelta(_MERGE_VERB, "DestArmy", "Opaque", None, self.name),
                FieldDelta(
                    _MERGE_VERB,
                    "SplitArmyTemplate",
                    "Ref:livingworldplayerarmys",
                    None,
                    self.name,
                ),
                FieldDelta(_MERGE_VERB, "SplitArmy", "Bool", False, self.name),
                FieldDelta(_MERGE_VERB, "DespawnSource", "Bool", False, self.name),
                FieldDelta("SpawnArmy", _EXACT_FIELD, "Bool", False, self.name),
            ),
        )
