"""Per-player `DisabledFactions`: let a War of the Ring scenario say which faction each lobby
slot may take, instead of only which factions the scenario as a whole allows.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/scenario-player-factions.md``.

**The limitation.** A `LivingWorldCampaign`'s `Scenario` block can disable factions, and with
``HistoricalScenario = Yes`` the engine additionally requires every player to take a *different*
one. What it cannot say is **who** takes which. `Scenario::isFactionEnabled` answers a question
about the scenario - "is this faction allowed here" - and takes no player, so a scripted scenario
that needs player 1 to be Angmar and player 2 to be Men can only narrow the pool to those two and
hope. With three players and five allowed factions it cannot even do that.

`StartingRestriction` looks like the missing piece and is not: its `Factions` list *is* consulted
as a per-start-region filter, but only when `HistoricalScenario` is **off** - the fill of the
faction combo box skips that filter outright for a historical scenario, which is the only kind of
scenario that pins factions to regions in the first place.

**What this does.** Extends the *value* syntax of the existing `DisabledFactions` keyword with an
optional ``:N`` player qualifier, and teaches every reader of the list to honour it:

    DisabledFactions = FactionArnor FactionElves FactionMen:1 FactionAngmar:2

An entry with no qualifier stays scenario-wide and behaves exactly as it does today. An entry
written ``Faction...:N`` disables that faction **for lobby slot N only**, counting from 1, and is
invisible to every other slot. So the line above bars Arnor and the Elves from everyone, leaves
slot 1 unable to take Men and slot 2 unable to take Angmar, and - in an otherwise two-faction
scenario - pins slot 1 to Angmar and slot 2 to Men.

No new keyword and no new storage: the qualifier rides in the `AsciiString` vector the stock
parser already builds, which is why this patch touches no INI field table and nothing about a
scenario written before it changes meaning.

**Where it takes effect.** `Scenario::isFactionEnabled` has exactly four callers, all inside the
multiplayer game-setup screen, and the patch redirects all four:

* the **combo box fill**, which is what a player sees - a faction refused for their slot is greyed
  and made unselectable, exactly as a scenario-wide disabled one already is;
* the **start-game gate**, which raises ``GUI:DisabledFaction`` and refuses to start;
* the **historical-scenario validation pass**, which rejects a slot's pick; and
* the **Random resolution pass**, which picks a faction for a slot left on Random - so Random in a
  pinned slot resolves to something that slot is allowed to have.

Redirecting all four is what makes the rule a rule rather than a UI hint: the host cannot start a
game that violates it however the slot came to hold that faction.

**How the slot reaches a function that has no parameter for it.** Each of the four call sites
already holds the lobby slot index it is asking about, in an `ebp`-relative local that is live and
unwritten at the call. So each site's five-byte `call` is redirected to its own two-instruction
trampoline in the cave, which loads that local into `edx` and tail-jumps into the shared
replacement. Nothing on the stack moves: the replacement keeps the stock `__thiscall` signature and
its `ret 4`, and - like the function it replaces - destroys the by-value `AsciiString` argument it
is handed.

**Case sensitivity is preserved.** The stock comparison bottoms out in `memcmp`, not `_memicmp`, so
`DisabledFactions` has always been case-*sensitive* and the replacement is too. A patch that
quietly made it case-insensitive would start disabling factions in scenarios that were relying on
the stock behaviour, which is the sort of change that looks like a fix until it is a bug report.

**Malformed qualifiers are ignored, not guessed at.** A bare trailing ``:``, a non-numeric
qualifier and ``:0`` all leave the entry applying to nobody rather than falling back to
scenario-wide - the alternative is an INI typo silently disabling a faction for everyone.

**Scope.** Lobby-side only: the four sites all live in the game-setup screen and none of them runs
after the game starts, so this changes nothing about simulation, saves or replays. It is still a
different binary, and the host's answer to "may this game start" is the one that counts, so **every
peer wants the same binary** to avoid one player's screen disagreeing with the host's gate.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the four five-byte `call`
instructions listed in :data:`~sage_patch.addresses.SCENARIO_FACTION_CALL_SITES`, which no other
bundled patch touches, and it reads nothing another patch rewrites.
"""

from __future__ import annotations

import struct

from ..addresses import (
    ASCII_STRING_DTOR,
    EMPTY_STRING,
    MP_SETUP_DISABLED_FACTION_PUSH,
    MP_SETUP_DISABLED_FACTION_PUSH_BYTES,
    MP_SETUP_FACTION_COMBO,
    MP_SETUP_FACTION_COMBO_BYTES,
    MP_SETUP_FACTION_COMBO_SLOT_ARG,
    MP_SETUP_FACTION_COMBO_SLOT_ARG_BYTES,
    MP_SETUP_FACTION_COMBO_SLOT_WINDOW,
    MP_SETUP_FACTION_COMBO_SLOT_WINDOW_BYTES,
    MP_SETUP_HISTORICAL_FIXUP,
    MP_SETUP_HISTORICAL_FIXUP_BYTES,
    MP_SETUP_RANDOM_LOOP_INIT,
    MP_SETUP_RANDOM_LOOP_INIT_BYTES,
    MP_SETUP_START_GATE_LOOP_INIT,
    MP_SETUP_START_GATE_LOOP_INIT_BYTES,
    MP_SETUP_VALIDATE_LOOP_INIT,
    MP_SETUP_VALIDATE_LOOP_INIT_BYTES,
    SCENARIO_DISABLED_FACTIONS_BEGIN,
    SCENARIO_DISABLED_FACTIONS_END,
    SCENARIO_FACTION_CALL_SITES,
    SCENARIO_IS_FACTION_ENABLED,
    SCENARIO_IS_FACTION_ENABLED_ENTRY,
)
from ..asm import JA, JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

# The one fact about an `AsciiString`'s buffer this cave needs - where the characters start - kept
# where the token-list patches already keep it rather than restated here.
from .utils.token_lists import ASCII_STRING_CHARS

__all__ = [
    "ANCHORS",
    "PLAYER_SEPARATOR",
    "SECTION_NAME",
    "ScenarioPlayerFactionsPatch",
    "build_code",
]

SECTION_NAME = ".plyfac"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The character that separates a faction name from the player it is disabled for. The same
#: `Name:N` form `commandset-button-upgrade` uses to pin a button to a slot, deliberately - a mod
#: that already writes one of them should not have to learn a second convention for the other.
PLAYER_SEPARATOR = 0x3A  # ':'

#: `ebp`-relative locals of the replacement's own frame.
_SLOT = -0x04  # the lobby slot index the caller is asking about, 0-based
_SIDE = -0x08  # the argument's characters, or the engine's empty string

#: What each site the cave jumps into or reads from holds in stock bytes. The four `call`
#: instructions being replaced are asserted by `apply_byte_patch`; these are what nothing else
#: would catch. Each entry is either the function the slot local belongs to or the instruction that
#: establishes that local, because the whole patch rests on the claim that the local named in
#: :data:`~sage_patch.addresses.SCENARIO_FACTION_CALL_SITES` is a lobby slot index - a build whose
#: layout moved has to fail here rather than by reading a slot number out of an unrelated variable.
ANCHORS = {
    SCENARIO_IS_FACTION_ENABLED: SCENARIO_IS_FACTION_ENABLED_ENTRY,
    MP_SETUP_START_GATE_LOOP_INIT: MP_SETUP_START_GATE_LOOP_INIT_BYTES,
    MP_SETUP_DISABLED_FACTION_PUSH: MP_SETUP_DISABLED_FACTION_PUSH_BYTES,
    MP_SETUP_HISTORICAL_FIXUP: MP_SETUP_HISTORICAL_FIXUP_BYTES,
    MP_SETUP_VALIDATE_LOOP_INIT: MP_SETUP_VALIDATE_LOOP_INIT_BYTES,
    MP_SETUP_RANDOM_LOOP_INIT: MP_SETUP_RANDOM_LOOP_INIT_BYTES,
    MP_SETUP_FACTION_COMBO: MP_SETUP_FACTION_COMBO_BYTES,
    MP_SETUP_FACTION_COMBO_SLOT_ARG: MP_SETUP_FACTION_COMBO_SLOT_ARG_BYTES,
    MP_SETUP_FACTION_COMBO_SLOT_WINDOW: MP_SETUP_FACTION_COMBO_SLOT_WINDOW_BYTES,
}


def _disp8(value: int) -> bytes:
    return struct.pack("<b", value)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _trampoline_label(index: int) -> str:
    return f"site{index}"


def _emit(base_va: int) -> Asm:
    """The four entry trampolines and the replacement they share, laid out but not resolved.

    A trampoline is entered by the `call` that used to reach `Scenario::isFactionEnabled`, so at
    its first instruction ``ebp`` is still the *caller's* frame pointer and the by-value
    `AsciiString` argument is at ``[esp+4]``. It reads the caller's slot local into ``edx`` and
    jumps; the replacement pushes its own frame after that, and its `ret 4` returns to the caller
    with the argument cleaned exactly as the stock function's did.

    Returned as the emitter rather than as bytes so that :func:`_trampolines` can read each
    trampoline's address off the layout that was actually emitted.
    """
    a = Asm(base_va)

    for index, (_, _, slot_ebp) in enumerate(SCENARIO_FACTION_CALL_SITES):
        a.label(_trampoline_label(index))
        a.emit(b"\x8b\x55", _disp8(slot_ebp))  # mov edx, [ebp+<the caller's slot local>]
        a.jmp("match")

    # __thiscall: ecx the Scenario, [esp+4] the side name by value; edx the 0-based lobby slot.
    a.label("match")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x52)  # push edx                ; [ebp-4] = the slot
    a.emit(0x51)  # push ecx                ; [ebp-8], filled in below
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi

    # `AsciiString::str()`, inlined: the characters live eight bytes into the buffer, and a null
    # handle reads as the engine's own empty string rather than short-circuiting - an empty entry
    # matching an empty name is what the stock comparison does.
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "side_chars")
    a.emit(0xB8, _u32(EMPTY_STRING))  # mov eax, EMPTY_STRING
    a.jmp("side_ready")

    a.label("side_chars")
    a.emit(b"\x83\xc0", _disp8(ASCII_STRING_CHARS))  # add eax, 8

    a.label("side_ready")
    a.emit(b"\x89\x45", _disp8(_SIDE))  # mov [ebp-8], eax
    a.emit(b"\x8b\x59", _disp8(SCENARIO_DISABLED_FACTIONS_BEGIN))  # mov ebx, [ecx+0x40]
    a.emit(b"\x8b\x79", _disp8(SCENARIO_DISABLED_FACTIONS_END))  # mov edi, [ecx+0x44]

    a.label("entry")
    a.emit(b"\x3b\xdf")  # cmp ebx, edi
    a.jcc(JE, "enabled")
    a.emit(b"\x8b\x03")  # mov eax, [ebx]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "next")
    a.emit(b"\x83\xc0", _disp8(ASCII_STRING_CHARS))  # add eax, 8    ; the entry's characters
    a.emit(b"\x8b\x75", _disp8(_SIDE))  # mov esi, [ebp-8]

    # The name part of the entry against the whole of the side name, byte for byte. `memcmp` is
    # what the stock comparison ends in, so this is case-sensitive on purpose.
    a.label("chars")
    a.emit(b"\x8a\x10")  # mov dl, [eax]
    a.emit(b"\x80\xfa", bytes([PLAYER_SEPARATOR]))  # cmp dl, ':'
    a.jcc(JE, "name_end")
    a.emit(b"\x84\xd2")  # test dl, dl
    a.jcc(JE, "name_end")
    a.emit(b"\x8a\x0e")  # mov cl, [esi]
    a.emit(b"\x3a\xd1")  # cmp dl, cl              ; a shorter side name ends on its NUL here
    a.jcc(JNE, "next")
    a.emit(0x40)  # inc eax
    a.emit(0x46)  # inc esi
    a.jmp("chars")

    a.label("name_end")
    a.emit(b"\x80\x3e\x00")  # cmp byte [esi], 0   ; the entry must not be a mere prefix
    a.jcc(JNE, "next")
    a.emit(b"\x80\xfa", bytes([PLAYER_SEPARATOR]))  # cmp dl, ':'
    a.jcc(JNE, "disabled")  # no qualifier: scenario-wide, exactly as stock

    # `:N`, the player this entry is written for. Counted from 1 in the INI because that is how
    # the lobby, `Teams` and everyone reading the file counts players; the engine's slot is 0-based.
    a.emit(0x40)  # inc eax
    a.emit(b"\x0f\xb6\x10")  # movzx edx, byte [eax]
    a.emit(b"\x83\xea\x30")  # sub edx, '0'
    a.emit(b"\x83\xfa\x09")  # cmp edx, 9
    a.jcc(JA, "next")  # a bare ':' names no player
    a.emit(b"\x33\xc9")  # xor ecx, ecx

    a.label("digits")
    a.emit(b"\x6b\xc9\x0a")  # imul ecx, ecx, 10
    a.emit(b"\x03\xca")  # add ecx, edx
    a.emit(0x40)  # inc eax
    a.emit(b"\x0f\xb6\x10")  # movzx edx, byte [eax]
    a.emit(b"\x83\xea\x30")  # sub edx, '0'
    a.emit(b"\x83\xfa\x09")  # cmp edx, 9
    a.jcc(JBE, "digits")

    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "next")  # ':0' is not a player either
    a.emit(b"\x8b\x55", _disp8(_SLOT))  # mov edx, [ebp-4]
    a.emit(0x42)  # inc edx                 ; the slot, as the INI counts it
    a.emit(b"\x3b\xca")  # cmp ecx, edx
    a.jcc(JNE, "next")  # written for somebody else

    a.label("disabled")
    a.emit(b"\x32\xc0")  # xor al, al
    a.jmp("done")

    a.label("next")
    a.emit(b"\x83\xc3\x04")  # add ebx, 4
    a.jmp("entry")

    a.label("enabled")
    a.emit(b"\xb0\x01")  # mov al, 1

    # The argument came by value and the callee owns it, which is what the stock function's own
    # tail does before it returns. The destructor clobbers eax, so the answer waits in bl - ebx is
    # callee-saved, so it survives the call and is restored after.
    a.label("done")
    a.emit(b"\x8a\xd8")  # mov bl, al
    a.emit(b"\x8d\x4d\x08")  # lea ecx, [ebp+8]
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(b"\x8a\xc3")  # mov al, bl
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0x59)  # pop ecx                 ; [ebp-8]
    a.emit(0x59)  # pop ecx                 ; [ebp-4]
    a.emit(0x5D)  # pop ebp
    a.emit(b"\xc2\x04\x00")  # ret 4
    return a


def build_code(base_va: int) -> bytes:
    """The cave's bytes, for a section based at ``base_va``."""
    return _emit(base_va).finish()


def _trampolines(section_va: int) -> list[int]:
    """Where each call site's trampoline starts, in the order of
    :data:`~sage_patch.addresses.SCENARIO_FACTION_CALL_SITES`.

    Read off the layout rather than counted: the trampolines are all the same size today, but a
    redirected `call` landing one byte into the wrong one is not a failure any test would describe.
    """
    a = _emit(section_va)
    return [a.label_va(_trampoline_label(i)) for i in range(len(SCENARIO_FACTION_CALL_SITES))]


class ScenarioPlayerFactionsPatch(Patch):
    name = "scenario-player-factions"
    author = "officialNecro"
    description = (
        "Let a War of the Ring Scenario disable a faction for one lobby slot instead of for "
        "everybody: an entry in the existing DisabledFactions list may be written Faction<X>:N, "
        "which bars that faction from player N only (counting from 1) and is invisible to every "
        "other slot. Entries with no :N keep their scenario-wide meaning, so no existing scenario "
        "changes. Honoured by the faction combo box, the start-game gate, the historical-scenario "
        "validation pass and the Random resolution pass alike"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        targets = _trampolines(section_va)
        for target, (site, original, _) in zip(targets, SCENARIO_FACTION_CALL_SITES, strict=True):
            off = va_to_offset(data, site)
            if off is None:
                raise ValueError(f"{site:#010x} is not mapped - not the expected build")
            call = b"\xe8" + struct.pack("<i", target - (site + 5))
            apply_byte_patch(
                data,
                off,
                original,
                call,
                f"Scenario::isFactionEnabled at {site:#010x} -> scenario-player-factions cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the game-setup "
                    "screen's layout is not this build's, so the slot a trampoline reads would "
                    "not be a slot"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        targets = _trampolines(section_va)
        for expected, (site, _, _) in zip(targets, SCENARIO_FACTION_CALL_SITES, strict=True):
            off = va_to_offset(data, site)
            if off is None:
                return [f"{site:#010x} is not mapped by any section"]
            if data[off] != 0xE8:
                problems.append(f"{site:#010x} is not a call - the hook is not installed")
                continue
            target = site + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != expected:
                problems.append(f"{site:#010x} calls {target:#010x}, expected {expected:#010x}")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected routine")
        return problems
