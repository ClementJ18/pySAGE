"""Typed decoders for the save chunks Phase 2 understands, built on `sage_save.xfer`.

Decoded so far: `CHUNK_GameState` (the browser header), `CHUNK_GameStateMap` (map paths +
the embedded `.map`), `CHUNK_Campaign` (empty in a skirmish save; in a campaign save the
current campaign/mission plus the persistent-hero carry-over roster), and `CHUNK_GameLogic`
down to the object level — its template table and the per-object index (template id,
object id, and body byte-range) that names every live object on the map (empty in a
between-missions save, which carries no live objects). Object *bodies* (each behavior
module's `xfer`) stay opaque, as does the deep per-player/script state of the other chunks.
Layouts were reversed against real BFME2 skirmish and campaign saves; single-sample regions
whose meaning is unresolved are kept as raw bytes so nothing is silently lost.

Every registered chunk also has an exact-inverse encoder — `encode(decode(payload)) == payload`
across the corpus — so edited values can be written back (see `sage_save.edit`). That includes
`CHUNK_GameLogic` and `CHUNK_GameClient`, whose module bodies stay opaque but round-trip
verbatim: each object/drawable's `KOLB` end-offset is recomputed from its stored body offset, so
the index reassembles losslessly without decoding a single module's `xfer`.
"""

import io
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sage_save.reversing import NestedBlock, nested_block_tree
from sage_save.save import BLOCK_MARKER, Chunk, SaveFile
from sage_save.xfer import XferReader
from sage_utils.stream import BinaryStream


def _read_systemtime(reader: XferReader) -> datetime | None:
    """The Win32 ``SYSTEMTIME`` the engine writes: year, month, day, dayOfWeek, hour,
    minute, second, milliseconds — eight uint16s. Returns None if the fields are not a
    valid date (defensive; the raw values are otherwise lost)."""
    year, month, day, _weekday, hour, minute, second, millis = (reader.uint16() for _ in range(8))
    try:
        return datetime(year, month, day, hour, minute, second, millis * 1000)
    except ValueError:
        return None


def _write_systemtime(stream: BinaryStream, when: datetime) -> None:
    """Inverse of `_read_systemtime`: the eight `SYSTEMTIME` uint16s. `wDayOfWeek` is
    0=Sunday..6=Saturday (Python's `isoweekday()` is 1=Monday..7=Sunday, so `% 7` maps it)."""
    fields = (
        when.year,
        when.month,
        when.day,
        when.isoweekday() % 7,
        when.hour,
        when.minute,
        when.second,
        when.microsecond // 1000,
    )
    for value in fields:
        stream.writeUInt16(value)


def _write_unicode(stream: BinaryStream, text: str) -> None:
    """A save `xferUnicodeString`: uint8 character count then that many UTF-16LE units."""
    stream.writeUChar(len(text))
    stream.writeBytes(text.encode("utf-16-le"))


@dataclass
class GameStateHeader:
    """`CHUNK_GameState` — the save-browser header (BFME2, version 1).

    The tail carries **two** unicode strings, not one: a `hero_name` before the profile
    `user_name`. It is empty in an ordinary skirmish/campaign save, but holds the display name of
    the hero the player brought into the game — a create-a-hero in skirmish (e.g. "Berethor"), or
    the created War-of-the-Ring hero in a WotR save ("The Hidden One"). It was invisible until a
    create-a-hero fixture populated it: with the string empty, its `0x00` length byte read as part
    of the constant region after the map name, so the layout looked like a single trailing name."""

    version: int
    description: str  # user-entered save name
    saved_at: datetime | None  # local time the save was written
    map_name: str  # portable path of the map the save was made on
    hero_name: str  # display name of the brought-in hero (create-a-hero / WotR hero); "" if none
    user_name: str  # the player profile that saved
    # Three regions whose meaning is unresolved but which round-trip verbatim: a save-type/flags
    # field near the Generals `saveFileType` (`leading`), a u32 after the map name that is 0 in
    # skirmish and 1 in campaign (`post_map`), and the WotR living-world state after the profile
    # name (`trailing`, empty in a skirmish/campaign save).
    leading: bytes
    post_map: bytes
    trailing: bytes


def decode_game_state(chunk: Chunk) -> GameStateHeader:
    reader = XferReader(chunk.payload)
    version = reader.version(1)
    leading = reader.bytes(6)
    saved_at = _read_systemtime(reader)
    description = reader.unicode_string()
    map_name = reader.ascii_string()
    post_map = reader.bytes(4)
    hero_name = reader.unicode_string()
    user_name = reader.unicode_string()
    trailing = reader.rest()
    return GameStateHeader(
        version, description, saved_at, map_name, hero_name, user_name, leading, post_map, trailing
    )


def encode_game_state(header: GameStateHeader) -> bytes:
    """Inverse of `decode_game_state`; `encode_game_state(decode_game_state(c)) == c.payload`.
    `saved_at` must be set (only a corrupt date decodes to None, which cannot be re-encoded)."""
    if header.saved_at is None:
        raise ValueError("cannot encode a GameState whose saved_at failed to decode")
    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(header.version)
    stream.writeBytes(header.leading)
    _write_systemtime(stream, header.saved_at)
    _write_unicode(stream, header.description)
    stream.writeString(header.map_name)
    stream.writeBytes(header.post_map)
    _write_unicode(stream, header.hero_name)
    _write_unicode(stream, header.user_name)
    stream.writeBytes(header.trailing)
    return stream.getvalue()


@dataclass
class GameStateMap:
    """`CHUNK_GameStateMap` — map paths plus the embedded `.map` file (BFME2, version 2).

    A between-missions (mission) save writes only a **stub**: it carries no scratch-map name and
    no embedded map (the next mission boots a fresh map), so `map_data` is empty, `game_mode` is
    -1, and the whole post-version remainder is kept in `trailing`. `has_map` distinguishes it."""

    version: int
    save_map_name: str  # portable "save\<leaf>.map" scratch path ("" in a mission stub)
    pristine_map_name: str  # portable path of the original map ("" in a mission stub)
    game_mode: int  # GameMode enum: 0 single-player, 2 skirmish (-1 in a mission stub)
    map_data: bytes  # the embedded map, byte-for-byte an on-disk `.map` (EAR/RefPack); "" in a stub
    trailing: bytes  # id counters + (skirmish) slot info, left undecoded

    @property
    def has_map(self) -> bool:
        """Whether this chunk actually carries an embedded map (false for a mission stub)."""
        return bool(self.map_data)


def decode_game_state_map(chunk: Chunk) -> GameStateMap:
    reader = XferReader(chunk.payload)
    version = reader.version(2)
    if BLOCK_MARKER not in chunk.payload:
        # Mission-save stub: no embedded map block. Its shorter field layout differs from a full
        # save's, so keep everything past the version opaque rather than mis-parse it by position.
        return GameStateMap(version, "", "", -1, b"", reader.rest())
    save_map_name = reader.ascii_string()
    pristine_map_name = reader.ascii_string()
    game_mode = reader.int32()
    reader.int32()  # block tag preceding the nested map block (observed 3)

    reader.nested_block()  # the map block's absolute end-offset (unused; sizes follow)
    size = reader.uint32()
    reader.uint32()  # a second copy of the size (compressed vs. stored; equal here)
    map_data = reader.bytes(size)
    trailing = reader.rest()
    return GameStateMap(version, save_map_name, pristine_map_name, game_mode, map_data, trailing)


def encode_game_state_map(gsm: GameStateMap, original_payload: bytes) -> bytes:
    """Re-encode `CHUNK_GameStateMap` with edited map paths / game mode, keeping the embedded
    map block and everything after it verbatim from `original_payload`. The nested map block
    stores an *absolute* file offset, so it is copied byte-for-byte rather than rebuilt — an
    edit that changes the prefix length would move it and invalidate that offset, which the
    caller (`apply_json`) guards against by requiring the payload length to be unchanged."""
    if BLOCK_MARKER not in original_payload:
        return original_payload  # mission stub: nothing decoded to re-encode
    reader = XferReader(original_payload)
    reader.version(2)
    reader.ascii_string()
    reader.ascii_string()
    reader.int32()
    block_tag = reader.int32()
    tail = original_payload[reader.tell() :]  # KOLB map block + id counters + slot info

    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(gsm.version)
    stream.writeString(gsm.save_map_name)
    stream.writeString(gsm.pristine_map_name)
    stream.writeInt32(gsm.game_mode)
    stream.writeInt32(block_tag)
    stream.writeBytes(tail)
    return stream.getvalue()


@dataclass
class TacticalView:
    """`CHUNK_TacticalView` — the camera (BFME2 version 3).

    Its leading fields are exactly the GPL `View::xfer` (`GameClient/View.cpp`): the camera
    `angle` and the look-at `position` (a `Coord3D`). Those match the BFME2 bytes — confirmed
    across the corpus (the position moves between saves as the camera pans) — even though BFME2
    bumped the chunk to version 3 and appended ~130 bytes of version-2/3 camera state (zoom,
    pitch, animation) that its (non-public) `View::xfer` overrides add. Those trailing bytes are
    kept opaque; `angle` and `position` decode and round-trip exactly, so the camera is editable
    (all three coordinates and the angle are length-preserving float edits)."""

    version: int
    angle: float  # camera rotation, radians
    position: tuple[float, float, float]  # camera look-at point (x, y, z)
    trailing: bytes  # BFME2 version-2/3 camera additions, left opaque


def decode_tactical_view(chunk: Chunk) -> TacticalView:
    reader = XferReader(chunk.payload)
    version = reader.version(3)
    angle = reader.real()
    position = (reader.real(), reader.real(), reader.real())
    return TacticalView(version, angle, position, reader.rest())


def encode_tactical_view(view: TacticalView) -> bytes:
    """Inverse of `decode_tactical_view`; `encode_tactical_view(decode_tactical_view(c)) ==
    c.payload`. The opaque BFME2 camera tail is written back verbatim."""
    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(view.version)
    stream.writeFloat(view.angle)
    for coordinate in view.position:
        stream.writeFloat(coordinate)
    stream.writeBytes(view.trailing)
    return stream.getvalue()


@dataclass
class TeamFactory:
    """`CHUNK_TeamFactory` — the team prototypes (BFME2 version 3).

    Only the header is decoded: the GPL `TeamFactory::xfer` writes a unique-team-ID counter then a
    `uint16` prototype count, and BFME2 matches that. Each prototype body also *starts* like ZH's
    `TeamPrototype::xfer` (version 2, `owningPlayerIndex`, `attackPriorityName`) — so the
    team→player attribution is right there — but the embedded `TeamTemplateInfo` is **BFME2 version
    3** where ZH is version 1, with extra fields whose layout is not public. That extra data throws
    off the following `teamInstanceCount`, so the per-prototype walk can't be completed and the
    prototype block is kept opaque in `body`. Reversing BFME2's `TeamTemplateInfo` v3 (the corpus
    has ~111 prototypes per save to constrain it) would unlock the full attribution."""

    version: int
    unique_team_id: int  # the factory's next-team-ID counter
    prototype_count: int  # number of team prototypes (teams defined on the map)
    body: bytes  # the prototype records, opaque (walk blocked at BFME2 TeamTemplateInfo v3)


def decode_team_factory(chunk: Chunk) -> TeamFactory:
    reader = XferReader(chunk.payload)
    version = reader.version(3)
    unique_team_id = reader.uint32()
    prototype_count = reader.uint16()
    return TeamFactory(version, unique_team_id, prototype_count, reader.rest())


def encode_team_factory(factory: TeamFactory) -> bytes:
    """Inverse of `decode_team_factory`; the opaque prototype block is written back verbatim."""
    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(factory.version)
    stream.writeUInt32(factory.unique_team_id)
    stream.writeUInt16(factory.prototype_count)
    stream.writeBytes(factory.body)
    return stream.getvalue()


_HERO_NAME_CHARS = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


@dataclass
class CampaignHero:
    """One persistent hero in the campaign carry-over roster (inside `CHUNK_Campaign`): the ini
    `Object` template that is recreated on the next mission, its accumulated experience/rank and
    health, and the ini `Upgrade` names it has earned. The template and every upgrade name are
    ini cross-references the roster restores by name."""

    name: str  # ini Object template
    experience: float
    rank: int
    health: int
    upgrades: list[str]  # ini Upgrade names earned by this hero


@dataclass
class Campaign:
    """`CHUNK_Campaign` — the campaign manager (BFME2, version 1).

    A skirmish save has no active campaign (`active` is false) and the chunk is just the version
    byte plus that flag. A campaign save carries the current campaign/mission and a persistent-
    **hero carry-over roster** — the heroes (with earned experience and upgrades) that survive
    between missions — inside a nested `KOLB` block kept here as `roster` (opaque for an exact
    round-trip; `heroes` is the decoded view harvested from it).

    `mission_number` is the 1-based mission index, read from the roster block preamble (`u8 6 +
    u32 0-based counter`); it correctly tracks progress across the corpus (mission-1 saves,
    between-mission autosaves for missions 2/3, and mid-mission-2 full saves). The `int32` the
    engine writes right after the campaign name — decoded as `campaign_flag` — is a constant `1`
    across all 20 campaign fixtures (both campaigns, all three missions); its meaning is
    unresolved (plausibly the difficulty, but the corpus has no hard-difficulty save to confirm),
    so it is kept verbatim rather than guessed."""

    version: int
    active: bool  # false in a skirmish save (no campaign); true in a campaign save
    current_campaign: str  # ini Campaign name (e.g. "EVIL_CAMPAIGN"), empty when inactive
    campaign_flag: int  # the int32 after the name; 1 across the corpus, unresolved (-1 inactive)
    mission_number: int  # 1-based mission index from the roster preamble (-1 when inactive)
    heroes: list["CampaignHero"]  # the carry-over roster, harvested from `roster`
    roster: bytes  # the raw nested roster block (KOLB marker onward), verbatim; empty when inactive


def _try_read_hero(data: bytes, offset: int) -> tuple[CampaignHero, int] | None:
    """Try to parse one hero record at `data[offset]`; return `(hero, end_offset)` or None.

    A record is self-delimiting: an `exists` byte (1), the ascii template name, an int (1), the
    experience f32, a rank byte, three ints (a built flag and current/max health), four flag
    bytes, a `uint16` upgrade count, that many ascii `Upgrade_*` names, then a trailing int. The
    field widths were validated by exact byte-consumption of a full 7-hero roster; the shape (a
    valid name immediately followed by the constant `int 1`) is specific enough to locate records
    inside the block without reversing the surrounding per-player group framing."""
    n = len(data)
    if offset >= n or data[offset] != 1:  # exists flag
        return None
    if offset + 1 >= n:
        return None
    name_len = data[offset + 1]
    name_end = offset + 2 + name_len
    if not (3 <= name_len <= 40) or name_end + 4 > n:
        return None
    name_bytes = data[offset + 2 : name_end]
    if not all(byte in _HERO_NAME_CHARS for byte in name_bytes):
        return None
    reader = XferReader(data)
    reader.skip(name_end)
    if reader.int32() != 1:  # the constant that anchors the record shape
        return None
    if reader.remaining() < 23:  # the fixed middle: f32 + u8 + 3×i32 + 4 flags + u16 count
        return None
    experience = reader.real()
    rank = reader.ubyte()
    if rank > 20:  # heroes cap around rank 10; guards against a false match
        return None
    reader.int32()  # built flag
    health = reader.int32()
    reader.int32()  # max health (equal to health in the sample)
    reader.bytes(4)  # four flag bytes
    upgrade_count = reader.uint16()
    if upgrade_count > 40:
        return None
    upgrades: list[str] = []
    for _ in range(upgrade_count):
        if reader.eof():
            return None
        length = reader.ubyte()
        if not (1 <= length <= 64) or reader.remaining() < length:
            return None
        raw = reader.bytes(length)
        if not all(byte in _HERO_NAME_CHARS for byte in raw):
            return None
        upgrades.append(raw.decode("ascii"))
    if reader.remaining() < 4:
        return None
    reader.int32()  # trailing status
    hero = CampaignHero(name_bytes.decode("ascii"), experience, rank, health, upgrades)
    return hero, reader.tell()


def _harvest_campaign_heroes(roster: bytes) -> list[CampaignHero]:
    """Every hero record in the roster block, found by the record signature. The surrounding
    per-player group framing (which splits the roster differently as the campaign progresses) is
    not reversed, so records are located by scan rather than a structured walk — the same
    signature-harvest strategy `sage_save.players` uses for the fatal `CHUNK_Players` names."""
    heroes: list[CampaignHero] = []
    offset = 0
    while offset < len(roster):
        result = _try_read_hero(roster, offset)
        if result is None:
            offset += 1
        else:
            hero, offset = result
            heroes.append(hero)
    return heroes


def _roster_mission_number(roster: bytes) -> int:
    """The 1-based mission index from the roster block preamble, or -1 if unreadable. The block
    is `KOLB(4) + u32 end-offset(4) + u8 (=6) + u32 mission (0-based) + …`, so the counter sits
    at roster byte 9; observed 0/1/2 across the corpus, tracking mission 1/2/3."""
    if len(roster) < 13 or roster[:4] != BLOCK_MARKER:
        return -1
    return struct.unpack_from("<I", roster, 9)[0] + 1


def decode_campaign(chunk: Chunk) -> Campaign:
    reader = XferReader(chunk.payload)
    version = reader.version(1)
    active = reader.bool()
    if not active:  # skirmish save: no campaign, nothing more in the chunk
        return Campaign(version, False, "", -1, -1, [], b"")
    current_campaign = reader.ascii_string()
    campaign_flag = reader.int32()
    roster = reader.rest()  # the nested KOLB roster block, kept verbatim
    heroes = _harvest_campaign_heroes(roster)
    mission_number = _roster_mission_number(roster)
    return Campaign(version, True, current_campaign, campaign_flag, mission_number, heroes, roster)


def encode_campaign(campaign: Campaign) -> bytes:
    """Inverse of `decode_campaign`; `encode_campaign(decode_campaign(c)) == c.payload`. The
    roster block is written back verbatim (its nested offsets are absolute, so it is never
    rebuilt), so only the campaign name / flag can be edited, and only length-preservingly.
    `mission_number` lives inside the opaque roster and is not re-encoded from the field."""
    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(campaign.version)
    stream.writeUChar(1 if campaign.active else 0)
    if campaign.active:
        stream.writeString(campaign.current_campaign)
        stream.writeInt32(campaign.campaign_flag)
        stream.writeBytes(campaign.roster)
    return stream.getvalue()


@dataclass
class SaveObject:
    """One live `Object` in `CHUNK_GameLogic`: its template (resolved through the chunk's
    template table), its runtime object id, and its `Object::xfer` body. The body stays opaque,
    but `object_modules` walks its `ModuleTag_*` nested-block structure — hence `body_offset`, the
    body's absolute file position, needed to resolve the blocks' absolute end-offsets."""

    template_id: int
    object_id: int
    template_name: str
    body: bytes
    body_offset: int  # absolute file offset of body[0], for `object_modules`


@dataclass
class ObjectPrefix:
    """The decoded head of an object's `Object::xfer` scalar prefix (the bytes between the
    body start and the first `ModuleTag_*` block): a version byte (26 for every one of the
    9,320 objects across the corpus), an ascii echo of the object's template name, a u32 echo
    of its object id, and the 12-float row-major 3x4 transform — rotation columns plus the
    world position. Both echoes are validated against the object index, which makes a
    mis-aligned read structurally impossible. The scalars after the matrix (status flags,
    veterancy, health module state, ...) remain undecoded in the prefix remainder."""

    version: int  # observed 26 corpus-wide
    template_name: str  # ascii echo of the TOC template
    object_id: int  # u32 echo of the object's runtime id
    matrix: tuple[float, ...]  # 12 f32: rows of the 3x4 transform, position in column 3

    @property
    def position(self) -> tuple[float, float, float]:
        """The object's world position (x, y, z) — the transform's translation column."""
        return (self.matrix[3], self.matrix[7], self.matrix[11])


def decode_object_prefix(obj: SaveObject) -> ObjectPrefix:
    """Decode the `Object::xfer` prefix head from an object's body, validating the template
    and id echoes. Raises `ValueError` if either echo mismatches (never observed)."""
    reader = XferReader(obj.body)
    version = reader.ubyte()
    name = reader.ascii_string()
    object_id = reader.uint32()
    if name != obj.template_name or object_id != obj.object_id:
        raise ValueError(
            f"object prefix echoes ({name!r}, {object_id}) do not match the index entry "
            f"({obj.template_name!r}, {obj.object_id})"
        )
    matrix = tuple(reader.real() for _ in range(12))
    return ObjectPrefix(version, name, object_id, matrix)


def _object_matrix_offset(obj: SaveObject) -> int:
    """Byte offset of the 12-float transform inside an object body: past the version byte, the
    length-prefixed template name, and the object-id u32."""
    return 1 + 1 + len(obj.template_name) + 4


_OBJECT_LEVEL_RE = re.compile(rb"Upgrade_ObjectLevel(\d+)")


def object_veterancy_level(obj: SaveObject) -> int:
    """The object's experience/veterancy level, read from its applied upgrade mask.

    BFME2 implements veterancy as `Upgrade_ObjectLevelN` upgrades granted at each rank: a level-N
    unit carries `Upgrade_ObjectLevel1..N` (the object prefix's applied-upgrade mask lists them,
    and the parallel `GoodLevelN` experience block names the current rank). This reads the level
    name-based — the highest `N` present — so it needs no offset walk into the variable prefix; an
    object that carries no such upgrade (a prop, most structures) returns 0. Pinned by the
    "unit full" → "unit vet" delta: a DwarvenGuardian horde and its members go 1 → 2 when the
    horde ranks up, gaining `Upgrade_ObjectLevel2`. The health counterpart lives inside the
    `ActiveBody` body module (`ModuleTag_03`), not this scalar prefix, and is not decoded yet."""
    levels = [int(match.group(1)) for match in _OBJECT_LEVEL_RE.finditer(obj.body)]
    return max(levels) if levels else 0


def set_object_position(obj: SaveObject, position: tuple[float, float, float]) -> SaveObject:
    """Return a copy of `obj` with the transform's translation column (world x, y, z) rewritten
    in place — a length-preserving edit (three f32 overwrites), so it satisfies the absolute-
    offset constraint and flows through `encode_game_logic`. The rotation columns are untouched.
    Validates the prefix echoes first (via `decode_object_prefix`) so a mis-indexed object can't
    be silently corrupted."""
    decode_object_prefix(obj)  # echo validation; raises on a mis-aligned body
    matrix_start = _object_matrix_offset(obj)
    body = bytearray(obj.body)
    for column, value in zip((3, 7, 11), position, strict=True):
        struct.pack_into("<f", body, matrix_start + column * 4, float(value))
    return SaveObject(
        obj.template_id, obj.object_id, obj.template_name, bytes(body), obj.body_offset
    )


def object_modules(obj: SaveObject) -> list[NestedBlock]:
    """The behavior-module blocks inside an object's `Object::xfer` body — each `ModuleTag_*`
    (occasionally unnamed) `KOLB` block, with its name, byte range and nesting depth. This is a
    structural x-ray of the object (the same self-delimiting block framing the container uses),
    obtained *without* decoding any module's `xfer`; the scalar `Object::xfer` prefix (team,
    transform, health, …) that precedes the first module is simply skipped by the block scan.
    Validated across the corpus to yield only clean module-tag names. It is the raw material for
    the Step 6 kind-of / command-button harvest (scan a named module's bytes for those names)."""
    return nested_block_tree(obj.body, obj.body_offset)


@dataclass
class GameLogicState:
    """`CHUNK_GameLogic` — the logic frame, the object template table, and the object index
    (BFME2, version 8). Object bodies and the surrounding scalar preamble/trailing are kept
    opaque, but reassemble losslessly (see `encode_game_logic`)."""

    version: int
    frame: int
    templates: dict[int, str]  # template id -> ini Object name
    objects: list[SaveObject]
    preamble: bytes  # opaque bytes between the frame and the template table
    trailing: bytes  # opaque bytes after the last object (managers, triggers, timers)


# How far into a `CHUNK_GameLogic` payload the object template table can begin — past the
# BFME2 scalar preamble. A real save's table sits within the first couple of KB; a payload
# smaller than this with no locatable table has been scanned in full (an objectless mission save).
_TEMPLATE_SEARCH_LIMIT = 0x4000


# Validates that the bytes immediately after a candidate template table are the start of a
# well-formed instance index — the strong signal that separates the real table from a coincidental
# name run. `payload[pos:]` begins right after the last table entry; `count` is the table size.
_IndexValidator = Callable[[bytes, int, int], bool]


def _game_logic_index_follows(payload: bytes, pos: int, count: int) -> bool:
    """`CHUNK_GameLogic` object index: `u32 objectCount` then each object `u16 tocId + u32 objId +
    KOLB`. Require at least one object whose tocId is a real table id and whose block opens with the
    `KOLB` marker — a lone `Command_*` / ini string that happens to carry id=1 has no such index."""
    if pos + 4 > len(payload):
        return False
    object_count = struct.unpack_from("<I", payload, pos)[0]
    if not (1 <= object_count <= 200_000):
        return False
    first = pos + 4
    if first + 10 > len(payload):
        return False
    toc_id = struct.unpack_from("<H", payload, first)[0]
    return 1 <= toc_id <= count and payload[first + 6 : first + 10] == BLOCK_MARKER


def _game_client_index_follows(payload: bytes, pos: int, count: int) -> bool:
    """`CHUNK_GameClient` drawable index: `u16 drawableCount` then each drawable `u16 tocId + KOLB`
    (the attached object id lives inside the block, not in the index)."""
    if pos + 2 > len(payload):
        return False
    drawable_count = struct.unpack_from("<H", payload, pos)[0]
    if not (1 <= drawable_count <= 200_000):
        return False
    first = pos + 2
    if first + 6 > len(payload):
        return False
    toc_id = struct.unpack_from("<H", payload, first)[0]
    return 1 <= toc_id <= count and payload[first + 2 : first + 6] == BLOCK_MARKER


def _locate_template_table(
    payload: bytes,
    index_follows: _IndexValidator,
    search_limit: int = _TEMPLATE_SEARCH_LIMIT,
) -> int:
    """Return the offset of the object/drawable template table's count field.

    The table is `uint32 count` then `count × (name + uint16 id)` with ids running
    1..count. BFME2 precedes it with a scalar preamble that a single sample cannot pin down
    deterministically, so the table is found by its own shape: the first offset carrying a
    plausible count whose entries all parse as names with sequential ids *and* that is followed
    by a well-formed instance index (`index_follows`).

    Template names are engine ini identifiers written as a length byte + raw bytes — *not*
    guaranteed 7-bit ASCII: a localized mod embeds its native encoding (the Edain WotR corpus
    names objects with Latin-1 umlauts, e.g. `ArnorPalantirwächterHorde` carrying 0xE4). So a
    name byte is anything printable-or-high (>= 0x20, excluding DEL); rejecting the high range
    would break the shape match mid-table on the first umlaut name and slide the scan onto a
    later false match.

    The `index_follows` check is what rejects a *short* coincidental match: a WotR living-world
    save embeds strings like `Command_CreateAHero_...` in the GameLogic preamble, and a lone such
    string preceded by `u32 1` and trailed by `u16 1` satisfies the bare name/id shape. Requiring
    a real object/drawable index after the table discards it, so the scan reaches the true table
    (in a battle save) or correctly finds none (in an objectless living-world save).
    """
    limit = min(search_limit, len(payload) - 4)
    for offset in range(5, limit):  # past the version byte + uint32 frame
        count = struct.unpack_from("<I", payload, offset)[0]
        if not (1 <= count <= 5000):
            continue
        pos = offset + 4
        ok = True
        for expected_id in range(1, count + 1):
            if pos >= len(payload):
                ok = False
                break
            length = payload[pos]
            end = pos + 1 + length
            if length == 0 or end + 2 > len(payload):
                ok = False
                break
            if not all(b >= 32 and b != 127 for b in payload[pos + 1 : end]):
                ok = False
                break
            if struct.unpack_from("<H", payload, end)[0] != expected_id:
                ok = False
                break
            pos = end + 2
        if ok and index_follows(payload, pos, count):
            return offset
    raise ValueError("could not locate the object/drawable template table")


def _read_template_table(
    reader: XferReader, payload: bytes, index_follows: _IndexValidator
) -> tuple[bytes, dict[int, str]]:
    """Skip the scalar preamble to the object/drawable template TOC and read it: `u32 count +
    count × (ascii name + u16 id)`. Returns `(preamble, {id: name})`. Shared by `CHUNK_GameLogic`
    (v8) and `CHUNK_GameClient` (v4), which write the same TOC shape but different instance indexes
    (`index_follows` supplies the per-chunk index check). Raises `ValueError` (from the locator) if
    there is no table."""
    table_offset = _locate_template_table(payload, index_follows)
    preamble = reader.bytes(table_offset - reader.tell())
    count = reader.uint32()
    templates: dict[int, str] = {}
    for _ in range(count):
        name = reader.ascii_string()
        templates[reader.uint16()] = name
    return preamble, templates


def decode_game_logic(chunk: Chunk) -> GameLogicState:
    reader = XferReader(chunk.payload, base_offset=chunk.payload_offset)
    version = reader.version(8)
    frame = reader.uint32()

    try:
        preamble, templates = _read_template_table(reader, chunk.payload, _game_logic_index_follows)
    except ValueError:
        # A mission / between-missions save has no live objects: its `CHUNK_GameLogic` is a
        # tiny frame + opaque tail with no template table (the next mission hasn't started).
        # Distinguish that from a corrupt large payload — where a missing table is a real
        # failure — by size: the objectless variant is well under the table search window, so
        # a table-less payload that small has been scanned end to end and legitimately has none.
        if len(chunk.payload) <= _TEMPLATE_SEARCH_LIMIT:
            return GameLogicState(version, frame, {}, [], b"", reader.rest())
        raise

    object_count = reader.uint32()
    objects: list[SaveObject] = []
    for _ in range(object_count):
        template_id = reader.uint16()
        object_id = reader.uint32()
        end = reader.nested_block()
        body_offset = chunk.payload_offset + reader.tell()
        body = reader.bytes(end - reader.tell())
        name = templates.get(template_id, f"<unknown template {template_id}>")
        objects.append(SaveObject(template_id, object_id, name, body, body_offset))

    return GameLogicState(version, frame, templates, objects, preamble, reader.rest())


def _write_template_table(stream: BinaryStream, templates: dict[int, str]) -> None:
    """Write the object/drawable template TOC: `u32 count + count × (ascii name + u16 id)`, in
    the dict's insertion order (which is file order — the decode inserts by id 1..count)."""
    stream.writeUInt32(len(templates))
    for template_id, name in templates.items():
        stream.writeString(name)
        stream.writeUInt16(template_id)


def encode_game_logic(state: GameLogicState) -> bytes:
    """Inverse of `decode_game_logic`; `encode_game_logic(decode_game_logic(c)) == c.payload`
    across the corpus. Object bodies are opaque but written back verbatim, and each `KOLB`
    header's absolute end-offset is recomputed from the object's stored `body_offset`
    (`body_offset + len(body)`), so no separately-stored offset is needed. The objectless
    mission-save case (empty templates + objects) writes just version + frame + trailing."""
    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(state.version)
    stream.writeUInt32(state.frame)
    stream.writeBytes(state.preamble)
    if state.templates or state.objects:
        _write_template_table(stream, state.templates)
        stream.writeUInt32(len(state.objects))
        for obj in state.objects:
            stream.writeUInt16(obj.template_id)
            stream.writeUInt32(obj.object_id)
            stream.writeBytes(BLOCK_MARKER)
            stream.writeUInt32(obj.body_offset + len(obj.body))
            stream.writeBytes(obj.body)
    stream.writeBytes(state.trailing)
    return stream.getvalue()


@dataclass
class SaveDrawable:
    """One drawable in `CHUNK_GameClient`: its drawable template (resolved through the chunk's
    TOC), the `CHUNK_GameLogic` object it renders (`object_id`, `0xFFFFFFFF`/-1 when unattached),
    and its opaque `Drawable::xfer` body. `object_id` is read from the first 4 bytes of the block;
    the rest of the body (draw modules) stays opaque."""

    template_id: int
    template_name: str
    object_id: int
    body: bytes
    body_offset: int  # absolute file offset of body[0], for a module walk (as `object_modules`)


@dataclass
class GameClientState:
    """`CHUNK_GameClient` — the client-side mirror of `CHUNK_GameLogic` (BFME2, version 4): a
    render frame, the drawable template TOC, and the drawable index (one drawable per live object).
    Drawable bodies and the trailing client state (`InGameUI`-adjacent) are kept opaque, but
    reassemble losslessly (see `encode_game_client`)."""

    version: int
    frame: int
    templates: dict[int, str]  # toc id -> ini drawable/Object template name
    drawables: list[SaveDrawable]
    preamble: bytes
    trailing: bytes


def decode_game_client(chunk: Chunk) -> GameClientState:
    reader = XferReader(chunk.payload, base_offset=chunk.payload_offset)
    version = reader.version(4)
    frame = reader.uint32()

    try:
        preamble, templates = _read_template_table(
            reader, chunk.payload, _game_client_index_follows
        )
    except ValueError:
        # Objectless save (a between-missions stub, or a WotR strategic-layer save that captured
        # no battle world): no drawables mirror the empty `CHUNK_GameLogic`, so there is no
        # template table. Same size guard as `decode_game_logic` — a small table-less payload has
        # been scanned in full and legitimately has none; a large one is a real failure, re-raised.
        if len(chunk.payload) <= _TEMPLATE_SEARCH_LIMIT:
            return GameClientState(version, frame, {}, [], b"", reader.rest())
        raise

    # drawable count is a uint16 (not the uint32 GameLogic uses), and each drawable is
    # `u16 tocId + KOLB block`, the block opening with the u32 objectID the drawable is attached to.
    drawable_count = reader.uint16()
    drawables: list[SaveDrawable] = []
    for _ in range(drawable_count):
        template_id = reader.uint16()
        end = reader.nested_block()
        body_offset = chunk.payload_offset + reader.tell()
        body = reader.bytes(end - reader.tell())
        object_id = struct.unpack_from("<I", body, 0)[0] if len(body) >= 4 else 0
        name = templates.get(template_id, f"<unknown template {template_id}>")
        drawables.append(SaveDrawable(template_id, name, object_id, body, body_offset))

    return GameClientState(version, frame, templates, drawables, preamble, reader.rest())


def encode_game_client(state: GameClientState) -> bytes:
    """Inverse of `decode_game_client`; `encode_game_client(decode_game_client(c)) == c.payload`
    across the corpus. Like `encode_game_logic`: drawable bodies are opaque but written verbatim,
    and each `KOLB` end-offset is recomputed from the drawable's `body_offset`. The drawable count
    is a `u16` (not the `u32` GameLogic uses). The objectless case (a living-world / mission save
    whose GameClient has no drawable table) writes just version + frame + trailing, mirroring
    `encode_game_logic`."""
    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(state.version)
    stream.writeUInt32(state.frame)
    stream.writeBytes(state.preamble)
    if state.templates or state.drawables:
        _write_template_table(stream, state.templates)
        stream.writeUInt16(len(state.drawables))
        for drawable in state.drawables:
            stream.writeUInt16(drawable.template_id)
            stream.writeBytes(BLOCK_MARKER)
            stream.writeUInt32(drawable.body_offset + len(drawable.body))
            stream.writeBytes(drawable.body)
    stream.writeBytes(state.trailing)
    return stream.getvalue()


def drawable_modules(drawable: SaveDrawable) -> list[NestedBlock]:
    """The draw-module blocks inside a drawable's `Drawable::xfer` body — each `ModuleTag_*` (or
    ini-tag-named, e.g. `DrawFloorBase`) `KOLB` block, with its name, byte range and nesting depth.
    The twin of `object_modules` on the client side: the same self-delimiting block framing walked
    without decoding any draw module's `xfer`, with the `Drawable::xfer` scalar prefix (object id,
    fade/status fields) that precedes the first module simply skipped by the block scan. Validated
    across the corpus to yield only clean identifier names (11,686 top-level blocks, no garbage)."""
    return nested_block_tree(drawable.body, drawable.body_offset)


@dataclass
class PlayerUpgrade:
    """One entry in a player's upgrade list (`Upgrade::xfer`): the ini `Upgrade` name and its
    status — 1 = in progress (researching), 2 = completed. The two upgrade *masks* on the same
    player split the identical names by that status, so list and masks cross-validate."""

    name: str
    status: int  # 1 = in progress, 2 = completed


# Every player record opens with these two bytes (plausibly the BFME2 Player::xfer version 10
# plus a sub-version). Constant across every skirmish and campaign fixture.
_PLAYER_RECORD_MAGIC = b"\x0a\x07"


@dataclass
class SavePlayer:
    """One player record in `CHUNK_Players` (BFME2 chunk version 1; records are written inline
    with no framing). The record head is `0a 07` + three u32s — two command-point-like values
    that vary per campaign mission (constant 100/0 in skirmish) and the **player index** — then
    a 16-byte scalar block, a cap-like u32 (50k–100k by lobby in skirmish, small in campaign),
    a flag byte, and `Money::xfer` (version + amount). From there the record follows the ZH v8
    order: upgrade count, preorder flag, the v8 disabled/hidden science vectors (BFME2 u32
    counts), the upgrade list, the 10-byte radar block, the in-progress/completed upgrade masks
    (u16 counts), a 6-byte energy stub, and the team-prototype id vector. Everything after the
    team ids — build list, AI player, gatherer/tunnel managers, sciences, rank block, hero
    roster, score — is kept opaque in `tail` (it round-trips verbatim; the science names inside
    it are still harvested by signature in `sage_save.players`)."""

    index: int  # the record's own player-list index (validates the walk)
    head_a: int  # u32, command-point-like; 100 in every skirmish record, varies in campaign
    head_b: int  # u32, command-point-like; 0 in skirmish, varies in campaign
    prefix: bytes  # 16 scalar bytes, unresolved
    cap: int  # u32, lobby-dependent cap (100000/87500/75000/50000 skirmish; small in campaign)
    flag: int  # u8 between cap and money (0; 1 on some campaign records)
    money: int  # the player's treasury — the HUD money value
    is_preorder: int  # ZH v>=7 u8
    sciences_disabled: list[str]  # ZH v>=8 xferScienceVec (BFME2 u32 count)
    sciences_hidden: list[str]
    upgrades: list[PlayerUpgrade]
    radar: bytes  # 10 bytes: i32 radarCount, u8 isPlayerDead, i32 disableProof, u8 radarDisabled
    upgrades_in_progress: list[str]  # xferUpgradeMask (u8 ver=1 + u16 count + names)
    upgrades_completed: list[str]
    energy: bytes  # 6 bytes (version byte + 5), the BFME2 Energy::xfer stub
    team_ids: list[int]  # u16 count + u32 TeamPrototypeIDs (joins CHUNK_TeamFactory)
    tail: bytes  # everything to the next record head (AI/build/science/rank/hero state), opaque


@dataclass
class PlayersState:
    """`CHUNK_Players` — the player list (BFME2, version 1), decoded per record down to the
    team-prototype vector with the record remainder opaque. Absent from between-missions saves."""

    version: int
    players: list[SavePlayer]


def _read_science_vec(reader: XferReader) -> list[str]:
    """BFME2 `xferScienceVec`: `u8 version=1 + u32 count + count x ascii` (ZH used u16)."""
    if reader.version(1) != 1:
        raise ValueError("science vector version != 1")
    return [reader.ascii_string() for _ in range(reader.uint32())]


def _read_upgrade_mask(reader: XferReader) -> list[str]:
    """`xferUpgradeMask`: `u8 version=1 + u16 count + count x ascii Upgrade names`."""
    if reader.version(1) != 1:
        raise ValueError("upgrade mask version != 1")
    return [reader.ascii_string() for _ in range(reader.uint16())]


def _find_player_head(payload: bytes, offset: int, expected_index: int) -> int:
    """The offset of the record head for player `expected_index` at/after `offset`. A head is
    the `0a 07` magic whose player-index u32 (10 bytes in) matches — the index field is what
    rejects chance `0a 07` pairs inside record bodies (observed once, in a campaign save)."""
    while True:
        found = payload.find(_PLAYER_RECORD_MAGIC, offset)
        if found < 0 or found + 14 > len(payload):
            raise ValueError(f"no player-record head for index {expected_index}")
        if struct.unpack_from("<I", payload, found + 10)[0] == expected_index:
            return found
        offset = found + 1


def _decode_player(reader: XferReader, expected_index: int) -> SavePlayer:
    magic = reader.bytes(2)
    if magic != _PLAYER_RECORD_MAGIC:
        raise ValueError(f"bad player record magic {magic.hex()}")
    head_a = reader.uint32()
    head_b = reader.uint32()
    index = reader.uint32()
    if index != expected_index:
        raise ValueError(f"player record index {index} != expected {expected_index}")
    prefix = reader.bytes(16)
    cap = reader.uint32()
    flag = reader.ubyte()
    if flag not in (0, 1):
        raise ValueError(f"player pre-money flag {flag}")
    if reader.version(1) != 1:
        raise ValueError("Money version != 1")
    money = reader.uint32()

    upgrade_count = reader.uint16()
    is_preorder = reader.ubyte()
    sciences_disabled = _read_science_vec(reader)
    sciences_hidden = _read_science_vec(reader)
    upgrades = []
    for _ in range(upgrade_count):
        name = reader.ascii_string()
        if reader.version(1) != 1:
            raise ValueError(f"Upgrade::xfer version != 1 for {name}")
        upgrades.append(PlayerUpgrade(name, reader.uint32()))

    radar = reader.bytes(10)
    upgrades_in_progress = _read_upgrade_mask(reader)
    upgrades_completed = _read_upgrade_mask(reader)
    energy = reader.bytes(6)
    if energy[0] != 1:
        raise ValueError(f"energy stub version {energy[0]}")
    team_ids = [reader.uint32() for _ in range(reader.uint16())]

    return SavePlayer(
        index,
        head_a,
        head_b,
        prefix,
        cap,
        flag,
        money,
        is_preorder,
        sciences_disabled,
        sciences_hidden,
        upgrades,
        radar,
        upgrades_in_progress,
        upgrades_completed,
        energy,
        team_ids,
        b"",  # tail is sliced in by decode_players (it needs the next record's offset)
    )


def decode_players(chunk: Chunk) -> PlayersState:
    payload = chunk.payload
    reader = XferReader(payload)
    version = reader.version(1)
    player_count = reader.uint32()
    players: list[SavePlayer] = []
    for i in range(player_count):
        player = _decode_player(reader, i)
        structured_end = reader.tell()
        if i + 1 < player_count:
            tail_end = _find_player_head(payload, structured_end, i + 1)
        else:
            tail_end = len(payload)
        player.tail = payload[structured_end:tail_end]
        reader.skip(tail_end - structured_end)
        players.append(player)
    return PlayersState(version, players)


def encode_players(state: PlayersState) -> bytes:
    """Inverse of `decode_players`; `encode_players(decode_players(c)) == c.payload`. `money`
    is a plain u32, so a money edit is length-preserving and qualifies for `apply_json`."""
    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(state.version)
    stream.writeUInt32(len(state.players))
    for player in state.players:
        stream.writeBytes(_PLAYER_RECORD_MAGIC)
        stream.writeUInt32(player.head_a)
        stream.writeUInt32(player.head_b)
        stream.writeUInt32(player.index)
        stream.writeBytes(player.prefix)
        stream.writeUInt32(player.cap)
        stream.writeUChar(player.flag)
        stream.writeUChar(1)
        stream.writeUInt32(player.money)

        stream.writeUInt16(len(player.upgrades))
        stream.writeUChar(player.is_preorder)
        for sciences in (player.sciences_disabled, player.sciences_hidden):
            stream.writeUChar(1)
            stream.writeUInt32(len(sciences))
            for science in sciences:
                stream.writeString(science)
        for upgrade in player.upgrades:
            stream.writeString(upgrade.name)
            stream.writeUChar(1)
            stream.writeUInt32(upgrade.status)

        stream.writeBytes(player.radar)
        for mask in (player.upgrades_in_progress, player.upgrades_completed):
            stream.writeUChar(1)
            stream.writeUInt16(len(mask))
            for name in mask:
                stream.writeString(name)
        stream.writeBytes(player.energy)
        stream.writeUInt16(len(player.team_ids))
        for team_id in player.team_ids:
            stream.writeUInt32(team_id)
        stream.writeBytes(player.tail)
    return stream.getvalue()


@dataclass
class ScriptCounter:
    """One script counter/timer in `CHUNK_ScriptEngine`. BFME2 scopes counters to a player by
    an always-present scope string — empty for a global counter, `"Player_N"` for a player-scoped
    one (the ZH record has no scope field; this is the fork's addition, and the reason the record
    layout resisted a name-based discriminator: the scope is a *second* string even when empty)."""

    scope: str  # "" = global, else "Player_N"
    name: str  # script counter name (map-author or engine ___MusicScript_* namespace)
    value: int
    is_countdown_timer: bool


@dataclass
class ScriptFlag:
    """One script flag in `CHUNK_ScriptEngine`, scoped exactly like `ScriptCounter`."""

    scope: str  # "" = global, else "Player_N"
    name: str
    value: bool


@dataclass
class AttackPriorityInfo:
    """One attack-priority set (`AttackPriorityInfo::xfer`, ZH v1 — BFME2 matches): the set
    name, the default priority, and per-template overrides (ini Object template → priority)."""

    name: str
    default_priority: int
    overrides: list[tuple[str, int]]  # (ini Object template, priority)


@dataclass
class NamedReveal:
    """One named map reveal. ZH writes `{revealName, waypointName, radius, playerName}` as four
    fields with two ascii names; BFME2 collapses the waypoint to a 4-byte key/hash."""

    key: int  # u32 waypoint key/hash (ZH wrote an ascii waypoint name here)
    name: str  # reveal name (script-authored)
    radius: float
    player: str  # e.g. "<Local Player>", "<All Players>"


@dataclass
class ObjectTypesList:
    """One scripting object-type list (`ObjectTypes::xfer`): a named list of ini Object
    templates (e.g. "Air_Units" → the fliers), used by script conditions."""

    name: str
    templates: list[str]  # ini Object template names


@dataclass
class ToppleDirection:
    """One entry in `m_toppleDirections`: where a scripted tree/prop is toppling. ZH's
    `xferListAsciiStringCoord3D` writes `{ascii name, Coord3D}`; BFME2 collapses the name to a
    u32 key-hash (the same fork as `NamedReveal`), leaving a 16-byte `{hash, x, y, z}` record.
    Only non-empty in the three Ettenmoors campaign fixtures (two toppling props apiece)."""

    key: int  # u32 name key/hash
    position: tuple[float, float, float]  # the toppling object's world position


# BFME2's MAX_PLAYER_COUNT: every per-player section in CHUNK_ScriptEngine is written as a
# u32 count of exactly 20 player slots (ZH wrote its MAX_PLAYER_COUNT=16 as a u16).
SCRIPT_ENGINE_PLAYER_SLOTS = 20


@dataclass
class ScriptEngineState:
    """`CHUNK_ScriptEngine` — the script runtime (BFME2, version 5), fully walked.

    BFME2 forked the ZH v5 serializer but kept its section order: counters, flags, attack
    priorities, end-game timers, the named-object table, screen fade, the special-power maps,
    per-player acquired sciences, breeze, difficulty, named reveals, object-type lists, and a
    BFME2-only *scoped* named-object table at the end. The fork's systematic changes: counter
    and flag records gained an always-present player-scope string (empty = global), list counts
    widened from u16 to u32 inside versioned lists, and every name-keyed special-power/upgrade
    list became `{u32 key-hash, u32 value}` pairs instead of ascii names. Regions whose field
    split is not pinned down stay raw bytes (`unknown_*`, `fade_state`, `reveal_unknown`) —
    all observed constant or near-constant; see sav_format.md."""

    version: int
    unknown_head: bytes  # 4 bytes after the version, observed all-zero corpus-wide
    counters: list[ScriptCounter]
    flags: list[ScriptFlag]
    unknown_mid: bytes  # 12 bytes between flags and attack priorities, observed all-zero
    attack_priorities: list[AttackPriorityInfo]
    end_game_timer: int  # -1 when idle (ZH default)
    close_window_timer: int  # -1 when idle
    named_objects: list[tuple[str, int]]  # script unitName -> objectId (0 = dead/invalid)
    first_update: bool
    fade: int  # TFade enum (4 = no fade in every fixture)
    fade_min: float
    fade_max: float
    fade_cur: float
    fade_state: bytes  # 20 bytes of fade counters (one f32-like + four i32-like slots)
    head_pair_lists: list[list[tuple[int, int]]]  # five {u32 key-hash, u32 value} lists
    special_power_maps: list[list[list[tuple[int, int]]]]  # 4 sections x 20 players x pairs
    player_sciences: list[list[str]]  # 20 players x acquired SCIENCE_* names (fatal xref)
    topple_directions: list[ToppleDirection]  # scripted toppling props (campaign only)
    breeze: tuple[float, float, float, float, float, float]  # direction, dir vector x/y,
    # intensity, lean, randomness — the ZH breeze block verbatim
    breeze_period: int
    breeze_version: int
    difficulty: int  # GameDifficulty enum (1 = normal)
    freeze_by_script: bool
    reveal_unknown: bytes  # 8 bytes between the reveal count and its records (two u32 slots)
    reveals: list[NamedReveal]
    object_type_lists: list[ObjectTypesList]
    difficulty_bonus: bool  # m_objectsShouldReceiveDifficultyBonus
    current_track: str  # m_currentTrackName
    scoped_named_objects: list[tuple[str, str, int]]  # (scope, name, objectId); BFME2-only
    unknown_tail: bytes  # 8 trailing bytes, observed all-zero corpus-wide


def _read_pair_list(reader: XferReader, context: str) -> list[tuple[int, int]]:
    """A BFME2 versioned pair list: `u8 version=1 + u32 count + count x {u32, u32}` — the fork
    of ZH's `xferListAsciiString*` helpers with the names collapsed to key-hashes."""
    version = reader.version(1)
    if version != 1:
        raise ValueError(f"ScriptEngine {context}: unexpected list version {version}")
    return [(reader.uint32(), reader.uint32()) for _ in range(reader.uint32())]


def _write_pair_list(stream: BinaryStream, pairs: list[tuple[int, int]]) -> None:
    stream.writeUChar(1)
    stream.writeUInt32(len(pairs))
    for first, second in pairs:
        stream.writeUInt32(first)
        stream.writeUInt32(second)


def decode_script_engine(chunk: Chunk) -> ScriptEngineState:
    reader = XferReader(chunk.payload)
    version = reader.version(5)
    unknown_head = reader.bytes(4)
    if unknown_head != b"\x00\x00\x00\x00":
        # Tripwire: possibly a sequential-script count (ZH's first section). A non-zero value
        # would mean records this decoder has never seen; refuse rather than mis-parse.
        raise ValueError(f"ScriptEngine head bytes {unknown_head.hex()} != 0; new section?")

    counters = []
    for _ in range(reader.uint16()):
        scope = reader.ascii_string()
        name = reader.ascii_string()
        value = reader.int32()
        counters.append(ScriptCounter(scope, name, value, reader.bool()))

    flags = []
    for _ in range(reader.uint16()):
        scope = reader.ascii_string()
        name = reader.ascii_string()
        flags.append(ScriptFlag(scope, name, reader.bool()))

    unknown_mid = reader.bytes(12)

    attack_priorities = []
    for _ in range(reader.uint16()):
        reader.version(1)
        name = reader.ascii_string()
        default_priority = reader.int32()
        overrides = [(reader.ascii_string(), reader.int32()) for _ in range(reader.uint16())]
        attack_priorities.append(AttackPriorityInfo(name, default_priority, overrides))
    if reader.int32() != len(attack_priorities):  # ZH's redundant post-loop m_numAttackInfo
        raise ValueError("ScriptEngine attack-priority trailing count mismatch")

    end_game_timer = reader.int32()
    close_window_timer = reader.int32()

    named_objects = [(reader.ascii_string(), reader.uint32()) for _ in range(reader.uint16())]

    first_update = reader.bool()
    fade = reader.uint32()
    fade_min = reader.real()
    fade_max = reader.real()
    fade_cur = reader.real()
    fade_state = reader.bytes(20)

    head_pair_lists = [_read_pair_list(reader, f"head list {i}") for i in range(5)]

    special_power_maps = []
    for section in range(4):
        slots = reader.uint32()
        if slots != SCRIPT_ENGINE_PLAYER_SLOTS:
            raise ValueError(f"ScriptEngine special-power section {section}: {slots} slots")
        special_power_maps.append([_read_pair_list(reader, f"sp {section}") for _ in range(slots)])

    if reader.uint32() != SCRIPT_ENGINE_PLAYER_SLOTS:
        raise ValueError("ScriptEngine science section: bad player-slot count")
    player_sciences = []
    for _ in range(SCRIPT_ENGINE_PLAYER_SLOTS):
        reader.version(1)
        player_sciences.append([reader.ascii_string() for _ in range(reader.uint32())])

    # topple directions: versioned list of 16-byte `{u32 key-hash, Coord3D}` records (ZH's
    # `{ascii, Coord3D}` with the name hashed — the same fork as NamedReveal). Empty except in
    # the Ettenmoors campaign saves; there the two records' positions land exactly on the breeze
    # block, confirming the 16-byte item size.
    reader.version(1)
    topple_directions = []
    for _ in range(reader.uint32()):
        key = reader.uint32()
        position = (reader.real(), reader.real(), reader.real())
        topple_directions.append(ToppleDirection(key, position))

    breeze = (
        reader.real(),
        reader.real(),
        reader.real(),
        reader.real(),
        reader.real(),
        reader.real(),
    )
    breeze_period = reader.uint16()
    breeze_version = reader.uint16()
    difficulty = reader.uint32()
    freeze_by_script = reader.bool()

    reveal_count = reader.uint16()
    reveal_unknown = reader.bytes(8)
    reveals = []
    for _ in range(reveal_count):
        key = reader.uint32()
        name = reader.ascii_string()
        radius = reader.real()
        reveals.append(NamedReveal(key, name, radius, reader.ascii_string()))

    object_type_lists = []
    for _ in range(reader.uint16()):
        reader.version(1)
        name = reader.ascii_string()
        templates = [reader.ascii_string() for _ in range(reader.uint16())]
        object_type_lists.append(ObjectTypesList(name, templates))

    difficulty_bonus = reader.bool()
    current_track = reader.ascii_string()

    scoped_named_objects = []
    for _ in range(reader.uint32()):
        scope = reader.ascii_string()
        name = reader.ascii_string()
        scoped_named_objects.append((scope, name, reader.uint32()))

    unknown_tail = reader.rest()
    if unknown_tail != b"\x00" * 8:
        raise ValueError(f"ScriptEngine tail {unknown_tail[:16].hex()} != 8 zero bytes")

    return ScriptEngineState(
        version,
        unknown_head,
        counters,
        flags,
        unknown_mid,
        attack_priorities,
        end_game_timer,
        close_window_timer,
        named_objects,
        first_update,
        fade,
        fade_min,
        fade_max,
        fade_cur,
        fade_state,
        head_pair_lists,
        special_power_maps,
        player_sciences,
        topple_directions,
        breeze,
        breeze_period,
        breeze_version,
        difficulty,
        freeze_by_script,
        reveal_unknown,
        reveals,
        object_type_lists,
        difficulty_bonus,
        current_track,
        scoped_named_objects,
        unknown_tail,
    )


def encode_script_engine(state: ScriptEngineState) -> bytes:
    """Inverse of `decode_script_engine`; `encode(decode(c)) == c.payload` on every fixture."""
    stream = BinaryStream(io.BytesIO())
    stream.writeUChar(state.version)
    stream.writeBytes(state.unknown_head)

    stream.writeUInt16(len(state.counters))
    for counter in state.counters:
        stream.writeString(counter.scope)
        stream.writeString(counter.name)
        stream.writeInt32(counter.value)
        stream.writeUChar(1 if counter.is_countdown_timer else 0)

    stream.writeUInt16(len(state.flags))
    for flag in state.flags:
        stream.writeString(flag.scope)
        stream.writeString(flag.name)
        stream.writeUChar(1 if flag.value else 0)

    stream.writeBytes(state.unknown_mid)

    stream.writeUInt16(len(state.attack_priorities))
    for priority in state.attack_priorities:
        stream.writeUChar(1)
        stream.writeString(priority.name)
        stream.writeInt32(priority.default_priority)
        stream.writeUInt16(len(priority.overrides))
        for template, value in priority.overrides:
            stream.writeString(template)
            stream.writeInt32(value)
    stream.writeInt32(len(state.attack_priorities))

    stream.writeInt32(state.end_game_timer)
    stream.writeInt32(state.close_window_timer)

    stream.writeUInt16(len(state.named_objects))
    for name, object_id in state.named_objects:
        stream.writeString(name)
        stream.writeUInt32(object_id)

    stream.writeUChar(1 if state.first_update else 0)
    stream.writeUInt32(state.fade)
    stream.writeFloat(state.fade_min)
    stream.writeFloat(state.fade_max)
    stream.writeFloat(state.fade_cur)
    stream.writeBytes(state.fade_state)

    for pairs in state.head_pair_lists:
        _write_pair_list(stream, pairs)

    for section in state.special_power_maps:
        stream.writeUInt32(len(section))
        for pairs in section:
            _write_pair_list(stream, pairs)

    stream.writeUInt32(len(state.player_sciences))
    for sciences in state.player_sciences:
        stream.writeUChar(1)
        stream.writeUInt32(len(sciences))
        for science in sciences:
            stream.writeString(science)

    stream.writeUChar(1)  # topple-direction list version
    stream.writeUInt32(len(state.topple_directions))
    for topple in state.topple_directions:
        stream.writeUInt32(topple.key)
        for coordinate in topple.position:
            stream.writeFloat(coordinate)

    for component in state.breeze:
        stream.writeFloat(component)
    stream.writeUInt16(state.breeze_period)
    stream.writeUInt16(state.breeze_version)
    stream.writeUInt32(state.difficulty)
    stream.writeUChar(1 if state.freeze_by_script else 0)

    stream.writeUInt16(len(state.reveals))
    stream.writeBytes(state.reveal_unknown)
    for reveal in state.reveals:
        stream.writeUInt32(reveal.key)
        stream.writeString(reveal.name)
        stream.writeFloat(reveal.radius)
        stream.writeString(reveal.player)

    stream.writeUInt16(len(state.object_type_lists))
    for type_list in state.object_type_lists:
        stream.writeUChar(1)
        stream.writeString(type_list.name)
        stream.writeUInt16(len(type_list.templates))
        for template in type_list.templates:
            stream.writeString(template)

    stream.writeUChar(1 if state.difficulty_bonus else 0)
    stream.writeString(state.current_track)

    stream.writeUInt32(len(state.scoped_named_objects))
    for scope, name, object_id in state.scoped_named_objects:
        stream.writeString(scope)
        stream.writeString(name)
        stream.writeUInt32(object_id)

    stream.writeBytes(state.unknown_tail)
    return stream.getvalue()


def extract_map(save: SaveFile) -> bytes:
    """Return the embedded `.map` bytes, ready to write out or hand to `sage_map`."""
    chunk = save.chunk("CHUNK_GameStateMap")
    if chunk is None:
        raise ValueError("save has no CHUNK_GameStateMap")
    gsm = decode_game_state_map(chunk)
    if not gsm.has_map:
        raise ValueError("save carries no embedded map (a between-missions save boots a fresh map)")
    return gsm.map_data


def iter_objects(save: SaveFile) -> list[SaveObject]:
    """Every live object in the save's `CHUNK_GameLogic`, each carrying its resolved ini
    template name — the raw material for the Phase 3 cross-reference against a `Game`."""
    chunk = save.chunk("CHUNK_GameLogic")
    if chunk is None:
        raise ValueError("save has no CHUNK_GameLogic")
    return decode_game_logic(chunk).objects


@dataclass
class SmallChunk:
    """A small, structurally-shallow chunk decoded to just its leading version byte, with the
    remainder kept opaque. This is the Step-1 treatment for the nine chunks that carry only a
    version plus a short fixed scalar blob in a skirmish save (`Partition`, `Collision`,
    `SpellStore`, `ObjectivesMenu`, `InGameUI`, `LivingWorldLogic`, `WeatherSystem`, the
    version-only `MineshaftPortalNetworkManager`, and `MissionObjectives`). Their payloads were
    confirmed constant across every fixture — except `WeatherSystem` (an equal `int32` pair near
    the end varies per save — a weather seed/offset) and `MissionObjectives` (empty in skirmish
    but a list of `SCRIPT:OBJECTIVE_*` / `SCRIPT:BONUS_*` names in a campaign save) — so those two
    keep meaningful data in `body` awaiting a fuller decode; the rest are effectively fully
    understood, just not field-split. `body` is exact, so the chunk round-trips."""

    version: int
    body: bytes  # the payload after the version byte, kept opaque


def decode_small_chunk(chunk: Chunk) -> SmallChunk:
    payload = chunk.payload
    return SmallChunk(payload[0] if payload else -1, payload[1:])


def encode_small_chunk(small: SmallChunk) -> bytes:
    """Inverse of `decode_small_chunk`: the version byte followed by the opaque remainder."""
    return bytes([small.version]) + small.body


# A living-world roster name: a length byte (3..48) then that many bytes forming an ini-style
# identifier — letters/digits/underscore, plus `:` for the `LWA:*` army-type refs. Matches the
# players.py harvest philosophy (strict framing + charset), validated on the WotR corpus to pull
# only real names out of `CHUNK_LivingWorldLogic` (players, armies, heroes, unit templates, icons,
# banners, regions) with no garbage.
_LWL_NAME = re.compile(rb"^[A-Za-z][A-Za-z0-9_:]*$")
_LWL_NAME_MIN = 3
_LWL_NAME_MAX = 48


# The 2-byte marker an army roster entry writes right before a unit/hero template's length byte:
# a `u8 kind = 2` + `u8 version = 1`. It precedes *every* living-world army unit/hero template and
# *no* runtime instance name across the WotR corpus (zero false positives), so it is the
# self-validating signature that separates ini-backed object templates from instance names
# (`DurmarthPlayerArmy`, `Player_1`) without walking the heterogeneous record body — the same
# bet players.py makes with the `Upgrade_`/`SCIENCE_` prefixes. (The CreateAHero available-hero
# list uses a weaker `00 0a` marker; held back as a second signature until it is confirmed
# structural rather than a common-byte coincidence.)
_LWL_ARMY_ENTRY_MARKER = b"\x02\x01"


def _iter_lwl_strings(payload: bytes):
    """Yield `(offset_of_length_byte, name)` for every length-prefixed identifier in a
    `CHUNK_LivingWorldLogic` payload. The shared scan behind the roster view and the
    object-template signature harvest."""
    pos = 0
    end = len(payload) - 1
    while pos < end:
        length = payload[pos]
        if _LWL_NAME_MIN <= length <= _LWL_NAME_MAX and pos + 1 + length <= len(payload):
            raw = payload[pos + 1 : pos + 1 + length]
            if _LWL_NAME.match(raw):
                yield pos, raw.decode("latin-1")
                pos += 1 + length
                continue
        pos += 1


def living_world_names(payload: bytes) -> list[str]:
    """The distinct length-prefixed identifier names in a `CHUNK_LivingWorldLogic` payload, in
    first-appearance order — the WotR strategic roster (see `LivingWorldLogicState`). Purely a
    *view*: a signature scan over the opaque body, not a structural walk, so it never feeds the
    encoder. Empty for the vanilla-skirmish constant (no living world)."""
    seen: dict[str, None] = {}
    for _offset, name in _iter_lwl_strings(payload):
        seen.setdefault(name, None)
    return list(seen)


def living_world_object_templates(payload: bytes) -> list[str]:
    """The distinct ini `Object` template names carried by the living-world army rosters in a
    `CHUNK_LivingWorldLogic` payload — the units and heroes each saved army fields — in
    first-appearance order. Identified by the `_LWL_ARMY_ENTRY_MARKER` (`02 01`) that precedes each
    roster entry's name, which on the WotR corpus selects only names that resolve as `objects` (no
    instance-name false positives). This is the safe subset of the roster to cross-reference; the
    rest of `living_world_names` (players, armies, icons, banners, instances) is not resolved as a
    single kind without the record walk."""
    seen: dict[str, None] = {}
    for offset, name in _iter_lwl_strings(payload):
        if payload[offset - len(_LWL_ARMY_ENTRY_MARKER) : offset] == _LWL_ARMY_ENTRY_MARKER:
            seen.setdefault(name, None)
    return list(seen)


@dataclass
class LivingWorldLogicState:
    """`CHUNK_LivingWorldLogic` (version 6) — the War-of-the-Ring strategic layer. In a non-WotR
    save this is a 22-byte constant (no living world); in a WotR save it is 22–32 KB holding the
    meta-campaign: the players, their living-world armies (`LWA:*` army-type refs + per-army
    instance names), the heroes and unit templates those armies field, and the region/icon/banner
    assets. The record structure (heterogeneous, variable-length, with embedded `NuggetTag_*`
    `KOLB` blocks) is not yet walked, so `body` is opaque and round-trips verbatim; `names` is a
    harvested *view* of the roster's ini-names (via `living_world_names`) for read-out and future
    xref. Not yet a dangling-reference source: a bare identifier here cannot, without the record
    walk, be told apart from a runtime instance name (`DurmarthPlayerArmy`, `Player_1`), so the
    harvest is surfaced but deliberately not fed to `check_save` (would risk false danglers)."""

    version: int
    names: list[str]  # the strategic roster's distinct ini-names, in file order (a view of body)
    body: bytes  # the payload after the version byte, kept opaque (exact round-trip)


def decode_living_world_logic(chunk: Chunk) -> LivingWorldLogicState:
    payload = chunk.payload
    version = payload[0] if payload else -1
    return LivingWorldLogicState(version, living_world_names(payload), payload[1:])


def encode_living_world_logic(state: LivingWorldLogicState) -> bytes:
    """Inverse of `decode_living_world_logic`: version byte + the opaque body. The `names` view is
    derived from `body`, so it is not written separately."""
    return bytes([state.version]) + state.body


# The Step-1 chunks handled by the generic `SmallChunk` codec (see that class for the reversing
# notes). Registered with the specific decoders below in `CHUNK_CODECS`.
_SMALL_CHUNK_NAMES = (
    "CHUNK_MineshaftPortalNetworkManager",
    "CHUNK_Partition",
    "CHUNK_Collision",
    "CHUNK_SpellStore",
    "CHUNK_ObjectivesMenu",
    "CHUNK_MissionObjectives",
    "CHUNK_InGameUI",
    "CHUNK_WeatherSystem",
)


@dataclass(frozen=True)
class ChunkCodec:
    """How one chunk is decoded, (optionally) re-encoded, and how much of it is understood — the
    single registration point so a new decoder joins the round-trip test and coverage report for
    free (see `CHUNK_CODECS`).

    - `decode(chunk)` → the typed value for that chunk.
    - `encode(value, payload)` is its **exact inverse** — `encode(decode(c), c.payload) ==
      c.payload` for every fixture — or None for a chunk decoded only partially (no lossless
      writer yet). The original payload is passed for decoders that keep an opaque region verbatim
      (e.g. the embedded map); encoders that don't need it ignore it.
    - `opaque_bytes(value)` is how many of the payload's bytes the decode left undecoded (raw
      `bytes` regions). Coverage subtracts it from the payload size, so a decoder silently falling
      back to opaque shows up as a coverage regression rather than passing unnoticed."""

    name: str
    decode: Callable[[Chunk], Any]
    encode: Callable[[Any, bytes], bytes] | None
    opaque_bytes: Callable[[Any], int]


# The registry of decoded chunks. Keyed by the exact `CHUNK_*` name the engine writes; the
# coverage report and the parametrized round-trip test both iterate this, so adding a decoder here
# is all it takes to enrol it in both. `CHUNK_GameLogic` and `CHUNK_GameClient` are decoded to their
# object/drawable index only — their module bodies stay opaque — but still carry an exact-inverse
# encoder: the bodies round-trip verbatim and each `KOLB` end-offset is recomputed from the stored
# body offset. The nine Step-1 chunks share the generic `SmallChunk` codec (version byte + opaque
# body).
CHUNK_CODECS: dict[str, ChunkCodec] = {
    codec.name: codec
    for codec in (
        ChunkCodec(
            "CHUNK_GameState",
            decode_game_state,
            lambda value, _payload: encode_game_state(value),
            lambda value: len(value.leading) + len(value.post_map) + len(value.trailing),
        ),
        ChunkCodec(
            "CHUNK_GameStateMap",
            decode_game_state_map,
            encode_game_state_map,
            lambda value: len(value.trailing),
        ),
        ChunkCodec(
            "CHUNK_Campaign",
            decode_campaign,
            lambda value, _payload: encode_campaign(value),
            # the roster block round-trips verbatim but its group framing is not structurally
            # decoded (heroes are a harvested view), so it counts as opaque for coverage
            lambda value: len(value.roster),
        ),
        ChunkCodec(
            "CHUNK_GameLogic",
            decode_game_logic,
            lambda value, _payload: encode_game_logic(value),
            lambda value: (
                len(value.preamble)
                + sum(len(obj.body) for obj in value.objects)
                + len(value.trailing)
            ),
        ),
        ChunkCodec(
            "CHUNK_GameClient",
            decode_game_client,
            lambda value, _payload: encode_game_client(value),
            lambda value: (
                len(value.preamble)
                + sum(len(drawable.body) for drawable in value.drawables)
                + len(value.trailing)
            ),
        ),
        ChunkCodec(
            "CHUNK_Players",
            decode_players,
            lambda value, _payload: encode_players(value),
            # per player: the 16-byte prefix, the 10-byte radar block, the 6-byte energy stub,
            # and the opaque record tail (AI/build/science/rank/hero state)
            lambda value: sum(
                len(p.prefix) + len(p.radar) + len(p.energy) + len(p.tail) for p in value.players
            ),
        ),
        ChunkCodec(
            "CHUNK_ScriptEngine",
            decode_script_engine,
            lambda value, _payload: encode_script_engine(value),
            # the four raw regions kept verbatim: head u32, the 12 mid bytes, the 20-byte
            # fade-counter block, the reveal-section u32 pair, and the 8-byte tail
            lambda value: (
                len(value.unknown_head)
                + len(value.unknown_mid)
                + len(value.fade_state)
                + len(value.reveal_unknown)
                + len(value.unknown_tail)
            ),
        ),
        ChunkCodec(
            "CHUNK_TacticalView",
            decode_tactical_view,
            lambda value, _payload: encode_tactical_view(value),
            lambda value: len(value.trailing),
        ),
        ChunkCodec(
            "CHUNK_TeamFactory",
            decode_team_factory,
            lambda value, _payload: encode_team_factory(value),
            lambda value: len(value.body),
        ),
        ChunkCodec(
            "CHUNK_LivingWorldLogic",
            decode_living_world_logic,
            lambda value, _payload: encode_living_world_logic(value),
            # the roster is a harvested view over the body, not a structural decode, so the whole
            # post-version body still counts as opaque for coverage
            lambda value: len(value.body),
        ),
        *(
            ChunkCodec(
                name,
                decode_small_chunk,
                lambda value, _payload: encode_small_chunk(value),
                lambda value: len(value.body),
            )
            for name in _SMALL_CHUNK_NAMES
        ),
    )
}


__all__ = [
    "CHUNK_CODECS",
    "AttackPriorityInfo",
    "Campaign",
    "CampaignHero",
    "ChunkCodec",
    "GameClientState",
    "GameLogicState",
    "GameStateHeader",
    "GameStateMap",
    "NamedReveal",
    "ObjectPrefix",
    "ObjectTypesList",
    "PlayerUpgrade",
    "PlayersState",
    "SCRIPT_ENGINE_PLAYER_SLOTS",
    "SaveDrawable",
    "SaveObject",
    "SavePlayer",
    "ScriptCounter",
    "ScriptEngineState",
    "ScriptFlag",
    "LivingWorldLogicState",
    "SmallChunk",
    "TacticalView",
    "TeamFactory",
    "ToppleDirection",
    "decode_campaign",
    "decode_game_client",
    "decode_game_logic",
    "decode_game_state",
    "decode_game_state_map",
    "decode_living_world_logic",
    "decode_object_prefix",
    "decode_players",
    "decode_script_engine",
    "decode_small_chunk",
    "decode_tactical_view",
    "decode_team_factory",
    "drawable_modules",
    "encode_game_client",
    "encode_game_logic",
    "encode_living_world_logic",
    "encode_players",
    "encode_script_engine",
    "encode_small_chunk",
    "encode_tactical_view",
    "encode_team_factory",
    "extract_map",
    "iter_objects",
    "living_world_names",
    "living_world_object_templates",
    "object_modules",
    "object_veterancy_level",
    "set_object_position",
]
