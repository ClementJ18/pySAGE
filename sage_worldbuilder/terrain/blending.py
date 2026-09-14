"""Blending textures: Blend Single Edge, Auto Edge Out and Auto Edge In, as WorldBuilder's
`WorldHeightMapEdit` does them (PHASE3.md, 3.3 Blending).

A blend draws another texture onto a cell, fading in from one side. A cell holds up to two, one
in `BlendTileData.blends` and a 3-way blend in `three_way_blends`, each an index (from 1) into
`blend_descriptions`. A description is WorldBuilder's blend info: the secondary texture's tile at
the blended cell, one-hot direction bytes (horizontal, vertical, right diagonal, left diagonal),
`flags` (bit 0 the blend comes from the -1 side, bit 1 set on an axis blend paired with a certain
corner), `two_sided` (a long diagonal: an inside corner) and `magic_value1` (the custom blend edge
class, -1 for the plain alpha blend written here).

The routines, with their addresses in `worldbuilder.exe`:

- `getTileNdxForClass` (`0x00670100`): a texture's tile at a cell, tiled with the texture's offset
  (`textures.tiling_offset`);
- `blendTile` (`0x006706E0`): the texture of a neighbour (or a given texture) blended onto a cell
  from the neighbour's side, and the blend writer it calls (`0x00670CB0`);
- `blendToThisClass` (`0x00673510`): a texture blended onto a cell from the side, sides or corner
  that show it;
- Auto Edge Out from a cell (`0x006711B0`) or, with Shift, over the whole map (`globalBlendOut`,
  `0x00672D70`); Auto Edge In (`0x00671E30`, `globalBlendIn` `0x006730C0`).

Both Auto Edge tools first absorb: a cell with more than two sides or five neighbours of a texture
becomes that texture (`0x0066E020` counts the neighbours, clamping to the map and passing over
blended cells). The custom blend edge options (`0x022A9744`, `0x022A9745`) are not built; the 3-way
switch at `[0x022CA7D8]+0x44` is taken as on, as the corpus maps' 3-way blends show.
"""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from sage_map.assets.blend_tile_data import BlendDescription, BlendTileTexture
from sage_worldbuilder.terrain.cells import TileLayer
from sage_worldbuilder.terrain.textures import tiling_offset

__all__ = [
    "DEFAULT_EDGE",
    "BlendEdit",
    "DescriptionIndex",
    "auto_edge_in",
    "auto_edge_out",
    "description_side",
    "flood_fill",
    "optimized_blends",
    "single_edge",
]

DEFAULT_EDGE = 0xFFFFFFFF
# A cell with more sides or more neighbours of a texture than these becomes that texture.
_ABSORB_SIDES = 2
_ABSORB_NEIGHBOURS = 5


@dataclass
class BlendEdit:
    """What a blend tool changes: the changed layers over the block from cell `(x0, y0)`, the
    descriptions to add to the map's list first, and a texture to add to its table first."""

    x0: int
    y0: int
    layers: dict[TileLayer, np.ndarray]
    descriptions: list[BlendDescription] = field(default_factory=list)
    texture: BlendTileTexture | None = None


def description_side(description: BlendDescription) -> tuple[int, int] | None:
    """The neighbour `(dx, dy)` a plain alpha blend shows its texture from, or None for a custom
    edge or no single direction. A long diagonal names the corner its texture is in."""
    raw = list(description.raw_blend_direction)
    if description.magic_value1 != DEFAULT_EDGE or sum(raw) != 1 or max(raw) != 1:
        return None
    sign = -1 if description.flags & 1 else 1
    return ((sign, 0), (0, sign), (1, sign), (-1, sign))[raw.index(1)]


class DescriptionIndex:
    """Blend descriptions by content, as WorldBuilder's find-or-add (`0x00670AF0`): an edit
    reuses the first stored description equal to the one it needs, and new ones are collected in
    `added`, numbered after the stored ones."""

    def __init__(self, stored: Sequence[BlendDescription]) -> None:
        self._stored = stored
        self._index: dict[tuple, int] = {}
        for number, description in enumerate(stored, 1):
            self._index.setdefault(_key(description), number)
        self.added: list[BlendDescription] = []

    def number(self, description: BlendDescription) -> int:
        key = _key(description)
        if key not in self._index:
            self.added.append(description)
            self._index[key] = len(self._stored) + len(self.added)
        return self._index[key]

    def description(self, number: int) -> BlendDescription | None:
        if 0 < number <= len(self._stored):
            return self._stored[number - 1]
        if 0 < number - len(self._stored) <= len(self.added):
            return self.added[number - len(self._stored) - 1]
        return None


def _key(description: BlendDescription) -> tuple:
    return (
        description.secondary_texture_tile,
        bytes(description.raw_blend_direction),
        description.flags,
        bool(description.two_sided),
        description.magic_value1,
    )


class _Terrain:
    """The tile and blend layers as flat lists (`y * columns + x`), with the texture each cell
    shows, for WorldBuilder's cell-by-cell routines."""

    def __init__(
        self,
        layers: Mapping[TileLayer, np.ndarray],
        textures: Sequence[BlendTileTexture],
        descriptions: Sequence[BlendDescription],
    ) -> None:
        self._layers = layers
        tiles = layers[TileLayer.TILES]
        self.rows, self.columns = tiles.shape
        self.tiles: list[int] = tiles.ravel().tolist()
        self.blends: list[int] = layers[TileLayer.BLENDS].ravel().tolist()
        self.three_way: list[int] = layers[TileLayer.THREE_WAY_BLENDS].ravel().tolist()
        cliff = layers.get(TileLayer.CLIFF_TEXTURES)
        self.cliff: list[int] | None = cliff.ravel().tolist() if cliff is not None else None
        self.textures = list(textures)
        self.new_texture: BlendTileTexture | None = None
        self._cell_texture: list[int] = []
        for number, texture in enumerate(self.textures):
            self._cover(number, texture)
        self.classes = [self.tile_class(tile) for tile in self.tiles]
        self._offsets: dict[int, tuple[int, int]] = {}
        self.index = DescriptionIndex(descriptions)

    def _cover(self, number: int, texture: BlendTileTexture) -> None:
        end = texture.cell_start + texture.cell_count
        if len(self._cell_texture) < end:
            self._cell_texture.extend([-1] * (end - len(self._cell_texture)))
        self._cell_texture[texture.cell_start : end] = [number] * texture.cell_count

    def add_texture(self, texture: BlendTileTexture) -> int:
        """The number of `texture` in the table, appending it when the map lacks it."""
        for number, entry in enumerate(self.textures):
            if entry is texture or entry.name.lower() == texture.name.lower():
                return number
        self.textures.append(texture)
        self.new_texture = texture
        self._cover(len(self.textures) - 1, texture)
        return len(self.textures) - 1

    def tile_class(self, tile: int) -> int:
        cell = tile >> 2
        return self._cell_texture[cell] if 0 <= cell < len(self._cell_texture) else -1

    def texture_class(self, x: int, y: int, ignore_blend: bool) -> int:
        """`getTextureClass` (`0x0066F3E0`): the texture a cell shows, or -1 for a blended cell
        unless `ignore_blend`."""
        i = y * self.columns + x
        if not ignore_blend and (self.blends[i] or self.three_way[i]):
            return -1
        return self.classes[i]

    def count(self, x: int, y: int, texture: int) -> tuple[int, int]:
        """The sides and all neighbours of a cell that show `texture` (`0x0066E020`)."""
        sides = total = 0
        last_column, last_row = self.columns - 1, self.rows - 1
        for nx in (x - 1, x, x + 1):
            cx = 0 if nx < 0 else last_column if nx > last_column else nx
            for ny in (y - 1, y, y + 1):
                if nx == x and ny == y:
                    continue
                cy = 0 if ny < 0 else last_row if ny > last_row else ny
                if self.texture_class(cx, cy, False) == texture:
                    total += 1
                    if nx == x or ny == y:
                        sides += 1
        return sides, total

    def _absorbs(self, x: int, y: int, texture: int) -> bool:
        sides, total = self.count(x, y, texture)
        return sides > _ABSORB_SIDES or total > _ABSORB_NEIGHBOURS

    def offset(self, texture: int) -> tuple[int, int]:
        if texture not in self._offsets:
            entry = self.textures[texture]
            self._offsets[texture] = (
                (0, 0)
                if entry is self.new_texture
                else tiling_offset(self._layers[TileLayer.TILES], entry)
            )
        return self._offsets[texture]

    def tile_for(self, x: int, y: int, texture: int) -> int:
        entry = self.textures[texture]
        ox, oy = self.offset(texture)
        size = entry.cell_size
        u, v = x + ox, y + oy
        cell = (u // 2) % size + ((v // 2) % size) * size + entry.cell_start
        return cell * 4 + (v & 1) * 2 + (u & 1)

    def set_tile(self, x: int, y: int, texture: int) -> None:
        """`setTileNdx` (`0x0066F010`): the texture's tile, with the cell's blends and cliff
        mapping cleared."""
        i = y * self.columns + x
        self.tiles[i] = self.tile_for(x, y, texture)
        self.classes[i] = texture
        self.blends[i] = self.three_way[i] = 0
        if self.cliff is not None:
            self.cliff[i] = 0

    def _absorb(self, x: int, y: int, texture: int) -> None:
        # The flood routines write the tile and clear only the first blend.
        i = y * self.columns + x
        self.tiles[i] = self.tile_for(x, y, texture)
        self.classes[i] = texture
        self.blends[i] = 0

    def _inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.columns and 0 <= y < self.rows

    def blend_tile(self, x: int, y: int, nx: int, ny: int, texture: int = -1) -> None:
        """`blendTile`: `texture`, or the texture neighbour `(nx, ny)` shows, blended onto
        `(x, y)` from the neighbour's side."""
        if not (self._inside(x, y) and self._inside(nx, ny)):
            return
        i = y * self.columns + x
        if texture < 0:
            texture = self.texture_class(nx, ny, False)
        # A blended neighbour lends its own tile.
        secondary = (
            self.tiles[ny * self.columns + nx] if texture < 0 else self.tile_for(x, y, texture)
        )
        own = self.tiles[i]
        if own == secondary:
            self.blends[i] = self.three_way[i] = 0
        else:
            self.write_blend(x, y, nx, ny, own, secondary, False)

    def write_blend(
        self, x: int, y: int, nx: int, ny: int, own: int, secondary: int, long_diagonal: bool
    ) -> None:
        """The blend writer (`0x00670CB0`): a blend of `secondary` onto `(x, y)` from point
        `(nx, ny)`, into the 3-way slot when the cell has a blend already."""
        i = y * self.columns + x
        existing = self.index.description(self.blends[i]) if self.blends[i] else None
        existing_diagonal = existing_facing = False
        if existing is not None:
            raw = existing.raw_blend_direction
            inverted = existing.flags & 0xFF != 0
            existing_diagonal = bool(raw[2] or raw[3])
            existing_facing = bool((raw[2] and not inverted) or (raw[3] and inverted))
        direction = [0, 0, 0, 0]
        facing = False
        if ny == y:
            direction[0] = 1
            flags = int(nx < x) | (2 if existing is not None and existing_facing else 0)
        elif nx == x:
            direction[1] = 1
            flags = int(ny < y) | (2 if existing is not None and existing_facing else 0)
        else:
            left = nx <= x
            flags = int(ny < y)
            if long_diagonal:
                flags, left = 1 - flags, not left
            direction[3 if left else 2] = 1
            facing = (not left and not flags) or (left and bool(flags))
            if existing is not None and existing_diagonal and existing_facing != facing:
                return
        if existing is not None and existing.secondary_texture_tile == secondary:
            return
        number = self.index.number(
            BlendDescription(
                secondary_texture_tile=secondary,
                raw_blend_direction=bytes(direction),
                flags=flags,
                two_sided=long_diagonal,
                magic_value1=DEFAULT_EDGE,
            )
        )
        self.tiles[i] = own
        if not self.blends[i]:
            self.blends[i] = number
            return
        self.three_way[i] = number
        if facing and not existing_diagonal and existing is not None:
            self.blends[i] = self.index.number(replace(existing, flags=existing.flags | 2))

    def blend_to_class(self, x: int, y: int, texture: int) -> None:
        """`blendToThisClass`: `texture` blended onto `(x, y)` from its one side or corner that
        shows it, or as a long diagonal from two sides."""
        sides, total = self.count(x, y, texture)
        if total <= 0 or sides > 2:
            return
        if sides < 2:
            for nx in (x - 1, x, x + 1):
                for ny in (y - 1, y, y + 1):
                    if sides == 1 and nx != x and ny != y:
                        continue
                    if (nx, ny) == (x, y) or not self._inside(nx, ny):
                        continue
                    if self.texture_class(nx, ny, False) == texture:
                        self.blend_tile(x, y, nx, ny)
                        return
            return
        px, py = x, y
        found = [
            (nx, ny)
            for nx, ny in ((x - 1, y), (x, y - 1), (x, y + 1), (x + 1, y))
            if self._inside(nx, ny) and self.texture_class(nx, ny, False) == texture
        ]
        if (x, y + 1) in found:
            py = y - 1
        if (x, y - 1) in found:
            py += 1
        if (x - 1, y) in found:
            px = x + 1
        if (x + 1, y) in found:
            px -= 1
        i = y * self.columns + x
        self.write_blend(x, y, px, py, self.tiles[i], self.tile_for(x, y, texture), True)

    def _neighbours(self, x: int, y: int):
        """The cells around `(x, y)` on the map, the cell itself included, x before y."""
        for nx in (x - 1, x, x + 1):
            if 0 <= nx < self.columns:
                for ny in (y - 1, y, y + 1):
                    if 0 <= ny < self.rows:
                        yield nx, ny

    def _blended_with(self, i: int, texture: int) -> bool:
        if self.blends[i] <= 0:
            return False
        description = self.index.description(self.blends[i])
        return description is not None and (
            self.tile_class(description.secondary_texture_tile) == texture
        )

    def local_blend_out(self, x: int, y: int) -> None:
        texture = self.texture_class(x, y, False)
        if texture < 0:
            return
        columns = self.columns
        visited = bytearray(self.rows * columns)
        visited[y * columns + x] = 1
        stack = [(x, y)]
        edge: list[tuple[int, int]] = []
        while stack:
            px, py = stack.pop()
            for nx, ny in self._neighbours(px, py):
                j = ny * columns + nx
                if visited[j]:
                    continue
                if self.classes[j] == texture:
                    if self.blends[j] > 0:
                        continue
                elif self._absorbs(nx, ny, texture):
                    self._absorb(nx, ny, texture)
                else:
                    continue
                stack.append((nx, ny))
                visited[j] = 1
            if self.count(px, py, texture)[1] != 8:
                edge.append((px, py))
        visited = bytearray(self.rows * columns)
        while edge:
            px, py = edge.pop()
            for nx, ny in self._neighbours(px, py):
                j = ny * columns + nx
                if visited[j] or self._blended_with(j, texture):
                    continue
                if self.classes[j] != texture:
                    self.blend_to_class(nx, ny, texture)
                visited[j] = 1

    def local_blend_in(self, x: int, y: int) -> None:
        texture = self.texture_class(x, y, False)
        if texture < 0:
            return
        columns = self.columns
        visited = bytearray(self.rows * columns)
        visited[y * columns + x] = 1
        stack = [(x, y)]
        edge: list[tuple[int, int]] = []
        absorbed: dict[int, tuple[int, int, int]] = {}
        while stack:
            px, py = stack.pop()
            for nx, ny in self._neighbours(px, py):
                j = ny * columns + nx
                if visited[j]:
                    continue
                other = self.classes[j]
                if other == texture:
                    if self.blends[j] <= 0:
                        stack.append((nx, ny))
                        visited[j] = 1
                elif other >= 0 and self._absorbs(px, py, other):
                    absorbed[py * columns + px] = (px, py, other)
            if self.count(px, py, texture)[1] != 8:
                edge.append((px, py))
        for key in sorted(absorbed):
            self._absorb(*absorbed[key])
        visited = bytearray(self.rows * columns)
        while edge:
            px, py = edge.pop()
            for nx, ny in self._neighbours(px, py):
                j = ny * columns + nx
                if visited[j] or self._blended_with(j, texture):
                    continue
                other = self.classes[j]
                if other != texture and other >= 0:
                    self.blend_to_class(px, py, other)
                visited[j] = 1

    def _classes_array(self) -> np.ndarray:
        return np.array(self.classes, dtype=np.int32).reshape(self.rows, self.columns)

    def _bordering(self, texture: int) -> list[int]:
        """The cells showing `texture` with a neighbour on the map that shows another, in
        row order."""
        classes = self._classes_array()
        same = classes == texture
        padded = np.pad(same, 1, constant_values=True)
        other = np.zeros(same.shape, dtype=bool)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                other |= ~padded[1 + dy : 1 + dy + self.rows, 1 + dx : 1 + dx + self.columns]
        return np.flatnonzero(same & other).tolist()

    def global_blend_out(self, x: int, y: int) -> None:
        texture = self.texture_class(x, y, False)
        if texture < 0:
            return
        columns = self.columns
        # WorldBuilder sweeps the map until a sweep absorbs nothing. Absorbing only adds cells
        # of the texture, so every order ends with the same cells; this visits only the cells
        # next to one.
        classes = self._classes_array()
        blended = (np.array(self.blends).reshape(classes.shape) != 0) | (
            np.array(self.three_way).reshape(classes.shape) != 0
        )
        shown = np.pad((classes == texture) & ~blended, 1)
        near = np.zeros(classes.shape, dtype=bool)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                near |= shown[1 + dy : 1 + dy + self.rows, 1 + dx : 1 + dx + columns]
        work = np.flatnonzero(near & (classes != texture)).tolist()
        while work:
            i = work.pop()
            cy, cx = divmod(i, columns)
            if self.classes[i] == texture or not self._absorbs(cx, cy, texture):
                continue
            self.set_tile(cx, cy, texture)
            work.extend(ny * columns + nx for nx, ny in self._neighbours(cx, cy))
        for i in self._bordering(texture):
            cy, cx = divmod(i, columns)
            for nx, ny in self._neighbours(cx, cy):
                if (nx, ny) != (cx, cy) and self.classes[ny * columns + nx] != texture:
                    self.blend_to_class(nx, ny, texture)

    def global_blend_in(self, x: int, y: int) -> None:
        texture = self.texture_class(x, y, False)
        if texture < 0:
            return
        columns = self.columns
        # Sweeps in row order until one absorbs nothing. Which texture a cell becomes depends on
        # the order, so each sweep visits, in row order, the cells whose surroundings changed
        # since they were last looked at.
        pending = self._bordering(texture)
        while pending:
            heap = sorted(set(pending))
            later: set[int] = set()
            while heap:
                i = heapq.heappop(heap)
                if heap and heap[0] == i:
                    continue
                if self.classes[i] != texture:
                    continue
                cy, cx = divmod(i, columns)
                for nx, ny in self._neighbours(cx, cy):
                    other = self.classes[ny * columns + nx]
                    if other == texture or other < 0 or not self._absorbs(cx, cy, other):
                        continue
                    self.set_tile(cx, cy, other)
                    for mx, my in self._neighbours(cx, cy):
                        j = my * columns + mx
                        if self.classes[j] == texture:
                            if j > i:
                                heapq.heappush(heap, j)
                            else:
                                later.add(j)
                    break
            pending = sorted(later)
        bordering = self._bordering(texture)
        classes = self._classes_array()
        blends = np.array(self.blends).reshape(classes.shape)
        inner = (classes == texture) & (blends != 0)
        inner.flat[bordering] = False
        for i in np.flatnonzero(inner).tolist():
            self.blends[i] = 0
        for i in bordering:
            cy, cx = divmod(i, columns)
            for nx, ny in self._neighbours(cx, cy):
                other = self.classes[ny * columns + nx]
                if (nx, ny) != (cx, cy) and other != texture and other >= 0:
                    self.blend_to_class(cx, cy, other)

    def flood_texture(self, x: int, y: int, texture: int, replace_all: bool) -> None:
        """Flood Fill (`0x00673B10`): `texture` over the area of the texture at `(x, y)`, or over
        every cell of that texture. A filled cell keeps its blend and loses its 3-way blend and
        cliff mapping; a cell round it whose blend shows the old texture shows the new one. The
        area grows through edge neighbours, never into the map's last row or column."""
        columns, rows = self.columns, self.rows
        old = self.classes[y * columns + x]
        if old < 0 or old == texture:
            return

        def fill(cx: int, cy: int) -> None:
            i = cy * columns + cx
            kept = self.blends[i]
            self.set_tile(cx, cy, texture)
            self.blends[i] = kept

        def retarget(cx: int, cy: int) -> None:
            i = cy * columns + cx
            if not self._blended_with(i, old):
                return
            description = self.index.description(self.blends[i])
            assert description is not None
            secondary = self.tile_for(cx, cy, texture)
            self.blends[i] = self.index.number(
                replace(description, secondary_texture_tile=secondary)
            )
            if self.cliff is not None:
                self.cliff[i] = 0

        if replace_all:
            for cx in range(columns):
                for cy in range(rows):
                    if self.classes[cy * columns + cx] == old:
                        fill(cx, cy)
                    else:
                        retarget(cx, cy)
            return
        stack = [(x, y)]
        while stack:
            px, py = stack.pop()
            fill(px, py)
            for nx in (px - 1, px, px + 1):
                if not 0 <= nx < columns - 1:
                    continue
                for ny in (py - 1, py, py + 1):
                    if not 0 <= ny < rows - 1:
                        continue
                    if self.classes[ny * columns + nx] == old:
                        if nx == px or ny == py:
                            stack.append((nx, ny))
                    else:
                        retarget(nx, ny)

    def edit(self) -> BlendEdit | None:
        """The changed block of every changed layer, or None when nothing changed."""
        shape = (self.rows, self.columns)
        current = {
            TileLayer.TILES: self.tiles,
            TileLayer.BLENDS: self.blends,
            TileLayer.THREE_WAY_BLENDS: self.three_way,
        }
        if self.cliff is not None:
            current[TileLayer.CLIFF_TEXTURES] = self.cliff
        arrays: dict[TileLayer, np.ndarray] = {}
        changed = np.zeros(shape, dtype=bool)
        for layer, values in current.items():
            old = self._layers[layer]
            new = np.array(values, dtype=old.dtype).reshape(shape)
            difference = new != old
            if difference.any():
                arrays[layer] = new
                changed |= difference
        if not arrays:
            return None
        found_rows = np.flatnonzero(changed.any(axis=1))
        found_columns = np.flatnonzero(changed.any(axis=0))
        x0, x1 = int(found_columns[0]), int(found_columns[-1]) + 1
        y0, y1 = int(found_rows[0]), int(found_rows[-1]) + 1
        blocks = {layer: array[y0:y1, x0:x1] for layer, array in arrays.items()}
        return BlendEdit(x0, y0, blocks, list(self.index.added), self.new_texture)


def _layers_with_blends(layers: Mapping[TileLayer, np.ndarray]) -> bool:
    return all(
        layers.get(layer) is not None
        for layer in (TileLayer.TILES, TileLayer.BLENDS, TileLayer.THREE_WAY_BLENDS)
    )


def single_edge(
    layers: Mapping[TileLayer, np.ndarray],
    textures: Sequence[BlendTileTexture],
    descriptions: Sequence[BlendDescription],
    cell: tuple[int, int],
    source: tuple[int, int],
    texture: BlendTileTexture | None = None,
) -> BlendEdit | None:
    """Blend Single Edge: the texture cell `source` shows, or `texture` (the right button's
    foreground texture, added to the table when the map lacks it), blended onto `cell` from the
    side `source` is on. Both are `(x, y)`; None when nothing changes."""
    if cell == source or not _layers_with_blends(layers):
        return None
    terrain = _Terrain(layers, textures, descriptions)
    number = terrain.add_texture(texture) if texture is not None else -1
    terrain.blend_tile(*cell, *source, number)
    return terrain.edit()


def auto_edge_out(
    layers: Mapping[TileLayer, np.ndarray],
    textures: Sequence[BlendTileTexture],
    descriptions: Sequence[BlendDescription],
    cell: tuple[int, int],
    *,
    whole_map: bool = False,
) -> BlendEdit | None:
    """Auto Edge Out at `cell` (`x, y`): the texture there spreads over the cells it nearly
    surrounds, then blends onto every cell around its area (the area joined to the cell, or every
    area of it with `whole_map`, Shift). None when the cell is blended or nothing changes."""
    return _auto_edge(layers, textures, descriptions, cell, outward=True, whole_map=whole_map)


def auto_edge_in(
    layers: Mapping[TileLayer, np.ndarray],
    textures: Sequence[BlendTileTexture],
    descriptions: Sequence[BlendDescription],
    cell: tuple[int, int],
    *,
    whole_map: bool = False,
) -> BlendEdit | None:
    """Auto Edge In at `cell` (`x, y`): the area's cells nearly surrounded by another texture
    become it, then the textures around the area blend onto its edge cells."""
    return _auto_edge(layers, textures, descriptions, cell, outward=False, whole_map=whole_map)


def flood_fill(
    layers: Mapping[TileLayer, np.ndarray],
    textures: Sequence[BlendTileTexture],
    descriptions: Sequence[BlendDescription],
    cell: tuple[int, int],
    texture: BlendTileTexture,
    *,
    replace_all: bool = False,
) -> BlendEdit | None:
    """Flood Fill at `cell` (`x, y`) with `texture` (added to the table when the map lacks it),
    over the area there or, with `replace_all`, every cell of its texture. None when nothing
    changes."""
    if not _layers_with_blends(layers):
        return None
    rows, columns = layers[TileLayer.TILES].shape
    x, y = cell
    if not (0 <= x < columns and 0 <= y < rows):
        return None
    terrain = _Terrain(layers, textures, descriptions)
    terrain.flood_texture(x, y, terrain.add_texture(texture), replace_all)
    return terrain.edit()


def _auto_edge(
    layers: Mapping[TileLayer, np.ndarray],
    textures: Sequence[BlendTileTexture],
    descriptions: Sequence[BlendDescription],
    cell: tuple[int, int],
    *,
    outward: bool,
    whole_map: bool,
) -> BlendEdit | None:
    if not _layers_with_blends(layers):
        return None
    rows, columns = layers[TileLayer.TILES].shape
    x, y = cell
    if not (0 <= x < columns and 0 <= y < rows):
        return None
    terrain = _Terrain(layers, textures, descriptions)
    if outward:
        (terrain.global_blend_out if whole_map else terrain.local_blend_out)(x, y)
    else:
        (terrain.global_blend_in if whole_map else terrain.local_blend_in)(x, y)
    return terrain.edit()


def optimized_blends(
    descriptions: Sequence[BlendDescription], blends: np.ndarray, three_way: np.ndarray
) -> tuple[list[BlendDescription], np.ndarray, np.ndarray]:
    """The descriptions the layers use, each once and in first-use order of the stored list, with
    both layers renumbered to match. WorldBuilder's Optimize tiles and blend tiles (`0x00675C10`)
    also re-tiles the map and compacts its texture table, which this does not."""
    used = sorted(set(np.unique(blends).tolist()) | set(np.unique(three_way).tolist()) - {0})
    renumber = np.zeros(len(descriptions) + 1, dtype=np.int64)
    kept: list[BlendDescription] = []
    by_key: dict[tuple, int] = {}
    for number in used:
        if not 0 < number <= len(descriptions):
            continue
        description = descriptions[number - 1]
        key = _key(description)
        if key not in by_key:
            kept.append(description)
            by_key[key] = len(kept)
        renumber[number] = by_key[key]
    valid_blends = np.where(blends <= len(descriptions), blends, 0)
    valid_three = np.where(three_way <= len(descriptions), three_way, 0)
    return kept, renumber[valid_blends], renumber[valid_three]
