"""The cell attribute layers: their orientation, painting them, the undoable patch and saving."""

import io
from pathlib import Path

import pytest

from sage_map.assets.blend_tile_data import TileFlammability
from sage_map.map import Map, parse_map
from sage_worldbuilder import Change, ChangeKind, MapDocument
from sage_worldbuilder.brush_options import PaintMode, PaintOptions, Passability
from sage_worldbuilder.changes import Region
from sage_worldbuilder.settings import Settings

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.terrain.cells import (  # noqa: E402
    CellLayer,
    layer_array,
    paint_cells,
    paint_values,
    square_block,
    write_layer,
)
from sage_worldbuilder.terrain.edits import PatchCells  # noqa: E402

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


class Blend:
    """The attribute layers of a `BlendTileData`, stored `[x][y]` with y counting up."""

    def __init__(self, width: int = 6, height: int = 4) -> None:
        self.impassability = [[False] * height for _ in range(width)]
        self.impassability_to_players = [[False] * height for _ in range(width)]
        self.extra_passability = [[False] * height for _ in range(width)]
        self.passage_widths = [[False] * height for _ in range(width)]
        self.taintability = None
        self.visibility = [[True] * height for _ in range(width)]
        self.flammability = [[TileFlammability.FIRE_RESISTANT] * height for _ in range(width)]


def test_layers_turn_x_y_lists_into_row_column_arrays():
    blend = Blend()
    blend.impassability[5][1] = True
    array = layer_array(blend, CellLayer.IMPASSABLE)
    assert array.shape == (4, 6) and array.dtype == bool
    assert array[1, 5] and array.sum() == 1
    assert layer_array(blend, CellLayer.TAINTABLE) is None
    assert layer_array(blend, CellLayer.FLAMMABILITY).dtype == np.uint8

    write_layer(blend, CellLayer.FLAMMABILITY, 2, 1, np.array([[1, 2]], dtype=np.uint8))
    assert blend.flammability[3][1] is TileFlammability.HIGHLY_FLAMMABLE
    assert blend.flammability[2][2] is TileFlammability.FIRE_RESISTANT


def test_passability_paints_one_state_and_clears_the_others():
    values = paint_values(PaintOptions(passability=Passability.IMPASSABLE_TO_PLAYERS))
    assert values == {
        CellLayer.IMPASSABLE: 0,
        CellLayer.IMPASSABLE_TO_PLAYERS: 1,
        CellLayer.EXTRA_PASSABLE: 0,
    }
    assert paint_values(PaintOptions(mode=PaintMode.VISIBILITY, visible=False)) == {
        CellLayer.VISIBLE: 0
    }
    assert paint_values(PaintOptions(mode=PaintMode.TEXTURE)) == {}


def test_square_blocks_centre_like_the_brushes():
    assert square_block((5.2, 5.4), 3, (20, 20)) == (4, 4, 7, 7)
    assert square_block((5.2, 5.4), 2, (20, 20)) == (5, 5, 7, 7)
    assert square_block((5.2, 5.4), 1, (20, 20)) == (5, 5, 6, 6)
    assert square_block((0.0, 0.0), 5, (20, 20)) == (0, 0, 3, 3)
    assert square_block((-9.0, -9.0), 3, (20, 20)) is None


def test_paint_cells_skips_layers_it_would_not_change():
    blend = Blend()
    layers = {layer: layer_array(blend, layer) for layer in CellLayer}
    painted = paint_cells(layers, (2.0, 2.0), 3, paint_values(PaintOptions()))
    x0, y0, blocks = painted
    assert (x0, y0) == (1, 1)
    assert list(blocks) == [CellLayer.IMPASSABLE]
    assert blocks[CellLayer.IMPASSABLE].shape == (3, 3)
    passable = PaintOptions(passability=Passability.PASSABLE)
    assert paint_cells(layers, (2.0, 2.0), 3, paint_values(passable)) is None
    taint = paint_values(PaintOptions(mode=PaintMode.TAINTABILITY))
    assert paint_cells(layers, (2.0, 2.0), 3, taint) is None, "the map has no such layer"


def test_patch_cells_writes_the_map_and_undoes_a_stroke():
    map = Map()
    map.blend_tile_data = Blend()
    document = MapDocument(map)
    heard = []
    document.subscribe(heard.append)
    cached = document.cells(CellLayer.NARROW)
    first = PatchCells(1, 0, {CellLayer.NARROW: np.ones((2, 2), dtype=bool)}, "Paint")
    document.execute(first)
    document.execute(PatchCells(4, 3, {CellLayer.NARROW: np.ones((1, 1), dtype=bool)}, "Paint"))
    assert document.cells(CellLayer.NARROW) is cached and cached[1, 2]
    assert map.blend_tile_data.passage_widths[2][1] is True
    assert heard[-1] == Change(ChangeKind.TERRAIN, Region(4, 3, 5, 4))
    first.closed = True
    document.stack.undo()
    assert not cached.any() and not document.stack.can_undo
    assert map.blend_tile_data.passage_widths[4][3] is False


def test_painted_passability_saves_and_an_undone_paint_saves_byte_identically():
    document = MapDocument.from_bytes(FIXTURE.read_bytes())
    untouched = document.to_bytes(compress=False)
    layers = {layer: document.cells(layer) for layer in CellLayer}
    rows, columns = layers[CellLayer.IMPASSABLE].shape
    painted = paint_cells(
        layers, (columns / 2, rows / 2), 9, paint_values(PaintOptions(mode=PaintMode.PASSABILITY))
    )
    x0, y0, blocks = painted
    document.execute(PatchCells(x0, y0, blocks, "Paint Passability"))

    saved = parse_map(io.BytesIO(document.to_bytes(compress=False)))
    reread = layer_array(saved.blend_tile_data, CellLayer.IMPASSABLE)
    assert np.array_equal(reread, document.cells(CellLayer.IMPASSABLE))
    block = reread[y0 : y0 + 9, x0 : x0 + 9]
    assert block.shape == (9, 9) and block.all()

    document.stack.undo()
    assert document.to_bytes(compress=False) == untouched


def test_paint_options_round_trip_through_the_settings():
    settings = Settings()
    settings.paint = PaintOptions(
        mode=PaintMode.FLAMMABILITY, passability=Passability.EXTRA_PASSABLE, flammability=2
    )
    assert Settings.from_dict(settings.to_dict()).paint == settings.paint
    assert PaintOptions.from_dict({"mode": "Nope", "flammability": 9}) == PaintOptions()
