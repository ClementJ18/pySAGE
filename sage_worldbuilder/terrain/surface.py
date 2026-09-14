"""The terrain as a surface in world space: its height anywhere, and where a ray meets it.

Heights between samples are bilinear; off the heightmap the edge samples carry on. A stored
height times `FEET_PER_HEIGHT_UNIT` is world units, like positions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from sage_worldbuilder.terrain.grid import FEET_PER_HEIGHT_UNIT, WORLD_UNITS_PER_CELL, TerrainGrid

__all__ = ["ground_height", "ground_heights", "ray_hit"]

# World units between the samples a ray is tested at: half a cell.
_RAY_STEP = WORLD_UNITS_PER_CELL / 2
_MAX_RAY_SAMPLES = 50_000
_BISECTIONS = 30


def ground_height(grid: TerrainGrid, x: float, y: float) -> float:
    """The terrain's height in world units under a world position."""
    heights = grid.heights
    rows, columns = heights.shape
    cx = min(max(x / WORLD_UNITS_PER_CELL + grid.border, 0.0), columns - 1.0)
    cy = min(max(y / WORLD_UNITS_PER_CELL + grid.border, 0.0), rows - 1.0)
    x0, y0 = min(int(cx), max(columns - 2, 0)), min(int(cy), max(rows - 2, 0))
    x1, y1 = min(x0 + 1, columns - 1), min(y0 + 1, rows - 1)
    fx, fy = cx - x0, cy - y0
    value = (
        float(heights[y0, x0]) * (1 - fx) * (1 - fy)
        + float(heights[y0, x1]) * fx * (1 - fy)
        + float(heights[y1, x0]) * (1 - fx) * fy
        + float(heights[y1, x1]) * fx * fy
    )
    return value * FEET_PER_HEIGHT_UNIT


def ground_heights(grid: TerrainGrid, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """`ground_height` for arrays of world positions."""
    heights = grid.heights
    rows, columns = heights.shape
    cx = np.clip(
        np.asarray(xs, dtype=np.float64) / WORLD_UNITS_PER_CELL + grid.border, 0, columns - 1
    )
    cy = np.clip(np.asarray(ys, dtype=np.float64) / WORLD_UNITS_PER_CELL + grid.border, 0, rows - 1)
    x0 = np.minimum(np.floor(cx).astype(np.intp), max(columns - 2, 0))
    y0 = np.minimum(np.floor(cy).astype(np.intp), max(rows - 2, 0))
    x1, y1 = np.minimum(x0 + 1, columns - 1), np.minimum(y0 + 1, rows - 1)
    fx, fy = cx - x0, cy - y0
    value = (
        heights[y0, x0] * (1 - fx) * (1 - fy)
        + heights[y0, x1] * fx * (1 - fy)
        + heights[y1, x0] * (1 - fx) * fy
        + heights[y1, x1] * fx * fy
    )
    return value * FEET_PER_HEIGHT_UNIT


def ray_hit(
    grid: TerrainGrid,
    origin: Sequence[float] | np.ndarray,
    direction: Sequence[float] | np.ndarray,
) -> tuple[float, float, float] | None:
    """The first point where a ray meets the terrain over the heightmap, or None when it misses.
    The ray is tested every half cell of ground it crosses, then the crossing is narrowed down, so
    a ridge thinner than half a cell can be missed."""
    start = np.asarray(origin, dtype=np.float64)
    step = np.asarray(direction, dtype=np.float64)
    length = float(np.linalg.norm(step))
    if length == 0.0:
        return None
    step = step / length
    rows, columns = grid.heights.shape
    x_lo, y_lo = grid.cell_to_world(0, 0)
    x_hi, y_hi = grid.cell_to_world(columns - 1, rows - 1)
    z_lo = float(grid.heights.min()) * FEET_PER_HEIGHT_UNIT
    z_hi = float(grid.heights.max()) * FEET_PER_HEIGHT_UNIT
    # Clip the ray to the box the terrain lies in.
    t0, t1 = 0.0, math.inf
    for axis, low, high in ((0, x_lo, x_hi), (1, y_lo, y_hi), (2, z_lo, z_hi)):
        o, d = float(start[axis]), float(step[axis])
        if abs(d) < 1e-12:
            if o < low or o > high:
                return None
            continue
        ta, tb = sorted(((low - o) / d, (high - o) / d))
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return None
    if not math.isfinite(t1):
        return None
    across = math.hypot(float(step[0]), float(step[1]))
    count = 2 if across < 1e-9 else int((t1 - t0) * across / _RAY_STEP) + 2
    ts = np.linspace(t0, t1, min(count, _MAX_RAY_SAMPLES))
    points = start + ts[:, None] * step
    above = points[:, 2] - ground_heights(grid, points[:, 0], points[:, 1])
    under = np.flatnonzero(above <= 1e-6)
    if under.size == 0:
        return None
    first = int(under[0])
    if first == 0:
        t = float(ts[0])
    else:
        low_t, high_t = float(ts[first - 1]), float(ts[first])
        for _ in range(_BISECTIONS):
            mid = (low_t + high_t) / 2
            point = start + mid * step
            if point[2] - ground_height(grid, point[0], point[1]) > 0:
                low_t = mid
            else:
                high_t = mid
        t = high_t
    hit = start + t * step
    return float(hit[0]), float(hit[1]), float(hit[2])
