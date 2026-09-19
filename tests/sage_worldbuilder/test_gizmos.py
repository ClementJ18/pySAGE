"""The transform gizmos' rules without Qt: how far a handle reaches, which way its axis points,
what an axis does to a drag, angle snapping, and the distance a hit test measures."""

import math

import pytest

from sage_worldbuilder.gizmos import (
    GIZMO_PIXELS,
    HANDLE_PIXELS,
    Axis,
    axis_tip,
    constrained,
    front_tip,
    point_to_segment,
    reach,
    snapped_angle,
)


def test_a_handle_is_the_same_size_on_screen_at_any_scale():
    assert reach(HANDLE_PIXELS, 1.0) == HANDLE_PIXELS
    assert reach(GIZMO_PIXELS, 2.0) == GIZMO_PIXELS / 2
    # A scale of zero cannot divide; the reach stays finite rather than blowing up.
    assert math.isfinite(reach(GIZMO_PIXELS, 0.0))


def test_the_front_handle_points_where_the_object_faces():
    assert front_tip(100.0, 100.0, 0.0, 1.0) == pytest.approx((100.0 + HANDLE_PIXELS, 100.0))
    x, y = front_tip(100.0, 100.0, math.pi / 2, 1.0)
    assert (x, y) == pytest.approx((100.0, 100.0 + HANDLE_PIXELS))
    # Twice the zoom, half the world length, so it still reaches the same pixels.
    assert front_tip(0.0, 0.0, 0.0, 2.0) == pytest.approx((HANDLE_PIXELS / 2, 0.0))


def test_the_move_axes_point_along_the_world_axes():
    center = (50.0, 60.0)
    assert axis_tip(center, Axis.X, 1.0) == pytest.approx((50.0 + GIZMO_PIXELS, 60.0))
    assert axis_tip(center, Axis.Y, 1.0) == pytest.approx((50.0, 60.0 + GIZMO_PIXELS))
    # Z has no direction on the ground: the tool draws it up the screen instead.
    assert axis_tip(center, Axis.Z, 1.0) == center


def test_an_axis_keeps_a_drag_to_itself():
    delta = (3.0, -4.0, 5.0)
    assert constrained(delta, Axis.X) == (3.0, 0.0, 0.0)
    assert constrained(delta, Axis.Y) == (0.0, -4.0, 0.0)
    assert constrained(delta, Axis.Z) == (0.0, 0.0, 5.0)
    assert constrained(delta, Axis.GROUND) == (3.0, -4.0, 0.0)
    assert constrained(delta, None) == (3.0, -4.0, 0.0)


def test_a_turn_snaps_to_whole_steps():
    assert snapped_angle(math.radians(50.0)) == pytest.approx(math.radians(45.0))
    assert snapped_angle(math.radians(22.0)) == pytest.approx(0.0)
    assert snapped_angle(math.radians(200.0), 90.0) == pytest.approx(math.pi)
    assert snapped_angle(math.radians(37.0), 0.0) == pytest.approx(math.radians(37.0))


def test_the_hit_test_measures_to_the_segment_not_its_line():
    assert point_to_segment((5.0, 3.0), (0.0, 0.0), (10.0, 0.0)) == pytest.approx(3.0)
    # Past the end, the distance is to the end itself.
    assert point_to_segment((13.0, 4.0), (0.0, 0.0), (10.0, 0.0)) == pytest.approx(5.0)
    assert point_to_segment((0.0, 2.0), (1.0, 1.0), (1.0, 1.0)) == pytest.approx(math.sqrt(2))
