"""The campaign-select patch: let the main menu start **any** `LinearCampaign`, by name.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below comes
from :mod:`sage_patch.addresses` and is derived in ``../docs/campaign-select.md``.

**The gap.** A ROTWK shell can start exactly the campaigns EA compiled into it. `Campaign.ini`
says so out loud - *"campaign names are basically hard-coded into the game engine. It would be
nice to pull them from the flash file or something but... we don't. They must be named
ANGMAR_CAMPAIGN"* - and the binary agrees: the menu's two campaign buttons reach two callbacks
that differ only in a screen id, and each id reaches a thunk holding one string literal. A mod
that ships three campaigns has two buttons for them.

**Only the name is hardcoded, though.** Everything under it is generic. The start itself
(`0x0091B1D2`) takes an `AsciiString *`, resolves it through `TheCampaignManager` and returns
without doing anything if the name is unknown - so any `LinearCampaign` block in INI is already
reachable, if you can say its name. Saying it is the whole patch.

**Where the name is said.** Case 13's thunk builds its `AsciiString` once, into a function-local
static, behind an MSVC magic-static guard::

    0091BE96  test byte ptr [CAMPAIGN_NAME_STATIC_GUARD], 1
    0091BE9D  push esi
    0091BE9E  mov  esi, CAMPAIGN_NAME_STATIC     ; loaded whether or not the branch is taken
    0091BEA3  jne  0091BECA                      ; already initialised -> on to the start
    ...                                          ; the only path the literal takes
    0091BED4  push esi                           ; -> startLinearCampaign

Set that static and its guard bit and the literal never runs. The thunk, the 14-entry jump table
it hangs off, and the callback registry are all untouched - which is why this is one detour and
not a table relocation plus a new FSCommand registration.

**What it does.** Replaces the first five bytes of `AptMainMenu::Expansion1Campaign`
(`MAIN_MENU_CAMPAIGN_HANDLER`) with a `jmp` into a cave that does everything the stock callback
did - phase, screen id, and the difficulty byte it takes from `params[0]` - and then reads the
*rest* of the params string, which the stock callback discards:

    ``GameCode("Expansion1Campaign", "Hard:DWARVEN_CAMPAIGN")``

Byte 0 is still the difficulty, exactly as before. Everything after the first ``:`` is the
campaign name, copied into the cave (63 chars max) and installed in the static.

**A params string with no ``:`` is left completely alone** - no copy, no static, no guard - so a
stock `.apt` sending ``"Easy"`` / ``"Medium"`` / ``"Hard"`` gets stock `ANGMAR_CAMPAIGN`
behaviour, including the `_DEMO` variant the thunk picks. The patch adds a channel; it does not
take one away.

**Consequence worth knowing.** Once a name has been installed, the guard stays set for the life of
the process, so the between-missions screen's own route into case 13 (`0x009C506F`) continues
whichever campaign was started rather than reverting to `ANGMAR_CAMPAIGN`. That is what you want,
and it is why the `.apt` should send a name on *every* campaign button rather than mixing the two
forms - a stock-form press after a named one runs the previously named campaign.

> **Shell-only and client-local.** Nothing here is in the simulation: the patch runs on a main-menu
> button press, before a game exists, and writes one string. It is not CRC'd, it does not cross the
> network and replays cross unpatched builds. Same rule as `replay-outcome` and `observer-switch`.

**Composition.** Order-independent. It appends its own section with
:func:`~sage_patch.utils.allocate_section`, the five bytes it edits are touched by no other
bundled patch, and it reads nothing another patch rewrites.

**The one leak.** Filling the static ourselves skips the `atexit` registration the stock
initialiser does at `0x0091BEC0`, so the last campaign name allocated is never freed. It is one
`AsciiString` buffer, released by the OS at process exit.
"""

from __future__ import annotations

import struct

from ...addresses import (
    ASCII_STRING_SET,
    ASCII_STRING_SET_BYTES,
    CAMPAIGN_NAME_BIND,
    CAMPAIGN_NAME_BIND_BYTES,
    CAMPAIGN_NAME_STATIC,
    CAMPAIGN_NAME_STATIC_GUARD,
    MAIN_MENU_CAMPAIGN_HANDLER,
    MAIN_MENU_CAMPAIGN_HANDLER_BYTES,
    MAIN_MENU_CAMPAIGN_REGISTRATION,
    MAIN_MENU_CAMPAIGN_REGISTRATION_BYTES,
    MAIN_MENU_CAMPAIGN_SELECTION_ID,
    MAIN_MENU_PHASE_LEAVING,
    MAIN_MENU_SCREEN_DIFFICULTY,
    MAIN_MENU_SCREEN_PHASE,
    MAIN_MENU_SCREEN_SELECTION,
)
from ...asm import JB, JE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "CODE_OFF",
    "NAME_CAPACITY",
    "NAME_OFF",
    "SEPARATOR",
    "SECTION_NAME",
    "CampaignSelectPatch",
    "build_code",
    "campaign_of",
    "params",
]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = ".cmpsel"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Unlike most caves here
# this one is written at *runtime* - the name buffer below the code is filled on every campaign
# button press - so it cannot be read-only.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The name buffer sits at the bottom of the section and the code above it, so the code's
#: addresses do not move when the buffer's size is reasoned about.
NAME_OFF = 0x00
#: 63 characters plus the terminator. `LinearCampaign` block names in the shipped INI are 15-21
#: characters; this is room for three times the longest and still one cache line.
NAME_CAPACITY = 0x40
CODE_OFF = NAME_OFF + NAME_CAPACITY

#: What divides the difficulty from the campaign name in the FSCommand's params string. Not a
#: parameter: it is half of a contract with the `.apt`, and a build whose engine and movie
#: disagreed about it would fail by silently starting the wrong campaign.
SEPARATOR = ":"


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def params(difficulty: str, campaign: str = "") -> str:
    """The params string the `.apt` passes to ``GameCode("Expansion1Campaign", …)``.

    ``difficulty`` is the stock word (``"Easy"`` / ``"Medium"`` / ``"Hard"``) - the engine reads
    only its first character, before and after this patch. Passing no ``campaign`` returns exactly
    what a stock movie sends, which the patched callback leaves alone.
    """
    if SEPARATOR in difficulty:
        raise ValueError(f"the difficulty word may not contain {SEPARATOR!r}: {difficulty!r}")
    return f"{difficulty}{SEPARATOR}{campaign}" if campaign else difficulty


def campaign_of(text: str) -> str:
    """The campaign name the cave would take out of ``text``, or ``""`` for "leave the static
    alone" - the parse rule in Python, so the tests can state it once and assert the emitted code
    against the same one.

    Everything after the **first** separator, truncated to what the buffer holds. An absent
    separator and an empty tail are the same answer, because the cave treats them the same way:
    both mean the movie did not name a campaign.
    """
    head, found, tail = text.partition(SEPARATOR)
    if not found:
        return ""
    return tail[: NAME_CAPACITY - 1]


def build_code(code_va: int, name_va: int) -> bytes:
    """The replacement callback, assembled to run at ``code_va`` with its buffer at ``name_va``.

    Entered by the `jmp` that replaced the callback's first five bytes, so on entry `ecx` is the
    `AptMainMenu`, `[esp]` is the caller's return address and `[esp+4]` is the params string - and
    the `ret 4` at the bottom returns the way the stock callback did.

    Only `eax`, `ecx` and `edx` are used, which are the three the stock callback already clobbers;
    nothing callee-saved is touched, so there is no prologue and no frame.
    """
    a = Asm(code_va)

    # --- the stock callback, instruction for instruction ---
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]         ; params
    # mov dword ptr [ecx+MAIN_MENU_SCREEN_PHASE], MAIN_MENU_PHASE_LEAVING
    a.emit(0xC7, 0x81, _u32(MAIN_MENU_SCREEN_PHASE), _u32(MAIN_MENU_PHASE_LEAVING))
    # mov dword ptr [ecx+MAIN_MENU_SCREEN_SELECTION], MAIN_MENU_CAMPAIGN_SELECTION_ID
    a.emit(0xC7, 0x81, _u32(MAIN_MENU_SCREEN_SELECTION), _u32(MAIN_MENU_CAMPAIGN_SELECTION_ID))
    a.emit(0x8A, 0x10)  # mov dl, [eax]            ; the difficulty letter
    a.emit(0x88, 0x91, _u32(MAIN_MENU_SCREEN_DIFFICULTY))  # mov [ecx+0x2A8], dl

    # `dl` is still the first character, so an empty params string is one test rather than a
    # second load. The stock callback dereferences `eax` unconditionally too, so a NULL params
    # faults here exactly where it faulted before - no new failure mode, and no new check.
    a.emit(0x84, 0xD2)  # test dl, dl
    a.jcc(JE, "done")

    # --- find the separator ---
    a.emit(0x8B, 0xD0)  # mov edx, eax             ; scan cursor
    a.label("scan")
    a.emit(0x8A, 0x0A)  # mov cl, [edx]
    a.emit(0x42)  # inc edx                  ; past the character just read
    a.emit(0x84, 0xC9)  # test cl, cl
    a.jcc(JE, "done")  # end of string, no separator -> stock behaviour
    a.emit(0x80, 0xF9, ord(SEPARATOR))  # cmp cl, ':'
    a.jcc(JNE, "scan")
    a.emit(0x80, 0x3A, 0x00)  # cmp byte ptr [edx], 0
    a.jcc(JE, "done")  # "Hard:" names nothing -> stock behaviour

    # --- copy the name, bounded by the destination rather than by a counter ---
    a.emit(0xB8, _u32(name_va))  # mov eax, <buffer>
    a.label("copy")
    a.emit(0x8A, 0x0A)  # mov cl, [edx]
    a.emit(0x88, 0x08)  # mov [eax], cl            ; the terminator is copied too
    a.emit(0x84, 0xC9)  # test cl, cl
    a.jcc(JE, "installed")
    a.emit(0x42)  # inc edx
    a.emit(0x40)  # inc eax
    a.emit(0x3D, _u32(name_va + NAME_CAPACITY - 1))  # cmp eax, <last byte of the buffer>
    a.jcc(JB, "copy")
    a.emit(0xC6, 0x00, 0x00)  # mov byte ptr [eax], 0    ; truncate, still terminated

    # --- install it as the campaign the start thunk will read ---
    a.label("installed")
    a.emit(0xB9, _u32(CAMPAIGN_NAME_STATIC))  # mov ecx, <the static AsciiString>
    a.emit(0x68, _u32(name_va))  # push <buffer>
    a.call_absolute(ASCII_STRING_SET)  # `ret 4`: cleans its own argument
    a.emit(0x83, 0x0D, _u32(CAMPAIGN_NAME_STATIC_GUARD), 0x01)  # or dword ptr [guard], 1

    a.label("done")
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a.finish()


def build_section(base_va: int) -> bytes:
    """The cave: the zeroed name buffer, then the code that fills it."""
    return b"\x00" * NAME_CAPACITY + build_code(base_va + CODE_OFF, base_va + NAME_OFF)


#: The sites that have to still hold their stock bytes for the patch to mean what it says, by
#: address. The callback's own first five bytes are *not* among them - those are the edit - but its
#: tail is, because that is where the screen id the cave re-emits is stated.
ANCHORS = {
    MAIN_MENU_CAMPAIGN_REGISTRATION: MAIN_MENU_CAMPAIGN_REGISTRATION_BYTES,
    CAMPAIGN_NAME_BIND: CAMPAIGN_NAME_BIND_BYTES,
    ASCII_STRING_SET: ASCII_STRING_SET_BYTES,
}

#: How many of the callback's bytes the `jmp` takes over. The other 30 are left as they were:
#: unreachable, and a fingerprint `verify` can still read.
_DETOUR_LEN = 5


class CampaignSelectPatch(Patch):
    name = "campaign-select"
    author = "officialNecro"
    experimental = True
    description = (
        "Let the main menu start any LinearCampaign by name - the campaign button's FSCommand "
        "params carry '<Difficulty>:<CAMPAIGN_NAME>' instead of only a difficulty"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        self._check_handler(data)

        off = va_to_offset(data, MAIN_MENU_CAMPAIGN_HANDLER)
        if off is None:
            raise ValueError(
                f"{MAIN_MENU_CAMPAIGN_HANDLER:#010x} is not mapped - not the expected build"
            )
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        code_va = section_va + CODE_OFF
        jump = b"\xe9" + struct.pack("<i", code_va - (MAIN_MENU_CAMPAIGN_HANDLER + _DETOUR_LEN))
        apply_byte_patch(
            data,
            off,
            MAIN_MENU_CAMPAIGN_HANDLER_BYTES[:_DETOUR_LEN],
            jump,
            "AptMainMenu::Expansion1Campaign -> the callback that reads the campaign name",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the campaign "
                    "start path is not this build's"
                )

    @staticmethod
    def _check_handler(data: bytes | bytearray) -> None:
        """Raise unless the callback's **tail** - everything the `jmp` does not cover - is still
        stock. That is where the screen id and the difficulty store are written down, which is what
        the cave reproduces; the first five bytes are deliberately excluded so this one check can
        serve :meth:`apply` and :meth:`verify` alike."""
        off = va_to_offset(data, MAIN_MENU_CAMPAIGN_HANDLER)
        if off is None:
            raise ValueError(
                f"{MAIN_MENU_CAMPAIGN_HANDLER:#010x} is not mapped - not the expected build"
            )
        expected = MAIN_MENU_CAMPAIGN_HANDLER_BYTES[_DETOUR_LEN:]
        got = bytes(data[off + _DETOUR_LEN : off + len(MAIN_MENU_CAMPAIGN_HANDLER_BYTES)])
        if got != expected:
            raise ValueError(
                f"{MAIN_MENU_CAMPAIGN_HANDLER + _DETOUR_LEN:#010x} is {got.hex()}, expected "
                f"{expected.hex()} - this is not the campaign callback this patch replaces"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"the {SECTION_NAME} section is absent - not installed"]
        section_va, section_off, _ = located
        code_va = section_va + CODE_OFF

        off = va_to_offset(data, MAIN_MENU_CAMPAIGN_HANDLER)
        if off is None:
            return [f"{MAIN_MENU_CAMPAIGN_HANDLER:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            problems.append(
                f"{MAIN_MENU_CAMPAIGN_HANDLER:#010x} is not a jmp - the callback is unpatched"
            )
        else:
            rel = struct.unpack_from("<i", data, off + 1)[0]
            target = MAIN_MENU_CAMPAIGN_HANDLER + _DETOUR_LEN + rel
            if target != code_va:
                problems.append(
                    f"the campaign callback jumps to {target:#010x}, expected {code_va:#010x}"
                )

        expected = build_code(code_va, section_va + NAME_OFF)
        got = bytes(data[section_off + CODE_OFF : section_off + CODE_OFF + len(expected)])
        if got != expected:
            problems.append(f"the {SECTION_NAME} cave does not hold this patch's code")

        try:
            self._check_anchors(data)
            self._check_handler(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems
