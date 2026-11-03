"""The `Xfer` wire-primitive vocabulary that every save `xfer()` method is written in.

`XferReader` is the byte-level layer the typed chunk decoders in `sage_save.chunks` are
built on: a cursor over a chunk payload exposing the primitives from the GPL Generals
`Xfer` base class (`Core/GameEngine/Source/Common/System/Xfer.cpp`) - versioned reads,
little-endian scalars, and the two string encodings (ASCII and UTF-16LE, each with a
uint8 length that escapes to a uint32 for long strings). Only the primitives the current
decoders need are implemented; the format is procedural, so a reader only ever needs the
primitives a given chunk actually calls.

BFME nests composite blocks as `"KOLB" marker + uint32 absolute-end-offset`; `nested_block`
reads that framing and returns the payload-relative end, so an object body can be sliced or
skipped without descending. Absolute offsets are resolved against `base_offset`, the file
position of the payload's first byte.
"""

import io

from sage_save.save import BLOCK_MARKER
from sage_utils.stream import BinaryStream

#: A string length below this rides as one byte; from it up the engine writes this byte and then
#: the length as a uint32 (`XferSave::xferAsciiString` `0x00A1FD80`, `xferUnicodeString`
#: `0x00A1FC7E`).
LONG_STRING_ESCAPE = 0xFF


def _write_string_length(stream: BinaryStream, length: int) -> None:
    if length < LONG_STRING_ESCAPE:
        stream.write_uchar(length)
    else:
        stream.write_uchar(LONG_STRING_ESCAPE)
        stream.write_uint32(length)


def write_ascii_string(stream: BinaryStream, text: str) -> None:
    """Write `text` the way `xferAsciiString` saves it - the inverse of
    `XferReader.ascii_string`."""
    data = text.encode(stream.encoding)
    _write_string_length(stream, len(data))
    stream.write_bytes(data)


def write_unicode_string(stream: BinaryStream, text: str) -> None:
    """Write `text` the way `xferUnicodeString` saves it - the inverse of
    `XferReader.unicode_string`."""
    data = text.encode("utf-16-le")
    _write_string_length(stream, len(data) // 2)
    stream.write_bytes(data)


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
        """The undecoded remainder - used to keep a chunk's tail opaque yet round-trippable."""
        return self._stream.read_bytes(self.remaining())

    def bytes(self, count: int) -> bytes:
        return self._stream.read_bytes(count)

    def version(self, current: int | None = None) -> int:
        """`xferVersion`: a 1-byte version. Loading a version greater than `current` is the
        engine's `XFER_INVALID_VERSION` failure - mirror it so unknown newer layouts surface
        loudly rather than mis-parse."""
        value = self._stream.read_uchar()
        if current is not None and value > current:
            raise ValueError(f"version {value} exceeds supported version {current}")
        return value

    def ubyte(self) -> int:
        return self._stream.read_uchar()

    def byte(self) -> int:
        return self._stream.read_char()

    def bool(self) -> bool:
        return self._stream.read_uchar() != 0

    def uint16(self) -> int:
        return self._stream.read_uint16()

    def int16(self) -> int:
        return self._stream.read_int16()

    def uint32(self) -> int:
        return self._stream.read_uint32()

    def int32(self) -> int:
        return self._stream.read_int32()

    def real(self) -> float:
        return self._stream.read_float()

    def _string_length(self) -> int:
        length = self._stream.read_uchar()
        return self._stream.read_uint32() if length == LONG_STRING_ESCAPE else length

    def ascii_string(self) -> str:
        """`xferAsciiString`: a string length (see `LONG_STRING_ESCAPE`) then that many bytes,
        no NUL."""
        return self._stream.read_bytes(self._string_length()).decode(self._stream.encoding)

    def unicode_string(self) -> str:
        """`xferUnicodeString`: a *character* count (see `LONG_STRING_ESCAPE`) then that many
        UTF-16LE units."""
        return self._stream.read_bytes(self._string_length() * 2).decode("utf-16-le")

    def nested_block(self) -> int:
        """Read a BFME `"KOLB"` block header (marker + absolute end-offset) and return the
        payload-relative offset at which the block ends. The cursor is left at the block body."""
        marker = self._stream.read_bytes(4)
        if marker != BLOCK_MARKER:
            raise ValueError(f"expected {BLOCK_MARKER!r} block marker, got {marker!r}")
        end_absolute = self._stream.read_uint32()
        return end_absolute - self.base_offset
