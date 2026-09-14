"""The per-cell attribute layers of `BlendTileData`, and painting them.

`BlendTileData` stores each layer as `[x][y]` lists with y counting up (like the tiles, and unlike
the heightmap, whose saved rows run top first). The editor works on `[cell_y, cell_x]` arrays, as
`TerrainGrid` holds the heights. What each stored True means, from WorldBuilder's painting loop
(`0x006245DA`, a switch on the painting mode) and the corpus:

- passability is three layers that WorldBuilder always writes together, one flag set or none:
  impassable, impassable to players, extra passable;
- `passage_widths` True is Narrow (set on 0.1% of the cells of 9 of 165 sampled maps);
- `taintability` True is Taintable;
- `visibility` True is Visible (every cell on 138 of 165 sampled maps);
- `flammability` is a byte (`TileFlammability`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import Enum

import numpy as np

from sage_map.assets.blend_tile_data import BlendTileData, TileFlammability
from sage_worldbuilder.brush_options import PaintMode, PaintOptions, Passability
from sage_worldbuilder.terrain.brushes import brush_center

__all__ = [
    "CellLayer",
    "CellPaint",
    "Layer",
    "TileLayer",
    "layer_array",
    "paint_cells",
    "paint_values",
    "square_block",
    "write_layer",
]


class CellLayer(Enum):
    """A cell attribute layer, by the `BlendTileData` attribute that stores it."""

    IMPASSABLE = "impassability"
    IMPASSABLE_TO_PLAYERS = "impassability_to_players"
    EXTRA_PASSABLE = "extra_passability"
    NARROW = "passage_widths"
    TAINTABLE = "taintability"
    FLAMMABILITY = "flammability"
    VISIBLE = "visibility"


class TileLayer(Enum):
    """The texture tile and blend layers, stored `[x][y]` like the cell attributes: the tile value
    of each cell, and indices into the blend descriptions and cliff mappings (0 for none)."""

    TILES = "tiles"
    BLENDS = "blends"
    THREE_WAY_BLENDS = "three_way_blends"
    CLIFF_TEXTURES = "cliff_textures"


Layer = CellLayer | TileLayer
CellPaint = tuple[int, int, dict[CellLayer, np.ndarray]]


def layer_array(blend: BlendTileData, layer: Layer) -> np.ndarray | None:
    """The layer as `[cell_y, cell_x]`: bool, uint8 for flammability, int64 for the tile and blend
    layers. None when the map's chunk version has no such layer."""
    stored = getattr(blend, layer.value)
    if stored is None:
        return None
    if isinstance(layer, TileLayer):
        values = np.array(stored, dtype=np.int64)
    elif layer is CellLayer.FLAMMABILITY:
        values = np.array([[int(value) for value in column] for column in stored], dtype=np.uint8)
    else:
        values = np.array(stored, dtype=bool)
    return np.ascontiguousarray(values.T)


def write_layer(blend: BlendTileData, layer: Layer, x0: int, y0: int, values: np.ndarray) -> None:
    """Store `values[row, column]` from cell `(x0, y0)` into the layer's saved lists."""
    stored = getattr(blend, layer.value)
    if stored is None:
        raise ValueError(f"the map has no {layer.value} layer")
    for offset, column in enumerate(values.T.tolist()):
        if isinstance(layer, TileLayer):
            converted: list[object] = [int(value) for value in column]
        elif layer is CellLayer.FLAMMABILITY:
            converted = [TileFlammability(value) for value in column]
        else:
            converted = [bool(value) for value in column]
        stored[x0 + offset][y0 : y0 + len(converted)] = converted


def paint_values(options: PaintOptions) -> dict[CellLayer, int]:
    """What one painted cell gets in each layer the painting mode writes."""
    mode = options.mode
    if mode is PaintMode.PASSABILITY:
        state = options.passability
        return {
            CellLayer.IMPASSABLE: int(state is Passability.IMPASSABLE),
            CellLayer.IMPASSABLE_TO_PLAYERS: int(state is Passability.IMPASSABLE_TO_PLAYERS),
            CellLayer.EXTRA_PASSABLE: int(state is Passability.EXTRA_PASSABLE),
        }
    if mode is PaintMode.PASSAGE_WIDTH:
        return {CellLayer.NARROW: int(options.narrow)}
    if mode is PaintMode.TAINTABILITY:
        return {CellLayer.TAINTABLE: int(options.taintable)}
    if mode is PaintMode.FLAMMABILITY:
        return {CellLayer.FLAMMABILITY: options.flammability}
    if mode is PaintMode.VISIBILITY:
        return {CellLayer.VISIBLE: int(options.visible)}
    return {}


def square_block(
    cell: tuple[float, float], width: int, shape: tuple[int, int]
) -> tuple[int, int, int, int] | None:
    """The `width`-square of cells a tile brush covers at a fractional cell position, centred as
    the height brushes are: `(x0, y0, x1, y1)`, half-open and clipped to a grid of `shape` (rows,
    columns), or None when it misses the grid."""
    cx, cy = brush_center(cell[0], cell[1], width)
    x0 = math.floor(cx - width / 2 + 0.5)
    y0 = math.floor(cy - width / 2 + 0.5)
    rows, columns = shape
    x1, y1 = min(x0 + width, columns), min(y0 + width, rows)
    x0, y0 = max(x0, 0), max(y0, 0)
    if x0 >= x1 or y0 >= y1:
        return None
    return x0, y0, x1, y1


def paint_cells(
    layers: Mapping[CellLayer, np.ndarray],
    cell: tuple[float, float],
    width: int,
    values: Mapping[CellLayer, int],
) -> CellPaint | None:
    """The new contents of the square a tile brush covers, for each layer it paints that the map
    has: `(x0, y0, {layer: block})`, or None when it would change nothing."""
    present = {layer: layers[layer] for layer in values if layers.get(layer) is not None}
    if not present:
        return None
    shape = next(iter(present.values())).shape
    block = square_block(cell, width, shape)
    if block is None:
        return None
    x0, y0, x1, y1 = block
    painted: dict[CellLayer, np.ndarray] = {}
    for layer, current in present.items():
        new = np.full((y1 - y0, x1 - x0), values[layer], dtype=current.dtype)
        if not np.array_equal(new, current[y0:y1, x0:x1]):
            painted[layer] = new
    if not painted:
        return None
    return x0, y0, painted
