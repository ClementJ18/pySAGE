"""Per-player visibility, read from the engine's own shroud grid.

This is the one honest answer to "can this player see that?". Everything else `sage_live` reads
is whole-map: the object table does not know who is looking, so a policy handed
`Observation.objects` is handed the opponent's army whether or not a single scout has left
home. `ShroudGrid` is what makes the filter possible, and `Observation.under_fog` is what
applies it.

**The model, recovered from `TheShroudManager` on RotWK 2.01 + Edain.** The global is a 20-byte
facade whose every method is `mov ecx, [ecx+0x10]; jmp <impl>`, so the real 0x70-byte object is
at `+0x10`. It owns a flat, row-major grid of `0xA8`-byte cells, and each cell carries twenty
eight-byte per-player records. The first `u16` of a record is that player's **shroud level**,
and the engine's own lookup (`0x00B4FB20`) is:

    cx = floor((x - origin_x) * inv_cell_size)      # inv_cell_size, not / cell_size
    cy = floor((y - origin_y) * inv_cell_size)
    cell  = cells + (cells_x * cy + cx) * 0xA8
    level = u16[cell + 4 + player * 8]

    out of bounds, or player outside 0..19, or level == 0xFFFF  ->  UNTRACKED
    level == 0                                                  ->  HIDDEN
    level > 0                                                   ->  CLEAR

so the level is a **reference count of that player's revealers currently covering the cell**,
not a flag. Measured live at frame ~500 of a two-player skirmish: of the enemy's 50 objects I
could see 0, and of my 70 they could see 0, while each of us saw all but one of our own. The
grid drawn as ASCII is a single filled blob around each base.

**There is no explored-but-not-currently-seen state here, and that is a measurement, not an
omission.** `0xFFFF` looks like `-1` read signed and would be the obvious "never explored"
sentinel, which would make the triple the classic `CLEAR / FOGGED / SHROUDED`. It is not: across
all twenty slots of a live match, `0xFFFF` filled the grid for the fourteen *unused* seats and
never once appeared for either playing seat, whose cells only ever read 0 or a positive count.
So the third state means "this seat has no shroud state", which is why it is named `UNTRACKED`
rather than `SHROUDED`.

The consequence matters for anything built on this: **a cell you explored and walked away from
is indistinguishable from one you have never reached.** The engine keeps that distinction per
*object* (`PartitionData::m_everSeenByPlayer[N]`, per `sage_patch/docs/max-player-count.md`),
which is what lets a real player keep seeing an enemy building after scouting it, and that
structure is still not located. Remembering what was seen is therefore the consumer's job -
`Observation.under_fog` hides what cannot be seen *now* and does not invent a memory it has no
way to check. See `docs/fog-of-war.md`.
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
    """What one player can see at one point, using the engine's own three return values.

    **Deliberately not `CLEAR / FOGGED / SHROUDED`.** That is the classic SAGE triple and it is
    the wrong name for what this build returns; see the module docstring for the measurement
    that rules it out.
    """

    CLEAR = 0
    """Visible right now: at least one of the player's units or buildings reveals the cell."""

    HIDDEN = 1
    """Not visible right now. Says nothing about whether it was ever explored."""

    UNTRACKED = 2
    """No shroud state: off the grid, not a valid seat, or a seat that is not playing."""


@dataclass(frozen=True)
class ShroudGrid:
    """One frame's visibility grid, for the seats that were asked for.

    Holds one `u16` per cell per requested player rather than the raw cell array, which is two
    orders of magnitude smaller (21 KB a seat against 1.8 MB) and drops nothing this can answer:
    the other three `u16`s of a cell record are its value maps, not visibility.
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
        """The cell a world position falls in, by the engine's own arithmetic.

        Multiplies by the stored reciprocal instead of dividing by `cell_size`, because that is
        what `0x00B4E390` does and the two disagree in the last bit. The result can be out of
        range; `status` is what bounds-checks it.
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
        """`CellShroud` for a world position. Z is ignored, as the grid is two-dimensional.

        **A position that is not a real point answers `UNTRACKED` rather than raising.** A live
        object table routinely carries one: something mid-spawn, mid-death or mid-teleport has
        `NaN` where its coordinates will be, and `math.floor` on that raises `ValueError` rather
        than producing a silly cell. That killed a 1,423-cycle run outright - the exception
        travelled up through `poll` and out of `Bot.run`, from an object nothing was even asking
        about, because `under_fog` walks *every* object in the frame.

        `UNTRACKED` is the honest answer and lands on the safe side: `visible` reads it as not
        visible, so an object whose position cannot be read is filtered out rather than acted on.
        """
        x, y = position[0], position[1]
        if not (math.isfinite(x) and math.isfinite(y)):
            return CellShroud.UNTRACKED
        cx, cy = self.cell_of(x, y)
        return self.status_at_cell(cx, cy, player)

    def visible(self, position: Point, player: int) -> bool:
        """Whether `player` can see `position` right now.

        `UNTRACKED` counts as **not** visible, which is the conservative direction for a filter:
        a seat with no shroud state sees nothing rather than everything. The one case where that
        would be wrong is a match with fog switched off, and `fog_enabled` says so - which is
        why `Observation.under_fog` checks it rather than leaving it to each caller.
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
