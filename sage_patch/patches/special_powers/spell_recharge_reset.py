"""Clear a player's spellbook discount when their last `SpellRechargeModifierUpgrade` goes away.

Stock, the module keeps one level counter (`Player+0x71C`) and one discount (`Player+0x718`) per
player. Losing a module (`onDelete`, `0x008B9FE0`) or handing it to another player (`onCapture`,
`0x008BA05E`) decrements the counter and writes `Percentage[level-1]` back, with the index clamped
into the list. At level 0 the clamp lands on index 0, so the player keeps the module's first
`Percentage` for the rest of the match. A tower of sorcery with `-20% -40%` leaves `-20%` behind
when the last tower falls, and a module with a single entry never comes off at all.

The patch replaces the level read that follows each decrement with a call into a cave. While the
level is still above 0 the cave returns the level, and the stock code carries on as before. At 0
or below it writes `0.0` to the discount and jumps past the stock write: to the routine's
epilogue for `onDelete`, and to the new owner's half for `onCapture`. Applies to every
`SpellRechargeModifierUpgrade` that is not targeted (`spell-recharge-targets`, whose modules never
reach these two sites). No INI change.

Derivation: `../docs/spell-recharge-reset.md`.
"""

from __future__ import annotations

import struct

from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section

__all__ = ["SECTION_NAME", "SITES", "SpellRechargeResetPatch", "build_code"]

SECTION_NAME = ".sprrst"

#: `Player+0x71C`, the level counter, and `Player+0x718`, the discount.
PLAYER_RECHARGE_LEVEL = 0x71C
PLAYER_RECHARGE_DISCOUNT = 0x718
#: `Player::getRechargeLevel`: `mov eax, [ecx+0x71C] / ret`.
PLAYER_GET_RECHARGE_LEVEL = 0x006AAAD9
#: `Player::decRechargeLevel`.
PLAYER_DEC_RECHARGE_LEVEL = 0x006AAAE7

#: Each site: the `call getRechargeLevel` right after a decrement, and where the cave resumes when
#: the level has reached 0. Both resume points sit at the same stack depth as the call.
#:   onDelete   0x008BA00B, resume 0x008BA05A (`pop esi / pop edi / leave / ret`)
#:   onCapture  0x008BA07A, resume 0x008BA0C9 (the new owner's half, then setUpgradeExecuted)
SITES: tuple[tuple[str, int, int], ...] = (
    ("onDelete", 0x008BA00B, 0x008BA05A),
    ("onCapture", 0x008BA07A, 0x008BA0C9),
)

#: The bytes the patch reads and does not write: `mov ecx, edi / call decRechargeLevel /
#: mov ecx, edi` before each site, and the instruction each resume point lands on.
_MOV_ECX_EDI = b"\x8b\xcf"
_RESUME_BYTES = {0x008BA05A: bytes.fromhex("5e5fc9c3"), 0x008BA0C9: bytes.fromhex("8b7d0c")}

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def _stock_call(site: int) -> bytes:
    return call_rel32(site, PLAYER_GET_RECHARGE_LEVEL)


def _anchor(site: int) -> bytes:
    """The nine bytes before `site`: the decrement and the `mov ecx, edi` for the level read."""
    return _MOV_ECX_EDI + call_rel32(site - 7, PLAYER_DEC_RECHARGE_LEVEL) + _MOV_ECX_EDI


def _entry(entry_va: int, resume: int) -> bytes:
    """One cave entry, called with `ecx` the player whose level was just decremented.

    Level above 0: return it in `eax`, as `getRechargeLevel` does. Otherwise: zero the discount,
    drop the return address and jump to `resume`."""
    head = b"".join(
        (
            b"\x8b\x81" + struct.pack("<I", PLAYER_RECHARGE_LEVEL),  # mov eax, [ecx+0x71C]
            b"\x85\xc0",  # test eax, eax
            b"\x7e\x01",  # jle zero
            b"\xc3",  # ret
            # zero:
            b"\xc7\x81"
            + struct.pack("<I", PLAYER_RECHARGE_DISCOUNT)
            + b"\x00" * 4,  # mov [ecx+0x718], 0
            b"\x83\xc4\x04",  # add esp, 4
        )
    )
    jmp_at = entry_va + len(head)
    return head + b"\xe9" + struct.pack("<i", resume - (jmp_at + 5))


def build_code(base_va: int) -> tuple[bytes, tuple[int, ...]]:
    """The cave's bytes at `base_va`, and each site's entry address in `SITES` order."""
    code = b""
    entries: list[int] = []
    for _name, _site, resume in SITES:
        entries.append(base_va + len(code))
        code += _entry(base_va + len(code), resume)
    return code, tuple(entries)


class SpellRechargeResetPatch(Patch):
    name = "spell-recharge-reset"
    author = "officialNecro"
    description = (
        "Clear a player's SpellRechargeModifierUpgrade discount when the last module counting "
        "towards it is deleted or captured. Stock, the level drops to 0 but the discount is set to "
        "the module's first Percentage, so the spellbook keeps the first level for the rest of "
        "the match. Logic-side: every peer needs the same binary. No INI change"
    )
    runtime_verified = "partly"

    def apply(self, data: bytearray) -> None:
        self._check_sites(data)
        cave_va = allocate_section(
            data, SECTION_NAME, lambda va: build_code(va)[0], _CHARACTERISTICS
        )
        _code, entries = build_code(cave_va)
        for (which, site, _resume), entry in zip(SITES, entries, strict=True):
            apply_byte_patch(
                data,
                file_offset(data, site),
                _stock_call(site),
                call_rel32(site, entry),
                f"SpellRechargeModifierUpgrade {which}: level 0 clears the discount",
            )

    @staticmethod
    def _check_sites(data: bytes | bytearray) -> None:
        """Raise unless each site follows the decrement and each resume point is the stock
        instruction the cave relies on landing on."""
        for which, site, resume in SITES:
            want = _anchor(site)
            off = file_offset(data, site - len(want))
            got = bytes(data[off : off + len(want)])
            if got != want:
                raise ValueError(
                    f"@0x{site - len(want):08x}: expected the {which} level decrement "
                    f"{want.hex()}, got {got.hex()} - not the expected build"
                )
            expected = _RESUME_BYTES[resume]
            off = file_offset(data, resume)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"@0x{resume:08x}: expected {expected.hex()} where {which} resumes, got "
                    f"{got.hex()} - not the expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        code, entries = build_code(cave_va)
        problems: list[str] = []
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routine in {SECTION_NAME} is not the one this patch builds")
        for (which, site, _resume), entry in zip(SITES, entries, strict=True):
            want = call_rel32(site, entry)
            off = file_offset(data, site)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(
                    f"@0x{site:08x}: {which}'s level read does not call {SECTION_NAME} "
                    f"(holds {got.hex()})"
                )
        return problems
