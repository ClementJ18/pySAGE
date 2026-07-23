"""The top-level `.w3d` file: a flat sequence of top-level chunks (mesh, hierarchy, animation,
HLOD, collision box, dazzle, or anything this package does not model, kept raw), plus whatever
comes after the last one (`trailing`) and the diagnostics the parse collected along the way.

`parse_w3d`/`write_w3d` round-trip any input byte-for-byte: a chunk this package cannot model, or
whose typed model does not reproduce its own payload, is kept as `UnknownChunk` (see
`sage_w3d.binary.parse_leaf`/`parse_container` for the mechanism); only input that is not a
chunk stream at all - 1 to 7 bytes (too short to hold even one header), or a first chunk header
overrunning the file - raises `W3DError`. Zero bytes is instead treated as a valid, empty chunk
stream (a handful of real BFME2/RotWK `.w3d` files ship that way)."""

import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sage_w3d.animation import Animation, parse_animation_chunk, write_animation_chunk
from sage_w3d.binary import write_chunk
from sage_w3d.chunks import (
    W3D_CHUNK_ANIMATION,
    W3D_CHUNK_BOX,
    W3D_CHUNK_COMPRESSED_ANIMATION,
    W3D_CHUNK_DAZZLE,
    W3D_CHUNK_HIERARCHY,
    W3D_CHUNK_HLOD,
    W3D_CHUNK_MESH,
    UnknownChunk,
    W3DDiagnostic,
    W3DError,
)
from sage_w3d.compressed_animation import (
    CompressedAnimation,
    parse_compressed_animation_chunk,
    write_compressed_animation_chunk,
)
from sage_w3d.hierarchy import Hierarchy, parse_hierarchy_chunk, write_hierarchy_chunk
from sage_w3d.hlod import HLOD, parse_hlod_chunk, write_hlod_chunk
from sage_w3d.mesh import Mesh, parse_mesh_chunk, write_mesh_chunk
from sage_w3d.objects import (
    CollisionBox,
    Dazzle,
    parse_box_chunk,
    parse_dazzle_chunk,
    write_box_chunk,
    write_dazzle_chunk,
)

__all__ = [
    "W3DChunk",
    "W3DFile",
    "parse_w3d",
    "parse_w3d_from_path",
    "write_w3d",
    "write_w3d_to_path",
]

W3DChunk = (
    Mesh | Hierarchy | Animation | CompressedAnimation | HLOD | CollisionBox | Dazzle | UnknownChunk
)

_TOP_LEVEL_PARSERS = {
    W3D_CHUNK_MESH: parse_mesh_chunk,
    W3D_CHUNK_HIERARCHY: parse_hierarchy_chunk,
    W3D_CHUNK_ANIMATION: parse_animation_chunk,
    W3D_CHUNK_COMPRESSED_ANIMATION: parse_compressed_animation_chunk,
    W3D_CHUNK_HLOD: parse_hlod_chunk,
    W3D_CHUNK_BOX: parse_box_chunk,
    W3D_CHUNK_DAZZLE: parse_dazzle_chunk,
}


@dataclass
class W3DFile:
    """A parsed `.w3d` file: every top-level chunk in file order, any bytes left over after the
    last one, and the diagnostics collected while parsing."""

    chunks: list[W3DChunk] = field(default_factory=list)
    trailing: bytes = b""
    diagnostics: list[W3DDiagnostic] = field(default_factory=list)

    @property
    def meshes(self) -> list[Mesh]:
        return [c for c in self.chunks if isinstance(c, Mesh)]

    @property
    def hierarchy(self) -> Hierarchy | None:
        for c in self.chunks:
            if isinstance(c, Hierarchy):
                return c
        return None

    @property
    def hlod(self) -> HLOD | None:
        for c in self.chunks:
            if isinstance(c, HLOD):
                return c
        return None

    @property
    def animation(self) -> Animation | None:
        for c in self.chunks:
            if isinstance(c, Animation):
                return c
        return None

    @property
    def animations(self) -> list[Animation]:
        return [c for c in self.chunks if isinstance(c, Animation)]

    @property
    def compressed_animation(self) -> CompressedAnimation | None:
        for c in self.chunks:
            if isinstance(c, CompressedAnimation):
                return c
        return None

    @property
    def compressed_animations(self) -> list[CompressedAnimation]:
        return [c for c in self.chunks if isinstance(c, CompressedAnimation)]

    @property
    def boxes(self) -> list[CollisionBox]:
        return [c for c in self.chunks if isinstance(c, CollisionBox)]

    @property
    def dazzles(self) -> list[Dazzle]:
        return [c for c in self.chunks if isinstance(c, Dazzle)]


def _parse_top_level_chunk(
    chunk_type: int,
    flagged: bool,
    payload: bytes,
    header_offset: int,
    diagnostics: list[W3DDiagnostic],
) -> W3DChunk:
    parser = _TOP_LEVEL_PARSERS.get(chunk_type)
    if parser is None:
        # Either a chunk this package deliberately keeps raw (no field model in v1 - see
        # sage_w3d/README.md) or an id it has never seen; both round-trip as-is either way.
        return UnknownChunk(chunk_type=chunk_type, flagged=flagged, data=payload)
    return parser(payload, flagged, header_offset, diagnostics)


def parse_w3d(data: bytes) -> W3DFile:
    # An empty file is a real, shipping asset (a handful of BFME2/RotWK animation stubs are
    # zero bytes) - a degenerate but valid empty chunk stream, not "not a chunk stream at all".
    # Anything from 1 to 7 bytes cannot hold even one header, so that is the genuinely malformed
    # case rule 4 (CONVENTIONS.md) still wants surfaced as a hard error.
    if len(data) == 0:
        return W3DFile()
    if len(data) < 8:
        raise W3DError(f"not a W3D chunk stream: {len(data)} byte(s), need at least 8")

    diagnostics: list[W3DDiagnostic] = []
    chunks: list[W3DChunk] = []
    offset = 0
    n = len(data)
    first = True

    while offset < n:
        if offset + 8 > n:
            break
        chunk_type, raw_size = struct.unpack_from("<II", data, offset)
        size = raw_size & 0x7FFFFFFF
        flagged = bool(raw_size & 0x80000000)
        payload_start = offset + 8
        if payload_start + size > n:
            if first:
                raise W3DError(
                    f"first chunk header at offset 0 (type 0x{chunk_type:08X}) declares a "
                    f"{size}-byte payload, overrunning the {n}-byte file"
                )
            break
        payload = data[payload_start : payload_start + size]
        chunks.append(_parse_top_level_chunk(chunk_type, flagged, payload, offset, diagnostics))
        offset = payload_start + size
        first = False

    trailing = data[offset:]
    if trailing:
        diagnostics.append(
            W3DDiagnostic(
                offset, None, f"{len(trailing)} trailing byte(s) after the last top-level chunk"
            )
        )

    return W3DFile(chunks=chunks, trailing=trailing, diagnostics=diagnostics)


def parse_w3d_from_path(path: str | Path) -> W3DFile:
    with open(path, "rb") as f:
        return parse_w3d(f.read())


_TOP_LEVEL_WRITERS: dict[type, Callable[[Any], bytes]] = {
    Mesh: write_mesh_chunk,
    Hierarchy: write_hierarchy_chunk,
    Animation: write_animation_chunk,
    CompressedAnimation: write_compressed_animation_chunk,
    HLOD: write_hlod_chunk,
    CollisionBox: write_box_chunk,
    Dazzle: write_dazzle_chunk,
}


def _write_top_level_chunk(chunk: W3DChunk) -> bytes:
    if isinstance(chunk, UnknownChunk):
        return write_chunk(chunk.chunk_type, chunk.flagged, chunk.data)
    writer = _TOP_LEVEL_WRITERS.get(type(chunk))
    if writer is None:
        raise TypeError(f"unwritable top-level chunk: {chunk!r}")
    return writer(chunk)


def write_w3d(w3d: W3DFile) -> bytes:
    return b"".join(_write_top_level_chunk(c) for c in w3d.chunks) + w3d.trailing


def write_w3d_to_path(w3d: W3DFile, path: str | Path) -> None:
    data = write_w3d(w3d)
    with open(path, "wb") as f:
        f.write(data)
