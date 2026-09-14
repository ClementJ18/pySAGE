"""Roads as ground the 3D view can draw: `road_mesh`'s pieces cut up to follow the terrain.

A piece is a quadrilateral on flat ground, so it is divided into a grid fine enough that its
corners sit on the heightmap and its middle does not sink into a slope, and every sample is lifted
`ROAD_LIFT` above the ground. That lift is the game's own: its road vertices take the terrain
height plus `0.078125` (`game.dat` `0x004D7CF9`), two heightmap units.

Texture coordinates come with the pieces (`road_mesh`), and pieces sharing a texture are gathered
into one surface, so a map's roads draw in as many passes as it has road textures. A road type
the game data does not name, and every bridge, has no texture and makes a surface of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from sage_worldbuilder.road_mesh import RoadPiece
from sage_worldbuilder.roads import RoadStyle
from sage_worldbuilder.terrain import WORLD_UNITS_PER_CELL
from sage_worldbuilder.terrain.grid import TerrainGrid
from sage_worldbuilder.terrain.surface import ground_heights

__all__ = ["ROAD_LIFT", "RoadSurface", "road_surfaces"]

ROAD_LIFT = 0.078125
# World units between the samples a piece is cut at, and the most cuts one of its sides takes.
_STEP = WORLD_UNITS_PER_CELL / 2
_MAX_STEPS = 64


@dataclass(frozen=True, eq=False)
class RoadSurface:
    """The roads drawn with one texture: `(N, 3)` positions and `(N, 2)` texture coordinates as
    `float32`, and `uint32` triangle indices. `texture` is None for a road drawn without one."""

    texture: str | None
    bridge: bool
    positions: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray


def _steps(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> int:
    """How many cuts a pair of opposite sides takes to keep each piece of them under `_STEP`."""
    longest = max(float(np.linalg.norm(b - a)), float(np.linalg.norm(c - d)))
    return int(min(max(round(longest / _STEP), 1), _MAX_STEPS))


def _piece_grid(piece: RoadPiece) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One piece cut into a grid: its samples' positions on flat ground, their texture coordinates,
    and the triangles over them, numbered from zero."""
    corners = np.asarray(piece.corners, dtype=np.float64)
    uvs = np.asarray(piece.uvs, dtype=np.float64)
    along = _steps(corners[0], corners[1], corners[2], corners[3])
    across = _steps(corners[0], corners[3], corners[2], corners[1])
    s = np.linspace(0.0, 1.0, along + 1)[None, :, None]
    t = np.linspace(0.0, 1.0, across + 1)[:, None, None]
    # The corners run start left, end left, end right, start right: `s` runs along the road from
    # the first side to the second, `t` across it from the left side to the right.
    left = corners[0] * (1 - s) + corners[1] * s
    right = corners[3] * (1 - s) + corners[2] * s
    points = (left * (1 - t) + right * t).reshape(-1, 2)
    left_uv = uvs[0] * (1 - s) + uvs[1] * s
    right_uv = uvs[3] * (1 - s) + uvs[2] * s
    coordinates = (left_uv * (1 - t) + right_uv * t).reshape(-1, 2)
    stride = along + 1
    first = (np.arange(across)[:, None] * stride + np.arange(along)[None, :]).ravel()
    second, third, fourth = first + 1, first + stride, first + stride + 1
    triangles = np.column_stack((first, second, fourth, first, fourth, third)).ravel()
    return points, coordinates, triangles


def road_surfaces(
    pieces: Sequence[RoadPiece], style: Callable[[str], RoadStyle], grid: TerrainGrid | None
) -> list[RoadSurface]:
    """The pieces draped over the terrain, gathered by the texture they are drawn with. Without a
    `grid` the roads lie flat at height zero."""
    gathered: dict[tuple[str | None, bool], list[tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
    for piece in pieces:
        look = style(piece.segment.type_name)
        texture = None if look.bridge or piece.segment.bridge else look.texture
        gathered.setdefault((texture, piece.segment.bridge), []).append(_piece_grid(piece))
    surfaces = []
    for (texture, bridge), grids in gathered.items():
        offsets = np.cumsum([0, *(len(points) for points, _, _ in grids)])
        points = np.concatenate([points for points, _, _ in grids])
        coordinates = np.concatenate([uvs for _, uvs, _ in grids])
        indices = np.concatenate(
            [triangles + offset for (_, _, triangles), offset in zip(grids, offsets, strict=False)]
        )
        xs, ys = points[:, 0], points[:, 1]
        heights = ground_heights(grid, xs, ys) if grid is not None else np.zeros_like(xs)
        positions = np.column_stack((xs, ys, heights + ROAD_LIFT)).astype(np.float32)
        surfaces.append(
            RoadSurface(
                texture,
                bridge,
                positions,
                coordinates.astype(np.float32),
                indices.astype(np.uint32),
            )
        )
    return surfaces
