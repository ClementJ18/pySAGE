"""Two small top-level W3D chunks that don't warrant their own module: the collision box
(`0x00000740`, a leaf) and the dazzle (`0x00000900`, a container wrapping two name strings)."""

import struct
from dataclasses import dataclass

from sage_w3d.binary import (
    ChunkEntry,
    FixedString,
    NulString,
    StringChunk,
    first_of,
    parse_leaf,
    split_or_degrade,
    write_chunk,
)
from sage_w3d.chunks import (
    W3D_CHUNK_BOX,
    W3D_CHUNK_DAZZLE,
    W3D_CHUNK_DAZZLE_NAME,
    W3D_CHUNK_DAZZLE_TYPENAME,
    Rgba,
    UnknownChunk,
    Version,
    W3DDiagnostic,
)

__all__ = [
    "COLLISION_TYPE_MASK",
    "GEOMETRY_TYPE_MASK",
    "CollisionBox",
    "Dazzle",
    "parse_box_chunk",
    "parse_dazzle_chunk",
    "write_box_chunk",
    "write_dazzle_chunk",
]

GEOMETRY_TYPE_MASK = 0xF
COLLISION_TYPE_MASK = 0xFF0

_BOX_FMT = "<II32s4B3f3f"


@dataclass
class CollisionBox:
    """A `BOX` chunk. `flags` is kept whole rather than split into its box-type/collision-type
    sub-fields (`GEOMETRY_TYPE_MASK`/`COLLISION_TYPE_MASK` cover only its low 12 bits) so any
    bits a real exporter set outside those masks still round-trip."""

    flagged: bool
    version: Version
    flags: int
    name: FixedString
    color: Rgba
    center: tuple[float, float, float]
    extend: tuple[float, float, float]

    @property
    def box_type(self) -> int:
        return self.flags & GEOMETRY_TYPE_MASK

    @property
    def collision_types(self) -> int:
        return self.flags & COLLISION_TYPE_MASK

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "CollisionBox":
        version_raw, flags, name, r, g, b, a, cx, cy, cz, ex, ey, ez = struct.unpack(
            _BOX_FMT, payload
        )
        return CollisionBox(
            flagged=flagged,
            version=Version.parse(version_raw),
            flags=flags,
            name=FixedString(raw=name),
            color=Rgba(r, g, b, a),
            center=(cx, cy, cz),
            extend=(ex, ey, ez),
        )

    def write(self) -> bytes:
        return struct.pack(
            _BOX_FMT,
            self.version.encode(),
            self.flags,
            self.name.raw,
            self.color.r,
            self.color.g,
            self.color.b,
            self.color.a,
            *self.center,
            *self.extend,
        )


def parse_box_chunk(
    payload: bytes, flagged: bool, header_offset: int, diagnostics: list[W3DDiagnostic]
):
    return parse_leaf(
        W3D_CHUNK_BOX,
        flagged,
        payload,
        header_offset,
        lambda p: CollisionBox.parse(flagged, p),
        CollisionBox.write,
        diagnostics,
    )


def write_box_chunk(box: CollisionBox) -> bytes:
    return write_chunk(W3D_CHUNK_BOX, box.flagged, box.write())


DazzleChunk = StringChunk | UnknownChunk


@dataclass
class Dazzle:
    flagged: bool
    chunks: list[DazzleChunk]

    @property
    def name(self) -> str | None:
        c = first_of(self.chunks, StringChunk, W3D_CHUNK_DAZZLE_NAME)
        return c.text.value if c is not None else None

    @property
    def type_name(self) -> str | None:
        c = first_of(self.chunks, StringChunk, W3D_CHUNK_DAZZLE_TYPENAME)
        return c.text.value if c is not None else None


def _parse_dazzle_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
) -> DazzleChunk:
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type in (W3D_CHUNK_DAZZLE_NAME, W3D_CHUNK_DAZZLE_TYPENAME):
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: StringChunk(entry.chunk_type, entry.flagged, NulString(raw=p)),
            StringChunk.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _write_dazzle_child(chunk: DazzleChunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    return write_chunk(chunk.chunk_type, chunk.flagged, chunk.text.write())


def parse_dazzle_chunk(
    payload: bytes, flagged: bool, header_offset: int, diagnostics: list[W3DDiagnostic]
):
    entries = split_or_degrade(W3D_CHUNK_DAZZLE, flagged, payload, header_offset, diagnostics)
    if entries is None:
        return UnknownChunk(W3D_CHUNK_DAZZLE, flagged, payload)
    payload_offset = header_offset + 8
    chunks = [_parse_dazzle_child(e, payload_offset, diagnostics) for e in entries]
    return Dazzle(flagged=flagged, chunks=chunks)


def write_dazzle_chunk(dazzle: Dazzle) -> bytes:
    payload = b"".join(_write_dazzle_child(c) for c in dazzle.chunks)
    return write_chunk(W3D_CHUNK_DAZZLE, dazzle.flagged, payload)
