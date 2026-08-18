"""The unique-production-id patch: stop a hero recruit from eating the money and doing nothing.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/unique-production-id.md``.

**The defect.** ``ProductionUpdateInterface::requestUniqueUnitID`` mints the ``ProductionID``
that names one queued production, and it mints it from a counter held **on the producer**
(``ProductionUpdate`` module ``+0x30``, seeded to 1 by the constructor). Every building
therefore hands out the same ids: the first thing each building ever produces is production 1,
the second is production 2, and so on.

That is harmless for ordinary unit production, whose queue is per-building - but hero
recruitment goes through the revive system, whose bookkeeping is **per player**. A revive
records its production id on the player's revive entry, and ``ReviveMgr::startRevive`` refuses
an id already recorded on another entry, because cancelling and completing a revive both find
their entry by that id and would otherwise reach the wrong hero.

So recruiting a hero from a second building while the first building's hero is still coming
collides on the id. ``ProductionUpdate::queueCreateUnit`` withdraws the cost **before** it calls
``startRevive`` and does not refund on the failure edge, so the click costs the money and starts
nothing. The counter still advanced, so retrying eventually finds a free id - which is why the
same click works on the second or third try, and why recruiting several heroes from *one*
building was never affected.

**What this does.** Appends a four-byte ``.prodid`` section holding one counter, and rewrites
``requestUniqueUnitID`` in place to mint from it instead:

.. code-block:: none

    mov eax, <counter>     ; the appended section's address
    inc dword [eax]
    mov eax, [eax]         ; the post-increment value: 1, 2, 3, ... game-wide
    ret

Ten bytes replacing ten, so there is no hook, no cave and no displaced instruction. Ids now
number the whole game rather than one building, which is what "unique" has to mean for a
consumer that is keyed per player.

**Why the mint rather than the check.** ``startRevive``'s refusal is correct as written: two
live revives of one player must not share an id, or cancel and complete would pick the wrong
one. The bug is that the id it is handed is not unique in the space that check ranges over. The
alternatives - widening the revive entry to hold the producer as well, or renumbering inside
``startRevive`` - both have to write back through a caller that has already stamped the id onto
its `ProductionEntry`. Minting a genuinely unique id fixes the cause and leaves every consumer
alone.

**Why no refund is added.** After this patch ``startRevive`` cannot fail on a click at all. Its
other two refusals - an unknown revive index, and a hero whose revive is already running - are
both pre-empted by ``BuildAssistant::canMakeUnit``, which ``queueCreateUnit`` consults through
the `TheBuildAssistant` vtable's ``+0x64`` entry *before* the money moves, and which ends a
revive query with ``ReviveMgr::canRevive(index)``. The id collision was the one reachable
failure past the withdrawal, so removing it removes the lost money rather than papering over it.

**The first id is unchanged.** The stock counter starts at 1 and is read before it advances; the
new one starts at 0 and is read after, so both mint 1, 2, 3, ... The id 0 stays unmintable,
which matters: a revive entry that has never been used holds 0 in that field, and -1 once
cancelled.

**Determinism.** The counter advances once per production request on the logic thread, off the
order stream, so every peer walks the same sequence - the same property the per-building
counters already needed, since their ids are compared inside the revive manager. The ten call
sites are the two `Object::doCommandButton` cases, ``queueCreateUnit``'s own loop, and seven
AI/script production paths; none is client-side.

**Composition.** Order-independent: the section is allocated past every existing one and
:meth:`verify` finds it by name. The ten bytes it rewrites are the whole of one leaf function
that no other bundled patch touches, and it reads nothing another patch rewrites.
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
    """The replacement `requestUniqueUnitID`, minting from the counter at ``counter_va``.

    Exactly as long as the body it replaces, so it is written over the stock function rather
    than hooked. Hand-encoded rather than assembled: the sequence is four instructions with no
    branch, so there is no address arithmetic for :mod:`sage_patch.asm` to protect.
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
