"""The map's teams: where they are stored, and creating or copying one under a free name.

Maps store teams in the `Teams` chunk; older ones keep them inside `SidesList`. Scripts name a
team by its qualified name, `owner/team`.
"""

from __future__ import annotations

import copy

from sage_map.assets.teams import Team
from sage_map.map import Map
from sage_worldbuilder.properties import TEAM_SPECS, PropertyValue, make_property

__all__ = [
    "copy_team",
    "new_team",
    "qualified_team_name",
    "team_list",
    "team_name",
    "team_owner",
    "unique_team_name",
]

_SPECS = {spec.name: spec for spec in TEAM_SPECS}


def team_list(map: Map) -> list[Team] | None:
    """The list the map stores its teams in, or `None` when it has neither place for them."""
    if map.teams is not None:
        return map.teams.teams
    if map.sides_list is not None:
        return map.sides_list.teams
    return None


def _text(team: Team, key: str) -> str:
    stored = team.properties.get(key)
    return str(stored["value"]) if stored is not None else ""


def team_name(team: Team) -> str:
    return _text(team, "teamName")


def team_owner(team: Team) -> str:
    return _text(team, "teamOwner")


def qualified_team_name(team: Team) -> str:
    return f"{team_owner(team)}/{team_name(team)}"


def unique_team_name(map: Map, base: str) -> str:
    taken = {team_name(team).lower() for team in team_list(map) or []}
    if base.lower() not in taken:
        return base
    suffix = 2
    while f"{base}{suffix}".lower() in taken:
        suffix += 1
    return f"{base}{suffix}"


def new_team(name: str, owner: str, is_singleton: bool = False) -> Team:
    """A team with the three properties every team carries; the rest take the engine's
    defaults until set."""
    values: dict[str, PropertyValue] = {
        "teamName": name,
        "teamOwner": owner,
        "teamIsSingleton": is_singleton,
    }
    return Team(
        properties={key: make_property(_SPECS[key], value) for key, value in values.items()}
    )


def copy_team(map: Map, team: Team) -> Team:
    """A copy of `team` under the next free name."""
    duplicate = copy.deepcopy(team)
    name = unique_team_name(map, team_name(team))
    duplicate.properties["teamName"] = make_property(_SPECS["teamName"], name)
    return duplicate
