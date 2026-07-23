"""Backend-agnostic W3D scene assembly: resolves a model's skeleton (its own `Hierarchy`, or
one looked up by name through an `AssetResolver`), places every visible mesh - skin or rigid -
in world space, and returns a flat, upload-ready `Scene`. Skin meshes store vertices in
bone-local space (blending the skeleton's rest-pose world matrices by each vertex's 1-2 bone
influences reproduces the mesh header's own `min_corner`/`max_corner` bounds); rigid HLOD
sub-object meshes are bone-local too, placed by their sub-object's bone. Normals are
transformed by the rotation part of that same matrix, alongside positions, then renormalized -
reference tool finalBIGv2 transforms positions but leaves normals in bone-local space, and
since real BFME skeletons carry heavily rotated rest bones, that points normals into the
surface, reading as an inverted/caved-in model under lighting."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sage_w3d.binary import Vec2ListChunk, first_of
from sage_w3d.chunks import W3D_CHUNK_STAGE_TEXCOORDS
from sage_w3d.hierarchy import Hierarchy
from sage_w3d.hlod import HLOD, HLODSubObjectArray
from sage_w3d.mesh import (
    GEOMETRY_TYPE_HIDDEN,
    GEOMETRY_TYPE_TWO_SIDED,
    Mesh,
    Texture,
    VertexInfluence,
    VertexMaterial,
)
from sage_w3d.render.math3d import (
    IDENTITY,
    Mat4,
    Vec3,
    blend_matrices,
    multiply,
    normalize,
    pivot_local_matrix,
    transform_direction,
    transform_point,
)
from sage_w3d.w3d import W3DFile, parse_w3d_from_path

__all__ = [
    "AssetResolver",
    "DirectoryResolver",
    "MeshSkin",
    "RenderMesh",
    "Scene",
    "build_scene",
]

_TEXTURE_EXTENSIONS = (".dds", ".tga")


class AssetResolver(Protocol):
    """What `build_scene` needs from an art source to resolve a skeleton (looked up by the
    HLOD's `hierarchy_name`) or a texture (looked up by the name a material pass carries).
    Names are case-insensitive by contract."""

    def find_hierarchy(self, name: str) -> W3DFile | None: ...

    def find_texture(self, name: str) -> bytes | None: ...


class DirectoryResolver:
    """An `AssetResolver` over one or more art directories, indexed once by lowercase filename
    stem so repeated lookups (many meshes sharing one skeleton, one texture reused across
    meshes) never re-walk the filesystem. A W3D texture entry typically names a `.tga` that
    ships compiled as `.dds` (or vice versa); `find_texture` matches by stem across both
    extensions, mirroring finalBIGv2's base-name texture matching. Resolved hierarchies are
    cached by name so one resolver reused across many models (as the full corpus gate does,
    one per directory) parses each skeleton file only once."""

    def __init__(self, *directories: str | Path) -> None:
        self._by_stem: dict[str, list[Path]] = {}
        for directory in directories:
            base = Path(directory)
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    self._by_stem.setdefault(path.stem.lower(), []).append(path)
        self._hierarchy_cache: dict[str, W3DFile | None] = {}

    def find_hierarchy(self, name: str) -> W3DFile | None:
        stem = Path(name).stem.lower()
        if stem not in self._hierarchy_cache:
            self._hierarchy_cache[stem] = self._load_hierarchy(stem)
        return self._hierarchy_cache[stem]

    def _load_hierarchy(self, stem: str) -> W3DFile | None:
        for path in self._by_stem.get(stem, ()):
            if path.suffix.lower() == ".w3d":
                return parse_w3d_from_path(path)
        return None

    def find_texture(self, name: str) -> bytes | None:
        stem = Path(name).stem.lower()
        requested_ext = Path(name).suffix.lower()
        candidates = self._by_stem.get(stem, ())
        order = [requested_ext] if requested_ext else []
        order += [ext for ext in _TEXTURE_EXTENSIONS if ext not in order]
        for ext in order:
            for path in candidates:
                if path.suffix.lower() == ext:
                    return path.read_bytes()
        return None


@dataclass
class MeshSkin:
    """The per-vertex data pose playback needs to re-skin a mesh at any frame: its own rest
    positions/normals in bone-local space (the values `_transform_mesh` bakes from, before the
    rest-pose blend) and, per vertex, up to two bone indices with normalized weights
    (`bone_indices`/`bone_weights` are flat, 2 entries per vertex, index-aligned with
    `local_positions`/`local_normals`'s 3-per-vertex layout). Both weights zero means the vertex
    has no valid influence and stays at its rest position under any pose - the same fallback the
    baked rest-pose transform already applies. A rigid mesh's `MeshSkin` is a degenerate
    single-bone case: every vertex weighted 1.0 to its one HLOD sub-object bone."""

    local_positions: list[float]
    local_normals: list[float]
    bone_indices: list[int]
    bone_weights: list[float]


@dataclass
class RenderMesh:
    """One mesh ready for upload: flat position/normal/uv arrays already placed in world space,
    plus the triangle index list and the honest-v1 material read finalBIGv2 also uses (first
    material pass, first vertex material, stage-0 texture). `skin` carries the bone-local data
    pose playback re-skins from every frame - `None` when no skeleton resolved, since there is
    then nothing to pose against. `rigid_bone` is the HLOD sub-object bone a rigid mesh is placed
    by, used at pose time to look up the bone's bit-channel visibility; `None` for a skin mesh,
    since bit-channel visibility is a rigid-mesh-only effect (a skin mesh has no single bone to
    look one up by, and no real corpus file keys visibility off a skin's own influences)."""

    name: str
    positions: list[float]
    normals: list[float]
    uvs: list[float] | None
    indices: list[int]
    texture: str | None
    color: tuple[float, float, float, float]
    two_sided: bool
    translucent: bool
    sort_level: int
    skin: MeshSkin | None = None
    rigid_bone: int | None = None


@dataclass
class Scene:
    meshes: list[RenderMesh]
    bounds: tuple[Vec3, Vec3]
    bones: list[tuple[str, Mat4]]
    diagnostics: list[str]
    hierarchy: Hierarchy | None = None


def build_scene(model: W3DFile, resolver: AssetResolver | None = None) -> Scene:
    diagnostics: list[str] = []
    hierarchy = _resolve_hierarchy(model, resolver)
    bone_worlds = _pivot_world_matrices(hierarchy) if hierarchy is not None else []
    bones = (
        [(p.name.value, w) for p, w in zip(hierarchy.pivots, bone_worlds, strict=True)]
        if hierarchy is not None
        else []
    )

    has_hlod = model.hlod is not None
    render_meshes: list[RenderMesh] = []
    for mesh, bone_index in _select_meshes(model):
        header = mesh.header
        if header is not None and header.attrs & GEOMETRY_TYPE_HIDDEN:
            continue

        positions, normals, pairs, mesh_diag = _transform_mesh(
            mesh, bone_index, bone_worlds, has_hlod
        )
        if mesh_diag is not None:
            diagnostics.append(mesh_diag)

        vertex_count = len(mesh.vertices)
        uvs = _mesh_uvs(mesh)
        is_skin = bool(mesh.vertex_influences)
        render_meshes.append(
            RenderMesh(
                name=_mesh_full_name(mesh),
                positions=positions,
                normals=normals,
                uvs=_flatten_uvs(uvs, vertex_count) if uvs is not None else None,
                indices=[i for t in mesh.triangles for i in t.vert_ids],
                texture=_mesh_texture_name(mesh),
                color=_mesh_base_color(mesh),
                two_sided=bool(header.attrs & GEOMETRY_TYPE_TWO_SIDED) if header else False,
                translucent=_mesh_translucent(mesh),
                sort_level=header.sort_level if header else 0,
                skin=_mesh_skin(mesh, bone_worlds, pairs),
                rigid_bone=None if is_skin else bone_index,
            )
        )

    return Scene(
        meshes=render_meshes,
        bounds=_compute_bounds(render_meshes),
        bones=bones,
        diagnostics=diagnostics,
        hierarchy=hierarchy,
    )


def _mesh_full_name(mesh: Mesh) -> str:
    return f"{mesh.container_name}.{mesh.name}" if mesh.container_name else mesh.name


def _resolve_hierarchy(model: W3DFile, resolver: AssetResolver | None) -> Hierarchy | None:
    if model.hierarchy is not None:
        return model.hierarchy
    hlod = model.hlod
    if hlod is None or resolver is None:
        return None
    header = hlod.header
    if header is None:
        return None
    name = header.hierarchy_name.value
    if not name:
        return None
    found = resolver.find_hierarchy(name)
    return found.hierarchy if found is not None else None


def _pivot_world_matrices(hierarchy: Hierarchy) -> list[Mat4]:
    # Pivots are stored parent-before-child (the root at index 0), so a single left-to-right
    # pass can always look up an already-computed parent world matrix.
    worlds: list[Mat4] = []
    for pivot in hierarchy.pivots:
        local = pivot_local_matrix(pivot.translation, pivot.rotation)
        parent = pivot.parent_id
        if 0 <= parent < len(worlds):
            worlds.append(multiply(worlds[parent], local))
        else:
            worlds.append(local)
    return worlds


def _select_highest_detail_lod(hlod: HLOD) -> HLODSubObjectArray | None:
    """The LOD array with the greatest `header.max_screen_size`; ties favor the later array.
    Verified against the corpus's own multi-LOD files (e.g. `muatktroll_disa.w3d`): the array
    with the largest `max_screen_size` (here `3.4e38`, effectively unbounded) is the one whose
    sub-objects match real, populated meshes (3630 total vertices across 4 real parts); the
    file's other array (`max_screen_size == 0.0`) references a single bone-attachment
    placeholder with no matching mesh at all - confirming greatest-max_screen_size selects the
    tier meant to be rendered, not a lower-poly geometric alternative (this corpus's multi-LOD
    HLODs don't happen to carry two tiers of real geometry to cross-check against vertex count,
    but the ordering rule holds on the tiers that do exist)."""
    arrays = hlod.lod_arrays
    if not arrays:
        return None
    best = arrays[0]
    best_score = best.header.max_screen_size if best.header else float("-inf")
    for array in arrays[1:]:
        score = array.header.max_screen_size if array.header else float("-inf")
        if score >= best_score:
            best = array
            best_score = score
    return best


def _select_meshes(model: W3DFile) -> list[tuple[Mesh, int]]:
    meshes = model.meshes
    hlod = model.hlod
    if hlod is None:
        return [(m, 0) for m in meshes]

    lod = _select_highest_detail_lod(hlod)
    if lod is None:
        return [(m, 0) for m in meshes]

    by_key = {_mesh_full_name(m).lower(): m for m in meshes}
    selected: list[tuple[Mesh, int]] = []
    for sub in lod.sub_objects:
        mesh = by_key.get(sub.identifier.value.lower())
        # A sub-object with no matching mesh is overwhelmingly a collision box or other
        # non-mesh HLOD attachment (every model has at least a BOUNDINGBOX entry) - expected,
        # not worth a diagnostic on every single file in the corpus.
        if mesh is not None:
            selected.append((mesh, sub.bone_index))
    return selected


# A vertex's up to two bone influences, already weight-normalized against each other:
# (bone_idx0, weight0, bone_idx1, weight1). Both weights zero means no valid influence - the
# vertex stays at its rest position under any pose (bone_worlds/pivot 0 is never read in that
# case). Shared by the baked rest-pose transform below and the `MeshSkin` `build_scene` emits,
# so both are the same resolution computed once, not two copies that could drift apart.
_InfluencePair = tuple[int, float, int, float]

_NO_INFLUENCE: _InfluencePair = (0, 0.0, 0, 0.0)


def _influence_pair(influence: VertexInfluence, num_pivots: int) -> _InfluencePair:
    """One vertex's up to two bone influences, normalized leniently by their own sum after
    dropping any raw weight of zero or bone index `num_pivots` cannot resolve. The on-disk
    weight scale is not consistently 0-10000 across real files (some exporters wrote 0-100
    directly), so weights are normalized against each other rather than assumed to total any
    fixed constant - "leniently", per the format's own inconsistency."""
    weighted: list[tuple[int, float]] = []
    bone_weight = influence.bone_weight_raw / 10000
    if bone_weight > 0 and influence.bone_idx < num_pivots:
        weighted.append((influence.bone_idx, bone_weight))
    xtra_weight = influence.xtra_weight_raw / 10000
    if xtra_weight > 0 and influence.xtra_idx < num_pivots:
        weighted.append((influence.xtra_idx, xtra_weight))
    if not weighted:
        return _NO_INFLUENCE
    total = sum(w for _, w in weighted)
    idx0, w0 = weighted[0]
    if len(weighted) == 1:
        return (idx0, w0 / total, 0, 0.0)
    idx1, w1 = weighted[1]
    return (idx0, w0 / total, idx1, w1 / total)


def _vertex_bone_pairs(
    mesh: Mesh, bone_index: int, bone_worlds: list[Mat4], has_hlod: bool
) -> tuple[list[_InfluencePair], str | None]:
    """Each vertex's `_InfluencePair` for `mesh`: a skin mesh reads its own `VertexInfluence`
    records (`_influence_pair`); a rigid mesh (no influences at all) reports its HLOD
    sub-object's bone at full weight for every vertex, or no influence when that bone cannot
    resolve (no skeleton, or the sub-object's bone index is out of range)."""
    vertex_count = len(mesh.vertices)
    influences = mesh.vertex_influences

    if influences:
        num_pivots = len(bone_worlds)
        pairs = [
            _influence_pair(influences[i], num_pivots) if i < len(influences) else _NO_INFLUENCE
            for i in range(vertex_count)
        ]
        diag: str | None = None
        if not bone_worlds:
            diag = (
                f"{_mesh_full_name(mesh)}: no skeleton resolved, skin mesh left in bone-local space"
            )
        return pairs, diag

    diag = None
    if has_hlod and not bone_worlds:
        diag = f"{_mesh_full_name(mesh)}: no skeleton resolved, rigid mesh left in bone-local space"
    valid = bool(bone_worlds) and 0 <= bone_index < len(bone_worlds)
    pair = (bone_index, 1.0, 0, 0.0) if valid else _NO_INFLUENCE
    return [pair] * vertex_count, diag


def _blend_matrix_for_pair(pair: _InfluencePair, bone_worlds: list[Mat4]) -> Mat4:
    """The linear-blend-skinning matrix for one vertex's `_InfluencePair` - both weights zero
    (no valid influence) leaves the vertex at rest (`IDENTITY`)."""
    bone0, weight0, bone1, weight1 = pair
    if weight0 <= 0.0 and weight1 <= 0.0:
        return IDENTITY
    weighted = [(bone_worlds[bone0], weight0)]
    if weight1 > 0.0:
        weighted.append((bone_worlds[bone1], weight1))
    return blend_matrices(weighted)


def _transform_mesh(
    mesh: Mesh, bone_index: int, bone_worlds: list[Mat4], has_hlod: bool
) -> tuple[list[float], list[float], list[_InfluencePair], str | None]:
    pairs, diag = _vertex_bone_pairs(mesh, bone_index, bone_worlds, has_hlod)
    positions: list[float] = []
    normals: list[float] = []
    mesh_normals = mesh.normals
    for i, vertex in enumerate(mesh.vertices):
        m = _blend_matrix_for_pair(pairs[i], bone_worlds)
        positions.extend(transform_point(m, vertex))
        n = mesh_normals[i] if i < len(mesh_normals) else (0.0, 0.0, 1.0)
        normals.extend(normalize(transform_direction(m, n)))
    return positions, normals, pairs, diag


def _mesh_skin(mesh: Mesh, bone_worlds: list[Mat4], pairs: list[_InfluencePair]) -> MeshSkin | None:
    """The rest-space per-vertex skinning data pose playback re-skins from every frame: `mesh`'s
    own bone-local positions/normals (the same values `_transform_mesh` bakes from) alongside
    the `_InfluencePair`s that bake blends - `None` when no skeleton resolved, since there is
    then nothing to pose the mesh against."""
    if not bone_worlds:
        return None
    local_positions: list[float] = []
    local_normals: list[float] = []
    mesh_normals = mesh.normals
    for i, vertex in enumerate(mesh.vertices):
        local_positions.extend(vertex)
        n = mesh_normals[i] if i < len(mesh_normals) else (0.0, 0.0, 1.0)
        local_normals.extend(n)
    bone_indices: list[int] = []
    bone_weights: list[float] = []
    for bone0, weight0, bone1, weight1 in pairs:
        bone_indices.extend((bone0, bone1))
        bone_weights.extend((weight0, weight1))
    return MeshSkin(
        local_positions=local_positions,
        local_normals=local_normals,
        bone_indices=bone_indices,
        bone_weights=bone_weights,
    )


def _mesh_uvs(mesh: Mesh) -> list[tuple[float, float]] | None:
    passes = mesh.material_passes
    if not passes:
        return None
    material_pass = passes[0]
    per_pass = first_of(material_pass.chunks, Vec2ListChunk, W3D_CHUNK_STAGE_TEXCOORDS)
    if per_pass is not None and per_pass.vectors:
        return per_pass.vectors
    stages = material_pass.texture_stages
    if stages and stages[0].tex_coords:
        return stages[0].tex_coords
    return None


def _flatten_uvs(uvs: list[tuple[float, float]], vertex_count: int) -> list[float]:
    out: list[float] = []
    for i in range(vertex_count):
        out.extend(uvs[i] if i < len(uvs) else (0.0, 0.0))
    return out


def _mesh_texture_name(mesh: Mesh) -> str | None:
    passes = mesh.material_passes
    if not passes:
        return None
    stages = passes[0].texture_stages
    if not stages or not stages[0].texture_ids:
        return None
    return _texture_name(mesh, stages[0].texture_ids[0])


def _texture_name(mesh: Mesh, index: int) -> str | None:
    textures = mesh.textures
    if textures is None or not (0 <= index < len(textures.chunks)):
        return None
    entry = textures.chunks[index]
    return entry.name if isinstance(entry, Texture) else None


def _mesh_base_color(mesh: Mesh) -> tuple[float, float, float, float]:
    vertex_materials = mesh.vertex_materials
    if vertex_materials is not None:
        for chunk in vertex_materials.chunks:
            if isinstance(chunk, VertexMaterial):
                info = chunk.info
                if info is not None:
                    d = info.diffuse
                    return (d.r / 255, d.g / 255, d.b / 255, d.a / 255)
    return (1.0, 1.0, 1.0, 1.0)


def _mesh_translucent(mesh: Mesh) -> bool:
    shaders = mesh.shaders
    return bool(shaders) and shaders[0].dest_blend != 0


def _compute_bounds(render_meshes: list[RenderMesh]) -> tuple[Vec3, Vec3]:
    min_c = [float("inf"), float("inf"), float("inf")]
    max_c = [float("-inf"), float("-inf"), float("-inf")]
    for mesh in render_meshes:
        positions = mesh.positions
        for i in range(0, len(positions), 3):
            for axis in range(3):
                value = positions[i + axis]
                if value < min_c[axis]:
                    min_c[axis] = value
                if value > max_c[axis]:
                    max_c[axis] = value
    if min_c[0] == float("inf"):
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    return ((min_c[0], min_c[1], min_c[2]), (max_c[0], max_c[1], max_c[2]))
