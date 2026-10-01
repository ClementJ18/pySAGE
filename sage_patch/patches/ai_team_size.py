"""Make the skirmish AI size its attack teams in battalions, not in soldiers.

The team builder asks `AI_TEAM_SIZE` how big a team is, and that counts every object on it with
`CAN_ATTACK`, `HERO` or `SUPPORT`. A battalion puts its members on its own team, so one battalion
of five counts as six - past every tactic's minimum and at the max of the attack tactics, which
also skips the "strong enough for what defends the target" test. Teams leave with whatever was idle
the moment they formed, which for a faction building one expensive battalion at a time is one.

A cave at the count's loop head skips objects carrying `HORDE_MEMBER`, so a battalion counts once.
The tactic's min, max and threat test then mean what they say. AI-only: the team builder is the
count's only caller. Applies to every faction.

Derivation: `../docs/ai-team-size.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_TEAM_BUILDER_DONE_SIZE_CALL,
    AI_TEAM_BUILDER_RECRUIT_SIZE_CALL,
    AI_TEAM_SIZE,
    AI_TEAM_SIZE_BACK_EDGE,
    AI_TEAM_SIZE_BACK_EDGE_BYTES,
    AI_TEAM_SIZE_ENTRY,
    AI_TEAM_SIZE_KINDOF_TESTS,
    AI_TEAM_SIZE_KINDOF_TESTS_BYTES,
    AI_TEAM_SIZE_MEMBER,
    AI_TEAM_SIZE_MEMBER_BYTES,
    AI_TEAM_SIZE_NEXT,
    AI_TEAM_SIZE_NEXT_BYTES,
    OBJECT_STATUS,
    OBJECT_STATUS_HORDE_MEMBER,
    OBJECT_TEST_STATUS,
    OBJECT_THING_TEMPLATE,
)
from ..asm import JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, find_section, u32, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "AiTeamSizePatch",
    "build_code",
]

SECTION_NAME = ".aiteam"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = AI_TEAM_SIZE_MEMBER
HOOK_ORIGINAL = AI_TEAM_SIZE_MEMBER_BYTES

#: `ObjectStatus` bit 38 as the byte and mask `OBJECT_TEST_STATUS` would index, derived rather than
#: written down so it cannot drift from the encoding that function documents.
_HORDE_MEMBER_BYTE = OBJECT_STATUS + (OBJECT_STATUS_HORDE_MEMBER // 32) * 4
_HORDE_MEMBER_MASK = 1 << (OBJECT_STATUS_HORDE_MEMBER % 8)

#: The iterator's current object, `[ebp-0x18]`, as the stock loop reads it.
_MEMBER = 0xE8

#: Byte windows the patch depends on and does not write. The entry pins the function and its
#: frame; the two resume points are where the cave jumps back to; the back-edge pins that the loop
#: head is the hook, so nothing lands inside the displaced bytes; the two team-builder calls prove
#: the function being edited is the one the team builder asks (their bytes are the displacement);
#: `testStatus` pins the bit encoding the `HORDE_MEMBER` test open-codes.
ANCHORS: dict[int, bytes] = {
    AI_TEAM_SIZE: AI_TEAM_SIZE_ENTRY,
    AI_TEAM_SIZE_KINDOF_TESTS: AI_TEAM_SIZE_KINDOF_TESTS_BYTES,
    AI_TEAM_SIZE_NEXT: AI_TEAM_SIZE_NEXT_BYTES,
    AI_TEAM_SIZE_BACK_EDGE: AI_TEAM_SIZE_BACK_EDGE_BYTES,
    AI_TEAM_BUILDER_RECRUIT_SIZE_CALL: call_rel32(AI_TEAM_BUILDER_RECRUIT_SIZE_CALL, AI_TEAM_SIZE),
    AI_TEAM_BUILDER_DONE_SIZE_CALL: call_rel32(AI_TEAM_BUILDER_DONE_SIZE_CALL, AI_TEAM_SIZE),
    OBJECT_TEST_STATUS: bytes.fromhex(
        "8b54240433c0568bf1408bca83e11fd3e0c1ea05238496940000005ef7d81bc0f7d8c20400"
    ),
}


def build_code(base_va: int) -> bytes:
    """The loop head, with the battalion-member test in front. Reached only from the hook, and
    never returns to it.

    `edi` is the running count and `esi` holds the `0x4000000` mask the stock KindOf tests reuse;
    the cave touches neither. `eax` is the only register it writes, and the stock code reloads it
    on every path it resumes on."""
    a = Asm(base_va)
    a.emit(b"\x8b\x45", _MEMBER)  # mov eax, [ebp-0x18]       ; the team member
    # HORDE_MEMBER: set on a battalion's rank and file and cleared for a MACHINE, HERO or
    # SIEGE_TOWER that joined one, so heroes and siege still count as units.
    a.emit(b"\xf6\x80", u32(_HORDE_MEMBER_BYTE), _HORDE_MEMBER_MASK)
    a.jcc(JNE, "member")
    a.emit(b"\x8b\x40", OBJECT_THING_TEMPLATE)  # mov eax, [eax+4] ; the displaced template read
    a.jmp_absolute(AI_TEAM_SIZE_KINDOF_TESTS)  # the stock KindOf tests, byte-for-byte

    a.label("member")
    a.jmp_absolute(AI_TEAM_SIZE_NEXT)  # counted through its battalion: next object
    return a.finish()


class AiTeamSizePatch(Patch):
    name = "ai-team-size"
    author = "officialNecro"
    description = (
        "The skirmish AI counts an attack team's size in battalions instead of soldiers, so a "
        "team waits for its tactic's minimum and fills up to its maximum or until it outweighs "
        "the target's defenders, instead of leaving with one battalion. All factions. No INI "
        "change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "SkirmishAI team size loop head -> ai-team-size cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the SkirmishAI "
                    "team size count is not this build's, so the cave would resume into the wrong "
                    "place or edit a function the team builder does not call"
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
        if target != section_va:
            problems.append(f"hook jumps to {target:#010x}, expected {section_va:#010x}")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected loop head")
        return problems
