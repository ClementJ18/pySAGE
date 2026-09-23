"""Stop the skirmish AI casting its rebuild spell on a building that is still going up.

The `AI_SPELLBOOK_REBUILD` target picker (`AI_REBUILD_PICKER`) takes the first structure below half
health, which scaffolding always is. A cave makes the picker skip structures under construction and
keep looking.

Derivation: `../docs/ai-rebuild-gate.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_REBUILD_BEHAVIOR_CTOR,
    AI_REBUILD_BEHAVIOR_CTOR_BYTES,
    AI_REBUILD_BEHAVIOR_VTABLE,
    AI_REBUILD_BODY_FETCH,
    AI_REBUILD_BODY_FETCH_BYTES,
    AI_REBUILD_FACTORY_CASE,
    AI_REBUILD_FACTORY_CASE_CALL,
    AI_REBUILD_FACTORY_CASE_CALL_BYTES,
    AI_REBUILD_HEALTH_TEST,
    AI_REBUILD_HEALTH_TEST_BYTES,
    AI_REBUILD_NEXT_CANDIDATE,
    AI_REBUILD_NEXT_CANDIDATE_BYTES,
    AI_REBUILD_PICKER,
    AI_REBUILD_PICKER_ENTRY,
    AI_REBUILD_PICKER_VTABLE_SLOT,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    OBJECT_TEST_STATUS,
    SPELLBOOK_AI_REBUILD,
    SPELLBOOK_AI_REBUILD_NAME,
    SPELLBOOK_AI_TYPE_JUMP_TABLE,
    SPELLBOOK_AI_TYPE_NAMES,
)
from ..asm import JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "AiRebuildGatePatch",
    "BEHAVIOR_CTOR_TARGET",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "PICKER_VTABLE_SLOT_VA",
    "REBUILD_CASE_SLOT",
    "REBUILD_NAME_SLOT",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".airbld"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = AI_REBUILD_BODY_FETCH
HOOK_ORIGINAL = AI_REBUILD_BODY_FETCH_BYTES

#: The name-table slot `SPELLBOOK_AI_REBUILD` indexes, and the jump-table slot the factory
#: dispatches that same index through. Both are computed from the index rather than written down,
#: so "the function being hooked is the one `AI_SPELLBOOK_REBUILD` reaches" is a *derived* fact an
#: anchor can enforce instead of a comment nobody rechecks.
REBUILD_NAME_SLOT = SPELLBOOK_AI_TYPE_NAMES + 4 * SPELLBOOK_AI_REBUILD
REBUILD_CASE_SLOT = SPELLBOOK_AI_TYPE_JUMP_TABLE + 4 * SPELLBOOK_AI_REBUILD

#: Where the vtable the behaviour's constructor stamps keeps its picker.
PICKER_VTABLE_SLOT_VA = AI_REBUILD_BEHAVIOR_VTABLE + AI_REBUILD_PICKER_VTABLE_SLOT

#: Where `AI_REBUILD_FACTORY_CASE_CALL` actually goes, decoded from its own bytes. Asserting the
#: call's five bytes - which `ANCHORS` does - therefore also asserts the constructor it reaches.
BEHAVIOR_CTOR_TARGET = (
    AI_REBUILD_FACTORY_CASE_CALL
    + 5
    + struct.unpack("<i", AI_REBUILD_FACTORY_CASE_CALL_BYTES[1:5])[0]
)

#: Every link of the chain from the keyword to the hooked function, as a `{va: bytes}` map, plus
#: the two points the cave jumps to and the helper it calls. The hook's own bytes are asserted by
#: `apply_byte_patch`. A build whose layout moved fails here rather than on a wild jump or a
#: gate aimed at the wrong picker.
ANCHORS = {
    SPELLBOOK_AI_REBUILD_NAME: b"AI_SPELLBOOK_REBUILD\x00",  # the keyword's spelling
    REBUILD_NAME_SLOT: struct.pack("<I", SPELLBOOK_AI_REBUILD_NAME),  # parses to this index
    REBUILD_CASE_SLOT: struct.pack("<I", AI_REBUILD_FACTORY_CASE),  # which dispatches to the case
    AI_REBUILD_FACTORY_CASE_CALL: AI_REBUILD_FACTORY_CASE_CALL_BYTES,  # which calls the ctor
    AI_REBUILD_BEHAVIOR_CTOR: AI_REBUILD_BEHAVIOR_CTOR_BYTES,  # which stamps the vtable
    PICKER_VTABLE_SLOT_VA: struct.pack("<I", AI_REBUILD_PICKER),  # whose slot 7 is the picker
    AI_REBUILD_PICKER: AI_REBUILD_PICKER_ENTRY,  # push ebx; push ebp; push esi; mov ebp,ecx
    AI_REBUILD_HEALTH_TEST: AI_REBUILD_HEALTH_TEST_BYTES,  # the resume, through the 0.5 compare
    AI_REBUILD_NEXT_CANDIDATE: AI_REBUILD_NEXT_CANDIDATE_BYTES,  # add esi,4; cmp; jne
    OBJECT_TEST_STATUS: bytes.fromhex("8b542404"),  # mov edx, [esp+4] ; testStatus(bit)
}


def build_code(base_va: int) -> bytes:
    """The gate. Reached only from the hook, and never returns to it."""
    a = Asm(base_va)
    # `ebx` is the candidate `Object` `findObjectByID` returned two instructions above the hook,
    # and is the register the displaced instruction indexes. `testStatus` is `__thiscall`, one
    # stack argument, `ret 4`; its body pushes and pops `esi` and otherwise touches only `eax`,
    # `ecx` and `edx`, so `ebx`/`esi`/`edi`/`ebp` all survive and `ecx` is reloaded below. The
    # x87 stack is untouched, which matters: the resume point loads the body vtable for a call
    # that returns its answer on `st(0)`.
    a.emit(0x6A, OBJECT_STATUS_UNDER_CONSTRUCTION)  # push 2
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(OBJECT_TEST_STATUS)  # Object::testStatus
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "still_going_up")

    a.emit(HOOK_ORIGINAL)  # mov ecx, [ebx+0x25c]  - the displaced instruction
    a.jmp_absolute(AI_REBUILD_HEALTH_TEST)  # on to the engine's own health test

    a.label("still_going_up")
    a.jmp_absolute(AI_REBUILD_NEXT_CANDIDATE)  # skip it; the loop keeps looking
    return a.finish()


class AiRebuildGatePatch(Patch):
    name = "ai-rebuild-gate"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Stop the skirmish AI aiming an AI_SPELLBOOK_REBUILD power at a structure that is still "
        "under construction. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        # Prove the picker being edited is the one `AI_SPELLBOOK_REBUILD` reaches, and that the
        # points the cave jumps to still hold the instructions they are chosen for.
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "AI_SPELLBOOK_REBUILD target picker body fetch -> ai-rebuild-gate cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the "
                    "AI_SPELLBOOK_REBUILD target picker's layout is not this build's, so the "
                    "gate would sit in the wrong picker or jump into the wrong place"
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
            problems.append(f"the {SECTION_NAME} cave does not hold the expected gate")
        return problems
