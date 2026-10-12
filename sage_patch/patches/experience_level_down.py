"""Reverse lost level effects only after an actual XP decrease.

The stock upward cascade and explicit grants stay intact. Pending lost grants are
cancelled in the engine's own queue; the state-only wrapper skips enqueueing the
already-owned lower level. Evidence: `../docs/experience-level-down.md`.
The optional XP bounds are documented in `../docs/experience-xp-cap.md`.
"""

from __future__ import annotations

import argparse
import struct

from ..addresses import (
    EXPERIENCE_LEVEL_COLLECTION,
    EXPERIENCE_LEVEL_DOWN_ANCHORS,
    EXPERIENCE_LEVEL_FIND_BY_KEY,
    EXPERIENCE_LEVEL_MODE_ALLOWED,
    EXPERIENCE_LEVEL_RESOLVE,
    EXPERIENCE_TRACKER_LEVEL_CHECK,
    EXPERIENCE_TRACKER_OBJECT_LEVEL_CHANGE,
    EXPERIENCE_XP_CAP_WINDOWS,
    OBJECT_REMOVE_LEVEL_MODIFIER,
    OBJECT_REMOVE_LEVEL_UPGRADE,
    THE_DELAYED_EXPERIENCE_LEVEL_GRANT_SYSTEM,
    THE_EXPERIENCE_LEVEL_SYSTEM,
)
from ..asm import JAE, JB, JBE, JE, JG, JGE, JL, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32
from .upgrade_module_removal import _compatible_anchor

__all__ = ["SECTION_NAME", "ExperienceLevelDownPatch", "build_code"]

SECTION_NAME = ".xpdown"
_CHARACTERISTICS = 0x60000020
_CAP = 0x0079D69E
_ADD = 0x0079D6E6
_SET = 0x0079D929
_QUEUE = 0x008215A2
_MODIFIER_RETURN = 0x0082134D
_UPGRADE_RETURN = 0x00821375
_WINDOWS = {
    _CAP: bytes.fromhex("8b41283bc27e053941247d52"),
    _ADD: bytes.fromhex("f30f104910ff7514f30f58c8f30f114910e845faffff"),
    _SET: bytes.fromhex("f30f11461050e80df8ffff"),
    _QUEUE: bytes.fromhex("8a46108bcd5053ff760ce868fdffff"),
    _MODIFIER_RETURN: bytes.fromhex("8b46342b4630"),
    _UPGRADE_RETURN: bytes.fromhex("8b46502b464c"),
}


def _emit_add(a: Asm) -> None:
    a.label("add")
    # Preserve xmm2, which the displaced code did not touch. No x87 stack change.
    a.emit(b"\x83\xec\x10\x0f\x11\x14\x24")
    a.emit(b"\xf3\x0f\x10\x51\x10\x0f\x28\xca\xf3\x0f\x58\xc8")
    a.emit(b"\x0f\x2e\xca")  # ucomiss xmm1,xmm2: actual new XP versus old XP
    a.jcc(0xA, "add_not_lower")  # unordered is not an XP decrease
    a.jcc(JB, "add_lower")
    a.label("add_not_lower")
    # Delay only the original max-rank guard until the effective delta is known.
    a.emit(b"\x8b\x41\x28\x85\xc0")
    a.jcc(JLE, "add_up")
    a.emit(b"\x39\x41\x24")
    a.jcc(JL, "add_up")
    a.emit(b"\x0f\x10\x14\x24\x83\xc4\x10")
    a.jmp_absolute(0x0079D6FC)
    a.label("add_up")
    a.emit(b"\xf3\x0f\x11\x49\x10\x0f\x10\x14\x24\x83\xc4\x10\xff\x75\x14")
    a.call_absolute(EXPERIENCE_TRACKER_LEVEL_CHECK)
    a.jmp_absolute(0x0079D6FC)
    a.label("add_lower")
    a.emit(b"\xf3\x0f\x11\x49\x10\x0f\x10\x14\x24\x83\xc4\x10\xff\x75\x14")
    a.call("down")
    a.jmp_absolute(0x0079D6FC)


def _emit_set(a: Asm) -> None:
    a.label("set")
    a.emit(b"\x50\x0f\x2e\x46\x10")  # preserve the stock feedback argument
    a.jcc(0xA, "set_up")
    a.jcc(JAE, "set_up")
    a.emit(b"\xf3\x0f\x11\x46\x10")
    a.call("down")
    a.jmp_absolute(0x0079D934)
    a.label("set_up")
    a.emit(b"\xf3\x0f\x11\x46\x10")
    a.call_absolute(EXPERIENCE_TRACKER_LEVEL_CHECK)
    a.jmp_absolute(0x0079D934)


def _emit_down(a: Asm) -> None:
    a.label("down")  # thiscall(tracker, feedback), ret 4
    a.emit(b"\x55\x8b\xec\x83\xec\x20\x53\x56\x57\x89\x4d\xfc")
    a.emit(b"\x8b\x01\x81\x78\x10", EXPERIENCE_TRACKER_OBJECT_LEVEL_CHANGE.to_bytes(4, "little"))
    a.jcc(JNE, "stock")  # do not interpret other tracker subclasses as Object trackers
    a.emit(b"\xf3\x0f\x2c\x41\x10")
    # CVTTSS2SI's positive-overflow sentinel must not masquerade as negative XP.
    a.emit(b"\x3d\x00\x00\x00\x80")
    a.jcc(JNE, "xp_integer")
    a.emit(b"\x8b\x51\x10\x85\xd2")
    a.jcc(0x9, "stock")  # jns: the float's sign bit is clear
    a.label("xp_integer")
    a.emit(b"\x89\x45\xec\x8b\x41\x24\x89\x45\xe8")
    a.emit(b"\xff\x71\x0c\x8b\x0d", THE_EXPERIENCE_LEVEL_SYSTEM.to_bytes(4, "little"))
    a.call_absolute(EXPERIENCE_LEVEL_FIND_BY_KEY)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "stock")
    a.emit(b"\x8b\x55\xec\x3b\x50\x18")
    a.jcc(JGE, "stock")  # negative delta alone does not imply losing a level
    a.emit(b"\xff\x75\xfc\x8b\x0d", THE_EXPERIENCE_LEVEL_SYSTEM.to_bytes(4, "little"))
    a.call_absolute(EXPERIENCE_LEVEL_COLLECTION)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "stock")
    a.emit(b"\x89\x45\xf8\x8b\x18\x8b\x3b\x33\xc0\x89\x45\xf4\x89\x45\xf0")
    a.label("select")
    a.emit(b"\x3b\xfb")
    a.jcc(JE, "selected")
    a.emit(b"\x8d\x4f\x08")
    a.call_absolute(EXPERIENCE_LEVEL_RESOLVE)
    a.emit(b"\x8b\xf0")
    a.call_absolute(EXPERIENCE_LEVEL_MODE_ALLOWED)  # implicit esi = effective level
    a.emit(b"\x84\xc0")
    a.jcc(JE, "select_next")
    a.emit(b"\x8b\x86\xfc\x00\x00\x00\x3b\x45\xe8")
    a.jcc(JG, "select_next")
    # Fallback is the lowest threshold, then lowest rank; list order breaks exact ties.
    a.emit(b"\x8b\x55\xf0\x85\xd2")
    a.jcc(JE, "fallback")
    a.emit(b"\x8b\x46\x18\x3b\x42\x18")
    a.jcc(JL, "fallback")
    a.jcc(JNE, "eligible")
    a.emit(b"\x8b\x86\xfc\x00\x00\x00\x3b\x82\xfc\x00\x00\x00")
    a.jcc(JGE, "eligible")
    a.label("fallback")
    a.emit(b"\x89\x75\xf0")
    a.label("eligible")
    a.emit(b"\x8b\x46\x18\x3b\x45\xec")
    a.jcc(JG, "select_next")
    a.emit(b"\x8b\x55\xf4\x85\xd2")
    a.jcc(JE, "choose")
    a.emit(b"\x3b\x42\x18")
    a.jcc(JG, "choose")
    a.jcc(JNE, "select_next")
    a.emit(b"\x8b\x86\xfc\x00\x00\x00\x3b\x82\xfc\x00\x00\x00")
    a.jcc(JLE, "select_next")
    a.label("choose")
    a.emit(b"\x89\x75\xf4")
    a.label("select_next")
    a.emit(b"\x8b\x3f")
    a.jmp("select")
    a.label("selected")
    a.emit(b"\x8b\x45\xf4\x85\xc0")
    a.jcc(JNE, "have_target")
    a.emit(b"\x8b\x45\xf0\x85\xc0")
    a.jcc(JE, "stock")
    a.emit(b"\x89\x45\xf4")
    a.label("have_target")
    a.emit(b"\x8b\x80\xfc\x00\x00\x00\x3b\x45\xe8")
    a.jcc(JGE, "stock")
    a.emit(b"\x89\x45\xe4")  # target rank
    a.emit(b"\x8b\x4d\xfc\xff\x75\xe8\x50")  # old rank, target rank
    a.call("cancel")
    # Find each lost rank in descending order; native helpers own all effect bookkeeping.
    a.label("lost_scan_start")
    a.emit(b"\x8b\x45\xf8\x8b\x18\x8b\x3b\xc7\x45\xe0\x00\x00\x00\x00")
    a.label("lost_scan")
    a.emit(b"\x3b\xfb")
    a.jcc(JE, "lost_selected")
    a.emit(b"\x8d\x4f\x08")
    a.call_absolute(EXPERIENCE_LEVEL_RESOLVE)
    a.emit(b"\x8b\xf0")
    a.call_absolute(EXPERIENCE_LEVEL_MODE_ALLOWED)
    a.emit(b"\x84\xc0")
    a.jcc(JE, "lost_next")
    a.emit(b"\x8b\x86\xfc\x00\x00\x00\x3b\x45\xe8")
    a.jcc(JG, "lost_next")
    a.emit(b"\x3b\x45\xe4")
    a.jcc(JLE, "lost_next")
    a.emit(b"\x8b\x55\xe0\x85\xd2")
    a.jcc(JE, "lost_choose")
    a.emit(b"\x3b\x82\xfc\x00\x00\x00")
    a.jcc(JLE, "lost_next")
    a.label("lost_choose")
    a.emit(b"\x89\x75\xe0")
    a.label("lost_next")
    a.emit(b"\x8b\x3f")
    a.jmp("lost_scan")
    a.label("lost_selected")
    a.emit(b"\x8b\x45\xe0\x85\xc0")
    a.jcc(JE, "change_state")
    a.emit(b"\x8b\x90\xfc\x00\x00\x00\x4a\x89\x55\xe8\x50\x8b\x4d\xfc\x8b\x49\x34")
    a.call("remove")
    a.jmp("lost_scan_start")
    a.label("change_state")
    a.emit(b"\xff\x75\x08\xff\x75\xf4\x8b\x4d\xfc")
    a.call("state")
    a.emit(b"\x8b\x4d\xfc\x8b\x41\x24")
    a.jmp("done")
    a.label("stock")
    a.emit(b"\xff\x75\x08\x8b\x4d\xfc")
    a.call_absolute(EXPERIENCE_TRACKER_LEVEL_CHECK)
    a.label("done")
    a.emit(b"\x5f\x5e\x5b\xc9\xc2\x04\x00")


def _emit_remove(a: Asm) -> None:
    a.label("remove")  # thiscall(object, level), ret 4
    a.emit(b"\x53\x56\x57\x8b\xd9\x8b\x74\x24\x10\x8b\x7e\x30")
    a.label("modifier")
    a.emit(b"\x3b\x7e\x34")
    a.jcc(JAE, "upgrades")
    a.emit(b"\x57\x8b\xcb")  # address of the Utf8String element, not its contents
    a.call_absolute(OBJECT_REMOVE_LEVEL_MODIFIER)
    a.emit(b"\x83\xc7\x04")
    a.jmp("modifier")
    a.label("upgrades")
    a.emit(b"\x8b\x7e\x4c")
    a.label("upgrade")
    a.emit(b"\x3b\x7e\x50")
    a.jcc(JAE, "remove_done")
    a.emit(b"\x8b\x17\x83\x7a\x04\x00")
    a.jcc(JE, "upgrade_next")  # type zero is PLAYER, native Lua dispatch confirms this
    a.emit(b"\x8b\x42\x38\x0f\xa3\x83\x8c\x02\x00\x00")
    a.jcc(JAE, "upgrade_next")  # already absent: duplicate definitions cause only one remove
    a.emit(b"\x52\x8b\xcb")
    a.call_absolute(OBJECT_REMOVE_LEVEL_UPGRADE)
    a.label("upgrade_next")
    a.emit(b"\x83\xc7\x04")
    a.jmp("upgrade")
    a.label("remove_done")
    a.emit(b"\x5f\x5e\x5b\xc2\x04\x00")


def _emit_cancel(a: Asm) -> None:
    a.label("cancel")  # thiscall(tracker, targetRank, oldRank), ret 8
    a.emit(b"\x53\x56\x57\x8b\x41\x34\x8b\x58\x74\xa1")
    a.emit(THE_DELAYED_EXPERIENCE_LEVEL_GRANT_SYSTEM.to_bytes(4, "little"))
    a.emit(b"\x85\xc0")
    a.jcc(JE, "cancel_done")
    a.emit(b"\x8b\x78\x10\x8b\x37")
    a.label("cancel_node")
    a.emit(b"\x3b\xf7")
    a.jcc(JE, "cancel_done")
    a.emit(b"\x39\x5e\x08")
    a.jcc(JNE, "cancel_next")
    a.emit(b"\x8b\x46\x0c\x85\xc0")
    a.jcc(JE, "cancel_next")
    a.emit(b"\x8b\x80\xfc\x00\x00\x00\x3b\x44\x24\x10")
    a.jcc(JLE, "cancel_next")
    a.emit(b"\x3b\x44\x24\x14")
    a.jcc(JG, "cancel_next")
    a.emit(b"\xc7\x46\x0c\x00\x00\x00\x00")
    a.label("cancel_next")
    a.emit(b"\x8b\x36")
    a.jmp("cancel_node")
    a.label("cancel_done")
    a.emit(b"\x5f\x5e\x5b\xc2\x08\x00")


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)
    _emit_add(a)
    _emit_set(a)
    _emit_down(a)
    _emit_remove(a)
    _emit_cancel(a)
    a.label("state")
    # Reproduce the object handler's callee-saved frame and enter after enqueueing.
    a.emit(b"\x56\x57\x8b\x7c\x24\x0c\x8b\xf1")
    a.jmp_absolute(0x0079DAB8)
    a.label("queue")
    a.emit(b"\x83\x7e\x0c\x00")
    a.jcc(JNE, "queue_valid")
    a.jmp_absolute(0x008215B1)
    a.label("queue_valid")
    # A private fourth argument identifies this queue node even during reentrant callbacks.
    a.emit(b"\x56\x8a\x46\x10\x8b\xcd\x50\x53\xff\x76\x0c")
    a.call_absolute(0x00821319)
    a.emit(b"\x83\xc4\x04")
    a.jmp_absolute(0x008215B1)
    for va, label in [(_MODIFIER_RETURN, "modifier_return"), (_UPGRADE_RETURN, "upgrade_return")]:
        a.label(label)
        a.emit(b"\x8b\x45\x14\x83\x78\x0c\x00")
        a.jcc(JNE, label + "_valid")
        a.jmp_absolute(0x0082146D)  # native SEH epilogue; no further effects of this lost grant
        a.label(label + "_valid")
        a.emit(_WINDOWS[va])
        a.jmp_absolute(va + len(_WINDOWS[va]))
    return a


def build_code(base_va: int) -> bytes:
    """Relocatable, code-only helpers; no new persistent object or XP state."""
    return _assemble(base_va).finish()


def _windows(section_va: int) -> tuple[tuple[int, bytes, bytes], ...]:
    a = _assemble(section_va)
    return tuple(
        (va, old, b"\x90" * len(old) if va == _CAP else jmp_rel32(va, a.label_va(label), len(old)))
        for va, label in [
            (_CAP, ""),
            (_ADD, "add"),
            (_SET, "set"),
            (_QUEUE, "queue"),
            (_MODIFIER_RETURN, "modifier_return"),
            (_UPGRADE_RETURN, "upgrade_return"),
        ]
        for old in [_WINDOWS[va]]
    )


class ExperienceLevelDownPatch(Patch):
    """Remove lost level effects on XP decrease while keeping the stock upward cascade."""

    name = "experience-level-down"
    author = "Ostkannit"
    description = (
        "Lower unit levels on actual XP loss, including at maximum rank, preserving remaining XP. "
        "Remove lost AttributeModifiers and OBJECT upgrades; preserve PLAYER upgrades. "
        "Enable optional dynamic XP bounds with --xp-cap. "
        "Combine with level-grant-special-power-negative-experience for negative Experience powers"
    )

    def __init__(self, xp_cap: bool = False) -> None:
        self.xp_cap = xp_cap

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--xp-cap",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="bound XP by the lowest and highest eligible level thresholds (default: off)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> ExperienceLevelDownPatch:
        return cls(xp_cap=args.xp_cap)

    @classmethod
    def detect(cls, data: bytes | bytearray) -> ExperienceLevelDownPatch | None:
        try:
            patch = cls(xp_cap=find_section(data, _XP_CAP_SECTION) is not None)
            return None if patch.verify(data) else patch
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None

    def apply(self, data: bytearray) -> None:
        for section in (SECTION_NAME, _XP_CAP_SECTION):
            if find_section(data, section) is not None:
                raise ValueError(f"the file already carries a {section} section")
        sites = {**_expected_anchors(data), **_WINDOWS}
        if self.xp_cap:
            sites.update(EXPERIENCE_XP_CAP_WINDOWS)
        for va, old in sites.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(old)])
            if got != old:
                raise ValueError(
                    f"unexpected build at {va:#010x}: expected {old.hex()} got {got.hex()}"
                )
        base = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        for va, old, new in _windows(base):
            apply_byte_patch(data, file_offset(data, va), old, new, self.name)
        if self.xp_cap:
            down_va = _assemble(base).label_va("down")
            cap_base = allocate_section(
                data,
                _XP_CAP_SECTION,
                lambda va: _cap_assemble(va, down_va).finish(),
                _CHARACTERISTICS,
            )
            for va, new in _cap_windows(cap_base).items():
                apply_byte_patch(
                    data, file_offset(data, va), EXPERIENCE_XP_CAP_WINDOWS[va], new, self.name
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section"]
        base, off, size = located
        code = build_code(base)
        problems = []
        if self.xp_cap:
            if _cap_present(data) is None:
                problems.append(f"missing or unexpected {_XP_CAP_SECTION} helper or hooks")
        elif find_section(data, _XP_CAP_SECTION) is not None:
            problems.append("XP bounds are enabled in this file; verify with xp_cap=True")
        if size != len(code) or bytes(data[off : off + len(code)]) != code:
            problems.append(f"unexpected {SECTION_NAME} helper body")
        sites = _expected_anchors(data)
        sites.update({va: new for va, _old, new in _windows(base)})
        for va, expected in sites.items():
            try:
                off = file_offset(data, va)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if bytes(data[off : off + len(expected)]) != expected:
                problems.append(f"unexpected bytes at {va:#010x}")
        return problems


_XP_CAP_SECTION = ".xpcap"


def _cap_assemble(base_va: int, down_va: int) -> Asm:
    a = Asm(base_va)
    a.label("cap_adjust")
    a.emit(b"\x38\x55\x0c")
    a.jcc(JE, "cap_add")
    a.jmp_absolute(0x0079D6D2)  # retain the native x87 adjustment, then enter through cap_add
    for setter, va, label in [(False, 0x0079D6E1, "cap_add"), (True, 0x0079D921, "cap_set")]:
        a.label(label)
        a.emit(EXPERIENCE_XP_CAP_WINDOWS[va])
        # Preserve all integer registers and the complete SSE registers used by the helper.
        a.emit(b"\x60\x83\xec\x40\x0f\x11\x04\x24\x0f\x11\x4c\x24\x10\x0f\x11\x54\x24\x20")
        restore = b"\x0f\x10\x04\x24\x0f\x10\x4c\x24\x10\x0f\x10\x54\x24\x20\x83\xc4\x40\x61"
        a.call("ceiling")
        a.emit(b"\x85\xc0")
        a.jcc(JE, label + "_done")
        a.emit(
            b"\x89\x54\x24\x30\x8b\x4c\x24\x58\xf3\x0f\x2a\x50\x18\xf3\x0f\x10\x49\x10\x0f\x2e\xca"
        )
        a.jcc(0xA, label + "_done")  # do not reinterpret unordered old XP
        a.jcc(JBE, label + "_old_ready")
        a.emit(b"\xf3\x0f\x11\x51\x10\x0f\x28\xca")  # normalize a saved reserve first
        a.label(label + "_old_ready")
        if not setter:
            a.emit(b"\xf3\x0f\x58\xc8\x0f\x2e\xca")  # normalized old + effective delta
        else:
            a.emit(b"\x0f\x2e\xc2")
        a.jcc(0xA, label + "_done")
        a.jcc(JBE, label + "_floor")
        if setter:
            a.emit(b"\x0f\x28\xc2")
        else:
            # Store the capped positive result directly; subtraction/readdition can
            # lose the entire ceiling when old XP has a very large negative magnitude.
            a.emit(b"\xf3\x0f\x11\x51\x10\x0f\x57\xc0")
        a.jmp(label + "_save")
        a.label(label + "_floor")
        a.emit(b"\x8b\x54\x24\x30\xf3\x0f\x2a\x52\x18")
        a.emit(b"\x0f\x2e\xc2" if setter else b"\x0f\x2e\xca")
        a.jcc(0xA, label + "_done")
        a.jcc(JAE, label + "_done")
        a.emit(b"\x0f\x28\xc2")
        if not setter:
            # Keep old XP intact: the normal add/down path must observe the decrease.
            a.emit(b"\xf3\x0f\x5c\x41\x10\xf3\x0f\x10\x49\x10\xf3\x0f\x58\xc8\x0f\x2e\xca")
            a.jcc(0xA, label + "_exact_floor")
            a.jcc(JNE, label + "_exact_floor")
        a.label(label + "_save")
        a.emit(b"\x0f\x11\x04\x24")
        a.label(label + "_done")
        a.emit(restore)
        a.jmp_absolute(va + len(EXPERIENCE_XP_CAP_WINDOWS[va]))
        if not setter:
            a.label(label + "_exact_floor")
            # Catastrophic cancellation or infinity cannot encode a suitable delta.
            # Decide direction before storing, then reuse the unchanged downward helper.
            a.emit(b"\x0f\x2e\x51\x10\xf3\x0f\x11\x51\x10")
            a.jcc(JB, label + "_floor_down")
            a.emit(restore, b"\xff\x75\x14")
            a.call_absolute(EXPERIENCE_TRACKER_LEVEL_CHECK)
            a.jmp_absolute(0x0079D6FC)
            a.label(label + "_floor_down")
            a.emit(restore, b"\xff\x75\x14")
            a.call_absolute(down_va)
            a.jmp_absolute(0x0079D6FC)

    a.label("cap_next")
    a.emit(b"\x52\x85\xc0")
    a.jcc(JE, "cap_next_ready")
    a.emit(b"\x8b\x16\x81\x7a\x10", EXPERIENCE_TRACKER_OBJECT_LEVEL_CHANGE.to_bytes(4, "little"))
    a.jcc(JNE, "cap_next_ready")
    a.emit(b"\x8b\x56\x28\x85\xd2")
    a.jcc(JLE, "cap_next_ready")
    a.emit(b"\x39\x90\xfc\x00\x00\x00")
    a.jcc(JLE, "cap_next_ready")
    a.emit(b"\x33\xc0")  # no native upward grant above a configured MaxRank
    a.label("cap_next_ready")
    a.emit(b"\x5a\x8b\xf8\x85\xff")
    a.jcc(JE, "cap_next_end")
    a.jmp_absolute(0x0079D181)
    a.label("cap_next_end")
    a.jmp_absolute(0x0079D1A2)

    a.label("ceiling")  # thiscall(tracker), EAX = highest record, EDX = lowest record
    a.emit(b"\x55\x8b\xec\x83\xec\x0c\x53\x56\x57\x89\x4d\xfc\x33\xc0\x89\x45\xf8\x89\x45\xf4")
    a.emit(b"\x8b\x11\x81\x7a\x10", EXPERIENCE_TRACKER_OBJECT_LEVEL_CHANGE.to_bytes(4, "little"))
    a.jcc(JNE, "ceiling_done")
    a.emit(b"\x51\x8b\x0d", THE_EXPERIENCE_LEVEL_SYSTEM.to_bytes(4, "little"))
    a.call_absolute(EXPERIENCE_LEVEL_COLLECTION)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "ceiling_done")
    a.emit(b"\x8b\x18\x8b\x3b")
    a.label("ceiling_scan")
    a.emit(b"\x3b\xfb")
    a.jcc(JE, "ceiling_done")
    a.emit(b"\x8d\x4f\x08")
    a.call_absolute(EXPERIENCE_LEVEL_RESOLVE)
    a.emit(b"\x8b\xf0")
    a.call_absolute(EXPERIENCE_LEVEL_MODE_ALLOWED)
    a.emit(b"\x84\xc0")
    a.jcc(JE, "ceiling_next")
    a.emit(b"\x8b\x4d\xfc\x8b\x51\x28\x85\xd2")
    a.jcc(JLE, "ceiling_eligible")
    a.emit(b"\x39\x96\xfc\x00\x00\x00")
    a.jcc(JG, "ceiling_next")
    a.label("ceiling_eligible")
    a.emit(b"\x8b\x55\xf4\x85\xd2")
    a.jcc(JE, "floor_choose")
    a.emit(b"\x8b\x86\xfc\x00\x00\x00\x3b\x82\xfc\x00\x00\x00")
    a.jcc(JL, "floor_choose")
    a.jcc(JNE, "ceiling_compare")
    a.emit(b"\x8b\x46\x18\x3b\x42\x18")
    a.jcc(JGE, "ceiling_compare")
    a.label("floor_choose")
    a.emit(b"\x89\x75\xf4")
    a.label("ceiling_compare")
    a.emit(b"\x8b\x55\xf8\x85\xd2")
    a.jcc(JE, "ceiling_choose")
    a.emit(b"\x8b\x86\xfc\x00\x00\x00\x3b\x82\xfc\x00\x00\x00")
    a.jcc(JG, "ceiling_choose")
    a.jcc(JNE, "ceiling_next")
    a.emit(b"\x8b\x46\x18\x3b\x42\x18")
    a.jcc(JLE, "ceiling_next")
    a.label("ceiling_choose")
    a.emit(b"\x89\x75\xf8")
    a.label("ceiling_next")
    a.emit(b"\x8b\x3f")
    a.jmp("ceiling_scan")
    a.label("ceiling_done")
    a.emit(b"\x8b\x45\xf8\x8b\x55\xf4\x5f\x5e\x5b\xc9\xc3")
    return a


def _cap_windows(base_va: int) -> dict[int, bytes]:
    a = _cap_assemble(base_va, 0)  # call destination does not affect label/window offsets
    return {
        va: jmp_rel32(va, a.label_va(label), len(EXPERIENCE_XP_CAP_WINDOWS[va]))
        for va, label in [
            (0x0079D6CD, "cap_adjust"),
            (0x0079D6E1, "cap_add"),
            (0x0079D921, "cap_set"),
            (0x0079D17B, "cap_next"),
        ]
    }


def _cap_present(data: bytes | bytearray) -> tuple[int, int, int] | None:
    located = find_section(data, _XP_CAP_SECTION)
    if located is None:
        return None
    base, off, size = located
    down = find_section(data, SECTION_NAME)
    if down is None:
        return None
    code = _cap_assemble(base, _assemble(down[0]).label_va("down")).finish()
    if size != len(code) or bytes(data[off : off + size]) != code:
        return None
    for va, expected in _cap_windows(base).items():
        try:
            off = file_offset(data, va)
        except ValueError:
            return None
        if bytes(data[off : off + len(expected)]) != expected:
            return None
    return located


def _expected_anchors(data: bytes | bytearray) -> dict[int, bytes]:
    sites = {
        va: _compatible_anchor(data, va, old) for va, old in EXPERIENCE_LEVEL_DOWN_ANCHORS.items()
    }
    cap = _cap_present(data)
    if cap is not None:
        for va, old in sites.items():
            blob = bytearray(old)
            for at, new in _cap_windows(cap[0]).items():
                if va <= at and at + len(new) <= va + len(blob):
                    blob[at - va : at - va + len(new)] = new
            sites[va] = bytes(blob)
    return sites
