"""Tests for binding declared objects to the live ones the engine made.

Data-free: `sage_live`'s observation model is stdlib-only, so a match can be simulated exactly
without a game. The cases that matter are the ones a scenario can actually produce - two objects
of the same template near each other, an object the engine dropped onto terrain a little away
from where it was placed, and a placement that never appeared at all.
"""

from __future__ import annotations

import pytest

from sage_live.api.observation import GameObject, Observation
from sage_test import Scenario, Seat
from sage_test.harness import DEFAULT_TOLERANCE, BindingError, bind_handles


def _obj(object_id: int, template: str, x: float, y: float) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name=template,
        template_side="Men",
        position=(x, y, 0.0),
        angle=0.0,
        health=1.0,
        max_health=100.0,
        owner_index=3,
    )


def _observation(*objects: GameObject) -> Observation:
    return Observation(frame=1, local_player=3, objects=tuple(objects))


def _scenario() -> Scenario:
    return Scenario("t", seats=(Seat.human(faction=3),))


class TestBinding:
    def test_it_binds_a_placement_to_the_object_at_its_position(self):
        scenario = _scenario()
        hero = scenario.place("Hero", at=(100.0, 100.0, 0.0))
        bindings = bind_handles(scenario, _observation(_obj(7, "Hero", 100.0, 100.0)))
        assert bindings[hero.index] == 7

    def test_height_is_not_part_of_the_match(self):
        """The engine drops placed objects onto the terrain, so the z a scenario declares is
        never the z it comes back at - the spike saw 0 become 100."""
        scenario = _scenario()
        hero = scenario.place("Hero", at=(100.0, 100.0, 0.0))
        found = _obj(7, "Hero", 100.0, 100.0)
        settled = GameObject(**{**found.__dict__, "position": (100.0, 100.0, 500.0)})
        assert bind_handles(scenario, _observation(settled))[hero.index] == 7

    def test_two_placements_of_one_template_bind_to_two_objects(self):
        """Both are within tolerance of each other, so a nearest-match that did not claim would
        bind them both to whichever object happened to be closer."""
        scenario = _scenario()
        first = scenario.place("Fighter", at=(100.0, 100.0, 0.0))
        second = scenario.place("Fighter", at=(140.0, 100.0, 0.0))
        bindings = bind_handles(
            scenario,
            _observation(_obj(1, "Fighter", 100.0, 100.0), _obj(2, "Fighter", 140.0, 100.0)),
        )
        assert bindings[first.index] == 1
        assert bindings[second.index] == 2
        assert len(set(bindings.values())) == 2

    def test_it_takes_the_nearest_candidate(self):
        scenario = _scenario()
        hero = scenario.place("Hero", at=(100.0, 100.0, 0.0))
        observation = _observation(
            _obj(1, "Hero", 130.0, 100.0),
            _obj(2, "Hero", 105.0, 100.0),
        )
        assert bind_handles(scenario, observation)[hero.index] == 2

    def test_template_matching_is_case_insensitive(self):
        """Ini identifiers are, everywhere else in this codebase and in the engine."""
        scenario = _scenario()
        hero = scenario.place("gondorfighter", at=(0.0, 0.0, 0.0))
        assert (
            bind_handles(scenario, _observation(_obj(3, "GondorFighter", 0.0, 0.0)))[hero.index]
            == 3
        )

    def test_a_different_template_at_the_same_spot_is_not_it(self):
        scenario = _scenario()
        scenario.place("Hero", at=(0.0, 0.0, 0.0))
        with pytest.raises(BindingError, match="Hero"):
            bind_handles(scenario, _observation(_obj(1, "Villain", 0.0, 0.0)))

    def test_an_object_beyond_the_tolerance_is_not_it(self):
        scenario = _scenario()
        scenario.place("Hero", at=(0.0, 0.0, 0.0))
        far = _obj(1, "Hero", DEFAULT_TOLERANCE + 10, 0.0)
        with pytest.raises(BindingError):
            bind_handles(scenario, _observation(far))

    def test_a_missing_placement_says_which_one(self):
        scenario = _scenario()
        scenario.place("Present", at=(0.0, 0.0, 0.0))
        scenario.place("Absent", at=(50.0, 50.0, 0.0))
        with pytest.raises(BindingError) as caught:
            bind_handles(scenario, _observation(_obj(1, "Present", 0.0, 0.0)))
        assert "placement 1" in str(caught.value)
        assert "Absent" in str(caught.value)

    def test_an_empty_scenario_binds_to_nothing_without_complaint(self):
        assert bind_handles(_scenario(), _observation()) == {}
