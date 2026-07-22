"""Data-free tests for `sage_asset.builder`. A tiny W3D file (mesh/hierarchy/box/HLOD chunks)
and a small compiledtextures tree are synthesized under `tmp_path` with `struct`, independent
of the parser under test, so a scan of them exercises the real chunk-walking and cross-
reference logic rather than just round-tripping the builder's own output."""

import os
import struct
from pathlib import Path

import pytest

from sage_asset.assetdat import Asset, parse_asset_dat, parse_asset_dat_from_path, write_asset_dat
from sage_asset.builder import build_asset_dat, collect_art_index, w3d_references

_FILETIME_EPOCH_DIFF = 116_444_736_000_000_000


def _chunk(ctype: int, payload: bytes, has_sub_chunks: bool = False) -> bytes:
    size_raw = len(payload) | (0x80000000 if has_sub_chunks else 0)
    return struct.pack("<II", ctype, size_raw) + payload


def _padded(name: str, length: int) -> bytes:
    raw = name.encode("latin-1")
    return raw + b"\x00" * (length - len(raw))


def _mesh_chunk(container: str, mesh: str, textures: list[str]) -> bytes:
    header_payload = b"\x00" * 8 + _padded(mesh, 16) + _padded(container, 16)
    header_sub = _chunk(0x1F, header_payload)
    texture_subs = b"".join(_chunk(0x32, tex.encode("latin-1") + b"\x00") for tex in textures)
    return _chunk(0x00000000, header_sub + texture_subs, has_sub_chunks=True)


def _hierarchy_def_chunk(name: str) -> bytes:
    inner_payload = b"\x00" * 4 + _padded(name, 16)
    inner = _chunk(0x0101, inner_payload)
    return _chunk(0x00000100, inner, has_sub_chunks=True)


def _hlod_chunk(name: str, hier_ref: str) -> bytes:
    inner_payload = b"\x00" * 8 + _padded(name, 16) + _padded(hier_ref, 16)
    inner = _chunk(0x0701, inner_payload)
    return _chunk(0x00000700, inner, has_sub_chunks=True)


def _box_chunk(name: str) -> bytes:
    payload = b"\x00" * 8 + _padded(name, 32)
    return _chunk(0x00000740, payload)


def _expected_filetime(path: Path) -> int:
    return os.stat(path).st_mtime_ns // 100 + _FILETIME_EPOCH_DIFF


def _build_art_tree(tmp_path: Path) -> Path:
    art_dir = tmp_path / "art"
    textures_dir = art_dir / "compiledtextures"
    w3d_dir = art_dir / "w3d"
    textures_dir.mkdir(parents=True)
    w3d_dir.mkdir(parents=True)

    # dds beats tga (extension priority) and the entry is named .tga regardless of which
    # extension actually won.
    (textures_dir / "mytex.dds").write_bytes(b"dds-bytes")
    (textures_dir / "mytex.tga").write_bytes(b"tga-bytes")
    (textures_dir / "ignored.txt").write_bytes(b"not a texture")

    # A mesh (referencing a known and an unknown texture), a hierarchy def, a box, and an
    # HLOD - in that chunk order, so the HLOD's refs pick up the mesh's and box's names plus
    # the hierarchy def already seen.
    w3d_data = (
        _mesh_chunk("MYCONTAINER", "MYMESH", ["MYTEX.TGA", "MISSING.TGA"])
        + _hierarchy_def_chunk("MYHIER")
        + _box_chunk("MYBOX")
        + _hlod_chunk("MYHLOD", "IGNOREME")
    )
    (w3d_dir / "model.w3d").write_bytes(w3d_data)

    return art_dir


def test_build_asset_dat_from_synthetic_art_tree(tmp_path):
    art_dir = _build_art_tree(tmp_path)
    w3d_path = art_dir / "w3d" / "model.w3d"

    ad = build_asset_dat(art_dir)

    assert ad.version == 0x102
    # entry sort order: "model.w3d" < "mytex.tga".
    assert [f.name for f in ad.files] == ["model.w3d", "mytex.tga"]

    w3d_entry, tex_entry = ad.files

    # offsets/sizes tile the synthetic w3d file exactly.
    assert [(a.name, a.type, a.offset, a.size) for a in w3d_entry.assets] == [
        ("MYCONTAINER.MYMESH", "MESH", 0, 94),
        ("H*MYHIER", "HIER", 94, 36),
        ("MYBOX", "BOX", 130, 48),
        ("MYHLOD", "HLOD", 178, 56),
    ]
    assert sum(a.size for a in w3d_entry.assets) == w3d_path.stat().st_size

    # FILETIME matches each source file's actual mtime.
    assert w3d_entry.file_time == _expected_filetime(w3d_path)
    assert tex_entry.file_time == _expected_filetime(art_dir / "compiledtextures" / "mytex.dds")

    # the texture entry is a single TEX sub-asset, named .tga regardless of the winning file.
    assert tex_entry.assets == [Asset(name="mytex.tga", type="TEX", offset=0, size=0)]

    # mesh cross-refs are limited to textures actually present in compiledtextures/.
    assert ad.references_for("model.w3d", "MYCONTAINER.MYMESH") == [["mytex.tga"]]

    # HLOD refs: sub-object names seen so far (mesh, then box) plus the file's own hierarchy.
    assert ad.references_for("model.w3d", "MYHLOD") == [["mycontainer.mymesh", "mybox", "h*myhier"]]

    # full write -> parse round trip.
    assert parse_asset_dat(write_asset_dat(ad)) == ad


def test_collect_art_index_matches_builder_entry_names_without_parsing_chunks(tmp_path):
    art_dir = _build_art_tree(tmp_path)
    dds_path = art_dir / "compiledtextures" / "mytex.dds"
    w3d_path = art_dir / "w3d" / "model.w3d"

    index = collect_art_index(art_dir)
    ad = build_asset_dat(art_dir)

    # same entry names the full build produces, from a scan that never touches w3d content.
    assert set(index) == {f.name for f in ad.files}

    # dds wins the texture priority, same as the builder, and the filetime is the winner's.
    path, filetime = index["mytex.tga"]
    assert path == dds_path
    assert filetime == _expected_filetime(dds_path)

    path, filetime = index["model.w3d"]
    assert path == w3d_path
    assert filetime == _expected_filetime(w3d_path)


def test_collect_art_index_empty_for_a_tree_with_no_art(tmp_path):
    art_dir = tmp_path / "empty_art"
    art_dir.mkdir()

    assert collect_art_index(art_dir) == {}


class TestW3dReferences:
    """`w3d_references` reads a single file's outward edges without a full art tree."""

    def test_collects_deduped_mesh_textures_and_external_hierarchy(self):
        data = _mesh_chunk(
            "MYCONTAINER", "MYMESH", ["MYTEX.TGA", "MYTEX.TGA", "OTHER.DDS"]
        ) + _hlod_chunk("MYHLOD", "MYSKELETON")

        refs = w3d_references(data)

        assert refs.textures == ["MYTEX.TGA", "OTHER.DDS"]  # deduped, original case, file order
        assert refs.hierarchies == ["myskeleton"]

    def test_own_hierarchy_def_needs_no_external_skeleton(self):
        # The file carries its own HIER chunk, so its HLOD's hier_ref (even naming a different,
        # real file) is not treated as an external skeleton.
        data = _hierarchy_def_chunk("MYHIER") + _hlod_chunk("MYHIER", "IGNOREME")

        assert w3d_references(data).hierarchies == []

    def test_hlod_matching_its_own_name_is_not_external(self):
        # No HIER chunk, but the HLOD's hier_ref equals its own name (case-insensitively) - a
        # self-contained model, not a skinned mesh pointing at a separate skeleton file.
        data = _hlod_chunk("SelfContained", "selfcontained")

        assert w3d_references(data).hierarchies == []

    def test_no_mesh_or_hlod_yields_nothing(self):
        assert w3d_references(_hierarchy_def_chunk("MYHIER")) == ([], [])


@pytest.mark.full
def test_build_matches_asset_cache_builder_output():
    """Compares a build of tests/sage_asset/fixtures/art/ against the real
    AssetCacheBuilder.exe's output for that same tree (fixtures/assetdats/acb_built.dat), on
    every field except `file_time` - re-copying the fixtures resets mtimes, so FILETIME is not
    reproducible here and is exercised by the synthetic test above instead. AssetCacheBuilder
    sorts each HLOD's references alphabetically; the ported builder keeps chunk order, so
    reference lists are compared as sorted lists rather than exact sequences."""
    art_dir = Path(__file__).parent / "fixtures" / "art"
    acb_path = Path(__file__).parent / "fixtures" / "assetdats" / "acb_built.dat"
    if not art_dir.is_dir() or not acb_path.is_file():
        pytest.skip("fixtures/art/ or fixtures/assetdats/acb_built.dat not present")

    ours = build_asset_dat(art_dir)
    acb = parse_asset_dat_from_path(acb_path)

    assert sorted(f.name for f in ours.files) == sorted(f.name for f in acb.files)

    ours_by_name = {f.name: f for f in ours.files}
    for acb_entry in acb.files:
        our_entry = ours_by_name[acb_entry.name]
        assert [(a.name, a.type, a.offset, a.size) for a in our_entry.assets] == [
            (a.name, a.type, a.offset, a.size) for a in acb_entry.assets
        ]

    ours_refs = {(r.file_name, r.asset_name): sorted(r.references) for r in ours.references}
    acb_refs = {(r.file_name, r.asset_name): sorted(r.references) for r in acb.references}
    assert ours_refs == acb_refs
