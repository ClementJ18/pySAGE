"""The W3D uncompressed animation chunk (`0x00000200`): a header plus one channel per animated
pivot property - a flat float array for translation/quaternion channels (`ANIMATION_CHANNEL`) or
a packed bit array for a visibility channel (`ANIMATION_BIT_CHANNEL`)."""

import struct
from dataclasses import dataclass

from sage_w3d.binary import (
    ChunkEntry,
    FixedString,
    all_of,
    first_of,
    parse_leaf,
    split_or_degrade,
    write_chunk,
)
from sage_w3d.chunks import (
    W3D_CHUNK_ANIMATION,
    W3D_CHUNK_ANIMATION_BIT_CHANNEL,
    W3D_CHUNK_ANIMATION_CHANNEL,
    W3D_CHUNK_ANIMATION_HEADER,
    UnknownChunk,
    Version,
    W3DDiagnostic,
)

__all__ = [
    "Animation",
    "AnimationBitChannel",
    "AnimationChannel",
    "AnimationHeader",
    "parse_animation_chunk",
    "write_animation_chunk",
]

_ANIMATION_HEADER_FMT = "<I16s16s2I"


@dataclass
class AnimationHeader:
    flagged: bool
    version: Version
    name: FixedString
    hierarchy_name: FixedString
    num_frames: int
    frame_rate: int

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "AnimationHeader":
        version_raw, name, hierarchy_name, num_frames, frame_rate = struct.unpack(
            _ANIMATION_HEADER_FMT, payload
        )
        return AnimationHeader(
            flagged=flagged,
            version=Version.parse(version_raw),
            name=FixedString(raw=name),
            hierarchy_name=FixedString(raw=hierarchy_name),
            num_frames=num_frames,
            frame_rate=frame_rate,
        )

    def write(self) -> bytes:
        return struct.pack(
            _ANIMATION_HEADER_FMT,
            self.version.encode(),
            self.name.raw,
            self.hierarchy_name.raw,
            self.num_frames,
            self.frame_rate,
        )


@dataclass
class AnimationChannel:
    """A translation or rotation channel. `data` is the flat `(last_frame - first_frame + 1) *
    vector_len` float array exactly as stored - grouped into `vector_len`-tuples by `.values`
    (a quaternion, in file order x, y, z, w, when `vector_len == 4`). `pad` is the u16
    immediately after `pivot`; real exporters do not always leave it zero (hazard), so it is
    kept as read rather than assumed."""

    flagged: bool
    first_frame: int
    last_frame: int
    vector_len: int
    channel_type: int
    pivot: int
    pad: int
    data: list[float]
    trailing: bytes

    @property
    def values(self) -> list[tuple[float, ...]]:
        n = self.vector_len
        if n <= 0:
            return []
        return [tuple(self.data[i : i + n]) for i in range(0, len(self.data), n)]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "AnimationChannel":
        first_frame, last_frame, vector_len, channel_type, pivot, pad = struct.unpack_from(
            "<6H", payload, 0
        )
        count = (last_frame - first_frame + 1) * vector_len
        data_size = count * 4
        if 12 + data_size > len(payload):
            raise struct.error("animation channel payload too short for its declared frame range")
        data = list(struct.unpack_from(f"<{count}f", payload, 12)) if count else []
        trailing = payload[12 + data_size :]
        return AnimationChannel(
            flagged, first_frame, last_frame, vector_len, channel_type, pivot, pad, data, trailing
        )

    def write(self) -> bytes:
        header = struct.pack(
            "<6H",
            self.first_frame,
            self.last_frame,
            self.vector_len,
            self.channel_type,
            self.pivot,
            self.pad,
        )
        body = struct.pack(f"<{len(self.data)}f", *self.data) if self.data else b""
        return header + body + self.trailing


@dataclass
class AnimationBitChannel:
    """A visibility channel: a packed bit per frame. `default_raw` and `bits` are the raw
    on-disk byte and bit-packed array - not the divided float / `list[bool]` a naive transcription
    would expose - because re-deriving them (`raw/255`, then `round(value*255)`) does not always
    recover the original byte, and any never-written high bits in the last packed byte would
    silently reset to 0. `.default`/`.values` compute the friendlier form on demand."""

    flagged: bool
    first_frame: int
    last_frame: int
    channel_type: int
    pivot: int
    default_raw: int
    bits: bytes

    @property
    def default(self) -> float:
        return self.default_raw / 255

    @property
    def values(self) -> list[bool]:
        n = self.last_frame - self.first_frame + 1
        return [bool(self.bits[i // 8] & (1 << (i % 8))) for i in range(n)]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "AnimationBitChannel":
        first_frame, last_frame, channel_type, pivot, default_raw = struct.unpack_from(
            "<4HB", payload, 0
        )
        n = last_frame - first_frame + 1
        nbytes = (n + 7) // 8
        bits = payload[9 : 9 + nbytes]
        if len(bits) != nbytes:
            raise struct.error(
                "animation bit channel payload too short for its declared frame range"
            )
        return AnimationBitChannel(
            flagged, first_frame, last_frame, channel_type, pivot, default_raw, bits
        )

    def write(self) -> bytes:
        header = struct.pack(
            "<4HB",
            self.first_frame,
            self.last_frame,
            self.channel_type,
            self.pivot,
            self.default_raw,
        )
        return header + self.bits


AnimationChunk = AnimationHeader | AnimationChannel | AnimationBitChannel | UnknownChunk


@dataclass
class Animation:
    flagged: bool
    chunks: list[AnimationChunk]

    @property
    def header(self) -> AnimationHeader | None:
        return first_of(self.chunks, AnimationHeader)

    @property
    def name(self) -> str:
        h = self.header
        return h.name.value if h is not None else ""

    @property
    def channels(self) -> list[AnimationChannel]:
        return all_of(self.chunks, AnimationChannel)

    @property
    def bit_channels(self) -> list[AnimationBitChannel]:
        return all_of(self.chunks, AnimationBitChannel)


def _parse_animation_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
) -> AnimationChunk:
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_ANIMATION_HEADER:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: AnimationHeader.parse(entry.flagged, p),
            AnimationHeader.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_ANIMATION_CHANNEL:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: AnimationChannel.parse(entry.flagged, p),
            AnimationChannel.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_ANIMATION_BIT_CHANNEL:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: AnimationBitChannel.parse(entry.flagged, p),
            AnimationBitChannel.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _write_animation_child(chunk: AnimationChunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, AnimationHeader):
        return write_chunk(W3D_CHUNK_ANIMATION_HEADER, chunk.flagged, chunk.write())
    if isinstance(chunk, AnimationChannel):
        return write_chunk(W3D_CHUNK_ANIMATION_CHANNEL, chunk.flagged, chunk.write())
    if isinstance(chunk, AnimationBitChannel):
        return write_chunk(W3D_CHUNK_ANIMATION_BIT_CHANNEL, chunk.flagged, chunk.write())
    raise TypeError(f"unwritable animation chunk: {chunk!r}")


def parse_animation_chunk(
    payload: bytes, flagged: bool, header_offset: int, diagnostics: list[W3DDiagnostic]
):
    entries = split_or_degrade(W3D_CHUNK_ANIMATION, flagged, payload, header_offset, diagnostics)
    if entries is None:
        return UnknownChunk(W3D_CHUNK_ANIMATION, flagged, payload)
    payload_offset = header_offset + 8
    chunks = [_parse_animation_child(e, payload_offset, diagnostics) for e in entries]
    return Animation(flagged=flagged, chunks=chunks)


def write_animation_chunk(animation: Animation) -> bytes:
    payload = b"".join(_write_animation_child(c) for c in animation.chunks)
    return write_chunk(W3D_CHUNK_ANIMATION, animation.flagged, payload)
