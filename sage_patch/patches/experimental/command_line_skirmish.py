"""The command-line-skirmish patch: make `-file <map>.map` start a game worth playing, and let
`-gameInfo` say which game.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/game-info.md``; this module implements the recipe §6 records and the launch
settings §7 reads out of the engine's own lobby parser.

**The gap.** `-file <map>.map` is a stock command line and it already skips every menu: the engine
appends `MSG_NEW_GAME`, builds a `SkirmishGameInfo` and asks for game mode 2. What it does *not* do
is configure the game. Slot 0 gets state 6 and the name "Test" with a **random** faction
(`-2`), no colour, no team and no start position; slots 1-7 are closed; the options block is left
at `-1` throughout; and `TheGameInfo` - which `GameLogic::update` reads every frame - is never
pointed at the object the auto-start filled. The result loads nothing, plays nothing and faults.

**What this does.** Four things, at the point the engine has finished building the `GameInfo` and
before it asks for the game mode:

1. **Fills the slots with a default match.** Slot 0 becomes a local human of a chosen faction and
   slot 1 an easy AI of another, each with a colour, a team and a start position - and each with
   the `AsciiString` at `GAME_SLOT_MAP_PLAYER` naming `Player_<startPos + 1>`, which is what binds
   a seat to the map-side player owning the pre-placed objects at that start position. The strings
   live in this patch's own section with a saturated refcount, so nothing the engine does can free
   them.
2. **Sets the options block**, starting resources included. Left unset every player begins on
   4999 - one short of a fortress - so the human can never unpack a base and the match ends in
   defeat inside thirty frames.
3. **Applies `-gameInfo <string>` when the command line carries one.** The string is the lobby's
   own format - the one a replay header and `Skirmish.ini` hold - and the engine already parses
   it, in `ParseAsciiStringToGameInfo` (`GAME_INFO_PARSE`). The cave finds the switch by walking
   `GameEngine::init`'s own `argv`, which is still in the frame the hook runs in, so the
   command-line table is left alone and `headless`, which rewrites that table, composes. Seats, AI
   difficulty, teams, colours, start positions, the ten `GR` rules and the seed come from the
   string. The map identity does not: the parser will not commit without `M`, `MC` and `MS`, but
   the map the engine is loading is the one `-file` named, so the cave saves what the auto-start
   set and puts it back afterwards - and `GSID`, `SI` and the contents mask with it. The parser's
   freshly built slots carry no map player, so every seated slot is then bound to
   `Player_<startPos + 1>` again. The parser is all-or-nothing: a string it rejects commits
   nothing, and the default match from (1) stands. Which of those happened is written to the
   section at `STATUS_OFFSET`.
4. **Points `TheGameInfo` at `TheSkirmishGameInfo`**, exactly as the skirmish setup screen does at
   `0x006309BF`. Without it `GameLogic::update` dereferences null on frame 1.

A fifth edit is elsewhere: the loading screen's progress update at `LOADING_SCREEN_PROGRESS`
dereferences a window only the shell creates. This patch relocates those twenty-four bytes into
the cave behind a null check, reproducing them exactly when the window exists. The engine already
treats that member as nullable - `0x0081C5C4` is a method whose entire body clears it - so the
guard restores an invariant the unguarded path assumes rather than inventing one.

**The map argument must be spelled `maps\\<name>.map`.** The engine's own path builder inserts the
file's stem as a directory, so that is what produces the `maps\\<name>\\<name>.map` key the map
cache is keyed by; passing the full path makes the builder insert the folder a second time and the
lookup misses, which sends the auto-start down a branch this patch never reaches. See §1 of the
document.

**Faction numbers are indices into the loaded mod's `playertemplate.ini` order**, not a fixed
enum: the defaults here (3 and 10) are Men and Mordor against Edain's table, and a different mod
orders its templates differently. `sage_test.game_info` builds a `-gameInfo` string from seats.

**Status - one run, and it played.** Installed as `game.dat` on an Edain install and started with
`-file maps\\map mp harlindon.map`, nothing else: both seats were created (`Player_1` as Men,
`Player_2` as Mordor, 10000 each), the bases unpacked - the object count went 369 -> 593 -> 721 -
frames advanced past 130, and income was flowing. That is one session against one map on one mod,
which is why this is still `experimental`. **`-gameInfo` has not been run in a game at all**: the
parser's contract is read from the disassembly and the cave is exercised under an emulator, and
that is all.

**Testing this needs the binary named `game.dat`.** A section-modified image only runs under that
name on a retail install - the same bytes renamed die at once with an access violation inside
`msvcr71.dll`, while an *unpatched* copy runs under any name. Copying a patched build somewhere
else to try it out therefore proves nothing.

**Composition.** The cave is allocated past every existing section and `verify` finds it by name.
The engine bytes it edits - nine at the auto-start's tail and twenty-four in the loading screen -
are touched by no other bundled patch.
"""

from __future__ import annotations

import argparse
import struct

from ...addresses import (
    ASCII_STRING_COPY_CTOR,
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    COMMAND_LINE_SKIRMISH_SETUP,
    COMMAND_LINE_SKIRMISH_SETUP_BYTES,
    COMMAND_LINE_SKIRMISH_SETUP_RESUME,
    GAME_ENGINE_INIT_ARGC,
    GAME_ENGINE_INIT_ARGV,
    GAME_INFO_GSID,
    GAME_INFO_MAP,
    GAME_INFO_MAP_CONTENTS_MASK,
    GAME_INFO_MAP_CRC,
    GAME_INFO_MAP_SIZE,
    GAME_INFO_OPTIONS,
    GAME_INFO_PARSE,
    GAME_INFO_PARSE_ENTRY,
    GAME_INFO_PARSE_KEYS,
    GAME_INFO_PARSE_KEYS_BYTES,
    GAME_INFO_SET_MAP,
    GAME_INFO_SET_MAP_CRC,
    GAME_INFO_SET_MAP_SIZE,
    GAME_INFO_SI,
    GAME_INFO_SLOT_ARRAY,
    GAME_INFO_SLOT_COUNT,
    GAME_INFO_STARTING_RESOURCES,
    GAME_MESSAGE_APPEND_INTEGER,
    GAME_SLOT_ACCEPTED,
    GAME_SLOT_COLOR,
    GAME_SLOT_MAP_PLAYER,
    GAME_SLOT_ORIGINAL_COLOR,
    GAME_SLOT_ORIGINAL_PLAYER_TEMPLATE,
    GAME_SLOT_ORIGINAL_START_POS,
    GAME_SLOT_PLAYER_TEMPLATE,
    GAME_SLOT_START_POS,
    GAME_SLOT_START_POS_GRANTED,
    GAME_SLOT_STATE,
    GAME_SLOT_STATE_EASY_AI,
    GAME_SLOT_STATE_LOCAL_HUMAN,
    GAME_SLOT_TEAM,
    LOADING_SCREEN_PROGRESS,
    LOADING_SCREEN_PROGRESS_BYTES,
    LOADING_SCREEN_PROGRESS_REPORT,
    LOADING_SCREEN_PROGRESS_RESUME,
    LOADING_SCREEN_PROGRESS_SINK,
    LOADING_SCREEN_PROGRESS_WINDOW,
    STRICMP,
    THE_GAME_INFO,
    THE_SKIRMISH_GAME_INFO,
)
from ...asm import JAE, JE, JGE, JL, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "DEFAULT_AI_FACTION",
    "DEFAULT_HUMAN_FACTION",
    "DEFAULT_RESOURCES",
    "MAGIC",
    "OPTION",
    "SECTION_NAME",
    "STATUS_APPLIED",
    "STATUS_NOT_GIVEN",
    "STATUS_OFFSET",
    "STATUS_REJECTED",
    "CommandLineSkirmishPatch",
]

SECTION_NAME = ".clskir"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: The cave holds writable data - the `AsciiString` blocks, whose refcount the engine may still
#: touch, the saved map identity and the status word - as well as code, so it is not the read-only
#: cave most patches here allocate.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

#: A header at the section base, so `detect` can recover the parameters a build was made with
#: rather than reporting this version's defaults. Magic, then the three values. The magic changed
#: when `-gameInfo` was added, so a build without it is not reported as carrying this patch.
MAGIC = b"CLS2"
_HEADER = struct.Struct("<4siii")

#: The switch the cave looks for, compared case-insensitively as the engine's own table is.
OPTION = b"-gameInfo"

#: Offset of the status word from the section base, directly after the header. The cave writes it
#: once, at startup, so a harness can read whether its `-gameInfo` string was the match it got.
STATUS_OFFSET = _HEADER.size
STATUS_NOT_GIVEN = 0
STATUS_APPLIED = 1
STATUS_REJECTED = 2

DEFAULT_HUMAN_FACTION = 3  # FactionMen, in Edain's playertemplate.ini order
DEFAULT_AI_FACTION = 10  # FactionMordor
DEFAULT_RESOURCES = 5000  # enough for a fortress; the unset default lands on 4999

#: The first instruction at each address the cave jumps to or calls. A build whose layout moved
#: fails here rather than on a wild branch.
ANCHORS = {
    COMMAND_LINE_SKIRMISH_SETUP_RESUME: bytes.fromhex("8d8ddcfdffff"),  # lea ecx, [ebp-0x224]
    LOADING_SCREEN_PROGRESS_RESUME: bytes.fromhex("578bce"),  # push edi; mov ecx, esi
    GAME_MESSAGE_APPEND_INTEGER: bytes.fromhex("e8c9feffff"),  # call 0x7110b3
    LOADING_SCREEN_PROGRESS_REPORT: bytes.fromhex("568bf1"),  # push esi; mov esi, ecx
    STRICMP: bytes.fromhex("ff25b406bd00"),  # jmp [_stricmp]
    ASCII_STRING_CTOR: bytes.fromhex("8b54240485d2"),  # mov edx, [esp+4]; test edx, edx
    ASCII_STRING_COPY_CTOR: bytes.fromhex("56578bf9"),  # push esi; push edi; mov edi, ecx
    ASCII_STRING_DTOR: bytes.fromhex("6aff68f80eb700"),  # push -1; push <EH record>
    GAME_INFO_PARSE: GAME_INFO_PARSE_ENTRY,  # mov eax, <EH record>
    GAME_INFO_PARSE_KEYS: GAME_INFO_PARSE_KEYS_BYTES,
    GAME_INFO_SET_MAP: bytes.fromhex("b8a98eb900"),
    GAME_INFO_SET_MAP_CRC: bytes.fromhex("b80490b900"),
    GAME_INFO_SET_MAP_SIZE: bytes.fromhex("b80490b900"),
}

# Each default seat: (slot index, state, start position, colour, team).  Colours are indices
# into `multiplayer.ini`'s MultiplayerColor order - 1 is red and 0 is blue - and teams are
# 0-based, so these two are on opposing teams at the map's first two start positions.
_SEATS = (
    (0, GAME_SLOT_STATE_LOCAL_HUMAN, 0, 1, 0),
    (1, GAME_SLOT_STATE_EASY_AI, 1, 0, 1),
)

#: The `GameInfo` dwords the `-file` start owns and the parser would overwrite from placeholders.
#: The map path is an `AsciiString` and is saved as a counted copy instead.
_RESTORED = (
    ("crc", GAME_INFO_MAP_CRC),
    ("size", GAME_INFO_MAP_SIZE),
    ("mask", GAME_INFO_MAP_CONTENTS_MASK),
    ("si", GAME_INFO_SI),
    ("gsid", GAME_INFO_GSID),
)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def _eax_at_esi(opcode: int, displacement: int) -> bytes:
    """`mov eax, [esi+d]` (0x8B) or `mov [esi+d], eax` (0x89), in the shortest form."""
    if displacement < 0x80:
        return bytes((opcode, 0x46, displacement))
    return bytes((opcode, 0x86)) + _u32(displacement)


def _ascii_string_block(text: str) -> bytes:
    """An `AsciiString`'s refcounted block: refcount, length, allocated, then the characters.

    Confirmed against the engine's own - the map path at `GameInfo+0x40` reads a refcount, a
    length word at `+4` and its characters at `+8`. The refcount saturates so that a release
    the engine makes on its own schedule can never take it to zero and free a page it did not
    allocate.
    """
    raw = text.encode("ascii") + b"\x00"
    return struct.pack("<IHH", 0x7FFFFFFF, len(text), len(raw)) + raw


def _align(a: Asm) -> None:
    while (len(a.buf) % 4) != 0:
        a.emit(0x00)


class CommandLineSkirmishPatch(Patch):
    name = "command-line-skirmish"
    author = "officialNecro"
    experimental = True
    description = (
        "Make `-file maps\\<name>.map` start a playable skirmish rather than an empty one, and "
        "let `-gameInfo <lobby string>` choose it: seats, factions, AI difficulty, teams, start "
        "positions, rules and seed, parsed by the engine's own lobby parser. Without the switch "
        "it fills a default two-seat match. No INI change; --human-faction and --ai-faction "
        "(the defaults) are indices into the loaded mod's PlayerTemplate order"
    )

    def __init__(
        self,
        human_faction: int = DEFAULT_HUMAN_FACTION,
        ai_faction: int = DEFAULT_AI_FACTION,
        resources: int = DEFAULT_RESOURCES,
    ) -> None:
        self.human_faction = human_faction
        self.ai_faction = ai_faction
        self.resources = resources

    def _factions(self) -> dict[int, int]:
        return {0: self.human_faction, 1: self.ai_faction}

    def _build(self, entries: dict[str, int]):
        """Return a `build` callable for `allocate_section`, recording its label addresses."""

        def build(base_va: int) -> bytes:
            a = Asm(base_va)
            a.emit(_HEADER.pack(MAGIC, self.human_faction, self.ai_faction, self.resources))
            a.label("status")
            a.emit(_u32(STATUS_NOT_GIVEN))
            a.label("saved_map")  # an `AsciiString`: one pointer, NULL until the copy is made
            a.emit(_u32(0))
            for field, _offset in _RESTORED:
                a.label(f"saved_{field}")
                a.emit(_u32(0))
            a.label("option")
            a.emit(OPTION + b"\x00")

            # One map-player name per start position, then a table of them the binding loop
            # indexes. Each block starts dword-aligned: its first field is a refcount the engine
            # may still write.
            for position in range(GAME_INFO_SLOT_COUNT):
                _align(a)
                a.label(f"name{position}")
                a.emit(_ascii_string_block(f"Player_{position + 1}"))
            _align(a)
            a.label("names")
            for position in range(GAME_INFO_SLOT_COUNT):
                a.emit(_u32(a.label_va(f"name{position}")))

            a.label("setup")
            a.emit(0x60, 0x9C)  # pushad; pushfd
            a.emit(0x8B, 0x35, _u32(THE_SKIRMISH_GAME_INFO))  # mov esi, [gi]
            a.emit(0x85, 0xF6)  # test esi, esi
            a.jcc(JE, "setup_done")

            options = (0, 0, 0, 1, 100)  # the five ahead of the resources field
            for step, value in enumerate(options):
                a.emit(0xC7, 0x46, GAME_INFO_OPTIONS + step * 4, struct.pack("<i", value))
            a.emit(0xC7, 0x46, GAME_INFO_STARTING_RESOURCES, struct.pack("<i", self.resources))

            factions = self._factions()
            for index, state, start_pos, colour, team in _SEATS:
                a.emit(0x8B, 0x46, GAME_INFO_SLOT_ARRAY + index * 4)  # mov eax, [esi+slot]
                a.emit(0x85, 0xC0)  # test eax, eax
                a.jcc(JE, f"seat{index}_done")
                for offset, value in (
                    (GAME_SLOT_STATE, state),
                    (GAME_SLOT_COLOR, colour),
                    (GAME_SLOT_START_POS, start_pos),
                    (GAME_SLOT_START_POS_GRANTED, start_pos),
                    (GAME_SLOT_PLAYER_TEMPLATE, factions[index]),
                    (GAME_SLOT_TEAM, team),
                    (GAME_SLOT_ORIGINAL_COLOR, colour),
                    (GAME_SLOT_ORIGINAL_START_POS, start_pos),
                    (GAME_SLOT_ORIGINAL_PLAYER_TEMPLATE, factions[index]),
                ):
                    a.emit(0xC7, 0x40, offset, struct.pack("<i", value))
                # The two bytes `setSlot` forces for a local human; an AI seat wants them too.
                a.emit(0xC6, 0x40, GAME_SLOT_ACCEPTED, 0x01)
                a.emit(0xC6, 0x40, GAME_SLOT_ACCEPTED + 1, 0x01)
                a.emit(0xC7, 0x40, GAME_SLOT_MAP_PLAYER, _u32(a.label_va(f"name{start_pos}")))
                a.label(f"seat{index}_done")

            # Find `-gameInfo <value>` in `GameEngine::init`'s argv. `ebp` is still that frame:
            # the hook is its own tail, and `pushad` leaves `ebp` where it was. Argument 0 is the
            # program, and the switch needs one argument after it.
            a.emit(0x8B, 0x4D, GAME_ENGINE_INIT_ARGC)  # mov ecx, [ebp+argc]
            a.emit(0x8B, 0x5D, GAME_ENGINE_INIT_ARGV)  # mov ebx, [ebp+argv]
            a.emit(0xBF, _u32(1))  # mov edi, 1
            a.label("scan")
            a.emit(0x8D, 0x47, 0x01)  # lea eax, [edi+1]
            a.emit(0x3B, 0xC1)  # cmp eax, ecx
            a.jcc(JGE, "publish")
            a.emit(0x51)  # push ecx               ; _stricmp may clobber it
            a.emit(0x68, _u32(a.label_va("option")))  # push "-gameInfo"
            a.emit(0xFF, 0x34, 0xBB)  # push [ebx+edi*4]
            a.call_absolute(STRICMP)
            a.emit(0x83, 0xC4, 0x08)  # add esp, 8
            a.emit(0x59)  # pop ecx
            a.emit(0x85, 0xC0)  # test eax, eax
            a.jcc(JE, "found")
            a.emit(0x47)  # inc edi
            a.jmp("scan")

            a.label("found")
            a.emit(0x8B, 0x7C, 0xBB, 0x04)  # mov edi, [ebx+edi*4+4]   ; the value
            # Save what the -file start owns: a counted copy of the map path, and the dwords.
            a.emit(0x8D, 0x46, GAME_INFO_MAP)  # lea eax, [esi+map]
            a.emit(0x50)  # push eax
            a.emit(0xB9, _u32(a.label_va("saved_map")))  # mov ecx, &saved_map
            a.call_absolute(ASCII_STRING_COPY_CTOR)
            for field, offset in _RESTORED:
                a.emit(_eax_at_esi(0x8B, offset))
                a.emit(0xA3, _u32(a.label_va(f"saved_{field}")))  # mov [saved], eax

            # ParseAsciiStringToGameInfo(gi, AsciiString(value), keepNames=false). The string is
            # constructed in its own argument slot, as the engine's callers do, and destroyed by
            # the callee.
            a.emit(0x6A, 0x00)  # push 0                 ; keepNames
            a.emit(0x51)  # push ecx               ; the AsciiString's slot
            a.emit(0x8B, 0xCC)  # mov ecx, esp
            a.emit(0x57)  # push edi               ; const char *
            a.call_absolute(ASCII_STRING_CTOR)
            a.emit(0x56)  # push esi               ; GameInfo *
            a.call_absolute(GAME_INFO_PARSE)
            a.emit(0x83, 0xC4, 0x0C)  # add esp, 12
            a.emit(0x84, 0xC0)  # test al, al
            a.jcc(JE, "rejected")

            # Put the map identity back, through the setters the auto-start itself called.
            a.emit(0x51)  # push ecx               ; setMap's by-value argument
            a.emit(0x8B, 0xCC)  # mov ecx, esp
            a.emit(0x68, _u32(a.label_va("saved_map")))  # push &saved_map
            a.call_absolute(ASCII_STRING_COPY_CTOR)
            a.emit(0x8B, 0xCE)  # mov ecx, esi
            a.call_absolute(GAME_INFO_SET_MAP)
            for field, setter in (("crc", GAME_INFO_SET_MAP_CRC), ("size", GAME_INFO_SET_MAP_SIZE)):
                a.emit(0xFF, 0x35, _u32(a.label_va(f"saved_{field}")))  # push [saved]
                a.emit(0x8B, 0xCE)  # mov ecx, esi
                a.call_absolute(setter)
            for field, offset in _RESTORED[2:]:
                a.emit(0xA1, _u32(a.label_va(f"saved_{field}")))  # mov eax, [saved]
                a.emit(_eax_at_esi(0x89, offset))

            # Bind every seated slot (states 2-6, the range `GameSlot::isOccupied` accepts) to
            # the map player at its start position. A slot with no start position binds nowhere.
            a.emit(0x33, 0xFF)  # xor edi, edi
            a.label("bind")
            a.emit(0x8B, 0x44, 0xBE, GAME_INFO_SLOT_ARRAY)  # mov eax, [esi+edi*4+slots]
            a.emit(0x85, 0xC0)  # test eax, eax
            a.jcc(JE, "bind_next")
            a.emit(0x83, 0x78, GAME_SLOT_STATE, GAME_SLOT_STATE_EASY_AI)  # cmp [eax+state], 2
            a.jcc(JL, "bind_next")
            a.emit(0x8B, 0x50, GAME_SLOT_START_POS)  # mov edx, [eax+startPos]
            a.emit(0x83, 0xFA, GAME_INFO_SLOT_COUNT)  # cmp edx, 8
            a.jcc(JAE, "bind_next")  # unsigned, so -1 is out of range too
            a.emit(0x8B, 0x14, 0x95, _u32(a.label_va("names")))  # mov edx, [names+edx*4]
            a.emit(0x89, 0x50, GAME_SLOT_MAP_PLAYER)  # mov [eax+mapPlayer], edx
            a.label("bind_next")
            a.emit(0x47)  # inc edi
            a.emit(0x83, 0xFF, GAME_INFO_SLOT_COUNT)  # cmp edi, 8
            a.jcc(JL, "bind")
            a.emit(0xC7, 0x05, _u32(a.label_va("status")), _u32(STATUS_APPLIED))
            a.jmp("release")

            a.label("rejected")
            a.emit(0xC7, 0x05, _u32(a.label_va("status")), _u32(STATUS_REJECTED))
            a.label("release")
            a.emit(0xB9, _u32(a.label_va("saved_map")))  # mov ecx, &saved_map
            a.call_absolute(ASCII_STRING_DTOR)

            a.label("publish")
            a.emit(0x89, 0x35, _u32(THE_GAME_INFO))  # mov [TheGameInfo], esi
            a.label("setup_done")
            a.emit(0x9D, 0x61)  # popfd; popad
            # The displaced tail, re-emitted: push 2; mov ecx, edi; appendIntegerArgument.
            a.emit(0x6A, 0x02, 0x8B, 0xCF)
            a.call_absolute(GAME_MESSAGE_APPEND_INTEGER)
            a.jmp_absolute(COMMAND_LINE_SKIRMISH_SETUP_RESUME)

            a.label("guard")
            a.emit(0x8B, 0x8E, _u32(LOADING_SCREEN_PROGRESS_WINDOW))
            a.emit(0x85, 0xC9)  # test ecx, ecx
            a.jcc(JE, "guard_done")
            a.emit(0x8B, 0x01, 0x57, 0xFF, 0x50, 0x34)  # mov eax,[ecx]; push edi; call [eax+0x34]
            a.emit(0x8B, 0x0D, _u32(LOADING_SCREEN_PROGRESS_SINK))
            a.emit(0x50)  # push eax
            a.call_absolute(LOADING_SCREEN_PROGRESS_REPORT)
            a.label("guard_done")
            a.jmp_absolute(LOADING_SCREEN_PROGRESS_RESUME)

            code = a.finish()
            for label in ("setup", "guard", "status", "saved_map", "option", "names"):
                entries[label] = a.label_va(label)
            return code

        return build

    def _check_anchors(self, data: bytearray) -> None:
        for va, expected in ANCHORS.items():
            offset = va_to_offset(data, va)
            if offset is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[offset : offset + len(expected)])
            if got != expected:
                raise ValueError(f"anchor {va:#010x}: expected {expected.hex()} got {got.hex()}")

    def apply(self, data: bytearray) -> None:
        setup_off = va_to_offset(data, COMMAND_LINE_SKIRMISH_SETUP)
        guard_off = va_to_offset(data, LOADING_SCREEN_PROGRESS)
        if setup_off is None or guard_off is None:
            raise ValueError("the hook sites are not mapped - not the expected build")
        self._check_anchors(data)

        entries: dict[str, int] = {}
        allocate_section(data, SECTION_NAME, self._build(entries), _CHARACTERISTICS)

        setup_jump = b"\xe9" + struct.pack(
            "<i", entries["setup"] - (COMMAND_LINE_SKIRMISH_SETUP + 5)
        )
        apply_byte_patch(
            data,
            setup_off,
            COMMAND_LINE_SKIRMISH_SETUP_BYTES,
            setup_jump + b"\x90" * (len(COMMAND_LINE_SKIRMISH_SETUP_BYTES) - len(setup_jump)),
            "auto-start skirmish setup -> cave",
        )
        guard_jump = b"\xe9" + struct.pack("<i", entries["guard"] - (LOADING_SCREEN_PROGRESS + 5))
        apply_byte_patch(
            data,
            guard_off,
            LOADING_SCREEN_PROGRESS_BYTES,
            guard_jump + b"\x90" * (len(LOADING_SCREEN_PROGRESS_BYTES) - len(guard_jump)),
            "loading-screen progress -> guarded cave",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        section = find_section(data, SECTION_NAME)
        if section is None:
            return [f"{SECTION_NAME} section is absent"]
        base_va, file_off, _size = section
        magic, human, ai, resources = _HEADER.unpack_from(bytes(data), file_off)
        if magic != MAGIC:
            problems.append(f"{SECTION_NAME} does not start with {MAGIC!r}")
        for label, found, want in (
            ("human-faction", human, self.human_faction),
            ("ai-faction", ai, self.ai_faction),
            ("resources", resources, self.resources),
        ):
            if found != want:
                problems.append(f"{label} is {found}, expected {want}")
        if OPTION + b"\x00" not in bytes(data[file_off : file_off + _size]):
            problems.append(f"{SECTION_NAME} does not carry the {OPTION.decode()} switch")
        for va, what in (
            (COMMAND_LINE_SKIRMISH_SETUP, "skirmish setup"),
            (LOADING_SCREEN_PROGRESS, "loading-screen progress"),
        ):
            offset = va_to_offset(data, va)
            if offset is None or data[offset] != 0xE9:
                problems.append(f"{what} at {va:#010x} does not jump")
                continue
            target = va + 5 + struct.unpack_from("<i", bytes(data), offset + 1)[0]
            if not base_va <= target < base_va + _size:
                problems.append(f"{what} jumps to {target:#010x}, outside {SECTION_NAME}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        section = find_section(data, SECTION_NAME)
        if section is None:
            return None
        try:
            magic, human, ai, resources = _HEADER.unpack_from(bytes(data), section[1])
        except struct.error:
            return None
        if magic != MAGIC:
            return None
        patch = cls(human_faction=human, ai_faction=ai, resources=resources)
        return None if patch.verify(data) else patch

    @staticmethod
    def status_va(data: bytes | bytearray) -> int | None:
        """Where a running copy of `data` keeps its `-gameInfo` status word, or None.

        The image has no relocations, so the VA read out of the file is the VA in the process:
        read a dword there once the match is up and compare it with the `STATUS_` constants.
        """
        section = find_section(data, SECTION_NAME)
        return None if section is None else section[0] + STATUS_OFFSET

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--human-faction",
            type=int,
            default=DEFAULT_HUMAN_FACTION,
            help="PlayerTemplate index for the default human seat (default: %(default)s, Men "
            "in Edain)",
        )
        parser.add_argument(
            "--ai-faction",
            type=int,
            default=DEFAULT_AI_FACTION,
            help="PlayerTemplate index for the default AI seat (default: %(default)s, Mordor "
            "in Edain)",
        )
        parser.add_argument(
            "--resources",
            type=int,
            default=DEFAULT_RESOURCES,
            help="starting resources for the default match (default: %(default)s)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        return cls(
            human_faction=args.human_faction,
            ai_faction=args.ai_faction,
            resources=args.resources,
        )
