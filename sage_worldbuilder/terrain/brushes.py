"""The height brushes as pure functions over the heightmap array.

Each brush takes the heights (`[cell_y, cell_x]` from the bottom-left, as `TerrainGrid` holds them)
and returns the rectangle it changes with its new values; the caller turns that into an undoable
edit. A brush is round: the samples closer to its centre than half its width get the full effect,
and the effect falls off linearly over the feather ring beyond. As in WorldBuilder, a brush of odd
width is centred on a sample and one of even width on the corner between four samples.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import numpy as np

from sage_worldbuilder.brush_options import BrushOptions
from sage_worldbuilder.terrain.grid import FEET_PER_HEIGHT_UNIT, MAX_HEIGHT

__all__ = ["BrushKind", "HeightPatch", "apply_brush", "brush_center", "brush_weights"]


class BrushKind(Enum):
    SET = "Height Brush"
    RAISE = "Mound"
    LOWER = "Dig"
    SMOOTH = "Smooth Height"


@dataclass(frozen=True)
class HeightPatch:
    """New heights for the rectangle whose bottom-left sample is `(x0, y0)`."""

    x0: int
    y0: int
    values: np.ndarray


def brush_center(cell_x: float, cell_y: float, width: int) -> tuple[float, float]:
    """Where a brush of `width` centres for the fractional cell position under the cursor."""
    if width % 2:
        return float(math.floor(cell_x + 0.5)), float(math.floor(cell_y + 0.5))
    return math.floor(cell_x) + 0.5, math.floor(cell_y) + 0.5


def brush_weights(
    center: tuple[float, float], width: int, feather: int, shape: tuple[int, int]
) -> tuple[int, int, np.ndarray] | None:
    """The strength, 0-1, at each sample the brush reaches, clipped to a grid of `shape`
    (rows, columns): `(x0, y0, weights)`, or None when it misses the grid."""
    cx, cy = center
    core = width / 2
    reach = core + feather
    rows, columns = shape
    x0, x1 = max(math.ceil(cx - reach), 0), min(math.floor(cx + reach), columns - 1)
    y0, y1 = max(math.ceil(cy - reach), 0), min(math.floor(cy + reach), rows - 1)
    if x0 > x1 or y0 > y1:
        return None
    xs = np.arange(x0, x1 + 1, dtype=np.float64) - cx
    ys = np.arange(y0, y1 + 1, dtype=np.float64) - cy
    distance = np.hypot(xs[None, :], ys[:, None])
    if feather > 0:
        weights = np.clip((reach - distance) / feather, 0.0, 1.0)
        weights[distance < core] = 1.0
    else:
        weights = (distance < core).astype(np.float64)
    if not weights.any():
        return None
    return x0, y0, weights


def _box_mean(values: np.ndarray, radius: int) -> np.ndarray:
    """The mean over the `(2 * radius + 1)`-square around each sample, repeating the edge."""
    size = 2 * radius + 1
    padded = np.pad(values, radius, mode="edge")
    sums = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    sums = np.pad(sums, ((1, 0), (1, 0)))
    total = sums[size:, size:] - sums[:-size, size:] - sums[size:, :-size] + sums[:-size, :-size]
    return total / (size * size)


def apply_brush(
    heights: np.ndarray,
    kind: BrushKind,
    cell: tuple[float, float],
    options: BrushOptions,
) -> HeightPatch | None:
    """One application of a brush at the fractional `cell` position, or None when it changes
    nothing."""
    center = brush_center(cell[0], cell[1], options.width)
    found = brush_weights(center, options.width, options.feather, heights.shape)
    if found is None:
        return None
    x0, y0, weights = found
    rows, columns = weights.shape
    old = heights[y0 : y0 + rows, x0 : x0 + columns].astype(np.float64)
    if kind is BrushKind.SET:
        target = options.height / FEET_PER_HEIGHT_UNIT
        new = old + (target - old) * weights
    elif kind in (BrushKind.RAISE, BrushKind.LOWER):
        step = options.amount / FEET_PER_HEIGHT_UNIT
        new = old + (step if kind is BrushKind.RAISE else -step) * weights
    else:
        radius = options.radius
        ya, xa = max(y0 - radius, 0), max(x0 - radius, 0)
        yb = min(y0 + rows + radius, heights.shape[0])
        xb = min(x0 + columns + radius, heights.shape[1])
        around = _box_mean(heights[ya:yb, xa:xb].astype(np.float64), radius)
        mean = around[y0 - ya : y0 - ya + rows, x0 - xa : x0 - xa + columns]
        new = old + (mean - old) * weights * (options.rate / 10)
    values = np.clip(np.rint(new), 0, MAX_HEIGHT).astype(np.uint16)
    if np.array_equal(values, heights[y0 : y0 + rows, x0 : x0 + columns]):
        return None
    return HeightPatch(x0, y0, values)
