"""Bind a REVIVE button to the hero its `Object` names, instead of to its position in the set.

Stock, three walks decide which hero a REVIVE button recruits and all three are positional: the
ControlBar's pass 1 gives REVIVE ordinal n to roster hero n, its pass 2 gives each unclaimed
ledger entry the next free REVIVE button, and `canMakeUnit` accepts once it has counted
`reviveIndex` REVIVE buttons. So a building that offers the eighth hero carries eight buttons and
disables the seven it must not offer.

With this patch a REVIVE button that sets `Object` is bound to that hero:

- pass 1 binds it to the hero's latest ledger entry (the last of his name), wherever it sits, in
  skirmish and campaign alike, and does not let it consume a roster ordinal;
- pass 2 skips it, so it is never handed another hero's entry;
- `canMakeUnit` accepts it for exactly that hero's ledger index, through the button's
  `NeededUpgrade` gate, and does not count it towards the positional match;
- the tooltip builder describes it as a REVIVE button (the hero's `RecruitText` / `ReviveText`,
  rank and revive cost) instead of as a unit build of its `Object`;
- pass 1 and `canMakeUnit` both treat it as unbound while the player already has a live object of
  that template. A War of the Ring battle seeds the ledger with the faction's off-map hero pool,
  so a hero the map hands the player can have an entry while he stands on the field.

A REVIVE button without `Object` behaves exactly as stock, so bound and positional buttons can
share a set; the positional ones simply number among themselves. `canMakeUnit`'s stock revive
branch is reached by a jump and never read, so `ai-revive-gate`, which rewrites it, composes.

Derivation: `../docs/revive-object-binding.md`.
"""

from __future__ import annotations

import struct

from ...addresses import (
    CAN_MAKE_UNIT_NEXT_SLOT,
    CAN_MAKE_UNIT_REVIVE_BRANCH,
    CAN_MAKE_UNIT_REVIVE_DISPATCH,
    CAN_MAKE_UNIT_REVIVE_DISPATCH_BYTES,
    CAN_MAKE_UNIT_TEMPLATE_BRANCH,
    CAN_MAKE_UNIT_TEMPLATE_BRANCH_BYTES,
    CAN_MAKE_UNIT_UPGRADE_GATE,
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_GET_THING_TEMPLATE,
    COMMAND_BUTTON_GET_THING_TEMPLATE_ENTRY,
    CONTROL_BAR_REVIVE_BIND,
    CONTROL_BAR_REVIVE_BIND_BYTES,
    CONTROL_BAR_REVIVE_BIND_SET_ENTRY,
    CONTROL_BAR_REVIVE_ENTRY_EBP,
    CONTROL_BAR_REVIVE_ORDINAL_EBP,
    CONTROL_BAR_REVIVE_PASS2_NEXT,
    CONTROL_BAR_REVIVE_PASS2_NEXT_BYTES,
    CONTROL_BAR_REVIVE_PASS2_RESUME,
    CONTROL_BAR_REVIVE_PASS2_RESUME_BYTES,
    CONTROL_BAR_REVIVE_PASS2_TEST,
    CONTROL_BAR_REVIVE_PASS2_TEST_BYTES,
    CONTROL_BAR_REVIVE_PLAYER_EBP,
    CONTROL_BAR_REVIVE_ROSTER_LOOKUP,
    CONTROL_BAR_REVIVE_ROSTER_LOOKUP_BYTES,
    CONTROL_BAR_REVIVE_ROSTER_RESUME,
    CONTROL_BAR_REVIVE_ROSTER_RESUME_BYTES,
    CONTROL_BAR_REVIVE_UNBOUND,
    CONTROL_BAR_REVIVE_UNBOUND_BYTES,
    CONTROL_BAR_REVIVE_USED_COUNT,
    CONTROL_BAR_REVIVE_USED_EBP,
    DESCRIPTION_REVIVE_CASE,
    DESCRIPTION_REVIVE_CASE_BYTES,
    DESCRIPTION_TEMPLATE_CASE,
    DESCRIPTION_TEMPLATE_CASE_BYTES,
    DESCRIPTION_TEMPLATE_DISPATCH,
    DESCRIPTION_TEMPLATE_DISPATCH_BYTES,
    DESCRIPTION_UNTEMPLATED_CASES,
    DESCRIPTION_UNTEMPLATED_CASES_BYTES,
    GUICOMMAND_REVIVE,
    HERO_LEDGER_FIND_ENTRY,
    HERO_LEDGER_FIND_ENTRY_ENTRY,
    HERO_LEDGER_GET_ENTRY,
    HERO_LEDGER_GET_ENTRY_ENTRY,
    HERO_LEDGER_GET_TEMPLATE,
    HERO_LEDGER_GET_TEMPLATE_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER,
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE,
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE_ENTRY,
    PLAYER_GET_BUILDABLE_HERO,
    PLAYER_GET_BUILDABLE_HERO_ENTRY,
    PLAYER_HERO_LEDGER_OFFSET,
)
from ...asm import JAE, JB, JE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32

__all__ = [
    "ANCHORS",
    "HOOKS",
    "SECTION_NAME",
    "ReviveObjectBindingPatch",
    "build_code",
    "layout",
]

SECTION_NAME = ".revobj"  # 7 chars: the PE name field is 8 bytes and truncates silently

# `find_last` stops asking past this many entries of one name; a ledger holds a few dozen at most.
_MAX_LEDGER = 64

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: Each hooked site, as `{va: (stock bytes, the cave label it jumps to)}`. Every one is whole
#: instructions with no inbound edge past its first byte, and is replaced by a `jmp` padded with
#: `nop`s.
HOOKS = {
    CAN_MAKE_UNIT_REVIVE_DISPATCH: (CAN_MAKE_UNIT_REVIVE_DISPATCH_BYTES, "can_make_unit"),
    CONTROL_BAR_REVIVE_ROSTER_LOOKUP: (CONTROL_BAR_REVIVE_ROSTER_LOOKUP_BYTES, "pass1"),
    CONTROL_BAR_REVIVE_PASS2_TEST: (CONTROL_BAR_REVIVE_PASS2_TEST_BYTES, "pass2"),
    DESCRIPTION_TEMPLATE_DISPATCH: (DESCRIPTION_TEMPLATE_DISPATCH_BYTES, "tooltip"),
}

#: The first bytes at each address the cave jumps to or calls, as a `{va: bytes}` map, so a build
#: whose layout moved fails here instead of on a wild jump. `canMakeUnit`'s stock revive branch is
#: deliberately absent: `ai-revive-gate` rewrites it, and this patch only ever jumps to it.
ANCHORS = {
    CAN_MAKE_UNIT_TEMPLATE_BRANCH: CAN_MAKE_UNIT_TEMPLATE_BRANCH_BYTES,
    CAN_MAKE_UNIT_UPGRADE_GATE: bytes.fromhex("8b461c"),  # mov eax, [esi+0x1c]   ; Options
    CAN_MAKE_UNIT_NEXT_SLOT: bytes.fromhex("ff45f8"),  # inc dword [ebp-8]     ; slot index
    CONTROL_BAR_REVIVE_ROSTER_RESUME: CONTROL_BAR_REVIVE_ROSTER_RESUME_BYTES,
    CONTROL_BAR_REVIVE_BIND: CONTROL_BAR_REVIVE_BIND_BYTES,
    CONTROL_BAR_REVIVE_UNBOUND: CONTROL_BAR_REVIVE_UNBOUND_BYTES,
    CONTROL_BAR_REVIVE_PASS2_RESUME: CONTROL_BAR_REVIVE_PASS2_RESUME_BYTES,
    CONTROL_BAR_REVIVE_PASS2_NEXT: CONTROL_BAR_REVIVE_PASS2_NEXT_BYTES,
    DESCRIPTION_TEMPLATE_CASE: DESCRIPTION_TEMPLATE_CASE_BYTES,
    DESCRIPTION_UNTEMPLATED_CASES: DESCRIPTION_UNTEMPLATED_CASES_BYTES,
    DESCRIPTION_REVIVE_CASE: DESCRIPTION_REVIVE_CASE_BYTES,
    COMMAND_BUTTON_GET_THING_TEMPLATE: COMMAND_BUTTON_GET_THING_TEMPLATE_ENTRY,
    HERO_LEDGER_FIND_ENTRY: HERO_LEDGER_FIND_ENTRY_ENTRY,
    HERO_LEDGER_GET_ENTRY: HERO_LEDGER_GET_ENTRY_ENTRY,
    HERO_LEDGER_GET_TEMPLATE: HERO_LEDGER_GET_TEMPLATE_ENTRY,
    PLAYER_GET_BUILDABLE_HERO: PLAYER_GET_BUILDABLE_HERO_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER: bytes.fromhex("8b891c030000"),  # mov ecx, [ecx+0x31c]
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE: PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE_ENTRY,
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE + 0x47: bytes.fromhex("c21400"),  # ret 0x14
}


def _ebp(displacement: int) -> int:
    """A negative frame displacement as the signed byte of a `[ebp+disp8]` operand."""
    return displacement & 0xFF


def _bound_template(a: Asm, unbound: str) -> None:
    """`eax` = the REVIVE button in `esi`'s `Object`, leaving through `unbound` when it has none.
    The getter keeps `esi`; `ecx` and `edx` are the callee's."""
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(COMMAND_BUTTON_GET_THING_TEMPLATE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, unbound)


def _find_entry(a: Asm) -> None:
    """`eax` = the last entry of ledger `ecx` whose hero has the name of the bound template in
    `eax`, or -1. The last, because a death appends: in a War of the Ring battle the ledger starts
    with the off-map pool, whose entry for a hero the map also fields comes first, at level 1."""
    a.emit(0x50)  # push eax                          ; the bound template
    a.emit(0x51)  # push ecx                          ; the ledger
    a.call("find_last")


def _skip_if_fielded(a: Asm, player: tuple[int, ...], fielded: str) -> None:
    """Leave through `fielded` when the player in `player` (the bytes of a `push` of it) already
    has the bound template in `eax` alive. `eax` survives the other way; `ecx` and `edx` do not.
    A War of the Ring battle seeds the ledger with off-map heroes, so a hero the map hands the
    player can have an entry while he stands on the field."""
    a.emit(0x50)  # push eax                          ; keep the template
    a.emit(*player)  # push <player>
    a.emit(0x50)  # push eax
    a.call("fielded")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.emit(0x58)  # pop eax                            ; flags untouched
    a.jcc(JNE, fielded)


def layout(base_va: int) -> Asm:
    """The four routines, laid out at `base_va`. `HOOKS` names the label each site enters."""
    a = Asm(base_va)
    player = _ebp(CONTROL_BAR_REVIVE_PLAYER_EBP)
    ordinal = _ebp(CONTROL_BAR_REVIVE_ORDINAL_EBP)
    entry = _ebp(CONTROL_BAR_REVIVE_ENTRY_EBP)
    ledger = struct.pack("<I", PLAYER_HERO_LEDGER_OFFSET)

    # `canMakeUnit`, per slot, in place of `cmp byte [ebp-1], 0` / `jne REVIVE_BRANCH`. A bound
    # REVIVE button answers for its own hero and is never counted; anything else goes where the
    # stock code sent it.
    a.label("can_make_unit")
    a.emit(0x80, 0x7D, 0xFF, 0x00)  # cmp byte [ebp-1], 0        ; isRevive
    a.jcc(JNE, "cmu_revive")
    a.jmp_absolute(CAN_MAKE_UNIT_TEMPLATE_BRANCH)
    a.label("cmu_revive")
    a.emit(0x83, 0x7E, COMMAND_BUTTON_COMMAND, GUICOMMAND_REVIVE)  # cmp [esi+0x14], REVIVE
    a.jcc(JNE, "cmu_stock")
    _bound_template(a, "cmu_stock")
    a.emit(0x50)  # push eax                                     ; the bound template
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]                ; the producer
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x5A)  # pop edx                                      ; the bound template
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "cmu_next")
    a.emit(0x50)  # push eax                                     ; keep the player
    a.emit(0x8B, 0xC2)  # mov eax, edx
    _skip_if_fielded(a, (0xFF, 0x74, 0x24, 0x04), "cmu_fielded")  # push [esp+4] ; the player
    a.emit(0x59)  # pop ecx                                      ; the player
    a.emit(0x81, 0xC1, ledger)  # add ecx, 0x758                 ; the player's ledger
    _find_entry(a)
    a.emit(0x3B, 0x45, 0x10)  # cmp eax, [ebp+0x10]             ; the requested revive index
    a.jcc(JNE, "cmu_next")
    a.jmp_absolute(CAN_MAKE_UNIT_UPGRADE_GATE)  # NeededUpgrade, then accept or the next slot
    a.label("cmu_fielded")
    a.emit(0x59)  # pop ecx                                      ; drop the kept player
    a.label("cmu_next")
    a.jmp_absolute(CAN_MAKE_UNIT_NEXT_SLOT)  # past the slot without counting it
    a.label("cmu_stock")
    a.jmp_absolute(CAN_MAKE_UNIT_REVIVE_BRANCH)  # the positional count, stock or ai-revive-gate

    # Pass 1, in place of the roster lookup. A bound button takes its hero's ledger entry and
    # rejoins the stock bind with `ebx` = the index, `edi` = its template and `[ebp-0x28]` = the
    # entry, past the campaign test that leaves every stock pass-1 slot unbound. Either way the
    # tail increments the roster ordinal, so a bound button pre-decrements it to stay out of the
    # positional numbering.
    a.label("pass1")
    _bound_template(a, "p1_stock")
    a.emit(0xFF, 0x4D, ordinal)  # dec dword [ebp-0x20]         ; the tail's inc cancels it
    _skip_if_fielded(a, (0xFF, 0x75, player), "p1_none")  # push [ebp-0x1c] ; the player
    a.emit(0x8B, 0x4D, player)  # mov ecx, [ebp-0x1c]           ; the player
    a.emit(0x81, 0xC1, ledger)  # add ecx, 0x758
    _find_entry(a)
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.emit(0x83, 0xFB, 0xFF)  # cmp ebx, -1
    a.jcc(JE, "p1_none")  # fielded, or never in this player's ledger
    a.emit(0x8B, 0x7D, player)  # mov edi, [ebp-0x1c]
    a.emit(0x81, 0xC7, ledger)  # add edi, 0x758
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(HERO_LEDGER_GET_ENTRY)
    a.emit(0x89, 0x45, entry)  # mov [ebp-0x28], eax
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(HERO_LEDGER_GET_TEMPLATE)
    a.emit(0x8B, 0xF8)  # mov edi, eax
    a.emit(0x83, 0x7D, entry, 0x00)  # cmp dword [ebp-0x28], 0
    a.jcc(JE, "p1_none")
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "p1_none")
    # Claim the entry so pass 2 does not hand it out again. The flags are 33 bytes and the stock
    # store is unguarded; this one is not.
    a.emit(0x83, 0xFB, CONTROL_BAR_REVIVE_USED_COUNT)  # cmp ebx, 0x21
    a.jcc(JAE, "p1_claimed")
    used = struct.pack("<i", CONTROL_BAR_REVIVE_USED_EBP)
    a.emit(0xC6, 0x84, 0x1D, used, 0x01)  # mov byte [ebp+ebx-0x84], 1
    a.label("p1_claimed")
    a.emit(0xFF, 0x75, entry)  # push dword [ebp-0x28]
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.jmp_absolute(CONTROL_BAR_REVIVE_BIND_SET_ENTRY)
    a.label("p1_none")
    a.jmp_absolute(CONTROL_BAR_REVIVE_UNBOUND)
    a.label("p1_stock")
    a.emit(0xFF, 0x75, ordinal)  # push dword [ebp-0x20]       ; the displaced lookup
    a.emit(0x8B, 0x4D, player)  # mov ecx, [ebp-0x1c]
    a.call_absolute(PLAYER_GET_BUILDABLE_HERO)
    a.jmp_absolute(CONTROL_BAR_REVIVE_ROSTER_RESUME)

    # Pass 2, in place of its REVIVE test: a bound button is not a free slot.
    a.label("pass2")
    a.emit(0x83, 0x7E, COMMAND_BUTTON_COMMAND, GUICOMMAND_REVIVE)  # cmp [esi+0x14], REVIVE
    a.jcc(JNE, "p2_next")
    _bound_template(a, "p2_free")
    a.label("p2_next")
    a.jmp_absolute(CONTROL_BAR_REVIVE_PASS2_NEXT)
    a.label("p2_free")
    a.jmp_absolute(CONTROL_BAR_REVIVE_PASS2_RESUME)

    # The tooltip builder, in place of its "has a ThingTemplate" test. Only a bound REVIVE button
    # is a REVIVE button with a template, and it goes to the REVIVE case; everything else goes
    # where the stock test sent it, with `ebx` = the template as the unit case expects.
    a.label("tooltip")
    a.emit(0x8B, 0x5D, _ebp(-0x4C))  # mov ebx, [ebp-0x4c]          ; the button's ThingTemplate
    a.emit(0x3B, 0xDF)  # cmp ebx, edi                               ; edi is 0 here
    a.jcc(JE, "tt_untemplated")
    a.emit(0x8B, 0x46, 0x0C)  # mov eax, [esi+0xc]                  ; the CommandButton
    a.emit(0x83, 0x78, COMMAND_BUTTON_COMMAND, GUICOMMAND_REVIVE)  # cmp [eax+0x14], REVIVE
    a.jcc(JE, "tt_revive")
    a.jmp_absolute(DESCRIPTION_TEMPLATE_CASE)
    a.label("tt_revive")
    a.jmp_absolute(DESCRIPTION_REVIVE_CASE)
    a.label("tt_untemplated")
    a.jmp_absolute(DESCRIPTION_UNTEMPLATED_CASES)

    # `fielded(template, player)`, stdcall: how many live objects of `template` the player owns,
    # by the OCL cap's own call (1, &tmpl, ignoreDead = 1, &count, ignoreUnderConstruction = 0).
    # Keeps `ebx`, `esi` and `edi`, as the counter does.
    a.label("fielded")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x83, 0xEC, 0x08)  # sub esp, 8
    a.emit(0x8B, 0x45, 0x08)  # mov eax, [ebp+8]                ; the template
    a.emit(0x89, 0x45, 0xF8)  # mov [ebp-8], eax                ; a one-entry template list
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x8D, 0x45, 0xFC)  # lea eax, [ebp-4]                ; the count
    a.emit(0x50)  # push eax
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x8D, 0x45, 0xF8)  # lea eax, [ebp-8]
    a.emit(0x50)  # push eax
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x8B, 0x4D, 0x0C)  # mov ecx, [ebp+0xc]              ; the player
    a.call_absolute(PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE)
    a.emit(0x8B, 0x45, 0xFC)  # mov eax, [ebp-4]
    a.emit(0xC9)  # leave
    a.emit(0xC2, 0x08, 0x00)  # ret 8

    # `find_last(ledger, template)`, stdcall: the index of the last ledger entry of the template's
    # name, or -1, by asking `findEntry` for each ordinal in turn until it has none. Keeps `ebx`,
    # `esi` and `edi`.
    a.label("find_last")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(0x83, 0xCF, 0xFF)  # or edi, -1                      ; the last match so far
    a.emit(0x33, 0xF6)  # xor esi, esi                          ; the ordinal
    a.label("fl_next")
    a.emit(0x56)  # push esi                                     ; the ordinal-th entry of that name
    a.emit(0x6A, 0xFF)  # push -1                                ; match by name, not by id
    a.emit(0xFF, 0x75, 0x0C)  # push dword [ebp+0xc]             ; the template
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]                 ; the ledger
    a.call_absolute(HERO_LEDGER_FIND_ENTRY)
    a.emit(0x83, 0xF8, 0xFF)  # cmp eax, -1
    a.jcc(JE, "fl_done")
    a.emit(0x8B, 0xF8)  # mov edi, eax
    a.emit(0x46)  # inc esi
    a.emit(0x83, 0xFE, _MAX_LEDGER)  # cmp esi, 64                ; more than any ledger holds
    a.jcc(JB, "fl_next")
    a.label("fl_done")
    a.emit(0x8B, 0xC7)  # mov eax, edi
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0x5D)  # pop ebp
    a.emit(0xC2, 0x08, 0x00)  # ret 8
    return a


def build_code(base_va: int) -> bytes:
    return layout(base_va).finish()


def _entries(base_va: int) -> dict[int, int]:
    """`{hook va: the cave address it jumps to}` for a cave at `base_va`."""
    a = layout(base_va)
    return {va: a.label_va(label) for va, (_stock, label) in HOOKS.items()}


class ReviveObjectBindingPatch(Patch):
    name = "revive-object-binding"
    author = "officialNecro"
    description = (
        "Bind a REVIVE CommandButton to the hero its Object names, instead of to its position "
        "among the set's REVIVE buttons, so a building lists only the heroes it offers. Its "
        "tooltip still comes from the hero's RecruitText/ReviveText. "
        "INI: set Object = <hero> on a Command = REVIVE button; buttons without Object keep the "
        "stock positional behaviour"
    )

    def apply(self, data: bytearray) -> None:
        self._check_sites(data)
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        for va, target in _entries(cave_va).items():
            stock, label = HOOKS[va]
            apply_byte_patch(
                data,
                file_offset(data, va),
                stock,
                jmp_rel32(va, target, len(stock)),
                f"{va:#010x} -> revive-object-binding {label}",
            )

    @staticmethod
    def _check_sites(data: bytes | bytearray) -> None:
        for va, (stock, _label) in HOOKS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(stock)])
            if got != stock:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {stock.hex()} - the file already "
                    "carries this patch, or is not the expected build"
                )
        for va, expected in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the revive "
                    "populate, canMakeUnit or tooltip layout is not this build's, so the cave "
                    "would jump into the wrong place"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        problems: list[str] = []
        code = build_code(cave_va)
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routines in {SECTION_NAME} are not the ones this patch builds")
        for va, target in _entries(cave_va).items():
            stock, label = HOOKS[va]
            want = jmp_rel32(va, target, len(stock))
            off = file_offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@{va:#010x}: does not jump to {SECTION_NAME} {label}")
        return problems
