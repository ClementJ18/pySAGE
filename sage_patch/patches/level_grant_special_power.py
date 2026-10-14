"""Signed XP, configurable target relationships and a single parent-horde XP drain.

The native positive horde aggregation remains intact. Evidence and calling conventions:
`../docs/level-grant-special-power.md`.
"""

from ..addresses import (
    EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS,
    EXPERIENCE_TRACKER_CAN_GAIN,
    EXPERIENCE_TRACKER_XP,
    HORDE_EXPERIENCE_GROUP_FIND,
    HORDE_EXPERIENCE_GROUP_NODE_XP_OFFSET,
    HORDE_EXPERIENCE_GROUPS_OFFSET,
    LEVEL_GRANT_SPECIAL_POWER_DISTRIBUTE_RETURN,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_OFFSET,
    LEVEL_GRANT_SPECIAL_POWER_HORDE_ANCHORS,
    LEVEL_GRANT_SPECIAL_POWER_HORDE_CALLBACK_PUSH,
    LEVEL_GRANT_SPECIAL_POWER_HORDE_CALLBACK_PUSH_BYTES,
    LEVEL_GRANT_SPECIAL_POWER_HORDE_ITERATOR_CALL,
    LEVEL_GRANT_SPECIAL_POWER_HORDE_ITERATOR_CALL_BYTES,
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_BYTES,
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_IMMEDIATE,
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_INSTRUCTION,
    LEVEL_GRANT_SPECIAL_POWER_XP_CALLBACK,
    OBJECT_EXPERIENCE_TRACKER,
    OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET,
    OBJECT_THING_TEMPLATE,
)
from ..asm import JE, JG, JGE, JL, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32, u32

__all__ = ["SECTION_NAME", "LevelGrantSpecialPowerPatch", "build_code"]

SECTION_NAME = ".lgxp"
_REPLACEMENT = bytes.fromhex("0f8491000000")
_WINDOWS = {
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE: (
        LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES,
        _REPLACEMENT,
    ),
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_INSTRUCTION: (
        LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_BYTES,
        bytes.fromhex("c745b807000000"),
    ),
}


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)
    a.label("after_members")
    # Execute the displaced iterator exactly once with the original stack arguments.
    a.emit(LEVEL_GRANT_SPECIAL_POWER_HORDE_ITERATOR_CALL_BYTES[:6], b"\x9c")
    a.emit(b"\x83\xbe", u32(LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_OFFSET), b"\x00")
    a.jcc(JGE, "parent_done")
    # The additional native XP call may touch all floating-point state, not just XMM0.
    a.emit(b"\x60\x89\xe5\x81\xec\x10\x02\x00\x00\x83\xe4\xf0\x0f\xae\x04\x24")
    a.emit(b"\x8b\xbb", u32(OBJECT_EXPERIENCE_TRACKER), b"\x85\xff")
    a.jcc(JE, "parent_restore")
    a.emit(b"\x8b\xcf")
    a.call_absolute(EXPERIENCE_TRACKER_CAN_GAIN)
    a.emit(b"\x84\xc0")
    a.jcc(JE, "parent_restore")
    a.emit(b"\xf3\x0f\x2a\x86", u32(LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_OFFSET))
    # thiscall(delta, adjust=0, scale=0, feedback=0, extra=0), ret 0x14.
    # The wrapper owns ExperienceSink forwarding; the existing cap/down hooks own bounds/ranks.
    a.emit(b"\x6a\x00" * 4, b"\x83\xec\x04\xf3\x0f\x11\x04\x24\x8b\xcf")
    a.call_absolute(EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS)
    a.label("parent_restore")
    a.emit(b"\x0f\xae\x0c\x24\x89\xec\x61")
    a.label("parent_done")
    a.emit(b"\x9d")
    a.jmp_absolute(LEVEL_GRANT_SPECIAL_POWER_DISTRIBUTE_RETURN)

    a.label("member_callback")  # cdecl(Object*, XPContext*), like the displaced callback
    a.emit(b"\x55\x8b\xec\xff\x75\x0c\xff\x75\x08")
    a.call_absolute(LEVEL_GRANT_SPECIAL_POWER_XP_CALLBACK)
    a.emit(b"\x83\xc4\x08\x9c\x60\x8b\x7d\x0c\x83\x3f\x00")
    a.jcc(JGE, "member_done")  # positive callbacks must not change the group account
    a.emit(b"\x8b\x75\x08\x8b\x86", u32(OBJECT_EXPERIENCE_TRACKER), b"\x85\xc0")
    a.jcc(JE, "member_done")
    a.emit(b"\x83\x78", EXPERIENCE_TRACKER_XP, b"\x00")
    a.jcc(JL, "member_done")  # unbounded negative member XP keeps its native group reserve
    a.emit(b"\x8b\x4f\x08\x85\xc9")
    a.jcc(JE, "member_done")
    a.emit(b"\x8d\x99", u32(HORDE_EXPERIENCE_GROUPS_OFFSET))
    a.emit(
        b"\x8b\x46",
        OBJECT_THING_TEMPLATE,
        b"\x33\xd2\x66\x8b\x90",
        u32(OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET),
    )
    a.emit(b"\x52\x8b\xd4\x52\x8b\xcb")
    a.call_absolute(HORDE_EXPERIENCE_GROUP_FIND)
    a.emit(b"\x83\xc4\x04\x3b\x03")
    a.jcc(JE, "member_done")  # never create a group entry during cleanup
    a.emit(b"\x8b\x50", HORDE_EXPERIENCE_GROUP_NODE_XP_OFFSET, b"\x85\xd2")
    a.jcc(JGE, "member_done")
    a.emit(b"\x81\xe2\xff\xff\xff\x7f\x81\xfa\x00\x00\x80\x7f")
    a.jcc(JG, "member_done")  # an unordered NaN is not a negative reserve
    a.emit(b"\xc7\x40", HORDE_EXPERIENCE_GROUP_NODE_XP_OFFSET, b"\x00\x00\x00\x00")
    a.label("member_done")
    a.emit(b"\x61\x9d\x5d\xc3")
    return a


def build_code(base_va: int) -> bytes:
    """Relocatable, code-only horde completion and callback helpers."""
    return _assemble(base_va).finish()


def _windows(base_va: int) -> dict[int, tuple[bytes, bytes]]:
    a = _assemble(base_va)
    return {
        **_WINDOWS,
        LEVEL_GRANT_SPECIAL_POWER_HORDE_CALLBACK_PUSH: (
            LEVEL_GRANT_SPECIAL_POWER_HORDE_CALLBACK_PUSH_BYTES,
            b"\x68" + u32(a.label_va("member_callback")),
        ),
        LEVEL_GRANT_SPECIAL_POWER_HORDE_ITERATOR_CALL: (
            LEVEL_GRANT_SPECIAL_POWER_HORDE_ITERATOR_CALL_BYTES,
            jmp_rel32(
                LEVEL_GRANT_SPECIAL_POWER_HORDE_ITERATOR_CALL, a.label_va("after_members"), 8
            ),
        ),
    }


def _anchors(windows: dict[int, tuple[bytes, bytes]], patched: bool) -> dict[int, bytes]:
    sites = dict(LEVEL_GRANT_SPECIAL_POWER_HORDE_ANCHORS)
    for va, old in sites.items():
        blob = bytearray(old)
        for at, (original, new) in windows.items():
            if va <= at and at + len(original) <= va + len(blob):
                blob[at - va : at - va + len(original)] = new if patched else original
        sites[va] = bytes(blob)
    sites.update({va: new if patched else old for va, (old, new) in windows.items()})
    return sites


class LevelGrantSpecialPowerPatch(Patch):
    """Signed XP for members and their parent horde, with native target filtering."""

    name = "level-grant-special-power"
    author = "Ostkannit"
    description = (
        "Allow negative Experience on LevelGrantSpecialPower and drain each parent horde once. "
        "Let AcceptanceFilter control target relationships. "
        "Use experience-level-down for rank loss; "
        "positive horde aggregation stays native; no new INI fields"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for va, old in _anchors(_windows(0), False).items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(old)])
            if got != old:
                raise ValueError(f"{self.name} @{va:#010x}: expected {old.hex()} got {got.hex()}")
        base = allocate_section(data, SECTION_NAME, build_code, 0x60000020)
        for va, (old, new) in _windows(base).items():
            if va == LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_INSTRUCTION:
                apply_byte_patch(
                    data,
                    file_offset(data, LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_IMMEDIATE),
                    b"\x04",
                    b"\x07",
                    self.name,
                )
            else:
                apply_byte_patch(data, file_offset(data, va), old, new, self.name)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section"]
        base, off, size = located
        code = build_code(base)
        problems = []
        if size != len(code) or bytes(data[off : off + size]) != code:
            problems.append(f"unexpected {SECTION_NAME} helper body")
        for va, expected in _anchors(_windows(base), True).items():
            try:
                off = file_offset(data, va)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if bytes(data[off : off + len(expected)]) != expected:
                problems.append(f"unexpected LevelGrantSpecialPower bytes at {va:#010x}")
        return problems
