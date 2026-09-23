"""Load `sage_accel.dll` at the engine's `Direct3DCreate9` resolve and let it wrap the renderer.

The loader half of `../../docs/accel-module.md` (milestone M0): the engine resolves
`Direct3DCreate9` from `d3d9.dll` itself and stores it in `DIRECT3D_CREATE9_PTR` before first use.
A `.accel` cave takes over that store. It re-runs it, `LoadLibraryA`s `sage_accel.dll`, resolves
`sage_accel_arm`, and hands it the real pointer. Whatever non-null pointer comes back is what the
engine calls from then on. A missing DLL, a missing export or a NULL answer each leave the engine's
own pointer in place, so a patched `game.dat` without the module runs as stock.

This replaces the original accelerator's two ways of starting, and it is the reason the port can
compose with other patches: `bfme2_accel.dll` recognised its build by a checksum over the whole of
`.text` and, on a build it did not recognise, guessed the game thread from 64 effect calls
(`../../docs/accel-thread-identity.md` §3). Here the module is armed from one site, on the game
thread, and identifies that thread positively.

Derived from OH1A's `bfme2_accel.dll`, with his permission (`../../docs/accel-port.md` §4).
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
    "EXPORT_NAME",
    "OFF_MODULE",
    "OFF_STATE",
    "SECTION_NAME",
    "STATE_ARMED",
    "STATE_DECLINED",
    "STATE_NO_EXPORT",
    "STATE_NO_MODULE",
    "STATE_NOT_REACHED",
    "AccelModulePatch",
    "build_code",
    "hook_va",
]

SECTION_NAME = ".accel"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE - code, two names, and the
# state the hook records for a live reader.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: `'SACL'`, so the block is recognisable in a process without being told where it landed.
BLOCK_MAGIC = 0x4C434153

#: Looked up by `LoadLibraryA`'s normal search, which starts in the directory holding `game.dat`.
#: Must match `sage_accel.build.DLL_NAME`; a test checks the two agree.
DLL_NAME = b"sage_accel.dll\x00"
EXPORT_NAME = b"sage_accel_arm\x00"

OFF_MAGIC = 0x00
#: What the hook found, as one of the `STATE_*` values; `sage_live` can read it to say why a game is
#: running without the module.
OFF_STATE = 0x04
#: The module handle `LoadLibraryA` returned, or 0.
OFF_MODULE = 0x08
OFF_DLL_NAME = 0x10
OFF_EXPORT_NAME = 0x20
#: Where the code starts. Fixed, so the hook can address the block absolutely while it is still
#: being emitted.
CODE_OFFSET = 0x30

STATE_NOT_REACHED = 0
STATE_NO_MODULE = 1
STATE_NO_EXPORT = 2
#: The module was asked and returned NULL: it is switched off (`sage_accel.off`), or the engine
#: resolved no `Direct3DCreate9` to wrap.
STATE_DECLINED = 3
STATE_ARMED = 4

#: What has to be true before the hook means anything: the resolve, the `cmp eax, ebx` whose flags
#: the `je` after the store reads, the store itself, and that `je`.
ANCHORS = {DIRECT3D_CREATE9_RESOLVE: DIRECT3D_CREATE9_RESOLVE_BYTES}


def _block() -> bytes:
    block = bytearray(CODE_OFFSET)
    struct.pack_into("<I", block, OFF_MAGIC, BLOCK_MAGIC)
    block[OFF_DLL_NAME : OFF_DLL_NAME + len(DLL_NAME)] = DLL_NAME
    block[OFF_EXPORT_NAME : OFF_EXPORT_NAME + len(EXPORT_NAME)] = EXPORT_NAME
    return bytes(block)


def _emit(base_va: int) -> Asm:
    state = base_va + OFF_STATE

    def set_state(value: int) -> None:
        a.emit(0xC6, 0x05, struct.pack("<I", state), value)  # mov byte [state], value

    a = Asm(base_va + CODE_OFFSET)
    a.label("hook")
    a.emit(0xA3, struct.pack("<I", DIRECT3D_CREATE9_PTR))  # the displaced store
    # The `je` at the resume reads the flags of the engine's `cmp eax, ebx`, so they and every
    # register go back exactly as they came.
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad

    a.emit(0x68, struct.pack("<I", base_va + OFF_DLL_NAME))  # push "sage_accel.dll"
    a.emit(0xFF, 0x15, struct.pack("<I", LOAD_LIBRARY_A_IAT))  # call [LoadLibraryA]
    a.emit(0xA3, struct.pack("<I", base_va + OFF_MODULE))  # mov [module], eax
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "no_module")

    a.emit(0x68, struct.pack("<I", base_va + OFF_EXPORT_NAME))  # push "sage_accel_arm"
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x15, struct.pack("<I", GET_PROC_ADDRESS_IAT))  # call [GetProcAddress]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "no_export")

    a.emit(0xFF, 0x35, struct.pack("<I", DIRECT3D_CREATE9_PTR))  # push [Direct3DCreate9]
    a.emit(0xFF, 0xD0)  # call eax        ; void *__cdecl sage_accel_arm(void *real)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "declined")
    a.emit(0xA3, struct.pack("<I", DIRECT3D_CREATE9_PTR))  # mov [Direct3DCreate9], eax
    set_state(STATE_ARMED)
    a.jmp("done")

    a.label("no_module")
    set_state(STATE_NO_MODULE)
    a.jmp("done")
    a.label("no_export")
    set_state(STATE_NO_EXPORT)
    a.jmp("done")
    a.label("declined")
    set_state(STATE_DECLINED)

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
    runtime_verified = "partly"  # M0 armed in Edain on 2026-09-24; the M1 census is unplayed
    description = (
        "Load sage_accel.dll from the game directory when the engine resolves Direct3DCreate9, "
        "and let it wrap the renderer. The module is built with `python -m sage_accel build` and "
        "copied beside game.dat with `python -m sage_accel install`; without it, or with a "
        "sage_accel.off file beside it, the game runs as stock. Milestone M1: the module counts "
        "every Direct3D device, effect and lock call and writes a report to sage_accel.log every "
        "30 s, changing nothing. Derived from OH1A's bfme2_accel.dll. Client-local. No INI change"
    )

    @property
    def credit(self) -> str:
        return f"{super().credit}, derived from OH1A's bfme2_accel.dll"

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
