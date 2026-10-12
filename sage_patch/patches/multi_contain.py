"""Let an object carry slaughter contains beside the contain that keeps its passengers.

An object keeps one contain module at `OBJECT_CONTAIN` - the last one it declares - and every
question about entering it is asked of that one. A `SlaughterHordeContain` declared before a
`TunnelContain` is parsed, constructed and never consulted, so Edain's Barrow Wight lair cannot
both take Angmar's tribute carts and hide its wights.

A routine in the cave, `pick(target, rider)`, answers "which of the target's contains is this
rider for": the one at `OBJECT_CONTAIN` if it accepts the rider, otherwise the first other contain
module that answers `CONTAIN_IS_SLAUGHTER_SLOT` and accepts it, otherwise the one at
`OBJECT_CONTAIN` again, so that a refusal reads exactly as it does today. Every place that asks
the target's contain about one particular rider calls it instead of reading the field:
`canEnterObject` (the client's enter command and the enter states' re-check), the enter hint,
`AIGroup`'s pre-enter filter, and `onEnter`/`update` of `AIEnterState` and
`AIEnterAndAttackState`, which walk the rider to the contain's entry position and add it. Their
`onExit` releases the rider from every contain on the target, because by then the rider may
already have been slaughtered and can no longer be matched.

Only a slaughter contain can be picked this way. What happens to a passenger after it is in -
exiting, evacuating, the container dying, the rider dying inside - goes through `OBJECT_CONTAIN`
in hundreds of places, and a slaughter contain is the one kind that keeps nobody: it pays out and
destroys a rider in `addToContain`. Hordes (`KindOf HORDE`) and horde members are left to the
contain at `OBJECT_CONTAIN`, as are objects whose contain at `OBJECT_CONTAIN` accepts the rider.

Derivation: `../docs/multi-contain.md`.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, LimitDelta

from ..addresses import (
    ACTION_MANAGER_CAN_ENTER_OBJECT,
    AI_ENTER_AND_ATTACK_ON_ENTER_CONTAIN_LOAD,
    AI_ENTER_AND_ATTACK_ON_ENTER_CONTAIN_LOAD_BYTES,
    AI_ENTER_AND_ATTACK_ON_EXIT_RELEASE,
    AI_ENTER_AND_ATTACK_ON_EXIT_RELEASE_BYTES,
    AI_ENTER_AND_ATTACK_STATE_ON_ENTER,
    AI_ENTER_AND_ATTACK_STATE_ON_EXIT,
    AI_ENTER_AND_ATTACK_STATE_UPDATE,
    AI_ENTER_AND_ATTACK_STATE_VTABLE,
    AI_ENTER_AND_ATTACK_UPDATE_ADD_LOAD,
    AI_ENTER_AND_ATTACK_UPDATE_ADD_LOAD_BYTES,
    AI_ENTER_ON_ENTER_CONTAIN_LOAD,
    AI_ENTER_ON_ENTER_CONTAIN_LOAD_BYTES,
    AI_ENTER_ON_EXIT_RELEASE,
    AI_ENTER_ON_EXIT_RELEASE_BYTES,
    AI_ENTER_STATE_ON_ENTER,
    AI_ENTER_STATE_ON_EXIT,
    AI_ENTER_STATE_UPDATE,
    AI_ENTER_STATE_VTABLE,
    AI_ENTER_UPDATE_ADD_LOAD,
    AI_ENTER_UPDATE_ADD_LOAD_BYTES,
    AI_ENTER_UPDATE_ENTRY_LOAD,
    AI_ENTER_UPDATE_ENTRY_LOAD_BYTES,
    AI_GROUP_ENTER_FILTER_MEMBER_TEST,
    AI_GROUP_ENTER_FILTER_MEMBER_TEST_BYTES,
    AI_GROUP_ENTER_FILTER_TARGET,
    AI_STATE_ON_ENTER_SLOT,
    AI_STATE_ON_EXIT_SLOT,
    AI_STATE_UPDATE_SLOT,
    BEHAVIOR_GET_CONTAIN_SLOT,
    BEHAVIOR_MODULE_INTERFACE,
    CAN_ENTER_OBJECT_CONTAIN_LOAD,
    CAN_ENTER_OBJECT_CONTAIN_LOAD_BYTES,
    CONTAIN_ANSWER_NO,
    CONTAIN_ANSWER_NO_BYTES,
    CONTAIN_ANSWER_YES,
    CONTAIN_ANSWER_YES_BYTES,
    CONTAIN_IS_SLAUGHTER_SLOT,
    CONTAIN_IS_VALID_CONTAINER_FOR_SLOT,
    CONTAIN_RIDER_INTENT_RELEASE,
    CONTAIN_RIDER_INTENT_SLOT,
    DRAWABLE_OBJECT,
    ENTER_HINT_CONTAIN_LOAD,
    ENTER_HINT_CONTAIN_LOAD_BYTES,
    ENTER_HINT_SLAUGHTER_TEST,
    ENTER_HINT_SLAUGHTER_TEST_BYTES,
    HORDE_GARRISON_CONTAIN_INTERFACE_VTABLE,
    KINDOF_HORDE_BIT,
    KINDOF_HORDE_BYTE,
    OBJECT_CONTAIN,
    OBJECT_MODULE_LIST,
    OBJECT_STATUS,
    OBJECT_STATUS_HORDE_MEMBER,
    SLAUGHTER_HORDE_CONTAIN_INTERFACE_VTABLE,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section

__all__ = [
    "ANCHORS",
    "LOAD_SITES",
    "RELEASE_SITES",
    "SECTION_NAME",
    "MultiContainPatch",
    "build_code",
    "hooks",
    "stock_windows",
]

SECTION_NAME = ".mltcnt"  # 7 chars: the PE name field is 8 bytes and truncates silently

# Register numbers, as ModRM and `push r32` encode them.
EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI = range(8)

#: `Object+4` - the object's `ThingTemplate`, whose `KindOf` mask the horde test reads.
_OBJECT_TEMPLATE = 0x04
#: A `std::list` node's value, past its `next` and `prev`.
_LIST_NODE_VALUE = 0x08
#: `HORDE_MEMBER`'s byte and bit in the status mask at `OBJECT_STATUS`.
_HORDE_MEMBER_BYTE = OBJECT_STATUS + OBJECT_STATUS_HORDE_MEMBER // 8
_HORDE_MEMBER_BIT = 1 << (OBJECT_STATUS_HORDE_MEMBER % 8)

#: The six sites that load the target's contain into a register while the rider sits in another,
#: as `{va: (stock bytes, destination, target, rider)}`. Each loses its 6-byte
#: `mov dst, [target+0x258]` to a `call` into the cave and a `nop`; the stock bytes run on past
#: the load so the test that follows it is asserted too.
LOAD_SITES: dict[int, tuple[bytes, int, int, int]] = {
    CAN_ENTER_OBJECT_CONTAIN_LOAD: (CAN_ENTER_OBJECT_CONTAIN_LOAD_BYTES, EBX, EDI, ESI),
    AI_ENTER_ON_ENTER_CONTAIN_LOAD: (AI_ENTER_ON_ENTER_CONTAIN_LOAD_BYTES, ECX, EBX, ESI),
    AI_ENTER_UPDATE_ENTRY_LOAD: (AI_ENTER_UPDATE_ENTRY_LOAD_BYTES, ECX, EBP, EBX),
    AI_ENTER_UPDATE_ADD_LOAD: (AI_ENTER_UPDATE_ADD_LOAD_BYTES, ESI, EBP, EBX),
    AI_ENTER_AND_ATTACK_ON_ENTER_CONTAIN_LOAD: (
        AI_ENTER_AND_ATTACK_ON_ENTER_CONTAIN_LOAD_BYTES,
        ECX,
        EDI,
        ESI,
    ),
    AI_ENTER_AND_ATTACK_UPDATE_ADD_LOAD: (AI_ENTER_AND_ATTACK_UPDATE_ADD_LOAD_BYTES, EBP, EBP, EBX),
}
_LOAD_WIDTH = 6

#: The two `onExit` releases, each 18 bytes from the load to the call, rewritten as `push ebx` /
#: `push eax` / `call release` and `nop`s up to the next instruction.
RELEASE_SITES: dict[int, bytes] = {
    AI_ENTER_ON_EXIT_RELEASE: AI_ENTER_ON_EXIT_RELEASE_BYTES,
    AI_ENTER_AND_ATTACK_ON_EXIT_RELEASE: AI_ENTER_AND_ATTACK_ON_EXIT_RELEASE_BYTES,
}
_RELEASE_WIDTH = 18

#: The enter hint's load, which needs its rider found from the selection list.
_HINT_WIDTH = 6
#: The group filter's per-member call, 15 bytes from `mov eax, [esi]` to the `call`, rewritten as
#: the same three pushes and a `call` into the cave, which tail-calls the picked contain.
_GROUP_WIDTH = 15

#: What the routines rely on beyond the bytes they rewrite, as `{va: bytes}`: the predicate the
#: first load sits in, that the two states are the ones the sites were read in (their vtable
#: slots), that the slaughter test the hint asks is the slot the cave asks, and what that slot
#: answers for the base and for the slaughter class.
ANCHORS: dict[int, bytes] = {
    ACTION_MANAGER_CAN_ENTER_OBJECT: bytes.fromhex("558bec51"),  # its prologue
    AI_ENTER_STATE_VTABLE + AI_STATE_ON_ENTER_SLOT: struct.pack("<I", AI_ENTER_STATE_ON_ENTER),
    AI_ENTER_STATE_VTABLE + AI_STATE_ON_EXIT_SLOT: struct.pack("<I", AI_ENTER_STATE_ON_EXIT),
    AI_ENTER_STATE_VTABLE + AI_STATE_UPDATE_SLOT: struct.pack("<I", AI_ENTER_STATE_UPDATE),
    AI_ENTER_AND_ATTACK_STATE_VTABLE + AI_STATE_ON_ENTER_SLOT: struct.pack(
        "<I", AI_ENTER_AND_ATTACK_STATE_ON_ENTER
    ),
    AI_ENTER_AND_ATTACK_STATE_VTABLE + AI_STATE_ON_EXIT_SLOT: struct.pack(
        "<I", AI_ENTER_AND_ATTACK_STATE_ON_EXIT
    ),
    AI_ENTER_AND_ATTACK_STATE_VTABLE + AI_STATE_UPDATE_SLOT: struct.pack(
        "<I", AI_ENTER_AND_ATTACK_STATE_UPDATE
    ),
    ENTER_HINT_SLAUGHTER_TEST: ENTER_HINT_SLAUGHTER_TEST_BYTES,
    HORDE_GARRISON_CONTAIN_INTERFACE_VTABLE + CONTAIN_IS_SLAUGHTER_SLOT: struct.pack(
        "<I", CONTAIN_ANSWER_NO
    ),
    SLAUGHTER_HORDE_CONTAIN_INTERFACE_VTABLE + CONTAIN_IS_SLAUGHTER_SLOT: struct.pack(
        "<I", CONTAIN_ANSWER_YES
    ),
    CONTAIN_ANSWER_NO: CONTAIN_ANSWER_NO_BYTES,
    CONTAIN_ANSWER_YES: CONTAIN_ANSWER_YES_BYTES,
}

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def _mov_r32_r32(dst: int, src: int) -> bytes:
    return bytes([0x8B, 0xC0 | (dst << 3) | src])


def _emit_pick(a: Asm) -> None:
    """`pick(Object *target, Object *rider)`, `__stdcall`, `ret 8`: the contain `rider` is for.

    Preserves `ebx`, `esi`, `edi` and `ebp`; the contain calls it makes are `__thiscall` and leave
    those four alone too, so only `eax`, `ecx` and `edx` change."""
    a.label("pick")
    a.emit(0x53, 0x56, 0x57, 0x55)  # push ebx / esi / edi / ebp
    a.emit(0x8B, 0x74, 0x24, 0x14)  # mov esi, [esp+0x14]    target
    a.emit(0x8B, 0x6C, 0x24, 0x18)  # mov ebp, [esp+0x18]    rider
    a.emit(0x8B, 0x9E, struct.pack("<I", OBJECT_CONTAIN))  # mov ebx, [esi+0x258]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "pick.done")  # no contain at all: stock
    a.emit(0x85, 0xED)  # test ebp, ebp
    a.jcc(JE, "pick.done")  # no rider to match
    a.emit(0x8B, 0x45, _OBJECT_TEMPLATE)  # mov eax, [ebp+4]
    a.emit(0xF6, 0x80, struct.pack("<I", KINDOF_HORDE_BYTE), KINDOF_HORDE_BIT)  # test KindOf HORDE
    a.jcc(JNE, "pick.done")  # hordes stay with OBJECT_CONTAIN
    a.emit(0xF6, 0x85, struct.pack("<I", _HORDE_MEMBER_BYTE), _HORDE_MEMBER_BIT)
    a.jcc(JNE, "pick.done")  # and so do their members
    _emit_is_valid(a, EBX)
    a.jcc(JNE, "pick.done")  # the usual contain takes it: stock
    a.emit(0x8B, 0xBE, struct.pack("<I", OBJECT_MODULE_LIST))  # mov edi, [esi+0x24c]

    a.label("pick.next")
    a.emit(0x8B, 0x07)  # mov eax, [edi]             the module, NULL at the end
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pick.done")
    a.emit(0x83, 0xC7, 0x04)  # add edi, 4
    a.emit(0x8D, 0x48, BEHAVIOR_MODULE_INTERFACE)  # lea ecx, [eax+0xc]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, BEHAVIOR_GET_CONTAIN_SLOT)  # call [eax+8]       getContain
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "pick.next")  # not a contain
    a.emit(0x3B, 0xC3)  # cmp eax, ebx
    a.jcc_short(JE, "pick.next")  # the one already asked
    a.emit(0x8B, 0xF0)  # mov esi, eax             (the target is no longer needed)
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.emit(0xFF, 0x50, CONTAIN_IS_SLAUGHTER_SLOT)  # call [eax+0x30]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "pick.next")  # keeps its passengers: never a second contain
    _emit_is_valid(a, ESI)
    a.jcc_short(JE, "pick.next")
    a.emit(0x8B, 0xDE)  # mov ebx, esi

    a.label("pick.done")
    a.emit(0x8B, 0xC3)  # mov eax, ebx
    a.emit(0x5D, 0x5F, 0x5E, 0x5B)  # pop ebp / edi / esi / ebx
    a.emit(0xC2, 0x08, 0x00)  # ret 8


def _emit_is_valid(a: Asm, contain: int) -> None:
    """`contain->isValidContainerFor(rider = ebp, 0, 0)`, leaving the answer in the flags."""
    a.emit(0x6A, 0x00, 0x6A, 0x00)  # push 0 / push 0
    a.emit(0x55)  # push ebp
    a.emit(_mov_r32_r32(ECX, contain))
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x90, struct.pack("<I", CONTAIN_IS_VALID_CONTAINER_FOR_SLOT))
    a.emit(0x84, 0xC0)  # test al, al


def _emit_release(a: Asm) -> None:
    """`release(Object *target, Object *rider)`, `__stdcall`, `ret 8`: erase the rider's entry
    from every contain on the target, as `onExit` erases it from the one at `OBJECT_CONTAIN`."""
    a.label("release")
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0x74, 0x24, 0x10)  # mov esi, [esp+0x10]    target
    a.emit(0x8B, 0x7C, 0x24, 0x14)  # mov edi, [esp+0x14]    rider
    a.emit(0x8B, 0x9E, struct.pack("<I", OBJECT_MODULE_LIST))  # mov ebx, [esi+0x24c]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc_short(JE, "release.done")

    a.label("release.next")
    a.emit(0x8B, 0x03)  # mov eax, [ebx]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "release.done")
    a.emit(0x83, 0xC3, 0x04)  # add ebx, 4
    a.emit(0x8D, 0x48, BEHAVIOR_MODULE_INTERFACE)  # lea ecx, [eax+0xc]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, BEHAVIOR_GET_CONTAIN_SLOT)  # call [eax+8]       getContain
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "release.next")
    a.emit(0x6A, CONTAIN_RIDER_INTENT_RELEASE)  # push 2
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x8B, 0x00)  # mov eax, [eax]
    a.emit(0xFF, 0x50, CONTAIN_RIDER_INTENT_SLOT)  # call [eax+0x44]
    a.jmp_short("release.next")

    a.label("release.done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC2, 0x08, 0x00)  # ret 8


def _emit_load(a: Asm, va: int, dst: int, target: int, rider: int) -> None:
    """The stand-in for `mov dst, [target+0x258]` at `va`: `dst = pick(target, rider)`, every
    other register as it was. Reached by `call`, so the flags the site sets next are its own."""
    saved = [r for r in (EAX, ECX, EDX) if r != dst]
    a.label(f"load.{va:08x}")
    for r in saved:
        a.emit(0x50 | r)  # push r
    a.emit(0x50 | rider)  # push rider
    a.emit(0x50 | target)  # push target
    a.call("pick")
    if dst != EAX:
        a.emit(_mov_r32_r32(dst, EAX))
    for r in reversed(saved):
        a.emit(0x58 | r)  # pop r
    a.emit(0xC3)  # ret


def _emit_hint_load(a: Asm) -> None:
    """The enter hint's load: `ebx = pick(edi, first selected object)`. The selection in `esi`
    is a `std::list` the hint has already found non-empty."""
    a.label("hint")
    a.emit(0x51, 0x52, 0x50)  # push ecx / edx / eax
    a.emit(0x8B, 0x06)  # mov eax, [esi]             the list's head
    a.emit(0x8B, 0x00)  # mov eax, [eax]             its first node
    a.emit(0x8B, 0x40, _LIST_NODE_VALUE)  # mov eax, [eax+8]      the drawable
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "hint.pick")
    a.emit(0x8B, 0x80, struct.pack("<I", DRAWABLE_OBJECT))  # mov eax, [eax+0xfc]   its object
    a.label("hint.pick")
    a.emit(0x50)  # push eax                   rider
    a.emit(0x57)  # push edi                   target
    a.call("pick")
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.emit(0x58, 0x5A, 0x59)  # pop eax / edx / ecx
    a.emit(0xC3)  # ret


def _emit_group_test(a: Asm) -> None:
    """The group filter's question, asked of the contain the member is for. Entered by `call`
    with the stock `(member, 0, 1)` already pushed; tail-calls `isValidContainerFor`, whose
    `ret 0xc` returns to the site with those arguments gone."""
    a.label("group")
    a.emit(0x8B, 0x45, 0x08)  # mov eax, [ebp+8]          the command
    a.emit(0x8B, 0x40, AI_GROUP_ENTER_FILTER_TARGET)  # mov eax, [eax+0xc]    its target
    a.emit(0x53)  # push ebx                   the member
    a.emit(0x50)  # push eax
    a.call("pick")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x8B, 0x00)  # mov eax, [eax]
    a.emit(0xFF, 0xA0, struct.pack("<I", CONTAIN_IS_VALID_CONTAINER_FOR_SLOT))  # jmp [eax+0x98]


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)
    _emit_pick(a)
    _emit_release(a)
    for va, (_stock, dst, target, rider) in LOAD_SITES.items():
        _emit_load(a, va, dst, target, rider)
    _emit_hint_load(a)
    _emit_group_test(a)
    return a


def build_code(base_va: int) -> bytes:
    """The cave: `pick`, `release`, and one entry per hooked site."""
    return _assemble(base_va).finish()


def hooks(cave_va: int) -> dict[int, tuple[bytes, bytes]]:
    """Every site this patch rewrites, as `{va: (stock bytes, patched bytes)}`, each the width
    of the rewrite."""
    a = _assemble(cave_va)
    edits: dict[int, tuple[bytes, bytes]] = {}

    def call_site(va: int, stock: bytes, width: int, label: str, prefix: bytes = b"") -> None:
        at = va + len(prefix)
        code = prefix + call_rel32(at, a.label_va(label))
        edits[va] = (stock[:width], code + b"\x90" * (width - len(code)))

    for va, (stock, *_regs) in LOAD_SITES.items():
        call_site(va, stock, _LOAD_WIDTH, f"load.{va:08x}")
    for va, stock in RELEASE_SITES.items():
        call_site(va, stock, _RELEASE_WIDTH, "release", b"\x53\x50")  # push ebx / push eax
    call_site(ENTER_HINT_CONTAIN_LOAD, ENTER_HINT_CONTAIN_LOAD_BYTES, _HINT_WIDTH, "hint")
    call_site(
        AI_GROUP_ENTER_FILTER_MEMBER_TEST,
        AI_GROUP_ENTER_FILTER_MEMBER_TEST_BYTES,
        _GROUP_WIDTH,
        "group",
        b"\x6a\x01\x6a\x00\x53",  # push 1 / push 0 / push ebx
    )
    return edits


def stock_windows() -> dict[int, bytes]:
    """Every byte run the patch asserts before it writes: each site's stock bytes in full (the
    rewrite and what follows it) and the anchors."""
    windows = {va: stock for va, (stock, *_regs) in LOAD_SITES.items()}
    windows.update(RELEASE_SITES)
    windows[ENTER_HINT_CONTAIN_LOAD] = ENTER_HINT_CONTAIN_LOAD_BYTES
    windows[AI_GROUP_ENTER_FILTER_MEMBER_TEST] = AI_GROUP_ENTER_FILTER_MEMBER_TEST_BYTES
    windows.update(ANCHORS)
    return windows


class MultiContainPatch(Patch):
    name = "multi-contain"
    author = "officialNecro"
    description = (
        "Let an object carry slaughter contains beside the contain that keeps its passengers: a "
        "unit entering it goes to the last-declared contain as today if that one accepts it, "
        "otherwise to the first other contain that is a slaughter contain (SlaughterHordeContain "
        "and its children) and accepts it - so a TunnelContain lair can also take tribute carts. "
        "Declare the slaughter contains before the contain that keeps passengers. Hordes and "
        "horde members only ever use the last-declared contain. Logic-side: every peer needs "
        "the same binary. No INI change"
    )

    def ini_surface(self) -> Engine:
        """The routing, as the engine limit the `unreachable-contain` lint rule reads: an earlier
        slaughter contain is now reachable, and any other earlier contain still is not."""
        return Engine(limits=(LimitDelta("contain.secondary_slaughter", 1, self.name),))

    def apply(self, data: bytearray) -> None:
        self._check_stock(data)
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        for va, (stock, patched) in hooks(cave_va).items():
            apply_byte_patch(
                data, file_offset(data, va), stock, patched, f"multi-contain @0x{va:08x}"
            )

    @staticmethod
    def _check_stock(data: bytes | bytearray) -> None:
        for va, expected in stock_windows().items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"@0x{va:08x}: expected {expected.hex()}, got {got.hex()} - the file is not "
                    "the expected build, or already carries this patch"
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
        for va, (_stock, patched) in hooks(cave_va).items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(patched)])
            if got != patched:
                problems.append(f"@0x{va:08x}: not hooked into {SECTION_NAME} (holds {got.hex()})")
        return problems
