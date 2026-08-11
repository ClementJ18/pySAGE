"""The AI construction-gate patch: stop the skirmish AI producing from a building that is still
going up.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/ai-construction-gate.md``.

**The defect.** "A structure that is still under construction may not produce" is a real rule,
and the engine states it in three places - none of them on the path a skirmish AI takes.

* The **ControlBar** (``0x0094307A``) refuses the button. That is client-side UI; the AI never
  runs a line of it.
* The legacy ``AIPlayer::findFactory`` (``0x008F5347``) tests the bit before it asks anything
  else. That is the Generals/BFME1 lineage - correct, and **not what RotWK skirmish runs**.
* ``ProductionUpdate::update`` (``0x008A1CB5``) refuses to let the finished unit *leave*. By then
  the order has been placed and paid for.

RotWK ships the BFME2-era ``SkirmishAI`` subsystem, which has its own producer index and its own
picker. A structure enters that index the frame it is placed - ``AIPlayer``'s structure-created
hook hands the brand-new object to the index builder at ``0x009A0838``, which walks its buildable
list *and* its revive slots while it is still scaffolding. The picker
(`AI_PRODUCER_PICKER`) then filters candidates on dead / has-a-``ProductionUpdate`` /
not-disabled / idle and stops there. A construction site passes all four - emphatically including
idle.

**What this does.** Appends an ``.aicons`` PE section holding a rewritten copy of the picker's
"which arm am I in" branch, and redirects the branch's six-byte entry into it. The rewrite adds
one ``Object::testStatus(UNDER_CONSTRUCTION)`` ahead of the engine's own usable-producer tests,
on the rejection edge those tests already use.

**Why the gate goes in the "use it now" arm only.** The picker's third argument
(``[ebp+0x10]``) selects between two questions. Zero means *pick a producer to use now* - and it
is that arm which runs the disabled and idle tests, and that arm the order pump at
``0x008F0FD4`` calls before stamping the winner's id into a pending build order. Non-zero means
*could anything here ever make this*, and three of the six callers ask it that way: a tactic
deciding whether a plan is possible at all, a cost/time estimator, and - the decisive one - a
sweep that **cancels** an order whose answer comes back null. Gating construction there would
cancel orders because their producer had not finished yet, which is a worse behaviour than the
one being fixed. So the cave reproduces the branch and leaves the hypothetical arm on the
byte-for-byte stock edge.

**Scope: the AI only, and it comes for free.** `AI_PRODUCER_PICKER` is inside ``SkirmishAI`` and
has six direct callers, every one of them AI. Unlike :mod:`~sage_patch.patches.ai_revive_gate` -
whose target sits on the player's path through ``BuildAssistant``'s ``+0x64`` gate and therefore
has to test its own return address - AI-only here falls out of *where the function is*. This
patch cannot change what is shown, clickable or queueable for a human, because no human-facing
code reaches it.

**This makes the AI less bad, not less cheaty.** Worth being clear, because it is the opposite
direction from `ai-revive-gate`. The production queue keeps ticking while a building goes up
(``0x008A1D5B`` is downstream of the exit-step bail), but the finished unit is held at the door
until the structure completes - and ``queueCreateUnit`` took the money at queue time. So the AI
pays, occupies the producer's one queue slot, and gets nothing early, while a finished barracks
next door looked equally attractive to the picker. The defect is a handicap; removing it is a
competence fix.

**Determinism.** The gate reads ``Object::m_status`` - logic state, identical on every peer - so
the added edge is network- and replay-safe. The ``SkirmishAI`` runs on the logic thread on every
peer, so a *non*-deterministic gate here would desync rather than merely misbehave, which is why
the model-condition ``ACTIVELY_BEING_CONSTRUCTED`` is not what is tested even though it names the
same state more precisely.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the six at
`AI_PRODUCER_ANY_BRANCH`, which no other bundled patch touches - they all sit at ``0x0079``,
``0x008A``, ``0x0094`` and ``0x00DA`` - and it reads nothing another patch rewrites.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_PRODUCER_ACCEPT,
    AI_PRODUCER_ANY_BRANCH,
    AI_PRODUCER_ANY_BRANCH_ENTRY,
    AI_PRODUCER_NEXT_CANDIDATE,
    AI_PRODUCER_PICKER,
    AI_PRODUCER_PICKER_CALL,
    AI_PRODUCER_PICKER_CALL_BYTES,
    AI_PRODUCER_PICKER_ENTRY,
    AI_PRODUCER_USABLE_TESTS,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    OBJECT_TEST_STATUS,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "AiConstructionGatePatch",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "PICKER_CALL_TARGET",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".aicons"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: Where `AI_PRODUCER_PICKER_CALL` actually goes, decoded from its own bytes rather than written
#: down, so that "the AI's order pump reaches the function this patch edits" is a *derived* fact
#: an anchor can enforce instead of a comment nobody rechecks. Asserting the call's five bytes -
#: which `ANCHORS` does - therefore also asserts its target.
PICKER_CALL_TARGET = (
    AI_PRODUCER_PICKER_CALL + 5 + struct.unpack("<i", AI_PRODUCER_PICKER_CALL_BYTES[1:5])[0]
)

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = AI_PRODUCER_ANY_BRANCH
HOOK_ORIGINAL = AI_PRODUCER_ANY_BRANCH_ENTRY

#: The first instruction at each address the cave jumps to or calls, as a `{va: bytes}` map. The
#: branch's own bytes are asserted by `apply_byte_patch`; these are the three jump targets, the
#: helper the new test calls, and the picker's own prologue. A build whose layout moved fails
#: here instead of on a wild jump or a mis-aimed `this`.
ANCHORS = {
    AI_PRODUCER_PICKER: AI_PRODUCER_PICKER_ENTRY,  # push ebp; mov ebp,esp; ... - the picker
    AI_PRODUCER_USABLE_TESTS: bytes.fromhex("8b06"),  # mov eax, [esi]  ; ProductionUpdate vtable
    AI_PRODUCER_ACCEPT: bytes.fromhex("32d2"),  # xor dl, dl      ; the accept path
    AI_PRODUCER_NEXT_CANDIDATE: bytes.fromhex("ff7508"),  # push [ebp+8]    ; next candidate
    OBJECT_TEST_STATUS: bytes.fromhex("8b542404"),  # mov edx, [esp+4] ; testStatus(bit)
    AI_PRODUCER_PICKER_CALL: AI_PRODUCER_PICKER_CALL_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The rewritten arm-select branch. Reached only from the hook, and never returns to it."""
    a = Asm(base_va)
    # Which question is this? Zero means "pick a producer to use now"; anything else means
    # "could this ever be made here", which three callers ask and one of them cancels orders on.
    a.emit(0x80, 0x7D, 0x10, 0x00)  # cmp byte [ebp+0x10], 0
    a.jcc(JE, "pick_one_to_use")
    a.jmp_absolute(AI_PRODUCER_ACCEPT)  # the hypothetical arm, byte-for-byte stock

    a.label("pick_one_to_use")
    # `edi` is the candidate `Object` (from `findObjectByID` at 0x009A0761) and is live here.
    # `testStatus` is `__thiscall`, one stack argument, `ret 4`; it preserves `esi`/`edi`/`ebx`
    # and clobbers `eax`/`ecx`/`edx`, none of which is live across the resume point - the stock
    # code at `AI_PRODUCER_USABLE_TESTS` reloads `eax` and `ecx` itself and reads only `esi`.
    a.emit(0x6A, OBJECT_STATUS_UNDER_CONSTRUCTION)  # push 2
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_TEST_STATUS)  # Object::testStatus
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "finished")
    a.jmp_absolute(AI_PRODUCER_NEXT_CANDIDATE)  # still going up: not this one

    a.label("finished")
    a.jmp_absolute(AI_PRODUCER_USABLE_TESTS)  # the engine's own disabled + idle tests
    return a.finish()


class AiConstructionGatePatch(Patch):
    name = "ai-construction-gate"
    author = "officialNecro"
    description = "Stop the skirmish AI producing from a building that is still under construction"

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        # Prove the function being edited is the one the AI's order pump reaches, and that the
        # points the cave jumps back into still hold the instructions they are chosen for.
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "SkirmishAI producer picker arm-select -> ai-construction-gate cave",
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
                    "producer picker's layout is not this build's, so the cave would jump into "
                    "the wrong place or test the wrong object"
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
