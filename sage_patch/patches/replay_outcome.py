"""The replay-outcome patch: write the final state of the game into the replay.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/replay-outcome.md``.

**The gap it closes.** A replay records *inputs*, not state. Eliminations are computed by the
simulation and never written to the stream, so no stock chunk says who won - which is why
:mod:`sage_replay.winner` has to infer an outcome from who stopped issuing orders, and why it
answers ``undetermined`` for every game that ended by elimination rather than by somebody
conceding.

**What it does.** Appends a ``.rpout`` PE section holding a chunk template plus a routine, and
retargets the ``writeToFile`` call in ``RecorderClass::updateRecord``'s ``MSG_CLEAR_GAME_DATA``
branch (``0x0077F98B``). That branch is where *every* ending converges: `0x1D` has **thirteen**
emitters in the binary - `GameLogic::clearGameData` is only the one a mid-match quit takes, and
a game that finishes ends through the score-screen code instead - but all of them are consumed
here, and the branch has already proven ``m_file`` non-NULL. The routine runs immediately before
the ``0x1D`` chunk is written and immediately before ``stopRecording`` closes the file, so it is
the last moment anything can be appended to a recording. It writes one chunk per player straight
to the recorder's own ``FILE*``, in the engine's own chunk format, stamped with the current
logic frame. Each chunk carries::

    order type  ORDER_TYPE (0x7D0)
    number      the player's `m_playerIndex`, exactly as a real order carries it
    Integer 0   outcome:  0 undetermined | 1 victorious | 2 defeated
    Integer 1   the frame that player was defeated on, or 0 if never

so the state of *every* player is on record at the moment the recording ends, whichever way it
ended, and :meth:`sage_replay.ReplayFile.slot_index` maps each chunk to its metadata slot with
no new rule - the number is the same field the engine fills for a human's own orders.

**Why write the file directly rather than append a message.** The recorder writes what it sees
on ``TheCommandList``, and it only keeps types 1001..1998 - the *network* range, which is
relayed to every peer and executed by all of them. Injecting an order there to carry a verdict
would put a new message type on the wire and make the patch a desync risk that every peer had
to carry. Writing the bytes ourselves keeps the whole thing client-local: nothing enters the
simulation, nothing crosses the network, and an unpatched peer is unaffected. The cave lands its
chunks at the file's current position, which is exactly where the recorder's next chunk would
have gone.

**Why ``0x7D0``.** The engine can never emit it. ``RecorderClass::updateRecord`` records
``0x1D`` plus the open range ``0x3E8 < type < 0x7CF``, and the ``GameMessage::Type`` enum stops
at ``0x47B`` (see ``../docs/message-stream.md``), so 2000 is outside both the recorded range and
the enum. A chunk of this type in a replay came from this patch or from nowhere.

**Why the outcome is the engine's own answer.** ``m_isDefeated[i]`` is a latch
``VictoryConditions::update`` sets on the frame a player is first found defeated, and the
``hasAchievedVictory`` predicate resolves teams. Both are already called every frame by the
stock UI, so the cave calling them once more at teardown introduces no side effect the engine
does not already have. A player who is neither is reported ``undetermined`` rather than guessed
at - the honest answer when the recorder quit a match that was still live.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name, and the only engine bytes it edits are the five of the
``call`` at ``0x0077F98B``, which no other bundled patch touches.

Section layout, at the base::

    +0x00  chunk        CHUNK_LEN bytes, the template rewritten per player
    +0x18  file         dword  the recorder's FILE*, held across the loop
    +0x20  code
"""

from __future__ import annotations

import struct

from ..addresses import (
    GAME_LOGIC_FRAME,
    IMPORT_FFLUSH,
    IMPORT_FWRITE,
    MAX_PLAYER_COUNT,
    PLAYER_DEFEAT_FRAME,
    PLAYER_INDEX,
    PLAYER_IS_DEFEATED,
    PLAYER_IS_OBSERVER,
    RECORDER_END_BRANCH,
    RECORDER_END_BRANCH_BYTES,
    RECORDER_END_WRITE_CALL,
    RECORDER_END_WRITE_CALL_BYTES,
    RECORDER_FILE,
    RECORDER_MODE,
    RECORDER_MODE_RECORD,
    RECORDER_WRITE_TO_FILE,
    THE_GAME_LOGIC,
    THE_RECORDER,
    THE_VICTORY_CONDITIONS,
    VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY,
    VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT,
    VICTORY_CONDITIONS_IS_DEFEATED,
    VICTORY_CONDITIONS_PLAYERS,
    VICTORY_CONDITIONS_VTABLE,
)
from ..asm import JE, JL, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "CHUNK_LEN",
    "CODE_OFF",
    "FILE_OFF",
    "ORDER_TYPE",
    "OUTCOME_DEFEATED",
    "OUTCOME_UNDETERMINED",
    "OUTCOME_VICTORIOUS",
    "SECTION_NAME",
    "ReplayOutcomePatch",
    "build_section",
    "chunk_template",
]

SECTION_NAME = ".rpout"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ | MEM_WRITE - the chunk template is rewritten
# in place once per player, so the section cannot be read-only.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

#: The chunk's order type. Outside both the range the recorder copies off the command list
#: (`0x3E8 < type < 0x7CF`) and the `GameMessage::Type` enum (which ends at `0x47B`), so the
#: engine cannot produce it and no real order can be mistaken for one. `sage_replay` reads it
#: back as `Bfme2OrderType.GameOutcome`; the two must agree.
ORDER_TYPE = 0x7D0

OUTCOME_UNDETERMINED = 0
OUTCOME_VICTORIOUS = 1
OUTCOME_DEFEATED = 2

# The chunk, as `RecorderClass::writeToFile` lays one down and `sage_replay.ReplayChunk`
# reads one back: three dwords, then a unique-argument-type count, one `(type, count)` pair
# per distinct type, then the values. Ours is two Integers, so one pair covers both.
CHUNK_TIMECODE_OFF = 0
CHUNK_TYPE_OFF = 4
CHUNK_NUMBER_OFF = 8
CHUNK_ARG_HEADER_OFF = 12  # 01 (one unique type), 00 (Integer), 02 (two of them)
CHUNK_OUTCOME_OFF = 15
CHUNK_FRAME_OFF = 19
CHUNK_LEN = 23

FILE_OFF = 0x18
CODE_OFF = 0x20

_ARG_HEADER = bytes((1, 0, 2))


def chunk_template() -> bytes:
    """The constant part of a chunk: the order type and the argument header. The timecode,
    the player number and the two values are filled in by the cave."""
    body = bytearray(CHUNK_LEN)
    struct.pack_into("<I", body, CHUNK_TYPE_OFF, ORDER_TYPE)
    body[CHUNK_ARG_HEADER_OFF : CHUNK_ARG_HEADER_OFF + len(_ARG_HEADER)] = _ARG_HEADER
    return bytes(body)


def _build_code(base_va: int) -> bytes:
    """The hook body. Runs once, on the logic thread, as the recorded game is torn down.

    Registers are the cave's own between `pushad` and `popad`: `esi` holds the subsystem being
    read, `edi` the current player and `ebx` the loop index - all callee-saved, so they survive
    the calls into the engine. The recorder's `FILE*` lives in the section rather than in `ebp`,
    so the frame pointer is never repurposed.
    """
    chunk = base_va
    file_slot = base_va + FILE_OFF

    a = Asm(base_va + CODE_OFF)
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad

    # Only a live recording gets written to. `m_file` is also the handle a *playback* reads
    # from, so the mode has to be checked too, not just the handle.
    a.emit(0x8B, 0x35, struct.pack("<I", THE_RECORDER))  # mov esi, [TheRecorder]
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "done")
    a.emit(0x83, 0x7E, RECORDER_MODE, RECORDER_MODE_RECORD)  # cmp dword [esi+0x1c], 0
    a.jcc(JNE, "done")
    a.emit(0x8B, 0x46, RECORDER_FILE)  # mov eax, [esi+0x10]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0xA3, struct.pack("<I", file_slot))  # mov [file], eax

    a.emit(0x8B, 0x35, struct.pack("<I", THE_VICTORY_CONDITIONS))  # mov esi, [TheVictoryCond..]
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "done")

    # Every chunk in this batch carries the same timecode: the frame the game ended on, which
    # is the frame the recorder is about to stamp the `0x1D` marker with.
    a.emit(0xA1, struct.pack("<I", THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.emit(0xA3, struct.pack("<I", chunk + CHUNK_TIMECODE_OFF))  # mov [chunk], eax

    a.emit(0x33, 0xDB)  # xor ebx, ebx                    ; i = 0

    a.label("loop")
    # mov edi, [esi + ebx*4 + 0x18]                       ; player = m_players[i]
    a.emit(0x8B, 0x7C, 0x9E, VICTORY_CONDITIONS_PLAYERS)
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "next")
    # An observer plays no side and is born flagged defeated, so it must not be reported.
    a.emit(0x80, 0xBF, struct.pack("<I", PLAYER_IS_OBSERVER), 0x00)  # cmp byte [edi+0x35a], 0
    a.jcc(JNE, "next")

    # cmp byte [esi + ebx + 0x70], 0                      ; m_isDefeated[i], the latch
    a.emit(0x80, 0x7C, 0x1E, VICTORY_CONDITIONS_IS_DEFEATED, 0x00)
    a.jcc(JNE, "defeated")
    # The player's own flag, which a quit sets before the subsystem catches up.
    a.emit(0x80, 0xBF, struct.pack("<I", PLAYER_IS_DEFEATED), 0x00)  # cmp byte [edi+0x754], 0
    a.jcc(JNE, "defeated")

    # `hasAchievedVictory(player)` - the engine's own answer, teams resolved. It is `ret 4`,
    # so it cleans the argument itself.
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0x06)  # mov eax, [esi]                  ; vtable
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0xFF, 0x50, VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT)  # call [eax+0x38]
    a.emit(0x33, 0xD2)  # xor edx, edx                    ; clobbered by the call; also the
    a.emit(0x84, 0xC0)  # test al, al                     ;   OUTCOME_UNDETERMINED default
    a.jcc_short(JE, "store")
    a.emit(0xBA, struct.pack("<I", OUTCOME_VICTORIOUS))  # mov edx, 1
    a.jmp_short("store")

    a.label("defeated")
    a.emit(0xBA, struct.pack("<I", OUTCOME_DEFEATED))  # mov edx, 2

    a.label("store")
    a.emit(0x89, 0x15, struct.pack("<I", chunk + CHUNK_OUTCOME_OFF))  # mov [chunk+15], edx
    a.emit(0x8B, 0x87, struct.pack("<I", PLAYER_DEFEAT_FRAME))  # mov eax, [edi+0x4cc]
    a.emit(0xA3, struct.pack("<I", chunk + CHUNK_FRAME_OFF))  # mov [chunk+19], eax
    a.emit(0x8B, 0x47, PLAYER_INDEX)  # mov eax, [edi+0x54]
    a.emit(0xA3, struct.pack("<I", chunk + CHUNK_NUMBER_OFF))  # mov [chunk+8], eax

    # fwrite(chunk, 1, CHUNK_LEN, file) - cdecl, so the caller cleans the four arguments.
    a.emit(0xFF, 0x35, struct.pack("<I", file_slot))  # push [file]
    a.emit(0x6A, CHUNK_LEN)  # push CHUNK_LEN
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x68, struct.pack("<I", chunk))  # push chunk
    a.emit(0xFF, 0x15, struct.pack("<I", IMPORT_FWRITE))  # call [fwrite]
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10

    a.label("next")
    a.emit(0x43)  # inc ebx
    a.emit(0x83, 0xFB, MAX_PLAYER_COUNT)  # cmp ebx, 20
    a.jcc(JL, "loop")

    # The recorder flushes after every chunk of its own; match it, so a crash between here and
    # `stopRecording` still leaves the verdict on disk.
    a.emit(0xFF, 0x35, struct.pack("<I", file_slot))  # push [file]
    a.emit(0xFF, 0x15, struct.pack("<I", IMPORT_FFLUSH))  # call [fflush]
    a.emit(0x59)  # pop ecx

    a.label("done")
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    # Tail-jump, not a call: the displaced call's return address is still on the stack, so the
    # campaign manager's own `ret` goes back to `clearGameData` exactly as it always did.
    a.jmp_absolute(RECORDER_WRITE_TO_FILE)
    return a.finish()


def build_section(base_va: int) -> bytes:
    """The whole ``.rpout`` payload: chunk template, the `FILE*` slot, then code."""
    body = bytearray(CODE_OFF)
    body[0:CHUNK_LEN] = chunk_template()
    return bytes(body) + _build_code(base_va)


class ReplayOutcomePatch(Patch):
    name = "replay-outcome"
    author = "officialNecro"
    description = (
        "Write each player's final victory/defeat state into the replay, at the frame the "
        "recording ends - whether a player left or the game finished"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, RECORDER_END_WRITE_CALL)
        if hook_off is None:
            raise ValueError(
                f"{RECORDER_END_WRITE_CALL:#010x} is not mapped - not the expected build"
            )
        # Two structural checks before taking the site over, both of which fail loudly on a
        # build whose layout moved rather than installing a hook that runs the wrong code.
        self._check_end_marker(data)
        self._check_vtable(data)
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        code_va = section_va + CODE_OFF
        call = b"\xe8" + struct.pack("<i", code_va - (RECORDER_END_WRITE_CALL + 5))
        apply_byte_patch(
            data,
            hook_off,
            RECORDER_END_WRITE_CALL_BYTES,
            call,
            "clearGameData campaign call -> replay-outcome hook",
        )

    @staticmethod
    def _check_end_marker(data: bytes | bytearray) -> None:
        """Raise unless the hooked call is still the `writeToFile` of the recorder's
        `MSG_CLEAR_GAME_DATA` branch. The site itself is a bare `call`; this 20-byte
        fingerprint - the `cmp eax, 0x1D`, the `m_file` test, and the `mov ecx, edi` that
        sets up the call - is what says which call it is."""
        off = va_to_offset(data, RECORDER_END_BRANCH)
        if off is None:
            raise ValueError("RecorderClass::updateRecord is not mapped - not the expected build")
        got = bytes(data[off : off + len(RECORDER_END_BRANCH_BYTES)])
        if got != RECORDER_END_BRANCH_BYTES:
            raise ValueError(
                f"{RECORDER_END_BRANCH:#010x} is {got.hex()}, expected "
                f"{RECORDER_END_BRANCH_BYTES.hex()} (cmp eax, MSG_CLEAR_GAME_DATA; test "
                "m_file; ...) - this is not the end-of-recording branch"
            )

    @staticmethod
    def _check_vtable(data: bytes | bytearray) -> None:
        """Raise unless the `VictoryConditions` vtable still names the predicates the cave
        dispatches to. Only `hasAchievedVictory` is called, but checking its neighbour too
        pins the slot numbering rather than one address."""
        for slot, expected, label in (
            (
                VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT,
                VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY,
                "hasAchievedVictory",
            ),
            (
                VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT,
                VICTORY_CONDITIONS_HAS_BEEN_DEFEATED,
                "hasBeenDefeated",
            ),
        ):
            off = va_to_offset(data, VICTORY_CONDITIONS_VTABLE + slot)
            if off is None:
                raise ValueError("the VictoryConditions vtable is not mapped")
            target = struct.unpack_from("<I", data, off)[0]
            if target != expected:
                raise ValueError(
                    f"VictoryConditions vtable +{slot:#x} dispatches to {target:#010x}, "
                    f"not {expected:#010x} ({label}) - the cave would call the wrong function"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        off = va_to_offset(data, RECORDER_END_WRITE_CALL)
        if off is None:
            return [f"{RECORDER_END_WRITE_CALL:#010x} is not mapped by any section"]
        if data[off] != 0xE8:
            return [f"{RECORDER_END_WRITE_CALL:#010x} is not a call - hook not installed"]
        target = RECORDER_END_WRITE_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va + CODE_OFF:
            problems.append(f"hook calls {target:#010x}, expected {section_va + CODE_OFF:#010x}")
        template = bytes(data[section_off : section_off + CHUNK_LEN])
        if template[CHUNK_TYPE_OFF : CHUNK_TYPE_OFF + 4] != struct.pack("<I", ORDER_TYPE):
            problems.append(f"the chunk template does not carry order type {ORDER_TYPE:#x}")
        header = template[CHUNK_ARG_HEADER_OFF : CHUNK_ARG_HEADER_OFF + len(_ARG_HEADER)]
        if header != _ARG_HEADER:
            problems.append("the chunk template's argument header is not two Integers")
        try:
            self._check_end_marker(data)
            self._check_vtable(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems
