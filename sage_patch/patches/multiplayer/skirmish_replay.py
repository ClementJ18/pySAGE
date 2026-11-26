"""Record single-player skirmish games, under a unique name.

The recorder only starts for the two network game modes, so a skirmish (mode 2) is never recorded,
though every later step already handles it. A `.rpskir` section holds a mode table and a name
buffer: the whitelist tail (`0x0077F910`) jumps to a routine that also accepts the table's modes,
and a second edit names each recording by timestamp and map instead of overwriting `Last Replay`. By
default network recordings are renamed too, which costs the replay menu's Save Replay button.
Before each recording is named, the oldest timestamp-named replays are deleted so only the newest
`keep` remain (10 by default; 0 keeps everything). Files of any other name are never touched.

Derivation: `../docs/skirmish-replay.md`.
"""

from __future__ import annotations

import argparse
import struct

from ...addresses import (
    DELETE_FILE_W_IAT,
    FIND_CLOSE_IAT,
    FIND_FIRST_FILE_W_IAT,
    FIND_NEXT_FILE_W_IAT,
    GAME_INFO_MAP,
    GAME_MODE_SKIRMISH,
    IMPORT_GET_LOCAL_TIME,
    IMPORT_SWPRINTF,
    IMPORT_WCSCMP,
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
    START_RECORDING_REPLAY_DIR,
    THE_GAME_INFO,
    THE_SKIRMISH_GAME_INFO,
    UNICODE_STRING_FROM_WIDE,
)
from ...asm import JA, JB, JE, JGE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, u32, va_to_offset

__all__ = [
    "DEFAULT_KEEP",
    "DEFAULT_MODES",
    "DIR_MAX",
    "FORMAT",
    "GATE_CODE_OFF",
    "ILLEGAL_CHARACTERS",
    "KEEP_OFF",
    "MAP_MAX",
    "MAX_DELETES",
    "MAX_MODES",
    "MODE_COUNT_OFF",
    "MODE_TABLE_OFF",
    "NAME_CODE_MAX",
    "NAME_CODE_OFF",
    "NAME_MAX",
    "NAME_TEMPLATE",
    "PRUNE_CODE_OFF",
    "PRUNE_DATA_OFF",
    "REPLAY_PATTERN",
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

#: Which recordings get a timestamp+map name. `all` is the default: the fixed `Last Replay`
#: name means every game overwrites the last one, and a file every player has under the same
#: name is exactly what makes replays hard to collect. `added` renames only the modes this
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
#: `SkirmishReplayPatch.verify`) can name without re-deriving one from the other's length.
GATE_CODE_MAX = 0x80
NAME_CODE_OFF = GATE_CODE_OFF + GATE_CODE_MAX

#: The naming routine's window, and after it the pruning routine's. Everything above this point
#: is laid out exactly as before pruning existed, so a binary patched without it still reads
#: back through `detect`.
NAME_CODE_MAX = 0x200
PRUNE_CODE_OFF = NAME_CODE_OFF + NAME_CODE_MAX
PRUNE_CODE_MAX = 0x200
PRUNE_DATA_OFF = PRUNE_CODE_OFF + PRUNE_CODE_MAX

#: How many timestamp-named replays survive a new recording, the new one included. 0 turns the
#: pruning off.
DEFAULT_KEEP = 10

#: The most files one recording start deletes. Deleting the oldest takes a fresh directory scan
#: each time, so a first run over a large backlog is capped rather than allowed to stall the
#: loading screen; the rest go over the following games. It is also what ends the loop if a
#: `DeleteFileW` reports success on a file another process keeps open (a pending delete still
#: lists).
MAX_DELETES = 256

#: What a file name must start with to count as one of the patch's own: `#` is any ASCII digit,
#: every other character literal. It is `FORMAT`'s timestamp and the space before the map, so
#: `Last Replay`, a replay saved under a typed name, and anything downloaded or renamed are
#: never counted and never deleted.
NAME_TEMPLATE = "####-##-## ##-##-## "

#: The scan's wildcard, appended to the replay directory. The extension is `getReplayExtension`'s
#: literal (`0x00C2EEB4`).
REPLAY_PATTERN = "*.BfME2Replay"

#: The longest replay directory the routine will scan, in characters. A longer one skips the
#: pruning rather than overrun the path buffer.
DIR_MAX = 200

# `WIN32_FIND_DATAW`: `dwFileAttributes` first, `cFileName[MAX_PATH]` at +0x2C, 592 bytes in all.
_WFD_ATTRIBUTES = 0x00
_WFD_FILE_NAME = 0x2C
_WFD_LEN = 0x250
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_MAX_PATH = 260

# The pruning data, relative to `PRUNE_DATA_OFF`.
KEEP_OFF = PRUNE_DATA_OFF
_COUNT_OFF = KEEP_OFF + 4
_DIR_END_OFF = _COUNT_OFF + 4
_BUDGET_OFF = _DIR_END_OFF + 4
_PATTERN_OFF = _BUDGET_OFF + 4
_PATTERN_BYTES = REPLAY_PATTERN.encode("utf-16-le") + b"\x00\x00"
_TEMPLATE_OFF = _PATTERN_OFF + 0x20
_TEMPLATE_BYTES = NAME_TEMPLATE.encode("ascii")
_WFD_OFF = _TEMPLATE_OFF + 0x20
_OLDEST_OFF = _WFD_OFF + _WFD_LEN
_PATH_OFF = _OLDEST_OFF + _MAX_PATH * 2
_PRUNE_DATA_END = _PATH_OFF + (DIR_MAX + _MAX_PATH + 1) * 2

# The mode the stock whitelist tail tests, taken from the bytes being replaced rather than
# written down twice: `cmp eax, imm8` is `83 F8 <imm>`.
_STOCK_TAIL_MODE = RECORDER_MODE_GATE_BYTES[2]


def _build_gate_code(base_va: int, count_va: int, table_va: int) -> bytes:
    """The whitelist routine. Entered by a `jmp` that replaced `cmp eax, 5` / `jne`, with
    `eax` holding the game mode and the recorder's loop state live in `ebx`/`esi`/`edi`/`ebp` -
    so only `ecx` and `edx` are borrowed, and both are given back on every path."""
    a = Asm(base_va + GATE_CODE_OFF)

    # The mode the replaced bytes tested. Mode 1 is not re-tested here: the `cmp eax, ebx` that
    # accepts it is still in the engine, above the bytes this patch took.
    a.emit(0x83, 0xF8, _STOCK_TAIL_MODE)  # cmp eax, 5
    a.jcc(JE, "accept")

    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(0x8B, 0x0D, u32(count_va))  # mov ecx, [mode_count]
    a.emit(0xBA, u32(table_va))  # mov edx, mode_table

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


def _emit_wide_copy(a: Asm, label: str) -> None:
    """`esi` -> `edi`, a wide string up to and including its terminator. Both pointers end past
    it. Every source handed to it is bounded: a constant, or a `cFileName` the OS terminated
    within `MAX_PATH`."""
    a.label(label)
    a.emit(0x0F, 0xB7, 0x06)  # movzx eax, word [esi]
    a.emit(0x66, 0x89, 0x07)  # mov word [edi], ax
    a.emit(0x83, 0xC6, 0x02)  # add esi, 2
    a.emit(0x83, 0xC7, 0x02)  # add edi, 2
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, label)


def _build_prune_code(base_va: int) -> bytes:
    """Delete the oldest timestamp-named replays until fewer than `keep` remain.

    A plain near function (`call` / `ret`, no arguments) entered from the top of the naming
    routine, so still on `startRecording`'s `ebp` frame: the replay directory is its local
    `UnicodeString` at `[ebp-0x2C]`, already created on disk, and not yet extended by the name.
    `pushad` / `popad` give every register back, so the naming routine's own contract is
    untouched.

    Each pass scans `<dir>*.BfME2Replay`, counts the files matching `NAME_TEMPLATE` and keeps the
    lowest such name; the names begin with a zero-padded local timestamp, so the lowest is the
    oldest. If the count has reached `keep`, that file is deleted and the scan repeats. Any
    failure - no directory, an over-long one, nothing found, a delete refused, the budget spent
    - simply returns: a replay that is not pruned is never worse than a recording that does not
    start.
    """
    keep = base_va + KEEP_OFF
    count = base_va + _COUNT_OFF
    dir_end = base_va + _DIR_END_OFF
    budget = base_va + _BUDGET_OFF
    pattern = base_va + _PATTERN_OFF
    template = base_va + _TEMPLATE_OFF
    wfd = base_va + _WFD_OFF
    file_name = wfd + _WFD_FILE_NAME
    oldest = base_va + _OLDEST_OFF
    path = base_va + _PATH_OFF

    a = Asm(base_va + PRUNE_CODE_OFF)
    a.emit(0x60)  # pushad
    # One more than the deletes allowed: the budget is spent by the `dec` ahead of each.
    a.emit(0xC7, 0x05, u32(budget), u32(MAX_DELETES + 1))  # mov dword [budget], MAX+1

    # The directory, copied once; each pass rewrites only what follows it.
    a.emit(0x8B, 0x45, START_RECORDING_REPLAY_DIR & 0xFF)  # mov eax, [ebp-0x2c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "out")  # an empty UnicodeString: no directory to scan
    a.emit(0x8D, 0x70, 0x08)  # lea esi, [eax+8]      ; the characters
    a.emit(0xBF, u32(path))  # mov edi, path
    a.emit(0xB9, u32(DIR_MAX))  # mov ecx, DIR_MAX
    a.label("dir")
    a.emit(0x0F, 0xB7, 0x06)  # movzx eax, word [esi]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "dir_done")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "out")  # longer than DIR_MAX: leave it alone
    a.emit(0x66, 0x89, 0x07)  # mov word [edi], ax
    a.emit(0x83, 0xC6, 0x02)  # add esi, 2
    a.emit(0x83, 0xC7, 0x02)  # add edi, 2
    a.emit(0x49)  # dec ecx
    a.jmp("dir")
    a.label("dir_done")
    a.emit(0x89, 0x3D, u32(dir_end))  # mov [dir_end], edi

    a.label("scan")
    a.emit(0x8B, 0x3D, u32(dir_end))  # mov edi, [dir_end]
    a.emit(0xBE, u32(pattern))  # mov esi, pattern
    _emit_wide_copy(a, "append_pattern")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0xA3, u32(count))  # mov [count], eax
    a.emit(0x66, 0xA3, u32(oldest))  # mov word [oldest], ax  ; none yet
    a.emit(0x68, u32(wfd))  # push &wfd
    a.emit(0x68, u32(path))  # push path
    a.emit(0xFF, 0x15, u32(FIND_FIRST_FILE_W_IAT))  # call [FindFirstFileW]  (stdcall)
    a.emit(0x83, 0xF8, 0xFF)  # cmp eax, INVALID_HANDLE_VALUE
    a.jcc(JE, "out")
    a.emit(0x8B, 0xD8)  # mov ebx, eax          ; the find handle

    a.label("entry")
    a.emit(0xF6, 0x05, u32(wfd + _WFD_ATTRIBUTES), _FILE_ATTRIBUTE_DIRECTORY)  # test byte
    a.jcc(JNE, "next")
    a.emit(0xBE, u32(file_name))  # mov esi, cFileName
    a.emit(0xBF, u32(template))  # mov edi, template
    a.emit(0xB9, u32(len(NAME_TEMPLATE)))  # mov ecx, len(template)
    a.label("match")
    a.emit(0x0F, 0xB7, 0x06)  # movzx eax, word [esi]
    a.emit(0x0F, 0xB6, 0x17)  # movzx edx, byte [edi]
    a.emit(0x83, 0xFA, ord("#"))  # cmp edx, '#'
    a.jcc(JNE, "literal")
    a.emit(0x83, 0xE8, ord("0"))  # sub eax, '0'
    a.emit(0x83, 0xF8, 0x09)  # cmp eax, 9
    a.jcc(JA, "next")  # unsigned: below '0' wraps high
    a.jmp("matched_char")
    a.label("literal")
    a.emit(0x3B, 0xC2)  # cmp eax, edx
    a.jcc(JNE, "next")
    a.label("matched_char")
    a.emit(0x83, 0xC6, 0x02)  # add esi, 2
    a.emit(0x47)  # inc edi
    a.emit(0x49)  # dec ecx
    a.jcc(JNE, "match")

    a.emit(0xFF, 0x05, u32(count))  # inc dword [count]
    a.emit(0x66, 0x83, 0x3D, u32(oldest), 0x00)  # cmp word [oldest], 0
    a.jcc(JE, "take")
    a.emit(0x68, u32(oldest))  # push oldest
    a.emit(0x68, u32(file_name))  # push cFileName
    a.emit(0xFF, 0x15, u32(IMPORT_WCSCMP))  # call [wcscmp]  (cdecl)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JGE, "next")  # not older than the oldest so far
    a.label("take")
    a.emit(0xBE, u32(file_name))  # mov esi, cFileName
    a.emit(0xBF, u32(oldest))  # mov edi, oldest
    _emit_wide_copy(a, "copy_oldest")

    a.label("next")
    a.emit(0x68, u32(wfd))  # push &wfd
    a.emit(0x53)  # push ebx
    a.emit(0xFF, 0x15, u32(FIND_NEXT_FILE_W_IAT))  # call [FindNextFileW]  (stdcall)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "entry")
    a.emit(0x53)  # push ebx
    a.emit(0xFF, 0x15, u32(FIND_CLOSE_IAT))  # call [FindClose]  (stdcall)

    # The new recording is about to make one more, so the count may reach keep - 1.
    a.emit(0xA1, u32(keep))  # mov eax, [keep]
    a.emit(0x3B, 0x05, u32(count))  # cmp eax, [count]
    a.jcc(JA, "out")  # keep > count: room enough
    a.emit(0xFF, 0x0D, u32(budget))  # dec dword [budget]
    a.jcc(JE, "out")
    a.emit(0x8B, 0x3D, u32(dir_end))  # mov edi, [dir_end]
    a.emit(0xBE, u32(oldest))  # mov esi, oldest
    _emit_wide_copy(a, "append_oldest")
    a.emit(0x68, u32(path))  # push path
    a.emit(0xFF, 0x15, u32(DELETE_FILE_W_IAT))  # call [DeleteFileW]  (stdcall)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "scan")  # deleted: count again

    a.label("out")
    a.emit(0x61)  # popad
    a.emit(0xC3)  # ret
    return a.finish()


def _build_name_code(base_va: int, rename_all: bool = True, prune: bool = False) -> bytes:
    """The base-name routine, in the place of `getLastReplayFileName`.

    cdecl with one argument - the uninitialised `UnicodeString` storage `startRecording` wants
    the name constructed into - which the caller cleans, and which it returns in `eax`. It
    borrows `ebx`/`esi`/`edi` and restores them, because the stock helper is a normal function
    and its caller assumes the same.

    When `rename_all` is false the routine first decides whether this recording is one of the
    modes the patch enabled, and tail-jumps to the stock helper if not. When it is true - the
    default - every recording is named, there is nothing to decide, and the routine never reads
    the caller's frame at all.

    When `prune` is set the routine first calls the pruning routine, before deciding anything:
    it only ever deletes timestamp-named files, so it is as safe ahead of a `Last Replay`
    recording as ahead of one of its own.
    """
    systemtime = base_va + SYSTEMTIME_OFF
    count_va = base_va + MODE_COUNT_OFF
    table_va = base_va + MODE_TABLE_OFF
    empty = base_va + EMPTY_OFF
    fmt = base_va + FORMAT_OFF
    map_buffer = base_va + MAP_OFF
    name_buffer = base_va + NAME_OFF

    a = Asm(base_va + NAME_CODE_OFF)

    if prune:
        a.call_absolute(base_va + PRUNE_CODE_OFF)

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
        a.emit(0x8B, 0x0D, u32(count_va))  # mov ecx, [mode_count]
        a.emit(0xBA, u32(table_va))  # mov edx, mode_table

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

    a.emit(0x68, u32(systemtime))  # push &systemtime
    a.emit(0xFF, 0x15, u32(IMPORT_GET_LOCAL_TIME))  # call [GetLocalTime]  (stdcall)

    a.emit(0x8B, 0x0D, u32(THE_GAME_INFO))  # mov ecx, [TheGameInfo]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JNE, "have_info")
    a.emit(0x8B, 0x0D, u32(THE_SKIRMISH_GAME_INFO))  # mov ecx, [TheSkirmishGameInfo]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "no_map")

    a.label("have_info")
    a.emit(0x8B, 0xB1, u32(GAME_INFO_MAP))  # mov esi, [ecx+0x40]   ; AsciiString m_map
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "no_map")
    a.emit(0x83, 0xC6, 0x08)  # add esi, 8            ; the characters
    a.jmp("basename")

    a.label("no_map")
    a.emit(0xBE, u32(empty))  # mov esi, empty

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
    a.emit(0xBF, u32(map_buffer))  # mov edi, map
    a.emit(0xB9, u32(MAP_MAX - 1))  # mov ecx, MAP_MAX-1    ; room for the terminator
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
    a.emit(0xB8, u32(ord(_SUBSTITUTE)))  # mov eax, '_'

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
    a.emit(0x81, 0xFB, u32(map_buffer))  # cmp ebx, map
    a.jcc(JE, "terminate")
    a.emit(0x8B, 0xFB)  # mov edi, ebx

    a.label("terminate")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x66, 0x89, 0x07)  # mov word [edi], ax    ; terminate

    # cdecl and variadic, so the caller cleans all nine dwords. The `SYSTEMTIME` fields are
    # 16-bit; they are zero-extended here because a variadic `%d` reads a full dword.
    a.emit(0x68, u32(map_buffer))  # push map
    for offset in (_ST_SECOND, _ST_MINUTE, _ST_HOUR, _ST_DAY, _ST_MONTH, _ST_YEAR):
        a.emit(0x0F, 0xB7, 0x05, u32(systemtime + offset))  # movzx eax, word [systemtime+n]
        a.emit(0x50)  # push eax
    a.emit(0x68, u32(fmt))  # push format
    a.emit(0x68, u32(name_buffer))  # push name
    a.emit(0xFF, 0x15, u32(IMPORT_SWPRINTF))  # call [swprintf]
    a.emit(0x83, 0xC4, 0x24)  # add esp, 0x24         ; 9 dwords

    a.emit(0x8B, 0x4C, 0x24, 0x10)  # mov ecx, [esp+0x10]   ; the storage
    a.emit(0x68, u32(name_buffer))  # push name
    a.call_absolute(UNICODE_STRING_FROM_WIDE)  # ret 4: it cleans its own argument

    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]      ; return the storage
    a.emit(0xC3)  # ret
    return a.finish()


def _pad(code: bytes, window: int, what: str) -> bytes:
    if len(code) > window:
        raise ValueError(f"the {what} routine is {len(code)} bytes, over the {window:#x}")
    return code + b"\xcc" * (window - len(code))


def build_section(
    base_va: int,
    modes: tuple[int, ...] = DEFAULT_MODES,
    rename_all: bool = True,
    keep: int = DEFAULT_KEEP,
) -> bytes:
    """The whole `.rpskir` payload: the mode table, the buffers, the three routines, then the
    pruning data. The pruning routine and its data are laid out even when `keep` is 0, and only
    the call into it is left out, so the layout never depends on the configuration."""
    body = bytearray(GATE_CODE_OFF)
    struct.pack_into("<I", body, RENAME_ALL_OFF, int(rename_all))
    struct.pack_into("<I", body, MODE_COUNT_OFF, len(modes))
    struct.pack_into(f"<{len(modes)}I", body, MODE_TABLE_OFF, *modes)
    body[FORMAT_OFF : FORMAT_OFF + len(_FORMAT_BYTES)] = _FORMAT_BYTES

    gate = _build_gate_code(base_va, base_va + MODE_COUNT_OFF, base_va + MODE_TABLE_OFF)
    body += _pad(gate, GATE_CODE_MAX, "whitelist")
    body += _pad(_build_name_code(base_va, rename_all, keep > 0), NAME_CODE_MAX, "naming")
    body += _pad(_build_prune_code(base_va), PRUNE_CODE_MAX, "pruning")

    data = bytearray(_PRUNE_DATA_END - PRUNE_DATA_OFF)
    struct.pack_into("<I", data, KEEP_OFF - PRUNE_DATA_OFF, keep)
    at = _PATTERN_OFF - PRUNE_DATA_OFF
    data[at : at + len(_PATTERN_BYTES)] = _PATTERN_BYTES
    at = _TEMPLATE_OFF - PRUNE_DATA_OFF
    data[at : at + len(_TEMPLATE_BYTES)] = _TEMPLATE_BYTES
    return bytes(body + data)


def _stored_keep(data: bytes | bytearray, section_off: int, section_size: int) -> int:
    """The keep count a cave carries, or 0 for one laid out before pruning existed."""
    if section_size < KEEP_OFF + 4:
        return 0
    return struct.unpack_from("<I", data, section_off + KEEP_OFF)[0]


class SkirmishReplayPatch(Patch):
    name = "skirmish-replay"
    author = "officialNecro"
    # The recording and the naming are live-verified; the `--keep` pruning has only run under
    # Unicorn (tests), not yet in a game.
    runtime_verified = "partly"
    description = (
        "Record single-player skirmish games, which the stock engine does not, and name each "
        "recording by timestamp and map instead of overwriting Last Replay, keeping only the "
        "newest --keep (default 10) of those. No INI change; the default --rename all renames "
        "network recordings too, which costs the replay menu's Save Replay button"
    )

    def __init__(
        self,
        modes: tuple[int, ...] | list[int] = DEFAULT_MODES,
        rename: str = RENAME_ALL,
        keep: int = DEFAULT_KEEP,
    ) -> None:
        if not 0 <= keep <= 0xFFFF:
            raise ValueError(f"keep must be 0 (keep everything) to 65535, got {keep}")
        self.keep = keep
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
        kept = self.keep if self.keep else "all"
        return f"{self.name} (modes {modes}, rename {self.rename}, keep {kept})"

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
            lambda base: build_section(base, self.modes, self.rename_all, self.keep),
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
        `verify` too, where they are the hook. Everything around them is untouched by the
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
        section_va, section_off, section_size = located

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
        problems.extend(self._verify_prune(data, section_va, section_off, section_size))

        try:
            self._check_new_game_branch(data)
            self._check_name_call(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems

    def _verify_prune(
        self, data: bytes | bytearray, section_va: int, section_off: int, section_size: int
    ) -> list[str]:
        """The keep count, and whether the naming routine calls the pruning one. A cave written
        before pruning existed ends with the naming routine; it reads as `keep=0`."""
        stored = _stored_keep(data, section_off, section_size)
        if stored != self.keep:
            return [f"the cave keeps {stored or 'all'} replays, expected {self.keep or 'all'}"]
        if not self.keep:
            return []
        problems: list[str] = []
        expected = build_section(section_va, self.modes, self.rename_all, self.keep)
        for start, end, what in (
            (NAME_CODE_OFF, NAME_CODE_OFF + 5, "the call into the pruning routine"),
            (PRUNE_CODE_OFF, PRUNE_DATA_OFF, "the pruning routine"),
            (_PATTERN_OFF, _WFD_OFF, "the pruning pattern and name template"),
        ):
            got = bytes(data[section_off + start : section_off + end])
            if got != expected[start:end]:
                problems.append(f"{what} is not the expected code")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> SkirmishReplayPatch | None:
        """Recognise this patch **and recover its modes and rename scope**.

        The default probe only ever recognises the default configuration, so a binary recording a
        different mode set reads as unpatched. Both settings are plain dwords the cave carries for
        its own gate to read - the mode count and table, and the rename flag - so they read
        straight back out, and `verify` then re-checks the cave and both hooks against
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
            keep = _stored_keep(data, section_off, _vsize)
            patch = cls(modes=modes, rename=RENAME_ALL if stored else RENAME_ADDED, keep=keep)
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
            "--keep",
            type=int,
            default=DEFAULT_KEEP,
            metavar="N",
            help=(
                "how many timestamp-named replays to keep, the new one included: when a "
                "recording starts, the oldest beyond that are deleted from Replays\\ (default "
                f"{DEFAULT_KEEP}; 0 keeps everything). Only names the patch itself writes - "
                "'YYYY-MM-DD HH-MM-SS <map>' - are ever counted or deleted; rename a replay to "
                "keep it"
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
            keep=args.keep,
        )
