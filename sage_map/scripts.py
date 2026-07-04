"""What each script argument *means*, keyed by the `ScriptArgumentType` the binary already records.

A parsed `ScriptArgument` carries its own type tag (`OBJECT_TYPE`, `TEAM_NAME`, `SCIENCE_NAME`,
...) and three payload slots (`int_value`, `float_value`, `string_value`) plus a `position_value`.
That tag is enough to type every argument independently of the enclosing action's id: the action's
`content_type` says *what* runs, but each argument self-describes what it holds. `ARG_SPECS` is the
table that turns the tag into (which slot holds the payload, what it must resolve against).

Resolution scopes:

* `GAME` — a definition in the assembled `Game` (an ini object); `target` is the table key passed
  to `Game.lookup` (e.g. ``"objects"``, ``"sciences"``).
* `MAP` — a symbol the map itself declares (a team, waypoint, script, player, ...); `target` names
  the map-local table the Phase 2 adapter builds.
* `STRINGS` — a localization label, resolved against `Game.strings`.
* `ENUM` — a closed value set the engine defines. Recorded now; value validation is deferred.
* `LITERAL` — a plain scalar (or a name we do not yet resolve); nothing to check.

Only `GAME`, `MAP` and `STRINGS` entries drive reference linting in v1. Following the sage_ini
schema-coverage approach, an argument type we are not yet sure how to resolve is left `LITERAL`
rather than guessed at — a wrong scope is a false positive, an absent one is merely a gap. The
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


ARG_SPECS: dict[ScriptArgumentType, ArgSpec] = {
    # Plain scalars — nothing to resolve.
    T.INTEGER: _INT,
    T.REAL_NUMBER: _REAL,
    T.ANGLE: _REAL,
    T.PERCENTAGE: _REAL,
    T.PERCENTAGE2: _REAL,
    T.TEXT: _TEXT,
    T.POSITION_COORDINATE: _POSITION,
    T.BOOLEAN: ArgSpec("int_value", Scope.ENUM, "Boolean"),
    # Definitions in the assembled game (ini objects). target = Game.lookup table key.
    T.OBJECT_TYPE: _game("objects"),
    T.SCIENCE_NAME: _game("sciences"),
    T.UPGRADE_NAME: _game("upgrades"),
    T.COMMAND_BUTTON_NAME: _game("commandbuttons"),
    T.SPECIAL_POWER_NAME: _game("specialpowers"),
    T.FACTION_NAME: _game("factions"),  # FACTION_NAME -> PlayerTemplate (key "factions")
    # Attack priority sets are *created by script actions*, not defined in ini, so they resolve
    # map-locally — and we do not harvest the creating actions yet, so the target is untracked
    # (resolve -> None) rather than checked against the game's ini AttackPriority table.
    T.ATTACK_PRIORITY_SET_NAME: _map("attack_priority_sets"),
    # Symbols the map itself declares (built by the Phase 2 adapter).
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
    # deferred: audio/font asset names live in archives the loose-file crawl misses (the same
    # reason sage_lint's asset rule skips audio), so resolving them would only churn false misses.
    T.SOUND_NAME: _TEXT,
    T.SPEECH_NAME: _TEXT,
    T.MUSIC_NAME: _TEXT,
    T.MOVIE_NAME: _TEXT,
    T.AUDIO_NAME: _TEXT,
    T.FONT_NAME: _TEXT,
    T.EMOTICON_NAME: _TEXT,
    # deferred: no game table registered yet (OBJECT_TYPE_LIST_NAME), or scope still ambiguous
    # (HERO/BRIDGE/COLOR/OBJECT_PANEL_FLAG/MAP_REVEAL_NAME/SCIENCE_AVAILABILITY_NAME/
    # EVACUATE_CONTAINER_SIDE/SKIRMISH_APPROACH_PATH/UNIT_ABILITY_NAME/TEAM_ABILITY_NAME/
    # SPEECH/UNKNOWN_1) — left LITERAL until confirmed.
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
