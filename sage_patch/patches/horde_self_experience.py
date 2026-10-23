"""Hand experience credited to a horde object itself to its members' groups.

The kill scorer (`0x00695475`) credits a killer that sits in a horde through the horde
interface's `HORDE_EXPERIENCE_ADD(killer, xp)`: the XP goes into an account keyed by the killer's
template, every member of that template is set to the account, and the horde object's own tracker
is raised to it. A member killer keys the account by its own template, so the members rank up.

When the killer is the horde object itself, which is what `BloodthirstyUpdate`'s sacrifice
credits, the account is keyed by the **horde's** template. No member has it, so the members stay
at their XP and only the horde object ranks up (its level, its banner carrier). Anything that
later rebuilds the horde's XP from its members drops that rank: a `ComboHorde` merge sets the new
horde to its highest member, so a sacrificed level-2 orc horde that joins an overseer makes a
level-1 combo and loses its banner.

The patch replaces the scorer's `call [eax+0xC0]` with a cave. A member killer goes on to the
interface's own slot, unchanged. For the horde object itself, the cave walks the horde's
contained list, keeps one member of each experience group, and calls `HORDE_EXPERIENCE_ADD` once
per group with the full amount, as if a member of each group had made the kill. A horde with no
members keeps the stock call. Logic-side: every peer needs the same binary. No INI change.

Derivation: `../docs/horde-self-experience.md`.
"""

from __future__ import annotations

from ..addresses import (
    CONTAIN_ITEM_LIST,
    CONTAIN_ITEM_LIST_NODE_OBJECT,
    HORDE_IFACE_EXPERIENCE_ADD_SLOT,
    HORDE_IFACE_OWNER,
    KILL_SCORE_HORDE_EXPERIENCE_CALL,
    KILL_SCORE_HORDE_EXPERIENCE_CALL_BYTES,
    OBJECT_CONTAIN,
    OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET,
    OBJECT_THING_TEMPLATE,
)
from ..asm import JAE, JB, JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section, u32

__all__ = [
    "ANCHORS",
    "GROUP_CAP",
    "SECTION_NAME",
    "HordeSelfExperiencePatch",
    "build_section",
    "hook_bytes",
    "layout",
]

SECTION_NAME = ".hordexp"

#: How many distinct experience groups one horde can hand XP to. A combo holds two or three.
GROUP_CAP = 8
_FRAME = 4 * GROUP_CAP

#: Read, never rewritten: the kill scorer around the hooked call - the horde branch, with `edi`
#: the interface and `esi` the killer, the `push ecx / fstp [esp] / push esi` that pass
#: `(killer, xp)`, and the jump past the non-horde branch that follows.
ANCHORS: dict[int, bytes] = {
    0x00695504: bytes.fromhex("8bcee8edf6ffff8bf885ff6a007440"),
    0x0069553F: bytes.fromhex("d945108b0751d91c24568bcf"),
    0x00695551: bytes.fromhex("eb18"),
}

# CNT_CODE | MEM_EXECUTE | MEM_READ
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI = range(8)


def _slot(reg: int, index: int) -> bytes:
    """ModRM + SIB + disp32 for `[ebp + index*4 - _FRAME]`, `reg` in the ModRM reg field."""
    return bytes([0x84 | reg << 3, 0x80 | index << 3 | EBP]) + u32(-_FRAME & 0xFFFFFFFF)


def _call_add(a: Asm) -> None:
    """`HORDE_EXPERIENCE_ADD` through the interface's vtable, `esi` the interface, args pushed."""
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.emit(0xFF, 0x90, u32(HORDE_IFACE_EXPERIENCE_ADD_SLOT))  # call [eax+0xc0]


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)

    # distribute(killer, xp): `__thiscall` on the horde interface, `ret 8`, standing in for the
    # scorer's virtual `HORDE_EXPERIENCE_ADD`.
    a.label("distribute")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]         ; the killer
    a.emit(0x3B, 0x81, u32(HORDE_IFACE_OWNER & 0xFFFFFFFF))  # cmp eax, [ecx-0x114]  ; the horde?
    a.jcc(JE, "self")
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0xA0, u32(HORDE_IFACE_EXPERIENCE_ADD_SLOT))  # jmp [eax+0xc0]   ; a member: stock

    a.label("self")
    a.emit(0x55, 0x8B, 0xEC)  # push ebp / mov ebp, esp
    a.emit(0x83, 0xEC, _FRAME)  # sub esp, frame            ; one member per group
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0xF1)  # mov esi, ecx                       ; the interface
    a.emit(0x33, 0xDB)  # xor ebx, ebx                       ; groups found
    a.emit(0x8B, 0x88, u32(OBJECT_CONTAIN))  # mov ecx, [eax+0x258]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "collected")
    a.emit(0x8B, 0x49, CONTAIN_ITEM_LIST)  # mov ecx, [ecx+0x34]   ; the list sentinel
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "collected")
    a.emit(0x8B, 0x11)  # mov edx, [ecx]                     ; the first node

    a.label("walk")
    a.emit(0x3B, 0xD1)  # cmp edx, ecx
    a.jcc(JE, "collected")
    a.emit(0x83, 0xFB, GROUP_CAP)  # cmp ebx, cap
    a.jcc(JAE, "collected")
    a.emit(0x8B, 0x42, CONTAIN_ITEM_LIST_NODE_OBJECT)  # mov eax, [edx+8]   ; the member
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "next")
    a.emit(0x8B, 0x78, OBJECT_THING_TEMPLATE)  # mov edi, [eax+4]
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "next")
    a.emit(0x66, 0x8B, 0xBF, u32(OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET))  # mov di, [edi+0x5e8]
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x33, 0xC9)  # xor ecx, ecx
    a.label("scan")
    a.emit(0x3B, 0xCB)  # cmp ecx, ebx
    a.jcc(JAE, "add")
    a.emit(0x8B, _slot(EDX, ECX))  # mov edx, [ebp+ecx*4-frame]
    a.emit(0x8B, 0x52, OBJECT_THING_TEMPLATE)  # mov edx, [edx+4]
    a.emit(0x66, 0x3B, 0xBA, u32(OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET))  # cmp di, [edx+0x5e8]
    a.jcc(JE, "known")
    a.emit(0x41)  # inc ecx
    a.jmp("scan")
    a.label("add")
    a.emit(0x89, _slot(EAX, EBX))  # mov [ebp+ebx*4-frame], eax
    a.emit(0x43)  # inc ebx
    a.label("known")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.label("next")
    a.emit(0x8B, 0x12)  # mov edx, [edx]
    a.jmp("walk")

    a.label("collected")
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "none")
    a.emit(0x33, 0xFF)  # xor edi, edi
    a.label("give")
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0xc]              ; xp
    a.emit(0xFF, _slot(6, EDI))  # push [ebp+edi*4-frame]     ; this group's member
    _call_add(a)
    a.emit(0x47)  # inc edi
    a.emit(0x3B, 0xFB)  # cmp edi, ebx
    a.jcc(JB, "give")
    a.jmp("done")

    a.label("none")  # an empty horde: the stock call
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0xc]
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]
    _call_add(a)

    a.label("done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC9)  # leave
    a.emit(0xC2, 0x08, 0x00)  # ret 8
    return a


def build_section(base_va: int) -> bytes:
    return _assemble(base_va).finish()


def layout(base_va: int) -> dict[str, int]:
    return {"distribute": _assemble(base_va).label_va("distribute")}


def hook_bytes(base_va: int) -> bytes:
    """The six bytes that replace the scorer's `call [eax+0xC0]`: `call distribute` and a `nop`."""
    at = KILL_SCORE_HORDE_EXPERIENCE_CALL
    return call_rel32(at, layout(base_va)["distribute"]) + b"\x90"


class HordeSelfExperiencePatch(Patch):
    name = "horde-self-experience"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Experience credited to a horde object itself (a BloodthirstyUpdate sacrifice) goes to "
        "its members, once per experience group, as if a member of each group had made the "
        "kill. Stock it lands in an account keyed by the horde's own template, so only the "
        "horde ranks up, and a ComboHorde merge, which rebuilds the level from the members, "
        "drops it and the banner. Logic-side: every peer needs the same binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in {
            **ANCHORS,
            KILL_SCORE_HORDE_EXPERIENCE_CALL: KILL_SCORE_HORDE_EXPERIENCE_CALL_BYTES,
        }.items():
            self._check_stock(data, va, expected)
        base_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            file_offset(data, KILL_SCORE_HORDE_EXPERIENCE_CALL),
            KILL_SCORE_HORDE_EXPERIENCE_CALL_BYTES,
            hook_bytes(base_va),
            "kill scorer -> horde self experience to the members",
        )

    @staticmethod
    def _check_stock(data: bytes | bytearray, va: int, expected: bytes) -> None:
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the file is not "
                "the expected build, or already carries this patch"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, section_off, vsize = located
        problems: list[str] = []
        expected = build_section(base_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if vsize < len(expected) or got != expected:
            problems.append(f"the {SECTION_NAME} cave is not the one this patch builds")
        off = file_offset(data, KILL_SCORE_HORDE_EXPERIENCE_CALL)
        here = bytes(data[off : off + 6])
        if here != hook_bytes(base_va):
            problems.append(
                f"@{KILL_SCORE_HORDE_EXPERIENCE_CALL:#010x}: the kill scorer hook is not "
                f"installed (holds {here.hex()})"
            )
        for va, expected_bytes in ANCHORS.items():
            off = file_offset(data, va)
            if bytes(data[off : off + len(expected_bytes)]) != expected_bytes:
                problems.append(f"@{va:#010x}: the kill scorer is not the expected build")
        return problems
