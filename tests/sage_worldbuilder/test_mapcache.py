"""The `mapcache.ini` entry a map needs: the escaping, the engine's CRC, and the derived fields.

The literal values asserted here are copied out of Edain's hand-maintained `mapcache.ini`, which
is also what the `--full` gate at the bottom regenerates entries against.
"""

import re
from pathlib import Path

import pytest

from sage_map.assets.height_map import HeightMapBorder, HeightMapData
from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.world_info import WorldInfo
from sage_map.context import AssetPropertyType
from sage_map.map import Map, parse_map_from_path
from sage_worldbuilder.mapcache import (
    FileIdentity,
    MapCacheEntry,
    build_entry,
    cache_key,
    escape,
    escape_text,
    sage_crc,
)
from tests.conftest import corpus_roots

FIXTURES = Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps"

_TEXT = AssetPropertyType.AsciiString
_BOOL = AssetPropertyType.Boolean
_INT = AssetPropertyType.Integer


def make_map(size=60, border=5, starts=(), camera=None, world=None) -> Map:
    """A map with nothing on it but a heightmap and the waypoints asked for."""
    map = Map()
    map.height_map_data = HeightMapData(
        version=5,
        width=size,
        height=size,
        border_width=border,
        borders=[HeightMapBorder((0, 0), (size - 2 * border, size - 2 * border))],
        area=size * size,
        min_height=0,
        max_height=0,
        elevations=[[0] * size for _ in range(size)],
        start_pos=0,
        end_pos=0,
    )
    objects = [waypoint(name, position) for name, position in starts]
    if camera is not None:
        objects.append(waypoint("InitialCameraPosition", camera))
    map.objects_list = ObjectsList(version=3, object_list=objects, start_pos=0, end_pos=0)
    if world is not None:
        map.world_info = WorldInfo(
            version=1,
            properties={
                key: {"name": key, "type": _BOOL if isinstance(v, bool) else _TEXT, "value": v}
                for key, v in world.items()
            },
            start_pos=0,
            end_pos=0,
        )
    return map


def waypoint(name, position) -> Object:
    return Object(
        version=3,
        position=position,
        angle=0.0,
        road_type=0,
        type_name="*Waypoints/Waypoint",
        properties={
            "waypointID": {"name": "waypointID", "type": _INT, "value": 1},
            "waypointName": {"name": "waypointName", "type": _TEXT, "value": name},
        },
        start_pos=0,
        end_pos=0,
    )


def test_sage_crc_rotates_and_adds():
    # A rotate-left-one then add, so a lone byte is itself and the top bit wraps to the bottom.
    assert sage_crc(b"") == 0
    assert sage_crc(b"\x01") == 1
    assert sage_crc(b"\x01\x00") == 2
    # The top bit comes back in at the bottom: a 1 driven up to bit 31 by 31 zero bytes is back
    # where it started after the thirty-second.
    assert sage_crc(b"\x01" + b"\x00" * 31) == 0x8000_0000
    assert sage_crc(b"\x01" + b"\x00" * 32) == 1
    assert sage_crc(b"BFME") == 0x407


def test_escaping_keeps_only_letters_and_digits():
    assert escape(b"Map01") == "Map01"
    # The escape character escapes itself; a space, a dot and a backslash never stand alone.
    assert escape(b"a_b c.d\\e") == "a_5Fb_20c_2Ed_5Ce"


def test_escape_text_is_the_utf16_form():
    assert escape_text("Map:Aldburg") == "M_00a_00p_00_3A_00A_00l_00d_00b_00u_00r_00g_00"
    assert escape_text("$Map:Aldburg/Desc") == (
        "_24_00M_00a_00p_00_3A_00A_00l_00d_00b_00u_00r_00g_00_2F_00D_00e_00s_00c_00"
    )


def test_cache_key_is_the_maps_folder_path_lowered(tmp_path):
    folder = tmp_path / "deep" / "Aldburg"
    assert cache_key(folder / "Aldburg.map") == "maps_5Caldburg_5Caldburg_2Emap"
    assert cache_key(folder / "Aldburg Horde.map") == "maps_5Caldburg_5Caldburg_20horde_2Emap"


def test_entry_text_aligns_on_the_widest_field():
    entry = MapCacheEntry(key="maps_5Ca_5Ca_2Emap", num_players=1)
    lines = entry.text().splitlines()
    assert lines[0] == "MapCache maps_5Ca_5Ca_2Emap"
    assert lines[-1] == "End"
    columns = {line.index("=") for line in lines[1:-1]}
    assert len(columns) == 1
    assert lines[1] == "    fileSize      = 0"


def test_map_symbol_is_left_out_until_it_is_set():
    entry = MapCacheEntry(key="k")
    assert "mapSymbol" not in entry.text()
    entry.map_symbol = 5
    assert "    mapSymbol     = 5\n" in entry.text()


def test_derived_fields_come_from_the_map():
    map = make_map(
        size=60,
        border=5,
        starts=(("Player_1_Start", (10.0, 20.0, 0.0)), ("Player_3_Start", (30.0, 40.0, -5.0))),
        camera=(1.0, 2.0, 0.0),
        world={"isScenarioMultiplayer": True},
    )
    entry = build_entry(map, "somewhere/Green Fields/Green Fields.map")

    assert entry.key == "maps_5Cgreen_20fields_5Cgreen_20fields_2Emap"
    # 60 cells less a 5-cell border on each side, at ten world units per cell.
    assert entry.extent_max == (500.0, 500.0, 0.0)
    assert entry.extent_min == (0.0, 0.0, 0.0)
    # Two starts, and a gap in their numbering is kept rather than closed up.
    assert entry.num_players == 2
    assert set(entry.player_starts) == {1, 3}
    assert entry.is_multiplayer is True
    assert entry.is_scenario_mp is True
    assert entry.initial_camera == (1.0, 2.0, 0.0)
    assert entry.display_name == "$Map:GreenFields"
    assert entry.description == "Map:GreenFields/Desc"

    rows = dict(entry.rows())
    assert rows["Player_3_Start"] == "X:30.00 Y:40.00 Z:-5.00"
    assert rows["numPlayers"] == "2"
    assert rows["isScenarioMP"] == "yes"


def test_one_start_is_not_a_multiplayer_map():
    map = make_map(starts=(("Player_1_Start", (0.0, 0.0, 0.0)),))
    entry = build_entry(map, "x/One/One.map")
    assert entry.num_players == 1
    assert entry.is_multiplayer is False
    assert entry.initial_camera is None
    assert "InitialCameraPosition" not in entry.text()


def test_map_settings_labels_win_over_the_derived_ones():
    map = make_map(world={"mapName": "Horde: Aldburg", "mapDescription": "A siege."})
    entry = build_entry(map, "x/Aldburg Horde/Aldburg Horde.map")
    assert entry.display_name == "Horde: Aldburg"
    assert entry.description == "A siege."


def test_an_unsaved_map_has_no_file_identity(tmp_path):
    entry = build_entry(make_map(), tmp_path / "Gone" / "Gone.map")
    assert entry.identity == FileIdentity()
    assert dict(entry.rows())["fileSize"] == "0"


def test_file_identity_reads_size_crc_and_timestamp(tmp_path):
    path = tmp_path / "Small" / "Small.map"
    path.parent.mkdir()
    path.write_bytes(b"BFME")
    identity = FileIdentity.of(path)
    assert identity.file_size == 4
    assert identity.file_crc == sage_crc(b"BFME")
    # 2001-09-09 in FILETIME terms: past the point where the high half is six figures, and the
    # low half is stored signed, so it stays in range either way.
    assert identity.timestamp_hi > 29_000_000
    assert -(2**31) <= identity.timestamp_lo < 2**31


def test_a_real_map_generates_a_whole_block():
    path = FIXTURES / "spieler.map"
    entry = build_entry(parse_map_from_path(str(path)), path)
    rows = dict(entry.rows())
    assert entry.num_players == 8
    assert rows["fileSize"] == str(path.stat().st_size)
    assert rows["displayName"] == escape_text("$Map:spieler")
    assert entry.text().count("_Start") == 8


_ENTRY = re.compile(r"^\s*MapCache\s+(\S+)", re.IGNORECASE)
_END = re.compile(r"^\s*End\s*$", re.IGNORECASE)
_FIELD = re.compile(r"^\s*(\w+)\s*=\s*(.*?)\s*$")

# Fields a hand-maintained cache overrides, or that describe a file rather than the map: a WotR
# map turns `isMultiplayer` off whatever its player count, a variant borrows the base map's
# labels, and a mod checked out again carries fresh timestamps.
_OVERRIDDEN = {"mapsymbol", "ismultiplayer", "displayname", "description"}
_FILE_BOUND = {"filecrc", "timestamplo", "timestamphi"}


def _key_path(key: str) -> Path:
    """The map a cache key stands for, as a path relative to the mod folder."""
    decoded = re.sub(r"_([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), key)
    return Path(*decoded.split("\\"))


def _blocks(text: str):
    """Every `MapCache` block of a cache file, as `(key, [(field, value), ...])`."""
    found, key, rows = [], None, []
    for raw in text.splitlines():
        line = raw.split(";", 1)[0]
        opener = _ENTRY.match(line)
        if opener:
            key, rows = opener.group(1), []
        elif key is None:
            continue
        elif _END.match(line):
            found.append((key, rows))
            key = None
        elif field := _FIELD.match(line):
            rows.append((field.group(1), field.group(2)))
    return found


def _caches() -> list[Path]:
    """Each corpus root's own `mapcache.ini`. A root naming a mod's `data/ini` means the mod."""
    caches = []
    for root in corpus_roots().values():
        mod = root.parent.parent if root.name.lower() == "ini" else root
        cache = mod / "maps" / "mapcache.ini"
        if cache.is_file():
            caches.append(cache)
    return caches


@pytest.mark.full
@pytest.mark.parametrize("cache", _caches(), ids=lambda path: path.parents[1].name)
def test_corpus_entries_regenerate(cache: Path):
    """Regenerate the entry for every corpus map whose file still matches what the cache says,
    and check every field the map itself decides.

    `fileCRC` and the timestamps are left out: a map edited since the entry was written can come
    back to the same size, and a mod checked out again carries fresh timestamps either way, so
    neither can be told from a wrong answer here. Both are covered by the unit tests above.
    """
    mod = cache.parents[1]
    checked = 0
    for key, rows in _blocks(cache.read_bytes().decode("latin-1")):
        stored = {name.lower(): value for name, value in rows}
        path = mod / _key_path(key)
        if not path.is_file() or str(path.stat().st_size) != stored.get("filesize"):
            continue
        checked += 1
        entry = build_entry(parse_map_from_path(str(path)), path)
        generated = dict(entry.rows())
        # Compared without case: a hand-written key spells its hex either way, and which one the
        # engine itself writes is what the unit test above pins.
        assert entry.key.lower() == key.lower()
        for name, value in rows:
            lowered = name.lower()
            if lowered in _OVERRIDDEN or lowered in _FILE_BOUND or lowered == "supplyposition":
                continue
            # A cache that names the camera waypoint a map does not place writes it as the origin;
            # leaving the field out says the same thing.
            if name == "InitialCameraPosition" and value == "X:0.00 Y:0.00 Z:0.00":
                assert entry.initial_camera is None
                continue
            assert generated.get(name) == value, f"{path.name}: {name}"
    if not checked:
        pytest.skip(f"no map under {mod} still matches its cache entry")
