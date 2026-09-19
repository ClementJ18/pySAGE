"""Camera keys as objects in the world, without a screen: what an animation puts there, where the
handles point, what a click lands on, and what dragging one comes to."""

import math

import pytest

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_map.assets.camera_animation_list import CameraAnimationList  # noqa: E402
from sage_map.assets.named_cameras import NamedCamera, NamedCameras  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument, camera_edit  # noqa: E402
from sage_worldbuilder.camera import Camera  # noqa: E402
from sage_worldbuilder.camera_edit import (  # noqa: E402
    CAMERA_KEY,
    DRAGGING,
    LOCAL,
    LOOK_KEY,
    NAMED_CAMERA,
    PICKED,
    ROTATE,
    WORLD,
    CameraObject,
    CameraScene,
    Editor,
    ViewState,
)
from sage_worldbuilder.cameras import (  # noqa: E402
    FREE,
    LOOK,
    Pose,
    camera_keys,
    focal_length,
    fov_from_focal,
    look_at_keys,
    look_rotation,
    new_animation,
    rotation_angles,
    set_camera_key,
    set_look_at_key,
)

FOV = math.radians(50.0)


def document_with(kind):
    """A document holding one animation of a kind, keyed at frames 0 and 10."""
    map = Map()
    map.camera_animation_list = _animation_list()
    document = MapDocument(map)
    animation = new_animation(map, kind, Pose((0.0, 0.0, 100.0), (0.0, 500.0, 0.0), None, 0.0, FOV))
    if kind == FREE:
        animation.frame_data.frames[0].rotation = look_rotation((0.0, 1.0, -0.2))
    map.camera_animation_list.animations.append(animation)
    animation.num_frames = 11
    document.execute(
        set_camera_key(
            animation, 10, Pose((100.0, 100.0, 200.0), None, (0.0, 0.0, 0.0, 1.0), 0.0, FOV)
        )
    )
    if kind == LOOK:
        document.execute(set_look_at_key(animation, 10, (200.0, 800.0, 0.0)))
    return document, animation


def _animation_list():
    listed = CameraAnimationList.__new__(CameraAnimationList)
    listed.animations = []
    return listed


def viewing(scene, cameras=(), **camera_options):
    """A view state looking north from above, with the scene in front of it."""
    camera = Camera(
        target_x=0.0,
        target_y=300.0,
        target_z=0.0,
        yaw=0.0,
        pitch=45.0,
        distance=1200.0,
        width=800,
        height=600,
        **camera_options,
    )
    return ViewState(camera, camera.projector(), scene, cameras)


def scene_for(animation, selected=None, **options):
    return CameraScene(
        animation=animation, objects=camera_edit.objects(animation), selected=selected, **options
    )


def test_an_animation_puts_its_keys_in_the_world():
    _document, animation = document_with(LOOK)
    listed = camera_edit.objects(animation)
    kinds = [(obj.kind, obj.index) for obj in listed]
    assert kinds == [(CAMERA_KEY, 0), (CAMERA_KEY, 1), (LOOK_KEY, 0), (LOOK_KEY, 1)]
    camera, look = listed[0], listed[2]
    assert camera.position == (0.0, 0.0, 100.0) and camera.frame == 0
    # A look-at animation's camera faces the point its look-at track holds at that frame.
    assert camera.forward == pytest.approx((0.0, 0.980580, -0.196116), abs=1e-5)
    assert camera.is_camera and not look.is_camera
    assert look.position == (0.0, 500.0, 0.0)


def test_the_handles_point_along_the_map_or_the_camera():
    _document, animation = document_with(FREE)
    camera = camera_edit.objects(animation)[0]
    world = camera_edit.handle_axes(camera, WORLD)
    assert [name for name, _axis in world] == ["X", "Y", "Z"]
    assert [axis for _name, axis in world] == [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    local = camera_edit.handle_axes(camera, LOCAL)
    assert [name for name, _axis in local] == ["Right", "Up", "Forward"]
    # The third local axis is where the camera looks, and the axes are at right angles.
    right, up, forward = (np.asarray(axis) for _name, axis in local)
    assert forward == pytest.approx(np.asarray(camera.forward))
    assert (right @ up, right @ forward, up @ forward) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    # A look-at point has no facing of its own, and cannot be turned.
    look = camera_edit.objects(animation and animation)[0]
    point = CameraObject(LOOK_KEY, 0, (0.0, 0.0, 0.0))
    assert [name for name, _axis in camera_edit.handle_axes(point, LOCAL)] == ["X", "Y", "Z"]
    assert camera_edit.handle_axes(point, WORLD, ROTATE) == []
    assert camera_edit.handle_axes(look, WORLD, ROTATE) != []


def test_a_click_lands_on_an_object_or_a_handle():
    _document, animation = document_with(LOOK)
    scene = scene_for(animation, selected=(CAMERA_KEY, 0))
    view = viewing(scene)
    key = scene.chosen
    at = view.project(*key.position)
    assert camera_edit.object_at(view.project, at, scene.objects).key == (CAMERA_KEY, 0)
    # Far from everything, nothing is picked.
    assert camera_edit.object_at(view.project, (5.0, 5.0), scene.objects) is None
    axes = camera_edit.handle_axes(key, WORLD)
    length = view.handle_length(key.position)
    tip = view.project(*camera_edit.handle_tips(key.position, axes, length)[2])
    assert camera_edit.handle_at(view.project, tip, key.position, axes, length) == 2


def test_dragging_a_handle_slides_the_key_along_its_axis_as_one_undo_entry():
    document, animation = document_with(LOOK)
    scene = scene_for(animation, selected=(CAMERA_KEY, 0))
    view = viewing(scene)
    editor = Editor(document.execute)
    key = camera_keys(animation)[0]
    axes = camera_edit.handle_axes(scene.chosen, WORLD)
    length = view.handle_length(key.position)
    tip = view.project(*camera_edit.handle_tips(key.position, axes, length)[0])
    assert editor.press(view, tip) == DRAGGING
    editor.move(view, (tip[0] + 40, tip[1]))
    editor.move(view, (tip[0] + 80, tip[1]))
    # The key slid east, and only east.
    assert key.position[0] > 50.0
    assert (key.position[1], key.position[2]) == (0.0, 100.0)
    assert editor.release()
    # However many steps the drag took, it is one entry.
    assert document.stack.undo_label == "Move Camera Key"
    document.stack.undo()
    assert key.position == (0.0, 0.0, 100.0)
    assert document.stack.undo_label != "Move Camera Key"


def test_a_press_away_from_the_handles_chooses_an_object_or_is_left_to_the_tool():
    document, animation = document_with(LOOK)
    scene = scene_for(animation, selected=(CAMERA_KEY, 0))
    view = viewing(scene)
    editor = Editor(document.execute)
    point = view.project(*camera_edit.objects(animation)[2].position)
    assert editor.press(view, point) == PICKED
    assert editor.picked == (LOOK_KEY, 0)
    assert editor.press(view, (3.0, 3.0)) is None and editor.drag is None


def test_dragging_a_look_at_point_moves_what_the_camera_watches():
    document, animation = document_with(LOOK)
    scene = scene_for(animation, selected=(LOOK_KEY, 0))
    view = viewing(scene)
    editor = Editor(document.execute)
    key = look_at_keys(animation)[0]
    axes = camera_edit.handle_axes(scene.chosen, WORLD)
    length = view.handle_length(key.look_at_point)
    tip = view.project(*camera_edit.handle_tips(key.look_at_point, axes, length)[2])
    assert editor.press(view, tip) == DRAGGING
    editor.move(view, (tip[0], tip[1] - 30))
    editor.release()
    # Dragging the z handle up raises the point and leaves it over the same ground.
    assert key.look_at_point[2] > 10.0
    assert key.look_at_point[:2] == (0.0, 500.0)
    assert document.stack.undo_label == "Move Look-at Point"


def test_turning_a_free_key_rolls_a_look_at_one_and_moves_a_named_camera():
    document, animation = document_with(FREE)
    scene = scene_for(animation, selected=(CAMERA_KEY, 0), motion=ROTATE)
    key = camera_keys(animation)[0]
    before = rotation_angles(key.rotation)
    command = camera_edit.turn_command(
        animation, (), scene.chosen, (0.0, 0.0, 1.0), math.radians(30)
    )
    document.execute(command)
    after = rotation_angles(key.rotation)
    # Yaw is a bearing, so turning a right-handed 30 degrees about z reads as 30 the other way.
    assert math.degrees(after[0] - before[0]) == pytest.approx(-30.0, abs=1e-6)
    # A look-at animation's camera is aimed by its track, so only a turn about its facing tells.
    document, look = document_with(LOOK)
    obj = camera_edit.objects(look)[0]
    assert camera_edit.turn_command(look, (), obj, (1.0, 0.0, 0.0), 0.5) is None
    rolled = camera_edit.turn_command(look, (), obj, obj.forward, 0.5)
    document.execute(rolled)
    assert camera_keys(look)[0].roll == pytest.approx(0.5)


def test_a_named_camera_is_dragged_by_the_point_it_looks_at():
    map = Map()
    map.named_cameras = NamedCameras.__new__(NamedCameras)
    camera = NamedCamera(
        look_at_point=(100.0, 200.0, 0.0),
        name="Camera 1",
        pitch=1.0,
        roll=0.0,
        yaw=0.0,
        zoom=0.5,
        fov=FOV,
        unknown=100.0,
    )
    map.named_cameras.cameras = [camera]
    document = MapDocument(map)
    obj = camera_edit.named_object(camera, 0)
    assert obj.key == (NAMED_CAMERA, 0) and obj.position == (100.0, 200.0, 0.0)
    command = camera_edit.move_command(None, [camera], obj, (150.0, 200.0, 0.0))
    document.execute(command)
    assert camera.look_at_point == (150.0, 200.0, 0.0)
    assert document.stack.undo_label == "Move Named Camera"


def test_the_hover_follows_the_handles():
    document, animation = document_with(LOOK)
    scene = scene_for(animation, selected=(CAMERA_KEY, 0))
    view = viewing(scene)
    editor = Editor(document.execute)
    key = camera_keys(animation)[0]
    axes = camera_edit.handle_axes(scene.chosen, WORLD)
    length = view.handle_length(key.position)
    tip = view.project(*camera_edit.handle_tips(key.position, axes, length)[1])
    assert editor.hover_at(view, tip) and editor.hover == (CAMERA_KEY, 0, 1)
    assert not editor.hover_at(view, tip)
    assert editor.hover_at(view, (2.0, 2.0)) and editor.hover is None


def test_a_camera_is_drawn_as_a_wireframe_facing_where_it_looks():
    _document, animation = document_with(LOOK)
    camera = camera_edit.objects(animation)[0]
    segments = camera_edit.glyph_segments(camera, 40.0)
    assert len(segments) > 12
    points = np.asarray([point for segment in segments for point in segment])
    # The wireframe stands about the key, and reaches further ahead of it than behind.
    assert points.mean(axis=0) == pytest.approx(np.asarray(camera.position), abs=40.0)
    ahead = (points - np.asarray(camera.position)) @ np.asarray(camera.forward)
    assert ahead.max() > 0 and ahead.min() < 0
    frustum = camera_edit.frustum_segments(
        camera.position, camera.forward, camera.up, FOV, 1000.0, 4 / 3
    )
    corners = np.asarray([end for _start, end in frustum])
    assert np.linalg.norm(corners - np.asarray(camera.position), axis=1).max() == pytest.approx(
        1000.0 * math.sqrt(1 + math.tan(FOV / 2) ** 2 * (1 + (4 / 3) ** 2)), rel=1e-6
    )


def test_the_focal_length_and_the_field_of_view_are_the_same_number():
    # WorldBuilder opens a new animation at 25.734mm, which is a 50-degree field of view.
    assert focal_length(math.radians(50.0)) == pytest.approx(25.734, abs=5e-4)
    assert math.degrees(fov_from_focal(25.734)) == pytest.approx(50.0, abs=1e-3)
    assert math.degrees(fov_from_focal(focal_length(math.radians(35.0)))) == pytest.approx(35.0)


def test_an_axis_along_the_view_cannot_be_dragged():
    scene = CameraScene()
    view = viewing(scene)
    origin, direction = view.camera.ray(400, 300)
    along = camera_edit.axis_parameter((0.0, 300.0, 0.0), tuple(direction), origin, direction)
    assert along is None
