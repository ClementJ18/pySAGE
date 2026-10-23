"""Let an AI-owned building plot build its own building, and rebuild it after a delay.

The skirmish AI only builds what a build list names: an `AIBase` layout for its start castle, or a
library script naming a slot. An outpost or camp unpacked mid-match has neither, so its plots stay
empty. Three fields on `FoundationAIUpdate` change that for the plots that ask:

    Behavior = FoundationAIUpdate ModuleTag_foundationAI
        AIAutoBuild         = Yes
        AIInitialBuildDelay = 2000      ; ms from the plot first standing empty
        AIRebuildDelay      = 60000     ; ms from the plot's building dying (or being sold)
    End

While the plot is empty and its owner is a computer player, the plot's update walks its current
command set (a `CommandSetUpgrade` override included) and presses the first `FOUNDATION_CONSTRUCT`
button the engine's own production gate accepts. The press goes through
`BuildAssistant::buildObjectNow` with the plot as constructor - the call the AI's own structure
requests make - so the building goes up as a construction site, is paid for the way a plot build
is paid for, and takes the plot. A plot whose owner is human, or that does not declare
`AIAutoBuild`, is stock.

Derivation: `../docs/ai-plot-autobuild.md`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    BUILD_OBJECT_NOW,
    BUILD_OBJECT_NOW_PROLOGUE,
    BUILD_OBJECT_NOW_SLOT,
    CAN_MAKE_RESULT_OK,
    CAN_MAKE_UNIT_PRODUCTION_GATE,
    CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_OBJECT,
    COMMAND_FOUNDATION_CONSTRUCT,
    COMMAND_SET_STORE_FIND_COMMAND_SET,
    FIELD_PARSE_STRIDE,
    FOUNDATION_AI_ALLOC,
    FOUNDATION_AI_ALLOC_BYTES,
    FOUNDATION_AI_ALLOC_RESUME,
    FOUNDATION_AI_CTOR_CALL,
    FOUNDATION_AI_CTOR_CALL_BYTES,
    FOUNDATION_AI_CTOR_VTABLE_STORE,
    FOUNDATION_AI_CTOR_VTABLE_STORE_BYTES,
    FOUNDATION_AI_DATA_ALLOC,
    FOUNDATION_AI_DATA_ALLOC_BYTES,
    FOUNDATION_AI_DATA_ALLOC_RESUME,
    FOUNDATION_AI_FIELD_TABLE,
    FOUNDATION_AI_FIELD_TABLE_REF,
    FOUNDATION_AI_FIELD_TABLE_REF_OPCODE,
    FOUNDATION_AI_INSTANCE_SIZE,
    FOUNDATION_AI_MODULE_DATA_SIZE,
    FOUNDATION_AI_STOCK_FIELDS,
    FOUNDATION_AI_UPDATE_BUILT_ON,
    FOUNDATION_AI_UPDATE_JOIN,
    FOUNDATION_AI_UPDATE_JOIN_BYTES,
    FOUNDATION_AI_UPDATE_JOIN_RESUME,
    FOUNDATION_AI_UPDATE_JOIN_RESUME_BYTES,
    FOUNDATION_AI_UPDATE_THIS_DELTA,
    FOUNDATION_AI_VTABLE,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    GAME_LOGIC_FRAME,
    INI_PARSE_BOOL,
    INI_PARSE_DURATION,
    OBJECT_ANGLE,
    OBJECT_GET_COMMAND_SET_STRING,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_ID,
    OBJECT_POSITION,
    OPERATOR_NEW,
    PLAYER_TYPE,
    PLAYER_TYPE_HUMAN,
    THE_BUILD_ASSISTANT,
    THE_COMMAND_SET_STORE,
    THE_GAME_LOGIC,
)
from ..asm import JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    find_section,
    i8,
    read_cstring,
    u32,
    va_to_offset,
)

__all__ = [
    "ANCHORS",
    "AUTO_BUILD_OFFSET",
    "AiPlotAutobuildPatch",
    "BUTTON_SLOTS",
    "INITIAL_DELAY_OFFSET",
    "KEYWORDS",
    "MODULE_DATA_SIZE",
    "INSTANCE_SIZE",
    "NEXT_FRAME_OFFSET",
    "REBUILD_DELAY_OFFSET",
    "SECTION_NAME",
    "STATE_OFFSET",
    "THROTTLE_MASK",
    "build_section",
    "layout",
]

SECTION_NAME = ".plotbld"  # 8 chars exactly: the PE name field is 8 bytes and truncates silently

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds the keyword strings and
# the rebuilt field table beside the stubs, and nothing in it is written at runtime.
_CHARACTERISTICS = 0x60000060

KEYWORDS = ("AIAutoBuild", "AIRebuildDelay", "AIInitialBuildDelay")

#: The grown `ModuleData`: the opt-in byte, then both delays in logic frames (the duration parser
#: turns the authored milliseconds into frames). Zeroed by the allocator stub, which is what makes
#: every plot that declares none of the keywords stock.
AUTO_BUILD_OFFSET = FOUNDATION_AI_MODULE_DATA_SIZE  # +0x10, Bool
REBUILD_DELAY_OFFSET = FOUNDATION_AI_MODULE_DATA_SIZE + 4  # +0x14, frames
INITIAL_DELAY_OFFSET = FOUNDATION_AI_MODULE_DATA_SIZE + 8  # +0x18, frames
MODULE_DATA_SIZE = FOUNDATION_AI_MODULE_DATA_SIZE + 0x10

#: The grown instance: the frame the next build may start, and the plot's state - 0 never seen
#: empty, 1 seen occupied, 2 empty with the timer armed. Zeroed by the allocator stub. Not saved
#: with the game: a loaded plot starts at 0 and waits its initial delay again.
NEXT_FRAME_OFFSET = FOUNDATION_AI_INSTANCE_SIZE  # +0x30
STATE_OFFSET = FOUNDATION_AI_INSTANCE_SIZE + 4  # +0x34
INSTANCE_SIZE = FOUNDATION_AI_INSTANCE_SIZE + 8
_STATE_FRESH, _STATE_OCCUPIED, _STATE_ARMED = 0, 1, 2

#: One build attempt per plot every eight logic frames (1.6 s at 5 Hz), staggered by object id so
#: an outpost's plots do not all walk their sets on the same frame.
THROTTLE_MASK = 7

#: How many command-set slots the walk visits: the stock 33. A plot's build buttons sit in the
#: first few, and `CommandSet+0x14` holds at least that many under `commandset-limit` too.
BUTTON_SLOTS = 33
_COMMAND_SET_BUTTONS = 0x14

#: Offsets from the `UpdateModule` subobject `update` is entered with.
_BASE = -FOUNDATION_AI_UPDATE_THIS_DELTA
_DATA = _BASE + 4
_OBJECT = _BASE + 8
_NEXT = NEXT_FRAME_OFFSET - FOUNDATION_AI_UPDATE_THIS_DELTA
_STATE = STATE_OFFSET - FOUNDATION_AI_UPDATE_THIS_DELTA

#: The first bytes of every engine function the stubs call or rejoin, plus the two stores that pin
#: the instance size and the vtable the update stub tests for. The edited sites' own bytes are
#: asserted by `apply_byte_patch`.
ANCHORS = {
    FOUNDATION_AI_CTOR_CALL: FOUNDATION_AI_CTOR_CALL_BYTES,
    FOUNDATION_AI_CTOR_VTABLE_STORE: FOUNDATION_AI_CTOR_VTABLE_STORE_BYTES,
    FOUNDATION_AI_UPDATE_JOIN_RESUME: FOUNDATION_AI_UPDATE_JOIN_RESUME_BYTES,
    GAME_LOGIC_FIND_OBJECT_BY_ID: GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    BUILD_OBJECT_NOW: BUILD_OBJECT_NOW_PROLOGUE,
    CAN_MAKE_UNIT_PRODUCTION_GATE: bytes.fromhex("558bec515156578b"),
    OBJECT_GET_COMMAND_SET_STRING: bytes.fromhex("568bf1578dbe"),
    OBJECT_GET_CONTROLLING_PLAYER: bytes.fromhex("8b891c030000"),
    COMMAND_SET_STORE_FIND_COMMAND_SET: bytes.fromhex("558bec"),
    OPERATOR_NEW: bytes.fromhex("8b4424046a00"),
}


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits. Strings first, so they read back off the section base."""

    keyword_vas: tuple[int, ...]
    table_va: int
    alloc_va: int
    data_alloc_va: int
    update_va: int


def layout(base_va: int) -> _Layout:
    vas = []
    va = base_va
    for name in KEYWORDS:
        vas.append(va)
        va += len(name) + 1
    table_va = va + (-va % 4)
    alloc_va = table_va + (len(FOUNDATION_AI_STOCK_FIELDS) + len(KEYWORDS) + 1) * FIELD_PARSE_STRIDE
    data_alloc_va = alloc_va + len(_build_alloc(alloc_va))
    update_va = data_alloc_va + len(_build_data_alloc(data_alloc_va))
    return _Layout(tuple(vas), table_va, alloc_va, data_alloc_va, update_va)


def _build_table(keyword_vas: tuple[int, ...], stock_rows: bytes) -> bytes:
    """The stock rows verbatim, the three new ones, the terminator."""
    rows = (
        (keyword_vas[0], INI_PARSE_BOOL, AUTO_BUILD_OFFSET),
        (keyword_vas[1], INI_PARSE_DURATION, REBUILD_DELAY_OFFSET),
        (keyword_vas[2], INI_PARSE_DURATION, INITIAL_DELAY_OFFSET),
    )
    new = b"".join(struct.pack("<IIII", name, parse, 0, offset) for name, parse, offset in rows)
    return stock_rows + new + bytes(FIELD_PARSE_STRIDE)


def _build_zeroing_alloc(base_va: int, size: int, first: int, dwords: int, resume: int) -> bytes:
    """`push <size> / call operator new`, then zero `dwords` dwords from `first`.

    Entered in place of the allocator's own `push / call`, and leaves what they left: the block in
    `eax` and the size still pushed, for the `pop ecx` the caller rejoins at. `operator new` hands
    back whatever was in the heap, so the zeroing is what gives the new fields their defaults."""
    a = Asm(base_va)
    a.emit(0x68, u32(size))  # push size
    a.call_absolute(OPERATOR_NEW)  # call operator new  ; cdecl, the push stays for the caller
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "done")
    for index in range(dwords):
        a.emit(0xC7, 0x40, first + 4 * index, u32(0))  # mov dword [eax+off], 0
    a.label("done")
    a.jmp_absolute(resume)
    return a.finish()


def _build_alloc(base_va: int) -> bytes:
    return _build_zeroing_alloc(
        base_va, INSTANCE_SIZE, NEXT_FRAME_OFFSET, 2, FOUNDATION_AI_ALLOC_RESUME
    )


def _build_data_alloc(base_va: int) -> bytes:
    return _build_zeroing_alloc(
        base_va, MODULE_DATA_SIZE, AUTO_BUILD_OFFSET, 4, FOUNDATION_AI_DATA_ALLOC_RESUME
    )


def _build_update(base_va: int) -> bytes:
    """The plot's tick, before the occupancy poll: track the plot's state, and build when due.

    Entered by the jump at `FOUNDATION_AI_UPDATE_JOIN` with `esi` = the `UpdateModule` subobject.
    Everything is saved around the body, which then re-executes the two displaced instructions -
    so the stock tick sees the registers and flags it always did, and an `Object` this stub just
    built on the plot is what the occupancy poll right behind it finds."""
    a = Asm(base_va)
    a.emit(0x60)  # pushad
    a.emit(0x81, 0x7E, i8(_BASE), u32(FOUNDATION_AI_VTABLE))  # cmp [esi-0x10], FoundationAIUpdate
    a.jcc(JNE, "out")  # a CastleBehavior: its fields past +0x30 are its own
    a.emit(0x8B, 0x5E, i8(_DATA))  # mov ebx, [esi-0xc]      ; ModuleData
    a.emit(0x80, 0x7B, AUTO_BUILD_OFFSET, 0x00)  # cmp byte [ebx+0x10], 0
    a.jcc(JE, "out")  # no AIAutoBuild: stock
    a.emit(0x8B, 0x7E, i8(_OBJECT))  # mov edi, [esi-8]        ; the plot

    # Occupied: the built-on id resolves. Remember it, so the plot's next empty tick starts the
    # rebuild delay.
    a.emit(0x8B, 0x46, FOUNDATION_AI_UPDATE_BUILT_ON)  # mov eax, [esi+0x18]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "empty")
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0x0D, u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(GAME_LOGIC_FIND_OBJECT_BY_ID)  # thiscall, ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "empty")
    a.emit(0xC6, 0x46, _STATE, _STATE_OCCUPIED)  # mov byte [esi+0x24], 1
    a.jmp("out")

    a.label("empty")
    a.emit(0x8B, 0x0D, u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x8B, 0x51, GAME_LOGIC_FRAME)  # mov edx, [ecx+0x40]     ; now
    a.emit(0x80, 0x7E, _STATE, _STATE_ARMED)  # cmp byte [esi+0x24], 2
    a.jcc(JE, "armed")
    # First empty tick: arm the timer, with the initial delay for a plot never seen occupied and
    # the rebuild delay for one whose building has just gone.
    a.emit(0x8B, 0x43, INITIAL_DELAY_OFFSET)  # mov eax, [ebx+0x18]
    a.emit(0x80, 0x7E, _STATE, _STATE_FRESH)  # cmp byte [esi+0x24], 0
    a.jcc_short(JE, "arm")
    a.emit(0x8B, 0x43, REBUILD_DELAY_OFFSET)  # mov eax, [ebx+0x14]
    a.label("arm")
    a.emit(0x03, 0xC2)  # add eax, edx
    a.emit(0x89, 0x46, _NEXT)  # mov [esi+0x20], eax
    a.emit(0xC6, 0x46, _STATE, _STATE_ARMED)  # mov byte [esi+0x24], 2
    a.jmp("out")

    a.label("armed")
    a.emit(0x3B, 0x56, _NEXT)  # cmp edx, [esi+0x20]
    a.jcc(JB, "out")  # not yet
    a.emit(0x8B, 0x47, OBJECT_ID)  # mov eax, [edi+0x74]
    a.emit(0x03, 0xC2)  # add eax, edx
    a.emit(0xA8, THROTTLE_MASK)  # test al, 7
    a.jcc(JNE, "out")  # not this plot's frame

    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "out")  # unowned
    a.emit(0x83, 0x78, PLAYER_TYPE, PLAYER_TYPE_HUMAN)  # cmp dword [eax+0x5c], 0
    a.jcc(JE, "out")  # a human's plot is never built for them
    a.emit(0x8B, 0xD8)  # mov ebx, eax              ; the player, from here on

    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_COMMAND_SET_STRING)  # -> AsciiString *, overrides first
    a.emit(0x8B, 0x0D, u32(THE_COMMAND_SET_STORE))  # mov ecx, [TheControlBar]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "out")
    a.emit(0x50)  # push eax
    a.call_absolute(COMMAND_SET_STORE_FIND_COMMAND_SET)  # thiscall, ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "out")
    a.emit(0x8B, 0xE8)  # mov ebp, eax              ; the CommandSet (pushad saved ebp)
    a.emit(0x33, 0xF6)  # xor esi, esi              ; the slot (pushad saved esi)

    a.label("slot")
    a.emit(0x8B, 0x44, 0xB5, _COMMAND_SET_BUTTONS)  # mov eax, [ebp+esi*4+0x14]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")
    a.emit(0x83, 0x78, COMMAND_BUTTON_COMMAND, COMMAND_FOUNDATION_CONSTRUCT)  # cmp [eax+0x14], 1
    a.jcc(JNE, "next")
    a.emit(0x8B, 0x40, COMMAND_BUTTON_OBJECT)  # mov eax, [eax+0x20]   ; the template
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")
    # The engine's own gate: in the plot's set, affordable, not disabled, under its maximum.
    a.emit(0x50)  # push eax                   ; kept for the build
    a.emit(0x6A, 0xFF)  # push -1               ; no revive slot
    a.emit(0x50)  # push eax
    a.emit(0x57)  # push edi                   ; the plot as producer
    a.emit(0x8B, 0x0D, u32(THE_BUILD_ASSISTANT))  # mov ecx, [TheBuildAssistant]
    a.emit(0x8B, 0x11)  # mov edx, [ecx]
    a.emit(0xFF, 0x52, CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT)  # call [edx+0x64]     ; ret 0xc
    a.emit(0x5A)  # pop edx                    ; the template
    a.emit(0x83, 0xF8, CAN_MAKE_RESULT_OK)  # cmp eax, 0
    a.jcc(JNE, "next")
    # buildObjectNow(plot, template, &plot position, plot angle, player): the AI's own build call,
    # which a BASE_FOUNDATION constructor routes into the plot's build-here.
    a.emit(0x53)  # push ebx                   ; owner
    a.emit(0xFF, 0x77, OBJECT_ANGLE)  # push dword [edi+0x44]   ; angle, a float
    a.emit(0x8D, 0x47, OBJECT_POSITION)  # lea eax, [edi+0x38]
    a.emit(0x50)  # push eax                   ; &position
    a.emit(0x52)  # push edx                   ; template
    a.emit(0x57)  # push edi                   ; constructor
    a.emit(0x8B, 0x0D, u32(THE_BUILD_ASSISTANT))  # mov ecx, [TheBuildAssistant]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, BUILD_OBJECT_NOW_SLOT)  # call [eax+0x38]        ; ret 0x14
    a.jmp("out")

    a.label("next")
    a.emit(0x46)  # inc esi
    a.emit(0x83, 0xFE, BUTTON_SLOTS)  # cmp esi, 33
    a.jcc(JB, "slot")

    a.label("out")
    a.emit(0x61)  # popad
    a.emit(FOUNDATION_AI_UPDATE_JOIN_BYTES)  # mov edi,[esi-8] / test byte [edi+0x458],1
    a.jmp_absolute(FOUNDATION_AI_UPDATE_JOIN_RESUME)  # the je to the occupancy poll
    return a.finish()


def build_section(base_va: int, stock_rows: bytes) -> bytes:
    pieces = layout(base_va)
    blob = bytearray()
    for name in KEYWORDS:
        blob += name.encode("ascii") + b"\x00"
    blob += bytes(pieces.table_va - (base_va + len(blob)))
    blob += _build_table(pieces.keyword_vas, stock_rows)
    assert base_va + len(blob) == pieces.alloc_va, "the cave layout and its addresses disagree"
    blob += _build_alloc(pieces.alloc_va)
    blob += _build_data_alloc(pieces.data_alloc_va)
    blob += _build_update(pieces.update_va)
    return bytes(blob)


def _jump(site: int, target: int, length: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target - (site + 5)) + b"\x90" * (length - 5)


class AiPlotAutobuildPatch(Patch):
    name = "ai-plot-autobuild"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Add AIAutoBuild, AIInitialBuildDelay and AIRebuildDelay to FoundationAIUpdate. An "
        "AI-owned plot that declares AIAutoBuild builds the first building its command set offers "
        "that the AI can afford, through the engine's own plot construction, and builds it again "
        "AIRebuildDelay after it is gone. Human plots and plots without the keyword are stock"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        stock_rows = self._read_stock_table(data)
        base_va = allocate_section(
            data, SECTION_NAME, lambda va: build_section(va, stock_rows), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, layout(base_va)):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located
        pieces = layout(section_va)
        installed = tuple(read_cstring(data, va) for va in pieces.keyword_vas)
        if installed != KEYWORDS:
            return [f"the keywords in {SECTION_NAME} are {installed!r}, not {KEYWORDS!r}"]
        problems: list[str] = []
        try:
            content = build_section(section_va, self._copied_rows(data, pieces))
            edits = self._edits(data, pieces)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]
        if len(content) > vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for this patch's cave"]
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(f"{SECTION_NAME} does not hold the expected table and stubs")
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        problems += self._anchor_problems(data)
        return problems

    def ini_surface(self) -> Engine:
        """The three `FoundationAIUpdate` fields. All default to off / zero, which is stock."""
        return Engine(
            fields=(
                FieldDelta("FoundationAIUpdate", KEYWORDS[0], "Bool", False, self.name),
                FieldDelta("FoundationAIUpdate", KEYWORDS[1], "Int", 0, self.name),
                FieldDelta("FoundationAIUpdate", KEYWORDS[2], "Int", 0, self.name),
            )
        )

    @staticmethod
    def _edits(data: bytes | bytearray, pieces: _Layout) -> list[tuple[int, bytes, bytes, str]]:
        def off(va: int) -> int:
            got = va_to_offset(data, va)
            if got is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            return got

        table_push = bytes((FOUNDATION_AI_FIELD_TABLE_REF_OPCODE,)) + u32(FOUNDATION_AI_FIELD_TABLE)
        return [
            (
                off(FOUNDATION_AI_ALLOC),
                FOUNDATION_AI_ALLOC_BYTES,
                _jump(FOUNDATION_AI_ALLOC, pieces.alloc_va, len(FOUNDATION_AI_ALLOC_BYTES)),
                "FoundationAIUpdate instance allocation -> ai-plot-autobuild (grown, zeroed)",
            ),
            (
                off(FOUNDATION_AI_DATA_ALLOC),
                FOUNDATION_AI_DATA_ALLOC_BYTES,
                _jump(
                    FOUNDATION_AI_DATA_ALLOC,
                    pieces.data_alloc_va,
                    len(FOUNDATION_AI_DATA_ALLOC_BYTES),
                ),
                "FoundationAIUpdate ModuleData allocation -> ai-plot-autobuild (grown, zeroed)",
            ),
            (
                off(FOUNDATION_AI_FIELD_TABLE_REF),
                table_push,
                bytes((FOUNDATION_AI_FIELD_TABLE_REF_OPCODE,)) + u32(pieces.table_va),
                "FoundationAIUpdate field table -> ai-plot-autobuild's rebuilt table",
            ),
            (
                off(FOUNDATION_AI_UPDATE_JOIN),
                FOUNDATION_AI_UPDATE_JOIN_BYTES,
                _jump(
                    FOUNDATION_AI_UPDATE_JOIN,
                    pieces.update_va,
                    len(FOUNDATION_AI_UPDATE_JOIN_BYTES),
                ),
                "FoundationAIUpdate::update join -> ai-plot-autobuild",
            ),
        ]

    @staticmethod
    def _read_stock_table(data: bytes | bytearray) -> bytes:
        off = va_to_offset(data, FOUNDATION_AI_FIELD_TABLE)
        if off is None:
            raise ValueError(f"the field table 0x{FOUNDATION_AI_FIELD_TABLE:08x} is not mapped")
        size = len(FOUNDATION_AI_STOCK_FIELDS) * FIELD_PARSE_STRIDE
        rows = bytes(data[off : off + size])
        for index, (name, field_off) in enumerate(FOUNDATION_AI_STOCK_FIELDS):
            name_va, _parse, _user, got_off = struct.unpack_from(
                "<4I", rows, index * FIELD_PARSE_STRIDE
            )
            got = read_cstring(data, name_va)
            if got != name or got_off != field_off:
                raise ValueError(
                    f"field table row {index}: expected {name!r} at 0x{field_off:x}, "
                    f"found {got!r} at 0x{got_off:x}"
                )
        if bytes(data[off + size : off + size + FIELD_PARSE_STRIDE]) != bytes(FIELD_PARSE_STRIDE):
            raise ValueError("the FoundationAIUpdate field table has more rows than expected")
        return rows

    @staticmethod
    def _copied_rows(data: bytes | bytearray, pieces: _Layout) -> bytes:
        off = va_to_offset(data, pieces.table_va)
        if off is None:
            raise ValueError(f"the rebuilt table at 0x{pieces.table_va:08x} is not mapped")
        return bytes(data[off : off + len(FOUNDATION_AI_STOCK_FIELDS) * FIELD_PARSE_STRIDE])

    @staticmethod
    def _anchor_problems(data: bytes | bytearray) -> list[str]:
        problems = []
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"0x{va:08x} is not mapped")
                continue
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                problems.append(f"0x{va:08x} holds {got.hex()}, expected {expected.hex()}")
        return problems

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        problems = cls._anchor_problems(data)
        if problems:
            raise ValueError(
                "ai-plot-autobuild: this is not the build the patch was written for - "
                + "; ".join(problems)
            )
