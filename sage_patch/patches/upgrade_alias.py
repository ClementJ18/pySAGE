"""The upgrade-alias patch: let an upgrade *reference* carry a descriptive suffix the engine
ignores, so a reused generic upgrade says what each use of it means.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/upgrade-alias.md``.

**The problem.** Upgrades are a fixed global bit space - 1152 bits, and nothing bounds-checks the
allocator (see `upgrade-mask-limit.md`). A mod near the ceiling reuses a handful of generic
upgrades as object-local flags, so `Upgrade_TestBuilding` gates a tent's banner on one object and
something wholly unrelated on the next. The names carry no intent, two uses of one bit on a single
object silently drive each other, and the collision is invisible in the text.

**What this does.** Hooks `UpgradeCenter::findUpgrade` and resolves a name only up to an interior
``@``, so `Upgrade_TestBuilding@SmithyLevel2` and `Upgrade_TestBuilding@GateOpen` are the same
upgrade to the engine and two different intents to a reader and to `sage_lint`.

**Why this function and not the INI parser.** `findUpgrade` is the one place a *name* becomes an
`UpgradeTemplate`, with 84 direct callers. Hooking it covers the INI mask parser
(`parseUpgradeMask`), the scalar `Upgrade =` fields, the Lua bindings - `ObjectGrantUpgrade`'s
handler reaches it at ``0x00736E6C`` through the shared grant/remove helper, and `ObjectHasUpgrade`
shares that helper - and the map-script actions at ``0x0073AFBE`` and ``0x0073B04B``. One hook,
every name source, with no per-parser work and nothing to keep in step as new sources appear.

**Why the separator must be interior.** A *leading* ``@`` is already meaningful: create-a-hero
bling lists mark their default option with one (`BlingUpgrades = @Upgrade_NoHelmet Upgrade_...`).
Truncating those at position zero would hash the empty string and break every create-a-hero
default, so the scan starts at the second character and a bare ``@Name`` is left exactly as the
stock code would see it. Every other ``@`` in the base game data sits inside a comment.

**The unaliased path costs nothing.** A name with no interior ``@`` falls through to a reproduced
prologue and a jump back into the stock body, so the 5368 upgrade reference tokens the base game
already has take a string scan and nothing else - no allocation, no extra call.

**Writing into the string is safe.** The aliased path writes a NUL over the ``@``, hashes, and
puts the byte back before it returns. The buffer is the `AsciiString`'s heap allocation (chars at
``+8``), so it is writable; `nameToKey` neither yields nor calls back into game code, so nothing
observes the gap; and when the key is new, the intern path copies the name through
`ASCII_STRING_SET` at ``0x00548888`` rather than keeping the pointer, so the entry it creates is
unaffected by the restore.

**Determinism.** The truncation is a pure function of the name, applied identically on every peer
before any logic reads the result, so an aliased reference is network- and replay-safe. Upgrade
mask *indices* are assigned in INI load order and are unchanged by this patch: an alias creates no
new upgrade and consumes no bit, which is the entire point.

**On a stock binary the data does not run.** An aliased name is an unknown upgrade. In INI that is
a fatal load error (`"An upgrade mask references %s, which is not an Upgrade"` at ``0x00C10C90``);
from Lua or a map script the handler returns zero and silently does nothing. The silent form is
the dangerous one, so a mod that adopts aliases in scripts ships this patch or does not run.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the five at
`UPGRADE_CENTER_FIND_UPGRADE`, which no bundled patch touches - `spell-store-upgrade` and
`upgrade-grant-lists` both *call* that address from their own caves and edit neither it nor
anything it reads, so both inherit alias resolution for free rather than conflicting with it.

**No INI surface change.** This adds no keyword and moves no ceiling; it widens what an existing
field's *value* may spell. `sage_ini` implements the same split in
:mod:`sage_ini.model.aliases` and applies it unconditionally, so the linter agrees with a patched
engine without being told which binary the data is destined for.
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
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

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


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


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
    a.emit(0x8B, 0x0D, _u32(THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
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
