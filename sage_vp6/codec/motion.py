"""Motion-compensated prediction of one 8x8 block from a reference plane.

A vector is in quarter pixels for luma and eighth pixels for chroma. Whole-pixel vectors copy;
fractional ones interpolate, bilinearly or (luma, when the stream asks) with VP6's 4-tap
filters. Reads past the plane edge repeat its border pixels. When the stream deblocks, the
reference area is loop-filtered across the 8-pixel grid line it straddles before interpolating;
the reference frame itself is left untouched.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sage_vp6.tables import BLOCK_COPY_FILTER, FILTER_THRESHOLD

__all__ = ["MotionFilter", "predict_block"]

type IntArray = npt.NDArray[np.int64]


def _bounding_values(limit: int) -> IntArray:
    """The loop filter's response curve, indexed by `filter_value + 128`."""
    table = [0] * 256
    for x in range(limit):
        table[128 + x] = x
        table[128 - x] = -x
    value = limit
    x = limit
    while x < 128 and value:
        table[128 + x] = value
        table[128 - x] = -value
        x += 1
        value -= 1
    # Index -128 lies outside the reference decoder's table; no sane stream reaches it.
    table[0] = 0
    return np.array(table, dtype=np.int64)


_BOUNDING = [_bounding_values(limit) for limit in FILTER_THRESHOLD]


@dataclass(frozen=True, slots=True)
class MotionFilter:
    """The interpolation settings of one frame."""

    mode: int = 0
    variance_threshold: int = 0
    max_vector_length: int = 0
    selection: int = 16
    deblock: bool = False
    quantizer: int = 0


def _trunc_div(value: int, divisor: int) -> int:
    quotient = abs(value) // divisor
    return -quotient if value < 0 else quotient


def _window(ref: npt.NDArray[np.uint8], top: int, left: int) -> IntArray:
    rows = np.clip(np.arange(top, top + 16), 0, ref.shape[0] - 1)
    cols = np.clip(np.arange(left, left + 16), 0, ref.shape[1] - 1)
    return ref[np.ix_(rows, cols)].astype(np.int64)


def _loop_filter(area: IntArray, index: int, vertical_edge: bool, bounding: IntArray) -> None:
    """Filter the 12-pixel edge in front of column (or row) `index` of a 12x12 area."""
    lines = area if vertical_edge else area.T
    p0 = lines[:, index - 2].copy()
    p1 = lines[:, index - 1].copy()
    p2 = lines[:, index].copy()
    p3 = lines[:, index + 1].copy()
    value = (p0 - p3) + (p2 - p1) * 3
    delta = bounding[((value + 4) >> 3) + 128]
    lines[:, index - 1] = np.clip(p1 + delta, 0, 255)
    lines[:, index] = np.clip(p2 - delta, 0, 255)


def _taps4(src: IntArray, weights: tuple[int, ...], step_rows: int, step_cols: int) -> IntArray:
    """4-tap filter along one direction over `src`; `src` covers the taps' extent."""
    h = src.shape[0] - 3 * step_rows
    w = src.shape[1] - 3 * step_cols
    total = np.full((h, w), 64, dtype=np.int64)
    for tap, weight in enumerate(weights):
        r = tap * step_rows
        c = tap * step_cols
        total += src[r : r + h, c : c + w] * weight
    return np.clip(total >> 7, 0, 255)


def _bilinear(src: IntArray, x8: int, y8: int, rows: int) -> IntArray:
    a = (8 - x8) * (8 - y8)
    b = x8 * (8 - y8)
    c = (8 - x8) * y8
    d = x8 * y8
    top = src[:rows, :8]
    return (
        a * top + b * src[:rows, 1:9] + c * src[1 : rows + 1, :8] + d * src[1 : rows + 1, 1:9] + 32
    ) >> 6


def _block_variance(win: IntArray, row: int, col: int) -> int:
    samples = win[row : row + 8 : 2, col : col + 8 : 2]
    total = int(samples.sum())
    squares = int((samples * samples).sum())
    return (16 * squares - total * total) >> 8


def predict_block(
    ref: npt.NDArray[np.uint8],
    left: int,
    top: int,
    mv: tuple[int, int],
    divisor: int,
    luma: bool,
    motion: MotionFilter,
) -> IntArray:
    """The 8x8 prediction of the block at (`left`, `top`) of `ref`'s plane, moved by `mv`."""
    mvx, mvy = mv
    mask = divisor - 1
    dx = _trunc_div(mvx, divisor)
    dy = _trunc_div(mvy, divisor)
    # The window's (3, 3) is the whole-pixel source position of the block's corner.
    win = _window(ref, top + dy - 3, left + dx - 3)
    if motion.deblock:
        area = win[1:13, 1:13]
        bounding = _BOUNDING[motion.quantizer]
        if dx & 7:
            _loop_filter(area, 10 - (dx & 7), True, bounding)
        if dy & 7:
            _loop_filter(area, 10 - (dy & 7), False, bounding)

    step_x = (1 if mvx > 0 else -1) if mvx & mask else 0
    step_y = (1 if mvy > 0 else -1) if mvy & mask else 0
    if not step_x and not step_y:
        return win[3:11, 3:11].copy()

    x8 = mvx & mask
    y8 = mvy & mask
    four_tap = 0
    if luma:
        x8 *= 2
        y8 *= 2
        four_tap = motion.mode
        if four_tap == 2:
            longest = motion.max_vector_length
            if longest and (abs(mvx) > longest or abs(mvy) > longest):
                four_tap = 0
            elif (
                motion.variance_threshold and _block_variance(win, 3, 3) < motion.variance_threshold
            ):
                four_tap = 0

    row, col = 3, 3
    if (y8 and step_y < 0) or (not y8 and step_x < 0):
        row, col = 3 + step_y, 3 + step_x
    skew = -1 if (mvx ^ mvy) < 0 else 0

    if four_tap:
        taps = BLOCK_COPY_FILTER[motion.selection]
        if not y8:
            return _taps4(win[row : row + 8, col - 1 : col + 10], taps[x8], 0, 1)
        if not x8:
            return _taps4(win[row - 1 : row + 10, col : col + 8], taps[y8], 1, 0)
        col += skew
        horizontal = _taps4(win[row - 1 : row + 10, col - 1 : col + 10], taps[x8], 0, 1)
        return _taps4(horizontal, taps[y8], 1, 0)

    if not x8 or not y8:
        return _bilinear(win[row : row + 9, col : col + 9], x8, y8, 8)
    col += skew
    horizontal = _bilinear(win[row : row + 10, col : col + 9], x8, 0, 9)
    return _bilinear(np.pad(horizontal, ((0, 0), (0, 1))), 0, y8, 8)
