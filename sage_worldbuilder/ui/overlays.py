"""What both map views draw over the terrain: the map boundaries, roads, trigger areas, waypoint
links, object and waypoint markers with their footprints, and build list entries.

`OverlayPainter` is a mixin. The view supplies `document`, `options`, `transform`, `scene`,
`footprints`, `road_styles`, `build_entry` and `is_shown`, and a `_draw_grid` of its own. The
top-down view answers the projection hooks (`_to_screen`, `_screen_points`, `_screen_path`,
`_world_circle`) with its flat transform; the 3D view answers them with its camera, where a point
can be behind it and a long edge has to follow the ground. The 3D view draws the roads themselves
as textured ground (`render.road_surface`) and leaves the overlay only their outlines.

`draw_label` draws every name either view puts over the terrain, the tools' own readouts included.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)

from sage_map.assets.river_areas import RiverArea
from sage_map.assets.standing_waves_area import StandingWaveArea
from sage_worldbuilder.build_lists import build_list_entries, side_names
from sage_worldbuilder.footprints import FootprintShape
from sage_worldbuilder.gizmos import HANDLE_KNOB_PIXELS, front_tip
from sage_worldbuilder.influences import sound_ranges
from sage_worldbuilder.road_mesh import RoadPiece, road_pieces
from sage_worldbuilder.roads import DEFAULT_ROAD_WIDTH, RoadSegment, RoadStyle
from sage_worldbuilder.scene import MapScene, Marker, MarkerKind
from sage_worldbuilder.terrain import WORLD_UNITS_PER_CELL
from sage_worldbuilder.water import water_handles

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument
    from sage_worldbuilder.footprints import Footprints
    from sage_worldbuilder.influences import Influences
    from sage_worldbuilder.roads import RoadStyles
    from sage_worldbuilder.viewport import ViewOptions

__all__ = [
    "BRIDGE_FILL",
    "CAMERA_PATH",
    "GRID_COLOR",
    "ROAD_FILL",
    "OverlayPainter",
    "arrow_head",
    "draw_label",
]

GRID_COLOR = QColor(255, 255, 255, 45)
# Screen pixels: an arrowhead's length and half width, and the shortest line that gets one.
_ARROW_LENGTH = 9.0
_ARROW_HALF_WIDTH = 4.0
_ARROW_MIN_LINE = 14.0
_MARKER_COLORS = {
    MarkerKind.OBJECT: QColor(250, 214, 90),
    MarkerKind.WAYPOINT: QColor(90, 200, 255),
    MarkerKind.ROAD: QColor(160, 160, 160),
    MarkerKind.GENERIC_AI: QColor(255, 120, 200),
}
_AREA_FILL = QColor(255, 80, 60, 40)
_AREA_LINE = QColor(255, 110, 90)
_LINK = QColor(90, 200, 255, 170)
_BOUNDARY = QColor(255, 255, 255, 200)
_BORDER = QColor(255, 60, 60, 160)
_SELECTED = QColor(255, 255, 255)
# The front handle on a selected object: warmer than the ring, since it can be grabbed.
_HANDLE = QColor(255, 200, 60)
_FOOTPRINT = QColor(250, 214, 90, 140)
_FOOTPRINT_MIN_PIXELS = 4.0
_BUILD_LIST = QColor(120, 255, 160)
_BOUNDING_BOX = QColor(120, 200, 255, 210)
_SIGHT = QColor(90, 230, 130, 180)
_WEAPON = QColor(255, 90, 70, 190)
_SOUND = QColor(200, 150, 255, 180)
# A road and a bridge with no texture of their own; the 3D view fills them with these too.
ROAD_FILL = QColor(170, 140, 100, 150)
BRIDGE_FILL = QColor(205, 205, 215, 170)
_ROAD_EDGE = QColor(95, 75, 55, 200)
_LAKE_FILL = QColor(60, 130, 220, 90)
_WATER_EDGE = QColor(110, 180, 255, 210)
_WAVE = QColor(170, 240, 255, 220)
CAMERA_PATH = QColor(255, 170, 60, 230)
_LABEL_MIN_SCALE = 0.35
# A name over the terrain is white inside a dark halo, so it reads over pale sand as well as over
# dark rock. It is drawn once into a pixmap of whole device pixels and blitted where it belongs:
# the 3D view paints through OpenGL, whose glyph cache smears text at this size, and a pixmap
# landing on whole pixels is sharp in either view.
_LABEL_TEXT = QColor(255, 255, 255)
_LABEL_HALO = QColor(0, 0, 0, 200)
# Pixels of room round the glyphs for the halo.
_LABEL_PAD = 2
_LABEL_CACHE_LIMIT = 4096
_label_cache: dict[tuple[str, str, int, float], tuple[QPixmap, QPointF]] = {}


def arrow_head(
    tail: tuple[float, float], tip: tuple[float, float], gap: float = 0.0
) -> list[tuple[float, float]] | None:
    """The three corners of an arrowhead pointing along `tail` -> `tip`, its point `gap` pixels
    short of `tip`; None for a line too short to show one."""
    dx, dy = tip[0] - tail[0], tip[1] - tail[1]
    length = math.hypot(dx, dy)
    if length < _ARROW_MIN_LINE + gap:
        return None
    ux, uy = dx / length, dy / length
    point = (tip[0] - ux * gap, tip[1] - uy * gap)
    base = (point[0] - ux * _ARROW_LENGTH, point[1] - uy * _ARROW_LENGTH)
    return [
        point,
        (base[0] - uy * _ARROW_HALF_WIDTH, base[1] + ux * _ARROW_HALF_WIDTH),
        (base[0] + uy * _ARROW_HALF_WIDTH, base[1] - ux * _ARROW_HALF_WIDTH),
    ]


def road_corners(
    start: tuple[float, float], end: tuple[float, float], width: float
) -> list[tuple[float, float]] | None:
    """The corners of a strip `width` world units across from `start` to `end`, or None when the
    two points coincide."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return None
    nx, ny = -dy / length * width / 2, dx / length * width / 2
    return [
        (start[0] + nx, start[1] + ny),
        (end[0] + nx, end[1] + ny),
        (end[0] - nx, end[1] - ny),
        (start[0] - nx, start[1] - ny),
    ]


def _water_fill(area: object) -> QColor:
    """A lake's fill, or a river's: its colour (white, the default, shown as water blue) at
    alpha scaled from its own."""
    if not isinstance(area, RiverArea):
        return _LAKE_FILL
    red, green, blue = area.color
    if (red, green, blue) == (255, 255, 255):
        red, green, blue = _LAKE_FILL.red(), _LAKE_FILL.green(), _LAKE_FILL.blue()
    return QColor(red, green, blue, max(30, min(140, round(140 * area.alpha))))


def _label_pixmap(text: str, font: QFont, color: QColor, ratio: float) -> tuple[QPixmap, QPointF]:
    """The label as a pixmap of whole device pixels, with the offset from the point it is anchored
    at to the pixmap's top left. Kept per text, font, colour and ratio: a map shows the same few
    hundred names frame after frame."""
    key = (text, font.toString(), color.rgba(), ratio)
    made = _label_cache.get(key)
    if made is not None:
        return made
    metrics = QFontMetricsF(font)
    origin = QPointF(_LABEL_PAD, _LABEL_PAD + metrics.ascent())
    width = math.ceil(metrics.horizontalAdvance(text)) + 2 * _LABEL_PAD
    height = math.ceil(metrics.height()) + 2 * _LABEL_PAD
    pixmap = QPixmap(round(width * ratio), round(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setFont(font)
    painter.setPen(QPen(_LABEL_HALO))
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        painter.drawText(origin + QPointF(dx, dy), text)
    painter.setPen(QPen(color))
    painter.drawText(origin, text)
    painter.end()
    if len(_label_cache) >= _LABEL_CACHE_LIMIT:
        # Drop the oldest half rather than all of it: a view showing more names than the cache
        # holds would otherwise redraw every one of them every frame.
        for old in list(_label_cache)[: _LABEL_CACHE_LIMIT // 2]:
            del _label_cache[old]
    made = (pixmap, QPointF(-origin.x(), -origin.y()))
    _label_cache[key] = made
    return made


def draw_label(
    painter: QPainter,
    point: QPointF,
    text: str,
    color: QColor = _LABEL_TEXT,
    centered: bool = False,
) -> None:
    """A name over the terrain, its baseline starting at `point` (centred on it when asked)."""
    if not text:
        return
    device = painter.device()
    ratio = device.devicePixelRatioF() if device is not None else 1.0
    pixmap, offset = _label_pixmap(text, painter.font(), color, ratio)
    x = point.x() + offset.x()
    y = point.y() + offset.y()
    if centered:
        x -= pixmap.width() / ratio / 2 - _LABEL_PAD
    smooth = painter.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    # On whole device pixels, so the glyphs land on the pixels they were drawn for.
    painter.drawPixmap(QPointF(round(x * ratio) / ratio, round(y * ratio) / ratio), pixmap)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)


def _is_bidirectional(obj: object) -> bool:
    properties = getattr(obj, "properties", {})
    stored = properties.get("waypointPathBiDirectional")
    return bool(stored["value"]) if stored is not None else False


class OverlayPainter:
    document: MapDocument | None
    options: ViewOptions
    transform: Any
    footprints: Footprints | None
    influences: Influences | None
    road_styles: RoadStyles | None
    build_entry: object
    # The chosen camera animation's path and key points (world x, y), or None.
    camera_path: tuple[list[tuple[float, float]], list[tuple[float, float]]] | None

    @property
    def scene(self) -> MapScene | None:
        return None

    def is_shown(self, source: object) -> bool:
        return True

    def _to_screen(self, x: float, y: float) -> QPointF | None:
        """Pixels for a world position on the ground, or None where the view cannot show it."""
        return QPointF(*self.transform.world_to_screen(x, y))

    def _screen_points(self, markers: Sequence[Marker]) -> list[QPointF | None]:
        return [self._to_screen(marker.x, marker.y) for marker in markers]

    def _screen_path(
        self, points: Sequence[tuple[float, float]], closed: bool = False
    ) -> list[QPointF] | None:
        """A world outline as pixels, or None when part of it cannot be shown."""
        screen = [self._to_screen(x, y) for x, y in points]
        if any(point is None for point in screen):
            return None
        return [point for point in screen if point is not None]

    def _world_circle(self, painter: QPainter, x: float, y: float, radius: float) -> None:
        center = self._to_screen(x, y)
        if center is not None:
            pixels = radius * self.transform.scale
            painter.drawEllipse(center, pixels, pixels)

    def world_circle(self, painter: QPainter, x: float, y: float, radius: float) -> None:
        """A circle of `radius` world units on the ground about a world position."""
        self._world_circle(painter, x, y, radius)

    def world_polygon(
        self, painter: QPainter, points: Sequence[tuple[float, float]], closed: bool = True
    ) -> None:
        """A world outline on the ground: a polygon, or a line through the points."""
        path = self._screen_path(points, closed)
        if path is None or len(path) < 2:
            return
        if closed:
            painter.drawPolygon(QPolygonF(path))
        else:
            painter.drawPolyline(QPolygonF(path))

    def _draw_grid(self, painter: QPainter) -> None:
        return None

    def _water_surface_drawn(self, area: object) -> bool:
        """Whether the view draws a water area's surface itself, so the overlay leaves its fill
        out."""
        return False

    def _marker_footprint(self, marker: Marker) -> bool:
        """Whether an object's footprint is drawn under its dot; a view that draws the object
        itself says no. The selection ring and label are drawn either way."""
        return True

    def _marker_dot(self, marker: Marker) -> bool:
        """Whether a marker is drawn as a dot; a view that draws the object itself may say no,
        since a dot per object on a map of thousands hides the map under them."""
        return True

    def _dot_size(self, kind: MarkerKind) -> float:
        """How wide a marker's dot is in pixels: it grows with the zoom, within limits."""
        return max(3.0, min(9.0, 30 * self.transform.scale))

    def _selection_ring(self, kind: MarkerKind) -> float:
        """The radius of the ring around a selected marker, just outside its dot."""
        return self._dot_size(kind) / 2 + 3

    def marker_at(
        self,
        screen: QPointF,
        world: tuple[float, float],
        pixels: float,
        accept: Callable[[Marker], bool],
    ) -> Marker | None:
        """The marker a click picks: the nearest one within `pixels` of the ground point the
        click landed on."""
        scene = self.scene
        if scene is None:
            return None
        return scene.nearest(*world, pixels / self.transform.scale, accept=accept)

    def _draw_overlays(self, painter: QPainter) -> None:
        """Everything over the terrain except the tool's own feedback."""
        if self.options.show_boundaries:
            self._draw_boundaries(painter)
        if self.options.show_grid:
            self._draw_grid(painter)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scene = self.scene
        if scene is not None:
            if self.options.show_water:
                self._draw_water(painter, scene)
            if self.options.show_roads:
                self._draw_roads(painter, scene)
            if self.options.show_areas:
                self._draw_areas(painter, scene)
            if self.options.show_waypoints:
                self._draw_links(painter, scene)
            self._draw_markers(painter, scene)
        if self.options.show_objects:
            self._draw_build_lists(painter)
        self._draw_camera_path(painter)

    def _draw_camera_path(self, painter: QPainter) -> None:
        """The chosen camera animation's path on the ground, its keys as squares (Show Path)."""
        path = self.camera_path
        if path is None:
            return
        points, keys = path
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(CAMERA_PATH, 2))
        if len(points) >= 2:
            self.world_polygon(painter, points, closed=False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(CAMERA_PATH))
        for x, y in keys:
            point = self._to_screen(x, y)
            if point is not None:
                painter.drawRect(QRectF(point.x() - 4, point.y() - 4, 8, 8))

    def _draw_world_rect(
        self, painter: QPainter, x0: float, y0: float, x1: float, y1: float
    ) -> None:
        path = self._screen_path([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True)
        if path is not None:
            painter.drawPolygon(QPolygonF(path))

    def _draw_boundaries(self, painter: QPainter) -> None:
        document = self.document
        grid = document.terrain if document is not None else None
        if grid is None or document is None:
            return
        height_map = document.map.height_map_data
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_BORDER, 1, Qt.PenStyle.DashLine))
        playable_x = (grid.width - 1 - 2 * grid.border) * WORLD_UNITS_PER_CELL
        playable_y = (grid.height - 1 - 2 * grid.border) * WORLD_UNITS_PER_CELL
        self._draw_world_rect(painter, 0.0, 0.0, playable_x, playable_y)
        painter.setPen(QPen(_BOUNDARY, 1))
        for border in height_map.borders if height_map is not None else []:
            (cx, cy), (px, py) = border.corner1, border.position
            self._draw_world_rect(
                painter,
                cx * WORLD_UNITS_PER_CELL,
                cy * WORLD_UNITS_PER_CELL,
                px * WORLD_UNITS_PER_CELL,
                py * WORLD_UNITS_PER_CELL,
            )

    def _draw_water(self, painter: QPainter, scene: MapScene) -> None:
        """Lakes and rivers as filled outlines (a river in its colour, as clear as its alpha),
        wave areas as lines; a selected area outlined in white with its points as handles."""
        selection = self.document.selection if self.document is not None else ()
        for outline in scene.water:
            area = outline.source
            if not self.is_shown(area) or not outline.points:
                continue
            selected = area in selection
            wave = isinstance(area, StandingWaveArea)
            closed = not wave and len(outline.points) >= 3
            path = self._screen_path(outline.points, closed=closed)
            if path is None:
                continue
            if wave:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_SELECTED if selected else _WAVE, 2.5))
                if len(path) == 1:
                    painter.drawEllipse(path[0], 4.0, 4.0)
                else:
                    painter.drawPolyline(QPolygonF(path))
            elif closed:
                # Where the view draws the water's own surface, only the outline goes over it.
                drawn = self._water_surface_drawn(area)
                painter.setBrush(Qt.BrushStyle.NoBrush if drawn else QBrush(_water_fill(area)))
                painter.setPen(QPen(_SELECTED, 2.5) if selected else QPen(_WATER_EDGE, 1))
                painter.drawPolygon(QPolygonF(path))
            if selected:
                painter.save()
                painter.setBrush(QBrush(_SELECTED))
                painter.setPen(Qt.PenStyle.NoPen)
                for _handle, (x, y) in water_handles(area):
                    corner = self._to_screen(x, y)
                    if corner is not None:
                        painter.drawRect(QRectF(corner.x() - 3, corner.y() - 3, 6, 6))
                painter.restore()
            if (
                self.options.show_labels
                and outline.name
                and self.transform.scale >= _LABEL_MIN_SCALE
            ):
                draw_label(
                    painter, QPolygonF(path).boundingRect().center(), outline.name, centered=True
                )

    def _road_style(self, type_name: str) -> RoadStyle:
        styles = self.road_styles
        if styles is None:
            return RoadStyle(DEFAULT_ROAD_WIDTH, bridge=False)
        return styles.get(type_name)

    def road_outline(self, segment: RoadSegment) -> list[tuple[float, float]] | None:
        """A segment's four corners on the ground, as wide as the game draws it; None for a
        segment whose ends coincide."""
        style = self._road_style(segment.type_name)
        width = style.width * (1.0 if style.bridge else style.width_in_texture)
        return road_corners(*segment.points, width)

    def road_key(self, scene: MapScene) -> object:
        """What the scene's road layout is made of: a road end, road type or road style change
        gives another key, anything else the same one."""
        return (
            id(self.road_styles),
            tuple(
                (s.start.position, s.end.position, s.start.road_type, s.end.road_type, s.type_name)
                for s in scene.roads
            ),
        )

    def road_pieces(self, scene: MapScene) -> list[RoadPiece]:
        """The scene's roads laid out as the game does (`road_mesh`), kept while no road end, road
        type or road style changes."""
        key = self.road_key(scene)
        cached = getattr(self, "_road_pieces_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        pieces = road_pieces(scene.roads, self._road_style)
        self._road_pieces_cache = (key, pieces)
        return pieces

    def _draw_roads(self, painter: QPainter, scene: MapScene) -> None:
        """The roads as the game lays them out: strips meeting at mitres and curves where two
        segments of a type share a point (tees, Y and four-way joins end square), bridges paler;
        the selected segments outlined in white."""
        x0, y0, x1, y1 = self.transform.visible_world()
        selection = self.document.selection if self.document is not None else ()
        for piece in self.road_pieces(scene):
            segment = piece.segment
            if not (self.is_shown(segment.start) and self.is_shown(segment.end)):
                continue
            corners = piece.corners
            xs, ys = [x for x, _ in corners], [y for _, y in corners]
            if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                continue
            path = self._screen_path(corners, closed=True)
            if path is None:
                continue
            selected = segment.start in selection or segment.end in selection
            painter.setBrush(QBrush(BRIDGE_FILL if segment.bridge else ROAD_FILL))
            if selected:
                painter.setPen(QPen(_SELECTED, 2))
            elif piece.curve:
                # A curve piece's edges would draw seams across the road.
                painter.setPen(Qt.PenStyle.NoPen)
            else:
                painter.setPen(QPen(_ROAD_EDGE, 1))
            painter.drawPolygon(QPolygonF(path))

    def _draw_areas(self, painter: QPainter, scene: MapScene) -> None:
        painter.setBrush(QBrush(_AREA_FILL))
        selection = self.document.selection if self.document is not None else ()
        for area in scene.areas:
            if not self.is_shown(area.source):
                continue
            path = self._screen_path(area.points, closed=True)
            if path is None:
                continue
            polygon = QPolygonF(path)
            selected = area.source in selection
            painter.setPen(QPen(_SELECTED if selected else _AREA_LINE, 2.5 if selected else 1.5))
            painter.drawPolygon(polygon)
            if selected:
                # Corner handles: dragging one reshapes the area.
                painter.save()
                painter.setBrush(QBrush(_SELECTED))
                painter.setPen(Qt.PenStyle.NoPen)
                for x, y in area.points:
                    corner = self._to_screen(x, y)
                    if corner is not None:
                        painter.drawRect(QRectF(corner.x() - 3, corner.y() - 3, 6, 6))
                painter.restore()
            if self.options.show_labels and area.points and area.name:
                draw_label(painter, polygon.boundingRect().center(), area.name, centered=True)

    def _draw_links(self, painter: QPainter, scene: MapScene) -> None:
        """Each waypoint link as a line with an arrowhead at the waypoint it leads to, and one at
        its start too when the start waypoint is bi-directional."""
        painter.setPen(QPen(_LINK, 1.5))
        painter.setBrush(QBrush(_LINK))
        # Stop the head at the edge of the waypoint's dot rather than under it.
        gap = self._dot_size(MarkerKind.WAYPOINT) / 2 + 2
        for start, end in scene.links:
            if not (self.is_shown(start.source) and self.is_shown(end.source)):
                continue
            tail_point, tip_point = self._to_screen(start.x, start.y), self._to_screen(end.x, end.y)
            if tail_point is None or tip_point is None:
                continue
            tail, tip = (tail_point.x(), tail_point.y()), (tip_point.x(), tip_point.y())
            painter.drawLine(tail_point, tip_point)
            heads = [arrow_head(tail, tip, gap)]
            if _is_bidirectional(start.source):
                heads.append(arrow_head(tip, tail, gap))
            for head in heads:
                if head is not None:
                    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in head]))

    def _draw_markers(self, painter: QPainter, scene: MapScene) -> None:
        x0, y0, x1, y1 = self.transform.visible_world()
        margin = 20 / self.transform.scale
        markers = [
            marker
            for marker in scene.in_rect(x0 - margin, y0 - margin, x1 + margin, y1 + margin)
            if self.options.shows(marker.kind) and self.is_shown(marker.source)
        ]
        batches: dict[MarkerKind, list[QPointF]] = {kind: [] for kind in MarkerKind}
        labels: list[tuple[QPointF, str]] = []
        selected: list[tuple[Marker, QPointF]] = []
        selection = self.document.selection if self.document is not None else ()
        for marker, point in zip(markers, self._screen_points(markers), strict=True):
            if point is None:
                continue
            if self._marker_dot(marker):
                batches[marker.kind].append(point)
            if marker.kind is MarkerKind.OBJECT and self._marker_footprint(marker):
                self._draw_footprint(painter, marker)
            if marker.source in selection:
                selected.append((marker, point))
            if marker.label:
                size = self._dot_size(marker.kind)
                labels.append((point + QPointF(size, -size / 2), marker.label))
        self._draw_influences(
            painter, [marker for marker in markers if marker.kind is MarkerKind.OBJECT]
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for kind, points in batches.items():
            if not points:
                continue
            width = self._dot_size(kind)
            painter.setPen(QPen(_MARKER_COLORS[kind], width, cap=Qt.PenCapStyle.RoundCap))
            painter.drawPoints(QPolygonF(points))
        painter.setPen(QPen(_SELECTED, 1.5))
        for marker, point in selected:
            ring = self._selection_ring(marker.kind)
            painter.drawEllipse(point, ring, ring)
        self._draw_front_handles(painter, selected, self._selection_ring(MarkerKind.OBJECT))
        if self.options.show_labels and self.transform.scale >= _LABEL_MIN_SCALE:
            for point, text in labels:
                draw_label(painter, point, text)

    def _draw_front_handles(
        self, painter: QPainter, selected: Sequence[tuple[Marker, QPointF]], ring: float
    ) -> None:
        """The line out of a selected object's ring along its facing, with the knob that grabs it
        to turn the object. Only objects have a facing, so only they get one."""
        painter.setPen(QPen(_HANDLE, 1.5))
        painter.setBrush(QBrush(_HANDLE))
        for marker, point in selected:
            if marker.kind is not MarkerKind.OBJECT:
                continue
            out = front_tip(marker.x, marker.y, marker.angle, self.transform.scale)
            tip = self._to_screen(*out)
            if tip is None:
                continue
            dx, dy = tip.x() - point.x(), tip.y() - point.y()
            length = math.hypot(dx, dy)
            if length <= ring:
                continue
            start = QPointF(point.x() + dx / length * ring, point.y() + dy / length * ring)
            painter.drawLine(start, tip)
            painter.drawEllipse(tip, HANDLE_KNOB_PIXELS, HANDLE_KNOB_PIXELS)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_build_lists(self, painter: QPainter) -> None:
        """Every player's build list entries, as squares; the chosen one outlined in white."""
        document = self.document
        if document is None:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for side in range(len(side_names(document.map))):
            for entry in build_list_entries(document.map, side) or []:
                point = self._to_screen(*entry.location[:2])
                if point is None:
                    continue
                chosen = entry is self.build_entry
                painter.setPen(QPen(_SELECTED if chosen else _BUILD_LIST, 2.5 if chosen else 1.5))
                painter.drawRect(QRectF(point.x() - 5, point.y() - 5, 10, 10))
                if self.options.show_labels and self.transform.scale >= _LABEL_MIN_SCALE:
                    draw_label(painter, point + QPointF(8, 4), entry.build_name)

    def _draw_influences(self, painter: QPainter, markers: Sequence[Marker]) -> None:
        """The influence views, for each object: its bounding box (its footprint, however
        small), and circles of how far it sees, how far its weapons reach, and its customized
        ambient sound's ranges (the minimum dashed)."""
        options, influences = self.options, self.influences
        if not (
            options.show_bounding_boxes
            or options.show_sight_ranges
            or options.show_weapon_ranges
            or options.show_sound_circles
        ):
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for marker in markers:
            obj = marker.source
            if options.show_bounding_boxes:
                self._draw_footprint(painter, marker, QPen(_BOUNDING_BOX, 1.5), 0.0)
            if influences is not None and options.show_sight_ranges:
                sight = influences.sight_range(obj.type_name)
                if sight is not None:
                    painter.setPen(QPen(_SIGHT, 1))
                    self.world_circle(painter, marker.x, marker.y, sight)
            if influences is not None and options.show_weapon_ranges:
                reach = influences.weapon_range(obj.type_name)
                if reach is not None:
                    painter.setPen(QPen(_WEAPON, 1))
                    self.world_circle(painter, marker.x, marker.y, reach)
            if options.show_sound_circles:
                ranges = sound_ranges(obj)
                if ranges is not None:
                    minimum, maximum = ranges
                    painter.setPen(QPen(_SOUND, 1))
                    self.world_circle(painter, marker.x, marker.y, maximum)
                    if minimum > 0:
                        painter.setPen(QPen(_SOUND, 1, Qt.PenStyle.DashLine))
                        self.world_circle(painter, marker.x, marker.y, minimum)

    def _draw_footprint(
        self,
        painter: QPainter,
        marker: Marker,
        pen: QPen | None = None,
        minimum_pixels: float = _FOOTPRINT_MIN_PIXELS,
    ) -> None:
        """The ground the object covers, once it is at least `minimum_pixels` across."""
        footprint = self.footprints.get(marker.source.type_name) if self.footprints else None
        if footprint is None or footprint.major * self.transform.scale < minimum_pixels:
            return
        painter.setPen(pen if pen is not None else QPen(_FOOTPRINT, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if footprint.shape is FootprintShape.CIRCLE:
            self._world_circle(painter, marker.x, marker.y, footprint.major)
            return
        cos, sin = math.cos(marker.angle), math.sin(marker.angle)
        corners = [
            (
                marker.x + along * footprint.major * cos - across * footprint.minor * sin,
                marker.y + along * footprint.major * sin + across * footprint.minor * cos,
            )
            for along, across in ((1, 1), (1, -1), (-1, -1), (-1, 1))
        ]
        path = self._screen_path(corners, closed=True)
        if path is not None:
            painter.drawPolygon(QPolygonF(path))
