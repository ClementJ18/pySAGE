"""The Cameras panel: WorldBuilder's Camera Options (225) named camera locations and its Camera
Animations dialog (280) with its timeline (287).

Named Cameras lists the map's named cameras: New saves the view shown as a new one, Update
replaces the chosen one's with the view, Go To shows it, and its fields are edited in place (angles
in degrees, as the dialog's sliders show them).

Camera Animations lists the map's animations: add a free or a look-at animation, copy or remove
one, and edit its name, length and start offset. The frame slider shows the animation at a frame in
the camera preview, a pane in the corner of the 3D view, so the view being worked in never moves.
Play runs it (at 30 frames a second with Real time, else as fast as the view redraws), and Loop
starts it again at the end. Set Camera Key keys the camera at the frame from the view, Set Look-at
Key keys what a look-at animation looks at from the view's target, and a key's interpolation is
Smooth (spline) or Linear.

Every key is also an object in the 3D view: a camera, or a marker for a look-at point. Choosing one
(in the list, or by clicking it) puts drag handles on it, along the map's axes or the camera's own
and either moving it or turning it, and its position, facing and focal length are the fields below
the list. Show Camera Path and Show Look-at Path draw the tracks the animation follows.
"""

from __future__ import annotations

import math
from typing import Protocol

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sage_map.assets.camera_animation_list import CameraAnimation
from sage_map.assets.named_cameras import NamedCamera
from sage_worldbuilder import camera_edit
from sage_worldbuilder.camera_edit import (
    CAMERA_KEY,
    LOCAL,
    LOOK_KEY,
    NAMED_CAMERA,
    ROTATE,
    TRANSLATE,
    WORLD,
    CameraScene,
    Vec3,
)
from sage_worldbuilder.cameras import (
    CAMERAS,
    FREE,
    LINEAR,
    LOOK,
    SPLINE,
    CameraView,
    add_animation,
    add_named_camera,
    animation_length_error,
    camera_keys,
    copy_animation,
    delete_key,
    evaluate,
    focal_length,
    fov_from_focal,
    look_at_keys,
    named_camera_from_view,
    named_camera_view,
    new_animation,
    new_camera_name,
    pose_axes,
    remove_animation,
    remove_named_camera,
    rotation_angles,
    rotation_for,
    set_camera_key,
    set_interpolation,
    set_look_at_key,
    view_pose,
)
from sage_worldbuilder.commands import Command, CompositeCommand, SetAttribute
from sage_worldbuilder.document import MapDocument

__all__ = ["CameraHost", "CameraPanel"]

REAL_TIME_FPS = 30
_PATH_SAMPLES = 400
# How far the camera preview sees by default, in world units. WorldBuilder opens its dialog at
# 2,000; half that keeps the cone the view draws from swallowing the map.
DEFAULT_FAR_CLIP = 1000.0


class CameraHost(Protocol):
    @property
    def document(self) -> MapDocument | None: ...

    def execute(self, command: Command) -> None: ...

    def current_view(self) -> CameraView:
        """The camera of the map view shown."""
        ...

    def show_status(self, text: str) -> None: ...


def _degrees(low: float, high: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(1)
    box.setSuffix("°")
    return box


class CameraPanel(QWidget):
    # A CameraView to show: Go To on a named camera.
    view_requested = pyqtSignal(object)
    # The chosen animation's path to draw (world points and key points), or None.
    path_changed = pyqtSignal(object)
    # What the 3D view draws and can drag: a `CameraScene`, or None.
    scene_changed = pyqtSignal(object)

    def __init__(self, host: CameraHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._updating = False
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._named_page(), "Named Cameras")
        self.tabs.addTab(self._animation_page(), "Camera Animations")
        self.tabs.currentChanged.connect(lambda _index: self._send_scene())
        # The paths through the chosen animation, kept while it is unchanged: rebuilding them
        # every frame of playback would cost more than drawing them.
        self._paths: tuple[list[Vec3], list[Vec3]] | None = None
        # The camera object chosen, kept across a refresh: an edit rebuilds the lists below, and
        # the drag that made it must not let go of what it is dragging.
        self._chosen: tuple[str, int] | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.refresh()

    # Named cameras.

    def _named_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        self.camera_list = QListWidget()
        self.camera_list.currentRowChanged.connect(lambda _row: self._show_camera())
        column.addWidget(self.camera_list, 1)
        buttons = QHBoxLayout()
        for text, slot in (
            ("New", self.new_camera),
            ("Update", self.update_camera),
            ("Go To", self.goto_camera),
            ("Delete", self.delete_camera),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        column.addLayout(buttons)
        form = QFormLayout()
        self.camera_name = QLineEdit()
        self.camera_name.editingFinished.connect(
            lambda: self._set_camera("name", self.camera_name.text().strip())
        )
        form.addRow("Name", self.camera_name)
        self.camera_boxes: dict[str, QDoubleSpinBox] = {}
        for field, label, box in (
            ("pitch", "Pitch", _degrees(-180.0, 180.0)),
            ("yaw", "Yaw", _degrees(-720.0, 720.0)),
            ("roll", "Roll", _degrees(-180.0, 180.0)),
            ("fov", "Field of view", _degrees(1.0, 179.0)),
        ):
            box.editingFinished.connect(
                lambda field=field, box=box: self._set_camera(field, math.radians(box.value()))
            )
            form.addRow(label, box)
            self.camera_boxes[field] = box
        self.camera_zoom = QDoubleSpinBox()
        self.camera_zoom.setRange(0.0, 1000.0)
        self.camera_zoom.setDecimals(3)
        self.camera_zoom.editingFinished.connect(
            lambda: self._set_camera("zoom", self.camera_zoom.value())
        )
        form.addRow("Zoom", self.camera_zoom)
        self.camera_look = QLabel()
        form.addRow("Look-at point", self.camera_look)
        column.addLayout(form)
        return page

    def _cameras(self) -> list[NamedCamera]:
        document = self.host.document
        chunk = document.map.named_cameras if document is not None else None
        return chunk.cameras if chunk is not None else []

    def selected_camera(self) -> NamedCamera | None:
        cameras, row = self._cameras(), self.camera_list.currentRow()
        return cameras[row] if 0 <= row < len(cameras) else None

    def new_camera(self) -> None:
        document = self.host.document
        if document is None or document.map.named_cameras is None:
            return
        camera = named_camera_from_view(
            document.map, new_camera_name(document.map), self.host.current_view()
        )
        self.host.execute(add_named_camera(document.map, camera))
        self.camera_list.setCurrentRow(len(self._cameras()) - 1)

    def update_camera(self) -> None:
        document, camera = self.host.document, self.selected_camera()
        if document is None or camera is None:
            return
        fresh = named_camera_from_view(document.map, camera.name, self.host.current_view())
        commands: list[Command] = [
            SetAttribute(camera, field, getattr(fresh, field), CAMERAS, "Update Named Camera")
            for field in ("look_at_point", "pitch", "roll", "yaw", "zoom", "fov")
            if getattr(camera, field) != getattr(fresh, field)
        ]
        if commands:
            self.host.execute(CompositeCommand("Update Named Camera", commands))

    def goto_camera(self) -> None:
        document, camera = self.host.document, self.selected_camera()
        if document is not None and camera is not None:
            self.view_requested.emit(named_camera_view(document.map, camera))

    def delete_camera(self) -> None:
        document, camera = self.host.document, self.selected_camera()
        if document is not None and camera is not None:
            self.host.execute(remove_named_camera(document.map, camera))

    def _set_camera(self, field: str, value: object) -> None:
        camera = self.selected_camera()
        if self._updating or camera is None or getattr(camera, field) == value:
            return
        if field == "name" and not value:
            return
        self.host.execute(SetAttribute(camera, field, value, CAMERAS, "Edit Named Camera"))

    def _show_camera(self) -> None:
        camera = self.selected_camera()
        self._updating = True
        try:
            for widget in (self.camera_name, self.camera_zoom, *self.camera_boxes.values()):
                widget.setEnabled(camera is not None)
            if camera is None:
                self.camera_look.setText("")
                return
            self._show_camera_fields(camera)
        finally:
            self._updating = False
        if self.tabs.currentIndex() == 0:
            self._send_scene()

    def _show_camera_fields(self, camera: NamedCamera) -> None:
        self.camera_name.setText(camera.name)
        for field, box in self.camera_boxes.items():
            box.setValue(math.degrees(getattr(camera, field)))
        self.camera_zoom.setValue(camera.zoom)
        x, y, z = camera.look_at_point
        self.camera_look.setText(f"{x:.0f}, {y:.0f}, {z:.0f}")

    # Camera animations.

    def _animation_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        chooser = QHBoxLayout()
        self.animation_box = QComboBox()
        self.animation_box.currentIndexChanged.connect(lambda _index: self._show_animation())
        chooser.addWidget(self.animation_box, 1)
        column.addLayout(chooser)
        buttons = QHBoxLayout()
        for text, slot in (
            ("Add Free", lambda: self.add_animation(FREE)),
            ("Add Look-at", lambda: self.add_animation(LOOK)),
            ("Copy", self.copy_animation),
            ("Remove", self.remove_animation),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        column.addLayout(buttons)
        form = QFormLayout()
        self.animation_name = QLineEdit()
        self.animation_name.editingFinished.connect(
            lambda: self._set_animation("name", self.animation_name.text().strip())
        )
        form.addRow("Name", self.animation_name)
        self.animation_length = QSpinBox()
        self.animation_length.setRange(1, 100000)
        self.animation_length.setSuffix(" frames")
        self.animation_length.editingFinished.connect(self._set_length)
        form.addRow("Length", self.animation_length)
        self.animation_start = QSpinBox()
        self.animation_start.setRange(0, 100000)
        self.animation_start.setSuffix(" frames")
        self.animation_start.editingFinished.connect(
            lambda: self._set_animation("start_offset", self.animation_start.value())
        )
        form.addRow("Start offset", self.animation_start)
        column.addLayout(form)

        timeline = QGridLayout()
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.valueChanged.connect(self._frame_moved)
        timeline.addWidget(self.frame_slider, 0, 0, 1, 3)
        self.frame_box = QSpinBox()
        self.frame_box.valueChanged.connect(self.frame_slider.setValue)
        timeline.addWidget(self.frame_box, 0, 3)
        self.play_button = QPushButton("Play")
        self.play_button.setCheckable(True)
        self.play_button.toggled.connect(self._play_toggled)
        timeline.addWidget(self.play_button, 1, 0)
        self.loop_box = QCheckBox("Loop")
        timeline.addWidget(self.loop_box, 1, 1)
        self.real_time_box = QCheckBox("Real time")
        self.real_time_box.setChecked(True)
        timeline.addWidget(self.real_time_box, 1, 2)
        self.path_box = QCheckBox("Camera path")
        self.path_box.setChecked(True)
        self.path_box.toggled.connect(lambda _on: (self._send_path(), self._send_scene()))
        timeline.addWidget(self.path_box, 1, 3)
        column.addLayout(timeline)

        self.key_list = QListWidget()
        self.key_list.currentRowChanged.connect(lambda _row: self._show_key())
        column.addWidget(self.key_list, 1)
        keys = QHBoxLayout()
        self.camera_key_button = QPushButton("Set Camera Key")
        self.camera_key_button.clicked.connect(self.set_camera_key)
        keys.addWidget(self.camera_key_button)
        self.look_key_button = QPushButton("Set Look-at Key")
        self.look_key_button.clicked.connect(self.set_look_key)
        keys.addWidget(self.look_key_button)
        self.delete_key_button = QPushButton("Delete Key")
        self.delete_key_button.clicked.connect(self.delete_key)
        keys.addWidget(self.delete_key_button)
        column.addLayout(keys)
        interpolation = QFormLayout()
        self.interpolation_box = QComboBox()
        self.interpolation_box.addItem("Smooth", SPLINE)
        self.interpolation_box.addItem("Linear", LINEAR)
        self.interpolation_box.currentIndexChanged.connect(self._set_interpolation)
        interpolation.addRow("Interpolation", self.interpolation_box)
        column.addLayout(interpolation)
        column.addWidget(self._key_group())
        column.addWidget(self._preview_group())
        column.addWidget(self._handle_group())
        return page

    def _key_group(self) -> QWidget:
        """The chosen key's own numbers: where it stands, where it faces and its lens."""
        group = QGroupBox("Chosen key")
        grid = QGridLayout(group)
        self.position_boxes: dict[str, QDoubleSpinBox] = {}
        for column, axis in enumerate("xyz"):
            box = QDoubleSpinBox()
            box.setRange(-1.0e6, 1.0e6)
            box.setDecimals(2)
            box.editingFinished.connect(self._set_position)
            grid.addWidget(QLabel(axis.upper()), 0, column * 2)
            grid.addWidget(box, 0, column * 2 + 1)
            self.position_boxes[axis] = box
        self.angle_boxes: dict[str, QDoubleSpinBox] = {}
        for column, (field, label) in enumerate(
            (("yaw", "Yaw"), ("pitch", "Pitch"), ("roll", "Roll"))
        ):
            box = _degrees(-360.0, 360.0)
            box.editingFinished.connect(self._set_angles)
            grid.addWidget(QLabel(label), 1, column * 2)
            grid.addWidget(box, 1, column * 2 + 1)
            self.angle_boxes[field] = box
        self.focal_box = QDoubleSpinBox()
        self.focal_box.setRange(1.0, 500.0)
        self.focal_box.setDecimals(2)
        self.focal_box.setSuffix(" mm")
        self.focal_box.editingFinished.connect(self._set_focal)
        grid.addWidget(QLabel("Focal length"), 2, 0)
        grid.addWidget(self.focal_box, 2, 1)
        self.fov_label = QLabel()
        grid.addWidget(self.fov_label, 2, 2, 1, 2)
        return group

    def _preview_group(self) -> QWidget:
        """What the views draw for the animation: its paths, and the camera preview."""
        group = QGroupBox("Show")
        grid = QGridLayout(group)
        self.look_path_box = QCheckBox("Look-at path")
        self.look_path_box.setChecked(True)
        self.look_path_box.toggled.connect(lambda _on: self._send_scene())
        grid.addWidget(self.look_path_box, 0, 0)
        self.preview_box = QCheckBox("Camera preview")
        self.preview_box.setChecked(True)
        self.preview_box.setToolTip(
            "Show what the camera sees in a pane in the corner of the 3D view, "
            "instead of moving the view itself."
        )
        self.preview_box.toggled.connect(lambda _on: self._send_scene())
        grid.addWidget(self.preview_box, 0, 1)
        self.far_clip_box = QDoubleSpinBox()
        self.far_clip_box.setRange(50.0, 100000.0)
        self.far_clip_box.setDecimals(0)
        self.far_clip_box.setSingleStep(100.0)
        self.far_clip_box.setValue(DEFAULT_FAR_CLIP)
        self.far_clip_box.valueChanged.connect(lambda _value: self._send_scene())
        grid.addWidget(QLabel("Preview far clip"), 1, 0)
        grid.addWidget(self.far_clip_box, 1, 1)
        return group

    def _handle_group(self) -> QWidget:
        """WorldBuilder's Camera Animation Options: which axes the drag handles point along, and
        whether dragging one moves the key or turns it."""
        group = QGroupBox("Drag handles")
        grid = QGridLayout(group)
        self.system_buttons = QButtonGroup(self)
        self.motion_buttons = QButtonGroup(self)
        rows = (
            ("Coordinate system", self.system_buttons, (("World", WORLD), ("Local", LOCAL))),
            (
                "Camera motion",
                self.motion_buttons,
                (("Translation", TRANSLATE), ("Rotation", ROTATE)),
            ),
        )
        for row, (label, buttons, choices) in enumerate(rows):
            grid.addWidget(QLabel(label), row, 0)
            for column, (text, value) in enumerate(choices):
                button = QRadioButton(text)
                button.setProperty("value", value)
                button.setChecked(column == 0)
                buttons.addButton(button)
                grid.addWidget(button, row, column + 1)
            buttons.buttonToggled.connect(lambda _button, on: self._send_scene() if on else None)
        return group

    def _animations(self) -> list[CameraAnimation]:
        document = self.host.document
        chunk = document.map.camera_animation_list if document is not None else None
        return chunk.animations if chunk is not None else []

    def selected_animation(self) -> CameraAnimation | None:
        animations, index = self._animations(), self.animation_box.currentIndex()
        return animations[index] if 0 <= index < len(animations) else None

    def add_animation(self, kind: str) -> None:
        document = self.host.document
        if document is None or document.map.camera_animation_list is None:
            return
        animation = new_animation(document.map, kind, view_pose(self.host.current_view()))
        self.host.execute(add_animation(document.map, animation))
        self.animation_box.setCurrentIndex(len(self._animations()) - 1)

    def copy_animation(self) -> None:
        document, animation = self.host.document, self.selected_animation()
        if document is None or animation is None:
            return
        copied = copy_animation(document.map, animation)
        self.host.execute(add_animation(document.map, copied, "Copy Camera Animation"))
        self.animation_box.setCurrentIndex(len(self._animations()) - 1)

    def remove_animation(self) -> None:
        document, animation = self.host.document, self.selected_animation()
        if document is not None and animation is not None:
            self.timer.stop()
            self.host.execute(remove_animation(document.map, animation))

    def _set_animation(self, field: str, value: object) -> None:
        animation = self.selected_animation()
        if self._updating or animation is None or getattr(animation, field) == value:
            return
        if field == "name" and not value:
            return
        self.host.execute(SetAttribute(animation, field, value, CAMERAS, "Edit Camera Animation"))

    def _set_length(self) -> None:
        animation = self.selected_animation()
        if self._updating or animation is None:
            return
        frames = self.animation_length.value()
        problem = animation_length_error(animation, frames)
        if problem is not None:
            self.host.show_status(problem)
            self._show_animation()
            return
        self._set_animation("num_frames", frames)

    @property
    def frame(self) -> int:
        return self.frame_slider.value()

    def _frame_moved(self, frame: int) -> None:
        self.frame_box.blockSignals(True)
        self.frame_box.setValue(frame)
        self.frame_box.blockSignals(False)
        if not self._updating:
            self.show_frame()

    def show_frame(self) -> None:
        """Show the chosen animation at the slider's frame in the camera preview."""
        self._send_scene()

    def _play_toggled(self, on: bool) -> None:
        self.play_button.setText("Stop" if on else "Play")
        if on:
            interval = round(1000 / REAL_TIME_FPS) if self.real_time_box.isChecked() else 0
            self.timer.start(interval)
        else:
            self.timer.stop()

    def _tick(self) -> None:
        if self.frame < self.frame_slider.maximum():
            self.frame_slider.setValue(self.frame + 1)
        elif self.loop_box.isChecked():
            self.frame_slider.setValue(0)
        else:
            self.play_button.setChecked(False)

    def set_camera_key(self) -> None:
        animation = self.selected_animation()
        if animation is not None:
            self.host.execute(
                set_camera_key(animation, self.frame, view_pose(self.host.current_view()))
            )

    def set_look_key(self) -> None:
        animation = self.selected_animation()
        if animation is not None and animation.animation_type == LOOK:
            self.host.execute(
                set_look_at_key(animation, self.frame, self.host.current_view().target)
            )

    def _object_key(self, row: int) -> tuple[str, int] | None:
        """The camera object a row of the key list stands for. The list holds the camera keys
        then the look-at keys, in the order the view draws them."""
        animation = self.selected_animation()
        if animation is None or row < 0:
            return None
        cameras = len(camera_keys(animation))
        if row < cameras:
            return (CAMERA_KEY, row)
        row -= cameras
        return (LOOK_KEY, row) if row < len(look_at_keys(animation)) else None

    def _object_row(self, key: tuple[str, int] | None) -> int:
        """Which row of the key list a camera object is, or -1 for one that is not listed."""
        animation = self.selected_animation()
        if animation is None or key is None or key[0] == NAMED_CAMERA:
            return -1
        kind, index = key
        row = index if kind == CAMERA_KEY else len(camera_keys(animation)) + index
        return row if 0 <= row < self.key_list.count() else -1

    def select_object(self, key: tuple[str, int] | None) -> None:
        """Choose the key a camera object in the view stands for, as clicking it does."""
        if key is not None and key[0] == NAMED_CAMERA:
            self.camera_list.setCurrentRow(key[1])
            return
        row = self._object_row(key)
        if row >= 0 and row != self.key_list.currentRow():
            self.key_list.setCurrentRow(row)

    def _selected_key(self) -> tuple[str, int, object] | None:
        """The chosen key as `(kind, index, key)`, or None with no row chosen."""
        key = self._object_key(self.key_list.currentRow())
        animation = self.selected_animation()
        if key is None or animation is None:
            return None
        kind, index = key
        track = camera_keys(animation) if kind == CAMERA_KEY else look_at_keys(animation)
        return (kind, index, track[index]) if 0 <= index < len(track) else None

    def _set_position(self) -> None:
        """Put the chosen key where its X, Y and Z say."""
        chosen, animation = self._selected_key(), self.selected_animation()
        if self._updating or chosen is None:
            return
        kind, index, key = chosen
        place: Vec3 = tuple(self.position_boxes[axis].value() for axis in "xyz")  # type: ignore[assignment]
        name = "position" if kind == CAMERA_KEY else "look_at_point"
        if tuple(getattr(key, name)) == place:
            return
        command = camera_edit.move_command(
            animation, (), camera_edit.CameraObject(kind, index, place), place
        )
        if command is not None:
            self.host.execute(command)

    def _set_angles(self) -> None:
        """Turn the chosen camera key to its yaw, pitch and roll. A free key stores the whole
        rotation; a look-at key is aimed by its look-at track and stores only the roll."""
        chosen, animation = self._selected_key(), self.selected_animation()
        if self._updating or chosen is None or animation is None or chosen[0] != CAMERA_KEY:
            return
        key = chosen[2]
        angles = {name: math.radians(box.value()) for name, box in self.angle_boxes.items()}
        if animation.animation_type == FREE:
            rotation = rotation_for(angles["yaw"], angles["pitch"], angles["roll"])
            if key.rotation != rotation:
                self.host.execute(
                    camera_edit.SetCameraValue(key, "rotation", rotation, "Turn Camera Key")
                )
            return
        if key.roll != angles["roll"]:
            self.host.execute(
                camera_edit.SetCameraValue(key, "roll", angles["roll"], "Roll Camera Key")
            )

    def _set_focal(self) -> None:
        """Set the chosen camera key's field of view from the focal length."""
        chosen = self._selected_key()
        if self._updating or chosen is None or chosen[0] != CAMERA_KEY:
            return
        key = chosen[2]
        fov = fov_from_focal(self.focal_box.value())
        if key.fov != fov:
            self.host.execute(camera_edit.SetCameraValue(key, "fov", fov, "Set Field Of View"))

    def _choice(self, buttons: QButtonGroup, fallback: str) -> str:
        button = buttons.checkedButton()
        return str(button.property("value")) if button is not None else fallback

    def _animation_paths(self, animation: CameraAnimation) -> tuple[list[Vec3], list[Vec3]]:
        """The camera's and the look-at point's paths, kept until the animation changes."""
        if self._paths is None:
            self._paths = (
                camera_edit.path_points(animation, _PATH_SAMPLES),
                camera_edit.path_points(animation, _PATH_SAMPLES, look_at=True),
            )
        return self._paths

    def refresh_scene(self) -> None:
        """Send the camera objects again, as when the panel is shown."""
        self._send_scene()

    def _send_scene(self) -> None:
        """Tell the 3D view what to draw and what may be dragged: the chosen animation's keys and
        paths, or on the Named Cameras tab the map's named cameras."""
        document = self.host.document
        system = self._choice(self.system_buttons, WORLD)
        motion = self._choice(self.motion_buttons, TRANSLATE)
        far_clip = self.far_clip_box.value()
        preview = self.preview_box.isChecked()
        if document is None:
            self.scene_changed.emit(None)
            return
        if self.tabs.currentIndex() == 0:
            cameras, row = self._cameras(), self.camera_list.currentRow()
            chosen = 0 <= row < len(cameras)
            pose = view_pose(named_camera_view(document.map, cameras[row])) if chosen else None
            self.scene_changed.emit(
                CameraScene(
                    objects=[
                        camera_edit.named_object(camera, index)
                        for index, camera in enumerate(cameras)
                    ],
                    selected=(NAMED_CAMERA, row) if chosen else None,
                    system=system,
                    motion=motion,
                    preview=pose if preview else None,
                    far_clip=far_clip,
                )
            )
            return
        animation = self.selected_animation()
        if animation is None:
            self.scene_changed.emit(None)
            return
        camera_path, look_at_path = self._animation_paths(animation)
        self.scene_changed.emit(
            CameraScene(
                animation=animation,
                objects=camera_edit.objects(animation),
                selected=self._object_key(self.key_list.currentRow()),
                system=system,
                motion=motion,
                camera_path=camera_path if self.path_box.isChecked() else None,
                look_at_path=look_at_path if self.look_path_box.isChecked() else None,
                preview=evaluate(animation, self.frame) if preview else None,
                far_clip=far_clip,
            )
        )

    def _selected_keys(self) -> list[tuple[str, object]]:
        animation = self.selected_animation()
        if animation is None:
            return []
        rows: list[tuple[str, object]] = [("Camera", key) for key in camera_keys(animation)]
        rows += [("Look-at", key) for key in look_at_keys(animation)]
        return rows

    def delete_key(self) -> None:
        animation, row = self.selected_animation(), self.key_list.currentRow()
        rows = self._selected_keys()
        if animation is None or not 0 <= row < len(rows):
            return
        track_name, key = rows[row]
        track = camera_keys(animation) if track_name == "Camera" else look_at_keys(animation)
        try:
            self.host.execute(delete_key(track, key.frame_index))  # type: ignore[attr-defined]
        except ValueError as exc:
            self.host.show_status(str(exc).capitalize() + ".")

    def _set_interpolation(self, _index: int) -> None:
        rows, row = self._selected_keys(), self.key_list.currentRow()
        if self._updating or not 0 <= row < len(rows):
            return
        key = rows[row][1]
        method = self.interpolation_box.currentData()
        if getattr(key, "interpolation_type", None) != method:
            self.host.execute(set_interpolation(key, method))

    def _show_key(self) -> None:
        rows, row = self._selected_keys(), self.key_list.currentRow()
        chosen, animation = self._selected_key(), self.selected_animation()
        sending = self._updating
        if not self._updating:
            # What the view draws the handles on, kept for the next refresh to choose again.
            self._chosen = self._object_key(row)
        self._updating = True
        try:
            has_key = 0 <= row < len(rows)
            self.interpolation_box.setEnabled(has_key)
            self.delete_key_button.setEnabled(has_key)
            if has_key:
                method = getattr(rows[row][1], "interpolation_type", SPLINE)
                self.interpolation_box.setCurrentIndex(0 if method == SPLINE else 1)
            self._show_key_fields(chosen, animation)
        finally:
            self._updating = False
        if not sending and self.tabs.currentIndex() == 1:
            self._send_scene()

    def _show_key_fields(
        self, chosen: tuple[str, int, object] | None, animation: CameraAnimation | None
    ) -> None:
        """Fill the chosen key's position, facing and lens, and grey what it does not store: a
        look-at point has no facing, and a look-at animation's camera key only a roll."""
        is_camera = chosen is not None and chosen[0] == CAMERA_KEY
        free = is_camera and animation is not None and animation.animation_type == FREE
        for box in self.angle_boxes.values():
            box.setEnabled(free)
        self.angle_boxes["roll"].setEnabled(is_camera)
        self.focal_box.setEnabled(is_camera)
        for box in self.position_boxes.values():
            box.setEnabled(chosen is not None)
        if chosen is None:
            self.fov_label.setText("")
            return
        kind, _index, key = chosen
        position = key.position if kind == CAMERA_KEY else key.look_at_point
        for axis, value in zip("xyz", position, strict=True):
            self.position_boxes[axis].setValue(float(value))
        if not is_camera:
            self.fov_label.setText("")
            return
        if free:
            yaw, pitch, roll = rotation_angles(key.rotation)
        else:
            pose = evaluate(animation, key.frame_index) if animation is not None else None
            forward = pose_axes(pose)[0] if pose is not None else (0.0, 1.0, 0.0)
            yaw = math.atan2(forward[0], forward[1])
            pitch = math.asin(max(-1.0, min(1.0, -forward[2])))
            roll = float(key.roll)
        for name, value in (("yaw", yaw), ("pitch", pitch), ("roll", roll)):
            self.angle_boxes[name].setValue(math.degrees(value))
        self.focal_box.setValue(focal_length(key.fov) if key.fov > 0 else 0.0)
        self.fov_label.setText(f"{math.degrees(key.fov):.1f}° field of view")

    def _show_animation(self) -> None:
        animation = self.selected_animation()
        self._paths = None
        self._updating = True
        try:
            for widget in (
                self.animation_name,
                self.animation_length,
                self.animation_start,
                self.frame_slider,
                self.frame_box,
                self.play_button,
                self.camera_key_button,
            ):
                widget.setEnabled(animation is not None)
            self.look_key_button.setEnabled(
                animation is not None and animation.animation_type == LOOK
            )
            if animation is None:
                self.key_list.clear()
                self.timer.stop()
                return
            self.animation_name.setText(animation.name)
            self.animation_length.setValue(animation.num_frames)
            self.animation_start.setValue(animation.start_offset)
            last = max(animation.num_frames - 1, 0)
            self.frame_slider.setMaximum(last)
            self.frame_box.setMaximum(last)
            self.key_list.clear()
            for track_name, key in self._selected_keys():
                method = "Linear" if key.interpolation_type == LINEAR else "Smooth"  # type: ignore[attr-defined]
                self.key_list.addItem(f"{track_name} key at frame {key.frame_index} ({method})")  # type: ignore[attr-defined]
            row = self._object_row(self._chosen)
            self.key_list.setCurrentRow(row if row >= 0 else min(0, self.key_list.count() - 1))
        finally:
            self._updating = False
        if animation is None:
            self._show_key_fields(None, None)
            if self.tabs.currentIndex() == 1:
                self._send_scene()
            return
        self._show_key()
        self._send_path()

    def _send_path(self) -> None:
        animation = self.selected_animation()
        if animation is None or not self.path_box.isChecked():
            self.path_changed.emit(None)
            return
        count = min(animation.num_frames, _PATH_SAMPLES)
        step = max(animation.num_frames - 1, 1) / max(count - 1, 1)
        points = []
        for index in range(count):
            pose = evaluate(animation, index * step)
            if pose is not None:
                points.append((pose.position[0], pose.position[1]))
        keys = [(key.position[0], key.position[1]) for key in camera_keys(animation)]
        self.path_changed.emit((points, keys))

    def refresh(self) -> None:
        cameras, animations = self._cameras(), self._animations()
        self._updating = True
        try:
            row = self.camera_list.currentRow()
            self.camera_list.clear()
            for camera in cameras:
                self.camera_list.addItem(camera.name)
            self.camera_list.setCurrentRow(min(max(row, 0), len(cameras) - 1) if cameras else -1)
            index = self.animation_box.currentIndex()
            self.animation_box.clear()
            for animation in animations:
                kind = "free" if animation.animation_type == FREE else "look-at"
                self.animation_box.addItem(f"{animation.name} ({kind})")
            self.animation_box.setCurrentIndex(
                min(max(index, 0), len(animations) - 1) if animations else -1
            )
        finally:
            self._updating = False
        self._show_camera()
        self._show_animation()
