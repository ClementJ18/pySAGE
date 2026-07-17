"""The Edain findings: one stable MAP-xxx code per convention, with its severity and message.

`finding` renders one as a `sage_ini` `Diagnostic`; the `extra` dict keeps the structured facts
(the offending object's position/id, counts) so consumers never re-parse the message. The
`--list-codes` CLI output is generated from the `FINDINGS` table.
"""

from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_map.checks import UNSTAMPED_SPAN

CONTAINS_EXPANSION_FLAG = "MAP-002"
START_WAYPOINT_FOR_NONEXISTENT_PLAYER = "MAP-003"
SPAWN_WAYPOINT_FOR_NONEXISTENT_PLAYER = "MAP-004"
ROTATED_PLOT_FLAG = "MAP-005"
MISSING_FARM_TEMPLATE = "MAP-006"
MISSING_PLAYER_TYPES = "MAP-007"
MISSING_GOLLUM_SPAWN_SCRIPT = "MAP-008"
MISSING_GOLLUM_SPAWN_POINT = "MAP-009"
MISSING_SPAWN_WAYPOINT = "MAP-010"
NON_FLAT_PLOT_FLAG = "MAP-011"
PLOT_FLAG_TOO_CLOSE_TO_BORDER = "MAP-012"
INSUFFICIENT_TREES_NEAR_WIRTSCHAFT = "MAP-013"
UNEVEN_FARM_TEMPLATE = "MAP-014"
EXCESSIVE_OBJECT_COUNT = "MAP-015"
LOW_EXPANSION_PLOT_FLAG_COUNT = "MAP-016"
CAMERA_MAX_HEIGHT_TOO_LOW = "MAP-017"

FINDINGS: dict[str, tuple[Severity, str]] = {
    CONTAINS_EXPANSION_FLAG: (
        Severity.ERROR,
        "Map contains ExpansionFlag at position {position} which is not supported.",
    ),
    START_WAYPOINT_FOR_NONEXISTENT_PLAYER: (
        Severity.ERROR,
        "Map has a start waypoint for non-existent {waypoint_name}.",
    ),
    SPAWN_WAYPOINT_FOR_NONEXISTENT_PLAYER: (
        Severity.ERROR,
        "Map has a spawn waypoint for non-existent {waypoint_name}.",
    ),
    ROTATED_PLOT_FLAG: (
        Severity.ERROR,
        "Map contains {flag_type} at position {position} with non-zero angle "
        "which may cause issues.",
    ),
    MISSING_FARM_TEMPLATE: (
        Severity.ERROR,
        "Map does not contain any FarmTemplate objects, which may cause issues with the AI.",
    ),
    MISSING_PLAYER_TYPES: (
        Severity.ERROR,
        "Map is missing required player types for AI: {missing_players}",
    ),
    MISSING_GOLLUM_SPAWN_SCRIPT: (
        Severity.ERROR,
        "Map does not contain any SkirmishGollum_Spawn script, "
        "which may cause issues with Gollum spawns.",
    ),
    MISSING_GOLLUM_SPAWN_POINT: (
        Severity.ERROR,
        "Map does not contain any Gollum spawn points, which may cause issues with Gollum spawns.",
    ),
    MISSING_SPAWN_WAYPOINT: (
        Severity.ERROR,
        "Player {player_num} has a start waypoint but is missing a spawn waypoint, "
        "which may cause issues with player spawns.",
    ),
    NON_FLAT_PLOT_FLAG: (
        Severity.ERROR,
        "{flag_type} at position {position} is placed on non-flat terrain (radius {radius}), "
        "which may cause building issues.",
    ),
    PLOT_FLAG_TOO_CLOSE_TO_BORDER: (
        Severity.ERROR,
        "{flag_type} at position {position} is too close to the world border "
        "(minimum distance: 10 units).",
    ),
    INSUFFICIENT_TREES_NEAR_WIRTSCHAFT: (
        Severity.WARNING,
        "WirtschaftPlotFlag at position {position} has insufficient trees nearby "
        "(found {tree_count}, required 30 within 30 units).",
    ),
    UNEVEN_FARM_TEMPLATE: (
        Severity.WARNING,
        "FarmTemplate at position {position} is placed on uneven terrain "
        "({flat_percentage:.1f}% flat, threshold 67%).",
    ),
    EXCESSIVE_OBJECT_COUNT: (
        Severity.WARNING,
        "Map contains {object_count} objects, which exceeds the recommended limit of {limit} "
        "and may cause performance issues.",
    ),
    LOW_EXPANSION_PLOT_FLAG_COUNT: (
        Severity.INFO,
        "Map has {count} ExpansionPlotFlag object(s); recommended is more than 1.",
    ),
    CAMERA_MAX_HEIGHT_TOO_LOW: (
        Severity.ERROR,
        "Map cameraMaxHeight is {height}, which is below the minimum of 533.",
    ),
}


def finding(code: str, **extra) -> Diagnostic:
    """Render the finding for `code`: the runner stamps the real file over the placeholder span."""
    severity, template = FINDINGS[code]
    return Diagnostic(
        code=code,
        message=template.format(**extra),
        span=UNSTAMPED_SPAN,
        severity=severity,
        extra=extra,
    )


def object_extra(obj) -> dict:
    """The structured facts every object-anchored finding carries."""
    return {
        "flag_type": obj.type_name,
        "position": obj.position,
        "id": obj.properties["uniqueID"]["value"],
    }
