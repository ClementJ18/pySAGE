"""The replay-annotations patch: write the engine's own score-keeping into the replay.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/replay-annotations.md``.

**The gap it closes.** A replay records *inputs*. Kills, losses, buildings traded and money
earned are computed by the simulation, so no chunk carries them and no amount of order-stream
analysis recovers them - which is why :mod:`sage_replay` can report what a player *did* and
never what it *cost* them. The engine has the numbers the whole time: every `Player` embeds a
`ScoreKeeper` at ``+0x3DC`` holding the score-screen counters, including two `Int[20]` arrays
indexed by the **victim's** `m_playerIndex` - a per-opponent kill matrix, not just a total.

**What it does.** Appends a ``.rpann`` PE section holding two chunk templates plus a routine,
and retargets the ``stopRecording`` call in ``RecorderClass::updateRecord``'s
``MSG_CLEAR_GAME_DATA`` branch (``0x0077F992``). That branch is where every ending converges,
and this is its second and last hook site: the ``0x1D`` end marker has been written, the file
is still open, and ``stopRecording`` - which closes it - has not run yet. The routine writes:

``ANNOTATION_MANIFEST`` (``0x7D1``), once
    schema version, a bitmask of the record kinds this build writes, and a writer id, so a
    consumer can tell "this build does not record scores" from "this game scored nothing".

``PLAYER_SCORE`` (``0x7D3``), one per player
    the keeper's counters, laid out in :data:`SCORE_FIELDS` order.

**Why the *second* call and not the first.** ``replay-outcome`` owns ``0x0077F98B``, and two
patches must not edit one site (:class:`~sage_patch.patcher.Patch`, composing rule 2). Hooking
the sibling call keeps both patches applicable in either order, at the cost of landing these
chunks *after* the ``0x1D`` marker rather than before it. They carry the same timecode either
way - ``writeToFile`` and this cave both read ``TheGameLogic->m_frame`` - so the header's
``num_timecodes`` still equals the last chunk's timecode and ``parse_replay``'s consistency
check passes unchanged.

**Why write the file directly rather than append a message.** The recorder only copies types
1001..1998 off the command list - the *network* range, relayed to every peer and executed by
all of them. Injecting an order to carry statistics would put a new message type on the wire
and make the patch a desync risk every peer had to share. Writing the bytes ourselves keeps it
client-local: nothing enters the simulation, nothing crosses the network, and an unpatched peer
is unaffected.

**Why these order types.** ``RecorderClass::updateRecord`` records ``0x1D`` plus the open range
``0x3E8 < type < 0x7CF``, and the ``GameMessage::Type`` enum stops at ``0x47B`` (see
``../docs/message-stream.md``), so everything from ``0x7D0`` up is unreachable for the engine.
``0x7D0`` is ``replay-outcome``'s; these take the next two of the reserved
``0x7D0``-``0x7EF`` annotation block.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name, and the only engine bytes it edits are the five of the ``call``
at ``0x0077F992``, which no other bundled patch touches. Its guards deliberately read no byte
``replay-outcome`` rewrites, so the two verify cleanly in either order.

Section layout, at the base::

    +0x00   manifest     MANIFEST_LEN bytes, written once
    +0x20   score        SCORE_LEN bytes, rewritten per player
    +0xF8   file         dword  the recorder's FILE*, held across the loop
    +0x100  code
"""

from __future__ import annotations

import struct

from ..addresses import (
    GAME_LOGIC_FRAME,
    IMPORT_FFLUSH,
    IMPORT_FWRITE,
    MAX_PLAYER_COUNT,
    PLAYER_COMMAND_POINTS_BONUS,
    PLAYER_COMMAND_POINTS_CAP,
    PLAYER_COMMAND_POINTS_HARD_CAP,
    PLAYER_COMMAND_POINTS_USED,
    PLAYER_INDEX,
    PLAYER_IS_OBSERVER,
    PLAYER_LIST_LOCAL_PLAYER,
    PLAYER_PLAYER_TEMPLATE,
    PLAYER_POWER_POINTS,
    PLAYER_POWER_POINTS_TOTAL,
    PLAYER_RESOURCES,
    PLAYER_SCORE_KEEPER,
    PLAYER_TEMPLATE_NAME_KEY,
    RECORDER_END_BRANCH,
    RECORDER_END_BRANCH_BYTES,
    RECORDER_END_STOP_CALL,
    RECORDER_END_STOP_CALL_BYTES,
    RECORDER_END_STOP_SETUP,
    RECORDER_END_STOP_SETUP_BYTES,
    RECORDER_FILE,
    RECORDER_MODE,
    RECORDER_MODE_RECORD,
    RECORDER_STOP_RECORDING,
    SCORE_KEEPER_COUNTER_BLOCK,
    SCORE_KEEPER_COUNTER_BLOCK_DWORDS,
    SCORE_KEEPER_END_FRAME,
    SCORE_KEEPER_LAYOUT_SITES,
    SCORE_KEEPER_MONEY_EARNED,
    SCORE_KEEPER_MONEY_SPENT,
    SCORE_KEEPER_PLAYER_REF,
    SCORE_KEEPER_PLAYER_REF_BYTES,
    SCORE_KEEPER_STRUCTURES_ALIVE,
    SCORE_KEEPER_UNITS_ALIVE,
    THE_GAME_LOGIC,
    THE_PLAYER_LIST,
    THE_RECORDER,
    THE_VICTORY_CONDITIONS,
    VICTORY_CONDITIONS_PLAYERS,
)
from ..asm import JE, JL, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "CODE_OFF",
    "FILE_OFF",
    "KIND_PLAYER_SCORE",
    "MANIFEST_LEN",
    "MANIFEST_OFF",
    "MANIFEST_TYPE",
    "MANIFEST_VALUES",
    "SCHEMA_VERSION",
    "SCORE_FIELDS",
    "SCORE_LEN",
    "SCORE_OFF",
    "SCORE_TYPE",
    "SCORE_VALUES",
    "SECTION_NAME",
    "WRITER_ID",
    "ReplayAnnotationsPatch",
    "build_section",
    "manifest_template",
    "score_template",
]

SECTION_NAME = ".rpann"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ | MEM_WRITE - both templates are rewritten in
# place as the loop runs, so the section cannot be read-only.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

#: The manifest chunk: what this build writes. Read first by any consumer, so that a record
#: kind being absent from a replay is distinguishable from the build never writing it.
MANIFEST_TYPE = 0x7D1

#: One per player: the `ScoreKeeper` counters.
SCORE_TYPE = 0x7D3

#: Integer argument 0 of every annotation chunk. Records grow by *appending* arguments and
#: bumping this; an argument position, once shipped, never changes meaning.
#:
#: v2 appends the eight `Player`-level fields in :data:`SCORE_FIELDS` marked `since=2` - the
#: seat's resolved faction, its resource balance, its spellbook points and its command-point
#: block. A v1 reader stops after `structures_lost` and is unaffected; this package's reader
#: takes whichever prefix a record carries.
SCHEMA_VERSION = 2

#: Bit 0 of the manifest's kind mask - this build writes `PLAYER_SCORE` records. The mask names
#: only what *this* patch writes: `replay-outcome`'s `0x7D0` is its own patch's business.
KIND_PLAYER_SCORE = 1 << 0

#: Identifies the writer, so the reserved block stays legible if anything else ever adopts it.
WRITER_ID = 0x53414745  # 'SAGE'

# The chunk, as `RecorderClass::writeToFile` lays one down and `sage_replay.ReplayChunk` reads
# one back: three dwords, then a unique-argument-type count, one `(type, count)` pair per
# distinct type, then the values. Both records are all-Integer, so one pair covers each.
CHUNK_TIMECODE_OFF = 0
CHUNK_TYPE_OFF = 4
CHUNK_NUMBER_OFF = 8
CHUNK_ARG_HEADER_OFF = 12
CHUNK_VALUES_OFF = 15

#: The manifest's Integers, in order.
MANIFEST_VALUES = ("schema_version", "kinds", "writer_id")

#: The score record's Integers, in order, from argument 1 (argument 0 is the schema version).
#:
#: The tail is the engine's own field order, not a chosen one: `units_destroyed[20]`,
#: `units_built`, `units_lost`, `structures_destroyed[20]`, `structures_built`,
#: `structures_lost` are contiguous in the keeper, so the cave copies all six counters with a
#: single `rep movsd` - one instruction to get right instead of forty-four.
#: Each entry is ``(name, width, since)`` - `since` being the schema version that introduced
#: it, so a reader can tell a field a record predates from one it is missing.
#:
#: The `since=2` tail is read off the `Player` rather than its keeper, which is why it sits
#: after the block copy instead of inside it.
SCORE_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("money_earned", 1, 1),
    ("money_spent", 1, 1),
    ("units_alive", 1, 1),
    ("structures_alive", 1, 1),
    ("end_frame", 1, 1),
    ("units_destroyed", MAX_PLAYER_COUNT, 1),
    ("units_built", 1, 1),
    ("units_lost", 1, 1),
    ("structures_destroyed", MAX_PLAYER_COUNT, 1),
    ("structures_built", 1, 1),
    ("structures_lost", 1, 1),
    ("faction_name_key", 1, 2),
    ("resources", 1, 2),
    ("power_points", 1, 2),
    ("power_points_total", 1, 2),
    ("command_points_used", 1, 2),
    ("command_points_cap", 1, 2),
    ("command_points_bonus", 1, 2),
    ("command_points_hard_cap", 1, 2),
)

#: Total Integers in a score record, the schema version included. Must stay <= 255: the chunk
#: format gives each `(type, count)` pair a single count byte.
SCORE_VALUES = 1 + sum(width for _, width, _ in SCORE_FIELDS)

MANIFEST_LEN = CHUNK_VALUES_OFF + 4 * len(MANIFEST_VALUES)
SCORE_LEN = CHUNK_VALUES_OFF + 4 * SCORE_VALUES

# The five scalars the cave copies one at a time, as (keeper offset, score argument index).
# Everything after them is the contiguous block.
_SCALARS = (
    (SCORE_KEEPER_MONEY_EARNED, 1),
    (SCORE_KEEPER_MONEY_SPENT, 2),
    (SCORE_KEEPER_UNITS_ALIVE, 3),
    (SCORE_KEEPER_STRUCTURES_ALIVE, 4),
    (SCORE_KEEPER_END_FRAME, 5),
)
_BLOCK_ARG = 6

# The `Player`-level tail, as (player offset, score argument index). Read through `edi` (the
# loop's current player) *before* the block copy, which borrows `esi`/`edi` for `rep movsd`.
_PLAYER_SCALARS = (
    (PLAYER_RESOURCES, 51),
    (PLAYER_POWER_POINTS, 52),
    (PLAYER_POWER_POINTS_TOTAL, 53),
    (PLAYER_COMMAND_POINTS_USED, 54),
    (PLAYER_COMMAND_POINTS_CAP, 55),
    (PLAYER_COMMAND_POINTS_BONUS, 56),
    (PLAYER_COMMAND_POINTS_HARD_CAP, 57),
)

#: The faction argument, filled by a guarded double dereference rather than a plain load.
_FACTION_ARG = 50

# `SCORE_OFF + SCORE_LEN` is 0x117 at schema v2, so the `FILE*` slot and the code both sit
# past it. These are section-relative and the section is allocated whole, so growing the
# record is a matter of moving them - but a record that overruns `FILE_OFF` would corrupt the
# handle mid-loop, which is why `test_replay_annotations.py` asserts the gap.
MANIFEST_OFF = 0x00
SCORE_OFF = 0x20
FILE_OFF = 0x120
CODE_OFF = 0x140


def _chunk(order_type: int, count: int, length: int) -> bytes:
    """A chunk template: the order type and an all-Integer argument header. The timecode, the
    player number and the values are filled in by the cave."""
    body = bytearray(length)
    struct.pack_into("<I", body, CHUNK_TYPE_OFF, order_type)
    body[CHUNK_ARG_HEADER_OFF : CHUNK_ARG_HEADER_OFF + 3] = bytes((1, 0, count))
    return bytes(body)


def manifest_template() -> bytes:
    """The manifest chunk, with its three constants already in place - only the timecode and
    the player number are runtime values."""
    body = bytearray(_chunk(MANIFEST_TYPE, len(MANIFEST_VALUES), MANIFEST_LEN))
    struct.pack_into("<III", body, CHUNK_VALUES_OFF, SCHEMA_VERSION, KIND_PLAYER_SCORE, WRITER_ID)
    return bytes(body)


def score_template() -> bytes:
    """The per-player chunk. Only the schema version is constant."""
    body = bytearray(_chunk(SCORE_TYPE, SCORE_VALUES, SCORE_LEN))
    struct.pack_into("<I", body, CHUNK_VALUES_OFF, SCHEMA_VERSION)
    return bytes(body)


def _value_va(base: int, chunk_off: int, index: int) -> int:
    """The address of Integer ``index`` of the chunk template at ``chunk_off``."""
    return base + chunk_off + CHUNK_VALUES_OFF + 4 * index


def _push_imm(a: Asm, value: int) -> None:
    """`push imm`, in the short form where it fits. `SCORE_LEN` does not."""
    if -0x80 <= value <= 0x7F:
        a.emit(0x6A, value & 0xFF)
    else:
        a.emit(0x68, struct.pack("<I", value))


def _fwrite(a: Asm, file_slot: int, chunk_va: int, length: int) -> None:
    """`fwrite(chunk, 1, length, file)` - cdecl, so the caller cleans the four arguments."""
    a.emit(0xFF, 0x35, struct.pack("<I", file_slot))  # push [file]
    _push_imm(a, length)
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x68, struct.pack("<I", chunk_va))  # push chunk
    a.emit(0xFF, 0x15, struct.pack("<I", IMPORT_FWRITE))  # call [fwrite]
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10


def _build_code(base_va: int) -> bytes:
    """The hook body. Runs once, on the logic thread, as the recorded game is torn down.

    Registers are the cave's own between `pushad` and `popad`: `esi` holds the subsystem being
    read, `edi` the current player and `ebx` the loop index - all callee-saved, so they survive
    the call into the CRT. The recorder's `FILE*` lives in the section rather than in `ebp`, so
    the frame pointer is never repurposed.
    """
    manifest = base_va + MANIFEST_OFF
    score = base_va + SCORE_OFF
    file_slot = base_va + FILE_OFF

    a = Asm(base_va + CODE_OFF)
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad
    # `rep movsd` copies upward only with the direction flag clear, and the CRT expects it
    # clear too. `popfd` puts back whatever the engine had.
    a.emit(0xFC)  # cld

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

    # Every chunk in this batch carries the frame the recording ends on - the same frame
    # `writeToFile` has just stamped the `0x1D` marker with, and the one `stopRecording` is
    # about to write into the header as `num_timecodes`.
    a.emit(0xA1, struct.pack("<I", THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.emit(0xA3, struct.pack("<I", manifest + CHUNK_TIMECODE_OFF))
    a.emit(0xA3, struct.pack("<I", score + CHUNK_TIMECODE_OFF))

    # The manifest is a file-level record, so it is attributed to the recording player -
    # the same player the `0x1D` marker names, and `ReplayFile.slot_index` maps it the same way.
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "manifest")
    a.emit(0x8B, 0x49, PLAYER_LIST_LOCAL_PLAYER)  # mov ecx, [ecx+0x10]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "manifest")
    a.emit(0x8B, 0x49, PLAYER_INDEX)  # mov ecx, [ecx+0x54]
    a.emit(0x89, 0x0D, struct.pack("<I", manifest + CHUNK_NUMBER_OFF))  # mov [manifest+8], ecx

    a.label("manifest")
    _fwrite(a, file_slot, manifest, MANIFEST_LEN)

    # The same walk `replay-outcome` makes, over the same compacted array, so the score records
    # pair one-to-one with the outcome records and carry the same player numbers.
    a.emit(0x8B, 0x35, struct.pack("<I", THE_VICTORY_CONDITIONS))  # mov esi, [TheVictoryCond..]
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "flush")
    a.emit(0x33, 0xDB)  # xor ebx, ebx                    ; i = 0

    a.label("loop")
    # mov edi, [esi + ebx*4 + 0x18]                       ; player = m_players[i]
    a.emit(0x8B, 0x7C, 0x9E, VICTORY_CONDITIONS_PLAYERS)
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "next")
    # An observer plays no side and keeps no score.
    a.emit(0x80, 0xBF, struct.pack("<I", PLAYER_IS_OBSERVER), 0x00)  # cmp byte [edi+0x35a], 0
    a.jcc(JNE, "next")

    a.emit(0x8B, 0x47, PLAYER_INDEX)  # mov eax, [edi+0x54]
    a.emit(0xA3, struct.pack("<I", score + CHUNK_NUMBER_OFF))  # mov [score+8], eax

    for keeper_off, argument in _SCALARS:
        # mov eax, [edi + PLAYER_SCORE_KEEPER + field]    ; the keeper is embedded in Player
        a.emit(0x8B, 0x87, struct.pack("<I", PLAYER_SCORE_KEEPER + keeper_off))
        a.emit(0xA3, struct.pack("<I", _value_va(base_va, SCORE_OFF, argument)))

    # Schema v2's tail, off the `Player` itself rather than its keeper.
    for player_off, argument in _PLAYER_SCALARS:
        a.emit(0x8B, 0x87, struct.pack("<I", player_off))  # mov eax, [edi + field]
        a.emit(0xA3, struct.pack("<I", _value_va(base_va, SCORE_OFF, argument)))

    # The seat's resolved faction, as its `PlayerTemplate`'s name key. Two dereferences, so the
    # null template a non-playing seat carries has to be handled - and handled by *storing zero*
    # rather than by skipping, because the template is reused across loop iterations and a
    # skipped store would leave the previous player's faction in this one's record.
    a.emit(0x8B, 0x87, struct.pack("<I", PLAYER_PLAYER_TEMPLATE))  # mov eax, [edi+0x34]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "faction")
    a.emit(0x8B, 0x40, PLAYER_TEMPLATE_NAME_KEY)  # mov eax, [eax+0x10]
    a.label("faction")
    a.emit(0xA3, struct.pack("<I", _value_va(base_va, SCORE_OFF, _FACTION_ARG)))

    # The six contiguous counters, in one copy. `esi`/`edi` are the loop's, so they are saved
    # around it rather than recomputed after.
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    # lea esi, [edi + PLAYER_SCORE_KEEPER + COUNTER_BLOCK]
    a.emit(0x8D, 0xB7, struct.pack("<I", PLAYER_SCORE_KEEPER + SCORE_KEEPER_COUNTER_BLOCK))
    a.emit(0xBF, struct.pack("<I", _value_va(base_va, SCORE_OFF, _BLOCK_ARG)))  # mov edi, dest
    a.emit(0xB9, struct.pack("<I", SCORE_KEEPER_COUNTER_BLOCK_DWORDS))  # mov ecx, 44
    a.emit(0xF3, 0xA5)  # rep movsd
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi

    _fwrite(a, file_slot, score, SCORE_LEN)

    a.label("next")
    a.emit(0x43)  # inc ebx
    a.emit(0x83, 0xFB, MAX_PLAYER_COUNT)  # cmp ebx, 20
    a.jcc(JL, "loop")

    a.label("flush")
    # The recorder flushes after every chunk of its own; match it, so the records are on disk
    # even if something goes wrong between here and `fclose`.
    a.emit(0xFF, 0x35, struct.pack("<I", file_slot))  # push [file]
    a.emit(0xFF, 0x15, struct.pack("<I", IMPORT_FFLUSH))  # call [fflush]
    a.emit(0x59)  # pop ecx

    a.label("done")
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    # Tail-jump, not a call: the displaced call's return address is still on the stack, so
    # `stopRecording`'s own `ret` goes back to `updateRecord` exactly as it always did. `ecx`
    # still holds the recorder - `popad` put back the `mov ecx, edi` the branch did for it.
    a.jmp_absolute(RECORDER_STOP_RECORDING)
    return a.finish()


def build_section(base_va: int) -> bytes:
    """The whole ``.rpann`` payload: the two chunk templates, the `FILE*` slot, then code."""
    body = bytearray(CODE_OFF)
    body[MANIFEST_OFF : MANIFEST_OFF + MANIFEST_LEN] = manifest_template()
    body[SCORE_OFF : SCORE_OFF + SCORE_LEN] = score_template()
    return bytes(body) + _build_code(base_va)


class ReplayAnnotationsPatch(Patch):
    name = "replay-annotations"
    author = "officialNecro"
    description = (
        "Write each player's score-screen counters into the replay - units and structures "
        "built, lost and destroyed (per opponent), money earned and spent"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, RECORDER_END_STOP_CALL)
        if hook_off is None:
            raise ValueError(
                f"{RECORDER_END_STOP_CALL:#010x} is not mapped - not the expected build"
            )
        # Three structural checks before taking the site over, all of which fail loudly on a
        # build whose layout moved rather than installing a hook that writes wrong numbers.
        self._check_end_branch(data)
        self._check_keeper_base(data)
        self._check_keeper_layout(data)
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        code_va = section_va + CODE_OFF
        call = b"\xe8" + struct.pack("<i", code_va - (RECORDER_END_STOP_CALL + 5))
        apply_byte_patch(
            data,
            hook_off,
            RECORDER_END_STOP_CALL_BYTES,
            call,
            "updateRecord stopRecording call -> replay-annotations hook",
        )

    @staticmethod
    def _check_end_branch(data: bytes | bytearray) -> None:
        """Raise unless the hooked call is still the `stopRecording` of the recorder's
        `MSG_CLEAR_GAME_DATA` branch. The site itself is a bare `call`; the branch fingerprint
        plus the `mov ecx, edi` that sets it up are what say which call it is.

        Both windows stop short of `replay-outcome`'s five bytes on purpose, so this reads the
        same either side of that patch."""
        for va, expected, label in (
            (RECORDER_END_BRANCH, RECORDER_END_BRANCH_BYTES, "the end-of-recording branch"),
            (RECORDER_END_STOP_SETUP, RECORDER_END_STOP_SETUP_BYTES, "its stopRecording setup"),
        ):
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} is {got.hex()}, expected {expected.hex()} - this is not {label}"
                )

    @staticmethod
    def _check_keeper_base(data: bytes | bytearray) -> None:
        """Raise unless `Player+0x3DC` is still handed out as a `ScoreKeeper`. Checked at one
        of the engine's own `lea` sites, because the offset is otherwise only visible in the
        arithmetic of code the cave does not touch."""
        off = va_to_offset(data, SCORE_KEEPER_PLAYER_REF)
        if off is None:
            raise ValueError("ScoreKeeper::addObjectDestroyed is not mapped")
        got = bytes(data[off : off + len(SCORE_KEEPER_PLAYER_REF_BYTES)])
        if got != SCORE_KEEPER_PLAYER_REF_BYTES:
            raise ValueError(
                f"{SCORE_KEEPER_PLAYER_REF:#010x} is {got.hex()}, expected "
                f"{SCORE_KEEPER_PLAYER_REF_BYTES.hex()} - the ScoreKeeper is not at "
                f"Player+{PLAYER_SCORE_KEEPER:#x}"
            )

    @staticmethod
    def _check_keeper_layout(data: bytes | bytearray) -> None:
        """Raise unless the four counter offsets the cave copies are still the ones the engine
        increments. A moved counter is the failure mode that would otherwise ship silently -
        the chunk would parse perfectly and mean something else."""
        for va, expected in SCORE_KEEPER_LAYOUT_SITES:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"the ScoreKeeper counter written at {va:#010x} is {got.hex()}, expected "
                    f"{expected.hex()} - the layout moved and the chunk would carry the "
                    "wrong numbers"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        off = va_to_offset(data, RECORDER_END_STOP_CALL)
        if off is None:
            return [f"{RECORDER_END_STOP_CALL:#010x} is not mapped by any section"]
        if data[off] != 0xE8:
            return [f"{RECORDER_END_STOP_CALL:#010x} is not a call - hook not installed"]
        target = RECORDER_END_STOP_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va + CODE_OFF:
            problems.append(f"hook calls {target:#010x}, expected {section_va + CODE_OFF:#010x}")
        for name, chunk_off, template in (
            ("manifest", MANIFEST_OFF, manifest_template()),
            ("score", SCORE_OFF, score_template()),
        ):
            at = section_off + chunk_off
            got = bytes(data[at + CHUNK_TYPE_OFF : at + CHUNK_VALUES_OFF])
            if got != template[CHUNK_TYPE_OFF:CHUNK_VALUES_OFF]:
                problems.append(f"the {name} template's type and argument header are not ours")
        try:
            self._check_end_branch(data)
            self._check_keeper_base(data)
            self._check_keeper_layout(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems
