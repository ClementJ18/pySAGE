"""Reader for SAGE replay files (`.rep`, `.BfMEReplay`, `.BfME2Replay`).

A replay is a header (timestamps, game version, the ASCII metadata string carrying the
map and player slots) followed by a stream of order chunks — one per issued command,
tagged with a logic-frame timecode and the issuing player. The header layouts diverge
per game; the chunk stream is shared. The Generals path follows OpenSAGE's ReplayFile
implementation; the BFME2 path was validated against a corpus of real replays (every
chunk stream parses exactly to end-of-file and the header timecode count matches the
last chunk). Open questions live in TODO.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from io import BytesIO
from pathlib import Path

from sage_utils.stream import BinaryStream

__all__ = [
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
    Integer = 0
    Float = 1
    Boolean = 2
    ObjectId = 3
    Unknown4 = 4
    Unknown5 = 5
    Position = 6
    ScreenPosition = 7
    ScreenRectangle = 8
    Unknown9 = 9
    Unknown10 = 10


class GeneralsOrderType(IntEnum):
    """Order-type ids as named by OpenSAGE — for **Generals** replays. BFME2 reuses the
    same numeric range with different meanings (see TODO.md), so BFME chunks keep the
    raw integer."""

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
    """Windows SYSTEMTIME — eight little-endian uint16s."""

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


@dataclass
class ReplaySlot:
    """One player slot from the metadata `S=` entry. Human slots look like
    `H<name>,<ip-hex>,<port>,TT,<color>,<faction>,<start>,<team>,...`; the trailing
    fields differ per game and are kept verbatim in `raw`."""

    slot_type: ReplaySlotType
    raw: str = ""
    human_name: str | None = None
    computer_difficulty: ReplaySlotDifficulty | None = None
    color: int = -1
    faction: int = -1
    start_position: int = -1
    team: int = -1

    _DIFFICULTIES = {
        "E": ReplaySlotDifficulty.Easy,
        "M": ReplaySlotDifficulty.Medium,
        "H": ReplaySlotDifficulty.Hard,
        "B": ReplaySlotDifficulty.Brutal,
    }

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
                slot.color = _to_int(details[4], -1)
                slot.faction = _to_int(details[5], -1)
                slot.start_position = _to_int(details[6], -1)
                slot.team = _to_int(details[7], -1)
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

        return slot


@dataclass
class ReplayMetadata:
    """The header's ASCII `key=value;` string. Known keys get typed accessors; every
    pair (known or not — BFME2 adds `GSID`, `GT`, `SI`, `GR`) survives in `values`."""

    raw: str = ""
    values: dict[str, str] = field(default_factory=dict)
    map_file: str = ""
    map_file_prefix: str = ""  # digits preceding the map path in `M=`; meaning unknown
    map_crc: int = 0
    map_size: int = 0
    seed: int = 0
    starting_credits: int | None = None
    slots: list[ReplaySlot] = field(default_factory=list)

    @staticmethod
    def parse(stream: BinaryStream) -> ReplayMetadata:
        result = ReplayMetadata(raw=stream.readNullTerminatedAsciiString())
        for entry in result.raw.split(";"):
            key, sep, value = entry.partition("=")
            if not sep:
                continue
            result.values[key] = value

            if key == "M":
                path = value.lstrip("0123456789")
                result.map_file_prefix = value[: len(value) - len(path)]
                result.map_file = path
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


@dataclass
class ReplayHeader:
    game_type: ReplayGameType
    start_time: datetime
    end_time: datetime
    num_timecodes: int
    unknown1: bytes  # Generals: 12 zero bytes; BFME/BFME2: 17 bytes (see TODO.md)
    filename: str
    timestamp: ReplayTimestamp
    version: str
    build_date: str
    metadata: ReplayMetadata
    # Generals only — the BFME2 header has a 9-byte block of unknown layout instead
    # (kept in unknown2), so no minor/major split is available there.
    version_minor: int | None = None
    version_major: int | None = None
    unknown2: bytes = b""
    # Trailing uint16 + uint32s. For Generals the last value is the game speed; the
    # BFME2 tail is longer and unmapped, so game_speed stays None there.
    unknown_tail: tuple[int, ...] = ()
    game_speed: int | None = None

    @staticmethod
    def parse(stream: BinaryStream) -> ReplayHeader:
        game_type = ReplayHeader._parse_game_type(stream)

        start_time = datetime.fromtimestamp(stream.readUInt32(), tz=UTC)
        end_time = datetime.fromtimestamp(stream.readUInt32(), tz=UTC)

        if game_type is ReplayGameType.Generals:
            num_timecodes = stream.readUInt16()
            unknown1 = stream.readBytes(12)
        else:
            num_timecodes = stream.readUInt32()
            unknown1 = stream.readBytes(17)

        filename = stream.readNullTerminatedUnicodeString()
        timestamp = ReplayTimestamp.parse(stream)
        version = stream.readNullTerminatedUnicodeString()
        build_date = stream.readNullTerminatedUnicodeString()

        version_minor: int | None = None
        version_major: int | None = None
        if game_type is ReplayGameType.Generals:
            version_minor = stream.readUInt16()
            version_major = stream.readUInt16()
            unknown2 = stream.readBytes(8)
        else:
            unknown2 = stream.readBytes(9)

        metadata = ReplayMetadata.parse(stream)

        tail_words = 4 if game_type is ReplayGameType.Generals else 6
        tail = [stream.readUInt16()] + [stream.readUInt32() for _ in range(tail_words)]

        return ReplayHeader(
            game_type=game_type,
            start_time=start_time,
            end_time=end_time,
            num_timecodes=num_timecodes,
            unknown1=unknown1,
            filename=filename,
            timestamp=timestamp,
            version=version,
            build_date=build_date,
            version_minor=version_minor,
            version_major=version_major,
            unknown2=unknown2,
            metadata=metadata,
            unknown_tail=tuple(tail),
            game_speed=tail[-1] if game_type is ReplayGameType.Generals else None,
        )

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
        case _:
            # Unknown4/5/9/10 — four opaque bytes each. Validated for Unknown9 on
            # BFME2 (the stream then lands exactly on end-of-file); see TODO.md.
            return stream.readBytes(4)


# Chunk player numbers are offset from the metadata slot list: the first occupied slot
# issues orders as number 3 (numbers 0-2 presumably belong to the engine's built-in
# players). Validated on BFME2 replays with 2, 4 and 5 humans/AIs; the Generals offset
# is unknown (see TODO.md), so no entry for it.
_FIRST_SLOT_NUMBER = {
    ReplayGameType.Bfme: 3,
    ReplayGameType.Bfme2: 3,
}


@dataclass
class ReplayFile:
    header: ReplayHeader
    chunks: list[ReplayChunk] = field(default_factory=list)

    @property
    def game_type(self) -> ReplayGameType:
        return self.header.game_type

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
    """Parse replay file bytes. With `only_header` the chunk stream is skipped —
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
    # (observed on a real crash replay) — the cross-check only applies when set.
    if replay.chunks and header.num_timecodes not in (0, replay.chunks[-1].timecode):
        raise ValueError(
            f"timecode count mismatch: header says {header.num_timecodes}, "
            f"last chunk is {replay.chunks[-1].timecode}"
        )

    return replay


def parse_replay_from_path(path: str | Path, only_header: bool = False) -> ReplayFile:
    return parse_replay(Path(path).read_bytes(), only_header=only_header)
