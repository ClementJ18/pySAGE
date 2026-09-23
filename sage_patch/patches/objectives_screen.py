"""Open the objectives screen from the Palantir button on any map that declares objectives, not only
in the linear campaign.

The button chooses between three screens through a game-type predicate asked at three call sites.
All three go to a cave that first asks whether the map declares a `MissionObjectiveList`: if so it
opens `Objectives.apt`, otherwise it defers to the stock predicate. Such a map can no longer reach
the tribute or player-list screen from that button.

Derivation: `../docs/objectives-in-any-map.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY,
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES,
    MISSION_OBJECTIVE_LIST_OFFSET,
    MISSION_OBJECTIVE_TRACKER,
    PALANTIR_BUTTON_ROUTE_CALL,
    PALANTIR_BUTTON_ROUTE_CALL_BYTES,
    PALANTIR_BUTTON_STATUS_CALL,
    PALANTIR_BUTTON_STATUS_CALL_BYTES,
    PALANTIR_BUTTON_TRIBUTE_CALL,
    PALANTIR_BUTTON_TRIBUTE_CALL_BYTES,
    PALANTIR_HOTKEY_ROUTE_CALL,
    PALANTIR_HOTKEY_ROUTE_CALL_BYTES,
    PALANTIR_HOTKEY_STATUS_CALL,
    PALANTIR_HOTKEY_STATUS_CALL_BYTES,
    PALANTIR_HOTKEY_TRIBUTE_CALL,
    PALANTIR_HOTKEY_TRIBUTE_CALL_BYTES,
    PALANTIR_OBJECTIVES_PUSH,
    PALANTIR_OBJECTIVES_PUSH_BYTES,
    PALANTIR_PLAYER_STATUS_PUSH,
    PALANTIR_PLAYER_STATUS_PUSH_BYTES,
    PALANTIR_SCREEN_CHOICE_CALL,
    PALANTIR_SCREEN_CHOICE_CALL_BYTES,
)
from ..asm import JB, JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOKS",
    "OBJECTIVE_ENTRY_SIZE",
    "ObjectivesScreenPatch",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".objscr"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: Every call to the stock predicate that stands between a click and the objectives screen, as a
#: `{va: original bytes}` map. All three are redirected to the same cave, and all three have to be:
#: the outer two pick the handler, and the handler holding the inner one is only reached once they
#: answer "not a game-type screen".
HOOKS = {
    PALANTIR_BUTTON_ROUTE_CALL: PALANTIR_BUTTON_ROUTE_CALL_BYTES,
    PALANTIR_HOTKEY_ROUTE_CALL: PALANTIR_HOTKEY_ROUTE_CALL_BYTES,
    PALANTIR_SCREEN_CHOICE_CALL: PALANTIR_SCREEN_CHOICE_CALL_BYTES,
}

#: The objective list is a vector of 8-byte entries; the HUD takes its count with `sar eax, 3`
#: (`0x006D78B5`). One entry is therefore `end - begin >= 8`.
OBJECTIVE_ENTRY_SIZE = 8

#: The first bytes at each address this patch depends on but does not edit, as a `{va: bytes}`
#: map. The hooks' own bytes are asserted by `apply_byte_patch`; these prove the *branches* are the
#: ones being changed - a build where the screen pushes or the two handlers moved or swapped fails
#: here rather than silently redirecting some other call to a cave that answers a question about
#: objectives.
ANCHORS = {
    PALANTIR_BUTTON_TRIBUTE_CALL: PALANTIR_BUTTON_TRIBUTE_CALL_BYTES,
    PALANTIR_BUTTON_STATUS_CALL: PALANTIR_BUTTON_STATUS_CALL_BYTES,
    PALANTIR_HOTKEY_TRIBUTE_CALL: PALANTIR_HOTKEY_TRIBUTE_CALL_BYTES,
    PALANTIR_HOTKEY_STATUS_CALL: PALANTIR_HOTKEY_STATUS_CALL_BYTES,
    PALANTIR_PLAYER_STATUS_PUSH: PALANTIR_PLAYER_STATUS_PUSH_BYTES,
    PALANTIR_OBJECTIVES_PUSH: PALANTIR_OBJECTIVES_PUSH_BYTES,
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY: IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The cave: answer "does this map declare objectives?", and defer to the stock predicate when
    it does not.

    Entered by `call` in place of `call IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY`, so it must
    return the same way that predicate does - `al` non-zero for the player list, zero for
    objectives - and leave `ecx` alone, because the stock predicate reads it as `this` and the
    fallback edge hands it straight on.
    """
    a = Asm(base_va)

    a.emit(0x51)  # push ecx                     - preserve the thiscall argument
    a.emit(0xA1, struct.pack("<I", MISSION_OBJECTIVE_TRACKER))  # mov eax, [TheMissionObjective..]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "fallback")

    a.emit(0x8B, 0x40, MISSION_OBJECTIVE_LIST_OFFSET)  # mov eax, [eax+0x10]  - the objective list
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "fallback")

    # count = (end - begin) / 8, and one entry is enough. Compared as a byte span so the divide
    # the HUD does is not reproduced.
    a.emit(0x8B, 0x50, 0x08)  # mov edx, [eax+8]     - end
    a.emit(0x2B, 0x50, 0x04)  # sub edx, [eax+4]     - begin
    a.emit(0x83, 0xFA, OBJECTIVE_ENTRY_SIZE)  # cmp edx, 8
    a.jcc(JB, "fallback")

    a.emit(0x59)  # pop ecx
    a.emit(0x33, 0xC0)  # xor eax, eax             - false: open Objectives.apt
    a.emit(0xC3)  # ret

    a.label("fallback")
    a.emit(0x59)  # pop ecx                        - `this` restored for the stock predicate
    a.jmp_absolute(IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY)  # tail call: its ret is ours
    return a.finish()


class ObjectivesScreenPatch(Patch):
    name = "objectives-screen"
    author = "officialNecro"
    description = (
        "Open Objectives.apt from the Palantir button on any map that declares objectives, "
        "instead of only in the linear campaign. The opt-in is the map's own "
        "MissionObjectiveList block in map.ini; a map that declares one can no longer reach the "
        "tribute or player-list screen from that button"
    )

    def apply(self, data: bytearray) -> None:
        offsets = {}
        for va in HOOKS:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            offsets[va] = off
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        for va, original in HOOKS.items():
            call = b"\xe8" + struct.pack("<i", section_va - (va + 5))
            apply_byte_patch(
                data,
                offsets[va],
                original,
                call,
                f"Palantir screen choice at {va:#010x} -> objectives-screen cave",
            )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Raise unless every address the cave depends on still holds the instruction it was
        chosen for."""
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            found = bytes(data[off : off + len(expected)])
            if found != expected:
                raise ValueError(
                    f"{va:#010x} holds {found.hex()}, expected {expected.hex()} - the Palantir's "
                    "screen choice is not laid out as this patch expects"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        try:
            self._check_anchors(data)
        except ValueError as exc:
            problems.append(str(exc))

        section = find_section(data, SECTION_NAME)
        if section is None:
            problems.append(f"no {SECTION_NAME} section: the file does not carry this patch")

        for va, original in HOOKS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} is not mapped")
                continue

            found = bytes(data[off : off + len(original)])
            if found == original:
                problems.append(
                    f"{va:#010x} still calls the stock predicate: the file does not carry "
                    "this patch"
                )
            elif found[:1] != b"\xe8":
                problems.append(f"{va:#010x} holds {found.hex()}, which is not a call")
            elif section is not None:
                base_va, _, size = section
                target = va + 5 + struct.unpack_from("<i", found, 1)[0]
                if not base_va <= target < base_va + size:
                    problems.append(
                        f"{va:#010x} calls {target:#010x}, which is outside the {SECTION_NAME} cave"
                    )
        return problems
