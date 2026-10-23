"""Stop a map's `PlayerAIType` blocks outliving the map.

`ThePlayerAITypeSet` is not an `Overridable` store: a `map.ini` `PlayerAIType` block is parsed
straight over the global record of the same name, and the set's `reset` does nothing. So a map
that sets `LibraryMap = NONE` - or a fortress map pointing every faction at its fortress library -
changes the AI of every later match in the session, until the game is restarted.

The fix re-reads the global file the blocks come from, `Data\\INI\\PlayerAITypes.ini`, at the top of
the map-INI loader, before the new map's `map.ini` is read. The record parser replaces an entry
whole, so every type the file defines gets its global value back, and the new map's own blocks
then apply over it exactly as before. A type that only some `map.ini` defined stays defined; only
a map naming it can use it. When the file does not exist the cave does nothing.

Derivation: `../docs/player-ai-type-reset.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    ASCII_STRING_CTOR,
    ASCII_STRING_CTOR_ENTRY,
    FILE_SYSTEM,
    FILE_SYSTEM_DOES_FILE_EXIST,
    FILE_SYSTEM_DOES_FILE_EXIST_ENTRY,
    GAME_LOGIC_LOAD_MAP_INI,
    GAME_LOGIC_LOAD_MAP_INI_CALL,
    GAME_LOGIC_LOAD_MAP_INI_CALL_BYTES,
    GAME_LOGIC_LOAD_MAP_INI_ENTRY,
    GAME_LOGIC_LOAD_MAP_INI_RESUME,
    GAME_LOGIC_LOAD_MAP_INI_RESUME_BYTES,
    INI_CTOR,
    INI_CTOR_ENTRY,
    INI_DTOR,
    INI_DTOR_ENTRY,
    INI_LOAD,
    INI_LOAD_CREATE_OVERRIDES,
    INI_LOAD_ENTRY,
    INI_OBJECT_SIZE,
    PLAYER_AI_TYPE_SET_RESET,
    PLAYER_AI_TYPE_SET_RESET_SLOT,
    PLAYER_AI_TYPE_SET_VTABLE,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, u32, va_to_offset

__all__ = [
    "ANCHORS",
    "GLOBAL_FILE",
    "HOOK_VA",
    "SECTION_NAME",
    "PlayerAiTypeResetPatch",
    "build_code",
]

SECTION_NAME = ".aitypes"  # 8 chars: the PE name field holds exactly 8

#: The file the global `PlayerAIType` blocks are read from, as the engine spells its INI paths
#: (`Data\INI\Eva.ini`). Lookup is case-insensitive and goes through the mod directory and the
#: archives like any other INI.
GLOBAL_FILE = b"Data\\INI\\PlayerAITypes.ini\x00"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - code and the path string, never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = GAME_LOGIC_LOAD_MAP_INI

#: The first bytes at each address the cave calls or returns to, and the caller that proves the
#: hooked loader is the one `startNewGame` runs. The hook's own bytes are asserted by
#: `apply_byte_patch`. The set's empty `reset` is anchored through its vtable slot, because it is
#: the reason the patch exists: a build whose `reset` does something needs no patch.
ANCHORS = {
    GAME_LOGIC_LOAD_MAP_INI_RESUME: GAME_LOGIC_LOAD_MAP_INI_RESUME_BYTES,
    GAME_LOGIC_LOAD_MAP_INI_CALL: GAME_LOGIC_LOAD_MAP_INI_CALL_BYTES,
    FILE_SYSTEM_DOES_FILE_EXIST: FILE_SYSTEM_DOES_FILE_EXIST_ENTRY,
    INI_CTOR: INI_CTOR_ENTRY,
    INI_DTOR: INI_DTOR_ENTRY,
    INI_LOAD: INI_LOAD_ENTRY,
    ASCII_STRING_CTOR: ASCII_STRING_CTOR_ENTRY,
    PLAYER_AI_TYPE_SET_VTABLE + PLAYER_AI_TYPE_SET_RESET_SLOT: u32(PLAYER_AI_TYPE_SET_RESET),
    PLAYER_AI_TYPE_SET_RESET: b"\xc3",
}


def build_code(base_va: int) -> bytes:
    """The cave: reload the global file, then run the loader's own first instruction and go on.

    Reached by a `jmp` from the loader's entry, so `[esp]` is `startNewGame`'s return address and
    `ecx` is `this`. `pushad` keeps both, and every register, for the stock body."""
    a = Asm(base_va)
    path_va = base_va  # the string leads the section so its address does not depend on the code
    a.emit(GLOBAL_FILE)
    a.label("entry")
    a.emit(0x60)  # pushad
    a.emit(0x81, 0xEC, u32(INI_OBJECT_SIZE))  # sub esp, sizeof(INI)
    # A mod may keep its AI types elsewhere; then there is nothing to put back.
    a.emit(0x68, u32(path_va))  # push path
    a.emit(0x8B, 0x0D, u32(FILE_SYSTEM))  # mov ecx, [TheFileSystem]
    a.call_absolute(FILE_SYSTEM_DOES_FILE_EXIST)  # ret 4
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "done")
    a.emit(0x8B, 0xCC)  # mov ecx, esp          ; the INI object
    a.call_absolute(INI_CTOR)
    # INI::load(AsciiString(path), INI_LOAD_CREATE_OVERRIDES, NULL), laid out as the stock loader
    # lays out its map.ini call; the callee pops all three and destroys the string.
    a.emit(0x6A, 0x00)  # push 0                 ; Xfer *
    a.emit(0x6A, INI_LOAD_CREATE_OVERRIDES)  # push 2
    a.emit(0x51)  # push ecx                     ; the AsciiString's slot
    a.emit(0x8B, 0xCC)  # mov ecx, esp
    a.emit(0x68, u32(path_va))  # push path
    a.call_absolute(ASCII_STRING_CTOR)  # ret 4
    a.emit(0x8D, 0x4C, 0x24, 0x0C)  # lea ecx, [esp+0xc]  ; the INI object again
    a.call_absolute(INI_LOAD)  # ret 0xc
    a.emit(0x8B, 0xCC)  # mov ecx, esp
    a.call_absolute(INI_DTOR)
    a.label("done")
    a.emit(0x81, 0xC4, u32(INI_OBJECT_SIZE))  # add esp, sizeof(INI)
    a.emit(0x61)  # popad
    a.emit(GAME_LOGIC_LOAD_MAP_INI_ENTRY)  # mov eax, <SEH table>  ; the displaced instruction
    a.jmp_absolute(GAME_LOGIC_LOAD_MAP_INI_RESUME)
    return a.finish()


def _entry_va(base_va: int) -> int:
    return base_va + len(GLOBAL_FILE)


class PlayerAiTypeResetPatch(Patch):
    name = "player-ai-type-reset"
    author = "officialNecro"
    description = (
        "Put every PlayerAIType back to its global definition before each map's map.ini is read, "
        "so a map that changes an AI type's LibraryMap - a campaign map's LibraryMap = NONE, a "
        "fortress map's fortress libraries - no longer changes the AI of every later match until "
        "the game is restarted. Reloads Data\\INI\\PlayerAITypes.ini; a mod that keeps its "
        "PlayerAIType blocks elsewhere is left stock. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", _entry_va(section_va) - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            GAME_LOGIC_LOAD_MAP_INI_ENTRY,
            jump,
            "map-INI loader entry -> player-ai-type-reset cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the map-INI "
                    "loader or the functions the cave calls are not this build's"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            return [f"{HOOK_VA:#010x} is not a jmp - the hook is not installed"]
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != _entry_va(section_va):
            problems.append(f"hook jumps to {target:#010x}, expected {_entry_va(section_va):#010x}")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected code")
        return problems
