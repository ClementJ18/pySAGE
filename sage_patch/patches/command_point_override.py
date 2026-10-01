"""Keep a script's command-point override when a player is defeated.

`OVERRIDE_PLAYER_COMMAND_POINTS` stores a base and hard cap and marks the player's command-point
bookkeeping as overridden. Defeating any player re-runs the bookkeeping's initialiser for every
player, and stock that initialiser treats the mark only as a floor: it keeps
`max(override, GameData value)` and then scales the hard cap by the lobby's command-point factor
again. A map that lowered command points, or one that read the factor as a game mode and reset it
to normal, gets the GameData numbers back the moment someone is defeated.

The edit is the initialiser's merge: an overridden bookkeeping now returns before it is touched,
so the override stands exactly until a script overrides it again. Everything else is unchanged -
a bookkeeping no script has overridden is recomputed, scaled and stored as stock.

Derivation: `../docs/command-point-override.md`.
"""

from __future__ import annotations

from ..addresses import (
    COMMAND_POINTS_BASE,
    COMMAND_POINTS_HARD_CAP,
    COMMAND_POINTS_INIT_FACTOR,
    COMMAND_POINTS_INIT_FACTOR_BYTES,
    COMMAND_POINTS_INIT_MERGE,
    COMMAND_POINTS_INIT_MERGE_BYTES,
    COMMAND_POINTS_INIT_RETURN,
    COMMAND_POINTS_INIT_RETURN_BYTES,
    COMMAND_POINTS_OVERRIDDEN,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["MERGE", "CommandPointOverridePatch"]


def _rel8(at: int, size: int, target: int) -> int:
    disp = target - (at + size)
    if not -0x80 <= disp < 0x80:
        raise ValueError(f"{target:#010x} is out of rel8 range of {at:#010x}")
    return disp & 0xFF


def _merge() -> bytes:
    """The merge as it becomes: return early when overridden, otherwise store both and go on to
    the factor - the stock unconditional stores, without the `max` the override used to take."""
    at = COMMAND_POINTS_INIT_MERGE
    code = bytearray()
    code += bytes([0x80, 0x7F, COMMAND_POINTS_OVERRIDDEN, 0x00])  # cmp byte [edi+0x2c], 0
    code += bytes([0x75, _rel8(at + len(code), 2, COMMAND_POINTS_INIT_RETURN)])  # jne return
    code += bytes([0x89, 0x77, COMMAND_POINTS_HARD_CAP])  # mov [edi+0x10], esi
    code += bytes([0x89, 0x5F, COMMAND_POINTS_BASE])  # mov [edi+4], ebx
    code += bytes([0xEB, _rel8(at + len(code), 2, COMMAND_POINTS_INIT_FACTOR)])  # jmp factor
    code += b"\x90" * (len(COMMAND_POINTS_INIT_MERGE_BYTES) - len(code))
    return bytes(code)


#: The merge's replacement, exactly as wide as the stock merge.
MERGE = _merge()


class CommandPointOverridePatch(Patch):
    name = "command-point-override"
    author = "officialNecro"
    description = (
        "Keep the command points a script set with OVERRIDE_PLAYER_COMMAND_POINTS when a player is "
        "defeated. Stock, every defeat recomputes every player's command points, and an override "
        "only survives where it is higher than the GameData value - and its maximum is scaled by "
        "the lobby's command-point factor again - so a lowered or game-mode-corrected override "
        "snaps back. Players no script has overridden are recomputed as stock. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        apply_byte_patch(
            data,
            self._offset(data, COMMAND_POINTS_INIT_MERGE),
            COMMAND_POINTS_INIT_MERGE_BYTES,
            MERGE,
            "command-point init: an override returns before the merge",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        """Raise unless the two places the new merge branches to are what it expects.

        The early return lands on an epilogue and the fall-through on the factor's first
        instruction; neither is this patch's to change, so a build where either moved is refused
        rather than branched into."""
        for va, expected, what in (
            (COMMAND_POINTS_INIT_RETURN, COMMAND_POINTS_INIT_RETURN_BYTES, "epilogue"),
            (COMMAND_POINTS_INIT_FACTOR, COMMAND_POINTS_INIT_FACTOR_BYTES, "factor load"),
        ):
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, not the command-point initialiser's {what} - "
                    "this is not the expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_anchors(data)
        except ValueError as exc:
            return [str(exc)]
        off = self._offset(data, COMMAND_POINTS_INIT_MERGE)
        got = bytes(data[off : off + len(MERGE)])
        if got == MERGE:
            return []
        which = "the stock merge" if got == COMMAND_POINTS_INIT_MERGE_BYTES else "something else"
        return [
            f"{COMMAND_POINTS_INIT_MERGE:#010x} holds {got.hex()} ({which}): the file does not "
            "carry this patch"
        ]
