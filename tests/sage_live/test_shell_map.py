"""Telling a real match apart from the main menu's shell map.

BFME2 renders its main menu over a *shell map*: an actual map, simulated by the same
`GameLogic`, with a looping camera script. So at the menu the logic frame counter advances,
objects exist, and a player list exists - every cheap "is a game running?" signal says yes.

What it does not have is a player. Observed at the menu of RotWK 2.01 + Edain: two players,
`PlyrCivilian` (Civilian) and `ReplayObserver` (Observer), with the local index pointing at
the observer, and 8 objects (particle proxies, `ShellMapMD`, and the four tree singletons).

Fixtures below reproduce both states, so this stays in the data-free suite.
"""

from __future__ import annotations

from sage_live.api.observation import GameObject, Observation, PlayerState


def _object(object_id: int, template: str, side: str = "Civilian") -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name=template,
        template_side=side,
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        health=1.0,
        max_health=1.0,
    )


def shell_map() -> Observation:
    """The menu, as actually observed - note the advancing frame and non-empty object list."""
    return Observation(
        frame=565,
        local_player=2,
        players=(
            PlayerState(index=1, name="PlyrCivilian", faction="Civilian", resources=1500),
            PlayerState(index=2, name="ReplayObserver", faction="Observer", resources=1500),
        ),
        objects=(
            _object(4, "ShellMapMD"),
            _object(99999999, "TheOneTree"),
        ),
    )


def skirmish() -> Observation:
    return Observation(
        frame=158,
        local_player=3,
        players=(
            PlayerState(index=1, name="PlyrCivilian", faction="Civilian", resources=4000),
            PlayerState(index=2, name="PlyrCreeps", faction="Civilian", resources=4000),
            PlayerState(index=3, name="Player_1", faction="Elves", resources=4000),
            PlayerState(index=4, name="ReplayObserver", faction="Observer", resources=4000),
        ),
        objects=(_object(400, "ElvenLorienWarriorHorde_StartUnit", "Elves"),),
    )


def test_the_menu_is_not_a_match_despite_looking_like_one():
    menu = shell_map()
    assert menu.frame > 0, "the shell map really does tick"
    assert menu.objects, "and really does have objects"
    assert not menu.in_match


def test_a_skirmish_is_a_match():
    assert skirmish().in_match


def test_the_test_is_the_local_player_not_the_roster():
    """The observer seat exists in a real match too, so its presence proves nothing."""
    match = skirmish()
    assert any(p.faction == "Observer" for p in match.players)
    assert match.in_match


def test_an_observer_seat_in_a_real_game_is_still_not_playing():
    """Watching a replay puts a real roster on screen with the observer as the local player."""
    watching = skirmish()
    assert not Observation(
        frame=watching.frame,
        local_player=4,  # the ReplayObserver seat
        players=watching.players,
        objects=watching.objects,
    ).in_match


def test_a_local_index_naming_nobody_is_not_a_match():
    assert not Observation(frame=99, local_player=7, players=skirmish().players).in_match


def test_an_empty_observation_is_not_a_match():
    assert not Observation(frame=0, local_player=0).in_match
