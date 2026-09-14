"""Heightmap files: WorldBuilder's Export / Import heightmap format, reanchoring a heightmap of
another size, and Open from TGA.

Export heightmap (the handler at `0x006B8E70`) writes every sample as three identical
little-endian 16-bit copies of its height, 6 bytes, rows from the top of the map down: a raw
48-bit RGB image any image editor opens as grey ("Exported as %i x %i pixel raw image.", string
141). Import heightmap (`0x006B8840`) insists the file is exactly the open map's width x height x
6 bytes, refusing any other with "Wrong file size." (139), and keeps the first copy of each
sample. (WorldBuilder's Reanchor Import dialog belongs to the `.scb` partial import, not to
this.) `reanchor` is here for Resize.

Open from TGA's scale is not traced: here an 8-bit grey level is 16 height units (0.625 feet, the
Generals-era height step), and a 16-bit grey image is taken as heights as they are.
"""

from __future__ import annotations

import io
from enum import Enum

import numpy as np

__all__ = [
    "BYTES_PER_SAMPLE",
    "Anchor",
    "export_raw",
    "import_raw",
    "raw_size",
    "reanchor",
    "read_image_heights",
]

BYTES_PER_SAMPLE = 6
# Height units per grey level of an 8-bit image.
_EIGHT_BIT_STEP = 16


class Anchor(Enum):
    """Where a heightmap of another size is pinned: which edge or corner stays in place."""

    TOP_LEFT = (0, 2)
    TOP = (1, 2)
    TOP_RIGHT = (2, 2)
    LEFT = (0, 1)
    CENTER = (1, 1)
    RIGHT = (2, 1)
    BOTTOM_LEFT = (0, 0)
    BOTTOM = (1, 0)
    BOTTOM_RIGHT = (2, 0)

    def offset(self, source: tuple[int, int], target: tuple[int, int]) -> tuple[int, int]:
        """Where the source's bottom-left sample lands in the target, `(dx, dy)` in samples, for
        shapes given as (rows, columns) with rows counted from the bottom."""
        horizontal, vertical = self.value
        dx = (target[1] - source[1]) * horizontal // 2
        dy = (target[0] - source[0]) * vertical // 2
        return dx, dy


def export_raw(heights: np.ndarray) -> bytes:
    """`heights` (`[cell_y, cell_x]` from the bottom-left) in WorldBuilder's export format."""
    top_first = np.ascontiguousarray(heights[::-1].astype("<u2"))
    return np.repeat(top_first[..., None], 3, axis=-1).tobytes()


def raw_size(data: bytes) -> int:
    """The number of samples in an exported heightmap; ValueError when it is not one."""
    if len(data) % BYTES_PER_SAMPLE:
        raise ValueError(f"a heightmap file is 6 bytes a sample; this one is {len(data)} bytes")
    return len(data) // BYTES_PER_SAMPLE


def import_raw(data: bytes, width: int, height: int) -> np.ndarray:
    """The heights in an exported heightmap of `width` x `height` samples, `[cell_y, cell_x]`
    from the bottom-left."""
    if raw_size(data) != width * height:
        raise ValueError(
            f"the file holds {raw_size(data)} samples, not {width} x {height} = {width * height}"
        )
    samples = np.frombuffer(data, dtype="<u2").reshape(height, width, 3)
    return np.ascontiguousarray(samples[::-1, :, 0].astype(np.uint16))


def reanchor(values: np.ndarray, shape: tuple[int, int], anchor: Anchor, fill: int) -> np.ndarray:
    """`values` placed into an array of `shape` at `anchor`, cropped where it is larger and
    `fill` where it is smaller."""
    result = np.full(shape, fill, dtype=values.dtype)
    dx, dy = anchor.offset(values.shape, shape)
    rows, columns = values.shape
    tx0, ty0 = max(dx, 0), max(dy, 0)
    tx1, ty1 = min(dx + columns, shape[1]), min(dy + rows, shape[0])
    if tx0 < tx1 and ty0 < ty1:
        result[ty0:ty1, tx0:tx1] = values[ty0 - dy : ty1 - dy, tx0 - dx : tx1 - dx]
    return result


def read_image_heights(data: bytes) -> np.ndarray:
    """Heights from a grey (or colour, averaged) image such as a TGA, `[cell_y, cell_x]` from the
    bottom-left: an 8-bit level is 16 height units, a 16-bit level one."""
    from PIL import Image  # noqa: PLC0415 - lazy: only needed to open an image

    with Image.open(io.BytesIO(data)) as image:
        if image.mode in ("I;16", "I;16L", "I;16B", "I"):
            levels = np.asarray(image, dtype=np.int64)
            heights = np.clip(levels, 0, 65535)
        else:
            grey = np.asarray(image.convert("L"), dtype=np.int64)
            heights = np.clip(grey * _EIGHT_BIT_STEP, 0, 65535)
    return np.ascontiguousarray(heights[::-1].astype(np.uint16))
