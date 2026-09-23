"""Let an aura come back when the structure carrying it is rebuilt from rubble.

`PassiveAreaEffectBehavior` and `AttributeModifierAuraUpdate` return `UPDATE_SLEEP_FOREVER` the
first time they tick on a dead object, and nothing wakes a module on revival, so a keep's aura is
lost for the rest of the game. The patch makes both return their ordinary sleep instead: five bytes
in the first, a 24-byte window and a cave in the second. No INI change.

Derivation: `../docs/passive-aura-revive.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    ATTRIBUTE_MODIFIER_AURA_ANCHORS,
    ATTRIBUTE_MODIFIER_AURA_GATES,
    ATTRIBUTE_MODIFIER_AURA_GATES_BYTES,
    ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP,
    ATTRIBUTE_MODIFIER_AURA_RUN_WHILE_DEAD_OFFSET,
    ATTRIBUTE_MODIFIER_AURA_SCAN,
    ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET,
    GETTING_BUILT_STILL_BUILDING_SLOT,
    OBJECT_EFFECTIVELY_DEAD_FLAG,
    OBJECT_GET_GETTING_BUILT_BEHAVIOR,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    OBJECT_TEST_STATUS,
    PASSIVE_AREA_EFFECT_ANCHORS,
    PASSIVE_AREA_EFFECT_DEAD_SLEEP,
    PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES,
    PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section

__all__ = [
    "GATE_JUMP_PADDING",
    "PATCHED_BYTES",
    "SECTION_NAME",
    "PassiveAuraRevivePatch",
    "build_code",
]

SECTION_NAME = ".aurevi"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: What the twenty-four byte gate block is padded out with behind the five-byte jump. Named because
#: `verify` checks it: the `nop` run is how the rewrite says it
#: covered the whole block rather than leaving the tail of an instruction behind.
GATE_JUMP_PADDING = b"\x90" * (len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES) - 5)


#: `[ebp-0x14]` as a `modrm` displacement byte - the slot the update keeps `this` in.
_EBP_THIS = ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET & 0xFF


def _sleep_the_ping_delay(offset: int) -> bytes:
    """`mov eax, [esp+offset]` then a `nop`, so the rewrite is the same five bytes the sentinel
    occupied and the `jmp` behind it keeps its address."""
    if not 0 <= offset <= 0x7F:
        raise ValueError(f"[esp+0x{offset:x}] does not encode as a byte displacement")
    return bytes((0x8B, 0x44, 0x24, offset, 0x90))


#: What replaces `PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES`.
PATCHED_BYTES = _sleep_the_ping_delay(PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET)


def build_code(base_va: int) -> bytes:
    """`AttributeModifierAuraUpdate`'s gate block, with a construction gate in front of it and the
    dead arm split off the shared sentinel.

    Entered from `ATTRIBUTE_MODIFIER_AURA_GATES` with `esi` holding the
    `Object`, `ecx` still holding the update's `this` and `ebx` zeroed. It never returns to the
    hook: every arm jumps back into the update. Both calls are `__thiscall` and preserve
    `esi`/`edi`/`ebx`, which is what lets the stock tests below them run unchanged - but **not**
    `ecx`, which the scan arm therefore reloads from the update's own `this` slot.
    """
    a = Asm(base_va)
    # The three displaced instructions, before `ecx` is needed for anything else.
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0x79, 0xF4)  # mov edi, [ecx-0xc]     the ModuleData
    a.emit(0x89, 0x4D, _EBP_THIS)  # mov [ebp-0x14], ecx    `this`, read back further down

    # Is the object still going up? Transcribed from `PassiveAreaEffectBehavior::update`
    # @0x00887E45, which is the gate this module is missing.
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_GET_GETTING_BUILT_BEHAVIOR)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "no_getting_built")
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0xFF, 0x52, GETTING_BUILT_STILL_BUILDING_SLOT)  # call [edx+0x2c]
    a.jmp("still_building")

    a.label("no_getting_built")
    a.emit(0x6A, OBJECT_STATUS_UNDER_CONSTRUCTION)  # push 2
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_TEST_STATUS)

    a.label("still_building")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "ordinary_sleep")  # not finished -> wait, and look again

    # The stock dead test, re-emitted.
    a.emit(0xF6, 0x86, struct.pack("<I", OBJECT_EFFECTIVELY_DEAD_FLAG), 0x01)
    a.jcc(JE, "scan")
    # The stock `RunWhileDead` compare. The immediate stands in for the stock `bl` so the cave does
    # not depend on the `xor ebx, ebx` at 0x0089F43F staying where it is; `ebx` is zero either way.
    a.emit(0x80, 0xBF, struct.pack("<I", ATTRIBUTE_MODIFIER_AURA_RUN_WHILE_DEAD_OFFSET), 0x00)
    a.jcc(JNE, "scan")  # RunWhileDead = Yes -> keep applying through the death, unchanged

    a.label("ordinary_sleep")
    a.jmp_absolute(ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP)

    # `this` goes back in `ecx` before the scan, because the calls above left their own there and
    # the resume point dereferences it ten instructions on. The sleep arm needs no such thing: it
    # reloads `ecx` from the SEH slot itself.
    a.label("scan")
    a.emit(0x8B, 0x4D, _EBP_THIS)  # mov ecx, [ebp-0x14]
    a.jmp_absolute(ATTRIBUTE_MODIFIER_AURA_SCAN)
    return a.finish()


class PassiveAuraRevivePatch(Patch):
    """Stop the two aura modules sleeping forever when their own object dies."""

    name = "passive-aura-revive"
    author = "officialNecro"
    description = (
        "PassiveAreaEffectBehavior and AttributeModifierAuraUpdate stop parking themselves at "
        "UPDATE_SLEEP_FOREVER the first time they tick on a dead object, and return their ordinary "
        "sleep instead, so an aura on a structure that survives death as rubble (KeepObjectDie "
        "plus RubbleRiseUpdate, which is every castle keep, wall, gate and camp citadel) resumes "
        "once the structure has been rebuilt rather than being lost for the rest of the game. The "
        "aura is still inactive while the object is dead and for the whole of the rebuild, "
        "AttributeModifierAuraUpdate gaining the GettingBuiltBehavior gate its sibling already "
        "has - so it also stays off while a structure is built for the first time. An aura still "
        "waiting on its TriggeredBy upgrade still sleeps until the upgrade arrives. Needs no INI, "
        ".str or map change - the modules and their fields are unchanged"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        gate_off = file_offset(data, ATTRIBUTE_MODIFIER_AURA_GATES)
        passive_off = file_offset(data, PASSIVE_AREA_EFFECT_DEAD_SLEEP)

        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (ATTRIBUTE_MODIFIER_AURA_GATES + 5))
        apply_byte_patch(
            data,
            passive_off,
            PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES,
            PATCHED_BYTES,
            f"PassiveAreaEffectBehavior dead-arm sleep @0x{PASSIVE_AREA_EFFECT_DEAD_SLEEP:08x}",
        )
        apply_byte_patch(
            data,
            gate_off,
            ATTRIBUTE_MODIFIER_AURA_GATES_BYTES,
            jump + GATE_JUMP_PADDING,
            f"AttributeModifierAuraUpdate gate block "
            f"@0x{ATTRIBUTE_MODIFIER_AURA_GATES:08x} -> {SECTION_NAME} cave",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        try:
            passive_off = file_offset(data, PASSIVE_AREA_EFFECT_DEAD_SLEEP)
            gate_off = file_offset(data, ATTRIBUTE_MODIFIER_AURA_GATES)
        except ValueError as exc:
            return [str(exc)]

        got = bytes(data[passive_off : passive_off + len(PATCHED_BYTES)])
        if got != PATCHED_BYTES:
            site = f"the PassiveAreaEffectBehavior dead arm @0x{PASSIVE_AREA_EFFECT_DEAD_SLEEP:08x}"
            if got == PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES:
                problems.append(f"{site} is unpatched")
            else:
                problems.append(
                    f"{site} is {got.hex()}, expected {PATCHED_BYTES.hex()} (patched) or "
                    f"{PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES.hex()} (stock)"
                )

        located = find_section(data, SECTION_NAME)
        if located is None:
            problems.append(f"{SECTION_NAME} section is absent")
            return problems
        section_va, section_off, _ = located

        gate = f"the AttributeModifierAuraUpdate gates @0x{ATTRIBUTE_MODIFIER_AURA_GATES:08x}"
        if data[gate_off] != 0xE9:
            problems.append(f"{gate} are not a jmp - the hook is not installed")
        else:
            displacement = struct.unpack_from("<i", data, gate_off + 1)[0]
            target = ATTRIBUTE_MODIFIER_AURA_GATES + 5 + displacement
            if target != section_va:
                problems.append(f"{gate} jump to 0x{target:08x}, expected 0x{section_va:08x}")
            tail = bytes(data[gate_off + 5 : gate_off + len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES)])
            if tail != GATE_JUMP_PADDING:
                problems.append(
                    f"{gate} left {tail.hex()} behind the jump, "
                    f"expected {len(GATE_JUMP_PADDING)} nop"
                )

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected gates")
        return problems

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Refuse a build where either update is not the function its bytes were read out of.

        For each module the module-name string and the vtable slot say the function is that
        module's update. Beyond that the passive module's `PingDelay` read and normal return frame
        the scratch slot `[esp+0x10]` names, and its construction gate is the routine the cave
        transcribes; the aura module's anchors cover the two exits its cave has to keep apart - the
        sentinel it deliberately leaves stock, and the sleep computation it jumps to - plus the two
        engine routines the transcription calls.
        """
        for va, expected in {
            **PASSIVE_AREA_EFFECT_ANCHORS,
            **ATTRIBUTE_MODIFIER_AURA_ANCHORS,
        }.items():
            got = bytes(data[file_offset(data, va) :][: len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the game.dat these addresses were read from"
                )
