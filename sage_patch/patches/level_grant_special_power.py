"""Allow signed XP and INI-controlled target relationships on LevelGrantSpecialPower.

The XP gate changes from JLE to JE; the fixed relationship mask changes from 4 to 7.
The AcceptanceFilter, signed conversions and tracker eligibility checks remain native.
Derivation: `../docs/level-grant-special-power.md`.
"""

from ..addresses import (
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES,
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_BYTES,
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_IMMEDIATE,
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_INSTRUCTION,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, file_offset

__all__ = ["LevelGrantSpecialPowerPatch"]

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


class LevelGrantSpecialPowerPatch(Patch):
    """Pass signed XP and all relationships to the existing configurable target filter."""

    name = "level-grant-special-power"
    author = "Ostkannit"
    description = (
        "Allow negative Experience on LevelGrantSpecialPower (for example Experience = -250). "
        "Fix the fixed ALLIES restriction so AcceptanceFilter controls target relationships. "
        "No automatic level-down or new INI fields"
    )

    def apply(self, data: bytearray) -> None:
        # Reject either incompatible instruction before changing the other one.
        for va, (old, _new) in _WINDOWS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(old)])
            if got != old:
                raise ValueError(f"{self.name} @{va:#010x}: expected {old.hex()} got {got.hex()}")
        apply_byte_patch(
            data,
            file_offset(data, LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE),
            LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES,
            _REPLACEMENT,
            "LevelGrantSpecialPower Experience gate: JLE -> JE",
        )
        apply_byte_patch(
            data,
            file_offset(data, LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_IMMEDIATE),
            b"\x04",
            b"\x07",
            "LevelGrantSpecialPower relationship mask: ALLIES -> all relationships",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems = []
        for va, (_old, new) in _WINDOWS.items():
            try:
                off = file_offset(data, va)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if bytes(data[off : off + len(new)]) != new:
                problems.append(f"unexpected LevelGrantSpecialPower instruction at {va:#010x}")
        return problems
