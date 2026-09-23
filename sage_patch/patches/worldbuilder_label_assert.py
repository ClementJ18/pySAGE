"""Stop Worldbuilder refusing a mod whose `.str` labels contain more than one colon.

Targets `Worldbuilder.exe`, an assert-enabled build. An assert inherited from EA's localisation tool
rejects labels like `CONTROLBAR:tooltip:name`, which the parser itself handles. One instruction: the
assert's second early-out becomes unconditional, jumping to `0x00BF5138` where the legal cases
already go (skipping the report gate at `0x00712DC0`).

Derivation: `../docs/worldbuilder-label-assert.md`.
"""

from __future__ import annotations

from ..patcher import Patch
from ..utils import apply_byte_patch, file_offset

__all__ = ["ASSERT_GUARD_VA", "WorldbuilderLabelAssertPatch"]

#: The second early-out, `je 0x00BF5138` as a 6-byte near jump.
ASSERT_GUARD_VA = 0x00BF505D
_ORIGINAL = bytes.fromhex("0f84d5000000")

#: `jmp 0x00BF5138` in five bytes, then a `nop` so the rewrite covers the site exactly and the
#: instruction that follows keeps its address. `0xD6 == 0x00BF5138 - (0x00BF505D + 5)`.
_PATCHED = bytes.fromhex("e9d600000090")

#: Sites that identify the guard beyond the jump's own encoding, as `(VA, bytes)`. The first is
#: the `colon == NULL` early-out immediately above it, the second is the assert's line number
#: (`0x378` is 888) and the third the expression string it reports. A build where all four agree
#: is the build these addresses were read from.
_FINGERPRINT = {
    0x00BF504A: bytes.fromhex("837dc4000f84e4000000"),  # cmp [ebp-0x3c],0 ; je 0x00BF5138
    0x00BF509E: bytes.fromhex("6878030000"),  # push 888
    0x00BF5094: bytes.fromhex("683c8ee901"),  # push "(colon==NULL) || (colon==(endOfLine-1))"
}


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
            file_offset(data, ASSERT_GUARD_VA),
            _ORIGINAL,
            _PATCHED,
            f"lotr.str label assert guard @0x{ASSERT_GUARD_VA:08x}",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            off = file_offset(data, ASSERT_GUARD_VA)
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
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the Worldbuilder these addresses were read from"
                )
