"""Object ownership: `Object -> Team* -> Player`, inverted through each player's own team.

Ownership is the one thing a policy cannot do without - it has to tell its units from an
enemy's - and it is *not* the template's Side. Measured in a live RotWK+Edain match:

- the creeps owned 18 objects whose template Side is `Neutral` (creep lairs),
- the local player owned one whose template Side is `Civilian`,
- and a sandbox hero the local player owned had template Side `Mordor`.

So the old "Side matches my faction" heuristic both missed owned objects and claimed foreign
ones. These tests cover the mapping logic and the `Observation` accessor over it; the offsets
themselves (`Object+0x31C`, `Player+0x30C`) are recorded in `EngineLayout`.
"""

from __future__ import annotations

from sage_live.api.observation import GameObject, Observation, PlayerState


def _object(object_id: int, side: str, owner: int | None) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name=f"Template{object_id}",
        template_side=side,
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        health=1.0,
        max_health=100.0,
        owner_index=owner,
    )


def match() -> Observation:
    """A roster and object set shaped like the live measurements above."""
    return Observation(
        frame=500,
        local_player=3,
        players=(
            PlayerState(index=1, name="PlyrCivilian", faction="Civilian", resources=0),
            PlayerState(index=2, name="PlyrCreeps", faction="Civilian", resources=0),
            PlayerState(index=3, name="Player_1", faction="Men", resources=0),
        ),
        objects=(
            _object(1, "Men", 3),
            _object(2, "Civilian", 3),  # owned by me, Side says otherwise
            _object(3, "Mordor", 3),  # a sandbox hero: Side is an enemy faction
            _object(4, "Neutral", 2),  # a creep lair, Side says neutral
            _object(5, "Wild", 2),
            _object(6, "Flags", 1),
            _object(7, "Civilian", None),  # script team - unresolved, not "nobody"
        ),
    )


def test_owned_by_finds_objects_whose_side_disagrees():
    mine = {o.object_id for o in match().owned_by(3)}
    assert mine == {1, 2, 3}, "Side-based filtering would have returned only object 1"


def test_side_filtering_would_have_been_wrong_both_ways():
    """The exact failure this replaced: it misses two of mine and claims one that is not."""
    observation = match()
    by_side = {o.object_id for o in observation.objects if o.template_side == "Men"}
    by_owner = {o.object_id for o in observation.owned_by(3)}
    assert by_side - by_owner == set(), "no false positives in this fixture"
    assert by_owner - by_side == {2, 3}, "Side misses the Civilian and Mordor objects I own"


def test_a_creep_owned_neutral_object_is_not_mine():
    assert 4 not in {o.object_id for o in match().owned_by(3)}
    assert 4 in {o.object_id for o in match().owned_by(2)}


def test_unresolved_ownership_belongs_to_nobody_rather_than_the_local_player():
    """None means "could not resolve", so it must not fall into any player's bucket."""
    observation = match()
    for index in (1, 2, 3):
        assert 7 not in {o.object_id for o in observation.owned_by(index)}


def test_by_side_still_reports_the_template_side():
    """`by_side` is deliberately about templates, so it keeps its old meaning."""
    assert {o.object_id for o in match().by_side("Neutral")} == {4}


def test_command_points_are_a_used_cap_pair():
    """Ordering matters: (in use, cap). Reading them the other way round silently inverts a
    capacity check, and both are plain ints so nothing would complain."""
    player = PlayerState(
        index=3, name="Player_1", faction="Men", resources=0, command_points=(180, 500)
    )
    used, cap = player.command_points
    assert used < cap
    assert (used, cap) == (180, 500)


def test_engine_sides_report_no_command_points_in_use():
    """0 in use for a Civilian side is the true answer, not a failed read."""
    creeps = PlayerState(
        index=2, name="PlyrCreeps", faction="Civilian", resources=0, command_points=(0, 500)
    )
    assert creeps.command_points == (0, 500)
