"""Data-free tests for the losslessness guarantee (CONVENTIONS.md rule 4 / the plan's "self-check
degrade rule"): malformed input never raises past `parse_w3d` except for input that isn't a
chunk stream at all, and every degrade produces a diagnostic while still round-tripping."""

import pytest

from sage_w3d.binary import write_chunk
from sage_w3d.chunks import W3D_CHUNK_MESH, W3D_CHUNK_MESH_HEADER, UnknownChunk, W3DError
from sage_w3d.mesh import Mesh
from sage_w3d.w3d import parse_w3d, write_w3d


class TestTopLevelErrors:
    def test_empty_input_is_a_valid_empty_chunk_stream(self):
        # A handful of real BFME2/RotWK .w3d files are genuinely zero bytes - a degenerate but
        # valid empty chunk stream, not "not a chunk stream at all".
        w3d = parse_w3d(b"")
        assert w3d.chunks == []
        assert w3d.trailing == b""
        assert write_w3d(w3d) == b""

    def test_short_input_raises_w3derror(self):
        with pytest.raises(W3DError):
            parse_w3d(b"\x00\x01\x02")

    def test_first_chunk_overrunning_file_raises_w3derror(self):
        header = write_chunk(W3D_CHUNK_MESH, False, b"")[:8]
        # size field says 1000 bytes follow; the file has none.
        bad = header[:4] + (1000).to_bytes(4, "little") + b"short"
        with pytest.raises(W3DError):
            parse_w3d(bad)


class TestLeafDegrade:
    def test_truncated_mesh_header_degrades_to_unknown_with_diagnostic(self):
        # A MESH_HEADER payload of 10 bytes can never parse (it needs exactly 116) - the mesh
        # container must still round-trip byte-exact with the bad sub-chunk kept raw.
        bad_header_chunk = write_chunk(W3D_CHUNK_MESH_HEADER, False, b"\x00" * 10)
        data = write_chunk(W3D_CHUNK_MESH, True, bad_header_chunk)

        w3d = parse_w3d(data)
        assert write_w3d(w3d) == data
        assert len(w3d.diagnostics) == 1
        assert "malformed" in w3d.diagnostics[0].message

        mesh = w3d.meshes[0]
        assert mesh.header is None
        assert any(
            isinstance(c, UnknownChunk) and c.chunk_type == W3D_CHUNK_MESH_HEADER
            for c in mesh.chunks
        )

    def test_never_raises_on_malformed_but_not_truncated_top_level_stream(self):
        # A second top-level chunk whose header overruns the file is not the *first* chunk, so
        # it must not raise - it becomes trailing bytes instead.
        good = write_chunk(
            W3D_CHUNK_MESH, True, write_chunk(W3D_CHUNK_MESH_HEADER, False, b"\x00" * 10)
        )
        bad_header = write_chunk(W3D_CHUNK_MESH, False, b"")[:4] + (999).to_bytes(4, "little")
        data = good + bad_header

        w3d = parse_w3d(data)
        assert write_w3d(w3d) == data
        assert w3d.trailing == bad_header
        assert len(w3d.meshes) == 1


class TestContainerDegrade:
    def test_container_with_truncated_sub_chunk_header_degrades_whole_container(self):
        # The MESH payload here is a sub-chunk header that itself overruns the container's own
        # payload - this cannot be split into sub-chunks at all, so the whole MESH becomes raw.
        malformed_payload = write_chunk(W3D_CHUNK_MESH_HEADER, False, b"")[:4] + (500).to_bytes(
            4, "little"
        )
        data = write_chunk(W3D_CHUNK_MESH, True, malformed_payload)

        w3d = parse_w3d(data)
        assert write_w3d(w3d) == data
        assert len(w3d.chunks) == 1
        assert isinstance(w3d.chunks[0], UnknownChunk)
        assert w3d.chunks[0].chunk_type == W3D_CHUNK_MESH
        assert not isinstance(w3d.chunks[0], Mesh)
        assert len(w3d.diagnostics) == 1
        assert "malformed" in w3d.diagnostics[0].message
