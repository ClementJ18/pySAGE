"""Stop the skirmish AI sending flag-capture squads at build plots that are already claimed.

The squad tactic's picker (`AI_FLAG_CAPTURE_PICKER`) takes the nearest non-allied `CAPTUREFLAG`. A
claimed build plot cannot be captured until its structure falls, so the squad stands on it forever.
A cave makes the picker skip claimed `BASE_SITE` plots; plain capture flags are unchanged.

Derivation: `../docs/ai-flag-capture-gate.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_FLAG_CAPTURE_KEEP,
    AI_FLAG_CAPTURE_PICKER,
    AI_FLAG_CAPTURE_PICKER_CALL,
    AI_FLAG_CAPTURE_PICKER_CALL_BYTES,
    AI_FLAG_CAPTURE_PICKER_ENTRY,
    AI_FLAG_CAPTURE_RELATIONSHIP_TEST,
    AI_FLAG_CAPTURE_RELATIONSHIP_TEST_BYTES,
    AI_FLAG_CAPTURE_SKIP,
    AI_FLAG_CAPTURE_SQUAD_NAME_PUSH,
    AI_FLAG_CAPTURE_SQUAD_NAME_PUSH_BYTES,
    AI_FLAG_CAPTURE_SQUAD_UPDATE,
    AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT,
    AI_FLAG_CAPTURE_SQUAD_VTABLE,
    KINDOF_BASE_SITE,
    OBJECT_STATUS,
    OBJECT_STATUS_UNSELECTABLE,
    PLAYER_RELATIONSHIP_ALLIES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

# `test byte [reg + base + bit/8], 1 << (bit % 8)` is how the engine asks a single bit of either
# bitfield: `KindOf` on the `ThingTemplate` and `ObjectStatus` on the `Object` differ only in
# their base displacement. `kind_of.bit_test` emits exactly that encoding and nothing about it is
# `KindOf`-specific beyond where it lives, so it serves for both rather than being duplicated.
from .utils.kind_of import THING_TEMPLATE_MASK_OFFSET, bit_test

__all__ = [
    "ANCHORS",
    "AiFlagCaptureGatePatch",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".aiflag"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = AI_FLAG_CAPTURE_RELATIONSHIP_TEST
HOOK_ORIGINAL = AI_FLAG_CAPTURE_RELATIONSHIP_TEST_BYTES

#: ModRM r/m encodings for the two registers the cave reads through: `esi` is the candidate
#: `Object` the picker is holding, `ecx` the `ThingTemplate` the cave loads from it.
_ESI = 6
_ECX = 1

#: The first instruction at each address the cave jumps to, plus the two that prove the function
#: being edited is the flag-capture tactic's picker: its own prologue, its single call site inside
#: `AIFlagCaptureSquad::update`, and the constructor push that names the tactic in plain text. The
#: test's own bytes are asserted by `apply_byte_patch`; these are what nothing else would catch,
#: so a build whose layout moved fails here rather than on a wild jump.
ANCHORS = {
    AI_FLAG_CAPTURE_PICKER: AI_FLAG_CAPTURE_PICKER_ENTRY,
    AI_FLAG_CAPTURE_PICKER_CALL: AI_FLAG_CAPTURE_PICKER_CALL_BYTES,
    AI_FLAG_CAPTURE_SQUAD_NAME_PUSH: AI_FLAG_CAPTURE_SQUAD_NAME_PUSH_BYTES,
    AI_FLAG_CAPTURE_KEEP: bytes.fromhex("8b4604"),  # mov eax, [esi+4]  ; ThingTemplate*
    AI_FLAG_CAPTURE_SKIP: bytes.fromhex("83c304"),  # add ebx, 4        ; next candidate
}


def build_code(base_va: int) -> bytes:
    """The replacement ownership test. Reached only from the hook, and never returns to it.

    On entry `eax` holds what `Player::getRelationship` just answered for the candidate and
    `esi` is the candidate `Object`. Both of the cave's exits are edges the stock picker
    already had, so nothing downstream can tell the difference except in the case this exists to
    change.
    """
    a = Asm(base_va)
    # The stock test, verbatim: one's own and one's allies' flags are not targets.
    a.emit(0x83, 0xF8, PLAYER_RELATIONSHIP_ALLIES)  # cmp eax, ALLIES
    a.jcc(JE, "skip")

    # BASE_SITE first, and on its own: a plain capture flag is recaptured by standing on it, which
    # is what this tactic is for, so it must reach the accept edge whoever holds it.
    a.emit(0x8B, 0x4E, 0x04)  # mov ecx, [esi+4]      ; ThingTemplate*
    a.emit(bit_test(KINDOF_BASE_SITE, _ECX, THING_TEMPLATE_MASK_OFFSET))
    a.jcc(JE, "keep")

    # A build plot, then. Claimed plots are unselectable - a free one is selectable because
    # clicking it is how a player builds on it - and a claimed plot carries a structure that has
    # to be destroyed before the flag under it can be taken by anyone.
    a.emit(bit_test(OBJECT_STATUS_UNSELECTABLE, _ESI, OBJECT_STATUS))
    a.jcc(JNE, "skip")

    a.label("keep")
    a.jmp_absolute(AI_FLAG_CAPTURE_KEEP)

    a.label("skip")
    a.jmp_absolute(AI_FLAG_CAPTURE_SKIP)
    return a.finish()


class AiFlagCaptureGatePatch(Patch):
    name = "ai-flag-capture-gate"
    author = "officialNecro"
    description = (
        "Stop the skirmish AI's flag-capture squads targeting build plots that are already "
        "claimed, which they can never capture and stall on forever. No INI change: what the "
        "gate reads is the BASE_SITE KindOf every plot flag already carries"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_dispatch(data)
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        # The stock test is five bytes and `jmp rel32` is five bytes, so nothing needs padding.
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "AIFlagCaptureSquad flag picker -> ai-flag-capture-gate cave",
        )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless `AIFlagCaptureSquad`'s vtable still names the update that calls the picker
        being edited. The anchors prove the call exists; this proves the function it sits in is
        the one the tactics generator actually dispatches to."""
        slot_va = AI_FLAG_CAPTURE_SQUAD_VTABLE + AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT
        slot_off = va_to_offset(data, slot_va)
        if slot_off is None:
            raise ValueError("the AIFlagCaptureSquad vtable is not mapped - not the expected build")
        target = struct.unpack_from("<I", data, slot_off)[0]
        if target != AI_FLAG_CAPTURE_SQUAD_UPDATE:
            raise ValueError(
                f"vtable slot {slot_va:#010x} dispatches to {target:#010x}, not "
                f"{AI_FLAG_CAPTURE_SQUAD_UPDATE:#010x} - the tactic whose picker is being gated "
                "is not the live one"
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the flag picker's "
                    "layout is not this build's, so the cave would jump into the wrong place"
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
            problems.append(f"the {SECTION_NAME} cave does not hold the expected test")
        return problems
