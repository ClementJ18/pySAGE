"""Building and describing script items.

New scripts, groups, conditions and actions are created the way the map format stores them, with
the chunk versions every RotWK map uses. Each item is described by the sentence its template
gives, filled with its arguments' values.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_map.assets.player_scripts import (
    OrCondition,
    Script,
    ScriptArgument,
    ScriptArgumentType,
    ScriptDerived,
    ScriptGroup,
    ScriptList,
)
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_map.scripts import Scope, arg_spec
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command, CompositeCommand, SetAttribute
from sage_worldbuilder.templates import (
    ParameterType,
    ScriptTemplate,
    TemplateKind,
    parameter_values,
    template,
    template_named,
)

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = [
    "ActiveFlags",
    "ScriptItem",
    "ScriptLocation",
    "SentencePart",
    "active_flags",
    "argument_choices",
    "argument_text",
    "item_matches",
    "item_template",
    "item_text",
    "iter_script_items",
    "map_symbols",
    "new_argument",
    "new_group",
    "new_item",
    "new_or_condition",
    "new_script",
    "player_script_lists",
    "reset_active",
    "retarget",
    "script_matches",
    "sentence_parts",
    "unique_script_name",
]

# The chunk versions of every script item in RotWK maps; a new item uses the same.
SCRIPT_VERSION = 4
GROUP_VERSION = 3
OR_CONDITION_VERSION = 1
CONDITION_VERSION = 6
ACTION_VERSION = 3
# `ScriptDerived.parse` arguments: from which version a condition or action carries its internal
# name, its enabled flag and (conditions only) its inverted flag.
_LAYOUT = {TemplateKind.CONDITION: (4, 5, True), TemplateKind.ACTION: (2, 3, False)}
# The evaluation-interval type every version-4 script stores.
_EVALUATION_INTERVAL_TYPE = 6
_SCRIPT_UNKNOWN = "ALL"

ScriptItem = Script | ScriptGroup


def new_script(name: str) -> Script:
    return Script(
        name=name,
        comment="",
        conditions_comment="",
        actions_comment="",
        is_active=True,
        deactivate_upon_success=False,
        active_in_easy=True,
        active_in_medium=True,
        active_in_hard=True,
        is_subroutine=False,
        version=SCRIPT_VERSION,
        start_pos=0,
        end_pos=0,
        evaluation_interval=0,
        evaluation_interval_type=_EVALUATION_INTERVAL_TYPE,
        actions_fire_sequentially=False,
        loop_actions=False,
        loop_count=0,
        sequential_target_type=True,
        sequential_target_name="",
        unknown=_SCRIPT_UNKNOWN,
        or_conditions=[new_or_condition()],
    )


def new_group(name: str) -> ScriptGroup:
    return ScriptGroup(
        version=GROUP_VERSION,
        name=name,
        is_active=True,
        is_subroutine=False,
        start_pos=0,
        end_pos=0,
    )


def new_or_condition() -> OrCondition:
    return OrCondition(version=OR_CONDITION_VERSION, conditions=[], start_pos=0, end_pos=0)


def new_argument(parameter_type: ParameterType) -> ScriptArgument:
    """A zeroed argument of `parameter_type`. A slot the template never filled holds an integer,
    which is what maps store for it."""
    if parameter_type is None:
        argument_type = ScriptArgumentType.INTEGER
    else:
        argument_type = ScriptArgumentType(parameter_type)
    if argument_type is ScriptArgumentType.POSITION_COORDINATE:
        return ScriptArgument(argument_type, position_value=(0.0, 0.0, 0.0))
    return ScriptArgument(argument_type, int_value=0, float_value=0.0, string_value="")


def new_item(entry: ScriptTemplate) -> ScriptDerived:
    """A condition or action for `entry` with default arguments."""
    name_version, enabled_version, has_inverted = _LAYOUT[entry.kind]
    return ScriptDerived(
        version=CONDITION_VERSION if entry.kind is TemplateKind.CONDITION else ACTION_VERSION,
        content_type=entry.id,
        internal_name=(AssetPropertyType.AsciiString, 0, entry.internal_name),
        arguments=[new_argument(parameter) for parameter in entry.parameters],
        is_enabled=True,
        is_inverted=False if has_inverted else None,
        has_internal_name_version=name_version,
        has_is_enabled_version=enabled_version,
        has_is_inverted=has_inverted,
    )


def retarget(item: ScriptDerived, entry: ScriptTemplate) -> ScriptDerived:
    """A copy of `item` switched to `entry`, keeping each argument whose position and type still
    fit, and the enabled and inverted flags."""
    changed = new_item(entry)
    for index, argument in enumerate(changed.arguments):
        if index < len(item.arguments) and item.arguments[index].type == argument.type:
            changed.arguments[index] = copy.deepcopy(item.arguments[index])
    changed.is_enabled = item.is_enabled
    if changed.has_is_inverted:
        changed.is_inverted = item.is_inverted
    return changed


def item_template(item: ScriptDerived, kind: TemplateKind) -> ScriptTemplate | None:
    """The template a stored item uses: by its id, or by its name when the id is unknown."""
    found = template(kind, item.content_type)
    if found is None and item.internal_name is not None and item.internal_name[2]:
        found = template_named(kind, item.internal_name[2])
    return found


def argument_text(argument: ScriptArgument) -> str:
    """How an argument's value reads inside a sentence."""
    kind = argument.type
    if kind is ScriptArgumentType.POSITION_COORDINATE:
        x, y, z = argument.position_value or (0.0, 0.0, 0.0)
        return f"({x:.2f}, {y:.2f}, {z:.2f})"
    if kind in (ScriptArgumentType.REAL_NUMBER, ScriptArgumentType.PERCENTAGE):
        return f"{argument.float_value or 0.0:g}"
    if kind is ScriptArgumentType.ANGLE:
        return f"{argument.float_value or 0.0:g} degrees"
    names = parameter_values(kind)
    if names is not None:
        value = argument.int_value or 0
        return names[value] if 0 <= value < len(names) else str(value)
    if argument.string_value:
        return argument.string_value
    if kind is ScriptArgumentType.INTEGER or argument.int_value:
        return str(argument.int_value or 0)
    return "???"


SentencePart = tuple[str, int | None]


def sentence_parts(item: ScriptDerived, kind: TemplateKind) -> list[SentencePart]:
    """The sentence of a condition or action in pieces: `(text, None)` for the template's own
    words, `(value, index)` for argument `index`, so a view can mark the arguments out."""
    entry = item_template(item, kind)
    if entry is None:
        name = item.internal_name[2] if item.internal_name else None
        return [(f"[unknown {kind.value} {item.content_type}{f' {name}' if name else ''}]", None)]
    parts: list[SentencePart] = []
    for index, fragment in enumerate(entry.ui_strings):
        if fragment:
            parts.append((fragment, None))
        if index < len(entry.parameters) and index < len(item.arguments):
            parts.append((argument_text(item.arguments[index]), index))
    # The fragments pad the sentence with spaces at either end; trim those, never an argument.
    while parts and parts[0][1] is None and not parts[0][0].strip():
        parts.pop(0)
    while parts and parts[-1][1] is None and not parts[-1][0].strip():
        parts.pop()
    if parts and parts[0][1] is None:
        parts[0] = (parts[0][0].lstrip(), None)
    if parts and parts[-1][1] is None:
        parts[-1] = (parts[-1][0].rstrip(), None)
    if item.is_inverted:
        parts.insert(0, ("NOT ", None))
    return parts


def item_text(item: ScriptDerived, kind: TemplateKind) -> str:
    """The sentence WorldBuilder lists for a condition or action."""
    return "".join(text for text, _ in sentence_parts(item, kind))


def player_script_lists(map: Map) -> list[tuple[str, ScriptList]]:
    """Each player's name with its script list; the lists are stored in player order."""
    if map.player_scripts_list is None:
        return []
    players = map.sides_list.players if map.sides_list is not None else []
    named = []
    for index, script_list in enumerate(map.player_scripts_list.script_lists):
        name = ""
        if index < len(players):
            value = players[index].properties.get("playerName")
            name = str(value["value"]) if value is not None else ""
        named.append((name, script_list))
    return named


@dataclass(frozen=True)
class ScriptLocation:
    """Where a script or group sits: the list holding it and its index in that list."""

    items: list[ScriptItem]
    index: int
    item: ScriptItem
    depth: int


def iter_script_items(items: list[ScriptItem], depth: int = 0) -> Iterator[ScriptLocation]:
    """Every script and group under `items`, depth first, each with the list that holds it."""
    for index, item in enumerate(items):
        yield ScriptLocation(items, index, item, depth)
        if isinstance(item, ScriptGroup):
            yield from iter_script_items(item.items, depth + 1)


# Each script and group with its Active flag, as `active_flags` records them.
ActiveFlags = list[tuple[ScriptItem, bool]]


def active_flags(map: Map) -> ActiveFlags:
    """Every script's and group's Active flag, for `reset_active` to put back later."""
    return [
        (location.item, location.item.is_active)
        for _, script_list in player_script_lists(map)
        for location in iter_script_items(script_list.items)
    ]


def reset_active(map: Map, flags: ActiveFlags) -> Command | None:
    """Put the Active flag of every script and group still in the map back to its value in
    `flags`, as WorldBuilder's Reset Active does with the flags the map was loaded with. Scripts
    added since keep theirs. `None` when every flag already matches."""
    present = {id(item) for item, _ in active_flags(map)}
    commands: list[Command] = [
        SetAttribute(item, "is_active", active, Change(ChangeKind.SCRIPTS))
        for item, active in flags
        if id(item) in present and item.is_active != active
    ]
    return CompositeCommand("Reset Active", commands) if commands else None


def _property_text(properties: dict, name: str) -> str | None:
    value = properties.get(name)
    if value is None or value["value"] in (None, ""):
        return None
    return str(value["value"])


def map_symbols(map: Map) -> dict[str, list[str]]:
    """The names a script argument can pick from this map, as written, keyed by the `ARG_SPECS`
    map target they answer for. Teams are listed as `owner/team`, the form scripts store.
    Counters and flags have no declaration, so theirs are the names the map's scripts use."""
    found: dict[str, set[str]] = {
        "teams": set(),
        "players": set(),
        "waypoints": set(),
        "waypoint_paths": set(),
        "trigger_areas": set(),
        "units": set(),
        "scripts": set(),
        "counters": set(),
        "flags": set(),
    }
    teams = list(map.teams.teams) if map.teams is not None else []
    if map.sides_list is not None:
        teams += map.sides_list.teams
        for player in map.sides_list.players:
            if (name := _property_text(player.properties, "playerName")) is not None:
                found["players"].add(name)
    for team in teams:
        if (name := _property_text(team.properties, "teamName")) is not None:
            owner = _property_text(team.properties, "teamOwner") or ""
            found["teams"].add(f"{owner}/{name}")
    if map.objects_list is not None:
        for placed in map.objects_list.object_list:
            if (name := _property_text(placed.properties, "waypointName")) is not None:
                found["waypoints"].add(name)
            if (name := _property_text(placed.properties, "objectName")) is not None:
                found["units"].add(name)
            for label in ("waypointPathLabel1", "waypointPathLabel2", "waypointPathLabel3"):
                if (name := _property_text(placed.properties, label)) is not None:
                    found["waypoint_paths"].add(name)
    if map.polygon_triggers is not None:
        found["trigger_areas"].update(area.name for area in map.polygon_triggers.polygon_triggers)
    if map.trigger_areas is not None:
        found["trigger_areas"].update(area.name for area in map.trigger_areas.trigger_areas)
    declared_by_argument = {
        ScriptArgumentType.COUNTER_NAME: "counters",
        ScriptArgumentType.FLAG_NAME: "flags",
    }
    for _, script_list in player_script_lists(map):
        for location in iter_script_items(script_list.items):
            found["scripts"].add(location.item.name)
            if not isinstance(location.item, Script):
                continue
            script = location.item
            items = [c for group in script.or_conditions for c in group.conditions]
            for item in items + script.actions_if_true + script.actions_if_false:
                for argument in item.arguments:
                    target = declared_by_argument.get(argument.type)
                    if target is not None and argument.string_value:
                        found[target].add(argument.string_value)
    return {key: sorted(names, key=str.casefold) for key, names in found.items()}


def argument_choices(
    argument_type: int, symbols: Mapping[str, Sequence[str]], game: Game | None
) -> list[str]:
    """The names an argument of `argument_type` can pick: the map's own symbols, the game's
    definitions, or its string labels, as `ARG_SPECS` resolves the type. Empty for a free value,
    or for game names when no game data is loaded."""
    try:
        kind = ScriptArgumentType(argument_type)
    except ValueError:
        return []
    spec = arg_spec(kind)
    if spec.scope is Scope.MAP and spec.target is not None:
        return list(symbols.get(spec.target, ()))
    if game is None:
        return []
    if spec.scope is Scope.GAME and spec.target is not None:
        return sorted(game.tables.get(spec.target, {}), key=str.casefold)
    if spec.scope is Scope.STRINGS:
        return sorted(game.strings, key=str.casefold)
    return []


def _taken_names(map: Map) -> set[str]:
    return {
        location.item.name.lower()
        for _, script_list in player_script_lists(map)
        for location in iter_script_items(script_list.items)
    }


def _free_name(base: str, taken: set[str]) -> str:
    if base.lower() not in taken:
        return base
    suffix = 2
    while f"{base} ({suffix})".lower() in taken:
        suffix += 1
    return f"{base} ({suffix})"


def unique_script_name(map: Map, base: str) -> str:
    """`base`, or `base` with the lowest free ` (n)` suffix, unused by any script or group."""
    return _free_name(base, _taken_names(map))


def item_matches(item: ScriptDerived, kind: TemplateKind, needle: str, whole: bool = False) -> bool:
    """Whether a condition or action mentions `needle`, ignoring case: anywhere in its sentence or
    internal name, or, with `whole`, as the entire value of one of its arguments."""
    folded = needle.casefold()
    if whole:
        return any(argument_text(argument).casefold() == folded for argument in item.arguments)
    name = item.internal_name[2] if item.internal_name is not None else None
    return folded in item_text(item, kind).casefold() or folded in (name or "").casefold()


def script_matches(item: ScriptItem, needle: str, whole: bool = False) -> bool:
    """Whether a script mentions `needle` in its name or any condition or action (see
    `item_matches`); a group matches by its name alone."""
    if not needle:
        return True
    if not whole and needle.casefold() in item.name.casefold():
        return True
    if not isinstance(item, Script):
        return False
    conditions = [condition for group in item.or_conditions for condition in group.conditions]
    return any(
        item_matches(condition, TemplateKind.CONDITION, needle, whole) for condition in conditions
    ) or any(
        item_matches(action, TemplateKind.ACTION, needle, whole)
        for action in item.actions_if_true + item.actions_if_false
    )
