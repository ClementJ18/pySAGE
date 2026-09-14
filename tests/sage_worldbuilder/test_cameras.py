"""Named cameras and camera animations: names, key edits, WorldBuilder's interpolation, and the
conversions between poses and the 3D view's camera."""

import math

import pytest

from sage_map.assets.camera_animation_list import (
    CameraAnimationList,
    FreeCameraAnimationCameraFrame,
    LookAtCameraAnimationCameraFrame,
    LookAtCameraAnimationLookAtFrame,
)
from sage_map.assets.named_cameras import NamedCameras
from sage_map.map import Map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.cameras import (  # noqa: E402
    CAMERA_FORWARD,
    FREE,
    LINEAR,
    LOOK,
    SPLINE,
    CameraView,
    Pose,
    _catmull_rom,
    _rotate,
    add_animation,
    add_named_camera,
    animation_length_error,
    camera_keys,
    copy_animation,
    delete_key,
    evaluate,
    look_at_keys,
    look_rotation,
    named_camera_from_view,
    named_camera_view,
    new_animation,
    new_animation_name,
    new_camera_name,
    pose_view,
    remove_animation,
    set_camera_key,
    set_interpolation,
    set_look_at_key,
    view_pose,
)


def camera_map():
    map = Map()
    map.named_cameras = NamedCameras(version=2, cameras=[], start_pos=0, end_pos=0)
    map.camera_animation_list = CameraAnimationList(
        version=3, animations=[], start_pos=0, end_pos=0
    )
    return map


POSE = Pose((0.0, 0.0, 100.0), (50.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 0.0, math.radians(50))


def test_names_follow_the_corpus_pattern():
    map = camera_map()
    document = MapDocument(map)
    first = new_animation(map, LOOK, POSE)
    assert first.name == "Look-at Animation" and first.num_frames == 1
    document.execute(add_animation(map, first))
    assert new_animation_name(map, LOOK) == "Look-at Animation 1"
    assert new_animation_name(map, FREE) == "Free Animation"
    copied = copy_animation(map, first)
    assert copied.name == "Look-at Animation 1" and copied.frame_data is not first.frame_data
    view = CameraView((10.0, 20.0, 5.0), 30.0, 60.0, 400.0, 50.0)
    camera = named_camera_from_view(map, new_camera_name(map), view)
    assert camera.name == "Camera 1" and camera.look_at_point == (10.0, 20.0, 0.0)
    document.execute(add_named_camera(map, camera))
    assert new_camera_name(map) == "Camera 2"
    document.execute(remove_animation(map, first))
    assert map.camera_animation_list.animations == []


def test_a_named_camera_round_trips_through_the_view():
    map = camera_map()
    view = CameraView((10.0, 20.0, 0.0), 30.0, 60.0, 400.0, 45.0)
    camera = named_camera_from_view(map, "Master", view)
    assert camera.pitch == pytest.approx(math.radians(60)) and camera.yaw == pytest.approx(
        math.radians(30)
    )
    back = named_camera_view(map, camera)
    assert (back.yaw, back.pitch, back.fov) == pytest.approx((30.0, 60.0, 45.0))
    assert back.distance == pytest.approx(400.0)


def test_keys_are_set_in_frame_order_replaced_and_deleted():
    map = camera_map()
    document = MapDocument(map)
    animation = new_animation(map, FREE, POSE)
    document.execute(add_animation(map, animation))
    animation.num_frames = 100
    moved = Pose((10.0, 0.0, 100.0), None, (0.0, 0.0, 0.0, 1.0), 0.0, 1.0)
    document.execute(set_camera_key(animation, 50, moved))
    document.execute(set_camera_key(animation, 20, moved))
    assert [key.frame_index for key in camera_keys(animation)] == [0, 20, 50]
    document.execute(set_camera_key(animation, 20, POSE))
    assert camera_keys(animation)[1].position == POSE.position
    document.stack.undo()
    assert camera_keys(animation)[1].position == moved.position
    document.execute(delete_key(camera_keys(animation), 50))
    assert [key.frame_index for key in camera_keys(animation)] == [0, 20]
    with pytest.raises(ValueError):
        delete_key(camera_keys(animation), 0)
    assert animation_length_error(animation, 20) is not None
    assert animation_length_error(animation, 21) is None
    assert animation_length_error(animation, 0) is not None


def look_animation(keys, looks):
    map = camera_map()
    animation = new_animation(map, LOOK, POSE)
    animation.num_frames = 200
    animation.frame_data.camera_frames[:] = [
        LookAtCameraAnimationCameraFrame(frame, method, position, 0.0, 1.0)
        for frame, method, position in keys
    ]
    animation.frame_data.look_at_frames[:] = [
        LookAtCameraAnimationLookAtFrame(frame, SPLINE, point) for frame, point in looks
    ]
    return animation


def test_linear_keys_mix_and_the_last_key_holds():
    animation = look_animation(
        [(0, LINEAR, (0.0, 0.0, 0.0)), (10, LINEAR, (100.0, 0.0, 0.0))], [(0, (0.0, 0.0, 0.0))]
    )
    assert evaluate(animation, 5).position == pytest.approx((50.0, 0.0, 0.0))
    assert evaluate(animation, 150).position == pytest.approx((100.0, 0.0, 0.0))
    assert evaluate(animation, 0).target == (0.0, 0.0, 0.0)


def test_spline_keys_pass_through_the_keys_as_worldbuilder_scales_them():
    points = [
        (0, (0.0, 0.0, 0.0)),
        (10, (100.0, 0.0, 0.0)),
        (40, (100.0, 100.0, 0.0)),
        (50, (0.0, 100.0, 0.0)),
    ]
    animation = look_animation([(f, SPLINE, p) for f, p in points], [(0, (0.0, 0.0, 0.0))])
    for frame, point in points:
        assert evaluate(animation, frame).position == pytest.approx(point)
    # The middle segment's neighbours are rescaled to its 30-frame gap before the curve.
    p = [np.array(point) for _frame, point in points]
    lead = p[1] + (p[0] - p[1]) * 30 / 10
    tail = p[2] + (p[3] - p[2]) * 30 / 10
    expected = _catmull_rom(lead, p[1], p[2], tail, 0.5)
    assert evaluate(animation, 25).position == pytest.approx(tuple(expected))


def test_catmull_rom_matches_the_game_formula():
    p = [np.array((v, 0.0, 0.0)) for v in (0.0, 1.0, 3.0, 4.0)]
    t = 0.3
    game = (
        (3 * p[1] - p[0] - 3 * p[2] + p[3]) * t**3
        + (4 * p[2] + 2 * p[0] - 5 * p[1] - p[3]) * t**2
        + (-p[0] + p[2]) * t
        + 2 * p[1]
    ) * 0.5
    assert _catmull_rom(*p, t) == pytest.approx(game)


def test_free_rotations_slerp_the_short_way():
    map = camera_map()
    animation = new_animation(map, FREE, POSE)
    animation.num_frames = 11
    half = math.sqrt(0.5)
    animation.frame_data.frames[:] = [
        FreeCameraAnimationCameraFrame(0, SPLINE, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), 1.0),
        # The same rotation as a quarter turn about z, stored negated.
        FreeCameraAnimationCameraFrame(10, SPLINE, (0.0, 0.0, 0.0), (0.0, 0.0, -half, -half), 1.0),
    ]
    q = evaluate(animation, 5).rotation
    assert abs(q[2]) == pytest.approx(math.sin(math.pi / 8), abs=1e-6)
    assert abs(q[3]) == pytest.approx(math.cos(math.pi / 8), abs=1e-6)


def test_interpolation_and_look_at_keys():
    map = camera_map()
    document = MapDocument(map)
    animation = new_animation(map, LOOK, POSE)
    document.execute(add_animation(map, animation))
    document.execute(set_interpolation(camera_keys(animation)[0], LINEAR))
    assert camera_keys(animation)[0].interpolation_type == LINEAR
    animation.num_frames = 30
    document.execute(set_look_at_key(animation, 10, (5.0, 6.0, 7.0)))
    assert [key.frame_index for key in look_at_keys(animation)] == [0, 10]
    assert look_at_keys(animation)[1].interpolation_type == SPLINE


def test_views_and_poses_convert_both_ways():
    view = CameraView((100.0, 200.0, 0.0), 45.0, 60.0, 500.0, 50.0)
    pose = view_pose(view)
    assert pose.position == pytest.approx(view.eye)
    forward = _rotate(pose.rotation, CAMERA_FORWARD)
    assert forward == pytest.approx(view.forward, abs=1e-9)
    back = pose_view(pose)
    assert (back.yaw, back.pitch, back.distance) == pytest.approx((45.0, 60.0, 500.0))
    free = Pose(pose.position, None, pose.rotation, 0.0, pose.fov)
    ground = pose_view(free, ground=0.0)
    assert ground.target == pytest.approx(view.target, abs=1e-6)
    level = look_rotation((1.0, 0.0, 0.0))
    assert _rotate(level, CAMERA_FORWARD) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)
