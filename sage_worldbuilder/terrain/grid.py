"""The heightmap as a numpy array, and the conversion between world units and its cells.

A map stores positions in world units, 10 to a heightmap cell, with (0, 0) at the inner corner of
the border, and the y axis pointing up. `HeightMapData.elevations` is the saved form, with row 0
at the top. `TerrainGrid.heights` turns that around so that `heights[cell_y, cell_x]` counts from
the bottom-left corner of the whole heightmap, border included, like the positions do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from sage_map.assets.height_map import HeightMapData

__all__ = ["FEET_PER_HEIGHT_UNIT", "MAX_HEIGHT", "WORLD_UNITS_PER_CELL", "TerrainGrid"]

WORLD_UNITS_PER_CELL = 10.0
# WorldBuilder's height readouts multiply a stored height by 10/256 (the float at 0x01DDD434) to
# show feet; world units are feet too.
FEET_PER_HEIGHT_UNIT = 10.0 / 256.0
MAX_HEIGHT = 65535


@dataclass(frozen=True, eq=False)
class TerrainGrid:
    heights: np.ndarray
    border: int

    @classmethod
    def from_height_map(cls, height_map: HeightMapData) -> TerrainGrid:
        rows = np.asarray(height_map.elevations, dtype=np.uint16)
        if rows.shape != (height_map.height, height_map.width):
            raise ValueError(
                f"elevations are {rows.shape[1] if rows.ndim == 2 else '?'}x{rows.shape[0]}, "
                f"the heightmap says {height_map.width}x{height_map.height}"
            )
        heights = np.ascontiguousarray(rows[::-1])
        heights.flags.writeable = False
        return cls(heights, height_map.border_width)

    @property
    def width(self) -> int:
        """Cells across, border included."""
        return int(self.heights.shape[1])

    @property
    def height(self) -> int:
        """Cells from bottom to top, border included."""
        return int(self.heights.shape[0])

    def patch(self, x0: int, y0: int, values: np.ndarray) -> None:
        """Overwrite the rectangle from sample `(x0, y0)` in place. The array stays read-only to
        everyone else, so a terrain edit is the only way it changes."""
        rows, columns = values.shape
        self.heights.flags.writeable = True
        try:
            self.heights[y0 : y0 + rows, x0 : x0 + columns] = values
        finally:
            self.heights.flags.writeable = False

    def world_to_cell(self, x: float, y: float) -> tuple[float, float]:
        """The fractional cell a world position falls in, counted from the heightmap's corner."""
        return x / WORLD_UNITS_PER_CELL + self.border, y / WORLD_UNITS_PER_CELL + self.border

    def cell_to_world(self, cell_x: float, cell_y: float) -> tuple[float, float]:
        return (
            (cell_x - self.border) * WORLD_UNITS_PER_CELL,
            (cell_y - self.border) * WORLD_UNITS_PER_CELL,
        )

    def nearest_cell(self, x: float, y: float) -> tuple[int, int] | None:
        """The heightmap sample nearest a world position, or None off the heightmap."""
        cell_x, cell_y = self.world_to_cell(x, y)
        column, row = math.floor(cell_x + 0.5), math.floor(cell_y + 0.5)
        if 0 <= column < self.width and 0 <= row < self.height:
            return column, row
        return None

    def elevation_at(self, x: float, y: float) -> int | None:
        """The stored height of the sample nearest a world position, or None off the map."""
        cell = self.nearest_cell(x, y)
        if cell is None:
            return None
        column, row = cell
        return int(self.heights[row, column])
