"""The horde-exit-absorption patch: a hero recruited in parallel stops joining the battalion
that is walking out of the same building.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/horde-exit-absorption.md``.

**The defect.** `QueueProductionExitUpdate` - the door every production building pushes finished
objects out of - remembers **one** horde, in a single `ObjectID` at module ``+0x40``
(`QUEUE_EXIT_PENDING_HORDE`). `exitObjectViaDoor` writes it whenever the object leaving is
`KINDOF HORDE` (`QUEUE_EXIT_REMEMBER_HORDE`), and the only thing that clears it is
`QUEUE_EXIT_FINISH`, which `ProductionUpdate::update` calls when a whole queue entry has been
emitted. A battalion's entry is `Slots + 1` objects long (`PRODUCTION_HORDE_ENTRY_REWRITE`), so
the field names that battalion for the fourteen-odd logic frames its members take to come out.

For every one of those frames, the *head* of the same `exitObjectViaDoor`
(`QUEUE_EXIT_HORDE_LOOKUP`) resolves the remembered id and, if it is still alive,
**unconditionally** binds whatever is leaving to it (`QUEUE_EXIT_BIND_BLOCK`):
`setProducer(horde)`, the horde interface's slot assignment, `setTeam(horde->m_team)`. Nothing
tests what the object is. Further down, `QUEUE_EXIT_LONE_UNIT_FLAG` reads the same resolved
pointer to decide whether this is a lone unit, and only a lone unit gets the structure's rally
point appended to its own exit path.

Hero revives queue in **parallel** with unit entries on the same `ProductionUpdate`, so a hero
finishing inside that window is bound to a battalion it has nothing to do with: its producer link
points at the horde - which is what the engine's own target resolver reads to decide "this unit is
part of that horde" - it is put on the horde's team, and it is denied its own rally-point
waypoint, so it walks out of the door and is then dragged along by the battalion's move order.

**What this does.** Redirects the five bytes of that one `findObjectByID` call into a cave that
answers the question the stock code never asks: *does this object belong in that horde?* It does
if the horde still has an unfilled formation slot whose declared payload template is equivalent to
the object's - which is exactly the rule `HORDE_IFACE_ASSIGN_SLOT` applies a few instructions
later, walked here with the same offsets, the same three helpers and the same registers. An object
that fails it makes the cave hand back NULL, and NULL is the answer the stock code already has a
path for: the whole bind block is skipped, `QUEUE_EXIT_LONE_UNIT_FLAG` reads "lone unit", and the
object leaves exactly as it would from a building with no battalion in the door.

**Why the horde's own rule and not a `KINDOF HERO` test.** A hero pair is itself a horde -
`LothlorienRumil` fields Rumil and Orophin as a two-slot battalion - so the member walking out of
that door *is* `KINDOF HERO` and *does* belong. The template test keeps that case working and
still refuses a separately-recruited hero, because the discriminator is the battalion's payload
list, not the kind of thing being produced.

**What it does not do.** The hero's own queue entry still completes while the battalion is
mid-exit, and `ProductionUpdate::update` still calls `QUEUE_EXIT_FINISH` on entry completion
whatever that entry produced - so the battalion's ranks are still closed early. That is a second
consequence of the same shared field and it needs a discriminator that is not available at that
site; ``../docs/horde-exit-absorption.md`` says what it would take and why the obvious gate is
worse than the bug. This patch narrows the binding and nothing else.

**The lazy slot list is built a few instructions early.** `HORDE_IFACE_ASSIGN_SLOT` fills the
free-slot list on first use, so the cave has to do the same before it can walk it. That call is
the one the stock code would make at the next site it reaches, with the same argument, on the same
horde, on the same frame - so nothing observes the difference except an object the cave rejects,
whose horde has its list built a little sooner than it otherwise would and needs it built anyway.

**Every peer must run the same patched binary.** Which objects a horde contains is logic state
feeding the per-frame CRC, so a patched and an unpatched client diverge the first time a hero is
recruited during a battalion's exit, and replays do not cross. Same requirement as
`production-condition`, `hero-recruit-parallel` and `rebuild-hole-construction`.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name.
The only engine bytes it edits are the five at `QUEUE_EXIT_HORDE_LOOKUP`. `smart-rally` is the
other patch that reaches into this module - it grows the module to ``0x48`` for a field at
``+0x44`` and hooks ``0x008A39AC``, ``0x008A3BF0`` and ``0x008A3D14`` - and none of those is this
site, nor does either patch read what the other writes.
"""

from __future__ import annotations

import struct

from ..addresses import (
    CONTAIN_GET_HORDE_IFACE,
    CONTAIN_GET_HORDE_IFACE_ENTRY,
    CONTAIN_GET_HORDE_IFACE_SLOT,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    HORDE_CONTAIN_BUILD_SLOTS_SLOT,
    HORDE_CONTAIN_IFACE,
    HORDE_IFACE_ASSIGN_SLOT,
    HORDE_IFACE_ASSIGN_SLOT_BYTES,
    HORDE_IFACE_FREE_SLOTS,
    HORDE_IFACE_SLOT_ARRAY,
    HORDE_IFACE_SLOT_INDEX,
    HORDE_IFACE_SLOT_STRIDE,
    HORDE_IFACE_SLOTS_BUILT,
    HORDE_PAYLOAD_ENTRY_NAME,
    HORDE_PAYLOAD_LOOKUP,
    HORDE_PAYLOAD_LOOKUP_ENTRY,
    MODULE_MODULE_DATA,
    OBJECT_CONTAIN,
    OBJECT_THING_TEMPLATE,
    QUEUE_EXIT_BIND_BLOCK,
    QUEUE_EXIT_BIND_BLOCK_BYTES,
    QUEUE_EXIT_HORDE_LOOKUP,
    QUEUE_EXIT_HORDE_LOOKUP_BYTES,
    QUEUE_EXIT_LONE_UNIT_FLAG,
    QUEUE_EXIT_LONE_UNIT_FLAG_BYTES,
    QUEUE_EXIT_OBJECT_VIA_DOOR,
    QUEUE_EXIT_OBJECT_VIA_DOOR_ENTRY,
    QUEUE_EXIT_REMEMBER_HORDE,
    QUEUE_EXIT_REMEMBER_HORDE_BYTES,
    THE_THING_FACTORY,
    THING_FACTORY_FIND_TEMPLATE,
    THING_FACTORY_FIND_TEMPLATE_ENTRY,
    THING_TEMPLATE_IS_EQUIVALENT,
    THING_TEMPLATE_IS_EQUIVALENT_ENTRY,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "HordeExitAbsorptionPatch",
    "build_code",
]

SECTION_NAME = ".hrdexit"  # 8 chars exactly: the PE name field truncates silently past 8

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = QUEUE_EXIT_HORDE_LOOKUP
HOOK_ORIGINAL = QUEUE_EXIT_HORDE_LOOKUP_BYTES

#: The `ModuleData` of a horde interface, reached the way its own methods reach it: the interface
#: sits at module `+0x11C`, so module `+0x04` is `0x11C - 0x04` bytes behind it.
_IFACE_TO_MODULE_DATA = HORDE_CONTAIN_IFACE - MODULE_MODULE_DATA

#: The first bytes at everything the cave calls, plus the three sites that pin what the field it
#: gates *means*: where the pending horde is written, what the stock code does with it, and what
#: reads the same answer to decide whether this is a lone unit. A build whose layout moved fails
#: here instead of walking a list that is no longer that list.
ANCHORS = {
    # the function being edited, and the three sites inside it this patch reasons about
    QUEUE_EXIT_OBJECT_VIA_DOOR: QUEUE_EXIT_OBJECT_VIA_DOOR_ENTRY,
    QUEUE_EXIT_BIND_BLOCK: QUEUE_EXIT_BIND_BLOCK_BYTES,
    QUEUE_EXIT_LONE_UNIT_FLAG: QUEUE_EXIT_LONE_UNIT_FLAG_BYTES,
    QUEUE_EXIT_REMEMBER_HORDE: QUEUE_EXIT_REMEMBER_HORDE_BYTES,
    # the four routines the cave calls
    GAME_LOGIC_FIND_OBJECT_BY_ID: GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY,
    HORDE_PAYLOAD_LOOKUP: HORDE_PAYLOAD_LOOKUP_ENTRY,
    THING_FACTORY_FIND_TEMPLATE: THING_FACTORY_FIND_TEMPLATE_ENTRY,
    THING_TEMPLATE_IS_EQUIVALENT: THING_TEMPLATE_IS_EQUIVALENT_ENTRY,
    # `getHordeIface` returning the sub-object at module +0x11C - the one fact that makes
    # `[obj+0x258]` and the interface the cave walks the same object
    CONTAIN_GET_HORDE_IFACE: CONTAIN_GET_HORDE_IFACE_ENTRY,
    # and the rule being mirrored, whole: lazy build, list walk, key lookup, findTemplate,
    # isEquivalentTo. If these 106 bytes still hold, the walk below is the engine's own.
    HORDE_IFACE_ASSIGN_SLOT: HORDE_IFACE_ASSIGN_SLOT_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The membership gate. Replaces the `findObjectByID` at `HOOK_VA` and answers with the horde
    the exiting object belongs to, or NULL.

    Called with `[esp+4]` holding the pending horde's `ObjectID` and `ecx` holding `TheGameLogic`,
    both set up by the two instructions the hook leaves alone, and returns `ret 4` like the call it
    replaces. `ebx` is the exiting `Object*` for the whole of the caller's body and `edi` is its
    `ExitInterface`, so both must come back untouched; `esi` and `edi` are saved because the walk
    uses them, and `ebx` is only read.

    The walk mirrors `HORDE_IFACE_ASSIGN_SLOT` instruction for instruction, including its register
    assignment - `esi` the interface, `edi` the list node, `ebx` the object - which is what lets it
    inherit that loop's own evidence that the three helpers preserve all three.
    """
    a = Asm(base_va)
    # The argument the hooked call site pushed, re-pushed for the callee that still wants it.
    a.emit(0xFF, 0x74, 0x24, 0x04)  # push dword [esp+4]
    a.call_absolute(GAME_LOGIC_FIND_OBJECT_BY_ID)  # eax = the pending horde, or NULL
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "out")  # nothing pending: the stock answer, unchanged

    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x50)  # push eax   - the horde, and the slot the answer comes back in
    a.emit(0x8B, 0x88, struct.pack("<I", OBJECT_CONTAIN))  # mov ecx, [eax+0x258]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "keep")  # no contain module: the stock code skips the bind on its own
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, CONTAIN_GET_HORDE_IFACE_SLOT)  # call [eax+0x7c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "keep")  # likewise: not a horde container, and stock already declines
    a.emit(0x8B, 0xF0)  # mov esi, eax

    # The free-slot list is built on first use, and the walk below is that first use.
    a.emit(0x80, 0x7E, HORDE_IFACE_SLOTS_BUILT, 0x00)  # cmp byte [esi+0x7c], 0
    a.jcc(JNE, "walk")
    a.emit(0x8D, 0x8E, struct.pack("<i", -HORDE_CONTAIN_IFACE))  # lea ecx, [esi-0x11c]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0xFF, 0x90, struct.pack("<I", HORDE_CONTAIN_BUILD_SLOTS_SLOT))  # call [eax+0x84]

    a.label("walk")
    a.emit(0x8B, 0x46, HORDE_IFACE_FREE_SLOTS)  # mov eax, [esi+0x78]
    a.emit(0x8B, 0x38)  # mov edi, [eax]
    a.emit(0x3B, 0xF8)  # cmp edi, eax
    a.jcc(JE, "reject")  # every slot is taken: this horde is not expecting anybody

    a.label("loop")
    a.emit(0x8B, 0x47, HORDE_IFACE_SLOT_INDEX)  # mov eax, [edi+8]
    a.emit(0x6B, 0xC0, HORDE_IFACE_SLOT_STRIDE)  # imul eax, eax, 0x1c
    a.emit(0x03, 0x46, HORDE_IFACE_SLOT_ARRAY)  # add eax, [esi+0x6c]
    a.emit(0xFF, 0x30)  # push dword [eax]  - the slot's payload key
    a.emit(0x8B, 0x8E, struct.pack("<i", -_IFACE_TO_MODULE_DATA))  # mov ecx, [esi-0x118]
    a.call_absolute(HORDE_PAYLOAD_LOOKUP)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_THING_FACTORY))  # mov ecx, [TheThingFactory]
    a.emit(0x83, 0xC0, HORDE_PAYLOAD_ENTRY_NAME)  # add eax, 4  - the entry's template name
    a.emit(0x50)  # push eax
    a.call_absolute(THING_FACTORY_FIND_TEMPLATE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")
    a.emit(0x8B, 0x4B, OBJECT_THING_TEMPLATE)  # mov ecx, [ebx+4]  - the exiting object's template
    a.emit(0x50)  # push eax
    a.call_absolute(THING_TEMPLATE_IS_EQUIVALENT)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "keep")  # a slot this object fits: it really is a member

    a.label("next")
    a.emit(0x8B, 0x3F)  # mov edi, [edi]
    a.emit(0x3B, 0x7E, HORDE_IFACE_FREE_SLOTS)  # cmp edi, [esi+0x78]
    a.jcc(JNE, "loop")

    a.label("reject")
    a.emit(0x58)  # pop eax
    a.emit(0x33, 0xC0)  # xor eax, eax  - "no horde is coming out of this door"
    a.jmp("restore")

    a.label("keep")
    a.emit(0x58)  # pop eax

    a.label("restore")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi

    a.label("out")
    a.emit(0xC2, 0x04, 0x00)  # ret 4  - the callee cleanup the replaced call did
    return a.finish()


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


class HordeExitAbsorptionPatch(Patch):
    name = "horde-exit-absorption"
    author = "officialNecro"
    description = (
        "Stop a hero recruited in parallel from being absorbed into a battalion that is walking "
        "out of the same building. An object only joins the horde in the door when that horde "
        "still has a formation slot its own template fits, which is the engine's own membership "
        "rule. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            hook_off,
            _call_bytes(HOOK_VA, GAME_LOGIC_FIND_OBJECT_BY_ID),
            _call_bytes(HOOK_VA, section_va),
            "exitObjectViaDoor pending-horde lookup -> horde-exit-absorption cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the production "
                    "exit door and the horde's slot list are not this build's, so the cave would "
                    "walk something that is no longer that list"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        expected = _call_bytes(HOOK_VA, section_va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            problems.append(
                f"the pending-horde lookup at {HOOK_VA:#010x} holds {got.hex()}, "
                f"expected {expected.hex()}"
            )

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected membership gate")
        return problems
