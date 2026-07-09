"""APT texture resolver: cropping `image` characters out of an atlas (Phase 6.4).

Needs Pillow (the `[apt]`/`[ui]` extra); skipped cleanly when absent. Uses a synthetic
in-memory atlas and a stub source, so no game files are required."""

import base64
import io

import pytest

pytest.importorskip("PIL", reason="the [apt]/[ui] extra (Pillow) is not installed")
from PIL import Image  # noqa: E402 - after the importorskip guard

from sage_apt.imagemap import parse_image_map  # noqa: E402
from sage_apt.textures import AptTextureResolver, build_resolver  # noqa: E402


class _StubSource:
    """Minimal stand-in for TextureSource: one named atlas of known bytes."""

    def __init__(self, name, image):
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        self._data = {name: buf.getvalue()}

    def texture_bytes(self, texture):
        return self._data.get(str(texture))


def _atlas():
    # 100x100 atlas: a red block at (0,0,10,20), green elsewhere.
    img = Image.new("RGBA", (100, 100), (0, 255, 0, 255))
    for x in range(10):
        for y in range(20):
            img.putpixel((x, y), (255, 0, 0, 255))
    return img


def test_crop_matches_rectangle():
    imap = parse_image_map("5->1\n5=0 0 10 20\n")
    source = _StubSource("apt_MyMovie_1", _atlas())
    resolver = AptTextureResolver("MyMovie", imap, source)

    png = resolver.image_png(5)
    assert png is not None
    crop = Image.open(io.BytesIO(png))
    assert crop.size == (10, 20)
    assert crop.convert("RGBA").getpixel((0, 0)) == (255, 0, 0, 255)


def test_data_uri_wraps_png():
    imap = parse_image_map("5=0 0 10 20\n")  # texture defaults to 1 when unassigned
    resolver = AptTextureResolver("MyMovie", imap, _StubSource("apt_MyMovie_1", _atlas()))
    uri = resolver.image_data_uri(5)
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert Image.open(io.BytesIO(raw)).size == (10, 20)


def test_no_rectangle_returns_none():
    imap = parse_image_map("5->1\n")  # assignment but no rectangle -> unknown size
    resolver = AptTextureResolver("MyMovie", imap, _StubSource("apt_MyMovie_1", _atlas()))
    assert resolver.image_png(5) is None


def test_missing_texture_returns_none():
    imap = parse_image_map("5=0 0 10 20\n")
    resolver = AptTextureResolver("MyMovie", imap, _StubSource("apt_Other_1", _atlas()))
    assert resolver.image_png(5) is None


def test_build_resolver_none_without_game_dir(tmp_path):
    assert build_resolver(tmp_path / "Movie.xml", None) is None
    assert build_resolver(tmp_path / "Movie.xml", "") is None


def test_geometry_resolver_end_to_end(tmp_path):
    """A movie with a `.dat`, a `_geometry` dir and its atlas resolves textured shape fills."""
    # atlas lives beside the movie; TextureSource finds apt_Movie_1 by file name
    _atlas().save(tmp_path / "apt_Movie_1.tga")
    (tmp_path / "Movie.xml").write_text("<aptdata/>", encoding="utf-8")
    (tmp_path / "Movie.dat").write_text("102->1\n", encoding="utf-8")
    geo = tmp_path / "Movie_geometry"
    geo.mkdir()
    (geo / "5.ru").write_text(
        "c\ns tc:255:255:255:255:102:1:0:0:1:10:20\nt 0:0:10:0:10:10\n", encoding="utf-8"
    )

    resolver = build_resolver(tmp_path / "Movie.xml", tmp_path)
    assert resolver is not None

    manifest = resolver.geometry_manifest()
    assert "5" in manifest
    fill = manifest["5"][0]
    assert fill["kind"] == "textured"
    assert fill["tex"] == 1
    assert fill["w"] == 100 and fill["h"] == 100
    assert fill["inv"] == [1.0, -0.0, -0.0, 1.0, -10.0, -20.0]
    assert fill["tris"] == [[0.0, 0.0, 10.0, 0.0, 10.0, 10.0]]

    # the whole atlas is available by texture id for /api/atlas/<tex>
    png = resolver.atlas_png_by_texture(1)
    assert png is not None and Image.open(io.BytesIO(png)).size == (100, 100)
