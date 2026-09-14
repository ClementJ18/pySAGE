"""Terrain texture colours for the map view, and the base install textures are read from."""

import io
from types import SimpleNamespace

import pytest

from sage_map.assets.blend_tile_data import BlendTileTexture
from sage_worldbuilder.gamedata import GameContext, GameLayers

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")
Image = pytest.importorskip("PIL.Image")

from sage_worldbuilder.texture_colors import (  # noqa: E402
    TextureColors,
    average_color,
    base_colors,
    terrain_textures,
)


def png(color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeFileSystem:
    def __init__(self, files):
        self.files = {path.lower(): data for path, data in files.items()}
        self.reads = 0

    def find(self, path):
        return path.lower() if path.lower() in self.files else None

    def read_bytes(self, entry):
        self.reads += 1
        return self.files[entry]


def test_average_color_and_unreadable_data():
    assert average_color(png((10, 200, 30))) == (10, 200, 30)
    assert average_color(b"not an image") is None


def test_colors_resolve_through_terrain_ini_and_are_cached():
    files = FakeFileSystem({"art\\terrain\\TGras01.tga": png((0, 128, 0))})
    colors = TextureColors(files, {"Grass": "TGras01.tga", "Rock": "TRock01.tga"})
    assert colors.color("GRASS") == (0, 128, 0)
    assert colors.color("grass") == (0, 128, 0)
    assert files.reads == 1
    assert colors.color("Rock") is None
    assert colors.color("Unknown") is None


def test_a_tga_texture_can_be_found_as_dds():
    files = FakeFileSystem({"art\\terrain\\TSand01.dds": png((200, 180, 90))})
    assert TextureColors(files, {"Sand": "TSand01.tga"}).color("Sand") == (200, 180, 90)


def test_base_colors_paint_known_textures_and_ramp_the_rest():
    class Blend:
        textures = [BlendTileTexture(0, 16, 4, 0, "Grass"), BlendTileTexture(16, 16, 4, 0, "Rock")]
        tiles = [[0, 0], [4 * 16, 4 * 16]]  # [x][y]: column 0 grass, column 1 rock

    files = FakeFileSystem({"art\\terrain\\g.tga": png((0, 128, 0))})
    colors = TextureColors(files, {"Grass": "g.tga", "Rock": "missing.tga"})
    heights = np.array([[0, 100], [50, 150]], dtype=np.uint16)
    rgb = base_colors(Blend(), heights, colors)
    assert rgb[0, 0].tolist() == [0, 128, 0]
    assert rgb[1, 0].tolist() == [0, 128, 0]
    assert rgb[0, 1].tolist() != [0, 0, 0]
    assert base_colors(Blend(), np.zeros((3, 3), dtype=np.uint16), colors).shape == (3, 3, 3)


def test_terrain_textures_reads_the_game_table():
    game = SimpleNamespace(
        terrains={"Grass": SimpleNamespace(Texture="g.tga"), "Blank": SimpleNamespace(Texture=None)}
    )
    assert terrain_textures(game) == {"Grass": "g.tga"}


def test_art_is_read_from_the_base_install_beneath(tmp_path):
    install, base = tmp_path / "rotwk", tmp_path / "bfme2"
    (install / "data").mkdir(parents=True)
    (base / "art" / "terrain").mkdir(parents=True)
    (base / "art" / "terrain" / "g.tga").write_bytes(b"texture")
    layers = GameLayers(install, base=base)
    context = GameContext.open(layers, detect_user_data=False)
    art = context.art_filesystem()
    assert art.find("art\\terrain\\g.tga") is not None
    assert context.art_filesystem() is art
    assert context.filesystem.find("art\\terrain\\g.tga") is None
    without = GameContext.open(GameLayers(install), detect_user_data=False)
    assert without.art_filesystem() is without.filesystem
    missing = GameContext.open(GameLayers(install, base=tmp_path / "gone"), detect_user_data=False)
    assert missing.art_filesystem() is missing.filesystem
