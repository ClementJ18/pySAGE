"""Little-endian binary stream reader/writer shared by the binary SAGE file formats
(`sage_map`'s `.map`/`.bse` assets, `sage_replay`'s replay files). Mirrors the
BinaryReader/BinaryWriter helper surface of OpenSAGE's C# implementation."""

import io
import struct

__all__ = [
    "BinaryStream",
]


class BinaryStream:
    def __init__(self, base_stream: io.BytesIO, encoding: str = "latin-1"):
        self.base_stream = base_stream
        self.encoding = encoding

    def read_byte(self) -> bytes:
        return self.base_stream.read(1)

    def write_byte(self, value: int):
        self.base_stream.write(bytes([value]))

    def read_bytes(self, length: int) -> bytes:
        return self.base_stream.read(length)

    def write_bytes(self, value: bytes):
        self.base_stream.write(value)

    def read_char(self) -> int:
        return self.unpack("b")

    def write_char(self, value: bytes):
        self.pack("c", value)

    def read_uchar(self) -> int:
        return self.unpack("B")

    def write_uchar(self, value: int):
        self.pack("B", value)

    def read_bool(self) -> bool:
        return self.unpack("?")

    def read_bool_checked(self) -> bool:
        value = self.read_uchar()
        if value == 0:
            return False
        elif value == 1:
            return True
        else:
            raise ValueError(f"Invalid boolean value: {value}, expected 0 or 1")

    def write_bool(self, value: bool):
        self.pack("?", value)

    def write_bool_checked(self, value: bool):
        if not isinstance(value, bool):
            raise ValueError(f"Expected boolean value, got: {type(value)}")
        self.write_uchar(1 if value else 0)

    def read_bool_uint32(self) -> bool:
        result = self.read_bool()
        unused = self.read_uint24()  # padding

        if unused != 0:
            raise ValueError("Expected padding bytes to be zero")

        return result

    def read_bool_uint32_checked(self) -> bool:
        result = self.read_bool_checked()
        unused = self.read_uint24()  # padding

        if unused != 0:
            raise ValueError(f"Expected padding bytes to be zero, got: {unused:06x}")

        return result

    def write_bool_uint32(self, value: bool):
        self.write_bool(value)
        self.write_uint24(0)

    def write_bool_uint32_checked(self, value: bool):
        self.write_bool_checked(value)
        self.write_uint24(0)

    def read_int16(self) -> int:
        return self.unpack("<h", 2)

    def write_int16(self, value: int):
        self.pack("<h", value)

    def read_uint16(self) -> int:
        return self.unpack("<H", 2)

    def write_uint16(self, value: int):
        self.pack("<H", value)

    def read_int32(self) -> int:
        return self.unpack("<i", 4)

    def write_int32(self, value: int):
        self.pack("<i", value)

    def read_uint32(self) -> int:
        return self.unpack("<I", 4)

    def write_uint32(self, value: int):
        self.pack("<I", value)

    def read_int64(self) -> int:
        return self.unpack("<q", 8)

    def write_int64(self, value: int):
        self.pack("<q", value)

    def read_uint64(self) -> int:
        return self.unpack("<Q", 8)

    def write_uint64(self, value: int):
        self.pack("<Q", value)

    # In the C# code this is readSingle()
    def read_float(self) -> float:
        return self.unpack("<f", 4)

    def write_float(self, value: float):
        self.pack("<f", value)

    def read_double(self) -> float:
        return self.unpack("<d", 8)

    def write_double(self, value: float):
        self.pack("<d", value)

    def read_vector2(self) -> tuple[float, float]:
        return (self.read_float(), self.read_float())

    def write_vector2(self, value: tuple[float, float]):
        self.write_float(value[0])
        self.write_float(value[1])

    def read_vector3(self) -> tuple[float, float, float]:
        return (self.read_float(), self.read_float(), self.read_float())

    def write_vector3(self, value: tuple[float, float, float]):
        self.write_float(value[0])
        self.write_float(value[1])
        self.write_float(value[2])

    def read_vector4(self) -> tuple[float, float, float, float]:
        return (self.read_float(), self.read_float(), self.read_float(), self.read_float())

    def write_vector4(self, value: tuple[float, float, float, float]):
        self.write_float(value[0])
        self.write_float(value[1])
        self.write_float(value[2])
        self.write_float(value[3])

    def read_string(self) -> str:
        length = self.read_uchar()
        return self.unpack(str(length) + "s", length).decode(self.encoding)

    def write_string(self, value: str):
        length = len(value)
        self.write_uchar(length)
        self.pack(str(length) + "s", value.encode(self.encoding))

    def read_uint16_prefixed_ascii_string(self) -> str:
        lenght = self.read_uint16()
        return self.read_bytes(lenght).decode(self.encoding)

    def write_uint16_prefixed_ascii_string(self, value: str):
        lenght = len(value)
        self.write_uint16(lenght)
        self.write_bytes(value.encode(self.encoding))

    def read_fourcc(self) -> str:
        return self.read_bytes(4).decode(self.encoding)

    def write_fourcc(self, value: str):
        if len(value) != 4:
            raise ValueError("FourCC must be exactly 4 characters")
        self.write_bytes(value.encode(self.encoding))

    def read_uint24(self) -> int:
        b = self.read_bytes(3)
        return int.from_bytes(b, "little", signed=False)

    def write_uint24(self, value: int):
        if not (0 <= value <= 0xFFFFFF):
            raise ValueError("Value out of range for UInt24 (0..16777215)")
        b = value.to_bytes(3, "little")
        self.write_bytes(b)

    def read_null_terminated_ascii_string(self) -> str:
        buf = bytearray()
        while True:
            char = self.read_bytes(1)
            if not char or char == b"\x00":
                break
            buf.extend(char)
        return buf.decode("ascii", errors="replace")

    def write_null_terminated_ascii_string(self, value: str):
        self.write_bytes(value.encode("ascii") + b"\x00")

    def read_null_terminated_unicode_string(self) -> str:
        """Read UTF-16LE characters (2 bytes each) until a NUL character."""
        buf = bytearray()
        while True:
            char = self.read_bytes(2)
            if len(char) < 2 or char == b"\x00\x00":
                break
            buf.extend(char)
        return buf.decode("utf-16-le", errors="replace")

    def write_null_terminated_unicode_string(self, value: str):
        self.write_bytes(value.encode("utf-16-le") + b"\x00\x00")

    def read_uint16_prefixed_unicode_string(self) -> str:
        length = self.read_uint16()
        return self.read_bytes(length * 2).decode("utf-16-le")

    def write_uint16_prefixed_unicode_string(self, value: str):
        encoded = value.encode("utf-16-le")
        self.write_uint16(len(value))
        self.write_bytes(encoded)

    def read_uint16_array2d(self, width: int, height: int) -> list[list[int]]:
        result = [[0] * height for _ in range(width)]
        for y in range(height):
            for x in range(width):
                result[x][y] = self.read_uint16()
        return result

    def write_uint16_array2d(self, array2d: list[list[int]]):
        width = len(array2d)
        height = len(array2d[0]) if width > 0 else 0
        for y in range(height):
            for x in range(width):
                self.write_uint16(array2d[x][y])

    def read_uint_array2d(self, width: int, height: int, bit_size: int) -> list[list[int]]:
        """Read a 2D array of unsigned integers.

        Args:
            width: Width of the array
            height: Height of the array
            bit_size: Size in bits (16 or 32) - determines whether to read UInt16 or UInt32
        """
        result = [[0] * height for _ in range(width)]

        for y in range(height):
            for x in range(width):
                if bit_size == 16:
                    value = self.read_uint16()
                elif bit_size == 32:
                    value = self.read_uint32()
                else:
                    raise ValueError(f"Unsupported bit_size: {bit_size}. Expected 16 or 32.")

                result[x][y] = value

        return result

    def read_single_bit_boolean_array2d(
        self, width: int, height: int, row_byte_aligned: bool = True
    ) -> list[list[bool]]:
        """Read a 2D array of single-bit boolean values.

        Args:
            width: Width of the array
            height: Height of the array
            row_byte_aligned: If True (default), each row starts on a byte boundary
                matching C# behavior.
                             If False, bits flow continuously (non-standard).
        """
        result = [[False] * height for _ in range(width)]

        if row_byte_aligned:
            # Each row starts on a fresh byte boundary
            for y in range(height):
                temp = 0
                for x in range(width):
                    if x % 8 == 0:
                        temp = self.read_uchar()

                    result[x][y] = (temp & (1 << (x % 8))) != 0
        else:
            # Bits flow continuously without row alignment
            temp = 0
            bit_index = 0
            for y in range(height):
                for x in range(width):
                    if bit_index % 8 == 0:
                        temp = self.read_uchar()

                    result[x][y] = (temp & (1 << (bit_index % 8))) != 0
                    bit_index += 1

            # Note: If we ended mid-byte, remaining bits are padding
            # This is implicit since bits_read will be reset on next read

        return result

    def read_byte_array2d(self, width: int, height: int) -> list[list[int]]:
        result = [[0] * height for _ in range(width)]
        for y in range(height):
            for x in range(width):
                result[x][y] = self.read_uchar()
        return result

    def read_byte_array2d_as_enum(self, width: int, height: int, enum_class):
        result = [[None] * height for _ in range(width)]
        for y in range(height):
            for x in range(width):
                result[x][y] = enum_class(self.read_uchar())
        return result

    def write_uint_array2d(self, array2d: list[list[int]], bit_size: int):
        """Write a 2D array of unsigned integers.

        Args:
            array2d: 2D array to write
            bit_size: Size in bits (16 or 32) - determines whether to write UInt16 or UInt32
        """
        width = len(array2d)
        height = len(array2d[0]) if width > 0 else 0

        for y in range(height):
            for x in range(width):
                value = array2d[x][y]
                if bit_size == 16:
                    self.write_uint16(value)
                elif bit_size == 32:
                    self.write_uint32(value)
                else:
                    raise ValueError(f"Unsupported bit_size: {bit_size}. Expected 16 or 32.")

    def write_single_bit_boolean_array2d(
        self, array2d: list[list[bool]], width: int | None = None, pad_value: int = 0x0
    ):
        """Write a 2D array of single-bit boolean values.

        Args:
            array2d: 2D boolean array to write
            width: Optional width override (for version 7 passability clipping)
            pad_value: Value to use for padding bits (default 0x0)
        """
        actual_width = len(array2d)
        height = len(array2d[0]) if actual_width > 0 else 0

        if width is None:
            width = actual_width

        for y in range(height):
            value = pad_value if width < 8 else 0
            for x in range(width):
                if x > 0 and x % 8 == 0:
                    self.write_uchar(value)
                    value = pad_value if x > width - 8 else 0

                bool_value = array2d[x][y] if x < actual_width else False
                if bool_value:
                    value |= 1 << (x % 8)
                elif pad_value != 0:
                    # When pad_value is non-zero, we need to explicitly clear False bits
                    value &= ~(1 << (x % 8))

            # Write last value
            self.write_uchar(value)

    def write_byte_array2d_as_enum(self, array2d: list[list]):
        """Write a 2D array of enum values as bytes.

        Args:
            array2d: 2D array of enum values
        """
        width = len(array2d)
        height = len(array2d[0]) if width > 0 else 0

        for y in range(height):
            for x in range(width):
                self.write_uchar(int(array2d[x][y]))

    def write_byte_array2d(self, array2d: list[list[int]]):
        """Write a 2D array of bytes.

        Args:
            array2d: 2D array of byte values
        """
        width = len(array2d)
        height = len(array2d[0]) if width > 0 else 0

        for y in range(height):
            for x in range(width):
                self.write_uchar(array2d[x][y])

    def pack(self, fmt, data):
        return self.write_bytes(struct.pack(fmt, data))

    def unpack(self, fmt, length=1):
        return struct.unpack(fmt, self.read_bytes(length))[0]

    def seek(self, offset, whence=io.SEEK_SET):
        self.base_stream.seek(offset, whence)

    def tell(self):
        return self.base_stream.tell()

    def getvalue(self):
        return self.base_stream.getvalue()
