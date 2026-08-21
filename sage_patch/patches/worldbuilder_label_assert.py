"""The `.str` label assert that stops Worldbuilder opening a mod with multi-colon labels.

**This patch targets `Worldbuilder.exe`, not `game.dat`.**

`Worldbuilder.exe` is an assert-enabled build - it prints ``_INTERNAL defined.`` on its second
line - so `DEBUG_CRASH` is *live* in it and compiled out of the shipping `game.dat`. That single
asymmetry is why a mod can run in the game and refuse to open in the editor, and this is one of
the asserts that difference exposes.

`GameText.cpp:888` requires every label in `data\\lotr.str` to be exactly ``[file]:[name]``: it
searches for a **second** colon and insists there is none, or that it is the last character on the
line. Edain's string table carries 108 labels that break that rule - ``CONTROLBAR:tooltip:
horrortiefen``, ``SCRIPT:interface:level1``, and so on - and the editor stops on the first one,
0.1 s into startup, before any INI is read:

    Assertion failed in ...GameClient\\GameText.cpp, line 888
    expression (colon==NULL) || (colon==(endOfLine-1)): Label 'CONTROLBAR:tooltip:horrortiefen'
    in file 'data\\lotr.str, line 49269 does not match '[file]:[name]' format: Too many colons.
    Babylon can't process this file.

The complaint is about **Babylon**, EA's localisation tool, not about the engine: the parser
splits on the *first* colon and takes the rest as the name either way, which is why the same
table loads in the game without comment. Nothing downstream of the assert reads the second colon.

The guard is the ordinary `DEBUG_CRASH` shape - two early-outs for the legal cases, then the
report block:

    00bf5047  mov  [ebp-0x3c], eax      ; colon = strchr(afterFirstColon, ':')
    00bf504a  cmp  dword [ebp-0x3c], 0  ; colon == NULL?
    00bf504e  je   0x00BF5138           ;   -> fine, carry on
    00bf5054  mov  eax, [ebp-0x18]      ; endOfLine
    00bf5057  sub  eax, 1
    00bf505a  cmp  [ebp-0x3c], eax      ; colon == endOfLine-1?
    00bf505d  je   0x00BF5138           ;   -> fine, carry on
    00bf5063  push 0                    ; else: is the assert suppressed?
    00bf5065  call 0x00712DC0
    ...
    00bf509e  push 0x378                ; line 888
    00bf5138                            ; <- where both legal cases land

So the whole patch is **one instruction**: make the second early-out unconditional, and the third
case joins the two that were already fine. `0x00BF5138` is the label the legal paths already jump
to, so this adds no new control flow - it takes an existing edge unconditionally.

**Why not fix the string table instead.** Renaming 108 labels means renaming every
`CommandButton`/script reference to them as well, in both language trees, for a rule that only
EA's internal tool ever enforced. And it would have to be redone for every label a translator adds
later. The assert is the thing that is wrong for a mod, so the assert is what moves.

**Scope.** This silences exactly one assert. Others in the same build stay live, which is
deliberate - they are the editor's early warning about real data problems, and the shipped
`Worldbuilder.dbgcmd` (``debug.errors -``) is the blunt instrument for turning the lot off.
"""

from __future__ import annotations

from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["ASSERT_GUARD_VA", "WorldbuilderLabelAssertPatch"]

#: The second early-out, ``je 0x00BF5138`` as a 6-byte near jump.
ASSERT_GUARD_VA = 0x00BF505D
_ORIGINAL = bytes.fromhex("0f84d5000000")

#: ``jmp 0x00BF5138`` in five bytes, then a `nop` so the rewrite covers the site exactly and the
#: instruction that follows keeps its address. ``0xD6 == 0x00BF5138 - (0x00BF505D + 5)``.
_PATCHED = bytes.fromhex("e9d600000090")

#: Sites that identify the guard beyond the jump's own encoding, as ``(VA, bytes)``. The first is
#: the `colon == NULL` early-out immediately above it, the second is the assert's line number
#: (``0x378`` is 888) and the third the expression string it reports. A build where all four agree
#: is the build these addresses were read from.
_FINGERPRINT = {
    0x00BF504A: bytes.fromhex("837dc4000f84e4000000"),  # cmp [ebp-0x3c],0 ; je 0x00BF5138
    0x00BF509E: bytes.fromhex("6878030000"),  # push 888
    0x00BF5094: bytes.fromhex("683c8ee901"),  # push "(colon==NULL) || (colon==(endOfLine-1))"
}


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off


class WorldbuilderLabelAssertPatch(Patch):
    """Let Worldbuilder open a mod whose `.str` labels carry more than one colon."""

    name = "worldbuilder-label-assert"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): stop the GameText.cpp:888 assert rejecting lotr.str "
        "labels with more than one colon, which halts the editor during startup before any INI "
        "is read. Needs no INI or .str change - the parser already splits on the first colon, "
        "and the game build never asserted because DEBUG_CRASH is compiled out of it"
    )

    def apply(self, data: bytearray) -> None:
        self._check_fingerprint(data)
        apply_byte_patch(
            data,
            _offset(data, ASSERT_GUARD_VA),
            _ORIGINAL,
            _PATCHED,
            f"lotr.str label assert guard @0x{ASSERT_GUARD_VA:08x}",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            off = _offset(data, ASSERT_GUARD_VA)
        except ValueError as exc:
            return [str(exc)]
        got = bytes(data[off : off + len(_PATCHED)])
        if got == _PATCHED:
            return []
        if got == _ORIGINAL:
            return [f"the guard @0x{ASSERT_GUARD_VA:08x} is unpatched"]
        return [
            f"the guard @0x{ASSERT_GUARD_VA:08x} is {got.hex()}, expected {_PATCHED.hex()} "
            f"(patched) or {_ORIGINAL.hex()} (stock)"
        ]

    @staticmethod
    def _check_fingerprint(data: bytes | bytearray) -> None:
        for va, expected in _FINGERPRINT.items():
            off = _offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the Worldbuilder these addresses were read from"
                )
