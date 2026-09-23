"""Let a summoned or spawned `ARMY_SUMMARY` unit come home from a War of the Ring battle, like a
recruited one.

The post-battle harvest needs a living-world army id, which only deployment and production write,
so a summon is always dropped. The six-byte load at `0x00811EAA` goes to a cave that, for an object
with no army id, adopts the army of the first object with the same controlling player that has one
- the army the battle is being fought with. The harvest then records it normally.

Derivation: `../docs/living-campaign/army-id-custody.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    LIVING_WORLD_BATTLE_HARVEST,
    LIVING_WORLD_HARVEST_ARMY_ID_TEST,
    LIVING_WORLD_HARVEST_ARMY_ID_TEST_BYTES,
    OBJECT_ARMY_ID,
    OBJECT_GET_CONTROLLING_PLAYER,
    THE_GAME_LOGIC,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, u32

__all__ = [
    "ANCHORS",
    "GAME_LOGIC_OBJECT_LIST_HEAD",
    "HOOK_BYTES",
    "OBJECT_LIST_NEXT",
    "SECTION",
    "SummonCarryoverPatch",
    "build_code",
]

SECTION = ".summonc"
_RX = 0xE0000020

#: `TheGameLogic + 0xAC` is the global object list head - the argument the post-battle handler
#: hands the harvest at `0x0062666D`.
GAME_LOGIC_OBJECT_LIST_HEAD = 0xAC
#: `Object + 0x8C` is the list's `next`, the link the harvest itself walks.
OBJECT_LIST_NEXT = 0x8C

#: The six stock bytes at the hook, replaced by `call <cave>` plus a `nop`. Nothing in the harvest
#: branches into them: its jump targets are `0x00811E77`, `0x00811ED8`, `0x00811EDA`, `0x00811EE7`,
#: `0x00811F18`, `0x00811F27`, `0x00811FC1` and `0x00811FC2`.
HOOK_BYTES = LIVING_WORLD_HARVEST_ARMY_ID_TEST_BYTES

#: Sites asserted but not rewritten, so a build that happens to carry the same six bytes at the
#: hook cannot be mistaken for this one. In order: the harvest's `ARMY_SUMMARY` test and the
#: object flag beside it, which fix that the hook sits in the filter chain; the `test eax, eax`
#: and `je` the cave's return value feeds; the army lookup and the conditional append that make
#: the id a destination; and the post-battle handler's `push [edi + 0xac]`, which is what says
#: `TheGameLogic + 0xAC` is the object list head.
ANCHORS = {
    0x00811E96: bytes.fromhex("849818010000"),
    0x00811EA2: bytes.fromhex("849f58040000"),
    0x00811EB0: bytes.fromhex("85c0894508"),
    0x00811EB5: bytes.fromhex("7470"),
    0x00811F04: bytes.fromhex("e8cbdbffff"),
    0x00811F0B: bytes.fromhex("740b"),
    0x00811F13: bytes.fromhex("e839faffff"),
    0x0062666D: bytes.fromhex("ffb7ac000000"),
}


def build_code(base: int) -> bytes:
    """The cave: `edi` is the object, the army id comes back in `eax`.

    `edi` and `ebx` are left alone because the harvest itself relies on them surviving a call to
    `Object::getControllingPlayer` (`0x00811E77` reads both immediately after one). `esi` has no
    such proof, so it is saved around every engine call rather than assumed callee-saved.
    """
    a = Asm(base)

    a.emit(0x8B, 0x87, u32(OBJECT_ARMY_ID))  # mov eax, [edi + 0x47C]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "done")  # already filed with an army

    a.emit(0x51, 0x52, 0x56)  # push ecx / edx / esi

    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "fail")
    a.emit(0x8B, 0xD0)  # mov edx, eax        ; the owning player

    a.emit(0xA1, u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x85, 0xC0)
    a.jcc(JE, "fail")
    a.emit(0x8B, 0xB0, u32(GAME_LOGIC_OBJECT_LIST_HEAD))  # mov esi, [eax + 0xAC]

    a.label("scan")
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "fail")
    a.emit(0x83, 0xBE, u32(OBJECT_ARMY_ID), 0x00)  # cmp dword [esi + 0x47C], 0
    a.jcc(JE, "next")

    # A sibling that carries an army id. Adopt it only if the owner matches.
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0x52, 0x56)  # push edx / esi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x5E, 0x5A)  # pop esi / edx
    a.emit(0x3B, 0xC2)  # cmp eax, edx
    a.jcc(JE, "hit")

    a.label("next")
    a.emit(0x8B, 0xB6, u32(OBJECT_LIST_NEXT))  # mov esi, [esi + 0x8C]
    a.jmp("scan")

    a.label("hit")
    a.emit(0x8B, 0x86, u32(OBJECT_ARMY_ID))  # mov eax, [esi + 0x47C]
    a.jmp("out")

    a.label("fail")
    a.emit(0x31, 0xC0)  # xor eax, eax - the stock outcome

    a.label("out")
    a.emit(0x5E, 0x5A, 0x59)  # pop esi / edx / ecx

    a.label("done")
    a.emit(0xC3)  # ret

    return a.finish()


def _patched(cave: int) -> bytes:
    site = LIVING_WORLD_HARVEST_ARMY_ID_TEST
    return bytes([0xE8]) + struct.pack("<i", cave - (site + 5)) + b"\x90"


class SummonCarryoverPatch(Patch):
    """Carry any `KindOf = ARMY_SUMMARY` survivor home, not only one deployed or recruited."""

    name = "summon-carryover"
    author = "officialNecro"
    description = (
        "Summoned and spawned units with KindOf = ARMY_SUMMARY come home from a War of the Ring "
        "battle instead of being dropped. The post-battle harvest also requires a living-world "
        "army id, which only the deployment and production chain ever writes, so a summon is "
        "discarded however it is flagged; this supplies the army of a sibling that has one. No "
        "INI change, but ARMY_SUMMARY now means 'comes home' rather than 'comes home when "
        "recruited', so a template that should not persist has to drop the flag"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION) is not None:
            raise ValueError(f"{SECTION} is already present - {self.name} is already applied")
        self._check_anchors(data)
        cave = allocate_section(data, SECTION, build_code, _RX)
        apply_byte_patch(
            data,
            file_offset(data, LIVING_WORLD_HARVEST_ARMY_ID_TEST),
            HOOK_BYTES,
            _patched(cave),
            f"harvest army-id load @0x{LIVING_WORLD_HARVEST_ARMY_ID_TEST:08x}",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION)
        if located is None:
            return [f"the {SECTION} cave is missing"]
        cave, _off, _size = located
        try:
            off = file_offset(data, LIVING_WORLD_HARVEST_ARMY_ID_TEST)
        except ValueError as exc:
            return [str(exc)]
        got = bytes(data[off : off + len(HOOK_BYTES)])
        want = _patched(cave)
        if got == want:
            return []
        site = LIVING_WORLD_HARVEST_ARMY_ID_TEST
        if got == HOOK_BYTES:
            return [f"the harvest army-id load @0x{site:08x} is unpatched"]
        return [
            f"the harvest army-id load @0x{site:08x} is {got.hex()}, expected {want.hex()} "
            f"(patched) or {HOOK_BYTES.hex()} (stock)"
        ]

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        sites = dict(ANCHORS)
        sites[LIVING_WORLD_HARVEST_ARMY_ID_TEST] = HOOK_BYTES
        sites[LIVING_WORLD_BATTLE_HARVEST] = bytes.fromhex("b8cd9fb900")
        for va, expected in sites.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the game.dat these addresses were read from"
                )
