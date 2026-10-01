"""Make an `AISpecialPowerUpdate` hook respect its button's `EnableOnModelCondition` and
`DisableOnModelCondition`.

A player can press a special-power button only while the control bar's model-condition test
(`COMMAND_BUTTON_CONDITION_GATE`) passes. The AI hook never asks it: once the power is ready it
flips its coin, runs its picker and casts. A cave on the ready edge of
`AISpecialPowerUpdate::update` calls the same test for the hook's own button on its own object,
and leaves by the tick's stock "did not cast" exit when it answers disabled. Every peer needs the
same binary.

Derivation: `../../docs/ai-power-model-condition.md`.
"""

from __future__ import annotations

import struct

from ...addresses import (
    AI_POWER_NOT_CAST,
    AI_POWER_NOT_CAST_BYTES,
    AI_POWER_READY_WINDOW,
    AI_POWER_READY_WINDOW_BYTES,
    AI_POWER_TICK,
    AI_POWER_TICK_ENTRY,
    AI_POWER_TICK_HOOK,
    AI_POWER_TICK_HOOK_BYTES,
    AI_POWER_TICK_RESUME,
    AI_POWER_UPDATE_BUTTON_OFFSET,
    AI_POWER_UPDATE_CTOR_VTABLE_WRITE,
    AI_POWER_UPDATE_CTOR_VTABLE_WRITE_BYTES,
    AI_POWER_UPDATE_TICK_VTABLE,
    COMMAND_BUTTON_CONDITION_DISABLED,
    COMMAND_BUTTON_CONDITION_GATE,
    COMMAND_BUTTON_CONDITION_GATE_BODY,
)
from ...asm import JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "AiPowerModelConditionPatch",
    "build_code",
]

SECTION_NAME = ".aipmc"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = AI_POWER_TICK_HOOK
HOOK_ORIGINAL = AI_POWER_TICK_HOOK_BYTES

#: Inside the tick `esi` is the module's `UpdateModuleInterface`: the owning `Object *` sits at
#: `esi-8` and the type behaviour at `esi+0x14`.
_OBJECT_DISP = 0xF8  # [esi-8] as a signed disp8
_BEHAVIOUR_DISP = 0x14

#: Where the hook falls inside the ready window. The window is anchored in two halves around it,
#: so the anchors describe the stock image both before and after the hook is written.
_HOOK_AT = HOOK_VA - AI_POWER_READY_WINDOW

#: The chain from the module to the hook site, and the function the cave calls, as `{va: bytes}`.
#: The hook's own bytes are asserted by `apply_byte_patch`. The constructor's vtable write and the
#: vtable's slot 0 prove the hooked function is `AISpecialPowerUpdate::update`; the ready window
#: pins the ready test the hook follows and, through its `call` rel32, the cast step it gates; the
#: gate's whole body is asserted because the cave relies on what it clobbers.
ANCHORS = {
    AI_POWER_UPDATE_CTOR_VTABLE_WRITE: AI_POWER_UPDATE_CTOR_VTABLE_WRITE_BYTES,
    AI_POWER_UPDATE_TICK_VTABLE: struct.pack("<I", AI_POWER_TICK),
    AI_POWER_TICK: AI_POWER_TICK_ENTRY,
    AI_POWER_READY_WINDOW: AI_POWER_READY_WINDOW_BYTES[:_HOOK_AT],
    AI_POWER_TICK_RESUME: AI_POWER_READY_WINDOW_BYTES[_HOOK_AT + len(HOOK_ORIGINAL) :],
    AI_POWER_NOT_CAST: AI_POWER_NOT_CAST_BYTES,
    COMMAND_BUTTON_CONDITION_GATE: COMMAND_BUTTON_CONDITION_GATE_BODY,
}


def build_code(base_va: int) -> bytes:
    """The gate. Reached only from the hook, and never returns to it."""
    a = Asm(base_va)
    # stdcall(button, object): push the object, then the button. The gate preserves `ebx`, `esi`
    # and `edi`, and writes `eax`, `ecx`, `edx`: the displaced instructions set `ecx` (its low byte,
    # as the stock code does) and `eax`, and nothing on either exit reads `edx` before writing it.
    a.emit(0xFF, 0x76, _OBJECT_DISP)  # push dword [esi-8]           ; the Object
    a.emit(0x8B, 0x46, _BEHAVIOUR_DISP)  # mov eax, [esi+0x14]          ; the type behaviour
    a.emit(0xFF, 0x70, AI_POWER_UPDATE_BUTTON_OFFSET)  # push dword [eax+0xc]  ; its button
    a.call_absolute(COMMAND_BUTTON_CONDITION_GATE)
    a.emit(0x83, 0xF8, COMMAND_BUTTON_CONDITION_DISABLED)  # cmp eax, 3
    a.jcc(JE, "disabled")

    a.emit(HOOK_ORIGINAL)  # mov cl, [edi+0x19] / mov eax, [esi-8]
    a.jmp_absolute(AI_POWER_TICK_RESUME)

    a.label("disabled")
    a.jmp_absolute(AI_POWER_NOT_CAST)  # the stock exit for a power that is not ready
    return a.finish()


class AiPowerModelConditionPatch(Patch):
    name = "ai-power-model-condition"
    author = "officialNecro"
    experimental = True
    description = (
        "Stop an AISpecialPowerUpdate hook casting while its button's EnableOnModelCondition / "
        "DisableOnModelCondition would grey it out for a player. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "AISpecialPowerUpdate ready edge -> ai-power-model-condition cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - "
                    "AISpecialPowerUpdate's layout is not this build's, so the gate would sit in "
                    "the wrong function or jump into the wrong place"
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
