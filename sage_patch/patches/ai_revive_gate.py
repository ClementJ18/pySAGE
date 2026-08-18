"""The AI revive-gate patch: make the AI honour a REVIVE button's ``NeededUpgrade``.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/ai-revive-gate.md``.

**The defect.** ``BuildAssistant::canMakeUnit(producer, what, reviveIndex)`` is the one gate the
AI consults before deciding a producer may make something. It walks the producer's `CommandSet`
and branches on whether a revive index was passed:

* the **template** branch (`UNIT_BUILD` / `FOUNDATION_CONSTRUCT` / `DOZER_CONSTRUCT`) matches the
  thing template *and* evaluates the button's ``NEED_UPGRADE`` / ``NeededUpgrade`` requirement;
* the **revive** branch tests only ``Command == REVIVE`` and a positional count of the REVIVE
  buttons seen so far, accepting when that count reaches ``reviveIndex``. It never reads
  ``Options`` or ``NeededUpgrade``.

So a REVIVE button gated by an upgrade its building can never hold is refused to the player -
whose control bar evaluates the requirement - and honoured for the AI. Mods reach hero
recruitment through the revive system precisely because heroes attach to REVIVE slots by
position, which forces every building that recruits *any* hero to carry the whole slot block;
the surplus slots are then disabled by an unobtainable ``NeededUpgrade``. The AI ignores that
and recruits any hero from any such building.

**What this does.** Appends an ``.aigate`` PE section holding a rewritten revive branch, and
redirects the branch's six-byte entry into it. The rewrite counts the matched slot *before*
handing control to the engine's own upgrade gate at ``CAN_MAKE_UNIT_UPGRADE_GATE``, whose
success edge already falls into the accept path and whose failure edge already continues the
walk.

**Why route into the engine's gate instead of re-implementing it.** The gate handles
``NeededUpgradeAny``, the object-vs-player distinction between upgrade types, and the
empty-``NeededUpgrade`` case. Re-deriving those in a cave would be a second implementation of
semantics the binary already states, free to drift from the template branch. This patch adds no
engine calls of its own; it only adds an edge.

**Why the slot is counted before the gate runs.** On a gate failure the engine's own edge
continues to the next `CommandSet` slot. Had the count not advanced, the *next* REVIVE button
would match the same ``reviveIndex`` and be tested in turn - so the AI would slide past a
disabled slot onto the following enabled one, and answer for a different hero than the one the
index names. Counting first makes a failure final for that index: no later slot can match, the
walk runs out, and ``canMakeUnit`` returns false. That keeps the AI's slot-to-hero mapping the
same one the player sees, rather than merely a stricter one.

**Scope: the AI only, and it takes work.** ``canMakeUnit`` has **five** call sites. Four are AI
(the factory search behind unit and hero production, and the tactic that enumerates revivable
heroes) and reach it directly through `TheBuildAssistant`'s vtable. The fifth is
``BuildAssistant``'s own ``+0x64`` gate at ``CAN_MAKE_UNIT_PRODUCTION_GATE``, which reaches it by
a **virtual self-call** on its own ``this`` - and *that* is what the ControlBar asks for button
availability and what ``ProductionUpdate::queueCreateUnit`` asks before queueing. So the revive
branch is squarely on the player's path, and a gate applied unconditionally there stops a human
recruiting heroes.

The cave therefore tests **who asked**: ``[ebp+4]`` is `canMakeUnit`'s return address, and the
one value that means "not the AI" is the instruction after that self-call. Anything arriving that
way takes the stock edge, so this patch cannot change what is shown, clickable or queueable - for
the player *or* for the AI. It changes only which producer the AI *chooses*, which is the whole
of the defect.

**Why the walk cannot be trusted to name the button.** The stock revive branch uses the matched
slot only as a count: reach `reviveIndex` REVIVE buttons and the answer is
``ReviveMgr::canRevive(reviveIndex)``, whatever button that was. The ControlBar builds its own
button-to-hero mapping in a separate walk (``0x00943F81``) with its own skip rules, over the
*visible* command range. Where the two disagree the stock engine cannot tell, because it never
reads the matched button - but a gate does. Restricting the gate to the AI's own queries keeps
that disagreement as harmless as it has always been on every path a human touches.

**Determinism.** The gate reads upgrade masks off the `Object` and its `Player` - logic state,
identical on every peer - so the added edge is network- and replay-safe. Gating on a button's
``DisableOnModelCondition`` would not be: model-condition state is client-side.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the six at the revive
branch's entry, which no other bundled patch touches, and it reads nothing another patch
rewrites - the three addresses its cave jumps to are all below
``CAN_MAKE_UNIT_SCAN_BOUND``, the one nearby site ``commandset-limit`` edits.
"""

from __future__ import annotations

import struct

from ..addresses import (
    BUILD_ASSISTANT_VTABLE,
    CAN_MAKE_UNIT,
    CAN_MAKE_UNIT_ACCEPT,
    CAN_MAKE_UNIT_BUMP_SLOT,
    CAN_MAKE_UNIT_NEXT_SLOT,
    CAN_MAKE_UNIT_PRODUCTION_GATE,
    CAN_MAKE_UNIT_PRODUCTION_GATE_CALL,
    CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES,
    CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
    CAN_MAKE_UNIT_REVIVE_BRANCH,
    CAN_MAKE_UNIT_REVIVE_BRANCH_ENTRY,
    CAN_MAKE_UNIT_UPGRADE_GATE,
    CAN_MAKE_UNIT_VTABLE_SLOT,
    GUICOMMAND_REVIVE,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "AiReviveGatePatch",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "PRODUCTION_GATE_RETURN",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".aigate"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = CAN_MAKE_UNIT_REVIVE_BRANCH
HOOK_ORIGINAL = CAN_MAKE_UNIT_REVIVE_BRANCH_ENTRY

#: The address `BuildAssistant`'s `+0x64` gate returns to, and therefore the return address
#: `canMakeUnit` sees on the stack when it was reached that way rather than by the AI directly.
#: Derived from the anchored call rather than written down, so a build whose layout moved fails
#: on the anchor instead of comparing against a stale constant.
PRODUCTION_GATE_RETURN = CAN_MAKE_UNIT_PRODUCTION_GATE_CALL + len(
    CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES
)

#: The first instruction at each address the cave jumps to or reads, as a `{va: bytes}` map. The
#: revive branch's own bytes are asserted by `apply_byte_patch`; these are the jump targets and
#: the call the return-address test is derived from, which nothing else would catch. A build
#: whose layout moved fails here instead of on a wild jump or a mis-aimed comparison.
ANCHORS = {
    CAN_MAKE_UNIT_UPGRADE_GATE: bytes.fromhex("8b461c"),  # mov eax, [esi+0x1c]   ; Options
    CAN_MAKE_UNIT_ACCEPT: bytes.fromhex("8b4d08"),  # mov ecx, [ebp+8]      ; the producer
    CAN_MAKE_UNIT_BUMP_SLOT: bytes.fromhex("ff45f4"),  # inc dword [ebp-0xc]   ; slots seen
    CAN_MAKE_UNIT_NEXT_SLOT: bytes.fromhex("ff45f8"),  # inc dword [ebp-8]     ; slot index
    CAN_MAKE_UNIT_PRODUCTION_GATE_CALL: CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The rewritten revive branch. Reached only from the hook, and never returns to it."""
    a = Asm(base_va)
    a.emit(0x83, 0x7E, 0x14, GUICOMMAND_REVIVE)  # cmp dword [esi+0x14], GUICOMMAND_REVIVE
    a.jcc(JE, "is_revive")
    a.jmp_absolute(CAN_MAKE_UNIT_NEXT_SLOT)  # not a REVIVE button

    a.label("is_revive")
    a.emit(0x8B, 0x45, 0xF4)  # mov eax, [ebp-0xc]       ; REVIVE slots seen
    a.emit(0x3B, 0x45, 0x10)  # cmp eax, [ebp+0x10]      ; the requested revive index
    a.jcc(JE, "matched")
    a.jmp_absolute(CAN_MAKE_UNIT_BUMP_SLOT)  # a REVIVE slot, but not this index

    a.label("matched")
    # Whose question is this? `canMakeUnit` is reached either directly - only the AI does that -
    # or through `BuildAssistant`'s `+0x64` gate, which is what the ControlBar and production ask.
    # The gate is for the AI's choice of producer, so anything arriving through `+0x64` takes the
    # stock edge and this patch cannot change what is shown, clickable or queueable.
    a.emit(0x81, 0x7D, 0x04, struct.pack("<I", PRODUCTION_GATE_RETURN))  # cmp [ebp+4], <return>
    a.jcc(JE, "not_the_ai")

    # Count it now: the gate's failure edge continues the walk, and a slot that has been counted
    # cannot be matched again, so failing the gate ends the search for this index.
    a.emit(0xFF, 0x45, 0xF4)  # inc dword [ebp-0xc]
    a.jmp_absolute(CAN_MAKE_UNIT_UPGRADE_GATE)

    a.label("not_the_ai")
    a.jmp_absolute(CAN_MAKE_UNIT_ACCEPT)
    return a.finish()


class AiReviveGatePatch(Patch):
    name = "ai-revive-gate"
    author = "officialNecro"
    description = (
        "Make the AI respect a REVIVE button's NeededUpgrade, as the player already does. No "
        "INI change: what gates the AI is the NeededUpgrade / NeededUpgradeAny already on the "
        "CommandButton"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        # Prove the function being edited is the one the AI dispatches to, and that the points
        # the cave jumps back into still hold the instructions they are chosen for.
        self._check_dispatch(data)
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "canMakeUnit revive branch -> ai-revive-gate cave",
        )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless `BuildAssistant`'s vtable still names both functions this depends on: the
        one being edited, and the `+0x64` gate whose return address separates the AI's queries
        from everyone else's."""
        for slot, expected, what in (
            (CAN_MAKE_UNIT_VTABLE_SLOT, CAN_MAKE_UNIT, "the revive branch being patched"),
            (
                CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
                CAN_MAKE_UNIT_PRODUCTION_GATE,
                "the production gate the return-address test names",
            ),
        ):
            slot_va = BUILD_ASSISTANT_VTABLE + slot
            slot_off = va_to_offset(data, slot_va)
            if slot_off is None:
                raise ValueError("the BuildAssistant vtable is not mapped - not the expected build")
            target = struct.unpack_from("<I", data, slot_off)[0]
            if target != expected:
                raise ValueError(
                    f"vtable slot {slot_va:#010x} dispatches to {target:#010x}, not "
                    f"{expected:#010x} - {what} is not the live one"
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - canMakeUnit's "
                    "layout is not this build's, so the cave would jump into the wrong place "
                    "or test the wrong return address"
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
            problems.append(f"the {SECTION_NAME} cave does not hold the expected branch")
        return problems
