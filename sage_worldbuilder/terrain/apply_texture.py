"""Apply texture to tiles: Terrain Material's Apply To Tiles... (dialog 250) paints the chosen
texture on the playable cells whose corners lie between two slopes and two heights, each at a
chance set by the saturation (PHASE3.md, 3.8).

From `TerrainMaterial::OnBnClickedTextureApply` (`0x0061C470`), the corner check it calls
(`BaseHeightMapRenderObjClass::CheckCorners`, `0x00758C00`) and the terrain's height and normal
lookup that check uses (`0x00756950`):

- a section whose Apply box is unticked uses slopes 0-89 degrees, heights 0-255 feet or
  saturation 100 (`CApplyTexture::GetResults`, `0x0043B9D0`), so heights above 255 feet are left
  alone unless the heights are given;
- a cell qualifies when each of its four corner samples has a height, in whole feet (truncated),
  within the heights, and a slope along x and along y within the slopes. A sample's slope along x
  is the angle whose tangent is the height difference between the samples on either side over
  their 20 feet; the first sample and the last two of a row or column count as flat;
- the cells are the playable ones, inside the border, taken column by column; each qualifying
  cell is painted when a roll of 1-100 is at most the saturation. Painting clears the cell's
  blends and cliff mapping, as all texture painting does.

WorldBuilder checks the corners of the cell `border` samples up and right of the one it paints
(it passes the cell's own index where the lookup expects a world position); here a cell's own
corners are checked. It also runs Optimize tiles and blend tiles afterwards, which is not built.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from sage_map.assets.blend_tile_data import BlendTileTexture
from sage_worldbuilder.terrain.cells import TileLayer
from sage_worldbuilder.terrain.textures import TilePaint, paint_texture_block, tiling_offset

__all__ = [
    "DEFAULT_HEIGHTS",
    "DEFAULT_SLOPES",
    "ApplyTextureOptions",
    "apply_texture",
    "qualifying_samples",
]

DEFAULT_SLOPES = (0, 89)
DEFAULT_HEIGHTS = (0, 255)
DEFAULT_SATURATION = 100
_FEET_PER_HEIGHT_UNIT = np.float32(10 / 256)
# The distance between the two samples a slope is measured across, in feet.
_SLOPE_RUN = 20.0


@dataclass
class ApplyTextureOptions:
    """The dialog's three sections: each Apply box and its values, kept while unticked."""

    use_slopes: bool = False
    slopes: tuple[int, int] = (0, 45)
    use_heights: bool = False
    heights: tuple[int, int] = DEFAULT_HEIGHTS
    use_saturation: bool = False
    saturation: int = DEFAULT_SATURATION

    def limits(self) -> tuple[tuple[int, int], tuple[int, int], int]:
        """The slopes, heights and saturation applied, the defaults for unticked sections."""
        slopes = tuple(sorted(self.slopes)) if self.use_slopes else DEFAULT_SLOPES
        heights = tuple(sorted(self.heights)) if self.use_heights else DEFAULT_HEIGHTS
        saturation = self.saturation if self.use_saturation else DEFAULT_SATURATION
        return slopes, heights, saturation  # type: ignore[return-value]


def qualifying_samples(
    heights: np.ndarray, slopes: tuple[int, int], height_range: tuple[int, int]
) -> np.ndarray:
    """Per height sample, whether its height and its slopes are within the limits."""
    rows, columns = heights.shape
    scaled = heights.astype(np.float32) * _FEET_PER_HEIGHT_UNIT
    feet = scaled.astype(np.int64)
    along_x = np.zeros(heights.shape, dtype=np.float64)
    along_y = np.zeros(heights.shape, dtype=np.float64)
    if rows >= 4 and columns >= 4:
        inner = (slice(1, rows - 2), slice(1, columns - 2))
        rise_x = scaled[1 : rows - 2, 2 : columns - 1] - scaled[1 : rows - 2, 0 : columns - 3]
        rise_y = scaled[2 : rows - 1, 1 : columns - 2] - scaled[0 : rows - 3, 1 : columns - 2]
        along_x[inner] = np.degrees(np.arctan2(np.abs(rise_x), _SLOPE_RUN))
        along_y[inner] = np.degrees(np.arctan2(np.abs(rise_y), _SLOPE_RUN))
    low, high = slopes
    return (
        (feet >= height_range[0])
        & (feet <= height_range[1])
        & (along_x >= low)
        & (along_x <= high)
        & (along_y >= low)
        & (along_y <= high)
    )


def apply_texture(
    layers: Mapping[TileLayer, np.ndarray],
    heights: np.ndarray,
    textures: Sequence[BlendTileTexture],
    texture: BlendTileTexture,
    border: int,
    options: ApplyTextureOptions,
    random: np.random.Generator | None = None,
) -> TilePaint | None:
    """`texture` over the playable cells that qualify, or None when no cell changes. A texture
    in `textures` keeps its tiling offset on the map; a new one is tiled from (0, 0)."""
    tiles = layers[TileLayer.TILES]
    rows, columns = tiles.shape
    if heights.shape != tiles.shape:
        return None
    x0, y0 = max(border, 0), max(border, 0)
    x1, y1 = columns - x0, rows - y0
    if x0 >= x1 or y0 >= y1:
        return None
    slopes, height_range, saturation = options.limits()
    samples = np.pad(qualifying_samples(heights, slopes, height_range), ((0, 1), (0, 1)), "edge")
    corners = samples[:-1, :-1] & samples[:-1, 1:] & samples[1:, 1:] & samples[1:, :-1]
    random = random if random is not None else np.random.default_rng()
    # One roll per cell, a column at a time, as WorldBuilder walks them.
    rolls = random.integers(1, 101, size=(x1 - x0, y1 - y0)).T
    mask = corners[y0:y1, x0:x1] & (rolls <= saturation)
    if not mask.any():
        return None
    in_map = any(entry is texture for entry in textures)
    offset = tiling_offset(tiles, texture) if in_map else (0, 0)
    painted = paint_texture_block(layers, (x0, y0, x1, y1), texture, mask, offset)
    return (x0, y0, painted) if painted is not None else None
