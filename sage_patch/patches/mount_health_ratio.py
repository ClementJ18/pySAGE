"""Carry health across a `MountedTemplate` swap as a fraction of maximum, not as hit points.

`ToggleMountedSpecialAbilityUpdate` creates the replacement object and stores the old object's
current health on it unchanged. Two templates with different `MaxHealth` then trade hit points
at a different ratio each way, and a unit can toggle back and forth for health it never earned.
The patch replaces the `getHealth` call in both the mount and the dismount swap with a routine
that answers `old ratio x new maximum`, which the stock code then stores exactly as before.

Derivation: `../docs/mount-health-ratio.md`.
"""

from __future__ import annotations

from ..addresses import (
    BODY_GET_HEALTH_RATIO_SLOT,
    BODY_GET_MAX_HEALTH_SLOT,
    TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY,
    TOGGLE_MOUNTED_HEALTH_COPY_HOOK,
    TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE,
    TOGGLE_MOUNTED_MOUNT_HEALTH_COPY,
)
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section

__all__ = ["HOOK_SITES", "SECTION_NAME", "STOCK_HOOK", "MountHealthRatioPatch", "build_code"]

SECTION_NAME = ".mnthp"  # 6 chars: the PE name field is 8 bytes and truncates silently

#: Both health hand-overs, as the address of the stock sequence each one is part of.
SEQUENCES = (TOGGLE_MOUNTED_MOUNT_HEALTH_COPY, TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY)
#: The five bytes replaced at each site with a `call` into the cave.
HOOK_SITES = tuple(va + TOGGLE_MOUNTED_HEALTH_COPY_HOOK for va in SEQUENCES)
STOCK_HOOK = TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE[
    TOGGLE_MOUNTED_HEALTH_COPY_HOOK : TOGGLE_MOUNTED_HEALTH_COPY_HOOK + 5
]
#: `[ebp-0x14]` in the swap's frame: the new object's body, stored there by the sequence just
#: before the hooked call and read back by it just after.
NEW_BODY_LOCAL = -0x14

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def build_code() -> bytes:
    """The replacement for `old->getHealth()`: `ecx` is the old body, and the answer goes back in
    `st(0)` for the stock `fstp` to hand to `setHealth`.

    It needs no address of its own - both calls go through the body vtables and the new body is
    read out of the caller's frame - so the same bytes serve both sites wherever the cave lands.
    The ratio is parked on the stack across the second call, because the x87 stack has to be
    empty at a call boundary."""
    return b"".join(
        (
            b"\x8b\x01",  # mov eax, [ecx]
            b"\xff\x50" + bytes([BODY_GET_HEALTH_RATIO_SLOT]),  # call [eax+0x14]  old ratio
            b"\x51",  # push ecx                     a slot for it
            b"\xd9\x1c\x24",  # fstp dword [esp]
            b"\x8b\x4d" + (NEW_BODY_LOCAL & 0xFF).to_bytes(1, "little"),  # mov ecx, [ebp-0x14]
            b"\x8b\x01",  # mov eax, [ecx]
            b"\xff\x50" + bytes([BODY_GET_MAX_HEALTH_SLOT]),  # call [eax+0x1c]  new maximum
            b"\xd8\x0c\x24",  # fmul dword [esp]
            b"\x59",  # pop ecx                      the slot; the caller reloads ecx
            b"\xc3",  # ret
        )
    )


class MountHealthRatioPatch(Patch):
    name = "mount-health-ratio"
    author = "officialNecro"
    description = (
        "Carry health across a ToggleMountedSpecialAbilityUpdate swap (MountedTemplate, both "
        "mounting and dismounting) as a percentage of maximum health rather than as hit points, "
        "so toggling between two templates with different MaxHealth no longer heals the unit. "
        "Logic-side: every peer needs the same binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_sequences(data)
        cave_va = allocate_section(data, SECTION_NAME, lambda _va: build_code(), _CHARACTERISTICS)
        for site, which in zip(HOOK_SITES, ("mount", "dismount"), strict=True):
            apply_byte_patch(
                data,
                file_offset(data, site),
                STOCK_HOOK,
                call_rel32(site, cave_va),
                f"the {which} swap's getHealth -> health ratio x new maximum",
            )

    @staticmethod
    def _check_sequences(data: bytes | bytearray) -> None:
        """Raise unless both hand-overs hold the whole stock sequence, not just the five bytes
        being replaced: the cave relies on `ecx` being the old body and `[ebp-0x14]` the new one,
        which only the instructions around the call establish."""
        for va in SEQUENCES:
            off = file_offset(data, va)
            got = bytes(data[off : off + len(TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE)])
            if got != TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE:
                raise ValueError(
                    f"@0x{va:08x}: expected the stock mount-swap health hand-over "
                    f"{TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE.hex()}, got {got.hex()} - the file is "
                    "not the expected build, or already carries this patch"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        problems: list[str] = []
        code = build_code()
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routine in {SECTION_NAME} is not the one this patch builds")
        for site in HOOK_SITES:
            want = call_rel32(site, cave_va)
            off = file_offset(data, site)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(
                    f"@0x{site:08x}: the health hand-over does not call {SECTION_NAME} "
                    f"(holds {got.hex()})"
                )
        return problems
