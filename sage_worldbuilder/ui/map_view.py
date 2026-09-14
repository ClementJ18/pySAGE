"""The top-down map view: the terrain picture with the objects, waypoints, trigger areas, grid and
map boundaries drawn over it.

Space-drag or middle-drag pans, the wheel zooms about the cursor, and moving the mouse reports the
heightmap sample under it. Everything it draws comes from the document through `MapScene` and
`TerrainGrid`, rebuilt only when the kind of data they show changes. It also keeps the state the
3D view shows (the document, the tool, the texture colours, the filters, the tile feedback) and
forwards each change to it when one is open.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Protocol

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import QWidget

from sage_worldbuilder.anchors import RotationAnchors
from sage_worldbuilder.changes import Change, ChangeKind, Region
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.footprints import Footprints
from sage_worldbuilder.layers import item_layer
from sage_worldbuilder.render.topdown import (
    blend_overlay,
    cell_overlay,
    contour_levels,
    contour_mask,
    mask_overlay,
    terrain_image,
)
from sage_worldbuilder.scene import MapScene
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, WORLD_UNITS_PER_CELL
from sage_worldbuilder.terrain.cells import CellLayer, TileLayer
from sage_worldbuilder.terrain.sizing import stretched_cells, unblended_cells
from sage_worldbuilder.ui.overlays import GRID_COLOR, OverlayPainter, arrow_head
from sage_worldbuilder.ui.tools import Gesture, Tool
from sage_worldbuilder.viewport import ViewOptions, ViewTransform

if TYPE_CHECKING:
    from sage_worldbuilder.influences import Influences
    from sage_worldbuilder.roads import RoadStyles

__all__ = ["MapView", "ViewTwin", "arrow_head"]

BaseColors = Callable[[MapDocument], object]

_BACKGROUND = QColor(24, 26, 30)
_STRETCHED = (255, 60, 200, 110)
_UNBLENDED = (255, 255, 255, 130)
_CONTOUR = (255, 236, 120, 220)
_PASSABILITY_LAYERS = (
    CellLayer.IMPASSABLE,
    CellLayer.IMPASSABLE_TO_PLAYERS,
    CellLayer.EXTRA_PASSABLE,
)
_ZOOM_STEP = 1.2


class ViewTwin(Protocol):
    """A second view of the same map (the 3D view), kept in step with this one."""

    def set_document(self, document: MapDocument | None) -> None: ...

    def on_change(self, change: Change) -> None: ...

    def colors_changed(self) -> None: ...

    def feedback_changed(self) -> None: ...

    def update(self) -> None: ...


def _stack(layers: Sequence[np.ndarray]) -> np.ndarray:
    """See-through RGBA pictures of one size laid over each other in order, as `uint8`."""
    color: np.ndarray = np.zeros(layers[0].shape[:2] + (3,), dtype=np.float32)
    alpha: np.ndarray = np.zeros(layers[0].shape[:2] + (1,), dtype=np.float32)
    for layer in layers:
        top = layer[..., 3:4].astype(np.float32) / 255
        merged = top + alpha * (1 - top)
        safe = np.where(merged > 0, merged, 1)
        color = (layer[..., :3] * top + color * alpha * (1 - top)) / safe
        alpha = merged
    stacked = np.concatenate((color, alpha * 255), axis=-1)
    return np.clip(np.rint(stacked), 0, 255).astype(np.uint8)


class MapView(QWidget, OverlayPainter):
    # (cell or None, height or None) under the cursor.
    cursor_moved = pyqtSignal(object, object)
    # A left-button gesture (a click or a drag) ended.
    gesture_finished = pyqtSignal()

    def __init__(self, options: ViewOptions | None = None, parent: QWidget | None = None) -> None:
        # The 3D view showing the same map, told about every change made here.
        self.twin: ViewTwin | None = None
        super().__init__(parent)
        self.options = options if options is not None else ViewOptions()
        self.document: MapDocument | None = None
        self.transform = ViewTransform()
        # RGB from the painted textures and their blends, a whole number of pixels a heightmap
        # cell side, or None for the height ramp.
        self.base_colors: object = None
        self._scene: MapScene | None = None
        self._image: QImage | None = None
        # The height range the picture's height ramp spans, so a patched part matches the rest.
        self._height_range: tuple[float, float] | None = None
        self._contours: QImage | None = None
        # The cell attribute layers tinted over the terrain (besides Show Impassable Areas).
        self.overlay_layers: tuple[CellLayer, ...] = ()
        self._overlay: QImage | None = None
        # Show Blends: the blended cells' tint.
        self._blends: QImage | None = None
        # Show Stretched Tiles: the stretched cells' tint.
        self._stretched: QImage | None = None
        # Show Unblended Tiles: the tint on cells that meet another texture without a blend.
        self._unblended: QImage | None = None
        self._panning = False
        self._space_down = False
        self._last_mouse: QPointF | None = None
        # The world position under the cursor while it is over the view, for Paste.
        self.cursor_world: tuple[float, float] | None = None
        self.tool: Tool = Tool()
        # True from the press a tool accepts until the button comes up: the window holds back
        # refreshing its lists meanwhile, so a drag is not slowed by redrawing them every step.
        self.gesture_active = False
        # The button that started it: the left one, or the right one for a tool that takes it.
        self._gesture_button = Qt.MouseButton.LeftButton
        # The ids of the only objects, waypoints and areas shown (the Item List's Filter map), or
        # None to show everything.
        self._shown: frozenset[int] | None = None
        self._hidden_layers: frozenset[str] = frozenset()
        # Object footprints and influence ranges from the game data; None until it has loaded.
        self.footprints: Footprints | None = None
        self.influences: Influences | None = None
        self.road_styles: RoadStyles | None = None
        self.camera_path: tuple[list[tuple[float, float]], list[tuple[float, float]]] | None = None
        # The camera objects the Cameras panel puts in the world, which the 3D view draws and
        # drags; this view shows the flat path instead, so it only holds them for its twin.
        self.camera_scene: object = None
        # Where objects with a rotation anchor stand; set with `set_anchors`.
        self.anchors: RotationAnchors | None = None
        # The build list entry chosen in the Build List panel, drawn highlighted.
        self.build_entry: object = None
        self.message = "No map open."
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 150)

    def update(self, *args: object) -> None:  # type: ignore[override]
        super().update(*args)  # type: ignore[arg-type]
        if self.twin is not None:
            self.twin.update()

    def _forget_feedback(self) -> None:
        """Drop the tile feedback pictures, here and in the 3D view."""
        self._contours = None
        self._overlay = None
        self._blends = None
        self._stretched = None
        self._unblended = None
        if self.twin is not None:
            self.twin.feedback_changed()

    def set_document(self, document: MapDocument | None) -> None:
        self.document = document
        self.base_colors = None
        self._scene = None
        self._image = None
        self._forget_feedback()
        if self.twin is not None:
            self.twin.set_document(document)
        self.fit_map()
        self.update()

    def set_overlay_layers(self, layers: Iterable[CellLayer]) -> None:
        """Tint these cell attribute layers over the terrain, as while painting them."""
        chosen = tuple(dict.fromkeys(layers))
        if chosen != self.overlay_layers:
            self.overlay_layers = chosen
            self._overlay = None
            if self.twin is not None:
                self.twin.feedback_changed()
            self.update()

    def on_change(self, change: Change) -> None:
        kind = change.kind
        if kind is ChangeKind.TERRAIN and change.region is not None:
            # A brush stroke: redraw only the cells it touched, unless the picture is not built.
            if self._image is not None and not self._patch_terrain(change.region):
                self._image = None
            self._forget_feedback()
        elif kind in (ChangeKind.TERRAIN, ChangeKind.WHOLE):
            self._image = None
            self._forget_feedback()
        if kind in (
            ChangeKind.OBJECTS,
            ChangeKind.WAYPOINTS,
            ChangeKind.AREAS,
            ChangeKind.WATER,
            ChangeKind.WHOLE,
        ):
            self._scene = None
        if self.twin is not None:
            self.twin.on_change(change)
        self.update()

    def options_changed(self) -> None:
        """Redraw after a View option changed; the texture toggle changes the terrain picture."""
        self._image = None
        self._forget_feedback()
        if self.twin is not None:
            self.twin.colors_changed()
        self.update()

    def set_shown(self, sources: Iterable[object] | None) -> None:
        """Show only these map items (placed objects, waypoints, trigger areas), or everything
        with None. Hidden items cannot be picked either."""
        shown = frozenset(id(source) for source in sources) if sources is not None else None
        if shown != self._shown:
            self._shown = shown
            self.update()

    def set_hidden_layers(self, layers: Iterable[str]) -> None:
        """Hide everything on these layers (the Layers List's unticked ones)."""
        hidden = frozenset(layers)
        if hidden != self._hidden_layers:
            self._hidden_layers = hidden
            self.update()

    def is_shown(self, source: object) -> bool:
        if self._hidden_layers and item_layer(source) in self._hidden_layers:
            return False
        return self._shown is None or id(source) in self._shown

    @property
    def visibility_key(self) -> object:
        """Changes whenever what `is_shown` answers can change: the shown items or the hidden
        layers."""
        return (self._shown, self._hidden_layers)

    def set_base_colors(self, colors: object) -> None:
        self.base_colors = colors
        self._image = None
        if self.twin is not None:
            self.twin.colors_changed()
        self.update()

    def set_anchors(self, anchors: RotationAnchors | None) -> None:
        """Stand objects out along their templates' rotation anchors, or at their stored
        positions with None; markers and the 3D view's models move with it."""
        self.anchors = anchors
        self._scene = None
        if self.twin is not None:
            self.twin.on_change(Change(ChangeKind.OBJECTS))
        self.update()

    @property
    def scene(self) -> MapScene | None:
        if self._scene is None and self.document is not None:
            self._scene = MapScene.from_map(self.document.map, self.anchors)
        return self._scene

    def map_bounds(self) -> tuple[float, float, float, float] | None:
        """The world rectangle the whole heightmap covers, border included."""
        grid = self.document.terrain if self.document is not None else None
        if grid is None:
            return None
        x0, y0 = grid.cell_to_world(-0.5, -0.5)
        x1, y1 = grid.cell_to_world(grid.width - 0.5, grid.height - 0.5)
        return x0, y0, x1, y1

    def fit_map(self) -> None:
        self.transform.width, self.transform.height = max(self.width(), 1), max(self.height(), 1)
        bounds = self.map_bounds()
        if bounds is not None:
            self.transform.fit(*bounds)
        self.update()

    def paste_position(self) -> tuple[float, float]:
        """Where Paste puts things: under the cursor when it is over the view, else the centre."""
        if self.cursor_world is not None:
            return self.cursor_world
        return self.transform.center_x, self.transform.center_y

    def zoom_to(self, x: float, y: float, scale: float = 1.0) -> None:
        """Centre on a world position, zooming in to at least `scale` pixels per world unit."""
        self.transform.center_on(x, y)
        self.transform.scale = max(self.transform.scale, scale)
        self.update()

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # noqa: N802 - Qt override
        first = self.transform.width <= 1
        self.transform.width, self.transform.height = max(self.width(), 1), max(self.height(), 1)
        if first:
            self.fit_map()
        super().resizeEvent(event)

    def _terrain_image(self) -> QImage | None:
        if self._image is None and self.document is not None:
            grid = self.document.terrain
            if grid is None:
                return None
            base = self.base_colors if self.options.show_texture else None
            self._height_range = (float(grid.heights.min()), float(grid.heights.max()))
            pixels = terrain_image(grid.heights, base, self._height_range)  # type: ignore[arg-type]
            self._image = _rgba_image(pixels)
        return self._image

    def _patch_terrain(self, region: Region) -> bool:
        """Redraw the cells of `region` and the ring around it (their slope shading reads their
        neighbours) into the terrain picture. False when only a full rebuild can show the change:
        the height ramp would need a new range."""
        document, image, height_range = self.document, self._image, self._height_range
        grid = document.terrain if document is not None else None
        if grid is None or image is None or height_range is None:
            return False
        heights = grid.heights
        rows, columns = heights.shape
        x0, y0 = max(region.x0 - 1, 0), max(region.y0 - 1, 0)
        x1, y1 = min(region.x1 + 1, columns), min(region.y1 + 1, rows)
        if x0 >= x1 or y0 >= y1:
            return True
        base = self.base_colors if self.options.show_texture else None
        # Pixels a cell side: the texture colours can have several.
        scale = base.shape[0] // rows if isinstance(base, np.ndarray) else 1
        if not (
            isinstance(base, np.ndarray)
            and scale >= 1
            and base.shape[:2] == (rows * scale, columns * scale)
        ):
            base, scale = None, 1
            block = heights[y0:y1, x0:x1]
            if block.min() < height_range[0] or block.max() > height_range[1]:
                return False
        # One more sample on each side, so the shading at the edge sees the real neighbours.
        xa, ya = max(x0 - 1, 0), max(y0 - 1, 0)
        xb, yb = min(x1 + 1, columns), min(y1 + 1, rows)
        around = heights[ya:yb, xa:xb]
        colors = None
        if base is not None:
            colors = base[ya * scale : yb * scale, xa * scale : xb * scale]
        pixels = terrain_image(around, colors, height_range)
        # `pixels` runs top first: its row r shows sample row yb - 1 - r // scale.
        crop = np.ascontiguousarray(
            pixels[(yb - y1) * scale : (yb - y0) * scale, (x0 - xa) * scale : (x1 - xa) * scale]
        )
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(QPoint(x0 * scale, (rows - y1) * scale), _rgba_image(crop))
        painter.end()
        return True

    # The tile feedback layers, each as see-through RGBA rows top first, or None when empty.

    def _contour_pixels(self) -> np.ndarray | None:
        document = self.document
        grid = document.terrain if document is not None else None
        if grid is None:
            return None
        contours = self.options.contours
        assert contours is not None
        heights = grid.heights
        levels = contour_levels(
            float(heights.min()),
            float(heights.max()),
            contours.count,
            contours.offset / FEET_PER_HEIGHT_UNIT,
        )
        mask = contour_mask(heights, levels, contours.width)
        pixels = np.zeros(mask.shape + (4,), dtype=np.uint8)
        pixels[mask] = _CONTOUR
        return np.ascontiguousarray(pixels[::-1])

    def _attribute_pixels(self) -> np.ndarray | None:
        document = self.document
        if document is None:
            return None
        wanted = (_PASSABILITY_LAYERS if self.options.show_impassable else ()) + tuple(
            self.overlay_layers
        )
        layers: dict[CellLayer, np.ndarray] = {}
        for layer in dict.fromkeys(wanted):
            values = document.cells(layer)
            if values is not None:
                layers[layer] = values
        return cell_overlay(layers) if layers else None

    def _blend_pixels(self) -> np.ndarray | None:
        document = self.document
        if document is None:
            return None
        blends = document.cells(TileLayer.BLENDS)
        three_way = document.cells(TileLayer.THREE_WAY_BLENDS)
        if blends is None or three_way is None:
            return None
        return blend_overlay(blends, three_way)

    def _stretched_pixels(self) -> np.ndarray | None:
        document = self.document
        grid = document.terrain if document is not None else None
        if grid is None:
            return None
        stretched = stretched_cells(grid.heights, self.options.stretched_threshold)
        return mask_overlay(stretched, _STRETCHED)

    def _unblended_pixels(self) -> np.ndarray | None:
        document = self.document
        blend = document.map.blend_tile_data if document is not None else None
        height_map = document.map.height_map_data if document is not None else None
        if document is None or blend is None:
            return None
        layers = {layer: document.cells(layer) for layer in TileLayer}
        border = height_map.border_width if height_map is not None else 0
        marked = unblended_cells(layers, blend.textures, border)
        return mask_overlay(marked, _UNBLENDED) if marked is not None else None

    def _feedback_layers(self) -> list[tuple[str, Callable[[], np.ndarray | None]]]:
        """The feedback layers switched on, in the order they are drawn."""
        options = self.options
        layers: list[tuple[str, Callable[[], np.ndarray | None]]] = []
        if options.show_impassable or self.overlay_layers:
            layers.append(("_overlay", self._attribute_pixels))
        if options.show_blends:
            layers.append(("_blends", self._blend_pixels))
        if options.show_stretched:
            layers.append(("_stretched", self._stretched_pixels))
        if options.show_unblended:
            layers.append(("_unblended", self._unblended_pixels))
        if options.show_contours:
            layers.append(("_contours", self._contour_pixels))
        return layers

    def tile_feedback(self) -> np.ndarray | None:
        """Every tile feedback view switched on, laid over each other as one see-through RGBA
        picture `[cell_y, cell_x]` from the bottom row, for the 3D view; None when none is on."""
        grid = self.document.terrain if self.document is not None else None
        if grid is None:
            return None
        pictures = [
            pixels
            for _name, make in self._feedback_layers()
            if (pixels := make()) is not None and pixels.shape[:2] == grid.heights.shape
        ]
        if not pictures:
            return None
        return np.ascontiguousarray(_stack(pictures)[::-1])

    def paintEvent(self, event: QPaintEvent | None) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), _BACKGROUND)
        document = self.document
        if document is None:
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        self._draw_terrain(painter)
        self._draw_overlays(painter)
        self.tool.paint(self, painter)
        painter.end()

    def _screen_rect(self, x0: float, y0: float, x1: float, y1: float) -> QRectF:
        left, top = self.transform.world_to_screen(x0, y1)
        right, bottom = self.transform.world_to_screen(x1, y0)
        return QRectF(QPointF(left, top), QPointF(right, bottom))

    def _draw_terrain(self, painter: QPainter) -> None:
        image, bounds = self._terrain_image(), self.map_bounds()
        if image is None or bounds is None:
            return
        # Close up, show the samples as blocks rather than a blur.
        smooth = self.transform.scale * WORLD_UNITS_PER_CELL < 4
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
        painter.drawImage(self._screen_rect(*bounds), image)
        for name, make in self._feedback_layers():
            layer = self._feedback_image(name, make)
            if layer is not None:
                painter.drawImage(self._screen_rect(*bounds), layer)

    def _feedback_image(self, name: str, make: Callable[[], np.ndarray | None]) -> QImage | None:
        """A tile feedback layer's picture, kept in the attribute `name` until it goes stale."""
        if getattr(self, name) is None:
            pixels = make()
            setattr(self, name, _rgba_image(pixels) if pixels is not None else None)
        image: QImage | None = getattr(self, name)
        return image

    def _overlay_image(self) -> QImage | None:
        return self._feedback_image("_overlay", self._attribute_pixels)

    def _blend_image(self) -> QImage | None:
        return self._feedback_image("_blends", self._blend_pixels)

    def _stretched_image(self) -> QImage | None:
        return self._feedback_image("_stretched", self._stretched_pixels)

    def _unblended_image(self) -> QImage | None:
        return self._feedback_image("_unblended", self._unblended_pixels)

    def _contour_image(self) -> QImage | None:
        return self._feedback_image("_contours", self._contour_pixels)

    def _draw_grid(self, painter: QPainter) -> None:
        grid = self.options.grid
        assert grid is not None
        xs, ys = self.transform.grid_lines(grid.spacing)
        painter.setPen(QPen(GRID_COLOR, 1))
        for x in xs:
            sx, _ = self.transform.world_to_screen(x, 0)
            painter.drawLine(QPointF(sx, 0), QPointF(sx, self.height()))
        for y in ys:
            _, sy = self.transform.world_to_screen(0, y)
            painter.drawLine(QPointF(0, sy), QPointF(self.width(), sy))

    def world_at(self, position: QPointF) -> tuple[float, float]:
        return self.transform.screen_to_world(position.x(), position.y())

    def _gesture(self, event: QMouseEvent) -> Gesture:
        modifiers = event.modifiers()
        return Gesture(
            self.world_at(event.position()),
            event.position(),
            shift=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
            alt=bool(modifiers & Qt.KeyboardModifier.AltModifier),
            right=event.button() == Qt.MouseButton.RightButton
            or bool(event.buttons() & Qt.MouseButton.RightButton),
        )

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        button = event.button()
        if button == Qt.MouseButton.MiddleButton or (
            button == Qt.MouseButton.LeftButton and self._space_down
        ):
            self._panning = True
            self._last_mouse = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        takes_button = button == Qt.MouseButton.LeftButton or (
            button == Qt.MouseButton.RightButton and self.tool.right_button
        )
        if takes_button and self.tool.press(self, self._gesture(event)):
            self.gesture_active = True
            self._gesture_button = button
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        position = event.position()
        self.cursor_world = self.world_at(position)
        if self._panning and self._last_mouse is not None:
            delta = position - self._last_mouse
            self.transform.pan_pixels(delta.x(), delta.y())
            self._last_mouse = position
            self.update()
        elif event.buttons() & Qt.MouseButton.LeftButton or (
            self.gesture_active and event.buttons() & self._gesture_button
        ):
            self.tool.move(self, self._gesture(event))
        elif not event.buttons():
            self.tool.hover(self, self._gesture(event))
        self._report_cursor(position)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        if self._panning:
            self._panning = False
            self._last_mouse = None
            self.unsetCursor()
            event.accept()
            return
        if event.button() == self._gesture_button and self.gesture_active:
            self.gesture_active = False
            handled = self.tool.release(self, self._gesture(event))
            self.gesture_finished.emit()
            if handled:
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        steps = event.angleDelta().y() / 120
        if self.options.reverse_scroll:
            steps = -steps
        if steps:
            position = event.position()
            self.transform.zoom_at(position.x(), position.y(), _ZOOM_STEP**steps)
            self.update()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # noqa: N802 - Qt override
        if event is not None and self.tool.key(self, event.key()):
            event.accept()
            return
        if event is not None and event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent | None) -> None:  # noqa: N802 - Qt override
        if event is not None and event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            if not self._panning:
                self.unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def leaveEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self.cursor_world = None
        self.cursor_moved.emit(None, None)

    def _report_cursor(self, position: QPointF) -> None:
        grid = self.document.terrain if self.document is not None else None
        if grid is None:
            self.cursor_moved.emit(None, None)
            return
        x, y = self.world_at(position)
        cell = grid.nearest_cell(x, y)
        height = grid.elevation_at(x, y)
        self.cursor_moved.emit(cell, float(height) if height is not None else None)


def _rgba_image(pixels: np.ndarray) -> QImage:
    """A QImage of contiguous `uint8` RGBA rows, copied so it owns its pixels."""
    height, width = pixels.shape[:2]
    data = np.ascontiguousarray(pixels).tobytes()
    return QImage(data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
