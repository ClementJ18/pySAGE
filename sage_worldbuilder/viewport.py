"""What a map view shows and where it looks, independent of the widget that draws it.

`ViewTransform` maps world positions (y up) to widget pixels (y down) and back, so tools can work
in world units whatever draws the map. `ViewOptions` are the View menu's toggles and the grid.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from typing import Any

from sage_worldbuilder.scene import MarkerKind

__all__ = [
    "PARTIAL_MAP_SIZES",
    "ContourOptions",
    "GridSettings",
    "ViewOptions",
    "ViewTransform",
    "letterbox_band",
    "safe_frame",
    "snap",
]

MIN_SCALE = 0.005
MAX_SCALE = 20.0
# Partial Map Size: the cells across the 3D view draws about its target when it does not
# draw the whole map, the values WorldBuilder's four menu handlers store (0x00662830-0x00662BF0).
PARTIAL_MAP_SIZES = (97, 129, 161, 192)
# The frames the 3D view can draw over itself: 16:9 inside the view, and the safe frame's 4:3.
WIDESCREEN = 0.5625
SAFE_FRAME_ASPECT = 1.3333


@dataclass
class GridSettings:
    """WorldBuilder's Grid Settings dialog: spacing in world units, snapping, and whether the
    lines start at the world origin."""

    spacing: float = 100.0
    snap: bool = False
    justify_to_origin: bool = True


@dataclass
class ContourOptions:
    """WorldBuilder's Contour Options: how many lines, how far (feet) they are moved from being
    spread evenly over the map's heights, and how thick they are drawn, in cells."""

    count: int = 10
    offset: float = 0.0
    width: int = 1


@dataclass
class ViewOptions:
    show_grid: bool = False
    show_contours: bool = False
    show_impassable: bool = False
    show_blends: bool = False
    show_stretched: bool = False
    show_unblended: bool = False
    # Show Stretched Tiles marks cells steeper than this, in degrees.
    stretched_threshold: float = 45.0
    show_texture: bool = True
    show_objects: bool = True
    show_waypoints: bool = True
    show_areas: bool = True
    show_roads: bool = True
    show_water: bool = True
    show_labels: bool = False
    show_boundaries: bool = True
    # The influence views: every object's footprint, and circles of how far it sees, how far its
    # weapons reach, and its ambient sound's ranges.
    show_bounding_boxes: bool = False
    show_sight_ranges: bool = False
    show_weapon_ranges: bool = False
    show_sound_circles: bool = False
    # A flag on every audio object, blue, or cyan for an ambient stream.
    show_sound_flags: bool = False
    # Objects show their GARRISONED condition state's model.
    show_garrisoned: bool = False
    # The 3D view: black bars cutting the picture to 16:9, and the safe frame - a 4:3 outline a
    # share of the view wide, marked with the 16:9 frame inside it.
    show_letterbox: bool = False
    show_safe_frame: bool = False
    safe_frame_scale: float = 0.6
    # Which view the central area opens in: the 3D view, or the top-down view. The editor
    # remembers the one last shown, so this is the choice for a first run.
    view_3d: bool = True
    # The 3D view: lines instead of surfaces, and all of the map or only Partial Map Size
    # cells about the camera's target.
    wireframe: bool = False
    # Objects show their WORLD_BUILDER condition state's model when they have one.
    world_builder_models: bool = True
    # A dot at the centre of every object. The 3D view draws it smaller, over the model, since
    # it is what a click picks the object by; turning this off leaves an object with a model to
    # draw with no dot, and one with none to draw still keeps its dot.
    show_object_dots: bool = True
    show_entire_map: bool = True
    partial_map_size: int = PARTIAL_MAP_SIZES[0]
    reverse_scroll: bool = False
    grid: GridSettings | None = None
    contours: ContourOptions | None = None

    def __post_init__(self) -> None:
        if self.grid is None:
            self.grid = GridSettings()
        if self.contours is None:
            self.contours = ContourOptions()

    def shows(self, kind: MarkerKind) -> bool:
        """Whether the View menu shows markers of a kind; a hidden kind cannot be picked."""
        if kind is MarkerKind.WAYPOINT:
            return self.show_waypoints
        if kind is MarkerKind.ROAD:
            return self.show_roads
        return self.show_objects

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> ViewOptions:
        options = cls()
        if not isinstance(data, dict):
            return options
        for field in fields(cls):
            value = data.get(field.name)
            if field.name in ("grid", "contours"):
                continue
            if isinstance(value, bool):
                setattr(options, field.name, value)
        grid = data.get("grid")
        if isinstance(grid, dict):
            assert options.grid is not None
            spacing = grid.get("spacing")
            if isinstance(spacing, (int, float)) and not isinstance(spacing, bool) and spacing > 0:
                options.grid.spacing = float(spacing)
            for name in ("snap", "justify_to_origin"):
                if isinstance(grid.get(name), bool):
                    setattr(options.grid, name, grid[name])
        contours = data.get("contours")
        if isinstance(contours, dict):
            assert options.contours is not None
            count, offset, width = (contours.get(name) for name in ("count", "offset", "width"))
            if isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 100:
                options.contours.count = count
            if isinstance(offset, (int, float)) and not isinstance(offset, bool):
                options.contours.offset = float(offset)
            if isinstance(width, int) and not isinstance(width, bool) and 1 <= width <= 10:
                options.contours.width = width
        threshold = data.get("stretched_threshold")
        if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
            options.stretched_threshold = min(max(float(threshold), 0.0), 90.0)
        size = data.get("partial_map_size")
        if isinstance(size, int) and not isinstance(size, bool) and size in PARTIAL_MAP_SIZES:
            options.partial_map_size = size
        return options


def snap(value: float, spacing: float, origin: float = 0.0) -> float:
    """`value` moved to the nearest grid line of `spacing` through `origin`."""
    return origin + round((value - origin) / spacing) * spacing


# Half a turn of a square's diagonal: the screen slant a height handle takes in a top-down
# view, where height itself has no direction.
_DIAGONAL = math.sqrt(0.5)


@dataclass
class ViewTransform:
    """A view of the world centred on `center`, at `scale` pixels per world unit, in a widget of
    `width` x `height` pixels."""

    center_x: float = 0.0
    center_y: float = 0.0
    scale: float = 0.2
    width: int = 1
    height: int = 1

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.width / 2 + (x - self.center_x) * self.scale,
            self.height / 2 - (y - self.center_y) * self.scale,
        )

    def scale_at(self, x: float, y: float) -> float:
        """Pixels a world unit spans at a place on the map: the same everywhere from above."""
        return self.scale

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (
            self.center_x + (sx - self.width / 2) / self.scale,
            self.center_y - (sy - self.height / 2) / self.scale,
        )

    def height_direction(self, x: float, y: float) -> tuple[float, float]:
        """Which way a rise in height goes on screen, as a unit vector in pixels.

        Looking straight down, height has no direction of its own, and up the screen is already
        where the world's +Y goes; a height handle leans up and to the left instead, so it cannot
        lie under the Y one."""
        return (-_DIAGONAL, -_DIAGONAL)

    def visible_world(self) -> tuple[float, float, float, float]:
        """The world rectangle in the widget: `(x0, y0, x1, y1)` with x0 < x1 and y0 < y1."""
        x0, y1 = self.screen_to_world(0, 0)
        x1, y0 = self.screen_to_world(self.width, self.height)
        return x0, y0, x1, y1

    def pan_pixels(self, dx: float, dy: float) -> None:
        """Move the picture by a mouse drag of `dx`, `dy` pixels."""
        self.center_x -= dx / self.scale
        self.center_y += dy / self.scale

    def zoom_at(self, sx: float, sy: float, factor: float) -> None:
        """Zoom by `factor`, keeping the world point under pixel `sx`, `sy` where it is."""
        wx, wy = self.screen_to_world(sx, sy)
        self.scale = min(MAX_SCALE, max(MIN_SCALE, self.scale * factor))
        nx, ny = self.screen_to_world(sx, sy)
        self.center_x += wx - nx
        self.center_y += wy - ny

    def center_on(self, x: float, y: float) -> None:
        self.center_x, self.center_y = x, y

    def fit(self, x0: float, y0: float, x1: float, y1: float, margin: float = 0.05) -> None:
        """Show the world rectangle whole, centred, with a `margin` fraction around it."""
        span_x, span_y = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        scale = min(self.width / span_x, self.height / span_y) * (1 - 2 * margin)
        self.scale = min(MAX_SCALE, max(MIN_SCALE, scale))
        self.center_on((x0 + x1) / 2, (y0 + y1) / 2)

    def grid_lines(self, spacing: float, origin: float = 0.0) -> tuple[list[float], list[float]]:
        """World x and y of the grid lines in view, or none when they would be under 4 pixels
        apart."""
        if spacing <= 0 or spacing * self.scale < 4:
            return [], []
        x0, y0, x1, y1 = self.visible_world()

        def lines(low: float, high: float) -> list[float]:
            first = math.ceil((low - origin) / spacing)
            last = math.floor((high - origin) / spacing)
            return [origin + index * spacing for index in range(first, last + 1)]

        return lines(x0, x1), lines(y0, y1)


def letterbox_band(width: int, height: int) -> int:
    """How tall each of Show Letterbox's two black bars is: what a 16:9 picture as wide as the
    view leaves above and below it (`worldbuilder.exe` `0x004E43DF`), none in a wider view."""
    return max(int((height - width * WIDESCREEN) * 0.5), 0)


def safe_frame(width: int, height: int, scale: float) -> tuple[int, int, int, int, int]:
    """The safe frame (`0x0065E1D0`): a 4:3 rectangle `scale` of the view wide, centred, as
    (left, top, width, height), and the height of the band at its top and bottom that leaves
    the 16:9 frame inside it."""
    frame_width = int(width * scale)
    frame_height = int(frame_width / SAFE_FRAME_ASPECT)
    band = int((frame_height - frame_width * WIDESCREEN) * 0.5)
    left = (width - frame_width) // 2
    top = (height - frame_height) // 2
    return left, top, frame_width, frame_height, band
