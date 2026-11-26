"""The EA movie container that BFME's `.vp6` files use.

A file is a flat run of chunks, each a 4-byte tag, a little-endian uint32 size that counts the
8-byte chunk header, and the payload. An opaque movie is an `MVhd` header chunk followed by one
`MV0K` (keyframe) or `MV0F` (inter frame) chunk per frame. A movie with an alpha channel opens
with an empty `AVP6` chunk and carries a second, alpha-only VP6 stream beside the first: an
`AVhd` header and `AV0K`/`AV0F` frames, interleaved with the colour ones.

The header payload is the codec fourcc (`vp60`, or `vp61` when the stream uses the VP6.1 tools),
uint16 width and height, uint32 frame count, uint32 size of the largest frame payload, and the
frame rate as a uint32 rate / scale pair (25 / 1, or 983019 / 32767 for 30 fps).

Every chunk is kept as raw bytes, so a movie round-trips byte-for-byte through `read_movie` and
`write_movie`.
"""

import struct
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ALPHA_FLAG_TAG",
    "Chunk",
    "Frame",
    "FrameHeader",
    "Movie",
    "StreamHeader",
    "Vp6FormatError",
    "build_movie",
    "parse_frame_header",
    "read_movie",
    "read_movie_from_path",
    "write_movie",
]

ALPHA_FLAG_TAG = b"AVP6"
_HEADER_TAGS = {b"MVhd": False, b"AVhd": True}
_FRAME_TAGS = {b"MV0K": (False, True), b"MV0F": (False, False)}
_ALPHA_FRAME_TAGS = {b"AV0K": (True, True), b"AV0F": (True, False)}
_HEADER = struct.Struct("<4sHHIIII")


class Vp6FormatError(ValueError):
    """The bytes are not a well-formed EA VP6 movie."""


@dataclass(frozen=True, slots=True)
class Chunk:
    tag: bytes
    payload: bytes

    @property
    def size(self) -> int:
        """The chunk's size field: payload plus the 8-byte chunk header."""
        return len(self.payload) + 8


@dataclass(frozen=True, slots=True)
class StreamHeader:
    """The payload of an `MVhd` (or `AVhd`) chunk."""

    codec: bytes
    width: int
    height: int
    frame_count: int
    largest_frame: int
    rate: int
    scale: int

    @property
    def fps(self) -> float:
        return self.rate / self.scale if self.scale else 0.0

    @classmethod
    def unpack(cls, payload: bytes) -> "StreamHeader":
        if len(payload) < _HEADER.size:
            raise Vp6FormatError(f"stream header is {len(payload)} bytes, expected 24")
        return cls(*_HEADER.unpack_from(payload))

    def pack(self) -> bytes:
        return _HEADER.pack(
            self.codec,
            self.width,
            self.height,
            self.frame_count,
            self.largest_frame,
            self.rate,
            self.scale,
        )


@dataclass(frozen=True, slots=True)
class Frame:
    keyframe: bool
    payload: bytes


@dataclass(frozen=True, slots=True)
class Movie:
    chunks: tuple[Chunk, ...]

    def _header(self, alpha: bool) -> StreamHeader | None:
        for chunk in self.chunks:
            if _HEADER_TAGS.get(chunk.tag) is alpha:
                return StreamHeader.unpack(chunk.payload)
        return None

    @property
    def header(self) -> StreamHeader:
        header = self._header(alpha=False)
        if header is None:
            raise Vp6FormatError("no MVhd header chunk")
        return header

    @property
    def alpha_header(self) -> StreamHeader | None:
        return self._header(alpha=True)

    @property
    def has_alpha(self) -> bool:
        return any(chunk.tag == ALPHA_FLAG_TAG for chunk in self.chunks)

    def frames(self, alpha: bool = False) -> list[Frame]:
        """The colour frames in order, or the alpha stream's with `alpha`."""
        tags = _ALPHA_FRAME_TAGS if alpha else _FRAME_TAGS
        return [
            Frame(keyframe=tags[chunk.tag][1], payload=chunk.payload)
            for chunk in self.chunks
            if chunk.tag in tags
        ]


def read_movie(data: bytes) -> Movie:
    chunks = []
    pos = 0
    while pos < len(data):
        if pos + 8 > len(data):
            raise Vp6FormatError(f"truncated chunk header at byte {pos}")
        tag = data[pos : pos + 4]
        (size,) = struct.unpack_from("<I", data, pos + 4)
        if size < 8 or pos + size > len(data):
            raise Vp6FormatError(f"chunk {tag!r} at byte {pos} has bad size {size}")
        chunks.append(Chunk(tag, data[pos + 8 : pos + size]))
        pos += size
    movie = Movie(tuple(chunks))
    movie.header  # noqa: B018 - a movie without a stream header is not a movie
    return movie


def read_movie_from_path(path: str | Path) -> Movie:
    return read_movie(Path(path).read_bytes())


def write_movie(movie: Movie) -> bytes:
    out = bytearray()
    for chunk in movie.chunks:
        out += chunk.tag + struct.pack("<I", chunk.size) + chunk.payload
    return bytes(out)


def build_movie(
    frames: list[Frame],
    width: int,
    height: int,
    rate: int,
    scale: int = 1,
    alpha: list[Frame] | None = None,
) -> Movie:
    """A movie of `frames`, with its header filled in from them. With `alpha` (one frame per
    colour frame, a VP6 stream whose luma is the matte: 16 transparent, 235 opaque) it is an
    alpha movie laid out as EA's are: both headers alike, each alpha frame before its colour
    frame, and the largest-frame field counting the chunk header."""
    if alpha is not None and len(alpha) != len(frames):
        raise ValueError(f"{len(frames)} colour frames but {len(alpha)} alpha frames")
    largest = max((len(frame.payload) for frame in [*frames, *(alpha or [])]), default=0)
    header = StreamHeader(
        codec=b"vp60",
        width=width,
        height=height,
        frame_count=len(frames),
        largest_frame=largest + 8 if alpha is not None else largest,
        rate=rate,
        scale=scale,
    )
    if alpha is None:
        chunks = [Chunk(b"MVhd", header.pack())]
        chunks += [Chunk(b"MV0K" if f.keyframe else b"MV0F", f.payload) for f in frames]
        return Movie(tuple(chunks))
    chunks = [
        Chunk(ALPHA_FLAG_TAG, b""),
        Chunk(b"MVhd", header.pack()),
        Chunk(b"AVhd", header.pack()),
    ]
    for colour, matte in zip(frames, alpha, strict=True):
        chunks.append(Chunk(b"AV0K" if matte.keyframe else b"AV0F", matte.payload))
        chunks.append(Chunk(b"MV0K" if colour.keyframe else b"MV0F", colour.payload))
    return Movie(tuple(chunks))


@dataclass(frozen=True, slots=True)
class FrameHeader:
    """The plain bytes at the head of a VP6 frame, before its range-coded partitions.

    `sub_version`, `filter_header` and the macroblock counts are only stored in keyframes; an
    inter frame carries `None` there and takes them from the keyframe before it. `coeff_offset`
    is where the coefficient partition starts, counted from the start of the frame, or 0 when
    the coefficients share the first partition.
    """

    keyframe: bool
    quantizer: int
    separated_coeff: bool
    coeff_offset: int
    data_start: int
    sub_version: int | None = None
    filter_header: int | None = None
    interlaced: bool = False
    mb_rows: int | None = None
    mb_cols: int | None = None
    display_rows: int | None = None
    display_cols: int | None = None


def parse_frame_header(payload: bytes, filter_header: int = 0) -> FrameHeader:
    """The header of one frame. `filter_header` is the stream's, from its last keyframe; an
    inter frame stores its coefficient offset only when the stream has none or the frame's
    coefficients are separated."""
    if len(payload) < 3:
        raise Vp6FormatError(f"frame is only {len(payload)} bytes")
    first = payload[0]
    keyframe = not first & 0x80
    quantizer = (first >> 1) & 0x3F
    separated = bool(first & 1)
    if keyframe:
        sub_version = payload[1] >> 3
        filter_header = payload[1] & 0x06
        pos = 2
        coeff_offset = 0
        if separated or not filter_header:
            coeff_offset = struct.unpack_from(">H", payload, pos)[0]
            pos += 2
        if len(payload) < pos + 4:
            raise Vp6FormatError("keyframe header is truncated")
        rows, cols, display_rows, display_cols = payload[pos : pos + 4]
        return FrameHeader(
            keyframe=True,
            quantizer=quantizer,
            separated_coeff=separated,
            coeff_offset=coeff_offset,
            data_start=pos + 4,
            sub_version=sub_version,
            filter_header=filter_header,
            interlaced=bool(payload[1] & 1),
            mb_rows=rows,
            mb_cols=cols,
            display_rows=display_rows,
            display_cols=display_cols,
        )
    coeff_offset = 0
    pos = 1
    if separated or not filter_header:
        coeff_offset = struct.unpack_from(">H", payload, pos)[0]
        pos += 2
    return FrameHeader(
        keyframe=False,
        quantizer=quantizer,
        separated_coeff=separated,
        coeff_offset=coeff_offset,
        data_start=pos,
    )
