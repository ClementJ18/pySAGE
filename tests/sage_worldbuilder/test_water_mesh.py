"""Water surfaces for the 3D view: the game's lake grid, river strips, depths, and the look each
area is drawn with."""

import pytest

from sage_map.assets.environment_data import EnvironmentData
from sage_map.assets.river_areas import RiverAreas
from sage_map.assets.standing_water_area import StandingWaterAreas
from sage_map.assets.standing_waves_area import StandingWaveAreas
from sage_map.map import Map
from sage_worldbuilder.water import new_lake, new_river

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.render.water_mesh import (  # noqa: E402
    LAKE_CELL,
    lake_look,
    lake_mesh,
    river_look,
    river_mesh,
)
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, TerrainGrid  # noqa: E402


def water_map():
    map = Map()
    map.standing_water_areas = StandingWaterAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.river_areas = RiverAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.standing_wave_areas = StandingWaveAreas(version=2, areas=[], start_pos=0, end_pos=0)
    return map


def test_a_lake_is_a_grid_of_cells_whose_centres_are_inside_at_the_water_height():
    square = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    mesh = lake_mesh(square, 42)
    assert mesh is not None
    # 100 units of 20-unit cells: 5 x 5 inside, plus the column and row the far edge starts.
    assert mesh.indices.size == 5 * 5 * 6
    assert set(mesh.positions[:, 2].tolist()) == {42.0}
    used = mesh.positions[np.unique(mesh.indices)]
    assert used[:, 0].min() == 0.0 and used[:, 0].max() == 100.0
    triangle = [(0.0, 0.0), (100.0, 0.0), (0.0, 100.0)]
    assert lake_mesh(triangle, 1).indices.size < mesh.indices.size
    assert lake_mesh(square[:2], 1) is None


def test_a_large_lake_doubles_its_cells_to_stay_under_the_point_limit():
    big = [(0.0, 0.0), (10_000.0, 0.0), (10_000.0, 10_000.0), (0.0, 10_000.0)]
    mesh = lake_mesh(big, 5)
    assert len(mesh.positions) <= 60_000
    xs = np.unique(mesh.positions[:, 0])
    # 20 units would be 501 x 501 points, 40 still 251 x 251: 80 is the first to fit.
    assert xs[1] - xs[0] == LAKE_CELL * 4


def test_depths_are_the_water_above_the_ground():
    heights = np.full((30, 30), 2560, dtype=np.int64)  # 100 ft
    grid = TerrainGrid(np.ascontiguousarray(heights), 0)
    square = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    mesh = lake_mesh(square, 130, grid)
    assert mesh.depths == pytest.approx(
        np.full(mesh.depths.shape, 130 - 2560 * FEET_PER_HEIGHT_UNIT)
    )
    assert lake_mesh(square, 90, grid).depths.max() == 0.0


def test_a_river_is_a_strip_across_from_left_to_right():
    lines = [((0.0, 0.0), (0.0, 40.0)), ((80.0, 0.0), (80.0, 40.0)), ((160.0, 0.0), (160.0, 40.0))]
    mesh = river_mesh(lines, 12)
    assert len(mesh.positions) == 6 and mesh.indices.size == 12
    assert mesh.uvs[:, 0].tolist() == [0.0, 1.0] * 3
    # Along the river, one repeat per width (40): 80 units is 2.
    assert mesh.uvs[:, 1].tolist() == [0.0, 0.0, 2.0, 2.0, 4.0, 4.0]
    assert river_mesh(lines[:1], 12) is None


def test_the_looks_of_a_lake_and_a_river():
    map = water_map()
    lake = new_lake(map, [(0, 0), (1, 0), (1, 1)], 5)
    environment = EnvironmentData(3, 8.0, 0.9, False, "", "", None, None, 0, 0)
    material = {
        "waterenvtexture": "WtrEnv_Default.tga",
        "materialcolordiffuse": (0.3, 0.38, 0.28, 0.5),
        "envuvscale": (0.4, 0.4, 0.0, 0.0),
    }
    look = lake_look(lake, material, environment)
    assert look.texture == "WtrEnv_Default.tga" and look.color == (0.3, 0.38, 0.28, 0.5)
    assert look.uv_scale == pytest.approx(0.4 / LAKE_CELL)
    assert look.depth_alpha == (8.0, 0.9) and not look.additive
    plain = lake_look(lake, None, None)
    assert plain.texture is None and plain.depth_alpha is None
    river = new_river(map, [((0, 0), (0, 1))], 5)
    river.color = (255, 128, 0)
    look = river_look(river)
    assert look.texture == river.river_texture and look.opacity_texture == river.alpha_edge_texture
    assert look.color == pytest.approx((1.0, 128 / 255, 0.0, river.alpha))
    assert look.additive == river.use_additive_blending and look.reflection is None


def test_the_lake_grid_matches_the_single_point_test_for_a_concave_outline():
    from sage_worldbuilder.areas import area_contains  # noqa: PLC0415

    notch = [(0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (100.0, 60.0), (0.0, 200.0)]
    mesh = lake_mesh(notch, 1)
    cells = set()
    for a, _b, d in mesh.indices.reshape(-1, 6)[:, :3]:
        x0, y0 = mesh.positions[a][:2]
        x1, y1 = mesh.positions[d][:2]
        cells.add(((x0 + x1) / 2, (y0 + y1) / 2))
    for x in np.arange(10.0, 220.0, 20.0):
        for y in np.arange(10.0, 220.0, 20.0):
            assert ((x, y) in cells) == area_contains(notch, x, y)
