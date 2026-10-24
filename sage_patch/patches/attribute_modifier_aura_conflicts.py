"""Recheck conflicts when an active AttributeModifierAuraUpdate receives an upgrade.

An aura-only dispatcher exception reaches slot +04 even when active. The evaluator stays stock.
Derivation and INI semantics: `../docs/attribute-modifier-aura-conflicts.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    ATTRIBUTE_MODIFIER_AURA_CONFLICT_ANCHORS,
    ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE,
    OBJECT_DISPATCH_UPGRADES,
    OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE,
    OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES,
    OBJECT_DISPATCH_UPGRADES_BUILD_MASK,
    OBJECT_DISPATCH_UPGRADES_BYTES,
    OBJECT_DISPATCH_UPGRADES_POST_CALLBACK,
    UPGRADE_MASK_ANY,
    UPGRADE_MASK_INIT,
    UPGRADE_MASK_TEST_ALL,
    UPGRADE_MASK_TEST_ANY,
    UPGRADE_MODULE_ON_ADDED,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32

__all__ = ["SECTION_NAME", "AttributeModifierAuraConflictsPatch", "build_code"]

SECTION_NAME = ".aurconf"
_SLOT = ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE + 4


def _assemble(base_va: int) -> Asm:
    """Thiscall(mask), ret 4. Preserve nonvolatile registers and delegate inactive calls intact.

    Two plain 0x90-byte masks occupy [ebp-0x120] and [ebp-0x90]. The stock builder
    takes (triggeredBy, conflictsWith), cleans both arguments, and owns no heap state.
    """
    a = Asm(base_va)
    a.emit(b"\x80\x79\x04\x00")  # cmp byte [ecx+4], 0
    a.jcc(JNE, "active")
    a.jmp_absolute(UPGRADE_MODULE_ON_ADDED)
    a.label("active")
    a.emit(b"\x55\x8b\xec\x81\xec\x20\x01\x00\x00\x56\x8b\xf1")
    a.emit(b"\x8d\x8d\xe0\xfe\xff\xff")  # lea ecx, [ebp-0x120]
    a.call_absolute(UPGRADE_MASK_INIT)
    a.emit(b"\x8d\x8d\x70\xff\xff\xff")  # lea ecx, [ebp-0x90]
    a.call_absolute(UPGRADE_MASK_INIT)
    a.emit(b"\x8d\x85\x70\xff\xff\xff\x50")  # push conflicts
    a.emit(b"\x8d\x85\xe0\xfe\xff\xff\x50")  # push triggers
    a.emit(b"\x8b\xce\x8b\x06\xff\x50\x2c")
    a.emit(b"\x8d\x8d\x70\xff\xff\xff")
    a.call_absolute(UPGRADE_MASK_ANY)
    a.emit(b"\x84\xc0")
    a.jcc(JE, "done")  # empty all-of must not disable every aura
    a.emit(b"\x8b\xce\x8b\x06\xff\x50\x38")
    a.emit(b"\x8b\x4d\x08\x84\xc0")  # ecx = held mask; test all-vs-any
    a.emit(b"\x8d\x85\x70\xff\xff\xff\x50")
    a.jcc(JE, "any")
    a.call_absolute(UPGRADE_MASK_TEST_ALL)
    a.jmp("tested")
    a.label("any")
    a.call_absolute(UPGRADE_MASK_TEST_ANY)
    a.label("tested")
    a.emit(b"\x84\xc0")
    a.jcc(JE, "done")
    a.emit(b"\xc6\x46\x04\x00")  # same state as stock TriggeredBy removal
    a.label("done")
    a.emit(b"\x33\xc0\x5e\xc9\xc2\x04\x00")
    a.label("dispatch")
    # Keep the virtual getter for all modules. Only this aura bypasses the active skip.
    a.emit(OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES[:8])
    a.jcc(JE, "build_mask")
    a.emit(b"\x81\x3b", struct.pack("<I", ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE))
    a.jcc(JE, "build_mask")
    a.jmp_absolute(OBJECT_DISPATCH_UPGRADES_POST_CALLBACK)
    a.label("build_mask")
    a.jmp_absolute(OBJECT_DISPATCH_UPGRADES_BUILD_MASK)
    return a


def build_code(base_va: int) -> bytes:
    """Build the conflict wrapper and the type-restricted dispatcher exception."""
    return _assemble(base_va).finish()


def _gate(base_va: int) -> bytes:
    return jmp_rel32(
        OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE,
        _assemble(base_va).label_va("dispatch"),
        len(OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES),
    )


def _anchors(base_va: int | None = None) -> dict[int, bytes]:
    sites = dict(ATTRIBUTE_MODIFIER_AURA_CONFLICT_ANCHORS)
    sites[OBJECT_DISPATCH_UPGRADES] = OBJECT_DISPATCH_UPGRADES_BYTES
    if base_va is not None:
        table = bytearray(sites[ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE])
        struct.pack_into("<I", table, 4, base_va)
        sites[ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE] = bytes(table)
        dispatcher = bytearray(OBJECT_DISPATCH_UPGRADES_BYTES)
        offset = OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE - OBJECT_DISPATCH_UPGRADES
        dispatcher[offset : offset + len(OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES)] = _gate(
            base_va
        )
        sites[OBJECT_DISPATCH_UPGRADES] = bytes(dispatcher)
    return sites


class AttributeModifierAuraConflictsPatch(Patch):
    """Honor later ConflictsWith upgrades on an already active aura."""

    name = "attribute-modifier-aura-conflicts"
    author = "Ostkannit"
    runtime_verified = "yes"
    description = (
        "Deactivate an active AttributeModifierAuraUpdate when ConflictsWith becomes satisfied, "
        "respecting RequiresAllConflictingTriggers. Uses existing INI fields; no new tokens"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for va, expected in _anchors().items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build at {va:#010x}: expected {expected.hex()} got {got.hex()}"
                )
        base = allocate_section(data, SECTION_NAME, build_code, 0x60000020)
        apply_byte_patch(
            data,
            file_offset(data, _SLOT),
            struct.pack("<I", UPGRADE_MODULE_ON_ADDED),
            struct.pack("<I", base),
            self.name,
        )

        apply_byte_patch(
            data,
            file_offset(data, OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE),
            OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES,
            _gate(base),
            self.name,
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section"]
        base, off, size = located
        code = build_code(base)
        problems = []
        legacy_size = _assemble(base).label_va("dispatch") - base
        if size == legacy_size and bytes(data[off : off + size]) == code[:legacy_size]:
            problems.append("legacy slot-only aura patch: rebuild with the dispatcher exception")
        elif size != len(code) or bytes(data[off : off + size]) != code:
            problems.append(f"unexpected {SECTION_NAME} helper body")
        for va, expected in _anchors(base).items():
            try:
                off = file_offset(data, va)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if bytes(data[off : off + len(expected)]) != expected:
                problems.append(f"unexpected bytes at {va:#010x}")
        return problems
