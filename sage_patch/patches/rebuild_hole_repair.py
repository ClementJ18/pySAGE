"""Make a structure destroyed while being rebuilt leave its rebuild hole again, on the ground.

A creep lair's loop runs through its hole: the hole pays treasure when broken and rebuilds the lair
when left alone. A lair destroyed mid-rebuild left no hole (a six-byte gate refused it), or a hole
buried at the wrong height. The gate is erased, and a `.rhrep` section rebuilds the placement so the
hole lands at the dying object's x and y on the terrain's ground height. The gate's rule moves into
the INI. Every peer needs the same binary.

Derivation: `../docs/rebuild-hole-repair.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    DIE_MODULE_IS_APPLICABLE,
    DIE_MODULE_IS_APPLICABLE_ENTRY,
    DIE_MUX_IS_APPLICABLE,
    DIE_MUX_IS_APPLICABLE_ENTRY,
    OBJECT_GET_HEIGHT_ABOVE_TERRAIN,
    OBJECT_GET_HEIGHT_ABOVE_TERRAIN_BYTES,
    OBJECT_SET_POSITION,
    OBJECT_SET_POSITION_ENTRY,
    REBUILD_HOLE_CONSTRUCTION_GATE,
    REBUILD_HOLE_CONSTRUCTION_GATE_BYTES,
    REBUILD_HOLE_CONSTRUCTION_TEST,
    REBUILD_HOLE_CONSTRUCTION_TEST_BYTES,
    REBUILD_HOLE_ON_DIE,
    REBUILD_HOLE_ON_DIE_ENTRY,
    REBUILD_HOLE_SELF_KILL,
    REBUILD_HOLE_SELF_KILL_BYTES,
    REBUILD_HOLE_SET_POSITION,
    REBUILD_HOLE_SET_POSITION_BYTES,
    REBUILD_HOLE_SET_POSITION_RESUME,
    REBUILD_HOLE_START_REBUILD,
    REBUILD_HOLE_START_REBUILD_BYTES,
    TERRAIN_LOGIC_GET_GROUND_HEIGHT_SLOT,
    THE_TERRAIN_LOGIC,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "COORD3D_SIZE",
    "GATE_ORIGINAL",
    "GATE_REPLACEMENT",
    "GATE_VA",
    "PLACEMENT_ORIGINAL",
    "PLACEMENT_PAD",
    "PLACEMENT_VA",
    "RebuildHoleRepairPatch",
    "SECTION_NAME",
    "build_code",
]

SECTION_NAME = ".rhrep"  # 6 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

GATE_VA = REBUILD_HOLE_CONSTRUCTION_GATE
GATE_ORIGINAL = REBUILD_HOLE_CONSTRUCTION_GATE_BYTES

#: A single six-byte `nop word ptr [eax+eax]` rather than six `0x90`s. Both fall through
#: identically, but one instruction is what the site now *is* - a disassembler, and `verify`,
#: read one erased branch instead of six pad bytes that could equally be leftovers.
GATE_REPLACEMENT = bytes.fromhex("660f1f440000")

PLACEMENT_VA = REBUILD_HOLE_SET_POSITION
PLACEMENT_ORIGINAL = REBUILD_HOLE_SET_POSITION_BYTES

#: What follows the `jmp` into the cave: a five-byte and a one-byte `nop` filling out the eleven
#: stolen bytes. The padding is never executed - the cave returns past it - but it keeps the site
#: readable as one erased sequence rather than as a jump followed by the tail of an instruction
#: that no longer begins anywhere.
PLACEMENT_PAD = bytes.fromhex("0f1f440000") + b"\x90"

#: The `Coord3D` the cave builds on the stack: three `Real`s, matching `Object+0x38`.
COORD3D_SIZE = 0x0C

#: `Object`'s position, as the three offsets the cave reads one at a time rather than as a block,
#: because z is the one it replaces.
_POS_X = 0x38
_POS_Y = 0x3C
_POS_Z = 0x40

#: The first bytes at each address that has to still mean what the patch assumes, as a
#: `{va: bytes}` map. Nothing here is written; they are asserted before either edit, so a build
#: whose layout moved fails loudly rather than erasing whatever branch now sits at `GATE_VA` or
#: returning a cave into the middle of an instruction.
#:
#: `onDie`'s prologue and the status test pin the function and the gate's subject; the die filter
#: pins the `ExemptStatus` opt-out the gate's contract rests on; `startRebuild` pins that this
#: really is the module that arms a rebuild; and the hole's `FADED` self-kill pins the other half
#: of the loop, the part that makes the gate reachable at all. For the placement half, the angle
#: copy pins where the cave returns, `setPosition`'s prologue pins the call it re-issues, and
#: `Object::getHeightAboveTerrain` - which is nothing but a ground-height call and one `fsubr` -
#: pins `THE_TERRAIN_LOGIC`, the vtable slot and the calling convention in a single run of bytes
#: that a moved build could not hold by accident.
ANCHORS = {
    REBUILD_HOLE_ON_DIE: REBUILD_HOLE_ON_DIE_ENTRY,
    REBUILD_HOLE_CONSTRUCTION_TEST: REBUILD_HOLE_CONSTRUCTION_TEST_BYTES,
    REBUILD_HOLE_START_REBUILD: REBUILD_HOLE_START_REBUILD_BYTES,
    REBUILD_HOLE_SELF_KILL: REBUILD_HOLE_SELF_KILL_BYTES,
    DIE_MODULE_IS_APPLICABLE: DIE_MODULE_IS_APPLICABLE_ENTRY,
    DIE_MUX_IS_APPLICABLE: DIE_MUX_IS_APPLICABLE_ENTRY,
    REBUILD_HOLE_SET_POSITION_RESUME: bytes.fromhex("d94644"),  # fld [esi+0x44] - the angle copy
    OBJECT_SET_POSITION: OBJECT_SET_POSITION_ENTRY,
    OBJECT_GET_HEIGHT_ABOVE_TERRAIN: OBJECT_GET_HEIGHT_ABOVE_TERRAIN_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The rewritten placement step. Reached only from the hook, and returns past the stolen run.

    On entry `esi` is the dying `Object` and `edi` the hole `onDie` has just created; both, and
    `ebx`, survive the two calls, which are `__thiscall` and preserve them. `eax`, `ecx` and `edx`
    are dead here - the stock code clobbers all three across the same span - which is what leaves
    the sequence free to use them. The x87 stack is empty at the hook, the next stock instruction
    starting its own, and the one `fstp` below balances the one value `getGroundHeight` pushes.
    """
    a = Asm(base_va)
    # A Coord3D on the stack, seeded with the stock answer, so the terrain lookup failing to
    # happen leaves the engine's own behaviour rather than a hole at the origin.
    a.emit(0x83, 0xEC, COORD3D_SIZE)  # sub esp, 0xc
    a.emit(0x8B, 0x46, _POS_X)  # mov eax, [esi+0x38]
    a.emit(0x89, 0x04, 0x24)  # mov [esp], eax
    a.emit(0x8B, 0x46, _POS_Y)  # mov eax, [esi+0x3c]
    a.emit(0x89, 0x44, 0x24, 0x04)  # mov [esp+4], eax
    a.emit(0x8B, 0x46, _POS_Z)  # mov eax, [esi+0x40]
    a.emit(0x89, 0x44, 0x24, 0x08)  # mov [esp+8], eax

    a.emit(0x8B, 0x0D, struct.pack("<I", THE_TERRAIN_LOGIC))  # mov ecx, [TheTerrainLogic]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "place")  # no terrain loaded: keep the stock answer
    # getGroundHeight(x, y, NULL) -> st0. `__thiscall`, and it cleans its own twelve bytes, so
    # `esp` is back at the Coord3D by the time the result is stored into its z.
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x6A, 0x00)  # push 0            ; Coord3D *normal
    a.emit(0xFF, 0x76, _POS_Y)  # push [esi+0x3c]   ; y
    a.emit(0xFF, 0x76, _POS_X)  # push [esi+0x38]   ; x
    a.emit(0xFF, 0x50, TERRAIN_LOGIC_GET_GROUND_HEIGHT_SLOT)  # call [eax+0x18]
    a.emit(0xD9, 0x5C, 0x24, 0x08)  # fstp dword [esp+8]

    a.label("place")
    a.emit(0x8B, 0xC4)  # mov eax, esp
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCF)  # mov ecx, edi      ; the hole
    a.call_absolute(OBJECT_SET_POSITION)  # ret 4 - it pops the pointer itself
    a.emit(0x83, 0xC4, COORD3D_SIZE)  # add esp, 0xc
    a.jmp_absolute(REBUILD_HOLE_SET_POSITION_RESUME)
    return a.finish()


class RebuildHoleRepairPatch(Patch):
    name = "rebuild-hole-repair"
    author = "officialNecro"
    description = (
        "Let a structure destroyed while it is being rebuilt leave its rebuild hole again, and "
        "put that hole on the terrain rather than at the dying structure's own height, so a creep "
        "lair killed mid-rebuild drops a hole a player can reach and loot. No INI change; add "
        "UNDER_CONSTRUCTION to a RebuildHoleExposeDie's ExemptStatus to keep the stock behaviour "
        "for that object"
    )

    def apply(self, data: bytearray) -> None:
        gate_off = self._offset(data, GATE_VA)
        placement_off = self._offset(data, PLACEMENT_VA)
        # Everything that can refuse is checked before anything is written, so a refused apply -
        # a moved build, or a second run over an image already carrying this - leaves no half-
        # patched binary and no orphan section behind.
        self._check_anchors(data)
        self._check_stock(data, gate_off, GATE_ORIGINAL, GATE_VA)
        self._check_stock(data, placement_off, PLACEMENT_ORIGINAL, PLACEMENT_VA)

        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            gate_off,
            GATE_ORIGINAL,
            GATE_REPLACEMENT,
            "RebuildHoleExposeDie::onDie UNDER_CONSTRUCTION gate -> nop",
        )
        jump = b"\xe9" + struct.pack("<i", section_va - (PLACEMENT_VA + 5)) + PLACEMENT_PAD
        apply_byte_patch(
            data,
            placement_off,
            PLACEMENT_ORIGINAL,
            jump,
            "RebuildHoleExposeDie::onDie hole placement -> rebuild-hole-repair cave",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @staticmethod
    def _check_stock(data: bytes | bytearray, off: int, expected: bytes, va: int) -> None:
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the site is not stock, "
                "so it is either a different build or already patched"
            )

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the rebuild-hole "
                    "death path or the ground-height call is not this build's, so the six bytes "
                    "at the gate are not the branch this patch means to erase and the cave would "
                    "return into the wrong place"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _vsize = located

        gate_off = va_to_offset(data, GATE_VA)
        if gate_off is None:
            return [f"{GATE_VA:#010x} is not mapped by any section"]
        gate = bytes(data[gate_off : gate_off + len(GATE_REPLACEMENT)])
        if gate == GATE_ORIGINAL:
            problems.append(f"{GATE_VA:#010x} still holds the UNDER_CONSTRUCTION gate")
        elif gate != GATE_REPLACEMENT:
            problems.append(
                f"{GATE_VA:#010x} holds {gate.hex()}, expected {GATE_REPLACEMENT.hex()} - "
                "something else has rewritten the gate"
            )

        placement_off = va_to_offset(data, PLACEMENT_VA)
        if placement_off is None:
            return [*problems, f"{PLACEMENT_VA:#010x} is not mapped by any section"]
        if data[placement_off] != 0xE9:
            problems.append(f"{PLACEMENT_VA:#010x} is not a jmp - the placement hook is absent")
        else:
            target = PLACEMENT_VA + 5 + struct.unpack_from("<i", data, placement_off + 1)[0]
            if target != section_va:
                problems.append(f"hook jumps to {target:#010x}, expected {section_va:#010x}")

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected placement step")
        return problems
