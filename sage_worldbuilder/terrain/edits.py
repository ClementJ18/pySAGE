"""Undoable terrain edits.

A brush stroke is many small patches. Each patch is its own command, and the patches of one stroke
merge into a single undo entry until the tool closes it when the button comes up. Only the
rectangles a stroke touched are kept, so undoing it restores those cells and nothing else.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from sage_map.assets.blend_tile_data import BlendDescription, BlendTileTexture
from sage_worldbuilder.changes import Change, ChangeKind, Region
from sage_worldbuilder.commands import Command
from sage_worldbuilder.terrain.cells import CellLayer, Layer, TileLayer

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "CopyTerrain",
    "PaintBlends",
    "PaintTiles",
    "PatchCells",
    "PatchHeights",
    "RenameTexture",
    "ReplaceBlendDescriptions",
    "ReplaceTerrainTables",
]


@dataclass
class _Patch:
    # None for the heights, else the cell attribute, tile or blend layer.
    layer: Layer | None
    x0: int
    y0: int
    after: np.ndarray
    before: np.ndarray | None = None

    @property
    def region(self) -> Region:
        rows, columns = self.after.shape
        return Region(self.x0, self.y0, self.x0 + columns, self.y0 + rows)


class _StrokeCommand(Command):
    """Rectangles written into the terrain, merging with the next command of the same class
    until `closed` is set."""

    def __init__(self, patches: list[_Patch], label: str) -> None:
        self.label = label
        self.closed = False
        self._patches = patches

    def _current(self, document: MapDocument, layer: Layer | None) -> np.ndarray:
        if layer is None:
            grid = document.terrain
            if grid is None:
                raise ValueError("the map has no heightmap")
            return grid.heights
        values = document.cells(layer)
        if values is None:
            raise ValueError(f"the map has no {layer.value} layer")
        return values

    def _write(self, document: MapDocument, patch: _Patch, values: np.ndarray) -> None:
        if patch.layer is None:
            document.write_heights(patch.x0, patch.y0, values)
        else:
            document.write_cells(patch.layer, patch.x0, patch.y0, values)

    def do(self, document: MapDocument) -> None:
        for patch in self._patches:
            if patch.before is None:
                rows, columns = patch.after.shape
                current = self._current(document, patch.layer)
                patch.before = current[
                    patch.y0 : patch.y0 + rows, patch.x0 : patch.x0 + columns
                ].copy()
            self._write(document, patch, patch.after)

    def undo(self, document: MapDocument) -> None:
        for patch in reversed(self._patches):
            assert patch.before is not None
            self._write(document, patch, patch.before)

    def changes(self) -> tuple[Change, ...]:
        region = self._patches[0].region
        for patch in self._patches[1:]:
            region = region.union(patch.region)
        return (Change(ChangeKind.TERRAIN, region),)

    def merge(self, following: Command) -> bool:
        if self.closed or type(following) is not type(self):
            return False
        assert isinstance(following, _StrokeCommand)
        self._patches.extend(following._patches)
        return True


class PatchHeights(_StrokeCommand):
    """Set a rectangle of heights, `values[row, column]` from sample `(x0, y0)` counted from the
    bottom-left."""

    def __init__(self, x0: int, y0: int, values: np.ndarray, label: str = "Edit Height") -> None:
        super().__init__([_Patch(None, x0, y0, np.array(values, dtype=np.uint16))], label)


class PatchCells(_StrokeCommand):
    """Set a rectangle of cells in one or more attribute layers at once (Passability writes
    three), `values[row, column]` from cell `(x0, y0)`."""

    def __init__(
        self,
        x0: int,
        y0: int,
        layers: Mapping[CellLayer, np.ndarray],
        label: str = "Paint Cells",
    ) -> None:
        patches = [_Patch(layer, x0, y0, np.array(values)) for layer, values in layers.items()]
        if not patches:
            raise ValueError("nothing to paint")
        super().__init__(patches, label)


def _add_texture(document: MapDocument, texture: BlendTileTexture | None) -> None:
    blend = document.map.blend_tile_data
    if blend is not None and texture is not None:
        if not any(entry is texture for entry in blend.textures):
            blend.textures.append(texture)
            blend.texture_cell_count += texture.cell_count


def _remove_texture(document: MapDocument, texture: BlendTileTexture | None) -> None:
    blend = document.map.blend_tile_data
    if blend is not None and texture is not None:
        for index, entry in enumerate(blend.textures):
            if entry is texture:
                del blend.textures[index]
                blend.texture_cell_count -= texture.cell_count
                break


class PaintTiles(_StrokeCommand):
    """Paint texture tiles: the tile layer and the blend layers a paint clears, from cell
    `(x0, y0)`. `texture`, when given, is a table entry the map does not have yet: it is added
    before the tiles that use it are written, and taken out again on undo."""

    def __init__(
        self,
        x0: int,
        y0: int,
        layers: Mapping[TileLayer, np.ndarray],
        texture: BlendTileTexture | None = None,
        label: str = "Paint Texture",
    ) -> None:
        patches = [_Patch(layer, x0, y0, np.array(values)) for layer, values in layers.items()]
        if not patches:
            raise ValueError("nothing to paint")
        super().__init__(patches, label)
        self._texture = texture

    def do(self, document: MapDocument) -> None:
        _add_texture(document, self._texture)
        super().do(document)

    def undo(self, document: MapDocument) -> None:
        super().undo(document)
        _remove_texture(document, self._texture)

    def merge(self, following: Command) -> bool:
        # A stroke that brings in another new texture stays its own entry.
        if isinstance(following, PaintTiles) and following._texture is not None:
            return False
        return super().merge(following)


class PaintBlends(_StrokeCommand):
    """Write the tile and blend layers from cell `(x0, y0)`, adding `descriptions` (blend
    descriptions the map does not have yet, numbered after its own) and `texture` (a table entry
    it lacks) before the layers that use them, and taking them out again on undo."""

    def __init__(
        self,
        x0: int,
        y0: int,
        layers: Mapping[TileLayer, np.ndarray],
        descriptions: Sequence[BlendDescription] = (),
        label: str = "Blend",
        texture: BlendTileTexture | None = None,
    ) -> None:
        patches = [_Patch(layer, x0, y0, np.array(values)) for layer, values in layers.items()]
        if not patches:
            raise ValueError("nothing to blend")
        super().__init__(patches, label)
        self._descriptions = list(descriptions)
        self._texture = texture

    def do(self, document: MapDocument) -> None:
        _add_texture(document, self._texture)
        blend = document.map.blend_tile_data
        if blend is not None and self._descriptions:
            stored = blend.blend_descriptions
            if not any(entry is self._descriptions[0] for entry in stored):
                stored.extend(self._descriptions)
        super().do(document)

    def undo(self, document: MapDocument) -> None:
        super().undo(document)
        blend = document.map.blend_tile_data
        if blend is not None and self._descriptions:
            added = {id(entry) for entry in self._descriptions}
            blend.blend_descriptions[:] = [
                entry for entry in blend.blend_descriptions if id(entry) not in added
            ]
        _remove_texture(document, self._texture)

    def merge(self, following: Command) -> bool:
        # A command that brings its own new descriptions or texture stays its own entry.
        if isinstance(following, PaintBlends) and (
            following._descriptions or following._texture is not None
        ):
            return False
        return super().merge(following)


class CopyTerrain(PaintBlends):
    """Terrain Copy's paste: blocks of heights (layer None), tile, blend and cell attribute layers,
    each from its own cell `(x0, y0)`, adding `descriptions` first."""

    def __init__(
        self,
        patches: Sequence[tuple[Layer | None, int, int, np.ndarray]],
        descriptions: Sequence[BlendDescription] = (),
        label: str = "Copy Terrain",
    ) -> None:
        built = [
            _Patch(layer, x0, y0, np.array(values, dtype=np.uint16) if layer is None else values)
            for layer, x0, y0, values in patches
        ]
        if not built:
            raise ValueError("nothing to paste")
        _StrokeCommand.__init__(self, built, label)
        self._descriptions = list(descriptions)
        self._texture = None


class ReplaceTerrainTables(_StrokeCommand):
    """A whole-map texture edit (Optimize tiles and blend tiles, Remove Cliff Tex Mapping, Remove
    all texture blends): blocks of tile layers, and new texture, blend description and cliff
    mapping tables, each None to keep the map's."""

    def __init__(
        self,
        patches: Sequence[tuple[TileLayer, int, int, np.ndarray]],
        textures: Sequence[BlendTileTexture] | None = None,
        descriptions: Sequence[BlendDescription] | None = None,
        cliff_mappings: Sequence[object] | None = None,
        label: str = "Edit Textures",
    ) -> None:
        built = [_Patch(layer, x0, y0, np.array(values)) for layer, x0, y0, values in patches]
        super().__init__(built, label)
        self._tables: dict[str, list | None] = {
            "textures": list(textures) if textures is not None else None,
            "blend_descriptions": list(descriptions) if descriptions is not None else None,
            "cliff_texture_mappings": list(cliff_mappings) if cliff_mappings is not None else None,
        }
        self._old: dict[str, list] = {}
        self._old_cell_count: int | None = None

    def do(self, document: MapDocument) -> None:
        blend = document.map.blend_tile_data
        if blend is None:
            raise ValueError("the map has no blend tile data")
        for name, new in self._tables.items():
            if new is not None:
                stored = getattr(blend, name)
                self._old[name] = list(stored)
                stored[:] = new
        textures = self._tables["textures"]
        if textures is not None:
            self._old_cell_count = blend.texture_cell_count
            blend.texture_cell_count = sum(texture.cell_count for texture in textures)
        super().do(document)

    def undo(self, document: MapDocument) -> None:
        super().undo(document)
        blend = document.map.blend_tile_data
        if blend is None:
            return
        for name, old in self._old.items():
            getattr(blend, name)[:] = old
        if self._old_cell_count is not None:
            blend.texture_cell_count = self._old_cell_count

    def changes(self) -> tuple[Change, ...]:
        return (Change(ChangeKind.TERRAIN),)

    def merge(self, following: Command) -> bool:
        return False


class RenameTexture(Command):
    """Give the map's texture `index` another Terrain.ini name, keeping its cells (Flood Fill's
    replace-all with a texture of the same size the map lacks)."""

    def __init__(self, index: int, name: str, label: str = "Flood Fill") -> None:
        self.label = label
        self._index = index
        self._name = name
        self._old: str | None = None

    def do(self, document: MapDocument) -> None:
        blend = document.map.blend_tile_data
        if blend is None:
            raise ValueError("the map has no blend tile data")
        entry = blend.textures[self._index]
        self._old = entry.name
        entry.name = self._name

    def undo(self, document: MapDocument) -> None:
        blend = document.map.blend_tile_data
        if blend is not None and self._old is not None:
            blend.textures[self._index].name = self._old

    def changes(self) -> tuple[Change, ...]:
        return (Change(ChangeKind.TERRAIN),)


class ReplaceBlendDescriptions(Command):
    """Swap the map's blend description list for `descriptions` (Optimize tiles and blend
    tiles, together with the renumbered layers)."""

    label = "Optimize Blend Tiles"

    def __init__(self, descriptions: Sequence[BlendDescription]) -> None:
        self._new = list(descriptions)
        self._old: list[BlendDescription] | None = None

    def do(self, document: MapDocument) -> None:
        blend = document.map.blend_tile_data
        if blend is None:
            raise ValueError("the map has no blend tile data")
        self._old = list(blend.blend_descriptions)
        blend.blend_descriptions[:] = self._new

    def undo(self, document: MapDocument) -> None:
        blend = document.map.blend_tile_data
        if blend is not None and self._old is not None:
            blend.blend_descriptions[:] = self._old

    def changes(self) -> tuple[Change, ...]:
        return (Change(ChangeKind.TERRAIN),)
