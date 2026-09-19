"""Painting textures: the map's texture table, which texture each cell shows, and the tiles a
paint writes (Flood Fill, which keeps blends, is in `blending`).

A map lists the textures it uses (`BlendTileData.textures`), each a run of 64-pixel texture cells
from `cell_start`; a tile value is `(cell << 2) | quadrant` (PHASE3.md, Tile values). Painting a
texture the map lacks appends it to the table. WorldBuilder refuses a texture that would take
the map past 4,096 texture cells (`cmp eax, 0x1000` at `0x0066F664`) and the game's parser
asserts fewer than 200 textures (`0x0076F920`).

A texture is tiled over the map's cell coordinates shifted by a tiling offset per texture
(WorldBuilder's `getTileNdxForClass`, `0x00670100`), so neighbouring paints of the same texture
join without a seam. The map does not store the offsets; WorldBuilder can shift them and re-tile
an area, so a map's own tiling of a texture may be offset. Here a texture's offset is the one most
of its cells already follow (93% of corpus cells follow their texture's; PHASE3.md), and (0, 0)
for a texture the map lacks. A paint clears the blends, 3-way blends and cliff mappings of the
cells it covers, as `setTileNdx` (`0x0066F010`) does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from sage_map.assets.blend_tile_data import BlendTileData, BlendTileTexture
from sage_worldbuilder.new_map import tile_pattern
from sage_worldbuilder.terrain.cells import TileLayer

__all__ = [
    "NO_ROOM_MESSAGE",
    "TEXTURE_CELL_LIMIT",
    "TEXTURE_LIMIT",
    "TextureCapacityError",
    "TilePaint",
    "paint_texture_block",
    "planned_texture",
    "texture_classes",
    "texture_index",
    "texture_tiles",
    "tiling_offset",
]

TEXTURE_CELL_LIMIT = 4096
TEXTURE_LIMIT = 199
# WorldBuilder's own message (string 33461).
NO_ROOM_MESSAGE = (
    "There is not room to add this texture to the map. You can use the paintbucket tool to "
    "replace another texture with this one."
)
_CLEARED = (TileLayer.BLENDS, TileLayer.THREE_WAY_BLENDS, TileLayer.CLIFF_TEXTURES)

TilePaint = tuple[int, int, dict[TileLayer, np.ndarray]]


class TextureCapacityError(ValueError):
    """The map's texture table has no room for another texture."""


def texture_index(blend: BlendTileData, name: str) -> int | None:
    """The index of the texture `name` in the map's table (case-insensitively), or None."""
    key = name.lower()
    return next(
        (index for index, texture in enumerate(blend.textures) if texture.name.lower() == key),
        None,
    )


def planned_texture(blend: BlendTileData, name: str, cell_size: int) -> BlendTileTexture:
    """The table entry the texture `name` gets when it is added after the current ones. Raises
    TextureCapacityError when it does not fit."""
    cell_count = cell_size * cell_size
    if (
        len(blend.textures) >= TEXTURE_LIMIT
        or blend.texture_cell_count + cell_count > TEXTURE_CELL_LIMIT
    ):
        raise TextureCapacityError(NO_ROOM_MESSAGE)
    return BlendTileTexture(blend.texture_cell_count, cell_count, cell_size, 0, name)


def texture_classes(tiles: np.ndarray, textures: Sequence[BlendTileTexture]) -> np.ndarray:
    """The index into `textures` each cell shows, `[cell_y, cell_x]` like `tiles`; -1 where a
    tile falls in no texture's cells."""
    if not textures:
        return np.full(tiles.shape, -1, dtype=np.int16)
    size = max(texture.cell_start + texture.cell_count for texture in textures)
    lookup = np.full(size + 1, -1, dtype=np.int16)
    for index, texture in enumerate(textures):
        lookup[texture.cell_start : texture.cell_start + texture.cell_count] = index
    cells = np.clip(tiles >> 2, 0, size)
    return lookup[cells]


def tiling_offset(tiles: np.ndarray, texture: BlendTileTexture) -> tuple[int, int]:
    """The tiling offset most cells showing `texture` follow: the `(ox, oy)`, each below twice the
    texture's `cell_size`, that tiling at cell `(x + ox, y + oy)` gives them. (0, 0) when no cell
    shows it."""
    size = texture.cell_size
    if size <= 0:
        return 0, 0
    cells = tiles >> 2
    ys, xs = np.nonzero((cells >= texture.cell_start) & (cells < texture.cell_start + size * size))
    if not ys.size:
        return 0, 0
    found = tiles[ys, xs]
    local = (found >> 2) - texture.cell_start
    ox = (2 * (local % size) + (found & 1) - xs) % (2 * size)
    oy = (2 * (local // size) + ((found >> 1) & 1) - ys) % (2 * size)
    best = int(np.bincount((ox * 2 * size + oy).astype(np.int64)).argmax())
    return best // (2 * size), best % (2 * size)


def texture_tiles(
    texture: BlendTileTexture,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    offset: tuple[int, int] = (0, 0),
) -> np.ndarray:
    """The tiles of `texture` over cells `x0 <= x < x1`, `y0 <= y < y1`, tiled with `offset`."""
    ox, oy = offset
    return tile_pattern(x1 - x0, y1 - y0, texture.cell_start, texture.cell_size, x0 + ox, y0 + oy)


def paint_texture_block(
    layers: Mapping[TileLayer, np.ndarray],
    block: tuple[int, int, int, int],
    texture: BlendTileTexture,
    mask: np.ndarray | None = None,
    offset: tuple[int, int] = (0, 0),
) -> dict[TileLayer, np.ndarray] | None:
    """The new contents of `block` (`x0, y0, x1, y1`) with `texture` painted on it with the tiling
    `offset`, only where `mask` is True when one is given: the tiles, and the blend layers cleared
    there. Layers that would not change are left out; None when nothing changes."""
    x0, y0, x1, y1 = block
    painted: dict[TileLayer, np.ndarray] = {}
    current = layers[TileLayer.TILES][y0:y1, x0:x1]
    tiles = texture_tiles(texture, x0, y0, x1, y1, offset)
    if mask is not None:
        tiles = np.where(mask, tiles, current)
    if not np.array_equal(tiles, current):
        painted[TileLayer.TILES] = tiles
    for layer in _CLEARED:
        values = layers.get(layer)
        if values is None:
            continue
        old = values[y0:y1, x0:x1]
        new = np.where(mask, 0, old) if mask is not None else np.zeros_like(old)
        if not np.array_equal(new, old):
            painted[layer] = new
    return painted or None
