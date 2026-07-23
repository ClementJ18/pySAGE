"""The W3D HLOD chunk (`0x00000700`): the level-of-detail and aggregate structure that ties a
hierarchy's bones to the meshes (or collision boxes) rendered at each bone, at each LOD level,
plus the optional aggregate and proxy sub-object arrays. The LOD array, aggregate array, and
proxy array chunks (`0x702`/`0x705`/`0x706`) all share the same inner layout - a header
sub-chunk followed by a run of sub-object records - so one dataclass (`HLODSubObjectArray`)
models all three; `chunk_type` says which."""

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
    W3D_CHUNK_HLOD,
    W3D_CHUNK_HLOD_AGGREGATE_ARRAY,
    W3D_CHUNK_HLOD_HEADER,
    W3D_CHUNK_HLOD_LOD_ARRAY,
    W3D_CHUNK_HLOD_PROXY_ARRAY,
    W3D_CHUNK_HLOD_SUB_OBJECT,
    W3D_CHUNK_HLOD_SUB_OBJECT_ARRAY_HEADER,
    UnknownChunk,
    Version,
    W3DDiagnostic,
)

__all__ = [
    "HLOD",
    "HLODArrayHeader",
    "HLODHeader",
    "HLODSubObject",
    "HLODSubObjectArray",
    "parse_hlod_chunk",
    "write_hlod_chunk",
]

_HLOD_HEADER_FMT = "<2I16s16s"


@dataclass
class HLODHeader:
    flagged: bool
    version: Version
    lod_count: int
    model_name: FixedString
    hierarchy_name: FixedString

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "HLODHeader":
        version_raw, lod_count, model_name, hierarchy_name = struct.unpack(
            _HLOD_HEADER_FMT, payload
        )
        return HLODHeader(
            flagged=flagged,
            version=Version.parse(version_raw),
            lod_count=lod_count,
            model_name=FixedString(raw=model_name),
            hierarchy_name=FixedString(raw=hierarchy_name),
        )

    def write(self) -> bytes:
        return struct.pack(
            _HLOD_HEADER_FMT,
            self.version.encode(),
            self.lod_count,
            self.model_name.raw,
            self.hierarchy_name.raw,
        )


@dataclass
class HLODArrayHeader:
    flagged: bool
    model_count: int
    max_screen_size: float

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "HLODArrayHeader":
        model_count, max_screen_size = struct.unpack("<If", payload)
        return HLODArrayHeader(flagged, model_count, max_screen_size)

    def write(self) -> bytes:
        return struct.pack("<If", self.model_count, self.max_screen_size)


@dataclass
class HLODSubObject:
    flagged: bool
    bone_index: int
    identifier: FixedString

    @staticmethod
    def parse(flagged: bool, payload: bytes) -> "HLODSubObject":
        bone_index, identifier = struct.unpack("<I32s", payload)
        return HLODSubObject(flagged, bone_index, FixedString(raw=identifier))

    def write(self) -> bytes:
        return struct.pack("<I32s", self.bone_index, self.identifier.raw)

    @property
    def name(self) -> str:
        """The part of `identifier` (`container.name`) after the first dot, or the whole thing
        if there is none."""
        return self.identifier.value.split(".", 1)[-1]


HLODSubObjectArrayChunk = HLODArrayHeader | HLODSubObject | UnknownChunk


@dataclass
class HLODSubObjectArray:
    chunk_type: int
    flagged: bool
    chunks: list[HLODSubObjectArrayChunk]

    @property
    def header(self) -> HLODArrayHeader | None:
        return first_of(self.chunks, HLODArrayHeader)

    @property
    def sub_objects(self) -> list[HLODSubObject]:
        return all_of(self.chunks, HLODSubObject)


def _parse_array_child(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_HLOD_SUB_OBJECT_ARRAY_HEADER:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: HLODArrayHeader.parse(entry.flagged, p),
            HLODArrayHeader.write,
            diagnostics,
        )
    if entry.chunk_type == W3D_CHUNK_HLOD_SUB_OBJECT:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: HLODSubObject.parse(entry.flagged, p),
            HLODSubObject.write,
            diagnostics,
        )
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _parse_sub_object_array(entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]):
    header_offset = base_offset + entry.header_offset
    entries = split_or_degrade(
        entry.chunk_type, entry.flagged, entry.payload, header_offset, diagnostics
    )
    if entries is None:
        return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)
    payload_offset = header_offset + 8
    chunks = [_parse_array_child(e, payload_offset, diagnostics) for e in entries]
    return HLODSubObjectArray(chunk_type=entry.chunk_type, flagged=entry.flagged, chunks=chunks)


def _write_array_child(chunk: HLODSubObjectArrayChunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, HLODArrayHeader):
        return write_chunk(W3D_CHUNK_HLOD_SUB_OBJECT_ARRAY_HEADER, chunk.flagged, chunk.write())
    if isinstance(chunk, HLODSubObject):
        return write_chunk(W3D_CHUNK_HLOD_SUB_OBJECT, chunk.flagged, chunk.write())
    raise TypeError(f"unwritable HLOD sub-object array chunk: {chunk!r}")


def _write_sub_object_array(array: HLODSubObjectArray) -> bytes:
    payload = b"".join(_write_array_child(c) for c in array.chunks)
    return write_chunk(array.chunk_type, array.flagged, payload)


HLODChunk = HLODHeader | HLODSubObjectArray | UnknownChunk

_ARRAY_CHUNK_TYPES = (
    W3D_CHUNK_HLOD_LOD_ARRAY,
    W3D_CHUNK_HLOD_AGGREGATE_ARRAY,
    W3D_CHUNK_HLOD_PROXY_ARRAY,
)


@dataclass
class HLOD:
    flagged: bool
    chunks: list[HLODChunk]

    @property
    def header(self) -> HLODHeader | None:
        return first_of(self.chunks, HLODHeader)

    @property
    def model_name(self) -> str:
        h = self.header
        return h.model_name.value if h is not None else ""

    @property
    def hierarchy_name(self) -> str:
        h = self.header
        return h.hierarchy_name.value if h is not None else ""

    @property
    def lod_arrays(self) -> list[HLODSubObjectArray]:
        return all_of(self.chunks, HLODSubObjectArray, W3D_CHUNK_HLOD_LOD_ARRAY)

    @property
    def aggregate_array(self) -> HLODSubObjectArray | None:
        return first_of(self.chunks, HLODSubObjectArray, W3D_CHUNK_HLOD_AGGREGATE_ARRAY)

    @property
    def proxy_array(self) -> HLODSubObjectArray | None:
        return first_of(self.chunks, HLODSubObjectArray, W3D_CHUNK_HLOD_PROXY_ARRAY)


def _parse_hlod_child(
    entry: ChunkEntry, base_offset: int, diagnostics: list[W3DDiagnostic]
) -> HLODChunk:
    header_offset = base_offset + entry.header_offset
    if entry.chunk_type == W3D_CHUNK_HLOD_HEADER:
        return parse_leaf(
            entry.chunk_type,
            entry.flagged,
            entry.payload,
            header_offset,
            lambda p: HLODHeader.parse(entry.flagged, p),
            HLODHeader.write,
            diagnostics,
        )
    if entry.chunk_type in _ARRAY_CHUNK_TYPES:
        return _parse_sub_object_array(entry, base_offset, diagnostics)
    return UnknownChunk(entry.chunk_type, entry.flagged, entry.payload)


def _write_hlod_child(chunk: HLODChunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    if isinstance(chunk, HLODHeader):
        return write_chunk(W3D_CHUNK_HLOD_HEADER, chunk.flagged, chunk.write())
    if isinstance(chunk, HLODSubObjectArray):
        return _write_sub_object_array(chunk)
    raise TypeError(f"unwritable HLOD chunk: {chunk!r}")


def parse_hlod_chunk(
    payload: bytes, flagged: bool, header_offset: int, diagnostics: list[W3DDiagnostic]
):
    entries = split_or_degrade(W3D_CHUNK_HLOD, flagged, payload, header_offset, diagnostics)
    if entries is None:
        return UnknownChunk(W3D_CHUNK_HLOD, flagged, payload)
    payload_offset = header_offset + 8
    chunks = [_parse_hlod_child(e, payload_offset, diagnostics) for e in entries]
    return HLOD(flagged=flagged, chunks=chunks)


def write_hlod_chunk(hlod: HLOD) -> bytes:
    payload = b"".join(_write_hlod_child(c) for c in hlod.chunks)
    return write_chunk(W3D_CHUNK_HLOD, hlod.flagged, payload)
