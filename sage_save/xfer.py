"""The `Xfer` wire-primitive vocabulary that every save `xfer()` method is written in.

`XferReader` is the byte-level layer the typed chunk decoders in `sage_save.chunks` are
built on: a cursor over a chunk payload exposing the primitives from the GPL Generals
`Xfer` base class (`Core/GameEngine/Source/Common/System/Xfer.cpp`) — versioned reads,
little-endian scalars, and the two string encodings (uint8-length ASCII, uint8-count
UTF-16LE). Only the primitives the current decoders need are implemented; the rest of the
table in sav_format.md is added here as decoding advances (the format is procedural, so a
reader only ever needs the primitives a given chunk actually calls).

BFME nests composite blocks as `"KOLB" marker + uint32 absolute-end-offset`; `nested_block`
reads that framing and returns the payload-relative end, so an object body can be sliced or
skipped without descending. Absolute offsets are resolved against `base_offset`, the file
position of the payload's first byte.
"""

import io

from sage_save.save import BLOCK_MARKER
from sage_utils.stream import BinaryStream


class XferReader:
    def __init__(self, data: bytes, base_offset: int = 0):
        self._data = data
        self._stream = BinaryStream(io.BytesIO(data))
        self.base_offset = base_offset

    def tell(self) -> int:
        return self._stream.tell()

    def remaining(self) -> int:
        return len(self._data) - self._stream.tell()

    def eof(self) -> bool:
        return self.remaining() <= 0

    def skip(self, count: int) -> None:
        self._stream.seek(self._stream.tell() + count)

    def rest(self) -> bytes:
        """The undecoded remainder — used to keep a chunk's tail opaque yet round-trippable."""
        return self._stream.readBytes(self.remaining())

    def bytes(self, count: int) -> bytes:
        return self._stream.readBytes(count)

    def version(self, current: int | None = None) -> int:
        """`xferVersion`: a 1-byte version. Loading a version greater than `current` is the
        engine's `XFER_INVALID_VERSION` failure — mirror it so unknown newer layouts surface
        loudly rather than mis-parse."""
        value = self._stream.readUChar()
        if current is not None and value > current:
            raise ValueError(f"version {value} exceeds supported version {current}")
        return value

    def ubyte(self) -> int:
        return self._stream.readUChar()

    def byte(self) -> int:
        return self._stream.readChar()

    def bool(self) -> bool:
        return self._stream.readUChar() != 0

    def uint16(self) -> int:
        return self._stream.readUInt16()

    def int16(self) -> int:
        return self._stream.readInt16()

    def uint32(self) -> int:
        return self._stream.readUInt32()

    def int32(self) -> int:
        return self._stream.readInt32()

    def real(self) -> float:
        return self._stream.readFloat()

    def ascii_string(self) -> str:
        """`xferAsciiString`: uint8 length then that many bytes, no NUL."""
        return self._stream.readString()

    def unicode_string(self) -> str:
        """`xferUnicodeString`: uint8 *character* count then that many UTF-16LE units."""
        count = self._stream.readUChar()
        return self._stream.readBytes(count * 2).decode("utf-16-le")

    def nested_block(self) -> int:
        """Read a BFME `"KOLB"` block header (marker + absolute end-offset) and return the
        payload-relative offset at which the block ends. The cursor is left at the block body."""
        marker = self._stream.readBytes(4)
        if marker != BLOCK_MARKER:
            raise ValueError(f"expected {BLOCK_MARKER!r} block marker, got {marker!r}")
        end_absolute = self._stream.readUInt32()
        return end_absolute - self.base_offset
