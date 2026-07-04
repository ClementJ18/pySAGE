"""Little-endian binary stream reader/writer shared by the binary SAGE file formats
(`sage_map`'s `.map`/`.bse` assets, `sage_replay`'s replay files). Mirrors the
BinaryReader/BinaryWriter helper surface of OpenSAGE's C# implementation."""

import io
import struct


class BinaryStream:
    def __init__(self, base_stream: io.BytesIO, encoding: str = "latin-1"):
        self.base_stream = base_stream
        self.encoding = encoding

    def readByte(self) -> bytes:
        return self.base_stream.read(1)

    def writeByte(self, value: int):
        self.base_stream.write(bytes([value]))

    def readBytes(self, length: int) -> bytes:
        return self.base_stream.read(length)

    def writeBytes(self, value: bytes):
        self.base_stream.write(value)

    def readChar(self) -> int:
        return self.unpack("b")

    def writeChar(self, value: bytes):
        self.pack("c", value)

    def readUChar(self) -> int:
        return self.unpack("B")

    def writeUChar(self, value: int):
        self.pack("B", value)

    def readBool(self) -> bool:
        return self.unpack("?")

    def readBoolChecked(self) -> bool:
        value = self.readUChar()
        if value == 0:
            return False
        elif value == 1:
            return True
        else:
            raise ValueError(f"Invalid boolean value: {value}, expected 0 or 1")

    def writeBool(self, value: bool):
        self.pack("?", value)

    def writeBoolChecked(self, value: bool):
        if not isinstance(value, bool):
            raise ValueError(f"Expected boolean value, got: {type(value)}")
        self.writeUChar(1 if value else 0)

    def readBoolUInt32(self) -> bool:
        result = self.readBool()
        unused = self.readUInt24()  # padding

        if unused != 0:
            raise ValueError("Expected padding bytes to be zero")

        return result

    def readBoolUInt32Checked(self) -> bool:
        result = self.readBoolChecked()
        unused = self.readUInt24()  # padding

        if unused != 0:
            raise ValueError(f"Expected padding bytes to be zero, got: {unused:06x}")

        return result

    def writeBoolUInt32(self, value: bool):
        self.writeBool(value)
        self.writeUInt24(0)

    def writeBoolUInt32Checked(self, value: bool):
        self.writeBoolChecked(value)
        self.writeUInt24(0)

    def readInt16(self) -> int:
        return self.unpack("<h", 2)

    def writeInt16(self, value: int):
        self.pack("<h", value)

    def readUInt16(self) -> int:
        return self.unpack("<H", 2)

    def writeUInt16(self, value: int):
        self.pack("<H", value)

    def readInt32(self) -> int:
        return self.unpack("<i", 4)

    def writeInt32(self, value: int):
        self.pack("<i", value)

    def readUInt32(self) -> int:
        return self.unpack("<I", 4)

    def writeUInt32(self, value: int):
        self.pack("<I", value)

    def readInt64(self) -> int:
        return self.unpack("<q", 8)

    def writeInt64(self, value: int):
        self.pack("<q", value)

    def readUInt64(self) -> int:
        return self.unpack("<Q", 8)

    def writeUInt64(self, value: int):
        self.pack("<Q", value)

    # In the C# code this is readSingle()
    def readFloat(self) -> float:
        return self.unpack("<f", 4)

    def writeFloat(self, value: float):
        self.pack("<f", value)

    def readDouble(self) -> float:
        return self.unpack("<d", 8)

    def writeDouble(self, value: float):
        self.pack("<d", value)

    def readVector2(self) -> tuple[float, float]:
        return (self.readFloat(), self.readFloat())

    def writeVector2(self, value: tuple[float, float]):
        self.writeFloat(value[0])
        self.writeFloat(value[1])

    def readVector3(self) -> tuple[float, float, float]:
        return (self.readFloat(), self.readFloat(), self.readFloat())

    def writeVector3(self, value: tuple[float, float, float]):
        self.writeFloat(value[0])
        self.writeFloat(value[1])
        self.writeFloat(value[2])

    def readVector4(self) -> tuple[float, float, float, float]:
        return (self.readFloat(), self.readFloat(), self.readFloat(), self.readFloat())

    def writeVector4(self, value: tuple[float, float, float, float]):
        self.writeFloat(value[0])
        self.writeFloat(value[1])
        self.writeFloat(value[2])
        self.writeFloat(value[3])

    def readString(self) -> str:
        length = self.readUChar()
        return self.unpack(str(length) + "s", length).decode(self.encoding)

    def writeString(self, value: str):
        length = len(value)
        self.writeUChar(length)
        self.pack(str(length) + "s", value.encode(self.encoding))

    def readUInt16PrefixedAsciiString(self) -> str:
        lenght = self.readUInt16()
        return self.readBytes(lenght).decode(self.encoding)

    def writeUInt16PrefixedAsciiString(self, value: str):
        lenght = len(value)
        self.writeUInt16(lenght)
        self.writeBytes(value.encode(self.encoding))

    def readFourCc(self) -> str:
        return self.readBytes(4).decode(self.encoding)

    def writeFourCc(self, value: str):
        if len(value) != 4:
            raise ValueError("FourCC must be exactly 4 characters")
        self.writeBytes(value.encode(self.encoding))

    def readUInt24(self) -> int:
        b = self.readBytes(3)
        return int.from_bytes(b, "little", signed=False)

    def writeUInt24(self, value: int):
        if not (0 <= value <= 0xFFFFFF):
            raise ValueError("Value out of range for UInt24 (0..16777215)")
        b = value.to_bytes(3, "little")
        self.writeBytes(b)

    def readNullTerminatedAsciiString(self) -> str:
        buf = bytearray()
        while True:
            char = self.readBytes(1)
            if not char or char == b"\x00":
                break
            buf.extend(char)
        return buf.decode("ascii", errors="replace")

    def readNullTerminatedUnicodeString(self) -> str:
        """Read UTF-16LE characters (2 bytes each) until a NUL character."""
        buf = bytearray()
        while True:
            char = self.readBytes(2)
            if len(char) < 2 or char == b"\x00\x00":
                break
            buf.extend(char)
        return buf.decode("utf-16-le", errors="replace")

    def readUInt16PrefixedUnicodeString(self) -> str:
        length = self.readUInt16()
        return self.readBytes(length * 2).decode("utf-16-le")

    def writeUInt16PrefixedUnicodeString(self, value: str):
        encoded = value.encode("utf-16-le")
        self.writeUInt16(len(value))
        self.writeBytes(encoded)

    def readUInt16Array2D(self, width: int, height: int) -> list[list[int]]:
        result = [[0] * height for _ in range(width)]
        for y in range(height):
            for x in range(width):
                result[x][y] = self.readUInt16()
        return result

    def writeUInt16Array2D(self, array2d: list[list[int]]):
        width = len(array2d)
        height = len(array2d[0]) if width > 0 else 0
        for y in range(height):
            for x in range(width):
                self.writeUInt16(array2d[x][y])

    def readUIntArray2D(self, width: int, height: int, bit_size: int) -> list[list[int]]:
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
                    value = self.readUInt16()
                elif bit_size == 32:
                    value = self.readUInt32()
                else:
                    raise ValueError(f"Unsupported bit_size: {bit_size}. Expected 16 or 32.")

                result[x][y] = value

        return result

    def readSingleBitBooleanArray2D(
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
                        temp = self.readUChar()

                    result[x][y] = (temp & (1 << (x % 8))) != 0
        else:
            # Bits flow continuously without row alignment
            temp = 0
            bit_index = 0
            for y in range(height):
                for x in range(width):
                    if bit_index % 8 == 0:
                        temp = self.readUChar()

                    result[x][y] = (temp & (1 << (bit_index % 8))) != 0
                    bit_index += 1

            # Note: If we ended mid-byte, remaining bits are padding
            # This is implicit since bits_read will be reset on next read

        return result

    def readByteArray2D(self, width: int, height: int) -> list[list[int]]:
        result = [[0] * height for _ in range(width)]
        for y in range(height):
            for x in range(width):
                result[x][y] = self.readUChar()
        return result

    def readByteArray2DAsEnum(self, width: int, height: int, enum_class):
        result = [[None] * height for _ in range(width)]
        for y in range(height):
            for x in range(width):
                result[x][y] = enum_class(self.readUChar())
        return result

    def writeUIntArray2D(self, array2d: list[list[int]], bit_size: int):
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
                    self.writeUInt16(value)
                elif bit_size == 32:
                    self.writeUInt32(value)
                else:
                    raise ValueError(f"Unsupported bit_size: {bit_size}. Expected 16 or 32.")

    def writeSingleBitBooleanArray2D(
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
                    self.writeUChar(value)
                    value = pad_value if x > width - 8 else 0

                bool_value = array2d[x][y] if x < actual_width else False
                if bool_value:
                    value |= 1 << (x % 8)
                elif pad_value != 0:
                    # When pad_value is non-zero, we need to explicitly clear False bits
                    value &= ~(1 << (x % 8))

            # Write last value
            self.writeUChar(value)

    def writeByteArray2DAsEnum(self, array2d: list[list]):
        """Write a 2D array of enum values as bytes.

        Args:
            array2d: 2D array of enum values
        """
        width = len(array2d)
        height = len(array2d[0]) if width > 0 else 0

        for y in range(height):
            for x in range(width):
                self.writeUChar(int(array2d[x][y]))

    def writeByteArray2D(self, array2d: list[list[int]]):
        """Write a 2D array of bytes.

        Args:
            array2d: 2D array of byte values
        """
        width = len(array2d)
        height = len(array2d[0]) if width > 0 else 0

        for y in range(height):
            for x in range(width):
                self.writeUChar(array2d[x][y])

    def pack(self, fmt, data):
        return self.writeBytes(struct.pack(fmt, data))

    def unpack(self, fmt, length=1):
        return struct.unpack(fmt, self.readBytes(length))[0]

    def seek(self, offset, whence=io.SEEK_SET):
        self.base_stream.seek(offset, whence)

    def tell(self):
        return self.base_stream.tell()

    def getvalue(self):
        return self.base_stream.getvalue()
