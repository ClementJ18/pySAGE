"""Chunk framing and small binary helpers shared by every W3D module: the 8-byte chunk header,
the fixed-width and NUL-terminated string fields that preserve a real exporter's raw bytes, the
routines that split a container's payload into its ordered children, and the leaf self-check
harness that makes the whole-file round trip byte-exact unconditionally (CONVENTIONS.md rule 4):
a chunk whose typed model does not reproduce its own payload is kept as an `UnknownChunk` instead,
with a diagnostic recording why.

`flagged` (bit 31 of the size field) is captured and rewritten verbatim wherever it is read, but
never used to decide how to parse - that decision is always made from the chunk id, because real
exporters do not set the bit consistently for the same id (see `sage_w3d.chunks`)."""

import struct
from collections.abc import Callable
from dataclasses import dataclass

from sage_w3d.chunks import Rgba, UnknownChunk, W3DDiagnostic, chunk_name

__all__ = [
    "ChunkEntry",
    "FixedString",
    "Int32ListChunk",
    "NulString",
    "RgbaListChunk",
    "StringChunk",
    "UInt32ListChunk",
    "Vec2ListChunk",
    "Vec3ListChunk",
    "all_of",
    "first_of",
    "parse_int32_array",
    "parse_leaf",
    "parse_record_list",
    "parse_uint32_array",
    "parse_vec2_array",
    "parse_vec3_array",
    "split_chunks",
    "split_or_degrade",
    "write_chunk",
    "write_chunk_header",
    "write_int32_array",
    "write_uint32_array",
    "write_vec2_array",
    "write_vec3_array",
]

HEADER_SIZE = 8
# The only exceptions a leaf's parse/write pair is allowed to raise; anything else would be a
# bug in this package rather than malformed input, and should not be silently swallowed.
_PARSE_ERRORS = (struct.error, ValueError, UnicodeDecodeError)


@dataclass(frozen=True)
class FixedString:
    """A fixed-width name field embedded in a larger struct (16 bytes for most names, 32 for a
    collision box or HLOD sub-object identifier). Old exporters never zero-filled the buffer
    past the NUL terminator, so `raw` - not `.value` - is what equality and round-trip compare;
    `.value` decodes latin-1 up to the first NUL."""

    raw: bytes

    @staticmethod
    def from_value(value: str, width: int) -> "FixedString":
        encoded = value.encode("latin-1")
        if len(encoded) >= width:
            raise ValueError(f"{value!r} does not fit in a {width}-byte fixed string")
        return FixedString(raw=encoded.ljust(width, b"\0"))

    @property
    def value(self) -> str:
        nul = self.raw.find(b"\0")
        raw = self.raw if nul < 0 else self.raw[:nul]
        return raw.decode("latin-1")

    def write(self) -> bytes:
        return self.raw


@dataclass(frozen=True)
class NulString:
    """A NUL-terminated string that is an entire leaf chunk's payload on its own (a texture or
    vertex-material name, mapper args, a dazzle field, mesh user text). `raw` is the exact
    payload, including anything after the first NUL a real exporter's leftover buffer left
    behind; `.value` decodes only the part before it."""

    raw: bytes

    @staticmethod
    def from_value(value: str) -> "NulString":
        return NulString(raw=value.encode("latin-1") + b"\0")

    @property
    def value(self) -> str:
        nul = self.raw.find(b"\0")
        raw = self.raw if nul < 0 else self.raw[:nul]
        return raw.decode("latin-1")

    def write(self) -> bytes:
        return self.raw


@dataclass
class StringChunk:
    """A leaf chunk whose entire payload is one `NulString` - the same shape covers mesh user
    text, a vertex material's name and mapper args, a texture's name, and a dazzle's name and
    type name; `chunk_type` says which id this instance is."""

    chunk_type: int
    flagged: bool
    text: NulString

    def write(self) -> bytes:
        return self.text.write()


@dataclass
class Vec3ListChunk:
    """A leaf chunk whose entire payload is a packed array of vec3s - mesh vertices, normals,
    tangents, bitangents, the secondary vertices/normals arrays, or a hierarchy's pivot fixups.
    `chunk_type` says which id this instance is."""

    chunk_type: int
    flagged: bool
    vectors: list[tuple[float, float, float]]

    def write(self) -> bytes:
        return write_vec3_array(self.vectors)


@dataclass
class Vec2ListChunk:
    """A leaf chunk whose entire payload is a packed array of vec2s (texture-stage coordinates,
    at either nesting level they appear at). `chunk_type` says which id this instance is."""

    chunk_type: int
    flagged: bool
    vectors: list[tuple[float, float]]

    def write(self) -> bytes:
        return write_vec2_array(self.vectors)


@dataclass
class Int32ListChunk:
    """A leaf chunk whose entire payload is a packed array of signed 32-bit integers."""

    chunk_type: int
    flagged: bool
    values: list[int]

    def write(self) -> bytes:
        return write_int32_array(self.values)


@dataclass
class UInt32ListChunk:
    """A leaf chunk whose entire payload is a packed array of unsigned 32-bit integers - vertex
    shade indices, AABB-tree poly indices, and the id arrays a material pass or texture stage
    carries. `chunk_type` says which id this instance is."""

    chunk_type: int
    flagged: bool
    values: list[int]

    def write(self) -> bytes:
        return write_uint32_array(self.values)


@dataclass
class RgbaListChunk:
    """A leaf chunk whose entire payload is a packed array of `Rgba` (a material pass's DCG/DIG/
    SCG vertex-color channels). `chunk_type` says which id this instance is."""

    chunk_type: int
    flagged: bool
    colors: list[Rgba]

    def write(self) -> bytes:
        return b"".join(bytes((c.r, c.g, c.b, c.a)) for c in self.colors)


def first_of[T](chunks: list, cls: type[T], chunk_type: int | None = None) -> T | None:
    """The first element of `chunks` that is an instance of `cls` - and, for the generic
    `chunk_type`-tagged wrappers above, whose `chunk_type` matches `chunk_type` - or `None`.
    The convenience property every container dataclass offers for its modeled children."""
    for c in chunks:
        if isinstance(c, cls) and (
            chunk_type is None or getattr(c, "chunk_type", None) == chunk_type
        ):
            return c
    return None


def all_of[T](chunks: list, cls: type[T], chunk_type: int | None = None) -> list[T]:
    """Every element of `chunks` that is an instance of `cls` (and matches `chunk_type`, for the
    tagged wrappers), in order - the list-valued counterpart to `first_of`."""
    return [
        c
        for c in chunks
        if isinstance(c, cls)
        and (chunk_type is None or getattr(c, "chunk_type", None) == chunk_type)
    ]


@dataclass(frozen=True)
class ChunkEntry:
    """One chunk read while splitting a container's payload: its id, its `flagged` bit, its
    payload bytes, and `header_offset` - where its own 8-byte header starts, relative to the
    start of the payload it was split from."""

    chunk_type: int
    flagged: bool
    payload: bytes
    header_offset: int


def split_chunks(payload: bytes) -> list[ChunkEntry] | None:
    """Split `payload` into an ordered list of `ChunkEntry`. Returns `None` if a chunk header is
    truncated (fewer than 8 bytes remain) or its declared payload size overruns what is left -
    `payload` is then not a well-formed chunk sequence at all, and the caller should degrade the
    whole container to raw bytes rather than trust a partial parse."""
    entries: list[ChunkEntry] = []
    offset = 0
    n = len(payload)
    while offset < n:
        if offset + HEADER_SIZE > n:
            return None
        chunk_type, raw_size = struct.unpack_from("<II", payload, offset)
        size = raw_size & 0x7FFFFFFF
        flagged = bool(raw_size & 0x80000000)
        header_offset = offset
        child_start = offset + HEADER_SIZE
        if child_start + size > n:
            return None
        entries.append(
            ChunkEntry(
                chunk_type, flagged, payload[child_start : child_start + size], header_offset
            )
        )
        offset = child_start + size
    return entries


def split_or_degrade(
    chunk_type: int,
    flagged: bool,
    payload: bytes,
    header_offset: int,
    diagnostics: list[W3DDiagnostic],
) -> list[ChunkEntry] | None:
    """`split_chunks(payload)`, appending a degrade diagnostic when it fails so the caller can
    return an `UnknownChunk` for the whole container without having to compose the message
    itself. `header_offset` is this container's own header's absolute file offset."""
    entries = split_chunks(payload)
    if entries is None:
        diagnostics.append(
            W3DDiagnostic(
                header_offset,
                chunk_type,
                f"malformed {chunk_name(chunk_type)} chunk: a sub-chunk header is truncated or "
                "overruns the payload, preserved raw",
            )
        )
    return entries


def write_chunk_header(chunk_type: int, flagged: bool, size: int) -> bytes:
    raw_size = size | (0x80000000 if flagged else 0)
    return struct.pack("<II", chunk_type, raw_size)


def write_chunk(chunk_type: int, flagged: bool, payload: bytes) -> bytes:
    """A full chunk (header + payload), the size field computed from `len(payload)` - never from
    arithmetic over a model's fields, so a stale count can never desync from what is written."""
    return write_chunk_header(chunk_type, flagged, len(payload)) + payload


def parse_leaf[T](
    chunk_type: int,
    flagged: bool,
    payload: bytes,
    header_offset: int,
    parse: Callable[[bytes], T],
    write: Callable[[T], bytes],
    diagnostics: list[W3DDiagnostic],
) -> T | UnknownChunk:
    """Parse `payload` with `parse`, then immediately re-serialize the result with `write` and
    compare it back against `payload`. Anything that keeps that from holding - a `parse` that
    raises on truncated/malformed input, or a model that does not reproduce its own payload
    (a non-canonical field a real exporter wrote that this package does not yet transcribe) -
    degrades to an `UnknownChunk` holding the exact original bytes, with a diagnostic explaining
    why. This is what makes the whole-file round trip byte-exact unconditionally."""
    try:
        model = parse(payload)
        rewritten = write(model)
    except _PARSE_ERRORS as exc:
        diagnostics.append(
            W3DDiagnostic(
                header_offset, chunk_type, f"malformed {chunk_name(chunk_type)} chunk: {exc}"
            )
        )
        return UnknownChunk(chunk_type=chunk_type, flagged=flagged, data=payload)

    if rewritten != payload:
        diagnostics.append(
            W3DDiagnostic(
                header_offset,
                chunk_type,
                f"non-canonical {chunk_name(chunk_type)} chunk preserved as raw bytes",
            )
        )
        return UnknownChunk(chunk_type=chunk_type, flagged=flagged, data=payload)

    return model


def parse_record_list[T](
    payload: bytes, record_size: int, parse_one: Callable[[bytes], T]
) -> list[T]:
    """Parse `payload` as a packed array of fixed-size records - `struct.error` if its length is
    not an exact multiple of `record_size` (a truncated last record), which `parse_leaf` turns
    into a degrade rather than a crash."""
    if record_size <= 0 or len(payload) % record_size != 0:
        raise struct.error(f"payload of {len(payload)} bytes is not a multiple of {record_size}")
    return [parse_one(payload[i : i + record_size]) for i in range(0, len(payload), record_size)]


def parse_vec3_array(payload: bytes) -> list[tuple[float, float, float]]:
    return parse_record_list(payload, 12, lambda b: struct.unpack("<3f", b))


def write_vec3_array(values: list[tuple[float, float, float]]) -> bytes:
    return b"".join(struct.pack("<3f", *v) for v in values)


def parse_vec2_array(payload: bytes) -> list[tuple[float, float]]:
    return parse_record_list(payload, 8, lambda b: struct.unpack("<2f", b))


def write_vec2_array(values: list[tuple[float, float]]) -> bytes:
    return b"".join(struct.pack("<2f", *v) for v in values)


def parse_uint32_array(payload: bytes) -> list[int]:
    return parse_record_list(payload, 4, lambda b: struct.unpack("<I", b)[0])


def write_uint32_array(values: list[int]) -> bytes:
    return b"".join(struct.pack("<I", v) for v in values)


def parse_int32_array(payload: bytes) -> list[int]:
    return parse_record_list(payload, 4, lambda b: struct.unpack("<i", b)[0])


def write_int32_array(values: list[int]) -> bytes:
    return b"".join(struct.pack("<i", v) for v in values)
