"""Let an upgrade reference carry a descriptive suffix after `@` that the engine ignores:
`Upgrade_TestBuilding@SmithyLevel2` is `Upgrade_TestBuilding`.

A mod near the upgrade-bit ceiling reuses generic upgrades as object-local flags, and the names say
nothing about intent. `UpgradeCenter::findUpgrade` is hooked to resolve a name only up to an
interior `@`; unaliased names cost nothing. On a stock binary such data does not load.

Derivation: `../docs/upgrade-alias.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    NAME_KEY_FROM_CSTR,
    THE_NAME_KEY_GENERATOR,
    UPGRADE_CENTER_FIND_UPGRADE,
    UPGRADE_CENTER_FIND_UPGRADE_BY_KEY,
    UPGRADE_CENTER_FIND_UPGRADE_BY_KEY_ENTRY,
    UPGRADE_CENTER_FIND_UPGRADE_ENTRY,
    UPGRADE_CENTER_FIND_UPGRADE_RESUME,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, u32, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "SEPARATOR",
    "UpgradeAliasPatch",
    "build_code",
]

SECTION_NAME = ".upgali"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: The separator, `@`. Shared with `sage_ini.model.aliases.ALIAS_SEPARATOR`, which is the
#: linter's copy of this same rule - the two must spell the character the same way or the linter
#: would accept names this engine rejects.
SEPARATOR = 0x40

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = UPGRADE_CENTER_FIND_UPGRADE
HOOK_ORIGINAL = UPGRADE_CENTER_FIND_UPGRADE_ENTRY

#: The first instruction at each address the cave jumps to or calls, as a `{va: bytes}` map. The
#: hooked five bytes are asserted by `apply_byte_patch`; these are the resume point inside the
#: stock body and the two helpers the aliased path calls. A build whose layout moved fails here
#: instead of hashing through a wild call.
ANCHORS = {
    # `mov esi, ecx` - where the stock body continues once the prologue is reproduced.
    UPGRADE_CENTER_FIND_UPGRADE_RESUME: bytes.fromhex("8bf1"),
    # `mov eax, 0xb7a847` - the SEH prologue of `nameToKey(const char *)`.
    NAME_KEY_FROM_CSTR: bytes.fromhex("b847a8b700"),
    UPGRADE_CENTER_FIND_UPGRADE_BY_KEY: UPGRADE_CENTER_FIND_UPGRADE_BY_KEY_ENTRY,
}


def build_code(base_va: int) -> bytes:
    """The alias-aware `findUpgrade`. Entered by the hook with `ecx` holding the `UpgradeCenter`,
    the return address at `[esp]` and the `const AsciiString *` at `[esp+4]`, exactly as the stock
    function is entered. Both paths end the call themselves, so nothing returns here."""
    a = Asm(base_va)
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]     ; the AsciiString
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "stock")  # no string at all: stock handles it
    a.emit(0x8B, 0x00)  # mov eax, [eax]       ; its buffer, NULL when empty
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "stock")  # empty: stock substitutes the "" literal
    a.emit(0x83, 0xC0, 0x08)  # add eax, 8           ; -> the chars
    a.emit(0x80, 0x38, 0x00)  # cmp byte [eax], 0
    a.jcc(JE, "stock")

    # Scan for a separator, starting at the *second* character: a leading `@` is the create-a-hero
    # default-bling marker and must reach the stock lookup spelled exactly as written.
    a.emit(0x8B, 0xD0)  # mov edx, eax         ; the cursor
    a.label("scan")
    a.emit(0x42)  # inc edx
    a.emit(0x80, 0x3A, 0x00)  # cmp byte [edx], 0
    a.jcc(JE, "stock")  # ran out of name: no alias
    a.emit(0x80, 0x3A, SEPARATOR)  # cmp byte [edx], '@'
    a.jcc(JNE, "scan")

    # An interior separator. Hash the name up to it and look that key up - the same two calls the
    # stock body makes, but keyed off the raw chars so the suffix never reaches the generator.
    # `ebx` and `esi` are callee-saved here (the stock function preserves `esi` the same way) and
    # both survive `nameToKey`, which saves them itself.
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xF1)  # mov esi, ecx         ; the UpgradeCenter
    a.emit(0x8B, 0xDA)  # mov ebx, edx         ; where the separator sits
    a.emit(0xC6, 0x03, 0x00)  # mov byte [ebx], 0    ; truncate in place
    a.emit(0x50)  # push eax             ; the truncated chars
    a.emit(0x8B, 0x0D, u32(THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
    a.call_absolute(NAME_KEY_FROM_CSTR)  # nameToKey(const char *)   ; ret 4
    a.emit(0xC6, 0x03, SEPARATOR)  # mov byte [ebx], '@'  ; put the name back
    a.emit(0x50)  # push eax             ; the key
    a.emit(0x8B, 0xCE)  # mov ecx, esi         ; the UpgradeCenter
    a.call_absolute(UPGRADE_CENTER_FIND_UPGRADE_BY_KEY)  # -> the template, or NULL ; ret 4
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4

    # No separator: reproduce the two instructions the hook overwrote and rejoin the stock body.
    a.label("stock")
    a.emit(0x56)  # push esi
    a.emit(0xFF, 0x74, 0x24, 0x08)  # push dword [esp+8]   ; the AsciiString
    a.jmp_absolute(UPGRADE_CENTER_FIND_UPGRADE_RESUME)
    return a.finish()


class UpgradeAliasPatch(Patch):
    name = "upgrade-alias"
    author = "officialNecro"
    description = (
        "Resolve an upgrade reference only up to an interior '@', so a reused generic upgrade "
        "can carry a descriptive intent per use. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "UpgradeCenter::findUpgrade -> upgrade-alias cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the upgrade "
                    "lookup's layout is not this build's, so the cave would rejoin the stock "
                    "body in the wrong place or hash through the wrong helper"
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
            problems.append(f"the {SECTION_NAME} cave does not hold the expected lookup")
        return problems
