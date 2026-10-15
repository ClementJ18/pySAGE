"""Let a model name its texture with any extension, or none.

The texture getter looks the authored name up verbatim, and the asset cache indexes every texture
under its `.tga` name whatever file provides it - so a mesh that says `foo.dds` (or `foo.png`, or
`foo`) gets no texture while `foo.tga` works. A wrapper around the getter retries a name the cache
does not hold with its extension swapped for `.tga`, and hands the getter that name when the cache
holds it. A name the cache already knows, and one whose `.tga` twin it does not, go through
untouched.

Derivation: `../docs/texture-any-extension.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    ASSET_CACHE_HAS_ASSET,
    ASSET_CACHE_HAS_ASSET_BYTES,
    STRCPY,
    STRLEN,
    STRRCHR_SLOT,
    TEXTURE_EXTENSION_TGA,
    TEXTURE_EXTENSION_TGA_BYTES,
    TEXTURE_GET_BY_NAME,
    TEXTURE_GET_BY_NAME_BYTES,
    TEXTURE_GET_BY_NAME_RESUME,
)
from ..asm import JAE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32

__all__ = [
    "ANCHORS",
    "HOOK_WIDTH",
    "MAX_NAME_LENGTH",
    "SECTION_NAME",
    "STOCK_HOOK",
    "TextureAnyExtensionPatch",
    "build_code",
]

SECTION_NAME = ".texext"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: `mov eax, <EH handler>` - replaced by a `jmp` into the cave, which replays it before resuming.
HOOK_WIDTH = 5
STOCK_HOOK = TEXTURE_GET_BY_NAME_BYTES[:HOOK_WIDTH]

#: The wrapper's name buffer, and the longest name it rewrites: a name with no extension grows by
#: `.tga` and its terminator, and anything longer is left to the stock lookup.
_BUFFER = 0x10C
MAX_NAME_LENGTH = _BUFFER - 8

#: Every window the patch reads or relies on, as `{VA: stock bytes}`.
ANCHORS: dict[int, bytes] = {
    TEXTURE_GET_BY_NAME: TEXTURE_GET_BY_NAME_BYTES,
    ASSET_CACHE_HAS_ASSET: ASSET_CACHE_HAS_ASSET_BYTES,
    TEXTURE_EXTENSION_TGA: TEXTURE_EXTENSION_TGA_BYTES,
}

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

_BUFFER_DISP = struct.pack("<i", -_BUFFER)


def build_code(cave_va: int) -> bytes:
    """The getter's wrapper: `cdecl (out, name, a3, a4)`, the getter's own signature.

    It keeps a frame of its own because the substitute name has to outlive the stock body, which
    reads it more than once; the stock body is then *called* through a trampoline that replays
    the displaced `mov eax, <EH handler>`, and its `eax` (the `out` pointer) is returned as is.
    `esi` is the name handed on, `edi` the buffer; every helper is `cdecl` and keeps both."""
    a = Asm(cave_va)
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov  ebp, esp
    a.emit(b"\x81\xec", struct.pack("<I", _BUFFER))  # sub esp, 0x10c
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(b"\x8b\x75\x0c")  # mov  esi, [ebp+0xc]       ; the authored name
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "get")  # the getter answers a null name itself
    a.emit(0x56)  # push esi
    a.call_absolute(ASSET_CACHE_HAS_ASSET)
    a.emit(0x59)  # pop  ecx
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "get")  # the cache knows the name as written
    a.emit(0x56)  # push esi
    a.call_absolute(STRLEN)
    a.emit(0x59)  # pop  ecx
    a.emit(0x3D, struct.pack("<I", MAX_NAME_LENGTH))  # cmp eax, 0x104
    a.jcc(JAE, "get")  # no room for the name plus `.tga`
    a.emit(0x56)  # push esi
    a.emit(b"\x8d\xbd", _BUFFER_DISP)  # lea edi, [ebp-0x10c]
    a.emit(0x57)  # push edi
    a.call_absolute(STRCPY)
    a.emit(0x59, 0x59)  # pop ecx / pop ecx
    a.emit(b"\x6a\x2e")  # push '.'
    a.emit(0x57)  # push edi
    a.emit(b"\xff\x15", struct.pack("<I", STRRCHR_SLOT))  # call [strrchr]
    a.emit(0x59, 0x59)  # pop ecx / pop ecx
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JNE, "extension")
    a.emit(0x57)  # push edi                              ; no extension: append one
    a.call_absolute(STRLEN)
    a.emit(0x59)  # pop  ecx
    a.emit(b"\x03\xc7")  # add  eax, edi
    a.label("extension")
    a.emit(0x68, struct.pack("<I", TEXTURE_EXTENSION_TGA))  # push ".tga"
    a.emit(0x50)  # push eax                              ; over the extension, dot included
    a.call_absolute(STRCPY)
    a.emit(0x59, 0x59)  # pop ecx / pop ecx
    a.emit(0x57)  # push edi
    a.call_absolute(ASSET_CACHE_HAS_ASSET)
    a.emit(0x59)  # pop  ecx
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JE, "get")  # no `.tga` twin either: the authored name, as stock
    a.emit(b"\x8b\xf7")  # mov  esi, edi
    a.label("get")
    a.emit(b"\xff\x75\x14")  # push [ebp+0x14]
    a.emit(b"\xff\x75\x10")  # push [ebp+0x10]
    a.emit(0x56)  # push esi
    a.emit(b"\xff\x75\x08")  # push [ebp+8]
    a.call("stock")
    a.emit(b"\x83\xc4\x10")  # add  esp, 0x10
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0xC9, 0xC3)  # leave / ret
    a.label("stock")
    a.emit(STOCK_HOOK)  # mov  eax, <EH handler>          ; the instruction the hook displaced
    a.jmp_absolute(TEXTURE_GET_BY_NAME_RESUME)
    return a.finish()


class TextureAnyExtensionPatch(Patch):
    name = "texture-any-extension"
    author = "officialNecro"
    description = (
        "Let a model (or anything else that names a texture) reference it with any extension, or "
        "none: a name the asset cache does not hold is retried as <stem>.tga, the name asset.dat "
        "indexes every texture under whatever file provides it. So a mesh exported with foo.dds "
        "or foo.png gets its texture the way one written foo.tga does. A name the cache already "
        "knows is untouched. Client-side only. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_sites(data)
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            file_offset(data, TEXTURE_GET_BY_NAME),
            STOCK_HOOK,
            jmp_rel32(TEXTURE_GET_BY_NAME, cave_va, HOOK_WIDTH),
            "texture getter -> retry an unknown name as <stem>.tga",
        )

    @staticmethod
    def _check_sites(data: bytes | bytearray) -> None:
        """Raise unless the getter's head, the cache lookup and the `.tga` literal are stock: the
        cave resumes inside the first, calls the second and pushes the third."""
        for va, want in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                raise ValueError(
                    f"@0x{va:08x}: expected {want.hex()}, got {got.hex()} - the file is not the "
                    "expected build, or already carries this patch"
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
        want = jmp_rel32(TEXTURE_GET_BY_NAME, cave_va, HOOK_WIDTH)
        off = file_offset(data, TEXTURE_GET_BY_NAME)
        got = bytes(data[off : off + HOOK_WIDTH])
        if got != want:
            problems.append(
                f"@0x{TEXTURE_GET_BY_NAME:08x}: the texture getter does not jump to "
                f"{SECTION_NAME} (holds {got.hex()})"
            )
        return problems
