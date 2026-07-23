"""CLI-level tests for `sage-w3d`, driven through `main([...])` with synthetic files in
`tmp_path` (style: `tests/sage_asset/test_cli.py`)."""

import json
from pathlib import Path

from sage_w3d.__main__ import main
from sage_w3d.binary import FixedString, write_chunk
from sage_w3d.chunks import W3D_CHUNK_MORPH_ANIMATION, Version
from sage_w3d.hierarchy import Hierarchy, HierarchyHeader, write_hierarchy_chunk
from sage_w3d.mesh import Mesh, MeshHeader, write_mesh_chunk


def _sample_mesh() -> Mesh:
    header = MeshHeader(
        flagged=False,
        version=Version(4, 2),
        attrs=0,
        mesh_name=FixedString.from_value("a_mesh", 16),
        container_name=FixedString.from_value("a_container", 16),
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


def _sample_hierarchy() -> Hierarchy:
    header = HierarchyHeader(
        flagged=False,
        version=Version(4, 1),
        name=FixedString.from_value("a_skeleton", 16),
        num_pivots=0,
        center_pos=(0.0, 0.0, 0.0),
    )
    return Hierarchy(flagged=True, chunks=[header])


def _write_sample(path: Path) -> None:
    data = write_mesh_chunk(_sample_mesh()) + write_hierarchy_chunk(_sample_hierarchy())
    path.write_bytes(data)


class TestInfo:
    def test_reports_mesh_and_hierarchy_summaries(self, tmp_path, capsys):
        path = tmp_path / "model.w3d"
        _write_sample(path)

        assert main(["info", str(path)]) == 0

        out = capsys.readouterr().out
        assert "MESH a_container.a_mesh" in out
        assert "HIERARCHY a_skeleton" in out
        assert "diagnostics: 0" in out


class TestTree:
    def test_shows_container_and_size_tags(self, tmp_path, capsys):
        path = tmp_path / "model.w3d"
        _write_sample(path)

        assert main(["tree", str(path)]) == 0

        out = capsys.readouterr().out
        assert "MESH size=" in out
        assert "[container]" in out
        assert "MESH_HEADER size=116" in out

    def test_marks_unmodeled_chunks_raw(self, tmp_path, capsys):
        path = tmp_path / "model.w3d"
        path.write_bytes(write_chunk(W3D_CHUNK_MORPH_ANIMATION, False, b"xyz"))

        assert main(["tree", str(path)]) == 0

        out = capsys.readouterr().out
        assert "MORPH_ANIMATION" in out
        assert "[raw]" in out


class TestJson:
    def test_writes_parseable_json_with_expected_shape(self, tmp_path, capsys):
        path = tmp_path / "model.w3d"
        _write_sample(path)

        assert main(["json", str(path), "--compact"]) == 0

        out = capsys.readouterr().out
        document = json.loads(out)
        assert len(document["chunks"]) == 2
        assert document["diagnostics"] == []

    def test_out_option_writes_to_file(self, tmp_path, capsys):
        path = tmp_path / "model.w3d"
        _write_sample(path)
        out_path = tmp_path / "model.json"

        assert main(["json", str(path), "--out", str(out_path)]) == 0

        document = json.loads(out_path.read_text(encoding="utf-8"))
        assert len(document["chunks"]) == 2


class TestCheck:
    def test_clean_file_passes(self, tmp_path, capsys):
        path = tmp_path / "model.w3d"
        _write_sample(path)

        assert main(["check", str(path)]) == 0

        out = capsys.readouterr().out
        assert "1 file(s), 0 failure(s)" in out

    def test_directory_is_scanned_recursively(self, tmp_path, capsys):
        sub = tmp_path / "nested"
        sub.mkdir()
        _write_sample(tmp_path / "a.w3d")
        _write_sample(sub / "b.W3D")
        (tmp_path / "not_a_w3d.txt").write_bytes(b"ignore me")

        assert main(["check", str(tmp_path)]) == 0

        out = capsys.readouterr().out
        assert "2 file(s), 0 failure(s)" in out

    def test_not_a_chunk_stream_fails(self, tmp_path, capsys):
        # Fewer than 8 bytes can't even hold one chunk header - parse_w3d raises W3DError,
        # which `check` must catch and report as a failure rather than crash on.
        path = tmp_path / "model.w3d"
        path.write_bytes(b"\x00\x01\x02")

        assert main(["check", str(path)]) == 1

        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "1 failure(s)" in out

    def test_empty_directory_reports_zero_files(self, tmp_path, capsys):
        assert main(["check", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "no .w3d files found" in out
