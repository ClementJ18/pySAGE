"""The terrain as the game textures it: the blend mask choice and the masks, texture cells cut
from their images in the game's row order, the atlas, and the per-cell data the 3D view's shader
reads. No Qt or OpenGL."""

import pytest

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")
pytest.importorskip("PIL", reason="the [worldbuilder] extra (pillow) is not installed")

from sage_map.assets.blend_tile_data import BlendDescription, BlendTileTexture  # noqa: E402
from sage_worldbuilder.render.terrain_texturing import (  # noqa: E402
    MISSING_TEXTURE,
    blend_secondaries,
    build_atlas,
    cell_data,
    mask_index,
    mask_indices,
    mask_weight,
    mask_weights,
    texture_cells,
)


def description(raw, flags=0, two_sided=False, tile=0, edge=0xFFFFFFFF):
    return BlendDescription(tile, bytes(raw), flags, two_sided, edge)


def test_the_mask_is_the_first_direction_set_with_long_diagonals_and_inversion():
    cases = [
        ((1, 0, 0, 0), 0, False, 0),
        ((0, 1, 0, 0), 0, False, 1),
        ((0, 0, 0, 1), 0, False, 2),
        ((0, 0, 1, 0), 0, False, 3),
        ((0, 0, 0, 1), 0, True, 4),
        ((0, 0, 1, 0), 0, True, 5),
        ((1, 0, 0, 0), 1, False, 6),
        ((0, 1, 0, 0), 2, False, 7),
        ((0, 0, 0, 1), 3, True, 10),
        ((1, 1, 0, 0), 0, False, 0),
        ((0, 0, 0, 0), 0, False, 0),
        ((1, 0, 0, 0), 0, True, 0),
    ]
    for raw, flags, two_sided, expected in cases:
        assert mask_index(description(raw, flags, two_sided)) == expected, (raw, flags, two_sided)
    assert mask_indices([description((0, 1, 0, 0))]).tolist() == [-1, 1]


def test_axis_masks_fade_in_from_their_side():
    assert mask_weight(0, 0, 30) == 0.0 and mask_weight(0, 63, 30) == 1.0, "from +x"
    assert mask_weight(6, 0, 30) == 1.0 and mask_weight(6, 63, 30) == 0.0, "inverted: from -x"
    assert mask_weight(1, 20, 63) == 1.0 and mask_weight(1, 20, 0) == 0.0, "from +y"
    assert mask_weight(7, 20, 0) == 1.0, "inverted: from -y"


def test_a_diagonal_fills_its_corner_and_a_long_one_all_but_the_far_corner():
    assert mask_weight(3, 63, 63) == 1.0, "right diagonal: the +x, +y corner"
    assert mask_weight(3, 0, 0) == 0.0 and mask_weight(3, 0, 63) == 0.0
    assert mask_weight(9, 63, 0) == 1.0 and mask_weight(9, 0, 63) == 0.0, "inverted: +x, -y"
    assert mask_weight(2, 0, 63) == 1.0 and mask_weight(2, 63, 0) == 0.0, "left: -x, +y"
    assert mask_weight(8, 0, 0) == 1.0, "inverted left: -x, -y"
    assert mask_weight(5, 0, 63) == 1.0 and mask_weight(5, 63, 0) == 1.0
    assert mask_weight(5, 0, 0) < 0.05


@pytest.mark.parametrize("pixels", [64, 4])
def test_the_mask_pictures_are_the_mask_arithmetic_at_pixel_centres(pixels):
    masks = mask_weights(pixels)
    assert masks.shape == (12, pixels, pixels)
    centres = [min(max((i + 0.5) * 64 / pixels - 0.5, 0.0), 63.0) for i in range(pixels)]
    for index in range(12):
        for row in (0, pixels // 2, pixels - 1):
            for column in (0, pixels // 3, pixels - 1):
                expected = mask_weight(index, centres[column], centres[row])
                assert masks[index, row, column] == pytest.approx(expected, abs=1e-6)


def tga(cells_across, top_first):
    """An uncompressed 32-bit TGA, 64-pixel cells, each cell one colour from its place in the
    file: the cell at file row r, column c is (40 r, 40 c, 200)."""
    side = cells_across * 64
    rows = []
    for scanline in range(side):
        row = bytearray()
        for x in range(side):
            red, green, blue = 40 * (scanline // 64), 40 * (x // 64), 200
            row += bytes((blue, green, red, 255))
        rows.append(bytes(row))
    header = bytes((0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    header += side.to_bytes(2, "little") * 2 + bytes((32, 8 | (0x20 if top_first else 0)))
    return header + b"".join(rows)


@pytest.mark.parametrize("top_first", [False, True])
def test_texture_cells_follow_the_files_scanline_order_whatever_its_origin(top_first):
    cells = texture_cells(tga(2, top_first), 2)
    assert cells is not None and cells.shape == (2, 2, 64, 64, 4)
    for row in range(2):
        for column in range(2):
            assert tuple(cells[row, column, 5, 7]) == (40 * row, 40 * column, 200, 255)


def test_texture_cells_are_resized_to_the_pixels_asked_for_and_unreadable_data_gives_none():
    cells = texture_cells(tga(2, False), 2, pixels=16)
    assert cells is not None and cells.shape == (2, 2, 16, 16, 4)
    assert tuple(cells[1, 0, 3, 3]) == (40, 0, 200, 255)
    assert texture_cells(b"not an image", 2) is None


def solid_cells(texture, pixels):
    size = texture.cell_size
    cells = np.zeros((size, size, pixels, pixels, 4), dtype=np.uint8)
    for row in range(size):
        for column in range(size):
            cells[row, column] = (texture.cell_start, row, column, 255)
    return cells


def test_the_atlas_places_each_texture_cell_by_its_number():
    textures = [BlendTileTexture(0, 4, 2, 0, "a"), BlendTileTexture(4, 1, 1, 0, "b")]
    atlas = build_atlas(textures, solid_cells)
    assert atlas.side == 3 and atlas.cell_pixels == 64
    assert atlas.pixels.shape == (192, 192, 4)
    # Cell 3 (texture a, row 1, column 1) is slot row 1, column 0; cell 4 is slot (1, 1).
    assert tuple(atlas.pixels[64 + 10, 10]) == (0, 1, 1, 255)
    assert tuple(atlas.pixels[64 + 10, 64 + 10]) == (4, 0, 0, 255)
    assert tuple(atlas.pixels[2 * 64 + 1, 2 * 64 + 1]) == MISSING_TEXTURE


def test_the_atlas_halves_its_cells_to_fit_and_leaves_an_unread_texture_grey():
    textures = [BlendTileTexture(0, 4, 2, 0, "a"), BlendTileTexture(4, 1, 1, 0, "b")]
    asked = []

    def cells_for(texture, pixels):
        asked.append(pixels)
        return None if texture.name == "b" else solid_cells(texture, pixels)

    atlas = build_atlas(textures, cells_for, max_size=64)
    assert atlas.cell_pixels == 16 and set(asked) == {16}
    assert tuple(atlas.pixels[16 + 1, 16 + 1]) == MISSING_TEXTURE


def test_cell_data_packs_tiles_and_masks_and_drops_what_the_game_does_not_draw():
    descriptions = [description((1, 0, 0, 0), tile=40), description((0, 0, 1, 0), 1, tile=44)]
    indices, secondaries = mask_indices(descriptions), blend_secondaries(descriptions)
    tiles = np.array([[5, 6, 7, 8]], dtype=np.uint16)
    blends = np.array([[1, 2, 9, 1]])
    three_way = np.array([[2, 0, 1, 2]])
    cliffs = np.array([[0, 0, 0, 3]])
    data = cell_data(tiles, blends, three_way, cliffs, indices, secondaries)
    assert data.dtype == np.uint16 and data.shape == (1, 4, 4)
    # A blend (mask 0) with a 3-way blend (mask 3 + 6) on top.
    assert data[0, 0].tolist() == [5, 40, 44, (9 + 1) << 4 | 1]
    assert data[0, 1].tolist() == [6, 44, 0, 9 + 1]
    # A blend number past the table, and a cliff-mapped cell, draw their tile alone.
    assert data[0, 2].tolist() == [7, 0, 0, 0]
    assert data[0, 3].tolist() == [8, 0, 0, 0]


def test_cliff_cells_place_their_corners_in_their_textures_picture():
    from sage_map.assets.blend_tile_data import CliffTextureMapping  # noqa: PLC0415
    from sage_worldbuilder.render.terrain_texturing import (  # noqa: PLC0415
        CLIFF_FLAG,
        cliff_cells,
    )

    textures = [BlendTileTexture(0, 4, 2, 0, "Grass"), BlendTileTexture(4, 16, 4, 0, "Cliff")]
    cliff_tile = 6 << 2
    mappings = [
        CliffTextureMapping(cliff_tile, (0.5, 0.5), (0.6, 3.6), (0.8, 2.0), (0.75, 0.15), 0)
    ]
    # A cliff cell, the same mapping under a grass tile, and a cell with none.
    tiles = np.array([[cliff_tile, 1 << 2, cliff_tile]])
    cliffs = np.array([[1, 1, 0]])
    cells = cliff_cells(tiles, cliffs, mappings, textures)
    assert cells.drawn.tolist() == [[True, False, False]]
    assert cells.starts[0, 0] == 4 and cells.sizes[0, 0] == 4
    # The mapping's (u, v) in repeats of the picture, in texture cells of it.
    assert cells.corners[0, 0] == pytest.approx([2.0, 2.0, 2.4, 14.4, 3.2, 8.0, 3.0, 0.6])
    indices, secondaries = np.array([-1], dtype=np.int16), np.zeros(1, dtype=np.uint16)
    zeros = np.zeros_like(tiles)
    data = cell_data(tiles, zeros, zeros, cliffs, indices, secondaries, cells)
    assert data[0, 0].tolist() == [cliff_tile, 4, 4, CLIFF_FLAG]
    assert data[0, 1].tolist() == [1 << 2, 0, 0, 0]
