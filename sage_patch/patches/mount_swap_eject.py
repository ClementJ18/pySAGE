"""Let a `MountedTemplate` swap drop its passengers instead of deleting them with the old object.

`ToggleMountedSpecialAbilityUpdate` builds the replacement, moves experience, health, selection
and the AI's command onto it, and then retires the old object through
`GameLogic::destroyObject`. Nothing moves the old object's passengers, so a hobbit riding with
Edain's Aragorn or Gandalf is deleted along with the form it was sitting on.
`EjectPassengersOnDeath` never gets a say: a retire is not a death.

A hook on the retire's `destroyObject` call walks the old object's modules first. Each contain
module with `EjectPassengersOnDeath = Yes` that is not a horde is emptied the way stock death
empties it: the riders who could not walk out from here are killed, then `removeAllContained`
puts the rest back in the world. `LifetimeUpdate`'s `ExpirationTemplate` (`lifetime-fields`)
retires through the same routine and gets the same behaviour.

Derivation: `../docs/mount-swap-eject.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    BEHAVIOR_GET_CONTAIN_SLOT,
    BEHAVIOR_MODULE_INTERFACE,
    CONTAIN_GET_HORDE_IFACE_SLOT,
    CONTAIN_REMOVE_ALL_SLOT,
    GAME_LOGIC_DESTROY_OBJECT,
    MODULE_MODULE_DATA,
    OBJECT_MODULE_LIST,
    OPEN_CONTAIN_CONTAIN_INTERFACE,
    OPEN_CONTAIN_EJECT_PASSENGERS_ON_DEATH,
    OPEN_CONTAIN_GET_CONTAIN,
    OPEN_CONTAIN_GET_CONTAIN_BYTES,
    OPEN_CONTAIN_KILL_RIDERS_NOT_FREE_TO_EXIT_SLOT,
    OPEN_CONTAIN_ON_DIE_EJECT,
    OPEN_CONTAIN_ON_DIE_EJECT_BYTES,
    THE_GAME_LOGIC,
    TOGGLE_MOUNTED_RETIRE,
    TOGGLE_MOUNTED_RETIRE_BYTES,
    TOGGLE_MOUNTED_RETIRE_DESTROY,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32

__all__ = [
    "ANCHORS",
    "HOOK_WIDTH",
    "MountSwapEjectPatch",
    "RESUME",
    "SECTION_NAME",
    "STOCK_HOOK",
    "build_code",
]

SECTION_NAME = ".mntejc"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: `mov ecx, [THE_GAME_LOGIC]` - replaced by a `jmp` into the cave and a `nop`.
HOOK_WIDTH = 6
STOCK_HOOK = b"\x8b\x0d" + struct.pack("<I", THE_GAME_LOGIC)
#: `push esi` / `call destroyObject`, where the cave rejoins once it has redone the `mov`.
RESUME = TOGGLE_MOUNTED_RETIRE_DESTROY + HOOK_WIDTH

#: What the cave relies on, as `{va: bytes}`. The retire in full, because the cave reads `esi` as
#: the old object and returns into its tail; `getContain`, because matching it is how the cave
#: knows a module has `OpenContain`'s layout; and the eject arm of `OpenContain::onDie`, which is
#: where the flag's offset and both slots the cave calls come from.
ANCHORS = {
    TOGGLE_MOUNTED_RETIRE: TOGGLE_MOUNTED_RETIRE_BYTES,
    OPEN_CONTAIN_GET_CONTAIN: OPEN_CONTAIN_GET_CONTAIN_BYTES,
    OPEN_CONTAIN_ON_DIE_EJECT: OPEN_CONTAIN_ON_DIE_EJECT_BYTES,
}

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def build_code(base_va: int) -> bytes:
    """Empty every ejecting contain on the object in `esi`, then do the displaced `mov` and go on
    to `destroyObject`.

    `esi` is the old object and belongs to the retire, which pops it last. `ebx` and `edi` are
    the retire's caller's, so they are saved; `eax`, `ecx` and `edx` are free, since a call to
    `destroyObject` follows. Each module call is `__thiscall` and preserves `ebx`/`esi`/`edi`."""
    a = Asm(base_va)
    a.emit(0x53)  # push ebx
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\x9e", struct.pack("<I", OBJECT_MODULE_LIST))  # mov ebx, [esi+0x24c]

    a.label("next")
    a.emit(0x8B, 0x03)  # mov eax, [ebx]                the module, NULL at the end
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "done")
    a.emit(0x83, 0xC3, 0x04)  # add ebx, 4
    a.emit(0x8B, 0x48, BEHAVIOR_MODULE_INTERFACE)  # mov ecx, [eax+0xc]    interface vtable
    a.emit(0x81, 0x79, BEHAVIOR_GET_CONTAIN_SLOT)  # cmp dword [ecx+8], OpenContain::getContain
    a.emit(struct.pack("<I", OPEN_CONTAIN_GET_CONTAIN))
    a.jcc_short(JNE, "next")  # not an OpenContain: left as stock
    a.emit(0x8B, 0x48, MODULE_MODULE_DATA)  # mov ecx, [eax+4]      ModuleData
    a.emit(0x80, 0xB9, struct.pack("<I", OPEN_CONTAIN_EJECT_PASSENGERS_ON_DEATH), 0x00)
    a.jcc_short(JE, "next")  # EjectPassengersOnDeath = No
    a.emit(0x8D, 0x78, OPEN_CONTAIN_CONTAIN_INTERFACE)  # lea edi, [eax+0x20]   contain iface
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.emit(0x8B, 0x07)  # mov eax, [edi]
    a.emit(0xFF, 0x50, CONTAIN_GET_HORDE_IFACE_SLOT)  # call [eax+0x7c]       getHordeIface
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JNE, "next")  # a horde's members go with it, as stock
    a.emit(0x8D, 0x4F, (-OPEN_CONTAIN_CONTAIN_INTERFACE) & 0xFF)  # lea ecx, [edi-0x20]  module
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, OPEN_CONTAIN_KILL_RIDERS_NOT_FREE_TO_EXIT_SLOT)  # call [eax+0x64]
    a.emit(0x6A, 0x00)  # push 0                        exposeStealthUnits = false
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.emit(0x8B, 0x07)  # mov eax, [edi]
    a.emit(0xFF, 0x90, struct.pack("<I", CONTAIN_REMOVE_ALL_SLOT))  # call [eax+0xa8]
    a.jmp_short("next")

    a.label("done")
    a.emit(0x5F)  # pop edi
    a.emit(0x5B)  # pop ebx
    a.emit(STOCK_HOOK)  # mov ecx, [TheGameLogic]      the displaced instruction
    a.jmp_absolute(RESUME)  # push esi / call destroyObject
    return a.finish()


class MountSwapEjectPatch(Patch):
    name = "mount-swap-eject"
    author = "officialNecro"
    description = (
        "When a ToggleMountedSpecialAbilityUpdate swap (MountedTemplate) or a LifetimeUpdate "
        "ExpirationTemplate replaces an object, first empty each of its contain modules that sets "
        "EjectPassengersOnDeath = Yes, as a death would: riders who cannot walk out from there "
        "are killed and the rest are put down beside it. Stock deletes them with the old object "
        "- a hobbit riding with a hero who changes form. Horde contains are left alone. "
        "Logic-side: every peer needs the same binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            file_offset(data, TOGGLE_MOUNTED_RETIRE_DESTROY),
            STOCK_HOOK,
            jmp_rel32(TOGGLE_MOUNTED_RETIRE_DESTROY, cave_va, HOOK_WIDTH),
            "mount-swap retire -> eject EjectPassengersOnDeath contains before destroyObject",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"@0x{va:08x}: expected {expected.hex()}, got {got.hex()} - the file is not "
                    "the expected build, or already carries this patch"
                )
        # the call the cave rejoins in front of, decoded rather than trusted to the anchor's hex
        call_va = RESUME + 1
        off = file_offset(data, call_va)
        target = call_va + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if data[off] != 0xE8 or target != GAME_LOGIC_DESTROY_OBJECT:
            raise ValueError(
                f"@0x{call_va:08x}: expected a call to destroyObject "
                f"(0x{GAME_LOGIC_DESTROY_OBJECT:08x}) - not the expected build"
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
        want = jmp_rel32(TOGGLE_MOUNTED_RETIRE_DESTROY, cave_va, HOOK_WIDTH)
        off = file_offset(data, TOGGLE_MOUNTED_RETIRE_DESTROY)
        got = bytes(data[off : off + HOOK_WIDTH])
        if got != want:
            problems.append(
                f"@0x{TOGGLE_MOUNTED_RETIRE_DESTROY:08x}: the retire does not jump to "
                f"{SECTION_NAME} (holds {got.hex()})"
            )
        return problems
