"""The AI hero build delay: `HeroBuildOrder` entries may name a time before which the skirmish
AI will not consider recruiting that hero.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/ai-hero-build-delay.md``.

**The defect.** `HeroBuildOrder` is a bare list of hero names, and the skirmish AI's hero builder
treats it as one. It copies the list off the faction's `ArmyDefinition` (`+0x8C` into its own
`+0x4C`), and its picker has three rules: retry an index it already asked for, otherwise
``GameLogicRandomValue(1, count-1)`` - a **uniform draw over the whole list** - and otherwise the
Ring hero when the player holds the Ring. There is no cost term in the choice and no clock
anywhere on the path.

The only thing between the AI and the most expensive hero in the list is the affordability test at
``AI_HERO_COST_TEST``, and that is not a policy: it asks whether the purse covers the hero *right
now*, so the AI saves until it does and then spends everything at once. What a player sees is an
AI that draws Gandalf on minute three, stops producing units while it banks for him, and arrives
with one hero and no army - or, on a longer game, banks repeatedly for heroes it cannot support.
The build **order** the keyword is named for is not an order at all.

**What this does.** Teaches the keyword one optional suffix. A token stays a bare ``Name``, or
becomes ``Name:Seconds`` - the number of seconds from the start of the match before the AI may
consider recruiting that hero:

    HeroBuildOrder = MordorSauron_RingHero MordorWitchKing:420 MordorFellBeast:600

A hero on the clock is **skipped, not blocked**: the gate hands it to the engine's own rejection
edge, which forgets the choice so the next tick draws again, and the whole rest of the list stays
reachable meanwhile. And a hero request that answers null is not a wasted tick either - the AI's
order pump runs its **unit** builder in the same call, so the money goes into an army instead.

**Two edits, and why they are in those two places.**

1. The `HeroBuildOrder` **row** of the `ArmyDefinition` field table is repointed at a replacement
   parser. The row, not the parse function it names: `INI_PARSE_STRING_LIST` is shared with
   `OffensiveBuildings` and `ScavangedResourceBuildings`, and neither of those wants a colon to
   mean anything. The replacement calls the stock parser and then walks the vector it filled,
   splitting each ``Name:Seconds`` in place - the name is written back through
   `AsciiString::set`, and the seconds are recorded in a table the cave owns.

   Splitting at **parse** time rather than at use time is what keeps the change to one gate: the
   name resolves through `TheThingFactory`, is interned as a `NameKey`, is compared against the
   AI's already-queued list, is xfered into save games and is folded into the per-frame CRC, and
   every one of those sees exactly the string a stock build would have seen.

2. `AI_HERO_NAME_RESOLVED`, the six bytes between "the hero's name is resolved" and "its template
   is looked up", is redirected into the gate. That is the last point in
   `createHeroBuildRequest` before anything is committed - no queue entry, no cost withdrawal,
   not even a producer search.

**Why the delay is keyed by name.** The gate holds the hero's `AsciiString` and nothing else; the
list it came from is a copy. So a recorded delay is keyed by `NameKey`, the same interning the
builder itself applies to these names. The consequence is a real limit worth stating: a delay is
global to a hero **name**, not to an `ArmyDefinition`, so a hero listed by two factions with two
different delays keeps the last one parsed. Keying on the `ArmyDefinition` would be exact, but
those are re-allocated on every parse of the block and a recycled pointer would hand one faction
another's delay - silently, and only sometimes. A name cannot be recycled.

**A hero with no suffix behaves exactly as it does today.** The parser records nothing for it, and
it also *erases* any delay standing against that name, so re-parsing a `HeroBuildOrder` without
the suffix takes the clock off again rather than leaving a stale one behind. A file that uses no
colons leaves the table empty and every lookup misses, which is stock behaviour instruction for
instruction past the gate.

**Seconds, not frames.** RotWK simulates at five logic frames per second, and the gate reads that
rate from `LOGIC_FRAMES_PER_SECOND` at run time rather than baking it in. Seconds are clamped at
parse time to 0x100000, which is four hundred times longer than any match and keeps the
multiplication inside an `int32`.

**Every peer must run the same patched binary, and the same INI.** Which hero the AI asks for
feeds the per-frame CRC, so a patched and an unpatched client diverge the first time a delay
refuses one - and the strings a patched build stores differ from the ``Name:Seconds`` an unpatched
one would keep, so the divergence starts at load. That is the same requirement
`ai-construction-gate` and `hero-recruit-parallel` carry.

**No Worldbuilder twin.** The editor keeps its own copies of the engine's *name* tables, which is
what makes an added token throw there; this adds no token. Worldbuilder's stock parser stores
``Name:Seconds`` as an uninterpreted string and never reads it.

**Composition.** Order-independent. The cave is allocated past every existing section and
:meth:`verify` finds it by name; the field table is resolved through the two instructions that
name it, so the row is found in whatever table is live. The only engine bytes edited are the six
at `AI_HERO_NAME_RESOLVED` and the one row's parse pointer, and no other bundled patch touches
either - `ai-construction-gate` and `ai-revive-gate` are the two that reach into the same AI, and
they take `AI_PRODUCER_USABLE_TESTS` and `CAN_MAKE_UNIT_REVIVE_BRANCH`.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    AI_HERO_ARMY_DEFINITION_LIST,
    AI_HERO_ARMY_DEFINITION_LIST_BYTES,
    AI_HERO_LIST_ELEMENT,
    AI_HERO_LIST_ELEMENT_BYTES,
    AI_HERO_NAME_RESOLVED,
    AI_HERO_NAME_RESOLVED_BYTES,
    AI_HERO_NAME_RESOLVED_RESUME,
    AI_HERO_PICK_INDEX,
    AI_HERO_PICK_INDEX_CALL,
    AI_HERO_PICK_INDEX_CALL_BYTES,
    AI_HERO_PICK_INDEX_ENTRY,
    AI_HERO_REJECT,
    AI_HERO_REJECT_BYTES,
    AI_HERO_REQUEST,
    AI_HERO_REQUEST_CALL,
    AI_HERO_REQUEST_CALL_BYTES,
    AI_HERO_REQUEST_ENTRY,
    ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES,
    ARMY_DEFINITION_FIELD_TABLE_REFS,
    ASCII_STRING_CHARS_OFFSET,
    ASCII_STRING_SET,
    GAME_LOGIC_FRAME,
    INI_PARSE_STRING_LIST,
    INI_PARSE_STRING_LIST_BYTES,
    LOGIC_FRAMES_PER_SECOND,
    NAME_KEY_FROM_STRING,
    THE_GAME_LOGIC,
    THE_NAME_KEY_GENERATOR,
    THE_THING_FACTORY,
)
from ..asm import JA, JB, JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import ROW_SIZE, entries_before, read_field_table, resolve_table

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "KEYWORD",
    "MAX_SECONDS",
    "SECTION_NAME",
    "SLOTS",
    "TABLE_BYTES",
    "AiHeroBuildDelayPatch",
    "build_code",
    "build_section",
    "layout",
]

SECTION_NAME = ".herodly"  # 8 chars exactly: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable, unlike
# most caves here, because the delay table at the section's base is filled while the INI is read.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The field whose token syntax this patch widens. Not configurable: the split is only correct for
#: a list whose entries are hero names, and only `HeroBuildOrder` is one.
KEYWORD = "HeroBuildOrder"

#: How many distinct hero names may carry a delay. Each costs eight bytes - a `NameKey` and a
#: second count - and the whole table sits at the section's base so the code that follows it lands
#: at a fixed offset. Stock RotWK declares six `HeroBuildOrder` lines and Edain ten; 256 is a
#: ceiling nothing is expected to approach rather than a budget to spend.
SLOTS = 256
_SLOT_SIZE = 8
TABLE_BYTES = SLOTS * _SLOT_SIZE

#: The delay a token may name, in seconds, before the parser clamps it. Four hundred times the
#: length of a long match, and small enough that `seconds * LOGIC_FRAMES_PER_SECOND` cannot leave
#: an `int32`.
MAX_SECONDS = 0x0010_0000

#: The parser's frame. 256 bytes of name buffer, then the seconds it read out of a token.
_BUF = -0x104
_BUF_END = -0x005  # the last byte of the buffer, kept free for the terminator
_SECONDS = -0x108
_FRAME_SIZE = 0x10C

HOOK_VA = AI_HERO_NAME_RESOLVED
HOOK_ORIGINAL = AI_HERO_NAME_RESOLVED_BYTES

#: The first bytes at each address the cave reaches, plus the ones that pin what is being gated.
#: `AI_HERO_ARMY_DEFINITION_LIST` is the load-bearing one: it is the single instruction pair tying
#: the builder's `+0x4C` list to the `HeroBuildOrder` keyword, and without it the gate would be
#: reading an anonymous vector of names. The hook's own six bytes are asserted by
#: `apply_byte_patch`.
ANCHORS = {
    AI_HERO_ARMY_DEFINITION_LIST: AI_HERO_ARMY_DEFINITION_LIST_BYTES,
    AI_HERO_REQUEST: AI_HERO_REQUEST_ENTRY,
    AI_HERO_REQUEST_CALL: AI_HERO_REQUEST_CALL_BYTES,
    AI_HERO_PICK_INDEX: AI_HERO_PICK_INDEX_ENTRY,
    AI_HERO_PICK_INDEX_CALL: AI_HERO_PICK_INDEX_CALL_BYTES,
    AI_HERO_LIST_ELEMENT: AI_HERO_LIST_ELEMENT_BYTES,
    AI_HERO_REJECT: AI_HERO_REJECT_BYTES,
    INI_PARSE_STRING_LIST: INI_PARSE_STRING_LIST_BYTES,
}


def _ebp(disp: int) -> bytes:
    """The `[ebp + disp]` half of a ModRM byte pair, always in the disp32 form.

    Every local here is past a byte's reach, and mixing forms would make the two routines'
    encodings differ for no reason a reader could see.
    """
    return struct.pack("<i", disp)


def _assemble(section_va: int) -> tuple[bytes, int, int]:
    """Return ``(code, parser VA, gate VA)`` for a cave based at ``section_va``.

    The delay table occupies the first :data:`TABLE_BYTES` of the section and the code follows it,
    so the table's address is the section's own and the code's is a fixed offset from it. That
    order is what lets `verify` compare the code without having to know what the table currently
    holds - it is written at run time, and a saved game's worth of INI parsing later it will not
    match what `apply` wrote.
    """
    table = section_va
    table_end = table + TABLE_BYTES
    a = Asm(section_va + TABLE_BYTES)

    parse_va = a.va
    _emit_parser(a, table, table_end)
    gate_va = a.va
    _emit_gate(a, table, table_end)
    return a.finish(), parse_va, gate_va


def _emit_parser(a: Asm, table: int, table_end: int) -> None:
    """`__cdecl parse(ini, instance, store, userData)` - the replacement for the `HeroBuildOrder`
    row.

    Runs the stock list parser first, so token splitting, macro expansion and the vector's own
    housekeeping stay the engine's; then walks what it produced. Every element is either plain -
    in which case any delay standing against that name is erased - or carries a ``:Seconds``
    suffix, in which case the name is written back without it and the seconds are recorded.
    """
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x81, 0xEC, struct.pack("<I", _FRAME_SIZE))  # sub esp, 0x10c
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi

    # The stock parser, with this call's own four arguments. Caller-cleaned, like every row.
    a.emit(0xFF, 0x75, 0x14)  # push [ebp+0x14]   userData
    a.emit(0xFF, 0x75, 0x10)  # push [ebp+0x10]   store
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0x0c]   instance
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+0x08]   ini
    a.call_absolute(INI_PARSE_STRING_LIST)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10

    a.emit(0x8B, 0x75, 0x10)  # mov esi, [ebp+0x10]   ; store == &vector<AsciiString>
    a.emit(0x8B, 0x1E)  # mov ebx, [esi]        ; begin

    a.label("each")
    a.emit(0x3B, 0x5E, 0x04)  # cmp ebx, [esi+4]
    a.jcc(JE, "done")
    a.emit(0x83, 0xA5, _ebp(_SECONDS), 0x00)  # and dword [ebp-0x108], 0   ; no delay yet
    a.emit(0x8B, 0x03)  # mov eax, [ebx]        ; AsciiStringData*
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")  # an empty entry has no name to key on
    a.emit(0x8D, 0x78, ASCII_STRING_CHARS_OFFSET)  # lea edi, [eax+8]   ; the characters
    a.emit(0x8B, 0xD7)  # mov edx, edi

    a.label("scan")
    a.emit(0x8A, 0x0A)  # mov cl, [edx]
    a.emit(0x84, 0xC9)  # test cl, cl
    a.jcc(JE, "record")  # no colon: the name is the whole token and carries no delay
    a.emit(0x80, 0xF9, 0x3A)  # cmp cl, ':'
    a.jcc(JE, "split")
    a.emit(0x42)  # inc edx
    a.jmp("scan")

    # edi is the first character and edx the colon. Copy the name out, bounded by the buffer, so
    # the terminator always has somewhere to go.
    a.label("split")
    a.emit(0x8D, 0x85, _ebp(_BUF))  # lea eax, [ebp-0x104]
    a.label("copy")
    a.emit(0x3B, 0xFA)  # cmp edi, edx
    a.jcc(JE, "copied")
    a.emit(0x8A, 0x0F)  # mov cl, [edi]
    a.emit(0x88, 0x08)  # mov [eax], cl
    a.emit(0x47)  # inc edi
    a.emit(0x40)  # inc eax
    a.emit(0x8D, 0x4D, struct.pack("<b", _BUF_END))  # lea ecx, [ebp-5]
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JB, "copy")
    a.label("copied")
    a.emit(0xC6, 0x00, 0x00)  # mov byte [eax], 0

    # The digits after the colon, saturating rather than wrapping. A token whose suffix is not a
    # number reads as zero seconds, which is the same as having written no suffix at all.
    a.emit(0x42)  # inc edx
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("digits")
    a.emit(0x0F, 0xB6, 0x0A)  # movzx ecx, byte [edx]
    a.emit(0x83, 0xE9, 0x30)  # sub ecx, '0'
    a.emit(0x83, 0xF9, 0x09)  # cmp ecx, 9        ; unsigned: anything below '0' wrapped high
    a.jcc(JA, "parsed")
    a.emit(0x6B, 0xC0, 0x0A)  # imul eax, eax, 10
    a.emit(0x03, 0xC1)  # add eax, ecx
    a.emit(0x3D, struct.pack("<I", MAX_SECONDS))  # cmp eax, MAX_SECONDS
    a.jcc(JBE, "digit")
    a.emit(0xB8, struct.pack("<I", MAX_SECONDS))  # mov eax, MAX_SECONDS
    a.label("digit")
    a.emit(0x42)  # inc edx
    a.jmp("digits")

    a.label("parsed")
    a.emit(0x89, 0x85, _ebp(_SECONDS))  # mov [ebp-0x108], eax
    a.emit(0x8D, 0x85, _ebp(_BUF))  # lea eax, [ebp-0x104]
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCB)  # mov ecx, ebx           ; the element itself
    a.call_absolute(ASCII_STRING_SET)  # the stored name loses the suffix

    # Interned the way the builder interns it, so the key taken here is the key the gate computes.
    a.label("record")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
    a.emit(0x53)  # push ebx
    a.call_absolute(NAME_KEY_FROM_STRING)  # eax = NameKey, ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")  # key 0 is the empty slot's own key: never store one

    # Erase first, unconditionally. That is what makes a re-parse authoritative: a name that has
    # lost its suffix loses its delay with it, rather than keeping the one a previous parse left.
    a.emit(0xB9, struct.pack("<I", table))  # mov ecx, table
    a.label("erase")
    a.emit(0x39, 0x01)  # cmp [ecx], eax
    a.jcc(JNE, "erase_next")
    a.emit(0x83, 0x21, 0x00)  # and dword [ecx], 0
    a.emit(0x83, 0x61, 0x04, 0x00)  # and dword [ecx+4], 0   ; a free slot reads as zero seconds
    a.label("erase_next")
    a.emit(0x83, 0xC1, _SLOT_SIZE)  # add ecx, 8
    a.emit(0x81, 0xF9, struct.pack("<I", table_end))  # cmp ecx, table_end
    a.jcc(JB, "erase")

    a.emit(0x8B, 0x95, _ebp(_SECONDS))  # mov edx, [ebp-0x108]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "next")  # no suffix, or `:0`: erased is all this token asks for

    a.emit(0xB9, struct.pack("<I", table))  # mov ecx, table
    a.label("free")
    a.emit(0x83, 0x39, 0x00)  # cmp dword [ecx], 0
    a.jcc(JE, "claim")
    a.emit(0x83, 0xC1, _SLOT_SIZE)  # add ecx, 8
    a.emit(0x81, 0xF9, struct.pack("<I", table_end))  # cmp ecx, table_end
    a.jcc(JB, "free")
    a.jmp("next")  # a full table drops the delay rather than displacing somebody else's
    a.label("claim")
    a.emit(0x89, 0x01)  # mov [ecx], eax
    a.emit(0x89, 0x51, 0x04)  # mov [ecx+4], edx

    a.label("next")
    a.emit(0x83, 0xC3, 0x04)  # add ebx, 4
    a.jmp("each")

    a.label("done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret          ; __cdecl, like every field-table row


def _emit_gate(a: Asm, table: int, table_end: int) -> None:
    """The delay gate. Reached only from the hook, and never returns to it.

    On entry ``edi`` is the chosen hero's `AsciiString`, ``eax`` its index in the build order -
    live, because the stock code stores it one instruction after the site - and ``esi`` the hero
    builder. Both exits are edges the stock function already had.
    """
    a.emit(0x50)  # push eax                 ; the index survives the lookup
    a.emit(0x57)  # push edi                 ; &AsciiString
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
    a.call_absolute(NAME_KEY_FROM_STRING)  # eax = NameKey, ret 4

    a.emit(0xB9, struct.pack("<I", table))  # mov ecx, table
    a.label("lookup")
    a.emit(0x39, 0x01)  # cmp [ecx], eax
    a.jcc(JE, "hit")
    a.emit(0x83, 0xC1, _SLOT_SIZE)  # add ecx, 8
    a.emit(0x81, 0xF9, struct.pack("<I", table_end))  # cmp ecx, table_end
    a.jcc(JB, "lookup")
    a.emit(0x58)  # pop eax
    a.jmp("allow")  # no delay recorded: stock, instruction for instruction

    # A free slot holds zero seconds, so a key that matched one - which is only the empty string's
    # key - answers "no delay" here rather than needing a test of its own.
    a.label("hit")
    a.emit(0x8B, 0x41, 0x04)  # mov eax, [ecx+4]              ; seconds
    a.emit(0x0F, 0xAF, 0x05, struct.pack("<I", LOGIC_FRAMES_PER_SECOND))  # imul eax, [logic rate]
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x39, 0x41, GAME_LOGIC_FRAME)  # cmp [ecx+0x40], eax
    a.emit(0x58)  # pop eax                       ; pop leaves the flags alone
    a.jcc(JB, "blocked")

    a.label("allow")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_THING_FACTORY))  # the displaced instruction
    a.jmp_absolute(AI_HERO_NAME_RESOLVED_RESUME)

    a.label("blocked")
    a.jmp_absolute(AI_HERO_REJECT)


def build_code(section_va: int) -> bytes:
    """The cave's code, for a section based at ``section_va``. The delay table precedes it."""
    return _assemble(section_va)[0]


def layout(section_va: int) -> tuple[int, int]:
    """``(parser VA, gate VA)`` for a section based at ``section_va``."""
    return _assemble(section_va)[1:]


def build_section(section_va: int) -> bytes:
    """The whole section: the zeroed delay table, then the code."""
    return b"\x00" * TABLE_BYTES + build_code(section_va)


class AiHeroBuildDelayPatch(Patch):
    name = "ai-hero-build-delay"
    author = "officialNecro"
    description = (
        "Let a HeroBuildOrder entry carry a delay, as Name:Seconds, before which the skirmish AI "
        "will not consider recruiting that hero - so it stops banking its whole purse for an "
        "expensive hero in the opening minutes. A bare Name behaves exactly as it does today"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        row_off = self._row_parse_offset(data)

        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        parse_va, gate_va = layout(section_va)

        # Six stock bytes, five for the jump and one to bury the tail of the instruction it
        # replaces so a disassembler does not walk into its remains.
        jump = b"\xe9" + struct.pack("<i", gate_va - (HOOK_VA + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "AI hero request name lookup -> ai-hero-build-delay gate",
        )
        apply_byte_patch(
            data,
            row_off,
            struct.pack("<I", INI_PARSE_STRING_LIST),
            struct.pack("<I", parse_va),
            f"ArmyDefinition {KEYWORD} row -> ai-hero-build-delay parser",
        )

    @staticmethod
    def _row_parse_offset(data: bytes | bytearray) -> int:
        """The file offset of the `HeroBuildOrder` row's parse pointer, in whatever
        `ArmyDefinition` table is live."""
        table_va = resolve_table(
            data,
            ARMY_DEFINITION_FIELD_TABLE_REFS,
            ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES,
            "ArmyDefinition",
        )
        preceding = entries_before(data, read_field_table(data, table_va), KEYWORD)
        if preceding is None:
            raise ValueError(f"the live ArmyDefinition table does not name {KEYWORD!r}")
        off = va_to_offset(data, table_va + len(preceding) * ROW_SIZE + 4)
        if off is None:
            raise ValueError("the ArmyDefinition table is not fully mapped")
        return off

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the AI's hero "
                    "builder is not this build's, so the gate would jump into the wrong place"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        parse_va, gate_va = layout(section_va)
        problems: list[str] = []

        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            return [f"{HOOK_VA:#010x} is not a jmp - the hook is not installed"]
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != gate_va:
            problems.append(f"hook jumps to {target:#010x}, expected {gate_va:#010x}")

        try:
            row_off = self._row_parse_offset(data)
        except (ValueError, struct.error) as exc:
            return [*problems, f"cannot read back the ArmyDefinition table: {exc}"]
        row = struct.unpack_from("<I", data, row_off)[0]
        if row != parse_va:
            problems.append(
                f"the {KEYWORD} row parses through {row:#010x}, expected {parse_va:#010x}"
            )

        # Only the code is compared. The delay table sits ahead of it and is written while the
        # engine reads its INI, so on a binary that has been run it holds whatever that run left.
        code = build_code(section_va)
        start = section_off + TABLE_BYTES
        if bytes(data[start : start + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected code")
        return problems

    def ini_surface(self) -> Engine:
        """`HeroBuildOrder` as a list of raw tokens rather than of object references: an entry is
        ``Name`` *or* ``Name:Seconds``, and the second form is not a name anything could be looked
        up by. No default is stated - the keyword's own default is unchanged, and so is what a
        list of bare names means."""
        return Engine(fields=(FieldDelta("ArmyDefinition", KEYWORD, "Opaque[]", None, self.name),))
