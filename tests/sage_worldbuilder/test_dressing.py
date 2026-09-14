"""World dressing: scorch marks, groves, fences, ramps, borders and mesh molds as map data."""

import math
from types import SimpleNamespace

import pytest

from sage_map.assets.height_map import HeightMapBorder, HeightMapData
from sage_map.assets.object_list import ObjectsList
from sage_map.assets.river_areas import RiverAreas
from sage_map.assets.standing_water_area import StandingWaterAreas
from sage_map.assets.standing_waves_area import StandingWaveAreas
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.water import new_lake

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.dressing import (  # noqa: E402
    DEFAULT_SCORCH_SIZE,
    NEUTRAL_OWNER,
    GroveOptions,
    MoldMode,
    MoldOptions,
    ResizeBorder,
    add_border,
    cluster_points,
    fence_objects,
    fence_points,
    grove_objects,
    list_molds,
    mold_patch,
    mold_triangles,
    new_scorch,
    pick_tree,
    playable_size,
    ramp_patch,
    rectangle_points,
    remove_border,
)
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, TerrainGrid  # noqa: E402


def flat_map(size=40, border=2, height=2560):
    map = Map()
    map.height_map_data = HeightMapData(
        version=5,
        width=size,
        height=size,
        border_width=border,
        borders=[HeightMapBorder((0, 0), (size - 2 * border, size - 2 * border))],
        area=size * size,
        min_height=0,
        max_height=0,
        elevations=[[height] * size for _ in range(size)],
        start_pos=0,
        end_pos=0,
    )
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.standing_water_areas = StandingWaterAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.river_areas = RiverAreas(version=2, areas=[], start_pos=0, end_pos=0)
    map.standing_wave_areas = StandingWaveAreas(version=2, areas=[], start_pos=0, end_pos=0)
    return map


def grid_of(map):
    return TerrainGrid.from_height_map(map.height_map_data)


def test_a_scorch_mark_takes_the_corpus_form():
    scorch = new_scorch(flat_map(), (50.0, 60.0), 3, DEFAULT_SCORCH_SIZE, layer="L")
    assert scorch.type_name == "Scorch" and scorch.position == (50.0, 60.0, 0.0)
    assert list(scorch.properties) == [
        "objectInitialHealth",
        "objectEnabled",
        "objectIndestructible",
        "objectUnsellable",
        "objectPowered",
        "objectRecruitableAI",
        "objectTargetable",
        "objectBasePriority",
        "objectBasePhase",
        "originalOwner",
        "uniqueID",
        "objectLayer",
        "scorchType",
        "objectRadius",
    ]
    assert scorch.properties["scorchType"]["type"] is AssetPropertyType.Integer
    assert scorch.properties["objectRadius"] == {
        "name": "objectRadius",
        "type": AssetPropertyType.RealNumber,
        "value": 20.0,
    }
    assert scorch.properties["originalOwner"]["value"] == NEUTRAL_OWNER


def test_trees_are_drawn_by_weight():
    rng = np.random.default_rng(1)
    options = GroveOptions(trees=[("Oak", 75), ("Pine", 25), ("", 50), ("Birch", 0)])
    drawn = [pick_tree(options, rng) for _ in range(4000)]
    assert set(drawn) == {"Oak", "Pine"}
    assert drawn.count("Oak") / len(drawn) == pytest.approx(0.75, abs=0.03)
    assert pick_tree(GroveOptions(trees=[("Oak", 0)]), rng) is None


def test_grove_points_fill_a_rectangle_or_a_disc():
    rng = np.random.default_rng(2)
    points = rectangle_points(rng, 50, (100.0, 200.0), (0.0, 0.0))
    assert len(points) == 50 and all(0 <= x <= 100 and 0 <= y <= 200 for x, y in points)
    disc = cluster_points(rng, 25, (500.0, 500.0))
    assert len(disc) == 25
    assert max(math.hypot(x - 500, y - 500) for x, y in disc) <= 20.0 * 5 / 2 + 1e-9


def test_a_grove_skips_water_and_cliffs_unless_allowed_and_numbers_its_trees():
    map = flat_map()
    map.standing_water_areas.areas.append(
        new_lake(map, [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)], 200)
    )
    rng = np.random.default_rng(3)
    options = GroveOptions(trees=[("Oak", 100)])
    points = [(50.0, 50.0), (250.0, 250.0), (260.0, 250.0)]
    trees = grove_objects(map, points, options, rng, grid_of(map), layer="Trees")
    assert [tree.position[:2] for tree in trees] == [(250.0, 250.0), (260.0, 250.0)]
    assert [tree.properties["uniqueID"]["value"] for tree in trees] == ["Oak 0", "Oak 1"]
    assert all(tree.properties["originalOwner"]["value"] == NEUTRAL_OWNER for tree in trees)
    options.allow_water = True
    assert len(grove_objects(map, points, options, rng, grid_of(map))) == 3
    cliff = flat_map()
    rows = cliff.height_map_data.elevations
    for row in rows:
        for column in range(20, 40):
            row[column] = 25600  # 1,000 ft: a wall at column 20
    cliff_trees = grove_objects(
        cliff, [(170.0, 100.0), (60.0, 100.0)], GroveOptions([("Oak", 100)]), rng, grid_of(cliff)
    )
    assert [tree.position[:2] for tree in cliff_trees] == [(60.0, 100.0)]


def test_fence_posts_space_along_the_line_or_stretch_to_its_end():
    points, angle = fence_points((0.0, 0.0), (100.0, 0.0), 30.0)
    assert points == [(0.0, 0.0), (30.0, 0.0), (60.0, 0.0), (90.0, 0.0)]
    assert angle == 0.0
    stretched, _ = fence_points((0.0, 0.0), (100.0, 0.0), 30.0, stretch=True)
    assert len(stretched) == 4 and stretched[-1] == pytest.approx((100.0, 0.0))
    posts = fence_objects(flat_map(), "Fence01", (0.0, 0.0), (0.0, 60.0), 30.0, "Player/team")
    assert [post.properties["uniqueID"]["value"] for post in posts] == [
        "Fence01 0",
        "Fence01 1",
        "Fence01 2",
    ]
    assert all(post.angle == pytest.approx(math.pi / 2) for post in posts)
    assert fence_points((5.0, 5.0), (5.0, 5.0), 30.0)[0] == [(5.0, 5.0)]


def test_a_ramp_slopes_evenly_between_the_ground_at_its_ends():
    map = flat_map(border=0)
    rows = map.height_map_data.elevations
    for row in rows:
        for column in range(40):
            row[column] = 2560 if column < 20 else 5120
    grid = grid_of(map)
    patch = ramp_patch(grid, (100.0, 200.0), (300.0, 200.0), 20.0)
    low, high = 2560, 5120
    row = 200 // 10 - patch.y0
    start, middle, end = (column - patch.x0 for column in (10, 20, 30))
    assert patch.values[row, start] == low and patch.values[row, end] == high
    assert patch.values[row, middle] == pytest.approx((low + high) / 2, abs=1)
    # A 20-unit ramp reaches one cell either side of its line, and the patch holds only those.
    assert patch.values.shape[0] == 3 and patch.y0 == 200 // 10 - 1


def test_borders_are_added_resized_as_one_drag_and_removed():
    map = flat_map(size=40, border=5)
    document = MapDocument(map)
    borders = map.height_map_data.borders
    assert playable_size(map) == (30, 30)
    document.execute(add_border(map, (10, 12)))
    added = borders[1]
    assert (added.corner1, added.position) == ((0, 0), (10, 12))
    document.execute(ResizeBorder(added, (11, 12)))
    document.execute(ResizeBorder(added, (14, 15)))
    assert added.position == (14, 15)
    document.stack.undo()
    assert added.position == (10, 12)
    document.execute(remove_border(map, borders[0]))
    assert borders == [added]
    document.stack.undo()
    assert len(borders) == 2


def square_mold(size=20.0, top=8.0):
    """A flat-topped box `size` across, `top` high, as a scene of two top triangles."""
    s = size / 2
    positions = [-s, -s, top, s, -s, top, s, s, top, -s, s, top]
    return SimpleNamespace(
        meshes=[SimpleNamespace(positions=positions, indices=[0, 1, 2, 0, 2, 3])]
    )


def test_a_mold_sets_the_heights_under_it():
    map = flat_map(size=40, border=0, height=0)
    grid = grid_of(map)
    triangles = mold_triangles(square_mold())
    assert triangles.shape == (2, 3, 3)
    patch = mold_patch(grid, triangles, (200.0, 200.0), MoldOptions(scale=2.0, height=10.0))
    values = np.array(grid.heights, dtype=np.int64)
    values[
        patch.y0 : patch.y0 + patch.values.shape[0], patch.x0 : patch.x0 + patch.values.shape[1]
    ] = patch.values
    expected = round((8.0 * 2 + 10.0) / FEET_PER_HEIGHT_UNIT)
    # At scale 2 the mold covers 40 units: samples 18-22 either way of the centre sample 20.
    assert values[20, 20] == expected and values[18, 22] == expected
    assert values[20, 24] == 0 and values[15, 20] == 0


def test_a_mold_turns_and_raises_or_lowers_only():
    map = flat_map(size=40, border=0, height=round(12 / FEET_PER_HEIGHT_UNIT))
    grid = grid_of(map)
    long = SimpleNamespace(
        meshes=[
            SimpleNamespace(
                positions=[-40, -5, 20, 40, -5, 20, 40, 5, 20, -40, 5, 20],
                indices=[0, 1, 2, 0, 2, 3],
            )
        ]
    )
    triangles = mold_triangles(long)
    turned = mold_patch(grid, triangles, (200.0, 200.0), MoldOptions(angle=90.0))
    row, column = 20 - turned.y0, 20 - turned.x0
    assert turned.values[row + 3, column] > grid.heights[23, 20]  # along y after a quarter turn
    assert turned.values[row, column + 3] == grid.heights[20, 23]
    assert mold_patch(grid, triangles, (200.0, 200.0), MoldOptions(mode=MoldMode.LOWER)) is None
    assert mold_patch(grid, triangles, (200.0, 200.0), MoldOptions(mode=MoldMode.RAISE)) is not None


def test_molds_are_listed_from_the_game_data():
    entries = [
        SimpleNamespace(path=p)
        for p in (
            "data\\editor\\molds\\ramp.w3d",
            "data\\editor\\molds\\Bowl.w3d",
            "data\\editor\\molds\\readme.txt",
        )
    ]
    filesystem = SimpleNamespace(listdir=lambda folder: entries)
    assert list_molds(filesystem) == ["Bowl.w3d", "ramp.w3d"]
