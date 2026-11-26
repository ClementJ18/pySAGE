# sage_vp6

Decoder and encoder for the movies Battle for Middle-earth plays: EA's `.vp6` files, On2 VP6
video in EA's chunked container. Use it to look inside a movie, export its frames, or turn any
video into a movie the game will play.

```
pip install "pysage-tools[vp6]"      # the codec needs numpy; `info` alone needs nothing
```

## Encoding a movie

```
sage-vp6 encode intro.mp4 data/movies/MyIntro.vp6
```

Any input ffmpeg reads works (`.mp4`, `.mkv`, `.mov`, ...); ffmpeg must be on `PATH`, or named
with `--ffmpeg`. A `.y4m` (YUV4MPEG2) file is read directly, with no ffmpeg needed. Options:

| Option | Default | |
| --- | --- | --- |
| `--quality N` | 50 | VP6 quantizer, 0 (smallest file) to 63 (best picture). EA's own movies use 47-60. |
| `--keyframe-interval N` | 120 | At most this many frames between keyframes. A scene cut gets its own keyframe whatever the interval. |
| `--size WxH` | source size | Rescale on the way in (through ffmpeg). |
| `--fps R` | source rate | Resample to this frame rate, e.g. `30` or `30000/1001`. |
| `--alpha MATTE` | | Make an alpha movie: MATTE is a video of the same size and length, white where the picture is opaque. |
| `--premultiply` | | Darken the colour by the input's own alpha channel first, as EA's alpha movies store it. |
| `--ffmpeg PATH` | `ffmpeg` on `PATH` | The ffmpeg executable. |

A `.vp6` holds pictures only, with no sound, so `encode` drops any audio track.

### Alpha movies

The faction flag wipes (`GondorFlag_with_alpha` and friends) are alpha movies. EA stores their
colour premultiplied, so it is black wherever the picture is transparent, and their alpha as a
second VP6 stream whose luma is the matte (16 transparent, 235 opaque). From an RGBA master and
its matte:

```
sage-vp6 encode flag_rgba.mov ImladrisFlag_with_alpha.vp6 --alpha flag_matte.mov \
    --premultiply --quality 60 --keyframe-interval 30
```

EA's flag wipes are 640x480 at 29.97 fps, quantizer 60, with a keyframe every 30 or so frames.

Encoding runs in pure Python with numpy: roughly half a second per frame at 960x544, so a
two-minute movie takes around half an hour.

## Inspecting and decoding

```
sage-vp6 info movie.vp6 [--frames] [--json]   # size, frame rate, length, keyframes, codec settings
sage-vp6 frame movie.vp6 still.png --index 120 [--alpha]   # --alpha: the frame's matte
sage-vp6 decode movie.vp6 movie.y4m           # then: ffmpeg -i movie.y4m movie.mp4
```

The decoder handles every VP6 feature BFME's movies use: VP6.0 and VP6.1 streams, 4-tap
motion filtering, the loop filter and Huffman-coded coefficients. Its output matches FFmpeg's
VP6 decoder bit for bit on every frame of the Edain movies checked. `decode` writes an alpha
movie's colour picture; `frame --alpha` gives its matte.

## The format

A `.vp6` file is a flat run of chunks: a 4-byte tag, a little-endian uint32 size counting the
8-byte chunk header, and the payload.

| Chunk | Payload |
| --- | --- |
| `MVhd` | Codec fourcc (`vp60`/`vp61`), uint16 width and height, uint32 frame count, uint32 largest frame payload, uint32 rate and scale (fps = rate / scale; 25/1, or 983019/32767 for 30 fps). |
| `MV0K` | A VP6 keyframe. |
| `MV0F` | A VP6 inter frame. |
| `AVP6`, `AVhd`, `AV0K`, `AV0F` | Alpha movies only: an empty marker, then a second, alpha-only stream interleaved with the colour one. |

EA movies code the picture bottom row first, so the decoder flips what it decodes and the
encoder flips what it writes.

## What the encoder writes

A deliberately plain subset of VP6, chosen to be easy to get exactly right:

- keyframes, and inter frames whose macroblocks either add a residual to the same spot of the
  previous frame or are coded intra, so still and slow scenes stay small;
- one quantizer for the whole movie, no loop filter and range-coded coefficients, with the
  coefficient probabilities fitted to each frame and sent in its header when that pays;
- VP6.1 (sub-version 7) frames. VP6.0's choice of a reduced inverse transform drops one
  coefficient position in some blocks; VP6.1's never does.

There is no motion search yet, so footage with a lot of camera movement comes out bigger than
EA's own encoder would make it, roughly 1.5-2x at the same quality. Every frame is
reconstructed exactly as the decoder rebuilds it, and the next frame predicts from that
reconstruction, so errors never build up. FFmpeg's decoder rebuilds the encoder's output bit
for bit, which checks the encoder against a decoder written independently of this one.

## Library

```python
from sage_vp6 import build_movie, read_movie_from_path, write_movie
from sage_vp6.codec import Decoder, Encoder, EncoderSettings, YuvFrame

movie = read_movie_from_path("ea.vp6")
decoder = Decoder(movie.header.width, movie.header.height)
pictures = [decoder.decode(frame.payload) for frame in movie.frames()]

encoder = Encoder(width, height, EncoderSettings(quality=55))
frames = [encoder.encode(picture) for picture in pictures]  # YuvFrame in, Frame out
data = write_movie(build_movie(frames, width, height, rate=30, scale=1))
```

The container (`sage_vp6.container`) round-trips any `.vp6` byte for byte and needs only the
standard library. The bitstream handling follows FFmpeg's VP6 decoder (`libavcodec/vp6.c`,
`vp56.c`); the tables in `sage_vp6.tables` are the format's own constants.
