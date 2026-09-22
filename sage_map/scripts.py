"""What each script argument *means*, keyed by the `ScriptArgumentType` the binary already records.

A parsed `ScriptArgument` carries its own type tag (`OBJECT_TYPE`, `TEAM_NAME`, `SCIENCE_NAME`,
...) and three payload slots (`int_value`, `float_value`, `string_value`) plus a `position_value`.
That tag is enough to type every argument independently of the enclosing action's id: the action's
`content_type` says *what* runs, but each argument self-describes what it holds. `ARG_SPECS` is the
table that turns the tag into (which slot holds the payload, what it must resolve against).

Resolution scopes:

* `GAME` - a definition in the assembled `Game` (an ini object); `target` is the table key passed
  to `Game.lookup` (e.g. ``"objects"``, ``"sciences"``).
* `MAP` - a symbol the map itself declares (a team, waypoint, script, player, ...); `target` names
  the map-local table the `sage_map.model` adapter builds.
* `STRINGS` - a localization label, resolved against `Game.strings`.
* `ENUM` - a closed value set the engine defines. Recorded now; value validation is deferred.
* `LITERAL` - a plain scalar (or a name we do not yet resolve); nothing to check.

Only `GAME`, `MAP` and `STRINGS` entries drive reference linting in v1. Following the sage_ini
schema-coverage approach, an argument type we are not yet sure how to resolve is left `LITERAL`
rather than guessed at - a wrong scope is a false positive, an absent one is merely a gap. The
`# deferred:` comments mark those gaps.
"""

from dataclasses import dataclass
from enum import Enum

from sage_map.assets.player_scripts import ScriptArgument, ScriptArgumentType

T = ScriptArgumentType  # local shorthand for the dense table below


class Scope(Enum):
    """What an argument's payload must resolve against (see module docstring)."""

    GAME = "game"
    MAP = "map"
    STRINGS = "strings"
    ENUM = "enum"
    LITERAL = "literal"


@dataclass(frozen=True)
class ArgSpec:
    """How to read one argument type and what it must resolve against.

    `field` is the `ScriptArgument` attribute holding the payload. `target` is the resolution
    handle: a `Game` table key for `GAME`, a map-local table name for `MAP`, an enum name for
    `ENUM`, and `None` for `STRINGS`/`LITERAL`.
    """

    field: str
    scope: Scope
    target: str | None = None


# Default for any type absent from the table below: a string payload we do not resolve. Keeps
# `arg_spec`/`typed_value` total over the enum without inventing a scope for an unmapped type.
_DEFAULT = ArgSpec("string_value", Scope.LITERAL)

# Reusable scalar literals.
_INT = ArgSpec("int_value", Scope.LITERAL)
_REAL = ArgSpec("float_value", Scope.LITERAL)
_TEXT = ArgSpec("string_value", Scope.LITERAL)
_POSITION = ArgSpec("position_value", Scope.LITERAL)


def _game(target: str) -> ArgSpec:
    return ArgSpec("string_value", Scope.GAME, target)


def _map(target: str) -> ArgSpec:
    return ArgSpec("string_value", Scope.MAP, target)


def _enum(target: str) -> ArgSpec:
    return ArgSpec("int_value", Scope.ENUM, target)


def _named_enum(target: str) -> ArgSpec:
    """A closed set the editor writes by *name* rather than by index, unlike `_enum`."""
    return ArgSpec("string_value", Scope.ENUM, target)


ARG_SPECS: dict[ScriptArgumentType, ArgSpec] = {
    # Plain scalars - nothing to resolve.
    T.INTEGER: _INT,
    T.REAL_NUMBER: _REAL,
    T.ANGLE: _REAL,
    T.PERCENTAGE: _REAL,
    T.TEXT: _TEXT,
    T.POSITION_COORDINATE: _POSITION,
    # `NAMED_CUSTOM_COLOR` carries a packed colour integer in the string slot, not a colour name.
    T.COLOR: _TEXT,
    T.BOOLEAN: ArgSpec("int_value", Scope.ENUM, "Boolean"),
    # Definitions in the assembled game (ini objects). target = Game.lookup table key.
    T.OBJECT_TYPE: _game("objects"),
    T.SCIENCE_NAME: _game("sciences"),
    T.UPGRADE_NAME: _game("upgrades"),
    T.COMMAND_BUTTON_NAME: _game("commandbuttons"),
    T.SPECIAL_POWER_NAME: _game("specialpowers"),
    # The `*_USE_COMMANDBUTTON_ABILITY*` actions name a CommandButton, whichever of the two types
    # the editor tagged the argument with: across a 471-map corpus every one of the 190 + 204
    # distinct values is a `Command_*`, and all but 15 of them resolve as one.
    T.UNIT_ABILITY_NAME: _game("commandbuttons"),
    T.TEAM_ABILITY_NAME: _game("commandbuttons"),
    # `HERO_SELECT_BUTTON_FLASH` names an object template, not a hero definition of its own.
    T.HERO: _game("objects"),
    # FACTION_NAME holds a *side* name (`Rohan`, `Angmar`), not a PlayerTemplate name
    # (`FactionRohan`) - 876 uses across a 471-map corpus, all of them `SKIRMISH_PLAYER_FACTION`,
    # spanning the twelve sides. There is no table of side names to look one up in (the `factions`
    # table is keyed by PlayerTemplate name), and the set is data-derived rather than compiled in,
    # so it is recorded as a named set and not resolved.
    T.FACTION_NAME: _named_enum("Side"),
    # Names a script action *creates*, not definitions - an attack priority set, an object-type
    # list (`OBJECTLIST_ADDOBJECTTYPE`) and a permanent map reveal
    # (`MAP_REVEAL_PERMANENTLY_*`, whose name a later undo refers back to) are all authored in
    # the script that first names them. We do not harvest the creating actions, so each target is
    # untracked (resolve -> None) rather than checked against a game table.
    T.ATTACK_PRIORITY_SET_NAME: _map("attack_priority_sets"),
    T.OBJECT_TYPE_LIST_NAME: _map("object_type_lists"),
    T.MAP_REVEAL_NAME: _map("map_reveals"),
    # Symbols the map itself declares (built by the `sage_map.model` adapter).
    T.SCRIPT_NAME: _map("scripts"),
    T.SUBROUTINE_NAME: _map("scripts"),
    T.TEAM_NAME: _map("teams"),
    T.TEAM_REFERENCE: _map("teams"),
    T.WAYPOINT_NAME: _map("waypoints"),
    T.WAYPOINT_PATH_NAME: _map("waypoint_paths"),
    T.TRIGGER_AREA_NAME: _map("trigger_areas"),
    T.PLAYER_NAME: _map("players"),
    T.COUNTER_NAME: _map("counters"),
    T.FLAG_NAME: _map("flags"),
    T.UNIT_NAME: _map("units"),  # a placed object with a name property
    T.UNIT_REFERENCE: _map("units"),
    T.OBJECT_NAME: _map("units"),  # a named instance, not a template (that is OBJECT_TYPE)
    T.BOUNDARY_NAME: _map("boundaries"),
    # A camera and a camera animation are declared only by the map that uses them, so a miss here
    # is a real dangling reference rather than a name merged in at runtime.
    T.CAMERA_NAME: _map("cameras"),
    T.CAMERA_ANIMATION_NAME: _map("camera_animations"),
    # Localization labels.
    T.LOCALIZED_STRING_NAME: ArgSpec("string_value", Scope.STRINGS),
    # Closed engine value sets. Recorded as ENUM; value validation is deferred (v1 does not check).
    T.COMPARISON: _enum("Comparison"),
    T.RELATION: _enum("Relation"),
    T.AI_MOOD: _enum("AiMood"),
    T.TEAM_STATE: _enum("TeamState"),
    T.RADAR_EVENT_TYPE: _enum("RadarEventType"),
    T.BUILDABILITY: _enum("Buildability"),
    T.SURFACE_TYPE: _enum("SurfaceType"),
    T.CAMERA_SHAKE_INTENSITY: _enum("CameraShakeIntensity"),
    T.OBJECT_STATUS: _enum("ObjectStatus"),
    T.UNIT_OR_STRUCTURE_KIND: _enum("KindOf"),
    T.NEAR_OR_FAR: _enum("NearOrFar"),
    T.MATH_OPERATOR: _enum("MathOperator"),
    T.MODEL_CONDITION: _enum("ModelCondition"),
    T.REVERB_ROOM_TYPE: _enum("ReverbRoomType"),
    T.EMOTION: _enum("Emotion"),
    T.OBJECTIVE_COMPLETE: _enum("ObjectiveComplete"),
    # Written by name, not by index: the flags `UNIT_AFFECT_OBJECT_PANEL_FLAGS` toggles
    # (`Selectable`, `Indestructible`, ... - the `object*` properties a placed object carries) and
    # the availability `PLAYER_SCIENCE_AVAILABILITY` sets (`Available`, ...).
    T.OBJECT_PANEL_FLAG: _named_enum("ObjectPanelFlag"),
    T.SCIENCE_AVAILABILITY_NAME: _named_enum("ScienceAvailability"),
    # deferred: audio/font asset names live in archives the loose-file crawl misses (the same
    # reason sage_lint's asset rule skips audio), so resolving them would only churn false misses.
    T.SOUND_NAME: _TEXT,
    T.SPEECH_NAME: _TEXT,
    T.MUSIC_NAME: _TEXT,
    T.MOVIE_NAME: _TEXT,
    T.AUDIO_NAME: _TEXT,
    T.FONT_NAME: _TEXT,
    T.EMOTICON_NAME: _TEXT,
    # deferred: these never occur in the 471-map corpus the rest of this table was surveyed
    # against (BRIDGE_NAME/SKIRMISH_APPROACH_PATH/THREAT_FINDER_NAME/STANCE/EVA and the seven
    # UNKNOWN_* types), so there is no evidence to scope them by. Left LITERAL until one shows up.
    # Every other type in the enum is mapped above.
}


@dataclass(frozen=True)
class ResolvedArg:
    """An argument paired with its spec and the active payload slot, ready for a rule to resolve.

    `value` is the payload `spec.field` points at (a `str` for every reference scope, an `int`/
    `float`/coordinate tuple for scalars), or `None` when that slot was not set.
    """

    type: ScriptArgumentType
    spec: ArgSpec
    value: object


def arg_spec(arg_type: ScriptArgumentType) -> ArgSpec:
    """The spec for an argument type, falling back to a non-resolving string literal."""
    return ARG_SPECS.get(arg_type, _DEFAULT)


def typed_value(arg: ScriptArgument) -> ResolvedArg:
    """Pair a parsed `ScriptArgument` with its spec and the payload slot the spec selects."""
    spec = arg_spec(arg.type)
    return ResolvedArg(type=arg.type, spec=spec, value=getattr(arg, spec.field))
