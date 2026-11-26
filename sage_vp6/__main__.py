"""Command-line entry point: `python -m sage_vp6 <command>` (or `sage-vp6`).

- `info <movie.vp6>` - the stream header (size, frame rate, length), the frame count, keyframes
  and frame sizes, and the codec settings of the first keyframe. `--frames` lists every frame,
  `--json` prints it all machine-readable. Needs no extras.
- `frame <movie.vp6> <out.png>` - decode one frame (`--index`, default 0) to a PNG; `--alpha`
  writes an alpha movie's matte instead.
- `decode <movie.vp6> <out.y4m>` - decode the whole movie to a YUV4MPEG2 stream, which ffmpeg
  and most video tools read (`ffmpeg -i out.y4m out.mp4`).
- `encode <input> <out.vp6>` - encode a video into a BFME movie. A `.y4m` input is read
  directly; anything else (`.mp4`, `.mkv`, ...) is decoded through ffmpeg, which must be on
  PATH. `--quality` (0-63, default 50) trades size for fidelity, `--keyframe-interval` bounds
  how far apart keyframes may be, `--size WxH` rescales and `--fps` resamples on the way in.
  `--alpha MATTE` makes an alpha movie (like the faction flag wipes) from a black-and-white matte
  video, and `--premultiply` darkens the colour by its own alpha channel first, as EA's alpha
  movies store it. `--ffmpeg PATH` names ffmpeg when it is not on PATH.

`frame`, `decode` and `encode` need the `vp6` extra (numpy).
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import IO, TYPE_CHECKING

from sage_utils.cli import existing_file
from sage_vp6.container import (
    Frame,
    Movie,
    Vp6FormatError,
    build_movie,
    parse_frame_header,
    read_movie_from_path,
    write_movie,
)

if TYPE_CHECKING:
    from sage_vp6.codec import EncoderSettings, Y4mHeader

_EXTRA_HINT = 'Install the "vp6" extra: pip install "pysage-tools[vp6]"'


def _codec(command: str) -> ModuleType | None:
    try:
        import sage_vp6.codec as codec  # noqa: PLC0415 - needs the [vp6] extra (numpy)
    except ImportError as exc:
        print(f"{command}: {exc}\n{_EXTRA_HINT}", file=sys.stderr)
        return None
    return codec


def _summary(movie: Movie) -> dict[str, object]:
    header = movie.header
    frames = movie.frames()
    sizes = [len(frame.payload) for frame in frames]
    keyframes = [i for i, frame in enumerate(frames) if frame.keyframe]
    summary: dict[str, object] = {
        "codec": header.codec.decode("latin-1"),
        "width": header.width,
        "height": header.height,
        "fps": round(header.fps, 3),
        "rate": header.rate,
        "scale": header.scale,
        "frame_count": header.frame_count,
        "frames": len(frames),
        "duration_seconds": round(len(frames) / header.fps, 2) if header.fps else None,
        "keyframes": len(keyframes),
        "largest_frame": max(sizes, default=0),
        "average_frame": round(sum(sizes) / len(sizes)) if sizes else 0,
        "alpha": movie.has_alpha,
    }
    if keyframes:
        first = parse_frame_header(frames[keyframes[0]].payload)
        summary["sub_version"] = first.sub_version
        summary["quantizer"] = first.quantizer
        summary["filtered"] = bool(first.filter_header)
    return summary


def _run_info(args: argparse.Namespace) -> int:
    movie = read_movie_from_path(args.movie)
    summary = _summary(movie)
    rows = [
        {"index": i, "keyframe": frame.keyframe, "bytes": len(frame.payload)}
        for i, frame in enumerate(movie.frames())
    ]
    if args.json:
        if args.frames:
            summary["frame_list"] = rows
        print(json.dumps(summary, indent=2))
        return 0
    for key, value in summary.items():
        print(f"{key:>17}: {value}")
    if args.frames:
        for row in rows:
            print(f"{row['index']:6}  {'K' if row['keyframe'] else ' '}  {row['bytes']}")
    return 0


def _run_frame(args: argparse.Namespace) -> int:
    codec = _codec("frame")
    if codec is None:
        return 1
    movie = read_movie_from_path(args.movie)
    if args.alpha and not movie.has_alpha:
        print("frame: the movie has no alpha channel", file=sys.stderr)
        return 1
    frames = movie.frames(alpha=args.alpha)
    if not 0 <= args.index < len(frames):
        print(f"frame: the movie has frames 0-{len(frames) - 1}", file=sys.stderr)
        return 1
    # Inter frames build on what came before, so decode from the keyframe that opens its run.
    start = max(i for i in range(args.index + 1) if frames[i].keyframe)
    decoder = codec.Decoder(movie.header.width, movie.header.height)
    for frame in frames[start : args.index + 1]:
        picture = decoder.decode(frame.payload)
    if args.alpha:
        # The matte as grey: its luma, which runs from 16 (transparent) to 235 (opaque).
        rgb = picture.y[:, :, None].repeat(3, axis=2)
    else:
        rgb = codec.to_rgb(picture)
    args.out.write_bytes(codec.png_bytes(rgb))
    print(f"frame {args.index} -> {args.out}")
    return 0


def _run_decode(args: argparse.Namespace) -> int:
    codec = _codec("decode")
    if codec is None:
        return 1
    movie = read_movie_from_path(args.movie)
    header = movie.header
    decoder = codec.Decoder(header.width, header.height)
    frames = movie.frames()
    with args.out.open("wb") as out:
        out.write(
            f"YUV4MPEG2 W{header.width} H{header.height} F{header.rate}:{header.scale} "
            "Ip A1:1 C420jpeg\n".encode()
        )
        for i, frame in enumerate(frames, 1):
            picture = decoder.decode(frame.payload)
            out.write(b"FRAME\n")
            out.write(picture.y.tobytes() + picture.u.tobytes() + picture.v.tobytes())
            _progress("decode", i, len(frames))
    print(f"{len(frames)} frames -> {args.out}", file=sys.stderr)
    return 0


def _progress(command: str, done: int, total: int | None) -> None:
    if done % 25 and done != total:
        return
    of = f"/{total}" if total else ""
    print(f"\r{command}: frame {done}{of}", end="", file=sys.stderr, flush=True)
    if done == total:
        print(file=sys.stderr)


def _ffmpeg_y4m(ffmpeg: str, source: Path, filters: list[str]) -> subprocess.Popen[bytes]:
    command = [ffmpeg, "-v", "error", "-i", str(source)]
    if filters:
        command += ["-vf", ",".join(filters)]
    command += ["-an", "-pix_fmt", "yuv420p", "-f", "yuv4mpegpipe", "-"]
    return subprocess.Popen(command, stdout=subprocess.PIPE)


def _parse_rate(fps: str) -> tuple[int, int]:
    number, _, denominator = fps.partition("/")
    return int(number), int(denominator or 1)


class _InputError(Exception):
    """An encode input that cannot be read; the message is for the user."""


def _encode_input(
    codec: ModuleType,
    args: argparse.Namespace,
    source: Path,
    settings: "EncoderSettings",
    filters: list[str],
    matte: bool,
) -> tuple["Y4mHeader", list[Frame]]:
    """The y4m header and the encoded frames of one input. A `matte` keeps only its luma, as the
    alpha stream of an alpha movie."""
    process: subprocess.Popen[bytes] | None = None
    stream: IO[bytes]
    if source.suffix.lower() == ".y4m" and not filters:
        stream = source.open("rb")
    else:
        ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
        if ffmpeg is None:
            raise _InputError(
                "ffmpeg is not on PATH; pass --ffmpeg, or convert the video to .y4m yourself"
            )
        process = _ffmpeg_y4m(ffmpeg, source, filters)
        assert process.stdout is not None
        stream = process.stdout
    label = "alpha" if matte else "encode"
    encoded: list[Frame] = []
    try:
        header, pictures = codec.iter_y4m(stream)
        encoder = codec.Encoder(header.width, header.height, settings)
        for picture in pictures:
            if matte:
                neutral = picture.u * 0 + 128
                picture = codec.YuvFrame(picture.y, neutral, neutral)
            encoded.append(encoder.encode(picture))
            _progress(label, len(encoded), None)
        print(file=sys.stderr)
    finally:
        stream.close()
        if process is not None:
            process.wait()
    if process is not None and process.returncode:
        raise _InputError(f"ffmpeg failed on {source} (exit {process.returncode})")
    if not encoded:
        raise _InputError(f"{source} has no frames")
    return header, encoded


def _run_encode(args: argparse.Namespace) -> int:
    codec = _codec("encode")
    if codec is None:
        return 1
    try:
        settings = codec.EncoderSettings(
            quality=args.quality, keyframe_interval=args.keyframe_interval
        )
    except ValueError as exc:
        print(f"encode: {exc}", file=sys.stderr)
        return 1
    shared = []
    if args.size:
        width, _, height = args.size.partition("x")
        shared.append(f"scale={width}:{height}")
    if args.fps:
        shared.append(f"fps={args.fps}")
    colour_filters = (["premultiply=inplace=1"] if args.premultiply else []) + shared

    alpha: list[Frame] | None = None
    try:
        header, encoded = _encode_input(codec, args, args.input, settings, colour_filters, False)
        if args.alpha is not None:
            matte_header, alpha = _encode_input(codec, args, args.alpha, settings, shared, True)
            if (matte_header.width, matte_header.height) != (header.width, header.height):
                raise _InputError("the alpha matte is not the size of the colour video")
            if len(alpha) != len(encoded):
                raise _InputError(
                    f"the colour video has {len(encoded)} frames but the matte {len(alpha)}"
                )
    except _InputError as exc:
        print(f"encode: {exc}", file=sys.stderr)
        return 1
    rate, scale = (header.rate, header.scale) if not args.fps else _parse_rate(args.fps)
    movie = build_movie(encoded, header.width, header.height, rate, scale, alpha)
    args.out.write_bytes(write_movie(movie))
    keyframes = sum(frame.keyframe for frame in encoded)
    size = args.out.stat().st_size
    kind = " with alpha" if alpha is not None else ""
    print(
        f"{len(encoded)} frames{kind} ({keyframes} keyframes), {header.width}x{header.height} "
        f"at {rate / scale:.3f} fps -> {args.out} ({size / 1024:.0f} KiB)"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sage-vp6",
        description="Read, decode and encode the EA VP6 movies of BFME (.vp6).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    info = commands.add_parser("info", help="describe a movie")
    info.add_argument("movie", type=existing_file)
    info.add_argument("--frames", action="store_true", help="list every frame")
    info.add_argument("--json", action="store_true", help="machine-readable output")
    info.set_defaults(run=_run_info)

    frame = commands.add_parser("frame", help="decode one frame to a PNG")
    frame.add_argument("movie", type=existing_file)
    frame.add_argument("out", type=Path)
    frame.add_argument("--index", type=int, default=0, help="frame number (default 0)")
    frame.add_argument("--alpha", action="store_true", help="the frame's alpha matte instead")
    frame.set_defaults(run=_run_frame)

    decode = commands.add_parser("decode", help="decode a movie to a .y4m stream")
    decode.add_argument("movie", type=existing_file)
    decode.add_argument("out", type=Path)
    decode.set_defaults(run=_run_decode)

    encode = commands.add_parser("encode", help="encode a video into a .vp6 movie")
    encode.add_argument("input", type=existing_file, help=".y4m, or any video ffmpeg reads")
    encode.add_argument("out", type=Path)
    encode.add_argument(
        "--quality", type=int, default=50, help="0 (smallest) to 63 (best); default 50"
    )
    encode.add_argument(
        "--keyframe-interval",
        type=int,
        default=120,
        help="at most this many frames between keyframes (default 120)",
    )
    encode.add_argument("--size", help="rescale to WIDTHxHEIGHT (through ffmpeg)")
    encode.add_argument("--fps", help="resample to this frame rate, e.g. 30 or 30000/1001")
    encode.add_argument(
        "--alpha",
        type=existing_file,
        help="a matte video (white opaque, black transparent): makes an alpha movie",
    )
    encode.add_argument(
        "--premultiply",
        action="store_true",
        help="darken the colour by the input's own alpha channel, as EA's alpha movies are",
    )
    encode.add_argument("--ffmpeg", help="the ffmpeg executable, if it is not on PATH")
    encode.set_defaults(run=_run_encode)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.run(args))
    except Vp6FormatError as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
