"""The W3D hierarchy chunk (`0x00000100`): a skeleton definition - named pivots (bones), each
with a parent index and a rest-pose transform, plus an optional fixup-matrix array some
exporters attach."""

import struct
from dataclasses import dataclass

from sage_w3d.binary import (
    ChunkEntry,
    FixedString,
    Vec3ListChunk,
    first_of,
    parse_leaf,
    parse_record_list,
    parse_vec3_array,
    split_or_degrade,
    write_chunk,
    write_vec3_array,
)
from sage_w3d.chunks import (
    W3D_CHUNK_HIERARCHY,
    W3D_CHUNK_HIERARCHY_HEADER,
    W3D_CHUNK_PIVOT_FIXUPS,
    W3D_CHUNK_PIVOTS,
    UnknownChunk,
    Version,
    W3DDiagnostic,
)

__all__ = [
    "Hierarchy",
    "HierarchyHeader",
    "HierarchyPivot",
    "Pivots",
    "parse_hierarchy_chunk",
    "write_hierarchy_chunk",
]

_HIERARCHY_HEADER_FMT = "<I16sI3f"


@dataclass
class HierarchyHeader:
    flagged: bool
    version: Version
    name: FixedString
    num_pivots: int
    center_pos: tuple[float, float, float]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "HierarchyHeader":
        version_raw, name, num_pivots, cx, cy, cz = struct.unpack(_HIERARCHY_HEADER_FMT, payload)
        return HierarchyHeader(
            flagged=flagged,
            version=Version.parse(version_raw),
            name=FixedString(raw=name),
            num_pivots=num_pivots,
            center_pos=(cx, cy, cz),
        )

    def write(self) -> bytes:
        return struct.pack(
            _HIERARCHY_HEADER_FMT,
            self.version.encode(),
            self.name.raw,
            self.num_pivots,
            *self.center_pos,
        )


@dataclass
class HierarchyPivot:
    """One bone: its name, its parent's index into the same pivot array (-1 for a root), and its
    rest-pose transform (translation, Euler angles, and the equivalent rotation quaternion -
    the exporter writes both)."""

    name: FixedString
    parent_id: int
    translation: tuple[float, float, float]
    euler_angles: tuple[float, float, float]
    rotation: tuple[float, float, float, float]

    @staticmethod
    def parse(data: bytes) -> "HierarchyPivot":
        name, parent_id, tx, ty, tz, ex, ey, ez, rx, ry, rz, rw = struct.unpack("<16si3f3f4f", data)
        return HierarchyPivot(
            name=FixedString(raw=name),
            parent_id=parent_id,
            translation=(tx, ty, tz),
            euler_angles=(ex, ey, ez),
            rotation=(rx, ry, rz, rw),
        )

    def write(self) -> bytes:
        return struct.pack(
            "<16si3f3f4f",
            self.name.raw,
            self.parent_id,
            *self.translation,
            *self.euler_angles,
            *self.rotation,
        )


@dataclass
class Pivots:
    flagged: bool
    pivots: list[HierarchyPivot]

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "Pivots":
        return Pivots(flagged=flagged, pivots=parse_record_list(payload, 60, HierarchyPivot.parse))

    def write(self) -> bytes:
        return b"".join(p.write() for p in self.pivots)


HierarchyChunk = HierarchyHeader | Pivots | Vec3ListChunk | UnknownChunk


@dataclass
class Hierarchy:
    flagged: bool
    chunks: list[HierarchyChunk]

    @property
    def header(self) -> HierarchyHeader | None:
        return first_of(self.chunks, HierarchyHeader)

    @property
    def name(self) -> str:
        h = self.header
        return h.name.value if h is not None else ""

    @property
    def pivots(self) -> list[HierarchyPivot]:
        c = first_of(self.chunks, Pivots)
        return c.pivots if c is not None else []

    @property
    def pivot_fixups(self) -> list[tuple[float, float, float]]:
        c = first_of(self.chunks, Vec3ListChunk, W3D_CHUNK_PIVOT_FIXUPS)
        return c.vectors if c is not None else []


def _parse_hierarchy_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
) -> HierarchyChunk:
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_HIERARCHY_HEADER:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: HierarchyHeader.parse(entry.flagged, p),
            HierarchyHeader.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_PIVOTS:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: Pivots.parse(entry.flagged, p),
            Pivots.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_PIVOT_FIXUPS:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: Vec3ListChunk(entry.chunk_type, entry.flagged, parse_vec3_array(p)),
            Vec3ListChunk.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _write_hierarchy_child(chunk: HierarchyChunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, HierarchyHeader):
        return write_chunk(W3D_CHUNK_HIERARCHY_HEADER, chunk.flagged, chunk.write())
    if isinstance(chunk, Pivots):
        return write_chunk(W3D_CHUNK_PIVOTS, chunk.flagged, chunk.write())
    if isinstance(chunk, Vec3ListChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, write_vec3_array(chunk.vectors))
    raise TypeError(f"unwritable hierarchy chunk: {chunk!r}")


def parse_hierarchy_chunk(
    payload: bytes, flagged: bool, header_offset: int, diagnostics: list[W3DDiagnostic]
):
    entries = split_or_degrade(W3D_CHUNK_HIERARCHY, flagged, payload, header_offset, diagnostics)
    if entries is None:
        return UnknownChunk(W3D_CHUNK_HIERARCHY, flagged, payload)
    payload_offset = header_offset + 8
    chunks = [_parse_hierarchy_child(e, payload_offset, diagnostics) for e in entries]
    return Hierarchy(flagged=flagged, chunks=chunks)


def write_hierarchy_chunk(hierarchy: Hierarchy) -> bytes:
    payload = b"".join(_write_hierarchy_child(c) for c in hierarchy.chunks)
    return write_chunk(W3D_CHUNK_HIERARCHY, hierarchy.flagged, payload)
