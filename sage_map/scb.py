"""Reader and writer for `.scb` files: WorldBuilder's "Export Scripts" script library.

A `.scb` uses the exact same `CkMp` asset-table container as `.map` (see `sage_map.map`), but
carries only the script-related subset of a map's assets plus three assets that exist nowhere
in a `.map`: `ScriptImportSize` (a persisted dialog size), `ScriptsPlayers` (which players the
scripts were exported for) and `ScriptTeams` (the map's teams, re-exported so WorldBuilder can
remap team references on import). Six of the nine top-level assets - `PlayerScriptsList`,
`NamedCameras`, `CameraAnimationList`, `ObjectsList`, `TriggerAreas`, `WaypointsList` - are the
same classes `sage_map.assets` already parses for `.map`.

`extract_scripts`/`inject_scripts` bridge to `sage_map.map.Map`: extracting builds a library the
way WorldBuilder's "export all" does, and injecting replaces a map's `player_scripts_list` with a
library's - the only thing safe to move without WorldBuilder's interactive reference remapping.
"""

import base64
import io
import logging
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO

from sage_utils import refpack
from sage_utils.stream import BinaryStream

from .assets import (
    CameraAnimationList,
    NamedCameras,
    ObjectsList,
    PlayerScriptsList,
    ScriptImportSize,
    ScriptPlayer,
    ScriptsPlayers,
    ScriptTeams,
    TriggerAreas,
    WaypointsList,
)
from .context import ParsingContext, WritingContext
from .map import Map

__all__ = [
    "ScriptLibrary",
    "extract_scripts",
    "inject_scripts",
    "parse_scb",
    "parse_scb_from_path",
    "write_scb",
    "write_scb_to_path",
]

# The one asset an exported library always carries under "export selected scripts" (no players
# picked): a single pseudo-player standing in for whatever was selected in the tree.
_SELECTION_PLAYER_NAME = "**SELECTION**"


def _serialize(obj: Any) -> Any:
    """Recursively serialize objects to JSON-compatible types. A module-level copy of
    `Map._serialize` - `sage_map.map` is left untouched, so this small helper is duplicated
    rather than shared."""
    if obj is None:
        return None
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    elif isinstance(obj, Enum):
        return obj.value
    elif is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    elif isinstance(obj, dict):
        return {(k.name if isinstance(k, Enum) else k): _serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_serialize(item) for item in obj]
    else:
        return obj


def _player_name(player: Any) -> str:
    """A `SidesList` player's script-facing name: the value of its `playerName` property, or the
    empty string when absent (WorldBuilder's neutral/civilian slots carry an empty name)."""
    prop = player.properties.get("playerName")
    return prop["value"] if prop is not None else ""


class ScriptLibrary:
    compression_bytes: str | None
    assets: dict[int, str]
    ea_compression_header: bytes | None

    script_import_size: ScriptImportSize | None
    player_scripts_list: PlayerScriptsList | None
    named_cameras: NamedCameras | None
    camera_animation_list: CameraAnimationList | None
    scripts_players: ScriptsPlayers | None
    objects_list: ObjectsList | None
    trigger_areas: TriggerAreas | None
    script_teams: ScriptTeams | None
    waypoints_list: WaypointsList | None

    def __init__(self) -> None:
        self.compression_bytes = None
        self.assets = {}
        self.ea_compression_header = None

        self.script_import_size = None
        self.player_scripts_list = None
        self.named_cameras = None
        self.camera_animation_list = None
        self.scripts_players = None
        self.objects_list = None
        self.trigger_areas = None
        self.script_teams = None
        self.waypoints_list = None

    def parse(self, context: ParsingContext) -> None:
        context.parse_assets()
        self.assets = context.assets
        self.compression_bytes = context.compression_bytes

        while context.stream.tell() < len(context.stream.getvalue()):
            asset_name = context.parse_asset_name()
            context.logger.info(f"Processing asset: {asset_name}")
            self.parse_asset(asset_name, context)

    def parse_asset(self, asset_name: str, context: ParsingContext) -> None:
        if asset_name == ScriptImportSize.asset_name:
            self.script_import_size = ScriptImportSize.parse(context)
        elif asset_name == PlayerScriptsList.asset_name:
            self.player_scripts_list = PlayerScriptsList.parse(context)
        elif asset_name == NamedCameras.asset_name:
            self.named_cameras = NamedCameras.parse(context)
        elif asset_name == CameraAnimationList.asset_name:
            self.camera_animation_list = CameraAnimationList.parse(context)
        elif asset_name == ScriptsPlayers.asset_name:
            self.scripts_players = ScriptsPlayers.parse(context)
        elif asset_name == ObjectsList.asset_name:
            self.objects_list = ObjectsList.parse(context)
        elif asset_name == TriggerAreas.asset_name:
            self.trigger_areas = TriggerAreas.parse(context)
        elif asset_name == ScriptTeams.asset_name:
            self.script_teams = ScriptTeams.parse(context)
        elif asset_name == WaypointsList.asset_name:
            self.waypoints_list = WaypointsList.parse(context)
        else:
            raise ValueError(f"Unknown asset: {asset_name}")

    def to_dict(self) -> dict[str, Any]:
        """Convert ScriptLibrary and all assets to a JSON-serializable dictionary"""
        result = {}
        for key, value in self.__dict__.items():
            result[key] = _serialize(value)
        return result

    def write(self, context: WritingContext) -> bytes:
        # Reuse the parsed asset table (like `Map.write`) so a round-trip assigns every asset
        # name the same index it had on disk, byte-exact even though new assets could in
        # principle be added to it.
        if self.assets:
            context.assets_by_index = self.assets.copy()
            context.index_by_asset = {name: idx for idx, name in self.assets.items()}

        # Fixed on-disk order, verified byte-level against all 12 real fixtures.
        if self.script_import_size is not None:
            context.write_asset_name(ScriptImportSize.asset_name)
            self.script_import_size.write(context)

        if self.player_scripts_list is not None:
            context.write_asset_name(PlayerScriptsList.asset_name)
            self.player_scripts_list.write(context)

        if self.named_cameras is not None:
            context.write_asset_name(NamedCameras.asset_name)
            self.named_cameras.write(context)

        if self.camera_animation_list is not None:
            context.write_asset_name(CameraAnimationList.asset_name)
            self.camera_animation_list.write(context)

        if self.scripts_players is not None:
            context.write_asset_name(ScriptsPlayers.asset_name)
            self.scripts_players.write(context)

        if self.objects_list is not None:
            context.write_asset_name(ObjectsList.asset_name)
            self.objects_list.write(context)

        if self.trigger_areas is not None:
            context.write_asset_name(TriggerAreas.asset_name)
            self.trigger_areas.write(context)

        if self.script_teams is not None:
            context.write_asset_name(ScriptTeams.asset_name)
            self.script_teams.write(context)

        if self.waypoints_list is not None:
            context.write_asset_name(WaypointsList.asset_name)
            self.waypoints_list.write(context)

        asset_data = context.stream.getvalue()
        header_stream = BinaryStream(io.BytesIO())

        compression_bytes = self.compression_bytes if self.compression_bytes else "    "
        header_stream.writeFourCc(compression_bytes)

        asset_count = len(context.assets_by_index)
        header_stream.writeUInt32(asset_count)

        for i in range(asset_count, 0, -1):
            asset_name = context.assets_by_index[i]
            header_stream.writeString(asset_name)
            header_stream.writeUInt32(i)

        return header_stream.getvalue() + asset_data


def parse_scb(file: BinaryIO) -> ScriptLibrary:
    """Parse a `.scb` script library. Refpack-tolerant like `parse_map` even though WorldBuilder
    always writes these uncompressed - a stray EA-compressed one should still parse."""
    header = file.read(8)
    ea_compression: bytes | None = header
    if not header.startswith(b"EAR"):
        file.seek(0)
        ea_compression = None

    compressed_data = file.read()

    try:
        decompressed_data = refpack.decompress(compressed_data)
    except refpack.RefpackError:  # not refpack-compressed; treat the bytes as raw
        decompressed_data = compressed_data

    logger = logging.getLogger("sage_map")

    stream = BinaryStream(io.BytesIO(decompressed_data))
    context = ParsingContext(stream)
    context.set_logger(logger)

    lib = ScriptLibrary()
    lib.ea_compression_header = ea_compression
    lib.parse(context)

    return lib


def write_scb(lib: ScriptLibrary) -> bytes:
    """Serialize a `.scb` script library. Always uncompressed - WorldBuilder never compresses
    these, so unlike `write_map` there is no `compress` argument."""
    stream = BinaryStream(io.BytesIO())
    context = WritingContext(stream)
    return lib.write(context)


def parse_scb_from_path(path: str | Path) -> ScriptLibrary:
    with open(path, "rb") as file:
        return parse_scb(file)


def write_scb_to_path(lib: ScriptLibrary, path: str | Path) -> None:
    data = write_scb(lib)
    with open(path, "wb") as file:
        file.write(data)


def extract_scripts(map_: Map) -> ScriptLibrary:
    """Build a `ScriptLibrary` the way WorldBuilder's "Export All Scripts" does: the map's
    script-related assets, repackaged as a `.scb` that can later be re-imported into another map
    with `inject_scripts`."""
    if map_.player_scripts_list is None:
        raise ValueError("map has no player_scripts_list to export")

    lib = ScriptLibrary()
    lib.script_import_size = ScriptImportSize(version=1, width=1, height=1, start_pos=0, end_pos=0)
    lib.player_scripts_list = map_.player_scripts_list

    lib.named_cameras = map_.named_cameras or NamedCameras(
        version=2, cameras=[], start_pos=0, end_pos=0
    )
    lib.camera_animation_list = map_.camera_animation_list or CameraAnimationList(
        version=3, animations=[], start_pos=0, end_pos=0
    )
    lib.objects_list = map_.objects_list or ObjectsList(
        version=3, object_list=[], start_pos=0, end_pos=0
    )
    lib.trigger_areas = map_.trigger_areas or TriggerAreas(
        version=1, trigger_areas=[], start_pos=0, end_pos=0
    )
    lib.waypoints_list = map_.waypoints_list or WaypointsList(
        version=1, waypoint_paths=[], start_pos=0, end_pos=0
    )

    # ScriptTeams is a scb-only asset (no map counterpart to inherit a version from); every
    # fixture observed carries version 1.
    teams = map_.teams.teams if map_.teams is not None else []
    lib.script_teams = ScriptTeams(version=1, teams=teams, start_pos=0, end_pos=0)

    if map_.sides_list is not None:
        players = [
            ScriptPlayer(name=_player_name(player), properties=player.properties)
            for player in map_.sides_list.players
        ]
        lib.scripts_players = ScriptsPlayers(
            version=2, has_properties=1, players=players, start_pos=0, end_pos=0
        )
    else:
        lib.scripts_players = ScriptsPlayers(
            version=2,
            has_properties=0,
            players=[ScriptPlayer(name=_SELECTION_PLAYER_NAME, properties=None)],
            start_pos=0,
            end_pos=0,
        )

    return lib


def inject_scripts(map_: Map, lib: ScriptLibrary) -> None:
    """Replace `map_.player_scripts_list` with the library's. Nothing else moves: the teams and
    players carried in the library exist so WorldBuilder can remap references interactively when
    it re-imports them, which a batch tool cannot do safely."""
    if map_.player_scripts_list is None:
        raise ValueError("map has no player_scripts_list to replace")
    if lib.player_scripts_list is None:
        raise ValueError("script library has no player_scripts_list to inject")

    map_.player_scripts_list = lib.player_scripts_list
