"""Seeing blends in the top-down view: the kinds of blend, their fades across a cell, the picture
with blends at several pixels a cell, the Show Blends tint, and patching the picture after an
Auto Edge."""

import pytest

from sage_map.assets.blend_tile_data import BlendDescription
from sage_map.map import Map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import blank_blend_tile_data, blank_height_map  # noqa: E402
from sage_worldbuilder.render.topdown import (  # noqa: E402
    blend_kinds,
    blend_masks,
    blend_overlay,
    blend_pixels,
    blended_colors,
    terrain_image,
)
from sage_worldbuilder.terrain.blending import auto_edge_out  # noqa: E402
from sage_worldbuilder.terrain.cells import TileLayer  # noqa: E402
from sage_worldbuilder.terrain.edits import PaintBlends, PaintTiles  # noqa: E402
from sage_worldbuilder.terrain.textures import paint_texture_block, planned_texture  # noqa: E402
from sage_worldbuilder.texture_colors import (  # noqa: E402
    patch_picture_colors,
    picture_colors,
)

GRASS, ROCK = (0, 200, 0), (100, 100, 100)


class Colors:
    def color(self, name):
        return {"grass": GRASS, "rock": ROCK}.get(name.lower())


def description(raw, flags=0, two_sided=False, edge=0xFFFFFFFF):
    return BlendDescription(0, bytes(raw), flags, two_sided, edge)


def test_blend_kinds_are_the_games_mask_choice():
    kinds = blend_kinds(
        [
            description((1, 0, 0, 0)),
            description((1, 0, 0, 0), 1),
            description((0, 1, 0, 0), 3),
            description((0, 0, 1, 0)),
            description((0, 0, 0, 1), 1, True),
            description((1, 0, 0, 0), edge=5),
            description((1, 1, 0, 0)),
        ]
    )
    assert kinds.tolist() == [-1, 0, 6, 7, 3, 10, 0, 0]


def test_blend_masks_fade_in_from_their_side():
    masks = blend_masks(4)
    assert (masks[0][:, -1] > masks[0][:, 0]).all(), "from +x"
    assert (masks[7][0, :] > masks[7][-1, :]).all(), "from -y (row 0 is the bottom)"
    assert masks[3][-1, -1] > 0 and masks[3][0, 0] == 0, "an outside corner at (+1, +1)"
    assert masks[5][0, -1] > 0.8 and masks[5][-1, 0] > 0.8 and masks[5][0, 0] < 0.3


def test_blended_colors_fade_a_cells_blend_and_put_three_way_blends_on_top():
    base = np.array([[(255, 0, 0), (0, 255, 0)]], dtype=np.uint8)
    kinds = np.array([-1, 0, 6], dtype=np.int16)
    colors = np.array([(0, 0, 0), (0, 0, 255), (255, 255, 255)], dtype=np.uint8)
    picture = blended_colors(base, (np.array([[1, 0]]),), kinds, colors, 4)
    assert picture.shape == (4, 8, 3)
    assert (picture[:, 3, 2] > picture[:, 0, 2]).all(), "blue grows towards +x"
    assert (picture[:, 4:] == (0, 255, 0)).all(), "the unblended cell keeps its colour"
    both = blended_colors(base, (np.array([[1, 0]]), np.array([[2, 0]])), kinds, colors, 4)
    assert both[0, 0, 1] > picture[0, 0, 1], "the 3-way blend whitens the -x side"
    past = blended_colors(base, (np.array([[9, 0]]),), kinds, colors, 4)
    assert (past[:, :4] == (255, 0, 0)).all()


def test_the_picture_takes_several_pixels_a_cell():
    heights = np.arange(6, dtype=np.uint16).reshape(2, 3)
    assert terrain_image(heights, np.zeros((8, 12, 3), dtype=np.uint8)).shape == (8, 12, 4)
    assert terrain_image(heights, np.zeros((5, 5, 3), dtype=np.uint8)).shape == (2, 3, 4)
    assert blend_pixels((420, 485)) == 4 and blend_pixels((720, 720)) == 2
    assert blend_pixels((10, 3000)) == 1


def test_show_blends_tints_blended_cells_and_three_way_ones_white():
    pixels = blend_overlay(np.array([[1, 0], [0, 2]]), np.array([[0, 0], [0, 3]]))
    # Rows top first: stored row 1 is image row 0.
    assert pixels[1, 0, 3] > 0 and pixels[1, 1, 3] == 0
    assert tuple(pixels[0, 1, :3]) == (255, 255, 255)


def edged_square():
    """A 20 x 16 grass map with a 4 x 4 rock square at cells x 8-11, y 6-9, edged outward."""
    map = Map()
    map.height_map_data = blank_height_map(20, 16, 2, 0)
    map.blend_tile_data = blank_blend_tile_data(20, 16, "Grass")
    document = MapDocument(map)
    blend = map.blend_tile_data
    rock = planned_texture(blend, "Rock", 2)
    layers = {layer: document.cells(layer) for layer in TileLayer}
    document.execute(PaintTiles(8, 6, paint_texture_block(layers, (8, 6, 12, 10), rock), rock))
    layers = {layer: document.cells(layer) for layer in TileLayer}
    edit = auto_edge_out(layers, blend.textures, blend.blend_descriptions, (9, 7))
    document.execute(PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions))
    return document


def test_the_picture_shows_the_rock_fading_onto_the_ring():
    document = edged_square()
    blend = document.map.blend_tile_data
    base, picture, _table = picture_colors(blend, document.terrain.heights, Colors())
    assert base.shape == (16, 20, 3) and picture.shape == (64, 80, 3)
    # Cell (7, 7) blends rock in from +x: greyer (more red) towards its right edge.
    cell = picture[7 * 4 : 8 * 4, 7 * 4 : 8 * 4]
    assert (cell[:, -1, 0] > cell[:, 0, 0]).all()
    assert (picture[0:4, 0:4] == GRASS).all(), "a cell far from the rock is plain grass"
    assert (picture[7 * 4 : 8 * 4, 9 * 4 : 10 * 4] == ROCK).all(), "the rock itself is not blended"


def test_patching_the_picture_matches_making_it_again():
    document = edged_square()
    blend = document.map.blend_tile_data
    base, picture, table = picture_colors(blend, document.terrain.heights, Colors())
    patched = picture.copy()
    patched[5 * 4 : 11 * 4, 7 * 4 : 13 * 4] = 0
    patch_picture_colors(
        patched,
        base,
        document.cells(TileLayer.BLENDS),
        document.cells(TileLayer.THREE_WAY_BLENDS),
        table,
        (7, 5, 13, 11),
    )
    assert np.array_equal(patched, picture)
