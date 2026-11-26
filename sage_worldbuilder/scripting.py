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

from sage_ini.model.enums import FactionSide, ModelCondition, ObjectStatus
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
    named_values,
    parameter_values,
    template,
    template_named,
)

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = [
    "BOUNDARY_COLOURS",
    "NAMED_INDEX_TYPES",
    "SPECIAL_NAMES",
    "ActiveFlags",
    "ScriptItem",
    "ScriptLocation",
    "SentencePart",
    "active_flags",
    "argument_choices",
    "argument_text",
    "indexed_names",
    "item_matches",
    "item_template",
    "item_text",
    "iter_script_items",
    "NEW_GROUP_NAME",
    "NEW_SCRIPT_BASE",
    "map_symbols",
    "new_argument",
    "new_group",
    "new_item",
    "new_or_condition",
    "new_script",
    "new_script_name",
    "player_script_lists",
    "reset_active",
    "retarget",
    "script_matches",
    "sentence_parts",
    "string_text",
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
# What New Script and New Group start from (`0x01E0C574` and `0x01E0C564`).
NEW_SCRIPT_BASE = "Script"
NEW_GROUP_NAME = "New Folder"
# The number the next new script takes; see `new_script_name`.
_script_number = 0

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
    names = indexed_names(argument_type, {}) if argument_type in NAMED_INDEX_TYPES else None
    name = names[0] if names else ""
    return ScriptArgument(argument_type, int_value=0, float_value=0.0, string_value=name)


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
    if kind is ScriptArgumentType.BOUNDARY_NAME:
        return f"Boundary {BOUNDARY_COLOURS[(argument.int_value or 0) % len(BOUNDARY_COLOURS)]}"
    names = indexed_names(kind, {})
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


def is_living_world_script_map(map: Map) -> bool:
    """Whether the map's `isLivingWorldScriptHolder` flag is set - the maps whose scripts drive
    the Living World map, and the only ones WorldBuilder offers the Living World templates."""
    info = map.world_info.properties if map.world_info is not None else {}
    stored = info.get("isLivingWorldScriptHolder")
    return bool(stored["value"]) if stored is not None else False


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
    Counters, flags, attack priority sets, object type lists and map reveals have no declaration,
    so theirs are the names the map's scripts use. Boundaries are listed in index order, each by
    the colour WorldBuilder draws it in."""
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
        "cameras": set(),
        "camera_animations": set(),
        "attack_priority_sets": set(),
        "object_type_lists": set(),
        "map_reveals": set(),
    }
    if map.named_cameras is not None:
        found["cameras"].update(camera.name for camera in map.named_cameras.cameras if camera.name)
    if map.camera_animation_list is not None:
        found["camera_animations"].update(
            animation.name for animation in map.camera_animation_list.animations if animation.name
        )
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
        ScriptArgumentType.ATTACK_PRIORITY_SET_NAME: "attack_priority_sets",
        ScriptArgumentType.OBJECT_TYPE_LIST_NAME: "object_type_lists",
        ScriptArgumentType.MAP_REVEAL_NAME: "map_reveals",
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
    symbols = {key: sorted(names, key=str.casefold) for key, names in found.items()}
    borders = map.height_map_data.borders if map.height_map_data is not None else []
    symbols["boundaries"] = [
        BOUNDARY_COLOURS[index % len(BOUNDARY_COLOURS)] for index in range(len(borders))
    ]
    return symbols


# The colours WorldBuilder names a boundary by, cycling with its index: the dialog lists them
# (`0x01DF24F8`) and a sentence prints `Boundary <colour>` (`getUiText`, `0x01E688D0`).
BOUNDARY_COLOURS = ("Orange", "Green", "Blue", "Cyan", "Magenta", "Yellow", "Purple", "Pink")

# Index-stored types WorldBuilder also writes the chosen value's name beside, so a map holds both
# (`2` and `Friend`, `4` and `NO_COLLISIONS`).
NAMED_INDEX_TYPES = frozenset({ScriptArgumentType.RELATION, ScriptArgumentType.OBJECT_STATUS})

# The game tables WorldBuilder lists an asset name from: `enumerateAudioTypes` by audio type,
# `enumerateAllRealAudio`, `enumerateMovies` and `enumerateEvaEvents`. Picker choices only: the
# lint scope in `ARG_SPECS` stays literal.
_ASSET_TABLES: dict[ScriptArgumentType, tuple[str, ...]] = {
    ScriptArgumentType.SOUND_NAME: ("audioevents", "multisounds"),
    ScriptArgumentType.SPEECH_NAME: ("dialogevents",),
    ScriptArgumentType.MUSIC_NAME: ("musictracks",),
    ScriptArgumentType.AUDIO_NAME: ("audioevents", "multisounds", "dialogevents", "musictracks"),
    ScriptArgumentType.MOVIE_NAME: ("videos",),
    ScriptArgumentType.EVA: ("evaevents",),
}


def indexed_names(
    argument_type: int, symbols: Mapping[str, Sequence[str]]
) -> tuple[str, ...] | None:
    """The names of an index-stored argument's values, entry `i` naming value `i`: an engine enum,
    the engine's object statuses, or the map's boundaries. `None` for a type not stored by index."""
    if argument_type == ScriptArgumentType.BOUNDARY_NAME:
        return tuple(symbols.get("boundaries", ()))
    if argument_type == ScriptArgumentType.OBJECT_STATUS:
        return tuple(status.name for status in ObjectStatus)
    return parameter_values(argument_type)


def _named_choices(kind: ScriptArgumentType, game: Game | None) -> list[str]:
    """The names a name-stored enum offers: WorldBuilder's own tables, the engine's model
    conditions, or what the game defines (sides, notification types)."""
    names = named_values(kind)
    if names is not None:
        return list(names)
    if kind is ScriptArgumentType.MODEL_CONDITION:
        return [condition.name for condition in ModelCondition]
    if game is None:
        return []
    if kind is ScriptArgumentType.FACTION_NAME:
        return sorted(FactionSide.sides(game), key=str.casefold)
    if kind is ScriptArgumentType.OBJECTIVE_COMPLETE:
        return [
            notification.name
            for box in game.tables.get("ingamenotificationboxs", {}).values()
            for notification in getattr(box, "NotificationType", None) or ()
        ]
    return []


# The names WorldBuilder offers for a map symbol on top of the ones the map declares, by the
# `ARG_SPECS` map target that lists them, in the order its enumerators add them - before the
# map's own names (`ScriptParameterEnumerators.cpp`: `enumerateSides` `0x005DC630`,
# `enumerateTeams` `0x005DA4A0`, `enumerateUnits` `0x005DB860`, trigger areas `0x005DCC60`).
#
# They are not declarations, so nothing in the map ever matches one: `<This Player>` is the player
# whose scripts are running, `[Skirmish]MyInnerPerimeter` an area the skirmish AI makes at run
# time. A script that names one is right even though the map has no such thing, which is why they
# are offered here rather than reported as missing.
SPECIAL_NAMES: dict[str, tuple[str, ...]] = {
    "players": (
        "<Local Player>",
        "<Local Player's Enemy>",
        "<Local Player's Enemies>",
        "<Local Player's Allies>",
        "<Local Player's Allies incl Self>",
        "<This Player>",
        "<This Player's Enemy>",
        "<This Player's Enemies>",
        "<This Player's Allies>",
        "<This Player's Allies incl Self>",
        "<All Players>",
    ),
    "teams": ("<This Team>",),
    "units": ("<This Object>",),
    "trigger_areas": (
        "[Skirmish]MyInnerPerimeter",
        "[Skirmish]MyOuterPerimeter",
        "[Skirmish]EnemyOuterPerimeter",
        "[Skirmish]EnemyInnerPerimeter",
        "Water Grid",
    ),
}


def argument_choices(
    argument_type: int, symbols: Mapping[str, Sequence[str]], game: Game | None
) -> list[str]:
    """The names an argument of `argument_type` can pick: the map's own symbols, the game's
    definitions, its audio, movies and EVA events, its string labels, or a closed set stored by
    name, as `ARG_SPECS` resolves the type. Empty for a free value, or for game names when no game
    data is loaded.

    A map symbol is offered with the run-time names WorldBuilder offers beside it (`SPECIAL_NAMES`)
    - `<This Player>`, `<This Team>`, the skirmish perimeters - ahead of the map's own."""
    try:
        kind = ScriptArgumentType(argument_type)
    except ValueError:
        return []
    spec = arg_spec(kind)
    if spec.scope is Scope.MAP and spec.target is not None:
        declared = list(symbols.get(spec.target, ()))
        special = [
            name
            for name in SPECIAL_NAMES.get(spec.target, ())
            if name.casefold() not in {other.casefold() for other in declared}
        ]
        return special + declared
    if spec.scope is Scope.ENUM and spec.field == "string_value":
        return _named_choices(kind, game)
    if game is None:
        return []
    if spec.scope is Scope.GAME and spec.target is not None:
        return sorted(game.tables.get(spec.target, {}), key=str.casefold)
    if kind in _ASSET_TABLES:
        names = {name for table in _ASSET_TABLES[kind] for name in game.tables.get(table, {})}
        return sorted(names, key=str.casefold)
    if spec.scope is Scope.STRINGS:
        return sorted(game.strings, key=str.casefold)
    return []


def string_text(game: Game, label: str) -> str | None:
    """The text a string label stands for, matched as written and then ignoring case; `None` when
    the game has no such label."""
    text = game.strings.get(label)
    if text is not None:
        return text
    folded = label.casefold()
    for name, value in game.strings.items():
        if name.casefold() == folded:
            return value
    return None


def _taken_names(map: Map) -> set[str]:
    return {
        location.item.name.lower()
        for _, script_list in player_script_lists(map)
        for location in iter_script_items(script_list.items)
    }


def _free_name(base: str, taken: set[str]) -> str:
    """WorldBuilder's `makeUnique` (`0x005C0F60` for groups, `0x005C08E0` for scripts): the name
    itself when it is free, else the name, a space and the lowest free number from 1 (`"%s %d"`)."""
    if base.lower() not in taken:
        return base
    suffix = 1
    while f"{base} {suffix}".lower() in taken:
        suffix += 1
    return f"{base} {suffix}"


def unique_script_name(map: Map, base: str) -> str:
    """`base`, or `base` with the lowest free ` n` suffix, unused by any script or group."""
    return _free_name(base, _taken_names(map))


def new_script_name(map: Map) -> str:
    """The name New Script gives: `Script <n>`, counting up until the map has no script or group
    by that name (`ScriptDialog::Impl::TreeItem::insertNew`, `0x005CFF8F`).

    The counter is the editor's, not the map's: WorldBuilder keeps it in a global that only ever
    goes up, so a number is never offered twice in one session even after the script that took it
    is deleted."""
    global _script_number  # noqa: PLW0603 - WorldBuilder's own session-wide counter
    taken = _taken_names(map)
    while True:
        _script_number += 1
        name = f"{NEW_SCRIPT_BASE} {_script_number}"
        if name.lower() not in taken:
            return name


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
