"""A new, empty map, as WorldBuilder's New makes one.

New asks for the heightmap's size and border in cells, the initial height in feet, and whether
the map is a Living World script holder (dialog 133, New Height Map). Everything else a map
stores starts from WorldBuilder's defaults: the camera and lighting settings that the corpus's
library maps share unchanged (see `map_defaults`), eight open multiplayer positions (every corpus
map stores the same eight), the neutral player with its team `team`, and no objects, waypoints,
areas, water or cameras. The ground is one texture, tiled as WorldBuilder tiles a texture.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sage_map.assets.blend_tile_data import BlendTileData, BlendTileTexture, TileFlammability
from sage_map.assets.camera_animation_list import CameraAnimationList
from sage_map.assets.environment_data import EnvironmentData
from sage_map.assets.global_lighting import (
    GlobalLight,
    GlobalLighting,
    GlobalLightingConfiguration,
    MapColorArgb,
    TimeOfTheDay,
)
from sage_map.assets.height_map import HeightMapBorder, HeightMapData
from sage_map.assets.library_map_lists import LibraryMapLists, LibraryMaps
from sage_map.assets.mp_positions import MPPosition, MPPositionList
from sage_map.assets.named_cameras import NamedCameras
from sage_map.assets.object_list import ObjectsList
from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList
from sage_map.assets.post_effects_chunk import PostEffectsChunk
from sage_map.assets.river_areas import RiverAreas
from sage_map.assets.sides_list import BuildList, BuildLists, SidesList
from sage_map.assets.standing_water_area import StandingWaterAreas
from sage_map.assets.standing_waves_area import StandingWaveAreas
from sage_map.assets.teams import Teams
from sage_map.assets.trigger_areas import TriggerAreas
from sage_map.assets.waypoint_list import WaypointsList
from sage_map.assets.world_info import WorldInfo
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import map_defaults
from sage_worldbuilder.players import new_player
from sage_worldbuilder.teams import new_team
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, MAX_HEIGHT

__all__ = ["NewMapOptions", "blank_blend_tile_data", "blank_height_map", "new_map", "tile_pattern"]

# A texture 256 pixels across: 48,151 of the corpus's 51,818 texture entries.
DEFAULT_CELL_SIZE = 4
_MULTIPLAYER_POSITIONS = 8
_NO_TEAM = 0xFFFFFFFF
_NO_FACTION = "UNKNOWN"


@dataclass
class NewMapOptions:
    """New Height Map's fields: sizes and border in cells (10 feet each), the initial height in
    feet, the Living World flag, and the texture to cover the ground with (a Terrain.ini entry
    and its width in 64-pixel texture cells)."""

    width: int = 200
    height: int = 200
    border: int = 30
    initial_height: float = 16.0
    living_world_script_holder: bool = False
    texture: str = "GrassMirkWood02"
    cell_size: int = DEFAULT_CELL_SIZE

    def validate(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("the map must be at least one cell across")
        if self.border < 0 or 2 * self.border >= min(self.width, self.height):
            raise ValueError("the border must leave a playable area inside it")
        if not self.texture:
            raise ValueError("choose a texture")
        if self.cell_size < 1:
            raise ValueError("a texture is at least one texture cell across")


def _property(name: str, kind: AssetPropertyType, value: object) -> dict[str, object]:
    return {"name": name, "type": kind, "value": value}


def tile_pattern(
    width: int, height: int, cell_start: int, cell_size: int, x0: int = 0, y0: int = 0
) -> np.ndarray:
    """One texture tiled over `width` x `height` cells from cell `(x0, y0)`, `[cell_y, cell_x]`:
    each heightmap cell shows a quarter of a 64-pixel texture cell, so the texture repeats every
    `2 * cell_size` cells, in step with the map's own cell coordinates."""
    xs = np.arange(x0, x0 + width)
    ys = np.arange(y0, y0 + height)
    column = (xs // 2) % cell_size
    row = (ys // 2) % cell_size
    cells = cell_start + row[:, None] * cell_size + column[None, :]
    quadrant = (xs % 2)[None, :] | ((ys % 2) << 1)[:, None]
    return (cells << 2) | quadrant


def blank_height_map(width: int, height: int, border: int, value: int) -> HeightMapData:
    return HeightMapData(
        version=5,
        width=width,
        height=height,
        border_width=border,
        borders=[HeightMapBorder((0, 0), (width - 2 * border, height - 2 * border))],
        area=width * height,
        min_height=value,
        max_height=value,
        elevations=[[value] * width for _ in range(height)],
        start_pos=0,
        end_pos=0,
    )


def blank_blend_tile_data(
    width: int, height: int, texture: str, cell_size: int = DEFAULT_CELL_SIZE
) -> BlendTileData:
    """One texture over the whole map, no blends or cliff mappings, every cell passable, fire
    resistant and visible (as the corpus's smallest library maps store it)."""
    cell_count = cell_size * cell_size
    tiles = tile_pattern(width, height, 0, cell_size).T.tolist()

    def layer(value: object) -> list[list[object]]:
        return [[value] * height for _ in range(width)]

    return BlendTileData(
        version=18,
        tiles=tiles,
        blends=layer(0),  # type: ignore[arg-type]
        three_way_blends=layer(0),  # type: ignore[arg-type]
        cliff_textures=layer(0),  # type: ignore[arg-type]
        impassability=layer(False),  # type: ignore[arg-type]
        impassability_to_players=layer(False),  # type: ignore[arg-type]
        passage_widths=layer(False),  # type: ignore[arg-type]
        taintability=layer(False),  # type: ignore[arg-type]
        extra_passability=layer(False),  # type: ignore[arg-type]
        flammability=layer(TileFlammability.FIRE_RESISTANT),  # type: ignore[arg-type]
        visibility=layer(True),  # type: ignore[arg-type]
        buildability=None,
        impassability_to_air_units=None,
        tiberium_growability=None,
        dynamic_shrubbery_density=None,
        texture_cell_count=cell_count,
        blends_count_raw=1,
        parsed_cliff_texture_mappings_count=1,
        textures=[BlendTileTexture(0, cell_count, cell_size, 0, texture)],
        magic_value1=0,
        magic_value2=0,
        blend_descriptions=[],
        cliff_texture_mappings=[],
        start_pos=0,
        end_pos=0,
    )


def _lighting() -> GlobalLighting:
    configurations = {}
    for time in TimeOfTheDay:
        lights = {
            name: GlobalLight(*light) for name, light in map_defaults.LIGHTS[time.name].items()
        }
        configurations[time] = GlobalLightingConfiguration(**lights)
    return GlobalLighting(
        version=map_defaults.LIGHTING_VERSION,
        time_of_the_day=TimeOfTheDay(map_defaults.TIME_OF_DAY),
        lighting_configurations=configurations,
        overbright=map_defaults.OVERBRIGHT,
        bloom_enabled=map_defaults.BLOOM_ENABLED,
        bloom_infantry=map_defaults.BLOOM_INFANTRY,
        bloom_terrain=map_defaults.BLOOM_TERRAIN,
        bloom_objects=map_defaults.BLOOM_OBJECTS,
        shadow_color=MapColorArgb(*map_defaults.SHADOW_COLOR),
        unknown=None,
        unknown2=None,
        unknown3=None,
        no_cloud_factor=map_defaults.NO_CLOUD_FACTOR,
        start_pos=0,
        end_pos=0,
    )


def _world_info(options: NewMapOptions) -> WorldInfo:
    real, boolean = AssetPropertyType.RealNumber, AssetPropertyType.Boolean
    integer, text = AssetPropertyType.Integer, AssetPropertyType.AsciiString
    rows = [
        ("cameraMaxHeight", real, 300.0),
        ("cameraPitchAngle", real, 37.5),
        ("cameraYawAngle", real, 0.0),
        ("cameraScrollSpeedScalar", real, 1.0),
        ("isLivingWorldScriptHolder", boolean, options.living_world_script_holder),
        ("weather", integer, 0),
        ("compression", integer, 1),
        ("cameraGroundMinHeight", real, 0.0),
        ("cameraGroundMaxHeight", real, 2560.0),
        ("mapName", text, ""),
        ("mapDescription", text, ""),
        ("isScenarioMultiplayer", boolean, False),
    ]
    properties = {name: _property(name, kind, value) for name, kind, value in rows}
    return WorldInfo(version=1, properties=properties, start_pos=0, end_pos=0)  # type: ignore[arg-type]


def new_map(options: NewMapOptions) -> Map:
    options.validate()
    initial = int(min(max(round(options.initial_height / FEET_PER_HEIGHT_UNIT), 0), MAX_HEIGHT))
    map = Map()
    map.height_map_data = blank_height_map(options.width, options.height, options.border, initial)
    map.blend_tile_data = blank_blend_tile_data(
        options.width, options.height, options.texture, options.cell_size
    )
    map.world_info = _world_info(options)
    map.mp_positions_list = MPPositionList(
        version=0,
        positions=[
            MPPosition(1, True, True, True, _NO_TEAM, [], 0, 0)
            for _ in range(_MULTIPLAYER_POSITIONS)
        ],
        start_pos=0,
        end_pos=0,
    )
    map.sides_list = SidesList(
        version=6,
        unknown1=False,
        players=[new_player("", "Neutral")],
        start_pos=0,
        end_pos=0,
    )
    map.library_map_lists = LibraryMapLists(
        version=1, lists=[LibraryMaps(1, [], 0, 0)], start_pos=0, end_pos=0
    )
    map.teams = Teams(version=1, teams=[new_team("team", "", True)], start_pos=0, end_pos=0)
    map.player_scripts_list = PlayerScriptsList(
        version=1, script_lists=[ScriptList(1, [], 0, 0)], start_pos=0, end_pos=0
    )
    map.build_lists = BuildLists(
        version=1,
        build_lists=[BuildList(None, (AssetPropertyType.AsciiString, 0, _NO_FACTION), [])],
        start_pos=0,
        end_pos=0,
    )
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.trigger_areas = TriggerAreas(version=1, trigger_areas=[], start_pos=0, end_pos=0)
    map.standing_water_areas = StandingWaterAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.river_areas = RiverAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.standing_wave_areas = StandingWaveAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.global_lighting = _lighting()
    map.post_effects_chunk = PostEffectsChunk(version=1, post_effects=[], start_pos=0, end_pos=0)
    map.environment_data = EnvironmentData(
        version=3,
        water_max_alpha_depth=3.0,
        deep_water_alpha=1.0,
        is_macro_texture_stretched=False,
        macro_texture="TSNoiseUrb.tga",
        cloud_texture="TSCloudMed.tga",
        unknown_texture=None,
        unknown_texture2=None,
        start_pos=0,
        end_pos=0,
    )
    map.named_cameras = NamedCameras(version=2, cameras=[], start_pos=0, end_pos=0)
    map.camera_animation_list = CameraAnimationList(
        version=3, animations=[], start_pos=0, end_pos=0
    )
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    return map
