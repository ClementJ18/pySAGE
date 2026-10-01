"""Bind a REVIVE button to the hero its `Object` names, instead of to its position in the set.

Stock, three walks decide which hero a REVIVE button recruits and all three are positional: the
ControlBar's pass 1 gives REVIVE ordinal n to roster hero n, its pass 2 gives each unclaimed
ledger entry the next free REVIVE button, and `canMakeUnit` accepts once it has counted
`reviveIndex` REVIVE buttons. So a building that offers the eighth hero carries eight buttons and
disables the seven it must not offer.

With this patch a REVIVE button that sets `Object` is bound to that hero:

- pass 1 binds it to the hero's own ledger entry (`findEntry` by name), whatever its position, in
  skirmish and campaign alike, and does not let it consume a roster ordinal;
- pass 2 skips it, so it is never handed another hero's entry;
- `canMakeUnit` accepts it for exactly that hero's ledger index, through the button's
  `NeededUpgrade` gate, and does not count it towards the positional match.

A REVIVE button without `Object` behaves exactly as stock, so bound and positional buttons can
share a set; the positional ones simply number among themselves. `canMakeUnit`'s stock revive
branch is reached by a jump and never read, so `ai-revive-gate`, which rewrites it, composes.

Derivation: `../docs/revive-object-binding.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
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
    GUICOMMAND_REVIVE,
    HERO_LEDGER_FIND_ENTRY,
    HERO_LEDGER_FIND_ENTRY_ENTRY,
    HERO_LEDGER_GET_ENTRY,
    HERO_LEDGER_GET_ENTRY_ENTRY,
    HERO_LEDGER_GET_TEMPLATE,
    HERO_LEDGER_GET_TEMPLATE_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER,
    PLAYER_GET_BUILDABLE_HERO,
    PLAYER_GET_BUILDABLE_HERO_ENTRY,
    PLAYER_HERO_LEDGER_OFFSET,
)
from ..asm import JAE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32

__all__ = [
    "ANCHORS",
    "HOOKS",
    "SECTION_NAME",
    "ReviveObjectBindingPatch",
    "build_code",
    "layout",
]

SECTION_NAME = ".revobj"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: Each hooked site, as `{va: (stock bytes, the cave label it jumps to)}`. Every one is whole
#: instructions with no inbound edge past its first byte, and is replaced by a `jmp` padded with
#: `nop`s.
HOOKS = {
    CAN_MAKE_UNIT_REVIVE_DISPATCH: (CAN_MAKE_UNIT_REVIVE_DISPATCH_BYTES, "can_make_unit"),
    CONTROL_BAR_REVIVE_ROSTER_LOOKUP: (CONTROL_BAR_REVIVE_ROSTER_LOOKUP_BYTES, "pass1"),
    CONTROL_BAR_REVIVE_PASS2_TEST: (CONTROL_BAR_REVIVE_PASS2_TEST_BYTES, "pass2"),
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
    COMMAND_BUTTON_GET_THING_TEMPLATE: COMMAND_BUTTON_GET_THING_TEMPLATE_ENTRY,
    HERO_LEDGER_FIND_ENTRY: HERO_LEDGER_FIND_ENTRY_ENTRY,
    HERO_LEDGER_GET_ENTRY: HERO_LEDGER_GET_ENTRY_ENTRY,
    HERO_LEDGER_GET_TEMPLATE: HERO_LEDGER_GET_TEMPLATE_ENTRY,
    PLAYER_GET_BUILDABLE_HERO: PLAYER_GET_BUILDABLE_HERO_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER: bytes.fromhex("8b891c030000"),  # mov ecx, [ecx+0x31c]
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
    """`eax` = `ledger(ecx)->findEntry(eax, -1, 0)`: the first ledger entry whose hero has the bound
    template's name, or -1. `ecx` must already be the ledger."""
    a.emit(0x6A, 0x00)  # push 0                      ; the first entry of that name
    a.emit(0x6A, 0xFF)  # push -1                     ; match by name, not by id
    a.emit(0x50)  # push eax                          ; the bound template
    a.call_absolute(HERO_LEDGER_FIND_ENTRY)


def layout(base_va: int) -> Asm:
    """The three routines, laid out at `base_va`. `HOOKS` names the label each site enters."""
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
    a.emit(0x8D, 0x88, ledger)  # lea ecx, [eax+0x758]           ; the player's ledger
    a.emit(0x8B, 0xC2)  # mov eax, edx
    _find_entry(a)
    a.emit(0x3B, 0x45, 0x10)  # cmp eax, [ebp+0x10]             ; the requested revive index
    a.jcc(JNE, "cmu_next")
    a.jmp_absolute(CAN_MAKE_UNIT_UPGRADE_GATE)  # NeededUpgrade, then accept or the next slot
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
        "among the set's REVIVE buttons, so a building lists only the heroes it offers. "
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
                    "populate or canMakeUnit layout is not this build's, so the cave would jump "
                    "into the wrong place"
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
