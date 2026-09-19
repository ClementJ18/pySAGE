"""The height brushes, the undoable height patch, contours and the brush settings."""

import io
from pathlib import Path

import pytest

from sage_map.assets.height_map import HeightMapBorder, HeightMapData
from sage_map.map import Map, parse_map
from sage_worldbuilder import Change, ChangeKind, MapDocument
from sage_worldbuilder.brush_options import BrushOptions
from sage_worldbuilder.changes import Region
from sage_worldbuilder.settings import Settings
from sage_worldbuilder.viewport import ViewOptions

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.render.topdown import contour_levels, contour_mask  # noqa: E402
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, TerrainGrid  # noqa: E402
from sage_worldbuilder.terrain.brushes import (  # noqa: E402
    BrushKind,
    apply_brush,
    brush_center,
    brush_weights,
)
from sage_worldbuilder.terrain.edits import PatchHeights  # noqa: E402


def flat_map(width: int = 12, height: int = 10, value: int = 256) -> Map:
    map = Map()
    map.height_map_data = HeightMapData(
        version=5,
        width=width,
        height=height,
        border_width=0,
        borders=[HeightMapBorder((0, 0), (width, height))],
        area=width * height,
        min_height=value,
        max_height=value,
        elevations=[[value] * width for _ in range(height)],
        start_pos=0,
        end_pos=0,
    )
    return map


def options(**changes) -> BrushOptions:
    values = {"width": 1, "feather": 0, "height": 16.0, "amount": 1.0, "radius": 1, "rate": 10}
    values.update(changes)
    return BrushOptions(**values)


def test_odd_brushes_centre_on_a_sample_and_even_ones_on_a_corner():
    assert brush_center(3.4, 5.6, 3) == (3.0, 6.0)
    assert brush_center(3.4, 5.6, 2) == (3.5, 5.5)


def test_brush_weights_are_round_with_a_linear_feather():
    x0, y0, weights = brush_weights((5.0, 5.0), 5, 0, (20, 20))
    assert (x0, y0, weights.shape) == (3, 3, (5, 5))
    assert weights[0, 0] == 0.0 and weights[0, 2] == 1.0 and weights[2, 2] == 1.0
    _, _, even = brush_weights((5.5, 5.5), 2, 0, (20, 20))
    assert int(even.sum()) == 4
    x0, _, feathered = brush_weights((5.0, 5.0), 1, 2, (20, 20))
    row = feathered[feathered.shape[0] // 2]
    assert x0 == 3 and row.tolist() == [0.25, 0.75, 1.0, 0.75, 0.25]


def test_brush_weights_clip_to_the_grid():
    x0, y0, weights = brush_weights((0.0, 0.0), 3, 0, (4, 4))
    assert (x0, y0, weights.shape) == (0, 0, (2, 2))
    assert brush_weights((-10.0, -10.0), 3, 0, (4, 4)) is None


def test_height_brush_sets_feet_and_mound_and_dig_step():
    heights = np.full((10, 12), 256, dtype=np.uint16)
    patch = apply_brush(heights, BrushKind.SET, (4.0, 3.0), options(height=32.0))
    expected = round(32.0 / FEET_PER_HEIGHT_UNIT)
    assert (patch.x0, patch.y0, patch.values.tolist()) == (4, 3, [[expected]])
    raised = apply_brush(heights, BrushKind.RAISE, (4.0, 3.0), options(amount=1.0))
    assert raised.values[0, 0] == 256 + 26
    lowered = apply_brush(heights, BrushKind.LOWER, (4.0, 3.0), options(amount=100.0))
    assert lowered.values[0, 0] == 0
    assert apply_brush(heights, BrushKind.SET, (4.0, 3.0), options(height=10.0)) is None


def test_smooth_pulls_a_spike_towards_its_neighbours():
    heights = np.full((9, 9), 100, dtype=np.uint16)
    heights[4, 4] = 1000
    patch = apply_brush(heights, BrushKind.SMOOTH, (4.0, 4.0), options(width=1, rate=10))
    assert patch.values[0, 0] == 200
    half = apply_brush(heights, BrushKind.SMOOTH, (4.0, 4.0), options(width=1, rate=5))
    assert half.values[0, 0] == 600


def test_patch_writes_the_saved_rows_and_the_array_and_a_stroke_undoes_at_once():
    map = flat_map()
    document = MapDocument(map)
    grid = document.terrain
    heard = []
    document.subscribe(heard.append)

    first = PatchHeights(2, 1, np.array([[300, 301]], dtype=np.uint16), "Mound")
    document.execute(first)
    document.execute(PatchHeights(5, 7, np.array([[400]], dtype=np.uint16), "Mound"))
    assert document.terrain is grid, "a regional change patches the array in place"
    assert grid.heights[1, 2] == 300 and grid.heights[7, 5] == 400
    # Saved rows run top first: sample row 1 of 10 is saved row 8.
    assert map.height_map_data.elevations[8][2:4] == [300, 301]
    assert heard[-1] == Change(ChangeKind.TERRAIN, Region(5, 7, 6, 8))
    assert document.stack.undo_label == "Mound"

    first.closed = True
    document.stack.undo()
    assert grid.heights[1, 2] == 256 and grid.heights[7, 5] == 256
    assert map.height_map_data.elevations[8][2] == 256
    assert heard[-1] == Change(ChangeKind.TERRAIN, Region(2, 1, 6, 8))
    assert not document.stack.can_undo
    document.stack.redo()
    assert map.height_map_data.elevations[2][5] == 400


def test_a_closed_stroke_does_not_merge_the_next():
    document = MapDocument(flat_map())
    first = PatchHeights(0, 0, np.array([[1]], dtype=np.uint16))
    document.execute(first)
    first.closed = True
    document.execute(PatchHeights(1, 0, np.array([[2]], dtype=np.uint16)))
    document.stack.undo()
    assert document.terrain.heights[0, 0] == 1 and document.terrain.heights[0, 1] == 256


def test_contours_follow_level_crossings():
    heights = np.tile(np.arange(10, dtype=np.uint16) * 10, (4, 1))
    levels = contour_levels(0.0, 90.0, 2)
    assert levels.tolist() == [30.0, 60.0]
    mask = contour_mask(heights, levels)
    assert mask[0].tolist() == [False, False, True, False, False, True, False, False, False, False]
    assert contour_mask(heights, levels, width=2)[0].sum() == 6
    assert not contour_mask(heights, contour_levels(5.0, 5.0, 3)).any()


def test_brush_and_contour_settings_round_trip():
    settings = Settings()
    settings.brush = BrushOptions(width=9, feather=4, height=40.5, amount=2.0, radius=3, rate=2)
    settings.view.show_contours = True
    settings.view.contours.count = 25
    loaded = Settings.from_dict(settings.to_dict())
    assert loaded.brush == settings.brush
    assert loaded.view.show_contours and loaded.view.contours.count == 25
    forgiven = BrushOptions.from_dict({"width": 0, "rate": "x", "height": True})
    assert forgiven == BrushOptions(width=1)
    assert ViewOptions.from_dict({"contours": {"count": 0, "width": 3}}).contours.width == 3


FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


def test_a_one_cell_map_draws_without_error():
    from sage_worldbuilder.render.topdown import terrain_image  # noqa: PLC0415

    assert terrain_image(np.array([[500]], dtype=np.uint16)).shape == (1, 1, 4)
    assert terrain_image(np.array([[1, 2, 3]], dtype=np.uint16)).shape == (1, 3, 4)


def test_a_stroke_saves_and_an_undone_one_saves_byte_identically():
    original = FIXTURE.read_bytes()
    document = MapDocument.from_bytes(original)
    untouched = document.to_bytes(compress=False)
    grid = document.terrain
    assert grid.heights.shape == (420, 485)
    cell = (grid.width / 2, grid.height / 2)
    patch = apply_brush(
        grid.heights, BrushKind.RAISE, cell, options(width=7, feather=3, amount=5.0)
    )
    assert patch.values.shape == (13, 13)
    document.execute(PatchHeights(patch.x0, patch.y0, patch.values, "Mound"))

    saved = parse_map(io.BytesIO(document.to_bytes(compress=False)))
    reread = TerrainGrid.from_height_map(saved.height_map_data)
    assert np.array_equal(reread.heights, document.terrain.heights)
    assert not np.array_equal(
        reread.heights,
        TerrainGrid.from_height_map(parse_map(io.BytesIO(original)).height_map_data).heights,
    )

    document.stack.undo()
    assert document.to_bytes(compress=False) == untouched
