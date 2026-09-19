"""The map's players: creating, adding and removing them, and the teams left without one.

A map keeps one entry per player, in player order, in four places: `SidesList.players`,
`PlayerScriptsList.script_lists`, `BuildLists.build_lists` and `LibraryMapLists.lists`. A player is
added or removed in all of them at once. Each build list is filed under its player's faction
name without the `Faction` prefix (`FactionMen` -> `Men`, `UNKNOWN` for no faction), as every
corpus map does.
"""

from __future__ import annotations

from sage_map.assets.library_map_lists import LibraryMaps
from sage_map.assets.player_scripts import ScriptList
from sage_map.assets.sides_list import BuildList, Player
from sage_map.assets.teams import Team
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command, CompositeCommand, SetAttribute
from sage_worldbuilder.commands.edits import InsertItem, RemoveItem, SetProperty
from sage_worldbuilder.properties import PLAYER_SPECS, PropertyValue, make_property
from sage_worldbuilder.teams import new_team, team_list, team_name, team_owner

__all__ = [
    "ALLY",
    "ENEMY",
    "NEUTRAL",
    "SKIRMISH_PLAYER_LIMIT",
    "add_player",
    "add_player_with_team",
    "add_skirmish_players",
    "build_list_owner",
    "join_relations",
    "library_map_path",
    "library_paths",
    "new_player",
    "numbered_player",
    "player_name",
    "regard",
    "relation_names",
    "remove_player",
    "set_player_faction",
    "teams_without_owner",
    "unique_player_name",
]

SIDES = Change(ChangeKind.SIDES)
ALLY, ENEMY, NEUTRAL = "Ally", "Enemy", "Neutral"
# Add Skirmish Players adds no player once the map has more than this many.
SKIRMISH_PLAYER_LIMIT = 18
_CIVILIAN_FACTION = "FactionCivilian"
_OPEN_SLOTS = 4
# How WorldBuilder's New Player names and displays the players it creates.
_NUMBERED_NAME = "player{:04d}"
_NUMBERED_DISPLAY = "Player {:04d}'s Display Name"
_SCRIPT_LIST_VERSION = 1
_LIBRARY_LIST_VERSION = 1
_FACTION_PREFIX = "Faction"
_NO_FACTION = "UNKNOWN"
_SPECS = {spec.name: spec for spec in PLAYER_SPECS}


def player_name(player: Player) -> str:
    stored = player.properties.get("playerName")
    return str(stored["value"]) if stored is not None else ""


def new_player(
    name: str, display_name: str = "", faction: str = "", is_human: bool = False
) -> Player:
    """A player with the six properties every map's players carry, in their stored order."""
    values: dict[str, PropertyValue] = {
        "playerName": name,
        "playerIsHuman": is_human,
        "playerDisplayName": display_name,
        "playerFaction": faction,
        "playerAllies": "",
        "playerEnemies": "",
    }
    properties = {key: make_property(_SPECS[key], value) for key, value in values.items()}
    return Player(properties=properties, build_list_items=[])


def numbered_player(map: Map) -> Player:
    """A player named the way WorldBuilder's New Player names one: the first free
    `player<NNNN>`, displayed as `Player <NNNN>'s Display Name`."""
    taken = {player_name(player).lower() for player in _players(map)}
    number = 1
    while _NUMBERED_NAME.format(number) in taken:
        number += 1
    return new_player(_NUMBERED_NAME.format(number), _NUMBERED_DISPLAY.format(number))


def unique_player_name(map: Map, base: str) -> str:
    taken = {player_name(player).lower() for player in _players(map)}
    if base.lower() not in taken:
        return base
    suffix = 2
    while f"{base}{suffix}".lower() in taken:
        suffix += 1
    return f"{base}{suffix}"


def _players(map: Map) -> list[Player]:
    return map.sides_list.players if map.sides_list is not None else []


def build_list_owner(faction: str) -> str:
    """The name a player's build list is filed under, for the player's `faction`."""
    return faction.removeprefix(_FACTION_PREFIX) or _NO_FACTION if faction else _NO_FACTION


def _owner_attribute(map: Map, owner: str) -> tuple[str, object]:
    # A map with an asset list names the owner as a string; one without, as a property key.
    if map.asset_list is not None:
        return "faction_name", owner
    return "faction_name_property", (AssetPropertyType.AsciiString, 0, owner)


def _new_build_list(map: Map, faction: str) -> BuildList:
    attribute, value = _owner_attribute(map, build_list_owner(faction))
    build_list = BuildList(faction_name=None, faction_name_property=None, build_list=[])
    setattr(build_list, attribute, value)
    return build_list


def add_player(map: Map, player: Player, offset: int = 0) -> Command:
    """Append `player`, with an empty script list, build list and library list for it wherever
    the map stores those. `offset` counts the players queued ahead of it in the same command,
    so each lands after the one before."""
    if map.sides_list is None:
        raise ValueError("the map has no players list")
    faction = str(player.properties.get("playerFaction", {"value": ""})["value"])
    commands: list[Command] = [
        InsertItem(map.sides_list.players, len(map.sides_list.players) + offset, player, SIDES)
    ]
    if map.player_scripts_list is not None:
        script_lists = map.player_scripts_list.script_lists
        empty = ScriptList(version=_SCRIPT_LIST_VERSION, items=[], start_pos=0, end_pos=0)
        commands.append(InsertItem(script_lists, len(script_lists) + offset, empty, SIDES))
    if map.build_lists is not None:
        build_lists = map.build_lists.build_lists
        new_list = _new_build_list(map, faction)
        commands.append(InsertItem(build_lists, len(build_lists) + offset, new_list, SIDES))
    if map.library_map_lists is not None:
        libraries = map.library_map_lists.lists
        version = libraries[0].version if libraries else _LIBRARY_LIST_VERSION
        new_library = LibraryMaps(version=version, values=[], start_pos=0, end_pos=0)
        commands.append(InsertItem(libraries, len(libraries) + offset, new_library, SIDES))
    return CompositeCommand(f"Add player {player_name(player)}", commands)


def add_player_with_team(map: Map, player: Player) -> Command:
    """Add `player` (see `add_player`) with its singleton `team<name>`, as WorldBuilder adds
    every new player; the team is left out when the map already has one of that name."""
    name = player_name(player)
    commands: list[Command] = [add_player(map, player)]
    teams = team_list(map)
    team = f"team{name}"
    if teams is not None and team.lower() not in {team_name(t).lower() for t in teams}:
        commands.append(InsertItem(teams, len(teams), new_team(team, name, True), SIDES))
    return CompositeCommand(f"Add player {name}", commands)


def add_skirmish_players(map: Map, factions: list[tuple[str, str]]) -> Command | None:
    """The players a skirmish map needs, added the way WorldBuilder's Add Skirmish Players adds
    them: `PlyrCivilian` and `PlyrCreeps`, a `Skirmish<Side>` player for each playable faction
    (given as `(template name, side)`), then `Player_1` to `Player_4`. Each is a computer player
    named and displayed alike, with its singleton `team<name>`. Names the map already has are
    skipped, and none is added once the map has more than `SKIRMISH_PLAYER_LIMIT` players.
    `None` when there is nothing to add."""
    if map.sides_list is None:
        raise ValueError("the map has no players list")
    wanted = [("PlyrCivilian", _CIVILIAN_FACTION), ("PlyrCreeps", _CIVILIAN_FACTION)]
    wanted += [(f"Skirmish{side}", template) for template, side in factions]
    wanted += [(f"Player_{slot}", _CIVILIAN_FACTION) for slot in range(1, _OPEN_SLOTS + 1)]
    players = map.sides_list.players
    taken = {player_name(player).lower() for player in players}
    teams = team_list(map)
    team_names = {team_name(team).lower() for team in teams or []}
    commands: list[Command] = []
    added = added_teams = 0
    for name, faction in wanted:
        if len(players) + added > SKIRMISH_PLAYER_LIMIT:
            break
        if name.lower() in taken:
            continue
        taken.add(name.lower())
        commands.append(add_player(map, new_player(name, name, faction), offset=added))
        added += 1
        team = f"team{name}"
        if teams is not None and team.lower() not in team_names:
            team_names.add(team.lower())
            singleton = new_team(team, name, True)
            commands.append(InsertItem(teams, len(teams) + added_teams, singleton, SIDES))
            added_teams += 1
    return CompositeCommand("Add Skirmish Players", commands) if commands else None


def remove_player(map: Map, index: int) -> Command:
    """Remove the player at `index` with its script, build and library lists. Its teams stay,
    and show up in `teams_without_owner` until they get a new owner or are deleted."""
    if map.sides_list is None:
        raise ValueError("the map has no players list")
    name = player_name(map.sides_list.players[index])
    commands: list[Command] = [RemoveItem(map.sides_list.players, index, SIDES)]
    parallel = [
        map.player_scripts_list.script_lists if map.player_scripts_list is not None else None,
        map.build_lists.build_lists if map.build_lists is not None else None,
        map.library_map_lists.lists if map.library_map_lists is not None else None,
    ]
    for entries in parallel:
        if entries is not None and index < len(entries):
            commands.append(RemoveItem(entries, index, SIDES))
    return CompositeCommand(f"Remove player {name}", commands)


def set_player_faction(map: Map, index: int, faction: str) -> Command:
    """Change a player's faction, and the name its build list is filed under with it."""
    if map.sides_list is None:
        raise ValueError("the map has no players list")
    player = map.sides_list.players[index]
    spec = _SPECS["playerFaction"]
    commands: list[Command] = [
        SetProperty(player.properties, spec.name, make_property(spec, faction), SIDES)
    ]
    if map.build_lists is not None and index < len(map.build_lists.build_lists):
        attribute, value = _owner_attribute(map, build_list_owner(faction))
        build_list = map.build_lists.build_lists[index]
        commands.append(SetAttribute(build_list, attribute, value, SIDES))
    return CompositeCommand("Set faction", commands)


def library_paths(map: Map, index: int) -> list[str] | None:
    """The library maps player `index` uses, as stored (`Libraries\\name\\name.map`)."""
    if map.library_map_lists is None or index >= len(map.library_map_lists.lists):
        return None
    return map.library_map_lists.lists[index].values


def library_map_path(name: str) -> str:
    return f"Libraries\\{name}\\{name}.map"


def relation_names(value: str) -> list[str]:
    """The player names in an allies or enemies property, which stores them space-separated."""
    return value.split()


def join_relations(names: list[str]) -> str:
    return " ".join(names)


def regard(player: Player, other: str) -> str:
    """How `player` regards the player named `other`: `ALLY`, `ENEMY` or `NEUTRAL`, from its
    allies and enemies."""
    folded = other.lower()
    for key, relation in (("playerAllies", ALLY), ("playerEnemies", ENEMY)):
        stored = player.properties.get(key)
        names = relation_names(str(stored["value"])) if stored is not None else []
        if folded in (name.lower() for name in names):
            return relation
    return NEUTRAL


def teams_without_owner(map: Map) -> list[Team]:
    """Teams whose owner is not one of the map's players, as WorldBuilder reports on load."""
    names = {player_name(player).lower() for player in _players(map)}
    return [team for team in team_list(map) or [] if team_owner(team).lower() not in names]
