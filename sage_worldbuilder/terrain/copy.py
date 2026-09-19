"""Terrain Copy: selected cells copied onto the map at the cursor, flipped and turned, as
WorldBuilder's Terrain Copy Tool does (PHASE3.md, 3.6 Terrain copy).

A selection is a set of cells, `[cell_y, cell_x]` like the terrain layers, with a bounding box
whose right and top edges are exclusive (`MapCellSelection`, `0x00530CC0`). A paste moves the
selection's centre to the cursor cell after flipping and quarter-turning it
(`MapCellCoordTransformation`, `0x00612D00`, built at `0x00612C30`), and maps each cell and height
sample near the cursor back to the one it copies (`0x0052F6B0` and `0x0052F880`). `copySelection`
(`0x00686C20`) then writes, all read from the terrain as it was before the paste:

- heights (`0x00685CD0`): each sample at a corner of a selected cell;
- texture (`0x00685F60`): each selected cell's texture, tiled anew at its new place with the
  texture's tiling offset, with its blends turned to match (the flips at `0x00686330`, then
  `rotateBlendTileInfo`, `0x00686410`) and their secondary tiles tiled anew too; the cells'
  cliff mappings are left as they were;
- passability (`0x006869C0`): all seven cell attribute layers.

WorldBuilder reads and writes a height sample one past the map's last column through the next
row's first sample; those samples are left out here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from sage_map.assets.blend_tile_data import BlendDescription, BlendTileTexture
from sage_worldbuilder.terrain.blending import DescriptionIndex
from sage_worldbuilder.terrain.cells import CellLayer, Layer, TileLayer
from sage_worldbuilder.terrain.textures import texture_classes, tiling_offset

__all__ = [
    "CopyParts",
    "CopyTransform",
    "TerrainPaste",
    "paste_terrain",
    "selection_bounds",
    "turned_blend",
]

# A cell or sample coordinate is an int or an array of them. The transforms below take it as a type
# parameter rather than a union so that a caller passing arrays gets arrays back: they index with
# what these return.


def _rotate[C: (int, np.ndarray)](x: C, y: C, turns: int) -> tuple[C, C]:
    """A quarter turn is `(x, y) -> (y, -x)`, clockwise with y up."""
    turns %= 4
    if turns == 1:
        return y, -x
    if turns == 2:
        return -x, -y
    if turns == 3:
        return -y, x
    return x, y


@dataclass(frozen=True)
class CopyParts:
    """What a paste copies: Copy Terrain Options' Terrain height, Terrain texture and
    Passability."""

    heights: bool = True
    texture: bool = True
    passability: bool = True


@dataclass(frozen=True)
class CopyTransform:
    """Where a selection lands: its cells offset by `origin`, flipped, turned `turns` quarter
    turns and offset by `destination`."""

    origin: tuple[int, int]
    destination: tuple[int, int]
    turns: int = 0
    flip_vertically: bool = False
    flip_horizontally: bool = False

    @classmethod
    def centred(
        cls,
        bounds: tuple[int, int, int, int],
        destination: tuple[int, int],
        turns: int = 0,
        flip_vertically: bool = False,
        flip_horizontally: bool = False,
    ) -> CopyTransform:
        """The transform that puts the centre of `bounds` (`x0, y0, x1, y1`) on `destination`."""
        x0, y0, x1, y1 = bounds
        origin = (-((x0 + x1) // 2), -((y0 + y1) // 2))
        return cls(origin, destination, turns % 4, flip_vertically, flip_horizontally)

    def forward[C: (int, np.ndarray)](self, x: C, y: C) -> tuple[C, C]:
        px, py = x + self.origin[0], y + self.origin[1]
        if self.flip_vertically:
            py = -py
        if self.flip_horizontally:
            px = -px
        px, py = _rotate(px, py, self.turns)
        return px + self.destination[0], py + self.destination[1]

    def cell_source[C: (int, np.ndarray)](self, x: C, y: C) -> tuple[C, C]:
        """The cell a cell shows after the paste, worked out from cell centres."""
        px = 2 * x + 1 - 2 * self.destination[0]
        py = 2 * y + 1 - 2 * self.destination[1]
        px, py = _rotate(px, py, -self.turns)
        if self.flip_horizontally:
            px = -px
        if self.flip_vertically:
            py = -py
        return (px - 2 * self.origin[0]) >> 1, (py - 2 * self.origin[1]) >> 1

    def sample_source[C: (int, np.ndarray)](self, x: C, y: C) -> tuple[C, C]:
        """The height sample a sample takes after the paste."""
        px, py = _rotate(x - self.destination[0], y - self.destination[1], -self.turns)
        if self.flip_horizontally:
            px = -px
        if self.flip_vertically:
            py = -py
        return px - self.origin[0], py - self.origin[1]

    def target_bounds(
        self, bounds: tuple[int, int, int, int], shape: tuple[int, int]
    ) -> tuple[int, int, int, int]:
        """The cells a paste of `bounds` covers, `x0, y0, x1, y1`, clipped to a map of `shape`."""
        rows, columns = shape
        ax, ay = self.forward(bounds[0], bounds[1])
        bx, by = self.forward(bounds[2], bounds[3])
        return (
            min(max(min(ax, bx), 0), columns),
            min(max(min(ay, by), 0), rows),
            min(max(max(ax, bx), 0), columns),
            min(max(max(ay, by), 0), rows),
        )


def selection_bounds(selection: np.ndarray) -> tuple[int, int, int, int] | None:
    """The bounding box of the selected cells, `x0, y0, x1, y1` with exclusive ends."""
    rows = np.flatnonzero(selection.any(axis=1))
    columns = np.flatnonzero(selection.any(axis=0))
    if not rows.size:
        return None
    return int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1


def _toggled(flags: int) -> int:
    return 0 if flags else 1


def turned_blend(
    description: BlendDescription, turns: int, flip_vertically: bool, flip_horizontally: bool
) -> BlendDescription:
    """A blend flipped and turned with the cells it is on (`0x00686330`, then `0x00686410`).
    Bytes are horizontal, vertical, right diagonal, left diagonal; flags bit 0 is the -1 side.
    A branch that sets the side writes 0 or 1, dropping flags bit 1."""
    h, v, r, left = list(description.raw_blend_direction)
    flags = description.flags
    if flip_vertically and (v or left or r):
        flags = _toggled(flags)
    if flip_horizontally:
        if h:
            flags = _toggled(flags)
        elif left or r:
            r, left = left, r
    turns %= 4
    if turns == 1:
        if h:
            h, v, flags = 0, 1, _toggled(flags)
        elif v:
            h, v = 1, 0
        elif left:
            if not flags:
                left, r = 0, 1
            else:
                flags = 0
        elif r:
            if not flags:
                flags = 1
            else:
                left, r = 1, 0
    elif turns == 2:
        if left or r:
            r, left = left, r
        flags = _toggled(flags)
    elif turns == 3:
        if h:
            h, v = 0, 1
        elif v:
            h, v, flags = 1, 0, _toggled(flags)
        elif left:
            if not flags:
                flags = 1
            else:
                left, r = 0, 1
        elif r:
            if not flags:
                left, r = 1, 0
            else:
                flags = 0
    return replace(description, raw_blend_direction=bytes((h, v, r, left)), flags=flags)


@dataclass
class TerrainPaste:
    """What a paste writes: `(layer or None for the heights, x0, y0, values)` blocks, and the blend
    descriptions to add to the map's list first."""

    patches: list[tuple[Layer | None, int, int, np.ndarray]]
    descriptions: list[BlendDescription] = field(default_factory=list)


def _selected(selection: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    rows, columns = selection.shape
    inside = (xs >= 0) & (xs < columns) & (ys >= 0) & (ys < rows)
    found = np.zeros(xs.shape, dtype=bool)
    found[inside] = selection[ys[inside], xs[inside]]
    return found


def _tiled(
    texture: BlendTileTexture, offset: tuple[int, int], xs: np.ndarray, ys: np.ndarray
) -> np.ndarray:
    size = texture.cell_size
    u, v = xs + offset[0], ys + offset[1]
    cells = (u // 2) % size + ((v // 2) % size) * size + texture.cell_start
    return cells * 4 + (v & 1) * 2 + (u & 1)


def paste_terrain(
    heights: np.ndarray | None,
    layers: Mapping[Layer, np.ndarray | None],
    textures: Sequence[BlendTileTexture],
    descriptions: Sequence[BlendDescription],
    selection: np.ndarray,
    transform: CopyTransform,
    parts: CopyParts,
) -> TerrainPaste | None:
    """The paste of the `selection` (`[cell_y, cell_x]` bools) with `transform`, or None when
    nothing changes."""
    bounds = selection_bounds(selection)
    if bounds is None:
        return None
    rows, columns = selection.shape
    x0, y0, x1, y1 = transform.target_bounds(bounds, selection.shape)
    patches: list[tuple[Layer | None, int, int, np.ndarray]] = []
    index = DescriptionIndex(descriptions)

    if parts.heights and heights is not None and heights.shape == selection.shape:
        hx1, hy1 = min(x1 + 1, columns), min(y1 + 1, rows)
        if x0 < hx1 and y0 < hy1:
            ys, xs = np.mgrid[y0:hy1, x0:hx1]
            sx, sy = transform.sample_source(xs, ys)
            corner = (
                _selected(selection, sx, sy)
                | _selected(selection, sx, sy - 1)
                | _selected(selection, sx - 1, sy)
                | _selected(selection, sx - 1, sy - 1)
            )
            take = corner & (sx >= 0) & (sx < columns) & (sy >= 0) & (sy < rows)
            current = heights[y0:hy1, x0:hx1]
            block = current.copy()
            block[take] = heights[sy[take], sx[take]]
            if not np.array_equal(block, current):
                patches.append((None, x0, y0, block))

    if x0 < x1 and y0 < y1:
        ys, xs = np.mgrid[y0:y1, x0:x1]
        sx, sy = transform.cell_source(xs, ys)
        take = _selected(selection, sx, sy)
        if take.any():
            sources = (sy[take], sx[take])
            targets = (xs[take], ys[take])
            if parts.texture:
                patches += _texture_patches(
                    layers, textures, index, transform, (x0, y0, x1, y1), take, sources, targets
                )
            if parts.passability:
                for layer in CellLayer:
                    values = layers.get(layer)
                    if values is None:
                        continue
                    current = values[y0:y1, x0:x1]
                    block = current.copy()
                    block[take] = values[sources]
                    if not np.array_equal(block, current):
                        patches.append((layer, x0, y0, block))
    if not patches:
        return None
    return TerrainPaste(patches, list(index.added))


def _texture_patches(
    layers: Mapping[Layer, np.ndarray | None],
    textures: Sequence[BlendTileTexture],
    index: DescriptionIndex,
    transform: CopyTransform,
    box: tuple[int, int, int, int],
    take: np.ndarray,
    sources: tuple[np.ndarray, np.ndarray],
    targets: tuple[np.ndarray, np.ndarray],
) -> list[tuple[Layer | None, int, int, np.ndarray]]:
    tiles = layers.get(TileLayer.TILES)
    if tiles is None:
        return []
    x0, y0, x1, y1 = box
    textures = list(textures)
    offsets: dict[int, tuple[int, int]] = {}

    def offset(number: int) -> tuple[int, int]:
        if number not in offsets:
            offsets[number] = tiling_offset(tiles, textures[number])
        return offsets[number]

    def tiled(numbers: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        # A cell of no texture gets tile 0, as `getTileNdxForClass` returns for no class.
        values = np.zeros(len(numbers), dtype=np.int64)
        for number in np.unique(numbers).tolist():
            if number >= 0:
                chosen = numbers == number
                values[chosen] = _tiled(textures[number], offset(number), xs[chosen], ys[chosen])
        return values

    patches: list[tuple[Layer | None, int, int, np.ndarray]] = []
    target_xs, target_ys = targets
    current = tiles[y0:y1, x0:x1]
    block = current.copy()
    block[take] = tiled(texture_classes(tiles[sources], textures), target_xs, target_ys)
    if not np.array_equal(block, current):
        patches.append((TileLayer.TILES, x0, y0, block))

    stored = index.description
    for layer in (TileLayer.BLENDS, TileLayer.THREE_WAY_BLENDS):
        values = layers.get(layer)
        if values is None:
            continue
        numbers = values[sources]
        written = np.zeros(len(numbers), dtype=np.int64)
        turned: dict[int, BlendDescription | None] = {}
        for k in np.flatnonzero(numbers > 0).tolist():
            number = int(numbers[k])
            if number not in turned:
                description = stored(number)
                turned[number] = (
                    turned_blend(
                        description,
                        transform.turns,
                        transform.flip_vertically,
                        transform.flip_horizontally,
                    )
                    if description is not None
                    else None
                )
            description = turned[number]
            if description is None:
                continue
            secondary_class = texture_classes(
                np.array([description.secondary_texture_tile]), textures
            )[0]
            secondary = tiled(
                np.array([secondary_class]), target_xs[k : k + 1], target_ys[k : k + 1]
            )[0]
            written[k] = index.number(replace(description, secondary_texture_tile=int(secondary)))
        current = values[y0:y1, x0:x1]
        block = current.copy()
        block[take] = written
        if not np.array_equal(block, current):
            patches.append((layer, x0, y0, block))
    return patches
