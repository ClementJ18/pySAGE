"""Typed access to the property dictionaries the map, its players and its teams carry.

A property is stored as `{"name", "type", "value"}` with an `AssetPropertyType`. A `PropertySpec`
gives a key its stored type, a label, a default and, for an enumerated value, the names of its
values, so every form writes exactly the type the game reads back.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from sage_ini.model.enums import MapWeatherType
from sage_map.context import AssetPropertyType, Property
from sage_worldbuilder.changes import Change
from sage_worldbuilder.commands.edits import SetProperty

__all__ = [
    "OBJECT_SPECS",
    "PLAYER_SPECS",
    "PropertyValue",
    "TEAM_SPECS",
    "TEAM_UNIT_SLOTS",
    "WAYPOINT_SPECS",
    "WAYPOINT_TYPE_NAMES",
    "WORLD_INFO_SPECS",
    "Editor",
    "PropertySpec",
    "make_property",
    "set_value",
    "team_generic_script_spec",
    "team_unit_specs",
    "value_of",
    "weather_names",
]

PropertyValue = str | int | float | bool

_TEXT_TYPES = (AssetPropertyType.AsciiString, AssetPropertyType.UnicodeString)


class Editor(Enum):
    TEXT = "text"
    INTEGER = "integer"
    REAL = "real"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    PRESET = "preset"


@dataclass(frozen=True)
class PropertySpec:
    name: str
    label: str
    type: AssetPropertyType
    default: PropertyValue
    # For an Integer that enumerates: the name of each value, in value order. A callable is
    # re-read every time a form reloads, for a list the engine can grow.
    choices: tuple[str, ...] | Callable[[], tuple[str, ...]] | None = None
    # The value the first choice stands for (aggressiveness counts from -3).
    choice_base: int = 0
    # For an Integer with named common values: each name and its value. Any other value is
    # "Other", typed in; `other` is what choosing Other from a preset starts at.
    presets: tuple[tuple[str, int], ...] | None = None
    other: int = 0

    def choice_names(self) -> tuple[str, ...]:
        """The names of this spec's values, resolving a callable list."""
        if callable(self.choices):
            return self.choices()
        return self.choices or ()

    @property
    def editor(self) -> Editor:
        if self.choices is not None:
            return Editor.CHOICE
        if self.presets is not None:
            return Editor.PRESET
        if self.type is AssetPropertyType.Boolean:
            return Editor.BOOLEAN
        if self.type is AssetPropertyType.Integer:
            return Editor.INTEGER
        if self.type is AssetPropertyType.RealNumber:
            return Editor.REAL
        return Editor.TEXT


def _coerce(kind: AssetPropertyType, value: PropertyValue) -> PropertyValue:
    if kind is AssetPropertyType.Boolean:
        return bool(value)
    if kind is AssetPropertyType.Integer:
        return int(value)
    if kind is AssetPropertyType.RealNumber:
        return float(value)
    if kind in _TEXT_TYPES:
        return str(value)
    return value


def value_of(properties: Mapping[str, Property], spec: PropertySpec) -> PropertyValue:
    """The stored value, or the spec's default when the key is absent."""
    stored = properties.get(spec.name)
    if stored is None:
        return spec.default
    return stored["value"]


def make_property(spec: PropertySpec, value: PropertyValue) -> Property:
    return {"name": spec.name, "type": spec.type, "value": _coerce(spec.type, value)}


def set_value(
    properties: dict[str, Property],
    spec: PropertySpec,
    value: PropertyValue,
    change: Change,
    label: str | None = None,
) -> SetProperty:
    """The command that stores `value` under `spec`, with the spec's type."""
    return SetProperty(
        properties, spec.name, make_property(spec, value), change, label or f"Set {spec.label}"
    )


def _spec(name: str, label: str, kind: AssetPropertyType, default: PropertyValue) -> PropertySpec:
    return PropertySpec(name, label, kind, default)


def weather_names() -> tuple[str, ...]:
    """The map's weather values, in the order the engine's name table holds them - which is the
    index a `WorldInfo` stores.

    Read from the live `MapWeatherType` rather than fixed, because a binary patch can grow that
    table: `desert-weather` appends `DESERT` as index 2, and the `.sagepatch` beside the mod says
    so. `GameContext.apply_engine` is what puts the extra member on the enum, so the list is
    resolved each time a form reloads rather than at import.
    """
    return tuple(member.name.capitalize() for member in MapWeatherType)


_A, _U = AssetPropertyType.AsciiString, AssetPropertyType.UnicodeString
_I, _R, _B = AssetPropertyType.Integer, AssetPropertyType.RealNumber, AssetPropertyType.Boolean

# The map settings, with the values most maps store as defaults.
WORLD_INFO_SPECS: tuple[PropertySpec, ...] = (
    _spec("mapName", "Map name", _A, ""),
    _spec("mapDescription", "Description", _A, ""),
    # WorldBuilder names the values from its table at 0x0221C288.
    PropertySpec("compression", "Compression", _I, 1, ("No compression", "RefPack")),
    PropertySpec("weather", "Weather", _I, 0, weather_names),
    _spec("isScenarioMultiplayer", "Multiplayer scenario", _B, False),
    _spec("isLivingWorldScriptHolder", "Living World script holder", _B, False),
    _spec("cameraMaxHeight", "Camera maximum height", _R, 300.0),
    _spec("cameraGroundMinHeight", "Ground minimum height", _R, 0.0),
    _spec("cameraGroundMaxHeight", "Ground maximum height", _R, 2560.0),
    _spec("cameraPitchAngle", "Camera pitch", _R, 37.5),
    _spec("cameraYawAngle", "Camera yaw", _R, 0.0),
    _spec("cameraScrollSpeedScalar", "Scroll speed", _R, 1.0),
    _spec("cameraMapHeightSmoothnessScalar", "Height-map smoothness", _R, 0.75),
)

PLAYER_SPECS: tuple[PropertySpec, ...] = (
    _spec("playerName", "Name", _A, ""),
    _spec("playerDisplayName", "Display name", _U, ""),
    _spec("playerIsHuman", "Human (playable)", _B, False),
    _spec("playerFaction", "Faction", _A, ""),
    _spec("playerAllies", "Allies", _A, ""),
    _spec("playerEnemies", "Enemies", _A, ""),
    _spec("playerColor", "Color", _I, 0),
    # Both are absent unless chosen: a player then uses its faction's AI and icon.
    _spec("playerAIType", "AI type", _A, ""),
    _spec("playerFactionIcon", "Faction icon", _A, ""),
)

TEAM_UNIT_SLOTS = 7
TEAM_GENERIC_SCRIPT_SLOTS = 32

TEAM_SPECS: tuple[PropertySpec, ...] = (
    _spec("teamName", "Name", _A, ""),
    _spec("teamOwner", "Owner", _A, ""),
    _spec("teamIsSingleton", "Singleton", _B, False),
    _spec("teamDescription", "Description", _A, ""),
    _spec("teamHome", "Home waypoint", _A, ""),
    _spec("teamMaxInstances", "Maximum instances", _I, 1),
    _spec("teamProductionPriority", "Production priority", _I, 0),
    _spec("teamProductionPrioritySuccessIncrease", "Priority increase on success", _I, 0),
    _spec("teamProductionPriorityFailureDecrease", "Priority decrease on failure", _I, 0),
    _spec("teamProductionCondition", "Production condition script", _A, ""),
    _spec("teamIsAIRecruitable", "AI recruitable", _B, False),
    _spec("teamAutoReinforce", "Auto reinforce", _B, False),
    _spec("teamInitialIdleSeconds", "Initial idle seconds", _I, 0),
    _spec("teamExecutesActionsOnCreate", "Execute associated actions", _B, False),
    _spec("teamOnCreateScript", "On create script", _A, ""),
    _spec("teamEnemySightedScript", "On enemy sighted script", _A, ""),
    _spec("teamOnDestroyedScript", "On destroyed script", _A, ""),
    _spec("teamDestroyedThreshold", "Destroyed threshold", _R, 0.5),
    _spec("teamAllClearScript", "All clear script", _A, ""),
    _spec("teamAggressiveness", "Aggressiveness", _I, 0),
    _spec("teamAttackCommonTarget", "Attack a common target", _B, False),
    _spec("teamTargetThreatFinderName", "Target threat finder", _A, ""),
    _spec("teamEventsList", "Events list", _A, ""),
)


# The keys of WorldBuilder's Object Properties sheet, with the type every corpus map stores them
# as. A default is what the form shows for an absent key; the ten keys on every object use the
# value nearly every object stores. Keys whose stored type no map shows (`objectGroupNumber`,
# `objectGrantUpgrade`) and the scorch-mark keys (world dressing) are left to the other-keys list.
OBJECT_SPECS: tuple[PropertySpec, ...] = (
    _spec("objectName", "Name", _A, ""),
    _spec("originalOwner", "Team", _A, ""),
    _spec("objectLayer", "Layer", _A, ""),
    # WorldBuilder's starting-health drop-down (`MapObjectProps::_DictToHealth`, `0x005563C0`);
    # choosing Other there starts the value at 99 (`OnSelChangeStartingHealth`, `0x005588C0`).
    PropertySpec(
        "objectInitialHealth",
        "Initial health %",
        _I,
        100,
        presets=(("0%", 0), ("25%", 25), ("50%", 50), ("75%", 75), ("100%", 100)),
        other=99,
    ),
    # -1 is `Default For Unit` (`0x005566F0`); WorldBuilder's box takes any other number typed
    # in, and the 100 Other starts at is a choice.
    PropertySpec(
        "objectMaxHPs", "Maximum HP", _I, -1, presets=(("Default For Unit", -1),), other=100
    ),
    # WorldBuilder's value names (script parameter type 20); stored -3 to 2.
    PropertySpec(
        "objectAggressiveness",
        "Aggressiveness",
        _I,
        0,
        ("Peaceful", "Sleep", "Passive", "Normal", "Alert", "Aggressive"),
        choice_base=-3,
    ),
    _spec("objectExperienceLevel", "Experience level", _I, 1),
    _spec("objectVeterancy", "Veterancy", _I, 0),
    # WorldBuilder's value names (script parameter type 68); stored 0 to 5.
    PropertySpec(
        "objectInitialStance",
        "Stance",
        _I,
        0,
        ("Uninitialized", "Battle", "Aggressive", "HoldGround", "Porcupine", "HoldGroundMoving"),
    ),
    _spec("objectEnabled", "Enabled", _B, True),
    _spec("objectRecruitableAI", "AI recruitable", _B, True),
    _spec("objectUnsellable", "Unsellable", _B, False),
    _spec("objectPowered", "Powered", _B, True),
    _spec("objectTargetable", "Targetable", _B, False),
    _spec("objectIndestructible", "Indestructible", _B, False),
    _spec("objectSelectable", "Selectable override", _B, True),
    _spec("objectIsABase", "Is a base", _B, False),
    _spec("objectBaseName", "Base name", _A, ""),
    _spec("objectBasePriority", "Base priority", _I, 40),
    _spec("objectBasePhase", "Base phase", _I, 1),
    _spec("objectPrototypeScale", "Scale", _R, 1.0),
    _spec("alignToTerrain", "Align to terrain", _B, False),
    _spec("objectTime", "Time", _I, 0),
    _spec("objectWeather", "Weather", _I, 0),
    _spec("objectStoppingDistance", "Stopping distance", _R, 0.0),
    _spec("objectVisualRange", "Targeting distance", _I, 0),
    _spec("objectShroudClearingDistance", "Shroud clearing distance", _I, 0),
    _spec("objectThreatFinderRadius", "Threat radius", _R, 0.0),
    _spec("objectUpgradesList", "Upgrades", _A, ""),
    _spec("objectEventsList", "Event list", _A, ""),
    _spec("exportWithScript", "Export with script", _B, False),
    _spec("objectSoundAmbient", "Attached sound", _A, ""),
    _spec("objectSoundAmbientCustomized", "Customize sound", _B, False),
    _spec("objectSoundAmbientEnabled", "Sound enabled", _B, True),
    _spec("objectSoundAmbientLooping", "Sound looping", _B, True),
    _spec("objectSoundAmbientPriority", "Sound priority", _I, 0),
    _spec("objectSoundAmbientVolume", "Sound volume", _R, 1.0),
    _spec("objectSoundAmbientMinVolume", "Sound minimum volume", _R, 0.0),
    _spec("objectSoundAmbientMinRange", "Sound minimum range", _R, 0.0),
    _spec("objectSoundAmbientMaxRange", "Sound maximum range", _R, 0.0),
)

# The names of the waypoint types, by stored value (`worldbuilder.exe` `0x01EA15A8`, the list
# Waypoint Options fills its type drop-down from). WorldBuilder itself marks the last two unused.
WAYPOINT_TYPE_NAMES = (
    "Normal",
    "Portal",
    "WalkPortal",
    "ClimbPortal",
    "PreClimbPortal",
    "Beacon",
    "Spline (CatmullRom)",
    "FakePathfindPortal (don't use)",
    "MineshaftPortal (don't use)",
)

# Waypoint Options (dialog 153). `waypointID` is not editable: ids are allocated.
WAYPOINT_SPECS: tuple[PropertySpec, ...] = (
    _spec("waypointName", "Name", _A, ""),
    _spec("waypointPathLabel1", "Path label 1", _A, ""),
    _spec("waypointPathLabel2", "Path label 2", _A, ""),
    _spec("waypointPathLabel3", "Path label 3", _A, ""),
    _spec("waypointPathBiDirectional", "Bi-directional", _B, False),
    PropertySpec("waypointType", "Waypoint type", _I, 0, WAYPOINT_TYPE_NAMES),
    _spec("waypointTypeOption", "Type options", _A, ""),
)


def team_unit_specs(slot: int) -> tuple[PropertySpec, ...]:
    """The five keys describing unit slot `slot` (1-7) of a team."""
    if not 1 <= slot <= TEAM_UNIT_SLOTS:
        raise ValueError(f"team unit slots are 1-{TEAM_UNIT_SLOTS}, not {slot}")
    return (
        _spec(f"teamUnitType{slot}", f"Unit type {slot}", _A, ""),
        _spec(f"teamUnitMinCount{slot}", "Minimum", _I, 0),
        _spec(f"teamUnitMaxCount{slot}", "Maximum", _I, 0),
        _spec(f"teamUnitExperienceLevel{slot}", "Experience level", _I, 1),
        _spec(f"teamUnitUpgradeList{slot}", "Upgrades", _A, ""),
    )


def team_generic_script_spec(slot: int) -> PropertySpec:
    """Generic script hook `slot` (0-31) of a team."""
    if not 0 <= slot < TEAM_GENERIC_SCRIPT_SLOTS:
        raise ValueError(f"generic script slots are 0-{TEAM_GENERIC_SCRIPT_SLOTS - 1}, not {slot}")
    return _spec(f"teamGenericScriptHook{slot}", f"Generic script {slot}", _A, "")
