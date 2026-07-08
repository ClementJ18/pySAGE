"""Decoding-coverage report: how much of a save this reader actually understands.

A `.sav` is a flat sequence of chunks; `sage_save.chunks.CHUNK_CODECS` decodes some of them,
each leaving a known amount of its payload as opaque `bytes`. `chunk_coverage` classifies every
chunk in a save — decoded / partial / opaque — with its decoded-vs-opaque byte split, and
`coverage_summary` rolls that up into the "progress bar for the whole effort": how many of the
save's chunks carry a decoder and what fraction of its bytes are understood. Because the split
is computed from each decoder's own opaque-region accounting, a decoder that silently regresses
to keeping more bytes opaque shows up here as a coverage drop rather than passing unnoticed.
"""

from dataclasses import dataclass

from sage_save.chunks import CHUNK_CODECS
from sage_save.save import SaveFile


@dataclass(frozen=True)
class ChunkCoverage:
    """One chunk's decoding coverage: its payload size and how that splits into understood
    (`decoded_bytes`) and still-raw (`opaque_bytes`) bytes."""

    name: str
    version: int
    size: int
    decoded_bytes: int
    opaque_bytes: int

    @property
    def status(self) -> str:
        """``"opaque"`` (no decoder), ``"partial"`` (decoded but with opaque regions left) or
        ``"decoded"`` (fully understood — nothing kept as raw bytes)."""
        if self.decoded_bytes == 0:
            return "opaque"
        return "decoded" if self.opaque_bytes == 0 else "partial"


def chunk_coverage(save: SaveFile) -> list[ChunkCoverage]:
    """Per-chunk coverage, in file order. A chunk with no registered decoder is wholly opaque;
    a decoded chunk's opaque share is what its `ChunkCodec.opaque_bytes` reports."""
    rows: list[ChunkCoverage] = []
    for chunk in save.chunks:
        size = len(chunk.payload)
        codec = CHUNK_CODECS.get(chunk.name)
        if codec is None:
            rows.append(ChunkCoverage(chunk.name, chunk.version, size, 0, size))
            continue
        opaque = codec.opaque_bytes(codec.decode(chunk))
        rows.append(ChunkCoverage(chunk.name, chunk.version, size, size - opaque, opaque))
    return rows


@dataclass(frozen=True)
class CoverageSummary:
    """The whole-save roll-up of `chunk_coverage`."""

    chunks_total: int
    chunks_decoded: int  # chunks with any decoder (decoded or partial)
    bytes_total: int
    bytes_decoded: int

    @property
    def byte_fraction(self) -> float:
        """Decoded bytes as a fraction of the file's chunk payload (0.0 when the save is empty)."""
        return self.bytes_decoded / self.bytes_total if self.bytes_total else 0.0


def coverage_summary(save: SaveFile) -> CoverageSummary:
    """Roll `chunk_coverage` up into the chunk- and byte-level totals."""
    rows = chunk_coverage(save)
    return CoverageSummary(
        chunks_total=len(rows),
        chunks_decoded=sum(1 for row in rows if row.status != "opaque"),
        bytes_total=sum(row.size for row in rows),
        bytes_decoded=sum(row.decoded_bytes for row in rows),
    )
