"""The 3D view's stand-in for `ViewTransform`: the conversions between world positions and widget
pixels a tool uses, answered by the camera and the terrain under it.

A world position `(x, y)` is taken on the ground: `world_to_screen` projects the terrain height
there, and `screen_to_world` is where the ray under the pixel meets the terrain. Where the ray
misses the heightmap it meets the level plane at the last height it hit, as WorldBuilder's
`WbView3d::viewToDocCoords` does. `scale`, pixels per world unit, depends on distance in 3D; it is
taken at the ground the cursor last pointed at, which is where a tool measures a pick radius or a
brush.

`ground_path` is what the view's overlays draw their outlines from: an outline follows the ground
between its corners, and where it passes behind the camera it is cut at the near plane instead of
dropped, so an outline the camera stands inside, the map's boundary above all, keeps the part of
it that is in view.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from sage_worldbuilder.camera import Camera, Projector
from sage_worldbuilder.terrain import WORLD_UNITS_PER_CELL
from sage_worldbuilder.terrain.grid import TerrainGrid
from sage_worldbuilder.terrain.surface import ground_height, ground_heights, ray_hit

__all__ = ["DRAPE_STEP", "MAX_DRAPE_POINTS", "OFF_SCREEN", "CameraProjection"]

# Where `world_to_screen` puts a point behind the camera: far outside any widget.
OFF_SCREEN = (-1.0e5, -1.0e5)
# How far apart `ground_path` samples the ground along an edge, and the most samples an edge gets.
DRAPE_STEP = 2 * WORLD_UNITS_PER_CELL
MAX_DRAPE_POINTS = 400
# How far a clipped corner is allowed to land from the widget: the near plane turns a point just
# in front of the camera into a huge pixel, and a painter wants a number it can still draw with.
_FAR_PIXELS = 1.0e6
# How far above the ground `height_direction` looks to find which way height goes on screen.
_HEIGHT_PROBE = 50.0


class CameraProjection:
    def __init__(self, camera: Camera, grid: TerrainGrid | None = None) -> None:
        self.camera = camera
        self.grid = grid
        # The ground point `(x, y, z)` the last `screen_to_world` found, or None.
        self.focus: tuple[float, float, float] | None = None
        self._projector: Projector | None = None

    def moved(self) -> None:
        """The camera changed: forget the cached projection."""
        self._projector = None

    @property
    def width(self) -> int:
        return self.camera.width

    @property
    def height(self) -> int:
        return self.camera.height

    @property
    def center_x(self) -> float:
        return self.camera.target_x

    @property
    def center_y(self) -> float:
        return self.camera.target_y

    def ground(self, x: float, y: float) -> float:
        return ground_height(self.grid, x, y) if self.grid is not None else 0.0

    def project(self, x: float, y: float, z: float | None = None) -> tuple[float, float] | None:
        """Pixels for a world point (on the ground when `z` is None), or None behind the camera."""
        if self._projector is None:
            self._projector = self.camera.projector()
        return self._projector(x, y, self.ground(x, y) if z is None else z)

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return self.project(x, y) or OFF_SCREEN

    @property
    def scale(self) -> float:
        camera = self.camera
        point = self.focus or (camera.target_x, camera.target_y, camera.target_z)
        return camera.pixels_per_unit_at(point)

    def hit(self, sx: float, sy: float) -> tuple[float, float, float]:
        """The ground point under a pixel. A ray that misses the heightmap and never comes down
        to the fallback plane gives the camera's target."""
        camera = self.camera
        origin, direction = camera.ray(sx, sy)
        found = ray_hit(self.grid, origin, direction) if self.grid is not None else None
        if found is None:
            plane = self.focus[2] if self.focus is not None else camera.target_z
            t = (plane - origin[2]) / direction[2] if direction[2] < -1e-9 else -1.0
            if t < 0:
                return camera.target_x, camera.target_y, camera.target_z
            point = origin + t * direction
            found = (float(point[0]), float(point[1]), plane)
        self.focus = found
        return found

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        x, y, _ = self.hit(sx, sy)
        return x, y

    def height_direction(self, x: float, y: float) -> tuple[float, float]:
        """Which way a rise in height goes on screen here, as a unit vector in pixels: the camera
        never rolls, so it is close to straight up, and that is what a point above the ground is
        taken to say when it cannot be projected."""
        ground = self.project(x, y)
        above = self.project(x, y, self.ground(x, y) + _HEIGHT_PROBE)
        if ground is None or above is None:
            return (0.0, -1.0)
        dx, dy = above[0] - ground[0], above[1] - ground[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 1e-6 else (0.0, -1.0)

    def visible_world(self) -> tuple[float, float, float, float]:
        """A world rectangle holding everything that can be in view: the whole heightmap."""
        grid = self.grid
        if grid is None:
            reach = self.camera.distance * 4
            return (
                self.camera.target_x - reach,
                self.camera.target_y - reach,
                self.camera.target_x + reach,
                self.camera.target_y + reach,
            )
        x0, y0 = grid.cell_to_world(0, 0)
        x1, y1 = grid.cell_to_world(grid.width - 1, grid.height - 1)
        return x0, y0, x1, y1

    def ground_path(
        self, points: Sequence[tuple[float, float]], closed: bool = False
    ) -> list[tuple[float, float]]:
        """An outline's world positions as pixels, the ground between them followed and the runs
        behind the camera cut off at the near plane.

        A ground outline reaching past the camera would lose every one of its corners to
        `project`, and with them the whole outline; cutting it instead keeps the part in view and
        sends the rest off the widget, where the clipped corners project to.
        """
        count = len(points)
        if count == 0:
            return []
        if count == 1:
            alone = self.project(*points[0])
            return [alone] if alone is not None else []
        samples = self._drape(points, closed)
        camera = self.camera
        right, up, forward = camera.basis()
        relative = samples - camera.eye
        depth, across, upward = relative @ forward, relative @ right, relative @ up
        near = camera.clip_planes()[0]
        in_front = depth > near
        focal, cx, cy = camera.focal_pixels(), camera.width / 2, camera.height / 2

        def pixel(index: int) -> tuple[float, float]:
            k = focal / depth[index]
            return _on_widget(cx + across[index] * k, cy - upward[index] * k)

        def crossing(before: int, after: int) -> tuple[float, float]:
            """Where the edge meets the near plane, at the depth the camera still draws."""
            t = (near - depth[before]) / (depth[after] - depth[before])
            k = focal / near
            return _on_widget(
                cx + (across[before] + t * (across[after] - across[before])) * k,
                cy - (upward[before] + t * (upward[after] - upward[before])) * k,
            )

        path: list[tuple[float, float]] = []
        total = len(samples)
        edges = total if closed else total - 1
        for index in range(edges):
            after = (index + 1) % total
            if index == 0 and not closed and in_front[index]:
                path.append(pixel(index))
            if in_front[index] != in_front[after]:
                path.append(crossing(index, after))
            if in_front[after]:
                path.append(pixel(after))
        return path

    def _drape(self, points: Sequence[tuple[float, float]], closed: bool) -> np.ndarray:
        """The outline's corners with the ground sampled along each edge, as world points."""
        xs: list[float] = []
        ys: list[float] = []
        count = len(points)
        for index in range(count if closed else count - 1):
            (ax, ay), (bx, by) = points[index], points[(index + 1) % count]
            steps = max(1, min(int(math.hypot(bx - ax, by - ay) / DRAPE_STEP), MAX_DRAPE_POINTS))
            for step in range(steps):
                t = step / steps
                xs.append(ax + (bx - ax) * t)
                ys.append(ay + (by - ay) * t)
        if not closed:
            xs.append(points[-1][0])
            ys.append(points[-1][1])
        x, y = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
        z = ground_heights(self.grid, x, y) if self.grid is not None else np.zeros_like(x)
        return np.stack((x, y, z), axis=1)


def _on_widget(x: float, y: float) -> tuple[float, float]:
    """A pixel a painter can draw with, however far off the widget it is."""
    return (
        float(min(max(x, -_FAR_PIXELS), _FAR_PIXELS)),
        float(min(max(y, -_FAR_PIXELS), _FAR_PIXELS)),
    )
