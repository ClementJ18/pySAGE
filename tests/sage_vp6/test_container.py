"""The EA chunk container and the plain frame header: lossless round trips over synthetic
movies, and the errors a malformed file raises."""

import struct

import pytest

from sage_vp6 import (
    Chunk,
    Frame,
    Movie,
    StreamHeader,
    Vp6FormatError,
    build_movie,
    parse_frame_header,
    read_movie,
    write_movie,
)


def _movie() -> Movie:
    frames = [
        Frame(True, b"\x79\x30\x00\x0a\x02\x03\x02\x03abcd"),
        Frame(False, b"\xf9\x00\x05xyz"),
    ]
    return build_movie(frames, width=40, height=30, rate=25)


def test_build_fills_the_header_from_the_frames():
    header = _movie().header
    assert header == StreamHeader(b"vp60", 40, 30, 2, 12, 25, 1)
    assert header.fps == 25


def test_round_trips_byte_for_byte():
    data = write_movie(_movie())
    assert write_movie(read_movie(data)) == data


def test_frames_split_colour_from_alpha():
    header = StreamHeader(b"vp60", 8, 8, 1, 3, 30, 1).pack()
    movie = Movie(
        (
            Chunk(b"AVP6", b""),
            Chunk(b"MVhd", header),
            Chunk(b"AVhd", header),
            Chunk(b"AV0K", b"alp"),
            Chunk(b"MV0K", b"col"),
        )
    )
    movie = read_movie(write_movie(movie))
    assert movie.has_alpha
    assert movie.alpha_header == movie.header
    assert [f.payload for f in movie.frames()] == [b"col"]
    assert [f.payload for f in movie.frames(alpha=True)] == [b"alp"]


def test_chunk_size_counts_its_header():
    data = write_movie(_movie())
    (size,) = struct.unpack_from("<I", data, 4)
    assert size == 8 + 24


@pytest.mark.parametrize(
    "data",
    [
        b"MVhd\x04\x00\x00\x00",  # a size smaller than the chunk header
        b"MVhd\x40\x00\x00\x00" + bytes(24),  # a size past the end of the file
        b"MV0K\x09\x00\x00\x00x",  # no stream header at all
        b"MVhd",  # truncated chunk header
    ],
)
def test_malformed_movies_raise(data):
    with pytest.raises(Vp6FormatError):
        read_movie(data)


def test_keyframe_header():
    header = parse_frame_header(bytes([0x79, 0x30, 0x00, 0x81, 0x24, 0x2D, 0x24, 0x2D, 0, 0]))
    assert header.keyframe
    assert header.quantizer == 60
    assert header.separated_coeff
    assert header.sub_version == 6
    assert header.filter_header == 0
    assert header.coeff_offset == 0x81
    assert (header.mb_rows, header.mb_cols) == (36, 45)
    assert header.data_start == 8


def test_filtered_keyframe_without_separate_coefficients_has_no_offset():
    header = parse_frame_header(bytes([0x78, 0x3E, 14, 14, 14, 14, 0, 0]))
    assert header.sub_version == 7
    assert header.filter_header == 6
    assert header.coeff_offset == 0
    assert header.data_start == 6


def test_inter_frame_header():
    header = parse_frame_header(bytes([0xD5, 0x01, 0x05, 0, 0]))
    assert not header.keyframe
    assert header.quantizer == 42
    assert header.coeff_offset == 0x105
    assert header.data_start == 3
    assert header.sub_version is None


def test_alpha_movie_layout_matches_eas():
    colour = [Frame(True, b"c0"), Frame(False, b"c1-long")]
    alpha = [Frame(True, b"a0"), Frame(False, b"a1")]
    movie = read_movie(write_movie(build_movie(colour, 64, 48, 982027, 32767, alpha)))
    tags = [chunk.tag for chunk in movie.chunks]
    assert tags == [b"AVP6", b"MVhd", b"AVhd", b"AV0K", b"MV0K", b"AV0F", b"MV0F"]
    assert movie.alpha_header == movie.header
    assert movie.header.largest_frame == len(b"c1-long") + 8
    assert [f.payload for f in movie.frames(alpha=True)] == [b"a0", b"a1"]


def test_alpha_needs_a_frame_per_colour_frame():
    with pytest.raises(ValueError, match="alpha frames"):
        build_movie([Frame(True, b"c")], 8, 8, 25, alpha=[])
