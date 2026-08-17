"""The skirmish-replay patch: record single-player skirmish games, under a unique name.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/skirmish-replay.md``.

**The gap it closes.** The stock engine only records network games. `RecorderClass::startRecording`
has exactly one caller - the ``MSG_NEW_GAME`` branch of `RecorderClass::updateRecord` - and that
branch whitelists the message's game mode against ``{1, 5}``, the two network flavours. A skirmish
started from the menu emits mode **2**, so it falls off the end of the whitelist and nothing is
ever written. Everything downstream of that decision already works: `startRecording` has a
complete non-network path that builds the header's metadata string from `TheSkirmishGameInfo`,
and the engine's own playback predicates (`0x00625456`) already accept a *recorded* mode of 2.
The only thing missing is the entry in the list.

**What it does.** Appends a ``.rpskir`` PE section holding a mode table, a name buffer and two
small routines, and makes two five-to-nine byte edits:

``0x0077F910`` - the whitelist tail (``cmp eax, 5`` / ``jne <skip>``) becomes a jump into the
first routine, which tests the same mode 5, then every mode in the table, and jumps back to the
recorder's own accept (``0x0077F919``) or reject (``0x0077F9DD``). Nothing else in the branch is
touched: the ``cmp eax, ebx`` that accepts mode 1 stays where it is, ``ebx`` is still 1 on entry
to `startRecording`, and the ``TheGameLogic+0x114`` test above is left alone.

``0x0077EA45`` - the ``call`` that asks for the file's base name is retargeted to the second
routine. Stock, that name is the localized ``GUI:LastReplay`` for *every* recording, so each game
overwrites ``Last Replay.BfME2Replay``. The routine writes ``YYYY-MM-DD HH-MM-SS <map>`` instead,
so a skirmish keeps its recording - and so does everything else.

**By default every recording is renamed** (``rename="all"``). A fixed name means each game
destroys the last one, and it means every player's replay of the same match is called the same
thing, which is what makes them awkward to collect. The cost is the replay menu's **Save Replay**
button (command 7, ``0x00817D0E``): it copies ``Last Replay.BfME2Replay`` to a name typed by the
user, so with nothing at that path it reports ``APT:ReplaySaveErrorMessageBox``. That button
exists only to rescue a file before it is overwritten, which is the problem this removes.

``rename="added"`` is the conservative alternative: only the modes this patch enables get the new
name, and a game the stock engine would have recorded anyway keeps the stock one byte for byte,
Save Replay included. It costs one extra decision at the top of the routine, which reads
`startRecording`'s own second argument - the game mode, and the value written into the header -
and tail-jumps to the original helper when it is not one of ours.

.. warning::

   That decision must **not** read `RecorderClass::m_gameMode`. `updateRecord` caches the mode
   there before calling `startRecording`, but `startRecording`'s first act is ``reset()``
   (vtable ``+0x24``), which tail-jumps to ``0x0077D7C1`` and writes the sentinel **9** over it
   forty bytes before the file is named. Reading that field falls back to the stock name on
   every single skirmish, silently.

**Why the call site and not the helper.** ``0x0077DEFD`` has that second caller. Patching the
helper would rename the file *and* change what the menu looks for; patching the call site inside
`startRecording` changes only what is written.

**The map comes from the `GameInfo`, not from `TheWritableGlobalData`.** `startNewGame` moves the
staged map name out of ``GlobalData+0xAC0`` and clears it, so whether that field still holds the
map at this moment depends on whether the logic dispatcher ran before the recorder. The `GameInfo`
is set by the menu, before the message, and is the same object the metadata string's ``M=`` field
comes from - so the name always agrees with the header.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The engine bytes it edits - nine at ``0x0077F910`` and five at
``0x0077EA45`` - are touched by no other bundled patch. It stacks with ``replay-outcome``, which
hooks ``0x0077F98B`` at the *other* end of the same function; a skirmish then records **and**
carries the verdict, which is the one combination that lets `sage_replay` resolve a game against
an AI at all (the concession heuristic cannot, because an AI issues no orders).

Section layout, at the base::

    +0x00  systemtime   16 bytes, the SYSTEMTIME `GetLocalTime` fills
    +0x10  rename_all   dword, 1 when every recording is renamed (what `verify` reads back)
    +0x14  mode_count   dword
    +0x18  mode_table   MAX_MODES dwords - the added `MSG_NEW_GAME` game modes
    +0x38  empty        one NUL: the narrow empty string used when there is no map
    +0x3c  format       the wide `swprintf` format
    ...    map          MAP_MAX wide chars - the sanitised map basename
    ...    name         NAME_MAX wide chars - the assembled base name
    ...    gate code    the whitelist routine
    ...    name code    the base-name routine
"""

from __future__ import annotations

import argparse
import struct

from ..addresses import (
    GAME_INFO_MAP,
    GAME_MODE_SKIRMISH,
    IMPORT_GET_LOCAL_TIME,
    IMPORT_SWPRINTF,
    RECORDER_LAST_REPLAY_NAME,
    RECORDER_MODE_GATE,
    RECORDER_MODE_GATE_ACCEPT,
    RECORDER_MODE_GATE_BYTES,
    RECORDER_MODE_GATE_REJECT,
    RECORDER_NAME_CALL,
    RECORDER_NAME_CALL_BYTES,
    RECORDER_NAME_CALL_FINGERPRINT,
    RECORDER_NEW_GAME_BRANCH,
    RECORDER_NEW_GAME_BRANCH_BYTES,
    RECORDER_RECORDED_MODES,
    START_RECORDING_MODE_ARG,
    THE_GAME_INFO,
    THE_SKIRMISH_GAME_INFO,
    UNICODE_STRING_FROM_WIDE,
)
from ..asm import JA, JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "DEFAULT_MODES",
    "FORMAT",
    "GATE_CODE_OFF",
    "ILLEGAL_CHARACTERS",
    "MAP_MAX",
    "MAX_MODES",
    "MODE_COUNT_OFF",
    "MODE_TABLE_OFF",
    "NAME_CODE_OFF",
    "NAME_MAX",
    "RENAME_ADDED",
    "RENAME_ALL",
    "RENAME_ALL_OFF",
    "SECTION_NAME",
    "SkirmishReplayPatch",
    "build_section",
]

SECTION_NAME = ".rpskir"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ | MEM_WRITE - the timestamp and both string
# buffers are written every time a recording starts, so the section cannot be read-only.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

#: The `MSG_NEW_GAME` game modes to record on top of the stock `{1, 5}`. 2 is what the skirmish
#: setup screen emits.
DEFAULT_MODES = (GAME_MODE_SKIRMISH,)

#: How many modes the table has room for. The whole emitter enum is 0..7, of which the stock
#: recorder already takes two and two more are the shell and playback, so eight is generous.
MAX_MODES = 8

#: Which recordings get a timestamp+map name. ``all`` is the default: the fixed `Last Replay`
#: name means every game overwrites the last one, and a file every player has under the same
#: name is exactly what makes replays hard to collect. ``added`` renames only the modes this
#: patch enables, leaving network recordings byte-identical to stock - the conservative choice
#: if the replay menu's Save Replay button matters more than shareable names.
RENAME_ALL = "all"
RENAME_ADDED = "added"

#: The base name, formatted by `swprintf`. Sorts chronologically, and the map is last so a long
#: name is what gets truncated. `%s` is a wide string - the cave widens the map itself rather
#: than leaning on `%S`, whose narrow-to-wide conversion is locale-dependent.
FORMAT = "%04d-%02d-%02d %02d-%02d-%02d %s"

#: Characters Windows forbids in a file name, replaced by `_`. The cave also substitutes
#: anything outside printable ASCII, which is what keeps the widening it does exact.
ILLEGAL_CHARACTERS = '<>:"/\\|?*'
_SUBSTITUTE = "_"

#: Wide-character capacities, terminator included.
MAP_MAX = 64
NAME_MAX = 128

# `SYSTEMTIME` field offsets - the four the name uses plus the two it does not.
_ST_YEAR = 0x00
_ST_MONTH = 0x02
_ST_DAY = 0x06
_ST_HOUR = 0x08
_ST_MINUTE = 0x0A
_ST_SECOND = 0x0C
_ST_LEN = 0x10

SYSTEMTIME_OFF = 0x00
RENAME_ALL_OFF = _ST_LEN
MODE_COUNT_OFF = RENAME_ALL_OFF + 4
MODE_TABLE_OFF = MODE_COUNT_OFF + 4
EMPTY_OFF = MODE_TABLE_OFF + MAX_MODES * 4
FORMAT_OFF = EMPTY_OFF + 4  # the NUL byte, padded back to alignment

_FORMAT_BYTES = FORMAT.encode("utf-16-le") + b"\x00\x00"
MAP_OFF = FORMAT_OFF + len(_FORMAT_BYTES) + (-len(_FORMAT_BYTES) % 4)
NAME_OFF = MAP_OFF + MAP_MAX * 2
GATE_CODE_OFF = NAME_OFF + NAME_MAX * 2

#: The window the whitelist routine gets, so both entry points are constants a caller (and
#: :meth:`SkirmishReplayPatch.verify`) can name without re-deriving one from the other's length.
GATE_CODE_MAX = 0x80
NAME_CODE_OFF = GATE_CODE_OFF + GATE_CODE_MAX

# The mode the stock whitelist tail tests, taken from the bytes being replaced rather than
# written down twice: `cmp eax, imm8` is `83 F8 <imm>`.
_STOCK_TAIL_MODE = RECORDER_MODE_GATE_BYTES[2]


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _build_gate_code(base_va: int, count_va: int, table_va: int) -> bytes:
    """The whitelist routine. Entered by a `jmp` that replaced ``cmp eax, 5`` / ``jne``, with
    `eax` holding the game mode and the recorder's loop state live in `ebx`/`esi`/`edi`/`ebp` -
    so only `ecx` and `edx` are borrowed, and both are given back on every path."""
    a = Asm(base_va + GATE_CODE_OFF)

    # The mode the replaced bytes tested. Mode 1 is not re-tested here: the `cmp eax, ebx` that
    # accepts it is still in the engine, above the bytes this patch took.
    a.emit(0x83, 0xF8, _STOCK_TAIL_MODE)  # cmp eax, 5
    a.jcc(JE, "accept")

    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(0x8B, 0x0D, _u32(count_va))  # mov ecx, [mode_count]
    a.emit(0xBA, _u32(table_va))  # mov edx, mode_table

    a.label("scan")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "reject")
    a.emit(0x3B, 0x02)  # cmp eax, [edx]
    a.jcc(JE, "hit")
    a.emit(0x83, 0xC2, 0x04)  # add edx, 4
    a.emit(0x49)  # dec ecx
    a.jmp("scan")

    a.label("hit")
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.label("accept")
    a.jmp_absolute(RECORDER_MODE_GATE_ACCEPT)

    a.label("reject")
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.jmp_absolute(RECORDER_MODE_GATE_REJECT)
    return a.finish()


def _build_name_code(base_va: int, rename_all: bool = True) -> bytes:
    """The base-name routine, in the place of `getLastReplayFileName`.

    cdecl with one argument - the uninitialised `UnicodeString` storage `startRecording` wants
    the name constructed into - which the caller cleans, and which it returns in `eax`. It
    borrows `ebx`/`esi`/`edi` and restores them, because the stock helper is a normal function
    and its caller assumes the same.

    When ``rename_all`` is false the routine first decides whether this recording is one of the
    modes the patch enabled, and tail-jumps to the stock helper if not. When it is true - the
    default - every recording is named, there is nothing to decide, and the routine never reads
    the caller's frame at all.
    """
    systemtime = base_va + SYSTEMTIME_OFF
    count_va = base_va + MODE_COUNT_OFF
    table_va = base_va + MODE_TABLE_OFF
    empty = base_va + EMPTY_OFF
    fmt = base_va + FORMAT_OFF
    map_buffer = base_va + MAP_OFF
    name_buffer = base_va + NAME_OFF

    a = Asm(base_va + NAME_CODE_OFF)

    if not rename_all:
        # `startRecording`'s own second argument - the value it writes into the header, so the
        # name and the recorded mode agree by construction.
        #
        # **Not** `TheRecorder`'s cached `m_gameMode`: `startRecording` calls `reset()` before
        # it names the file, and that overwrites the field with the sentinel 9, so reading it
        # here falls back to the stock name on every skirmish.
        a.emit(0x8B, 0x45, START_RECORDING_MODE_ARG)  # mov eax, [ebp+0x0c]
        a.emit(0x51)  # push ecx
        a.emit(0x52)  # push edx
        a.emit(0x8B, 0x0D, _u32(count_va))  # mov ecx, [mode_count]
        a.emit(0xBA, _u32(table_va))  # mov edx, mode_table

        a.label("scan")
        a.emit(0x85, 0xC9)  # test ecx, ecx
        a.jcc(JE, "miss")
        a.emit(0x3B, 0x02)  # cmp eax, [edx]
        a.jcc(JE, "ours")
        a.emit(0x83, 0xC2, 0x04)  # add edx, 4
        a.emit(0x49)  # dec ecx
        a.jmp("scan")

        a.label("miss")
        a.emit(0x5A)  # pop edx
        a.emit(0x59)  # pop ecx
        # A tail-jump, not a call: the argument is still on the stack exactly as the helper
        # wants it, its `ret` returns to `startRecording`, and its `eax` is already the answer.
        a.jmp_absolute(RECORDER_LAST_REPLAY_NAME)

        a.label("ours")
        a.emit(0x5A)  # pop edx
        a.emit(0x59)  # pop ecx

    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    # From here the argument is at [esp+0x10]: three saves, then the return address.

    a.emit(0x68, _u32(systemtime))  # push &systemtime
    a.emit(0xFF, 0x15, _u32(IMPORT_GET_LOCAL_TIME))  # call [GetLocalTime]  (stdcall)

    a.emit(0x8B, 0x0D, _u32(THE_GAME_INFO))  # mov ecx, [TheGameInfo]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JNE, "have_info")
    a.emit(0x8B, 0x0D, _u32(THE_SKIRMISH_GAME_INFO))  # mov ecx, [TheSkirmishGameInfo]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "no_map")

    a.label("have_info")
    a.emit(0x8B, 0xB1, _u32(GAME_INFO_MAP))  # mov esi, [ecx+0x40]   ; AsciiString m_map
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "no_map")
    a.emit(0x83, 0xC6, 0x08)  # add esi, 8            ; the characters
    a.jmp("basename")

    a.label("no_map")
    a.emit(0xBE, _u32(empty))  # mov esi, empty

    # `M=` carries `maps/map mp westfold`, and a separator is not a legal file-name character,
    # so the name is taken from after the last one rather than sanitised into `maps_map...`.
    a.label("basename")
    a.emit(0x8B, 0xDE)  # mov ebx, esi          ; best so far
    a.emit(0x8B, 0xFE)  # mov edi, esi          ; the cursor

    a.label("separator")
    a.emit(0x8A, 0x07)  # mov al, [edi]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "copy_init")
    a.emit(0x47)  # inc edi
    a.emit(0x3C, ord("/"))  # cmp al, '/'
    a.jcc(JE, "mark")
    a.emit(0x3C, ord("\\"))  # cmp al, '\'
    a.jcc(JNE, "separator")
    a.label("mark")
    a.emit(0x8B, 0xDF)  # mov ebx, edi
    a.jmp("separator")

    a.label("copy_init")
    a.emit(0x8B, 0xF3)  # mov esi, ebx          ; source = the basename
    a.emit(0xBF, _u32(map_buffer))  # mov edi, map
    a.emit(0xB9, _u32(MAP_MAX - 1))  # mov ecx, MAP_MAX-1    ; room for the terminator
    a.emit(0x33, 0xDB)  # xor ebx, ebx          ; where the last '.' landed, 0 = none

    a.label("copy")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "copy_done")
    a.emit(0x0F, 0xB6, 0x06)  # movzx eax, byte [esi]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "copy_done")
    a.emit(0x46)  # inc esi
    # `GameInfo::m_map` is a full path with the file on the end
    # (`maps\map wor forlindon\map wor forlindon.map`), so remember where an extension would
    # start; the copy is truncated there rather than carrying `.map` into the middle of the
    # replay's own name.
    a.emit(0x83, 0xF8, ord("."))  # cmp eax, '.'
    a.jcc(JNE, "not_dot")
    a.emit(0x8B, 0xDF)  # mov ebx, edi
    a.label("not_dot")
    # Outside printable ASCII the byte's meaning depends on the ANSI code page, which is not
    # something a file name should inherit - substitute rather than guess at a widening.
    a.emit(0x83, 0xF8, 0x20)  # cmp eax, ' '
    a.jcc(JB, "substitute")
    a.emit(0x83, 0xF8, 0x7E)  # cmp eax, '~'
    a.jcc(JA, "substitute")
    for character in ILLEGAL_CHARACTERS:
        a.emit(0x83, 0xF8, ord(character))  # cmp eax, <illegal>
        a.jcc(JE, "substitute")
    a.jmp("store")

    a.label("substitute")
    a.emit(0xB8, _u32(ord(_SUBSTITUTE)))  # mov eax, '_'

    a.label("store")
    a.emit(0x66, 0x89, 0x07)  # mov word [edi], ax
    a.emit(0x83, 0xC7, 0x02)  # add edi, 2
    a.emit(0x49)  # dec ecx
    a.jmp("copy")

    a.label("copy_done")
    # Truncate at the last '.', unless there was none or it was the first character (a name
    # that is nothing but an extension is not improved by becoming empty).
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "terminate")
    a.emit(0x81, 0xFB, _u32(map_buffer))  # cmp ebx, map
    a.jcc(JE, "terminate")
    a.emit(0x8B, 0xFB)  # mov edi, ebx

    a.label("terminate")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x66, 0x89, 0x07)  # mov word [edi], ax    ; terminate

    # cdecl and variadic, so the caller cleans all nine dwords. The `SYSTEMTIME` fields are
    # 16-bit; they are zero-extended here because a variadic `%d` reads a full dword.
    a.emit(0x68, _u32(map_buffer))  # push map
    for offset in (_ST_SECOND, _ST_MINUTE, _ST_HOUR, _ST_DAY, _ST_MONTH, _ST_YEAR):
        a.emit(0x0F, 0xB7, 0x05, _u32(systemtime + offset))  # movzx eax, word [systemtime+n]
        a.emit(0x50)  # push eax
    a.emit(0x68, _u32(fmt))  # push format
    a.emit(0x68, _u32(name_buffer))  # push name
    a.emit(0xFF, 0x15, _u32(IMPORT_SWPRINTF))  # call [swprintf]
    a.emit(0x83, 0xC4, 0x24)  # add esp, 0x24         ; 9 dwords

    a.emit(0x8B, 0x4C, 0x24, 0x10)  # mov ecx, [esp+0x10]   ; the storage
    a.emit(0x68, _u32(name_buffer))  # push name
    a.call_absolute(UNICODE_STRING_FROM_WIDE)  # ret 4: it cleans its own argument

    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]      ; return the storage
    a.emit(0xC3)  # ret
    return a.finish()


def build_section(
    base_va: int, modes: tuple[int, ...] = DEFAULT_MODES, rename_all: bool = True
) -> bytes:
    """The whole ``.rpskir`` payload: the mode table, the buffers, then the two routines."""
    body = bytearray(GATE_CODE_OFF)
    struct.pack_into("<I", body, RENAME_ALL_OFF, int(rename_all))
    struct.pack_into("<I", body, MODE_COUNT_OFF, len(modes))
    struct.pack_into(f"<{len(modes)}I", body, MODE_TABLE_OFF, *modes)
    body[FORMAT_OFF : FORMAT_OFF + len(_FORMAT_BYTES)] = _FORMAT_BYTES

    gate = _build_gate_code(base_va, base_va + MODE_COUNT_OFF, base_va + MODE_TABLE_OFF)
    if len(gate) > GATE_CODE_MAX:
        raise ValueError(f"the whitelist routine is {len(gate)} bytes, over the {GATE_CODE_MAX}")
    body += gate + b"\xcc" * (GATE_CODE_MAX - len(gate))
    return bytes(body) + _build_name_code(base_va, rename_all)


class SkirmishReplayPatch(Patch):
    name = "skirmish-replay"
    author = "officialNecro"
    description = (
        "Record single-player skirmish games, which the stock engine does not, and name each "
        "recording by timestamp and map instead of overwriting Last Replay"
    )

    def __init__(
        self,
        modes: tuple[int, ...] | list[int] = DEFAULT_MODES,
        rename: str = RENAME_ALL,
    ) -> None:
        if rename not in (RENAME_ALL, RENAME_ADDED):
            raise ValueError(f"rename must be {RENAME_ALL!r} or {RENAME_ADDED!r}, got {rename!r}")
        self.rename = rename
        self.modes = tuple(dict.fromkeys(modes))  # de-duplicated, order preserved
        if not self.modes:
            raise ValueError("at least one game mode must be added")
        if len(self.modes) > MAX_MODES:
            raise ValueError(f"at most {MAX_MODES} modes fit in the table, got {len(self.modes)}")
        for mode in self.modes:
            if not 0 < mode < 256:
                raise ValueError(f"game mode {mode} is outside the 1..255 the emitters use")
            if mode in RECORDER_RECORDED_MODES:
                raise ValueError(
                    f"game mode {mode} is already recorded by the stock engine; adding it here "
                    "would only change what its recordings are named"
                )

    @property
    def rename_all(self) -> bool:
        return self.rename == RENAME_ALL

    def __str__(self) -> str:
        modes = ", ".join(str(mode) for mode in self.modes)
        return f"{self.name} (modes {modes}, rename {self.rename})"

    def apply(self, data: bytearray) -> None:
        gate_off = va_to_offset(data, RECORDER_MODE_GATE)
        name_off = va_to_offset(data, RECORDER_NAME_CALL)
        if gate_off is None or name_off is None:
            raise ValueError(
                f"{RECORDER_MODE_GATE:#010x}/{RECORDER_NAME_CALL:#010x} is not mapped - not the "
                "expected build"
            )
        # Both sites are unremarkable bytes on their own - a `cmp eax, 5` and a `call`. What
        # says which ones they are is the code around them, so that is checked first, and
        # before anything is written.
        self._check_new_game_branch(data)
        self._check_name_call(data)

        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base: build_section(base, self.modes, self.rename_all),
            _CHARACTERISTICS,
        )
        jump = b"\xe9" + struct.pack("<i", section_va + GATE_CODE_OFF - (RECORDER_MODE_GATE + 5))
        apply_byte_patch(
            data,
            gate_off,
            RECORDER_MODE_GATE_BYTES,
            # The gate is nine bytes and the jump is five; the rest are `nop` rather than
            # anything cleverer, because nothing branches into them - the only way in is the
            # fall-through this jump replaces.
            jump + b"\x90" * (len(RECORDER_MODE_GATE_BYTES) - len(jump)),
            "recorder game-mode whitelist -> skirmish-replay gate",
        )
        call = b"\xe8" + struct.pack("<i", section_va + NAME_CODE_OFF - (RECORDER_NAME_CALL + 5))
        apply_byte_patch(
            data,
            name_off,
            RECORDER_NAME_CALL_BYTES,
            call,
            "startRecording's getLastReplayFileName call -> skirmish-replay naming",
        )

    @staticmethod
    def _check_new_game_branch(data: bytes | bytearray) -> None:
        """Raise unless the whole `MSG_NEW_GAME` branch is still what it was: the message-type
        compare, the argument fetch, the two rejects, the `TheGameLogic` test and the accept of
        mode 1. Those 63 bytes are what make the nine after them the mode whitelist."""
        off = va_to_offset(data, RECORDER_NEW_GAME_BRANCH)
        if off is None:
            raise ValueError("RecorderClass::updateRecord is not mapped - not the expected build")
        got = bytes(data[off : off + len(RECORDER_NEW_GAME_BRANCH_BYTES)])
        if got != RECORDER_NEW_GAME_BRANCH_BYTES:
            raise ValueError(
                f"{RECORDER_NEW_GAME_BRANCH:#010x} does not match the MSG_NEW_GAME branch "
                "(cmp eax, 0x1E; getArgument(0); the 4/7 rejects; TheGameLogic+0x114 == 3) - "
                "the nine bytes after it are not the game-mode whitelist"
            )

    @staticmethod
    def _check_name_call(data: bytes | bytearray) -> None:
        """Raise unless the retargeted `call` is still the one `startRecording` makes to name
        the file - `lea eax, [ebp-0x14]` / `push eax` before it, `pop ecx` and the assignment
        into `m_fileName` after.

        The call's own five bytes are deliberately **not** compared: this runs from
        :meth:`verify` too, where they are the hook. Everything around them is untouched by the
        patch, which is what lets one check serve both."""
        split = RECORDER_NAME_CALL_FINGERPRINT.index(RECORDER_NAME_CALL_BYTES)
        start = RECORDER_NAME_CALL - split
        off = va_to_offset(data, start)
        if off is None:
            raise ValueError("RecorderClass::startRecording is not mapped - not the expected build")
        end = split + len(RECORDER_NAME_CALL_BYTES)
        for at, expected in (
            (0, RECORDER_NAME_CALL_FINGERPRINT[:split]),
            (end, RECORDER_NAME_CALL_FINGERPRINT[end:]),
        ):
            got = bytes(data[off + at : off + at + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{start + at:#010x} is {got.hex()}, expected {expected.hex()} - this is "
                    "not startRecording's getLastReplayFileName call"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located

        gate_off = va_to_offset(data, RECORDER_MODE_GATE)
        name_off = va_to_offset(data, RECORDER_NAME_CALL)
        if gate_off is None or name_off is None:
            return [f"{RECORDER_MODE_GATE:#010x} is not mapped by any section"]

        if data[gate_off] != 0xE9:
            problems.append(f"{RECORDER_MODE_GATE:#010x} is not a jmp - the gate is not installed")
        else:
            target = RECORDER_MODE_GATE + 5 + struct.unpack_from("<i", data, gate_off + 1)[0]
            if target != section_va + GATE_CODE_OFF:
                problems.append(
                    f"the gate jumps to {target:#010x}, expected {section_va + GATE_CODE_OFF:#010x}"
                )
            padding = bytes(data[gate_off + 5 : gate_off + len(RECORDER_MODE_GATE_BYTES)])
            if padding != b"\x90" * len(padding):
                problems.append("the bytes after the gate jump are not nop")

        if data[name_off] != 0xE8:
            problems.append(f"{RECORDER_NAME_CALL:#010x} is not a call - naming is not installed")
        else:
            target = RECORDER_NAME_CALL + 5 + struct.unpack_from("<i", data, name_off + 1)[0]
            if target != section_va + NAME_CODE_OFF:
                problems.append(
                    f"naming calls {target:#010x}, expected {section_va + NAME_CODE_OFF:#010x}"
                )

        count = struct.unpack_from("<I", data, section_off + MODE_COUNT_OFF)[0]
        table = struct.unpack_from(f"<{MAX_MODES}I", data, section_off + MODE_TABLE_OFF)[:count]
        if count != len(self.modes) or table != self.modes:
            problems.append(f"the mode table is {table}, expected {self.modes}")
        stored = struct.unpack_from("<I", data, section_off + RENAME_ALL_OFF)[0]
        if bool(stored) != self.rename_all:
            was = RENAME_ALL if stored else RENAME_ADDED
            problems.append(f"the cave renames {was}, expected {self.rename}")
        at = section_off + FORMAT_OFF
        if bytes(data[at : at + len(_FORMAT_BYTES)]) != _FORMAT_BYTES:
            problems.append("the name format in the cave is not the expected one")

        try:
            self._check_new_game_branch(data)
            self._check_name_call(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> SkirmishReplayPatch | None:
        """Recognise this patch **and recover its modes and rename scope**.

        The default probe only ever recognises the default configuration, so a binary recording a
        different mode set reads as unpatched. Both settings are plain dwords the cave carries for
        its own gate to read - the mode count and table, and the rename flag - so they read
        straight back out, and :meth:`verify` then re-checks the cave and both hooks against
        them."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        _section_va, section_off, _vsize = located
        try:
            count = struct.unpack_from("<I", data, section_off + MODE_COUNT_OFF)[0]
            if not 0 < count <= MAX_MODES:
                return None
            modes = struct.unpack_from(f"<{count}I", data, section_off + MODE_TABLE_OFF)
            stored = struct.unpack_from("<I", data, section_off + RENAME_ALL_OFF)[0]
            patch = cls(modes=modes, rename=RENAME_ALL if stored else RENAME_ADDED)
        except (ValueError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--modes",
            default=",".join(str(mode) for mode in DEFAULT_MODES),
            metavar="N[,N...]",
            help=(
                "the MSG_NEW_GAME game modes to record on top of the stock "
                f"{','.join(str(m) for m in RECORDER_RECORDED_MODES)} (default "
                f"{','.join(str(m) for m in DEFAULT_MODES)} - skirmish)"
            ),
        )
        parser.add_argument(
            "--rename",
            choices=(RENAME_ALL, RENAME_ADDED),
            default=RENAME_ALL,
            help=(
                f"which recordings get a timestamp+map name: '{RENAME_ALL}' (default) renames "
                f"every recording, so no two replays collide and a file can be shared as-is - "
                f"at the cost of the replay menu's Save Replay button, which copies the fixed "
                f"'Last Replay' name and will report its error box. '{RENAME_ADDED}' renames "
                "only the modes --modes enables, leaving network recordings exactly as stock"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> SkirmishReplayPatch:
        return cls(
            modes=tuple(int(part) for part in args.modes.split(",") if part.strip()),
            rename=args.rename,
        )
