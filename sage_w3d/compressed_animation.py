"""The W3D compressed animation chunk (`0x00000280`): the same per-pivot channels as
`sage_w3d.animation`'s uncompressed `ANIMATION`, packed far smaller - either time-coded (only
the frames that actually change are stored, each with its own time code) or adaptive-delta
(every frame's value is a small quantized delta from the previous one, decoded through
`sage_w3d.adaptive_delta`). Which shape `COMPRESSED_ANIMATION_CHANNEL` (`0x282`) uses depends on
the header's `flavor`, read earlier in the same container - a channel is only parsed once its
container has already seen a header stating flavor 0 (time-coded) or 1 (adaptive-delta); any
other flavor, or a channel with no header yet, is kept as raw bytes."""

import struct
from dataclasses import dataclass

from sage_w3d import adaptive_delta
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
    W3D_CHUNK_COMPRESSED_ANIMATION,
    W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL,
    W3D_CHUNK_COMPRESSED_ANIMATION_HEADER,
    W3D_CHUNK_COMPRESSED_ANIMATION_MOTION_CHANNEL,
    W3D_CHUNK_COMPRESSED_BIT_CHANNEL,
    UnknownChunk,
    Version,
    W3DDiagnostic,
)

__all__ = [
    "AdaptiveDeltaAnimationChannel",
    "AdaptiveDeltaBlock",
    "AdaptiveDeltaData",
    "CompressedAnimation",
    "CompressedAnimationHeader",
    "MotionAdaptiveDeltaData",
    "MotionChannel",
    "MotionTimeCodedData",
    "MotionTimeCodedDatum",
    "TIME_CODED_FLAVOR",
    "ADAPTIVE_DELTA_FLAVOR",
    "TimeCodedAnimationChannel",
    "TimeCodedBitChannel",
    "TimeCodedBitDatum",
    "TimeCodedDatum",
    "parse_compressed_animation_chunk",
    "write_compressed_animation_chunk",
]

TIME_CODED_FLAVOR = 0
ADAPTIVE_DELTA_FLAVOR = 1

_HEADER_FMT = "<I16s16sIHH"


@dataclass
class CompressedAnimationHeader:
    flagged: bool
    version: Version
    name: FixedString
    hierarchy_name: FixedString
    num_frames: int
    frame_rate: int
    flavor: int

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "CompressedAnimationHeader":
        version_raw, name, hierarchy_name, num_frames, frame_rate, flavor = struct.unpack(
            _HEADER_FMT, payload
        )
        return CompressedAnimationHeader(
            flagged=flagged,
            version=Version.parse(version_raw),
            name=FixedString(raw=name),
            hierarchy_name=FixedString(raw=hierarchy_name),
            num_frames=num_frames,
            frame_rate=frame_rate,
            flavor=flavor,
        )

    def write(self) -> bytes:
        return struct.pack(
            _HEADER_FMT,
            self.version.encode(),
            self.name.raw,
            self.hierarchy_name.raw,
            self.num_frames,
            self.frame_rate,
            self.flavor,
        )


@dataclass
class TimeCodedDatum:
    time_code: int
    interpolated: bool
    value: float | tuple[float, float, float, float]


@dataclass
class TimeCodedAnimationChannel:
    flagged: bool
    pivot: int
    vector_len: int
    channel_type: int
    data: list[TimeCodedDatum]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "TimeCodedAnimationChannel":
        num_time_codes, pivot, vector_len, channel_type = struct.unpack_from("<IHBB", payload, 0)
        offset = 8
        data = []
        for _ in range(num_time_codes):
            (raw_time_code,) = struct.unpack_from("<I", payload, offset)
            offset += 4
            interpolated = bool(raw_time_code & 0x80000000)
            time_code = raw_time_code & 0x7FFFFFFF
            value: float | tuple[float, float, float, float]
            if channel_type == 6:
                value = struct.unpack_from("<4f", payload, offset)
                offset += 16
            else:
                (value,) = struct.unpack_from("<f", payload, offset)
                offset += 4
            data.append(TimeCodedDatum(time_code, interpolated, value))
        if offset != len(payload):
            raise struct.error(
                f"{len(payload) - offset} unconsumed byte(s) in time-coded animation channel"
            )
        return TimeCodedAnimationChannel(flagged, pivot, vector_len, channel_type, data)

    def write(self) -> bytes:
        out = struct.pack("<IHBB", len(self.data), self.pivot, self.vector_len, self.channel_type)
        for datum in self.data:
            raw_time_code = datum.time_code | (0x80000000 if datum.interpolated else 0)
            out += struct.pack("<I", raw_time_code)
            if self.channel_type == 6:
                assert isinstance(datum.value, tuple)
                out += struct.pack("<4f", *datum.value)
            else:
                assert isinstance(datum.value, float)
                out += struct.pack("<f", datum.value)
        return out


@dataclass
class AdaptiveDeltaBlock:
    """One block of `bit_count * 2` quantized per-frame deltas for one vector component, 16
    frames at a time. `delta_bytes` is kept as the exact raw on-disk bytes - decoding them to
    signed deltas (`adaptive_delta._unpack_deltas`) is only needed to compute actual values, not
    to round-trip the chunk."""

    block_index: int
    delta_bytes: bytes

    def write(self) -> bytes:
        return bytes((self.block_index,)) + self.delta_bytes


@dataclass
class AdaptiveDeltaData:
    initial_value: float | tuple[float, float, float, float]
    delta_blocks: list[AdaptiveDeltaBlock]

    def decode(
        self,
        channel_type: int,
        vector_len: int,
        num_time_codes: int,
        scale: float,
        bit_count: int = 4,
    ):
        blocks = [(b.block_index, b.delta_bytes) for b in self.delta_blocks]
        return adaptive_delta.decode(
            channel_type, vector_len, num_time_codes, scale, self.initial_value, blocks, bit_count
        )

    def write(self, channel_type: int) -> bytes:
        if channel_type == 6:
            assert isinstance(self.initial_value, tuple)
            head = struct.pack("<4f", *self.initial_value)
        else:
            assert isinstance(self.initial_value, float)
            head = struct.pack("<f", self.initial_value)
        return head + b"".join(b.write() for b in self.delta_blocks)


def _parse_adaptive_delta_data(
    payload: bytes,
    offset: int,
    channel_type: int,
    num_time_codes: int,
    vector_len: int,
    bit_count: int,
) -> tuple[AdaptiveDeltaData, int]:
    if channel_type == 6:
        initial_value: float | tuple[float, float, float, float] = struct.unpack_from(
            "<4f", payload, offset
        )
        offset += 16
    else:
        (initial_value,) = struct.unpack_from("<f", payload, offset)
        offset += 4

    block_count = ((num_time_codes + 15) >> 4) * vector_len
    block_size = 1 + bit_count * 2
    blocks = []
    for _ in range(block_count):
        if offset + block_size > len(payload):
            raise struct.error("adaptive delta block truncated")
        block_index = payload[offset]
        delta_bytes = payload[offset + 1 : offset + block_size]
        blocks.append(AdaptiveDeltaBlock(block_index, delta_bytes))
        offset += block_size
    return AdaptiveDeltaData(initial_value, blocks), offset


@dataclass
class AdaptiveDeltaAnimationChannel:
    """`padding` is the 3 trailing bytes the format reserves after every channel; stored raw
    rather than assumed zero (the same caution as `AABBTreeHeader.padding`)."""

    flagged: bool
    num_time_codes: int
    pivot: int
    vector_len: int
    channel_type: int
    scale: float
    data: AdaptiveDeltaData
    padding: bytes

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "AdaptiveDeltaAnimationChannel":
        num_time_codes, pivot, vector_len, channel_type, scale = struct.unpack_from(
            "<IHBBf", payload, 0
        )
        data, offset = _parse_adaptive_delta_data(
            payload, 12, channel_type, num_time_codes, vector_len, 4
        )
        padding = payload[offset : offset + 3]
        if len(padding) != 3:
            raise struct.error("adaptive delta animation channel missing its 3-byte trailing pad")
        if offset + 3 != len(payload):
            extra = len(payload) - offset - 3
            raise struct.error(f"{extra} unconsumed byte(s) in adaptive delta animation channel")
        return AdaptiveDeltaAnimationChannel(
            flagged, num_time_codes, pivot, vector_len, channel_type, scale, data, padding
        )

    def write(self) -> bytes:
        header = struct.pack(
            "<IHBBf",
            self.num_time_codes,
            self.pivot,
            self.vector_len,
            self.channel_type,
            self.scale,
        )
        return header + self.data.write(self.channel_type) + self.padding


@dataclass
class TimeCodedBitDatum:
    time_code: int
    value: bool


@dataclass
class TimeCodedBitChannel:
    flagged: bool
    pivot: int
    channel_type: int
    default_value: int
    data: list[TimeCodedBitDatum]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "TimeCodedBitChannel":
        num_time_codes, pivot, channel_type, default_value = struct.unpack_from("<IHBB", payload, 0)
        offset = 8
        data = []
        for _ in range(num_time_codes):
            (raw,) = struct.unpack_from("<I", payload, offset)
            offset += 4
            data.append(TimeCodedBitDatum(raw & 0x7FFFFFFF, bool(raw & 0x80000000)))
        if offset != len(payload):
            raise struct.error(
                f"{len(payload) - offset} unconsumed byte(s) in time-coded bit channel"
            )
        return TimeCodedBitChannel(flagged, pivot, channel_type, default_value, data)

    def write(self) -> bytes:
        out = struct.pack(
            "<IHBB", len(self.data), self.pivot, self.channel_type, self.default_value
        )
        for datum in self.data:
            raw = datum.time_code | (0x80000000 if datum.value else 0)
            out += struct.pack("<I", raw)
        return out


@dataclass
class MotionTimeCodedDatum:
    time_code: int
    value: float | tuple[float, float, float, float]


@dataclass
class MotionTimeCodedData:
    """`pad` is the 2-byte alignment gap the format inserts between the time-code array and the
    value array when `len(data)` is odd (so the value array starts on a 4-byte boundary); stored
    raw rather than assumed zero."""

    data: list[MotionTimeCodedDatum]
    pad: bytes


@dataclass
class MotionAdaptiveDeltaData:
    scale: float
    data: AdaptiveDeltaData


@dataclass
class MotionChannel:
    """The `COMPRESSED_ANIMATION_MOTION_CHANNEL` leaf. `zero_byte` is a leading byte the format
    reserves (conventionally 0); stored raw rather than discarded. `body` is time-coded data
    when `delta_type == 0`, or a scaled adaptive-delta block otherwise (`delta_type * 4` is the
    adaptive-delta bit count)."""

    flagged: bool
    zero_byte: int
    delta_type: int
    vector_len: int
    channel_type: int
    num_time_codes: int
    pivot: int
    body: MotionTimeCodedData | MotionAdaptiveDeltaData

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "MotionChannel":
        zero_byte, delta_type, vector_len, channel_type = struct.unpack_from("<4B", payload, 0)
        num_time_codes, pivot = struct.unpack_from("<hh", payload, 4)
        offset = 8
        body: MotionTimeCodedData | MotionAdaptiveDeltaData
        if delta_type == 0:
            time_codes = []
            for _ in range(num_time_codes):
                (tc,) = struct.unpack_from("<h", payload, offset)
                offset += 2
                time_codes.append(tc)
            if num_time_codes % 2 != 0:
                pad = payload[offset : offset + 2]
                if len(pad) != 2:
                    raise struct.error("motion channel missing its 2-byte alignment pad")
                offset += 2
            else:
                pad = b""
            data = []
            for tc in time_codes:
                value: float | tuple[float, float, float, float]
                if channel_type == 6:
                    value = struct.unpack_from("<4f", payload, offset)
                    offset += 16
                else:
                    (value,) = struct.unpack_from("<f", payload, offset)
                    offset += 4
                data.append(MotionTimeCodedDatum(tc, value))
            body = MotionTimeCodedData(data=data, pad=pad)
        else:
            bit_count = delta_type * 4
            (scale,) = struct.unpack_from("<f", payload, offset)
            offset += 4
            adata, offset = _parse_adaptive_delta_data(
                payload, offset, channel_type, num_time_codes, vector_len, bit_count
            )
            body = MotionAdaptiveDeltaData(scale=scale, data=adata)

        if offset != len(payload):
            raise struct.error(f"{len(payload) - offset} unconsumed byte(s) in motion channel")
        return MotionChannel(
            flagged, zero_byte, delta_type, vector_len, channel_type, num_time_codes, pivot, body
        )

    def write(self) -> bytes:
        header = struct.pack(
            "<4Bhh",
            self.zero_byte,
            self.delta_type,
            self.vector_len,
            self.channel_type,
            self.num_time_codes,
            self.pivot,
        )
        if isinstance(self.body, MotionTimeCodedData):
            out = header
            for datum in self.body.data:
                out += struct.pack("<h", datum.time_code)
            out += self.body.pad
            for datum in self.body.data:
                if self.channel_type == 6:
                    assert isinstance(datum.value, tuple)
                    out += struct.pack("<4f", *datum.value)
                else:
                    assert isinstance(datum.value, float)
                    out += struct.pack("<f", datum.value)
            return out
        return header + struct.pack("<f", self.body.scale) + self.body.data.write(self.channel_type)


CompressedAnimationChunk = (
    CompressedAnimationHeader
    | TimeCodedAnimationChannel
    | AdaptiveDeltaAnimationChannel
    | TimeCodedBitChannel
    | MotionChannel
    | UnknownChunk
)


@dataclass
class CompressedAnimation:
    flagged: bool
    chunks: list[CompressedAnimationChunk]

    @property
    def header(self) -> CompressedAnimationHeader | None:
        return first_of(self.chunks, CompressedAnimationHeader)

    @property
    def name(self) -> str:
        h = self.header
        return h.name.value if h is not None else ""

    @property
    def time_coded_channels(self) -> list[TimeCodedAnimationChannel]:
        return all_of(self.chunks, TimeCodedAnimationChannel)

    @property
    def adaptive_delta_channels(self) -> list[AdaptiveDeltaAnimationChannel]:
        return all_of(self.chunks, AdaptiveDeltaAnimationChannel)

    @property
    def bit_channels(self) -> list[TimeCodedBitChannel]:
        return all_of(self.chunks, TimeCodedBitChannel)

    @property
    def motion_channels(self) -> list[MotionChannel]:
        return all_of(self.chunks, MotionChannel)


def _parse_compressed_animation_child(
    entry: ChunkEntry, base_offset: int, flavor: int | None, diagnostics: list[W3DDiagnostic]
) -> CompressedAnimationChunk:
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_COMPRESSED_ANIMATION_HEADER:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: CompressedAnimationHeader.parse(entry.flagged, p),
            CompressedAnimationHeader.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL and flavor == TIME_CODED_FLAVOR:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: TimeCodedAnimationChannel.parse(entry.flagged, p),
            TimeCodedAnimationChannel.write,
            diagnostics,
        )
    if (
        entry.chunk_type == W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL
        and flavor == ADAPTIVE_DELTA_FLAVOR
    ):
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: AdaptiveDeltaAnimationChannel.parse(entry.flagged, p),
            AdaptiveDeltaAnimationChannel.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_COMPRESSED_BIT_CHANNEL:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: TimeCodedBitChannel.parse(entry.flagged, p),
            TimeCodedBitChannel.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_COMPRESSED_ANIMATION_MOTION_CHANNEL:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: MotionChannel.parse(entry.flagged, p),
            MotionChannel.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def parse_compressed_animation_chunk(
    payload: bytes, flagged: bool, header_offset: int, diagnostics: list[W3DDiagnostic]
):
    entries = split_or_degrade(
        W3D_CHUNK_COMPRESSED_ANIMATION, flagged, payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(W3D_CHUNK_COMPRESSED_ANIMATION, flagged, payload)

    payload_offset = header_offset + 8
    chunks: list[CompressedAnimationChunk] = []
    flavor: int | None = None
    for e in entries:
        child = _parse_compressed_animation_child(e, payload_offset, flavor, diagnostics)
        if isinstance(child, CompressedAnimationHeader):
            flavor = child.flavor
        chunks.append(child)

    return CompressedAnimation(flagged=flagged, chunks=chunks)


def _write_compressed_animation_child(chunk: CompressedAnimationChunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, CompressedAnimationHeader):
        return write_chunk(W3D_CHUNK_COMPRESSED_ANIMATION_HEADER, chunk.flagged, chunk.write())
    if isinstance(chunk, TimeCodedAnimationChannel):
        return write_chunk(W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL, chunk.flagged, chunk.write())
    if isinstance(chunk, AdaptiveDeltaAnimationChannel):
        return write_chunk(W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL, chunk.flagged, chunk.write())
    if isinstance(chunk, TimeCodedBitChannel):
        return write_chunk(W3D_CHUNK_COMPRESSED_BIT_CHANNEL, chunk.flagged, chunk.write())
    if isinstance(chunk, MotionChannel):
        return write_chunk(
            W3D_CHUNK_COMPRESSED_ANIMATION_MOTION_CHANNEL, chunk.flagged, chunk.write()
        )
    raise TypeError(f"unwritable compressed animation chunk: {chunk!r}")


def write_compressed_animation_chunk(animation: CompressedAnimation) -> bytes:
    payload = b"".join(_write_compressed_animation_child(c) for c in animation.chunks)
    return write_chunk(W3D_CHUNK_COMPRESSED_ANIMATION, animation.flagged, payload)
