"""Validation > Fix Teams: remove duplicate teams and teams whose player the map does not have,
and move objects off teams that do not exist, reporting each repair in WorldBuilder's words.
Also the Validation command that turns "Execute associated actions" off on every team.

WorldBuilder asks which player an object on a missing team should go to; here it goes to the
player its owner names when the map has that player, and to the neutral player otherwise. Either
way the object lands on that player's default team, `<player>/team<player>`.
"""

from __future__ import annotations

from sage_map.context import Property
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command, CompositeCommand
from sage_worldbuilder.commands.edits import RemoveItem, SetProperty
from sage_worldbuilder.players import player_name
from sage_worldbuilder.properties import TEAM_SPECS, make_property
from sage_worldbuilder.teams import team_list, team_name, team_owner

__all__ = ["NO_PROBLEMS", "clear_execute_actions", "default_team", "fix_teams"]

NO_PROBLEMS = "No problems were detected."
_OWNER_KEY = "originalOwner"
_EXECUTES_KEY = "teamExecutesActionsOnCreate"


def clear_execute_actions(map: Map) -> tuple[Command | None, list[str]]:
    """Turn "Execute associated actions" off on every team that has it on, as one command, with
    the names of the teams changed. The command is `None` when no team has it on."""
    spec = next(spec for spec in TEAM_SPECS if spec.name == _EXECUTES_KEY)
    changed = [team for team in team_list(map) or [] if _executes(team.properties)]
    commands: list[Command] = [
        SetProperty(
            team.properties, _EXECUTES_KEY, make_property(spec, False), Change(ChangeKind.SIDES)
        )
        for team in changed
    ]
    command = CompositeCommand("Clear Execute associated actions", commands) if commands else None
    return command, [team_name(team) for team in changed]


def _executes(properties: dict[str, Property]) -> bool:
    stored = properties.get(_EXECUTES_KEY)
    return stored is not None and bool(stored["value"])


def default_team(player: str) -> str:
    """The owner an object on `player`'s default team stores."""
    return f"{player}/team{player}"


def fix_teams(map: Map) -> tuple[Command | None, list[str]]:
    """The repairs Fix Teams makes, as one command, and a message for each. The command is
    `None` when nothing needs fixing."""
    teams = team_list(map) or []
    players = {
        player_name(player).lower(): player_name(player)
        for player in (map.sides_list.players if map.sides_list is not None else [])
    }
    messages: list[str] = []
    removed: set[int] = set()

    seen: set[str] = set()
    for index, team in enumerate(teams):
        name = team_name(team)
        if name.lower() in seen:
            removed.add(index)
            messages.append(f'Duplicate instance of team "{name}" removed.')
        seen.add(name.lower())

    kept: set[str] = set()
    for index, team in enumerate(teams):
        if index in removed:
            continue
        owner = team_owner(team)
        if owner.lower() not in players:
            removed.add(index)
            messages.append(
                f'Team "{team_name(team)}" was on non-existent player "{owner}".  Team removed.'
            )
        else:
            kept.add(team_name(team).lower())

    # Removed from the back, so each index still points at its team when its removal runs.
    commands: list[Command] = [
        RemoveItem(teams, index, Change(ChangeKind.SIDES), "Remove team")
        for index in sorted(removed, reverse=True)
    ]

    objects = map.objects_list.object_list if map.objects_list is not None else []
    for placed in objects:
        stored = placed.properties.get(_OWNER_KEY)
        if stored is None:
            continue
        owner = str(stored["value"])
        player, _, owner_team = owner.rpartition("/")
        if owner_team.lower() in kept:
            continue
        target = default_team(players.get(player.lower(), ""))
        if target.lower() == owner.lower():
            continue
        object_name = placed.properties.get("objectName")
        label = f'"{placed.type_name}"'
        if object_name is not None and object_name["value"]:
            label = f'"{object_name["value"]}" ({placed.type_name})'
        messages.append(f'Object {label} on missing team "{owner}" moved to team "{target}".')
        value: Property = {"name": _OWNER_KEY, "type": stored["type"], "value": target}
        commands.append(
            SetProperty(placed.properties, _OWNER_KEY, value, Change(ChangeKind.OBJECTS))
        )

    return (CompositeCommand("Fix Teams", commands) if commands else None), messages
