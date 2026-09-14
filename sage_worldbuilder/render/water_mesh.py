"""Water areas as the 3D view draws them: a surface at the area's own height, and how it looks.

A water height is the world height, in feet, of the surface: the terrain around corpus lakes and
rivers agrees (PHASE5.md, R10).

- A lake or ocean is built as the game builds it (`RenderableStandingWaterArea::
  AllocateAndFillBuffers`, `0x0073FBA0` in `worldbuilder.exe`): a grid of 20 world-unit cells over
  the outline's bounds, the cell size doubled until the grid has at most 60,000 points, and two
  triangles for each cell whose centre is inside the outline, all at the water height. Its
  vertices carry only a position, so the texture is laid over it in world space.
- A river is a strip: each bank line (left, right) is a row of two vertices, and consecutive rows
  make two triangles. Across the river the texture runs from 0 at the left bank to 1 at the right,
  which is how its opacity texture fades at both banks (`TWAlphaEdge.tga` is clear at both ends of
  its x); along it, one repeat per river width.

The game draws lakes with the FX shader named by the area (`WaterShader.FX`: bump, environment and
wave textures over a diffuse colour) and rivers with `RiverWater.fx` (its `RiverTexture`,
`NoiseTexture`, `OpacityTexture` and `SparklesTexture` slots, an opacity, a UV scroll and additive
blending). A view gives a still picture of them, `WaterLook`: a lake shows its material's diffuse
colour with its environment texture added at the material's reflection strength, growing opaque
with depth up to the map's Max alpha depth but never more transparent than its Deep water alpha;
a river shows its own texture in its colour, faded by its opacity texture and alpha.

Those two map values are the engine's `WaterTransparency` block, which a map overrides: the
`EnvironmentData` chunk holds the same pair of floats the block seeds (`0x0046c62c` copies
`TransparentWaterDepth` from the block's `+0x18` and `TransparentWaterMinOpacity` from its `+0x1c`
into the fields the chunk reads at `0x004adcb9` and writes at `0x00467c56`). So Deep water alpha
is a floor under the opacity, not a factor over it: stock `water.ini` sets it to 1.0, which makes
standing water opaque whatever its depth.
The lake's texture scale is a choice; the game's shaders are not read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sage_map.assets.environment_data import EnvironmentData
    from sage_map.assets.river_areas import RiverArea
    from sage_map.assets.standing_water_area import StandingWaterArea
    from sage_worldbuilder.terrain import TerrainGrid

__all__ = [
    "LAKE_CELL",
    "MAX_LAKE_POINTS",
    "WaterLook",
    "WaterMesh",
    "lake_look",
    "lake_mesh",
    "river_look",
    "river_mesh",
]

LAKE_CELL = 20.0
MAX_LAKE_POINTS = 60_000
# A lake without a readable FX material: a clear blue.
_PLAIN_WATER = (0.24, 0.47, 0.72, 0.6)
# The environment texture's world scale at the materials' usual EnvUVScale of 0.2: one repeat
# every 100 world units, five lake grid cells.
_ENV_UNITS_PER_SCALE = LAKE_CELL


@dataclass(frozen=True, eq=False)
class WaterMesh:
    """`(N, 3)` positions, `(N, 2)` texture coordinates and `(N,)` water depths (the water height
    above the ground there, never below 0) as `float32`, and `uint32` triangle indices."""

    positions: np.ndarray
    uvs: np.ndarray
    depths: np.ndarray
    indices: np.ndarray


@dataclass(frozen=True)
class WaterLook:
    # The tiled texture (by name) and a texture whose alpha fades it, or None.
    texture: str | None
    opacity_texture: str | None
    # Multiplies the texture, or is the colour without one; RGBA 0-1.
    color: tuple[float, float, float, float]
    # Texture repeats per texture coordinate unit.
    uv_scale: float
    additive: bool
    # A lake's reflection strength: its environment texture is added over the colour at this
    # strength. None multiplies the colour by the texture instead, as a river's is.
    reflection: float | None
    # (Max alpha depth in feet, deep water alpha) for a lake, or None for a fixed alpha. The
    # map's two `WaterTransparency` values: the depth at which water is opaque, and the opacity
    # it never falls below, so water shallower than that depth still shows.
    depth_alpha: tuple[float, float] | None


def _depths(grid: TerrainGrid | None, xs: np.ndarray, ys: np.ndarray, height: float) -> np.ndarray:
    if grid is None:
        return np.full(xs.shape, np.float32(1e6), dtype=np.float32)
    from sage_worldbuilder.terrain.surface import ground_heights  # noqa: PLC0415

    return np.maximum(height - ground_heights(grid, xs, ys), 0.0).astype(np.float32)


def _inside(outline: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Which points are inside a polygon, by the even-odd rule, as `areas.area_contains` decides
    one point."""
    inside = np.zeros(xs.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(outline, np.roll(outline, -1, axis=0), strict=True):
        if y1 == y2:
            continue
        crosses = (y1 > ys) != (y2 > ys)
        edge_x = (x2 - x1) * (ys - y1) / (y2 - y1) + x1
        inside ^= crosses & (xs < edge_x)
    return inside


def lake_mesh(
    points: Sequence[tuple[float, float]],
    height: float,
    grid: TerrainGrid | None = None,
    cell: float = LAKE_CELL,
    max_points: int = MAX_LAKE_POINTS,
) -> WaterMesh | None:
    """A lake's surface, or None for an outline of fewer than three points or with no cell centre
    inside it."""
    if len(points) < 3:
        return None
    outline = np.asarray(points, dtype=np.float64)
    x0, y0 = (np.floor(outline.min(axis=0) / cell) * cell).tolist()
    x1, y1 = outline.max(axis=0).tolist()
    while True:
        columns = int(np.floor((x1 - x0) / cell)) + 1
        rows = int(np.floor((y1 - y0) / cell)) + 1
        if (columns + 1) * (rows + 1) <= max_points:
            break
        cell *= 2
    centres_x = x0 + (np.arange(columns) + 0.5) * cell
    centres_y = y0 + (np.arange(rows) + 0.5) * cell
    inside = _inside(outline, *np.meshgrid(centres_x, centres_y))
    if not inside.any():
        return None
    corner_x = x0 + np.arange(columns + 1) * cell
    corner_y = y0 + np.arange(rows + 1) * cell
    grid_x, grid_y = np.meshgrid(corner_x, corner_y)
    xs, ys = grid_x.ravel(), grid_y.ravel()
    positions = np.column_stack((xs, ys, np.full(xs.shape, float(height)))).astype(np.float32)
    uvs = np.column_stack((xs, ys)).astype(np.float32)
    row, column = np.nonzero(inside)
    stride = columns + 1
    a = row * stride + column
    b, c, d = a + 1, a + stride, a + stride + 1
    indices = np.column_stack((a, b, d, a, d, c)).ravel().astype(np.uint32)
    depths = _depths(grid, xs, ys, float(height))
    return WaterMesh(positions, uvs, depths, indices)


def river_mesh(
    lines: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    height: float,
    grid: TerrainGrid | None = None,
) -> WaterMesh | None:
    """A river's strip, or None for a river of fewer than two bank lines."""
    if len(lines) < 2:
        return None
    left = np.asarray([line[0] for line in lines], dtype=np.float64)
    right = np.asarray([line[1] for line in lines], dtype=np.float64)
    widths = np.linalg.norm(right - left, axis=1)
    width = float(widths.mean()) if widths.mean() > 0 else 1.0
    centres = (left + right) / 2
    steps = np.linalg.norm(np.diff(centres, axis=0), axis=1)
    along = np.concatenate(([0.0], np.cumsum(steps))) / width
    count = len(lines)
    xs = np.column_stack((left[:, 0], right[:, 0])).ravel()
    ys = np.column_stack((left[:, 1], right[:, 1])).ravel()
    positions = np.column_stack((xs, ys, np.full(xs.shape, float(height)))).astype(np.float32)
    uvs = np.column_stack((np.tile([0.0, 1.0], count), np.repeat(along, 2))).astype(np.float32)
    a = np.arange(count - 1) * 2
    indices = np.column_stack((a, a + 1, a + 3, a, a + 3, a + 2)).ravel().astype(np.uint32)
    depths = _depths(grid, xs, ys, float(height))
    return WaterMesh(positions, uvs, depths, indices)


def _floats(value: object, count: int) -> tuple[float, ...] | None:
    if isinstance(value, (tuple, list)) and len(value) >= count:
        try:
            return tuple(float(part) for part in value[:count])
        except (TypeError, ValueError):
            return None
    return None


def lake_look(
    area: StandingWaterArea,
    material: Mapping[str, object] | None,
    environment: EnvironmentData | None,
) -> WaterLook:
    """How a lake is drawn from its FX material's properties (lower-case names, as the model's
    `ShaderMaterials` store them), or plain water without one."""
    texture = material.get("waterenvtexture") if material else None
    diffuse = _floats(material.get("materialcolordiffuse"), 4) if material else None
    scale = _floats(material.get("envuvscale"), 1) if material else None
    reflection = material.get("reflectionstrength") if material else None
    color = diffuse if diffuse is not None else _PLAIN_WATER
    depth = environment.water_max_alpha_depth if environment is not None else None
    deep = environment.deep_water_alpha if environment is not None else None
    return WaterLook(
        texture=texture if isinstance(texture, str) and texture else None,
        opacity_texture=None,
        color=(color[0], color[1], color[2], color[3]),
        uv_scale=(scale[0] if scale else 0.2) / _ENV_UNITS_PER_SCALE,
        additive=False,
        reflection=float(reflection) if isinstance(reflection, (int, float)) else 0.4,
        depth_alpha=(float(depth), float(deep)) if depth is not None and deep is not None else None,
    )


def river_look(area: RiverArea) -> WaterLook:
    red, green, blue = area.color
    return WaterLook(
        texture=area.river_texture or None,
        opacity_texture=area.alpha_edge_texture or None,
        color=(red / 255, green / 255, blue / 255, float(area.alpha)),
        uv_scale=1.0,
        additive=bool(area.use_additive_blending),
        reflection=None,
        depth_alpha=None,
    )
