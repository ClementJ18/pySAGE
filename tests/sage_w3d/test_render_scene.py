"""Data-free tests for `sage_w3d.render.scene`: synthetic `W3DFile`s built the way the rest of
`sage_w3d`'s own test suite builds chunks (see `test_mesh.py`/`test_hierarchy.py`/
`test_hlod.py`), exercising skin/rigid placement, HLOD LOD selection, hidden-mesh skipping, the
no-skeleton fallback, and `DirectoryResolver`'s stem/extension matching."""

import math

import pytest

from sage_w3d.binary import FixedString, Vec3ListChunk
from sage_w3d.chunks import (
    W3D_CHUNK_HLOD_LOD_ARRAY,
    W3D_CHUNK_VERTEX_NORMALS,
    W3D_CHUNK_VERTICES,
    Version,
)
from sage_w3d.hierarchy import Hierarchy, HierarchyHeader, HierarchyPivot, Pivots
from sage_w3d.hlod import HLOD, HLODArrayHeader, HLODHeader, HLODSubObject, HLODSubObjectArray
from sage_w3d.mesh import GEOMETRY_TYPE_HIDDEN, Mesh, MeshHeader, VertexInfluence, VertexInfluences
from sage_w3d.render.scene import DirectoryResolver, build_scene
from sage_w3d.w3d import W3DFile, write_w3d

_SIN45 = math.sqrt(2) / 2
_COS45 = math.sqrt(2) / 2


def _pivot(
    name: str,
    parent_id: int,
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
) -> HierarchyPivot:
    return HierarchyPivot(
        name=FixedString.from_value(name, 16),
        parent_id=parent_id,
        translation=translation,
        euler_angles=(0.0, 0.0, 0.0),
        rotation=rotation,
    )


def _hierarchy(name: str, pivots: list[HierarchyPivot]) -> Hierarchy:
    header = HierarchyHeader(
        flagged=False,
        version=Version(4, 1),
        name=FixedString.from_value(name, 16),
        num_pivots=len(pivots),
        center_pos=(0.0, 0.0, 0.0),
    )
    return Hierarchy(flagged=True, chunks=[header, Pivots(False, pivots)])


def _mesh_header(**overrides) -> MeshHeader:
    defaults = dict(
        flagged=False,
        version=Version(4, 2),
        attrs=0,
        mesh_name=FixedString.from_value("a_mesh", 16),
        container_name=FixedString.from_value("a_container", 16),
        face_count=0,
        vert_count=1,
        matl_count=0,
        damage_stage_count=0,
        sort_level=0,
        prelit_version=0,
        future_count=0,
        vert_channel_flags=0,
        face_channel_flags=0,
        min_corner=(0.0, 0.0, 0.0),
        max_corner=(1.0, 1.0, 1.0),
        sph_center=(0.0, 0.0, 0.0),
        sph_radius=1.0,
    )
    defaults.update(overrides)
    return MeshHeader(**defaults)


def _hlod_header(lod_count: int, hierarchy_name: str = "skel") -> HLODHeader:
    return HLODHeader(
        flagged=False,
        version=Version(1, 0),
        lod_count=lod_count,
        model_name=FixedString.from_value("m", 16),
        hierarchy_name=FixedString.from_value(hierarchy_name, 16),
    )


def _mesh(header: MeshHeader, vertices, normals, influences=None) -> Mesh:
    chunks = [
        header,
        Vec3ListChunk(W3D_CHUNK_VERTICES, False, vertices),
        Vec3ListChunk(W3D_CHUNK_VERTEX_NORMALS, False, normals),
    ]
    if influences is not None:
        chunks.append(VertexInfluences(False, influences))
    return Mesh(flagged=True, chunks=chunks)


class TestSkinTransform:
    def test_positions_and_normals_follow_the_bone(self):
        # root at the origin (identity); child translated (1, 0, 0) and rotated 90 degrees
        # about Z. A vertex/normal along local +X, fully weighted to the child, must rotate
        # *then* translate for the position (matching pivot_local_matrix's compose order) and
        # only rotate for the normal (no translation component).
        hierarchy = _hierarchy(
            "skel",
            [
                _pivot("root", -1),
                _pivot(
                    "child", 0, translation=(1.0, 0.0, 0.0), rotation=(0.0, 0.0, _SIN45, _COS45)
                ),
            ],
        )
        mesh = _mesh(
            _mesh_header(),
            vertices=[(1.0, 0.0, 0.0)],
            normals=[(1.0, 0.0, 0.0)],
            influences=[
                VertexInfluence(bone_idx=1, xtra_idx=0, bone_weight_raw=10000, xtra_weight_raw=0)
            ],
        )
        model = W3DFile(chunks=[hierarchy, mesh])

        scene = build_scene(model)

        assert len(scene.meshes) == 1
        rm = scene.meshes[0]
        assert rm.positions == pytest.approx([1.0, 1.0, 0.0])
        assert rm.normals == pytest.approx([0.0, 1.0, 0.0])
        assert scene.diagnostics == []

    def test_two_influences_are_weight_blended(self):
        # child_a stays at the origin; child_b sits at (2, 0, 0). A vertex split 50/50 between
        # them lands at their positional midpoint, (1, 0, 0).
        hierarchy = _hierarchy(
            "skel",
            [
                _pivot("root", -1),
                _pivot("child_a", 0),
                _pivot("child_b", 0, translation=(2.0, 0.0, 0.0)),
            ],
        )
        mesh = _mesh(
            _mesh_header(),
            vertices=[(0.0, 0.0, 0.0)],
            normals=[(0.0, 0.0, 1.0)],
            influences=[
                VertexInfluence(bone_idx=1, xtra_idx=2, bone_weight_raw=5000, xtra_weight_raw=5000)
            ],
        )
        model = W3DFile(chunks=[hierarchy, mesh])

        scene = build_scene(model)

        assert scene.meshes[0].positions == pytest.approx([1.0, 0.0, 0.0])


class TestRigidTransform:
    def test_hlod_sub_object_places_the_mesh_at_its_bone(self):
        hierarchy = _hierarchy(
            "skel", [_pivot("root", -1), _pivot("child", 0, translation=(5.0, 0.0, 0.0))]
        )
        header = _mesh_header(
            mesh_name=FixedString.from_value("MeshA", 16),
            container_name=FixedString.from_value("ContainerA", 16),
        )
        mesh = _mesh(header, vertices=[(0.0, 0.0, 0.0)], normals=[(0.0, 0.0, 1.0)])
        hlod = HLOD(
            flagged=True,
            chunks=[
                _hlod_header(1),
                HLODSubObjectArray(
                    chunk_type=W3D_CHUNK_HLOD_LOD_ARRAY,
                    flagged=True,
                    chunks=[
                        HLODArrayHeader(False, 1, 1000.0),
                        # Lowercase identifier: matching is case-insensitive.
                        HLODSubObject(False, 1, FixedString.from_value("containera.mesha", 32)),
                    ],
                ),
            ],
        )
        model = W3DFile(chunks=[hierarchy, mesh, hlod])

        scene = build_scene(model)

        assert len(scene.meshes) == 1
        assert scene.meshes[0].positions == pytest.approx([5.0, 0.0, 0.0])

    def test_unmatched_sub_object_is_skipped_without_a_diagnostic(self):
        # Every real HLOD carries at least a BOUNDINGBOX sub-object with no matching Mesh - not
        # an error, so it must not show up as a diagnostic on every single corpus file.
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        hlod = HLOD(
            flagged=True,
            chunks=[
                _hlod_header(1),
                HLODSubObjectArray(
                    chunk_type=W3D_CHUNK_HLOD_LOD_ARRAY,
                    flagged=True,
                    chunks=[
                        HLODArrayHeader(False, 1, 1000.0),
                        HLODSubObject(False, 0, FixedString.from_value("m.boundingbox", 32)),
                    ],
                ),
            ],
        )
        model = W3DFile(chunks=[hierarchy, hlod])

        scene = build_scene(model)

        assert scene.meshes == []
        assert scene.diagnostics == []


class TestHiddenMesh:
    def test_hidden_mesh_is_skipped(self):
        header = _mesh_header(attrs=GEOMETRY_TYPE_HIDDEN)
        mesh = _mesh(header, vertices=[(0.0, 0.0, 0.0)], normals=[(0.0, 0.0, 1.0)])
        model = W3DFile(chunks=[mesh])

        scene = build_scene(model)

        assert scene.meshes == []


class TestLodSelection:
    def _lod_array(self, max_screen_size: float, identifier: str) -> HLODSubObjectArray:
        return HLODSubObjectArray(
            chunk_type=W3D_CHUNK_HLOD_LOD_ARRAY,
            flagged=True,
            chunks=[
                HLODArrayHeader(False, 1, max_screen_size),
                HLODSubObject(False, 0, FixedString.from_value(identifier, 32)),
            ],
        )

    def _two_mesh_model(self) -> W3DFile:
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        low = _mesh(
            _mesh_header(
                mesh_name=FixedString.from_value("Low", 16),
                container_name=FixedString.from_value("M", 16),
            ),
            vertices=[(0.0, 0.0, 0.0)],
            normals=[(0.0, 0.0, 1.0)],
        )
        high = _mesh(
            _mesh_header(
                mesh_name=FixedString.from_value("High", 16),
                container_name=FixedString.from_value("M", 16),
            ),
            vertices=[(0.0, 0.0, 0.0)],
            normals=[(0.0, 0.0, 1.0)],
        )
        return hierarchy, low, high

    def test_only_the_highest_max_screen_size_array_is_used(self):
        hierarchy, low, high = self._two_mesh_model()
        hlod = HLOD(
            flagged=True,
            chunks=[
                _hlod_header(2),
                self._lod_array(100.0, "m.low"),
                self._lod_array(1000.0, "m.high"),
            ],
        )
        model = W3DFile(chunks=[hierarchy, low, high, hlod])

        scene = build_scene(model)

        assert [m.name for m in scene.meshes] == ["M.High"]

    def test_ties_favor_the_later_array(self):
        hierarchy, low, high = self._two_mesh_model()
        hlod = HLOD(
            flagged=True,
            chunks=[
                _hlod_header(2),
                self._lod_array(1000.0, "m.low"),
                self._lod_array(1000.0, "m.high"),
            ],
        )
        model = W3DFile(chunks=[hierarchy, low, high, hlod])

        scene = build_scene(model)

        assert [m.name for m in scene.meshes] == ["M.High"]


class TestNoSkeleton:
    def test_skin_mesh_is_left_untransformed_with_a_diagnostic(self):
        # An HLOD names a hierarchy but no resolver is given and no hierarchy is embedded -
        # the skeleton cannot resolve, so the geometry must pass through unchanged rather than
        # silently collapsing to nonsense, and the reason must be recorded.
        header = _mesh_header()
        mesh = _mesh(
            header,
            vertices=[(1.0, 2.0, 3.0)],
            normals=[(0.0, 0.0, 1.0)],
            influences=[
                VertexInfluence(bone_idx=0, xtra_idx=0, bone_weight_raw=10000, xtra_weight_raw=0)
            ],
        )
        hlod = HLOD(
            flagged=True,
            chunks=[
                _hlod_header(1, hierarchy_name="nope"),
                HLODSubObjectArray(
                    chunk_type=W3D_CHUNK_HLOD_LOD_ARRAY,
                    flagged=True,
                    chunks=[
                        HLODArrayHeader(False, 1, 1000.0),
                        HLODSubObject(False, 0, FixedString.from_value("a_container.a_mesh", 32)),
                    ],
                ),
            ],
        )
        model = W3DFile(chunks=[mesh, hlod])

        scene = build_scene(model)

        assert scene.meshes[0].positions == [1.0, 2.0, 3.0]
        assert scene.meshes[0].normals == [0.0, 0.0, 1.0]
        assert len(scene.diagnostics) == 1
        assert "no skeleton resolved" in scene.diagnostics[0]


class TestMeshSkin:
    def test_skin_mesh_weights_normalize_leniently(self):
        # Some exporters write raw weights on a 0-100 scale instead of the more common 0-10000
        # one; MeshSkin.bone_weights normalizes by each vertex's own weight sum either way, not
        # against a fixed assumed total.
        hierarchy = _hierarchy(
            "skel",
            [
                _pivot("root", -1),
                _pivot("child_a", 0),
                _pivot("child_b", 0, translation=(2.0, 0.0, 0.0)),
            ],
        )
        mesh = _mesh(
            _mesh_header(),
            vertices=[(0.0, 0.0, 0.0)],
            normals=[(0.0, 0.0, 1.0)],
            influences=[
                VertexInfluence(bone_idx=1, xtra_idx=2, bone_weight_raw=50, xtra_weight_raw=50)
            ],
        )
        model = W3DFile(chunks=[hierarchy, mesh])

        scene = build_scene(model)

        skin = scene.meshes[0].skin
        assert skin is not None
        assert skin.bone_indices == [1, 2]
        assert skin.bone_weights == pytest.approx([0.5, 0.5])
        assert skin.local_positions == pytest.approx([0.0, 0.0, 0.0])
        assert skin.local_normals == pytest.approx([0.0, 0.0, 1.0])
        assert scene.meshes[0].rigid_bone is None

    def test_rigid_mesh_gets_single_bone_pairs_and_rigid_bone(self):
        hierarchy = _hierarchy(
            "skel", [_pivot("root", -1), _pivot("child", 0, translation=(5.0, 0.0, 0.0))]
        )
        header = _mesh_header(
            mesh_name=FixedString.from_value("MeshA", 16),
            container_name=FixedString.from_value("ContainerA", 16),
        )
        mesh = _mesh(header, vertices=[(0.0, 0.0, 0.0)], normals=[(0.0, 0.0, 1.0)])
        hlod = HLOD(
            flagged=True,
            chunks=[
                _hlod_header(1),
                HLODSubObjectArray(
                    chunk_type=W3D_CHUNK_HLOD_LOD_ARRAY,
                    flagged=True,
                    chunks=[
                        HLODArrayHeader(False, 1, 1000.0),
                        HLODSubObject(False, 1, FixedString.from_value("containera.mesha", 32)),
                    ],
                ),
            ],
        )
        model = W3DFile(chunks=[hierarchy, mesh, hlod])

        scene = build_scene(model)

        assert scene.hierarchy is hierarchy
        rm = scene.meshes[0]
        assert rm.rigid_bone == 1
        assert rm.skin is not None
        assert rm.skin.bone_indices == [1, 0]
        assert rm.skin.bone_weights == pytest.approx([1.0, 0.0])

    def test_no_skeleton_resolved_leaves_skin_none(self):
        header = _mesh_header()
        mesh = _mesh(header, vertices=[(1.0, 2.0, 3.0)], normals=[(0.0, 0.0, 1.0)])
        model = W3DFile(chunks=[mesh])

        scene = build_scene(model)

        assert scene.meshes[0].skin is None
        assert scene.meshes[0].rigid_bone == 0
        assert scene.hierarchy is None

    def test_baked_rest_positions_unchanged_by_the_skin_refactor(self):
        # Re-run of TestSkinTransform's own case as a guard: emitting MeshSkin alongside the
        # baked rest-pose transform must not perturb RenderMesh.positions/normals, which
        # TestSkinTransform already pins bit-for-bit.
        hierarchy = _hierarchy(
            "skel",
            [
                _pivot("root", -1),
                _pivot(
                    "child", 0, translation=(1.0, 0.0, 0.0), rotation=(0.0, 0.0, _SIN45, _COS45)
                ),
            ],
        )
        mesh = _mesh(
            _mesh_header(),
            vertices=[(1.0, 0.0, 0.0)],
            normals=[(1.0, 0.0, 0.0)],
            influences=[
                VertexInfluence(bone_idx=1, xtra_idx=0, bone_weight_raw=10000, xtra_weight_raw=0)
            ],
        )
        model = W3DFile(chunks=[hierarchy, mesh])

        scene = build_scene(model)

        assert scene.meshes[0].positions == pytest.approx([1.0, 1.0, 0.0])
        assert scene.meshes[0].normals == pytest.approx([0.0, 1.0, 0.0])


class TestDirectoryResolver:
    def test_finds_a_dds_file_for_a_tga_request_case_insensitively(self, tmp_path):
        (tmp_path / "Texture.dds").write_bytes(b"dds-bytes")

        resolver = DirectoryResolver(tmp_path)

        assert resolver.find_texture("texture.tga") == b"dds-bytes"

    def test_finds_a_hierarchy_by_stem_case_insensitively(self, tmp_path):
        hierarchy = _hierarchy("Skel", [_pivot("root", -1)])
        (tmp_path / "Skel.w3d").write_bytes(write_w3d(W3DFile(chunks=[hierarchy])))

        resolver = DirectoryResolver(tmp_path)
        found = resolver.find_hierarchy("SKEL")

        assert found is not None
        assert found.hierarchy is not None
        assert found.hierarchy.pivots[0].name.value == "root"

    def test_missing_names_resolve_to_none(self, tmp_path):
        resolver = DirectoryResolver(tmp_path)
        assert resolver.find_texture("nope.tga") is None
        assert resolver.find_hierarchy("nope") is None
