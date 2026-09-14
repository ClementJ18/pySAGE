"""Water areas: kinds and ids per set, new lakes, rivers and waves in their chunk's form,
outlines and handles, and the undoable add, delete and move edits."""

import io

import pytest

from sage_map.assets.river_areas import RiverArea, RiverAreas
from sage_map.assets.standing_water_area import StandingWaterArea, StandingWaterAreas
from sage_map.assets.standing_waves_area import StandingWaveArea, StandingWaveAreas
from sage_map.context import ParsingContext, WritingContext
from sage_map.map import Map
from sage_utils.stream import BinaryStream
from sage_worldbuilder import MapDocument
from sage_worldbuilder.changes import ChangeKind
from sage_worldbuilder.water import (
    NEW_NAMES,
    DeleteWater,
    MoveWater,
    WaterKind,
    add_river_line,
    add_water,
    all_water,
    default_height,
    move_handle,
    new_lake,
    new_river,
    new_wave,
    next_water_id,
    water_contains,
    water_handles,
    water_kind,
    water_outline,
)

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, TerrainGrid  # noqa: E402


def water_map(wave_version=2):
    map = Map()
    map.standing_water_areas = StandingWaterAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.river_areas = RiverAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.standing_wave_areas = StandingWaveAreas(
        version=wave_version, areas=[], start_pos=0, end_pos=0
    )
    return map


def test_each_kind_numbers_its_own_ids():
    map = water_map()
    lake = new_lake(map, [(0, 0), (10, 0), (10, 10)], 50)
    map.standing_water_areas.areas.append(lake)
    lake.unique_id = 7
    assert next_water_id(map, WaterKind.LAKE) == 8
    assert next_water_id(map, WaterKind.RIVER) == 1
    river = new_river(map, [((0, 0), (0, 10))], 20)
    assert (river.unique_id, water_kind(river)) == (1, WaterKind.RIVER)
    assert water_kind(lake) is WaterKind.LAKE and water_kind(object()) is None


def test_new_areas_take_their_chunk_versions_form():
    map = water_map()
    lake = new_lake(map, [(0, 0), (10, 0), (10, 10)], 50, layer="Water")
    assert (lake.name, lake.water_height, lake.layer_name) == (
        NEW_NAMES[WaterKind.LAKE],
        50,
        "Water",
    )
    river = new_river(map, [((0, 0), (0, 10))], 20)
    assert river.river_type is None and river.version == 2 and river.unused_color_a == 0
    wave = new_wave(map, [(0, 0), (40, 0)])
    assert wave.texture is not None and wave.enable_pca_wave is not None
    assert wave.wave_particle_fx_name is None
    later = new_wave(water_map(wave_version=4), [(0, 0), (40, 0)])
    assert later.texture is None and later.enable_pca_wave is None
    assert later.wave_particle_fx_name == ""


def _written(write) -> bytes:
    buffer = io.BytesIO()
    write(WritingContext(BinaryStream(buffer)))
    return buffer.getvalue()


def _parsed(data: bytes, parse):
    return parse(ParsingContext(BinaryStream(io.BytesIO(data))))


@pytest.mark.parametrize("wave_version", [2, 4])
def test_new_areas_write_read_and_write_back_the_same_bytes(wave_version):
    map = water_map(wave_version)
    records = (
        (
            new_lake(map, [(0, 0), (10, 0), (10, 10)], 5),
            lambda area, context: area.write(context),
            StandingWaterArea.parse,
        ),
        (
            new_river(map, [((0, 0), (0, 10)), ((20, 0), (20, 10))], 5),
            lambda area, context: area.write(context),
            lambda context: RiverArea.parse(context, 2),
        ),
        (
            new_wave(map, [(0, 0), (40, 0)]),
            lambda area, context: area.write(context, wave_version),
            lambda context: StandingWaveArea.parse(context, wave_version),
        ),
    )
    for area, write, parse in records:
        data = _written(lambda context, area=area, write=write: write(area, context))
        again = _parsed(data, parse)
        assert again.name == area.name
        assert _written(lambda context, again=again, write=write: write(again, context)) == data


def test_outlines_contain_and_handles():
    map = water_map()
    river = new_river(map, [((0, 0), (0, 10)), ((20, 0), (20, 10)), ((40, 2), (40, 8))], 5)
    assert water_outline(river) == [(0, 0), (20, 0), (40, 2), (40, 8), (20, 10), (0, 10)]
    assert water_contains(river, 20, 5) and not water_contains(river, 50, 5)
    assert [handle for handle, _point in water_handles(river)][:3] == [(0, 0), (0, 1), (1, 0)]
    lake = new_lake(map, [(0, 0), (10, 0), (10, 10)], 5)
    assert water_handles(lake)[2] == ((2, None), (10.0, 10.0))
    assert not water_contains(new_wave(map, [(0, 0), (40, 0)]), 20, 0)


def test_add_delete_and_undo_keep_positions():
    map = water_map()
    document = MapDocument(map)
    lakes = [new_lake(map, [(0, 0), (1, 0), (1, 1)], 5) for _ in range(3)]
    for lake in lakes:
        document.execute(add_water(map, lake))
    river = new_river(map, [((0, 0), (0, 1))], 5)
    document.execute(add_water(map, river))
    assert all_water(map) == [*lakes, river]
    document.execute(DeleteWater([lakes[1], river]))
    assert map.standing_water_areas.areas == [lakes[0], lakes[2]] and not map.river_areas.areas
    document.stack.undo()
    assert map.standing_water_areas.areas == lakes and map.river_areas.areas == [river]


def test_moves_merge_change_lists_in_place_and_undo():
    map = water_map()
    document = MapDocument(map)
    river = new_river(map, [((0, 0), (0, 10))], 5)
    lake = new_lake(map, [(0, 0), (10, 0), (10, 10)], 5)
    document.execute(add_water(map, river))
    document.execute(add_water(map, lake))
    document.execute(add_river_line(river, ((20, 0), (20, 10))))
    lines = river.lines
    document.execute(MoveWater([river, lake], 5, 0))
    document.execute(MoveWater([river, lake], 0, 5))
    assert river.lines is lines
    assert river.lines == [((5, 5), (5, 15)), ((25, 5), (25, 15))]
    assert lake.points[0] == (5, 5)
    document.stack.undo()
    assert river.lines == [((0, 0), (0, 10)), ((20, 0), (20, 10))]
    document.stack.undo()
    assert river.lines == [((0, 0), (0, 10))]


def test_dragging_handles_moves_one_point_and_reports_water():
    map = water_map()
    document = MapDocument(map)
    river = new_river(map, [((0, 0), (0, 10))], 5)
    lake = new_lake(map, [(0, 0), (10, 0), (10, 10)], 5)
    seen = []
    document.subscribe(lambda change: seen.append(change.kind))
    document.execute(move_handle(river, (0, 1), (3, 12)))
    document.execute(move_handle(lake, (1, None), (11, 1)))
    assert river.lines == [((0, 0), (3, 12))] and lake.points[1] == (11, 1)
    assert seen == [ChangeKind.WATER, ChangeKind.WATER]
    document.stack.undo()
    document.stack.undo()
    assert river.lines == [((0, 0), (0, 10))] and lake.points[1] == (10.0, 0.0)


def test_default_height_is_the_lowest_ground_under_the_points():
    rows = np.full((20, 20), 2560, dtype=np.int64)
    rows[5, 5] = 1280
    grid = TerrainGrid(np.ascontiguousarray(rows), 0)
    low = 1280 * FEET_PER_HEIGHT_UNIT
    assert default_height(grid, [(50.0, 50.0), (100.0, 100.0)]) == pytest.approx(round(low))
    assert default_height(None, [(0.0, 0.0)]) == 0
