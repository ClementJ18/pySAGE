"""Container-level reader/writer for SAGE `.sav` save games (BFME-era).

A save file is a serialized engine snapshot: a 16-byte file header followed by a flat
sequence of named, self-delimiting chunks, terminated by the ASCII token ``SG_EOF``.
Each chunk is ``ascii-name + "KOLB" marker + uint32 end-offset + payload``, where the
end-offset is the *absolute* file position at which the chunk ends (so the payload runs
from just after the offset field up to that position). This mirrors the Generals
``XferSave`` block framing, with the BFME addition of a per-block ``BLOK`` fourCC (stored
little-endian, so it reads ``KOLB``) and an absolute end-offset instead of a relative size.

Walking the top level never descends into a payload, so a save round-trips as bytes even
though the deep per-object state is not understood. The typed decoders for individual
chunks live in `sage_save.chunks`; here every payload is opaque.
"""

import io
from dataclasses import dataclass
from pathlib import Path

from sage_utils.stream import BinaryStream

# The 16-byte file header: two fourCCs stored reversed ("EALA", "RTS2") followed by two
# int32s (observed 1, 0 on a BFME2 skirmish save — the same family as `.cah` hero files).
HEADER_SIZE = 16
MAGIC_EALA = b"ALAE"  # "EALA" little-endian
MAGIC_RTS = b"2STR"  # "RTS2" little-endian

# Per-chunk marker: the fourCC "BLOK" stored little-endian.
BLOCK_MARKER = b"KOLB"

# The bare ASCII string that ends the chunk stream (no marker/offset follows it).
EOF_TOKEN = "SG_EOF"


@dataclass
class SaveHeader:
    """The 16-byte file header. Kept verbatim so a save round-trips exactly."""

    magic_eala: bytes
    magic_rts: bytes
    value1: int
    value2: int

    @property
    def container_id(self) -> str:
        """The human-readable fourCCs, e.g. ``"EALA RTS2"``."""
        return f"{self.magic_eala[::-1].decode('latin-1')} {self.magic_rts[::-1].decode('latin-1')}"


@dataclass
class Chunk:
    """One top-level chunk: its registered name and its opaque payload bytes.

    `offset` is the file position of the chunk's name-length byte, kept for reporting.
    Every payload begins with a 1-byte version (`version`); the rest is decoded lazily by
    `sage_save.chunks` on the chunks that are understood.
    """

    name: str
    payload: bytes
    offset: int

    @property
    def version(self) -> int:
        """The leading version byte every chunk payload carries."""
        return self.payload[0] if self.payload else -1

    @property
    def payload_offset(self) -> int:
        """The absolute file position of the payload's first byte (past the name, `KOLB`
        marker and end-offset field). Nested blocks store *absolute* end-offsets, so a
        decoder resolves them against this base."""
        return self.offset + 1 + len(self.name) + len(BLOCK_MARKER) + 4


@dataclass
class SaveFile:
    header: SaveHeader
    chunks: list[Chunk]

    def chunk(self, name: str) -> Chunk | None:
        """The first chunk with this name (case-insensitive, as the engine matches)."""
        lowered = name.lower()
        for chunk in self.chunks:
            if chunk.name.lower() == lowered:
                return chunk
        return None


def parse_save(data: bytes) -> SaveFile:
    """Parse the container of an in-memory `.sav`. Payloads stay opaque; lossless."""
    if len(data) < HEADER_SIZE:
        raise ValueError("file too short to hold a save header")

    stream = BinaryStream(io.BytesIO(data))
    magic_eala = stream.readBytes(4)
    magic_rts = stream.readBytes(4)
    if magic_eala != MAGIC_EALA or magic_rts != MAGIC_RTS:
        raise ValueError(
            f"not a BFME save: header magic is {magic_eala!r} {magic_rts!r}, "
            f"expected {MAGIC_EALA!r} {MAGIC_RTS!r}"
        )
    header = SaveHeader(magic_eala, magic_rts, stream.readInt32(), stream.readInt32())

    chunks: list[Chunk] = []
    size = len(data)
    while True:
        offset = stream.tell()
        if offset >= size:
            raise ValueError("chunk stream ended before the SG_EOF token")
        name = stream.readString()
        if name == EOF_TOKEN:
            break
        marker = stream.readBytes(4)
        if marker != BLOCK_MARKER:
            raise ValueError(
                f"chunk {name!r} at {offset:#x} is missing the {BLOCK_MARKER!r} marker "
                f"(got {marker!r}); this reader handles BFME-era saves only"
            )
        end = stream.readUInt32()
        payload_start = stream.tell()
        if end < payload_start or end > size:
            raise ValueError(
                f"chunk {name!r} at {offset:#x} has an out-of-range end offset {end:#x}"
            )
        payload = stream.readBytes(end - payload_start)
        chunks.append(Chunk(name, payload, offset))

    return SaveFile(header, chunks)


def parse_save_from_path(path: str | Path) -> SaveFile:
    return parse_save(Path(path).read_bytes())


def write_save(save: SaveFile) -> bytes:
    """Serialize a `SaveFile` back to bytes, re-computing the absolute end-offsets."""
    stream = BinaryStream(io.BytesIO())
    stream.writeBytes(save.header.magic_eala)
    stream.writeBytes(save.header.magic_rts)
    stream.writeInt32(save.header.value1)
    stream.writeInt32(save.header.value2)

    for chunk in save.chunks:
        stream.writeString(chunk.name)
        stream.writeBytes(BLOCK_MARKER)
        offset_field = stream.tell()
        stream.writeUInt32(0)  # placeholder, backpatched below
        stream.writeBytes(chunk.payload)
        end = stream.tell()
        stream.seek(offset_field)
        stream.writeUInt32(end)
        stream.seek(end)

    stream.writeString(EOF_TOKEN)
    return stream.getvalue()


def write_save_to_path(save: SaveFile, path: str | Path) -> None:
    Path(path).write_bytes(write_save(save))
