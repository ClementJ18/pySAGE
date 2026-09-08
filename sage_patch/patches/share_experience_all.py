"""Dispatch the original XP to every ShareExperienceBehavior on a ROTWK object.

The first-match getter stays intact; each recipient uses the original XP independently.
The code-only section is allocated after existing patches and located by name on
verification. No INI extension or persistent state is needed. Evidence and ABI are
documented in ``../docs/share-experience-all.md``.
"""

from __future__ import annotations

import struct

from ..addresses import (
    COORD3D_GET_LENGTH,
    EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS,
    FLOAT_ONE,
    OBJECT_MODULE_LIST,
    OBJECT_POSITION,
    SHARE_EXPERIENCE_CALC,
    SHARE_EXPERIENCE_CALC_BYTES,
    SHARE_EXPERIENCE_CALC_RESUME,
    SHARE_EXPERIENCE_DISPATCH,
    SHARE_EXPERIENCE_DISPATCH_BYTES,
    SHARE_EXPERIENCE_DROPOFF,
    SHARE_EXPERIENCE_GET_DROPOFF,
    SHARE_EXPERIENCE_GET_DROPOFF_BYTES,
    SHARE_EXPERIENCE_GET_DROPOFF_RESUME,
    SHARE_EXPERIENCE_INTERFACE,
    SHARE_EXPERIENCE_MODULEDATA,
    SHARE_EXPERIENCE_PERCENTAGE,
    SHARE_EXPERIENCE_QUERY_SLOT,
    SHARE_EXPERIENCE_RADIUS,
)
from ..asm import JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = ["SECTION_NAME", "ShareExperienceAllPatch"]

SECTION_NAME = ".sharexp"
# CNT_CODE | MEM_EXECUTE | MEM_READ: no runtime writes or persistent data.
_CHARACTERISTICS = 0x60000020


def _assemble_dispatch(base_va: int) -> bytes:
    """cdecl (Object*, float); each virtual ShareExperience call consumes its own float."""
    a = Asm(base_va)
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x45, 0x08)  # mov eax, [ebp+8]
    a.emit(0x8B, 0xB0, struct.pack("<I", OBJECT_MODULE_LIST))  # mov esi, [eax+0x24c]
    a.label("next")
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8D, 0x48, 0x0C)  # lea ecx, [eax+0xc]
    a.emit(0x8B, 0x11)  # mov edx, [ecx]
    a.emit(0xFF, 0x92, struct.pack("<I", SHARE_EXPERIENCE_QUERY_SLOT))  # call [edx+0xa4]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "advance")
    # Reload the original bits: ShareExperience may overwrite its own argument slot.
    a.emit(0xFF, 0x75, 0x0C)  # push dword [ebp+0xc]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0xFF, 0x12)  # call [edx] ; __thiscall, ret 4
    a.label("advance")
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4
    a.jmp("next")
    a.label("done")
    a.emit(0x5E)  # pop esi
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret
    return a.finish()


def _hook(section_va: int) -> bytes:
    a = Asm(SHARE_EXPERIENCE_DISPATCH)
    a.emit(0xFF, 0x75, 0x08)  # push dword [ebp+8] ; original XP bits
    a.emit(0x56)  # push esi ; Object*
    a.call_absolute(section_va)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    return a.finish().ljust(len(SHARE_EXPERIENCE_DISPATCH_BYTES), b"\x90")


def _assemble_scaling(base_va: int) -> bytes:
    """Private stack scratch preserves the argument and the stock float rounding points."""
    a = Asm(base_va)
    a.emit(0x51)  # push ecx ; private float slot, outside the SEH frame locals
    a.emit(b"\xd9\x45\x08")  # fld [ebp+8]
    a.emit(0xD8, 0x4F, SHARE_EXPERIENCE_PERCENTAGE)  # fmul [edi+Percentage]
    a.emit(b"\xd9\x1c\x24")  # fstp [esp]
    a.emit(b"\x8b\x4d\xec")  # mov ecx, [ebp-0x14]
    a.emit(0x83, 0xE9, SHARE_EXPERIENCE_INTERFACE)  # sub ecx, interface offset
    a.emit(b"\x56\x8d\x45\xbc\x50")  # push esi; lea eax,[ebp-0x44]; push eax
    a.call_absolute(SHARE_EXPERIENCE_GET_DROPOFF)
    a.emit(b"\xd8\x0c\x24\xd9\x1c\x24")  # fmul [esp]; fstp [esp]
    a.emit(b"\xd9\xee\xd9\x04\x24\xdf\xf1\xdd\xd8")  # stock positive XP test
    a.jcc(JBE, "done")
    a.emit(b"\xd9\x04\x24")  # fld [esp]
    a.emit(b"\x6a\x00\x6a\x01\x6a\x01\x6a\x01\x51")  # unchanged flags and XP slot
    a.emit(b"\x8b\x4d\xe8\xd9\x1c\x24")  # tracker; fstp [esp]
    a.call_absolute(EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS)
    a.label("done")
    a.emit(b"\x83\xc4\x04")  # discard only our scratch
    a.jmp_absolute(SHARE_EXPERIENCE_CALC_RESUME)
    return a.finish()


def _assemble_dropoff(base_va: int) -> bytes:
    """thiscall/ret 8, ST0 float; zero radius delegates to the untouched stock body."""
    a = Asm(base_va)
    a.emit(0x8B, 0x41, SHARE_EXPERIENCE_MODULEDATA)  # mov eax, [ecx+4]
    a.emit(b"\x0f\x57\xd2")  # xorps xmm2, xmm2
    a.emit(0x0F, 0x2E, 0x50, SHARE_EXPERIENCE_RADIUS)  # ucomiss xmm2, [eax+Radius]
    a.jcc(JNE, "normal")
    a.emit(SHARE_EXPERIENCE_GET_DROPOFF_BYTES[:6])  # original frame setup
    a.jmp_absolute(SHARE_EXPERIENCE_GET_DROPOFF_RESUME)
    a.label("normal")
    a.emit(b"\x55\x8b\xec\x83\xec\x0c\x56")  # frame, Coord3D, saved esi
    a.emit(b"\x8b\xf0")  # mov esi, eax
    a.emit(0xF3, 0x0F, 0x10, 0x46, SHARE_EXPERIENCE_DROPOFF)
    a.emit(b"\x0f\x2f\xc2")  # comiss xmm0, xmm2
    a.jcc(JBE, "one")  # zero strength avoids distance/radius entirely
    a.emit(b"\x8b\x45\x0c")  # recipient
    for opcode, offset in [(0x40, 0), (0x48, 4), (0x50, 8)]:
        a.emit(0xF3, 0x0F, 0x10, opcode, OBJECT_POSITION + offset)
    a.emit(b"\x8b\x45\x08")  # source
    a.emit(b"\xf3\x0f\x5c\x00\xf3\x0f\x5c\x48\x04\xf3\x0f\x5c\x50\x08")
    a.emit(b"\x8d\x4d\xf4")  # Coord3D temporary
    a.emit(b"\xf3\x0f\x11\x45\xf4\xf3\x0f\x11\x4d\xf8\xf3\x0f\x11\x55\xfc")
    a.call_absolute(COORD3D_GET_LENGTH)
    a.emit(b"\xd9\x5d\x0c\xf3\x0f\x10\x4d\x0c")  # stock distance rounding
    a.emit(0xF3, 0x0F, 0x5E, 0x4E, SHARE_EXPERIENCE_RADIUS)
    a.emit(b"\x0f\x57\xd2")  # zero
    a.emit(b"\xf3\x0f\x10\x05", struct.pack("<I", FLOAT_ONE))
    a.emit(b"\xf3\x0f\x5f\xca\xf3\x0f\x5d\xc8")  # ratio=max(ratio,0); min(ratio,1)
    a.emit(0xF3, 0x0F, 0x10, 0x5E, SHARE_EXPERIENCE_DROPOFF)
    a.emit(b"\xf3\x0f\x5f\xda\xf3\x0f\x5d\xd8")  # strength clamp
    a.emit(b"\xf3\x0f\x59\xcb\xf3\x0f\x5c\xc1")  # 1 - ratio * strength
    a.emit(b"\xf3\x0f\x11\x45\x0c\xd9\x45\x0c")  # ST0 result
    a.jmp("done")
    a.label("one")
    a.emit(b"\xd9\xe8")  # fld1
    a.label("done")
    a.emit(b"\x5e\xc9\xc2\x08\x00")
    return a.finish()


def _assemble(base_va: int) -> bytes:
    code = _assemble_dispatch(base_va)
    code += _assemble_scaling(base_va + len(code))
    return code + _assemble_dropoff(base_va + len(code))


def _windows(section_va: int) -> tuple[tuple[int, bytes, bytes], ...]:
    scaling = section_va + len(_assemble_dispatch(section_va))
    dropoff = scaling + len(_assemble_scaling(scaling))
    calc_hook = Asm(SHARE_EXPERIENCE_CALC).jmp_absolute(scaling).finish()
    drop_hook = Asm(SHARE_EXPERIENCE_GET_DROPOFF).jmp_absolute(dropoff).finish()
    return (
        (SHARE_EXPERIENCE_DISPATCH, SHARE_EXPERIENCE_DISPATCH_BYTES, _hook(section_va)),
        (
            SHARE_EXPERIENCE_CALC,
            SHARE_EXPERIENCE_CALC_BYTES,
            calc_hook.ljust(len(SHARE_EXPERIENCE_CALC_BYTES), b"\x90"),
        ),
        (
            SHARE_EXPERIENCE_GET_DROPOFF,
            SHARE_EXPERIENCE_GET_DROPOFF_BYTES,
            drop_hook + b"\x90" + SHARE_EXPERIENCE_GET_DROPOFF_BYTES[6:],
        ),
    )


def _offset(data: bytes | bytearray, address: int) -> int:
    off = va_to_offset(data, address)
    if off is None:
        raise ValueError(f"0x{address:08x} is not mapped - not the expected build")
    return off


class ShareExperienceAllPatch(Patch):
    """Evaluate all sharing behaviors, with independent recipient XP and percentage DropOff."""

    name = "share-experience-all"
    author = "Ostkannit"
    description = (
        "Give every ShareExperienceBehavior and recipient the original XP independently. "
        "DropOff is a clamped 0..1 falloff strength; 0 and 1 retain their stock semantics. "
        "Use distinct ModuleTags for multiple behaviors; no new INI fields are needed"
    )
    experimental = False

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for address, stock, _replacement in _windows(0):
            off = _offset(data, address)
            got = bytes(data[off : off + len(stock)])
            if got != stock:
                raise ValueError(
                    f"unexpected build at 0x{address:08x}: {got.hex()}, expected {stock.hex()}"
                )
        section_va = allocate_section(data, SECTION_NAME, _assemble, _CHARACTERISTICS)
        for address, stock, replacement in _windows(section_va):
            apply_byte_patch(data, _offset(data, address), stock, replacement, "ShareExperience")

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located
        problems: list[str] = []
        want = _assemble(section_va)
        if vsize < len(want):
            problems.append(f"{SECTION_NAME} is too small for the helpers")
        if bytes(data[section_off : section_off + len(want)]) != want:
            problems.append(f"the helper in {SECTION_NAME} is not the one this patch builds")
        for address, _stock, replacement in _windows(section_va):
            try:
                off = _offset(data, address)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if bytes(data[off : off + len(replacement)]) != replacement:
                problems.append(f"ShareExperience hook/body at 0x{address:08x} differs")
        return problems
