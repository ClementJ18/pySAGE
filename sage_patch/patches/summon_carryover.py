"""Let a summoned or spawned unit come home from a War of the Ring battle, like a recruited one.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/living-campaign/army-id-custody.md``.

**The premise.** `KindOf = ARMY_SUMMARY` reads like "this goes home with the player", but it is
only the second of four filters the post-battle harvest applies (``0x00811E1F``). The fourth is a
non-zero living-world army id on the object itself::

    00811e96  test byte [eax + 0x118], bl   ; KindOf = ARMY_SUMMARY
    00811ea2  test byte [edi + 0x458], bl   ; an object flag nothing ever sets
    00811eaa  mov  eax, [edi + 0x47c]       ; the army id
    00811eb0  test eax, eax
    00811eb5  je   skip

`Object+0x47C` is zeroed by the constructor and only ever written down a chain of custody: the
army's own deployment seeds it, and `CastleBehavior`, `DozerAIUpdate`, `FoundationAIUpdate`,
`ProductionUpdate`, `HordeContain` and `OpenContain` pass it on. A recruited unit inherits it from
the structure that built it. **No object-creation path outside production writes it at all** -
`OCLUpdate`, `CreateObjectDie`, `SpawnBehavior`, `SpawnUnitBehavior`,
`SummonReplacementSpecialAbilityUpdate`, `ObjectCreationUpgrade` and the rest all reach
`THING_FACTORY_NEW_OBJECT`, which takes a template and a team and no creator. So a summon is born
with zero and is dropped no matter what `KindOf` it carries.

**The id is a destination, not a gate.** Twelve instructions later the record that was just built
is filed into `findArmyById(id)`, and a NULL army throws it away::

    00811ef2  push dword [ebp + 8]
    00811f04  call 0x80fad4                 ; findArmyRoster(id)
    00811f0b  je   0x811f18                 ; NULL -> the record is discarded
    00811f13  call 0x811951                 ; else append

Simply skipping the test therefore achieves nothing; the patch has to **supply** an id.

**What this does.** Replaces the six-byte load at ``0x00811EAA`` with a call into a cave that
returns the same value when the object has one, and otherwise adopts the army of a sibling: the
first object in the global object list with the same controlling player and a non-zero army id.
That is the army the player is fighting the battle with, so the summon joins the force it fought
alongside. Everything downstream is untouched - the harvest's own `Object::toArmyRecord` records
the summon's upgrades and veterancy exactly as it does for a recruited unit.

The rule the patch implements is therefore **`ARMY_SUMMARY` means always comes home**, with no new
INI surface: no `KindOf` token, no field, nothing for a mod to migrate. The flag a mod already sets
becomes the whole answer.

**What a mod has to know.** `ARMY_SUMMARY` stops meaning "comes home when recruited" and starts
meaning "comes home". Measured against Edain, 383 of the 1716 templates carrying the flag are
reachable from a non-production creation path and become eligible; 156 of those are `KindOf
SUMMONED` - the intended summons - and 227 are ordinary recruitable hordes that some
`ObjectCreationList` also references, including campaign reinforcements, `_Kampagne` hero variants
and story units. Their `ARMY_SUMMARY` is not evidence anybody wanted them kept, because on the
summon path the flag has never done anything. Dropping the flag from a template that should not
persist is the fix, and it is a data change rather than a patch option.

**Determinism.** The fallback walks the same global object list the harvest is already walking, in
list order, so every client resolves the same army from the same state. It runs once per battle,
and only for objects that would otherwise be discarded.

**Limits.** A player fielding more than one army in a single battle gets an arbitrary one of them -
the first sibling in list order - because the object carries no other evidence of which it belongs
to. A player whose entire roster died and whose only survivors are summons has no sibling to adopt
from, so nothing is carried, which is the behaviour without the patch.

**Not covered.** `ReplaceObjectUpdate` and the mount/dismount toggles are absent from the chain of
custody too, so a unit that transforms mid-battle loses the army id it had; this patch does not
restore it, it only supplies one where there was never any. Filter 3 (``0x00811EA2``) is left
alone: `Object+0x458` bit 0 has no setter anywhere in the image, so it never rejects anything.
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
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

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


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"unmapped address {va:#x}: not RotWK 2.01")
    return off


def build_code(base: int) -> bytes:
    """The cave: `edi` is the object, the army id comes back in `eax`.

    `edi` and `ebx` are left alone because the harvest itself relies on them surviving a call to
    `Object::getControllingPlayer` (`0x00811E77` reads both immediately after one). `esi` has no
    such proof, so it is saved around every engine call rather than assumed callee-saved.
    """
    a = Asm(base)

    a.emit(0x8B, 0x87, _u32(OBJECT_ARMY_ID))  # mov eax, [edi + 0x47C]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "done")  # already filed with an army

    a.emit(0x51, 0x52, 0x56)  # push ecx / edx / esi

    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "fail")
    a.emit(0x8B, 0xD0)  # mov edx, eax        ; the owning player

    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x85, 0xC0)
    a.jcc(JE, "fail")
    a.emit(0x8B, 0xB0, _u32(GAME_LOGIC_OBJECT_LIST_HEAD))  # mov esi, [eax + 0xAC]

    a.label("scan")
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "fail")
    a.emit(0x83, 0xBE, _u32(OBJECT_ARMY_ID), 0x00)  # cmp dword [esi + 0x47C], 0
    a.jcc(JE, "next")

    # A sibling that carries an army id. Adopt it only if the owner matches.
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0x52, 0x56)  # push edx / esi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x5E, 0x5A)  # pop esi / edx
    a.emit(0x3B, 0xC2)  # cmp eax, edx
    a.jcc(JE, "hit")

    a.label("next")
    a.emit(0x8B, 0xB6, _u32(OBJECT_LIST_NEXT))  # mov esi, [esi + 0x8C]
    a.jmp("scan")

    a.label("hit")
    a.emit(0x8B, 0x86, _u32(OBJECT_ARMY_ID))  # mov eax, [esi + 0x47C]
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
            _offset(data, LIVING_WORLD_HARVEST_ARMY_ID_TEST),
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
            off = _offset(data, LIVING_WORLD_HARVEST_ARMY_ID_TEST)
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
            off = _offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the game.dat these addresses were read from"
                )
