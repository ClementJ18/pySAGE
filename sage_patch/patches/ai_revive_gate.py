"""Make the AI respect a REVIVE button's `NeededUpgrade`, as the player's control bar does.

`BuildAssistant::canMakeUnit` checks `NeededUpgrade` for unit buttons but not in its revive branch,
so the AI recruits heroes from slots a mod disabled. A cave adds the upgrade test to the revive
branch, applied only when the caller is the AI (it checks the return address).

Derivation: `../docs/ai-revive-gate.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    BUILD_ASSISTANT_VTABLE,
    CAN_MAKE_UNIT,
    CAN_MAKE_UNIT_ACCEPT,
    CAN_MAKE_UNIT_BUMP_SLOT,
    CAN_MAKE_UNIT_NEXT_SLOT,
    CAN_MAKE_UNIT_PRODUCTION_GATE,
    CAN_MAKE_UNIT_PRODUCTION_GATE_CALL,
    CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES,
    CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
    CAN_MAKE_UNIT_REVIVE_BRANCH,
    CAN_MAKE_UNIT_REVIVE_BRANCH_ENTRY,
    CAN_MAKE_UNIT_UPGRADE_GATE,
    CAN_MAKE_UNIT_VTABLE_SLOT,
    GUICOMMAND_REVIVE,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "AiReviveGatePatch",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "PRODUCTION_GATE_RETURN",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".aigate"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = CAN_MAKE_UNIT_REVIVE_BRANCH
HOOK_ORIGINAL = CAN_MAKE_UNIT_REVIVE_BRANCH_ENTRY

#: The address `BuildAssistant`'s `+0x64` gate returns to, and therefore the return address
#: `canMakeUnit` sees on the stack when it was reached that way rather than by the AI directly.
#: Derived from the anchored call rather than written down, so a build whose layout moved fails
#: on the anchor instead of comparing against a stale constant.
PRODUCTION_GATE_RETURN = CAN_MAKE_UNIT_PRODUCTION_GATE_CALL + len(
    CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES
)

#: The first instruction at each address the cave jumps to or reads, as a `{va: bytes}` map. The
#: revive branch's own bytes are asserted by `apply_byte_patch`; these are the jump targets and
#: the call the return-address test is derived from, which nothing else would catch. A build
#: whose layout moved fails here instead of on a wild jump or a mis-aimed comparison.
ANCHORS = {
    CAN_MAKE_UNIT_UPGRADE_GATE: bytes.fromhex("8b461c"),  # mov eax, [esi+0x1c]   ; Options
    CAN_MAKE_UNIT_ACCEPT: bytes.fromhex("8b4d08"),  # mov ecx, [ebp+8]      ; the producer
    CAN_MAKE_UNIT_BUMP_SLOT: bytes.fromhex("ff45f4"),  # inc dword [ebp-0xc]   ; slots seen
    CAN_MAKE_UNIT_NEXT_SLOT: bytes.fromhex("ff45f8"),  # inc dword [ebp-8]     ; slot index
    CAN_MAKE_UNIT_PRODUCTION_GATE_CALL: CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The rewritten revive branch. Reached only from the hook, and never returns to it."""
    a = Asm(base_va)
    a.emit(0x83, 0x7E, 0x14, GUICOMMAND_REVIVE)  # cmp dword [esi+0x14], GUICOMMAND_REVIVE
    a.jcc(JE, "is_revive")
    a.jmp_absolute(CAN_MAKE_UNIT_NEXT_SLOT)  # not a REVIVE button

    a.label("is_revive")
    a.emit(0x8B, 0x45, 0xF4)  # mov eax, [ebp-0xc]       ; REVIVE slots seen
    a.emit(0x3B, 0x45, 0x10)  # cmp eax, [ebp+0x10]      ; the requested revive index
    a.jcc(JE, "matched")
    a.jmp_absolute(CAN_MAKE_UNIT_BUMP_SLOT)  # a REVIVE slot, but not this index

    a.label("matched")
    # Whose question is this? `canMakeUnit` is reached either directly - only the AI does that -
    # or through `BuildAssistant`'s `+0x64` gate, which is what the ControlBar and production ask.
    # The gate is for the AI's choice of producer, so anything arriving through `+0x64` takes the
    # stock edge and this patch cannot change what is shown, clickable or queueable.
    a.emit(0x81, 0x7D, 0x04, struct.pack("<I", PRODUCTION_GATE_RETURN))  # cmp [ebp+4], <return>
    a.jcc(JE, "not_the_ai")

    # Count it now: the gate's failure edge continues the walk, and a slot that has been counted
    # cannot be matched again, so failing the gate ends the search for this index.
    a.emit(0xFF, 0x45, 0xF4)  # inc dword [ebp-0xc]
    a.jmp_absolute(CAN_MAKE_UNIT_UPGRADE_GATE)

    a.label("not_the_ai")
    a.jmp_absolute(CAN_MAKE_UNIT_ACCEPT)
    return a.finish()


class AiReviveGatePatch(Patch):
    name = "ai-revive-gate"
    author = "officialNecro"
    description = (
        "Make the AI respect a REVIVE button's NeededUpgrade, as the player already does. No "
        "INI change: what gates the AI is the NeededUpgrade / NeededUpgradeAny already on the "
        "CommandButton"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        # Prove the function being edited is the one the AI dispatches to, and that the points
        # the cave jumps back into still hold the instructions they are chosen for.
        self._check_dispatch(data)
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "canMakeUnit revive branch -> ai-revive-gate cave",
        )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless `BuildAssistant`'s vtable still names both functions this depends on: the
        one being edited, and the `+0x64` gate whose return address separates the AI's queries
        from everyone else's."""
        for slot, expected, what in (
            (CAN_MAKE_UNIT_VTABLE_SLOT, CAN_MAKE_UNIT, "the revive branch being patched"),
            (
                CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
                CAN_MAKE_UNIT_PRODUCTION_GATE,
                "the production gate the return-address test names",
            ),
        ):
            slot_va = BUILD_ASSISTANT_VTABLE + slot
            slot_off = va_to_offset(data, slot_va)
            if slot_off is None:
                raise ValueError("the BuildAssistant vtable is not mapped - not the expected build")
            target = struct.unpack_from("<I", data, slot_off)[0]
            if target != expected:
                raise ValueError(
                    f"vtable slot {slot_va:#010x} dispatches to {target:#010x}, not "
                    f"{expected:#010x} - {what} is not the live one"
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - canMakeUnit's "
                    "layout is not this build's, so the cave would jump into the wrong place "
                    "or test the wrong return address"
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
