"""Data-free round-trip tests for `sage_w3d.mesh`: build a synthetic `Mesh` (and its sub-chunks)
in memory, write it, parse it back, and check the result is byte-exact and re-parses to an equal
model. Also covers duplicate/oddly-ordered sub-chunks - the "ordered children" architecture's
whole reason for existing."""

from sage_w3d.binary import (
    FixedString,
    NulString,
    StringChunk,
    UInt32ListChunk,
    Vec3ListChunk,
    first_of,
)
from sage_w3d.chunks import (
    W3D_CHUNK_MESH_USER_TEXT,
    W3D_CHUNK_VERTICES,
    Rgba,
    UnknownChunk,
    Version,
)
from sage_w3d.mesh import (
    MaterialInfo,
    MaterialPass,
    Mesh,
    MeshHeader,
    Shader,
    Shaders,
    Triangle,
    Triangles,
    VertexInfluence,
    VertexInfluences,
    VertexMaterial,
    VertexMaterialInfo,
    VertexMaterials,
    parse_mesh_chunk,
    write_mesh_chunk,
)


def _mesh_header(**overrides) -> MeshHeader:
    defaults = dict(
        flagged=False,
        version=Version(major=4, minor=2),
        attrs=0,
        mesh_name=FixedString.from_value("a_mesh", 16),
        container_name=FixedString.from_value("a_container", 16),
        face_count=1,
        vert_count=3,
        matl_count=1,
        damage_stage_count=0,
        sort_level=0,
        prelit_version=0,
        future_count=0,
        vert_channel_flags=0,
        face_channel_flags=1,
        min_corner=(0.0, 0.0, 0.0),
        max_corner=(1.0, 1.0, 1.0),
        sph_center=(0.5, 0.5, 0.5),
        sph_radius=1.0,
    )
    defaults.update(overrides)
    return MeshHeader(**defaults)


def _round_trip(mesh: Mesh) -> Mesh:
    data = write_mesh_chunk(mesh)
    diagnostics: list = []
    parsed = parse_mesh_chunk(data[8:], mesh.flagged, 0, diagnostics)
    assert diagnostics == []
    assert isinstance(parsed, Mesh)
    assert write_mesh_chunk(parsed) == data
    return parsed


class TestMeshRoundTrip:
    def test_minimal_mesh(self):
        mesh = Mesh(
            flagged=True,
            chunks=[
                _mesh_header(),
                Vec3ListChunk(
                    W3D_CHUNK_VERTICES, False, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
                ),
                Triangles(False, [Triangle((0, 1, 2), 13, (0.0, 0.0, 1.0), 0.0)]),
            ],
        )
        parsed = _round_trip(mesh)
        assert parsed.name == "a_mesh"
        assert parsed.container_name == "a_container"
        assert parsed.vertices == mesh.vertices
        assert parsed.triangles == mesh.triangles

    def test_user_text_and_vertex_influences(self):
        mesh = Mesh(
            flagged=True,
            chunks=[
                _mesh_header(),
                StringChunk(W3D_CHUNK_MESH_USER_TEXT, False, NulString.from_value("hello")),
                VertexInfluences(False, [VertexInfluence(0, 1, 10000, 0)]),
            ],
        )
        parsed = _round_trip(mesh)
        assert parsed.user_text == "hello"
        assert parsed.vertex_influences == [VertexInfluence(0, 1, 10000, 0)]
        assert parsed.vertex_influences[0].bone_weight == 100.0

    def test_duplicate_vertices_chunks_preserved_in_order(self):
        # Two VERTICES chunks back to back is unusual but the ordered-children model must not
        # collapse or reorder them - only `.vertices` (first_of) picks the first.
        v1 = Vec3ListChunk(W3D_CHUNK_VERTICES, False, [(1.0, 0.0, 0.0)])
        v2 = Vec3ListChunk(W3D_CHUNK_VERTICES, False, [(2.0, 0.0, 0.0)])
        mesh = Mesh(flagged=True, chunks=[_mesh_header(), v1, v2])
        parsed = _round_trip(mesh)
        vec3_chunks = [c for c in parsed.chunks if isinstance(c, Vec3ListChunk)]
        assert len(vec3_chunks) == 2
        assert vec3_chunks[0].vectors == [(1.0, 0.0, 0.0)]
        assert vec3_chunks[1].vectors == [(2.0, 0.0, 0.0)]

    def test_material_passes_and_vertex_materials(self):
        vm = VertexMaterial(
            flagged=True,
            chunks=[
                StringChunk(0x2C, False, NulString.from_value("mat")),
                VertexMaterialInfo(
                    False,
                    0,
                    Rgba(1, 2, 3, 4),
                    Rgba(5, 6, 7, 8),
                    Rgba(9, 10, 11, 12),
                    Rgba(13, 14, 15, 16),
                    0.0,
                    1.0,
                    0.0,
                ),
            ],
        )
        mesh = Mesh(
            flagged=True,
            chunks=[
                _mesh_header(),
                MaterialInfo(False, 1, 1, 0, 0),
                VertexMaterials(False, [vm]),
                MaterialPass(False, [UInt32ListChunk(0x39, False, [0])]),
            ],
        )
        parsed = _round_trip(mesh)
        assert parsed.vertex_materials is not None
        assert parsed.vertex_materials.chunks[0].name == "mat"
        assert len(parsed.material_passes) == 1
        assert parsed.material_passes[0].vertex_material_ids == [0]

    def test_shaders_list(self):
        shader = Shader(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        mesh = Mesh(flagged=True, chunks=[_mesh_header(), Shaders(False, [shader, shader])])
        parsed = _round_trip(mesh)
        assert parsed.shaders == [shader, shader]

    def test_unknown_chunk_inside_mesh_round_trips(self):
        unknown = UnknownChunk(0xDEAD, False, b"whatever bytes")
        mesh = Mesh(flagged=True, chunks=[_mesh_header(), unknown])
        parsed = _round_trip(mesh)
        assert first_of(parsed.chunks, UnknownChunk) == unknown
