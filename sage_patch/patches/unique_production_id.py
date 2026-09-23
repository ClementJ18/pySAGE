"""Stop a hero recruit from taking the money and producing nothing.

`requestUniqueUnitID` mints production ids from a counter on each producer, so every building hands
out the same ids, and two queued productions can collide. A four-byte `.prodid` section holds one
global counter and the minting function is rewritten in place to use it. The first id is unchanged.

Derivation: `../docs/unique-production-id.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    PRODUCTION_UPDATE_INTERFACE_VTABLE,
    REQUEST_UNIQUE_UNIT_ID,
    REQUEST_UNIQUE_UNIT_ID_BODY,
    REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT,
)
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = ["COUNTER_SIZE", "SECTION_NAME", "UniqueProductionIdPatch", "build_body"]

SECTION_NAME = ".prodid"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: The section holds one dword and nothing else. It is read and written every time a production
#: is queued, and never executed.
COUNTER_SIZE = 4

# IMAGE_SCN_CNT_INITIALIZED_DATA | MEM_READ | MEM_WRITE. Deliberately not executable: unlike the
# other bundled caves this section is data, so the loader need not map it as code.
_CHARACTERISTICS = 0x40 | 0x40000000 | 0x80000000


def build_body(counter_va: int) -> bytes:
    """The replacement `requestUniqueUnitID`, minting from the counter at `counter_va`.

    Exactly as long as the body it replaces, so it is written over the stock function rather
    than hooked. Hand-encoded rather than assembled: the sequence is four instructions with no
    branch, so there is no address arithmetic for `sage_patch.asm` to protect.
    """
    body = b"".join(
        (
            b"\xb8" + struct.pack("<I", counter_va),  # mov eax, counter
            b"\xff\x00",  # inc dword [eax]
            b"\x8b\x00",  # mov eax, [eax]
            b"\xc3",  # ret      (__thiscall, no arguments; ecx is untouched)
        )
    )
    assert len(body) == len(REQUEST_UNIQUE_UNIT_ID_BODY)
    return body


class UniqueProductionIdPatch(Patch):
    name = "unique-production-id"
    author = "officialNecro"
    description = (
        "Mint production ids game-wide, so a hero recruit from a second building works. No INI "
        "change"
    )

    def apply(self, data: bytearray) -> None:
        body_off = va_to_offset(data, REQUEST_UNIQUE_UNIT_ID)
        if body_off is None:
            raise ValueError(
                f"{REQUEST_UNIQUE_UNIT_ID:#010x} is not mapped - not the expected build"
            )
        # Prove the function being rewritten is the one production dispatches to. A rewrite of
        # some other ten bytes installs perfectly and never runs.
        self._check_dispatch(data)
        counter_va = allocate_section(
            data, SECTION_NAME, lambda _va: bytes(COUNTER_SIZE), _CHARACTERISTICS
        )
        apply_byte_patch(
            data,
            body_off,
            REQUEST_UNIQUE_UNIT_ID_BODY,
            build_body(counter_va),
            "requestUniqueUnitID -> game-wide counter",
        )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless the production interface's vtable still names the function being
        rewritten."""
        slot_va = PRODUCTION_UPDATE_INTERFACE_VTABLE + REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT
        slot_off = va_to_offset(data, slot_va)
        if slot_off is None:
            raise ValueError(
                "the ProductionUpdate interface vtable is not mapped - not the expected build"
            )
        target = struct.unpack_from("<I", data, slot_off)[0]
        if target != REQUEST_UNIQUE_UNIT_ID:
            raise ValueError(
                f"vtable slot {slot_va:#010x} dispatches to {target:#010x}, not "
                f"{REQUEST_UNIQUE_UNIT_ID:#010x} - the id mint being patched is not the live one"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        counter_va, section_off, vsize = located
        if vsize < COUNTER_SIZE:
            problems.append(f"{SECTION_NAME} holds {vsize} bytes, expected {COUNTER_SIZE}")
        off = va_to_offset(data, REQUEST_UNIQUE_UNIT_ID)
        if off is None:
            return [f"{REQUEST_UNIQUE_UNIT_ID:#010x} is not mapped by any section"]
        expected = build_body(counter_va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            problems.append(
                f"requestUniqueUnitID holds {got.hex()}, expected {expected.hex()} - "
                "the mint is not installed, or points at another address"
            )
        if bytes(data[section_off : section_off + COUNTER_SIZE]) != bytes(COUNTER_SIZE):
            problems.append(f"the {SECTION_NAME} counter is not zero-initialised")
        return problems
