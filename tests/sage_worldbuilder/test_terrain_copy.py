"""Terrain Copy: where a flipped and turned selection lands, how its blends turn with it, and a
paste of heights, texture, blends and cell attributes that undoes byte-identically."""

import itertools

import pytest

from sage_map.assets.blend_tile_data import BlendDescription
from sage_map.map import Map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import blank_blend_tile_data, blank_height_map  # noqa: E402
from sage_worldbuilder.terrain.blending import auto_edge_out, description_side  # noqa: E402
from sage_worldbuilder.terrain.cells import CellLayer, TileLayer  # noqa: E402
from sage_worldbuilder.terrain.copy import (  # noqa: E402
    CopyParts,
    CopyTransform,
    paste_terrain,
    selection_bounds,
    turned_blend,
)
from sage_worldbuilder.terrain.edits import (  # noqa: E402
    CopyTerrain,
    PaintBlends,
    PaintTiles,
    PatchCells,
    PatchHeights,
)
from sage_worldbuilder.terrain.textures import (  # noqa: E402
    paint_texture_block,
    planned_texture,
    texture_classes,
    texture_tiles,
    tiling_offset,
)

ALL_LAYERS = (*TileLayer, *CellLayer)


def layers_of(document):
    return {layer: document.cells(layer) for layer in ALL_LAYERS}


def run(document, command):
    document.execute(command)
    command.closed = True


def test_turned_blends_keep_pointing_at_their_neighbour():
    for byte, flags in itertools.product(range(4), (0, 1)):
        raw = [0, 0, 0, 0]
        raw[byte] = 1
        description = BlendDescription(0, bytes(raw), flags, False, 0xFFFFFFFF)
        dx, dy = description_side(description)
        for turns, down, across in itertools.product(range(4), (False, True), (False, True)):
            ex, ey = (-dx if across else dx), (-dy if down else dy)
            for _ in range(turns):
                ex, ey = ey, -ex
            turned = turned_blend(description, turns, down, across)
            assert description_side(turned) == (ex, ey), (raw, flags, turns, down, across)


def test_a_turn_that_sets_the_side_drops_flags_bit_1():
    side = BlendDescription(0, bytes((1, 0, 0, 0)), 3, False, 0xFFFFFFFF)
    assert turned_blend(side, 0, False, False).flags == 3
    assert turned_blend(side, 2, False, False).flags == 0


def test_a_quarter_turn_lands_each_cell_clockwise():
    selection = np.zeros((20, 20), dtype=bool)
    selection[5, 3:6] = True
    bounds = selection_bounds(selection)
    assert bounds == (3, 5, 6, 6)
    transform = CopyTransform.centred(bounds, (10, 10), turns=1)
    x0, y0, x1, y1 = transform.target_bounds(bounds, selection.shape)
    ys, xs = np.mgrid[y0:y1, x0:x1]
    sources = {
        (int(x), int(y)): tuple(int(v) for v in transform.cell_source(x, y))
        for x, y in zip(xs.ravel(), ys.ravel(), strict=True)
    }
    # The row's west end lands north of its east end (y up).
    assert sources[(10, 10)] == (3, 5) and sources[(10, 8)] == (5, 5)


def test_every_flip_and_turn_lands_each_selected_cell_once():
    selection = np.zeros((30, 30), dtype=bool)
    selection[4:9, 6:13] = True
    selection[6, 6] = False
    bounds = selection_bounds(selection)
    for turns, down, across in itertools.product(range(4), (False, True), (False, True)):
        transform = CopyTransform.centred(bounds, (15, 16), turns, down, across)
        x0, y0, x1, y1 = transform.target_bounds(bounds, selection.shape)
        ys, xs = np.mgrid[y0:y1, x0:x1]
        sx, sy = transform.cell_source(xs, ys)
        inside = (sx >= 0) & (sx < 30) & (sy >= 0) & (sy < 30)
        landed = sorted(zip(sx[inside].tolist(), sy[inside].tolist(), strict=True))
        chosen = [cell for cell in landed if selection[cell[1], cell[0]]]
        assert len(chosen) == int(selection.sum()) == len(set(chosen)), (turns, down, across)


def edged_map():
    """A 24 x 20 grass map with a 3 x 2 rock patch at cells x 4-6, y 4-5, edged outward, an
    impassable cell at (3, 3) and a raised height sample at (4, 4)."""
    map = Map()
    map.height_map_data = blank_height_map(24, 20, 2, 0)
    map.blend_tile_data = blank_blend_tile_data(24, 20, "Grass")
    document = MapDocument(map)
    blend = map.blend_tile_data
    rock = planned_texture(blend, "Rock", 2)
    run(
        document,
        PaintTiles(4, 4, paint_texture_block(layers_of(document), (4, 4, 7, 6), rock), rock),
    )
    edit = auto_edge_out(layers_of(document), blend.textures, blend.blend_descriptions, (5, 5))
    run(document, PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions))
    run(document, PatchCells(3, 3, {CellLayer.IMPASSABLE: np.array([[True]])}))
    run(document, PatchHeights(4, 4, np.array([[500]])))
    return document


def test_a_paste_copies_heights_texture_blends_and_passability():
    document = edged_map()
    blend = document.map.blend_tile_data
    selection = np.zeros((20, 24), dtype=bool)
    selection[3:7, 3:8] = True
    bounds = selection_bounds(selection)
    transform = CopyTransform.centred(bounds, (15, 12))
    ox, oy = transform.origin
    dx, dy = 15 + ox, 12 + oy  # a paste without turns only moves the cells
    paste = paste_terrain(
        document.terrain.heights,
        layers_of(document),
        blend.textures,
        blend.blend_descriptions,
        selection,
        transform,
        CopyParts(),
    )
    before = document.to_bytes(compress=False)
    old = layers_of(document)
    old_classes = texture_classes(old[TileLayer.TILES], blend.textures)
    run(document, CopyTerrain(paste.patches, paste.descriptions))
    new = layers_of(document)

    assert document.terrain.heights[4 + dy, 4 + dx] == 500
    assert new[CellLayer.IMPASSABLE][3 + dy, 3 + dx]
    classes = texture_classes(new[TileLayer.TILES], blend.textures)
    assert np.array_equal(classes[3 + dy : 7 + dy, 3 + dx : 8 + dx], old_classes[3:7, 3:8])
    rock = blend.textures[1]
    x, y = 5 + dx, 4 + dy
    assert (
        new[TileLayer.TILES][y, x]
        == texture_tiles(rock, x, y, x + 1, y + 1, tiling_offset(old[TileLayer.TILES], rock))[0, 0]
    ), "the texture is tiled anew where it lands"
    for sy, sx in zip(*np.nonzero(old[TileLayer.BLENDS][3:7, 3:8]), strict=True):
        source = blend.blend_descriptions[old[TileLayer.BLENDS][3 + sy, 3 + sx] - 1]
        landed = blend.blend_descriptions[new[TileLayer.BLENDS][3 + sy + dy, 3 + sx + dx] - 1]
        assert description_side(landed) == description_side(source)
        assert texture_classes(np.array([landed.secondary_texture_tile]), blend.textures)[0] == 1

    document.stack.undo()
    assert document.to_bytes(compress=False) == before


def test_parts_left_out_are_not_copied_and_a_paste_onto_itself_changes_nothing():
    document = edged_map()
    blend = document.map.blend_tile_data
    selection = np.zeros((20, 24), dtype=bool)
    selection[3:7, 3:8] = True
    bounds = selection_bounds(selection)
    arguments = (document.terrain.heights, layers_of(document), blend.textures)
    here = CopyTransform.centred(bounds, ((3 + 8) // 2, (3 + 7) // 2))
    assert paste_terrain(*arguments, blend.blend_descriptions, selection, here, CopyParts()) is None
    away = CopyTransform.centred(bounds, (15, 12))
    only_heights = paste_terrain(
        *arguments,
        blend.blend_descriptions,
        selection,
        away,
        CopyParts(texture=False, passability=False),
    )
    assert [patch[0] for patch in only_heights.patches] == [None]
    assert (
        paste_terrain(
            *arguments, blend.blend_descriptions, np.zeros((20, 24), dtype=bool), away, CopyParts()
        )
        is None
    )
