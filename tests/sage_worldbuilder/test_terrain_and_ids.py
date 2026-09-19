"""The heightmap array and its coordinates, and free ids and names for new map items."""

import pytest

from sage_map.assets.height_map import HeightMapBorder, HeightMapData
from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import Change, ChangeKind, MapDocument
from sage_worldbuilder.ids import (
    new_unique_id,
    new_waypoint_name,
    next_trigger_area_id,
    next_unique_number,
    next_waypoint_id,
)

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.terrain import TerrainGrid  # noqa: E402


def height_map(width: int = 4, height: int = 3, border: int = 1) -> HeightMapData:
    # Row 0 is the top of the map; each value encodes (column, row counted from the bottom).
    elevations = [
        [10 * (height - 1 - row) + column for column in range(width)] for row in range(height)
    ]
    return HeightMapData(
        version=5,
        width=width,
        height=height,
        border_width=border,
        borders=[
            HeightMapBorder(corner1=(0, 0), position=(width - 2 * border, height - 2 * border))
        ],
        area=width * height,
        min_height=0,
        max_height=0,
        elevations=elevations,
        start_pos=0,
        end_pos=0,
    )


def prop(name, value, kind=AssetPropertyType.AsciiString):
    return {"name": name, "type": kind, "value": value}


def placed(type_name: str, **properties) -> Object:
    stored = {
        key: prop(
            key,
            value,
            AssetPropertyType.Integer if isinstance(value, int) else AssetPropertyType.AsciiString,
        )
        for key, value in properties.items()
    }
    return Object(3, (0.0, 0.0, 0.0), 0.0, 0, type_name, stored, 0, 0)


def map_with(objects=(), areas=()) -> Map:
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=list(objects), start_pos=0, end_pos=0)
    map.trigger_areas = TriggerAreas(version=1, trigger_areas=list(areas), start_pos=0, end_pos=0)
    return map


def test_heights_count_rows_from_the_bottom():
    grid = TerrainGrid.from_height_map(height_map())
    assert (grid.width, grid.height) == (4, 3)
    assert grid.heights[0, 0] == 0
    assert grid.heights[2, 3] == 23
    assert not grid.heights.flags.writeable


def test_world_positions_start_inside_the_border():
    grid = TerrainGrid.from_height_map(height_map(border=1))
    assert grid.world_to_cell(0.0, 0.0) == (1.0, 1.0)
    assert grid.cell_to_world(3.0, 2.0) == (20.0, 10.0)
    assert grid.elevation_at(0.0, 0.0) == 11
    # World (14, 6) is cell (2.4, 1.6), nearest the sample at column 2, row 2.
    assert grid.elevation_at(14.0, 6.0) == 22
    assert grid.nearest_cell(-20.0, 0.0) is None
    assert grid.elevation_at(0.0, 20.0) is None


def test_mismatched_elevations_are_rejected():
    data = height_map()
    data.elevations.pop()
    with pytest.raises(ValueError):
        TerrainGrid.from_height_map(data)


def test_document_rebuilds_terrain_only_after_a_terrain_change():
    map = Map()
    map.height_map_data = height_map()
    document = MapDocument(map)
    grid = document.terrain
    assert grid is not None
    document.notify(Change(ChangeKind.OBJECTS))
    assert document.terrain is grid
    map.height_map_data.elevations[0][0] = 99
    document.notify(Change(ChangeKind.TERRAIN))
    assert document.terrain is not grid
    assert document.terrain.heights[2, 0] == 99


def test_document_without_a_heightmap_has_no_terrain():
    assert MapDocument(Map()).terrain is None


def test_unique_ids_continue_past_the_highest_number():
    map = map_with(
        [placed("GondorFighter", uniqueID="GondorFighter 4"), placed("Tree", uniqueID="Tree 9")]
    )
    assert next_unique_number(map) == 10
    assert new_unique_id(map, "Rock") == "Rock 10"
    assert next_unique_number(map_with()) == 0


def test_waypoint_ids_and_names():
    map = map_with(
        [
            placed("*Waypoints/Waypoint", waypointID=1, waypointName="Start", uniqueID="Start"),
            placed(
                "*Waypoints/Waypoint",
                waypointID=2,
                waypointName="Waypoint 7",
                uniqueID="Waypoint 7",
            ),
        ]
    )
    assert next_waypoint_id(map) == 3
    assert new_waypoint_name(map) == "Waypoint 8"
    assert next_waypoint_id(map_with()) == 1
    assert new_waypoint_name(map_with()) == "Waypoint 1"


def test_trigger_area_ids_skip_past_deleted_ones():
    areas = [TriggerArea("A", "", 1, [], 0), TriggerArea("B", "", 5, [], 0)]
    assert next_trigger_area_id(map_with(areas=areas)) == 6
    assert next_trigger_area_id(Map()) == 1
