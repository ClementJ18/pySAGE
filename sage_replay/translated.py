"""The translated-replay document: one replay's own structure, with every version-coupled id
replaced by its code name and nothing else.

A raw replay is not portable analysis data: its order stream carries integer ids that only
resolve against the exact game build that recorded it (template ids by ini load order, hero
recruits by revive-menu position, faction indices by PlayerTemplate order), so consuming a
corpus spanning mod patches normally means installing and mounting each patch in turn. This
module defines the document that removes that coupling: the replay serialized to JSON with each
id-bearing Integer argument turned into the definition's code name (`data.object_name`,
`data.upgrade`, `data.science`, `data.special_power`, and the `ReviveList` simulation for
fortress heroes), and everything else - booleans, ObjectIds, positions, order types, slots -
kept as raw replay structure. All analysis (KindOf bucketing, cancel netting, the winner
heuristic, aggregation) stays at load time, run against ANY paired game whose templates share
the recording's names by rehydrating the document into a `ReplayFile` and feeding it to the
existing pipeline unchanged. The document only goes stale when id-space knowledge itself
changes, so a pipeline or overlay change never invalidates it.

A translated id is a `str` sitting in an Integer argument slot; that JSON-type difference is the
whole signal a consumer reads (an `int` there is a raw, unresolved id, a `str` a resolved name).
The wire schema, version `FORMAT_VERSION`:

    {
      "format": "sage-replay/translated",   # the document's magic, for shared files
      "format_version": 2,
      "replay": "<replay file name>",       # the source name player-games report
      "size": 123456,                       # the replay file's byte size ...
      "sha256": "<hex digest>",             # ... and content hash: identity that survives
                                            # copying (an mtime would not), so a document
                                            # shared alongside its replay stays verifiable
      "fingerprint": "<patch fingerprint>", # which recording patch produced it (provenance)
      "game_type": "Bfme2",                 # ReplayGameType name
      "map": "maps/map edain linhir",       # header.metadata.map_file
      "num_timecodes": 21507,
      "seconds_per_frame": 0.2004,          # ReplayFile.seconds_per_frame, reproduced on load
      "crashed": false,
      "local_player_index": 0,              # header.local_player_index (raw; -1 unknown)
      "players": [                          # every occupied slot, in replay order
        {"type": "human", "name": "Elendil", "difficulty": null,
         "faction": "FactionAngmar",        # PlayerTemplate code name, null for a lobby Random
         "observer": false,                 # a caster/spectator slot (faction -2)
         "inferred_faction": null,          # a Random's rolled faction, when inferable
         "team": 0, "color": 3, "start_position": 2},
        ...
      ],
      "header": {                           # v2: the recording header's raw surface, verbatim
        "start_time": 1758055192,           # unix seconds, as stored on disk
        "end_time": 1758058844,
        "crc_interval": 100,
        "abnormal_end_frame": null,         # exact value; `crashed` above is its summary
        "reserved1": "<18 hex chars>",      # the raw reserved blocks, hex-encoded
        "filename": "Last Replay",          # the replay's internal name (not the disk name)
        "timestamp": [2025, 9, 16, 2, 22, 39, 52, 0],   # Windows SYSTEMTIME words
        "version": "2.01.2614 ...", "build_date": "...",
        "data_checksum": 305419896,         # the recording patch's INI-tree checksum
        "reserved2": "<10 hex chars>",
        "metadata": "M=387maps/...;S=...;", # the whole key=value; string - map CRC/size,
                                            # seed, GSID, GR, and every slot string verbatim
        "local_player_raw": "0",            # the index as its original ASCII digits
        "unknown_tail": [0, 0, 1, 1, 0, 0],
        "custom_hero_flags": [],            # Create-A-Hero games: per-player flag bytes,
        "custom_heroes": [],                # the raw ALAE2STR blobs (hex), and
        "custom_hero_tail": ""              # the shortened trailing block (hex)
      },
      "chunks": [                           # [timecode, order hex, raw chunk number, args]
        [462, "0x417", 3, [["bool", false], ["int", "AngmarThrallMaster"], ["int", 0]]],
        ...                                 # arg = [tag, value]; a str in an "int" slot is a name
      ]
    }

Version 1 is the same document without `header`; the reader still accepts it. Everything the
analysis pipeline consumes lives outside `header`, so a v1 document loses nothing there - but
only a v2 document carries the raw header a binary re-emission needs, so converting a v1
document to a replay file (`sage_replay.retarget`) asks for a re-translate instead.

`from_dict` and `matches_replay` document their own validation and verification contracts; both
are what let a consumer trust a shared replay+document pair without the recording build, and
`to_replay` rehydrates the document into a `ReplayFile` the rest of `sage_replay` consumes as if
it had parsed the bytes itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sage_replay.aggregate import _faction_from_orders
from sage_replay.narrate import GameData, revive_resolver
from sage_replay.replay import (
    Order,
    OrderArgument,
    OrderArgumentType,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotDifficulty,
    ReplaySlotType,
    ReplayTimestamp,
    first_bool,
    integer_arguments,
)
from sage_replay.stats import compute_stats

__all__ = ["FORMAT", "FORMAT_VERSION", "TranslatedHeader", "TranslatedReplay", "TranslatedSlot"]

# The document magic and schema version. Bump the version when id-space knowledge changes how a
# fresh translation fills the id positions - a new resolvable space, a corrected offset - or when
# the schema gains fields a new capability requires; an analysis-side change (a stats bucketing
# rule, a mod overlay hook) runs at load and leaves every document valid. The reader accepts every
# version it can serve: v1 documents stay fully valid for analysis and only lack the raw `header`
# that binary re-emission (v2) needs.
FORMAT = "sage-replay/translated"
FORMAT_VERSION = 2
_ANALYSIS_VERSIONS = (1, 2)

# The lowercase argument tag stored per `OrderArgumentType`, and its inverse. The tag is the
# whole wire type of an argument: an `int` value under `"int"` is a raw id, a `str` value under
# `"int"` a resolved code name.
_TAG_BY_TYPE = {
    OrderArgumentType.Integer: "int",
    OrderArgumentType.Float: "flt",
    OrderArgumentType.Boolean: "bool",
    OrderArgumentType.ObjectId: "obj",
    OrderArgumentType.Position: "pos",
    OrderArgumentType.ScreenPosition: "spos",
    OrderArgumentType.ScreenRectangle: "srect",
    OrderArgumentType.DrawableId: "draw",
    OrderArgumentType.TeamId: "team",
    OrderArgumentType.Timestamp: "ts",
    OrderArgumentType.WideChar: "wchar",
}
_TYPE_BY_TAG = {tag: arg_type for arg_type, tag in _TAG_BY_TYPE.items()}

# The order types whose first Integer is a `data.object_name` thing-template id (a build
# placement, a mobile-builder construct, a wall segment, a plot unpack/build, and a unit
# recruit/cancel in its flag=False mode).
_THING_ORDERS = {0x419, 0x41A, 0x463, 0x43F}
# The order types whose first Integer is a `data.upgrade` id (a research and its cancel).
_UPGRADE_ORDERS = {0x415, 0x416}
# The special-power casts, whose first Integer is a `data.special_power` id (the second is the
# firing button's Options bitfield and stays raw).
_POWER_ORDERS = {0x410, 0x411, 0x412, 0x456}

# The Unix epoch as the rehydrated header's start time: an arbitrary anchor, chosen so the end
# time carries `num_timecodes * seconds_per_frame` and `ReplayFile.seconds_per_frame` reproduces
# the stored float.
_EPOCH = datetime.fromtimestamp(0, tz=UTC)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _encode_value(arg_type: OrderArgumentType, value: object) -> object:
    """One argument value as a JSON-native scalar/list: a Position's (x, y, z) and the
    screen geometries become lists, a WideChar's two bytes become four hex chars, and every
    other value (int/float/bool) is already JSON-native and passes through."""
    if arg_type is OrderArgumentType.Position:
        return [value[0], value[1], value[2]]  # type: ignore[index]
    if arg_type is OrderArgumentType.ScreenPosition:
        return [value[0], value[1]]  # type: ignore[index]
    if arg_type is OrderArgumentType.ScreenRectangle:
        return list(value)  # type: ignore[call-overload]
    if arg_type is OrderArgumentType.WideChar:
        return value.hex()  # type: ignore[attr-defined]
    return value


def _decode_value(arg_type: OrderArgumentType, value: object) -> object:
    """The inverse of `_encode_value`: rebuild the tuple/bytes shapes `replay.py` produces so a
    rehydrated argument is indistinguishable from a freshly parsed one."""
    if arg_type is OrderArgumentType.Position:
        return (value[0], value[1], value[2])  # type: ignore[index]
    if arg_type is OrderArgumentType.ScreenPosition:
        return (value[0], value[1])  # type: ignore[index]
    if arg_type is OrderArgumentType.ScreenRectangle:
        return tuple(value)  # type: ignore[arg-type]
    if arg_type is OrderArgumentType.WideChar:
        return bytes.fromhex(value)  # type: ignore[arg-type]
    return value


@dataclass(slots=True)
class TranslatedHeader:
    """The recording header's raw, version-coupled surface, kept verbatim (v2 documents only).
    Analysis never reads it; it exists so `sage_replay.retarget` can rebuild a real
    `ReplayHeader` and re-emit a binary replay without the source file. Byte fields
    (`reserved1`, `reserved2`, the custom-hero blobs and tail) are hex-encoded; everything
    else is stored as the parser's own value. `metadata` is the whole `key=value;` string,
    which carries the map identity, seed, GSID, lobby rules, and every slot string - so the
    document needs no per-slot raw copies."""

    start_time: int
    end_time: int
    crc_interval: int
    abnormal_end_frame: int | None
    reserved1: str
    filename: str
    timestamp: tuple[int, ...]
    version: str
    build_date: str
    data_checksum: int
    reserved2: str
    metadata: str
    local_player_raw: str
    unknown_tail: tuple[int, ...]
    custom_hero_flags: tuple[int, ...]
    custom_heroes: tuple[str, ...]
    custom_hero_tail: str

    @classmethod
    def from_header(cls, header: ReplayHeader) -> TranslatedHeader:
        return cls(
            start_time=int(header.start_time.timestamp()),
            end_time=int(header.end_time.timestamp()),
            crc_interval=header.crc_interval,
            abnormal_end_frame=header.abnormal_end_frame,
            reserved1=header.reserved1.hex(),
            filename=header.filename,
            timestamp=(
                header.timestamp.year,
                header.timestamp.month,
                header.timestamp.day_of_week,
                header.timestamp.day,
                header.timestamp.hour,
                header.timestamp.minute,
                header.timestamp.second,
                header.timestamp.millisecond,
            ),
            version=header.version,
            build_date=header.build_date,
            data_checksum=header.data_checksum,
            reserved2=header.reserved2.hex(),
            metadata=header.metadata.raw,
            local_player_raw=header.local_player_raw,
            unknown_tail=header.unknown_tail,
            custom_hero_flags=header.custom_hero_flags,
            custom_heroes=tuple(blob.hex() for blob in header.custom_heroes),
            custom_hero_tail=header.custom_hero_tail.hex(),
        )

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "crc_interval": self.crc_interval,
            "abnormal_end_frame": self.abnormal_end_frame,
            "reserved1": self.reserved1,
            "filename": self.filename,
            "timestamp": list(self.timestamp),
            "version": self.version,
            "build_date": self.build_date,
            "data_checksum": self.data_checksum,
            "reserved2": self.reserved2,
            "metadata": self.metadata,
            "local_player_raw": self.local_player_raw,
            "unknown_tail": list(self.unknown_tail),
            "custom_hero_flags": list(self.custom_hero_flags),
            "custom_heroes": list(self.custom_heroes),
            "custom_hero_tail": self.custom_hero_tail,
        }

    @classmethod
    def from_dict(cls, payload: object) -> TranslatedHeader:
        if not isinstance(payload, dict):
            raise ValueError("translated header must be a JSON object")
        try:
            return cls(
                start_time=payload["start_time"],
                end_time=payload["end_time"],
                crc_interval=payload["crc_interval"],
                abnormal_end_frame=payload["abnormal_end_frame"],
                reserved1=payload["reserved1"],
                filename=payload["filename"],
                timestamp=tuple(payload["timestamp"]),
                version=payload["version"],
                build_date=payload["build_date"],
                data_checksum=payload["data_checksum"],
                reserved2=payload["reserved2"],
                metadata=payload["metadata"],
                local_player_raw=payload["local_player_raw"],
                unknown_tail=tuple(payload["unknown_tail"]),
                custom_hero_flags=tuple(payload["custom_hero_flags"]),
                custom_heroes=tuple(payload["custom_heroes"]),
                custom_hero_tail=payload["custom_hero_tail"],
            )
        except (TypeError, KeyError) as error:
            raise ValueError(f"malformed translated header: missing {error}") from error


@dataclass(slots=True)
class TranslatedSlot:
    """One occupied player slot as the document records it. `faction` is the PlayerTemplate
    code name (`None` for a lobby Random, whose faction the engine rolled at load time);
    `inferred_faction` is that rolled faction when it could be read back from the player's own
    build orders, so the hero roster their recruits index is known on load; `observer` marks a
    caster/spectator slot (faction -2), kept out of stats."""

    type: str  # "human" | "computer"
    name: str | None
    difficulty: str | None  # AI difficulty name, else None
    faction: str | None
    observer: bool
    inferred_faction: str | None
    team: int
    color: int
    start_position: int

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "name": self.name,
            "difficulty": self.difficulty,
            "faction": self.faction,
            "observer": self.observer,
            "inferred_faction": self.inferred_faction,
            "team": self.team,
            "color": self.color,
            "start_position": self.start_position,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> TranslatedSlot:
        try:
            return cls(
                type=payload["type"],
                name=payload.get("name"),
                difficulty=payload.get("difficulty"),
                faction=payload.get("faction"),
                observer=bool(payload.get("observer", False)),
                inferred_faction=payload.get("inferred_faction"),
                team=payload["team"],
                color=payload["color"],
                start_position=payload["start_position"],
            )
        except (TypeError, KeyError) as error:
            raise ValueError(f"malformed translated player slot: missing {error}") from error


@dataclass(slots=True)
class TranslatedReplay:
    """One replay's translated parse - see the module docstring for the schema and the
    portability contract. `size`/`sha256` identify the replay file the document was produced
    from, and `fingerprint` records the patch that recording simulates under; `chunks` is the
    replay-shaped order stream with id positions resolved to code names."""

    replay: str
    size: int
    sha256: str
    fingerprint: str
    game_type: str
    map: str
    num_timecodes: int
    seconds_per_frame: float
    crashed: bool
    local_player_index: int
    # The raw header surface (v2 documents; None when read from a v1 document, which stays
    # analysis-only). See TranslatedHeader.
    header: TranslatedHeader | None = None
    players: list[TranslatedSlot] = field(default_factory=list)
    # Each chunk is [timecode, order type as lowercase hex "0x417", raw chunk number, args],
    # each argument [tag, value] - the raw replay structure, with the id positions the id-space
    # table resolves turned into code-name strings.
    chunks: list[list] = field(default_factory=list)

    @classmethod
    def from_replay(cls, replay_path: Path, replay: ReplayFile, data: GameData) -> TranslatedReplay:
        """Translate a freshly parsed `replay` (read from `replay_path`) against the recording
        build's `data`: resolve every id-bearing Integer argument to its code name, resolve
        fortress-hero recruits/cancels through each player's `ReviveList`, infer a lobby-Random's
        rolled faction from what they built, and keep every other argument raw."""
        stats = {per.player: per for per in compute_stats(replay, data)}
        inferred = _inferred_factions(replay, data, stats)
        players = [_translate_slot(slot, data, inferred) for slot in replay.header.metadata.players]

        spf = replay.seconds_per_frame
        revives: dict = {}
        chunks: list[list] = []
        for chunk in replay.chunks:
            args = [
                [_TAG_BY_TYPE[a.argument_type], _encode_value(a.argument_type, a.value)]
                for a in chunk.order.arguments
            ]
            _translate_ids(replay, chunk, args, data, revives, inferred, spf)
            chunks.append([chunk.timecode, f"0x{chunk.order_type:x}", chunk.number, args])

        stat = replay_path.stat()
        return cls(
            replay=replay_path.name,
            size=stat.st_size,
            sha256=_sha256(replay_path),
            fingerprint=replay.header.patch_fingerprint,
            game_type=replay.game_type.name,
            map=replay.header.metadata.map_file,
            num_timecodes=replay.header.num_timecodes,
            seconds_per_frame=spf,
            crashed=replay.crashed,
            local_player_index=replay.header.local_player_index,
            header=TranslatedHeader.from_header(replay.header),
            players=players,
            chunks=chunks,
        )

    def to_dict(self) -> dict:
        payload = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION if self.header is not None else 1,
            "replay": self.replay,
            "size": self.size,
            "sha256": self.sha256,
            "fingerprint": self.fingerprint,
            "game_type": self.game_type,
            "map": self.map,
            "num_timecodes": self.num_timecodes,
            "seconds_per_frame": self.seconds_per_frame,
            "crashed": self.crashed,
            "local_player_index": self.local_player_index,
            "players": [player.to_dict() for player in self.players],
            "chunks": self.chunks,
        }
        if self.header is not None:
            payload["header"] = self.header.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> TranslatedReplay:
        """The document `payload` describes, or `ValueError` when it is not exactly this schema:
        a wrong or absent magic, a `format_version` outside the supported set (1 loads
        analysis-only with `header=None`; 2 also carries the raw header), a missing top-level
        field, or a malformed chunk or argument entry. Unknown extra keys are ignored, so a
        same-version producer may annotate documents freely."""
        if not isinstance(payload, dict):
            raise ValueError("translated replay document must be a JSON object")
        if payload.get("format") != FORMAT:
            raise ValueError(f"not a {FORMAT} document: format={payload.get('format')!r}")
        version = payload.get("format_version")
        if version not in _ANALYSIS_VERSIONS:
            raise ValueError(f"unsupported format_version {version!r} (reader is {FORMAT_VERSION})")
        for key in (
            "replay",
            "size",
            "sha256",
            "fingerprint",
            "game_type",
            "map",
            "num_timecodes",
            "seconds_per_frame",
            "crashed",
            "local_player_index",
            "players",
            "chunks",
        ):
            if key not in payload:
                raise ValueError(f"translated replay document is missing {key!r}")
        if version == FORMAT_VERSION and "header" not in payload:
            raise ValueError("translated replay document is missing 'header'")
        players = [TranslatedSlot.from_dict(p) for p in payload["players"]]
        chunks = [_validate_chunk(chunk) for chunk in payload["chunks"]]
        header = TranslatedHeader.from_dict(payload["header"]) if "header" in payload else None
        return cls(
            replay=payload["replay"],
            size=payload["size"],
            sha256=payload["sha256"],
            fingerprint=payload["fingerprint"],
            game_type=payload["game_type"],
            map=payload["map"],
            num_timecodes=payload["num_timecodes"],
            seconds_per_frame=payload["seconds_per_frame"],
            crashed=payload["crashed"],
            local_player_index=payload["local_player_index"],
            header=header,
            players=players,
            chunks=chunks,
        )

    def write(self, path: Path) -> None:
        """Serialize to `path` (UTF-8 JSON, compact - the chunk stream dominates the file). The
        caller owns the location; a shared document can go anywhere."""
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: Path) -> TranslatedReplay:
        """Deserialize the document at `path`. Raises `OSError` for an unreadable file and
        `ValueError` for one that isn't a supported translated-replay document."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path.name}: not JSON: {error}") from error
        return cls.from_dict(payload)

    def matches_replay(self, replay_path: Path) -> bool:
        """Whether the file at `replay_path` is the replay this document was produced from:
        size first (a cheap reject), then the content hash. Copying a replay to another
        machine preserves both, so a shared replay+document pair verifies anywhere."""
        try:
            stat = replay_path.stat()
        except OSError:
            return False
        return stat.st_size == self.size and _sha256(replay_path) == self.sha256

    def to_replay(self, data: GameData) -> ReplayFile:
        """Rehydrate into a `ReplayFile` the rest of `sage_replay` consumes unchanged: the id
        positions keep their resolved code-name strings (against `data`, the PAIRED game whose
        templates share those names), slot factions become that game's PlayerTemplate indices,
        and the header carries a wall-clock span that reproduces `seconds_per_frame`. The result
        is flagged `translated`, so `stats.compute_stats` skips the revive-submenu resolver."""
        slots = [_rehydrate_slot(slot, data) for slot in self.players]
        if self.num_timecodes and self.seconds_per_frame:
            end_time = _EPOCH + timedelta(seconds=self.num_timecodes * self.seconds_per_frame)
        else:
            # A crashed/unfinalized recording never had a usable span; the property falls back to
            # its nominal constant, which the stored float already is - leave start == end.
            end_time = _EPOCH
        header = ReplayHeader(
            game_type=ReplayGameType[self.game_type],
            start_time=_EPOCH,
            end_time=end_time,
            num_timecodes=self.num_timecodes,
            filename=self.replay,
            timestamp=ReplayTimestamp(*([0] * 8)),
            version="",
            build_date="",
            metadata=ReplayMetadata(map_file=self.map, slots=slots),
            local_player_index=self.local_player_index,
            abnormal_end_frame=0 if self.crashed else None,
        )
        chunks = [_rehydrate_chunk(chunk) for chunk in self.chunks]
        return ReplayFile(header=header, chunks=chunks, translated=True)


def _translate_slot(slot: ReplaySlot, data: GameData, inferred: dict[str, int]) -> TranslatedSlot:
    """One occupied slot as a `TranslatedSlot`: its faction resolved to the PlayerTemplate code
    name (None for a lobby Random or an observer), with a Random's inferred rolled faction
    attached when one was read from its build orders."""
    in_range = 0 <= slot.faction < len(data.faction_names)
    faction = data.faction_names[slot.faction] if in_range else None
    inferred_id = inferred.get(slot.human_name or "")
    return TranslatedSlot(
        type="human" if slot.slot_type is ReplaySlotType.Human else "computer",
        name=slot.human_name,
        difficulty=slot.computer_difficulty.name if slot.computer_difficulty else None,
        faction=faction,
        observer=slot.is_observer,
        inferred_faction=data.faction_names[inferred_id] if inferred_id is not None else None,
        team=slot.team,
        color=slot.color,
        start_position=slot.start_position,
    )


def _inferred_factions(replay: ReplayFile, data: GameData, stats: dict) -> dict[str, int]:
    """The faction id each lobby-Random human (slot faction -1) actually rolled, read from what
    they built (`aggregate._faction_from_orders`, the same vote the aggregate path uses). Only
    factions the loaded game knows are kept, so the id indexes a real roster."""
    inferred: dict[str, int] = {}
    for slot in replay.header.metadata.players:
        if slot.faction != -1 or not slot.human_name:
            continue
        per = stats.get(slot.human_name)
        if per is None:
            continue
        label = _faction_from_orders(per, data)
        if label is not None and label in data.faction_labels:
            inferred[slot.human_name] = data.faction_labels.index(label)
    return inferred


def _translate_ids(
    replay: ReplayFile,
    chunk: ReplayChunk,
    args: list[list],
    data: GameData,
    revives: dict,
    inferred: dict[str, int],
    spf: float,
) -> None:
    """Resolve the id-bearing Integer positions of one chunk in place: replace the raw int in the
    argument list `args` with its code name where the id-space table resolves, leaving every
    other argument (and any id that failed to resolve) untouched."""
    order = chunk.order_type
    ints = integer_arguments(chunk)
    if not ints:
        return

    if order in (0x417, 0x418):
        if first_bool(chunk):
            # A fortress hero: the id is a revive-submenu position, resolved through the issuing
            # player's ReviveList (recruit on 0x417, cancel on 0x418 - the cancel must still run
            # to keep the list state right even though its name is what gets stored).
            resolver = revive_resolver(revives, replay, chunk, data, inferred)
            name = None
            slot = ints[0]
            if resolver is not None and isinstance(slot, int):
                seconds = chunk.timecode * spf
                if order == 0x417:
                    name = resolver.recruit(seconds, slot)
                else:
                    name = resolver.cancel(seconds, slot)
            if name is not None:
                _set_int(args, 0, name)
        else:
            _set_int(args, 0, data.object_name(ints[0]))
    elif order in _THING_ORDERS:
        _set_int(args, 0, data.object_name(ints[0]))
    elif order in _UPGRADE_ORDERS:
        _set_int(args, 0, data.upgrade(ints[0]))
    elif order in _POWER_ORDERS:
        _set_int(args, 0, data.special_power(ints[0]))
    elif order == 0x414 and len(ints) >= 2:
        # A spellbook purchase: the science is the SECOND Integer (the first is the issuer's
        # chunk number and stays raw).
        _set_int(args, 1, data.science(ints[1]))


def _set_int(args: list[list], which: int, name: str | None) -> None:
    """Replace the value of the `which`-th Integer argument in `args` with the resolved `name`
    (a `str`); a `None` name (an id out of range) leaves the raw int in place."""
    if name is None:
        return
    seen = -1
    for arg in args:
        if arg[0] == "int":
            seen += 1
            if seen == which:
                arg[1] = name
                return


def _rehydrate_slot(slot: TranslatedSlot, data: GameData) -> ReplaySlot:
    """One `TranslatedSlot` as a `ReplaySlot` against the paired game: the faction name becomes
    that game's PlayerTemplate index (the inferred rolled faction when the slot itself carried a
    Random), -2 for an observer, -1 when neither a faction nor an inference is known."""
    if slot.observer:
        faction = ReplaySlot.OBSERVER_FACTION
    elif slot.faction is not None:
        faction = _faction_index(data, slot.faction)
    elif slot.inferred_faction is not None:
        faction = _faction_index(data, slot.inferred_faction)
    else:
        faction = -1
    difficulty = ReplaySlotDifficulty[slot.difficulty] if slot.difficulty else None
    return ReplaySlot(
        slot_type=ReplaySlotType.Human if slot.type == "human" else ReplaySlotType.Computer,
        human_name=slot.name,
        computer_difficulty=difficulty,
        faction=faction,
        team=slot.team,
        color=slot.color,
        start_position=slot.start_position,
    )


def _faction_index(data: GameData, name: str) -> int:
    """The paired game's PlayerTemplate index for the faction code `name`, or -1 when the paired
    game does not carry it (a template renamed across builds falls back to a lobby Random)."""
    try:
        return data.faction_names.index(name)
    except ValueError:
        return -1


def _rehydrate_chunk(chunk: list) -> ReplayChunk:
    """One stored `[timecode, order hex, number, args]` entry as a `ReplayChunk`, its arguments
    rebuilt with their `OrderArgumentType` (a resolved name stays a `str` in its Integer slot)."""
    timecode, order_hex, number, raw_args = chunk
    order_type = int(order_hex, 16)
    order = Order(player_index=number - 1, order_type=order_type)
    for tag, value in raw_args:
        arg_type = _TYPE_BY_TAG[tag]
        order.arguments.append(OrderArgument(arg_type, _decode_value(arg_type, value)))
    return ReplayChunk(timecode=timecode, order_type=order_type, number=number, order=order)


def _validate_chunk(chunk: object) -> list:
    """Check one chunk entry against the wire shape and return it: `[timecode, order hex, number,
    args]` with each argument a `[known tag, value]` pair. Raises `ValueError` on any deviation."""
    if not isinstance(chunk, list) or len(chunk) != 4:
        raise ValueError(f"malformed chunk entry: {chunk!r}")
    _timecode, order_hex, _number, raw_args = chunk
    if not isinstance(order_hex, str):
        raise ValueError(f"chunk order type must be a hex string: {order_hex!r}")
    try:
        int(order_hex, 16)
    except (TypeError, ValueError):
        raise ValueError(f"chunk order type is not a hex string: {order_hex!r}") from None
    if not isinstance(raw_args, list):
        raise ValueError(f"chunk arguments must be a list: {raw_args!r}")
    for arg in raw_args:
        if not isinstance(arg, list) or len(arg) != 2:
            raise ValueError(f"malformed chunk argument: {arg!r}")
        if arg[0] not in _TYPE_BY_TAG:
            raise ValueError(f"unknown chunk argument tag: {arg[0]!r}")
    return chunk
