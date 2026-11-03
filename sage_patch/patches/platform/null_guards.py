"""Null tests the engine leaves out, each at a site a crash dump proved is reached.

Every guard is a hook into one shared cave. A guard tests a pointer the stock code dereferences
blindly and, when it is NULL, leaves through the function's own failure or "no" answer, so the
caller sees an outcome it already handles. On a non-NULL pointer each guard runs the displaced
stock instructions verbatim.

- **transfer**: `ToggleMountedSpecialAbilityUpdate` carries a unit's pending AI order across a
  `MountedTemplate` swap. When that order names an object that is gone, the stored target is NULL
  and the transfer check reads through it. The guard answers "not worth transferring". The
  skirmish AI hits this when a hero picks up the One Ring and then transforms.
- **enter**: `AIMoveToPositionAndEnterState::onEnter`, the state behind every Enter order, reads
  the target's contain to find its door with no test of the target or its contain. The guard
  fails the state, as `AIEnterState::onEnter` does when it refuses. Seen in a replay whose recorded
  Enter order named an object with no contain.

Derivation: `../docs/null-guards.md`.
"""

from __future__ import annotations

import struct

from ...addresses import (
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
    AI_ENTER_ON_ENTER_FAILURE,
    AI_ENTER_ON_ENTER_FAILURE_BYTES,
    AI_MOVE_AND_ENTER_CONTAIN_LOAD,
    AI_MOVE_AND_ENTER_CONTAIN_LOAD_BYTES,
    AI_MOVE_AND_ENTER_EDI_POP,
    AI_MOVE_AND_ENTER_EDI_POP_BYTES,
    AI_MOVE_AND_ENTER_EDI_PUSH,
    AI_MOVE_AND_ENTER_EDI_PUSH_BYTES,
    AI_MOVE_AND_ENTER_GOAL_CALL,
    AI_MOVE_AND_ENTER_GOAL_CALL_BYTES,
    AI_MOVE_AND_ENTER_ON_ENTER,
    AI_MOVE_AND_ENTER_ON_ENTER_ENTRY,
    AI_MOVE_AND_ENTER_ON_ENTER_SLOT,
    AI_MOVE_AND_ENTER_ON_ENTER_SLOT_BYTES,
    AI_MOVE_AND_ENTER_RESUME,
    AI_MOVE_AND_ENTER_RESUME_BYTES,
    AI_MOVE_AND_ENTER_TAIL,
    AI_MOVE_AND_ENTER_TAIL_BYTES,
    AI_STATE_FAILURE,
)
from ...asm import JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "ENTER_HOOK_ORIGINAL",
    "ENTER_HOOK_VA",
    "NOT_WORTH_TRANSFERRING",
    "NullGuardsPatch",
    "SECTION_NAME",
    "TRANSFER_CALL_TARGETS",
    "TRANSFER_HOOK_ORIGINAL",
    "TRANSFER_HOOK_VA",
    "build_code",
    "hooks",
]

SECTION_NAME = ".nullgd"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: The answer the transfer guard gives for a target that no longer exists, in the encoding the
#: callers read: `test al, al` / `jne` past the re-issue, so non-zero is "leave this order behind".
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

TRANSFER_HOOK_VA = AI_COMMAND_TRANSFER_TARGET_USE
TRANSFER_HOOK_ORIGINAL = AI_COMMAND_TRANSFER_TARGET_USE_BYTES

ENTER_HOOK_VA = AI_MOVE_AND_ENTER_CONTAIN_LOAD
ENTER_HOOK_ORIGINAL = AI_MOVE_AND_ENTER_CONTAIN_LOAD_BYTES
# The window holds two instructions: the contain load, then the store of the goal object.
_ENTER_LOAD = ENTER_HOOK_ORIGINAL[:6]  # mov ecx, [eax+0x258]
_ENTER_STORE = ENTER_HOOK_ORIGINAL[6:]  # mov [ebp-0xc], eax

#: The first instruction at each address a guard depends on, as a `{va: bytes}` map. The hooked
#: windows are asserted by `apply_byte_patch`; these are the jump targets, the loads and pushes
#: that fix what each register and stack slot holds at the hook, and the call sites and vtable slot
#: that prove each edited function is the one the crash reached. A build whose layout moved fails
#: here instead of on a wild jump or a guard that tests the wrong thing.
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
    AI_MOVE_AND_ENTER_ON_ENTER_SLOT: AI_MOVE_AND_ENTER_ON_ENTER_SLOT_BYTES,
    AI_MOVE_AND_ENTER_ON_ENTER: AI_MOVE_AND_ENTER_ON_ENTER_ENTRY,
    AI_MOVE_AND_ENTER_EDI_PUSH: AI_MOVE_AND_ENTER_EDI_PUSH_BYTES,
    AI_MOVE_AND_ENTER_GOAL_CALL: AI_MOVE_AND_ENTER_GOAL_CALL_BYTES,
    AI_MOVE_AND_ENTER_RESUME: AI_MOVE_AND_ENTER_RESUME_BYTES,
    AI_MOVE_AND_ENTER_EDI_POP: AI_MOVE_AND_ENTER_EDI_POP_BYTES,
    AI_MOVE_AND_ENTER_TAIL: AI_MOVE_AND_ENTER_TAIL_BYTES,
    AI_ENTER_ON_ENTER_FAILURE: AI_ENTER_ON_ENTER_FAILURE_BYTES,
}


def _emit_transfer(a: Asm) -> None:
    a.label("transfer")
    # `eax` is `AICommandParms::m_obj`, loaded by the instruction before the window and NULL
    # exactly when the stored `ObjectID` no longer names a live object.
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "transfer.no_target")
    a.emit(TRANSFER_HOOK_ORIGINAL)  # subss xmm0, dword [eax+0x38]
    a.jmp_absolute(AI_COMMAND_TRANSFER_RESUME)

    a.label("transfer.no_target")
    # Written rather than inherited from the seed, so the answer does not depend on no arm on the
    # way here having touched `ebx`.
    a.emit(0xB3, NOT_WORTH_TRANSFERRING)  # mov bl, 1
    # The function's own tail: SEH restore, the waypoint vector's free, then `mov al, bl`.
    a.jmp_absolute(AI_COMMAND_TRANSFER_ANSWER)


def _emit_enter(a: Asm) -> None:
    a.label("enter")
    # `eax` is the state's goal object, straight out of the call before the window.
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "enter.fail")
    a.emit(_ENTER_LOAD)  # mov ecx, [eax+0x258]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "enter.fail")
    a.emit(_ENTER_STORE)  # mov [ebp-0xc], eax
    a.jmp_absolute(AI_MOVE_AND_ENTER_RESUME)

    a.label("enter.fail")
    # `[esp]` is the `edi` pushed just before the goal call; the stock path pops it before the
    # tail, so this path has to as well. The tail then answers `esi` and pops the rest.
    a.emit(0x5F)  # pop edi
    a.emit(0x6A, AI_STATE_FAILURE & 0xFF)  # push -2
    a.emit(0x5E)  # pop esi
    a.jmp_absolute(AI_MOVE_AND_ENTER_TAIL)


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)
    _emit_transfer(a)
    _emit_enter(a)
    return a


def build_code(base_va: int) -> bytes:
    """The cave: one guard per hooked site, each left only by its own jumps."""
    return _assemble(base_va).finish()


def hooks(cave_va: int) -> dict[int, tuple[bytes, bytes]]:
    """Every site this patch rewrites, as `{va: (stock bytes, patched bytes)}`: a `jmp rel32` to
    the site's guard, padded with `nop` to the width of the window."""
    a = _assemble(cave_va)
    edits: dict[int, tuple[bytes, bytes]] = {}
    for va, stock, label in (
        (TRANSFER_HOOK_VA, TRANSFER_HOOK_ORIGINAL, "transfer"),
        (ENTER_HOOK_VA, ENTER_HOOK_ORIGINAL, "enter"),
    ):
        jump = b"\xe9" + struct.pack("<i", a.label_va(label) - (va + 5))
        edits[va] = (stock, jump + b"\x90" * (len(stock) - len(jump)))
    return edits


class NullGuardsPatch(Patch):
    name = "null-guards"
    author = "officialNecro"
    description = (
        "Add null tests the engine leaves out, at sites crash dumps showed are reached: a "
        "MountedTemplate transform whose pending AI order names a removed object (a hero who "
        "walked to the One Ring, then transforms) drops the order, and an Enter order on an "
        "object that is gone or has no contain fails instead of crashing. Logic-side: every "
        "peer needs the same binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        for va, (stock, patched) in hooks(cave_va).items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            apply_byte_patch(data, off, stock, patched, f"null-guards @0x{va:08x}")

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the guarded "
                    "function's layout is not this build's, so a guard would test the wrong "
                    "register or jump into the wrong place"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        cave_va, cave_off, _vsize = located
        problems: list[str] = []
        code = build_code(cave_va)
        if bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected guards")
        for va, (_stock, patched) in hooks(cave_va).items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} is not mapped by any section")
                continue
            got = bytes(data[off : off + len(patched)])
            if got != patched:
                problems.append(f"@0x{va:08x}: not hooked into {SECTION_NAME} (holds {got.hex()})")
        return problems
