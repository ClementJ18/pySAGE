"""The `maps\\mapcache.ini` entry the game needs before it will list a map or start it.

`-file` does not start a file, it starts a **cache entry**: `TheMapCache` is populated once at
startup from `maps\\mapcache.ini`, and a map that file does not name cannot be reached from the
lobby or the command line at all. The engine writes that file itself for maps under the user's
Maps folder, but it never rewrites one inside a `.big`, so a mod's cache is maintained by hand -
which is what this module is for: it derives the block a finished map needs, to be pasted into the
mod's `mapcache.ini`.

What the fields mean, and the field table the engine parses them with, is written up in
``sage_patch/docs/map-list-symbols.md`` §1. Two of them are worth repeating here:

- **Unknown keywords are fatal.** `mapSymbol` is a field the map-list-symbols engine patch adds;
  a `mapcache.ini` carrying it will not load on an unpatched `game.dat`, so it is left out unless
  it is set.
- **A non-multiplayer entry cannot be auto-started.** `isMultiplayer` defaults to what the engine
  derives - two or more player starts - but it is the mod's to decide, and every War of the Ring
  map in Edain's cache turns it off by hand.

Everything derived here was checked against Edain's 432-entry `mapcache.ini`, over the 25 maps
whose file on disk still matches the entry: extents, player count and the player starts reproduce
exactly, and `sage_crc` reproduces 22 of the 25 `fileCRC` values (the other three are maps edited
since, coincidentally back to the same size).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sage_worldbuilder.dressing import playable_size
from sage_worldbuilder.selection_helpers import TemplateIndex
from sage_worldbuilder.terrain.grid import WORLD_UNITS_PER_CELL

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_map.assets.object_list import Object
    from sage_map.map import Map

__all__ = [
    "CAMERA_WAYPOINT",
    "MAX_PLAYERS",
    "MAX_SYMBOL",
    "SUPPLY_KIND",
    "FileIdentity",
    "MapCacheEntry",
    "build_entry",
    "cache_key",
    "escape",
    "escape_text",
    "sage_crc",
    "string_base",
]

Coord = tuple[float, float, float]

#: The engine's field table names `Player_1_Start` through `Player_8_Start` and no more.
MAX_PLAYERS = 8

#: `mapSymbol` is two digits wide - it names the `AptMapSymbolNN` images the patch draws.
MAX_SYMBOL = 99

#: The waypoint the engine reads `InitialCameraPosition` from.
CAMERA_WAYPOINT = "InitialCameraPosition"

#: The `KindOf` that puts an object's position in the entry's `supplyPosition` list, which is what
#: draws the resource markers on the lobby's map preview. There is no BFME `KindOf` answering for
#: `techPosition`, so that list is never derived - the field exists, but nothing fills it.
SUPPLY_KIND = "SUPPLY_SOURCE_ON_PREVIEW"

_START_PREFIX = "player_"
_START_SUFFIX = "_start"

# FILETIME counts 100ns ticks from 1601-01-01, 11,644,473,600 seconds before the Unix epoch.
_FILETIME_EPOCH = 116_444_736_000_000_000


def sage_crc(data: bytes) -> int:
    """The engine's own CRC over `data`, which is not a standard one.

    Each byte rotates the accumulator left by one and is added to it - the bit shifted off the top
    comes back in at the bottom, where the addition can then carry it up again.
    """
    crc = 0
    for byte in data:
        crc = ((((crc << 1) & 0xFFFFFFFF) | (crc >> 31)) + byte) & 0xFFFFFFFF
    return crc


def escape(raw: bytes) -> str:
    """`raw` in the `_XX` escaping the cache uses for its key and its two text fields.

    An ASCII letter or digit stands for itself and every other byte becomes its two hex digits
    after an underscore - so `_` itself escapes, as `_5F`, and a name round-trips unambiguously.
    """
    return "".join(
        chr(byte) if (48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122) else f"_{byte:02X}"
        for byte in raw
    )


def escape_text(text: str) -> str:
    """A `displayName` or `description` value: the entry holds a `UnicodeString`, so what is
    escaped is the UTF-16LE form - which is why every second byte of a plain name reads `_00`."""
    return escape(text.encode("utf-16-le"))


def cache_key(map_path: str | Path) -> str:
    """The `MapCache` block's key for the map at `map_path`, escaped.

    The engine keys a map by `maps\\<folder>\\<file>`, lower-cased, wherever the file itself sits:
    the path is rebuilt from the map's own folder rather than taken from the caller, so a map
    opened from an install, a mod tree or a working copy all key the same.
    """
    path = Path(map_path)
    return escape(f"maps\\{path.parent.name}\\{path.name}".lower().encode("latin-1"))


def string_base(map_path: str | Path) -> str:
    """The name the map's `displayName` and `description` are built on: its file name without the
    extension and without spaces, which is how the game's string table spells a map label."""
    return Path(map_path).stem.replace(" ", "")


@dataclass(frozen=True)
class FileIdentity:
    """What the entry says about the `.map` file itself.

    The engine compares these four against the file before it trusts a cached entry, so they
    describe the map **as saved** - a map with unsaved edits needs the entry generated again.
    """

    file_size: int = 0
    file_crc: int = 0
    timestamp_lo: int = 0
    timestamp_hi: int = 0

    @classmethod
    def of(cls, path: str | Path) -> FileIdentity:
        """Read the file at `path`. The timestamp is its last-write time as a Windows FILETIME,
        split into the two halves the entry stores, the low one signed as the engine parses it."""
        stat = Path(path).stat()
        ticks = stat.st_mtime_ns // 100 + _FILETIME_EPOCH
        low = ticks & 0xFFFFFFFF
        return cls(
            file_size=stat.st_size,
            file_crc=sage_crc(Path(path).read_bytes()),
            timestamp_lo=low - 0x100000000 if low >= 0x80000000 else low,
            timestamp_hi=ticks >> 32,
        )


@dataclass
class MapCacheEntry:
    """One `MapCache` block, ready to be written out.

    The fields the map decides (its extents, its player starts, its supply markers) are filled by
    `build_entry`; the rest are the mod's to choose and carry the engine's own defaults.
    """

    key: str
    identity: FileIdentity = field(default_factory=FileIdentity)
    is_official: bool = True
    map_symbol: int = 0
    is_multiplayer: bool = False
    is_scenario_mp: bool = False
    num_players: int = 0
    extent_min: Coord = (0.0, 0.0, 0.0)
    extent_max: Coord = (0.0, 0.0, 0.0)
    display_name: str = ""
    description: str = ""
    initial_camera: Coord | None = None
    player_starts: dict[int, Coord] = field(default_factory=dict)
    supply_positions: list[Coord] = field(default_factory=list)
    tech_positions: list[Coord] = field(default_factory=list)

    def rows(self) -> list[tuple[str, str]]:
        """The entry's `name = value` pairs, in the order the engine's own writer emits them.

        `mapSymbol` is left out when it is 0, which is both its default and a field an unpatched
        engine refuses; `InitialCameraPosition` when the map has no such waypoint.
        """
        rows = [
            ("fileSize", str(self.identity.file_size)),
            ("fileCRC", str(self.identity.file_crc)),
            ("timestampLo", str(self.identity.timestamp_lo)),
            ("timestampHi", str(self.identity.timestamp_hi)),
            ("isOfficial", _yes_no(self.is_official)),
        ]
        if self.map_symbol:
            rows.append(("mapSymbol", str(self.map_symbol)))
        rows += [
            ("isMultiplayer", _yes_no(self.is_multiplayer)),
            ("isScenarioMP", _yes_no(self.is_scenario_mp)),
            ("numPlayers", str(self.num_players)),
            ("extentMin", _coord(self.extent_min)),
            ("extentMax", _coord(self.extent_max)),
            ("displayName", escape_text(self.display_name)),
            ("description", escape_text(self.description)),
        ]
        if self.initial_camera is not None:
            rows.append((CAMERA_WAYPOINT, _coord(self.initial_camera)))
        rows += [
            (f"Player_{index}_Start", _coord(position))
            for index, position in sorted(self.player_starts.items())
        ]
        rows += [("supplyPosition", _coord(position)) for position in self.supply_positions]
        rows += [("techPosition", _coord(position)) for position in self.tech_positions]
        return rows

    def text(self) -> str:
        """The block as it goes into `mapcache.ini`, its `=` aligned on the widest field name as
        the hand-maintained caches align theirs."""
        rows = self.rows()
        width = max(len(name) for name, _ in rows)
        lines = [f"MapCache {self.key}"]
        lines += [f"    {name.ljust(width)} = {value}" for name, value in rows]
        lines.append("End")
        return "\n".join(lines) + "\n"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _coord(position: Coord) -> str:
    x, y, z = position
    return f"X:{x:.2f} Y:{y:.2f} Z:{z:.2f}"


def _value(obj: Object, key: str) -> object:
    stored = obj.properties.get(key)
    return None if stored is None else stored["value"]


def _objects(map: Map) -> list[Object]:
    return list(map.objects_list.object_list) if map.objects_list is not None else []


def _waypoints(map: Map) -> dict[str, Object]:
    """The map's waypoints by name, folded to lower case. A duplicate name keeps the first, as a
    map with two waypoints of one name is a map whose scripts already mean the first."""
    found: dict[str, Object] = {}
    for obj in _objects(map):
        name = _value(obj, "waypointName")
        if isinstance(name, str) and name:
            found.setdefault(name.lower(), obj)
    return found


def _player_starts(waypoints: dict[str, Object]) -> dict[int, Coord]:
    """`Player_<n>_Start` for every n the map places one for. The count of these is what the
    engine calls `numPlayers`, and gaps are kept rather than closed up."""
    starts: dict[int, Coord] = {}
    for index in range(1, MAX_PLAYERS + 1):
        obj = waypoints.get(f"{_START_PREFIX}{index}{_START_SUFFIX}")
        if obj is not None:
            starts[index] = obj.position
    return starts


def _supply_positions(map: Map, game: Game | None) -> list[Coord]:
    """Where the lobby preview draws a resource marker: every placed object whose template is
    `SUPPLY_SOURCE_ON_PREVIEW`, in map order. Empty without game data to read the kinds from."""
    if game is None:
        return []
    index = TemplateIndex(game)
    positions: list[Coord] = []
    for obj in _objects(map):
        template = index.get(obj.type_name)
        kinds = getattr(template, "KindOf", None) or []
        if any(str(getattr(kind, "name", kind)).upper() == SUPPLY_KIND for kind in kinds):
            positions.append(obj.position)
    return positions


def _extent(map: Map) -> Coord:
    """The playable area in world units: the heightmap less its border on each side. The far
    corner only - the near one is the origin, as it is in every cached entry."""
    columns, rows = playable_size(map)
    return (columns * WORLD_UNITS_PER_CELL, rows * WORLD_UNITS_PER_CELL, 0.0)


def build_entry(
    map: Map,
    path: str | Path,
    *,
    game: Game | None = None,
    identity: FileIdentity | None = None,
) -> MapCacheEntry:
    """The entry for `map`, saved at `path`.

    `identity` describes the file and is read from `path` when it is not given, so a map that has
    never been saved - or one whose file is gone - can still have the rest of its entry derived.
    `game` is only needed for `supplyPosition`.

    `displayName` and `description` come from Map Settings when the mapper filled them in, and are
    otherwise the string-table labels the game looks for: `$Map:<name>` and `Map:<name>/Desc`.
    """
    if identity is None:
        identity = FileIdentity.of(path) if Path(path).is_file() else FileIdentity()
    info = map.world_info.properties if map.world_info is not None else {}

    def stored(key: str) -> object:
        entry = info.get(key)
        return None if entry is None else entry["value"]

    waypoints = _waypoints(map)
    starts = _player_starts(waypoints)
    camera = waypoints.get(CAMERA_WAYPOINT.lower())
    base = string_base(path)
    name = stored("mapName")
    description = stored("mapDescription")

    return MapCacheEntry(
        key=cache_key(path),
        identity=identity,
        is_multiplayer=len(starts) >= 2,
        is_scenario_mp=bool(stored("isScenarioMultiplayer")),
        num_players=len(starts),
        extent_max=_extent(map),
        display_name=name if isinstance(name, str) and name else f"$Map:{base}",
        description=(
            description if isinstance(description, str) and description else f"Map:{base}/Desc"
        ),
        initial_camera=camera.position if camera is not None else None,
        player_starts=starts,
        supply_positions=_supply_positions(map, game),
    )
