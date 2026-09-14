"""Whole-map texture edits: Optimize tiles and blend tiles, Remove Cliff Tex Mapping and Remove all
texture blends, and the test behind Show Stretched Tiles (PHASE3.md, 3.9).

- *Optimize tiles and blend tiles* (`optimizeTiles`, `0x00675C10`) rebuilds the texture table and
  the blend descriptions from what the map uses. Walking the cells a column at a time, each
  cell's texture, then its blend's texture, then its 3-way blend's texture takes the next cells of
  the new table the first time it is met; unused textures go. Every tile keeps its place within
  its texture. A blend whose tile is the cell's own is dropped, a 3-way blend without a blend
  too, and a blend without a 3-way blend loses flags bit 1. The descriptions are numbered anew in
  the order they are met. A cliff mapping's tile becomes its texture's tile at the cell one past
  the map's last column and row, as WorldBuilder's loop leaves its counters there.
- *Remove Cliff Tex Mapping* (`0x0067E4D0`): every cell's cliff mapping index goes to 0 and the
  table is emptied.
- *Remove all texture blends* (`0x00670910` for each cell): a cell with a blend or a 3-way blend
  loses both and its cliff mapping; the descriptions stay. WorldBuilder then refits the cliff
  mapping of flat cells next to cliffs (`updateFlatCellForAdjacentCliffs`), which is not built.
- *Show Stretched Tiles* (`0x0075B520`, `0x007591D0`): a cell is stretched when a corner's slope
  along x or y is steeper than the threshold, the Apply texture check with the threshold as the
  highest slope.
- *Show Unblended Tiles* (`0x00663BB0`): a playable cell with no blend whose four side
  neighbours do not all show its texture, a neighbour with a blend counting as one that does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np

from sage_map.assets.blend_tile_data import BlendDescription, BlendTileTexture, CliffTextureMapping
from sage_worldbuilder.terrain.apply_texture import qualifying_samples
from sage_worldbuilder.terrain.blending import DescriptionIndex
from sage_worldbuilder.terrain.cells import TileLayer
from sage_worldbuilder.terrain.textures import texture_classes

__all__ = [
    "DEFAULT_STRETCH_THRESHOLD",
    "TableEdit",
    "blends_removed",
    "cliff_mappings_removed",
    "optimized_tiles",
    "stretched_cells",
    "unblended_cells",
]

DEFAULT_STRETCH_THRESHOLD = 45.0


@dataclass
class TableEdit:
    """A whole-map texture edit: `(layer, x0, y0, values)` blocks, and the new texture, blend
    description and cliff mapping tables, None for a table left as it is."""

    patches: list[tuple[TileLayer, int, int, np.ndarray]]
    textures: list[BlendTileTexture] | None = None
    descriptions: list[BlendDescription] | None = None
    cliff_mappings: list[CliffTextureMapping] | None = None


def _box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    rows = np.flatnonzero(mask.any(axis=1))
    columns = np.flatnonzero(mask.any(axis=0))
    if not rows.size:
        return None
    return int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1


def cliff_mappings_removed(
    layers: Mapping[TileLayer, np.ndarray | None], cliff_mappings: Sequence[CliffTextureMapping]
) -> TableEdit | None:
    """Remove Cliff Tex Mapping, or None when the map has none."""
    cliff = layers.get(TileLayer.CLIFF_TEXTURES)
    if cliff is None:
        return None
    box = _box(cliff != 0)
    if box is None and not cliff_mappings:
        return None
    patches = []
    if box is not None:
        x0, y0, x1, y1 = box
        patches.append((TileLayer.CLIFF_TEXTURES, x0, y0, np.zeros_like(cliff[y0:y1, x0:x1])))
    return TableEdit(patches, cliff_mappings=[])


def blends_removed(layers: Mapping[TileLayer, np.ndarray | None]) -> TableEdit | None:
    """Remove all texture blends, or None when no cell has one."""
    blends = layers.get(TileLayer.BLENDS)
    three_way = layers.get(TileLayer.THREE_WAY_BLENDS)
    if blends is None or three_way is None:
        return None
    blended = (blends != 0) | (three_way != 0)
    box = _box(blended)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    patches = [
        (TileLayer.BLENDS, x0, y0, np.where(blended, 0, blends)[y0:y1, x0:x1]),
        (TileLayer.THREE_WAY_BLENDS, x0, y0, np.where(blended, 0, three_way)[y0:y1, x0:x1]),
    ]
    cliff = layers.get(TileLayer.CLIFF_TEXTURES)
    if cliff is not None and (cliff[blended] != 0).any():
        patches.append(
            (TileLayer.CLIFF_TEXTURES, x0, y0, np.where(blended, 0, cliff)[y0:y1, x0:x1])
        )
    return TableEdit(patches)


def optimized_tiles(
    layers: Mapping[TileLayer, np.ndarray | None],
    textures: Sequence[BlendTileTexture],
    descriptions: Sequence[BlendDescription],
    cliff_mappings: Sequence[CliffTextureMapping],
) -> TableEdit | None:
    """Optimize tiles and blend tiles, or None for a map without textures or blend layers."""
    tiles = layers.get(TileLayer.TILES)
    blends = layers.get(TileLayer.BLENDS)
    three_way = layers.get(TileLayer.THREE_WAY_BLENDS)
    if tiles is None or blends is None or three_way is None or not textures:
        return None
    rows, columns = tiles.shape
    textures = list(textures)
    starts = np.array([texture.cell_start for texture in textures], dtype=np.int64)
    # A tile of no texture counts as the first texture's, as WorldBuilder clamps it.
    classes = np.maximum(texture_classes(tiles, textures), 0).astype(np.int64)
    offsets = tiles - starts[classes] * 4
    count = len(descriptions)
    secondary = np.array([d.secondary_texture_tile for d in descriptions] + [0], dtype=np.int64)
    described = np.maximum(texture_classes(secondary, textures), 0).astype(np.int64)
    described_offsets = secondary - starts[described] * 4

    blend_numbers = np.where((blends > 0) & (blends <= count), blends, 0).astype(np.int64)
    three_numbers = np.where((three_way > 0) & (three_way <= count), three_way, 0).astype(np.int64)
    # Column by column: arrays `[x, y]`, flattened.
    by_column = [array.T.ravel() for array in (classes, blend_numbers, three_numbers)]
    tile_classes, blend_column, three_column = by_column
    met = np.stack(
        (
            tile_classes,
            np.where(blend_column > 0, described[blend_column - 1], -1),
            np.where(three_column > 0, described[three_column - 1], -1),
        ),
        axis=1,
    ).ravel()
    met = met[met >= 0]
    _, first = np.unique(met, return_index=True)
    order = met[np.sort(first)].tolist()

    new_textures: list[BlendTileTexture] = []
    new_starts = np.zeros(len(textures), dtype=np.int64)
    placed: set[int] = set()

    def place(number: int) -> None:
        if number in placed:
            return
        placed.add(number)
        cells = sum(texture.cell_count for texture in new_textures)
        new_starts[number] = cells
        new_textures.append(replace(textures[number], cell_start=cells))

    for number in order:
        place(number)

    new_tiles = offsets + new_starts[classes] * 4
    new_secondary = described_offsets + new_starts[described] * 4
    blend_tile = np.where(blend_numbers > 0, new_secondary[blend_numbers - 1], -1)
    three_tile = np.where(three_numbers > 0, new_secondary[three_numbers - 1], -1)
    keep_blend = (blend_numbers > 0) & (blend_tile != new_tiles)
    keep_three = (three_numbers > 0) & keep_blend & (three_tile != new_tiles)
    # A code per blend kept: the description's number doubled, plus 1 when flags bit 1 goes.
    blend_codes = np.where(keep_blend, blend_numbers * 2 + (three_way == 0), -1)
    three_codes = np.where(keep_three, three_numbers * 2, -1)
    codes = np.stack((blend_codes.T.ravel(), three_codes.T.ravel()), axis=1).ravel()
    codes = codes[codes >= 0]
    _, first = np.unique(codes, return_index=True)
    index = DescriptionIndex([])
    renumbered = np.zeros(2 * (count + 1), dtype=np.int64)
    for code in codes[np.sort(first)].tolist():
        number = code // 2
        description = descriptions[number - 1]
        flags = description.flags & ~2 if code % 2 else description.flags
        turned = replace(
            description, secondary_texture_tile=int(new_secondary[number - 1]), flags=flags
        )
        renumbered[code] = index.number(turned)
    new_blends = np.where(keep_blend, renumbered[np.maximum(blend_codes, 0)], 0)
    new_three = np.where(keep_three, renumbered[np.maximum(three_codes, 0)], 0)

    new_mappings = []
    for mapping in cliff_mappings:
        number = max(int(texture_classes(np.array([mapping.texture_tile]), textures)[0]), 0)
        place(number)
        entry = new_textures[[t.name for t in new_textures].index(textures[number].name)]
        size = entry.cell_size
        cell = (columns // 2) % size + ((rows // 2) % size) * size + entry.cell_start
        tile = cell * 4 + (rows & 1) * 2 + (columns & 1)
        new_mappings.append(replace(mapping, texture_tile=int(tile)))

    patches = [
        (TileLayer.TILES, 0, 0, new_tiles.astype(tiles.dtype)),
        (TileLayer.BLENDS, 0, 0, new_blends.astype(blends.dtype)),
        (TileLayer.THREE_WAY_BLENDS, 0, 0, new_three.astype(three_way.dtype)),
    ]
    return TableEdit(patches, new_textures, list(index.added), new_mappings)


def unblended_cells(
    layers: Mapping[TileLayer, np.ndarray | None],
    textures: Sequence[BlendTileTexture],
    border: int,
) -> np.ndarray | None:
    """Show Unblended Tiles (`0x00663BB0`): the playable cells with no blend of their own that
    have a side neighbour showing another texture. A neighbour with a blend counts as matching,
    so an edge that is blended from either side is not marked. None without the blend layers.

    WorldBuilder reads a neighbour's blend through an index that wraps to the next row at the map
    edge; inside the border, where it looks, the neighbours are always on the map."""
    tiles = layers.get(TileLayer.TILES)
    blends = layers.get(TileLayer.BLENDS)
    three_way = layers.get(TileLayer.THREE_WAY_BLENDS)
    if tiles is None or blends is None or three_way is None:
        return None
    rows, columns = tiles.shape
    classes = texture_classes(tiles, textures)
    blended = blends != 0
    # A blended cell shows no texture of its own, as `getTextureClass` reports it.
    shown = np.where(blended | (three_way != 0), -1, classes)
    sides = np.zeros(tiles.shape, dtype=np.int64)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ys = np.clip(np.arange(rows) + dy, 0, rows - 1)
        xs = np.clip(np.arange(columns) + dx, 0, columns - 1)
        neighbour = np.ix_(ys, xs)
        sides += ((shown[neighbour] == classes) | blended[neighbour]).astype(np.int64)
    marked = (sides < 4) & ~blended
    playable = np.zeros(tiles.shape, dtype=bool)
    edge = max(border, 0)
    if edge < rows - edge and edge < columns - edge:
        playable[edge : rows - edge, edge : columns - edge] = True
    return marked & playable


def stretched_cells(heights: np.ndarray, threshold: float) -> np.ndarray:
    """Per cell, whether a corner is steeper than `threshold` degrees along x or y."""
    limit = int(threshold)
    huge = 2**62
    samples = np.pad(
        qualifying_samples(heights, (0, limit), (-huge, huge)), ((0, 1), (0, 1)), "edge"
    )
    flat = samples[:-1, :-1] & samples[:-1, 1:] & samples[1:, 1:] & samples[1:, :-1]
    return ~flat
