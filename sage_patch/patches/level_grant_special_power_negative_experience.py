"""Allow negative `Experience` on RotWK's `LevelGrantSpecialPower`.

Change only the XP distribution gate from JLE to JE; the stock target selection,
signed conversions and ExperienceTracker eligibility checks remain intact.
Derivation: `../docs/level-grant-special-power-negative-experience.md`.
"""

from ..addresses import (
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, file_offset

__all__ = ["LevelGrantSpecialPowerNegativeExperiencePatch"]

_REPLACEMENT = bytes.fromhex("0f8491000000")


class LevelGrantSpecialPowerNegativeExperiencePatch(Patch):
    """Pass nonzero signed XP through the existing LevelGrantSpecialPower paths."""

    name = "level-grant-special-power-negative-experience"
    author = "Ostkannit"
    description = (
        "Allow negative Experience on LevelGrantSpecialPower (for example Experience = -250). "
        "No automatic level-down or maximum-level special handling; no new INI fields"
    )

    def apply(self, data: bytearray) -> None:
        apply_byte_patch(
            data,
            file_offset(data, LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE),
            LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES,
            _REPLACEMENT,
            "LevelGrantSpecialPower Experience gate: JLE -> JE",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            off = file_offset(data, LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE)
        except ValueError as exc:
            return [str(exc)]
        if bytes(data[off : off + len(_REPLACEMENT)]) != _REPLACEMENT:
            return ["LevelGrantSpecialPower Experience gate does not hold the expected JE"]
        return []
