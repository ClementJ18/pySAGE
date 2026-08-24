"""The quiet-exit patch: no crash dump for a normal quit.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The addresses are named in
``../addresses.py`` and the reasoning is in ``../docs/quiet-exit.md``.

**The defect.** The engine raises its own "Game crash" exception (`DEBUG_CRASH_EXCEPTION_CODE`,
``0x04560123``) from `Debug::crash` when a `DEBUG_CRASH`/assert trips, and a benign one trips on the
shutdown path every time the game is closed. The exception reaches the unhandled-exception filter at
`0x0043D610` (the `SetUnhandledExceptionFilter` target), which writes a minidump before letting the
process die. So a clean exit through the menu's exit button leaves a `.dmp` in the working directory
every single time - an artifact that looks like a crash and, with `crash-dump` applied, is now a
large one.

**What this does.** Redirects the filter's one `call writeMiniDump` (at
`WRITE_MINI_DUMP_CALL_FILTER`) through a tiny appended cave that first asks whether the process is
quitting. If it is, the dump is skipped; if it is not - a real fault mid-game - the call is made
exactly as before.

* The discriminator is `GameEngine::m_quitting`, the byte at ``[GAME_ENGINE] +
  GAME_ENGINE_QUITTING`` that the main loop reads to decide whether to keep running. It is set true
  when the app is asked to exit and stays true through teardown, and it is false for the whole of a
  live game - so gating on it can only ever drop a dump the game is already exiting past, never one
  from a fault in play.
* The cave is `call`-ed in place of `writeMiniDump`, so the filter's return address (the
  `add esp, 8` at `WRITE_MINI_DUMP_CALL_FILTER` + 5) is on the stack when the cave runs. On the
  write path the cave **tail-jumps** to `writeMiniDump`, which therefore sees the identical frame it
  would have from a direct call and returns straight to the filter. On the skip path the cave
  `ret`s, and the filter's own `add esp, 8` balances the two arguments the call site had already
  pushed. Either way the stack is exactly what the stock code expects at the instruction after the
  call.

**Crash-time safety.** The cave runs inside a process that has already raised an exception, so it is
leaf code: no allocation, no CRT, no locks, no loop. It reads one global and, only if that is
non-null, one byte through it; a null `GameEngine` pointer takes the write path, which is the stock
behaviour. A fault inside it costs the dump and nothing else - the filter's second-chance guard at
`0x00DC6E50` sits outside it.

**Blast radius: client-local.** Nothing here touches the simulation, the frame checksum, the order
stream or the replay format. The only site it reads or edits is the filter's dump call, which runs
only after an unhandled exception - never in a game that is not already over. Peers need not match
and replays cross both ways.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The single engine site it edits is the five bytes at
`WRITE_MINI_DUMP_CALL_FILTER`, which no other bundled patch touches - `crash-dump`, the other patch
on this path, rewrites the argument push at `MINI_DUMP_ARGS` and the raise at `DEBUG_CRASH_RAISE`
and only *reads* `writeMiniDump`'s prologue as a build anchor, none of which this patch disturbs. It
reads no structure another patch rewrites and has no INI surface.
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
    """The gate routine, for a section placed at ``base_va``.

    ``call``-ed in place of the filter's `call writeMiniDump`. `eax` is free - the stock call
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
