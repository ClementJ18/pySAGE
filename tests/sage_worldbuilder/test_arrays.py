"""Radial arrays without Qt: where a ring's copies land, which way they face, what a copy keeps
from its source, and the options a settings file can hold."""

import math

from sage_map.assets.object_list import ObjectsList
from sage_map.map import Map
from sage_worldbuilder.arrays import (
    ArrayOptions,
    Facing,
    aim_delta,
    array_copies,
    array_placements,
    stamp_objects,
)
from sage_worldbuilder.objects import new_object
from sage_worldbuilder.waypoints import new_waypoint

CENTER = (0.0, 0.0)


def empty_map():
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    return map


def place(map, name, x, y, angle=0.0):
    return new_object(map, name, (x, y, 0.0), angle, "team")


def same_angle(one, other):
    """Whether two angles point the same way, whichever side of a half turn they are stored on."""
    return math.isclose(math.remainder(one - other, math.tau), 0.0, abs_tol=1e-9)


def positions(copies):
    return [[(round(x, 6), round(y, 6)) for x, y, _angle in placed] for placed in copies]


def test_a_ring_spaces_its_copies_evenly_at_the_stamps_distance():
    copies = array_placements([(10.0, 0.0, 0.0)], CENTER, ArrayOptions(count=4))
    assert positions(copies) == [[(10.0, 0.0)], [(0.0, 10.0)], [(-10.0, 0.0)], [(-0.0, -10.0)]]
    for placed in copies:
        for x, y, _angle in placed:
            assert math.isclose(math.hypot(x, y), 10.0, abs_tol=1e-9)


def test_the_first_copy_stays_where_the_stamp_is_and_the_ring_runs_from_it():
    copies = array_placements([(0.0, 8.0, 0.0)], CENTER, ArrayOptions(count=2))
    assert positions(copies) == [[(0.0, 8.0)], [(-0.0, -8.0)]]


def test_a_pivot_moves_the_stamp_before_the_ring_is_built():
    copies = array_placements([(3.0, 3.0, 0.0)], CENTER, ArrayOptions(count=2), pivot=(10.0, 0.0))
    assert positions(copies) == [[(10.0, 0.0)], [(-10.0, 0.0)]]


def test_keep_first_leaves_the_stamps_own_place_out():
    options = ArrayOptions(count=4)
    copies = array_placements([(10.0, 0.0, 0.0)], CENTER, options, keep_first=True)
    assert positions(copies) == [[(0.0, 10.0)], [(-10.0, 0.0)], [(-0.0, -10.0)]]


def test_facing_aims_every_copy_at_the_centre():
    copies = array_placements([(10.0, 0.0, 0.0)], CENTER, ArrayOptions(count=4))
    for placed in copies:
        for x, y, angle in placed:
            assert same_angle(angle, math.atan2(-y, -x))


def test_facing_away_along_and_kept_turn_the_copies_the_other_ways():
    stamp = [(10.0, 0.0, 0.0)]
    away = array_placements(stamp, CENTER, ArrayOptions(count=4, facing=Facing.AWAY))
    assert all(same_angle(angle, math.atan2(y, x)) for placed in away for x, y, angle in placed)
    along = array_placements(stamp, CENTER, ArrayOptions(count=4, facing=Facing.ALONG))
    assert math.isclose(along[0][0][2], math.pi / 2, abs_tol=1e-9)
    kept = array_placements(stamp, CENTER, ArrayOptions(count=4, facing=Facing.KEEP))
    assert [round(angle, 6) for placed in kept for _x, _y, angle in placed] == [
        0.0,
        round(math.pi / 2, 6),
        round(math.remainder(math.pi, math.tau), 6),
        round(-math.pi / 2, 6),
    ]


def test_the_angle_offset_turns_every_copy_further():
    options = ArrayOptions(count=4, offset_degrees=90.0)
    copies = array_placements([(10.0, 0.0, 0.0)], CENTER, options)
    assert math.isclose(copies[0][0][2], math.remainder(math.pi * 1.5, math.tau), abs_tol=1e-9)


def test_a_group_keeps_its_arrangement_and_its_lead_does_the_aiming():
    # A building at the ring's radius with a wall four units behind it, facing the same way.
    stamp = [(10.0, 0.0, 0.0), (14.0, 0.0, 0.0)]
    copies = array_placements(stamp, CENTER, ArrayOptions(count=4))
    for building, wall in copies:
        assert math.isclose(math.dist(building[:2], wall[:2]), 4.0, abs_tol=1e-9)
        # Both members turn by the same amount, so the wall stays behind the building.
        assert same_angle(building[2], wall[2])
        assert same_angle(building[2], math.atan2(-building[1], -building[0]))
    assert math.isclose(math.hypot(*copies[1][1][:2]), 14.0, abs_tol=1e-9)


def test_aim_delta_is_what_turns_the_objects_already_on_the_map():
    stamp = [(10.0, 0.0, 0.5)]
    delta = aim_delta(stamp, CENTER, ArrayOptions(count=4))
    assert math.isclose(0.5 + delta, math.pi, abs_tol=1e-9)
    assert aim_delta(stamp, CENTER, ArrayOptions(count=4, facing=Facing.KEEP)) == 0.0


def test_a_copy_takes_a_fresh_id_keeps_its_height_and_drops_the_script_name():
    map = empty_map()
    source = place(map, "GondorMarketPlace", 10.0, 0.0)
    source.position = (10.0, 0.0, 12.5)
    source.properties["objectName"] = {
        "name": "objectName",
        "type": source.properties["uniqueID"]["type"],
        "value": "Market",
    }
    map.objects_list.object_list.append(place(map, "GondorFighter", 0.0, 0.0))
    copies = array_copies(map, [source], CENTER, ArrayOptions(count=3))
    assert len(copies) == 3
    assert [obj.position[2] for obj in copies] == [12.5, 12.5, 12.5]
    assert not any("objectName" in obj.properties for obj in copies)
    ids = [obj.properties["uniqueID"]["value"] for obj in copies]
    assert ids == ["GondorMarketPlace 1", "GondorMarketPlace 2", "GondorMarketPlace 3"]
    assert source.position == (10.0, 0.0, 12.5)


def test_a_ring_through_the_selection_makes_one_copy_fewer():
    map = empty_map()
    source = place(map, "GondorMarketPlace", 10.0, 0.0)
    map.objects_list.object_list.append(source)
    copies = array_copies(map, [source], CENTER, ArrayOptions(count=4), keep_first=True)
    assert len(copies) == 3
    assert source not in copies


def test_a_stamp_leaves_out_waypoints_and_whatever_is_not_an_object():
    map = empty_map()
    object = place(map, "GondorFighter", 0.0, 0.0)
    waypoint = new_waypoint(map, (1.0, 1.0, 0.0))
    assert stamp_objects([object, waypoint, "an area"]) == [object]


def test_options_survive_the_settings_file_and_a_bad_one_gives_defaults():
    options = ArrayOptions(count=8, facing=Facing.AWAY, offset_degrees=45.0, use_selection=False)
    assert ArrayOptions.from_dict(options.to_dict()) == options
    assert ArrayOptions.from_dict({"count": 0, "facing": "sideways"}) == ArrayOptions()
    assert ArrayOptions.from_dict("nonsense") == ArrayOptions()
