"""The top-down terrain picture: a colour per heightmap sample, shaded by the slope.

The colour comes from the texture painted on each tile when the texture colours are known, and
from a height ramp otherwise. With texture colours, the picture can have several pixels a cell, so
a blend shows as its texture's colour fading in from the side the blend comes from. Arrays follow
`TerrainGrid`: `[cell_y, cell_x]` counted from the bottom-left. `terrain_image` returns rows top
first, the way images are stored.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from sage_map.assets.blend_tile_data import BlendDescription, BlendTileData
from sage_worldbuilder.render.terrain_texturing import mask_indices, mask_weights
from sage_worldbuilder.terrain.cells import CellLayer

__all__ = [
    "BLEND_PIXELS",
    "blend_kinds",
    "blend_masks",
    "blend_overlay",
    "blend_pixels",
    "blended_colors",
    "cell_overlay",
    "class_colors",
    "contour_levels",
    "contour_mask",
    "height_colors",
    "hillshade",
    "mask_overlay",
    "terrain_image",
    "tile_classes",
]

# Pixels a cell side when the picture shows blends, unless the picture would pass _PICTURE_SIDE.
BLEND_PIXELS = 4
_PICTURE_SIDE = 2048
# A plain alpha blend's custom edge class; other blends' direction bytes mean something else.
_DEFAULT_EDGE = 0xFFFFFFFF
# Show Blends: cells with a blend, and cells with a 3-way blend as well (white, as WorldBuilder's
# Show 3-Way Blends in White).
_BLEND_TINT = (40, 190, 255, 110)
_THREE_WAY_TINT = (255, 255, 255, 170)

# Tiles per texture cell: a tile index divided by 4 is the texture cell it samples.
_TILES_PER_CELL_SHIFT = 2
# The light comes from the top left, as on a printed map.
_LIGHT = np.array([-1.0, 1.0, 1.4])
# The tint each cell attribute gets on the overlay, where the cell has it.
_CELL_TINTS = {
    CellLayer.IMPASSABLE: (230, 40, 30, 120),
    CellLayer.IMPASSABLE_TO_PLAYERS: (255, 150, 0, 140),
    CellLayer.EXTRA_PASSABLE: (40, 220, 90, 140),
    CellLayer.NARROW: (50, 140, 255, 140),
    CellLayer.TAINTABLE: (170, 60, 230, 120),
    CellLayer.VISIBLE: (0, 0, 0, 160),
}
# Flammability by stored value: grass, highly flammable, undefined (fire resistant is untinted).
_FLAMMABILITY_TINTS = {1: (240, 220, 60, 120), 2: (255, 90, 20, 150), 3: (150, 150, 150, 150)}
_LOW = np.array([70, 92, 52], dtype=np.float32)
_HIGH = np.array([214, 206, 184], dtype=np.float32)


def hillshade(heights: np.ndarray, relief: float = 0.08) -> np.ndarray:
    """How brightly each sample is lit, 0-1. `relief` scales the stored heights against the
    sample spacing: the stored values are much larger than the steps between samples."""
    scaled = heights.astype(np.float32) * relief
    # A gradient needs two samples along an axis; a map one cell wide or tall is flat along it.
    dy = np.gradient(scaled, axis=0) if heights.shape[0] > 1 else np.zeros_like(scaled)
    dx = np.gradient(scaled, axis=1) if heights.shape[1] > 1 else np.zeros_like(scaled)
    normal = np.stack((-dx, -dy, np.ones_like(dx)), axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    light = _LIGHT / np.linalg.norm(_LIGHT)
    return np.clip(normal @ light, 0.0, 1.0)


def height_colors(
    heights: np.ndarray, low: float | None = None, high: float | None = None
) -> np.ndarray:
    """A green-to-stone ramp over a height range (the heights' own by default), as `uint8`
    RGB. Pass the whole map's range to colour part of it the same way as the rest."""
    low = float(heights.min()) if low is None else low
    high = float(heights.max()) if high is None else high
    if high > low:
        fraction = np.clip((heights.astype(np.float32) - low) / (high - low), 0.0, 1.0)
    else:
        fraction = np.zeros(heights.shape, dtype=np.float32)
    rgb = _LOW + (_HIGH - _LOW) * fraction[..., None]
    return rgb.astype(np.uint8)


def cell_overlay(layers: dict[CellLayer, np.ndarray]) -> np.ndarray:
    """A see-through picture of cell attributes, as contiguous `uint8` RGBA rows top first: each
    layer tints the cells that have it (Visible tints the cells that are not), later layers over
    earlier ones."""
    shape = next(iter(layers.values())).shape
    pixels = np.zeros(shape + (4,), dtype=np.uint8)
    for layer, values in layers.items():
        if layer is CellLayer.FLAMMABILITY:
            for value, tint in _FLAMMABILITY_TINTS.items():
                pixels[values == value] = tint
        elif layer is CellLayer.VISIBLE:
            pixels[~values.astype(bool)] = _CELL_TINTS[layer]
        else:
            pixels[values.astype(bool)] = _CELL_TINTS[layer]
    return np.ascontiguousarray(pixels[::-1])


def contour_levels(low: float, high: float, count: int, offset: float = 0.0) -> np.ndarray:
    """`count` heights spread evenly inside `low`-`high`, all moved by `offset`."""
    if count < 1 or high <= low:
        return np.zeros(0, dtype=np.float64)
    step = (high - low) / (count + 1)
    return low + offset + step * np.arange(1, count + 1, dtype=np.float64)


def contour_mask(heights: np.ndarray, levels: np.ndarray, width: int = 1) -> np.ndarray:
    """True on the samples where a contour at one of `levels` passes: where a sample and its
    right or upper neighbour lie on different sides of a level. `width` thickens the lines."""
    mask = np.zeros(heights.shape, dtype=bool)
    if len(levels) == 0:
        return mask
    band = np.searchsorted(np.sort(levels), heights, side="right")
    mask[:, :-1] |= band[:, :-1] != band[:, 1:]
    mask[:-1, :] |= band[:-1, :] != band[1:, :]
    for _ in range(max(width, 1) - 1):
        grown = mask.copy()
        grown[1:, :] |= mask[:-1, :]
        grown[:-1, :] |= mask[1:, :]
        grown[:, 1:] |= mask[:, :-1]
        grown[:, :-1] |= mask[:, 1:]
        mask = grown
    return mask


def tile_classes(blend: BlendTileData) -> np.ndarray:
    """The index into `blend.textures` painted on each tile, `[cell_y, cell_x]`; -1 where a tile
    names no texture. `BlendTileData.tiles` is stored `[x][y]` with y counting up."""
    tiles = np.asarray(blend.tiles, dtype=np.int32).T >> _TILES_PER_CELL_SHIFT
    classes = np.full(tiles.shape, -1, dtype=np.int16)
    for index, texture in enumerate(blend.textures):
        inside = (tiles >= texture.cell_start) & (tiles < texture.cell_start + texture.cell_count)
        classes[inside] = index
    return classes


def class_colors(classes: np.ndarray, palette: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """RGB per sample from `palette[class]` (`(n, 3)` uint8); `fallback` where the class is -1 or
    beyond the palette."""
    rgb = fallback.copy()
    known = (classes >= 0) & (classes < len(palette))
    rgb[known] = palette[classes[known]]
    return rgb


def blend_pixels(shape: tuple[int, ...]) -> int:
    """Pixels a cell side for a picture with blends of a heightmap of `shape`."""
    return max(1, min(BLEND_PIXELS, _PICTURE_SIDE // max(max(shape[:2]), 1)))


def blend_kinds(descriptions: Sequence[BlendDescription]) -> np.ndarray:
    """Per blend number (0 for none, then each description) the game's alpha mask for it, an
    index into `blend_masks`, or -1 for none (`terrain_texturing.mask_index`)."""
    return mask_indices(descriptions)


def blend_masks(pixels: int) -> np.ndarray:
    """How much of the blend's texture shows, 0-1, over a cell `pixels` a side (`[y, x]`, y up),
    per mask: the game's own twelve (`terrain_texturing.mask_weights`)."""
    return mask_weights(pixels)


def blended_colors(
    base: np.ndarray,
    layers: Sequence[np.ndarray],
    kinds: np.ndarray,
    colors: np.ndarray,
    pixels: int,
) -> np.ndarray:
    """RGB with `pixels` pixels a cell side: `base` (RGB per sample) with, for each blend layer in
    order (`blends`, then `three_way_blends`), the colour `colors[number]` of each cell's blend
    faded in as its kind (`kinds[number]`) says. Numbers past the tables count as no blend."""
    rows, columns = base.shape[:2]
    picture = np.repeat(np.repeat(base, pixels, axis=0), pixels, axis=1).astype(np.float32)
    blocks = picture.reshape(rows, pixels, columns, pixels, 3)
    masks = blend_masks(pixels)
    for numbers in layers:
        numbers = np.where((numbers >= 0) & (numbers < len(kinds)), numbers, 0)
        kind = kinds[numbers]
        ys, xs = np.nonzero(kind >= 0)
        if not ys.size:
            continue
        alpha = masks[kind[ys, xs]][..., None]
        color = colors[numbers[ys, xs]].astype(np.float32)[:, None, None, :]
        blocks[ys, :, xs, :] = blocks[ys, :, xs, :] * (1 - alpha) + color * alpha
    return np.clip(np.rint(picture), 0, 255).astype(np.uint8)


def blend_overlay(blends: np.ndarray, three_way: np.ndarray) -> np.ndarray:
    """Show Blends: a see-through tint on the cells with a blend, white where they have a 3-way
    blend too, as contiguous `uint8` RGBA rows top first."""
    pixels = np.zeros(blends.shape + (4,), dtype=np.uint8)
    pixels[blends != 0] = _BLEND_TINT
    pixels[three_way != 0] = _THREE_WAY_TINT
    return np.ascontiguousarray(pixels[::-1])


def mask_overlay(mask: np.ndarray, rgba: tuple[int, int, int, int]) -> np.ndarray:
    """A see-through tint on the cells of `mask`, as contiguous `uint8` RGBA rows top first."""
    pixels = np.zeros(mask.shape + (4,), dtype=np.uint8)
    pixels[mask] = rgba
    return np.ascontiguousarray(pixels[::-1])


def terrain_image(
    heights: np.ndarray,
    base: np.ndarray | None = None,
    height_range: tuple[float, float] | None = None,
) -> np.ndarray:
    """The picture as contiguous `uint8` RGBA, rows top first. `base` is RGB with a whole number
    of pixels a cell side (one per sample, or more from `blended_colors`); the height ramp, over
    `height_range` when given, stands in when it is missing or does not fit the heightmap."""
    rows, columns = heights.shape
    scale = base.shape[0] // rows if base is not None and rows else 1
    if base is None or scale < 1 or base.shape[:2] != (rows * scale, columns * scale):
        low, high = height_range if height_range is not None else (None, None)
        base, scale = height_colors(heights, low, high), 1
    shade = 0.45 + 0.75 * hillshade(heights)
    if scale > 1:
        shade = np.repeat(np.repeat(shade, scale, axis=0), scale, axis=1)
    rgb = np.clip(base.astype(np.float32) * shade[..., None], 0, 255).astype(np.uint8)
    alpha = np.full(rgb.shape[:2] + (1,), 255, dtype=np.uint8)
    return np.ascontiguousarray(np.concatenate((rgb, alpha), axis=-1)[::-1])
