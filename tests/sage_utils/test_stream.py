"""The shared BinaryStream's null-terminated string readers and writers (the rest of the
reader surface is exercised by the sage_map asset suites)."""

import io

import pytest

from sage_utils.stream import BinaryStream

pytestmark = pytest.mark.full


def stream_of(data: bytes) -> BinaryStream:
    return BinaryStream(io.BytesIO(data))


def test_read_null_terminated_ascii():
    stream = stream_of(b"hello\x00rest")
    assert stream.read_null_terminated_ascii_string() == "hello"
    assert stream.tell() == 6  # consumed the terminator, not the tail


def test_read_null_terminated_ascii_at_eof():
    assert stream_of(b"abc").read_null_terminated_ascii_string() == "abc"


def test_read_null_terminated_unicode():
    data = "Last Replay".encode("utf-16-le") + b"\x00\x00" + b"tail"
    stream = stream_of(data)
    assert stream.read_null_terminated_unicode_string() == "Last Replay"
    assert stream.tell() == len(data) - 4


def test_read_null_terminated_unicode_at_eof():
    assert stream_of("abc".encode("utf-16-le")).read_null_terminated_unicode_string() == "abc"


def test_write_null_terminated_ascii():
    stream = stream_of(b"")
    stream.write_null_terminated_ascii_string("hello")
    assert stream.getvalue() == b"hello\x00"


def test_write_null_terminated_ascii_rejects_non_ascii():
    with pytest.raises(UnicodeEncodeError):
        stream_of(b"").write_null_terminated_ascii_string("héllo")


def test_write_null_terminated_unicode():
    stream = stream_of(b"")
    stream.write_null_terminated_unicode_string("Last Replay")
    assert stream.getvalue() == "Last Replay".encode("utf-16-le") + b"\x00\x00"


def test_null_terminated_write_read_round_trip():
    stream = stream_of(b"")
    stream.write_null_terminated_ascii_string("abc")
    stream.write_null_terminated_unicode_string("déf")
    stream.seek(0)
    assert stream.read_null_terminated_ascii_string() == "abc"
    assert stream.read_null_terminated_unicode_string() == "déf"
