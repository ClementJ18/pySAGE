"""`.scb` files carrying more than scripts: the passability, water, terrain and lighting chunks
WorldBuilder's Export Options can add, in its writer's order."""

import io
from pathlib import Path

from sage_map.assets import ScriptApplyHeight, ScriptImportSize, ScriptPassability
from sage_map.assets.script_passability import LAYERS
from sage_map.map import parse_map_from_path
from sage_map.scb import ScriptLibrary, extract_scripts, parse_scb, write_scb

FIXTURE = Path(__file__).parent / "fixtures" / "maps" / "map edain ford of bruinen.map"


def _passability(map, version=3):
    blend, height = map.blend_tile_data, map.height_map_data
    cells = {}
    for name, since in LAYERS:
        if version < since:
            continue
        stored = getattr(blend, name)
        cells[name] = [[int(value) for value in column] for column in stored]
    return ScriptPassability(version, cells, 0, 0), height.width, height.height


def _library(map) -> ScriptLibrary:
    library = extract_scripts(map)
    passability, width, height = _passability(map)
    library.script_import_size = ScriptImportSize(1, width, height, 0, 0)
    library.script_passability = passability
    library.standing_water_areas = map.standing_water_areas
    library.river_areas = map.river_areas
    library.standing_wave_areas = map.standing_wave_areas
    library.height_map_data = map.height_map_data
    library.script_apply_height = ScriptApplyHeight(1, True, 0, 0)
    library.blend_tile_data = map.blend_tile_data
    library.global_lighting = map.global_lighting
    return library


def test_an_export_with_every_chunk_round_trips_byte_exact():
    map = parse_map_from_path(FIXTURE)
    written = write_scb(_library(map))

    reread = parse_scb(io.BytesIO(written))

    assert write_scb(reread) == written
    assert reread.script_passability.cells == _passability(map)[0].cells
    assert reread.script_apply_height.apply_height is True
    assert reread.height_map_data.elevations == map.height_map_data.elevations
    assert reread.blend_tile_data.tiles == map.blend_tile_data.tiles
    assert reread.global_lighting.time_of_the_day == map.global_lighting.time_of_the_day


def test_chunks_are_written_in_worldbuilders_order():
    map = parse_map_from_path(FIXTURE)
    reread = parse_scb(io.BytesIO(write_scb(_library(map))))
    order = [name for _, name in sorted(reread.assets.items())]

    stored = [name for name in order if name[0].isupper() and name in _CHUNK_ORDER]
    assert stored == [name for name in _CHUNK_ORDER if name in stored]


_CHUNK_ORDER = [
    "ScriptImportSize",
    "ScriptPassability",
    "PlayerScriptsList",
    "NamedCameras",
    "CameraAnimationList",
    "ScriptsPlayers",
    "ObjectsList",
    "TriggerAreas",
    "StandingWaterAreas",
    "RiverAreas",
    "StandingWaveAreas",
    "ScriptTeams",
    "WaypointsList",
    "HeightMapData",
    "ScriptApplyHeight",
    "BlendTileData",
    "GlobalLighting",
]


def test_older_passability_versions_store_fewer_values_per_cell():
    map = parse_map_from_path(FIXTURE)
    library = ScriptLibrary()
    passability, width, height = _passability(map, version=1)
    library.script_import_size = ScriptImportSize(1, width, height, 0, 0)
    library.script_passability = passability

    written = write_scb(library)
    reread = parse_scb(io.BytesIO(written))

    assert sorted(reread.script_passability.cells) == sorted(
        name for name, since in LAYERS if since == 1
    )
    assert write_scb(reread) == written
