"""Turning a scenario's scripts, waypoints and trigger areas into map data.

Every script goes into a group named `sage_test` on its side's script list, under the name
`sage_test.<name>`, so it cannot collide with a script the template map already carries. The items
are built with the editor's own constructors (`sage_worldbuilder.scripting`), with the chunk
versions every RotWK map uses, so the generated map opens in WorldBuilder like an authored one.

What makes a script drivable from a test is two choices made here:

- a **trigger** is written *inactive* and one-shot. The harness fires it by writing the live
  active flag (`SCRIPT_ACTIVE`), which needs no hook in the game; the engine clears the flag again
  when the script fires.
- every script **ends by adding one to the counter `sage_test.<name>`**. A counter exists only
  once a script has touched it, so the counter appearing and rising is the receipt that the
  actions ran, and its value is how many times.

Arguments are checked against the template's parameters here, before anything launches: a wrong
count, a wrong type or an unknown enum value raises with the script, the item and the argument
named.
"""

from __future__ import annotations

from collections.abc import Sequence

from sage_map.assets.object_list import Object
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
from sage_map.scripts import arg_spec
from sage_test.scenario import Action, Condition, Scenario, ScriptDecl, Value
from sage_worldbuilder.areas import new_area
from sage_worldbuilder.scripting import (
    new_group,
    new_item,
    new_or_condition,
    new_script,
    player_script_lists,
)
from sage_worldbuilder.templates import (
    ParameterType,
    TemplateKind,
    parameter_values,
    template_named,
)
from sage_worldbuilder.waypoints import new_waypoint

__all__ = [
    "GROUP",
    "PREFIX",
    "ScriptCompileError",
    "build_script",
    "compile_scripts",
    "counter_name",
    "script_name",
]

#: The group every scenario script goes into, and the prefix on its name and its counter.
GROUP = "sage_test"
PREFIX = "sage_test."

#: Comparisons as a test writes them, by the index the map stores (`Less Than` .. `Not Equal To`).
_COMPARISONS = {"<": 0, "<=": 1, "==": 2, ">=": 3, ">": 4, "!=": 5}


class ScriptCompileError(ValueError):
    """A declared script that cannot be written: unknown template, wrong arguments, no side."""


def script_name(name: str) -> str:
    return f"{PREFIX}{name}"


def counter_name(name: str) -> str:
    """The counter a scenario script's last action raises."""
    return f"{PREFIX}{name}"


def _int_value(kind: ScriptArgumentType, value: Value, where: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if kind is ScriptArgumentType.COMPARISON and value in _COMPARISONS:
            return _COMPARISONS[value]
        names = parameter_values(kind)
        if names is not None:
            folded = [n.lower() for n in names]
            if value.lower() in folded:
                return folded.index(value.lower())
            raise ScriptCompileError(f"{where}: {value!r} is not one of {list(names)}")
    raise ScriptCompileError(f"{where}: {kind.name} takes an integer, not {value!r}")


def build_argument(parameter: ParameterType, value: Value, where: str) -> ScriptArgument:
    """One argument, with `value` in the slot the parameter type stores it in."""
    kind = ScriptArgumentType.INTEGER if parameter is None else ScriptArgumentType(parameter)
    field = arg_spec(kind).field
    if field == "position_value":
        if not isinstance(value, tuple) or len(value) not in (2, 3):
            raise ScriptCompileError(f"{where}: a position is (x, y) or (x, y, z), not {value!r}")
        x, y, *rest = (float(v) for v in value)
        return ScriptArgument(kind, position_value=(x, y, rest[0] if rest else 0.0))
    argument = ScriptArgument(kind, int_value=0, float_value=0.0, string_value="")
    if field == "string_value":
        if not isinstance(value, str):
            raise ScriptCompileError(f"{where}: {kind.name} takes a name, not {value!r}")
        argument.string_value = value
    elif field == "float_value":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ScriptCompileError(f"{where}: {kind.name} takes a number, not {value!r}")
        argument.float_value = float(value)
    else:
        argument.int_value = _int_value(kind, value, where)
    return argument


def _item(kind: TemplateKind, name: str, args: Sequence[Value], where: str) -> ScriptDerived:
    entry = template_named(kind, name)
    if entry is None:
        raise ScriptCompileError(f"{where}: no {kind.value} template is named {name!r}")
    if len(args) != len(entry.parameters):
        wanted = ", ".join(str(getattr(p, "name", p)) for p in entry.parameters) or "nothing"
        raise ScriptCompileError(
            f"{where}: {name} takes {len(entry.parameters)} arguments ({wanted}), got {len(args)}"
        )
    item = new_item(entry)
    item.arguments = [
        build_argument(parameter, value, f"{where} {name} argument {index + 1}")
        for index, (parameter, value) in enumerate(zip(entry.parameters, args, strict=True))
    ]
    return item


def _action(action: Action, where: str) -> ScriptDerived:
    return _item(TemplateKind.ACTION, action.name, action.args, where)


def _condition(condition: Condition, where: str) -> ScriptDerived:
    item = _item(TemplateKind.CONDITION, condition.name, condition.args, where)
    item.is_inverted = condition.inverted
    return item


def build_script(decl: ScriptDecl) -> Script:
    """The `Script` for one declaration, receipt counter included."""
    where = f"script {decl.name!r}"
    script = new_script(script_name(decl.name))
    script.is_active = decl.probe
    script.deactivate_upon_success = decl.once or not decl.probe
    script.evaluation_interval = decl.every
    clauses: list[OrCondition] = []
    for clause in decl.clauses or ((Condition("CONDITION_TRUE"),),):
        built = new_or_condition()
        built.conditions = [_condition(condition, where) for condition in clause]
        clauses.append(built)
    script.or_conditions = clauses
    receipt = Action("INCREMENT_COUNTER", (1, counter_name(decl.name)))
    script.actions_if_true = [_action(action, where) for action in (*decl.actions, receipt)]
    return script


def _side_list(scenario: Scenario, template: Map, decl: ScriptDecl) -> ScriptList:
    if decl.side is None:
        side = ""
    elif isinstance(decl.side, int):
        side = scenario.seats[decl.side].map_player
    else:
        side = decl.side
    lists = player_script_lists(template)
    for name, script_list in lists:
        if name.lower() == side.lower():
            return script_list
    sides = ", ".join(repr(name) for name, _ in lists) or "none"
    raise ScriptCompileError(f"script {decl.name!r}: the map has no side {side!r} ({sides})")


def _group(script_list: ScriptList) -> ScriptGroup:
    for item in script_list.items:
        if isinstance(item, ScriptGroup) and item.name == GROUP:
            return item
    group = new_group(GROUP)
    script_list.items.append(group)
    return group


def _named(obj: Object, key: str, value: str) -> None:
    obj.properties[key] = {"name": key, "type": AssetPropertyType.AsciiString, "value": value}


def _compile_waypoints(scenario: Scenario, template: Map) -> None:
    if not scenario.waypoints:
        return
    if template.objects_list is None:
        raise ScriptCompileError("the template map has no ObjectsList for waypoints")
    taken = {
        str(obj.properties["waypointName"]["value"]).lower()
        for obj in template.objects_list.object_list
        if "waypointName" in obj.properties
    }
    for waypoint in scenario.waypoints:
        if waypoint.name.lower() in taken:
            raise ScriptCompileError(f"the template map already has a waypoint {waypoint.name!r}")
        obj = new_waypoint(template, waypoint.at)
        _named(obj, "waypointName", waypoint.name)
        _named(obj, "uniqueID", waypoint.name)
        template.objects_list.object_list.append(obj)


def _compile_areas(scenario: Scenario, template: Map) -> None:
    if not scenario.areas:
        return
    if template.trigger_areas is None:
        raise ScriptCompileError("the template map has no TriggerAreas chunk")
    listed = template.trigger_areas.trigger_areas
    taken = {area.name.lower() for area in listed}
    for area in scenario.areas:
        if area.name.lower() in taken:
            raise ScriptCompileError(f"the template map already has an area {area.name!r}")
        built = new_area(template, area.points)
        built.name = area.name
        listed.append(built)


def compile_scripts(scenario: Scenario, template: Map) -> Map:
    """Add `scenario`'s waypoints, trigger areas and scripts to `template`, in place.

    Every script is built and its side found before anything is added, so a declaration that
    fails leaves the map as it was.
    """
    if scenario.scripts and template.player_scripts_list is None:
        raise ScriptCompileError("the template map has no PlayerScriptsList")
    built = [(decl, build_script(decl)) for decl in scenario.scripts]
    targets = [_side_list(scenario, template, decl) for decl, _ in built]
    _compile_waypoints(scenario, template)
    _compile_areas(scenario, template)
    for (_, script), script_list in zip(built, targets, strict=True):
        _group(script_list).items.append(script)
    return template
