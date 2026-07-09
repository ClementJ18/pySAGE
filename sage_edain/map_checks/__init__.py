"""Edain map linting: the Edain rule set on the `sage_map.checks` architecture.

`lint_map` parses nothing itself - hand it a `sage_map` `Map` and it runs the Edain mapping
conventions over it, returning ordinary `sage_ini` `Diagnostics` (one stable MAP-xxx code per
convention, see `findings.FINDINGS`). `python -m sage_edain.map_checks <map>` is the
command-line front end.
"""

from .findings import (
    CAMERA_MAX_HEIGHT_TOO_LOW,
    CONTAINS_EXPANSION_FLAG,
    EXCESSIVE_OBJECT_COUNT,
    FINDINGS,
    INSUFFICIENT_TREES_NEAR_WIRTSCHAFT,
    LOW_EXPANSION_PLOT_FLAG_COUNT,
    MISSING_FARM_TEMPLATE,
    MISSING_GOLLUM_SPAWN_POINT,
    MISSING_GOLLUM_SPAWN_SCRIPT,
    MISSING_PLAYER_TYPES,
    MISSING_SPAWN_WAYPOINT,
    NON_FLAT_PLOT_FLAG,
    PLOT_FLAG_TOO_CLOSE_TO_BORDER,
    ROTATED_PLOT_FLAG,
    SPAWN_WAYPOINT_FOR_NONEXISTENT_PLAYER,
    START_WAYPOINT_FOR_NONEXISTENT_PLAYER,
    UNEVEN_FARM_TEMPLATE,
    finding,
)
from .linter import (
    FLATNESS_RADIUS,
    REQUIRED_PLAYERS,
    LintConfig,
    lint_map,
    lint_map_flatness,
    lint_map_performance,
    lint_map_resources,
    lint_map_validation,
)

__all__ = [
    "FINDINGS",
    "FLATNESS_RADIUS",
    "REQUIRED_PLAYERS",
    "CAMERA_MAX_HEIGHT_TOO_LOW",
    "CONTAINS_EXPANSION_FLAG",
    "EXCESSIVE_OBJECT_COUNT",
    "INSUFFICIENT_TREES_NEAR_WIRTSCHAFT",
    "LOW_EXPANSION_PLOT_FLAG_COUNT",
    "MISSING_FARM_TEMPLATE",
    "MISSING_GOLLUM_SPAWN_POINT",
    "MISSING_GOLLUM_SPAWN_SCRIPT",
    "MISSING_PLAYER_TYPES",
    "MISSING_SPAWN_WAYPOINT",
    "NON_FLAT_PLOT_FLAG",
    "PLOT_FLAG_TOO_CLOSE_TO_BORDER",
    "ROTATED_PLOT_FLAG",
    "SPAWN_WAYPOINT_FOR_NONEXISTENT_PLAYER",
    "START_WAYPOINT_FOR_NONEXISTENT_PLAYER",
    "UNEVEN_FARM_TEMPLATE",
    "LintConfig",
    "finding",
    "lint_map",
    "lint_map_flatness",
    "lint_map_performance",
    "lint_map_resources",
    "lint_map_validation",
]
