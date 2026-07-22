"""The object asset walker (sage_mods.edain.assets): every model, animation clip and texture a
set of ini objects reference, deduplicated, sized against a synthetic art tree.

Fast tests build a tiny synthetic game (ini fixture, plain objects - no faction needed) plus a
tiny synthetic art tree (w3d chunk bytes, in the style of tests/sage_asset/test_builder.py's
local `_chunk`/`_mesh_chunk`/`_hlod_chunk` helpers, copied rather than imported so this module
stays independent of that one)."""

import csv
import io
import struct
from pathlib import Path

import pytest

from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_mods.edain.assets import ArtIndex, object_assets, write_csv

# A citadel whose draw shows the same model in two model-condition states (dedup), binds an
# animation clip, and carries a UI icon via a MappedImage; a soldier with a RandomTexture swap and
# a missing texture; an FXParticleSystem naming a particle texture. No PlayerTemplate: the walker
# is handed objects directly, so nothing here needs a faction.
FIXTURE = """
Object TestCitadel
    KindOf = STRUCTURE
    SelectPortrait = TestButtonIcon
    Draw = W3DModelDraw ModuleTag_Draw
        DefaultModelConditionState
            Model = TestKeep_SKN
        End
        ModelConditionState = DAMAGED
            Model = TestKeep_SKN
        End
        AnimationState = IDLE
            Animation = TestKeep_IDLA
                AnimationName = TestKeep_SKL.TestKeep_IDLA
            End
        End
    End
End
MappedImage TestButtonIcon
    Texture = testui.tga
End

Object TestSoldier
    KindOf = INFANTRY
    Draw = W3DScriptedModelDraw ModuleTag_Draw
        DefaultModelConditionState
            Model = TestSoldier_SKN
        End
        RandomTexture = TestSoldierAlt.tga
    End
End

FXParticleSystem FXPS_Test
    System
        ParticleName = testfx.tga
    End
End
"""


def _load(text: str) -> Game:
    game = Game()
    result = parse(text, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


@pytest.fixture
def game() -> Game:
    return _load(FIXTURE)


# Synthetic art tree (w3d chunk bytes), independent of tests/sage_asset/test_builder.py.


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


# Distinctly-sized dummy files so a resolved AssetRecord's size is unambiguous.
_TESTKEEP_SKN_W3D = _mesh_chunk("TESTKEEP_SKN", "MESH0", ["TESTKEEP.TGA"]) + _hlod_chunk(
    "TESTKEEP_SKN", "TESTKEEP_SKL"
)
_TESTKEEP_SKL_W3D = _hierarchy_def_chunk("TESTKEEP_SKL")
_TESTKEEP_IDLA_W3D = b"IDLA-ANIMATION-DUMMY-BYTES-PADDED-OUT"
_TESTSOLDIER_SKN_W3D = _mesh_chunk("TESTSOLDIER_SKN", "MESH0", [])
_TESTKEEP_TGA = b"TESTKEEP-TEXTURE-BYTES"
_TESTFX_TGA = b"TESTFX-PARTICLE-BYTES"
_TESTUI_DDS = b"TESTUI-DDS-WINNING-BYTES"
_TESTUI_TGA = b"tga-loses"


def _build_art_tree(tmp_path) -> Path:
    art_dir = tmp_path / "art"
    art_dir.mkdir()
    (art_dir / "testkeep_skn.w3d").write_bytes(_TESTKEEP_SKN_W3D)
    (art_dir / "testkeep_skl.w3d").write_bytes(_TESTKEEP_SKL_W3D)
    (art_dir / "testkeep_idla.w3d").write_bytes(_TESTKEEP_IDLA_W3D)
    (art_dir / "testsoldier_skn.w3d").write_bytes(_TESTSOLDIER_SKN_W3D)
    (art_dir / "testkeep.tga").write_bytes(_TESTKEEP_TGA)
    (art_dir / "testfx.tga").write_bytes(_TESTFX_TGA)
    (art_dir / "testui.dds").write_bytes(_TESTUI_DDS)
    (art_dir / "testui.tga").write_bytes(_TESTUI_TGA)
    return art_dir


@pytest.fixture
def art_dir(tmp_path):
    return _build_art_tree(tmp_path)


@pytest.fixture
def art(art_dir):
    return ArtIndex.build([art_dir])


@pytest.fixture
def all_objects(game):
    """Every object/particle-system/mapped-image in the fixture, the natural set to hand the
    walker - the tests scope tighter where they need to."""
    return [
        game.objects["TestCitadel"],
        game.objects["TestSoldier"],
        game.particlesystems["FXPS_Test"],
        game.mappedimages["TestButtonIcon"],
    ]


class TestArtIndex:
    def test_dds_beats_a_same_stem_tga(self, art):
        found = art.textures["testui"]
        assert found.name == "testui.dds"
        assert found.size == len(_TESTUI_DDS)

    def test_models_and_textures_indexed_by_stem(self, art):
        assert art.models["testkeep_skn"].size == len(_TESTKEEP_SKN_W3D)
        assert art.textures["testkeep"].size == len(_TESTKEEP_TGA)

    def test_read_w3d_returns_bytes_for_a_resolved_stem(self, art):
        assert art.read_w3d("TESTKEEP_SKN") == _TESTKEEP_SKN_W3D  # case-insensitive

    def test_read_w3d_none_for_an_unresolved_stem(self, art):
        assert art.read_w3d("nope") is None

    def test_later_source_overrides_earlier_regardless_of_extension(self, tmp_path):
        # A base source ships the dds; a "mod" source overrides with only a tga - the mod wins
        # even though its extension alone would lose the in-source priority contest.
        base = tmp_path / "base"
        base.mkdir()
        (base / "shared.dds").write_bytes(b"base-dds")
        mod = tmp_path / "mod"
        mod.mkdir()
        (mod / "shared.tga").write_bytes(b"mod-tga-override")

        art = ArtIndex.build([base, mod])
        assert art.textures["shared"].name == "shared.tga"

    def test_big_archive_source(self, tmp_path):
        pytest.importorskip("pyBIG")
        from pyBIG import Archive  # noqa: PLC0415 - lazy: the [ui]/[wiki] extra is optional

        archive = Archive.empty()
        archive.add_file("art\\test.tga", b"big-texture-bytes")
        big_path = tmp_path / "art.big"
        archive.save(str(big_path))

        art = ArtIndex.build([big_path])
        found = art.textures["test"]
        assert found.name == "test.tga"
        assert found.size == len(b"big-texture-bytes")
        assert found.load() == b"big-texture-bytes"


class TestObjectAssets:
    def test_model_texture_and_skeleton_resolve(self, game, art):
        records = object_assets([game.objects["TestCitadel"]], art)
        by_name = {r.name: r for r in records}

        model = by_name["testkeep_skn.w3d"]
        assert model.kind == "model"
        assert model.size == len(_TESTKEEP_SKN_W3D)
        assert model.source == str(art.models["testkeep_skn"].origin)

        skeleton = by_name["testkeep_skl.w3d"]
        assert skeleton.kind == "model"
        assert skeleton.size == len(_TESTKEEP_SKL_W3D)
        assert skeleton.referrers == ["testkeep_skn.w3d"]  # pulled in via the mesh's HLOD

        mesh_texture = by_name["testkeep.tga"]
        assert mesh_texture.kind == "texture"
        assert mesh_texture.referrers == ["testkeep_skn.w3d"]

    def test_animation_clip_counted(self, game, art):
        records = object_assets([game.objects["TestCitadel"]], art)
        animation = next(r for r in records if r.name == "testkeep_idla.w3d")
        assert animation.kind == "animation"
        assert animation.size == len(_TESTKEEP_IDLA_W3D)
        assert animation.referrers == ["TestCitadel"]

    def test_shared_model_referrer_counted_once_not_per_state(self, game, art):
        # DefaultModelConditionState and the DAMAGED state both name TestKeep_SKN; the citadel is
        # one referrer, not two.
        records = object_assets([game.objects["TestCitadel"]], art)
        model = next(r for r in records if r.name == "testkeep_skn.w3d")
        assert model.referrers == ["TestCitadel"]
        assert model.ref_count == 1

    def test_particle_texture_from_the_particle_system(self, game, art):
        records = object_assets([game.particlesystems["FXPS_Test"]], art)
        particle_texture = next(r for r in records if r.name == "testfx.tga")
        assert particle_texture.kind == "texture"
        assert particle_texture.referrers == ["FXPS_Test"]

    def test_mapped_image_texture(self, game, art):
        records = object_assets([game.mappedimages["TestButtonIcon"]], art)
        ui_texture = next(r for r in records if r.name == "testui.dds")  # dds wins over tga
        assert ui_texture.referrers == ["TestButtonIcon"]

    def test_missing_texture_has_no_size_and_missing_source(self, game, art):
        records = object_assets([game.objects["TestSoldier"]], art)
        missing = next(r for r in records if r.name == "testsoldieralt.tga")
        assert missing.kind == "texture"
        assert missing.size is None
        assert missing.source == "missing"
        assert missing.referrers == ["TestSoldier"]

    def test_only_passed_objects_are_walked(self, game, art):
        # Walking just the soldier must not surface the citadel's or the particle system's assets.
        records = object_assets([game.objects["TestSoldier"]], art)
        names = {r.name for r in records}
        assert "testsoldier_skn.w3d" in names
        assert "testkeep_skn.w3d" not in names
        assert "testfx.tga" not in names

    def test_dedup_across_multiple_objects(self, game, art):
        # Two objects both naming testui via the shared MappedImage -> one record, both referrers.
        records = object_assets(
            [game.objects["TestCitadel"], game.mappedimages["TestButtonIcon"]], art
        )
        ui = [r for r in records if r.name == "testui.dds"]
        assert len(ui) == 1
        assert ui[0].referrers == ["TestButtonIcon"]  # SelectPortrait resolves through the image

    def test_every_expected_asset_present_exactly_once(self, game, art, all_objects):
        records = object_assets(all_objects, art)
        names = [r.name for r in records]
        assert len(names) == len(set(names))  # every stem appears exactly once
        expected = {
            "testkeep_skn.w3d",
            "testkeep_skl.w3d",
            "testkeep_idla.w3d",
            "testsoldier_skn.w3d",
            "testkeep.tga",
            "testfx.tga",
            "testui.dds",
            "testsoldieralt.tga",
        }
        assert expected <= set(names)


class TestWriteCsv:
    def _rows(self, records):
        out = io.StringIO()
        write_csv(records, out)
        return list(csv.reader(io.StringIO(out.getvalue())))

    def test_header_and_shape(self, game, art, all_objects):
        records = object_assets(all_objects, art)
        rows = self._rows(records)
        assert rows[0] == ["asset", "kind", "size_bytes", "ref_count", "references", "source"]
        assert len(rows) == 1 + len(records)

    def test_missing_row_sorts_last_with_empty_size(self, game, art, all_objects):
        records = object_assets(all_objects, art)
        rows = self._rows(records)
        last = rows[-1]
        assert last[0] == "testsoldieralt.tga"
        assert last[2] == ""  # empty size_bytes
        assert last[5] == "missing"

    def test_resolved_rows_sorted_by_size_descending(self, game, art, all_objects):
        records = object_assets(all_objects, art)
        rows = self._rows(records)[1:-1]  # header off the top, the missing row off the bottom
        sizes = [int(row[2]) for row in rows]
        assert sizes == sorted(sizes, reverse=True)

    def test_references_column_is_semicolon_joined(self, game, art, all_objects):
        records = object_assets(all_objects, art)
        rows = {row[0]: row for row in self._rows(records)[1:]}
        assert rows["testkeep_skn.w3d"][4] == "TestCitadel"
