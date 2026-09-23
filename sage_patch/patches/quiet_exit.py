"""Don't write a crash dump when the game is quit normally.

A benign engine assert trips on every shutdown, and the unhandled-exception filter writes a minidump
for it. The filter's `call writeMiniDump` (`WRITE_MINI_DUMP_CALL_FILTER`) goes to a small cave that
skips the dump when the engine is quitting (`GameEngine::m_quitting`). Client-local.

Derivation: `../docs/quiet-exit.md`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import (
    GAME_ENGINE,
    GAME_ENGINE_QUITTING,
    WRITE_MINI_DUMP,
    WRITE_MINI_DUMP_CALL_FILTER,
    WRITE_MINI_DUMP_CALL_FILTER_BYTES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "SECTION_NAME",
    "QuietExitPatch",
    "build_code",
]

SECTION_NAME = ".qexit"  # 6 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ. Not writable: the cave holds only the gate routine
# and spills nothing, unlike `crash-dump`'s cave.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def build_code(base_va: int) -> bytes:
    """The gate routine, for a section placed at `base_va`.

    `call`-ed in place of the filter's `call writeMiniDump`. `eax` is free - the stock call
    discards `writeMiniDump`'s return - so the check clobbers only it, and the write path leaves the
    two pushed arguments untouched for `writeMiniDump` to read.
    """
    a = Asm(base_va)
    a.emit(0xA1, struct.pack("<I", GAME_ENGINE))  # mov eax, [TheGameEngine]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "write")  # no engine -> can't tell, write the dump (stock behaviour)
    a.emit(0x80, 0x78, GAME_ENGINE_QUITTING, 0x00)  # cmp byte [eax+0x10], 0   ; m_quitting
    a.jcc_short(JNE, "skip")  # quitting -> drop the dump
    a.label("write")
    a.jmp_absolute(WRITE_MINI_DUMP)  # tail-call: returns straight to the filter
    a.label("skip")
    a.emit(0xC3)  # ret: the filter's `add esp, 8` cleans the two pushed args
    return a.finish()


class QuietExitPatch(Patch):
    """Skip the crash minidump when the process is quitting, so a clean exit leaves no `.dmp`."""

    name = "quiet-exit"
    author = "officialNecro"
    description = (
        "Suppress the crash .dmp the engine writes when its own shutdown assert fires on a normal "
        "quit, so closing the game via the exit button leaves no dump; a real in-game fault still "
        "dumps - no INI, string table or map data to declare"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchor(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        off = va_to_offset(data, WRITE_MINI_DUMP_CALL_FILTER)
        if off is None:
            raise ValueError(
                f"{WRITE_MINI_DUMP_CALL_FILTER:#010x} is not mapped - not the expected build"
            )
        apply_byte_patch(
            data,
            off,
            WRITE_MINI_DUMP_CALL_FILTER_BYTES,
            self._call(section_va),
            "unhandled-exception filter writeMiniDump call -> quiet-exit gate",
        )

    @staticmethod
    def _call(section_va: int) -> bytes:
        """A `call rel32` from the filter's call site to the cave, the same five bytes the window
        held - only the target changes, from `writeMiniDump` to the gate."""
        rel = section_va - (WRITE_MINI_DUMP_CALL_FILTER + 5)
        return b"\xe8" + struct.pack("<i", rel)

    @staticmethod
    def _check_anchor(data: bytes | bytearray) -> None:
        off = va_to_offset(data, WRITE_MINI_DUMP_CALL_FILTER)
        if off is None:
            raise ValueError(
                f"{WRITE_MINI_DUMP_CALL_FILTER:#010x} is not mapped - not the expected build"
            )
        got = bytes(data[off : off + len(WRITE_MINI_DUMP_CALL_FILTER_BYTES)])
        if got != WRITE_MINI_DUMP_CALL_FILTER_BYTES:
            raise ValueError(
                f"{WRITE_MINI_DUMP_CALL_FILTER:#010x} holds {got.hex()}, expected "
                f"{WRITE_MINI_DUMP_CALL_FILTER_BYTES.hex()} - this build's unhandled-exception "
                "filter is not the one the gate was written against"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _vsize = located
        content = build_code(section_va)
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(f"the {SECTION_NAME} cave's gate is not the expected bytes")
        off = va_to_offset(data, WRITE_MINI_DUMP_CALL_FILTER)
        if off is None:
            return [f"{WRITE_MINI_DUMP_CALL_FILTER:#010x} is not mapped by any section"]
        if data[off] != 0xE8:
            problems.append(
                f"{WRITE_MINI_DUMP_CALL_FILTER:#010x} is not a call - the hook is absent"
            )
        else:
            reached = WRITE_MINI_DUMP_CALL_FILTER + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if reached != section_va:
                problems.append(
                    f"the filter's call reaches {reached:#010x}, expected the gate at "
                    f"{section_va:#010x}"
                )
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """No parameters: the gate is the whole patch."""

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> QuietExitPatch:
        return cls()
