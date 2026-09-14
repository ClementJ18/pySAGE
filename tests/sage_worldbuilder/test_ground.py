"""Adjust Terrain to GROUND Objects: the ground under the objects' `.GROUND` meshes."""

from types import SimpleNamespace

import pytest

from sage_worldbuilder.objects import new_object
from sage_worldbuilder.waypoints import new_waypoint

# A 40 x 40 pad at 8 feet, as two triangles.


np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.ground import (  # noqa: E402
    GroundPlacement,
    adjust_heights,
    ground_placements,
    ground_triangles,
)
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402
from sage_worldbuilder.terrain import TerrainGrid  # noqa: E402
from sage_worldbuilder.terrain.grid import FEET_PER_HEIGHT_UNIT  # noqa: E402

PAD = np.array(
    [
        [(-20.0, -20.0, 8.0), (20.0, -20.0, 8.0), (20.0, 20.0, 8.0)],
        [(-20.0, -20.0, 8.0), (20.0, 20.0, 8.0), (-20.0, 20.0, 8.0)],
    ]
)


def _mesh(name, positions, indices):
    return SimpleNamespace(name=name, positions=np.array(positions), indices=np.array(indices))


def _grid(size=24, height=0):
    map = new_map(NewMapOptions(width=size, height=size, border=0, initial_height=height))
    return map, TerrainGrid.from_height_map(map.height_map_data)


def test_only_ground_meshes_are_taken():
    scene = SimpleNamespace(
        meshes=[
            _mesh("Keep.GROUND", [(0, 0, 1), (1, 0, 1), (0, 1, 1)], [0, 1, 2]),
            _mesh("keep_walls", [(0, 0, 9), (1, 0, 9), (0, 1, 9)], [0, 1, 2]),
            _mesh("BASE.ground", [(2, 0, 3), (3, 0, 3), (2, 1, 3)], [0, 1, 2]),
            _mesh("Broken.GROUND", [(0, 0, 1)], [0, 1, 2]),
        ]
    )

    triangles = ground_triangles(scene)

    assert triangles.shape == (2, 3, 3)
    assert sorted(triangle[0][2] for triangle in triangles) == [1.0, 3.0]
    assert ground_triangles(SimpleNamespace(meshes=[])).shape == (0, 3, 3)


def test_a_pad_raises_the_samples_under_it_and_leaves_the_rest():
    map, grid = _grid()
    placement = GroundPlacement(100.0, 100.0, 0.0, 0.0, 1.0, PAD)

    x0, y0, values = adjust_heights(grid, [placement])

    expected = int(np.floor(8.0 / FEET_PER_HEIGHT_UNIT + 0.5))
    raised = values == expected
    assert raised.any()
    # The pad covers cells 8 to 12 either way: every raised sample is inside it.
    rows, columns = np.nonzero(raised)
    assert set(columns + x0) <= set(range(8, 13)) and set(rows + y0) <= set(range(8, 13))
    assert (values[~raised] == 0).all()


def test_the_highest_pad_wins_and_scale_angle_and_height_count():
    _, grid = _grid()
    low = GroundPlacement(100.0, 100.0, 0.0, 0.0, 1.0, PAD)
    high = GroundPlacement(100.0, 100.0, 4.0, 0.0, 1.0, PAD)

    _, _, values = adjust_heights(grid, [low, high])
    assert values.max() == int(np.floor(12.0 / FEET_PER_HEIGHT_UNIT + 0.5))

    _, _, scaled = adjust_heights(grid, [GroundPlacement(100.0, 100.0, 0.0, 0.0, 2.0, PAD)])
    assert scaled.max() == int(np.floor(16.0 / FEET_PER_HEIGHT_UNIT + 0.5))
    # A pad twice as wide reaches further: more samples change.
    assert (scaled > 0).sum() > (values > 0).sum()

    turned = np.array([[(-40.0, -5.0, 8.0), (40.0, -5.0, 8.0), (40.0, 5.0, 8.0)]])
    _, _, flat = adjust_heights(grid, [GroundPlacement(100.0, 100.0, 0.0, 0.0, 1.0, turned)])
    _, _, upright = adjust_heights(
        grid, [GroundPlacement(100.0, 100.0, 0.0, np.pi / 2, 1.0, turned)]
    )
    assert np.count_nonzero(flat) == np.count_nonzero(upright)
    assert flat.shape != upright.shape or not np.array_equal(flat, upright)


def test_ground_that_is_not_above_the_map_changes_nothing():
    _, grid = _grid(height=0)
    below = np.array([[(-20.0, -20.0, -3.0), (20.0, -20.0, -3.0), (20.0, 20.0, -3.0)]])

    assert adjust_heights(grid, []) is None
    assert adjust_heights(grid, [GroundPlacement(100.0, 100.0, 0.0, 0.0, 1.0, below)]) is None
    # A pad at the height the ground already has is no change either.
    map, flat_grid = _grid(height=8)
    assert adjust_heights(flat_grid, [GroundPlacement(100.0, 100.0, 0.0, 0.0, 1.0, PAD)]) is None
    assert map.height_map_data is not None


def test_placements_skip_waypoints_and_models_without_ground():
    map, _ = _grid()
    keep = new_object(map, "Keep", (100.0, 100.0, 0.0), 0.5, "/team")
    tree = new_object(map, "Tree", (50.0, 50.0, 0.0), 0.0, "/team")
    waypoint = new_waypoint(map, (10.0, 10.0, 0.0))
    map.objects_list.object_list += [keep, tree, waypoint]

    placements = ground_placements(map, {"Keep": PAD, waypoint.type_name: PAD})

    assert [(p.x, p.y, p.angle) for p in placements] == [(100.0, 100.0, 0.5)]
