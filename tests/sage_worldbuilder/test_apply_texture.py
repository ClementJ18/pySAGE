"""Apply texture to tiles: the corner slopes and heights, the playable area, the saturation roll,
and a new texture tiled from the map's origin."""

import pytest

from sage_map.map import Map
from sage_worldbuilder import MapDocument

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import blank_blend_tile_data, blank_height_map  # noqa: E402
from sage_worldbuilder.terrain.apply_texture import (  # noqa: E402
    ApplyTextureOptions,
    apply_texture,
    qualifying_samples,
)
from sage_worldbuilder.terrain.cells import TileLayer  # noqa: E402
from sage_worldbuilder.terrain.textures import (  # noqa: E402
    planned_texture,
    texture_classes,
    texture_tiles,
)

# Stored height units in 100 feet.
HUNDRED_FEET = 2560


def grass_map(heights=None):
    """A 20 x 16 grass map with a border of 2."""
    map = Map()
    map.height_map_data = blank_height_map(20, 16, 2, 0)
    map.blend_tile_data = blank_blend_tile_data(20, 16, "Grass")
    document = MapDocument(map)
    if heights is not None:
        from sage_worldbuilder.terrain.edits import PatchHeights  # noqa: PLC0415

        document.execute(PatchHeights(0, 0, heights))
    return document


def layers_of(document):
    return {layer: document.cells(layer) for layer in TileLayer}


def test_a_samples_slope_is_measured_across_its_neighbours_and_the_rim_is_flat():
    heights = np.tile(np.arange(10, dtype=np.int64) * (HUNDRED_FEET // 2), (8, 1))
    # 100 feet up over the 20 feet between a sample's neighbours: about 78.7 degrees.
    # A cell qualifies only when both its slopes do: this ramp is flat along y.
    assert not qualifying_samples(heights, (70, 80), (0, 1000)).any()
    steep = qualifying_samples(heights, (0, 80), (0, 1000))
    assert steep.all()
    flat = qualifying_samples(heights, (0, 10), (0, 1000))
    assert flat[:, 0].all() and flat[:, 8:].all(), "the rim counts as flat"
    assert not flat[1:6, 1:7].any()
    assert not qualifying_samples(heights, (0, 89), (0, 50))[3, 3], "above the heights"


def test_the_playable_cells_all_take_the_texture_at_full_saturation():
    document = grass_map()
    blend = document.map.blend_tile_data
    rock = planned_texture(blend, "Rock", 2)
    x0, y0, painted = apply_texture(
        layers_of(document),
        document.terrain.heights,
        blend.textures,
        rock,
        2,
        ApplyTextureOptions(),
    )
    assert (x0, y0) == (2, 2)
    tiles = painted[TileLayer.TILES]
    assert tiles.shape == (12, 16)
    assert np.array_equal(tiles, texture_tiles(rock, 2, 2, 18, 14)), "tiled from the map origin"


def test_saturation_and_heights_limit_the_cells_painted():
    heights = np.zeros((16, 20), dtype=np.int64)
    heights[:, 10:] = 3 * HUNDRED_FEET
    document = grass_map(heights)
    blend = document.map.blend_tile_data
    rock = planned_texture(blend, "Rock", 2)
    low = ApplyTextureOptions(use_heights=True, heights=(0, 100))
    x0, y0, painted = apply_texture(
        layers_of(document), document.terrain.heights, blend.textures, rock, 2, low
    )
    classes = texture_classes(painted[TileLayer.TILES], [*blend.textures, rock])
    # Cells whose corners all stay under 100 feet: x up to 8, since cell 9's right corner is high.
    assert (classes[:, : 9 - x0] == 1).all() and (classes[:, 9 - x0 :] == 0).all()

    half = ApplyTextureOptions(use_saturation=True, saturation=50)
    x0, y0, painted = apply_texture(
        layers_of(grass_map()),
        np.zeros((16, 20), dtype=np.int64),
        blend.textures,
        rock,
        2,
        half,
        np.random.default_rng(7),
    )
    share = np.mean(texture_classes(painted[TileLayer.TILES], [*blend.textures, rock]) == 1)
    assert 0.3 < share < 0.7
    none = ApplyTextureOptions(use_slopes=True, slopes=(30, 60))
    assert (
        apply_texture(layers_of(document), document.terrain.heights, blend.textures, rock, 2, none)
        is None
    )
