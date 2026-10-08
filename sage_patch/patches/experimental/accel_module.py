"""Initialize the native pySAGE accelerator on the engine's Direct3D resolve thread.

The optional companion is built from ``native/accelerator``. LoadLibrary only attaches it;
SageAccelInitialize performs installation outside the loader lock and returns a protocol result.
The cave preserves the engine's pointer, registers and flags on every outcome. Engine-address
hooks are disabled in this companion so that runtime installation cannot replace sage-patch edits.

Derived from OH1A's MIT-licensed BFME2 Accelerator; see ``docs/accel-module.md``.
"""

from __future__ import annotations

import struct

from ...addresses import (
    DIRECT3D_CREATE9_PTR,
    DIRECT3D_CREATE9_RESOLVE,
    DIRECT3D_CREATE9_RESOLVE_BYTES,
    DIRECT3D_CREATE9_STORE,
    DIRECT3D_CREATE9_STORE_ENTRY,
    DIRECT3D_CREATE9_STORE_RESUME,
    GET_PROC_ADDRESS_IAT,
    LOAD_LIBRARY_A_IAT,
)
from ...asm import JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "BLOCK_MAGIC",
    "CODE_OFFSET",
    "DLL_NAME",
    "INIT_NAME",
    "OFF_MODULE",
    "OFF_STATE",
    "SECTION_NAME",
    "STATE_LOADED",
    "STATE_INCOMPATIBLE",
    "STATE_INIT_FAILED",
    "STATE_NOT_REACHED",
    "STATE_NO_MODULE",
    "AccelModulePatch",
    "build_code",
    "hook_va",
]

SECTION_NAME = ".accel"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE - code, the DLL's name, and
# the state the hook records for a live reader.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: `'SACL'`, so the block is recognisable in a process without being told where it landed.
BLOCK_MAGIC = 0x4C434153

#: Looked up by `LoadLibraryA`'s normal search, which starts in the directory holding `game.dat`.
DLL_NAME = b"pysage_accel.dll\x00"
INIT_NAME = b"SageAccelInitialize\x00"

OFF_MAGIC = 0x00
#: What the hook found, as one of the `STATE_*` values; `sage_live` can read it to say why a game is
#: running without the accelerator.
OFF_STATE = 0x04
#: The module handle `LoadLibraryA` returned, or 0.
OFF_MODULE = 0x08
OFF_DLL_NAME = 0x10
OFF_INIT_NAME = 0x30
#: Where the code starts. Fixed, so the hook can address the block absolutely while it is still
#: being emitted.
CODE_OFFSET = 0x50

STATE_NOT_REACHED = 0
STATE_NO_MODULE = 1
STATE_LOADED = 2
STATE_INCOMPATIBLE = 3
STATE_INIT_FAILED = 4

#: What has to be true before the hook means anything: the resolve, the `cmp eax, ebx` whose flags
#: the `je` after the store reads, the store itself, and that `je`.
ANCHORS = {DIRECT3D_CREATE9_RESOLVE: DIRECT3D_CREATE9_RESOLVE_BYTES}


def _block() -> bytes:
    block = bytearray(CODE_OFFSET)
    struct.pack_into("<I", block, OFF_MAGIC, BLOCK_MAGIC)
    block[OFF_DLL_NAME : OFF_DLL_NAME + len(DLL_NAME)] = DLL_NAME
    block[OFF_INIT_NAME : OFF_INIT_NAME + len(INIT_NAME)] = INIT_NAME
    return bytes(block)


def _emit(base_va: int) -> Asm:
    a = Asm(base_va + CODE_OFFSET)
    a.label("hook")
    a.emit(0xA3, struct.pack("<I", DIRECT3D_CREATE9_PTR))  # the displaced store
    # The `je` at the resume reads the flags of the engine's `cmp eax, ebx`, so they and every
    # register go back exactly as they came.
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad
    a.emit(0x68, struct.pack("<I", base_va + OFF_DLL_NAME))  # push companion DLL name
    a.emit(0xFF, 0x15, struct.pack("<I", LOAD_LIBRARY_A_IAT))  # call [LoadLibraryA]
    a.emit(0xA3, struct.pack("<I", base_va + OFF_MODULE))  # mov [module], eax
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "no_module")
    a.emit(0x68, struct.pack("<I", base_va + OFF_INIT_NAME))
    a.emit(0x50)  # push module
    a.emit(0xFF, 0x15, struct.pack("<I", GET_PROC_ADDRESS_IAT))
    a.emit(0x85, 0xC0)
    a.jcc(JE, "incompatible")
    a.emit(0xFF, 0xD0)  # initialize on this engine thread, outside the loader lock
    a.emit(0x83, 0xF8, 0x01)  # protocol success is exactly 1
    a.jcc(JE, "ready")
    a.emit(0xC6, 0x05, struct.pack("<I", base_va + OFF_STATE), STATE_INIT_FAILED)
    a.jmp("done")
    a.label("incompatible")
    a.emit(0xC6, 0x05, struct.pack("<I", base_va + OFF_STATE), STATE_INCOMPATIBLE)
    a.jmp("done")
    a.label("ready")
    a.emit(0xC6, 0x05, struct.pack("<I", base_va + OFF_STATE), STATE_LOADED)
    a.jmp("done")
    a.label("no_module")
    a.emit(0xC6, 0x05, struct.pack("<I", base_va + OFF_STATE), STATE_NO_MODULE)
    a.label("done")
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    a.jmp_absolute(DIRECT3D_CREATE9_STORE_RESUME)
    return a


def build_code(base_va: int) -> bytes:
    """The whole section as it is written to the file: the block, then the hook."""
    return _block() + _emit(base_va).finish()


def hook_va(section_va: int) -> int:
    return _emit(section_va).label_va("hook")


class AccelModulePatch(Patch):
    name = "accel-module"
    author = "officialNecro"
    experimental = True
    # In-game smoke tested; extended stability and multiplayer remain unverified.
    runtime_verified = "partly"
    description = (
        "Initialize the pySAGE companion build of OH1A's BFME2 Accelerator (pysage_accel.dll) "
        "on the engine thread when it resolves Direct3DCreate9. "
        "Build the DLL from native/accelerator. "
        "Without the DLL the game runs as stock. The companion leaves fixed-address engine hooks "
        "off to preserve sage-patch edits. Parallel rendering is disabled by default pending "
        "driver validation. Experimental; client-local. No INI change"
    )

    @property
    def credit(self) -> str:
        return f"{super().credit}, loading a companion derived from OH1A's BFME2 Accelerator"

    def apply(self, data: bytearray) -> None:
        off = va_to_offset(data, DIRECT3D_CREATE9_STORE)
        if off is None:
            raise ValueError(
                f"{DIRECT3D_CREATE9_STORE:#010x} is not mapped - not the expected build"
            )
        self._check_anchors(data)

        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            off,
            DIRECT3D_CREATE9_STORE_ENTRY,
            b"\xe9" + struct.pack("<i", hook_va(section_va) - (DIRECT3D_CREATE9_STORE + 5)),
            "Direct3DCreate9 resolve -> accel-module hook",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "Direct3DCreate9 resolve is not the one this was written against"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        problems: list[str] = []

        off = va_to_offset(data, DIRECT3D_CREATE9_STORE)
        if off is None:
            problems.append(f"{DIRECT3D_CREATE9_STORE:#010x} is not mapped by any section")
        elif data[off] != 0xE9:
            problems.append(f"the hook at {DIRECT3D_CREATE9_STORE:#010x} is not a jmp")
        else:
            target = DIRECT3D_CREATE9_STORE + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != hook_va(section_va):
                problems.append(
                    f"the hook jumps to {target:#010x}, expected {hook_va(section_va):#010x}"
                )

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} section does not hold the expected block")
        return problems
