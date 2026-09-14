"""New maps, and the heightmap file formats."""

import io

import pytest

from sage_map.map import parse_map, write_map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.heightmap_io import (  # noqa: E402
    Anchor,
    export_raw,
    import_raw,
    raw_size,
    read_image_heights,
    reanchor,
)
from sage_worldbuilder.new_map import NewMapOptions, new_map, tile_pattern  # noqa: E402
from sage_worldbuilder.render.topdown import tile_classes  # noqa: E402
from sage_worldbuilder.terrain.cells import CellLayer  # noqa: E402


def test_a_new_map_saves_and_reopens_with_its_size_height_and_texture():
    options = NewMapOptions(width=64, height=48, border=6, initial_height=20.0, texture="Gravel")
    map = new_map(options)
    reopened = parse_map(io.BytesIO(write_map(map, compress=False)))
    height_map = reopened.height_map_data
    assert (height_map.width, height_map.height, height_map.border_width) == (64, 48, 6)
    assert height_map.borders[0].position == (52, 36)
    assert {value for row in height_map.elevations for value in row} == {512}
    blend = reopened.blend_tile_data
    assert [texture.name for texture in blend.textures] == ["Gravel"]
    assert (tile_classes(blend) == 0).all()
    assert blend.texture_cell_count == 16 and blend.blends_count_raw == 1
    assert len(reopened.mp_positions_list.positions) == 8
    assert reopened.world_info.properties["isLivingWorldScriptHolder"]["value"] is False
    assert [t.properties["teamName"]["value"] for t in reopened.teams.teams] == ["team"]
    assert reopened.sides_list.players[0].properties["playerDisplayName"]["value"] == "Neutral"
    assert write_map(reopened, compress=False) == write_map(map, compress=False)

    document = MapDocument(reopened)
    assert document.terrain.heights.shape == (48, 64)
    assert document.cells(CellLayer.VISIBLE).all()
    assert not document.cells(CellLayer.IMPASSABLE).any()


def test_new_map_options_are_checked():
    with pytest.raises(ValueError):
        new_map(NewMapOptions(width=20, height=20, border=10))
    with pytest.raises(ValueError):
        new_map(NewMapOptions(texture=""))


def test_tiles_repeat_every_two_texture_cells_with_quadrant_bits():
    tiles = tile_pattern(10, 4, 16, 4)
    assert tiles[0, :4].tolist() == [64, 65, 68, 69]
    assert tiles[1, :2].tolist() == [66, 67]
    assert tiles[2, 0] == (16 + 4) << 2
    assert tiles[0, 8] == tiles[0, 0]


def test_raw_heightmaps_round_trip_top_row_first():
    heights = np.arange(12, dtype=np.uint16).reshape(3, 4) * 1000
    data = export_raw(heights)
    assert len(data) == 12 * 6 and raw_size(data) == 12
    # The first sample in the file is the top-left one, three times.
    assert data[:6] == (8000).to_bytes(2, "little") * 3
    assert np.array_equal(import_raw(data, 4, 3), heights)
    with pytest.raises(ValueError):
        import_raw(data, 3, 3)
    with pytest.raises(ValueError):
        raw_size(data[:-1])


def test_reanchor_crops_and_pads_about_the_anchor():
    values = np.arange(4, dtype=np.uint16).reshape(2, 2) + 1
    grown = reanchor(values, (4, 4), Anchor.BOTTOM_LEFT, 0)
    assert grown[:2, :2].tolist() == [[1, 2], [3, 4]] and grown[2:, :].sum() == 0
    top_right = reanchor(values, (4, 4), Anchor.TOP_RIGHT, 9)
    assert top_right[2:, 2:].tolist() == [[1, 2], [3, 4]] and top_right[0, 0] == 9
    centred = reanchor(values, (4, 4), Anchor.CENTER, 0)
    assert centred[1:3, 1:3].tolist() == [[1, 2], [3, 4]]
    shrunk = reanchor(np.arange(16, dtype=np.uint16).reshape(4, 4), (2, 2), Anchor.CENTER, 0)
    assert shrunk.tolist() == [[5, 6], [9, 10]]


def test_grey_images_become_heights():
    from PIL import Image  # noqa: PLC0415

    image = Image.new("L", (3, 2))
    image.putpixel((0, 0), 10)  # top-left
    buffer = io.BytesIO()
    image.save(buffer, format="TGA")
    heights = read_image_heights(buffer.getvalue())
    assert heights.shape == (2, 3)
    assert heights[1, 0] == 160 and heights[0, 0] == 0
