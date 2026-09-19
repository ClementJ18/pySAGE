"""The Terrain Copy Tool (WorldBuilder's `TerrainCopyTool`, command 33436): select cells, then
copy them onto the map at the cursor (PHASE3.md, 3.6).

Copy Terrain Options chooses the mode. In Selection mode a drag adds or removes the rectangle
between the press and the release (`TerrainDragSelector`), or the brush adds or removes a square
of cells round the cursor as it moves (`TerrainBrushSelector`). In Copy mode the selection, flipped
and turned, follows the cursor, and a click copies it there (the copy mode handler's mouse down,
`0x006131D0`). The selection belongs to the tool and the open map, and is not an undoable edit.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen

from sage_worldbuilder.brush_options import CopyTerrainOptions, SelectMethod
from sage_worldbuilder.terrain.cells import CellLayer, TileLayer
from sage_worldbuilder.terrain.copy import (
    CopyParts,
    CopyTransform,
    paste_terrain,
    selection_bounds,
)
from sage_worldbuilder.terrain.edits import CopyTerrain
from sage_worldbuilder.terrain.grid import TerrainGrid
from sage_worldbuilder.ui.tools import EditHost, Gesture, Tool, ToolView

__all__ = ["NOTHING_SELECTED", "CopyHost", "TerrainCopyTool"]

NOTHING_SELECTED = "Nothing is selected: select cells in Copy Terrain Options' Selection mode."

_SELECTED = (80, 200, 255, 90)
_LANDING = (255, 220, 80, 120)
_OUTLINE = QColor(255, 255, 255, 220)


class CopyHost(EditHost, Protocol):
    def copy_terrain_options(self) -> CopyTerrainOptions: ...

    def show_status(self, text: str) -> None: ...


class TerrainCopyTool(Tool):
    def __init__(self, host: CopyHost) -> None:
        self.host = host
        # The selected cells, `[cell_y, cell_x]`, for the map they were selected on.
        self.selection: np.ndarray | None = None
        self._document: object = None
        self.cursor: tuple[int, int] | None = None
        self._start: tuple[int, int] | None = None
        self._brushing = False
        self._image: QImage | None = None

    def _grid(self, view: ToolView) -> TerrainGrid | None:
        """The view's terrain, with the selection made to fit its map."""
        document = view.document
        grid = document.terrain if document is not None else None
        if grid is None:
            return None
        shape = grid.heights.shape
        if (
            self._document is not document
            or self.selection is None
            or self.selection.shape != shape
        ):
            self._document = document
            self.selection = np.zeros(shape, dtype=bool)
            self._image = None
        return grid

    def clear_selection(self) -> None:
        if self.selection is not None:
            self.selection[:] = False
        self._image = None

    def _cell(self, view: ToolView, gesture: Gesture) -> tuple[int, int] | None:
        grid = self._grid(view)
        return grid.nearest_cell(*gesture.world) if grid is not None else None

    def _mark(self, block: tuple[int, int, int, int], remove: bool) -> None:
        assert self.selection is not None
        rows, columns = self.selection.shape
        x0, y0, x1, y1 = block
        x0, x1 = max(x0, 0), min(x1, columns)
        y0, y1 = max(y0, 0), min(y1, rows)
        if x0 < x1 and y0 < y1:
            self.selection[y0:y1, x0:x1] = not remove
            self._image = None

    @staticmethod
    def _brush_block(cell: tuple[int, int], size: int) -> tuple[int, int, int, int]:
        left, bottom = cell[0] - size // 2, cell[1] - size // 2
        return left, bottom, left + size, bottom + size

    def press(self, view: ToolView, gesture: Gesture) -> bool:
        cell = self._cell(view, gesture)
        if cell is None:
            return False
        options = self.host.copy_terrain_options()
        self.cursor = cell
        if options.copying:
            self._paste(view, cell, options)
        elif options.method is SelectMethod.BRUSH:
            self._brushing = True
            self._mark(self._brush_block(cell, options.brush_size), options.remove)
        else:
            self._start = cell
        view.update()
        return True

    def move(self, view: ToolView, gesture: Gesture) -> bool:
        cell = self._cell(view, gesture)
        if cell is None:
            return False
        self.cursor = cell
        if self._brushing:
            options = self.host.copy_terrain_options()
            self._mark(self._brush_block(cell, options.brush_size), options.remove)
        view.update()
        return True

    def release(self, view: ToolView, gesture: Gesture) -> bool:
        cell = self._cell(view, gesture) or self.cursor
        if self._start is not None and cell is not None:
            (sx, sy), (ex, ey) = self._start, cell
            block = (min(sx, ex), min(sy, ey), max(sx, ex) + 1, max(sy, ey) + 1)
            self._mark(block, self.host.copy_terrain_options().remove)
        self._start = None
        self._brushing = False
        view.update()
        return True

    def hover(self, view: ToolView, gesture: Gesture) -> None:
        self.cursor = self._cell(view, gesture)
        view.update()

    def cancel(self) -> None:
        self._start = None
        self._brushing = False
        self.cursor = None

    def transform(self, cell: tuple[int, int], options: CopyTerrainOptions) -> CopyTransform | None:
        """Where the selection lands with its centre on `cell`; None with nothing selected."""
        bounds = selection_bounds(self.selection) if self.selection is not None else None
        if bounds is None:
            return None
        return CopyTransform.centred(
            bounds, cell, options.turns, options.flip_vertically, options.flip_horizontally
        )

    def _paste(self, view: ToolView, cell: tuple[int, int], options: CopyTerrainOptions) -> None:
        document = view.document
        grid = document.terrain if document is not None else None
        blend = document.map.blend_tile_data if document is not None else None
        transform = self.transform(cell, options)
        if transform is None:
            self.host.show_status(NOTHING_SELECTED)
            return
        if document is None or grid is None or blend is None or self.selection is None:
            return
        layers = {layer: document.cells(layer) for layer in (*TileLayer, *CellLayer)}
        paste = paste_terrain(
            grid.heights,
            layers,
            blend.textures,
            blend.blend_descriptions,
            self.selection,
            transform,
            CopyParts(options.heights, options.texture, options.passability),
        )
        if paste is None:
            return
        command = CopyTerrain(paste.patches, paste.descriptions)
        self.host.execute(command)
        command.closed = True

    def paint(self, view: ToolView, painter: QPainter) -> None:
        grid = self._grid(view)
        if grid is None or self.selection is None:
            return
        rows, columns = self.selection.shape
        if self.selection.any():
            if self._image is None:
                self._image = _mask_image(self.selection, _SELECTED)
            painter.drawImage(_cell_rect(view, grid, (0, 0, columns, rows)), self._image)
        if self.cursor is None:
            return
        options = self.host.copy_terrain_options()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_OUTLINE, 1.5))
        if options.copying:
            transform = self.transform(self.cursor, options)
            bounds = selection_bounds(self.selection)
            if transform is None or bounds is None:
                return
            box = transform.target_bounds(bounds, self.selection.shape)
            x0, y0, x1, y1 = box
            if x0 >= x1 or y0 >= y1:
                return
            ys, xs = np.mgrid[y0:y1, x0:x1]
            sx, sy = transform.cell_source(xs, ys)
            inside = (sx >= 0) & (sx < columns) & (sy >= 0) & (sy < rows)
            landed = np.zeros(xs.shape, dtype=bool)
            landed[inside] = self.selection[sy[inside], sx[inside]]
            painter.drawImage(_cell_rect(view, grid, box), _mask_image(landed, _LANDING))
            _outline_cells(view, painter, grid, box)
        elif self._start is not None:
            (sx0, sy0), (ex, ey) = self._start, self.cursor
            block = (min(sx0, ex), min(sy0, ey), max(sx0, ex) + 1, max(sy0, ey) + 1)
            _outline_cells(view, painter, grid, block)
        elif options.method is SelectMethod.BRUSH:
            block = self._brush_block(self.cursor, options.brush_size)
            _outline_cells(view, painter, grid, block)


def _outline_cells(
    view: ToolView, painter: QPainter, grid: TerrainGrid, block: tuple[int, int, int, int]
) -> None:
    """The outline of a block of cells, on the ground."""
    x0, y0, x1, y1 = block
    left, bottom = grid.cell_to_world(x0 - 0.5, y0 - 0.5)
    right, top = grid.cell_to_world(x1 - 0.5, y1 - 0.5)
    view.world_polygon(painter, [(left, bottom), (right, bottom), (right, top), (left, top)])


def _cell_rect(view: ToolView, grid: TerrainGrid, block: tuple[int, int, int, int]) -> QRectF:
    x0, y0, x1, y1 = block
    left, bottom = grid.cell_to_world(x0 - 0.5, y0 - 0.5)
    right, top = grid.cell_to_world(x1 - 0.5, y1 - 0.5)
    sx0, sy0 = view.transform.world_to_screen(left, top)
    sx1, sy1 = view.transform.world_to_screen(right, bottom)
    return QRectF(QPointF(sx0, sy0), QPointF(sx1, sy1))


def _mask_image(mask: np.ndarray, rgba: tuple[int, int, int, int]) -> QImage:
    """A see-through picture of `mask`, rows top first."""
    rows, columns = mask.shape
    pixels = np.zeros((rows, columns, 4), dtype=np.uint8)
    pixels[mask] = rgba
    data = np.ascontiguousarray(pixels[::-1]).tobytes()
    return QImage(data, columns, rows, 4 * columns, QImage.Format.Format_RGBA8888).copy()
