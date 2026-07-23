"""Import-guard tests for `sage_w3d.render.viewport` and the `examples/sage_w3d/view_model.py`
PyQt6 example: both need the `w3d-view` extra (PyQt6, PyOpenGL, numpy, pillow), so this module
skips outright when it is not installed (pattern: `tests/sage_asset/test_ui.py`) rather than
failing the core suite. No GL context is created here - constructing/painting a real
`QOpenGLWidget` needs a display or software rasterizer, which is the smoke-run gate's job
(`examples/sage_w3d/view_model.py --smoke`), not this data-free test."""

import importlib.util
import math
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="the [w3d-view] extra (PyQt6) is not installed")
pytest.importorskip("OpenGL", reason="the [w3d-view] extra (PyOpenGL) is not installed")
pytest.importorskip("numpy", reason="the [w3d-view] extra (numpy) is not installed")

import numpy as np  # noqa: E402
from PyQt6.QtCore import QObject  # noqa: E402
from PyQt6.QtOpenGLWidgets import QOpenGLWidget  # noqa: E402

from sage_w3d.render.viewport import (  # noqa: E402
    CAMERA_PRESETS,
    LIGHTING_PRESETS,
    PlaybackController,
    W3DViewport,
    _skinned_arrays,
)

_EXAMPLE = Path(__file__).parents[2] / "examples" / "sage_w3d" / "view_model.py"


def test_viewport_class_imports_and_is_a_qopenglwidget():
    assert issubclass(W3DViewport, QOpenGLWidget)


def test_camera_presets_cover_the_six_finalbigv2_directions():
    assert set(CAMERA_PRESETS) == {"front", "back", "left", "right", "top", "bottom"}


def test_lighting_presets_cover_the_five_finalbigv2_presets():
    assert set(LIGHTING_PRESETS) == {"Default", "Bright", "Moody", "Top Light", "Side Light"}
    for preset in LIGHTING_PRESETS.values():
        assert set(preset) == {"position", "ambient", "diffuse"}


def test_example_script_imports_without_error():
    spec = importlib.util.spec_from_file_location("view_model", _EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "main")
    assert hasattr(module, "BigArchiveResolver")


class TestSkinnedArrays:
    """`_skinned_arrays` is pure numpy with no GL calls, so it is headless-testable - these
    exercise the linear-blend-skinning math directly, independent of `W3DViewport`."""

    def test_identity_pose_reproduces_local_arrays(self):
        local_positions = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
        local_normals = np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0]], dtype=np.float32)
        bone_indices = np.array([[0, 0], [0, 0]], dtype=np.int32)
        bone_weights = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
        matrices = np.stack([np.eye(4, dtype=np.float32)])

        positions, normals = _skinned_arrays(
            local_positions, local_normals, bone_indices, bone_weights, matrices
        )

        assert positions == pytest.approx(local_positions)
        assert normals == pytest.approx(local_normals)

    def test_translation_only_bone_moves_its_vertices(self):
        local_positions = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        local_normals = np.array([[0.0, 0.0, 1.0]], dtype=np.float32)
        bone_indices = np.array([[0, 0]], dtype=np.int32)
        bone_weights = np.array([[1.0, 0.0]], dtype=np.float32)
        bone = np.eye(4, dtype=np.float32)
        bone[0, 3] = 5.0
        bone[1, 3] = -2.0
        matrices = np.stack([bone])

        positions, normals = _skinned_arrays(
            local_positions, local_normals, bone_indices, bone_weights, matrices
        )

        assert positions[0] == pytest.approx([6.0, -2.0, 0.0])
        assert normals[0] == pytest.approx([0.0, 0.0, 1.0])  # translation doesn't rotate normals

    def test_zero_weight_rows_stay_at_rest(self):
        local_positions = np.array([[3.0, 4.0, 5.0]], dtype=np.float32)
        local_normals = np.array([[0.0, 1.0, 0.0]], dtype=np.float32)
        bone_indices = np.array([[0, 0]], dtype=np.int32)
        bone_weights = np.array([[0.0, 0.0]], dtype=np.float32)
        bone = np.eye(4, dtype=np.float32)
        bone[0, 3] = 100.0  # would move the vertex a long way if it were used
        matrices = np.stack([bone])

        positions, normals = _skinned_arrays(
            local_positions, local_normals, bone_indices, bone_weights, matrices
        )

        assert positions[0] == pytest.approx([3.0, 4.0, 5.0])
        assert normals[0] == pytest.approx([0.0, 1.0, 0.0])

    def test_normals_stay_unit_length_after_a_rotation(self):
        local_positions = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
        local_normals = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        bone_indices = np.array([[0, 0]], dtype=np.int32)
        bone_weights = np.array([[1.0, 0.0]], dtype=np.float32)
        angle = math.radians(37.0)
        bone = np.eye(4, dtype=np.float32)
        bone[0, 0], bone[0, 1] = math.cos(angle), -math.sin(angle)
        bone[1, 0], bone[1, 1] = math.sin(angle), math.cos(angle)
        matrices = np.stack([bone])

        _, normals = _skinned_arrays(
            local_positions, local_normals, bone_indices, bone_weights, matrices
        )

        assert float(np.linalg.norm(normals[0])) == pytest.approx(1.0)


class TestPlaybackController:
    def test_is_a_qobject(self):
        assert issubclass(PlaybackController, QObject)

    def test_has_the_expected_transport_api(self):
        for name in ("play", "pause", "toggle", "set_frame", "set_evaluator", "frame_changed"):
            assert hasattr(PlaybackController, name)
