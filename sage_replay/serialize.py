"""Byte-exact writer for BFME2 / RotWK replay files - the inverse of `replay.py`'s parser.

`serialize_replay` re-emits a parsed `ReplayFile` as the bytes the engine would have written:
`parse_replay(serialize_replay(parse_replay(data))) == parse_replay(data)` structurally, and
`serialize_replay(parse_replay(data)) == data` byte-for-byte across the fixture corpus (the
acceptance gate in `tests/sage_replay/test_serialize.py`). Byte-exactness is what proves the
format knowledge is complete - any byte the parser dropped would surface as a diff here.

Only the BFME2 layout is written: every corpus fixture is a `.BfME2Replay`, so the Generals and
BFME1 write paths would be unverifiable guesses. A `ReplayFile` rehydrated from a translated
document (`translated=True`) is refused - its id positions hold code-name strings, not the
integers the wire format needs; run it through `sage_replay.retarget` first to resolve them
against a target game.
"""

from __future__ import annotations

from io import BytesIO
from itertools import groupby
from pathlib import Path

from sage_replay.replay import (
    OrderArgument,
    OrderArgumentType,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
)
from sage_utils.stream import BinaryStream

__all__ = ["serialize_replay", "write_replay"]

# The finalized-recording sentinel for the abnormal-end field (see ReplayHeader).
_FINALIZED_SENTINEL = 0xFFFFFFFF

# A chunk's (type, count) pairs carry the count as one byte; a run longer than this must be
# split across pairs. No corpus chunk does, so a split (255-sized runs) is structural.
_MAX_RUN = 0xFF


def serialize_replay(replay: ReplayFile) -> bytes:
    """The replay re-encoded as `.BfME2Replay` bytes. Raises `ValueError` for a non-BFME2
    replay (the only corpus-verifiable layout) and for a translated replay, whose id
    positions hold resolved names instead of wire integers."""
    if replay.game_type is not ReplayGameType.Bfme2:
        raise ValueError(f"can only serialize Bfme2 replays, not {replay.game_type.name}")
    if replay.translated:
        raise ValueError(
            "cannot serialize a translated replay: its id positions hold code names, "
            "not integers - retarget it against a game first (sage_replay.retarget)"
        )
    stream = BinaryStream(BytesIO())
    _write_header(stream, replay.header)
    for chunk in replay.chunks:
        _write_chunk(stream, chunk)
    return stream.getvalue()


def write_replay(replay: ReplayFile, path: Path) -> None:
    """Serialize `replay` to `path`."""
    path.write_bytes(serialize_replay(replay))


def _write_header(stream: BinaryStream, header: ReplayHeader) -> None:
    """The header in the exact field order of `ReplayHeader.parse`'s BFME2 branch."""
    stream.writeBytes(b"BFME2RPL")
    stream.writeUInt32(int(header.start_time.timestamp()))
    stream.writeUInt32(int(header.end_time.timestamp()))
    stream.writeUInt32(header.num_timecodes)
    stream.writeUInt32(header.crc_interval)
    abnormal = header.abnormal_end_frame
    stream.writeUInt32(_FINALIZED_SENTINEL if abnormal is None else abnormal)
    stream.writeBytes(_sized(header.reserved1, 9, "reserved1"))
    stream.writeNullTerminatedUnicodeString(header.filename)
    for word in (
        header.timestamp.year,
        header.timestamp.month,
        header.timestamp.day_of_week,
        header.timestamp.day,
        header.timestamp.hour,
        header.timestamp.minute,
        header.timestamp.second,
        header.timestamp.millisecond,
    ):
        stream.writeUInt16(word)
    stream.writeNullTerminatedUnicodeString(header.version)
    stream.writeNullTerminatedUnicodeString(header.build_date)
    stream.writeUInt32(header.data_checksum)
    stream.writeBytes(_sized(header.reserved2, 5, "reserved2"))
    stream.writeNullTerminatedAsciiString(header.metadata.raw)
    stream.writeNullTerminatedAsciiString(header.local_player_raw)

    if header.custom_hero_flags:
        # The Create-A-Hero extension: the flag byte vector interleaved with each flagged
        # player's blob, then the shortened raw tail (see ReplayHeader.custom_heroes).
        if sum(1 for flag in header.custom_hero_flags if flag == 1) != len(header.custom_heroes):
            raise ValueError("custom_hero_flags does not match the number of custom_heroes blobs")
        blobs = iter(header.custom_heroes)
        for flag in header.custom_hero_flags:
            stream.writeUChar(flag)
            if flag == 1:
                blob = next(blobs)
                stream.writeUInt32(len(blob))
                stream.writeBytes(blob)
        stream.writeBytes(header.custom_hero_tail)
    else:
        for word in header.unknown_tail:
            stream.writeUInt32(word)


def _sized(value: bytes, length: int, name: str) -> bytes:
    if len(value) != length:
        raise ValueError(f"{name} must be exactly {length} bytes, got {len(value)}")
    return value


def _write_chunk(stream: BinaryStream, chunk: ReplayChunk) -> None:
    """One chunk in `ReplayChunk.parse` order: the ids, then the (type, count) pairs, then
    every argument value in pair order. The parser flattens the pairs into one argument
    list, so the partition is rebuilt here by run-length over consecutive same-type
    arguments - the corpus round-trip gate is what proves the engine writes the same one."""
    stream.writeUInt32(chunk.timecode)
    stream.writeUInt32(chunk.order_type)
    stream.writeUInt32(chunk.number)

    runs: list[tuple[OrderArgumentType, list[OrderArgument]]] = []
    for argument_type, group in groupby(chunk.order.arguments, key=lambda a: a.argument_type):
        arguments = list(group)
        while len(arguments) > _MAX_RUN:
            runs.append((argument_type, arguments[:_MAX_RUN]))
            arguments = arguments[_MAX_RUN:]
        runs.append((argument_type, arguments))

    stream.writeUChar(len(runs))
    for argument_type, arguments in runs:
        stream.writeUChar(argument_type.value)
        stream.writeUChar(len(arguments))
    for _, arguments in runs:
        for argument in arguments:
            _write_argument(stream, argument)


def _write_argument(stream: BinaryStream, argument: OrderArgument) -> None:
    """One argument value, the exact inverse of `replay._read_argument`."""
    value = argument.value
    match argument.argument_type:
        case OrderArgumentType.Integer:
            if not isinstance(value, int):
                raise ValueError(f"Integer argument holds {value!r} - a translated name?")
            stream.writeInt32(value)
        case OrderArgumentType.Float:
            stream.writeFloat(value)  # type: ignore[arg-type]
        case OrderArgumentType.Boolean:
            stream.writeBoolChecked(value)  # type: ignore[arg-type]
        case (
            OrderArgumentType.ObjectId
            | OrderArgumentType.DrawableId
            | OrderArgumentType.TeamId
            | OrderArgumentType.Timestamp
        ):
            stream.writeUInt32(value)  # type: ignore[arg-type]
        case OrderArgumentType.Position:
            stream.writeVector3(value)  # type: ignore[arg-type]
        case OrderArgumentType.ScreenPosition:
            stream.writeInt32(value[0])  # type: ignore[index]
            stream.writeInt32(value[1])  # type: ignore[index]
        case OrderArgumentType.ScreenRectangle:
            for word in value:  # type: ignore[attr-defined]
                stream.writeInt32(word)
        case OrderArgumentType.WideChar:
            stream.writeBytes(_sized(value, 2, "WideChar"))  # type: ignore[arg-type]
