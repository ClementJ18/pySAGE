"""Tests for the headless texture resolver / button-image cropper (sage_utils.textures)."""

from pathlib import Path

import pytest
from PIL import Image

import sage_ini.model.definitions  # noqa: F401  (register classes, incl. MappedImage)
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_utils.textures import (
    TextureSource,
    ability_overlay,
    composite_on_background,
    crop_mapped_image,
    default_background,
    frame_icon,
)

pytestmark = pytest.mark.full


def _mapped_image(body: str):
    """A parsed MappedImage definition from its block body."""
    game = Game()
    result = parse(f"MappedImage TestImg\n{body}End\n", file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game.mappedimages["TestImg"]


def _write_image(path: Path, size, color=(255, 0, 0, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "TGA" if path.suffix.lower() == ".tga" else "DDS"
    Image.new("RGBA", size, color).save(path, format=fmt)


def _write_dds(path: Path, size, color=(255, 0, 0, 255)) -> None:
    _write_image(path, size, color)


def test_texture_source_resolves_compiledtextures_path(tmp_path):
    # "INGameUI.tga" -> art/compiledtextures/IN/INGameUI.dds, matched case-insensitively.
    _write_dds(tmp_path / "art" / "compiledtextures" / "in" / "INGameUI.dds", (64, 64))
    source = TextureSource([("folder", str(tmp_path))])
    assert len(source) == 1
    assert source.texture_bytes("INGameUI.tga") is not None
    assert source.texture_bytes("Missing.tga") is None


def test_texture_source_falls_back_to_filename(tmp_path):
    # A texture stored outside the compiledtextures/XX layout still resolves by name.
    _write_dds(tmp_path / "art" / "textures" / "Loose.dds", (16, 16))
    source = TextureSource([("folder", str(tmp_path))])
    assert source.texture_bytes("Loose.tga") is not None


def test_texture_source_falls_back_to_tga_when_no_dds(tmp_path):
    # The Texture names ".tga"; usually the shipped file is the compiled ".dds",
    # but a source carrying the uncompiled ".tga" still resolves.
    _write_image(tmp_path / "art" / "compiledtextures" / "in" / "INGameUI.tga", (32, 32))
    source = TextureSource([("folder", str(tmp_path))])
    assert source.texture_bytes("INGameUI.tga") is not None


def test_texture_source_prefers_dds_over_tga(tmp_path):
    # Both extensions present — the compiled .dds wins (8x8 vs the .tga's 4x4).
    _write_image(tmp_path / "art" / "compiledtextures" / "in" / "INGameUI.dds", (8, 8))
    _write_image(tmp_path / "art" / "compiledtextures" / "in" / "INGameUI.tga", (4, 4))
    source = TextureSource([("folder", str(tmp_path))])
    image = _mapped_image("Texture = INGameUI.tga\n")
    cropped = crop_mapped_image(source, image)
    assert cropped is not None and cropped.size == (8, 8)


def test_crop_mapped_image_crops_to_coords(tmp_path):
    _write_dds(tmp_path / "art" / "compiledtextures" / "te" / "Tex.dds", (100, 80))
    source = TextureSource([("folder", str(tmp_path))])
    image = _mapped_image(
        "Texture = Tex.tga\n"
        "TextureWidth = 100\n"
        "TextureHeight = 80\n"
        "Coords = Left:10 Top:20 Right:40 Bottom:60\n"
    )
    cropped = crop_mapped_image(source, image)
    assert cropped is not None
    assert cropped.size == (30, 40)  # (Right-Left) x (Bottom-Top)
    assert cropped.mode == "RGBA"


def test_crop_scales_coords_to_actual_texture_size(tmp_path):
    # Authored against a 200x160 texture but compiled at half that — coords scale.
    _write_dds(tmp_path / "art" / "compiledtextures" / "te" / "Tex.dds", (100, 80))
    source = TextureSource([("folder", str(tmp_path))])
    image = _mapped_image(
        "Texture = Tex.tga\n"
        "TextureWidth = 200\n"
        "TextureHeight = 160\n"
        "Coords = Left:20 Top:40 Right:80 Bottom:120\n"
    )
    cropped = crop_mapped_image(source, image)
    assert cropped is not None
    assert cropped.size == (30, 40)  # halved to the compiled size


def test_crop_without_coords_returns_whole_texture(tmp_path):
    _write_dds(tmp_path / "art" / "compiledtextures" / "te" / "Tex.dds", (24, 24))
    source = TextureSource([("folder", str(tmp_path))])
    cropped = crop_mapped_image(source, _mapped_image("Texture = Tex.tga\n"))
    assert cropped is not None
    assert cropped.size == (24, 24)


def test_crop_returns_none_when_texture_missing(tmp_path):
    source = TextureSource([("folder", str(tmp_path))])
    assert crop_mapped_image(source, _mapped_image("Texture = Nope.tga\n")) is None


def test_composite_on_background_centers_and_sizes_to_background():
    background = Image.new("RGBA", (192, 197), (50, 40, 30, 255))
    portrait = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    result = composite_on_background(portrait, background)
    assert result.size == background.size  # background-sized
    # 64x64 scaled to fit 192x197 -> 192x192, centered with a 2px vertical margin.
    assert result.getpixel((96, 98)) == (255, 0, 0, 255)  # red portrait at the center
    assert result.getpixel((96, 0))[:3] == (50, 40, 30)  # parchment shows in the top margin


def test_default_background_loads_the_bundled_asset():
    # The parchment asset ships in the package, so it decodes to an RGBA image.
    background = default_background()
    assert background is not None
    assert background.mode == "RGBA"


def test_ability_overlay_loads_the_bundled_frames():
    # Both frames ship in the package; an unknown kind resolves to nothing.
    for kind in ("active", "passive"):
        overlay = ability_overlay(kind)
        assert overlay is not None
        assert overlay.mode == "RGBA"
    assert ability_overlay(None) is None
    assert ability_overlay("upgrade") is None


def test_frame_icon_scales_and_centers_under_the_overlay():
    overlay = Image.new("RGBA", (66, 68), (0, 0, 0, 0))  # transparent frame canvas
    icon = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
    framed = frame_icon(icon, overlay, size=58)
    assert framed.size == overlay.size  # overlay-sized
    # The 58x58 icon is centered, so the canvas center is the icon's red.
    assert framed.getpixel((33, 34)) == (255, 0, 0, 255)
    # The corner is outside the 58x58 icon, so the transparent canvas shows through.
    assert framed.getpixel((0, 0)) == (0, 0, 0, 0)
