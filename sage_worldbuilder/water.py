"""Water areas: lakes and oceans, rivers, and wave areas.

Three chunks hold them: `StandingWaterAreas`, `RiverAreas` and `StandingWaveAreas`, version 2 on
every corpus map. Each numbers its own `unique_id`s, so ids overlap across the three and with the
trigger areas; a new area takes one past the highest id of its own set, as `AreaSet::getID` keeps
a set of its own for each kind. A lake or a wave area is a list of world points; a river is a list
of bank lines, each a (left, right) point pair across the river. A water height is in feet, as
WorldBuilder's dialog labels it and the terrain around corpus rivers agrees.

WorldBuilder names new areas `New Water Area`, `New River` and `New Wave Area` and never numbers
them; the other fields of a new area are the values most of the corpus's areas still carrying
those names store (1,161 lakes, 1,469 rivers, 2,354 wave areas). The lake FX shader has no such
majority (`Wtr_Moat.W3D` on 241), so a new lake has none. Ids keep gaps: most maps' sets neither
start at 1 nor run densely.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sage_map.assets.river_areas import RiverArea
from sage_map.assets.standing_water_area import StandingWaterArea
from sage_map.assets.standing_waves_area import StandingWaveArea
from sage_map.map import Map
from sage_worldbuilder.areas import MoveAreaPoint, area_contains
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, SetAttribute
from sage_worldbuilder.commands.edits import InsertItem

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument
    from sage_worldbuilder.terrain import TerrainGrid

__all__ = [
    "NEW_NAMES",
    "WATER",
    "DeleteWater",
    "MoveRiverPoint",
    "MoveWater",
    "WaterArea",
    "WaterKind",
    "add_river_line",
    "add_water",
    "all_water",
    "default_height",
    "move_handle",
    "new_lake",
    "new_river",
    "new_wave",
    "next_water_id",
    "set_water",
    "water_areas",
    "water_contains",
    "water_handles",
    "water_kind",
    "water_outline",
]

WaterArea = StandingWaterArea | RiverArea | StandingWaveArea
# A draggable point of an area: (point index, None) for a lake or wave area; (line index, 0 for
# the left bank or 1 for the right) for a river.
Handle = tuple[int, int | None]

WATER = Change(ChangeKind.WATER)


class WaterKind(StrEnum):
    LAKE = "Lake/Ocean"
    RIVER = "River"
    WAVE = "Wave"


NEW_NAMES = {
    WaterKind.LAKE: "New Water Area",
    WaterKind.RIVER: "New River",
    WaterKind.WAVE: "New Wave Area",
}
_CHUNKS = {
    WaterKind.LAKE: "standing_water_areas",
    WaterKind.RIVER: "river_areas",
    WaterKind.WAVE: "standing_wave_areas",
}
_LABELS = {
    WaterKind.LAKE: "Add Water Area",
    WaterKind.RIVER: "Add River",
    WaterKind.WAVE: "Add Wave Area",
}
_VERSION = 2

LAKE_DEFAULTS: dict[str, Any] = {
    "uv_scroll_speed": 0.06,
    "use_adaptive_blending": False,
    "bump_map_texture": "WaterRippleBump.tga",
    "sky_texture": "SkyEnv.tga",
    "fx_shader": "",
    "depth_color": "LUTDepthTint.tga",
}
RIVER_DEFAULTS: dict[str, Any] = {
    "uv_scroll_speed": 0.06,
    "use_additive_blending": True,
    "river_texture": "TWWaterEmpty.tga",
    "noise_texture": "Noise0000.tga",
    "alpha_edge_texture": "TWAlphaEdge.tga",
    "sparkle_texture": "WaterSurfaceBubbles.tga",
    "color": (255, 255, 255),
    "alpha": 1.0,
    "minimum_water_lod": "",
}
WAVE_DEFAULTS: dict[str, Any] = {
    "uv_scroll_speed": 0.06,
    "use_adaptive_blending": False,
    "final_width": 28,
    "final_height": 18,
    "initial_width_fraction": 50,
    "initial_height_fraction": 100,
    "initial_velocity": 5,
    "time_to_fade": 2000,
    "time_to_compress": 1000,
    "time_offset_2nd_wave": 3000,
    "distance_from_shore": 40,
    "texture": "wave256.tga",
    "enable_pca_wave": True,
    "wave_particle_fx_name": "",
}


def water_kind(item: object) -> WaterKind | None:
    if isinstance(item, StandingWaterArea):
        return WaterKind.LAKE
    if isinstance(item, RiverArea):
        return WaterKind.RIVER
    if isinstance(item, StandingWaveArea):
        return WaterKind.WAVE
    return None


def _chunk(map: Map, kind: WaterKind) -> Any:
    return getattr(map, _CHUNKS[kind])


def water_areas(map: Map, kind: WaterKind) -> list[Any] | None:
    """The map's areas of a kind, or None when it has no chunk for them."""
    chunk = _chunk(map, kind)
    return chunk.areas if chunk is not None else None


def all_water(map: Map) -> list[WaterArea]:
    return [area for kind in WaterKind for area in water_areas(map, kind) or []]


def next_water_id(map: Map, kind: WaterKind) -> int:
    return max((area.unique_id for area in water_areas(map, kind) or []), default=0) + 1


def water_outline(area: WaterArea) -> list[tuple[float, float]]:
    """The ground an area covers as a polygon: a river's left banks down, then its right banks
    back up."""
    if isinstance(area, RiverArea):
        return [left for left, _right in area.lines] + [
            right for _left, right in reversed(area.lines)
        ]
    return [(float(x), float(y)) for x, y in area.points]


def water_contains(area: WaterArea, x: float, y: float) -> bool:
    outline = water_outline(area)
    return len(outline) >= 3 and area_contains(outline, x, y)


def water_handles(area: WaterArea) -> list[tuple[Handle, tuple[float, float]]]:
    """Each point of an area that can be dragged, with where it is."""
    if isinstance(area, RiverArea):
        return [
            ((index, side), line[side]) for index, line in enumerate(area.lines) for side in (0, 1)
        ]
    return [((index, None), (float(x), float(y))) for index, (x, y) in enumerate(area.points)]


def default_height(grid: TerrainGrid | None, points: Sequence[tuple[float, float]]) -> int:
    """A new area's water height: the lowest ground under its points, in whole feet, so the water
    reaches the lowest point of its shore."""
    if grid is None or not points:
        return 0
    from sage_worldbuilder.terrain.surface import ground_height  # noqa: PLC0415 - numpy

    return max(0, round(min(ground_height(grid, x, y) for x, y in points)))


def _version(map: Map, kind: WaterKind) -> int:
    chunk = _chunk(map, kind)
    return chunk.version if chunk is not None else _VERSION


def new_lake(
    map: Map, points: Sequence[tuple[float, float]], height: int, layer: str = ""
) -> StandingWaterArea:
    return StandingWaterArea(
        unique_id=next_water_id(map, WaterKind.LAKE),
        name=NEW_NAMES[WaterKind.LAKE],
        layer_name=layer,
        points=[(float(x), float(y)) for x, y in points],
        water_height=height,
        **LAKE_DEFAULTS,
    )


def new_river(
    map: Map,
    lines: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    height: int,
    layer: str = "",
) -> RiverArea:
    version = _version(map, WaterKind.RIVER)
    return RiverArea(
        version=version,
        unique_id=next_water_id(map, WaterKind.RIVER),
        name=NEW_NAMES[WaterKind.RIVER],
        layer_name=layer,
        unused_color_a=0,
        water_height=height,
        river_type="" if version >= 3 else None,
        lines=[(tuple(left), tuple(right)) for left, right in lines],  # type: ignore[misc]
        **RIVER_DEFAULTS,
    )


def new_wave(map: Map, points: Sequence[tuple[float, float]], layer: str = "") -> StandingWaveArea:
    """A wave area, with the fields its chunk's version stores: the sizes, timings and texture
    before version 3, the PCA flag at version 2, the particle effect from version 4."""
    version = _version(map, WaterKind.WAVE)
    values = dict(WAVE_DEFAULTS)
    if version >= 3:
        for name in (
            "final_width",
            "final_height",
            "initial_width_fraction",
            "initial_height_fraction",
            "initial_velocity",
            "time_to_fade",
            "time_to_compress",
            "time_offset_2nd_wave",
            "distance_from_shore",
            "texture",
        ):
            values[name] = None
    if version != 2:
        values["enable_pca_wave"] = None
    if version < 4:
        values["wave_particle_fx_name"] = None
    return StandingWaveArea(
        unique_id=next_water_id(map, WaterKind.WAVE),
        name=NEW_NAMES[WaterKind.WAVE],
        layer_name=layer,
        points=[(float(x), float(y)) for x, y in points],
        unknown=0,
        **values,
    )


def add_water(map: Map, area: WaterArea) -> Command:
    kind = water_kind(area)
    listed = water_areas(map, kind) if kind is not None else None
    if kind is None or listed is None:
        raise ValueError("the map has no chunk for this kind of water area")
    return InsertItem(listed, len(listed), area, WATER, _LABELS[kind])


def add_river_line(
    area: RiverArea, line: tuple[tuple[float, float], tuple[float, float]]
) -> Command:
    return InsertItem(area.lines, len(area.lines), line, WATER, "Add River Bank")


def set_water(area: WaterArea, name: str, value: object, label: str | None = None) -> Command:
    return SetAttribute(area, name, value, WATER, label)


class DeleteWater(Command):
    """Remove water areas from whichever sets they are in."""

    def __init__(self, areas: Sequence[WaterArea], label: str = "Delete") -> None:
        self.areas = list(areas)
        self.label = label
        self._removed: list[tuple[list[Any], int, WaterArea]] = []

    def do(self, document: MapDocument) -> None:
        wanted = {id(area) for area in self.areas}
        self._removed = []
        for kind in WaterKind:
            listed = water_areas(document.map, kind) or []
            removed = [(listed, index, a) for index, a in enumerate(listed) if id(a) in wanted]
            for _listed, index, _area in reversed(removed):
                del listed[index]
            self._removed += removed

    def undo(self, document: MapDocument) -> None:
        for listed, index, area in self._removed:
            listed.insert(index, area)

    def changes(self) -> tuple[Change, ...]:
        return (WATER,)


def _same(a: Sequence[object], b: Sequence[object]) -> bool:
    return len(a) == len(b) and all(x is y for x, y in zip(a, b, strict=True))


class MoveWater(Command):
    """Move water areas by `dx`, `dy` world units. Point lists change in place, so commands that
    hold them (an added bank line) stay valid; a run of moves merges until closed."""

    def __init__(
        self, areas: Sequence[WaterArea], dx: float, dy: float, label: str = "Move"
    ) -> None:
        self.areas = list(areas)
        self.dx, self.dy = dx, dy
        self.label = label
        self.closed = False
        self._before: list[list[Any]] | None = None

    def do(self, document: MapDocument) -> None:
        if self._before is None:
            self._before = [list(_points(area)) for area in self.areas]
        for area, before in zip(self.areas, self._before, strict=True):
            if isinstance(area, RiverArea):
                area.lines[:] = [
                    ((lx + self.dx, ly + self.dy), (rx + self.dx, ry + self.dy))
                    for (lx, ly), (rx, ry) in before
                ]
            else:
                area.points[:] = [(x + self.dx, y + self.dy) for x, y in before]

    def undo(self, document: MapDocument) -> None:
        assert self._before is not None
        for area, before in zip(self.areas, self._before, strict=True):
            _points(area)[:] = before

    def changes(self) -> tuple[Change, ...]:
        return (WATER,)

    def merge(self, following: Command) -> bool:
        if self.closed or not (
            isinstance(following, MoveWater) and _same(self.areas, following.areas)
        ):
            return False
        self.dx += following.dx
        self.dy += following.dy
        return True


def _points(area: WaterArea) -> list[Any]:
    return area.lines if isinstance(area, RiverArea) else area.points


class MoveRiverPoint(Command):
    """Move one bank point of a river. A run of moves of the same point merges until closed."""

    def __init__(
        self,
        area: RiverArea,
        line: int,
        side: int,
        point: tuple[float, float],
        label: str = "Move Point",
    ) -> None:
        self.area = area
        self.line = line
        self.side = side
        self.point = point
        self.label = label
        self.closed = False
        self._before: tuple[tuple[float, float], tuple[float, float]] | None = None

    def do(self, document: MapDocument) -> None:
        if self._before is None:
            self._before = self.area.lines[self.line]
        left, right = self._before
        self.area.lines[self.line] = (self.point, right) if self.side == 0 else (left, self.point)

    def undo(self, document: MapDocument) -> None:
        assert self._before is not None
        self.area.lines[self.line] = self._before

    def changes(self) -> tuple[Change, ...]:
        return (WATER,)

    def merge(self, following: Command) -> bool:
        if self.closed or not (
            isinstance(following, MoveRiverPoint)
            and following.area is self.area
            and (following.line, following.side) == (self.line, self.side)
        ):
            return False
        self.point = following.point
        return True


def move_handle(
    area: WaterArea, handle: Handle, point: tuple[float, float]
) -> MoveAreaPoint | MoveRiverPoint:
    """The command dragging one of an area's points (see `water_handles`) to `point`."""
    index, side = handle
    if isinstance(area, RiverArea):
        return MoveRiverPoint(area, index, side or 0, point)
    return MoveAreaPoint(area, index, point, change=WATER)
