"""The query surface on an observation: filtering, proximity, and the JSON export.

These are what a consumer actually touches, so they are tested against a fixture that
reproduces the two things about live data most likely to trip a caller up - ownership that
disagrees with the template's Side, and objects with no body at all.
"""

from __future__ import annotations

import json

import pytest

from sage_live.observation import GameObject, Observation, PlayerState, distance


def obj(
    object_id: int,
    template: str,
    side: str,
    owner: int | None,
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    health: float = 1.0,
    max_health: float = 255.0,
    upgrades: frozenset[str] = frozenset(),
) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name=template,
        template_side=side,
        position=position,
        angle=0.0,
        health=health,
        max_health=max_health,
        owner_index=owner,
        upgrades=upgrades,
    )


@pytest.fixture
def match() -> Observation:
    """A skirmish with the disagreements a real one has.

    Object 5 is a creep lair the creeps own but whose template Side is `Neutral`; object 6 is
    a farm plot flag the local player owns with no body at all. Both are shapes measured in a
    live match, and both defeat the naive "filter by Side" reading.
    """
    return Observation(
        frame=900,
        local_player=3,
        players=(
            PlayerState(index=1, name="PlyrCivilian", faction="Civilian", resources=0),
            PlayerState(index=2, name="PlyrCreeps", faction="Wild", resources=0),
            PlayerState(
                index=3,
                name="Player_1",
                faction="Men",
                resources=1200,
                resources_collected=2000,
                command_points=(60, 200),
                upgrades=frozenset({"Upgrade_MenIronOre"}),
            ),
            PlayerState(index=4, name="ReplayObserver", faction="Observer", resources=0),
            PlayerState(index=5, name="Enemy", faction="Mordor", resources=800),
        ),
        objects=(
            obj(
                1, "GondorFighter", "Men", 3, (0.0, 0.0, 0.0), upgrades=frozenset({"Upgrade_Blade"})
            ),
            obj(2, "GondorFighter", "Men", 3, (30.0, 40.0, 0.0), health=0.5),
            obj(3, "GondorBarracks", "Men", 3, (300.0, 0.0, 0.0)),
            obj(4, "MordorOrcFighter", "Mordor", 5, (900.0, 0.0, 0.0)),
            obj(5, "CreepLair", "Neutral", 2, (100.0, 0.0, 0.0)),
            obj(6, "FarmPlotFlag", "Civilian", 3, (10.0, 0.0, 0.0), max_health=0.0),
        ),
    )


def test_me_and_mine_answer_for_the_local_player(match):
    assert match.me is not None
    assert match.me.name == "Player_1"
    assert {o.object_id for o in match.mine} == {1, 2, 3, 6}


def test_mine_uses_ownership_not_the_templates_side(match):
    """The plot flag's Side is `Civilian` and the local player owns it anyway."""
    assert 6 in {o.object_id for o in match.mine}
    assert 6 not in {o.object_id for o in match.by_side("Men")}


def test_opponents_excludes_the_engines_own_seats(match):
    assert [p.name for p in match.opponents] == ["PlyrCreeps", "Enemy"]


def test_a_player_with_no_faction_is_not_playing():
    assert not PlayerState(index=0, name="", faction="", resources=0).playing


def test_obj_finds_by_id_and_answers_none_for_the_dead(match):
    assert match.obj(3).template_name == "GondorBarracks"
    assert match.obj(999) is None


def test_find_combines_criteria(match):
    assert {o.object_id for o in match.find(template="GondorFighter")} == {1, 2}
    assert {o.object_id for o in match.find(owner=3, has_body=True)} == {1, 2, 3}
    assert {o.object_id for o in match.find(damaged=True)} == {2}
    assert {o.object_id for o in match.find(upgrade="upgrade_blade")} == {1}
    assert {o.object_id for o in match.find(templates={"CreepLair", "MordorOrcFighter"})} == {4, 5}


def test_find_is_case_insensitive_because_ini_identifiers_are(match):
    assert match.find(template="gondorbarracks") == match.find(template="GondorBarracks")
    assert match.find(side="men") == match.find(side="Men")


def test_find_with_no_criteria_is_every_object(match):
    assert match.find() == match.objects


def test_a_radius_query_filters_then_sorts_by_distance(match):
    near_base = match.find(near=(0.0, 0.0, 0.0), within=60.0)
    assert [o.object_id for o in near_base] == [1, 6, 2]


def test_near_without_within_sorts_rather_than_filters(match):
    ordered = match.find(near=(900.0, 0.0, 0.0))
    assert len(ordered) == len(match.objects)
    assert ordered[0].object_id == 4


def test_nearest_takes_the_same_criteria(match):
    assert match.nearest((0.0, 0.0, 0.0), owner=5).object_id == 4
    assert match.nearest((0.0, 0.0, 0.0), template="NoSuchThing") is None


def test_nearest_refuses_a_second_anchor(match):
    with pytest.raises(TypeError):
        match.nearest((0.0, 0.0, 0.0), near=(1.0, 1.0, 1.0))


def test_census_counts_templates_and_accepts_a_subset(match):
    assert match.census()["GondorFighter"] == 2
    assert match.census(match.find(owner=5)) == {"MordorOrcFighter": 1}


def test_distance_is_three_dimensional():
    assert distance((0.0, 0.0, 0.0), (3.0, 4.0, 0.0)) == pytest.approx(5.0)
    assert distance((0.0, 0.0, 0.0), (0.0, 3.0, 4.0)) == pytest.approx(5.0)


def test_object_helpers(match):
    fighter = match.obj(2)
    assert fighter.hit_points == pytest.approx(127.5)
    assert fighter.is_damaged
    assert fighter.distance_to(match.obj(1)) == pytest.approx(50.0)
    assert fighter.distance_to((30.0, 40.0, 0.0)) == pytest.approx(0.0)


def test_an_object_with_no_body_reports_no_hit_points(match):
    flag = match.obj(6)
    assert not flag.has_body
    assert not flag.is_damaged, "no body means not applicable, not dead"
    assert flag.hit_points == 0.0


def test_upgrade_membership_is_case_insensitive_on_both_scopes(match):
    assert match.obj(1).has("UPGRADE_BLADE")
    assert not match.obj(2).has("Upgrade_Blade")
    assert match.me.has("upgrade_menironore")
    assert not match.me.researching("Upgrade_MenIronOre")


def test_veterancy_reads_the_engines_own_level_upgrade():
    """The engine records an experience level as an ordinary object upgrade, so no separate
    field is needed - and a battalion that has never fought still carries level 1."""
    fresh = obj(1, "MordorFighter", "Mordor", 3, upgrades=frozenset({"Upgrade_ObjectLevel1"}))
    veteran = obj(
        2,
        "MordorFighter",
        "Mordor",
        3,
        upgrades=frozenset(
            {"Upgrade_ObjectLevel1", "Upgrade_ObjectLevel2", "Upgrade_MordorForgedBlades"}
        ),
    )
    assert fresh.veterancy == 1
    assert veteran.veterancy == 2, "the highest level present, not the count"


def test_veterancy_is_zero_where_the_concept_does_not_apply():
    """Foundations, plot flags and scenery gain no experience and carry no level upgrade."""
    assert obj(3, "MordorBuildingFoundation", "Mordor", 3).veterancy == 0
    assert obj(4, "Keep", "Men", 3, upgrades=frozenset({"Upgrade_StructureLevel1"})).veterancy == 0


def test_veterancy_ignores_a_level_upgrade_with_a_non_numeric_tail():
    odd = obj(5, "X", "Men", 3, upgrades=frozenset({"Upgrade_ObjectLevelMax"}))
    assert odd.veterancy == 0


def test_player_economy_helpers(match):
    me = match.me
    assert me.spent == 800
    assert me.command_points_free == 140
    assert me.can_afford(1200)
    assert not me.can_afford(1201)


def test_command_points_free_never_goes_negative():
    """A command-point grant can push usage past the cap, and free capacity is not negative."""
    over = PlayerState(index=0, name="p", faction="Men", resources=0, command_points=(250, 200))
    assert over.command_points_free == 0


def test_the_snapshot_survives_json_and_keeps_the_derived_fields(match):
    document = match.to_dict()
    round_tripped = json.loads(json.dumps(document))

    assert round_tripped["frame"] == 900
    assert round_tripped["in_match"] is True
    assert len(round_tripped["objects"]) == len(match.objects)

    me = next(p for p in round_tripped["players"] if p["index"] == 3)
    assert me["upgrades"] == ["Upgrade_MenIronOre"], "frozenset must become a sorted list"
    assert me["spent"] == 800
    assert me["playing"] is True

    flag = next(o for o in round_tripped["objects"] if o["object_id"] == 6)
    assert flag["has_body"] is False
