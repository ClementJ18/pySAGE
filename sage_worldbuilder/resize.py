"""Resize: give the map a new heightmap size and border, keeping its terrain pinned at an anchor.

The kept part of the old terrain lands where the anchor says; new cells get the initial height,
the first texture tiled on, no blends, and default attributes (passable, fire resistant,
visible). World positions are counted from the inner corner of the border, so every one on the
map moves by the change in anchor offset and border: objects (waypoints are objects), trigger
areas, water, wave and river areas, build list entries, named camera look-at points, camera
animation frames, the skybox, and the older polygon triggers. Castle template offsets are
relative to their castle and stay. Undo puts back the old chunks and the exact old positions.

WorldBuilder's resize dialog also has Scale and Scale Sounds; those are not built.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from sage_map.assets.blend_tile_data import BlendTileData, TileFlammability
from sage_map.assets.height_map import HeightMapData
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command
from sage_worldbuilder.heightmap_io import Anchor, reanchor
from sage_worldbuilder.new_map import DEFAULT_CELL_SIZE, blank_height_map, tile_pattern
from sage_worldbuilder.terrain import WORLD_UNITS_PER_CELL
from sage_worldbuilder.terrain.cells import CellLayer, layer_array

__all__ = ["ResizeMap", "ResizeOptions", "resized_terrain", "world_shift"]

_INT_LAYERS = ("tiles", "blends", "three_way_blends", "cliff_textures")


@dataclass(frozen=True)
class ResizeOptions:
    width: int
    height: int
    border: int
    anchor: Anchor = Anchor.CENTER
    # Stored height units for new cells.
    fill_height: int = 0

    def validate(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("the map must be at least one cell across")
        if self.border < 0 or 2 * self.border >= min(self.width, self.height):
            raise ValueError("the border must leave a playable area inside it")


def world_shift(height_map: HeightMapData, options: ResizeOptions) -> tuple[float, float]:
    """How far, in world units, every position on the map moves."""
    dx, dy = options.anchor.offset(
        (height_map.height, height_map.width), (options.height, options.width)
    )
    border_change = height_map.border_width - options.border
    return (dx + border_change) * WORLD_UNITS_PER_CELL, (dy + border_change) * WORLD_UNITS_PER_CELL


def _xy_to_lists(values: np.ndarray, kind: Callable[[Any], object]) -> list[list[object]]:
    """`[cell_y, cell_x]` back to the `[x][y]` lists `BlendTileData` stores."""
    return [[kind(value) for value in column] for column in values.T.tolist()]


def resized_terrain(
    height_map: HeightMapData, blend: BlendTileData | None, options: ResizeOptions
) -> tuple[HeightMapData, BlendTileData | None]:
    """New heightmap and blend tile chunks of the new size; the old ones are left untouched."""
    options.validate()
    shape = (options.height, options.width)
    old_heights = np.asarray(height_map.elevations, dtype=np.uint16)[::-1]
    heights = reanchor(old_heights, shape, options.anchor, options.fill_height)
    new_height_map = blank_height_map(options.width, options.height, options.border, 0)
    new_height_map.version = height_map.version
    new_height_map.elevations = heights[::-1].tolist()
    new_height_map.min_height = int(heights.min())
    new_height_map.max_height = int(heights.max())
    if blend is None:
        return new_height_map, None

    first = blend.textures[0] if blend.textures else None
    cell_start = first.cell_start if first is not None else 0
    cell_size = first.cell_size if first is not None else DEFAULT_CELL_SIZE
    fresh_tiles = tile_pattern(options.width, options.height, cell_start, cell_size)
    new_blend = BlendTileData(**{**vars(blend)})
    for name in _INT_LAYERS:
        old = np.asarray(getattr(blend, name), dtype=np.int64).T
        placed = reanchor(old, shape, options.anchor, 0)
        if name == "tiles":
            mask = reanchor(np.ones(old.shape, dtype=bool), shape, options.anchor, False)
            placed = np.where(mask, placed, fresh_tiles)
        setattr(new_blend, name, _xy_to_lists(placed, int))
    defaults = {CellLayer.VISIBLE: True, CellLayer.FLAMMABILITY: 0}
    for layer in CellLayer:
        old_layer = layer_array(blend, layer)
        if old_layer is None:
            continue
        fill = defaults.get(layer, False)
        placed = reanchor(old_layer, shape, options.anchor, fill)
        kind = TileFlammability if layer is CellLayer.FLAMMABILITY else bool
        setattr(new_blend, layer.value, _xy_to_lists(placed, kind))
    return new_height_map, new_blend


@dataclass
class _Moved:
    """One stored position: `holder[key]` (or the attribute `key` of `holder`) and its old and
    new values."""

    holder: object
    key: object
    old: object
    new: object

    def set(self, value: object) -> None:
        if isinstance(self.key, str):
            setattr(self.holder, self.key, value)
        else:
            self.holder[self.key] = value  # type: ignore[index]


def _shifted(point: tuple, sx: float, sy: float) -> tuple:
    return (point[0] + sx, point[1] + sy, *point[2:])


def _positions(map: Map, sx: float, sy: float) -> list[_Moved]:
    moved: list[_Moved] = []

    def attribute(holder: object, name: str, round_to_int: bool = False) -> None:
        old = getattr(holder, name)
        new = _shifted(old, sx, sy)
        if round_to_int:
            new = tuple(int(round(value)) for value in new)
        moved.append(_Moved(holder, name, old, new))

    def points(values: list, round_to_int: bool = False) -> None:
        for index, old in enumerate(values):
            new = _shifted(old, sx, sy)
            if round_to_int:
                new = tuple(int(round(value)) for value in new)
            moved.append(_Moved(values, index, old, new))

    if map.objects_list is not None:
        for obj in map.objects_list.object_list:
            attribute(obj, "position")
    if map.trigger_areas is not None:
        for area in map.trigger_areas.trigger_areas:
            points(area.points)
    for chunk in (map.standing_water_areas, map.standing_wave_areas):
        for water in chunk.areas if chunk is not None else []:
            points(water.points)
    if map.river_areas is not None:
        for river in map.river_areas.areas:
            for index, (left, right) in enumerate(river.lines):
                new = (_shifted(left, sx, sy), _shifted(right, sx, sy))
                moved.append(_Moved(river.lines, index, (left, right), new))
    if map.polygon_triggers is not None:
        for trigger in map.polygon_triggers.polygon_triggers:
            points(trigger.points, round_to_int=True)
    if map.build_lists is not None:
        for build_list in map.build_lists.build_lists:
            for entry in build_list.build_list:
                attribute(entry, "location")
    if map.sides_list is not None:
        for player in map.sides_list.players:
            for entry in player.build_list_items:
                attribute(entry, "location")
    if map.named_cameras is not None:
        for camera in map.named_cameras.cameras:
            attribute(camera, "look_at_point")
    if map.camera_animation_list is not None:
        for animation in map.camera_animation_list.animations:
            data = animation.frame_data
            # A free camera animation keeps `frames`; a look-at one, camera and look-at frames.
            for frames_name in ("frames", "camera_frames", "look_at_frames"):
                for frame in getattr(data, frames_name, []) or []:
                    for name in ("position", "look_at_point"):
                        if hasattr(frame, name):
                            attribute(frame, name)
    if map.skybox_settings is not None:
        attribute(map.skybox_settings, "position")
    return moved


class ResizeMap(Command):
    label = "Resize"

    def __init__(self, map: Map, options: ResizeOptions) -> None:
        if map.height_map_data is None:
            raise ValueError("the map has no heightmap")
        options.validate()
        self.options = options
        self._old = (map.height_map_data, map.blend_tile_data)
        self._new = resized_terrain(map.height_map_data, map.blend_tile_data, options)
        sx, sy = world_shift(map.height_map_data, options)
        self._moved = _positions(map, sx, sy) if (sx, sy) != (0.0, 0.0) else []

    def do(self, document) -> None:  # noqa: ANN001 - MapDocument, imported lazily to avoid a cycle
        map = document.map
        map.height_map_data, map.blend_tile_data = self._new
        for item in self._moved:
            item.set(item.new)

    def undo(self, document) -> None:  # noqa: ANN001
        map = document.map
        map.height_map_data, map.blend_tile_data = self._old
        for item in reversed(self._moved):
            item.set(item.old)

    def changes(self) -> tuple[Change, ...]:
        return (Change(ChangeKind.WHOLE),)
