"""Whole-map texture edits: Optimize tiles and blend tiles (a small map and a real one), Remove
Cliff Tex Mapping, Remove all texture blends, and the stretched tile test."""

from pathlib import Path

import pytest

from sage_map.assets.blend_tile_data import CliffTextureMapping
from sage_map.map import Map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import blank_blend_tile_data, blank_height_map  # noqa: E402
from sage_worldbuilder.terrain.blending import auto_edge_out, description_side  # noqa: E402
from sage_worldbuilder.terrain.cells import TileLayer  # noqa: E402
from sage_worldbuilder.terrain.edits import (  # noqa: E402
    PaintBlends,
    PaintTiles,
    ReplaceTerrainTables,
)
from sage_worldbuilder.terrain.sizing import (  # noqa: E402
    blends_removed,
    cliff_mappings_removed,
    optimized_tiles,
    stretched_cells,
    unblended_cells,
)
from sage_worldbuilder.terrain.textures import (  # noqa: E402
    paint_texture_block,
    planned_texture,
    texture_classes,
)

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


def layers_of(document):
    return {layer: document.cells(layer) for layer in TileLayer}


def run(document, command):
    document.execute(command)
    command.closed = True


def apply_edit(document, edit, label="Edit Textures"):
    run(
        document,
        ReplaceTerrainTables(
            edit.patches, edit.textures, edit.descriptions, edit.cliff_mappings, label
        ),
    )


def cell_names(document):
    blend = document.map.blend_tile_data
    classes = texture_classes(document.cells(TileLayer.TILES), blend.textures)
    names = np.array([texture.name for texture in blend.textures], dtype=object)
    return names[classes]


def blend_summary(document):
    """Per blended cell: the side its blend comes from and the texture it shows."""
    blend = document.map.blend_tile_data
    blends = document.cells(TileLayer.BLENDS)
    summary = {}
    for y, x in zip(*np.nonzero(blends), strict=True):
        description = blend.blend_descriptions[blends[y, x] - 1]
        shown = texture_classes(np.array([description.secondary_texture_tile]), blend.textures)[0]
        summary[(int(x), int(y))] = (description_side(description), blend.textures[shown].name)
    return summary


def edged_map_with_a_spare_texture():
    """A 20 x 16 grass map with an unused sand entry and an edged rock square."""
    map = Map()
    map.height_map_data = blank_height_map(20, 16, 2, 0)
    map.blend_tile_data = blank_blend_tile_data(20, 16, "Grass")
    document = MapDocument(map)
    blend = map.blend_tile_data
    sand = planned_texture(blend, "Sand", 4)
    run(
        document,
        PaintTiles(2, 2, paint_texture_block(layers_of(document), (2, 2, 4, 4), sand), sand),
    )
    grass = blend.textures[0]
    run(document, PaintTiles(2, 2, paint_texture_block(layers_of(document), (2, 2, 4, 4), grass)))
    rock = planned_texture(blend, "Rock", 2)
    run(
        document,
        PaintTiles(8, 6, paint_texture_block(layers_of(document), (8, 6, 12, 10), rock), rock),
    )
    edit = auto_edge_out(layers_of(document), blend.textures, blend.blend_descriptions, (9, 7))
    run(document, PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions))
    return document


def test_optimize_drops_unused_textures_and_keeps_every_cell_and_blend():
    document = edged_map_with_a_spare_texture()
    blend = document.map.blend_tile_data
    assert [t.name for t in blend.textures] == ["Grass", "Sand", "Rock"]
    before = document.to_bytes(compress=False)
    names, blends = cell_names(document), blend_summary(document)
    edit = optimized_tiles(
        layers_of(document), blend.textures, blend.blend_descriptions, blend.cliff_texture_mappings
    )
    apply_edit(document, edit, "Optimize Tiles and Blend Tiles")
    assert [(t.name, t.cell_start) for t in blend.textures] == [("Grass", 0), ("Rock", 16)]
    assert blend.texture_cell_count == 20
    assert np.array_equal(cell_names(document), names)
    assert blend_summary(document) == blends
    assert len(blend.blend_descriptions) <= len(blends)
    document.stack.undo()
    assert document.to_bytes(compress=False) == before


def test_optimize_keeps_a_real_maps_cells_and_undoes_byte_identically():
    document = MapDocument.from_bytes(FIXTURE.read_bytes())
    blend = document.map.blend_tile_data
    before = document.to_bytes(compress=False)
    names = cell_names(document)
    edit = optimized_tiles(
        layers_of(document), blend.textures, blend.blend_descriptions, blend.cliff_texture_mappings
    )
    apply_edit(document, edit)
    assert np.array_equal(cell_names(document), names)
    reopened = MapDocument.from_bytes(document.to_bytes(compress=False))
    assert np.array_equal(cell_names(reopened), names)
    document.stack.undo()
    assert document.to_bytes(compress=False) == before


def test_remove_cliff_mapping_and_all_blends():
    document = edged_map_with_a_spare_texture()
    blend = document.map.blend_tile_data
    blend.cliff_texture_mappings.append(
        CliffTextureMapping(64, (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), 0)
    )
    run(document, PaintBlends(3, 3, {TileLayer.CLIFF_TEXTURES: np.array([[1]])}))
    before = document.to_bytes(compress=False)

    apply_edit(document, cliff_mappings_removed(layers_of(document), blend.cliff_texture_mappings))
    assert blend.cliff_texture_mappings == []
    assert not document.cells(TileLayer.CLIFF_TEXTURES).any()
    document.stack.undo()
    assert document.to_bytes(compress=False) == before

    count = len(blend.blend_descriptions)
    apply_edit(document, blends_removed(layers_of(document)))
    assert not document.cells(TileLayer.BLENDS).any()
    assert len(blend.blend_descriptions) == count, "the descriptions stay"
    assert blends_removed(layers_of(document)) is None
    document.stack.undo()
    assert document.to_bytes(compress=False) == before


def test_unblended_cells_are_the_edges_without_a_blend():
    document = edged_map_with_a_spare_texture()
    blend = document.map.blend_tile_data
    edged = unblended_cells(layers_of(document), blend.textures, 2)
    assert not edged.any(), "every edge of the rock square is blended"

    map = Map()
    map.height_map_data = blank_height_map(20, 16, 2, 0)
    map.blend_tile_data = blank_blend_tile_data(20, 16, "Grass")
    plain = MapDocument(map)
    rock = planned_texture(map.blend_tile_data, "Rock", 2)
    run(
        plain,
        PaintTiles(8, 6, paint_texture_block(layers_of(plain), (8, 6, 12, 10), rock), rock),
    )
    marked = unblended_cells(layers_of(plain), plain.map.blend_tile_data.textures, 2)
    assert marked[6, 8] and marked[6, 7], "both sides of an unblended edge"
    assert not marked[7, 9], "inside the rock"
    assert not marked[:2].any() and not marked[:, :2].any(), "the border is left out"


def test_stretched_cells_are_the_steep_ones():
    heights = np.zeros((12, 12), dtype=np.int64)
    heights[:, 6:] = 2560  # a 100-foot step between columns 5 and 6
    stretched = stretched_cells(heights, 45.0)
    assert stretched[4, 5] and stretched[4, 4]
    assert not stretched[4, 1] and not stretched[4, 9]
    assert not stretched_cells(heights, 89.0)[4, 5]
