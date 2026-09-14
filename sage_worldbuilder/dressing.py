"""World dressing that writes ordinary map data: scorch marks, groves, fences, ramps, borders and
mesh molds (PLAN.md 5.4 and 5.7).

- **Scorch marks** are objects of template `Scorch` with an integer `scorchType` (Scorch Options
  lists Scorch 1-4, stored 0-3) and a real `objectRadius` (its Scorch Size, 20 by default,
  `0x0221B1E0`). Their other properties are a new object's, in the same order, owned by the
  neutral team: the form of 1,341 of the corpus's 3,083 scorch marks.
- **Groves** place trees chosen by Grove Options' weights (`GroveTool::addObj`, `0x005108F0`, gives
  each a random angle and the neutral team): a drag fills its rectangle with the total tree count
  at random points (`0x0050EDF0`); a click places them about the spot. Points under water or on
  cliffs are skipped unless allowed. The click cluster's size, the cliff slope and "under water"
  are choices; WorldBuilder's cluster (`0x0050FA10`) and tests are not read.
- **Fences** place the Object Palette's object along a drag at Fence options' spacing
  (27.35 by default, `FenceTool::FenceTool`), each turned along the line; stretched, the spacing
  is adjusted so the row ends where the drag does.
- **Ramps** set the heights across a drag, its Ramp Width (20 by default) wide, to a straight slope
  from the ground at its start to the ground at its end: a choice, the Ramp tool's code is not
  read.
- **Borders** are the heightmap's border records: every corpus border starts at (0, 0) and its
  other corner is a size in cells (on 981 of 1,646, the playable area). A map may have several;
  scripts switch between them.
- **Mesh molds** reshape the ground to a W3D model from `data\\Editor\\Molds`, as
  `0x005706B0` does: every heightmap sample within the mold's reach is taken into the mold's space
  (moved by the mold's position, divided by its scale, turned back by its angle), a ray is cast
  straight down onto the model, and the hit's height times the scale, plus the mold's height in
  feet, becomes the sample's height (in 0.0390625 ft steps, rounded), everywhere, or only where it
  raises or only where it lowers the ground.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import numpy as np

from sage_map.assets.height_map import HeightMapBorder
from sage_map.assets.object_list import Object
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder.areas import area_contains
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command
from sage_worldbuilder.commands.edits import InsertItem, RemoveItem
from sage_worldbuilder.objects import new_object, renumber_unique_ids
from sage_worldbuilder.terrain.grid import FEET_PER_HEIGHT_UNIT, MAX_HEIGHT, WORLD_UNITS_PER_CELL

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument
    from sage_worldbuilder.terrain import TerrainGrid

__all__ = [
    "DEFAULT_FENCE_SPACING",
    "DEFAULT_RAMP_WIDTH",
    "DEFAULT_SCORCH_SIZE",
    "MOLD_FOLDER",
    "NEUTRAL_OWNER",
    "SCORCH_TEMPLATE",
    "SCORCH_TYPES",
    "GroveOptions",
    "HeightPatch",
    "MoldMode",
    "MoldOptions",
    "ResizeBorder",
    "add_border",
    "cluster_points",
    "fence_objects",
    "fence_points",
    "grove_objects",
    "highest_hits",
    "list_molds",
    "mold_patch",
    "mold_triangles",
    "new_scorch",
    "pick_tree",
    "playable_size",
    "ramp_patch",
    "rectangle_points",
    "remove_border",
]

SCORCH_TEMPLATE = "Scorch"
SCORCH_TYPES = ("Scorch 1", "Scorch 2", "Scorch 3", "Scorch 4")
DEFAULT_SCORCH_SIZE = 20.0
DEFAULT_FENCE_SPACING = 27.35
DEFAULT_RAMP_WIDTH = 20.0
NEUTRAL_OWNER = "/team"
MOLD_FOLDER = "data/editor/molds"
# A click's grove spreads its trees over a disc this many world units across per tree's worth of
# area: 20 units, two heightmap cells, per tree.
_CLUSTER_SPACING = 20.0
# Ground steeper than this, in degrees, is a cliff to a grove.
_CLIFF_DEGREES = 45.0

BORDERS = Change(ChangeKind.SETTINGS)


def new_scorch(
    map: Map,
    position: tuple[float, float],
    scorch_type: int,
    radius: float,
    layer: str = "",
) -> Object:
    obj = new_object(
        map, SCORCH_TEMPLATE, (position[0], position[1], 0.0), 0.0, NEUTRAL_OWNER, layer
    )
    obj.properties["scorchType"] = {
        "name": "scorchType",
        "type": AssetPropertyType.Integer,
        "value": int(scorch_type),
    }
    obj.properties["objectRadius"] = {
        "name": "objectRadius",
        "type": AssetPropertyType.RealNumber,
        "value": float(radius),
    }
    return obj


@dataclass
class GroveOptions:
    """Grove Options: up to five tree types with their weights (percent), the total tree count,
    whether trees may stand in water or on cliffs, and whether they align to the terrain."""

    trees: list[tuple[str, int]] = field(default_factory=list)
    count: int = 10
    allow_water: bool = False
    allow_cliffs: bool = False
    align_to_terrain: bool = False


def pick_tree(options: GroveOptions, rng: np.random.Generator) -> str | None:
    """A tree type drawn by the options' weights; None when no type has weight."""
    choices = [(name, weight) for name, weight in options.trees if name and weight > 0]
    total = sum(weight for _name, weight in choices)
    if total <= 0:
        return None
    draw = rng.integers(0, total)
    for name, weight in choices:
        if draw < weight:
            return name
        draw -= weight
    return choices[-1][0]


def rectangle_points(
    rng: np.random.Generator, count: int, corner: tuple[float, float], other: tuple[float, float]
) -> list[tuple[float, float]]:
    if not count:
        return []
    x0, x1 = sorted((corner[0], other[0]))
    y0, y1 = sorted((corner[1], other[1]))
    xs = rng.uniform(x0, x1, count)
    ys = rng.uniform(y0, y1, count)
    return [(float(x), float(y)) for x, y in zip(xs, ys, strict=True)]


def cluster_points(
    rng: np.random.Generator, count: int, center: tuple[float, float]
) -> list[tuple[float, float]]:
    """`count` points spread evenly over a disc about `center`, larger the more trees it holds."""
    radius = _CLUSTER_SPACING * math.sqrt(max(count, 1)) / 2
    angles = rng.uniform(0.0, math.tau, count)
    distances = radius * np.sqrt(rng.uniform(0.0, 1.0, count))
    return [
        (center[0] + float(d * math.cos(a)), center[1] + float(d * math.sin(a)))
        for a, d in zip(angles, distances, strict=True)
    ]


def _under_water(map: Map, grid: TerrainGrid | None, x: float, y: float) -> bool:
    from sage_worldbuilder.water import all_water, water_outline  # noqa: PLC0415 - cycle

    ground = 0.0
    if grid is not None:
        from sage_worldbuilder.terrain.surface import ground_height  # noqa: PLC0415

        ground = ground_height(grid, x, y)
    for area in all_water(map):
        height = getattr(area, "water_height", None)
        outline = water_outline(area)
        if height is None or len(outline) < 3 or height <= ground:
            continue
        if area_contains(outline, x, y):
            return True
    return False


def _on_cliff(grid: TerrainGrid | None, x: float, y: float) -> bool:
    if grid is None:
        return False
    from sage_worldbuilder.terrain.surface import ground_height  # noqa: PLC0415

    step = WORLD_UNITS_PER_CELL
    dx = (ground_height(grid, x + step, y) - ground_height(grid, x - step, y)) / (2 * step)
    dy = (ground_height(grid, x, y + step) - ground_height(grid, x, y - step)) / (2 * step)
    return math.degrees(math.atan(math.hypot(dx, dy))) > _CLIFF_DEGREES


def grove_objects(
    map: Map,
    points: Iterable[tuple[float, float]],
    options: GroveOptions,
    rng: np.random.Generator,
    grid: TerrainGrid | None = None,
    layer: str = "",
) -> list[Object]:
    """A tree at each point the options allow, drawn by weight, at a random angle, owned by the
    neutral team."""
    trees: list[Object] = []
    for x, y in points:
        if not options.allow_water and _under_water(map, grid, x, y):
            continue
        if not options.allow_cliffs and _on_cliff(grid, x, y):
            continue
        name = pick_tree(options, rng)
        if name is None:
            break
        angle = float(rng.uniform(-math.pi, math.pi))
        tree = new_object(map, name, (x, y, 0.0), angle, NEUTRAL_OWNER, layer)
        if options.align_to_terrain:
            tree.properties["alignToTerrain"] = {
                "name": "alignToTerrain",
                "type": AssetPropertyType.Boolean,
                "value": True,
            }
        trees.append(tree)
    return renumber_unique_ids(map, trees)


def fence_points(
    start: tuple[float, float], end: tuple[float, float], spacing: float, stretch: bool = False
) -> tuple[list[tuple[float, float]], float]:
    """Where a fence's posts stand along a line, and the angle they face (radians, along the
    line): every `spacing` from the start, or, stretched, evenly from the start to the end."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    angle = math.atan2(dy, dx) if length else 0.0
    if length == 0 or spacing <= 0:
        return [start], angle
    if stretch:
        count = max(1, round(length / spacing))
        step = length / count
    else:
        count = math.floor(length / spacing + 1e-9)
        step = spacing
    ux, uy = dx / length, dy / length
    return [(start[0] + ux * step * i, start[1] + uy * step * i) for i in range(count + 1)], angle


def fence_objects(
    map: Map,
    template: str,
    start: tuple[float, float],
    end: tuple[float, float],
    spacing: float,
    owner: str,
    stretch: bool = False,
    layer: str = "",
) -> list[Object]:
    points, angle = fence_points(start, end, spacing, stretch)
    posts = [new_object(map, template, (x, y, 0.0), angle, owner, layer) for x, y in points]
    return renumber_unique_ids(map, posts)


@dataclass(frozen=True)
class HeightPatch:
    """A rectangle of stored heights, `values[row, column]` from sample `(x0, y0)`."""

    x0: int
    y0: int
    values: np.ndarray


def ramp_patch(
    grid: TerrainGrid, start: tuple[float, float], end: tuple[float, float], width: float
) -> HeightPatch | None:
    """The heights of a ramp `width` world units across from `start` to `end`: each sample within
    half the width of the line takes the height of a straight slope from the ground at the start
    to the ground at the end. None when no sample is within reach."""
    from sage_worldbuilder.terrain.surface import ground_height  # noqa: PLC0415

    h0 = ground_height(grid, *start) / FEET_PER_HEIGHT_UNIT
    h1 = ground_height(grid, *end) / FEET_PER_HEIGHT_UNIT
    half = width / 2
    cells = [grid.world_to_cell(*point) for point in (start, end)]
    reach = half / WORLD_UNITS_PER_CELL
    x0 = max(0, math.floor(min(c[0] for c in cells) - reach))
    y0 = max(0, math.floor(min(c[1] for c in cells) - reach))
    x1 = min(grid.width - 1, math.ceil(max(c[0] for c in cells) + reach))
    y1 = min(grid.height - 1, math.ceil(max(c[1] for c in cells) + reach))
    if x1 < x0 or y1 < y0:
        return None
    columns, rows = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
    wx = (columns - grid.border) * WORLD_UNITS_PER_CELL
    wy = (rows - grid.border) * WORLD_UNITS_PER_CELL
    ax, ay = start
    dx, dy = end[0] - ax, end[1] - ay
    length = dx * dx + dy * dy
    t = (
        np.zeros(wx.shape)
        if length == 0
        else np.clip(((wx - ax) * dx + (wy - ay) * dy) / length, 0, 1)
    )
    distance = np.hypot(wx - (ax + t * dx), wy - (ay + t * dy))
    inside = distance <= half
    if not inside.any():
        return None
    values = grid.heights[y0 : y1 + 1, x0 : x1 + 1].astype(np.int64)
    slope = np.clip(np.floor(h0 + t * (h1 - h0) + 0.5), 0, MAX_HEIGHT)
    values[inside] = slope[inside]
    return HeightPatch(x0, y0, values.astype(np.uint16))


def playable_size(map: Map) -> tuple[int, int]:
    """The playable area's size in cells: the heightmap less its border on each side."""
    height_map = map.height_map_data
    if height_map is None:
        return 0, 0
    border = height_map.border_width
    return max(0, height_map.width - 2 * border), max(0, height_map.height - 2 * border)


def add_border(map: Map, size: tuple[int, int] | None = None) -> Command:
    """The command adding a border from (0, 0) to `size` cells, the playable area by default."""
    height_map = map.height_map_data
    if height_map is None:
        raise ValueError("the map has no heightmap")
    width, height = size if size is not None else playable_size(map)
    border = HeightMapBorder((0, 0), (int(width), int(height)))
    return InsertItem(height_map.borders, len(height_map.borders), border, BORDERS, "Add Border")


def remove_border(map: Map, border: HeightMapBorder) -> Command:
    height_map = map.height_map_data
    if height_map is None or all(item is not border for item in height_map.borders):
        raise ValueError("the border is not on the map")
    index = next(i for i, item in enumerate(height_map.borders) if item is border)
    return RemoveItem(height_map.borders, index, BORDERS, "Remove Border")


class ResizeBorder(Command):
    """Move a border's far corner to `size` cells. A run of resizes of the same border merges
    until closed, so one drag is one undo entry."""

    def __init__(
        self, border: HeightMapBorder, size: tuple[int, int], label: str = "Resize Border"
    ) -> None:
        self.border = border
        self.size = (int(size[0]), int(size[1]))
        self.label = label
        self.closed = False
        self._before: tuple[int, int] | None = None

    def do(self, document: MapDocument) -> None:
        if self._before is None:
            self._before = self.border.position
        self.border.position = self.size

    def undo(self, document: MapDocument) -> None:
        assert self._before is not None
        self.border.position = self._before

    def changes(self) -> tuple[Change, ...]:
        return (BORDERS,)

    def merge(self, following: Command) -> bool:
        if self.closed or not (
            isinstance(following, ResizeBorder) and following.border is self.border
        ):
            return False
        self.size = following.size
        return True


class MoldMode(StrEnum):
    BOTH = "Raise and Lower"
    RAISE = "Raise Only"
    LOWER = "Lower Only"


@dataclass
class MoldOptions:
    """Mesh Mold Options: the mold, its scale (1 for 100%), its height in feet, its angle in
    degrees, and which way it may move the ground."""

    mold: str = ""
    scale: float = 1.0
    height: float = 0.0
    angle: float = 0.0
    mode: MoldMode = MoldMode.BOTH


def list_molds(filesystem: Any) -> list[str]:
    """The mold models the game data has, by file name."""
    names = set()
    for entry in filesystem.listdir(MOLD_FOLDER):
        path = str(getattr(entry, "path", entry)).replace("\\", "/")
        if path.lower().endswith(".w3d"):
            names.add(path.rsplit("/", 1)[-1])
    return sorted(names, key=str.lower)


def mold_triangles(scene: Any) -> np.ndarray:
    """A built W3D scene's triangles in model space as `(T, 3, 3)` floats."""
    triangles = []
    for mesh in getattr(scene, "meshes", None) or []:
        positions = np.asarray(mesh.positions, dtype=np.float64).reshape(-1, 3)
        indices = np.asarray(mesh.indices, dtype=np.int64).reshape(-1, 3)
        if len(positions) and len(indices) and indices.max() < len(positions):
            triangles.append(positions[indices])
    return np.concatenate(triangles) if triangles else np.zeros((0, 3, 3))


def highest_hits(triangles: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """The height where a ray straight down first meets the triangles above each point: the
    highest surface there, or NaN where it misses them all."""
    best = np.full(xs.shape, np.nan)
    for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in triangles:
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(denominator) < 1e-12:
            continue
        u = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / denominator
        v = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / denominator
        w = 1 - u - v
        inside = (u >= -1e-9) & (v >= -1e-9) & (w >= -1e-9)
        if not inside.any():
            continue
        z = u * az + v * bz + w * cz
        best = np.where(inside & ~(z <= best), z, best)
    return best


def mold_patch(
    grid: TerrainGrid,
    triangles: np.ndarray,
    position: tuple[float, float],
    options: MoldOptions,
) -> HeightPatch | None:
    """The heights a mold at `position` gives the ground, with the samples it does not change
    left as they are; None when it changes none."""
    if len(triangles) == 0 or options.scale <= 0:
        return None
    reach = float(np.hypot(triangles[..., 0], triangles[..., 1]).max()) * options.scale
    cx, cy = grid.world_to_cell(*position)
    cells = reach / WORLD_UNITS_PER_CELL
    x0, y0 = max(0, math.floor(cx - cells)), max(0, math.floor(cy - cells))
    x1 = min(grid.width - 1, math.ceil(cx + cells))
    y1 = min(grid.height - 1, math.ceil(cy + cells))
    if x1 < x0 or y1 < y0:
        return None
    columns, rows = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
    dx = ((columns - grid.border) * WORLD_UNITS_PER_CELL - position[0]) / options.scale
    dy = ((rows - grid.border) * WORLD_UNITS_PER_CELL - position[1]) / options.scale
    turn = math.radians(-options.angle)
    cos, sin = math.cos(turn), math.sin(turn)
    local_x, local_y = cos * dx - sin * dy, sin * dx + cos * dy
    hits = highest_hits(triangles, local_x, local_y)
    hit = ~np.isnan(hits)
    if not hit.any():
        return None
    before = grid.heights[y0 : y1 + 1, x0 : x1 + 1].astype(np.int64)
    after = np.floor(
        (np.nan_to_num(hits) * options.scale + options.height) / FEET_PER_HEIGHT_UNIT + 0.5
    )
    after = np.clip(after, 0, MAX_HEIGHT).astype(np.int64)
    if options.mode is MoldMode.RAISE:
        hit &= after > before
    elif options.mode is MoldMode.LOWER:
        hit &= after < before
    if not hit.any():
        return None
    values = np.where(hit, after, before)
    return HeightPatch(x0, y0, values.astype(np.uint16))
