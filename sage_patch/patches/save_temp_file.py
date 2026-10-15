"""Write a save to `<name>.tmp` and move it over the real file only once it is complete.

`GameState::saveGame` opens the destination itself and writes straight into it. When a subsystem's
save code fails, the `catch (...)` around the chunk loop - which under VC++ 7.1 also catches an
access violation - closes the file and returns, leaving a half-written save under the player's
chosen name. Saving over an existing slot destroys the old save before the new one exists.

Four hooks put the save through a temporary file instead:

- **open**: the `LOCAL_FILE_SYSTEM_OPEN_WIDE` call is given `<path>.tmp` (wide, like the
  engine's own path). A path too long for the buffer, or empty, opens as stock and is never renamed.
- **done**: after the file is closed on success, `MoveFileExW(tmp, path, REPLACE_EXISTING |
  WRITE_THROUGH)` puts it in place. The engine never imports `MoveFileExW`, so it is resolved once
  through `GetModuleHandleA("kernel32.dll")` and `GetProcAddress`.
- **both catch handlers**: after the file is closed, `DeleteFileW(tmp)`.

So a failed save leaves the previous save untouched and no partial file behind. A rename that
fails (the target locked by another program) leaves the complete save in `<name>.tmp` and the old
one in place. The `.tmp` suffix follows the engine's extension, so the save menu never lists it.
Derivation: `../docs/living-campaign/wotr-save-failure.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    DELETE_FILE_W_IAT,
    GAME_STATE_SAVE_CATCH_CLOSE,
    GAME_STATE_SAVE_CATCH_CLOSE_RESUME,
    GAME_STATE_SAVE_CATCH_CLOSE_RESUME_BYTES,
    GAME_STATE_SAVE_CLOSE_BYTES,
    GAME_STATE_SAVE_DONE_CLOSE,
    GAME_STATE_SAVE_DONE_CLOSE_RESUME,
    GAME_STATE_SAVE_DONE_CLOSE_RESUME_BYTES,
    GAME_STATE_SAVE_FILE_STORE,
    GAME_STATE_SAVE_FILE_STORE_BYTES,
    GAME_STATE_SAVE_OPEN_CALL,
    GAME_STATE_SAVE_OPEN_CALL_BYTES,
    GAME_STATE_SAVE_OPEN_CATCH,
    GAME_STATE_SAVE_OPEN_CATCH_RESUME,
    GAME_STATE_SAVE_OPEN_CATCH_RESUME_BYTES,
    GET_MODULE_HANDLE_A_IAT,
    GET_PROC_ADDRESS_IAT,
    LOCAL_FILE_SYSTEM_OPEN_WIDE,
    LOCAL_FILE_SYSTEM_OPEN_WIDE_ENTRY,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOKS",
    "MOVE_FLAGS",
    "OFF_ACTIVE",
    "OFF_FINAL",
    "OFF_MOVE",
    "OFF_TEMP",
    "SECTION_NAME",
    "SUFFIX",
    "SaveTempFilePatch",
    "TEMP_CHARS",
    "build_section",
    "entry_points",
]

SECTION_NAME = ".svtmp"  # 6 chars: the PE name field is 8 bytes and truncates silently

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE - code plus the temp path
# buffer and the three words of state it writes.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: 1 while a temporary file is open for the save in progress, so only that save is renamed or
#: deleted.
OFF_ACTIVE = 0x00
#: `MoveFileExW`, once resolved.
OFF_MOVE = 0x04
#: The engine's own wide path for the save in progress - the rename target. It points into the
#: `UnicodeString` `saveGame` keeps alive until after the last hook.
OFF_FINAL = 0x08
OFF_KERNEL32 = 0x10
OFF_MOVE_NAME = 0x20
OFF_TEMP = 0x40
#: Wide characters in the temporary path buffer, terminator included.
TEMP_CHARS = 1024
CODE_OFFSET = OFF_TEMP + TEMP_CHARS * 2

SUFFIX = ".tmp"
KERNEL32 = b"kernel32.dll\x00"
MOVE_NAME = b"MoveFileExW\x00"
#: `MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH`.
MOVE_FLAGS = 0x1 | 0x8

#: `(hooked VA, the stock bytes there, the cave routine it reaches, how)`. The open site is a
#: `call` and stays one; the three close sites become a `jmp` padded with `nop`s.
HOOKS: tuple[tuple[int, bytes, str, str], ...] = (
    (GAME_STATE_SAVE_OPEN_CALL, GAME_STATE_SAVE_OPEN_CALL_BYTES, "open", "call"),
    (GAME_STATE_SAVE_DONE_CLOSE, GAME_STATE_SAVE_CLOSE_BYTES, "done", "jmp"),
    (GAME_STATE_SAVE_CATCH_CLOSE, GAME_STATE_SAVE_CLOSE_BYTES, "abort", "jmp"),
    (GAME_STATE_SAVE_OPEN_CATCH, GAME_STATE_SAVE_CLOSE_BYTES, "open_abort", "jmp"),
)

#: The open function the cave calls, the store that makes `[ebp-0x14]` the file the close sites
#: read, and the three instructions each close hook resumes at.
ANCHORS = {
    LOCAL_FILE_SYSTEM_OPEN_WIDE: LOCAL_FILE_SYSTEM_OPEN_WIDE_ENTRY,
    GAME_STATE_SAVE_FILE_STORE: GAME_STATE_SAVE_FILE_STORE_BYTES,
    GAME_STATE_SAVE_DONE_CLOSE_RESUME: GAME_STATE_SAVE_DONE_CLOSE_RESUME_BYTES,
    GAME_STATE_SAVE_CATCH_CLOSE_RESUME: GAME_STATE_SAVE_CATCH_CLOSE_RESUME_BYTES,
    GAME_STATE_SAVE_OPEN_CATCH_RESUME: GAME_STATE_SAVE_OPEN_CATCH_RESUME_BYTES,
}


def _block() -> bytes:
    block = bytearray(CODE_OFFSET)
    block[OFF_KERNEL32 : OFF_KERNEL32 + len(KERNEL32)] = KERNEL32
    block[OFF_MOVE_NAME : OFF_MOVE_NAME + len(MOVE_NAME)] = MOVE_NAME
    return bytes(block)


def _emit(base_va: int) -> Asm:
    active = struct.pack("<I", base_va + OFF_ACTIVE)
    move = struct.pack("<I", base_va + OFF_MOVE)
    final = struct.pack("<I", base_va + OFF_FINAL)
    temp = struct.pack("<I", base_va + OFF_TEMP)
    suffix = SUFFIX.encode("utf-16-le")

    a = Asm(base_va + CODE_OFFSET)

    # open(path, access, size), `ret 0xC` like `FileSystem::openFile` it stands in for. Copies the
    # path into the buffer with the suffix appended and opens that; `active` says whether it did.
    a.label("open")
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0x74, 0x24, 0x0C)  # mov esi, [esp+0xc]      ; path
    a.emit(0xC6, 0x05, active, 0x00)  # mov byte [active], 0
    a.emit(0x89, 0x35, final)  # mov [final], esi
    a.emit(0x66, 0x83, 0x3E, 0x00)  # cmp word [esi], 0
    a.jcc(JE, "plain")
    a.emit(0xBF, temp)  # mov edi, temp
    a.emit(0xB9, struct.pack("<I", TEMP_CHARS - len(SUFFIX) - 1))  # mov ecx, room
    a.label("copy")
    a.emit(0x66, 0x8B, 0x06)  # mov ax, [esi]
    a.emit(0x66, 0x85, 0xC0)  # test ax, ax
    a.jcc(JE, "suffix")
    a.emit(0x66, 0x89, 0x07)  # mov [edi], ax
    a.emit(0x83, 0xC6, 0x02)  # add esi, 2
    a.emit(0x83, 0xC7, 0x02)  # add edi, 2
    a.emit(0x49)  # dec ecx
    a.jcc(JNE, "copy")
    a.label("plain")  # empty or too long: the stock open, on the stock arguments
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.jmp_absolute(LOCAL_FILE_SYSTEM_OPEN_WIDE)
    a.label("suffix")
    a.emit(0xC7, 0x07, suffix[0:4])  # mov dword [edi], ".t"
    a.emit(0xC7, 0x47, 0x04, suffix[4:8])  # mov dword [edi+4], "mp"
    a.emit(0x66, 0xC7, 0x47, 0x08, 0x00, 0x00)  # mov word [edi+8], 0
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]   ; size
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]   ; access
    a.emit(0x68, temp)  # push temp
    a.call_absolute(LOCAL_FILE_SYSTEM_OPEN_WIDE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "opened")
    a.emit(0xC6, 0x05, active, 0x01)  # mov byte [active], 1
    a.label("opened")
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc

    # done: the save completed and the file is closed - move it into place.
    a.label("done")
    a.emit(GAME_STATE_SAVE_CLOSE_BYTES)  # the displaced File::close
    a.emit(0x80, 0x3D, active, 0x00)  # cmp byte [active], 0
    a.jcc(JE, "done_out")
    a.emit(0xC6, 0x05, active, 0x00)  # mov byte [active], 0
    a.emit(0x60)  # pushad
    a.call("resolve")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done_pop")
    a.emit(0x6A, MOVE_FLAGS)  # push flags
    a.emit(0xFF, 0x35, final)  # push dword [final]
    a.emit(0x68, temp)  # push temp
    a.emit(0xFF, 0xD0)  # call eax                ; MoveFileExW, stdcall
    a.label("done_pop")
    a.emit(0x61)  # popad
    a.label("done_out")
    a.jmp_absolute(GAME_STATE_SAVE_DONE_CLOSE_RESUME)

    # The two catch handlers: the save failed and the file is closed - remove what was written.
    a.label("abort")
    a.emit(GAME_STATE_SAVE_CLOSE_BYTES)
    a.call("discard")
    a.jmp_absolute(GAME_STATE_SAVE_CATCH_CLOSE_RESUME)
    a.label("open_abort")
    a.emit(GAME_STATE_SAVE_CLOSE_BYTES)
    a.call("discard")
    a.jmp_absolute(GAME_STATE_SAVE_OPEN_CATCH_RESUME)

    a.label("discard")
    a.emit(0x80, 0x3D, active, 0x00)  # cmp byte [active], 0
    a.jcc(JE, "discard_out")
    a.emit(0xC6, 0x05, active, 0x00)  # mov byte [active], 0
    a.emit(0x60)  # pushad
    a.emit(0x68, temp)  # push temp
    a.emit(0xFF, 0x15, struct.pack("<I", DELETE_FILE_W_IAT))  # call [DeleteFileW]
    a.emit(0x61)  # popad
    a.label("discard_out")
    a.emit(0xC3)  # ret

    # resolve() -> eax = MoveFileExW, or 0. Cached after the first success.
    a.label("resolve")
    a.emit(0xA1, move)  # mov eax, [move]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "resolve_out")
    a.emit(0x68, struct.pack("<I", base_va + OFF_KERNEL32))  # push "kernel32.dll"
    a.emit(0xFF, 0x15, struct.pack("<I", GET_MODULE_HANDLE_A_IAT))  # call [GetModuleHandleA]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "resolve_out")
    a.emit(0x68, struct.pack("<I", base_va + OFF_MOVE_NAME))  # push "MoveFileExW"
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x15, struct.pack("<I", GET_PROC_ADDRESS_IAT))  # call [GetProcAddress]
    a.emit(0xA3, move)  # mov [move], eax
    a.label("resolve_out")
    a.emit(0xC3)  # ret
    return a


def build_section(base_va: int) -> bytes:
    """The whole section: the state block and path buffer, then the code."""
    return _block() + _emit(base_va).finish()


def entry_points(base_va: int) -> dict[str, int]:
    """Where each routine starts, for a section at `base_va`."""
    asm = _emit(base_va)
    asm.finish()
    names = ("open", "done", "abort", "open_abort", "discard", "resolve")
    return {name: asm.label_va(name) for name in names}


def _hook_bytes(va: int, window: int, target: int, how: str) -> bytes:
    opcode = 0xE8 if how == "call" else 0xE9
    return bytes([opcode]) + struct.pack("<i", target - (va + 5)) + b"\x90" * (window - 5)


class SaveTempFilePatch(Patch):
    name = "save-temp-file"
    author = "officialNecro"
    description = (
        "Write every save game to <name>.tmp and move it over the real file only once the save "
        "has completed; a save that fails part-way deletes the temporary file instead. A failed "
        "save no longer leaves a half-written file behind or destroys the save it was replacing. "
        "No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        for va, _original, _routine, _how in HOOKS:
            if va_to_offset(data, va) is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        entries = entry_points(section_va)
        for va, original, routine, how in HOOKS:
            off = va_to_offset(data, va)
            assert off is not None
            apply_byte_patch(
                data,
                off,
                original,
                _hook_bytes(va, len(original), entries[routine], how),
                f"{routine} hook -> {self.name} cave",
            )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - saveGame is not "
                    "this build's, so a cave would return into the wrong place"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        problems: list[str] = []
        code_va = section_va + CODE_OFFSET
        code = build_section(section_va)[CODE_OFFSET:]
        start = section_off + CODE_OFFSET
        if bytes(data[start : start + len(code)]) != code:
            problems.append(
                f"the {SECTION_NAME} cave does not hold the expected code at {code_va:#x}"
            )
        entries = entry_points(section_va)
        for va, original, routine, how in HOOKS:
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} is not mapped by any section")
                continue
            expected = _hook_bytes(va, len(original), entries[routine], how)
            if bytes(data[off : off + len(expected)]) != expected:
                problems.append(f"the {routine} hook at {va:#010x} is not installed")
        return problems
