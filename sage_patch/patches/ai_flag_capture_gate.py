"""The AI flag-capture gate: stop the skirmish AI sending capture squads at build plots it
cannot capture.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/ai-flag-capture-gate.md``.

**The defect.** `AIFlagCaptureSquad` is one of the skirmish AI's *targetless* tactics - the
family that acts on the map rather than on an enemy force. Every 100-450 frames it may build a
squad of one to three units, name the team ``TARGETLESS_FlagCaptureSquad_<n>_0``, pick a capture
flag and send the squad to stand on it.

Its picker (``AI_FLAG_CAPTURE_PICKER``) applies exactly two filters to the global list of every
`CAPTUREFLAG` object on the map: skip anything whose `Player::getRelationship` is ``ALLIES``,
require ``KindOf CAPTUREFLAG``, and keep the nearest survivor. It never asks whether the flag can
actually be captured.

That is fine for a plain capture flag, which is recaptured by walking a squad onto it. It is
wrong for a **build plot** - a settlement, camp, fortress or economy plot - because a plot that
somebody has claimed carries a structure, and the flag underneath it cannot be taken until that
structure is destroyed. Both kinds are `CAPTURABLE CAPTUREFLAG UNATTACKABLE STRUCTURE`, so the
picker cannot tell them apart, and a plot is usually the *nearest* flag to a squad forming up.

The squad then deadlocks, because the tactic's update only releases a target when the flag is
destroyed or turns ``ALLIES``. There is no timeout. The units are given a plain move onto the
flag's position, which is the centre of the structure standing on it and therefore inside an
impassable footprint, so they never arrive - and the move state they are parked in holds
``NO_AUTO_ACQUIRE``, which overrides the ``AutoAcquireEnemiesWhenIdle`` their own
`HordeAIUpdate` declares. The visible result is a battalion or two circling an enemy building
forever without attacking it, for the rest of the match.

**What this does.** Appends an ``.aiflag`` PE section holding a replacement ownership test, and
redirects the picker's five-byte test into it. The replacement keeps the stock ``ALLIES`` skip
and adds one more rejection: a candidate that is both ``KindOf BASE_SITE`` **and**
``ObjectStatus UNSELECTABLE`` is dropped.

**Why those two conditions and not "is it an enemy's".** ``BASE_SITE`` is what separates the two
kinds of flag, and it has to be tested first: without it an enemy-held plain capture flag would
be excluded too, and recapturing exactly those is the tactic's whole purpose. Every plot flag in
the data carries it (`FestungPlotFlag_Real`, `LagerPlotFlag_Real`, `WirtschaftPlotFlag_Real`,
`DefensivePlotFlag`, `ExpansionPlotFlag`, `HalfCastlePlotFlag_Real`) and no plain capture flag
does.

``UNSELECTABLE`` is then the engine's own record that the plot has been claimed - an unclaimed
plot is selectable, because clicking it is how a player builds on it. Testing that rather than
ownership keeps two cases right that an ownership test gets wrong: a free plot stays a target
however far away it is, and a claimed-but-not-yet-allied plot is dropped without the gate having
to reason about what ``NEUTRAL`` means for the civilian player who owns unclaimed plots.

**What the AI still does.** Everything except the impossible case. Free plots remain targets, so
the tactic keeps grabbing economy and expansion plots, which is the behaviour it exists for;
plain capture flags are untouched by the new test entirely; and an enemy plot that is a real
target is already handled by a different tactic - `AIFarmKillSquad` carries the structures on
those plots in its own candidate list and sends squads to destroy them.

**Scope: the AI only, and for free.** The picker lives inside the `SkirmishAI` subsystem and has
exactly one caller, ``AIFlagCaptureSquad::update``. Nothing a human does reaches it, so unlike
`ai-revive-gate` this needs no return-address discrimination.

**Determinism.** The gate reads a `KindOf` off the `ThingTemplate` and one bit of the object's
own status mask - both logic state, identical on every peer - so the added edge is network- and
replay-safe. It is still a logic-side change: **every peer needs the same binary.**

**Null candidates.** The cave dereferences ``[esi+4]`` on the path the stock code reaches
``mov eax, [esi+4]`` on, and no other. A null candidate faults in exactly the place and for
exactly the reason it already did.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the five at the picker's
ownership test, which no other bundled patch touches, and it reads nothing another patch
rewrites.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_FLAG_CAPTURE_KEEP,
    AI_FLAG_CAPTURE_PICKER,
    AI_FLAG_CAPTURE_PICKER_CALL,
    AI_FLAG_CAPTURE_PICKER_CALL_BYTES,
    AI_FLAG_CAPTURE_PICKER_ENTRY,
    AI_FLAG_CAPTURE_RELATIONSHIP_TEST,
    AI_FLAG_CAPTURE_RELATIONSHIP_TEST_BYTES,
    AI_FLAG_CAPTURE_SKIP,
    AI_FLAG_CAPTURE_SQUAD_NAME_PUSH,
    AI_FLAG_CAPTURE_SQUAD_NAME_PUSH_BYTES,
    AI_FLAG_CAPTURE_SQUAD_UPDATE,
    AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT,
    AI_FLAG_CAPTURE_SQUAD_VTABLE,
    KINDOF_BASE_SITE,
    OBJECT_STATUS,
    OBJECT_STATUS_UNSELECTABLE,
    PLAYER_RELATIONSHIP_ALLIES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

# `test byte [reg + base + bit/8], 1 << (bit % 8)` is how the engine asks a single bit of either
# bitfield: `KindOf` on the `ThingTemplate` and `ObjectStatus` on the `Object` differ only in
# their base displacement. `kind_of.bit_test` emits exactly that encoding and nothing about it is
# `KindOf`-specific beyond where it lives, so it serves for both rather than being duplicated.
from .utils.kind_of import THING_TEMPLATE_MASK_OFFSET, bit_test

__all__ = [
    "ANCHORS",
    "AiFlagCaptureGatePatch",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".aiflag"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = AI_FLAG_CAPTURE_RELATIONSHIP_TEST
HOOK_ORIGINAL = AI_FLAG_CAPTURE_RELATIONSHIP_TEST_BYTES

#: ModRM r/m encodings for the two registers the cave reads through: `esi` is the candidate
#: `Object` the picker is holding, `ecx` the `ThingTemplate` the cave loads from it.
_ESI = 6
_ECX = 1

#: The first instruction at each address the cave jumps to, plus the two that prove the function
#: being edited is the flag-capture tactic's picker: its own prologue, its single call site inside
#: `AIFlagCaptureSquad::update`, and the constructor push that names the tactic in plain text. The
#: test's own bytes are asserted by `apply_byte_patch`; these are what nothing else would catch,
#: so a build whose layout moved fails here rather than on a wild jump.
ANCHORS = {
    AI_FLAG_CAPTURE_PICKER: AI_FLAG_CAPTURE_PICKER_ENTRY,
    AI_FLAG_CAPTURE_PICKER_CALL: AI_FLAG_CAPTURE_PICKER_CALL_BYTES,
    AI_FLAG_CAPTURE_SQUAD_NAME_PUSH: AI_FLAG_CAPTURE_SQUAD_NAME_PUSH_BYTES,
    AI_FLAG_CAPTURE_KEEP: bytes.fromhex("8b4604"),  # mov eax, [esi+4]  ; ThingTemplate*
    AI_FLAG_CAPTURE_SKIP: bytes.fromhex("83c304"),  # add ebx, 4        ; next candidate
}


def build_code(base_va: int) -> bytes:
    """The replacement ownership test. Reached only from the hook, and never returns to it.

    On entry ``eax`` holds what `Player::getRelationship` just answered for the candidate and
    ``esi`` is the candidate `Object`. Both of the cave's exits are edges the stock picker
    already had, so nothing downstream can tell the difference except in the case this exists to
    change.
    """
    a = Asm(base_va)
    # The stock test, verbatim: one's own and one's allies' flags are not targets.
    a.emit(0x83, 0xF8, PLAYER_RELATIONSHIP_ALLIES)  # cmp eax, ALLIES
    a.jcc(JE, "skip")

    # BASE_SITE first, and on its own: a plain capture flag is recaptured by standing on it, which
    # is what this tactic is for, so it must reach the accept edge whoever holds it.
    a.emit(0x8B, 0x4E, 0x04)  # mov ecx, [esi+4]      ; ThingTemplate*
    a.emit(bit_test(KINDOF_BASE_SITE, _ECX, THING_TEMPLATE_MASK_OFFSET))
    a.jcc(JE, "keep")

    # A build plot, then. Claimed plots are unselectable - a free one is selectable because
    # clicking it is how a player builds on it - and a claimed plot carries a structure that has
    # to be destroyed before the flag under it can be taken by anyone.
    a.emit(bit_test(OBJECT_STATUS_UNSELECTABLE, _ESI, OBJECT_STATUS))
    a.jcc(JNE, "skip")

    a.label("keep")
    a.jmp_absolute(AI_FLAG_CAPTURE_KEEP)

    a.label("skip")
    a.jmp_absolute(AI_FLAG_CAPTURE_SKIP)
    return a.finish()


class AiFlagCaptureGatePatch(Patch):
    name = "ai-flag-capture-gate"
    author = "officialNecro"
    description = (
        "Stop the skirmish AI's flag-capture squads targeting build plots that are already "
        "claimed, which they can never capture and stall on forever. No INI change: what the "
        "gate reads is the BASE_SITE KindOf every plot flag already carries"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_dispatch(data)
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        # The stock test is five bytes and `jmp rel32` is five bytes, so nothing needs padding.
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "AIFlagCaptureSquad flag picker -> ai-flag-capture-gate cave",
        )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless `AIFlagCaptureSquad`'s vtable still names the update that calls the picker
        being edited. The anchors prove the call exists; this proves the function it sits in is
        the one the tactics generator actually dispatches to."""
        slot_va = AI_FLAG_CAPTURE_SQUAD_VTABLE + AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT
        slot_off = va_to_offset(data, slot_va)
        if slot_off is None:
            raise ValueError("the AIFlagCaptureSquad vtable is not mapped - not the expected build")
        target = struct.unpack_from("<I", data, slot_off)[0]
        if target != AI_FLAG_CAPTURE_SQUAD_UPDATE:
            raise ValueError(
                f"vtable slot {slot_va:#010x} dispatches to {target:#010x}, not "
                f"{AI_FLAG_CAPTURE_SQUAD_UPDATE:#010x} - the tactic whose picker is being gated "
                "is not the live one"
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the flag picker's "
                    "layout is not this build's, so the cave would jump into the wrong place"
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
            problems.append(f"the {SECTION_NAME} cave does not hold the expected test")
        return problems
