"""Per-player visibility, read from the engine's own shroud grid.

Everything else `sage_live` reads is whole-map; this is what lets `Observation.under_fog` hide what
a player cannot see. The engine keeps a grid of cells with one `u16` per player: the number of that
player's revealers covering the cell. 0 is `HIDDEN`, positive is `CLEAR`, and `0xFFFF` (seats not in
play) is `UNTRACKED`. The lookup mirrors the engine's own (`0x00B4FB20`).

There is no explored-but-not-visible state in this grid, so remembering what was seen is the
consumer's job. Layout and measurements: `sage_patch/docs/fog-of-war.md`.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum

__all__ = ["MAX_SHROUD_PLAYERS", "CellShroud", "Point", "ShroudGrid"]

# A world position. Accepts `Vec3` as it comes off an object, and a bare (x, y) for the
# callers that only have ground coordinates - the grid is two-dimensional either way.
Point = tuple[float, float] | tuple[float, float, float]

# The engine's own bound: `0x00B4FB20` rejects a player index outside `0 <= p < 0x14` before it
# touches the grid, and every cell carries exactly this many records.
MAX_SHROUD_PLAYERS = 20

# A grid larger than this is a bad read rather than a big map. The measured map is 104x104 and
# a cell is 40 world units, so this allows a map some 80x larger by area before refusing.
_MAX_CELLS = 1 << 20

# `0xFFFF` in a level means the seat has no shroud state - see the module docstring.
_UNTRACKED = 0xFFFF


class CellShroud(IntEnum):
    """What one player can see at one point, as the engine's three return values. Not the classic
    `CLEAR / FOGGED / SHROUDED`: this build has no fogged state (see the module docstring).
    """

    CLEAR = 0
    """Visible right now: at least one of the player's units or buildings reveals the cell."""

    HIDDEN = 1
    """Not visible right now. Says nothing about whether it was ever explored."""

    UNTRACKED = 2
    """No shroud state: off the grid, not a valid seat, or a seat that is not playing."""


@dataclass(frozen=True)
class ShroudGrid:
    """One frame's visibility grid, for the seats that were asked for: one `u16` per cell per
    player, rather than the whole 1.8 MB cell array.
    """

    origin: tuple[float, float]
    cell_size: float
    inv_cell_size: float
    cells_x: int
    cells_y: int
    # False when the match runs with fog of war switched off. The grid is still maintained, so
    # the levels stay meaningful; the engine simply stops acting on them.
    fog_enabled: bool
    # `{player index -> little-endian u16 per cell, row-major}`. A seat that was not asked for
    # is absent, and asking about it yields `UNTRACKED` rather than a wrong answer.
    levels: Mapping[int, bytes]

    @property
    def cell_count(self) -> int:
        return self.cells_x * self.cells_y

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        """The cell a world position falls in, by the engine's arithmetic: multiplying by the stored
        reciprocal, which can differ from dividing in the last bit. `status` bounds-checks it.
        """
        return (
            math.floor((x - self.origin[0]) * self.inv_cell_size),
            math.floor((y - self.origin[1]) * self.inv_cell_size),
        )

    def level(self, cx: int, cy: int, player: int) -> int | None:
        """The raw revealer count at a cell, or None where the engine would refuse."""
        if not (0 <= cx < self.cells_x and 0 <= cy < self.cells_y):
            return None
        column = self.levels.get(player)
        if column is None:
            return None
        return struct.unpack_from("<H", column, (self.cells_x * cy + cx) * 2)[0]

    def status_at_cell(self, cx: int, cy: int, player: int) -> CellShroud:
        """`CellShroud` for a cell, reproducing `0x00B4FB20` exactly."""
        if not (0 <= player < MAX_SHROUD_PLAYERS):
            return CellShroud.UNTRACKED
        level = self.level(cx, cy, player)
        if level is None or level == _UNTRACKED:
            return CellShroud.UNTRACKED
        return CellShroud.CLEAR if level else CellShroud.HIDDEN

    def status(self, position: Point, player: int) -> CellShroud:
        """`CellShroud` for a world position; Z is ignored.

        A position that is not a real point (NaN, as a mid-spawn object may report) answers
        `UNTRACKED` rather than raising, which `visible` reads as not visible.
        """
        x, y = position[0], position[1]
        if not (math.isfinite(x) and math.isfinite(y)):
            return CellShroud.UNTRACKED
        cx, cy = self.cell_of(x, y)
        return self.status_at_cell(cx, cy, player)

    def visible(self, position: Point, player: int) -> bool:
        """Whether `player` can see `position` right now. `UNTRACKED` counts as not visible; a match
        with fog off is handled by `Observation.under_fog` through `fog_enabled`.
        """
        return self.status(position, player) is CellShroud.CLEAR

    def visible_cells(self, player: int) -> int:
        """How many cells the player currently reveals. Cheap enough to log every frame."""
        column = self.levels.get(player)
        if column is None:
            return 0
        return sum(
            1
            for value in struct.unpack_from(f"<{self.cell_count}H", column)
            if value and value != _UNTRACKED
        )
