"""Hide a freshly unpacked castle's command buttons until its build-up has finished.

`CastleBehavior` fades its new structures in for `FadeTime` before it gives them `BASE_BUILD` for
`BuildTime`, and the control bar only hides the command set on `BASE_BUILD`, so the buttons work for
the whole fade. The bar's `BASE_BUILD` test is repointed at a cave that also answers "building" for
a castle member whose castle is still in that fade state. The bar's own under-construction context
then re-evaluates every frame and gives the buttons back the moment neither holds.

Derivation: `../docs/castle-unpack-button-gap.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    CASTLE_BEHAVIOR_NAME_STRING,
    CASTLE_BEHAVIOR_START_BUILD_UP,
    CASTLE_BEHAVIOR_START_BUILD_UP_BYTES,
    CASTLE_BEHAVIOR_START_FADE,
    CASTLE_BEHAVIOR_START_FADE_BYTES,
    CASTLE_BEHAVIOR_STATE,
    CASTLE_BEHAVIOR_UPDATE,
    CASTLE_BEHAVIOR_UPDATE_VTABLE,
    CASTLE_BEHAVIOR_UPDATE_VTABLE_STAMP,
    CASTLE_BEHAVIOR_UPDATE_VTABLE_STAMP_BYTES,
    CASTLE_MEMBER_BEHAVIOR_NAME_STRING,
    CASTLE_MEMBER_CASTLE_ID,
    CASTLE_MEMBER_CASTLE_ID_STAMP,
    CASTLE_MEMBER_CASTLE_ID_STAMP_BYTES,
    CASTLE_STATE_FADING,
    CONTROL_BAR_BASE_BUILD_CALL,
    CONTROL_BAR_BASE_BUILD_TEST,
    CONTROL_BAR_BASE_BUILD_TEST_BYTES,
    CONTROL_BAR_UNDER_CONSTRUCTION_ARM,
    CONTROL_BAR_UNDER_CONSTRUCTION_ARM_BYTES,
    CONTROL_BAR_UNDER_CONSTRUCTION_UPDATE,
    CONTROL_BAR_UNDER_CONSTRUCTION_UPDATE_BYTES,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    NAME_KEY_FROM_CSTR,
    OBJECT_FIND_MODULE,
    OBJECT_FIND_MODULE_ENTRY,
    OBJECT_TEST_MODEL_CONDITION,
    OBJECT_TEST_MODEL_CONDITION_ENTRY,
    THE_GAME_LOGIC,
    THE_NAME_KEY_GENERATOR,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section

__all__ = [
    "ANCHORS",
    "CastleUnpackButtonsPatch",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".cstbtn"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The bar's `call testModelCondition(BASE_BUILD)`. The cave takes that function's place, so it
#: keeps its contract: `__thiscall` on the object, the condition index on the stack, `ret 4`, the
#: answer in `eax`.
HOOK_VA = CONTROL_BAR_BASE_BUILD_CALL
HOOK_ORIGINAL = call_rel32(HOOK_VA, OBJECT_TEST_MODEL_CONDITION)
_HOOK = HOOK_VA - CONTROL_BAR_BASE_BUILD_TEST

#: Every site the cave's reading depends on, as a `{va: bytes}` map; `apply_byte_patch` asserts the
#: hooked `call` itself.
ANCHORS = {
    # The whole bar test around the hook, minus the `call`: the `push 0xdb` that is the cave's
    # argument, `ecx` = the object, and the `jne` to the under-construction arm.
    CONTROL_BAR_BASE_BUILD_TEST: CONTROL_BAR_BASE_BUILD_TEST_BYTES[:_HOOK],
    HOOK_VA + 5: CONTROL_BAR_BASE_BUILD_TEST_BYTES[_HOOK + 5 :],
    CONTROL_BAR_UNDER_CONSTRUCTION_ARM: CONTROL_BAR_UNDER_CONSTRUCTION_ARM_BYTES,
    # What gives the buttons back: the context's update re-evaluates while not UNDER_CONSTRUCTION.
    CONTROL_BAR_UNDER_CONSTRUCTION_UPDATE: CONTROL_BAR_UNDER_CONSTRUCTION_UPDATE_BYTES,
    # The helpers the cave calls.
    OBJECT_TEST_MODEL_CONDITION: OBJECT_TEST_MODEL_CONDITION_ENTRY,
    OBJECT_FIND_MODULE: OBJECT_FIND_MODULE_ENTRY,
    NAME_KEY_FROM_CSTR: bytes.fromhex("b847a8b700e8fa464f00"),
    GAME_LOGIC_FIND_OBJECT_BY_ID: bytes.fromhex("837c24040074"),  # an id of 0 answers NULL
    CASTLE_BEHAVIOR_NAME_STRING: b"CastleBehavior\x00",
    CASTLE_MEMBER_BEHAVIOR_NAME_STRING: b"CastleMemberBehavior\x00",
    # Why `CASTLE_BEHAVIOR_STATE == 2` means "fading": the update interface is at `+0x10`, the
    # state-1 arm stores 2 there and unpacks, and the state-2 expiry stores 3 and sets BASE_BUILD.
    CASTLE_BEHAVIOR_UPDATE_VTABLE_STAMP: CASTLE_BEHAVIOR_UPDATE_VTABLE_STAMP_BYTES,
    CASTLE_BEHAVIOR_UPDATE_VTABLE: struct.pack("<I", CASTLE_BEHAVIOR_UPDATE),
    CASTLE_BEHAVIOR_START_FADE: CASTLE_BEHAVIOR_START_FADE_BYTES,
    CASTLE_BEHAVIOR_START_BUILD_UP: CASTLE_BEHAVIOR_START_BUILD_UP_BYTES,
    # Where a member learns which flag built it.
    CASTLE_MEMBER_CASTLE_ID_STAMP: CASTLE_MEMBER_CASTLE_ID_STAMP_BYTES,
}


def build_code(base_va: int) -> bytes:
    """`testModelCondition`, widened: also true for a castle member whose castle is fading in."""
    a = Asm(base_va)
    # Every callee is `__thiscall` and keeps `ebx`/`esi`/`edi`/`ebp`, so `esi` is the only register
    # the cave has to save for itself; `edx` is the stock callee's to clobber too.
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xF1)  # mov esi, ecx                      the selected object
    a.emit(0xFF, 0x74, 0x24, 0x08)  # push [esp+8]            the condition index (BASE_BUILD)
    a.call_absolute(OBJECT_TEST_MODEL_CONDITION)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "done")  # already building: the stock answer

    _find_module(a, CASTLE_MEMBER_BEHAVIOR_NAME_STRING)
    a.emit(0xFF, 0x70, CASTLE_MEMBER_CASTLE_ID)  # push [eax+0x18]   the flag's ObjectID
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(GAME_LOGIC_FIND_OBJECT_BY_ID)  # NULL for 0 or a flag that is gone
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "no")
    a.emit(0x8B, 0xF0)  # mov esi, eax                      the flag
    _find_module(a, CASTLE_BEHAVIOR_NAME_STRING)
    a.emit(0x83, 0x78, CASTLE_BEHAVIOR_STATE, CASTLE_STATE_FADING)  # cmp dword [eax+0x34], 2
    a.jcc(JNE, "no")
    a.emit(0x33, 0xC0, 0x40)  # xor eax, eax / inc eax
    a.jmp("done")

    a.label("no")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("done")
    a.emit(0x5E)  # pop esi
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a.finish()


def _find_module(a: Asm, name: int) -> None:
    """`eax` = `esi->findModule(nameKey(name))`, leaving through `no` when it is NULL. The key is
    looked up each time rather than read from the engine's lazily-filled caches, which may still
    be empty."""
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
    a.emit(0x68, struct.pack("<I", name))  # push name
    a.call_absolute(NAME_KEY_FROM_CSTR)
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_FIND_MODULE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "no")


class CastleUnpackButtonsPatch(Patch):
    name = "castle-unpack-buttons"
    author = "officialNecro"
    description = (
        "Hide the command buttons of structures a CastleBehavior flag has just unpacked (the "
        "citadel, its buildings) while they fade in, as they already are during the BASE_BUILD "
        "build-up that follows, so nothing can be used before the unpack has finished. No INI "
        "change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            file_offset(data, HOOK_VA),
            HOOK_ORIGINAL,
            call_rel32(HOOK_VA, cave_va),
            "control bar BASE_BUILD test -> castle-unpack-buttons cave",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        got = bytes(data[file_offset(data, HOOK_VA) : file_offset(data, HOOK_VA) + 5])
        if got != HOOK_ORIGINAL:
            raise ValueError(
                f"{HOOK_VA:#010x} holds {got.hex()}, expected the stock call "
                f"{HOOK_ORIGINAL.hex()} - the file already carries this patch, or is not the "
                "expected build"
            )
        for va, expected in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the control bar "
                    "or CastleBehavior layout is not this build's, so the cave would read the "
                    "wrong state or return into the wrong place"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        problems: list[str] = []
        code = build_code(cave_va)
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routine in {SECTION_NAME} is not the one this patch builds")
        want = call_rel32(HOOK_VA, cave_va)
        off = file_offset(data, HOOK_VA)
        got = bytes(data[off : off + len(want)])
        if got != want:
            problems.append(
                f"@{HOOK_VA:#010x}: the BASE_BUILD test does not call {SECTION_NAME} "
                f"(holds {got.hex()})"
            )
        return problems
