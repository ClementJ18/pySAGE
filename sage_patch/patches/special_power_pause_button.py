"""Grey paused SpecialPower buttons in the native availability evaluator.

Only the failed-isReady UI branch changes. Gameplay pause/resume, upgrade removal
and XP processing remain native or owned by their existing patches.
Evidence: `../docs/special-power-pause-button.md`.
"""

from __future__ import annotations

from ..addresses import (
    CONTROL_BAR_SPECIAL_POWER_PAUSE_ANCHORS,
    CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL,
    CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES,
    CONTROL_BAR_UNAVAILABLE,
)
from ..asm import JE, JG, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32

__all__ = ["SECTION_NAME", "SpecialPowerPauseButtonPatch", "build_code"]

SECTION_NAME = ".sppause"


def build_code(base_va: int) -> bytes:
    """Identify the native interface layout before interpreting its pause counter."""
    a = Asm(base_va)
    a.emit(b"\x8b\x06\x81\x78\x3c\x31\x6e\x89\x00")
    a.jcc(JE, "ordinary")  # startPowerRecharge: interface at module +0x10
    a.emit(b"\x81\x78\x3c\x00\x15\x99\x00")
    a.jcc(JE, "update")  # SpecialPowerUpdate interface at module +0x24
    a.jmp("percent")  # unknown layout: retain stock availability
    a.label("ordinary")
    a.emit(b"\x83\x7e\x0c\x00")
    a.jcc(JG, "disabled")
    a.jmp("percent")
    a.label("update")
    a.emit(b"\x83\x7e\x08\x00")
    a.jcc(JG, "disabled")
    a.label("percent")
    a.emit(CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES)
    a.jmp_absolute(CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL + 7)
    a.label("disabled")
    a.jmp_absolute(CONTROL_BAR_UNAVAILABLE)
    return a.finish()


def _replacement(base_va: int) -> bytes:
    return jmp_rel32(CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL, base_va, 7)


class SpecialPowerPauseButtonPatch(Patch):
    """Use native disabled status for a paused, not-ready SpecialPower button."""

    name = "special-power-pause-button"
    author = "Ostkannit"
    description = (
        "Grey not-ready SpecialPower CommandButtons with a positive pause count. "
        "Preserve normal cooldowns, ready buttons and gameplay; no INI changes"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        sites = dict(CONTROL_BAR_SPECIAL_POWER_PAUSE_ANCHORS)
        sites[CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL] = CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES
        for va, old in sites.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(old)])
            if got != old:
                raise ValueError(
                    f"unexpected build at {va:#010x}: expected {old.hex()} got {got.hex()}"
                )
        base = allocate_section(data, SECTION_NAME, build_code, 0x60000020)
        apply_byte_patch(
            data,
            file_offset(data, CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL),
            CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES,
            _replacement(base),
            self.name,
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
        sites = dict(CONTROL_BAR_SPECIAL_POWER_PAUSE_ANCHORS)
        sites[CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL] = _replacement(base)
        for va, expected in sites.items():
            try:
                off = file_offset(data, va)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if bytes(data[off : off + len(expected)]) != expected:
                problems.append(f"unexpected bytes at {va:#010x}")
        return problems
