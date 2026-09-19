"""Roads draped over the terrain for the 3D view: following the ground, the lift off it, and the
surfaces the pieces are gathered into."""

import pytest

from sage_worldbuilder.road_mesh import road_pieces
from sage_worldbuilder.roads import (
    BRIDGE_END,
    BRIDGE_START,
    ROAD_END,
    ROAD_START,
    RoadStyle,
    road_segments,
)
from tests.sage_worldbuilder.test_road_mesh import road
from tests.sage_worldbuilder.test_roads import placed

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.render.road_surface import ROAD_LIFT, road_surfaces  # noqa: E402
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, TerrainGrid  # noqa: E402

WIDTH = 80.0


def style(name):
    """Dirt and Stone are roads with a texture of their own, Track a road the game data does not
    define, and Bridge a bridge."""
    textures = {"dirt": "TRDirtRoad.tga", "stone": "TRStone.tga"}
    return RoadStyle(
        WIDTH,
        bridge=name.lower() == "bridge",
        width_in_texture=0.9,
        texture=textures.get(name.lower()),
    )


def surfaces_of(objects, grid=None):
    return road_surfaces(road_pieces(road_segments(objects), style), style, grid)


def slope(rows=12, columns=12):
    """A grid rising one height unit per cell along x."""
    heights = np.tile(np.arange(columns, dtype=np.int32), (rows, 1))
    return TerrainGrid(heights, border=0)


def test_a_road_on_flat_ground_lies_one_lift_above_it():
    (surface,) = surfaces_of(road((0.0, 0.0), (200.0, 0.0)))
    assert surface.texture == "TRDirtRoad.tga"
    assert not surface.bridge
    assert surface.positions[:, 2] == pytest.approx(ROAD_LIFT)
    assert len(surface.positions) == len(surface.uvs)
    assert int(surface.indices.max()) == len(surface.positions) - 1


def test_a_road_follows_the_ground_under_it():
    grid = slope()
    (surface,) = surfaces_of(road((10.0, 50.0), (100.0, 50.0)), grid)
    xs, zs = surface.positions[:, 0], surface.positions[:, 2]
    assert zs == pytest.approx(xs / 10.0 * FEET_PER_HEIGHT_UNIT + ROAD_LIFT, abs=1e-4)


def test_a_piece_is_cut_up_across_and_along():
    (surface,) = surfaces_of(road((0.0, 0.0), (200.0, 0.0)))
    xs = sorted({round(float(x), 3) for x in surface.positions[:, 0]})
    ys = sorted({round(float(y), 3) for y in surface.positions[:, 1]})
    assert xs == pytest.approx(np.arange(0.0, 205.0, 5.0))
    assert len(ys) > 2 and min(ys) == pytest.approx(-WIDTH * 0.9 / 2)


def test_roads_are_gathered_by_the_texture_they_are_drawn_with():
    objects = (
        road((0.0, 0.0), (200.0, 0.0))
        + road((0.0, 400.0), (200.0, 400.0))
        + road((0.0, 800.0), (200.0, 800.0), type_name="Stone")
        + road((0.0, 1200.0), (200.0, 1200.0), type_name="Track")
        + [
            placed("Bridge", 0.0, 1600.0, BRIDGE_START),
            placed("Bridge", 200.0, 1600.0, BRIDGE_END),
        ]
    )
    surfaces = {(s.texture, s.bridge): s for s in surfaces_of(objects)}
    assert set(surfaces) == {
        ("TRDirtRoad.tga", False),
        ("TRStone.tga", False),
        (None, False),
        (None, True),
    }
    # The two dirt roads are one surface, and its triangles number into it as a whole.
    dirt = surfaces[("TRDirtRoad.tga", False)]
    assert int(dirt.indices.max()) == len(dirt.positions) - 1
    assert len(dirt.positions) == 2 * len(surfaces[("TRStone.tga", False)].positions)


def test_no_roads_make_no_surfaces():
    assert road_surfaces([], style, None) == []
    assert surfaces_of([placed("Dirt", 0.0, 0.0, ROAD_START)]) == []
    assert surfaces_of([placed("Dirt", 0.0, 0.0, ROAD_END)]) == []


def test_a_curve_is_draped_like_the_strips_it_joins():
    grid = slope(rows=60, columns=60)
    (surface,) = surfaces_of(road((0.0, 0.0), (300.0, 0.0), (300.0, 300.0)), grid)
    xs, zs = surface.positions[:, 0], surface.positions[:, 2]
    assert zs == pytest.approx(xs / 10.0 * FEET_PER_HEIGHT_UNIT + ROAD_LIFT, abs=1e-4)
