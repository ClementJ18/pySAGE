"""CLI-level tests for `sage-asset`'s staleness check (`check --art`), dangling-reference
warning (`check`, always on), and combine shadowing report (`combine [--show-overrides]`) -
driven through `main([...])` the way sage_ini's CLI tests do, rather than via subprocess."""

import os
from pathlib import Path

from sage_asset.__main__ import main
from sage_asset.assetdat import (
    Asset,
    AssetDat,
    FileEntry,
    ReferenceRecord,
    write_asset_dat_to_path,
)
from sage_asset.builder import build_asset_dat


def _build_tiny_art_tree(art_dir: Path) -> None:
    textures_dir = art_dir / "compiledtextures"
    w3d_dir = art_dir / "w3d"
    textures_dir.mkdir(parents=True)
    w3d_dir.mkdir(parents=True)
    (textures_dir / "a_tex.tga").write_bytes(b"tga-bytes")
    # check --art only needs each file's name and mtime (see collect_art_index), never its
    # chunk structure, so a content-free w3d is fine here.
    (w3d_dir / "a_model.w3d").write_bytes(b"\x00" * 8)


def _bump_mtime(path: Path) -> None:
    stat = path.stat()
    os.utime(path, (stat.st_atime + 10, stat.st_mtime + 10))


class TestCheckArt:
    def test_clean_tree_exits_zero(self, tmp_path, capsys):
        art_dir = tmp_path / "art"
        _build_tiny_art_tree(art_dir)
        dat_path = tmp_path / "asset.dat"
        write_asset_dat_to_path(build_asset_dat(art_dir), dat_path)

        assert main(["check", str(dat_path), "--art", str(art_dir)]) == 0

        out = capsys.readouterr().out
        assert "missing: 0" in out
        assert "stale: 0" in out
        assert "orphaned: 0" in out

    def test_stale_texture_exits_one(self, tmp_path, capsys):
        art_dir = tmp_path / "art"
        _build_tiny_art_tree(art_dir)
        dat_path = tmp_path / "asset.dat"
        write_asset_dat_to_path(build_asset_dat(art_dir), dat_path)

        _bump_mtime(art_dir / "compiledtextures" / "a_tex.tga")

        assert main(["check", str(dat_path), "--art", str(art_dir)]) == 1

        out = capsys.readouterr().out
        assert "stale: 1" in out
        assert "a_tex.tga" in out
        assert "missing: 0" in out

    def test_new_texture_reports_missing_and_exits_one(self, tmp_path, capsys):
        art_dir = tmp_path / "art"
        _build_tiny_art_tree(art_dir)
        dat_path = tmp_path / "asset.dat"
        write_asset_dat_to_path(build_asset_dat(art_dir), dat_path)

        (art_dir / "compiledtextures" / "b_tex.tga").write_bytes(b"new-bytes")

        assert main(["check", str(dat_path), "--art", str(art_dir)]) == 1

        out = capsys.readouterr().out
        assert "missing: 1" in out
        assert "b_tex.tga" in out

    def test_deleted_source_reports_orphaned_and_stays_exit_zero(self, tmp_path, capsys):
        art_dir = tmp_path / "art"
        _build_tiny_art_tree(art_dir)
        dat_path = tmp_path / "asset.dat"
        write_asset_dat_to_path(build_asset_dat(art_dir), dat_path)

        (art_dir / "w3d" / "a_model.w3d").unlink()

        assert main(["check", str(dat_path), "--art", str(art_dir)]) == 0

        out = capsys.readouterr().out
        assert "orphaned: 1" in out
        assert "a_model.w3d" in out
        assert "missing: 0" in out
        assert "stale: 0" in out


class TestDanglingReferences:
    def test_warns_when_a_reference_names_nothing_resolvable(self, tmp_path, capsys):
        ad = AssetDat(
            version=0x102,
            files=[
                FileEntry(
                    name="a.w3d",
                    file_time=1,
                    assets=[Asset(name="A", type="MESH", offset=0, size=0)],
                )
            ],
            references=[
                ReferenceRecord(file_name="a.w3d", asset_name="A", references=["ghost.tga"])
            ],
        )
        dat_path = tmp_path / "asset.dat"
        write_asset_dat_to_path(ad, dat_path)

        assert main(["check", str(dat_path)]) == 0  # a warning, not a failure

        out = capsys.readouterr().out
        assert "dangling reference" in out
        assert "ghost.tga" in out

    def test_no_warning_when_every_reference_resolves(self, tmp_path, capsys):
        ad = AssetDat(
            version=0x102,
            files=[
                FileEntry(
                    name="a.w3d",
                    file_time=1,
                    assets=[Asset(name="A", type="MESH", offset=0, size=0)],
                ),
                FileEntry(
                    name="a.tga",
                    file_time=1,
                    assets=[Asset(name="a.tga", type="TEX", offset=0, size=0)],
                ),
            ],
            references=[ReferenceRecord(file_name="a.w3d", asset_name="A", references=["a.tga"])],
        )
        dat_path = tmp_path / "asset.dat"
        write_asset_dat_to_path(ad, dat_path)

        assert main(["check", str(dat_path)]) == 0

        out = capsys.readouterr().out
        assert "dangling" not in out


def _write_base_and_overlay(tmp_path: Path) -> tuple[Path, Path]:
    """A base with three files and an overlay that shadows two of them - one with an
    identical entry (pure re-ship), one with a changed one - plus one unique file each."""
    base = AssetDat(
        version=0x102,
        files=[
            FileEntry(
                name="unique_base.tga",
                file_time=1,
                assets=[Asset(name="unique_base.tga", type="TEX", offset=0, size=0)],
            ),
            FileEntry(
                name="same.tga",
                file_time=5,
                assets=[Asset(name="same.tga", type="TEX", offset=0, size=0)],
            ),
            FileEntry(name="changed.tga", file_time=1, assets=[]),
        ],
    )
    overlay = AssetDat(
        version=0x102,
        files=[
            FileEntry(
                name="same.tga",
                file_time=5,
                assets=[Asset(name="same.tga", type="TEX", offset=0, size=0)],
            ),
            FileEntry(name="changed.tga", file_time=2, assets=[]),
            FileEntry(
                name="unique_overlay.tga",
                file_time=1,
                assets=[Asset(name="unique_overlay.tga", type="TEX", offset=0, size=0)],
            ),
        ],
    )
    base_path = tmp_path / "base.dat"
    overlay_path = tmp_path / "overlay.dat"
    write_asset_dat_to_path(base, base_path)
    write_asset_dat_to_path(overlay, overlay_path)
    return base_path, overlay_path


class TestCombineShadowing:
    def test_reports_identical_and_changed_shadow_counts(self, tmp_path, capsys):
        base_path, overlay_path = _write_base_and_overlay(tmp_path)
        out_path = tmp_path / "combined.dat"

        exit_code = main(["combine", str(base_path), str(overlay_path), "-o", str(out_path)])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "2 duplicate file names" in out
        assert "shadowed: 2 entries (1 identical, 1 changed)" in out
        # no per-name listing without --show-overrides.
        assert "[identical]" not in out
        assert "[changed]" not in out

    def test_show_overrides_lists_each_shadowed_name_with_a_tag(self, tmp_path, capsys):
        base_path, overlay_path = _write_base_and_overlay(tmp_path)
        out_path = tmp_path / "combined.dat"

        main(
            ["combine", str(base_path), str(overlay_path), "-o", str(out_path), "--show-overrides"]
        )

        out = capsys.readouterr().out
        assert "same.tga  [identical]" in out
        assert "changed.tga  [changed]" in out

    def test_no_shadowing_line_when_there_are_no_duplicates(self, tmp_path, capsys):
        base = AssetDat(version=0x102, files=[FileEntry(name="a.tga", file_time=1, assets=[])])
        overlay = AssetDat(version=0x102, files=[FileEntry(name="b.tga", file_time=1, assets=[])])
        base_path = tmp_path / "base.dat"
        overlay_path = tmp_path / "overlay.dat"
        write_asset_dat_to_path(base, base_path)
        write_asset_dat_to_path(overlay, overlay_path)
        out_path = tmp_path / "combined.dat"

        main(["combine", str(base_path), str(overlay_path), "-o", str(out_path)])

        out = capsys.readouterr().out
        assert "0 duplicate file names" in out
        assert "shadowed" not in out
