"""Blending as WorldBuilder does it: the blend writer's encoding, Blend Single Edge, Auto Edge Out
and In on a small map, the secondary tile rule against a real map made in WorldBuilder, and an
undoable Auto Edge on that map."""

import io
from pathlib import Path

import pytest

from sage_map.assets.blend_tile_data import BlendDescription, BlendTileTexture
from sage_map.map import Map, parse_map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import blank_blend_tile_data, blank_height_map  # noqa: E402
from sage_worldbuilder.terrain.blending import (  # noqa: E402
    DEFAULT_EDGE,
    auto_edge_in,
    auto_edge_out,
    description_side,
    optimized_blends,
    single_edge,
)
from sage_worldbuilder.terrain.cells import TileLayer, layer_array  # noqa: E402
from sage_worldbuilder.terrain.edits import PaintBlends, PaintTiles  # noqa: E402
from sage_worldbuilder.terrain.textures import (  # noqa: E402
    paint_texture_block,
    planned_texture,
    texture_classes,
    texture_tiles,
    tiling_offset,
)

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


def layers_of(document):
    return {layer: document.cells(layer) for layer in TileLayer}


def square_of_rock(mask=None):
    """A 20 x 16 grass map with a 4 x 4 square of rock at cells x 8-11, y 6-9, only where `mask`
    (`[y - 6, x - 8]`) is True when one is given."""
    map = Map()
    map.height_map_data = blank_height_map(20, 16, 2, 0)
    map.blend_tile_data = blank_blend_tile_data(20, 16, "Grass")
    document = MapDocument(map)
    rock = planned_texture(map.blend_tile_data, "Rock", 2)
    painted = paint_texture_block(layers_of(document), (8, 6, 12, 10), rock, mask)
    command = PaintTiles(8, 6, painted, rock)
    document.execute(command)
    command.closed = True
    return document, rock


def run(document, routine, *args, **kwargs):
    blend = document.map.blend_tile_data
    return routine(layers_of(document), blend.textures, blend.blend_descriptions, *args, **kwargs)


def apply(document, edit):
    command = PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions, "Blend", edit.texture)
    document.execute(command)
    command.closed = True


def blend_at(document, edit, x, y, layer=TileLayer.BLENDS):
    """The description an edit leaves in `layer` at map cell `(x, y)`, or None."""
    number = int(edit.layers[layer][y - edit.y0, x - edit.x0])
    known = [*document.map.blend_tile_data.blend_descriptions, *edit.descriptions]
    return known[number - 1] if number else None


def test_descriptions_decode_to_the_side_their_texture_is_on():
    def description(raw, flags, edge=DEFAULT_EDGE):
        return BlendDescription(0, bytes(raw), flags, False, edge)

    assert description_side(description((1, 0, 0, 0), 0)) == (1, 0)
    assert description_side(description((1, 0, 0, 0), 3)) == (-1, 0)
    assert description_side(description((0, 1, 0, 0), 1)) == (0, -1)
    assert description_side(description((0, 0, 1, 0), 1)) == (1, -1)
    assert description_side(description((0, 0, 0, 1), 0)) == (-1, 1)
    assert description_side(description((1, 0, 0, 0), 0, edge=5)) is None
    assert description_side(description((1, 1, 0, 0), 0)) is None


def test_tiling_offset_follows_the_maps_own_tiling():
    rock = BlendTileTexture(16, 4, 2, 0, "Rock")
    tiles = texture_tiles(rock, 0, 0, 6, 5, (3, 1))
    assert tiling_offset(tiles, rock) == (3, 1)
    assert tiling_offset(np.zeros((2, 2), dtype=np.int64), rock) == (0, 0)


def test_single_edge_blends_the_source_texture_from_its_side():
    document, rock = square_of_rock()
    edit = run(document, single_edge, (7, 7), (8, 7))
    assert (edit.x0, edit.y0) == (7, 7) and set(edit.layers) == {TileLayer.BLENDS}
    (description,) = edit.descriptions
    assert list(description.raw_blend_direction) == [1, 0, 0, 0]
    assert description.flags == 0 and not description.two_sided
    assert description.magic_value1 == DEFAULT_EDGE
    # The texture's own tile at the blended cell, not the neighbour's.
    assert description.secondary_texture_tile == texture_tiles(rock, 7, 7, 8, 8)[0, 0]
    apply(document, edit)
    assert run(document, single_edge, (7, 7), (8, 7)) is None, "already blended"
    assert run(document, single_edge, (3, 3), (4, 3)) is None, "the same texture"


def test_a_second_blend_goes_to_the_three_way_slot():
    document, _rock = square_of_rock()
    sand = planned_texture(document.map.blend_tile_data, "Sand", 4)
    # A corner facing its texture, then a side blend of the chosen texture onto the same cell.
    apply(document, run(document, single_edge, (7, 5), (8, 6)))
    edit = run(document, single_edge, (7, 5), (6, 5), sand)
    assert edit.texture is sand and set(edit.layers) == {TileLayer.THREE_WAY_BLENDS}
    side = blend_at(document, edit, 7, 5, TileLayer.THREE_WAY_BLENDS)
    assert list(side.raw_blend_direction) == [1, 0, 0, 0]
    assert side.flags == 1 | 2, "a side paired with a facing corner"
    count = len(document.map.blend_tile_data.textures)
    apply(document, edit)
    assert len(document.map.blend_tile_data.textures) == count + 1
    document.stack.undo()
    assert len(document.map.blend_tile_data.textures) == count


def test_a_facing_corner_over_a_side_marks_the_side():
    document, _rock = square_of_rock()
    sand = planned_texture(document.map.blend_tile_data, "Sand", 4)
    apply(document, run(document, single_edge, (7, 5), (6, 5), sand))
    edit = run(document, single_edge, (7, 5), (8, 6))
    corner = blend_at(document, edit, 7, 5, TileLayer.THREE_WAY_BLENDS)
    assert list(corner.raw_blend_direction) == [0, 0, 1, 0]
    side = blend_at(document, edit, 7, 5)
    assert list(side.raw_blend_direction) == [1, 0, 0, 0] and side.flags == 1 | 2


def test_corners_facing_apart_do_not_stack():
    document, _rock = square_of_rock()
    sand = planned_texture(document.map.blend_tile_data, "Sand", 4)
    apply(document, run(document, single_edge, (7, 5), (8, 6)))
    assert run(document, single_edge, (7, 5), (6, 6), sand) is None


def ring(edit):
    rows, columns = edit.layers[TileLayer.BLENDS].shape
    outside = np.ones((rows, columns), dtype=bool)
    outside[1:-1, 1:-1] = False
    return outside


def test_auto_edge_out_rings_the_area_with_its_texture():
    document, rock = square_of_rock()
    edit = run(document, auto_edge_out, (9, 7))
    assert (edit.x0, edit.y0) == (7, 5) and set(edit.layers) == {TileLayer.BLENDS}
    blends = edit.layers[TileLayer.BLENDS]
    assert blends.shape == (6, 6)
    assert (blends[1:5, 1:5] == 0).all(), "the area itself is not blended"
    assert (blends[ring(edit)] > 0).all()
    sides = {
        (7, 7): (1, 0),
        (12, 7): (-1, 0),
        (9, 5): (0, 1),
        (9, 10): (0, -1),
        (7, 5): (1, 1),
        (12, 5): (-1, 1),
        (7, 10): (1, -1),
        (12, 10): (-1, -1),
    }
    for (x, y), side in sides.items():
        description = blend_at(document, edit, x, y)
        assert description_side(description) == side and not description.two_sided
    for y, x in zip(*np.nonzero(ring(edit)), strict=True):
        description = blend_at(document, edit, edit.x0 + x, edit.y0 + y)
        expected = texture_tiles(rock, edit.x0 + x, edit.y0 + y, edit.x0 + x + 1, edit.y0 + y + 1)
        assert description.secondary_texture_tile == expected[0, 0]
    # Over the whole map, the one square gets the same blends.
    everywhere = run(document, auto_edge_out, (9, 7), whole_map=True)
    for y, x in zip(*np.nonzero(ring(edit)), strict=True):
        cell = edit.x0 + x, edit.y0 + y
        assert blend_at(document, everywhere, *cell) == blend_at(document, edit, *cell)


def test_auto_edge_out_fills_a_nearly_surrounded_cell():
    mask = np.ones((4, 4), dtype=bool)
    mask[3, 1] = False  # cell (9, 9) stays grass, with rock on three sides
    document, rock = square_of_rock(mask)
    edit = run(document, auto_edge_out, (8, 6))
    tiles = edit.layers[TileLayer.TILES]
    assert tiles[9 - edit.y0, 9 - edit.x0] == texture_tiles(rock, 9, 9, 10, 10)[0, 0]
    assert edit.layers[TileLayer.BLENDS][9 - edit.y0, 9 - edit.x0] == 0


def test_auto_edge_in_blends_the_surroundings_onto_the_edge():
    document, _rock = square_of_rock()
    for whole_map in (False, True):
        edit = run(document, auto_edge_in, (9, 7), whole_map=whole_map)
        assert (edit.x0, edit.y0) == (8, 6)
        blends = edit.layers[TileLayer.BLENDS]
        assert blends.shape == (4, 4)
        assert (blends[1:3, 1:3] == 0).all() and (blends[ring(edit)] > 0).all()
        corner = blend_at(document, edit, 8, 6)
        assert description_side(corner) == (-1, -1) and corner.two_sided
        assert description_side(blend_at(document, edit, 8, 7)) == (-1, 0)
        far = blend_at(document, edit, 11, 9)
        assert description_side(far) == (1, 1) and far.two_sided
        secondary = [d.secondary_texture_tile for d in edit.descriptions]
        assert (
            texture_classes(np.array(secondary), document.map.blend_tile_data.textures) == 0
        ).all()


def test_the_secondary_tile_rule_reproduces_a_real_maps_blends():
    """WorldBuilder's secondary tile is the blending texture tiled at the blended cell."""
    blend = parse_map(io.BytesIO(FIXTURE.read_bytes())).blend_tile_data
    tiles = layer_array(blend, TileLayer.TILES)
    textures = blend.textures
    starts = np.array([t.cell_start for t in textures])
    sizes = np.array([t.cell_size for t in textures])
    offsets = np.array([tiling_offset(tiles, t) for t in textures])
    secondary = np.array([d.secondary_texture_tile for d in blend.blend_descriptions])
    plain = np.array([d.magic_value1 == DEFAULT_EDGE for d in blend.blend_descriptions])
    for layer, share in ((TileLayer.BLENDS, 0.9), (TileLayer.THREE_WAY_BLENDS, 0.97)):
        numbers = layer_array(blend, layer)
        ys, xs = np.nonzero(numbers)
        found = secondary[numbers[ys, xs] - 1]
        classes = texture_classes(found, textures)
        keep = plain[numbers[ys, xs] - 1] & (classes >= 0)
        ys, xs, found, classes = ys[keep], xs[keep], found[keep], classes[keep]
        u, v, size = xs + offsets[classes, 0], ys + offsets[classes, 1], sizes[classes]
        cell = (u // 2) % size + ((v // 2) % size) * size + starts[classes]
        expected = cell * 4 + (v & 1) * 2 + (u & 1)
        assert found.size > 10000
        # 91.4% of blends and 98.2% of 3-way blends on this map.
        assert np.mean(expected == found) > share


def test_optimize_drops_unused_and_duplicate_descriptions():
    def description(tile):
        return BlendDescription(tile, bytes((1, 0, 0, 0)), 0, False, DEFAULT_EDGE)

    a, b, c = (description(n) for n in (4, 8, 4))
    blends = np.array([[0, 3, 2]])
    three = np.array([[1, 0, 0]])
    kept, new_blends, new_three = optimized_blends([a, b, c], blends, three)
    assert kept == [a, b]
    assert new_blends.tolist() == [[0, 1, 2]] and new_three.tolist() == [[1, 0, 0]]


def test_an_auto_edge_saves_and_undoes_byte_identically_on_a_real_map():
    document = MapDocument.from_bytes(FIXTURE.read_bytes())
    untouched = document.to_bytes(compress=False)
    blend = document.map.blend_tile_data
    count = len(blend.blend_descriptions)
    edit = run(document, auto_edge_in, (240, 210), whole_map=True)
    assert edit is not None and edit.descriptions
    apply(document, edit)
    assert len(blend.blend_descriptions) == count + len(edit.descriptions)
    reopened = parse_map(io.BytesIO(document.to_bytes(compress=False)))
    for layer, values in edit.layers.items():
        stored = layer_array(reopened.blend_tile_data, layer)
        rows, columns = values.shape
        assert np.array_equal(stored[edit.y0 : edit.y0 + rows, edit.x0 : edit.x0 + columns], values)
    document.stack.undo()
    assert document.to_bytes(compress=False) == untouched
