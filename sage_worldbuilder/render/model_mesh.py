"""Placed objects' models as the 3D view draws them: each mesh of every model an object shows as
flat arrays ready for the GPU, and where each copy of a model stands.

A model is drawn once for every object that shows it, turned about the vertical by the object's
angle (radians, counter-clockwise from +x), scaled by its `objectPrototypeScale`, and stood on
the ground plus the object's own height: an object's stored z is its height above the terrain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

import numpy as np

from sage_w3d.render.scene import Scene, build_scene
from sage_w3d.render.textures import decode_texture

if TYPE_CHECKING:
    from sage_map.assets.object_list import Object
    from sage_worldbuilder.models import ArtIndex, ObjectModels

__all__ = [
    "ModelGeometry",
    "ModelPart",
    "aligned_to_terrain",
    "instance_matrices",
    "load_object_models",
    "model_geometry",
    "object_scale",
    "ray_hit_instances",
    "upright_rotations",
]

_SCALE_KEY = "objectPrototypeScale"
_ALIGN_KEY = "alignToTerrain"


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

    @cached_property
    def solid_triangles(self) -> np.ndarray:
        """`(T, 3, 3)` corners of the triangles a click can land on: every mesh but the additive
        ones, which are pictures of light (a flame's glow) rather than of the object."""
        corners = [
            part.positions[part.indices[: part.indices.size // 3 * 3].reshape(-1, 3)]
            for part in self.parts
            if not part.additive
        ]
        if not corners:
            return np.zeros((0, 3, 3), dtype=np.float64)
        return np.concatenate(corners).astype(np.float64)


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
    """The geometry of each object name (None for an object with no model, or one whose files are
    all missing or unreadable), and the RGBA pixels of every texture those models use by
    lower-case name, bottom row first as OpenGL takes them (None where unreadable).

    An object draws every model its draws show, so the parts of all of them make up its geometry:
    a building and the floor under it are one mesh list, at the object's own place. A draw whose
    model cannot be read is left out and the rest still draw."""
    geometry: dict[str, ModelGeometry | None] = {}
    textures: dict[str, np.ndarray | None] = {}
    for name in names:
        parts: list[ModelPart] = []
        for chosen in models.get(name):
            try:
                model = art.find_model(chosen.model)
                if model is None:
                    continue
                parts += model_geometry(
                    build_scene(model, art, chosen.skeleton), chosen.texture
                ).parts
            except Exception:  # noqa: BLE001 - one unreadable model must not lose the rest
                continue
        built = ModelGeometry(tuple(parts)) if parts else None
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


def aligned_to_terrain(obj: Object) -> bool:
    """An object's `alignToTerrain`: whether it lies along the slope it stands on instead of
    standing upright."""
    stored = obj.properties.get(_ALIGN_KEY)
    return bool(stored["value"]) if stored is not None else False


def upright_rotations(normals: np.ndarray) -> np.ndarray:
    """`(N, 3, 3)` rotations that take the world's up onto each unit normal by the shortest turn:
    what stands a model out of a slope rather than out of the level ground.

    Rodrigues about `up x normal`, whose length and dot give the turn; a normal pointing straight
    down (never terrain) would have no shortest turn, and is left upright."""
    normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    nx, ny, nz = normals[:, 0], normals[:, 1], normals[:, 2]
    # 1 + nz is 0 only for a normal pointing straight down; there the rotation stays the identity.
    share = np.where(1.0 + nz > 1e-9, 1.0 / np.maximum(1.0 + nz, 1e-9), 0.0)
    rotations = np.zeros((len(normals), 3, 3), dtype=np.float64)
    rotations[:, 0, 0] = 1.0 - nx * nx * share
    rotations[:, 0, 1] = -nx * ny * share
    rotations[:, 0, 2] = nx
    rotations[:, 1, 0] = -nx * ny * share
    rotations[:, 1, 1] = 1.0 - ny * ny * share
    rotations[:, 1, 2] = ny
    rotations[:, 2, 0] = -nx
    rotations[:, 2, 1] = -ny
    rotations[:, 2, 2] = 1.0 - (nx * nx + ny * ny) * share
    return rotations


def instance_matrices(
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray,
    angles: np.ndarray,
    scales: np.ndarray,
    normals: np.ndarray | None = None,
) -> np.ndarray:
    """`(N, 4, 4)` row-major world matrices: scale, turn about z by the angle, then move.

    With `normals`, a `(N, 3)` unit vector per copy, the turned model is laid along that normal
    first, which is how an object with `alignToTerrain` sits on a slope; the vertical normal every
    other object takes leaves the matrix as it would have been."""
    cos, sin = np.cos(angles), np.sin(angles)
    heading = np.zeros((len(xs), 3, 3), dtype=np.float64)
    heading[:, 0, 0] = cos
    heading[:, 0, 1] = -sin
    heading[:, 1, 0] = sin
    heading[:, 1, 1] = cos
    heading[:, 2, 2] = 1.0
    if normals is not None:
        heading = upright_rotations(normals) @ heading
    matrices = np.zeros((len(xs), 4, 4), dtype=np.float32)
    matrices[:, :3, :3] = heading * np.asarray(scales, dtype=np.float64)[:, None, None]
    matrices[:, 0, 3] = xs
    matrices[:, 1, 3] = ys
    matrices[:, 2, 3] = zs
    matrices[:, 3, 3] = 1.0
    return matrices


def ray_hit_instances(
    geometry: ModelGeometry,
    matrices: np.ndarray,
    origin: np.ndarray,
    direction: np.ndarray,
) -> tuple[int, float] | None:
    """The copy of a model a ray meets first, among copies standing at `(N, 4, 4)` world
    `matrices`: its index, and how far along the ray the hit is in units of `direction`; None
    when the ray meets none of them. Both faces of a triangle count."""
    triangles = geometry.solid_triangles
    if not len(triangles) or not len(matrices):
        return None
    inverse = np.linalg.inv(np.asarray(matrices, dtype=np.float64))
    # A world matrix is affine, so the ray carried into a copy's own space keeps its parameter:
    # a distance found there is the same distance along the world ray.
    origins = (inverse @ np.append(np.asarray(origin, dtype=np.float64), 1.0))[:, :3]
    directions = (inverse @ np.append(np.asarray(direction, dtype=np.float64), 0.0))[:, :3]
    corners = triangles.reshape(-1, 3)
    low, high = corners.min(axis=0), corners.max(axis=0)
    # The model's box first, to leave out the copies the ray passes nowhere near.
    with np.errstate(divide="ignore", invalid="ignore"):
        ta = (low - origins) / directions
        tb = (high - origins) / directions
    near = np.maximum(np.nanmax(np.minimum(ta, tb), axis=1), 0.0)
    far = np.nanmin(np.maximum(ta, tb), axis=1)
    candidates = np.flatnonzero(near <= far)
    best: tuple[int, float] | None = None
    for index in candidates[np.argsort(near[candidates])].tolist():
        if best is not None and near[index] > best[1]:
            break
        t = _triangles_hit(triangles, origins[index], directions[index])
        if t is not None and (best is None or t < best[1]):
            best = (index, t)
    return best


def _triangles_hit(
    triangles: np.ndarray, origin: np.ndarray, direction: np.ndarray
) -> float | None:
    """How far along the ray it first meets one of the `(T, 3, 3)` triangles, in front of its
    origin (Möller-Trumbore, over all the triangles at once)."""
    v0 = triangles[:, 0]
    e1 = triangles[:, 1] - v0
    e2 = triangles[:, 2] - v0
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    usable = np.abs(det) > 1e-12
    inverse = 1.0 / np.where(usable, det, 1.0)
    s = origin - v0
    u = np.einsum("ij,ij->i", s, p) * inverse
    q = np.cross(s, e1)
    v = (q @ direction) * inverse
    t = np.einsum("ij,ij->i", e2, q) * inverse
    hit = usable & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)
    return float(t[hit].min()) if hit.any() else None
