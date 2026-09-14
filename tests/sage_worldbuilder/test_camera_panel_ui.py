"""Qt-level tests for the Cameras panel: named cameras saved from the view, edited, shown and
deleted; camera animations added, keyed, scrubbed, played and their paths drawn; the keys as
objects in the world, chosen and edited by their own fields. Headless via the Qt 'offscreen'
platform (the top-down view stands in for the 3D view); marked `full`."""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.camera import Camera  # noqa: E402
from sage_worldbuilder.camera_edit import (  # noqa: E402
    CAMERA_KEY,
    DRAGGING,
    LOCAL,
    LOOK_KEY,
    NAMED_CAMERA,
    ROTATE,
    WORLD,
    Editor,
    ViewState,
    handle_axes,
    handle_tips,
)
from sage_worldbuilder.cameras import (  # noqa: E402
    FREE,
    LINEAR,
    LOOK,
    CameraView,
    camera_keys,
    focal_length,
    look_at_keys,
)
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402
from sage_worldbuilder.viewport import ViewOptions  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    # The top-down view, which these read the shown camera off.
    settings = Settings(install=str(install), view=ViewOptions(view_3d=False))
    window = MainWindow(settings, load_game_data=False)
    window._set_document(MapDocument(new_map(NewMapOptions(width=64, height=64, border=4))))
    window.current_view = lambda: CameraView((100.0, 200.0, 0.0), 30.0, 60.0, 500.0, 50.0)
    yield window
    window.document = None
    window.close()


def test_the_menu_commands_open_the_tabs(window):
    window.camera_animations_action.trigger()
    assert window.camera_dock.isVisibleTo(window) and window.camera_panel.tabs.currentIndex() == 1
    window.camera_options_action.trigger()
    assert window.camera_panel.tabs.currentIndex() == 0


def test_named_cameras_are_saved_edited_shown_and_deleted(window):
    panel = window.camera_panel
    cameras = window.document.map.named_cameras.cameras
    panel.new_camera()
    (camera,) = cameras
    assert camera.name == "Camera 1" and camera.look_at_point == (100.0, 200.0, 0.0)
    assert panel.camera_list.currentRow() == 0
    panel.camera_boxes["pitch"].setValue(45.0)
    panel.camera_boxes["pitch"].editingFinished.emit()
    assert camera.pitch == pytest.approx(math.radians(45.0))
    shown = []
    panel.view_requested.connect(shown.append)
    panel.goto_camera()
    assert shown[-1].target == (100.0, 200.0, 0.0) and shown[-1].pitch == pytest.approx(45.0)
    # Go To shows the camera in the 3D view; the top-down view centres on what it looks at.
    window.show_3d_view(False)
    window.show_camera_view(shown[-1])
    assert (window.map_view.transform.center_x, window.map_view.transform.center_y) == (
        100.0,
        200.0,
    )
    window.current_view = lambda: CameraView((300.0, 50.0, 0.0), 0.0, 70.0, 400.0, 50.0)
    panel.update_camera()
    assert camera.look_at_point == (300.0, 50.0, 0.0)
    window.document.stack.undo()
    assert camera.look_at_point == (100.0, 200.0, 0.0)
    panel.delete_camera()
    assert cameras == []


def test_an_animation_is_added_keyed_scrubbed_and_played(window):
    panel = window.camera_panel
    panel.tabs.setCurrentIndex(1)
    animations = window.document.map.camera_animation_list.animations
    panel.add_animation(LOOK)
    (animation,) = animations
    assert animation.name == "Look-at Animation" and panel.selected_animation() is animation
    panel.animation_length.setValue(31)
    panel.animation_length.editingFinished.emit()
    assert animation.num_frames == 31 and panel.frame_slider.maximum() == 30
    window.current_view = lambda: CameraView((500.0, 200.0, 0.0), 30.0, 60.0, 500.0, 50.0)
    panel.frame_slider.setValue(30)
    panel.set_camera_key()
    panel.set_look_key()
    assert [key.frame_index for key in camera_keys(animation)] == [0, 30]
    assert look_at_keys(animation)[1].look_at_point == (500.0, 200.0, 0.0)
    panel.key_list.setCurrentRow(0)
    panel.interpolation_box.setCurrentIndex(1)
    assert camera_keys(animation)[0].interpolation_type == LINEAR
    scenes = []
    panel.scene_changed.connect(scenes.append)
    panel.frame_slider.setValue(15)
    # The frame goes to the camera preview, not to the view being worked in.
    assert scenes[-1].preview.target == pytest.approx((300.0, 200.0, 0.0))
    panel.animation_length.setValue(10)
    panel.animation_length.editingFinished.emit()
    assert animation.num_frames == 31
    panel.frame_slider.setValue(29)
    panel.play_button.setChecked(True)
    panel._tick()
    panel._tick()
    assert panel.frame == 30 and not panel.play_button.isChecked()


def test_show_path_draws_the_animation_on_the_map(window):
    panel = window.camera_panel
    panel.add_animation(LOOK)
    animation = window.document.map.camera_animation_list.animations[0]
    panel.animation_length.setValue(11)
    panel.animation_length.editingFinished.emit()
    window.current_view = lambda: CameraView((600.0, 200.0, 0.0), 30.0, 60.0, 500.0, 50.0)
    panel.frame_slider.setValue(10)
    panel.set_camera_key()
    panel.path_box.setChecked(True)
    points, keys = window.map_view.camera_path
    assert len(points) == 11 and len(keys) == 2
    window.map_view.resize(300, 300)
    window.map_view.grab()
    panel.path_box.setChecked(False)
    assert window.map_view.camera_path is None
    assert animation.num_frames == 11


def keyed(window, kind=LOOK, frames=11):
    """An animation of a kind with keys at frames 0 and `frames - 1`, and the panel on it."""
    window.camera_animations_action.trigger()
    panel = window.camera_panel
    panel.add_animation(kind)
    animation = window.document.map.camera_animation_list.animations[0]
    panel.animation_length.setValue(frames)
    panel.animation_length.editingFinished.emit()
    window.current_view = lambda: CameraView((600.0, 200.0, 100.0), 30.0, 60.0, 500.0, 50.0)
    panel.frame_slider.setValue(frames - 1)
    panel.set_camera_key()
    if kind == LOOK:
        panel.set_look_key()
    panel.frame_slider.setValue(0)
    return panel, animation


def test_the_keys_stand_in_the_world_as_objects(window):
    panel, animation = keyed(window)
    scenes = []
    panel.scene_changed.connect(scenes.append)
    panel.key_list.setCurrentRow(1)
    scene = scenes[-1]
    assert [obj.key for obj in scene.objects] == [
        (CAMERA_KEY, 0),
        (CAMERA_KEY, 1),
        (LOOK_KEY, 0),
        (LOOK_KEY, 1),
    ]
    # A key stands where the camera stands, which is behind what the view looks at.
    assert scene.selected == (CAMERA_KEY, 1)
    assert scene.chosen.position == camera_keys(animation)[1].position
    assert scene.animation is animation
    # Both paths are drawn in three dimensions, and the preview looks from the frame shown.
    assert len(scene.camera_path) == 11 and len(scene.look_at_path) == 11
    assert len(scene.camera_path[0]) == 3
    assert scene.preview.position == pytest.approx(camera_keys(animation)[0].position)
    panel.look_path_box.setChecked(False)
    assert scenes[-1].look_at_path is None
    panel.preview_box.setChecked(False)
    assert scenes[-1].preview is None


def test_clicking_an_object_in_the_view_chooses_its_key(window):
    panel, animation = keyed(window)
    panel.select_object((LOOK_KEY, 1))
    # The list holds the camera keys then the look-at keys, in the order the view draws them.
    assert panel.key_list.currentRow() == 3
    panel.select_object((CAMERA_KEY, 0))
    assert panel.key_list.currentRow() == 0
    assert panel.key_list.count() == len(camera_keys(animation)) + len(look_at_keys(animation))


def test_the_chosen_key_is_edited_by_its_own_fields(window):
    panel, animation = keyed(window, FREE)
    panel.key_list.setCurrentRow(0)
    key = camera_keys(animation)[0]
    assert panel.position_boxes["x"].value() == pytest.approx(key.position[0])
    panel.position_boxes["z"].setValue(250.0)
    panel.position_boxes["z"].editingFinished.emit()
    assert key.position == pytest.approx((key.position[0], key.position[1], 250.0))
    panel.angle_boxes["yaw"].setValue(90.0)
    panel.angle_boxes["yaw"].editingFinished.emit()
    assert panel.angle_boxes["yaw"].value() == pytest.approx(90.0, abs=1e-3)
    # The focal length and the field of view are the same number two ways.
    panel.focal_box.setValue(50.0)
    panel.focal_box.editingFinished.emit()
    assert focal_length(key.fov) == pytest.approx(50.0)
    assert "field of view" in panel.fov_label.text()
    window.document.stack.undo()
    assert focal_length(key.fov) == pytest.approx(25.734, abs=5e-4)


def test_a_look_at_key_has_a_point_but_no_facing(window):
    panel, animation = keyed(window)
    panel.key_list.setCurrentRow(2)
    assert not panel.angle_boxes["yaw"].isEnabled() and not panel.focal_box.isEnabled()
    assert panel.position_boxes["x"].isEnabled()
    panel.position_boxes["y"].setValue(750.0)
    panel.position_boxes["y"].editingFinished.emit()
    assert look_at_keys(animation)[0].look_at_point[1] == pytest.approx(750.0)
    # A look-at animation's camera key stores only a roll, so only that angle can be set.
    panel.key_list.setCurrentRow(0)
    assert panel.angle_boxes["roll"].isEnabled() and not panel.angle_boxes["pitch"].isEnabled()


def test_the_handle_options_reach_the_view(window):
    panel, _animation = keyed(window)
    scenes = []
    panel.scene_changed.connect(scenes.append)
    local = next(b for b in panel.system_buttons.buttons() if b.property("value") == LOCAL)
    local.setChecked(True)
    assert scenes[-1].system == LOCAL
    rotate = next(b for b in panel.motion_buttons.buttons() if b.property("value") == ROTATE)
    rotate.setChecked(True)
    assert scenes[-1].motion == ROTATE
    assert window.map_view.camera_scene.motion == ROTATE


def test_the_named_cameras_stand_in_the_world_too(window):
    window.camera_options_action.trigger()
    panel = window.camera_panel
    panel.new_camera()
    scene = window.map_view.camera_scene
    assert [obj.key for obj in scene.objects] == [(NAMED_CAMERA, 0)]
    assert scene.selected == (NAMED_CAMERA, 0)
    assert scene.preview is not None and scene.animation is None


def test_the_objects_go_away_with_the_panel(window):
    panel, _animation = keyed(window)
    assert window.map_view.camera_scene is not None
    window.camera_dock.hide()
    assert window.map_view.camera_scene is None
    window.camera_animations_action.trigger()
    assert window.map_view.camera_scene is not None


def test_a_drag_keeps_hold_of_the_key_it_is_dragging(window):
    """Every step of a drag is an edit, and an edit rebuilds the panel's lists. The key being
    dragged has to stay chosen through that, or the handles go away under the cursor."""
    panel, animation = keyed(window)
    panel.key_list.setCurrentRow(0)
    scene = window.map_view.camera_scene
    camera = Camera(
        target_x=0.0,
        target_y=0.0,
        target_z=300.0,
        yaw=0.0,
        pitch=40.0,
        distance=1500.0,
        width=800,
        height=600,
    )
    view = ViewState(camera, camera.projector(), scene, ())
    editor = Editor(window.execute)
    key = camera_keys(animation)[0]
    axes = handle_axes(scene.chosen, WORLD)
    tip = view.project(*handle_tips(key.position, axes, view.handle_length(key.position))[0])
    assert editor.press(view, tip) == DRAGGING
    editor.move(view, (tip[0] + 40, tip[1]))
    assert panel.key_list.currentRow() == 0
    assert window.map_view.camera_scene.selected == (CAMERA_KEY, 0)
    editor.move(view, (tip[0] + 80, tip[1]))
    editor.release()
    assert window.map_view.camera_scene.selected == (CAMERA_KEY, 0)
    assert window.document.stack.undo_label == "Move Camera Key"
    assert key.position[0] > 0.0
