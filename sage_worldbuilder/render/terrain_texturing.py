"""The terrain's textures as the game draws them, for the 3D view and the top-down picture.

The game cuts each Terrain.ini texture into 64-pixel texture cells, reading a TGA's scanlines in
file order (`WorldHeightMap::readTiles`, `0x00770590`), so row 0 of a texture cell is the file's
first scanlines: the bottom of the picture for a TGA stored bottom-up, the usual order. A tile value
`(cell << 2) | quadrant` shows one quarter of its cell, bit 0 the right half and bit 1 the upper
one (`0x00772D60`).

A blended cell is its tile with the blend's secondary tile mixed in through one of twelve alpha
masks (`0x007730D0`); a 3-way blend mixes a third tile in the same way on top. The mask comes from
the blend description (`0x007731C0`): the first direction byte that is set, in the order
horizontal, vertical, right diagonal (the +x, +y corner), left diagonal (the -x, +y corner), with
none set counting as horizontal; a long diagonal (`two_sided`) for the diagonals; and any non-zero
`flags` as inverted, which adds six. The masks (`0x007732F0`) are 64 pixels a side over one
heightmap cell, `[y, x]` with y up. The secondary tile's weight is `1 - clamp(v / 63)`, pixels
counted from 0:

    horizontal       63 - x, or x when inverted
    vertical         63 - y, or y when inverted
    right diagonal   (63 - y, or y when inverted) + (63 - x), less 64 when long
    left diagonal    (63 - y, or y when inverted) + x, less 64 when long

and the two tiles mix as `secondary * m + base * (255 - m)` over 256, `m` the weight in 0-255
(`0x00773150`). A cell with a cliff mapping is drawn without its blends.

A cliff mapping replaces a cell's texture coordinates. WorldBuilder draws cliff cells as a mesh of
their own (`0x007C3930`) over their texture's whole picture, repeating: the cell's corners from
(x, y) round to (x, y + 1) take the mapping's four (u, v), in repeats of the picture, `u` across
and `v` up from its first scanline. It draws them so only where the mapping's tile is of the
texture the cell's own tile shows (`0x007712D0`); a cell whose mapping names another texture is
drawn with its own tile here (WorldBuilder fades that mapping over the ground, which is not
read). `cliff_cells` gives each mapped cell its texture and its corners in texture cells, for the
3D view's shader to find the pixel under each point.

`build_atlas` lays a map's texture cells out by cell number, so a tile value finds its pixels by
arithmetic, and `cell_data` packs each cell's tiles and masks for the 3D view's shader, which
repeats the mask arithmetic per pixel.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from sage_map.assets.blend_tile_data import (
    BlendDescription,
    BlendTileTexture,
    CliffTextureMapping,
)
from sage_worldbuilder.terrain.textures import texture_classes

__all__ = [
    "CLIFF_FLAG",
    "MASK_COUNT",
    "MISSING_TEXTURE",
    "TEXTURE_CELL_PIXELS",
    "TerrainAtlas",
    "atlas_key",
    "CliffCells",
    "blend_secondaries",
    "build_atlas",
    "cell_data",
    "cliff_cells",
    "mask_index",
    "mask_indices",
    "mask_weight",
    "mask_weights",
    "texture_cells",
]

TEXTURE_CELL_PIXELS = 64
MASK_COUNT = 12
# What a texture cell shows when its texture's image cannot be read.
MISSING_TEXTURE = (128, 128, 128, 255)
# TGA image descriptor bit: the first scanline is the top of the picture.
_TGA_TOP_ORIGIN = 0x20
_TGA_DESCRIPTOR = 17


def mask_index(description: BlendDescription) -> int:
    """The alpha mask, 0-11, the game draws a blend description with."""
    horizontal, vertical, right, left = (bytes(description.raw_blend_direction) + bytes(4))[:4]
    if horizontal:
        index = 0
    elif vertical:
        index = 1
    elif right:
        index = 5 if description.two_sided else 3
    elif left:
        index = 4 if description.two_sided else 2
    else:
        index = 0
    return index + 6 if description.flags else index


def mask_indices(descriptions: Sequence[BlendDescription]) -> np.ndarray:
    """Per blend number (0 for none, then each description) its mask, and -1 for none."""
    indices = np.full(len(descriptions) + 1, -1, dtype=np.int16)
    if descriptions:
        indices[1:] = [mask_index(description) for description in descriptions]
    return indices


def mask_weight(index: int, x: float, y: float) -> float:
    """How much of the secondary tile mask `index` shows at pixel `(x, y)`, 0-63 each, y up."""
    inverted, shape = index >= 6, index % 6
    rise = y if inverted else 63.0 - y
    if shape == 0:
        value = x if inverted else 63.0 - x
    elif shape == 1:
        value = rise
    elif shape in (3, 5):
        value = rise + (63.0 - x) - (64.0 if shape == 5 else 0.0)
    else:
        value = rise + x - (64.0 if shape == 4 else 0.0)
    return 1.0 - min(max(value / 63.0, 0.0), 1.0)


def mask_weights(pixels: int) -> np.ndarray:
    """All twelve masks at `pixels` pixels a cell side, `[mask, y, x]` with y up, each pixel taken
    at its centre on the game's 64-pixel mask."""
    centres = np.clip((np.arange(pixels, dtype=np.float64) + 0.5) * 64 / pixels - 0.5, 0.0, 63.0)
    x = np.broadcast_to(centres[None, :], (pixels, pixels))
    y = np.broadcast_to(centres[:, None], (pixels, pixels))
    masks = []
    for inverted in (False, True):
        rise = y if inverted else 63.0 - y
        values = (
            x if inverted else 63.0 - x,
            rise,
            rise + x,
            rise + (63.0 - x),
            rise + x - 64.0,
            rise + (63.0 - x) - 64.0,
        )
        masks += [1.0 - np.clip(value / 63.0, 0.0, 1.0) for value in values]
    return np.stack(masks).astype(np.float32)


def texture_cells(
    data: bytes, cell_size: int, pixels: int = TEXTURE_CELL_PIXELS
) -> np.ndarray | None:
    """A texture's cells as the game reads them: `[row, column, y, x]` RGBA, rows and y counted
    from the image's first scanline, resized to `cell_size` cells of `pixels` pixels when the
    image is another size. None when Pillow cannot read it."""
    if cell_size < 1 or pixels < 1:
        return None
    side = cell_size * pixels
    try:
        from PIL import Image  # noqa: PLC0415 - lazy: needs the `worldbuilder` extra (pillow)

        with Image.open(io.BytesIO(data)) as image:
            top_first = (
                image.format == "TGA"
                and len(data) > _TGA_DESCRIPTOR
                and bool(data[_TGA_DESCRIPTOR] & _TGA_TOP_ORIGIN)
            )
            rgba = image.convert("RGBA")
            if rgba.size != (side, side):
                rgba = rgba.resize((side, side), Image.Resampling.BOX)
            picture = np.asarray(rgba, dtype=np.uint8)
    except (ImportError, OSError, ValueError):
        return None
    # Pillow gives rows top first; a bottom-up file's first scanline is the picture's last row.
    if not top_first:
        picture = picture[::-1]
    cells = picture.reshape(cell_size, pixels, cell_size, pixels, 4).transpose(0, 2, 1, 3, 4)
    return np.ascontiguousarray(cells)


@dataclass(frozen=True, eq=False)
class TerrainAtlas:
    """A map's texture cells in one picture: cell number `n` at slot row `n // side`, column
    `n % side`, `cell_pixels` a side, slot row 0 and each cell's row 0 at the bottom."""

    pixels: np.ndarray
    side: int
    cell_pixels: int


def atlas_key(textures: Sequence[BlendTileTexture]) -> tuple[tuple[str, int, int], ...]:
    """What an atlas depends on: each texture's name, first cell and size."""
    return tuple(
        (texture.name.lower(), texture.cell_start, texture.cell_size) for texture in textures
    )


def build_atlas(
    textures: Sequence[BlendTileTexture],
    cells_for: Callable[[BlendTileTexture, int], np.ndarray | None],
    max_size: int = 16384,
) -> TerrainAtlas:
    """The atlas of a map's texture table. `cells_for(texture, pixels)` gives the texture's cells
    (`texture_cells`) or None; a cell's pixels halve until the atlas fits in `max_size`."""
    count = max((texture.cell_start + texture.cell_count for texture in textures), default=1)
    side = max(1, math.ceil(math.sqrt(count)))
    pixels = TEXTURE_CELL_PIXELS
    while pixels > 1 and side * pixels > max_size:
        pixels //= 2
    atlas = np.empty((side * pixels, side * pixels, 4), dtype=np.uint8)
    atlas[:] = MISSING_TEXTURE
    for texture in textures:
        size = texture.cell_size
        cells = cells_for(texture, pixels)
        if cells is None or cells.shape != (size, size, pixels, pixels, 4):
            continue
        for row in range(size):
            for column in range(size):
                slot_row, slot_column = divmod(texture.cell_start + row * size + column, side)
                if slot_row >= side:
                    continue
                atlas[
                    slot_row * pixels : (slot_row + 1) * pixels,
                    slot_column * pixels : (slot_column + 1) * pixels,
                ] = cells[row, column]
    return TerrainAtlas(atlas, side, pixels)


def blend_secondaries(descriptions: Sequence[BlendDescription]) -> np.ndarray:
    """Per blend number (0 for none, then each description) the tile it mixes in."""
    tiles = np.zeros(len(descriptions) + 1, dtype=np.uint16)
    if descriptions:
        tiles[1:] = [description.secondary_texture_tile & 0xFFFF for description in descriptions]
    return tiles


# The cell data flag of a cell drawn through its cliff mapping.
CLIFF_FLAG = 0x100


@dataclass(frozen=True, eq=False)
class CliffCells:
    """The cells drawn through their cliff mapping, `[y, x]`: whether each is, its texture's
    first cell and size, and its corners `(x, y)` from (x, y) round to (x, y + 1) in texture
    cells of that texture's picture."""

    drawn: np.ndarray
    starts: np.ndarray
    sizes: np.ndarray
    corners: np.ndarray


def cliff_cells(
    tiles: np.ndarray,
    cliffs: np.ndarray,
    mappings: Sequence[CliffTextureMapping],
    textures: Sequence[BlendTileTexture],
) -> CliffCells:
    """Which cells show their cliff mapping, and where their corners fall in its texture."""
    count = len(mappings)
    numbers = np.asarray(cliffs, dtype=np.int64)
    known = (numbers > 0) & (numbers <= count)
    rows, columns = numbers.shape
    corners = np.zeros((rows, columns, 8), dtype=np.float32)
    starts = np.zeros((rows, columns), dtype=np.int64)
    sizes = np.ones((rows, columns), dtype=np.int64)
    if not count or not textures:
        return CliffCells(np.zeros_like(known), starts, sizes, corners)
    mapping_tiles = np.array([mapping.texture_tile for mapping in mappings], dtype=np.int64)
    mapping_classes = np.concatenate(([-1], texture_classes(mapping_tiles, textures)))
    coords = np.zeros((count + 1, 8), dtype=np.float32)
    coords[1:] = [
        [
            *mapping.bottom_left_coords,
            *mapping.bottom_right_coords,
            *mapping.top_right_coords,
            *mapping.top_left_coords,
        ]
        for mapping in mappings
    ]
    index = np.where(known, numbers, 0)
    classes = mapping_classes[index]
    drawn = known & (classes >= 0) & (classes == texture_classes(np.asarray(tiles), textures))
    table_starts = np.array([texture.cell_start for texture in textures], dtype=np.int64)
    table_sizes = np.array([max(texture.cell_size, 1) for texture in textures], dtype=np.int64)
    safe = np.maximum(classes, 0)
    starts = np.where(drawn, table_starts[safe], 0)
    sizes = np.where(drawn, table_sizes[safe], 1)
    corners = np.where(drawn[..., None], coords[index] * sizes[..., None], 0.0).astype(np.float32)
    return CliffCells(drawn, starts, sizes, corners)


def cell_data(
    tiles: np.ndarray,
    blends: np.ndarray,
    three_way: np.ndarray,
    cliffs: np.ndarray | None,
    indices: np.ndarray,
    secondaries: np.ndarray,
    cliff: CliffCells | None = None,
) -> np.ndarray:
    """Per cell `[y, x]`, four `uint16`: its tile, its blend's tile, its 3-way blend's tile, and
    `(3-way mask + 1) << 4 | (blend mask + 1)`, 0 for none. A blend number past the table counts
    as none, a cell with a cliff mapping has no blends, and a 3-way blend needs a blend under it.
    A cell drawn through its cliff mapping (`cliff`) instead carries its texture's first cell and
    size where the blend tiles go, and `CLIFF_FLAG`."""
    count = len(indices)
    blends = np.asarray(blends, dtype=np.int64)
    three_way = np.asarray(three_way, dtype=np.int64)
    blended = (blends > 0) & (blends < count)
    if cliffs is not None:
        blended &= np.asarray(cliffs) == 0
    layered = blended & (three_way > 0) & (three_way < count)
    first = np.where(blended, blends, 0)
    second = np.where(layered, three_way, 0)
    codes = np.where(blended, indices[first].astype(np.int64) + 1, 0)
    codes |= np.where(layered, indices[second].astype(np.int64) + 1, 0) << 4
    data = np.empty(np.shape(tiles) + (4,), dtype=np.uint16)
    data[..., 0] = np.asarray(tiles, dtype=np.int64) & 0xFFFF
    data[..., 1] = secondaries[first]
    data[..., 2] = secondaries[second]
    data[..., 3] = codes
    if cliff is not None:
        drawn = cliff.drawn
        data[..., 1] = np.where(drawn, cliff.starts & 0xFFFF, data[..., 1])
        data[..., 2] = np.where(drawn, cliff.sizes & 0xFFFF, data[..., 2])
        data[..., 3] = np.where(drawn, CLIFF_FLAG, data[..., 3])
    return data
