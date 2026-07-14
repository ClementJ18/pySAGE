"""Reader for SAGE replay files (`.rep`, `.BfMEReplay`, `.BfME2Replay`).

A replay is a header (timestamps, game version, the ASCII metadata string carrying the
map and player slots) followed by a stream of order chunks - one per issued command,
tagged with a logic-frame timecode and the issuing player. The header layouts diverge
per game; the chunk stream is shared. The Generals path follows OpenSAGE's ReplayFile
implementation; the BFME2 path was validated against a corpus of real replays (every
chunk stream parses exactly to end-of-file and the header timecode count matches the
last chunk).
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from io import BytesIO
from pathlib import Path

from sage_utils.stream import BinaryStream

__all__ = [
    "Bfme2OrderType",
    "GeneralsOrderType",
    "Order",
    "OrderArgument",
    "OrderArgumentType",
    "ReplayChunk",
    "ReplayFile",
    "ReplayGameType",
    "ReplayHeader",
    "ReplayMetadata",
    "ReplaySlot",
    "ReplaySlotDifficulty",
    "ReplaySlotType",
    "ReplayTimestamp",
    "parse_replay",
    "parse_replay_from_path",
]


class ReplayGameType(IntEnum):
    Generals = 0
    Bfme = 1
    Bfme2 = 2


class OrderArgumentType(IntEnum):
    """SAGE order-argument type tags, sharing Generals' `ArgumentDataType` enum. The read
    shape of each tag is fixed by that enum: Boolean is one byte, WideChar two, everything
    else four (or a run of four-byte words). In BFME2 replays only Integer/Float/Boolean/
    ObjectId/Position/ScreenRectangle/Timestamp ever occur; DrawableId/TeamId/ScreenPosition/
    WideChar are unattested there, so their reads are structural rather than corpus-validated."""

    Integer = 0
    Float = 1
    Boolean = 2
    ObjectId = 3
    DrawableId = 4
    TeamId = 5
    Position = 6
    ScreenPosition = 7
    ScreenRectangle = 8
    Timestamp = 9
    WideChar = 10


class GeneralsOrderType(IntEnum):
    """Order-type ids as named by OpenSAGE - for **Generals** replays. BFME2 reuses the
    same numeric range with different meanings, so BFME chunks keep the raw integer."""

    EndGame = 27
    SetSelection = 1001
    SelectAcrossScreen = 1002
    ClearSelection = 1003
    Deselect = 1004
    CreateGroup0 = 1006
    CreateGroup1 = 1007
    CreateGroup2 = 1008
    CreateGroup3 = 1009
    CreateGroup4 = 1010
    CreateGroup5 = 1011
    CreateGroup6 = 1012
    CreateGroup7 = 1013
    CreateGroup8 = 1014
    CreateGroup9 = 1015
    SelectGroup0 = 1016
    SelectGroup1 = 1017
    SelectGroup2 = 1018
    SelectGroup3 = 1019
    SelectGroup4 = 1020
    SelectGroup5 = 1021
    SelectGroup6 = 1022
    SelectGroup7 = 1023
    SelectGroup8 = 1024
    SelectGroup9 = 1025
    UseWeapon = 1038
    SnipeVehicle = 1039
    SpecialPower = 1040
    SpecialPowerAtLocation = 1041
    SpecialPowerAtObject = 1042
    SetRallyPoint = 1043
    PurchaseScience = 1044
    BeginUpgrade = 1045
    CancelUpgrade = 1046
    CreateUnit = 1047
    CancelUnit = 1048
    BuildObject = 1049
    CancelBuild = 1051
    Sell = 1052
    ExitContainer = 1053
    Evacuate = 1054
    CombatDrop = 1057
    DrawBoxSelection = 1058
    AttackObject = 1059
    ForceAttackObject = 1060
    ForceAttackGround = 1061
    RepairVehicle = 1062
    RepairStructure = 1064
    ResumeBuild = 1065
    Enter = 1066
    GatherDumpSupplies = 1067
    MoveTo = 1068
    AttackMove = 1069
    AddWaypoint = 1071
    GuardMode = 1072
    StopMoving = 1074
    Scatter = 1075
    HackInternet = 1076
    Cheer = 1077
    ToggleOvercharge = 1078
    SelectWeapon = 1079
    DirectParticleCannon = 1086
    SetCameraPosition = 1092
    ToggleFormationMode = 1094
    Checksum = 1095
    SelectClearMines = 1096


class Bfme2OrderType(IntEnum):
    """Order-type ids for **BFME2 / RotWK** replays that resolve to a definition or action
    name exactly (the ✅ grade of `order_space_map.md` sections A and B). BFME2 reuses the
    Generals numeric range with shifted/appended meanings, so these are the BFME2 readings,
    not the Generals ones. Ids still carrying a provisional offset or unknown meaning (🟡/❓)
    are deliberately absent; `chunk.order_type` keeps the raw integer regardless."""

    EndOfRecording = 0x1D  # issued once at the last timecode by the recording client
    Select = 0x3E9  # new/additive selection (Bool) with the selected ObjectId list
    Deselect = 0x3EC  # selection emptied
    CreateGroup0 = 0x3EE
    CreateGroup1 = 0x3EF
    CreateGroup2 = 0x3F0
    CreateGroup3 = 0x3F1
    CreateGroup4 = 0x3F2
    CreateGroup5 = 0x3F3
    CreateGroup6 = 0x3F4
    CreateGroup7 = 0x3F5
    CreateGroup8 = 0x3F6
    CreateGroup9 = 0x3F7
    SelectGroup0 = 0x3F8
    SelectGroup1 = 0x3F9
    SelectGroup2 = 0x3FA
    SelectGroup3 = 0x3FB
    SelectGroup4 = 0x3FC
    SelectGroup5 = 0x3FD
    SelectGroup6 = 0x3FE
    SelectGroup7 = 0x3FF
    SelectGroup8 = 0x400
    SelectGroup9 = 0x401
    SpecialPower = 0x410  # cast - self / no target
    SpecialPowerAtLocation = 0x411  # cast - at a ground point
    SpecialPowerAtObject = 0x412  # cast - at a target object
    SetRallyPoint = 0x413
    PurchaseSpellbookPower = 0x414
    Recruit = 0x417  # recruit unit / buy upgrade (flag False) or fortress hero (flag True)
    Construct = 0x419  # build-plot placement (thing, location, angle)
    BuildStructure = 0x41A
    CombineHordes = 0x423  # combine hordes (Edain horde-merge); arg = target/primary horde ObjectId
    BandBoxSelect = 0x424
    GroundMove = 0x42F  # ground smart command (move)
    LeaveGame = 0x448  # voluntary leave-game
    ChecksumHeartbeat = 0x44A  # per-client checksum, every REPLAY_CRC_INTERVAL frames
    SpecialPowerGlobal = 0x456  # cast - untargeted / global
    ToggleWeaponSet = 0x457
    Handshake = 0x462  # start-of-match handshake
    ModalBracket = 0x469  # modal-state enter/exit bracket


class ReplaySlotType(IntEnum):
    Human = 0
    Computer = 1
    Empty = 2


class ReplaySlotDifficulty(IntEnum):
    Easy = 0
    Medium = 1
    Hard = 2
    Brutal = 3  # BFME2 only ("B" slots); Generals stops at Hard


@dataclass
class ReplayTimestamp:
    """Windows SYSTEMTIME - eight little-endian uint16s."""

    year: int
    month: int
    day_of_week: int
    day: int
    hour: int
    minute: int
    second: int
    millisecond: int

    @staticmethod
    def parse(stream: BinaryStream) -> ReplayTimestamp:
        return ReplayTimestamp(*(stream.readUInt16() for _ in range(8)))

    def __str__(self) -> str:
        return (
            f"{self.year:04d}-{self.month:02d}-{self.day:02d} "
            f"{self.hour:02d}:{self.minute:02d}:{self.second:02d}.{self.millisecond:03d}"
        )


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _parse_ip(text: str) -> ipaddress.IPv4Address | None:
    """The slot's connection address as 8 hex digits, most-significant octet first."""
    try:
        return ipaddress.IPv4Address(int(text, 16))
    except (ValueError, ipaddress.AddressValueError):
        return None


@dataclass
class ReplaySlot:
    """One player slot from the metadata `S=` entry, written by the engine's lobby
    serializer. Human slots are
    `H<name>,<ip-hex>,<port>,<TT>,<color>,<faction>,<start>,<team>,<NATBehavior>,<reserved...>`
    (the `TT` field is two `T`/`F` flags: accepted and has-map); computer slots drop the
    network fields: `C<difficulty>,<color>,<faction>,<start>,<team>,<NATBehavior>,<reserved...>`.
    The trailing `reserved` fields are constant across the corpus (`1,0` for humans, `0` for
    AI) and unexplained. `faction` is the mod's PlayerTemplate block index (resolving it to a
    name needs a loaded game and is out of scope); the sentinel `-1` is a lobby Random pick and
    `-2` marks an observer (a caster/spectator slot, always unteamed - see `is_observer`). `raw`
    is retained only for debugging."""

    slot_type: ReplaySlotType
    raw: str = ""
    human_name: str | None = None
    computer_difficulty: ReplaySlotDifficulty | None = None
    ip: ipaddress.IPv4Address | None = None
    port: int | None = None
    accepted: bool | None = None
    has_map: bool | None = None
    color: int = -1
    faction: int = -1
    start_position: int = -1
    team: int = -1
    nat_behavior: int = -1
    reserved: tuple[int, ...] = ()

    _DIFFICULTIES = {
        "E": ReplaySlotDifficulty.Easy,
        "M": ReplaySlotDifficulty.Medium,
        "H": ReplaySlotDifficulty.Hard,
        "B": ReplaySlotDifficulty.Brutal,
    }

    # The faction sentinel an observer (caster/spectator) slot carries: it joined the lobby but
    # plays no side, so it is always unteamed and issues no build orders. Distinct from `-1`, the
    # lobby Random pick (a real player whose faction the engine rolls at load time).
    OBSERVER_FACTION = -2

    @property
    def is_observer(self) -> bool:
        """Whether this slot is an observer (a caster/spectator that plays no side). Such a slot
        is a Human with a name but no faction and no team, so it must be kept out of player
        stats, faction labels, opponents, and any winner mapping."""
        return self.faction == ReplaySlot.OBSERVER_FACTION

    @staticmethod
    def parse(raw: str) -> ReplaySlot:
        kind = raw[0] if raw else ""
        if kind in ("X", "O", ""):
            return ReplaySlot(slot_type=ReplaySlotType.Empty, raw=raw)
        if kind not in ("H", "C"):
            raise ValueError(f"unexpected slot type character: {kind!r} in {raw!r}")

        details = raw.split(",")
        slot = ReplaySlot(
            slot_type=ReplaySlotType.Human if kind == "H" else ReplaySlotType.Computer,
            raw=raw,
        )

        if kind == "H":
            slot.human_name = details[0][1:]
            if len(details) > 7:
                slot.ip = _parse_ip(details[1])
                slot.port = _to_int(details[2], -1)
                tt = details[3]
                slot.accepted = tt[0] == "T" if len(tt) > 0 else None
                slot.has_map = tt[1] == "T" if len(tt) > 1 else None
                slot.color = _to_int(details[4], -1)
                slot.faction = _to_int(details[5], -1)
                slot.start_position = _to_int(details[6], -1)
                slot.team = _to_int(details[7], -1)
                if len(details) > 8:
                    slot.nat_behavior = _to_int(details[8], -1)
                    slot.reserved = tuple(_to_int(d, -1) for d in details[9:])
        else:
            difficulty = ReplaySlot._DIFFICULTIES.get(raw[1] if len(raw) > 1 else "")
            if difficulty is None:
                raise ValueError(f"unexpected difficulty character in slot {raw!r}")
            slot.computer_difficulty = difficulty
            if len(details) > 4:
                slot.color = _to_int(details[1], -1)
                slot.faction = _to_int(details[2], -1)
                slot.start_position = _to_int(details[3], -1)
                slot.team = _to_int(details[4], -1)
                if len(details) > 5:
                    slot.nat_behavior = _to_int(details[5], -1)
                    slot.reserved = tuple(_to_int(d, -1) for d in details[6:])

        return slot


# Width of the map-contents-mask hex prefix on the `M=` entry. Generals writes it as
# `%2.2x` (EA's released Recorder/GameInfo source; OpenSAGE reads exactly two chars);
# every BFME2 corpus replay carries three (`387maps/...`). The width is fixed per game,
# not greedy: map paths can themselves start with hex-alphabet characters (`data...`,
# `bfme...`), so stripping all leading hex digits would bleed into the path. BFME1 is
# unattested; it shares the BFME2 engine era, so it gets the same width.
_MAP_MASK_HEX_DIGITS = {
    ReplayGameType.Generals: 2,
    ReplayGameType.Bfme: 3,
    ReplayGameType.Bfme2: 3,
}


@dataclass
class ReplayMetadata:
    """The header's ASCII `key=value;` string, written by the engine's game-info encoder.
    Known keys get typed accessors; every pair (known or not - BFME2 adds `GSID`, `GT`, `SI`,
    `GR`) survives verbatim in `values`."""

    raw: str = ""
    values: dict[str, str] = field(default_factory=dict)
    map_file: str = ""
    # `getMapContentsMask()` (which map files exist); fixed-width hex prefix of `M=`
    map_contents_mask: int = 0
    map_crc: int = 0
    map_size: int = 0
    seed: int = 0
    starting_credits: int | None = None
    slots: list[ReplaySlot] = field(default_factory=list)

    @staticmethod
    def parse(stream: BinaryStream, game_type: ReplayGameType) -> ReplayMetadata:
        result = ReplayMetadata(raw=stream.readNullTerminatedAsciiString())
        width = _MAP_MASK_HEX_DIGITS[game_type]
        for entry in result.raw.split(";"):
            key, sep, value = entry.partition("=")
            if not sep:
                continue
            result.values[key] = value

            if key == "M":
                # The map path is prefixed by the contents mask as fixed-width hex
                # (see _MAP_MASK_HEX_DIGITS); a malformed prefix means no mask at all.
                try:
                    result.map_contents_mask = int(value[:width], 16)
                    result.map_file = value[width:]
                except ValueError:
                    result.map_contents_mask = 0
                    result.map_file = value
            elif key == "MC":
                result.map_crc = int(value, 16)
            elif key == "MS":
                result.map_size = _to_int(value)
            elif key == "SD":
                result.seed = _to_int(value)
            elif key == "SC":
                result.starting_credits = _to_int(value)
            elif key == "S":
                result.slots = [ReplaySlot.parse(s) for s in value.split(":") if s]
        return result

    @property
    def players(self) -> list[ReplaySlot]:
        return [s for s in self.slots if s.slot_type != ReplaySlotType.Empty]

    @property
    def install_id(self) -> int | None:
        """`GSID` - an install/mod identifier (co-varies 1:1 with the header's
        `data_checksum`), stored as hex. None when absent."""
        value = self.values.get("GSID")
        if value is None:
            return None
        try:
            return int(value, 16)
        except ValueError:
            return None

    @property
    def game_type_flag(self) -> int | None:
        """`GT` - always 0 in the corpus; meaning unconfirmed."""
        value = self.values.get("GT")
        return _to_int(value) if value is not None else None

    @property
    def si(self) -> int | None:
        """`SI` - always -1 in the corpus; meaning unconfirmed."""
        value = self.values.get("SI")
        return _to_int(value, -1) if value is not None else None

    @property
    def game_rules(self) -> tuple[int, ...]:
        """`GR` - ten space-separated lobby-rule ints. Fields 3 and 4 are the starting-
        resources and command-point sliders (see `starting_resources`/`command_points`);
        the trailing five are unset (-1)."""
        value = self.values.get("GR")
        return tuple(_to_int(v) for v in value.split()) if value else ()

    @property
    def starting_resources(self) -> int | None:
        """`GR` field 3 - the starting-resources slider (100 default)."""
        rules = self.game_rules
        return rules[3] if len(rules) > 3 else None

    @property
    def command_points(self) -> int | None:
        """`GR` field 4 - the command-point slider (1000 default)."""
        rules = self.game_rules
        return rules[4] if len(rules) > 4 else None


# Magic opening every BFME2 Create-A-Hero blob (see ReplayHeader.custom_heroes).
_CUSTOM_HERO_MAGIC = b"ALAE2STR"


@dataclass
class ReplayHeader:
    game_type: ReplayGameType
    start_time: datetime
    end_time: datetime
    num_timecodes: int
    filename: str
    timestamp: ReplayTimestamp
    version: str
    build_date: str
    metadata: ReplayMetadata
    # The recording client's own player index, written as a NUL-terminated ASCII "%d"
    # string. It is an index into `metadata.players` and identifies the replay's point of
    # view (matching the `0x1D` end-of-recording issuer, and available even when a crash
    # left no `0x1D`).
    local_player_index: int = -1
    # BFME2 header block. `crc_interval` is REPLAY_CRC_INTERVAL, the checksum-heartbeat
    # cadence (always 100). `abnormal_end_frame` is None when the recording finalized
    # normally (a 0xFFFFFFFF sentinel on disk) and otherwise the last completed heartbeat
    # frame of a crashed recording. `data_checksum` is an install/mod-scoped INI-tree
    # checksum (co-varies 1:1 with the metadata `GSID`). The reserved blocks are zero
    # across the corpus except a lone 0x01 in `reserved1` of one fixture, kept inspectable.
    crc_interval: int = 0
    abnormal_end_frame: int | None = None
    reserved1: bytes = b""
    data_checksum: int = 0
    reserved2: bytes = b""
    # BFME2's six trailing uint32s, constant (0, 0, 1, 1, 0, 0) across the corpus and
    # unnamed; Generals stores difficulty/originalGameMode/rankPoints/maxFPS here instead
    # (see the Generals-only fields below). Empty for a custom-hero replay, whose trailing
    # header words are replaced by `custom_hero_tail` (see below).
    unknown_tail: tuple[int, ...] = ()
    # BFME2 Create-A-Hero extension. A game featuring a customized hero embeds one
    # length-prefixed `ALAE2STR` blob per occupied player (a stock-hero slot carries a bare
    # 0 flag and no blob) between `local_player_index` and the trailing header words. The
    # blobs are retained raw (`custom_heroes`); decoding a hero's name/equipment/powers is a
    # follow-up. The per-player flag list shortens the trailing header block by one byte per
    # player, so those bytes are kept as `custom_hero_tail` (`24 - len(players)` bytes; its
    # last five words are the usual (0, 1, 1, 0, 0)) instead of `unknown_tail`.
    custom_heroes: list[bytes] = field(default_factory=list)
    custom_hero_tail: bytes = b""
    # Generals-only fields. The Generals branch follows EA's officially released
    # Recorder.cpp writer, cross-checked against OpenSAGE's reader; no Generals fixture
    # in the corpus exercises it yet.
    version_minor: int | None = None
    version_major: int | None = None
    desync: bool | None = None
    quit_early: bool | None = None
    player_disconnects: tuple[bool, ...] = ()
    exe_crc: int | None = None
    ini_crc: int | None = None
    difficulty: int | None = None
    original_game_mode: int | None = None
    rank_points: int | None = None
    game_speed: int | None = None  # Generals maxFPS; None for BFME2

    @staticmethod
    def parse(stream: BinaryStream) -> ReplayHeader:
        game_type = ReplayHeader._parse_game_type(stream)

        start_time = datetime.fromtimestamp(stream.readUInt32(), tz=UTC)
        end_time = datetime.fromtimestamp(stream.readUInt32(), tz=UTC)

        crc_interval = 0
        abnormal_end_frame: int | None = None
        reserved1 = b""
        desync: bool | None = None
        quit_early: bool | None = None
        player_disconnects: tuple[bool, ...] = ()
        if game_type is ReplayGameType.Generals:
            # Field order/sizes confirmed against EA's officially released Recorder.cpp
            # writer (frameDuration u32 + desync + quitEarly + 8 per-player disconnect
            # bools, one byte each); no corpus fixture exercises this branch yet.
            # OpenSAGE reads the same 14 bytes as a u16 count + 12 reserved bytes, which
            # truncates frame counts past 65535 - the EA layout is authoritative. They
            # consume the same 14 bytes the corpus-validated BFME2 branch spends on its
            # 17-byte block's first 14, so the reads stay aligned regardless.
            num_timecodes = stream.readUInt32()
            desync = stream.readUChar() != 0
            quit_early = stream.readUChar() != 0
            player_disconnects = tuple(stream.readUChar() != 0 for _ in range(8))
        else:
            num_timecodes = stream.readUInt32()
            crc_interval = stream.readUInt32()
            raw_abnormal = stream.readUInt32()
            abnormal_end_frame = None if raw_abnormal == 0xFFFFFFFF else raw_abnormal
            reserved1 = stream.readBytes(9)

        filename = stream.readNullTerminatedUnicodeString()
        timestamp = ReplayTimestamp.parse(stream)
        version = stream.readNullTerminatedUnicodeString()
        build_date = stream.readNullTerminatedUnicodeString()

        version_minor: int | None = None
        version_major: int | None = None
        exe_crc: int | None = None
        ini_crc: int | None = None
        data_checksum = 0
        reserved2 = b""
        if game_type is ReplayGameType.Generals:
            version_minor = stream.readUInt16()
            version_major = stream.readUInt16()
            exe_crc = stream.readUInt32()
            ini_crc = stream.readUInt32()
        else:
            data_checksum = stream.readUInt32()
            reserved2 = stream.readBytes(5)

        metadata = ReplayMetadata.parse(stream, game_type)

        local_player_index = _to_int(stream.readNullTerminatedAsciiString(), -1)

        custom_heroes: list[bytes] = []
        custom_hero_tail = b""
        if game_type is not ReplayGameType.Generals:
            custom_heroes = ReplayHeader._read_custom_heroes(stream, len(metadata.players))

        if custom_heroes:
            # The per-player flag list consumed one byte per player from the trailing header
            # block; the remainder (validated at 24 - len(players) across the corpus) carries
            # the same (…, 0, 1, 1, 0, 0) closing words as unknown_tail. Keep it raw.
            custom_hero_tail = stream.readBytes(24 - len(metadata.players))
            tail: tuple[int, ...] = ()
        else:
            tail_words = 4 if game_type is ReplayGameType.Generals else 6
            tail = tuple(stream.readUInt32() for _ in range(tail_words))

        difficulty: int | None = None
        original_game_mode: int | None = None
        rank_points: int | None = None
        game_speed: int | None = None
        if game_type is ReplayGameType.Generals:
            difficulty, original_game_mode, rank_points, game_speed = tail

        return ReplayHeader(
            game_type=game_type,
            start_time=start_time,
            end_time=end_time,
            num_timecodes=num_timecodes,
            filename=filename,
            timestamp=timestamp,
            version=version,
            build_date=build_date,
            metadata=metadata,
            local_player_index=local_player_index,
            crc_interval=crc_interval,
            abnormal_end_frame=abnormal_end_frame,
            reserved1=reserved1,
            data_checksum=data_checksum,
            reserved2=reserved2,
            unknown_tail=tail,
            custom_heroes=custom_heroes,
            custom_hero_tail=custom_hero_tail,
            version_minor=version_minor,
            version_major=version_major,
            desync=desync,
            quit_early=quit_early,
            player_disconnects=player_disconnects,
            exe_crc=exe_crc,
            ini_crc=ini_crc,
            difficulty=difficulty,
            original_game_mode=original_game_mode,
            rank_points=rank_points,
            game_speed=game_speed,
        )

    @staticmethod
    def _read_custom_heroes(stream: BinaryStream, num_players: int) -> list[bytes]:
        """Read the BFME2 Create-A-Hero header extension, if present. A game featuring a
        customized hero writes, right after `local_player_index`, one entry per occupied
        player: a `u8` flag (1 = this player brought a custom hero, 0 = a stock hero) and,
        when set, a `u32`-length-prefixed `ALAE2STR` blob. The list is absent entirely in an
        ordinary game, detected by peeking for the `1`+`ALAE2STR` signature; the stream is
        left untouched when it does not match. Returns the raw blobs (see `custom_heroes`)."""
        start = stream.tell()
        flag = stream.readUChar()
        stream.readUInt32()  # length
        magic = stream.readBytes(8)
        stream.seek(start)
        if flag != 1 or magic != _CUSTOM_HERO_MAGIC:
            return []

        heroes: list[bytes] = []
        for _ in range(num_players):
            if stream.readUChar() == 1:
                length = stream.readUInt32()
                heroes.append(stream.readBytes(length))
        return heroes

    @staticmethod
    def _parse_game_type(stream: BinaryStream) -> ReplayGameType:
        magic = stream.readBytes(8)
        if magic.startswith(b"GENREP"):
            stream.seek(6)  # GENREP magic is only six bytes
            return ReplayGameType.Generals
        if magic == b"BFMEREPL":
            return ReplayGameType.Bfme
        if magic == b"BFME2RPL":
            return ReplayGameType.Bfme2
        raise ValueError(f"not a SAGE replay (magic {magic!r})")

    @property
    def patch_fingerprint(self) -> str:
        """The recording install's game-data identity as a short comparable label: replays
        whose fingerprints differ were recorded on different game data (another patch or
        mod - the game itself flags such a replay on load) and do not simulate identically,
        so corpus tooling must not pool their stats. BFME/BFME2 write one INI-tree checksum
        (`data_checksum`); Generals writes its version split plus separate exe/ini CRCs."""
        if self.game_type is ReplayGameType.Generals:
            return (
                f"Generals {self.version_major}.{self.version_minor} "
                f"exe=0x{(self.exe_crc or 0):08X} ini=0x{(self.ini_crc or 0):08X}"
            )
        return f"{self.game_type.name} data=0x{self.data_checksum:08X}"

    def __repr__(self) -> str:
        return (
            f"<ReplayHeader {self.game_type.name} v{self.version!r} map={self.metadata.map_file!r}>"
        )


@dataclass
class OrderArgument:
    argument_type: OrderArgumentType
    value: object

    def __repr__(self) -> str:
        return f"{self.argument_type.name}({self.value!r})"


@dataclass
class Order:
    player_index: int
    order_type: int
    arguments: list[OrderArgument] = field(default_factory=list)

    def __repr__(self) -> str:
        args = ", ".join(repr(a) for a in self.arguments)
        return f"Order(0x{self.order_type:X}, player={self.player_index}, [{args}])"


@dataclass
class ReplayChunk:
    timecode: int
    order_type: int
    number: int  # 1-based player number as stored in the file
    order: Order

    @property
    def player_index(self) -> int:
        return self.number - 1

    @staticmethod
    def parse(stream: BinaryStream) -> ReplayChunk:
        timecode = stream.readUInt32()
        order_type = stream.readUInt32()
        number = stream.readUInt32()

        num_unique_argument_types = stream.readUChar()
        argument_counts = [
            (stream.readUChar(), stream.readUChar()) for _ in range(num_unique_argument_types)
        ]

        order = Order(player_index=number - 1, order_type=order_type)
        for argument_type_raw, count in argument_counts:
            try:
                argument_type = OrderArgumentType(argument_type_raw)
            except ValueError:
                raise ValueError(
                    f"unknown order argument type {argument_type_raw} at offset {stream.tell()}"
                ) from None
            for _ in range(count):
                order.arguments.append(
                    OrderArgument(argument_type, _read_argument(stream, argument_type))
                )

        return ReplayChunk(timecode=timecode, order_type=order_type, number=number, order=order)

    def __repr__(self) -> str:
        return (
            f"<ReplayChunk [{self.timecode}] order=0x{self.order_type:X} "
            f"player={self.player_index} ({len(self.order.arguments)} args)>"
        )


def _read_argument(stream: BinaryStream, argument_type: OrderArgumentType) -> object:
    match argument_type:
        case OrderArgumentType.Integer:
            return stream.readInt32()
        case OrderArgumentType.Float:
            return stream.readFloat()
        case OrderArgumentType.Boolean:
            return stream.readBoolChecked()
        case OrderArgumentType.ObjectId:
            return stream.readUInt32()
        case OrderArgumentType.Position:
            return stream.readVector3()
        case OrderArgumentType.ScreenPosition:
            return (stream.readInt32(), stream.readInt32())
        case OrderArgumentType.ScreenRectangle:
            return tuple(stream.readInt32() for _ in range(4))
        case OrderArgumentType.DrawableId | OrderArgumentType.TeamId:
            return stream.readUInt32()
        case OrderArgumentType.Timestamp:
            # Rides only the `0x44A` heartbeat in BFME2; the stream lands exactly on EOF.
            return stream.readUInt32()
        case OrderArgumentType.WideChar:
            # A single UTF-16 code unit - two bytes on disk, not four (unattested in the
            # BFME2 corpus, so this shape is structural rather than corpus-validated).
            return stream.readBytes(2)


# Chunk player numbers are offset from the metadata slot list: the first occupied slot
# issues orders as number 3 (numbers 0-2 presumably belong to the engine's built-in
# players). Validated on BFME2 replays with 2, 4 and 5 humans/AIs; the Generals offset
# is unknown, so no entry for it.
_FIRST_SLOT_NUMBER = {
    ReplayGameType.Bfme: 3,
    ReplayGameType.Bfme2: 3,
}

# Fallback seconds-per-timecode for replays whose header carries no usable wall-clock span
# (crashed recordings never finalize end_time/num_timecodes). The finalized BFME2 corpus
# clusters tightly at ~0.20 s per timecode, so this keeps crashed-replay clocks on the same
# scale rather than reading 0:00 everywhere. Used only when the real span is unavailable.
_NOMINAL_SECONDS_PER_FRAME = 0.2


@dataclass
class ReplayFile:
    header: ReplayHeader
    chunks: list[ReplayChunk] = field(default_factory=list)

    @property
    def game_type(self) -> ReplayGameType:
        return self.header.game_type

    @property
    def crashed(self) -> bool:
        """True when the recording did not finalize normally - the header carries an
        `abnormal_end_frame` (the last completed heartbeat before the crash) instead of
        the finalized sentinel."""
        return self.header.abnormal_end_frame is not None

    @property
    def seconds_per_frame(self) -> float:
        """Real seconds per logic frame, taken from the header's wall-clock span and
        timecode count (so clocks match the recording rather than an assumed tick rate).
        A crashed recording never finalizes its `end_time`/`num_timecodes`, leaving no
        usable span; there `_NOMINAL_SECONDS_PER_FRAME` keeps clocks on the same scale as
        finalized replays instead of collapsing every timecode to 0:00."""
        span = (self.header.end_time - self.header.start_time).total_seconds()
        if self.header.num_timecodes and span > 0:
            return span / self.header.num_timecodes
        return _NOMINAL_SECONDS_PER_FRAME

    def slot_index(self, chunk: ReplayChunk) -> int | None:
        """Index into `header.metadata.players` of the slot that issued this chunk's
        order, or None when the offset for the game is unknown or the number falls
        outside the occupied slots (engine-issued orders)."""
        first = _FIRST_SLOT_NUMBER.get(self.game_type)
        if first is None:
            return None
        index = chunk.number - first
        return index if 0 <= index < len(self.header.metadata.players) else None

    def slot_for(self, chunk: ReplayChunk) -> ReplaySlot | None:
        """The player slot that issued this chunk's order, when it can be mapped."""
        index = self.slot_index(chunk)
        return self.header.metadata.players[index] if index is not None else None

    def __repr__(self) -> str:
        return (
            f"<ReplayFile {self.header.game_type.name} "
            f"map={self.header.metadata.map_file!r} {len(self.chunks)} chunks>"
        )


def parse_replay(data: bytes, only_header: bool = False) -> ReplayFile:
    """Parse replay file bytes. With `only_header` the chunk stream is skipped -
    a cheap peek when only the map/players/version matter."""
    stream = BinaryStream(BytesIO(data))
    header = ReplayHeader.parse(stream)
    replay = ReplayFile(header=header)

    if only_header:
        return replay

    size = len(data)
    while stream.tell() < size:
        replay.chunks.append(ReplayChunk.parse(stream))

    # A crashed game never finalizes the header and leaves its timecode count 0
    # (observed on a real crash replay) - the cross-check only applies when set.
    if replay.chunks and header.num_timecodes not in (0, replay.chunks[-1].timecode):
        raise ValueError(
            f"timecode count mismatch: header says {header.num_timecodes}, "
            f"last chunk is {replay.chunks[-1].timecode}"
        )

    return replay


def parse_replay_from_path(path: str | Path, only_header: bool = False) -> ReplayFile:
    return parse_replay(Path(path).read_bytes(), only_header=only_header)
