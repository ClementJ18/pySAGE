"""The map view's terrain tools: Height Brush, Mound, Dig and Smooth Height, and Single Tile and
Large Tile.

A tool applies its brush where the button goes down and again as the cursor moves, as one undo
entry per stroke. Height Brush, Mound and Dig apply once each time the brush moves to a new
centre, so holding still does not keep piling up height; Smooth Height applies on every movement,
because smoothing is meant to be scrubbed. The brush outline follows the cursor: the full-strength
core, and the feather ring around it.

Single Tile and Large Tile paint what the Terrain Material panel's painting mode says, one cell or
a square the brush width across: the chosen texture, or a cell attribute (passability, passage
width, taintability, flammability, visibility). Flood Fill paints the texture over the area of
one texture, or Shift replaces that texture everywhere; the Eyedropper, or Alt with any of the
texture tools, picks the texture under the cursor.

Blend Single Edge blends the texture of the cell a drag starts on onto the cell it ends on, or with
the right button the chosen texture; Auto Edge Out and In edge the texture area clicked, or with
Shift every area of that texture.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from sage_map.assets.blend_tile_data import BlendTileData, BlendTileTexture
from sage_worldbuilder.brush_options import BrushOptions, PaintMode, PaintOptions
from sage_worldbuilder.terrain import WORLD_UNITS_PER_CELL
from sage_worldbuilder.terrain.blending import (
    BlendEdit,
    auto_edge_in,
    auto_edge_out,
    flood_fill,
    single_edge,
)
from sage_worldbuilder.terrain.brushes import BrushKind, apply_brush, brush_center
from sage_worldbuilder.terrain.cells import TileLayer, paint_cells, paint_values, square_block
from sage_worldbuilder.terrain.edits import (
    PaintBlends,
    PaintTiles,
    PatchCells,
    PatchHeights,
    RenameTexture,
)
from sage_worldbuilder.terrain.textures import (
    TextureCapacityError,
    paint_texture_block,
    planned_texture,
    texture_classes,
    texture_index,
    tiling_offset,
)
from sage_worldbuilder.ui.tools import EditHost, Gesture, Tool, ToolView

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "AutoEdgeTool",
    "BlendSingleEdgeTool",
    "BrushHost",
    "EyedropperTool",
    "FloodFillTool",
    "HeightBrushTool",
    "PaintHost",
    "TilePaintTool",
]

CHOOSE_TEXTURE = "Choose a texture in the Terrain Material panel."

_CORE = QColor(255, 255, 255, 220)
_FEATHER = QColor(255, 255, 255, 110)


class BrushHost(EditHost, Protocol):
    def brush_options(self) -> BrushOptions: ...


class PaintHost(BrushHost, Protocol):
    def paint_options(self) -> PaintOptions: ...

    def texture_cell_size(self, name: str) -> int:
        """The width, in 64-pixel texture cells, of a texture the map does not have yet."""
        ...

    def pick_texture(self, name: str) -> None:
        """Make `name` the texture Texture mode paints (the Eyedropper)."""
        ...

    def show_status(self, text: str) -> None: ...

    def confirm_replace_all(self, name: str) -> bool:
        """Ask before Flood Fill replaces every cell of the texture `name`."""
        ...


class HeightBrushTool(Tool):
    def __init__(self, host: BrushHost, kind: BrushKind) -> None:
        self.host = host
        self.kind = kind
        # The brush centre under the cursor, in fractional samples, for the outline.
        self.center: tuple[float, float] | None = None
        self._stroke: list[PatchHeights] = []
        self._last_center: tuple[float, float] | None = None
        self._last_cell: tuple[float, float] | None = None
        self._active = False

    def _locate(self, view: ToolView, gesture: Gesture) -> tuple[float, float] | None:
        document = view.document
        grid = document.terrain if document is not None else None
        if grid is None:
            return None
        return grid.world_to_cell(*gesture.world)

    def _apply(self, view: ToolView, cell: tuple[float, float]) -> None:
        document = view.document
        grid = document.terrain if document is not None else None
        if grid is None:
            return
        patch = apply_brush(grid.heights, self.kind, cell, self.host.brush_options())
        if patch is None:
            return
        command = PatchHeights(patch.x0, patch.y0, patch.values, self.kind.value)
        self._stroke.append(command)
        self.host.execute(command)

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        cell = self._locate(view, gesture)
        if cell is None:
            return False
        self._active = True
        width = self.host.brush_options().width
        self._last_center = self.center = brush_center(cell[0], cell[1], width)
        self._last_cell = cell
        self._apply(view, cell)
        view.update()
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        cell = self._locate(view, gesture)
        if not self._active or cell is None:
            return False
        width = self.host.brush_options().width
        start = self._last_cell if self._last_cell is not None else cell
        for point in _stroke_points(start, cell, 1.0):
            center = brush_center(point[0], point[1], width)
            if self.kind is BrushKind.SMOOTH or center != self._last_center:
                self._last_center = center
                self._apply(view, point)
        self._last_cell = cell
        self.center = brush_center(cell[0], cell[1], width)
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        if not self._active:
            return False
        self._end_stroke()
        return True

    def hover(self, view: ToolView, gesture: Gesture) -> None:
        cell = self._locate(view, gesture)
        width = self.host.brush_options().width
        self.center = brush_center(cell[0], cell[1], width) if cell is not None else None
        view.update()

    def cancel(self) -> None:
        self._end_stroke()
        self.center = None

    def _end_stroke(self) -> None:
        """Close the stroke's commands, so the next stroke is its own undo entry."""
        for command in self._stroke:
            command.closed = True
        self._stroke = []
        self._last_center = None
        self._last_cell = None
        self._active = False

    def paint(self, view: ToolView, painter: QPainter) -> None:
        document = view.document
        grid = document.terrain if document is not None else None
        if self.center is None or grid is None:
            return
        options = self.host.brush_options()
        x, y = grid.cell_to_world(*self.center)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_CORE, 1.5))
        view.world_circle(painter, x, y, options.width / 2 * WORLD_UNITS_PER_CELL)
        if options.feather:
            outer = (options.width / 2 + options.feather) * WORLD_UNITS_PER_CELL
            painter.setPen(QPen(_FEATHER, 1, Qt.PenStyle.DashLine))
            view.world_circle(painter, x, y, outer)


class TilePaintTool(Tool):
    """Single Tile (one cell) or Large Tile (a square the brush width across)."""

    def __init__(self, host: PaintHost, *, large: bool) -> None:
        self.host = host
        self.large = large
        self.cell: tuple[float, float] | None = None
        self._stroke: list[PatchCells | PaintTiles] = []
        self._last_block: tuple[int, int, int, int] | None = None
        self._last_cell: tuple[float, float] | None = None
        self._active = False
        # Each texture's tiling offset, found once per stroke.
        self._offsets: dict[str, tuple[int, int]] = {}

    @property
    def width(self) -> int:
        return self.host.brush_options().width if self.large else 1

    def _locate(self, view: ToolView, gesture: Gesture) -> tuple[float, float] | None:
        document = view.document
        grid = document.terrain if document is not None else None
        return grid.world_to_cell(*gesture.world) if grid is not None else None

    def _apply(self, view: ToolView, cell: tuple[float, float]) -> None:
        document = view.document
        if document is None:
            return
        options = self.host.paint_options()
        if options.mode is PaintMode.TEXTURE:
            self._apply_texture(view, cell, options.texture)
            return
        values = paint_values(options)
        layers = {layer: document.cells(layer) for layer in values}
        painted = paint_cells(layers, cell, self.width, values)  # type: ignore[arg-type]
        if painted is None:
            return
        x0, y0, blocks = painted
        command: PatchCells | PaintTiles = PatchCells(x0, y0, blocks, f"Paint {options.mode.value}")
        self._stroke.append(command)
        self.host.execute(command)

    def _apply_texture(self, view: ToolView, cell: tuple[float, float], name: str) -> None:
        document = view.document
        blend = document.map.blend_tile_data if document is not None else None
        if document is None or blend is None:
            return
        found = _texture_entry(self.host, blend, name)
        tiles = document.cells(TileLayer.TILES)
        if found is None or tiles is None:
            return
        entry, new = found
        block = square_block(cell, self.width, tiles.shape)
        if block is None:
            return
        key = name.lower()
        if key not in self._offsets:
            self._offsets[key] = (0, 0) if new is not None else tiling_offset(tiles, entry)
        layers = {layer: document.cells(layer) for layer in TileLayer}
        painted = paint_texture_block(
            layers,  # type: ignore[arg-type]
            block,
            entry,
            offset=self._offsets[key],
        )
        if painted is None:
            return
        command = PaintTiles(block[0], block[1], painted, new, "Paint Texture")
        self._stroke.append(command)
        self.host.execute(command)

    def _block(self, view: ToolView, cell: tuple[float, float]) -> tuple[int, int, int, int] | None:
        grid = view.document.terrain if view.document is not None else None
        return square_block(cell, self.width, grid.heights.shape) if grid is not None else None

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        cell = self._locate(view, gesture)
        if cell is None:
            return False
        if gesture.alt:
            _pick_texture_at(self.host, view, gesture)
            return True
        options = self.host.paint_options()
        if options.mode is PaintMode.TEXTURE:
            if not options.texture:
                self.host.show_status(CHOOSE_TEXTURE)
                return False
        elif not paint_values(options):
            return False
        self._active = True
        self.cell = self._last_cell = cell
        self._last_block = self._block(view, cell)
        self._apply(view, cell)
        view.update()
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        cell = self._locate(view, gesture)
        if not self._active or cell is None:
            return False
        start = self._last_cell if self._last_cell is not None else cell
        # Half the block apart, so consecutive blocks overlap and a fast stroke leaves no gap.
        for point in _stroke_points(start, cell, max(1.0, self.width / 2)):
            block = self._block(view, point)
            if block != self._last_block:
                self._last_block = block
                self._apply(view, point)
        self.cell = self._last_cell = cell
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        if not self._active:
            return False
        self._end_stroke()
        return True

    def hover(self, view: ToolView, gesture: Gesture) -> None:
        self.cell = self._locate(view, gesture)
        view.update()

    def cancel(self) -> None:
        self._end_stroke()
        self.cell = None

    def _end_stroke(self) -> None:
        for command in self._stroke:
            command.closed = True
        self._stroke = []
        self._last_block = None
        self._last_cell = None
        self._active = False
        self._offsets = {}

    def paint(self, view: ToolView, painter: QPainter) -> None:
        document = view.document
        grid = document.terrain if document is not None else None
        if self.cell is None or grid is None:
            return
        block = square_block(self.cell, self.width, grid.heights.shape)
        if block is None:
            return
        x0, y0, x1, y1 = block
        left, bottom = grid.cell_to_world(x0 - 0.5, y0 - 0.5)
        right, top = grid.cell_to_world(x1 - 0.5, y1 - 0.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_CORE, 1.5))
        view.world_polygon(painter, [(left, bottom), (right, bottom), (right, top), (left, top)])


def _stroke_points(
    start: tuple[float, float], end: tuple[float, float], spacing: float
) -> list[tuple[float, float]]:
    """The points from just past `start` up to `end`, no more than `spacing` cells apart, so a
    mouse that jumps several cells between two events still paints the cells in between."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    steps = max(1, math.ceil(math.hypot(dx, dy) / spacing))
    return [(start[0] + dx * i / steps, start[1] + dy * i / steps) for i in range(1, steps + 1)]


class FloodFillTool(Tool):
    """Flood Fill: click to paint the chosen texture over the area of the texture under the
    cursor that joins the clicked cell; Shift-click replaces that texture everywhere, once
    confirmed; Alt-click picks the texture under the cursor."""

    def __init__(self, host: PaintHost) -> None:
        self.host = host

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        grid = document.terrain if document is not None else None
        blend = document.map.blend_tile_data if document is not None else None
        if document is None or grid is None or blend is None:
            return False
        if gesture.alt:
            _pick_texture_at(self.host, view, gesture)
            return True
        name = self.host.paint_options().texture
        cell = grid.nearest_cell(*gesture.world)
        if cell is None:
            return False
        if not name:
            self.host.show_status(CHOOSE_TEXTURE)
            return True
        if gesture.shift:
            under = _texture_name_at(document, blend, cell)
            if under is None or not self.host.confirm_replace_all(under):
                return True
        found = _texture_entry(self.host, blend, name)
        if found is None:
            return True
        entry, new = found
        layers = {layer: document.cells(layer) for layer in TileLayer}
        tiles = layers[TileLayer.TILES]
        if tiles is None:
            return True
        if gesture.shift and new is not None:
            # A texture the map lacks takes over the replaced texture's table entry, when it is
            # the same size, so every cell and blend keeps its tile.
            column, row = cell
            under = texture_classes(tiles[row : row + 1, column : column + 1], blend.textures)
            number = int(under[0, 0])
            if number >= 0 and blend.textures[number].cell_size == new.cell_size:
                self.host.execute(RenameTexture(number, new.name))
                return True
        edit = flood_fill(
            layers,  # type: ignore[arg-type]
            blend.textures,
            blend.blend_descriptions,
            cell,
            entry,
            replace_all=gesture.shift,
        )
        _execute_blend(self.host, edit, "Flood Fill")
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        return True


class EyedropperTool(Tool):
    """Eyedropper: click to make the texture under the cursor the one Texture mode paints."""

    def __init__(self, host: PaintHost) -> None:
        self.host = host

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        if view.document is None:
            return False
        _pick_texture_at(self.host, view, gesture)
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        return True


class BlendSingleEdgeTool(Tool):
    """Blend Single Edge: drag from one cell onto another to blend the first cell's texture onto
    the second from that side; drag with the right button to blend the chosen texture instead."""

    right_button = True

    def __init__(self, host: PaintHost) -> None:
        self.host = host
        self.source: tuple[int, int] | None = None
        self.target: tuple[int, int] | None = None
        self._right = False

    def _cell(self, view: ToolView, gesture: Gesture) -> tuple[int, int] | None:
        document = view.document
        grid = document.terrain if document is not None else None
        return grid.nearest_cell(*gesture.world) if grid is not None else None

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        cell = self._cell(view, gesture)
        if cell is None:
            return False
        if gesture.alt and not gesture.right:
            _pick_texture_at(self.host, view, gesture)
            return True
        self.source = self.target = cell
        self._right = gesture.right
        view.update()
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        if self.source is None:
            return False
        cell = self._cell(view, gesture)
        if cell is not None:
            self.target = cell
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        source, self.source = self.source, None
        if source is None:
            return False
        cell = self._cell(view, gesture) or self.target
        self.target = None
        view.update()
        document = view.document
        blend = document.map.blend_tile_data if document is not None else None
        if document is None or blend is None or cell is None or cell == source:
            return True
        texture = None
        if self._right:
            name = self.host.paint_options().texture
            if not name:
                self.host.show_status(CHOOSE_TEXTURE)
                return True
            found = _texture_entry(self.host, blend, name)
            if found is None:
                return True
            texture = found[0]
        layers = _tile_layers(document)
        if layers is None:
            return True
        edit = single_edge(layers, blend.textures, blend.blend_descriptions, cell, source, texture)
        _execute_blend(self.host, edit, "Blend Single Edge")
        return True

    def cancel(self) -> None:
        self.source = self.target = None

    def paint(self, view: ToolView, painter: QPainter) -> None:
        document = view.document
        grid = document.terrain if document is not None else None
        if self.source is None or self.target is None or grid is None:
            return
        start = grid.cell_to_world(*self.source)
        ex, ey = grid.cell_to_world(*self.target)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_CORE, 1.5))
        view.world_polygon(painter, [start, (ex, ey)], closed=False)
        half = WORLD_UNITS_PER_CELL / 2
        view.world_polygon(
            painter,
            [
                (ex - half, ey - half),
                (ex + half, ey - half),
                (ex + half, ey + half),
                (ex - half, ey + half),
            ],
        )


class AutoEdgeTool(Tool):
    """Auto Edge Out (`outward`) or Auto Edge In: click a texture area to edge it; Shift-click
    edges every area of that texture on the map."""

    def __init__(self, host: PaintHost, *, outward: bool) -> None:
        self.host = host
        self.outward = outward

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        document = view.document
        grid = document.terrain if document is not None else None
        blend = document.map.blend_tile_data if document is not None else None
        if document is None or grid is None or blend is None:
            return False
        if gesture.alt:
            _pick_texture_at(self.host, view, gesture)
            return True
        cell = grid.nearest_cell(*gesture.world)
        layers = _tile_layers(document)
        if cell is None or layers is None:
            return False
        routine = auto_edge_out if self.outward else auto_edge_in
        edit = routine(
            layers, blend.textures, blend.blend_descriptions, cell, whole_map=gesture.shift
        )
        _execute_blend(self.host, edit, "Auto Edge Out" if self.outward else "Auto Edge In")
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        return True


def _tile_layers(document: MapDocument) -> dict[TileLayer, object] | None:
    layers = {layer: document.cells(layer) for layer in TileLayer}
    return layers if layers[TileLayer.TILES] is not None else None


def _execute_blend(host: PaintHost, edit: BlendEdit | None, label: str) -> None:
    if edit is None:
        return
    command = PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions, label, edit.texture)
    host.execute(command)
    command.closed = True


def _texture_entry(
    host: PaintHost, blend: BlendTileData, name: str
) -> tuple[BlendTileTexture, BlendTileTexture | None] | None:
    """The table entry to paint `name` with, and the same entry again when the map does not have
    it yet (the paint adds it); None, after saying why, when there is no room for it."""
    index = texture_index(blend, name)
    if index is not None:
        return blend.textures[index], None
    try:
        planned = planned_texture(blend, name, host.texture_cell_size(name))
    except TextureCapacityError as exc:
        host.show_status(str(exc))
        return None
    return planned, planned


def _texture_name_at(document: object, blend: BlendTileData, cell: tuple[int, int]) -> str | None:
    tiles = document.cells(TileLayer.TILES)  # type: ignore[attr-defined]
    if tiles is None:
        return None
    column, row = cell
    index = int(texture_classes(tiles[row : row + 1, column : column + 1], blend.textures)[0, 0])
    return blend.textures[index].name if index >= 0 else None


def _pick_texture_at(host: PaintHost, view: ToolView, gesture: Gesture) -> None:
    document = view.document
    grid = document.terrain if document is not None else None
    blend = document.map.blend_tile_data if document is not None else None
    if document is None or grid is None or blend is None:
        return
    cell = grid.nearest_cell(*gesture.world)
    name = _texture_name_at(document, blend, cell) if cell is not None else None
    if name is not None:
        host.pick_texture(name)
