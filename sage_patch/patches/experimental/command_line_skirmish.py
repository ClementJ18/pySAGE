"""The command-line-skirmish patch: make `-file <map>.map` start a game worth playing.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/game-info.md``; this module implements the recipe that document's §6 records.

**The gap.** `-file <map>.map` is a stock command line and it already skips every menu: the engine
appends `MSG_NEW_GAME`, builds a `SkirmishGameInfo` and asks for game mode 2. What it does *not* do
is configure the game. Slot 0 gets state 6 and the name "Test" with a **random** faction
(`-2`), no colour, no team and no start position; slots 1-7 are closed; the options block is left
at `-1` throughout; and `TheGameInfo` - which `GameLogic::update` reads every frame - is never
pointed at the object the auto-start filled. The result loads nothing, plays nothing and faults.

**What this does.** Three things, at the point the engine has finished building the `GameInfo` and
before it asks for the game mode:

1. **Fills the slots.** Slot 0 becomes a local human of a chosen faction and slot 1 an easy AI of
   another, each with a colour, a team and a start position - and each with the `AsciiString` at
   `GAME_SLOT_MAP_PLAYER` naming `Player_<startPos + 1>`, which is what binds a seat to the
   map-side player owning the pre-placed objects at that start position. The strings live in this
   patch's own section with a saturated refcount, so nothing the engine does can free them.
2. **Sets the options block**, starting resources included. Left unset every player begins on
   4999 - one short of a fortress - so the human can never unpack a base and the match ends in
   defeat inside thirty frames.
3. **Points `TheGameInfo` at `TheSkirmishGameInfo`**, exactly as the skirmish setup screen does at
   `0x006309BF`. Without it `GameLogic::update` dereferences null on frame 1.

A fourth edit is elsewhere: the loading screen's progress update at `LOADING_SCREEN_PROGRESS`
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
orders its templates differently.

**Status - one run, and it played.** Installed as `game.dat` on an Edain install and started with
`-file maps\\map mp harlindon.map`, nothing else: both seats were created (`Player_1` as Men,
`Player_2` as Mordor, 10000 each), the bases unpacked - the object count went 369 -> 593 -> 721 -
frames advanced past 130, and income was flowing. That is one session against one map on one mod,
which is why this is still `experimental`: what it has not had is enough play, across enough maps
and factions, to know the reading was right everywhere.

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
    COMMAND_LINE_SKIRMISH_SETUP,
    COMMAND_LINE_SKIRMISH_SETUP_BYTES,
    COMMAND_LINE_SKIRMISH_SETUP_RESUME,
    GAME_INFO_OPTIONS,
    GAME_INFO_SLOT_ARRAY,
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
    THE_GAME_INFO,
    THE_SKIRMISH_GAME_INFO,
)
from ...asm import JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "DEFAULT_AI_FACTION",
    "DEFAULT_HUMAN_FACTION",
    "DEFAULT_RESOURCES",
    "MAGIC",
    "SECTION_NAME",
    "CommandLineSkirmishPatch",
]

SECTION_NAME = ".clskir"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: The cave holds writable data - the `AsciiString` blocks, whose refcount the engine may still
#: touch - as well as code, so it is not the read-only cave most patches here allocate.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

#: A header at the section base, so `detect` can recover the parameters a build was made with
#: rather than reporting this version's defaults. Magic, then the three values.
MAGIC = b"CLSK"
_HEADER = struct.Struct("<4siii")

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
}

# Each configured seat: (slot index, state, start position, colour, team).  Colours are indices
# into `multiplayer.ini`'s MultiplayerColor order - 1 is red and 0 is blue - and teams are
# 0-based, so these two are on opposing teams at the map's first two start positions.
_SEATS = (
    (0, GAME_SLOT_STATE_LOCAL_HUMAN, 0, 1, 0),
    (1, GAME_SLOT_STATE_EASY_AI, 1, 0, 1),
)


def _ascii_string_block(text: str) -> bytes:
    """An `AsciiString`'s refcounted block: refcount, length, allocated, then the characters.

    Confirmed against the engine's own - the map path at `GameInfo+0x40` reads a refcount, a
    length word at `+4` and its characters at `+8`. The refcount saturates so that a release
    the engine makes on its own schedule can never take it to zero and free a page it did not
    allocate.
    """
    raw = text.encode("ascii") + b"\x00"
    return struct.pack("<IHH", 0x7FFFFFFF, len(text), len(raw)) + raw


class CommandLineSkirmishPatch(Patch):
    name = "command-line-skirmish"
    author = "officialNecro"
    experimental = True
    description = (
        "Make `-file maps\\<name>.map` start a playable skirmish rather than an empty one: fills "
        "the GameInfo slots the auto-start leaves random, sets the starting resources, points "
        "TheGameInfo at the skirmish one, and null-guards a loading-screen window a menu-less "
        "start never creates. No INI change; --human-faction and --ai-faction are indices into "
        "the loaded mod's PlayerTemplate order"
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

            # Each block starts dword-aligned: its first field is a refcount the engine may still
            # write, and the code that follows the blocks is aligned by the same padding.
            for index, *_ in _SEATS:
                while (len(a.buf) % 4) != 0:
                    a.emit(0x00)
                a.label(f"name{index}")
                a.emit(_ascii_string_block(f"Player_{index + 1}"))
            while (len(a.buf) % 4) != 0:
                a.emit(0x00)

            a.label("setup")
            a.emit(0x60, 0x9C)  # pushad; pushfd
            a.emit(0x8B, 0x35, struct.pack("<I", THE_SKIRMISH_GAME_INFO))  # mov esi, [gi]
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
                a.emit(
                    0xC7, 0x40, GAME_SLOT_MAP_PLAYER, struct.pack("<I", a.label_va(f"name{index}"))
                )
                a.label(f"seat{index}_done")

            a.emit(0x89, 0x35, struct.pack("<I", THE_GAME_INFO))  # mov [TheGameInfo], esi
            a.label("setup_done")
            a.emit(0x9D, 0x61)  # popfd; popad
            # The displaced tail, re-emitted: push 2; mov ecx, edi; appendIntegerArgument.
            a.emit(0x6A, 0x02, 0x8B, 0xCF)
            a.call_absolute(GAME_MESSAGE_APPEND_INTEGER)
            a.jmp_absolute(COMMAND_LINE_SKIRMISH_SETUP_RESUME)

            a.label("guard")
            a.emit(0x8B, 0x8E, struct.pack("<I", LOADING_SCREEN_PROGRESS_WINDOW))
            a.emit(0x85, 0xC9)  # test ecx, ecx
            a.jcc(JE, "guard_done")
            a.emit(0x8B, 0x01, 0x57, 0xFF, 0x50, 0x34)  # mov eax,[ecx]; push edi; call [eax+0x34]
            a.emit(0x8B, 0x0D, struct.pack("<I", LOADING_SCREEN_PROGRESS_SINK))
            a.emit(0x50)  # push eax
            a.call_absolute(LOADING_SCREEN_PROGRESS_REPORT)
            a.label("guard_done")
            a.jmp_absolute(LOADING_SCREEN_PROGRESS_RESUME)

            code = a.finish()
            entries["setup"] = a.label_va("setup")
            entries["guard"] = a.label_va("guard")
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

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--human-faction",
            type=int,
            default=DEFAULT_HUMAN_FACTION,
            help="PlayerTemplate index for the human seat (default: %(default)s, Men in Edain)",
        )
        parser.add_argument(
            "--ai-faction",
            type=int,
            default=DEFAULT_AI_FACTION,
            help="PlayerTemplate index for the AI seat (default: %(default)s, Mordor in Edain)",
        )
        parser.add_argument(
            "--resources",
            type=int,
            default=DEFAULT_RESOURCES,
            help="starting resources for every seat (default: %(default)s)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        return cls(
            human_faction=args.human_faction,
            ai_faction=args.ai_faction,
            resources=args.resources,
        )
