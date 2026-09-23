"""Stop a hero's mount transform crashing on an AI order whose target has been removed.

When `ToggleMountedSpecialAbilityUpdate` swaps an object for its `MountedTemplate`, it carries the
pending AI order across (fetched through `0x0066D7C9`). If that order names an object that is gone,
the stored target is NULL and the transfer check reads through it. A cave adds the missing null test
and answers "not worth transferring". The skirmish AI hits this when a hero picks up the One Ring
and then transforms.

Derivation: `../docs/ai-command-null-target.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_COMMAND_TRANSFER_ANSWER,
    AI_COMMAND_TRANSFER_ANSWER_BYTES,
    AI_COMMAND_TRANSFER_ANSWER_READ,
    AI_COMMAND_TRANSFER_ANSWER_READ_BYTES,
    AI_COMMAND_TRANSFER_BOOL_INIT,
    AI_COMMAND_TRANSFER_BOOL_INIT_BYTES,
    AI_COMMAND_TRANSFER_CHECK,
    AI_COMMAND_TRANSFER_CHECK_ENTRY,
    AI_COMMAND_TRANSFER_DISMOUNT_CALL,
    AI_COMMAND_TRANSFER_DISMOUNT_CALL_BYTES,
    AI_COMMAND_TRANSFER_MOUNT_CALL,
    AI_COMMAND_TRANSFER_MOUNT_CALL_BYTES,
    AI_COMMAND_TRANSFER_OBJECT_ARM,
    AI_COMMAND_TRANSFER_OBJECT_ARM_BYTES,
    AI_COMMAND_TRANSFER_RESUME,
    AI_COMMAND_TRANSFER_RESUME_BYTES,
    AI_COMMAND_TRANSFER_TARGET_LOAD,
    AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES,
    AI_COMMAND_TRANSFER_TARGET_USE,
    AI_COMMAND_TRANSFER_TARGET_USE_BYTES,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "AiCommandNullTargetPatch",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "NOT_WORTH_TRANSFERRING",
    "SECTION_NAME",
    "TRANSFER_CALL_TARGETS",
    "build_code",
]

SECTION_NAME = ".ainull"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: The answer the guard gives for a target that no longer exists, in the encoding the callers
#: read: `test al, al` / `jne` past the re-issue, so non-zero is "leave this order behind".
NOT_WORTH_TRANSFERRING = 1

#: Where the two calls to the transfer check actually go, decoded from their own bytes rather
#: than written down, so "the function this patch edits is the one the mount swap reaches" is a
#: *derived* fact an anchor enforces rather than a comment nobody rechecks.
TRANSFER_CALL_TARGETS = tuple(
    va + 5 + struct.unpack("<i", raw[1:5])[0]
    for va, raw in (
        (AI_COMMAND_TRANSFER_MOUNT_CALL, AI_COMMAND_TRANSFER_MOUNT_CALL_BYTES),
        (AI_COMMAND_TRANSFER_DISMOUNT_CALL, AI_COMMAND_TRANSFER_DISMOUNT_CALL_BYTES),
    )
)

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = AI_COMMAND_TRANSFER_TARGET_USE
HOOK_ORIGINAL = AI_COMMAND_TRANSFER_TARGET_USE_BYTES

#: The first instruction at each address the guard depends on, as a `{va: bytes}` map. The hooked
#: bytes are asserted by `apply_byte_patch`; these are the two jump targets, the load that fixes
#: which frame slot holds the target, the arm that load belongs to, the seed and the read of the
#: answer register, and both call sites. A build whose layout moved fails here instead of on a
#: wild jump or a guard that tests the wrong thing.
ANCHORS = {
    AI_COMMAND_TRANSFER_CHECK: AI_COMMAND_TRANSFER_CHECK_ENTRY,
    AI_COMMAND_TRANSFER_BOOL_INIT: AI_COMMAND_TRANSFER_BOOL_INIT_BYTES,
    AI_COMMAND_TRANSFER_OBJECT_ARM: AI_COMMAND_TRANSFER_OBJECT_ARM_BYTES,
    AI_COMMAND_TRANSFER_TARGET_LOAD: AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES,
    AI_COMMAND_TRANSFER_RESUME: AI_COMMAND_TRANSFER_RESUME_BYTES,
    AI_COMMAND_TRANSFER_ANSWER: AI_COMMAND_TRANSFER_ANSWER_BYTES,
    AI_COMMAND_TRANSFER_ANSWER_READ: AI_COMMAND_TRANSFER_ANSWER_READ_BYTES,
    AI_COMMAND_TRANSFER_MOUNT_CALL: AI_COMMAND_TRANSFER_MOUNT_CALL_BYTES,
    AI_COMMAND_TRANSFER_DISMOUNT_CALL: AI_COMMAND_TRANSFER_DISMOUNT_CALL_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The null guard. Reached only from the hook, and leaves by one of two jumps."""
    a = Asm(base_va)
    # `eax` is `AICommandParms::m_obj`, loaded five instructions earlier at
    # `AI_COMMAND_TRANSFER_TARGET_LOAD` and NULL exactly when the stored `ObjectID` no longer
    # names a live object.
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "no_target")

    # The displaced instruction, verbatim, then straight back - so a live target runs the stock
    # instruction stream with nothing added but the test.
    a.emit(HOOK_ORIGINAL)  # subss xmm0, dword [eax+0x38]
    a.jmp_absolute(AI_COMMAND_TRANSFER_RESUME)

    a.label("no_target")
    # The answer register the tail reads back out with `mov al, bl`. Written rather than
    # inherited: see the module docstring.
    a.emit(0xB3, NOT_WORTH_TRANSFERRING)  # mov bl, 1
    a.jmp_absolute(AI_COMMAND_TRANSFER_ANSWER)
    return a.finish()


class AiCommandNullTargetPatch(Patch):
    name = "ai-command-null-target"
    author = "officialNecro"
    description = (
        "Stop a MountedTemplate transform crashing when the unit's pending AI order names an "
        "object that has since been removed (a hero who walked to the One Ring, then transforms). "
        "No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "AI command transfer target read -> ai-command-null-target cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the AI command "
                    "transfer check's layout is not this build's, so the guard would test the "
                    "wrong register or jump into the wrong place"
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
            problems.append(f"the {SECTION_NAME} cave does not hold the expected guard")
        return problems
