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
- **hero**: a Create-a-Hero saved under another mod can name a class or subclass this mod does not
  have. The `.cah` loader keeps it, and the skirmish lobby then reads the hero's allowed factions
  through a NULL subclass. The guard answers "not loaded" at the loader instead, the answer it
  already gives a hero whose checksum fails, so the hero is left out of every list.
- **path**: `AIUpdateInterface::doLocomotor`, following a path, moves the unit and then reloads
  its path to update its progress along it with no test, though the move can have dropped the
  path. The guard skips the update, whose answer nothing reads. Seen in a skirmish dump: a unit
  whose transform had gone NaN, following a path tied to a map waypoint.

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
    AI_UPDATE_DO_LOCOMOTOR,
    AI_UPDATE_DO_LOCOMOTOR_ENTRY,
    AI_UPDATE_DO_LOCOMOTOR_PATH_CALL,
    AI_UPDATE_DO_LOCOMOTOR_PATH_CALL_BYTES,
    AI_UPDATE_DO_LOCOMOTOR_PATH_DONE,
    AI_UPDATE_DO_LOCOMOTOR_PATH_DONE_BYTES,
    AI_UPDATE_DO_LOCOMOTOR_PATH_LOAD,
    AI_UPDATE_DO_LOCOMOTOR_PATH_LOAD_BYTES,
    AI_UPDATE_DO_LOCOMOTOR_SLOT,
    AI_UPDATE_DO_LOCOMOTOR_SLOT_BYTES,
    CREATE_A_HERO_CHECKSUM_STORE,
    CREATE_A_HERO_CHECKSUM_STORE_BYTES,
    CREATE_A_HERO_CLASS_LOOKUP,
    CREATE_A_HERO_CLASS_LOOKUP_BYTES,
    CREATE_A_HERO_CLASS_SIZE,
    CREATE_A_HERO_CLASS_SUBCLASSES,
    CREATE_A_HERO_DAT_LOAD_CALL,
    CREATE_A_HERO_DAT_LOAD_CALL_BYTES,
    CREATE_A_HERO_HERO_CLASS,
    CREATE_A_HERO_HERO_SUBCLASS,
    CREATE_A_HERO_LIST_LOAD_CALL,
    CREATE_A_HERO_LIST_LOAD_CALL_BYTES,
    CREATE_A_HERO_LOAD,
    CREATE_A_HERO_LOAD_ENTRY,
    CREATE_A_HERO_LOAD_RESUME,
    CREATE_A_HERO_LOAD_RESUME_BYTES,
    CREATE_A_HERO_LOAD_THIS,
    CREATE_A_HERO_LOAD_THIS_BYTES,
    CREATE_A_HERO_LOAD_VERDICT,
    CREATE_A_HERO_LOAD_VERDICT_BYTES,
    CREATE_A_HERO_LOBBY_INDEX_READ,
    CREATE_A_HERO_LOBBY_INDEX_READ_BYTES,
    CREATE_A_HERO_MANAGER_CLASSES,
    CREATE_A_HERO_REFRESH_POWER_COST,
    CREATE_A_HERO_REFRESH_POWER_COST_ENTRY,
    CREATE_A_HERO_SUBCLASS_FLAGS_ADD,
    CREATE_A_HERO_SUBCLASS_FLAGS_ADD_BYTES,
    CREATE_A_HERO_SUBCLASS_LOOKUP,
    CREATE_A_HERO_SUBCLASS_LOOKUP_BYTES,
    CREATE_A_HERO_SUBCLASS_SIZE,
    PATH_UPDATE_PROGRESS,
    PATH_UPDATE_PROGRESS_ENTRY,
    THE_CREATE_A_HERO_MANAGER,
)
from ...asm import JAE, JB, JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "ENTER_HOOK_ORIGINAL",
    "ENTER_HOOK_VA",
    "HERO_CALL_TARGETS",
    "HERO_HOOK_ORIGINAL",
    "HERO_HOOK_VA",
    "NOT_WORTH_TRANSFERRING",
    "NullGuardsPatch",
    "PATH_CALL_TARGET",
    "PATH_HOOK_ORIGINAL",
    "PATH_HOOK_VA",
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

#: Where the loader's two callers go, decoded the same way: both `.cah` paths reach the hooked
#: loader, so no hero is loaded around the guard.
HERO_CALL_TARGETS = tuple(
    va + 5 + struct.unpack("<i", raw[1:5])[0]
    for va, raw in (
        (CREATE_A_HERO_LIST_LOAD_CALL, CREATE_A_HERO_LIST_LOAD_CALL_BYTES),
        (CREATE_A_HERO_DAT_LOAD_CALL, CREATE_A_HERO_DAT_LOAD_CALL_BYTES),
    )
)

#: Where the call after the path guard's window goes, decoded from its own bytes: the guarded load
#: is the `this` of `PATH_UPDATE_PROGRESS`, whose first read through it is the fault.
PATH_CALL_TARGET = (
    AI_UPDATE_DO_LOCOMOTOR_PATH_CALL
    + 8
    + struct.unpack("<i", AI_UPDATE_DO_LOCOMOTOR_PATH_CALL_BYTES[4:8])[0]
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

HERO_HOOK_VA = CREATE_A_HERO_LOAD_VERDICT
HERO_HOOK_ORIGINAL = CREATE_A_HERO_LOAD_VERDICT_BYTES
# The window holds two instructions: the power-cost refresh, then the checksum verdict into `bl`.
_HERO_REFRESH_CALL_END = HERO_HOOK_VA + 5
_HERO_VERDICT = HERO_HOOK_ORIGINAL[5:]  # mov bl, [edi+0x71]

PATH_HOOK_VA = AI_UPDATE_DO_LOCOMOTOR_PATH_LOAD
PATH_HOOK_ORIGINAL = AI_UPDATE_DO_LOCOMOTOR_PATH_LOAD_BYTES

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
    CREATE_A_HERO_LOAD: CREATE_A_HERO_LOAD_ENTRY,
    CREATE_A_HERO_LOAD_THIS: CREATE_A_HERO_LOAD_THIS_BYTES,
    CREATE_A_HERO_LOAD_RESUME: CREATE_A_HERO_LOAD_RESUME_BYTES,
    CREATE_A_HERO_REFRESH_POWER_COST: CREATE_A_HERO_REFRESH_POWER_COST_ENTRY,
    CREATE_A_HERO_CHECKSUM_STORE: CREATE_A_HERO_CHECKSUM_STORE_BYTES,
    CREATE_A_HERO_LIST_LOAD_CALL: CREATE_A_HERO_LIST_LOAD_CALL_BYTES,
    CREATE_A_HERO_DAT_LOAD_CALL: CREATE_A_HERO_DAT_LOAD_CALL_BYTES,
    CREATE_A_HERO_CLASS_LOOKUP: CREATE_A_HERO_CLASS_LOOKUP_BYTES,
    CREATE_A_HERO_SUBCLASS_LOOKUP: CREATE_A_HERO_SUBCLASS_LOOKUP_BYTES,
    CREATE_A_HERO_SUBCLASS_FLAGS_ADD: CREATE_A_HERO_SUBCLASS_FLAGS_ADD_BYTES,
    CREATE_A_HERO_LOBBY_INDEX_READ: CREATE_A_HERO_LOBBY_INDEX_READ_BYTES,
    AI_UPDATE_DO_LOCOMOTOR_SLOT: AI_UPDATE_DO_LOCOMOTOR_SLOT_BYTES,
    AI_UPDATE_DO_LOCOMOTOR: AI_UPDATE_DO_LOCOMOTOR_ENTRY,
    AI_UPDATE_DO_LOCOMOTOR_PATH_CALL: AI_UPDATE_DO_LOCOMOTOR_PATH_CALL_BYTES,
    AI_UPDATE_DO_LOCOMOTOR_PATH_DONE: AI_UPDATE_DO_LOCOMOTOR_PATH_DONE_BYTES,
    PATH_UPDATE_PROGRESS: PATH_UPDATE_PROGRESS_ENTRY,
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


def _emit_hero(a: Asm) -> None:
    a.label("hero")
    # The displaced window, relocated: the call's target is fixed, only its displacement moves.
    a.call_absolute(_HERO_REFRESH_CALL_END + struct.unpack("<i", HERO_HOOK_ORIGINAL[1:5])[0])
    a.emit(_HERO_VERDICT)  # mov bl, [edi+0x71]
    # `edi` is the hero. `eax`, `ecx` and `edx` are dead from here to the tail.
    a.emit(0xA1, struct.pack("<I", THE_CREATE_A_HERO_MANAGER))  # mov eax, [TheCreateAHeroManager]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "hero.done")
    a.emit(0x8B, 0x88, struct.pack("<I", CREATE_A_HERO_MANAGER_CLASSES))  # mov ecx, [eax+0x154]
    a.emit(0x8B, 0x90, struct.pack("<I", CREATE_A_HERO_MANAGER_CLASSES + 4))  # mov edx, [eax+0x158]
    # No classes parsed yet means nothing to judge against, not that every hero is foreign.
    a.emit(0x2B, 0xD1)  # sub edx, ecx
    a.jcc_short(JE, "hero.done")
    a.emit(0xC1, 0xFA, CREATE_A_HERO_CLASS_SIZE.bit_length() - 1)  # sar edx, 5
    a.emit(0x8B, 0x47, CREATE_A_HERO_HERO_CLASS)  # mov eax, [edi+0xc]
    # Unsigned, so a negative index is as foreign as one past the end.
    a.emit(0x3B, 0xC2)  # cmp eax, edx
    a.jcc_short(JAE, "hero.foreign")
    a.emit(0xC1, 0xE0, CREATE_A_HERO_CLASS_SIZE.bit_length() - 1)  # shl eax, 5
    a.emit(0x03, 0xC8)  # add ecx, eax
    # The subclass count the way the engine's own lookup takes it: byte span over 0xd8.
    a.emit(0x8B, 0x41, CREATE_A_HERO_CLASS_SUBCLASSES + 4)  # mov eax, [ecx+0x18]
    a.emit(0x2B, 0x41, CREATE_A_HERO_CLASS_SUBCLASSES)  # sub eax, [ecx+0x14]
    a.emit(0x33, 0xD2)  # xor edx, edx
    a.emit(0xB9, struct.pack("<I", CREATE_A_HERO_SUBCLASS_SIZE))  # mov ecx, 0xd8
    a.emit(0xF7, 0xF1)  # div ecx
    a.emit(0x39, 0x47, CREATE_A_HERO_HERO_SUBCLASS)  # cmp [edi+0x10], eax
    a.jcc_short(JB, "hero.done")

    a.label("hero.foreign")
    a.emit(0x32, 0xDB)  # xor bl, bl

    a.label("hero.done")
    a.jmp_absolute(CREATE_A_HERO_LOAD_RESUME)


def _emit_path(a: Asm) -> None:
    a.label("path")
    # `esi` is the `AIUpdateInterface`; the displaced load is the path the move may have dropped.
    a.emit(PATH_HOOK_ORIGINAL)  # mov ecx, [esi+0x140]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "path.none")
    a.jmp_absolute(AI_UPDATE_DO_LOCOMOTOR_PATH_CALL)

    a.label("path.none")
    # Past the call: nothing pushed for it yet, and its answer is never read.
    a.jmp_absolute(AI_UPDATE_DO_LOCOMOTOR_PATH_DONE)


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)
    _emit_transfer(a)
    _emit_enter(a)
    _emit_hero(a)
    _emit_path(a)
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
        (HERO_HOOK_VA, HERO_HOOK_ORIGINAL, "hero"),
        (PATH_HOOK_VA, PATH_HOOK_ORIGINAL, "path"),
    ):
        jump = b"\xe9" + struct.pack("<i", a.label_va(label) - (va + 5))
        edits[va] = (stock, jump + b"\x90" * (len(stock) - len(jump)))
    return edits


class NullGuardsPatch(Patch):
    name = "null-guards"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Add null tests the engine leaves out, at sites real crashes showed are reached: a "
        "MountedTemplate transform whose pending AI order names a removed object (a hero who "
        "walked to the One Ring, then transforms) drops the order, and an Enter order on an "
        "object that is gone or has no contain fails instead of crashing. A Create-a-Hero saved "
        "under another mod, naming a class or subclass this mod lacks, is skipped like a hero "
        "with a bad checksum instead of crashing the skirmish menu. A unit whose path is dropped "
        "while it moves along it skips that frame's path progress update instead of crashing. "
        "Logic-side: every peer "
        "needs the same binary. No INI change"
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
