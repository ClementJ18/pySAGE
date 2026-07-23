"""Rendering layer for `sage_w3d`: backend-agnostic scene assembly (`math3d.py`, `scene.py`,
`pose.py` - stdlib-only, no Qt/OpenGL/numpy) plus a thin PyQt6/OpenGL viewport (`viewport.py`)
behind the `w3d-view` extra. `decode_texture` (`textures.py`) turns raw image bytes into the
RGBA buffer `viewport.py` uploads; it lazy-imports Pillow so this package's core stays
dependency-free. `pose.py`'s `PoseEvaluator` samples a parsed animation into a `Pose` of pivot
world matrices, which `viewport.py`'s `W3DViewport.set_pose` re-skins a `Scene`'s meshes
against - exported here since evaluating a pose needs no extra, only drawing one does.

`viewport.py` is not imported here - it needs the `w3d-view` extra, so consumers import it
directly (`from sage_w3d.render.viewport import W3DViewport`), the same lazy pattern
`sage_w3d.__main__`'s `view` command and `examples/sage_w3d/view_model.py` use; that also holds
for `PlaybackController`, which lives in `viewport.py` alongside it rather than here."""

from sage_w3d.render.pose import Pose, PoseEvaluator
from sage_w3d.render.scene import AssetResolver, DirectoryResolver, RenderMesh, Scene, build_scene
from sage_w3d.render.textures import decode_texture

__all__ = [
    "AssetResolver",
    "DirectoryResolver",
    "Pose",
    "PoseEvaluator",
    "RenderMesh",
    "Scene",
    "build_scene",
    "decode_texture",
]
