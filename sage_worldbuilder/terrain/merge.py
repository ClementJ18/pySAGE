"""One map's terrain textures merged into another's, as WorldBuilder's `.scb` import does it
(`WorldHeightMapEdit::mergeTexture`, `0x00684420`).

The source's textures are matched to the map's by name. One the map lacks is appended after the
map's own, its cells taken from the end of the map's texture cells; a texture that does not fit
(the limits `planned_texture` holds a paint to, which the game's parser needs) is left out, and the
cells showing it keep what the map had. A tile then moves by four for each cell its texture's
first cell moves between the two tables. Each blend description is carried over with its
secondary texture's tile moved the same way, reusing an equal description the map already has.
Every cliff mapping of the source is appended with its tile moved, and a cell's cliff mapping
number goes up by the number of mappings the map had. The merged cells are the source's, placed
with their first cell at `(dx, dy)` and cut to the map.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from sage_map.assets.blend_tile_data import (
    BlendDescription,
    BlendTileData,
    BlendTileTexture,
    CliffTextureMapping,
)
from sage_worldbuilder.terrain.blending import DescriptionIndex
from sage_worldbuilder.terrain.cells import TileLayer, layer_array
from sage_worldbuilder.terrain.textures import (
    TEXTURE_CELL_LIMIT,
    TEXTURE_LIMIT,
    texture_classes,
)

__all__ = ["TextureMerge", "merge_textures"]

_BLEND_LAYERS = (TileLayer.BLENDS, TileLayer.THREE_WAY_BLENDS)


@dataclass
class TextureMerge:
    """The merged cells as `(layer, x0, y0, values)` blocks, the map's new tables, and the names
    of the source textures that did not fit."""

    patches: list[tuple[TileLayer, int, int, np.ndarray]]
    textures: list[BlendTileTexture]
    descriptions: list[BlendDescription]
    cliff_mappings: list[CliffTextureMapping]
    left_out: list[str] = field(default_factory=list)


@dataclass
class _Table:
    """The map's texture table with the source's missing textures appended; for each source
    texture, how many cells its cells move by and whether it is in the table; the names of those
    that are not."""

    textures: list[BlendTileTexture]
    shifts: np.ndarray
    kept: np.ndarray
    left_out: list[str]


def _merged_table(target: list[BlendTileTexture], source: list[BlendTileTexture]) -> _Table:
    textures = list(target)
    by_name = {texture.name.lower(): number for number, texture in enumerate(textures)}
    cells = sum(texture.cell_count for texture in textures)
    shifts = np.zeros(len(source), dtype=np.int64)
    kept = np.ones(len(source), dtype=bool)
    left_out: list[str] = []
    for number, texture in enumerate(source):
        found = by_name.get(texture.name.lower())
        if found is None:
            if len(textures) >= TEXTURE_LIMIT or cells + texture.cell_count > TEXTURE_CELL_LIMIT:
                kept[number] = False
                left_out.append(texture.name)
                continue
            textures.append(replace(texture, cell_start=cells, magic_value=0))
            cells += texture.cell_count
            found = by_name[texture.name.lower()] = len(textures) - 1
        shifts[number] = textures[found].cell_start - texture.cell_start
    return _Table(textures, shifts, kept, left_out)


def _moved(tiles: np.ndarray, source: list[BlendTileTexture], table: _Table) -> np.ndarray:
    """Source tiles in the map's table; -1 where the tile's texture is unknown or left out."""
    if not source:
        return np.full(tiles.shape, -1, dtype=np.int64)
    classes = texture_classes(tiles, source).astype(np.int64)
    number = np.maximum(classes, 0)
    valid = (classes >= 0) & table.kept[number]
    return np.where(valid, tiles + table.shifts[number] * 4, -1)


def merge_textures(
    target: BlendTileData, source: BlendTileData, dx: int, dy: int
) -> TextureMerge | None:
    """The textures of `source` merged into `target` with its first cell at `(dx, dy)`, or None
    when no source cell lands on the map."""
    tiles = layer_array(target, TileLayer.TILES)
    source_tiles = layer_array(source, TileLayer.TILES)
    if tiles is None or source_tiles is None:
        return None
    rows, columns = source_tiles.shape
    x0, y0 = max(dx, 0), max(dy, 0)
    x1, y1 = min(dx + columns, tiles.shape[1]), min(dy + rows, tiles.shape[0])
    if x0 >= x1 or y0 >= y1:
        return None
    table = _merged_table(target.textures, source.textures)

    index = DescriptionIndex(target.blend_descriptions)
    blend_numbers = np.zeros(len(source.blend_descriptions) + 1, dtype=np.int64)
    if source.blend_descriptions:
        secondary = _moved(
            np.array([d.secondary_texture_tile for d in source.blend_descriptions]),
            source.textures,
            table,
        )
        for number, (description, tile) in enumerate(
            zip(source.blend_descriptions, secondary.tolist(), strict=True), 1
        ):
            if tile >= 0:
                blend_numbers[number] = index.number(
                    replace(description, secondary_texture_tile=tile)
                )
    cliff_mappings = list(target.cliff_texture_mappings)
    cliff_offset = len(cliff_mappings)
    if source.cliff_texture_mappings:
        cliff_tiles = _moved(
            np.array([m.texture_tile for m in source.cliff_texture_mappings]),
            source.textures,
            table,
        )
        cliff_mappings += [
            replace(mapping, texture_tile=max(tile, 0))
            for mapping, tile in zip(
                source.cliff_texture_mappings, cliff_tiles.tolist(), strict=True
            )
        ]

    window = (slice(y0 - dy, y1 - dy), slice(x0 - dx, x1 - dx))
    moved = _moved(source_tiles[window], source.textures, table)
    taken = moved >= 0
    merged = {TileLayer.TILES: np.where(taken, moved, tiles[y0:y1, x0:x1])}
    for layer in (*_BLEND_LAYERS, TileLayer.CLIFF_TEXTURES):
        current, incoming = layer_array(target, layer), layer_array(source, layer)
        if current is None:
            continue
        values = np.zeros_like(taken, dtype=np.int64)
        if incoming is not None:
            numbers = np.clip(incoming[window], 0, None)
            if layer is TileLayer.CLIFF_TEXTURES:
                values = np.where(numbers > 0, numbers + cliff_offset, 0)
            else:
                values = blend_numbers[np.minimum(numbers, len(blend_numbers) - 1)]
        merged[layer] = np.where(taken, values, current[y0:y1, x0:x1])
    return TextureMerge(
        [(layer, x0, y0, values) for layer, values in merged.items()],
        table.textures,
        [*target.blend_descriptions, *index.added],
        cliff_mappings,
        table.left_out,
    )
