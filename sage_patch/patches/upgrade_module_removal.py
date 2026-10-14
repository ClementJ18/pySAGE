"""Restore active UpgradeMux state only for a confirmed OBJECT removal event.

The dispatcher keeps Permanent and inactive reset behavior. A transient nonzero
state guards recursive removal/reset callbacks; no persistent field is added.
Evidence: `../docs/upgrade-module-removal.md`.
"""

from __future__ import annotations

from ..addresses import UPGRADE_MODULE_REMOVAL_ANCHORS, UPGRADE_MODULE_REMOVAL_WINDOWS
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32

__all__ = ["SECTION_NAME", "UpgradeModuleRemovalPatch", "build_code"]

SECTION_NAME = ".uprem"


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)
    a.label("event")
    a.emit(b"\xc6\x43\x04\x01\x53")
    a.call_absolute(0x008D2688)
    # Permanent skips the native setter, but the removed event still ends inactive.
    a.emit(b"\xc6\x43\x04\x00")
    a.jmp_absolute(0x006914A6)  # retain the original POP ECX argument cleanup
    a.label("dispatch")
    a.emit(b"\x8b\x44\x24\x04\x80\x78\x04\x02")
    a.jcc(JNE, "dispatch_native")
    a.emit(b"\xc3")  # nested reset of this module: already removing
    a.label("dispatch_native")
    a.emit(UPGRADE_MODULE_REMOVAL_WINDOWS[0x008D2688])
    a.jmp_absolute(0x008D268D)
    a.label("callback")
    # Getter tests remain true during removal, while event tests accept only state 1.
    a.emit(b"\x80\x7e\x04\x01")
    a.jcc(JNE, "callback_native")
    a.emit(b"\xc6\x46\x04\x02")
    a.label("callback_native")
    a.emit(UPGRADE_MODULE_REMOVAL_WINDOWS[0x008D2698])
    a.jmp_absolute(0x008D269F)  # native setter clears the transient state
    a.label("ready")
    # SharedSyncedTimer's native readiness branch bypasses the local pause check.
    a.emit(b"\x83\x79\x0c\x00")
    a.jcc(JE, "ready_native")
    a.emit(b"\x33\xc0\xc3")
    a.label("ready_native")
    a.emit(UPGRADE_MODULE_REMOVAL_WINDOWS[0x00896C72])
    a.jmp_absolute(0x00896C79)
    return a


def build_code(base_va: int) -> bytes:
    """Build relocatable code with no runtime writes to the cave."""
    return _assemble(base_va).finish()


def _windows(base_va: int) -> dict[int, bytes]:
    a = _assemble(base_va)
    return {
        **{
            va: jmp_rel32(va, a.label_va(label), len(UPGRADE_MODULE_REMOVAL_WINDOWS[va]))
            for va, label in [
                (0x006914A0, "event"),
                (0x008D2688, "dispatch"),
                (0x008D2698, "callback"),
                (0x00896C72, "ready"),
            ]
        },
        0x008D27D3: bytes.fromhex("807e04017508"),  # active == 1, not in removal == 2
    }


def _anchors(base_va: int | None = None) -> dict[int, bytes]:
    sites = dict(UPGRADE_MODULE_REMOVAL_ANCHORS)
    if base_va is not None:
        replacements = _windows(base_va)
        for va, old in sites.items():
            blob = bytearray(old)
            for at, new in replacements.items():
                if va <= at and at + len(new) <= va + len(blob):
                    blob[at - va : at - va + len(new)] = new
            sites[va] = bytes(blob)
    return sites


def _compatible_anchor(data: bytes | bytearray, va: int, old: bytes) -> bytes:
    """Let the level-down fingerprint accept this fully verified companion patch."""
    if va not in UPGRADE_MODULE_REMOVAL_ANCHORS:
        return old
    located = find_section(data, SECTION_NAME)
    if located is not None and not UpgradeModuleRemovalPatch().verify(data):
        expected = _anchors(located[0]).get(va)
        if expected is not None and len(expected) == len(old):
            return expected
    return old


class UpgradeModuleRemovalPatch(Patch):
    """Run native reversible UpgradeModule handlers after an OBJECT upgrade is removed."""

    name = "upgrade-module-removal"
    author = "Ostkannit"
    description = (
        "Reverse UpgradeModule effects on OBJECT upgrade removal with Permanent = No (default). "
        "Preserve Permanent = Yes, native reset behavior and PLAYER upgrades"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for va, old in {**_anchors(), **UPGRADE_MODULE_REMOVAL_WINDOWS}.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(old)])
            if got != old:
                raise ValueError(
                    f"unexpected build at {va:#010x}: expected {old.hex()} got {got.hex()}"
                )
        base = allocate_section(data, SECTION_NAME, build_code, 0x60000020)
        for va, new in _windows(base).items():
            apply_byte_patch(
                data, file_offset(data, va), UPGRADE_MODULE_REMOVAL_WINDOWS[va], new, self.name
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section"]
        base, off, size = located
        code = build_code(base)
        problems = []
        if size != len(code) or bytes(data[off : off + size]) != code:
            problems.append(f"unexpected {SECTION_NAME} helper body")
        for va, expected in {**_anchors(base), **_windows(base)}.items():
            try:
                off = file_offset(data, va)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if bytes(data[off : off + len(expected)]) != expected:
                problems.append(f"unexpected bytes at {va:#010x}")
        return problems
