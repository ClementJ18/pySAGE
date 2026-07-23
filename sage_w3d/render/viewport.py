"""`W3DViewport`, a `QOpenGLWidget` that renders a `Scene` (see `scene.py`) with the
fixed-function GL pipeline via vertex arrays - `glVertexPointer`/`glNormalPointer`/
`glTexCoordPointer` + `glDrawElements`, never `glBegin` immediate mode. Geometry uploads once
per scene; only the camera and lighting state, and - under pose playback - the posed vertex
arrays, change per frame.

Interaction (orbit-drag camera, wheel zoom, arrow-key nudge, camera and lighting presets) is
ported from finalBIGv2's W3D tab - its interaction design, not its renderer, which is what
`scene.py` exists to fix (its module docstring explains the bug). Needs the `w3d-view` extra
(PyQt6, PyOpenGL, numpy, Pillow); this module is the only one in `sage_w3d.render` that imports
them, and it is only ever imported lazily by its consumers (`sage_w3d.__main__`'s `view`
command, `examples/sage_w3d/view_model.py`).

Pose playback (`set_pose`, `_skinned_arrays`, `PlaybackController`) re-skins a `Scene`'s meshes
on the CPU against a `sage_w3d.render.pose.Pose` every frame, rather than uploading new geometry
or skinning on the GPU - simple, and fast enough for the polycounts real W3D models carry."""

import math
from dataclasses import dataclass, field

import numpy as np
from OpenGL.GL import (
    GL_AMBIENT,
    GL_AMBIENT_AND_DIFFUSE,
    GL_BLEND,
    GL_COLOR_BUFFER_BIT,
    GL_COLOR_MATERIAL,
    GL_CULL_FACE,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_DIFFUSE,
    GL_FALSE,
    GL_FLOAT,
    GL_FRONT_AND_BACK,
    GL_LIGHT0,
    GL_LIGHTING,
    GL_LINEAR,
    GL_MODELVIEW,
    GL_NORMAL_ARRAY,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_POSITION,
    GL_PROJECTION,
    GL_REPEAT,
    GL_RGBA,
    GL_SRC_ALPHA,
    GL_TEXTURE_2D,
    GL_TEXTURE_COORD_ARRAY,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLES,
    GL_TRUE,
    GL_UNSIGNED_BYTE,
    GL_UNSIGNED_INT,
    GL_VERTEX_ARRAY,
    glBindTexture,
    glBlendFunc,
    glClear,
    glClearColor,
    glColor4f,
    glColorMaterial,
    glDepthMask,
    glDisable,
    glDisableClientState,
    glDrawElements,
    glEnable,
    glEnableClientState,
    glGenTextures,
    glLightfv,
    glLoadIdentity,
    glMatrixMode,
    glMultMatrixf,
    glNormalPointer,
    glTexCoordPointer,
    glTexImage2D,
    glTexParameteri,
    glTranslatef,
    glVertexPointer,
    glViewport,
)
from OpenGL.GLU import gluPerspective
from PyQt6.QtCore import QElapsedTimer, QObject, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget

from sage_w3d.render.pose import Pose, PoseEvaluator
from sage_w3d.render.scene import RenderMesh, Scene
from sage_w3d.render.textures import decode_texture

__all__ = ["CAMERA_PRESETS", "LIGHTING_PRESETS", "PlaybackController", "W3DViewport"]

CAMERA_FOV = 45.0
CAMERA_PADDING = 1.5
ROTATION_STEP = 5.0
MOUSE_SENSITIVITY = 0.5

# (rot_x, rot_y) degrees for each named camera preset - ported from finalBIGv2's camera_presets.
# (pitch, yaw) pairs applied on top of the Z-up base orientation (`_z_up_base`), so "front"
# is a head-on view of a standing model and "top" looks down the world's +Z axis.
CAMERA_PRESETS: dict[str, tuple[float, float]] = {
    "front": (0.0, 0.0),
    "back": (0.0, 180.0),
    "left": (0.0, -90.0),
    "right": (0.0, 90.0),
    "top": (90.0, 0.0),
    "bottom": (-90.0, 0.0),
}

# Ported verbatim from finalBIGv2's LIGHTING_PRESETS (GL_LIGHT0 position/ambient/diffuse).
LIGHTING_PRESETS: dict[str, dict[str, list[float]]] = {
    "Default": {
        "position": [0.5, 1.0, 1.0, 0.0],
        "ambient": [0.2, 0.2, 0.2, 1.0],
        "diffuse": [0.8, 0.8, 0.8, 1.0],
    },
    "Bright": {
        "position": [0.5, 1.0, 1.0, 0.0],
        "ambient": [0.4, 0.4, 0.4, 1.0],
        "diffuse": [1.0, 1.0, 1.0, 1.0],
    },
    "Moody": {
        "position": [-0.2, 0.5, 0.2, 0.0],
        "ambient": [0.05, 0.05, 0.1, 1.0],
        "diffuse": [0.3, 0.3, 0.5, 1.0],
    },
    "Top Light": {
        "position": [0.0, 2.0, 0.0, 0.0],
        "ambient": [0.1, 0.1, 0.1, 1.0],
        "diffuse": [0.8, 0.8, 0.7, 1.0],
    },
    "Side Light": {
        "position": [2.0, 0.0, 0.0, 0.0],
        "ambient": [0.1, 0.1, 0.1, 1.0],
        "diffuse": [0.7, 0.8, 0.8, 1.0],
    },
}


def _rotation_y(angle_deg: float) -> np.ndarray:
    rot = np.eye(4, dtype=np.float32)
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    rot[0, 0] = cos_a
    rot[0, 2] = sin_a
    rot[2, 0] = -sin_a
    rot[2, 2] = cos_a
    return rot


def _rotation_x(angle_deg: float) -> np.ndarray:
    rot = np.eye(4, dtype=np.float32)
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    rot[1, 1] = cos_a
    rot[1, 2] = -sin_a
    rot[2, 1] = sin_a
    rot[2, 2] = cos_a
    return rot


def _z_up_base() -> np.ndarray:
    """W3D models are Z-up (a standing character extends along +Z), while the GL camera looks
    down its -Z with +Y up - an identity orientation would show every model top-down. Pitching
    the world -90 degrees about X maps world +Z to screen up, making the default view a
    head-on look at a standing model."""
    return _rotation_x(-90.0)


@dataclass
class _MeshBuffers:
    """Everything one mesh needs to draw, plus what pose playback needs to re-skin it. `positions`/
    `normals` are the arrays actually drawn - the baked rest pose at first, swapped for freshly
    skinned arrays by `set_pose` and swapped back to `rest_positions`/`rest_normals` by
    `set_pose(None)`. `skin_*` are `None` for a mesh with no skeleton to pose against
    (`RenderMesh.skin is None`) - such a mesh is never re-skinned, only ever shown at rest."""

    name: str
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray | None
    indices: np.ndarray
    texture_name: str | None
    color: tuple[float, float, float, float]
    two_sided: bool
    translucent: bool
    sort_level: int
    rest_positions: np.ndarray
    rest_normals: np.ndarray
    skin_local_positions: np.ndarray | None
    skin_local_normals: np.ndarray | None
    skin_bone_indices: np.ndarray | None
    skin_bone_weights: np.ndarray | None
    rigid_bone: int | None
    visible: bool = field(default=True)
    pose_visible: bool = field(default=True)
    texture_id: int | None = field(default=None)


def _build_buffers(mesh: RenderMesh) -> _MeshBuffers:
    positions = np.array(mesh.positions, dtype=np.float32).reshape(-1, 3)
    normals = np.array(mesh.normals, dtype=np.float32).reshape(-1, 3)
    skin = mesh.skin
    return _MeshBuffers(
        name=mesh.name,
        positions=positions,
        normals=normals,
        uvs=np.array(mesh.uvs, dtype=np.float32).reshape(-1, 2) if mesh.uvs is not None else None,
        indices=np.array(mesh.indices, dtype=np.uint32),
        texture_name=mesh.texture,
        color=mesh.color,
        two_sided=mesh.two_sided,
        translucent=mesh.translucent,
        sort_level=mesh.sort_level,
        rest_positions=positions,
        rest_normals=normals,
        skin_local_positions=(
            np.array(skin.local_positions, dtype=np.float32).reshape(-1, 3)
            if skin is not None
            else None
        ),
        skin_local_normals=(
            np.array(skin.local_normals, dtype=np.float32).reshape(-1, 3)
            if skin is not None
            else None
        ),
        skin_bone_indices=(
            np.array(skin.bone_indices, dtype=np.int32).reshape(-1, 2) if skin is not None else None
        ),
        skin_bone_weights=(
            np.array(skin.bone_weights, dtype=np.float32).reshape(-1, 2)
            if skin is not None
            else None
        ),
        rigid_bone=mesh.rigid_bone,
    )


def _skinned_arrays(
    local_positions: np.ndarray,
    local_normals: np.ndarray,
    bone_indices: np.ndarray,
    bone_weights: np.ndarray,
    matrices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Linear blend skinning for every vertex at once: `M = w0*B[i0] + w1*B[i1]`, positions
    transformed by the full `4x4` (rotation and translation), normals by its rotation block
    only, then renormalized. A row with `w0 + w1 == 0` (`MeshSkin`'s "no valid influence"
    convention) uses the identity matrix, leaving that vertex at its local position - the same
    fallback `scene._blend_matrix_for_pair` bakes into the rest pose. `local_positions`/
    `local_normals` are `(N, 3)`, `bone_indices`/`bone_weights` are `(N, 2)` - `MeshSkin`'s flat
    per-vertex arrays reshaped for numpy; `matrices` is `(P, 4, 4)`, one row-major matrix per
    hierarchy pivot (`Pose.world_matrices` as an array). No GL calls, so this is headless-
    testable without a display or GPU."""
    idx0, idx1 = bone_indices[:, 0], bone_indices[:, 1]
    weight0, weight1 = bone_weights[:, 0:1, None], bone_weights[:, 1:2, None]
    blended = matrices[idx0] * weight0 + matrices[idx1] * weight1  # (N, 4, 4)

    no_influence = (bone_weights[:, 0] + bone_weights[:, 1]) <= 0.0
    if np.any(no_influence):
        blended[no_influence] = np.eye(4, dtype=np.float32)

    ones = np.ones((local_positions.shape[0], 1), dtype=np.float32)
    homogeneous = np.concatenate([local_positions, ones], axis=1)
    positions = np.einsum("nij,nj->ni", blended, homogeneous)[:, :3]

    normals = np.einsum("nij,nj->ni", blended[:, :3, :3], local_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    safe_lengths = np.where(lengths == 0.0, 1.0, lengths)  # a zero-length normal divides by 1
    normals = normals / safe_lengths

    return positions.astype(np.float32), normals.astype(np.float32)


class W3DViewport(QOpenGLWidget):
    """Renders a `Scene`: opaque meshes first, then translucent ones (blending on, depth-write
    off) ordered by `sort_level`. Public, typed API; no Qt widgets beyond the GL widget itself -
    a toolbar or sidebar around it is the consumer's job (see `examples/sage_w3d/view_model.py`)."""

    def __init__(
        self,
        scene: Scene,
        textures: dict[str, bytes] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._textures_data: dict[str, bytes] = dict(textures) if textures else {}
        self._meshes: list[_MeshBuffers] = []
        self._rotation = np.eye(4, dtype=np.float32)
        self._zoom = -50.0
        self._zoom_near = -5.0
        self._zoom_far = -400.0
        self._zoom_step = 2.0
        self._bbox_center = (0.0, 0.0, 0.0)
        self._last_mouse: QPointF | None = None
        self._lighting_preset = "Default"
        self._scene = scene
        self.set_scene(scene)

    def set_scene(self, scene: Scene) -> None:
        self._scene = scene
        self._meshes = [_build_buffers(m) for m in scene.meshes]
        self.reset_camera()

    def set_mesh_visible(self, name: str, visible: bool) -> None:
        for mesh in self._meshes:
            if mesh.name == name:
                mesh.visible = visible
        self.update()

    def set_lighting(self, preset: str) -> None:
        self._lighting_preset = preset
        self.update()

    def set_pose(self, pose: Pose | None) -> None:
        """`None` restores every mesh's baked rest-pose arrays and `pose_visible = True`
        everywhere; otherwise re-skins every mesh carrying skin arrays against
        `pose.world_matrices` (`_skinned_arrays`) and sets each rigid mesh's `pose_visible` from
        `pose.pivot_visible[rigid_bone]` - a skin mesh's `pose_visible` is left at `True`
        always, since bit-channel visibility is a rigid-mesh-only effect (see
        `scene.RenderMesh`'s docstring). Either way, triggers a repaint."""
        if pose is None:
            for mesh in self._meshes:
                mesh.positions = mesh.rest_positions
                mesh.normals = mesh.rest_normals
                mesh.pose_visible = True
            self.update()
            return

        matrices = np.array(pose.world_matrices, dtype=np.float32)
        for mesh in self._meshes:
            if (
                mesh.skin_local_positions is not None
                and mesh.skin_local_normals is not None
                and mesh.skin_bone_indices is not None
                and mesh.skin_bone_weights is not None
            ):
                mesh.positions, mesh.normals = _skinned_arrays(
                    mesh.skin_local_positions,
                    mesh.skin_local_normals,
                    mesh.skin_bone_indices,
                    mesh.skin_bone_weights,
                    matrices,
                )
            if mesh.rigid_bone is not None and 0 <= mesh.rigid_bone < len(pose.pivot_visible):
                mesh.pose_visible = pose.pivot_visible[mesh.rigid_bone]
        self.update()

    def set_camera_preset(self, name: str) -> None:
        if name not in CAMERA_PRESETS:
            return
        rot_x, rot_y = CAMERA_PRESETS[name]
        self._rotation = _rotation_y(rot_y) @ _rotation_x(rot_x) @ _z_up_base()
        self.update()

    def reset_camera(self) -> None:
        """Fit the camera to `scene.bounds`, padded by `CAMERA_PADDING` - the same
        `compute_bounding_box` distance formula finalBIGv2 uses. The zoom clamp range is
        derived from the model's own size (not a fixed absolute constant like finalBIGv2's)
        since W3D models span a huge range of scales, from a torch prop to a fortress."""
        lo, hi = self._scene.bounds
        self._bbox_center = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2)
        max_dim = max(hi[i] - lo[i] for i in range(3))
        if max_dim <= 0.0:
            max_dim = 1.0
        self._zoom = -max_dim * CAMERA_PADDING / (2 * math.tan(math.radians(CAMERA_FOV / 2)))
        self._zoom_near = -max(max_dim * 0.02, 0.05)
        self._zoom_far = -max_dim * 50
        self._zoom_step = max_dim * 0.05
        self._rotation = _z_up_base()
        self.update()

    def _adjust_zoom(self, delta: float) -> None:
        self._zoom = max(self._zoom_far, min(self._zoom_near, self._zoom + delta))

    def initializeGL(self) -> None:
        glEnable(GL_DEPTH_TEST)
        glClearColor(0.2, 0.2, 0.2, 1.0)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)

    def resizeGL(self, w: int, h: int) -> None:
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(CAMERA_FOV, w / max(h, 1), 0.1, 100000.0)
        glMatrixMode(GL_MODELVIEW)

    def paintGL(self) -> None:
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        self._apply_lighting()

        glTranslatef(0.0, 0.0, self._zoom)
        glTranslatef(self._bbox_center[0], self._bbox_center[1], self._bbox_center[2])
        glMultMatrixf(self._rotation.T)
        glTranslatef(-self._bbox_center[0], -self._bbox_center[1], -self._bbox_center[2])

        opaque = [m for m in self._meshes if m.visible and m.pose_visible and not m.translucent]
        translucent = sorted(
            (m for m in self._meshes if m.visible and m.pose_visible and m.translucent),
            key=lambda m: m.sort_level,
        )

        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)
        for mesh in opaque:
            self._draw_mesh(mesh)

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        for mesh in translucent:
            self._draw_mesh(mesh)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)

    def _draw_mesh(self, mesh: _MeshBuffers) -> None:
        if mesh.two_sided:
            glDisable(GL_CULL_FACE)
        else:
            glEnable(GL_CULL_FACE)

        texture_id = self._texture_id_for(mesh)
        if texture_id is not None:
            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, texture_id)
            glEnableClientState(GL_TEXTURE_COORD_ARRAY)
            glTexCoordPointer(2, GL_FLOAT, 0, mesh.uvs)
        else:
            glDisable(GL_TEXTURE_2D)
            glDisableClientState(GL_TEXTURE_COORD_ARRAY)
            glColor4f(*mesh.color)

        glVertexPointer(3, GL_FLOAT, 0, mesh.positions)
        glNormalPointer(GL_FLOAT, 0, mesh.normals)
        glDrawElements(GL_TRIANGLES, len(mesh.indices), GL_UNSIGNED_INT, mesh.indices)

    def _texture_id_for(self, mesh: _MeshBuffers) -> int | None:
        if mesh.texture_name is None or mesh.uvs is None:
            return None
        if mesh.texture_id is not None:
            return mesh.texture_id
        data = self._textures_data.get(mesh.texture_name)
        if data is None:
            return None
        mesh.texture_id = self._load_texture(data)
        return mesh.texture_id

    def _load_texture(self, data: bytes) -> int:
        width, height, rgba = decode_texture(data)
        image = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4)
        image = np.flipud(image).copy()  # OpenGL's texture origin is bottom-left
        texture_id = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, texture_id)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, image)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        # GL_REPEAT, not finalBIGv2's GL_CLAMP_TO_EDGE - game UVs tile.
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        return texture_id

    def _apply_lighting(self) -> None:
        preset = LIGHTING_PRESETS.get(self._lighting_preset, LIGHTING_PRESETS["Default"])
        glLightfv(GL_LIGHT0, GL_POSITION, preset["position"])
        glLightfv(GL_LIGHT0, GL_AMBIENT, preset["ambient"])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, preset["diffuse"])

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        key = event.key()
        rotation_keys = {
            int(Qt.Key.Key_Left): (_rotation_y, ROTATION_STEP),
            int(Qt.Key.Key_Right): (_rotation_y, -ROTATION_STEP),
            int(Qt.Key.Key_Up): (_rotation_x, -ROTATION_STEP),
            int(Qt.Key.Key_Down): (_rotation_x, ROTATION_STEP),
        }
        if key in rotation_keys:
            make_rotation, angle = rotation_keys[key]
            self._rotation = make_rotation(angle) @ self._rotation
        elif key in (int(Qt.Key.Key_Plus), int(Qt.Key.Key_Equal), int(Qt.Key.Key_PageUp)):
            self._adjust_zoom(self._zoom_step)
        elif key in (
            int(Qt.Key.Key_Minus),
            int(Qt.Key.Key_Underscore),
            int(Qt.Key.Key_PageDown),
        ):
            self._adjust_zoom(-self._zoom_step)
        self.update()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse = event.position()
        self.setFocus()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None or self._last_mouse is None:
            return
        pos = event.position()
        dx = pos.x() - self._last_mouse.x()
        dy = pos.y() - self._last_mouse.y()
        if abs(dx) > 0.01 or abs(dy) > 0.01:
            rot_y = _rotation_y(-dx * MOUSE_SENSITIVITY)
            rot_x = _rotation_x(dy * MOUSE_SENSITIVITY)
            self._rotation = rot_y @ self._rotation @ rot_x
        self._last_mouse = pos
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._last_mouse = None

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is None:
            return
        delta = event.angleDelta().y() / 120
        self._adjust_zoom(delta * self._zoom_step)
        self.update()


_TIMER_INTERVAL_MS = 16  # ~60 Hz


class PlaybackController(QObject):
    """Drives a `sage_w3d.render.pose.PoseEvaluator` against a `W3DViewport` on a `QTimer`:
    while playing, each timeout advances the frame by `elapsed_seconds * evaluator.frame_rate`
    and loops it over `[0, num_frames - 1)` (`math.fmod`, `num_frames - 1` floored to `1` so a
    one-frame or header-less animation still advances something rather than dividing by zero).
    `frame_changed` fires with the frame just applied on every advance and on `set_frame`
    (scrubbing), so a UI slider can follow playback without polling it.

    Not a widget - Qt is already this module's domain, and nothing here draws; a caller wires it
    to one `W3DViewport` and, if it wants transport controls, a `QSlider`/`QPushButton` of its
    own (`examples/sage_w3d/view_model.py`; `sage_w3d.__main__`'s `view` command binds only
    Space, via `QShortcut`, to `toggle`)."""

    frame_changed = pyqtSignal(float)

    def __init__(self, viewport: W3DViewport, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._viewport = viewport
        self._evaluator: PoseEvaluator | None = None
        self._frame = 0.0
        self._playing = False
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(_TIMER_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

    @property
    def playing(self) -> bool:
        return self._playing

    def set_evaluator(self, evaluator: PoseEvaluator | None) -> None:
        """Switches to a new evaluator (or `None`, restoring the rest pose) and stops playback -
        the caller decides whether to `play()` again, e.g. auto-playing the newly picked
        animation from frame 0."""
        self.pause()
        self._evaluator = evaluator
        self._frame = 0.0
        if evaluator is None:
            self._viewport.set_pose(None)
        else:
            self._apply()

    def play(self) -> None:
        if self._evaluator is None or self._playing:
            return
        self._playing = True
        self._elapsed.start()
        self._timer.start()

    def pause(self) -> None:
        self._playing = False
        self._timer.stop()

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def set_frame(self, frame: float) -> None:
        """Scrubs to `frame` directly - evaluates, applies, and emits `frame_changed`, without
        touching whether playback is running."""
        self._frame = frame
        self._apply()

    def _advance(self) -> None:
        if self._evaluator is None:
            return
        dt_seconds = self._elapsed.restart() / 1000.0
        span = max(self._evaluator.num_frames - 1, 1)
        self._frame = math.fmod(self._frame + dt_seconds * self._evaluator.frame_rate, span)
        self._apply()

    def _apply(self) -> None:
        if self._evaluator is None:
            return
        self._viewport.set_pose(self._evaluator.evaluate(self._frame))
        self.frame_changed.emit(self._frame)
