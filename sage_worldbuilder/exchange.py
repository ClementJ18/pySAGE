"""WorldBuilder's map data export and import (`MapDataImportExport.cpp`): chosen parts of a map
written to a `.scb`, and a `.scb` merged into another map.

Export follows the Export Options dialog (194) and the writer at `0x005350F3`: the options pick
the terrain, objects, waypoints, trigger areas, water, lighting, players, passability and scripts,
and "Include items referenced in exported scripts" adds the units and teams, waypoint paths and
trigger areas the exported scripts name. Import follows the reader at `0x0053D92C`: a library of
another size is placed at an anchor (Reanchor Import), a waypoint, named object or trigger area
whose name the map already has is resolved by a choice (Keep existing / Keep imported), a team
whose player the map lacks goes to a chosen player, and each exported player's scripts go to the
map's player of that name, dropping scripts whose names the player already has. Terrain
textures are merged into the map's texture table (`terrain.merge`). Everything is one undoable
edit.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Iterable, MutableSequence, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum, IntEnum
from typing import TYPE_CHECKING, Any

import numpy as np

from sage_map.assets import (
    CameraAnimationList,
    NamedCameras,
    ObjectsList,
    PlayerScriptsList,
    ScriptApplyHeight,
    ScriptImportSize,
    ScriptPassability,
    ScriptPlayer,
    ScriptsPlayers,
    ScriptTeams,
    TriggerAreas,
    WaypointsList,
)
from sage_map.assets.object_list import Object
from sage_map.assets.player_scripts import Script, ScriptArgumentType, ScriptGroup, ScriptList
from sage_map.assets.script_passability import LAYERS
from sage_map.assets.teams import Team
from sage_map.map import Map
from sage_map.scb import ScriptLibrary
from sage_worldbuilder.areas import DeleteAreas
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand, SetAttribute
from sage_worldbuilder.heightmap_io import Anchor
from sage_worldbuilder.ids import next_trigger_area_id, next_unique_number, next_waypoint_id
from sage_worldbuilder.objects import DeleteObjects
from sage_worldbuilder.roads import with_partners
from sage_worldbuilder.scene import WAYPOINT_PREFIX
from sage_worldbuilder.scripting import iter_script_items, player_script_lists
from sage_worldbuilder.terrain.cells import CellLayer, layer_array
from sage_worldbuilder.terrain.edits import PatchCells, PatchHeights, ReplaceTerrainTables
from sage_worldbuilder.terrain.merge import merge_textures
from sage_worldbuilder.water import WaterKind, next_water_id, water_areas

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "SELECTION_PLAYER",
    "DuplicateKind",
    "DuplicatePolicy",
    "ExportOptions",
    "ImportChoices",
    "ImportPlan",
    "ImportReport",
    "ScriptsMode",
    "build_export",
    "import_library",
    "plan_import",
]

# The pseudo player an export of selected scripts files them under.
SELECTION_PLAYER = "**SELECTION**"
# World units per heightmap cell.
_CELL = 10.0

_T = ScriptArgumentType
_REFERENCE_TYPES = (
    _T.TEAM_NAME,
    _T.WAYPOINT_NAME,
    _T.TRIGGER_AREA_NAME,
    _T.UNIT_NAME,
    _T.WAYPOINT_PATH_NAME,
    _T.CAMERA_NAME,
)
_PATH_LABELS = ("waypointPathLabel1", "waypointPathLabel2", "waypointPathLabel3")
_WATER = (
    (WaterKind.LAKE, "standing_water_areas"),
    (WaterKind.RIVER, "river_areas"),
    (WaterKind.WAVE, "standing_wave_areas"),
)


class ScriptsMode(IntEnum):
    """Export Options' scripts radio buttons, valued as the table at `0x01DF9800` values them."""

    NONE = 0
    SELECTED = 1
    ALL = 2


@dataclass
class ExportOptions:
    """Export Options' check boxes (the table at `0x01DF97A0`), the players whose objects go
    along, and the scripts choice. The defaults, a choice, export every script with what the
    scripts name."""

    terrain_texture: bool = False
    terrain_height: bool = False
    selected_objects: bool = False
    all_waypoints: bool = False
    all_areas: bool = False
    water: bool = False
    lighting: bool = False
    all_players: bool = False
    passability: bool = False
    players: frozenset[str] = frozenset()
    scripts: ScriptsMode = ScriptsMode.ALL
    referenced_objects: bool = True
    referenced_waypoints: bool = True
    referenced_areas: bool = True


def _text(properties: dict[str, Any] | None, key: str) -> str:
    stored = properties.get(key) if properties is not None else None
    value = stored["value"] if stored is not None else ""
    return value if isinstance(value, str) else ""


def _integer(properties: dict[str, Any], key: str) -> int | None:
    stored = properties.get(key)
    value = stored["value"] if stored is not None else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _objects(map: Map | ScriptLibrary) -> list[Object]:
    return map.objects_list.object_list if map.objects_list is not None else []


def _is_waypoint(obj: Object) -> bool:
    return obj.type_name.startswith(WAYPOINT_PREFIX)


def _team_of(obj: Object) -> str:
    """The team an object is on: the last part of its `originalOwner` (`player/team`)."""
    return _text(obj.properties, "originalOwner").rsplit("/", 1)[-1]


def _teams(map: Map) -> list[Team]:
    return map.teams.teams if map.teams is not None else []


def _player_names(map: Map) -> list[str]:
    players = map.sides_list.players if map.sides_list is not None else []
    return [_text(player.properties, "playerName") for player in players]


def _size(map: Map) -> tuple[int, int]:
    height = map.height_map_data
    return (height.width, height.height) if height is not None else (0, 0)


def _references(items: Iterable[Any]) -> dict[ScriptArgumentType, set[str]]:
    """The names each reference argument type of the scripts under `items` gives."""
    found: dict[ScriptArgumentType, set[str]] = {kind: set() for kind in _REFERENCE_TYPES}
    for location in iter_script_items(list(items)):
        script = location.item
        if not isinstance(script, Script):
            continue
        entries = [c for clause in script.or_conditions for c in clause.conditions]
        for entry in entries + script.actions_if_true + script.actions_if_false:
            for argument in entry.arguments:
                if argument.type in found and argument.string_value:
                    found[argument.type].add(argument.string_value)
    return found


def _linked(map: Map, starts: set[int]) -> set[int]:
    """The waypoint ids on the paths through `starts`, as `0x005337E0` marks a whole path."""
    neighbours: dict[int, set[int]] = defaultdict(set)
    for first, second in map.waypoints_list.waypoint_paths if map.waypoints_list else []:
        neighbours[first].add(second)
        neighbours[second].add(first)
    seen, stack = set(starts), list(starts)
    while stack:
        for following in neighbours[stack.pop()]:
            if following not in seen:
                seen.add(following)
                stack.append(following)
    return seen


def _passability(map: Map) -> ScriptPassability | None:
    blend, (width, height) = map.blend_tile_data, _size(map)
    if blend is None:
        return None
    cells: dict[str, list[list[int]]] = {}
    for name, _since in LAYERS:
        values = np.full((width, height), 1 if name == "visibility" else 0, dtype=np.int64)
        stored = getattr(blend, name)
        if stored is not None:
            source = np.array([[int(value) for value in column] for column in stored])
            if source.ndim == 2:
                columns, rows = min(width, source.shape[0]), min(height, source.shape[1])
                values[:columns, :rows] = source[:columns, :rows]
        cells[name] = values.tolist()
    return ScriptPassability(3, cells, 0, 0)


def build_export(
    map: Map,
    options: ExportOptions,
    *,
    selection: Iterable[object] = (),
    selected_scripts: Sequence[Any] = (),
) -> ScriptLibrary:
    """The library WorldBuilder's export writes for `options`: `selection` is the view's selected
    objects, `selected_scripts` the groups and scripts chosen in the Scripts panel."""
    library = ScriptLibrary()
    width, height = _size(map)
    library.script_import_size = ScriptImportSize(1, width, height, 0, 0)
    if options.passability:
        library.script_passability = _passability(map)

    lists = player_script_lists(map)
    exported: list[ScriptList] = []
    if options.scripts is ScriptsMode.ALL:
        exported = [
            replace(script_list, items=copy.deepcopy(script_list.items)) for _, script_list in lists
        ]
    elif options.scripts is ScriptsMode.SELECTED:
        exported = [ScriptList(1, copy.deepcopy(list(selected_scripts)), 0, 0)]
    scripts_chunk = map.player_scripts_list
    library.player_scripts_list = (
        replace(scripts_chunk, script_lists=exported)
        if scripts_chunk is not None
        else PlayerScriptsList(1, exported, 0, 0)
    )
    references = _references(item for script_list in exported for item in script_list.items)

    cameras = map.named_cameras
    library.named_cameras = NamedCameras(
        cameras.version if cameras is not None else 2,
        [
            copy.deepcopy(camera)
            for camera in (cameras.cameras if cameras is not None else [])
            if options.scripts is ScriptsMode.ALL or camera.name in references[_T.CAMERA_NAME]
        ],
        0,
        0,
    )
    animations = map.camera_animation_list
    library.camera_animation_list = CameraAnimationList(
        animations.version if animations is not None else 3,
        copy.deepcopy(animations.animations)
        if animations is not None and options.scripts is not ScriptsMode.NONE
        else [],
        0,
        0,
    )

    sides = map.sides_list.players if map.sides_list is not None else []
    if options.scripts is ScriptsMode.ALL or options.all_players:
        players = [
            ScriptPlayer(
                _text(side.properties, "playerName"),
                copy.deepcopy(side.properties) if options.all_players else None,
            )
            for side in sides
        ]
    else:
        players = [ScriptPlayer(SELECTION_PLAYER, None)]
    library.scripts_players = ScriptsPlayers(2, int(options.all_players), players, 0, 0)

    objects = _objects(map)
    chosen = {id(item) for item in selection}
    owners = {
        _text(team.properties, "teamName"): _text(team.properties, "teamOwner")
        for team in _teams(map)
    }
    wanted: set[int] = set()
    for obj in objects:
        waypoint = _is_waypoint(obj)
        if (
            (options.selected_objects and id(obj) in chosen)
            or (options.all_waypoints and waypoint)
            or (not waypoint and owners.get(_team_of(obj), None) in options.players)
        ):
            wanted.add(id(obj))
    if options.referenced_objects:
        units, teams = references[_T.UNIT_NAME], references[_T.TEAM_NAME]
        for obj in objects:
            if not _is_waypoint(obj) and (
                _text(obj.properties, "objectName") in units or _team_of(obj) in teams
            ):
                wanted.add(id(obj))
    if options.referenced_waypoints:
        names, labels = references[_T.WAYPOINT_NAME], references[_T.WAYPOINT_PATH_NAME]
        starts = {
            identity
            for obj in objects
            if _is_waypoint(obj)
            and (identity := _integer(obj.properties, "waypointID")) is not None
            and (
                _text(obj.properties, "waypointName") in names
                or any(_text(obj.properties, key) in labels for key in _PATH_LABELS)
            )
        }
        on_paths = _linked(map, starts)
        for obj in objects:
            if _is_waypoint(obj) and _integer(obj.properties, "waypointID") in on_paths:
                wanted.add(id(obj))
    chosen_objects = with_partners(map, [obj for obj in objects if id(obj) in wanted])
    listed = map.objects_list
    library.objects_list = ObjectsList(
        listed.version if listed is not None else 3,
        [copy.deepcopy(obj) for obj in chosen_objects],
        0,
        0,
    )

    areas = map.trigger_areas
    area_names = references[_T.TRIGGER_AREA_NAME] if options.referenced_areas else set()
    library.trigger_areas = TriggerAreas(
        areas.version if areas is not None else 1,
        [
            copy.deepcopy(area)
            for area in (areas.trigger_areas if areas is not None else [])
            if options.all_areas or area.name in area_names
        ],
        0,
        0,
    )

    if options.water:
        for _kind, name in _WATER:
            setattr(library, name, copy.deepcopy(getattr(map, name)))

    team_names = references[_T.TEAM_NAME] | {_team_of(obj) for obj in chosen_objects}
    library.script_teams = ScriptTeams(
        1,
        [
            copy.deepcopy(team)
            for team in _teams(map)
            if options.scripts is ScriptsMode.ALL
            or _text(team.properties, "teamName") in team_names
        ],
        0,
        0,
    )

    exported_ids = {
        identity
        for obj in chosen_objects
        if _is_waypoint(obj) and (identity := _integer(obj.properties, "waypointID")) is not None
    }
    paths = map.waypoints_list
    library.waypoints_list = WaypointsList(
        paths.version if paths is not None else 1,
        [
            (first, second)
            for first, second in (paths.waypoint_paths if paths is not None else [])
            if first in exported_ids and second in exported_ids
        ],
        0,
        0,
    )

    if (options.terrain_texture or options.terrain_height) and map.height_map_data is not None:
        library.height_map_data = copy.deepcopy(map.height_map_data)
        library.script_apply_height = ScriptApplyHeight(1, options.terrain_height, 0, 0)
        if options.terrain_texture and map.blend_tile_data is not None:
            library.blend_tile_data = copy.deepcopy(map.blend_tile_data)
    if options.lighting and map.global_lighting is not None:
        library.global_lighting = copy.deepcopy(map.global_lighting)
    return library


class DuplicateKind(Enum):
    OBJECT = "object"
    WAYPOINT = "waypoint"
    AREA = "area trigger"


class DuplicatePolicy(Enum):
    """The Duplicate ... Detected dialogs' (253-255) answers."""

    KEEP_EXISTING = "existing"
    KEEP_IMPORTED = "imported"


def _uses_selection(library: ScriptLibrary) -> bool:
    players = library.scripts_players.players if library.scripts_players is not None else []
    return len(players) == 1 and players[0].name == SELECTION_PLAYER


@dataclass
class ImportPlan:
    """What an import of a library into a map has to ask before it can be applied."""

    import_size: tuple[int, int]
    map_size: tuple[int, int]
    duplicates: dict[DuplicateKind, list[str]]
    # (team, the player it belongs to) for teams whose player the map lacks.
    teams_without_player: list[tuple[str, str]]
    uses_selection: bool
    missing_script_players: list[str]

    @property
    def needs_anchor(self) -> bool:
        return self.import_size != self.map_size

    def offset(self, anchor: Anchor) -> tuple[int, int]:
        """Where the library's first cell lands, in cells: the size difference at the far edge,
        half of it (rounded toward zero) at the centre, none at the near edge."""
        horizontal, vertical = anchor.value
        return (
            int((self.map_size[0] - self.import_size[0]) * horizontal / 2),
            int((self.map_size[1] - self.import_size[1]) * vertical / 2),
        )


def plan_import(map: Map, library: ScriptLibrary) -> ImportPlan:
    size = library.script_import_size
    existing = _objects(map)
    duplicates: dict[DuplicateKind, list[str]] = {kind: [] for kind in DuplicateKind}
    waypoint_names = {
        _text(obj.properties, "waypointName") for obj in existing if _is_waypoint(obj)
    }
    object_names = {
        name
        for obj in existing
        if not _is_waypoint(obj) and (name := _text(obj.properties, "objectName"))
    }
    for obj in _objects(library):
        if _is_waypoint(obj):
            name = _text(obj.properties, "waypointName")
            if name in waypoint_names:
                duplicates[DuplicateKind.WAYPOINT].append(name)
        elif (name := _text(obj.properties, "objectName")) and name in object_names:
            duplicates[DuplicateKind.OBJECT].append(name)
    area_names = (
        {area.name for area in map.trigger_areas.trigger_areas} if map.trigger_areas else set()
    )
    for area in library.trigger_areas.trigger_areas if library.trigger_areas else []:
        if area.name in area_names:
            duplicates[DuplicateKind.AREA].append(area.name)

    players = set(_player_names(map))
    team_names = {_text(team.properties, "teamName") for team in _teams(map)}
    without = [
        (name, owner)
        for team in (library.script_teams.teams if library.script_teams else [])
        if (name := _text(team.properties, "teamName")) not in team_names
        and (owner := _text(team.properties, "teamOwner")) not in players
    ]
    selection = _uses_selection(library)
    missing: list[str] = []
    if not selection and library.player_scripts_list is not None:
        names = (
            [player.name for player in library.scripts_players.players]
            if library.scripts_players
            else []
        )
        for index, script_list in enumerate(library.player_scripts_list.script_lists):
            name = names[index] if index < len(names) else ""
            if script_list.items and name not in players:
                missing.append(name)
    return ImportPlan(
        (size.width, size.height) if size is not None else _size(map),
        _size(map),
        duplicates,
        without,
        selection,
        missing,
    )


@dataclass
class ImportChoices:
    """The answers an import needs: the anchor, each duplicate's policy (by kind, then name, with
    a default per kind), the player each ownerless team goes to (absent or `None`: the team is not
    imported), and the player selected scripts go to."""

    anchor: Anchor = Anchor.CENTER
    duplicate_defaults: dict[DuplicateKind, DuplicatePolicy] = field(default_factory=dict)
    duplicates: dict[tuple[DuplicateKind, str], DuplicatePolicy] = field(default_factory=dict)
    team_players: dict[str, str | None] = field(default_factory=dict)
    selection_player: str | None = None

    def policy(self, kind: DuplicateKind, name: str) -> DuplicatePolicy:
        return self.duplicates.get(
            (kind, name), self.duplicate_defaults.get(kind, DuplicatePolicy.KEEP_EXISTING)
        )


@dataclass
class ImportReport:
    objects: int = 0
    waypoints: int = 0
    areas: int = 0
    teams: int = 0
    scripts: int = 0
    dropped_scripts: list[str] = field(default_factory=list)
    discarded_players: list[str] = field(default_factory=list)
    skipped_teams: list[str] = field(default_factory=list)
    not_imported: list[str] = field(default_factory=list)


class _Append(Command):
    """Append items to a list; undo removes them. The position is taken when it runs, so earlier
    removals in the same import do not shift it."""

    def __init__(self, items: MutableSequence[Any], added: Sequence[Any], *changes: Change) -> None:
        self.items = items
        self.added = list(added)
        self._changes = changes
        self._start = 0
        self.label = "Import"

    def do(self, document: MapDocument) -> None:
        self._start = len(self.items)
        self.items.extend(self.added)

    def undo(self, document: MapDocument) -> None:
        del self.items[self._start : self._start + len(self.added)]

    def changes(self) -> tuple[Change, ...]:
        return self._changes


def _shifted(point: Sequence[float], dx: float, dy: float) -> tuple[float, ...]:
    return (point[0] + dx, point[1] + dy, *point[2:])


def _shifted3(point: Sequence[float], dx: float, dy: float) -> tuple[float, float, float]:
    """`_shifted` for the fields typed as a fixed 3-tuple: a camera's, an object's."""
    x, y, z = _shifted(point, dx, dy)
    return (x, y, z)


def _script_names(items: Iterable[Any]) -> set[str]:
    return {
        location.item.name
        for location in iter_script_items(list(items))
        if isinstance(location.item, Script)
    }


def _filtered(items: list[Any], taken: set[str], report: ImportReport) -> list[Any]:
    """`items` without the scripts whose names are taken, groups kept."""
    kept: list[Any] = []
    for item in items:
        if isinstance(item, ScriptGroup):
            kept.append(replace(item, items=_filtered(item.items, taken, report)))
        elif item.name in taken:
            report.dropped_scripts.append(item.name)
        else:
            taken.add(item.name)
            report.scripts += 1
            kept.append(item)
    return kept


def _merge_scripts(
    target: list[Any], imported: list[Any], taken: set[str], report: ImportReport
) -> list[Command]:
    """Commands appending `imported` under `target`, without the scripts whose names are taken.
    A group whose name the level already has takes the imported group's scripts (a choice)."""
    commands: list[Command] = []
    added: list[Any] = []
    for item in imported:
        if isinstance(item, ScriptGroup):
            existing = next(
                (
                    each
                    for each in target
                    if isinstance(each, ScriptGroup) and each.name == item.name
                ),
                None,
            )
            if existing is not None:
                commands += _merge_scripts(existing.items, item.items, taken, report)
            else:
                added.append(replace(item, items=_filtered(item.items, taken, report)))
        elif item.name in taken:
            report.dropped_scripts.append(item.name)
        else:
            taken.add(item.name)
            report.scripts += 1
            added.append(item)
    if added:
        commands.append(_Append(target, added, Change(ChangeKind.SCRIPTS)))
    return commands


def import_library(
    map: Map, library: ScriptLibrary, choices: ImportChoices
) -> tuple[Command | None, ImportReport]:
    """The edit merging `library` into `map`, and what it did and left out."""
    plan = plan_import(map, library)
    report = ImportReport()
    dx_cells, dy_cells = plan.offset(choices.anchor) if plan.needs_anchor else (0, 0)
    dx, dy = dx_cells * _CELL, dy_cells * _CELL
    commands: list[Command] = []

    commands += _import_objects(map, library, choices, dx, dy, report)
    commands += _import_areas(map, library, choices, dx, dy, report)
    commands += _import_teams(map, library, choices, report)
    commands += _import_scripts(map, library, choices, report)
    commands += _import_terrain(map, library, dx_cells, dy_cells, report)
    commands += _import_water(map, library, dx, dy, report)

    if library.global_lighting is not None:
        commands.append(
            SetAttribute(
                map,
                "global_lighting",
                copy.deepcopy(library.global_lighting),
                Change(ChangeKind.SETTINGS),
                "Import",
            )
        )
    if library.named_cameras is not None and map.named_cameras is not None:
        names = {camera.name for camera in map.named_cameras.cameras}
        cameras = []
        for camera in library.named_cameras.cameras:
            if camera.name not in names:
                cameras.append(
                    replace(camera, look_at_point=_shifted3(camera.look_at_point, dx, dy))
                )
        if cameras:
            commands.append(_Append(map.named_cameras.cameras, cameras, Change(ChangeKind.CAMERAS)))
    if library.camera_animation_list is not None and map.camera_animation_list is not None:
        names = {animation.name for animation in map.camera_animation_list.animations}
        animations = [
            copy.deepcopy(animation)
            for animation in library.camera_animation_list.animations
            if animation.name not in names
        ]
        if animations:
            commands.append(
                _Append(
                    map.camera_animation_list.animations, animations, Change(ChangeKind.CAMERAS)
                )
            )
    if not commands:
        return None, report
    return CompositeCommand("Import", commands), report


def _import_objects(
    map: Map,
    library: ScriptLibrary,
    choices: ImportChoices,
    dx: float,
    dy: float,
    report: ImportReport,
) -> list[Command]:
    imported = _objects(library)
    if not imported:
        return []
    if map.objects_list is None:
        report.not_imported.append("objects (the map has no object list)")
        return []
    existing = _objects(map)
    waypoints = {
        _text(obj.properties, "waypointName"): obj for obj in existing if _is_waypoint(obj)
    }
    named: dict[str, list[Object]] = defaultdict(list)
    for obj in existing:
        if not _is_waypoint(obj) and (name := _text(obj.properties, "objectName")):
            named[name].append(obj)
    id_offset = next_waypoint_id(map) - 1
    number = next_unique_number(map)
    removed: list[Object] = []
    added: list[Object] = []
    ids: dict[int, int] = {}
    for obj in imported:
        new = copy.deepcopy(obj)
        new.position = _shifted3(new.position, dx, dy)
        if _is_waypoint(obj):
            name, old = (
                _text(obj.properties, "waypointName"),
                _integer(obj.properties, "waypointID"),
            )
            present = waypoints.get(name)
            if present is not None:
                if choices.policy(DuplicateKind.WAYPOINT, name) is DuplicatePolicy.KEEP_EXISTING:
                    kept = _integer(present.properties, "waypointID")
                    if old is not None and kept is not None:
                        ids[old] = kept
                    continue
                removed.append(present)
            if old is not None:
                ids[old] = old + id_offset
                new.properties["waypointID"] = {
                    **new.properties["waypointID"],
                    "value": old + id_offset,
                }
            report.waypoints += 1
        else:
            name = _text(obj.properties, "objectName")
            if name and named.get(name):
                if choices.policy(DuplicateKind.OBJECT, name) is DuplicatePolicy.KEEP_EXISTING:
                    continue
                removed += named[name]
            if "uniqueID" in new.properties:
                new.properties["uniqueID"] = {
                    **new.properties["uniqueID"],
                    "value": f"{new.type_name} {number}",
                }
                number += 1
            report.objects += 1
        added.append(new)

    commands: list[Command] = []
    if removed:
        commands.append(DeleteObjects(removed, "Import"))
    if added:
        commands.append(
            _Append(
                map.objects_list.object_list,
                added,
                Change(ChangeKind.OBJECTS),
                Change(ChangeKind.WAYPOINTS),
            )
        )
    if library.waypoints_list is not None and map.waypoints_list is not None:
        links = [
            (ids[first], ids[second])
            for first, second in library.waypoints_list.waypoint_paths
            if first in ids and second in ids
        ]
        if links:
            commands.append(
                _Append(map.waypoints_list.waypoint_paths, links, Change(ChangeKind.WAYPOINTS))
            )
    return commands


def _import_areas(
    map: Map,
    library: ScriptLibrary,
    choices: ImportChoices,
    dx: float,
    dy: float,
    report: ImportReport,
) -> list[Command]:
    imported = library.trigger_areas.trigger_areas if library.trigger_areas is not None else []
    if not imported:
        return []
    if map.trigger_areas is None:
        report.not_imported.append("trigger areas (the map has no trigger area list)")
        return []
    existing: dict[str, list[Any]] = defaultdict(list)
    for area in map.trigger_areas.trigger_areas:
        existing[area.name].append(area)
    removed: list[Any] = []
    added: list[Any] = []
    identity = next_trigger_area_id(map)
    for area in imported:
        if existing.get(area.name):
            if choices.policy(DuplicateKind.AREA, area.name) is DuplicatePolicy.KEEP_EXISTING:
                continue
            removed += existing[area.name]
        added.append(
            replace(
                area,
                area_id=identity,
                points=[(x + dx, y + dy) for x, y in area.points],
            )
        )
        identity += 1
        report.areas += 1
    commands: list[Command] = []
    if removed:
        commands.append(DeleteAreas(removed, "Import"))
    if added:
        commands.append(_Append(map.trigger_areas.trigger_areas, added, Change(ChangeKind.AREAS)))
    return commands


def _import_teams(
    map: Map, library: ScriptLibrary, choices: ImportChoices, report: ImportReport
) -> list[Command]:
    imported = library.script_teams.teams if library.script_teams is not None else []
    if not imported or map.teams is None:
        return []
    players = set(_player_names(map))
    names = {_text(team.properties, "teamName") for team in _teams(map)}
    added: list[Team] = []
    for team in imported:
        name, owner = _text(team.properties, "teamName"), _text(team.properties, "teamOwner")
        if name in names:
            continue
        new = copy.deepcopy(team)
        if owner not in players:
            chosen = choices.team_players.get(name)
            if chosen is None:
                report.skipped_teams.append(name)
                continue
            new.properties["teamOwner"] = {**new.properties["teamOwner"], "value": chosen}
        names.add(name)
        added.append(new)
        report.teams += 1
    return [_Append(map.teams.teams, added, Change(ChangeKind.SIDES))] if added else []


def _import_scripts(
    map: Map, library: ScriptLibrary, choices: ImportChoices, report: ImportReport
) -> list[Command]:
    if library.player_scripts_list is None:
        return []
    targets = dict(player_script_lists(map))
    names = (
        [player.name for player in library.scripts_players.players]
        if library.scripts_players
        else []
    )
    selection = _uses_selection(library)
    commands: list[Command] = []
    for index, script_list in enumerate(library.player_scripts_list.script_lists):
        if not script_list.items:
            continue
        name = (
            choices.selection_player if selection else (names[index] if index < len(names) else "")
        )
        target = targets.get(name) if name is not None else None
        if target is None:
            report.discarded_players.append(SELECTION_PLAYER if name is None else name)
            continue
        taken = _script_names(target.items)
        commands += _merge_scripts(target.items, copy.deepcopy(script_list.items), taken, report)
    return commands


def _placed(
    source: np.ndarray, target_shape: tuple[int, int], dx: int, dy: int
) -> tuple[int, int, np.ndarray] | None:
    """The part of `source` (`[row, column]`, rows from the bottom) that lands inside a target of
    `target_shape` when its first cell goes to `(dx, dy)`, with where it lands."""
    rows, columns = source.shape
    x0, y0 = max(dx, 0), max(dy, 0)
    x1, y1 = min(dx + columns, target_shape[1]), min(dy + rows, target_shape[0])
    if x0 >= x1 or y0 >= y1:
        return None
    return x0, y0, source[y0 - dy : y1 - dy, x0 - dx : x1 - dx]


def _import_terrain(
    map: Map, library: ScriptLibrary, dx: int, dy: int, report: ImportReport
) -> list[Command]:
    commands: list[Command] = []
    passability = library.script_passability
    if passability is not None and map.blend_tile_data is not None:
        blocks: dict[tuple[int, int], dict[CellLayer, np.ndarray]] = {}
        for name, values in passability.cells.items():
            layer = CellLayer(name)
            current = layer_array(map.blend_tile_data, layer)
            if current is None or not values:
                continue
            source = np.array(values).T.astype(current.dtype)
            placed = _placed(source, current.shape, dx, dy)
            if placed is not None:
                x0, y0, block = placed
                blocks.setdefault((x0, y0), {})[layer] = block
        for (x0, y0), layers in blocks.items():
            commands.append(PatchCells(x0, y0, layers, "Import"))

    heights, apply = library.height_map_data, library.script_apply_height
    target = map.height_map_data
    if heights is not None and apply is not None and apply.apply_height and target is not None:
        source = np.array(heights.elevations, dtype=np.uint16)[::-1]
        placed = _placed(source, (target.height, target.width), dx, dy)
        if placed is not None:
            x0, y0, block = placed
            commands.append(PatchHeights(x0, y0, block, "Import"))
    if library.blend_tile_data is not None and map.blend_tile_data is not None:
        merge = merge_textures(map.blend_tile_data, library.blend_tile_data, dx, dy)
        if merge is not None:
            commands.append(
                ReplaceTerrainTables(
                    merge.patches,
                    merge.textures,
                    merge.descriptions,
                    merge.cliff_mappings,
                    "Import",
                )
            )
            if merge.left_out:
                report.not_imported.append(
                    "terrain textures with no room in the map: " + ", ".join(merge.left_out)
                )
    return commands


def _import_water(
    map: Map, library: ScriptLibrary, dx: float, dy: float, report: ImportReport
) -> list[Command]:
    commands: list[Command] = []
    for kind, name in _WATER:
        chunk = getattr(library, name)
        if chunk is None or not chunk.areas:
            continue
        listed = water_areas(map, kind)
        if listed is None:
            report.not_imported.append(f"{kind.value} areas (the map has no chunk for them)")
            continue
        identity = next_water_id(map, kind)
        added = []
        for area in chunk.areas:
            new = copy.deepcopy(area)
            new.unique_id = identity
            identity += 1
            if kind is WaterKind.RIVER:
                new.lines = [
                    (_shifted(left, dx, dy), _shifted(right, dx, dy)) for left, right in new.lines
                ]
            else:
                new.points = [_shifted(point, dx, dy) for point in new.points]
            added.append(new)
        commands.append(_Append(listed, added, Change(ChangeKind.WATER)))
    return commands
