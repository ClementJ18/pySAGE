"""Re-evaluate ``ConflictsWith`` for active, standard ``UpgradeModule`` interfaces.

The stock Object dispatcher never calls an active module again. This patch admits interfaces
that satisfy the common UpgradeModule vtable contract and makes a newly satisfied conflict take
the same virtual removal path as losing a ``TriggeredBy`` upgrade. The historical patch name is
kept because it is part of pySAGE's public CLI and manifest surface.

Derivation and the deliberately conservative interface contract:
``../../docs/attribute-modifier-aura-conflicts.md``.
"""

from __future__ import annotations

from ...addresses import (
    OBJECT_DISPATCH_UPGRADES,
    OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE,
    OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES,
    OBJECT_DISPATCH_UPGRADES_BUILD_MASK,
    OBJECT_DISPATCH_UPGRADES_BYTES,
    OBJECT_DISPATCH_UPGRADES_CALLBACK,
    OBJECT_DISPATCH_UPGRADES_CALLBACK_BYTES,
    OBJECT_DISPATCH_UPGRADES_POST_CALLBACK,
    UPGRADE_INTERFACE_GET_FLAG,
    UPGRADE_MASK_ANY,
    UPGRADE_MASK_INIT,
    UPGRADE_MASK_TEST_ALL,
    UPGRADE_MASK_TEST_ANY,
    UPGRADE_MODULE_CONFLICT_ANCHORS,
    UPGRADE_MODULE_ON_ADDED,
    UPGRADE_MODULE_REMOVAL,
    UPGRADE_MODULE_REMOVAL_WITH_MODEL_CONDITION,
    UPGRADE_MODULE_REMOVE_EFFECTS,
    UPGRADE_MODULE_SET_FLAG,
)
from ...asm import JE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32, u32

__all__ = ["SECTION_NAME", "AttributeModifierAuraConflictsPatch", "build_code"]

SECTION_NAME = ".aurconf"


def _assemble(base_va: int) -> Asm:
    """Build the active conflict transition, the type gate and the callback trampoline."""
    a = Asm(base_va)

    # __thiscall(iface, heldMask), ret 4. Build both ModuleData masks through the interface so
    # specialised layouts (the aura is one) keep working. A satisfied conflict is expressed as
    # a removal of the complete TriggeredBy mask; the virtual +0x0c handler therefore performs
    # the exact per-type state transition used for a real TriggeredBy loss.
    a.label("active")
    a.emit(b"\x55\x8b\xec\x81\xec\x20\x01\x00\x00\x56\x8b\xf1")
    a.emit(b"\x8d\x8d\xe0\xfe\xff\xff")  # lea ecx, [ebp-0x120] ; TriggeredBy
    a.call_absolute(UPGRADE_MASK_INIT)
    a.emit(b"\x8d\x8d\x70\xff\xff\xff")  # lea ecx, [ebp-0x90] ; ConflictsWith
    a.call_absolute(UPGRADE_MASK_INIT)
    a.emit(b"\x8d\x85\x70\xff\xff\xff\x50")
    a.emit(b"\x8d\x85\xe0\xfe\xff\xff\x50")
    a.emit(b"\x8b\x06\x8b\xce\xff\x50\x2c")
    a.emit(b"\x8d\x8d\x70\xff\xff\xff")
    a.call_absolute(UPGRADE_MASK_ANY)
    a.emit(b"\x84\xc0")
    a.jcc(JE, "active_done")  # an empty all-of mask must never disable a module
    a.emit(b"\x8b\x06\x8b\xce\xff\x50\x38")
    a.emit(b"\x84\xc0\x8b\x4d\x08")
    a.emit(b"\x8d\x85\x70\xff\xff\xff\x50")
    a.jcc(JE, "test_any")
    a.call_absolute(UPGRADE_MASK_TEST_ALL)
    a.jmp("tested")
    a.label("test_any")
    a.call_absolute(UPGRADE_MASK_TEST_ANY)
    a.label("tested")
    a.emit(b"\x84\xc0")
    a.jcc(JE, "active_done")

    # Slot +0x0c clears the flag and, for the 0x8d2901 variant, clears its ModelCondition.
    # Only a true return denotes the same transition a real TriggeredBy loss would have made.
    a.emit(b"\x8d\x85\xe0\xfe\xff\xff\x50")
    a.emit(b"\x8b\x06\x8b\xce\xff\x50\x0c\x84\xc0")
    a.jcc(JE, "active_done")
    # The common removal helper must observe the module as active. It then runs slot +0x20 and
    # the standard setter, including Permanent semantics. The final store also covers the
    # companion upgrade-module-removal patch's transient state.
    a.emit(b"\xc6\x46\x04\x01\x56")
    a.call_absolute(UPGRADE_MODULE_REMOVE_EFFECTS)
    a.emit(b"\x83\xc4\x04\xc6\x46\x04\x00")
    a.label("active_done")
    a.emit(b"\x33\xc0\x5e\xc9\xc2\x04\x00")

    # The stock active getter remains authoritative. Only the two known standard removal
    # callbacks, together with the rest of the standard vtable contract, may bypass the skip.
    a.label("gate")
    a.emit(OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES[:8])
    a.jcc(JE, "build_mask")
    a.emit(b"\x8b\x03")  # mov eax, [ebx] ; vtable
    a.emit(b"\x81\x38", u32(UPGRADE_INTERFACE_GET_FLAG))
    a.jcc(JNE, "post_callback")
    a.emit(b"\x81\x78\x04", u32(UPGRADE_MODULE_ON_ADDED))
    a.jcc(JNE, "post_callback")
    a.emit(b"\x8b\x50\x0c")
    a.emit(b"\x81\xfa", u32(UPGRADE_MODULE_REMOVAL))
    a.jcc(JE, "removal_ok")
    a.emit(b"\x81\xfa", u32(UPGRADE_MODULE_REMOVAL_WITH_MODEL_CONDITION))
    a.jcc(JNE, "post_callback")
    a.label("removal_ok")
    a.emit(b"\x81\x78\x24", u32(UPGRADE_MODULE_SET_FLAG))
    a.jcc(JNE, "post_callback")
    a.emit(b"\x83\x78\x2c\x00")  # no mask builder: retain stock active skip
    a.jcc(JE, "post_callback")
    a.emit(b"\x83\x78\x38\x00")
    a.jcc(JNE, "build_mask")
    a.label("post_callback")
    a.jmp_absolute(OBJECT_DISPATCH_UPGRADES_POST_CALLBACK)
    a.label("build_mask")
    a.jmp_absolute(OBJECT_DISPATCH_UPGRADES_BUILD_MASK)

    # This replaces the one virtual +0x04 call after the stock held-mask merge. Inactive modules
    # receive the displaced call byte-for-byte; active qualified modules run the transition above.
    a.label("callback")
    a.emit(b"\x80\x7b\x04\x00")
    a.jcc(JE, "callback_stock")
    a.emit(b"\x8d\x85\x68\xff\xff\xff\x50\x8b\xcb")
    a.call("active")
    a.jmp_absolute(OBJECT_DISPATCH_UPGRADES_POST_CALLBACK)
    a.label("callback_stock")
    a.emit(OBJECT_DISPATCH_UPGRADES_CALLBACK_BYTES)
    a.jmp_absolute(OBJECT_DISPATCH_UPGRADES_POST_CALLBACK)
    return a


def build_code(base_va: int) -> bytes:
    """Return the relocatable helper body."""
    return _assemble(base_va).finish()


def _windows(base_va: int) -> dict[int, bytes]:
    a = _assemble(base_va)
    return {
        OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE: jmp_rel32(
            OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE,
            a.label_va("gate"),
            len(OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES),
        ),
        OBJECT_DISPATCH_UPGRADES_CALLBACK: jmp_rel32(
            OBJECT_DISPATCH_UPGRADES_CALLBACK,
            a.label_va("callback"),
            len(OBJECT_DISPATCH_UPGRADES_CALLBACK_BYTES),
        ),
    }


def _dispatcher(base_va: int | None = None) -> bytes:
    blob = bytearray(OBJECT_DISPATCH_UPGRADES_BYTES)
    if base_va is not None:
        for va, replacement in _windows(base_va).items():
            start = va - OBJECT_DISPATCH_UPGRADES
            blob[start : start + len(replacement)] = replacement
    return bytes(blob)


def _companion_removal_is_valid(data: bytes | bytearray) -> bool:
    """The companion patch rewrites two called anchors but preserves their entry contracts."""
    if find_section(data, ".uprem") is None:
        return False
    # Local import avoids making either patch's module import order significant.
    from ..upgrades.upgrade_module_removal import UpgradeModuleRemovalPatch  # noqa: PLC0415

    return not UpgradeModuleRemovalPatch().verify(data)


class AttributeModifierAuraConflictsPatch(Patch):
    """Make later ConflictsWith grants remove active standard UpgradeModule effects."""

    name = "attribute-modifier-aura-conflicts"
    author = "Ostkannit"
    runtime_verified = "partly"
    description = (
        "Deactivate active standard UpgradeModules when ConflictsWith becomes satisfied, using "
        "the same removal lifecycle as loss of TriggeredBy. Uses existing INI fields; no new tokens"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        companion = _companion_removal_is_valid(data)
        for va, expected in UPGRADE_MODULE_CONFLICT_ANCHORS.items():
            if companion and va in {UPGRADE_MODULE_REMOVE_EFFECTS, UPGRADE_MODULE_REMOVAL}:
                continue
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build at {va:#010x}: expected {expected.hex()} got {got.hex()}"
                )
        off = file_offset(data, OBJECT_DISPATCH_UPGRADES)
        got = bytes(data[off : off + len(OBJECT_DISPATCH_UPGRADES_BYTES)])
        if got != OBJECT_DISPATCH_UPGRADES_BYTES:
            raise ValueError(
                f"unexpected build at {OBJECT_DISPATCH_UPGRADES:#010x}: "
                f"expected {OBJECT_DISPATCH_UPGRADES_BYTES.hex()} got {got.hex()}"
            )

        base = allocate_section(data, SECTION_NAME, build_code, 0x60000020)
        for va, replacement in _windows(base).items():
            stock = {
                OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE: OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES,
                OBJECT_DISPATCH_UPGRADES_CALLBACK: OBJECT_DISPATCH_UPGRADES_CALLBACK_BYTES,
            }[va]
            apply_byte_patch(data, file_offset(data, va), stock, replacement, self.name)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section"]
        base, off, size = located
        code = build_code(base)
        problems: list[str] = []
        if size != len(code) or bytes(data[off : off + size]) != code:
            problems.append(f"unexpected {SECTION_NAME} helper body")
        try:
            dispatch_off = file_offset(data, OBJECT_DISPATCH_UPGRADES)
            got = bytes(data[dispatch_off : dispatch_off + len(OBJECT_DISPATCH_UPGRADES_BYTES)])
            if got != _dispatcher(base):
                problems.append(f"unexpected bytes at {OBJECT_DISPATCH_UPGRADES:#010x}")
        except ValueError as exc:
            problems.append(str(exc))

        companion = _companion_removal_is_valid(data)
        for va, expected in UPGRADE_MODULE_CONFLICT_ANCHORS.items():
            if companion and va in {UPGRADE_MODULE_REMOVE_EFFECTS, UPGRADE_MODULE_REMOVAL}:
                continue
            try:
                anchor_off = file_offset(data, va)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if bytes(data[anchor_off : anchor_off + len(expected)]) != expected:
                problems.append(f"unexpected bytes at {va:#010x}")
        return problems
