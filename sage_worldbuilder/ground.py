"""Adjust Terrain to GROUND Objects: the ground takes the shape of the objects standing on it.

WorldBuilder's Edit > Special > Adjust Terrain to GROUND Objects (33402, `0x0042F0D0`, behind
"This changes the terrain height of the current map. Do you really want to do this?") walks every
object whose model has sub-objects named `*.GROUND`, casts a ray straight down at each heightmap
sample, and where the highest hit is above zero sets the sample to the hit in feet over the stored
unit, rounded (`floor(z / 0.0390625 + 0.5)`). 92 of the install's 20,169 models have such meshes:
fortresses, gates, mines and altars, whose models carry the flat pad they are meant to sit on.

WorldBuilder then moves the objects standing on the cells it changed. Here an object's stored z is
already its height above the ground, so nothing moves: a deviation.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from sage_worldbuilder.dressing import highest_hits
from sage_worldbuilder.render.model_mesh import object_scale
from sage_worldbuilder.scene import WAYPOINT_PREFIX
from sage_worldbuilder.terrain.grid import (
    FEET_PER_HEIGHT_UNIT,
    MAX_HEIGHT,
    WORLD_UNITS_PER_CELL,
    TerrainGrid,
)

if TYPE_CHECKING:
    from sage_map.map import Map
    from sage_worldbuilder.models import ArtIndex, ObjectModels

__all__ = [
    "GROUND_SUFFIX",
    "GroundPlacement",
    "adjust_heights",
    "ground_placements",
    "ground_triangles",
    "load_ground_triangles",
]

GROUND_SUFFIX = ".GROUND"


def ground_triangles(scene: Any) -> np.ndarray:
    """The triangles of a built model's `.GROUND` meshes, in model space, as `(T, 3, 3)` floats."""
    triangles = []
    for mesh in getattr(scene, "meshes", None) or []:
        if GROUND_SUFFIX not in str(getattr(mesh, "name", "")).upper():
            continue
        positions = np.asarray(mesh.positions, dtype=np.float64).reshape(-1, 3)
        indices = np.asarray(mesh.indices, dtype=np.int64).reshape(-1, 3)
        if len(positions) and len(indices) and indices.max() < len(positions):
            triangles.append(positions[indices])
    return np.concatenate(triangles) if triangles else np.zeros((0, 3, 3))


def load_ground_triangles(
    names: Iterable[str], models: ObjectModels, art: ArtIndex
) -> dict[str, np.ndarray]:
    """Each object name's `.GROUND` triangles; a name whose model has none, or cannot be read, is
    left out."""
    from sage_w3d.render.scene import build_scene  # noqa: PLC0415 - lazy: parsing is on demand

    found: dict[str, np.ndarray] = {}
    for name in names:
        if name in found:
            continue
        chosen = models.get(name)
        try:
            model = art.find_model(chosen.model) if chosen is not None else None
            triangles = (
                ground_triangles(build_scene(model, art, chosen.skeleton))
                if model is not None and chosen is not None
                else np.zeros((0, 3, 3))
            )
        except Exception:  # noqa: BLE001 - one unreadable model must not lose the rest
            continue
        if len(triangles):
            found[name] = triangles
    return found


@dataclass(frozen=True)
class GroundPlacement:
    """One object's ground shape where it stands: its position, facing and scale, and the
    triangles of its model's `.GROUND` meshes in model space."""

    x: float
    y: float
    z: float
    angle: float
    scale: float
    triangles: np.ndarray


def ground_placements(map: Map, triangles: Mapping[str, np.ndarray]) -> list[GroundPlacement]:
    """Where each of the map's objects lays ground, for the models `triangles` knows."""
    objects = map.objects_list.object_list if map.objects_list is not None else []
    placements = []
    for obj in objects:
        found = triangles.get(obj.type_name)
        if found is None or obj.type_name.startswith(WAYPOINT_PREFIX):
            continue
        x, y, z = obj.position
        placements.append(GroundPlacement(x, y, z, obj.angle, object_scale(obj), found))
    return placements


def _reach(placement: GroundPlacement) -> float:
    return (
        float(np.hypot(placement.triangles[..., 0], placement.triangles[..., 1]).max())
        * placement.scale
    )


def _box(grid: TerrainGrid, placement: GroundPlacement) -> tuple[int, int, int, int] | None:
    cells = _reach(placement) / WORLD_UNITS_PER_CELL
    cx, cy = grid.world_to_cell(placement.x, placement.y)
    x0, y0 = max(0, math.floor(cx - cells)), max(0, math.floor(cy - cells))
    x1 = min(grid.width - 1, math.ceil(cx + cells))
    y1 = min(grid.height - 1, math.ceil(cy + cells))
    return (x0, y0, x1, y1) if x0 <= x1 and y0 <= y1 else None


def adjust_heights(
    grid: TerrainGrid, placements: Sequence[GroundPlacement]
) -> tuple[int, int, np.ndarray] | None:
    """The heights the placements give the map: `(x0, y0, values)` for `PatchHeights`, or None
    when no sample changes. A sample takes the highest ground above it, and keeps its height where
    nothing lays ground above zero."""
    boxes = [(placement, box) for placement in placements if (box := _box(grid, placement))]
    if not boxes:
        return None
    x0 = min(box[0] for _, box in boxes)
    y0 = min(box[1] for _, box in boxes)
    x1 = max(box[2] for _, box in boxes)
    y1 = max(box[3] for _, box in boxes)
    best = np.full((y1 - y0 + 1, x1 - x0 + 1), np.nan)
    for placement, (bx0, by0, bx1, by1) in boxes:
        columns, rows = np.meshgrid(np.arange(bx0, bx1 + 1), np.arange(by0, by1 + 1))
        dx = ((columns - grid.border) * WORLD_UNITS_PER_CELL - placement.x) / placement.scale
        dy = ((rows - grid.border) * WORLD_UNITS_PER_CELL - placement.y) / placement.scale
        cos, sin = math.cos(-placement.angle), math.sin(-placement.angle)
        hits = highest_hits(placement.triangles, cos * dx - sin * dy, sin * dx + cos * dy)
        heights = hits * placement.scale + placement.z
        window = best[by0 - y0 : by1 - y0 + 1, bx0 - x0 : bx1 - x0 + 1]
        window[:] = np.where(np.isnan(heights) | (heights <= window), window, heights)

    laid = ~np.isnan(best) & (best > 0)
    if not laid.any():
        return None
    values = grid.heights[y0 : y1 + 1, x0 : x1 + 1].astype(np.int64)
    raised = np.floor(np.nan_to_num(best) / FEET_PER_HEIGHT_UNIT + 0.5)
    values = np.where(laid, np.clip(raised, 0, MAX_HEIGHT).astype(np.int64), values)
    if np.array_equal(values, grid.heights[y0 : y1 + 1, x0 : x1 + 1]):
        return None
    return x0, y0, values.astype(np.uint16)
