"""Roads laid out as the game's road mesh does: strip widths, mitred and curved corners, curves
that do not fit, and the joins that are not built."""

import math

import pytest

from sage_worldbuilder.road_mesh import BROAD_RADIUS, STRAIGHT_ROW, TEXTURE_REPEAT, road_pieces
from sage_worldbuilder.roads import (
    BRIDGE_END,
    BRIDGE_START,
    CORNER_ANGLED,
    CORNER_TIGHT,
    ROAD_END,
    ROAD_START,
    RoadStyle,
    road_segments,
)
from tests.sage_worldbuilder.test_roads import placed

WIDTH, IN_TEXTURE = 80.0, 0.9
HALF = WIDTH * IN_TEXTURE / 2


def style(name):
    return RoadStyle(WIDTH, bridge=False, width_in_texture=IN_TEXTURE)


def road(*points, corner=0, type_name="Dirt"):
    """A road through `points`, one segment per pair of neighbours, with `corner` on every end."""
    objects = []
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        objects.append(placed(type_name, x0, y0, ROAD_START | corner))
        objects.append(placed(type_name, x1, y1, ROAD_END | corner))
    return objects


def pieces_of(objects):
    return road_pieces(road_segments(objects), style)


def strips(pieces):
    return [piece for piece in pieces if not piece.curve]


def curves(pieces):
    return [piece for piece in pieces if piece.curve]


def close(a, b):
    return a == pytest.approx(b, abs=1e-6)


def test_a_strip_is_the_road_width_times_its_width_in_texture_across():
    (piece,) = pieces_of(road((0.0, 0.0), (100.0, 0.0)))
    assert close(piece.corners, [(0, HALF), (100, HALF), (100, -HALF), (0, -HALF)])


def test_an_angled_corner_is_mitred():
    first, second = strips(
        pieces_of(road((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), corner=CORNER_ANGLED))
    )
    inside, outside = (100 - HALF, HALF), (100 + HALF, -HALF)
    assert close(first.corners[1], inside) and close(first.corners[2], outside)
    assert close(second.corners[0], inside) and close(second.corners[3], outside)


def test_a_small_turn_is_mitred_even_when_broad():
    pieces = pieces_of(road((0.0, 0.0), (100.0, 0.0), (200.0, 30.0)))
    assert curves(pieces) == []
    first, second = strips(pieces)
    assert close(first.corners[1], second.corners[0]) and close(first.corners[2], second.corners[3])


@pytest.mark.parametrize(("corner", "radius"), [(0, 1.5 * WIDTH), (CORNER_TIGHT, 0.5 * WIDTH)])
def test_a_right_angle_curves_in_30_degree_pieces(corner, radius):
    pieces = pieces_of(road((-200.0, 0.0), (100.0, 0.0), (100.0, 300.0), corner=corner))
    first, second = strips(pieces)
    arc = curves(pieces)
    assert len(arc) == 3
    # Each strip stops where the curve leaves it, the radius back from the corner.
    assert close(first.corners[1], (100 - radius, HALF)) and close(
        first.corners[2], (100 - radius, -HALF)
    )
    assert close(second.corners[0], (100 - HALF, radius)) and close(
        second.corners[3], (100 + HALF, radius)
    )
    centre = (100 - radius, radius)
    inner, outer = max(radius - HALF, 0.0), radius + HALF
    for piece in arc:
        distances = sorted(math.dist(corner_point, centre) for corner_point in piece.corners)
        assert close(distances, [inner, inner, outer, outer])
    # The curve starts on the first strip's end and ends on the second's start.
    assert close(arc[0].corners[0], first.corners[1]) and close(arc[0].corners[1], first.corners[2])
    assert close(arc[-1].corners[3], second.corners[0]) and close(
        arc[-1].corners[2], second.corners[3]
    )


def test_a_curve_that_does_not_fit_is_mitred():
    pieces = pieces_of(road((60.0, 0.0), (100.0, 0.0), (100.0, 300.0)))
    assert curves(pieces) == []
    first, second = strips(pieces)
    assert close(first.corners[1], second.corners[0])


def test_the_curve_follows_a_segment_stored_backwards():
    objects = road((-200.0, 0.0), (100.0, 0.0)) + [
        placed("Dirt", 100.0, 300.0, ROAD_START),
        placed("Dirt", 100.0, 0.0, ROAD_END),
    ]
    assert len(curves(pieces_of(objects))) == 3


def test_different_road_types_and_three_way_points_are_not_joined():
    mixed = road((0.0, 0.0), (100.0, 0.0)) + road((100.0, 0.0), (100.0, 300.0), type_name="Stone")
    pieces = pieces_of(mixed)
    assert curves(pieces) == []
    assert close(strips(pieces)[0].corners[1], (100, HALF))
    tee = road((-200.0, 0.0), (100.0, 0.0), (100.0, 300.0)) + road((100.0, 0.0), (100.0, -300.0))
    pieces = pieces_of(tee)
    assert curves(pieces) == []
    assert close(strips(pieces)[0].corners[1], (100, HALF))


def test_bridges_are_full_width_and_never_joined():
    objects = [
        placed("Bridge", 0.0, 0.0, BRIDGE_START),
        placed("Bridge", 100.0, 0.0, BRIDGE_END),
        *road((100.0, 0.0), (100.0, 300.0)),
    ]

    def bridge_style(name):
        return RoadStyle(WIDTH, bridge=name == "Bridge", width_in_texture=IN_TEXTURE)

    pieces = road_pieces(road_segments(objects), bridge_style)
    assert curves(pieces) == []
    assert close(pieces[0].corners[0], (0, WIDTH / 2))


def test_two_ends_at_one_spot_are_moved_apart():
    (piece,) = pieces_of(road((50.0, 50.0), (50.0, 50.0)))
    assert close(piece.corners[1][0], 50.25)


def test_the_straight_texture_runs_four_road_widths_and_sits_in_the_top_row():
    (piece,) = pieces_of(road((0.0, 0.0), (TEXTURE_REPEAT * WIDTH, 0.0)))
    across = IN_TEXTURE / 8
    assert close([u for u, _v in piece.uvs], [0.0, 1.0, 1.0, 0.0])
    assert close(
        [v for _u, v in piece.uvs],
        [STRAIGHT_ROW - across, STRAIGHT_ROW - across, STRAIGHT_ROW + across] * 1
        + [STRAIGHT_ROW + across],
    )


def test_each_segment_measures_its_texture_from_its_own_start():
    first, second = strips(
        pieces_of(road((0.0, 0.0), (400.0, 0.0)) + road((0.0, 500.0), (200.0, 500.0)))
    )
    assert close([u for u, _v in first.uvs], [0.0, 1.25, 1.25, 0.0])
    assert close([u for u, _v in second.uvs], [0.0, 0.625, 0.625, 0.0])


def test_a_curve_carries_the_texture_on_round_the_bend():
    pieces = pieces_of(road((0.0, 0.0), (300.0, 0.0), (300.0, 300.0)))
    arriving = strips(pieces)[0]
    bend = curves(pieces)
    # The first curve piece starts where the strip now ends, and each one takes up where the
    # piece before it left off.
    assert close(bend[0].uvs[0], arriving.uvs[1])
    assert close(bend[0].uvs[1], arriving.uvs[2])
    for before, after in zip(bend, bend[1:], strict=False):
        assert close(after.uvs[0], before.uvs[3])
        assert close(after.uvs[1], before.uvs[2])
    # A quarter turn of radius 1.5 road widths is that arc long, in four road widths.
    turn = BROAD_RADIUS * WIDTH * math.pi / 2 / (TEXTURE_REPEAT * WIDTH)
    assert close(bend[-1].uvs[3][0] - bend[0].uvs[0][0], turn)


def test_a_curve_stays_across_the_same_band_as_its_strip():
    pieces = pieces_of(road((0.0, 0.0), (300.0, 0.0), (300.0, 300.0)))
    across = IN_TEXTURE / 8
    for piece in curves(pieces):
        assert close(
            sorted({round(v, 9) for _u, v in piece.uvs}),
            [STRAIGHT_ROW - across, STRAIGHT_ROW + across],
        )


def test_a_curve_off_a_segment_start_carries_its_texture_backwards():
    # Both segments are stored leaving the corner, so the curve arrives along the first one
    # against the way it is stored and its texture runs the other way.
    objects = [
        placed("Dirt", 100.0, 0.0, ROAD_START),
        placed("Dirt", -200.0, 0.0, ROAD_END),
        placed("Dirt", 100.0, 0.0, ROAD_START),
        placed("Dirt", 100.0, 300.0, ROAD_END),
    ]
    pieces = pieces_of(objects)
    arriving = strips(pieces)[0]
    bend = curves(pieces)
    entry = {(round(u, 9), round(v, 9)) for u, v in bend[0].uvs[:2]}
    assert entry == {(round(u, 9), round(v, 9)) for u, v in (arriving.uvs[0], arriving.uvs[3])}
    assert bend[-1].uvs[3][0] < bend[0].uvs[0][0]
