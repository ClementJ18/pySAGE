"""The 3D view's pure parts: the camera, the projection tools use, the terrain surface and ray
casts, and the chunked terrain mesh. No Qt or OpenGL."""

import math

import pytest

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.camera import MAX_PITCH, MIN_PITCH, Camera  # noqa: E402
from sage_worldbuilder.changes import Region  # noqa: E402
from sage_worldbuilder.projection import OFF_SCREEN, CameraProjection  # noqa: E402
from sage_worldbuilder.render.terrain_mesh import (  # noqa: E402
    chunk_boxes,
    chunk_vertices,
    chunks_touching,
    grid_indices,
)
from sage_worldbuilder.terrain.grid import TerrainGrid  # noqa: E402
from sage_worldbuilder.terrain.surface import ground_height, ground_heights, ray_hit  # noqa: E402


def camera(**settings):
    return Camera(**{"width": 800, "height": 600, **settings})


def ramp(columns=6, rows=5, border=1):
    """Stored heights `256 * column + 512 * row`: world height `10 * column + 20 * row`."""
    heights = np.arange(columns)[None, :] * 256 + np.arange(rows)[:, None] * 512
    return TerrainGrid(heights.astype(np.uint16), border)


def flat(size=11, stored=1024, border=0):
    return TerrainGrid(np.full((size, size), stored, dtype=np.uint16), border)


def test_the_target_projects_to_the_middle_of_the_widget():
    view = camera(target_x=120.0, target_y=-40.0, target_z=15.0, yaw=30.0, pitch=40.0)
    assert view.world_to_screen(120.0, -40.0, 15.0) == pytest.approx((400.0, 300.0))


def test_a_pixel_ray_passes_through_the_point_projected_there():
    view = camera(target_x=50, target_y=60, yaw=200, pitch=35, distance=700)
    point = np.array((130.0, 20.0, 40.0))
    origin, direction = view.ray(*view.world_to_screen(*point))
    closest = origin + direction * ((point - origin) @ direction)
    assert np.linalg.norm(closest - point) < 1e-6
    assert np.linalg.norm(direction) == pytest.approx(1.0)


def test_the_gl_matrix_agrees_with_the_projection():
    view = camera(yaw=75, pitch=60, distance=500, target_x=10)
    point = np.array((40.0, -30.0, 5.0, 1.0))
    clip = view.matrix() @ point
    ndc = clip[:3] / clip[3]
    sx, sy = view.world_to_screen(*point[:3])
    assert ((ndc[0] + 1) / 2 * 800, (1 - ndc[1]) / 2 * 600) == pytest.approx((sx, sy))
    assert -1 < ndc[2] < 1


def test_the_array_projection_matches_the_single_point_one():
    view = camera(yaw=310, pitch=25, distance=900, target_y=80)
    points = np.array(((0.0, 0.0, 0.0), (250.0, 400.0, 30.0), (-90.0, 60.0, -5.0)))
    pixels, in_front = view.project(points)
    assert in_front.all()
    for point, pixel in zip(points, pixels, strict=True):
        assert view.world_to_screen(*point) == pytest.approx(tuple(pixel))


def test_a_point_behind_the_camera_does_not_project():
    view = camera(pitch=10, distance=100)
    behind = view.eye - view.basis()[2] * 50
    assert view.world_to_screen(*behind) is None
    assert not view.project(behind[None, :])[1][0]


def test_looking_straight_down_east_is_right_and_north_is_up():
    view = camera(pitch=90, yaw=0, distance=1000)
    cx, cy = view.world_to_screen(0, 0, 0)
    ex, ey = view.world_to_screen(100, 0, 0)
    nx, ny = view.world_to_screen(0, 100, 0)
    assert ex > cx and ey == pytest.approx(cy)
    assert ny < cy and nx == pytest.approx(cx)


def test_zooming_about_a_point_keeps_it_under_the_same_pixel():
    view = camera(yaw=20, pitch=45, distance=1200)
    anchor = (300.0, 150.0, 0.0)
    before = view.world_to_screen(*anchor)
    view.zoom(1.5, anchor)
    assert view.distance == pytest.approx(800.0)
    assert view.world_to_screen(*anchor) == pytest.approx(before)


def test_pixels_per_unit_is_the_step_one_unit_makes_at_that_depth():
    view = camera(pitch=90, distance=1000)
    a, b = view.world_to_screen(0, 0, 0), view.world_to_screen(1, 0, 0)
    assert b[0] - a[0] == pytest.approx(view.pixels_per_unit_at((0, 0, 0)))


def test_orbiting_keeps_the_pitch_between_its_limits_and_wraps_the_yaw():
    view = camera(yaw=350)
    view.orbit(50, 10_000)
    assert view.pitch == MAX_PITCH
    assert view.yaw == pytest.approx(10.0)
    view.orbit(0, -10_000)
    assert view.pitch == MIN_PITCH


def test_panning_straight_down_moves_the_ground_under_the_cursor_across():
    view = camera(pitch=90, yaw=0, distance=1000)
    view.pan(80, 0)
    # Dragged right: the ground follows the mouse, so the target moves west by 80 pixels' worth.
    assert view.target_x == pytest.approx(-80 / view.pixels_per_unit_at(view.target))
    assert view.target_y == pytest.approx(0.0)


def test_fitting_shows_the_whole_rectangle():
    view = camera(pitch=90)
    view.fit(0, 0, 4000, 2000)
    for corner in ((0, 0, 0), (4000, 0, 0), (0, 2000, 0), (4000, 2000, 0)):
        sx, sy = view.world_to_screen(*corner)
        assert 0 <= sx <= 800 and 0 <= sy <= 600


def test_ground_height_is_bilinear_and_carries_the_edge_on():
    grid = ramp()
    x, y = grid.cell_to_world(2, 3)
    assert ground_height(grid, x, y) == pytest.approx(80.0)
    assert ground_height(grid, x + 5, y + 5) == pytest.approx(95.0)
    assert ground_height(grid, -1000.0, y) == pytest.approx(60.0)
    xs = np.array((x, x + 5, -1000.0, 1000.0))
    ys = np.array((y, y + 5, y, 1000.0))
    assert ground_heights(grid, xs, ys) == pytest.approx(
        [ground_height(grid, px, py) for px, py in zip(xs, ys, strict=True)]
    )


def test_a_ray_straight_down_hits_the_ground_below():
    grid = ramp()
    x, y = grid.cell_to_world(2, 3)
    assert ray_hit(grid, (x, y, 1000.0), (0.0, 0.0, -1.0)) == pytest.approx((x, y, 80.0))


def test_a_slanting_ray_hits_a_point_on_both_the_ray_and_the_ground():
    grid = ramp(columns=40, rows=30, border=0)
    origin = np.array((-50.0, -80.0, 900.0))
    direction = np.array((150.0, 120.0, 0.0)) - origin
    hit = ray_hit(grid, origin, direction)
    assert hit is not None
    assert hit[2] == pytest.approx(ground_height(grid, hit[0], hit[1]), abs=1e-3)
    unit = direction / np.linalg.norm(direction)
    offset = np.array(hit) - origin
    assert np.linalg.norm(offset - unit * (offset @ unit)) < 1e-6


def test_a_ray_that_misses_the_terrain_hits_nothing():
    grid = ramp()
    assert ray_hit(grid, (10.0, 10.0, 500.0), (0.0, 0.0, 1.0)) is None
    assert ray_hit(grid, (-500.0, -500.0, 500.0), (-1.0, 0.0, 0.0)) is None
    assert ray_hit(grid, (10.0, 10.0, 500.0), (0.0, 0.0, 0.0)) is None


def test_a_one_sample_heightmap_still_has_a_ground():
    grid = TerrainGrid(np.array([[256]], dtype=np.uint16), 0)
    assert ground_height(grid, 3.0, -7.0) == pytest.approx(10.0)
    assert ray_hit(grid, (0.0, 0.0, 50.0), (0.0, 0.0, -1.0)) == pytest.approx((0.0, 0.0, 10.0))


def test_the_projection_puts_the_ground_under_the_middle_pixel_at_the_target():
    view = camera(pitch=90, distance=500, target_x=50.0, target_y=50.0, target_z=40.0)
    projection = CameraProjection(view, flat())
    assert projection.screen_to_world(400, 300) == pytest.approx((50.0, 50.0))
    assert projection.focus == pytest.approx((50.0, 50.0, 40.0))
    assert projection.world_to_screen(50.0, 50.0) == pytest.approx((400.0, 300.0))
    assert projection.scale == pytest.approx(view.pixels_per_unit_at((50.0, 50.0, 40.0)))


def test_scale_at_a_place_does_not_follow_the_cursor():
    # A tilted camera: the near ground spans more pixels a unit than the far. `scale` follows the
    # last point under the cursor; `scale_at`, which sizes gizmos, only the place asked about.
    view = camera(pitch=40, distance=800, target_x=50.0, target_y=50.0, target_z=40.0)
    projection = CameraProjection(view, flat(size=101))
    before = projection.scale_at(50.0, 50.0)
    assert before == pytest.approx(view.pixels_per_unit_at((50.0, 50.0, 40.0)))
    projection.hit(400, 590)
    assert projection.scale != pytest.approx(before)
    assert projection.scale_at(50.0, 50.0) == pytest.approx(before)


def test_off_the_heightmap_the_projection_falls_back_to_the_last_ground_height():
    view = camera(pitch=60, distance=3000, target_x=50.0, target_y=50.0, target_z=40.0)
    projection = CameraProjection(view, flat())
    projection.screen_to_world(400, 300)
    x, y, z = projection.hit(0, 0)
    assert z == pytest.approx(40.0)
    assert not (0 <= x <= 100 and 0 <= y <= 100)
    assert projection.world_to_screen(*projection.screen_to_world(0, 0)) == pytest.approx((0, 0))


def test_a_ground_point_behind_the_camera_is_off_screen():
    view = camera(pitch=10, distance=50, target_x=50.0, target_y=50.0, target_z=40.0)
    projection = CameraProjection(view, flat())
    behind = view.eye - view.basis()[2] * 200
    assert projection.world_to_screen(float(behind[0]), float(behind[1])) == OFF_SCREEN
    view.yaw = 180.0
    projection.moved()
    assert projection.world_to_screen(float(behind[0]), float(behind[1])) != OFF_SCREEN


def test_an_outline_in_front_of_the_camera_keeps_every_corner():
    view = camera(pitch=60, distance=4000, target_x=50.0, target_y=50.0)
    projection = CameraProjection(view, flat(size=11, border=0))
    corners = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    path = projection.ground_path(corners, closed=True)
    for corner in corners:
        pixel = projection.project(*corner)
        assert any(point == pytest.approx(pixel) for point in path)


def test_an_outline_reaching_behind_the_camera_is_cut_at_the_near_plane():
    """The map's boundary rectangle stays drawn when the camera stands inside it: the corners
    behind it are cut off, not the whole outline."""
    view = camera(pitch=20, distance=300, target_x=500.0, target_y=500.0)
    projection = CameraProjection(view, flat(size=101, border=0))
    corners = [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)]
    assert projection.project(0.0, 0.0) is None
    path = projection.ground_path(corners, closed=True)
    assert len(path) > 2
    assert any(0 <= x <= view.width and 0 <= y <= view.height for x, y in path)
    # The cut corners go below the widget, where the ground passes the camera.
    assert max(y for _x, y in path) > view.height


def test_an_outline_wholly_behind_the_camera_is_not_drawn():
    view = camera(pitch=20, distance=300, target_x=500.0, target_y=500.0, yaw=180.0)
    projection = CameraProjection(view, flat(size=101, border=0))
    assert projection.ground_path([(0.0, 900.0), (100.0, 1000.0)]) == []


def test_chunks_cover_every_cell_and_share_their_edges():
    assert chunk_boxes(130, 70, 64) == [
        (0, 0, 64, 64),
        (64, 0, 128, 64),
        (128, 0, 129, 64),
        (0, 64, 64, 69),
        (64, 64, 128, 69),
        (128, 64, 129, 69),
    ]
    assert chunk_boxes(1, 5) == []
    assert chunk_boxes(5, 1) == []


def test_each_cell_is_two_counter_clockwise_triangles():
    indices = grid_indices(3, 2)
    assert indices.tolist() == [0, 1, 4, 0, 4, 3, 1, 2, 5, 1, 5, 4]


def test_chunk_vertices_are_the_samples_in_world_space_with_their_normals():
    grid = ramp()
    vertices = chunk_vertices(grid, (0, 0, 5, 4))
    assert vertices.shape == (30, 6)
    x, y = grid.cell_to_world(2, 3)
    assert vertices[3 * 6 + 2, :3] == pytest.approx((x, y, 80.0))
    # The ramp rises 1 unit per unit east and 2 per unit north.
    normal = np.array((-1.0, -2.0, 1.0)) / math.sqrt(6)
    assert vertices[:, 3:] == pytest.approx(np.tile(normal, (30, 1)), abs=1e-6)


def test_a_chunk_agrees_with_the_same_samples_of_a_larger_chunk():
    heights = np.random.default_rng(4).integers(0, 4000, size=(9, 12)).astype(np.uint16)
    grid = TerrainGrid(heights, 2)
    whole = chunk_vertices(grid, (0, 0, 11, 8)).reshape(9, 12, 6)
    part = chunk_vertices(grid, (3, 2, 7, 5)).reshape(4, 5, 6)
    assert part == pytest.approx(whole[2:6, 3:8])


def test_an_edit_touches_the_chunks_holding_its_samples_and_their_neighbours_normals():
    boxes = chunk_boxes(130, 130, 64)
    assert chunks_touching(boxes, Region(10, 10, 20, 20)) == [0]
    # Sample 64 is on the edge two chunks share; sample 63's normal reads sample 64.
    assert chunks_touching(boxes, Region(60, 10, 64, 20)) == [0, 1]
    assert chunks_touching(boxes, Region(65, 65, 66, 66)) == [0, 1, 3, 4]
