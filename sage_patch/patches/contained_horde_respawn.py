"""The contained-horde-respawn patch: let `AffectsContained` replenish the battalion it heals.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/contained-horde-respawn.md``.

**The gap.** `AutoHealBehavior::update` (``AUTO_HEAL_UPDATE``) is an if/else chain over four
`ModuleData` flags, and `RespawnNearbyHordeMembers` is read at exactly one site in the whole image,
inside the fourth arm - the radius scan. `AffectsContained` is the second arm and leaves through
``AUTO_HEAL_CONTAINED_EXIT`` long before it. So the two fields are mutually exclusive as shipped:
a garrison tower can heal the battalion inside it, or replenish battalions standing around it, and
writing both keyword lines silently gets only the first.

That leaves no way at all to replenish a **contained** battalion. The radius arm only ever sees
what a `ThePartitionManager` range query returns, and so does `ReplenishUnitsBehavior`, the only
other module in the engine that repopulates a horde.

**What the patch does.** Five bytes and a cave. ``AUTO_HEAL_CONTAINED_EXIT`` is the
`AffectsContained` arm's closing `jmp` to the shared tail, with nothing else in it, so replacing it
with a jump into a ``.cnthrd`` cave adds a step to that arm and nothing to any other. The cave
re-checks the same `RespawnNearbyHordeMembers` and `RespawnMinimumDelay` the radius arm checks,
walks the container's passengers, and runs the transcribed respawn block on each one before
returning to ``AUTO_HEAL_UPDATE_TAIL``, which is where the five bytes went anyway. The sleep the
module asks for is unchanged.

**No INI change.** No keyword, no token, no `.str` key. `RespawnNearbyHordeMembers` is the switch
it already is, and a module without `AffectsContained` never reaches the new code, so every
existing object behaves exactly as before. What changes is that the two lines together now mean
something::

    Behavior = AutoHealBehavior ModuleTag_HearthHeal
        StartsActive              = Yes
        AffectsContained          = Yes
        RespawnNearbyHordeMembers = Yes
        RespawnFXList             = FX_BannerCarrierSpawnUnit
        RespawnMinimumDelay       = 1
        HealingDelay              = 10000
        HealingAmount             = 35
    End

**The gates are the stock ones.** Per passenger: `KindOf HORDE` on its template, not
`UNDER_CONSTRUCTION`, a non-NULL horde interface, and live members below that contain's `Slots`.
A passenger that is not a battalion costs one `test` and is skipped, so a transport full of
infantry pays almost nothing. The respawn timestamp is the same module field the radius arm stamps,
so a module cannot respawn through both arms in one tick - and it could not anyway, because the two
arms are exclusive.

**Cadence.** The update reschedules itself `HealingDelay` frames out, so that is the ceiling on how
often the cave runs whatever `RespawnMinimumDelay` says. This patch does not change that, and a mod
wanting a faster replenish lowers `HealingDelay`.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`~ContainedHordeRespawnPatch.verify` finds it by name. The five engine bytes it edits are at
``AUTO_HEAL_CONTAINED_EXIT``, which no other bundled patch touches, and it reads nothing another
patch rewrites.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AUTO_HEAL_ANCHORS,
    AUTO_HEAL_CONTAINED_EXIT,
    AUTO_HEAL_CONTAINED_EXIT_BYTES,
    AUTO_HEAL_LAST_RESPAWN_FRAME,
    AUTO_HEAL_MODULE_BASE_SLOT,
    AUTO_HEAL_RESPAWN_FX_LIST,
    AUTO_HEAL_RESPAWN_MEMBER_FIXUP,
    AUTO_HEAL_RESPAWN_MINIMUM_DELAY,
    AUTO_HEAL_RESPAWN_NEARBY_HORDE_MEMBERS,
    AUTO_HEAL_SCOPE_INDEX_SLOT,
    AUTO_HEAL_UPDATE_TAIL,
    CONTAIN_ITERATE_SLOT,
    FX_LIST_PLAY_AT_OBJECT,
    GAME_LOGIC_FRAME,
    HORDE_IFACE_MAX_MEMBERS_SLOT,
    HORDE_IFACE_MEMBER_COUNT_SLOT,
    HORDE_IFACE_RESPAWN_MEMBER_SLOT,
    KINDOF_HORDE_BIT,
    KINDOF_HORDE_BYTE,
    OBJECT_GET_HORDE_IFACE,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    OBJECT_TEST_STATUS,
    OBJECT_TRANSFORM,
    THE_GAME_LOGIC,
)
from ..asm import JAE, JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "SECTION_NAME",
    "ContainedHordeRespawnPatch",
    "build_code",
]

SECTION_NAME = ".cnthrd"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def _ebp(slot: int) -> int:
    """The byte displacement naming `[ebp-slot]`, which is how every frame reference here is
    written - the update's own instructions use the same form."""
    if not 0 < slot <= 0x80:
        raise ValueError(f"[ebp-0x{slot:x}] does not encode as a byte displacement")
    return (256 - slot) & 0xFF


def _call_slot(slot: int) -> bytes:
    """``call dword [eax+slot]`` - a vtable call through a vtable already loaded into `eax`."""
    return b"\xff\x90" + struct.pack("<I", slot)


def _emit_callback(a: Asm) -> None:
    """`__cdecl(Object *passenger, AutoHealBehaviorModuleData *data)`, the callback the cave hands
    to `iterateContained`.

    The shape is `0x0085584B`'s, the callback the stock `AffectsContained` arm passes the same
    slot: two arguments, no return value, and a plain `ret` because the iterator cleans them. The
    body is the respawn block at ``AUTO_HEAL_RESPAWN_BLOCK`` with the object it works on coming
    from the argument rather than from a partition iterator.

    `ebx`, `esi` and `edi` are saved and restored, so the engine's iterator gets its callee-saved
    registers back untouched - and so does the update, whose `ebx` still has to be the `ModuleData`
    when the cave returns to the tail.
    """
    a.label("callback")
    a.emit(0x53, 0x56, 0x57)  # push ebx / push esi / push edi
    a.emit(0x8B, 0x74, 0x24, 0x10)  # mov esi, [esp+0x10]  - the passenger
    a.emit(0x8B, 0x5C, 0x24, 0x14)  # mov ebx, [esp+0x14]  - the ModuleData, as userData

    # `KindOf HORDE` on the passenger's template. Everything below needs a horde interface, and a
    # passenger that is not a battalion leaves here having cost one `test`.
    a.emit(0x8B, 0x46, 0x04)  # mov eax, [esi+4]  - the ThingTemplate
    a.emit(0xF6, 0x80, struct.pack("<I", KINDOF_HORDE_BYTE), KINDOF_HORDE_BIT)
    a.jcc(JE, "done")

    # A battalion still being built has slots it is not entitled to fill yet.
    a.emit(0x6A, OBJECT_STATUS_UNDER_CONSTRUCTION)  # push 2
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_TEST_STATUS)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "done")

    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_GET_HORDE_IFACE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0xF8)  # mov edi, eax  - the horde interface

    # `Slots`, then the live member count, then the stock comparison: a horde at or over its
    # ceiling is skipped. Taken in that order so the count is the value in `eax` at the `cmp`,
    # exactly as the radius arm has it.
    a.emit(0x8B, 0x07, 0x8B, 0xCF)  # mov eax, [edi] / mov ecx, edi
    a.emit(_call_slot(HORDE_IFACE_MAX_MEMBERS_SLOT))
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0x07, 0x8B, 0xCF)  # mov eax, [edi] / mov ecx, edi
    a.emit(_call_slot(HORDE_IFACE_MEMBER_COUNT_SLOT))
    a.emit(0x59)  # pop ecx  - Slots
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JAE, "done")

    # One member, at the battalion's own transform. The slot is `ret 4`, so it takes the argument
    # off the stack itself.
    a.emit(0x83, 0xC6, OBJECT_TRANSFORM)  # add esi, 8  - &passenger->m_transform
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x07, 0x8B, 0xCF)  # mov eax, [edi] / mov ecx, edi
    a.emit(_call_slot(HORDE_IFACE_RESPAWN_MEMBER_SLOT))
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0xF0)  # mov esi, eax  - the new member

    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(AUTO_HEAL_RESPAWN_MEMBER_FIXUP)

    # `RespawnFXList`, through the wrapper that tolerates a NULL list, as the radius arm does.
    a.emit(0x8B, 0x83, struct.pack("<I", AUTO_HEAL_RESPAWN_FX_LIST))  # mov eax, [ebx+0x178]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x6A, 0x00, 0x56, 0x50)  # push 0 / push esi / push eax
    a.call_absolute(FX_LIST_PLAY_AT_OBJECT)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc  - __cdecl

    a.label("done")
    a.emit(0x5F, 0x5E, 0x5B, 0xC3)  # pop edi / pop esi / pop ebx / ret


def _emit_entry(a: Asm) -> None:
    """The hook body, entered from ``AUTO_HEAL_CONTAINED_EXIT`` with the `AffectsContained` arm
    finished healing.

    `ebx` is the `ModuleData` and `edi` the `ContainModuleInterface` the arm selected - the object's
    own, or for a module on a passenger the one containing it. Both are callee-saved and the only
    two calls since `edi`'s last write are `AutoHealBehavior::healObject` and the arm's list
    destructor, so both still hold what the arm put in them. Every path leaves through
    ``AUTO_HEAL_UPDATE_TAIL``, which is where the five replaced bytes went.
    """
    a.label("entry")
    # `RespawnNearbyHordeMembers`. Off is the overwhelming majority of `AutoHealBehavior`s in a
    # mod, and they leave here.
    a.emit(0x80, 0xBB, struct.pack("<I", AUTO_HEAL_RESPAWN_NEARBY_HORDE_MEMBERS), 0x00)
    a.jcc(JE, "leave")

    # The radius arm's own delay gate, recomputed: `RespawnMinimumDelay` past the frame the last
    # respawn was stamped at. `edx` is the module base for the rest of the entry.
    a.emit(0x8B, 0x55, _ebp(AUTO_HEAL_MODULE_BASE_SLOT))  # mov edx, [ebp-0x20]
    a.emit(0x8B, 0x8B, struct.pack("<I", AUTO_HEAL_RESPAWN_MINIMUM_DELAY))  # mov ecx, [ebx+0x17c]
    a.emit(0x03, 0x4A, AUTO_HEAL_LAST_RESPAWN_FRAME)  # add ecx, [edx+0x34]
    a.emit(0xA1, struct.pack("<I", THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JB, "leave")

    # The arm destroyed its list at 0x00855ABC without resetting the scope index, so an unwind out
    # of the calls below would run that destructor a second time. The radius arm clears the index
    # the same way before its own last destructor.
    a.emit(0x83, 0x4D, _ebp(AUTO_HEAL_SCOPE_INDEX_SLOT), 0xFF)  # or dword [ebp-4], -1

    # Stamp before iterating rather than after, because `edx` does not survive the calls. The
    # radius arm stamps whenever its gate was open too, respawn or no respawn.
    a.emit(0x89, 0x42, AUTO_HEAL_LAST_RESPAWN_FRAME)  # mov [edx+0x34], eax

    # `iterateContained(callback, moduleData, 1)` - the same slot, on the same interface, with the
    # same trailing argument the arm passed it three instructions before the hook.
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x53)  # push ebx  - the ModuleData, as userData
    a.emit(0x68, struct.pack("<I", a.label_va("callback")))  # push callback
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.emit(0x8B, 0x07)  # mov eax, [edi]
    a.emit(_call_slot(CONTAIN_ITERATE_SLOT))

    a.label("leave")
    a.jmp_absolute(AUTO_HEAL_UPDATE_TAIL)


def build_code(base_va: int) -> bytes:
    """The whole cave: a jump to the entry, the callback, then the entry.

    The callback is laid out first because the entry has to `push` its address, and the only honest
    source for that is a label already placed. Which puts a five-byte `jmp` at the section base,
    where the hook lands.
    """
    a = Asm(base_va)
    a.jmp("entry")
    _emit_callback(a)
    _emit_entry(a)
    return a.finish()


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off


class ContainedHordeRespawnPatch(Patch):
    """Run `AutoHealBehavior`'s horde respawn on the passengers `AffectsContained` heals."""

    name = "contained-horde-respawn"
    author = "officialNecro"
    description = (
        "makes RespawnNearbyHordeMembers work alongside AffectsContained on AutoHealBehavior, so a "
        "garrison tower or transport replenishes the battalion inside it instead of only healing "
        "it. The stock engine reads RespawnNearbyHordeMembers in one arm of the update and "
        "AffectsContained in the arm above it, so writing both keyword lines today silently gets "
        "only the healing, and no module in the engine can replenish a contained horde at all - "
        "both the radius arm and ReplenishUnitsBehavior only see what a partition range query "
        "returns. Each passenger is gated exactly as the radius arm gates a horde it finds: KindOf "
        "HORDE, not under construction, and live members below its contain's Slots, with "
        "RespawnMinimumDelay and RespawnFXList read from the same fields. Needs no INI, .str or "
        "map change - the keywords already exist, and a module without AffectsContained is "
        "untouched"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        exit_off = _offset(data, AUTO_HEAL_CONTAINED_EXIT)

        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (AUTO_HEAL_CONTAINED_EXIT + 5))
        apply_byte_patch(
            data,
            exit_off,
            AUTO_HEAL_CONTAINED_EXIT_BYTES,
            jump,
            f"AutoHealBehavior AffectsContained exit @0x{AUTO_HEAL_CONTAINED_EXIT:08x} -> "
            f"{SECTION_NAME} cave",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        try:
            exit_off = _offset(data, AUTO_HEAL_CONTAINED_EXIT)
        except ValueError as exc:
            return [str(exc)]

        located = find_section(data, SECTION_NAME)
        if located is None:
            problems.append(f"{SECTION_NAME} section is absent")
            return problems
        section_va, section_off, _ = located

        site = f"the AffectsContained exit @0x{AUTO_HEAL_CONTAINED_EXIT:08x}"
        if data[exit_off] != 0xE9:
            problems.append(f"{site} is not a jmp - the hook is not installed")
        else:
            displacement = struct.unpack_from("<i", data, exit_off + 1)[0]
            target = AUTO_HEAL_CONTAINED_EXIT + 5 + displacement
            if target == AUTO_HEAL_UPDATE_TAIL:
                problems.append(f"{site} is unpatched - it still jumps straight to the tail")
            elif target != section_va:
                problems.append(f"{site} jumps to 0x{target:08x}, expected 0x{section_va:08x}")

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected respawn")
        return problems

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Refuse a build where the five bytes are not the ones this patch read.

        The constructor's vtable store, the update vtable slot and the module-name string say the
        function is `AutoHealBehavior::update`; the prologue says which register holds the
        `ModuleData` and which frame slot the module base; the `AffectsContained` gate and the
        contain fetch say what `edi` holds at the hook, and the list destructor abuts it; the
        delay gate and the write-back locate the respawn timestamp; the respawn block is what the
        cave transcribes, and the four routine entries are what it calls.
        """
        for va, expected in AUTO_HEAL_ANCHORS.items():
            got = bytes(data[_offset(data, va) :][: len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the game.dat these addresses were read from"
                )
