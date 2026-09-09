"""Refresh the persistent spellbook bar when its Object's resolved CommandSet changes.

Original RotWK game.dat 2.01.2614.37001; see ``../docs/spellbook-commandset-refresh.md``.
The stock function's game-state and player-validity gates remain in front of the hook. A player
change takes the original path. With the same non-null player, resolve the Object's current set
and compare pointers: only a difference re-enters the stock cache store / button-marking path.

Runtime-verified in ordinary play, online multiplayer and replay playback for CommandSet switching,
including the CommandButtons extension and repeated observer/player changes. The supported use is
the exact reference build, identical multiplayer binaries and permanently granted PlayerUpgrades.
The stock CommandSetUpgrade UI tail stays untouched.
"""

from __future__ import annotations

import struct

from ..addresses import (
    COMMAND_SET_STORE_FIND_COMMAND_SET,
    OBJECT_GET_COMMAND_SET_STRING,
    PLAYER_GET_SPELLBOOK_OBJECT,
    SPELLBOOK_UI_CACHE,
    SPELLBOOK_UI_CACHE_HOOK,
    SPELLBOOK_UI_CACHE_PLAYER_CHANGED,
    SPELLBOOK_UI_CACHE_REBUILD,
    SPELLBOOK_UI_CACHE_RETURN,
    SPELLBOOK_UI_UPDATE_CACHE_CALL,
    SPELLBOOK_UI_UPDATE_COMMAND_BUTTON,
    THE_COMMAND_SET_STORE,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "CACHE_BYTES",
    "HOOK_BYTES",
    "SECTION_NAME",
    "SpellbookCommandSetRefreshPatch",
    "build_guard",
]

SECTION_NAME = ".sbcsref"
_CHARACTERISTICS = 0x60000060  # executable/read-only, no persistent state
_CACHED_PLAYER = 0x28
_CACHED_COMMAND_SET = 0x2C
HOOK_BYTES = bytes.fromhex("3b7e287455")  # cmp edi,[esi+28]; je <return>

# The complete stock cache function, including the gates before the hook, the null checks,
# 33-byte marking loop and both epilogues. Only HOOK_BYTES are replaced in apply / verify.
CACHE_BYTES = bytes.fromhex(
    "568bf18b0d2c41de0057e8bb0bb1ff84c00f84830000008b0d5049de0085c97409"
    "e88e0eb1ff84c075708b0d2849de00e86e78d7ff8bf885ff740d8bcfe87a9cd7ff"
    "84c0750233ff3b7e28745583662c0085ff897e28744a8bcfe803c1d7ff85c0743f"
    "8bc8e86b05d6ff8b0d4477de0050e896dfdeff8d7e308d4e513bf989462c741f"
    "2bcf8bd1c1e902b801010101f3ab8bca83e103f3aaeb088366280083662c005f5ec3"
)

# Untouched build anchors pin the caller's use of the cached pointer and the helpers' ABI.
# The getter is excluded: commandset-button-upgrade legitimately detours it, and the cave calls
# that same public entry so an overlay remains visible. Its target is pinned by CACHE_BYTES.
ANCHORS = {
    SPELLBOOK_UI_UPDATE_CACHE_CALL - 2: bytes.fromhex("8bcbe879fcffff33c039432c8945ec"),
    SPELLBOOK_UI_UPDATE_COMMAND_BUTTON: bytes.fromhex("8b4b2c568945d8e8e1b4edff"),
    PLAYER_GET_SPELLBOOK_OBJECT: bytes.fromhex(
        "558bec5151568bf183be100700000075258365fc008d45f850683cae6a008975f8"
        "e89fe9ffff8b45fc85c074098b4074898610070000ffb6100700008b0d2c41de00"
        "e842c5d9ff5ec9c3"
    ),
    COMMAND_SET_STORE_FIND_COMMAND_SET: bytes.fromhex(
        "558bec5151ff75088d45f85083c130e8c8e4ebff8b45f885c074058b4008eb0233c0c9c20400"
    ),
}


def build_guard(base_va: int) -> bytes:
    """ESI = UI, EDI = validated Player; enter by JMP with stock saves still on stack.

    ESI/EDI are callee-saved by the helpers; no extra frame is needed. findCommandSet pops its
    one argument (ret 4). EAX/ECX/EDX and flags are volatile at the stock epilogue. The rebuild
    entry expects EAX = resolved CommandSet and overwrites EDI for its existing marking loop.
    """
    a = Asm(base_va)
    a.emit(b"\x3b\x7e", _CACHED_PLAYER)
    a.jcc(JNE, "player_changed")
    a.emit(b"\x85\xff")  # never query a null Player
    a.jcc(JE, "done")
    a.emit(b"\x8b\xcf")
    a.call_absolute(PLAYER_GET_SPELLBOOK_OBJECT)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "compare")  # absent Object resolves to null; no dereference
    a.emit(b"\x8b\xc8")
    a.call_absolute(OBJECT_GET_COMMAND_SET_STRING)
    a.emit(b"\x8b\x0d", struct.pack("<I", THE_COMMAND_SET_STORE))
    a.emit(0x50)
    a.call_absolute(COMMAND_SET_STORE_FIND_COMMAND_SET)
    a.label("compare")
    a.emit(b"\x3b\x46", _CACHED_COMMAND_SET)
    a.jcc(JE, "done")
    a.jmp_absolute(SPELLBOOK_UI_CACHE_REBUILD)
    a.label("player_changed")
    a.jmp_absolute(SPELLBOOK_UI_CACHE_PLAYER_CHANGED)
    a.label("done")
    a.jmp_absolute(SPELLBOOK_UI_CACHE_RETURN)
    return a.finish()


def _detour(section_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", section_va - (SPELLBOOK_UI_CACHE_HOOK + 5))


def _site_problems(data: bytes | bytearray, hook: bytes) -> list[str]:
    expected_cache = bytearray(CACHE_BYTES)
    at = SPELLBOOK_UI_CACHE_HOOK - SPELLBOOK_UI_CACHE
    expected_cache[at : at + len(HOOK_BYTES)] = hook
    problems: list[str] = []
    for va, expected in {SPELLBOOK_UI_CACHE: bytes(expected_cache), **ANCHORS}.items():
        off = va_to_offset(data, va)
        if off is None or bytes(data[off : off + len(expected)]) != expected:
            problems.append(f"0x{va:08x}: not the expected game.dat spellbook cache bytes")
    return problems


class SpellbookCommandSetRefreshPatch(Patch):
    """Rebuild the left spellbook bar only when its player or resolved CommandSet changes."""

    name = "spellbook-commandset-refresh"
    author = "Ostkannit"
    description = (
        "Makes the CommandSetUpgrade work for the Spellbook-Object "
        "by letting the game refresh its cache afterwards"
    )

    def apply(self, data: bytearray) -> None:
        problems = _site_problems(data, HOOK_BYTES)
        if problems:
            raise ValueError("; ".join(problems))
        section_va = allocate_section(data, SECTION_NAME, build_guard, _CHARACTERISTICS)
        off = va_to_offset(data, SPELLBOOK_UI_CACHE_HOOK)
        assert off is not None  # checked before allocation
        apply_byte_patch(data, off, HOOK_BYTES, _detour(section_va), "spellbook cache -> set check")

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located
        expected = build_guard(section_va)
        problems = _site_problems(data, _detour(section_va))
        if vsize != len(expected) or bytes(data[section_off : section_off + vsize]) != expected:
            problems.append(f"{SECTION_NAME} does not hold the expected spellbook cache guard")
        return problems
