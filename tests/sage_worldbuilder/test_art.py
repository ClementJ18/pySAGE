"""The art the 3D view draws with: textures decoded bottom row first and kept, and a model's FX
shader material."""

import io
from types import SimpleNamespace

import pytest

pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.render.art import ArtTextures, fx_material  # noqa: E402


class FakeArt:
    def __init__(self, textures, models):
        self.textures, self.models, self.reads = textures, models, 0

    def find_texture(self, name):
        self.reads += 1
        return self.textures.get(name)

    def find_model(self, name):
        return self.models.get(name)


def _tga(width, height, rgba):
    image = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image.new("RGBA", (width, height), rgba).save(buffer, format="TGA")
    return buffer.getvalue()


def _property(name, value):
    return SimpleNamespace(name=name, value=value)


def test_textures_decode_bottom_row_first_and_are_read_once():
    art = FakeArt({"Env.tga": _tga(4, 2, (10, 20, 30, 40))}, {})
    textures = ArtTextures(art)
    pixels = textures.texture("Env.tga")
    assert pixels.shape == (2, 4, 4)
    assert pixels[0, 0].tolist() == [10, 20, 30, 40]
    textures.texture("env.TGA")
    assert art.reads == 1
    assert textures.texture("Missing.tga") is None


def test_fx_materials_come_from_the_first_mesh_that_has_one():
    material = SimpleNamespace(
        properties=[_property("WaterEnvTexture", "Env.tga"), _property("EnvUVScale", (0.2, 0.2))]
    )
    model = SimpleNamespace(
        meshes=[
            SimpleNamespace(shader_materials=None),
            SimpleNamespace(shader_materials=SimpleNamespace(chunks=[material])),
        ]
    )
    assert fx_material(model) == {"waterenvtexture": "Env.tga", "envuvscale": (0.2, 0.2)}
    textures = ArtTextures(FakeArt({}, {"Wtr_Moat": model}))
    assert textures.material("Wtr_Moat")["waterenvtexture"] == "Env.tga"
    assert textures.material("NoSuchShader") is None
