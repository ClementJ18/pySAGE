"""Tests for the scenario declaration and its compilation into map data.

Data-free: nothing here needs a game, a map file or Windows. The one fact worth stating up front
is the one everything else rests on - a seat binds to `Player_<start_position + 1>`, not to its
index in the seat list - because a scenario that gets that wrong produces a map that loads, plays,
and hands the objects to nobody.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sage_map.assets.object_list import ObjectsList
from sage_map.context import AssetPropertyType
from sage_test import Scenario, Seat
from sage_test.compile import OBJECT_VERSION, compile_into, placement_object


def _template(objects=()):
    """A stand-in for a parsed map: `compile_into` only reaches its object list."""
    return SimpleNamespace(
        objects_list=ObjectsList(version=3, object_list=list(objects), start_pos=0, end_pos=0)
    )


def _scenario(**kwargs):
    return Scenario(
        "t",
        seats=(
            Seat.human(faction=3, start_position=0),
            Seat.easy_ai(faction=10, start_position=1),
        ),
        **kwargs,
    )


class TestSeat:
    def test_the_map_player_follows_the_start_position(self):
        assert Seat.human(faction=3, start_position=0).map_player == "Player_1"
        assert Seat.human(faction=3, start_position=2).map_player == "Player_3"

    def test_it_is_the_start_position_and_not_the_seat_order(self):
        """The whole binding rests on this: a seat's map player comes from where it starts, so
        two seats listed in one order but starting elsewhere bind the other way round."""
        scenario = Scenario(
            "t",
            seats=(
                Seat.human(faction=3, start_position=4),
                Seat.easy_ai(faction=10, start_position=0),
            ),
        )
        assert scenario.seats[0].map_player == "Player_5"
        assert scenario.seats[1].map_player == "Player_1"

    def test_the_owner_is_qualified_by_its_team(self):
        assert Seat.human(faction=3, start_position=1).map_team == "Player_2/teamPlayer_2"

    def test_the_human_is_the_first_non_ai_seat(self):
        scenario = _scenario()
        assert scenario.human is scenario.seats[0]
        assert Scenario("t", seats=(Seat.easy_ai(faction=1),)).human is None


class TestPlacing:
    def test_place_returns_a_handle_naming_what_was_placed(self):
        scenario = _scenario()
        hero = scenario.place("SomeHero", at=(1.0, 2.0, 0.0), level=7)
        assert hero.template == "SomeHero"
        assert hero.at == (1.0, 2.0, 0.0)
        assert scenario.placements[hero.index].level == 7

    def test_handles_are_distinct_for_identical_placements(self):
        scenario = _scenario()
        first = scenario.place("Same", at=(0.0, 0.0, 0.0))
        second = scenario.place("Same", at=(0.0, 0.0, 0.0))
        assert first.index != second.index

    def test_placing_on_a_seat_that_does_not_exist_is_refused(self):
        with pytest.raises(ValueError, match="seat 5"):
            _scenario().place("X", at=(0.0, 0.0, 0.0), seat=5)

    def test_a_neutral_placement_has_no_owner(self):
        scenario = _scenario()
        scenario.place("Rock", at=(0.0, 0.0, 0.0), seat=None)
        assert scenario.owner_of(scenario.placements[0]) is None


class TestCompiledProperties:
    def _properties(self, **kwargs):
        scenario = _scenario()
        scenario.place("Thing", at=(10.0, 20.0, 0.0), **kwargs)
        obj = placement_object(scenario, scenario.placements[0], "Thing 0")
        return {name: prop["value"] for name, prop in obj.properties.items()}

    def test_the_owner_is_the_seats_map_player(self):
        assert self._properties()["originalOwner"] == "Player_1/teamPlayer_1"
        assert self._properties(seat=1)["originalOwner"] == "Player_2/teamPlayer_2"

    def test_a_neutral_placement_keeps_the_editors_empty_owner(self):
        assert self._properties(seat=None)["originalOwner"] == "/team"

    def test_a_level_is_written_only_when_asked_for(self):
        assert "objectExperienceLevel" not in self._properties()
        assert self._properties(level=7)["objectExperienceLevel"] == 7

    def test_upgrades_are_space_separated_with_the_trailing_space(self):
        """Shipped maps write `'Upgrade_A Upgrade_B '`; the trailing space is not an accident and
        the engine's parser is what decides that, not us."""
        assert "objectUpgradesList" not in self._properties()
        value = self._properties(upgrades=("Upgrade_A", "Upgrade_B"))["objectUpgradesList"]
        assert value == "Upgrade_A Upgrade_B "

    def test_health_defaults_to_a_whole_object(self):
        assert self._properties()["objectInitialHealth"] == 100
        assert self._properties(health=35)["objectInitialHealth"] == 35

    def test_every_object_carries_the_editors_standard_set(self):
        properties = self._properties()
        for name in (
            "objectEnabled",
            "objectIndestructible",
            "objectUnsellable",
            "objectPowered",
            "objectRecruitableAI",
            "objectTargetable",
            "objectLayer",
            "uniqueID",
        ):
            assert name in properties, f"{name} is missing from a generated object"

    def test_the_property_types_are_what_the_format_expects(self):
        scenario = _scenario()
        scenario.place("Thing", at=(0.0, 0.0, 0.0), level=3, upgrades=("U",), name="n")
        obj = placement_object(scenario, scenario.placements[0], "Thing 0")
        kinds = {name: prop["type"] for name, prop in obj.properties.items()}
        assert kinds["objectExperienceLevel"] is AssetPropertyType.Integer
        assert kinds["objectUpgradesList"] is AssetPropertyType.AsciiString
        assert kinds["originalOwner"] is AssetPropertyType.AsciiString
        assert kinds["objectEnabled"] is AssetPropertyType.Boolean


class TestCompileInto:
    def test_it_appends_rather_than_replacing(self):
        """The template's own objects are the map: its terrain features, its castle plots and the
        start positions they sit on. A scenario adds to them."""
        template = _template([_stand_in("Existing", "Existing 0")])
        scenario = _scenario()
        scenario.place("A", at=(0.0, 0.0, 0.0))
        compile_into(scenario, template)
        placed = template.objects_list.object_list
        assert [obj.type_name for obj in placed] == ["Existing", "A"]

    def test_generated_objects_use_the_shipped_version(self):
        template = _template()
        scenario = _scenario()
        scenario.place("A", at=(0.0, 0.0, 0.0))
        compile_into(scenario, template)
        assert template.objects_list.object_list[-1].version == OBJECT_VERSION

    def test_positions_and_angles_survive(self):
        template = _template()
        scenario = _scenario()
        scenario.place("A", at=(12.5, 34.5, 1.0), angle=1.25)
        compile_into(scenario, template)
        placed = template.objects_list.object_list[-1]
        assert placed.position == (12.5, 34.5, 1.0)
        assert placed.angle == 1.25

    def test_unique_ids_do_not_collide_with_the_templates(self):
        """`uniqueID` is map-wide. Reusing one a shipped object already has is the kind of thing
        that loads fine and then behaves strangely, so the counter walks past what is taken."""
        template = _template([_stand_in("A", "A 0"), _stand_in("A", "A 1")])
        scenario = _scenario()
        scenario.place("A", at=(0.0, 0.0, 0.0))
        scenario.place("A", at=(1.0, 0.0, 0.0))
        compile_into(scenario, template)
        ids = [obj.properties["uniqueID"]["value"] for obj in template.objects_list.object_list]
        assert len(ids) == len(set(ids)), ids
        assert ids[2:] == ["A 2", "A 3"]

    def test_a_template_without_an_object_list_is_refused(self):
        with pytest.raises(ValueError, match="ObjectsList"):
            compile_into(_scenario(), SimpleNamespace(objects_list=None))


def _stand_in(template: str, unique_id: str):
    """An object already on the template map, with a `uniqueID` a generated one must avoid."""
    scenario = _scenario()
    scenario.place(template, at=(0.0, 0.0, 0.0))
    return placement_object(scenario, scenario.placements[-1], unique_id)
