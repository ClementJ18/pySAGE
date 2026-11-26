"""Reader, decoder and encoder for the EA VP6 movies of Battle for Middle-earth (`.vp6`).

`sage_vp6.container` reads and writes the EA chunk container losslessly and needs nothing
beyond the standard library, so `info`-style tools work anywhere. The codec itself lives in
`sage_vp6.codec` and needs numpy (the `vp6` extra): `Decoder` turns frames into pictures and
handles every VP6 feature BFME's movies use, and `Encoder` turns pictures into a movie the game
plays. `sage-vp6 encode` drives ffmpeg to feed it any video.
"""

from sage_vp6.container import (
    Chunk,
    Frame,
    FrameHeader,
    Movie,
    StreamHeader,
    Vp6FormatError,
    build_movie,
    parse_frame_header,
    read_movie,
    read_movie_from_path,
    write_movie,
)

__all__ = [
    "Chunk",
    "Frame",
    "FrameHeader",
    "Movie",
    "StreamHeader",
    "Vp6FormatError",
    "build_movie",
    "parse_frame_header",
    "read_movie",
    "read_movie_from_path",
    "write_movie",
]
