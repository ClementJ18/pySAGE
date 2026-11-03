"""The Xfer string encodings: a one-byte length, escaping to `0xFF` + uint32 from 255 up."""

import io

import pytest

from sage_save.xfer import (
    LONG_STRING_ESCAPE,
    XferReader,
    write_ascii_string,
    write_unicode_string,
)
from sage_utils.stream import BinaryStream


def _written(write, text: str) -> bytes:
    stream = BinaryStream(io.BytesIO())
    write(stream, text)
    return stream.getvalue()


@pytest.mark.parametrize("length", [0, 1, 254, 255, 256, 1000])
def test_ascii_string_round_trips(length):
    text = "a" * length
    data = _written(write_ascii_string, text)
    assert XferReader(data).ascii_string() == text
    assert len(data) == length + (1 if length < LONG_STRING_ESCAPE else 5)


@pytest.mark.parametrize("length", [0, 254, 255, 600])
def test_unicode_string_round_trips(length):
    text = "ä" * length
    data = _written(write_unicode_string, text)
    assert XferReader(data).unicode_string() == text
    assert len(data) == 2 * length + (1 if length < LONG_STRING_ESCAPE else 5)


def test_long_string_uses_the_escape_byte_then_a_uint32_length():
    data = _written(write_ascii_string, "x" * 300)
    assert data[:5] == bytes([LONG_STRING_ESCAPE]) + (300).to_bytes(4, "little")
