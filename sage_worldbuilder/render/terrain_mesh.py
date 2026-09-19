"""The terrain as triangle meshes for the 3D view, in square chunks so an edit rebuilds only the
chunks it touches.

A chunk's vertices are the heightmap samples of its box in world space, with normals from the
slopes around each sample (reading one sample past the box, so neighbouring chunks agree along
their shared edge). Each cell is two triangles, counter-clockwise seen from above.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from sage_worldbuilder.changes import Region
from sage_worldbuilder.terrain.grid import FEET_PER_HEIGHT_UNIT, WORLD_UNITS_PER_CELL, TerrainGrid

__all__ = [
    "CHUNK_CELLS",
    "Box",
    "chunk_boxes",
    "chunk_vertices",
    "chunks_near",
    "chunks_touching",
    "grid_indices",
]

CHUNK_CELLS = 64

# A chunk's samples: columns `x0..x1` and rows `y0..y1`, both ends included.
Box = tuple[int, int, int, int]


def chunk_boxes(columns: int, rows: int, size: int = CHUNK_CELLS) -> list[Box]:
    """Boxes covering every cell of a heightmap, neighbours sharing their edge samples. None for a
    heightmap without two samples along either axis: it has no cells to draw."""
    if columns < 2 or rows < 2:
        return []
    return [
        (x0, y0, min(x0 + size, columns - 1), min(y0 + size, rows - 1))
        for y0 in range(0, rows - 1, size)
        for x0 in range(0, columns - 1, size)
    ]


def grid_indices(columns: int, rows: int) -> np.ndarray:
    """Triangle indices over a `columns` x `rows` block of vertices stored row by row."""
    index = np.arange(columns * rows, dtype=np.uint32).reshape(rows, columns)
    a, b = index[:-1, :-1], index[:-1, 1:]
    c, d = index[1:, 1:], index[1:, :-1]
    return np.ascontiguousarray(np.stack((a, b, c, a, c, d), axis=-1).reshape(-1))


def chunk_vertices(grid: TerrainGrid, box: Box) -> np.ndarray:
    """`float32` rows of position (x, y, z) and unit normal for the box's samples, row by row
    from the bottom."""
    x0, y0, x1, y1 = box
    heights = grid.heights
    rows, columns = heights.shape
    xa, ya = max(x0 - 1, 0), max(y0 - 1, 0)
    xb, yb = min(x1 + 2, columns), min(y1 + 2, rows)
    z = heights[ya:yb, xa:xb].astype(np.float64) * FEET_PER_HEIGHT_UNIT
    dzdy = np.gradient(z, WORLD_UNITS_PER_CELL, axis=0) if z.shape[0] > 1 else np.zeros_like(z)
    dzdx = np.gradient(z, WORLD_UNITS_PER_CELL, axis=1) if z.shape[1] > 1 else np.zeros_like(z)
    crop = (slice(y0 - ya, y1 - ya + 1), slice(x0 - xa, x1 - xa + 1))
    normals = np.stack((-dzdx[crop], -dzdy[crop], np.ones_like(z[crop])), axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    cell_y, cell_x = np.mgrid[y0 : y1 + 1, x0 : x1 + 1]
    positions = np.stack(
        (
            (cell_x - grid.border) * WORLD_UNITS_PER_CELL,
            (cell_y - grid.border) * WORLD_UNITS_PER_CELL,
            z[crop],
        ),
        axis=-1,
    )
    return np.ascontiguousarray(
        np.concatenate((positions, normals), axis=-1).reshape(-1, 6), dtype=np.float32
    )


def chunks_touching(boxes: Sequence[Box], region: Region) -> list[int]:
    """The chunks whose vertices change when the heights of `region` do: its samples, and the
    normals one sample around them."""
    return [
        index
        for index, (x0, y0, x1, y1) in enumerate(boxes)
        if x0 <= region.x1 and region.x0 - 1 <= x1 and y0 <= region.y1 and region.y0 - 1 <= y1
    ]


def chunks_near(boxes: Sequence[Box], border: int, x: float, y: float, radius: float) -> list[int]:
    """The chunks with ground within `radius` world units of a world position, for drawing only
    part of the map."""
    near = []
    for index, (x0, y0, x1, y1) in enumerate(boxes):
        left, right = (x0 - border) * WORLD_UNITS_PER_CELL, (x1 - border) * WORLD_UNITS_PER_CELL
        bottom, top = (y0 - border) * WORLD_UNITS_PER_CELL, (y1 - border) * WORLD_UNITS_PER_CELL
        dx = max(left - x, 0.0, x - right)
        dy = max(bottom - y, 0.0, y - top)
        if dx * dx + dy * dy <= radius * radius:
            near.append(index)
    return near
