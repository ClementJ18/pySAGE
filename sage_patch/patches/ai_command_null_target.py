"""The AI command null-target patch: stop a hero transform crashing on an order whose target
has been removed.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/ai-command-null-target.md``.

**The defect.** When `ToggleMountedSpecialAbilityUpdate` swaps an object for its
`MountedTemplate` (``0x008B140D``), the tail of the swap carries the old object's pending AI
order onto the new one. It fetches that order with ``0x0066D7C9``, which reconstitutes it out of
`AICommandParmsStorage` - and `reconstitute` (``0x0075315B``) turns the stored `ObjectID` back
into a pointer through `GameLogic::findObjectByID`, storing the result **unchecked**::

    00753179  push dword [ebx+0x14]      ; the stored ObjectID
    00753182  call 0x00449681            ; findObjectByID -> NULL if the object is gone
    00753187  mov  [ebp+0x14], eax       ; AICommandParms::m_obj, no null test

The swap then asks `AI_COMMAND_TRANSFER_CHECK` whether the order is still worth re-issuing. For
the arms that name an object - command types 1 (`AICMD_MOVE_TO_OBJECT`), 0x48 and 0x49 - that
question is answered by measuring the distance to the target, and the target is read with no
guard either::

    0066c3fb  mov   eax, [ecx+8]              ; the owning Object
    0066c3fe  movss xmm0, [eax+0x38]          ; its position
    0066c40d  mov   eax, [ebp+0x1c]           ; AICommandParms::m_obj  -> NULL
    0066c410  subss xmm0, [eax+0x38]          ; *** EXCEPTION_ACCESS_VIOLATION reading 0x38

**How it is reached in practice.** `PickupStuffUpdate` orders the skirmish AI's heroes to walk to
the One Ring with `aiMoveToObject(ring, CMD_FROM_AI)` - command type 1, stored at `AIUpdate+0x3E4`.
The hero arrives, the Ring object is destroyed by the pickup, and the module's "am I there yet"
branch (``0x00895572``) clears only its own flag: it issues no replacement order, so the stored
one keeps naming a dead id. Becoming a Ring hero then fires the toggle, and the swap trips over
it. In the Edain tree 120 templates carry both halves - every Ring-capable hero and every mounted
horde - so this is not a data mistake that can be edited out.

**What this does.** Appends an ``.ainull`` PE section holding a null guard, and redirects the five
bytes of the faulting instruction into it. A non-null target runs the instruction that was
displaced and returns; a null one sets the answer to "not worth transferring" and jumps into the
function's own tail, which restores the SEH state, frees the parms' waypoint vector and returns
`bl` in `al`.

**Why "not worth transferring" is the right answer.** The call sites read it as
``test al, al`` / ``jne`` **past** the re-issue, so a non-zero answer means *do not hand this
order to the replacement*. That is what a move-to-object with no object should mean - and the
alternative is worse than the crash it replaces: answering zero re-issues the same NULL-carrying
`AICommandParms` on the new object's state machine, moving the fault rather than removing it.

**The guard sets `bl` rather than trusting it.** `bl` is seeded to 1 at
`AI_COMMAND_TRANSFER_BOOL_INIT` and no arm on the path to the hook clears it, so jumping straight
to the tail would already answer 1. Writing it anyway costs two bytes and makes the cave's answer
independent of a fact about the path, which is the kind of fact a future edit breaks silently.

**Flags.** ``test eax, eax`` clobbers EFLAGS. Nothing downstream reads them: the resume point runs
two `subss` and a `jmp`, and the first flag consumer after it is the ``ja`` at ``0x0066C46C``,
whose flags come from the ``fcompi`` two instructions earlier. The tail edge reaches
``or dword [ebp-4], -1``, which sets flags before anything tests them.

**Determinism.** The guard reads a pointer the logic already computed and changes only whether an
order is re-issued - logic state, identical on every peer, evaluated inside a swap that every
peer runs on the same frame. Nothing here is client-local, and nothing depends on timing.

**Blast radius.** `AI_COMMAND_TRANSFER_CHECK` has exactly two callers, both inside
`ToggleMountedSpecialAbilityUpdate`, so the changed edge is reachable only from a mount/dismount
swap. On a non-null target the patched path executes the same instruction stream as stock.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the five at
`AI_COMMAND_TRANSFER_TARGET_USE`, which no other bundled patch touches.
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
