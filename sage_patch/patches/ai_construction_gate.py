"""Stop the skirmish AI producing from a building that is still under construction.

The engine enforces this rule in the control bar, the legacy `AIPlayer::findFactory` and
`ProductionUpdate`, but not in the `SkirmishAI` producer picker (`AI_PRODUCER_PICKER`) RotWK
skirmish actually uses. A cave adds the `UNDER_CONSTRUCTION` test to the picker's "use it now" arm.
AI-only for free: every caller of the picker is AI.

Derivation: `../docs/ai-construction-gate.md`.
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
    runtime_verified = "yes"
    description = (
        "Stop the skirmish AI producing from a building that is still under construction. No "
        "INI change"
    )

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
