"""Resize: the terrain kept at its anchor, new cells, shifted positions, and undo."""

import io

import pytest

from sage_map.assets.object_list import Object
from sage_map.assets.trigger_areas import TriggerArea
from sage_map.map import parse_map, write_map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.heightmap_io import Anchor  # noqa: E402
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402
from sage_worldbuilder.resize import ResizeMap, ResizeOptions, world_shift  # noqa: E402
from sage_worldbuilder.terrain.cells import CellLayer  # noqa: E402


def sample_map():
    map = new_map(NewMapOptions(width=20, height=16, border=2, initial_height=0.0, texture="Rock"))
    rows = map.height_map_data.elevations
    for saved_row, row in enumerate(rows):
        for column in range(len(row)):
            row[column] = (15 - saved_row) * 100 + column
    map.blend_tile_data.impassability[3][4] = True
    map.objects_list.object_list.append(Object(3, (50.0, 30.0, 0.0), 0.0, 0, "Tree", {}, 0, 0))
    map.trigger_areas.trigger_areas.append(TriggerArea("Zone", "", 1, [(0.0, 0.0), (10.0, 5.0)], 0))
    return map


def test_growing_at_the_top_right_keeps_the_bottom_left_and_moves_nothing_but_the_border():
    map = sample_map()
    options = ResizeOptions(width=30, height=20, border=4, anchor=Anchor.BOTTOM_LEFT, fill_height=7)
    # Pinned bottom-left, the old cells keep their samples; the border grew by 2 cells, so the
    # inner corner moved right and up by 2 cells and positions count 20 world units less.
    assert world_shift(map.height_map_data, options) == (-20.0, -20.0)
    document = MapDocument(map)
    before = document.to_bytes(compress=False)
    document.execute(ResizeMap(map, options))

    heights = document.terrain.heights
    assert heights.shape == (20, 30)
    assert heights[0, 0] == 0 and heights[15, 19] == 1519
    assert heights[19, 29] == 7 and heights[0, 25] == 7
    assert document.cells(CellLayer.IMPASSABLE)[4, 3]
    assert document.cells(CellLayer.VISIBLE)[19, 29]
    assert map.objects_list.object_list[0].position == (30.0, 10.0, 0.0)
    assert map.trigger_areas.trigger_areas[0].points == [(-20.0, -20.0), (-10.0, -15.0)]
    assert map.height_map_data.borders[0].position == (22, 12)

    reopened = parse_map(io.BytesIO(document.to_bytes(compress=False)))
    assert (reopened.height_map_data.width, reopened.height_map_data.height) == (30, 20)
    assert len(reopened.blend_tile_data.tiles) == 30
    assert len(reopened.blend_tile_data.impassability[0]) == 20

    document.stack.undo()
    assert document.to_bytes(compress=False) == before


def test_shrinking_about_the_centre_crops_both_sides():
    map = sample_map()
    options = ResizeOptions(width=10, height=8, border=2, anchor=Anchor.CENTER)
    document = MapDocument(map)
    document.execute(ResizeMap(map, options))
    heights = document.terrain.heights
    assert heights.shape == (8, 10)
    # Cropped 5 columns and 4 rows from each side.
    assert heights[0, 0] == 4 * 100 + 5
    assert map.objects_list.object_list[0].position == (0.0, -10.0, 0.0)
    assert len(write_map(map, compress=False)) > 0


def test_resize_options_are_checked():
    with pytest.raises(ValueError):
        ResizeOptions(width=8, height=8, border=4).validate()


def test_polygon_triggers_and_camera_animation_frames_move_too():
    from types import SimpleNamespace  # noqa: PLC0415

    map = sample_map()
    trigger = SimpleNamespace(points=[(10, 20, 5)])
    map.polygon_triggers = SimpleNamespace(polygon_triggers=[trigger])
    free = SimpleNamespace(frames=[SimpleNamespace(position=(1.0, 2.0, 3.0))])
    look_at = SimpleNamespace(
        camera_frames=[SimpleNamespace(position=(4.0, 5.0, 6.0))],
        look_at_frames=[SimpleNamespace(look_at_point=(7.0, 8.0, 9.0))],
    )
    map.camera_animation_list.animations = [
        SimpleNamespace(frame_data=free),
        SimpleNamespace(frame_data=look_at),
    ]
    options = ResizeOptions(width=30, height=16, border=2, anchor=Anchor.RIGHT)
    document = MapDocument(map)
    document.execute(ResizeMap(map, options))
    # Pinned right: the old map starts 10 cells further right, 100 world units.
    assert trigger.points == [(110, 20, 5)]
    assert free.frames[0].position == (101.0, 2.0, 3.0)
    assert look_at.camera_frames[0].position == (104.0, 5.0, 6.0)
    assert look_at.look_at_frames[0].look_at_point == (107.0, 8.0, 9.0)
    document.stack.undo()
    assert trigger.points == [(10, 20, 5)] and free.frames[0].position == (1.0, 2.0, 3.0)
