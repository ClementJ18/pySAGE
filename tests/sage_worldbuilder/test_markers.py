"""Markers: areas, points and paths through points, named in turn, edited in place, and outside
the map's history."""

import numpy as np
import pytest

from sage_worldbuilder.markers import (
    MarkerError,
    MarkerKind,
    Markers,
    distance_to_polyline,
    polygon_contains,
)


def test_each_kind_is_named_in_turn_and_reuses_a_freed_name():
    markers = Markers()
    names = [markers.mark_rectangle(0, 0, 10, 10).name for _ in range(28)]
    assert names[:3] == ["A", "B", "C"]
    assert names[25:] == ["Z", "AA", "AB"]
    markers.remove("b")
    assert markers.mark_rectangle(0, 0, 1, 1).name == "B"
    assert [markers.mark_point(i, 0).name for i in range(3)] == ["P1", "P2", "P3"]
    assert markers.mark_path(["p1", "P2"]).name == "L1"


def test_a_rectangle_is_normalised_and_a_name_replaces_its_namesake():
    markers = Markers()
    area = markers.mark_rectangle(30.04, 20, 10, -5.06, name=" home ")
    assert area.name == "HOME"
    assert area.bounds == (10.0, -5.1, 30.0, 20.0)
    assert area.is_rectangle
    markers.mark_rectangle(0, 0, 5, 5, name="Home")
    assert len(markers) == 1
    assert markers.get("home").bounds == (0.0, 0.0, 5.0, 5.0)


def test_a_polygon_contains_what_it_encloses():
    markers = Markers()
    # An L shape: the notch at the top right is outside.
    area = markers.mark_area([(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)])
    assert not area.is_rectangle
    assert area.contains(5, 15)
    assert area.contains(15, 5)
    assert not area.contains(15, 15)
    assert area.contains(20, 5)  # on the outline
    with pytest.raises(MarkerError, match="three corners"):
        markers.mark_area([(0, 0), (10, 0), (20, 0)])


def test_the_last_marked_area_wins_a_point_two_share():
    markers = Markers()
    markers.mark_rectangle(0, 0, 100, 100)
    markers.mark_rectangle(50, 50, 150, 150)
    assert markers.at(75, 75).name == "B"
    assert markers.at(25, 25).name == "A"
    assert markers.at(200, 200) is None


def test_a_path_follows_its_points():
    markers = Markers()
    for x in (0, 100, 200):
        markers.mark_point(x, 0)
    path = markers.mark_path(["P1", "P2", "P3"])
    markers.set_position("P2", 100, 50)
    assert markers.path_points(path) == [(0, 0), (100, 50), (200, 0)]
    markers.rename("p2", "ford")
    assert markers.get("L1").stops == ("P1", "FORD", "P3")
    markers.move("L1", 10, 0)
    assert markers.path_points(markers.get("L1")) == [(10, 0), (110, 50), (210, 0)]


def test_removing_a_point_shortens_its_paths_and_drops_a_path_left_too_short():
    markers = Markers()
    for x in (0, 100, 200):
        markers.mark_point(x, 0)
    markers.mark_path(["P1", "P2", "P3"])
    markers.mark_path(["P1", "P2"])
    markers.remove("P2")
    assert markers.get("L1").stops == ("P1", "P3")
    assert markers.get("L2") is None
    assert markers.clear(MarkerKind.POINT) == 3  # the points and the path through them


def test_paths_need_marked_points_and_names_stay_with_their_kind():
    markers = Markers()
    markers.mark_rectangle(0, 0, 10, 10)
    markers.mark_point(0, 0)
    with pytest.raises(MarkerError, match="A is not a marked point"):
        markers.mark_path(["P1", "A"])
    with pytest.raises(MarkerError, match="two different points"):
        markers.mark_path(["P1", "P1"])
    with pytest.raises(MarkerError, match="already an area"):
        markers.mark_point(5, 5, name="A")
    with pytest.raises(MarkerError, match="already taken"):
        markers.rename("P1", "a")
    with pytest.raises(MarkerError, match="is a point, not an area"):
        markers.set_corners("P1", [(0, 0), (1, 0), (1, 1)])


def test_the_selection_follows_renames_and_removals():
    markers = Markers()
    markers.mark_point(0, 0)
    markers.select("p1")
    markers.rename("P1", "X")
    assert markers.selected.name == "X"
    markers.remove("X")
    assert markers.selected is None


def test_listeners_hear_every_change_but_not_a_no_op():
    markers = Markers()
    heard = []
    unsubscribe = markers.subscribe(lambda: heard.append(len(markers)))
    markers.mark_rectangle(0, 0, 1, 1)
    markers.remove("Z")
    markers.clear()
    markers.clear()
    unsubscribe()
    markers.mark_rectangle(0, 0, 1, 1)
    assert heard == [1, 0]


def test_geometry_helpers():
    xs, ys = np.array([5.0, 15.0, 5.0]), np.array([5.0, 5.0, 12.0])
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert polygon_contains(square, xs, ys).tolist() == [True, False, False]
    line = [(0, 0), (10, 0)]
    assert distance_to_polyline(line, xs, ys).tolist() == pytest.approx([5.0, 7.0710678, 12.0])
