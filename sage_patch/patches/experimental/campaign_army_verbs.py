"""`MergePlayerArmy` and `DespawnArmy`: the two BFME1 campaign Act verbs that move a living-world
army's units around and take an army off the map, re-implemented for ROTWK.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/living-campaign/merge-player-army.md``.

**What BFME1 had.** A campaign `Act` could split a named group of units out of one army into
another (`MergePlayerArmy` with `SplitArmy = Yes` - the Fellowship breaking apart), pour one army
wholesale into another (`SplitArmy = No`), and remove an army from the world map
(`DespawnArmy = <name>`). ROTWK's Act verb table has neither, which is why Edain's
`wotrscenarioangmar.inc` carries both of them written out correctly and commented out with
``; Doesn't work ;( - Necro``.

**What this adds**, as two rows on the Act verb table::

    Act SomeAct
        MergePlayerArmy
            SourceArmy        = Zaphragor_Army        ; a SpawnArmy ScriptingName
            DestArmy          = WitchKing_Army        ; a SpawnArmy ScriptingName
            SplitArmyTemplate = ZaphragorSplitArmy    ; a LivingWorldPlayerArmy, the manifest
            SplitArmy         = Yes                   ; omit to merge the whole army instead
            DespawnSource     = Yes                   ; optional; see below
        End
        DespawnArmy = Zaphragor_Army
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
:meth:`verify` finds it by name. The two engine sites it edits - the `push` of the Act verb table
at :data:`~sage_patch.addresses.ACT_VERB_TABLE_PUSH_SITE` and pass nine's `call` at
:data:`~sage_patch.addresses.ACT_RUN_PASS9_CALL` - are touched by no other bundled patch, and the
stock table it copies is rewritten by none either.

**Untested in game.** Every address is read out of the disassembly and the tests are written from
the same reading, so this is `experimental` until a scenario has actually been played with it.
"""

from __future__ import annotations

import struct

from sage_ini.engine import BlockDelta, Engine, FieldDelta, NestedDelta

from ...addresses import (
    ACT_NAME_OFFSET,
    ACT_RUN_PASS9_CALL,
    ACT_RUN_PASS9_CALL_BYTES,
    ACT_SET_PLAYER_CONTROL_EXEC,
    ACT_VERB_ROW_COUNT,
    ACT_VERB_ROW_SIZE,
    ACT_VERB_TABLE,
    ACT_VERB_TABLE_BYTES,
    ACT_VERB_TABLE_PUSH_SITE,
    ACT_VERB_TABLE_PUSH_SITE_BYTES,
    ARMY_ENTRY_REFCOUNT_OFFSET,
    ARMY_ENTRY_TEMPLATE_OFFSET,
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
    LIVING_WORLD_ARMY_RECORDS_BEGIN,
    LIVING_WORLD_ARMY_RECORDS_END,
    LIVING_WORLD_ARMY_ROSTER_OFFSET,
    LIVING_WORLD_FIND_ARMY_BY_NAME,
    LIVING_WORLD_FIND_PLAYER_ARMY_BY_NAME,
    REF_COUNT_RELEASE,
    THE_LIVING_WORLD_CAMPAIGN_MANAGER,
    THE_LIVING_WORLD_LOGIC,
)
from ...asm import JAE, JB, JE, JGE, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

# Where an `AsciiString`'s characters start, kept where the other string-reading patches keep it.
from ..utils.token_lists import ASCII_STRING_CHARS

__all__ = [
    "FIELD_ROWS",
    "NAME_CAPACITY",
    "RECORD_CAPACITY",
    "RECORD_SIZE",
    "SECTION_NAME",
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

# The strings the cave needs, in the order they are laid out.
_STRINGS: tuple[str, ...] = (_MERGE_VERB, _DESPAWN_VERB, *(name for name, _, _ in FIELD_ROWS))


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> bytes:
    return struct.pack("<b", value)


def cave_layout() -> dict[str, int]:
    """Offsets from the cave's base for everything in it.

    The data comes **first**, at offsets that depend on nothing, so the code that follows can
    address it as `base + constant`; the code's own addresses are only known once it is laid out,
    which is the direction the verb table needs and the data does not."""
    count = 0x00
    records = 0x04
    verb_table = records + RECORD_CAPACITY * RECORD_SIZE
    # The stock rows, this patch's two, and the terminator.
    field_table = verb_table + (ACT_VERB_ROW_COUNT + 3) * ACT_VERB_ROW_SIZE
    strings = field_table + (len(FIELD_ROWS) + 1) * ACT_VERB_ROW_SIZE
    layout = {
        "count": count,
        "records": records,
        "verb_table": verb_table,
        "field_table": field_table,
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

    # `pass_hook`: what pass nine's `call` now reaches. It makes the call it displaced and then
    # falls into the new pass, so the stock ten still happen in the stock order.
    a.label("pass_hook")
    a.emit(0x51)  # push ecx
    a.call_absolute(ACT_SET_PLAYER_CONTROL_EXEC)
    a.emit(0x59)  # pop ecx

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


def build_cave(base_va: int, stock_table: bytes = ACT_VERB_TABLE_BYTES) -> bytes:
    """The cave's bytes, for a section based at ``base_va``."""
    layout = cave_layout()
    code = _emit_code(base_va + layout["code"], base_va, layout)
    strings_va = {text: base_va + layout[f"str:{text}"] for text in _STRINGS}

    blob = bytearray(layout["code"])
    blob[layout["count"] : layout["count"] + 4] = _u32(0)
    table = _verb_table(
        stock_table, code.label_va("merge_parse"), code.label_va("despawn_parse"), strings_va
    )
    blob[layout["verb_table"] : layout["verb_table"] + len(table)] = table
    fields = _field_table(strings_va)
    blob[layout["field_table"] : layout["field_table"] + len(fields)] = fields
    for text in _STRINGS:
        start = layout[f"str:{text}"]
        blob[start : start + len(text) + 1] = text.encode("ascii") + b"\x00"
    return bytes(blob) + code.finish()


def _hook_targets(section_va: int) -> tuple[int, int]:
    """`(the verb table's new address, the address pass nine now calls)`, read off the layout that
    was actually emitted rather than counted a second time by hand."""
    layout = cave_layout()
    code = _emit_code(section_va + layout["code"], section_va, layout)
    return section_va + layout["verb_table"], code.label_va("pass_hook")


class CampaignArmyVerbsPatch(Patch):
    name = "campaign-army-verbs"
    author = "officialNecro"
    experimental = True
    description = (
        "Restore BFME1's two missing campaign Act verbs. MergePlayerArmy { SourceArmy, DestArmy, "
        "SplitArmyTemplate, SplitArmy, DespawnSource } moves roster entries from one living-world "
        "army to another - all of them, or just the ones a SplitArmyTemplate "
        "LivingWorldPlayerArmy names - and DespawnArmy = <name> removes an army from the world "
        "map. SourceArmy and DestArmy are SpawnArmy ScriptingNames, not PlayerArmy names as they "
        "were in BFME1, because in ROTWK the live army's roster is the state and the template is "
        f"only its seed. Up to {RECORD_CAPACITY} entries across the campaign, names up to "
        f"{NAME_CAPACITY - 1} characters"
    )

    def apply(self, data: bytearray) -> None:
        stock = self._stock_table(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: build_cave(base, stock), _CHARACTERISTICS
        )
        table_va, pass_hook = _hook_targets(section_va)

        off = self._offset(data, ACT_VERB_TABLE_PUSH_SITE)
        apply_byte_patch(
            data,
            off,
            ACT_VERB_TABLE_PUSH_SITE_BYTES,
            b"\x68" + _u32(table_va),
            "the Act verb table -> campaign-army-verbs cave",
        )

        off = self._offset(data, ACT_RUN_PASS9_CALL)
        apply_byte_patch(
            data,
            off,
            ACT_RUN_PASS9_CALL_BYTES,
            b"\xe8" + struct.pack("<i", pass_hook - (ACT_RUN_PASS9_CALL + 5)),
            "act runner pass 9 -> campaign-army-verbs cave",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _stock_table(cls, data: bytes | bytearray) -> bytes:
        """The stock verb table, asserted before it is copied.

        The copy is only as good as what it copies: a build whose table has moved, grown or holds
        different parsers has to fail here rather than have fifteen wrong rows relocated into a
        cave and pushed at the parser."""
        off = cls._offset(data, ACT_VERB_TABLE)
        got = bytes(data[off : off + len(ACT_VERB_TABLE_BYTES)])
        if got != ACT_VERB_TABLE_BYTES:
            raise ValueError(
                f"the Act verb table at {ACT_VERB_TABLE:#010x} is not this build's "
                f"({got[:16].hex()}...) - refusing to relocate it"
            )
        return got

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        table_va, pass_hook = _hook_targets(section_va)

        off = self._offset(data, ACT_VERB_TABLE_PUSH_SITE)
        if data[off] != 0x68:
            problems.append(f"{ACT_VERB_TABLE_PUSH_SITE:#010x} is not a push - the table is stock")
        else:
            pushed = struct.unpack_from("<I", data, off + 1)[0]
            if pushed != table_va:
                problems.append(
                    f"{ACT_VERB_TABLE_PUSH_SITE:#010x} pushes {pushed:#010x}, "
                    f"expected {table_va:#010x}"
                )

        off = self._offset(data, ACT_RUN_PASS9_CALL)
        if data[off] != 0xE8:
            problems.append(f"{ACT_RUN_PASS9_CALL:#010x} is not a call - the hook is not installed")
        else:
            target = ACT_RUN_PASS9_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != pass_hook:
                problems.append(
                    f"{ACT_RUN_PASS9_CALL:#010x} calls {target:#010x}, expected {pass_hook:#010x}"
                )

        cave = build_cave(section_va)
        # The record table is written at run time, so only the parts that never change are
        # compared: everything from the verb table on.
        layout = cave_layout()
        start = layout["verb_table"]
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
        """The verb block, where it may be written, and the field `DespawnArmy` becomes on an Act.

        `MergePlayerArmy` needs both a block type and a place to appear: registering the type says
        it exists, and nesting it under `Act` is what stops every use being reported as an unknown
        attribute of the act it is written in."""
        return Engine(
            blocks=(BlockDelta(_MERGE_VERB, base="NestedAttribute", patch=self.name),),
            nested=(NestedDelta("Act", _MERGE_VERB, patch=self.name),),
            fields=(
                FieldDelta("Act", _DESPAWN_VERB, "Opaque", None, self.name),
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
            ),
        )
