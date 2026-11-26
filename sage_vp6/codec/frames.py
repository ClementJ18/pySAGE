"""Pictures in and out of the codec: 8-bit YUV 4:2:0 frames, the YUV4MPEG2 (`.y4m`) stream
format that ffmpeg pipes raw video in, and PNG snapshots of decoded frames.

A `YuvFrame` is in display orientation. VP6 in an EA movie codes the picture bottom row first
and in whole macroblocks; `to_coded` and `from_coded` convert between the two.
"""

import re
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO

import numpy as np
import numpy.typing as npt

__all__ = [
    "Y4mHeader",
    "YuvFrame",
    "from_coded",
    "iter_y4m",
    "png_bytes",
    "to_coded",
    "to_rgb",
]

type Plane = npt.NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class YuvFrame:
    """Planar YUV 4:2:0: `y` is height x width, `u` and `v` half that, rounded up."""

    y: Plane
    u: Plane
    v: Plane

    @property
    def width(self) -> int:
        return int(self.y.shape[1])

    @property
    def height(self) -> int:
        return int(self.y.shape[0])


def _pad(plane: Plane, height: int, width: int) -> Plane:
    rows = min(plane.shape[0], height)
    cols = min(plane.shape[1], width)
    trimmed = plane[:rows, :cols]
    return np.pad(trimmed, ((0, height - rows), (0, width - cols)), mode="edge")


def to_coded(frame: YuvFrame, mb_rows: int, mb_cols: int, flip: bool = True) -> list[Plane]:
    """The three planes as the codec sees them: padded to whole macroblocks by repeating the
    last row and column, and turned bottom-up when `flip`."""
    sizes = ((16 * mb_rows, 16 * mb_cols), (8 * mb_rows, 8 * mb_cols), (8 * mb_rows, 8 * mb_cols))
    planes = [_pad(p, h, w) for p, (h, w) in zip((frame.y, frame.u, frame.v), sizes, strict=True)]
    return [np.ascontiguousarray(p[::-1]) if flip else p for p in planes]


def from_coded(planes: list[Plane], width: int, height: int, flip: bool = True) -> YuvFrame:
    """The display frame of coded planes: the inverse of `to_coded`."""
    if flip:
        planes = [p[::-1] for p in planes]
    chroma_w = (width + 1) // 2
    chroma_h = (height + 1) // 2
    return YuvFrame(
        y=np.ascontiguousarray(planes[0][:height, :width]),
        u=np.ascontiguousarray(planes[1][:chroma_h, :chroma_w]),
        v=np.ascontiguousarray(planes[2][:chroma_h, :chroma_w]),
    )


def to_rgb(frame: YuvFrame) -> npt.NDArray[np.uint8]:
    """Height x width x 3 RGB, from limited-range BT.601 YUV."""
    h, w = frame.height, frame.width
    y = frame.y.astype(np.float64) - 16
    u = np.repeat(np.repeat(frame.u, 2, axis=0), 2, axis=1)[:h, :w].astype(np.float64) - 128
    v = np.repeat(np.repeat(frame.v, 2, axis=0), 2, axis=1)[:h, :w].astype(np.float64) - 128
    r = 1.164 * y + 1.596 * v
    g = 1.164 * y - 0.392 * u - 0.813 * v
    b = 1.164 * y + 2.017 * u
    rgb = np.stack([r, g, b], axis=-1)
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)


def png_bytes(rgb: npt.NDArray[np.uint8]) -> bytes:
    """An 8-bit RGB PNG of a height x width x 3 array."""
    height, width = rgb.shape[:2]
    raw = np.zeros((height, width * 3 + 1), dtype=np.uint8)
    raw[:, 1:] = rgb.reshape(height, width * 3)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw.tobytes(), 6))
        + chunk(b"IEND", b"")
    )


@dataclass(frozen=True, slots=True)
class Y4mHeader:
    width: int
    height: int
    rate: int
    scale: int


_Y4M_MAGIC = b"YUV4MPEG2"


def _read_line(stream: IO[bytes]) -> bytes:
    line = bytearray()
    while True:
        byte = stream.read(1)
        if not byte or byte == b"\n":
            return bytes(line)
        line += byte


def _parse_y4m_header(line: bytes) -> Y4mHeader:
    if not line.startswith(_Y4M_MAGIC):
        raise ValueError("not a YUV4MPEG2 stream")
    fields = {token[:1]: token[1:] for token in line.split()[1:]}
    colour = fields.get(b"C", b"420jpeg")
    if not colour.startswith(b"420"):
        raise ValueError(
            f"y4m colour space {colour.decode()} is not 4:2:0; convert with -pix_fmt yuv420p"
        )
    match = re.fullmatch(rb"(\d+):(\d+)", fields.get(b"F", b"25:1"))
    rate, scale = (int(match[1]), int(match[2])) if match else (25, 1)
    return Y4mHeader(int(fields[b"W"]), int(fields[b"H"]), rate, scale)


def iter_y4m(stream: IO[bytes]) -> tuple[Y4mHeader, Iterator[YuvFrame]]:
    """The header of a YUV4MPEG2 stream and an iterator over its frames."""
    header = _parse_y4m_header(_read_line(stream))
    width, height = header.width, header.height
    chroma_w = (width + 1) // 2
    chroma_h = (height + 1) // 2
    luma_size = width * height
    chroma_size = chroma_w * chroma_h

    def frames() -> Iterator[YuvFrame]:
        while True:
            marker = _read_line(stream)
            if not marker:
                return
            if not marker.startswith(b"FRAME"):
                raise ValueError(f"expected a FRAME marker, got {marker[:16]!r}")
            data = stream.read(luma_size + 2 * chroma_size)
            if len(data) < luma_size + 2 * chroma_size:
                return
            buffer = np.frombuffer(data, dtype=np.uint8)
            yield YuvFrame(
                y=buffer[:luma_size].reshape(height, width),
                u=buffer[luma_size : luma_size + chroma_size].reshape(chroma_h, chroma_w),
                v=buffer[luma_size + chroma_size :].reshape(chroma_h, chroma_w),
            )

    return header, frames()
