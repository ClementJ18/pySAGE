"""The Edain mapping-convention rules, run over a parsed `Map` without game data.

Each `lint_map_*` function is a rule for the `sage_map.checks` runner; `lint_map` bundles them
according to the config's toggles. The conventions are Edain's: plot-flag placement (Festung /
Lager / Wirtschaft), FarmTemplate terrain, Gollum spawns, the skirmish AI player roster, and
performance limits.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sage_ini.parser.diagnostics import Diagnostic, Diagnostics
from sage_map.checks import (
    LintConfig as BaseLintConfig,
)
from sage_map.checks import (
    get_flatness_percentage,
    is_flat_at_position,
)
from sage_map.checks import (
    lint_map as run_rules,
)

from .findings import (
    CAMERA_MAX_HEIGHT_TOO_LOW,
    CONTAINS_EXPANSION_FLAG,
    EXCESSIVE_OBJECT_COUNT,
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
    object_extra,
)

if TYPE_CHECKING:
    from sage_map.map import Map


def _prop_str(obj: Any, key: str) -> str:
    """The string value of object property `key` (raises KeyError if the property is absent).

    These name-like properties are stored as AsciiString, so a non-str value means a corrupt
    file; the raised TypeError propagates to the checks runner as a rule-error finding."""
    value = obj.properties[key]["value"]
    if not isinstance(value, str):
        raise TypeError(f"Property {key!r} is not a string, got {type(value).__name__}")
    return value


@dataclass
class LintConfig(BaseLintConfig):
    """Toggles and thresholds for the Edain rule set."""

    run_validation: bool = True
    run_flatness: bool = True
    run_resources: bool = True
    run_performance: bool = True

    min_camera_max_height: int = 533

    min_border_distance: int = 10
    farm_flatness_check_radius: int = 30
    farm_flatness_threshold: float = 0.67

    required_trees_near_wirtschaft: int = 30
    wirtschaft_tree_search_radius: int = 30

    max_recommended_objects: int = 2000


REQUIRED_PLAYERS = [
    "SkirmishMen",
    "SkirmishRohan",
    "SkirmishElves",
    "SkirmishDwarves",
    "SkirmishIsengard",
    "SkirmishMordor",
    "SkirmishImladris",
    "SkirmishWild",
    "SkirmishAngmar",
    "SkirmishEvilmen",
]

FLATNESS_RADIUS = {
    "FestungPlotFlag": 50,
    "LagerPlotFlag": 40,
    "HalfCastlePlotFlag": 40,
    "ExpansionPlotFlag": 30,
    "WirtschaftPlotFlag": 10,
}


def lint_map_validation(map_obj: "Map", config: LintConfig) -> list[Diagnostic]:
    errors: list[Diagnostic] = []

    objects_list = map_obj.objects_list
    assert objects_list is not None

    player_points = {str(x): {"exists": False, "has_spawn": False} for x in range(1, 9)}
    expansion_plot_flag_count = 0
    is_wotr = not any(
        obj.type_name.startswith(("FestungPlotFlag", "LagerPlotFlag", "HalfCastlePlotFlag"))
        for obj in objects_list.object_list
    )
    gollum = has_farm_templates = has_gollum_spawn = is_wotr

    for obj in objects_list.object_list:
        obj_type = obj.type_name

        if obj_type == "ExpansionFlag":
            errors.append(finding(CONTAINS_EXPANSION_FLAG, **object_extra(obj)))
        elif obj_type == "ExpansionPlotFlag":
            expansion_plot_flag_count += 1
            if obj.angle != 0:
                errors.append(finding(ROTATED_PLOT_FLAG, **object_extra(obj)))
        elif obj_type == "FarmTemplate":
            has_farm_templates = True
        elif obj_type == "*Waypoints/Waypoint":
            waypoint_name = _prop_str(obj, "waypointName")
            paths = [
                obj.properties[f"waypointPathLabel{x}"]["value"]
                for x in range(1, 4)
                if f"waypointPathLabel{x}" in obj.properties
            ]

            if waypoint_name.startswith("Player_") and waypoint_name.endswith("_Start"):
                player_num = waypoint_name[7:-6]
                try:
                    player_points[player_num]["exists"] = True
                except KeyError:
                    errors.append(
                        finding(START_WAYPOINT_FOR_NONEXISTENT_PLAYER, waypoint_name=waypoint_name)
                    )
                continue

            if (
                waypoint_name.startswith("Player_")
                and waypoint_name.endswith("_Spawn")
                and "Player_Path" in paths
            ):
                player_num = waypoint_name[7:-6]
                try:
                    player_points[player_num]["has_spawn"] = True
                except KeyError:
                    errors.append(
                        finding(SPAWN_WAYPOINT_FOR_NONEXISTENT_PLAYER, waypoint_name=waypoint_name)
                    )
                continue

            if waypoint_name.startswith("SpawnPoint_SkirmishGollum_"):
                gollum = True
        elif obj.type_name.startswith(("FestungPlotFlag", "LagerPlotFlag", "HalfCastlePlotFlag")):
            if obj.angle != 0:
                errors.append(finding(ROTATED_PLOT_FLAG, **object_extra(obj)))

    if expansion_plot_flag_count <= 1:
        errors.append(finding(LOW_EXPANSION_PLOT_FLAG_COUNT, count=expansion_plot_flag_count))

    world_info = map_obj.world_info
    assert world_info is not None
    camera_prop = world_info.properties.get("cameraMaxHeight")
    if camera_prop is not None:
        camera_max_height = camera_prop["value"]
        # A non-numeric cameraMaxHeight is a corrupt file; let it raise into a rule-error.
        assert isinstance(camera_max_height, (int, float))
        if camera_max_height < config.min_camera_max_height:
            errors.append(finding(CAMERA_MAX_HEIGHT_TOO_LOW, height=camera_max_height))

    if not has_farm_templates:
        errors.append(finding(MISSING_FARM_TEMPLATE))

    if not gollum:
        errors.append(finding(MISSING_GOLLUM_SPAWN_POINT))

    missing_spawns = [num for num, p in player_points.items() if p["exists"] and not p["has_spawn"]]
    errors.extend(finding(MISSING_SPAWN_WAYPOINT, player_num=num) for num in missing_spawns)

    sides_list = map_obj.sides_list
    assert sides_list is not None
    players = {player.properties["playerName"]["value"] for player in sides_list.players}
    missing_players = [p for p in REQUIRED_PLAYERS if p not in players]
    if missing_players:
        errors.append(finding(MISSING_PLAYER_TYPES, missing_players=missing_players))

    if not is_wotr:
        player_scripts_list = map_obj.player_scripts_list
        assert player_scripts_list is not None
        for script_list in player_scripts_list.script_lists:
            if any(script.name == "SkirmishGollum_Spawn" for script in script_list.items):
                has_gollum_spawn = True
                break

        if not has_gollum_spawn:
            library_map_lists = map_obj.library_map_lists
            assert library_map_lists is not None
            for library in library_map_lists.lists:
                if any("Lib_GollumSpawn" in script for script in library.values):
                    has_gollum_spawn = True
                    break

        if not has_gollum_spawn:
            errors.append(finding(MISSING_GOLLUM_SPAWN_SCRIPT))

    return errors


def lint_map_flatness(map_obj: "Map", config: LintConfig) -> list[Diagnostic]:
    errors: list[Diagnostic] = []

    height_map = map_obj.height_map_data
    assert height_map is not None
    objects_list = map_obj.objects_list
    assert objects_list is not None
    border_width = height_map.border_width
    world_width = height_map.width - 2 * border_width
    world_height = height_map.height - 2 * border_width
    min_border_distance = config.min_border_distance

    flags = [
        obj
        for obj in objects_list.object_list
        if any(obj.type_name.startswith(prefix) for prefix in FLATNESS_RADIUS)
    ]
    for flag in flags:
        radius = next(
            FLATNESS_RADIUS[prefix]
            for prefix in FLATNESS_RADIUS
            if flag.type_name.startswith(prefix)
        )

        flag_x, flag_y, _ = flag.position
        flag_x = flag_x / 10.0
        flag_y = flag_y / 10.0

        if (
            flag_x < min_border_distance
            or flag_y < min_border_distance
            or flag_x > world_width - min_border_distance
            or flag_y > world_height - min_border_distance
        ):
            errors.append(finding(PLOT_FLAG_TOO_CLOSE_TO_BORDER, **object_extra(flag)))

        if not is_flat_at_position(map_obj, flag_x, flag_y, radius):
            errors.append(finding(NON_FLAT_PLOT_FLAG, radius=radius, **object_extra(flag)))

    farm_templates = [obj for obj in objects_list.object_list if obj.type_name == "FarmTemplate"]

    for farm in farm_templates:
        farm_x, farm_y, _ = farm.position
        farm_x = farm_x / 10.0
        farm_y = farm_y / 10.0

        flat_percentage = get_flatness_percentage(
            map_obj, farm_x, farm_y, config.farm_flatness_check_radius
        )

        if flat_percentage < config.farm_flatness_threshold:
            errors.append(
                finding(
                    UNEVEN_FARM_TEMPLATE,
                    flat_percentage=flat_percentage * 100,
                    **object_extra(farm),
                )
            )

    return errors


def lint_map_resources(map_obj: "Map", config: LintConfig) -> list[Diagnostic]:
    errors: list[Diagnostic] = []

    objects_list = map_obj.objects_list
    assert objects_list is not None
    wirtschaft_flags = [
        obj for obj in objects_list.object_list if obj.type_name.startswith("WirtschaftPlotFlag")
    ]
    tree_objects = [obj for obj in objects_list.object_list if "tree" in obj.type_name.lower()]

    for flag in wirtschaft_flags:
        flag_x, flag_y, _ = flag.position
        flag_x = flag_x / 10.0
        flag_y = flag_y / 10.0

        tree_count = 0
        for tree in tree_objects:
            tree_x, tree_y, _ = tree.position
            tree_x = tree_x / 10.0
            tree_y = tree_y / 10.0

            distance = ((flag_x - tree_x) ** 2 + (flag_y - tree_y) ** 2) ** 0.5

            if distance <= config.wirtschaft_tree_search_radius:
                tree_count += 1

        if tree_count < config.required_trees_near_wirtschaft:
            errors.append(
                finding(
                    INSUFFICIENT_TREES_NEAR_WIRTSCHAFT,
                    tree_count=tree_count,
                    **object_extra(flag),
                )
            )

    return errors


def lint_map_performance(map_obj: "Map", config: LintConfig) -> list[Diagnostic]:
    errors: list[Diagnostic] = []

    objects_list = map_obj.objects_list
    assert objects_list is not None
    object_count = len(objects_list.object_list)

    if object_count > config.max_recommended_objects:
        errors.append(
            finding(
                EXCESSIVE_OBJECT_COUNT,
                object_count=object_count,
                limit=config.max_recommended_objects,
            )
        )

    return errors


def lint_map(
    map_obj: "Map", config: LintConfig | None = None, path: str | Path = "<map>"
) -> Diagnostics:
    if config is None:
        config = LintConfig()

    rules = []
    if config.run_validation:
        rules.append(lint_map_validation)
    if config.run_flatness:
        rules.append(lint_map_flatness)
    if config.run_resources:
        rules.append(lint_map_resources)
    if config.run_performance:
        rules.append(lint_map_performance)

    return run_rules(map_obj, rules, config, path)
