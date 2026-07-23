"""Data-free round-trip tests for `sage_w3d.w3d`: a synthetic file mixing every top-level chunk
kind, byte-exact through `parse_w3d`/`write_w3d`, plus the `W3DFile` convenience properties and
trailing-bytes handling."""

from sage_w3d.binary import FixedString, write_chunk
from sage_w3d.chunks import W3D_CHUNK_HLOD_LOD_ARRAY, W3D_CHUNK_MORPH_ANIMATION, Rgba, Version
from sage_w3d.hierarchy import (
    Hierarchy,
    HierarchyHeader,
    parse_hierarchy_chunk,
    write_hierarchy_chunk,
)
from sage_w3d.hlod import HLOD, HLODArrayHeader, HLODHeader, HLODSubObjectArray, write_hlod_chunk
from sage_w3d.mesh import Mesh, MeshHeader, write_mesh_chunk
from sage_w3d.objects import CollisionBox, write_box_chunk
from sage_w3d.w3d import W3DFile, parse_w3d, write_w3d


def _mesh() -> Mesh:
    header = MeshHeader(
        flagged=False,
        version=Version(4, 2),
        attrs=0,
        mesh_name=FixedString.from_value("m", 16),
        container_name=FixedString.from_value("c", 16),
        face_count=0,
        vert_count=0,
        matl_count=0,
        damage_stage_count=0,
        sort_level=0,
        prelit_version=0,
        future_count=0,
        vert_channel_flags=0,
        face_channel_flags=1,
        min_corner=(0.0, 0.0, 0.0),
        max_corner=(0.0, 0.0, 0.0),
        sph_center=(0.0, 0.0, 0.0),
        sph_radius=0.0,
    )
    return Mesh(flagged=True, chunks=[header])


def _hierarchy() -> Hierarchy:
    header = HierarchyHeader(
        flagged=False,
        version=Version(4, 1),
        name=FixedString.from_value("h", 16),
        num_pivots=0,
        center_pos=(0, 0, 0),
    )
    return Hierarchy(flagged=True, chunks=[header])


def _hlod() -> HLOD:
    header = HLODHeader(
        flagged=False,
        version=Version(1, 0),
        lod_count=1,
        model_name=FixedString.from_value("c", 16),
        hierarchy_name=FixedString.from_value("h", 16),
    )
    lod_array = HLODSubObjectArray(W3D_CHUNK_HLOD_LOD_ARRAY, True, [HLODArrayHeader(False, 0, 0.0)])
    return HLOD(flagged=True, chunks=[header, lod_array])


def _box() -> CollisionBox:
    return CollisionBox(
        flagged=False,
        version=Version(1, 0),
        flags=0,
        name=FixedString.from_value("c.box", 32),
        color=Rgba(0, 0, 0, 0),
        center=(0.0, 0.0, 0.0),
        extend=(0.0, 0.0, 0.0),
    )


class TestFullFileRoundTrip:
    def test_mixed_top_level_chunks_byte_exact(self):
        raw = write_chunk(W3D_CHUNK_MORPH_ANIMATION, False, b"not modeled")
        data = (
            write_mesh_chunk(_mesh())
            + write_hierarchy_chunk(_hierarchy())
            + write_hlod_chunk(_hlod())
            + write_box_chunk(_box())
            + raw
        )

        w3d = parse_w3d(data)
        assert w3d.diagnostics == []
        assert write_w3d(w3d) == data

        assert len(w3d.meshes) == 1
        assert w3d.hierarchy is not None
        assert w3d.hlod is not None
        assert len(w3d.boxes) == 1
        assert w3d.animation is None
        assert w3d.compressed_animation is None
        assert w3d.dazzles == []

    def test_trailing_bytes_are_preserved_and_diagnosed(self):
        data = write_mesh_chunk(_mesh()) + b"\x01\x02\x03"
        w3d = parse_w3d(data)
        assert w3d.trailing == b"\x01\x02\x03"
        assert len(w3d.diagnostics) == 1
        assert "trailing" in w3d.diagnostics[0].message
        assert write_w3d(w3d) == data

    def test_empty_file_round_trips(self):
        w3d = W3DFile()
        assert write_w3d(w3d) == b""


def test_parse_hierarchy_chunk_is_reachable_directly():
    header = HierarchyHeader(
        flagged=False,
        version=Version(4, 1),
        name=FixedString.from_value("h", 16),
        num_pivots=0,
        center_pos=(0, 0, 0),
    )
    hierarchy = Hierarchy(flagged=False, chunks=[header])
    data = write_hierarchy_chunk(hierarchy)
    diagnostics: list = []
    parsed = parse_hierarchy_chunk(data[8:], False, 0, diagnostics)
    assert parsed == hierarchy
