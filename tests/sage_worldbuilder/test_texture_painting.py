"""Texture painting: the texture table, which texture a cell shows, painting a block, flood fill,
and the undoable paint on a real map."""

import io
from pathlib import Path

import pytest

from sage_map.assets.blend_tile_data import BlendTileTexture
from sage_map.map import Map, parse_map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import blank_blend_tile_data, blank_height_map  # noqa: E402
from sage_worldbuilder.terrain.blending import flood_fill, single_edge  # noqa: E402
from sage_worldbuilder.terrain.cells import TileLayer, layer_array  # noqa: E402
from sage_worldbuilder.terrain.edits import PaintBlends, PaintTiles  # noqa: E402
from sage_worldbuilder.terrain.textures import (  # noqa: E402
    TEXTURE_CELL_LIMIT,
    TextureCapacityError,
    paint_texture_block,
    planned_texture,
    texture_classes,
    texture_index,
    texture_tiles,
)

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


def small_map(width=16, height=12):
    map = Map()
    map.height_map_data = blank_height_map(width, height, 2, 0)
    map.blend_tile_data = blank_blend_tile_data(width, height, "Grass")
    return map


def layers_of(document):
    return {layer: document.cells(layer) for layer in TileLayer}


def test_the_texture_table_grows_by_cell_runs_up_to_the_limit():
    blend = small_map().blend_tile_data
    assert texture_index(blend, "GRASS") == 0 and texture_index(blend, "Rock") is None
    rock = planned_texture(blend, "Rock", 2)
    assert (rock.cell_start, rock.cell_count, rock.cell_size) == (16, 4, 2)
    blend.texture_cell_count = TEXTURE_CELL_LIMIT - 3
    with pytest.raises(TextureCapacityError):
        planned_texture(blend, "Rock", 2)


def test_cells_show_the_texture_their_tile_falls_in():
    textures = [BlendTileTexture(0, 16, 4, 0, "A"), BlendTileTexture(16, 4, 2, 0, "B")]
    tiles = np.array([[0, 63, 64, 79, 80]])
    assert texture_classes(tiles, textures).tolist() == [[0, 0, 1, 1, -1]]


def test_a_painted_block_tiles_by_map_coordinates_and_clears_blends():
    document = MapDocument(small_map())
    document.map.blend_tile_data.blends[5][4] = 7
    layers = layers_of(document)
    rock = BlendTileTexture(16, 4, 2, 0, "Rock")
    painted = paint_texture_block(layers, (4, 3, 7, 6), rock)
    assert np.array_equal(painted[TileLayer.TILES], texture_tiles(rock, 4, 3, 7, 6))
    # Cell (4, 3): texture cell column (4 // 2) % 2 = 0, row (3 // 2) % 2 = 1, quadrant x0 y1.
    assert painted[TileLayer.TILES][0, 0] == ((16 + 1 * 2 + 0) << 2) | 2
    assert painted[TileLayer.BLENDS][1, 1] == 0 and list(painted) == [
        TileLayer.TILES,
        TileLayer.BLENDS,
    ]
    grass = document.map.blend_tile_data.textures[0]
    assert paint_texture_block(layers, (0, 0, 4, 4), grass) is None


def split_by_rock():
    """A 16 x 12 grass map split by a rock strip at x 6-7, with grass blended onto the strip's
    left cells and rock onto grass cell (2, 2)."""
    document = MapDocument(small_map())
    blend = document.map.blend_tile_data
    rock = planned_texture(blend, "Rock", 2)
    strip = paint_texture_block(layers_of(document), (6, 0, 8, 12), rock)
    document.execute(PaintTiles(6, 0, strip, rock))
    for y in range(12):
        edit = single_edge(
            layers_of(document), blend.textures, blend.blend_descriptions, (6, y), (5, y)
        )
        document.execute(PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions))
    edit = single_edge(
        layers_of(document), blend.textures, blend.blend_descriptions, (2, 2), (3, 2), rock
    )
    document.execute(PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions))
    return document


def shown(document, x, y):
    """The texture the blend on cell `(x, y)` shows."""
    blend = document.map.blend_tile_data
    number = document.cells(TileLayer.BLENDS)[y, x]
    tile = blend.blend_descriptions[number - 1].secondary_texture_tile
    return blend.textures[texture_classes(np.array([tile]), blend.textures)[0]].name


def run_edit(document, edit):
    document.execute(
        PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions, "Flood Fill", edit.texture)
    )


def test_flood_fill_keeps_blends_and_turns_the_blends_beside_it():
    document = split_by_rock()
    blend = document.map.blend_tile_data
    sand = planned_texture(blend, "Sand", 4)
    edit = flood_fill(layers_of(document), blend.textures, blend.blend_descriptions, (1, 1), sand)
    assert edit.texture is sand
    run_edit(document, edit)
    classes = texture_classes(document.cells(TileLayer.TILES), blend.textures)
    assert (classes[0:11, 0:6] == 2).all(), "the area, short of the map's last row"
    assert (classes[11, 0:6] == 0).all() and (classes[:, 6:8] == 1).all()
    assert shown(document, 2, 2) == "Rock", "a filled cell keeps its blend"
    assert all(shown(document, 6, y) == "Sand" for y in range(11))
    assert shown(document, 6, 11) == "Grass", "not beside a filled cell"
    assert (
        flood_fill(layers_of(document), blend.textures, blend.blend_descriptions, (1, 1), sand)
        is None
    )


def test_flood_fill_replace_all_fills_every_cell_of_the_texture():
    document = split_by_rock()
    blend = document.map.blend_tile_data
    sand = planned_texture(blend, "Sand", 4)
    edit = flood_fill(
        layers_of(document),
        blend.textures,
        blend.blend_descriptions,
        (1, 1),
        sand,
        replace_all=True,
    )
    run_edit(document, edit)
    classes = texture_classes(document.cells(TileLayer.TILES), blend.textures)
    assert (classes[:, :6] == 2).all() and (classes[:, 8:] == 2).all()
    assert all(shown(document, 6, y) == "Sand" for y in range(12))


def test_a_new_texture_joins_the_table_with_its_stroke_and_leaves_on_undo():
    original = FIXTURE.read_bytes()
    document = MapDocument.from_bytes(original)
    untouched = document.to_bytes(compress=False)
    blend = document.map.blend_tile_data
    count = len(blend.textures)
    new = planned_texture(blend, "PaintedTestTexture", 4)
    layers = layers_of(document)
    first = PaintTiles(100, 100, paint_texture_block(layers, (100, 100, 110, 104), new), new)
    document.execute(first)
    second = paint_texture_block(layers_of(document), (110, 100, 114, 104), new)
    document.execute(PaintTiles(110, 100, second))
    assert len(blend.textures) == count + 1
    assert document.stack.undo_label == "Paint Texture"

    reopened = parse_map(io.BytesIO(document.to_bytes(compress=False)))
    classes = texture_classes(
        layer_array(reopened.blend_tile_data, TileLayer.TILES), reopened.blend_tile_data.textures
    )
    assert (classes[100:104, 100:114] == count).all()
    assert not layer_array(reopened.blend_tile_data, TileLayer.BLENDS)[100:104, 100:114].any()

    first.closed = True
    document.stack.undo()
    assert len(blend.textures) == count
    assert document.to_bytes(compress=False) == untouched


def test_the_palette_groups_by_type_and_region_whatever_the_case():
    from types import SimpleNamespace  # noqa: PLC0415

    from sage_worldbuilder.texture_colors import texture_palette  # noqa: PLC0415

    def terrain(kind_and_region):
        return SimpleNamespace(Texture="x.tga", Class=kind_and_region)

    game = SimpleNamespace(
        terrains={
            "GrassB": terrain("Type Grass NEXT Region Fangorn_Forest"),
            "GrassA": terrain("Type Grass NEXT Region FANGORN_FOREST"),
            "Plain": terrain("Type Grass"),
            "Loose": terrain(""),
            "NoFile": SimpleNamespace(Texture=None, Class="Type Rock"),
        }
    )
    assert texture_palette(game) == {
        "Grass": {"": ["Plain"], "Fangorn_Forest": ["GrassA", "GrassB"]},
        "Other": {"": ["Loose"]},
    }
    assert texture_palette(SimpleNamespace()) == {}
