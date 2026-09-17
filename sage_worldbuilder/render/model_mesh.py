"""Placed objects' models as the 3D view draws them: each mesh of a model as flat arrays ready for
the GPU, and where each copy of a model stands.

A model is drawn once for every object that shows it, turned about the vertical by the object's
angle (radians, counter-clockwise from +x), scaled by its `objectPrototypeScale`, and stood on
the ground plus the object's own height: an object's stored z is its height above the terrain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sage_map.assets.object_list import Object
    from sage_w3d.render.scene import Scene
    from sage_worldbuilder.models import ArtIndex, ObjectModels

__all__ = [
    "ModelGeometry",
    "ModelPart",
    "instance_matrices",
    "load_object_models",
    "model_geometry",
    "object_scale",
]

_SCALE_KEY = "objectPrototypeScale"


@dataclass(frozen=True, eq=False)
class ModelPart:
    """One mesh: `(N, 3)` positions and normals, `(N, 2)` texture coordinates or None, triangle
    indices, and how it is shaded."""

    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray | None
    indices: np.ndarray
    texture: str | None
    color: tuple[float, float, float, float]
    two_sided: bool
    translucent: bool
    alpha_test: bool
    # Added to what is already drawn rather than mixed into it, and lit by itself rather than by
    # the map's lights: a flame, a glow or a sky, which are pictures of light.
    additive: bool = False
    unlit: bool = False


@dataclass(frozen=True, eq=False)
class ModelGeometry:
    parts: tuple[ModelPart, ...]

    def textures(self) -> set[str]:
        return {part.texture for part in self.parts if part.texture is not None}


def model_geometry(scene: Scene, texture: str | None = None) -> ModelGeometry:
    """A built W3D scene's meshes as parts; `texture` replaces the texture of every mesh with
    texture coordinates. A mesh without triangles, or with an index past its vertices, is left
    out."""
    parts = []
    for mesh in scene.meshes:
        positions = np.asarray(mesh.positions, dtype=np.float32).reshape(-1, 3)
        indices = np.asarray(mesh.indices, dtype=np.uint32)
        if not indices.size or int(indices.max()) >= len(positions):
            continue
        normals = np.asarray(mesh.normals, dtype=np.float32).reshape(-1, 3)
        if normals.shape != positions.shape:
            normals = np.tile(np.array((0.0, 0.0, 1.0), dtype=np.float32), (len(positions), 1))
        uvs = None
        if mesh.uvs is not None:
            uvs = np.asarray(mesh.uvs, dtype=np.float32).reshape(-1, 2)
            if len(uvs) != len(positions):
                uvs = None
        name = mesh.texture if uvs is not None else None
        if texture is not None and uvs is not None:
            name = texture
        parts.append(
            ModelPart(
                positions=np.ascontiguousarray(positions),
                normals=np.ascontiguousarray(normals),
                uvs=np.ascontiguousarray(uvs) if uvs is not None else None,
                indices=np.ascontiguousarray(indices),
                texture=name,
                color=mesh.color,
                two_sided=mesh.two_sided,
                translucent=mesh.translucent,
                alpha_test=getattr(mesh, "alpha_test", False),
                additive=getattr(mesh, "additive", False),
                unlit=getattr(mesh, "unlit", False),
            )
        )
    return ModelGeometry(tuple(parts))


def load_object_models(
    names: Iterable[str], models: ObjectModels, art: ArtIndex
) -> tuple[dict[str, ModelGeometry | None], dict[str, np.ndarray | None]]:
    """The geometry of each object name's model (None for an object with no model, or one whose
    files are missing or cannot be read), and the RGBA pixels of every texture those models use
    by lower-case name, bottom row first as OpenGL takes them (None where unreadable)."""
    from sage_w3d.render.scene import build_scene  # noqa: PLC0415 - lazy: parsing is on demand
    from sage_w3d.render.textures import decode_texture  # noqa: PLC0415

    geometry: dict[str, ModelGeometry | None] = {}
    textures: dict[str, np.ndarray | None] = {}
    for name in names:
        chosen = models.get(name)
        try:
            model = art.find_model(chosen.model) if chosen is not None else None
            built = (
                model_geometry(build_scene(model, art, chosen.skeleton), chosen.texture)
                if model is not None and chosen is not None
                else None
            )
        except Exception:  # noqa: BLE001 - one unreadable model must not lose the rest
            built = None
        geometry[name] = built
        for texture in built.textures() if built is not None else ():
            key = texture.lower()
            if key in textures:
                continue
            data = art.find_texture(texture)
            try:
                width, height, rgba = decode_texture(data) if data is not None else (0, 0, b"")
            except (ImportError, OSError, ValueError):
                width = height = 0
            if width and height:
                pixels = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4)
                textures[key] = np.ascontiguousarray(pixels[::-1])
            else:
                textures[key] = None
    return geometry, textures


def object_scale(obj: Object) -> float:
    """An object's `objectPrototypeScale`, 1 when it has none or a scale that is not positive."""
    stored = obj.properties.get(_SCALE_KEY)
    try:
        scale = float(stored["value"]) if stored is not None else 1.0
    except (TypeError, ValueError):
        return 1.0
    return scale if scale > 0 else 1.0


def instance_matrices(
    xs: np.ndarray, ys: np.ndarray, zs: np.ndarray, angles: np.ndarray, scales: np.ndarray
) -> np.ndarray:
    """`(N, 4, 4)` row-major world matrices: scale, turn about z by the angle, then move."""
    cos, sin = np.cos(angles), np.sin(angles)
    matrices = np.zeros((len(xs), 4, 4), dtype=np.float32)
    matrices[:, 0, 0] = cos * scales
    matrices[:, 0, 1] = -sin * scales
    matrices[:, 1, 0] = sin * scales
    matrices[:, 1, 1] = cos * scales
    matrices[:, 2, 2] = scales
    matrices[:, 0, 3] = xs
    matrices[:, 1, 3] = ys
    matrices[:, 2, 3] = zs
    matrices[:, 3, 3] = 1.0
    return matrices
