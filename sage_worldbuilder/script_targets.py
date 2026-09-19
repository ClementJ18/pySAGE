"""What a script argument points at, so the editor can go there.

An argument already carries the type tag that says what it names (`sage_map.scripts.ARG_SPECS`
turns the tag into a map-local table), so the stored value and the map are enough to find the
thing itself: the placed object an `OBJECT_NAME` names, the trigger area a `TRIGGER_AREA_NAME`
names, the script a `SUBROUTINE_NAME` calls. `argument_target` is that lookup; the UI turns each
result into a Go To button and hands it back to the window, which knows how to show each kind.

Only the types that name something the map declares resolve here. Counters and flags have no
declaration to go to, and an argument naming an ini definition (an object type, an upgrade) is
not somewhere the map can take you.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sage_map.assets.player_scripts import ScriptArgument, ScriptArgumentType
from sage_map.map import Map
from sage_map.scripts import Scope, arg_spec
from sage_worldbuilder.scripting import iter_script_items, player_script_lists
from sage_worldbuilder.teams import qualified_team_name, team_list

__all__ = ["ScriptTarget", "TargetKind", "argument_target", "navigable", "target_kind"]


class TargetKind(StrEnum):
    """What the editor has to show to take the mapper to a target; the value is how a button
    names it."""

    OBJECT = "object"
    WAYPOINT = "waypoint"
    WAYPOINT_PATH = "waypoint path"
    AREA = "area"
    TEAM = "team"
    PLAYER = "player"
    SCRIPT = "script"


@dataclass(frozen=True)
class ScriptTarget:
    """Something an argument names, found in the map.

    `name` is the name as the map stores it, not as the argument spells it, so a button reads
    what the mapper will see when they get there. `sources` are the map items to select - several
    for a waypoint path, which is a label its waypoints share - and `position` is where to centre
    the view, `None` for a target that is shown in a panel rather than on the map.
    """

    kind: TargetKind
    name: str
    sources: tuple[object, ...] = ()
    position: tuple[float, float] | None = None

    @property
    def label(self) -> str:
        """What a Go To button or menu entry for this target reads."""
        return f"Go to {self.kind.value} '{self.name}'"


# The map-local table an argument resolves against -> what going there means. The tables left out
# (`counters`, `flags`, `attack_priority_sets`, `boundaries`) name things nothing in the map
# declares, so there is nowhere to go.
_KINDS = {
    "units": TargetKind.OBJECT,
    "waypoints": TargetKind.WAYPOINT,
    "waypoint_paths": TargetKind.WAYPOINT_PATH,
    "trigger_areas": TargetKind.AREA,
    "teams": TargetKind.TEAM,
    "players": TargetKind.PLAYER,
    "scripts": TargetKind.SCRIPT,
}
_PATH_LABELS = ("waypointPathLabel1", "waypointPathLabel2", "waypointPathLabel3")


def target_kind(argument_type: int) -> TargetKind | None:
    """What an argument of this type names, or `None` for one that names nothing to go to."""
    try:
        kind = ScriptArgumentType(argument_type)
    except ValueError:
        return None
    spec = arg_spec(kind)
    if spec.scope is not Scope.MAP or spec.target is None:
        return None
    return _KINDS.get(spec.target)


def navigable(argument_type: int) -> bool:
    """Whether an argument of this type can name something to go to, whatever it holds now."""
    return target_kind(argument_type) is not None


def argument_target(argument: ScriptArgument, map: Map) -> ScriptTarget | None:
    """What `argument` points at in `map`, or `None` when it names nothing the map has - an empty
    argument, a type that names nothing to go to, or a name no longer in the map."""
    kind = target_kind(argument.type)
    name = (argument.string_value or "").strip()
    if kind is None or not name:
        return None
    return _FINDERS[kind](name, map)


def _text(properties: dict, key: str) -> str:
    stored = properties.get(key)
    return str(stored["value"]) if stored is not None and stored["value"] else ""


def _placed(map: Map) -> list:
    return map.objects_list.object_list if map.objects_list is not None else []


def _centre(positions: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not positions:
        return None
    return (
        sum(x for x, _ in positions) / len(positions),
        sum(y for _, y in positions) / len(positions),
    )


def _by_property(name: str, map: Map, key: str, kind: TargetKind) -> ScriptTarget | None:
    folded = name.casefold()
    for placed in _placed(map):
        stored = _text(placed.properties, key)
        if stored.casefold() == folded:
            x, y, _z = placed.position
            return ScriptTarget(kind, stored, (placed,), (float(x), float(y)))
    return None


def _find_object(name: str, map: Map) -> ScriptTarget | None:
    return _by_property(name, map, "objectName", TargetKind.OBJECT)


def _find_waypoint(name: str, map: Map) -> ScriptTarget | None:
    return _by_property(name, map, "waypointName", TargetKind.WAYPOINT)


def _find_waypoint_path(name: str, map: Map) -> ScriptTarget | None:
    """Every waypoint carrying the label; the view centres on the path as a whole."""
    folded = name.casefold()
    found = []
    label = name
    for placed in _placed(map):
        stored = next(
            (
                value
                for key in _PATH_LABELS
                if (value := _text(placed.properties, key)).casefold() == folded
            ),
            None,
        )
        if stored is not None:
            label = stored
            found.append(placed)
    if not found:
        return None
    positions = [(float(placed.position[0]), float(placed.position[1])) for placed in found]
    return ScriptTarget(TargetKind.WAYPOINT_PATH, label, tuple(found), _centre(positions))


def _find_area(name: str, map: Map) -> ScriptTarget | None:
    folded = name.casefold()
    areas: list = []
    if map.polygon_triggers is not None:
        areas += map.polygon_triggers.polygon_triggers
    if map.trigger_areas is not None:
        areas += map.trigger_areas.trigger_areas
    for area in areas:
        if area.name.casefold() == folded:
            points = [(float(point[0]), float(point[1])) for point in getattr(area, "points", [])]
            return ScriptTarget(TargetKind.AREA, area.name, (area,), _centre(points))
    return None


def _find_team(name: str, map: Map) -> ScriptTarget | None:
    """Teams are named `owner/team` in scripts; a bare name matches the team part alone, which is
    how a mapper usually types one."""
    folded = name.casefold()
    for team in team_list(map) or []:
        qualified = qualified_team_name(team)
        if folded in (qualified.casefold(), qualified.split("/", 1)[-1].casefold()):
            return ScriptTarget(TargetKind.TEAM, qualified, (team,))
    return None


def _find_player(name: str, map: Map) -> ScriptTarget | None:
    folded = name.casefold()
    players = map.sides_list.players if map.sides_list is not None else []
    for player in players:
        stored = _text(player.properties, "playerName")
        if stored.casefold() == folded:
            return ScriptTarget(TargetKind.PLAYER, stored, (player,))
    return None


def _find_script(name: str, map: Map) -> ScriptTarget | None:
    folded = name.casefold()
    for _, script_list in player_script_lists(map):
        for location in iter_script_items(script_list.items):
            if location.item.name.casefold() == folded:
                return ScriptTarget(TargetKind.SCRIPT, location.item.name, (location.item,))
    return None


_FINDERS = {
    TargetKind.OBJECT: _find_object,
    TargetKind.WAYPOINT: _find_waypoint,
    TargetKind.WAYPOINT_PATH: _find_waypoint_path,
    TargetKind.AREA: _find_area,
    TargetKind.TEAM: _find_team,
    TargetKind.PLAYER: _find_player,
    TargetKind.SCRIPT: _find_script,
}
